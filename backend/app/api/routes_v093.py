"""v0.9.3：作品完整度、新手引导、字段级 AI 与 @引用、角色灵魂五维、成本提示与用量、拆书工作台。

调模型的接口一律走 Job（jobs.manager.submit），同步接口只做校验与读写库。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import card_out, job_out
from app.db import get_session
from app.jobs.manager import submit
from app.models.tables import Book, Card

router = APIRouter(prefix="/api")


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


def _entry(s: Session, book_id: int, entry_id: int) -> Card:
    c = s.get(Card, entry_id)
    if c is None or c.book_id != book_id:
        raise HTTPException(404, "设定条目不存在")
    return c


def _http(e: Exception) -> HTTPException:
    return HTTPException(getattr(e, "status", 400), str(e))


def _job(j: Any) -> dict[str, Any]:
    out = job_out(j)
    return {**out, "job_id": out["id"]}


# ------------------------------------------------------------------ 作品完整度 / 新手引导

@router.get("/books/{book_id}/completeness")
def book_completeness(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import progress_ui

    return progress_ui.completeness(s, _book(s, book_id))


OnboardingKey = Literal["model", "project", "bible_outline", "first_chapter"]


class OnboardingIn(BaseModel):
    steps: dict[OnboardingKey, bool] | None = None
    dismissed: bool | None = None


@router.get("/onboarding")
def onboarding_get(s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import progress_ui

    return progress_ui.onboarding_get(s)


@router.put("/onboarding")
def onboarding_put(body: OnboardingIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import progress_ui

    return progress_ui.onboarding_put(s, dict(body.steps or {}), body.dismissed)


# ------------------------------------------------------------------ 字段级 AI / @引用 / 灵魂五维

class FieldAiIn(BaseModel):
    field: str = Field(min_length=1, max_length=60)
    instruction: str = Field(default="", max_length=500)
    mode: Literal["fill", "rewrite", "expand"] = "fill"
    route: str | None = None


class FieldApplyIn(BaseModel):
    field: str = Field(min_length=1, max_length=60)
    value: Any = None


@router.post("/books/{book_id}/bible/{entry_id}/field-ai")
async def field_ai(book_id: int, entry_id: int, body: FieldAiIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import bible_ai

    _book(s, book_id)
    c = _entry(s, book_id, entry_id)
    if c.locked:
        raise HTTPException(409, "这张设定已锁定，AI 不能修改；先解锁再让 AI 改")
    try:
        bible_ai.check_field(c, body.field)
    except bible_ai.FieldError as e:
        raise _http(e) from e
    return _job(submit("field_ai", lambda ctx: bible_ai.field_ai(book_id, entry_id, body.field, body.instruction, body.mode,
                                                                 body.route, ctx), book_id=book_id, ref=f"card:{entry_id}"))


@router.post("/books/{book_id}/bible/{entry_id}/field-ai/apply")
def field_ai_apply(book_id: int, entry_id: int, body: FieldApplyIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import bible_ai

    _book(s, book_id)
    _entry(s, book_id, entry_id)
    if not isinstance(body.value, (str, list)):
        raise HTTPException(422, "value 只能是字符串或字符串数组")
    try:
        return card_out(bible_ai.apply_field(book_id, entry_id, body.field, body.value))
    except bible_ai.FieldError as e:
        raise _http(e) from e


@router.get("/books/{book_id}/refs")
def book_refs(book_id: int, q: str = "", limit: int = Query(20, ge=1, le=100),
              s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    from app.services import refs

    _book(s, book_id)
    return refs.list_refs(s, book_id, q, limit)


class SoulJobIn(BaseModel):
    mode: Literal["fill", "rewrite"] = "fill"
    instruction: str = Field(default="", max_length=500)
    route: str | None = None


@router.post("/books/{book_id}/characters/{entry_id}/soul")
async def character_soul(book_id: int, entry_id: int, body: SoulJobIn | None = Body(default=None),
                         s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import bible_ai

    _book(s, book_id)
    c = _entry(s, book_id, entry_id)
    if c.type != "character":
        raise HTTPException(400, "只有角色条目有灵魂五维")
    if c.locked:
        raise HTTPException(409, "这张设定已锁定，AI 不能修改；先解锁再让 AI 改")
    b = body or SoulJobIn()
    return _job(submit("character_soul", lambda ctx: bible_ai.soul_job(book_id, entry_id, b.mode, b.instruction, b.route, ctx),
                       book_id=book_id, ref=f"card:{entry_id}"))


# ------------------------------------------------------------------ 成本提示 / 用量

class EstimateIn(BaseModel):
    kind: Literal["chapter_write", "chapter_rewrite", "polish_voice", "humanize", "thicken", "review", "outline", "bible",
                  "report", "idea", "field_ai", "soul", "teardown", "package", "aigc"]
    book_id: int | None = None
    chapter_id: int | None = None
    words: int | None = Field(default=None, ge=100, le=200000)


@router.post("/estimate")
def estimate(body: EstimateIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import estimate as est

    return est.estimate(s, body.kind, body.book_id, body.chapter_id, body.words)


@router.get("/books/{book_id}/usage")
def book_usage(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.llm import usage

    _book(s, book_id)
    return usage.summary(book_id=book_id)


@router.get("/usage")
def global_usage(days: int = Query(30, ge=1, le=3650)) -> dict[str, Any]:
    from app.llm import usage

    return usage.summary(days=days)


# ------------------------------------------------------------------ 拆书工作台

class TeardownIn(BaseModel):
    source: Literal["rank_book", "paste", "txt"]
    book_id_ext: str | None = Field(default=None, max_length=40)
    text: str | None = None
    title: str | None = Field(default=None, max_length=60)


class TeardownIdeaIn(BaseModel):
    expand: bool = True
    notes: str = Field(default="", max_length=500)


class TeardownBibleIn(BaseModel):
    book_id: int
    parts: list[Literal["characters", "golden_finger", "reusable", "selling_points"]] = Field(min_length=1)


@router.post("/teardowns")
async def teardown_create(body: TeardownIn) -> dict[str, Any]:
    from app.services import teardown_ws as tw

    try:
        tw.check_create(body.source, body.book_id_ext, body.text)
    except tw.TeardownError as e:
        raise _http(e) from e
    return _job(submit("teardown_project", lambda ctx: tw.create(body.source, body.book_id_ext, body.text, body.title, ctx),
                       ref=f"teardown:{body.source}:{body.book_id_ext or ''}"))


@router.get("/teardowns")
def teardown_list() -> list[dict[str, Any]]:
    from app.services import teardown_ws as tw

    return tw.list_all()


@router.get("/teardowns/{teardown_id}")
def teardown_get(teardown_id: int) -> dict[str, Any]:
    from app.services import teardown_ws as tw

    return tw.teardown_out(tw.get(teardown_id))


@router.delete("/teardowns/{teardown_id}")
def teardown_delete(teardown_id: int) -> dict[str, bool]:
    from app.services import teardown_ws as tw

    tw.delete(teardown_id)
    return {"ok": True}


@router.post("/teardowns/{teardown_id}/to-idea")
async def teardown_to_idea(teardown_id: int, body: TeardownIdeaIn | None = Body(default=None)) -> dict[str, Any]:
    from app.services import teardown_ws as tw

    b = body or TeardownIdeaIn()
    tw.get(teardown_id)  # 不存在 404
    if not b.expand:
        return tw.to_idea_direct(teardown_id, b.notes)
    return _job(submit("idea_seed", lambda ctx: tw.to_idea_expand(teardown_id, b.notes, ctx), ref=f"teardown#{teardown_id}"))


@router.post("/teardowns/{teardown_id}/to-bible")
def teardown_to_bible(teardown_id: int, body: TeardownBibleIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import teardown_ws as tw

    _book(s, body.book_id)
    try:
        return tw.to_bible(teardown_id, body.book_id, list(dict.fromkeys(body.parts)))
    except tw.TeardownError as e:
        raise _http(e) from e
