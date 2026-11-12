"""每本书的专属 Agent：会话、消息持久化、function calling 循环。

一轮对话 = 一个 agent_run 后台任务：
  组装消息（系统提示 + 历史）→ 模型决定调用哪些工具 → 程序执行工具（读库 / 生成提案）→ 结果回填 → 重复，
  直到模型不再调用工具，或到达步数上限（MAX_STEPS），或作者点了停止。
每一步（assistant 消息、每次工具结果）都立即落库，前端轮询或订阅 SSE 就能一步步看到进展。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext, submit
from app.llm.gateway import get_gateway
from app.models.tables import AgentMessage, AgentProposal, AgentSession, Job, utcnow
from app.services import agent_proposals as props
from app.services import agent_tools, common, tropes
from app.services.common import Conflict, NotFound

log = logging.getLogger("novelos.agent")

MAX_STEPS = 12
HISTORY_MESSAGES = 60
TOOL_CONTENT_CHARS = 6000
OLD_TOOL_CONTENT_CHARS = 1200

EXAMPLES = [
    "别强调拳法，把碎星神通改个名，同步设定和大纲",
    "看看前三章的节奏，第 2 章对话多一点",
    "规划 3 条伏笔，前十章至少一条长线",
    "简介再抓人一点，突出反差",
    "按现在的设定改封面提示词，生成 2 张封面",
    "写下一章",
]


# ------------------------------------------------------------------ 输出

def session_out(s: Session, a: AgentSession) -> dict[str, Any]:
    from app.api.schemas import iso

    n = len(list(s.exec(select(AgentMessage.id).where(AgentMessage.session_id == a.id))))
    last = s.exec(select(AgentMessage).where(AgentMessage.session_id == a.id, AgentMessage.role == "user").order_by(AgentMessage.id.desc())).first()  # type: ignore[union-attr]
    return {"id": a.id, "book_id": a.book_id, "title": a.title, "messages": n, "running": _running(s, a) is not None,
            "running_job_id": a.running_job_id if _running(s, a) else None, "last_user": (last.content[:60] if last else ""),
            "created_at": iso(a.created_at), "updated_at": iso(a.updated_at)}


def message_out(m: AgentMessage) -> dict[str, Any]:
    from app.api.schemas import iso

    calls = [{"id": c.get("id"), "name": c.get("name"), "arguments": c.get("arguments") or {},
              "label": agent_tools.BY_NAME[c["name"]].label if c.get("name") in agent_tools.BY_NAME else c.get("name"),
              "kind": agent_tools.BY_NAME[c["name"]].kind if c.get("name") in agent_tools.BY_NAME else "read"} for c in (m.tool_calls or [])]
    out: dict[str, Any] = {"id": m.id, "role": m.role, "content": m.content, "tool_calls": calls, "tool_call_id": m.tool_call_id,
                           "name": m.name, "summary": m.summary, "status": m.status, "proposal_ids": list(m.proposal_ids or []),
                           "job_ids": list(m.job_ids or []), "created_at": iso(m.created_at)}
    if m.role == "tool":
        t = agent_tools.BY_NAME.get(m.name)
        out["label"] = t.label if t else m.name
        out["kind"] = t.kind if t else "read"
        out["content"] = m.content[:4000]
    return out


def _running(s: Session, a: AgentSession) -> Job | None:
    if not a.running_job_id:
        return None
    j = s.get(Job, a.running_job_id)
    return j if j is not None and j.status in ("queued", "running") else None


def get_session_obj(s: Session, sid: int) -> AgentSession:
    a = s.get(AgentSession, sid)
    if a is None:
        raise NotFound("会话不存在")
    return a


def detail(s: Session, sid: int, after: int = 0) -> dict[str, Any]:
    from app.api.schemas import job_out

    a = get_session_obj(s, sid)
    msgs = list(s.exec(select(AgentMessage).where(AgentMessage.session_id == sid, AgentMessage.id > after).order_by(AgentMessage.id)))
    ps = list(s.exec(select(AgentProposal).where(AgentProposal.session_id == sid).order_by(AgentProposal.id)))
    j = _running(s, a)
    return {"session": session_out(s, a), "messages": [message_out(m) for m in msgs],
            "proposals": [props.proposal_out(p) for p in ps],
            "proposal_jobs": {str(p.id): props.job_state(p.job_id) for p in ps if p.job_id},
            "job": job_out(j) if j else None}


# ------------------------------------------------------------------ 会话管理

def list_sessions(s: Session, book_id: int) -> list[dict[str, Any]]:
    rows = s.exec(select(AgentSession).where(AgentSession.book_id == book_id).order_by(AgentSession.updated_at.desc()))  # type: ignore[attr-defined]
    return [session_out(s, a) for a in rows]


def create_session(s: Session, book_id: int, title: str | None = None) -> AgentSession:
    common.get_book(s, book_id)
    a = AgentSession(book_id=book_id, title=(title or "新对话").strip()[:40] or "新对话")
    s.add(a)
    s.commit()
    s.refresh(a)
    return a


def _wipe(s: Session, sid: int) -> None:
    for m in s.exec(select(AgentMessage).where(AgentMessage.session_id == sid)):
        s.delete(m)
    for p in s.exec(select(AgentProposal).where(AgentProposal.session_id == sid)):
        s.delete(p)


def clear_session(s: Session, sid: int) -> AgentSession:
    """清空会话：删消息和提案。已经写入的改动不受影响，仍可在各页的历史版本 / 快照里撤回。"""
    a = get_session_obj(s, sid)
    if _running(s, a):
        raise Conflict("Agent 正在工作，先停止再清空")
    _wipe(s, sid)
    a.title, a.updated_at = "新对话", utcnow()
    s.add(a)
    s.commit()
    s.refresh(a)
    return a


def delete_session(s: Session, sid: int) -> None:
    a = get_session_obj(s, sid)
    if _running(s, a):
        raise Conflict("Agent 正在工作，先停止再删除")
    _wipe(s, sid)
    s.delete(a)
    s.commit()


def delete_book_data(s: Session, book_id: int) -> None:
    for model in (AgentMessage, AgentProposal, AgentSession):
        for row in s.exec(select(model).where(model.book_id == book_id)):  # type: ignore[attr-defined]
            s.delete(row)


def request_stop(s: Session, sid: int) -> AgentSession:
    a = get_session_obj(s, sid)
    if _running(s, a):
        a.stop_requested = True
        s.add(a)
        s.commit()
    return a


# ------------------------------------------------------------------ 发消息 → 后台跑一轮

def send(sid: int, content: str, route: str | None = None) -> tuple[AgentMessage, Job]:
    content = (content or "").strip()
    if not content:
        raise ValueError("说点什么吧")
    with session_scope() as s:
        a = get_session_obj(s, sid)
        if _running(s, a):
            raise Conflict("Agent 还在处理上一条，稍等或先停止")
        book_id = a.book_id
        common.get_book(s, book_id)
        m = AgentMessage(session_id=sid, book_id=book_id, role="user", content=content[:4000])
        s.add(m)
        if a.title == "新对话":
            a.title = content[:24]
        a.stop_requested = False
        a.updated_at = utcnow()
        s.add(a)
        s.commit()
        s.refresh(m)
    job = submit("agent_run", lambda ctx: run_turn(sid, route, ctx), book_id=book_id)
    with session_scope() as s:
        a = get_session_obj(s, sid)
        a.running_job_id = job.id
        s.add(a)
        s.commit()
    return m, job


def _add(s: Session, **kw: Any) -> AgentMessage:
    m = AgentMessage(**kw)
    s.add(m)
    s.commit()
    s.refresh(m)
    return m


def system_prompt(book_id: int, session_id: int) -> str:
    with session_scope() as s:
        b = common.get_book(s, book_id)
        bctx = common.book_context(s, b, with_cards=False)
        stats = common.book_stats(s, book_id)
        tl = tropes.tropes_for(s, b)
        ps = list(s.exec(select(AgentProposal).where(AgentProposal.session_id == session_id).order_by(AgentProposal.id)))
        auto = bool(b.agent_auto_apply)
    status_cn = {"pending": "待采纳", "applied": "已采纳", "rejected": "作者拒绝了", "reverted": "已撤回", "running": "执行中", "failed": "失败"}
    plines = "\n".join(f"- #{p.id}【{props.KIND_LABEL.get(p.kind, p.kind)}】{p.title} —— {status_cn.get(p.status, p.status)}" for p in ps[-20:]) or "（还没有）"
    trope_lines = "\n".join(f"- {t['name']}（{'、'.join(t['keywords'][:5])}）" for t in tl) or "（无）"
    mode = ("当前书级「自动采纳」已打开：非删除、无冲突的提案会直接写入（写入前留快照/旧版本，作者可撤回）。"
            if auto else "当前「自动采纳」关闭：所有改动都只是提案，作者在对话里点「采纳」才写入。")
    return f"""你是《{b.title}》的专属编辑 Agent，负责这本书的一切：作品信息、设定库、大纲、章节正文、伏笔、文风、包装与封面。
作者告诉你要改什么，你先用读工具弄清现状，再调用改动工具，让对应环节去改。

工作守则：
1. 流程归代码，判断归你。所有改动都必须通过工具完成；不要在回复里贴一大段“改好的内容”冒充已经修改。
2. {mode} 删除类操作（删设定卡、删伏笔、重写设定库时删除旧卡）永远要作者确认。设定冲突会进入冲突审阅，由作者逐条决定。
3. 改动会牵动下游：改了书名/核心设定/专有名词或拿掉某个说法，用 revise_book_info 或 find_mentions 拿到受影响的词，
   再用 sync_downstream 同步设定库和大纲；正文里还在用旧说法的章节，告诉作者是哪几章，问他要不要逐章 rewrite_chapter。
4. 读工具可以一步并行调用多个；同样的读取不要重复做。最多 {MAX_STEPS} 步，别绕远路。
5. 写下一章、生成封面是长任务，提案采纳后会在后台执行，你不用等它完成。
6. 遵守禁用套路：除非作者明确点名要用，不要引入下面这些高频俗套；作者的要求和这里冲突时以作者为准。
{trope_lines}
7. 最后用简短的中文（3–6 行）告诉作者：做了什么、生成了哪些提案（写 #编号）、还需要他决定什么。只说工具真实返回的内容，不要编造。

这本书现在：
{bctx}
进度：已提交 {stats['chapters']} 章，{stats['words']} 字，未回收伏笔 {stats['foreshadow_open']} 条。

本会话的提案：
{plines}"""


def build_messages(book_id: int, session_id: int) -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = list(s.exec(select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.id)))
    rows = [r for r in rows if r.role in ("user", "assistant", "tool")]
    if len(rows) > HISTORY_MESSAGES:  # 从某条 user 消息开始截，避免把 tool_calls 和工具结果拆开
        cut = len(rows) - HISTORY_MESSAGES
        while cut < len(rows) and rows[cut].role != "user":
            cut += 1
        rows = rows[cut:]
    last_user = max((i for i, r in enumerate(rows) if r.role == "user"), default=0)
    out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(book_id, session_id)}]
    answered = {r.tool_call_id for r in rows if r.role == "tool"}
    for i, r in enumerate(rows):
        if r.role == "user":
            out.append({"role": "user", "content": r.content})
        elif r.role == "assistant":
            calls = [c for c in (r.tool_calls or []) if c.get("id")]
            out.append({"role": "assistant", "content": r.content, "tool_calls": calls} if calls else {"role": "assistant", "content": r.content or "（无）"})
            for c in calls:  # 上次中断留下的没有结果的调用，补一个占位结果，满足接口要求
                if c["id"] not in answered:
                    out.append({"role": "tool", "tool_call_id": c["id"], "name": c.get("name", ""), "content": json.dumps({"error": "上次运行中断，没有执行"}, ensure_ascii=False)})
        else:
            limit = TOOL_CONTENT_CHARS if i > last_user else OLD_TOOL_CONTENT_CHARS
            text = r.content if len(r.content) <= limit else r.content[:limit] + "…（已截断）"
            out.append({"role": "tool", "tool_call_id": r.tool_call_id, "name": r.name, "content": text})
    return out


def _stop_requested(sid: int) -> bool:
    with session_scope() as s:
        a = s.get(AgentSession, sid)
        return bool(a and a.stop_requested)


def run_turn(sid: int, route: str | None, ctx: JobContext | None) -> dict[str, Any]:
    """跑一轮 Agent 循环。返回 {steps, proposals, stopped_by}。"""
    with session_scope() as s:
        a = get_session_obj(s, sid)
        book_id = a.book_id
        meta = common.kit_meta(s, common.get_book(s, book_id))
    tc = agent_tools.ToolCtx(book_id=book_id, session_id=sid, job=ctx)
    specs = agent_tools.specs()
    gw = get_gateway()
    pids: list[int] = []
    stopped_by = "done"
    steps = 0
    try:
        for step in range(1, MAX_STEPS + 1):
            if _stop_requested(sid):
                stopped_by = "user"
                with session_scope() as s:
                    _add(s, session_id=sid, book_id=book_id, role="notice", content="已按你的要求停下。")
                break
            steps = step
            tc.step = step
            tc.progress(f"第 {step} 步：思考中")
            msgs = build_messages(book_id, sid)
            out = gw.chat_tools(msgs, specs, meta={**meta, "book_id": book_id, "step": step}, route=route)
            calls = [c for c in out.get("tool_calls") or [] if c.get("name")]
            for i, c in enumerate(calls):
                c["id"] = str(c.get("id") or f"call_{step}_{i}")
            with session_scope() as s:
                _add(s, session_id=sid, book_id=book_id, role="assistant", content=str(out.get("content") or "").strip(),
                     tool_calls=[{"id": c["id"], "name": c["name"], "arguments": c.get("arguments") or {}} for c in calls])
            if not calls:
                break
            for c in calls:
                res = agent_tools.dispatch(tc, c["name"], c.get("arguments") or {})
                pids += res.proposal_ids
                with session_scope() as s:
                    m = _add(s, session_id=sid, book_id=book_id, role="tool", tool_call_id=c["id"], name=c["name"],
                             content=json.dumps({"ok": res.ok, "summary": res.summary, **res.data}, ensure_ascii=False, default=str),
                             summary=res.summary[:200], status="ok" if res.ok else "error",
                             proposal_ids=res.proposal_ids, job_ids=res.job_ids)
                    for pid in res.proposal_ids:
                        p = s.get(AgentProposal, pid)
                        if p is not None:
                            p.message_id = m.id
                            s.add(p)
                    s.commit()
        else:
            stopped_by = "max_steps"
            with session_scope() as s:
                _add(s, session_id=sid, book_id=book_id, role="notice", status="error",
                     content=f"已经连续调用了 {MAX_STEPS} 步工具，先停在这里。上面的提案照常可以采纳；需要的话告诉我接着做哪一步。")
    except Exception as e:
        log.exception("Agent 运行失败")
        with session_scope() as s:
            _add(s, session_id=sid, book_id=book_id, role="notice", status="error", content=f"出错了：{str(e)[:300]}")
        raise
    finally:
        with session_scope() as s:
            a = s.get(AgentSession, sid)
            if a is not None:
                a.running_job_id = None
                a.stop_requested = False
                a.updated_at = utcnow()
                s.add(a)
                s.commit()
    return {"steps": steps, "proposals": pids, "stopped_by": stopped_by}
