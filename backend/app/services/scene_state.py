"""场景状态账本（v0.6）。

问题：正文按场景逐个生成，旧版每个场景只看到上一场景末尾 200 字，看不到“谁站在哪、面朝哪、手里拿着什么、穿什么、
身上什么伤/义体什么状态”。于是道具会瞬移（反派一直拿着的合同突然出现在柜台上）、服装会变（皮鞋 → 金属脚掌）、
角度会变（对折成钝角 → 弯成九十度）、朝向会错（本就面朝门外却“转过身来迎着门外”）。

做法（思路参考 Narcooo/inkos 的“物理状态/资源”事实抽取与 fuxiangxu/novel-ops 的 character-state 逐章追踪，均为 idea-only；
r/WritingWithAI 社区“把未解决的线索当作显式状态逐场传下去”的经验；实现为本项目自写）：
1. 每个场景写完，模型在 ---STATE--- 后输出本场景结束时的状态 JSON；
2. 程序校验、合并成账本，原样注入下一个场景的提示词；
3. 程序比对前后账本：道具换了位置/持有人，但这一场正文里根本没提到这个道具 → 记“道具凭空移动”警告；
4. 同时把本章已写正文（而不是 200 字尾巴）交给下一个场景，并按已写内容计算“口头禅/群众镜头/强化词”剩余额度。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.lint.craft_zh import CATCHPHRASE_MAX, CROWD_SHOTS_MAX
from app.lint.humanlint import count_words, crowd_shot_paragraphs, intensifier_report

STATE_MARKER = "---STATE---"
CHANGES_MARKER = "---CHANGES---"
MAX_CAST, MAX_PROPS = 8, 10
SO_FAR_BUDGET = 6000  # 本章已写正文注入上限（字）；网文单章 2000–3000 字，通常整章都能放下

STATE_SCHEMA_HINT = (
    '{"cast":[{"name":"人物","position":"具体位置（门槛内/柜台后/台阶下第二级）","facing":"面朝哪边",'
    '"holding":["手里或身上带着的东西（在哪只手/哪个兜）"],"wearing":"衣着鞋子装备","body":"伤势、义体、体力等身体状态"}],'
    '"props":[{"name":"道具","where":"此刻在哪/在谁手里","state":"外观与状态（硬壳/折了/弯成多少度/亮着）"}],'
    '"env":"光线、时间、车辆等会影响下一场的环境事实"}'
)


# ------------------------------------------------------------------ 拆分与解析

def split_scene_output(text: str) -> tuple[str, str | None, str | None]:
    """拆成（正文, 状态 JSON 原文, 变更 JSON 原文）。两个标记顺序不限，各取最后一次出现。"""
    marks = []
    for name, mk in (("state", STATE_MARKER), ("changes", CHANGES_MARKER)):
        i = text.rfind(mk)
        if i != -1:
            marks.append((i, name, mk))
    if not marks:
        return text.strip(), None, None
    marks.sort()
    body = text[: marks[0][0]].strip()
    seg: dict[str, str] = {}
    for k, (i, name, mk) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        seg[name] = text[i + len(mk): end].strip()
    return body, seg.get("state"), seg.get("changes")


def _json_obj(raw: str) -> Any:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    a, b = t.find("{"), t.rfind("}")
    return json.loads(t[a: b + 1] if a != -1 and b > a else t)


def _prop_name(v: Any) -> str:
    """模型常把账本里的「道具·xxx」整段抄回来，去掉前缀，避免同一道具被当成两件。"""
    t = _s(v, 40)
    while t.startswith(("道具·", "道具:", "道具：")):
        t = t[3:].strip()
    return t[:20]


def _s(v: Any, n: int = 60) -> str:
    if isinstance(v, (list, tuple)):
        v = "、".join(str(x) for x in v if x)
    return str(v or "").strip()[:n]


def normalize_scene_state(data: Any) -> dict[str, Any]:
    """宽松接收模型给的状态，规范成 {cast, props, env}；字段过长截断，条数封顶。"""
    out: dict[str, Any] = {"cast": [], "props": [], "env": ""}
    if not isinstance(data, dict):
        return out
    cast = data.get("cast") or data.get("characters") or []
    for c in cast if isinstance(cast, list) else []:
        if not isinstance(c, dict) or not _s(c.get("name")):
            continue
        holding = c.get("holding") or c.get("items") or []
        if isinstance(holding, str):
            holding = [x for x in re.split(r"[、，,；;]", holding) if x.strip()]
        out["cast"].append({
            "name": _s(c.get("name"), 20),
            "position": _s(c.get("position") or c.get("where")),
            "facing": _s(c.get("facing"), 30),
            "holding": [_s(x, 40) for x in holding][:5] if isinstance(holding, list) else [],
            "wearing": _s(c.get("wearing") or c.get("outfit")),
            "body": _s(c.get("body") or c.get("injury")),
        })
    props = data.get("props") or data.get("items") or []
    for p in props if isinstance(props, list) else []:
        if not isinstance(p, dict) or not _prop_name(p.get("name")):
            continue
        out["props"].append({"name": _prop_name(p.get("name")), "where": _s(p.get("where") or p.get("location")),
                             "state": _s(p.get("state"))})
    out["cast"], out["props"] = out["cast"][:MAX_CAST], out["props"][:MAX_PROPS]
    out["env"] = _s(data.get("env") or data.get("environment"), 120)
    return out


def parse_scene_state(raw: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if raw is None:
        return None, ["场景没有给出 ---STATE--- 结束状态，沿用上一场景的账本"]
    try:
        st = normalize_scene_state(_json_obj(raw))
    except (json.JSONDecodeError, ValueError):
        return None, ["场景结束状态不是合法 JSON，沿用上一场景的账本"]
    if not st["cast"] and not st["props"]:
        return None, ["场景结束状态为空，沿用上一场景的账本"]
    return st, []


def merge_state(prev: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """新状态覆盖同名条目；上一场有、这一场没提到的人物/道具原样保留（他们还在原处）。"""
    base = normalize_scene_state(prev or {})
    if not new:
        return base
    cast = {c["name"]: c for c in base["cast"]}
    for c in new.get("cast") or []:
        old = cast.get(c["name"], {})
        cast[c["name"]] = {**old, **{k: v for k, v in c.items() if v not in ("", [], None)}}
    props = {p["name"]: p for p in base["props"]}
    for p in new.get("props") or []:
        old = props.get(p["name"], {})
        props[p["name"]] = {**old, **{k: v for k, v in p.items() if v not in ("", None)}}
    return {"cast": list(cast.values())[:MAX_CAST], "props": list(props.values())[:MAX_PROPS],
            "env": new.get("env") or base.get("env", "")}


def render_state(state: dict[str, Any] | None, title: str) -> str:
    st = normalize_scene_state(state or {})
    lines: list[str] = []
    for c in st["cast"]:
        bits = [f"位置：{c['position']}" if c["position"] else "", f"朝向：{c['facing']}" if c["facing"] else "",
                f"手持/随身：{'、'.join(c['holding'])}" if c["holding"] else "", f"穿着：{c['wearing']}" if c["wearing"] else "",
                f"身体：{c['body']}" if c["body"] else ""]
        lines.append(f"- {c['name']}｜" + "；".join(b for b in bits if b))
    for p in st["props"]:
        lines.append(f"- 道具·{p['name']}｜在：{p['where'] or '未写明'}" + (f"；状态：{p['state']}" if p["state"] else ""))
    if st["env"]:
        lines.append(f"- 环境｜{st['env']}")
    if not lines:
        return f"【{title}】\n（本章开头，还没有账本：道具第一次出现时写清它在谁手里、什么样子）"
    return f"【{title}】\n" + "\n".join(lines)


def prop_move_warnings(prev: dict[str, Any] | None, new: dict[str, Any] | None, body: str, scene_index: int) -> list[str]:
    """道具的位置或持有人变了，但这一场正文里没写到这个道具 → 疑似凭空移动。"""
    if not prev or not new:
        return []
    old = {p["name"]: p for p in (prev.get("props") or [])}
    warns: list[str] = []
    for p in new.get("props") or []:
        o = old.get(p["name"])
        if not o or not o.get("where") or not p.get("where") or o["where"] == p["where"]:
            continue
        if p["name"] not in body:
            warns.append(f"第 {scene_index} 场：道具「{p['name']}」从「{o['where']}」变到「{p['where']}」，正文里没写怎么过去的（疑似凭空移动）")
    return warns


# ------------------------------------------------------------------ 本章已写正文与剩余额度

def chapter_so_far(texts: list[str], budget: int = SO_FAR_BUDGET) -> str:
    if not texts:
        return "（本章开头）"
    joined = "\n\n".join(texts)
    return joined if len(joined) <= budget else "…" + joined[-budget:]


def scene_budget_lines(texts: list[str], scene_chars: list[str], voices: dict[str, dict[str, Any]]) -> list[str]:
    """按本章已写内容计算剩余额度：口头禅（每人每章 ≤2）、群众反应镜头（≤3）、已用够的强化词。"""
    so_far = "\n\n".join(texts)
    lines: list[str] = []
    for name, v in voices.items():
        if scene_chars and name not in scene_chars:
            continue
        for ph in v.get("catchphrases") or []:
            key = re.sub(r"[，,。！？!?、…\s“”\"]+", "", str(ph))
            if not key:
                continue
            used = so_far.count(key)
            left = max(0, CATCHPHRASE_MAX - used)
            lines.append(f"{name}的口头禅「{key}」本章已用 {used} 次，" + ("本场景不要再用" if left == 0 else f"本场景最多再用 {min(left, 1)} 次，不用也行"))
    crowd = len(crowd_shot_paragraphs(so_far)) if so_far else 0
    lines.append(f"群众/配角反应镜头本章已用 {crowd}/{CROWD_SHOTS_MAX}" + ("，本场景不要再切围观者反应" if crowd >= CROWD_SHOTS_MAX else ""))
    if so_far and count_words(so_far) > 200:
        used_up = [d["word"].split("（")[0] for d in intensifier_report(so_far) if d["count"] >= 2]
        if used_up:
            lines.append("这些词本章已经用够，本场景不要再出现：" + "、".join(used_up))
    return lines


# ------------------------------------------------------------------ 场景级硬规则（程序按章号与节拍拼出来）

def scene_rules(number: int, idx: int, total: int, scene: dict[str, Any], beats: dict[str, Any], pov: str | None) -> list[str]:
    rules: list[str] = []
    if idx == 1 and number <= 3:
        hook = scene.get("opening") or beats.get("opening_hook") or beats.get("conflict") or ""
        rules.append(f"开篇硬指标：正文前三行（前三段）必须已经出现冲突或异常（{hook}）。环境描写只能附着在人物动作上，不能单独占一段。")
    if scene.get("cheat"):
        rules.append(f"卖点露出：本场景必须让金手指露一次读者能感知的苗头：{scene['cheat']}。写成具体反馈（数字、提示、身体感受或一次小收益），一两句，不解释原理。")
    who = pov or "视点主角"
    rules.append(f"代入感：{who}在本场景至少有一处 1–2 句的简短内心（判断、算计或情绪），夹在动作之间；不写超过 3 句的独白。")
    if idx == total:
        main = scene.get("main_hook") or beats.get("hook_end") or ""
        rules.append(f"章末只留 1 个主钩（{main}）+ 至多 1 个副钩，断在主钩那一刻；不要再追加第三个悬念或预告。")
    else:
        rules.append("本场景结尾留一个推动下一场的小悬念即可，不要提前写章末钩子。")
    return rules
