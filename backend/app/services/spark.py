"""v0.13 抽卡立项向导：赛道来自雷达真实榜单 → 世界观 / 主角 / 金手指三轮抽卡（每轮 9 张，可保留跨轮）→ 立项书（带种子设定卡）。

每张卡带三个标记：赛道热度、命中禁用套路、与榜上书的相似度（3 字片段重合）。
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Card, Idea, RankItem, SparkSession, utcnow
from app.services import tropes
from app.services.common import Conflict, NotFound
from app.skills.loader import render, system_prompt

AXES = {"world": "世界观", "hero": "主角", "cheat": "金手指"}
AXIS_RULE = {
    "world": "世界观要有一条能制造长期冲突的规则（资源怎么分、强弱怎么定、谁在压迫谁）。",
    "hero": "主角写身份 + 处境 + 性格底色，开局就有让读者想看他翻身的困境。",
    "cheat": "金手指写清用法、现阶段上限、成长路线，和已定的世界观、主角对得上。",
}
BUILTIN_TRACKS = {
    "male": [("玄幻", ["高武", "东方玄幻", "异世大陆"]), ("仙侠", ["修真", "洪荒", "古典仙侠"]), ("都市", ["都市高武", "神医", "异能"]),
             ("历史", ["架空", "争霸", "穿越"]), ("科幻", ["末世", "星际", "进化"]), ("悬疑", ["灵异", "规则怪谈", "推理"]),
             ("游戏", ["网游", "全民游戏", "电竞"]), ("战神", ["赘婿", "兵王", "归来"])],
    "female": [("古言", ["宫斗", "宅斗", "种田"]), ("现言", ["豪门", "甜宠", "职场"]), ("玄幻言情", ["修仙", "穿越", "快穿"]),
               ("幻想言情", ["末世", "系统", "无限流"]), ("悬疑", ["灵异", "推理", "规则怪谈"]), ("年代", ["七零", "八零", "重生"])],
}
TAG_GROUPS = {"male": ["系统", "重生", "无敌", "扮猪吃虎", "打脸", "签到", "多女主", "单女主", "热血", "种田", "群像", "黑暗"],
              "female": ["甜宠", "虐恋", "大女主", "双强", "穿书", "重生", "团宠", "马甲", "追妻", "先婚后爱", "逆袭", "萌宝"]}


def _now() -> str:
    return utcnow().isoformat()


def tracks(s: Session, gender: str) -> dict[str, Any]:
    from app.radar.service import compute_trends

    gender = gender if gender in ("male", "female") else "male"
    try:
        hot = compute_trends(s, gender)
    except Exception:  # noqa: BLE001
        hot = []
    by = {h["category"]: h for h in hot}
    out = []
    seen = set()
    for h in hot[:16]:
        sub = next((subs for name, subs in BUILTIN_TRACKS[gender] if name in h["category"] or h["category"] in name), [])
        out.append({"track": h["category"], "heat": h["heat"], "rising": h["rising"], "subs": sub, "sample_titles": h["sample_titles"], "from_rank": True})
        seen.add(h["category"])
    for name, subs in BUILTIN_TRACKS[gender]:
        if name not in seen:
            h = by.get(name) or {}
            out.append({"track": name, "heat": h.get("heat"), "rising": h.get("rising"), "subs": subs, "sample_titles": [], "from_rank": False})
    return {"gender": gender, "tracks": out, "tag_groups": TAG_GROUPS[gender]}


def _get(s: Session, sid: int) -> SparkSession:
    r = s.get(SparkSession, sid)
    if r is None:
        raise NotFound("抽卡会话不存在")
    return r


def out(r: SparkSession) -> dict[str, Any]:
    st = dict(r.state or {})
    return {"id": r.id, "idea_id": r.idea_id, **st, "created_at": r.created_at.isoformat() if r.created_at else None}


def create(s: Session, body: dict[str, Any]) -> dict[str, Any]:
    gender = body.get("gender") if body.get("gender") in ("male", "female") else "male"
    track = str(body.get("track") or "").strip()[:20]
    if not track:
        raise ValueError("请选择赛道")
    st = {"gender": gender, "track": track, "sub": str(body.get("sub") or "")[:20],
          "tags": [str(t)[:10] for t in (body.get("tags") or [])][:8],
          "inspiration": {k: str((body.get("inspiration") or {}).get(k) or "")[:300] for k in ("title", "tags", "synopsis")},
          "cards": {a: [] for a in AXES}, "keep": {a: [] for a in AXES}, "picks": {}, "rounds": {a: 0 for a in AXES}, "proposal": None}
    r = SparkSession(state=st)
    s.add(r)
    s.commit()
    s.refresh(r)
    return out(r)


def _grams(t: str, n: int = 3) -> set[str]:
    t = re.sub(r"[^\u4e00-\u9fff]", "", t)
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def _rank_pool(s: Session, gender: str, track: str) -> tuple[list[RankItem], float | None]:
    from app.radar.service import compute_trends, latest_snapshot, snapshot_items

    snap = latest_snapshot(s)
    items: list[RankItem] = []
    if snap is not None:
        items = [i for i in snapshot_items(s, snap.id or 0, gender=gender, dedupe=False) if track in (i.category or "") or (i.category or "") in track]
    heat = None
    try:
        heat = next((h["heat"] for h in compute_trends(s, gender) if h["category"] == track), None)
    except Exception:  # noqa: BLE001
        pass
    return items[:200], heat


def annotate(card: dict[str, Any], pool: list[RankItem], heat: float | None, banned: list[dict[str, Any]]) -> dict[str, Any]:
    text = f"{card['title']} {card['desc']}"
    g = _grams(text)
    best, best_t = 0.0, ""
    for it in pool:
        og = _grams(f"{it.title} {it.abstract[:300]}")
        if not g or not og:
            continue
        sim = len(g & og) / max(1, min(len(g), 60))
        if sim > best:
            best, best_t = sim, it.title
    hits = tropes.detect(text, banned)
    return {**card, "heat": heat, "similarity": round(min(1.0, best) * 100), "similar_to": best_t if best >= 0.15 else "",
            "trope_hits": [h.get("name") or h.get("keyword") or "" for h in hits][:3]}


def draw(sid: int, axis: str, keep: list[str], custom: str, ctx: JobContext) -> dict[str, Any]:
    if axis not in AXES:
        raise ValueError("axis 只能是 world / hero / cheat")
    with session_scope() as s:
        r = _get(s, sid)
        st = dict(r.state or {})
        prev = {c["id"]: c for c in st["cards"].get(axis) or []}
        kept = [prev[k] for k in keep if k in prev]
        pool, heat = _rank_pool(s, st["gender"], st["track"])
        banned = tropes.global_tropes(s)
    picked = "\n".join(f"- {AXES[a]}：{p['title']}——{p['desc']}" for a, p in st["picks"].items() if a != axis and p) or "（还没定）"
    n = max(1, 9 - len(kept))
    insp = st.get("inspiration") or {}
    user = render("spark_round", axis_label=AXES[axis], gender_label="男频" if st["gender"] == "male" else "女频", track=st["track"],
                  sub=st.get("sub") or "不限", tags="、".join(st.get("tags") or []) or "不限",
                  inspiration="；".join(f"{k}：{v}" for k, v in insp.items() if v) + (f"；本轮要求：{custom}" if custom else "") or "（无）",
                  hot_titles="、".join(i.title for i in pool[:8]) or "（暂无榜单数据）", picked=picked,
                  keep="、".join(k["title"] for k in kept) or "（无）", n=n, axis_rule=AXIS_RULE[axis])
    ctx.progress(20, f"抽{AXES[axis]}卡")
    raw = get_gateway().chat_json("spark_round", system_prompt("ideation"), user, temperature=1.0,
                                  meta={"axis": axis, "track": st["track"], "keep_titles": [k["title"] for k in kept]})
    items = raw.get("cards") if isinstance(raw, dict) else raw
    fresh = []
    for it in items or []:
        if not isinstance(it, dict) or not str(it.get("title") or "").strip():
            continue
        c = {"id": uuid.uuid4().hex[:8], "title": str(it["title"]).strip()[:24], "desc": str(it.get("desc") or "").strip()[:240],
             "tags": [str(t)[:8] for t in it.get("tags") or []][:4]}
        fresh.append(annotate(c, pool, heat, banned))
    cards = kept + fresh[:n]
    with session_scope() as s:
        r = _get(s, sid)
        st = dict(r.state or {})
        st["cards"] = {**st["cards"], axis: cards}
        st["keep"] = {**st["keep"], axis: [k["id"] for k in kept]}
        st["rounds"] = {**st["rounds"], axis: int(st["rounds"].get(axis) or 0) + 1}
        r.state = st
        r.updated_at = utcnow()
        s.add(r)
        s.commit()
        s.refresh(r)
        return out(r)


def pick(s: Session, sid: int, axis: str, card_id: str | None, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    if axis not in AXES:
        raise ValueError("axis 只能是 world / hero / cheat")
    r = _get(s, sid)
    st = dict(r.state or {})
    if custom and str(custom.get("title") or "").strip():
        card = {"id": "custom", "title": str(custom["title"])[:24], "desc": str(custom.get("desc") or "")[:240], "tags": []}
    elif card_id is None:
        card = None
    else:
        card = next((c for c in st["cards"].get(axis) or [] if c["id"] == card_id), None)
        if card is None:
            raise NotFound("这张卡不在当前这一轮里")
    st["picks"] = {**st["picks"], axis: card}
    r.state = st
    r.updated_at = utcnow()
    s.add(r)
    s.commit()
    s.refresh(r)
    return out(r)


def proposal(sid: int, ctx: JobContext) -> dict[str, Any]:
    from app.services.packaging import score_title

    with session_scope() as s:
        r = _get(s, sid)
        st = dict(r.state or {})
    miss = [AXES[a] for a in AXES if not st["picks"].get(a)]
    if miss:
        raise Conflict(f"还没选：{'、'.join(miss)}")
    p = st["picks"]
    insp = st.get("inspiration") or {}
    user = render("spark_proposal", gender_label="男频" if st["gender"] == "male" else "女频", track=st["track"], sub=st.get("sub") or "不限",
                  tags="、".join(st.get("tags") or []) or "不限", inspiration="；".join(f"{k}：{v}" for k, v in insp.items() if v) or "（无）",
                  world=f"{p['world']['title']}：{p['world']['desc']}", hero=f"{p['hero']['title']}：{p['hero']['desc']}",
                  cheat=f"{p['cheat']['title']}：{p['cheat']['desc']}")
    ctx.progress(20, "写立项书")
    raw = get_gateway().chat_json("spark_proposal", system_prompt("ideation"), user, meta={"picks": p, "track": st["track"]})
    if not isinstance(raw, dict):
        raise ValueError("立项书不是 JSON 对象")
    titles = [str(t).strip()[:30] for t in raw.get("titles") or [] if str(t).strip()]
    scored = sorted(({"title": t, "score": sum(score_title(t).values())} for t in dict.fromkeys(titles)), key=lambda x: -x["score"])
    from app.services.bible_ops import normalize_card

    seeds = [c for c in (normalize_card(x) for x in raw.get("seed_cards") or [] if isinstance(x, dict)) if c]
    pw = raw.get("power") if isinstance(raw.get("power"), dict) else {}
    if pw.get("name") and not any(c["type"] == "power" for c in seeds):
        seeds.append({"type": "power", "name": str(pw["name"])[:20], "summary": "力量体系", "data": {"levels": pw.get("levels") or []}, "known_by": []})
    prop = {"titles": scored[:9], "title": scored[0]["title"] if scored else p["hero"]["title"],
            **{k: str(raw.get(k) or "")[:600] for k in ("tagline", "logline", "hook", "endgame", "style", "conflict")},
            **{k: [str(x)[:120] for x in raw.get(k) or []][:8] for k in ("selling_points", "expectations", "arc")},
            "power": {"name": str(pw.get("name") or "")[:20], "levels": [str(x)[:12] for x in pw.get("levels") or []][:12]},
            "seed_cards": seeds[:12]}
    fields = ["title", "tagline", "logline", "hook", "selling_points", "expectations", "endgame", "arc", "style", "conflict", "power", "seed_cards"]
    prop["completeness"] = round(100 * sum(1 for f in fields if prop.get(f) and (prop[f] if not isinstance(prop[f], dict) else prop[f].get("name"))) / len(fields))
    with session_scope() as s:
        r = _get(s, sid)
        st = dict(r.state or {})
        st["proposal"] = prop
        r.state = st
        r.updated_at = utcnow()
        s.add(r)
        s.commit()
        s.refresh(r)
        return out(r)


def update_proposal(s: Session, sid: int, patch: dict[str, Any]) -> dict[str, Any]:
    r = _get(s, sid)
    st = dict(r.state or {})
    if not st.get("proposal"):
        raise Conflict("还没有立项书")
    prop = dict(st["proposal"])
    for k in ("title", "tagline", "logline", "hook", "endgame", "style", "conflict"):
        if isinstance(patch.get(k), str):
            prop[k] = patch[k][:600]
    for k in ("selling_points", "expectations", "arc"):
        if isinstance(patch.get(k), list):
            prop[k] = [str(x)[:120] for x in patch[k]][:8]
    if isinstance(patch.get("seed_cards"), list):
        from app.services.bible_ops import normalize_card

        prop["seed_cards"] = [c for c in (normalize_card(x) for x in patch["seed_cards"] if isinstance(x, dict)) if c][:12]
    st["proposal"] = prop
    r.state = st
    r.updated_at = utcnow()
    s.add(r)
    s.commit()
    s.refresh(r)
    return out(r)


def adopt(s: Session, sid: int) -> dict[str, Any]:
    """写成选题（Idea.source.kind = spark，带种子设定卡）；立项建书时种子卡直接进设定库。"""
    r = _get(s, sid)
    st = dict(r.state or {})
    prop = st.get("proposal")
    if not prop:
        raise Conflict("还没有立项书")
    if r.idea_id and s.get(Idea, r.idea_id):
        return {"idea_id": r.idea_id}
    idea = Idea(title=prop["title"][:40], logline=prop.get("logline") or prop.get("tagline") or "", selling_points=prop.get("selling_points") or [],
                hook=prop.get("hook") or prop.get("tagline") or "", expectations=prop.get("expectations") or [], endgame=prop.get("endgame") or "",
                arc=prop.get("arc") or [], genre=st["track"], gender=st["gender"],
                source={"kind": "spark", "session_id": sid, "picks": st["picks"], "style": prop.get("style"), "conflict": prop.get("conflict"),
                        "power": prop.get("power"), "seed_cards": prop.get("seed_cards") or [], "titles": prop.get("titles") or [],
                        "seed": {"protagonist": (st["picks"].get("hero") or {}).get("title", ""), "mechanism": (st["picks"].get("cheat") or {}).get("title", "")}})
    s.add(idea)
    s.commit()
    s.refresh(idea)
    r.idea_id = idea.id
    s.add(r)
    s.commit()
    return {"idea_id": idea.id}


def seed_cards_for_book(s: Session, book_id: int, idea: Idea) -> int:
    """立项建书时：抽卡立项带来的种子设定卡写进设定库（同名跳过）。"""
    src = idea.source if isinstance(idea.source, dict) else {}
    if src.get("kind") != "spark":
        return 0
    have = {c.name for c in s.exec(select(Card).where(Card.book_id == book_id))}
    n = 0
    for c in src.get("seed_cards") or []:
        if not isinstance(c, dict) or not c.get("name") or c["name"] in have:
            continue
        s.add(Card(book_id=book_id, type=c.get("type") or "character", name=str(c["name"])[:40], summary=str(c.get("summary") or ""),
                   data=c.get("data") or {}, known_by=c.get("known_by") or []))
        have.add(c["name"])
        n += 1
    return n


def list_sessions(s: Session) -> list[dict[str, Any]]:
    rows = list(s.exec(select(SparkSession).order_by(SparkSession.id.desc()).limit(20)))  # type: ignore[union-attr]
    return [{"id": r.id, "track": (r.state or {}).get("track"), "gender": (r.state or {}).get("gender"), "idea_id": r.idea_id,
             "title": ((r.state or {}).get("proposal") or {}).get("title"), "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows]
