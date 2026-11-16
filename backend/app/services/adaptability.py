"""v0.11 完本模式：短剧可改编度审读、短剧分镜档单章自查、同质化自查。

- 可改编度（Job，kind = adaptability）：规则层统计人设标签、冲突密度、反转速度、场景数与可拍性、对白占比、
  每章可切几集，再由模型审读打 0–10 分并给改进建议；两层分数取平均。
- 短剧分镜档单章自查（同步，不调模型）：前 100 字是否切动作/强对白、心理独白与景物注水占比、章末是否停在危机/揭露前一刻。
- 同质化自查：拿书名、简介、金手指、开局与最新榜单快照前列书比对（同步、纯规则）；要模型给差异化建议时走 Job（kind = homogeneity）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.lint.humanlint import count_words, dialogue_ratio, paragraphs
from app.llm.gateway import get_gateway
from app.models.tables import Chapter, Idea, RankItem
from app.radar.service import board_of, latest_snapshot, snapshot_items
from app.services import common
from app.services.book_check import CLIFF_RX, _clip
from app.services.imitate import CHEAT_WORDS, CONFLICT_WORDS, TITLE_OVERLAP_N, overlap_segments
from app.skills.loader import render, system_prompt

KIND = "adaptability"
HOMO_KIND = "homogeneity"

# ================================================================== 短剧分镜档：单章自查

OPENING_CHARS = 100
ACTION_WORDS = ("推开", "踹开", "撞开", "抬手", "一脚", "一巴掌", "耳光", "拔出", "拔刀", "拔剑", "砸", "摔", "跪", "冲", "踹", "抓住",
                "掐住", "拍", "按住", "扯", "掀", "甩", "扑", "挡", "攥", "揪", "扔", "泼", "指着", "撕", "捏碎", "抽出", "刺", "劈")
INNER_WORDS = ("心想", "暗道", "心中", "心里", "内心", "暗自", "思索", "回想", "想起", "心底", "脑海", "寻思", "忍不住想", "他想", "她想")
SCENERY_WORDS = ("天空", "阳光", "月光", "夕阳", "晚霞", "微风", "风吹", "云层", "白云", "乌云", "山峦", "群山", "树叶", "树梢", "雨丝",
                 "细雨", "大雨", "雪花", "夜色", "星空", "星光", "湖面", "河面", "远处", "天边", "落叶", "雾气", "晨光", "暮色", "炊烟")
MONOLOGUE_PARA_CHARS = 60
SCENERY_PARA_CHARS = 40
SCENE_SEP = re.compile(r"^\s*(?:\*\s*){3,}$|^\s*[◆◇☆★#＊~～—-]{3,}\s*$")
SCENE_SHIFT = re.compile(r"^(?:与此同时|另一边|另一头|此时此刻|片刻后|半个时辰后|一个时辰后|半小时后|第二天|次日|翌日|当晚|深夜|"
                         r"清晨|傍晚|回到|来到|走进|赶到|另一处)")
REVERSAL_RX = re.compile(r"没想到|竟然|居然|原来是|原来|谁知|谁料|不料|却是|反而|真相|真实身份|身份是|下一秒|反转|翻盘|露出底牌|摊牌")
EXTREME_WORDS = ("极", "最", "唯一", "天才", "废物", "疯", "狠", "毒", "冷血", "护短", "偏执", "腹黑", "病娇", "毒舌", "睚眦必报",
                 "千年", "首富", "战神", "女帝", "杀伐", "嚣张", "隐忍", "绝不", "宁死")
_QUOTE_RX = re.compile(r"[“「\"]")


def _no_dialogue(p: str) -> bool:
    return not _QUOTE_RX.search(p)


def duanju_check(text: str, names: list[str] | None = None) -> dict[str, Any]:
    """短剧分镜档单章自查（纯规则）。返回指标 + issues[{type, severity, evidence, suggestion}]。"""
    names = [n for n in (names or []) if n]
    paras = paragraphs(text)
    words = max(count_words(text), 1)
    opening = text.strip()[:OPENING_CHARS]
    has_quote = bool(_QUOTE_RX.search(opening))
    has_action = any(w in opening for w in ACTION_WORDS)
    opening_ok = has_quote or has_action
    mono_words = sum(count_words(p) for p in paras
                     if _no_dialogue(p) and count_words(p) >= MONOLOGUE_PARA_CHARS and any(w in p for w in INNER_WORDS))
    scen_paras = [p for p in paras if _no_dialogue(p) and count_words(p) >= SCENERY_PARA_CHARS
                  and sum(1 for w in SCENERY_WORDS if w in p) >= 2 and not any(n in p for n in names)]
    scen_words = sum(count_words(p) for p in scen_paras)
    tail = text.strip()[-200:]
    last = tail.rstrip()
    cliff = bool(CLIFF_RX.search(tail[-120:])) or last.endswith(("？", "?", "——", "……", "！”", "?”", "？”", "…”"))
    mono_ratio, scen_ratio = mono_words / words, scen_words / words
    issues: list[dict[str, Any]] = []
    if not opening_ok:
        issues.append({"type": "opening_slow", "severity": "mid", "evidence": _clip(opening, 60),
                       "suggestion": "前 100 字直接切一个正在发生的动作或一句强对白，天气、来历、心理放到后面"})
    if mono_ratio > 0.12:
        issues.append({"type": "monologue", "severity": "mid" if mono_ratio > 0.2 else "low", "evidence": f"心理独白段约占 {mono_ratio:.0%}",
                       "suggestion": "大段心理独白压成一两句，立刻转成台词、动作或微表情"})
    if scen_ratio > 0.08:
        issues.append({"type": "scenery", "severity": "mid" if scen_ratio > 0.15 else "low",
                       "evidence": _clip(scen_paras[0], 50) if scen_paras else "", "suggestion": "景物描写只留一句布景提示，其余删掉"})
    if not cliff:
        issues.append({"type": "ending_flat", "severity": "mid", "evidence": _clip(last[-50:], 50),
                       "suggestion": "章末停在危机落下或真相揭开的前一刻：最后一句是动作或半句台词，不写结果"})
    return {"opening_ok": opening_ok, "opening_has_dialogue": has_quote, "opening_has_action": has_action,
            "monologue_ratio": round(mono_ratio, 3), "scenery_ratio": round(scen_ratio, 3), "ending_cliff": cliff,
            "dialogue_ratio": round(dialogue_ratio(text), 3), "issues": issues}


# ================================================================== 可改编度：规则层指标

def _count_any(text: str, words: tuple[str, ...]) -> int:
    return sum(text.count(w) for w in words)


def scene_count(text: str) -> int:
    paras = [p for p in text.split("\n") if p.strip()]
    seps = sum(1 for p in paras if SCENE_SEP.match(p))
    shifts = sum(1 for p in paras if SCENE_SHIFT.match(p.strip()))
    return max(1, min(8, 1 + seps + shifts))


def episodes_estimate(words: int, scenes: int, conflict_per_k: float) -> float:
    """每章可切几集（竖屏短剧每集 1–2 分钟，约 500–800 字原文的戏量）：按字数与场景数折中，冲突稀的打折。"""
    by_words = words / 700
    est = (by_words + scenes) / 2
    if conflict_per_k < 1:
        est *= 0.7
    return round(max(0.5, min(4.0, est)), 1)


def chapter_metrics(c: dict[str, Any], names: list[str]) -> dict[str, Any]:
    text = c["content"]
    words = max(count_words(text), 1)
    per_k = 1000.0 / words
    conflict = _count_any(text, CONFLICT_WORDS) * per_k
    reversal = len(REVERSAL_RX.findall(text)) * per_k
    scenes = scene_count(text)
    dj = duanju_check(text, names)
    return {"chapter": c["number"], "chapter_id": c["id"], "words": words, "dialogue_ratio": dj["dialogue_ratio"],
            "conflict_per_k": round(conflict, 2), "reversal_per_k": round(reversal, 2), "scenes": scenes,
            "episodes": episodes_estimate(words, scenes, conflict), "opening_ok": dj["opening_ok"],
            "ending_cliff": dj["ending_cliff"], "monologue_ratio": dj["monologue_ratio"], "scenery_ratio": dj["scenery_ratio"]}


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cl(v: float) -> float:
    return round(max(0.0, min(10.0, v)), 1)


def persona_rule_score(cards: list[Any]) -> tuple[float, list[str]]:
    """人设极致度（规则粗估）：人物卡摘要/灵魂五维里有没有极端标签词。"""
    tags: list[str] = []
    for c in cards:
        if c.type != "character":
            continue
        blob = (c.summary or "") + json.dumps(c.soul or {}, ensure_ascii=False) + json.dumps(c.data or {}, ensure_ascii=False)
        hit = [w for w in EXTREME_WORDS if w in blob]
        if hit:
            tags.append(f"{c.name}：{'、'.join(hit[:3])}")
    return _cl(3 + 2 * len(tags)), tags


def rule_scores(ms: list[dict[str, Any]], persona: float) -> dict[str, float]:
    conflict = _avg([m["conflict_per_k"] for m in ms])
    reversal = _avg([m["reversal_per_k"] for m in ms])
    dr = _avg([m["dialogue_ratio"] for m in ms])
    mono = _avg([m["monologue_ratio"] for m in ms])
    scen = _avg([m["scenery_ratio"] for m in ms])
    scenes = _avg([m["scenes"] for m in ms])
    eps = _avg([m["episodes"] for m in ms])
    shoot = 10 - mono * 20 - scen * 25 - max(0.0, scenes - 5) - (1 if scenes < 1.5 else 0)
    return {"persona": persona, "conflict": _cl(conflict * 2.5), "reversal": _cl(reversal * 3.3), "shootability": _cl(shoot),
            "dialogue": _cl(dr / 0.5 * 10), "episodes": _cl(eps * 3.3)}


DIMS = ("persona", "conflict", "reversal", "shootability", "dialogue", "episodes")
DIM_LABEL = {"persona": "人设极致度", "conflict": "冲突密度", "reversal": "反转速度", "shootability": "场景数与可拍性",
             "dialogue": "对白占比", "episodes": "每章可切集数"}
DIM_WEIGHT = {"persona": 0.2, "conflict": 0.2, "reversal": 0.15, "shootability": 0.15, "dialogue": 0.15, "episodes": 0.15}


def rule_suggestions(ms: list[dict[str, Any]], scores: dict[str, float]) -> list[str]:
    out: list[str] = []
    slow = [m["chapter"] for m in ms if not m["opening_ok"]]
    flat = [m["chapter"] for m in ms if not m["ending_cliff"]]
    if slow:
        out.append(f"第{'、'.join(map(str, slow[:8]))}章开场 100 字没有动作或强对白，改成直接切进冲突")
    if flat:
        out.append(f"第{'、'.join(map(str, flat[:8]))}章章末没有停在危机/揭露前一刻，砍掉结果和反应，停在半句台词或动作上")
    if scores["dialogue"] < 5:
        out.append("对白偏少：把叙述里的信息改成角色之间的交锋台词")
    if scores["reversal"] < 5:
        out.append("反转偏慢：每 500–800 字安排一次身份揭露、立场翻转或局势逆转")
    if scores["shootability"] < 6:
        out.append("心理独白/景物描写偏多：压成一两句，换成看得见的动作和微表情")
    if scores["persona"] < 6:
        out.append("人设不够极致：给主角、反派各定一个一眼记住的极端标签，每章用一个具体行为强化")
    return out


def _range(chs: list[dict[str, Any]], start: int | None, end: int | None) -> list[dict[str, Any]]:
    return [c for c in chs if (start is None or c["number"] >= start) and (end is None or c["number"] <= end)]


def _load_chapters(s: Session, book_id: int) -> list[dict[str, Any]]:
    rows = s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number, Chapter.id))
    return [{"id": c.id, "number": c.number, "title": c.title or "", "content": c.content or ""}
            for c in rows if (c.content or "").strip()]


EXCERPT_BUDGET = 8000


def _excerpts(chs: list[dict[str, Any]]) -> str:
    per = 350
    k = max(1, EXCERPT_BUDGET // per)
    pick = chs if len(chs) <= k else [chs[round(i * (len(chs) - 1) / (k - 1))] for i in range(k)]
    lines = []
    for c in pick:
        body = c["content"].strip()
        lines.append(f"第{c['number']}章 开头：{_clip(body[:200], 200)}\n  结尾：{_clip(body[-150:], 150)}")
    return "\n".join(dict.fromkeys(lines))


def run(book_id: int, start: int | None = None, end: int | None = None, ctx: JobContext | None = None,
        use_llm: bool = True) -> dict[str, Any]:
    """可改编度审读（Job 工作函数）。"""
    if start is not None and end is not None and start > end:
        raise ValueError("起始章号不能大于结束章号")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        chs = _range(_load_chapters(s, book_id), start, end)
        if not chs:
            raise ValueError("指定范围内没有写好的章节")
        cards = common.cards(s, book_id)
        names = [c.name for c in cards]
        persona, persona_tags = persona_rule_score(cards)
        book_ctx = common.book_context(s, book)
        char_lines = [f"{c.name}：{_clip(c.summary, 80)}" for c in cards if c.type == "character"][:12]
    if ctx:
        ctx.progress(20, "统计冲突、反转、场景与对白")
    ms = [chapter_metrics(c, names) for c in chs]
    rs = rule_scores(ms, persona)
    llm: dict[str, Any] = {}
    if use_llm:
        if ctx:
            ctx.progress(50, "审读可改编度")
        metrics_text = "\n".join(
            f"第{m['chapter']}章：{m['words']}字，对白{m['dialogue_ratio']:.0%}，冲突{m['conflict_per_k']}/千字，反转{m['reversal_per_k']}/千字，"
            f"场景{m['scenes']}，开场{'切入' if m['opening_ok'] else '慢'}，章末{'卡点' if m['ending_cliff'] else '平'}" for m in ms[:60])
        raw = get_gateway().chat_json(
            "adaptability", system_prompt("adaptability"),
            render("adaptability", start=chs[0]["number"], end=chs[-1]["number"], book_context=book_ctx,
                   characters="\n".join(char_lines) or "（无人物卡）", metrics=metrics_text, excerpts=_excerpts(chs)),
            meta={"rule_scores": rs, "chapters": [m["chapter"] for m in ms], "episodes": [m["episodes"] for m in ms]},
            role="reviewer", temperature=0.3)
        llm = raw if isinstance(raw, dict) else {}
    lsc = llm.get("scores") if isinstance(llm.get("scores"), dict) else {}
    dims: dict[str, Any] = {}
    for d in DIMS:
        item = lsc.get(d) if isinstance(lsc.get(d), dict) else {}
        try:
            lv: float | None = _cl(float(item.get("score"))) if item.get("score") is not None else None
        except (TypeError, ValueError):
            lv = None
        final = _cl((rs[d] + lv) / 2) if lv is not None else rs[d]
        dims[d] = {"label": DIM_LABEL[d], "score": final, "rule_score": rs[d], "llm_score": lv, "comment": str(item.get("comment") or "")}
    eps_avg = round(_avg([m["episodes"] for m in ms]), 1)
    try:
        llm_eps = float((lsc.get("episodes") or {}).get("per_chapter") or 0) if isinstance(lsc.get("episodes"), dict) else 0.0
    except (TypeError, ValueError):
        llm_eps = 0.0
    per_chapter = round((eps_avg + llm_eps) / 2, 1) if llm_eps > 0 else eps_avg
    overall = _cl(sum(dims[d]["score"] * DIM_WEIGHT[d] for d in DIMS))
    sugg = [str(x) for x in (llm.get("suggestions") or []) if str(x).strip()][:6]
    sugg += [x for x in rule_suggestions(ms, {d: dims[d]["score"] for d in DIMS}) if x not in sugg]
    notes = []
    for n in llm.get("chapter_notes") or []:
        if isinstance(n, dict) and n.get("chapter") in [m["chapter"] for m in ms]:
            notes.append({"chapter": int(n["chapter"]), "episodes": n.get("episodes"), "note": str(n.get("note") or "")})
    return {
        "book_id": book_id, "kind": KIND, "range": {"start": chs[0]["number"], "end": chs[-1]["number"], "chapters": len(chs)},
        "score": overall, "dimensions": dims, "episodes_per_chapter": per_chapter,
        "episodes_total": round(sum(m["episodes"] for m in ms), 1), "persona_tags": persona_tags,
        "suggestions": sugg[:10], "chapter_notes": notes[:10], "chapters": ms, "llm_used": use_llm,
    }


# ================================================================== 同质化自查

TROPE_WORDS = tuple(dict.fromkeys((*CHEAT_WORDS, "重生", "穿越", "退婚", "赘婿", "战神", "神医", "末世", "规则", "怪谈", "无敌", "修仙",
                                   "校花", "总裁", "闪婚", "萌宝", "宫斗", "宅斗", "种田", "直播", "鉴宝", "弹幕", "年代", "首富", "逆袭",
                                   "废柴", "词条", "御兽", "高武", "灵气复苏", "诡异", "无限流", "抽卡", "模拟器", "反派", "女帝", "龙王",
                                   "神豪", "离婚", "替身", "真假千金", "团宠", "末日", "囤货", "全民", "转职", "废物", "下山", "师父",
                                   "长生", "仙帝", "剑仙", "大佬", "马甲", "读心", "心声")))
HOMO_TOP_N = 50
SIMILAR_MAX = 8
SIMILAR_MIN = 15


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _tropes(text: str) -> list[str]:
    return [w for w in TROPE_WORDS if w in (text or "")]


def mine_from_book(s: Session, book_id: int) -> dict[str, Any]:
    book = common.get_book(s, book_id)
    cheats = [f"{c.name}：{c.summary}" for c in common.cards(s, book_id) if c.type in ("cheat", "power")]
    ch1 = s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number)).first()
    opening = (ch1.content or "")[:300] if ch1 else ""
    return {"type": "book", "id": book_id, "title": book.title, "genre": book.genre, "gender": book.gender,
            "blurb": "；".join(x for x in (book.tagline, book.premise) if x), "cheat": "；".join(cheats)[:400], "opening": opening}


def mine_from_idea(s: Session, idea_id: int) -> dict[str, Any]:
    idea = s.get(Idea, idea_id)
    if idea is None:
        raise common.NotFound("灵感不存在")
    return {"type": "idea", "id": idea_id, "title": idea.title, "genre": idea.genre, "gender": idea.gender,
            "blurb": idea.logline, "cheat": "；".join(idea.selling_points or [])[:400], "opening": idea.hook or "",
            "book_id": idea.book_id}


def _compare(mine: dict[str, Any], it: RankItem) -> dict[str, Any]:
    overlaps: list[str] = []
    score = 0.0
    t_segs = overlap_segments(mine["title"], it.title, TITLE_OVERLAP_N)
    if t_segs:
        score += 30
        overlaps.append(f"书名重合：「{'」「'.join(t_segs[:3])}」")
    tj = _jaccard(_bigrams(mine["title"]), _bigrams(it.title))
    score += tj * 20
    my_text = " ".join((mine["blurb"], mine["cheat"], mine["opening"]))
    aj = _jaccard(_bigrams(my_text), _bigrams(it.abstract))
    score += min(30.0, aj * 200)
    if aj >= 0.08:
        overlaps.append(f"简介用词相近（{aj:.0%}）")
    mine_tropes = set(_tropes(f"{mine['title']} {my_text}"))
    theirs = set(_tropes(f"{it.title} {it.abstract} {' '.join(it.tags or [])}")) | {t for t in (it.tags or []) if t in mine_tropes}
    shared = sorted(mine_tropes & theirs, key=lambda w: TROPE_WORDS.index(w) if w in TROPE_WORDS else 999)
    if shared:
        score += min(30, 8 * len(shared))
        overlaps.append(f"共同套路：{'、'.join(shared[:6])}")
    cheat_shared = [w for w in shared if w in CHEAT_WORDS]
    if cheat_shared:
        overlaps.append(f"金手指同类：{'、'.join(cheat_shared[:3])}")
    if mine.get("genre") and it.category and (mine["genre"] in it.category or it.category in mine["genre"]):
        score += 10
        overlaps.append(f"同题材：{it.category}")
    return {"rank_item_id": it.id, "book_id_ext": it.book_id_ext, "title": it.title, "author": it.author, "category": it.category,
            "rank": it.rank, "board": board_of(it), "gender": it.gender, "read_count": it.read_count,
            "score": round(min(100.0, score), 1), "overlaps": overlaps, "shared_tropes": shared, "title_overlap": t_segs[:3],
            "abstract": _clip(it.abstract, 120)}


def homogeneity_rules(s: Session, mine: dict[str, Any], top_n: int = HOMO_TOP_N) -> dict[str, Any]:
    snap = latest_snapshot(s)
    base = {"target": {"type": mine["type"], "id": mine["id"], "title": mine["title"]}, "kind": HOMO_KIND}
    if snap is None:
        return {**base, "snapshot": None, "similar": [], "max_score": 0, "level": "unknown",
                "suggestions": ["还没有榜单快照：先在风向标里刷新一次榜单，再来自查"], "llm": None}
    items = [it for it in snapshot_items(s, snap.id or 0) if (it.rank or 0) <= top_n]
    rows = [_compare(mine, it) for it in items]
    rows = [r for r in rows if r["score"] >= SIMILAR_MIN]
    rows.sort(key=lambda r: (-r["score"], r["rank"]))
    rows = rows[:SIMILAR_MAX]
    mx = rows[0]["score"] if rows else 0
    level = "high" if mx >= 60 else "mid" if mx >= 35 else "low"
    sugg: list[str] = []
    from collections import Counter

    trope_cnt = Counter(t for r in rows for t in r["shared_tropes"])
    for t, k in trope_cnt.most_common(3):
        if k >= 2:
            sugg.append(f"「{t}」在榜单前列 {k} 本相似书里都有：保留也行，但要给它加一个别人没有的限制、代价或使用场景")
    if any(r["title_overlap"] for r in rows):
        sugg.append("书名和榜单书有连续重合的字：换掉重合部分，突出本书独有的身份或金手指")
    if level == "low" and not sugg:
        sugg.append("和当前榜单前列重合不多，差异化已经不错；注意开局三章把独有卖点亮出来")
    return {**base, "snapshot": {"id": snap.id, "taken_at": snap.taken_at.isoformat() if snap.taken_at else None,
                                 "items_compared": len(items), "top_n": top_n},
            "similar": rows, "max_score": mx, "level": level, "suggestions": sugg, "llm": None}


def homogeneity_job(target: str, tid: int, top_n: int, ctx: JobContext | None = None) -> dict[str, Any]:
    """同质化自查 + 模型差异化建议（Job 工作函数）。"""
    with session_scope() as s:
        mine = mine_from_book(s, tid) if target == "book" else mine_from_idea(s, tid)
        rep = homogeneity_rules(s, mine, top_n)
    if not rep["similar"]:
        return rep
    if ctx:
        ctx.progress(50, "生成差异化建议")
    mine_text = (f"书名：{mine['title']}\n题材：{mine['genre']}\n简介：{mine['blurb']}\n金手指/卖点：{mine['cheat']}\n"
                 f"开局：{_clip(mine['opening'], 300)}")
    sim_text = "\n".join(f"《{r['title']}》（{r['category']}，榜{r['rank']}，相似 {r['score']}）：{'；'.join(r['overlaps'])}｜简介：{r['abstract']}"
                         for r in rep["similar"])
    raw = get_gateway().chat_json("homogeneity", system_prompt("homogeneity"), render("homogeneity", mine=mine_text, similar=sim_text),
                                  meta={"titles": [r["title"] for r in rep["similar"]], "tropes": [t for r in rep["similar"] for t in r["shared_tropes"]]},
                                  role="planner", temperature=0.5)
    llm = raw if isinstance(raw, dict) else {}
    notes = {str(n.get("title") or "").strip("《》"): str(n.get("overlap") or "") for n in llm.get("notes") or [] if isinstance(n, dict)}
    for r in rep["similar"]:
        r["llm_note"] = notes.get(r["title"], "")
    rep["llm"] = {"overall": str(llm.get("overall") or ""),
                  "suggestions": [str(x) for x in llm.get("suggestions") or [] if str(x).strip()][:6]}
    return rep


# ================================================================== mock（只在没有配置渠道时生效，确定性输出）

def _mock_adapt(meta: dict[str, Any]) -> str:
    rs = meta.get("rule_scores") or {}
    eps = [float(x) for x in meta.get("episodes") or [] if x] or [1.0]
    scores = {d: {"score": max(0, min(10, round(float(rs.get(d, 5))))), "comment": f"{DIM_LABEL[d]}按程序统计给分（演示）"} for d in DIMS}
    scores["episodes"]["per_chapter"] = round(sum(eps) / len(eps), 1)
    chapters = [int(x) for x in meta.get("chapters") or []][:3]
    return json.dumps({"scores": scores, "suggestions": ["开场三句内让冲突落到主角身上（演示）", "每章至少一次身份或立场反转（演示）"],
                       "chapter_notes": [{"chapter": c, "episodes": eps[0], "note": "可切一集，章末卡点可做集尾（演示）"} for c in chapters]},
                      ensure_ascii=False)


def _mock_homo(meta: dict[str, Any]) -> str:
    titles = [str(x) for x in meta.get("titles") or []]
    tropes = list(dict.fromkeys(str(x) for x in meta.get("tropes") or []))
    return json.dumps({"overall": f"与榜单前列 {len(titles)} 本有重合（演示）",
                       "notes": [{"title": t, "overlap": "套路和开局处境相近（演示）"} for t in titles],
                       "suggestions": [f"「{t}」换成带代价的变体，或换一种触发方式（演示）" for t in tropes[:3]] or ["开局处境换成更具体的职业困境（演示）"]},
                      ensure_ascii=False)


def _register_mock() -> None:
    from app.llm import mock

    mock.HANDLERS.setdefault("adaptability", _mock_adapt)
    mock.HANDLERS.setdefault("homogeneity", _mock_homo)


_register_mock()
