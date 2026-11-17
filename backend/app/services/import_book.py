"""v0.12 导入已有作品 + 接管旧书。

- 解析：TXT（utf-8 / gb18030 / BOM）、MD、DOCX（不加依赖，直接读 word/document.xml）、粘贴；按「第X章/回/节、Chapter N、序章」切章，
  识别「第X卷」并把卷名从正文里拿掉；给出疑似空章、重复章、过短、过长、章号跳号的提示。解析结果暂存在内存（30 分钟），预览后再建书。
- 建书：作者自己的作品，正文正常入库，章节直接是已提交状态。
- 接管（Job book_adopt）：逐章补摘要（已有摘要的章跳过，所以中断后重跑会接着做）→ 从摘要反推设定卡、事实账本、伏笔账本
  → 按卷生成大纲节点（卷 / 弧 / 章，章节点挂上对应章节，状态为已成文）。
"""

from __future__ import annotations

import io
import re
import time
import uuid
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from sqlmodel import select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Book, Card, Chapter, Fact, Foreshadow, OutlineNode, utcnow
from app.services import common
from app.services.changes import CARD_TYPES
from app.services.common import NotFound
from app.services.imitate_txt import _CH_RX, ExtractError, decode, guess_title
from app.skills.loader import render, system_prompt

MAX_BYTES = 30 * 1024 * 1024
MAX_CHAPTERS = 5000
CACHE_TTL = 30 * 60
SUMMARY_BATCH_CHARS = 60_000  # 反推设定时一次喂给模型的摘要字数上限（太长的书取首尾 + 均匀抽样）

_NUM = r"[0-9０-９零〇一二两三四五六七八九十百千万]+"
_VOL_RX = re.compile(rf"^[ \t\u3000]*(第{_NUM}[卷部集](?:[ \t\u3000:：、.\-—]*[^\n]{{0,40}})?)[ \t\u3000]*$", re.M)
_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cn_num(s: str) -> int | None:
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    total, section, num = 0, 0, 0
    units = {"十": 10, "百": 100, "千": 1000}
    for ch in s:
        if ch in _CN:
            num = _CN[ch]
        elif ch in units:
            section += (num or 1) * units[ch]
            num = 0
        elif ch == "万":
            total += (section + num) * 10000
            section, num = 0, 0
        else:
            return None
    return total + section + num


def _chapter_no(title: str) -> int | None:
    m = re.match(rf"第({_NUM})[章回节]", title)
    if m:
        return _cn_num(m.group(1))
    m = re.match(r"chapter\s*(\d+)", title, re.I)
    return int(m.group(1)) if m else None


def _words(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s)) + len(re.findall(r"[A-Za-z0-9]+", s))


def docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ExtractError("DOCX 文件读不出来，换成 TXT 再试") from e
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter(f"{ns}p"):
        parts = []
        for node in p.iter():
            if node.tag == f"{ns}t" and node.text:
                parts.append(node.text)
            elif node.tag in (f"{ns}tab",):
                parts.append("\t")
            elif node.tag in (f"{ns}br", f"{ns}cr"):
                parts.append("\n")
        paras.append("".join(parts))
    return "\n".join(paras)


def _split(text: str) -> list[dict[str, Any]]:
    """→ [{title, body, volume}]。卷标题行不进正文；第一个章节标题前的文字（书名、简介）丢掉。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    vols = [(m.start(), m.end(), re.sub(r"\s+", " ", m.group(1)).strip()) for m in _VOL_RX.finditer(text)]
    chs = list(_CH_RX.finditer(text))
    if not chs:
        body = text.strip()
        return [{"title": "第1章", "body": body, "volume": ""}] if body else []
    out = []
    for k, m in enumerate(chs):
        end = chs[k + 1].start() if k + 1 < len(chs) else len(text)
        body = text[m.end():end]
        for vs, ve, _ in reversed([v for v in vols if m.end() <= v[0] < end]):  # 夹在正文末尾的卷名拿掉
            body = body[: vs - m.end()] + body[ve - m.end():]
        vol = ""
        for vs, _, name in vols:
            if vs < m.start():
                vol = name
        out.append({"title": re.sub(r"\s+", " ", m.group(1)).strip(), "body": body.strip("\n").strip(), "volume": vol})
    return out


def _clean_body(body: str) -> str:
    lines = [ln.strip().strip("\u3000") for ln in body.split("\n")]
    paras = [ln for ln in lines if ln]
    return "\n\n".join(paras)


def parse(data: bytes | None = None, text: str | None = None, filename: str | None = None) -> dict[str, Any]:
    enc = "text"
    if data is not None:
        if len(data) > MAX_BYTES:
            raise ExtractError(f"文件超过 {MAX_BYTES // 1024 // 1024}MB")
        if (filename or "").lower().endswith(".docx") or data[:2] == b"PK":
            text, enc = docx_text(data), "docx"
        else:
            text, enc = decode(data)
    text = (text or "").replace("\ufeff", "")
    if not text.strip():
        raise ExtractError("没有可用的正文")
    raw = _split(text)
    if len(raw) > MAX_CHAPTERS:
        raise ExtractError(f"章节太多（{len(raw)} 章），一次最多导入 {MAX_CHAPTERS} 章")
    chapters: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: dict[str, int] = {}
    prev_no: int | None = None
    for i, c in enumerate(raw, 1):
        body = _clean_body(c["body"])
        w = _words(body)
        title = re.sub(rf"^(第{_NUM}[章回节]|chapter\s*\d+)[\s:：、.\-—]*", "", c["title"], flags=re.I).strip() or c["title"]
        flags = []
        if w == 0:
            flags.append("空章")
        elif w < 300:
            flags.append("过短")
        elif w > 15000:
            flags.append("过长，可能漏切章")
        key = re.sub(r"\s", "", body[:200])
        if key and key in seen:
            flags.append(f"和第 {seen[key]} 章开头重复")
        elif key:
            seen[key] = i
        no = _chapter_no(c["title"])
        if prev_no is not None and no is not None and no != prev_no + 1 and no != 1:
            flags.append(f"章号从 {prev_no} 跳到 {no}")
        prev_no = no if no is not None else prev_no
        chapters.append({"index": i, "raw_title": c["title"], "title": title[:60], "volume": c["volume"], "words": w,
                         "flags": flags, "content": body})
    if len(chapters) == 1 and not _CH_RX.search(text):
        warnings.append("没认出章节标题，整篇算作一章；章节标题写成「第1章 xxx」这种格式能自动切章")
    n_flag = sum(1 for c in chapters if c["flags"])
    if n_flag:
        warnings.append(f"{n_flag} 章有疑点，导入前看一下")
    vols = list(dict.fromkeys(c["volume"] for c in chapters if c["volume"]))
    pid = uuid.uuid4().hex[:12]
    _gc()
    title_guess = guess_title(text, filename) or "导入的作品"
    _cache[pid] = (time.time(), {"title": title_guess, "chapters": chapters})
    return {"import_id": pid, "title": title_guess, "encoding": enc, "total_words": sum(c["words"] for c in chapters),
            "volumes": vols, "warnings": warnings,
            "chapters": [{k: v for k, v in c.items() if k != "content"} | {"preview": c["content"][:80]} for c in chapters]}


def _gc() -> None:
    now = time.time()
    for k in [k for k, (t, _) in _cache.items() if now - t > CACHE_TTL]:
        _cache.pop(k, None)


def commit(import_id: str, title: str, genre: str = "", gender: str = "male", tagline: str = "",
           skip: list[int] | None = None) -> dict[str, Any]:
    """按预览建书：跳过 skip 里的章（index），其余按顺序编号入库，状态为已提交。"""
    _gc()
    got = _cache.get(import_id)
    if got is None:
        raise NotFound("导入预览已过期，重新上传一次")
    data = got[1]
    skip_set = set(skip or [])
    chs = [c for c in data["chapters"] if c["index"] not in skip_set and c["content"].strip()]
    if not chs:
        raise ExtractError("没有可导入的章节")
    words = [c["words"] for c in chs]
    with session_scope() as s:
        book = Book(title=(title or data["title"]).strip()[:60] or "导入的作品", genre=genre.strip()[:20], gender=gender if gender in ("male", "female") else "male",
                    tagline=tagline.strip()[:200], status="writing",
                    chapter_words=max(1000, min(8000, int(sorted(words)[len(words) // 2]) if words else 2200)),
                    target_words=max(1_000_000, sum(words) * 2))
        s.add(book)
        s.flush()
        for n, c in enumerate(chs, 1):
            s.add(Chapter(book_id=book.id or 0, number=n, title=c["title"], content=c["content"], words=c["words"], status="committed",
                          review=None, lint=None, summary=""))
        meta = {"volumes": {str(n): c["volume"] for n, c in enumerate(chs, 1) if c["volume"]}}
        from app.db import kv_set

        kv_set(s, f"import_meta:{book.id}", meta)
        s.commit()
        s.refresh(book)
        bid = book.id or 0
    _cache.pop(import_id, None)
    return {"book_id": bid, "chapters": len(chs), "words": sum(words)}


# ------------------------------------------------------------------ 接管

def _sample_summaries(rows: list[tuple[int, str, str]]) -> str:
    lines = [f"第{n}章 {t}：{sm}" for n, t, sm in rows]
    text = "\n".join(lines)
    if len(text) <= SUMMARY_BATCH_CHARS:
        return text
    keep_head = lines[:30]
    keep_tail = lines[-60:]
    mid = lines[30:-60]
    room = SUMMARY_BATCH_CHARS - len("\n".join(keep_head + keep_tail)) - 200
    step = max(1, int(len("\n".join(mid)) / max(1, room)) + 1)
    return "\n".join(keep_head + ["……（中间章节按间隔抽样）"] + mid[::step] + keep_tail)


def adopt(book_id: int, steps: list[str], ctx: JobContext) -> dict[str, Any]:
    from app.services.writing import _summarize

    steps = [x for x in steps if x in ("summary", "bible", "ledger", "outline")] or ["summary", "bible", "ledger", "outline"]
    res: dict[str, Any] = {"summaries": 0, "cards": 0, "facts": 0, "foreshadows": 0, "outline_nodes": 0, "skipped_cards": []}
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = common.kit_meta(s, book)
        rows = [(c.id or 0, c.number, c.title, c.summary or "") for c in common.committed_chapters(s, book_id)]
    if not rows:
        raise ExtractError("这本书还没有已提交的章节")
    total = len(rows)
    # 1) 逐章摘要（已有的跳过：中断后重跑会接着做）
    if "summary" in steps or "bible" in steps or "ledger" in steps:
        todo = [r for r in rows if not r[3].strip()]
        for k, (cid, num, _t, _) in enumerate(todo, 1):
            ctx.progress(2 + int(60 * k / max(1, len(todo))), f"补摘要：第 {num} 章（{k}/{len(todo)}）")
            with session_scope() as s:
                ch = s.get(Chapter, cid)
                if ch is None or (ch.summary or "").strip():
                    continue
                content = ch.content
            summ = _summarize(content, num, {}, meta)
            with session_scope() as s:
                ch = s.get(Chapter, cid)
                if ch is not None:
                    ch.summary = summ
                    ch.updated_at = utcnow()
                    s.add(ch)
                    s.commit()
            res["summaries"] += 1
        with session_scope() as s:
            rows = [(c.id or 0, c.number, c.title, c.summary or "") for c in common.committed_chapters(s, book_id)]
    # 2) 反推设定卡 + 账本
    if "bible" in steps or "ledger" in steps:
        ctx.progress(65, "从摘要反推设定和伏笔")
        with session_scope() as s:
            book = common.get_book(s, book_id)
            existing = common.cards(s, book_id, include_deprecated=True)
            ex_names = [c.name for c in existing]
        user = render("adopt_bible", n_chapters=total, title=book.title,
                      summaries=_sample_summaries([(n, t, sm) for _, n, t, sm in rows]),
                      existing="、".join(ex_names) or "（无）")
        data = get_gateway().chat_json("adopt_bible", system_prompt("adopt_bible"), user,
                                       meta={**meta, "existing": ex_names, "chapters": total, "summaries": [sm for *_, sm in rows][:50]})
        if not isinstance(data, dict):
            raise ValueError("反推结果不是 JSON 对象")
        ctx.progress(85, "写入设定卡和账本")
        with session_scope() as s:
            from app.services import bible_ops

            cards = {c.name: c for c in common.cards(s, book_id, include_deprecated=True)}
            if "bible" in steps:
                if cards:
                    bible_ops.snapshot(s, book_id, "接管旧书前")
                for it in data.get("cards") or []:
                    card = bible_ops.normalize_card(it) if isinstance(it, dict) else None
                    if card is None:
                        continue
                    old = cards.get(card["name"])
                    if old is not None:  # 已有同名卡（包括锁定的）不覆盖
                        res["skipped_cards"].append(card["name"])
                        continue
                    if card["type"] not in CARD_TYPES:
                        card["type"] = "character"
                    c = Card(book_id=book_id, **card)
                    s.add(c)
                    s.flush()
                    cards[c.name] = c
                    res["cards"] += 1
            if "ledger" in steps:
                for f in data.get("facts") or []:
                    if not isinstance(f, dict) or not str(f.get("key") or "").strip():
                        continue
                    ent = cards.get(str(f.get("entity") or ""))
                    try:
                        fc = max(0, min(total, int(f.get("from_chapter") or 0)))
                    except (TypeError, ValueError):
                        fc = 0
                    dup = s.exec(select(Fact).where(Fact.book_id == book_id, Fact.entity_id == (ent.id if ent else None),
                                                    Fact.key == str(f["key"])[:60], Fact.to_chapter == None)).first()  # noqa: E711
                    if dup is not None:
                        continue
                    s.add(Fact(book_id=book_id, entity_id=ent.id if ent else None, key=str(f["key"])[:60], value=str(f.get("value") or "")[:500],
                               from_chapter=fc, visibility="author"))
                    res["facts"] += 1
                have = {fs.desc for fs in s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id))}
                for fs in data.get("foreshadows") or []:
                    if not isinstance(fs, dict) or not str(fs.get("desc") or "").strip() or str(fs["desc"]).strip() in have:
                        continue

                    def _ch(v: Any, default: int = 0) -> int:
                        try:
                            return max(0, min(total, int(v)))
                        except (TypeError, ValueError):
                            return default
                    st = fs.get("status") if fs.get("status") in ("planted", "advancing", "resolved") else "planted"
                    pc = _ch(fs.get("planted_ch"), 1)
                    s.add(Foreshadow(book_id=book_id, desc=str(fs["desc"]).strip()[:300], status=st, planted_ch=pc,
                                     last_ch=_ch(fs.get("last_ch"), pc) or pc,
                                     resolved_ch=_ch(fs.get("resolved_ch")) or None if st == "resolved" else None,
                                     tier=fs.get("tier") if fs.get("tier") in ("short", "mid", "long") else "mid", source="manual",
                                     note="接管旧书时从已写章节反推"))
                    res["foreshadows"] += 1
            s.commit()
    # 3) 大纲：卷 / 弧 / 章（章节点挂上章节，已成文）
    if "outline" in steps:
        ctx.progress(92, "按章节生成大纲")
        res["outline_nodes"] = _build_outline(book_id)
    ctx.progress(100, "接管完成")
    return res


def _build_outline(book_id: int) -> int:
    from app.db import kv_get

    with session_scope() as s:
        book = common.get_book(s, book_id)
        nodes = common.outline_nodes(s, book_id)
        linked = {n.chapter_id for n in nodes if n.level == "chapter" and n.chapter_id}
        chs = [c for c in common.committed_chapters(s, book_id) if c.id not in linked]
        if not chs:
            return 0
        vol_names: dict[str, str] = (kv_get(s, f"import_meta:{book_id}", {}) or {}).get("volumes") or {}
        root = next((n for n in nodes if n.level == "book"), None)
        if root is None:
            root = OutlineNode(book_id=book_id, level="book", order=1, title=book.title, summary=book.premise or book.tagline or "", status="expanded")
            s.add(root)
            s.flush()
        groups: list[tuple[str, list[Chapter]]] = []
        for c in chs:
            vname = vol_names.get(str(c.number)) or ""
            if not groups or (vname and vname != groups[-1][0]):
                groups.append((vname or "已写部分", [c]))
            else:
                groups[-1][1].append(c)
        n_vol = sum(1 for n in nodes if n.level == "volume")
        made = 0
        for gi, (vname, items) in enumerate(groups, 1):
            vol = OutlineNode(book_id=book_id, parent_id=root.id, level="volume", order=n_vol + gi, title=vname[:80],
                              summary=f"第{items[0].number}–{items[-1].number}章（导入）", status="expanded")
            s.add(vol)
            s.flush()
            arc = OutlineNode(book_id=book_id, parent_id=vol.id, level="arc", order=1, title=f"{vname}·全部章节"[:80],
                              summary="", status="expanded")
            s.add(arc)
            s.flush()
            made += 2
            for c in items:
                first = re.split(r"(?<=[。！？])", (c.summary or "").strip(), maxsplit=1)[0]
                node = OutlineNode(book_id=book_id, parent_id=arc.id, level="chapter", order=c.number, title=c.title or f"第{c.number}章",
                                   summary=first[:200], status="written", chapter_id=c.id,
                                   beats={"title": c.title or f"第{c.number}章", "goal": first[:120]})
                s.add(node)
                s.flush()
                if not c.outline_node_id:
                    c.outline_node_id = node.id
                    s.add(c)
                made += 1
        s.commit()
        return made


def adopt_status(book_id: int) -> dict[str, Any]:
    with session_scope() as s:
        common.get_book(s, book_id)
        chs = common.committed_chapters(s, book_id)
        with_sum = sum(1 for c in chs if (c.summary or "").strip())
        nodes = common.outline_nodes(s, book_id)
        linked = sum(1 for n in nodes if n.level == "chapter" and n.chapter_id)
        return {"chapters": len(chs), "summaries": with_sum, "cards": len(common.cards(s, book_id)),
                "foreshadows": len(list(s.exec(select(Foreshadow.id).where(Foreshadow.book_id == book_id)))),
                "outline_linked": linked}
