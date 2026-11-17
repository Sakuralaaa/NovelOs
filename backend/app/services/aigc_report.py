"""v0.12 E6 朱雀检测报告导出：自包含 HTML（内联样式、无外部资源），PDF 用浏览器「打印 → 存为 PDF」。

- 章节报告：整体 AI 置信度与档位、人工/疑似/AI 三段占比、AI 段与疑似段列表（带原文与置信度）、
  原文高亮（AI 红、疑似黄）、本章历次检测趋势。
- 独立检测报告：同上（无历史）。
- 批量报告：一批章节的 AI 率前后对比表、失败章及原因。
print=1 时页面加载完自动弹出打印对话框。
"""

from __future__ import annotations

import html
from typing import Any

LEVEL_LABEL = {"low": "低", "mid": "中", "high": "高"}
LEVEL_COLOR = {"low": "#1f8a5b", "mid": "#b7791f", "high": "#c53030"}
SEG_LABEL = {"ai": "AI", "suspect": "疑似", "human": "人工"}

_CSS = """
*{box-sizing:border-box}body{margin:0;background:#f6f5f2;color:#1f1d1a;font:14px/1.7 -apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:28px 22px 60px}
.bar{position:sticky;top:0;z-index:2;background:#1f1d1a;color:#fff;padding:10px 22px;display:flex;gap:12px;align-items:center;justify-content:space-between}
.bar button{background:#fff;color:#1f1d1a;border:0;border-radius:6px;padding:6px 14px;font-size:13px;cursor:pointer}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid #e3e0d8}
.sub{color:#6b665d;font-size:12.5px}
.card{background:#fff;border:1px solid #e3e0d8;border-radius:12px;padding:18px 20px;margin-top:16px}
.big{font-size:44px;font-weight:700;line-height:1;letter-spacing:-.02em}.big small{font-size:18px;margin-left:2px}
.pill{display:inline-block;border-radius:999px;padding:2px 12px;font-weight:600;font-size:13px;background:#f1efe9}
.row{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap}
.stack{display:flex;height:12px;border-radius:999px;overflow:hidden;background:#eee;margin-top:14px}
.stack i{display:block;height:100%}
.legend{display:flex;gap:18px;margin-top:8px;font-size:12.5px}.legend b{font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:middle}
.meta{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:12px;padding-top:10px;border-top:1px solid #eee;color:#6b665d;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #eee;vertical-align:top}
th{color:#6b665d;font-weight:500;background:#faf9f6}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.seg{display:inline-block;color:#fff;border-radius:4px;padding:0 6px;font-size:11px;font-weight:600}
.text{font-family:"Songti SC","Noto Serif CJK SC","SimSun",serif;font-size:15.5px;line-height:1.95;white-space:pre-wrap;word-break:break-word}
mark{color:inherit;border-radius:2px;padding:0 1px}mark.ai{background:rgba(197,48,48,.16);box-shadow:inset 0 -2px 0 rgba(197,48,48,.6)}
mark.suspect{background:rgba(214,158,46,.22);box-shadow:inset 0 -2px 0 rgba(214,158,46,.7)}
.good{color:#1f8a5b}.bad{color:#c53030}.muted{color:#8a857b}
.warn{background:#fff6e5;border:1px solid #f3dca8;color:#8a5a00;border-radius:8px;padding:8px 12px;font-size:12.5px;margin-top:12px}
@media print{body{background:#fff}.bar{display:none}.wrap{padding:0;max-width:none}.card{break-inside:avoid;border-color:#ccc}
 h2{break-after:avoid}tr{break-inside:avoid}@page{margin:16mm 14mm}}
"""


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def pct(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, f * 100 if f <= 1 else f))


def _fmt(v: float) -> str:
    return f"{v:.0f}" if v >= 10 else f"{v:.1f}"


def _page(title: str, body: str, print_mode: bool) -> str:
    auto = "<script>window.addEventListener('load',function(){setTimeout(function(){window.print()},300)})</script>" if print_mode else ""
    return (f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
            f"<div class=\"bar\"><span>{_e(title)}</span><button onclick=\"window.print()\">打印 / 存为 PDF</button></div>"
            f"<div class=\"wrap\">{body}</div>{auto}</body></html>")


def _summary_card(r: dict[str, Any]) -> str:
    level = r.get("level") or "low"
    big = pct(r.get("softmax"))
    color = LEVEL_COLOR.get(level, "#444")
    lr = r.get("labels_ratio") or {}
    parts = [("human", "人工", pct(lr.get("human")), "#38a169"), ("suspect", "疑似", pct(lr.get("suspect")), "#d69e2e"),
             ("ai", "AI", pct(lr.get("ai")), "#c53030")]
    total = sum(p[2] for p in parts) or 1
    stack = "".join(f"<i style=\"width:{p[2] / total * 100:.2f}%;background:{p[3]}\"></i>" for p in parts if p[2] > 0)
    legend = "".join(f"<span><span class=\"dot\" style=\"background:{p[3]}\"></span>{p[1]} <b>{_fmt(p[2])}%</b></span>" for p in parts)
    meta = []
    if r.get("ai_segment_ratio") is not None:
        meta.append(f"AI 段 {_fmt(pct(r.get('ai_segment_ratio')))}% · 疑似段 {_fmt(pct(r.get('suspect_segment_ratio')))}%")
    if r.get("chars"):
        meta.append(f"{int(r['chars']):,} 字")
    meta.append(f"{int(r.get('tokens') or 0):,} tokens" + (f" · 分 {r['chunks']} 段检测" if (r.get("chunks") or 0) > 1 else ""))
    if r.get("checked_at"):
        meta.append(f"检测于 {_e(str(r['checked_at']).replace('T', ' ')[:19])}（UTC）")
    meta.append("检测模型：腾讯朱雀 @makers/zhuque-text")
    return (f"<div class=\"card\"><div class=\"row\"><div><div class=\"sub\">整体 AI 置信度</div>"
            f"<div class=\"big\" style=\"color:{color}\">{_fmt(big)}<small>%</small></div></div>"
            f"<span class=\"pill\" style=\"color:{color}\">{LEVEL_LABEL.get(level, level)} 风险</span></div>"
            f"<div class=\"stack\">{stack}</div><div class=\"legend\">{legend}</div>"
            f"<div class=\"meta\">{''.join(f'<span>{m}</span>' for m in meta)}</div></div>")


def _segments_table(text: str, segs: list[dict[str, Any]], limit: int = 200) -> str:
    rows = [s for s in segs if s.get("label") in ("ai", "suspect") and int(s.get("end") or 0) > int(s.get("start") or 0)]
    rows.sort(key=lambda s: (-float(s.get("conf") or 0), int(s.get("start") or 0)))
    if not rows:
        return "<p class=\"muted\">没有标出 AI 或疑似片段。</p>"
    body = []
    for i, s in enumerate(rows[:limit], 1):
        a, b = int(s["start"]), int(s["end"])
        snip = " ".join(text[a:b].split()) if text else ""
        color = "#c53030" if s["label"] == "ai" else "#d69e2e"
        body.append(f"<tr><td class=\"num\">{i}</td><td><span class=\"seg\" style=\"background:{color}\">{SEG_LABEL[s['label']]}</span></td>"
                    f"<td>{_e(snip[:160]) + ('…' if len(snip) > 160 else '') or f'<span class=muted>位置 {a}–{b}</span>'}</td>"
                    f"<td class=\"num\">{_fmt(pct(s.get('conf')))}%</td><td class=\"num\">{b - a}</td></tr>")
    more = f"<p class=\"muted\">另有 {len(rows) - limit} 段未列出。</p>" if len(rows) > limit else ""
    return ("<table><thead><tr><th class=\"num\">#</th><th>判定</th><th>片段</th><th class=\"num\">置信度</th><th class=\"num\">字数</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>{more}")


def _highlight(text: str, segs: list[dict[str, Any]]) -> str:
    marks = sorted([s for s in segs if s.get("label") in ("ai", "suspect")], key=lambda s: int(s.get("start") or 0))
    out, pos = [], 0
    for s in marks:
        a, b = int(s.get("start") or 0), int(s.get("end") or 0)
        if a < pos or a >= len(text) or b <= a:
            continue
        out.append(_e(text[pos:a]))
        out.append(f"<mark class=\"{s['label']}\" title=\"{SEG_LABEL[s['label']]} {_fmt(pct(s.get('conf')))}%\">{_e(text[a:min(b, len(text))])}</mark>")
        pos = b
    out.append(_e(text[pos:]))
    return "".join(out)


def _history_table(history: list[dict[str, Any]], current_index: int) -> str:
    if len(history) < 2:
        return ""
    rows = []
    prev = None
    for i, h in enumerate(history):
        v = pct(h.get("softmax"))
        d = "" if prev is None else (f"<span class=\"{'good' if v < prev else 'bad' if v > prev else 'muted'}\">{v - prev:+.1f}</span>")
        cur = " <b>（本报告）</b>" if i == current_index else ""
        src = {"batch": "批量质检", "manual": "手动检测"}.get(str(h.get("source") or ""), "")
        rows.append(f"<tr><td class=\"num\">{i + 1}</td><td>{_e(str(h.get('checked_at') or '').replace('T', ' ')[:19])}{cur}</td>"
                    f"<td>{_e(src)}</td><td class=\"num\">{_fmt(v)}%</td><td class=\"num\">{d}</td>"
                    f"<td>{LEVEL_LABEL.get(str(h.get('level')), '')}</td><td class=\"num\">{int(h.get('chars') or 0):,}</td></tr>")
        prev = v
    return ("<h2>历次检测</h2><table><thead><tr><th class=\"num\">#</th><th>时间（UTC）</th><th>来源</th><th class=\"num\">AI 置信度</th>"
            "<th class=\"num\">较上次</th><th>档位</th><th class=\"num\">字数</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def render_aigc(title: str, subtitle: str, result: dict[str, Any], text: str, history: list[dict[str, Any]] | None = None,
                current_index: int = -1, stale: bool = False, print_mode: bool = False) -> str:
    segs = [s for s in (result.get("segments") or []) if isinstance(s, dict)]
    body = [f"<h1>{_e(title)}</h1><div class=\"sub\">{_e(subtitle)}</div>", _summary_card(result)]
    if stale:
        body.append("<div class=\"warn\">这次检测之后正文又改过；下方原文是检测时的版本。</div>")
    body.append("<h2>AI / 疑似片段（按置信度排序）</h2>")
    body.append(_segments_table(text, segs))
    if history:
        body.append(_history_table(history, current_index if current_index >= 0 else len(history) + current_index))
    if text:
        body.append("<h2>原文标注</h2><div class=\"legend\"><span><span class=\"dot\" style=\"background:#c53030\"></span>AI</span>"
                    "<span><span class=\"dot\" style=\"background:#d69e2e\"></span>疑似</span></div>")
        body.append(f"<div class=\"card text\">{_highlight(text, segs)}</div>")
    return _page(title, "".join(body), print_mode)


def render_batch(book_title: str, run: dict[str, Any], items: list[dict[str, Any]], print_mode: bool = False) -> str:
    title = f"《{book_title}》批量{run.get('op_label', '')}报告"
    sm = run.get("live_summary") or run.get("summary") or {}
    ai = sm.get("ai") or {}
    src = {"zhuque": "腾讯朱雀 AI 置信度", "local": "本地人味分（0–100，越高越像 AI）"}.get(str(ai.get("source") or ""), "—")
    head = [f"<h1>{_e(title)}</h1><div class=\"sub\">第 {run.get('from')}–{run.get('to')} 章 · 共 {sm.get('total', len(items))} 章 · "
            f"批次 #{run.get('id')} · 创建于 {_e(str(run.get('created_at') or '').replace('T', ' ')[:19])}（UTC）</div>"]
    tiles = [("已处理", f"{sm.get('processed', 0)}/{sm.get('total', 0)}"), ("待确认", (sm.get("counts") or {}).get("pending", 0)),
             ("失败", len(sm.get("failed") or []))]
    if ai.get("avg_before") is not None:
        tiles.append(("AI 率均值", f"{ai['avg_before']} → {ai['avg_after']}（{ai['avg_delta']:+}）"))
    elif ai.get("avg_after") is not None:
        tiles.append(("AI 率均值", f"{ai['avg_after']}"))
    head.append("<div class=\"card\"><div class=\"row\">" + "".join(
        f"<div><div class=\"sub\">{_e(k)}</div><div style=\"font-size:20px;font-weight:700\">{_e(v)}</div></div>" for k, v in tiles)
        + f"</div><div class=\"meta\"><span>AI 率口径：{_e(src)}</span></div></div>")
    status_label = {"pending": "待确认", "adopted": "已采纳", "discarded": "已弃用", "done": "完成", "unchanged": "无改动",
                    "failed": "失败", "skipped": "跳过", "queued": "排队", "running": "处理中"}
    rows = []
    for it in items:
        m = it.get("metrics") or {}
        b, a = (m.get("ai_before") or {}).get("value"), (m.get("ai_after") or {}).get("value")
        d = m.get("ai_delta")
        dcell = "" if d is None else f"<span class=\"{'good' if d < 0 else 'bad' if d > 0 else 'muted'}\">{d:+.1f}</span>"
        note = it.get("error") or ""
        if it.get("op") == "titles" and it.get("changed"):
            note = f"{it.get('base_title') or '（无）'} → {it.get('title')}"
        rv = m.get("review")
        if rv:
            note = f"审稿 {rv.get('overall')} 分，严重 {rv.get('high')} / 中等 {rv.get('mid')}" + (f"；{note}" if note else "")
        rounds = len(m.get("rounds") or [])
        rows.append(f"<tr><td class=\"num\">第{it.get('number')}章</td><td>{_e(status_label.get(str(it.get('status')), it.get('status')))}</td>"
                    f"<td class=\"num\">{'' if b is None else b}</td><td class=\"num\">{'' if a is None else a}</td><td class=\"num\">{dcell}</td>"
                    f"<td class=\"num\">{rounds or ''}</td><td class=\"num\">{m.get('words_before') or ''}→{m.get('words_after') or ''}</td>"
                    f"<td>{_e(note)}</td></tr>")
    table = ("<h2>逐章结果</h2><table><thead><tr><th class=\"num\">章</th><th>状态</th><th class=\"num\">AI 前</th><th class=\"num\">AI 后</th>"
             "<th class=\"num\">变化</th><th class=\"num\">轮数</th><th class=\"num\">字数</th><th>说明</th></tr></thead>"
             f"<tbody>{''.join(rows)}</tbody></table>")
    return _page(title, "".join(head) + table, print_mode)
