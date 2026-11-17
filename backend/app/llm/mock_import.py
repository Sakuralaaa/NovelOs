"""v0.12 E1 导入已有作品 / 接管旧书 / 大纲导入 的 mock（演示模式）。确定性输出，只用程序传来的 meta。

本模块被 app.services.import_book 导入时把处理函数注册进 mock.HANDLERS，并补上任务 → 角色、任务 → 规则包的映射，
不改共享文件（mock.py / gateway.py / loader.py）。
"""

from __future__ import annotations

import json
import re
from typing import Any


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[。！？!?])", re.sub(r"\s+", "", text or "")) if len(x) >= 4]


def mock_adopt_bible(meta: dict[str, Any]) -> str:
    existing = set(meta.get("existing") or [])
    names = [n for n in (meta.get("names") or [])]
    start = int(meta.get("start") or 1)
    cards: list[dict[str, Any]] = []
    for i, n in enumerate(names[:4]):
        role = "protagonist" if i == 0 and not existing else "other"
        cards.append({"action": "update" if n in existing else "add", "target": n if n in existing else "", "type": "character", "name": n,
                      "summary": f"第{start}章前后反复出场的人物（演示：从正文里按出场次数识别）",
                      "data": {"role": role, "first_chapter": start, "identity": "（演示）待作者补充"}, "known_by": []})
    if "故事世界（导入反推）" not in existing:
        cards.append({"action": "add", "type": "world", "name": "故事世界（导入反推）",
                      "summary": f"根据第{start}章起的正文整理的时代与环境（演示）", "data": {}, "known_by": []})
    return _j({"cards": cards})


def mock_adopt_ledger(meta: dict[str, Any]) -> str:
    n = int(meta.get("number") or 1)
    known = set(meta.get("known") or [])
    names = list(meta.get("names") or [])
    content = str(meta.get("content") or "")
    sents = _sentences(content)
    new = [{"type": "character", "name": x, "summary": f"第{n}章登场（演示）"} for x in names[:2] if x not in known]
    states = []
    who = names[0] if names else None
    if who:
        line = next((s for s in sents if who in s), sents[0] if sents else "")
        states.append({"entity": who, "key": "处境", "value": (line[:40] or f"第{n}章的处境（演示）"), "visibility": "reader"})
    fs: list[dict[str, Any]] = []
    opens = list(meta.get("open_foreshadows") or [])
    if opens:
        oldest = min(opens, key=lambda f: int(f.get("planted_ch") or 0))
        fs.append({"action": "resolve" if n % 10 == 0 else "advance", "id": oldest.get("id"), "desc": oldest.get("desc", "")})
    if n % 5 == 1 and sents:
        fs.append({"action": "plant", "id": None, "desc": f"第{n}章留下的疑点：{sents[-1][:24]}（演示）"})
    return _j({"new_entities": new, "state_changes": states, "foreshadow": fs})


def mock_adopt_outline(meta: dict[str, Any]) -> str:
    out = []
    names = list(meta.get("names") or [])
    pt = ["打脸", "危机化解", "真相揭示", "收获升级", "关系突破"]
    ht = ["悬念反转", "信息缺口", "危机突降", "决定", "发现"]
    oc = ["yes-but", "no-and", "yes", "yes-but", "no"]
    em = ["up", "down", "flat"]
    for i, c in enumerate(meta.get("chapters") or []):
        n = int(c.get("number") or i + 1)
        summ = re.sub(r"\s+", "", str(c.get("summary") or ""))
        first = (_sentences(summ) or [summ])[0][:60]
        out.append({"number": n, "goal": first or f"第{n}章的主线推进（演示）", "conflict": "（演示）阻力来自对手或环境",
                    "outcome": oc[n % len(oc)], "payoff": "（演示）本章的满足点", "payoff_type": pt[n % len(pt)],
                    "payoff_level": "combo" if n % 5 == 0 else "small", "strand": ["quest"] if n % 3 else ["quest", "fire"],
                    "emotion": em[n % 3], "characters": names[:2], "location": "",
                    "expectation": "（演示）读者想知道接下来怎么收场", "hook_end": str(c.get("tail") or "")[-40:] or "章末悬念（演示）",
                    "hook_type": ht[n % len(ht)]})
    nums = [x["number"] for x in out]
    return _j({"arc": {"title": "旧章回顾", "summary": f"第{min(nums) if nums else 0}–{max(nums) if nums else 0}章的剧情段（演示）"},
               "chapters": out})


def mock_outline_import(meta: dict[str, Any]) -> str:
    parsed = meta.get("parsed") or {"book": {"summary": ""}, "volumes": []}
    return _j({"book": parsed.get("book") or {"summary": ""}, "volumes": parsed.get("volumes") or []})


IMPORT_HANDLERS = {
    "adopt_bible": mock_adopt_bible,
    "adopt_ledger": mock_adopt_ledger,
    "adopt_outline": mock_adopt_outline,
    "outline_import": mock_outline_import,
}
IMPORT_ROLES = {"adopt_bible": "planner", "adopt_ledger": "planner", "adopt_outline": "planner", "outline_import": "planner"}
IMPORT_SKILLS: dict[str, tuple[str, ...]] = {"adopt_bible": ("bible",), "adopt_ledger": ("bible",), "adopt_outline": ("outline",),
                                             "outline_import": ("outline",)}


def register() -> None:
    from app.llm import gateway, mock
    from app.skills import loader

    for k, v in IMPORT_HANDLERS.items():
        mock.HANDLERS.setdefault(k, v)
    for k, v in IMPORT_ROLES.items():
        gateway.TASK_ROLE.setdefault(k, v)
    for k, v in IMPORT_SKILLS.items():
        loader.TASK_SKILLS.setdefault(k, v)
