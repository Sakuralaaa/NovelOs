"""v0.12 E1 导入已有作品：切章（纯函数）、DOCX/TXT 样例、导入建书、接管旧书（分批/暂停/续跑/冲突审阅）、
接着续写、大纲文本导入。全部走 mock LLM，不做真实网络与模型调用。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import wait_job

FIX = Path(__file__).parent / "fixtures"


def _wait_any(client: TestClient, job_id: int, timeout: float = 120) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed", "interrupted"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"任务超时：{job_id}")


def _novel(n: int = 50, volumes: int = 2) -> str:
    per = max(1, n // volumes)
    out = ["书名：《雪夜灯》", "作者：测试", "简介：冰封的城里，一家只换不卖的超市。", ""]
    k = 0
    for v in range(volumes):
        out.append(f"第{'一二三四五'[v]}卷 卷{v + 1}")
        cnt = per if v < volumes - 1 else n - per * (volumes - 1)
        for _ in range(cnt):
            k += 1
            out.append(f"第{k}章 标题{k}")
            out += [f"林野说道：“第{k}章第{i}句，账本不能丢。”苏晚看着他。林野笑了。" for i in range(20)]
    return "\n".join(out) + "\n"


def _commit(client: TestClient, text: str, title: str = "") -> dict[str, Any]:
    p = client.post("/api/import/preview", json={"text": text, "filename": "雪夜灯.txt"})
    assert p.status_code == 200, p.text
    pv = p.json()
    body = {"title": title or pv["title_guess"], "genre": "末世", "premise": pv["premise_guess"],
            "chapters": [{"title": c["title"], "content": c["content"], "volume": c["volume"]} for c in pv["chapters"]],
            "volume_intros": pv["volume_intros"], "source": {"format": pv["format"], "filename": "雪夜灯.txt", "rule": pv["rule"]}}
    r = client.post("/api/import/commit", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ================================================================== 切章：纯函数

def test_cn2int() -> None:
    from app.services.import_text import cn2int

    assert cn2int("十二") == 12 and cn2int("一百零三") == 103 and cn2int("二十") == 20
    assert cn2int("两千零五") == 2005 and cn2int("０１２") == 12 and cn2int("一二三") == 123
    assert cn2int("一万零一") == 10001 and cn2int("abc") is None and cn2int("") is None


def test_split_common_formats() -> None:
    from app.services.import_text import split_text

    t = ("书名：《雪夜灯》\n简介：守夜人的故事。\n\n第一卷 冰城\n卷首语在这里。\n第一章 风起\n林野推开门。\n"
         "第2章：灯\n苏晚说话了。\n【第三章】旧账\n第三回合开始了，他喊道。\n第五节课很无聊。\n"
         "第二卷 北上\n第 4 章\n北上。\nChapter 5 Snow\n雪。\n番外 春天\n春天来了。\n")
    r = split_text(t)
    assert r["rule"] == "auto"
    assert [c["title"] for c in r["chapters"]] == ["风起", "灯", "旧账", "", "Snow", "春天"]
    assert [c["num"] for c in r["chapters"]] == [1, 2, 3, 4, 5, None]
    assert [c["volume"] for c in r["chapters"]] == ["第一卷 冰城"] * 3 + ["第二卷 北上"] * 3
    assert r["volume_intros"] == {"第一卷 冰城": "卷首语在这里。"}
    assert "第三回合开始了" in r["chapters"][2]["content"] and "第五节课很无聊" in r["chapters"][2]["content"]  # 正文不误切
    assert r["preface"].startswith("书名")
    assert [c["volume"] for c in split_text(t, split_volumes=False)["chapters"]] == [""] * 6


def test_split_fallbacks_and_custom_pattern() -> None:
    from app.services.import_text import ImportError_, compile_pattern, split_text

    r = split_text("001 开端\n正文a\n002 继续\n正文b\n003 结束\n正文c\n")
    assert r["rule"] == "numbered" and [c["title"] for c in r["chapters"]] == ["开端", "继续", "结束"]
    # 不连续的序号行是正文列表，不切
    assert split_text("清单：\n1. 面包\n7. 牛奶\n3. 罐头\n")["rule"] == "none"
    r = split_text("# 风起\n林野。\n# 旧账\n金牙。\n", headings=["风起", "旧账"])
    assert r["rule"] == "headings" and [c["title"] for c in r["chapters"]] == ["风起", "旧账"]
    r = split_text("☆风起\n林野。\n☆旧账\n金牙。\n☆雪线\n雪。", pattern=r"^☆")
    assert r["rule"] == "custom" and len(r["chapters"]) == 3 and r["chapters"][1]["title"] == "☆旧账"
    r = split_text("没有任何标题的一段文字。\n第二段。")
    assert r["rule"] == "none" and len(r["chapters"]) == 1 and r["chapters"][0]["raw_title"] == "全文"
    with pytest.raises(ImportError_):
        compile_pattern("第(章")
    with pytest.raises(ImportError_):
        compile_pattern("x" * 300)


def test_flag_chapters() -> None:
    from app.services.import_text import flag_chapters

    body = "林野推开门，风雪灌进来。" * 40
    chs = [{"title": "风起", "raw_title": "第1章 风起", "num": 1, "content": body},
           {"title": "旧账", "raw_title": "第2章 旧账", "num": 2, "content": body + "多一句。"},
           {"title": "旧账", "raw_title": "第2章 旧账", "num": 2, "content": body + "多一句。"},
           {"title": "空", "raw_title": "第5章 空", "num": 5, "content": "请假"},
           {"title": "长", "raw_title": "第6章 长", "num": 6, "content": body * 30}]
    f = flag_chapters(chs)
    assert f[0] == [] and f[1] == []
    assert "dup_title" in f[2] and "dup_content" in f[2]
    assert "empty" in f[3] and "gap" in f[3]
    assert "long" in f[4]


def test_docx_sample() -> None:
    from app.services.import_text import preview

    p = preview(data=(FIX / "import_sample.docx").read_bytes(), filename="import_sample.docx")
    assert p["format"] == "docx" and p["rule"] == "auto"
    assert p["title_guess"] == "雪夜灯" and "只换不卖" in p["premise_guess"]
    assert [c["title"] for c in p["chapters"]] == ["风起", "旧账", "雪线"]
    assert p["volumes"] == ["第一卷 冰城", "第二卷 北上"] and p["chapters"][2]["volume"] == "第二卷 北上"
    assert p["volume_intros"]["第一卷 冰城"].startswith("卷首")
    assert "卷帘门" in p["chapters"][0]["content"] and "“只换不卖。”" in p["chapters"][0]["content"]
    # 标题不是「第X章」格式：按 Word 标题样式切
    p = preview(data=(FIX / "import_headings.docx").read_bytes(), filename="import_headings.docx")
    assert p["rule"] == "headings" and [c["title"] for c in p["chapters"]] == ["风起", "旧账", "雪线"]
    assert any("标题样式" in w for w in p["warnings"])


def test_txt_encoding_and_errors() -> None:
    from app.services.import_text import ImportError_, preview

    p = preview(data=(FIX / "import_sample_gbk.txt").read_bytes(), filename="import_sample_gbk.txt")
    assert p["encoding"] == "gb18030" and p["title_guess"] == "雪夜灯"
    assert [c["num"] for c in p["chapters"]] == [1, 2, 3] and "罐头" in p["chapters"][2]["content"]
    with pytest.raises(ImportError_):
        preview(data=b"\xd0\xcf\x11\xe0", filename="old.doc")
    with pytest.raises(ImportError_):
        preview(data=b"PK\x03\x04broken", filename="bad.docx")
    with pytest.raises(ImportError_):
        preview(text="   \n  ")


def test_parse_outline() -> None:
    from app.services.import_text import parse_outline

    r = parse_outline("总纲：主角复仇。\n第一卷 起\n第1章 开局：主角醒来\n被追杀\n第2章 反击：打脸\n第二卷 承\n第3章 新城")
    assert r["book"]["summary"] == "总纲：主角复仇。" and r["chapters"] == 3
    assert [v["title"] for v in r["volumes"]] == ["第一卷 起", "第二卷 承"]
    c1 = r["volumes"][0]["arcs"][0]["chapters"][0]
    assert c1 == {"number": 1, "title": "开局", "goal": "主角醒来；被追杀"}
    r = parse_outline("1. 开局：醒来\n2、反击：打脸\n3) 收尾")
    assert [c["number"] for c in r["volumes"][0]["arcs"][0]["chapters"]] == [1, 2, 3]


# ================================================================== 接口

def test_preview_api(client: TestClient) -> None:
    r = client.post("/api/import/preview", files={"file": ("import_sample.docx", (FIX / "import_sample.docx").read_bytes(),
                                                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    assert len(r.json()["chapters"]) == 3 and r.json()["flag_labels"]["gap"]
    r = client.post("/api/import/preview", files={"file": ("a.txt", "第1章 甲\n正文\n第2章 乙\n正文".encode("gb18030"), "text/plain")},
                    data={"split_volumes": "0", "pattern": ""})
    assert r.status_code == 200 and len(r.json()["chapters"]) == 2
    assert client.post("/api/import/preview", json={"text": "☆甲\n正文\n☆乙\n正文", "pattern": "^☆"}).json()["rule"] == "custom"
    assert client.post("/api/import/preview", json={"text": "x", "pattern": "第(章"}).status_code == 422
    assert client.post("/api/import/preview", json={"text": ""}).status_code == 422
    assert client.post("/api/import/preview", files={"file": ("a.doc", b"\xd0\xcf\x11\xe0", "application/msword")}).status_code == 422
    assert client.post("/api/import/commit", json={"title": "x", "chapters": [{"title": "a", "content": "  "}]}).status_code == 422
    assert client.post("/api/import/commit", json={"title": "x", "chapters": []}).status_code == 422


def test_commit_builds_book_outline_and_style(client: TestClient) -> None:
    r = _commit(client, _novel(12, 2))
    bid = r["book_id"]
    assert r["chapters"] == 12 and r["volumes"] == 2 and r["book"]["status"] == "writing"
    assert r["book"]["title"] == "雪夜灯" and r["book"]["premise"].startswith("冰封")
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert [c["number"] for c in chs] == list(range(1, 13)) and all(c["status"] == "committed" for c in chs)
    assert chs[0]["title"] == "标题1" and chs[0]["words"] > 100
    nodes = client.get(f"/api/books/{bid}/outline").json()
    levels = [n["level"] for n in nodes]
    assert levels.count("book") == 1 and levels.count("volume") == 2 and levels.count("chapter") == 12
    cont = [n for n in nodes if n["level"] == "arc" and n["status"] == "planned"]
    assert len(cont) == 1 and cont[0]["title"].startswith("接续")
    assert all(n["status"] == "written" for n in nodes if n["level"] == "chapter")
    assert client.get(f"/api/books/{bid}/style").json()["sample_text"]
    st = client.get(f"/api/books/{bid}/adopt").json()
    assert st["imported"]["chapters"] == 12 and st["imported"]["format"] == "paste"
    assert st["can_continue"] and st["next_chapter"] == 13 and not st["complete"]
    assert client.get("/api/books/999999/adopt").status_code == 404
    # 不是导入的书：没有导入记录
    b = client.post("/api/books", json={"title": "原创", "genre": "都市", "gender": "male"}).json()
    assert client.post(f"/api/books/{b['id']}/adopt", json={}).status_code == 409


def test_adopt_full_then_continue_writing(client: TestClient) -> None:
    """路线图验收：导入 50 章 → 接管产出设定卡、账本与细纲 → 续写第 51 章，写前核对没有底账类报错。"""
    bid = _commit(client, _novel(50, 2))["book_id"]
    est = client.post(f"/api/books/{bid}/adopt/estimate", json={}).json()
    assert est["calls_est"] == 50 + 5 + 50 + 5 and est["input_tokens_est"] > 0 and est["model"] == "mock"
    assert [x["step"] for x in est["steps"]] == ["summary", "bible", "ledger", "outline"]
    j = _wait_any(client, client.post(f"/api/books/{bid}/adopt", json={}).json()["id"])
    assert j["status"] == "succeeded", j
    res = j["result"]
    assert res["units_total"] == 110 and not res["stopped"] and res["stats"]["summary"] == 50 and res["stats"]["outline"] == 50
    st = client.get(f"/api/books/{bid}/adopt").json()
    assert st["complete"] and all(x["covered_to"] == 50 for x in st["steps"])
    assert client.post(f"/api/books/{bid}/adopt/estimate", json={}).json()["calls_est"] == 0  # 都做完了，不再计费
    cards = client.get(f"/api/books/{bid}/cards").json()
    assert any(c["name"] == "林野" for c in cards) and any(c["type"] == "world" for c in cards)
    facts = client.get(f"/api/books/{bid}/facts").json()
    assert facts and {f["from_chapter"] for f in facts} >= {1, 50}
    fos = client.get(f"/api/books/{bid}/foreshadows").json()
    assert fos and any(f["status"] == "resolved" for f in fos)
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert all(c["summary"] for c in chs) if "summary" in chs[0] else True
    ch10 = client.get(f"/api/chapters/{chs[9]['id']}").json()
    assert ch10["changes"]["adopted"] is True
    nodes = [n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "chapter"]
    assert all(n["beats"].get("goal") and n["beats"].get("hook_type") for n in nodes)
    # 再跑一次：全部跳过
    j2 = _wait_any(client, client.post(f"/api/books/{bid}/adopt", json={}).json()["id"])
    assert j2["result"]["units_total"] == 0
    # 接着写第 51 章
    w = _wait_any(client, client.post(f"/api/books/{bid}/chapters/write-next", json={}).json()["id"])
    assert w["status"] == "succeeded", w
    assert w["result"]["number"] == 51
    pre = w["result"].get("preflight") or []
    assert not [x for x in pre if "章没动静" in x or "已登记为" in x or "伏笔池里找不到" in x], pre
    chs = client.get(f"/api/books/{bid}/chapters").json()
    assert chs[-1]["number"] == 51


def test_adopt_batches_pause_and_resume(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import kv_set, session_scope
    from app.services import import_book as ib

    bid = _commit(client, _novel(20, 1))["book_id"]
    # 分批：先只做 1–8 章的摘要
    j = _wait_any(client, client.post(f"/api/books/{bid}/adopt", json={"from": 1, "to": 8, "steps": ["summary"], "batch_size": 4}).json()["id"])
    assert j["result"]["units_total"] == 8
    st = client.get(f"/api/books/{bid}/adopt").json()
    assert st["steps"][0]["done"] == 8 and st["steps"][0]["covered_to"] == 8 and st["steps"][2]["done"] == 0
    assert client.post(f"/api/books/{bid}/adopt", json={"from": 9, "to": 3}).status_code == 400
    assert client.post(f"/api/books/{bid}/adopt", json={"steps": ["nope"]}).status_code == 422

    # 暂停：第 3 个单元开始前收到暂停请求
    class Ctx:
        job_id, book_id, resume_state = 0, bid, None
        calls = 0

        def progress(self, pct: int, message: str = "") -> None:
            Ctx.calls += 1
            if Ctx.calls == 3:
                with session_scope() as s:
                    kv_set(s, f"adopt_stop:{bid}", True)

        def checkpoint(self, *a: Any, **k: Any) -> None:
            pass

    params = {"from": 1, "to": 20, "steps": ["summary", "ledger"], "batch_size": 5}
    r = ib.adopt_job(bid, params, Ctx())  # type: ignore[arg-type]
    assert r["stopped"] and r["units_done"] == 3 and "暂停" in r["message"]
    st = client.get(f"/api/books/{bid}/adopt").json()
    assert not st["stop_requested"]
    done_ledger = st["steps"][2]["done"]
    assert done_ledger >= 1
    # 接着跑：只做剩下的
    j = _wait_any(client, client.post(f"/api/books/{bid}/adopt", json={"steps": ["summary", "ledger"], "batch_size": 5}).json()["id"])
    assert j["result"]["units_total"] == (20 - 8 - (3 - done_ledger)) + (20 - done_ledger)
    # pause 接口：没有在跑的任务
    assert client.post(f"/api/books/{bid}/adopt/pause").json() == {"ok": True, "running": False}

    # 失败后续跑：反推细纲第二批抛错 → 任务失败（有断点）→ /jobs/{id}/resume 从没做完的单元继续
    real = ib._outline_unit
    hits = {"n": 0}

    def flaky(book_id: int, numbers: list[int]) -> int:
        hits["n"] += 1
        if hits["n"] == 2:
            raise RuntimeError("渠道抖了一下")
        return real(book_id, numbers)

    monkeypatch.setattr(ib, "_outline_unit", flaky)
    j = _wait_any(client, client.post(f"/api/books/{bid}/adopt", json={"steps": ["outline"], "batch_size": 5}).json()["id"])
    assert j["status"] == "failed" and j["resumable"], j
    st = client.get(f"/api/books/{bid}/adopt").json()
    assert st["steps"][3]["done"] == 5
    r = client.post(f"/api/jobs/{j['id']}/resume")
    assert r.status_code == 200, r.text
    j = _wait_any(client, j["id"])
    assert j["status"] == "succeeded" and j["result"]["units_total"] == 3
    assert client.get(f"/api/books/{bid}/adopt").json()["steps"][3]["done"] == 20


def test_adopt_bible_conflicts_go_to_review(client: TestClient) -> None:
    bid = _commit(client, _novel(10, 1))["book_id"]
    # 作者自己先建了同名卡：接管不直接改，进冲突审阅
    c = client.post(f"/api/books/{bid}/cards", json={"type": "character", "name": "林野", "summary": "作者写的主角卡"})
    assert c.status_code == 200, c.text
    j = _wait_any(client, client.post(f"/api/books/{bid}/adopt", json={"steps": ["bible"], "batch_size": 10}).json()["id"])
    assert j["status"] == "succeeded", j
    assert j["result"]["stats"]["bible_review"] >= 1
    st = client.get(f"/api/books/{bid}/adopt").json()
    assert st["pending_review"] >= 1
    item = st["proposal"]["items"][0]
    assert item["target_id"] == c.json()["id"] and item["conflicts"] and item["default"] == "keep_old"
    card = next(x for x in client.get(f"/api/books/{bid}/cards").json() if x["name"] == "林野")
    assert card["summary"] == "作者写的主角卡"
    # 采纳走原有的 bible/apply（先存快照），然后清掉提案
    r = client.post(f"/api/books/{bid}/bible/apply", json={"mode": "optimize", "instruction": "接管",
                                                           "ops": [{"op": "update", "card_id": item["target_id"], "card": item["card"]}]})
    assert r.status_code == 200 and r.json()["updated"] == 1
    assert client.delete(f"/api/books/{bid}/adopt/proposal").json()["ok"]
    assert client.get(f"/api/books/{bid}/adopt").json()["pending_review"] == 0
    snaps = client.get(f"/api/books/{bid}/bible/snapshots").json()
    assert any("接管旧书" in s["note"] for s in snaps)


def test_outline_import_fill_and_append(client: TestClient) -> None:
    bid = _commit(client, _novel(5, 1))["book_id"]
    text = ("总纲：林野守住超市，查清旧账。\n第一卷 冰城\n第1章 风起：林野开门迎客\n第3章 旧账：金牙上门讨账\n"
            "第6章 反击：林野设局，金牙中计\n第7章 北上：苏晚要去北方\n第8章 雪线：车队出发")
    r = client.post(f"/api/books/{bid}/outline/import", json={"text": text})
    assert r.status_code == 200, r.text
    j = wait_job(client, r.json())
    pv = j["result"]
    assert pv["chapters"] == 5 and pv["suggest_mode"] == "fill" and any("已经写过" in w for w in pv["warnings"])
    a = client.post(f"/api/books/{bid}/outline/import/apply", json={"preview": pv["preview"], "mode": "fill"})
    assert a.status_code == 200, a.text
    assert a.json()["chapters_updated"] == 2 and a.json()["chapters_created"] == 3
    nodes = client.get(f"/api/books/{bid}/outline").json()
    chs = {n["order"]: n for n in nodes if n["level"] == "chapter"}
    assert chs[1]["status"] == "written" and chs[1]["beats"]["goal"] == "林野开门迎客" and chs[1]["title"] == "标题1"
    assert chs[6]["status"] == "planned" and chs[6]["title"] == "反击" and sorted(chs) == list(range(1, 9))
    assert any(n["level"] == "arc" and n["title"].startswith("接续") for n in nodes)
    # 续写直接用导入的第 6 章细纲
    w = _wait_any(client, client.post(f"/api/books/{bid}/chapters/write-next", json={}).json()["id"])
    assert w["status"] == "succeeded" and w["result"]["number"] == 6

    # 没有大纲的新书：append 建出整棵树
    b = client.post("/api/books", json={"title": "新书", "genre": "都市", "gender": "male"}).json()
    j = wait_job(client, client.post(f"/api/books/{b['id']}/outline/import", json={"text": "1. 开局：醒来\n2. 反击：打脸\n3. 收尾"}).json())
    assert j["result"]["suggest_mode"] == "append"
    a = client.post(f"/api/books/{b['id']}/outline/import/apply", json={"preview": j["result"]["preview"], "mode": "append"}).json()
    assert a["chapters_created"] == 3 and a["volumes"] == 1
    nodes = client.get(f"/api/books/{b['id']}/outline").json()
    assert [n["order"] for n in nodes if n["level"] == "chapter"] == [1, 2, 3]
    assert client.post(f"/api/books/{b['id']}/outline/import/apply", json={"preview": {}, "mode": "fill"}).status_code == 400
    assert client.post(f"/api/books/{b['id']}/outline/import/apply", json={"preview": {"volumes": []}, "mode": "x"}).status_code == 422
    assert client.post("/api/books/999999/outline/import", json={"text": "第1章 a"}).status_code == 404
