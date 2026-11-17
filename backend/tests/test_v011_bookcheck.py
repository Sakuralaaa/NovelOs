"""v0.11 完本模式·质检：整书体检（规则层 + 模型层）、短剧分镜档、可改编度审读、同质化自查。

全部走项目已有的 mock LLM（没有配置渠道时网关自动用 mock），不发真实请求。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from conftest import wait_job

# 每章用不同的句子拼，避免被误判成重复章
_POOL = [
    "林川推开祠堂的门，烛火被风压得一低。", "“账本在哪？”他把刀拍在供桌上。", "三叔的手指在袖子里攥紧，指节发白。",
    "院子里的狗忽然不叫了，众人都转头看向门口。", "苏晚端着药碗进来，碗沿还冒着热气，她看了一眼刀。",
    "“你要是今天走出这扇门，就别再回林家。”", "林川没回头，弯腰把地上的碎瓷一片片捡起来。", "雨点砸在瓦上，像有人在屋顶上走。",
    "他数到第七片，抬头问：“那晚是谁守的夜？”", "顾长风把茶盏搁下，盏底磕出一声脆响。", "“是我。”角落里有人站了起来。",
    "那人的左手少了两根手指，袖口沾着没洗净的泥。", "林川盯着他看了很久，才把刀收回鞘里。", "苏晚忽然开口：“药凉了，先喝药。”",
    "他接过碗，一口没喝，把碗放在账本旁边。", "门外传来马蹄声，由远及近，在院门口停下。", "管家跑进来，脸色煞白，话都说不利索。",
    "“城里来人了，说要见二少爷。”", "林川站起身，把账本揣进怀里，往外走。", "三叔在他身后冷笑：“你以为你斗得过他们？”",
]


def _text(seed: int, n: int) -> str:
    """生成约 n 字、彼此不同的正文：轮换句子并插入章节专属的数字与名词。"""
    out: list[str] = []
    k = 0
    while sum(len(x) for x in out) < n:
        s = _POOL[(seed * 7 + k) % len(_POOL)]
        out.append(f"{s}第{seed}夜的第{k}更，{['东', '南', '西', '北', '中'][k % 5]}院{seed * 31 + k}号房的灯还亮着。")
        k += 1
    return "\n".join(out)


def _book(client: TestClient, title: str, **kw: Any) -> int:
    r = client.post("/api/books", json={"title": title, "genre": "都市高武", "gender": "male", **kw})
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _chapter(bid: int, number: int, content: str, title: str | None = None, status: str = "committed", summary: str = "") -> int:
    from app.db import session_scope
    from app.lint.humanlint import count_words
    from app.models.tables import Chapter

    with session_scope() as s:
        ch = Chapter(book_id=bid, number=number, title=title if title is not None else f"第{number}章 夜里的事", content=content,
                     words=count_words(content), status=status, summary=summary)
        s.add(ch)
        s.commit()
        s.refresh(ch)
        return int(ch.id or 0)


def _foreshadow(bid: int, desc: str, planted: int, tier: str = "long") -> None:
    from app.db import session_scope
    from app.models.tables import Foreshadow

    with session_scope() as s:
        s.add(Foreshadow(book_id=bid, desc=desc, status="planted", planted_ch=planted, last_ch=planted, tier=tier))
        s.commit()


def _seed_problem_book(client: TestClient) -> tuple[int, dict[int, int]]:
    """一本带各种问题的书：第 4 章缺号、第 3 章过短、第 6 章与第 2 章重复、第 7 章标题章号不符、末章停在悬念、长线伏笔未回收。"""
    bid = _book(client, "体检测试书")
    ids: dict[int, int] = {}
    for n in (1, 2, 5, 8):
        ids[n] = _chapter(bid, n, _text(n, 1600))
    ids[3] = _chapter(bid, 3, _text(3, 400))
    ids[6] = _chapter(bid, 6, _text(2, 1600))  # 与第 2 章一字不差
    ids[7] = _chapter(bid, 7, _text(7, 1600), title="第九章 错号")
    ids[9] = _chapter(bid, 9, _text(9, 1600) + "\n就在这时，门外有人喊出了那个名字——", title="第9章 门外")
    _foreshadow(bid, "祠堂暗格里的半块玉佩", 1, "long")
    return bid, ids


# ------------------------------------------------------------------ 整书体检

def test_book_check_rules_only(client: TestClient) -> None:
    bid, ids = _seed_problem_book(client)
    assert client.get(f"/api/books/{bid}/book-check").json() == {"report": None}
    job = client.post(f"/api/books/{bid}/book-check", json={"llm": False}).json()
    assert job["kind"] == "book_check" and job["job_id"] == job["id"]
    rep = wait_job(client, job)["result"]
    assert rep["verdict"] in ("ready", "fix_first", "not_ready") and 0 <= rep["score"] <= 100
    assert rep["llm"] == {"used": False}
    types = {i["type"] for i in rep["issues"]}
    assert {"number_gap", "short_chapter", "duplicate_chapter", "title_mismatch", "ending_open", "foreshadow_open"} <= types, types
    # 按严重度排序
    order = {"high": 0, "mid": 1, "low": 2}
    sev = [order[i["severity"]] for i in rep["issues"]]
    assert sev == sorted(sev)
    dup = next(i for i in rep["issues"] if i["type"] == "duplicate_chapter")
    assert dup["chapter"] == 6 and dup["related_chapters"] == [2] and dup["severity"] == "high"
    gap = next(i for i in rep["issues"] if i["type"] == "number_gap")
    assert gap["chapter"] == 4
    tm = next(i for i in rep["issues"] if i["type"] == "title_mismatch")
    assert tm["fixable"] and tm["fix"]["method"] == "PUT" and tm["fix"]["body"]["title"] == "第7章 错号"
    short = next(i for i in rep["issues"] if i["type"] == "short_chapter")
    assert short["chapter"] == 3 and short["fix"]["endpoint"] == f"/api/chapters/{ids[3]}/thicken"
    for i in rep["issues"]:
        assert set(i) >= {"id", "type", "type_label", "severity", "layer", "chapter", "evidence", "suggestion", "fixable", "fix"}
    st = rep["stats"]
    assert st["chapters"] == 8 and st["word_tier"]["tier"] == "below_15w" and st["word_tier"]["reference"] == [150000, 300000]
    assert "字数参考档位" in st["word_tier"]["label"] and st["short_chapters"] == 1 and st["open_foreshadows"] == 1
    assert st["ending"]["cliff"] is True and st["ending"]["closed"] is False
    assert rep["verdict"] != "ready"
    # 只做内容质量：不出现发文频率 / 合规 / AI 申报相关文案
    blob = str(rep)
    for w in ("发文频率", "更新频率", "合规", "AI 申报", "声明使用", "签约"):
        assert w not in blob
    # 一键修：改标题落到已有接口
    r = client.put(tm["fix"]["endpoint"], json=tm["fix"]["body"])
    assert r.status_code == 200 and r.json()["title"] == "第7章 错号"


def test_book_check_with_llm_latest_history(client: TestClient) -> None:
    bid, _ = _seed_problem_book(client)
    rep = wait_job(client, client.post(f"/api/books/{bid}/book-check").json())["result"]
    assert rep["llm"]["used"] is True and rep["llm"]["segments"] >= 1 and rep["llm"]["sent_chars"] > 0
    assert rep["llm"]["ending"]["rushed"] is True  # mock：末章没有收束标记 → 仓促
    assert any(i["layer"] == "llm" for i in rep["issues"])
    j2 = wait_job(client, client.post(f"/api/books/{bid}/book-check", json={"llm": False}).json())
    latest = client.get(f"/api/books/{bid}/book-check").json()["report"]
    assert latest["job_id"] == j2["id"] and latest["checked_at"] and latest["llm"]["used"] is False
    hist = client.get(f"/api/books/{bid}/book-check/history").json()["items"]
    assert len(hist) == 2 and hist[0]["job_id"] == j2["id"] and hist[1]["llm_used"] is True
    assert set(hist[0]) >= {"job_id", "created_at", "verdict", "score", "by_severity", "chapters", "total_words", "llm_used"}
    old = client.get(f"/api/books/{bid}/book-check", params={"job_id": hist[1]["job_id"]}).json()["report"]
    assert old["llm"]["used"] is True


def test_book_check_clean_book_and_errors(client: TestClient) -> None:
    bid = _book(client, "干净的书")
    for n in range(1, 4):
        _chapter(bid, n, _text(n + 40, 1500))
    _chapter(bid, 4, _text(50, 1500) + "\n多年以后，林川回到祠堂，把那半块玉佩放回了暗格。全书完。", title="第4章 尾声")
    rep = wait_job(client, client.post(f"/api/books/{bid}/book-check", json={"llm": False}).json())["result"]
    assert rep["stats"]["ending"]["closed"] is True
    assert not any(i["type"] in ("ending_open", "number_gap", "duplicate_chapter", "short_chapter") for i in rep["issues"])
    assert rep["score"] >= 80
    empty = _book(client, "空书")
    r = client.post(f"/api/books/{empty}/book-check", json={"llm": False}).json()
    t = r
    import time

    for _ in range(200):
        t = client.get(f"/api/jobs/{r['id']}").json()
        if t["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert t["status"] == "failed" and "没有写好的章节" in t["error"]
    assert client.post("/api/books/999999/book-check").status_code == 404
    assert client.get("/api/books/999999/book-check/history").status_code == 404


def test_book_check_units() -> None:
    from app.services import book_check as bc

    assert bc.word_tier(149_999)["tier"] == "below_15w"
    assert bc.word_tier(150_000)["tier"] == "15w_30w" and bc.word_tier(310_000)["tier"] == "above_30w"
    assert bc.word_tier(100_000)["to_next"] == 50_000
    chs = [{"id": i, "number": n, "title": t, "content": "x"} for i, (n, t) in enumerate([(1, "第一章 起"), (2, ""), (2, "第2章 承"), (5, "第五章 合")], 1)]
    types = [i["type"] for i in bc.numbering_issues(chs)]
    assert "number_duplicate" in types and "number_gap" in types and "title_missing" in types
    assert not any(i["type"] == "title_mismatch" for i in bc.numbering_issues(chs))  # 中文章号也能识别
    sc, v = bc.score_and_verdict([])
    assert (sc, v) == (100, "ready")
    many = [bc._issue("short_chapter", "high", n, "", "") for n in range(10)]
    sc, v = bc.score_and_verdict(many)
    assert sc == 80 and v == "not_ready"  # 同类封顶 20 分；高危 ≥5 → not_ready
    # 分段送模型：长书按预算切多段
    long_chs = [{"id": i, "number": i, "title": "", "content": "字" * 3000, "summary": "摘要" * 80} for i in range(1, 201)]
    segs = bc.build_segments(long_chs)
    assert len(segs) > 1 and segs[0]["start"] == 1 and segs[-1]["end"] == 200
    assert all(len(sg["text"]) <= bc.SEGMENT_CHARS + 2000 for sg in segs)


# ------------------------------------------------------------------ 短剧分镜风格档

def test_duanju_platform_style(client: TestClient) -> None:
    from app.skills.loader import system_prompt

    styles = client.get("/api/platform-styles").json()["items"]
    assert {"id": "duanju", "label": "短剧分镜", "optional": True} in styles
    bid = _book(client, "短剧书", platform_style="duanju")
    assert client.get(f"/api/books/{bid}").json()["platform_style"] == "duanju"
    assert client.patch(f"/api/books/{bid}", json={"platform_style": "fanqie"}).json()["platform_style"] == "fanqie"
    assert client.patch(f"/api/books/{bid}", json={"platform_style": "duanju"}).json()["platform_style"] == "duanju"
    p = system_prompt("writing_chapter", platform="duanju")
    assert "短剧分镜" in p and "前 100 字" in p and "番茄写法" in p and "起点写法" not in p
    assert "短剧分镜写法" not in system_prompt("writing_chapter", platform="fanqie")
    assert "短剧分镜写法" not in system_prompt("review", platform="duanju")  # 只挂在写作/细纲类任务上
    # 写章上下文按 duanju 档组装
    from app.db import session_scope
    from app.models.tables import Book, OutlineNode
    from app.services.context import build_context_pack

    with session_scope() as s:
        node = OutlineNode(book_id=bid, level="chapter", order=1, title="第1章", summary="开局", beats={})
        s.add(node)
        s.commit()
        s.refresh(node)
        pack = build_context_pack(s, s.get(Book, bid), node)
    assert "短剧分镜写法" in pack.prefix


def test_duanju_chapter_check(client: TestClient) -> None:
    from app.services.adaptability import duanju_check

    good = "“跪下！”林川一脚踹开祠堂的门。\n三叔的手抖了一下。\n“你敢——”他话没说完，门外有人喊出了那个名字——"
    r = duanju_check(good)
    assert r["opening_ok"] and r["ending_cliff"] and not r["issues"]
    slow = ("天空灰蒙蒙的，远处的山峦被雾气吞没，微风吹过树梢，落叶在街道上打着旋，夕阳把天边染成一片暗红，炊烟从屋顶升起。\n"
            "他心里想着这些年的事，内心五味杂陈，脑海里一遍遍回想那个雨夜，心中始终有一个解不开的结，他想不明白为什么那个人宁可死也不肯说出真相。\n"
            "后来他回家睡了。")
    r = duanju_check(slow)
    assert {i["type"] for i in r["issues"]} == {"opening_slow", "monologue", "scenery", "ending_flat"}
    bid = _book(client, "短剧自查书", platform_style="duanju")
    cid = _chapter(bid, 1, good)
    out = client.post(f"/api/chapters/{cid}/duanju-check").json()
    assert out["chapter_id"] == cid and out["number"] == 1 and out["opening_ok"] is True
    assert client.post("/api/chapters/999999/duanju-check").status_code == 404


# ------------------------------------------------------------------ 可改编度

def test_adaptability_job(client: TestClient) -> None:
    bid = _book(client, "改编测试书")
    for n in range(1, 6):
        _chapter(bid, n, "“跪下！”林川一脚踹开门。没想到，来的竟然是三叔。\n" + _text(n + 60, 1500) + "\n就在这时，门被推开了——")
    job = client.post(f"/api/books/{bid}/adaptability", json={"start": 2, "end": 4}).json()
    assert job["kind"] == "adaptability"
    rep = wait_job(client, job)["result"]
    assert rep["range"] == {"start": 2, "end": 4, "chapters": 3}
    assert 0 <= rep["score"] <= 10 and rep["episodes_per_chapter"] > 0 and rep["episodes_total"] > 0
    assert set(rep["dimensions"]) == {"persona", "conflict", "reversal", "shootability", "dialogue", "episodes"}
    for d in rep["dimensions"].values():
        assert 0 <= d["score"] <= 10 and d["llm_score"] is not None and d["label"]
    assert [m["chapter"] for m in rep["chapters"]] == [2, 3, 4]
    assert all(m["opening_ok"] and m["ending_cliff"] for m in rep["chapters"])
    assert rep["suggestions"] and rep["llm_used"] is True
    rules = wait_job(client, client.post(f"/api/books/{bid}/adaptability", json={"llm": False}).json())["result"]
    assert rules["range"]["chapters"] == 5 and all(d["llm_score"] is None for d in rules["dimensions"].values())
    latest = client.get(f"/api/books/{bid}/adaptability").json()["report"]
    assert latest["llm_used"] is False and latest["range"]["chapters"] == 5
    hist = client.get(f"/api/books/{bid}/adaptability/history").json()["items"]
    assert len(hist) == 2 and hist[1]["range"]["start"] == 2
    assert client.post(f"/api/books/{bid}/adaptability", json={"start": 5, "end": 2}).status_code == 422


# ------------------------------------------------------------------ 同质化自查

def _snapshot() -> None:
    from app.db import session_scope
    from app.models.tables import RadarSnapshot, RankItem

    with session_scope() as s:
        snap = RadarSnapshot(source="mock", items_count=3, version="test-v011")
        s.add(snap)
        s.commit()
        s.refresh(snap)
        for k, (t, cat, ab) in enumerate([
            ("被退婚后，我觉醒了吞天魔功", "玄幻脑洞", "少年被未婚妻当众退婚，觉醒系统，吞天魔功一路打脸逆袭。"),
            ("开局签到荒古圣体", "玄幻脑洞", "穿越而来，签到系统奖励荒古圣体，宗门废物逆袭。"),
            ("我在乡下开民宿", "都市日常", "辞职回乡开民宿，种菜养鸡，慢生活。"),
        ], 1):
            s.add(RankItem(snapshot_id=snap.id or 0, book_id_ext=f"v011-{k}", title=t, category=cat, rank=k, abstract=ab,
                           read_count=1000 - k, tags=["系统"] if k < 3 else ["种田"], gender="male", board="read"))
        s.commit()


def test_homogeneity_book_and_idea(client: TestClient) -> None:
    _snapshot()
    bid = _book(client, "被退婚后，我觉醒了吞天神功", tagline="少年被退婚，觉醒系统打脸逆袭", premise="废物少年觉醒吞天系统")
    out = client.post(f"/api/books/{bid}/homogeneity").json()
    assert out["mode"] == "sync"
    rep = out["report"]
    assert rep["target"] == {"type": "book", "id": bid, "title": "被退婚后，我觉醒了吞天神功"}
    assert rep["snapshot"]["items_compared"] >= 3
    top = rep["similar"][0]
    assert top["title"] == "被退婚后，我觉醒了吞天魔功" and top["title_overlap"] and "退婚" in top["shared_tropes"]
    assert rep["level"] in ("mid", "high") and rep["suggestions"] and rep["llm"] is None
    assert all(r["title"] != "我在乡下开民宿" for r in rep["similar"])
    job = client.post(f"/api/books/{bid}/homogeneity", json={"llm": True}).json()
    assert job["mode"] == "job" and job["job"]["kind"] == "homogeneity"
    rep2 = wait_job(client, job["job"])["result"]
    assert rep2["llm"]["overall"] and rep2["llm"]["suggestions"] and rep2["similar"][0]["llm_note"]

    from app.db import session_scope
    from app.models.tables import Idea

    with session_scope() as s:
        idea = Idea(title="开局签到混沌圣体", logline="穿越成宗门废物，签到系统奖励圣体", selling_points=["签到系统", "废物逆袭"], genre="玄幻脑洞")
        s.add(idea)
        s.commit()
        s.refresh(idea)
        iid = idea.id
    rep3 = client.post(f"/api/ideas/{iid}/homogeneity", json={"top_n": 10}).json()["report"]
    assert rep3["target"]["type"] == "idea" and rep3["similar"][0]["title"] == "开局签到荒古圣体"
    assert client.post("/api/ideas/999999/homogeneity").status_code == 404
