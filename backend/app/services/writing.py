"""正文流水线（确定性编排：代码控制流程，LLM 只做生成与判断）。

write-next（v0.17 整章一次写）：
  取下一章细纲（必要时滚动展开，读者账本兜底）→ 段落安排（3–6 段，只写事件不写台词）→ 组 Context Pack
  → 写手一次写完整章（纯正文，上一章结尾原文放在提示最后）→ 另起一次调用从正文抽状态账本与变更声明
  → 校验变更、对照底账、出场守卫 → 证据式审稿 + 读者审读 → 人味 lint
  → 开篇第 1 章与大爽点章写 2 版，审稿模型成对比较「哪版更想点下一章」选优
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
from app.models.tables import Book, Card, Chapter, Fact, Foreshadow, OutlineNode, utcnow
from app.services import common
from app.services.changes import ChangeSet, check_against_ledger, match_foreshadow, parse_changes, split_output
from app.services.common import Conflict, NotFound
from app.services.context import ContextPack, build_context_pack, scene_plan_context
from app.services.refs import refs_block
from app.services.outline import chapter_beats_list, ensure_next_chapter_node, ensure_opening_beats, node_plan_text
from app.services.scene_state import (
    STATE_SCHEMA_HINT, merge_state, normalize_scene_state, prop_move_warnings, render_state,
)
from app.services.review import apply_patches, pairwise_compare, pre_commit_targets, reader_persona, run_review
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
WRITER_TEMPERATURE = 0.85   # v0.17 写作温度（旧版逐场景 0.9）
CANDIDATE_LEVELS = ("milestone",)  # v0.17 章纲标了大爽点（payoff_level）的章写 2 版成对比较


def writer_max_tokens(words: int) -> int:
    """v0.17：写作调用的 max_tokens，按章字数估（中文约 1–1.5 token/字，留到 2 倍再加余量），封顶 16000。"""
    return int(min(16000, max(4000, int(words or 2000) * 2 + 1500)))


def is_candidate_chapter(number: int, beats: dict[str, Any] | None) -> bool:
    """开篇第 1 章，以及章纲标了大爽点的章：写 2 版，成对比较选优。"""
    b = beats or {}
    return int(number or 0) == 1 or str(b.get("payoff_level") or "") in CANDIDATE_LEVELS or bool(b.get("big_payoff"))


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

def lint_for(s: Session, book_id: int, content: str, number: int, exclude_chapter_id: int | None = None,
             habits: dict[str, list[str]] | None = None) -> LintResult:
    others = [c.content for c in common.committed_chapters(s, book_id) if c.id != exclude_chapter_id]
    cards = common.cards(s, book_id)
    names = [c.name for c in cards]
    cps = {c.name: common.voice_of(c)["catchphrases"] for c in cards if c.type == "character" and (c.data or {}).get("catchphrases")}
    if habits is None:  # v0.17 习惯动作计数：默认数出场人物（正文里出现了名字）的习惯
        habits = {c.name: list((c.data or {}).get("habits") or []) for c in cards
                  if c.type == "character" and (c.data or {}).get("habits") and c.name in content}
    from app.services.continuity import recent_usage

    prev = [c for c in common.written_chapters(s, book_id, before=number) if c.id != exclude_chapter_id]
    return lint_chapter(content, get_settings().lint, others, names, number, catchphrases=cps, platform=book_platform(s, book_id),
                        ledger=numeric_ledger(s, book_id, number, cards), habits=habits,
                        recent_usage=recent_usage(s, book_id, number, prev))


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

_QUOTED_LINE = re.compile(r"[“「\"『][^”」\"』]{4,}[”」\"』]")


def _no_lines(text: Any, n: int = 160) -> str:
    """段落安排里只留事件：拆场景的模型爱预写台词原句，去掉引号里的整句。"""
    t = _QUOTED_LINE.sub("", str(text or ""))
    return re.sub(r"[，,：:]\s*$", "", re.sub(r"\s+", " ", t)).strip()[:n]


def normalize_scenes(raw: Any, beats: dict[str, Any], sensory_pool: list[str] | None = None, number: int | None = None) -> list[dict[str, Any]]:
    """v0.17：段落安排（原拆场景）只保留事件与局面变化，去掉感官锚点和预写的台词。sensory_pool 参数保留兼容，不再使用。"""
    items = raw.get("scenes") if isinstance(raw, dict) else raw
    scenes: list[dict[str, Any]] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        sc = {
            "goal": _no_lines(it.get("goal")),
            "conflict": _no_lines(it.get("conflict")),
            "outcome": it.get("outcome") if it.get("outcome") in OUTCOMES else "yes-but",
            "characters": [str(c) for c in (it.get("characters") or beats.get("characters") or [])],
        }
        if it.get("turn"):
            sc["turn"] = _no_lines(it["turn"], 120)
        if it.get("payoff_phase") in PAYOFF_PHASES:
            sc["payoff_phase"] = it["payoff_phase"]
        if it.get("relations"):
            sc["relations"] = _no_lines(it["relations"], 120)
        if it.get("cheat"):
            sc["cheat"] = _no_lines(it["cheat"], 160)
        scenes.append(sc)
    scenes = scenes[:MAX_SCENES]
    while len(scenes) < MIN_SCENES:
        scenes.append({"goal": beats.get("want") or beats.get("goal", ""), "conflict": beats.get("conflict", ""), "outcome": "yes-but",
                       "characters": list(beats.get("characters") or [])})
    # 连续 3 个 yes 视为节奏塌陷：中间那个改成 yes-but
    for i in range(2, len(scenes)):
        if all(scenes[j]["outcome"] == "yes" for j in (i - 2, i - 1, i)):
            scenes[i - 1]["outcome"] = "yes-but"
    # 末段承接章结果
    if beats.get("outcome") in OUTCOMES:
        scenes[-1]["outcome"] = beats["outcome"]
    return enforce_scene_rules(scenes, beats, number)


def enforce_scene_rules(scenes: list[dict[str, Any]], beats: dict[str, Any], number: int | None) -> list[dict[str, Any]]:
    """程序兜底：
    - 第 1–3 章：第一段带 opening（前三行冲突/异常）；
    - 细纲安排了金手指（cheat_beat 不是“本章不用”）而没有任何一段认领 → 挂到兑现段（没有就挂第 2 段）；
    - 章末最后一拍只由最后一段承担：main_hook = 细纲 hook_end。
    """
    if not scenes:
        return scenes
    n = int(number or beats.get("number") or 0)
    if n and n <= 3 and beats.get("opening_hook"):
        scenes[0].setdefault("opening", str(beats["opening_hook"])[:160])
    cb = str(beats.get("cheat_beat") or "").strip()
    if cb and not cb.startswith(("本章不用", "不用")) and not any(sc.get("cheat") for sc in scenes):
        target = next((sc for sc in scenes if sc.get("payoff_phase") == "delivery"), scenes[min(1, len(scenes) - 1)])
        target["cheat"] = cb[:160]
    last = scenes[-1]
    last.pop("exit_hook", None)
    if beats.get("hook_end"):
        last["main_hook"] = str(beats["hook_end"])[:160]
    return scenes


def scene_plan_rules(beats: dict[str, Any], number: int) -> str:
    """拆场景时的程序附加要求（按章号与细纲拼）。"""
    lines: list[str] = []
    if number <= 3:
        lines.append(f"第一段的第一拍就是冲突或异常：{beats.get('opening_hook') or beats.get('conflict') or ''}。")
    cb = str(beats.get("cheat_beat") or "").strip()
    if cb and not cb.startswith(("本章不用", "不用")):
        lines.append(f"金手指本章要出手，放进兑现那一段，在那一段的 JSON 里写 \"cheat\"：{cb}")
    if beats.get("want"):
        lines.append(f"主角本章主动想要：{beats['want']}。每段的 goal 都从主角出发。")
    lines.append("最后一段落到章末最后一拍：" + str(beats.get("hook_end") or "停在事件进行中或一句话上") + "。")
    lines.append("有新人物出场或关系容易误读时，在 relations 里写清他和主角的关系与称呼依据。")
    return "\n".join(f"- {x}" for x in lines)


# ------------------------------------------------------------------ 生成一版（v0.17 整章一次写）

_OUTCOME_LABEL = {"yes": "得手", "no": "没得手", "yes-but": "得手但有麻烦", "no-and": "没得手且局面更糟"}


def scenes_text(scenes: list[dict[str, Any]]) -> str:
    """段落安排给写手看的样子：每段要发生什么、局面怎么变。"""
    lines: list[str] = []
    for i, sc in enumerate(scenes, 1):
        bits = [f"想要：{sc['goal']}" if sc.get("goal") else "", f"阻力：{sc['conflict']}" if sc.get("conflict") else "",
                f"转折：{sc['turn']}" if sc.get("turn") else "", f"结果：{_OUTCOME_LABEL.get(sc.get('outcome') or '', '')}" if sc.get("outcome") else "",
                f"在场：{'、'.join(sc['characters'])}" if sc.get("characters") else "",
                f"关系：{sc['relations']}" if sc.get("relations") else "", f"金手指：{sc['cheat']}" if sc.get("cheat") else "",
                f"开篇：{sc['opening']}" if sc.get("opening") else "", f"章末最后一拍：{sc['main_hook']}" if sc.get("main_hook") else ""]
        lines.append(f"{i}. " + "；".join(b for b in bits if b))
    return "\n".join(lines) or "（按本章写作任务写）"


def build_chapter_user(pack: ContextPack, number: int, title: str, scenes: list[dict[str, Any]], words: int,
                       research: str = "") -> str:
    """整章写作的 user 提示词：动态上下文在前，本章段落安排与人物提醒居中，上一章结尾原文放在最后（动笔前最后读到的是正文）。纯函数。"""
    prev = f"【上一章结尾原文】\n{pack.prev_tail}" if pack.prev_tail else ""
    if pack.prev_tail:
        start = "从上一章最后一句之后紧接着写，人在哪、手里拿着什么、情绪接得上。"
    elif number == 1:
        start = "从冲突发生的那一刻写起。"
    else:
        start = ""
    return pack.suffix + "\n\n" + render(
        "writing_chapter", number=number, chapter_title=title, words=words, scenes=scenes_text(scenes),
        research=("\n" + research.strip() + "\n") if research.strip() else "", cast_notes=pack.cast_notes or "（无）",
        prev_tail=prev, start_line=start,
    )


_MARKERS = ("---STATE---", "---CHANGES---")
_JSONISH = re.compile(r'^\s*(?:[{}\[\]]|"[A-Za-z_][\w ]*"\s*:)')
_DECOR = re.compile(r"^\s*(?:\*\*|#+\s*)?\s*(?:本章)?(?:正文|章节正文|正文开始|正文如下)\s*[:：]?\s*(?:\*\*)?\s*$")
_SCENE_HEAD = re.compile(r"^\s*(?:#+\s*)?(?:场景|段落)[一二三四五六七八九十0-9]+\s*[:：.、]?.{0,30}$")
_TITLE_HEAD = re.compile(r"^\s*(?:#+\s*)?第[一二三四五六七八九十百千零〇0-9]+章.{0,30}$")


def clean_prose(text: str) -> str:
    """v0.17 正文清洗（写手输出 → 可发布正文）：
    整段是 JSON 时取里面的正文字段；切掉 ---STATE--- / ---CHANGES--- 及之后；去代码块围栏、`**正文**`、markdown 标题、
    「场景一：」、开头的章标题、孤立的 ---、行内 **加粗**；去掉 JSON 残片行（以 { } [ ] 或 "key": 开头）。"""
    t = (text or "").replace("\r\n", "\n").strip()
    if t[:1] in ("{", "`"):
        try:
            from app.llm.gateway import extract_json

            obj = extract_json(t)
            if isinstance(obj, dict):
                for k in ("content", "text", "正文", "chapter", "body"):
                    if isinstance(obj.get(k), str) and obj[k].strip():
                        t = obj[k].strip()
                        break
        except Exception:  # noqa: BLE001
            pass
    for mk in _MARKERS:
        i = t.find(mk)
        if i != -1:
            t = t[:i]
    out: list[str] = []
    for i, ln in enumerate(t.split("\n")):
        st = ln.strip()
        if st.startswith("```"):
            continue
        if re.fullmatch(r"[-—_*=~]{3,}", st):
            continue
        if _DECOR.match(st) or _SCENE_HEAD.match(st):
            continue
        if not out and _TITLE_HEAD.match(st) and len(st) <= 30:
            continue
        if st.startswith("#"):
            continue
        if _JSONISH.match(st) and "“" not in st:
            continue
        out.append(ln)
    t = "\n".join(out)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    return normalize_paragraphs(t)


def _clean_scene(text: str) -> str:  # 旧名，保留给外部调用
    return clean_prose(text)


def _write_variant(pack: ContextPack, meta: dict[str, Any], title: str, number: int, scenes: list[dict[str, Any]],
                   words: int, variant: int, ctx: JobContext, pct: int, research: str = "") -> str:
    """v0.17：写手一次写完整章，只要纯正文。"""
    ctx.progress(pct, f"第{number}章 版本{variant + 1}：整章写作")
    user = build_chapter_user(pack, number, title, scenes, words, research)
    out = get_gateway().chat(
        "writing_chapter",
        [{"role": "system", "content": pack.prefix}, {"role": "user", "content": user}],
        meta={**meta, "scenes": scenes, "variant": variant, "words": words},
        temperature=WRITER_TEMPERATURE, max_tokens=writer_max_tokens(words),
    )
    content = clean_prose(out)
    if not content.strip():
        raise ValueError("模型没有写出正文")
    have = count_words(content)
    if have < TOPUP_RATIO * words:  # v0.18：整章写短了（常见于开篇），接着续写一次补齐，不另起炉灶
        ctx.progress(pct, f"第{number}章 版本{variant + 1}：篇幅不够（{have}/{words} 字），续写补齐")
        more = get_gateway().chat(
            "writing_chapter",
            [{"role": "system", "content": pack.prefix}, {"role": "user", "content": user},
             {"role": "assistant", "content": content},
             {"role": "user", "content": TOPUP_NOTE.format(missing=max(words - have, 500))}],
            meta={**meta, "scenes": scenes, "variant": variant, "words": words, "topup": True},
            temperature=WRITER_TEMPERATURE, max_tokens=writer_max_tokens(words),
        )
        extra = clean_prose(more)
        if extra.strip() and extra.strip()[:30] not in content:
            content = content.rstrip() + "\n\n" + extra.strip()
    return content


TOPUP_RATIO = 0.75
TOPUP_NOTE = ("篇幅不够，还差约 {missing} 字。从你最后一句之后接着写，把本章细纲里还没写到的段落写完，"
              "写到本章结果和章末最后一拍为止；不重复前文，不重新开头，不写章节标题。只输出续写的正文。")


def extract_chapter_state(book_id: int, pack: ContextPack, meta: dict[str, Any], number: int, title: str, content: str,
                          beats: dict[str, Any]) -> dict[str, Any]:
    """v0.17：写完后另起一次 planner 调用，从正文抽本章结束时的状态账本和变更声明。失败不挡写章（沿用上一章账本、按无变更）。
    返回 {end_state, raw_changes(str|None), warnings}。"""
    with session_scope() as s:
        known = [c.name for c in common.cards(s, book_id, include_deprecated=True)]
        opens = common.open_foreshadows(s, book_id)
    planned = "；".join(f"{ {'plant': '埋下', 'advance': '推进', 'resolve': '回收'}.get(str(f.get('action')), '') }「{f.get('desc')}」"
                       + (f"(#{f['id']})" if f.get("id") else "")
                       for f in beats.get("foreshadow") or [] if isinstance(f, dict) and f.get("desc")) or "无"
    user = render("chapter_state", number=number, chapter_title=title, schema_hint=STATE_SCHEMA_HINT,
                  known="、".join(known[:120]) or "（无）",
                  opens="\n".join(f"- #{f.id} {f.desc}" for f in opens[:20]) or "（无）", planned=planned,
                  prev_state=render_state(pack.opening_state, "上一章结束时") if pack.opening_state else "（无）",
                  content=content)
    warns: list[str] = []
    try:
        raw = get_gateway().chat_json("chapter_state", system_prompt("chapter_state"), user,
                                      meta={**meta, "content": content, "prev_state": pack.opening_state, "number": number},
                                      temperature=0.2)
    except Exception as e:  # noqa: BLE001
        raw = None
        warns.append(f"状态账本没抽出来（{str(e)[:60]}），沿用上一章的账本，变更声明按无变更处理")
    state = pack.opening_state
    changes: str | None = None
    if isinstance(raw, dict):
        st = normalize_scene_state(raw.get("state"))
        if st["cast"] or st["props"]:
            warns += prop_move_warnings(pack.opening_state, st, content, 0)
            state = merge_state(pack.opening_state, st)
        else:
            warns.append("状态账本为空，沿用上一章的账本")
        if isinstance(raw.get("changes"), dict):
            changes = json.dumps(raw["changes"], ensure_ascii=False)
    elif raw is not None:
        warns.append("状态账本不是合法 JSON，沿用上一章的账本")
    return {"end_state": state, "raw_changes": changes if changes is not None else "{}", "warnings": warns}


def _evaluate(
    s: Session, book: Book, pack: ContextPack, content: str, number: int, plan: str, meta: dict[str, Any],
    exclude_chapter_id: int | None,
) -> tuple[dict[str, Any], LintResult, int]:
    lint = lint_for(s, book.id or 0, content, number, exclude_chapter_id, habits=pack.habits)
    # v0.9.4：数值一致性 lint 的问题进审稿结果（mid / continuity，带位置）
    review, dropped = run_review(get_gateway(), content, number, plan, pack.protagonist, pack.required_chars, meta,
                                 context=pack.state_text, cheat_terms=pack.cheat_terms,
                                 extra_issues=list(lint.numeric_issues or []) + _fanfic_issues(s, book, content, exclude_chapter_id),
                                 persona=reader_persona(book), ledger=_reader_ledger(s, book.id or 0, number))
    return review, lint, dropped


def _reader_ledger(s: Session, book_id: int, number: int) -> str:
    try:
        from app.services.outline import reader_ledger

        return reader_ledger(s, book_id, number)
    except Exception:  # noqa: BLE001
        return ""


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


CARRY_REVIEW_KEYS = ("pairwise", "heal")  # v0.17 重新审稿时保留的记录


def carry_review(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """重新审稿会整份替换 review：把多候选比较、自愈记录带过去。"""
    for k in CARRY_REVIEW_KEYS:
        if (old or {}).get(k) is not None and new.get(k) is None:
            new[k] = old[k]  # type: ignore[index]
    return new


def _variant_score(v: dict[str, Any]) -> tuple[int, float]:
    return (int(v.get("review_overall") or 0), -float((v.get("lint") or {}).get("ai_score") or 0))


def pick_by_pairwise(book_id: int, vlist: list[dict[str, Any]], number: int, plan: str,
                     meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """v0.17 多候选选优：擂台式两两比较「哪版更让人想点下一章」（每对正反各比一次）；
    意见不一致时按审稿分（_variant_score）兜底。返回（入选版本, 比较记录）。"""
    with session_scope() as s:
        persona = reader_persona(s.get(Book, book_id))
    gw = get_gateway()
    champ = vlist[0]
    rounds: list[dict[str, Any]] = []
    for challenger in vlist[1:]:
        r = pairwise_compare(gw, champ["content"], challenger["content"], number, plan, persona, meta)
        if r["winner"] is None:
            winner = max((champ, challenger), key=_variant_score)
            how = "两次比较意见不一，按审稿分选"
        else:
            winner = champ if r["winner"] == 0 else challenger
            how = r["reason"] or "成对比较选出"
        rounds.append({"a": champ["id"], "b": challenger["id"], "winner": winner["id"], "votes": r["votes"], "reason": how})
        champ = winner
    return champ, {"winner": champ["id"], "rounds": rounds, "reason": rounds[-1]["reason"] if rounds else ""}


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
        f"- {n}：{v.get('voice', '')}；小动作（偶尔用，全章同一个不超过 2 次）：{'、'.join(v.get('habits') or [])}；神态：{v.get('demeanor', '')}"
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
    prev_params = dict(cp.get("params") or {})
    explicit = bool(prev_params.get("explicit")) if "explicit" in prev_params else variants is not None
    n_var = max(1, min(3, int(variants or settings["default_variants"] or 1)))
    cp["params"] = {"variants": n_var, "instruction": instruction, "explicit": explicit}
    if "pairwise" in prev_params:  # 续跑：沿用断点里定好的多候选
        cp["params"]["pairwise"] = prev_params["pairwise"]
    if no_commit:
        cp["params"]["no_commit"] = True
    if allow_pending:
        cp["params"]["allow_pending"] = [int(x) for x in allow_pending]

    node_id = cp.get("node_id") or ensure_next_chapter_node(book_id, ctx)
    cp["node_id"] = node_id
    # v0.17.1 衔接校正：上一章已经写出来了，先对照它的真实结尾校正本章（和下一章）章纲，避免重做、重复结算
    if not cp.get("synced") and not cp.get("scenes"):
        ctx.progress(6, "章纲衔接校正")
        try:
            from app.services.continuity import sync_chapter_beats

            cp["sync"] = sync_chapter_beats(book_id, node_id)
        except Exception as e:  # noqa: BLE001  校正失败不挡写章
            cp["sync"] = {"changed": False, "reason": f"衔接校正没做成：{e}"[:200]}
        cp["synced"] = True

    with session_scope() as s:
        book = common.get_book(s, book_id)
        node = s.get(OutlineNode, node_id)
        if node is None:
            raise NotFound("断点里的细纲节点已不存在，请重新发起写章")
        cheat = next(iter(common.cards(s, book_id, "cheat")), None)
        recent = [b for b in chapter_beats_list(s, book_id) if int(b.get("number") or 0) < node.order]
        fixed = ensure_opening_beats(dict(node.beats or {}), node.order, cheat, book.tagline or "", recent)
        if fixed != (node.beats or {}):
            node.beats = fixed
            s.add(node)
            s.commit()
            s.refresh(node)
        number, plan = node.order, node_plan_text(node)
        beats = {k: v for k, v in dict(node.beats or {}).items() if k != "scenes"} if cp.get("scenes") else dict(node.beats or {})
        meta = {**common.kit_meta(s, book), "number": number, "beats": beats, "title": book.title,
                "pronoun": common.pronoun(book), "words": book.chapter_words, "platform": book_platform(s, book_id)}
        plan_ctx = scene_plan_context(s, book, node)
        if instruction.strip():
            rb = refs_block(s, book_id, instruction)
            plan_ctx += "\n【作者对本章的额外要求】\n" + instruction.strip() + ("\n" + rb if rb else "")
    cp["number"] = number
    if "beats" not in cp:
        cp["beats"] = beats
    beats = cp["beats"]
    meta["beats"] = beats
    # v0.17 多候选：开篇第 1 章和大爽点章写 2 版，成对比较选优（作者手动指定版本数时照作者的）
    if "pairwise" not in cp["params"]:
        cp["params"]["pairwise"] = bool(is_candidate_chapter(number, beats) and not explicit)
    if cp["params"]["pairwise"]:
        n_var = max(n_var, 2)
        cp["params"]["variants"] = n_var
    save("node")

    # 0) 本章涉及的现实细节先联网核实（未配置搜索模型时跳过）
    if "research" not in cp:
        cp["research"] = research_notes("chapter", plan, book_id, ctx, 5)
    plan += cp["research"]

    # 1) 段落安排（只写事件与局面变化）
    if cp.get("scenes"):
        scenes = cp["scenes"]
        ctx.progress(10, f"第{number}章：从断点续写（已排好 {len(scenes)} 段）")
    else:
        ctx.progress(8, f"第{number}章：排段落")
        raw_scenes = get_gateway().chat_json(
            "scene_plan", system_prompt("scene_plan"),
            render("scene_plan", chapter_plan=plan, min_scenes=MIN_SCENES, max_scenes=MAX_SCENES,
                   opening_rules=scene_plan_rules(beats, number), book_context=plan_ctx),
            meta=meta,
        )
        scenes = normalize_scenes(raw_scenes, beats, None, number)
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
        chapter_words = int(beats.get("words") or book.chapter_words or 2000)
        title = node.title
    meta["voices"] = pack.voices
    meta["beats"] = {**beats, "scenes": scenes}

    # 2) 生成各版本并评估：每版一次写完整章 → 抽状态 → 审稿（每版写完都存断点）
    span = 60 // n_var
    vlist: list[dict[str, Any]] = list(cp.get("variants_done") or [])
    for v in range(len(vlist), n_var):
        lo = 12 + v * span
        partial = cp.get("partial") if (cp.get("partial") or {}).get("variant") == v else None
        if partial and partial.get("content"):
            content = str(partial["content"])
        else:
            content = _write_variant(pack, meta, title, number, scenes, chapter_words, v, ctx, lo, cp.get("research") or "")
            cp["partial"] = {"variant": v, "content": content}
            save(f"draft:{v + 1}")
        ctx.progress(lo + span // 2, f"第{number}章 版本{v + 1}：从正文抽状态账本")
        st = extract_chapter_state(book_id, pack, meta, number, title, content, beats)
        ctx.progress(lo + span - 5, f"第{number}章 版本{v + 1}：校验变更、审稿、人味 lint")
        cs, warns = parse_changes(st["raw_changes"])
        with session_scope() as s:
            known = {c.name for c in common.cards(s, book_id, include_deprecated=True)}
            opens = {f.id or 0: f.desc for f in common.open_foreshadows(s, book_id)}
            cs, warns2 = check_against_ledger(cs, known, opens)
            warns2 += planned_foreshadow_gaps(beats, cs)
            book = common.get_book(s, book_id)
            review, lint, dropped = _evaluate(s, book, pack, content, number, plan, meta, None)
            is_ff = bool(book.fanfic)
        if is_ff:  # v0.13 同人：新写的章节和原著重合偏高时直接提醒
            try:
                from app.services import fanfic as _ff

                ov = _ff.text_overlap(book_id, content)
                if ov.get("level") in ("warn", "high") and ov.get("warning"):
                    warns2.append(str(ov["warning"]))
            except Exception:  # noqa: BLE001
                pass
        vlist.append({
            "id": v + 1, "content": content, "words": count_words(content), "lint": lint.to_dict(),
            "review_overall": review["scores"]["overall"], "review": review, "changes": cs.model_dump(),
            "warnings": warns + warns2 + st["warnings"], "dropped_issues": dropped,
            "end_state": st["end_state"],
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
    cp["result"] = {"chapter_id": chapter_id, "number": number, "variants": n_var, "sync": cp.get("sync"),
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
    use_pair = bool((cp.get("params") or {}).get("pairwise")) and n_var > 1
    if n_var > 1 and not settings["auto_adopt_best"] and not use_pair:
        result["awaiting_adopt"] = True
        result["committed"] = False
        return finish(result)

    if "adopted" not in done:
        pair: dict[str, Any] | None = None
        if use_pair:
            ctx.progress(76, f"第{number}章：{n_var} 版成对比较，挑更想点下一章的那版")
            best, pair = pick_by_pairwise(book_id, vlist, number, plan, meta)
        else:
            best = max(vlist, key=_variant_score)
        with session_scope() as s:
            ch = s.get(Chapter, chapter_id)
            assert ch is not None
            if pair is not None:
                ch.variants = [{**x, "picked": int(x.get("id", 0)) == int(best["id"])} for x in vlist]
            _apply_variant(ch, best)
            if pair is not None:
                ch.review = {**(ch.review or {}), "pairwise": pair}
            s.add(ch)
            s.commit()
        result["adopted_variant"] = best["id"]
        if pair is not None:
            result["pairwise"] = pair
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
        # v0.17：先把摘要算好，后面的章写的时候看得到这一章的前情
        if "presummary" not in done:
            presummarize(chapter_id)
            done.append("presummary")
            save("presummary")
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
        carry_review(old, review2)
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
        ch.review = carry_review(ch.review, review2)
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


def _content_hash(text: str) -> str:
    import hashlib

    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def presummarize(chapter_id: int) -> str:
    """v0.17：精修范围里写好不提交的章先算好摘要（记下对应的正文指纹），后面的章写作时当前情；提交时正文没变就直接复用。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None or not ch.content.strip():
            return ""
        if ch.summary and (ch.changes or {}).get("summary_hash") == _content_hash(ch.content):
            return ch.summary
        book = common.get_book(s, ch.book_id)
        node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
        beats = (node.beats if node else None) or {}
        meta = {**common.kit_meta(s, book), "title": book.title}
        content, number = ch.content, ch.number
    summ = _summarize(content, number, beats, meta)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        if ch.content == content:
            ch.summary = summ
            ch.changes = {**(ch.changes or {}), "summary_hash": _content_hash(content)}
            s.add(ch)
            s.commit()
    return summ


BASELINE_MIN, BASELINE_MAX = 600, 1000


def pick_baseline(content: str, lo: int = BASELINE_MIN, hi: int = BASELINE_MAX) -> str:
    """从一章正文里摘 600–1000 字的连续段落当文风基准：优先对白和叙述都有、段落长短有变化的一段。"""
    paras = [p.strip() for p in (content or "").split("\n") if p.strip()]
    if count_words(content) <= hi:
        return "\n\n".join(paras)
    best, best_score = "", -1.0
    for i in range(len(paras)):
        chunk: list[str] = []
        n = 0
        for p in paras[i:]:
            if n + count_words(p) > hi and n >= lo:
                break
            chunk.append(p)
            n += count_words(p)
        if n < lo:
            continue
        dlg = sum(1 for p in chunk if "“" in p) / len(chunk)
        lens = [count_words(p) for p in chunk]
        spread = (max(lens) - min(lens)) / max(1, max(lens))
        score = (1 - abs(dlg - 0.4)) + spread * 0.5 - (0.3 if i == 0 else 0)
        if score > best_score:
            best, best_score = "\n\n".join(chunk), score
    return best or content[:hi]


def autofill_baseline(book_id: int, content: str) -> bool:
    """v0.17：本书文风基准为空时，第 1 章定稿后自动摘一段回填。作者随时可以在文风页改。"""
    from app.models.tables import Style

    text = pick_baseline(content)
    if count_words(text) < 200:
        return False
    with session_scope() as s:
        st = s.get(Style, book_id) or Style(book_id=book_id)
        if (st.baseline or "").strip():
            return False
        st.baseline = text
        s.add(st)
        s.commit()
    return True


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
        reuse = ch.summary if ch.summary and (ch.changes or {}).get("summary_hash") == _content_hash(content) else ""
    summary = reuse or _summarize(content, number, beats, meta)

    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        book = common.get_book(s, ch.book_id)
        bid = book.id or 0
        raw = dict(ch.changes or {})
        warns = list(raw.pop("warnings", []) or [])
        end_state = raw.pop("end_state", None)
        raw.pop("summary_hash", None)
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
    if ch.number == 1:  # v0.17 文风基准为空时从第 1 章回填
        try:
            autofill_baseline(ch.book_id, ch.content)
        except Exception:  # noqa: BLE001
            pass
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
        ch.review = carry_review(ch.review, review)
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
    return clean_prose(body.strip().strip("<>").strip())


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
        max_tokens=writer_max_tokens(count_words(text)),
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


# ------------------------------------------------------------------ v0.17 带完整上下文的整章重写（自愈、迭代用）

def rewrite_full(chapter_id: int, content: str, instruction: str, route: str | None = None) -> str:
    """整章重写：和写新章一样带完整上下文（写手规则 + 书设定 + 文风基准；前情摘要、最新状态、伏笔、本章任务；
    上一章结尾原文），以 content 为底稿按 instruction 改。返回清洗后的正文（可能为空，由调用方判断能不能用）。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        pack, meta, plan = _pack_for_chapter(s, ch)
        book = common.get_book(s, ch.book_id)
        node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
        words = int(((node.beats if node else None) or {}).get("words") or book.chapter_words or 2000)
        number = ch.number
    voices = "\n".join(f"- {n}：{v.get('voice', '')}" for n, v in pack.voices.items()) or "（未设定）"
    prev = f"【上一章结尾原文（本章开头从这里接）】\n{pack.prev_tail}" if pack.prev_tail else ""
    user = pack.suffix + "\n\n" + render("chapter_rewrite", number=number, scope_label="（全章）", chapter_plan=plan, voices=voices,
                                          context=prev, text=content, instruction=instruction)
    out = get_gateway().chat(
        "chapter_rewrite", [{"role": "system", "content": pack.prefix}, {"role": "user", "content": user}],
        meta={**meta, "text": content, "instruction": instruction, "scope": "chapter"},
        temperature=WRITER_TEMPERATURE, max_tokens=writer_max_tokens(words), route=route,
    )
    return clean_prose(out)


def target_words(chapter_id: int) -> int:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            return 2000
        book = common.get_book(s, ch.book_id)
        node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
        return int(((node.beats if node else None) or {}).get("words") or book.chapter_words or 2000)


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


def polish_voice_job(chapter_id: int, ctx: JobContext, book_id: int | None = None, base: str | None = None) -> dict[str, Any]:
    """语感重塑：只生成润色稿（不落库），结构同改写稿（before/after…），作者对比后 apply-rewrite 采纳、undo 撤回。
    生成后做程序校验，不符的写进 warnings；不会因为任何检测分数自动再改。"""
    with session_scope() as s:
        ch = _require_content(s.get(Chapter, chapter_id))
        if book_id is not None and ch.book_id != book_id:
            raise NotFound("章节不存在")
        pack, meta, _ = _pack_for_chapter(s, ch)
        content, number = (base if base is not None else ch.content), ch.number  # v0.13 批量：可指定底稿
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
        meta={**meta, "text": content, "names": present}, temperature=0.8, max_tokens=writer_max_tokens(count_words(content)),
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
