"""v0.12 E6 排版：纯代码规范化正文（不调模型），给批量质检的 format 操作和章节排版用。

做的事（每项可关）：
- 段落：去掉每段首尾空白、丢弃空段，段间统一空一行（或不空行）；可选首行缩进两个全角空格。
- 标点：省略号统一为「……」、破折号统一为「——」、中文语境里的半角 , . ? ! : ; 换成全角、
  直引号成对换成弯引号、重复的逗号句号去重、汉字之间多余的空格删掉。
- 长段：按平台档（番茄 70 字 / 起点 150 / 通用 120）列出超长段提示；开启 split_long 时在句末标点处拆开。
数字、人名、对白内容一字不改；只动空白和标点。
"""

from __future__ import annotations

import re
from typing import Any

from app.lint.humanlint import count_words

PARA_MAX = {"fanqie": 70, "qidian": 150, "generic": 120, "duanju": 70}
INDENT = "\u3000\u3000"
DEFAULTS: dict[str, Any] = {"blank_line": True, "indent": False, "punct": True, "split_long": False}

_CJK = r"\u4e00-\u9fff\u3400-\u4dbf"
_ELLIPSIS = re.compile(r"(?:\.{3,}|。{3,}|…+|·{3,}|．{3,}|、{3,})")
_DASH = re.compile(r"(?:-{2,}|－{2,}|—+|―+|─{2,})")
_HALF = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；"}
_HALF_AFTER = re.compile(rf"(?<=[{_CJK}”’）》」』…—])([,?!:;])")
_HALF_BEFORE = re.compile(rf"([,?!:;])(?=\s*[{_CJK}“‘（《「『])")
_DOT = re.compile(rf"(?<=[{_CJK}”’）》」』])\.(?![\d.])")
_DUP = re.compile(r"([，。、；：])\1+")
_SPACE = re.compile(rf"(?<=[{_CJK}，。！？；：、“”‘’（）《》…—])[ \t\u3000\u00a0]+(?=[{_CJK}，。！？；：、“”‘’（）《》…—])")


def _quotes(p: str, left: str, right: str, ch: str) -> tuple[str, int]:
    """段内直引号成对换成弯引号；数量是奇数说明有残缺，原样不动。"""
    n = p.count(ch)
    if n == 0 or n % 2:
        return p, 0
    out, k = [], 0
    for c in p:
        if c == ch:
            out.append(left if k % 2 == 0 else right)
            k += 1
        else:
            out.append(c)
    return "".join(out), n // 2


def _punct(p: str, stats: dict[str, int]) -> str:
    def count(rx: re.Pattern[str], repl: Any, text: str, key: str) -> str:
        new, n = rx.subn(repl, text)
        # 已经规范的（如「……」「——」）被同样替换回来不算改动
        if n and new != text:
            stats[key] = stats.get(key, 0) + n
        return new

    p = count(_ELLIPSIS, "……", p, "ellipsis")
    p = count(_DASH, "——", p, "dash")
    if re.search(rf"[{_CJK}]", p):
        p = count(_HALF_AFTER, lambda m: _HALF[m.group(1)], p, "punct")
        p = count(_HALF_BEFORE, lambda m: _HALF[m.group(1)], p, "punct")
        p = count(_DOT, "。", p, "punct")
        p, q1 = _quotes(p, "“", "”", '"')
        p, q2 = _quotes(p, "‘", "’", "'")
        if q1 + q2:
            stats["quotes"] = stats.get("quotes", 0) + q1 + q2
    p = count(_DUP, r"\1", p, "punct")
    p = count(_SPACE, "", p, "spaces")
    return p


def _split_long(p: str, limit: int) -> list[str]:
    """在句末标点处把超长段拆开（不在引号里面拆），尽量每段不超过 limit 字。"""
    if count_words(p) <= limit:
        return [p]
    cuts: list[int] = []
    depth = 0
    n = len(p)
    for i, c in enumerate(p):
        nxt = p[i + 1] if i + 1 < n else ""
        if c in "“‘「『":
            depth += 1
        elif c in "”’」』":
            depth = max(0, depth - 1)
            if depth == 0 and i > 0 and p[i - 1] in "。！？…" and i + 1 < n:
                cuts.append(i + 1)
        elif c in "。！？…" and depth == 0 and nxt and nxt not in "。！？…”’」』":
            cuts.append(i + 1)
    if not cuts:
        return [p]
    out: list[str] = []
    start = 0
    last_ok = None
    for c in cuts:
        if count_words(p[start:c]) > limit and last_ok is not None and last_ok > start:
            out.append(p[start:last_ok])
            start = last_ok
        last_ok = c
    out.append(p[start:])
    res: list[str] = []
    for seg in out:
        seg = seg.strip()
        if seg:
            res.append(seg)
    return res or [p]


def format_text(text: str, options: dict[str, Any] | None = None, platform: str = "fanqie") -> tuple[str, dict[str, Any]]:
    """返回（排版后正文, 报告）。报告：{changes:{ellipsis,dash,punct,quotes,spaces,split}, paragraphs_before, paragraphs_after,
    long_paragraphs:[{paragraph, words, excerpt}], limit, options}。"""
    opt = {**DEFAULTS, **{k: v for k, v in (options or {}).items() if k in DEFAULTS and v is not None}}
    limit = PARA_MAX.get(platform, 120)
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paras = [ln.strip(" \t\u3000\u00a0") for ln in raw.split("\n")]
    paras = [p for p in paras if p]
    before_n = len(paras)
    stats: dict[str, int] = {}
    if opt["punct"]:
        paras = [_punct(p, stats) for p in paras]
    if opt["split_long"]:
        new: list[str] = []
        for p in paras:
            parts = _split_long(p, limit)
            if len(parts) > 1:
                stats["split"] = stats.get("split", 0) + len(parts) - 1
            new.extend(parts)
        paras = new
    long_hints = [{"paragraph": i, "words": count_words(p), "excerpt": p[:24]} for i, p in enumerate(paras) if count_words(p) > limit]
    sep = "\n\n" if opt["blank_line"] else "\n"
    pre = INDENT if opt["indent"] else ""
    out = sep.join(pre + p for p in paras)
    report = {"changes": {k: stats.get(k, 0) for k in ("ellipsis", "dash", "punct", "quotes", "spaces", "split")},
              "paragraphs_before": before_n, "paragraphs_after": len(paras), "long_paragraphs": long_hints[:50],
              "long_count": len(long_hints), "limit": limit, "options": opt}
    return out, report
