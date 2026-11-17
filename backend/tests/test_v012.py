"""v0.12：锁定与单卡版本、生成档案与成本、导入已有作品。"""

from __future__ import annotations

from typing import Any

from conftest import wait_job


def _book(client: Any, title: str = "v012") -> int:
    r = client.post("/api/books", json={"title": title, "genre": "玄幻", "gender": "male", "premise": "少年得残卷"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_card_lock_and_versions(client: Any) -> None:
    bid = _book(client)
    c = client.post(f"/api/books/{bid}/cards", json={"type": "character", "name": "林川", "summary": "主角"}).json()
    r = client.put(f"/api/cards/{c['id']}", json={"summary": "主角，外门弟子"})
    assert r.json()["versions"] == 1
    vs = client.get(f"/api/cards/{c['id']}/versions").json()
    assert vs[0]["summary"] == "主角" and vs[0]["label"] == "手动编辑"
    r = client.post(f"/api/cards/{c['id']}/versions/{vs[0]['n']}/restore")
    assert r.status_code == 200 and r.json()["summary"] == "主角"
    assert r.json()["versions"] == 2  # 回滚前也存了一版
    # 锁定后 AI 入口全部拒绝，手动编辑照常
    assert client.put(f"/api/cards/{c['id']}", json={"locked": True}).json()["locked"] is True
    assert client.post(f"/api/books/{bid}/bible/{c['id']}/field-ai", json={"field": "summary"}).status_code == 409
    assert client.post(f"/api/books/{bid}/cards/suggest", json={"card_id": c["id"], "instruction": "改狠一点"}).status_code == 409
    assert client.post(f"/api/books/{bid}/characters/{c['id']}/soul", json={}).status_code == 409
    assert client.put(f"/api/cards/{c['id']}", json={"summary": "手改可以"}).status_code == 200


def test_bible_apply_skips_locked(client: Any) -> None:
    from app.services import bible_ops

    bid = _book(client, "锁定批量")
    c = client.post(f"/api/books/{bid}/cards", json={"type": "faction", "name": "青云宗", "summary": "原样"}).json()
    client.put(f"/api/cards/{c['id']}", json={"locked": True})
    r = bible_ops.apply(bid, "optimize", "", [
        {"op": "update", "card_id": c["id"], "card": {"type": "faction", "name": "青云宗", "summary": "被改了"}},
        {"op": "delete", "card_id": c["id"]},
    ])
    assert r["skipped_locked"] == ["青云宗", "青云宗"] and r["updated"] == 0 and r["deleted"] == 0
    got = client.get(f"/api/books/{bid}/cards").json()
    assert [x["summary"] for x in got if x["id"] == c["id"]] == ["原样"]


def test_outline_lock(client: Any) -> None:
    bid = _book(client, "大纲锁定")
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    nodes = client.get(f"/api/books/{bid}/outline").json()
    ch = next(n for n in nodes if n["level"] == "chapter")
    assert client.put(f"/api/outline/{ch['id']}", json={"locked": True}).json()["locked"] is True
    assert client.post(f"/api/outline/{ch['id']}/suggest", json={"instruction": "快一点"}).status_code == 409
    assert client.post(f"/api/outline/{ch['id']}/expand").status_code == 409
    assert client.post(f"/api/books/{bid}/outline/generate").status_code == 409
    r = client.post(f"/api/books/{bid}/outline/apply", json={"instruction": "同步", "items": [{"node_id": ch["id"], "title": "改名"}]})
    assert r.json()["updated"] == 0


def test_generation_archive_followup_and_budget(client: Any) -> None:
    bid = _book(client, "档案")
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    lst = client.get("/api/generations", params={"book_id": bid}).json()
    assert lst["total"] >= 1 and lst["items"][0]["model"] == "mock" and lst["items"][0]["status"] == "ok"
    gid = lst["items"][0]["id"]
    full = client.get(f"/api/generations/{gid}").json()
    assert full["output"] and "prompt" in full
    assert client.patch(f"/api/generations/{gid}", json={"starred": True}).json()["starred"] is True
    assert client.get("/api/generations", params={"starred": True, "book_id": bid}).json()["total"] == 1
    j = wait_job(client, client.post(f"/api/generations/{gid}/followup", json={"instruction": "短一点"}).json())
    new_id = j["result"]["id"]
    assert new_id and new_id != gid
    kid = client.get(f"/api/generations/{new_id}").json()
    assert kid["parent_id"] == gid and kid["note"] == "短一点"
    assert client.get(f"/api/generations/{gid}").json()["output"] == full["output"]  # 原结果不被覆盖
    assert [k["id"] for k in client.get(f"/api/generations/{gid}").json()["children"]] == [new_id]
    # 预算
    b = client.put("/api/settings/budget", json={"daily_cny": 5, "book_cny": 0}).json()
    assert b["daily_cny"] == 5 and "today_cny" in b
    client.put("/api/settings/budget", json={"daily_cny": 0, "book_cny": 0})
    assert client.delete(f"/api/generations/{new_id}").json()["ok"] is True


def test_cost_and_budget_units() -> None:
    from app.llm import archive

    prices = {"m": {"in": 2, "out": 8}}
    assert archive.cost_cny(prices, "m", 1_000_000, 500_000) == 6.0
    assert archive.cost_cny(prices, "other", 1000, 1000) == 0.0
    assert archive.count_words("林川拔剑 abc 123") == 6


def test_channel_prices_roundtrip(client: Any) -> None:
    r = client.post("/api/settings/channels", json={"name": "价测", "base_url": "https://example.invalid/v1", "api_key": "sk-x",
                                                    "models": ["m1"], "enabled": False, "prices": {"m1": {"in": 1.5, "out": 6}}})
    assert r.status_code == 200 and r.json()["prices"] == {"m1": {"in": 1.5, "out": 6.0}}
    cid = r.json()["id"]
    r = client.put(f"/api/settings/channels/{cid}", json={"prices": {"m1": {"in": 0, "out": 3}, "": {"in": 1}}})
    assert r.json()["prices"] == {"m1": {"out": 3.0}}
    client.delete(f"/api/settings/channels/{cid}")


SAMPLE = """《残卷问道》
作者：某某

第一卷 外门

第1章 山门
雨落在青石板上，林川把剑往背后一收，抬头看了眼山门。""" + "他记得赵管事那张脸。" * 40 + """

第2章 残卷
林川在柴房里翻出一页残卷。""" + "字迹像是被血洇过。" * 40 + """

第二卷 内门

第3章 入内门
三个月后，林川站上了内门的演武台。""" + "台下有人冷笑。" * 40 + """

第5章 空
"""


def test_import_preview_commit_adopt(client: Any) -> None:
    r = client.post("/api/books/import", json={"text": SAMPLE})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["title"] == "残卷问道"
    assert [c["raw_title"] for c in pv["chapters"]] == ["第1章 山门", "第2章 残卷", "第3章 入内门", "第5章 空"]
    assert pv["volumes"] == ["第一卷 外门", "第二卷 内门"]
    assert pv["chapters"][2]["volume"] == "第二卷 内门"
    assert "第二卷" not in pv["chapters"][1]["preview"]
    last = pv["chapters"][3]
    assert "空章" in last["flags"] and any("跳到 5" in f for f in last["flags"])
    r = client.post("/api/books/import/commit", json={"import_id": pv["import_id"], "title": "残卷问道", "skip": [4]})
    assert r.status_code == 200, r.text
    bid = r.json()["book_id"]
    assert r.json()["chapters"] == 3
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert [c["status"] for c in chs] == ["committed"] * 3
    j = wait_job(client, client.post(f"/api/books/{bid}/adopt").json())
    assert j["result"]["summaries"] == 3 and j["result"]["cards"] >= 1
    st = client.get(f"/api/books/{bid}/adopt").json()
    assert st["summaries"] == 3 and st["outline_linked"] == 3
    nodes = client.get(f"/api/books/{bid}/outline").json()
    assert [n["title"] for n in nodes if n["level"] == "volume"] == ["第一卷 外门", "第二卷 内门"]
    # 重跑：摘要和大纲都不重复
    j = wait_job(client, client.post(f"/api/books/{bid}/adopt").json())
    assert j["result"]["summaries"] == 0 and j["result"]["outline_nodes"] == 0
    assert client.post("/api/books/import/commit", json={"import_id": pv["import_id"], "title": "x"}).status_code == 404


def test_import_docx() -> None:
    import io
    import zipfile

    from app.services import import_book

    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           '<w:p><w:r><w:t>第1章 开始</w:t></w:r></w:p><w:p><w:r><w:t>' + "正文。" * 120 + '</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>第2章 继续</w:t></w:r></w:p><w:p><w:r><w:t>' + "后文。" * 120 + '</w:t></w:r></w:p></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    pv = import_book.parse(data=buf.getvalue(), filename="书.docx")
    assert pv["encoding"] == "docx" and [c["title"] for c in pv["chapters"]] == ["开始", "继续"]
