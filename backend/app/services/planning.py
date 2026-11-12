"""选题与设定库。"""

from __future__ import annotations

import re
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
    """按题材在榜单里的名次给分：第 1 名 90，往后递减，没上榜 40。"""
    if not trends:
        return 50
    for i, t in enumerate(trends):
        if t["category"] and (t["category"] in genre or genre in t["category"]):
            rising = t.get("rising", 0) / max(1, t.get("books", 1))
            return int(round(max(45, 90 - 6 * i) + min(8, 20 * rising)))
    return 40


_PREFIX_RE = re.compile(r"^\s*[^：:，,！!？?\s]{1,4}[：:]\s*")


def _clean_title(title: str, genre: str) -> str:
    t = str(title).strip().strip("《》")
    m = _PREFIX_RE.match(t)
    if m and len(t) - m.end() >= 4:
        t = t[m.end():]
    return t[:40]


def _clamp(v: Any, default: int = 50) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return default


def _review_scores(items: list[dict[str, Any]], gender: str, trends: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """让审稿模型横向复核新颖和适配，压住模型自评虚高。失败时返回空，沿用自评。"""
    tops = [x for t in trends[:8] for x in t.get("sample_titles", [])[:4]]
    listing = "\n".join(
        f"{i}. 《{it.get('title')}》［{it.get('genre', '')}］{it.get('logline', '')} 卖点：{'；'.join(map(str, it.get('selling_points') or []))}"
        f" 终局：{it.get('endgame', '')} 长线：{' → '.join(map(str, it.get('arc') or []))}"
        for i, it in enumerate(items, 1)
    )
    try:
        data = get_gateway().chat_json(
            "idea_score", system_prompt("idea_score"),
            render("idea_score", gender_label=common.GENDER_LABEL.get(gender, gender),
                   top_titles="、".join(tops) or "（无榜单数据）", ideas=listing),
            meta={"count": len(items)}, temperature=0.2,
        )
    except Exception:  # noqa: BLE001
        return {}
    out: dict[int, dict[str, Any]] = {}
    for sc in (data.get("scores") if isinstance(data, dict) else None) or []:
        if isinstance(sc, dict) and str(sc.get("index", "")).isdigit():
            out[int(sc["index"])] = sc
    return out


_IDEA_FIELDS = ("title", "logline", "selling_points", "hook", "expectations", "endgame", "arc", "genre", "scores")


def _idea_text(i: Idea) -> str:
    return (f"书名：{i.title}\n题材：{i.genre}\n简介：{i.logline}\n卖点：{'；'.join(i.selling_points)}\n钩子：{i.hook}\n"
            f"长期期待：{'；'.join(i.expectations)}\n长线阶段：{' → '.join(i.arc)}\n终局：{i.endgame}")


def revise_idea(idea_id: int, instruction: str, route: str | None, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        gender = idea.gender
        history = "\n".join(f"- {v.get('instruction')}" for v in idea.versions if v.get("instruction")) or "（无）"
        user = render("idea_revise", gender_label=common.GENDER_LABEL.get(gender, gender), idea=_idea_text(idea),
                      history=history, instruction=instruction.strip())
        cur = {k: getattr(idea, k) for k in _IDEA_FIELDS}
        meta = {**{k: v for k, v in cur.items() if k != "scores"}, "instruction": instruction, "gender": gender}
    ctx.progress(20, "按意见修改")
    it = get_gateway().chat_json("idea_revise", system_prompt("idea_revise"), user, meta=meta, route=route)
    if not isinstance(it, dict) or not it.get("title"):
        raise ValueError("模型没有返回修改后的选题")
    ctx.progress(70, "重新打分")
    with session_scope() as s:
        trends = radar.compute_trends(s, gender=gender)
    g = str(it.get("genre") or cur["genre"] or "")
    rv = _review_scores([it], gender, trends).get(1) or {}
    heat = _heat_for(g, trends)
    novelty = round(0.8 * _clamp(rv["novelty"]) + 0.2 * _clamp(it.get("novelty"))) if "novelty" in rv else min(80, _clamp(it.get("novelty")))
    fit = round(0.8 * _clamp(rv["fit"]) + 0.2 * _clamp(it.get("fit"))) if "fit" in rv else min(80, _clamp(it.get("fit")))
    issue = str(rv.get("issue") or "").strip()
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        idea.versions = [*idea.versions, {**cur, "instruction": instruction.strip()}][-10:]
        idea.title = _clean_title(it["title"], g)
        idea.logline = str(it.get("logline") or idea.logline)
        idea.selling_points = [str(x) for x in (it.get("selling_points") or idea.selling_points)][:4]
        idea.hook = str(it.get("hook") or idea.hook)
        idea.expectations = [str(x) for x in (it.get("expectations") or idea.expectations)][:3]
        idea.endgame = str(it.get("endgame") or idea.endgame)[:120]
        idea.arc = [str(x) for x in (it.get("arc") or idea.arc)][:6]
        idea.genre = g
        idea.scores = {"heat": heat, "novelty": novelty, "fit": fit, "overall": round(0.3 * heat + 0.3 * novelty + 0.4 * fit),
                       "issue": "" if issue in ("无", "没有", "-") else issue[:40]}
        s.add(idea)
        s.commit()
    return {"idea_id": idea_id, "change": str(it.get("change") or "")[:80]}


def undo_idea(idea_id: int) -> Idea:
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        if not idea.versions:
            raise ValueError("没有可以撤回的版本")
        prev = idea.versions[-1]
        for k in _IDEA_FIELDS:
            if k in prev:
                setattr(idea, k, prev[k])
        idea.versions = idea.versions[:-1]
        s.add(idea)
        s.commit()
        s.refresh(idea)
        return idea


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
    with session_scope() as s:
        recent = s.exec(select(Idea).where(Idea.gender == gender).order_by(Idea.id.desc()).limit(30)).all()  # type: ignore[union-attr]
        existing = "\n".join(f"- 《{i.title}》{i.logline[:50]}" for i in recent) or "（无）"
    ctx.progress(20, "构思选题")
    data = get_gateway().chat_json(
        "ideation", system_prompt("ideation"),
        render("ideation", count=count, gender_label=common.GENDER_LABEL.get(gender, gender),
               genre_hint=f"题材限定：{genre}。" if genre else "", trends=trend_text, existing=existing),
        meta={"count": count, "gender": gender, "genre": genre, "trends": trends[:6] if params.get("from_trends") else []},
    )
    items = data.get("ideas") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError("模型没有返回选题")
    items = [it for it in items if isinstance(it, dict) and it.get("title")][:count]
    if not items:
        raise ValueError("模型没有返回选题")
    ctx.progress(70, "编辑复核打分")
    reviewed = _review_scores(items, gender, trends) if len(items) else {}
    ids: list[int] = []
    with session_scope() as s:
        for n, it in enumerate(items, 1):
            g = str(it.get("genre") or genre or "")
            heat = _heat_for(g, trends)
            rv = reviewed.get(n) or {}
            # 复核分为主，自评只占两成，避免模型自己给自己打 95
            novelty = round(0.8 * _clamp(rv["novelty"]) + 0.2 * _clamp(it.get("novelty"))) if "novelty" in rv else min(80, _clamp(it.get("novelty")))
            fit = round(0.8 * _clamp(rv["fit"]) + 0.2 * _clamp(it.get("fit"))) if "fit" in rv else min(80, _clamp(it.get("fit")))
            issue = str(rv.get("issue") or "").strip()
            idea = Idea(
                title=_clean_title(it["title"], g), logline=str(it.get("logline", "")),
                selling_points=[str(x) for x in (it.get("selling_points") or [])][:4], hook=str(it.get("hook", "")),
                expectations=[str(x) for x in (it.get("expectations") or [])][:3],
                endgame=str(it.get("endgame") or "")[:120],
                arc=[str(x) for x in (it.get("arc") or [])][:6],
                genre=g, gender=gender,
                scores={"heat": heat, "novelty": novelty, "fit": fit,
                        "overall": round(0.3 * heat + 0.3 * novelty + 0.4 * fit),
                        "issue": "" if issue in ("无", "没有", "-") else issue[:40]},
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
            premise=f"{idea.logline}\n卖点：{'；'.join(idea.selling_points)}" + (f"\n长期期待：{'；'.join(idea.expectations)}" if idea.expectations else "")
            + (f"\n终局目标：{idea.endgame}" if idea.endgame else "")
            + (f"\n长线阶段：{' → '.join(idea.arc)}" if idea.arc else ""), status="bible",
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
