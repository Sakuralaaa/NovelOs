from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.apikeys import ApiKeyStore, token_from_headers


def test_store_roundtrip():
    d = Path(tempfile.mkdtemp())
    s = ApiKeyStore(d)
    meta, tok = s.create("hark")
    assert tok.startswith("nvk_") and s.check(tok)
    assert not s.check(tok + "x") and not s.check("nvk_bad") and not s.check(None)
    assert ApiKeyStore(d).check(tok), "重启后仍有效"
    assert "hash" not in s.list()[0] and s.list()[0]["preview"].endswith(tok[-4:])
    assert s.revoke(meta["id"]) and not s.check(tok)
    env = ApiKeyStore(d, "nvk_fixed_abcdef")
    assert env.check("nvk_fixed_abcdef") and env.env_key_enabled


def test_header_parse():
    assert token_from_headers({"authorization": "Bearer nvk_a_b"}) == "nvk_a_b"
    assert token_from_headers({"x-api-key": "nvk_a_b"}) == "nvk_a_b"
    assert token_from_headers({"authorization": "Basic xxx"}) is None


def test_auth_middleware_with_key(monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    s = get_settings()
    monkeypatch.setattr(s, "auth_disabled", False)
    app = create_app()
    with TestClient(app) as c:
        assert c.get("/api/books").status_code == 401
        meta, tok = app.state.api_keys.create("t")
        h = {"Authorization": f"Bearer {tok}"}
        assert c.get("/api/books", headers=h).status_code == 200
        # 带 Origin 的写请求，用密钥时不做同源校验
        r = c.post("/api/auth/keys", json={"name": "x"}, headers={**h, "Origin": "https://evil.example"})
        assert r.status_code == 200 and r.json()["token"].startswith("nvk_")
        assert c.get("/api/books", headers={"X-API-Key": "nvk_zz_wrong"}).status_code == 401
        c.delete(f"/api/auth/keys/{meta['id']}", headers={"X-API-Key": r.json()["token"]})
        assert c.get("/api/books", headers=h).status_code == 401


def test_prompt_override_and_trace(client):
    from app.skills import loader

    items = client.get("/api/prompts").json()["items"]
    assert any(i["kind"] == "prompts" and i["name"] == "ideation" for i in items)
    assert any(i["kind"] == "rules" and i["name"] == "writing" and "writing_scene" in i["used_by"] for i in items)
    orig = client.get("/api/prompts/prompts/summary").json()
    assert not orig["overridden"]
    r = client.put("/api/prompts/prompts/summary", json={"content": "覆盖版 $title"})
    assert r.status_code == 200
    assert loader.render("summary", title="X") == "覆盖版 X"
    r = client.put("/api/prompts/rules/writing", json={"content": "---\nstage: writing\n---\n规则覆盖"})
    assert "规则覆盖" in loader.system_prompt("writing_scene")
    assert client.delete("/api/prompts/prompts/summary").json()["removed"]
    client.delete("/api/prompts/rules/writing")
    assert loader.render("summary", title="X") != "覆盖版 X"
    assert "规则覆盖" not in loader.system_prompt("writing_scene")
    assert client.put("/api/prompts/prompts/../../etc", json={"content": "x"}).status_code in (400, 404)
    assert client.get("/api/prompts/prompts/nope").status_code == 400

    from app.llm.gateway import get_gateway

    client.delete("/api/debug/llm-calls")
    get_gateway().chat("summary", [{"role": "user", "content": "你好"}])
    lst = client.get("/api/debug/llm-calls").json()["items"]
    assert lst and lst[0]["task"] == "summary" and lst[0]["model"] == "mock"
    full = client.get(f"/api/debug/llm-calls/{lst[0]['id']}").json()
    assert full["messages"][0]["content"] == "你好"


def test_routing_partial_update_keeps_others(client):
    ch = client.post("/api/settings/channels", json={"name": "t", "base_url": "http://x/v1", "api_key": "k", "models": ["a", "b"]}).json()
    cid = ch["id"]
    client.put("/api/settings/routing", json={"planner": f"{cid}:a", "writer": f"{cid}:b"})
    r = client.put("/api/settings/routing", json={"planner": f"{cid}:b"}).json()
    assert r["planner"] == f"{cid}:b" and r["writer"] == f"{cid}:b"
    r = client.put("/api/settings/routing", json={"writer": None}).json()
    assert r["writer"] is None and r["planner"] == f"{cid}:b"
    client.put("/api/settings/routing", json={"planner": None})
    client.delete(f"/api/settings/channels/{cid}")


def test_stream_fallback(monkeypatch):
    import httpx

    from app.llm import gateway as g

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        b = _j.loads(req.content)
        if not b.get("stream"):
            return httpx.Response(400, json={"error": {"message": "Non-stream chat request is currently not supported (11101)"}})
        if req.url.path.endswith("/responses"):
            sse = ('data: {"type":"response.output_text.delta","delta":"你"}\n\n'
                   'data: {"type":"response.output_text.delta","delta":"好"}\n\n'
                   'data: {"type":"response.completed","response":{"usage":{"input_tokens":3,"output_tokens":2}}}\n\n')
        else:
            sse = ('data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
                   'data: {"choices":[{"delta":{"content":"好"}}],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
                   "data: [DONE]\n\n")
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(g, "_keepalive_transport", lambda: httpx.MockTransport(handler))
    for fmt in ("openai", "responses"):
        t = g.Target(0, "t", "http://x/v1", "k", "m", fmt)
        data = g.LLMGateway()._post_chat(t, [{"role": "user", "content": "hi"}], 0.5, 10)
        from app.llm import protocols as proto
        text, usage, _ = proto.parse_chat(fmt, data)
        assert text == "你好" and usage["completion_tokens"] == 2


def test_scene_state_prop_prefix_dedup():
    from app.services.scene_state import merge_state, normalize_scene_state
    a = normalize_scene_state({"props": [{"name": "牌匾", "where": "长案底座"}]})
    b = normalize_scene_state({"props": [{"name": "道具·牌匾", "where": "叶承怀里"}]})
    m = merge_state(a, b)
    assert [p["name"] for p in m["props"]] == ["牌匾"] and m["props"][0]["where"] == "叶承怀里"
