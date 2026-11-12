from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest

from app.auth import AuthManager, LoginBlocked, hash_password, verify_password


def test_hash_roundtrip():
    h = hash_password("hunter22", iterations=1000)
    assert verify_password("hunter22", h)
    assert not verify_password("hunter23", h)
    assert not verify_password("x", "garbage")


def test_initial_password_generated_and_change():
    d = Path(tempfile.mkdtemp())
    a = AuthManager(d, None)
    assert a.initial_password and (d / "initial_password.txt").exists()
    pw = a.initial_password
    tok, _ = a.issue(True)
    assert a.check(tok)
    assert not a.check(tok + "x")
    # 重启后仍然是同一个密码，且旧会话有效
    b = AuthManager(d, None)
    assert b.initial_password is None and b.attempt("1.1.1.1", pw) and b.check(tok)
    with pytest.raises(PermissionError):
        b.change_password("wrong", "newpassword1")
    with pytest.raises(ValueError):
        b.change_password(pw, "short")
    b.change_password(pw, "newpassword1")
    assert not b.check(tok), "改密后旧会话应失效"
    assert not (d / "initial_password.txt").exists()
    assert AuthManager(d, None).attempt("1.1.1.1", "newpassword1")


def test_env_password_and_lockout():
    a = AuthManager(Path(tempfile.mkdtemp()), "from-env-123")
    assert a.managed_by_env
    with pytest.raises(ValueError):
        a.change_password("from-env-123", "whatever123")
    for _ in range(5):
        assert not a.attempt("9.9.9.9", "nope")
    with pytest.raises(LoginBlocked):
        a.attempt("9.9.9.9", "from-env-123")
    assert a.attempt("8.8.8.8", "from-env-123")


def test_http_flow(client, monkeypatch):
    app = client.app
    monkeypatch.setattr(app.state.settings, "auth_disabled", False)
    auth = app.state.auth
    auth.password_hash = hash_password("correct-horse", iterations=1000)
    auth._fingerprint_src = auth.password_hash.encode()
    client.cookies.clear()

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/books").status_code == 401
    assert client.get("/openapi.json").status_code == 401
    st = client.get("/api/auth/status").json()
    assert st["enabled"] and not st["authenticated"]

    r = client.post("/api/auth/login", json={"password": "bad", "remember": False}, headers={"x-forwarded-for": "5.5.5.5"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"password": "correct-horse"}, headers={"x-forwarded-for": "5.5.5.6"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/books").status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"]

    # 跨站写请求被拦
    assert client.post("/api/books", json={"genre": "x", "gender": "male"}, headers={"origin": "https://evil.example"}).status_code == 403

    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/books").status_code == 401

    basic = base64.b64encode(b"any:correct-horse").decode()
    assert client.get("/api/books", headers={"authorization": f"Basic {basic}"}).status_code == 200
