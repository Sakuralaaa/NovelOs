"""v0.11 完本模式 mock：字数倒推卷纲。确定性输出，按程序给的卷区间生成。"""

from __future__ import annotations

import json
from typing import Any


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def mock_wanben_plan(meta: dict[str, Any]) -> str:
    vols = meta.get("volumes") or []
    total = int(meta.get("total_chapters") or 0)
    names = ["开局立足", "旧案浮出", "势力洗牌", "高层博弈", "终局清算", "尘埃落定"]
    out = []
    for i, v in enumerate(vols):
        start, end = int(v.get("start") or 1), int(v.get("end") or 1)
        last = i == len(vols) - 1
        out.append({
            "order": int(v.get("order") or i + 1),
            "title": v.get("title") or f"第{i + 1}卷 {names[i % len(names)]}",
            "summary": v.get("summary") or f"卷目标：主角在第{start}–{end}章里解决本卷的核心麻烦（演示）",
            "crisis": "幕后对手亮出底牌，主角腹背受敌" if last else f"第{i + 1}卷的对手把主角逼到绝路（演示）",
            "climax_chapter": max(start, end - 2),
            "closure": "主线了结，全书收束" if last else "阶段胜利到手，新的更大威胁露出一角",
        })
    return _j({
        "volumes": out,
        "finale": {"resolution": "主角当众翻开总账，终极对手认罪伏法（演示）",
                   "payoffs": ["开篇埋下的旧账来历在结局前三章回收"], "endings": ["主角守住了想守的人", "盟友各得其所"],
                   "last_chapter_beat": f"第{total}章：尘埃落定后的一个安静早晨，主角把账本合上"},
        "ending": "旧账清完，主角站到了最高处（演示）",
    })


WANBEN_HANDLERS = {"wanben_plan": mock_wanben_plan}
