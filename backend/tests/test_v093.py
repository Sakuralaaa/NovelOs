"""v0.9.3：完整度/引导、字段级 AI、@引用、灵魂五维、弃用条目、审批模式、成本估算与用量、拆书工作台。

全部走 mock LLM，不做真实网络与模型调用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from conftest import wait_job

ROOT = Path(__file__).resolve().parents[2]


def _book(client: TestClient, title: str = "v093 测试书") -> int:
    return client.post("/api/books", json={"title": title, "genre": "都市高武", "gender": "male"}).json()["id"]


def _card(client: TestClient, bid: int, **kw: Any) -> dict[str, Any]:
    body = {"type": "character", "name": "林川", "summary": "落魄武馆少主", "data": {"role": "protagonist"}, **kw}
    r = client.post(f"/api/books/{bid}/cards", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ 迁移与字段

def test_new_columns_exist() -> None:
    from sqlalchemy import inspect

    from app.db import session_scope

    with session_scope() as s:
        insp = inspect(s.get_bind())
        cols = {c["name"] for c in insp.get_columns("card")}
        assert {"status", "ref_enabled", "soul"} <= cols
        assert "approval_mode" in {c["name"] for c in insp.get_columns("book")}
        tables = set(insp.get_table_names())
        assert "llm_usage" in tables and "teardown_project" in tables


def test_card_out_has_new_fields(client: TestClient) -> None:
    bid = _book(client)
    c = _card(client, bid, soul={"desire": "重振武馆"})
    assert c["status"] == "active" and c["ref_enabled"] is True
    assert c["soul"]["desire"] == "重振武馆"
    # soul 按键合并
    r = client.put(f"/api/cards/{c['id']}", json={"soul": {"fear": "再次失去亲人"}}).json()
    assert r["soul"]["desire"] == "重振武馆" and r["soul"]["fear"] == "再次失去亲人"


# ------------------------------------------------------------------ 完整度 / 引导

def test_completeness_and_onboarding(client: TestClient) -> None:
    bid = _book(client, "完整度书")
    r = client.get(f"/api/books/{bid}/completeness").json()
    assert 0 <= r["score"] <= 100
    keys = {i["key"] for i in r["items"]}
    assert {"world", "protagonist", "outline", "chapter1", "cover"} <= keys
    for i in r["items"]:
        assert {"key", "label", "done", "hint", "action"} <= set(i)
    before = r["score"]
    client.post(f"/api/books/{bid}/cards", json={"type": "world", "name": "灵气复苏", "summary": "世界设定"})
    assert client.get(f"/api/books/{bid}/completeness").json()["score"] >= before

    ob = client.get("/api/onboarding").json()
    assert ob["order"] == ["model", "project", "bible_outline", "first_chapter"]
    assert ob["steps"]["project"] is True  # 已有书，自动判定
    ob2 = client.put("/api/onboarding", json={"steps": {"model": True}, "dismissed": True}).json()
    assert ob2["steps"]["model"] is True and ob2["dismissed"] is True
    client.put("/api/onboarding", json={"dismissed": False})
    assert client.get("/api/books/999999/completeness").status_code == 404


# ------------------------------------------------------------------ 字段 AI

def test_field_ai_and_apply(client: TestClient) -> None:
    bid = _book(client, "字段书")
    c = _card(client, bid)
    j = client.post(f"/api/books/{bid}/bible/{c['id']}/field-ai", json={"field": "summary", "mode": "expand"})
    assert j.status_code == 200, j.text
    res = wait_job(client, j.json())["result"]
    assert "value" in res and "before" in res
    # 不直接写库
    assert client.get(f"/api/books/{bid}/cards").json()[0]["summary"] == "落魄武馆少主"
    ap = client.post(f"/api/books/{bid}/bible/{c['id']}/field-ai/apply", json={"field": "summary", "value": "新简介"})
    assert ap.status_code == 200 and ap.json()["summary"] == "新简介"
    # 错误码
    assert client.post(f"/api/books/{bid}/bible/{c['id']}/field-ai/apply", json={"field": "summary", "value": 5}).status_code == 422
    assert client.post(f"/api/books/{bid}/bible/999999/field-ai", json={"field": "summary"}).status_code == 404
    bad = client.post(f"/api/books/{bid}/bible/{c['id']}/field-ai", json={"field": "no_such_field!"})
    assert bad.status_code in (400, 422)


# ------------------------------------------------------------------ @引用

def test_refs_and_mentions(client: TestClient) -> None:
    from app.db import session_scope
    from app.services import refs

    bid = _book(client, "引用书")
    a = _card(client, bid, name="林川")
    b = _card(client, bid, type="item", name="老猎枪", data={}, ref_enabled=False)
    _card(client, bid, type="location", name="青石武馆", data={})
    lst = client.get(f"/api/books/{bid}/refs").json()
    names = {x["name"] for x in lst}
    assert "林川" in names and "青石武馆" in names and "老猎枪" not in names
    assert [x["name"] for x in client.get(f"/api/books/{bid}/refs", params={"q": "武馆"}).json()] == ["青石武馆"]
    with session_scope() as s:
        block = refs.refs_block(s, bid, "让 @林川 带着 @老猎枪 去 @青石武馆")
    assert "林川" in block and "青石武馆" in block and "老猎枪" not in block
    assert a["id"] and b["id"]


# ------------------------------------------------------------------ 灵魂五维

def test_soul_job_fill_keeps_existing(client: TestClient) -> None:
    bid = _book(client, "五维书")
    c = _card(client, bid, soul={"desire": "重振武馆"})
    res = wait_job(client, client.post(f"/api/books/{bid}/characters/{c['id']}/soul", json={"mode": "fill"}).json())["result"]
    soul = res.get("soul") or res.get("value") or {}
    assert soul.get("desire") in (None, "", "重振武馆")
    w = _card(client, bid, type="world", name="世界", data={})
    assert client.post(f"/api/books/{bid}/characters/{w['id']}/soul", json={}).status_code == 400


# ------------------------------------------------------------------ 弃用条目

def test_deprecated_excluded(client: TestClient) -> None:
    from app.db import session_scope
    from app.services import common

    bid = _book(client, "弃用书")
    _card(client, bid, name="张三")
    d = _card(client, bid, name="废角色")
    client.put(f"/api/cards/{d['id']}", json={"status": "deprecated"})
    assert {c["name"] for c in client.get(f"/api/books/{bid}/cards").json()} == {"张三"}
    all_ = client.get(f"/api/books/{bid}/cards", params={"include_deprecated": True}).json()
    assert {c["name"] for c in all_} == {"张三", "废角色"}
    with session_scope() as s:
        assert "废角色" not in common.book_context(s, common.get_book(s, bid))
        assert "废角色" not in {c.name for c in common.cards(s, bid)}


# ------------------------------------------------------------------ 审批模式

def test_approval_mode_sync(client: TestClient) -> None:
    bid = _book(client, "审批书")
    b = client.get(f"/api/books/{bid}").json()
    assert b["approval_mode"] in ("auto", "review") and b["approval_mode_explicit"] is False
    b = client.patch(f"/api/books/{bid}", json={"approval_mode": "review"}).json()
    assert b["approval_mode"] == "review" and b["agent_auto_apply"] is False and b["approval_mode_explicit"] is True
    b = client.patch(f"/api/books/{bid}", json={"agent_auto_apply": True}).json()
    assert b["approval_mode"] == "auto"


# ------------------------------------------------------------------ 估算与用量

def test_estimate_and_usage(client: TestClient) -> None:
    bid = _book(client, "估算书")
    for kind in ("chapter_write", "review", "outline", "humanize", "thicken", "field_ai", "teardown"):
        r = client.post("/api/estimate", json={"kind": kind, "book_id": bid})
        assert r.status_code == 200, (kind, r.text)
        e = r.json()
        assert e["calls_est"] >= 1 and e["input_tokens_est"] > 0 and e["seconds_est"] >= 1 and e["route"]
    a = client.post("/api/estimate", json={"kind": "aigc"}).json()
    assert a["input_tokens_est"] == 0 and a["route"] == "zhuque"
    assert client.post("/api/estimate", json={"kind": "nope"}).status_code == 422
    # 跑一个调模型的任务后，用量表有记录
    c = _card(client, bid)
    wait_job(client, client.post(f"/api/books/{bid}/bible/{c['id']}/field-ai", json={"field": "summary"}).json())
    u = client.get(f"/api/books/{bid}/usage").json()
    assert isinstance(u, dict)
    assert client.get("/api/usage", params={"days": 7}).status_code == 200


# ------------------------------------------------------------------ 拆书工作台

ORIGINAL = "\n".join(
    [f"第{i}章 风起\n" + "林川握紧拳头，青石武馆的大门在风中吱呀作响，他知道今天必须赢下这一战。" * 8 for i in range(1, 4)]
)


def test_teardown_workspace(client: TestClient) -> None:
    from app.services import teardown_ws as tw

    # 8 字指纹
    fp = set(tw.fingerprint(ORIGINAL))
    assert tw.fp_hits("林川握紧拳头，青石武馆", fp) > 0
    assert tw.fp_hits("完全不相干的一句话内容", fp) == 0

    assert client.post("/api/teardowns", json={"source": "paste", "text": ""}).status_code in (400, 422)
    j = client.post("/api/teardowns", json={"source": "paste", "text": ORIGINAL, "title": "测试拆书"})
    assert j.status_code == 200, j.text
    res = wait_job(client, j.json())["result"]
    tid = res["teardown_id"]
    t = client.get(f"/api/teardowns/{tid}").json()
    assert t["title"] == "测试拆书"
    assert ORIGINAL[:200] not in str(t)  # 原文不入库
    assert any(x["id"] == tid for x in client.get("/api/teardowns").json())

    bid = _book(client, "拆书写入书")
    tb = client.post(f"/api/teardowns/{tid}/to-bible", json={"book_id": bid, "parts": ["characters", "reusable", "selling_points"]})
    assert tb.status_code == 200, tb.text
    out = tb.json()
    assert {"cards", "warnings", "skipped"} <= set(out)
    for c in out["cards"]:
        assert "林川" not in c["name"]

    idea = client.post(f"/api/teardowns/{tid}/to-idea", json={"expand": False})
    assert idea.status_code == 200, idea.text

    assert client.delete(f"/api/teardowns/{tid}").status_code == 200
    assert client.get(f"/api/teardowns/{tid}").status_code == 404


def test_version_and_docs(client: TestClient) -> None:
    assert client.get("/api/health").json()["version"].startswith(("0.9.", "0.10.", "0.11.", "0.12.", "0.13.", "0.14.", "0.15.", "0.16.", "0.17.", "0.18.", "0.19."))
    assert "## v0.9.3" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "v0.9.3" in (ROOT / "docs" / "API_CONTRACT.md").read_text(encoding="utf-8")
