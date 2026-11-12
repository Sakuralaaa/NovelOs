"""作品信息（书名 / 一句话简介 / 核心设定）：让 AI 按要求改 → 预览对比 → 采纳（保留旧版本，可撤回）
→ 列出下游受影响的设定卡、大纲节点、章节 → 可选交给 AI 按同一要求同步到设定库和大纲。"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Book, Card, Chapter, OutlineNode, utcnow
from app.services import common, tropes
from app.services.common import NotFound
from app.skills.loader import render, system_prompt

INFO_FIELDS = ("title", "tagline", "premise")
MAX_VERSIONS = 10

_QUOTE_RX = re.compile(r"[『「“\"《]([^』」”\"》]{1,20})[』」”\"》]")
_NEG_RX = re.compile(r"(?:不要|别|不用|去掉|删掉|拿掉|弱化|淡化|少提|不再)(?:再)?(?:强调|突出|叫|用|提|写|出现|主打)?(?:成|做)?([\u4e00-\u9fa5A-Za-z0-9]{2,8}?)(?=[，,。；;、\s）)]|$|的|了)")


def extract_terms(instruction: str) -> list[str]:
    """从作者要求里抽出被点名的词：引号里的词，以及“不要强调X / 不要叫X / 去掉X”里的 X。"""
    out = [m.strip() for m in _QUOTE_RX.findall(instruction or "") if len(m.strip()) >= 2]
    for m in _NEG_RX.findall(instruction or ""):
        m = m.strip()
        if len(m) >= 2 and not any(m in o or o in m for o in out) and m not in ("这个", "那个", "这些", "太多", "一直"):
            out.append(m)
    return list(dict.fromkeys(out))[:10]


def info_of(b: Book) -> dict[str, str]:
    return {"title": b.title, "tagline": b.tagline, "premise": b.premise}


def push_version(b: Book, instruction: str) -> None:
    b.versions = [*(b.versions or []), {**info_of(b), "instruction": instruction[:200], "at": utcnow().isoformat()}][-MAX_VERSIONS:]


def _snippet(text: str, term: str, width: int = 26) -> str:
    i = text.find(term)
    if i < 0:
        return ""
    a, b = max(0, i - width), min(len(text), i + len(term) + width)
    return ("…" if a else "") + text[a:b].replace("\n", " ") + ("…" if b < len(text) else "")


def impact(s: Session, book_id: int, terms: list[str]) -> dict[str, Any]:
    """下游哪些条目包含这些词：设定卡、大纲节点（含细纲节拍）、章节正文。"""
    terms = [t for t in dict.fromkeys(t.strip() for t in terms) if len(t) >= 2]
    res: dict[str, Any] = {"terms": terms, "cards": [], "outline": [], "chapters": [], "total": 0}
    if not terms:
        return res
    for c in common.cards(s, book_id):
        text = f"{c.name}\n{c.summary}\n{json.dumps(c.data or {}, ensure_ascii=False)}"
        hit = [t for t in terms if t in text]
        if hit:
            res["cards"].append({"id": c.id, "name": c.name, "type": c.type, "terms": hit, "snippet": _snippet(text, hit[0])})
    for n in sorted(common.outline_nodes(s, book_id), key=lambda n: (["book", "volume", "arc", "chapter"].index(n.level) if n.level in ("book", "volume", "arc", "chapter") else 9, n.order)):
        text = f"{n.title}\n{n.summary}\n{json.dumps(n.beats or {}, ensure_ascii=False)}"
        hit = [t for t in terms if t in text]
        if hit:
            res["outline"].append({"id": n.id, "level": n.level, "order": n.order, "title": n.title, "status": n.status,
                                   "terms": hit, "snippet": _snippet(text, hit[0])})
    for ch in s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number)):
        text = ch.content or ""
        hit = {t: text.count(t) for t in terms if t in text}
        if hit:
            res["chapters"].append({"id": ch.id, "number": ch.number, "title": ch.title, "status": ch.status, "terms": list(hit),
                                    "count": sum(hit.values()), "snippet": _snippet(text, next(iter(hit)))})
    res["total"] = len(res["cards"]) + len(res["outline"]) + len(res["chapters"])
    return res


def revise_info(book_id: int, instruction: str, route: str | None, ctx: JobContext) -> dict[str, Any]:
    """按要求改书名 / 一句话简介 / 核心设定。结果只是建议，不落库。"""
    with session_scope() as s:
        b = common.get_book(s, book_id)
        cur = info_of(b)
        tl = tropes.tropes_for(s, b)
        history = "\n".join(f"- {v.get('instruction')}" for v in (b.versions or []) if v.get("instruction") and v.get("instruction") != "手动修改") or "（无）"
        gender = b.gender
    terms0 = extract_terms(instruction)
    user = render("book_revise", gender_label=common.GENDER_LABEL.get(gender, gender), title=cur["title"], tagline=cur["tagline"] or "（空）",
                  premise=cur["premise"] or "（空）", history=history, instruction=instruction.strip())
    user += tropes.prompt_block(tl, instruction)
    ctx.progress(25, "按要求改作品信息")
    out = get_gateway().chat_json("book_revise", system_prompt("book_revise"), user,
                                  meta={**cur, "instruction": instruction, "terms": terms0, "banned_keywords": tropes.keywords(tl, instruction)},
                                  route=route)
    if not isinstance(out, dict):
        raise ValueError("模型没有给出修改")
    prop = {
        "title": str(out.get("title") or cur["title"]).strip().strip("《》")[:40] or cur["title"],
        "tagline": str(out.get("tagline") if out.get("tagline") is not None else cur["tagline"]).strip(),
        "premise": str(out.get("premise") if out.get("premise") is not None else cur["premise"]).strip(),
    }
    reps = out.get("replacements") if isinstance(out.get("replacements"), dict) else {}
    reps = {str(k).strip(): str(v or "").strip() for k, v in reps.items() if str(k).strip()}
    removed = [str(t).strip() for t in (out.get("removed_terms") or []) if isinstance(t, str)]
    terms = list(dict.fromkeys([*terms0, *removed, *reps.keys()]))
    ctx.progress(75, "检查设定库、大纲和正文里受影响的地方")
    with session_scope() as s:
        imp = impact(s, book_id, terms)
        # 只保留真的出现在旧信息或下游里的词
        old_text = " ".join(cur.values())
        keep = [t for t in imp["terms"] if t in old_text or any(t in x["terms"] for k in ("cards", "outline", "chapters") for x in imp[k])]
        imp = impact(s, book_id, keep) if keep != imp["terms"] else imp
        hits = tropes.detect(" ".join(prop.values()), tropes.active(tl, instruction))
    return {"book_id": book_id, "instruction": instruction.strip(), "current": cur, "proposal": prop,
            "change": str(out.get("change") or "")[:120], "terms": imp["terms"],
            "replacements": {k: v for k, v in reps.items() if k in imp["terms"]}, "impact": imp, "trope_hits": hits}


def apply_info(book_id: int, fields: dict[str, Any], instruction: str) -> Book:
    with session_scope() as s:
        b = common.get_book(s, book_id)
        new = {k: str(fields[k]).strip() for k in INFO_FIELDS if fields.get(k) is not None}
        if "title" in new:
            new["title"] = new["title"].strip("《》")[:40] or b.title
        if any(new[k] != getattr(b, k) for k in new):
            push_version(b, instruction or "手动修改")
            for k, v in new.items():
                setattr(b, k, v)
            b.updated_at = utcnow()
            s.add(b)
            s.commit()
            s.refresh(b)
        return b


def undo_info(book_id: int) -> Book:
    with session_scope() as s:
        b = common.get_book(s, book_id)
        if not b.versions:
            raise ValueError("没有可以撤回的版本")
        prev = b.versions[-1]
        for k in INFO_FIELDS:
            if k in prev:
                setattr(b, k, prev[k])
        b.versions = b.versions[:-1]
        b.updated_at = utcnow()
        s.add(b)
        s.commit()
        s.refresh(b)
        return b


def _replace_in(v: Any, reps: dict[str, str]) -> Any:
    if isinstance(v, str):
        for a, b in reps.items():
            if b:
                v = v.replace(a, b)
        return v
    if isinstance(v, list):
        return [_replace_in(x, reps) for x in v]
    if isinstance(v, dict):
        return {k: _replace_in(x, reps) for k, x in v.items()}
    return v


def sync_downstream(book_id: int, instruction: str, terms: list[str], replacements: dict[str, str], targets: list[str],
                    route: str | None, ctx: JobContext) -> dict[str, Any]:
    """按同一要求生成对设定库与大纲的修改建议（不落库）：设定走冲突审阅，大纲给逐条勾选。"""
    from app.services import bible_ops

    reps = {k: v for k, v in (replacements or {}).items() if k}
    with session_scope() as s:
        imp = impact(s, book_id, terms)
        book = common.get_book(s, book_id)
        bctx = common.book_context(s, book, with_cards=False)
    out: dict[str, Any] = {"terms": imp["terms"], "replacements": reps, "bible": None, "outline": {"items": []},
                           "chapters": imp["chapters"]}
    rep_text = "；".join(f"{a} → {b or '（拿掉）'}" for a, b in reps.items()) or "（无，按要求拿掉或弱化）"
    if "bible" in targets and imp["cards"]:
        ctx.progress(15, f"同步设定库（{len(imp['cards'])} 张卡）")
        out["bible"] = bible_ops.propose(
            book_id, "optimize", f"{instruction}\n需要同步处理的词：{'、'.join(imp['terms'])}；改名对照：{rep_text}",
            route, ctx, card_ids=[c["id"] for c in imp["cards"]], terms=imp["terms"], replacements=reps)
    if "outline" in targets and imp["outline"]:
        ctx.progress(60, f"同步大纲（{len(imp['outline'])} 个节点）")
        with session_scope() as s:
            nodes = {n.id: n for n in common.outline_nodes(s, book_id)}
            sel = [nodes[x["id"]] for x in imp["outline"] if x["id"] in nodes]
            rows = [{"id": n.id, "level": n.level, "title": n.title, "summary": n.summary} for n in sel]
            before = {n.id: {"title": n.title, "summary": n.summary, "beats": n.beats, "level": n.level, "status": n.status} for n in sel}
        user = render("outline_sync", book_context=bctx, instruction=instruction, terms="、".join(imp["terms"]), replacements=rep_text,
                      nodes="\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        data = get_gateway().chat_json("outline_sync", system_prompt("outline_sync"), user,
                                       meta={"nodes": rows, "terms": imp["terms"], "replacements": reps, "instruction": instruction}, route=route)
        got = {int(x["id"]): x for x in ((data or {}).get("nodes") or []) if isinstance(x, dict) and str(x.get("id", "")).lstrip("-").isdigit()}
        items = []
        for nid, old in before.items():
            g = got.get(nid or 0)
            title = str(g.get("title") or old["title"]) if g else old["title"]
            summary = str(g.get("summary") if g and g.get("summary") is not None else old["summary"])
            beats = old["beats"]
            new_beats = _replace_in(beats, reps) if (beats and reps and old["level"] == "chapter" and old["status"] != "written") else beats
            if title == old["title"] and summary == old["summary"] and new_beats == beats:
                continue
            item = {"node_id": nid, "level": old["level"], "old": {"title": old["title"], "summary": old["summary"]},
                    "new": {"title": title, "summary": summary}, "reason": str((g or {}).get("reason") or "")[:80]}
            if new_beats != beats:
                item["new"]["beats"] = new_beats
                item["beats_changed"] = True
            items.append(item)
        out["outline"] = {"items": items}
    return out
