"""证据式审稿：LLM 只给带原句的 issues；程序校验 quote、补充确定性检查、计算分数。"""

from __future__ import annotations

import re
from typing import Any

from app.llm.gateway import LLMGateway
from app.skills.loader import render, system_prompt

DIMENSIONS = ("hook", "pacing", "payoff", "character", "coherence")
SEVERITIES = ("high", "mid", "low")
PENALTY = {"high": 25, "mid": 10, "low": 3}
WEIGHTS = {"hook": 0.25, "pacing": 0.2, "payoff": 0.2, "character": 0.15, "coherence": 0.2}
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


def deterministic_issues(
    content: str,
    protagonist: str | None,
    required_chars: list[str],
    number: int,
) -> list[dict[str, str]]:
    """程序检查：主角 300 字内出场、出场守卫。quote 由程序取自正文，天然可校验。"""
    out: list[dict[str, str]] = []
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
) -> tuple[dict[str, Any], int]:
    """返回（Review dict, 被丢弃的无证据 issue 数）。"""
    raw = gw.chat_json(
        "review",
        system_prompt("review"),
        render("review", number=number, chapter_plan=chapter_plan, content=content),
        meta={**(meta or {}), "content": content, "number": number},
        temperature=0.2,
    )
    llm_issues, dropped = validate_issues(raw, content)
    issues = deterministic_issues(content, protagonist, required_chars, number) + llm_issues
    return build_review(issues), dropped
