"""v0.9.3 字段级 AI 与角色灵魂五维。

都只给建议（不写库）；采纳走 apply_field（存设定快照后写入）或 PUT /api/cards/{id}。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Card, utcnow
from app.services import bible_ops, card_versions, common, tropes
from app.services.common import NotFound
from app.services.refs import SOUL_KEYS, SOUL_LABEL, TYPE_LABEL, soul_dict
from app.skills.loader import render, system_prompt

FIELD_RX = re.compile(r"^(name|summary|data\.[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]{0,40}|soul\.(desire|fear|wound|belief|voice))$")
MODES = ("fill", "rewrite", "expand")
MODE_RULE = {
    "fill": "补写：字段是空的就从零写出来；已经有内容就在保留原意的前提下补齐缺的信息。",
    "rewrite": "改写：按作者要求重写这一字段，可以换说法和细节，但不能和条目其它字段冲突。",
    "expand": "扩写：保留原有内容和说法，在后面补充更具体的细节、例子或限制，篇幅约为原来的 1.5–2 倍。",
}
FIELD_LABEL = {"name": "名称", "summary": "简介"}
SOUL_MODE_RULE = {
    "fill": "只补空着的维度；已经写了的维度原样保留，不要改动。",
    "rewrite": "五个维度全部重写；作者原有的意思能保留就保留，但要写得更具体、更能驱动情节。",
}


class FieldError(ValueError):
    """字段不合法（422）或用错了条目类型（400）。"""

    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


def check_field(card: Card, field: str) -> None:
    if not FIELD_RX.match(field or ""):
        raise FieldError("不支持的字段：只能是 name、summary、data.<键> 或 soul.<desire|fear|wound|belief|voice>")
    if field.startswith("soul.") and card.type != "character":
        raise FieldError("只有角色条目有灵魂五维", 400)


def get_card(s: Any, book_id: int, entry_id: int) -> Card:
    c = s.get(Card, entry_id)
    if c is None or c.book_id != book_id:
        raise NotFound("设定条目不存在")
    return c


def field_value(c: Card, field: str) -> Any:
    if field in ("name", "summary"):
        return getattr(c, field) or ""
    if field.startswith("data."):
        v = (c.data or {}).get(field[5:], "")
        return v if v is not None else ""
    if field.startswith("soul."):
        return soul_dict(c).get(field[5:], "")
    return ""


def field_label(field: str) -> str:
    if field.startswith("soul."):
        return "灵魂五维·" + SOUL_LABEL.get(field[5:], field[5:])
    if field.startswith("data."):
        return field[5:]
    return FIELD_LABEL.get(field, field)


def _card_json(c: Card) -> str:
    d = {"type": c.type, "type_label": TYPE_LABEL.get(c.type, c.type), "name": c.name, "summary": c.summary, "data": c.data or {}}
    if c.type == "character":
        d["soul"] = soul_dict(c)
    return json.dumps(d, ensure_ascii=False)


def _others(s: Any, book_id: int, exclude: int, only: str | None = None) -> str:
    rows = [c for c in common.cards(s, book_id, only) if c.id != exclude]
    return "\n".join(f"[{TYPE_LABEL.get(c.type, c.type)}] {c.name}：{(c.summary or '')[:60]}" for c in rows[:40]) or "（无）"


def field_ai(book_id: int, entry_id: int, field: str, instruction: str, mode: str, route: str | None,
             ctx: JobContext) -> dict[str, Any]:
    if mode not in MODES:
        raise FieldError("mode 只能是 fill / rewrite / expand")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        c = get_card(s, book_id, entry_id)
        check_field(c, field)
        before = field_value(c, field)
        meta = {**common.kit_meta(s, book), "field": field, "current": before, "mode": mode, "instruction": instruction,
                "card_name": c.name, "card_type": c.type}
        tl = tropes.tropes_for(s, book)
        user = render("field_ai", book_context=common.book_context(s, book, with_cards=False), others=_others(s, book_id, entry_id),
                      card=_card_json(c), field=field, field_label=field_label(field),
                      before=(json.dumps(before, ensure_ascii=False) if isinstance(before, (list, dict)) else str(before)) or "（空）",
                      mode_rule=MODE_RULE[mode], instruction=(instruction or "").strip() or "无",
                      value_shape='["…","…"]' if isinstance(before, list) else '"…"')
        user += tropes.prompt_block(tl, instruction)
    ctx.progress(30, f"AI {field_label(field)}")
    out = get_gateway().chat_json("field_ai", system_prompt("field_ai"), user, meta=meta, route=route)
    v = out.get("value") if isinstance(out, dict) else out
    if isinstance(before, list):
        v = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x or "").strip()]
    elif isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    else:
        v = str(v or "").strip()
    if field == "name" and isinstance(v, str):
        v = v.strip("《》「」")[:40]
    if v in ("", []):
        raise ValueError("模型没有给出内容")
    note = str(out.get("note") or "")[:60] if isinstance(out, dict) else ""
    return {"entry_id": entry_id, "field": field, "mode": mode, "before": before, "value": v, "note": note}


def apply_field(book_id: int, entry_id: int, field: str, value: Any) -> Card:
    with session_scope() as s:
        c = get_card(s, book_id, entry_id)
        check_field(c, field)
        if c.locked:
            raise FieldError(card_versions.LOCKED_MSG, 409)
        bible_ops.snapshot(s, book_id, f"采纳 AI：{c.name}·{field_label(field)}")
        card_versions.push(c, f"采纳 AI：{field_label(field)}")
        if field == "name":
            name = str(value or "").strip()[:40]
            if not name:
                raise FieldError("名称不能为空", 400)
            c.name = name
        elif field == "summary":
            c.summary = str(value or "")
        elif field.startswith("data."):
            d = dict(c.data or {})
            d[field[5:]] = [str(x) for x in value] if isinstance(value, list) else value
            c.data = d
        else:
            sd = soul_dict(c)
            sd[field[5:]] = str(value or "").strip()
            c.soul = sd if any(sd.values()) else None
        c.updated_at = utcnow()
        s.add(c)
        s.commit()
        s.refresh(c)
        return c


def soul_job(book_id: int, entry_id: int, mode: str, instruction: str, route: str | None, ctx: JobContext) -> dict[str, Any]:
    if mode not in SOUL_MODE_RULE:
        raise FieldError("mode 只能是 fill / rewrite")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        c = get_card(s, book_id, entry_id)
        if c.type != "character":
            raise FieldError("只有角色条目有灵魂五维", 400)
        before = soul_dict(c)
        meta = {**common.kit_meta(s, book), "card_name": c.name, "before": before, "mode": mode, "instruction": instruction,
                "card_data": dict(c.data or {}), "card_summary": c.summary}
        user = render("character_soul", book_context=common.book_context(s, book, with_cards=False),
                      others=_others(s, book_id, entry_id, "character"), card=_card_json(c),
                      before=json.dumps(before, ensure_ascii=False), mode_rule=SOUL_MODE_RULE[mode],
                      instruction=(instruction or "").strip() or "无")
    ctx.progress(30, f"补全「{c.name}」的灵魂五维")
    out = get_gateway().chat_json("character_soul", system_prompt("character_soul"), user, meta=meta, route=route)
    raw = out.get("soul") if isinstance(out, dict) and isinstance(out.get("soul"), dict) else (out if isinstance(out, dict) else {})
    soul: dict[str, str] = {}
    for k in SOUL_KEYS:
        nv = str(raw.get(k) or "").strip()[:300]
        soul[k] = before[k] if (mode == "fill" and before[k]) else (nv or before[k])
    if soul == before and mode == "fill" and all(before.values()):
        note = "五维已经全部写好，fill 模式没有改动"
    else:
        note = str(out.get("note") or "")[:60] if isinstance(out, dict) else ""
    if not any(soul.values()):
        raise ValueError("模型没有给出五维")
    return {"entry_id": entry_id, "mode": mode, "before": before, "soul": soul, "note": note}
