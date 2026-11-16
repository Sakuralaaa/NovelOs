"""正文流水线（确定性编排：代码控制流程，LLM 只做生成与判断）。

write-next：
  取下一章细纲（必要时滚动展开）→ 场景节拍（3–6）→ 组 Context Pack → 逐场景生成（末场景附 ---CHANGES---）
  → 解析/校验变更、对照底账、出场守卫 → 证据式审稿 → 人味 lint
  → 多版本时每版各跑一遍，按设置自动采纳或等作者 adopt
  → 若有 high issue 或 lint 超阈值：定点重写/描写增厚，最多 1 轮 → 复审复检
  → 通过且开启自动提交：原子提交（章节、facts、伏笔、摘要、新实体一个事务）；否则留作草稿等作者确认。
生成结果在提交前只是草稿，不落入事实底账。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session, select

from app.services.research import research_notes
from app.config import get_settings
from app.db import kv_get, session_scope
from app.jobs.manager import JobContext, register_resumable
from app.lint.humanlint import LintResult, count_words, lint_chapter, paragraphs, sentence_stats
from app.lint.platform import get_profile, thresholds_for
from app.llm.gateway import get_gateway
from app.llm.mock import kit_for
from app.models.tables import Book, Card, Chapter, Fact, Foreshadow, OutlineNode, utcnow
from app.services import common
from app.services.changes import ChangeSet, check_against_ledger, match_foreshadow, parse_changes, split_output
from app.services.common import Conflict, NotFound
from app.services.context import ContextPack, build_context_pack, scene_plan_context
from app.services.refs import refs_block
from app.services.outline import ensure_next_chapter_node, ensure_opening_beats, node_plan_text
from app.services.scene_state import (
    STATE_SCHEMA_HINT, chapter_so_far, merge_state, parse_scene_state, prop_move_warnings, render_state, scene_budget_lines,
    scene_rules, split_scene_output,
)
from app.services.review import apply_patches, pre_commit_targets, run_review
from app.skills.loader import render, system_prompt

WRITING_SETTINGS_KEY = "writing_settings"
DEFAULT_WRITING_SETTINGS: dict[str, Any] = {
    "auto_adopt_best": False, "auto_commit": True, "default_variants": 1,
    # v0.9.4：提交前自动修 continuity/retention 类 mid 问题；自动应用审稿补丁后重审一次
    "fix_mid_before_commit": True, "auto_rereview": True,
}
BOOK_SWITCHES = ("fix_mid_before_commit", "auto_rereview")  # v0.9.4 可按书覆盖的开关
OUTCOMES = ("yes", "no", "yes-but", "no-and")
MIN_SCENES, MAX_SCENES = 3, 6
PAYOFF_PHASES = ("setup", "delivery", "aftermath")  # 爽点三段：铺垫 / 兑现 / 余韵


def planned_foreshadow_gaps(beats: dict[str, Any], cs: ChangeSet) -> list[str]:
    """细纲要求的伏笔动作，变更声明里没有对应条目 → 警告（作者核对正文是否真的写到了）。"""
    warns: list[str] = []
    declared = [(f.action, f.desc, f.id) for f in cs.foreshadow]
    for f in beats.get("foreshadow") or []:
        act, desc, fid = f.get("action"), str(f.get("desc", "")), f.get("id")
        if act not in ("plant", "advance", "resolve"):
            continue
        hit = any(a == act and ((fid is not None and i == fid) or (desc and d and (desc in d or d in desc)))
                  for a, d, i in declared)
        if not hit:
            label = {"plant": "埋下", "advance": "推进", "resolve": "回收"}[act]
            warns.append(f"细纲要求{label}伏笔「{desc}」，但变更声明里没有这一项：确认正文是否写到")
    return warns


def writing_settings(s: Session) -> dict[str, Any]:
    return {**DEFAULT_WRITING_SETTINGS, **(kv_get(s, WRITING_SETTINGS_KEY, {}) or {})}


def book_writing_key(book_id: int) -> str:
    return f"book_writing:{book_id}"


def book_writing_overrides(s: Session, book_id: int) -> dict[str, Any]:
    """v0.9.4 书级开关（存 KV，不改 Book 表）：{fix_mid_before_commit, auto_rereview}，值为 null 表示跟随全局。"""
    raw = kv_get(s, book_writing_key(book_id), {}) or {}
    return {k: (raw.get(k) if isinstance(raw.get(k), bool) else None) for k in BOOK_SWITCHES}


def effective_writing_settings(s: Session, book_id: int | None) -> dict[str, Any]:
    """全局写作设置 + 书级覆盖（书级为 null 时跟随全局）。"""
    eff = writing_settings(s)
    if book_id:
        for k, v in book_writing_overrides(s, book_id).items():
            if v is not None:
                eff[k] = v
    return eff


# ------------------------------------------------------------------ lint 辅助

def lint_for(s: Session, book_id: int, content: str, number: int, exclude_chapter_id: int | None = None) -> LintResult:
    others = [c.content for c in common.committed_chapters(s, book_id) if c.id != exclude_chapter_id]
    cards = common.cards(s, book_id)
    names = [c.name for c in cards]
    cps = {c.name: common.voice_of(c)["catchphrases"] for c in cards if c.type == "character" and (c.data or {}).get("catchphrases")}
    return lint_chapter(content, get_settings().lint, others, names, number, catchphrases=cps, platform=book_platform(s, book_id),
                        ledger=numeric_ledger(s, book_id, number, cards))


_CARD_NUM_KEYS = {"age": "年龄", "年龄": "年龄", "年纪": "年龄", "height": "身高", "身高": "身高", "weight": "体重", "体重": "体重",
                  "realm": "境界", "level": "境界", "境界": "境界", "修为": "修为", "高度": "高度", "重量": "重量", "功率": "功率",
                  "时速": "时速", "长度": "长度"}


def numeric_ledger(s: Session, book_id: int, number: int, cards: list[Card] | None = None) -> list[dict[str, Any]]:
    """v0.9.4 数值一致性对照用：本章之前仍有效的事实账本 + 设定卡里的数值字段（年龄/身高/体重/境界/机甲参数…）。"""
    cards = cards if cards is not None else common.cards(s, book_id)
    by_id = {c.id: c.name for c in cards}
    out: list[dict[str, Any]] = []
    prev = max(0, int(number or 0) - 1)
    for f in s.exec(select(Fact).where(Fact.book_id == book_id, Fact.from_chapter <= prev)):
        if f.to_chapter is not None and f.to_chapter < prev:
            continue
        name = by_id.get(f.entity_id)
        if name:
            out.append({"entity": name, "key": f.key, "value": f.value, "source": f"事实账本·{f.key}（第{f.from_chapter}章起）"})
    for c in cards:
        for k, v in (c.data or {}).items():
            key = _CARD_NUM_KEYS.get(str(k))
            if key and isinstance(v, (str, int, float)) and str(v).strip():
                out.append({"entity": c.name, "key": key, "value": str(v), "source": f"设定卡·{key}"})
    return out


def book_platform(s: Session, book_id: int) -> str:
    """书的平台风格档（v0.9）：fanqie 默认 / qidian / generic；v0.11 加 duanju（短剧分镜）。"""
    b = s.get(Book, book_id)
    ps = getattr(b, "platform_style", None) if b else None
    return ps if ps in ("fanqie", "qidian", "generic", "duanju") else "fanqie"


def book_thresholds(s: Session, book_id: int) -> Any:
    return thresholds_for(get_settings().lint, book_platform(s, book_id))


# ------------------------------------------------------------------ 场景节拍

def normalize_scenes(raw: Any, beats: dict[str, Any], sensory_pool: list[str], number: int | None = None) -> list[dict[str, Any]]:
    items = raw.get("scenes") if isinstance(raw, dict) else raw
    scenes: list[dict[str, Any]] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        sc = {
            "goal": str(it.get("goal", "")),
            "conflict": str(it.get("conflict", "")),
            "outcome": it.get("outcome") if it.get("outcome") in OUTCOMES else "yes-but",
            "characters": [str(c) for c in (it.get("characters") or beats.get("characters") or [])],
            "sensory": str(it.get("sensory") or (sensory_pool[len(scenes) % len(sensory_pool)] if sensory_pool else "")),
        }
        # 可选：这场戏结束时改变了什么（信息/关系/计划/风险/权力/情绪）、在爽点里承担的位置、给读者的悬念
        if it.get("turn"):
            sc["turn"] = str(it["turn"])[:120]
        if it.get("payoff_phase") in PAYOFF_PHASES:
            sc["payoff_phase"] = it["payoff_phase"]
        if it.get("exit_hook"):
            sc["exit_hook"] = str(it["exit_hook"])[:120]
        if it.get("relations"):
            sc["relations"] = str(it["relations"])[:120]
        if it.get("cheat"):
            sc["cheat"] = str(it["cheat"])[:160]
        scenes.append(sc)
    scenes = scenes[:MAX_SCENES]
    while len(scenes) < MIN_SCENES:
        scenes.append({"goal": beats.get("goal", ""), "conflict": beats.get("conflict", ""), "outcome": "yes-but",
                       "characters": list(beats.get("characters") or []), "sensory": sensory_pool[len(scenes) % len(sensory_pool)] if sensory_pool else ""})
    # 连续 3 个 yes 视为节奏塌陷：中间那个改成 yes-but
    for i in range(2, len(scenes)):
        if all(scenes[j]["outcome"] == "yes" for j in (i - 2, i - 1, i)):
            scenes[i - 1]["outcome"] = "yes-but"
    # 末场景承接章结果
    if beats.get("outcome") in OUTCOMES:
        scenes[-1]["outcome"] = beats["outcome"]
    return enforce_scene_rules(scenes, beats, number)


def enforce_scene_rules(scenes: list[dict[str, Any]], beats: dict[str, Any], number: int | None) -> list[dict[str, Any]]:
    """v0.6 程序兜底：
    - 第 1–3 章：第一个场景带 opening（前三行冲突/异常）；
    - 细纲有 cheat_beat（第 1 章必有）而没有任何场景认领 → 挂到兑现场景（没有就挂第 2 个场景）；
    - 章末钩子只由最后一个场景承担：去掉它的 exit_hook，换成 main_hook = 细纲 hook_end，避免场景钩 + 章末钩叠成三个。
    """
    if not scenes:
        return scenes
    n = int(number or beats.get("number") or 0)
    if n and n <= 3 and beats.get("opening_hook"):
        scenes[0].setdefault("opening", str(beats["opening_hook"])[:160])
    cb = str(beats.get("cheat_beat") or "").strip()
    if cb and not any(sc.get("cheat") for sc in scenes):
        target = next((sc for sc in scenes if sc.get("payoff_phase") == "delivery"), scenes[min(1, len(scenes) - 1)])
        target["cheat"] = cb[:160]
    last = scenes[-1]
    last.pop("exit_hook", None)
    if beats.get("hook_end"):
        last["main_hook"] = str(beats["hook_end"])[:160]
    return scenes


def _sensory_pool(s: Session, book: Book) -> list[str]:
    pool: list[str] = []
    for c in common.cards(s, book.id or 0, "location"):
        sen = (c.data or {}).get("sensory")
        if sen:
            pool.extend([x for x in re.split(r"[，,；;]", str(sen)) if x.strip()])
    pool.extend(kit_for(book.genre, book.gender)["sensory"])
    return pool


def scene_plan_rules(beats: dict[str, Any], number: int) -> str:
    """拆场景时的程序附加要求（按章号与细纲拼）。"""
    lines: list[str] = []
    if number <= 3:
        lines.append(f"第一个场景的第一拍就是冲突或异常：{beats.get('opening_hook') or beats.get('conflict') or ''}。不要用环境描写开场。")
    if beats.get("cheat_beat"):
        lines.append(f"金手指/卖点必须在某个场景露出可感知的苗头（优先放在兑现场景），在那个场景的 JSON 里写 \"cheat\"：{beats['cheat_beat']}")
    lines.append("群众/配角反应镜头全章不超过 3 个，只放在兑现和余韵场景。")
    lines.append("只有最后一个场景承接章末钩子；其它场景的 exit_hook 只是推动下一场的小悬念。")
    lines.append("有新人物出场或关系容易误读时，在 relations 里写清他和视点人物的关系与称呼依据（如：被清退的前学员，还没入门，叫“叶馆主”不叫“师父”）。")
    return "\n".join(f"- {x}" for x in lines)


# ------------------------------------------------------------------ 生成一版

def build_scene_user(
    pack: ContextPack, number: int, node_title: str, plan: str, sc: dict[str, Any], i: int, total: int, per: int,
    texts: list[str], state: dict[str, Any] | None, beats: dict[str, Any],
) -> str:
    """组一个场景的 user 提示词：动态上下文 + 本章已写正文 + 状态账本 + 剩余额度 + 场景硬规则。纯函数，便于测试。"""
    last = i == total
    output_instruction = (
        f"正文写完后另起一行写 {STATE_MARKER_TEXT}，给出本场景结束时的状态 JSON：{STATE_SCHEMA_HINT}\n"
        "只写在场或刚离场的人物与本场出现过的道具；位置、朝向、手持物、穿着、身体都按正文最后一刻填写。"
    )
    if last:
        output_instruction += "\n这是本章最后一个场景：状态 JSON 之后再另起一行写 ---CHANGES---，给出覆盖全章的变更声明 JSON。"
    else:
        output_instruction += "\n不要写 ---CHANGES---。"
    state_title = "上一场景结束时的状态账本（本场景开头必须与此一致；道具只能被正文里写出来的动作移动）" if texts else \
        "上一章结束时的状态账本（本章第一个场景从这里接）"
    budget = scene_budget_lines(texts, sc.get("characters") or [], pack.voices)
    rules = scene_rules(number, i, total, sc, beats, pack.protagonist)
    return pack.suffix + "\n\n" + render(
        "writing_scene", number=number, chapter_title=node_title, scene_index=i, scene_total=total,
        scene_words=per, chapter_plan=plan, scene=json.dumps(sc, ensure_ascii=False),
        chapter_so_far=chapter_so_far(texts), state_block=render_state(state, state_title),
        budget="\n".join(f"- {x}" for x in budget) or "- 无", scene_rules="\n".join(f"- {x}" for x in rules),
        output_instruction=output_instruction,
    )


STATE_MARKER_TEXT = "---STATE---"


def _write_variant(
    pack: ContextPack, meta: dict[str, Any], node_title: str, number: int, plan: str,
    scenes: list[dict[str, Any]], chapter_words: int, variant: int, ctx: JobContext, pct: tuple[int, int],
    partial: dict[str, Any] | None = None, on_scene: Any = None,
) -> dict[str, Any]:
    """逐场景生成一版正文。每个场景都看到：本章已写正文、上一场景结束时的状态账本、口头禅/群众镜头/强化词剩余额度。

    v0.9.4：partial 为断点（{texts, states, state, warnings}）时从下一个场景接着写；on_scene(partial) 在每个场景写完后回调（存断点）。
    返回 {content, raw_changes, scene_states, end_state, warnings}。
    """
    gw = get_gateway()
    total = len(scenes)
    per = max(300, chapter_words // total)
    beats = meta.get("beats") or {}
    texts: list[str] = list((partial or {}).get("texts") or [])
    raw_changes: str | None = None
    state: dict[str, Any] | None = (partial or {}).get("state") if partial and texts else pack.opening_state
    states: list[dict[str, Any]] = list((partial or {}).get("states") or [])
    warns: list[str] = list((partial or {}).get("warnings") or [])
    for i, sc in enumerate(scenes, 1):
        if i <= len(texts):  # 断点里已写完的场景
            continue
        ctx.progress(pct[0] + (pct[1] - pct[0]) * (i - 1) // total, f"第{number}章 版本{variant + 1}：写第 {i}/{total} 个场景")
        last = i == total
        user = build_scene_user(pack, number, node_title, plan, sc, i, total, per, texts, state, beats)
        out = gw.chat(
            "writing_scene",
            [{"role": "system", "content": pack.prefix}, {"role": "user", "content": user}],
            meta={**meta, "scene": sc, "scene_index": i, "scene_total": total, "scene_words": per,
                  "variant": variant, "include_changes": last, "prev_state": state},
            temperature=0.9,
        )
        body, raw_state, raw = split_scene_output(out)
        if last:
            raw_changes = raw
        body = _clean_scene(body)
        new_state, w = parse_scene_state(raw_state)
        warns += [f"第 {i} 场：{x}" for x in w]
        warns += prop_move_warnings(state, new_state, body, i)
        state = merge_state(state, new_state)
        states.append(state)
        texts.append(body)
        if on_scene is not None and not last:
            on_scene({"variant": variant, "texts": list(texts), "states": list(states), "state": state, "warnings": list(warns)}, i, total)
    return {"content": "\n\n".join(texts), "raw_changes": raw_changes, "scene_states": states,
            "end_state": state, "warnings": warns}


def _clean_scene(text: str) -> str:
    t = re.sub(r"^\s*(#+.*|场景[一二三四五六0-9]+[:：].*)\n", "", text.strip())
    return t.strip()


def _evaluate(
    s: Session, book: Book, pack: ContextPack, content: str, number: int, plan: str, meta: dict[str, Any],
    exclude_chapter_id: int | None,
) -> tuple[dict[str, Any], LintResult, int]:
    lint = lint_for(s, book.id or 0, content, number, exclude_chapter_id)
    # v0.9.4：数值一致性 lint 的问题进审稿结果（mid / continuity，带位置）
    review, dropped = run_review(get_gateway(), content, number, plan, pack.protagonist, pack.required_chars, meta,
                                 context=pack.state_text, cheat_terms=pack.cheat_terms,
                                 extra_issues=list(lint.numeric_issues or []) + _fanfic_issues(s, book, content, exclude_chapter_id))
    return review, lint, dropped


def _fanfic_issues(s: Session, book: Book, content: str, chapter_id: int | None) -> list[dict[str, Any]]:
    """v0.10：同人书的 OOC/原著重合问题并进审稿（原创书为空，失败不影响审稿）。"""
    if not getattr(book, "fanfic", None):
        return []
    try:
        from types import SimpleNamespace
        from app.models.tables import Chapter as _Ch
        from app.services import fanfic
        ch = s.get(_Ch, chapter_id) if chapter_id else None
        stub = ch or SimpleNamespace(book_id=book.id, content=content, fanfic_meta={})
        return fanfic.ooc_block(s, stub, content)
    except Exception:  # noqa: BLE001
        return []


def _variant_score(v: dict[str, Any]) -> tuple[int, float]:
    return (int(v.get("review_overall") or 0), -float((v.get("lint") or {}).get("ai_score") or 0))


# ------------------------------------------------------------------ 定点重写 / 精修

def patch_rewrite(content: str, review: dict[str, Any] | None, lint: LintResult, meta: dict[str, Any]) -> tuple[str, int]:
    """定点替换：只改被点名的句子。返回（新正文, 应用的补丁数）。"""
    problems: list[str] = []
    for it in (review or {}).get("issues", []):
        if it.get("severity") in ("high", "mid") and it.get("quote"):
            problems.append(f"- [{it['severity']}/{it['dimension']}] 「{it['quote']}」：{it.get('comment', '')}")
    for h in lint.banned_hits[:15]:
        problems.append(f"- AI 腔：{h['word']}（{h['count']} 处）")
    for w in lint.warnings:
        if w.startswith(("章末用总结", "弱化副词", "群众/配角反应镜头")):
            problems.append(f"- {w}")
    # v0.6 手艺类：逐句点名（重复强化词、陈词比喻、量词搭配、口头禅超频），模型只改这些句子
    for t in lint.fix_targets[:20]:
        problems.append(f"- [{t['kind']}] 「{t['quote']}」：{t['hint']}")
    if not problems:
        return content, 0
    raw = get_gateway().chat_json(
        "humanize", system_prompt("humanize", platform=meta.get("platform")),
        render("humanize", problems="\n".join(problems), content=content),
        meta={**meta, "content": content, "fix_quotes": [t["quote"] for t in lint.fix_targets[:20]]}, temperature=0.5,
    )
    patches = raw.get("patches") if isinstance(raw, dict) else None
    applied = 0
    for p in patches if isinstance(patches, list) else []:
        if not isinstance(p, dict):
            continue
        q, r = str(p.get("quote", "")), str(p.get("replacement", ""))
        if len(q) >= 4 and q in content and q != r:
            content = content.replace(q, r, 1)
            applied += 1
    return content, applied


def thicken_targets(content: str, lint: LintResult, max_n: int, merge_short: bool = True) -> list[dict[str, Any]]:
    paras = paragraphs(content)
    targets: dict[int, str] = {}
    for i in lint.bare_paragraphs:
        targets.setdefault(i, "裸对白：对白前后缺少动作、神态或环境")
    for i in lint.summary_paragraphs:
        targets.setdefault(i, "概述式叙述：一句话带过，需要写成可见的场面")
    for i, p in enumerate(paras if merge_short else []):  # 番茄档：短句推进是常态，不合并
        st = sentence_stats(p)
        if st["count"] >= 3 and st["short_ratio"] >= 0.6:
            targets.setdefault(i, "短句碎段：连续动作拆得太碎，合并成长短交替的句子")
    out = [{"index": i, "problem": prob, "text": paras[i]} for i, prob in sorted(targets.items()) if i < len(paras)]
    return out[:max_n]


_QUOTE_RX = re.compile(r"“[^”]*”")


def thicken(content: str, lint: LintResult, pack_voices: dict[str, dict[str, Any]], all_names: list[str], meta: dict[str, Any]) -> tuple[str, int, int]:
    """描写增厚：程序定位段落 → 只把这些段落交给 LLM → 校验后回贴。返回（新正文, 定位数, 应用数）。"""
    th = get_settings().lint
    prof = get_profile(meta.get("platform"))
    targets = thicken_targets(content, lint, th.thicken_max_paragraphs, prof.merge_short_sentences)
    if not targets:
        return content, 0, 0
    paras = paragraphs(content)
    idxs = {t["index"] for t in targets}
    around: list[str] = []
    for t in targets:
        i = t["index"]
        if i - 1 >= 0 and i - 1 not in idxs:
            around.append(f"[{i - 1}] {paras[i - 1][:120]}")
        if i + 1 < len(paras) and i + 1 not in idxs:
            around.append(f"[{i + 1}] {paras[i + 1][:120]}")
    voices = "\n".join(
        f"- {n}：{v.get('voice', '')}；小动作：{'、'.join(v.get('habits') or [])}；神态：{v.get('demeanor', '')}"
        for n, v in pack_voices.items()
    ) or "（未设定）"
    raw = get_gateway().chat_json(
        "thicken", system_prompt("thicken", platform=meta.get("platform")),
        render("thicken", voices=voices, targets="\n".join(f"{t['index']}: {t['problem']} | {t['text']}" for t in targets),
               context="\n".join(dict.fromkeys(around)) or "无"),
        meta={**meta, "targets": targets, "voices": pack_voices}, temperature=0.7,
    )
    items = raw.get("paragraphs") if isinstance(raw, dict) else None
    applied = 0
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("index"))
        except (TypeError, ValueError):
            continue
        new = str(it.get("text", "")).strip()
        if i not in idxs or not new:
            continue
        old = paras[i]
        if not (0.8 * len(old) <= len(new) <= max(4 * len(old), len(old) + 400)):
            continue
        # 对白原话必须保留；不得引入本章原文没有出现过的已登记实体（不新增事实）
        if any(q not in new for q in _QUOTE_RX.findall(old)):
            continue
        if any(n in new and n not in content for n in all_names):
            continue
        paras[i] = new
        applied += 1
    return "\n\n".join(paras), len(targets), applied


# ------------------------------------------------------------------ write-next

WRITE_NEXT_KIND = "chapter_write_next"


def write_next(book_id: int, ctx: JobContext, variants: int | None = None, instruction: str = "",
               resume: dict[str, Any] | None = None, no_commit: bool = False,
               allow_pending: list[int] | None = None) -> dict[str, Any]:
    """写下一章。v0.9.4：每完成一步把断点写进 job_checkpoint（拆场景 / 每个场景 / 每个版本 / 建章 / 精修 / 补丁重审），
    续跑时（resume 或 ctx.resume_state）跳过已完成的步骤，从最后完成的场景接着写。批量写章（_SubContext）不存断点。
    v0.11 完本模式：no_commit=True 时照常采纳/精修/补丁，但不自动提交（留 reviewing 等人工审批）；
    allow_pending 里的章号即使未提交也不挡写下一章（精修范围里待审批的章）。默认值保持旧行为。"""
    cp: dict[str, Any] = dict(resume if resume is not None else (getattr(ctx, "resume_state", None) or {}))
    resuming = bool(cp)
    can_cp = callable(getattr(ctx, "checkpoint", None)) and not isinstance(ctx, _SubContext)
    done: list[str] = list(cp.get("done") or [])

    def save(stage: str) -> None:
        cp["done"] = done
        if can_cp:
            ctx.checkpoint(stage, cp, kind=WRITE_NEXT_KIND)

    if resuming:
        params = cp.get("params") or {}
        variants = params.get("variants", variants)
        instruction = params.get("instruction", instruction) or ""
        no_commit = bool(params.get("no_commit", no_commit))
        allow_pending = params.get("allow_pending", allow_pending)
    if cp.get("chapter_id"):
        return _write_next_after_draft(book_id, ctx, cp, done, save)

    with session_scope() as s:
        book = common.get_book(s, book_id)
        skip = [int(x) for x in (allow_pending or [])]
        q = select(Chapter).where(Chapter.book_id == book_id, Chapter.status != "committed")
        if skip:
            q = q.where(Chapter.number.notin_(skip))  # type: ignore[attr-defined]
        pending = s.exec(q.order_by(Chapter.number)).first()
        if pending is not None:
            raise Conflict(f"第{pending.number}章尚未提交（{pending.status}），请先选定版本并提交")
        settings = writing_settings(s)
    n_var = max(1, min(3, int(variants or settings["default_variants"] or 1)))
    cp["params"] = {"variants": n_var, "instruction": instruction}
    if no_commit:
        cp["params"]["no_commit"] = True
    if allow_pending:
        cp["params"]["allow_pending"] = [int(x) for x in allow_pending]

    node_id = cp.get("node_id") or ensure_next_chapter_node(book_id, ctx)
    cp["node_id"] = node_id

    with session_scope() as s:
        book = common.get_book(s, book_id)
        node = s.get(OutlineNode, node_id)
        if node is None:
            raise NotFound("断点里的细纲节点已不存在，请重新发起写章")
        cheat = next(iter(common.cards(s, book_id, "cheat")), None)
        fixed = ensure_opening_beats(dict(node.beats or {}), node.order, cheat, book.tagline or "")
        if fixed != (node.beats or {}):
            node.beats = fixed
            s.add(node)
            s.commit()
            s.refresh(node)
        number, plan = node.order, node_plan_text(node)
        beats = {k: v for k, v in dict(node.beats or {}).items() if k != "scenes"} if cp.get("scenes") else dict(node.beats or {})
        meta = {**common.kit_meta(s, book), "number": number, "beats": beats, "title": book.title,
                "pronoun": common.pronoun(book), "words": book.chapter_words, "platform": book_platform(s, book_id)}
        pool = _sensory_pool(s, book)
        plan_ctx = scene_plan_context(s, book, node)
        if instruction.strip():
            rb = refs_block(s, book_id, instruction)
            plan_ctx += "\n【作者对本章的额外要求】\n" + instruction.strip() + ("\n" + rb if rb else "")
    cp["number"] = number
    if "beats" not in cp:
        cp["beats"] = beats
    beats = cp["beats"]
    meta["beats"] = beats
    save("node")

    # 0) 本章涉及的现实细节先联网核实（未配置搜索模型时跳过）
    if "research" not in cp:
        cp["research"] = research_notes("chapter", plan, book_id, ctx, 5)
    plan += cp["research"]

    # 1) 场景节拍
    if cp.get("scenes"):
        scenes = cp["scenes"]
        ctx.progress(10, f"第{number}章：从断点续写（已拆好 {len(scenes)} 个场景）")
    else:
        ctx.progress(8, f"第{number}章：拆分场景节拍")
        raw_scenes = get_gateway().chat_json(
            "scene_plan", system_prompt("scene_plan"),
            render("scene_plan", chapter_plan=plan, min_scenes=MIN_SCENES, max_scenes=MAX_SCENES,
                   opening_rules=scene_plan_rules(beats, number), book_context=plan_ctx),
            meta={**meta, "sensory_pool": pool},
        )
        scenes = normalize_scenes(raw_scenes, beats, pool, number)
        cp["scenes"] = scenes
        save("scenes")
    with session_scope() as s:
        node = s.get(OutlineNode, node_id)
        assert node is not None
        if (node.beats or {}).get("scenes") != scenes:
            node.beats = {**(node.beats or {}), "scenes": scenes}
            s.add(node)
            s.commit()
        book = common.get_book(s, book_id)
        pack = build_context_pack(s, book, node, instruction=instruction)
        chapter_words = book.chapter_words
        title = node.title
    meta["voices"] = pack.voices
    meta["beats"] = {**beats, "scenes": scenes}

    # 2) 生成各版本并评估（每个场景、每个版本写完都存断点）
    span = 60 // n_var
    vlist: list[dict[str, Any]] = list(cp.get("variants_done") or [])
    for v in range(len(vlist), n_var):
        lo = 12 + v * span
        partial = cp.get("partial") if (cp.get("partial") or {}).get("variant") == v else None

        def on_scene(p: dict[str, Any], i: int, total: int, _v: int = v) -> None:
            cp["partial"] = p
            save(f"scene:{_v + 1}:{i}/{total}")

        wv = _write_variant(pack, meta, title, number, plan, scenes, chapter_words, v, ctx, (lo, lo + span - 5),
                            partial=partial, on_scene=on_scene)
        content, raw_changes = wv["content"], wv["raw_changes"]
        ctx.progress(lo + span - 5, f"第{number}章 版本{v + 1}：校验变更、审稿、人味 lint")
        cs, warns = parse_changes(raw_changes)
        with session_scope() as s:
            known = {c.name for c in common.cards(s, book_id, include_deprecated=True)}
            opens = {f.id or 0: f.desc for f in common.open_foreshadows(s, book_id)}
            cs, warns2 = check_against_ledger(cs, known, opens)
            warns2 += planned_foreshadow_gaps(beats, cs)
            book = common.get_book(s, book_id)
            review, lint, dropped = _evaluate(s, book, pack, content, number, plan, meta, None)
        vlist.append({
            "id": v + 1, "content": content, "words": count_words(content), "lint": lint.to_dict(),
            "review_overall": review["scores"]["overall"], "review": review, "changes": cs.model_dump(),
            "warnings": warns + warns2 + wv["warnings"], "dropped_issues": dropped,
            "scene_states": wv["scene_states"], "end_state": wv["end_state"],
        })
        cp["variants_done"] = vlist
        cp.pop("partial", None)
        save(f"variant:{v + 1}")

    # 3) 建章（草稿）
    with session_scope() as s:
        ch = Chapter(book_id=book_id, number=number, title=title, status="draft", variants=vlist,
                     outline_node_id=node_id, content="", words=0)
        s.add(ch)
        s.commit()
        s.refresh(ch)
        chapter_id = ch.id or 0
    cp["chapter_id"] = chapter_id
    cp["result"] = {"chapter_id": chapter_id, "number": number, "variants": n_var,
                    "context": pack.summary(), "scenes": len(scenes), "preflight": pack.preflight}
    cp.pop("variants_done", None)  # 版本已进章节，断点不再重复保存正文
    done.append("chapter")
    save("chapter")
    return _write_next_after_draft(book_id, ctx, cp, done, save, (pack, meta, plan))


def _write_next_after_draft(book_id: int, ctx: JobContext, cp: dict[str, Any], done: list[str], save: Any,
                            prepared: tuple[ContextPack, dict[str, Any], str] | None = None) -> dict[str, Any]:
    """建章之后的步骤：采纳最高分 → 定点重写/精修 → 审稿补丁 + 重审 → 提交（含提交前修 mid）。每步完成写断点。"""
    chapter_id = int(cp["chapter_id"])
    result: dict[str, Any] = dict(cp.get("result") or {"chapter_id": chapter_id})
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("断点里的章节已被删除，请重新发起写章")
        book = common.get_book(s, book_id)
        settings = effective_writing_settings(s, book_id)
        review_mode = common.chapter_review_mode(book)
        number = ch.number
        vlist = list(ch.variants or [])
        if ch.status == "committed":
            result["committed"] = True
            return result
        if prepared is None:
            pack, meta, plan = _pack_for_chapter(s, ch)
            plan += cp.get("research") or ""
        else:
            pack, meta, plan = prepared
    n_var = len(vlist) or 1

    def finish(r: dict[str, Any]) -> dict[str, Any]:
        cp["result"] = r
        return r

    result["approval_mode"] = "review" if review_mode else "auto"
    if review_mode:
        # v0.9.3 审批模式 review：版本只作对比稿，不自动采纳、不精修落库、不自动提交
        result["awaiting_adopt"] = True
        result["committed"] = False
        result["reason"] = "审批模式为「逐条审阅」：请对比版本后采纳"
        return finish(result)
    if n_var > 1 and not settings["auto_adopt_best"]:
        result["awaiting_adopt"] = True
        result["committed"] = False
        return finish(result)

    if "adopted" not in done:
        best = max(vlist, key=_variant_score)
        with session_scope() as s:
            ch = s.get(Chapter, chapter_id)
            assert ch is not None
            _apply_variant(ch, best)
            s.add(ch)
            s.commit()
        result["adopted_variant"] = best["id"]
        done.append("adopted")
        cp["result"] = result
        save("adopted")

    # 4) 定点重写 / 精修（最多 1 轮）
    if "refined" not in done:
        ctx.progress(80, f"第{number}章：定点重写与描写增厚")
        result.update(refine_chapter(chapter_id, pack, meta, plan))
        done.append("refined")
        cp["result"] = result
        save("refined")

    # 4.5) v0.9：最后一轮审稿仍有 mid/high 问题且带补丁 → 按原文逐字匹配逐个应用，重跑 lint
    #      v0.9.4：应用了补丁就再审一次（最多 1 次），结果写回；high 仍在则留草稿并标记
    if "patched" not in done:
        ctx.progress(86, f"第{number}章：应用审稿补丁")
        result["review_patches"] = auto_apply_review_patches(chapter_id)
        if result["review_patches"]["applied"] and settings.get("auto_rereview", True):
            ctx.progress(89, f"第{number}章：补丁后重审")
            result["rereview"] = rereview_after_patches(chapter_id, pack, meta, plan)
        done.append("patched")
        cp["result"] = result
        save("patched")

    # 5) 提交（commit_chapter 内部：提交前按开关修 continuity/retention 类 mid 问题）
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        passed = bool((ch.review or {}).get("passed"))
        flagged = bool((ch.review or {}).get("flagged"))
    if (cp.get("params") or {}).get("no_commit"):
        # v0.11 完本模式精修范围：只写不提交，留 reviewing 等作者人工审批
        result["committed"] = False
        result["awaiting_approval"] = True
        result["review_passed"] = passed
        result["reason"] = "精修范围内的章节：已写好并自检，等待作者审批后提交"
    elif passed and settings["auto_commit"]:
        ctx.progress(92, f"第{number}章：原子提交")
        ch2 = commit_chapter(chapter_id)
        result["committed"] = True
        if (ch2.review or {}).get("pre_commit_fix"):
            result["pre_commit_fix"] = (ch2.review or {})["pre_commit_fix"]
    else:
        result["committed"] = False
        if not passed:
            result["reason"] = ("自动修补后重审仍有 high 问题，留作草稿并已标记，等作者修改后提交" if flagged
                                else "审稿仍有 high 问题，留作草稿等作者修改后提交")
        else:
            result["reason"] = "已关闭自动提交，等待作者确认"
    return finish(result)


def _resume_write_next(job: Any, state: dict[str, Any]) -> Any:
    book_id = int(job.book_id or 0)
    return lambda ctx: write_next(book_id, ctx, resume=state)


register_resumable(WRITE_NEXT_KIND, _resume_write_next)


def rereview_after_patches(chapter_id: int, pack: ContextPack, meta: dict[str, Any], plan: str) -> dict[str, Any]:
    """v0.9.4：自动应用审稿补丁后重审一次（不再循环）。新审稿写回章节（保留 patch_log），
    high 问题仍在 → review.flagged=True、passed=False，章节留草稿等作者处理。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        old = dict(ch.review or {})
        book = common.get_book(s, ch.book_id)
        review2, lint2, dropped = _evaluate(s, book, pack, ch.content, ch.number, plan, meta, chapter_id)
        highs = [i for i in review2.get("issues") or [] if i.get("severity") == "high"]
        info = {"round": 1, "at": utcnow().isoformat(),
                "before_overall": int((old.get("scores") or {}).get("overall") or 0),
                "after_overall": int(review2["scores"]["overall"]), "passed": bool(review2.get("passed")),
                "high_left": len(highs), "dropped_issues": dropped}
        review2["patch_log"] = list(old.get("patch_log") or [])
        # 旧补丁原样留在列表前面（下标不变，patch_log 仍对得上；issue_ref 置空、未应用的标 stale：旧问题已被新审稿替换），
        # 新审稿的补丁接在后面重新编号
        kept = [{**p, "issue_ref": None, "round": 0, **({} if p.get("applied") else {"stale": True})} for p in old.get("patches") or []]
        olds = {p["original"] for p in kept}
        fresh = [p for p in review2.get("patches") or [] if p.get("original") not in olds]
        review2["patches"] = [*({**p, "index": i} for i, p in enumerate(kept)),
                              *({**p, "index": len(kept) + i, "round": 1} for i, p in enumerate(fresh))]
        review2["rereview"] = info
        if old.get("pre_commit_fix"):
            review2["pre_commit_fix"] = old["pre_commit_fix"]
        if highs:
            review2["passed"] = False
            review2["flagged"] = True
            review2["flag_reason"] = f"自动修补后重审仍有 {len(highs)} 个 high 问题，请作者处理后再提交"
        ch.review = review2
        ch.lint = lint2.to_dict()
        if highs:
            chg = dict(ch.changes or {})
            chg["warnings"] = [*(chg.get("warnings") or []), review2["flag_reason"]]
            ch.changes = chg
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
    return info


AUTO_PATCH_SEVERITIES = ("high", "mid")


def _record_patches(ch: Chapter, applied: list[dict[str, Any]], skipped: list[dict[str, Any]], label: str) -> None:
    """把这次应用的补丁记进 review（patches[i].applied、patch_log）和变更声明的 warnings（提交后仍保留）。"""
    rv = dict(ch.review or {})
    pats = [dict(p) for p in rv.get("patches") or []]
    for a in applied:
        if 0 <= a["index"] < len(pats):
            pats[a["index"]]["applied"] = True
    rv["patches"] = pats
    rv["patch_log"] = [*(rv.get("patch_log") or []), {"label": label, "at": utcnow().isoformat(),
                                                      "applied": [a["index"] for a in applied], "skipped": skipped}][-10:]
    ch.review = rv
    if applied:
        chg = dict(ch.changes or {})
        brief = "；".join(f"「{a['original'][:16]}」→「{a['improved'][:16]}」" for a in applied[:5])
        chg["warnings"] = [*(chg.get("warnings") or []), f"{label}：应用审稿补丁 {len(applied)} 处（{brief}）"
                           + (f"，跳过 {len(skipped)} 处" if skipped else "")]
        ch.changes = chg


def auto_apply_review_patches(chapter_id: int) -> dict[str, Any]:
    """写作流程里的自动修：只应用对应 mid/high 问题的补丁。返回 {applied:[index], skipped:[{index,reason}]}。
    不重新审稿（passed 仍按审稿结果），作者可以再点一次审稿确认。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        rv = ch.review or {}
        issues = rv.get("issues") or []
        pats = rv.get("patches") or []
        if not pats or not any(i.get("severity") in AUTO_PATCH_SEVERITIES for i in issues):
            return {"applied": [], "skipped": []}
        want = [p["index"] for p in pats if not p.get("applied") and p.get("issue_ref") is not None
                and 0 <= int(p["issue_ref"]) < len(issues) and issues[int(p["issue_ref"])].get("severity") in AUTO_PATCH_SEVERITIES]
        if not want:
            return {"applied": [], "skipped": []}
        new, applied, skipped = apply_patches(ch.content, pats, want)
        if applied:
            push_history(ch, "审稿补丁前")
            ch.content, ch.words = new, count_words(new)
            ch.lint = lint_for(s, ch.book_id, new, ch.number, ch.id).to_dict()
        _record_patches(ch, applied, skipped, "自动修")
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
    return {"applied": [a["index"] for a in applied], "skipped": skipped}


def apply_review_patches(chapter_id: int, indices: list[int]) -> tuple[Chapter, list[dict[str, Any]], list[dict[str, Any]]]:
    """作者勾选应用审稿补丁（POST /chapters/{id}/review/patches/apply）。旧正文进历史可撤回，应用后重跑 lint。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        pats = (ch.review or {}).get("patches") or []
        if not pats:
            raise Conflict("这一章的审稿没有补丁，先重新审稿")
        if not ch.content.strip():
            raise Conflict("章节正文为空；多版本章节请先 adopt 一个版本")
        new, applied, skipped = apply_patches(ch.content, pats, indices)
        if applied:
            push_history(ch, "应用审稿补丁前")
            ch.content, ch.words = new, count_words(new)
            ch.lint = lint_for(s, ch.book_id, new, ch.number, ch.id).to_dict()
        _record_patches(ch, applied, skipped, "作者应用")
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
        s.refresh(ch)
        return ch, applied, skipped


def _apply_variant(ch: Chapter, v: dict[str, Any]) -> None:
    ch.content = v["content"]
    ch.words = count_words(v["content"])
    ch.review = v.get("review")
    ch.lint = v.get("lint")
    ch.changes = {**(v.get("changes") or {}), "warnings": v.get("warnings") or []}
    if v.get("end_state"):
        ch.changes["end_state"] = v["end_state"]  # 下一章第一个场景从这份账本接
    ch.status = "reviewing"
    ch.updated_at = utcnow()


def refine_chapter(chapter_id: int, pack: ContextPack, meta: dict[str, Any], plan: str) -> dict[str, Any]:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        content, review, number, book_id = ch.content, ch.review or {}, ch.number, ch.book_id
        lint = lint_for(s, book_id, content, number, chapter_id)
        th = book_thresholds(s, book_id)
    has_high = any(i.get("severity") == "high" for i in review.get("issues", []))
    info: dict[str, Any] = {"rewrite_round": 0, "patches": 0, "thickened": 0}
    if not (has_high or lint.over_threshold(th)):
        return info
    info["rewrite_round"] = 1
    if has_high or lint.needs_patch(th):
        content, info["patches"] = patch_rewrite(content, review, lint, meta)
    with session_scope() as s:
        lint = lint_for(s, book_id, content, number, chapter_id)
    if lint.needs_thicken(th):
        content, _, info["thickened"] = thicken(content, lint, pack.voices, pack.all_names, meta)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        book = common.get_book(s, book_id)
        review2, lint2, _ = _evaluate(s, book, pack, content, number, plan, meta, chapter_id)
        ch.content = content
        ch.words = count_words(content)
        ch.review = review2
        ch.lint = lint2.to_dict()
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
    return info


# ------------------------------------------------------------------ 提交

def _summarize(content: str, number: int, beats: dict[str, Any], meta: dict[str, Any]) -> str:
    try:
        raw = get_gateway().chat_json("summary", system_prompt("summary"), render("summary", number=number, content=content),
                                      meta={**meta, "content": content, "number": number, "beats": beats}, temperature=0.3)
        summ = str(raw.get("summary", "")).strip() if isinstance(raw, dict) else ""
    except Exception:  # noqa: BLE001
        summ = ""
    return summ or re.sub(r"\s+", "", content)[:200]


def commit_chapter(chapter_id: int, fix_mid: bool | None = None) -> Chapter:
    """原子提交：章节状态、摘要、新实体卡、facts、伏笔、大纲节点状态一个事务内写入。
    v0.9.4：提交前按开关（fix_mid=None 时读书级/全局 fix_mid_before_commit，默认开）修一次 continuity/retention 类 mid 问题。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        if ch.status == "committed":
            return ch
        if not ch.content.strip():
            raise Conflict("章节正文为空；多版本章节请先 adopt 一个版本")
        if fix_mid is None:
            fix_mid = bool(effective_writing_settings(s, ch.book_id).get("fix_mid_before_commit", True))
    if fix_mid:
        pre_commit_fix(chapter_id)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        book = common.get_book(s, ch.book_id)
        node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
        beats = (node.beats if node else None) or {}
        meta = {**common.kit_meta(s, book), "title": book.title}
        content, number = ch.content, ch.number
    summary = _summarize(content, number, beats, meta)

    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        book = common.get_book(s, ch.book_id)
        bid = book.id or 0
        raw = dict(ch.changes or {})
        warns = list(raw.pop("warnings", []) or [])
        end_state = raw.pop("end_state", None)
        cs = ChangeSet.model_validate(raw) if raw else ChangeSet()
        card_by_name = {c.name: c for c in common.cards(s, bid, include_deprecated=True)}
        opens = {f.id or 0: f.desc for f in common.open_foreshadows(s, bid)}
        cs, w2 = check_against_ledger(cs, set(card_by_name), opens)
        warns += w2
        n = ch.number
        try:
            for e in cs.new_entities:
                card = Card(book_id=bid, type=e.type, name=e.name, summary=e.summary or f"第{n}章登场",
                            data={"first_chapter": n}, known_by=[])
                s.add(card)
                s.flush()
                card_by_name[e.name] = card
            for sc in cs.state_changes:
                ent = card_by_name.get(sc.entity)
                eid = ent.id if ent else None
                prev = s.exec(select(Fact).where(Fact.book_id == bid, Fact.entity_id == eid, Fact.key == sc.key,
                                                 Fact.to_chapter == None)).all()  # noqa: E711
                for p in prev:
                    p.to_chapter = max(p.from_chapter, n - 1)
                    s.add(p)
                s.add(Fact(book_id=bid, entity_id=eid, key=sc.key, value=sc.value, from_chapter=n, visibility=sc.visibility))
            planned = {x.id or 0: x.desc for x in s.exec(select(Foreshadow).where(Foreshadow.book_id == bid, Foreshadow.status == "planned"))}
            for f in cs.foreshadow:
                if f.action == "plant":
                    pid = match_foreshadow(f.desc, planned)
                    if pid is not None:  # 规划好的伏笔（计划中）这一章真正埋下了
                        fo = s.get(Foreshadow, pid)
                        assert fo is not None
                        fo.status, fo.planted_ch, fo.last_ch = "planted", n, n
                        s.add(fo)
                        planned.pop(pid, None)
                        continue
                    s.add(Foreshadow(book_id=bid, desc=f.desc, status="planted", planted_ch=n, last_ch=n))
                    continue
                fo = s.get(Foreshadow, f.id) if f.id else None
                if fo is None or fo.book_id != bid:
                    continue
                fo.last_ch = n
                if f.action == "advance":
                    fo.status = "advancing"
                else:
                    fo.status = "resolved"
                    fo.resolved_ch = n
                s.add(fo)
            # 兜底：细纲安排在本章“埋下”的伏笔，变更声明里漏了（模型没写 ---CHANGES--- 或漏项）→ 仍按细纲登记，
            # 标注来源让作者核对，避免伏笔页一直是空的
            declared = [f.desc for f in cs.foreshadow if f.action == "plant"]
            for a in (beats.get("foreshadow") or []):
                d = str(a.get("desc") or "").strip() if isinstance(a, dict) and a.get("action") == "plant" else ""
                if not d or match_foreshadow(d, dict(enumerate(declared))) is not None:
                    continue
                pid = match_foreshadow(d, planned)
                fo = s.get(Foreshadow, pid) if pid is not None else Foreshadow(book_id=bid, desc=d, source="outline")
                assert fo is not None
                fo.status, fo.planted_ch, fo.last_ch = "planted", n, n
                fo.tier = fo.tier or str(a.get("tier") or "")
                fo.note = (fo.note + "\n" if fo.note else "") + f"第{n}章细纲安排埋下，变更声明里没有确认，请核对正文是否写到"
                s.add(fo)
                planned.pop(pid, None) if pid is not None else None
                declared.append(d)
                warns.append(f"细纲要求埋下伏笔「{d}」，变更声明漏了，已按细纲登记，请核对正文")
            ch.summary = summary
            ch.status = "committed"
            ch.changes = {**cs.model_dump(), "warnings": warns}
            if end_state:
                ch.changes["end_state"] = end_state
            ch.updated_at = utcnow()
            s.add(ch)
            if ch.outline_node_id:
                node = s.get(OutlineNode, ch.outline_node_id)
                if node:
                    node.status = "written"
                    node.chapter_id = ch.id
                    s.add(node)
            if book.status in ("idea", "bible", "outline"):
                book.status = "writing"
            book.updated_at = utcnow()
            s.add(book)
            s.commit()
        except Exception:
            s.rollback()
            raise
        s.refresh(ch)
    # v0.9.1：开启「提交后朱雀检测」时后台检测一次（默认关；失败不影响提交，不会触发任何改写）
    from app.services import zhuque

    zhuque.maybe_auto_check(chapter_id)
    return ch


# ------------------------------------------------------------------ v0.9.4 提交前修中等问题

PRE_COMMIT_LABEL = "提交前修中等问题前"


def issue_rewrite(content: str, issues: list[dict[str, Any]], meta: dict[str, Any]) -> tuple[str, int]:
    """按审稿问题描述定点改写（没有可用补丁的 mid 问题）：只把被点名的原句交给模型，返回（新正文, 改动句数）。"""
    problems = [f"- [{it.get('severity')}/{it.get('dimension')}] 「{it['quote']}」：{it.get('comment', '')}"
                + ("（番茄老读者：这里让人想划走，补一个让读者想往下看的具体信息、代价或悬念）" if it.get("dimension") == "retention" else "")
                for it in issues if it.get("quote")]
    if not problems:
        return content, 0
    quotes = [str(it["quote"]) for it in issues if it.get("quote")]
    raw = get_gateway().chat_json(
        "humanize", system_prompt("humanize", platform=meta.get("platform")),
        render("humanize", problems="\n".join(problems), content=content),
        meta={**meta, "content": content, "fix_quotes": quotes, "purpose": "pre_commit_mid_fix"}, temperature=0.5,
    )
    patches = raw.get("patches") if isinstance(raw, dict) else None
    applied = 0
    for p in patches if isinstance(patches, list) else []:
        if not isinstance(p, dict):
            continue
        q, r = str(p.get("quote", "")), str(p.get("replacement", ""))
        # 只认落在被点名句子里的改动，防止模型顺手改别处
        if len(q) >= 4 and q in content and q != r and r.strip() and any(q in x or x in q for x in quotes):
            content = content.replace(q, r, 1)
            applied += 1
    return content, applied


def pre_commit_fix(chapter_id: int) -> dict[str, Any]:
    """提交前修中等问题：最后一轮审稿（含番茄老读者审读）里 continuity / retention 类 mid 问题，
    先用对应的审稿补丁逐字替换，没有补丁（或补丁对不上）的按问题描述再定点改一次。每章只做一次；
    旧正文进历史可撤回，改后重跑 lint；不重新审稿。审批模式为「逐条审阅」时跳过（只记录原因）。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None or ch.status == "committed" or not ch.content.strip():
            return {"skipped": "章节不存在、已提交或正文为空"}
        rv = dict(ch.review or {})
        if rv.get("pre_commit_fix"):
            return {"skipped": "已修过一次", **rv["pre_commit_fix"]}
        book = common.get_book(s, ch.book_id)
        content = ch.content
        idx, pidx = pre_commit_targets(rv, content)
        if not idx:
            return {"issues": [], "patches_applied": [], "rewritten": 0}
        if common.chapter_review_mode(book):
            info = {"issues": idx, "patches_applied": [], "rewritten": 0, "skipped": "审批模式为「逐条审阅」，不自动改正文"}
            rv["pre_commit_fix"] = {**info, "at": utcnow().isoformat()}
            ch.review = rv
            s.add(ch)
            s.commit()
            return info
        pack, meta, _ = _pack_for_chapter(s, ch)
    issues = rv.get("issues") or []
    pats = rv.get("patches") or []
    new, applied, skipped = apply_patches(content, pats, pidx)
    covered = {pats[a["index"]].get("issue_ref") for a in applied}
    rest = [issues[k] for k in idx if k not in covered and str(issues[k].get("quote") or "") in new]
    rewritten = 0
    if rest:
        new, rewritten = issue_rewrite(new, rest, meta)
    info = {"issues": idx, "patches_applied": [a["index"] for a in applied], "patches_skipped": skipped,
            "rewritten": rewritten, "changed": new != content, "at": utcnow().isoformat()}
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        if new != ch.content:
            push_history(ch, PRE_COMMIT_LABEL)
            ch.content, ch.words = new, count_words(new)
            ch.lint = lint_for(s, ch.book_id, new, ch.number, ch.id).to_dict()
        if applied or skipped:
            _record_patches(ch, applied, skipped, "提交前修")
        rv2 = dict(ch.review or {})
        rv2["pre_commit_fix"] = info
        ch.review = rv2
        if rewritten:
            chg = dict(ch.changes or {})
            chg["warnings"] = [*(chg.get("warnings") or []),
                               f"提交前修中等问题：按审稿描述定点改写 {rewritten} 处（continuity/retention）"]
            ch.changes = chg
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
    return info


# ------------------------------------------------------------------ 作者操作

def adopt_variant(chapter_id: int, variant_id: int) -> Chapter:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        if ch.status == "committed":
            raise Conflict("章节已提交，不能再切换版本")
        v = next((x for x in ch.variants or [] if int(x.get("id", -1)) == int(variant_id)), None)
        if v is None:
            raise NotFound(f"版本 {variant_id} 不存在")
        _apply_variant(ch, v)
        lint = lint_for(s, ch.book_id, ch.content, ch.number, ch.id)
        ch.lint = lint.to_dict()
        s.add(ch)
        s.commit()
        s.refresh(ch)
        return ch


def _pack_for_chapter(s: Session, ch: Chapter) -> tuple[ContextPack, dict[str, Any], str]:
    book = common.get_book(s, ch.book_id)
    node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
    if node is None:
        node = OutlineNode(book_id=ch.book_id, level="chapter", order=ch.number, title=ch.title, beats={"characters": []})
    pack = build_context_pack(s, book, node)
    meta = {**common.kit_meta(s, book), "number": ch.number, "beats": node.beats or {}, "voices": pack.voices,
            "pronoun": common.pronoun(book), "platform": book_platform(s, ch.book_id)}
    return pack, meta, node_plan_text(node)


def _require_content(ch: Chapter | None) -> Chapter:
    if ch is None:
        raise NotFound("章节不存在")
    if not ch.content.strip():
        raise Conflict("章节正文为空；多版本章节请先 adopt 一个版本")
    return ch


def review_chapter_job(chapter_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        ch = _require_content(s.get(Chapter, chapter_id))
        pack, meta, plan = _pack_for_chapter(s, ch)
        book = common.get_book(s, ch.book_id)
        ctx.progress(20, "审稿中")
        review, lint, dropped = _evaluate(s, book, pack, ch.content, ch.number, plan, meta, ch.id)
        ch.review = review
        ch.lint = lint.to_dict()
        if ch.status == "draft":
            ch.status = "reviewing"
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
        return {"chapter_id": chapter_id, "overall": review["scores"]["overall"], "passed": review["passed"], "dropped_issues": dropped}


def pack_book_id(chapter_id: int) -> int:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        return ch.book_id if ch else 0


def _review_draft(before: str, after: str, label: str) -> dict[str, Any]:
    """v0.9.3 审批模式 review：章节 AI 只给对比稿（不落库），前端用 apply-rewrite 采纳。
    注意 thicken 的 before/after 是指标，所以正文对比稿放在 draft 里。"""
    return {"applied": False, "approval_mode": "review",
            "draft": {"label": label, "before": before, "after": after, "changed": after != before,
                      "words_before": count_words(before), "words_after": count_words(after)}}


def humanize_chapter_job(chapter_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        ch = _require_content(s.get(Chapter, chapter_id))
        pack, meta, _ = _pack_for_chapter(s, ch)
        before = lint_for(s, ch.book_id, ch.content, ch.number, ch.id)
        content, review = ch.content, ch.review
    ctx.progress(30, "定点清理 AI 腔")
    original = content
    content, applied = patch_rewrite(content, review, before, meta)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        after = lint_for(s, ch.book_id, content, ch.number, ch.id)
        if common.chapter_review_mode(common.get_book(s, ch.book_id)):
            return {"chapter_id": chapter_id, "patches": applied, "ai_score_before": before.ai_score, "ai_score_after": after.ai_score,
                    **_review_draft(original, content, "人味修整前")}
        if content != ch.content:
            push_history(ch, "人味修整前")
        ch.content, ch.words, ch.lint, ch.updated_at = content, count_words(content), after.to_dict(), utcnow()
        s.add(ch)
        s.commit()
    return {"chapter_id": chapter_id, "patches": applied, "ai_score_before": before.ai_score, "ai_score_after": after.ai_score}


def thicken_chapter_job(chapter_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        ch = _require_content(s.get(Chapter, chapter_id))
        pack, meta, _ = _pack_for_chapter(s, ch)
        before = lint_for(s, ch.book_id, ch.content, ch.number, ch.id)
        content = ch.content
    ctx.progress(30, "定位裸对白与概述段落")
    original = content
    content, located, applied = thicken(content, before, pack.voices, pack.all_names, meta)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        after = lint_for(s, ch.book_id, content, ch.number, ch.id)
        if common.chapter_review_mode(common.get_book(s, ch.book_id)):
            keys = ("bare_dialogue_ratio", "summary_ratio", "short_sentence_ratio", "ai_score")
            return {"chapter_id": chapter_id, "located": located, "rewritten": applied,
                    "before": {k: before.to_dict()[k] for k in keys}, "after": {k: after.to_dict()[k] for k in keys},
                    **_review_draft(original, content, "描写增厚前")}
        if content != ch.content:
            push_history(ch, "描写增厚前")
        ch.content, ch.words, ch.lint, ch.updated_at = content, count_words(content), after.to_dict(), utcnow()
        s.add(ch)
        s.commit()
    return {
        "chapter_id": chapter_id, "located": located, "rewritten": applied,
        "before": {k: before.to_dict()[k] for k in ("bare_dialogue_ratio", "summary_ratio", "short_sentence_ratio", "ai_score")},
        "after": {k: after.to_dict()[k] for k in ("bare_dialogue_ratio", "summary_ratio", "short_sentence_ratio", "ai_score")},
    }


def write_batch(book_id: int, count: int, ctx: JobContext, variants: int | None = None) -> dict[str, Any]:
    done: list[int] = []
    for i in range(count):
        sub = _SubContext(ctx, i, count)
        r = write_next(book_id, sub, variants)  # type: ignore[arg-type]
        done.append(r["chapter_id"])
        if not r.get("committed"):
            return {"chapter_ids": done, "stopped": True, "reason": r.get("reason") or "等待作者选定版本", "last": r}
    return {"chapter_ids": done, "stopped": False}


class _SubContext:
    def __init__(self, parent: JobContext, i: int, n: int) -> None:
        self.parent, self.i, self.n = parent, i, n
        self.job_id, self.book_id = parent.job_id, parent.book_id

    def progress(self, pct: int, message: str = "") -> None:
        self.parent.progress(int((self.i * 100 + pct) / self.n), f"[{self.i + 1}/{self.n}] {message}")


def update_chapter(chapter_id: int, title: str | None, content: str | None) -> Chapter:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        if title is not None:
            ch.title = title
        if content is not None:
            ch.content = content
            ch.words = count_words(content)
            ch.lint = lint_for(s, ch.book_id, content, ch.number, ch.id).to_dict()
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
        s.refresh(ch)
        return ch


# ------------------------------------------------------------------ 按要求改写（v0.4）

MAX_HISTORY = 10


def push_history(ch: Chapter, label: str) -> None:
    ch.history = [*(ch.history or []), {"content": ch.content, "title": ch.title, "words": ch.words, "label": label[:60],
                                        "at": utcnow().isoformat()}][-MAX_HISTORY:]


def _clean_rewrite(text: str) -> str:
    body, _ = split_output(text)
    body = re.sub(r"^```[a-z]*\s*|\s*```$", "", body.strip())
    body = body.strip().strip("<>").strip()
    return body


def normalize_paragraphs(text: str) -> str:
    """统一段落格式：每段去掉首尾空白，段与段之间空一行（与生成正文一致）。"""
    paras = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    return "\n\n".join(p for p in paras if p)


def rewrite_chapter_job(chapter_id: int, instruction: str, route: str | None, scope: str, start: int | None, end: int | None,
                        ctx: JobContext) -> dict[str, Any]:
    """按作者要求改写全章或选中的文字。只生成改写稿，不落库；作者对比后采纳（apply_rewrite）或丢弃。"""
    with session_scope() as s:
        ch = _require_content(s.get(Chapter, chapter_id))
        pack, meta, plan = _pack_for_chapter(s, ch)
        content, number = ch.content, ch.number
    if scope == "selection":
        if start is None or end is None or not (0 <= start < end <= len(content)):
            raise ValueError("选中的范围不对，请重新选择要改的文字")
        text = content[start:end]
        if not text.strip():
            raise ValueError("选中的是空白，请重新选择")
        context = (f"上文（不要改）：…{content[max(0, start - 300):start]}\n下文（不要改）：{content[end:end + 300]}…")
        scope_label = "中选中的一段文字（只改这一段，和上下文衔接）"
    else:
        start, end, text = 0, len(content), content
        context = ""
        scope_label = "（全章）"
    voices = "\n".join(f"- {n}：{v.get('voice', '')}；口头禅：{'、'.join(v.get('catchphrases') or [])}" for n, v in pack.voices.items()) or "（未设定）"
    user = render("chapter_rewrite", number=number, scope_label=scope_label, chapter_plan=plan, voices=voices, context=context,
                  text=text, instruction=instruction.strip())
    with session_scope() as s:
        rb = refs_block(s, pack_book_id(chapter_id), instruction)
    if rb:
        user += "\n\n" + rb
    ctx.progress(20, "按要求改写" + ("选中的文字" if scope == "selection" else "全章"))
    out = get_gateway().chat(
        "chapter_rewrite", [{"role": "system", "content": system_prompt("chapter_rewrite", platform=meta.get("platform"))},
                            {"role": "user", "content": user}],
        meta={**meta, "text": text, "instruction": instruction, "scope": scope}, temperature=0.8, route=route,
    )
    new = _clean_rewrite(out)
    if scope != "selection" or "\n\n" in text:
        new = normalize_paragraphs(new)
    if not new.strip():
        raise ValueError("模型没有给出改写稿")
    if scope != "selection" and len(new) < 0.3 * len(text) and not re.search(r"(删|缩|压|精简|短)", instruction):
        raise ValueError("改写稿比原文短太多，疑似被截断，请重试或换个模型")
    after = content[:start] + new + content[end:]
    ctx.progress(85, "人味检查")
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        lint = lint_for(s, ch.book_id, after, number, chapter_id)
    return {"chapter_id": chapter_id, "scope": scope, "start": start, "end": end, "instruction": instruction.strip(),
            "before": content, "after": after, "changed": after != content, "words_before": count_words(content),
            "words_after": count_words(after), "ai_score_after": lint.ai_score}


# ------------------------------------------------------------------ v0.9.1 语感重塑

POLISH_LABEL = "语感重塑前"
POLISH_RATIO = 0.2  # 字数变化上限 ±20%
_CN_NUM = "零〇一二两三四五六七八九十百千万亿"
_MEASURE = "个只名位次招层阶级品重块颗枚斤两里米丈年月天日岁倍成拳剑刀步秒分钟章段星转境下声遍圈口张根条把间座道份家"
_NUM_RX = re.compile(rf"\d+(?:[.,]\d+)*%?|[{_CN_NUM}]{{2,}}|[二三四五六七八九十百千万亿](?=[{_MEASURE}])")
_NUM_STOP = {"万一", "一一", "千万", "万万", "一二", "三三两两", "七七八八", "十有八九", "一一二"}
PARA_RULE = {
    "fanqie": "番茄档：短段，每段不超过 70 字（一段 1–3 行），长段拆开，对白单独成段。",
    "qidian": "起点档：段落可以稍长，但单段别超过 150 字。",
    "generic": "通用档：段落长短跟着内容走，单段别超过 120 字。",
}
PARA_MAX = {"fanqie": 70, "qidian": 150, "generic": 120}


def number_tokens(text: str) -> set[str]:
    """正文里的数字 / 数值词集合：阿拉伯数字、两字以上的中文数字串、单个中文数字 + 量词（三招、九层）。"""
    out = set()
    for m in _NUM_RX.finditer(text or ""):
        t = m.group(0)
        if t in _NUM_STOP:
            continue
        out.add(t)
    return out


def polish_checks(before: str, after: str, names: list[str], platform: str = "fanqie") -> tuple[dict[str, Any], list[str]]:
    """程序校验：数字/数值词集合一致、主要人名都在、字数变化在 ±20% 内、段长（番茄 ≤70 字）。"""
    nb, na = number_tokens(before), number_tokens(after)
    missing_nums, added_nums = sorted(nb - na), sorted(na - nb)
    present = [n for n in names if n and n in before]
    missing_names = [n for n in present if n not in after]
    wb, wa = count_words(before), count_words(after)
    ratio = round((wa - wb) / wb, 3) if wb else 0.0
    limit = PARA_MAX.get(platform, 120)
    long_paras = sum(1 for p in paragraphs(after) if count_words(p) > limit)
    warns: list[str] = []
    if missing_nums or added_nums:
        parts = []
        if missing_nums:
            parts.append("少了 " + "、".join(missing_nums[:8]))
        if added_nums:
            parts.append("多了 " + "、".join(added_nums[:8]))
        warns.append(f"数字/数值和原文不一致（{'；'.join(parts)}），请核对战力、金额、时间有没有被改")
    if missing_names:
        warns.append(f"这些人名在润色稿里不见了：{'、'.join(missing_names[:8])}")
    if abs(ratio) > POLISH_RATIO:
        warns.append(f"字数变化 {ratio:+.0%}（{wb} → {wa} 字），超过 ±{POLISH_RATIO:.0%}，可能删了情节或注了水")
    if long_paras:
        warns.append(f"还有 {long_paras} 段超过 {limit} 字，建议再拆段")
    checks = {"numbers_missing": missing_nums, "numbers_added": added_nums, "names_checked": present, "names_missing": missing_names,
              "words_ratio": ratio, "long_paragraphs": long_paras}
    return checks, warns


def _banned_for(text: str, k: int = 30) -> str:
    from app.lint.banned_zh import BANNED_PATTERNS

    hits: list[str] = []
    for p in BANNED_PATTERNS:
        if p.priority == 1 and p.word in text and p.word not in hits:
            hits.append(p.word)
    base = ["嘴角勾起一抹", "深吸一口气", "眼神一凛", "瞳孔一缩", "眼中闪过一丝", "指节泛白", "心中一凛", "不禁", "仿佛", "与此同时"]
    words = hits[:k] + [w for w in base if w not in hits]
    return "、".join(words[:k + len(base)])


def polish_voice_job(chapter_id: int, ctx: JobContext, book_id: int | None = None) -> dict[str, Any]:
    """语感重塑：只生成润色稿（不落库），结构同改写稿（before/after…），作者对比后 apply-rewrite 采纳、undo 撤回。
    生成后做程序校验，不符的写进 warnings；不会因为任何检测分数自动再改。"""
    with session_scope() as s:
        ch = _require_content(s.get(Chapter, chapter_id))
        if book_id is not None and ch.book_id != book_id:
            raise NotFound("章节不存在")
        pack, meta, _ = _pack_for_chapter(s, ch)
        content, number = ch.content, ch.number
        names = [c.name for c in common.cards(s, ch.book_id) if c.type == "character"]
        for n in (meta.get("beats") or {}).get("characters") or []:
            n = str(n.get("name") if isinstance(n, dict) else n or "").strip()
            if n and n not in names:
                names.append(n)
    platform = meta.get("platform") or "fanqie"
    present = [n for n in names if n and n in content]
    voices = "\n".join(f"- {n}：{v.get('voice', '')}；口头禅：{'、'.join(v.get('catchphrases') or [])}" for n, v in pack.voices.items()) or "（未设定）"
    from app.skills.loader import PLATFORM_LABEL

    user = render("polish_voice", number=number, platform_label=PLATFORM_LABEL.get(platform, platform), para_rule=PARA_RULE.get(platform, ""),
                  voices=voices, names="、".join(present) or "（无）", banned=_banned_for(content), text=content)
    ctx.progress(15, "语感重塑中")
    out = get_gateway().chat(
        "polish_voice", [{"role": "system", "content": system_prompt("polish_voice", platform=platform)}, {"role": "user", "content": user}],
        meta={**meta, "text": content, "names": present}, temperature=0.8,
    )
    new = normalize_paragraphs(_clean_rewrite(out))
    if not new.strip():
        raise ValueError("模型没有给出润色稿")
    if len(new) < 0.3 * len(content):
        raise ValueError("润色稿比原文短太多，疑似被截断，请重试或换个模型")
    ctx.progress(85, "校验数值、人名与字数，人味检查")
    checks, warns = polish_checks(content, new, present, platform)
    with session_scope() as s:
        lint = lint_for(s, ch.book_id, new, number, chapter_id)
    return {"chapter_id": chapter_id, "scope": "all", "start": 0, "end": len(content), "instruction": "语感重塑",
            "label": POLISH_LABEL, "before": content, "after": new, "changed": new != content, "words_before": count_words(content),
            "words_after": count_words(new), "ai_score_after": lint.ai_score, "checks": checks, "warnings": warns}


def apply_rewrite(chapter_id: int, content: str, label: str) -> Chapter:
    """采纳改写稿：旧正文进历史（可撤回），新正文落库并重跑 lint。审稿由前端随后发起。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        if ch.status == "draft" and ch.variants and not ch.content.strip():
            raise Conflict("多版本章节请先采纳一个版本")
        if content != ch.content:
            push_history(ch, label or "按要求改写前")
            ch.content = content
            ch.words = count_words(content)
            ch.lint = lint_for(s, ch.book_id, content, ch.number, ch.id).to_dict()
            ch.updated_at = utcnow()
            s.add(ch)
            s.commit()
            s.refresh(ch)
        return ch


def undo_chapter(chapter_id: int) -> Chapter:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        if not ch.history:
            raise Conflict("没有可以撤回的版本")
        prev = ch.history[-1]
        ch.content = prev.get("content", ch.content)
        ch.title = prev.get("title", ch.title)
        ch.words = count_words(ch.content)
        ch.lint = lint_for(s, ch.book_id, ch.content, ch.number, ch.id).to_dict()
        ch.history = ch.history[:-1]
        ch.updated_at = utcnow()
        s.add(ch)
        s.commit()
        s.refresh(ch)
        return ch
