"""v0.12 E1 导入已有作品 + 接管旧书 + 大纲文本导入。

- 导入（commit）：作者确认后的卷章列表 → 建书、章节直接是 committed（正文入库），同时建大纲骨架
  （总纲 → 卷 → 每 10 章一个弧 → 已成文的章节点），末尾留一个空弧，续写时滚动规划从这里展开下一章细纲。
- 接管（adopt，Job kind=book_adopt）：按章节区间分批，每批依次「摘要 → 反推设定卡 → 回填事实/伏笔账本 → 反推章细纲」。
  每完成一个单元（一章或一批）记进度（KV adopt:{book_id}）并写断点；可暂停、可续跑、可分多次跑不同区间，
  已完成的单元自动跳过。设定卡里新名字直接建卡，改到作者自己的卡时进冲突审阅（待采纳提案），不直接覆盖。
- 大纲导入（Job kind=outline_import）：粘贴已有大纲/卷纲/章纲文本 → 程序先切出骨架 → 模型结构化成节点 → 预览；
  作者采纳（outline/import/apply）才写库，两种写法：按章号合并（fill）或接在现有大纲后面（append）。
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from typing import Any

from sqlmodel import Session, select

from app.db import kv_get, kv_set, session_scope
from app.jobs.manager import JobContext, register_resumable
from app.llm.gateway import get_gateway
from app.models.tables import Book, Card, Chapter, Fact, Foreshadow, OutlineNode, Style, utcnow
from app.services import common
from app.services.changes import CARD_TYPES, ChangeSet, check_against_ledger, match_foreshadow, parse_changes
from app.services.common import Conflict, NotFound
from app.services.import_text import ImportError_, MAX_CHAPTERS, count_words, parse_outline
from app.services.outline import normalize_beats, push_node_version
from app.skills.loader import render, system_prompt

from app.llm.mock_import import register as _register_mock  # noqa: E402

_register_mock()  # 演示模式处理函数 + 任务角色 + 规则包映射（不改共享文件）

ADOPT_KIND = "book_adopt"
OUTLINE_IMPORT_KIND = "outline_import"
STEPS = ("summary", "bible", "ledger", "outline")
STEP_LABEL = {"summary": "章节摘要", "bible": "反推设定卡", "ledger": "回填事实/伏笔账本", "outline": "反推章细纲"}
ARC_SIZE = 10  # 导入时大纲骨架每弧章数
DEFAULT_BATCH = 10
MAX_BATCH = 30
CONTENT_CAP = 12000  # 单章进提示词的最大字数（超长章截断，首尾各留一段）
CONTINUE_ARC_TITLE = "接续（待展开）"


def _meta_key(book_id: int) -> str:
    return f"import:{book_id}"


def _prog_key(book_id: int) -> str:
    return f"adopt:{book_id}"


def _stop_key(book_id: int) -> str:
    return f"adopt_stop:{book_id}"


def _proposal_key(book_id: int) -> str:
    return f"adopt_proposal:{book_id}"


def _created_tag(b: Book) -> str:
    return b.created_at.isoformat() if b.created_at else ""


def import_meta(s: Session, book: Book) -> dict[str, Any] | None:
    """这本书的导入记录；书 id 被复用（删书后新建）时作废。"""
    m = kv_get(s, _meta_key(book.id or 0))
    if not isinstance(m, dict) or m.get("book_created_at") != _created_tag(book):
        return None
    return m


def _progress(s: Session, book: Book) -> dict[str, list[int]]:
    p = kv_get(s, _prog_key(book.id or 0))
    if not isinstance(p, dict) or p.get("book_created_at") != _created_tag(book):
        return {k: [] for k in STEPS}
    return {k: [int(x) for x in (p.get(k) or [])] for k in STEPS}


def _save_progress(book_id: int, step: str, numbers: list[int]) -> None:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        p = kv_get(s, _prog_key(book_id))
        if not isinstance(p, dict) or p.get("book_created_at") != _created_tag(book):
            p = {"book_created_at": _created_tag(book)}
        cur = set(int(x) for x in (p.get(step) or []))
        cur.update(numbers)
        p = {**p, step: sorted(cur), "updated_at": utcnow().isoformat()}
        kv_set(s, _prog_key(book_id), p)


# ------------------------------------------------------------------ 导入建书

def _clean_chapters(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in chapters:
        content = str(c.get("content") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not content:
            continue
        out.append({"title": str(c.get("title") or "").strip()[:60], "content": content,
                    "volume": str(c.get("volume") or "").strip()[:60]})
    return out


def _style_sample(chs: list[dict[str, Any]], limit: int = 3000) -> str:
    """风格样本：从第 2–4 章（没有就第 1 章）各取一段正文，给风格提取和续写参考。"""
    pick = chs[1:4] or chs[:1]
    parts, total = [], 0
    for c in pick:
        seg = c["content"][: max(0, min(1200, limit - total))]
        if not seg:
            break
        parts.append(seg)
        total += len(seg)
    return "\n\n".join(parts)


def commit_import(data: dict[str, Any]) -> dict[str, Any]:
    """建书 + 写入章节（committed）+ 大纲骨架。data 为路由校验后的 dict。"""
    from app.config import get_settings

    chs = _clean_chapters(list(data.get("chapters") or []))
    if not chs:
        raise ImportError_("没有可导入的章节（正文都是空的）", 422)
    if len(chs) > MAX_CHAPTERS:
        raise ImportError_(f"单次最多导入 {MAX_CHAPTERS} 章", 422)
    st = get_settings()
    words = [count_words(c["content"]) for c in chs]
    total = sum(words)
    med = int(statistics.median(words)) if words else st.default_chapter_words
    chapter_words = int(data.get("chapter_words") or 0) or max(800, min(10000, round(med / 100) * 100 or st.default_chapter_words))
    intros = data.get("volume_intros") if isinstance(data.get("volume_intros"), dict) else {}
    with session_scope() as s:
        book = Book(title=(str(data.get("title") or "").strip().strip("《》")[:40] or "导入的作品"), genre=str(data.get("genre") or "")[:20],
                    gender=data.get("gender") if data.get("gender") in ("male", "female") else "male",
                    premise=str(data.get("premise") or "")[:4000], status="writing",
                    target_words=max(int(data.get("target_words") or 0) or st.default_target_words, total),
                    chapter_words=chapter_words, platform_style=str(data.get("platform_style") or "fanqie"))
        s.add(book)
        s.flush()
        bid = book.id or 0
        root = OutlineNode(book_id=bid, level="book", order=1, title=book.title,
                           summary=(book.premise[:300] if book.premise else "（导入的作品，接管后可补全总纲）"), status="expanded")
        s.add(root)
        s.flush()
        # 卷：按出现顺序；没写卷的章节归到「正文」卷
        vol_names: list[str] = []
        for c in chs:
            if c["volume"] not in vol_names:
                vol_names.append(c["volume"])
        vols: dict[str, OutlineNode] = {}
        for i, name in enumerate(vol_names, 1):
            v = OutlineNode(book_id=bid, parent_id=root.id, level="volume", order=i, title=name or ("正文" if len(vol_names) == 1 else f"第{i}卷"),
                            summary=str(intros.get(name) or "")[:800], status="expanded")
            s.add(v)
            vols[name] = v
        s.flush()
        arc_cur: dict[str, tuple[OutlineNode, int]] = {}
        arc_count: dict[str, int] = {}
        n_nodes = 0
        for n, c in enumerate(chs, 1):
            v = vols[c["volume"]]
            arc, used = arc_cur.get(c["volume"], (None, 0))  # type: ignore[assignment]
            if arc is None or used >= ARC_SIZE:
                arc_count[c["volume"]] = arc_count.get(c["volume"], 0) + 1
                arc = OutlineNode(book_id=bid, parent_id=v.id, level="arc", order=arc_count[c["volume"]],
                                  title=f"第{n}章起", summary="", status="expanded")
                s.add(arc)
                s.flush()
                used = 0
            arc_cur[c["volume"]] = (arc, used + 1)
            arc.title = f"第{n - used}–{n}章"
            s.add(arc)
            ch = Chapter(book_id=bid, number=n, title=c["title"], content=c["content"], words=count_words(c["content"]),
                         status="committed", summary="")
            s.add(ch)
            s.flush()
            node = OutlineNode(book_id=bid, parent_id=arc.id, level="chapter", order=n, title=c["title"] or f"第{n}章",
                               summary="", beats={"number": n, "title": c["title"] or f"第{n}章", "words": ch.words},
                               status="written", chapter_id=ch.id)
            s.add(node)
            s.flush()
            ch.outline_node_id = node.id
            s.add(ch)
            n_nodes += 1
        last_vol = vols[vol_names[-1]]
        s.add(OutlineNode(book_id=bid, parent_id=last_vol.id, level="arc", order=arc_count.get(vol_names[-1], 0) + 1,
                          title=CONTINUE_ARC_TITLE, summary="导入后的续写从这里开始：写下一章时会自动展开这一弧的章细纲。", status="planned"))
        sample = _style_sample(chs)
        if sample:
            s.add(Style(book_id=bid, sample_text=sample))
        src = data.get("source") if isinstance(data.get("source"), dict) else {}
        kv_set(s, _meta_key(bid), {
            "book_created_at": _created_tag(book), "imported_at": utcnow().isoformat(),
            "format": str(src.get("format") or "paste")[:10], "filename": str(src.get("filename") or "")[:120],
            "encoding": str(src.get("encoding") or "")[:20], "rule": str(src.get("rule") or "")[:20],
            "chapters": len(chs), "words": total, "volumes": len(vol_names),
        })
        s.commit()
        return {"book_id": bid, "chapters": len(chs), "words": total, "volumes": len(vol_names), "outline_nodes": n_nodes,
                "chapter_words": chapter_words}


# ------------------------------------------------------------------ 接管：状态 / 预估

def _committed(s: Session, book_id: int) -> list[Chapter]:
    return list(s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.status == "committed").order_by(Chapter.number)))


def norm_params(s: Session, book_id: int, frm: int | None, to: int | None, steps: list[str] | None,
                batch_size: int | None) -> dict[str, Any]:
    chs = _committed(s, book_id)
    if not chs:
        raise Conflict("这本书还没有已提交的章节，没有可接管的内容")
    lo, hi = chs[0].number, chs[-1].number
    a = max(lo, int(frm or lo))
    b = min(hi, int(to or hi))
    if a > b:
        raise ValueError(f"章节区间不对：本书已有第{lo}–{hi}章")
    st = [x for x in STEPS if x in (steps or STEPS)]
    if not st:
        raise ValueError("至少选一个步骤")
    bs = max(1, min(MAX_BATCH, int(batch_size or DEFAULT_BATCH)))
    return {"from": a, "to": b, "steps": st, "batch_size": bs}


def _batches(numbers: list[int], size: int) -> list[list[int]]:
    return [numbers[i:i + size] for i in range(0, len(numbers), size)]


def status(book_id: int) -> dict[str, Any]:
    from app.jobs.manager import find_active
    from app.models.tables import Job
    from app.services.outline import next_chapter_node

    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = import_meta(s, book)
        chs = _committed(s, book_id)
        nums = [c.number for c in chs]
        prog = _progress(s, book)
        done = {k: sorted(set(v) & set(nums)) for k, v in prog.items()}
        prop = kv_get(s, _proposal_key(book_id))
        prop = prop if isinstance(prop, dict) and prop.get("book_created_at") == _created_tag(book) and prop.get("items") else None
        last = s.exec(select(Job).where(Job.book_id == book_id, Job.kind == ADOPT_KIND).order_by(Job.id.desc())).first()  # type: ignore[union-attr]
        nxt = next_chapter_node(s, book_id)
        has_continue = nxt is not None or any(n.level == "arc" and n.status == "planned" for n in common.outline_nodes(s, book_id))
        stop = bool(kv_get(s, _stop_key(book_id), False))
    running = find_active(ADOPT_KIND, f"{ADOPT_KIND}:{book_id}")
    from app.api.schemas import job_out

    total = len(nums)
    return {
        "book_id": book_id, "imported": meta, "chapters": total,
        "first": nums[0] if nums else 0, "last": nums[-1] if nums else 0,
        "steps": [{"key": k, "label": STEP_LABEL[k], "done": len(done[k]), "total": total,
                   "covered_to": _covered_to(nums, done[k])} for k in STEPS],
        "complete": bool(total) and all(len(done[k]) >= total for k in STEPS),
        "running_job": job_out(running) if running else None,
        "last_job": job_out(last) if last else None,
        "stop_requested": stop and running is not None,
        "proposal": prop,
        "pending_review": len(prop["items"]) if prop else 0,
        "can_continue": has_continue,
        "next_chapter": (nums[-1] + 1) if nums else 1,
    }


def _covered_to(nums: list[int], done: list[int]) -> int:
    """从第一章起连续完成到第几章（0 表示还没开始）。"""
    d = set(done)
    last = 0
    for n in nums:
        if n not in d:
            break
        last = n
    return last


def estimate(book_id: int, params: dict[str, Any]) -> dict[str, Any]:
    """按区间内还没完成的单元估 token / 调用次数 / 秒数；已完成的跳过不计。"""
    from app.llm import usage as usage_log
    from app.llm.gateway import resolve_targets
    from app.services.estimate import DEFAULT_SECONDS, SYSTEM_CHARS

    with session_scope() as s:
        book = common.get_book(s, book_id)
        prog = {k: set(v) for k, v in _progress(s, book).items()}
        chs = [c for c in _committed(s, book_id) if params["from"] <= c.number <= params["to"]]
        n_cards = len(common.cards(s, book_id))
        targets = resolve_targets(s, "planner")
        rtargets = resolve_targets(s, "reviewer")
    length = {c.number: min(len(c.content), CONTENT_CAP) for c in chs}
    batches = _batches([c.number for c in chs], params["batch_size"])
    rows = []
    total_in = total_out = total_calls = 0
    for step in params["steps"]:
        if step in ("summary", "ledger"):
            todo = [n for n in length if n not in prog[step]]
            per_in = (900 if step == "summary" else 1800 + n_cards * 40) + SYSTEM_CHARS // (3 if step == "summary" else 1)
            inp = sum(length[n] + per_in for n in todo)
            out = len(todo) * (350 if step == "summary" else 700)
            calls = len(todo)
        else:
            todo_b = [b for b in batches if any(n not in prog[step] for n in b)]
            if step == "bible":
                inp = sum(len(b) * 320 + 2500 + n_cards * 60 + SYSTEM_CHARS for b in todo_b)
                out = len(todo_b) * 2200
            else:
                inp = sum(len(b) * 650 + 2200 + SYSTEM_CHARS for b in todo_b)
                out = sum(len(b) * 260 + 300 for b in todo_b)
            calls = len(todo_b)
            todo = [n for b in todo_b for n in b]
        route = "reviewer" if step == "summary" else "planner"
        tin, tout = usage_log.est_tokens(inp), usage_log.est_tokens(out)
        rows.append({"step": step, "label": STEP_LABEL[step], "chapters_todo": len(todo), "calls": calls,
                     "input_tokens_est": tin, "output_tokens_est": tout, "route": route})
        total_in, total_out, total_calls = total_in + tin, total_out + tout, total_calls + calls
    secs = 0
    for r in rows:
        avg, n_hist = usage_log.avg_ms(r["route"])
        secs += int(round(avg / 1000 * r["calls"])) if n_hist else DEFAULT_SECONDS.get(r["route"], 30) * r["calls"]
    model = f"{targets[0].name}/{targets[0].model}" if targets else "mock"
    rmodel = f"{rtargets[0].name}/{rtargets[0].model}" if rtargets else "mock"
    notes = ["已完成的章节/批次自动跳过，不重复计费"]
    if model == "mock" and rmodel == "mock":
        notes.append("当前没有可用模型渠道，实际会走演示模式（不花钱）")
    return {"kind": ADOPT_KIND, "label": "接管旧书", "params": params, "steps": rows,
            "input_tokens_est": total_in, "output_tokens_est": total_out, "calls_est": total_calls,
            "model": model, "summary_model": rmodel, "seconds_est": max(1, secs) if total_calls else 0, "note": "；".join(notes)}


# ------------------------------------------------------------------ 接管：任务

def request_stop(book_id: int, stop: bool = True) -> None:
    with session_scope() as s:
        common.get_book(s, book_id)
        kv_set(s, _stop_key(book_id), bool(stop))


def _stopped(book_id: int) -> bool:
    with session_scope() as s:
        return bool(kv_get(s, _stop_key(book_id), False))


def _clip(text: str, cap: int = CONTENT_CAP) -> str:
    if len(text) <= cap:
        return text
    head = int(cap * 0.7)
    return text[:head] + "\n……（中间省略）……\n" + text[-(cap - head):]


def _summary_unit(book_id: int, number: int) -> None:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        ch = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number == number)).first()
        if ch is None or not ch.content.strip():
            return
        if ch.summary.strip():  # 已有摘要（本系统写的章，或上次接管写过）
            return
        meta = {**common.kit_meta(s, book), "number": number, "content": ch.content, "title": book.title, "adopt": True}
        content = _clip(ch.content)
    try:
        raw = get_gateway().chat_json("summary", system_prompt("summary"), render("summary", number=number, content=content),
                                      meta=meta, temperature=0.3)
        summ = str(raw.get("summary", "")).strip() if isinstance(raw, dict) else ""
    except Exception:  # noqa: BLE001  摘要失败不挡后续步骤，用开头兜底
        summ = ""
    summ = summ or re.sub(r"\s+", "", content)[:200]
    with session_scope() as s:
        ch = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number == number)).first()
        if ch is not None:
            ch.summary = summ[:2000]
            s.add(ch)
            s.commit()


_SURNAMES = "林王李张刘陈杨赵黄周吴徐孙马朱胡郭何高罗郑梁谢宋唐许韩冯邓曹彭曾萧田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦方白邹孟熊秦邱江尹薛段雷侯龙史陶黎贺顾毛郝龚邵万钱严武戴莫孔向汤楚沐慕容欧阳上官司马"


def name_candidates(text: str, k: int = 6) -> list[str]:
    """程序找的人名候选（常见姓 + 1–2 字，出现 ≥2 次）。只给演示模式和提示词做参考，不直接入库。"""
    cnt: Counter[str] = Counter()
    for m in re.finditer(rf"(?<![\u4e00-\u9fff])([{_SURNAMES}][\u4e00-\u9fff]{{1,2}}?)(?=[说道笑看问喊听想走站点摇叹皱冷沉低望回伸抬：，。！？“])", text):
        cnt[m.group(1)] += 1
    out = []
    for name, c in cnt.most_common(k * 3):
        if c < 2 or any(name in o or o in name for o in out):
            continue
        out.append(name)
        if len(out) >= k:
            break
    return out


def _batch_digest(s: Session, book_id: int, numbers: list[int], per: int = 600) -> tuple[str, str]:
    """→ (各章摘要（没有摘要用开头）, 用于程序找人名的拼接正文)。"""
    lines, texts = [], []
    for c in s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number.in_(numbers)).order_by(Chapter.number)):  # type: ignore[attr-defined]
        summ = c.summary.strip() or re.sub(r"\s+", "", c.content)[:per]
        lines.append(f"第{c.number}章《{c.title or ''}》：{summ}")
        texts.append(c.content[:4000])
    return "\n".join(lines), "\n".join(texts)


def _bible_unit(book_id: int, numbers: list[int]) -> dict[str, int]:
    from app.services.bible_ops import _norm, card_dict, detect_conflicts, normalize_card

    with session_scope() as s:
        book = common.get_book(s, book_id)
        existing = common.cards(s, book_id, include_deprecated=True)
        digest, texts = _batch_digest(s, book_id, numbers)
        ex = "\n".join(f"[{c.type}] {c.name}：{c.summary[:80]}" for c in existing if c.status != "deprecated") or "（空）"
        user = render("adopt_bible", book_context=common.book_context(s, book, with_cards=False), existing=ex,
                      start=numbers[0], end=numbers[-1], digest=digest)
        meta = {**common.kit_meta(s, book), "names": name_candidates(texts), "existing": [c.name for c in existing],
                "start": numbers[0], "end": numbers[-1]}
    data = get_gateway().chat_json("adopt_bible", system_prompt("adopt_bible"), user, meta=meta, temperature=0.4)
    raw_cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(raw_cards, list):
        raise ValueError("模型没有返回设定卡")
    counts = {"created": 0, "updated": 0, "review": 0}
    review: list[dict[str, Any]] = []
    with session_scope() as s:
        book = common.get_book(s, book_id)
        existing = common.cards(s, book_id, include_deprecated=True)
        by_norm = {_norm(c.name): c for c in existing}
        for i, rc in enumerate(raw_cards):
            card = normalize_card(rc if isinstance(rc, dict) else {})
            if card is None:
                continue
            card["data"] = {**card["data"], "origin": "adopt", "first_chapter": card["data"].get("first_chapter") or numbers[0]}
            target = by_norm.get(_norm(str(rc.get("target") or ""))) or by_norm.get(_norm(card["name"]))
            if target is None:
                conflicts = detect_conflicts(card, existing, None)
                if not conflicts:
                    c = Card(book_id=book_id, **card)
                    s.add(c)
                    s.flush()
                    existing.append(c)
                    by_norm[_norm(c.name)] = c
                    counts["created"] += 1
                    continue
                review.append({"action": "add", "card": card, "target_id": None,
                               "old": card_dict(next(x for x in existing if x.id == conflicts[0]["card_id"])), "conflicts": conflicts, "default": "keep_old"})
                continue
            if (target.data or {}).get("origin") == "adopt":  # 接管时建的卡：后面章节的信息直接补进去
                merged = {**(target.data or {}), **{k: v for k, v in card["data"].items() if v not in (None, "", [], {})}}
                merged["first_chapter"] = (target.data or {}).get("first_chapter") or card["data"]["first_chapter"]
                new_summary = card["summary"] if len(card["summary"]) >= len(target.summary or "") else target.summary
                if new_summary != target.summary or merged != (target.data or {}):
                    target.summary, target.data = new_summary, merged
                    target.known_by = list(dict.fromkeys(list(target.known_by or []) + card["known_by"]))
                    target.updated_at = utcnow()
                    s.add(target)
                    counts["updated"] += 1
                continue
            # 作者自己的卡：不直接改，进冲突审阅
            if all(card_dict(target)[k] == card[k] for k in ("type", "name", "summary")):
                continue
            review.append({"action": "update", "card": {**card, "data": {**(target.data or {}), **card["data"]}}, "target_id": target.id,
                           "old": card_dict(target), "conflicts": [{"card_id": target.id, "name": target.name, "type": target.type,
                                                                    "reason": f"第{numbers[0]}–{numbers[-1]}章正文反推出的设定和你写的卡不一样", "source": "program"}],
                           "default": "keep_old"})
        if book.status in ("idea", "bible", "outline"):
            book.status = "writing"
        s.add(book)
        s.commit()
        if review:
            prop = kv_get(s, _proposal_key(book_id))
            if not isinstance(prop, dict) or prop.get("book_created_at") != _created_tag(book):
                prop = {"book_created_at": _created_tag(book), "book_id": book_id, "mode": "optimize",
                        "instruction": "接管旧书：从已写章节反推的设定", "change": "从旧章节反推的设定与已有设定不一致的地方",
                        "items": [], "removals": [], "facts": []}
            seq = len(prop["items"])
            known = {(x.get("target_id"), _norm(x["card"]["name"])) for x in prop["items"]}
            for r in review:
                if (r["target_id"], _norm(r["card"]["name"])) in known:
                    continue
                seq += 1
                prop["items"].append({"key": f"a{seq}", "trope_hits": [], **r})
            prop["counts"] = {"add": 0, "review": len(prop["items"]), "removals": 0}
            kv_set(s, _proposal_key(book_id), prop)
            counts["review"] = len(review)
    return counts


def apply_ledger(s: Session, book_id: int, n: int, cs: ChangeSet, warns: list[str]) -> dict[str, int]:
    """把一章的 ChangeSet 记进底账（与提交章节时的入账规则一致：新实体建卡、状态变化关闭旧事实、伏笔埋/推/收）。"""
    card_by_name = {c.name: c for c in common.cards(s, book_id, include_deprecated=True)}
    opens = {f.id or 0: f.desc for f in common.open_foreshadows(s, book_id)}
    cs, w2 = check_against_ledger(cs, set(card_by_name), opens)
    warns += w2
    out = {"entities": 0, "facts": 0, "foreshadows": 0}
    for e in cs.new_entities:
        card = Card(book_id=book_id, type=e.type, name=e.name, summary=e.summary or f"第{n}章登场",
                    data={"first_chapter": n, "origin": "adopt"}, known_by=[])
        s.add(card)
        s.flush()
        card_by_name[e.name] = card
        out["entities"] += 1
    for sc in cs.state_changes:
        ent = card_by_name.get(sc.entity)
        eid = ent.id if ent else None
        prev = s.exec(select(Fact).where(Fact.book_id == book_id, Fact.entity_id == eid, Fact.key == sc.key,
                                         Fact.to_chapter == None)).all()  # noqa: E711
        same = [p for p in prev if p.value == sc.value]
        if same:
            continue
        for p in prev:
            p.to_chapter = max(p.from_chapter, n - 1)
            s.add(p)
        s.add(Fact(book_id=book_id, entity_id=eid, key=sc.key, value=sc.value, from_chapter=n, visibility=sc.visibility))
        out["facts"] += 1
    for f in cs.foreshadow:
        if f.action == "plant":
            if match_foreshadow(f.desc, opens) is not None:
                continue
            fo = Foreshadow(book_id=book_id, desc=f.desc[:300], status="planted", planted_ch=n, last_ch=n, source="chapter",
                            note=f"接管旧书时从第{n}章正文识别")
            s.add(fo)
            s.flush()
            opens[fo.id or 0] = fo.desc
            out["foreshadows"] += 1
            continue
        fo = s.get(Foreshadow, f.id) if f.id else None
        if fo is None or fo.book_id != book_id:
            continue
        fo.last_ch = max(fo.last_ch, n)
        if f.action == "advance":
            fo.status = "advancing"
        else:
            fo.status, fo.resolved_ch = "resolved", n
            opens.pop(fo.id or 0, None)
        s.add(fo)
        out["foreshadows"] += 1
    ch = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number == n)).first()
    if ch is not None:
        ch.changes = {**cs.model_dump(), "warnings": warns, "adopted": True}
        s.add(ch)
    return out


def _ledger_unit(book_id: int, number: int) -> dict[str, int]:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        ch = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number == number)).first()
        if ch is None or not ch.content.strip():
            return {"entities": 0, "facts": 0, "foreshadows": 0}
        cards = common.cards(s, book_id)
        known = "\n".join(f"[{c.type}] {c.name}" for c in cards) or "（还没有）"
        opens = common.open_foreshadows(s, book_id)
        facts = s.exec(select(Fact).where(Fact.book_id == book_id, Fact.to_chapter == None)).all()  # noqa: E711
        by_id = {c.id: c.name for c in cards}
        fact_lines = "\n".join(f"{by_id.get(f.entity_id, '（全书）')}·{f.key}={f.value}（第{f.from_chapter}章起）" for f in facts[-60:]) or "（还没有）"
        content = _clip(ch.content)
        user = render("adopt_ledger", number=number, known=known, facts=fact_lines,
                      open_foreshadows="\n".join(f"#{f.id} {f.desc}（第{f.planted_ch}章埋）" for f in opens) or "（没有）",
                      content=content)
        meta = {**common.kit_meta(s, book), "number": number, "content": content, "known": [c.name for c in cards],
                "names": name_candidates(content, 4), "open_foreshadows": [{"id": f.id, "desc": f.desc, "planted_ch": f.planted_ch} for f in opens]}
    raw = get_gateway().chat_json("adopt_ledger", system_prompt("adopt_ledger"), user, meta=meta, temperature=0.3)
    cs, warns = parse_changes(json.dumps(raw, ensure_ascii=False) if isinstance(raw, (dict, list)) else str(raw))
    with session_scope() as s:
        out = apply_ledger(s, book_id, number, cs, warns)
        s.commit()
    return out


def _outline_unit(book_id: int, numbers: list[int]) -> int:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        rows = list(s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number.in_(numbers)).order_by(Chapter.number)))  # type: ignore[attr-defined]
        blocks = []
        for c in rows:
            summ = c.summary.strip() or re.sub(r"\s+", "", c.content)[:500]
            tail = re.sub(r"\s+", "", c.content)[-160:]
            blocks.append(f"第{c.number}章《{c.title or ''}》\n摘要：{summ}\n章末原文：{tail}")
        names = [c.name for c in common.cards(s, book_id, "character")]
        user = render("adopt_outline", book_context=common.book_context(s, book), start=numbers[0], end=numbers[-1],
                      chapters="\n\n".join(blocks), names="、".join(names[:40]) or "（无）")
        meta = {**common.kit_meta(s, book), "chapters": [{"number": c.number, "title": c.title, "summary": c.summary,
                                                          "tail": re.sub(r"\s+", "", c.content)[-80:]} for c in rows],
                "names": names}
    data = get_gateway().chat_json("adopt_outline", system_prompt("adopt_outline"), user, meta=meta, temperature=0.4)
    items = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("模型没有返回章细纲")
    by_no: dict[int, dict[str, Any]] = {}
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        try:
            no = int(it.get("number") or 0)
        except (TypeError, ValueError):
            no = 0
        by_no[no if no in numbers else (numbers[i] if i < len(numbers) else -1)] = it
    n = 0
    with session_scope() as s:
        book = common.get_book(s, book_id)
        arc_ids: set[int] = set()
        for c in s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number.in_(numbers))):  # type: ignore[attr-defined]
            raw = by_no.get(c.number)
            if raw is None:
                continue
            node = s.get(OutlineNode, c.outline_node_id) if c.outline_node_id else None
            if node is None:
                node = s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter",
                                                        OutlineNode.order == c.number)).first()
            if node is None:
                continue
            beats = normalize_beats({**raw, "title": c.title or raw.get("title") or ""}, c.number, c.words or book.chapter_words)
            beats["words"] = c.words
            beats["adopted"] = True
            if node.beats and any(k in (node.beats or {}) for k in ("goal", "conflict")) and not (node.beats or {}).get("adopted"):
                push_node_version(node, "接管旧书前")
            node.beats = beats
            node.title = c.title or beats["title"]
            node.summary = f"{beats['goal']}；{beats['conflict']}".strip("；")[:400]
            node.status, node.chapter_id = "written", c.id
            s.add(node)
            if node.parent_id:
                arc_ids.add(node.parent_id)
            n += 1
        arc_info = data.get("arc") if isinstance(data, dict) and isinstance(data.get("arc"), dict) else {}
        for aid in arc_ids:
            arc = s.get(OutlineNode, aid)
            if arc is None or arc.level != "arc" or arc.summary:
                continue
            if arc_info.get("summary"):
                arc.summary = str(arc_info["summary"])[:600]
                if arc_info.get("title") and re.fullmatch(r"第\d+–\d+章", arc.title or ""):
                    arc.title = f"{arc.title} {str(arc_info['title'])[:20]}"
                s.add(arc)
        s.commit()
    return n


def adopt_job(book_id: int, params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    """接管任务主循环。单元级跳过 + 断点：中途失败/重启后用 /jobs/{id}/resume 或重新发起都从没做完的单元接着做。"""
    from app.services import bible_ops

    with session_scope() as s:
        book = common.get_book(s, book_id)
        nums = [c.number for c in _committed(s, book_id) if params["from"] <= c.number <= params["to"]]
        kv_set(s, _stop_key(book_id), False)
    batches = _batches(nums, params["batch_size"])
    steps = list(params["steps"])
    with session_scope() as s:
        prog = {k: set(v) for k, v in _progress(s, common.get_book(s, book_id)).items()}
    units: list[tuple[str, list[int]]] = []
    for b in batches:
        for st in steps:
            if st in ("summary", "ledger"):
                units += [(st, [n]) for n in b if n not in prog[st]]
            elif any(n not in prog[st] for n in b):
                units.append((st, b))
    total = len(units)
    stats = {"summary": 0, "bible_created": 0, "bible_updated": 0, "bible_review": 0, "entities": 0, "facts": 0,
             "foreshadows": 0, "outline": 0}
    if "bible" in steps and units:
        with session_scope() as s:
            bible_ops.snapshot(s, book_id, f"接管旧书第{params['from']}–{params['to']}章前")
            s.commit()
    ctx.checkpoint("start", {"params": params}, kind=ADOPT_KIND)
    stopped = False
    for i, (st, ns) in enumerate(units):
        if _stopped(book_id):
            stopped = True
            break
        rng = f"第{ns[0]}章" if len(ns) == 1 else f"第{ns[0]}–{ns[-1]}章"
        ctx.progress(int(100 * i / max(1, total)), f"{STEP_LABEL[st]}：{rng}（{i + 1}/{total}）")
        if st == "summary":
            _summary_unit(book_id, ns[0])
            stats["summary"] += 1
        elif st == "ledger":
            r = _ledger_unit(book_id, ns[0])
            for k in ("entities", "facts", "foreshadows"):
                stats[k] += r[k]
        elif st == "bible":
            r = _bible_unit(book_id, ns)
            stats["bible_created"] += r["created"]
            stats["bible_updated"] += r["updated"]
            stats["bible_review"] += r["review"]
        else:
            stats["outline"] += _outline_unit(book_id, ns)
        _save_progress(book_id, st, ns)
        ctx.checkpoint(f"{st}:{ns[0]}-{ns[-1]}", {"params": params}, kind=ADOPT_KIND)
    with session_scope() as s:
        kv_set(s, _stop_key(book_id), False)
    msg = (f"已暂停（完成 {i}/{total} 个单元），再点开始会从没做完的地方继续" if stopped
           else ("区间内全部已完成，没有需要做的" if not total else f"完成 {total} 个单元"))
    return {"book_id": book_id, "params": params, "units_total": total, "units_done": (i if stopped else total) if total else 0,
            "stopped": stopped, "stats": stats, "message": msg}


def _resume_adopt(job: Any, state: dict[str, Any]) -> Any:
    params = dict(state.get("params") or {})
    bid = job.book_id or 0
    return lambda ctx: adopt_job(bid, params, ctx)


register_resumable(ADOPT_KIND, _resume_adopt)


def dismiss_proposal(book_id: int) -> None:
    with session_scope() as s:
        common.get_book(s, book_id)
        kv_set(s, _proposal_key(book_id), None)


# ------------------------------------------------------------------ 大纲导入

def outline_import_job(book_id: int, text: str, ctx: JobContext) -> dict[str, Any]:
    parsed = parse_outline(text)
    ctx.progress(15, f"程序识别到 {len(parsed['volumes'])} 卷、{parsed['chapters']} 章，交给模型结构化")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = {**common.kit_meta(s, book), "parsed": parsed}
        user = render("outline_import", book_context=common.book_context(s, book), text=text[:30000],
                      skeleton=json.dumps(parsed, ensure_ascii=False)[:8000])
        written = max([c.number for c in _committed(s, book_id)] or [0])
        max_node = max([n.order for n in common.outline_nodes(s, book_id) if n.level == "chapter"] or [0])
    data = get_gateway().chat_json("outline_import", system_prompt("outline_import"), user, meta=meta, temperature=0.3)
    vols = data.get("volumes") if isinstance(data, dict) else None
    warnings: list[str] = []
    if not isinstance(vols, list) or not vols:
        warnings.append("模型没有给出结构，按程序识别的结果预览")
        data, vols = parsed, parsed["volumes"]
    ctx.progress(85, "整理预览")
    out_vols = []
    n_ch = 0
    for vi, v in enumerate(vols, 1):
        if not isinstance(v, dict):
            continue
        arcs = []
        for ai, a in enumerate(v.get("arcs") or [], 1):
            if not isinstance(a, dict):
                continue
            chs = []
            for c in a.get("chapters") or []:
                if not isinstance(c, dict):
                    continue
                try:
                    num = int(c.get("number") or 0)
                except (TypeError, ValueError):
                    num = 0
                chs.append({**{k: v2 for k, v2 in c.items() if k != "number"}, "number": num})
                n_ch += 1
            arcs.append({"title": str(a.get("title") or f"第{ai}段")[:60], "summary": str(a.get("summary") or "")[:800], "chapters": chs})
        out_vols.append({"title": str(v.get("title") or f"第{vi}卷")[:60], "summary": str(v.get("summary") or "")[:800], "arcs": arcs})
    if not n_ch:
        warnings.append("没有识别到章纲，只会导入卷和弧")
    nums = [c["number"] for v in out_vols for a in v["arcs"] for c in a["chapters"] if c["number"]]
    if nums and len(set(nums)) != len(nums):
        warnings.append("有重复的章号，按章号合并时后出现的会覆盖前面的")
    overlap = sorted(n for n in set(nums) if n <= written)
    if overlap:
        warnings.append(f"第{overlap[0]}–{overlap[-1]}章已经写过：按章号合并时只补这些章的细纲，不动正文")
    book_sum = str(((data.get("book") or {}) if isinstance(data, dict) else {}).get("summary") or parsed["book"]["summary"])[:1500]
    return {"book_id": book_id, "preview": {"book": {"summary": book_sum}, "volumes": out_vols}, "chapters": n_ch,
            "written": written, "outline_max": max_node, "warnings": warnings,
            "suggest_mode": "fill" if (max_node and nums and min(nums) <= max_node) else "append"}


def _beats_from(raw: dict[str, Any], number: int, chapter_words: int) -> dict[str, Any]:
    return normalize_beats({**raw, "title": raw.get("title") or f"第{number}章"}, number, chapter_words)


def apply_outline_import(book_id: int, preview: dict[str, Any], mode: str) -> dict[str, Any]:
    """采纳大纲导入预览。fill：按章号合并（已有节点更新细纲、写过的章只补细纲；缺的章新建）；append：接在现有大纲后面重新编号。"""
    if mode not in ("fill", "append"):
        raise ValueError("mode 只能是 fill 或 append")
    vols = preview.get("volumes") if isinstance(preview, dict) else None
    if not isinstance(vols, list) or not vols:
        raise ValueError("预览里没有大纲内容")
    res = {"volumes": 0, "arcs": 0, "chapters_created": 0, "chapters_updated": 0, "skipped": 0}
    with session_scope() as s:
        book = common.get_book(s, book_id)
        nodes = common.outline_nodes(s, book_id)
        root = next((n for n in nodes if n.level == "book"), None)
        if root is None:
            root = OutlineNode(book_id=book_id, level="book", order=1, title=book.title, status="expanded",
                               summary=str((preview.get("book") or {}).get("summary") or "")[:1500])
            s.add(root)
            s.flush()
        elif not root.summary and (preview.get("book") or {}).get("summary"):
            root.summary = str(preview["book"]["summary"])[:1500]
            s.add(root)
        by_order = {n.order: n for n in nodes if n.level == "chapter"}
        vol_by_title = {n.title: n for n in nodes if n.level == "volume"}
        vol_count = sum(1 for n in nodes if n.level == "volume")
        next_no = max([n.order for n in nodes if n.level == "chapter"] or [0]) + 1
        # 末尾的「接续（待展开）」空弧：追加章节后它仍要排在最后
        cont = [n for n in nodes if n.level == "arc" and n.title == CONTINUE_ARC_TITLE and not any(c.parent_id == n.id for c in nodes)]
        for v in vols:
            vnode = vol_by_title.get(str(v.get("title") or "")) if mode == "fill" else None
            arcs = v.get("arcs") or []
            if vnode is None:
                has_new = mode == "append" or any(int(c.get("number") or 0) not in by_order for a in arcs for c in (a.get("chapters") or []))
                if not has_new and arcs:
                    vnode = None
                else:
                    vol_count += 1
                    vnode = OutlineNode(book_id=book_id, parent_id=root.id, level="volume", order=vol_count,
                                        title=str(v.get("title") or f"第{vol_count}卷")[:60], summary=str(v.get("summary") or "")[:800], status="expanded")
                    s.add(vnode)
                    s.flush()
                    vol_by_title[vnode.title] = vnode
                    res["volumes"] += 1
            elif v.get("summary") and not vnode.summary:
                vnode.summary = str(v["summary"])[:800]
                s.add(vnode)
            for a in arcs:
                anode: OutlineNode | None = None
                for c in a.get("chapters") or []:
                    num = int(c.get("number") or 0)
                    if mode == "fill" and num and num in by_order:
                        node = by_order[num]
                        beats = _beats_from(c, num, book.chapter_words)
                        if node.status == "written":
                            old = dict(node.beats or {})
                            if any(old.get(k) for k in ("goal", "conflict")):
                                res["skipped"] += 1
                                continue
                            beats["title"] = node.title or beats["title"]
                            beats["words"] = old.get("words") or beats["words"]
                        push_node_version(node, "导入大纲前")
                        node.beats = {**(node.beats or {}), **beats}
                        if node.status != "written":
                            node.title = beats["title"]
                        node.summary = f"{beats['goal']}；{beats['conflict']}".strip("；")[:400] or node.summary
                        s.add(node)
                        res["chapters_updated"] += 1
                        continue
                    if anode is None:
                        if vnode is None:
                            vnode = max((n for n in common.outline_nodes(s, book_id) if n.level == "volume"), key=lambda n: n.order, default=None)
                            if vnode is None:
                                vol_count += 1
                                vnode = OutlineNode(book_id=book_id, parent_id=root.id, level="volume", order=vol_count, title="导入的大纲", status="expanded")
                                s.add(vnode)
                                s.flush()
                                res["volumes"] += 1
                        k = len(list(s.exec(select(OutlineNode).where(OutlineNode.parent_id == vnode.id)))) + 1
                        anode = OutlineNode(book_id=book_id, parent_id=vnode.id, level="arc", order=k, title=str(a.get("title") or f"第{k}段")[:60],
                                            summary=str(a.get("summary") or "")[:800], status="expanded")
                        s.add(anode)
                        s.flush()
                        res["arcs"] += 1
                    no = num if (mode == "fill" and num and num >= next_no) else next_no
                    if mode == "fill" and num and num < next_no and num not in by_order:
                        no = num  # 中间缺的章号补上
                    beats = _beats_from(c, no, book.chapter_words)
                    node = OutlineNode(book_id=book_id, parent_id=anode.id, level="chapter", order=no, title=beats["title"],
                                       summary=f"{beats['goal']}；{beats['conflict']}".strip("；")[:400], beats=beats, status="planned")
                    s.add(node)
                    s.flush()
                    by_order[no] = node
                    next_no = max(next_no, no + 1)
                    res["chapters_created"] += 1
                if anode is None and not (a.get("chapters") or []) and vnode is not None and mode == "append":
                    k = len(list(s.exec(select(OutlineNode).where(OutlineNode.parent_id == vnode.id)))) + 1
                    s.add(OutlineNode(book_id=book_id, parent_id=vnode.id, level="arc", order=k, title=str(a.get("title") or f"第{k}段")[:60],
                                      summary=str(a.get("summary") or "")[:800], status="planned"))
                    res["arcs"] += 1
        for c in cont:  # 空的「接续」弧挪到最后一卷的最后
            last_vol = max((n for n in common.outline_nodes(s, book_id) if n.level == "volume"), key=lambda n: n.order, default=None)
            if last_vol is not None:
                c.parent_id = last_vol.id
                c.order = len(list(s.exec(select(OutlineNode).where(OutlineNode.parent_id == last_vol.id, OutlineNode.id != c.id)))) + 1
                s.add(c)
        if book.status in ("idea", "bible"):
            book.status = "outline"
        book.updated_at = utcnow()
        s.add(book)
        s.commit()
    return res


__all__ = ["commit_import", "status", "estimate", "adopt_job", "request_stop", "norm_params", "dismiss_proposal",
           "outline_import_job", "apply_outline_import", "apply_ledger", "name_candidates", "STEPS", "ADOPT_KIND",
           "OUTLINE_IMPORT_KIND", "NotFound", "CARD_TYPES"]
