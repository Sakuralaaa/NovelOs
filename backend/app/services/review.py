"""证据式审稿：LLM 只给带原句的 issues；程序校验 quote、补充确定性检查、计算分数。"""

from __future__ import annotations

import re
from typing import Any

from app.lint.humanlint import measure_errors
from app.llm.gateway import LLMGateway
from app.skills.loader import render, system_prompt

# v0.6：新增 continuity（连续性与物理逻辑：道具/服装/站位朝向/角度/身体前后矛盾）与 semantics（语义写反、搭配错误）
DIMENSIONS = ("hook", "pacing", "payoff", "character", "coherence", "continuity", "semantics")
SEVERITIES = ("high", "mid", "low")
PENALTY = {"high": 25, "mid": 10, "low": 3}
WEIGHTS = {"hook": 0.2, "pacing": 0.15, "payoff": 0.15, "character": 0.12, "coherence": 0.13, "continuity": 0.15, "semantics": 0.1}
# 模型偶尔用别名，归一到正式维度
DIM_ALIASES = {"physics": "continuity", "logic": "continuity", "props": "continuity", "consistency": "continuity",
               "semantic": "semantics", "meaning": "semantics", "wording": "semantics"}
PASS_OVERALL = 70

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub("", s).replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")


def quote_in_text(quote: str, content: str, min_len: int = 4) -> bool:
    """quote 必须（去空白后）原样出现在正文中，且不少于 min_len 字。"""
    q = _norm(quote).strip("\"'「」")
    if len(q) < min_len:
        return False
    return q in _norm(content)


def validate_issues(raw: Any, content: str) -> tuple[list[dict[str, str]], int]:
    """返回（合法 issues, 被丢弃数）。"""
    items = raw.get("issues") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return [], 0
    kept: list[dict[str, str]] = []
    dropped = 0
    for it in items:
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
        kept.append({"severity": sev, "dimension": dim, "quote": quote.strip(), "comment": str(it.get("comment", ""))[:300]})
    return kept, dropped


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
    if protagonist and protagonist not in content[:300]:
        out.append({
            "severity": "mid" if number > 3 else "high",
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


def build_review(issues: list[dict[str, str]]) -> dict[str, Any]:
    scores = compute_scores(issues)
    passed = not any(i["severity"] == "high" for i in issues) and scores["overall"] >= PASS_OVERALL
    return {"scores": scores, "issues": issues, "passed": passed}


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
) -> tuple[dict[str, Any], int]:
    """返回（Review dict, 被丢弃的无证据 issue 数）。context：人物当前状态 + 上一章结尾，供连贯性核对。"""
    raw = gw.chat_json(
        "review",
        system_prompt("review"),
        render("review", number=number, chapter_plan=chapter_plan, content=content,
               context=context or "（无：本书尚无已登记状态）"),
        meta={**(meta or {}), "content": content, "number": number},
        temperature=0.2,
    )
    llm_issues, dropped = validate_issues(raw, content)
    issues = deterministic_issues(content, protagonist, required_chars, number, cheat_terms) + llm_issues
    return build_review(issues), dropped
