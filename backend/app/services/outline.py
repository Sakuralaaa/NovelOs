"""大纲：总纲 → 卷 → 弧 → 章细纲，滚动展开。chapter 级节点的 order 即全书章号。"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, func, select

from app.services.research import research_notes
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Book, OutlineNode, utcnow
from app.services import common
from app.services.common import Conflict, NotFound
from app.skills.loader import render, system_prompt

OUTCOMES = ("yes", "no", "yes-but", "no-and")
CHAPTERS_PER_ARC = 5

# ---- 节奏字段（均为可选；旧细纲没有这些键时按“未标注”处理，不影响写作）----
# 爽点执行模式（思路参考 lingfengQAQ/webnovel-writer cool-points-guide，GPL-3.0，仅借思路，文字自写）
PAYOFF_TYPES = ("打脸", "扮猪吃虎", "越级反杀", "打脸权威", "反派翻车", "甜蜜超预期", "真相揭示", "收获升级", "危机化解", "关系突破")
# 爽点强度：small 小爽点 / combo 组合爽点（两种模式叠加）/ milestone 里程碑（改变主角地位）
PAYOFF_LEVELS = ("small", "combo", "milestone")
# 章末钩子类型（危机突降/悬念反转/挑衅叫板/倒计时 + 信息缺口/选择悬置/后果预示 + 决定/发现/误判/代价）
HOOK_TYPES = ("危机突降", "悬念反转", "挑衅叫板", "倒计时", "信息缺口", "选择悬置", "后果预示", "决定", "发现", "误判", "代价")
# 叙事线：quest 主线 / fire 感情与人物关系线 / constellation 世界观与势力扩展（Strand Weave 思路，XuanRanL/webnovelwriter，GPL-3.0，仅借思路）
STRANDS = ("quest", "fire", "constellation")
EMOTIONS = ("up", "down", "flat")  # 本章读者情绪走向：扬 / 压 / 平
FORESHADOW_TIERS = ("short", "mid", "long")  # 伏笔层级：10 章内 / 30 章内 / 50 章以上回收

# 节奏红线（经验值，未校准）
MAX_SAME_PAYOFF_RUN = 2      # 同一爽点模式连续超过 2 章 → 审美疲劳
MAX_SAME_HOOK_RUN = 2        # 同一钩子类型连续超过 2 章 → 套路感
MAX_YES_RUN = 2              # 章结果连续 yes 超过 2 章 → 节奏塌陷
MAX_SAME_EMOTION_RUN = 2     # 情绪同方向连续超过 2 章（novel-ops：连续 3 章同方向强制调整）
MAX_QUEST_RUN = 5            # 主线连续不超过 5 章
MAX_FIRE_GAP = 10            # 感情/关系线断档不超过 10 章
MAX_CONSTELLATION_GAP = 15   # 世界观扩展断档不超过 15 章
COMBO_WINDOW = 5             # 每 5 章至少 1 个组合爽点
MILESTONE_WINDOW = 15        # 每 15 章至少 1 个里程碑爽点
FORESHADOW_WARN_AGE = 20     # 伏笔超过 20 章无推进标黄（novel-ops）
FORESHADOW_ALERT_AGE = 40    # 超过 40 章标红


def _pick(v: Any, allowed: tuple[str, ...]) -> str:
    v = str(v or "").strip()
    if v in allowed:
        return v
    for a in allowed:  # 容忍“打脸（当众）”“quest主线”这类带注释的写法
        if a and a in v:
            return a
    return ""


def _strands(v: Any) -> list[str]:
    items = v if isinstance(v, list) else [v] if v else []
    out: list[str] = []
    for it in items:
        k = _pick(str(it).lower(), STRANDS)
        if k and k not in out:
            out.append(k)
    return out


CHAPTER_SCHEMA = (
    '{"chapters":[{"title":"","goal":"本章戏剧问题","conflict":"","outcome":"yes|no|yes-but|no-and","payoff":"",'
    '"payoff_type":"打脸|扮猪吃虎|越级反杀|打脸权威|反派翻车|甜蜜超预期|真相揭示|收获升级|危机化解|关系突破",'
    '"payoff_level":"small|combo|milestone","strand":["quest|fire|constellation"],"emotion":"up|down|flat",'
    '"expectation":"本章挂起或兑现的读者期待","info_gap":"读者知道而角色不知道的事（可空）","time":"本章故事内时间",'
    '"characters":[],"location":"","foreshadow":[{"action":"plant|advance|resolve","id":null,"desc":"","tier":"short|mid|long"}],'
    '"hook_end":"","hook_type":"危机突降|悬念反转|挑衅叫板|倒计时|信息缺口|选择悬置|后果预示|决定|发现|误判|代价","must_avoid":[]}]}'
)


def normalize_beats(raw: dict[str, Any], number: int, chapter_words: int) -> dict[str, Any]:
    fs = []
    for f in raw.get("foreshadow") or []:
        if isinstance(f, dict) and f.get("action") in ("plant", "advance", "resolve"):
            fid = f.get("id")
            item: dict[str, Any] = {"action": f["action"], "id": fid if isinstance(fid, int) else None, "desc": str(f.get("desc", ""))}
            tier = _pick(f.get("tier"), FORESHADOW_TIERS)
            if f["action"] == "plant" and tier:
                item["tier"] = tier
            fs.append(item)
    outcome = raw.get("outcome") if raw.get("outcome") in OUTCOMES else "yes-but"
    chars = [str(c) for c in (raw.get("characters") or []) if c]
    out: dict[str, Any] = {
        "number": number,
        "title": str(raw.get("title") or f"第{number}章"),
        "goal": str(raw.get("goal", "")),
        "conflict": str(raw.get("conflict", "")),
        "outcome": outcome,
        "payoff": str(raw.get("payoff", "")),
        "characters": chars,
        "location": str(raw.get("location", "")),
        "foreshadow": fs,
        "hook_end": str(raw.get("hook_end", "")),
        "words": int(raw.get("words") or chapter_words),
    }
    # 可选的节奏字段：只在模型给了合法值时写入，保持旧数据与前端键值编辑兼容
    optional = {
        "payoff_type": _pick(raw.get("payoff_type"), PAYOFF_TYPES),
        "payoff_level": _pick(str(raw.get("payoff_level") or "").lower(), PAYOFF_LEVELS),
        "hook_type": _pick(raw.get("hook_type"), HOOK_TYPES),
        "emotion": _pick(str(raw.get("emotion") or "").lower(), EMOTIONS),
    }
    for k, v in optional.items():
        if v:
            out[k] = v
    st = _strands(raw.get("strand") or raw.get("strands"))
    if st:
        out["strand"] = st
    for k in ("expectation", "info_gap", "time"):
        if raw.get(k):
            out[k] = str(raw[k])[:200]
    avoid = raw.get("must_avoid")
    if isinstance(avoid, list) and avoid:
        out["must_avoid"] = [str(x)[:80] for x in avoid if x][:5]
    elif isinstance(avoid, str) and avoid.strip():
        out["must_avoid"] = [avoid.strip()[:80]]
    return out


# ------------------------------------------------------------------ 节奏审计（纯代码）

def _runs(values: list[tuple[int, str]]) -> list[tuple[str, int, int]]:
    """把（章号, 值）序列压成连续段：(值, 起始章, 结束章)。空值打断连续。"""
    out: list[tuple[str, int, int]] = []
    for n, v in values:
        if out and v and out[-1][0] == v and out[-1][2] == n - 1:
            out[-1] = (v, out[-1][1], n)
        elif v:
            out.append((v, n, n))
    return out


def pacing_audit(chapters: list[dict[str, Any]], open_foreshadows: list[Any] | None = None,
                 current: int | None = None) -> list[str]:
    """对一段按章号排序的章细纲做节奏体检，返回问题清单（中文，可直接喂给规划提示词）。

    只检查模型标注过的字段；未标注的章节不参与对应检查。阈值为经验值，未校准。
    """
    chs = sorted([c for c in chapters if isinstance(c, dict) and c.get("number")], key=lambda c: int(c["number"]))
    issues: list[str] = []
    if not chs:
        return issues
    seq = lambda key: [(int(c["number"]), str(c.get(key) or "")) for c in chs]  # noqa: E731
    for v, a, b in _runs(seq("payoff_type")):
        if b - a + 1 > MAX_SAME_PAYOFF_RUN:
            issues.append(f"第{a}–{b}章连续 {b - a + 1} 章都是「{v}」式爽点，读者会疲劳，换一种模式或穿插感情线/世界观章")
    for v, a, b in _runs(seq("hook_type")):
        if b - a + 1 > MAX_SAME_HOOK_RUN:
            issues.append(f"第{a}–{b}章连续 {b - a + 1} 章用「{v}」式章末钩子，换一种钩子类型")
    for v, a, b in _runs([(n, o if o == "yes" else "") for n, o in seq("outcome")]):
        if b - a + 1 > MAX_YES_RUN:
            issues.append(f"第{a}–{b}章连续 {b - a + 1} 章结果都是 yes，主角太顺，至少一章改成 yes-but 或 no-and")
    for v, a, b in _runs(seq("emotion")):
        if v in ("up", "down") and b - a + 1 > MAX_SAME_EMOTION_RUN:
            label = "扬" if v == "up" else "压"
            issues.append(f"第{a}–{b}章情绪连续 {b - a + 1} 章都在「{label}」，需要一章反向调节")
    tagged = [c for c in chs if c.get("strand")]
    if len(tagged) >= 3:
        quest_only = [(int(c["number"]), "q" if c.get("strand") == ["quest"] else "") for c in tagged]
        for _, a, b in _runs(quest_only):
            if b - a + 1 > MAX_QUEST_RUN:
                issues.append(f"第{a}–{b}章连续 {b - a + 1} 章只走主线，穿插一章感情/人物关系或世界观扩展")
        last = int(chs[-1]["number"])
        for strand, gap, label in (("fire", MAX_FIRE_GAP, "感情/人物关系线"), ("constellation", MAX_CONSTELLATION_GAP, "世界观/势力扩展")):
            hits = [int(c["number"]) for c in tagged if strand in (c.get("strand") or [])]
            first = int(tagged[0]["number"])
            prev = hits[-1] if hits else first - 1
            if last - prev > gap:
                issues.append(f"{label}已经 {last - prev} 章没有推进（上限 {gap} 章），下一弧安排一次")
    levels = [(int(c["number"]), str(c.get("payoff_level") or "")) for c in chs if c.get("payoff_level")]
    if len(levels) >= COMBO_WINDOW:
        nums = [n for n, _ in levels]
        for i in range(0, len(levels) - COMBO_WINDOW + 1):
            window = levels[i : i + COMBO_WINDOW]
            if not any(lv in ("combo", "milestone") for _, lv in window):
                issues.append(f"第{window[0][0]}–{window[-1][0]}章没有组合爽点（每 {COMBO_WINDOW} 章建议至少 1 个）")
                break
        if nums[-1] - nums[0] + 1 >= MILESTONE_WINDOW and not any(lv == "milestone" for _, lv in levels[-MILESTONE_WINDOW:]):
            issues.append(f"最近 {MILESTONE_WINDOW} 章没有里程碑爽点（改变主角地位的阶段胜利），本弧安排一个")
    if open_foreshadows and current:
        for f in open_foreshadows:
            age = current - int(getattr(f, "last_ch", 0) or getattr(f, "planted_ch", 0) or 0)
            if age > FORESHADOW_ALERT_AGE:
                issues.append(f"伏笔 #{getattr(f, 'id', '?')}「{getattr(f, 'desc', '')}」已 {age} 章没有推进（红线 {FORESHADOW_ALERT_AGE}），尽快回收或推进")
            elif age > FORESHADOW_WARN_AGE:
                issues.append(f"伏笔 #{getattr(f, 'id', '?')}「{getattr(f, 'desc', '')}」已 {age} 章没有推进，给一条新线索让读者知道它还活着")
    return issues


def foreshadow_age_label(f: Any, current: int) -> str:
    age = current - int(getattr(f, "last_ch", 0) or getattr(f, "planted_ch", 0) or 0)
    if age > FORESHADOW_ALERT_AGE:
        return f"已 {age} 章未推进，超期红线"
    if age > FORESHADOW_WARN_AGE:
        return f"已 {age} 章未推进，偏久"
    return f"{age} 章前推进过" if age > 0 else "本章前刚推进"


def chapter_beats_list(s: Session, book_id: int) -> list[dict[str, Any]]:
    nodes = s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter")
                   .order_by(OutlineNode.order)).all()
    return [{**(n.beats or {}), "number": n.order} for n in nodes]


def rhythm_ledger(beats_list: list[dict[str, Any]], before: int, n: int = 8) -> str:
    """最近 n 章（章号 < before）的节奏标注，供规划/写作时避免重复。"""
    rows = [b for b in beats_list if int(b.get("number") or 0) < before][-n:]
    lines = []
    for b in rows:
        bits = [x for x in (
            b.get("payoff_type") and f"爽点 {b['payoff_type']}" + (f"/{b['payoff_level']}" if b.get("payoff_level") else ""),
            b.get("hook_type") and f"钩子 {b['hook_type']}",
            b.get("outcome") and f"结果 {b['outcome']}",
            b.get("strand") and f"线 {'+'.join(b['strand'])}",
            b.get("emotion") and f"情绪 {b['emotion']}",
        ) if x]
        if bits:
            lines.append(f"第{b['number']}章：" + "，".join(bits))
    return "\n".join(lines)


def _children(s: Session, parent_id: int) -> list[OutlineNode]:
    return list(s.exec(select(OutlineNode).where(OutlineNode.parent_id == parent_id).order_by(OutlineNode.order)))


def max_chapter_number(s: Session, book_id: int) -> int:
    v = s.exec(
        select(func.max(OutlineNode.order)).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter")
    ).one()
    return int(v or 0)


def _add_chapters(s: Session, book: Book, arc: OutlineNode, chapters: list[dict[str, Any]]) -> list[OutlineNode]:
    n = max_chapter_number(s, book.id or 0)
    out = []
    for raw in chapters:
        n += 1
        beats = normalize_beats(raw if isinstance(raw, dict) else {}, n, book.chapter_words)
        node = OutlineNode(
            book_id=book.id or 0, parent_id=arc.id, level="chapter", order=n, title=beats["title"],
            summary=f"{beats['goal']}；{beats['conflict']}".strip("；"), beats=beats, status="planned",
        )
        s.add(node)
        out.append(node)
    arc.status = "expanded"
    s.add(arc)
    return out


def generate_outline(book_id: int, ctx: JobContext) -> dict[str, Any]:
    gw = get_gateway()
    with common_session() as s:
        book = common.get_book(s, book_id)
        meta = {**common.kit_meta(s, book), "chapters_per_arc": CHAPTERS_PER_ARC}
        user = render(
            "outline", book_context=common.book_context(s, book), target_words=book.target_words,
            chapter_words=book.chapter_words,
        )
    user += research_notes("outline", user, book_id, ctx, 5)
    ctx.progress(10, "生成总纲、卷与前两弧")
    data = gw.chat_json("outline", system_prompt("outline"), user, meta=meta)
    if not isinstance(data, dict) or not data.get("volumes"):
        raise ValueError("大纲结构不完整（缺少 volumes）")
    ctx.progress(70, "写入大纲")
    with common_session() as s:
        book = common.get_book(s, book_id)
        for n in common.outline_nodes(s, book_id):
            s.delete(n)
        s.flush()
        bk = data.get("book") or {}
        root_summary = str(bk.get("summary", ""))
        if bk.get("promise"):
            root_summary += f"\n长期追读承诺：{bk['promise']}"
        root = OutlineNode(book_id=book_id, level="book", order=1, title=str(bk.get("title") or book.title),
                           summary=root_summary, status="expanded")
        s.add(root)
        s.flush()
        vols: list[OutlineNode] = []
        for i, v in enumerate(data.get("volumes") or [], 1):
            node = OutlineNode(book_id=book_id, parent_id=root.id, level="volume", order=i,
                               title=str(v.get("title") or f"第{i}卷"), summary=str(v.get("summary", "")), status="planned")
            s.add(node)
            vols.append(node)
        s.flush()
        arc_count: dict[int, int] = {}
        chapters_total = 0
        for a in data.get("arcs") or []:
            vi = int(a.get("volume") or 1)
            vol = vols[min(max(vi, 1), len(vols)) - 1]
            arc_count[vol.id or 0] = arc_count.get(vol.id or 0, 0) + 1
            arc = OutlineNode(book_id=book_id, parent_id=vol.id, level="arc", order=arc_count[vol.id or 0],
                              title=str(a.get("title") or "未命名弧"), summary=str(a.get("summary", "")), status="planned")
            s.add(arc)
            s.flush()
            vol.status = "expanded"
            s.add(vol)
            chapters_total += len(_add_chapters(s, book, arc, a.get("chapters") or []))
        if book.status in ("idea", "bible"):
            book.status = "outline"
        book.updated_at = utcnow()
        s.add(book)
        s.flush()
        pacing = pacing_audit(chapter_beats_list(s, book_id))
        s.commit()
    return {"volumes": len(vols), "chapters": chapters_total, "pacing_warnings": pacing}


def expand_node(node_id: int, ctx: JobContext) -> dict[str, Any]:
    gw = get_gateway()
    with common_session() as s:
        node = s.get(OutlineNode, node_id)
        if node is None:
            raise NotFound("大纲节点不存在")
        book = common.get_book(s, node.book_id)
        kids = _children(s, node.id or 0)
        siblings = [n.title for n in s.exec(select(OutlineNode).where(OutlineNode.parent_id == node.parent_id)).all()] if node.parent_id else []
        recent = common.committed_chapters(s, book.id or 0)[-3:]
        opens = common.open_foreshadows(s, book.id or 0)
        next_no = max_chapter_number(s, book.id or 0) + 1
        all_beats = chapter_beats_list(s, book.id or 0)
        ledger = rhythm_ledger(all_beats, next_no)
        audit = pacing_audit(all_beats[-15:], opens, next_no)
        meta = {**common.kit_meta(s, book), "level": node.level, "existing": len(kids),
                "next_number": max_chapter_number(s, book.id or 0) + 1, "chapters_per_arc": CHAPTERS_PER_ARC,
                "number": node.order}
        if node.level == "book":
            instruction, schema = "再规划 2 卷。", '{"volumes":[{"title":"","summary":""}]}'
        elif node.level == "volume":
            instruction, schema = "为这一卷规划接下来的 2 个弧。", '{"arcs":[{"title":"","summary":""}]}'
        elif node.level == "arc":
            instruction = f"为这一弧写 {CHAPTERS_PER_ARC} 章细纲（章号从 {meta['next_number']} 开始）。"
            schema = CHAPTER_SCHEMA
        else:
            instruction = "把这一章细纲补充完整。"
            schema = '{"beats":{"title":"","goal":"","conflict":"","outcome":"","payoff":"","characters":[],"location":"","foreshadow":[],"hook_end":""}}'
        user = render(
            "expand", book_context=common.book_context(s, book), node_level=node.level, node_title=node.title,
            node_summary=node.summary, siblings="、".join(siblings) or "无",
            recent="\n".join(f"第{c.number}章：{c.summary}" for c in recent) or "无",
            open_foreshadows="\n".join(f"#{f.id} {f.desc}（第{f.planted_ch}章埋，{foreshadow_age_label(f, next_no)}）" for f in opens) or "无",
            rhythm=ledger or "（尚无节奏标注）",
            pacing="\n".join(f"- {x}" for x in audit) or "（无）",
            instruction=instruction, schema=schema,
        )
        level = node.level
    ctx.progress(15, f"展开{level}")
    data = gw.chat_json("expand", system_prompt("expand"), user, meta=meta)
    if not isinstance(data, dict):
        raise ValueError("展开结果不是 JSON 对象")
    with common_session() as s:
        node = s.get(OutlineNode, node_id)
        assert node is not None
        book = common.get_book(s, node.book_id)
        created: list[OutlineNode] = []
        if level in ("book", "volume"):
            key, child_level = ("volumes", "volume") if level == "book" else ("arcs", "arc")
            start = len(_children(s, node.id or 0))
            for i, it in enumerate(data.get(key) or [], 1):
                c = OutlineNode(book_id=node.book_id, parent_id=node.id, level=child_level, order=start + i,
                                title=str(it.get("title") or ""), summary=str(it.get("summary", "")), status="planned")
                s.add(c)
                created.append(c)
            node.status = "expanded"
            s.add(node)
        elif level == "arc":
            created = _add_chapters(s, book, node, data.get("chapters") or [])
        else:
            if node.status == "written":
                raise Conflict("该章已写，不能再展开细纲")
            beats = normalize_beats({**(node.beats or {}), **(data.get("beats") or {})}, node.order, book.chapter_words)
            node.beats = beats
            node.title = beats["title"]
            node.status = "expanded"
            s.add(node)
        if not created and level != "chapter":
            raise ValueError("展开结果为空")
        s.flush()
        pacing = pacing_audit(chapter_beats_list(s, node.book_id)[-15:]) if level in ("arc", "chapter") else []
        s.commit()
        return {"node_id": node_id, "created": [c.id for c in created], "pacing_warnings": pacing}


def next_chapter_node(s: Session, book_id: int) -> OutlineNode | None:
    return s.exec(
        select(OutlineNode)
        .where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter", OutlineNode.status != "written",
               OutlineNode.chapter_id == None)  # noqa: E711
        .order_by(OutlineNode.order)
    ).first()


def ensure_next_chapter_node(book_id: int, ctx: JobContext) -> int:
    """取下一个未写的章细纲；没有时按滚动规划自动展开下一弧（必要时先展开下一卷）。最多展开 3 步。"""
    for _ in range(3):
        with common_session() as s:
            node = next_chapter_node(s, book_id)
            if node is not None:
                return node.id or 0
            nodes = common.outline_nodes(s, book_id)
            if not nodes:
                raise Conflict("还没有大纲，请先生成大纲（没有细纲不许写正文）")
            vols = sorted([n for n in nodes if n.level == "volume"], key=lambda n: n.order)
            target: int | None = None
            for v in vols:
                arcs = sorted([n for n in nodes if n.level == "arc" and n.parent_id == v.id], key=lambda n: n.order)
                empty = [a for a in arcs if not any(c.parent_id == a.id for c in nodes if c.level == "chapter")]
                if empty:
                    target = empty[0].id
                    break
                if not arcs:
                    target = v.id
                    break
            if target is None:
                raise Conflict("大纲中的章节已全部写完，请先在大纲里展开新的卷或弧")
        ctx.progress(5, "滚动规划：自动展开下一层大纲")
        expand_node(target, ctx)
    raise Conflict("自动展开大纲失败，请手动展开")


def common_session():  # type: ignore[no-untyped-def]
    from app.db import session_scope

    return session_scope()


def node_plan_text(node: OutlineNode) -> str:
    b = dict(node.beats or {})
    b.pop("scenes", None)
    return json.dumps(b, ensure_ascii=False, indent=1)
