"""内容/规划层 v0.2：节奏体检、细纲可选字段、写前核对、长篇记忆压缩、新 lint 指标、章末检查。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.config import LintThresholds
from app.lint.humanlint import (
    banned_hits, ending_summary, lint_chapter, single_sentence_waterfall, subject_start_ratio, weak_adverb_density,
)
from app.models.tables import Card, Fact
from app.services.changes import ChangeSet, ForeshadowAction
from app.services.context import (
    chapter_tail, chapter_task_lines, older_index, pick_foreshadows, preflight_check, related_old_chapters, state_block,
)
from app.services.outline import normalize_beats, pacing_audit, rhythm_ledger
from app.services.review import deterministic_issues, ending_issue
from app.services.writing import normalize_scenes, planned_foreshadow_gaps
from app.skills.loader import all_packs, render, system_prompt

TH = LintThresholds()


# ------------------------------------------------------------------ 细纲字段

def test_normalize_beats_keeps_valid_optional_fields_and_drops_junk() -> None:
    raw = {
        "title": "夜雨", "goal": "拿回账本", "outcome": "yes", "payoff_type": "打脸（当众）", "payoff_level": "COMBO",
        "hook_type": "不存在的钩子", "strand": ["quest", "fire", "unknown"], "emotion": "up", "expectation": "钱少坤何时认账",
        "foreshadow": [{"action": "plant", "desc": "豁口", "tier": "long"}, {"action": "bogus", "desc": "x"}],
        "must_avoid": "提前揭晓老周身份",
    }
    b = normalize_beats(raw, 7, 2200)
    assert b["payoff_type"] == "打脸" and b["payoff_level"] == "combo"
    assert "hook_type" not in b
    assert b["strand"] == ["quest", "fire"] and b["emotion"] == "up"
    assert b["foreshadow"] == [{"action": "plant", "id": None, "desc": "豁口", "tier": "long"}]
    assert b["must_avoid"] == ["提前揭晓老周身份"]
    # 旧数据没有这些键：保持原有结构
    old = normalize_beats({"title": "t"}, 1, 2000)
    assert not {"payoff_type", "hook_type", "strand", "emotion"} & set(old)


# ------------------------------------------------------------------ 节奏体检

def _ch(n: int, **kw: Any) -> dict[str, Any]:
    return {"number": n, **kw}


def test_pacing_audit_flags_repeats_and_yes_runs() -> None:
    chs = [_ch(i, payoff_type="打脸", hook_type="危机突降" if i < 4 else "发现", outcome="yes") for i in range(1, 5)]
    issues = pacing_audit(chs)
    assert any("连续 4 章都是「打脸」" in x for x in issues)
    assert any("「危机突降」式章末钩子" in x for x in issues)
    assert any("结果都是 yes" in x for x in issues)
    ok = [_ch(1, payoff_type="打脸", outcome="yes"), _ch(2, payoff_type="真相揭示", outcome="yes-but"),
          _ch(3, payoff_type="打脸", outcome="yes")]
    assert pacing_audit(ok) == []


def test_pacing_audit_strands_levels_and_foreshadow_age() -> None:
    chs = [_ch(i, strand=["quest"], payoff_level="small") for i in range(1, 13)]
    issues = pacing_audit(chs)
    assert any("只走主线" in x for x in issues)
    assert any("感情/人物关系线已经" in x for x in issues)
    assert any("没有组合爽点" in x for x in issues)
    old = SimpleNamespace(id=3, desc="玉佩裂纹", planted_ch=1, last_ch=2)
    mid = SimpleNamespace(id=4, desc="斗笠客", planted_ch=10, last_ch=10)
    issues2 = pacing_audit([_ch(50)], [old, mid], current=50)
    assert any("#3" in x and "红线" in x for x in issues2)
    assert any("#4" in x and "还活着" in x for x in issues2)


def test_rhythm_ledger_only_lists_earlier_chapters() -> None:
    ledger = rhythm_ledger([_ch(1, payoff_type="打脸", hook_type="发现"), _ch(2, outcome="no"), _ch(5, payoff_type="打脸")], before=3)
    assert "第1章：爽点 打脸，钩子 发现" in ledger and "第2章" in ledger and "第5章" not in ledger


# ------------------------------------------------------------------ 写前核对 / 状态 / 记忆

def test_preflight_check_dead_unknown_and_missing_foreshadow() -> None:
    cards = [Card(id=1, book_id=1, type="character", name="林照"), Card(id=2, book_id=1, type="character", name="老周"),
             Card(id=3, book_id=1, type="location", name="七号仓")]
    facts = [Fact(book_id=1, entity_id=2, key="生死", value="已死，被钱家灭口", from_chapter=12)]
    opens = [SimpleNamespace(id=9, desc="铜扣上的豁口", planted_ch=1, last_ch=1)]
    beats = {"characters": ["林照", "老周", "斗笠客"], "location": "七号仓",
             "foreshadow": [{"action": "resolve", "id": None, "desc": "老周隐瞒的过去"},
                            {"action": "advance", "id": None, "desc": "铜扣上的豁口"}]}
    issues = preflight_check(beats, cards, facts, opens, number=60)
    assert any("老周" in x and "已死" in x for x in issues)
    assert any("斗笠客" in x and "不在设定库" in x for x in issues)
    assert any("老周隐瞒的过去" in x and "找不到" in x for x in issues)
    assert not any("铜扣上的豁口」在伏笔池里找不到" in x for x in issues)
    assert any("#9" in x and "没动静" in x for x in issues)  # 59 章没推进的伏笔


def test_state_block_groups_by_entity_and_includes_global_facts() -> None:
    cards = [Card(id=1, book_id=1, type="character", name="林照")]
    facts = [Fact(book_id=1, entity_id=1, key="情绪", value="压着火", from_chapter=3),
             Fact(book_id=1, entity_id=1, key="位置", value="七号仓", from_chapter=4),
             Fact(book_id=1, entity_id=None, key="故事时间", value="入秋第三天夜里", from_chapter=4),
             Fact(book_id=1, entity_id=99, key="位置", value="无关的人", from_chapter=1)]
    text = state_block(facts, cards, cards)
    line = next(x for x in text.splitlines() if x.startswith("- 林照"))
    assert line.index("位置") < line.index("情绪")  # 关键键在前
    assert "全书·故事时间：入秋第三天夜里" in text and "无关的人" not in text


def _chap(n: int, summary: str) -> Any:
    return SimpleNamespace(id=n, number=n, title=f"t{n}", summary=summary)


def test_long_book_memory_compression() -> None:
    older = [_chap(i, f"第{i}章发生了一件事情。后面还有很多细节" + "字" * 80) for i in range(1, 61)]
    older[4] = _chap(5, "老周第一次提到铜扣上的豁口。")
    related = related_old_chapters(older, {"老周"}, ["铜扣上的豁口"])
    assert [c.number for c in related][:1] == [5]
    idx = older_index(older, exclude={5})
    assert len(idx) <= 700 and "第60章" in idx and "后面还有很多细节" not in idx
    assert "第1章" not in idx or idx.count("\n") < 59  # 远处按间隔抽样，不会全量塞入


def test_pick_foreshadows_prioritises_planned_then_stale() -> None:
    fs = [SimpleNamespace(id=i, desc=d, planted_ch=p, last_ch=p, status="planted")
          for i, d, p in ((1, "铜扣豁口", 1), (2, "斗笠客", 30), (3, "老周的过去", 2), (4, "钱家账房", 45))]
    picked = pick_foreshadows(fs, {"老周"}, ["斗笠客"], current=50)
    ids = [f.id for f in picked]
    assert ids[0] == 2 and 3 in ids and 1 in ids  # 计划内 → 相关 → 超期
    assert 4 not in ids  # 刚推进过、不相关、不超期


def test_chapter_tail_cuts_at_paragraphs() -> None:
    content = "\n\n".join(["第一段很长" * 40, "第二段。", "最后一段，门开了。"])
    tail = chapter_tail(content, 50)
    assert tail.endswith("最后一段，门开了。") and "第一段" not in tail


def test_chapter_task_lines_golden_three_and_payoff_shape() -> None:
    lines = chapter_task_lines({"payoff_type": "扮猪吃虎", "payoff": "当众认账", "hook_end": "门外有人", "hook_type": "发现",
                                "info_gap": "读者知道他已筑基"}, 2)
    text = "\n".join(lines)
    assert "黄金三章·第2章" in text and "表面示弱" in text and "期待 → 压抑 → 释放" in text
    assert "类型：发现" in text and "信息差" in text
    assert not any("黄金三章" in x for x in chapter_task_lines({}, 9))


def test_planned_foreshadow_gaps() -> None:
    beats = {"foreshadow": [{"action": "plant", "desc": "斗笠客"}, {"action": "resolve", "id": 3, "desc": "老周的过去"}]}
    cs = ChangeSet(foreshadow=[ForeshadowAction(action="plant", desc="人群后的斗笠客")])
    warns = planned_foreshadow_gaps(beats, cs)
    assert len(warns) == 1 and "回收" in warns[0]


def test_normalize_scenes_keeps_turn_and_phase() -> None:
    raw = {"scenes": [{"goal": "g", "outcome": "no", "turn": "老周知道了账本在谁手里", "payoff_phase": "setup"},
                      {"goal": "g2", "outcome": "yes", "payoff_phase": "bogus"}]}
    scenes = normalize_scenes(raw, {"characters": ["林照"], "outcome": "yes-but"}, ["雨声"])
    assert scenes[0]["turn"].startswith("老周") and scenes[0]["payoff_phase"] == "setup"
    assert "payoff_phase" not in scenes[1] and len(scenes) >= 3


# ------------------------------------------------------------------ lint

def test_new_banned_patterns_narration_only() -> None:
    text = ("他笑了一下，带着一丝不易察觉的嘲讽。她声音不大，却压住了全场。这一刻他终于明白了。"
            "他感到一丝失落。笑容消失，取而代之的是冰冷。他眼里淬了毒。")
    words = {h["word"] for h in banned_hits(text)}
    for w in ("万能状语：，带着一丝/几分", "无情绪声线", "总结收束：终于明白/这才意识到", "告知式心理：他/她感到",
              "取而代之的是", "模板通感：淬了/淬着"):
        assert w in words, w
    quoted = "“我终于明白了，带着一丝希望。”他说。"
    words2 = {h["word"] for h in banned_hits(quoted)}
    assert "总结收束：终于明白/这才意识到" not in words2 and "万能状语：，带着一丝/几分" not in words2


def test_weak_adverb_subject_waterfall_and_ending_metrics() -> None:
    weak = "他缓缓起身，微微点头，轻轻推门，淡淡地看了一眼。" * 3
    assert weak_adverb_density(weak) > 3
    assert weak_adverb_density("“慢慢说，轻轻放。”他说。") == 0  # 台词不计
    mono = "。".join(["他推开门", "他看了一眼屋里", "他把账本放下", "他坐下来", "他没说话", "他等着", "他抬起头", "他站起来",
                     "他走到窗边"]) + "。"
    assert subject_start_ratio(mono) > 0.9
    falls = "\n".join(["他走了。", "门关了。", "风停了。", "灯灭了。", "雨还在下。", "没人说话。"])
    ratio, run = single_sentence_waterfall(falls)
    assert run == 6 and ratio == 1.0
    assert ending_summary("他推开门。\n\n这一切，才刚刚开始。") == "才刚刚开始"
    assert ending_summary("他推开门。\n\n门后站着一个本该死了三年的人。") is None
    r = lint_chapter(falls + "\n这一切，才刚刚开始。", TH)
    d = r.to_dict()
    assert {"weak_adverb_per_k", "subject_start_ratio", "sentence_len_cv", "waterfall_run"} <= set(d)
    assert any("单句成段" in w for w in r.warnings) and any("章末用总结" in w for w in r.warnings)


# ------------------------------------------------------------------ 审稿

def test_review_flags_summary_ending_with_verifiable_quote() -> None:
    content = "林照推开门，雨灌进来。\n\n他把账本拍在桌上。\n\n他不知道的是，更大的风暴即将来临。"
    issue = ending_issue(content)
    assert issue and issue["dimension"] == "hook" and issue["severity"] == "mid" and issue["quote"] in content
    assert ending_issue("林照推开门。\n\n门后站着一个本该死了三年的人。") is None
    assert ending_issue("他推开门。\n\n“这一切才刚刚开始。”") is None  # 台词收尾不算
    issues = deterministic_issues(content, "林照", [], 5)
    assert any("总结" in i["comment"] for i in issues)


# ------------------------------------------------------------------ 规则包 / 提示词

def test_rule_packs_parse_and_new_sections_loaded() -> None:
    packs = {p.stage: p for p in all_packs()}
    assert "节奏账本" in packs["outline"].body and "爽点三拍" in packs["chapter_plan"].body
    assert any("oh-story" in s.repo for s in packs["humanize"].sources)
    assert all(s.license for p in packs.values() for s in p.sources)
    assert "章末断在变化发生的那一刻" in system_prompt("writing_scene")
    rv = render("review", number=1, chapter_plan="{}", content="正文", context="底账X")
    assert "底账X" in rv and "$" not in rv
    ex = render("expand", book_context="", node_level="arc", node_title="", node_summary="", siblings="", recent="",
                open_foreshadows="", rhythm="R1", pacing="P1", instruction="", schema="{}")
    assert "R1" in ex and "P1" in ex and "$" not in ex
