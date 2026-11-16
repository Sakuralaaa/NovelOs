"""v0.9.1 榜单封面缓存代理。

番茄 thumbUri 是带 x-expires 的签名地址（约 7 天过期，不需要 Referer），所以首次访问时下载存盘：
数据目录 covers/{book_id}.jpg（文件名固定 .jpg，实际格式按文件头识别，番茄有时给 PNG），之后一直用本地文件。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

import httpx
from sqlmodel import select

from app.config import get_settings
from app.db import session_scope
from app.models.tables import RankItem
from app.radar.fanqie_web import WEB_UA

log = logging.getLogger("novelos.radar")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_lock = threading.Lock()
_running = threading.Event()


class CoverError(Exception):
    pass


def covers_dir() -> Path:
    d = get_settings().data_dir / "covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_id(book_id: str) -> str:
    if not _SAFE_ID.match(book_id or ""):
        raise CoverError("书 id 不合法")
    return book_id


def cover_path(book_id: str) -> Path:
    return covers_dir() / f"{safe_id(book_id)}.jpg"


def media_type(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def latest_cover_url(book_id: str) -> str:
    with session_scope() as s:
        row = s.exec(select(RankItem).where(RankItem.book_id_ext == book_id, RankItem.cover_url != "")
                     .order_by(RankItem.id.desc())).first()  # type: ignore[union-attr]
        return row.cover_url if row is not None else ""


def download(url: str, client: httpx.Client | None = None) -> bytes:
    """下载封面：超时 radar_cover_timeout（10 秒），content-type 必须是 image/*，大小上限 radar_cover_max_bytes（2MB）。"""
    st = get_settings()
    if not url.startswith(("http://", "https://")):
        raise CoverError("封面地址不合法")
    own = client is None
    c = client or httpx.Client(timeout=st.radar_cover_timeout, headers={"User-Agent": WEB_UA}, follow_redirects=True)
    try:
        with c.stream("GET", url, timeout=st.radar_cover_timeout) as r:
            if r.status_code != 200:
                raise CoverError(f"封面下载失败：HTTP {r.status_code}")
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                raise CoverError(f"封面不是图片：{ctype or '未知类型'}")
            if int(r.headers.get("content-length") or 0) > st.radar_cover_max_bytes:
                raise CoverError("封面太大")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > st.radar_cover_max_bytes:
                    raise CoverError("封面太大")
            if not buf:
                raise CoverError("封面为空")
            return bytes(buf)
    except httpx.HTTPError as e:
        raise CoverError(f"封面下载失败：{e}") from e
    finally:
        if own:
            c.close()


def _save(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def get_cover(book_id: str) -> tuple[bytes, str]:
    """返回（图片字节, media_type）。本地有缓存直接读；否则用最新条目的 cover_url 下载存盘。失败抛 CoverError。"""
    path = cover_path(book_id)
    if path.is_file() and path.stat().st_size > 0:
        data = path.read_bytes()
        return data, media_type(data)
    url = latest_cover_url(book_id)
    if not url:
        raise CoverError("这本书没有封面地址")
    data = download(url)
    _save(path, data)
    return data, media_type(data)


def prefetch(todo: dict[str, str], interval: float | None = None, sleep=time.sleep) -> dict[str, int]:
    """逐本下载还没缓存的封面；请求间隔取 radar_interval_s 的一半（不低于 0.5 秒）。失败忽略。"""
    st = get_settings()
    gap = max(0.5, st.radar_interval_s / 2) if interval is None else interval
    done = failed = skipped = 0
    with httpx.Client(timeout=st.radar_cover_timeout, headers={"User-Agent": WEB_UA}, follow_redirects=True) as c:
        first = True
        for bid, url in todo.items():
            try:
                path = cover_path(bid)
            except CoverError:
                failed += 1
                continue
            if path.is_file() and path.stat().st_size > 0:
                skipped += 1
                continue
            if not first:
                sleep(gap)
            first = False
            try:
                _save(path, download(url, c))
                done += 1
            except Exception as e:  # noqa: BLE001  预缓存失败不影响任何东西，访问时再试
                failed += 1
                log.debug("预缓存封面失败 %s：%s", bid, e)
    return {"cached": done, "failed": failed, "skipped": skipped}


def prefetch_async(todo: dict[str, str]) -> bool:
    """后台线程预缓存；已有一个在跑时不重复启动。返回是否启动了新线程。"""
    with _lock:
        if _running.is_set():
            return False
        _running.set()

    def run() -> None:
        try:
            r = prefetch(todo)
            log.info("封面预缓存：%s", r)
        except Exception:  # noqa: BLE001
            log.exception("封面预缓存异常")
        finally:
            _running.clear()

    threading.Thread(target=run, name="radar-cover-prefetch", daemon=True).start()
    return True
