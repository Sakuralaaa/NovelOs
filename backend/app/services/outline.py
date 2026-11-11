"""大纲：总纲 → 卷 → 弧 → 章细纲，滚动展开。chapter 级节点的 order 即全书章号。"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, func, select

from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Book, OutlineNode, utcnow
from app.services import common
from app.services.common import Conflict, NotFound
from app.skills.loader import render, system_prompt

OUTCOMES = ("yes", "no", "yes-but", "no-and")
CHAPTERS_PER_ARC = 5


def normalize_beats(raw: dict[str, Any], number: int, chapter_words: int) -> dict[str, Any]:
    fs = []
    for f in raw.get("foreshadow") or []:
        if isinstance(f, dict) and f.get("action") in ("plant", "advance", "resolve"):
            fid = f.get("id")
            fs.append({"action": f["action"], "id": fid if isinstance(fid, int) else None, "desc": str(f.get("desc", ""))})
    outcome = raw.get("outcome") if raw.get("outcome") in OUTCOMES else "yes-but"
    chars = [str(c) for c in (raw.get("characters") or []) if c]
    return {
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
        root = OutlineNode(book_id=book_id, level="book", order=1, title=str(bk.get("title") or book.title),
                           summary=str(bk.get("summary", "")), status="expanded")
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
        s.commit()
    return {"volumes": len(vols), "chapters": chapters_total}


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
        meta = {**common.kit_meta(s, book), "level": node.level, "existing": len(kids),
                "next_number": max_chapter_number(s, book.id or 0) + 1, "chapters_per_arc": CHAPTERS_PER_ARC,
                "number": node.order}
        if node.level == "book":
            instruction, schema = "再规划 2 卷。", '{"volumes":[{"title":"","summary":""}]}'
        elif node.level == "volume":
            instruction, schema = "为这一卷规划接下来的 2 个弧。", '{"arcs":[{"title":"","summary":""}]}'
        elif node.level == "arc":
            instruction = f"为这一弧写 {CHAPTERS_PER_ARC} 章细纲（章号从 {meta['next_number']} 开始）。"
            schema = ('{"chapters":[{"title":"","goal":"","conflict":"","outcome":"yes|no|yes-but|no-and","payoff":"",'
                      '"characters":[],"location":"","foreshadow":[{"action":"plant|advance|resolve","id":null,"desc":""}],"hook_end":""}]}')
        else:
            instruction = "把这一章细纲补充完整。"
            schema = '{"beats":{"title":"","goal":"","conflict":"","outcome":"","payoff":"","characters":[],"location":"","foreshadow":[],"hook_end":""}}'
        user = render(
            "expand", book_context=common.book_context(s, book), node_level=node.level, node_title=node.title,
            node_summary=node.summary, siblings="、".join(siblings) or "无",
            recent="\n".join(f"第{c.number}章：{c.summary}" for c in recent) or "无",
            open_foreshadows="\n".join(f"#{f.id} {f.desc}" for f in opens) or "无",
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
        s.commit()
        return {"node_id": node_id, "created": [c.id for c in created]}


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
