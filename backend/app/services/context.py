"""Context Pack：固定前缀（规则 + 书设定 + 风格卡）在前，动态后缀（相关卡片、事实、最近摘要、伏笔、细纲）在后。

相关性筛选（借鉴 Hurricane0698/novelwriter 的思路，自写实现）：
只注入当前章细纲/场景节拍点名的人物、地点、物品等卡片与其当前事实，以及与这些实体相关的未回收伏笔，
而不是把整个设定库塞进上下文。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from app.models.tables import Book, Card, Fact, OutlineNode
from app.services import common
from app.skills.loader import system_prompt

RECENT_SUMMARIES = 3
MAX_FORESHADOWS = 6


@dataclass
class ContextPack:
    prefix: str
    suffix: str
    relevant_cards: list[Card] = field(default_factory=list)
    voices: dict[str, dict[str, Any]] = field(default_factory=dict)
    protagonist: str | None = None
    required_chars: list[str] = field(default_factory=list)
    all_names: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"cards": [c.name for c in self.relevant_cards], "prefix_chars": len(self.prefix), "suffix_chars": len(self.suffix)}


def style_block(s: Session, book_id: int) -> str:
    st = common.get_style(s, book_id)
    lines: list[str] = []
    lines.append(f"叙述人称：{'第一人称' if st.pov == 'first' else '第三人称限知'}")
    if st.tone:
        lines.append(f"基调：{st.tone}")
    if st.voice_notes:
        lines.append(f"作者的写法要求：{st.voice_notes}")
    ex = st.extracted or {}
    if ex:
        llm = ex.get("llm") or {}
        stats = ex.get("stats") or {}
        if stats:
            lines.append(
                f"范文统计：平均句长 {stats.get('avg_sentence_len')} 字，≤8 字短句占 {stats.get('short_sentence_ratio')}，"
                f"对话占比 {stats.get('dialogue_ratio')}，描写词每千字 {stats.get('descriptor_per_k')}。"
            )
        if llm.get("summary"):
            lines.append(f"范文写法：{llm['summary']}")
        for t in (llm.get("techniques") or [])[:8]:
            lines.append(f"- {t}")
        if ex.get("excerpt"):
            lines.append("范文片段（只学写法：句长节奏、对白配动作的方式、描写密度；不要照搬情节、人名、设定）：")
            lines.append("<<<\n" + str(ex["excerpt"]) + "\n>>>")
    return "【风格卡】\n" + "\n".join(lines)


def _plan_text(beats: dict[str, Any]) -> str:
    return json.dumps(beats, ensure_ascii=False)


def relevant_cards(all_cards: list[Card], beats: dict[str, Any], protagonist: Card | None) -> list[Card]:
    text = _plan_text(beats)
    named = set(beats.get("characters") or [])
    for sc in beats.get("scenes") or []:
        named.update(sc.get("characters") or [])
    if beats.get("location"):
        named.add(str(beats["location"]))
    out: list[Card] = []
    for c in all_cards:
        if c.type in ("world",):
            continue  # world 在固定前缀
        if (protagonist and c.id == protagonist.id) or c.name in named or c.name in text:
            out.append(c)
    return out


def build_context_pack(s: Session, book: Book, node: OutlineNode) -> ContextPack:
    bid = book.id or 0
    beats = node.beats or {}
    all_cards = common.cards(s, bid)
    prot = common.protagonist(s, bid)

    # ---------- 固定前缀：规则 + 书设定 + 风格 ----------
    fixed = [f"【本书】\n{common.book_context(s, book, with_cards=False)}"]
    for c in all_cards:
        if c.type in ("world", "power"):
            extra = ""
            if c.type == "power" and c.data:
                d = c.data
                extra = f"（用法：{d.get('input', '')}；代价：{d.get('cost', '')}；限制：{d.get('limit', '')}）"
            fixed.append(f"[{c.type}] {c.name}：{c.summary}{extra}")
    fixed.append(style_block(s, bid))
    prefix = system_prompt("writing_scene", "\n".join(fixed))

    # ---------- 动态后缀 ----------
    rel = relevant_cards(all_cards, beats, prot)
    rel_ids = {c.id for c in rel}
    rel_names = {c.name for c in rel}
    parts: list[str] = ["【本章相关设定】"]
    voices: dict[str, dict[str, Any]] = {}
    for c in rel:
        line = f"[{c.type}] {c.name}：{c.summary}"
        if c.type == "character":
            v = common.voice_of(c)
            voices[c.name] = v
            line += (
                f"\n  说话方式：{v['voice'] or '未设定'}；口头禅：{'、'.join(v['catchphrases']) or '无'}；"
                f"小动作：{'、'.join(v['habits']) or '无'}；神态：{v['demeanor'] or '未设定'}"
            )
            d = c.data or {}
            if d.get("knows") or d.get("unknown") or d.get("misbelief"):
                line += f"\n  此刻知道：{d.get('knows', [])}；不知道：{d.get('unknown', [])}；误解：{d.get('misbelief', [])}"
        elif c.type == "location" and (c.data or {}).get("sensory"):
            line += f"\n  感官：{c.data['sensory']}"  # type: ignore[index]
        parts.append(line)
    facts = list(
        s.exec(select(Fact).where(Fact.book_id == bid, Fact.to_chapter == None))  # noqa: E711
    )
    fact_lines = []
    for f in facts:
        if f.entity_id in rel_ids:
            name = next((c.name for c in rel if c.id == f.entity_id), "")
            tag = "（作者真相，读者与其他角色未必知道）" if f.visibility == "author" else ""
            fact_lines.append(f"- {name}·{f.key}：{f.value}{tag}")
    if fact_lines:
        parts.append("【当前事实】\n" + "\n".join(fact_lines))

    recent = common.committed_chapters(s, bid, before=node.order)[-RECENT_SUMMARIES:]
    if recent:
        parts.append("【最近章节摘要】\n" + "\n".join(f"第{c.number}章 {c.title}：{c.summary}" for c in recent))

    opens = common.open_foreshadows(s, bid)
    planned_descs = [str(f.get("desc", "")) for f in beats.get("foreshadow") or []]
    picked = [
        f for f in opens
        if any(n in f.desc for n in rel_names) or any(d and (d in f.desc or f.desc in d) for d in planned_descs)
    ]
    for f in opens:  # 最老的几条也带上，防止长线伏笔被遗忘
        if len(picked) >= MAX_FORESHADOWS:
            break
        if f not in picked and len(picked) < 2:
            picked.append(f)
    if picked:
        parts.append("【未回收伏笔（相关）】\n" + "\n".join(f"- #{f.id} {f.desc}（第{f.planted_ch}章埋，状态 {f.status}）" for f in picked[:MAX_FORESHADOWS]))

    required = [c for c in (beats.get("characters") or []) if isinstance(c, str)]
    return ContextPack(
        prefix=prefix,
        suffix="\n\n".join(parts),
        relevant_cards=rel,
        voices=voices,
        protagonist=prot.name if prot else None,
        required_chars=required,
        all_names=[c.name for c in all_cards],
    )
