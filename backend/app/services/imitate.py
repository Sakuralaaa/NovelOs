"""v0.7 榜单仿写：拆解榜单书（只学结构）→ 出换皮选题。

- teardown：只用书名/简介/标签/品类/热度/名次变化，让模型拆出爽点公式、金手指、人设模板等；按榜单条目缓存。
- deep：作者贴的试读原文（≤20000 字）。程序算按章字数、对白比例、首个冲突/金手指关键词位置，模型只补每章冲突/爽点/钩子。
- reskin：基于拆解出 3 个换皮选题，按 Idea 结构保存（来源与相似点自检放在 Idea.source），可直接走现有「采纳建书」。
- ngram_overlap：连续重合片段计数，用来提醒“抄得太像”，只提醒不拦截。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.llm.gateway import get_gateway
from app.models.tables import Idea, RankItem, RankTeardown, utcnow
from app.radar import service as radar
from app.services import common, tropes
from app.services.common import NotFound
from app.skills.loader import render, system_prompt

DEEP_MAX_CHARS = 20000
OVERLAP_N = 8  # 连续 8 字相同算一处重合
OVERLAP_WARN = 1  # 重合片段数 ≥ 这个值就加 warning
TITLE_OVERLAP_N = 4  # 书名连续 4 字相同就提醒
RESKIN_COUNT = 3

Progress = Callable[[int, str], None] | None  # 任务进度回调：JobContext.progress(pct, message)


def _report(progress: Progress, pct: int, message: str) -> None:
    if progress is not None:
        progress(pct, message)

CONFLICT_WORDS = ("退婚", "废物", "羞辱", "嘲笑", "嘲讽", "冷笑", "欺负", "威胁", "逼", "跪下", "滚", "打断", "耳光", "杀", "动手", "挑衅",
                  "看不起", "瞧不起", "背叛", "陷害", "赶出")
CHEAT_WORDS = ("系统", "金手指", "面板", "签到", "觉醒", "叮", "奖励", "天赋", "异能", "传承", "空间", "重生", "穿越", "外挂", "词条", "属性点")

_PUNCT_RE = re.compile(r"[\s\u3000，。！？、；：,.!?;:“”‘’\"'「」『』（）()《》【】\[\]…—\-·~～]+")
_CH_RE = re.compile(r"^[ \t\u3000]*(第[0-9零〇一二两三四五六七八九十百千]+[章节回][^\n]{0,30})[ \t\u3000]*$", re.M)
_DIALOGUE_RE = re.compile(r"“([^”]*)”|「([^」]*)」|\"([^\"\n]*)\"")


# ------------------------------------------------------------------ 原文重合检测

def _norm(text: str) -> str:
    return _PUNCT_RE.sub("", text or "")


def overlap_segments(a: str, b: str, n: int = OVERLAP_N) -> list[str]:
    """a 中与 b 连续 n 字（去空白和标点后）相同的片段，相邻的命中合并成一段。"""
    a, b = _norm(a), _norm(b)
    if n <= 0 or len(a) < n or len(b) < n:
        return []
    grams = {b[i:i + n] for i in range(len(b) - n + 1)}
    segs: list[str] = []
    start = last = -2
    for i in range(len(a) - n + 1):
        if a[i:i + n] not in grams:
            continue
        if i == last + 1:
            last = i
            continue
        if start >= 0:
            segs.append(a[start:last + n])
        start = last = i
    if start >= 0:
        segs.append(a[start:last + n])
    return segs


def ngram_overlap(a: str, b: str, n: int = OVERLAP_N) -> int:
    """连续重合片段计数：a 里有几段（每段至少 n 字）和 b 一字不差。"""
    return len(overlap_segments(a, b, n))


def _dump(obj: Any) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)


# ------------------------------------------------------------------ 公共

def _item_dict(s: Session, rank_item: RankItem | int) -> dict[str, Any]:
    rid = rank_item if isinstance(rank_item, int) else rank_item.id
    it = s.get(RankItem, rid or 0)
    if it is None:
        raise NotFound("榜单条目不存在")
    return it.model_dump()


def _row(s: Session, rank_item_id: int) -> RankTeardown | None:
    return s.exec(select(RankTeardown).where(RankTeardown.rank_item_id == rank_item_id).order_by(RankTeardown.id.desc())).first()  # type: ignore[union-attr]


def teardown_out(r: RankTeardown, cached: bool = False) -> dict[str, Any]:
    from app.api.schemas import iso

    return {"id": r.id, "rank_item_id": r.rank_item_id, "book_id_ext": r.book_id_ext, "title": r.title,
            "teardown": r.teardown, "deep": r.deep, "created_at": iso(r.created_at), "cached": cached}


def get_teardown(rank_item_id: int) -> dict[str, Any]:
    with session_scope() as s:
        _item_dict(s, rank_item_id)
        r = _row(s, rank_item_id)
        if r is None:
            raise NotFound("这本书还没有拆解")
        return teardown_out(r, cached=True)


def _str(v: Any, n: int = 200) -> str:
    return str(v or "").strip()[:n]


def _strs(v: Any, k: int = 8, n: int = 80) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [str(x).strip()[:n] for x in (v if isinstance(v, list) else []) if str(x).strip()][:k]


# ------------------------------------------------------------------ 1. 拆解（只用公开信息）

def teardown(rank_item: RankItem | int, refresh: bool = False, progress: Progress = None) -> dict[str, Any]:
    with session_scope() as s:
        it = _item_dict(s, rank_item)
        row = _row(s, it["id"])
        if row is not None and row.teardown and not refresh:
            return teardown_out(row, cached=True)
        if not refresh:  # 同一本书在别的快照里拆过，直接复用
            same = s.exec(select(RankTeardown).where(RankTeardown.book_id_ext == it["book_id_ext"], RankTeardown.title == it["title"])
                          .order_by(RankTeardown.id.desc())).first()  # type: ignore[union-attr]
            if same is not None and same.teardown:
                r = row or RankTeardown(rank_item_id=it["id"], book_id_ext=it["book_id_ext"], title=it["title"])
                r.teardown = same.teardown
                s.add(r)
                s.commit()
                s.refresh(r)
                return teardown_out(r, cached=True)
    _report(progress, 10, f"拆解中：《{it['title']}》的爽点公式、金手指、人设")
    user = render("teardown", gender_label=common.GENDER_LABEL.get(it["gender"], it["gender"]), title=it["title"],
                  category=it["category"] or "未分类", tags="、".join(it.get("tags") or []) or "（无）",
                  abstract=it["abstract"] or "（无简介）", read_count=it["read_count"], rank=it["rank"], rank_diff=it["rank_diff"])
    data = get_gateway().chat_json("teardown", system_prompt("teardown"), user,
                                   meta={k: it[k] for k in ("title", "category", "tags", "gender", "rank", "rank_diff", "read_count")},
                                   temperature=0.4)
    if not isinstance(data, dict):
        raise ValueError("模型没有返回拆解")
    gf = data.get("golden_finger") if isinstance(data.get("golden_finger"), dict) else {"type": _str(data.get("golden_finger")), "delivery": ""}
    td: dict[str, Any] = {
        "payoff_formula": _str(data.get("payoff_formula")),
        "golden_finger": {"type": _str(gf.get("type"), 80), "delivery": _str(gf.get("delivery"))},
        "protagonist_template": _str(data.get("protagonist_template")),
        "opening_hook": _str(data.get("opening_hook")),
        "target_readers": _str(data.get("target_readers"), 120),
        "transferable": _strs(data.get("transferable")),
        "must_replace": _strs(data.get("must_replace")),
    }
    if not td["payoff_formula"] and not td["transferable"]:
        raise ValueError("模型没有返回有效的拆解")
    _report(progress, 90, "检查和简介的重合并保存")
    segs = overlap_segments(_dump(td), it["abstract"] or "")
    td["warnings"] = [f"拆解里有 {len(segs)} 处和简介原句连续 {OVERLAP_N} 字相同：{'、'.join(x[:20] for x in segs[:3])}"] if len(segs) >= OVERLAP_WARN else []
    with session_scope() as s:
        r = _row(s, it["id"]) or RankTeardown(rank_item_id=it["id"], book_id_ext=it["book_id_ext"], title=it["title"])
        r.teardown, r.created_at = td, utcnow()
        s.add(r)
        s.commit()
        s.refresh(r)
        return teardown_out(r)


# ------------------------------------------------------------------ 2. 深度拆解（作者贴试读原文）

def split_chapters(text: str) -> list[dict[str, str]]:
    """按「第N章」标题切章；没有标题时整段算一章。标题前的文字并进第一章。"""
    ms = list(_CH_RE.finditer(text))
    if not ms:
        return [{"title": "全文", "body": text.strip()}]
    out = []
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(text)
        out.append({"title": m.group(1).strip(), "body": text[m.end():end].strip()})
    pre = text[:ms[0].start()].strip()
    if pre:
        out[0]["body"] = pre + "\n" + out[0]["body"]
    return out


def _count(text: str) -> int:
    return len(re.sub(r"\s", "", text or ""))


def _first_hit(text: str, words: tuple[str, ...]) -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for w in words:
        i = text.find(w)
        if i >= 0 and (best is None or i < best[1]):
            best = (w, i)
    return best


def text_stats(text: str) -> dict[str, Any]:
    """程序统计：按章字数、对白比例、首个冲突/金手指关键词出现在第几字（去空白后计）。"""
    chs = split_chapters(text)
    rows: list[dict[str, Any]] = []
    flat_parts: list[str] = []
    for i, ch in enumerate(chs, 1):
        words = _count(ch["body"])
        dlg = sum(_count(next(g for g in m.groups() if g is not None)) for m in _DIALOGUE_RE.finditer(ch["body"]))
        rows.append({"index": i, "title": ch["title"], "words": words, "dialogue_ratio": round(dlg / words, 3) if words else 0.0})
        flat_parts.append(re.sub(r"\s", "", ch["body"]))
    flat = "".join(flat_parts)
    bounds, acc = [], 0
    for p in flat_parts:
        acc += len(p)
        bounds.append(acc)

    def locate(words: tuple[str, ...]) -> dict[str, Any] | None:
        hit = _first_hit(flat, words)
        if hit is None:
            return None
        ch = next((k + 1 for k, b in enumerate(bounds) if hit[1] < b), len(bounds))
        return {"keyword": hit[0], "at_char": hit[1] + 1, "chapter": ch}

    total = len(flat)
    dlg_total = sum(r["words"] * r["dialogue_ratio"] for r in rows)
    return {"chapters": rows, "total_words": total, "dialogue_ratio": round(dlg_total / total, 3) if total else 0.0,
            "first_conflict": locate(CONFLICT_WORDS), "first_cheat": locate(CHEAT_WORDS)}


def check_deep_text(text: str) -> str:
    """校验深度拆解原文（为空/超过 20000 字抛 ValueError → 400），返回去掉首尾空白的原文。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("原文不能为空")
    n = _count(text)
    if n > DEEP_MAX_CHARS:
        raise ValueError(f"原文 {n} 字，超过 {DEEP_MAX_CHARS} 字上限，请只贴前几章")
    return text


def deep(rank_item: RankItem | int, text: str, progress: Progress = None) -> dict[str, Any]:
    text = check_deep_text(text)
    with session_scope() as s:
        it = _item_dict(s, rank_item)
    _report(progress, 5, "统计按章字数与对白比例")
    st = text_stats(text)
    stats_text = "\n".join(f"{r['index']}. {r['title']}：{r['words']} 字，对白 {round(100 * r['dialogue_ratio'])}%" for r in st["chapters"])
    for key, label in (("first_conflict", "首个冲突关键词"), ("first_cheat", "首个金手指关键词")):
        h = st[key]
        stats_text += f"\n{label}：" + (f"「{h['keyword']}」在第 {h['at_char']} 字（第 {h['chapter']} 章）" if h else "未出现")
    _report(progress, 15, f"逐章拆解中（共 {len(st['chapters'])} 章）")
    user = render("teardown_deep", title=it["title"], category=it["category"] or "未分类", stats=stats_text, text=text)
    data = get_gateway().chat_json("teardown_deep", system_prompt("teardown_deep"), user,
                                   meta={"chapters": len(st["chapters"]), "title": it["title"], "stats": st}, temperature=0.3)
    if not isinstance(data, dict):
        raise ValueError("模型没有返回深度拆解")
    by_idx: dict[int, dict[str, Any]] = {}
    for c in data.get("chapters") or []:
        if isinstance(c, dict) and str(c.get("index", "")).isdigit():
            by_idx[int(c["index"])] = c
    chapters = [{**r, "conflict": _str(by_idx.get(r["index"], {}).get("conflict")), "payoff": _str(by_idx.get(r["index"], {}).get("payoff")),
                 "hook": _str(by_idx.get(r["index"], {}).get("hook"))} for r in st["chapters"]]
    model_part = {"chapters": [{k: c[k] for k in ("conflict", "payoff", "hook")} for c in chapters],
                  "rhythm": _str(data.get("rhythm")), "learnable": _strs(data.get("learnable"))}
    _report(progress, 90, "检查和原文的重合并保存")
    segs = overlap_segments(_dump(model_part), text)
    warnings = [f"拆解里有 {len(segs)} 处和原文连续 {OVERLAP_N} 字相同（只该学结构）：{'、'.join(x[:20] for x in segs[:3])}"] if len(segs) >= OVERLAP_WARN else []
    out = {"chapters": chapters, "total_words": st["total_words"], "dialogue_ratio": st["dialogue_ratio"],
           "first_conflict": st["first_conflict"], "first_cheat": st["first_cheat"], "rhythm": model_part["rhythm"],
           "learnable": model_part["learnable"], "overlap": len(segs), "warnings": warnings}
    with session_scope() as s:
        r = _row(s, it["id"]) or RankTeardown(rank_item_id=it["id"], book_id_ext=it["book_id_ext"], title=it["title"])
        r.deep = out  # 原文不落库，只存统计和结构
        s.add(r)
        s.commit()
        s.refresh(r)
        return teardown_out(r)


# ------------------------------------------------------------------ 3. 换皮选题

def _self_check(idea: dict[str, Any], it: dict[str, Any], td: dict[str, Any], tl: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """程序自检：简介/书名与原书的重合、必须换掉的元素是否还在、禁用套路。"""
    text = _dump({k: idea.get(k) for k in ("title", "logline", "selling_points", "hook", "expectations", "endgame", "arc")})
    ref = f"{it['title']}\n{it['abstract'] or ''}"
    segs = overlap_segments(text, ref)
    title_segs = overlap_segments(str(idea.get("title") or ""), it["title"], TITLE_OVERLAP_N)
    kept_bad = [m for m in td.get("must_replace") or [] if 2 <= len(m) <= 10 and m in text]
    hits = tropes.detect(text, tl)
    warnings: list[str] = []
    if len(segs) >= OVERLAP_WARN:
        warnings.append(f"和原书书名/简介有 {len(segs)} 处连续 {OVERLAP_N} 字相同：{'、'.join(x[:20] for x in segs[:3])}")
    if title_segs:
        warnings.append(f"书名和原书《{it['title']}》太像：{'、'.join(title_segs[:2])}")
    if kept_bad:
        warnings.append(f"还留着原书必须换掉的元素：{'、'.join(kept_bad[:4])}")
    if hits:
        warnings.append(f"命中禁用套路：{'、'.join(h['name'] for h in hits)}")
    model_check = []
    for c in idea.get("self_check") or []:
        if isinstance(c, dict) and c.get("aspect"):
            model_check.append({"aspect": _str(c.get("aspect"), 20), "original": _str(c.get("original"), 80), "ours": _str(c.get("ours"), 80),
                                "similar": bool(c.get("similar"))})
    still = [c["aspect"] for c in model_check if c["similar"]]
    if still:
        warnings.append(f"模型自检认为仍偏像：{'、'.join(still[:4])}")
    src = {"kind": "reskin", "rank_item_id": it["id"], "ref_title": it["title"], "ref_book_id_ext": it["book_id_ext"],
           "ref_category": it["category"], "kept": _strs(idea.get("kept")), "changed": _strs(idea.get("changed")),
           "self_check": model_check, "overlap": {"count": len(segs), "title": len(title_segs), "segments": [x[:30] for x in segs[:5]]},
           "warnings": warnings}
    return src, warnings


def reskin_preview(rank_item: RankItem | int, progress: Progress = None) -> dict[str, Any]:
    """出 3 个换皮选题（不落库）：返回 {teardown, ideas:[Idea 字段 + scores + source]}。

    v0.7.1：逐个生成（每次调用只出 1 个，并把本批已出的选题告诉模型避开），便于汇报进度、缩短单次调用时长。
    第一个就失败直接报错；后面的失败只少出几个，由调用方加提醒。
    """
    from app.services import planning

    _report(progress, 3, "读取拆解")
    td_out = teardown(rank_item, progress=(lambda p, m: _report(progress, 3 + p // 5, m)) if progress else None)
    td = td_out["teardown"] or {}
    with session_scope() as s:
        it = _item_dict(s, td_out["rank_item_id"])
        recent = s.exec(select(Idea).where(Idea.gender == it["gender"]).order_by(Idea.id.desc()).limit(30)).all()  # type: ignore[union-attr]
        existing = "\n".join(f"- 《{i.title}》{i.logline[:50]}" for i in recent) or "（无）"
        tl = tropes.global_tropes(s)
        trends = radar.compute_trends(s, gender=it["gender"])
    td_text = "\n".join([
        f"爽点公式：{td.get('payoff_formula', '')}",
        f"金手指：{(td.get('golden_finger') or {}).get('type', '')}；兑现方式：{(td.get('golden_finger') or {}).get('delivery', '')}",
        f"主角人设模板：{td.get('protagonist_template', '')}", f"开篇钩子：{td.get('opening_hook', '')}",
        f"目标读者：{td.get('target_readers', '')}", f"可迁移结构要素：{'；'.join(td.get('transferable') or [])}",
        f"必须换掉的元素：{'；'.join(td.get('must_replace') or [])}",
    ])
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for k in range(RESKIN_COUNT):
        _report(progress, 25 + k * 20, f"生成选题 {k + 1}/{RESKIN_COUNT}")
        batch = "\n".join(f"- 《{x['title']}》{_str(x.get('logline'), 60)}" for x in items) or "（这是第一个）"
        user = render("reskin", gender_label=common.GENDER_LABEL.get(it["gender"], it["gender"]), title=it["title"],
                      category=it["category"] or "未分类", abstract=it["abstract"] or "（无）", teardown=td_text, existing=existing,
                      index=k + 1, total=RESKIN_COUNT, batch=batch) + tropes.prompt_block(tl)
        try:
            data = get_gateway().chat_json("reskin", system_prompt("reskin"), user,
                                           meta={"title": it["title"], "category": it["category"], "gender": it["gender"], "count": 1,
                                                 "index": k, "must_replace": td.get("must_replace") or [],
                                                 "banned_keywords": tropes.keywords(tl)})
        except Exception as e:  # noqa: BLE001
            if not items:
                raise
            errors.append(f"第 {k + 1} 个选题生成失败：{e}")
            continue
        got = data.get("ideas") if isinstance(data, dict) and "ideas" in data else data
        if isinstance(got, dict):
            got = [got]
        got = [x for x in (got if isinstance(got, list) else []) if isinstance(x, dict) and x.get("title")]
        seen = {str(x["title"]) for x in items}
        got = [x for x in got if str(x["title"]) not in seen]
        if not got:
            errors.append(f"第 {k + 1} 个选题模型没有返回")
            continue
        items.append(got[0])
    if not items:
        raise ValueError("模型没有返回换皮选题")
    _report(progress, 88, "评分与相似点自检")
    reviewed = planning._review_scores(items, it["gender"], trends)
    ideas: list[dict[str, Any]] = []
    for n, x in enumerate(items, 1):
        g = _str(x.get("genre") or it["category"], 20)
        title = planning._clean_title(x["title"], g)
        x = {**x, "title": title}
        src, _ = _self_check(x, it, td, tl)
        ideas.append({
            "title": title, "logline": _str(x.get("logline"), 300), "selling_points": _strs(x.get("selling_points"), 4, 60),
            "hook": _str(x.get("hook")), "expectations": _strs(x.get("expectations"), 3), "endgame": _str(x.get("endgame"), 120),
            "arc": _strs(x.get("arc"), 6, 120), "genre": g, "gender": it["gender"],
            "scores": planning._score(reviewed.get(n) or {}, planning._heat_for(g, trends), title), "source": src,
        })
    return {"rank_item_id": it["id"], "teardown_id": td_out["id"], "ref_title": it["title"], "teardown": td, "ideas": ideas, "errors": errors}


def save_ideas(ideas: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    with session_scope() as s:
        for x in ideas:
            idea = Idea(**{k: x[k] for k in ("title", "logline", "selling_points", "hook", "expectations", "endgame", "arc", "genre", "gender",
                                             "scores", "source") if k in x})
            s.add(idea)
            s.flush()
            ids.append(idea.id or 0)
        s.commit()
    return ids


def reskin(rank_item: RankItem | int, progress: Progress = None) -> dict[str, Any]:
    """出 3 个换皮选题并保存为 Idea（之后走现有 POST /api/ideas/{id}/adopt 建书）。"""
    pv = reskin_preview(rank_item, progress=progress)
    _report(progress, 96, "保存到选题库")
    ids = save_ideas(pv["ideas"])
    warnings = [f"《{x['title']}》：{w}" for x in pv["ideas"] for w in x["source"]["warnings"]]
    warnings += pv.get("errors") or []
    if len(ids) < RESKIN_COUNT:
        warnings.append(f"模型只给了 {len(ids)} 个选题")
    return {"rank_item_id": pv["rank_item_id"], "teardown_id": pv["teardown_id"], "ref_title": pv["ref_title"],
            "idea_ids": ids, "warnings": warnings}


def find_rank_item(title: str) -> int | None:
    """按书名在最新快照里找榜单条目（Agent 工具用）。"""
    title = (title or "").strip().strip("《》")
    if not title:
        return None
    with session_scope() as s:
        snap = radar.latest_snapshot(s)
        if snap is None:
            return None
        rows = radar.snapshot_items(s, snap.id or 0, dedupe=False)
        for exact in (True, False):
            for r in rows:
                if (r.title == title) if exact else (title in r.title or r.title in title):
                    return r.id
    return None
