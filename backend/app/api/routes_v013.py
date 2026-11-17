"""v0.13：批量后台质检、章节工具（章名 / 脑洞 / 神评 / 查找替换 / 高频词 / 排版）、写作笔记、AI 率报告。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import job_out
from app.db import get_session
from app.jobs.manager import submit
from app.models.tables import Book, Chapter
from app.services import batch, chapter_tools

router = APIRouter(prefix="/api")


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


def _chapter(s: Session, chapter_id: int) -> Chapter:
    c = s.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(404, "章节不存在")
    return c


# ------------------------------------------------------------------ 批量

class BatchIn(BaseModel):
    op: Literal["humanize", "polish", "format", "review", "aigc", "titles"]
    start: Optional[int] = None
    end: Optional[int] = None
    numbers: list[int] = []
    ranges: list[list[int]] = []
    options: dict[str, Any] = {}


@router.post("/books/{book_id}/batch")
async def start_batch(book_id: int, body: BatchIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    if not (body.start or body.end or body.numbers or body.ranges):
        raise HTTPException(422, "请选择章节范围")
    if body.op == "aigc":
        from app.services import zhuque

        zhuque.require_configured()
    params = body.model_dump()
    return job_out(submit(batch.KIND, lambda ctx: batch.batch_job(book_id, params, ctx), book_id=book_id, lock_book=True,
                          ref=f"batch:{body.op}"))


@router.post("/books/{book_id}/batch/stop")
def stop_batch(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    batch.request_stop(book_id)
    return {"ok": True, "message": "当前这一章处理完就停"}


# ------------------------------------------------------------------ 章名 / 脑洞 / 神评

class TitlesIn(BaseModel):
    n: int = 6


@router.post("/chapters/{chapter_id}/titles")
async def chapter_titles(chapter_id: int, body: TitlesIn | None = None, s: Session = Depends(get_session)) -> dict[str, Any]:
    ch = _chapter(s, chapter_id)
    n = (body or TitlesIn()).n
    return job_out(submit("chapter_titles", lambda ctx: chapter_tools.chapter_titles(chapter_id, n), book_id=ch.book_id,
                          ref=f"chapter:{chapter_id}"))


class SparksIn(BaseModel):
    n: int = 5
    use_context: bool = True
    hint: str = Field(default="", max_length=300)


@router.post("/books/{book_id}/sparks")
async def sparks(book_id: int, body: SparksIn | None = None, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    b = body or SparksIn()
    return job_out(submit("sparks", lambda ctx: chapter_tools.sparks(book_id, b.n, b.use_context, b.hint), book_id=book_id))


class CommentsIn(BaseModel):
    personas: int = 4


@router.post("/chapters/{chapter_id}/reader-comments")
async def reader_comments(chapter_id: int, body: CommentsIn | None = None, s: Session = Depends(get_session)) -> dict[str, Any]:
    ch = _chapter(s, chapter_id)
    n = (body or CommentsIn()).personas
    return job_out(submit("reader_comments", lambda ctx: chapter_tools.reader_comments(chapter_id, n), book_id=ch.book_id,
                          ref=f"chapter:{chapter_id}"))


# ------------------------------------------------------------------ 高频词 / 排版

@router.get("/chapters/{chapter_id}/freq")
def chapter_freq(chapter_id: int) -> dict[str, Any]:
    return chapter_tools.chapter_freq(chapter_id)


@router.get("/books/{book_id}/freq")
def book_freq(book_id: int, start: Optional[int] = Query(default=None), end: Optional[int] = Query(default=None)) -> dict[str, Any]:
    return chapter_tools.book_freq(book_id, start, end)


class FormatIn(BaseModel):
    text: str = Field(max_length=200000)


@router.post("/format")
def format_text(body: FormatIn) -> dict[str, Any]:
    out, notes = chapter_tools.format_text(body.text)
    return {"text": out, "changed": out != body.text, "notes": notes}


# ------------------------------------------------------------------ 查找替换

@router.get("/books/{book_id}/search")
def search(book_id: int, q: str = Query(min_length=1, max_length=200), scope: str = Query(default="chapters"),
           regex: bool = Query(default=False), case: bool = Query(default=True)) -> dict[str, Any]:
    try:
        return chapter_tools.search(book_id, q, scope.split(","), regex, case)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class ReplaceIn(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    replacement: str = Field(default="", max_length=2000)
    scopes: list[str] = ["chapters"]
    regex: bool = False
    case: bool = True
    expect: Optional[int] = None
    skip: list[str] = []


@router.post("/books/{book_id}/replace")
def replace(book_id: int, body: ReplaceIn) -> dict[str, Any]:
    try:
        return chapter_tools.replace(book_id, body.q, body.replacement, body.scopes, body.regex, body.case, body.expect, body.skip)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


# ------------------------------------------------------------------ 笔记

class NoteIn(BaseModel):
    title: Optional[str] = None
    folder: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    pinned: Optional[bool] = None
    source: Optional[dict[str, Any]] = None


@router.get("/books/{book_id}/notes")
def list_notes(book_id: int, q: str = Query(default=""), folder: Optional[str] = Query(default=None),
               s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return chapter_tools.list_notes(s, book_id, q, folder)


@router.post("/books/{book_id}/notes")
def create_note(book_id: int, body: NoteIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    return chapter_tools.create_note(s, book_id, body.model_dump(exclude_none=True))


@router.put("/books/{book_id}/notes/{note_id}")
def update_note(book_id: int, note_id: int, body: NoteIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    return chapter_tools.update_note(s, book_id, note_id, body.model_dump(exclude_none=True))


@router.delete("/books/{book_id}/notes/{note_id}")
def delete_note(book_id: int, note_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    chapter_tools.delete_note(s, book_id, note_id)
    return {"ok": True}


@router.get("/books/{book_id}/notes/export")
def export_notes(book_id: int, s: Session = Depends(get_session)) -> PlainTextResponse:
    return PlainTextResponse(chapter_tools.export_notes_md(s, book_id), media_type="text/markdown; charset=utf-8")


class NotesImportIn(BaseModel):
    text: str = Field(max_length=500000)
    folder: str = ""


@router.post("/books/{book_id}/notes/import")
def import_notes(book_id: int, body: NotesImportIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return chapter_tools.import_notes_md(s, book_id, body.text, body.folder)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class SparkNoteIn(BaseModel):
    title: str
    beat: str = ""
    payoff: str = ""
    fit: str = ""


@router.post("/books/{book_id}/notes/from-spark")
def spark_note(book_id: int, body: SparkNoteIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    return chapter_tools.spark_to_note(s, book_id, body.model_dump())


# ------------------------------------------------------------------ AI 率报告

@router.get("/chapters/{chapter_id}/aigc/report")
def aigc_report(chapter_id: int) -> HTMLResponse:
    from app.services import zhuque

    return HTMLResponse(zhuque.report_html(chapter_id))


# ------------------------------------------------------------------ 抽卡立项

class SparkCreateIn(BaseModel):
    gender: Literal["male", "female"] = "male"
    track: str = Field(min_length=1, max_length=20)
    sub: str = Field(default="", max_length=20)
    tags: list[str] = []
    inspiration: dict[str, str] = {}


class SparkDrawIn(BaseModel):
    axis: Literal["world", "hero", "cheat"]
    keep: list[str] = []
    custom: str = Field(default="", max_length=300)


class SparkPickIn(BaseModel):
    axis: Literal["world", "hero", "cheat"]
    card_id: Optional[str] = None
    custom: Optional[dict[str, str]] = None


@router.get("/spark/tracks")
def spark_tracks(gender: str = Query(default="male"), s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    return spark.tracks(s, gender)


@router.get("/spark/sessions")
def spark_sessions(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    from app.services import spark

    return spark.list_sessions(s)


@router.post("/spark/sessions")
def spark_create(body: SparkCreateIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    try:
        return spark.create(s, body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/spark/sessions/{sid}")
def spark_get(sid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    return spark.out(spark._get(s, sid))  # noqa: SLF001


@router.post("/spark/sessions/{sid}/draw")
async def spark_draw(sid: int, body: SparkDrawIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    spark._get(s, sid)  # noqa: SLF001
    return job_out(submit("spark_draw", lambda ctx: spark.draw(sid, body.axis, body.keep, body.custom, ctx), ref=f"spark:{sid}"))


@router.post("/spark/sessions/{sid}/pick")
def spark_pick(sid: int, body: SparkPickIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    return spark.pick(s, sid, body.axis, body.card_id, body.custom)


@router.post("/spark/sessions/{sid}/proposal")
async def spark_proposal(sid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    spark._get(s, sid)  # noqa: SLF001
    return job_out(submit("spark_proposal", lambda ctx: spark.proposal(sid, ctx), ref=f"spark:{sid}"))


@router.patch("/spark/sessions/{sid}/proposal")
def spark_proposal_patch(sid: int, body: dict[str, Any], s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    return spark.update_proposal(s, sid, body)


@router.post("/spark/sessions/{sid}/adopt")
def spark_adopt(sid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import spark

    return spark.adopt(s, sid)


# ------------------------------------------------------------------ 上下文构成 / @变量

@router.get("/books/{book_id}/context-preview")
def context_preview(book_id: int, chapter_id: Optional[int] = Query(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import vars as v

    _book(s, book_id)
    return v.context_preview(s, book_id, chapter_id)


class ExcludeIn(BaseModel):
    blocks: list[str] = []


@router.put("/books/{book_id}/context-exclude")
def context_exclude(book_id: int, body: ExcludeIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import vars as v

    _book(s, book_id)
    return {"blocks": v.set_exclude(s, book_id, body.blocks)}


@router.get("/books/{book_id}/vars")
def list_vars(book_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    from app.services import vars as v

    _book(s, book_id)
    return v.catalog(s, book_id)


class ResolveIn(BaseModel):
    text: str = Field(max_length=5000)
    chapter_number: Optional[int] = None


@router.post("/books/{book_id}/vars/resolve")
def resolve_vars(book_id: int, body: ResolveIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import vars as v

    _book(s, book_id)
    return v.resolve(s, book_id, body.text, body.chapter_number)
