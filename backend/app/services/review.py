"""证据式审稿：LLM 只给带原句的 issues；程序校验 quote、补充确定性检查、计算分数。"""

from __future__ import annotations

import re
from typing import Any

from app.lint.humanlint import measure_errors
from app.llm.gateway import LLMGateway
from app.skills.loader import render, system_prompt

# v0.6：新增 continuity（连续性与物理逻辑：道具/服装/站位朝向/角度/身体前后矛盾）与 semantics（语义写反、搭配错误）
# v0.8.4：新增 retention（追读欲）——单独一次「番茄老读者」视角的审读，专门找让人想划走的地方
DIMENSIONS = ("hook", "pacing", "payoff", "character", "coherence", "continuity", "semantics", "retention")
SEVERITIES = ("high", "mid", "low")
PENALTY = {"high": 25, "mid": 10, "low": 3}
WEIGHTS = {"hook": 0.15, "pacing": 0.12, "payoff": 0.13, "character": 0.1, "coherence": 0.12, "continuity": 0.13,
           "semantics": 0.1, "retention": 0.15}
# 模型偶尔用别名，归一到正式维度
DIM_ALIASES = {"physics": "continuity", "logic": "continuity", "props": "continuity", "consistency": "continuity",
               "semantic": "semantics", "meaning": "semantics", "wording": "semantics",
               "reader": "retention", "drop": "retention", "engagement": "retention"}
PASS_OVERALL = 70
READER_PASS = 6  # 读者视角打分低于这个，章节不算通过

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub("", s).replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")


def quote_in_text(quote: str, content: str, min_len: int = 4) -> bool:
    """quote 必须（去空白后）原样出现在正文中，且不少于 min_len 字。"""
    q = _norm(quote).strip("\"'「」")
    if len(q) < min_len:
        return False
    return q in _norm(content)


def validate_issues(raw: Any, content: str, keep_src: bool = False) -> tuple[list[dict[str, Any]], int]:
    """返回（合法 issues, 被丢弃数）。keep_src=True 时每条带 _src（模型原始数组里的下标），用来对上补丁的 issue_ref。"""
    items = raw.get("issues") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return [], 0
    kept: list[dict[str, Any]] = []
    dropped = 0
    for src, it in enumerate(items):
        if not isinstance(it, dict):
            dropped += 1
            continue
        sev = str(it.get("severity", "low")).lower()
        dim = str(it.get("dimension", "coherence")).lower()
        dim = DIM_ALIASES.get(dim, dim)
        quote = str(it.get("quote", ""))
        if sev not in SEVERITIES:
            sev = "low"
        if dim not in DIMENSIONS:
            dim = "coherence"
        if not quote_in_text(quote, content):
            dropped += 1
            continue
        row: dict[str, Any] = {"severity": sev, "dimension": dim, "quote": quote.strip(), "comment": str(it.get("comment", ""))[:300]}
        if keep_src:
            row["_src"] = src
        kept.append(row)
    return kept, dropped


# ------------------------------------------------------------------ v0.9 审稿补丁

MAX_PATCHES = 8


def validate_patches(raw: Any, content: str, issues: list[dict[str, Any]], src_map: dict[int, int] | None = None
                     ) -> tuple[list[dict[str, Any]], int]:
    """补丁校验：original 必须是正文里逐字存在的连续片段（≥4 字），improved 与 original 不同。
    issue_ref：模型给的是它自己 issues 数组的下标，经 src_map 换成最终 review.issues 的下标；给的是引文时按 quote 对上。
    返回（合法补丁, 丢弃数）。每条补丁：{index, original, improved, reason, issue_ref, severity, applied}。"""
    items = raw.get("patches") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], 0
    out: list[dict[str, Any]] = []
    dropped = 0
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            dropped += 1
            continue
        orig = str(it.get("original") or it.get("original_snippet") or "")
        new = str(it.get("improved") if it.get("improved") is not None else it.get("improved_snippet") or "")
        orig_s = orig.strip()
        if len(orig_s) < 4 or orig_s not in content or orig_s == new.strip() or orig_s in seen:
            dropped += 1
            continue
        seen.add(orig_s)
        ref = it.get("issue_ref")
        final: int | None = None
        if isinstance(ref, bool):
            ref = None
        if isinstance(ref, (int, float)) or (isinstance(ref, str) and ref.strip().isdigit()):
            r = int(ref)
            final = src_map.get(r) if src_map is not None else (r if 0 <= r < len(issues) else None)
        elif isinstance(ref, str) and ref.strip():
            final = next((k for k, x in enumerate(issues) if _norm(ref) in _norm(x["quote"]) or _norm(x["quote"]) in _norm(ref)), None)
        if final is None:  # 没给或对不上：看 original 落在哪条问题的引文里
            final = next((k for k, x in enumerate(issues) if _norm(x["quote"]) and (_norm(x["quote"]) in _norm(orig_s) or _norm(orig_s) in _norm(x["quote"]))), None)
        out.append({"index": len(out), "original": orig_s, "improved": new.strip(), "reason": str(it.get("reason") or it.get("explanation") or "")[:200],
                    "issue_ref": final, "severity": issues[final]["severity"] if final is not None else None, "applied": False})
        if len(out) >= MAX_PATCHES:
            break
    return out, dropped


def apply_patches(content: str, patches: list[dict[str, Any]], indices: list[int] | None = None
                  ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """按原文逐字匹配、按顺序逐个应用（每个只替换第一次出现）。匹配不到 / 已应用过的跳过并记录原因。
    返回（新正文, applied[{index, original, improved}], skipped[{index, reason}]）。"""
    want = list(range(len(patches))) if indices is None else list(dict.fromkeys(int(i) for i in indices))
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i in want:
        if not 0 <= i < len(patches):
            skipped.append({"index": i, "reason": "没有这个补丁"})
            continue
        p = patches[i]
        if p.get("applied"):
            skipped.append({"index": i, "reason": "已经应用过"})
            continue
        if p.get("stale"):
            skipped.append({"index": i, "reason": "补丁来自上一轮审稿，已过期"})
            continue
        orig = str(p.get("original") or "")
        if not orig or orig not in content:
            skipped.append({"index": i, "reason": "原文里找不到这段（可能已被改过或被前一个补丁改动）"})
            continue
        content = content.replace(orig, str(p.get("improved") or ""), 1)
        applied.append({"index": i, "original": orig, "improved": str(p.get("improved") or "")})
    return content, applied, skipped


def compute_scores(issues: list[dict[str, str]]) -> dict[str, int]:
    scores = {d: 100 for d in DIMENSIONS}
    for it in issues:
        scores[it["dimension"]] = max(0, scores[it["dimension"]] - PENALTY.get(it["severity"], 3))
    overall = round(sum(scores[d] * w for d, w in WEIGHTS.items()))
    return {**scores, "overall": int(overall)}


def first_sentence(content: str) -> str:
    m = re.search(r"[^。！？\n]+[。！？]", content)
    return m.group(0).strip() if m else content[:30]


# 章末“总结 / 升华 / 空泛预告”收尾（oh-story-claudecode story-deslop 的总结句式，MIT，改写；maliangwriter 弱章尾示例）
ENDING_SUMMARY_RX = re.compile(
    r"(终于明白|这才意识到|才刚刚开始|从这一刻(?:开始|起)|这一刻[，,]?[他她]终于|他知道|她知道|他不知道的是|她不知道的是|"
    r"命运的齿轮|无论如何[，,]?[他她]都|未来(?:还|会)有|更大的(?:风暴|挑战|危机)(?:即将|正在)|一切都(?:将|会)(?:改变|不同))"
)


def last_sentence(content: str) -> str:
    sents = [m.group(0).strip() for m in re.finditer(r"[^。！？\n]+[。！？”」]*", content) if m.group(0).strip()]
    return sents[-1] if sents else ""


def ending_issue(content: str) -> dict[str, str] | None:
    """章末最后一句是总结、升华或空泛预告 → 钩子落空（mid）。"""
    last = last_sentence(content)
    if last and len(last) >= 4 and ENDING_SUMMARY_RX.search(last) and not last.startswith(("“", "「")):
        return {"severity": "mid", "dimension": "hook", "quote": last,
                "comment": "章末收在总结/升华/空泛预告上，读者合上也不损失什么。断在一个决定、发现、误判或代价出现的那一刻"}
    return None


def deterministic_issues(
    content: str,
    protagonist: str | None,
    required_chars: list[str],
    number: int,
    cheat_terms: list[str] | None = None,
) -> list[dict[str, str]]:
    """程序检查：主角 300 字内出场、出场守卫、章末总结句、量词搭配、第 1 章金手指露面。quote 由程序取自正文，天然可校验。"""
    out: list[dict[str, str]] = []
    for m in measure_errors(content)[:3]:
        out.append({"severity": "low", "dimension": "semantics", "quote": m["quote"],
                    "comment": f"量词搭配错误「{m['match']}」：{m['hint']}"})
    terms = [t for t in (cheat_terms or []) if t and len(t) >= 2]
    if number == 1 and terms and not any(t in content for t in terms):
        out.append({"severity": "mid", "dimension": "payoff", "quote": first_sentence(content),
                    "comment": "第 1 章没检出金手指/核心卖点的苗头（关键词：" + "、".join(terms[:4])
                               + "）。让它在本章露一次读者能感知的反应：数字、提示、身体感受或一次小收益"})
    # v0.17：只查第 1 章（之后的章常从配角或上一章的场面接起），主角取同人设定里的原创主角
    if number == 1 and protagonist and protagonist not in content[:300]:
        out.append({
            "severity": "mid",
            "dimension": "hook",
            "quote": first_sentence(content),
            "comment": f"主角「{protagonist}」没有在前 300 字内出场",
        })
    for name in required_chars:
        if name and name not in content:
            out.append({
                "severity": "high",
                "dimension": "coherence",
                "quote": first_sentence(content),
                "comment": f"出场守卫：细纲要求的角色「{name}」没有出现在正文中",
            })
    end = ending_issue(content)
    if end:
        out.append(end)
    return out


def build_review(issues: list[dict[str, str]], reader: dict[str, Any] | None = None) -> dict[str, Any]:
    scores = compute_scores(issues)
    passed = not any(i["severity"] == "high" for i in issues) and scores["overall"] >= PASS_OVERALL
    out: dict[str, Any] = {"scores": scores, "issues": issues, "passed": passed}
    if reader:
        out["reader"] = reader
        if isinstance(reader.get("score"), int) and reader["score"] < READER_PASS:
            out["passed"] = False
    return out


DEFAULT_PERSONA = "一个每天在番茄刷 3 小时网文的老读者：通勤时单手刷，没耐心，看过几百本，最烦主角憋屈、注水、套路重复"


def reader_persona(book: Any) -> str:
    """v0.17 读者人设按书来：同人书是看过原著的同人读者，原创书按频道和题材。"""
    if book is None:
        return DEFAULT_PERSONA
    gender = "女频" if getattr(book, "gender", "") == "female" else "男频"
    ff = getattr(book, "fanfic", None)
    if isinstance(ff, dict) and (ff.get("source_title") or ff.get("source_id")):
        src = str(ff.get("source_title") or "原著").strip("《》")
        return (f"一个把《{src}》原著翻过好几遍、也常在番茄刷{gender}同人的老读者：熟悉原著人物和名场面，"
                "最烦人物 OOC、照抄原著剧情和主角被原著人物抢戏，想看主角怎么把原著的走向改掉")
    genre = str(getattr(book, "genre", "") or "").strip()
    genre = genre if genre and genre != "同人" else "网文"
    return (f"一个每天在番茄刷 3 小时{gender}{genre}的老读者：通勤时单手刷，没耐心，这类书看过几百本，"
            "最烦主角憋屈、注水、套路重复")


def run_reader(gw: LLMGateway, content: str, number: int, chapter_plan: str, context: str,
               meta: dict[str, Any] | None = None, persona: str = "") -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """番茄老读者视角：给追读意愿打分，标出想划走的句子，并回答三问（主角想要什么 / 在等什么 / 最后一句后想知道什么）。
    失败时返回 (None, [])，不影响主审稿。"""
    try:
        raw = gw.chat_json(
            "reader", system_prompt("reader"),
            render("reader", number=number, chapter_plan=chapter_plan, content=content, persona=persona or DEFAULT_PERSONA,
                   context=context or "（无：这是开篇）"),
            meta={**(meta or {}), "content": content, "number": number}, temperature=0.3,
        )
    except Exception:  # noqa: BLE001
        return None, []
    if not isinstance(raw, dict):
        return None, []
    items = [{**it, "dimension": "retention"} for it in (raw.get("issues") or []) if isinstance(it, dict)]
    issues, _ = validate_issues({"issues": items[:6]}, content)
    score = raw.get("score")
    try:
        score = max(0, min(10, int(score)))
    except (TypeError, ValueError):
        score = None
    if score is None and not issues:
        return None, []
    out: dict[str, Any] = {"score": score, "verdict": str(raw.get("verdict") or "")[:200]}
    for k in ("want", "waiting", "next"):
        if str(raw.get(k) or "").strip():
            out[k] = str(raw[k]).strip()[:160]
    drop = str(raw.get("drop") or "").strip()
    if drop and quote_in_text(drop, content):
        out["drop"] = drop[:160]
    return out, issues


def run_review(
    gw: LLMGateway,
    content: str,
    number: int,
    chapter_plan: str,
    protagonist: str | None,
    required_chars: list[str],
    meta: dict[str, Any] | None = None,
    context: str = "",
    cheat_terms: list[str] | None = None,
    extra_issues: list[dict[str, Any]] | None = None,
    persona: str = "",
) -> tuple[dict[str, Any], int]:
    """返回（Review dict, 被丢弃的无证据 issue 数）。context：人物当前状态 + 上一章结尾，供连贯性核对。
    extra_issues：v0.9.4 程序规则产出的问题（数值一致性 lint 等），quote 取自正文，与确定性检查一起计分。"""
    raw = gw.chat_json(
        "review",
        system_prompt("review"),
        render("review", number=number, chapter_plan=chapter_plan, content=content,
               context=context or "（无：本书尚无已登记状态）"),
        meta={**(meta or {}), "content": content, "number": number},
        temperature=0.2,
    )
    llm_issues, dropped = validate_issues(raw, content, keep_src=True)
    reader, reader_issues = run_reader(gw, content, number, chapter_plan, context, meta, persona)
    det = deterministic_issues(content, protagonist, required_chars, number, cheat_terms)
    for it in extra_issues or []:
        if isinstance(it, dict) and it.get("quote") and quote_in_text(str(it["quote"]), content):
            dim = DIM_ALIASES.get(str(it.get("dimension")), str(it.get("dimension")))
            det.append({**it, "severity": it.get("severity") if it.get("severity") in SEVERITIES else "mid",
                        "dimension": dim if dim in DIMENSIONS else "continuity"})
    issues = det + llm_issues + reader_issues
    src_map = {int(x["_src"]): len(det) + k for k, x in enumerate(llm_issues)}
    for x in llm_issues:
        x.pop("_src", None)
    patches, _ = validate_patches(raw, content, issues, src_map)
    review = build_review(issues, reader)
    review["patches"] = patches
    return review, dropped


# ------------------------------------------------------------------ v0.9.4 提交前修中等问题

PRE_COMMIT_FIX_DIMENSIONS = ("continuity", "retention")


def pre_commit_targets(review: dict[str, Any] | None, content: str) -> tuple[list[int], list[int]]:
    """最后一轮审稿里 continuity / retention（含番茄老读者审读）类 mid 问题。
    返回（问题下标, 能直接用的补丁下标）。问题的 quote 必须还在正文里；补丁要没应用过且对应这些问题。"""
    rv = review or {}
    issues = rv.get("issues") or []
    idx = [k for k, it in enumerate(issues) if it.get("severity") == "mid" and it.get("dimension") in PRE_COMMIT_FIX_DIMENSIONS
           and quote_in_text(str(it.get("quote") or ""), content)]
    want = set(idx)
    pats = [int(p["index"]) for p in rv.get("patches") or [] if not p.get("applied") and p.get("issue_ref") is not None
            and int(p["issue_ref"]) in want and str(p.get("original") or "") in content]
    return idx, pats


# ------------------------------------------------------------------ v0.17 多候选：成对比较

def _pair_once(gw: LLMGateway, first: str, second: str, number: int, chapter_plan: str, persona: str,
               meta: dict[str, Any] | None) -> tuple[str | None, str]:
    raw = gw.chat_json(
        "pairwise", system_prompt("pairwise"),
        render("pairwise", persona=f"你是{persona or DEFAULT_PERSONA}。", number=number, chapter_plan=chapter_plan, a=first, b=second),
        meta={**(meta or {}), "a": first, "b": second, "number": number}, temperature=0.2,
    )
    if not isinstance(raw, dict):
        return None, ""
    w = str(raw.get("winner") or "").strip().upper()[:1]
    return (w if w in ("A", "B") else None), str(raw.get("reason") or "")[:200]


def pairwise_compare(gw: LLMGateway, a: str, b: str, number: int, chapter_plan: str, persona: str = "",
                     meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """两版候选成对比较「哪版更让人想点下一章」，不打绝对分。为抵消先后顺序的偏好，正反各比一次：
    两次都选同一版才算赢（winner=0/1），意见不一致 winner=None，由调用方按审稿分兜底。"""
    votes: list[dict[str, Any]] = []
    picks: list[int | None] = []
    for order, (x, y) in enumerate(((a, b), (b, a))):
        try:
            w, why = _pair_once(gw, x, y, number, chapter_plan, persona, meta)
        except Exception:  # noqa: BLE001
            w, why = None, ""
        idx = None if w is None else ((0 if w == "A" else 1) if order == 0 else (1 if w == "A" else 0))
        picks.append(idx)
        votes.append({"order": "AB" if order == 0 else "BA", "winner": idx, "reason": why})
    winner = picks[0] if picks[0] is not None and picks[0] == picks[1] else None
    reason = next((v["reason"] for v in votes if v["winner"] == winner and v["reason"]), "") if winner is not None else ""
    return {"winner": winner, "votes": votes, "reason": reason}
