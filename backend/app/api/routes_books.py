"""书、选题、设定库、大纲、章节、伏笔、包装、风格卡、导出。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session, select

from app.api.schemas import (
    AdoptVariantIn, BookCreate, BookPatch, CardIn, CardUpdate, ChapterUpdate, CoversIn, IdeasGenerate, OutlineUpdate,
    IdeaRevise, IdeaSuggest, IdeaUpdate, PackageUpdate, StyleIn, WriteBatchIn, WriteNextIn, book_out, card_out, chapter_out, fact_out, foreshadow_out, idea_out,
    job_out, node_out, package_out, style_out,
)
from app.config import get_settings
from app.db import get_session
from app.jobs.manager import submit
from app.lint.humanlint import count_words
from app.models.tables import (
    Book, Card, Chapter, Fact, Foreshadow, Idea, Job, OutlineNode, Package, Style, utcnow,
)
from app.services import common, outline, packaging, planning, style as style_svc, writing

router = APIRouter(prefix="/api")


def _book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "书不存在")
    return b


# ------------------------------------------------------------------ books

@router.get("/books")
def list_books(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [book_out(s, b) for b in s.exec(select(Book).order_by(Book.updated_at.desc()))]  # type: ignore[attr-defined]


@router.post("/books")
def create_book(body: BookCreate, s: Session = Depends(get_session)) -> dict[str, Any]:
    st = get_settings()
    b = Book(title=body.title or "未命名作品", genre=body.genre, gender=body.gender, premise=body.premise or "",
             status="idea", target_words=st.default_target_words, chapter_words=st.default_chapter_words)
    s.add(b)
    s.commit()
    s.refresh(b)
    return book_out(s, b)


@router.get("/books/{book_id}")
def get_book(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    return book_out(s, _book(s, book_id))


@router.patch("/books/{book_id}")
def patch_book(book_id: int, body: BookPatch, s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(b, k, v)
    b.updated_at = utcnow()
    s.add(b)
    s.commit()
    s.refresh(b)
    return book_out(s, b)


@router.delete("/books/{book_id}")
def delete_book(book_id: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    b = _book(s, book_id)
    for model in (Card, Fact, OutlineNode, Chapter, Foreshadow):
        for row in s.exec(select(model).where(model.book_id == book_id)):  # type: ignore[attr-defined]
            s.delete(row)
    for model in (Package, Style):
        row = s.get(model, book_id)
        if row:
            s.delete(row)
    for idea in s.exec(select(Idea).where(Idea.book_id == book_id)):
        idea.book_id = None
        idea.chosen = False
        s.add(idea)
    for job in s.exec(select(Job).where(Job.book_id == book_id)):
        job.book_id = None
        s.add(job)
    s.delete(b)
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ ideas

@router.post("/ideas/generate")
async def ideas_generate(body: IdeasGenerate) -> dict[str, Any]:
    params = body.model_dump()
    return job_out(submit("ideas_generate", lambda ctx: planning.generate_ideas(params, ctx)))


@router.get("/ideas")
def list_ideas(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [idea_out(i) for i in s.exec(select(Idea).order_by(Idea.id.desc()).limit(200))]  # type: ignore[union-attr]


@router.delete("/ideas/{idea_id}")
def delete_idea(idea_id: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    idea = s.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(404, "选题不存在")
    s.delete(idea)  # 已建的书不受影响
    s.commit()
    return {"ok": True}


@router.post("/ideas/clear")
def clear_ideas(s: Session = Depends(get_session)) -> dict[str, int]:
    """删除所有未建书的选题。"""
    rows = list(s.exec(select(Idea).where(Idea.chosen == False)))  # noqa: E712
    for r in rows:
        s.delete(r)
    s.commit()
    return {"deleted": len(rows)}


@router.post("/ideas/{idea_id}/revise")
async def revise_idea(idea_id: int, body: IdeaRevise, s: Session = Depends(get_session)) -> dict[str, Any]:
    idea = s.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(404, "选题不存在")
    if idea.chosen:
        raise HTTPException(409, "已建书的选题不能再改，去书里改设定")
    return job_out(submit("idea_revise", lambda ctx: planning.revise_idea(idea_id, body.instruction, body.route, ctx)))


@router.get("/ideas/{idea_id}")
def get_idea(idea_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    idea = s.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(404, "选题不存在")
    return idea_out(idea)


def _editable(s: Session, idea_id: int) -> Idea:
    idea = s.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(404, "选题不存在")
    if idea.chosen:
        raise HTTPException(409, "已建书的选题不能再改，去书里改设定")
    return idea


@router.patch("/ideas/{idea_id}")
def update_idea(idea_id: int, body: IdeaUpdate, s: Session = Depends(get_session)) -> dict[str, Any]:
    _editable(s, idea_id)
    return idea_out(planning.update_idea(idea_id, body.model_dump(exclude_none=True)))


@router.post("/ideas/{idea_id}/suggest")
async def suggest_idea_field(idea_id: int, body: IdeaSuggest, s: Session = Depends(get_session)) -> dict[str, Any]:
    _editable(s, idea_id)
    return job_out(submit("idea_field", lambda ctx: planning.suggest_field(idea_id, body.field, body.instruction, body.route, body.draft, ctx)))


@router.post("/ideas/{idea_id}/rescore")
async def rescore_idea(idea_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    if s.get(Idea, idea_id) is None:
        raise HTTPException(404, "选题不存在")
    return job_out(submit("idea_rescore", lambda ctx: planning.rescore_idea(idea_id, ctx)))


@router.post("/ideas/{idea_id}/undo")
def undo_idea(idea_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return idea_out(planning.undo_idea(idea_id))
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/ideas/rescore")
async def rescore_all_ideas() -> dict[str, Any]:
    return job_out(submit("idea_rescore", lambda ctx: planning.rescore_all(ctx)))


@router.post("/ideas/{idea_id}/adopt")
def adopt_idea(idea_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    book = planning.adopt_idea(idea_id)
    return book_out(s, s.get(Book, book.id) or book)


# ------------------------------------------------------------------ bible

@router.post("/books/{book_id}/bible/generate")
async def bible_generate(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return job_out(submit("bible_generate", lambda ctx: planning.generate_bible(book_id, ctx), book_id=book_id, lock_book=True))


@router.get("/books/{book_id}/cards")
def list_cards(book_id: int, type: str | None = None, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return [card_out(c) for c in common.cards(s, book_id, type or None)]


@router.post("/books/{book_id}/cards")
def create_card(book_id: int, body: CardIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    c = Card(book_id=book_id, **body.model_dump())
    s.add(c)
    s.commit()
    s.refresh(c)
    return card_out(c)


@router.put("/cards/{card_id}")
def update_card(card_id: int, body: CardUpdate, s: Session = Depends(get_session)) -> dict[str, Any]:
    c = s.get(Card, card_id)
    if c is None:
        raise HTTPException(404, "卡片不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(c, k, v)
    c.updated_at = utcnow()
    s.add(c)
    s.commit()
    s.refresh(c)
    return card_out(c)


@router.delete("/cards/{card_id}")
def delete_card(card_id: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    c = s.get(Card, card_id)
    if c is None:
        raise HTTPException(404, "卡片不存在")
    for f in s.exec(select(Fact).where(Fact.entity_id == card_id)):
        f.entity_id = None
        s.add(f)
    s.delete(c)
    s.commit()
    return {"ok": True}


@router.get("/books/{book_id}/facts")
def list_facts(book_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return [fact_out(f) for f in s.exec(select(Fact).where(Fact.book_id == book_id).order_by(Fact.id))]


# ------------------------------------------------------------------ outline

@router.post("/books/{book_id}/outline/generate")
async def outline_generate(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return job_out(submit("outline_generate", lambda ctx: outline.generate_outline(book_id, ctx), book_id=book_id, lock_book=True))


@router.post("/outline/{node_id}/expand")
async def outline_expand(node_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    node = s.get(OutlineNode, node_id)
    if node is None:
        raise HTTPException(404, "大纲节点不存在")
    bid = node.book_id
    return job_out(submit("outline_expand", lambda ctx: outline.expand_node(node_id, ctx), book_id=bid, lock_book=True))


@router.get("/books/{book_id}/outline")
def get_outline(book_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return [node_out(n) for n in common.outline_nodes(s, book_id)]


@router.put("/outline/{node_id}")
def update_outline(node_id: int, body: OutlineUpdate, s: Session = Depends(get_session)) -> dict[str, Any]:
    n = s.get(OutlineNode, node_id)
    if n is None:
        raise HTTPException(404, "大纲节点不存在")
    data = body.model_dump(exclude_unset=True)
    if "beats" in data and data["beats"] is not None and n.level == "chapter":
        book = _book(s, n.book_id)
        data["beats"] = {**outline.normalize_beats({**(n.beats or {}), **data["beats"]}, n.order, book.chapter_words),
                         **({"scenes": data["beats"]["scenes"]} if "scenes" in data["beats"] else {})}
    for k, v in data.items():
        if v is not None:
            setattr(n, k, v)
    s.add(n)
    s.commit()
    s.refresh(n)
    return node_out(n)


@router.delete("/outline/{node_id}")
def delete_outline(node_id: int, s: Session = Depends(get_session)) -> dict[str, int]:
    """删除大纲节点及其子树；子树里有已提交的章节时拒绝，未提交的草稿一并删除。"""
    n = s.get(OutlineNode, node_id)
    if n is None:
        raise HTTPException(404, "大纲节点不存在")
    if n.level == "book":
        raise HTTPException(400, "总纲不能删除，可以重新生成大纲")
    all_nodes = common.outline_nodes(s, n.book_id)
    kids: dict[int | None, list[OutlineNode]] = {}
    for x in all_nodes:
        kids.setdefault(x.parent_id, []).append(x)
    subtree, stack = [], [n]
    while stack:
        cur = stack.pop()
        subtree.append(cur)
        stack.extend(kids.get(cur.id, []))
    ids = {x.id for x in subtree}
    chapters = list(s.exec(select(Chapter).where(Chapter.book_id == n.book_id)))
    linked = [c for c in chapters if c.outline_node_id in ids or any(x.chapter_id == c.id for x in subtree)]
    if any(c.status == "committed" for c in linked):
        raise HTTPException(409, "这部分大纲下已有提交入账的章节，不能删除")
    for c in linked:
        s.delete(c)
    for x in subtree:
        s.delete(x)
    s.commit()
    return {"deleted": len(subtree)}


# ------------------------------------------------------------------ chapters

@router.get("/books/{book_id}/chapters")
def list_chapters(book_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    rows = s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number))
    return [chapter_out(c, with_content=False) for c in rows]


@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    c = s.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(404, "章节不存在")
    return chapter_out(c)


@router.put("/chapters/{chapter_id}")
def update_chapter(chapter_id: int, body: ChapterUpdate) -> dict[str, Any]:
    return chapter_out(writing.update_chapter(chapter_id, body.title, body.content))


@router.delete("/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    """只能删未提交的草稿；已提交的章节牵动人物状态与伏笔底账，不允许直接删。"""
    c = s.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(404, "章节不存在")
    if c.status == "committed":
        raise HTTPException(409, "已提交入账的章节不能删除")
    for node in s.exec(select(OutlineNode).where(OutlineNode.chapter_id == chapter_id)):
        node.chapter_id = None
        if node.status == "written":
            node.status = "planned"
        s.add(node)
    s.delete(c)
    s.commit()
    return {"ok": True}


@router.post("/books/{book_id}/chapters/write-next")
async def write_next(book_id: int, body: WriteNextIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    variants = body.variants if body else None
    return job_out(submit("chapter_write_next", lambda ctx: writing.write_next(book_id, ctx, variants), book_id=book_id, lock_book=True))


@router.post("/books/{book_id}/chapters/write-batch")
async def write_batch(book_id: int, body: WriteBatchIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    count = body.count if body else 3
    variants = body.variants if body else None
    return job_out(submit("chapter_write_batch", lambda ctx: writing.write_batch(book_id, count, ctx, variants), book_id=book_id, lock_book=True))


def _chapter_book(s: Session, chapter_id: int) -> int:
    c = s.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(404, "章节不存在")
    return c.book_id


@router.post("/chapters/{chapter_id}/review")
async def review_chapter(chapter_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    bid = _chapter_book(s, chapter_id)
    return job_out(submit("chapter_review", lambda ctx: writing.review_chapter_job(chapter_id, ctx), book_id=bid, lock_book=True))


@router.post("/chapters/{chapter_id}/humanize")
async def humanize_chapter(chapter_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    bid = _chapter_book(s, chapter_id)
    return job_out(submit("chapter_humanize", lambda ctx: writing.humanize_chapter_job(chapter_id, ctx), book_id=bid, lock_book=True))


@router.post("/chapters/{chapter_id}/thicken")
async def thicken_chapter(chapter_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    bid = _chapter_book(s, chapter_id)
    return job_out(submit("chapter_thicken", lambda ctx: writing.thicken_chapter_job(chapter_id, ctx), book_id=bid, lock_book=True))


@router.post("/chapters/{chapter_id}/adopt-variant")
def adopt_variant(chapter_id: int, body: AdoptVariantIn) -> dict[str, Any]:
    return chapter_out(writing.adopt_variant(chapter_id, body.variant_id))


@router.post("/chapters/{chapter_id}/commit")
def commit_chapter(chapter_id: int) -> dict[str, Any]:
    return chapter_out(writing.commit_chapter(chapter_id))


@router.get("/books/{book_id}/foreshadows")
def list_foreshadows(book_id: int, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _book(s, book_id)
    return [foreshadow_out(f) for f in s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id).order_by(Foreshadow.id))]


# ------------------------------------------------------------------ style

@router.get("/books/{book_id}/style")
def get_style(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return style_out(common.get_style(s, book_id))


@router.put("/books/{book_id}/style")
def put_style(book_id: int, body: StyleIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    if count_words(body.sample_text) > style_svc.SAMPLE_MAX:
        raise HTTPException(400, f"范文不超过 {style_svc.SAMPLE_MAX} 字（当前 {count_words(body.sample_text)} 字）")
    st = s.get(Style, book_id) or Style(book_id=book_id)
    if st.sample_text != body.sample_text:
        st.extracted = None  # 范文变了，旧的提炼结果作废
    st.sample_text, st.voice_notes, st.pov, st.tone = body.sample_text, body.voice_notes, body.pov, body.tone
    s.add(st)
    s.commit()
    s.refresh(st)
    return style_out(st)


@router.post("/books/{book_id}/style/extract")
async def extract_style(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return job_out(submit("style_extract", lambda ctx: style_svc.extract_style(book_id, ctx), book_id=book_id))


# ------------------------------------------------------------------ package

@router.post("/books/{book_id}/package/generate")
async def package_generate(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return job_out(submit("package_generate", lambda ctx: packaging.generate_package(book_id, ctx), book_id=book_id))


@router.post("/books/{book_id}/covers/generate")
async def covers_generate(book_id: int, body: CoversIn | None = Body(default=None), s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    prompt = body.prompt if body else None
    n = body.n if body else 4
    return job_out(submit("covers_generate", lambda ctx: packaging.generate_covers(book_id, prompt, n, ctx), book_id=book_id))


@router.get("/books/{book_id}/package")
def get_package(book_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    _book(s, book_id)
    return package_out(book_id, s.get(Package, book_id))


@router.put("/books/{book_id}/package")
def put_package(book_id: int, body: PackageUpdate, s: Session = Depends(get_session)) -> dict[str, Any]:
    b = _book(s, book_id)
    p = s.get(Package, book_id) or Package(book_id=book_id)
    data = body.model_dump(exclude_unset=True)
    if "titles" in data and data["titles"] is not None:
        p.titles = [{"title": str(t.get("title", "")),
                     "score": int(t["score"]) if isinstance(t.get("score"), (int, float)) else packaging.score_title(str(t.get("title", "")))["total"]}
                    for t in data["titles"] if t.get("title")]
    for k in ("blurb", "tags", "cover_prompt"):
        if data.get(k) is not None:
            setattr(p, k, data[k])
    if "chosen_cover" in data:
        cc = data["chosen_cover"]
        if cc is not None and cc not in (p.covers or []):
            raise HTTPException(400, "chosen_cover 必须是已生成的封面之一")
        p.chosen_cover = cc
        b.cover_url = cc
        b.updated_at = utcnow()
        s.add(b)
    s.add(p)
    s.commit()
    s.refresh(p)
    return package_out(book_id, p)


@router.get("/books/{book_id}/export")
def export_book(book_id: int, s: Session = Depends(get_session)) -> Response:
    _book(s, book_id)
    title, data = packaging.build_export(book_id)
    fname = f"{title}_发布包.zip"
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=\"novelos_{book_id}.zip\"; filename*=UTF-8''{quote(fname)}"},
    )

