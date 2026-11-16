"""v0.9.3 @引用与角色灵魂五维的提示词片段。

- 章节计划 / 大纲概要 / 作者指令里出现「@条目名」时，把该条目完整注入提示词（名称最长优先匹配）。
- 只有 status=active 且 ref_enabled=true 的条目能被引用；弃用条目不进任何生成上下文。
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from app.models.tables import Card
from app.services import common

TYPE_LABEL = {"world": "世界观", "cheat": "金手指", "power": "力量体系", "faction": "势力", "character": "角色",
              "item": "物品", "location": "地点"}
SOUL_KEYS = ("desire", "fear", "wound", "belief", "voice")
SOUL_LABEL = {"desire": "欲望", "fear": "恐惧", "wound": "伤痕", "belief": "信念", "voice": "说话方式"}
MAX_REFS = 8
REF_BLOCK_BUDGET = 3000


def ref_cards(s: Session, book_id: int) -> list[Card]:
    return [c for c in common.cards(s, book_id) if c.ref_enabled is not False]


def brief(c: Card, n: int = 40) -> str:
    t = (c.summary or "").strip().replace("\n", " ")
    return t[:n] + ("…" if len(t) > n else "")


def list_refs(s: Session, book_id: int, q: str = "", limit: int = 20) -> list[dict[str, Any]]:
    q = (q or "").strip().lstrip("@").lower()
    order = {k: i for i, k in enumerate(TYPE_LABEL)}
    rows = [c for c in ref_cards(s, book_id) if not q or q in c.name.lower()]
    rows.sort(key=lambda c: (0 if q and c.name.lower().startswith(q) else 1, order.get(c.type, 99), c.id or 0))
    return [{"id": c.id, "name": c.name, "type": c.type, "type_label": TYPE_LABEL.get(c.type, c.type), "brief": brief(c)}
            for c in rows[: max(1, min(100, limit))]]


def find_mentions(text: str, cards: list[Card]) -> list[Card]:
    """文本里所有「@名称」命中的条目（按出现顺序去重）。同一处 @ 后能匹配多个名字时取最长的。"""
    if not text or "@" not in text and "＠" not in text:
        return []
    text = text.replace("＠", "@")
    by_len = sorted([c for c in cards if c.name], key=lambda c: -len(c.name))
    out: list[Card] = []
    seen: set[int] = set()
    i = text.find("@")
    while i >= 0:
        rest = text[i + 1:]
        for c in by_len:
            if rest.startswith(c.name):
                if (c.id or 0) not in seen:
                    seen.add(c.id or 0)
                    out.append(c)
                break
        i = text.find("@", i + 1)
    return out


def soul_dict(c: Card) -> dict[str, str]:
    return {k: str((c.soul or {}).get(k) or "").strip() for k in SOUL_KEYS}


def soul_line(c: Card, per: int = 30) -> str:
    """出场角色的简短五维（每项 ≤per 字）；没有五维返回空串。"""
    if c.type != "character":
        return ""
    sd = soul_dict(c)
    parts = [f"{SOUL_LABEL[k]}：{v[:per]}" for k, v in sd.items() if v]
    return "；".join(parts)


def card_full_text(c: Card) -> str:
    lines = [f"[{TYPE_LABEL.get(c.type, c.type)}] {c.name}：{c.summary}"]
    if c.data:
        lines.append("  详情：" + json.dumps(c.data, ensure_ascii=False)[:1200])
    sl = soul_line(c, per=120)
    if sl:
        lines.append("  灵魂五维：" + sl)
    return "\n".join(lines)


def refs_block(s: Session, book_id: int, *texts: str) -> str:
    """把文本里 @ 到的条目完整写成提示词片段；没有 @ 命中返回空串。"""
    joined = "\n".join(t for t in texts if t)
    hits = find_mentions(joined, ref_cards(s, book_id))[:MAX_REFS]
    if not hits:
        return ""
    body, used = [], 0
    for c in hits:
        t = card_full_text(c)
        if used + len(t) > REF_BLOCK_BUDGET and body:
            break
        body.append(t)
        used += len(t)
    return "【@引用设定（作者点名，写作时严格以此为准）】\n" + "\n".join(body)
