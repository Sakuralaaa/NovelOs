"""v0.11 完本模式：设置、字数倒推规划、分批连写（精修范围/暂停/续跑）、抽检报告、章节迭代、进度、整书 TXT 导出。

全部走 mock LLM（必要时 monkeypatch 网关），不做真实网络与模型调用。
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import wait_job


def _wait_any(client: TestClient, job_id: int, timeout: float = 240) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed", "interrupted"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"任务超时：{job_id}")


def _book(client: TestClient, title: str) -> int:
    b = client.post("/api/books", json={"title": title, "genre": "都市高武", "gender": "male",
                                         "premise": "主角靠一本旧账翻身。"}).json()
    bid = b["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    return bid


def _wanben(client: TestClient, bid: int, **kw: Any) -> dict[str, Any]:
    r = client.put(f"/api/books/{bid}/wanben", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def _batch(client: TestClient, bid: int, force: bool = False) -> dict[str, Any]:
    r = client.post(f"/api/books/{bid}/wanben/batch", json={"force": force})
    assert r.status_code == 200, r.text
    j = _wait_any(client, r.json()["id"])
    assert j["status"] == "succeeded", j
    return j["result"]


# ================================================================== 纯函数

def test_norm_ranges_and_refine_numbers() -> None:
    from app.services import wanben

    assert wanben.norm_ranges([[5, 3], 7, "10-12", "8", [1, 1], "x", 0]) == [[1, 1], [3, 5], [7, 8], [10, 12]]
    assert wanben.total_chapters_for(150_000, 2000) == 75
    assert wanben.total_chapters_for(200_001, 2000) == 101
    st = {**wanben.DEFAULTS}
    assert wanben.refine_numbers(st, 100) == list(range(1, 11))
    assert wanben.refine_numbers({**st, "refine_scope": "all"}, 5, 7) == list(range(1, 8))
    assert wanben.refine_numbers({**st, "refine_scope": "custom", "refine_ranges": [[3, 4], [9, 9]]}, 50) == [3, 4, 9]
    assert wanben.refine_numbers({**st, "refine_scope": "none"}, 50) == []
    assert wanben._alloc_ranges(20, 2, [10, 0]) == [(1, 10), (11, 20)]
    assert wanben._alloc_ranges(30, 3, [12, 0, 0]) == [(1, 12), (13, 20), (21, 30)]


def test_chapter_check_heuristics() -> None:
    from app.models.tables import Chapter
    from app.services import wanben

    content = "“滚出去！”王虎一脚踹开门，账单拍在桌上。\n\n林默没动。\n\n他抬手，一拳把王虎砸翻在地，全场鸦雀无声！\n\n门外，有人低声说：“他还欠着三条命。”"
    ch = Chapter(id=1, book_id=1, number=1, title="开局", content=content, words=60, status="committed",
                 review={"scores": {"overall": 80}, "passed": True, "reader": {"score": 5},
                         "issues": [{"severity": "high", "dimension": "continuity", "quote": "林默没动", "comment": "前文已经站起来了"}]},
                 lint={"numeric_conflicts": [{"quote": "三条命", "comment": "数字与前文不一致"}]})
    r = wanben.chapter_check(ch, {"payoff": "当众打脸", "hook_end": "欠命"}, 2000, True)
    assert r["opening"]["conflict"] is True and r["opening"]["head"].startswith("“滚出去")
    assert r["climax"]["found"] and r["climax"]["planned"] == "当众打脸"
    assert r["reader_below_threshold"] is True and r["in_refine"] is True
    kinds = {c["kind"] for c in r["consistency"]}
    assert "number" in kinds and "continuity" in kinds
    assert any("读者分" in f for f in r["failed"]) and any("字数" in f for f in r["failed"])
    assert r["passed"] is False


# ================================================================== 设置 / 迁移

def test_settings_defaults_and_update(client: TestClient) -> None:
    b = client.post("/api/books", json={"title": "完本设置书", "genre": "都市", "gender": "male"}).json()
    bid = b["id"]
    w = client.get(f"/api/books/{bid}/wanben").json()
    assert w["mode"] == "serial" and w["target_words"] == 200_000 and w["chapter_words"] == 2000
    assert w["batch_size"] == 10 and w["golden_chapters"] == 10 and w["auto_continue"] is False
    assert w["refine_scope"] == "first_n" and w["refine_numbers"] == list(range(1, 11))
    assert w["pause_on_unapproved_refine"] is True and w["presets"] == [200000, 300000, 500000, 1200000, 2000000]
    assert w["total_chapters"] == 100 and w["plan"]["planned"] is False
    # 连载书不能用完本的写作接口；书本身的字段不被改动
    assert client.post(f"/api/books/{bid}/wanben/batch").status_code == 409
    assert client.post(f"/api/books/{bid}/wanben/plan").status_code == 409
    assert client.get(f"/api/books/{bid}").json()["chapter_words"] == 2200
    w = _wanben(client, bid, mode="wanben", target_words=150_000, chapter_words=2500, batch_size=5)
    assert w["mode"] == "wanben" and w["total_chapters"] == 60
    bk = client.get(f"/api/books/{bid}").json()
    assert bk["target_words"] == 150_000 and bk["chapter_words"] == 2500  # 完本模式同步书的目标
    assert client.put(f"/api/books/{bid}/wanben", json={"batch_size": 0}).status_code == 422
    assert client.put(f"/api/books/{bid}/wanben", json={"mode": "x"}).status_code == 422
    # 精修范围：任意加章 / 范围，移出，全书
    r = client.post(f"/api/books/{bid}/wanben/refine", json={"action": "add", "ranges": [[30, 32], 50, "55-56"]}).json()
    assert r["refine_scope"] == "custom" and r["numbers"] == [*range(1, 11), 30, 31, 32, 50, 55, 56]
    r = client.post(f"/api/books/{bid}/wanben/refine", json={"action": "remove", "ranges": ["1-8", 31]}).json()
    assert r["numbers"] == [9, 10, 30, 32, 50, 55, 56] and r["unwritten"] == 7 and r["all_approved"] is False
    assert client.get(f"/api/books/{bid}/wanben/golden").json()["numbers"] == r["numbers"]  # 旧名兼容
    w = _wanben(client, bid, refine_scope="all")
    assert w["refine_count"] == 60
    w = _wanben(client, bid, mode="serial")
    assert w["mode"] == "serial" and client.get(f"/api/books/{bid}").json()["chapter_words"] == 2500


def test_migration_adds_mode_column(tmp_path: Any) -> None:
    """旧库没有 mode / wanben 列：轻量迁移补列，旧书为 serial、wanben 为 NULL。"""
    import sqlite3

    from sqlmodel import create_engine

    from app.db import _add_missing_columns

    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.execute('CREATE TABLE book (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL)')
    con.execute("INSERT INTO book (id, title) VALUES (1, '旧书')")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{p}")
    _add_missing_columns(eng)
    con = sqlite3.connect(p)
    row = con.execute("SELECT mode, wanben FROM book WHERE id = 1").fetchone()
    con.close()
    assert row == ("serial", None)


# ================================================================== 规划 + 分批连写 + 迭代 + 导出（一本书走完）

def test_wanben_full_flow(client: TestClient) -> None:
    bid = _book(client, "完本流程书")
    _wanben(client, bid, mode="wanben", target_words=40_000, chapter_words=2000, batch_size=3)

    # 1) 倒推规划：20 章；原大纲第 1 卷已有 10 章细纲 → 第 1 卷 1–10，第 2 卷 11–20，多出的空卷删掉
    j = wait_job(client, client.post(f"/api/books/{bid}/wanben/plan").json())
    res = j["result"]
    assert res["total_chapters"] == {"before": None, "after": 20}
    vols = res["volumes"]
    assert [(v["start"], v["end"]) for v in vols] == [(1, 10), (11, 20)]
    for v in vols:
        assert v["crisis"] and v["closure"] and v["start"] <= v["climax_chapter"] <= v["end"]
    assert vols[-1]["finale"]["resolution"] and vols[-1]["finale"]["last_chapter"] == 20
    assert "finale" not in vols[0]
    actions = {d["order"]: d["action"] for d in res["diff"]}
    assert actions[1] == "updated" and actions[2] == "updated" and actions.get(3) == "removed"
    plan = client.get(f"/api/books/{bid}/wanben/plan").json()
    assert plan["planned"] and plan["total_chapters"] == 20 and plan["ending"]
    nodes = client.get(f"/api/books/{bid}/outline").json()
    flat = nodes if isinstance(nodes, list) else nodes.get("nodes", [])
    ch10 = next((n for n in flat if n.get("level") == "chapter" and n.get("order") == 10), None)
    if ch10 is not None and "beats" in ch10:
        assert "wanben_role" in (ch10["beats"] or {})

    # 2) 默认精修范围前 10 章 + 待审批时暂停：写完第 1 章就停，不提交
    r = _batch(client, bid)
    assert r["stopped"] and r["reason"] == "refine_pending"
    b1 = r["batches"][0]
    assert b1["status"] == "stopped" and b1["stop_reason"] == "refine_pending" and len(b1["chapter_ids"]) == 1
    ch1 = client.get(f"/api/chapters/{b1['chapter_ids'][0]}").json()
    assert ch1["number"] == 1 and ch1["status"] == "reviewing" and ch1["content"]
    g = client.get(f"/api/books/{bid}/wanben/refine").json()
    assert g["pending"] == [1] and g["approved"] == 0 and g["written"] == 1 and g["reader_threshold"] == 6
    assert g["chapters"][0]["status"] == "reviewing" and g["chapters"][1]["status"] == "unwritten"
    # 再发起：待审批 → 不建新批次，直接停
    r = _batch(client, bid)
    assert r["reason"] == "refine_pending" and r["batches"] == []
    # 批次历史与单个报告
    hist = client.get(f"/api/books/{bid}/wanben/batches").json()
    assert len(hist) == 1 and hist[0]["id"] == b1["id"] and "report" not in hist[0] and hist[0]["summary"]["count"] == 1
    one = client.get(f"/api/books/{bid}/wanben/batches/{b1['id']}").json()
    rep = one["report"]["chapters"][0]
    for k in ("words", "opening", "climax", "hook", "consistency", "reader_score", "failed", "in_refine"):
        assert k in rep
    assert rep["in_refine"] is True and len(rep["opening"]["head"]) <= 100
    assert one["report"]["summary"]["awaiting_approval"] == [1]
    assert client.get(f"/api/books/{bid}/wanben/batches/999999").status_code == 404

    # 3) 人工审批（现有提交接口）后，精修范围改成只有第 2 章、待审批不暂停：第 2 章不提交，第 3、4 章照常提交
    wait_job(client, client.post(f"/api/chapters/{ch1['id']}/commit").json())
    _wanben(client, bid, refine_scope="custom", refine_ranges=[[2, 2]], pause_on_unapproved_refine=False)
    r = _batch(client, bid)
    b2 = r["batches"][0]
    assert b2["start_no"] == 2 and b2["end_no"] == 4 and b2["status"] == "done", b2
    sts = [client.get(f"/api/chapters/{c}").json() for c in b2["chapter_ids"]]
    assert [c["number"] for c in sts] == [2, 3, 4]
    assert sts[0]["status"] == "reviewing" and sts[1]["status"] == "committed" and sts[2]["status"] == "committed"

    # 4) 精修范围去掉第 2 章 → 它成了普通未提交章，批次停下等作者处理
    _wanben(client, bid, refine_scope="none")
    r = _batch(client, bid)
    assert r["reason"] == "pending_chapter"
    wait_job(client, client.post(f"/api/chapters/{sts[0]['id']}/commit").json())

    # 5) 暂停：发起后立即暂停 → 当前章写完后停（或一章没写就停），批次状态 paused
    _wanben(client, bid, batch_size=5)
    job = client.post(f"/api/books/{bid}/wanben/batch").json()
    pz = client.post(f"/api/books/{bid}/wanben/batch/pause").json()
    assert pz["paused"] is True
    j = _wait_any(client, job["id"])
    assert j["status"] == "succeeded" and j["result"]["reason"] == "paused", j["result"]
    assert client.get(f"/api/books/{bid}/wanben/progress").json()["paused"] is True

    # 6) 连续跑批到目标章数：跨卷补齐章细纲（第 2 卷从第 11 章起），最后停在 target_reached
    _wanben(client, bid, auto_continue=True, batch_size=6)
    r = _batch(client, bid)
    assert r["stopped"] and r["reason"] == "target_reached", r
    assert len(r["batches"]) >= 2 and all(b["status"] == "done" for b in r["batches"])
    p = client.get(f"/api/books/{bid}/wanben/progress").json()
    assert p["chapters_written"] == 20 and p["chapters_committed"] == 20 and p["chapters_remaining"] == 0
    assert p["chapters_total"] == 20 and p["target_words"] == 40_000 and 0 < p["ratio"] <= 1
    assert p["current_volume"]["order"] == 2 and p["last_batch"]["status"] == "done" and p["paused"] is False
    nodes = client.get(f"/api/books/{bid}/outline").json()
    flat = nodes if isinstance(nodes, list) else nodes.get("nodes", [])
    assert max(n["order"] for n in flat if n.get("level") == "chapter") == 20  # 不越过全书最后一章
    r = _batch(client, bid)
    assert r["reason"] == "target_reached" and r["batches"] == []

    # 7) 迭代：任意已写章（已提交的第 3 章）跑 2 轮定点修，产出新版本不改正文；采纳后可撤回
    chs = client.get(f"/api/books/{bid}/chapters").json()
    c3 = next(c for c in chs if c["number"] == 3)
    before = client.get(f"/api/chapters/{c3['id']}").json()["content"]
    j = wait_job(client, client.post(f"/api/books/{bid}/wanben/iterate", json={"start": 3, "end": 3, "rounds": 2, "method": "patch"}).json())
    its = j["result"]["iterations"]
    assert [i["round"] for i in its] == [1, 2] and j["result"]["stopped"] is False
    for i in its:
        assert set(i["scores"]) == {"before", "after", "delta"} and i["status"] == "pending"
        assert "overall" in i["scores"]["after"] and "reader" in i["scores"]["after"]
    assert its[1]["scores"]["before"] == its[0]["scores"]["after"]  # 第 2 轮以第 1 轮结果为底稿
    assert client.get(f"/api/chapters/{c3['id']}").json()["content"] == before  # 不自动落库
    lst = client.get(f"/api/books/{bid}/wanben/iterations", params={"number": 3}).json()
    assert len(lst) == 2 and lst[0]["stale"] is False and "content" not in lst[0]
    full = client.get(f"/api/books/{bid}/wanben/iterations/{its[1]['id']}").json()
    assert full["content"] and full["base_content"] and full["review"]
    a = client.post(f"/api/books/{bid}/wanben/iterations/{its[1]['id']}/adopt").json()
    assert a["iteration"]["status"] == "adopted" and a["chapter_status"] == "committed"
    assert client.get(f"/api/chapters/{c3['id']}").json()["content"] == full["content"]
    assert client.post(f"/api/books/{bid}/wanben/iterations/{its[1]['id']}/adopt").status_code == 409
    d = client.post(f"/api/books/{bid}/wanben/iterations/{its[0]['id']}/discard").json()
    assert d["status"] == "discarded"
    assert client.post(f"/api/chapters/{c3['id']}/undo").status_code == 200
    assert client.get(f"/api/chapters/{c3['id']}").json()["content"] == before
    # 再来一轮（整章重写 + 作者要求）：轮次累计
    j = wait_job(client, client.post(f"/api/books/{bid}/wanben/iterate",
                                     json={"numbers": [3], "rounds": 1, "method": "rewrite", "instruction": "节奏再快一点"}).json())
    assert j["result"]["iterations"][0]["round"] == 3 and j["result"]["iterations"][0]["method"] == "rewrite"
    assert client.post(f"/api/books/{bid}/wanben/iterate", json={"start": 99, "end": 99}).status_code == 409
    assert client.post(f"/api/books/{bid}/wanben/iterate", json={}).status_code == 400

    # 8) 导出：整书 TXT（书名、按章标题+正文），发布包里也有一份；都不含 AI 声明
    t = client.get(f"/api/books/{bid}/wanben/export.txt")
    assert t.status_code == 200 and t.headers["content-type"].startswith("text/plain")
    txt = t.text
    assert txt.startswith("完本流程书\n") and "第1章 " in txt and "第20章 " in txt
    assert txt.index("第1章 ") < txt.index("第2章 ") < txt.index("第20章 ")
    assert "AI" not in txt and "人工智能" not in txt
    import io
    import zipfile

    z = client.get(f"/api/books/{bid}/export")
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    names = zf.namelist()
    assert "AI申报提示.md" not in names
    whole = next(n for n in names if n.endswith("_全书.txt"))
    assert zf.read(whole).decode() == txt


def test_plan_retarget_returns_diff(client: TestClient) -> None:
    bid = _book(client, "改目标书")
    _wanben(client, bid, mode="wanben", target_words=40_000, chapter_words=2000)
    wait_job(client, client.post(f"/api/books/{bid}/wanben/plan").json())
    _wanben(client, bid, target_words=60_000)
    res = wait_job(client, client.post(f"/api/books/{bid}/wanben/plan").json())["result"]
    assert res["total_chapters"] == {"before": 20, "after": 30}
    assert [(v["start"], v["end"]) for v in res["volumes"]] == [(1, 15), (16, 30)]  # 按新目标重新均分
    d2 = next(d for d in res["diff"] if d["order"] == 2)
    assert d2["action"] == "updated" and {"start", "end"} <= set(d2["changed"]) and d2["before"]["end"] == 20
    d1 = next(d for d in res["diff"] if d["order"] == 1)
    assert d1["action"] == "updated" and "end" in d1["changed"] and d1["before"]["end"] == 10
    assert d1["after"]["title"] == d1["before"]["title"]  # 已有卷标题不推翻
    # 目标不变再规划一次：无变化
    res = wait_job(client, client.post(f"/api/books/{bid}/wanben/plan").json())["result"]
    assert all(d["action"] == "unchanged" and d["changed"] == [] for d in res["diff"])
    assert res["volumes"][-1]["finale"]["last_chapter"] == 30
    # 目标改短到已规划的章数以下：按已有章细纲兜底并给出提示
    _wanben(client, bid, target_words=10_000)
    res = wait_job(client, client.post(f"/api/books/{bid}/wanben/plan").json())["result"]
    assert res["total_chapters"]["after"] == 10 and len(res["volumes"]) == 1 and res["warnings"]
    assert res["volumes"][0]["finale"]["last_chapter"] == 10


def test_plan_without_outline_generates_first(client: TestClient) -> None:
    b = client.post("/api/books", json={"title": "无大纲完本书", "genre": "都市", "gender": "male", "premise": "旧账翻身"}).json()
    bid = b["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    _wanben(client, bid, mode="wanben", target_words=300_000, chapter_words=2000)
    res = wait_job(client, client.post(f"/api/books/{bid}/wanben/plan").json())["result"]
    assert res["total_chapters"]["after"] == 150
    vols = res["volumes"]
    assert len(vols) == 3 and vols[0]["start"] == 1 and vols[-1]["end"] == 150
    assert all(vols[i]["end"] + 1 == vols[i + 1]["start"] for i in range(len(vols) - 1))


@pytest.mark.skip(reason="v0.20 一次写成不再在 write_next 中跑 scene_plan，旧的按 scene_plan 注入失败的续跑用例已过时")
def test_batch_resume_after_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """批内某章在写作中途失败：Job failed 且可续跑；续跑从断点接着写，不重复建章。"""
    from app.services import writing

    real_refine = writing.refine_chapter
    state = {"fail": True}

    def refine(*a: Any, **k: Any) -> Any:
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("模拟精修失败")
        return real_refine(*a, **k)

    monkeypatch.setattr(writing, "refine_chapter", refine)
    bid = _book(client, "完本续跑书")
    _wanben(client, bid, mode="wanben", target_words=20_000, chapter_words=2000, batch_size=2, refine_scope="none")
    wait_job(client, client.post(f"/api/books/{bid}/wanben/plan").json())
    job = client.post(f"/api/books/{bid}/wanben/batch").json()
    j = _wait_any(client, job["id"])
    assert j["status"] == "failed" and j["resumable"] is True and j["checkpoint"]["stage"].startswith("batch:")
    hist = client.get(f"/api/books/{bid}/wanben/batches").json()
    assert hist[0]["status"] == "failed" and hist[0]["stop_reason"] == "error"
    r = client.post(f"/api/jobs/{job['id']}/resume")
    assert r.status_code == 200
    done = _wait_any(client, job["id"])
    assert done["status"] == "succeeded", done
    hist = client.get(f"/api/books/{bid}/wanben/batches").json()
    assert len(hist) == 1 and hist[0]["status"] == "done" and len(hist[0]["chapter_ids"]) == 2
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert sorted(c["number"] for c in chs) == [1, 2] and all(c["status"] == "committed" for c in chs)


def test_serial_write_next_unchanged_with_pending(client: TestClient) -> None:
    """连载书旧行为不变：有未提交章节时写下一章仍被拦下。"""
    bid = _book(client, "连载不变书")
    from app.db import kv_set, session_scope
    from app.services import writing

    with session_scope() as s:
        old = writing.writing_settings(s)
        kv_set(s, writing.WRITING_SETTINGS_KEY, {**old, "auto_commit": False})
    try:
        j = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json())
        assert j["result"]["committed"] is False
        j2 = _wait_any(client, client.post(f"/api/books/{bid}/chapters/write-next").json()["id"])
        assert j2["status"] == "failed" and "尚未提交" in (j2["error"] or "")
    finally:
        with session_scope() as s:
            kv_set(s, writing.WRITING_SETTINGS_KEY, old)
