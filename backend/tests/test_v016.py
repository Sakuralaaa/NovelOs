"""v0.16 一键成书：选题/同人一路跑到完本、自愈、卷末复盘与决策点、作者导向、长篇记忆、备用路由、创作想法 AI 重写。全部 mock。"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from conftest import wait_job
from test_v010 import _fanfic_book, _source


def _wait_run(client: TestClient, bid: int, statuses: tuple[str, ...], timeout: float = 300) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        o = client.get(f"/api/books/{bid}/autopilot").json()
        r = o.get("run") or {}
        if r.get("status") in statuses and not o["running"]:
            return o
        time.sleep(0.1)
    raise AssertionError(f"一键成书超时：{client.get(f'/api/books/{bid}/autopilot').json().get('run')}")


SMALL = {"target_words": 24_000, "chapter_words": 2000, "batch_size": 4, "golden_chapters": 3}


def test_idea_autopilot_full(client: TestClient) -> None:
    ids = wait_job(client, client.post("/api/ideas/generate", json={"gender": "male", "count": 1}).json())["result"]["idea_ids"]
    r = client.post(f"/api/ideas/{ids[0]}/autopilot", json={**SMALL, "level": "full"})
    assert r.status_code == 200, r.text
    bid = r.json()["book"]["id"]
    o = _wait_run(client, bid, ("done", "stopped"))
    run = o["run"]
    assert run["status"] == "done", run
    p = o["progress"]
    assert p["chapters_written"] == p["chapters_total"] == 12 and p["chapters_committed"] == 12
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert all(c["status"] == "committed" for c in chs)
    assert o["recaps"], "每卷写完都有前情回顾"
    assert all(d["status"] == "auto" for d in o["decisions"])
    assert any(e["kind"] == "done" for e in run["events"])
    assert client.get(f"/api/books/{bid}/wanben").json()["mode"] == "wanben"
    # 再开始：已完结的运行不会重写
    assert client.post(f"/api/books/{bid}/autopilot/start").status_code == 200
    o2 = _wait_run(client, bid, ("done", "stopped"))
    assert o2["run"]["status"] == "done"


def test_guided_decisions_and_guidance(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import Book
    from app.services import autopilot, context, common

    b = client.post("/api/books", json={"title": "关键时刻", "genre": "玄幻", "gender": "male", "premise": "少年拿到一枚会说话的戒指。"}).json()
    bid = b["id"]
    r = client.post(f"/api/books/{bid}/autopilot/start", json={**SMALL, "level": "guided", "stop_on": ["opening", "volume"]})
    assert r.status_code == 200, r.text
    o = _wait_run(client, bid, ("waiting", "stopped"))
    assert o["run"]["status"] == "waiting", o["run"]
    d = next(x for x in o["decisions"] if x["status"] == "pending")
    assert d["kind"] == "opening"
    assert client.post(f"/api/books/{bid}/autopilot/start").status_code == 409  # 有待拍板的决策点
    r = client.post(f"/api/books/{bid}/autopilot/decisions/{d['id']}", json={"choice": 0, "custom": "女主早点登场"})
    assert r.status_code == 200, r.text
    o = _wait_run(client, bid, ("waiting", "done", "stopped"))
    with session_scope() as s:
        assert "女主早点登场" in autopilot.guidance_lines(s, bid, 5)
        assert not autopilot.guidance_lines(s, bid, 2)
    if o["run"]["status"] == "waiting":
        d = next(x for x in o["decisions"] if x["status"] == "pending")
        assert d["kind"] == "volume" and len(d["options"]) == 3
        r = client.post(f"/api/books/{bid}/autopilot/decisions/{d['id']}", json={"choice": 1, "custom": ""})
        assert r.status_code == 200
        with session_scope() as s:
            from app.services import wanben
            v2 = wanben.volumes(s, bid)[d["volume"]]
            assert "秘境" in v2.title and "关键转折" in v2.summary
        o = _wait_run(client, bid, ("waiting", "done", "stopped"))
    # 写完前情卷回顾进写章上下文
    with session_scope() as s:
        book = s.get(Book, bid)
        node = max((n for n in common.outline_nodes(s, bid) if n.level == "chapter"), key=lambda n: n.order)
        text, state, end = context.volume_recaps(s, bid, node.order)
        assert text and 0 < end < node.order
        pack = context.build_context_pack(s, book, node)
        assert "【前情卷回顾】" in pack.suffix and "【作者导向】" in pack.suffix


def test_heal_and_retry(client: TestClient, monkeypatch: Any) -> None:
    """v0.17：按章自愈，最多 2 轮；还没过就停下「待你看」，不放行、不往下写；作者放行后接着写到完。"""
    from app.llm.gateway import LLMError
    from app.services import autopilot, wanben, writing

    monkeypatch.setattr(autopilot, "RETRY_WAITS", (0, 0, 0))
    real = wanben._run_one_batch
    calls = {"n": 0}

    def flaky(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("所有渠道均失败：测试")
        return real(*a, **k)

    monkeypatch.setattr(wanben, "_run_one_batch", flaky)
    state = {"fail": True}
    real_ev = writing._evaluate

    def ev(*a: Any, **k: Any) -> Any:
        rv, lint, dropped = real_ev(*a, **k)
        if state["fail"]:
            rv = {**rv, "passed": False, "issues": [*rv["issues"], {"severity": "high", "dimension": "hook", "quote": "",
                                                                   "comment": "测试：冲突没立住"}]}
        return rv, lint, dropped

    monkeypatch.setattr(writing, "_evaluate", ev)
    b = client.post("/api/books", json={"title": "自愈", "genre": "都市", "gender": "male", "premise": "外卖员捡到神秘手机。"}).json()
    bid = b["id"]
    r = client.post(f"/api/books/{bid}/autopilot/start", json={**SMALL, "target_words": 10_000, "batch_size": 4, "golden_chapters": 0})
    assert r.status_code == 200
    o = _wait_run(client, bid, ("waiting", "done", "stopped"))
    run = o["run"]
    assert run["status"] == "waiting" and run["stop_reason"] == "needs_review", run
    assert run["stats"].get("retries", 0) >= 1 and any(e["kind"] == "retry" for e in run["events"])
    assert run["stats"].get("forced", 0) == 0 and run["stats"].get("needs_review") == 1
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert [c["number"] for c in chs] == [1] and chs[0]["status"] != "committed"  # 没往下写
    heal_events = [e for e in run["events"] if e["kind"] == "heal"]
    assert 1 <= len(heal_events) <= 2
    fl = run["flags"][0]
    assert fl["blocking"] and fl["chapter_id"] == chs[0]["id"] and "冲突没立住" in fl["reason"]
    ch = client.get(f"/api/chapters/{chs[0]['id']}").json()
    assert ch["review"]["heal"]["rounds"] == 2 and ch["review"]["heal"]["exhausted"]
    # 再点继续：正文没改，不再自动重写，继续等作者
    client.post(f"/api/books/{bid}/autopilot/start")
    o = _wait_run(client, bid, ("waiting", "done", "stopped"))
    assert o["run"]["stop_reason"] == "needs_review"
    assert len([e for e in o["run"]["events"] if e["kind"] == "heal"]) == len(heal_events)
    # 作者放行：照现在的正文提交，划掉清单，接着写到完
    j = wait_job(client, client.post(f"/api/books/{bid}/autopilot/flags/{fl['chapter_id']}/accept").json())
    assert j["status"] == "succeeded", j
    assert client.get(f"/api/chapters/{fl['chapter_id']}").json()["status"] == "committed"
    assert not client.get(f"/api/books/{bid}/autopilot").json()["run"]["flags"]
    state["fail"] = False
    client.post(f"/api/books/{bid}/autopilot/start")
    o = _wait_run(client, bid, ("waiting", "done", "stopped"))
    assert o["run"]["status"] == "done", o["run"]
    assert all(c["status"] == "committed" for c in client.get(f"/api/books/{bid}/chapters").json())


def test_heal_rejects_short_and_equal_rewrites(client: TestClient, monkeypatch: Any) -> None:
    """自愈新稿不到目标字数 85% 不用；分数不比原稿高不换；比原稿好且过审就换上并提交。"""
    from app.db import session_scope
    from app.models.tables import AutoRun, Chapter
    from app.services import autopilot, wanben, writing

    b = client.post("/api/books", json={"title": "自愈细则", "genre": "都市", "gender": "male", "premise": "外卖员捡到神秘手机。",
                                        "chapter_words": 2000}).json()
    bid = b["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    monkeypatch.setattr(writing, "effective_writing_settings", lambda s, b: {**writing.writing_settings(s), "auto_commit": False})
    r = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next", json={"variants": 1}).json(), timeout=120)["result"]
    cid = r["chapter_id"]
    with session_scope() as s:
        run = AutoRun(book_id=bid, status="running", stage="write", settings={}, state={}, stats={})
        s.add(run)
        ch = s.get(Chapter, cid)
        ch.review = {**(ch.review or {}), "passed": False, "scores": {"overall": 60},
                     "reader": {"score": 4, "verdict": "主角一直挨打，没意思", "waiting": "等他还手"}}
        s.add(ch)
        s.commit()
        run_id = run.id
        original = ch.content
    seen: list[str] = []
    monkeypatch.setattr(writing, "rewrite_full", lambda cid_, content, ins, route=None: seen.append(ins) or "短稿。" * 50)
    assert autopilot.heal_chapter(bid, run_id, cid) == "needs_review"
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        assert ch.content == original and ch.status != "committed"
        evs = [e["text"] for e in s.get(AutoRun, run_id).events]
    assert sum("不采用" in t for t in evs) == 2
    assert "读者意见" in seen[0] and "主角这章想要什么" in seen[0]

    # 新稿够长、过审、分数更高 → 换上并提交
    good = original + "\n\n" + "陈野把单据往桌上一拍，对面的人脸色当场变了。" * 10
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        ch.review = {"passed": False, "scores": {"overall": 60}, "issues": []}  # 新一轮：清掉耗尽标记
        s.add(ch)
        s.commit()
    monkeypatch.setattr(writing, "rewrite_full", lambda cid_, content, ins, route=None: good)
    monkeypatch.setattr(wanben, "_evaluate_text", lambda cid_, content: ({"passed": True, "scores": {"overall": 90}, "issues": [],
                                                                         "reader": {"score": 8}}, {}))
    assert autopilot.heal_chapter(bid, run_id, cid) == "committed"
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        assert ch.status == "committed" and "当场变了" in ch.content


def test_llm_down_stops_and_pause(client: TestClient, monkeypatch: Any) -> None:
    from app.llm.gateway import LLMError
    from app.services import autopilot, wanben

    monkeypatch.setattr(autopilot, "RETRY_WAITS", (0,))

    def down(*a: Any, **k: Any) -> Any:
        raise LLMError("所有渠道均失败：测试")

    monkeypatch.setattr(wanben, "plan_job", down)
    b = client.post("/api/books", json={"title": "挂了", "genre": "都市", "gender": "male", "premise": "x"}).json()
    bid = b["id"]
    client.post(f"/api/books/{bid}/autopilot/start", json=SMALL)
    o = _wait_run(client, bid, ("stopped",))
    assert o["run"]["stop_reason"] == "llm_down"
    assert client.post(f"/api/books/{bid}/autopilot/pause").json()["ok"]


def test_fanfic_autopilot(client: TestClient) -> None:
    sid = _source(client)["id"]
    bid = _fanfic_book(client, sid, fidelity="moderate", direction="canon_fill")["id"]
    r = client.post(f"/api/books/{bid}/autopilot/start", json={**SMALL, "target_words": 10_000, "golden_chapters": 0})
    assert r.status_code == 200, r.text
    o = _wait_run(client, bid, ("done", "stopped"))
    assert o["run"]["status"] == "done", o["run"]
    assert o["fanfic"]
    cards = client.get(f"/api/books/{bid}/cards").json()
    assert any((c.get("data") or {}).get("from_fanfic_source") for c in cards)


def test_settings_validation(client: TestClient) -> None:
    b = client.post("/api/books", json={"title": "设置", "genre": "都市", "gender": "male"}).json()
    bid = b["id"]
    st = client.put(f"/api/books/{bid}/autopilot/settings", json={"level": "guided", "target_words": 1_200_000}).json()
    assert st["level"] == "guided" and st["target_words"] == 1_200_000
    assert client.put(f"/api/books/{bid}/autopilot/settings", json={"level": "x"}).status_code == 422


def test_rolling_volumes_for_long_books() -> None:
    from app.services import wanben

    assert wanben.MAX_VOLUMES >= 17  # 200 万字约 1000 章，按 60 章一卷不再被压成 12 卷


def test_related_old_chapters_by_similarity() -> None:
    from types import SimpleNamespace

    from app.services.context import related_old_chapters

    older = [SimpleNamespace(id=i, number=i, title="", summary=t) for i, t in enumerate([
        "主角在集市卖草药，被地痞找麻烦。", "主角在青云山脚的古洞里得到一块残缺的玉简，上面刻着上古阵法。",
        "主角和师姐比剑。", "宗门大比开始报名。"], 1)]
    got = related_old_chapters(older, set(), [], "主角带着残缺玉简重回青云山古洞，补全上古阵法")
    assert got and got[0].number == 2


def test_backup_routing(client: TestClient) -> None:
    from app.db import session_scope
    from app.llm.gateway import resolve_targets
    from app.models.tables import Channel

    with session_scope() as s:
        a = Channel(name="甲", base_url="http://a.invalid", api_key_enc="", models=["m1"], enabled=False)
        b = Channel(name="乙", base_url="http://b.invalid", api_key_enc="", models=["m2", "m3"], enabled=False)
        s.add(a)
        s.add(b)
        s.commit()
        aid, bid = a.id, b.id
    try:
        r = client.put("/api/settings/routing/backup", json={"writer": [f"{bid}:m3", f"{bid}:m3"]})
        assert r.status_code == 200 and r.json()["writer"] == [f"{bid}:m3"]
        assert client.put("/api/settings/routing/backup", json={"image": ["1:x"]}).status_code == 400
        assert client.put("/api/settings/routing/backup", json={"writer": ["999999:x"]}).status_code == 400
        with session_scope() as s:
            for c in (s.get(Channel, aid), s.get(Channel, bid)):
                c.enabled = True
                s.add(c)
            s.commit()
        client.put("/api/settings/routing", json={"writer": f"{aid}:m1"})
        with session_scope() as s:
            ts = resolve_targets(s, "writer")
        assert [(t.channel_id, t.model) for t in ts] == [(aid, "m1"), (bid, "m3")]
    finally:
        client.put("/api/settings/routing/backup", json={"writer": []})
        client.put("/api/settings/routing", json={"writer": None})
        with session_scope() as s:
            for cid in (aid, bid):
                c = s.get(Channel, cid)
                if c:
                    s.delete(c)
            s.commit()


def test_fanfic_idea_rewrite(client: TestClient) -> None:
    sid = _source(client)["id"]
    r = client.post("/api/fanfic/idea/rewrite", json={"source_id": sid, "direction": "system", "text": "穿越成同学\n\n诸天联动",
                                                      "instruction": "节奏快一点"})
    assert r.status_code == 200, r.text
    assert len(r.json()["text"]) > 50 and "节奏快一点" in r.json()["text"]
    assert client.post("/api/fanfic/idea/rewrite", json={"source_id": 999999, "text": "x"}).status_code == 404
