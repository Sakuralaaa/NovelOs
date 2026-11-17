"""v0.10 同人创作：原著资料、同人书设置、方向模板、OOC 检查、原著重合检查。

调模型的接口（原著卡提炼、OOC 检查）走 Job（jobs.manager.submit）；其余同步。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session

from app.api.schemas import FanficSpec, job_out
from app.db import get_session
from app.jobs.manager import submit
from app.models.tables import Book

router = APIRouter(prefix="/api")


def _http(e: Exception) -> HTTPException:
    return HTTPException(getattr(e, "status", 400), str(e))


def _job(j: Any) -> dict[str, Any]:
    out = job_out(j)
    return {**out, "job_id": out["id"]}


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


# ------------------------------------------------------------------ 方向模板 / 遵循度 / 版权声明

@router.get("/fanfic/directions")
def fanfic_directions() -> dict[str, Any]:
    from app.services.fanfic_directions import catalog

    return catalog()


@router.get("/fanfic/templates")
def fanfic_templates() -> dict[str, Any]:
    """v0.11.1 热门同人题材模板 + 当前联网搜索是否可用（mode: web / mock / none）。"""
    from app.services import fanfic as ff
    from app.services.fanfic_templates import catalog

    return {**catalog(), "search": ff.search_status()}


# ------------------------------------------------------------------ 原著资料

class SourceIn(BaseModel):
    source: Literal["paste", "txt", "search"] = "paste"
    text: str = ""  # paste / txt 必填（check_input 校验）；search 不需要
    title: str | None = Field(default=None, max_length=60)  # search / 联网补充时是作品名（必填）
    focus: list[str] = Field(default_factory=list, max_length=10)
    depth: Literal["quick", "standard", "deep"] = "standard"
    web_supplement: bool = False  # v0.11.1 paste / txt：提炼后再联网补齐原文没覆盖的部分（以原文为准）
    template_id: str | None = Field(default=None, max_length=40)


class SupplementIn(BaseModel):
    focus: list[str] | None = Field(default=None, max_length=10)
    depth: Literal["quick", "standard", "deep"] = "standard"


class SourceUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=60)
    cards: dict[str, Any] | None = None


@router.post("/fanfic/sources")
async def source_create(request: Request) -> dict[str, Any]:
    """JSON：{source, text, title?, focus?, depth?, web_supplement?, template_id?}；source=search 时只要 title（作品名）；
    或 multipart：file（TXT）+ title/focus（逗号分隔）/depth/web_supplement（1/true）。"""
    from app.services import fanfic as ff

    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/form-data"):
            clen = int(request.headers.get("content-length") or 0)
            if clen > ff.MAX_BYTES + 64 * 1024:
                raise ff.FanficError("文件超过 30MB，请只保留需要的部分再导入", 413)
            form = await request.form()
            f = form.get("file")
            if f is None or not hasattr(f, "read"):
                raise ff.FanficError("请上传 TXT 文件（字段名 file）", 422)
            text = ff.decode_txt(await f.read())  # type: ignore[union-attr]
            focus_raw = str(form.get("focus") or "")
            body = SourceIn(source="txt", text=text or " ", title=(str(form.get("title") or "") or None),
                            focus=[x.strip() for x in focus_raw.replace("，", ",").split(",") if x.strip()][:10],
                            depth=str(form.get("depth") or "standard"),  # type: ignore[arg-type]
                            web_supplement=str(form.get("web_supplement") or "").lower() in ("1", "true", "on", "yes"),
                            template_id=(str(form.get("template_id") or "") or None))
        else:
            try:
                body = SourceIn.model_validate(json.loads(await request.body() or b"{}"))
            except ValueError as e:
                if isinstance(e, ValidationError):
                    raise HTTPException(422, f"参数错误：{e.errors()[0].get('loc')}: {e.errors()[0].get('msg')}") from e
                raise HTTPException(422, "请求体不是合法 JSON") from e
        ff.check_input(body.source, body.text, body.depth, body.title, body.web_supplement and body.source != "search")
    except ValidationError as e:
        raise HTTPException(422, f"参数错误：{e.errors()[0].get('msg')}") from e
    except ff.FanficError as e:
        raise _http(e) from e
    text, src, title, focus, depth = body.text, body.source, body.title, list(body.focus), body.depth
    web, tid = body.web_supplement and src != "search", body.template_id
    return _job(submit("fanfic_source", lambda ctx: ff.create_source(text, src, title, focus, depth, ctx, web=web, template_id=tid),
                       ref=f"fanfic_source:{src}"))


@router.post("/fanfic/sources/{source_id}/supplement")
async def source_supplement(source_id: int, body: SupplementIn | None = Body(default=None)) -> dict[str, Any]:
    """v0.11.1 给已有原著资料联网补充（后台 Job，kind=fanfic_supplement）：以已有设定卡为准，只补空缺，冲突记 warning。"""
    from app.services import fanfic as ff

    b = body or SupplementIn()
    try:
        ff.check_supplement(source_id)
    except ff.FanficError as e:
        raise _http(e) from e
    focus, depth = (list(b.focus) if b.focus is not None else None), b.depth
    return _job(submit("fanfic_supplement", lambda ctx: ff.supplement_source(source_id, focus, depth, ctx), ref=f"fanfic_source:{source_id}"))


@router.get("/fanfic/sources")
def source_list() -> list[dict[str, Any]]:
    from app.services import fanfic as ff

    return ff.list_sources()


@router.get("/fanfic/sources/{source_id}")
def source_get(source_id: int) -> dict[str, Any]:
    from app.services import fanfic as ff

    return ff.get_source(source_id)


@router.put("/fanfic/sources/{source_id}")
def source_update(source_id: int, body: SourceUpdate) -> dict[str, Any]:
    from app.services import fanfic as ff

    try:
        return ff.update_source(source_id, body.title, body.cards)
    except ff.FanficError as e:
        raise _http(e) from e


@router.delete("/fanfic/sources/{source_id}")
def source_delete(source_id: int, force: bool = Query(False)) -> dict[str, bool]:
    from app.services import fanfic as ff

    ff.delete_source(source_id, force)
    return {"ok": True}


# ------------------------------------------------------------------ 同人书

class FanficAttachIn(FanficSpec):
    copyright_ack: bool = False


class FanficPatchIn(BaseModel):
    fidelity: Literal["strict", "moderate", "loose"] | None = None
    direction: str | None = Field(default=None, max_length=40)
    extra_source_ids: list[int] | None = Field(default=None, max_length=9)
    notes: str | None = Field(default=None, max_length=1000)
    protagonist: dict[str, Any] | None = None
    pov: str | None = None
    slots: dict[str, str] | None = None


class FanficImportIn(BaseModel):
    parts: list[Literal["characters", "factions", "world", "locations"]] = Field(default_factory=lambda: ["characters"], min_length=1)


@router.post("/books/{book_id}/fanfic")
def book_fanfic_attach(book_id: int, body: FanficAttachIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import fanfic as ff

    b = _book(s, book_id)
    spec = body.model_dump(exclude={"copyright_ack"})
    try:
        return ff.attach(s, b, spec, body.copyright_ack)
    except ff.FanficError as e:
        raise _http(e) from e


@router.get("/books/{book_id}/fanfic")
def book_fanfic_get(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import fanfic as ff

    return ff.fanfic_out(s, _book(s, book_id))


@router.patch("/books/{book_id}/fanfic")
def book_fanfic_patch(book_id: int, body: FanficPatchIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import fanfic as ff

    b = _book(s, book_id)
    try:
        return ff.patch(s, b, body.model_dump(exclude_unset=True))
    except ff.FanficError as e:
        raise _http(e) from e


@router.delete("/books/{book_id}/fanfic")
def book_fanfic_detach(book_id: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    from app.services import fanfic as ff

    ff.detach(s, _book(s, book_id))
    return {"ok": True}


@router.get("/books/{book_id}/fanfic/context")
def book_fanfic_context(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    """调试/预览：写章与大纲时注入的同人上下文原文。"""
    from app.services import fanfic as ff

    text = ff.context_block(s, _book(s, book_id))
    return {"book_id": book_id, "text": text, "chars": len(text)}


@router.post("/books/{book_id}/fanfic/import-cards")
def book_fanfic_import(book_id: int, body: FanficImportIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import fanfic as ff

    _book(s, book_id)
    b = body or FanficImportIn()
    try:
        return ff.import_cards(book_id, list(dict.fromkeys(b.parts)))
    except ff.FanficError as e:
        raise _http(e) from e


# ------------------------------------------------------------------ 章节检查

@router.post("/chapters/{chapter_id}/ooc-check")
async def chapter_ooc_check(chapter_id: int) -> dict[str, Any]:
    from app.services import fanfic as ff

    try:
        book_id = ff.check_ooc(chapter_id)
    except ff.FanficError as e:
        raise _http(e) from e
    return _job(submit("fanfic_ooc", lambda ctx: ff.run_ooc(chapter_id, ctx), book_id=book_id, ref=f"chapter:{chapter_id}"))


@router.post("/books/{book_id}/fanfic/oc/generate")
async def book_fanfic_oc(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    """v0.13 原创主角：按原著设定补全身份、能力与上限、成长路线、性格与说话方式、想接触的原著人物、初始关系，写进设定库。"""
    from app.services import fanfic as ff

    b = _book(s, book_id)
    if not b.fanfic:
        raise HTTPException(409, "这本书不是同人书")
    return _job(submit("fanfic_oc", lambda ctx: ff.generate_oc(book_id, ctx), book_id=book_id, lock_book=True))


@router.get("/chapters/{chapter_id}/ooc")
def chapter_ooc_get(chapter_id: int) -> dict[str, Any]:
    from app.services import fanfic as ff

    return ff.chapter_fanfic_meta(chapter_id)


@router.post("/chapters/{chapter_id}/fanfic-overlap")
def chapter_overlap(chapter_id: int) -> dict[str, Any]:
    from app.services import fanfic as ff

    try:
        return ff.chapter_overlap(chapter_id)
    except ff.FanficError as e:
        raise _http(e) from e
