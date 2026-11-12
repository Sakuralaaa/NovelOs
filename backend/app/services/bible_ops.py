"""设定库 AI 生成三种模式（完全重写 / 纯增加 / 优化）+ 冲突审阅 + 快照回滚。

流程：propose（后台任务，不落库）→ 前端展示「新增」与「冲突审阅」两组，作者逐条决定
→ apply（先存快照，再按作者选择执行 create / update / delete）→ 需要时从快照回滚。
冲突 = 程序检测（同名、名称相近、重复金手指）+ 模型自报（矛盾的事实等）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import BibleSnapshot, Card, Fact, utcnow
from app.services import common, tropes
from app.services.changes import CARD_TYPES
from app.services.common import NotFound
from app.services.research import research_notes
from app.skills.loader import render, system_prompt

MODES = ("rewrite", "add", "optimize")
MODE_LABEL = {"rewrite": "完全重写", "add": "纯增加", "optimize": "优化"}
MAX_SNAPSHOTS = 20

MODE_TASK = {
    "rewrite": "基于书的信息和作者要求，重新生成这本书的整套设定库（会替换现有设定，作者会先预览）。",
    "add": "在现有设定库的基础上只新增设定卡，不改动任何已有的卡。",
    "optimize": "在现有设定库的基础上改进：可以改写已有的卡（action=update，target 写旧卡名），也可以补充新卡（action=add）。",
}
MODE_SCOPE = {
    "rewrite": ("要求：输出完整的一整套设定（全部 action=add）：至少 1 张 world、1 张 cheat（data 含 input/limit/growth）、1 张 power（data 含 levels）、"
                "2 张 faction、5 张 character（第一张是主角，data 含 role、voice、catchphrases、habits、demeanor、knows、unknown、misbelief）、"
                "2 张 item、3 张 location（data 含 sensory）。可以沿用旧设定里好的部分（同名即视为替换旧卡）。"),
    "add": "要求：只输出新卡（action=add），3–6 张为宜；不要和已有卡重名，不要和已有事实矛盾；主角已有金手指就不要再加第二个金手指。",
    "optimize": "要求：只动作者要求涉及的卡，没提到的卡不要输出；改写时保留原卡没提到的内容和 data 键。",
}


def _norm(name: str) -> str:
    return re.sub(r"[\s·・（）()《》「」『』\"“”]", "", name or "").lower()


def card_dict(c: Card) -> dict[str, Any]:
    return {"id": c.id, "type": c.type, "name": c.name, "summary": c.summary, "data": dict(c.data or {}), "known_by": list(c.known_by or [])}


def normalize_card(it: dict[str, Any], fallback_type: str = "character") -> dict[str, Any] | None:
    if not isinstance(it, dict) or not str(it.get("name") or "").strip():
        return None
    t = it.get("type") if it.get("type") in CARD_TYPES else fallback_type
    return {"type": t, "name": str(it["name"]).strip()[:40], "summary": str(it.get("summary") or ""),
            "data": it.get("data") if isinstance(it.get("data"), dict) else {},
            "known_by": [str(x) for x in (it.get("known_by") or []) if str(x).strip()] if isinstance(it.get("known_by"), list) else []}


def detect_conflicts(card: dict[str, Any], existing: list[Card], target_id: int | None) -> list[dict[str, Any]]:
    """程序侧冲突检测：同名（任何类型）、同类名称相近、重复金手指。"""
    out: list[dict[str, Any]] = []
    n = _norm(card["name"])
    for c in existing:
        if c.id == target_id:
            continue
        cn = _norm(c.name)
        reason = ""
        if cn and cn == n:
            reason = "同名设定" + ("（类型也相同）" if c.type == card["type"] else f"（旧卡是「{c.type}」类）")
        elif c.type == card["type"] and len(n) >= 2 and len(cn) >= 2 and (n in cn or cn in n):
            reason = "同类设定，名称相近，可能是同一个东西"
        elif card["type"] == "cheat" and c.type == "cheat":
            reason = f"主角已经有金手指「{c.name}」，新卡会变成第二个金手指"
        if reason:
            out.append({"card_id": c.id, "name": c.name, "type": c.type, "reason": reason, "source": "program"})
    return out


def propose(book_id: int, mode: str, instruction: str, route: str | None, ctx: JobContext,
            card_ids: list[int] | None = None, terms: list[str] | None = None, replacements: dict[str, str] | None = None) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError("不支持的模式")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = common.kit_meta(s, book)
        existing = common.cards(s, book_id)
        scope_cards = [c for c in existing if card_ids is None or c.id in card_ids]
        tl = tropes.tropes_for(s, book)
        bctx = common.book_context(s, book, with_cards=False)
    shown = scope_cards if mode == "optimize" else existing
    ex_lines = "\n".join(json.dumps({k: v for k, v in card_dict(c).items() if k != "id"}, ensure_ascii=False) for c in shown) or "（空）"
    if mode == "optimize" and card_ids is not None:
        others = [c for c in existing if c.id not in set(card_ids)]
        ex_lines += "\n（其余设定卡，只作参考，不要改）：\n" + ("\n".join(f"[{c.type}] {c.name}：{c.summary}" for c in others) or "（无）")
    user = render("bible_propose", mode_task=MODE_TASK[mode], book_context=bctx, existing=ex_lines,
                  instruction=instruction.strip() or ("按书的信息把设定写完整、写具体。" if mode != "optimize" else "写得更具体、更有画面感，彼此咬合。"),
                  scope=MODE_SCOPE[mode])
    user += tropes.prompt_block(tl, instruction)
    if mode == "rewrite":
        user += research_notes("bible", user, book_id, ctx, 10)
    ctx.progress(20, f"AI {MODE_LABEL[mode]}设定")
    data = get_gateway().chat_json(
        "bible_propose", system_prompt("bible_propose"), user,
        meta={**meta, "mode": mode, "instruction": instruction, "existing": [card_dict(c) for c in shown], "terms": terms or [],
              "replacements": replacements or {}, "banned_keywords": tropes.keywords(tl, instruction)},
        route=route)
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        raise ValueError("模型没有返回设定卡")
    ctx.progress(75, "检测冲突")
    by_norm = {_norm(c.name): c for c in existing}
    items: list[dict[str, Any]] = []
    matched_old: set[int] = set()
    act_tropes = tropes.active(tl, instruction)
    for i, raw in enumerate(data["cards"]):
        card = normalize_card(raw)
        if card is None:
            continue
        action = "update" if raw.get("action") == "update" and mode == "optimize" else "add"
        target: Card | None = None
        if action == "update":
            target = by_norm.get(_norm(str(raw.get("target") or ""))) or by_norm.get(_norm(card["name"]))
            if target is None or (card_ids is not None and target.id not in card_ids):
                action, target = "add", None
        elif mode == "rewrite":
            target = by_norm.get(_norm(card["name"]))  # 重写时同名视为替换旧卡
        conflicts = detect_conflicts(card, existing, target.id if (target and action == "update") else None)
        if mode == "rewrite" and target is not None:
            conflicts = [c for c in conflicts if c["card_id"] != target.id]
            conflicts.insert(0, {"card_id": target.id, "name": target.name, "type": target.type, "reason": "重写后的同名设定，内容有变化", "source": "program"})
        seen = {c["card_id"] for c in conflicts}
        for ac in raw.get("conflicts") or []:
            if not isinstance(ac, dict):
                continue
            old = by_norm.get(_norm(str(ac.get("name") or "")))
            if old is None or old.id in seen or (target is not None and old.id == target.id and action == "update"):
                continue
            seen.add(old.id)
            conflicts.append({"card_id": old.id, "name": old.name, "type": old.type, "reason": str(ac.get("reason") or "与已有设定矛盾")[:80], "source": "ai"})
        if target is not None:
            matched_old.add(target.id or 0)
        by_id = {c.id: c for c in existing}
        old_card = card_dict(target) if target is not None else (card_dict(by_id[conflicts[0]["card_id"]]) if conflicts else None)
        if action == "update" and old_card is not None and all(old_card[k] == card[k] for k in ("type", "name", "summary", "data", "known_by")):
            continue  # 没有实际改动
        items.append({
            "key": f"n{i + 1}", "action": action, "card": card, "target_id": target.id if target is not None else None, "old": old_card,
            "conflicts": conflicts, "trope_hits": tropes.detect_obj(card, act_tropes),
            "default": ("replace" if (action == "update" or mode == "rewrite") else "keep_old") if conflicts or action == "update" else "add",
        })
    removals: list[dict[str, Any]] = []
    if mode == "rewrite":
        for c in existing:
            if c.id not in matched_old:
                removals.append({"card_id": c.id, "name": c.name, "type": c.type, "summary": c.summary})
    facts = [f for f in (data.get("facts") or []) if isinstance(f, dict) and f.get("key")] if mode == "rewrite" else []
    return {"book_id": book_id, "mode": mode, "instruction": instruction.strip(), "change": str(data.get("change") or "")[:120],
            "items": items, "removals": removals, "facts": facts[:40],
            "counts": {"add": sum(1 for x in items if not x["conflicts"] and x["action"] == "add"),
                       "review": sum(1 for x in items if x["conflicts"] or x["action"] == "update"), "removals": len(removals)}}


def snapshot(s: Session, book_id: int, note: str) -> BibleSnapshot:
    snap = BibleSnapshot(book_id=book_id, note=note[:80], cards=[card_dict(c) for c in common.cards(s, book_id)])
    s.add(snap)
    s.flush()
    olds = list(s.exec(select(BibleSnapshot).where(BibleSnapshot.book_id == book_id).order_by(BibleSnapshot.id)))
    for o in olds[:-MAX_SNAPSHOTS]:
        s.delete(o)
    return snap


def _unlink_facts(s: Session, card_id: int) -> None:
    for f in s.exec(select(Fact).where(Fact.entity_id == card_id)):
        f.entity_id = None
        s.add(f)


def apply(book_id: int, mode: str, instruction: str, ops: list[dict[str, Any]], facts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """执行作者勾选后的操作。先存快照，整个过程一个事务。"""
    with session_scope() as s:
        book = common.get_book(s, book_id)
        snap = snapshot(s, book_id, f"{MODE_LABEL.get(mode, '批量修改')}前" + (f"：{instruction.strip()[:30]}" if instruction.strip() else ""))
        cards = {c.id: c for c in common.cards(s, book_id)}
        names = {c.name for c in cards.values()}
        n = {"created": 0, "updated": 0, "deleted": 0}
        try:
            for op in ops:
                kind = op.get("op")
                if kind == "delete":
                    c = cards.pop(int(op.get("card_id") or 0), None)
                    if c is not None:
                        _unlink_facts(s, c.id or 0)
                        names.discard(c.name)
                        s.delete(c)
                        n["deleted"] += 1
                    continue
                card = normalize_card(op.get("card") or {})
                if card is None:
                    continue
                if kind == "update":
                    c = cards.get(int(op.get("card_id") or 0))
                    if c is None:
                        raise NotFound(f"卡片 {op.get('card_id')} 不存在或已删除")
                    names.discard(c.name)
                    c.type, c.name, c.summary, c.data, c.known_by = card["type"], card["name"], card["summary"], card["data"], card["known_by"]
                    c.updated_at = utcnow()
                    s.add(c)
                    names.add(c.name)
                    n["updated"] += 1
                elif kind == "create":
                    name = card["name"]
                    k = 1
                    while name in names:  # 两者都留：新卡改名避免同名
                        k += 1
                        name = f"{card['name']}（新{'' if k == 2 else k - 1}）"[:40]
                    c = Card(book_id=book_id, **{**card, "name": name})
                    s.add(c)
                    s.flush()
                    cards[c.id] = c
                    names.add(name)
                    n["created"] += 1
            by_name = {c.name: c for c in cards.values()}
            for f in facts or []:
                if not isinstance(f, dict) or not f.get("key"):
                    continue
                ent = by_name.get(str(f.get("entity", "")))
                dup = s.exec(select(Fact).where(Fact.book_id == book_id, Fact.entity_id == (ent.id if ent else None),
                                                Fact.key == str(f["key"]), Fact.to_chapter == None)).first()  # noqa: E711
                if dup is None:
                    s.add(Fact(book_id=book_id, entity_id=ent.id if ent else None, key=str(f["key"]), value=str(f.get("value", "")),
                               from_chapter=0, visibility="reader" if f.get("visibility") == "reader" else "author"))
            if book.status == "idea":
                book.status = "bible"
            book.updated_at = utcnow()
            s.add(book)
            s.commit()
        except Exception:
            s.rollback()
            raise
        return {**n, "snapshot_id": snap.id}


def list_snapshots(s: Session, book_id: int) -> list[dict[str, Any]]:
    from app.api.schemas import iso

    rows = s.exec(select(BibleSnapshot).where(BibleSnapshot.book_id == book_id).order_by(BibleSnapshot.id.desc())).all()  # type: ignore[union-attr]
    return [{"id": r.id, "note": r.note, "count": len(r.cards or []), "created_at": iso(r.created_at),
             "names": [c.get("name") for c in (r.cards or [])][:12]} for r in rows]


def restore(book_id: int, snapshot_id: int) -> dict[str, Any]:
    """回滚到快照（回滚前也存一份快照，回滚本身可再回滚）。按 id 还原，人物状态等关联事实不丢。"""
    with session_scope() as s:
        common.get_book(s, book_id)
        snap = s.get(BibleSnapshot, snapshot_id)
        if snap is None or snap.book_id != book_id:
            raise NotFound("快照不存在")
        target = list(snap.cards or [])
        before = snapshot(s, book_id, f"回滚到「{snap.note}」之前")
        cur = {c.id: c for c in common.cards(s, book_id)}
        keep = {int(c["id"]) for c in target if c.get("id")}
        for cid, c in cur.items():
            if cid not in keep:
                _unlink_facts(s, cid or 0)
                s.delete(c)
        s.flush()
        for d in target:
            c = cur.get(d.get("id")) if d.get("id") else None
            if c is None:
                other = s.get(Card, d.get("id")) if d.get("id") else None
                c = Card(id=d.get("id") if other is None else None, book_id=book_id, type=d["type"], name=d["name"])
            c.type, c.name, c.summary = d.get("type") or "character", d.get("name") or "未命名", d.get("summary") or ""
            c.data, c.known_by, c.updated_at = dict(d.get("data") or {}), list(d.get("known_by") or []), utcnow()
            s.add(c)
        s.commit()
        return {"restored": len(target), "snapshot_id": before.id}
