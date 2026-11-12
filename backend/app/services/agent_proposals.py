"""Agent 提案：改动类工具只产出提案，作者采纳才写入；书级「自动采纳」打开时直接写入，但仍可撤回。

写入与撤回全部复用 v0.4 已有的服务：
- 作品信息：book_edit.apply_info / undo_info（旧版本栈）
- 设定库：bible_ops.apply（先存快照，冲突走冲突审阅）/ bible_ops.restore（按快照回滚）
- 大纲：outline.apply_nodes / undo_node（节点旧版本栈）
- 章节改写：writing.apply_rewrite / undo_chapter（history）
- 伏笔：foreshadows.add_batch / update / delete
- 包装：Package 字段（旧值存在提案里）
- 长任务（写下一章、生图）：提交现有 Job，提案状态跟着任务走

删除类提案（destructive）永远需要作者确认，不受自动采纳影响；有设定冲突的提案（needs_review）也不会自动写入。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext, submit
from app.models.tables import (
    AgentProposal, Chapter, Foreshadow, Job, OutlineNode, Package, utcnow,
)
from app.services import bible_ops, book_edit, common, outline, packaging, writing
from app.services import foreshadows as fs_svc
from app.services.common import Conflict, NotFound

KIND_LABEL = {
    "book_info": "作品信息",
    "bible": "设定库",
    "card_delete": "删除设定卡",
    "outline_nodes": "大纲",
    "chapter_rewrite": "章节改写",
    "foreshadow_add": "新增伏笔",
    "foreshadow_update": "修改伏笔",
    "foreshadow_delete": "删除伏笔",
    "package": "包装",
    "covers": "生成封面",
    "write_chapter": "写下一章",
}
JOB_KINDS = ("covers", "write_chapter")


def _digest(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ 输出

def proposal_out(p: AgentProposal) -> dict[str, Any]:
    from app.api.schemas import iso

    return {
        "id": p.id, "book_id": p.book_id, "session_id": p.session_id, "message_id": p.message_id, "kind": p.kind,
        "kind_label": KIND_LABEL.get(p.kind, p.kind), "title": p.title, "summary": p.summary, "payload": p.payload or {},
        "status": p.status, "destructive": p.destructive, "needs_review": p.needs_review, "auto_applied": p.auto_applied,
        "result": p.result, "error": p.error, "job_id": p.job_id,
        "revertible": p.status == "applied" and p.kind in _REVERT,
        "created_at": iso(p.created_at), "updated_at": iso(p.updated_at),
    }


def _get(s: Session, pid: int) -> AgentProposal:
    p = s.get(AgentProposal, pid)
    if p is None:
        raise NotFound("提案不存在")
    return p


def _set(pid: int, **fields: Any) -> AgentProposal:
    with session_scope() as s:
        p = _get(s, pid)
        for k, v in fields.items():
            setattr(p, k, v)
        p.updated_at = utcnow()
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


# ------------------------------------------------------------------ 创建（可能自动采纳）

def create(book_id: int, session_id: int, kind: str, title: str, summary: str, payload: dict[str, Any],
           destructive: bool = False, needs_review: bool = False) -> AgentProposal:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        auto = bool(book.agent_auto_apply)
        p = AgentProposal(book_id=book_id, session_id=session_id, kind=kind, title=title[:80], summary=summary[:600],
                          payload=payload, destructive=destructive, needs_review=needs_review)
        s.add(p)
        s.commit()
        s.refresh(p)
    if auto and not destructive and not needs_review:
        try:
            out = apply(p.id or 0, auto=True)
            p = out["proposal_obj"]
        except (Conflict, NotFound, ValueError) as e:
            p = _set(p.id or 0, error=f"自动采纳失败：{e}")
    return p


# ------------------------------------------------------------------ 采纳

def apply(pid: int, edited: dict[str, Any] | None = None, ops: list[dict[str, Any]] | None = None, auto: bool = False) -> dict[str, Any]:
    """采纳提案。edited：作者在卡片里改过的内容（编辑后采纳）；ops：设定库冲突审阅里作者的逐条选择。"""
    with session_scope() as s:
        p = _get(s, pid)
        if p.status not in ("pending", "failed"):
            raise Conflict(f"这个提案已经{STATUS_LABEL.get(p.status, p.status)}")
        kind, book_id, payload = p.kind, p.book_id, dict(p.payload or {})
        common.get_book(s, book_id)
    fn = _APPLY.get(kind)
    if fn is None:
        raise ValueError(f"不支持的提案类型：{kind}")
    if kind == "bible" and ops is None and (payload.get("needs_review") or _bible_has_review(payload)):
        raise Conflict("这个设定提案和已有设定有冲突，请先逐条审阅")
    job_id: int | None = None
    if kind in JOB_KINDS:
        job_id = fn(pid, book_id, payload, edited)
        p = _set(pid, status="running", job_id=job_id, auto_applied=auto, error="")
    else:
        result = fn(book_id, payload, edited, ops) if kind == "bible" else fn(book_id, payload, edited)
        p = _set(pid, status="applied", result=result, auto_applied=auto, error="")
    return {"proposal": proposal_out(p), "proposal_obj": p, "job_id": job_id}


STATUS_LABEL = {"applied": "采纳过了", "rejected": "拒绝过了", "reverted": "撤回过了", "running": "在执行中"}


def reject(pid: int) -> AgentProposal:
    with session_scope() as s:
        p = _get(s, pid)
        if p.status not in ("pending", "failed"):
            raise Conflict(f"这个提案已经{STATUS_LABEL.get(p.status, p.status)}")
    return _set(pid, status="rejected")


def revert(pid: int) -> AgentProposal:
    with session_scope() as s:
        p = _get(s, pid)
        if p.status != "applied":
            raise Conflict("只有已采纳的提案可以撤回")
        kind, book_id, payload, result = p.kind, p.book_id, dict(p.payload or {}), dict(p.result or {})
    fn = _REVERT.get(kind)
    if fn is None:
        raise ValueError("这个提案不支持撤回")
    info = fn(book_id, payload, result) or {}
    return _set(pid, status="reverted", result={**result, "revert": info})


# ------------------------------------------------------------------ 各类提案：apply / revert

def _apply_book_info(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    prop = {k: v for k, v in {**(payload.get("proposal") or {}), **(edited or {})}.items() if k in book_edit.INFO_FIELDS}
    with session_scope() as s:
        before = book_edit.info_of(common.get_book(s, book_id))
    b = book_edit.apply_info(book_id, prop, "Agent：" + str(payload.get("instruction") or "修改")[:100])
    after = book_edit.info_of(b)
    return {"before": before, "after": after, "changed": after != before}


def _revert_book_info(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("changed"):
        return {"note": "当时没有实际改动"}
    with session_scope() as s:
        cur = book_edit.info_of(common.get_book(s, book_id))
    if cur != result.get("after"):
        raise Conflict("作品信息之后又改过，请到概览页「编辑信息」里按历史版本撤回")
    book_edit.undo_info(book_id)
    return {"undone": True}


def _bible_has_review(payload: dict[str, Any]) -> bool:
    return any(x.get("conflicts") for x in payload.get("items") or [])


def bible_default_ops(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """没有冲突时的默认写入：新增卡建出来，无冲突的改写写进旧卡。删除（重写模式下没对应的旧卡）不在默认里。"""
    ops: list[dict[str, Any]] = []
    for x in payload.get("items") or []:
        if x.get("conflicts"):
            continue
        if x.get("action") == "update" and x.get("target_id"):
            ops.append({"op": "update", "card_id": x["target_id"], "card": x["card"]})
        else:
            ops.append({"op": "create", "card": x["card"]})
    return ops


def _apply_bible(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None, ops: list[dict[str, Any]] | None) -> dict[str, Any]:
    use = ops if ops is not None else bible_default_ops(payload)
    if edited and isinstance(edited.get("cards"), dict):  # 编辑后采纳：按 key 覆盖卡内容
        keyed = {x["key"]: x for x in payload.get("items") or []}
        use = []
        for k, card in edited["cards"].items():
            x = keyed.get(k)
            if x is None or x.get("conflicts"):
                continue
            use.append({"op": "update", "card_id": x["target_id"], "card": card} if x.get("action") == "update" and x.get("target_id")
                       else {"op": "create", "card": card})
    if not use:
        raise ValueError("没有要写入的设定")
    r = bible_ops.apply(book_id, str(payload.get("mode") or "optimize"), "Agent：" + str(payload.get("instruction") or "")[:60], use,
                        payload.get("facts") if ops is None or payload.get("mode") == "rewrite" else None)
    return {**r, "ops": len(use)}


def _revert_snapshot(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    sid = result.get("snapshot_id")
    if not sid:
        raise Conflict("没有找到写入前的快照")
    return bible_ops.restore(book_id, int(sid))


def _apply_card_delete(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    return bible_ops.apply(book_id, "delete", f"Agent 删除设定卡「{payload.get('name', '')}」", [{"op": "delete", "card_id": payload.get("card_id")}])


def _apply_outline(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    over = {int(x["node_id"]): x for x in ((edited or {}).get("items") or []) if isinstance(x, dict) and x.get("node_id")}
    items = []
    for it in payload.get("items") or []:
        new = dict(it.get("new") or {})
        if it["node_id"] in over:
            new.update({k: v for k, v in over[it["node_id"]].items() if k in ("title", "summary") and v is not None})
            if over[it["node_id"]].get("skip"):
                continue
        items.append({"node_id": it["node_id"], **new})
    r = outline.apply_nodes(book_id, items, "Agent：" + str(payload.get("instruction") or "")[:100])
    return {**r, "nodes": [{"node_id": x["node_id"], "title": x.get("title"), "summary": x.get("summary")} for x in items]}


def _revert_outline(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    undone, skipped = 0, []
    with session_scope() as s:
        cur = {n.id: n for n in common.outline_nodes(s, book_id)}
    for x in result.get("nodes") or []:
        n = cur.get(x["node_id"])
        if n is None:
            continue
        same = (x.get("title") is None or n.title == str(x["title"])[:80]) and (x.get("summary") is None or n.summary == x["summary"])
        if same and n.versions:
            outline.undo_node(n.id or 0)
            undone += 1
        else:
            skipped.append(n.title)
    if not undone and skipped:
        raise Conflict("这些大纲节点之后又改过，请到大纲页逐个撤回：" + "、".join(skipped[:5]))
    return {"undone": undone, "skipped": skipped}


def _apply_chapter(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    cid = int(payload.get("chapter_id") or 0)
    content = str((edited or {}).get("content") or payload.get("after") or "")
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        if ch is None or ch.book_id != book_id:
            raise NotFound("章节不存在")
        if ch.content != payload.get("before"):
            raise Conflict("这一章在提案之后又改过，请让 Agent 按现在的正文重新改")
    ch = writing.apply_rewrite(cid, content, "Agent 改写前：" + str(payload.get("instruction") or "")[:30])
    return {"chapter_id": cid, "words": ch.words, "content_hash": _digest(ch.content)}


def _revert_chapter(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    cid = int(result.get("chapter_id") or 0)
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        if ch is None:
            raise NotFound("章节不存在")
        if _digest(ch.content) != result.get("content_hash"):
            raise Conflict("这一章之后又改过，请到章节页用「撤回」逐步回退")
    writing.undo_chapter(cid)
    return {"undone": True}


def _apply_fs_add(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    items = (edited or {}).get("items") if isinstance((edited or {}).get("items"), list) else payload.get("items") or []
    with session_scope() as s:
        before = {f.id for f in s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id))}
    r = fs_svc.add_batch(book_id, [{**it, "source": it.get("source") or "ai"} for it in items], bool(payload.get("attach")))
    with session_scope() as s:
        new = [f.id for f in s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id)) if f.id not in before]
    return {**r, "ids": new}


def _revert_fs_add(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    removed, descs = 0, set()
    with session_scope() as s:
        for fid in result.get("ids") or []:
            f = s.get(Foreshadow, fid)
            if f is not None and f.book_id == book_id:
                descs.add(f.desc)
                s.delete(f)
                removed += 1
        if payload.get("attach") and descs:  # 写进章细纲的埋设/回收动作一并拿掉
            for n in s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter")):
                beats = dict(n.beats or {})
                fs = [a for a in beats.get("foreshadow") or [] if not (isinstance(a, dict) and a.get("desc") in descs and a.get("id") is None)]
                if n.status != "written" and len(fs) != len(beats.get("foreshadow") or []):
                    beats["foreshadow"] = fs
                    n.beats = beats
                    s.add(n)
        s.commit()
    return {"removed": removed}


FS_FIELDS = ("desc", "status", "tier", "planted_ch", "last_ch", "resolved_ch", "plan_plant_ch", "plan_resolve_ch", "note")


def fs_row(f: Foreshadow) -> dict[str, Any]:
    return {k: getattr(f, k) for k in FS_FIELDS}


def _apply_fs_update(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    changes = {**(payload.get("changes") or {}), **(edited or {})}
    f = fs_svc.update(int(payload["id"]), {k: v for k, v in changes.items() if k in FS_FIELDS})
    return {"id": f.id, "after": fs_row(f)}


def _revert_fs_update(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        f = s.get(Foreshadow, int(payload["id"]))
        if f is None:
            raise NotFound("伏笔已被删除")
        if fs_row(f) != result.get("after"):
            raise Conflict("这条伏笔之后又改过，请到伏笔页手动调整")
        for k, v in (payload.get("before") or {}).items():
            if k in FS_FIELDS:
                setattr(f, k, v)
        s.add(f)
        s.commit()
    return {"restored": True}


def _apply_fs_delete(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    with session_scope() as s:
        f = s.get(Foreshadow, int(payload["id"]))
        if f is None or f.book_id != book_id:
            raise NotFound("伏笔不存在或已删除")
        row = {**fs_row(f), "source": f.source}
    fs_svc.delete(int(payload["id"]))
    return {"row": row}


def _revert_fs_delete(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    row = dict(result.get("row") or {})
    with session_scope() as s:
        f = Foreshadow(book_id=book_id, **{k: row[k] for k in (*FS_FIELDS, "source") if k in row})
        s.add(f)
        s.commit()
        s.refresh(f)
        return {"id": f.id}


PKG_FIELDS = ("blurb", "tags", "titles", "cover_prompt")


def _pkg_now(s: Session, book_id: int) -> dict[str, Any]:
    p = s.get(Package, book_id)
    return {"blurb": p.blurb if p else "", "tags": list(p.tags or []) if p else [], "titles": [t.get("title") for t in (p.titles or [])] if p else [],
            "cover_prompt": p.cover_prompt if p else ""}


def _apply_package(book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    after = {k: v for k, v in {**(payload.get("after") or {}), **(edited or {})}.items() if k in PKG_FIELDS and v is not None}
    with session_scope() as s:
        common.get_book(s, book_id)
        before = _pkg_now(s, book_id)
        p = packaging.get_or_create_package(s, book_id)
        if "blurb" in after:
            p.blurb = str(after["blurb"])
        if "tags" in after:
            p.tags = [str(t) for t in after["tags"]][:6]
        if "cover_prompt" in after:
            p.cover_prompt = str(after["cover_prompt"])
        if "titles" in after:
            p.titles = [{"title": str(t), "score": packaging.score_title(str(t))["total"]} for t in after["titles"] if str(t).strip()][:12]
        s.add(p)
        s.commit()
        now = _pkg_now(s, book_id)
    return {"before": {k: before[k] for k in after}, "after": {k: now[k] for k in after}}


def _revert_package(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        now = _pkg_now(s, book_id)
        if any(now.get(k) != v for k, v in (result.get("after") or {}).items()):
            raise Conflict("包装之后又改过，请到包装发布页手动调整")
    _apply_package(book_id, {"after": result.get("before") or {}}, None)
    return {"restored": list((result.get("before") or {}).keys())}


def _track(pid: int, inner: Callable[[JobContext], dict[str, Any]]) -> Callable[[JobContext], dict[str, Any]]:
    """长任务：任务结束时把结果和状态写回提案。"""
    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            r = inner(ctx) or {}
        except Exception as e:
            _set(pid, status="failed", error=str(e)[:300])
            raise
        _set(pid, status="applied", result=r)
        return r
    return run


def _apply_write(pid: int, book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> int:
    variants = int((edited or {}).get("variants") or payload.get("variants") or 1)
    job = submit("chapter_write_next", _track(pid, lambda ctx: writing.write_next(book_id, ctx, variants)), book_id=book_id, lock_book=True)
    return job.id or 0


def _revert_write(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    cid = int(result.get("chapter_id") or 0)
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        if ch is None:
            return {"note": "章节已经不在了"}
        if ch.status == "committed":
            raise Conflict("这一章已经提交入账，不能撤回")
        for node in s.exec(select(OutlineNode).where(OutlineNode.chapter_id == cid)):
            node.chapter_id = None
            if node.status == "written":
                node.status = "planned"
            s.add(node)
        s.delete(ch)
        s.commit()
    return {"deleted_chapter": cid}


def _apply_covers(pid: int, book_id: int, payload: dict[str, Any], edited: dict[str, Any] | None) -> int:
    prompt = str((edited or {}).get("prompt") or payload.get("prompt") or "") or None
    n = max(1, min(4, int(payload.get("n") or 2)))
    mode = payload.get("title_mode") or "model"
    job = submit("covers_generate", _track(pid, lambda ctx: packaging.generate_covers(book_id, prompt, n, ctx, mode)), book_id=book_id)
    return job.id or 0


def _revert_covers(book_id: int, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    n = 0
    for u in result.get("covers") or []:
        try:
            packaging.delete_cover(book_id, u)
            n += 1
        except ValueError:
            continue
    return {"deleted": n}


_APPLY: dict[str, Callable[..., Any]] = {
    "book_info": _apply_book_info,
    "bible": _apply_bible,
    "card_delete": _apply_card_delete,
    "outline_nodes": _apply_outline,
    "chapter_rewrite": _apply_chapter,
    "foreshadow_add": _apply_fs_add,
    "foreshadow_update": _apply_fs_update,
    "foreshadow_delete": _apply_fs_delete,
    "package": _apply_package,
    "write_chapter": _apply_write,
    "covers": _apply_covers,
}
_REVERT: dict[str, Callable[..., Any]] = {
    "book_info": _revert_book_info,
    "bible": _revert_snapshot,
    "card_delete": _revert_snapshot,
    "outline_nodes": _revert_outline,
    "chapter_rewrite": _revert_chapter,
    "foreshadow_add": _revert_fs_add,
    "foreshadow_update": _revert_fs_update,
    "foreshadow_delete": _revert_fs_delete,
    "package": _revert_package,
    "write_chapter": _revert_write,
    "covers": _revert_covers,
}


def job_state(job_id: int | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    with session_scope() as s:
        j = s.get(Job, job_id)
        return {"id": j.id, "status": j.status, "progress": j.progress, "message": j.message, "error": j.error} if j else None

