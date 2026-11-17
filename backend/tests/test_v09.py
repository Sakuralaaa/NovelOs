"""v0.9：新书榜、风向标日报、平台风格档、审稿补丁、书测、后两章章纲、版本号。"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import wait_job


class _Ctx:
    job_id = 0
    book_id = None

    def progress(self, *a: Any, **k: Any) -> None:
        pass


def _item(bid: str, title: str, rank: int, board: str = "read", gender: str = "male", cat: str = "都市脑洞", **kw: Any) -> dict[str, Any]:
    return {"book_id_ext": bid, "title": title, "author": "", "category": cat, "rank": rank, "rank_diff": kw.get("rank_diff", 0),
            "read_count": kw.get("read_count", 1000 * (50 - rank)), "word_count": 1, "abstract": kw.get("abstract", "简介" * 100),
            "tags": [cat, "连载"], "gender": gender, "board": board}


# ================================================================== 1. 新书榜

def test_parse_board_marks_board() -> None:
    from app.radar import fanqie_web

    payload = {"code": 0, "data": {"book_list": [{"bookId": "1", "bookName": "书", "currentPos": "1"}]}}
    assert fanqie_web.parse_board(payload, "male", "都市", "new")[0]["board"] == "new"
    assert fanqie_web.parse_board(payload, "male", "都市")[0]["board"] == "read"
    assert fanqie_web.BOARD_MOLD == {"read": 2, "new": 1}


def test_fetch_rank_lists_requests_both_boards(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.radar import fanqie_web

    seen: list[dict[str, list[str]]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/rank/category/list" not in str(req.url):
            return httpx.Response(200, text="<html></html>")  # 题材列表页解析失败 → 内置题材表
        q = parse_qs(urlparse(str(req.url)).query)
        seen.append(q)
        mold = q["rankMold"][0]
        return httpx.Response(200, json={"code": 0, "data": {"rankVersion": "v9", "book_list": [
            {"bookId": f"{q['category_id'][0]}-{mold}", "bookName": f"书{mold}", "currentPos": "1"}]}})

    real = httpx.Client
    monkeypatch.setattr(fanqie_web.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(fanqie_web.time, "sleep", lambda s: None)
    items, version = fanqie_web.fetch_rank_lists(per_board=10)
    n_cat = sum(len(v) for v in fanqie_web.BOARDS.values())
    assert version == "v9"
    assert {q["rankMold"][0] for q in seen} == {"1", "2"} and len(seen) == 2 * n_cat
    assert sum(1 for i in items if i["board"] == "new") == n_cat == sum(1 for i in items if i["board"] == "read")
    only = fanqie_web.fetch_rank_lists(per_board=10, boards=["read"])[0]
    assert {i["board"] for i in only} == {"read"}


def test_refresh_new_board_and_old_data_compat(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import session_scope
    from app.models.tables import RadarSnapshot, RankItem
    from app.radar import service

    # 旧版本留下的快照：只有阅读榜，且 board 为空串（模拟迁移前写入）
    with session_scope() as s:
        old = RadarSnapshot(source="web", items_count=2, version="v-old")
        s.add(old)
        s.flush()
        for it in (_item("a", "旧书甲", 1), _item("b", "旧书乙", 2)):
            s.add(RankItem(snapshot_id=old.id or 0, **{**it, "board": ""}))
        s.commit()
    with session_scope() as s:
        assert service.snapshot_boards(s, old.id or 0) == {"read"}

    calls = {"boards": [["read"]]}

    def fake(per_board: Any = None, progress: Any = None, boards: Any = None) -> tuple[list[dict[str, Any]], str]:
        rows = [_item("a", "旧书甲", 2), _item("b", "旧书乙", 1)]  # 乙从 2 升到 1
        if "new" in calls["boards"][-1]:
            rows += [_item("n1", "新书一号", 1, "new"), _item("n2", "新书二号", 2, "new")]
        return rows, "v-old"

    monkeypatch.setattr(service.fanqie_web, "fetch_rank_lists", fake)
    monkeypatch.setattr(service, "get_config", lambda s: {"enabled": True, "daily_hour": 8, "auto_report": False})
    r1 = service.refresh(_Ctx())
    assert r1.get("unchanged") and r1["snapshot_id"] == old.id  # 同版本、榜单类型没变多 → 不新建
    calls["boards"].append(["read", "new"])
    r2 = service.refresh(_Ctx())
    assert not r2.get("unchanged") and r2["boards"] == {"read": 2, "new": 2}  # 同版本但多了新书榜 → 新快照

    latest = client.get("/api/radar/latest", params={"board": "new"}).json()
    assert {i["board"] for i in latest["items"]} == {"new"} and latest["boards"] == ["new", "read"]
    assert len(client.get("/api/radar/latest", params={"board": "read"}).json()["items"]) == 2
    assert client.get("/api/radar/latest", params={"board": "x"}).status_code == 422
    # 趋势：旧快照 board="" 视为 read，和新快照的 read 对得上 → 乙上升；新书榜在上一份里没有 → 新上榜计 rising
    read_tr = client.get("/api/radar/trends", params={"board": "read"}).json()
    assert read_tr[0]["books"] == 2 and read_tr[0]["rising"] == 1
    new_tr = client.get("/api/radar/trends", params={"board": "new"}).json()
    assert new_tr[0]["books"] == 2 and new_tr[0]["rising"] == 2
    assert client.get("/api/radar/trends").json()[0]["books"] == 4


def test_mock_refresh_contains_new_board() -> None:
    from app.radar.mock_data import mock_items_50, mock_new_items

    new = mock_new_items()
    assert new and all(i["board"] == "new" and i["word_count"] < 300_000 for i in new)
    assert all(i["board"] == "read" for i in mock_items_50())


# ================================================================== 2. 风向标日报

def test_build_input_marks_new_and_risers() -> None:
    from app.radar import report

    prev = [_item("a", "甲", 3), _item("b", "乙", 1), _item("c", "丙", 2, "new")]
    cur = [_item("a", "甲", 1), _item("b", "乙", 2), _item("c", "丙", 1, "new"), _item("d", "丁", 2, "new"),
           _item("f", "女频书", 1, gender="female", cat="现言脑洞")]
    inp = report.build_input(cur, prev, "overall", top_n=5)
    assert inp["board_names"] == ["男频阅读", "男频新书", "女频阅读", "女频新书"]
    assert [i["title"] for i in inp["movers"]["男频新书"]["new"]] == ["丁"]
    assert [(i["title"], i["rank_change"]) for i in inp["movers"]["男频阅读"]["up"]] == [("甲", 2)]
    assert "《甲》" in inp["boards_text"] and "（↑2）" in inp["boards_text"] and "新上榜" in inp["boards_text"]
    assert "（本期没有数据）" in inp["boards_text"]  # 女频新书为空
    line = report.item_line(cur[0])
    assert line.count("简介") <= 60 and "在读" in line  # 简介只取前 120 字
    cat = report.build_input(cur, prev, "category:female:现言脑洞")
    assert cat["board_names"] == ["女频阅读", "女频新书"] and cat["titles"] == ["女频书"]


def test_normalize_report_drops_fabricated_examples() -> None:
    from app.radar import report

    raw = {
        "hot_words": [{"word": "读心", "why": "w", "examples": ["《真书》", "假书"]}, {"word": "凭空", "examples": ["假书"]}, "裸字符串"],
        "boards": [{"board": "男频阅读榜", "overview": "o", "idea_hooks": [{"title": "《真书》", "pitch": "重名"}, "新书｜一句话梗"]},
                   {"board": "不存在的榜"}, {"board": "男频阅读", "overview": "重复"}],
        "open_directions": ["方向一", "", 3],
        "title_patterns": [{"pattern": "《[A]，我[B]》", "examples": "真书、假书"}, {"pattern": "《凭空》", "examples": []}],
        "pitfalls": ["切忌前期被反派按在地上摩擦超过三章", "题材多元化，未来可期"],
    }
    rep, warns = report.normalize_report(raw, ["真书", "另一本"], ["男频阅读", "男频新书"])
    assert [h["word"] for h in rep["hot_words"]] == ["读心"] and rep["hot_words"][0]["examples"] == ["真书"]
    assert [b["board"] for b in rep["boards"]] == ["男频阅读"] and rep["boards"][0]["overview"] == "o"
    assert rep["boards"][0]["idea_hooks"] == [{"title": "新书", "pitch": "一句话梗"}]
    assert rep["open_directions"] == ["方向一"]
    assert rep["title_patterns"] == [{"pattern": "《[A]，我[B]》", "examples": ["真书"]}]
    joined = "\n".join(warns)
    assert "凭空" in joined and "男频新书" in joined and "套话" in joined and "重名" in joined
    with pytest.raises(report.ReportError):
        report.normalize_report({"boards": []}, ["真书"], ["男频阅读"])
    with pytest.raises(report.ReportError):
        report.parse_scope("category:alien:x")


def test_report_api_flow(client: TestClient) -> None:
    from app.db import session_scope
    from app.radar import report

    wait_job(client, client.post("/api/radar/refresh").json())
    snap = client.get("/api/radar/latest").json()["snapshot"]
    assert client.get("/api/radar/report", params={"scope": "category:male:没有这个题材"}).status_code == 404
    assert client.post("/api/radar/report", json={"scope": "category:male:没有这个题材"}).status_code == 404
    assert client.post("/api/radar/report", json={"scope": "bad"}).status_code == 400
    assert client.get("/api/radar/report", params={"scope": "bad"}).status_code == 400

    job = client.post("/api/radar/report", json={"scope": "overall"}).json()
    assert job["job_id"] == job["id"] and job["kind"] == "radar_report" and job["ref"] == "trend_report:overall"
    res = wait_job(client, job)["result"]
    rep = res["report"]
    assert res["snapshot_id"] == snap["id"] and res["scope"] == "overall" and res["model"] == "mock" and res["stale"] is False
    with session_scope() as s:
        from app.radar import service as radar
        titles = {i.title for i in radar.snapshot_items(s, snap["id"], dedupe=False)}
    assert rep["hot_words"] and all(set(h["examples"]) <= titles for h in rep["hot_words"])
    assert all(h["word"] != "凭空热词" for h in rep["hot_words"])  # mock 故意给的假例子被删
    assert all(set(p["examples"]) <= titles for p in rep["title_patterns"]) and rep["title_patterns"]
    assert {b["board"] for b in rep["boards"]} <= set(report.BOARD_NAMES) and rep["boards"]
    assert all({"overview", "reader_mood", "opportunity", "writing_tips", "idea_hooks"} <= set(b) for b in rep["boards"])
    assert rep["open_directions"] and rep["pitfalls"] and rep["inputs"]["books"] > 0
    got = client.get("/api/radar/report").json()
    assert got["id"] == res["id"] and got["report"] == rep

    cat = next(i for i in client.get("/api/radar/latest", params={"gender": "female"}).json()["items"])
    scope = f"category:female:{cat['category']}"
    r2 = wait_job(client, client.post("/api/radar/report", json={"scope": scope, "top_n": 5}).json())["result"]
    assert {b["board"] for b in r2["report"]["boards"]} <= {"女频阅读", "女频新书"}
    hist = client.get("/api/radar/reports", params={"limit": 5}).json()
    assert hist[0]["id"] == r2["id"] and "report" not in hist[0] and isinstance(hist[0]["hot_words"], list)
    assert "report" in client.get("/api/radar/reports", params={"full": True}).json()[0]
    assert [h["scope"] for h in client.get("/api/radar/reports", params={"scope": "overall"}).json()] == ["overall"] * len(
        client.get("/api/radar/reports", params={"scope": "overall"}).json())


def test_auto_report_after_refresh(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.radar import service

    cfg = client.put("/api/radar/config", json={"enabled": False, "daily_hour": 8, "auto_report": True}).json()
    assert cfg == {"enabled": False, "daily_hour": 8, "auto_report": True}
    assert client.put("/api/radar/config", json={"enabled": False, "daily_hour": 9}).json()["auto_report"] is True  # 不传不改
    monkeypatch.setattr(service.fanqie_web, "fetch_rank_lists",
                        lambda **k: ([_item("z1", "自动日报书", 1), _item("z2", "自动日报新书", 1, "new")], "v-auto"))
    monkeypatch.setattr(service, "get_config", lambda s: {"enabled": True, "daily_hour": 8, "auto_report": True})
    r = service.refresh(_Ctx())
    assert r.get("report_job_id")
    j = wait_job(client, client.get(f"/api/jobs/{r['report_job_id']}").json())
    assert j["result"]["snapshot_id"] == r["snapshot_id"]
    again = service.refresh(_Ctx())  # 同版本 unchanged，且这份快照已有日报 → 不再提交
    assert again.get("unchanged") and "report_job_id" not in again
    client.put("/api/radar/config", json={"enabled": False, "daily_hour": 8, "auto_report": False})


# ================================================================== 3. 平台风格档

def test_book_platform_style_create_patch(client: TestClient) -> None:
    b = client.post("/api/books", json={"title": "起点书", "platform_style": "qidian"}).json()
    assert b["platform_style"] == "qidian" and b["has_book_test"] is False
    assert client.post("/api/books", json={"title": "默认书"}).json()["platform_style"] == "fanqie"
    assert client.patch(f"/api/books/{b['id']}", json={"platform_style": "generic"}).json()["platform_style"] == "generic"
    assert client.patch(f"/api/books/{b['id']}", json={"platform_style": "jjwxc"}).status_code == 422


def test_platform_sections_injected_by_profile() -> None:
    from app.skills.loader import system_prompt

    fq = system_prompt("writing_scene", platform="fanqie")
    qd = system_prompt("writing_scene", platform="qidian")
    gen = system_prompt("writing_scene")
    assert "单段 1–3 行" in fq and "金手指弹出异常提示" in fq and "配角有智商" not in fq
    assert "配角有智商" in qd and "单段 1–3 行" not in qd
    assert "单段 1–3 行" not in gen and "配角有智商" not in gen and "platform:" not in gen
    assert "去 AI 腔" in system_prompt("humanize") and "动词先行" in system_prompt("humanize")
    assert "过朱雀" not in fq + system_prompt("humanize") and "检测" not in system_prompt("humanize").split("v0.9 去 AI 腔")[1]


def test_lint_platform_thresholds() -> None:
    from app.config import get_settings
    from app.lint.humanlint import lint_chapter

    th = get_settings().lint
    long_para = "他把门推开，屋里的灯还亮着，桌上的茶已经凉透了，杯沿上一圈茶垢，像是有人在这里坐了一整夜没合眼，窗外的雨也一直没有停过，滴答滴答地敲着铁皮雨棚。"
    waterfall = "\n\n".join(["他停下。", "门开了。", "风灌进来。", "灯晃了晃。", "没人说话。", "他抬头。"])
    text = long_para + "\n\n" + waterfall + "\n\n“走。”他说。"
    fq = lint_chapter(text, th, platform="fanqie")
    gen = lint_chapter(text, th)
    assert fq.platform == "fanqie" and gen.platform == "generic"
    # v0.9.4 校准：番茄档长段 70→100 字，且要成片（≥3 段、占比 ≥10%）才算问题；单段 73 字不再报
    assert fq.long_paragraphs == [] and gen.long_paragraphs == []
    assert not any(t["kind"] == "长段" for t in fq.fix_targets)
    assert any("单句成段" in w for w in gen.warnings) and not any("单句成段" in w for w in fq.warnings)
    long3 = "\n\n".join([long_para + long_para[:40]] * 3)
    text2 = long3 + "\n\n" + waterfall + "\n\n“走。”他说。"
    fq2, gen2 = lint_chapter(text2, th, platform="fanqie"), lint_chapter(text2, th)
    assert fq2.long_paragraphs == [0, 1, 2] and gen2.long_paragraphs == []
    assert any(t["kind"] == "长段" for t in fq2.fix_targets) and not any(t["kind"] == "长段" for t in gen2.fix_targets)
    assert any("100 字" in w for w in fq2.warnings) and fq2.to_dict()["long_paragraphs"] == 3
    # 群众反应镜头：番茄档上限放宽到 5
    crowd = "\n\n".join(["围观的人群里有人嘀咕了一句。", "他往前走。", "街坊们面面相觑。", "他继续走。", "人群往后退了两步。", "他没停。",
                         "众人愣住了。", "他到了门口。"])
    assert any("群众" in w for w in lint_chapter(crowd, th).warnings)
    assert not any("群众" in w for w in lint_chapter(crowd, th, platform="fanqie").warnings)
    # 书面成语只查叙述
    hits = {h["word"] for h in lint_chapter("这简直匪夷所思。“不可思议！”他说。", th).banned_hits}
    assert "匪夷所思" in hits and "不可思议" not in hits


# ================================================================== 4. 审稿补丁

CONTENT = "叶承推开门。\n\n韩铎把合同拍在桌上，经过一番周旋，两人各退一步。\n\n他的修为没有上限了。"


def test_validate_and_apply_patches() -> None:
    from app.services.review import apply_patches, validate_patches

    issues = [{"severity": "mid", "dimension": "pacing", "quote": "经过一番周旋，两人各退一步。", "comment": ""},
              {"severity": "low", "dimension": "hook", "quote": "叶承推开门。", "comment": ""}]
    raw = {"patches": [
        {"original": "经过一番周旋，两人各退一步。", "improved": "两人对着合同磨了半盏茶。", "reason": "概述", "issue_ref": 5},
        {"original": "他的修为没有上限了。", "improved": "他的修为到顶了。", "issue_ref": "没有上限"},
        {"original": "原文里没有", "improved": "x"},
        {"original": "叶承推开门。", "improved": "叶承推开门。"},
        "junk",
    ]}
    pats, dropped = validate_patches(raw, CONTENT, issues, {5: 0})
    assert dropped == 3 and [p["index"] for p in pats] == [0, 1]
    assert pats[0]["issue_ref"] == 0 and pats[0]["severity"] == "mid" and pats[0]["applied"] is False
    assert pats[1]["issue_ref"] is None  # 引文对不上任何问题
    new, applied, skipped = apply_patches(CONTENT, pats + [{"original": "不存在的句子", "improved": "y"}], [0, 0, 2, 9])
    assert "磨了半盏茶" in new and "经过一番" not in new
    assert [a["index"] for a in applied] == [0]
    assert {s["index"] for s in skipped} == {2, 9} and len(skipped) == 2  # 重复下标只算一次


def test_run_review_returns_patches_with_issue_refs() -> None:
    from app.llm.gateway import get_gateway
    from app.services.review import run_review

    review, _ = run_review(get_gateway(), CONTENT, 5, "{}", "叶承", [], {})
    pats = review["patches"]
    assert pats and all(p["original"] in CONTENT for p in pats)
    assert all(p["original"] != "这句话不在正文里。" for p in pats)
    for p in pats:
        assert p["issue_ref"] is not None
        assert review["issues"][p["issue_ref"]]["quote"] == p["original"]


def _write_book(client: TestClient, platform: str = "fanqie") -> int:
    b = client.post("/api/books", json={"title": "补丁测试书", "genre": "都市高武", "gender": "male", "platform_style": platform,
                                         "premise": "主角靠一本旧账翻身。"}).json()
    bid = b["id"]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    return bid


def test_write_flow_auto_applies_patches_and_manual_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import review as review_svc
    from app.services import writing

    # 让最后一轮审稿一定带一个 mid 问题和能匹配的补丁：取正文第一段的第一句
    real = review_svc.run_review

    def fake_run_review(gw: Any, content: str, *a: Any, **k: Any) -> Any:
        rv, dropped = real(gw, content, *a, **k)
        first = content.split("\n")[0]
        q = first[: first.find("。") + 1] if "。" in first else first[:20]
        rv["issues"].append({"severity": "mid", "dimension": "pacing", "quote": q, "comment": "测试"})
        rv["patches"] = [{"index": 0, "original": q, "improved": q + "（补丁）", "reason": "测试", "issue_ref": len(rv["issues"]) - 1,
                          "severity": "mid", "applied": False},
                         {"index": 1, "original": "根本不在正文里的句子", "improved": "x", "reason": "", "issue_ref": len(rv["issues"]) - 1,
                          "severity": "mid", "applied": False}]
        return rv, dropped

    monkeypatch.setattr(writing, "run_review", fake_run_review)
    bid = _write_book(client)
    r = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
    assert r["review_patches"]["applied"] == [0] and r["review_patches"]["skipped"][0]["index"] == 1
    ch = client.get(f"/api/chapters/{r['chapter_id']}").json()
    assert "（补丁）" in ch["content"] and ch["last_history_label"] == "审稿补丁前"
    assert ch["review"]["patches"][0]["applied"] is True and ch["review"]["patch_log"][-1]["applied"] == [0]
    assert any("审稿补丁" in w for w in ch["changes"]["warnings"])
    assert ch["lint"]["platform"] == "fanqie"

    # 手动接口：已应用的跳过；新审稿后的补丁按下标应用，可撤回
    out = client.post(f"/api/chapters/{r['chapter_id']}/review/patches/apply", json={"indices": [0]}).json()
    assert out["applied"] == [] and out["skipped"][0]["reason"] == "已经应用过"
    wait_job(client, client.post(f"/api/chapters/{r['chapter_id']}/review").json())
    ch = client.get(f"/api/chapters/{r['chapter_id']}").json()
    idx = ch["review"]["patches"][0]["index"]
    before = ch["content"]
    out = client.post(f"/api/chapters/{r['chapter_id']}/review/patches/apply", json={"indices": [idx]}).json()
    assert [a["index"] for a in out["applied"]] == [idx] and out["chapter"]["content"] != before
    assert out["chapter"]["review"]["patches"][idx]["applied"] is True
    assert client.post(f"/api/chapters/{r['chapter_id']}/undo").json()["content"] == before
    assert client.post(f"/api/chapters/{r['chapter_id']}/review/patches/apply", json={"indices": []}).status_code == 422
    if not r.get("committed"):
        wait_job(client, client.post(f"/api/chapters/{r['chapter_id']}/commit").json())


# ================================================================== 5. 书测

def test_normalize_variants() -> None:
    from app.services.book_test import normalize_variants

    raw = {"variants": [
        {"style": "D 起点正剧", "title": "《渊天》", "subtitle": "一" * 30, "hook": "h", "cover_prompt": "远山"},
        {"style": "方案A", "title": "让你看店", "subtitle": "s", "hook": "h", "cover_prompt": "金光，竖版 3:4"},
        {"style": "随便", "title": "第三个", "subtitle": "s", "hook": "h", "cover_prompt": ""},
        {"style": "C", "title": ""},
    ]}
    vs, warns = normalize_variants(raw)
    assert [v["style"] for v in vs] == ["A 番茄情绪爽感", "B 悬疑规则脑洞", "D 起点正剧"]
    assert vs[2]["title"] == "渊天" and len(vs[2]["subtitle"]) == 20 and vs[2]["cover_prompt"].endswith("竖版 3:4")
    assert vs[0]["cover_prompt"].count("3:4") == 1
    assert any("C" in w for w in warns) and any("截断" in w for w in warns)
    with pytest.raises(ValueError):
        normalize_variants({"variants": []})


def test_book_test_api_and_adopt(client: TestClient) -> None:
    bid = _write_book(client)
    assert client.get(f"/api/books/{bid}/book-test").status_code == 404
    res = wait_job(client, client.post(f"/api/books/{bid}/book-test").json())["result"]
    vs = res["variants"]
    assert [v["style"][0] for v in vs] == ["A", "B", "C", "D"]
    assert all(len(v["subtitle"]) <= 20 and "3:4" in v["cover_prompt"] and v["title"] and v["hook"] for v in vs)
    assert client.get(f"/api/books/{bid}/book-test").json()["variants"] == vs
    old = client.get(f"/api/books/{bid}").json()
    out = client.post(f"/api/books/{bid}/book-test/adopt", json={"index": 2, "fields": ["title", "subtitle", "hook"]}).json()
    assert out["book"]["title"] == vs[2]["title"] and out["book"]["tagline"] == vs[2]["subtitle"]
    assert out["package"]["blurb"] == vs[2]["hook"] and out["adopted"]["index"] == 2 and out["book"]["has_book_test"]
    assert client.get(f"/api/books/{bid}/book-test").json()["adopted"] == 2
    assert client.post(f"/api/books/{bid}/undo").json()["title"] == old["title"]  # 走作品信息版本栈，可撤回
    assert client.post(f"/api/books/{bid}/book-test/adopt", json={"index": 7}).status_code == 404


def test_agent_book_test_tool(client: TestClient) -> None:
    from app.services import agent_proposals as props
    from app.services import agent_tools

    bid = _write_book(client)
    client.patch(f"/api/books/{bid}", json={"agent_auto_apply": True})
    from app.db import session_scope
    from app.services.agent import create_session

    with session_scope() as s:
        sid = create_session(s, bid).id or 0
    tc = agent_tools.ToolCtx(book_id=bid, session_id=sid)
    r = agent_tools.dispatch(tc, "book_test", {})
    assert r.ok and len(r.data["variants"]) == 4 and r.proposal_ids
    pid = r.proposal_ids[0]
    p = props.proposal_out(props._set(pid))
    assert p["status"] == "pending" and p["needs_review"]  # 自动采纳打开也不替作者选
    title_before = client.get(f"/api/books/{bid}").json()["title"]
    out = props.apply(pid, {"index": 3})
    assert client.get(f"/api/books/{bid}").json()["title"] == r.data["variants"][3]["title"]
    assert out["proposal"]["status"] == "applied" and out["proposal"]["revertible"]
    props.revert(pid)
    assert client.get(f"/api/books/{bid}").json()["title"] == title_before
    assert "book_test" in {t["name"] for t in agent_tools.catalog()}


# ================================================================== 6. 后两章章纲

def test_context_includes_next_two_outlines(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import OutlineNode
    from app.services import common
    from app.services.context import NEXT_OUTLINES_BUDGET, build_context_pack, next_outlines_block

    bid = _write_book(client)
    with session_scope() as s:
        nodes = sorted([n for n in common.outline_nodes(s, bid) if n.level == "chapter"], key=lambda n: n.order)
        assert len(nodes) >= 3
        n2 = s.get(OutlineNode, nodes[1].id)
        assert n2 is not None
        n2.beats = {**(n2.beats or {}), "foreshadow": [{"action": "plant", "desc": "井底的铜铃"}]}
        n2.summary = "长" * 500
        s.add(n2)
        s.commit()
        block = next_outlines_block(s, bid, 1)
        assert f"第{nodes[1].order}章" in block and f"第{nodes[2].order}章" in block
        assert f"第{nodes[3].order}章" not in block if len(nodes) > 3 else True
        assert "不得提前写出" in block and len(block) < NEXT_OUTLINES_BUDGET + 200
        book = common.get_book(s, bid)
        pack = build_context_pack(s, book, nodes[0])
        assert "后两章章纲" in pack.suffix
        assert next_outlines_block(s, bid, nodes[-1].order) == ""


# ================================================================== 7. 版本号

def test_version_090(client: TestClient) -> None:
    from pathlib import Path

    assert client.get("/api/health").json()["version"].startswith(("0.9.", "0.10.", "0.11.", "0.12.", "0.13."))  # v0.9.1 起版本号由 test_v091 精确校验
    root = Path(__file__).resolve().parents[2]
    assert "## v0.9.0" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
