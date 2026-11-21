"""v0.17 读者驱动写作：主角识别、前文可见、整章一次写与正文清洗、读者账本、文风基准、多候选成对比较、习惯动作限次。全部 mock。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import wait_job


def _book(client: TestClient, title: str, **kw: Any) -> int:
    b = client.post("/api/books", json={"title": title, "genre": "都市高武", "gender": "male", "premise": "主角靠一本旧账翻身。", **kw}).json()
    bid = b["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    return bid


# ------------------------------------------------------------------ 1. 主角识别

def test_protagonist_prefers_fanfic_oc(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import Book, Card, OutlineNode
    from app.services import common
    from app.services.context import build_context_pack

    b = client.post("/api/books", json={"title": "龙族之测试", "genre": "同人", "gender": "male", "premise": "穿越者改写雨夜。"}).json()
    bid = b["id"]
    with session_scope() as s:
        canon = Card(book_id=bid, type="character", name="路明非", summary="原著主角", data={"role": "protagonist", "habits": ["挠头"]})
        oc = Card(book_id=bid, type="character", name="江叙", summary="穿越者", data={"role": "protagonist", "origin": "oc"})
        s.add(canon)
        s.add(oc)
        s.commit()
        s.refresh(oc)
        oc_id = oc.id
        # 原著主角卡在前：旧版会认错
        assert common.protagonist(s, bid).name == "江叙"
        book = s.get(Book, bid)
        book.fanfic = {"source_title": "龙族", "protagonist": {"source": "oc", "name": "江叙", "card_id": oc_id}}
        s.add(book)
        s.commit()
        assert common.protagonist(s, bid).id == oc_id
        # card_id 指向的卡被删了，按名字找
        book.fanfic = {"source_title": "龙族", "protagonist": {"source": "oc", "name": "江叙", "card_id": 999999}}
        s.add(book)
        s.commit()
        assert common.protagonist(s, bid).name == "江叙"
        node = OutlineNode(book_id=bid, level="chapter", order=3, title="t", beats={"characters": ["路明非", "江叙"]})
        pack = build_context_pack(s, book, node)
    assert pack.protagonist == "江叙"
    assert "路明非：原著主角（原著主角，本书里是重要配角" in pack.suffix
    assert "视点主角：江叙" in pack.cast_notes and "路明非是原著主角" in pack.cast_notes
    assert "偶尔体现，全章同一个不超过 2 次" in pack.suffix


def test_protagonist_check_only_chapter_one() -> None:
    from app.services.review import deterministic_issues

    text = "雨下得很大。" * 80 + "江叙推门进来。"
    one = deterministic_issues(text, "江叙", [], 1)
    assert any("没有在前 300 字内出场" in i["comment"] and i["severity"] == "mid" for i in one)
    assert not any("前 300 字" in i["comment"] for i in deterministic_issues(text, "江叙", [], 2))


# ------------------------------------------------------------------ 3. 正文清洗

def test_clean_prose_strips_wrappers() -> None:
    from app.services.writing import clean_prose

    raw = ("**正文**\n第3章 雨夜\n```\n江叙推开门。\n\n---\n\n“你来了。”路明非抬头。\n```\n"
           "---STATE---\n{\"cast\":[]}\n---CHANGES---\n{\"new_entities\":[]}")
    out = clean_prose(raw)
    assert out == "江叙推开门。\n\n“你来了。”路明非抬头。"
    j = clean_prose('```json\n{"content": "江叙推开门。\\n路明非抬头。"}\n```')
    assert j == "江叙推开门。\n\n路明非抬头。"
    tail = clean_prose("江叙推开门。\n{\n  \"cast\": [\n    {\"name\": \"江叙\"}\n  ]\n}\n场景二：雨里\n他笑了。")
    assert tail == "江叙推开门。\n\n他笑了。"
    assert clean_prose("**他**看着门口，“**走**。”") == "他看着门口，“走。”"


def test_writer_params_and_prompt_order() -> None:
    from app.services.context import ContextPack
    from app.services.writing import build_chapter_user, writer_max_tokens
    from app.skills.loader import system_prompt

    assert writer_max_tokens(2000) == 5500 and writer_max_tokens(100) == 4000 and writer_max_tokens(20000) == 16000
    pack = ContextPack(prefix="sys", suffix="【本章写作任务】\n江叙本章想要：拿回账本", prev_tail="他推开门，雨灌进来。", cast_notes="视点主角：江叙")
    u = build_chapter_user(pack, 2, "雨夜", [{"goal": "拿回账本", "conflict": "管事拦着", "outcome": "yes-but", "characters": ["江叙"]}], 2000)
    assert u.index("【本章写作任务】") < u.index("想要：拿回账本") < u.index("视点主角") < u.index("他推开门") < u.index("直接输出正文")
    sp = system_prompt("writing_chapter")
    assert sp.startswith("你是一位熟悉番茄小说读者口味的中文网文作者。") and "JSON" not in sp
    assert len(system_prompt("writing_chapter", platform="fanqie")) < 1500


def test_normalize_scenes_strips_dialogue() -> None:
    from app.services.writing import normalize_scenes

    raw = {"scenes": [{"goal": "逼管事开口，“账本在哪？”他问", "conflict": "管事说“你算什么东西”", "sensory": "雨声", "exit_hook": "门外有人"},
                      {"goal": "b"}, {"goal": "c"}]}
    sc = normalize_scenes(raw, {"hook_end": "门外有人敲门"}, None, 5)
    assert "账本在哪" not in sc[0]["goal"] and "你算什么东西" not in sc[0]["conflict"]
    assert "sensory" not in sc[0] and "exit_hook" not in sc[0] and sc[-1]["main_hook"] == "门外有人敲门"


# ------------------------------------------------------------------ 6. 读者账本

def test_reader_ledger_cheat_gap_and_mechanism_dupes() -> None:
    from app.services.outline import CHEAT_IDLE, ensure_opening_beats, mechanism_dupes, normalize_beats, pacing_audit

    class Cheat:
        name, summary, data = "遗憾修正系统", "接住悲剧就发奖励", {"input": "改写原著悲剧场面"}

    recent = [{"number": 2, "cheat_beat": "本章不用"}, {"number": 3, "cheat_beat": ""}]
    b = ensure_opening_beats({"goal": "救下楚叔叔"}, 4, Cheat(), "", recent)
    assert "遗憾修正系统" in b["cheat_beat"] and "可见地兑现" in b["cheat_beat"] and b["want"].endswith("救下楚叔叔")
    assert ensure_opening_beats({"goal": "x"}, 4, Cheat(), "", [{"number": 3, "cheat_beat": "系统发奖励"}])["cheat_beat"] == CHEAT_IDLE
    nb = normalize_beats({"want": "抢下名额", "turn": "管事失算", "result": "名额到手", "payoff_mechanism": "管事当众认错"}, 6, 2000)
    assert nb["want"] == "抢下名额" and nb["payoff_mechanism"] == "管事当众认错"
    rows = [{"number": 1, "payoff_mechanism": "主角当众说出反派的三件秘密，反派丢脸"},
            {"number": 2, "payoff_mechanism": "主角当众说出管事的三件秘密，管事丢脸"},
            {"number": 3, "payoff_mechanism": "主角一拳打穿擂台，全场看见"}]
    d = mechanism_dupes(rows)
    assert [(x[0], x[1]) for x in d] == [(2, 1)]
    b = ensure_opening_beats({"payoff_mechanism": "主角当众说出长老的三件秘密，长老丢脸"}, 4, None, "", rows)
    assert any("和第" in x and "一样的爽点机制" in x for x in b["must_avoid"])
    audit = pacing_audit([*rows, {"number": 4, "want": "躲过追杀"}, {"number": 5, "want": "撑过今晚"}, {"number": 6, "want": "保住摊子"},
                          {"number": 7, "cheat_beat": "本章不用"}, {"number": 8, "cheat_beat": "本章不用"}, {"number": 9, "cheat_beat": "不用"}])
    text = "\n".join(audit)
    assert "第2章的爽点机制和第1章重复" in text and "躲、守、撑" in text and "金手指都没出手" in text


def test_reader_persona_by_book() -> None:
    from types import SimpleNamespace

    from app.services.review import reader_persona

    ff = reader_persona(SimpleNamespace(gender="male", genre="同人", fanfic={"source_title": "龙族"}))
    assert "《龙族》" in ff and "OOC" in ff and "都市高武" not in ff
    assert "女频仙侠" in reader_persona(SimpleNamespace(gender="female", genre="仙侠", fanfic=None))


def test_issues_instruction_includes_reader() -> None:
    from app.services.wanben import _issues_instruction

    ins = _issues_instruction({"issues": [{"severity": "high", "dimension": "hook", "quote": "雨下得很大", "comment": "开头太慢"}],
                               "reader": {"score": 4, "verdict": "主角一直挨打", "drop": "雨下得很大。", "waiting": "等他还手", "next": ""}}, "")
    assert "开头太慢" in ins and "读者分 4/10" in ins and "主角一直挨打" in ins and "想弃" in ins and "等他还手" in ins
    assert "章末停在事件进行中" in ins


# ------------------------------------------------------------------ 4. 习惯动作限次

def test_habit_report_and_catchphrase_limit() -> None:
    from app.config import get_settings
    from app.lint.humanlint import habit_report, lint_chapter

    text = "他摩挲着腕上那条旧疤，没说话。\n\n管事又开口了。他摩挲着腕上旧疤。\n\n门开了，他摩挲着腕上那条旧疤，抬头。"
    rep = habit_report(text, {"江叙": ["摩挲腕上那条旧疤"]})
    assert rep and rep[0]["count"] == 3 and rep[0]["over"]
    lint = lint_chapter(text + "\n\n“行。”他说。“行。”", get_settings().lint, habits={"江叙": ["摩挲腕上那条旧疤"]},
                        catchphrases={"江叙": ["行。"]}, platform="fanqie")
    assert any("习惯动作超频" in w for w in lint.warnings) and any(t["kind"] == "习惯动作重复" for t in lint.fix_targets)
    assert any(d["over"] for d in lint.catchphrases)  # 口头禅全章最多 1 次
    assert lint.to_dict()["habits"][0]["count"] == 3


# ------------------------------------------------------------------ 8. 多候选成对比较

def test_pairwise_compare_both_orders() -> None:
    from app.llm.gateway import get_gateway
    from app.services.review import pairwise_compare

    r = pairwise_compare(get_gateway(), "长" * 50, "短" * 10, 1, "{}")
    assert r["winner"] == 0 and len(r["votes"]) == 2 and r["votes"][1]["order"] == "BA"

    class Biased:  # 永远选 A：两次结论相反 → 不算赢
        def chat_json(self, *a: Any, **k: Any) -> Any:
            return {"winner": "A", "reason": "x"}

    assert pairwise_compare(Biased(), "a", "b", 1, "{}")["winner"] is None  # type: ignore[arg-type]


# ------------------------------------------------------------------ 2. 前文可见 + 5. 文风基准

@pytest.mark.skip(reason="v0.20 一次写成不再在 write_next 中自动抽状态账本")
def test_refine_scope_chapters_visible_to_next(client: TestClient, monkeypatch: Any) -> None:
    """完本模式精修范围（写好不提交）里，写第 2 章时仍能看到第 1 章的结尾原文、摘要和状态变化。"""
    import app.services.writing as writing

    users: list[str] = []
    real = writing.get_gateway()

    class Spy:
        def __getattr__(self, k: str) -> Any:
            return getattr(real, k)

        def chat(self, task: str, messages: list[dict[str, str]], **kw: Any) -> str:
            if task == "writing_chapter":
                users.append(messages[-1]["content"])
            return real.chat(task, messages, **kw)

    monkeypatch.setattr(writing, "get_gateway", lambda: Spy())
    bid = _book(client, "精修可见")
    r = client.put(f"/api/books/{bid}/wanben", json={"mode": "wanben", "target_words": 100_000, "chapter_words": 2000,
                                                            "batch_size": 2, "refine_scope": "first_n", "golden_chapters": 3,
                                                            "pause_on_unapproved_refine": False})
    assert r.status_code == 200, r.text
    j = wait_job(client, client.post(f"/api/books/{bid}/wanben/batch", json={}).json(), timeout=240)
    assert j["status"] == "succeeded", j
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert [c["number"] for c in chs][:2] == [1, 2] and all(c["status"] != "committed" for c in chs[:2])
    ch1 = client.get(f"/api/chapters/{chs[0]['id']}").json()
    assert ch1["summary"] if "summary" in ch1 else True
    second = users[-1]
    last_para = [p for p in ch1["content"].split("\n") if p.strip()][-1]
    assert "【上一章结尾原文】" in second and last_para[-20:] in second
    assert "【最近章节摘要】" in second and "第1章" in second
    assert "待审" in second  # 第 1 章登记的状态变化叠在底账上
    from app.db import session_scope
    from app.models.tables import Chapter

    with session_scope() as s:
        c1 = s.get(Chapter, chs[0]["id"])
        assert c1.summary and c1.changes.get("summary_hash")


def test_style_baseline_api(client: TestClient) -> None:
    b = client.post("/api/books", json={"title": "文风基准", "genre": "玄幻", "gender": "male"}).json()
    bid = b["id"]
    st = client.get(f"/api/books/{bid}/style").json()
    assert st["baseline"] == ""
    st = client.put(f"/api/books/{bid}/style", json={"sample_text": "", "baseline": "  他推开门。  ", "pov": "third"}).json()
    assert st["baseline"] == "他推开门。"
    # 不传 baseline 保持原样
    st = client.put(f"/api/books/{bid}/style", json={"sample_text": "", "tone": "热血燃", "pov": "third"}).json()
    assert st["baseline"] == "他推开门。" and st["tone"] == "热血燃"
    assert client.put(f"/api/books/{bid}/style", json={"baseline": "字" * 2100}).status_code == 400


def test_pick_baseline_range() -> None:
    from app.lint.humanlint import count_words
    from app.services.writing import pick_baseline

    paras = [("“走。”他说着把门推开。" if i % 2 else "雨打在铁皮上，院子里站满了人，管事坐在台阶上数钱。") * 3 for i in range(60)]
    text = pick_baseline("\n".join(paras))
    assert 600 <= count_words(text) <= 1000
