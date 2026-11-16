"""v0.11 完本模式接口。调模型的接口（规划、分批连写、章节迭代）一律走后台 Job + 轮询 GET /api/jobs/{id}；其余同步。"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import job_out
from app.db import get_session
from app.jobs.manager import find_active, submit
from app.models.tables import Book
from app.services import wanben

router = APIRouter(prefix="/api")

RangeItem = Union[int, str, list[int]]


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


def _job(j: Any) -> dict[str, Any]:
    out = job_out(j)
    return {**out, "job_id": out["id"]}


def _need_wanben(b: Book) -> None:
    if wanben.book_mode(b) != "wanben":
        raise HTTPException(409, "本书是连载模式，请先在完本设置里把模式切换为完本（mode=wanben）")


class WanbenSettingsIn(BaseModel):
    mode: Optional[Literal["serial", "wanben"]] = None
    target_words: Optional[int] = Field(default=None, ge=10_000, le=10_000_000)
    chapter_words: Optional[int] = Field(default=None, ge=500, le=20_000)
    batch_size: Optional[int] = Field(default=None, ge=1, le=50)
    refine_scope: Optional[Literal["first_n", "all", "custom", "none"]] = None
    golden_chapters: Optional[int] = Field(default=None, ge=0, le=5000)
    refine_ranges: Optional[list[RangeItem]] = None
    pause_on_unapproved_refine: Optional[bool] = None
    auto_continue: Optional[bool] = None


class RefineEditIn(BaseModel):
    action: Literal["add", "remove", "set"] = "add"
    ranges: list[RangeItem] = Field(default_factory=list)


class BatchIn(BaseModel):
    force: bool = False  # 精修范围有待审批章时也继续写（忽略「精修待审批时暂停」）


class IterateIn(BaseModel):
    start: Optional[int] = Field(default=None, ge=1)
    end: Optional[int] = Field(default=None, ge=1)
    numbers: list[int] = Field(default_factory=list)
    ranges: list[RangeItem] = Field(default_factory=list)
    instruction: str = Field(default="", max_length=2000)
    method: Literal["auto", "patch", "rewrite"] = "auto"
    rounds: int = Field(default=1, ge=1, le=wanben.MAX_ITER_ROUNDS)
    route: Optional[str] = None


# ------------------------------------------------------------------ 设置

@router.get("/books/{book_id}/wanben")
def get_wanben(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    return {**wanben.settings_out(s, b), "plan": wanben.plan_summary(s, book_id)}


@router.put("/books/{book_id}/wanben")
def put_wanben(book_id: int, body: WanbenSettingsIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    out = wanben.update_settings(s, b, body.model_dump(exclude_none=True))
    return {**out, "plan": wanben.plan_summary(s, book_id)}


# ------------------------------------------------------------------ 规划

@router.post("/books/{book_id}/wanben/plan")
async def plan(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    _need_wanben(b)
    ref = f"wanben:{book_id}"
    active = find_active(wanben.PLAN_KIND, ref)
    if active is not None:
        return _job(active)
    return _job(submit(wanben.PLAN_KIND, lambda ctx: wanben.plan_job(book_id, ctx), book_id=book_id, lock_book=True, ref=ref))


@router.get("/books/{book_id}/wanben/plan")
def get_plan(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return wanben.plan_summary(s, book_id)


# ------------------------------------------------------------------ 分批连写

@router.post("/books/{book_id}/wanben/batch")
async def batch(book_id: int, body: BatchIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    _need_wanben(b)
    ref = f"wanben:{book_id}"
    active = find_active(wanben.BATCH_KIND, ref)
    if active is not None:
        return _job(active)
    force = bool(body.force) if body else False
    wanben.set_pause(book_id, False)
    wanben.close_stale_batches(book_id)
    return _job(submit(wanben.BATCH_KIND, lambda ctx: wanben.batch_job(book_id, ctx, force=force), book_id=book_id,
                       lock_book=True, ref=ref))


@router.post("/books/{book_id}/wanben/batch/pause")
def pause_batch(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    wanben.set_pause(book_id, True)
    rb = wanben.running_batch(s, book_id)
    active = find_active(wanben.BATCH_KIND, f"wanben:{book_id}")
    return {"ok": True, "paused": True, "running_batch_id": rb.id if rb else None, "job_id": active.id if active else None,
            "message": "当前章写完后暂停" if active else "没有正在跑的批次；下次发起连写会自动清除暂停"}


@router.get("/books/{book_id}/wanben/batches")
def batches(book_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return wanben.list_batches(s, book_id)


@router.get("/books/{book_id}/wanben/batches/{batch_id}")
def one_batch(book_id: int, batch_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return wanben.get_batch(s, book_id, batch_id)


# ------------------------------------------------------------------ 精修范围

@router.get("/books/{book_id}/wanben/refine")
def refine(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return wanben.refine_summary(s, book_id)


@router.get("/books/{book_id}/wanben/golden")
def golden(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    """兼容旧名：同 GET /wanben/refine。"""
    _book(s, book_id)
    return wanben.refine_summary(s, book_id)


@router.post("/books/{book_id}/wanben/refine")
def edit_refine(book_id: int, body: RefineEditIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    wanben.edit_refine(s, b, body.action, body.ranges)
    return wanben.refine_summary(s, book_id)


# ------------------------------------------------------------------ 章节迭代

@router.post("/books/{book_id}/wanben/iterate")
async def iterate(book_id: int, body: IterateIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    params = body.model_dump()
    if not wanben.select_chapters(s, book_id, params):
        raise HTTPException(409, "所选范围内没有已写正文的章节")
    wanben.clear_iterate_stop(book_id)
    return _job(submit(wanben.ITERATE_KIND, lambda ctx: wanben.iterate_job(book_id, params, ctx), book_id=book_id,
                       lock_book=True, ref=f"wanben:{book_id}"))


@router.post("/books/{book_id}/wanben/iterate/stop")
def iterate_stop(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    wanben.request_iterate_stop(book_id)
    return {"ok": True, "message": "当前这一轮结束后停止"}


@router.get("/books/{book_id}/wanben/iterations")
def iterations(book_id: int, number: Optional[int] = Query(default=None), chapter_id: Optional[int] = Query(default=None),
               status: Optional[Literal["pending", "adopted", "discarded"]] = Query(default=None),
               s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return wanben.list_iterations(s, book_id, number, chapter_id, status)


@router.get("/books/{book_id}/wanben/iterations/{iteration_id}")
def one_iteration(book_id: int, iteration_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.models.tables import Chapter

    _book(s, book_id)
    it = wanben.get_iteration(s, book_id, iteration_id)
    ch = s.get(Chapter, it.chapter_id)
    return wanben.iteration_out(it, with_content=True, current=ch.content if ch else "")


@router.post("/books/{book_id}/wanben/iterations/{iteration_id}/adopt")
def adopt_iteration(book_id: int, iteration_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return wanben.adopt_iteration(book_id, iteration_id)


@router.post("/books/{book_id}/wanben/iterations/{iteration_id}/discard")
def discard_iteration(book_id: int, iteration_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return wanben.discard_iteration(book_id, iteration_id)


# ------------------------------------------------------------------ 进度 / 导出

@router.get("/books/{book_id}/wanben/progress")
def progress(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return wanben.progress(s, book_id)


@router.get("/books/{book_id}/wanben/export.txt")
def export_txt(book_id: int, s: Session = Depends(get_session)) -> Response:
    _book(s, book_id)
    title, text = wanben.export_txt(book_id)
    fname = f"{title}.txt"
    return Response(content=text.encode("utf-8"), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=\"novelos_{book_id}.txt\"; filename*=UTF-8''{quote(fname)}"})
