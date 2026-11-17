"""v0.13 章节工具：AI 章名、脑洞抽卡、神评（锚定原句）、查找替换、高频词、排版、写作笔记。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.llm.gateway import get_gateway
from app.models.tables import Chapter, Foreshadow, Note, OutlineNode, utcnow
from app.services import card_versions, common
from app.services.common import Conflict, NotFound
from app.services.review import _norm, quote_in_text
from app.skills.loader import render, system_prompt

# ------------------------------------------------------------------ 公共

_PARA_SPLIT = re.compile(r"\n+")


def _para_index(text: str, pos: int) -> int:
    return len([p for p in _PARA_SPLIT.split(text[:pos]) if p.strip()]) - (0 if text[:pos].endswith("\n") or pos == 0 else 1)


def locate(quote: str, content: str) -> dict[str, Any] | None:
    """原句在正文里的位置（先精确找，找不到按去空白匹配回推）。找不到返回 None。"""
    q = quote.strip().strip("\"'「」“”")
    if not q:
        return None
    i = content.find(q)
    if i < 0:
        nq, nc = _norm(q), ""
        idx_map: list[int] = []
        for k, ch in enumerate(content):
            n = _norm(ch)
            if n:
                nc += n
                idx_map.extend([k] * len(n))
        j = nc.find(nq)
        if j < 0 or not nq:
            return None
        i = idx_map[j]
        end = idx_map[min(len(idx_map) - 1, j + len(nq) - 1)] + 1
        q = content[i:end]
    return {"offset": i, "paragraph": max(0, _para_index(content, i)), "match": q}


def _chapter(s: Session, chapter_id: int) -> Chapter:
    ch = s.get(Chapter, chapter_id)
    if ch is None:
        raise NotFound("章节不存在")
    return ch


def _plan_of(s: Session, ch: Chapter) -> tuple[str, dict[str, Any]]:
    node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
    if node is None:
        node = s.exec(select(OutlineNode).where(OutlineNode.book_id == ch.book_id, OutlineNode.level == "chapter",
                                                OutlineNode.order == ch.number)).first()
    if node is None:
        return "（无细纲）", {}
    beats = node.beats or {}
    bits = [node.title, node.summary or ""] + [f"{k}：{v}" for k, v in beats.items() if k in ("goal", "conflict", "payoff", "hook", "must_avoid") and v]
    return "\n".join(b for b in bits if b), beats


def _excerpt(content: str, head: int = 2500, tail: int = 800) -> str:
    return content if len(content) <= head + tail else content[:head] + "\n……\n" + content[-tail:]


# ------------------------------------------------------------------ AI 章名

_CLICHE = ("风云再起", "暗流涌动", "初露锋芒", "一鸣惊人", "峰回路转", "意想不到", "震惊", "不可思议")
_HOOK = re.compile(r"[0-9０-９一二三四五六七八九十百千万]+|打脸|翻盘|跪|当场|一拳|一剑|退婚|送上门|反杀|亲手|全场|满级|撞上")


def _bigrams(t: str) -> set[str]:
    t = re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]", "", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def score_title(title: str, neighbors: list[str], must_avoid: list[str]) -> tuple[int, list[str]]:
    """程序打分（0–100）：长度、钩子词、和相邻章名不重复、不碰细纲禁区、不用套话。"""
    notes: list[str] = []
    n = len(re.sub(r"\s", "", title))
    sc = 60
    if 5 <= n <= 12:
        sc += 15
    elif n < 4 or n > 16:
        sc -= 20
        notes.append("太短" if n < 4 else "太长")
    if _HOOK.search(title):
        sc += 10
    if any(c in title for c in _CLICHE):
        sc -= 25
        notes.append("套话")
    if re.search(r"[？?！!]{1,}$", title):
        sc -= 5
    bg = _bigrams(title)
    for nb in neighbors:
        if nb and len(bg & _bigrams(nb)) >= 2:
            sc -= 15
            notes.append("和相邻章名撞词")
            break
    for w in must_avoid:
        w = str(w).strip()
        if len(w) >= 2 and w in title:
            sc -= 30
            notes.append("碰到细纲禁区")
            break
    return max(0, min(100, sc)), notes


def chapter_titles(chapter_id: int, n: int = 6) -> dict[str, Any]:
    n = max(3, min(9, n))
    with session_scope() as s:
        ch = _chapter(s, chapter_id)
        if not ch.content.strip():
            raise Conflict("章节还没有正文")
        plan, beats = _plan_of(s, ch)
        nbs = s.exec(select(Chapter).where(Chapter.book_id == ch.book_id, Chapter.number.in_([ch.number - 2, ch.number - 1, ch.number + 1]))).all()  # type: ignore[attr-defined]
        neighbors = [c.title for c in nbs if c.title]
        meta = {**common.kit_meta(s, common.get_book(s, ch.book_id)), "number": ch.number, "content": ch.content, "n": n}
        content, number, current = ch.content, ch.number, ch.title
    must_avoid = beats.get("must_avoid") if isinstance(beats.get("must_avoid"), list) else (
        [beats["must_avoid"]] if isinstance(beats.get("must_avoid"), str) and beats.get("must_avoid") else [])
    user = render("chapter_titles", number=number, chapter_plan=plan, neighbors="、".join(neighbors) or "（无）",
                  content=_excerpt(content), n=n)
    out = get_gateway().chat_json("chapter_titles", system_prompt("chapter_titles"), user, meta=meta, temperature=0.9)
    raw = out.get("titles") if isinstance(out, dict) else out
    seen: set[str] = set()
    items = []
    for it in raw or []:
        t = str((it.get("title") if isinstance(it, dict) else it) or "").strip().strip("《》\"“”")
        t = re.sub(rf"^第[0-9０-９零〇一二两三四五六七八九十百千万]+章[\s:：]*", "", t)
        if not t or t in seen:
            continue
        seen.add(t)
        sc, notes = score_title(t, neighbors, must_avoid)
        items.append({"title": t[:30], "reason": str(it.get("reason") or "")[:80] if isinstance(it, dict) else "", "score": sc, "notes": notes})
    items.sort(key=lambda x: -x["score"])
    return {"chapter_id": chapter_id, "number": number, "current": current, "titles": items}


# ------------------------------------------------------------------ 脑洞抽卡

def sparks(book_id: int, n: int = 5, use_context: bool = True, hint: str = "") -> dict[str, Any]:
    n = max(3, min(8, n))
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = {**common.kit_meta(s, book), "n": n}
        ctx = ""
        if use_context:
            chs = common.committed_chapters(s, book_id)[-5:]
            cs = [c for c in common.cards(s, book_id) if c.type in ("character", "cheat", "faction", "world")][:12]
            fs = s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id, Foreshadow.status.in_(["planted", "advancing"]))).all()[:8]  # type: ignore[attr-defined]
            parts = [f"简介：{book.premise or book.tagline or '（无）'}"]
            if cs:
                parts.append("主要设定：\n" + "\n".join(f"- {c.name}：{(c.summary or '')[:60]}" for c in cs))
            if chs:
                parts.append("最近几章：\n" + "\n".join(f"- 第{c.number}章：{(c.summary or c.content[:120])[:160]}" for c in chs))
            if fs:
                parts.append("还没回收的伏笔：\n" + "\n".join(f"- {f.desc[:60]}" for f in fs))
            ctx = "\n\n".join(parts)
        else:
            ctx = f"题材：{book.genre or '网文'}"
        title = book.title
    user = render("sparks", title=title, n=n, context=ctx, hint=hint.strip()[:300] or "（无）")
    out = get_gateway().chat_json("sparks", system_prompt("sparks"), user, meta=meta, temperature=1.0)
    raw = out.get("sparks") if isinstance(out, dict) else out
    items = [{"title": str(x.get("title") or "")[:40], "beat": str(x.get("beat") or "")[:600], "payoff": str(x.get("payoff") or "")[:120],
              "fit": str(x.get("fit") or "")[:20]} for x in raw or [] if isinstance(x, dict) and x.get("title")]
    return {"book_id": book_id, "sparks": items[:n]}


# ------------------------------------------------------------------ 神评

PERSONAS = {
    "male": [("老书虫", "刷了几百本男频，最烦注水和憋屈，爱挑逻辑漏洞"),
             ("通勤党", "地铁上单手刷，没耐心，开头三句没冲突就划走"),
             ("爽点猎人", "只看打脸和升级，爽到会刷「好！」「下一章」"),
             ("考据党", "爱算战力和时间线，数字对不上就开喷"),
             ("段子手", "专门在段评里玩梗、吐槽配角")],
    "female": [("甜宠党", "只看男女主互动，心动了会尖叫"),
               ("虐文爱好者", "喜欢情绪拉满，嫌主角太顺"),
               ("通勤党", "地铁上单手刷，没耐心，开头三句没冲突就划走"),
               ("人设党", "人设崩一点就弃书，最在意角色说话像不像本人"),
               ("段子手", "专门在段评里玩梗、吐槽配角")],
}


def reader_comments(chapter_id: int, personas: int = 4) -> dict[str, Any]:
    with session_scope() as s:
        ch = _chapter(s, chapter_id)
        if not ch.content.strip():
            raise Conflict("章节还没有正文")
        book = common.get_book(s, ch.book_id)
        ps = PERSONAS["female" if book.gender == "female" else "male"][: max(2, min(5, personas))]
        meta = {**common.kit_meta(s, book), "number": ch.number, "content": ch.content, "personas": [p for p, _ in ps]}
        content, number = ch.content, ch.number
    user = render("reader_comments", number=number, content=content, personas="\n".join(f"- {p}：{d}" for p, d in ps))
    out = get_gateway().chat_json("reader_comments", system_prompt("reader_comments"), user, meta=meta, temperature=0.9)
    out = out if isinstance(out, dict) else {}
    comments, dropped = [], 0
    for c in out.get("comments") or []:
        if not isinstance(c, dict) or not str(c.get("text") or "").strip():
            continue
        q = str(c.get("quote") or "")
        pos = locate(q, content) if quote_in_text(q, content, 4) else None
        if pos is None:
            dropped += 1
            continue
        comments.append({"persona": str(c.get("persona") or "读者")[:12], "quote": pos["match"], "text": str(c["text"]).strip()[:140],
                         "mood": str(c.get("mood") or "")[:2], "offset": pos["offset"], "paragraph": pos["paragraph"]})
    comments.sort(key=lambda x: x["offset"])
    verdicts = []
    for v in out.get("verdicts") or []:
        if not isinstance(v, dict):
            continue
        d = str(v.get("drop") or "")
        dpos = locate(d, content) if d and quote_in_text(d, content, 4) else None
        verdicts.append({"persona": str(v.get("persona") or "读者")[:12], "will_continue": bool(v.get("will_continue")),
                         "drop": dpos["match"] if dpos else "", "drop_offset": dpos["offset"] if dpos else None, "why": str(v.get("why") or "")[:120]})
    keep = sum(1 for v in verdicts if v["will_continue"])
    drops = [v for v in verdicts if v["drop"]]
    instruction = ""
    if drops:
        instruction = "按读者段评修改：\n" + "\n".join(f"- 「{v['drop'][:40]}」这里{v['persona']}想划走：{v['why'] or '节奏拖'}" for v in drops)
    return {"chapter_id": chapter_id, "number": number, "comments": comments, "verdicts": verdicts, "dropped": dropped,
            "continue_rate": round(keep / len(verdicts), 2) if verdicts else None, "instruction": instruction}


# ------------------------------------------------------------------ 高频词

_STOP = set("的了是在我你他她它们这那就也都还又和与及而且但却被把给让对从向到着过得地之其个一不有没人说道看去来上下里中后前时候自己什么怎么没有一个已经知道这个那个可以现在然后因为所以如果虽然只是还是就是不是")


def freq(text: str, exclude: list[str] | None = None, top: int = 40, min_count: int = 3) -> list[dict[str, Any]]:
    """2–4 字高频片段（排除设定库人名等专名、虚词开头/结尾、被更长片段完全覆盖的子串）。"""
    ex = [e for e in (exclude or []) if e]
    runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    total = sum(len(r) for r in runs) or 1
    cnt: Counter[str] = Counter()
    for r in runs:
        for n in (2, 3, 4):
            for i in range(len(r) - n + 1):
                g = r[i:i + n]
                if g[0] in _STOP or g[-1] in _STOP:
                    continue
                cnt[g] += 1
    cands = {g: c for g, c in cnt.items() if c >= min_count and not any(g in e or e in g for e in ex)}
    keep = {}
    for g, c in sorted(cands.items(), key=lambda x: -len(x[0])):
        if any(g in k and keep[k] >= c * 0.8 for k in keep):  # 被更长的片段覆盖
            continue
        keep[g] = c
    rows = sorted(keep.items(), key=lambda x: (-x[1] * (1 + 0.3 * (len(x[0]) - 2)), x[0]))[:top]
    return [{"word": g, "count": c, "per_10k": round(c * 10000 / total, 1)} for g, c in rows]


def chapter_freq(chapter_id: int) -> dict[str, Any]:
    with session_scope() as s:
        ch = _chapter(s, chapter_id)
        names = [c.name for c in common.cards(s, ch.book_id, include_deprecated=True)]
        return {"chapter_id": chapter_id, "items": freq(ch.content, names, top=40, min_count=3)}


def book_freq(book_id: int, start: int | None = None, end: int | None = None) -> dict[str, Any]:
    with session_scope() as s:
        common.get_book(s, book_id)
        q = select(Chapter).where(Chapter.book_id == book_id)
        if start:
            q = q.where(Chapter.number >= start)
        if end:
            q = q.where(Chapter.number <= end)
        chs = s.exec(q).all()
        names = [c.name for c in common.cards(s, book_id, include_deprecated=True)]
        text = "\n".join(c.content for c in chs)
        return {"book_id": book_id, "chapters": len(chs), "items": freq(text, names, top=60, min_count=max(3, len(chs)))}


# ------------------------------------------------------------------ 排版（纯代码）

def format_text(text: str) -> tuple[str, list[str]]:
    """规范化：段落去首尾空白、段间一个空行、中文引号成对、省略号「……」、破折号「——」、去掉中文之间多余空格。"""
    notes: list[str] = []
    t = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    paras = [p.strip() for p in t.split("\n") if p.strip()]
    out = []
    for p in paras:
        o = p
        p = re.sub(r"(?<=[\u4e00-\u9fff，。！？；：、”’）])\s+(?=[\u4e00-\u9fff“‘（])", "", p)
        p = re.sub(r"\.{3,}|。{3,}|…(?!…)|(?<!…)…{3,}", "……", p)
        p = re.sub(r"……+", "……", p)
        p = re.sub(r"(?<![—])[—－-]{2,}(?![—])|(?<=[\u4e00-\u9fff])—(?=[\u4e00-\u9fff])", "——", p)
        if p.count('"') >= 2 and p.count('"') % 2 == 0:
            k = 0

            def _q(_m: re.Match[str]) -> str:
                nonlocal k
                k += 1
                return "“" if k % 2 else "”"
            p = re.sub('"', _q, p)
        p = re.sub(r"(?<=[\u4e00-\u9fff]),", "，", p)
        p = re.sub(r"(?<=[\u4e00-\u9fff])\?", "？", p)
        p = re.sub(r"(?<=[\u4e00-\u9fff])!", "！", p)
        p = re.sub(r"(?<=[\u4e00-\u9fff]):(?=[“\u4e00-\u9fff])", "：", p)
        if o != p:
            notes.append(p[:20])
        out.append(p)
    res = "\n\n".join(out)
    long_n = sum(1 for p in out if len(p) > 100)
    msgs = []
    if notes:
        msgs.append(f"{len(notes)} 段标点或空格已规范")
    if res.count("\n\n") != text.count("\n\n"):
        msgs.append("段落间距已统一")
    if long_n:
        msgs.append(f"{long_n} 段超过 100 字，手机上偏长，建议拆开")
    return res, msgs


# ------------------------------------------------------------------ 查找替换

SCOPES = ("chapters", "cards", "outline", "notes")
MAX_HITS = 500


def _matcher(q: str, regex: bool, case: bool = True) -> re.Pattern[str]:
    if not q:
        raise ValueError("要找的内容不能为空")
    try:
        return re.compile(q if regex else re.escape(q), 0 if case else re.I)
    except re.error as e:
        raise ValueError(f"正则写得不对：{e}") from e


def _targets(s: Session, book_id: int, scopes: list[str]) -> list[tuple[str, Any, str, str, str]]:
    """→ [(scope, obj, field, label, text)]"""
    out: list[tuple[str, Any, str, str, str]] = []
    if "chapters" in scopes:
        for c in s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number)):  # type: ignore[arg-type]
            out.append(("chapters", c, "title", f"第{c.number}章 章名", c.title or ""))
            out.append(("chapters", c, "content", f"第{c.number}章 {c.title}", c.content or ""))
    if "cards" in scopes:
        for c in common.cards(s, book_id, include_deprecated=True):
            out.append(("cards", c, "name", f"设定·{c.name} 名称", c.name))
            out.append(("cards", c, "summary", f"设定·{c.name}", c.summary or ""))
            for k, v in (c.data or {}).items():
                if isinstance(v, str):
                    out.append(("cards", c, f"data.{k}", f"设定·{c.name}·{k}", v))
    if "outline" in scopes:
        for n in common.outline_nodes(s, book_id):
            out.append(("outline", n, "title", f"大纲·{n.title or n.level} 标题", n.title or ""))
            out.append(("outline", n, "summary", f"大纲·{n.title or n.level}", n.summary or ""))
    if "notes" in scopes:
        for n in s.exec(select(Note).where(Note.book_id == book_id)):
            out.append(("notes", n, "title", f"笔记·{n.title} 标题", n.title or ""))
            out.append(("notes", n, "content", f"笔记·{n.title}", n.content or ""))
    return out


def search(book_id: int, q: str, scopes: list[str] | None = None, regex: bool = False, case: bool = True) -> dict[str, Any]:
    pat = _matcher(q, regex, case)
    scopes = [x for x in (scopes or ["chapters"]) if x in SCOPES] or ["chapters"]
    hits: list[dict[str, Any]] = []
    total = 0
    by_scope: Counter[str] = Counter()
    with session_scope() as s:
        common.get_book(s, book_id)
        for scope, obj, field, label, text in _targets(s, book_id, scopes):
            for m in pat.finditer(text):
                if m.end() == m.start():
                    continue
                total += 1
                by_scope[scope] += 1
                if len(hits) < MAX_HITS:
                    hits.append({"scope": scope, "id": obj.id, "field": field, "label": label, "offset": m.start(),
                                 "before": text[max(0, m.start() - 24):m.start()], "match": m.group(0), "after": text[m.end():m.end() + 24],
                                 "locked": bool(getattr(obj, "locked", False)),
                                 "chapter_id": obj.id if scope == "chapters" else None})
    return {"q": q, "regex": regex, "total": total, "by_scope": dict(by_scope), "hits": hits, "truncated": total > len(hits)}


def replace(book_id: int, q: str, repl: str, scopes: list[str] | None = None, regex: bool = False, case: bool = True,
            expect: int | None = None, skip: list[str] | None = None) -> dict[str, Any]:
    """执行替换：章节旧稿进历史（可撤回），设定卡存一版、大纲节点存一版，锁定的设定和大纲跳过。
    expect 是预览时的命中总数，对不上说明内容变了，要求重新预览。skip 为不替换的命中「scope:id:field:offset」。"""
    from app.services.writing import count_words, lint_for, push_history

    pat = _matcher(q, regex, case)
    scopes = [x for x in (scopes or ["chapters"]) if x in SCOPES] or ["chapters"]
    skip_set = set(skip or [])
    changed: Counter[str] = Counter()
    n_rep = 0
    skipped_locked: list[str] = []
    with session_scope() as s:
        common.get_book(s, book_id)
        targets = _targets(s, book_id, scopes)
        total = sum(1 for *_, t in targets for m in pat.finditer(t) if m.end() > m.start())
        if expect is not None and expect != total:
            raise Conflict(f"内容变了（预览时 {expect} 处，现在 {total} 处），请重新查找")
        before_state: dict[tuple[str, int], Any] = {}
        for scope, obj, field, label, text in targets:
            if scope in ("cards", "outline") and getattr(obj, "locked", False):
                if any(True for _ in pat.finditer(text)):
                    skipped_locked.append(label)
                continue

            def _sub(m: re.Match[str], _sc: str = scope, _id: int = obj.id, _f: str = field) -> str:
                nonlocal n_rep
                if m.end() == m.start() or f"{_sc}:{_id}:{_f}:{m.start()}" in skip_set:
                    return m.group(0)
                n_rep += 1
                return m.expand(repl) if regex else repl
            try:
                new = pat.sub(_sub, text)
            except (re.error, IndexError) as e:
                raise ValueError(f"替换内容写得不对：{e}") from e
            if new == text:
                continue
            key = (scope, obj.id)
            if key not in before_state:
                if scope == "chapters":
                    push_history(obj, f"查找替换「{q[:12]}」前")
                elif scope == "cards":
                    card_versions.push(obj, f"查找替换「{q[:12]}」前")
                elif scope == "outline":
                    obj.versions = [*(obj.versions or []), {"title": obj.title, "summary": obj.summary, "beats": obj.beats, "label": "查找替换前",
                                                            "at": utcnow().isoformat()}][-20:]
                before_state[key] = True
                changed[scope] += 1
            if field.startswith("data."):
                obj.data = {**(obj.data or {}), field[5:]: new}
            else:
                setattr(obj, field, new)
            if scope == "chapters" and field == "content":
                obj.words = count_words(new)
            if hasattr(obj, "updated_at"):
                obj.updated_at = utcnow()
            s.add(obj)
        for (scope, oid), _ in before_state.items():
            if scope == "chapters":
                ch = s.get(Chapter, oid)
                if ch is not None:
                    ch.lint = lint_for(s, book_id, ch.content, ch.number, ch.id).to_dict()
                    s.add(ch)
        s.commit()
    return {"replaced": n_rep, "changed": dict(changed), "skipped_locked": skipped_locked}


# ------------------------------------------------------------------ 写作笔记

def note_out(n: Note) -> dict[str, Any]:
    return {"id": n.id, "book_id": n.book_id, "folder": n.folder, "title": n.title, "content": n.content, "tags": n.tags or [],
            "pinned": n.pinned, "source": n.source, "created_at": n.created_at.isoformat() if n.created_at else None,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None}


def list_notes(s: Session, book_id: int, q: str = "", folder: str | None = None) -> list[dict[str, Any]]:
    common.get_book(s, book_id)
    rows = list(s.exec(select(Note).where(Note.book_id == book_id)))
    if folder is not None:
        rows = [n for n in rows if n.folder == folder]
    if q.strip():
        k = q.strip().lower()
        rows = [n for n in rows if k in n.title.lower() or k in n.content.lower() or any(k in t.lower() for t in n.tags or [])]
    rows.sort(key=lambda n: (not n.pinned, -(n.updated_at.timestamp() if n.updated_at else 0)))
    return [note_out(n) for n in rows]


def _clean_note(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "title" in d:
        out["title"] = str(d["title"] or "").strip()[:80]
    if "folder" in d:
        out["folder"] = str(d["folder"] or "").strip().strip("/")[:40]
    if "content" in d:
        out["content"] = str(d["content"] or "")[:50000]
    if "tags" in d:
        out["tags"] = list(dict.fromkeys(str(t).strip()[:20] for t in (d["tags"] or []) if str(t).strip()))[:12]
    if "pinned" in d:
        out["pinned"] = bool(d["pinned"])
    if "source" in d and (d["source"] is None or isinstance(d["source"], dict)):
        out["source"] = d["source"]
    return out


def create_note(s: Session, book_id: int, d: dict[str, Any]) -> dict[str, Any]:
    common.get_book(s, book_id)
    data = _clean_note(d)
    if not data.get("title"):
        data["title"] = (data.get("content") or "").strip().split("\n")[0][:30] or "未命名笔记"
    n = Note(book_id=book_id, **data)
    s.add(n)
    s.commit()
    s.refresh(n)
    return note_out(n)


def update_note(s: Session, book_id: int, note_id: int, d: dict[str, Any]) -> dict[str, Any]:
    n = s.get(Note, note_id)
    if n is None or n.book_id != book_id:
        raise NotFound("笔记不存在")
    for k, v in _clean_note(d).items():
        setattr(n, k, v)
    if not n.title:
        n.title = "未命名笔记"
    n.updated_at = utcnow()
    s.add(n)
    s.commit()
    s.refresh(n)
    return note_out(n)


def delete_note(s: Session, book_id: int, note_id: int) -> None:
    n = s.get(Note, note_id)
    if n is None or n.book_id != book_id:
        raise NotFound("笔记不存在")
    s.delete(n)
    s.commit()


def export_notes_md(s: Session, book_id: int) -> str:
    book = common.get_book(s, book_id)
    rows = list(s.exec(select(Note).where(Note.book_id == book_id)))
    rows.sort(key=lambda n: (n.folder, n.id or 0))
    out = [f"# 《{book.title}》写作笔记", ""]
    cur = None
    for n in rows:
        if n.folder != cur:
            cur = n.folder
            out += [f"## {cur or '未归类'}", ""]
        out += [f"### {n.title}", ""]
        if n.tags:
            out += ["标签：" + "、".join(n.tags), ""]
        out += [n.content.strip(), ""]
    return "\n".join(out).rstrip() + "\n"


def import_notes_md(s: Session, book_id: int, text: str, folder: str = "") -> dict[str, Any]:
    """Markdown 导入：「## 目录」下的「### 标题」各成一条；没有 ### 时按 # / ## 切；都没有就整篇一条。"""
    common.get_book(s, book_id)
    text = (text or "").replace("\r\n", "\n")
    if not text.strip():
        raise ValueError("没有内容")
    made = 0
    cur_folder = folder.strip()[:40]
    level = 3 if re.search(r"^###\s", text, re.M) else (2 if re.search(r"^##\s", text, re.M) else (1 if re.search(r"^#\s", text, re.M) else 0))
    if level == 0:
        s.add(Note(book_id=book_id, folder=cur_folder, title=text.strip().split("\n")[0][:30], content=text.strip()[:50000]))
        s.commit()
        return {"created": 1}
    title, buf = None, []

    def flush() -> None:
        nonlocal made, title, buf
        body = "\n".join(buf).strip()
        if title is not None and (title or body):
            tags: list[str] = []
            m = re.match(r"^标签[:：](.+)$", body.split("\n")[0]) if body else None
            if m:
                tags = [t.strip() for t in re.split(r"[、,，]", m.group(1)) if t.strip()][:12]
                body = "\n".join(body.split("\n")[1:]).strip()
            s.add(Note(book_id=book_id, folder=cur_folder, title=(title or "未命名笔记")[:80], content=body[:50000], tags=tags))
            made += 1
        title, buf = None, []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and len(m.group(1)) <= level:
            depth = len(m.group(1))
            if depth == level:
                flush()
                title = m.group(2).strip()
                continue
            if depth == level - 1:
                flush()
                cur_folder = "" if m.group(2).strip() in ("未归类",) else m.group(2).strip()[:40]
                continue
            flush()
            continue
        buf.append(line)
    flush()
    s.commit()
    return {"created": made}


def spark_to_note(s: Session, book_id: int, spark: dict[str, Any]) -> dict[str, Any]:
    body = "\n\n".join(x for x in [str(spark.get("beat") or ""), f"爽点：{spark.get('payoff')}" if spark.get("payoff") else "",
                                      f"适合：{spark.get('fit')}" if spark.get("fit") else ""] if x)
    return create_note(s, book_id, {"folder": "脑洞", "title": str(spark.get("title") or "脑洞"), "content": body, "source": {"kind": "spark"}})

