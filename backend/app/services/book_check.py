"""v0.11 完本模式·整书体检（内容质量体检）。

只看内容质量，不做任何平台发文频率、发布合规、AI 申报相关的检查；15 万 / 30 万字只作为字数参考档位展示。

分两层：
- 规则层（不调模型）：总字数与参考档位、单章过短、重复/近似章（8 字 n-gram 抽样重合率）、水化（复用现有 lint：
  套话、短段瀑布、概述式叙述、重复强化词/陈词比喻，加全书高频重复短语）、数值一致性汇总（复用 v0.9.4 数值 lint）、
  伏笔未回收（foreshadows）、章号/标题断档、末章是否收束。
- 模型层：每 10 章一组的逐章摘要，按字数预算拼段、带着「当前状态」滚动送模型查连续性
  （人物状态、战力/境界、势力、时间线、主线），最后一次调用判断结局是否仓促/烂尾、主线是否跑偏。

结果存在 Job.result（kind = book_check，按 book_id 查历史），不新增表。
"""

from __future__ import annotations

import json
import re
import zlib
from collections import Counter
from typing import Any

from sqlmodel import Session, select

from app.config import get_settings
from app.db import session_scope
from app.jobs.manager import JobContext
from app.lint.humanlint import _CJK_RUN, count_words, lint_chapter
from app.lint.numeric_zh import cn_to_num
from app.lint.platform import get_profile
from app.llm.gateway import get_gateway
from app.models.tables import Book, Chapter, Foreshadow, Job
from app.services import common
from app.services.imitate import _norm, overlap_segments
from app.services.writing import book_platform, numeric_ledger
from app.skills.loader import render, system_prompt

KIND = "book_check"

# ---------- 规则层阈值 ----------
WORD_TIERS = (150_000, 300_000)        # 字数参考档位（只做展示参考）
SHORT_CHAPTER_WORDS = 1000             # 单章少于这个字数算过短
DUP_GRAM_N = 8                         # 重复章：连续 8 字（去标点）算重合，与 imitate 的查重口径一致
DUP_SAMPLE_MOD = 4                     # 抽样：只取 hash % 4 == 0 的 gram，全书比对降到 1/4 开销
DUP_HIGH = 0.5                         # 重合率 ≥ 50% 算重复章
DUP_MID = 0.2                          # 重合率 ≥ 20% 算近似章
DUP_PASSAGE_MIN = 50                   # 重合率不高但有 ≥ 50 字一字不差的段落，也提示
DUP_COMMON_RATIO = 0.3                 # 出现在 30% 以上章节里的 gram 视为惯用语，不参与重复章比对
DUP_COMMON_MAX = 20
PHRASE_N = 6                           # 全书重复句式：6 字短语
PHRASE_MIN_CHAPTERS = 5
PHRASE_CHAPTER_RATIO = 0.4             # 出现在 ≥ 40% 的章节里
PHRASE_REPORT_MAX = 10

# ---------- 模型层预算 ----------
GROUP_SIZE = 10                        # 每 10 章一组
SUMMARY_CHARS = 120                    # 每章摘要截断
SEGMENT_CHARS = 6000                   # 每次调用的摘要字数预算
MAX_SEGMENTS = 24                      # 超过就进一步压缩每章摘要
STATE_CHARS = 1200
TAIL_CHARS = 1500

MAX_ISSUES = 300
SEVERITY_ORDER = {"high": 0, "mid": 1, "low": 2}
PENALTY = {"high": 10, "mid": 4, "low": 1}
TYPE_PENALTY_CAP = 20                  # 同一类问题最多扣 20 分，避免长书被同一类小问题刷到 0 分

TYPE_LABEL = {
    "short_chapter": "单章过短",
    "empty_chapter": "空章",
    "duplicate_chapter": "重复章",
    "similar_chapter": "近似章",
    "repeated_passage": "大段重复",
    "watering": "水化",
    "repetitive_phrases": "全书重复句式",
    "numeric": "数值不一致",
    "foreshadow_open": "伏笔未回收",
    "foreshadow_unplanted": "计划伏笔未埋",
    "number_gap": "章号断档",
    "number_duplicate": "章号重复",
    "title_missing": "缺标题",
    "title_mismatch": "标题章号不符",
    "title_duplicate": "标题重复",
    "ending_open": "末章未收束",
    "ending_unresolved": "末章收束不足",
    "ending_rushed": "结局仓促",
    "mainline_drift": "主线跑偏",
    "character_state": "人物状态矛盾",
    "power_level": "战力/境界矛盾",
    "faction": "势力矛盾",
    "timeline": "时间线矛盾",
}
LLM_TYPES = ("character_state", "power_level", "faction", "timeline", "mainline_drift", "ending_rushed", "ending_open")

_TITLE_NUM = re.compile(r"第([0-9零〇一二两三四五六七八九十百千]+)章")
CLOSURE_WORDS = ("大结局", "全书完", "全文完", "完结", "终章", "尾声", "番外", "（完）", "(完)", "多年以后", "多年后", "许多年后",
                 "很多年后", "从此以后", "从此", "后来的后来", "一年后", "数年后", "十年后")
CLIFF_RX = re.compile(r"就在这时|就在此时|突然|忽然|下一刻|下一秒|猛地|竟然是|到底是谁|未完待续|下一章|下回|"
                      r"更大的(?:风暴|挑战|危机)|才刚刚开始|一切才刚开始|命运的齿轮")


# ================================================================== 小工具

def word_tier(total: int) -> dict[str, Any]:
    """字数参考档位（只做参考展示）。"""
    lo, hi = WORD_TIERS
    if total < lo:
        tier, label, nxt = "below_15w", "不足 15 万字", lo
    elif total < hi:
        tier, label, nxt = "15w_30w", "15 万–30 万字", hi
    else:
        tier, label, nxt = "above_30w", "30 万字以上", None
    return {"total_words": total, "tier": tier, "label": f"字数参考档位：{label}", "reference": list(WORD_TIERS),
            "to_next": (nxt - total) if nxt else 0}


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def _issue(type_: str, severity: str, chapter: int | None, evidence: str, suggestion: str, *, layer: str = "rule",
           chapter_id: int | None = None, related: list[int] | None = None, fix: dict[str, Any] | None = None) -> dict[str, Any]:
    sev = severity if severity in SEVERITY_ORDER else "mid"
    return {
        "type": type_, "type_label": TYPE_LABEL.get(type_, type_), "severity": sev, "layer": layer,
        "chapter": chapter, "chapter_id": chapter_id, "related_chapters": related or [],
        "evidence": _clip(evidence, 200), "suggestion": suggestion,
        "fixable": fix is not None, "fix": fix,
    }


def _fix(action: str, chapter_id: int | None, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """一键修的落点：都是已有接口（改标题同步；去 AI 腔/增厚/改写走已有 Job，改写只出草稿，作者对比后再采纳）。"""
    if not chapter_id:
        return None
    if action == "set_title":
        return {"action": action, "method": "PUT", "endpoint": f"/api/chapters/{chapter_id}", "body": body or {}}
    path = {"humanize": "humanize", "thicken": "thicken", "rewrite": "rewrite"}[action]
    return {"action": action, "method": "POST", "endpoint": f"/api/chapters/{chapter_id}/{path}", "body": body or {}}


def _rewrite_fix(chapter_id: int | None, suggestion: str) -> dict[str, Any] | None:
    ins = (suggestion or "").strip()[:1000]
    return _fix("rewrite", chapter_id, {"instruction": ins, "scope": "all"}) if ins else None


# ================================================================== 规则层

def numbering_issues(chs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """章号断档/重复、缺标题、标题里的章号与实际章号不符、标题重复。"""
    out: list[dict[str, Any]] = []
    nums = [c["number"] for c in chs]
    cnt = Counter(nums)
    for n, k in sorted(cnt.items()):
        if k > 1:
            ids = [c["id"] for c in chs if c["number"] == n]
            out.append(_issue("number_duplicate", "mid", n, f"第{n}章出现 {k} 次",
                              "保留一章，把其余的改成正确章号或删除多余草稿", chapter_id=ids[0], related=ids[1:]))
    if nums:
        have = set(nums)
        missing = [n for n in range(1, max(nums) + 1) if n not in have]
        # 连续缺号合并成一段
        runs: list[tuple[int, int]] = []
        for n in missing:
            if runs and runs[-1][1] == n - 1:
                runs[-1] = (runs[-1][0], n)
            else:
                runs.append((n, n))
        for a, b in runs[:20]:
            span = f"第{a}章" if a == b else f"第{a}–{b}章"
            out.append(_issue("number_gap", "high" if b - a >= 2 else "mid", a, f"{span}缺失",
                              f"补写{span}，或把后面章节的章号顺延补齐"))
    titles: dict[str, list[int]] = {}
    for c in chs:
        title = (c.get("title") or "").strip()
        if not title:
            out.append(_issue("title_missing", "low", c["number"], f"第{c['number']}章没有标题", "补一个能概括本章看点的标题",
                              chapter_id=c["id"], fix=_fix("set_title", c["id"], {"title": f"第{c['number']}章"})))
            continue
        m = _TITLE_NUM.search(title)
        if m:
            v = cn_to_num(m.group(1)) if not m.group(1).isdigit() else float(m.group(1))
            if v is not None and int(v) != c["number"]:
                fixed = title[:m.start()] + f"第{c['number']}章" + title[m.end():]
                out.append(_issue("title_mismatch", "mid", c["number"], f"标题「{title}」与章号 {c['number']} 不符",
                                  f"标题改成「{fixed}」", chapter_id=c["id"], fix=_fix("set_title", c["id"], {"title": fixed})))
        core = _TITLE_NUM.sub("", title).strip(" ：:　-—")
        if core:
            titles.setdefault(core, []).append(c["number"])
    for core, ns in titles.items():
        if len(ns) > 1:
            out.append(_issue("title_duplicate", "low", ns[1], f"标题「{core}」用在第{'、'.join(map(str, ns[:6]))}章",
                              "给重复标题的章节各换一个具体的看点标题", related=ns))
    return out


def short_chapter_issues(chs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in chs:
        if c["words"] < SHORT_CHAPTER_WORDS:
            out.append(_issue("short_chapter", "mid", c["number"], f"第{c['number']}章仅 {c['words']} 字：{_clip(c['content'], 40)}",
                              f"补到 {SHORT_CHAPTER_WORDS} 字以上：把概述的过程写成场面，或与相邻章合并",
                              chapter_id=c["id"], fix=_fix("thicken", c["id"])))
    return out


def _sampled_grams(text: str, n: int = DUP_GRAM_N) -> set[str]:
    t = _norm(text)
    # 用 crc32 而不是 hash()：跨进程稳定，同一本书两次体检结果一致
    return {g for g in (t[i:i + n] for i in range(len(t) - n + 1)) if zlib.crc32(g.encode("utf-8")) % DUP_SAMPLE_MOD == 0}


def duplicate_issues(chs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """重复/近似章：抽样 8-gram 倒排索引统计两两共有数，重合率 = 共有 / 较短一章的 gram 数。
    返回 (issues, pairs)；pairs 给统计用。"""
    grams = [_sampled_grams(c["content"]) for c in chs]
    index: dict[str, list[int]] = {}
    for i, gs in enumerate(grams):
        for g in gs:
            index.setdefault(g, []).append(i)
    # 出现在太多章里的 gram 是惯用语；同时封顶 20 章，避免长书两两配对数爆炸
    limit = max(3, min(DUP_COMMON_MAX, int(len(chs) * DUP_COMMON_RATIO)))
    shared: Counter[tuple[int, int]] = Counter()
    for owners in index.values():
        if len(owners) < 2 or len(owners) > limit:
            continue
        for a in range(len(owners)):
            for b in range(a + 1, len(owners)):
                shared[(owners[a], owners[b])] += 1
    issues: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for (i, j), k in shared.most_common():
        denom = max(1, min(len(grams[i]), len(grams[j])))
        ratio = k / denom
        if ratio < DUP_MID and k < 6:
            continue
        a, b = chs[i], chs[j]
        segs = overlap_segments(b["content"], a["content"])
        longest = max(segs, key=len) if segs else ""
        if ratio < DUP_MID and len(longest) < DUP_PASSAGE_MIN:
            continue
        pairs.append({"chapters": [a["number"], b["number"]], "ratio": round(ratio, 3), "longest": len(longest)})
        if ratio >= DUP_HIGH:
            typ, sev, sug = "duplicate_chapter", "high", f"第{b['number']}章与第{a['number']}章大面积重复，删掉重复部分重写，或确认是否误存了两份"
        elif ratio >= DUP_MID:
            typ, sev, sug = "similar_chapter", "mid", f"第{b['number']}章与第{a['number']}章情节/句子高度相似，换场景、换冲突或合并两章"
        else:
            typ, sev, sug = "repeated_passage", "low", f"第{b['number']}章有一段与第{a['number']}章一字不差，改写这一段"
        issues.append(_issue(typ, sev, b["number"], f"与第{a['number']}章重合约 {ratio:.0%}：{longest[:60]}", sug,
                             chapter_id=b["id"], related=[a["number"]],
                             fix=_rewrite_fix(b["id"], sug) if typ != "duplicate_chapter" else None))
        if len(issues) >= 40:
            break
    return issues, pairs


def repeated_phrase_issue(chs: list[dict[str, Any]], names: list[str]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """全书重复句式：同一个 6 字短语出现在 ≥ 40%（且 ≥ 5）章里，排除人名。"""
    if len(chs) < PHRASE_MIN_CHAPTERS:
        return None, []
    df: Counter[str] = Counter()
    for c in chs:
        seen: set[str] = set()
        for run in _CJK_RUN.findall(c["content"]):
            for i in range(len(run) - PHRASE_N + 1):
                seen.add(run[i:i + PHRASE_N])
        df.update(seen)
    need = max(PHRASE_MIN_CHAPTERS, int(len(chs) * PHRASE_CHAPTER_RATIO))
    cands = [(g, k) for g, k in df.items() if k >= need and not any(n and (n in g or g in n) for n in names)]
    cands.sort(key=lambda x: -x[1])
    kept: list[tuple[str, int]] = []
    for g, k in cands:
        if any(g[1:] in x or g[:-1] in x for x, _ in kept):  # 相互重叠的 6-gram 只留一个
            continue
        kept.append((g, k))
        if len(kept) >= PHRASE_REPORT_MAX:
            break
    if not kept:
        return None, []
    top = [{"text": g, "chapters": k} for g, k in kept]
    ev = "、".join(f"「{g}」×{k}章" for g, k in kept[:5])
    return _issue("repetitive_phrases", "mid" if len(kept) >= 3 else "low", None, ev,
                  "这些说法几乎每章都出现，读者会疲劳：逐章换成当场的具体动作或细节，同一说法全书控制在少数几次"), top


def chapter_lint(s: Session, book_id: int, chs: list[dict[str, Any]], names: list[str], cps: dict[str, list[str]],
                 platform: str, ctx: JobContext | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """逐章跑现有 lint（不带全书文本，避免 O(n²)）：水化信号 + 数值一致性。返回 (水化 issues, 数值 issues, 统计)。"""
    th0 = get_settings().lint
    prof = get_profile(platform)
    th = prof.thresholds(th0)
    cards = common.cards(s, book_id)
    water: list[dict[str, Any]] = []
    numeric: list[dict[str, Any]] = []
    ai_scores: list[float] = []
    dialogue: list[float] = []
    n = len(chs)
    for k, c in enumerate(chs):
        if ctx and n and k % 10 == 0:
            ctx.progress(5 + int(35 * k / n), f"规则体检：第 {c['number']} 章")
        text = c["content"]
        r = lint_chapter(text, th0, (), names, c["number"], catchphrases=cps, platform=platform,
                         ledger=numeric_ledger(s, book_id, c["number"], cards))
        ai_scores.append(r.ai_score)
        dialogue.append(r.dialogue_ratio)
        per_k = 1000.0 / max(c["words"], 1)
        banned_k = sum(int(h["count"]) for h in r.banned_hits) * per_k
        signals: list[str] = []
        weight = 0
        action = None
        if banned_k > th.banned_per_k_warn:
            signals.append(f"套话每千字 {banned_k:.1f} 处（{'、'.join(str(h['word']) for h in r.banned_hits[:3])}）")
            weight += 2 if banned_k > th.banned_per_k_warn * 2 else 1
            action = "humanize"
        cl = [d for d in r.cliche_similes] + [d for d in r.intensifiers if d.get("over")]
        if cl:
            signals.append("重复套词：" + "、".join(f"{d['word']}×{d['count']}" for d in cl[:3]))
            weight += 1
            action = action or "humanize"
        if r.waterfall_run > prof.waterfall_run_max:
            signals.append(f"连续 {r.waterfall_run} 段单句成段（短段瀑布）")
            weight += 2 if r.waterfall_run > prof.waterfall_run_max * 2 else 1
            action = action or "thicken"
        if r.summary_ratio > th.summary_ratio_max:
            signals.append(f"概述式叙述约 {r.summary_ratio:.0%}")
            weight += 1
            action = action or "thicken"
        if signals:
            sev = "mid" if weight >= 3 else "low"
            water.append(_issue("watering", sev, c["number"], "；".join(signals),
                                "删套话和重复套词，把概述的过程写成可见的场面，单句段按动作链并成完整段落",
                                chapter_id=c["id"], fix=_fix(action or "humanize", c["id"])))
        for it in r.numeric_issues:
            numeric.append(_issue("numeric", it.get("severity", "mid"), c["number"], str(it.get("quote") or ""),
                                  str(it.get("comment") or "统一成一个数"), chapter_id=c["id"],
                                  fix=_rewrite_fix(c["id"], f"只改数值不一致的地方：{it.get('comment')}")))
    stats = {
        "avg_ai_score": round(sum(ai_scores) / len(ai_scores), 1) if ai_scores else 0.0,
        "avg_dialogue_ratio": round(sum(dialogue) / len(dialogue), 3) if dialogue else 0.0,
        "watering_chapters": len(water),
        "numeric_conflicts": len(numeric),
    }
    return water, numeric, stats


def foreshadow_issues(s: Session, book_id: int, last_number: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = list(s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id).order_by(Foreshadow.planted_ch, Foreshadow.id)))
    out: list[dict[str, Any]] = []
    open_list: list[dict[str, Any]] = []
    for f in rows:
        if f.status in ("planted", "advancing"):
            open_list.append({"id": f.id, "desc": f.desc, "status": f.status, "planted_ch": f.planted_ch, "last_ch": f.last_ch,
                              "tier": f.tier, "plan_resolve_ch": f.plan_resolve_ch})
            overdue = f.plan_resolve_ch is not None and f.plan_resolve_ch <= last_number
            sev = "high" if (f.tier == "long" or overdue) else "mid"
            where = f"（计划第{f.plan_resolve_ch}章回收）" if f.plan_resolve_ch else ""
            out.append(_issue("foreshadow_open", sev, f.planted_ch or None, f"第{f.planted_ch}章埋下：{f.desc}{where}",
                              "在结局前补一场回收戏，让这条伏笔有交代；确实不要了就在伏笔面板标记为放弃"))
        elif f.status == "planned" and f.plan_plant_ch is not None and f.plan_plant_ch <= last_number:
            out.append(_issue("foreshadow_unplanted", "low", f.plan_plant_ch, f"计划第{f.plan_plant_ch}章埋下：{f.desc}",
                              "这条计划伏笔没有写进正文：补埋或在伏笔面板删除"))
    return out, open_list


def ending_check(last: dict[str, Any] | None, open_count: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """末章是否收束：收束标记（尾声/多年后/全书完…）与悬念标记（突然/下一刻/更大的风暴…）。"""
    if not last:
        return [], {"closed": False, "cliff": False}
    tail = last["content"][-300:]
    head = (last.get("title") or "") + last["content"][-800:]
    closed = any(w in head for w in CLOSURE_WORDS)
    stripped = tail.rstrip()
    cliff = bool(CLIFF_RX.search(tail[-200:])) or stripped.endswith(("？", "?", "……", "——"))
    info = {"closed": closed, "cliff": cliff, "last_chapter": last["number"], "tail": _clip(tail[-120:], 120)}
    out = []
    if cliff and not closed:
        out.append(_issue("ending_open", "high", last["number"], _clip(tail[-80:], 80),
                          "末章停在悬念上：把主线矛盾在这一章正面解决，最后写一段主角的落点（得到了什么、失去了什么、接下来怎么过）",
                          chapter_id=last["id"], fix=_rewrite_fix(last["id"], "把末章改成收束结局：主线矛盾正面解决，结尾写主角的落点，不留悬念式钩子")))
    elif not closed and open_count >= 3:
        out.append(_issue("ending_unresolved", "mid", last["number"], f"末章没有收束迹象，仍有 {open_count} 条伏笔未回收",
                          "末章前集中回收主要伏笔，末章交代主要人物的去向", chapter_id=last["id"]))
    return out, info


# ================================================================== 模型层

def _chapter_digest(c: dict[str, Any], n: int = SUMMARY_CHARS) -> str:
    summ = (c.get("summary") or "").strip()
    if not summ:
        body = c["content"].strip()
        summ = body[: n // 2] + " … " + body[-n // 2:] if len(body) > n else body
    return f"第{c['number']}章 {c.get('title') or ''}：{_clip(summ, n)}"


def build_segments(chs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每 10 章一组，再按字数预算把组拼成若干段；段太多时压缩每章摘要。"""
    per = SUMMARY_CHARS
    for _ in range(4):
        groups = [chs[i:i + GROUP_SIZE] for i in range(0, len(chs), GROUP_SIZE)]
        segs: list[dict[str, Any]] = []
        cur: list[str] = []
        cur_chs: list[dict[str, Any]] = []
        size = 0
        for g in groups:
            lines = [_chapter_digest(c, per) for c in g]
            block = "\n".join(lines)
            if cur and size + len(block) > SEGMENT_CHARS:
                segs.append({"start": cur_chs[0]["number"], "end": cur_chs[-1]["number"], "text": "\n".join(cur),
                             "numbers": [c["number"] for c in cur_chs]})
                cur, cur_chs, size = [], [], 0
            cur.append(f"【第{g[0]['number']}–{g[-1]['number']}章】\n{block}")
            cur_chs += g
            size += len(block)
        if cur:
            segs.append({"start": cur_chs[0]["number"], "end": cur_chs[-1]["number"], "text": "\n".join(cur),
                         "numbers": [c["number"] for c in cur_chs]})
        if len(segs) <= MAX_SEGMENTS or per <= 40:
            return segs
        per = max(40, per // 2)
    return segs


def _state_text(state: Any) -> str:
    if not state:
        return "（开篇，尚无）"
    return _clip(json.dumps(state, ensure_ascii=False), STATE_CHARS)


def _norm_llm_issues(raw: Any, by_num: dict[int, dict[str, Any]], allowed: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            continue
        typ = str(it.get("type") or "")
        if typ not in allowed:
            continue
        try:
            num = int(it.get("chapter") or 0)
        except (TypeError, ValueError):
            num = 0
        ch = by_num.get(num)
        ev = str(it.get("evidence") or "").strip()
        sug = str(it.get("suggestion") or "").strip()
        if not ev and not sug:
            continue
        iss = _issue(typ, str(it.get("severity") or "mid"), num if ch else None, ev, sug or "按问题描述修改",
                     layer="llm", chapter_id=ch["id"] if ch else None, fix=_rewrite_fix(ch["id"], sug) if ch and sug else None)
        # 证据能在正文或摘要里找到才算“有据”，前端可据此弱化显示
        iss["verified"] = bool(ch and ev and (_norm(ev)[:12] in _norm(ch["content"]) or _norm(ev)[:12] in _norm(ch.get("summary") or "")))
        out.append(iss)
    return out


def llm_layer(meta: dict[str, Any], chs: list[dict[str, Any]], ctx: JobContext | None = None) -> dict[str, Any]:
    gw = get_gateway()
    by_num = {c["number"]: c for c in chs}
    segs = build_segments(chs)
    state: Any = None
    issues: list[dict[str, Any]] = []
    sys_seg = system_prompt("book_check_segment")
    sent_chars = 0
    for k, seg in enumerate(segs):
        if ctx:
            ctx.progress(45 + int(40 * k / max(len(segs), 1)), f"连续性检查：第 {seg['start']}–{seg['end']} 章")
        user = render("book_check_segment", book_context=meta["book_context"], state=_state_text(state),
                      chapters=seg["text"], start=seg["start"], end=seg["end"])
        sent_chars += len(user)
        raw = gw.chat_json("book_check_segment", sys_seg, user, role="reviewer", temperature=0.2,
                           meta={"start": seg["start"], "end": seg["end"], "numbers": seg["numbers"], "names": meta["names"],
                                 "segment": k})
        if isinstance(raw, dict):
            issues += _norm_llm_issues(raw.get("issues"), by_num, LLM_TYPES[:5])
            if raw.get("state"):
                state = raw["state"]
    if ctx:
        ctx.progress(88, "判断结局与主线")
    last3 = chs[-3:]
    digest_lines = []
    for seg in segs:  # 每段只取首尾两章做全书骨架
        a, b = by_num.get(seg["start"]), by_num.get(seg["end"])
        digest_lines += [_chapter_digest(x, 60) for x in (a, b) if x]
    user = render("book_check_final", book_context=meta["book_context"], outline=meta["outline"] or "（无大纲）",
                  state=_state_text(state), digest=_clip("\n".join(dict.fromkeys(digest_lines)), 4000),
                  last_chapters="\n".join(_chapter_digest(c, 300) for c in last3),
                  tail=chs[-1]["content"][-TAIL_CHARS:] if chs else "", chapter_count=len(chs),
                  total_words=meta["total_words"], open_foreshadows="；".join(meta["open_foreshadows"][:10]) or "无")
    sent_chars += len(user)
    raw = gw.chat_json("book_check_final", system_prompt("book_check_final"), user, role="reviewer", temperature=0.2,
                       meta={"last": chs[-1]["number"] if chs else 0, "open_foreshadows": len(meta["open_foreshadows"]),
                             "tail": chs[-1]["content"][-200:] if chs else ""})
    ending: dict[str, Any] = {}
    mainline: dict[str, Any] = {}
    summary = ""
    if isinstance(raw, dict):
        issues += _norm_llm_issues(raw.get("issues"), by_num, LLM_TYPES)
        ending = _verdict_part(raw.get("ending"), "rushed")
        mainline = _verdict_part(raw.get("mainline"), "drift")
        summary = str(raw.get("summary") or "")
        last = chs[-1] if chs else None
        if ending.get("rushed") and not any(i["type"] in ("ending_rushed", "ending_open") for i in issues):
            issues.append(_issue("ending_rushed", "high", last["number"] if last else None, ending.get("evidence") or ending.get("comment", ""),
                                 ending.get("comment") or "结局仓促：高潮后补足收尾，交代主要人物去向", layer="llm",
                                 chapter_id=last["id"] if last else None))
        if mainline.get("drift") and not any(i["type"] == "mainline_drift" for i in issues):
            issues.append(_issue("mainline_drift", "mid", None, mainline.get("evidence") or mainline.get("comment", ""),
                                 mainline.get("comment") or "主线跑偏：删减偏离主线的支线，把主角目标拉回核心设定", layer="llm"))
    return {"issues": issues, "ending": ending, "mainline": mainline, "summary": summary, "state": state,
            "segments": len(segs), "sent_chars": sent_chars}


def _verdict_part(v: Any, flag: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        return {}
    try:
        score = max(0.0, min(10.0, float(v.get("score") or 0)))
    except (TypeError, ValueError):
        score = 0.0
    return {flag: bool(v.get(flag)), "score": score, "comment": str(v.get("comment") or ""), "evidence": str(v.get("evidence") or "")}


# ================================================================== 汇总

def score_and_verdict(issues: list[dict[str, Any]]) -> tuple[int, str]:
    by_type: Counter[str] = Counter()
    for i in issues:
        by_type[i["type"]] += PENALTY.get(i["severity"], 1)
    total = sum(min(TYPE_PENALTY_CAP, v) for v in by_type.values())
    score = max(0, 100 - total)
    highs = sum(1 for i in issues if i["severity"] == "high")
    if score < 60 or highs >= 5:
        return score, "not_ready"
    if highs >= 1 or score < 80:
        return score, "fix_first"
    return score, "ready"


VERDICT_LABEL = {"ready": "可以收尾", "fix_first": "先修再收尾", "not_ready": "还需大修"}


def _load(s: Session, book_id: int) -> tuple[Book, list[dict[str, Any]], list[dict[str, Any]]]:
    book = common.get_book(s, book_id)
    rows = list(s.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.number, Chapter.id)))
    chs, empty = [], []
    for c in rows:
        d = {"id": c.id, "number": c.number, "title": c.title or "", "content": c.content or "", "status": c.status,
             "summary": c.summary or "", "words": count_words(c.content or "")}
        (chs if (c.content or "").strip() else empty).append(d)
    return book, chs, empty


def _outline_text(s: Session, book_id: int) -> str:
    nodes = [n for n in common.outline_nodes(s, book_id) if n.level in ("book", "volume", "arc")]
    lines = [f"[{n.level}] {n.title}：{_clip(n.summary, 120)}" for n in nodes]
    return _clip("\n".join(lines), 3000)


def run(book_id: int, ctx: JobContext | None = None, use_llm: bool = True) -> dict[str, Any]:
    """整书体检主函数（Job 工作函数）。"""
    if ctx:
        ctx.progress(2, "读取章节")
    with session_scope() as s:
        book, chs, empty = _load(s, book_id)
        if not chs:
            raise ValueError("这本书还没有写好的章节，写完再来体检")
        cards = common.cards(s, book_id)
        names = [c.name for c in cards]
        cps = {c.name: common.voice_of(c)["catchphrases"] for c in cards if c.type == "character" and (c.data or {}).get("catchphrases")}
        platform = book_platform(s, book_id)
        issues: list[dict[str, Any]] = []
        issues += numbering_issues(chs + empty)
        for e in empty:
            issues.append(_issue("empty_chapter", "mid", e["number"], f"第{e['number']}章没有正文", "补写或删除这一章草稿",
                                 chapter_id=e["id"]))
        issues += short_chapter_issues(chs)
        water, numeric, lint_stats = chapter_lint(s, book_id, chs, names, cps, platform, ctx)
        if ctx:
            ctx.progress(40, "查重复章与重复句式")
        dup, pairs = duplicate_issues(chs)
        phrase, top_phrases = repeated_phrase_issue(chs, names)
        fs_issues, open_fs = foreshadow_issues(s, book_id, chs[-1]["number"])
        end_issues, ending_info = ending_check(chs[-1], len(open_fs))
        issues += dup + water + ([phrase] if phrase else []) + numeric + fs_issues + end_issues
        meta = {"book_context": common.book_context(s, book), "outline": _outline_text(s, book_id), "names": names[:20],
                "total_words": sum(c["words"] for c in chs), "open_foreshadows": [f"{f['desc']}（第{f['planted_ch']}章）" for f in open_fs]}
    llm: dict[str, Any] = {}
    if use_llm:
        llm = llm_layer(meta, chs, ctx)
        issues += llm["issues"]
    if ctx:
        ctx.progress(95, "汇总")
    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 3), i["chapter"] if i["chapter"] is not None else 10**9, i["type"]))
    total_issues = len(issues)
    issues = issues[:MAX_ISSUES]
    for k, i in enumerate(issues, 1):
        i["id"] = k
    score, verdict = score_and_verdict(issues)
    words = [c["words"] for c in chs]
    by_sev = Counter(i["severity"] for i in issues)
    by_type = Counter(i["type"] for i in issues)
    stats = {
        "chapters": len(chs), "empty_chapters": len(empty),
        "committed_chapters": sum(1 for c in chs if c["status"] == "committed"),
        "total_words": sum(words), "avg_words": round(sum(words) / len(words)) if words else 0,
        "min_words": min(words) if words else 0, "max_words": max(words) if words else 0,
        "short_chapters": sum(1 for w in words if w < SHORT_CHAPTER_WORDS),
        "word_tier": word_tier(sum(words)),
        "duplicate_pairs": pairs[:20], "top_phrases": top_phrases,
        "open_foreshadows": len(open_fs), "ending": ending_info,
        **lint_stats,
        "issues_total": total_issues, "issues_truncated": max(0, total_issues - len(issues)),
        "by_severity": {k: by_sev.get(k, 0) for k in ("high", "mid", "low")},
        "by_type": dict(by_type), "fixable": sum(1 for i in issues if i["fixable"]),
    }
    return {
        "book_id": book_id, "kind": KIND, "verdict": verdict, "verdict_label": VERDICT_LABEL[verdict], "score": score,
        "issues": issues, "stats": stats, "foreshadows_open": open_fs,
        "llm": {"used": use_llm, "ending": llm.get("ending") or None, "mainline": llm.get("mainline") or None,
                "summary": llm.get("summary", ""), "segments": llm.get("segments", 0), "sent_chars": llm.get("sent_chars", 0),
                "final_state": llm.get("state")} if use_llm else {"used": False},
        "platform": platform,
    }


# ================================================================== 历史（Job.result）

def _job_brief(j: Job) -> dict[str, Any]:
    r = j.result or {}
    st = r.get("stats") or {}
    return {"job_id": j.id, "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None, "verdict": r.get("verdict"),
            "score": r.get("score"), "by_severity": st.get("by_severity"), "chapters": st.get("chapters"),
            "total_words": st.get("total_words"), "llm_used": bool((r.get("llm") or {}).get("used"))}


def history(s: Session, book_id: int, kind: str = KIND, limit: int = 30) -> list[dict[str, Any]]:
    rows = s.exec(select(Job).where(Job.book_id == book_id, Job.kind == kind, Job.status == "succeeded")
                  .order_by(Job.id.desc()).limit(limit))  # type: ignore[union-attr]
    return [_job_brief(j) for j in rows]


def latest(s: Session, book_id: int, kind: str = KIND, job_id: int | None = None) -> dict[str, Any] | None:
    q = select(Job).where(Job.book_id == book_id, Job.kind == kind, Job.status == "succeeded")
    if job_id is not None:
        q = q.where(Job.id == job_id)
    j = s.exec(q.order_by(Job.id.desc())).first()  # type: ignore[union-attr]
    if j is None:
        return None
    return {**(j.result or {}), "job_id": j.id, "checked_at": j.updated_at.isoformat() if j.updated_at else None}


# ================================================================== mock（只在没有配置渠道时生效，确定性输出）

def _mock_segment(meta: dict[str, Any]) -> str:
    nums = [int(x) for x in meta.get("numbers") or []]
    names = [str(x) for x in meta.get("names") or [] if x] or ["主角"]
    issues = []
    if meta.get("segment") == 0 and len(nums) >= 3:
        issues.append({"type": "timeline", "severity": "low", "chapter": nums[len(nums) // 2],
                       "evidence": f"第{nums[len(nums) // 2]}章", "suggestion": "补一句时间推进，交代距上一章过了多久（演示）"})
    state = {"characters": [{"name": n, "status": "在场", "realm": ""} for n in names[:3]], "factions": [],
             "timeline": [f"读到第{meta.get('end')}章"], "mainline": "主线推进中（演示）"}
    return json.dumps({"issues": issues, "state": state}, ensure_ascii=False)


def _mock_final(meta: dict[str, Any]) -> str:
    tail = str(meta.get("tail") or "")
    closed = any(w in tail for w in CLOSURE_WORDS)
    rushed = not closed
    return json.dumps({
        "ending": {"rushed": rushed, "score": 8 if closed else 4, "comment": "结局收束完整（演示）" if closed else "末章没有交代主要人物去向，收得仓促（演示）",
                   "evidence": tail[-30:]},
        "mainline": {"drift": False, "score": 7, "comment": "主线基本贯穿全书（演示）", "evidence": ""},
        "issues": [], "summary": "整书连续性检查完成（演示）",
    }, ensure_ascii=False)


def _register_mock() -> None:
    from app.llm import mock

    mock.HANDLERS.setdefault("book_check_segment", _mock_segment)
    mock.HANDLERS.setdefault("book_check_final", _mock_final)


_register_mock()
