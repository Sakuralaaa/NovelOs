"""v0.12 E6 批量质检：按章节区间批量 消痕/语感/审稿/AI 率/排版/改章名；暂停续跑、单章失败重试、
改写后复检 AI 率、DIFF 确认后写回（含一键全部采纳）、朱雀报告导出 HTML（打印存 PDF）。

模型走 mock；朱雀走 httpx.MockTransport，不真实调用。
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import wait_job

_REAL_CLIENT = httpx.Client

TEXT = ("林恩深吸一口气，嘴角勾起一抹冷笑。他不禁握紧了拳头，三千灵石就这么没了。\n\n"
        "苏晚站在门口，眼中闪过一丝担忧：“你真要去？第九层可不是闹着玩的。”\n\n"
        "林恩点头。与此同时，远处传来钟声，一共敲了七下，整整十二个时辰过去了，天色仿佛被墨染过一样黑。")


def _book(client: TestClient, n: int = 3, title: str = "批量质检测试书", text: str = TEXT) -> tuple[int, list[int]]:
    from app.db import session_scope
    from app.lint.humanlint import count_words
    from app.models.tables import Card, Chapter

    bid = client.post("/api/books", json={"title": title, "genre": "都市高武", "gender": "male"}).json()["id"]
    ids = []
    with session_scope() as s:
        s.add(Card(book_id=bid, type="character", name="林恩", summary="主角", data={"role": "protagonist"}, known_by=[]))
        s.add(Card(book_id=bid, type="character", name="苏晚", summary="女主", data={}, known_by=[]))
        for i in range(1, n + 1):
            body = text.replace("三千", f"{i}千") if i > 1 else text
            ch = Chapter(book_id=bid, number=i, title=f"第{i}章旧标题", content=body, words=count_words(body), status="committed")
            s.add(ch)
            s.commit()
            ids.append(ch.id or 0)
    return bid, ids


def _run(client: TestClient, bid: int, op: str, a: int, b: int, **kw: Any) -> dict[str, Any]:
    r = client.post(f"/api/books/{bid}/batch", json={"op": op, "from": a, "to": b, **kw})
    assert r.status_code == 200, r.text
    d = r.json()
    wait_job(client, d["job"])
    return client.get(f"/api/books/{bid}/batch/{d['id']}").json()


def _mock_zhuque(monkeypatch: pytest.MonkeyPatch, soft: Any) -> list[str]:
    """soft: float 或 callable(text)->float。返回被检测过的文字列表。"""
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        t = json.loads(req.content)["text"]
        seen.append(t)
        v = soft(t) if callable(soft) else soft
        first = t.split("。")[0] + "。"
        return httpx.Response(200, json={"softmax_confidence": v, "ratio_confidence": v, "labels_ratio": {"0": 1 - v, "1": v, "2": 0},
                                         "segment_labels": [{"text": first, "label": 1, "conf": 0.9, "order": 0, "position": 0}],
                                         "usage": {"total_tokens": 5}})

    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: _REAL_CLIENT(*a, transport=httpx.MockTransport(handler), **kw))
    return seen


@pytest.fixture()
def zq_key(client: TestClient) -> Any:
    assert client.put("/api/settings/zhuque", json={"zhuque_api_key": "sk-test-zhuque-e6"}).status_code == 200
    yield
    client.put("/api/settings/zhuque", json={"zhuque_api_key": "", "zhuque_base_url": "", "zhuque_auto_check": False})


# ================================================================== 排版（纯代码）

def test_format_text_rules() -> None:
    from app.services.typeset import format_text

    raw = '林恩深吸一口气...他说:"走吧",然后转身--没回头。。\n\n\n  苏晚  看着他 。\n速度是3.5米每秒，1,000 块。'
    out, rep = format_text(raw)
    assert out == "林恩深吸一口气……他说：“走吧”，然后转身——没回头。\n\n苏晚看着他。\n\n速度是3.5米每秒，1,000 块。"
    c = rep["changes"]
    assert c["ellipsis"] == 1 and c["dash"] == 1 and c["quotes"] == 1 and c["spaces"] >= 1 and c["punct"] >= 2
    assert format_text(out)[0] == out and not any(format_text(out)[1]["changes"].values())  # 幂等
    out2, _ = format_text(out, {"indent": True, "blank_line": False})
    assert out2.split("\n")[1] == "\u3000\u3000苏晚看着他。"
    long = "他走了很远的路。" * 12 + "“你来了。”她说。" + "风停了。"
    o3, r3 = format_text(long)
    assert r3["long_count"] == 1 and r3["long_paragraphs"][0]["words"] > 70 and o3 == long  # 默认只提示
    o4, r4 = format_text(long, {"split_long": True})
    assert r4["changes"]["split"] >= 1 and all(len(p) <= 80 for p in o4.split("\n\n")) and "“你来了。”" in o4


# ================================================================== 消痕：待确认 → DIFF 采纳 / 一键全部采纳，复检 AI 率

def test_batch_humanize_pending_recheck_and_adopt_all(client: TestClient) -> None:
    bid, ids = _book(client, 3)
    run = _run(client, bid, "humanize", 1, 3)
    assert run["status"] == "done" and run["total"] == 3 and run["op_label"] == "消痕"
    items = run["items"]
    assert [i["number"] for i in items] == [1, 2, 3]
    assert all(i["status"] == "pending" and i["changed"] for i in items), items
    m = items[0]["metrics"]
    # 没配朱雀：复检用本地人味分，前后都有，变化 = 后 - 前
    assert m["ai_before"]["source"] == "local" and m["ai_after"]["source"] == "local"
    assert m["ai_delta"] == round(m["ai_after"]["value"] - m["ai_before"]["value"], 1)
    assert len(m["rounds"]) == 1 and m["rounds"][0]["patches"] >= 1
    sm = run["live_summary"]
    assert sm["counts"]["pending"] == 3 and sm["ai"]["compared"] == 3 and sm["ai"]["avg_before"] is not None
    # 正文还没动（只出对比稿）
    assert client.get(f"/api/chapters/{ids[0]}").json()["content"] == TEXT
    # 单章：带 DIFF 取舍后的正文采纳
    one = client.get(f"/api/books/{bid}/batch/{run['id']}/items/{items[0]['id']}").json()
    assert one["base_content"] == TEXT and one["content"] != TEXT and one["stale"] is False
    partial = one["content"].split("\n\n")[0] + "\n\n" + "\n\n".join(TEXT.split("\n\n")[1:])
    r = client.post(f"/api/books/{bid}/batch/{run['id']}/items/{items[0]['id']}/adopt", json={"content": partial})
    assert r.status_code == 200, r.text
    ch = client.get(f"/api/chapters/{ids[0]}").json()
    assert ch["content"] == partial
    assert client.post(f"/api/books/{bid}/batch/{run['id']}/items/{items[0]['id']}/adopt").status_code == 409  # 已采纳
    # 其余一键全部采纳
    r = client.post(f"/api/books/{bid}/batch/{run['id']}/adopt-all").json()
    assert r["adopted"] == [2, 3] and r["skipped"] == []
    for cid, it in zip(ids[1:], items[1:]):
        full = client.get(f"/api/books/{bid}/batch/{run['id']}/items/{it['id']}").json()
        assert full["status"] == "adopted" and client.get(f"/api/chapters/{cid}").json()["content"] == full["content"]
    # 撤回：旧正文进了历史
    u = client.post(f"/api/chapters/{ids[1]}/undo")
    assert u.status_code == 200 and u.json()["content"].startswith("林恩深吸一口气")


def test_adopt_refuses_when_chapter_changed_and_discard(client: TestClient) -> None:
    bid, ids = _book(client, 2)
    run = _run(client, bid, "humanize", 1, 2)
    it1, it2 = run["items"]
    client.put(f"/api/chapters/{ids[0]}", json={"content": TEXT + "\n\n作者手改了一句。"})
    assert client.get(f"/api/books/{bid}/batch/{run['id']}").json()["items"][0]["stale"] is True
    r = client.post(f"/api/books/{bid}/batch/{run['id']}/items/{it1['id']}/adopt")
    assert r.status_code == 409 and "又改过" in r.json()["detail"]
    allr = client.post(f"/api/books/{bid}/batch/{run['id']}/adopt-all").json()
    assert allr["adopted"] == [2] and allr["skipped"][0]["number"] == 1
    assert client.post(f"/api/books/{bid}/batch/{run['id']}/items/{it1['id']}/adopt", json={"force": True}).status_code == 200
    run2 = _run(client, bid, "format", 1, 2, options={"format": {"indent": True}})
    assert client.post(f"/api/books/{bid}/batch/{run2['id']}/discard-all").json()["count"] == 2
    assert all(i["status"] == "discarded" for i in client.get(f"/api/books/{bid}/batch/{run2['id']}").json()["items"])


# ================================================================== 单章失败不影响其它章，可重试

def test_single_chapter_failure_is_isolated_and_retryable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import writing

    bid, ids = _book(client, 4)
    real = writing.patch_rewrite

    def flaky(content: str, *a: Any, **kw: Any) -> Any:
        if "2千灵石" in content:
            raise RuntimeError("模型渠道超时（测试注入）")
        return real(content, *a, **kw)

    monkeypatch.setattr(writing, "patch_rewrite", flaky)
    run = _run(client, bid, "humanize", 1, 4, concurrency=2)
    by = {i["number"]: i for i in run["items"]}
    assert by[2]["status"] == "failed" and "测试注入" in by[2]["error"] and by[2]["attempts"] == 1
    assert all(by[n]["status"] == "pending" for n in (1, 3, 4))
    assert run["failed"] == 1 and run["live_summary"]["failed"][0]["number"] == 2
    # 不是失败的章不能重试
    assert client.post(f"/api/books/{bid}/batch/{run['id']}/items/{by[1]['id']}/retry").status_code == 409
    monkeypatch.setattr(writing, "patch_rewrite", real)
    r = client.post(f"/api/books/{bid}/batch/{run['id']}/items/{by[2]['id']}/retry")
    assert r.status_code == 200, r.text
    wait_job(client, r.json()["job"])
    after = {i["number"]: i for i in client.get(f"/api/books/{bid}/batch/{run['id']}").json()["items"]}
    assert after[2]["status"] == "pending" and after[2]["attempts"] == 2 and after[2]["error"] == ""
    assert after[1]["status"] == "pending"  # 其他章不受影响
    assert client.post(f"/api/books/{bid}/batch/{run['id']}/retry").status_code == 409  # 没有失败章了


# ================================================================== 暂停 / 续跑 / 中断后续跑

def test_pause_and_resume(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import batch_qa

    bid, ids = _book(client, 5)
    real = batch_qa.process_item
    calls: list[int] = []

    def pausing(item_id: int, engine: Any) -> None:
        calls.append(item_id)
        if len(calls) == 2:  # 处理第 2 章时作者点了暂停
            with batch_qa.session_scope() as s:
                rid = s.get(batch_qa.BatchQaItem, item_id).run_id  # type: ignore[union-attr]
            batch_qa.set_pause(rid, True)
        real(item_id, engine)

    monkeypatch.setattr(batch_qa, "process_item", pausing)
    run = _run(client, bid, "format", 1, 5, options={"format": {"indent": True}})
    assert run["status"] == "paused" and run["processed"] == 2 and run["counts"]["queued"] == 3
    assert "已暂停" in run["message"]
    r = client.post(f"/api/books/{bid}/batch/{run['id']}/resume")
    assert r.status_code == 200, r.text
    wait_job(client, r.json()["job"])
    done = client.get(f"/api/books/{bid}/batch/{run['id']}").json()
    assert done["status"] == "done" and done["processed"] == 5 and done["counts"].get("pending") == 5
    assert len(calls) == 5  # 续跑只处理剩下的 3 章
    assert client.post(f"/api/books/{bid}/batch/{run['id']}/resume").status_code == 409  # 没有剩余


def test_interrupted_job_resumes_from_queue(client: TestClient) -> None:
    from app.jobs.manager import create_job, save_checkpoint
    from app.db import session_scope
    from app.models.tables import Job
    from app.services import batch_qa

    bid, ids = _book(client, 3)
    run = batch_qa.create_run(bid, "format", 1, 3, {})
    job = create_job(batch_qa.KIND, bid, ref=f"batch:{run.id}")
    batch_qa.attach_job(run.id or 0, job.id or 0)
    save_checkpoint(job.id or 0, "item:1/3", {"run_id": run.id}, kind=batch_qa.KIND, book_id=bid)
    with session_scope() as s:  # 模拟服务重启：任务标中断，第 1 章停在处理中
        j = s.get(Job, job.id)
        j.status = "interrupted"  # type: ignore[union-attr]
        s.add(j)
        it = batch_qa._items(s, run.id or 0)[0]  # noqa: SLF001
        it.status = "running"
        s.add(it)
        s.commit()
    info = client.get(f"/api/jobs/{job.id}").json()
    assert info["resumable"] is True
    assert client.get(f"/api/books/{bid}/batch/{run.id}").json()["status"] == "interrupted"
    r = client.post(f"/api/jobs/{job.id}/resume")
    assert r.status_code == 200, r.text
    wait_job(client, r.json())
    d = client.get(f"/api/books/{bid}/batch/{run.id}").json()
    assert d["status"] == "done" and d["processed"] == 3


# ================================================================== AI 率检测（朱雀 / 本地）+ 报告导出

def test_batch_aigc_local_and_validation(client: TestClient) -> None:
    bid, ids = _book(client, 2)
    run = _run(client, bid, "aigc", 1, 2)
    assert all(i["status"] == "done" and i["metrics"]["ai_after"]["source"] == "local" for i in run["items"])
    # 参数：op 不认识 422；区间里没正文 409；指定朱雀但没密钥 409；不限章数
    assert client.post(f"/api/books/{bid}/batch", json={"op": "nope", "from": 1, "to": 2}).status_code == 422
    assert client.post(f"/api/books/{bid}/batch", json={"op": "format", "from": 50, "to": 60}).status_code == 409
    r = client.post(f"/api/books/{bid}/batch", json={"op": "aigc", "from": 1, "to": 2, "options": {"aigc_engine": "zhuque"}})
    assert r.status_code == 409 and "朱雀" in r.json()["detail"]
    assert client.post(f"/api/books/{bid}/batch", json={"op": "format", "from": 1, "to": 2, "concurrency": 9}).status_code == 422
    bid2, _ = _book(client, 25, title="长书")
    run = _run(client, bid2, "format", 1, 25, concurrency=4)
    assert run["total"] == 25 and run["processed"] == 25
    lst = client.get(f"/api/books/{bid2}/batch").json()
    assert lst[0]["id"] == run["id"] and lst[0]["op"] == "format"


def test_batch_aigc_zhuque_history_and_report(client: TestClient, zq_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    bid, ids = _book(client, 2)
    _mock_zhuque(monkeypatch, 0.9)
    run = _run(client, bid, "aigc", 1, 2)
    it = run["items"][0]
    assert it["status"] == "done" and it["metrics"]["ai_after"]["source"] == "zhuque" and it["metrics"]["ai_after"]["value"] == 90.0
    assert it["metrics"]["ai_before"] is None
    ch = client.get(f"/api/chapters/{ids[0]}").json()
    assert ch["aigc"]["softmax"] == 0.9 and ch["aigc"]["stale"] is False
    # 第二次检测：「前」= 上一次的结果
    _mock_zhuque(monkeypatch, 0.4)
    run2 = _run(client, bid, "aigc", 1, 1)
    m = run2["items"][0]["metrics"]
    assert m["ai_before"]["value"] == 90.0 and m["ai_after"]["value"] == 40.0 and m["ai_delta"] == -50.0
    hist = client.get(f"/api/chapters/{ids[0]}/aigc/history").json()
    assert [round(h["softmax"], 2) for h in hist] == [0.9, 0.4] and hist[-1]["source"] == "batch" and hist[-1]["current"]
    # HTML 报告：自包含，带高亮、历次检测、打印按钮；print=1 自动弹打印；download 带附件头
    r = client.get(f"/api/chapters/{ids[0]}/aigc/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    assert "<mark class=\"ai\"" in page and "历次检测" in page and "40%" in page and "window.print()" in page
    assert "<link" not in page and "src=\"http" not in page  # 不引外部资源
    assert "申报" not in page
    assert "setTimeout" in client.get(f"/api/chapters/{ids[0]}/aigc/report?print=1").text
    d = client.get(f"/api/chapters/{ids[0]}/aigc/report?download=1&index=0")
    assert "attachment" in d.headers["content-disposition"] and "90%" in d.text
    j = client.get(f"/api/chapters/{ids[0]}/aigc/report?format=json&index=0").json()
    assert j["index"] == 0 and j["result"]["softmax"] == 0.9 and j["text"] == TEXT
    assert client.get(f"/api/chapters/{ids[0]}/aigc/report?index=5").status_code == 404
    assert client.get(f"/api/chapters/{ids[1]}/aigc/history").json()[0]["source"] == "batch"
    # 批量报告
    br = client.get(f"/api/books/{bid}/batch/{run2['id']}/report")
    assert br.status_code == 200 and "第1章" in br.text and "-50.0" in br.text
    assert client.get(f"/api/books/{bid}/batch/{run2['id']}/report?format=json").json()["items"][0]["number"] == 1


def test_rewrite_recheck_with_zhuque_target_rounds(client: TestClient, zq_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    bid, ids = _book(client, 1)
    seen = _mock_zhuque(monkeypatch, lambda t: 0.95 if t == TEXT else 0.7)
    run = _run(client, bid, "polish", 1, 1, options={"aigc_target": 50, "max_rounds": 2})
    it = run["items"][0]
    m = it["metrics"]
    assert it["status"] == "pending"
    assert m["ai_before"]["value"] == 95.0 and m["ai_before"]["source"] == "zhuque"
    assert len(m["rounds"]) == 2 and m["reached_target"] is False  # 一直高于 50：跑满 2 轮
    assert m["ai_after"]["value"] == 70.0 and m["ai_delta"] == -25.0
    assert "result" not in m["ai_after"]  # 对外不带 segments
    assert len(seen) == 3
    client.post(f"/api/books/{bid}/batch/{run['id']}/items/{it['id']}/adopt")
    ch = client.get(f"/api/chapters/{ids[0]}").json()
    assert ch["aigc"]["softmax"] == 0.7 and ch["aigc"]["stale"] is False  # 复检结果直接成为章节 AI 率
    assert client.get(f"/api/chapters/{ids[0]}/aigc/history").json()[-1]["source"] == "batch"
    # 章节已有对得上的检测结果时，「前」复用、不再花朱雀额度
    seen.clear()
    run2 = _run(client, bid, "humanize", 1, 1, options={"recheck": True})
    assert run2["items"][0]["metrics"]["ai_before"]["value"] == 70.0
    assert len(seen) == (1 if run2["items"][0]["status"] == "pending" else 0)


# ================================================================== 改章名 / 审稿 / 排版 / 语感

def test_titles_review_format_polish(client: TestClient) -> None:
    bid, ids = _book(client, 2)
    run = _run(client, bid, "titles", 1, 2)
    it = run["items"][0]
    assert it["status"] == "pending" and it["base_title"] == "第1章旧标题" and it["title"] and it["title"] != it["base_title"]
    cands = it["metrics"]["candidates"]
    assert len(cands) == 3 and not any(c.startswith("第") and "章" in c[:4] for c in cands)
    r = client.post(f"/api/books/{bid}/batch/{run['id']}/items/{it['id']}/adopt", json={"title": "《" + cands[1] + "》"})
    assert r.status_code == 200 and r.json()["title"] == cands[1]
    assert client.get(f"/api/chapters/{ids[0]}").json()["title"] == cands[1]
    assert client.post(f"/api/chapters/{ids[0]}/undo").json()["title"] == "第1章旧标题"

    rv = _run(client, bid, "review", 1, 2)
    assert all(i["status"] == "done" and i["metrics"]["review"]["overall"] is not None for i in rv["items"])
    assert rv["live_summary"]["review"]["count"] == 2
    assert client.get(f"/api/chapters/{ids[1]}").json()["review"] is not None
    rvf = _run(client, bid, "review", 1, 1, options={"fix": True})
    assert rvf["items"][0]["status"] in ("pending", "done", "unchanged")

    fm = _run(client, bid, "format", 1, 2)
    assert all(i["status"] == "unchanged" for i in fm["items"])  # 已经规范
    fm2 = _run(client, bid, "format", 1, 1, options={"format": {"indent": True}})
    assert fm2["items"][0]["status"] == "pending" and fm2["items"][0]["metrics"]["format"]["options"]["indent"] is True

    pv = _run(client, bid, "polish", 2, 2, options={"recheck": False})
    p = pv["items"][0]
    assert p["status"] == "pending" and p["metrics"]["ai_before"] is None and "checks" in p["metrics"]["rounds"][0]
    assert client.delete(f"/api/books/{bid}/batch/{pv['id']}").json()["ok"] is True
    assert client.get(f"/api/books/{bid}/batch/{pv['id']}").status_code == 404


def test_auto_adopt_option(client: TestClient) -> None:
    bid, ids = _book(client, 1)
    run = _run(client, bid, "format", 1, 1, options={"auto_adopt": True, "format": {"indent": True}})
    assert run["items"][0]["status"] == "adopted"
    assert client.get(f"/api/chapters/{ids[0]}").json()["content"].startswith("\u3000\u3000")


# ================================================================== 独立检测页：历史报告

def test_detect_page_report_history(client: TestClient, zq_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_zhuque(monkeypatch, 0.6)
    j = client.post("/api/detect/aigc", json={"text": TEXT}).json()
    res = wait_job(client, j)["result"]
    rid = res["report_id"]
    lst = client.get("/api/aigc/reports").json()
    assert lst[0]["id"] == rid and lst[0]["softmax"] == 0.6 and "text" not in lst[0]
    full = client.get(f"/api/aigc/reports/{rid}").json()
    assert full["text"] == TEXT and full["result"]["level"] == "mid"
    page = client.get(f"/api/aigc/reports/{rid}/export").text
    assert "朱雀 AI 检测报告" in page and "<mark" in page and "60%" in page
    assert client.delete(f"/api/aigc/reports/{rid}").json()["ok"]
    assert client.get(f"/api/aigc/reports/{rid}").status_code == 404
    time.sleep(0)
