"""v0.10 同人创作：原著资料（设定卡、原文不入库）、版权确认、同人书三档遵循度、12 方向、上下文注入、OOC 检查、原著重合。

全部走 mock LLM，不做真实网络与模型调用。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from conftest import wait_job

LINE = "雨从屋檐上一串串落下来，打在青石板上溅起细碎的水花，巷子尽头的灯笼被风吹得忽明忽暗。"
SRC_TEXT = "\n".join(
    [f"第{i}章 雨夜\n{LINE}\n林川说：“少废话，要打就打。”\n苏晚说：“你总是这样，一点余地都不留。”\n"
     f"顾长风冷笑：“宗门的规矩，你们也敢坏？”\n林川说：“规矩是给守规矩的人定的。”\n苏晚问：“那我们现在去哪？”\n"
     f"第{i}次交手之后，城里的人都知道了这个名字。" for i in range(1, 9)]
)


def _source(client: TestClient, text: str = SRC_TEXT, **kw: Any) -> dict[str, Any]:
    r = client.post("/api/fanfic/sources", json={"source": "paste", "text": text, "title": "测试原著", **kw})
    assert r.status_code == 200, r.text
    j = wait_job(client, r.json())
    return j["result"]["source"]


def _fanfic_book(client: TestClient, sid: int, fidelity: str = "strict", direction: str = "canon_fill") -> dict[str, Any]:
    r = client.post("/api/books", json={"title": "同人测试书", "genre": "同人", "fanfic": {"source_id": sid, "fidelity": fidelity,
                                                                                    "direction": direction}, "copyright_ack": True})
    assert r.status_code == 200, r.text
    return r.json()


def _chapter(bid: int, content: str, number: int = 1) -> int:
    from app.db import session_scope
    from app.lint.humanlint import count_words
    from app.models.tables import Chapter

    with session_scope() as s:
        ch = Chapter(book_id=bid, number=number, title=f"第{number}章", content=content, words=count_words(content))
        s.add(ch)
        s.commit()
        s.refresh(ch)
        return int(ch.id or 0)


# ------------------------------------------------------------------ 表与字段

def test_new_tables_and_columns() -> None:
    from sqlalchemy import inspect

    from app.db import session_scope

    with session_scope() as s:
        insp = inspect(s.get_bind())
        assert "fanfic_source" in set(insp.get_table_names())
        assert "fanfic" in {c["name"] for c in insp.get_columns("book")}
        assert "fanfic_meta" in {c["name"] for c in insp.get_columns("chapter")}


# ------------------------------------------------------------------ 方向模板

def test_directions_catalog(client: TestClient) -> None:
    r = client.get("/api/fanfic/directions").json()
    ds = r["directions"]
    assert len(ds) == 12
    ids = {d["id"] for d in ds}
    assert {"canon_fill", "if_line", "transmigration", "rebirth", "system", "au_modern", "au_ancient", "side_pov", "cp",
            "villain_redemption", "epilogue", "crossover"} == ids
    for d in ds:
        assert d["label"] and d["desc"] and d["tips"] and d["risks"] and d["suggested_fidelity"] in ("strict", "moderate", "loose")
    assert [f["id"] for f in r["fidelities"]] == ["strict", "moderate", "loose"]
    assert "版权" in r["copyright_notice"] or "授权" in r["copyright_notice"]


# ------------------------------------------------------------------ 原著资料

def test_source_create_no_raw_text(client: TestClient) -> None:
    src = _source(client, focus=["林川"])
    assert src["title"] == "测试原著"
    names = [c["name"] for c in src["cards"]["characters"]]
    assert "林川" in names and "苏晚" in names
    assert src["cards"]["world"]["summary"]
    assert src["cards"]["timeline"] and src["cards"]["scenes"]
    assert 0 < src["completeness"] <= 100
    assert src["chars"] > 0 and src["total_chars"] >= src["chars"]
    # 原文不入库：库里没有任何原文句子，只有 int 指纹
    from app.db import session_scope
    from app.models.tables import FanficSource

    with session_scope() as s:
        row = s.get(FanficSource, src["id"])
        assert row is not None
        assert row.fingerprint and all(isinstance(x, int) for x in row.fingerprint[:20])
        dump = str(row.cards) + str(row.warnings) + row.title
        assert "青石板上溅起细碎的水花" not in dump
    # 列表 / 详情
    lst = client.get("/api/fanfic/sources").json()
    assert any(x["id"] == src["id"] and "cards" not in x and x["counts"]["characters"] >= 2 for x in lst)
    assert client.get(f"/api/fanfic/sources/{src['id']}").json()["id"] == src["id"]
    assert client.get("/api/fanfic/sources/999999").status_code == 404


def test_source_validation(client: TestClient) -> None:
    assert client.post("/api/fanfic/sources", json={"source": "paste", "text": "太短了"}).status_code == 400
    assert client.post("/api/fanfic/sources", json={"source": "web", "text": SRC_TEXT}).status_code == 422
    assert client.post("/api/fanfic/sources", json={"source": "paste", "text": SRC_TEXT, "depth": "xx"}).status_code == 422


def test_source_txt_upload(client: TestClient) -> None:
    r = client.post("/api/fanfic/sources", files={"file": ("yuan.txt", SRC_TEXT.encode("gb18030"), "text/plain")},
                    data={"title": "TXT 原著", "focus": "林川,苏晚", "depth": "quick"})
    assert r.status_code == 200, r.text
    src = wait_job(client, r.json())["result"]["source"]
    assert src["source"] == "txt" and src["depth"] == "quick" and src["focus"] == ["林川", "苏晚"]
    assert any(c["name"] == "林川" for c in src["cards"]["characters"])


def test_source_scrub_copied_fields(client: TestClient, monkeypatch: Any) -> None:
    from app.llm import mock

    orig = mock.HANDLERS["fanfic_source"]

    def copying(meta: dict[str, Any]) -> str:
        import json

        d = json.loads(orig(meta))
        d["scenes"].append({"title": "照抄", "summary": LINE, "characters": ["林川"]})
        d["characters"][0]["personality"] = LINE
        return mock._j(d)

    monkeypatch.setitem(mock.HANDLERS, "fanfic_source", copying)
    src = _source(client, depth="quick")
    assert all(x["summary"] != LINE for x in src["cards"]["scenes"])
    assert src["cards"]["characters"][0]["personality"] == ""
    assert any("连续 8 字" in w for w in src["warnings"])


def test_source_update_and_delete(client: TestClient) -> None:
    src = _source(client, depth="quick")
    sid = src["id"]
    chars = src["cards"]["characters"]
    chars[0]["catchphrases"] = ["少废话", "要打就打"]
    chars[0]["notes"] = LINE  # 作者手改照抄：只提醒不删
    r = client.put(f"/api/fanfic/sources/{sid}", json={"title": "改名原著", "cards": {"characters": chars}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source"]["title"] == "改名原著"
    assert out["source"]["cards"]["characters"][0]["catchphrases"] == ["少废话", "要打就打"]
    assert out["source"]["cards"]["characters"][0]["notes"] == LINE
    assert out["warnings"]
    assert client.put(f"/api/fanfic/sources/{sid}", json={"cards": {"bogus": []}}).status_code == 422
    # 被书引用时删除要 force
    _fanfic_book(client, sid)
    assert client.delete(f"/api/fanfic/sources/{sid}").status_code == 409
    assert client.delete(f"/api/fanfic/sources/{sid}?force=true").json() == {"ok": True}
    assert client.get(f"/api/fanfic/sources/{sid}").status_code == 404


# ------------------------------------------------------------------ 版权确认与同人书

def test_copyright_ack_required(client: TestClient) -> None:
    src = _source(client, depth="quick")
    n0 = len(client.get("/api/books").json())
    r = client.post("/api/books", json={"title": "未确认", "fanfic": {"source_id": src["id"]}})
    assert r.status_code == 400 and "版权" in r.json()["detail"]
    assert len(client.get("/api/books").json()) == n0  # 不建书
    assert client.post("/api/books", json={"title": "x", "fanfic": {"source_id": 999999}, "copyright_ack": True}).status_code == 404
    bid = client.post("/api/books", json={"title": "原创书"}).json()["id"]
    assert client.post(f"/api/books/{bid}/fanfic", json={"source_id": src["id"]}).status_code == 400
    r = client.post(f"/api/books/{bid}/fanfic", json={"source_id": src["id"], "fidelity": "loose", "direction": "au_modern",
                                                     "copyright_ack": True})
    assert r.status_code == 200, r.text
    ff = r.json()["fanfic"]
    assert ff["fidelity"] == "loose" and ff["direction"] == "au_modern" and ff["copyright_ack_at"]
    assert ff["direction_label"] == "AU 现代" and ff["source"]["id"] == src["id"]
    assert client.get(f"/api/books/{bid}").json()["fanfic"]["source_id"] == src["id"]
    # 改档不用重新确认
    r = client.patch(f"/api/books/{bid}/fanfic", json={"fidelity": "moderate"}).json()
    assert r["fanfic"]["fidelity"] == "moderate" and r["fanfic"]["direction"] == "au_modern"
    assert client.post(f"/api/books/{bid}/fanfic", json={"source_id": src["id"], "fidelity": "xx", "copyright_ack": True}).status_code == 422
    assert client.delete(f"/api/books/{bid}/fanfic").json() == {"ok": True}
    assert client.get(f"/api/books/{bid}").json()["fanfic"] is None
    assert client.patch(f"/api/books/{bid}/fanfic", json={"fidelity": "strict"}).status_code == 400


def test_create_book_with_fanfic(client: TestClient) -> None:
    src = _source(client, depth="quick")
    b = _fanfic_book(client, src["id"], "strict", "side_pov")
    assert b["fanfic"]["fidelity"] == "strict" and b["fanfic"]["copyright_ack"] is True
    assert client.post("/api/books", json={"title": "普通书"}).json()["fanfic"] is None


# ------------------------------------------------------------------ 上下文注入（三档）

def test_context_block_by_fidelity(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import Book
    from app.services import common

    src = _source(client, depth="quick")
    texts = {}
    for fid in ("strict", "moderate", "loose"):
        bid = _fanfic_book(client, src["id"], fid)["id"]
        r = client.get(f"/api/books/{bid}/fanfic/context").json()
        texts[fid] = r["text"]
        assert "林川" in r["text"] and "遵循规则" in r["text"]
        with session_scope() as s:
            b = s.get(Book, bid)
            assert b is not None
            assert "同人创作·原著设定" in common.book_context(s, b, with_cards=False)
    assert "不得改写" in texts["strict"]
    assert "AU" in texts["loose"] and "原著时间线（已发生" not in texts["loose"] and "原著主线节点" not in texts["loose"]
    assert "支线" in texts["moderate"]
    plain = client.post("/api/books", json={"title": "原创"}).json()["id"]
    assert client.get(f"/api/books/{plain}/fanfic/context").json()["text"] == ""


def test_context_reaches_outline_prompt(client: TestClient) -> None:
    """大纲任务的提示词里带上原著卡（经 common.book_context 钩子）。"""
    from app.db import session_scope
    from app.models.tables import Book
    from app.services import common
    from app.skills.loader import render

    src = _source(client, depth="quick")
    bid = _fanfic_book(client, src["id"], "moderate", "if_line")["id"]
    with session_scope() as s:
        b = s.get(Book, bid)
        assert b is not None
        txt = render("outline", book_context=common.book_context(s, b), target_words=b.target_words)
    assert "if 线改写" in txt and "林川" in txt


def test_import_cards(client: TestClient) -> None:
    src = _source(client, depth="quick")
    bid = _fanfic_book(client, src["id"])["id"]
    r = client.post(f"/api/books/{bid}/fanfic/import-cards", json={"parts": ["characters", "world", "factions"]})
    assert r.status_code == 200, r.text
    cards = r.json()["cards"]
    lc = next(c for c in cards if c["name"] == "林川")
    assert lc["type"] == "character"
    assert any(c["type"] == "world" for c in cards) and any(c["type"] == "faction" for c in cards)
    again = client.post(f"/api/books/{bid}/fanfic/import-cards", json={"parts": ["characters"]}).json()
    assert again["cards"] == [] and again["skipped"] >= 2
    plain = client.post("/api/books", json={"title": "原创"}).json()["id"]
    assert client.post(f"/api/books/{plain}/fanfic/import-cards", json={"parts": ["characters"]}).status_code == 400


# ------------------------------------------------------------------ OOC 检查

CH_TEXT = ("林川推开门，慢慢解释了很久自己为什么来，语气温柔得不像他。\n"
           "林川说：“少废话。”苏晚看着他。林川又说：“少废话。”“少废话！”“少废话，走。”\n"
           "苏晚说：“我们先回城里，别让顾长风察觉。”")


def test_ooc_check(client: TestClient) -> None:
    src = _source(client, depth="quick")
    bid = _fanfic_book(client, src["id"], "strict")["id"]
    cid = _chapter(bid, CH_TEXT)
    r = client.post(f"/api/chapters/{cid}/ooc-check")
    assert r.status_code == 200, r.text
    res = wait_job(client, r.json())["result"]
    ooc = res["ooc"]
    assert ooc["fidelity"] == "strict" and ooc["pass_score"] == 80
    names = {c["name"] for c in ooc["characters"]}
    assert "林川" in names and "苏晚" in names
    lc = next(c for c in ooc["characters"] if c["name"] == "林川")
    assert 0 <= lc["score"] <= 100 and lc["level"] in ("pass", "warn", "fail")
    types = {i["type"] for i in lc["issues"]}
    assert "speech" in types  # mock 模型给的
    assert "catchphrase" in types  # 程序发现口癖刷屏
    for i in lc["issues"]:
        assert i["quote"] and i["type_label"]
    assert ooc["verdict"] in ("pass", "warn", "fail")
    assert res["overlap"]["level"] == "ok"
    # 存进章节 meta
    got = client.get(f"/api/chapters/{cid}/ooc").json()
    assert got["ooc"]["overall"] == ooc["overall"] and got["ooc"]["stale"] is False
    client.put(f"/api/chapters/{cid}", json={"content": CH_TEXT + "\n林川点头。"})
    assert client.get(f"/api/chapters/{cid}/ooc").json()["ooc"]["stale"] is True


def test_ooc_fidelity_leniency(client: TestClient, monkeypatch: Any) -> None:
    from app.llm import mock

    def timeline_issue(meta: dict[str, Any]) -> str:
        q = meta["quotes"]
        return mock._j({"characters": [{"name": n, "score": 80, "issues": [
            {"type": "timeline", "severity": "low", "quote": q.get(n) or "", "problem": "时间点不对", "suggestion": "改"}]}
            for n in meta["characters"]], "summary": ""})

    monkeypatch.setitem(mock.HANDLERS, "fanfic_ooc", timeline_issue)
    src = _source(client, depth="quick")
    out = {}
    for fid in ("strict", "loose"):
        bid = _fanfic_book(client, src["id"], fid)["id"]
        cid = _chapter(bid, "苏晚说：“我们先回城里，别让顾长风察觉。”")
        out[fid] = wait_job(client, client.post(f"/api/chapters/{cid}/ooc-check").json())["result"]["ooc"]
    s_iss = [i for c in out["strict"]["characters"] for i in c["issues"]]
    assert s_iss and all(i["severity"] == "mid" for i in s_iss if i["type"] == "timeline")  # strict 加严
    assert not [i for c in out["loose"]["characters"] for i in c["issues"] if i["type"] == "timeline"]  # AU 忽略时间线
    assert out["loose"]["ignored_issues"] >= 1


def test_ooc_requires_fanfic_book(client: TestClient) -> None:
    plain = client.post("/api/books", json={"title": "原创"}).json()["id"]
    cid = _chapter(plain, "林川说：“少废话。”")
    assert client.post(f"/api/chapters/{cid}/ooc-check").status_code == 400
    assert client.post("/api/chapters/999999/ooc-check").status_code == 404


def test_ooc_block_for_review(client: TestClient) -> None:
    from app.db import session_scope
    from app.models.tables import Chapter
    from app.services import fanfic

    src = _source(client, depth="quick")
    bid = _fanfic_book(client, src["id"], "moderate")["id"]
    cid = _chapter(bid, CH_TEXT)
    wait_job(client, client.post(f"/api/chapters/{cid}/ooc-check").json())
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        assert ch is not None
        issues = fanfic.ooc_block(s, ch)
    assert issues and all(i["dimension"] in ("character", "semantics") and i["quote"] for i in issues)
    assert any("OOC" in i["comment"] for i in issues)
    plain = client.post("/api/books", json={"title": "原创"}).json()["id"]
    pc = _chapter(plain, CH_TEXT)
    with session_scope() as s:
        ch = s.get(Chapter, pc)
        assert ch is not None and fanfic.ooc_block(s, ch) == []


# ------------------------------------------------------------------ 原著重合（融合二创检查）

def test_overlap_check(client: TestClient) -> None:
    src = _source(client, depth="quick")
    bid = _fanfic_book(client, src["id"])["id"]
    clean = _chapter(bid, "林川收起刀，转身走进夜色。苏晚没有追，只在门口站了很久。")
    r = client.post(f"/api/chapters/{clean}/fanfic-overlap").json()
    assert r["overlap"]["level"] == "ok" and r["overlap"]["segments"] == 0
    copied = _chapter(bid, "他抬头看天。" + LINE + "林川握紧了刀柄。", number=2)
    ov = client.post(f"/api/chapters/{copied}/fanfic-overlap").json()["overlap"]
    assert ov["segments"] >= 1 and ov["longest"] >= 20 and ov["level"] in ("warn", "high") and ov["warning"]
    assert ov["samples"] and "青石板" in ov["samples"][0]
    assert client.get(f"/api/chapters/{copied}/ooc").json()["overlap"]["segments"] == ov["segments"]
    from app.services import fanfic

    from app.db import session_scope
    from app.models.tables import Chapter

    assert fanfic.text_overlap(bid, "林川收起刀。")["level"] == "ok"
    with session_scope() as s:
        ch = s.get(Chapter, copied)
        assert ch is not None
        assert any("原著重合" in i["comment"] for i in fanfic.ooc_block(s, ch))


def test_select_material_large_text() -> None:
    from app.services import fanfic

    para = "这是一段用来凑字数的普通叙述文字，没有任何人物出场。"
    big = "\n".join([para + str(i) for i in range(12000)] + ["林川说：“重点段落在最后。”"])
    selected, chunks = fanfic.select_material(big, ["林川"], "deep")
    assert len(selected) <= fanfic.FP_CHARS * 1.1  # 段落间换行不计入预算
    assert "重点段落在最后" in selected
    assert 1 <= len(chunks) <= 4 and all(len(c) <= fanfic.PROMPT_CHUNK for c in chunks)
    assert any("重点段落在最后" in c for c in chunks)
