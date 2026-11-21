"""v0.19/v0.20 Agent 接入（MCP）与流式写作测试。"""

from __future__ import annotations

import json
from typing import Any


def rpc(client, method: str, params: dict[str, Any] | None = None, mid: int = 1, headers: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json(), dict(r.headers)


def call(client, _tool: str, **args: Any) -> tuple[bool, str]:
    body, _ = rpc(client, "tools/call", {"name": _tool, "arguments": args})
    res = body["result"]
    return not res["isError"], res["content"][0]["text"]


def test_mcp_handshake_session_and_delete(client) -> None:
    init, hdrs = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert init["result"]["protocolVersion"] == "2025-03-26"
    sid = hdrs.get("mcp-session-id")
    assert sid
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Mcp-Session-Id": sid}).status_code == 202
    assert client.delete("/api/mcp", headers={"Mcp-Session-Id": sid}).status_code == 204
    body, _ = rpc(client, "tools/list")
    names = {t["name"] for t in body["result"]["tools"]}
    assert {"save_chapter", "patch_chapter", "chapter_brief", "call_model", "api", "notes", "radar_and_teardown", "fanfic_library"} <= names
    assert len(names) <= 30  # 精简高信号工具集，不膨胀
    assert client.get("/api/mcp-info").json()["url"].endswith("/api/mcp")


def test_mcp_end_to_end_fast_commit_patch_batch_and_prev_tail(client) -> None:
    ok, txt = call(client, "create_book", title="接入测试", genre="玄幻", premise="少年得到会说话的剑")
    assert ok, txt
    bid = json.loads(txt)["id"]

    # 1. 批量建设定卡
    ok, txt = call(client, "save_card", book_id=bid, items=[
        {"type": "character", "name": "林远", "summary": "主角"},
        {"type": "cheat", "name": "残剑", "summary": "会说话的剑", "data": {"input": "滴血", "limit": "每日一次"}},
    ])
    assert ok, txt
    assert json.loads(txt)["count"] == 2

    # 2. 批量建大纲树（ref / parent_ref）
    ok, txt = call(client, "save_outline_node", book_id=bid, items=[
        {"ref": "v1", "level": "volume", "order": 1, "title": "第一卷"},
        {"ref": "a1", "parent_ref": "v1", "level": "arc", "order": 1, "title": "青石镇"},
        {"parent_ref": "a1", "level": "chapter", "order": 1, "title": "剑醒", "summary": "林远捡到剑"},
        {"parent_ref": "a1", "level": "chapter", "order": 2, "title": "试锋", "summary": "林远试剑"},
    ])
    assert ok, txt
    assert json.loads(txt)["count"] == 4

    # 3. 写第 1 章并秒级同步入账（附带摘要、人物状态、新实体、伏笔、结尾场面）
    ch1_tail = "铁剑突然发出一声低鸣，震得窗纸嗡嗡作响，剑柄上浮现出一行血字。"
    ok, txt = call(
        client, "save_chapter", book_id=bid, number=1, title="剑醒",
        content=("林远推开柴门，冷风灌进破屋。\n\n" * 40) + ch1_tail,
        commit=True,
        summary="林远在破屋唤醒残剑，发现剑身藏着血字。",
        state_changes=[{"entity": "林远", "key": "持有物品", "value": "残剑"}],
        new_entities=[{"type": "character", "name": "王管事", "summary": "青石镇恶霸"}],
        foreshadow_updates=[{"action": "plant", "desc": "残剑血字的来历"}],
        end_state={"cast": {"林远": {"location": "破屋", "holding": "残剑"}}, "props": {}},
    )
    assert ok, txt
    r = json.loads(txt)
    assert r["committed"] is True and r["status"] == "committed"
    assert r["summary"] == "林远在破屋唤醒残剑，发现剑身藏着血字。"

    # 校验底账确实同步落库
    facts = client.get(f"/api/books/{bid}/facts").json()
    assert any(f["key"] == "持有物品" and f["value"] == "残剑" for f in facts)
    fses = client.get(f"/api/books/{bid}/foreshadows").json()
    assert any("残剑血字" in f["desc"] for f in fses)

    # 4. 第 2 章 chapter_brief 必须包含上一章结尾原文 prev_tail，且不再重复规则
    ok, brief_txt = call(client, "chapter_brief", book_id=bid, number=2, with_rules=True)
    assert ok, brief_txt
    brief = json.loads(brief_txt)
    assert ch1_tail in brief["prev_tail"]
    assert ch1_tail in brief["context"]
    assert brief["context"].count("# 正文写法") <= 1

    # 无细纲的第 3 章也能降级返回前情上下文
    ok, brief3 = call(client, "chapter_brief", book_id=bid, number=3, with_rules=False)
    assert ok, brief3
    b3 = json.loads(brief3)
    assert b3["has_outline"] is False and "note" in b3

    # 5. patch_chapter 定点局部替换
    ok, ptxt = call(client, "patch_chapter", book_id=bid, number=1, patches=[
        {"find": "一行血字", "replace": "三行古篆血字"},
    ])
    assert ok, ptxt
    pr = json.loads(ptxt)
    assert len(pr["applied"]) == 1 and len(pr["skipped"]) == 0

    # 6. 分页读取 & 笔记 & 活动日志 & 鉴权拦截
    ok, ltxt = call(client, "list_chapters", book_id=bid, from_number=1, to_number=1, limit=10)
    assert ok and json.loads(ltxt)["total"] == 1
    ok, ntxt = call(client, "notes", book_id=bid, action="save", title="灵感", content="第二卷去京城")
    assert ok and json.loads(ntxt)["id"]
    ok, _ = call(client, "api", method="GET", path="/api/auth/keys")
    assert not ok
    ok, _ = call(client, "api", method="GET", path="/api/books/../auth/keys")
    assert not ok
    ok, _ = call(client, "api", method="GET", path="/API//auth/keys")
    assert not ok
    ok, idx = call(client, "api_index", keyword="/books", with_schema=True)
    assert ok and "body={" in idx

    acts = client.get(f"/api/books/{bid}/agent-activity").json()
    assert len(acts) >= 4

    # 7. 流式写下一章 SSE 接口（mock 模式）
    with client.stream("POST", f"/api/books/{bid}/chapters/write-stream", json={"instruction": ""}) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())
    assert "event: start" in raw and "event: delta" in raw and "event: done" in raw

    # 8. 回归：同名设定卡 upsert 不重复、大纲 beats 局部更新保留旧键、宽松入账不崩溃
    ok, c_up = call(client, "save_card", book_id=bid, type="character", name="林远",
                    summary="重生复仇的主角（升级版）", data={"realm": "炼气二层"})
    assert ok, c_up
    cu = json.loads(c_up)
    assert cu.get("updated") is True and cu["data"].get("realm") == "炼气二层"
    ok, all_cards = call(client, "search_bible", book_id=bid, type="character")
    assert ok and sum(1 for x in json.loads(all_cards)["cards"] if x["name"] == "林远") == 1

    ok, _ = call(client, "save_outline_node", book_id=bid, level="chapter", order=2,
                 beats={"goal": "林远试剑验证威力"})
    assert ok
    ok, o_patch = call(client, "save_outline_node", book_id=bid, level="chapter", order=2,
                       beats={"hook": "门外响起钟声"})
    assert ok, o_patch
    ok, o_node = call(client, "get_outline_node", book_id=bid, node_id=json.loads(o_patch)["node_id"])
    assert ok, o_node
    ch2_beats = json.loads(o_node)["beats"]
    assert ch2_beats.get("hook") == "门外响起钟声" and ch2_beats.get("goal") == "林远试剑验证威力"

    ok, loose_save = call(
        client, "save_chapter", book_id=bid, number=3, title="宽松入账验证",
        content="林远推门而出，看见雪地上多了一串脚印，一直延伸到藏经阁后墙。",
        commit=True, summary="林远发现雪地脚印直通藏经阁。",
        state_changes=[{"entity": "林远", "key": "银两", "value": 500, "visibility": "public"}],
        new_entities=[{"type": "unknown_kind", "name": "名字超长测试" * 10, "summary": "测试自动截断"}],
    )
    assert ok, loose_save
    assert json.loads(loose_save)["status"] == "committed"

    # 9. 长篇人机协同 6 项增强回归：置顶笔记、人工改稿失步提醒、卷前情回顾、beats 别名归一化、facts 底账修正、跨会话恢复、零耗时穿帮自检
    # 9.1 置顶笔记自动进 chapter_brief 与 get_book_info
    ok, _ = call(client, "notes", book_id=bid, action="save", title="长期红线", content="绝不让师姐在第20章前下线", pinned=True)
    assert ok
    ok, info_txt = call(client, "get_book_info", book_id=bid)
    assert ok, info_txt
    info = json.loads(info_txt)
    assert info["last_chapter_number"] == 3 and info["next_chapter_number"] == 4
    assert any(n["title"] == "长期红线" for n in info["pinned_notes"])
    assert len(info["active_writing_skills"]) >= 1

    # 9.2 卷前情回顾快捷写入 + beats 别名归一化
    ok, vol_up = call(
        client, "save_outline_node", book_id=bid, level="volume", order=1,
        recap_text="第一卷林远在青石镇唤醒残剑，逼退王管事并查出藏经阁脚印线索。",
        recap_state=["林远已达炼气二层", "王管事怀恨在心"],
        start_chapter=1, end_chapter=3,
    )
    assert ok, vol_up
    assert json.loads(vol_up).get("updated") is True

    ok, ch4_node = call(
        client, "save_outline_node", book_id=bid, level="chapter", order=4, title="暗夜追踪",
        beats={"cast": ["林远"], "hook": "黑衣人摘下面具", "target_words": 2600},
    )
    assert ok, ch4_node
    ok, ch4_detail = call(client, "get_outline_node", book_id=bid, node_id=json.loads(ch4_node)["node_id"])
    assert ok
    b4 = json.loads(ch4_detail)["beats"]
    assert b4["characters"] == ["林远"] and b4["hook_end"] == "黑衣人摘下面具" and b4["words"] == 2600

    # 9.3 人工手动改已提交的第 3 章正文 → 第 4 章 chapter_brief 必须报 stale_chapters_warning，且包含卷回顾和置顶笔记
    ch3_id = json.loads(loose_save)["chapter_id"]
    client.put(f"/api/chapters/{ch3_id}", json={"title": "宽松入账验证", "content": "林远推门而出，雪地脚印竟通向后山古井，反派逃脱未死。"})
    ok, b4_txt = call(client, "chapter_brief", book_id=bid, number=4, with_rules=False)
    assert ok, b4_txt
    b4_data = json.loads(b4_txt)
    assert "绝不让师姐在第20章前下线" in b4_data["context"]
    assert "第一卷林远在青石镇唤醒残剑" in b4_data["context"]
    assert "林远已达炼气二层" in b4_data["context"]
    assert any(w["number"] == 3 for w in (b4_data.get("stale_chapters_warning") or []))

    # 刷新第 3 章摘要后，第 3 章的失步提醒消失
    ok, _ = call(client, "commit_chapter", book_id=bid, number=3, summary="林远发现脚印通向后山古井，反派逃脱。", update_ledger=True)
    assert ok
    ok, b4_clean = call(client, "chapter_brief", book_id=bid, number=4, with_rules=False)
    assert ok and not any(w["number"] == 3 for w in (json.loads(b4_clean).get("stale_chapters_warning") or []))

    # 9.4 facts 底账查询、修正（同章不重叠）、删除
    ok, f_set = call(client, "facts", book_id=bid, action="set", entity="林远", key="银两", value="800", from_chapter=3)
    assert ok, f_set
    assert json.loads(f_set).get("updated") is True
    ok, f_list = call(client, "facts", book_id=bid, action="list", entity="林远", key="银两")
    assert ok
    fl = json.loads(f_list)["facts"]
    assert len(fl) == 1 and fl[0]["value"] == "800"
    ok, _ = call(client, "facts", book_id=bid, action="delete", fact_id=fl[0]["id"])
    assert ok

    # 9.5 零耗时防穿帮自检（弃用卡误用 + 禁用套路命中）
    ok, _ = call(client, "save_card", book_id=bid, type="faction", name="旧西区教会", summary="已废弃设定", status="deprecated")
    assert ok
    ok, ch4_save = call(
        client, "save_chapter", book_id=bid, number=4, title="暗夜追踪",
        content="黑衣人冷笑一声，自称来自旧西区教会，还说当年林远修为被废全是一场退婚阴谋。",
    )
    assert ok, ch4_save
    cw = json.loads(ch4_save).get("consistency_warnings") or {}
    assert "旧西区教会" in (cw.get("deprecated_cards_mentioned") or [])
    assert any(h["name"] == "退婚流" for h in (cw.get("banned_trope_hits") or []))
