"""人味 lint：纯代码、确定性、中文。

输出与合约 Lint 对齐：
{ai_score, dialogue_ratio, repeated_ngrams, banned_hits, warnings,
 avg_sentence_len, short_sentence_ratio, bare_dialogue_ratio, summary_ratio}

所有阈值见 app.config.LintThresholds（经验值，未校准）。
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.config import LintThresholds
from app.lint.banned_zh import BANNED_PATTERNS, DESCRIPTOR_WORDS, SUMMARY_MARKERS

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_DIALOGUE = re.compile(r"“[^”]*”|「[^」]*」|\"[^\"\n]*\"")
_DASH_ELLIPSIS = re.compile(r"——|……|\.\.\.|…")
_SENT_END = re.compile(r"[^。！？!?；;…\n]+[。！？!?；;…]*")
_DESCRIPTOR_RX = re.compile("|".join(re.escape(w) for w in sorted(DESCRIPTOR_WORDS, key=len, reverse=True)))
_SUMMARY_RX = re.compile("|".join(re.escape(w) for w in sorted(SUMMARY_MARKERS, key=len, reverse=True)))


def count_words(text: str) -> int:
    """网文字数：去掉空白后的字符数。"""
    return len(re.sub(r"\s", "", text))


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n+", text) if p.strip()]


def dialogue_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in _DIALOGUE.finditer(text)]


def dialogue_ratio(text: str) -> float:
    total = count_words(text)
    if total == 0:
        return 0.0
    d = sum(count_words(m.group(0)) for m in _DIALOGUE.finditer(text))
    return round(d / total, 4)


def sentences(text: str) -> list[str]:
    """按句末标点切句；引号内整段对白内部也会被切开（与读感一致）。"""
    out: list[str] = []
    for p in paragraphs(text):
        for m in _SENT_END.finditer(p):
            s = m.group(0).strip().strip("“”「」\"")
            if count_words(re.sub(r"[，,、：:；;。！？!?…“”「」\"—\s]", "", s)) > 0:
                out.append(s)
    return out


def _core_len(s: str) -> int:
    return len(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s))


def sentence_stats(text: str) -> dict[str, Any]:
    lens = [_core_len(s) for s in sentences(text)]
    lens = [n for n in lens if n > 0]
    if not lens:
        return {"avg": 0.0, "short_ratio": 0.0, "hist": {}, "count": 0}
    buckets = {"1-8": 0, "9-15": 0, "16-25": 0, "26-40": 0, "41+": 0}
    for n in lens:
        k = "1-8" if n <= 8 else "9-15" if n <= 15 else "16-25" if n <= 25 else "26-40" if n <= 40 else "41+"
        buckets[k] += 1
    return {
        "avg": round(statistics.mean(lens), 2),
        "short_ratio": round(sum(1 for n in lens if n <= 8) / len(lens), 4),
        "hist": {k: round(v / len(lens), 4) for k, v in buckets.items()},
        "count": len(lens),
    }


# ---------- 裸对白 ----------

@dataclass
class _Unit:
    kind: str  # "q" 对白 / "n" 叙述句
    text: str
    para: int


def _units(text: str) -> list[_Unit]:
    units: list[_Unit] = []
    for pi, p in enumerate(paragraphs(text)):
        pos = 0
        for m in _DIALOGUE.finditer(p):
            before = p[pos : m.start()]
            for s in _SENT_END.findall(before):
                if s.strip():
                    units.append(_Unit("n", s.strip(), pi))
            units.append(_Unit("q", m.group(0), pi))
            pos = m.end()
        for s in _SENT_END.findall(p[pos:]):
            if s.strip(" ，,：:"):
                units.append(_Unit("n", s.strip(), pi))
    return units


def has_descriptor(s: str) -> bool:
    return bool(_DESCRIPTOR_RX.search(s))


def bare_dialogue_analysis(text: str) -> tuple[float, list[int]]:
    """对白段前后 1 句（叙述句）内没有动作/神态/环境词即为“裸对白”。

    返回 (裸对白比例, 含裸对白的段落下标列表)。启发式，非精确判定。
    """
    units = _units(text)
    q_idx = [i for i, u in enumerate(units) if u.kind == "q"]
    if not q_idx:
        return 0.0, []
    bare_paras: list[int] = []
    bare = 0
    for i in q_idx:
        # 同段内的前后叙述句都算；跨段只认“紧接在上一段末尾、引出这句对白”的那一句
        neigh = []
        for j in (i - 1, i + 1):
            if 0 <= j < len(units) and units[j].kind == "n":
                if units[j].para == units[i].para or (j == i - 1):
                    neigh.append(units[j])
        if not any(has_descriptor(u.text) for u in neigh):
            bare += 1
            if units[i].para not in bare_paras:
                bare_paras.append(units[i].para)
    return round(bare / len(q_idx), 4), bare_paras


# ---------- 概述式叙述 ----------

def summary_analysis(text: str) -> tuple[float, list[int]]:
    """叙述句中含概述标记（“经过一番”“很快”“于是”“随后”…）的比例。估计值。

    返回 (比例, 概述标记密集的段落下标)。
    """
    narr: list[tuple[int, str]] = []
    for u in _units(text):
        if u.kind == "n":
            narr.append((u.para, u.text))
    if not narr:
        return 0.0, []
    hit_paras: Counter[int] = Counter()
    hits = 0
    for pi, s in narr:
        if _SUMMARY_RX.search(s):
            hits += 1
            hit_paras[pi] += 1
    paras = paragraphs(text)
    flagged = [pi for pi, c in hit_paras.items() if c >= 2 or not _DIALOGUE.search(paras[pi])]
    return round(hits / len(narr), 4), sorted(flagged)


# ---------- 词表 ----------

def banned_hits(text: str) -> list[dict[str, int | str]]:
    """词表命中。句式类优先，其次长词优先；已被覆盖的位置不重复计数。只查叙述的条目跳过引号内。"""
    spans = dialogue_spans(text)
    claimed: list[tuple[int, int]] = []
    counts: Counter[str] = Counter()
    pats = sorted(BANNED_PATTERNS, key=lambda p: (p.priority, -len(p.word) if p.priority == 1 else 0))
    for pat in pats:
        for m in pat.regex.finditer(text):
            a, b = m.span()
            if b <= a:
                continue
            if pat.narration_only and any(sa <= a < sb for sa, sb in spans):
                continue
            if any(a < cb and ca < b for ca, cb in claimed):
                continue
            claimed.append((a, b))
            counts[pat.word] += 1
    return [{"word": w, "count": c} for w, c in counts.most_common()]


def category_counts(hits: list[dict[str, int | str]]) -> dict[str, int]:
    by_word = {p.word: p.category for p in BANNED_PATTERNS}
    c: Counter[str] = Counter()
    for h in hits:
        c[by_word.get(str(h["word"]), "其他")] += int(h["count"])
    return dict(c)


# ---------- n-gram ----------

def _grams(text: str, n_min: int, n_max: int) -> Counter[str]:
    c: Counter[str] = Counter()
    for run in _CJK_RUN.findall(text):
        for n in range(n_min, n_max + 1):
            for i in range(0, len(run) - n + 1):
                c[run[i : i + n]] += 1
    return c


def repeated_ngrams(
    text: str,
    book_texts: Iterable[str],
    th: LintThresholds,
    exclude_names: Sequence[str] = (),
) -> list[dict[str, int | str]]:
    """本章中、在全书（含本章）出现 ≥ ngram_min_count 次的 4–6 gram。

    含人物/实体名的 gram 排除；被更长复用 gram 覆盖的短 gram 去重。
    """
    mine = _grams(text, th.ngram_min, th.ngram_max)
    total = Counter(mine)
    for t in book_texts:
        g = _grams(t, th.ngram_min, th.ngram_max)
        for k in mine:
            if k in g:
                total[k] += g[k]
    names = [n for n in exclude_names if n]

    def touches_name(k: str) -> bool:
        for n in names:
            if n in k or k in n:
                return True
            # 名字被 gram 边界截断（如“连看都没看沈”）
            for i in range(1, len(n)):
                if k.endswith(n[:i]) or k.startswith(n[i:]):
                    return True
        return False

    cands = [(k, total[k]) for k in mine if total[k] >= th.ngram_min_count and not touches_name(k)]
    cands.sort(key=lambda kv: (-len(kv[0]), -kv[1]))
    kept: list[tuple[str, int]] = []
    for k, c in cands:
        if any(k in longer and c <= lc for longer, lc in kept):
            continue
        kept.append((k, c))
    kept.sort(key=lambda kv: (-kv[1], -len(kv[0])))
    return [{"text": k, "count": c} for k, c in kept[: th.ngram_report_max]]


# ---------- 汇总 ----------

@dataclass
class LintResult:
    ai_score: float
    dialogue_ratio: float
    repeated_ngrams: list[dict[str, int | str]] = field(default_factory=list)
    banned_hits: list[dict[str, int | str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    avg_sentence_len: float = 0.0
    short_sentence_ratio: float = 0.0
    bare_dialogue_ratio: float = 0.0
    summary_ratio: float = 0.0
    # 内部：精修定位
    bare_paragraphs: list[int] = field(default_factory=list)
    summary_paragraphs: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai_score": self.ai_score,
            "dialogue_ratio": self.dialogue_ratio,
            "repeated_ngrams": self.repeated_ngrams,
            "banned_hits": self.banned_hits,
            "warnings": self.warnings,
            "avg_sentence_len": self.avg_sentence_len,
            "short_sentence_ratio": self.short_sentence_ratio,
            "bare_dialogue_ratio": self.bare_dialogue_ratio,
            "summary_ratio": self.summary_ratio,
        }

    def needs_patch(self, th: LintThresholds) -> bool:
        """AI 腔词/总分超阈值 → 定点替换式重写。"""
        return self.ai_score > th.ai_score_rewrite

    def needs_thicken(self, th: LintThresholds) -> bool:
        """裸对白/概述/短句超阈值 → 描写增厚。"""
        return (
            self.bare_dialogue_ratio > th.bare_dialogue_max
            or self.summary_ratio > th.summary_ratio_max
            or self.short_sentence_ratio > th.short_sentence_ratio_max
        )

    def over_threshold(self, th: LintThresholds) -> bool:
        return self.needs_patch(th) or self.needs_thicken(th)


def lint_chapter(
    text: str,
    th: LintThresholds,
    book_texts: Iterable[str] = (),
    exclude_names: Sequence[str] = (),
    chapter_number: int | None = None,
) -> LintResult:
    words = max(count_words(text), 1)
    per_k = 1000.0 / words
    warnings: list[str] = []

    dr = dialogue_ratio(text)
    hits = banned_hits(text)
    cats = category_counts(hits)
    hit_total = sum(int(h["count"]) for h in hits)
    banned_density = hit_total * per_k
    reps = repeated_ngrams(text, book_texts, th, exclude_names)
    paras = paragraphs(text)
    lens = [count_words(p) for p in paras]
    mean_len = statistics.mean(lens) if lens else 0
    cv = statistics.pstdev(lens) / mean_len if len(lens) >= 2 and mean_len > 0 else 1.0
    punct_density = len(_DASH_ELLIPSIS.findall(text)) * per_k
    ss = sentence_stats(text)
    bare_ratio, bare_paras = bare_dialogue_analysis(text)
    sum_ratio, sum_paras = summary_analysis(text)

    # 分项（满分 100）
    s_banned = min(1.0, banned_density / th.banned_per_k_max) * 30
    s_ngram = min(1.0, len(reps) / max(th.ngram_report_max, 1)) * 10
    s_uniform = max(0.0, (th.para_cv_min - cv) / th.para_cv_min) * 10 if cv < th.para_cv_min else 0.0
    s_punct = min(1.0, punct_density / th.punct_per_k_max) * 5
    if dr > th.dialogue_warn:
        s_dialogue = min(1.0, (dr - th.dialogue_warn) / 0.3) * 5
    elif dr < th.dialogue_low_warn:
        s_dialogue = 2.5
    else:
        s_dialogue = 0.0
    s_short = min(1.0, max(0.0, ss["short_ratio"] - 0.15) / 0.35) * 10
    if ss["avg"] and ss["avg"] < th.avg_sentence_len_min:
        s_short += min(1.0, (th.avg_sentence_len_min - ss["avg"]) / th.avg_sentence_len_min) * 5
    s_bare = min(1.0, bare_ratio / 0.8) * 15
    s_summary = min(1.0, sum_ratio / 0.25) * 10
    ai_score = round(
        min(100.0, s_banned + s_ngram + s_uniform + s_punct + s_dialogue + s_short + s_bare + s_summary), 1
    )

    if dr > th.dialogue_warn:
        warnings.append(f"对话占比 {dr:.0%}，超过 {th.dialogue_warn:.0%}，建议压缩对话、补动作与场景")
    elif dr < th.dialogue_low_warn and words > 500:
        warnings.append(f"对话占比仅 {dr:.0%}，叙述过密，读者容易疲劳")
    if banned_density > th.banned_per_k_warn:
        top = "、".join(str(h["word"]) for h in hits[:5])
        warnings.append(f"AI 腔词每千字 {banned_density:.1f} 处（{top}），建议逐处改成具体动作或删掉")
    for cat, label in (
        ("翻案腔", "翻案腔（无人主张时写“不是A而是B”）"),
        ("叙述破折号", "叙述中用破折号解释/列举/揭晓"),
        ("修饰副词+动作", "动作前多余修饰副词（微微点头→点头）"),
        ("翻译腔", "翻译腔连接词（当……时、对于……来说、这意味着、然而/此外）"),
    ):
        if cats.get(cat):
            warnings.append(f"{label} {cats[cat]} 处")
    if len(reps) >= 5:
        warnings.append(f"全书复用短语 {len(reps)} 组，例如「{reps[0]['text']}」，换个说法")
    if cv < th.para_cv_min and len(lens) >= 6:
        warnings.append(f"段落长度过于均匀（变异系数 {cv:.2f}），长短段交错会更像人写的")
    if punct_density > th.punct_per_k_max / 2:
        warnings.append("破折号/省略号偏多，正文里尽量清掉")
    if ss["short_ratio"] > th.short_sentence_ratio_max:
        warnings.append(f"≤8 字短句占 {ss['short_ratio']:.0%}，句子太碎，合并连续动作、长短句交替")
    if ss["avg"] and ss["avg"] < th.avg_sentence_len_min:
        warnings.append(f"平均句长 {ss['avg']:.1f} 字，偏短")
    if bare_ratio > th.bare_dialogue_max:
        warnings.append(f"裸对白占 {bare_ratio:.0%}：对白前后缺少动作、神态或环境，读起来像念稿")
    if sum_ratio > th.summary_ratio_max:
        warnings.append(f"概述式叙述约占 {sum_ratio:.0%}（经过一番/很快/于是/随后…），把概述改成可见的场面")
    if chapter_number is not None and chapter_number <= 3:
        for p in paras:
            if count_words(p) > th.first3_monologue_chars and not _DIALOGUE.search(p):
                warnings.append(
                    f"前三章出现超过 {th.first3_monologue_chars} 字的无对话长段（疑似长独白或大段设定）："
                    f"「{p[:16]}…」"
                )
                break

    return LintResult(
        ai_score=ai_score,
        dialogue_ratio=dr,
        repeated_ngrams=reps,
        banned_hits=hits,
        warnings=warnings,
        avg_sentence_len=float(ss["avg"]),
        short_sentence_ratio=float(ss["short_ratio"]),
        bare_dialogue_ratio=bare_ratio,
        summary_ratio=sum_ratio,
        bare_paragraphs=bare_paras,
        summary_paragraphs=sum_paras,
    )


def text_stats(text: str) -> dict[str, Any]:
    """风格卡用：范文的代码统计。"""
    words = max(count_words(text), 1)
    ss = sentence_stats(text)
    bare_ratio, _ = bare_dialogue_analysis(text)
    sum_ratio, _ = summary_analysis(text)
    desc = len(_DESCRIPTOR_RX.findall(text))
    paras = paragraphs(text)
    plens = [count_words(p) for p in paras]
    return {
        "words": words,
        "avg_sentence_len": ss["avg"],
        "short_sentence_ratio": ss["short_ratio"],
        "sentence_len_hist": ss["hist"],
        "dialogue_ratio": dialogue_ratio(text),
        "descriptor_per_k": round(desc * 1000 / words, 1),
        "bare_dialogue_ratio": bare_ratio,
        "summary_ratio": sum_ratio,
        "avg_paragraph_len": round(statistics.mean(plens), 1) if plens else 0,
        "paragraphs": len(paras),
    }
