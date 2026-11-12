"""v0.4：作品信息让 AI 改 + 下游影响/同步、设定库三模式与冲突审阅/快照回滚、大纲节点 AI 重写/撤回、
章节按要求改写/撤回、伏笔规划与手动管理、禁用套路。全部在 mock 模式下跑。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from fastapi.testclient import TestClient

from conftest import wait_job


def _book(client: TestClient, premise: str = "") -> int:
    b = client.post("/api/books", json={"title": "碎星拳神", "genre": "都市高武", "gender": "male",
                                         "premise": premise or "主角练成碎星神通，一套拳法打穿灰港城。\n卖点：拳法越打越强"}).json()
    client.patch(f"/api/books/{b['id']}", json={"tagline": "一拳碎星，靠『碎星神通』的拳法横扫全城"})
    return b["id"]


def _failed(client: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    for _ in range(400):
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("任务超时")


# ------------------------------------------------------------------ 1. 作品信息

def test_extract_terms() -> None:
    from app.services.book_edit import extract_terms

    t = extract_terms("不要强调拳法，不要非叫『碎星神通』")
    assert "拳法" in t and "碎星神通" in t
    assert extract_terms("别再叫“老周”了") == ["老周"]


def test_book_revise_preview_apply_undo_and_sync(client: TestClient) -> None:
    bid = _book(client)
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    cards = client.get(f"/api/books/{bid}/cards").json()
    hero = next(c for c in cards if c["type"] == "character")
    client.put(f"/api/cards/{hero['id']}", json={"summary": "主角，靠碎星神通的拳法起家。"})
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    root = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "book")
    client.put(f"/api/outline/{root['id']}", json={"summary": "主角以碎星神通的拳法，从码头打到全城。"})

    before = client.get(f"/api/books/{bid}").json()
    assert before["premise"] and before["versions"] == 1  # 上面 PATCH tagline 记了一个手动版本
    ins = "不要强调拳法，不要非叫『碎星神通』"
    r = wait_job(client, client.post(f"/api/books/{bid}/revise", json={"instruction": ins}).json())["result"]
    assert r["current"]["tagline"] == before["tagline"]
    assert "碎星神通" not in r["proposal"]["tagline"] and "拳法" not in r["proposal"]["premise"]
    assert set(r["terms"]) >= {"拳法", "碎星神通"}
    imp = r["impact"]
    assert any(c["id"] == hero["id"] for c in imp["cards"])
    assert any(n["id"] == root["id"] for n in imp["outline"])
    # 预览不落库
    assert client.get(f"/api/books/{bid}").json()["tagline"] == before["tagline"]

    # 采纳 → 版本 +1 → 撤回
    applied = client.post(f"/api/books/{bid}/info", json={**r["proposal"], "instruction": ins}).json()
    assert applied["tagline"] == r["proposal"]["tagline"] and applied["versions"] == 2 and applied["last_instruction"] == ins
    undone = client.post(f"/api/books/{bid}/undo").json()
    assert undone["tagline"] == before["tagline"] and undone["versions"] == 1
    client.post(f"/api/books/{bid}/info", json={**r["proposal"], "instruction": ins})

    # 单独查影响
    imp2 = client.post(f"/api/books/{bid}/impact", json={"terms": ["碎星神通"]}).json()
    assert imp2["total"] >= 2

    # 交给 AI 同步：设定走冲突审阅，大纲给逐条修改
    sj = wait_job(client, client.post(f"/api/books/{bid}/sync", json={"instruction": ins, "terms": r["terms"],
                                                                        "replacements": r["replacements"]}).json())["result"]
    bible = sj["bible"]
    assert bible and bible["mode"] == "optimize"
    upd = next(x for x in bible["items"] if x["target_id"] == hero["id"])
    assert upd["action"] == "update" and "碎星神通" not in upd["card"]["summary"] and upd["old"]["summary"].startswith("主角")
    out = client.post(f"/api/books/{bid}/bible/apply", json={"mode": "sync", "instruction": ins,
                                                            "ops": [{"op": "update", "card_id": hero["id"], "card": upd["card"]}]}).json()
    assert out["updated"] == 1 and out["snapshot_id"]
    items = sj["outline"]["items"]
    node_item = next(x for x in items if x["node_id"] == root["id"])
    assert "碎星神通" not in node_item["new"]["summary"]
    res = client.post(f"/api/books/{bid}/outline/apply", json={"instruction": ins, "items": [
        {"node_id": x["node_id"], **x["new"]} for x in items]}).json()
    assert res["updated"] == len(items)
    root2 = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["id"] == root["id"])
    assert "碎星神通" not in root2["summary"] and root2["versions"] >= 2
    # 同步后下游不再命中（章节还没写）
    left = client.post(f"/api/books/{bid}/impact", json={"terms": ["碎星神通"]}).json()
    assert not any(c["id"] == hero["id"] for c in left["cards"])
    assert client.post(f"/api/books/{bid}/undo").json()["versions"] >= 1


# ------------------------------------------------------------------ 2. 设定库三模式

def test_bible_modes_conflicts_and_snapshots(client: TestClient) -> None:
    bid = _book(client, "普通人意外拿到账簿系统")
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    cards = client.get(f"/api/books/{bid}/cards").json()
    n0 = len(cards)

    # 纯增加：一张干净新卡 + 同名冲突 + 重复金手指冲突
    p = wait_job(client, client.post(f"/api/books/{bid}/bible/propose", json={"mode": "add", "instruction": "加个茶馆掌柜"}).json())["result"]
    clean = [x for x in p["items"] if not x["conflicts"]]
    review = [x for x in p["items"] if x["conflicts"]]
    assert clean and len(review) >= 2
    reasons = " ".join(c["reason"] for x in review for c in x["conflicts"])
    assert "同名" in reasons and "金手指" in reasons
    assert all(x["action"] == "add" for x in p["items"])
    assert len(client.get(f"/api/books/{bid}/cards").json()) == n0  # 预览不落库
    same = next(x for x in review if any("同名" in c["reason"] for c in x["conflicts"]))
    old_id = same["conflicts"][0]["card_id"]
    # 只采纳干净新卡 + 同名那条“两者都留”
    out = client.post(f"/api/books/{bid}/bible/apply", json={"mode": "add", "ops": [
        {"op": "create", "card": clean[0]["card"]}, {"op": "create", "card": same["card"]}]}).json()
    assert out["created"] == 2
    names = [c["name"] for c in client.get(f"/api/books/{bid}/cards").json()]
    assert len(names) == n0 + 2 and len(set(names)) == len(names)  # 同名自动加后缀
    snap_add = out["snapshot_id"]

    # 优化：改写已有卡（update）+ 新增
    p = wait_job(client, client.post(f"/api/books/{bid}/bible/propose", json={"mode": "optimize", "instruction": "更具体"}).json())["result"]
    ups = [x for x in p["items"] if x["action"] == "update"]
    assert ups and all(x["old"] and x["target_id"] for x in ups) and all(x["default"] == "replace" for x in ups)
    # 删掉旧的：旧卡删、新卡新建
    out = client.post(f"/api/books/{bid}/bible/apply", json={"mode": "optimize", "ops": [
        {"op": "delete", "card_id": ups[0]["target_id"]}, {"op": "create", "card": ups[0]["card"]}]}).json()
    assert out["deleted"] == 1 and out["created"] == 1

    # 完全重写：预览 → 旧卡里没对应的给出删除清单 → 应用 → 快照回滚
    p = wait_job(client, client.post(f"/api/books/{bid}/bible/propose", json={"mode": "rewrite", "instruction": "整体换成冷峻风格"}).json())["result"]
    assert p["mode"] == "rewrite" and p["removals"] and all(x["action"] == "add" for x in p["items"])
    assert any(x["target_id"] for x in p["items"])  # 同名视为替换
    ops: list[dict[str, Any]] = []
    for x in p["items"]:
        ops.append({"op": "update", "card_id": x["target_id"], "card": x["card"]} if x["target_id"] else {"op": "create", "card": x["card"]})
    ops += [{"op": "delete", "card_id": r["card_id"]} for r in p["removals"]]
    before = client.get(f"/api/books/{bid}/cards").json()
    out = client.post(f"/api/books/{bid}/bible/apply", json={"mode": "rewrite", "instruction": "整体换成冷峻风格", "ops": ops, "facts": p["facts"]}).json()
    after = client.get(f"/api/books/{bid}/cards").json()
    assert all("冷峻" in c["summary"] for c in after)
    snaps = client.get(f"/api/books/{bid}/bible/snapshots").json()
    assert snaps[0]["id"] == out["snapshot_id"] and snaps[0]["count"] == len(before)
    client.post(f"/api/books/{bid}/bible/snapshots/{out['snapshot_id']}/restore")
    restored = client.get(f"/api/books/{bid}/cards").json()
    assert sorted((c["id"], c["summary"]) for c in restored) == sorted((c["id"], c["summary"]) for c in before)
    # 回滚本身也留了快照
    assert client.get(f"/api/books/{bid}/bible/snapshots").json()[0]["note"].startswith("回滚")
    assert any(s["id"] == snap_add for s in client.get(f"/api/books/{bid}/bible/snapshots").json())
    bad = client.post(f"/api/books/{bid}/bible/apply", json={"ops": [{"op": "update", "card_id": 999999, "card": {"type": "world", "name": "x"}}]})
    assert bad.status_code == 404
    assert client.post(f"/api/books/{bid}/bible/propose", json={"mode": "nope"}).status_code == 422


def test_conflict_detection_unit() -> None:
    from app.models.tables import Card
    from app.services.bible_ops import detect_conflicts

    ex = [Card(id=1, book_id=1, type="cheat", name="账簿系统"), Card(id=2, book_id=1, type="character", name="老周")]
    assert detect_conflicts({"type": "character", "name": "老周", "summary": ""}, ex, None)[0]["card_id"] == 2
    assert "金手指" in detect_conflicts({"type": "cheat", "name": "回声", "summary": ""}, ex, None)[0]["reason"]
    assert detect_conflicts({"type": "cheat", "name": "账簿系统", "summary": ""}, ex, 1) == []
    assert detect_conflicts({"type": "location", "name": "码头", "summary": ""}, ex, None) == []


# ------------------------------------------------------------------ 3. 大纲节点

def test_outline_node_ai_rewrite_and_undo(client: TestClient) -> None:
    bid = _book(client, "普通人当上码头账房")
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    nodes = client.get(f"/api/books/{bid}/outline").json()
    for level in ("book", "volume", "arc"):
        n = next(x for x in nodes if x["level"] == level)
        r = wait_job(client, client.post(f"/api/outline/{n['id']}/suggest", json={"instruction": "冲突更狠"}).json())["result"]
        assert r["current"]["summary"] == n["summary"] and "冲突更狠" in r["proposal"]["summary"]
        assert client.get(f"/api/books/{bid}/outline").json()[nodes.index(n)]["summary"] == n["summary"]  # 不落库
        saved = client.put(f"/api/outline/{n['id']}", json={**r["proposal"], "instruction": "冲突更狠"}).json()
        assert saved["summary"] == r["proposal"]["summary"] and saved["versions"] == 1 and saved["last_instruction"] == "冲突更狠"
        manual = client.put(f"/api/outline/{n['id']}", json={"summary": "作者手写的概要"}).json()
        assert manual["versions"] == 2 and manual["last_instruction"] == "手动修改"
        back = client.post(f"/api/outline/{n['id']}/undo").json()
        assert back["summary"] == r["proposal"]["summary"] and back["versions"] == 1
        back = client.post(f"/api/outline/{n['id']}/undo").json()
        assert back["summary"] == n["summary"]
        assert client.post(f"/api/outline/{n['id']}/undo").status_code == 409


# ------------------------------------------------------------------ 4. 章节按要求改写 / 5. 伏笔

def test_chapter_rewrite_and_foreshadows(client: TestClient) -> None:
    bid = _book(client, "普通人当上码头账房，靠账簿系统催债")
    # 写章前：伏笔为空，但细纲里已经安排了
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    assert client.get(f"/api/books/{bid}/foreshadows").json() == []
    ov = client.get(f"/api/books/{bid}/foreshadows/overview").json()
    assert ov["committed"] == 0 and len(ov["outline_planned"]) >= 2

    # AI 规划伏笔 → 勾选加入（写进细纲）
    pj = wait_job(client, client.post(f"/api/books/{bid}/foreshadows/plan", json={"instruction": "多埋长线", "count": 3}).json())["result"]
    assert len(pj["items"]) == 3 and all(x["plant_ch"] and x["resolve_ch"] > x["plant_ch"] for x in pj["items"])
    assert client.get(f"/api/books/{bid}/foreshadows").json() == []  # 预览不落库
    first = pj["items"][0]
    assert first["plant_ch"] == 1
    added = client.post(f"/api/books/{bid}/foreshadows/batch", json={"items": pj["items"][:2], "attach": True}).json()
    assert added["created"] == 2 and added["attached"] >= 2
    fos = client.get(f"/api/books/{bid}/foreshadows").json()
    assert all(f["status"] == "planned" and f["source"] == "ai" and f["plan_plant_ch"] for f in fos)
    ch1_node = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "chapter" and n["order"] == 1)
    assert any(a["desc"] == first["desc"] and a["action"] == "plant" for a in ch1_node["beats"]["foreshadow"])

    # 手动新增 / 编辑 / 标记回收 / 删除
    m = client.post(f"/api/books/{bid}/foreshadows", json={"desc": "墙上那道刀痕", "tier": "short", "plan_plant_ch": 2}).json()
    assert m["status"] == "planned" and m["source"] == "manual"
    m2 = client.put(f"/api/foreshadows/{m['id']}", json={"status": "planted", "planted_ch": 2}).json()
    assert m2["status"] == "planted" and m2["last_ch"] == 2
    m3 = client.put(f"/api/foreshadows/{m['id']}", json={"status": "resolved", "resolved_ch": 6}).json()
    assert m3["resolved_ch"] == 6 and m3["last_ch"] == 6
    assert client.put(f"/api/foreshadows/{m['id']}", json={"desc": "  "}).status_code == 400
    assert client.delete(f"/api/foreshadows/{m['id']}").json() == {"ok": True}
    assert client.delete(f"/api/foreshadows/{m['id']}").status_code == 404

    # 写第 1 章并提交：计划中的伏笔转为已埋
    r = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
    cid = r["chapter_id"]
    if not r["committed"]:
        client.post(f"/api/chapters/{cid}/commit")
    fos = {f["desc"]: f for f in client.get(f"/api/books/{bid}/foreshadows").json()}
    assert fos[first["desc"]]["status"] == "planted" and fos[first["desc"]]["planted_ch"] == 1
    assert sum(1 for f in fos.values() if f["desc"] == first["desc"]) == 1  # 没有重复登记

    # 按要求改写：全章
    ch = client.get(f"/api/chapters/{cid}").json()
    hist0 = ch["history"]
    rw = wait_job(client, client.post(f"/api/chapters/{cid}/rewrite", json={"instruction": "节奏加快，对话多一点"}).json())["result"]
    assert rw["changed"] and rw["before"] == ch["content"] and rw["after"] != ch["content"]
    assert client.get(f"/api/chapters/{cid}").json()["content"] == ch["content"]  # 不落库
    ap = client.post(f"/api/chapters/{cid}/apply-rewrite", json={"content": rw["after"]}).json()
    assert ap["content"] == rw["after"] and ap["history"] == hist0 + 1 and ap["lint"]
    # 选中段落改写
    start = ap["content"].index("。") + 1
    end = start + 40
    rs = wait_job(client, client.post(f"/api/chapters/{cid}/rewrite", json={"instruction": "这一段改得更紧", "scope": "selection",
                                                                           "start": start, "end": end}).json())["result"]
    assert rs["after"][:start] == ap["content"][:start] and rs["after"].endswith(ap["content"][end:])
    bad = _failed(client, client.post(f"/api/chapters/{cid}/rewrite", json={"instruction": "x", "scope": "selection", "start": 5, "end": 5}).json())
    assert bad["status"] == "failed" and "范围" in bad["error"]
    # 撤回
    un = client.post(f"/api/chapters/{cid}/undo").json()
    assert un["content"] == ch["content"] and un["history"] == hist0
    # 人味修整也进历史，可撤回
    wait_job(client, client.post(f"/api/chapters/{cid}/humanize").json())
    h = client.get(f"/api/chapters/{cid}").json()
    if h["content"] != ch["content"]:
        assert h["history"] == hist0 + 1 and h["last_history_label"] == "人味修整前"
    # 指定不存在的模型 → 失败而不是悄悄走 mock
    jf = _failed(client, client.post(f"/api/chapters/{cid}/rewrite", json={"instruction": "x", "route": "999:nope"}).json())
    assert jf["status"] == "failed" and "不可用" in jf["error"]


# ------------------------------------------------------------------ 6. 禁用套路

def test_tropes_settings_detection_and_replace(client: TestClient) -> None:
    from app.services import tropes

    st = client.get("/api/settings/tropes").json()
    names = [t["name"] for t in st["banned"]]
    assert any("父母失踪" in n for n in names) and any("血脉" in n for n in names) and any("退婚" in n for n in names)

    # 提示词注入 + 作者明确想要时豁免
    tl = st["banned"]
    block = tropes.prompt_block(tl, "")
    assert "去套路" in block and "退婚" in block
    assert "退婚流" not in tropes.prompt_block(tl, "我就想写退婚流，开局被退婚")
    assert "退婚流" in tropes.prompt_block(tl, "不要退婚，换个开局")
    assert "退婚流" in tropes.prompt_block(tl, tropes.replace_instruction([{"name": "退婚流", "hits": ["退婚"]}, {"name": "神秘血脉", "hits": ["血脉之力"]}]))
    from app.skills.loader import load_pack
    assert "去套路" in load_pack("ideation").body and "去套路" in load_pack("bible").body

    # 选题：命中标黄 → 一键换掉 → 不再命中，可撤回
    ids = wait_job(client, client.post("/api/ideas/generate", json={"gender": "male", "count": 3}).json())["result"]["idea_ids"]
    iid = ids[0]
    client.patch(f"/api/ideas/{iid}", json={"logline": "父亲失踪多年，主角觉醒神秘血脉，一路打脸。"})
    idea = client.get(f"/api/ideas/{iid}").json()
    hit_names = {h["name"] for h in idea["trope_hits"]}
    assert any("父母失踪" in n for n in hit_names) and "神秘血脉" in hit_names
    assert any(i["id"] == iid and i["trope_hits"] for i in client.get("/api/ideas").json())
    wait_job(client, client.post(f"/api/ideas/{iid}/detrope", json={}).json())
    idea2 = client.get(f"/api/ideas/{iid}").json()
    assert idea2["trope_hits"] == [] and idea2["versions"] == idea["versions"] + 1
    assert client.post(f"/api/ideas/{iid}/detrope", json={}).status_code == 409

    # 全局列表可编辑；每本书可追加
    custom = [*tl, {"name": "系统签到", "keywords": "签到系统，每日签到"}]
    saved = client.put("/api/settings/tropes", json={"banned": [{"name": "系统签到", "keywords": ["签到系统", "每日签到"]}, *tl]}).json()
    assert saved["banned"][0] == {"name": "系统签到", "keywords": ["签到系统", "每日签到"]}
    assert custom  # 字符串关键词由 clean() 拆分
    assert tropes.clean([{"name": "x", "keywords": "甲，乙、丙"}])[0]["keywords"] == ["甲", "乙", "丙"]
    bid = _book(client, "普通人当上码头账房")
    b = client.patch(f"/api/books/{bid}", json={"banned_tropes": [{"name": "赘婿", "keywords": ["赘婿", "上门女婿"]}]}).json()
    assert b["banned_tropes"] == [{"name": "赘婿", "keywords": ["赘婿", "上门女婿"]}]
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    card = client.get(f"/api/books/{bid}/cards").json()[0]
    client.put(f"/api/cards/{card['id']}", json={"summary": "上门女婿出身，每日签到。"})
    c2 = next(c for c in client.get(f"/api/books/{bid}/cards").json() if c["id"] == card["id"])
    assert {h["name"] for h in c2["trope_hits"]} >= {"赘婿", "系统签到"}
    # 一键换掉：整张卡 AI 改（结果回填编辑器，不落库）
    fix = wait_job(client, client.post(f"/api/books/{bid}/cards/suggest", json={
        "card_id": card["id"], "instruction": tropes.replace_instruction(c2["trope_hits"]), "draft": {}}).json())["result"]["card"]
    assert "上门女婿" not in fix["summary"] and "每日签到" not in fix["summary"]
    client.put("/api/settings/tropes", json={"banned": tl})


# ------------------------------------------------------------------ 迁移：旧库加列

def test_migration_adds_columns_with_empty_json(tmp_path: Any) -> None:
    from app.config import Settings
    from app.db import _add_missing_columns
    from sqlmodel import create_engine

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE book (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, genre VARCHAR NOT NULL, gender VARCHAR NOT NULL,
          tagline VARCHAR NOT NULL, premise TEXT NOT NULL, status VARCHAR NOT NULL, target_words INTEGER NOT NULL,
          chapter_words INTEGER NOT NULL, cover_url VARCHAR, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
        INSERT INTO book VALUES (1,'旧书','','male','','','idea',1000000,2200,NULL,'2026-01-01','2026-01-01');
        CREATE TABLE foreshadow (id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, "desc" VARCHAR NOT NULL, status VARCHAR NOT NULL,
          planted_ch INTEGER NOT NULL, last_ch INTEGER NOT NULL, resolved_ch INTEGER);
        INSERT INTO foreshadow VALUES (1,1,'旧伏笔','planted',1,1,NULL);
    """)
    con.commit()
    con.close()
    _ = Settings
    eng = create_engine(f"sqlite:///{db}")
    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(eng)
    _add_missing_columns(eng)
    con = sqlite3.connect(db)
    row = con.execute("SELECT versions, banned_tropes FROM book WHERE id=1").fetchone()
    assert row == ("[]", "[]")
    f = con.execute("SELECT tier, plan_plant_ch, plan_resolve_ch, note, source FROM foreshadow WHERE id=1").fetchone()
    assert f[0] == "" and f[1] is None and f[2] is None and f[3] == "" and f[4] in ("chapter", "")
    con.close()


def test_foreshadow_bugfixes_string_beats_and_commit_fallback(client: TestClient) -> None:
    """旧版前端把细纲里的列表存成 JSON 字符串 → 伏笔和出场人物丢失；变更声明漏了细纲安排的伏笔 → 伏笔页一直空。"""
    import json as _json

    from app.db import session_scope
    from app.models.tables import Chapter

    bid = _book(client, "普通人当上码头账房")
    wait_job(client, client.post(f"/api/books/{bid}/bible/generate").json())
    wait_job(client, client.post(f"/api/books/{bid}/outline/generate").json())
    node = next(n for n in client.get(f"/api/books/{bid}/outline").json() if n["level"] == "chapter" and n["order"] == 1)
    beats = {k: (v if isinstance(v, str) else _json.dumps(v, ensure_ascii=False)) for k, v in node["beats"].items()}
    beats["foreshadow"] = _json.dumps([*node["beats"]["foreshadow"], {"action": "plant", "id": None, "desc": "柜台下压着的半张欠条"}], ensure_ascii=False)
    saved = client.put(f"/api/outline/{node['id']}", json={"beats": beats}).json()
    assert isinstance(saved["beats"]["foreshadow"], list) and len(saved["beats"]["foreshadow"]) == 2
    assert saved["beats"]["characters"] == node["beats"]["characters"]

    ws = client.get("/api/settings/writing").json()
    client.put("/api/settings/writing", json={"auto_commit": False})
    try:
        r = wait_job(client, client.post(f"/api/books/{bid}/chapters/write-next").json(), timeout=120)["result"]
    finally:
        client.put("/api/settings/writing", json={"auto_commit": ws["auto_commit"]})
    assert r["committed"] is False
    with session_scope() as s:  # 模拟模型漏写变更声明里的伏笔
        ch = s.get(Chapter, r["chapter_id"])
        assert ch is not None
        ch.changes = {"new_entities": [], "state_changes": [], "foreshadow": [], "warnings": []}
        s.add(ch)
        s.commit()
    c = client.post(f"/api/chapters/{r['chapter_id']}/commit").json()
    assert c["status"] == "committed"
    fos = client.get(f"/api/books/{bid}/foreshadows").json()
    descs = {f["desc"]: f for f in fos}
    assert "柜台下压着的半张欠条" in descs and descs["柜台下压着的半张欠条"]["source"] == "outline"
    assert descs["柜台下压着的半张欠条"]["status"] == "planted" and "核对" in descs["柜台下压着的半张欠条"]["note"]
    assert any("变更声明漏了" in w for w in c["changes"]["warnings"])
