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
from app.jobs.manager import JobContext
from app.lint.humanlint import LintResult, count_words, lint_chapter, paragraphs, sentence_stats
from app.llm.gateway import get_gateway
from app.llm.mock import kit_for
from app.models.tables import Book, Card, Chapter, Fact, Foreshadow, OutlineNode, utcnow
from app.services import common
from app.services.changes import ChangeSet, check_against_ledger, match_foreshadow, parse_changes, split_output
from app.services.common import Conflict, NotFound
from app.services.context import ContextPack, build_context_pack
from app.services.outline import ensure_next_chapter_node, node_plan_text
from app.services.review import run_review
from app.skills.loader import render, system_prompt

WRITING_SETTINGS_KEY = "writing_settings"
DEFAULT_WRITING_SETTINGS: dict[str, Any] = {"auto_adopt_best": False, "auto_commit": True, "default_variants": 1}
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


# ------------------------------------------------------------------ lint 辅助

def lint_for(s: Session, book_id: int, content: str, number: int, exclude_chapter_id: int | None = None) -> LintResult:
    others = [c.content for c in common.committed_chapters(s, book_id) if c.id != exclude_chapter_id]
    names = [c.name for c in common.cards(s, book_id)]
    return lint_chapter(content, get_settings().lint, others, names, number)


# ------------------------------------------------------------------ 场景节拍

def normalize_scenes(raw: Any, beats: dict[str, Any], sensory_pool: list[str]) -> list[dict[str, Any]]:
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
    return scenes


def _sensory_pool(s: Session, book: Book) -> list[str]:
    pool: list[str] = []
    for c in common.cards(s, book.id or 0, "location"):
        sen = (c.data or {}).get("sensory")
        if sen:
            pool.extend([x for x in re.split(r"[，,；;]", str(sen)) if x.strip()])
    pool.extend(kit_for(book.genre, book.gender)["sensory"])
    return pool


# ------------------------------------------------------------------ 生成一版

def _write_variant(
    pack: ContextPack, meta: dict[str, Any], node_title: str, number: int, plan: str,
    scenes: list[dict[str, Any]], chapter_words: int, variant: int, ctx: JobContext, pct: tuple[int, int],
) -> tuple[str, str | None]:
    gw = get_gateway()
    total = len(scenes)
    per = max(300, chapter_words // total)
    texts: list[str] = []
    raw_changes: str | None = None
    for i, sc in enumerate(scenes, 1):
        ctx.progress(pct[0] + (pct[1] - pct[0]) * (i - 1) // total, f"第{number}章 版本{variant + 1}：写第 {i}/{total} 个场景")
        last = i == total
        changes_instruction = (
            "这是本章最后一个场景。正文写完后另起一行写 ---CHANGES---，再给出覆盖全章的变更声明 JSON。"
            if last else "不要写 ---CHANGES---。"
        )
        prev_tail = texts[-1][-200:] if texts else "（本章开头）"
        user = pack.suffix + "\n\n" + render(
            "writing_scene", number=number, chapter_title=node_title, scene_index=i, scene_total=total,
            scene_words=per, chapter_plan=plan, scene=json.dumps(sc, ensure_ascii=False),
            previous_tail=prev_tail, changes_instruction=changes_instruction,
        )
        out = gw.chat(
            "writing_scene",
            [{"role": "system", "content": pack.prefix}, {"role": "user", "content": user}],
            meta={**meta, "scene": sc, "scene_index": i, "scene_total": total, "scene_words": per,
                  "variant": variant, "include_changes": last},
            temperature=0.9,
        )
        body, raw = split_output(out)
        if last:
            raw_changes = raw
        texts.append(_clean_scene(body))
    return "\n\n".join(texts), raw_changes


def _clean_scene(text: str) -> str:
    t = re.sub(r"^\s*(#+.*|场景[一二三四五六0-9]+[:：].*)\n", "", text.strip())
    return t.strip()


def _evaluate(
    s: Session, book: Book, pack: ContextPack, content: str, number: int, plan: str, meta: dict[str, Any],
    exclude_chapter_id: int | None,
) -> tuple[dict[str, Any], LintResult, int]:
    review, dropped = run_review(get_gateway(), content, number, plan, pack.protagonist, pack.required_chars, meta,
                                 context=pack.state_text)
    lint = lint_for(s, book.id or 0, content, number, exclude_chapter_id)
    return review, lint, dropped


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
        if w.startswith(("章末用总结", "弱化副词")):
            problems.append(f"- {w}")
    if not problems:
        return content, 0
    raw = get_gateway().chat_json(
        "humanize", system_prompt("humanize"),
        render("humanize", problems="\n".join(problems), content=content),
        meta={**meta, "content": content}, temperature=0.5,
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


def thicken_targets(content: str, lint: LintResult, max_n: int) -> list[dict[str, Any]]:
    paras = paragraphs(content)
    targets: dict[int, str] = {}
    for i in lint.bare_paragraphs:
        targets.setdefault(i, "裸对白：对白前后缺少动作、神态或环境")
    for i in lint.summary_paragraphs:
        targets.setdefault(i, "概述式叙述：一句话带过，需要写成可见的场面")
    for i, p in enumerate(paras):
        st = sentence_stats(p)
        if st["count"] >= 3 and st["short_ratio"] >= 0.6:
            targets.setdefault(i, "短句碎段：连续动作拆得太碎，合并成长短交替的句子")
    out = [{"index": i, "problem": prob, "text": paras[i]} for i, prob in sorted(targets.items()) if i < len(paras)]
    return out[:max_n]


_QUOTE_RX = re.compile(r"“[^”]*”")


def thicken(content: str, lint: LintResult, pack_voices: dict[str, dict[str, Any]], all_names: list[str], meta: dict[str, Any]) -> tuple[str, int, int]:
    """描写增厚：程序定位段落 → 只把这些段落交给 LLM → 校验后回贴。返回（新正文, 定位数, 应用数）。"""
    th = get_settings().lint
    targets = thicken_targets(content, lint, th.thicken_max_paragraphs)
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
        "thicken", system_prompt("thicken"),
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

def write_next(book_id: int, ctx: JobContext, variants: int | None = None) -> dict[str, Any]:
    with session_scope() as s:
        book = common.get_book(s, book_id)
        pending = s.exec(
            select(Chapter).where(Chapter.book_id == book_id, Chapter.status != "committed").order_by(Chapter.number)
        ).first()
        if pending is not None:
            raise Conflict(f"第{pending.number}章尚未提交（{pending.status}），请先选定版本并提交")
        settings = writing_settings(s)
    n_var = max(1, min(3, int(variants or settings["default_variants"] or 1)))

    node_id = ensure_next_chapter_node(book_id, ctx)

    with session_scope() as s:
        book = common.get_book(s, book_id)
        node = s.get(OutlineNode, node_id)
        assert node is not None
        number, plan = node.order, node_plan_text(node)
        beats = dict(node.beats or {})
        meta = {**common.kit_meta(s, book), "number": number, "beats": beats, "title": book.title,
                "pronoun": common.pronoun(book), "words": book.chapter_words}
        pool = _sensory_pool(s, book)

    # 0) 本章涉及的现实细节先联网核实（未配置搜索模型时跳过）
    plan += research_notes("chapter", plan, book_id, ctx, 5)

    # 1) 场景节拍
    ctx.progress(8, f"第{number}章：拆分场景节拍")
    raw_scenes = get_gateway().chat_json(
        "scene_plan", system_prompt("scene_plan"),
        render("scene_plan", chapter_plan=plan, min_scenes=MIN_SCENES, max_scenes=MAX_SCENES),
        meta={**meta, "sensory_pool": pool},
    )
    scenes = normalize_scenes(raw_scenes, beats, pool)
    with session_scope() as s:
        node = s.get(OutlineNode, node_id)
        assert node is not None
        node.beats = {**(node.beats or {}), "scenes": scenes}
        s.add(node)
        s.commit()
        book = common.get_book(s, book_id)
        pack = build_context_pack(s, book, node)
        chapter_words = book.chapter_words
        title = node.title
    meta["voices"] = pack.voices
    meta["beats"] = {**beats, "scenes": scenes}

    # 2) 生成各版本并评估
    span = 60 // n_var
    vlist: list[dict[str, Any]] = []
    for v in range(n_var):
        lo = 12 + v * span
        content, raw_changes = _write_variant(pack, meta, title, number, plan, scenes, chapter_words, v, ctx, (lo, lo + span - 5))
        ctx.progress(lo + span - 5, f"第{number}章 版本{v + 1}：校验变更、审稿、人味 lint")
        cs, warns = parse_changes(raw_changes)
        with session_scope() as s:
            known = {c.name for c in common.cards(s, book_id)}
            opens = {f.id or 0: f.desc for f in common.open_foreshadows(s, book_id)}
            cs, warns2 = check_against_ledger(cs, known, opens)
            warns2 += planned_foreshadow_gaps(beats, cs)
            review, lint, dropped = _evaluate(s, book, pack, content, number, plan, meta, None)
        vlist.append({
            "id": v + 1, "content": content, "words": count_words(content), "lint": lint.to_dict(),
            "review_overall": review["scores"]["overall"], "review": review, "changes": cs.model_dump(),
            "warnings": warns + warns2, "dropped_issues": dropped,
        })

    # 3) 建章（草稿）
    with session_scope() as s:
        ch = Chapter(book_id=book_id, number=number, title=title, status="draft", variants=vlist,
                     outline_node_id=node_id, content="", words=0)
        s.add(ch)
        s.commit()
        s.refresh(ch)
        chapter_id = ch.id or 0

    result: dict[str, Any] = {"chapter_id": chapter_id, "number": number, "variants": n_var,
                              "context": pack.summary(), "scenes": len(scenes), "preflight": pack.preflight}
    if n_var > 1 and not settings["auto_adopt_best"]:
        result["awaiting_adopt"] = True
        result["committed"] = False
        return result

    best = max(vlist, key=_variant_score)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        _apply_variant(ch, best)
        s.add(ch)
        s.commit()
    result["adopted_variant"] = best["id"]

    # 4) 定点重写 / 精修（最多 1 轮）
    ctx.progress(80, f"第{number}章：定点重写与描写增厚")
    refine = refine_chapter(chapter_id, pack, meta, plan)
    result.update(refine)

    # 5) 提交
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        passed = bool((ch.review or {}).get("passed"))
    if passed and settings["auto_commit"]:
        ctx.progress(92, f"第{number}章：原子提交")
        commit_chapter(chapter_id)
        result["committed"] = True
    else:
        result["committed"] = False
        result["reason"] = "审稿仍有 high 问题，留作草稿等作者修改后提交" if not passed else "已关闭自动提交，等待作者确认"
    return result


def _apply_variant(ch: Chapter, v: dict[str, Any]) -> None:
    ch.content = v["content"]
    ch.words = count_words(v["content"])
    ch.review = v.get("review")
    ch.lint = v.get("lint")
    ch.changes = {**(v.get("changes") or {}), "warnings": v.get("warnings") or []}
    ch.status = "reviewing"
    ch.updated_at = utcnow()


def refine_chapter(chapter_id: int, pack: ContextPack, meta: dict[str, Any], plan: str) -> dict[str, Any]:
    th = get_settings().lint
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        content, review, number, book_id = ch.content, ch.review or {}, ch.number, ch.book_id
        lint = lint_for(s, book_id, content, number, chapter_id)
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


def commit_chapter(chapter_id: int) -> Chapter:
    """原子提交：章节状态、摘要、新实体卡、facts、伏笔、大纲节点状态一个事务内写入。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        if ch.status == "committed":
            return ch
        if not ch.content.strip():
            raise Conflict("章节正文为空；多版本章节请先 adopt 一个版本")
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
        cs = ChangeSet.model_validate(raw) if raw else ChangeSet()
        card_by_name = {c.name: c for c in common.cards(s, bid)}
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
        return ch


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
            "pronoun": common.pronoun(book)}
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


def humanize_chapter_job(chapter_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        ch = _require_content(s.get(Chapter, chapter_id))
        pack, meta, _ = _pack_for_chapter(s, ch)
        before = lint_for(s, ch.book_id, ch.content, ch.number, ch.id)
        content, review = ch.content, ch.review
    ctx.progress(30, "定点清理 AI 腔")
    content, applied = patch_rewrite(content, review, before, meta)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        after = lint_for(s, ch.book_id, content, ch.number, ch.id)
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
    content, located, applied = thicken(content, before, pack.voices, pack.all_names, meta)
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        after = lint_for(s, ch.book_id, content, ch.number, ch.id)
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
    ctx.progress(20, "按要求改写" + ("选中的文字" if scope == "selection" else "全章"))
    out = get_gateway().chat(
        "chapter_rewrite", [{"role": "system", "content": system_prompt("chapter_rewrite")}, {"role": "user", "content": user}],
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
