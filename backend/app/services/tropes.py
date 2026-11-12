"""禁用套路：全局列表（设置里可编辑）+ 每本书追加；生成时注入提示词，生成后程序做关键词检测。

检测只是简单的关键词命中，用来提醒作者，不拦截写入。作者要求里明确点名想要的套路会从禁用列表里豁免。
"""

from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session

from app.db import kv_get

TROPES_KEY = "trope_settings"

DEFAULT_TROPES: list[dict[str, Any]] = [
    {"name": "父母失踪/神秘消失", "keywords": ["父亲失踪", "母亲失踪", "父母失踪", "父母双双失踪", "父母神秘消失", "父亲神秘消失",
                                              "母亲神秘消失", "父亲下落不明", "母亲下落不明", "父母下落不明", "父亲没死", "你父亲没死", "失踪的父亲", "失踪多年的父亲"]},
    {"name": "隐藏身世/大人物之子", "keywords": ["隐藏身世", "真实身世", "身世之谜", "大人物之子", "真实身份是", "其实是某位", "私生子", "遗孤", "流落在外的"]},
    {"name": "神秘血脉", "keywords": ["神秘血脉", "隐藏血脉", "上古血脉", "血脉觉醒", "远古血脉", "神族血脉", "血脉之力"]},
    {"name": "退婚流", "keywords": ["退婚", "悔婚", "婚约被退", "解除婚约"]},
    {"name": "被废天才/天才陨落", "keywords": ["修为被废", "被废了修为", "天才陨落", "曾经的天才", "沦为废物", "修为尽失", "丹田被废", "经脉尽断"]},
]


def _clean(items: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()[:40]
        kws = it.get("keywords") or []
        if isinstance(kws, str):
            kws = re.split(r"[，,、；;\s]+", kws)
        kws = list(dict.fromkeys(str(k).strip() for k in kws if str(k).strip()))[:40]
        if name or kws:
            out.append({"name": name or kws[0], "keywords": kws})
    return out[:40]


def global_tropes(s: Session) -> list[dict[str, Any]]:
    cfg = kv_get(s, TROPES_KEY, None)
    if not isinstance(cfg, dict) or "banned" not in cfg:
        return [dict(t, keywords=list(t["keywords"])) for t in DEFAULT_TROPES]
    return _clean(cfg.get("banned"))


def clean(items: Any) -> list[dict[str, Any]]:
    return _clean(items)


def tropes_for(s: Session, book: Any | None = None) -> list[dict[str, Any]]:
    """全局 + 本书追加（同名合并关键词）。"""
    merged: dict[str, dict[str, Any]] = {}
    for t in global_tropes(s) + _clean(getattr(book, "banned_tropes", None) or []):
        cur = merged.setdefault(t["name"], {"name": t["name"], "keywords": []})
        cur["keywords"] = list(dict.fromkeys([*cur["keywords"], *t["keywords"]]))
    return list(merged.values())


def wanted(instruction: str, t: dict[str, Any]) -> bool:
    """作者要求里明确点名想要（提到套路名或关键词，且不是“不要/别/去掉”这类否定）。"""
    ins = instruction or ""
    for w in [t["name"], *t["keywords"], *re.split(r"[/／]", t["name"])]:
        w = w.strip()
        if len(w) < 2 or w not in ins:
            continue
        i = ins.index(w)
        clause = re.split(r"[。；;！!？?\n]", ins[:i])[-1]  # 同一句里出现否定词就算“不要”
        if re.search(r"(不要|别|不用|去掉|删掉|换掉|避免|禁止|不想|少用|拿掉|不能|俗套)", clause):
            continue
        return True
    return False


def active(tropes: list[dict[str, Any]], instruction: str = "") -> list[dict[str, Any]]:
    return [t for t in tropes if not wanted(instruction, t)]


def prompt_block(tropes: list[dict[str, Any]], instruction: str = "") -> str:
    act = active(tropes, instruction)
    if not act:
        return ""
    lines = "\n".join(f"- {t['name']}（如：{'、'.join(t['keywords'][:4])}）" for t in act)
    return ("\n\n【去套路】默认不要用下面这些高频俗套（作者在要求里明确点名想要的除外）：\n" + lines +
            "\n主角的起点、动机和金手指的来源要多样：可以来自职业经验、一次意外、一件旧物、一份工作、一场交易、"
            "自己琢磨出的门道等，不要把一切归结为“父母失踪/神秘消失 → 主角其实是大人物之子/身负隐藏血脉”。")


def keywords(tropes: list[dict[str, Any]], instruction: str = "") -> list[str]:
    return [k for t in active(tropes, instruction) for k in t["keywords"]]


def detect(text: str, tropes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回命中的套路：[{name, hits:[关键词]}]。"""
    if not text:
        return []
    out = []
    for t in tropes:
        hits = [k for k in t["keywords"] if k and k in text]
        if hits:
            out.append({"name": t["name"], "hits": hits[:5]})
    return out


def detect_obj(obj: Any, tropes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import json

    return detect(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), tropes)


def replace_instruction(hits: list[dict[str, Any]]) -> str:
    names = "、".join(h["name"] for h in hits) or "高频俗套"
    words = "、".join(dict.fromkeys(w for h in hits for w in h.get("hits", [])))
    return (f"去掉这些俗套：{names}（命中：{words}）。换成更新鲜的主角起点、动机或金手指来源，"
            "其余没提到的内容尽量保留，不要再出现上面这些词。")
