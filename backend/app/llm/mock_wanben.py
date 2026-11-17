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


def mock_volume_review(meta: dict[str, Any]) -> str:
    """v0.16 卷末复盘 mock：三个走向选项，推荐第一个。"""
    v = int(meta.get("volume") or 1)
    nxt = v + 1
    opts = [
        {"title": f"第{nxt}卷 名动一城", "summary": f"主角带着第{v}卷的战果进城，卷入城中三大家族的明争暗斗（演示）",
         "crisis": "城主府设局，要主角背下灭门血案", "closure": "当众洗清冤屈，城主府倒台，更高层的势力注意到主角",
         "turns": ["新的主要角色：城主府的冷面千金登场", "金手指升级：可以同时推演两条路"], "why": "危机升级，旧仇人在城里露面"},
        {"title": f"第{nxt}卷 秘境夺宝", "summary": "秘境开启，各方天骄云集，主角要抢在仇家之前拿到传承（演示）",
         "crisis": "仇家联手堵在秘境出口", "closure": "拿到传承杀出重围，秘境深处的旧秘密露出一角",
         "turns": ["大反转：领路的前辈是幕后黑手的人"], "why": "打怪升级节奏快，爽点密"},
        {"title": f"第{nxt}卷 宗门大比", "summary": "主角报名宗门大比，一路打上擂台（演示）",
         "crisis": "大比被人做了手脚，主角的对手全是硬茬", "closure": "大比夺魁，被长老收为亲传",
         "turns": ["感情线定调：师姐站到主角一边"], "why": "擂台打脸，读者熟悉的爽点"},
    ]
    return _j({
        "recap": f"第{v}卷前情：主角从被人看不起到一战成名，拿到了第一份真正的底牌；和旧仇人彻底撕破脸，结识了第一个可靠的盟友。（演示）",
        "state": ["主角：境界突破一层，身份从外门杂役变成内门弟子（演示）", "关键物品：残破玉佩已认主（演示）"],
        "problems": ["本卷后半段连续三章都是打脸型爽点，下一卷换换花样（演示）"],
        "options": opts, "recommended": 0,
        "later": [],
    })


WANBEN_HANDLERS = {"wanben_plan": mock_wanben_plan, "volume_review": mock_volume_review}
