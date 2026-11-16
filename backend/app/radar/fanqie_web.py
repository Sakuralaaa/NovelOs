"""番茄网页版榜单客户端：「阅读榜」+「新书榜」，各有男频 19 个 + 女频 18 个题材榜，每榜最多 100 本。

- 数据接口：fanqienovel.com/api/rank/category/list（rank_list_type=3），匿名可用。
  rankMold=2 → 阅读榜（30 万字以上，页面路径 /rank/{gender}_2_{cid}）；
  rankMold=1 → 新书榜（30 万字以下、未断更，页面路径 /rank/{gender}_1_{cid}）。
  2026-11-16 实测：/rank/1_1_1141 页面内嵌数据与 rankMold=1 返回一致，两者 rankVersion 相同。
- 书名/作者/简介做了 PUA 字体混淆，用 fanqie_charset 还原。
- 每个榜带 rankVersion（每日一个版本号）；同一版本重复刷新内容不变，服务层据此去重。
- 合规：只取公开字段，单次刷新内请求间隔 ≥1s，正常 UA。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.radar.fanqie_charset import CHARSET, CODE_START

log = logging.getLogger("novelos.radar")

API = "https://fanqienovel.com/api/rank/category/list"
RANK_PAGE = "https://fanqienovel.com/rank/1_2_1141"
BOOK_PAGE = "https://fanqienovel.com/page/{book_id}"  # v0.9.1：书页（含 chapterTotal、chapterListWithVolume）
READER_PAGE = "https://fanqienovel.com/reader/{item_id}"
# 榜单类型 → rankMold
BOARD_MOLD: dict[str, int] = {"read": 2, "new": 1}
BOARD_LABEL: dict[str, str] = {"read": "阅读榜", "new": "新书榜"}
WEB_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# 页面解析失败时的兜底题材表（2026-11 实测）
BOARDS: dict[str, list[tuple[str, str]]] = {
    "male": [("1141", "西方奇幻"), ("1140", "东方仙侠"), ("8", "科幻末世"), ("261", "都市日常"), ("124", "都市修真"),
             ("1014", "都市高武"), ("273", "历史古代"), ("27", "战神赘婿"), ("263", "都市种田"), ("258", "传统玄幻"),
             ("272", "历史脑洞"), ("539", "悬疑脑洞"), ("262", "都市脑洞"), ("257", "玄幻脑洞"), ("751", "悬疑灵异"),
             ("504", "抗战谍战"), ("746", "游戏体育"), ("718", "动漫衍生"), ("1016", "男频衍生")],
    "female": [("1139", "古风世情"), ("8", "科幻末世"), ("746", "游戏体育"), ("1015", "女频衍生"), ("248", "玄幻言情"),
               ("23", "种田"), ("79", "年代"), ("267", "现言脑洞"), ("246", "宫斗宅斗"), ("539", "悬疑脑洞"),
               ("253", "古言脑洞"), ("24", "快穿"), ("749", "青春甜宠"), ("745", "星光璀璨"), ("747", "女频悬疑"),
               ("750", "职场婚恋"), ("748", "豪门总裁"), ("1017", "民国言情")],
}


def decode(s: str | None) -> str:
    out = []
    for ch in s or "":
        i = ord(ch) - CODE_START
        out.append(CHARSET[i] if 0 <= i < len(CHARSET) and CHARSET[i] != "?" else ch)
    return "".join(out)


def _int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CHAPTER_NO = re.compile(r"第\s*([0-9０-９]+|[零〇一二两三四五六七八九十百千万]+)\s*[章节回话集]")


def cn_number(s: str) -> int:
    """中文数字转整数：八十 → 80，一千零二十三 → 1023，两百 → 200；全角/半角阿拉伯数字直接转。认不出返回 0。"""
    s = (s or "").strip()
    if not s:
        return 0
    if s.isdigit():
        try:
            return int(s.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
        except ValueError:
            return 0
    if any(ch not in _CN_DIGIT and ch not in _CN_UNIT for ch in s):
        return 0
    if all(ch in _CN_DIGIT for ch in s) and len(s) > 1:  # 一二三 → 123
        return int("".join(str(_CN_DIGIT[ch]) for ch in s))
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch == "万":
            total += (section + num) * 10000
            section, num = 0, 0
        else:
            section += (num or 1) * _CN_UNIT[ch]
            num = 0
    return total + section + num


def chapter_no(title: str | None) -> int:
    """从章节标题里取章号（「第八十章 …」→ 80，「第412章 …」→ 412）。没有章号返回 0。"""
    m = _CHAPTER_NO.search(title or "")
    return cn_number(m.group(1)) if m else 0


def _ts(v: Any) -> datetime | None:
    n = _int(v)
    if n <= 0:
        return None
    if n > 10**11:  # 毫秒
        n //= 1000
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def source_url(book_id: str | None) -> str | None:
    """番茄书页链接；示例数据（非数字 id）没有书页，返回 None。"""
    return BOOK_PAGE.format(book_id=book_id) if book_id and str(book_id).isdigit() else None


def reader_url(item_id: str | None) -> str | None:
    return READER_PAGE.format(item_id=item_id) if item_id and str(item_id).isdigit() else None


def fetch_boards(c: httpx.Client) -> dict[str, list[tuple[str, str]]]:
    try:
        html = c.get(RANK_PAGE).text
        i = html.find("__INITIAL_STATE__=")
        if i >= 0:
            state, _ = json.JSONDecoder().raw_decode(html[i + 18:].replace(":undefined", ":null"))
            lst = (state.get("rank") or {}).get("rankCategoryTypeList") or {}
            boards = {g: [(str(x["id"]), str(x["name"])) for x in lst.get(g) or [] if x.get("id")] for g in ("male", "female")}
            if boards["male"] and boards["female"]:
                return boards
    except Exception as e:  # noqa: BLE001
        log.info("读取题材列表失败，使用内置列表：%s", e)
    return BOARDS


def parse_board(data: dict[str, Any], gender: str, category: str, board: str = "read") -> list[dict[str, Any]]:
    out = []
    for k, r in enumerate((data.get("data") or {}).get("book_list") or [], 1):
        if not isinstance(r, dict) or not r.get("bookName"):
            continue
        title = decode(r.get("bookName"))
        out.append({
            "book_id_ext": str(r.get("bookId") or ""),
            "title": title,
            "author": decode(r.get("author")),
            "category": category,
            "rank": _int(r.get("currentPos")) or k,
            "rank_diff": _int(r.get("rankPosDiff")),
            "read_count": _int(r.get("read_count")) or _int(r.get("readCount")),
            "word_count": _int(r.get("wordNumber")),
            "abstract": re.sub(r"\s+", " ", decode(r.get("abstract"))).strip()[:500],
            "tags": [category, "完结" if str(r.get("creationStatus")) == "0" else "连载"],
            "gender": gender,
            "board": board,
            # v0.9.1
            "cover_url": str(r.get("thumbUri") or r.get("thumbUrl") or "").strip(),
            "first_chapter_id": str(r.get("firstChapterItemId") or ""),
            "last_chapter_id": str(r.get("lastChapterItemId") or ""),
            "last_chapter_title": decode(r.get("lastChapterTitle")).strip()[:120],
            "last_update_at": _ts(r.get("lastChapterUpdateTime")),
            "chapter_count": chapter_no(decode(r.get("lastChapterTitle"))),
        })
    return out


# ---------------------------------------------------------------- v0.9.1：书页详情

def _state_page(html: str) -> dict[str, Any] | None:
    i = html.find("__INITIAL_STATE__=")
    if i < 0:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(html[i + 18:].lstrip().replace(":undefined", ":null"))
    except ValueError:
        return None
    page = state.get("page") if isinstance(state, dict) else None
    return page if isinstance(page, dict) else None


def _chapters_from(v: Any) -> list[dict[str, str]]:
    """chapterListWithVolume：[[{itemId,title,...}, ...], ...]（按卷分组）；也兼容平铺列表。"""
    out: list[dict[str, str]] = []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return out
    if not isinstance(v, list):
        return out
    for vol in v:
        rows = vol if isinstance(vol, list) else [vol]
        for c in rows:
            if isinstance(c, dict) and c.get("itemId"):
                out.append({"title": decode(str(c.get("title") or "")).strip(), "item_id": str(c["itemId"])})
    return out


_RX_TOTAL = re.compile(r'"chapterTotal"\s*:\s*"?(\d+)')
_RX_CHAPTER = re.compile(r'"itemId"\s*:\s*"(\d+)"[^{}]*?"title"\s*:\s*"((?:[^"\\]|\\.)*)"')
_RX_ABSTRACT = re.compile(r'"abstract"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def parse_book_page(html: str) -> dict[str, Any]:
    """解析番茄书页：{chapter_total:int|None, abstract:str, chapters:[{title,item_id}]}。
    先取 window.__INITIAL_STATE__.page，取不到（或字段缺）再用正则兜底；都取不到时字段为空，不抛错。"""
    page = _state_page(html) or {}
    total = _int(page.get("chapterTotal")) or None
    abstract = decode(str(page.get("abstract") or "")).strip()
    chapters = _chapters_from(page.get("chapterListWithVolume"))
    if total is None:
        m = _RX_TOTAL.search(html)
        total = int(m.group(1)) if m else None
    if not chapters:
        seen: set[str] = set()
        for m in _RX_CHAPTER.finditer(html):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                chapters.append({"title": decode(_unescape(m.group(2))).strip(), "item_id": m.group(1)})
    if not abstract:
        m = _RX_ABSTRACT.search(html)
        abstract = decode(_unescape(m.group(1))).strip() if m else ""
    if total is None and chapters:
        total = len(chapters)
    return {"chapter_total": total, "abstract": abstract, "chapters": chapters}


def fetch_book_page(book_id: str, client: httpx.Client | None = None) -> str:
    """取书页 HTML（普通 UA）。非 200 抛 httpx.HTTPStatusError。"""
    s = get_settings()
    own = client is None
    c = client or httpx.Client(timeout=s.radar_timeout, headers={"User-Agent": WEB_UA, "Accept": "text/html,*/*"}, follow_redirects=True)
    try:
        r = c.get(BOOK_PAGE.format(book_id=book_id))
        r.raise_for_status()
        return r.text
    finally:
        if own:
            c.close()


def fetch_rank_lists(per_board: int | None = None, progress=None, boards: list[str] | tuple[str, ...] | None = None
                     ) -> tuple[list[dict[str, Any]], str]:
    """返回（全部条目, 榜单版本号）。boards 默认取配置 radar_boards（阅读榜 + 新书榜）。任何异常向上抛，由调用方回退。"""
    s = get_settings()
    kinds = [b for b in (boards or s.radar_boards) if b in BOARD_MOLD] or ["read"]
    per_board = max(10, min(100, per_board or s.radar_per_board))
    headers = {"User-Agent": WEB_UA, "Accept": "application/json, text/plain, */*", "Referer": "https://fanqienovel.com/rank"}
    items: list[dict[str, Any]] = []
    version = ""
    with httpx.Client(timeout=s.radar_timeout, headers=headers, follow_redirects=True) as c:
        boards = fetch_boards(c)
        todo = [(bk, g, cid, name) for bk in kinds for g in ("male", "female") for cid, name in boards[g]]
        for n, (bk, g, cid, name) in enumerate(todo):
            time.sleep(max(1.0, s.radar_interval_s))
            got: list[dict[str, Any]] = []
            for offset in range(0, per_board, 30):
                r = c.get(API, params={
                    "app_id": 2503, "rank_list_type": 3, "offset": offset, "limit": min(30, per_board - offset),
                    "category_id": cid, "rank_version": version, "gender": 1 if g == "male" else 0, "rankMold": BOARD_MOLD[bk],
                })
                r.raise_for_status()
                data = r.json()
                if data.get("code") not in (0, "0"):
                    raise RuntimeError(f"榜单接口返回 code={data.get('code')}")
                version = version or str((data.get("data") or {}).get("rankVersion") or "")
                page = parse_board(data, g, name, bk)
                got.extend(page)
                if len(page) < 30:
                    break
                time.sleep(max(1.0, s.radar_interval_s))
            items.extend(got[:per_board])
            if progress:
                progress(10 + int(70 * (n + 1) / len(todo)),
                         f"{'男频' if g == 'male' else '女频'}{BOARD_LABEL[bk]} · {name}（{n + 1}/{len(todo)}）")
    if not items:
        raise RuntimeError("榜单接口没有返回数据")
    return items, version
