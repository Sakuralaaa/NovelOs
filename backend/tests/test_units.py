"""网关（失败重试/切换、token 记录、images b64/url）、雷达解析、风格片段、相关性筛选、精修校验、SPA 托管。"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import select

from app.db import kv_set, session_scope
from app.llm import gateway as gw_mod
from app.llm.crypto import encrypt
from app.models.tables import Card, Channel, Job, OutlineNode, TokenUsage
from app.radar.fanqie import guess_gender, parse_items


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (900, 900), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def fake_channels(monkeypatch: pytest.MonkeyPatch) -> Any:
    calls: list[str] = []
    png = _png()

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.url.host}{req.url.path}")
        if req.url.host == "bad.example":
            return httpx.Response(500, text="boom")
        if req.url.path.endswith("/chat/completions"):
            body = json.loads(req.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": f"ok:{body['model']}"}}],
                                             "usage": {"prompt_tokens": 11, "completion_tokens": 7}})
        if req.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode()},
                                                      {"url": "https://good.example/img.png"}]})
        if req.url.path == "/img.png":
            return httpx.Response(200, content=png)
        return httpx.Response(404)

    real = httpx.Client

    def factory(*a: Any, **kw: Any) -> httpx.Client:
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(gw_mod.httpx, "Client", factory)
    monkeypatch.setattr(gw_mod.time, "sleep", lambda *_: None)
    with session_scope() as s:
        bad = Channel(name="bad", base_url="https://bad.example/v1", api_key_enc=encrypt("k1"), models=["m-a"])
        good = Channel(name="good", base_url="https://good.example/v1", api_key_enc=encrypt("k2"), models=["m-b", "img-1"])
        s.add(bad)
        s.add(good)
        s.commit()
        s.refresh(bad)
        s.refresh(good)
        kv_set(s, gw_mod.ROUTING_KEY, {"writer": f"{bad.id}:m-a", "image": f"{good.id}:img-1"})
        ids = (bad.id, good.id)
    yield calls
    with session_scope() as s:
        for cid in ids:
            c = s.get(Channel, cid)
            if c:
                s.delete(c)
        s.commit()
        kv_set(s, gw_mod.ROUTING_KEY, {})


def test_gateway_retry_then_failover_and_usage(client: TestClient, fake_channels: list[str]) -> None:
    g = gw_mod.LLMGateway()
    out = g.chat("writing_scene", [{"role": "user", "content": "hi"}])
    assert out == "ok:m-b"  # 路由渠道失败 3 次（1+重试2）后切到同角色其他渠道
    assert fake_channels.count("bad.example/v1/chat/completions") == 3
    with session_scope() as s:
        u = s.exec(select(TokenUsage).order_by(TokenUsage.id.desc())).first()
        assert u and u.prompt_tokens == 11 and u.completion_tokens == 7 and u.role == "writer"
    usage = client.get("/api/settings/usage").json()
    assert any(x["completion_tokens"] >= 7 for x in usage)


def test_gateway_images_b64_and_url(client: TestClient, fake_channels: list[str]) -> None:
    imgs = gw_mod.LLMGateway().images("prompt", 2)
    assert imgs is not None and len(imgs) == 2 and all(i[:4] == b"\x89PNG" for i in imgs)


def test_mock_mode_when_no_channels(client: TestClient) -> None:
    out = gw_mod.LLMGateway().chat_json("ideation", "s", "u", meta={"count": 2, "gender": "female"})
    assert len(out["ideas"]) == 2
    assert gw_mod.LLMGateway().images("p", 1) is None


def test_extract_json_tolerant() -> None:
    assert gw_mod.extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert gw_mod.extract_json('好的，结果如下：{"a":[1,2]} 希望有帮助') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        gw_mod.extract_json("没有 JSON")


def test_radar_parse_items() -> None:
    payload = {"code": 0, "data": {"result": [
        {"book_id": "1", "book_name": "误亲后，和死对头共感了", "author": "某", "category": "甜宠,纯爱",
         "category_v2": ["甜宠", "纯爱"], "read_count": "198034", "abstract": "简介", "hot": 48305.7},
        {"book_id": "2", "book_name": "短剧", "item_schema_url": "sslocal://x?novel_page_type=short_series_player"},
        {"book_id": "3", "book_name": "高武：一刀", "category": "都市高武", "read_count": "", "hot": 1200},
    ]}}
    items = parse_items(payload)
    assert [i["title"] for i in items] == ["误亲后，和死对头共感了", "高武：一刀"]
    assert items[0]["gender"] == "female" and items[0]["read_count"] == 198034
    assert items[1]["gender"] == "male" and items[1]["read_count"] == 1200 and items[1]["word_count"] == 0
    assert guess_gender("宫斗宅斗", []) == "female"


def test_radar_enabled_failure_falls_back_to_mock(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.radar import fanqie
    from conftest import wait_job

    def boom() -> list[dict[str, Any]]:
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(fanqie, "fetch_rank_lists", boom)
    assert client.put("/api/radar/config", json={"enabled": True, "daily_hour": 9}).json() == {"enabled": True, "daily_hour": 9}
    j = wait_job(client, client.post("/api/radar/refresh").json())
    assert j["result"]["source"] == "mock" and "回退" in j["result"]["note"]
    client.put("/api/radar/config", json={"enabled": False, "daily_hour": 8})


def test_style_excerpt_window() -> None:
    from app.lint.humanlint import count_words
    from app.services.style import pick_excerpt

    para = "他把伞往墙角一靠，拉开椅子坐下，椅腿在地上刮出一声。“钱呢？”她抬眼看他，手里的笔没停。"
    text = "\n".join([para] * 120)
    ex = pick_excerpt(text)
    assert 800 <= count_words(ex) <= 1700
    assert pick_excerpt("短文。") == "短文。"


def test_context_pack_relevance_filter(client: TestClient) -> None:
    from app.services.context import build_context_pack
    from conftest import wait_job

    bid = client.post("/api/books", json={"genre": "都市", "gender": "male", "title": "相关性测试"}).json()["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    client.post(f"/api/books/{bid}/cards", json={"type": "character", "name": "无关路人丙", "summary": "不该被注入"})
    with session_scope() as s:
        from app.services import common
        book = common.get_book(s, bid)
        names = [c.name for c in s.exec(select(Card).where(Card.book_id == bid, Card.type == "character"))]
        prot = names[0]
        node = OutlineNode(book_id=bid, level="chapter", order=1, title="t",
                           beats={"characters": [prot], "location": "老码头七号仓", "goal": "拿回铜扣账本"})
        pack = build_context_pack(s, book, node)
    rel = {c.name for c in pack.relevant_cards}
    assert prot in rel and "老码头七号仓" in rel and "铜扣账本" in rel
    assert "无关路人丙" not in rel and "无关路人丙" not in pack.suffix
    assert "风格卡" in pack.prefix and pack.prefix.index("正文写作规则") < pack.prefix.index("【本书】")


def test_thicken_rejects_new_facts(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    from app.config import get_settings
    from app.lint.humanlint import lint_chapter
    from app.services import writing

    content = "他推门进来。\n\n“钱呢？”\n\n“没有。”\n\n经过一番周旋，事情很快办妥，于是随后散了。"
    lint = lint_chapter(content, get_settings().lint)
    targets = writing.thicken_targets(content, lint, 8)
    assert {t["index"] for t in targets} >= {2, 3}

    def fake_chat_json(*_: Any, **__: Any) -> dict[str, Any]:
        return {"paragraphs": [
            {"index": 2, "text": "老周把烟按灭在桌沿上：“没有。”"},           # 引入正文中没有的已登记实体 → 拒绝
            {"index": 3, "text": "两人对坐着磨了半盏茶，茶凉透了才起身散了。"},  # 合法
            {"index": 1, "text": "乱改"},                                      # 不在定位列表 → 拒绝
        ]}

    monkeypatch.setattr(writing.get_gateway(), "chat_json", fake_chat_json)
    new, located, applied = writing.thicken(content, lint, {}, ["老周", "林照"], {})
    assert applied == 1 and "老周" not in new and "半盏茶" in new and "“钱呢？”" in new


def test_job_recovery_marks_running_failed(client: TestClient) -> None:
    from app.jobs.manager import recover_on_startup

    with session_scope() as s:
        j = Job(kind="x", status="running")
        s.add(j)
        s.commit()
        s.refresh(j)
        jid = j.id
    assert recover_on_startup() >= 1
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "failed"


def test_spa_fallback(tmp_path: Any) -> None:
    from fastapi import FastAPI

    from app.main import _mount_spa

    (tmp_path / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    _mount_spa(app, tmp_path)
    c = TestClient(app)
    assert c.get("/api/ping").json() == {"ok": True}
    assert "spa" in c.get("/books/3/write").text
    assert c.get("/assets/a.js").text == "console.log(1)"
    assert c.get("/api/nope").status_code == 404
    assert c.get("/media/x.png").status_code == 404


def test_title_scoring() -> None:
    from app.services.packaging import score_title

    s = score_title("离婚后，前夫跪求复合三年")
    assert s["length"] == 25 and s["number"] == 25 and s["emotion"] == 25 and s["identity"] == 25
    assert score_title("夜")["total"] == 0


def test_placeholder_cover() -> None:
    from app.services.cover import placeholder_cover

    img = Image.open(io.BytesIO(placeholder_cover("灰港旧账", "都市", 1)))
    assert img.size == (600, 800)


def test_iso_format() -> None:
    import re
    from datetime import datetime, timezone

    from app.api.schemas import iso

    v = iso(datetime(2026, 11, 12, 3, 4, 5, 678000, tzinfo=timezone.utc))
    assert v == "2026-11-12T03:04:05.678+00:00"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00", iso(datetime(2026, 1, 1)) or "")


def test_job_sse_events(client: TestClient) -> None:
    from conftest import wait_job

    j = wait_job(client, client.post("/api/radar/refresh").json())
    with client.stream("GET", f"/api/jobs/{j['id']}/events") as r:
        body = "".join(r.iter_text())
    assert r.headers["content-type"].startswith("text/event-stream")
    assert '"status": "succeeded"' in body
