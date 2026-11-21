"""v0.19 Agent 接入：MCP 服务（Streamable HTTP，POST /api/mcp）。

外部 agent（反重力里的 Gemini、Claude Code、Cursor 等）用「设置 → API 密钥」生成的 nvk_ 密钥接入，
把 NovelOS 当资产库用：读写作品、设定卡、大纲、章节、伏笔、文风，自己写正文提交入账；
也可以调用作者已配置的模型渠道（call_model），或启动内置流程（写下一章、一键成书等，走 api 工具）。

所有写操作复用现有接口与服务（版本栈、锁定、底账提交照旧），不另起一套。
"""

from __future__ import annotations

import json
import re
from typing import Any

import anyio
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlmodel import select

from app import __version__
from app.db import session_scope
from app.models.tables import Book, Channel, Chapter, OutlineNode

router = APIRouter(prefix="/api")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
BLOCKED_PATHS = ("/api/mcp", "/api/auth", "/api/settings/api-keys", "/api/apikeys", "/api/keys")
READ_TOOLS = ("get_book_info", "search_bible", "get_card", "get_outline", "get_outline_node", "list_chapters",
              "get_chapter", "list_foreshadows", "get_style", "get_package", "get_banned_tropes", "find_mentions", "web_search")

GUIDE = """NovelOS 是网文写作资产库：作品、设定卡（世界观/金手指/势力/人物/物品/地点）、大纲树（总纲→卷→弧→章细纲）、
章节正文、伏笔底账、文风卡、包装。你可以全权接管：

一、自己写（推荐你文笔好时用）
1. list_books 选书，或 create_book 新建；get_book_info / search_bible / get_outline 了解设定。
2. 缺设定就 save_card 写卡，缺大纲就 save_outline_node 建卷/弧/章细纲（章细纲 order=全书章号）。
3. 写某章前先 chapter_brief：返回 NovelOS 给写手的同款上下文（章细纲节拍、人物当前状态、前情、上一章结尾、要回收的伏笔、文风与写作规则）。
4. 按上下文写好正文后 save_chapter(book_id, number, title, content, commit=true)：存为该章正文并提交入账
   （提交会生成摘要、更新人物状态与伏笔底账，是后台任务，用 get_job 查进度）。一章提交后再写下一章。
5. 想要审稿意见：api POST /api/chapters/{id}/review（后台任务）。

二、让 NovelOS 用已配置的模型干
- list_models 看渠道与各角色路由；call_model 直接调某个模型（route="渠道id:模型名"，或 role=writer/planner/reviewer）。
- 内置流程用 api 工具调用：写下一章 POST /api/books/{id}/chapters/write-next；一键成书 POST /api/ideas/{idea_id}/autopilot；
  暂停 POST /api/books/{id}/autopilot/pause；生成大纲 POST /api/books/{id}/outline/generate。长任务都返回 job，用 get_job 查。
- api_index 列出全部接口（可按关键词过滤），api 工具可调用任何一个。

约定：正文用简体中文网文写法；已提交章节牵动底账，别随便覆盖；锁定的卡和大纲节点不能改。"""


def _txt(obj: Any) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1, default=str)


S: dict[str, Any] = {"type": "string"}
I: dict[str, Any] = {"type": "integer"}
B: dict[str, Any] = {"type": "boolean"}
O: dict[str, Any] = {"type": "object"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


# ------------------------------------------------------------------ 工具实现

async def _api(request: Request, method: str, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
    """以调用方的密钥在进程内调用本服务的 HTTP 接口（同样经过鉴权、校验、任务系统）。"""
    path = "/" + path.lstrip("/")
    if not path.startswith("/api/"):
        path = "/api" + path
    if any(path == p or path.startswith(p + "/") for p in BLOCKED_PATHS):
        raise ValueError("这个接口不对 agent 开放")
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "x-api-key", "cookie")}
    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://novelos.local", timeout=600) as c:
        r = await c.request(method.upper(), path, json=body if body is not None else None, params=query or None, headers=headers)
    try:
        data = r.json()
    except ValueError:
        data = r.text[:4000]
    if r.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        raise ValueError(f"HTTP {r.status_code}：{_txt(detail)[:800]}")
    return data


def _read_tool(name: str, args: dict[str, Any]) -> Any:
    from app.services import agent_tools
    book_id = int(args.pop("book_id"))
    with session_scope() as s:
        if s.get(Book, book_id) is None:
            raise ValueError("作品不存在")
    res = agent_tools.dispatch(agent_tools.ToolCtx(book_id=book_id, session_id=0), name, args)
    if not res.ok:
        raise ValueError(_txt(res.data.get("error") or res.summary))
    return res.data


def _list_books() -> Any:
    with session_scope() as s:
        out = []
        for b in s.exec(select(Book).order_by(Book.id)):
            chs = list(s.exec(select(Chapter).where(Chapter.book_id == b.id)))
            out.append({"id": b.id, "title": b.title, "genre": getattr(b, "genre", ""),
                        "chapters": len(chs), "committed": sum(1 for c in chs if c.status == "committed"),
                        "words": sum(c.words or 0 for c in chs if c.status == "committed")})
        return out


def _chapter_node(s: Any, book_id: int, number: int) -> OutlineNode | None:
    return s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter",
                                            OutlineNode.order == number)).first()


def _chapter_brief(book_id: int, number: int, instruction: str = "", with_rules: bool = True) -> Any:
    from app.services.context import build_context_pack
    from app.skills.loader import system_prompt
    with session_scope() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise ValueError("作品不存在")
        node = _chapter_node(s, book_id, number)
        if node is None:
            raise ValueError(f"第 {number} 章还没有章细纲：先 save_outline_node 建一个 level=chapter、order={number} 的节点")
        pack = build_context_pack(s, book, node, instruction=instruction)
        words = int((node.beats or {}).get("target_words") or getattr(book, "chapter_words", 0) or 2200)
        out: dict[str, Any] = {
            "number": number, "title": node.title, "outline_node_id": node.id, "target_words": words,
            "context": (pack.prefix + "\n\n" + pack.suffix).strip(),
            "preflight": pack.preflight,
        }
        if with_rules:
            try:
                out["writing_rules"] = system_prompt("writing_chapter", platform=getattr(book, "platform_style", None))
            except Exception:  # noqa: BLE001
                pass
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
        elif ch.variants and not ch.content:
            ch.variants = []
            s.add(ch)
            s.commit()
        cid, status = ch.id or 0, ch.status
    ch2 = writing.update_chapter(cid, title, content)
    return {"chapter_id": cid, "number": number, "title": ch2.title, "words": ch2.words, "status": status,
            "lint": (ch2.lint or {}).get("summary") if isinstance(ch2.lint, dict) else None}


def _add_outline_node(args: dict[str, Any]) -> dict[str, Any]:
    book_id = int(args["book_id"])
    level = str(args.get("level") or "chapter")
    if level not in ("book", "volume", "arc", "chapter"):
        raise ValueError("level 只能是 book / volume / arc / chapter")
    with session_scope() as s:
        if s.get(Book, book_id) is None:
            raise ValueError("作品不存在")
        order = int(args.get("order") or 0)
        if level == "chapter" and order and _chapter_node(s, book_id, order) is not None:
            raise ValueError(f"第 {order} 章细纲已存在，用 node_id 修改")
        if not order:
            sib = list(s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == level)))
            order = max([n.order for n in sib] or [0]) + 1
        n = OutlineNode(book_id=book_id, parent_id=args.get("parent_id"), level=level, order=order,
                        title=str(args.get("title") or ""), summary=str(args.get("summary") or ""),
                        beats=args.get("beats") if isinstance(args.get("beats"), dict) else None)
        s.add(n)
        s.commit()
        s.refresh(n)
        return {"node_id": n.id, "level": n.level, "order": n.order, "title": n.title}


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
    out = get_gateway().chat("agent_external", msgs, meta=meta, role=str(args.get("role") or "writer"),
                             temperature=float(args.get("temperature", 0.8)),
                             max_tokens=int(args["max_tokens"]) if args.get("max_tokens") else None,
                             route=str(args["route"]) if args.get("route") else None)
    return out


def _api_index(request: Request, keyword: str = "") -> Any:
    rows = []
    for r in request.app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/") or any(path.startswith(p) for p in BLOCKED_PATHS):
            continue
        doc = (getattr(r, "endpoint", None).__doc__ or "").strip().split("\n")[0] if getattr(r, "endpoint", None) else ""
        for m in sorted(getattr(r, "methods", []) or []):
            if m in ("HEAD", "OPTIONS"):
                continue
            line = f"{m} {path}" + (f"  {doc}" if doc else "")
            if not keyword or keyword.lower() in line.lower():
                rows.append(line)
    return "\n".join(rows) or "没有匹配的接口"


TOOLS: list[dict[str, Any]] = [
    {"name": "guide", "description": "NovelOS 使用说明与推荐流程（第一次接入先读）。", "inputSchema": _schema({})},
    {"name": "list_books", "description": "列出所有作品（id、书名、章数、已提交字数）。", "inputSchema": _schema({})},
    {"name": "create_book", "description": "新建作品。target_words 全书字数，chapter_words 每章字数。",
     "inputSchema": _schema({"title": S, "genre": S, "premise": {**S, "description": "一句话简介/核心设定"},
                             "gender": {**S, "enum": ["male", "female"]}, "target_words": I, "chapter_words": I}, ["title"])},
    {"name": "get_book_info", "description": "读作品信息：书名、题材、简介、核心设定、进度。", "inputSchema": _schema({"book_id": I}, ["book_id"])},
    {"name": "search_bible", "description": "检索设定卡（关键词空格分隔，或按类型）。",
     "inputSchema": _schema({"book_id": I, "query": S, "type": {**S, "enum": ["world", "cheat", "power", "faction", "character", "item", "location"]}}, ["book_id"])},
    {"name": "get_card", "description": "读一张设定卡完整内容。", "inputSchema": _schema({"book_id": I, "card_id": I, "name": S}, ["book_id"])},
    {"name": "get_outline", "description": "读大纲树节点列表，可按 level 过滤。",
     "inputSchema": _schema({"book_id": I, "level": {**S, "enum": ["book", "volume", "arc", "chapter"]}}, ["book_id"])},
    {"name": "get_outline_node", "description": "读一个大纲节点（含章细纲节拍 beats）。", "inputSchema": _schema({"book_id": I, "node_id": I}, ["book_id", "node_id"])},
    {"name": "list_chapters", "description": "列章节（章号、标题、状态、字数、摘要）。", "inputSchema": _schema({"book_id": I}, ["book_id"])},
    {"name": "get_chapter", "description": "读一章：part=summary/excerpt/full（full 最多 8000 字）。",
     "inputSchema": _schema({"book_id": I, "number": I, "chapter_id": I, "part": {**S, "enum": ["summary", "excerpt", "full"]}}, ["book_id"])},
    {"name": "list_foreshadows", "description": "列伏笔底账。", "inputSchema": _schema({"book_id": I, "status": S}, ["book_id"])},
    {"name": "get_style", "description": "读文风卡。", "inputSchema": _schema({"book_id": I}, ["book_id"])},
    {"name": "get_package", "description": "读书名候选、简介、标签、封面提示词。", "inputSchema": _schema({"book_id": I}, ["book_id"])},
    {"name": "get_banned_tropes", "description": "读本书禁用套路。", "inputSchema": _schema({"book_id": I}, ["book_id"])},
    {"name": "find_mentions", "description": "查哪些卡、大纲、正文出现了这些词。", "inputSchema": _schema({"book_id": I, "terms": {"type": "array", "items": S}}, ["book_id", "terms"])},
    {"name": "web_search", "description": "用已配置的联网搜索模型查资料。", "inputSchema": _schema({"book_id": I, "query": S}, ["book_id", "query"])},
    {"name": "save_card", "description": "新建或修改设定卡（给 card_id 就是改，只改传了的字段）。type: world/cheat/faction/character/item/location。"
                                         "金手指卡 data 键：input/limit/growth/cost。",
     "inputSchema": _schema({"book_id": I, "card_id": I, "type": S, "name": S, "summary": S, "data": O,
                             "status": {**S, "enum": ["active", "deprecated"]}}, ["book_id"])},
    {"name": "save_outline_node", "description": "新建或修改大纲节点（给 node_id 就是改）。章细纲 level=chapter、order=全书章号；"
                                                 "beats 是章细纲节拍对象（目标、冲突、爽点、结尾钩子、伏笔等）。",
     "inputSchema": _schema({"book_id": I, "node_id": I, "parent_id": I, "level": {**S, "enum": ["book", "volume", "arc", "chapter"]},
                             "order": I, "title": S, "summary": S, "beats": O}, ["book_id"])},
    {"name": "save_style", "description": "写文风卡。", "inputSchema": _schema({"book_id": I, "tone": S, "voice_notes": S, "pov": {**S, "enum": ["first", "third"]},
                                                                           "sample_text": S}, ["book_id"])},
    {"name": "chapter_brief", "description": "写某章前取上下文：NovelOS 写手同款的章细纲节拍、人物状态、前情、上一章结尾、伏笔、文风与写作规则。",
     "inputSchema": _schema({"book_id": I, "number": I, "instruction": S, "with_rules": B}, ["book_id", "number"])},
    {"name": "save_chapter", "description": "把你写好的正文存为第 number 章（没有就新建草稿，有草稿就覆盖）。commit=true 同时提交入账（后台任务，返回 job）。",
     "inputSchema": _schema({"book_id": I, "number": I, "title": S, "content": S, "commit": B}, ["book_id", "number", "content"])},
    {"name": "commit_chapter", "description": "提交一章入账（生成摘要、更新人物状态与伏笔底账，后台任务）。",
     "inputSchema": _schema({"chapter_id": I}, ["chapter_id"])},
    {"name": "list_models", "description": "列出作者配置的模型渠道和各角色路由。", "inputSchema": _schema({})},
    {"name": "call_model", "description": "用作者配置的模型生成文本。route=「渠道id:模型名」指定模型；不填按 role（writer/planner/reviewer）路由。",
     "inputSchema": _schema({"prompt": S, "system": S, "messages": {"type": "array", "items": O}, "route": S,
                             "role": {**S, "enum": ["writer", "planner", "reviewer", "agent"]}, "temperature": {"type": "number"},
                             "max_tokens": I, "book_id": I}, [])},
    {"name": "get_job", "description": "查后台任务进度与结果。", "inputSchema": _schema({"job_id": I}, ["job_id"])},
    {"name": "api_index", "description": "列出 NovelOS 全部接口（方法 路径 说明），可按关键词过滤。", "inputSchema": _schema({"keyword": S})},
    {"name": "api", "description": "调用任意 NovelOS 接口（路径以 /api/ 开头），用于内置流程：写下一章、一键成书、审稿、生成大纲、包装等。",
     "inputSchema": _schema({"method": {**S, "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]}, "path": S, "body": O, "query": O}, ["method", "path"])},
]


async def _call(request: Request, name: str, a: dict[str, Any]) -> Any:
    if name == "guide":
        return GUIDE
    if name == "list_books":
        return await anyio.to_thread.run_sync(_list_books)
    if name == "create_book":
        body = {k: a[k] for k in ("title", "genre", "premise", "gender", "target_words", "chapter_words") if a.get(k) is not None}
        return await _api(request, "POST", "/api/books", body)
    if name in READ_TOOLS:
        return await anyio.to_thread.run_sync(_read_tool, name, dict(a))
    if name == "save_card":
        bid = int(a["book_id"])
        fields = {k: a[k] for k in ("type", "name", "summary", "data", "status") if a.get(k) is not None}
        if a.get("card_id"):
            return await _api(request, "PUT", f"/api/cards/{int(a['card_id'])}", fields)
        if not fields.get("type") or not fields.get("name"):
            raise ValueError("新建设定卡要给 type 和 name")
        return await _api(request, "POST", f"/api/books/{bid}/cards", fields)
    if name == "save_outline_node":
        if a.get("node_id"):
            fields = {k: a[k] for k in ("title", "summary", "beats", "order") if a.get(k) is not None}
            return await _api(request, "PUT", f"/api/outline/{int(a['node_id'])}", fields)
        return await anyio.to_thread.run_sync(_add_outline_node, dict(a))
    if name == "save_style":
        bid = int(a["book_id"])
        cur = await _api(request, "GET", f"/api/books/{bid}/style")
        cur = cur if isinstance(cur, dict) else {}
        body = {k: (a[k] if a.get(k) is not None else cur.get(k)) for k in ("tone", "voice_notes", "pov", "sample_text")}
        body = {k: v for k, v in body.items() if v is not None}
        return await _api(request, "PUT", f"/api/books/{bid}/style", body)
    if name == "chapter_brief":
        return await anyio.to_thread.run_sync(_chapter_brief, int(a["book_id"]), int(a["number"]),
                                              str(a.get("instruction") or ""), a.get("with_rules", True) is not False)
    if name == "save_chapter":
        content = str(a.get("content") or "")
        if not content.strip():
            raise ValueError("content 不能为空")
        r = await anyio.to_thread.run_sync(_save_chapter, int(a["book_id"]), int(a["number"]), a.get("title"), content)
        if a.get("commit"):
            if r["status"] == "committed":
                r["note"] = "这一章之前已提交，正文已更新，底账不重算"
            else:
                r["job"] = await _api(request, "POST", f"/api/chapters/{r['chapter_id']}/commit")
        return r
    if name == "commit_chapter":
        return await _api(request, "POST", f"/api/chapters/{int(a['chapter_id'])}/commit")
    if name == "list_models":
        return await anyio.to_thread.run_sync(_list_models)
    if name == "call_model":
        return await anyio.to_thread.run_sync(_call_model, dict(a))
    if name == "get_job":
        return await _api(request, "GET", f"/api/jobs/{int(a['job_id'])}")
    if name == "api_index":
        return _api_index(request, str(a.get("keyword") or ""))
    if name == "api":
        return await _api(request, str(a.get("method") or "GET"), str(a.get("path") or ""),
                          a.get("body"), a.get("query") if isinstance(a.get("query"), dict) else None)
    raise ValueError(f"没有这个工具：{name}")


# ------------------------------------------------------------------ JSON-RPC

def _ok(mid: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, msg: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


async def _handle(request: Request, msg: dict[str, Any]) -> dict[str, Any] | None:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # 通知，不回
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        ver = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _ok(mid, {"protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": {"name": "novelos", "version": __version__},
                         "instructions": GUIDE})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method in ("resources/list", "resources/templates/list"):
        return _ok(mid, {"resources": [], "resourceTemplates": []})
    if method == "prompts/list":
        return _ok(mid, {"prompts": []})
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        try:
            out = await _call(request, name, args if isinstance(args, dict) else {})
            return _ok(mid, {"content": [{"type": "text", "text": _txt(out)}], "isError": False})
        except Exception as e:  # noqa: BLE001  工具错误回给模型，不断连接
            text = str(e) if isinstance(e, (ValueError, KeyError)) else f"{type(e).__name__}: {e}"
            if isinstance(e, KeyError):
                text = f"缺少参数 {e}"
            return _ok(mid, {"content": [{"type": "text", "text": text[:2000]}], "isError": True})
    return _err(mid, -32601, f"不支持的方法：{method}")


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(_err(None, -32700, "不是合法 JSON"), status_code=400)
    if isinstance(payload, list):
        res = [r for r in [await _handle(request, m) for m in payload if isinstance(m, dict)] if r is not None]
        return JSONResponse(res) if res else Response(status_code=202)
    if not isinstance(payload, dict):
        return JSONResponse(_err(None, -32600, "请求格式不对"), status_code=400)
    res = await _handle(request, payload)
    return JSONResponse(res) if res is not None else Response(status_code=202)


@router.get("/mcp")
async def mcp_get() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


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
