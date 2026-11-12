"""选题与设定库。"""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from app.services.research import research_notes
from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Book, Card, Fact, Idea, utcnow
from app.radar import service as radar
from app.services import common
from app.services.changes import CARD_TYPES
from app.services.common import NotFound
from app.skills.loader import render, system_prompt


def _heat_for(genre: str, trends: list[dict[str, Any]]) -> int:
    if not trends:
        return 50
    top = max(t["heat"] for t in trends) or 1
    for t in trends:
        if t["category"] and (t["category"] in genre or genre in t["category"]):
            return int(round(30 + 70 * t["heat"] / top))
    return 35


def generate_ideas(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    gender = params.get("gender") or "male"
    count = max(1, min(10, int(params.get("count") or 3)))
    genre = params.get("genre")
    with session_scope() as s:
        trends = radar.compute_trends(s, gender=gender)
    trend_text = "\n".join(
        f"- {t['category']}：热度 {t['heat']}，上榜 {t['books']} 本，上升 {t['rising']} 本，例：{'、'.join(t['sample_titles'][:3])}"
        for t in trends[:8]
    ) if params.get("from_trends") else "（未使用榜单）"
    ctx.progress(20, "构思选题")
    data = get_gateway().chat_json(
        "ideation", system_prompt("ideation"),
        render("ideation", count=count, gender_label=common.GENDER_LABEL.get(gender, gender),
               genre_hint=f"题材限定：{genre}。" if genre else "", trends=trend_text),
        meta={"count": count, "gender": gender, "genre": genre, "trends": trends[:6] if params.get("from_trends") else []},
    )
    items = data.get("ideas") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError("模型没有返回选题")
    ids: list[int] = []
    with session_scope() as s:
        for it in items[:count]:
            if not isinstance(it, dict) or not it.get("title"):
                continue
            g = str(it.get("genre") or genre or "")
            heat = _heat_for(g, trends)
            novelty = max(0, min(100, int(it.get("novelty") or 50)))
            fit = max(0, min(100, int(it.get("fit") or 50)))
            idea = Idea(
                title=str(it["title"])[:60], logline=str(it.get("logline", "")),
                selling_points=[str(x) for x in (it.get("selling_points") or [])][:6], hook=str(it.get("hook", "")),
                genre=g, gender=gender,
                scores={"heat": heat, "novelty": novelty, "fit": fit, "overall": round(0.4 * heat + 0.3 * novelty + 0.3 * fit)},
            )
            s.add(idea)
            s.flush()
            ids.append(idea.id or 0)
        s.commit()
    return {"idea_ids": ids}


def adopt_idea(idea_id: int) -> Book:
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        if idea.book_id and s.get(Book, idea.book_id):
            return s.get(Book, idea.book_id)  # type: ignore[return-value]
        from app.config import get_settings

        st = get_settings()
        book = Book(
            title=idea.title, genre=idea.genre, gender=idea.gender, tagline=idea.hook,
            premise=f"{idea.logline}\n卖点：{'；'.join(idea.selling_points)}", status="bible",
            target_words=st.default_target_words, chapter_words=st.default_chapter_words,
        )
        s.add(book)
        s.flush()
        idea.book_id = book.id
        idea.chosen = True
        s.add(idea)
        s.commit()
        s.refresh(book)
        return book


def generate_bible(book_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = common.kit_meta(s, book)
        user = render("bible", title=book.title, genre=book.genre,
                      gender_label=common.GENDER_LABEL.get(book.gender, book.gender), premise=book.premise or book.tagline)
    user += research_notes("bible", user, book_id, ctx, 10)
    ctx.progress(15, "生成设定库")
    data = get_gateway().chat_json("bible", system_prompt("bible"), user, meta=meta)
    if not isinstance(data, dict) or not data.get("cards"):
        raise ValueError("设定库结果缺少 cards")
    ctx.progress(70, "写入设定卡与初始事实")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        existing = {c.name: c for c in common.cards(s, book_id)}
        n_cards = 0
        for it in data["cards"]:
            if not isinstance(it, dict) or not it.get("name"):
                continue
            t = it.get("type") if it.get("type") in CARD_TYPES else "character"
            name = str(it["name"])[:40]
            card = existing.get(name) or Card(book_id=book_id, type=t, name=name)
            card.type, card.summary = t, str(it.get("summary", ""))
            card.data = it.get("data") if isinstance(it.get("data"), dict) else {}
            card.known_by = [str(x) for x in (it.get("known_by") or [])]
            card.updated_at = utcnow()
            s.add(card)
            s.flush()
            existing[name] = card
            n_cards += 1
        n_facts = 0
        for f in data.get("facts") or []:
            if not isinstance(f, dict) or not f.get("key"):
                continue
            ent = existing.get(str(f.get("entity", "")))
            dup = s.exec(select(Fact).where(Fact.book_id == book_id, Fact.entity_id == (ent.id if ent else None),
                                            Fact.key == str(f["key"]), Fact.to_chapter == None)).first()  # noqa: E711
            if dup:
                continue
            s.add(Fact(book_id=book_id, entity_id=ent.id if ent else None, key=str(f["key"]), value=str(f.get("value", "")),
                       from_chapter=0, visibility="reader" if f.get("visibility") == "reader" else "author"))
            n_facts += 1
        if data.get("tagline") and not book.tagline:
            book.tagline = str(data["tagline"])
        elif data.get("tagline"):
            book.tagline = str(data["tagline"])
        if book.status == "idea":
            book.status = "bible"
        book.updated_at = utcnow()
        s.add(book)
        s.commit()
    return {"cards": n_cards, "facts": n_facts}
