"""Agent 工具：全部复用 v0.4 已有服务，不另写一套。

- 读工具：直接查库，返回精简 JSON（给模型看）+ 一句话摘要（给作者看）。
- 改工具：调用已有的「让 AI 改」服务生成建议 → 存成提案（agent_proposals），默认等作者采纳。
- 长任务（写下一章、生图）：提案采纳后走现有 Job，对话里显示进度。

流程归代码（参数校验、冲突检测、快照、版本栈），判断归 AI（改什么、怎么改、先读什么）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import select

from app.db import session_scope
from app.llm.gateway import get_gateway, is_mock_mode
from app.models.tables import Card, Chapter, Foreshadow, OutlineNode, Package
from app.services import agent_proposals as props
from app.services import bible_ops, book_edit, common, outline, packaging, tropes, writing
from app.services import foreshadows as fs_svc
from app.services.common import NotFound


@dataclass
class ToolCtx:
    book_id: int
    session_id: int
    job: Any = None  # JobContext（agent_run 任务）
    step: int = 0

    def progress(self, msg: str) -> None:
        if self.job is not None:
            try:
                self.job.progress(min(95, 5 + self.step * 7), msg)
            except Exception:  # noqa: BLE001
                pass


class _SubCtx:
    """把服务内部的进度转发到 agent 任务上（前缀写明是哪个工具）。"""

    def __init__(self, tc: ToolCtx, label: str) -> None:
        self.tc, self.label = tc, label
        self.job_id = getattr(tc.job, "job_id", 0)
        self.book_id = tc.book_id

    def progress(self, pct: int, message: str = "") -> None:
        self.tc.progress(f"{self.label}：{message}" if message else self.label)


@dataclass
class ToolResult:
    data: dict[str, Any]
    summary: str
    proposal_ids: list[int] = field(default_factory=list)
    job_ids: list[int] = field(default_factory=list)
    ok: bool = True


@dataclass
class Tool:
    name: str
    label: str
    kind: str  # read / write
    description: str
    params: dict[str, Any]
    required: list[str]
    fn: Callable[[ToolCtx, dict[str, Any]], ToolResult]

    def spec(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": {"type": "object", "properties": self.params, "required": self.required}}}


def _clip(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + f"…（共 {len(text)} 字，已截断）"


S = {"type": "string"}
I = {"type": "integer"}


def _int(v: Any, default: int | None = None) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ================================================================== 读工具

def t_book_info(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        b = common.get_book(s, c.book_id)
        stats = common.book_stats(s, c.book_id)
        n_cards = len(common.cards(s, c.book_id))
        n_nodes = len(common.outline_nodes(s, c.book_id))
        data = {"title": b.title, "genre": b.genre, "gender": common.GENDER_LABEL.get(b.gender, b.gender), "tagline": b.tagline,
                "premise": b.premise, "status": b.status, "chapter_words": b.chapter_words, "stats": stats,
                "cards": n_cards, "outline_nodes": n_nodes, "auto_apply": bool(b.agent_auto_apply),
                "banned_tropes": [t["name"] for t in tropes.tropes_for(s, b)]}
    return ToolResult(data, f"《{data['title']}》：{stats['chapters']} 章已提交，{n_cards} 张设定卡，{n_nodes} 个大纲节点")


def _card_brief(cd: Card) -> dict[str, Any]:
    return {"id": cd.id, "type": cd.type, "name": cd.name, "summary": _clip(cd.summary, 160)}


def t_search_bible(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    q = str(a.get("query") or "").strip()
    typ = str(a.get("type") or "").strip() or None
    with session_scope() as s:
        rows = common.cards(s, c.book_id, typ)
    if q:
        words = [w for w in q.replace("，", " ").replace(",", " ").split() if w]
        rows = [r for r in rows if any(w in f"{r.name}\n{r.summary}\n{json.dumps(r.data or {}, ensure_ascii=False)}" for w in words)]
    out = [_card_brief(r) for r in rows[:30]]
    return ToolResult({"count": len(rows), "cards": out}, f"设定库{('里含「' + q + '」的') if q else ''}共 {len(rows)} 张卡")


def _find_card(s: Any, book_id: int, a: dict[str, Any]) -> Card:
    cid = _int(a.get("card_id"))
    if cid:
        cd = s.get(Card, cid)
        if cd is not None and cd.book_id == book_id:
            return cd
    name = str(a.get("name") or "").strip()
    for cd in common.cards(s, book_id):
        if name and (cd.name == name):
            return cd
    for cd in common.cards(s, book_id):
        if name and name in cd.name:
            return cd
    raise NotFound(f"没有找到设定卡「{name or cid}」")


def t_get_card(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        cd = _find_card(s, c.book_id, a)
        d = bible_ops.card_dict(cd)
    return ToolResult(d, f"读取设定卡「{d['name']}」")


def t_get_outline(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    level = str(a.get("level") or "").strip() or None
    with session_scope() as s:
        nodes = common.outline_nodes(s, c.book_id)
    order = {"book": 0, "volume": 1, "arc": 2, "chapter": 3}
    nodes = sorted(nodes, key=lambda n: (order.get(n.level, 9), n.order))
    if level:
        nodes = [n for n in nodes if n.level == level]
    rows = [{"id": n.id, "level": n.level, "order": n.order, "parent_id": n.parent_id, "title": n.title,
             "summary": _clip(n.summary, 120), "status": n.status} for n in nodes[:80]]
    return ToolResult({"count": len(nodes), "nodes": rows}, f"大纲{level or ''}共 {len(nodes)} 个节点")


def t_get_outline_node(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        n = s.get(OutlineNode, _int(a.get("node_id"), 0))
        if n is None or n.book_id != c.book_id:
            raise NotFound("大纲节点不存在")
        d = {"id": n.id, "level": n.level, "order": n.order, "title": n.title, "summary": n.summary, "beats": n.beats,
             "status": n.status, "versions": len(n.versions or [])}
    return ToolResult(d, f"读取大纲节点「{d['title']}」")


def t_list_chapters(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        rows = list(s.exec(select(Chapter).where(Chapter.book_id == c.book_id).order_by(Chapter.number)))
    out = [{"id": r.id, "number": r.number, "title": r.title, "status": r.status, "words": r.words, "summary": _clip(r.summary, 100)}
           for r in rows]
    return ToolResult({"count": len(rows), "chapters": out[-60:]}, f"共 {len(rows)} 章（含草稿）")


def _find_chapter(s: Any, book_id: int, a: dict[str, Any]) -> Chapter:
    cid = _int(a.get("chapter_id"))
    if cid:
        ch = s.get(Chapter, cid)
        if ch is not None and ch.book_id == book_id:
            return ch
    num = _int(a.get("number"))
    if num is not None:
        ch = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number == num)).first()
        if ch is not None:
            return ch
    raise NotFound(f"没有找到第 {num or cid} 章")


def t_get_chapter(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    part = str(a.get("part") or "summary")
    with session_scope() as s:
        ch = _find_chapter(s, c.book_id, a)
        d: dict[str, Any] = {"id": ch.id, "number": ch.number, "title": ch.title, "status": ch.status, "words": ch.words,
                             "summary": ch.summary}
        if part == "full":
            d["content"] = _clip(ch.content, 8000)
        elif part == "excerpt":
            d["opening"] = _clip(ch.content[:600], 600)
            d["ending"] = ch.content[-400:]
        if ch.lint:
            d["ai_score"] = (ch.lint or {}).get("ai_score")
    return ToolResult(d, f"读取第 {d['number']} 章《{d['title']}》（{'正文' if part == 'full' else '摘要'}）")


def t_list_foreshadows(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    st = str(a.get("status") or "").strip()
    with session_scope() as s:
        rows = list(s.exec(select(Foreshadow).where(Foreshadow.book_id == c.book_id).order_by(Foreshadow.id)))
        planned = fs_svc.outline_planned(s, c.book_id)
    if st:
        rows = [r for r in rows if r.status == st]
    out = [{"id": r.id, "desc": r.desc, "status": r.status, "tier": r.tier, "planted_ch": r.planted_ch, "resolved_ch": r.resolved_ch,
            "plan_plant_ch": r.plan_plant_ch, "plan_resolve_ch": r.plan_resolve_ch} for r in rows[:60]]
    return ToolResult({"count": len(rows), "foreshadows": out, "outline_planned": planned[:20]}, f"伏笔 {len(rows)} 条")


def t_get_style(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        st = common.get_style(s, c.book_id)
        d = {"pov": st.pov, "tone": st.tone, "voice_notes": st.voice_notes, "sample_excerpt": _clip(st.sample_text, 800),
             "extracted": st.extracted}
    return ToolResult(d, "读取文风卡" + ("" if st.sample_text else "（还没有范文）"))


def t_get_package(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        p = s.get(Package, c.book_id)
        d = {"titles": [t.get("title") for t in (p.titles if p else [])][:12], "blurb": p.blurb if p else "",
             "tags": list(p.tags or []) if p else [], "cover_prompt": p.cover_prompt if p else "",
             "covers": len(p.covers or []) if p else 0, "chosen_cover": p.chosen_cover if p else None}
    return ToolResult(d, "读取包装（书名候选、简介、标签、封面）")


def t_banned_tropes(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        tl = tropes.tropes_for(s, common.get_book(s, c.book_id))
    return ToolResult({"banned": tl}, f"禁用套路 {len(tl)} 类")


def t_find_mentions(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    terms = [str(t) for t in (a.get("terms") or []) if str(t).strip()]
    with session_scope() as s:
        imp = book_edit.impact(s, c.book_id, terms)
    return ToolResult(imp, f"「{'、'.join(imp['terms'])}」出现在 {len(imp['cards'])} 张设定卡、{len(imp['outline'])} 个大纲节点、{len(imp['chapters'])} 章正文")


def t_web_search(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    q = str(a.get("query") or "").strip()
    if not q:
        raise ValueError("搜索问题不能为空")
    gw = get_gateway()
    with session_scope() as s:
        mock = is_mock_mode(s)
    if mock:
        ans = f"（演示数据）关于「{q[:30]}」：mock 模式没有联网，这里只演示搜索结果的样子。配置渠道并在「任务路由 → 联网搜索」选好模型后会真实检索。"
        return ToolResult({"query": q, "answer": ans, "mock": True}, f"联网搜索「{q[:20]}」（演示）")
    if not gw.has_search():
        return ToolResult({"query": q, "error": "没有配置联网搜索模型（设置 → 任务路由 → 联网搜索）"}, "没有配置联网搜索模型", ok=False)
    c.progress(f"联网搜索：{q[:20]}")
    ans = gw.search(q, "") or ""
    return ToolResult({"query": q, "answer": _clip(ans, 2000)}, f"联网搜索「{q[:20]}」")


# ================================================================== 改工具（产出提案）

def _proposal_result(c: ToolCtx, p: Any, extra: dict[str, Any] | None = None) -> ToolResult:
    st = {"pending": "等作者采纳", "applied": "已自动采纳（可撤回）", "running": "已自动开始执行", "failed": "失败"}.get(p.status, p.status)
    data = {"proposal_id": p.id, "status": p.status, "title": p.title, "change": p.summary, "note": st, **(extra or {})}
    if p.error:
        data["error"] = p.error
    if p.needs_review:
        data["note"] = "有设定冲突，需要作者逐条审阅后才写入"
    if p.destructive:
        data["note"] = "删除类操作，必须作者确认"
    jobs = [p.job_id] if p.job_id else []
    return ToolResult(data, f"提案 #{p.id}「{p.title}」— {data['note']}", proposal_ids=[p.id], job_ids=jobs)


def t_revise_book_info(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    ins = str(a.get("instruction") or "").strip()
    if not ins:
        raise ValueError("instruction 不能为空")
    r = book_edit.revise_info(c.book_id, ins, None, _SubCtx(c, "改作品信息"))
    changed = [k for k in book_edit.INFO_FIELDS if r["proposal"][k] != r["current"][k]]
    label = {"title": "书名", "tagline": "一句话简介", "premise": "核心设定"}
    p = props.create(c.book_id, c.session_id, "book_info", "改" + "、".join(label[k] for k in changed) if changed else "作品信息（无改动）",
                     r.get("change") or "", {**r, "impact": {k: r["impact"][k] for k in ("terms", "total")} | {
                         "cards": r["impact"]["cards"][:20], "outline": r["impact"]["outline"][:20], "chapters": r["impact"]["chapters"][:20]}})
    return _proposal_result(c, p, {"proposal": r["proposal"], "terms": r["terms"], "replacements": r["replacements"],
                                   "impact": {"cards": len(r["impact"]["cards"]), "outline": len(r["impact"]["outline"]),
                                              "chapters": [x["number"] for x in r["impact"]["chapters"]]}})


def _bible_proposal(c: ToolCtx, r: dict[str, Any], title: str) -> Any:
    review = any(x.get("conflicts") for x in r.get("items") or [])
    r = {**r, "needs_review": review}
    summ = f"新增 {r['counts']['add']} 张，需审阅 {r['counts']['review']} 张" + (f"，建议删除 {r['counts']['removals']} 张旧卡" if r["counts"]["removals"] else "")
    return props.create(c.book_id, c.session_id, "bible", title, (r.get("change") or "") + "；" + summ, r,
                        destructive=bool(r.get("removals")), needs_review=review)


def t_propose_bible(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    mode = str(a.get("mode") or "optimize")
    if mode not in bible_ops.MODES:
        raise ValueError("mode 只能是 rewrite / add / optimize")
    ins = str(a.get("instruction") or "").strip()
    names = [str(x) for x in (a.get("card_names") or []) if str(x).strip()]
    ids: list[int] | None = None
    if names and mode == "optimize":
        with session_scope() as s:
            ids = [_find_card(s, c.book_id, {"name": n}).id or 0 for n in names]
    r = bible_ops.propose(c.book_id, mode, ins, None, _SubCtx(c, f"设定库{bible_ops.MODE_LABEL[mode]}"), card_ids=ids)
    if not r["items"] and not r["removals"]:
        return ToolResult({"note": "AI 认为设定库不需要改动"}, "设定库没有需要改的地方")
    p = _bible_proposal(c, r, f"设定库{bible_ops.MODE_LABEL[mode]}")
    return _proposal_result(c, p, {"items": [{"name": x["card"]["name"], "action": x["action"], "conflicts": len(x["conflicts"])} for x in r["items"]][:20]})


def t_sync_downstream(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    ins = str(a.get("instruction") or "").strip()
    terms = [str(t) for t in (a.get("terms") or []) if str(t).strip()]
    reps = {str(k): str(v or "") for k, v in (a.get("replacements") or {}).items()} if isinstance(a.get("replacements"), dict) else {}
    targets = [t for t in (a.get("targets") or ["bible", "outline"]) if t in ("bible", "outline")] or ["bible", "outline"]
    if not terms:
        raise ValueError("terms 不能为空：先用 find_mentions 或 revise_book_info 拿到要同步的词")
    r = book_edit.sync_downstream(c.book_id, ins, terms, reps, targets, None, _SubCtx(c, "同步设定库和大纲"))
    pids: list[int] = []
    out: dict[str, Any] = {"chapters_mentioning": [x["number"] for x in r.get("chapters") or []]}
    lines = []
    if r.get("bible") and (r["bible"]["items"] or r["bible"]["removals"]):
        p = _bible_proposal(c, r["bible"], "同步设定库：" + "、".join(terms[:3]))
        pids.append(p.id or 0)
        out["bible_proposal"] = {"id": p.id, "status": p.status, "needs_review": p.needs_review}
        lines.append(f"设定库提案 #{p.id}")
    items = (r.get("outline") or {}).get("items") or []
    if items:
        p = props.create(c.book_id, c.session_id, "outline_nodes", f"同步大纲 {len(items)} 个节点", "；".join(x["reason"] for x in items if x.get("reason"))[:200],
                         {"instruction": ins, "items": items})
        pids.append(p.id or 0)
        out["outline_proposal"] = {"id": p.id, "status": p.status}
        lines.append(f"大纲提案 #{p.id}")
    if not pids:
        return ToolResult({**out, "note": "设定库和大纲里没有需要同步的地方"}, "设定库和大纲都不用改")
    return ToolResult({**out, "proposal_ids": pids}, "同步：" + "，".join(lines) + (f"；正文第 {out['chapters_mentioning'][:6]} 章还在用旧说法" if out["chapters_mentioning"] else ""),
                      proposal_ids=pids)


def t_delete_card(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        cd = _find_card(s, c.book_id, a)
        info = bible_ops.card_dict(cd)
    p = props.create(c.book_id, c.session_id, "card_delete", f"删除设定卡「{info['name']}」", str(a.get("reason") or ""),
                     {"card_id": info["id"], "name": info["name"], "card": info}, destructive=True)
    return _proposal_result(c, p)


def t_suggest_outline_node(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    nid = _int(a.get("node_id"), 0) or 0
    with session_scope() as s:
        n = s.get(OutlineNode, nid)
        if n is None or n.book_id != c.book_id:
            raise NotFound("大纲节点不存在")
        level = n.level
    r = outline.suggest_node(nid, str(a.get("instruction") or ""), None, _SubCtx(c, "重写大纲节点"))
    item = {"node_id": nid, "level": level, "old": r["current"], "new": r["proposal"], "reason": r.get("change") or ""}
    p = props.create(c.book_id, c.session_id, "outline_nodes", f"重写大纲「{r['current']['title'][:20]}」", r.get("change") or "",
                     {"instruction": r["instruction"], "items": [item]})
    return _proposal_result(c, p, {"new": r["proposal"]})


def t_rewrite_chapter(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    with session_scope() as s:
        ch = _find_chapter(s, c.book_id, a)
        cid, num, title = ch.id or 0, ch.number, ch.title
    ins = str(a.get("instruction") or "").strip()
    if not ins:
        raise ValueError("instruction 不能为空")
    r = writing.rewrite_chapter_job(cid, ins, None, "all", None, None, _SubCtx(c, f"改写第 {num} 章"))
    if not r["changed"]:
        return ToolResult({"note": "改写稿和原文一样"}, f"第 {num} 章没有需要改的地方")
    p = props.create(c.book_id, c.session_id, "chapter_rewrite", f"改写第 {num} 章《{title}》",
                     f"{r['words_before']} → {r['words_after']} 字，AI 味 {r['ai_score_after']}",
                     {"chapter_id": cid, "number": num, "title": title, "instruction": ins, "before": r["before"], "after": r["after"],
                      "words_before": r["words_before"], "words_after": r["words_after"], "ai_score_after": r["ai_score_after"]})
    return _proposal_result(c, p, {"words_before": r["words_before"], "words_after": r["words_after"]})


def t_plan_foreshadows(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    r = fs_svc.plan(c.book_id, str(a.get("instruction") or ""), None, _int(a.get("count"), 3) or 3, _SubCtx(c, "规划伏笔"))
    items = [x for x in r["items"] if not x.get("duplicate_of")] or r["items"]
    p = props.create(c.book_id, c.session_id, "foreshadow_add", f"规划 {len(items)} 条伏笔", "；".join(x["desc"] for x in items)[:200],
                     {"items": items, "attach": bool(a.get("attach", True))})
    return _proposal_result(c, p, {"items": [{"desc": x["desc"], "tier": x["tier"], "plant_ch": x["plant_ch"], "resolve_ch": x["resolve_ch"]} for x in items]})


def t_add_foreshadow(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    desc = str(a.get("desc") or "").strip()
    if not desc:
        raise ValueError("desc 不能为空")
    item = {"desc": desc, "tier": a.get("tier") or "", "plant_ch": _int(a.get("plant_ch")), "resolve_ch": _int(a.get("resolve_ch")),
            "note": str(a.get("note") or ""), "source": "ai"}
    p = props.create(c.book_id, c.session_id, "foreshadow_add", f"新增伏笔：{desc[:20]}", item["note"][:200],
                     {"items": [item], "attach": bool(a.get("attach", False))})
    return _proposal_result(c, p)


def t_update_foreshadow(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    fid = _int(a.get("id"), 0) or 0
    with session_scope() as s:
        f = s.get(Foreshadow, fid)
        if f is None or f.book_id != c.book_id:
            raise NotFound("伏笔不存在")
        before = props.fs_row(f)
    changes = {k: a[k] for k in props.FS_FIELDS if k in a and k != "id"}
    if not changes:
        raise ValueError("没有要改的字段")
    p = props.create(c.book_id, c.session_id, "foreshadow_update", f"修改伏笔：{before['desc'][:20]}",
                     "；".join(f"{k}: {before.get(k)} → {v}" for k, v in changes.items())[:300],
                     {"id": fid, "before": {k: before[k] for k in changes}, "changes": changes})
    return _proposal_result(c, p)


def t_delete_foreshadow(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    fid = _int(a.get("id"), 0) or 0
    with session_scope() as s:
        f = s.get(Foreshadow, fid)
        if f is None or f.book_id != c.book_id:
            raise NotFound("伏笔不存在")
        row = props.fs_row(f)
    p = props.create(c.book_id, c.session_id, "foreshadow_delete", f"删除伏笔：{row['desc'][:20]}", str(a.get("reason") or ""),
                     {"id": fid, "row": row}, destructive=True)
    return _proposal_result(c, p)


def t_propose_package(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    after: dict[str, Any] = {}
    if a.get("blurb"):
        after["blurb"] = str(a["blurb"]).strip()
    if isinstance(a.get("tags"), list) and a["tags"]:
        after["tags"] = [str(t).strip() for t in a["tags"] if str(t).strip()][:6]
    if isinstance(a.get("titles"), list) and a["titles"]:
        after["titles"] = [str(t).strip().strip("《》") for t in a["titles"] if str(t).strip()][:12]
    if not after:
        raise ValueError("blurb / tags / titles 至少给一项")
    with session_scope() as s:
        before = props._pkg_now(s, c.book_id)
        tl = tropes.tropes_for(s, common.get_book(s, c.book_id))
    hits = tropes.detect_obj(after, tl)
    label = {"blurb": "简介", "tags": "标签", "titles": "书名候选"}
    p = props.create(c.book_id, c.session_id, "package", "改" + "、".join(label[k] for k in after), str(a.get("reason") or "")[:200],
                     {"before": {k: before[k] for k in after}, "after": after, "trope_hits": hits})
    return _proposal_result(c, p, {"trope_hits": hits})


def t_revise_cover_prompt(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    ins = str(a.get("instruction") or "").strip()
    if not ins:
        raise ValueError("instruction 不能为空")
    r = packaging.revise_cover_prompt(c.book_id, ins, None, None, _SubCtx(c, "改封面提示词"))
    with session_scope() as s:
        before = props._pkg_now(s, c.book_id)["cover_prompt"]
    p = props.create(c.book_id, c.session_id, "package", "改封面提示词", ins[:120],
                     {"before": {"cover_prompt": before}, "after": {"cover_prompt": r["prompt"]}, "instruction": ins})
    return _proposal_result(c, p, {"prompt": r["prompt"]})


def t_generate_covers(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    n = max(1, min(4, _int(a.get("n"), 2) or 2))
    prompt = str(a.get("prompt") or "").strip()
    with session_scope() as s:
        cur = props._pkg_now(s, c.book_id)["cover_prompt"]
    p = props.create(c.book_id, c.session_id, "covers", f"生成 {n} 张封面", _clip(prompt or cur or "用包装里的封面提示词", 160),
                     {"prompt": prompt or None, "n": n, "title_mode": "model" if a.get("title_mode") != "overlay" else "overlay"})
    return _proposal_result(c, p)


def t_write_next_chapter(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    v = max(1, min(3, _int(a.get("variants"), 1) or 1))
    with session_scope() as s:
        pending = s.exec(select(Chapter).where(Chapter.book_id == c.book_id, Chapter.status != "committed")).first()
        nxt = outline.next_chapter_node(s, c.book_id)
        last = fs_svc.last_committed(s, c.book_id)
    if pending is not None:
        return ToolResult({"error": f"第 {pending.number} 章还是草稿，先让作者选定版本并提交"}, f"第 {pending.number} 章还没提交，不能写下一章", ok=False)
    title = f"写第 {nxt.order if nxt else last + 1} 章" + (f"《{nxt.title}》" if nxt else "") + (f"（{v} 个版本）" if v > 1 else "")
    p = props.create(c.book_id, c.session_id, "write_chapter", title, "按章细纲写作 → 审稿 → 人味检查 → 定点修改，写完是草稿，提交前不入账",
                     {"variants": v, "number": nxt.order if nxt else last + 1})
    return _proposal_result(c, p)


def t_imitate_rank_book(c: ToolCtx, a: dict[str, Any]) -> ToolResult:
    """v0.7：拆解一本榜单书（只学结构）并出 3 个换皮选题，产出提案；采纳后存进选题库。"""
    from app.services import imitate

    rid = _int(a.get("rank_item_id")) or imitate.find_rank_item(str(a.get("title") or ""))
    if not rid:
        raise NotFound(f"最新榜单里没有找到《{a.get('title') or a.get('rank_item_id') or ''}》")
    c.progress("拆解榜单书")
    pv = imitate.reskin_preview(rid)
    ideas = pv["ideas"]
    warns = [f"《{x['title']}》：{w}" for x in ideas for w in x["source"]["warnings"]]
    p = props.create(c.book_id, c.session_id, "reskin_ideas", f"仿《{pv['ref_title']}》出 {len(ideas)} 个换皮选题",
                     "；".join(f"《{x['title']}》{x['logline'][:30]}" for x in ideas)[:400],
                     {"rank_item_id": pv["rank_item_id"], "teardown_id": pv["teardown_id"], "ref_title": pv["ref_title"],
                      "teardown": pv["teardown"], "ideas": ideas, "warnings": warns})
    return _proposal_result(c, p, {"teardown": {k: pv["teardown"].get(k) for k in ("payoff_formula", "golden_finger", "transferable", "must_replace")},
                                   "ideas": [{"title": x["title"], "logline": x["logline"], "warnings": x["source"]["warnings"]} for x in ideas]})


# ================================================================== 注册表

TOOLS: list[Tool] = [
    Tool("get_book_info", "读作品信息", "read", "读取本书的书名、题材、一句话简介、核心设定、进度、自动采纳开关和禁用套路。", {}, [], t_book_info),
    Tool("search_bible", "检索设定库", "read", "按关键词（空格分隔，任一命中）或类型检索设定卡，返回 id、类型、名称、简介。",
         {"query": {**S, "description": "关键词，可空"}, "type": {**S, "enum": ["world", "cheat", "power", "faction", "character", "item", "location"]}}, [], t_search_bible),
    Tool("get_card", "读设定卡", "read", "读取一张设定卡的完整内容（含 data）。", {"card_id": I, "name": S}, [], t_get_card),
    Tool("get_outline", "读大纲树", "read", "读取大纲节点列表（总纲/卷/弧/章细纲），可按 level 过滤。",
         {"level": {**S, "enum": ["book", "volume", "arc", "chapter"]}}, [], t_get_outline),
    Tool("get_outline_node", "读大纲节点", "read", "读取一个大纲节点的完整内容（含章细纲节拍 beats）。", {"node_id": I}, ["node_id"], t_get_outline_node),
    Tool("list_chapters", "列章节", "read", "列出所有章节（章号、标题、状态、字数、摘要）。", {}, [], t_list_chapters),
    Tool("get_chapter", "读章节", "read", "读取一章：part=summary 只要摘要，excerpt 开头结尾，full 全文（最多 8000 字）。",
         {"number": I, "chapter_id": I, "part": {**S, "enum": ["summary", "excerpt", "full"]}}, [], t_get_chapter),
    Tool("list_foreshadows", "读伏笔", "read", "列出伏笔（可按状态过滤），以及章细纲里已安排但还没入账的伏笔。",
         {"status": {**S, "enum": ["planned", "planted", "advancing", "resolved", "dropped"]}}, [], t_list_foreshadows),
    Tool("get_style", "读文风", "read", "读取文风卡（人称、基调、范文摘录、提炼结果）。", {}, [], t_get_style),
    Tool("get_package", "读包装", "read", "读取书名候选、简介、标签、封面提示词。", {}, [], t_get_package),
    Tool("get_banned_tropes", "读禁用套路", "read", "读取本书生效的禁用套路清单（全局 + 本书追加）。", {}, [], t_banned_tropes),
    Tool("find_mentions", "查影响范围", "read", "查哪些设定卡、大纲节点、章节正文里出现了这些词（改名、拿掉某个说法前先查）。",
         {"terms": {"type": "array", "items": S}}, ["terms"], t_find_mentions),
    Tool("web_search", "联网搜索", "read", "用设置里配置的联网搜索模型查现实资料（历史、地理、职业、规则等），没配置会返回提示。",
         {"query": S}, ["query"], t_web_search),
    Tool("revise_book_info", "改作品信息", "write", "按要求改书名 / 一句话简介 / 核心设定，产出提案，并返回受影响的词和下游范围（可接着 sync_downstream）。",
         {"instruction": {**S, "description": "作者的修改要求，原话或整理后的要求"}}, ["instruction"], t_revise_book_info),
    Tool("sync_downstream", "同步设定和大纲", "write", "把改名/拿掉某个说法同步到设定库（走冲突审阅）和大纲（逐条勾选），各产出一个提案。",
         {"instruction": S, "terms": {"type": "array", "items": S, "description": "要同步处理的旧说法"},
          "replacements": {"type": "object", "description": "改名对照 {旧词: 新词}，拿掉的词给空字符串"},
          "targets": {"type": "array", "items": {**S, "enum": ["bible", "outline"]}}}, ["instruction", "terms"], t_sync_downstream),
    Tool("propose_bible", "改设定库", "write", "设定库三种模式：rewrite 完全重写 / add 纯增加 / optimize 优化（可用 card_names 限定只改哪些卡）。冲突会进入冲突审阅。",
         {"mode": {**S, "enum": ["rewrite", "add", "optimize"]}, "instruction": S, "card_names": {"type": "array", "items": S}}, ["mode", "instruction"], t_propose_bible),
    Tool("delete_card", "删设定卡", "write", "删除一张设定卡（删除类操作，永远需要作者确认）。", {"card_id": I, "name": S, "reason": S}, [], t_delete_card),
    Tool("suggest_outline_node", "改大纲节点", "write", "按要求重写一个大纲节点的标题和概要，产出提案。", {"node_id": I, "instruction": S}, ["node_id", "instruction"], t_suggest_outline_node),
    Tool("rewrite_chapter", "改写章节", "write", "按要求改写一整章正文（节奏、对话、删情节、换说法等），产出带逐段对比的提案。",
         {"number": I, "chapter_id": I, "instruction": S}, ["instruction"], t_rewrite_chapter),
    Tool("plan_foreshadows", "规划伏笔", "write", "读大纲和设定让 AI 规划长短线伏笔，产出提案（attach=true 时采纳后同时写进对应章细纲）。",
         {"instruction": S, "count": I, "attach": {"type": "boolean"}}, [], t_plan_foreshadows),
    Tool("add_foreshadow", "加伏笔", "write", "新增一条伏笔（计划中），产出提案。",
         {"desc": S, "tier": {**S, "enum": ["short", "mid", "long"]}, "plant_ch": I, "resolve_ch": I, "note": S, "attach": {"type": "boolean"}}, ["desc"], t_add_foreshadow),
    Tool("update_foreshadow", "改伏笔", "write", "修改一条伏笔的内容、状态或计划章节，产出提案。",
         {"id": I, "desc": S, "status": {**S, "enum": ["planned", "planted", "advancing", "resolved", "dropped"]}, "tier": S,
          "plan_plant_ch": I, "plan_resolve_ch": I, "resolved_ch": I, "note": S}, ["id"], t_update_foreshadow),
    Tool("delete_foreshadow", "删伏笔", "write", "删除一条伏笔（删除类操作，永远需要作者确认）。", {"id": I, "reason": S}, ["id"], t_delete_foreshadow),
    Tool("propose_package", "改简介/包装", "write", "由你直接写好新的简介、标签或书名候选，产出提案（不会改正式书名，正式书名用 revise_book_info）。",
         {"blurb": S, "tags": {"type": "array", "items": S}, "titles": {"type": "array", "items": S}, "reason": S}, [], t_propose_package),
    Tool("revise_cover_prompt", "改封面提示词", "write", "按要求改封面生图提示词，产出提案。", {"instruction": S}, ["instruction"], t_revise_cover_prompt),
    Tool("generate_covers", "生成封面", "write", "调用生图模型生成封面（长任务，采纳后执行）。prompt 不填就用包装里的封面提示词。",
         {"prompt": S, "n": I, "title_mode": {**S, "enum": ["model", "overlay"]}}, [], t_generate_covers),
    Tool("write_next_chapter", "写下一章", "write", "按章细纲写下一章（长任务，采纳后执行；可写 1–3 个版本供挑选）。写完是草稿，作者提交才入账。",
         {"variants": I}, [], t_write_next_chapter),
    Tool("imitate_rank_book", "拆解榜单书并出仿写选题", "write",
         "拆解一本热榜书（只用书名/简介/标签/热度，只学结构：爽点公式、金手指兑现、人设模板、可迁移要素、必须换掉的元素），"
         "再出 3 个换皮选题（带相似点自检），产出提案；采纳后存进选题库，不改当前这本书。用 rank_item_id 或书名指定。",
         {"rank_item_id": I, "title": {**S, "description": "榜单书名（在最新榜单里查找）"}}, [], t_imitate_rank_book),
]
BY_NAME = {t.name: t for t in TOOLS}


def specs() -> list[dict[str, Any]]:
    return [t.spec() for t in TOOLS]


def catalog() -> list[dict[str, Any]]:
    return [{"name": t.name, "label": t.label, "kind": t.kind, "description": t.description} for t in TOOLS]


def dispatch(c: ToolCtx, name: str, args: dict[str, Any]) -> ToolResult:
    """执行一次工具调用。参数错误、找不到对象、服务报错都转成结果返回给模型，不中断循环。"""
    t = BY_NAME.get(name)
    if t is None:
        return ToolResult({"error": f"没有这个工具：{name}"}, f"未知工具 {name}", ok=False)
    c.progress(f"调用「{t.label}」")
    try:
        return t.fn(c, args if isinstance(args, dict) else {})
    except (NotFound, ValueError, common.Conflict) as e:
        return ToolResult({"error": str(e)}, f"{t.label}失败：{e}", ok=False)
    except Exception as e:  # noqa: BLE001
        return ToolResult({"error": f"{type(e).__name__}: {e}"[:300]}, f"{t.label}出错：{str(e)[:60]}", ok=False)
