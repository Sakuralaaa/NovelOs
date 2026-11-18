"""v0.16 一键成书接口。开始/继续/拍板会起后台任务（kind=autopilot），进度看 GET /books/{id}/autopilot。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import book_out, job_out
from app.db import get_session
from app.models.tables import Book
from app.services import autopilot as ap
from app.services.common import Conflict, NotFound

router = APIRouter(prefix="/api")


class AutoSettingsIn(BaseModel):
    level: Optional[Literal["full", "guided"]] = None
    stop_on: Optional[list[Literal["opening", "volume"]]] = None
    target_words: Optional[int] = Field(default=None, ge=10_000, le=5_000_000)
    chapter_words: Optional[int] = Field(default=None, ge=1000, le=6000)
    batch_size: Optional[int] = Field(default=None, ge=1, le=30)
    golden_chapters: Optional[int] = Field(default=None, ge=0, le=30)
    max_cost_cny: Optional[float] = Field(default=None, ge=0)


class AnswerIn(BaseModel):
    choice: Optional[int] = None
    custom: str = Field(default="", max_length=1000)


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


def _http(e: Exception) -> HTTPException:
    if isinstance(e, NotFound):
        return HTTPException(404, str(e))
    if isinstance(e, Conflict):
        return HTTPException(409, str(e))
    return HTTPException(400, str(e))


@router.get("/books/{book_id}/autopilot")
def get_autopilot(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return ap.overview(s, book_id)


@router.put("/books/{book_id}/autopilot/settings")
def put_settings(book_id: int, body: AutoSettingsIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    try:
        return ap.save_settings(s, book_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise _http(e) from e


@router.post("/books/{book_id}/autopilot/start")
async def start(book_id: int, body: Optional[AutoSettingsIn] = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    try:
        run, job = ap.start(book_id, body.model_dump(exclude_unset=True) if body else {})
    except (Conflict, NotFound, ValueError) as e:
        raise _http(e) from e
    return {"run_id": run.id, "job": job_out(job)}


@router.post("/books/{book_id}/autopilot/pause")
def pause(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return ap.pause(book_id)


@router.post("/books/{book_id}/autopilot/decisions/{decision_id}")
async def answer(book_id: int, decision_id: int, body: AnswerIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    try:
        return ap.answer(book_id, decision_id, body.choice, body.custom)
    except (Conflict, NotFound, ValueError) as e:
        raise _http(e) from e


@router.post("/books/{book_id}/autopilot/flags/{chapter_id}/resolve")
def resolve_flag(book_id: int, chapter_id: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    _book(s, book_id)
    try:
        ap.resolve_flag(book_id, chapter_id)
    except NotFound as e:
        raise _http(e) from e
    return {"ok": True}


@router.post("/books/{book_id}/autopilot/flags/{chapter_id}/accept")
async def accept_flag(book_id: int, chapter_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    """v0.17「待你看」的章作者放行：照现在的正文提交（后台任务，含摘要），划掉清单；之后点继续接着写。"""
    from app.jobs.manager import submit
    from app.models.tables import Chapter

    _book(s, book_id)
    ch = s.get(Chapter, chapter_id)
    if ch is None or ch.book_id != book_id:
        raise HTTPException(404, "章节不存在")
    if not (ch.content or "").strip():
        raise HTTPException(409, "这一章正文为空，先采纳一个版本")
    return job_out(submit("autopilot_accept", lambda ctx: ap.accept_flag(book_id, chapter_id), book_id=book_id))


@router.post("/books/{book_id}/autopilot/flags/{chapter_id}/replan")
async def replan_flag(book_id: int, chapter_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    """v0.17.1「待你看」的章：对照上一章实写重新校正章纲，再自动整章重写；过审就提交，之后点继续接着写。"""
    from app.jobs.manager import submit
    from app.models.tables import Chapter

    _book(s, book_id)
    ch = s.get(Chapter, chapter_id)
    if ch is None or ch.book_id != book_id:
        raise HTTPException(404, "章节不存在")
    if ch.status == "committed":
        raise HTTPException(409, "这一章已经提交了")
    if ap.find_active(ap.KIND, ap._ref(book_id)):  # noqa: SLF001
        raise HTTPException(409, "一键成书正在跑，先暂停")
    return job_out(submit("autopilot_replan", lambda ctx: ap.replan_flag(book_id, chapter_id), book_id=book_id))


@router.post("/ideas/{idea_id}/autopilot")
async def idea_autopilot(idea_id: int, body: Optional[AutoSettingsIn] = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    """选题一键成书：采纳建书 + 开始一键成书。"""
    from app.services import planning

    try:
        book = planning.adopt_idea(idea_id)
        run, job = ap.start(book.id or 0, body.model_dump(exclude_unset=True) if body else {})
    except (Conflict, NotFound, ValueError) as e:
        raise _http(e) from e
    b = s.get(Book, book.id)
    return {"book": book_out(s, b or book), "run_id": run.id, "job": job_out(job)}
