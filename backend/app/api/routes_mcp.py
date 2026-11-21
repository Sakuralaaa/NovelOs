"""v0.19/v0.20 Agent 接入：MCP 服务（Streamable HTTP，POST/DELETE /api/mcp）。

外部 agent（反重力里的 Gemini、Claude Code、Cursor 等）用「设置 → API 密钥」生成的 nvk_ 密钥接入，
把 NovelOS 当结构化资产库 + 上下文引擎 + 技能库用：
- 读写作品、设定卡（支持批量）、大纲（支持批量）、章节（支持定点 patch_chapter）、伏笔、文风、笔记、包装
- 扫榜、拆书、选题、同人原著世界库、体检、审稿全覆盖，结果落回面板页面
- chapter_brief 带全上下文（含上一章结尾原文 prev_tail、视点提醒 cast_notes、本书技能，不再重复塞规则，无细纲也能降级读前情）
- save_chapter 支持 Agent 顺手传 summary / state_changes / new_entities / foreshadow_updates / end_state 秒级同步入账，零额外模型调用、零竞态、零渠道也能用
- 每次写操作记录进 agent_activity，在作品概览页可回看
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

import anyio
import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlmodel import Session, select

from app import __version__
from app.api.schemas import iso
from app.db import get_session, session_scope
from app.models.tables import (
    AgentActivity, Book, Card, Channel, Chapter, Fact, FanficSource, Foreshadow,
    Idea, Job, Note, OutlineNode, Package, RadarSnapshot, RankItem, Teardown, utcnow,
)

router = APIRouter(prefix="/api")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
BLOCKED_PATHS = ("/api/mcp", "/api/auth", "/api/settings/api-keys", "/api/apikeys", "/api/keys")

GUIDE = """NovelOS 是你的网文写作资产库与上下文引擎。你可以全权接管整本书：

一、推荐写章流程（一次写成、秒入账、不卡顿）
1. list_books 选书，或 create_book 新建；get_book_info 一次看全进度（最新章号、下一章号、未提交草稿、置顶笔记、启用技能）。
2. 批量建设定用 save_card(items=[...])，批量建卷/弧/章细纲用 save_outline_node(items=[...])（可用 ref / parent_ref 一次建树）。
   - 章细纲 beats 推荐标准键：characters（出场角色名数组）、goal、conflict、hook_end、payoff_type、ending_image、foreshadow（[{action:"plant|advance|resolve",desc:"..."}]）、words。
   - 写完一整卷后，用 save_outline_node(level="volume", order=卷号, recap_text="本卷总结", recap_state=["卷末长期状态"], start_chapter=起章, end_chapter=末章) 写入「前情卷回顾」，后续卷自动带上长篇记忆。
3. 写第 N 章前先调 chapter_brief(book_id, number=N)：一次拿到完整上下文（书设定、相关卡片、人物当前事实、前情卷回顾、最近摘要、未回收伏笔、作者置顶笔记、上一章结尾原文 prev_tail、视点与口头禅提醒、本书启用的写作技能）；若返回 stale_chapters_warning，说明作者在提交后手动改过前章，请先 get_chapter(part="full") 核对。
4. 写完正文后调 save_chapter(book_id, number=N, title=..., content=..., commit=true, summary="本章200字内摘要", state_changes=[{"entity":"角色","key":"位置/境界/伤势/持有物品","value":"新状态"}], new_entities=[{"type":"character","name":"...","summary":"..."}], foreshadow_updates=[{"action":"plant|advance|resolve","desc":"...","id":null}], end_state={...})：
   只要传入 summary 或状态变更，就会毫秒级同步入账（更新底账、伏笔、摘要，不调后端模型，不改你写好的正文），同时返回人味检查与零耗时一致性自检（弃用卡误用、禁用套路命中、超期伏笔）。
5. 局部改稿用 patch_chapter(book_id, number=N, patches=[{"find":"原句","replace":"改后"}])，无需重传整章，自动留历史可撤回。

二、其他能力（结果直接回显在面板）
- facts：查看/修正/删除角色与世界状态事实底账；foreshadows：伏笔增删改查；notes：写作笔记读写（置顶笔记会自动进章前上下文）；style_and_package：文风/包装/禁用套路/全文检索。
- radar_and_teardown：查番茄榜单、风向标、拆书记录、写入拆书与选题。
- fanfic_library：查/搜/写入同人原著世界库，用原著建同人书。
- book_tools：按需触发单章审稿、全书体检、完本状态、联网搜索。
- list_models / call_model：借用作者配置的模型渠道；api_index(with_schema=true) + api：调用任意剩余接口。

约定：正文用简体中文网文写法；锁定的设定卡和大纲节点不可被 AI 修改。"""


def _txt(obj: Any) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def _clip(text: str | None, n: int) -> str:
    t = text or ""
    return t if len(t) <= n else t[:n] + f"…（共 {len(t)} 字，已截断）"


S: dict[str, Any] = {"type": "string"}
I: dict[str, Any] = {"type": "integer"}
B: dict[str, Any] = {"type": "boolean"}
O: dict[str, Any] = {"type": "object"}
A: dict[str, Any] = {"type": "array"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


# ------------------------------------------------------------------ 活动日志

WRITE_TOOLS = {
    "create_book", "save_card", "save_outline_node", "save_chapter", "patch_chapter",
    "commit_chapter", "foreshadows", "style_and_package", "notes", "radar_and_teardown",
    "fanfic_library", "book_tools", "save_style",
}


def _record_activity(book_id: int | None, tool: str, summary: str, detail: dict[str, Any] | None = None, ok: bool = True) -> None:
    try:
        with session_scope() as s:
            s.add(AgentActivity(book_id=book_id, tool=tool, summary=summary[:500], detail=detail, ok=ok))
            s.commit()
    except Exception:  # noqa: BLE001
        pass


def _activity_out(a: AgentActivity) -> dict[str, Any]:
    return {
        "id": a.id, "book_id": a.book_id, "tool": a.tool, "summary": a.summary,
        "detail": a.detail, "ok": a.ok, "created_at": iso(a.created_at),
    }


@router.get("/books/{book_id}/agent-activity")
def book_agent_activity(book_id: int, limit: int = 30, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = s.exec(
        select(AgentActivity).where(AgentActivity.book_id == book_id).order_by(AgentActivity.id.desc()).limit(min(limit, 100))  # type: ignore[union-attr]
    ).all()
    return [_activity_out(r) for r in rows]


@router.get("/agent-activity")
def global_agent_activity(limit: int = 30, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = s.exec(
        select(AgentActivity).order_by(AgentActivity.id.desc()).limit(min(limit, 100))  # type: ignore[union-attr]
    ).all()
    return [_activity_out(r) for r in rows]


# ------------------------------------------------------------------ 内部 HTTP 代理

async def _api(request: Request, method: str, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
    """以调用方的密钥在进程内调用本服务的 HTTP 接口（经过同样的鉴权、校验、版本栈与任务系统）。"""
    import posixpath
    from urllib.parse import unquote

    raw_path = unquote(str(path or "")).split("?", 1)[0].split("#", 1)[0]
    norm = posixpath.normpath("/" + raw_path.lstrip("/"))
    if not norm.lower().startswith("/api/"):
        norm = posixpath.normpath("/api/" + norm.lstrip("/"))
    norm_low = norm.lower()
    if any(norm_low == p or norm_low.startswith(p + "/") for p in BLOCKED_PATHS):
        raise ValueError("这个接口不对 agent 开放")
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "x-api-key", "cookie")}
    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://novelos.local", timeout=600) as c:
        r = await c.request(method.upper(), norm, json=body if body is not None else None, params=query or None, headers=headers)
    try:
        data = r.json()
    except ValueError:
        data = r.text[:4000]
    if r.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        raise ValueError(f"HTTP {r.status_code}：{_txt(detail)[:800]}")
    return data


# ------------------------------------------------------------------ 读工具（独立实现，支持分页与区间过滤）

def _list_books() -> Any:
    with session_scope() as s:
        out = []
        for b in s.exec(select(Book).order_by(Book.id)):
            chs = list(s.exec(select(Chapter).where(Chapter.book_id == b.id)))
            out.append({
                "id": b.id, "title": b.title, "genre": b.genre, "gender": b.gender,
                "status": b.status, "platform_style": b.platform_style,
                "is_fanfic": bool(b.fanfic), "chapters": len(chs),
                "committed": sum(1 for c in chs if c.status == "committed"),
                "words": sum(c.words or 0 for c in chs if c.status == "committed"),
            })
        return out


def _get_book_info(book_id: int) -> dict[str, Any]:
    from app.services import common, skills_store, tropes
    with session_scope() as s:
        b = common.get_book(s, book_id)
        stats = common.book_stats(s, book_id)
        n_cards = len(common.cards(s, book_id))
        n_nodes = len(common.outline_nodes(s, book_id))
        chs = list(s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number)))
        last_num = chs[-1].number if chs else 0
        uncommitted = [{"id": c.id, "number": c.number, "title": c.title, "status": c.status, "words": c.words}
                       for c in chs if c.status != "committed"]
        recent_chs = [{"id": c.id, "number": c.number, "title": c.title, "status": c.status, "words": c.words}
                      for c in chs[-5:]]
        pinned = list(s.exec(
            select(Note).where(Note.book_id == book_id, Note.pinned == True).order_by(Note.updated_at.desc()).limit(10)  # noqa: E712  # type: ignore[attr-defined]
        ))
        _, sel_ids = skills_store.book_skill_ids(s, book_id)
        active_sk = [
            {"id": sk.id, "name": sk.name, "stage": sk.stage}
            for sk in skills_store.active_skills_for_book(s, book_id, "writing")
        ] if sel_ids else []
        open_fs = len(common.open_foreshadows(s, book_id))
        return {
            "id": b.id, "title": b.title, "genre": b.genre, "gender": b.gender,
            "tagline": b.tagline, "premise": b.premise, "status": b.status,
            "target_words": b.target_words, "chapter_words": b.chapter_words,
            "platform_style": b.platform_style, "mode": b.mode,
            "fanfic": b.fanfic, "stats": stats, "cards": n_cards, "outline_nodes": n_nodes,
            "last_chapter_number": last_num,
            "next_chapter_number": uncommitted[0]["number"] if uncommitted else last_num + 1,
            "uncommitted_chapters": uncommitted,
            "recent_chapters": recent_chs,
            "open_foreshadows_count": open_fs,
            "pinned_notes": [{"id": n.id, "folder": n.folder, "title": n.title, "content": _clip(n.content, 200)} for n in pinned],
            "active_writing_skills": active_sk,
            "banned_tropes": [t["name"] for t in tropes.tropes_for(s, b)],
        }


def _search_bible(book_id: int, query: str = "", typ: str | None = None, offset: int = 0, limit: int = 50,
                  include_deprecated: bool = False) -> dict[str, Any]:
    from app.services import common
    with session_scope() as s:
        common.get_book(s, book_id)
        rows = common.cards(s, book_id, typ or None, include_deprecated=include_deprecated)
    q = (query or "").strip()
    if q:
        words = [w for w in q.replace("，", " ").replace(",", " ").split() if w]
        rows = [r for r in rows if any(w in f"{r.name}\n{r.summary}\n{json.dumps(r.data or {}, ensure_ascii=False)}" for w in words)]
    total = len(rows)
    off = max(0, int(offset or 0))
    lim = max(1, min(200, int(limit or 50)))
    sliced = rows[off : off + lim]
    return {
        "total": total, "offset": off, "limit": lim, "has_more": off + lim < total,
        "cards": [{"id": r.id, "type": r.type, "name": r.name, "summary": _clip(r.summary, 200),
                   "locked": bool(r.locked), "status": r.status} for r in sliced],
    }


def _get_card(book_id: int, card_id: int | None = None, name: str | None = None) -> dict[str, Any]:
    from app.services import bible_ops, common
    with session_scope() as s:
        common.get_book(s, book_id)
        if card_id:
            cd = s.get(Card, int(card_id))
            if cd is not None and cd.book_id == book_id:
                return bible_ops.card_dict(cd)
        nm = (name or "").strip()
        cards = common.cards(s, book_id, include_deprecated=True)
        for cd in cards:
            if nm and cd.name == nm:
                return bible_ops.card_dict(cd)
        for cd in cards:
            if nm and nm in cd.name:
                return bible_ops.card_dict(cd)
        raise ValueError(f"没有找到设定卡「{nm or card_id}」")


def _get_outline(book_id: int, level: str | None = None, parent_id: int | None = None,
                 from_order: int | None = None, to_order: int | None = None,
                 offset: int = 0, limit: int = 100) -> dict[str, Any]:
    from app.services import common
    with session_scope() as s:
        common.get_book(s, book_id)
        nodes = common.outline_nodes(s, book_id)
    rank = {"book": 0, "volume": 1, "arc": 2, "chapter": 3}
    nodes = sorted(nodes, key=lambda n: (rank.get(n.level, 9), n.order))
    if level:
        nodes = [n for n in nodes if n.level == level]
    if parent_id is not None:
        nodes = [n for n in nodes if n.parent_id == int(parent_id)]
    if from_order is not None:
        nodes = [n for n in nodes if n.order >= int(from_order)]
    if to_order is not None:
        nodes = [n for n in nodes if n.order <= int(to_order)]
    total = len(nodes)
    off = max(0, int(offset or 0))
    lim = max(1, min(300, int(limit or 100)))
    sliced = nodes[off : off + lim]
    return {
        "total": total, "offset": off, "limit": lim, "has_more": off + lim < total,
        "nodes": [{"id": n.id, "level": n.level, "order": n.order, "parent_id": n.parent_id,
                   "title": n.title, "summary": _clip(n.summary, 160), "status": n.status,
                   "locked": bool(n.locked), "chapter_id": n.chapter_id} for n in sliced],
    }


def _get_outline_node(book_id: int, node_id: int) -> dict[str, Any]:
    with session_scope() as s:
        n = s.get(OutlineNode, int(node_id))
        if n is None or n.book_id != book_id:
            raise ValueError("大纲节点不存在")
        return {
            "id": n.id, "level": n.level, "order": n.order, "parent_id": n.parent_id,
            "title": n.title, "summary": n.summary, "beats": n.beats, "status": n.status,
            "locked": bool(n.locked), "chapter_id": n.chapter_id, "versions": len(n.versions or []),
        }


def _list_chapters(book_id: int, from_number: int | None = None, to_number: int | None = None,
                   status: str | None = None, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    from app.services import common
    with session_scope() as s:
        common.get_book(s, book_id)
        rows = list(s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number)))
    if from_number is not None:
        rows = [r for r in rows if r.number >= int(from_number)]
    if to_number is not None:
        rows = [r for r in rows if r.number <= int(to_number)]
    if status:
        rows = [r for r in rows if r.status == status]
    total = len(rows)
    off = max(0, int(offset or 0))
    lim = max(1, min(300, int(limit or 100)))
    sliced = rows[off : off + lim]
    return {
        "total": total, "offset": off, "limit": lim, "has_more": off + lim < total,
        "chapters": [{"id": r.id, "number": r.number, "title": r.title, "status": r.status,
                      "words": r.words, "summary": _clip(r.summary, 140)} for r in sliced],
    }


def _find_chapter(s: Session, book_id: int, chapter_id: int | None = None, number: int | None = None) -> Chapter:
    if chapter_id:
        ch = s.get(Chapter, int(chapter_id))
        if ch is not None and ch.book_id == book_id:
            return ch
    if number is not None:
        ch = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number == int(number))).first()
        if ch is not None:
            return ch
    raise ValueError(f"没有找到第 {number or chapter_id} 章")


def _get_chapter(book_id: int, chapter_id: int | None = None, number: int | None = None,
                 part: str = "summary", max_chars: int = 20000) -> dict[str, Any]:
    from app.services import writing
    with session_scope() as s:
        ch = _find_chapter(s, book_id, chapter_id, number)
        d: dict[str, Any] = {
            "id": ch.id, "number": ch.number, "title": ch.title, "status": ch.status,
            "words": ch.words, "summary": ch.summary,
        }
        if part == "full":
            d["content"] = _clip(ch.content, max(1000, min(50000, int(max_chars or 20000))))
        elif part == "excerpt":
            d["opening"] = _clip(ch.content[:800], 800)
            d["ending"] = (ch.content or "")[-600:]
        if ch.lint:
            d["lint"] = writing.actionable_lint(ch.lint)
        if ch.changes:
            d["changes"] = ch.changes
        return d


# ------------------------------------------------------------------ 写作核心工具

def _chapter_node(s: Session, book_id: int, number: int) -> OutlineNode | None:
    return s.exec(select(OutlineNode).where(
        OutlineNode.book_id == book_id, OutlineNode.level == "chapter", OutlineNode.order == number,
    )).first()


def _chapter_brief(book_id: int, number: int, instruction: str = "", with_rules: bool = True) -> dict[str, Any]:
    """v0.20 完整章前上下文：
    - 修复 prev_tail（上一章结尾原文）和 cast_notes 丢失的问题
    - 不再重复塞两遍 writing_rules
    - 没有章细纲节点时也能降级返回前情、设定与上一章结尾
    - 检测上一章是否有仍在运行中的后台提交任务，提醒避免竞态
    """
    from app.services.context import build_context_pack

    with session_scope() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise ValueError("作品不存在")
        node = _chapter_node(s, book_id, number)
        has_outline = node is not None
        if node is None:
            node = OutlineNode(book_id=book_id, level="chapter", order=number, title=f"第{number}章", summary="", beats={})
        pack = build_context_pack(s, book, node, instruction=instruction)
        words = int((node.beats or {}).get("target_words") or (node.beats or {}).get("words") or getattr(book, "chapter_words", 0) or 2200)
        # 检查是否有未完成的提交任务（防连写竞态）
        running_commits = s.exec(
            select(Job).where(Job.book_id == book_id, Job.kind == "chapter_commit", Job.status.in_(("queued", "running")))  # type: ignore[attr-defined]
        ).all()

        # 检测最近 3 章已提交章节是否在提交后被人工改过（正文指纹与 summary_hash 不一致）
        from app.services.writing import _content_hash
        prev_committed = list(s.exec(
            select(Chapter).where(Chapter.book_id == book_id, Chapter.number < number, Chapter.status == "committed")
            .order_by(Chapter.number.desc()).limit(3)  # type: ignore[attr-defined]
        ))
        stale_warns: list[dict[str, Any]] = []
        for pc in reversed(prev_committed):
            sh = (pc.changes or {}).get("summary_hash") if isinstance(pc.changes, dict) else None
            if sh and _content_hash(pc.content or "") != sh:
                stale_warns.append({
                    "chapter_id": pc.id, "number": pc.number, "title": pc.title,
                    "hint": f"第 {pc.number} 章《{pc.title}》在提交后正文有改动，摘要与场面账本可能已过期，建议 get_chapter(part='full') 核对。",
                })

        prefix_text = pack.prefix
        if not with_rules:
            # 去掉最前面内置的 system_prompt 规则部分，只保留【本书】及之后设定与风格
            idx = prefix_text.find("【本书】")
            if idx != -1:
                prefix_text = prefix_text[idx:]

        sections = [prefix_text.strip(), pack.suffix.strip()]
        if stale_warns:
            sections.append("【前章人工改稿提醒】\n" + "\n".join(f"- {w['hint']}" for w in stale_warns))
        if pack.cast_notes and pack.cast_notes != "（无）":
            sections.append("【视点与人物提醒】\n" + pack.cast_notes)
        if pack.prev_tail:
            sections.append("【上一章结尾原文（本章开头紧接着这里写）】\n" + pack.prev_tail)

        out: dict[str, Any] = {
            "number": number,
            "title": node.title,
            "outline_node_id": node.id if has_outline else None,
            "has_outline": has_outline,
            "target_words": words,
            "context": "\n\n".join(x for x in sections if x),
            "prev_tail": pack.prev_tail,
            "cast_notes": pack.cast_notes,
            "preflight": pack.preflight,
        }
        if stale_warns:
            out["stale_chapters_warning"] = stale_warns
        if not has_outline:
            out["note"] = f"第 {number} 章暂无章细纲节点，以上为前情、设定与上一章结尾上下文；如需规划节拍可先 save_outline_node。"
        if running_commits:
            out["pending_commit_warning"] = f"当前有 {len(running_commits)} 个章节提交任务正在后台运行（job_id={[j.id for j in running_commits]}），前情摘要可能尚未更新完毕。"
        return out


def _quick_consistency_check(s: Session, book_id: int, content: str, number: int) -> dict[str, Any]:
    """零 LLM 毫秒级防穿帮自检：检查弃用设定卡误用、禁用套路命中、超期未动伏笔。"""
    from app.services import common, tropes
    out: dict[str, Any] = {}
    book = s.get(Book, book_id)
    if book is None:
        return out
    dep_cards = [
        c.name for c in common.cards(s, book_id, include_deprecated=True)
        if c.status == "deprecated" and len(c.name or "") >= 2 and c.name in (content or "")
    ]
    if dep_cards:
        out["deprecated_cards_mentioned"] = dep_cards[:10]
    tr_hits = tropes.detect(content or "", tropes.tropes_for(s, book))
    if tr_hits:
        out["banned_trope_hits"] = tr_hits[:6]
    stale_fs = [
        {"id": f.id, "desc": f.desc, "planted_ch": f.planted_ch, "age": number - int(f.last_ch or f.planted_ch or 0)}
        for f in common.open_foreshadows(s, book_id)
        if (number - int(f.last_ch or f.planted_ch or 0)) >= 20
    ]
    if stale_fs:
        stale_fs.sort(key=lambda x: -x["age"])
        out["stale_foreshadows"] = stale_fs[:5]
    return out


def _save_chapter(book_id: int, number: int, title: str | None, content: str) -> dict[str, Any]:
    from app.services import writing
    with session_scope() as s:
        if s.get(Book, book_id) is None:
            raise ValueError("作品不存在")
        ch = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number == number)).first()
        if ch is None:
            node = _chapter_node(s, book_id, number)
            ch = Chapter(book_id=book_id, number=number, title=title or (node.title if node else f"第{number}章"),
                         status="draft", outline_node_id=node.id if node else None, content="", words=0)
            s.add(ch)
            s.commit()
            s.refresh(ch)
            if node is not None:
                node.chapter_id = ch.id
                node.status = "written"
                s.add(node)
                s.commit()
        else:
            if ch.content:
                writing.push_history(ch, "Agent 覆盖前")
            if ch.variants and not ch.content:
                ch.variants = []
            s.add(ch)
            s.commit()
        cid, status = ch.id or 0, ch.status
    ch2 = writing.update_chapter(cid, title, content)
    with session_scope() as s:
        checks = _quick_consistency_check(s, book_id, ch2.content or "", number)
    res: dict[str, Any] = {
        "chapter_id": cid, "number": number, "title": ch2.title, "words": ch2.words,
        "status": status, "lint": writing.actionable_lint(ch2.lint),
    }
    if checks:
        res["consistency_warnings"] = checks
    return res


def _patch_chapter(book_id: int, chapter_id: int | None, number: int | None,
                   patches: list[dict[str, str]], title: str | None = None) -> dict[str, Any]:
    from app.services import writing
    with session_scope() as s:
        ch = _find_chapter(s, book_id, chapter_id, number)
        cid = ch.id or 0
    ch2, applied, skipped = writing.patch_chapter(cid, patches, title=title)
    with session_scope() as s:
        checks = _quick_consistency_check(s, book_id, ch2.content or "", ch2.number)
    res: dict[str, Any] = {
        "chapter_id": cid, "number": ch2.number, "title": ch2.title, "words": ch2.words,
        "status": ch2.status, "applied": applied, "skipped": skipped,
        "lint": writing.actionable_lint(ch2.lint),
    }
    if checks:
        res["consistency_warnings"] = checks
    return res


def _save_card_one(s: Session, book_id: int, item: dict[str, Any]) -> dict[str, Any]:
    from app.api.schemas import card_out, merge_soul
    from app.services import card_versions

    cid = item.get("card_id") or item.get("id")
    c: Card | None = None
    updated_existing = False
    if cid:
        c = s.get(Card, int(cid))
        if c is None or c.book_id != book_id:
            raise ValueError(f"设定卡 {cid} 不存在")
        updated_existing = True
    else:
        typ = str(item.get("type") or "").strip()
        name = str(item.get("name") or "").strip()
        if not typ or not name:
            raise ValueError("新建设定卡需要提供 type 和 name")
        existing = s.exec(
            select(Card).where(Card.book_id == book_id, Card.type == typ, Card.name == name, Card.status != "deprecated")
        ).first()
        if existing is not None:
            c = existing
            updated_existing = True

    if c is not None:
        if c.locked:
            raise ValueError(f"设定卡「{c.name}」已锁定，不可由 AI 修改")
        before = card_versions.state_of(c)
        for k in ("type", "name", "summary", "status"):
            if item.get(k) is not None:
                setattr(c, k, item[k])
        if isinstance(item.get("data"), dict):
            c.data = {**(c.data or {}), **item["data"]} if not cid else item["data"]
        if item.get("soul") is not None and c.type == "character":
            c.soul = merge_soul(c.soul, item["soul"])
        if card_versions.changed(before, c):
            card_versions.push(c, "Agent 修改前", before)
        c.updated_at = utcnow()
        s.add(c)
        s.flush()
        out = card_out(c)
        if updated_existing and not cid:
            out["updated"] = True
        return out

    typ = str(item.get("type") or "").strip()
    name = str(item.get("name") or "").strip()
    c = Card(
        book_id=book_id, type=typ, name=name, summary=str(item.get("summary") or ""),
        data=item.get("data") if isinstance(item.get("data"), dict) else {},
        status=str(item.get("status") or "active"),
    )
    if item.get("soul") is not None and typ == "character":
        c.soul = merge_soul(None, item["soul"])
    s.add(c)
    s.flush()
    return card_out(c)


def _save_cards(args: dict[str, Any]) -> Any:
    book_id = int(args["book_id"])
    items = args.get("items")
    with session_scope() as s:
        if s.get(Book, book_id) is None:
            raise ValueError("作品不存在")
        if isinstance(items, list):
            if not items:
                raise ValueError("items 不能为空")
            saved = [_save_card_one(s, book_id, it) for it in items if isinstance(it, dict)]
            s.commit()
            return {"count": len(saved), "cards": saved}
        res = _save_card_one(s, book_id, args)
        s.commit()
        return res


def _normalize_beats(raw: Any, item: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """把外部 Agent 常见的细纲别名字段归一化到上下文引擎识别的标准键，并支持卷节点的 recap 快捷字段。"""
    b: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    # 别名映射（不覆盖已有的标准键）
    if "characters" not in b:
        for alias in ("cast", "actors", "roles"):
            if isinstance(b.get(alias), list):
                b["characters"] = b[alias]
                break
    if "words" not in b and b.get("target_words"):
        b["words"] = b["target_words"]
    if "hook_end" not in b:
        for alias in ("hook", "ending_hook"):
            if b.get(alias):
                b["hook_end"] = b[alias]
                break
    if "payoff_type" not in b and isinstance(b.get("payoff"), str) and len(b["payoff"]) <= 20:
        b["payoff_type"] = b["payoff"]
    if "foreshadow" not in b and isinstance(b.get("foreshadows"), list):
        b["foreshadow"] = b["foreshadows"]
    # 卷节点前情回顾快捷字段：recap_text / recap_state / start_chapter / end_chapter
    if isinstance(item, dict):
        rtxt = item.get("recap_text")
        rstate = item.get("recap_state")
        if rtxt is not None or rstate is not None:
            prev_rc = dict(b.get("recap")) if isinstance(b.get("recap"), dict) else {}
            if rtxt is not None:
                prev_rc["text"] = str(rtxt).strip()
            if isinstance(rstate, list):
                prev_rc["state"] = [str(x).strip() for x in rstate if str(x).strip()]
            b["recap"] = prev_rc
        sc, ec = item.get("start_chapter"), item.get("end_chapter")
        if sc is not None or ec is not None:
            prev_wb = dict(b.get("wanben")) if isinstance(b.get("wanben"), dict) else {}
            if sc is not None:
                prev_wb["start"] = int(sc)
            elif ec is not None and "start" not in prev_wb:
                prev_wb["start"] = 1
            if ec is not None:
                prev_wb["end"] = int(ec)
            b["wanben"] = prev_wb
    return b if b else (raw if isinstance(raw, dict) else None)


def _save_outline_one(s: Session, book_id: int, item: dict[str, Any], ref_map: dict[str, int]) -> dict[str, Any]:
    from app.services import outline as outline_svc

    has_recap = any(item.get(k) is not None for k in ("recap_text", "recap_state", "start_chapter", "end_chapter"))
    nid = item.get("node_id") or item.get("id")
    if nid:
        n = s.get(OutlineNode, int(nid))
        if n is None or n.book_id != book_id:
            raise ValueError(f"大纲节点 {nid} 不存在")
        if n.locked:
            raise ValueError(f"大纲节点「{n.title}」已锁定，不可由 AI 修改")
        outline_svc.push_node_version(n, "Agent 修改")
        for k in ("title", "summary", "order"):
            if item.get(k) is not None:
                setattr(n, k, item[k])
        if item.get("beats") is not None or has_recap:
            merged = {**(n.beats or {}), **(item["beats"] if isinstance(item.get("beats"), dict) else {})}
            n.beats = _normalize_beats(merged, item)
        s.add(n)
        s.flush()
        if item.get("ref") and n.id:
            ref_map[str(item["ref"])] = n.id
        return {"node_id": n.id, "level": n.level, "order": n.order, "title": n.title, "parent_id": n.parent_id}

    level = str(item.get("level") or "chapter")
    if level not in ("book", "volume", "arc", "chapter"):
        raise ValueError("level 只能是 book / volume / arc / chapter")
    parent_id = item.get("parent_id")
    if parent_id is None and item.get("parent_ref"):
        parent_id = ref_map.get(str(item["parent_ref"]))
    order = int(item.get("order") or 0)
    if level in ("chapter", "volume") and order:
        existing = (
            _chapter_node(s, book_id, order)
            if level == "chapter"
            else s.exec(select(OutlineNode).where(
                OutlineNode.book_id == book_id, OutlineNode.level == "volume", OutlineNode.order == order,
            )).first()
        )
        if existing is not None:
            if existing.locked:
                raise ValueError(f"第 {order} {'章细纲' if level == 'chapter' else '卷'}已锁定，不可修改")
            outline_svc.push_node_version(existing, "Agent 覆盖")
            if item.get("title") is not None:
                existing.title = str(item["title"])
            if item.get("summary") is not None:
                existing.summary = str(item["summary"])
            if isinstance(item.get("beats"), dict) or has_recap:
                merged = {**(existing.beats or {}), **(item["beats"] if isinstance(item.get("beats"), dict) else {})}
                existing.beats = _normalize_beats(merged, item)
            if parent_id is not None:
                existing.parent_id = int(parent_id)
            s.add(existing)
            s.flush()
            if item.get("ref") and existing.id:
                ref_map[str(item["ref"])] = existing.id
            return {"node_id": existing.id, "level": existing.level, "order": existing.order,
                    "title": existing.title, "parent_id": existing.parent_id, "updated": True}
    if not order:
        sib = list(s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == level)))
        order = max([x.order for x in sib] or [0]) + 1
    n = OutlineNode(
        book_id=book_id, parent_id=int(parent_id) if parent_id is not None else None,
        level=level, order=order, title=str(item.get("title") or ""), summary=str(item.get("summary") or ""),
        beats=_normalize_beats(item.get("beats"), item) if (isinstance(item.get("beats"), dict) or has_recap) else None,
    )
    s.add(n)
    s.flush()
    if item.get("ref") and n.id:
        ref_map[str(item["ref"])] = n.id
    return {"node_id": n.id, "level": n.level, "order": n.order, "title": n.title, "parent_id": n.parent_id}


def _save_outline_nodes(args: dict[str, Any]) -> Any:
    book_id = int(args["book_id"])
    items = args.get("items")
    with session_scope() as s:
        if s.get(Book, book_id) is None:
            raise ValueError("作品不存在")
        ref_map: dict[str, int] = {}
        if isinstance(items, list):
            if not items:
                raise ValueError("items 不能为空")
            saved = [_save_outline_one(s, book_id, it, ref_map) for it in items if isinstance(it, dict)]
            s.commit()
            return {"count": len(saved), "nodes": saved}
        res = _save_outline_one(s, book_id, args, ref_map)
        s.commit()
        return res


# ------------------------------------------------------------------ 聚合领域工具（伏笔 / 笔记 / 风格包装 / 扫榜拆书 / 同人库 / 书内工具）

def _facts_tool(args: dict[str, Any]) -> Any:
    """事实底账（角色/世界当前状态）查询、修正与删除。"""
    from app.services import common, context as ctx_svc

    book_id = int(args["book_id"])
    action = str(args.get("action") or "list")
    with session_scope() as s:
        common.get_book(s, book_id)
        cards = common.cards(s, book_id, include_deprecated=True)
        name_by_id = {c.id: c.name for c in cards if c.id is not None}
        id_by_name = {c.name: c.id for c in cards if c.id is not None}

        if action == "list":
            ch = args.get("chapter")
            include_expired = bool(args.get("include_expired"))
            if ch is not None:
                rows = ctx_svc.facts_at(s, book_id, int(ch))
            else:
                q = select(Fact).where(Fact.book_id == book_id)
                if not include_expired:
                    q = q.where(Fact.to_chapter == None)  # noqa: E711
                rows = list(s.exec(q.order_by(Fact.from_chapter.desc(), Fact.id.desc())))  # type: ignore[attr-defined]
            ent = str(args.get("entity") or "").strip()
            if ent:
                if ent == "全书":
                    rows = [r for r in rows if r.entity_id is None]
                else:
                    rows = [r for r in rows if name_by_id.get(r.entity_id or -1) == ent]
            key_kw = str(args.get("key") or "").strip()
            if key_kw:
                rows = [r for r in rows if key_kw in (r.key or "")]
            return {
                "count": len(rows),
                "facts": [{
                    "id": r.id, "entity_id": r.entity_id,
                    "entity": name_by_id.get(r.entity_id or -1, "全书") if r.entity_id is not None else "全书",
                    "key": r.key, "value": r.value, "from_chapter": r.from_chapter,
                    "to_chapter": r.to_chapter, "visibility": r.visibility,
                } for r in rows[:200]],
            }
        if action == "set":
            fid = args.get("fact_id")
            vis_raw = str(args.get("visibility") or "author").strip().lower()
            vis = "reader" if vis_raw == "reader" else "author"
            if fid:
                f = s.get(Fact, int(fid))
                if f is None or f.book_id != book_id:
                    raise ValueError(f"事实 {fid} 不存在")
                if args.get("key") is not None:
                    f.key = str(args["key"]).strip()[:40]
                if args.get("value") is not None:
                    v = args["value"]
                    f.value = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                if args.get("from_chapter") is not None:
                    f.from_chapter = int(args["from_chapter"])
                if "to_chapter" in args:
                    f.to_chapter = int(args["to_chapter"]) if args["to_chapter"] is not None else None
                if args.get("visibility") is not None:
                    f.visibility = vis
                s.add(f)
                s.commit()
                s.refresh(f)
                return {"id": f.id, "entity": name_by_id.get(f.entity_id or -1, "全书") if f.entity_id else "全书",
                        "key": f.key, "value": f.value, "from_chapter": f.from_chapter, "to_chapter": f.to_chapter, "updated": True}
            ent = str(args.get("entity") or "全书").strip()
            key = str(args.get("key") or "").strip()[:40]
            val_raw = args.get("value")
            if not key or val_raw is None:
                raise ValueError("set 事实需要 key 和 value")
            val = val_raw if isinstance(val_raw, str) else json.dumps(val_raw, ensure_ascii=False)
            eid = None if ent in ("", "全书") else id_by_name.get(ent)
            if ent not in ("", "全书") and eid is None:
                raise ValueError(f"未找到名为「{ent}」的设定卡（如需全书级事实请传 entity='全书'）")
            if args.get("from_chapter") is not None:
                from_ch = int(args["from_chapter"])
            else:
                last_ch = s.exec(select(Chapter.number).where(Chapter.book_id == book_id).order_by(Chapter.number.desc())).first()  # type: ignore[attr-defined]
                from_ch = int(last_ch) if last_ch is not None else 0
            prev = s.exec(select(Fact).where(Fact.book_id == book_id, Fact.entity_id == eid, Fact.key == key,
                                             Fact.to_chapter == None)).all()  # noqa: E711
            reused: Fact | None = None
            for p in prev:
                if p.from_chapter == from_ch and reused is None:
                    p.value = val
                    p.visibility = vis
                    s.add(p)
                    reused = p
                elif p.from_chapter >= from_ch:
                    s.delete(p)
                else:
                    p.to_chapter = max(p.from_chapter, from_ch - 1)
                    s.add(p)
            if reused is not None:
                s.commit()
                s.refresh(reused)
                return {"id": reused.id, "entity": ent or "全书", "key": reused.key, "value": reused.value,
                        "from_chapter": reused.from_chapter, "updated": True}
            nf = Fact(book_id=book_id, entity_id=eid, key=key, value=val, from_chapter=from_ch, visibility=vis)
            s.add(nf)
            s.commit()
            s.refresh(nf)
            return {"id": nf.id, "entity": ent or "全书", "key": nf.key, "value": nf.value, "from_chapter": nf.from_chapter}
        if action == "delete":
            f = s.get(Fact, int(args["fact_id"]))
            if f is None or f.book_id != book_id:
                raise ValueError("事实不存在")
            s.delete(f)
            s.commit()
            return {"ok": True}
    raise ValueError(f"不支持的 facts action：{action}")


def _foreshadows_tool(args: dict[str, Any]) -> Any:
    from app.api.schemas import foreshadow_out
    from app.services import common, foreshadows as fs_svc

    book_id = int(args["book_id"])
    action = str(args.get("action") or "list")
    if action == "list":
        st = str(args.get("status") or "").strip()
        with session_scope() as s:
            common.get_book(s, book_id)
            rows = list(s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id).order_by(Foreshadow.id)))
            planned = fs_svc.outline_planned(s, book_id)
        if st:
            rows = [r for r in rows if r.status == st]
        return {"count": len(rows), "foreshadows": [foreshadow_out(r) for r in rows], "outline_planned": planned[:30]}
    if action == "create":
        desc = str(args.get("desc") or "").strip()
        if not desc:
            raise ValueError("create 伏笔需要 desc")
        data = {k: args[k] for k in ("desc", "status", "tier", "planted_ch", "plan_plant_ch", "plan_resolve_ch", "note") if args.get(k) is not None}
        data["source"] = "agent"
        return foreshadow_out(fs_svc.create(book_id, data))
    if action == "update":
        fid = int(args["foreshadow_id"])
        patch = {k: args[k] for k in ("desc", "status", "tier", "planted_ch", "last_ch", "resolved_ch", "plan_plant_ch", "plan_resolve_ch", "note") if args.get(k) is not None}
        return foreshadow_out(fs_svc.update(fid, patch))
    if action == "delete":
        fs_svc.delete(int(args["foreshadow_id"]))
        return {"ok": True}
    raise ValueError(f"不支持的 foreshadows action：{action}")


def _notes_tool(args: dict[str, Any]) -> Any:
    book_id = int(args["book_id"])
    action = str(args.get("action") or "list")
    with session_scope() as s:
        if s.get(Book, book_id) is None:
            raise ValueError("作品不存在")
        if action == "list":
            rows = list(s.exec(select(Note).where(Note.book_id == book_id).order_by(Note.pinned.desc(), Note.updated_at.desc())))  # type: ignore[attr-defined]
            q = str(args.get("query") or "").strip()
            if q:
                rows = [r for r in rows if q in r.title or q in r.content or q in r.folder]
            return {
                "count": len(rows),
                "notes": [{"id": r.id, "folder": r.folder, "title": r.title, "tags": r.tags,
                           "pinned": r.pinned, "excerpt": _clip(r.content, 160)} for r in rows[:100]],
            }
        if action == "get":
            n = s.get(Note, int(args["note_id"]))
            if n is None or n.book_id != book_id:
                raise ValueError("笔记不存在")
            return {"id": n.id, "folder": n.folder, "title": n.title, "content": n.content,
                    "tags": n.tags, "pinned": n.pinned, "updated_at": iso(n.updated_at)}
        if action == "save":
            nid = args.get("note_id")
            if nid:
                n = s.get(Note, int(nid))
                if n is None or n.book_id != book_id:
                    raise ValueError("笔记不存在")
            else:
                n = Note(book_id=book_id)
            for k in ("folder", "title", "content", "tags", "pinned"):
                if args.get(k) is not None:
                    setattr(n, k, args[k])
            n.updated_at = utcnow()
            s.add(n)
            s.commit()
            s.refresh(n)
            return {"id": n.id, "folder": n.folder, "title": n.title, "pinned": n.pinned}
        if action == "delete":
            n = s.get(Note, int(args["note_id"]))
            if n is None or n.book_id != book_id:
                raise ValueError("笔记不存在")
            s.delete(n)
            s.commit()
            return {"ok": True}
    raise ValueError(f"不支持的 notes action：{action}")


def _radar_and_teardown_tool(args: dict[str, Any]) -> Any:
    action = str(args.get("action") or "ranks")
    with session_scope() as s:
        if action == "snapshots":
            rows = s.exec(select(RadarSnapshot).order_by(RadarSnapshot.id.desc()).limit(20)).all()  # type: ignore[union-attr]
            return [{"id": r.id, "taken_at": iso(r.taken_at), "source": r.source, "items_count": r.items_count, "version": r.version} for r in rows]
        if action == "ranks":
            snap_id = args.get("snapshot_id")
            snap = s.get(RadarSnapshot, int(snap_id)) if snap_id else s.exec(select(RadarSnapshot).order_by(RadarSnapshot.id.desc())).first()  # type: ignore[union-attr]
            if snap is None:
                return {"snapshot": None, "items": []}
            q = select(RankItem).where(RankItem.snapshot_id == snap.id)
            if args.get("gender"):
                q = q.where(RankItem.gender == str(args["gender"]))
            if args.get("board"):
                q = q.where(RankItem.board == str(args["board"]))
            if args.get("category"):
                q = q.where(RankItem.category == str(args["category"]))
            rows = list(s.exec(q.order_by(RankItem.rank)))
            lim = max(1, min(100, int(args.get("limit") or 30)))
            return {
                "snapshot": {"id": snap.id, "taken_at": iso(snap.taken_at), "source": snap.source},
                "total": len(rows),
                "items": [{"id": r.id, "book_id_ext": r.book_id_ext, "title": r.title, "author": r.author,
                           "category": r.category, "gender": r.gender, "board": r.board, "rank": r.rank,
                           "rank_diff": r.rank_diff, "read_count": r.read_count, "word_count": r.word_count,
                           "tags": r.tags, "abstract": _clip(r.abstract, 180)} for r in rows[:lim]],
            }
        if action == "trend":
            from app.radar.report import latest_report
            rep = latest_report(s, str(args.get("scope") or "overall"))
            return rep or {"note": "暂无风向标日报"}
        if action == "teardowns":
            rows = s.exec(select(Teardown).order_by(Teardown.id.desc()).limit(30)).all()  # type: ignore[union-attr]
            return [{"id": r.id, "title": r.title, "source": r.source, "chars": r.chars, "created_at": iso(r.created_at)} for r in rows]
        if action == "get_teardown":
            t = s.get(Teardown, int(args["teardown_id"]))
            if t is None:
                raise ValueError("拆书记录不存在")
            return {"id": t.id, "title": t.title, "source": t.source, "chars": t.chars, "result": t.result, "warnings": t.warnings}
        if action == "save_teardown":
            title = str(args.get("title") or "").strip()
            result = args.get("result")
            if not title or not isinstance(result, dict):
                raise ValueError("save_teardown 需要 title 和 result（对象）")
            t = Teardown(title=title, source="agent", chars=int(args.get("chars") or 0),
                         result=result, warnings=list(args.get("warnings") or []), model="external-agent")
            s.add(t)
            s.commit()
            s.refresh(t)
            return {"id": t.id, "title": t.title}
        if action == "ideas":
            rows = s.exec(select(Idea).order_by(Idea.id.desc()).limit(50)).all()  # type: ignore[union-attr]
            return [{"id": r.id, "title": r.title, "genre": r.genre, "gender": r.gender, "logline": r.logline,
                     "selling_points": r.selling_points, "hook": r.hook, "chosen": r.chosen, "book_id": r.book_id} for r in rows]
        if action == "create_idea":
            title = str(args.get("title") or "").strip()
            if not title:
                raise ValueError("create_idea 需要 title")
            idea = Idea(
                title=title, logline=str(args.get("logline") or ""),
                genre=str(args.get("genre") or ""), gender=str(args.get("gender") or "male"),
                selling_points=list(args.get("selling_points") or []),
                hook=str(args.get("hook") or ""), expectations=list(args.get("expectations") or []),
                endgame=str(args.get("endgame") or ""), arc=list(args.get("arc") or []),
            )
            s.add(idea)
            s.commit()
            s.refresh(idea)
            return {"id": idea.id, "title": idea.title}
    raise ValueError(f"不支持的 radar_and_teardown action：{action}")


def _fanfic_library_tool(args: dict[str, Any]) -> Any:
    action = str(args.get("action") or "list_sources")
    with session_scope() as s:
        if action == "list_sources":
            rows = s.exec(select(FanficSource).order_by(FanficSource.id.desc())).all()  # type: ignore[union-attr]
            return [{"id": r.id, "title": r.title, "source": r.source, "intro": _clip(r.intro, 120),
                     "tags": r.tags, "entries_count": len(r.entries or [])} for r in rows]
        if action == "get_source":
            fs = s.get(FanficSource, int(args["source_id"]))
            if fs is None:
                raise ValueError("原著资料不存在")
            return {"id": fs.id, "title": fs.title, "intro": fs.intro, "tags": fs.tags,
                    "entries_count": len(fs.entries or []), "cards": fs.cards}
        if action == "search_entries":
            fs = s.get(FanficSource, int(args["source_id"]))
            if fs is None:
                raise ValueError("原著资料不存在")
            entries = list(fs.entries or [])
            cat = str(args.get("cat") or "").strip()
            q = str(args.get("query") or "").strip()
            if cat:
                entries = [e for e in entries if e.get("cat") == cat]
            if q:
                entries = [e for e in entries if q in f"{e.get('name', '')} {e.get('summary', '')} {e.get('detail', '')}"]
            lim = max(1, min(100, int(args.get("limit") or 40)))
            return {"total": len(entries), "entries": entries[:lim]}
        if action == "save_entry":
            fs = s.get(FanficSource, int(args["source_id"]))
            if fs is None:
                raise ValueError("原著资料不存在")
            entries = list(fs.entries or [])
            name = str(args.get("name") or "").strip()
            if not name:
                raise ValueError("save_entry 需要 name")
            eid = str(args.get("entry_id") or "")
            new_item = {
                "id": eid or f"ag_{secrets.token_hex(4)}",
                "cat": str(args.get("cat") or "world"),
                "sub": str(args.get("sub") or ""),
                "name": name,
                "summary": str(args.get("summary") or ""),
                "detail": str(args.get("detail") or ""),
                "tags": list(args.get("tags") or []),
            }
            replaced = False
            if eid:
                for idx, e in enumerate(entries):
                    if str(e.get("id")) == eid:
                        entries[idx] = {**e, **new_item}
                        replaced = True
                        break
            if not replaced:
                entries.append(new_item)
            fs.entries = entries
            fs.updated_at = utcnow()
            s.add(fs)
            s.commit()
            return {"source_id": fs.id, "entry": new_item, "entries_count": len(entries)}
    raise ValueError(f"不支持的 fanfic_library action：{action}")


def _list_models() -> Any:
    from app.llm.gateway import get_routing
    with session_scope() as s:
        chans = [{"id": c.id, "name": c.name, "format": c.api_format, "models": c.models, "enabled": c.enabled}
                 for c in s.exec(select(Channel).order_by(Channel.id))]
        return {"channels": chans, "routing": get_routing(s),
                "note": "call_model 的 route 写「渠道id:模型名」，或用 role 走对应角色的路由"}


def _call_model(args: dict[str, Any]) -> Any:
    from app.llm.gateway import get_gateway
    msgs: list[dict[str, str]] = []
    if args.get("system"):
        msgs.append({"role": "system", "content": str(args["system"])})
    if isinstance(args.get("messages"), list):
        msgs += [{"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")} for m in args["messages"]]
    if args.get("prompt"):
        msgs.append({"role": "user", "content": str(args["prompt"])})
    if not any(m["role"] == "user" for m in msgs):
        raise ValueError("prompt 或 messages 至少给一个")
    meta = {"book_id": args.get("book_id")} if args.get("book_id") else None
    return get_gateway().chat(
        "agent_external", msgs, meta=meta, role=str(args.get("role") or "writer"),
        temperature=float(args.get("temperature", 0.8)),
        max_tokens=int(args["max_tokens"]) if args.get("max_tokens") else None,
        route=str(args["route"]) if args.get("route") else None,
    )


def _api_index(request: Request, keyword: str = "", with_schema: bool = False) -> Any:
    openapi = request.app.openapi()
    paths_spec = openapi.get("paths") or {}
    comps = (openapi.get("components") or {}).get("schemas") or {}

    def _body_fields(op: dict[str, Any]) -> str:
        req = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema") or {}
        if "$ref" in req:
            ref_name = req["$ref"].rsplit("/", 1)[-1]
            req = comps.get(ref_name) or {}
        elif isinstance(req.get("anyOf"), list):
            for branch in req["anyOf"]:
                if isinstance(branch, dict) and "$ref" in branch:
                    req = comps.get(branch["$ref"].rsplit("/", 1)[-1]) or {}
                    break
        props = req.get("properties") or {}
        if not props:
            return ""
        req_set = set(req.get("required") or [])
        bits = [f"{k}{'*' if k in req_set else ''}" for k in list(props)[:12]]
        return " body={" + ", ".join(bits) + "}"

    rows = []
    for path, methods in sorted(paths_spec.items()):
        if not path.startswith("/api/") or any(path == p or path.startswith(p + "/") for p in BLOCKED_PATHS):
            continue
        if not isinstance(methods, dict):
            continue
        for m, op in sorted(methods.items()):
            method = m.upper()
            if method in ("HEAD", "OPTIONS", "PARAMETERS") or not isinstance(op, dict):
                continue
            doc = str(op.get("description") or op.get("summary") or "").strip().split("\n")[0]
            extra = _body_fields(op) if with_schema else ""
            line = f"{method} {path}{extra}" + (f"  {doc}" if doc else "")
            if not keyword or keyword.lower() in line.lower():
                rows.append(line)
    return "\n".join(rows) or "没有匹配的接口"


# ------------------------------------------------------------------ 工具清单（精简高信号）

TOOLS: list[dict[str, Any]] = [
    {"name": "guide", "description": "NovelOS 使用说明与推荐写章流程（第一次接入先读）。", "inputSchema": _schema({})},
    {"name": "list_books", "description": "列出所有作品（id、书名、题材、章数、已提交字数）。", "inputSchema": _schema({})},
    {"name": "create_book", "description": "新建作品。target_words 全书字数，chapter_words 每章字数，platform_style 可选 fanqie/qidian/generic/duanju。",
     "inputSchema": _schema({"title": S, "genre": S, "premise": {**S, "description": "一句话简介/核心设定"},
                             "gender": {**S, "enum": ["male", "female"]}, "target_words": I, "chapter_words": I,
                             "platform_style": {**S, "enum": ["fanqie", "qidian", "generic", "duanju"]}}, ["title"])},
    {"name": "get_book_info", "description": "读作品信息：书名、题材、简介、核心设定、进度、同人配置与禁用套路。",
     "inputSchema": _schema({"book_id": I}, ["book_id"])},
    {"name": "search_bible", "description": "检索或分页列出设定卡（支持 query、type、offset、limit）。",
     "inputSchema": _schema({"book_id": I, "query": S, "type": {**S, "enum": ["world", "cheat", "power", "faction", "character", "item", "location"]},
                             "offset": I, "limit": I}, ["book_id"])},
    {"name": "get_card", "description": "读一张设定卡完整内容（传 card_id 或 name）。",
     "inputSchema": _schema({"book_id": I, "card_id": I, "name": S}, ["book_id"])},
    {"name": "save_card", "description": "新建/修改单张设定卡，或传 items:[...] 一次批量写入多张卡（锁定卡不可改）。",
     "inputSchema": _schema({"book_id": I, "card_id": I, "type": S, "name": S, "summary": S, "data": O, "soul": O,
                             "status": {**S, "enum": ["active", "deprecated"]},
                             "items": {**A, "items": O, "description": "批量写入多张卡"}}, ["book_id"])},
    {"name": "get_outline", "description": "读大纲树节点（支持 level、parent_id、from_order、to_order、offset、limit 分页）。",
     "inputSchema": _schema({"book_id": I, "level": {**S, "enum": ["book", "volume", "arc", "chapter"]},
                             "parent_id": I, "from_order": I, "to_order": I, "offset": I, "limit": I}, ["book_id"])},
    {"name": "get_outline_node", "description": "读单个大纲节点（含章细纲节拍 beats）。",
     "inputSchema": _schema({"book_id": I, "node_id": I}, ["book_id", "node_id"])},
    {"name": "save_outline_node", "description": "新建/修改单个大纲节点，或传 items:[...] 一次批量建树（支持 ref/parent_ref）。章细纲 beats 标准键：characters、goal、conflict、hook_end、payoff_type、ending_image、foreshadow、words；卷节点可传 recap_text/recap_state/start_chapter/end_chapter 写入前情卷回顾。",
     "inputSchema": _schema({"book_id": I, "node_id": I, "parent_id": I, "level": {**S, "enum": ["book", "volume", "arc", "chapter"]},
                             "order": I, "title": S, "summary": S, "beats": O,
                             "recap_text": S, "recap_state": {**A, "items": S}, "start_chapter": I, "end_chapter": I,
                             "items": {**A, "items": O, "description": "批量写入大纲节点"}}, ["book_id"])},
    {"name": "list_chapters", "description": "分页列出章节（支持 from_number、to_number、status、offset、limit）。",
     "inputSchema": _schema({"book_id": I, "from_number": I, "to_number": I, "status": S, "offset": I, "limit": I}, ["book_id"])},
    {"name": "get_chapter", "description": "读一章：part=summary/excerpt/full（full 默认最多 20000 字），含具体人味检查命中。",
     "inputSchema": _schema({"book_id": I, "number": I, "chapter_id": I, "part": {**S, "enum": ["summary", "excerpt", "full"]},
                             "max_chars": I}, ["book_id"])},
    {"name": "chapter_brief", "description": "写某章前一次取全上下文（含章细纲、人物状态、前情摘要、未回收伏笔、上一章结尾原文 prev_tail、视点提醒与本书技能；无细纲也可降级返回前情）。",
     "inputSchema": _schema({"book_id": I, "number": I, "instruction": S, "with_rules": B}, ["book_id", "number"])},
    {"name": "save_chapter", "description": "保存第 number 章正文。commit=true 时若同时提供 summary 或 state_changes/new_entities/foreshadow_updates/end_state，直接同步秒入账（零额外模型调用、零等待）；返回具体人味检查命中。",
     "inputSchema": _schema({
         "book_id": I, "number": I, "title": S, "content": S, "commit": B, "update_ledger": B,
         "summary": {**S, "description": "本章摘要（100-200字），提供后直接同步入账"},
         "state_changes": {**A, "items": O, "description": "[{entity, key, value}] 人物/物品状态变更"},
         "new_entities": {**A, "items": O, "description": "[{type, name, summary}] 本章新登场实体"},
         "foreshadow_updates": {**A, "items": O, "description": "[{action: plant|advance|resolve, desc, id?}] 伏笔变动"},
         "end_state": {**O, "description": "本章结尾场面账本 {cast, props}"},
     }, ["book_id", "number", "content"])},
    {"name": "patch_chapter", "description": "定点局部修改章节正文（按原句精确替换，无需重传整章，自动存历史可撤回）。",
     "inputSchema": _schema({
         "book_id": I, "number": I, "chapter_id": I, "title": S,
         "patches": {**A, "items": _schema({"find": S, "replace": S}, ["find", "replace"])},
     }, ["book_id", "patches"])},
    {"name": "commit_chapter", "description": "提交一章入账（传 chapter_id 或 book_id+number；附带 summary/state_changes/new_entities/foreshadow_updates 可同步秒入账）。",
     "inputSchema": _schema({
         "chapter_id": I, "book_id": I, "number": I, "summary": S, "state_changes": {**A, "items": O}, "new_entities": {**A, "items": O},
         "foreshadow_updates": {**A, "items": O}, "end_state": O, "update_ledger": B,
     }, [])},
    {"name": "facts", "description": "事实底账管理（角色/世界当前状态）：action=list|set|delete，用于核对或更正写错的人物境界、位置、物品等状态。",
     "inputSchema": _schema({"book_id": I, "action": {**S, "enum": ["list", "set", "delete"]},
                             "fact_id": I, "entity": S, "key": S, "value": S, "chapter": I,
                             "from_chapter": I, "to_chapter": I, "visibility": {**S, "enum": ["author", "reader"]},
                             "include_expired": B}, ["book_id"])},
    {"name": "foreshadows", "description": "伏笔底账管理：action=list|create|update|delete。",
     "inputSchema": _schema({"book_id": I, "action": {**S, "enum": ["list", "create", "update", "delete"]},
                             "foreshadow_id": I, "status": S, "desc": S, "tier": S,
                             "planted_ch": I, "resolved_ch": I, "plan_plant_ch": I, "plan_resolve_ch": I, "note": S}, ["book_id"])},
    {"name": "style_and_package", "description": "文风卡、包装、禁用套路与全文检索：action=get_style|save_style|get_package|save_package|get_banned_tropes|find_mentions。",
     "inputSchema": _schema({"book_id": I, "action": {**S, "enum": ["get_style", "save_style", "get_package", "save_package", "get_banned_tropes", "find_mentions"]},
                             "tone": S, "voice_notes": S, "pov": {**S, "enum": ["first", "third"]}, "sample_text": S, "baseline": S,
                             "blurb": S, "tags": {**A, "items": S}, "cover_prompt": S, "titles": {**A, "items": O},
                             "terms": {**A, "items": S}}, ["book_id", "action"])},
    {"name": "notes", "description": "本书写作笔记读写：action=list|get|save|delete。",
     "inputSchema": _schema({"book_id": I, "action": {**S, "enum": ["list", "get", "save", "delete"]},
                             "note_id": I, "query": S, "folder": S, "title": S, "content": S,
                             "tags": {**A, "items": S}, "pinned": B}, ["book_id"])},
    {"name": "radar_and_teardown", "description": "热点雷达、风向标、拆书工作台与选题库：action=snapshots|ranks|trend|teardowns|get_teardown|save_teardown|ideas|create_idea。",
     "inputSchema": _schema({"action": {**S, "enum": ["snapshots", "ranks", "trend", "teardowns", "get_teardown", "save_teardown", "ideas", "create_idea"]},
                             "snapshot_id": I, "gender": S, "board": S, "category": S, "scope": S, "limit": I,
                             "teardown_id": I, "title": S, "result": O, "chars": I, "warnings": {**A, "items": S},
                             "logline": S, "genre": S, "selling_points": {**A, "items": S}, "hook": S,
                             "expectations": {**A, "items": S}, "endgame": S, "arc": {**A, "items": S}}, ["action"])},
    {"name": "fanfic_library", "description": "同人原著世界库：action=list_sources|get_source|search_entries|save_entry。",
     "inputSchema": _schema({"action": {**S, "enum": ["list_sources", "get_source", "search_entries", "save_entry"]},
                             "source_id": I, "cat": S, "sub": S, "query": S, "limit": I,
                             "entry_id": S, "name": S, "summary": S, "detail": S, "tags": {**A, "items": S}}, ["action"])},
    {"name": "book_tools", "description": "按需工具：action=review（审稿建议）|book_check（全书体检）|wanben_status（完本进度）|web_search（联网搜索）。",
     "inputSchema": _schema({"book_id": I, "action": {**S, "enum": ["review", "book_check", "wanben_status", "web_search"]},
                             "chapter_id": I, "number": I, "query": S}, ["book_id", "action"])},
    {"name": "skills", "description": "可插拔技能库读写与按书绑定：action=list|get|save|delete|book_skills|bind_book|import_github。",
     "inputSchema": _schema({
         "action": {**S, "enum": ["list", "get", "save", "delete", "book_skills", "bind_book", "import_github"]},
         "skill_id": I, "book_id": I, "stage": S, "query": S,
         "name": S, "description": S, "body": S, "enabled": B, "is_default": B,
         "references": {**A, "items": O}, "skill_ids": {**A, "items": I}, "url": S, "token": S,
     }, ["action"])},
    {"name": "list_models", "description": "列出作者配置的模型渠道和各角色路由。", "inputSchema": _schema({})},
    {"name": "call_model", "description": "用作者配置的模型生成文本。route=「渠道id:模型名」或按 role 路由。",
     "inputSchema": _schema({"prompt": S, "system": S, "messages": {**A, "items": O}, "route": S,
                             "role": {**S, "enum": ["writer", "planner", "reviewer"]}, "temperature": {"type": "number"},
                             "max_tokens": I, "book_id": I}, [])},
    {"name": "get_job", "description": "查后台任务进度与结果。", "inputSchema": _schema({"job_id": I}, ["job_id"])},
    {"name": "api_index", "description": "列出 NovelOS 全部接口（可按 keyword 过滤，with_schema=true 显示请求体字段）。",
     "inputSchema": _schema({"keyword": S, "with_schema": B})},
    {"name": "api", "description": "调用任意 NovelOS 接口（路径以 /api/ 开头），用于低频/高级操作。",
     "inputSchema": _schema({"method": {**S, "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]}, "path": S, "body": O, "query": O}, ["method", "path"])},
]


# ------------------------------------------------------------------ 调度

async def _style_and_package(request: Request, a: dict[str, Any]) -> Any:
    from app.services import book_edit, common, tropes

    bid = int(a["book_id"])
    action = str(a.get("action") or "")
    if action == "get_style":
        return await _api(request, "GET", f"/api/books/{bid}/style")
    if action == "save_style":
        cur = await _api(request, "GET", f"/api/books/{bid}/style")
        cur = cur if isinstance(cur, dict) else {}
        body = {k: (a[k] if a.get(k) is not None else cur.get(k)) for k in ("tone", "voice_notes", "pov", "sample_text", "baseline")}
        body = {k: v for k, v in body.items() if v is not None}
        return await _api(request, "PUT", f"/api/books/{bid}/style", body)
    if action == "get_package":
        return await _api(request, "GET", f"/api/books/{bid}/package")
    if action == "save_package":
        body = {k: a[k] for k in ("blurb", "tags", "cover_prompt", "titles") if a.get(k) is not None}
        return await _api(request, "PUT", f"/api/books/{bid}/package", body)
    if action == "get_banned_tropes":
        def _bt() -> Any:
            with session_scope() as s:
                return {"banned": tropes.tropes_for(s, common.get_book(s, bid))}
        return await anyio.to_thread.run_sync(_bt)
    if action == "find_mentions":
        terms = [str(t) for t in (a.get("terms") or []) if str(t).strip()]
        def _fm() -> Any:
            with session_scope() as s:
                return book_edit.impact(s, bid, terms)
        return await anyio.to_thread.run_sync(_fm)
    raise ValueError(f"不支持的 style_and_package action：{action}")


async def _book_tools(request: Request, a: dict[str, Any]) -> Any:
    bid = int(a["book_id"])
    action = str(a.get("action") or "")
    if action == "review":
        def _resolve_cid() -> int:
            with session_scope() as s:
                return _find_chapter(s, bid, a.get("chapter_id"), a.get("number")).id or 0
        cid = await anyio.to_thread.run_sync(_resolve_cid)
        return await _api(request, "POST", f"/api/chapters/{cid}/review")
    if action == "book_check":
        return await _api(request, "POST", f"/api/books/{bid}/check")
    if action == "wanben_status":
        return await _api(request, "GET", f"/api/books/{bid}/wanben")
    if action == "web_search":
        from app.services.research import search_once
        q = str(a.get("query") or "").strip()
        if not q:
            raise ValueError("web_search 需要 query")
        return await anyio.to_thread.run_sync(search_once, q, bid)
    raise ValueError(f"不支持的 book_tools action：{action}")


async def _skills_tool(request: Request, a: dict[str, Any]) -> Any:
    action = str(a.get("action") or "list")
    if action == "list":
        q = {k: a[k] for k in ("stage", "source") if a.get(k)}
        if a.get("query"):
            q["q"] = a["query"]
        res = await _api(request, "GET", "/api/skills", query=q)
        # 列表精简掉正文，防止一次占满上下文；需要正文用 get
        return {
            "stages": res.get("stages"),
            "items": [{k: v for k, v in it.items() if k not in ("body", "references")} for it in (res.get("items") or [])],
        }
    if action == "get":
        return await _api(request, "GET", f"/api/skills/{int(a['skill_id'])}")
    if action == "save":
        sid = a.get("skill_id")
        body = {k: a[k] for k in ("name", "description", "stage", "body", "references", "enabled", "is_default") if a.get(k) is not None}
        if sid:
            res = await _api(request, "PUT", f"/api/skills/{int(sid)}", body)
            _record_activity(None, "skills", f"更新技能「{res.get('name', '')}」")
            return res
        res = await _api(request, "POST", "/api/skills", body)
        _record_activity(None, "skills", f"新建技能「{res.get('name', '')}」")
        return res
    if action == "delete":
        sid = int(a["skill_id"])
        res = await _api(request, "DELETE", f"/api/skills/{sid}")
        _record_activity(None, "skills", f"删除技能 #{sid}")
        return res
    if action == "book_skills":
        return await _api(request, "GET", f"/api/books/{int(a['book_id'])}/skills")
    if action == "bind_book":
        bid = int(a["book_id"])
        res = await _api(request, "PUT", f"/api/books/{bid}/skills", {"skill_ids": list(a.get("skill_ids") or [])})
        _record_activity(bid, "skills", f"更新本书技能绑定（已选 {len(res.get('selected_ids') or [])} 个）")
        return res
    if action == "import_github":
        body = {"url": str(a.get("url") or "")}
        if a.get("stage"):
            body["stage"] = str(a["stage"])
        if a.get("token"):
            body["token"] = str(a["token"])
        res = await _api(request, "POST", "/api/skills/import-github", body)
        _record_activity(None, "skills", f"从 GitHub 导入技能「{res.get('name', '')}」")
        return res
    raise ValueError(f"不支持的 skills action：{action}")


async def _call(request: Request, name: str, a: dict[str, Any]) -> Any:
    from app.llm.gateway import is_mock_mode
    from app.services import writing

    # 兼容 v0.19 旧工具名别名
    if name == "list_foreshadows":
        name, a = "foreshadows", {**a, "action": "list"}
    elif name in ("get_style", "save_style", "get_package", "get_banned_tropes", "find_mentions"):
        name, a = "style_and_package", {**a, "action": name}
    elif name == "web_search":
        name, a = "book_tools", {**a, "action": "web_search"}

    book_id = int(a["book_id"]) if a.get("book_id") is not None else None

    if name == "guide":
        return GUIDE
    if name == "list_books":
        return await anyio.to_thread.run_sync(_list_books)
    if name == "create_book":
        body = {k: a[k] for k in ("title", "genre", "premise", "gender", "target_words", "chapter_words", "platform_style") if a.get(k) is not None}
        res = await _api(request, "POST", "/api/books", body)
        _record_activity(res.get("id"), "create_book", f"创建新书《{res.get('title')}》", {"book_id": res.get("id")})
        return res
    if name == "get_book_info":
        return await anyio.to_thread.run_sync(_get_book_info, int(a["book_id"]))
    if name == "search_bible":
        return await anyio.to_thread.run_sync(
            _search_bible, int(a["book_id"]), str(a.get("query") or ""), a.get("type"),
            int(a.get("offset") or 0), int(a.get("limit") or 50),
        )
    if name == "get_card":
        return await anyio.to_thread.run_sync(_get_card, int(a["book_id"]), a.get("card_id"), a.get("name"))
    if name == "save_card":
        res = await anyio.to_thread.run_sync(_save_cards, dict(a))
        desc = f"批量保存 {res['count']} 张设定卡" if isinstance(res, dict) and "count" in res else f"保存设定卡「{res.get('name', '')}」"
        _record_activity(book_id, "save_card", desc)
        return res
    if name == "get_outline":
        return await anyio.to_thread.run_sync(
            _get_outline, int(a["book_id"]), a.get("level"), a.get("parent_id"),
            a.get("from_order"), a.get("to_order"), int(a.get("offset") or 0), int(a.get("limit") or 100),
        )
    if name == "get_outline_node":
        return await anyio.to_thread.run_sync(_get_outline_node, int(a["book_id"]), int(a["node_id"]))
    if name == "save_outline_node":
        res = await anyio.to_thread.run_sync(_save_outline_nodes, dict(a))
        desc = f"批量保存 {res['count']} 个大纲节点" if isinstance(res, dict) and "count" in res else f"保存大纲节点「{res.get('title', '')}」"
        _record_activity(book_id, "save_outline_node", desc)
        return res
    if name == "list_chapters":
        return await anyio.to_thread.run_sync(
            _list_chapters, int(a["book_id"]), a.get("from_number"), a.get("to_number"),
            a.get("status"), int(a.get("offset") or 0), int(a.get("limit") or 100),
        )
    if name == "get_chapter":
        return await anyio.to_thread.run_sync(
            _get_chapter, int(a["book_id"]), a.get("chapter_id"), a.get("number"),
            str(a.get("part") or "summary"), int(a.get("max_chars") or 20000),
        )
    if name == "chapter_brief":
        return await anyio.to_thread.run_sync(
            _chapter_brief, int(a["book_id"]), int(a["number"]),
            str(a.get("instruction") or ""), a.get("with_rules", True) is not False,
        )
    if name == "save_chapter":
        content = str(a.get("content") or "")
        if not content.strip():
            raise ValueError("content 不能为空")
        r = await anyio.to_thread.run_sync(_save_chapter, int(a["book_id"]), int(a["number"]), a.get("title"), content)
        has_ledger = any(a.get(k) for k in ("summary", "state_changes", "new_entities", "foreshadow_updates", "end_state"))
        if a.get("commit"):
            def _is_mock() -> bool:
                with session_scope() as s:
                    return is_mock_mode(s)
            mock_now = await anyio.to_thread.run_sync(_is_mock)
            if r["status"] == "committed" and not a.get("update_ledger"):
                r["note"] = "这一章之前已提交，正文已更新；如需刷新摘要或底账请传 update_ledger=true"
            elif has_ledger or mock_now:
                # 同步秒入账：零额外 LLM 调用、零等待、零竞态
                ch_c = await anyio.to_thread.run_sync(
                    writing.commit_chapter_direct, r["chapter_id"],
                    a.get("summary"), a.get("state_changes"), a.get("new_entities"),
                    a.get("foreshadow_updates"), a.get("end_state"), bool(a.get("update_ledger")),
                )
                r["status"] = ch_c.status
                r["committed"] = True
                r["summary"] = ch_c.summary
            else:
                r["job"] = await _api(request, "POST", f"/api/chapters/{r['chapter_id']}/commit")
        _record_activity(
            book_id, "save_chapter",
            f"{'写入并提交' if r.get('committed') or r.get('job') else '保存草稿'}第 {r['number']} 章《{r['title']}》（{r['words']} 字）",
            {"chapter_id": r["chapter_id"], "number": r["number"], "words": r["words"]},
        )
        return r
    if name == "patch_chapter":
        r = await anyio.to_thread.run_sync(
            _patch_chapter, int(a["book_id"]), a.get("chapter_id"), a.get("number"),
            list(a.get("patches") or []), a.get("title"),
        )
        _record_activity(
            book_id, "patch_chapter",
            f"局部修改第 {r['number']} 章《{r['title']}》（应用 {len(r['applied'])} 处替换）",
            {"chapter_id": r["chapter_id"], "applied": len(r["applied"])},
        )
        return r
    if name == "commit_chapter":
        if a.get("chapter_id"):
            cid = int(a["chapter_id"])
        elif a.get("book_id") is not None and a.get("number") is not None:
            def _find_cid() -> int:
                with session_scope() as s:
                    return _find_chapter(s, int(a["book_id"]), None, int(a["number"])).id or 0
            cid = await anyio.to_thread.run_sync(_find_cid)
        else:
            raise ValueError("commit_chapter 需要提供 chapter_id，或同时提供 book_id 和 number")
        has_ledger = any(a.get(k) for k in ("summary", "state_changes", "new_entities", "foreshadow_updates", "end_state"))
        def _is_mock2() -> bool:
            with session_scope() as s:
                return is_mock_mode(s)
        if has_ledger or await anyio.to_thread.run_sync(_is_mock2):
            ch_c = await anyio.to_thread.run_sync(
                writing.commit_chapter_direct, cid,
                a.get("summary"), a.get("state_changes"), a.get("new_entities"),
                a.get("foreshadow_updates"), a.get("end_state"), bool(a.get("update_ledger")),
            )
            _record_activity(ch_c.book_id, "commit_chapter", f"提交第 {ch_c.number} 章《{ch_c.title}》入账")
            return {"chapter_id": ch_c.id, "number": ch_c.number, "status": ch_c.status, "committed": True, "summary": ch_c.summary}
        res = await _api(request, "POST", f"/api/chapters/{cid}/commit")
        return res
    if name == "facts":
        res = await anyio.to_thread.run_sync(_facts_tool, dict(a))
        if a.get("action") in ("set", "delete"):
            _record_activity(book_id, "facts", f"事实底账 {a.get('action')}：{a.get('entity') or ''} {a.get('key') or a.get('fact_id') or ''}".strip())
        return res
    if name == "foreshadows":
        res = await anyio.to_thread.run_sync(_foreshadows_tool, dict(a))
        if a.get("action") in ("create", "update", "delete"):
            _record_activity(book_id, "foreshadows", f"伏笔 {a.get('action')}：{a.get('desc') or a.get('foreshadow_id')}")
        return res
    if name == "style_and_package":
        res = await _style_and_package(request, dict(a))
        if a.get("action") in ("save_style", "save_package"):
            _record_activity(book_id, "style_and_package", f"更新{'文风卡' if a.get('action') == 'save_style' else '包装信息'}")
        return res
    if name == "notes":
        res = await anyio.to_thread.run_sync(_notes_tool, dict(a))
        if a.get("action") in ("save", "delete"):
            _record_activity(book_id, "notes", f"笔记 {a.get('action')}：{a.get('title') or a.get('note_id')}")
        return res
    if name == "radar_and_teardown":
        res = await anyio.to_thread.run_sync(_radar_and_teardown_tool, dict(a))
        if a.get("action") in ("save_teardown", "create_idea"):
            _record_activity(None, "radar_and_teardown", f"{a.get('action')}：{a.get('title', '')}")
        return res
    if name == "fanfic_library":
        res = await anyio.to_thread.run_sync(_fanfic_library_tool, dict(a))
        if a.get("action") == "save_entry":
            _record_activity(None, "fanfic_library", f"写入原著世界库条目「{a.get('name', '')}」")
        return res
    if name == "book_tools":
        return await _book_tools(request, dict(a))
    if name == "skills":
        return await _skills_tool(request, dict(a))
    if name == "list_models":
        return await anyio.to_thread.run_sync(_list_models)
    if name == "call_model":
        return await anyio.to_thread.run_sync(_call_model, dict(a))
    if name == "get_job":
        return await _api(request, "GET", f"/api/jobs/{int(a['job_id'])}")
    if name == "api_index":
        return _api_index(request, str(a.get("keyword") or ""), bool(a.get("with_schema")))
    if name == "api":
        return await _api(request, str(a.get("method") or "GET"), str(a.get("path") or ""),
                          a.get("body"), a.get("query") if isinstance(a.get("query"), dict) else None)
    raise ValueError(f"没有这个工具：{name}")


# ------------------------------------------------------------------ JSON-RPC / Streamable HTTP

def _ok(mid: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, msg: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


async def _handle(request: Request, msg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # 通知，不回
        return None, None
    if method == "initialize":
        want = params.get("protocolVersion")
        ver = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        sid = request.headers.get("mcp-session-id") or secrets.token_hex(16)
        return _ok(mid, {
            "protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "novelos", "version": __version__},
            "instructions": GUIDE,
        }), sid
    if method == "ping":
        return _ok(mid, {}), None
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS}), None
    if method in ("resources/list", "resources/templates/list"):
        return _ok(mid, {"resources": [], "resourceTemplates": []}), None
    if method == "prompts/list":
        return _ok(mid, {"prompts": []}), None
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        try:
            out = await _call(request, name, args if isinstance(args, dict) else {})
            return _ok(mid, {"content": [{"type": "text", "text": _txt(out)}], "isError": False}), None
        except Exception as e:  # noqa: BLE001  工具错误回给模型，不断连接
            text = str(e) if isinstance(e, (ValueError, KeyError)) else f"{type(e).__name__}: {e}"
            if isinstance(e, KeyError):
                text = f"缺少参数 {e}"
            return _ok(mid, {"content": [{"type": "text", "text": text[:2000]}], "isError": True}), None
    return _err(mid, -32601, f"不支持的方法：{method}"), None


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(_err(None, -32700, "不是合法 JSON"), status_code=400)
    sid_in = request.headers.get("mcp-session-id")
    if isinstance(payload, list):
        res_list: list[dict[str, Any]] = []
        sid_out = sid_in
        for m in payload:
            if isinstance(m, dict):
                r, s_new = await _handle(request, m)
                if s_new:
                    sid_out = s_new
                if r is not None:
                    res_list.append(r)
        headers = {"Mcp-Session-Id": sid_out} if sid_out else {}
        return JSONResponse(res_list, headers=headers) if res_list else Response(status_code=202, headers=headers)
    if not isinstance(payload, dict):
        return JSONResponse(_err(None, -32600, "请求格式不对"), status_code=400)
    res, sid_new = await _handle(request, payload)
    sid_out = sid_new or sid_in
    headers = {"Mcp-Session-Id": sid_out} if sid_out else {}
    return JSONResponse(res, headers=headers) if res is not None else Response(status_code=202, headers=headers)


@router.get("/mcp")
async def mcp_get() -> Response:
    return Response(status_code=405, headers={"Allow": "POST, DELETE"})


@router.delete("/mcp")
async def mcp_delete() -> Response:
    """Streamable HTTP 会话结束清理（无状态服务直接返回 204）。"""
    return Response(status_code=204)


@router.get("/mcp-info")
def mcp_info(request: Request) -> dict[str, Any]:
    """设置页「Agent 接入」：MCP 地址与工具清单。"""
    base = str(request.base_url).rstrip("/")
    proto = request.headers.get("x-forwarded-proto")
    if proto:
        base = re.sub(r"^https?", proto, base)
    host = request.headers.get("x-forwarded-host")
    if host:
        base = re.sub(r"^(https?://)[^/]+", rf"\g<1>{host}", base)
    return {"url": f"{base}/api/mcp", "tools": [{"name": t["name"], "description": t["description"]} for t in TOOLS]}
