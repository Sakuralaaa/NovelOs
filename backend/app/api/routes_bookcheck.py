"""v0.11 完本模式·质检：整书体检、短剧可改编度、短剧分镜档单章自查、同质化自查。

调模型的接口一律走后台 Job（jobs.manager.submit）；结果存在 Job.result，按书查最新与历史。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import job_out
from app.db import get_session
from app.jobs.manager import find_active, submit
from app.models.tables import Book, Chapter, Idea
from app.services import adaptability, book_check, common
from app.skills.loader import PLATFORM_LABEL, PLATFORMS

router = APIRouter(prefix="/api")


def _job(j: Any) -> dict[str, Any]:
    out = job_out(j)
    return {**out, "job_id": out["id"]}


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


# ------------------------------------------------------------------ 平台风格档（含 v0.11 短剧分镜）

@router.get("/platform-styles")
def platform_styles() -> dict[str, Any]:
    """可选的平台风格档：[{id, label}]；duanju（短剧分镜）为 v0.11 新增的可选档。"""
    return {"items": [{"id": p, "label": PLATFORM_LABEL.get(p, p), "optional": p == "duanju"} for p in PLATFORMS]}


# ------------------------------------------------------------------ 整书体检

class BookCheckIn(BaseModel):
    llm: bool = True  # false：只跑规则层（不调模型，也走 Job，长书逐章 lint 较耗时）


@router.post("/books/{book_id}/book-check")
async def start_book_check(book_id: int, body: BookCheckIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    ref = f"book:{book_id}"
    active = find_active(book_check.KIND, ref)
    if active is not None:
        return _job(active)
    use_llm = body.llm if body else True
    return _job(submit(book_check.KIND, lambda ctx: book_check.run(book_id, ctx, use_llm=use_llm), book_id=book_id, ref=ref))


@router.get("/books/{book_id}/book-check")
def get_book_check(book_id: int, job_id: int | None = Query(None), s: Session = Depends(get_session)) -> dict[str, Any]:
    """最新一次（或指定 job_id 的）体检报告；还没做过时 report 为 null。"""
    _book(s, book_id)
    return {"report": book_check.latest(s, book_id, job_id=job_id)}


@router.get("/books/{book_id}/book-check/history")
def book_check_history(book_id: int, limit: int = Query(30, ge=1, le=100), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return {"items": book_check.history(s, book_id, limit=limit)}


# ------------------------------------------------------------------ 短剧可改编度

class AdaptIn(BaseModel):
    start: int | None = Field(default=None, ge=1)
    end: int | None = Field(default=None, ge=1)
    llm: bool = True


@router.post("/books/{book_id}/adaptability")
async def start_adaptability(book_id: int, body: AdaptIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    b = body or AdaptIn()
    if b.start is not None and b.end is not None and b.start > b.end:
        raise HTTPException(422, "起始章号不能大于结束章号")
    return _job(submit(adaptability.KIND, lambda ctx: adaptability.run(book_id, b.start, b.end, ctx, use_llm=b.llm),
                       book_id=book_id, ref=f"book:{book_id}"))


@router.get("/books/{book_id}/adaptability")
def get_adaptability(book_id: int, job_id: int | None = Query(None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return {"report": book_check.latest(s, book_id, kind=adaptability.KIND, job_id=job_id)}


@router.get("/books/{book_id}/adaptability/history")
def adaptability_history(book_id: int, limit: int = Query(30, ge=1, le=100), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    rows = []
    for it in book_check.history(s, book_id, kind=adaptability.KIND, limit=limit):
        rep = book_check.latest(s, book_id, kind=adaptability.KIND, job_id=it["job_id"]) or {}
        rows.append({"job_id": it["job_id"], "created_at": it["created_at"], "updated_at": it["updated_at"],
                     "score": rep.get("score"), "range": rep.get("range"), "episodes_per_chapter": rep.get("episodes_per_chapter"),
                     "llm_used": bool(rep.get("llm_used"))})
    return {"items": rows}


@router.post("/chapters/{chapter_id}/duanju-check")
def chapter_duanju_check(chapter_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    """短剧分镜档单章自查（同步、纯规则）。"""
    ch = s.get(Chapter, chapter_id)
    if ch is None:
        raise HTTPException(404, "章节不存在")
    names = [c.name for c in common.cards(s, ch.book_id)]
    return {"chapter_id": chapter_id, "number": ch.number, **adaptability.duanju_check(ch.content or "", names)}


# ------------------------------------------------------------------ 同质化自查

class HomoIn(BaseModel):
    llm: bool = False  # true：再让模型给差异化建议（走 Job）
    top_n: int = Field(default=adaptability.HOMO_TOP_N, ge=5, le=200)


def _homogeneity(target: str, tid: int, body: HomoIn | None, book_id: int | None) -> dict[str, Any]:
    b = body or HomoIn()
    if b.llm:
        return {"mode": "job", "job": _job(submit(adaptability.HOMO_KIND, lambda ctx: adaptability.homogeneity_job(target, tid, b.top_n, ctx),
                                                  book_id=book_id, ref=f"{target}:{tid}"))}
    from app.db import session_scope

    with session_scope() as s2:
        mine = adaptability.mine_from_book(s2, tid) if target == "book" else adaptability.mine_from_idea(s2, tid)
        return {"mode": "sync", "report": adaptability.homogeneity_rules(s2, mine, b.top_n)}


@router.post("/books/{book_id}/homogeneity")
async def book_homogeneity(book_id: int, body: HomoIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return _homogeneity("book", book_id, body, book_id)


@router.post("/ideas/{idea_id}/homogeneity")
async def idea_homogeneity(idea_id: int, body: HomoIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    idea = s.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(404, "灵感不存在")
    return _homogeneity("idea", idea_id, body, idea.book_id)
