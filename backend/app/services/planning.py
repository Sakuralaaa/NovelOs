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
from app.services import common, tropes
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


# 分项打分：每项 0–4 档，由程序加总换算，避免模型直接给总分时全挤在 85–95
RUBRIC: dict[str, tuple[str, str]] = {
    "gf": ("novelty", "金手指玩法"),
    "angle": ("novelty", "切入点"),
    "fresh": ("novelty", "不撞车"),
    "opening": ("fit", "开篇抓人"),
    "payoff": ("fit", "爽点兑现"),
    "growth": ("fit", "成长后劲"),
    "longrun": ("fit", "长线结构"),
    "pitch": ("fit", "书名简介"),
}


def _score(rv: dict[str, Any], heat: int, title: str = "") -> dict[str, Any]:
    """把复核的分项档位换算成分数。复核失败时给中性分，不用模型自评。"""
    detail = {k: max(0, min(4, int(rv[k]))) for k in RUBRIC if str(rv.get(k, "")).lstrip("-").isdigit()}
    def part(dim: str) -> int:
        keys = [k for k, (d, _) in RUBRIC.items() if d == dim]
        got = [detail[k] for k in keys if k in detail]
        return round(100 * sum(got) / (4 * len(got))) if got else 50
    novelty, fit = part("novelty"), part("fit")
    if title and not 6 <= len(title) <= 18:  # 书名过短或过长，程序直接扣分
        fit = max(0, fit - 5)
    issue = str(rv.get("issue") or "").strip()
    # 同题材下热度几乎一样，只占一成五，主要看选题本身
    return {"heat": heat, "novelty": novelty, "fit": fit, "overall": round(0.15 * heat + 0.35 * novelty + 0.5 * fit),
            "issue": "" if issue in ("无", "没有", "-") else issue[:40], "detail": detail}


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


FIELD_SPEC: dict[str, tuple[str, str, bool]] = {
    # 字段：(名称, 规则, 是否列表)
    "title": ("书名", "番茄式大白话，8–16 字，不带题材前缀。", False),
    "genre": ("题材", "用番茄的分类名。", False),
    "logline": ("简介", "一到两句，80 字内：身份、外部压力、金手指、怎么越用越强。", False),
    "selling_points": ("卖点", "3 条，每条 30 字内，说读者能看到的爽点，不写内部标签。", True),
    "hook": ("钩子", "开篇第一个场面，60 字内。", False),
    "expectations": ("长期期待", "2–3 条，读者追下去最想看到的事。", True),
    "arc": ("长线阶段", "4–6 个阶段，每个阶段换一层地图，对手和实力跟着升，写清在哪、对谁、拿到什么。", True),
    "endgame": ("终局", "一句话的终局目标。", False),
}


def suggest_field(idea_id: int, field: str, instruction: str, route: str | None, draft: dict[str, Any] | None,
                  ctx: JobContext) -> dict[str, Any]:
    """只改一项，结果作为建议返回，不落库，由作者确认后保存。"""
    if field not in FIELD_SPEC:
        raise ValueError("不支持的字段")
    label, rule, is_list = FIELD_SPEC[field]
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        tmp = Idea(**{k: getattr(idea, k) for k in ("title", "logline", "selling_points", "hook", "expectations", "endgame", "arc", "genre", "gender")})
    for k, v in (draft or {}).items():  # 用页面上还没保存的内容
        if k in FIELD_SPEC and isinstance(v, (list, str)):
            setattr(tmp, k, v)
    user = render("idea_field", gender_label=common.GENDER_LABEL.get(tmp.gender, tmp.gender), field_label=label,
                  idea=_idea_text(tmp), instruction=instruction.strip() or "写得更好、更抓人。",
                  field_rule=f"「{label}」要求：{rule}", value_shape='["…","…"]' if is_list else '"…"')
    with session_scope() as s:
        tl = tropes.global_tropes(s)
    user += tropes.prompt_block(tl, instruction)
    ctx.progress(30, f"改{label}")
    cur = getattr(tmp, field)
    data = get_gateway().chat_json("idea_field", system_prompt("idea_field"), user,
                                   meta={"field": field, "current": cur, "instruction": instruction,
                                         "banned_keywords": tropes.keywords(tl, instruction)}, route=route)
    v = data.get("value") if isinstance(data, dict) else data
    if is_list:
        v = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()][:6]
    else:
        v = str(v or "").strip()
        if field == "title":
            v = _clean_title(v, tmp.genre)
    if not v:
        raise ValueError("模型没有给出修改")
    return {"field": field, "value": v}


def update_idea(idea_id: int, fields: dict[str, Any]) -> Idea:
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        cur = {k: getattr(idea, k) for k in _IDEA_FIELDS}
        changed = False
        for k, v in fields.items():
            if k not in FIELD_SPEC or v is None:
                continue
            v = [str(x).strip() for x in v if str(x).strip()] if FIELD_SPEC[k][2] else str(v).strip()
            if k == "title":
                v = v.strip("《》")[:40]
            if v != getattr(idea, k):
                setattr(idea, k, v)
                changed = True
        if changed:
            idea.versions = [*(idea.versions or []), {**cur, "instruction": "手动修改"}][-10:]
            s.add(idea)
            s.commit()
            s.refresh(idea)
        return idea


def rescore_all(ctx: JobContext) -> dict[str, Any]:
    """按新的分项标准把未建书的选题重新打一遍，按频道分批，每批 8 个。"""
    with session_scope() as s:
        rows = [(i.id, i.gender, {k: getattr(i, k) for k in ("title", "logline", "selling_points", "endgame", "arc", "genre")})
                for i in s.exec(select(Idea).where(Idea.chosen == False))]  # noqa: E712
    done = 0
    for gender in ("male", "female"):
        group = [r for r in rows if r[1] == gender]
        if not group:
            continue
        with session_scope() as s:
            trends = radar.compute_trends(s, gender=gender)
        for k in range(0, len(group), 8):
            chunk = group[k:k + 8]
            ctx.progress(5 + int(90 * done / max(1, len(rows))), f"复核打分 {done}/{len(rows)}")
            rv = _review_scores([r[2] for r in chunk], gender, trends)
            with session_scope() as s:
                for n, (iid, _, it) in enumerate(chunk, 1):
                    idea = s.get(Idea, iid)
                    if idea is not None and rv.get(n):
                        idea.scores = _score(rv[n], _heat_for(it["genre"], trends), idea.title)
                        s.add(idea)
                s.commit()
            done += len(chunk)
    return {"count": done}


def rescore_idea(idea_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        gender = idea.gender
        it = {k: getattr(idea, k) for k in ("title", "logline", "selling_points", "endgame", "arc", "genre")}
        trends = radar.compute_trends(s, gender=gender)
    ctx.progress(30, "编辑复核打分")
    rv = _review_scores([it], gender, trends).get(1)
    if not rv:
        raise ValueError("打分失败，检查审稿模型")
    heat = _heat_for(it["genre"], trends)
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        idea.scores = _score(rv, heat, idea.title)
        s.add(idea)
        s.commit()
    return {"idea_id": idea_id}


def revise_idea(idea_id: int, instruction: str, route: str | None, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        gender = idea.gender
        history = "\n".join(f"- {v.get('instruction')}" for v in (idea.versions or []) if v.get("instruction")) or "（无）"
        user = render("idea_revise", gender_label=common.GENDER_LABEL.get(gender, gender), idea=_idea_text(idea),
                      history=history, instruction=instruction.strip())
        tl = tropes.global_tropes(s)
        user += tropes.prompt_block(tl, instruction)
        cur = {k: getattr(idea, k) for k in _IDEA_FIELDS}
        meta = {**{k: v for k, v in cur.items() if k != "scores"}, "instruction": instruction, "gender": gender,
                "banned_keywords": tropes.keywords(tl, instruction)}
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
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        if idea is None:
            raise NotFound("选题不存在")
        idea.versions = [*(idea.versions or []), {**cur, "instruction": instruction.strip()}][-10:]
        idea.title = _clean_title(it["title"], g)
        idea.logline = str(it.get("logline") or idea.logline)
        idea.selling_points = [str(x) for x in (it.get("selling_points") or idea.selling_points)][:4]
        idea.hook = str(it.get("hook") or idea.hook)
        idea.expectations = [str(x) for x in (it.get("expectations") or idea.expectations)][:3]
        idea.endgame = str(it.get("endgame") or idea.endgame)[:120]
        idea.arc = [str(x) for x in (it.get("arc") or idea.arc)][:6]
        idea.genre = g
        idea.scores = _score(rv, heat, idea.title)
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
        tl = tropes.global_tropes(s)
    ctx.progress(20, "构思选题")
    data = get_gateway().chat_json(
        "ideation", system_prompt("ideation"),
        render("ideation", count=count, gender_label=common.GENDER_LABEL.get(gender, gender),
               genre_hint=f"题材限定：{genre}。" if genre else "", trends=trend_text, existing=existing) + tropes.prompt_block(tl),
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
            title = _clean_title(it["title"], g)
            idea = Idea(
                title=title, logline=str(it.get("logline", "")),
                selling_points=[str(x) for x in (it.get("selling_points") or [])][:4], hook=str(it.get("hook", "")),
                expectations=[str(x) for x in (it.get("expectations") or [])][:3],
                endgame=str(it.get("endgame") or "")[:120],
                arc=[str(x) for x in (it.get("arc") or [])][:6],
                genre=g, gender=gender,
                scores=_score(rv, heat, title),
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
        tl = tropes.tropes_for(s, book)
        meta["banned_keywords"] = tropes.keywords(tl)
    user += tropes.prompt_block(tl)
    user += research_notes("bible", user, book_id, ctx, 10)
    ctx.progress(15, "生成设定库")
    data = get_gateway().chat_json("bible", system_prompt("bible"), user, meta=meta)
    if not isinstance(data, dict) or not data.get("cards"):
        raise ValueError("设定库结果缺少 cards")
    ctx.progress(70, "写入设定卡与初始事实")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        existing = {c.name: c for c in common.cards(s, book_id)}
        if existing:  # 已有设定时先存快照，可回滚
            from app.services.bible_ops import snapshot

            snapshot(s, book_id, "重新生成设定前")
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


CARD_FIELDS = {"name": ("名称", False), "summary": ("简介", False), "voice": ("说话方式", False),
               "catchphrases": ("口头禅", True), "habits": ("小动作", True), "demeanor": ("神态习惯", False)}


def suggest_card(book_id: int, card_id: int | None, field: str | None, instruction: str, route: str | None,
                 draft: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    """改一张设定卡（或卡上的一项），结果回填编辑器，作者保存后才落库。"""
    import json as _json
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = common.kit_meta(s, book)
        all_cards = common.cards(s, book_id)
        base: dict[str, Any] = {}
        if card_id is not None:
            c = s.get(Card, card_id)
            if c is None or c.book_id != book_id:
                raise NotFound("卡片不存在")
            base = {"type": c.type, "name": c.name, "summary": c.summary, "data": dict(c.data or {}), "known_by": list(c.known_by or [])}
        cur = {**base, **{k: v for k, v in (draft or {}).items() if k in ("type", "name", "summary", "data", "known_by")}}
        cur.setdefault("type", "character")
        cur.setdefault("data", {})
        others = "\n".join(f"[{c.type}] {c.name}：{c.summary}" for c in all_cards if c.id != card_id) or "（无）"
        ctx_text = common.book_context(s, book, with_cards=False)
        tl = tropes.tropes_for(s, book)
    data_obj = cur.get("data") if isinstance(cur.get("data"), dict) else {}
    if field:
        if field.startswith("data."):
            key = field[5:]
            label, is_list = key, isinstance(data_obj.get(key), list)
            value = data_obj.get(key, "")
        elif field in CARD_FIELDS:
            label, is_list = CARD_FIELDS[field]
            value = cur.get(field) if field in ("name", "summary") else data_obj.get(field, [] if is_list else "")
        else:
            raise ValueError("不支持的字段")
        scope = f"只改「{label}」这一项，其它不动。"
        if not isinstance(value, (str, list)):
            shape, value_shape = '{"value": <与原值同样结构的 JSON>}', None
        else:
            value_shape = '["…","…"]' if is_list else '"…"'
            shape = f'{{"value": {value_shape}}}'
    else:
        value = cur
        scope = ("按要求改整张卡：只动要求涉及的部分，没提到的内容原样保留；空白新卡就按名称、类型和要求写完整。"
                 "人物卡 data 里保留 role、voice、catchphrases、habits、demeanor 等键；力量体系 data 含 input、cost、limit。")
        shape = '{"card":{"type":"world|power|faction|character|item|location","name":"","summary":"","data":{},"known_by":[]}}'
    user = render("card_suggest", book_context=ctx_text, others=others, card=_json.dumps(cur, ensure_ascii=False),
                  instruction=instruction.strip() or "写得更具体、更有画面感，和其它设定咬合。", scope=scope, shape=shape)
    user += tropes.prompt_block(tl, instruction)
    ctx.progress(30, "AI 改设定")
    out = get_gateway().chat_json("card_suggest", system_prompt("card_suggest"), user,
                                  meta={**meta, "field": field, "current": value, "instruction": instruction,
                                        "banned_keywords": tropes.keywords(tl, instruction)}, route=route)
    if not isinstance(out, dict):
        raise ValueError("模型没有给出修改")
    if field:
        v = out.get("value")
        if isinstance(value, list):
            v = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
        elif isinstance(value, str):
            v = str(v or "").strip()
        if v in (None, "", []):
            raise ValueError("模型没有给出修改")
        return {"field": field, "value": v}
    card = out.get("card") if isinstance(out.get("card"), dict) else out
    t = card.get("type") if card.get("type") in CARD_TYPES else cur["type"]
    res = {"type": t, "name": str(card.get("name") or cur.get("name") or "")[:40], "summary": str(card.get("summary") or ""),
           "data": card.get("data") if isinstance(card.get("data"), dict) else data_obj,
           "known_by": [str(x) for x in (card.get("known_by") if isinstance(card.get("known_by"), list) else cur.get("known_by") or [])]}
    if not res["name"]:
        raise ValueError("模型没有给出修改")
    return {"card": res}
