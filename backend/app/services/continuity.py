"""v0.17.1 衔接：规划和实写对齐。

- sync_chapter_beats：写一章前，拿上一章实际写出的结尾、已结算的奖励，校正本章和下一章的章纲：
  本章从上一章真实结尾接着走，上一章已经发生、已经结算的事不再重做；章纲本身没问题就不动。
- settled_lines：最近几章里结算过的系统提示/面板行（整行【…】），交给规划和写手，同一笔奖励只结算一次。
- recent_usage：前两章口头禅、习惯动作已用次数，lint 按连续三章合计计数，写手提示里点名别再用。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session

from app.models.tables import Chapter, OutlineNode
from app.services import common

SYNC_FIELDS = ("title", "goal", "want", "conflict", "conflict_type", "turn", "result", "outcome", "payoff", "payoff_mechanism",
               "cheat_beat", "hook_end", "opening_hook", "expectation", "characters", "location")
SETTLED_CHAPTERS = 5
SETTLED_MAX = 14
USAGE_CHAPTERS = 2
_PANEL = re.compile(r"^\s*【[^【】\n]{2,80}】\s*$")


def settled_lines(chapters: list[Chapter], n: int = SETTLED_CHAPTERS, limit: int = SETTLED_MAX) -> list[str]:
    """最近 n 章正文里整行的【…】提示（系统面板、结算、奖励），按章号带出处，去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for c in sorted(chapters, key=lambda x: x.number)[-n:]:
        for line in (c.content or "").split("\n"):
            if _PANEL.match(line):
                t = line.strip()
                if t not in seen:
                    seen.add(t)
                    out.append(f"第{c.number}章：{t}")
    return out[-limit:]


def settled_block(chapters: list[Chapter]) -> str:
    lines = settled_lines(chapters)
    if not lines:
        return ""
    return ("【前文已经结算/提示过的系统面板（这些事已经发生过，本章不再结算同一笔、不再重报同一条，只写新的变化）】\n"
            + "\n".join(lines))


def recent_usage(s: Session, book_id: int, number: int, chapters: list[Chapter] | None = None) -> dict[str, int]:
    """前 USAGE_CHAPTERS 章里各口头禅、习惯动作出现的次数（键与 lint 里的 word 一致）。"""
    from app.lint.humanlint import habit_quotes

    prev = chapters if chapters is not None else common.written_chapters(s, book_id, before=number)
    texts = [c.content or "" for c in sorted(prev, key=lambda x: x.number)[-USAGE_CHAPTERS:]]
    if not texts:
        return {}
    out: dict[str, int] = {}
    for c in common.cards(s, book_id, "character"):
        v = common.voice_of(c)
        for ph in v["catchphrases"]:
            key = re.sub(r"[，,。！？!?、…\s“”\"]+", "", str(ph))
            if key:
                n = sum(t.count(key) for t in texts)
                if n:
                    out[key] = out.get(key, 0) + n
        for h in v["habits"]:
            n = sum(len(habit_quotes(t, str(h))) for t in texts)
            if n:
                out[str(h)[:30]] = out.get(str(h)[:30], 0) + n
    return out


def usage_note(usage: dict[str, int]) -> str:
    used = [f"「{k}」{v} 次" for k, v in sorted(usage.items(), key=lambda kv: -kv[1]) if v >= 1][:8]
    if not used:
        return ""
    return "前两章已经用过的口头禅和习惯动作：" + "、".join(used) + "。本章尽量不用，腔调靠句式和选择带出来。"


def _brief_beats(b: dict[str, Any]) -> dict[str, Any]:
    return {k: b[k] for k in SYNC_FIELDS if b.get(k) not in (None, "", [])}


def _prev_written(s: Session, book_id: int, number: int) -> Chapter | None:
    prev = [c for c in common.written_chapters(s, book_id, before=number) if c.number == number - 1]
    return prev[-1] if prev and (prev[-1].content or "").strip() else None


def _merge(node: OutlineNode, patch: Any) -> bool:
    if not isinstance(patch, dict):
        return False
    b = dict(node.beats or {})
    changed = False
    for k in SYNC_FIELDS:
        if k not in patch:
            continue
        v = patch[k]
        if k == "characters":
            if not isinstance(v, list):
                continue
            v = [str(x) for x in v if str(x).strip()][:12]
        elif k == "outcome":
            v = str(v or "").strip()
            if v not in ("yes", "no", "yes-but", "no-and"):
                continue
        else:
            v = str(v or "").strip()[:600]
        if v and v != b.get(k):
            b[k] = v
            changed = True
    if not changed:
        return False
    b.pop("scenes", None)  # 段落安排要按新章纲重排
    from app.services.outline import push_node_version

    push_node_version(node, "按上一章实写衔接校正")
    node.beats = b
    if b.get("title"):
        node.title = str(b["title"])[:60]
    node.summary = f"{b.get('goal', '')}；{b.get('conflict', '')}".strip("；")
    return True


def sync_chapter_beats(book_id: int, node_id: int, force: bool = False) -> dict[str, Any]:
    """写第 n 章前：上一章写出来了，就让规划模型对照上一章实际结尾校正本章（和下一章）的章纲。
    锁定的节点不动；没有上一章、或规划模型判断衔接没问题时原样返回。force=True 时即使模型说没问题也照它给的字段改。"""
    from app.db import session_scope
    from app.llm.gateway import get_gateway
    from app.services.context import chapter_brief, chapter_tail
    from app.services import outline as _ol
    from app.services.scene_state import render_state
    from app.skills.loader import render, system_prompt

    with session_scope() as s:
        node = s.get(OutlineNode, node_id)
        if node is None or node.level != "chapter":
            return {"changed": False, "reason": "节点不存在"}
        number = node.order
        prev = _prev_written(s, book_id, number)
        if prev is None:
            return {"changed": False, "reason": "没有上一章"}
        nxt = next((x for x in common.outline_nodes(s, book_id) if x.level == "chapter" and x.order == number + 1), None)
        prev_node = s.get(OutlineNode, prev.outline_node_id) if prev.outline_node_id else None
        written = common.written_chapters(s, book_id, before=number)
        es = (prev.changes or {}).get("end_state") if isinstance(prev.changes, dict) else None
        book = common.get_book(s, book_id)
        user = render(
            "chapter_sync",
            book=f"《{book.title}》{(book.premise or '')[:300]}",
            prev_number=prev.number, prev_title=prev.title,
            prev_plan=json.dumps(_brief_beats((prev_node.beats if prev_node else None) or {}), ensure_ascii=False),
            prev_summary=chapter_brief(prev, 400),
            prev_tail=chapter_tail(prev.content or "", 900, 400),
            prev_state=render_state(es, "上一章结束时的场面") if isinstance(es, dict) else "（无）",
            settled="\n".join(settled_lines(written)) or "（无）",
            recent="\n".join(f"第{c.number}章 {c.title}：{chapter_brief(c, 120)}" for c in written[-4:-1]) or "（无）",
            number=number,
            plan=json.dumps(_brief_beats(node.beats or {}), ensure_ascii=False),
            next_plan=json.dumps(_brief_beats(nxt.beats or {}), ensure_ascii=False) if nxt else "（还没有）",
            promises=_ol.promises_text(_ol.book_promises(s, book_id), number) or "（没列）",
            rhythm=_ol.rhythm_ledger(_ol.chapter_beats_list(s, book_id), number, 4) or "（无）",
        )
        locked = bool(getattr(node, "locked", False))
        next_id = nxt.id if nxt is not None and not getattr(nxt, "locked", False) else None
    if locked:
        return {"changed": False, "reason": "章纲已锁定"}
    data = get_gateway().chat_json("chapter_sync", system_prompt("chapter_sync"), user,
                                   meta={"book_id": book_id, "number": number})
    if not isinstance(data, dict):
        return {"changed": False, "reason": "模型没有给出结果"}
    ok = bool(data.get("ok", True))
    reason = str(data.get("reason") or "")[:300]
    if ok and not force:
        return {"changed": False, "reason": reason or "衔接没问题"}
    changed: list[int] = []
    with session_scope() as s:
        node = s.get(OutlineNode, node_id)
        if node is not None and _merge(node, data.get("chapter")):
            s.add(node)
            changed.append(number)
        if next_id:
            n2 = s.get(OutlineNode, next_id)
            if n2 is not None and _merge(n2, data.get("next")):
                s.add(n2)
                changed.append(number + 1)
        s.commit()
    return {"changed": bool(changed), "chapters": changed, "reason": reason}
