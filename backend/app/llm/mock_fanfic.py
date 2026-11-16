"""v0.10 同人 mock：原著设定卡提炼、OOC 检查。确定性输出，按 meta 里程序给的候选名/证据句生成。"""

from __future__ import annotations

import json
from typing import Any


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def mock_fanfic_source(meta: dict[str, Any]) -> str:
    names = [str(x) for x in meta.get("names") or [] if x][:4] or ["原著主角", "原著配角"]
    part = int(meta.get("part") or 1)
    chars = []
    for k, n in enumerate(names):
        others = [x for x in names if x != n]
        chars.append({
            "name": n, "aliases": [], "role": "主角" if k == 0 else ("反派" if k == len(names) - 1 and k > 1 else "主要配角"),
            "personality": f"{n}外冷内热，遇事先观察再动手，对认定的人极护短" if k == 0 else f"{n}心思细，说话留三分，关键时刻不退",
            "speech_style": "话短，常用反问收尾" if k == 0 else "措辞客气，句子偏长",
            "catchphrases": ["少废话"] if k == 0 else [],
            "relations": [{"target": o, "relation": "生死之交" if k == 0 else "互相试探"} for o in others[:2]],
            "abilities": ["近身搏斗", "过目不忘"] if k == 0 else ["察言观色"],
            "limits": ["不会任何法术，远程手段为零"] if k == 0 else ["正面打斗不是强项"],
        })
    return _j({
        "characters": chars,
        "world": {"summary": "一个以宗门与世家共治的大陆，力量靠修炼积累，资源被少数势力把持（演示）",
                  "rules": ["境界不可越级跨两阶交手", "动用禁术必付代价"], "locations": [{"name": "主城", "desc": "各方势力交汇之地"}]},
        "factions": [{"name": "宗门", "stance": "中立偏守成", "members": names[:2], "notes": "表面公正，内部派系林立"}],
        "timeline": [{"event": f"第{part}段：{names[0]}卷入一场冲突并第一次暴露底牌", "characters": names[:2], "impact": "与对立势力结下梁子"}],
        "scenes": [{"title": f"雨夜对峙（第{part}段）", "summary": f"{names[0]}独自挡在众人前面，用一句反问逼退来人，奠定其护短形象", "characters": names[:1]}],
    })


def mock_fanfic_ooc(meta: dict[str, Any]) -> str:
    quotes = meta.get("quotes") if isinstance(meta.get("quotes"), dict) else {}
    out = []
    for k, n in enumerate([str(x) for x in meta.get("characters") or []]):
        q = str(quotes.get(n) or "")
        issues = []
        if q and k == 0:
            issues.append({"type": "speech", "severity": "mid", "quote": q, "problem": f"{n}在原著里话短，这里说得太多太软",
                           "suggestion": "删掉解释，改成一句反问"})
        out.append({"name": n, "score": 78 if issues else 92, "verdict": "基本贴合原著（演示）", "issues": issues})
    return _j({"characters": out, "summary": "整体人设贴合，个别对白偏离（演示）"})


FANFIC_HANDLERS = {
    "fanfic_source": mock_fanfic_source,
    "fanfic_ooc": mock_fanfic_ooc,
}
