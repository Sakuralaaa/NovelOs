"""登录相关接口。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import COOKIE_NAME, MIN_PASSWORD_LEN, LoginBlocked

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    remember: bool = True


class PasswordIn(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


def client_ip(request: Request) -> str:
    # 反向代理（Nginx/Caddy）后面时取 X-Forwarded-For 的第一个地址
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip().lower() == "https"


def is_authenticated(request: Request) -> bool:
    auth = request.app.state.auth
    if request.app.state.settings.auth_disabled:
        return True
    return auth.check(request.cookies.get(COOKIE_NAME))


@router.get("/status")
def status(request: Request) -> dict:
    s = request.app.state.settings
    auth = request.app.state.auth
    return {
        "enabled": not s.auth_disabled,
        "authenticated": is_authenticated(request),
        "username": auth.username,
        "managed_by_env": auth.managed_by_env,
        "min_password_len": MIN_PASSWORD_LEN,
    }


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict:
    auth = request.app.state.auth
    s = request.app.state.settings
    ip = client_ip(request)
    try:
        ok = await asyncio.to_thread(auth.attempt, ip, body.password)
    except LoginBlocked as e:
        raise HTTPException(429, f"失败次数过多，请 {max(1, e.retry_after // 60)} 分钟后再试",
                            headers={"Retry-After": str(e.retry_after)})
    if not ok:
        await asyncio.sleep(0.6)
        left = auth.remaining_attempts(ip)
        msg = "密码不正确" + (f"，还可尝试 {left} 次" if 0 < left <= 3 else "")
        if left == 0:
            msg = "失败次数过多，已锁定 15 分钟"
        raise HTTPException(401, msg)
    token, ttl = auth.issue(body.remember)
    secure = s.cookie_secure if s.cookie_secure is not None else is_https(request)
    response.set_cookie(
        COOKIE_NAME, token, max_age=ttl if body.remember else None, httponly=True,
        samesite="lax", secure=secure, path="/",
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/password")
async def change_password(body: PasswordIn, request: Request, response: Response) -> dict:
    if not is_authenticated(request):
        raise HTTPException(401, "未登录")
    auth = request.app.state.auth
    try:
        await asyncio.to_thread(auth.change_password, body.current, body.new)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    # 改密后旧会话失效，给当前浏览器重新签发
    token, ttl = auth.issue(True)
    s = request.app.state.settings
    secure = s.cookie_secure if s.cookie_secure is not None else is_https(request)
    response.set_cookie(COOKIE_NAME, token, max_age=ttl, httponly=True, samesite="lax", secure=secure, path="/")
    return {"ok": True}
