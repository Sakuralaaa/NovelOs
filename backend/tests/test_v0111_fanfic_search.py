"""v0.11.1 同人「联网取材」：source=search、原文 + 联网补充、已有资料联网补充、无搜索模型 422、热门题材模板。

全部走 mock LLM / 打桩的搜索函数，不做真实网络与模型调用。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import wait_job
from test_v010 import SRC_TEXT, _chapter, _fanfic_book, _source


def _search_source(client: TestClient, **kw: Any) -> dict[str, Any]:
    body = {"source": "search", "title": "斗罗大陆", "template_id": "douluo", "depth": "quick", **kw}
    r = client.post("/api/fanfic/sources", json=body)
    assert r.status_code == 200, r.text
    return wait_job(client, r.json())["result"]


def _fp(sid: int) -> list[int]:
    from app.db import session_scope
    from app.models.tables import FanficSource

    with session_scope() as s:
        row = s.get(FanficSource, sid)
        assert row is not None
        return list(row.fingerprint or [])


# ------------------------------------------------------------------ 模板

def test_templates_catalog(client: TestClient) -> None:
    from app.services.fanfic_directions import DIRECTION_IDS

    r = client.get("/api/fanfic/templates")
    assert r.status_code == 200
    d = r.json()
    ts = d["templates"]
    assert 15 <= len(ts) <= 20
    titles = {t["title"] for t in ts}
    for need in ("斗罗大陆", "斗破苍穹", "漫威", "龙族", "宝可梦", "火影忍者", "海贼王", "哈利·波特", "原神", "崩坏：星穹铁道",
                 "凡人修仙传", "诡秘之主", "名侦探柯南", "遮天", "完美世界", "DC"):
        assert need in titles, need
    assert len({t["id"] for t in ts}) == len(ts)
    assert set(d["categories"]) == {"国漫", "网文", "欧美", "日漫", "游戏"}
    for t in ts:
        assert t["category"] in d["categories"]
        assert t["intro"] and len(t["intro"]) <= 60
        assert len(t["characters"]) >= 4 and t["search_focus"] and t["styles"]
        assert all(x in DIRECTION_IDS for x in t["directions"])
        assert all(st["direction"] in DIRECTION_IDS and st["label"] and st["desc"] for st in t["styles"])
    assert d["search"]["mode"] == "mock" and d["search"]["available"] is True


def test_find_template_by_alias() -> None:
    from app.services.fanfic_templates import find_template

    assert find_template(None, "航海王")["id"] == "onepiece"
    assert find_template(None, "哈利波特")["id"] == "harrypotter"
    assert find_template("marvel", "随便")["id"] == "marvel"
    assert find_template(None, "完全不存在的作品") is None


def test_plan_queries_by_depth() -> None:
    from app.services import fanfic as ff
    from app.services.fanfic_templates import TEMPLATE_BY_ID

    tpl = TEMPLATE_BY_ID["naruto"]
    assert len(ff.plan_queries("火影忍者", [], "quick")) == 2
    assert len(ff.plan_queries("火影忍者", [], "standard")) == 4
    assert len(ff.plan_queries("火影忍者", ["宇智波鼬", "佐助"], "standard")) == 6
    deep = ff.plan_queries("火影忍者", [], "deep", tpl)
    assert len(deep) >= 6 and all("火影忍者" in q for _, q in deep)
    assert any("宇智波鼬" in q for _, q in ff.plan_queries("火影忍者", ["宇智波鼬"], "quick"))
    assert len(ff.plan_queries("x", [f"人物{i}" for i in range(10)], "quick")) == 2 + ff.MAX_FOCUS_ROUNDS


# ------------------------------------------------------------------ 纯联网取材（mock 演示）

def test_search_source_mock_flow(client: TestClient) -> None:
    res = _search_source(client, focus=["唐三"])
    src = res["source"]
    assert src["source"] == "search" and src["title"] == "斗罗大陆" and src["template_id"] == "douluo"
    assert src["web_rounds"] == 3  # quick 2 轮 + 重点 1 轮
    assert src["chars"] == 0 and src["total_chars"] == 0
    names = [c["name"] for c in src["cards"]["characters"]]
    assert "唐三" in names
    assert src["refs"] and all(u.startswith("https://") for u in src["refs"]) and src["refs_count"] == len(src["refs"])
    assert any("联网检索" in w for w in src["warnings"])
    assert _fp(src["id"]) == []
    lst = client.get("/api/fanfic/sources").json()
    assert any(x["id"] == src["id"] and x["source"] == "search" for x in lst)

    # 空指纹：重合检查不报错，标 no_fingerprint；OOC 照常
    bid = _fanfic_book(client, src["id"], fidelity="moderate", direction="transmigration")["id"]
    cid = _chapter(bid, "唐三收起暗器，抬头看了一眼天色。小舞在旁边笑：“走吧。”")
    ov = client.post(f"/api/chapters/{cid}/fanfic-overlap").json()["overlap"]
    assert ov["level"] == "ok" and ov["no_fingerprint"] is True and "联网" in ov["warning"]
    j = wait_job(client, client.post(f"/api/chapters/{cid}/ooc-check").json())
    assert j["result"]["overlap"]["no_fingerprint"] is True
    from app.db import session_scope
    from app.models.tables import Chapter
    from app.services import fanfic

    with session_scope() as s:
        ch = s.get(Chapter, cid)
        assert ch is not None
        assert not any("原著重合" in i["comment"] for i in fanfic.ooc_block(s, ch))


def test_search_source_validation(client: TestClient) -> None:
    assert client.post("/api/fanfic/sources", json={"source": "search"}).status_code == 422
    assert client.post("/api/fanfic/sources", json={"source": "search", "title": "  "}).status_code == 422
    assert client.post("/api/fanfic/sources", json={"source": "search", "title": "龙族", "depth": "xx"}).status_code == 422
    # paste 仍然要原文
    assert client.post("/api/fanfic/sources", json={"source": "paste", "title": "龙族"}).status_code == 400
    # 联网补充要作品名
    r = client.post("/api/fanfic/sources", json={"source": "paste", "text": SRC_TEXT, "web_supplement": True})
    assert r.status_code == 422 and "原著名" in r.json()["detail"]


def test_search_free_title_without_template(client: TestClient) -> None:
    src = _search_source(client, title="某部自拟作品", template_id=None, focus=["主角甲"], depth="standard")["source"]
    assert src["template_id"] == "" and src["web_rounds"] == 5
    assert "主角甲" in [c["name"] for c in src["cards"]["characters"]]


# ------------------------------------------------------------------ 原文 + 联网补充

def test_paste_with_web_supplement(client: TestClient) -> None:
    r = client.post("/api/fanfic/sources", json={"source": "paste", "text": SRC_TEXT, "title": "斗罗大陆", "depth": "quick",
                                                 "web_supplement": True})
    assert r.status_code == 200, r.text
    src = wait_job(client, r.json())["result"]["source"]
    assert src["source"] == "paste" and src["web_rounds"] >= 2 and src["template_id"] == "douluo"
    names = [c["name"] for c in src["cards"]["characters"]]
    assert "林川" in names and "唐三" in names
    assert names.index("林川") < names.index("唐三")  # 原文提炼在前
    tang = next(c for c in src["cards"]["characters"] if c["name"] == "唐三")
    assert "联网补充" in tang["notes"]
    assert any(w.startswith("联网补充") for w in src["warnings"])
    assert _fp(src["id"])  # 原文指纹仍在


def test_txt_with_web_supplement(client: TestClient) -> None:
    r = client.post("/api/fanfic/sources", files={"file": ("yuan.txt", SRC_TEXT.encode("utf-8"), "text/plain")},
                    data={"title": "龙族", "depth": "quick", "web_supplement": "1"})
    assert r.status_code == 200, r.text
    src = wait_job(client, r.json())["result"]["source"]
    assert src["source"] == "txt" and src["web_rounds"] >= 2 and src["template_id"] == "longzu"


def test_supplement_existing_source(client: TestClient) -> None:
    base = _source(client, depth="quick", title="火影忍者")
    assert base["web_rounds"] == 0 and base["refs"] == []
    r = client.post(f"/api/fanfic/sources/{base['id']}/supplement", json={"depth": "quick", "focus": ["宇智波鼬"]})
    assert r.status_code == 200, r.text
    j = wait_job(client, r.json())
    assert j["kind"] == "fanfic_supplement"
    res = j["result"]
    src = res["source"]
    assert src["id"] == base["id"] and src["web_rounds"] >= 3 and src["refs"]
    assert res["added"]["characters"] >= 1
    old = {c["name"]: c for c in base["cards"]["characters"]}
    for c in src["cards"]["characters"]:
        if c["name"] in old:
            assert c["personality"] == old[c["name"]]["personality"]  # 以已有资料为准
    assert client.post("/api/fanfic/sources/999999/supplement", json={}).status_code == 404
    assert client.post(f"/api/fanfic/sources/{base['id']}/supplement", json={"depth": "nope"}).status_code == 422


def test_merge_priority_conflicts() -> None:
    from app.services import fanfic as ff

    base = {"characters": [{"name": "林川", "role": "主角", "personality": "冷", "relations": [{"target": "苏晚", "relation": "青梅竹马"}]}],
            "factions": [{"name": "宗门", "stance": "中立"}], "timeline": [{"event": "雨夜一战"}]}
    extra = {"characters": [{"name": "林川", "role": "反派", "personality": "热", "speech_style": "话少",
                             "relations": [{"target": "苏晚", "relation": "仇人"}, {"target": "顾长风", "relation": "师兄"}]},
                            {"name": "新角色", "role": "配角"}],
             "factions": [{"name": "宗门", "stance": "敌对"}, {"name": "魔教", "stance": "敌对"}],
             "timeline": [{"event": "雨夜一战"}, {"event": "后续大战"}]}
    cards, warns, added = ff.merge_priority(base, extra)
    lin = cards["characters"][0]
    assert lin["role"] == "主角" and lin["personality"] == "冷" and lin["speech_style"] == "话少"
    assert {r["target"]: r["relation"] for r in lin["relations"]} == {"苏晚": "青梅竹马", "顾长风": "师兄"}
    assert cards["factions"][0]["stance"] == "中立"
    assert [t["event"] for t in cards["timeline"]] == ["雨夜一战", "后续大战"]
    assert added == {"characters": 1, "factions": 1, "timeline": 1, "scenes": 0, "rules": 0, "locations": 0}
    assert sum("不一致" in w for w in warns) == 3 and all("以原文为准" in w for w in warns if "不一致" in w)


# ------------------------------------------------------------------ 真实搜索路径（打桩）与无搜索模型

def test_web_mode_uses_long_search_prompt(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.gateway import SEARCH_SYSTEM_MAX, get_gateway
    from app.services import fanfic as ff

    calls: list[dict[str, Any]] = []

    def fake_search(query: str, context: str = "", system: str | None = None) -> str:
        calls.append({"q": query, "ctx": context, "system": system})
        return f"资料：唐三是主角，小舞与他关系密切。来源：https://baike.example.org/{len(calls)} 以及 https://wiki.example.org/x。"

    monkeypatch.setattr(ff, "search_mode", lambda: "web")
    monkeypatch.setattr(get_gateway(), "search", fake_search)
    src = _search_source(client, depth="standard", focus=[])["source"]
    assert len(calls) == 4 and src["web_rounds"] == 4
    assert all(c["system"] == ff.FANFIC_SEARCH_SYSTEM for c in calls)
    assert 250 < len(ff.FANFIC_SEARCH_SYSTEM) <= SEARCH_SYSTEM_MAX
    assert "https://wiki.example.org/x" in src["refs"] and all(not u.endswith("。") for u in src["refs"])


def test_web_mode_partial_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.gateway import LLMError, get_gateway
    from app.services import fanfic as ff

    n = {"i": 0}

    def flaky(query: str, context: str = "", system: str | None = None) -> str:
        n["i"] += 1
        if "主要人物" in query or "人物的身份" in query:
            raise LLMError("超时")
        return "资料：唐三是主角。来源：https://a.example.org/1"

    monkeypatch.setattr(ff, "search_mode", lambda: "web")
    monkeypatch.setattr(get_gateway(), "search", flaky)
    src = _search_source(client, depth="quick", focus=[])["source"]
    assert src["web_rounds"] == 1 and any("失败" in w for w in src["warnings"])


def test_gateway_search_system_limit() -> None:
    from app.llm.gateway import SEARCH_SYSTEM_MAX, get_gateway

    with pytest.raises(ValueError):
        get_gateway().search("q", system="长" * (SEARCH_SYSTEM_MAX + 1))
    assert get_gateway().search("q", system="自定义") is None  # mock 模式没有搜索路由


def test_no_search_model_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import fanfic as ff

    base = _source(client, depth="quick")
    monkeypatch.setattr(ff, "search_mode", lambda: "none")
    r = client.post("/api/fanfic/sources", json={"source": "search", "title": "龙族"})
    assert r.status_code == 422 and "任务路由" in r.json()["detail"] and "联网搜索" in r.json()["detail"]
    r = client.post("/api/fanfic/sources", json={"source": "paste", "text": SRC_TEXT, "title": "龙族", "web_supplement": True})
    assert r.status_code == 422 and "联网搜索" in r.json()["detail"]
    r = client.post(f"/api/fanfic/sources/{base['id']}/supplement", json={})
    assert r.status_code == 422 and "联网搜索" in r.json()["detail"]
    t = client.get("/api/fanfic/templates").json()["search"]
    assert t == {"mode": "none", "available": False, "hint": ff.NO_SEARCH_MSG}
    # 不勾联网补充的 paste 不受影响
    assert client.post("/api/fanfic/sources", json={"source": "paste", "text": SRC_TEXT, "title": "龙族"}).status_code == 200


def test_search_mode_real_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """有渠道（非 mock）但没配搜索路由 → none；配了 → web。"""
    from app.llm import gateway
    from app.services import fanfic as ff

    monkeypatch.setattr(ff, "is_mock_mode", lambda s: False)
    monkeypatch.setattr(gateway.LLMGateway, "has_search", lambda self: False)
    assert ff.search_mode() == "none"
    monkeypatch.setattr(gateway.LLMGateway, "has_search", lambda self: True)
    assert ff.search_mode() == "web"


def test_new_columns_migrate() -> None:
    from sqlalchemy import inspect

    from app.db import get_engine

    cols = {c["name"] for c in inspect(get_engine()).get_columns("fanfic_source")}
    assert {"refs", "template_id", "web_rounds"} <= cols
