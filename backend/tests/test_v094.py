"""v0.9.4：提交前修中等问题、数值一致性 lint、补丁后自动重审、任务断点续跑、lint 阈值校准。

全部走 mock LLM（必要时 monkeypatch 网关），不做真实网络与模型调用。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import wait_job

WORK = Path(__file__).resolve().parents[3] / "work"


def _write_book(client: TestClient, title: str = "v094 测试书", platform: str = "fanqie") -> int:
    b = client.post("/api/books", json={"title": title, "genre": "都市高武", "gender": "male", "platform_style": platform,
                                         "premise": "主角靠一本旧账翻身。"}).json()
    bid = b["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    return bid


def _wait_any(client: TestClient, job_id: int, timeout: float = 120) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed", "interrupted"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"任务超时：{job_id}")


class _ProxyGW:
    """包一层真实（mock）网关：按 task 截获部分调用，其余转发。"""

    def __init__(self, real: Any, chat_json: Any = None, chat: Any = None) -> None:
        self._real, self._cj, self._chat = real, chat_json, chat

    def chat_json(self, task: str, *a: Any, **k: Any) -> Any:
        if self._cj is not None:
            out = self._cj(task, *a, **k)
            if out is not None:
                return out
        return self._real.chat_json(task, *a, **k)

    def chat(self, task: str, *a: Any, **k: Any) -> Any:
        if self._chat is not None:
            out = self._chat(task, *a, **k)
            if out is not None:
                return out
        return self._real.chat(task, *a, **k)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _unique_sentences(content: str, n: int) -> list[str]:
    out: list[str] = []
    for s in re.findall(r"[^。！？\n“”]+[。！？]", content):
        s = s.strip()
        if len(s) >= 8 and content.count(s) == 1 and not any(s in o or o in s for o in out):
            out.append(s)
        if len(out) >= n:
            break
    assert len(out) >= n, "样章句子不够"
    return out


# ================================================================== 2. 数值一致性

def test_cn_to_num() -> None:
    from app.lint.numeric_zh import cn_to_num

    assert [cn_to_num(x) for x in ("十七", "二十", "一百五十", "三千", "两万", "一万五", "3.5", "三点五", "半")] == \
        [17, 20, 150, 3000, 20000, 15000, 3.5, 3.5, 0.5]
    assert cn_to_num("一些") is None


def test_numeric_conflicts_in_chapter() -> None:
    from app.lint.numeric_zh import numeric_consistency

    text = ("叶承今年十七岁，身高一米八，体重七十公斤。\n\n那块玄铁重八十斤。三天后的宗门大比，谁都跑不了。\n\n"
            "“叶承才十八岁？”有人嘀咕。后天的宗门大比他也要去。\n\n"
            "天罡号机甲高十八米。后来那台天罡号高二十米。玄铁足有一百六十斤重。叶承的体重一百四十斤。")
    issues = numeric_consistency(text, ["叶承", "天罡号"])
    by = {(i["object"], i["kind"]): i for i in issues}
    assert ("叶承", "age") in by and "十八岁" in by[("叶承", "age")]["comment"]
    assert ("玄铁", "weight") in by and ("天罡号", "height") in by and ("宗门大比", "days") in by
    assert "单位混用" in by[("叶承", "weight")]["comment"]  # 七十公斤 = 一百四十斤，数对得上但市制/公制混用
    for i in issues:
        assert i["severity"] == "mid" and i["dimension"] == "continuity" and i["source"] == "lint:numeric"
        assert i["quote"] in text and i["position"]["match"] in text
        assert text[i["position"]["offset"]:].startswith(i["position"]["match"])
        assert isinstance(i["position"]["paragraph"], int) and i["related"]


def test_numeric_no_false_positive() -> None:
    from app.lint.numeric_zh import numeric_consistency

    text = ("叶承今年十七岁。他十岁那年就没了爹，韩铎比他大三岁。\n\n三天后的宗门大比，谁都跑不了。\n\n第二天一早，"
            "后天的宗门大比就成了全城的话题。\n\n叶承修为炼气三层。一夜苦修，他终于突破，踏入炼气四层。\n\n他拎起三十斤的石锁，又放下五十斤的那块。")
    assert numeric_consistency(text, ["叶承", "韩铎"]) == []


def test_numeric_against_ledger_and_lint() -> None:
    from app.config import get_settings
    from app.lint.humanlint import lint_chapter
    from app.lint.numeric_zh import numeric_consistency

    led = [{"entity": "叶承", "key": "境界", "value": "炼气五层", "source": "事实账本·境界"},
           {"entity": "叶承", "key": "年龄", "value": "17", "source": "设定卡·年龄"}]
    text = "叶承修为炼气三层。\n\n叶承今年十九岁。"
    issues = numeric_consistency(text, ["叶承"], led)
    kinds = {i["kind"] for i in issues}
    assert {"realm", "age"} <= kinds
    assert all(i["related"].get("source") == "ledger" for i in issues)
    # 本章写了突破 → 境界与账本不同不报
    assert not any(i["kind"] == "realm" for i in numeric_consistency("叶承一举突破，踏入炼气三层。", ["叶承"], led))

    r = lint_chapter(text, get_settings().lint, (), ["叶承"], 5, platform="fanqie", ledger=led)
    d = r.to_dict()
    assert d["numeric_conflicts"] and any(w.startswith("数值不一致") for w in d["warnings"])
    assert r.craft_problem_count() >= len(d["numeric_conflicts"])


def test_numeric_issues_enter_review() -> None:
    from app.llm.gateway import get_gateway
    from app.services.review import run_review

    content = "叶承今年十七岁，站在门口。\n\n“叶承才十八岁？”有人嘀咕，他没理会，转身进了屋。"
    extra = [{"severity": "mid", "dimension": "continuity", "quote": "“叶承才十八岁？”有人嘀咕，他没理会，转身进了屋。",
              "comment": "年龄不一致", "position": {"offset": 15}, "source": "lint:numeric"},
             {"severity": "mid", "dimension": "continuity", "quote": "正文里没有这句", "comment": "x"}]
    review, _ = run_review(get_gateway(), content, 3, "{}", "叶承", [], {}, extra_issues=extra)
    got = [i for i in review["issues"] if i.get("source") == "lint:numeric"]
    assert len(got) == 1 and got[0]["position"]["offset"] == 15 and got[0]["dimension"] == "continuity"
    assert review["scores"]["continuity"] <= 90


def test_numeric_ledger_from_db(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import Card, Fact
    from app.services import writing

    bid = client.post("/api/books", json={"title": "账本书", "genre": "玄幻", "gender": "male"}).json()["id"]
    with session_scope() as s:
        c = Card(book_id=bid, type="character", name="叶承", summary="主角", data={"age": "17"})
        s.add(c)
        s.flush()
        s.add(Fact(book_id=bid, entity_id=c.id, key="境界", value="炼气五层", from_chapter=1))
        s.commit()
        led = writing.numeric_ledger(s, bid, 3)
        assert {e["key"] for e in led} >= {"境界", "年龄"}
        lint = writing.lint_for(s, bid, "叶承修为炼气三层。\n\n叶承今年十九岁。", 3)
        assert {i["kind"] for i in lint.numeric_issues} >= {"realm", "age"}
        # 第 1 章看不到第 1 章才登记的事实
        assert all(e["key"] != "境界" for e in writing.numeric_ledger(s, bid, 1))


# ================================================================== 5. 阈值校准

def test_lint_profiles_centralized(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import PlatformLintProfile, get_settings
    from app.lint.humanlint import lint_chapter
    from app.lint.platform import PROFILES, get_profile

    fq, qd, gen = get_profile("fanqie"), get_profile("qidian"), get_profile("generic")
    assert fq.tier == "fanqie" and qd.tier == "publish" and gen.tier == "publish"
    assert fq.long_para_chars == 100 and qd.long_para_chars is None and PROFILES["fanqie"].long_para_chars == 100
    assert fq.long_para_flagged(3, 20) and not fq.long_para_flagged(2, 20) and not fq.long_para_flagged(3, 40)

    st = get_settings()
    custom = dict(st.lint_profiles)
    custom["fanqie"] = PlatformLintProfile(long_para_chars=20, long_para_min_count=1, long_para_min_ratio=0.0)
    monkeypatch.setattr(st, "lint_profiles", custom)
    text = "他把门推开，屋里的灯还亮着，桌上的茶已经凉透了。\n\n“走。”他说。"
    r = lint_chapter(text, st.lint, platform="fanqie")
    assert r.long_paragraphs == [0] and r.long_para_flagged and r.to_dict()["lint_tier"] == "fanqie"


def test_fanqie_samples_not_flooded() -> None:
    """真实番茄风格样章（work/tuning 追读版 1–3 章）：番茄档不应因长段报警到需要定点修。"""
    from app.config import get_settings
    from app.lint.humanlint import lint_chapter

    files = [WORK / "tuning" / f"b3_ch{i}.txt" for i in (1, 3)]
    if not all(f.exists() for f in files):
        pytest.skip("样章不在")
    for f in files:
        r = lint_chapter(f.read_text("utf-8"), get_settings().lint, (), ("叶承",), 2, platform="fanqie")
        assert not r.long_para_flagged and not any(t["kind"] == "长段" for t in r.fix_targets)
        assert r.numeric_issues == []
        assert len(r.warnings) <= 1


# ================================================================== 1. 提交前修中等问题

def test_pre_commit_targets() -> None:
    from app.services.review import pre_commit_targets

    content = "第一句在这里写着。第二句也在正文里。第三句同样存在呢。"
    rv = {"issues": [
        {"severity": "mid", "dimension": "continuity", "quote": "第一句在这里写着。"},
        {"severity": "mid", "dimension": "retention", "quote": "第二句也在正文里。"},
        {"severity": "mid", "dimension": "pacing", "quote": "第三句同样存在呢。"},
        {"severity": "high", "dimension": "continuity", "quote": "第三句同样存在呢。"},
        {"severity": "mid", "dimension": "continuity", "quote": "不在正文的句子。"},
    ], "patches": [
        {"index": 0, "original": "第一句在这里写着。", "improved": "x", "issue_ref": 0, "applied": False},
        {"index": 1, "original": "第三句同样存在呢。", "improved": "y", "issue_ref": 2, "applied": False},
        {"index": 2, "original": "第二句也在正文里。", "improved": "z", "issue_ref": 1, "applied": True},
    ]}
    idx, pats = pre_commit_targets(rv, content)
    assert idx == [0, 1] and pats == [0]


def _set_review(chapter_id: int, issues: list[dict[str, Any]], patches: list[dict[str, Any]]) -> None:
    from app.db import session_scope
    from app.models.tables import Chapter
    from app.services.review import compute_scores

    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        ch.review = {"scores": compute_scores(issues), "issues": issues, "passed": True, "patches": patches}
        s.add(ch)
        s.commit()


def test_pre_commit_fix_and_switches(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import writing

    real = writing.get_gateway()

    def cj(task: str, *a: Any, **k: Any) -> Any:
        meta = k.get("meta") or {}
        if task == "humanize" and meta.get("purpose") == "pre_commit_mid_fix":
            return {"patches": [{"quote": q, "replacement": q.rstrip("。！？") + "（修）。"} for q in meta.get("fix_quotes") or []]}
        return None

    old = client.get("/api/settings/writing").json()
    assert old["fix_mid_before_commit"] is True and old["auto_rereview"] is True
    client.put("/api/settings/writing", json={"auto_commit": False})
    try:
        bid = _write_book(client, "提交前修书")
        r = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
        assert r["committed"] is False
        cid = r["chapter_id"]
        content = client.get(f"/api/chapters/{cid}").json()["content"]
        q1, q2, q3 = _unique_sentences(content, 3)
        _set_review(cid, [
            {"severity": "mid", "dimension": "continuity", "quote": q1, "comment": "道具位置前后矛盾"},
            {"severity": "mid", "dimension": "retention", "quote": q2, "comment": "老读者：这里想划走"},
            {"severity": "mid", "dimension": "pacing", "quote": q3, "comment": "节奏慢（不在提交前修的范围）"},
        ], [{"index": 0, "original": q1, "improved": q1 + "【补】", "reason": "", "issue_ref": 0, "severity": "mid", "applied": False}])
        monkeypatch.setattr(writing, "get_gateway", lambda: _ProxyGW(real, chat_json=cj))
        wait_job(client, client.post(f"/api/chapters/{cid}/commit").json())
        ch = client.get(f"/api/chapters/{cid}").json()
        assert ch["status"] == "committed"
        assert q1 + "【补】" in ch["content"] and q2.rstrip("。！？") + "（修）。" in ch["content"] and q3 in ch["content"]
        pcf = ch["review"]["pre_commit_fix"]
        assert pcf["issues"] == [0, 1] and pcf["patches_applied"] == [0] and pcf["rewritten"] == 1 and pcf["changed"]
        assert ch["review"]["patches"][0]["applied"] is True
        assert any("提交前修中等问题" in w for w in ch["changes"]["warnings"])

        # 书级开关关掉：第 2 章同样的问题不修
        bs = client.put(f"/api/books/{bid}/writing-settings", json={"fix_mid_before_commit": False}).json()
        assert bs["overrides"]["fix_mid_before_commit"] is False and bs["effective"]["fix_mid_before_commit"] is False
        assert bs["global"]["fix_mid_before_commit"] is True and bs["overrides"]["auto_rereview"] is None
        r2 = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
        cid2 = r2["chapter_id"]
        c2 = client.get(f"/api/chapters/{cid2}").json()["content"]
        p1, p2 = _unique_sentences(c2, 2)
        _set_review(cid2, [{"severity": "mid", "dimension": "continuity", "quote": p1, "comment": "x"},
                           {"severity": "mid", "dimension": "retention", "quote": p2, "comment": "y"}],
                    [{"index": 0, "original": p1, "improved": p1 + "【补】", "reason": "", "issue_ref": 0, "severity": "mid", "applied": False}])
        wait_job(client, client.post(f"/api/chapters/{cid2}/commit").json())
        ch2 = client.get(f"/api/chapters/{cid2}").json()
        assert ch2["status"] == "committed" and ch2["content"] == c2 and ch2["review"]["pre_commit_fix"] is None
        # null 恢复跟随全局
        bs = client.put(f"/api/books/{bid}/writing-settings", json={"fix_mid_before_commit": None}).json()
        assert bs["overrides"]["fix_mid_before_commit"] is None and bs["effective"]["fix_mid_before_commit"] is True
        assert client.get("/api/books/999999/writing-settings").status_code == 404
    finally:
        client.put("/api/settings/writing", json={"auto_commit": old["auto_commit"]})


def test_global_switch_off_skips_fix(client: TestClient) -> None:
    from app.db import session_scope
    from app.services import writing

    client.put("/api/settings/writing", json={"fix_mid_before_commit": False})
    try:
        assert client.get("/api/settings/writing").json()["fix_mid_before_commit"] is False
        with session_scope() as s:
            assert writing.effective_writing_settings(s, None)["fix_mid_before_commit"] is False
    finally:
        client.put("/api/settings/writing", json={"fix_mid_before_commit": True})


# ================================================================== 3. 补丁后自动重审

def test_rereview_after_patches_flags_high(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import review as review_svc
    from app.services import writing

    real = review_svc.run_review
    calls = {"after_patch": 0}

    def fake_run_review(gw: Any, content: str, *a: Any, **k: Any) -> Any:
        rv, dropped = real(gw, content, *a, **k)
        if "（补丁）" in content:
            calls["after_patch"] += 1
        first = content.split("\n")[0]
        q = first[: first.find("。") + 1] if "。" in first else first[:20]
        rv["issues"].append({"severity": "high", "dimension": "coherence", "quote": q, "comment": "测试 high"})
        rv["patches"] = [{"index": 0, "original": q, "improved": q + "（补丁）", "reason": "测试",
                          "issue_ref": len(rv["issues"]) - 1, "severity": "high", "applied": False}]
        rv["passed"] = False
        return rv, dropped

    monkeypatch.setattr(writing, "run_review", fake_run_review)
    bid = _write_book(client, "重审书")
    r = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
    assert r["review_patches"]["applied"] == [0]
    assert calls["after_patch"] == 1  # 最多重审 1 次
    rr = r["rereview"]
    assert rr["round"] == 1 and rr["high_left"] >= 1 and rr["passed"] is False
    assert r["committed"] is False and "标记" in r["reason"]
    ch = client.get(f"/api/chapters/{r['chapter_id']}").json()
    assert ch["status"] != "committed" and ch["review"]["flagged"] is True and ch["review"]["flag_reason"]
    assert ch["review"]["rereview"]["round"] == 1
    # 旧补丁保留（已应用），新补丁接在后面；patch_log 仍在
    assert ch["review"]["patches"][0]["applied"] is True and ch["review"]["patch_log"][-1]["applied"] == [0]
    assert any("high" in w for w in ch["changes"]["warnings"])

    # 书级关闭重审：不再重审
    client.delete(f"/api/chapters/{r['chapter_id']}")
    client.put(f"/api/books/{bid}/writing-settings", json={"auto_rereview": False})
    calls["after_patch"] = 0
    r2 = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
    assert "rereview" not in r2 and calls["after_patch"] == 0


def test_stale_patch_skipped() -> None:
    from app.services.review import apply_patches

    pats = [{"index": 0, "original": "一二三四五", "improved": "x", "stale": True}]
    new, applied, skipped = apply_patches("一二三四五六", pats, [0])
    assert new == "一二三四五六" and not applied and "过期" in skipped[0]["reason"]


# ================================================================== 4. 断点续跑

def test_checkpoint_helpers_and_recover() -> None:
    from app.db import session_scope
    from app.jobs import manager
    from app.models.tables import Job

    a = manager.create_job("chapter_write_next", None)
    b = manager.create_job("chapter_review", None)
    c = manager.create_job("chapter_write_next", None)
    manager.save_checkpoint(a.id or 0, "scenes", {"scenes": [{}, {}, {}], "number": 1})
    manager.save_checkpoint(b.id or 0, "x", {})
    with session_scope() as s:
        for jid in (a.id, b.id, c.id):
            j = s.get(Job, jid)
            assert j is not None
            j.status = "running"
            s.add(j)
        s.commit()
    assert manager.recover_on_startup() >= 3
    with session_scope() as s:
        ja, jb, jc = s.get(Job, a.id), s.get(Job, b.id), s.get(Job, c.id)
        assert ja is not None and jb is not None and jc is not None
        assert ja.status == "interrupted" and "可续跑" in (ja.error or "")
        assert jb.status == "failed" and jc.status == "failed"  # 没注册续跑 / 没断点
        info = manager.resume_info(ja)
        assert info["resumable"] is True and info["checkpoint"]["stage"] == "scenes" and info["checkpoint"]["scenes_total"] == 3
        assert manager.resume_info(jb)["resumable"] is False and manager.resume_info(jc)["checkpoint"] is None
    with pytest.raises(manager.NotResumable):
        manager.resume(b.id or 0)
    with pytest.raises(manager.NotResumable):
        manager.resume(c.id or 0)
    with pytest.raises(LookupError):
        manager.resume(99999999)
    manager.clear_checkpoint(a.id or 0)
    assert manager.load_checkpoint(a.id or 0) is None


def test_write_next_resume_from_last_scene(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import session_scope
    from app.jobs import manager
    from app.models.tables import Job
    from app.services import writing

    real = writing.get_gateway()
    calls = {"scene": 0, "fail_at": 3}

    def chat(task: str, *a: Any, **k: Any) -> Any:
        if task == "writing_scene":
            calls["scene"] += 1
            if calls["scene"] == calls["fail_at"]:
                raise RuntimeError("模拟进程中断")
        return None

    monkeypatch.setattr(writing, "get_gateway", lambda: _ProxyGW(real, chat=chat))
    bid = _write_book(client, "续跑书")
    job = client.post(f"/api/books/{bid}/chapters/write-next").json()
    j = _wait_any(client, job["id"])
    assert j["status"] == "failed" and j["resumable"] is True
    cp = j["checkpoint"]
    assert cp["stage"].startswith("scene:1:2/") and cp["scenes_done"] == 2
    total = cp["scenes_total"]
    assert total >= 3

    # 模拟进程重启：任务停在 running → recover_on_startup 标 interrupted
    with session_scope() as s:
        row = s.get(Job, job["id"])
        assert row is not None
        row.status = "running"
        s.add(row)
        s.commit()
    manager.recover_on_startup()
    j = client.get(f"/api/jobs/{job['id']}").json()
    assert j["status"] == "interrupted" and j["resumable"] is True

    calls["scene"], calls["fail_at"] = 0, -1
    r = client.post(f"/api/jobs/{job['id']}/resume")
    assert r.status_code == 200 and r.json()["id"] == job["id"]
    done = _wait_any(client, job["id"])
    assert done["status"] == "succeeded", done
    assert calls["scene"] == total - 2  # 只写剩下的场景
    assert done["resumable"] is False and done["checkpoint"] is None
    res = done["result"]
    ch = client.get(f"/api/chapters/{res['chapter_id']}").json()
    assert ch["content"] and res["scenes"] == total
    # 已成功的任务不能再续跑；不存在的 404
    assert client.post(f"/api/jobs/{job['id']}/resume").status_code == 409
    assert client.post("/api/jobs/99999999/resume").status_code == 404
    if not res.get("committed"):
        wait_job(client, client.post(f"/api/chapters/{res['chapter_id']}/commit").json())


def test_resume_after_chapter_created(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """断点在建章之后（精修阶段失败）：续跑不重写正文，直接从精修接着做。"""
    from app.services import writing

    real_refine = writing.refine_chapter
    state = {"fail": True}

    def refine(*a: Any, **k: Any) -> Any:
        if state["fail"]:
            raise RuntimeError("模拟精修失败")
        return real_refine(*a, **k)

    monkeypatch.setattr(writing, "refine_chapter", refine)
    bid = _write_book(client, "建章后续跑书")
    job = client.post(f"/api/books/{bid}/chapters/write-next").json()
    j = _wait_any(client, job["id"])
    assert j["status"] == "failed" and j["checkpoint"]["stage"] == "adopted" and j["checkpoint"]["chapter_id"]
    cid = j["checkpoint"]["chapter_id"]
    real = writing.get_gateway()
    scenes = {"n": 0}

    def chat(task: str, *a: Any, **k: Any) -> Any:
        if task == "writing_scene":
            scenes["n"] += 1
        return None

    monkeypatch.setattr(writing, "get_gateway", lambda: _ProxyGW(real, chat=chat))
    state["fail"] = False
    client.post(f"/api/jobs/{job['id']}/resume")
    done = _wait_any(client, job["id"])
    assert done["status"] == "succeeded" and done["result"]["chapter_id"] == cid and scenes["n"] == 0
    assert "rewrite_round" in done["result"]
