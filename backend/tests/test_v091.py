"""v0.9.1：榜单书架字段、封面缓存代理、单书详情、单书 AI 灵感、朱雀 AIGC 检测、语感重塑、版本号。

网络请求全部用 httpx.MockTransport；不做真实抓取、不真实调用朱雀。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import wait_job

FIXTURES = Path(__file__).parent / "fixtures"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG = b"\xff\xd8\xff\xe0" + b"1" * 64
_REAL_CLIENT = httpx.Client


class _Ctx:
    job_id = 0
    book_id = None

    def __init__(self) -> None:
        self.msgs: list[str] = []

    def progress(self, pct: int = 0, message: str = "") -> None:
        self.msgs.append(message)


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    """把 httpx.Client 换成走 MockTransport 的版本（fanqie_web / covers / zhuque 共用同一个 httpx 模块）。"""
    seen: list[httpx.Request] = []
    real = _REAL_CLIENT

    def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: real(*a, transport=httpx.MockTransport(wrapped), **kw))
    return seen


def _add_item(book_id: str, title: str = "测试书", **kw: Any) -> int:
    from app.db import session_scope
    from app.models.tables import RadarSnapshot, RankItem

    with session_scope() as s:
        snap = RadarSnapshot(source="web", items_count=1, version=f"v-{book_id}-{time.time()}")
        s.add(snap)
        s.flush()
        row = RankItem(snapshot_id=snap.id or 0, book_id_ext=book_id, title=title, category=kw.pop("category", "西方奇幻"),
                       abstract=kw.pop("abstract", "穿越到诡异横行的异界，林恩发现自己成了一尊神力枯竭的伪神。"),
                       tags=["西方奇幻", "连载"], gender="male", rank=1, read_count=1000, **kw)
        s.add(row)
        s.commit()
        return row.id or 0


# ================================================================== 1. 书架字段

def test_chapter_number_parsing() -> None:
    from app.radar.fanqie_web import chapter_no, cn_number

    assert chapter_no("第八十章 普拉达，灭亡的国度！") == 80
    assert chapter_no("第412章 “慈祥”的姬璃") == 412
    assert chapter_no("第一千零二十三章 回家") == 1023
    assert chapter_no("第两百章") == 200 and chapter_no("第十章") == 10 and chapter_no("第一百零五章") == 105
    assert chapter_no("第１２章") == 12 and chapter_no("楔子") == 0 and chapter_no("") == 0
    assert cn_number("三万五千") == 35000 and cn_number("abc") == 0


def test_parse_board_shelf_fields() -> None:
    from app.radar import fanqie_web

    payload = {"code": 0, "data": {"book_list": [{
        "bookId": "7654593151348247614", "bookName": "书", "currentPos": 1, "wordNumber": "888717", "read_count": "779455",
        "creationStatus": "1", "thumbUri": "https://p3-reading-sign.fqnovelpic.com/novel-pic/x~tplv-resize:225:0.image?x-expires=1795424680",
        "firstChapterItemId": "7654593184701366846", "lastChapterItemId": "7708383865093505598",
        "lastChapterTitle": "第八十章 普拉达，灭亡的国度！", "lastChapterUpdateTime": "1794748039"}]}}
    it = fanqie_web.parse_board(payload, "male", "西方奇幻")[0]
    assert it["cover_url"].startswith("https://p3-reading-sign") and it["first_chapter_id"] == "7654593184701366846"
    assert it["last_chapter_id"] == "7708383865093505598" and it["chapter_count"] == 80
    assert it["last_chapter_title"] == "第八十章 普拉达，灭亡的国度！"
    assert it["last_update_at"].year == 2026 and it["last_update_at"].tzinfo is not None
    bare = fanqie_web.parse_board({"data": {"book_list": [{"bookId": "1", "bookName": "旧"}]}}, "male", "x")[0]
    assert bare["cover_url"] == "" and bare["chapter_count"] == 0 and bare["last_update_at"] is None


def test_old_db_migration_adds_shelf_and_aigc_columns(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, inspect, text

    from app.db import _add_missing_columns

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:
        c.execute(text('CREATE TABLE rankitem (id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL, book_id_ext VARCHAR NOT NULL, '
                       'title VARCHAR NOT NULL, author VARCHAR NOT NULL DEFAULT "", category VARCHAR NOT NULL DEFAULT "", '
                       'rank INTEGER NOT NULL DEFAULT 0, read_count INTEGER NOT NULL DEFAULT 0, word_count INTEGER NOT NULL DEFAULT 0, '
                       'abstract TEXT NOT NULL DEFAULT "", tags JSON NOT NULL DEFAULT "[]", gender VARCHAR NOT NULL DEFAULT "male")'))
        c.execute(text("INSERT INTO rankitem (snapshot_id, book_id_ext, title) VALUES (1, '42', '旧书')"))
        c.execute(text('CREATE TABLE chapter (id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, number INTEGER NOT NULL, '
                       'content TEXT NOT NULL DEFAULT "")'))
    _add_missing_columns(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("rankitem")}
    assert {"cover_url", "first_chapter_id", "last_chapter_id", "last_chapter_title", "last_update_at", "chapter_count", "board"} <= cols
    assert "aigc" in {c["name"] for c in inspect(eng).get_columns("chapter")}
    with eng.connect() as c:
        row = c.execute(text("SELECT cover_url, chapter_count, last_update_at, board FROM rankitem")).one()
    assert tuple(row) == ("", 0, None, "read")


def test_mock_items_have_shelf_examples() -> None:
    from app.radar.mock_data import mock_items_50, mock_new_items

    for it in mock_items_50()[:5] + mock_new_items()[:5]:
        assert it["chapter_count"] > 0 and it["last_chapter_title"].startswith(f"第{it['chapter_count']}章")
        assert it["cover_url"] == "" and it["last_update_at"] is not None


def test_refresh_stores_fields_and_latest_shape(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from app.radar import covers, service

    started: list[dict[str, str]] = []
    monkeypatch.setattr(covers, "prefetch_async", lambda todo: started.append(todo) or True)
    ts = datetime(2026, 11, 15, 13, 7, 19, tzinfo=timezone.utc)
    rows = [{"book_id_ext": "9001", "title": "封面书", "author": "", "category": "西方奇幻", "rank": 1, "rank_diff": 0, "read_count": 5,
             "word_count": 1, "abstract": "a", "tags": [], "gender": "male", "board": "read", "cover_url": "https://img.test/9001.png",
             "first_chapter_id": "111", "last_chapter_id": "222", "last_chapter_title": "第八十章 x", "last_update_at": ts, "chapter_count": 80},
            {"book_id_ext": "9002", "title": "无封面书", "author": "", "category": "西方奇幻", "rank": 2, "read_count": 4, "word_count": 1,
             "abstract": "b", "tags": [], "gender": "male", "board": "read"}]
    monkeypatch.setattr(service.fanqie_web, "fetch_rank_lists", lambda **k: (rows, f"v091-{time.time()}"))
    monkeypatch.setattr(service, "get_config", lambda s: {"enabled": True, "daily_hour": 8, "auto_report": False})
    r = service.refresh(_Ctx())
    assert not r.get("unchanged") and started == [{"9001": "https://img.test/9001.png"}]  # 只预缓存有封面地址的
    items = {i["book_id_ext"]: i for i in client.get("/api/radar/latest").json()["items"]}
    a, b = items["9001"], items["9002"]
    assert a["cover"] == "/api/radar/cover/9001" and a["source_url"] == "https://fanqienovel.com/page/9001"
    assert a["first_chapter_url"] == "https://fanqienovel.com/reader/111" and a["chapter_count"] == 80
    assert a["last_chapter_title"] == "第八十章 x" and a["last_update_at"].startswith("2026-11-15T13:07:19")
    assert b["cover"] is None and b["first_chapter_url"] is None and b["last_update_at"] is None and b["chapter_count"] == 0
    # 关掉 radar_cache_covers 时不预缓存
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "radar_cache_covers", False)
    started.clear()
    rows[0]["book_id_ext"] = "9003"
    monkeypatch.setattr(service.fanqie_web, "fetch_rank_lists", lambda **k: (rows, f"v091b-{time.time()}"))
    service.refresh(_Ctx())
    assert started == []


# ================================================================== 2. 封面缓存代理

def test_cover_proxy_downloads_caches_and_validates(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.radar import covers

    _add_item("8001", cover_url="https://img.test/8001.image?x-expires=1")
    _add_item("8002", cover_url="https://img.test/html")
    _add_item("8003", cover_url="https://img.test/big")
    _add_item("8004", cover_url="")

    def handler(req: httpx.Request) -> httpx.Response:
        assert "referer" not in req.headers  # 番茄封面不需要 Referer
        if req.url.path == "/8001.image":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        if req.url.path == "/html":
            return httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 10), headers={"content-type": "image/jpeg"})

    seen = _mock_client(monkeypatch, handler)
    r = client.get("/api/radar/cover/8001")
    assert r.status_code == 200, r.text
    assert r.content == PNG and r.headers["content-type"] == "image/png"
    assert "max-age=" in r.headers["cache-control"] and "no-store" not in r.headers["cache-control"]
    assert covers.cover_path("8001").read_bytes() == PNG
    n = len(seen)
    assert client.get("/api/radar/cover/8001").status_code == 200 and len(seen) == n  # 第二次直接读盘
    assert client.get("/api/radar/cover/8002").status_code == 404  # 不是图片
    assert client.get("/api/radar/cover/8003").status_code == 404  # 超过 2MB
    assert not covers.cover_path("8003").exists()
    assert client.get("/api/radar/cover/8004").status_code == 404  # 没有封面地址
    assert client.get("/api/radar/cover/nope-404").status_code == 404
    assert client.get("/api/radar/cover/bad.id").status_code == 404


def test_cover_prefetch_rate_limited_and_ignores_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.radar import covers

    def handler(req: httpx.Request) -> httpx.Response:
        if "fail" in req.url.path:
            return httpx.Response(500)
        return httpx.Response(200, content=JPG, headers={"content-type": "image/jpeg"})

    _mock_client(monkeypatch, handler)
    covers.cover_path("7001").write_bytes(JPG)  # 已缓存 → 跳过
    sleeps: list[float] = []
    monkeypatch.setattr(get_settings(), "radar_interval_s", 3.0)
    r = covers.prefetch({"7001": "https://img.test/a", "7002": "https://img.test/b", "7003": "https://img.test/fail", "../x": "https://img.test/c"},
                        sleep=sleeps.append)
    assert r == {"cached": 1, "failed": 2, "skipped": 1}
    assert sleeps == [1.5] and covers.cover_path("7002").read_bytes() == JPG  # 间隔 = radar_interval_s / 2
    monkeypatch.setattr(get_settings(), "radar_interval_s", 0.2)
    sleeps.clear()
    covers.prefetch({"7004": "https://img.test/d", "7005": "https://img.test/e"}, sleep=sleeps.append)
    assert sleeps == [0.5]  # 不低于 0.5 秒


def test_cover_requires_login_cookie_works_for_img(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.auth import COOKIE_NAME
    from app.config import get_settings
    from app.main import create_app
    from app.radar import covers

    _add_item("6001", cover_url="https://img.test/6001")
    covers.cover_path("6001").write_bytes(JPG)
    monkeypatch.setattr(get_settings(), "auth_disabled", False)
    app = create_app()
    with TestClient(app) as c:
        assert c.get("/api/radar/cover/6001").status_code == 401  # 和其它 /api 一样要登录
        token, _ = app.state.auth.issue(False)
        c.cookies.set(COOKIE_NAME, token)  # 同源 <img> 会自动带登录 Cookie
        r = c.get("/api/radar/cover/6001")
        assert r.status_code == 200 and r.content == JPG and r.headers["content-type"] == "image/jpeg"


# ================================================================== 3. 详情

def test_book_detail_parses_and_caches(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    html = (FIXTURES / "fanqie_book_page_trimmed.html").read_text(encoding="utf-8")
    _add_item("7654593151348247614", title="人在诡异", abstract="榜单里截断的简介", first_chapter_id="7654593184701366846")
    seen = _mock_client(monkeypatch, lambda req: httpx.Response(200, text=html))
    d = client.get("/api/radar/books/7654593151348247614/detail").json()
    assert seen[0].url == "https://fanqienovel.com/page/7654593151348247614" and "Mozilla" in seen[0].headers["user-agent"]
    assert d["detail_error"] is None and d["chapter_total"] == 412 and d["cached"] is False and d["fetched_at"]
    assert d["abstract"].startswith("穿越到诡异横行的异界") and len(d["abstract"]) > 50
    assert len(d["chapters_head"]) == 50 and len(d["chapters_tail"]) == 10
    h0, t9 = d["chapters_head"][0], d["chapters_tail"][-1]
    assert h0["title"].startswith("第1章") and h0["url"] == f"https://fanqienovel.com/reader/{h0['item_id']}"
    assert t9["title"].startswith("第412章")
    assert d["item"]["title"] == "人在诡异" and d["item"]["first_chapter_url"].endswith("7654593184701366846")
    d2 = client.get("/api/radar/books/7654593151348247614/detail").json()
    assert d2["cached"] is True and len(seen) == 1 and d2["chapters_tail"] == d["chapters_tail"]  # 24 小时内不重复抓
    client.get("/api/radar/books/7654593151348247614/detail", params={"refresh": True})
    assert len(seen) == 2


def test_book_detail_regex_fallback_and_errors(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.radar import fanqie_web

    chs = ",".join(f'{{"itemId":"{100 + i}","needPay":0,"title":"第{i}章 标题{i}","volume_name":"一"}}' for i in range(1, 6))
    html = f'<html><script>var x={{"chapterTotal":80,"abstract":"完整\\n简介","list":[{chs}]}}</script></html>'
    p = fanqie_web.parse_book_page(html)
    assert p["chapter_total"] == 80 and p["abstract"] == "完整\n简介" and [c["item_id"] for c in p["chapters"]] == ["101", "102", "103", "104", "105"]
    assert fanqie_web.parse_book_page("<html>改版了</html>") == {"chapter_total": None, "abstract": "", "chapters": []}

    _add_item("5001", title="抓不到的书")
    _mock_client(monkeypatch, lambda req: httpx.Response(503, text="busy"))
    d = client.get("/api/radar/books/5001/detail").json()
    assert d["item"]["title"] == "抓不到的书" and "503" in d["detail_error"] and d["chapters_head"] == [] and d["chapter_total"] is None
    _add_item("5002", title="改版书")
    _mock_client(monkeypatch, lambda req: httpx.Response(200, text="<html>改版了</html>"))
    assert "章节目录" in client.get("/api/radar/books/5002/detail").json()["detail_error"]
    _add_item("mock123", title="示例书")
    d = client.get("/api/radar/books/mock123/detail").json()
    assert d["detail_error"] == "示例数据没有番茄书页" and d["item"]["source_url"] is None
    assert client.get("/api/radar/books/nobook999/detail").status_code == 404


# ================================================================== 4. 单书 AI 灵感

def test_book_ai_kinds_and_defaults(client: TestClient) -> None:
    from app.llm.gateway import TASK_ROLE

    assert TASK_ROLE["radar_book_ai"] == "planner"
    _add_item("4001", title="人在诡异，靠第四天灾登顶至高")
    r = client.post("/api/radar/books/4001/ai", json={"kind": "title"}).json()
    assert r["job_id"] == r["id"]
    res = wait_job(client, r)["result"]
    assert res["kind"] == "title" and len(res["candidates"]) == 5 and res["dropped"] == 0
    assert all(c["title"] and c["why"] for c in res["candidates"])
    cov = wait_job(client, client.post("/api/radar/books/4001/ai", json={"kind": "cover"}).json())["result"]
    assert len(cov["candidates"]) == 3 and all("3:4" in c["prompt"] and c["style"] for c in cov["candidates"])
    bl = wait_job(client, client.post("/api/radar/books/4001/ai", json={"kind": "blurb", "n": 2}).json())["result"]
    assert len(bl["candidates"]) == 2 and all(c["blurb"] and c["hook"] for c in bl["candidates"])
    assert client.post("/api/radar/books/4001/ai", json={"kind": "poster"}).status_code == 422
    assert client.post("/api/radar/books/4001/ai", json={"kind": "title", "n": 50}).status_code == 422
    assert client.post("/api/radar/books/nobook888/ai", json={"kind": "title"}).status_code == 404


def test_book_ai_drops_copies(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import mock

    abstract = "穿越到诡异横行的异界，林恩发现自己成了一尊神力枯竭即将消散的野鸡伪神。"
    _add_item("4002", title="人在诡异靠天灾登顶", abstract=abstract)
    monkeypatch.setitem(mock.HANDLERS, "radar_book_ai", lambda meta: mock._j({"candidates": [
        {"title": "人在诡异靠天灾登顶", "why": "照抄"},
        {"title": "人在诡异：我开了家驾校", "why": "前四字相同"},
        {"title": "退婚当天，我成了城隍爷", "why": "这个可以", "extra": "林恩发现自己成了一尊神力枯竭"},
        {"title": "被逐出师门后，我开了家修仙驾校", "why": "这个也可以"},
    ]}))
    res = wait_job(client, client.post("/api/radar/books/4002/ai", json={"kind": "title", "n": 5}).json())["result"]
    assert [c["title"] for c in res["candidates"]] == ["退婚当天，我成了城隍爷", "被逐出师门后，我开了家修仙驾校"]
    assert res["dropped"] == 2 and len(res["warnings"]) == 2
    monkeypatch.setitem(mock.HANDLERS, "radar_book_ai", lambda meta: mock._j({"candidates": [
        {"blurb": "开头。林恩发现自己成了一尊神力枯竭的伪神，后面不同。", "hook": "抄了简介"}, {"blurb": "她被退婚那天收到一条提示。", "hook": "ok"}]}))
    res = wait_job(client, client.post("/api/radar/books/4002/ai", json={"kind": "blurb"}).json())["result"]
    assert res["dropped"] == 1 and [c["hook"] for c in res["candidates"]] == ["ok"]


def test_new_prompts_listed_and_overridable(client: TestClient) -> None:
    from app.skills import loader

    names = {i["name"] for i in client.get("/api/prompts").json()["items"] if i["kind"] == "prompts"}
    assert {"radar_book_title", "radar_book_cover", "radar_book_blurb", "polish_voice"} <= names
    body = client.get("/api/prompts/prompts/polish_voice").json()["content"]
    for bad in ("反检测", "朱雀", "PPL", "降AI"):
        assert bad not in body
    assert client.put("/api/prompts/prompts/radar_book_title", json={"content": "覆盖 $title $n"}).status_code == 200
    try:
        assert loader.render("radar_book_title", title="甲", n=3) == "覆盖 甲 3"
    finally:
        client.delete("/api/prompts/prompts/radar_book_title")


# ================================================================== 5. 朱雀 AIGC 检测

def _zq_response(text: str, soft: float, ratio: float, labels: dict[str, float], segs: list[dict[str, Any]], tokens: int = 10) -> dict[str, Any]:
    return {"status": "success", "softmax_confidence": soft, "ratio_confidence": ratio, "labels_ratio": labels,
            "segment_labels": segs, "usage": {"total_tokens": tokens}}


@pytest.fixture()
def zq_key(client: TestClient) -> Any:
    r = client.put("/api/settings/zhuque", json={"zhuque_api_key": "sk-test-zhuque-1234"})
    assert r.status_code == 200
    yield
    client.put("/api/settings/zhuque", json={"zhuque_api_key": "", "zhuque_base_url": "", "zhuque_auto_check": False})


def test_zhuque_settings_partial_and_masked(client: TestClient) -> None:
    from app.db import kv_get, session_scope

    d = client.get("/api/settings/zhuque").json()
    assert d["zhuque_configured"] is False and d["zhuque_key_tail"] == "" and d["zhuque_base_url"] == "https://ai-gateway.edgeone.link"
    assert d["zhuque_auto_check"] is False
    d = client.put("/api/settings/zhuque", json={"zhuque_api_key": "sk-secret-abcd9876"}).json()
    assert d["zhuque_configured"] and d["zhuque_key_tail"] == "9876" and "sk-secret" not in json.dumps(d)
    with session_scope() as s:
        assert "sk-secret" not in json.dumps(kv_get(s, "zhuque_settings"))  # 库里是密文
    d = client.put("/api/settings/zhuque", json={"zhuque_base_url": "https://my-gw.example.com/"}).json()
    assert d["zhuque_configured"] and d["zhuque_base_url"] == "https://my-gw.example.com"  # 只改地址，密钥还在
    d = client.put("/api/settings/zhuque", json={"zhuque_auto_check": True}).json()
    assert d["zhuque_auto_check"] and d["zhuque_key_tail"] == "9876" and d["zhuque_base_url"] == "https://my-gw.example.com"
    assert client.put("/api/settings/zhuque", json={"zhuque_base_url": "ftp://x"}).status_code == 400
    d = client.put("/api/settings/zhuque", json={"zhuque_api_key": "", "zhuque_base_url": "", "zhuque_auto_check": False}).json()
    assert not d["zhuque_configured"] and d["zhuque_base_url"] == "https://ai-gateway.edgeone.link"
    assert client.get("/api/settings/writing").json()["auto_commit"] is not None  # 别的设置不受影响


def test_zhuque_split_chunks_offsets() -> None:
    from app.services.zhuque import split_chunks

    paras = [("段落%d" % i) + "字" * 300 + "。" for i in range(10)]
    text = "\n\n".join(paras)
    chunks = split_chunks(text, 1000)
    assert len(chunks) > 1 and all(len(c) <= 1000 for _, c in chunks)
    assert all(text[off:off + len(c)] == c for off, c in chunks)
    assert "".join(c for _, c in chunks).replace("\n", "") == text.replace("\n", "")
    long_para = "很长的一句话。" * 400
    chunks = split_chunks(long_para, 1000)
    assert all(len(c) <= 1000 for _, c in chunks) and "".join(c for _, c in chunks) == long_para
    assert split_chunks("短文本", 1000) == [(0, "短文本")] and split_chunks("  ", 1000) == []


def test_zhuque_detect_merges_chunks(client: TestClient, zq_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services import zhuque

    monkeypatch.setattr(get_settings(), "zhuque_chunk_chars", 300)
    a = "甲" * 200 + "。人写的句子。"
    b = "乙" * 100 + "。机器写的句子。"
    text = a + "\n\n" + b

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url == "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify"
        assert req.headers["authorization"] == "Bearer sk-test-zhuque-1234"
        body = json.loads(req.content)
        assert body["is_merge"] is True
        t = body["text"]
        if t.startswith("甲"):
            return httpx.Response(200, json=_zq_response(t, 0.2, 0.1, {"0": 0.9, "1": 0.1, "2": 0.0},
                                                         [{"text": "人写的句子。", "label": 0, "conf": 0.9, "order": 0, "position": t.find("人写")}], 7))
        return httpx.Response(200, json=_zq_response(t, 0.95, 0.8, {"0": 0.0, "1": 0.8, "2": 0.2},
                                                     [{"text": "机器写的句子。", "label": "1", "conf": 0.97, "order": 0, "position": 999}], 5))

    seen = _mock_client(monkeypatch, handler)
    r = zhuque.detect(text)
    assert r["chunks"] == 2 and len(seen) == 2 and r["tokens"] == 12
    wa, wb = len(a.replace("\n", "")), len(b)
    assert r["softmax"] == round((0.2 * wa + 0.95 * wb) / (wa + wb), 4)
    assert abs(sum(r["labels_ratio"].values()) - 1) < 0.01 and set(r["labels_ratio"]) == {"human", "ai", "suspect"}
    segs = {s["label"]: s for s in r["segments"]}
    assert text[segs["human"]["start"]:segs["human"]["end"]] == "人写的句子。"
    assert text[segs["ai"]["start"]:segs["ai"]["end"]] == "机器写的句子。"  # position 不对时按原文找回
    assert r["ai_segment_ratio"] == round(7 / 13, 4)
    assert zhuque.level_of(0.49) == "low" and zhuque.level_of(0.5) == "mid" and zhuque.level_of(0.85) == "high"
    assert client.get("/api/settings/zhuque").json()["zhuque_usage"]["tokens"] >= 12


def test_zhuque_auth_errors_and_api(client: TestClient, zq_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import zhuque

    _mock_client(monkeypatch, lambda req: httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(zhuque.ZhuqueError, match="密钥无效"):
        zhuque.detect("一段文字。")
    j = client.post("/api/detect/aigc", json={"text": "一段文字。"}).json()
    t0 = time.time()
    while client.get(f"/api/jobs/{j['id']}").json()["status"] not in ("succeeded", "failed") and time.time() - t0 < 10:
        time.sleep(0.05)
    jj = client.get(f"/api/jobs/{j['id']}").json()
    assert jj["status"] == "failed" and "密钥无效" in jj["error"]
    _mock_client(monkeypatch, lambda req: httpx.Response(403, text="forbidden"))
    with pytest.raises(zhuque.ZhuqueError, match="HTTP 403"):
        zhuque.detect("一段文字。")
    _mock_client(monkeypatch, lambda req: httpx.Response(200, json=_zq_response("x", 0.6, 0.3, {"0": 0.4, "1": 0.3, "2": 0.3}, [], 3)))
    j = client.post("/api/detect/aigc", json={"text": "一段文字。", "is_merge": False}).json()
    res = wait_job(client, j)["result"]
    assert res["level"] == "mid" and res["chunks"] == 1 and res["tokens"] == 3 and res["is_merge"] is False
    assert client.post("/api/detect/aigc", json={"text": ""}).status_code == 422


def test_zhuque_detect_requires_key(client: TestClient) -> None:
    client.put("/api/settings/zhuque", json={"zhuque_api_key": ""})
    assert client.post("/api/detect/aigc", json={"text": "一段文字。"}).status_code == 409


def _book_with_chapter(client: TestClient, content: str, title: str = "朱雀测试书") -> tuple[int, int]:
    from app.db import session_scope
    from app.lint.humanlint import count_words
    from app.models.tables import Card, Chapter

    bid = client.post("/api/books", json={"title": title, "genre": "都市高武", "gender": "male"}).json()["id"]
    with session_scope() as s:
        s.add(Card(book_id=bid, type="character", name="林恩", summary="主角", data={}, known_by=[]))
        s.add(Card(book_id=bid, type="character", name="苏晚", summary="女主", data={}, known_by=[]))
        ch = Chapter(book_id=bid, number=1, title="第一章", content=content, words=count_words(content))
        s.add(ch)
        s.commit()
        return bid, ch.id or 0


CHAPTER = ("林恩深吸一口气，嘴角勾起一抹冷笑。他不禁握紧了拳头，三千灵石就这么没了。\n\n"
           "苏晚站在门口，眼中闪过一丝担忧：“你真要去？第九层可不是闹着玩的。”\n\n"
           "林恩点头。与此同时，远处传来钟声，一共敲了七下，整整十二个时辰过去了，天色仿佛被墨染过一样黑。")


def test_chapter_aigc_job_saves_and_staleness(client: TestClient, zq_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    bid, cid = _book_with_chapter(client, CHAPTER)
    _mock_client(monkeypatch, lambda req: httpx.Response(200, json=_zq_response(
        "", 0.9, 0.7, {"0": 0.1, "1": 0.7, "2": 0.2}, [{"text": "林恩点头。", "label": 2, "conf": 0.6, "order": 0, "position": 0}], 21)))
    j = client.post(f"/api/books/{bid}/chapters/{cid}/aigc").json()
    assert j["job_id"] == j["id"]
    res = wait_job(client, j)["result"]
    assert res["chapter_id"] == cid and res["aigc"]["level"] == "high"
    a = client.get(f"/api/chapters/{cid}").json()["aigc"]
    assert a["softmax"] == 0.9 and a["ratio"] == 0.7 and a["labels_ratio"] == {"human": 0.1, "ai": 0.7, "suspect": 0.2}
    assert a["level"] == "high" and a["tokens"] == 21 and a["chunks"] == 1 and a["checked_at"] and a["content_hash"]
    assert a["stale"] is False and a["segments"][0]["label"] == "suspect"
    assert CHAPTER[a["segments"][0]["start"]:a["segments"][0]["end"]] == "林恩点头。"
    lst = client.get(f"/api/books/{bid}/chapters").json()[0]["aigc"]
    assert "segments" not in lst and lst["level"] == "high"
    client.put(f"/api/chapters/{cid}", json={"content": CHAPTER + "\n\n新加一段。"})
    assert client.get(f"/api/chapters/{cid}").json()["aigc"]["stale"] is True
    other, _ = _book_with_chapter(client, "别的书。", "另一本")
    assert client.post(f"/api/books/{other}/chapters/{cid}/aigc").status_code == 404


def test_auto_check_off_by_default_and_never_blocks_commit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import writing, zhuque

    calls: list[int] = []
    monkeypatch.setattr(zhuque, "check_chapter", lambda cid, *a, **k: calls.append(cid) or (_ for _ in ()).throw(RuntimeError("额度用完")))
    client.put("/api/settings/zhuque", json={"zhuque_api_key": "sk-auto-0000", "zhuque_auto_check": False})
    try:
        _, cid = _book_with_chapter(client, CHAPTER, "自动检测关")
        ch = writing.commit_chapter(cid)
        assert ch.status == "committed"
        time.sleep(0.1)
        assert calls == []  # 默认关：写章/提交不调用朱雀
        client.put("/api/settings/zhuque", json={"zhuque_auto_check": True})
        _, cid2 = _book_with_chapter(client, CHAPTER, "自动检测开")
        ch2 = writing.commit_chapter(cid2)  # 检测抛错也不影响提交
        assert ch2.status == "committed"
        t0 = time.time()
        while not calls and time.time() - t0 < 5:
            time.sleep(0.02)
        assert calls == [cid2]
    finally:
        client.put("/api/settings/zhuque", json={"zhuque_api_key": "", "zhuque_auto_check": False})


# ================================================================== 6. 语感重塑

def test_number_tokens_and_checks() -> None:
    from app.services.writing import number_tokens, polish_checks

    toks = number_tokens(CHAPTER)
    assert "三千" in toks and "十二" in toks and "七" in toks and "九" in toks
    assert "万一" not in number_tokens("万一他来了")
    checks, warns = polish_checks(CHAPTER, CHAPTER.replace("三千", "五千").replace("苏晚", "她"), ["林恩", "苏晚"])
    assert checks["numbers_missing"] == ["三千"] and checks["numbers_added"] == ["五千"] and checks["names_missing"] == ["苏晚"]
    assert any("数字" in w for w in warns) and any("苏晚" in w for w in warns)
    _, warns = polish_checks(CHAPTER, CHAPTER[: len(CHAPTER) // 2], ["林恩"])
    assert any("字数变化" in w for w in warns)
    checks, warns = polish_checks(CHAPTER, CHAPTER, ["林恩", "苏晚"])
    assert checks["numbers_missing"] == [] and not any("数字" in w or "人名" in w or "字数" in w for w in warns)


def test_polish_voice_preview_apply_undo(client: TestClient) -> None:
    from app.llm.gateway import TASK_ROLE

    assert TASK_ROLE["polish_voice"] == "writer"
    bid, cid = _book_with_chapter(client, CHAPTER, "语感书")
    j = client.post(f"/api/books/{bid}/chapters/{cid}/polish-voice").json()
    assert j["job_id"] == j["id"] and j["kind"] == "chapter_polish_voice"
    res = wait_job(client, j)["result"]
    assert res["before"] == CHAPTER and res["after"] != CHAPTER and res["changed"] and res["scope"] == "all"
    assert "嘴角勾起一抹" not in res["after"] and "三千" in res["after"] and "苏晚" in res["after"]
    assert isinstance(res["warnings"], list) and res["checks"]["numbers_missing"] == [] and res["label"] == "语感重塑前"
    assert client.get(f"/api/chapters/{cid}").json()["content"] == CHAPTER  # 不直接覆盖正文
    ch = client.post(f"/api/chapters/{cid}/apply-rewrite", json={"content": res["after"], "label": res["label"]}).json()
    assert ch["content"] == res["after"] and ch["last_history_label"] == "语感重塑前"
    assert client.post(f"/api/chapters/{cid}/undo").json()["content"] == CHAPTER
    other, _ = _book_with_chapter(client, "x。", "别的书2")
    assert client.post(f"/api/books/{other}/chapters/{cid}/polish-voice").status_code == 404


def test_polish_voice_warns_on_changed_numbers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import mock

    bid, cid = _book_with_chapter(client, CHAPTER, "语感书2")
    monkeypatch.setitem(mock.HANDLERS, "polish_voice", lambda meta: str(meta["text"]).replace("三千", "3000").replace("苏晚", "那姑娘"))
    res = wait_job(client, client.post(f"/api/books/{bid}/chapters/{cid}/polish-voice").json())["result"]
    assert any("数字" in w and "三千" in w for w in res["warnings"]) and any("苏晚" in w for w in res["warnings"])


def test_agent_polish_voice_tool(client: TestClient) -> None:
    from app.services import agent_tools

    assert "polish_voice" in {t["name"] for t in agent_tools.catalog()}
    bid, cid = _book_with_chapter(client, CHAPTER, "Agent 语感书")
    sid = client.post(f"/api/books/{bid}/agent/sessions").json()["id"]
    r = agent_tools.dispatch(agent_tools.ToolCtx(book_id=bid, session_id=sid), "polish_voice", {"number": 1})
    assert r.ok and r.proposal_ids
    from app.db import session_scope
    from app.models.tables import AgentProposal

    with session_scope() as s:
        p = s.get(AgentProposal, r.proposal_ids[0])
        assert p is not None and p.kind == "chapter_rewrite" and p.payload["instruction"] == "语感重塑"
        assert "warnings" in p.payload and p.payload["before"] == CHAPTER
    assert client.get(f"/api/chapters/{cid}").json()["content"] == CHAPTER


# ================================================================== 7. 版本号

def test_version_091(client: TestClient) -> None:
    assert client.get("/api/health").json()["version"].startswith(("0.9.", "0.10.", "0.11."))
    root = Path(__file__).resolve().parents[2]
    assert "## v0.9.1" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## v0.9.1" in (root / "docs" / "API_CONTRACT.md").read_text(encoding="utf-8")
