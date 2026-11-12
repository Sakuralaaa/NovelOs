"""v0.5：每本书的专属 Agent —— 循环、工具调度、提案采纳/拒绝/撤回、自动采纳、步数上限、旧库升级。全部在 mock 模式下跑。"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import wait_job

ASK = "别强调拳法，把『碎星神通』改个名，同步设定和大纲"


def _book(client: TestClient, outline: bool = True) -> int:
    b = client.post("/api/books", json={"title": "碎星拳神", "genre": "都市高武", "gender": "male",
                                         "premise": "主角练成碎星神通，一套拳法打穿灰港城。"}).json()
    bid = b["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    client.patch(f"/api/books/{bid}", json={"tagline": "一拳碎星，靠『碎星神通』的拳法横扫全城"})
    hero = next(c for c in client.get(f"/api/books/{bid}/cards").json() if c["type"] == "character")
    client.put(f"/api/cards/{hero['id']}", json={"summary": "主角，靠碎星神通的拳法起家。"})
    if outline:
        wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
        root = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "book")
        client.put(f"/api/outline/{root['id']}", json={"summary": "主角以碎星神通的拳法，从码头打到全城。"})
    return bid


def _session(client: TestClient, bid: int) -> int:
    return client.post(f"/api/books/{bid}/agent/sessions").json()["id"]


def _say(client: TestClient, sid: int, text: str) -> dict[str, Any]:
    r = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": text})
    assert r.status_code == 200, r.text
    job = wait_job(client, r.json()["job"])
    return {**client.get(f"/api/agent/sessions/{sid}").json(), "run": job}


def _wait_proposal(client: TestClient, pid: int, timeout: float = 60) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = client.get(f"/api/agent/proposals/{pid}").json()
        if p["status"] not in ("running",):
            return p
        time.sleep(0.05)
    raise AssertionError("提案任务超时")


# ------------------------------------------------------------------ 1. 循环 + mock 多工具脚本

def test_agent_mock_flow_multi_tools(client: TestClient) -> None:
    bid = _book(client)
    sid = _session(client, bid)
    d = _say(client, sid, ASK)
    assert d["run"]["result"]["stopped_by"] == "done" and d["run"]["result"]["steps"] == 4
    roles = [m["role"] for m in d["messages"]]
    assert roles[0] == "user" and roles[-1] == "assistant"
    first = d["messages"][1]
    assert {c["name"] for c in first["tool_calls"]} == {"get_book_info", "search_bible"}  # 一步并行两个读工具
    tool_names = [m["name"] for m in d["messages"] if m["role"] == "tool"]
    assert tool_names == ["get_book_info", "search_bible", "revise_book_info", "sync_downstream"]
    kinds = [p["kind"] for p in d["proposals"]]
    assert kinds == ["book_info", "bible", "outline_nodes"]
    assert all(p["status"] == "pending" for p in d["proposals"])  # 默认只是提案，没写入
    book = client.get(f"/api/books/{bid}").json()
    assert "碎星神通" in book["tagline"]
    assert "#" in d["messages"][-1]["content"]
    # 会话标题取第一句话；会话列表
    ss = client.get(f"/api/books/{bid}/agent/sessions").json()
    assert ss[0]["title"].startswith("别强调拳法") and ss[0]["running"] is False


def test_proposals_apply_reject_revert(client: TestClient) -> None:
    bid = _book(client)
    sid = _session(client, bid)
    d = _say(client, sid, ASK)
    info, bible, outl = d["proposals"]
    # 作品信息：编辑后采纳
    edited = {"tagline": "一拳碎星，横扫全城（作者手改）"}
    r = client.post(f"/api/agent/proposals/{info['id']}/apply", json={"edited": edited}).json()
    assert r["proposal"]["status"] == "applied" and r["proposal"]["revertible"]
    assert client.get(f"/api/books/{bid}").json()["tagline"] == edited["tagline"]
    assert client.post(f"/api/agent/proposals/{info['id']}/apply").status_code == 409  # 不能重复采纳
    # 设定库：没有冲突 → 直接采纳，带快照
    r = client.post(f"/api/agent/proposals/{bible['id']}/apply").json()
    assert r["proposal"]["status"] == "applied" and r["proposal"]["result"]["snapshot_id"]
    cards = client.get(f"/api/books/{bid}/cards").json()
    assert not any("碎星神通" in c["summary"] for c in cards)
    # 大纲：拒绝
    r = client.post(f"/api/agent/proposals/{outl['id']}/reject").json()
    assert r["status"] == "rejected"
    assert client.post(f"/api/agent/proposals/{outl['id']}/apply").status_code == 409
    root = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "book")
    assert "碎星神通" in root["summary"]
    # 撤回设定库（快照回滚）与作品信息（版本栈）
    assert client.post(f"/api/agent/proposals/{bible['id']}/revert").json()["status"] == "reverted"
    assert any("碎星神通" in c["summary"] for c in client.get(f"/api/books/{bid}/cards").json())
    assert client.post(f"/api/agent/proposals/{info['id']}/revert").json()["status"] == "reverted"
    assert "碎星神通" in client.get(f"/api/books/{bid}").json()["tagline"]
    assert client.post(f"/api/agent/proposals/{info['id']}/revert").status_code == 409
    # 提案状态会进入下一轮的系统提示
    from app.services.agent import system_prompt

    sp = system_prompt(bid, sid)
    assert f"#{outl['id']}" in sp and "作者拒绝了" in sp and "已撤回" in sp


def test_revert_refuses_when_changed_afterwards(client: TestClient) -> None:
    bid = _book(client)
    sid = _session(client, bid)
    d = _say(client, sid, ASK)
    info = d["proposals"][0]
    client.post(f"/api/agent/proposals/{info['id']}/apply")
    client.patch(f"/api/books/{bid}", json={"tagline": "作者后来又手改了"})
    r = client.post(f"/api/agent/proposals/{info['id']}/revert")
    assert r.status_code == 409 and "改过" in r.json()["detail"]


# ------------------------------------------------------------------ 2. 自动采纳

def test_auto_apply_writes_but_keeps_undo_and_deletes_still_confirm(client: TestClient) -> None:
    bid = _book(client)
    r = client.put(f"/api/books/{bid}/agent/settings", json={"auto_apply": True}).json()
    assert r["auto_apply"] is True and r["book"]["agent_auto_apply"] is True
    sid = _session(client, bid)
    d = _say(client, sid, ASK)
    assert all(p["status"] == "applied" and p["auto_applied"] for p in d["proposals"])
    assert "碎星神通" not in client.get(f"/api/books/{bid}").json()["tagline"]
    tool_msgs = [json.loads(m["content"]) for m in d["messages"] if m["role"] == "tool" and m["name"] == "revise_book_info"]
    assert "自动采纳" in tool_msgs[0]["note"]
    # 仍可撤回
    assert client.post(f"/api/agent/proposals/{d['proposals'][0]['id']}/revert").json()["status"] == "reverted"
    # 删除类：即使自动采纳也要确认
    from app.services import agent_tools

    card = client.get(f"/api/books/{bid}/cards").json()[-1]
    res = agent_tools.dispatch(agent_tools.ToolCtx(book_id=bid, session_id=sid), "delete_card", {"card_id": card["id"], "reason": "没用了"})
    assert res.ok and res.data["status"] == "pending" and "确认" in res.data["note"]
    p = client.get(f"/api/agent/proposals/{res.proposal_ids[0]}").json()
    assert p["destructive"] and p["status"] == "pending"
    assert any(c["id"] == card["id"] for c in client.get(f"/api/books/{bid}/cards").json())
    r = client.post(f"/api/agent/proposals/{p['id']}/apply").json()
    assert r["proposal"]["status"] == "applied"
    assert not any(c["id"] == card["id"] for c in client.get(f"/api/books/{bid}/cards").json())
    client.post(f"/api/agent/proposals/{p['id']}/revert")
    assert any(c["id"] == card["id"] for c in client.get(f"/api/books/{bid}/cards").json())
    client.put(f"/api/books/{bid}/agent/settings", json={"auto_apply": False})


# ------------------------------------------------------------------ 3. 步数上限 / 停止 / 出错

def test_step_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import gateway
    from app.services import agent

    calls = {"n": 0}

    def always_tool(self: Any, messages: list[dict[str, Any]], tools: list[dict[str, Any]], meta: Any = None, route: Any = None, temperature: float = 0.4) -> dict[str, Any]:
        calls["n"] += 1
        assert messages[0]["role"] == "system" and "禁用套路" in messages[0]["content"] or "俗套" in messages[0]["content"]
        return {"content": "", "tool_calls": [{"id": f"c{calls['n']}", "name": "get_book_info", "arguments": {}}]}

    monkeypatch.setattr(gateway.LLMGateway, "chat_tools", always_tool)
    bid = _book(client, outline=False)
    sid = _session(client, bid)
    d = _say(client, sid, "一直读下去")
    assert calls["n"] == agent.MAX_STEPS
    assert d["run"]["result"] == {"steps": agent.MAX_STEPS, "proposals": [], "stopped_by": "max_steps"}
    assert d["messages"][-1]["role"] == "notice" and str(agent.MAX_STEPS) in d["messages"][-1]["content"]
    assert d["session"]["running"] is False


def test_stop_and_error_are_recorded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import gateway
    from app.services import agent

    bid = _book(client, outline=False)
    sid = _session(client, bid)
    # 停止：在第一步之前置位
    from app.db import session_scope
    from app.models.tables import AgentSession

    with session_scope() as s:
        a = s.get(AgentSession, sid)
        a.stop_requested = True
        s.add(a)
        s.commit()
    r = agent.run_turn(sid, None, None)
    assert r["stopped_by"] == "user"

    def boom(*a: Any, **k: Any) -> dict[str, Any]:
        raise gateway.LLMError("所有渠道均失败：测试")

    monkeypatch.setattr(gateway.LLMGateway, "chat_tools", boom)
    r = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "随便"}).json()
    for _ in range(200):
        j = client.get(f"/api/jobs/{r['job']['id']}").json()
        if j["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert j["status"] == "failed"
    d = client.get(f"/api/agent/sessions/{sid}").json()
    assert d["messages"][-1]["role"] == "notice" and "测试" in d["messages"][-1]["content"]
    assert d["session"]["running"] is False


# ------------------------------------------------------------------ 4. 工具调度

def test_tool_dispatch_errors_and_reads(client: TestClient) -> None:
    from app.services import agent_tools

    bid = _book(client)
    sid = _session(client, bid)
    tc = agent_tools.ToolCtx(book_id=bid, session_id=sid)
    assert not agent_tools.dispatch(tc, "no_such_tool", {}).ok
    r = agent_tools.dispatch(tc, "get_card", {"name": "根本不存在的卡"})
    assert not r.ok and "没有找到" in r.data["error"]
    r = agent_tools.dispatch(tc, "revise_book_info", {})
    assert not r.ok and "instruction" in r.data["error"]
    assert agent_tools.dispatch(tc, "search_bible", {"query": "碎星神通"}).data["count"] >= 1
    assert agent_tools.dispatch(tc, "get_outline", {"level": "chapter"}).data["count"] > 0
    node = agent_tools.dispatch(tc, "get_outline", {"level": "book"}).data["nodes"][0]
    assert agent_tools.dispatch(tc, "get_outline_node", {"node_id": node["id"]}).data["title"] == node["title"]
    imp = agent_tools.dispatch(tc, "find_mentions", {"terms": ["碎星神通"]}).data
    assert imp["cards"] and imp["outline"]
    assert len(agent_tools.dispatch(tc, "get_banned_tropes", {}).data["banned"]) >= 5
    ws = agent_tools.dispatch(tc, "web_search", {"query": "清末民初的银元成色"})
    assert ws.ok and ws.data.get("mock")
    for name in ("get_book_info", "list_chapters", "list_foreshadows", "get_style", "get_package"):
        assert agent_tools.dispatch(tc, name, {}).ok, name
    cat = client.get("/api/agent/tools").json()
    assert cat["max_steps"] == 12 and len(cat["tools"]) == len(agent_tools.TOOLS) >= 25
    assert {t["kind"] for t in cat["tools"]} == {"read", "write"}


def test_build_messages_pairs_orphan_tool_calls(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import AgentMessage
    from app.services import agent

    bid = _book(client, outline=False)
    sid = _session(client, bid)
    with session_scope() as s:
        s.add(AgentMessage(session_id=sid, book_id=bid, role="user", content="hi"))
        s.add(AgentMessage(session_id=sid, book_id=bid, role="assistant", content="", tool_calls=[{"id": "x1", "name": "get_book_info", "arguments": {}}]))
        s.add(AgentMessage(session_id=sid, book_id=bid, role="notice", content="出错了"))
        s.commit()
    msgs = agent.build_messages(bid, sid)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]
    assert msgs[-1]["tool_call_id"] == "x1"


def test_protocol_helpers_and_text_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import protocols as proto
    from app.llm.gateway import LLMGateway, Target

    data = {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "get_card", "arguments": "{\"name\": \"林野\"}"}},
        {"id": "b", "type": "function", "function": {"name": "get_book_info", "arguments": ""}}]}}], "usage": {"prompt_tokens": 3}}
    out = proto.parse_tool_response(data)
    assert out["tool_calls"] == [{"id": "a", "name": "get_card", "arguments": {"name": "林野"}}, {"id": "b", "name": "get_book_info", "arguments": {}}]
    msgs = proto.openai_tool_messages([{"role": "assistant", "content": "", "tool_calls": out["tool_calls"]},
                                       {"role": "tool", "tool_call_id": "a", "content": "{}"}])
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == "{\"name\": \"林野\"}" and msgs[1]["role"] == "tool"
    # 非 OpenAI 格式：文本协议
    tools = [{"type": "function", "function": {"name": "get_book_info", "description": "读", "parameters": {"properties": {}}}}]
    tm = proto.text_tool_messages([{"role": "system", "content": "S"}, {"role": "user", "content": "u"},
                                   {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "get_book_info", "arguments": {}}]},
                                   {"role": "tool", "name": "get_book_info", "content": "{}"}, {"role": "user", "content": "再看"}], tools)
    assert "工具调用协议" in tm[0]["content"] and tm[-1]["role"] == "user" and "工具结果" in tm[-1]["content"]
    monkeypatch.setattr(LLMGateway, "_post_chat", lambda self, *a, **k: {"content": [{"type": "text", "text": "先读一下\n```tool\n{\"name\": \"get_book_info\", \"arguments\": {}}\n```"}]})
    r = LLMGateway()._tools_text(Target(0, "t", "http://x", "k", "m", "anthropic"), [{"role": "user", "content": "x"}], tools, 0.3)
    assert r["content"] == "先读一下" and r["tool_calls"][0]["name"] == "get_book_info"


# ------------------------------------------------------------------ 5. 各类提案

def test_bible_conflict_goes_to_review(client: TestClient) -> None:
    from app.services import agent_tools

    bid = _book(client, outline=False)
    sid = _session(client, bid)
    tc = agent_tools.ToolCtx(book_id=bid, session_id=sid)
    r = agent_tools.dispatch(tc, "propose_bible", {"mode": "add", "instruction": "加几个配角"})
    assert r.ok
    p = client.get(f"/api/agent/proposals/{r.proposal_ids[0]}").json()
    assert p["needs_review"] and p["status"] == "pending"
    assert client.post(f"/api/agent/proposals/{p['id']}/apply").status_code == 409  # 冲突必须审阅
    n0 = len(client.get(f"/api/books/{bid}/cards").json())
    clean = [x for x in p["payload"]["items"] if not x["conflicts"]]
    ops = [{"op": "create", "card": x["card"]} for x in clean]
    r2 = client.post(f"/api/agent/proposals/{p['id']}/apply", json={"ops": ops}).json()
    assert r2["proposal"]["status"] == "applied"
    assert len(client.get(f"/api/books/{bid}/cards").json()) == n0 + len(clean)
    client.post(f"/api/agent/proposals/{p['id']}/revert")
    assert len(client.get(f"/api/books/{bid}/cards").json()) == n0


def test_chapter_rewrite_proposal(client: TestClient) -> None:
    from app.services import agent_tools

    bid = _book(client)
    ch = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json())["result"]
    cid = ch.get("chapter_id") or client.get(f"/api/books/{bid}/chapters").json()[0]["id"]
    sid = _session(client, bid)
    d = _say(client, sid, "第 1 章节奏快一点，对话多一点")
    p = next(x for x in d["proposals"] if x["kind"] == "chapter_rewrite")
    assert p["payload"]["before"] != p["payload"]["after"]
    edited = p["payload"]["after"] + "\n\n（作者补的一句）"
    r = client.post(f"/api/agent/proposals/{p['id']}/apply", json={"edited": {"content": edited}}).json()
    assert r["proposal"]["status"] == "applied"
    c = client.get(f"/api/chapters/{cid}").json()
    assert c["content"] == edited and c["history"] >= 1
    client.post(f"/api/agent/proposals/{p['id']}/revert")
    assert client.get(f"/api/chapters/{cid}").json()["content"] == p["payload"]["before"]
    # 章节在提案之后被改过 → 采纳冲突
    tc = agent_tools.ToolCtx(book_id=bid, session_id=sid)
    r3 = agent_tools.dispatch(tc, "rewrite_chapter", {"number": 1, "instruction": "对话多一点"})
    client.put(f"/api/chapters/{cid}", json={"title": c["title"], "content": c["content"] + "改"})
    assert client.post(f"/api/agent/proposals/{r3.proposal_ids[0]}/apply").status_code == 409


def test_foreshadow_proposals(client: TestClient) -> None:
    from app.services import agent_tools

    bid = _book(client)
    sid = _session(client, bid)
    d = _say(client, sid, "规划 3 条伏笔")
    p = next(x for x in d["proposals"] if x["kind"] == "foreshadow_add")
    r = client.post(f"/api/agent/proposals/{p['id']}/apply").json()
    ids = r["proposal"]["result"]["ids"]
    assert len(ids) == 3
    fs = client.get(f"/api/books/{bid}/foreshadows").json()
    assert all(f["status"] == "planned" for f in fs if f["id"] in ids)
    tc = agent_tools.ToolCtx(book_id=bid, session_id=sid)
    u = agent_tools.dispatch(tc, "update_foreshadow", {"id": ids[0], "desc": "改过的伏笔", "tier": "long"})
    client.post(f"/api/agent/proposals/{u.proposal_ids[0]}/apply")
    assert next(f for f in client.get(f"/api/books/{bid}/foreshadows").json() if f["id"] == ids[0])["desc"] == "改过的伏笔"
    client.post(f"/api/agent/proposals/{u.proposal_ids[0]}/revert")
    assert next(f for f in client.get(f"/api/books/{bid}/foreshadows").json() if f["id"] == ids[0])["desc"] != "改过的伏笔"
    dl = agent_tools.dispatch(tc, "delete_foreshadow", {"id": ids[1]})
    dp = client.get(f"/api/agent/proposals/{dl.proposal_ids[0]}").json()
    assert dp["destructive"] and dp["status"] == "pending"
    client.post(f"/api/agent/proposals/{dp['id']}/apply")
    assert ids[1] not in [f["id"] for f in client.get(f"/api/books/{bid}/foreshadows").json()]
    client.post(f"/api/agent/proposals/{dp['id']}/revert")
    assert any(f["desc"] for f in client.get(f"/api/books/{bid}/foreshadows").json())
    # 撤回整批新增
    client.post(f"/api/agent/proposals/{p['id']}/revert")
    left = {f["id"] for f in client.get(f"/api/books/{bid}/foreshadows").json()}
    assert ids[0] not in left and ids[2] not in left


def test_long_jobs_write_chapter_and_covers(client: TestClient) -> None:
    client.put("/api/settings/writing", json={"auto_commit": False})  # 写完留草稿，才能演示撤回
    bid = _book(client)
    sid = _session(client, bid)
    d = _say(client, sid, "写下一章")
    p = next(x for x in d["proposals"] if x["kind"] == "write_chapter")
    assert p["status"] == "pending"
    r = client.post(f"/api/agent/proposals/{p['id']}/apply").json()
    assert r["proposal"]["status"] == "running" and r["job"]["kind"] == "chapter_write_next"
    wait_job(client, r["job"])
    p = _wait_proposal(client, p["id"])
    assert p["status"] == "applied" and p["result"]["chapter_id"]
    assert client.get(f"/api/agent/sessions/{sid}").json()["proposal_jobs"][str(p["id"])]["status"] == "succeeded"
    rv = client.post(f"/api/agent/proposals/{p['id']}/revert")
    assert rv.status_code == 200, rv.text
    assert client.get(f"/api/chapters/{p['result']['chapter_id']}").status_code == 404
    client.put("/api/settings/writing", json={"auto_commit": True})

    d = _say(client, sid, "按现在的设定改封面提示词，生成 2 张封面")
    pp = [x for x in d["proposals"] if x["kind"] in ("package", "covers")]
    assert [x["kind"] for x in pp] == ["package", "covers"]
    client.post(f"/api/agent/proposals/{pp[0]['id']}/apply")
    assert client.get(f"/api/books/{bid}/package").json()["cover_prompt"] == pp[0]["payload"]["after"]["cover_prompt"]
    r = client.post(f"/api/agent/proposals/{pp[1]['id']}/apply").json()
    wait_job(client, r["job"])
    cp = _wait_proposal(client, pp[1]["id"])
    assert len(cp["result"]["covers"]) == 2
    assert len(client.get(f"/api/books/{bid}/package").json()["covers"]) == 2
    client.post(f"/api/agent/proposals/{cp['id']}/revert")
    assert client.get(f"/api/books/{bid}/package").json()["covers"] == []


def test_package_proposal_with_trope_hits(client: TestClient) -> None:
    from app.services import agent_tools

    bid = _book(client, outline=False)
    sid = _session(client, bid)
    tc = agent_tools.ToolCtx(book_id=bid, session_id=sid)
    r = agent_tools.dispatch(tc, "propose_package", {"blurb": "他被退婚那天，血脉觉醒。", "tags": ["都市", "高武"]})
    p = client.get(f"/api/agent/proposals/{r.proposal_ids[0]}").json()
    assert {h["name"] for h in p["payload"]["trope_hits"]} >= {"退婚流", "神秘血脉"}
    client.post(f"/api/agent/proposals/{p['id']}/apply", json={"edited": {"blurb": "改成作者自己的简介"}})
    assert client.get(f"/api/books/{bid}/package").json()["blurb"] == "改成作者自己的简介"
    client.post(f"/api/agent/proposals/{p['id']}/revert")
    assert client.get(f"/api/books/{bid}/package").json()["blurb"] == ""


# ------------------------------------------------------------------ 6. 会话管理、路由、删书

def test_sessions_crud_and_routing(client: TestClient) -> None:
    bid = _book(client, outline=False)
    s1 = _session(client, bid)
    s2 = _session(client, bid)
    _say(client, s1, "你好")
    assert client.patch(f"/api/agent/sessions/{s1}", json={"title": "改名测试"}).json()["title"] == "改名测试"
    assert {x["id"] for x in client.get(f"/api/books/{bid}/agent/sessions").json()} == {s1, s2}
    c = client.post(f"/api/agent/sessions/{s1}/clear").json()
    assert c["messages"] == 0 and c["title"] == "新对话"
    assert client.get(f"/api/agent/sessions/{s1}").json()["messages"] == []
    client.delete(f"/api/agent/sessions/{s2}")
    assert client.get(f"/api/agent/sessions/{s2}").status_code == 404
    assert client.post(f"/api/agent/sessions/{s1}/messages", json={"content": ""}).status_code == 422
    assert client.post(f"/api/agent/sessions/{s1}/stop").status_code == 200
    # 设置里多了 agent 路由
    rt = client.get("/api/settings/routing").json()
    assert "agent" in rt
    # SSE：一轮结束后推送消息并关闭
    _say(client, s1, "你好")
    with client.stream("GET", f"/api/agent/sessions/{s1}/events?after=0") as r:
        body = "".join(x for x in r.iter_text())
    assert "event: message" in body and "event: done" in body
    # 删书一并删除 Agent 数据
    client.delete(f"/api/books/{bid}")
    assert client.get(f"/api/agent/sessions/{s1}").status_code == 404


# ------------------------------------------------------------------ 7. 旧库升级

def test_old_db_upgrade_adds_agent_tables_and_column(tmp_path: Any) -> None:
    from sqlmodel import SQLModel, create_engine

    from app.db import _add_missing_columns

    db = tmp_path / "v04.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE book (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, genre VARCHAR NOT NULL, gender VARCHAR NOT NULL,
          tagline VARCHAR NOT NULL, premise TEXT NOT NULL, status VARCHAR NOT NULL, target_words INTEGER NOT NULL,
          chapter_words INTEGER NOT NULL, cover_url VARCHAR, versions JSON NOT NULL DEFAULT '[]', banned_tropes JSON NOT NULL DEFAULT '[]',
          created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
        INSERT INTO book VALUES (1,'旧书','','male','','','idea',1000000,2200,NULL,'[]','[]','2026-01-01','2026-01-01');
        CREATE TABLE agentmessage (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, book_id INTEGER NOT NULL, role VARCHAR NOT NULL,
          content TEXT NOT NULL, created_at DATETIME NOT NULL);
        INSERT INTO agentmessage VALUES (1, 1, 1, 'user', '早期版本的消息', '2026-01-01');
    """)
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(eng)
    _add_missing_columns(eng)
    _add_missing_columns(eng)  # 重复执行无副作用
    con = sqlite3.connect(db)
    assert con.execute("SELECT agent_auto_apply FROM book WHERE id=1").fetchone() == (0,)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"agentsession", "agentmessage", "agentproposal"} <= tables
    row = con.execute("SELECT tool_calls, proposal_ids, job_ids, tool_call_id, status FROM agentmessage WHERE id=1").fetchone()
    assert row == ("[]", "[]", "[]", "", "ok")
    con.close()
