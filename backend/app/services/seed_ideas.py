"""v0.9.2 「榜单 → 立项」：种子立项、一键整理、多本熔炉。

- seed_direct：不调模型，把种子（日报灵感卡 / 单书 / 粘贴 / 熔炉 / 手填）直接映射成 Idea，评分留空。
- seed_expand：planner 把种子扩成完整 Idea（结构、禁用套路清单同 /ideas/generate），程序做来源自检。
- organize：把作者粘贴的零散想法整理成一个 Idea，不改作者核心设定；原文只存前 60 字摘录。
- fusion：1–3 本参考（榜单书 / 书名 / 粘贴原文），按权重熔成 n 个原创 Idea；
  结果用 v0.7 的 8 字 n-gram 与每本参考的书名、简介、原文比对，过相似丢弃计 dropped。粘贴原文只在本次使用，不入库。

Idea.source 统一带 type（trend_report | rank_book | paste | fusion | manual）与 ref；kind 同 type，兼容 v0.7 的 source.kind。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Idea, RankItem, RankTeardown, TrendReport
from app.radar import service as radar
from app.services import common, planning, tropes
from app.services.common import NotFound
from app.services.imitate import DEEP_MAX_CHARS, OVERLAP_N, TITLE_OVERLAP_N, _count, overlap_segments
from app.skills.loader import render, system_prompt

SOURCE_LABEL = {"trend_report": "风向标日报的灵感卡", "rank_book": "一本榜单书", "paste": "作者粘贴的想法",
                "fusion": "多本熔炉", "manual": "作者自己填的种子"}
ORGANIZE_MAX_CHARS = 5000
FUSION_PROMPT_TEXT_CHARS = 6000  # 每本参考原文进提示词的上限（查重仍用全文）


def _s(v: Any, n: int = 300) -> str:
    if isinstance(v, (list, tuple)):
        v = "；".join(str(x) for x in v if x)
    return str(v or "").strip()[:n]


def _strs(v: Any, k: int, n: int) -> list[str]:
    if isinstance(v, str):
        v = [x for x in re.split(r"[；;\n]+", v) if x.strip()]
    return [str(x).strip()[:n] for x in (v if isinstance(v, list) else []) if str(x).strip()][:k]


def _idea_text(x: dict[str, Any]) -> str:
    return json.dumps({k: x.get(k) for k in ("title", "logline", "selling_points", "hook", "expectations", "endgame", "arc")},
                      ensure_ascii=False)


def _existing(gender: str) -> str:
    with session_scope() as s:
        recent = s.exec(select(Idea).where(Idea.gender == gender).order_by(Idea.id.desc()).limit(30)).all()  # type: ignore[union-attr]
        return "\n".join(f"- 《{i.title}》{i.logline[:50]}" for i in recent) or "（无）"


def _book_ref(book_id_ext: str) -> dict[str, Any]:
    """最新一条榜单记录的书名 / 简介 / 标签 / 题材，以及 v0.7 已有的拆解（有就带）。"""
    with session_scope() as s:
        row = s.exec(select(RankItem).where(RankItem.book_id_ext == book_id_ext).order_by(RankItem.id.desc())).first()  # type: ignore[union-attr]
        if row is None:
            raise NotFound(f"榜单里没有这本书：{book_id_ext}")
        td = s.exec(select(RankTeardown).where(RankTeardown.book_id_ext == book_id_ext).order_by(RankTeardown.id.desc())).first()  # type: ignore[union-attr]
        return {"book_id_ext": row.book_id_ext, "title": row.title, "abstract": row.abstract or "", "tags": list(row.tags or []),
                "category": row.category or "", "gender": row.gender, "teardown": (td.teardown if td else None) or {},
                "deep": (td.deep if td else None) or {}}


def _overlap(text: str, refs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """→ [{ref, segments}]：text 和每个参考（标签, 全文）连续 8 字相同的片段。"""
    out = []
    for label, ref in refs:
        segs = overlap_segments(text, ref)
        if segs:
            out.append({"ref": label, "count": len(segs), "segments": [x[:30] for x in segs[:5]]})
    return out


def _finalize(items: list[dict[str, Any]], gender: str, genre: str | None) -> list[dict[str, Any]]:
    """模型给的 Idea 结构 → 清洗 + 复核打分（同 /ideas/generate）。"""
    with session_scope() as s:
        trends = radar.compute_trends(s, gender=gender)
    reviewed = planning._review_scores(items, gender, trends) if items else {}
    out = []
    for n, x in enumerate(items, 1):
        g = _s(x.get("genre") or genre, 20)
        title = planning._clean_title(x.get("title") or "", g)
        out.append({"title": title, "logline": _s(x.get("logline"), 300), "selling_points": _strs(x.get("selling_points"), 4, 60),
                    "hook": _s(x.get("hook")), "expectations": _strs(x.get("expectations"), 3, 80), "endgame": _s(x.get("endgame"), 120),
                    "arc": _strs(x.get("arc"), 6, 120), "genre": g, "gender": gender,
                    "scores": planning._score(reviewed.get(n) or {}, planning._heat_for(g, trends), title)})
    return out


def _save(x: dict[str, Any]) -> dict[str, Any]:
    from app.api.schemas import idea_out

    with session_scope() as s:
        idea = Idea(**{k: x[k] for k in ("title", "logline", "selling_points", "hook", "expectations", "endgame", "arc", "genre", "gender",
                                         "scores", "source") if k in x})
        s.add(idea)
        s.commit()
        s.refresh(idea)
        return idea_out(idea, tropes.global_tropes(s))


def _check_tropes(x: dict[str, Any]) -> list[str]:
    with session_scope() as s:
        tl = tropes.global_tropes(s)
    hits = tropes.detect(_idea_text(x), tl)
    return [f"命中禁用套路：{'、'.join(h['name'] for h in hits)}"] if hits else []


# ------------------------------------------------------------------ 1. 种子立项

def _seed_fields(seed: dict[str, Any]) -> dict[str, Any]:
    return {"title": _s(seed.get("title"), 60).strip("《》"), "logline": _s(seed.get("logline"), 500),
            "protagonist": _s(seed.get("protagonist"), 300), "mechanism": _s(seed.get("mechanism"), 300),
            "opening": _s(seed.get("opening"), 500), "selling_points": _strs(seed.get("selling_points"), 8, 60),
            "genre": _s(seed.get("genre"), 30)}


def _seed_source(src: dict[str, Any], seed: dict[str, Any], **extra: Any) -> dict[str, Any]:
    t = src.get("type") or "manual"
    ref = _s(src.get("ref"), 200)
    if not ref and src.get("report_id"):
        ref = f"trend_report#{src['report_id']}"
    if not ref and src.get("book_id_ext"):
        ref = f"rank_book:{src['book_id_ext']}"
    out: dict[str, Any] = {"type": t, "kind": t, "ref": ref or None, "seed": seed, "warnings": []}
    for k in ("report_id", "book_id_ext"):
        if src.get(k) not in (None, ""):
            out[k] = src[k]
    out.update(extra)
    return out


def _resolve_seed_context(src: dict[str, Any], gender: str | None) -> tuple[str, dict[str, Any] | None]:
    """→ (gender, 参考书)。rank_book 带 book_id_ext 时读那本书（找不到 404）；trend_report 带 report_id 时校验存在。"""
    book = None
    if src.get("book_id_ext"):
        book = _book_ref(str(src["book_id_ext"]))
    if src.get("report_id") is not None:
        with session_scope() as s:
            if s.get(TrendReport, int(src["report_id"])) is None:
                raise NotFound("风向标日报不存在")
    return gender or (book["gender"] if book else None) or "male", book


def check_seed(body: dict[str, Any]) -> None:
    """POST 前同步检查（参考书 / 日报不存在 404）。"""
    _resolve_seed_context(body.get("source") or {}, body.get("gender"))


def seed_direct(body: dict[str, Any]) -> dict[str, Any]:
    """不调模型：种子 → Idea。hook←opening；主角 / 机制原样记在 source.seed（建书时并进 premise）。评分留空。"""
    src = body.get("source") or {}
    gender, book = _resolve_seed_context(src, body.get("gender"))
    seed = _seed_fields(body)
    x = {"title": seed["title"][:40], "logline": seed["logline"], "selling_points": seed["selling_points"][:4], "hook": seed["opening"],
         "expectations": [], "endgame": "", "arc": [], "genre": seed["genre"], "gender": gender, "scores": None}
    source = _seed_source(src, seed, expanded=False)
    if book:
        ov = _overlap(_idea_text(x), [(f"《{book['title']}》", f"{book['title']}\n{book['abstract']}")])
        source["overlap"] = ov
        if ov:
            source["warnings"].append(f"和《{book['title']}》的书名/简介有 {ov[0]['count']} 处连续 {OVERLAP_N} 字相同")
    source["warnings"] += _check_tropes(x)
    x["source"] = source
    return {"idea": _save(x)}


def seed_expand(body: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    src = body.get("source") or {}
    gender, book = _resolve_seed_context(src, body.get("gender"))
    seed = _seed_fields(body)
    genre = seed["genre"] or (book["category"] if book else "")
    with session_scope() as s:
        tl = tropes.global_tropes(s)
    seed_text = "\n".join(f"{label}：{v}" for label, v in (
        ("书名", seed["title"]), ("一句话钩子", seed["logline"]), ("主角", seed["protagonist"]), ("核心机制", seed["mechanism"]),
        ("第一章开局", seed["opening"]), ("卖点", "；".join(seed["selling_points"])), ("题材", genre)) if v)
    ref_block = (f"种子参考的榜单书：《{book['title']}》（{book['category']}）。简介只用来避开，不要沿用其中的词句和专有名词：{book['abstract'][:200]}\n\n"
                 if book else "")
    ctx.progress(15, "把种子扩成完整选题")
    user = render("idea_seed", source_label=SOURCE_LABEL.get(src.get("type") or "manual", "选题种子"),
                  gender_label=common.GENDER_LABEL.get(gender, gender), genre_hint=f"题材：{genre}。" if genre else "",
                  seed=seed_text, ref_block=ref_block, existing=_existing(gender)) + tropes.prompt_block(tl)
    data = get_gateway().chat_json("idea_seed", system_prompt("idea_seed"), user,
                                   meta={"seed": seed, "gender": gender, "genre": genre, "banned_keywords": tropes.keywords(tl)})
    if isinstance(data, dict) and isinstance(data.get("idea"), dict):
        data = data["idea"]
    if not isinstance(data, dict) or not _s(data.get("title")):
        raise ValueError("模型没有返回扩写后的选题")
    ctx.progress(70, "复核打分与来源自检")
    x = _finalize([data], gender, genre)[0]
    checks = [{"aspect": _s(c.get("aspect"), 20), "kept": bool(c.get("kept")), "note": _s(c.get("note"), 80)}
              for c in data.get("self_check") or [] if isinstance(c, dict) and c.get("aspect")]
    source = _seed_source(src, seed, expanded=True, change=_s(data.get("change"), 120), self_check=checks)
    if book:
        ov = _overlap(_idea_text(x), [(f"《{book['title']}》", f"{book['title']}\n{book['abstract']}")])
        title_segs = overlap_segments(x["title"], book["title"], TITLE_OVERLAP_N)
        source["overlap"] = ov
        if ov:
            source["warnings"].append(f"和《{book['title']}》的书名/简介有 {ov[0]['count']} 处连续 {OVERLAP_N} 字相同：{'、'.join(ov[0]['segments'][:3])}")
        if title_segs:
            source["warnings"].append(f"书名和《{book['title']}》太像：{'、'.join(title_segs[:2])}")
    source["warnings"] += _check_tropes(x)
    x["source"] = source
    ctx.progress(95, "保存到选题库")
    idea = _save(x)
    return {"idea": idea, "idea_id": idea["id"]}


# ------------------------------------------------------------------ 2. 一键整理

def check_organize_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("内容不能为空")
    if len(text) > ORGANIZE_MAX_CHARS:
        raise ValueError(f"内容 {len(text)} 字，超过 {ORGANIZE_MAX_CHARS} 字上限")
    return text


def organize(text: str, genre: str | None, gender: str | None, ctx: JobContext) -> dict[str, Any]:
    text = check_organize_text(text)
    gender = gender or "male"
    with session_scope() as s:
        tl = tropes.global_tropes(s)
    ctx.progress(15, "整理想法")
    user = render("idea_organize", gender_label=common.GENDER_LABEL.get(gender, gender), genre_hint=f"题材：{genre}。" if genre else "",
                  text=text, existing=_existing(gender)) + tropes.prompt_block(tl)
    with session_scope() as s:
        user += common.name_note(s)
    data = get_gateway().chat_json("idea_organize", system_prompt("idea_organize"), user,
                                   meta={"text": text, "gender": gender, "genre": genre, "banned_keywords": tropes.keywords(tl)})
    if isinstance(data, dict) and isinstance(data.get("idea"), dict):
        data = {**data["idea"], **{k: v for k, v in data.items() if k != "idea"}}
    if not isinstance(data, dict) or not _s(data.get("title")):
        raise ValueError("模型没有返回整理后的选题")
    ctx.progress(70, "复核打分")
    x = _finalize([data], gender, genre)[0]
    kept = _strs(data.get("kept_core"), 12, 60)
    flat = re.sub(r"\s", "", _idea_text(x))
    missing = [k for k in kept if 2 <= len(k) <= 12 and re.sub(r"\s", "", k) not in flat and re.sub(r"\s", "", k) in re.sub(r"\s", "", text)]
    warnings = [f"作者原有设定在整理稿里没找到原词，请核对：{'、'.join(missing[:5])}"] if missing else []
    warnings += _check_tropes(x)
    x["source"] = {"type": "paste", "kind": "organize", "ref": re.sub(r"\s+", " ", text)[:60], "chars": len(text),
                   "kept_core": kept, "added": _strs(data.get("added"), 12, 80), "conflicts": _strs(data.get("conflicts"), 6, 120),
                   "warnings": warnings}
    ctx.progress(95, "保存到选题库")
    idea = _save(x)
    return {"idea": idea, "idea_id": idea["id"]}


# ------------------------------------------------------------------ 3. 多本熔炉

def resolve_fusion_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同步校验并补全参考：book_id_ext 读榜单（不存在 404）；text 去空白后 ≤20000 字；权重归一化。"""
    if not 1 <= len(refs) <= 3:
        raise ValueError("参考书要 1–3 本")
    out = []
    for i, r in enumerate(refs, 1):
        text = (r.get("text") or "").strip()
        if text and _count(text) > DEEP_MAX_CHARS:
            raise ValueError(f"参考{i}的原文 {_count(text)} 字，超过 {DEEP_MAX_CHARS} 字上限")
        item: dict[str, Any] = {"index": i, "title": _s(r.get("title"), 60).strip("《》"), "abstract": "", "tags": [], "category": "",
                                "teardown": {}, "deep": {}, "text": text, "book_id_ext": r.get("book_id_ext") or None}
        if item["book_id_ext"]:
            b = _book_ref(str(item["book_id_ext"]))
            item.update({k: b[k] for k in ("abstract", "tags", "category", "teardown", "deep")})
            item["title"] = item["title"] or b["title"]
            item["gender"] = b["gender"]
        if not (item["title"] or item["text"]):
            raise ValueError(f"参考{i}至少要有 book_id_ext、title 或 text 之一")
        item["weight_raw"] = float(r.get("weight") or 1.0)
        out.append(item)
    total = sum(x["weight_raw"] for x in out) or 1.0
    for x in out:
        x["weight"] = round(x["weight_raw"] / total, 3)
    return out


def _ref_prompt(r: dict[str, Any]) -> str:
    lines = [f"【参考{r['index']}】权重 {r['weight']:.2f}｜" + (f"《{r['title']}》" if r["title"] else "（作者粘贴的原文）")
             + (f"｜{r['category']}" if r["category"] else "")]
    if r["tags"]:
        lines.append("标签：" + "、".join(r["tags"][:8]))
    if r["abstract"]:
        lines.append("简介（只借结构，不沿用词句）：" + r["abstract"][:300])
    td = r.get("teardown") or {}
    if td:
        gf = td.get("golden_finger") or {}
        lines.append("已有拆解：" + "；".join(x for x in (
            f"爽点公式 {td.get('payoff_formula')}" if td.get("payoff_formula") else "",
            f"金手指 {gf.get('type')}，兑现 {gf.get('delivery')}" if gf.get("type") else "",
            f"人设模板 {td.get('protagonist_template')}" if td.get("protagonist_template") else "",
            f"开篇钩子 {td.get('opening_hook')}" if td.get("opening_hook") else "",
            f"可迁移 {'、'.join(td.get('transferable') or [])}" if td.get("transferable") else "") if x))
    dp = r.get("deep") or {}
    if dp.get("rhythm") or dp.get("learnable"):
        lines.append(f"深度拆解：节奏 {dp.get('rhythm', '')}；可学 {'、'.join(dp.get('learnable') or [])}")
    if r["text"]:
        lines.append("原文节选（学结构和语感，不许照抄句子）：\n" + r["text"][:FUSION_PROMPT_TEXT_CHARS])
    return "\n".join(lines)


def fusion(refs: list[dict[str, Any]], notes: str | None, n: int, ctx: JobContext) -> dict[str, Any]:
    refs = resolve_fusion_refs(refs)
    n = max(1, min(5, int(n or 3)))
    gender = next((r["gender"] for r in sorted(refs, key=lambda r: -r["weight"]) if r.get("gender")), "male")
    genre = next((r["category"] for r in sorted(refs, key=lambda r: -r["weight"]) if r.get("category")), "")
    with session_scope() as s:
        tl = tropes.global_tropes(s)
    ctx.progress(10, f"熔炼 {len(refs)} 本参考")
    user = render("idea_fusion", n=n, gender_label=common.GENDER_LABEL.get(gender, gender),
                  refs="\n\n".join(_ref_prompt(r) for r in refs),
                  notes_block=f"作者的要求：{notes.strip()}\n\n" if notes and notes.strip() else "",
                  existing=_existing(gender)) + tropes.prompt_block(tl)
    data = get_gateway().chat_json("idea_fusion", system_prompt("idea_fusion"), user, meta={
        "n": n, "gender": gender, "genre": genre, "banned_keywords": tropes.keywords(tl),
        "refs": [{k: r[k] for k in ("index", "title", "abstract", "category", "weight")} | {"text": r["text"][:2000]} for r in refs]})
    items = data.get("ideas") if isinstance(data, dict) else data
    if isinstance(items, dict):
        items = [items]
    items = [x for x in (items if isinstance(items, list) else []) if isinstance(x, dict) and _s(x.get("title"))][:n]
    if not items:
        raise ValueError("模型没有返回熔炉选题")
    ctx.progress(60, "查重：和每本参考的书名、简介、原文比对")
    compare = [(f"参考{r['index']}" + (f"《{r['title']}》" if r["title"] else ""), "\n".join(x for x in (r["title"], r["abstract"], r["text"]) if x))
               for r in refs]
    kept_raw: list[dict[str, Any]] = []
    warnings: list[str] = []
    dropped = 0
    for x in items:
        ov = _overlap(_idea_text(x), compare)
        title = _s(x.get("title"), 40)
        if ov:
            dropped += 1
            warnings.append(f"已丢弃《{title}》：和{ov[0]['ref']}有 {ov[0]['count']} 处连续 {OVERLAP_N} 字相同（{ov[0]['segments'][0][:20]}）")
            continue
        kept_raw.append(x)
    ref_label = "；".join((f"《{r['title']}》" if r["title"] else f"粘贴原文{r['index']}") + f"×{r['weight']:.2f}" for r in refs)
    out: list[dict[str, Any]] = []
    if kept_raw:
        ctx.progress(75, "复核打分")
        for x, raw in zip(_finalize(kept_raw, gender, genre), kept_raw):
            w: list[str] = []
            for r in refs:
                if r["title"] and overlap_segments(x["title"], r["title"], TITLE_OVERLAP_N):
                    w.append(f"书名和《{r['title']}》连续 {TITLE_OVERLAP_N} 字相同")
            w += _check_tropes(x)
            warnings += [f"《{x['title']}》：{m}" for m in w]
            x["source"] = {"type": "fusion", "kind": "fusion", "ref": ref_label,
                           "refs": [{"index": r["index"], "title": r["title"] or None, "book_id_ext": r["book_id_ext"], "weight": r["weight"],
                                     "has_text": bool(r["text"])} for r in refs],
                           "notes": _s(notes, 200) or None,
                           "borrowed": [{"ref": _s(b.get("ref"), 10), "what": _s(b.get("what"), 80)} for b in raw.get("borrowed") or [] if isinstance(b, dict)][:6],
                           "changed": _strs(raw.get("changed"), 6, 80), "overlap": [], "warnings": w}
            out.append(_save(x))
    if len(out) < n:
        warnings.append(f"只留下 {len(out)} 个选题（要求 {n} 个，丢弃 {dropped} 个）")
    return {"ideas": out, "idea_ids": [i["id"] for i in out], "dropped": dropped, "warnings": warnings}
