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


def mock_fanfic_idea(meta: dict[str, Any]) -> str:
    """v0.16 创作想法 AI 重写 mock：把几段想法拧成一段立意（演示）。"""
    work = meta.get("work") or "原著"
    first = next((x.strip() for x in str(meta.get("text") or "").split("\n") if x.strip()), "")
    ins = str(meta.get("instruction") or "").strip()
    return (f"主角以原创身份切入《{work}》开篇，带着一个只有他知道的秘密混进主角团。" + (f"（起点：{first[:40]}）" if first else "") + "\n\n"
            "他不抢原著主角的风头，而是在几场关键战斗里换了打法，把原本输掉的局一点点扳回来，人物关系也跟着重新洗牌。\n\n"
            "长线目标是查清原著里没说透的一桩旧案，对手是藏在幕后的那位大人物；每一卷都有一次明面上的胜利，暗线一步步逼近真相。"
            + (f"\n\n（按要求：{ins[:60]}）" if ins else "") + "（演示）")


def mock_fanfic_entries(meta: dict[str, Any]) -> str:
    cat, sub, work = str(meta.get("cat") or "world"), str(meta.get("sub") or ""), str(meta.get("work") or "原著")
    have = set(meta.get("have") or [])
    subs = {"world": ["力量体系", "关键物品", "组织势力", "地理地点"], "character": ["主要配角"], "timeline": ["剧情时间线"], "relation": ["同伴"]}[cat] if cat in ("world", "character", "timeline", "relation") else ["其他设定"]
    out = []
    for i in range(int(meta.get("count") or 8)):
        name = f"{work}{(sub or subs[i % len(subs)])}条目{i + 1}（演示）"
        if cat == "relation":
            name = f"角色{i + 1} — 角色{i + 2}（演示）"
        if name in have:
            continue
        out.append({"sub": sub or subs[i % len(subs)], "name": name, "summary": "演示条目：一句话要点", "detail": "演示条目的展开说明：来历、规则与限制。",
                    "tags": [], "order": i + 1})
    return _j({"entries": out})


FANFIC_HANDLERS = {
    "fanfic_entries": mock_fanfic_entries,
    "fanfic_idea": mock_fanfic_idea,
    "fanfic_source": mock_fanfic_source,
    "fanfic_ooc": mock_fanfic_ooc,
}
