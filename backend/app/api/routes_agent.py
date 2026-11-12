"""v0.5：每本书的专属 Agent —— 会话、消息、提案（采纳 / 拒绝 / 撤回）、步骤事件流（SSE）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import book_out, job_out
from app.db import get_session, session_scope
from app.models.tables import AgentProposal, Book
from app.services import agent, agent_proposals, agent_tools

router = APIRouter(prefix="/api")


class SessionIn(BaseModel):
    title: str | None = None


class SessionPatch(BaseModel):
    title: str = Field(min_length=1, max_length=40)


class AgentSendIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    route: str | None = None


class AgentSettingsIn(BaseModel):
    auto_apply: bool


class ProposalApplyIn(BaseModel):
    edited: dict[str, Any] | None = None  # 编辑后采纳：作者改过的内容
    ops: list[dict[str, Any]] | None = None  # 设定库冲突审阅的逐条选择


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


@router.get("/agent/tools")
def tools() -> dict[str, Any]:
    return {"tools": agent_tools.catalog(), "max_steps": agent.MAX_STEPS, "examples": agent.EXAMPLES}


@router.get("/books/{book_id}/agent/settings")
def agent_settings(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    return {"auto_apply": bool(_book(s, book_id).agent_auto_apply)}


@router.put("/books/{book_id}/agent/settings")
def put_agent_settings(book_id: int, body: AgentSettingsIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    b.agent_auto_apply = body.auto_apply
    s.add(b)
    s.commit()
    s.refresh(b)
    return {"auto_apply": bool(b.agent_auto_apply), "book": book_out(s, b)}


@router.get("/books/{book_id}/agent/sessions")
def list_sessions(book_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return agent.list_sessions(s, book_id)


@router.post("/books/{book_id}/agent/sessions")
def create_session(book_id: int, body: SessionIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    a = agent.create_session(s, book_id, body.title if body else None)
    return agent.session_out(s, a)


@router.get("/agent/sessions/{sid}")
def get_session_detail(sid: int, after: int = 0, s: Session = Depends(get_session)) -> dict[str, Any]:
    return agent.detail(s, sid, after)


@router.patch("/agent/sessions/{sid}")
def rename_session(sid: int, body: SessionPatch, s: Session = Depends(get_session)) -> dict[str, Any]:
    a = agent.get_session_obj(s, sid)
    a.title = body.title.strip()
    s.add(a)
    s.commit()
    s.refresh(a)
    return agent.session_out(s, a)


@router.post("/agent/sessions/{sid}/clear")
def clear_session(sid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    return agent.session_out(s, agent.clear_session(s, sid))


@router.delete("/agent/sessions/{sid}")
def delete_session(sid: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    agent.delete_session(s, sid)
    return {"ok": True}


@router.post("/agent/sessions/{sid}/messages")
async def send_message(sid: int, body: AgentSendIn) -> dict[str, Any]:
    """发一条消息，后台跑一轮 Agent（返回 Job）。进度：轮询 GET /agent/sessions/{sid}?after= 或订阅 /events。"""
    m, job = agent.send(sid, body.content, body.route)
    return {"message": agent.message_out(m), "job": job_out(job)}


@router.post("/agent/sessions/{sid}/stop")
def stop(sid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    return agent.session_out(s, agent.request_stop(s, sid))


@router.get("/agent/sessions/{sid}/events")
async def events(sid: int, after: int = 0) -> StreamingResponse:
    """SSE：逐步推送新消息（assistant / 工具结果 / 提示）、提案状态和运行状态；本轮结束后发 done 并关闭。"""
    async def gen():  # type: ignore[no-untyped-def]
        last_id, last_state, idle = after, "", 0
        while True:
            with session_scope() as s:
                try:
                    d = agent.detail(s, sid, last_id)
                except Exception:  # noqa: BLE001
                    yield "event: error\ndata: {\"detail\":\"会话不存在\"}\n\n"
                    return
            for m in d["messages"]:
                last_id = max(last_id, m["id"] or 0)
                yield f"event: message\ndata: {json.dumps(m, ensure_ascii=False)}\n\n"
            state = json.dumps({"job": d["job"], "proposals": [(p["id"], p["status"]) for p in d["proposals"]],
                                "pj": d["proposal_jobs"]}, ensure_ascii=False)
            if state != last_state:
                last_state = state
                yield f"event: state\ndata: {json.dumps({'job': d['job'], 'proposals': d['proposals'], 'proposal_jobs': d['proposal_jobs']}, ensure_ascii=False)}\n\n"
            running = d["job"] is not None or any(p["status"] == "running" for p in d["proposals"])
            idle = 0 if running else idle + 1
            if idle >= 2:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.8)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/agent/proposals/{pid}")
def get_proposal(pid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    p = s.get(AgentProposal, pid)
    if p is None:
        raise HTTPException(404, "提案不存在")
    return agent_proposals.proposal_out(p)


@router.post("/agent/proposals/{pid}/apply")
def apply_proposal(pid: int, body: ProposalApplyIn | None = Body(default=None)) -> dict[str, Any]:
    r = agent_proposals.apply(pid, body.edited if body else None, body.ops if body else None)
    out: dict[str, Any] = {"proposal": r["proposal"], "job": None}
    if r["job_id"]:
        with session_scope() as s:
            from app.models.tables import Job

            j = s.get(Job, r["job_id"])
            out["job"] = job_out(j) if j else None
    return out


@router.post("/agent/proposals/{pid}/reject")
def reject_proposal(pid: int) -> dict[str, Any]:
    return agent_proposals.proposal_out(agent_proposals.reject(pid))


@router.post("/agent/proposals/{pid}/revert")
def revert_proposal(pid: int) -> dict[str, Any]:
    return agent_proposals.proposal_out(agent_proposals.revert(pid))
