"""v0.7 榜单仿写：拆解（只学结构）、深度拆解字数上限、换皮选题 3 个且带自检、ngram 重合检测、路由与 Agent 提案工具。

v0.7.1：拆解 / 深度拆解 / 换皮选题改为任务接口（立即返回 Job，结果在 Job.result），这里统一用 _run 等任务完成。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.services import imitate
from conftest import wait_job

TD_KEYS = ("payoff_formula", "golden_finger", "protagonist_template", "opening_hook", "target_readers", "transferable", "must_replace")


def _run(client: TestClient, r: Any) -> dict[str, Any]:
    """POST 仿写接口 → 立即拿到 Job → 等它完成，返回 Job.result。"""
    assert r.status_code == 200, r.text
    job = r.json()
    assert {"id", "kind", "status", "ref"} <= set(job) and job["kind"].startswith("radar_") and job["ref"].startswith("rank_item:"), job
    return wait_job(client, job)["result"]


def _item(client: TestClient, idx: int = 0) -> dict[str, Any]:
    wait_job(client, client.post("/api/radar/refresh").json())
    items = client.get("/api/radar/latest").json()["items"]
    assert items and all(isinstance(i["id"], int) for i in items)
    return items[idx]


# ------------------------------------------------------------------ ngram

def test_ngram_overlap_counts_segments() -> None:
    src = "他一拳砸在桌上，所有人都愣住了。那个被叫做废物的少年，缓缓抬起了头。"
    assert imitate.ngram_overlap("完全不相干的另一句话，写的是别的东西。", src) == 0
    # 一段长重合只算一处（相邻命中合并），标点和空白不影响
    assert imitate.ngram_overlap("开头不同。他一拳砸在桌上， 所有人都愣住了！结尾也不同", src) == 1
    two = "他一拳砸在桌上所有人中间插一句话完全无关被叫做废物的少年缓缓抬起"
    assert imitate.ngram_overlap(two, src) == 2
    segs = imitate.overlap_segments(two, src)
    assert segs[0].startswith("他一拳砸在桌上") and "被叫做废物的少年" in segs[1]
    assert imitate.ngram_overlap("短", src) == 0 and imitate.ngram_overlap(src, src, n=4) == 1
    assert imitate.ngram_overlap("abcdefg", "abcdefg") == 0  # 不足 8 字不算


# ------------------------------------------------------------------ 拆解

def test_teardown_fields_and_cache(client: TestClient) -> None:
    it = _item(client)
    assert client.get(f"/api/radar/items/{it['id']}/teardown").status_code in (200, 404)
    d = _run(client, client.post(f"/api/radar/items/{it['id']}/teardown"))
    assert d["rank_item_id"] == it["id"] and d["title"] == it["title"] and d["book_id_ext"] == it["book_id_ext"]
    td = d["teardown"]
    for k in TD_KEYS:
        assert td[k], k
    assert set(td["golden_finger"]) == {"type", "delivery"}
    assert isinstance(td["transferable"], list) and isinstance(td["must_replace"], list) and isinstance(td["warnings"], list)
    again = _run(client, client.post(f"/api/radar/items/{it['id']}/teardown"))
    assert again["cached"] and again["id"] == d["id"] and again["teardown"] == td
    got = client.get(f"/api/radar/items/{it['id']}/teardown").json()
    assert got["id"] == d["id"] and got["teardown"] == td and got["deep"] is None
    fresh = _run(client, client.post(f"/api/radar/items/{it['id']}/teardown?refresh=true"))
    assert not fresh["cached"] and fresh["id"] == d["id"]
    assert client.post("/api/radar/items/999999/teardown").status_code == 404
    assert client.get("/api/radar/items/999999/teardown").status_code == 404


def test_teardown_reused_across_snapshots(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import RadarSnapshot, RankItem

    it = _item(client, 1)
    first = _run(client, client.post(f"/api/radar/items/{it['id']}/teardown"))
    with session_scope() as s:  # 同一本书出现在新快照里
        snap = RadarSnapshot(source="mock", items_count=1, version="test-v07")
        s.add(snap)
        s.flush()
        row = RankItem(snapshot_id=snap.id or 0, **{k: it[k] for k in ("book_id_ext", "title", "author", "category", "rank",
                                                                       "read_count", "word_count", "abstract", "tags", "gender")})
        s.add(row)
        s.commit()
        new_id = row.id
    d = _run(client, client.post(f"/api/radar/items/{new_id}/teardown"))
    assert d["cached"] and d["rank_item_id"] == new_id and d["teardown"] == first["teardown"]


# ------------------------------------------------------------------ 深度拆解

SAMPLE = """第一章 雨夜
雨下得很大。“你也配站在这里？”管事冷笑一声，把账本摔在他脸上。
陈默没说话，只是弯腰捡起了账本。
就在这时，脑海里响起一声：“叮，系统已绑定。”
第二章 翻盘
第二天，他把账本上的错处一条条念了出来。
“这不可能。”管事的脸色变了。
所有人都看着他，没人再敢笑。
"""


def test_text_stats() -> None:
    st = imitate.text_stats(SAMPLE)
    assert [c["title"] for c in st["chapters"]] == ["第一章 雨夜", "第二章 翻盘"]
    assert all(c["words"] > 0 and 0 < c["dialogue_ratio"] < 1 for c in st["chapters"])
    assert st["total_words"] == sum(c["words"] for c in st["chapters"])
    assert st["first_conflict"]["keyword"] == "冷笑" and st["first_conflict"]["chapter"] == 1
    assert st["first_cheat"]["keyword"] in ("叮", "系统") and st["first_cheat"]["chapter"] == 1
    assert st["first_conflict"]["at_char"] < st["first_cheat"]["at_char"]
    one = imitate.text_stats("没有章节标题的一段话。“对白”。")
    assert len(one["chapters"]) == 1 and one["chapters"][0]["title"] == "全文" and one["first_cheat"] is None


def test_deep_limit_and_fields(client: TestClient) -> None:
    it = _item(client, 2)
    too_long = "字" * (imitate.DEEP_MAX_CHARS + 1)
    r = client.post(f"/api/radar/items/{it['id']}/deep", json={"text": too_long})
    assert r.status_code == 400 and "20000" in r.json()["detail"]
    assert client.post(f"/api/radar/items/{it['id']}/deep", json={"text": "  "}).status_code == 400
    _run(client, client.post(f"/api/radar/items/{it['id']}/deep", json={"text": "字" * imitate.DEEP_MAX_CHARS}))  # 恰好 20000 字可以
    d = _run(client, client.post(f"/api/radar/items/{it['id']}/deep", json={"text": SAMPLE}))
    deep = d["deep"]
    assert len(deep["chapters"]) == 2
    for c in deep["chapters"]:
        assert c["words"] > 0 and "dialogue_ratio" in c and c["conflict"] and c["payoff"] and c["hook"]
    assert deep["first_conflict"]["keyword"] == "冷笑" and deep["first_cheat"]
    assert deep["overlap"] == 0 and deep["warnings"] == [] and deep["rhythm"]
    assert "管事" not in str(deep) and "陈默" not in str(deep)  # 原文不落库、不出现原文人名
    assert client.get(f"/api/radar/items/{it['id']}/teardown").json()["deep"]["total_words"] == deep["total_words"]


def test_deep_overlap_warning(client: TestClient, monkeypatch) -> None:
    from app.llm import mock

    it = _item(client, 3)
    copied = "管事冷笑一声把账本摔在他脸上"
    monkeypatch.setitem(mock.HANDLERS, "teardown_deep", lambda meta: mock._j(
        {"chapters": [{"index": 1, "conflict": copied, "payoff": "反击", "hook": "钩子"}], "rhythm": "快", "learnable": []}))
    deep = _run(client, client.post(f"/api/radar/items/{it['id']}/deep", json={"text": SAMPLE}))["deep"]
    assert deep["overlap"] >= 1 and deep["warnings"] and "原文" in deep["warnings"][0]


# ------------------------------------------------------------------ 换皮选题

def test_reskin_three_ideas_with_self_check(client: TestClient) -> None:
    it = _item(client, 4)
    d = _run(client, client.post(f"/api/radar/items/{it['id']}/reskin"))
    assert d["rank_item_id"] == it["id"] and d["ref_title"] == it["title"] and len(d["idea_ids"]) == 3 and len(d["ideas"]) == 3
    for idea in d["ideas"]:
        assert idea["title"] and idea["logline"] and idea["selling_points"] and idea["arc"] and idea["scores"]["overall"] > 0
        src = idea["source"]
        assert src["kind"] == "reskin" and src["rank_item_id"] == it["id"] and src["ref_title"] == it["title"]
        assert src["kept"] and src["changed"] and src["self_check"]
        assert all({"aspect", "original", "ours", "similar"} <= set(c) for c in src["self_check"])
        assert set(src["overlap"]) == {"count", "title", "segments"} and isinstance(src["warnings"], list)
        assert idea["trope_hits"] == []
    assert len({i["title"] for i in d["ideas"]}) == 3
    # 拆解已缓存
    assert client.get(f"/api/radar/items/{it['id']}/teardown").json()["teardown"]["payoff_formula"]
    # 选题列表里能看到，且能走现有建书流程
    listed = {i["id"]: i for i in client.get("/api/ideas").json()}
    assert all(i in listed and listed[i]["source"]["kind"] == "reskin" for i in d["idea_ids"])
    book = client.post(f"/api/ideas/{d['idea_ids'][0]}/adopt").json()
    assert book["title"] == d["ideas"][0]["title"]


def test_reskin_self_check_flags_copies(client: TestClient, monkeypatch) -> None:
    from app.llm import mock

    it = _item(client, 5)
    assert len(it["abstract"]) >= 10
    orig = mock.HANDLERS["reskin"]

    def copying(meta: dict[str, Any]) -> str:  # v0.7.1：逐个生成，按 meta["index"] 区分第几个
        import json

        data = json.loads(orig(meta))
        x, k = data["ideas"][0], int(meta.get("index") or 0)
        if k == 0:
            x["title"] = it["title"][:6] + "新篇"
            x["logline"] = it["abstract"][:30]
        elif k == 1:
            x["logline"] += "父母失踪多年"
        else:
            x["self_check"][0]["similar"] = True
        return mock._j(data)

    monkeypatch.setitem(mock.HANDLERS, "reskin", copying)
    d = _run(client, client.post(f"/api/radar/items/{it['id']}/reskin"))
    w0 = " ".join(d["ideas"][0]["source"]["warnings"])
    assert "连续 8 字相同" in w0 and "书名" in w0 and d["ideas"][0]["source"]["overlap"]["count"] >= 1
    assert any("禁用套路" in w for w in d["ideas"][1]["source"]["warnings"]) and d["ideas"][1]["trope_hits"]
    assert any("仍偏像" in w for w in d["ideas"][2]["source"]["warnings"])
    assert d["warnings"] and all(w.startswith("《") for w in d["warnings"])


def test_reskin_404(client: TestClient) -> None:
    assert client.post("/api/radar/items/999999/reskin").status_code == 404
    assert client.post("/api/radar/items/999999/deep", json={"text": SAMPLE}).status_code == 404


# ------------------------------------------------------------------ v0.7.1 任务化

def test_imitate_jobs_progress_and_lookup(client: TestClient, monkeypatch) -> None:
    """接口立即返回 Job；进度文字逐个汇报；按条目能查回任务；同类任务进行中重复点击返回同一个任务。"""
    import threading

    from app.llm import mock

    it = _item(client, 7)
    gate = threading.Event()
    orig = mock.HANDLERS["reskin"]
    seen: list[str] = []

    def slow(meta: dict[str, Any]) -> str:
        gate.wait(10)
        return orig(meta)

    monkeypatch.setitem(mock.HANDLERS, "reskin", slow)
    job = client.post(f"/api/radar/items/{it['id']}/reskin").json()
    assert job["status"] in ("queued", "running") and job["kind"] == "radar_reskin" and job["ref"] == f"rank_item:{it['id']}"
    again = client.post(f"/api/radar/items/{it['id']}/reskin").json()
    assert again["id"] == job["id"]  # 去重
    import time

    for _ in range(200):  # 等到卡在第 1 个选题
        cur = client.get(f"/api/jobs/{job['id']}").json()
        if "生成选题" in cur["message"]:
            seen.append(cur["message"])
            break
        time.sleep(0.02)
    assert seen and seen[0] == "生成选题 1/3"
    listed = client.get(f"/api/radar/items/{it['id']}/jobs").json()
    assert listed[0]["id"] == job["id"] and listed[0]["status"] == "running"
    assert [j["id"] for j in client.get(f"/api/jobs?ref=rank_item:{it['id']}&kind=radar_reskin").json()][0] == job["id"]
    gate.set()
    done = wait_job(client, job)
    assert len(done["result"]["ideas"]) == 3 and done["progress"] == 100


def test_imitate_job_failure_and_partial(client: TestClient, monkeypatch) -> None:
    from app.llm import mock

    it = _item(client, 8)

    def boom(meta: dict[str, Any]) -> str:
        raise ValueError("模型炸了")

    monkeypatch.setitem(mock.HANDLERS, "teardown", boom)
    job = client.post(f"/api/radar/items/{it['id']}/teardown").json()
    import time

    for _ in range(300):
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.02)
    assert j["status"] == "failed" and j["error"]  # 失败信息在 Job.error 里
    monkeypatch.undo()

    orig = mock.HANDLERS["reskin"]

    def second_fails(meta: dict[str, Any]) -> str:
        if int(meta.get("index") or 0) == 1:
            raise ValueError("第二个超时")
        return orig(meta)

    monkeypatch.setitem(mock.HANDLERS, "reskin", second_fails)
    d = _run(client, client.post(f"/api/radar/items/{it['id']}/reskin"))
    assert len(d["idea_ids"]) == 2 and any("第 2 个选题生成失败" in w for w in d["warnings"])
    assert any("只给了 2 个" in w for w in d["warnings"])


# ------------------------------------------------------------------ Agent 提案工具

def test_agent_tool_imitate_proposal(client: TestClient) -> None:
    from app.services import agent_tools

    it = _item(client, 6)
    bid = client.post("/api/books", json={"title": "测试书", "genre": "都市高武", "gender": "male"}).json()["id"]
    sid = client.post(f"/api/books/{bid}/agent/sessions").json()["id"]
    tc = agent_tools.ToolCtx(book_id=bid, session_id=sid)
    assert "imitate_rank_book" in agent_tools.BY_NAME
    assert not agent_tools.dispatch(tc, "imitate_rank_book", {"title": "根本不存在的书名xyz"}).ok
    before = len(client.get("/api/ideas").json())
    r = agent_tools.dispatch(tc, "imitate_rank_book", {"title": it["title"]})
    assert r.ok and r.proposal_ids and len(r.data["ideas"]) == 3 and r.data["teardown"]["payoff_formula"]
    assert len(client.get("/api/ideas").json()) == before  # 提案未采纳，不落库
    pid = r.proposal_ids[0]
    applied = client.post(f"/api/agent/proposals/{pid}/apply").json()
    ids = applied["proposal"]["result"]["idea_ids"]
    assert len(ids) == 3 and len(client.get("/api/ideas").json()) == before + 3
    assert client.post(f"/api/agent/proposals/{pid}/revert").json()["status"] == "reverted"
    assert len(client.get("/api/ideas").json()) == before


def test_commit_chapter_is_job(client: TestClient) -> None:
    """v0.7.1：提交章节（要调一次模型生成摘要）也走任务；不存在的章节仍同步 404。"""
    assert client.post("/api/chapters/999999/commit").status_code == 404
