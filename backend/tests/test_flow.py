"""mock 模式全流程：选题 → 采纳 → 设定 → 大纲 → 风格卡 → 写 3 章 → 多版本/精修 → 包装 → 封面 → 导出 zip。"""

from __future__ import annotations

import io
import time as _time
import zipfile

from fastapi.testclient import TestClient

from conftest import wait_job

SAMPLE = ("雨下到半夜才停。陈默把车停在巷口，熄了火，没急着下去，先摇下半扇车窗，听了听巷子深处的动静。"
          "铁皮棚上还在滴水，一下接一下砸在空油桶上。\n\n"
          "“你来晚了。”老板娘把卷帘门拉起一半，弯腰钻出来，围裙上全是面粉。\n\n"
          "陈默拎着两袋冻货走过去，鞋底在湿地上打滑。“路上封了一段，绕的。”\n\n"
          "她接过一袋掂了掂，眉头皱起来：“少了两斤。”陈默没解释，从兜里摸出一张收据递过去，"
          "收据被雨水泡得发软，字迹晕开了一半。\n\n") * 8


def test_health_and_status(client: TestClient) -> None:
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["version"]
    assert client.get("/api/settings/status").json() == {"mock_mode": True}


def test_full_mock_pipeline(client: TestClient) -> None:
    # 雷达（默认关闭 → mock）
    j = wait_job(client, client.post("/api/radar/refresh").json())
    assert j["result"]["source"] == "mock"
    latest = client.get("/api/radar/latest", params={"gender": "male"}).json()
    assert latest["snapshot"]["source"] == "mock" and latest["items"]
    assert all(i["gender"] == "male" for i in latest["items"])
    trends = client.get("/api/radar/trends").json()
    assert trends and {"category", "heat", "books", "rising", "sample_titles"} <= set(trends[0])
    assert len(client.get("/api/radar/snapshots").json()) >= 1

    # 选题 → 采纳
    j = wait_job(client, client.post("/api/ideas/generate", json={"gender": "male", "from_trends": True, "count": 3}).json())
    ids = j["result"]["idea_ids"]
    assert len(ids) == 3
    ideas = client.get("/api/ideas").json()
    idea = next(i for i in ideas if i["id"] == ids[0])
    assert set(idea["scores"]) == {"heat", "novelty", "fit", "overall"}
    # 按意见修改 → 撤回
    other = ids[1]
    old = next(i for i in ideas if i["id"] == other)
    j = wait_job(client, client.post(f"/api/ideas/{other}/revise", json={"instruction": "主角换成武道高考生"}).json())
    assert j["status"] == "succeeded", j
    rev = next(i for i in client.get("/api/ideas").json() if i["id"] == other)
    assert rev["versions"] == 1 and rev["last_instruction"] == "主角换成武道高考生" and rev["logline"] != old["logline"]
    bad = client.post(f"/api/ideas/{other}/revise", json={"instruction": "x", "route": "999:nope"}).json()
    for _ in range(200):
        jb = client.get(f"/api/jobs/{bad['id']}").json()
        if jb["status"] in ("succeeded", "failed"):
            break
        _time.sleep(0.05)
    assert jb["status"] == "failed" and "不可用" in (jb["error"] or "")
    back = client.post(f"/api/ideas/{other}/undo").json()
    assert back["logline"] == old["logline"] and back["versions"] == 0
    # 详情页：单项建议（不落库）→ 手动保存 → 重新打分
    one = client.get(f"/api/ideas/{other}").json()
    sj = wait_job(client, client.post(f"/api/ideas/{other}/suggest", json={"field": "selling_points", "instruction": "更爽", "draft": {"hook": "草稿钩子"}}).json())
    assert sj["result"]["field"] == "selling_points" and len(sj["result"]["value"]) == len(one["selling_points"])
    assert client.get(f"/api/ideas/{other}").json()["selling_points"] == one["selling_points"]
    up = client.patch(f"/api/ideas/{other}", json={"title": "《我的新书名》", "arc": ["一", " ", "二"]}).json()
    assert up["title"] == "我的新书名" and up["arc"] == ["一", "二"] and up["versions"] == 1
    wait_job(client, client.post(f"/api/ideas/{other}/rescore").json())
    book = client.post(f"/api/ideas/{idea['id']}/adopt").json()
    assert book["status"] == "bible" and book["stats"] == {"chapters": 0, "words": 0, "foreshadow_open": 0}
    bid = book["id"]

    # 设定
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    cards = client.get(f"/api/books/{bid}/cards").json()
    chars = [c for c in cards if c["type"] == "character"]
    assert len(chars) >= 3 and all(c["data"].get("voice") for c in chars)
    assert client.get(f"/api/books/{bid}/cards", params={"type": "power"}).json()[0]["data"]["cost"]
    assert len(client.get(f"/api/books/{bid}/facts").json()) >= 3

    # 大纲
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    nodes = client.get(f"/api/books/{bid}/outline").json()
    levels = {n["level"] for n in nodes}
    assert levels == {"book", "volume", "arc", "chapter"}
    assert client.get(f"/api/books/{bid}").json()["status"] == "outline"

    # 风格卡
    st = client.put(f"/api/books/{bid}/style", json={"sample_text": SAMPLE, "voice_notes": "少用形容词", "pov": "third", "tone": "冷峻"}).json()
    assert st["extracted"] is None
    wait_job(client, client.post(f"/api/books/{bid}/style/extract").json())
    st = client.get(f"/api/books/{bid}/style").json()
    ex = st["extracted"]
    assert ex["stats"]["avg_sentence_len"] > 0 and 800 <= ex["excerpt_words"] <= 1700
    assert client.put(f"/api/books/{bid}/style", json={"sample_text": "字" * 5001}).status_code == 400

    # 写 3 章（第 1 章单独，后 2 章批量）
    j = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)
    r = j["result"]
    assert r["committed"] is True and r["rewrite_round"] == 1  # mock 初稿故意留了问题 → 走一轮定点重写
    ch1 = client.get(f"/api/chapters/{r['chapter_id']}").json()
    assert ch1["status"] == "committed" and ch1["number"] == 1 and ch1["words"] > 1000
    assert "嘴角勾起一抹" not in ch1["content"]  # 定点重写去掉了模板表情
    assert ch1["review"]["passed"] and all(i["quote"] for i in ch1["review"]["issues"])
    lint = ch1["lint"]
    for k in ("avg_sentence_len", "short_sentence_ratio", "bare_dialogue_ratio", "summary_ratio", "ai_score"):
        assert isinstance(lint[k], (int, float))
    assert lint["avg_sentence_len"] > 10
    assert len(ch1["variants"]) == 1
    assert "林" in ch1["content"] or ch1["content"]

    j = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-batch", json={"count": 2}).json(), timeout=180)
    assert j["result"]["stopped"] is False and len(j["result"]["chapter_ids"]) == 2
    chapters = client.get(f"/api/books/{bid}/chapters").json()
    assert [c["number"] for c in chapters] == [1, 2, 3]
    assert all("content" not in c for c in chapters)
    assert all(c["status"] == "committed" for c in chapters)

    # 底账：伏笔、事实、新实体
    fos = client.get(f"/api/books/{bid}/foreshadows").json()
    assert len(fos) >= 2 and all(f["planted_ch"] in (1, 2) for f in fos)
    facts = client.get(f"/api/books/{bid}/facts").json()
    assert any(f["from_chapter"] == 3 for f in facts)
    closed = [f for f in facts if f["to_chapter"] is not None]
    assert closed, "同一实体同一状态的旧事实应被关闭"
    assert any(c["name"] == "斗笠客" for c in client.get(f"/api/books/{bid}/cards").json())
    b = client.get(f"/api/books/{bid}").json()
    assert b["status"] == "writing" and b["stats"]["chapters"] == 3 and b["stats"]["foreshadow_open"] >= 1
    written = [n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "chapter" and n["status"] == "written"]
    assert len(written) == 3 and all(n["chapter_id"] for n in written)
    assert all(3 <= len(n["beats"]["scenes"]) <= 6 for n in written)

    # 第 4 章：多版本（2），默认不自动采纳 → 草稿等作者挑
    j = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next", json={"variants": 2}).json(), timeout=180)
    r = j["result"]
    assert r["awaiting_adopt"] is True and r["committed"] is False
    ch4 = client.get(f"/api/chapters/{r['chapter_id']}").json()
    assert ch4["status"] == "draft" and len(ch4["variants"]) == 2
    assert {"id", "content", "words", "lint", "review_overall"} <= set(ch4["variants"][0])
    facts_before = len(client.get(f"/api/books/{bid}/facts").json())
    # 草稿不入底账；未提交时不能写下一章
    resp = client.post(f"/api/books/{bid}/chapters/write-next").json()
    jj = client.get(f"/api/jobs/{resp['id']}").json()
    import time
    for _ in range(100):
        jj = client.get(f"/api/jobs/{resp['id']}").json()
        if jj["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert jj["status"] == "failed" and "尚未提交" in jj["error"]
    adopted = client.post(f"/api/chapters/{ch4['id']}/adopt-variant", json={"variant_id": 1}).json()
    assert adopted["status"] == "reviewing" and adopted["content"] == ch4["variants"][0]["content"]
    assert len(client.get(f"/api/books/{bid}/facts").json()) == facts_before

    # 精修：thicken 只改裸对白/概述段落，复跑 lint
    before = adopted["lint"]
    j = wait_job(client, client.post(f"/api/chapters/{ch4['id']}/thicken").json())
    assert j["result"]["located"] >= 1 and j["result"]["rewritten"] >= 1
    after = client.get(f"/api/chapters/{ch4['id']}").json()
    assert after["lint"]["bare_dialogue_ratio"] <= before["bare_dialogue_ratio"]
    assert after["lint"]["summary_ratio"] < before["summary_ratio"]
    assert "经过一番周旋" not in after["content"]
    assert after["content"] != adopted["content"]
    wait_job(client, client.post(f"/api/chapters/{ch4['id']}/humanize").json())
    wait_job(client, client.post(f"/api/chapters/{ch4['id']}/review").json())
    committed = client.post(f"/api/chapters/{ch4['id']}/commit").json()
    assert committed["status"] == "committed"

    # 人工修改
    edited = client.put(f"/api/chapters/{ch4['id']}", json={"title": "改过的标题"}).json()
    assert edited["title"] == "改过的标题"

    # 大纲滚动展开：展开一个弧节点
    arc = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "volume" and n["order"] == 2)
    wait_job(client, client.post(f"/api/outline/{arc['id']}/expand").json())
    assert any(n["parent_id"] == arc["id"] for n in client.get(f"/api/books/{bid}/outline").json())

    # 包装 → 封面 → 导出
    wait_job(client, client.post(f"/api/books/{bid}/package/generate").json())
    pkg = client.get(f"/api/books/{bid}/package").json()
    assert pkg["titles"] and pkg["blurb"] and pkg["tags"] and pkg["cover_prompt"]
    assert pkg["titles"] == sorted(pkg["titles"], key=lambda t: -t["score"])
    j = wait_job(client, client.post(f"/api/books/{bid}/covers/generate", json={"n": 2}).json())
    pkg = client.get(f"/api/books/{bid}/package").json()
    assert len(pkg["covers"]) == 2 and pkg["chosen_cover"] == pkg["covers"][0]
    img = client.get(pkg["covers"][1])
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    assert Image.open(io.BytesIO(img.content)).size == (600, 800)
    pkg = client.put(f"/api/books/{bid}/package", json={"chosen_cover": pkg["covers"][1], "blurb": "新简介"}).json()
    assert pkg["chosen_cover"].endswith("_2.png") and pkg["blurb"] == "新简介"
    assert client.get(f"/api/books/{bid}").json()["cover_url"] == pkg["chosen_cover"]
    assert client.get(f"/api/books/{bid}").json()["status"] == "packaging"

    z = client.get(f"/api/books/{bid}/export")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "建书资料.md" in names and "cover.png" in names and "AI申报提示.md" in names
    assert len([n for n in names if n.startswith("chapters/") and n.endswith(".txt")]) == 4
    notice = zipfile.ZipFile(io.BytesIO(z.content)).read("AI申报提示.md").decode()
    assert "如实勾选" in notice

    jobs = client.get("/api/jobs", params={"book_id": bid}).json()
    assert jobs and jobs[0]["id"] > jobs[-1]["id"]


def test_channels_routing_and_masking(client: TestClient) -> None:
    c = client.post("/api/settings/channels", json={"name": "测试", "base_url": "http://127.0.0.1:9/v1",
                                                     "api_key": "sk-abcdefghijklmnop", "models": ["m1"]}).json()
    assert c["api_key_masked"] == "sk-****mnop" and "api_key" not in c
    assert client.get("/api/settings/status").json()["mock_mode"] is False
    assert client.put("/api/settings/routing", json={"writer": f"{c['id']}:m1"}).json()["writer"] == f"{c['id']}:m1"
    assert client.put("/api/settings/routing", json={"writer": "999:m1"}).status_code == 400
    t = client.post(f"/api/settings/channels/{c['id']}/test").json()
    assert t["ok"] is False and "latency_ms" in t
    upd = client.put(f"/api/settings/channels/{c['id']}", json={"enabled": False}).json()
    assert upd["enabled"] is False and upd["api_key_masked"] == "sk-****mnop"
    assert client.get("/api/settings/status").json()["mock_mode"] is True
    assert client.delete(f"/api/settings/channels/{c['id']}").json() == {"ok": True}
    assert client.get("/api/settings/routing").json()["writer"] is None
    # 密钥落库是密文
    from app.db import session_scope
    from app.models.tables import Channel
    from sqlmodel import select
    with session_scope() as s:
        assert all("abcdefgh" not in (x.api_key_enc or "") for x in s.exec(select(Channel)).all())


def test_writing_settings_auto_adopt(client: TestClient) -> None:
    w = client.get("/api/settings/writing").json()
    assert w == {"auto_adopt_best": False, "auto_commit": True, "default_variants": 1}
    w = client.put("/api/settings/writing", json={"auto_adopt_best": True}).json()
    assert w["auto_adopt_best"] is True
    book = client.post("/api/books", json={"genre": "悬疑灵异", "gender": "male", "premise": "能听见死者最后十秒的声音"}).json()
    bid = book["id"]
    assert book["status"] == "idea"
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    j = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next", json={"variants": 3}).json(), timeout=180)
    r = j["result"]
    assert r["committed"] is True and r["adopted_variant"] in (1, 2, 3)
    ch = client.get(f"/api/chapters/{r['chapter_id']}").json()
    best = max(ch["variants"], key=lambda v: v["review_overall"])
    assert ch["variants"][r["adopted_variant"] - 1]["review_overall"] == best["review_overall"]
    client.put("/api/settings/writing", json={"auto_adopt_best": False})
    assert client.delete(f"/api/books/{bid}").json() == {"ok": True}
    assert client.get(f"/api/books/{bid}").status_code == 404


def test_errors_are_detail_json(client: TestClient) -> None:
    r = client.get("/api/books/99999")
    assert r.status_code == 404 and "detail" in r.json()
    r = client.post("/api/books/99999/chapters/write-next")
    assert r.status_code == 404
    r = client.post("/api/books", json={"gender": "x"})
    assert r.status_code == 422 and "detail" in r.json()
