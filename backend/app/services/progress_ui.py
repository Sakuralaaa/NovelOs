"""v0.9.3 作品完整度（每本书 10 项待办）与全局新手引导（四步，按实际数据自动判定）。"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, func, select

from app.db import kv_get, kv_set
from app.models.tables import Book, Card, Channel, Chapter, OutlineNode, Package
from app.services import common
from app.services.refs import soul_dict

ONBOARDING_KEY = "onboarding"
ONBOARDING_ORDER = ("model", "project", "bible_outline", "first_chapter")
ONBOARDING_LABEL = {"model": "配置模型", "project": "立项", "bible_outline": "生成设定与大纲", "first_chapter": "写第一章"}
WEIGHT = 10


def _item(key: str, label: str, done: bool, hint: str, action: dict[str, str], score: int | None = None) -> dict[str, Any]:
    return {"key": key, "label": label, "done": done, "weight": WEIGHT, "score": WEIGHT if done else (score or 0),
            "hint": "" if done else hint, "action": action}


def completeness(s: Session, book: Book) -> dict[str, Any]:
    bid = book.id or 0
    route = lambda p: {"type": "route", "target": f"/books/{bid}{p}"}  # noqa: E731
    job = lambda p: {"type": "job", "target": f"/api/books/{bid}{p}"}  # noqa: E731
    cards = common.cards(s, bid)  # 只算 active
    by_type: dict[str, list[Card]] = {}
    for c in cards:
        by_type.setdefault(c.type, []).append(c)
    chars = by_type.get("character", [])
    prot = common.protagonist(s, bid)
    nodes = common.outline_nodes(s, bid)
    ch_nodes = {n.order: n for n in nodes if n.level == "chapter"}
    ch1 = s.exec(select(Chapter).where(Chapter.book_id == bid, Chapter.number == 1)).first()
    pkg = s.get(Package, bid)
    items: list[dict[str, Any]] = []

    items.append(_item("overview", "概览与一句话卖点", bool(book.tagline.strip() and book.premise.strip()),
                       "补上一句话卖点和核心设定，后面所有生成都靠它定调", route("")))
    items.append(_item("world", "世界观", bool(by_type.get("world") or by_type.get("power")),
                       "还没有世界观或力量体系条目，可一键生成设定", job("/bible/generate")))
    if prot is None:
        items.append(_item("protagonist", "主角卡（含灵魂五维）", False, "还没有主角卡，先生成设定", job("/bible/generate")))
    else:
        sd = soul_dict(prot)
        missing = [k for k, v in sd.items() if not v]
        items.append(_item("protagonist", "主角卡（含灵魂五维）", not missing,
                           f"主角「{prot.name}」的灵魂五维还缺 {len(missing)} 项", job(f"/characters/{prot.id}/soul"),
                           score=WEIGHT // 2))
    others = [c for c in chars if prot is None or c.id != prot.id]
    items.append(_item("supporting", "配角≥2", len(others) >= 2, f"配角现在 {len(others)} 个，至少要 2 个", route("/bible")))
    items.append(_item("factions_locations", "势力/地点", bool(by_type.get("faction") or by_type.get("location")),
                       "补一个势力或地点，场景才有落脚处", route("/bible")))
    items.append(_item("outline", "大纲", any(n.level != "chapter" for n in nodes), "还没有大纲，可一键生成", job("/outline/generate")))
    plans = [k for k in (1, 2, 3) if ch_nodes.get(k) is not None and (ch_nodes[k].summary or "").strip()]
    items.append(_item("chapter_plans", "前三章章纲", len(plans) == 3, f"前三章章纲已有 {len(plans)}/3", route("/outline")))
    items.append(_item("chapter1", "第 1 章", bool(ch1 and (ch1.content or "").strip()), "第 1 章还没写", job("/chapters/write-next")))
    titled = bool(book.title.strip()) and book.title.strip() != "未命名作品"
    blurb = bool((pkg.blurb if pkg else "").strip() or book.tagline.strip())
    items.append(_item("title_blurb", "书名与简介", titled and blurb,
                       "起个正式书名" if not titled else "写一段简介", route("/package")))
    items.append(_item("cover", "封面", bool(book.cover_url or (pkg and pkg.chosen_cover)), "还没有封面", route("/package")))
    return {"book_id": bid, "score": sum(i["score"] for i in items), "items": items}


# ------------------------------------------------------------------ 新手引导

def onboarding_auto(s: Session) -> dict[str, bool]:
    model = any(c.enabled and c.models for c in s.exec(select(Channel)))
    project = bool(s.exec(select(func.count()).select_from(Book)).one())
    has_cards = {r for r in s.exec(select(Card.book_id).distinct())}
    has_nodes = {r for r in s.exec(select(OutlineNode.book_id).distinct())}
    bible_outline = bool(has_cards & has_nodes)
    first_chapter = s.exec(select(Chapter.id).where(Chapter.content != "")).first() is not None
    return {"model": bool(model), "project": project, "bible_outline": bible_outline, "first_chapter": first_chapter}


def onboarding_get(s: Session) -> dict[str, Any]:
    stored = kv_get(s, ONBOARDING_KEY, {}) or {}
    manual = {k: bool((stored.get("steps") or {}).get(k)) for k in ONBOARDING_ORDER}
    auto = onboarding_auto(s)
    steps = {k: auto[k] or manual[k] for k in ONBOARDING_ORDER}
    current = next((k for k in ONBOARDING_ORDER if not steps[k]), None)
    return {"steps": steps, "order": list(ONBOARDING_ORDER), "labels": dict(ONBOARDING_LABEL), "auto": auto,
            "current": current, "dismissed": bool(stored.get("dismissed"))}


def onboarding_put(s: Session, steps: dict[str, bool] | None, dismissed: bool | None) -> dict[str, Any]:
    stored = dict(kv_get(s, ONBOARDING_KEY, {}) or {})
    cur = {k: bool((stored.get("steps") or {}).get(k)) for k in ONBOARDING_ORDER}
    for k, v in (steps or {}).items():
        cur[k] = bool(v)
    stored["steps"] = cur
    if dismissed is not None:
        stored["dismissed"] = bool(dismissed)
    kv_set(s, ONBOARDING_KEY, stored)
    return onboarding_get(s)
