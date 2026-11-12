"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import routes_agent, routes_auth, routes_books, routes_core
from app.auth import COOKIE_NAME, AuthManager
from app.config import get_settings
from app.db import init_engine
from app.jobs.manager import recover_on_startup
from app.llm.gateway import LLMError
from app.radar.service import daily_scheduler
from app.services.common import Conflict, NotFound

log = logging.getLogger("novelos")


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        n = recover_on_startup()
        if n:
            log.warning("已将 %s 个中断的任务标记为 failed", n)
        stop = asyncio.Event()
        task = None
        if not settings.disable_scheduler:
            task = asyncio.create_task(daily_scheduler(stop))
        yield
        stop.set()
        if task:
            task.cancel()

    app = FastAPI(title="NovelOS", version=__version__, lifespan=lifespan)

    auth = AuthManager(settings.data_dir, settings.password or settings.basic_password, settings.basic_user)
    app.state.auth = auth
    app.state.settings = settings

    @app.middleware("http")
    async def security(request: Request, call_next):
        path = request.url.path
        protected = path.startswith(PROTECTED_PREFIXES) and path not in PUBLIC_PATHS
        if protected and not settings.auth_disabled and not _authorized(request, auth):
            return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
        # 写操作校验来源，防跨站请求伪造（配合 SameSite=Lax Cookie）
        origin = request.headers.get("origin")
        if protected and request.method not in ("GET", "HEAD", "OPTIONS") and origin and not settings.auth_disabled:
            parsed = urlsplit(origin)
            host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).lower()
            if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != host:
                return PlainTextResponse("Origin not allowed", status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(Conflict)
    async def _cf(_: Request, e: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(LLMError)
    async def _llm(_: Request, e: LLMError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=502)

    @app.exception_handler(ValueError)
    async def _ve(_: Request, e: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def _rv(_: Request, e: RequestValidationError) -> JSONResponse:
        errs = e.errors()
        msg = "；".join(f"{'.'.join(str(x) for x in err.get('loc', [])[1:])}: {err.get('msg')}" for err in errs[:5])
        return JSONResponse({"detail": f"参数错误：{msg}"}, status_code=422)

    app.include_router(routes_auth.router)
    app.include_router(routes_core.router)
    app.include_router(routes_books.router)
    app.include_router(routes_agent.router)
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

    _mount_spa(app, settings.static_dir)
    return app


PROTECTED_PREFIXES = ("/api/", "/media/", "/docs", "/redoc", "/openapi.json")
PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"}


def _authorized(request: Request, auth: AuthManager) -> bool:
    if auth.check(request.cookies.get(COOKIE_NAME)):
        return True
    # 兼容脚本调用：Authorization: Basic base64(任意用户名:密码)
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode()
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return False
    _, sep, password = decoded.partition(":")
    return bool(sep) and auth.verify_cached(password)


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.is_file():
        log.info("未找到前端静态文件 %s，只提供 API", index)
        return
    root = static_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith(("api/", "media/")):
            raise HTTPException(404, "Not Found")
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
