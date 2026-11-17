"""v0.9.2：风向标日报 schema 升级与按榜 scope、种子立项、一键整理、多本熔炉、仿写立项 TXT、版本号。

全部用 mock LLM 与 monkeypatch 的抓榜函数；不做真实抓取、不真实调用模型。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import wait_job

ROOT = Path(__file__).resolve().parents[2]


def _item(bid: str, title: str, rank: int, board: str = "read", gender: str = "male", cat: str = "都市脑洞",
          abstract: str = "", read: int = 1000) -> dict[str, Any]:
    return {"book_id_ext": bid, "title": title, "author": "", "category": cat, "tags": [cat], "gender": gender,
            "abstract": abstract or f"{title}的简介", "read_count": read, "rank": rank, "rank_diff": 0, "word_count": 1000,
            "board": board}


def _add_book(bid: str, title: str, abstract: str, gender: str = "male", cat: str = "都市脑洞") -> None:
    from app.db import session_scope
    from app.models.tables import RadarSnapshot, RankItem

    with session_scope() as s:
        snap = RadarSnapshot(source="web", items_count=1, version=f"v092-{bid}-{time.time()}")
        s.add(snap)
        s.flush()
        s.add(RankItem(snapshot_id=snap.id or 0, book_id_ext=bid, title=title, category=cat, abstract=abstract, tags=[cat, "连载"],
                       gender=gender, rank=1, read_count=5000, board="read"))
        s.commit()


@pytest.fixture()
def fresh_snapshot(client: TestClient) -> dict[str, Any]:
    """刷新一份示例快照（mock 数据，最新快照）。"""
    wait_job(client, client.post("/api/radar/refresh").json())
    return client.get("/api/radar/latest").json()


# ================================================================== 1. scope

def test_scope_parsing_new_and_legacy() -> None:
    from app.radar import report

    assert report.scope_boards("overall") == report.BOARD_ORDER
    info = report.scope_info("board:female:new")
    assert info["kind"] == "board" and info["gender"] == "female" and info["board"] == "new" and info["category"] is None
    assert report.scope_boards("board:female:new") == [("female", "new")]
    assert report.scope_boards("category:male:new:都市脑洞") == [("male", "new")]
    assert report.scope_info("category:male:read:都市脑洞")["category"] == "都市脑洞"
    # 旧写法保持 v0.9 行为：阅读榜 + 新书榜
    assert report.scope_boards("category:male:都市脑洞") == [("male", "read"), ("male", "new")]
    assert report.parse_scope("board:male:read") == ("board", "male", None)
    assert "只看这一个榜" in report.scope_label("board:male:read")
    assert "新书榜" in report.scope_label("category:female:new:现言脑洞")
    for bad in ("board:male:hot", "board:alien:read", "category:male:read:", "x"):
        with pytest.raises(report.ReportError):
            report.scope_info(bad)


def test_build_input_top_n_default_and_meta() -> None:
    from app.radar import report

    cur = [_item(f"m{i}", f"男书{i}", i, abstract="甲" * 200) for i in range(1, 41)]
    cur += [_item("n1", "新书一", 1, "new"), _item("f1", "女书一", 1, gender="female", cat="现言脑洞")]
    inp = report.build_input(cur, [], "overall")
    assert inp["top_n"] == 30 and len(inp["boards"]["男频阅读"]) == 30
    assert inp["books_read"] == 32  # 男频阅读 30 + 男频新书 1 + 女频阅读 1
    assert "甲" * 80 in inp["boards_text"] and "甲" * 81 not in inp["boards_text"]  # 简介截到 80 字
    assert {"title", "abstract"} <= set(inp["refs"][0]) and len(inp["refs"][0]["abstract"]) == 200  # 查重用完整简介
    one = report.build_input(cur, [], "board:male:new")
    assert one["board_names"] == ["男频新书"] and one["titles"] == ["新书一"]
    cat = report.build_input(cur, [], "category:male:read:都市脑洞", top_n=5)
    assert cat["board_names"] == ["男频阅读"] and len(cat["boards"]["男频阅读"]) == 5
    assert report.build_input(cur, [], "overall", top_n=999)["top_n"] == report.TOP_N_MAX


# ================================================================== 2. normalize_report 新字段

def test_normalize_report_new_fields_and_dedupe() -> None:
    from app.radar import report

    refs = [{"title": "真书", "abstract": "退婚当天他在废品站捡到一台会说话的收音机从此改命"}]
    raw = {
        "headline": "灵异职业化与系统返还双主线，弱起点强结算最吃香" + "多余" * 20,
        "summary": "今天榜上灵异职业化最猛。",
        "boards": [{"board": "男频阅读", "overview": "o", "risks": "跟风太多"}],
        "inspirations": [
            {"title": "《真书》", "logline": "重名"},
            {"title": "抄简介", "logline": "他在废品站捡到一台会说话的收音机"},
            {"title": "殡葬师的第一笔账", "logline": "夜班殡葬师听见遗物说话", "protagonist": "夜班殡葬师", "mechanism": "遗物开口",
             "opening": "灵堂里怀表开口", "selling_points": "开局兑现；收益可见；反差大；第四条", "board": "男频阅读榜"},
            {"title": "修表匠返还十倍寿命", "logline": "修好旧物返还寿命", "selling_points": ["a", "b", "c"], "board": "不存在"},
            "不是对象",
        ],
        "opening_hooks": ["第一句欠债", "", "三百字内失灵"],
        "plot_devices": [{"name": "倒计时结算", "desc": "每章末给结算点"}, "规则反噬：用规则打回去", {"desc": "没名字"}],
        "writing_advice": "开局别讲世界观。",
        "risk_alerts": ["同类开局太多"],
    }
    rep, warns = report.normalize_report(raw, ["真书"], ["男频阅读"], refs)
    assert len(rep["headline"]) == 40 and rep["summary"]
    assert [x["title"] for x in rep["inspirations"]] == ["殡葬师的第一笔账", "修表匠返还十倍寿命"]
    card = rep["inspirations"][0]
    assert card["selling_points"] == ["开局兑现", "收益可见", "反差大"] and card["board"] == "男频阅读"
    assert "board" not in rep["inspirations"][1]
    assert rep["boards"][0]["risks"] == "跟风太多"
    # 模型没给 idea_hooks：由灵感卡派生（单榜日报全部算这个榜）
    assert rep["boards"][0]["idea_hooks"][0] == {"title": "殡葬师的第一笔账", "pitch": "夜班殡葬师听见遗物说话"}
    assert rep["opening_hooks"] == ["第一句欠债", "三百字内失灵"]
    assert rep["plot_devices"] == [{"name": "倒计时结算", "desc": "每章末给结算点"}, {"name": "规则反噬", "desc": "用规则打回去"}]
    assert rep["writing_advice"] and rep["risk_alerts"] == ["同类开局太多"]
    joined = "\n".join(warns)
    assert "《真书》和榜上书重名" in joined.replace("灵感", "") or "重名" in joined
    assert "连续 8 字相同" in joined and "灵感卡只有 2 条" in joined
    # 只有灵感卡、没有榜和热词也算可用
    rep2, _ = report.normalize_report({"inspirations": raw["inspirations"][2:3]}, [], ["男频阅读"])
    assert rep2["inspirations"] and rep2["boards"] == []


def test_old_report_still_normalizes_and_reads(client: TestClient) -> None:
    """旧格式（没有新字段）照常通过校验；库里的旧报告原样返回。"""
    from app.db import session_scope
    from app.models.tables import RadarSnapshot, TrendReport
    from app.radar import report

    old = {"hot_words": [{"word": "读心", "why": "w", "examples": ["真书"]}],
           "boards": [{"board": "男频阅读", "overview": "o", "idea_hooks": [{"title": "新书", "pitch": "梗"}]}]}
    rep, _ = report.normalize_report(old, ["真书"], ["男频阅读"])
    assert rep["inspirations"] == [] and rep["headline"] == "" and rep["boards"][0]["idea_hooks"] == [{"title": "新书", "pitch": "梗"}]
    with session_scope() as s:
        snap = RadarSnapshot(source="mock", items_count=0, version="v092-old-report")
        s.add(snap)
        s.flush()
        s.add(TrendReport(snapshot_id=snap.id or 0, scope="category:male:旧报告题材", report={**old, "warnings": []}, model="mock"))
        s.commit()
    got = client.get("/api/radar/report", params={"scope": "category:male:旧报告题材"}).json()
    assert got["report"]["hot_words"][0]["word"] == "读心" and "inspirations" not in got["report"]
    assert client.get("/api/radar/report/latest", params={"scope": "category:male:旧报告题材"}).json()["id"] == got["id"]


# ================================================================== 3. 日报 API：新 scope 与新字段

def test_report_api_board_and_category_scopes(client: TestClient, fresh_snapshot: dict[str, Any]) -> None:
    from app.db import session_scope
    from app.radar import service as radar

    snap = fresh_snapshot["snapshot"]
    with session_scope() as s:
        items = radar.snapshot_items(s, snap["id"], dedupe=False)
        titles = {i.title for i in items}
        male_cat = next(i.category for i in items if i.gender == "male" and radar.board_of(i) == "read")
    job = client.post("/api/radar/report", json={"scope": "board:male:read"}).json()
    assert job["ref"] == "trend_report:board:male:read"
    res = wait_job(client, job)["result"]
    rep = res["report"]
    assert res["scope"] == "board:male:read" and [b["board"] for b in rep["boards"]] == ["男频阅读"]
    assert rep["headline"] and rep["summary"] and rep["boards"][0]["risks"]
    assert 4 <= len(rep["inspirations"]) <= 6
    assert all(x["title"] not in titles for x in rep["inspirations"])
    assert all({"title", "logline", "protagonist", "mechanism", "opening", "selling_points"} <= set(x) for x in rep["inspirations"])
    assert all(len(x["selling_points"]) == 3 for x in rep["inspirations"])
    assert rep["opening_hooks"] and rep["plot_devices"] and rep["writing_advice"] and rep["risk_alerts"]
    assert any("重名" in w for w in rep["warnings"])  # mock 故意混进的重名灵感被删
    assert rep["meta"]["top_n"] == 30 and rep["meta"]["books_read"] == rep["inputs"]["books_read"] > 0
    assert rep["meta"]["abstract_chars"] == 80
    assert client.get("/api/radar/report/latest", params={"scope": "board:male:read"}).json()["id"] == res["id"]

    scope = f"category:male:read:{male_cat}"
    r2 = wait_job(client, client.post("/api/radar/report", json={"scope": scope, "top_n": 40}).json())["result"]
    assert [b["board"] for b in r2["report"]["boards"]] == ["男频阅读"] and r2["report"]["meta"]["top_n"] == 40
    hist = client.get("/api/radar/reports", params={"scope": scope}).json()
    assert hist and all(h["scope"] == scope for h in hist)
    assert client.post("/api/radar/report", json={"scope": "category:male:read:没有这个题材"}).status_code == 404
    assert client.post("/api/radar/report", json={"scope": "board:male:hot"}).status_code == 400
    assert client.post("/api/radar/report", json={"scope": "overall", "top_n": 51}).status_code == 422


def test_report_ngram_drops_copied_inspiration(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.radar import report, service

    abstract = "退婚当天他在废品站捡到一台会说话的收音机，从此每天收到一条明天的新闻。"
    monkeypatch.setattr(service.fanqie_web, "fetch_rank_lists",
                        lambda **k: ([_item("ng1", "收音机里的明天", 1, abstract=abstract), _item("ng2", "第二本书", 2)], f"v-ng-{time.time()}"))
    monkeypatch.setattr(service, "get_config", lambda s: {"enabled": True, "daily_hour": 8, "auto_report": False})
    wait_job(client, client.post("/api/radar/refresh").json())
    res = report.generate("board:male:read")
    rep = res["report"]
    assert all("收音机" not in x["logline"] for x in rep["inspirations"])
    assert any("连续 8 字相同" in w and "收音机里的明天" in w for w in rep["warnings"])


def test_report_config_and_auto_scopes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import session_scope
    from app.radar import report, service

    cfg = client.get("/api/radar/report/config").json()
    assert cfg == {"radar_report_top_n": 30, "radar_report_auto_scopes": ["overall"]}
    assert client.put("/api/radar/report/config", json={"radar_report_auto_scopes": ["overall", "nope"]}).status_code == 400
    cfg = client.put("/api/radar/report/config", json={"radar_report_auto_scopes": ["overall", "board:male:new", "board:male:new"]}).json()
    assert cfg["radar_report_auto_scopes"] == ["overall", "board:male:new"] and cfg["radar_report_top_n"] == 30
    assert client.put("/api/radar/report/config", json={"radar_report_top_n": 12}).json()["radar_report_auto_scopes"] == ["overall", "board:male:new"]
    # /api/radar/config 的形状不变
    assert set(client.get("/api/radar/config").json()) == {"enabled", "daily_hour", "auto_report"}
    try:
        monkeypatch.setattr(service.fanqie_web, "fetch_rank_lists",
                            lambda **k: ([_item("as1", "自动书", 1), _item("as2", "自动新书", 1, "new")], f"v-auto-{time.time()}"))
        monkeypatch.setattr(service, "get_config", lambda s: {"enabled": True, "daily_hour": 8, "auto_report": True})
        j = wait_job(client, client.post("/api/radar/refresh").json())
        ids = j["result"]["report_job_ids"]
        assert set(ids) == {"overall", "board:male:new"} and j["result"]["report_job_id"] == ids["overall"]
        r = wait_job(client, client.get(f"/api/jobs/{ids['board:male:new']}").json())["result"]
        assert r["scope"] == "board:male:new" and r["report"]["meta"]["top_n"] == 12
        wait_job(client, client.get(f"/api/jobs/{ids['overall']}").json())
        with session_scope() as s:
            assert report.latest_report(s, "board:male:new", snapshot_id=j["result"]["snapshot_id"]) is not None
    finally:
        client.put("/api/radar/report/config", json={"radar_report_top_n": 30, "radar_report_auto_scopes": ["overall"]})


# ================================================================== 4. 种子立项

def test_seed_direct_maps_without_model(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import gateway

    def no_model(*a: Any, **k: Any) -> Any:
        raise AssertionError("expand=false 不应调用模型")

    monkeypatch.setattr(gateway.LLMGateway, "chat_json", no_model)
    body = {"title": "《殡葬师的第一笔账》", "logline": "夜班殡葬师听见遗物说话", "protagonist": "夜班殡葬师，欠债",
            "mechanism": "遗物能报出死者没说完的话", "opening": "灵堂里怀表开口", "selling_points": ["开局兑现", "收益可见", "反差大"],
            "genre": "都市脑洞", "gender": "male", "source": {"type": "trend_report", "report_id": None, "ref": "灵感卡#2"}}
    r = client.post("/api/ideas/from-seed", json=body)
    assert r.status_code == 200, r.text
    idea = r.json()["idea"]
    assert idea["title"] == "殡葬师的第一笔账" and idea["hook"] == "灵堂里怀表开口" and idea["selling_points"] == body["selling_points"]
    assert idea["scores"]["overall"] == 0 and idea["arc"] == [] and idea["genre"] == "都市脑洞"
    src = idea["source"]
    assert src["type"] == src["kind"] == "trend_report" and src["ref"] == "灵感卡#2" and src["expanded"] is False
    assert src["seed"]["mechanism"] == "遗物能报出死者没说完的话"
    book = client.post(f"/api/ideas/{idea['id']}/adopt").json()
    premise = client.get(f"/api/books/{book['id']}").json().get("premise") or ""
    assert "核心机制：遗物能报出死者没说完的话" in premise and "主角：夜班殡葬师" in premise
    # 校验
    assert client.post("/api/ideas/from-seed", json={**body, "title": ""}).status_code == 422
    assert client.post("/api/ideas/from-seed", json={**body, "source": {"type": "weird"}}).status_code == 422
    assert client.post("/api/ideas/from-seed", json={**body, "source": {"type": "rank_book", "book_id_ext": "nope404"}}).status_code == 404
    assert client.post("/api/ideas/from-seed", json={**body, "source": {"type": "trend_report", "report_id": 999999}}).status_code == 404


def test_seed_expand_job_and_self_check(client: TestClient) -> None:
    _add_book("seed01", "收音机里的明天", "退婚当天他在废品站捡到一台会说话的收音机，从此每天收到一条明天的新闻。")
    body = {"title": "修表匠返还十倍寿命", "logline": "修好一件旧物就返还十倍寿命", "mechanism": "修物返寿", "expand": True,
            "source": {"type": "rank_book", "book_id_ext": "seed01"}}
    job = client.post("/api/ideas/from-seed", json=body).json()
    assert job["kind"] == "idea_seed" and job["job_id"] == job["id"]
    res = wait_job(client, job)["result"]
    idea = res["idea"]
    assert res["idea_id"] == idea["id"] and idea["title"] == "修表匠返还十倍寿命"
    assert len(idea["arc"]) >= 3 and idea["endgame"] and idea["scores"]["overall"] > 0
    assert idea["genre"] == "都市脑洞"  # 种子没给题材时取参考书的题材
    src = idea["source"]
    assert src["type"] == "rank_book" and src["ref"] == "rank_book:seed01" and src["book_id_ext"] == "seed01" and src["expanded"] is True
    assert src["self_check"] and isinstance(src["overlap"], list) and isinstance(src["warnings"], list)
    assert any(i["id"] == idea["id"] for i in client.get("/api/ideas").json())


# ================================================================== 5. 一键整理

def test_organize_keeps_author_core(client: TestClient) -> None:
    text = "书名：灶台下的神仙\n小镇饭馆的帮厨陈三，做对一道菜就能解锁一位食客的秘密。老板娘其实是退隐的厨神。想写成慢热的种田升级。"
    job = client.post("/api/ideas/organize", json={"text": text, "gender": "male", "genre": "都市日常"}).json()
    assert job["kind"] == "idea_organize"
    res = wait_job(client, job)["result"]
    idea = res["idea"]
    assert idea["title"] == "灶台下的神仙" and "陈三" in idea["logline"] and idea["genre"] == "都市日常"
    src = idea["source"]
    assert src["type"] == "paste" and src["kind"] == "organize" and src["chars"] == len(text) and len(src["ref"]) <= 60
    assert src["kept_core"] and src["added"]
    assert client.post("/api/ideas/organize", json={"text": "字" * 5001}).status_code == 422
    assert client.post("/api/ideas/organize", json={"text": "   "}).status_code == 400


# ================================================================== 6. 多本熔炉

def test_fusion_weights_dedupe_and_no_text_stored(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import Idea, Job

    _add_book("fus01", "雾港夜巡人", "雾港的夜巡人能看见每盏路灯下藏着的旧账，一盏一盏把账收回来。")
    pasted = "第一章 雨夜\n\n" + "沈砚把伞收起来的时候，巷子尽头那盏灯忽然灭了。" * 30
    body = {"refs": [{"book_id_ext": "fus01", "weight": 3}, {"title": "某本参考", "text": pasted, "weight": 1}], "notes": "要轻松一点", "n": 3}
    job = client.post("/api/ideas/fusion", json=body).json()
    assert job["kind"] == "idea_fusion" and job["job_id"] == job["id"]
    res = wait_job(client, job)["result"]
    assert res["dropped"] == 1 and len(res["ideas"]) == 2 and len(res["idea_ids"]) == 2
    assert any("已丢弃" in w for w in res["warnings"])
    src = res["ideas"][0]["source"]
    assert src["type"] == "fusion" and src["kind"] == "fusion"
    assert src["ref"] == "《雾港夜巡人》×0.75；《某本参考》×0.25"
    assert [r["weight"] for r in src["refs"]] == [0.75, 0.25] and src["refs"][1]["has_text"] is True and src["notes"] == "要轻松一点"
    # 粘贴原文不入库（Idea 与 Job 里都没有）
    with session_scope() as s:
        for i in s.exec(__import__("sqlmodel").select(Idea)).all():
            assert "沈砚把伞收起来" not in json.dumps(i.model_dump(mode="json"), ensure_ascii=False)
        j = s.get(Job, job["id"])
        assert "沈砚把伞收起来" not in json.dumps(j.model_dump(mode="json"), ensure_ascii=False)


def test_fusion_validation(client: TestClient) -> None:
    ok = {"title": "甲", "weight": 1}
    assert client.post("/api/ideas/fusion", json={"refs": []}).status_code == 422
    assert client.post("/api/ideas/fusion", json={"refs": [ok] * 4}).status_code == 422
    assert client.post("/api/ideas/fusion", json={"refs": [{"weight": 1}]}).status_code == 400
    assert client.post("/api/ideas/fusion", json={"refs": [{"title": "甲", "weight": 0}]}).status_code == 422
    assert client.post("/api/ideas/fusion", json={"refs": [{"book_id_ext": "nope404", "weight": 1}]}).status_code == 404
    assert client.post("/api/ideas/fusion", json={"refs": [{"text": "字" * 20001, "weight": 1}]}).status_code == 400
    one = wait_job(client, client.post("/api/ideas/fusion", json={"refs": [{"title": "只有书名的参考", "weight": 2}], "n": 1}).json())["result"]
    assert one["dropped"] == 0 and len(one["ideas"]) == 1 and one["ideas"][0]["source"]["refs"][0]["weight"] == 1.0


# ================================================================== 7. 仿写立项 TXT

def _novel(n: int, body: str = "他推开门，屋里没人。" * 20, head: str = "《雾港夜巡人》\n作者：某人\n简介：一句话简介\n\n") -> str:
    return head + "\n".join(f"第{k}章 夜巡{k}\n{body}\n" for k in range(1, n + 1))


def test_imitate_extract_gb18030_file(client: TestClient) -> None:
    data = _novel(12).encode("gb18030")
    r = client.post("/api/radar/imitate/extract", files={"file": ("雾港夜巡人（全本）.txt", data, "text/plain")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["encoding"] == "gb18030" and out["title_guess"] == "雾港夜巡人" and out["total_chapters"] == 12
    assert [c["title"] for c in out["chapters"]] == [f"第{k}章 夜巡{k}" for k in range(1, 11)]
    assert out["chapters"][0]["chars"] == 200
    assert out["text"].startswith("第1章 夜巡1") and "第10章" in out["text"] and "第11章" not in out["text"]
    assert "简介：一句话简介" not in out["text"] and out["truncated"] is False and out["text_chars"] == len(out["text"])


def test_imitate_extract_json_variants(client: TestClient) -> None:
    long = client.post("/api/radar/imitate/extract", json={"text": _novel(10, body="字" * 5000, head="")}).json()
    assert long["truncated"] is True and len(long["text"]) == 20000 and long["encoding"] == "text"
    utf = client.post("/api/radar/imitate/extract", files={"file": ("x.txt", ("\ufeff" + _novel(2)).encode("utf-8"), "text/plain")}).json()
    assert utf["encoding"] == "utf-8-sig" and utf["total_chapters"] == 2
    en = client.post("/api/radar/imitate/extract", json={"text": "Chapter 1 Rain\nhello there\nCHAPTER 2: Fog\nmore words\n第三回 再会\n回目",
                                                         "filename": "night.txt"}).json()
    assert [c["title"] for c in en["chapters"]] == ["Chapter 1 Rain", "CHAPTER 2: Fog", "第三回 再会"] and en["title_guess"] == "night"
    flat = client.post("/api/radar/imitate/extract", json={"text": "没有章节标题的一段正文。"}).json()
    assert flat["chapters"] == [{"title": "全文", "chars": 12}] and flat["total_chapters"] == 0 and flat["text"] == "没有章节标题的一段正文。"
    assert client.post("/api/radar/imitate/extract", json={"text": "   "}).status_code == 400
    assert client.post("/api/radar/imitate/extract", json={"nope": 1}).status_code == 400
    assert client.post("/api/radar/imitate/extract", files={"file": ("e.txt", b"", "text/plain")}).status_code == 400
    assert client.post("/api/radar/imitate/extract", content=b"raw", headers={"content-type": "text/plain"}).status_code == 400


def test_imitate_text_feeds_deep_teardown(client: TestClient) -> None:
    """extract 出来的 text 可直接喂 v0.7 深度拆解（≤20000 字）。"""
    from app.db import session_scope
    from app.models.tables import RankItem

    _add_book("imi01", "雾港夜巡人", "雾港的夜巡人能看见路灯下的旧账。")
    with session_scope() as s:
        rid = s.exec(__import__("sqlmodel").select(RankItem).where(RankItem.book_id_ext == "imi01")).first().id
    text = client.post("/api/radar/imitate/extract", json={"text": _novel(3)}).json()["text"]
    res = wait_job(client, client.post(f"/api/radar/items/{rid}/deep", json={"text": text}).json())["result"]
    assert len(res["deep"]["chapters"]) == 3


# ================================================================== 8. 提示词与版本

def test_new_prompts_listed_and_wording(client: TestClient) -> None:
    names = {i["name"] for i in client.get("/api/prompts").json()["items"] if i["kind"] == "prompts"}
    assert {"idea_seed", "idea_organize", "idea_fusion", "trend_report"} <= names
    tr = client.get("/api/prompts/prompts/trend_report").json()["content"]
    for key in ("headline", "inspirations", "opening_hooks", "plot_devices", "writing_advice", "risk_alerts", "risks", "$top_n"):
        assert key in tr
    fu = client.get("/api/prompts/prompts/idea_fusion").json()["content"]
    assert "连续 8 个字" in fu and "专有名词" in fu


def test_version_092(client: TestClient) -> None:
    assert client.get("/api/health").json()["version"].startswith(("0.9.", "0.10.", "0.11.", "0.12.", "0.13.", "0.14.", "0.15.", "0.16."))
    assert "## v0.9.2" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## v0.9.2" in (ROOT / "docs" / "API_CONTRACT.md").read_text(encoding="utf-8")
