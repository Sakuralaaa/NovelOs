"""v0.13：批量质检、章节工具（章名 / 脑洞 / 神评 / 查找替换 / 高频词 / 排版）、笔记、@变量与上下文构成、抽卡立项、同人三步立项与原创主角、旧金手指卡迁移。"""

from __future__ import annotations

from typing import Any

from conftest import wait_job

PARA = "林川把剑往背后一收，抬头看了眼山门。赵管事冷笑一声，说外门杂役也敢来领月钱？林川没说话，一拳砸在门柱上。"


def _book(client: Any, n: int = 3, title: str = "v013") -> tuple[int, list[dict[str, Any]]]:
    text = "\n\n".join(f"第{i}章 第{i}回合\n" + (PARA + "\n") * 8 for i in range(1, n + 1))
    pv = client.post("/api/books/import", json={"text": text}).json()
    r = client.post("/api/books/import/commit", json={"import_id": pv["import_id"], "title": title})
    assert r.status_code == 200, r.text
    bid = r.json()["book_id"]
    return bid, client.get(f"/api/books/{bid}/chapters").json()


def test_batch_format_titles_review(client: Any) -> None:
    bid, chs = _book(client, 3, "批量")
    from app.db import session_scope
    from app.models.tables import Chapter

    with session_scope() as s:  # 弄乱一章排版
        c = s.get(Chapter, chs[0]["id"])
        c.content = c.content.replace("\n\n", "\n").replace("。", "。 ", 2) + "...."
        s.add(c)
        s.commit()
    client.patch(f"/api/books/{bid}", json={"approval_mode": "review"})  # 审批模式：批量结果进待采纳
    j = wait_job(client, client.post(f"/api/books/{bid}/batch", json={"op": "format", "start": 1, "end": 3}).json())
    rows = {r["number"]: r for r in j["result"]["rows"]}
    assert rows[1]["status"] == "ok" and rows[1]["iteration_id"]
    its = client.get(f"/api/books/{bid}/wanben/iterations", params={"status": "pending"}).json()
    assert any(it["method"] == "format" and it["number"] == 1 for it in its)
    full = client.get(f"/api/books/{bid}/wanben/iterations/{rows[1]['iteration_id']}").json()
    assert "……" in full["content"] and "\n\n" in full["content"]
    client.post(f"/api/books/{bid}/wanben/iterations/{rows[1]['iteration_id']}/adopt")
    assert "……" in client.get(f"/api/chapters/{chs[0]['id']}").json()["content"]

    j = wait_job(client, client.post(f"/api/books/{bid}/batch", json={"op": "titles", "numbers": [2]}).json())
    t = j["result"]["rows"][0]["titles"]
    assert t and t[0]["score"] >= t[-1]["score"]
    j = wait_job(client, client.post(f"/api/books/{bid}/batch", json={"op": "review", "start": 1, "end": 2}).json())
    assert j["result"]["summary"]["ok"] == 2
    assert client.post(f"/api/books/{bid}/batch", json={"op": "aigc", "start": 1}).status_code == 409  # 没配朱雀


def test_chapter_tools(client: Any) -> None:
    bid, chs = _book(client, 2, "工具")
    cid = chs[0]["id"]
    r = wait_job(client, client.post(f"/api/chapters/{cid}/titles", json={"n": 6}).json())["result"]
    assert r["titles"] and all(4 <= len(x["title"]) <= 30 for x in r["titles"])
    r = wait_job(client, client.post(f"/api/books/{bid}/sparks", json={"n": 5}).json())["result"]
    assert len(r["sparks"]) == 5
    r = wait_job(client, client.post(f"/api/chapters/{cid}/reader-comments").json())["result"]
    content = client.get(f"/api/chapters/{cid}").json()["content"]
    assert r["comments"] and all(c["quote"] in content for c in r["comments"])
    assert r["dropped"] >= 1  # 编造的原句被丢掉
    fr = client.get(f"/api/chapters/{cid}/freq").json()["items"]
    assert fr and fr[0]["count"] >= 3
    f = client.post("/api/format", json={"text": "他说:\"走吧\"...\n\n\n她点头,没说话"}).json()
    assert f["text"] == "他说：“走吧”……\n\n她点头，没说话"


def test_search_replace_and_notes(client: Any) -> None:
    bid, chs = _book(client, 2, "替换")
    r = client.get(f"/api/books/{bid}/search", params={"q": "赵管事", "scope": "chapters"}).json()
    assert r["total"] == 16
    skip = [f"{h['scope']}:{h['id']}:{h['field']}:{h['offset']}" for h in r["hits"][:1]]
    assert client.post(f"/api/books/{bid}/replace", json={"q": "赵管事", "replacement": "钱管事", "expect": 3}).status_code == 409
    out = client.post(f"/api/books/{bid}/replace", json={"q": "赵管事", "replacement": "钱管事", "expect": 16, "skip": skip}).json()
    assert out["replaced"] == 15 and out["changed"]["chapters"] == 2
    ch = client.get(f"/api/chapters/{chs[0]['id']}").json()
    assert ch["content"].count("赵管事") == 1 and ch["history"] >= 1
    assert client.get(f"/api/books/{bid}/search", params={"q": "(", "regex": True}).status_code == 422
    r = client.post(f"/api/books/{bid}/replace", json={"q": r"(钱)管事", "replacement": r"\1长老", "regex": True}).json()
    assert r["replaced"] == 15
    # 笔记
    n = client.post(f"/api/books/{bid}/notes", json={"title": "残卷规则", "folder": "设定", "content": "一天最多看三次破绽", "tags": ["金手指"]}).json()
    assert client.get(f"/api/books/{bid}/notes", params={"q": "破绽"}).json()[0]["id"] == n["id"]
    client.put(f"/api/books/{bid}/notes/{n['id']}", json={"pinned": True})
    md = client.get(f"/api/books/{bid}/notes/export").text
    assert "## 设定" in md and "### 残卷规则" in md
    assert client.post(f"/api/books/{bid}/notes/import", json={"text": md}).json()["created"] == 1
    refs = client.get(f"/api/books/{bid}/refs", params={"q": "笔记:残"}).json()
    assert any(x["name"] == "笔记:残卷规则" for x in refs)
    from app.db import session_scope
    from app.services.refs import refs_block

    with session_scope() as s:
        blk = refs_block(s, bid, "按 @笔记:残卷规则 写，参考 @第1章摘要 和 @书名")
    assert "一天最多看三次破绽" in blk and "〔书名〕" in blk
    assert client.delete(f"/api/books/{bid}/notes/{n['id']}").json()["ok"]


def test_vars_and_context(client: Any) -> None:
    bid, chs = _book(client, 3, "变量")
    wait_job(client, client.post(f"/api/books/{bid}/adopt").json())
    r = client.post(f"/api/books/{bid}/vars/resolve", json={"text": "看 @第1章正文 @第1-2章摘要 @第1章正文 @目标字数"}).json()
    labels = [u["label"] for u in r["used"]]
    assert labels.count("第1章正文") == 1 and any("摘要" in x for x in labels) and "目标字数" in labels
    pv = client.get(f"/api/books/{bid}/context-preview", params={"chapter_id": chs[2]["id"]}).json()
    labs = [b["label"] for b in pv["blocks"]]
    assert "最近章节摘要" in labs
    client.put(f"/api/books/{bid}/context-exclude", json={"blocks": ["最近章节摘要", "本章写作任务"]})
    pv2 = client.get(f"/api/books/{bid}/context-preview", params={"chapter_id": chs[2]["id"]}).json()
    assert pv2["exclude"] == ["最近章节摘要"] and next(b for b in pv2["blocks"] if b["label"] == "最近章节摘要")["excluded"]
    from app.db import session_scope
    from app.models.tables import Chapter, OutlineNode
    from app.services import common
    from app.services.context import build_context_pack

    with session_scope() as s:
        ch = s.get(Chapter, chs[2]["id"])
        node = s.get(OutlineNode, ch.outline_node_id)
        pack = build_context_pack(s, common.get_book(s, bid), node)
    assert "【最近章节摘要】" not in pack.suffix


def test_spark_flow(client: Any) -> None:
    t = client.get("/api/spark/tracks", params={"gender": "male"}).json()
    assert t["tracks"] and t["tag_groups"]
    sid = client.post("/api/spark/sessions", json={"gender": "male", "track": "玄幻", "tags": ["系统"]}).json()["id"]
    assert client.post(f"/api/spark/sessions/{sid}/proposal").status_code == 200  # 任务会失败：还没选
    for axis in ("world", "hero", "cheat"):
        d = wait_job(client, client.post(f"/api/spark/sessions/{sid}/draw", json={"axis": axis}).json())["result"]
        cards = d["cards"][axis]
        assert len(cards) == 9 and all("similarity" in c for c in cards)
        keep = [cards[0]["id"]]
        d = wait_job(client, client.post(f"/api/spark/sessions/{sid}/draw", json={"axis": axis, "keep": keep}).json())["result"]
        assert d["cards"][axis][0]["id"] == keep[0] and len(d["cards"][axis]) == 9
        client.post(f"/api/spark/sessions/{sid}/pick", json={"axis": axis, "card_id": keep[0]})
    d = wait_job(client, client.post(f"/api/spark/sessions/{sid}/proposal").json())["result"]
    p = d["proposal"]
    assert len(p["titles"]) == 9 and p["seed_cards"] and p["completeness"] >= 80
    client.patch(f"/api/spark/sessions/{sid}/proposal", json={"title": p["titles"][1]["title"]})
    idea_id = client.post(f"/api/spark/sessions/{sid}/adopt").json()["idea_id"]
    book = client.post(f"/api/ideas/{idea_id}/adopt").json()
    cards = client.get(f"/api/books/{book['id']}/cards").json()
    assert {c["type"] for c in cards} >= {"world", "cheat", "character"}
    assert book["title"] == p["titles"][1]["title"]


def test_fanfic_three_step_and_oc(client: Any) -> None:
    from test_v010 import _source

    cat = client.get("/api/fanfic/directions").json()
    ids = [d["id"] for d in cat["directions"]]
    assert {"multi_transmigration", "reverse_transmigration", "revival", "unfinished"} <= set(ids)
    assert all(d["slots"] for d in cat["directions"]) and len(cat["povs"]) == 5
    sysd = next(d for d in cat["directions"] if d["id"] == "system")
    assert not any("代价" in t and "上限" not in t for t in sysd["tips"])
    src = _source(client)
    r = client.post("/api/books", json={
        "title": "穿书测试", "genre": "同人", "copyright_ack": True, "target_words": 1_200_000, "chapter_words": 3000, "mode": "wanben", "volume_chapters": 50,
        "fanfic": {"source_id": src["id"], "direction": "transmigration", "fidelity": "moderate", "pov": "first",
                   "slots": {"s0": "外门杂役"}, "protagonist": {"source": "oc", "oc_type": "transmigrator", "name": "沈渡"}}})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["target_words"] == 1_200_000 and b["chapter_words"] == 3000
    ff = client.get(f"/api/books/{b['id']}/fanfic").json()["fanfic"]
    assert ff["protagonist"]["oc_type"] == "transmigrator" and ff["pov"] == "first" and ff["slots"] == {"s0": "外门杂役"}
    j = wait_job(client, client.post(f"/api/books/{b['id']}/fanfic/oc/generate").json())
    assert j["result"]["name"] == "沈渡"
    oc = next(c for c in client.get(f"/api/books/{b['id']}/cards").json() if c["name"] == "沈渡")
    assert oc["data"]["origin"] == "oc"
    ctx = client.get(f"/api/books/{b['id']}/fanfic/context").json()["text"]
    assert "原创主角" in ctx and "沈渡" in ctx and "第一人称" in ctx and "外门杂役" in ctx
    assert client.post("/api/books", json={"title": "x", "copyright_ack": True, "fanfic": {"source_id": src["id"], "direction": "nope"}}).status_code in (400, 422)


def test_power_cheat_migration(tmp_path: Any) -> None:
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.db import _migrate_cheat_cards
    from app.models.tables import Card

    eng = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Card(book_id=1, type="power", name="系统", summary="", data={"input": "签到", "growth": "升级"}))
        s.add(Card(book_id=1, type="power", name="境界", summary="", data={"levels": "一、二"}))
        s.commit()
    _migrate_cheat_cards(eng)
    with Session(eng) as s:
        got = {c.name: c.type for c in s.exec(select(Card))}
    assert got == {"系统": "cheat", "境界": "power"}
