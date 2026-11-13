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
