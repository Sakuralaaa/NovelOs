"""v0.12 E6 批量质检 + 朱雀报告导出接口。

批量处理走后台 Job（kind=book_batch_qa，轮询 GET /api/jobs/{id}）；其余同步。
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.schemas import job_out
from app.db import get_session
from app.jobs.manager import submit
from app.models.tables import Book, Chapter
from app.services import aigc_report, batch_qa, zhuque

router = APIRouter(prefix="/api")

Op = Literal["humanize", "polish", "review", "aigc", "format", "titles"]


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


def _job(j: Any) -> dict[str, Any]:
    out = job_out(j)
    return {**out, "job_id": out["id"]}


class FormatOptions(BaseModel):
    blank_line: Optional[bool] = None
    indent: Optional[bool] = None
    punct: Optional[bool] = None
    split_long: Optional[bool] = None


class BatchOptions(BaseModel):
    recheck: Optional[bool] = None
    aigc_engine: Optional[Literal["auto", "zhuque", "local"]] = None
    aigc_target: Optional[float] = Field(default=None, ge=0, le=100)
    max_rounds: Optional[int] = Field(default=None, ge=1, le=batch_qa.MAX_ROUNDS)
    fix: Optional[bool] = None
    auto_adopt: Optional[bool] = None
    skip_committed: Optional[bool] = None
    format: Optional[FormatOptions] = None


class BatchIn(BaseModel):
    op: Op
    from_: int = Field(alias="from", ge=1)
    to: int = Field(ge=1)
    concurrency: int = Field(default=1, ge=1, le=batch_qa.MAX_CONCURRENCY)
    options: Optional[BatchOptions] = None

    model_config = {"populate_by_name": True}


class RetryIn(BaseModel):
    item_ids: list[int] = Field(default_factory=list)


class AdoptIn(BaseModel):
    content: Optional[str] = None  # DIFF 里逐段取舍后的正文；不传用对比稿全文
    title: Optional[str] = Field(default=None, max_length=60)  # 改章名：可换成其它候选
    force: bool = False  # 正文在生成对比稿后又改过时也覆盖


class AdoptAllIn(BaseModel):
    force: bool = False


def _start(book_id: int, run_id: int) -> dict[str, Any]:
    j = submit(batch_qa.KIND, lambda ctx: batch_qa.run_job(run_id, ctx), book_id=book_id, ref=f"batch:{run_id}")
    batch_qa.attach_job(run_id, j.id or 0)
    return j  # type: ignore[return-value]


def _run_with_job(s: Session, book_id: int, run_id: int, job: Any) -> dict[str, Any]:
    s.expire_all()
    run = batch_qa.get_run(s, book_id, run_id)
    return {**batch_qa.run_out(s, run), "job": _job(job), "job_id": job.id}


# ------------------------------------------------------------------ 批次

@router.post("/books/{book_id}/batch")
async def create_batch(book_id: int, body: BatchIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    """按章节区间批量处理（Job kind=book_batch_qa）。返回批次 + job。"""
    _book(s, book_id)
    opts = body.options.model_dump(exclude_none=True) if body.options else {}
    if body.options and body.options.format:
        opts["format"] = body.options.format.model_dump(exclude_none=True)
    opts["concurrency"] = body.concurrency
    run = batch_qa.create_run(book_id, body.op, body.from_, body.to, opts)
    job = _start(book_id, run.id or 0)
    return _run_with_job(s, book_id, run.id or 0, job)


@router.get("/books/{book_id}/batch")
def list_batches(book_id: int, limit: int = Query(30, ge=1, le=200), s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return batch_qa.list_runs(s, book_id, limit)


@router.get("/books/{book_id}/batch/{run_id}")
def get_batch(book_id: int, run_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return batch_qa.run_out(s, batch_qa.get_run(s, book_id, run_id), with_items=True)


@router.delete("/books/{book_id}/batch/{run_id}")
def delete_batch(book_id: int, run_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    batch_qa.delete_run(book_id, run_id)
    return {"ok": True}


@router.post("/books/{book_id}/batch/{run_id}/pause")
def pause_batch(book_id: int, run_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return batch_qa.pause(book_id, run_id)


@router.post("/books/{book_id}/batch/{run_id}/resume")
async def resume_batch(book_id: int, run_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    batch_qa.prepare_resume(book_id, run_id)
    return _run_with_job(s, book_id, run_id, _start(book_id, run_id))


@router.post("/books/{book_id}/batch/{run_id}/retry")
async def retry_batch(book_id: int, run_id: int, body: RetryIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    """失败章重新排队并处理：不传 item_ids 重试本批全部失败章。"""
    _book(s, book_id)
    batch_qa.prepare_retry(book_id, run_id, (body.item_ids if body else None) or None)
    return _run_with_job(s, book_id, run_id, _start(book_id, run_id))


@router.post("/books/{book_id}/batch/{run_id}/adopt-all")
def adopt_all(book_id: int, run_id: int, body: AdoptAllIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return batch_qa.adopt_all(book_id, run_id, force=bool(body.force) if body else False)


@router.post("/books/{book_id}/batch/{run_id}/discard-all")
def discard_all(book_id: int, run_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return batch_qa.discard_all(book_id, run_id)


@router.get("/books/{book_id}/batch/{run_id}/report")
def batch_report(book_id: int, run_id: int, format: Literal["html", "json"] = "html", print: bool = False,  # noqa: A002
                 download: bool = False, s: Session = Depends(get_session)) -> Response:
    b = _book(s, book_id)
    run = batch_qa.run_out(s, batch_qa.get_run(s, book_id, run_id), with_items=True)
    if format == "json":
        return JSONResponse(run)
    page = aigc_report.render_batch(b.title, run, run["items"], print_mode=print)
    return _html(page, f"批量{run['op_label']}报告-第{run['from']}-{run['to']}章.html", download)


# ------------------------------------------------------------------ 单章结果

@router.get("/books/{book_id}/batch/{run_id}/items/{item_id}")
def get_item(book_id: int, run_id: int, item_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    it = batch_qa.get_item(s, book_id, item_id)
    if it.run_id != run_id:
        raise HTTPException(404, "批量结果不存在")
    return batch_qa.item_out(it, with_content=True, current=s.get(Chapter, it.chapter_id))


@router.post("/books/{book_id}/batch/{run_id}/items/{item_id}/adopt")
def adopt_item(book_id: int, run_id: int, item_id: int, body: AdoptIn | None = Body(default=None),
               s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    if batch_qa.get_item(s, book_id, item_id).run_id != run_id:
        raise HTTPException(404, "批量结果不存在")
    b = body or AdoptIn()
    return batch_qa.adopt_item(book_id, item_id, content=b.content, title=b.title, force=b.force)


@router.post("/books/{book_id}/batch/{run_id}/items/{item_id}/discard")
def discard_item(book_id: int, run_id: int, item_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    if batch_qa.get_item(s, book_id, item_id).run_id != run_id:
        raise HTTPException(404, "批量结果不存在")
    return batch_qa.discard_item(book_id, item_id)


@router.post("/books/{book_id}/batch/{run_id}/items/{item_id}/retry")
async def retry_item(book_id: int, run_id: int, item_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    batch_qa.prepare_retry(book_id, run_id, [item_id])
    return _run_with_job(s, book_id, run_id, _start(book_id, run_id))


# ------------------------------------------------------------------ 朱雀报告：章节

def _html(page: str, filename: str, download: bool) -> HTMLResponse:
    headers = {"Content-Disposition": f"attachment; filename=\"aigc-report.html\"; filename*=UTF-8''{quote(filename)}"} if download else {}
    return HTMLResponse(page, headers=headers)


def _chapter_history(ch: Chapter) -> list[dict[str, Any]]:
    hist = list(ch.aigc_history or [])
    if not hist and isinstance(ch.aigc, dict):  # v0.12 之前的检测没有历史：用当前结果 + 当前正文顶上
        hist = [{**ch.aigc, "text": ch.content if ch.aigc.get("content_hash") == zhuque.content_hash(ch.content) else ""}]
    return hist


@router.get("/chapters/{chapter_id}/aigc/history")
def chapter_aigc_history(chapter_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    ch = s.get(Chapter, chapter_id)
    if ch is None:
        raise HTTPException(404, "章节不存在")
    cur = zhuque.content_hash(ch.content)
    out = []
    for i, h in enumerate(_chapter_history(ch)):
        out.append({"index": i, "checked_at": h.get("checked_at"), "softmax": h.get("softmax"), "level": h.get("level"),
                    "labels_ratio": h.get("labels_ratio"), "chars": h.get("chars"), "tokens": h.get("tokens"),
                    "source": h.get("source") or "manual", "current": h.get("content_hash") == cur})
    return out


@router.get("/chapters/{chapter_id}/aigc/report")
def chapter_aigc_report(chapter_id: int, format: Literal["html", "json"] = "html", index: int = -1,  # noqa: A002
                        print: bool = False, download: bool = False, s: Session = Depends(get_session)) -> Response:  # noqa: A002
    """导出本章朱雀检测报告（index 为历史下标，默认最近一次）。format=html 自包含页面；print=1 打开即弹打印（存为 PDF）。"""
    ch = s.get(Chapter, chapter_id)
    if ch is None:
        raise HTTPException(404, "章节不存在")
    hist = _chapter_history(ch)
    if not hist:
        raise HTTPException(404, "这一章还没有朱雀检测结果")
    if not -len(hist) <= index < len(hist):
        raise HTTPException(404, "没有这一次检测")
    entry = hist[index]
    real_index = index % len(hist)
    text = str(entry.get("text") or "")
    stale = entry.get("content_hash") != zhuque.content_hash(ch.content)
    if format == "json":
        return JSONResponse({"chapter_id": chapter_id, "number": ch.number, "title": ch.title, "index": real_index,
                             "stale": stale, "result": {k: v for k, v in entry.items() if k != "text"}, "text": text})
    b = s.get(Book, ch.book_id)
    title = f"第{ch.number}章 {ch.title or ''} · 朱雀 AI 检测报告".replace("  ", " ")
    sub = f"《{b.title if b else ''}》 · 第 {real_index + 1}/{len(hist)} 次检测"
    page = aigc_report.render_aigc(title, sub, entry, text, history=hist, current_index=real_index, stale=stale, print_mode=print)
    return _html(page, f"第{ch.number}章-AI检测报告.html", download)


# ------------------------------------------------------------------ 朱雀报告：独立检测页历史

@router.get("/aigc/reports")
def aigc_reports() -> list[dict[str, Any]]:
    return zhuque.list_reports()


@router.get("/aigc/reports/{report_id}")
def aigc_report_get(report_id: int) -> dict[str, Any]:
    return zhuque.get_report(report_id)


@router.delete("/aigc/reports/{report_id}")
def aigc_report_delete(report_id: int) -> dict[str, Any]:
    zhuque.delete_report(report_id)
    return {"ok": True}


@router.get("/aigc/reports/{report_id}/export")
def aigc_report_export(report_id: int, format: Literal["html", "json"] = "html", print: bool = False,  # noqa: A002
                       download: bool = False) -> Response:
    r = zhuque.get_report(report_id)
    if format == "json":
        return JSONResponse(r)
    result = {**(r.get("result") or {}), "checked_at": r.get("checked_at")}
    page = aigc_report.render_aigc(f"朱雀 AI 检测报告 #{report_id}", f"「{r.get('title') or ''}」 · {int(result.get('chars') or 0):,} 字",
                                   result, str(r.get("text") or ""), print_mode=print)
    return _html(page, f"AI检测报告-{report_id}.html", download)

