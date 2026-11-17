"""v0.12 E1 导入已有作品 + 接管旧书 + 大纲文本导入。

- POST /api/import/preview          解析文件或粘贴文本 → 卷章预览（同步，不入库）
- POST /api/import/commit           作者确认（可手动调整后）的卷章 → 建书 + 章节 + 大纲骨架
- GET  /api/books/{id}/adopt        接管进度
- POST /api/books/{id}/adopt/estimate  接管成本预估（已完成单元不计）
- POST /api/books/{id}/adopt        发起接管（Job kind=book_adopt，可续跑）
- POST /api/books/{id}/adopt/pause  请求暂停（当前单元做完后停下）
- DELETE /api/books/{id}/adopt/proposal  清掉待审的设定提案（采纳走 /books/{id}/bible/apply）
- POST /api/books/{id}/outline/import        大纲文本 → 结构化预览（Job kind=outline_import）
- POST /api/books/{id}/outline/import/apply  采纳预览（fill 按章号合并 / append 接在后面）
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from app.api.schemas import job_out
from app.db import session_scope
from app.jobs.manager import find_active, submit
from app.services import common
from app.services import import_book as ib
from app.services import import_text as it

router = APIRouter(prefix="/api")


def _http(e: it.ImportError_) -> HTTPException:
    return HTTPException(e.status, str(e))


def _truthy(v: Any) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "on", "yes")


class PreviewIn(BaseModel):
    text: str = Field(min_length=1)
    filename: str | None = Field(default=None, max_length=200)
    pattern: str | None = Field(default=None, max_length=it.MAX_PATTERN_LEN)
    split_volumes: bool = True


@router.post("/import/preview")
async def import_preview(request: Request) -> dict[str, Any]:
    """multipart：file（.txt/.md/.docx）+ pattern? + split_volumes?；或 JSON：{text, filename?, pattern?, split_volumes?}。"""
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/form-data"):
            clen = int(request.headers.get("content-length") or 0)
            if clen > it.MAX_BYTES + 64 * 1024:
                raise it.ImportError_("文件超过 30MB，请拆成几部分分别导入", 413)
            form = await request.form()
            f = form.get("file")
            if f is None or not hasattr(f, "read"):
                raise it.ImportError_("请上传文件（字段名 file）", 422)
            data = await f.read()  # type: ignore[union-attr]
            return it.preview(data=data, filename=getattr(f, "filename", None) or None,
                              pattern=str(form.get("pattern") or "") or None,
                              split_volumes=not (form.get("split_volumes") is not None and not _truthy(form.get("split_volumes"))))
        try:
            body = PreviewIn.model_validate(json.loads(await request.body() or b"{}"))
        except ValidationError as e:
            raise HTTPException(422, f"参数错误：{e.errors()[0].get('loc')}: {e.errors()[0].get('msg')}") from e
        except ValueError as e:
            raise HTTPException(422, "请求体不是合法 JSON") from e
        return it.preview(text=body.text, filename=body.filename, pattern=body.pattern, split_volumes=body.split_volumes)
    except it.ImportError_ as e:
        raise _http(e) from e


class ChapterIn(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = ""
    volume: str = Field(default="", max_length=200)


class SourceMeta(BaseModel):
    format: str = Field(default="paste", max_length=10)
    filename: str = Field(default="", max_length=200)
    encoding: str = Field(default="", max_length=20)
    rule: str = Field(default="", max_length=20)


class CommitIn(BaseModel):
    title: str = Field(default="", max_length=60)
    genre: str = Field(default="", max_length=20)
    gender: Literal["male", "female"] = "male"
    premise: str = Field(default="", max_length=4000)
    platform_style: Literal["fanqie", "qidian", "generic", "duanju"] = "fanqie"
    chapter_words: int | None = Field(default=None, ge=300, le=20000)
    target_words: int | None = Field(default=None, ge=10000, le=50_000_000)
    chapters: list[ChapterIn] = Field(min_length=1, max_length=it.MAX_CHAPTERS)
    volume_intros: dict[str, str] = Field(default_factory=dict)
    source: SourceMeta = Field(default_factory=SourceMeta)


@router.post("/import/commit")
def import_commit(body: CommitIn) -> dict[str, Any]:
    try:
        r = ib.commit_import(body.model_dump())
    except it.ImportError_ as e:
        raise _http(e) from e
    from app.api.schemas import book_out
    from app.models.tables import Book

    with session_scope() as s:
        b = s.get(Book, r["book_id"])
        assert b is not None
        return {**r, "book": book_out(s, b)}


# ------------------------------------------------------------------ 接管

class AdoptIn(BaseModel):
    from_: int | None = Field(default=None, alias="from", ge=1)
    to: int | None = Field(default=None, ge=1)
    steps: list[Literal["summary", "bible", "ledger", "outline"]] | None = None
    batch_size: int | None = Field(default=None, ge=1, le=ib.MAX_BATCH)

    model_config = {"populate_by_name": True}


def _params(book_id: int, b: AdoptIn | None) -> dict[str, Any]:
    b = b or AdoptIn()
    with session_scope() as s:
        common.get_book(s, book_id)
        return ib.norm_params(s, book_id, b.from_, b.to, list(b.steps) if b.steps else None, b.batch_size)


@router.get("/books/{book_id}/adopt")
def adopt_status(book_id: int) -> dict[str, Any]:
    return ib.status(book_id)


@router.post("/books/{book_id}/adopt/estimate")
def adopt_estimate(book_id: int, body: AdoptIn | None = Body(default=None)) -> dict[str, Any]:
    return ib.estimate(book_id, _params(book_id, body))


@router.post("/books/{book_id}/adopt")
async def adopt_start(book_id: int, body: AdoptIn | None = Body(default=None)) -> dict[str, Any]:
    params = _params(book_id, body)
    ref = f"{ib.ADOPT_KIND}:{book_id}"
    j = find_active(ib.ADOPT_KIND, ref)
    if j is None:
        ib.request_stop(book_id, False)
        j = submit(ib.ADOPT_KIND, lambda ctx: ib.adopt_job(book_id, params, ctx), book_id=book_id, lock_book=True, ref=ref)
    out = job_out(j)
    return {**out, "job_id": out["id"]}


@router.post("/books/{book_id}/adopt/pause")
def adopt_pause(book_id: int) -> dict[str, Any]:
    running = find_active(ib.ADOPT_KIND, f"{ib.ADOPT_KIND}:{book_id}")
    if running is None:
        with session_scope() as s:
            common.get_book(s, book_id)
        return {"ok": True, "running": False}
    ib.request_stop(book_id, True)
    return {"ok": True, "running": True}


@router.delete("/books/{book_id}/adopt/proposal")
def adopt_dismiss_proposal(book_id: int) -> dict[str, bool]:
    ib.dismiss_proposal(book_id)
    return {"ok": True}


# ------------------------------------------------------------------ 大纲导入

class OutlineImportIn(BaseModel):
    text: str = Field(min_length=2, max_length=200_000)


class OutlineApplyIn(BaseModel):
    preview: dict[str, Any]
    mode: Literal["fill", "append"] = "fill"


@router.post("/books/{book_id}/outline/import")
async def outline_import(book_id: int, body: OutlineImportIn) -> dict[str, Any]:
    with session_scope() as s:
        common.get_book(s, book_id)
    text = body.text
    if not text.strip():
        raise HTTPException(422, "大纲文本是空的")
    j = submit(ib.OUTLINE_IMPORT_KIND, lambda ctx: ib.outline_import_job(book_id, text, ctx), book_id=book_id,
               ref=f"{ib.OUTLINE_IMPORT_KIND}:{book_id}")
    out = job_out(j)
    return {**out, "job_id": out["id"]}


@router.post("/books/{book_id}/outline/import/apply")
def outline_import_apply(book_id: int, body: OutlineApplyIn) -> dict[str, Any]:
    return ib.apply_outline_import(book_id, body.preview, body.mode)
