"""Context Pack：固定前缀（规则 + 书设定 + 风格卡）在前，动态后缀（相关卡片、事实、最近摘要、伏笔、细纲）在后。

相关性筛选（借鉴 Hurricane0698/novelwriter 的思路，自写实现）：
只注入当前章细纲/场景节拍点名的人物、地点、物品等卡片与其当前事实，以及与这些实体相关的未回收伏笔，
而不是把整个设定库塞进上下文。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from app.models.tables import Book, Card, Fact, OutlineNode
from app.services import common
from app.services.outline import (
    FORESHADOW_ALERT_AGE, FORESHADOW_WARN_AGE, chapter_beats_list, foreshadow_age_label, rhythm_ledger,
)
from app.skills.loader import system_prompt

RECENT_SUMMARIES = 3
MAX_FORESHADOWS = 6
MAX_RELATED_OLD = 3          # 回读推荐：与本章实体/伏笔相关的更早章节摘要条数
OLDER_INDEX_CHARS = 600      # 更早章节“一句话索引”的总字数预算（长篇记忆压缩）
PREV_TAIL_CHARS = 300        # 上一章结尾原文，保证章与章之间动作、位置、情绪的衔接
MAX_GLOBAL_FACTS = 8

# 人物状态里优先展示、并在写前核对的键（变更声明推荐使用这些键名）
STATE_KEY_ORDER = ("位置", "处境", "身体", "伤势", "境界", "实力", "持有物品", "情绪", "目标", "已知信息", "关系", "身份", "生死")
DEAD_RX = re.compile(r"(已死|死亡|身亡|阵亡|毙命|被杀|去世|殒命)")
DEAD_KEY_RX = re.compile(r"(生死|状态|存活|身体|处境)")

# 黄金三章：入局 → 加压 → 承诺（参考 maliangwriter.com 黄金三章检查、番茄开篇硬指标；文字自写）
GOLDEN_TASKS = {
    1: "【黄金三章·第1章：入局】前 300 字内让主角在做事并撞上一个具体异常或危险；只交代当下行动需要的设定；"
       "章末钩子要让读者问“他接下来怎么办”。",
    2: "【黄金三章·第2章：加压】阻力升级，规则露出：金手指第一次使用时写清怎么用、付出什么、哪里用不了；"
       "主角必须主动做一次选择，不要重复第1章的惊讶。",
    3: "【黄金三章·第3章：承诺】给出第一次小胜并结算收益（资源、认可、资格至少一项），同时把短期冲突接到长期目标上；"
       "章末钩子比前两章更贴近主角本人。",
}


@dataclass
class ContextPack:
    prefix: str
    suffix: str
    relevant_cards: list[Card] = field(default_factory=list)
    voices: dict[str, dict[str, Any]] = field(default_factory=dict)
    protagonist: str | None = None
    required_chars: list[str] = field(default_factory=list)
    all_names: list[str] = field(default_factory=list)
    state_text: str = ""  # 人物当前状态 + 上一章结尾，供审稿核对连贯性
    preflight: list[str] = field(default_factory=list)  # 写前核对发现的问题

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
    state_text = state_block(facts, rel, all_cards)
    if state_text:
        parts.append(state_text)

    committed = common.committed_chapters(s, bid, before=node.order)
    recent = committed[-RECENT_SUMMARIES:]
    older = committed[:-RECENT_SUMMARIES] if len(committed) > RECENT_SUMMARIES else []
    planned_descs = [str(f.get("desc", "")) for f in beats.get("foreshadow") or []]
    if older:
        related = related_old_chapters(older, rel_names, planned_descs)
        if related:
            parts.append("【相关旧章回读】\n" + "\n".join(f"第{c.number}章 {c.title}：{c.summary}" for c in related))
        idx = older_index(older, exclude={c.id for c in related})
        if idx:
            parts.append("【更早章节索引（压缩）】\n" + idx)
    if recent:
        parts.append("【最近章节摘要】\n" + "\n".join(f"第{c.number}章 {c.title}：{c.summary}" for c in recent))
    tail = ""
    if committed and committed[-1].number == node.order - 1 and committed[-1].content:
        tail = chapter_tail(committed[-1].content)
        parts.append(f"【上一章结尾原文（本章第一个场景从这里接，位置、时间、情绪要连上）】\n{tail}")

    opens = common.open_foreshadows(s, bid)
    picked = pick_foreshadows(opens, rel_names, planned_descs, node.order)
    if picked:
        parts.append("【未回收伏笔（相关）】\n" + "\n".join(
            f"- #{f.id} {f.desc}（第{f.planted_ch}章埋，状态 {f.status}，{foreshadow_age_label(f, node.order)}）" for f in picked))

    plan_lines = chapter_task_lines(beats, node.order)
    ledger = rhythm_ledger(chapter_beats_list(s, bid), node.order, 5)
    if ledger:
        plan_lines.append("最近几章的节奏（本章不要重复同一种爽点模式和钩子类型）：\n" + ledger)
    if plan_lines:
        parts.append("【本章写作任务】\n" + "\n".join(plan_lines))

    pre = preflight_check(beats, all_cards, facts, opens, node.order)
    if pre:
        parts.append("【写前核对（程序发现，写作时按这里处理）】\n" + "\n".join(f"- {x}" for x in pre))

    required = [c for c in (beats.get("characters") or []) if isinstance(c, str)]
    return ContextPack(
        prefix=prefix,
        suffix="\n\n".join(parts),
        relevant_cards=rel,
        voices=voices,
        protagonist=prot.name if prot else None,
        required_chars=required,
        all_names=[c.name for c in all_cards],
        state_text="\n\n".join(x for x in (state_text, f"【上一章结尾】\n{tail}" if tail else "") if x),
        preflight=pre,
    )


# ------------------------------------------------------------------ 状态 / 记忆 / 伏笔 / 写前核对

def chapter_tail(content: str, budget: int = PREV_TAIL_CHARS) -> str:
    """上一章结尾：从末尾按整段往前取，总长不超过 budget（至少一段，过长的单段截取末尾）。"""
    paras = [p.strip() for p in content.split("\n") if p.strip()]
    out: list[str] = []
    used = 0
    for p in reversed(paras):
        if out and used + len(p) > budget:
            break
        out.append(p if len(p) <= budget else "…" + p[-budget:])
        used += len(p)
    return "\n".join(reversed(out))


def _key_rank(key: str) -> int:
    for i, k in enumerate(STATE_KEY_ORDER):
        if key.startswith(k) or k in key:
            return i
    return len(STATE_KEY_ORDER)


def state_block(facts: list[Fact], rel: list[Card], all_cards: list[Card]) -> str:
    """按实体分组的“当前状态”快照（只含相关实体 + 全书级事实），关键键在前。"""
    rel_by_id = {c.id: c for c in rel}
    by_ent: dict[int, list[Fact]] = {}
    global_facts: list[Fact] = []
    for f in facts:
        if f.entity_id is None:
            global_facts.append(f)
        elif f.entity_id in rel_by_id:
            by_ent.setdefault(f.entity_id, []).append(f)
    lines: list[str] = []
    for eid, fs in by_ent.items():
        fs.sort(key=lambda f: (_key_rank(f.key), -f.from_chapter))
        bits = []
        for f in fs:
            tag = "（作者真相，读者与其他角色未必知道）" if f.visibility == "author" else ""
            since = f"[第{f.from_chapter}章起]" if f.from_chapter else ""
            bits.append(f"{f.key}：{f.value}{since}{tag}")
        lines.append(f"- {rel_by_id[eid].name}｜" + "；".join(bits))
    if global_facts:
        global_facts.sort(key=lambda f: -f.from_chapter)
        for f in global_facts[:MAX_GLOBAL_FACTS]:
            tag = "（作者真相）" if f.visibility == "author" else ""
            lines.append(f"- 全书·{f.key}：{f.value}{tag}")
    if not lines:
        return ""
    return "【人物与世界当前状态（以此为准，正文不得与之矛盾；变化要在变更声明里登记）】\n" + "\n".join(lines)


def related_old_chapters(older: list[Any], names: set[str], planned_descs: list[str]) -> list[Any]:
    """回读推荐：更早章节中摘要提到本章相关实体或本章要推进/回收的伏笔的，取最相关的几章。"""
    scored = []
    keys = [d[:6] for d in planned_descs if len(d) >= 4]
    for c in older:
        summ = c.summary or ""
        score = sum(2 for k in keys if k and k in summ) + sum(1 for n in names if n and n in summ)
        if score:
            scored.append((score, c.number, c))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return sorted([c for _, _, c in scored[:MAX_RELATED_OLD]], key=lambda c: c.number)


def older_index(older: list[Any], exclude: set[Any] | None = None, budget: int = OLDER_INDEX_CHARS) -> str:
    """更早章节的一句话索引：每章只取摘要第一句；从近到远填满预算，超出部分按间隔抽样，保证长书上下文不膨胀。"""
    exclude = exclude or set()
    items = [c for c in older if c.id not in exclude and c.summary]
    if not items:
        return ""
    def first(c: Any) -> str:
        m = re.match(r"[^。！？]*[。！？]?", c.summary.strip())
        return (m.group(0) if m else c.summary)[:60]
    lines: list[str] = []
    used = 0
    step = 1
    i = len(items) - 1
    while i >= 0:
        line = f"第{items[i].number}章：{first(items[i])}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
        if len(lines) >= 10:
            step = 3  # 更远的章节抽样
        i -= step
    return "\n".join(reversed(lines))


def pick_foreshadows(opens: list[Any], rel_names: set[str], planned_descs: list[str], current: int) -> list[Any]:
    """本章细纲点名的伏笔优先，其次与相关实体有关的，再补超期最久的（防止长线伏笔被遗忘）。"""
    planned = [f for f in opens if any(d and (d in f.desc or f.desc in d) for d in planned_descs)]
    related = [f for f in opens if f not in planned and any(n in f.desc for n in rel_names)]
    stale = sorted([f for f in opens if f not in planned and f not in related],
                   key=lambda f: int(f.last_ch or f.planted_ch or 0))
    out = planned + related
    for f in stale:
        if len(out) >= MAX_FORESHADOWS:
            break
        age = current - int(f.last_ch or f.planted_ch or 0)
        if age > FORESHADOW_WARN_AGE or len(out) < 2:
            out.append(f)
    return out[:MAX_FORESHADOWS]


_PAYOFF_SHAPE = {
    "打脸": "铺垫轻视 → 主角亮实力 → 对方震惊/后悔 → 实质收获",
    "扮猪吃虎": "表面示弱 → 对手得意 → 关键时刻爆发 → 众人反应",
    "越级反杀": "差距写具体 → 付出代价逆转 → 敌人不可置信",
    "打脸权威": "权威质疑 → 用结果证明 → 权威认可或尴尬",
    "反派翻车": "反派得意 → 计划破产 → 反派狼狈",
    "甜蜜超预期": "平淡日常 → 意外的心意 → 关系升温",
    "真相揭示": "旧细节 → 新解释 → 读者恍然、角色处境改变",
    "收获升级": "目标 → 付出 → 得到 → 让人看见变化",
    "危机化解": "危机压到眼前 → 主角用已铺垫的手段破局 → 余波",
    "关系突破": "误会或距离 → 一个具体举动 → 关系变化被双方确认",
}


def chapter_task_lines(beats: dict[str, Any], number: int) -> list[str]:
    lines: list[str] = []
    if number in GOLDEN_TASKS:
        lines.append(GOLDEN_TASKS[number])
    pt = beats.get("payoff_type")
    if pt or beats.get("payoff"):
        shape = _PAYOFF_SHAPE.get(str(pt), "")
        lines.append(
            f"爽点：{beats.get('payoff') or pt}"
            + (f"（{pt}：{shape}）" if shape else "")
            + "。按“期待 → 压抑 → 释放”写：先让读者想要，再写清阻力和代价，释放的分量配得上压抑的长度，释放后给围观反应或实际收获。"
        )
    if beats.get("expectation"):
        lines.append(f"读者期待：{beats['expectation']}（本章要么推进它，要么兑现它，不能让它静止）")
    if beats.get("info_gap"):
        lines.append(f"信息差：{beats['info_gap']}（读者知道、角色不知道，用它蓄爽感，不要让角色提前知道）")
    if beats.get("hook_end"):
        ht = beats.get("hook_type")
        lines.append(f"章末钩子：{beats['hook_end']}" + (f"（类型：{ht}）" if ht else "") + "。断在变化发生的那一刻，不写总结句。")
    if beats.get("time"):
        lines.append(f"故事时间：{beats['time']}")
    for a in beats.get("must_avoid") or []:
        lines.append(f"本章避免：{a}")
    return lines


def preflight_check(beats: dict[str, Any], all_cards: list[Card], facts: list[Fact], opens: list[Any], number: int) -> list[str]:
    """写前一致性核对（纯代码）：细纲点名的人物/地点是否登记、是否已死亡、要推进的伏笔是否还开着、超期伏笔。"""
    issues: list[str] = []
    names = {c.name: c for c in all_cards}
    for ch in beats.get("characters") or []:
        if not isinstance(ch, str) or not ch:
            continue
        card = names.get(ch)
        if card is None:
            issues.append(f"细纲人物「{ch}」不在设定库里：若是新人物，正文里交代身份并在变更声明 new_entities 中登记")
            continue
        for f in facts:
            if f.entity_id == card.id and DEAD_KEY_RX.search(f.key) and DEAD_RX.search(f.value):
                issues.append(f"「{ch}」在第{f.from_chapter}章已登记为「{f.value}」，本章却要求出场：只能以回忆、尸体、遗物或假死揭晓的方式出现")
                break
    loc = str(beats.get("location") or "")
    if loc and loc not in names and len(loc) <= 12:
        issues.append(f"地点「{loc}」不在设定库里：第一次出现时写清它的样子与气味，并登记为 location")
    open_descs = {f.id: f.desc for f in opens}
    for f in beats.get("foreshadow") or []:
        if f.get("action") in ("advance", "resolve"):
            fid, desc = f.get("id"), str(f.get("desc", ""))
            ok = (fid in open_descs) or any(desc and (desc in d or d in desc) for d in open_descs.values())
            if not ok:
                issues.append(f"细纲要{ '回收' if f['action'] == 'resolve' else '推进' }的伏笔「{desc}」在伏笔池里找不到（可能已回收或从未埋下），写之前确认")
    for f in opens:
        age = number - int(f.last_ch or f.planted_ch or 0)
        if age > FORESHADOW_ALERT_AGE:
            issues.append(f"伏笔 #{f.id}「{f.desc}」已 {age} 章没动静：本章哪怕一句话也给它一个新线索")
    return issues
