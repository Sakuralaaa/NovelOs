"""风格卡：用户粘贴范文 → 代码统计 + LLM 总结写法 → 截取 800–1500 字片段作为 few-shot，写入 Context Pack 固定前缀。"""

from __future__ import annotations

from typing import Any

from app.db import session_scope
from app.jobs.manager import JobContext
from app.lint.humanlint import bare_dialogue_analysis, count_words, dialogue_ratio, has_descriptor, paragraphs, text_stats
from app.llm.gateway import get_gateway
from app.models.tables import Style
from app.services import common
from app.skills.loader import render, system_prompt

SAMPLE_MAX = 5000
EXCERPT_MIN, EXCERPT_MAX = 800, 1500


def pick_excerpt(text: str) -> str:
    """按段落滑窗挑 800–1500 字的片段，优先“对话配动作、描写密”的一段。范文不足 800 字则全取。"""
    paras = paragraphs(text)
    if count_words(text) <= EXCERPT_MAX:
        return "\n".join(paras)
    best, best_score = "", -1.0
    for i in range(len(paras)):
        chunk: list[str] = []
        n = 0
        for p in paras[i:]:
            if n + count_words(p) > EXCERPT_MAX and n >= EXCERPT_MIN:
                break
            chunk.append(p)
            n += count_words(p)
            if n >= EXCERPT_MAX:
                break
        if n < EXCERPT_MIN:
            continue
        seg = "\n".join(chunk)
        bare, _ = bare_dialogue_analysis(seg)
        dr = dialogue_ratio(seg)
        desc = sum(1 for p in chunk if has_descriptor(p)) / max(len(chunk), 1)
        score = desc + (1 - bare) + (0.5 if 0.15 <= dr <= 0.45 else 0)
        if score > best_score:
            best, best_score = seg, score
    if not best:
        best = text[:EXCERPT_MAX]
    if count_words(best) > EXCERPT_MAX:
        best = best[: EXCERPT_MAX + 200]
    return best


def extract_style(book_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        common.get_book(s, book_id)
        st = s.get(Style, book_id)
        sample = st.sample_text if st else ""
    if not sample.strip():
        raise ValueError("请先在风格卡里粘贴范文（不超过 5000 字）")
    ctx.progress(20, "统计句长、对话、描写密度")
    stats = text_stats(sample)
    excerpt = pick_excerpt(sample)
    ctx.progress(50, "总结写法")
    llm = get_gateway().chat_json(
        "style_extract", system_prompt("style_extract"),
        render("style_extract", stats=stats, sample=sample[:SAMPLE_MAX]),
        meta={"stats": stats}, temperature=0.3,
    )
    if not isinstance(llm, dict):
        llm = {}
    extracted = {"stats": stats, "llm": llm, "excerpt": excerpt, "excerpt_words": count_words(excerpt)}
    with session_scope() as s:
        st = s.get(Style, book_id) or Style(book_id=book_id)
        st.extracted = extracted
        s.add(st)
        s.commit()
    return {"excerpt_words": extracted["excerpt_words"], "avg_sentence_len": stats["avg_sentence_len"]}
