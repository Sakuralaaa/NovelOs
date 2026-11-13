"""调试与调优接口：API 密钥管理、提示词/规则包线上覆盖、最近模型调用追踪。

这些接口与其它 /api 接口一样需要登录 Cookie 或 API 密钥。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.llm import trace
from app.skills import loader

router = APIRouter(prefix="/api", tags=["dev"])


# ---------- API 密钥 ----------
class KeyIn(BaseModel):
    name: str = Field(default="", max_length=40)


@router.get("/auth/keys")
def list_keys(request: Request) -> dict:
    store = request.app.state.api_keys
    return {"keys": store.list(), "env_key_enabled": store.env_key_enabled}


@router.post("/auth/keys")
def create_key(body: KeyIn, request: Request) -> dict:
    meta, token = request.app.state.api_keys.create(body.name)
    return {**meta, "token": token}


@router.delete("/auth/keys/{kid}")
def revoke_key(kid: str, request: Request) -> dict:
    if not request.app.state.api_keys.revoke(kid):
        raise HTTPException(404, "密钥不存在")
    return {"ok": True}


# ---------- 提示词覆盖 ----------
class PromptIn(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)


def _users(kind: str, name: str) -> list[str]:
    if kind == "prompts":
        return [name]
    return [task for task, packs in loader.TASK_SKILLS.items() if name in packs]


@router.get("/prompts")
def list_prompts() -> dict:
    out = []
    for kind in loader.KINDS:
        for name in loader.builtin_names(kind):
            o = loader.override_text(kind, name)
            out.append({"kind": kind, "name": name, "overridden": o is not None,
                        "chars": len(o if o is not None else loader.default_text(kind, name)),
                        "used_by": _users(kind, name)})
    return {"items": out, "system_base": loader.SYSTEM_BASE}


@router.get("/prompts/{kind}/{name}")
def get_prompt(kind: str, name: str) -> dict:
    o = loader.override_text(kind, name)
    d = loader.default_text(kind, name)
    return {"kind": kind, "name": name, "overridden": o is not None, "content": o if o is not None else d,
            "default": d, "used_by": _users(kind, name)}


@router.put("/prompts/{kind}/{name}")
def put_prompt(kind: str, name: str, body: PromptIn) -> dict:
    loader.set_override(kind, name, body.content)
    return {"ok": True, "kind": kind, "name": name, "overridden": True}


@router.delete("/prompts/{kind}/{name}")
def reset_prompt(kind: str, name: str) -> dict:
    return {"ok": True, "removed": loader.clear_override(kind, name)}


# ---------- 模型调用追踪 ----------
@router.get("/debug/llm-calls")
def llm_calls(task: str | None = None, limit: int = 50, after_id: int = 0) -> dict:
    return {"enabled": request_enabled(), "items": trace.list_calls(task, limit, after_id)}


def request_enabled() -> bool:
    from app.config import get_settings

    return get_settings().llm_trace


@router.get("/debug/llm-calls/{cid}")
def llm_call(cid: int) -> dict:
    e = trace.get_call(cid)
    if not e:
        raise HTTPException(404, "没有这条记录（可能已被新调用挤出，或服务重启过）")
    return e


@router.delete("/debug/llm-calls")
def clear_llm_calls() -> dict:
    trace.clear()
    return {"ok": True}
