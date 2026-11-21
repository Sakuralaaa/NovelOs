"""v0.19 Agent 接入（MCP）。"""

from __future__ import annotations

import json
from typing import Any

from conftest import wait_job


def rpc(client, method: str, params: dict[str, Any] | None = None, mid: int = 1) -> dict[str, Any]:
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()


def call(client, _tool: str, **args: Any) -> tuple[bool, str]:
    res = rpc(client, "tools/call", {"name": _tool, "arguments": args})["result"]
    return not res["isError"], res["content"][0]["text"]


def test_mcp_handshake_and_tools(client) -> None:
    init = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    names = {t["name"] for t in rpc(client, "tools/list")["result"]["tools"]}
    assert {"save_chapter", "chapter_brief", "call_model", "api"} <= names
    assert client.get("/api/mcp-info").json()["url"].endswith("/api/mcp")


def test_mcp_agent_writes_book(client) -> None:
    ok, txt = call(client, "create_book", title="接入测试", genre="玄幻", premise="少年得到会说话的剑")
    assert ok, txt
    bid = json.loads(txt)["id"]
    ok, txt = call(client, "save_card", book_id=bid, type="character", name="林远", summary="主角")
    assert ok, txt
    ok, txt = call(client, "save_outline_node", book_id=bid, level="chapter", order=1, title="剑醒", summary="林远捡到剑")
    assert ok, txt
    ok, brief = call(client, "chapter_brief", book_id=bid, number=1, with_rules=False)
    assert ok, brief
    assert "context" in json.loads(brief)
    ok, txt = call(client, "save_chapter", book_id=bid, number=1, title="剑醒", content="林远推开柴门。" * 200, commit=True)
    assert ok, txt
    r = json.loads(txt)
    assert r["words"] > 0 and r["job"]["id"]
    wait_job(client, r["job"])
    ok, txt = call(client, "list_chapters", book_id=bid)
    assert ok and "committed" in txt
    ok, txt = call(client, "api", method="GET", path=f"/api/books/{bid}")
    assert ok, txt
    ok, txt = call(client, "api", method="GET", path="/api/auth/keys")
    assert not ok
    ok, txt = call(client, "call_model", prompt="写一句话")
    assert ok and txt
    ok, txt = call(client, "get_card", book_id=bid)
    assert not ok or txt
