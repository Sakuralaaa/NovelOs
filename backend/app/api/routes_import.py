"""v0.12 导入已有作品 + 接管旧书。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import job_out
from app.db import get_session
from app.jobs.manager import submit
from app.models.tables import Book
from app.services import import_book
from app.services.imitate_txt import ExtractError

router = APIRouter(prefix="/api")


@router.post("/books/import")
async def import_preview(request: Request) -> dict[str, Any]:
    """multipart（file=TXT/MD/DOCX）或 JSON {text, filename?} → 预览（卷章列表、字数、疑点），不建书。"""
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            f = form.get("file")
            if f is None or isinstance(f, str):
                t = form.get("text")
                if isinstance(t, str) and t.strip():
                    return import_book.parse(text=t)
                raise HTTPException(400, "请上传文件（字段名 file）")
            data = await f.read(import_book.MAX_BYTES + 1)
            return import_book.parse(data=data, filename=f.filename)
        try:
            body = await request.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, "请求体要么是 multipart（file），要么是 JSON {text}") from e
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise HTTPException(400, "JSON 里要有 text 字段")
        return import_book.parse(text=body["text"], filename=body.get("filename") if isinstance(body.get("filename"), str) else None)
    except ExtractError as e:
        raise HTTPException(400, str(e)) from e


class ImportCommitIn(BaseModel):
    import_id: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=60)
    genre: str = Field(default="", max_length=20)
    gender: str = "male"
    tagline: str = Field(default="", max_length=200)
    skip: list[int] = []


@router.post("/books/import/commit")
def import_commit(body: ImportCommitIn) -> dict[str, Any]:
    try:
        return import_book.commit(body.import_id, body.title, body.genre, body.gender, body.tagline, body.skip)
    except ExtractError as e:
        raise HTTPException(400, str(e)) from e


class AdoptIn(BaseModel):
    steps: list[str] = ["summary", "bible", "ledger", "outline"]


@router.post("/books/{book_id}/adopt")
async def adopt_book(book_id: int, body: AdoptIn | None = None, s: Session = Depends(get_session)) -> dict[str, Any]:
    if s.get(Book, book_id) is None:
        raise HTTPException(404, "书不存在")
    steps = (body or AdoptIn()).steps
    return job_out(submit("book_adopt", lambda ctx: import_book.adopt(book_id, steps, ctx), book_id=book_id, lock_book=True))


@router.get("/books/{book_id}/adopt")
def adopt_status(book_id: int) -> dict[str, Any]:
    return import_book.adopt_status(book_id)
