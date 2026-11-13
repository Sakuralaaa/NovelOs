"""v0.6 写作质量：样章回归（新 lint 抓得到人工审稿指出的问题）、场景状态账本、开篇硬约束、审稿新维度。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import LintThresholds
from app.lint.humanlint import (
    catchphrase_report, crowd_shot_paragraphs, intensifier_report, lint_chapter, measure_errors, sentence_at,
)
from app.llm.gateway import LLMGateway
from app.services.outline import ensure_opening_beats, normalize_beats
from app.services.review import DIMENSIONS, WEIGHTS, compute_scores, deterministic_issues, quote_in_text, run_review
from app.services.scene_state import (
    merge_state, parse_scene_state, prop_move_warnings, render_state, scene_budget_lines, scene_rules, split_scene_output,
)
from app.services.writing import enforce_scene_rules, normalize_scenes, scene_plan_rules
from app.skills.loader import render, system_prompt
from conftest import wait_job

SAMPLE = (Path(__file__).parent / "fixtures" / "ch1_sample_2026-11-13.txt").read_text(encoding="utf-8")
TH = LintThresholds()


# ------------------------------------------------------------------ 样章回归：lint

def test_sample_intensifiers_overuse() -> None:
    rep = {d["word"]: d for d in intensifier_report(SAMPLE)}
    assert rep["死死"]["count"] == 5 and rep["死死"]["over"]
    assert rep["硬生生"]["count"] == 3 and rep["硬生生"]["over"]  # 硬生生 ×2 + 生生 ×1 合并计
    assert rep["一把（抓/掐/撕…）"]["over"]
    assert not rep["猛地"]["over"]  # 2 次在额度内


def test_sample_dialogue_tics_and_catchphrase() -> None:
    lint = lint_chapter(SAMPLE, TH, chapter_number=1)
    tics = {d["word"]: d for d in lint.dialogue_tics}
    assert tics["嘛"]["count"] == 4 and tics["嘛"]["over"]
    assert tics["对吧"]["count"] == 3 and tics["对吧"]["over"]
    # 人物卡口头禅：按 voice 卡统计
    cps = catchphrase_report(SAMPLE, {"韩铎": ["嘛", "对吧？"], "叶承": ["九十天"]})
    by = {(d["who"], d["word"]): d for d in cps}
    assert by[("韩铎", "嘛")]["over"] and by[("韩铎", "对吧")]["count"] == 3
    assert by[("叶承", "九十天")]["count"] >= 3


def test_sample_cliche_similes_and_measure() -> None:
    lint = lint_chapter(SAMPLE, TH, chapter_number=1)
    words = {d["word"] for d in lint.cliche_similes}
    assert {"空气像灌了铅", "像砂纸在磨", "脊背/背脊像铁条标枪"} <= words
    ms = measure_errors(SAMPLE)
    assert len(ms) == 1 and ms[0]["match"] == "一柄生了锈的万斤铁砣" and "块" in ms[0]["hint"]
    assert ms[0]["quote"] in SAMPLE


def test_sample_crowd_shots_and_warnings() -> None:
    assert len(crowd_shot_paragraphs(SAMPLE)) > 3
    lint = lint_chapter(SAMPLE, TH, chapter_number=1)
    d = lint.to_dict()
    for k in ("intensifiers", "cliche_similes", "measure_errors", "crowd_shots", "dialogue_tics", "catchphrases", "fix_targets"):
        assert k in d
    assert d["crowd_shots"] > 3
    text = "\n".join(lint.warnings)
    assert "死死×5" in text and "一柄生了锈的万斤铁砣" in text and "「嘛」×4" in text and "群众/配角反应镜头" in text
    assert lint.needs_patch(TH)  # 手艺类问题会触发定点修整


def test_fix_targets_are_verbatim_quotes() -> None:
    lint = lint_chapter(SAMPLE, TH, chapter_number=1)
    kinds = {t["kind"] for t in lint.fix_targets}
    assert {"重复强化词", "陈词比喻", "量词搭配", "口头禅超频"} <= kinds
    assert all(t["quote"] in SAMPLE and len(t["quote"]) >= 4 for t in lint.fix_targets)
    # 强化词只点名超出额度的那几处（死死 5 次、额度 2 → 3 处）
    assert sum(1 for t in lint.fix_targets if t["word"] == "死死") == 3


def test_sentence_at_is_substring() -> None:
    i = SAMPLE.index("铁砣")
    s = sentence_at(SAMPLE, i)
    assert s in SAMPLE and "铁砣" in s and not s.startswith("”")


def test_clean_text_has_no_craft_problems() -> None:
    clean = ("叶承把铲刀插回门框缝里，转身看韩铎。“三十八万，不卖。”韩铎没接话，把合同往柜台上一放。\n\n"
             "叶承伸手按住合同封皮，指腹压着烫金的字。三千七百块，撑不过三个月，这人算准了才来。")
    lint = lint_chapter(clean, TH, chapter_number=1)
    assert not lint.fix_targets and not lint.measure_errors and not lint.cliche_similes


# ------------------------------------------------------------------ 审稿：新维度 + 程序检查

def test_review_dimensions_and_weights() -> None:
    assert "continuity" in DIMENSIONS and "semantics" in DIMENSIONS
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    sc = compute_scores([{"severity": "mid", "dimension": "continuity", "quote": "x", "comment": ""}])
    assert sc["continuity"] == 90 and sc["semantics"] == 100


def test_review_mock_on_sample_has_new_dimensions() -> None:
    review, _ = run_review(LLMGateway(), SAMPLE, 1, "{}", "叶承", ["叶承", "韩铎", "陆昭"], {"protagonist": "叶承"},
                           cheat_terms=["传功系统"])
    assert {"continuity", "semantics"} <= set(review["scores"])
    dims = {i["dimension"] for i in review["issues"]}
    assert "continuity" in dims and "semantics" in dims
    sem = [i for i in review["issues"] if i["dimension"] == "semantics"]
    assert any("没有上限" in i["quote"] for i in sem)          # 语义写反（mock 近似）
    assert any("一柄" in i["comment"] for i in sem)           # 量词错误（程序检查）
    assert any("金手指" in i["comment"] for i in review["issues"] if i["dimension"] == "payoff")  # 第 1 章卖点没露面
    assert all(quote_in_text(i["quote"], SAMPLE) for i in review["issues"])


def test_review_prompt_and_alias() -> None:
    p = render("review", number=1, chapter_plan="{}", context="", content="x")
    assert "continuity" in p and "semantics" in p and "前文「" in p
    assert "连续性与语义" in system_prompt("review")
    from app.services.review import validate_issues
    kept, _ = validate_issues({"issues": [{"severity": "mid", "dimension": "physics", "quote": "正堂里的空气像灌了铅。", "comment": ""}]}, SAMPLE)
    assert kept[0]["dimension"] == "continuity"


def test_cheat_check_only_chapter_one() -> None:
    assert any("金手指" in i["comment"] for i in deterministic_issues(SAMPLE, "叶承", [], 1, ["传功系统"]))
    assert not any("金手指" in i["comment"] for i in deterministic_issues(SAMPLE, "叶承", [], 2, ["传功系统"]))
    assert not any("金手指" in i["comment"] for i in deterministic_issues(SAMPLE, "叶承", [], 1, ["承武"]))


# ------------------------------------------------------------------ 场景状态账本

STATE_A = {"cast": [{"name": "韩铎", "position": "门槛外第一级石阶", "facing": "面朝堂屋", "holding": ["硬壳烫金合同（左手）"],
                     "wearing": "定制西装、黑皮鞋", "body": "右臂钛合金外骨骼"}],
           "props": [{"name": "合同", "where": "韩铎左手", "state": "硬壳烫金"}], "env": "阴天上午"}


def test_split_scene_output_any_order() -> None:
    body, st, ch = split_scene_output("正文。\n---STATE---\n{\"cast\":[]}\n---CHANGES---\n{\"new_entities\":[]}")
    assert body == "正文。" and st.startswith("{") and ch.startswith("{")
    body, st, ch = split_scene_output("正文。\n---CHANGES---\n{}\n---STATE---\n{\"a\":1}")
    assert body == "正文。" and st == '{"a":1}' and ch == "{}"
    assert split_scene_output("只有正文") == ("只有正文", None, None)


def test_parse_merge_render_state() -> None:
    st, w = parse_scene_state("```json\n" + json.dumps(STATE_A, ensure_ascii=False) + "\n```")
    assert st and not w and st["cast"][0]["holding"] == ["硬壳烫金合同（左手）"]
    assert parse_scene_state(None)[0] is None and parse_scene_state("不是json")[1]
    nxt = {"cast": [{"name": "叶承", "position": "门槛内", "facing": "面朝街"}], "props": [{"name": "合同", "where": "柜台上"}]}
    merged = merge_state(st, nxt)
    names = {c["name"] for c in merged["cast"]}
    assert names == {"韩铎", "叶承"}  # 没提到的人物保留
    assert next(p for p in merged["props"] if p["name"] == "合同")["state"] == "硬壳烫金"  # 未给的字段沿用
    text = render_state(merged, "上一场景结束时的状态账本")
    assert "韩铎｜位置：门槛外第一级石阶" in text and "道具·合同｜在：柜台上" in text
    assert "还没有账本" in render_state(None, "x")


def test_prop_teleport_warning() -> None:
    nxt = {"cast": [], "props": [{"name": "合同", "where": "柜台上", "state": "硬壳"}]}
    assert prop_move_warnings(STATE_A, nxt, "叶承扫了一眼柜台，一把抓起那叠厚纸。", 3)
    assert not prop_move_warnings(STATE_A, nxt, "韩铎把合同拍在柜台上。", 3)


def test_scene_budget_lines() -> None:
    voices = {"韩铎": {"catchphrases": ["嘛"]}, "叶承": {"catchphrases": []}}
    lines = scene_budget_lines([SAMPLE[:1500]], ["韩铎", "叶承"], voices)
    joined = "\n".join(lines)
    assert "韩铎的口头禅「嘛」本章已用" in joined and "本场景不要再用" in joined
    assert "群众/配角反应镜头本章已用" in joined
    assert "这些词本章已经用够" not in scene_budget_lines([], [], voices)[-1]


def test_scene_rules_opening_cheat_inner_hook() -> None:
    sc = {"opening": "韩铎把合同拍在门框上", "cheat": "让「传功系统」露一次苗头"}
    r1 = "\n".join(scene_rules(1, 1, 4, sc, {}, "叶承"))
    assert "前三行" in r1 and "传功系统" in r1 and "叶承在本场景至少有一处" in r1 and "不要提前写章末钩子" in r1
    r4 = "\n".join(scene_rules(5, 4, 4, {"main_hook": "门外来了人"}, {}, "叶承"))
    assert "前三行" not in r4 and "1 个主钩" in r4 and "门外来了人" in r4


def test_enforce_scene_rules_and_opening_beats() -> None:
    class Cheat:
        name, summary, data = "传功系统", "教徒即涨修为", {"input": "收下弟子并传授一式"}
    beats = ensure_opening_beats(normalize_beats({"conflict": "集团逼签合同", "hook_end": "电表箱上的断电单"}, 1, 2000), 1, Cheat())
    assert "传功系统" in beats["cheat_beat"] and "集团逼签合同" in beats["opening_hook"]
    assert "cheat_beat" not in ensure_opening_beats({"conflict": "x"}, 2, Cheat())
    assert "opening_hook" not in ensure_opening_beats({"conflict": "x"}, 4, Cheat())
    assert ensure_opening_beats({}, 1, None, "教徒即涨修为")["cheat_beat"].endswith("教徒即涨修为")
    raw = {"scenes": [{"goal": "a", "outcome": "no", "payoff_phase": "setup", "exit_hook": "h1"},
                      {"goal": "b", "outcome": "yes", "payoff_phase": "delivery", "exit_hook": "h2"},
                      {"goal": "c", "outcome": "yes", "exit_hook": "h3", "relations": "陆昭：被清退的前学员，叫叶馆主"}]}
    scenes = normalize_scenes(raw, beats, ["雨声"], 1)
    assert scenes[0]["opening"] and scenes[1]["cheat"] == beats["cheat_beat"]
    assert "exit_hook" not in scenes[-1] and scenes[-1]["main_hook"] == "电表箱上的断电单"
    assert scenes[-1]["relations"].startswith("陆昭")
    # 模型自己认领了 cheat 的不覆盖
    s2 = enforce_scene_rules([{"goal": "x", "cheat": "自定"}, {"goal": "y"}], beats, 1)
    assert s2[0]["cheat"] == "自定" and "cheat" not in s2[1]
    rules = scene_plan_rules(beats, 1)
    assert "第一个场景的第一拍就是冲突" in rules and "cheat" in rules and "不超过 3 个" in rules


def test_prompts_mention_new_rules() -> None:
    sp = system_prompt("writing_scene")
    assert "状态账本说了算" in sp and "---STATE---" in sp and "开篇三行见冲突" in sp
    assert "cheat_beat" in system_prompt("scene_plan")
    up = render("writing_scene", number=1, chapter_title="t", scene_index=1, scene_total=3, scene_words=500, chapter_plan="{}",
                scene="{}", chapter_so_far="（本章开头）", state_block="【账本】", budget="- 无", scene_rules="- r", output_instruction="o")
    assert "<chapter_so_far>" in up and "【账本】" in up and "没有上限" in up and "$" not in up


# ------------------------------------------------------------------ 集成：mock 全流程里账本逐场传递、第 1 章金手指进节拍

def test_mock_pipeline_passes_state_between_scenes(client: TestClient, monkeypatch: Any) -> None:
    import app.services.writing as writing

    seen: list[tuple[int, str]] = []
    real = writing.get_gateway()

    class Spy:
        def __getattr__(self, k: str) -> Any:
            return getattr(real, k)

        def chat(self, task: str, messages: list[dict[str, str]], **kw: Any) -> str:
            if task == "writing_scene":
                seen.append((int((kw.get("meta") or {}).get("scene_index") or 0), messages[-1]["content"]))
            return real.chat(task, messages, **kw)

    monkeypatch.setattr(writing, "get_gateway", lambda: Spy())

    j = wait_job(client, client.post("/api/ideas/generate", json={"gender": "male", "count": 1}).json())
    book = client.post(f"/api/ideas/{j['result']['idea_ids'][0]}/adopt").json()
    bid = book["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    ch1_node = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "chapter" and n["order"] == 1)
    assert ch1_node["beats"].get("cheat_beat") and ch1_node["beats"].get("opening_hook")

    r = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
    ch = client.get(f"/api/chapters/{r['chapter_id']}").json()
    assert "---STATE---" not in ch["content"]
    assert ch["changes"]["end_state"]["cast"]  # 本章结束账本留给下一章
    scene1 = next(c for i, c in seen if i == 1)
    scene2 = next(c for i, c in seen if i == 2)
    assert "上一章结束时的状态账本" in scene1 and "前三行" in scene1
    assert "上一场景结束时的状态账本" in scene2 and "道具·" in scene2 and "<chapter_so_far>" in scene2
    lint = ch["lint"]
    assert "fix_targets" in lint and "crowd_shots" in lint
    assert {"continuity", "semantics"} <= set(ch["review"]["scores"])

    # 第 2 章第一个场景从第 1 章的结束账本接（提交后账本仍保留）
    if not r.get("committed"):
        assert client.post(f"/api/chapters/{r['chapter_id']}/commit").status_code == 200
    assert client.get(f"/api/chapters/{r['chapter_id']}").json()["changes"]["end_state"]["cast"]
    seen.clear()
    wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)
    first = next(c for i, c in seen if i == 1)
    assert "上一章结束时的状态账本" in first and "还没有账本" not in first


def test_humanize_patches_craft_targets_on_sample() -> None:
    from app.services.writing import patch_rewrite

    lint = lint_chapter(SAMPLE, TH, chapter_number=1)
    new, applied = patch_rewrite(SAMPLE, None, lint, {"protagonist": "叶承"})
    assert applied >= 3
    assert "一柄生了锈的万斤铁砣" not in new and "一块生了锈的万斤铁砣" in new
    assert "空气像灌了铅" not in new
    after = lint_chapter(new, TH, chapter_number=1)
    before_n = next(d["count"] for d in lint.intensifiers if d["word"] == "死死")
    after_n = next((d["count"] for d in after.intensifiers if d["word"] == "死死"), 0)
    assert after_n < before_n and len(after.fix_targets) < len(lint.fix_targets)
