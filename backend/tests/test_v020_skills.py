"""v0.20 可插拔技能库与 MCP 技能工具测试。"""

from __future__ import annotations

import json
from typing import Any


def _call_mcp(client, tool: str, **args: Any) -> tuple[bool, str]:
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return not res["isError"], res["content"][0]["text"]


def test_skills_crud_book_binding_and_context_injection(client) -> None:
    # 1. 启动后自动装入内置技能（rules + 精选网文技能）
    res = client.get("/api/skills").json()
    items = res["items"]
    assert len(items) >= 12
    slugs = {x["slug"] for x in items}
    assert "builtin-rule-writing" in slugs and "curated-golden-opening" in slugs

    # 2. 自建技能 + 编辑 + 复制 + 删除
    created = client.post("/api/skills", json={
        "name": "测试爽文口癖约束",
        "description": "每章必有一次反杀",
        "stage": "writing",
        "body": "# 独家口诀\n主角绝不吃闷亏，当场找回场子。",
    }).json()
    sid = created["id"]
    assert created["source"] == "custom"

    updated = client.put(f"/api/skills/{sid}", json={"body": "# 独家口诀\n主角绝不吃闷亏，三段之内必反杀。"}).json()
    assert "三段之内必反杀" in updated["body"]

    dup = client.post(f"/api/skills/{sid}/duplicate").json()
    assert dup["id"] != sid
    assert client.delete(f"/api/skills/{dup['id']}").status_code == 200

    # 内置技能不可删除但可修改与重置
    builtin_w = next(x for x in items if x["slug"] == "builtin-rule-writing")
    assert client.delete(f"/api/skills/{builtin_w['id']}").status_code == 409
    client.put(f"/api/skills/{builtin_w['id']}", json={"body": "# 临时改写"})
    reset_r = client.post(f"/api/skills/{builtin_w['id']}/reset").json()
    assert "正文写法" in reset_r["body"]

    # 3. 绑定到作品并验证 chapter_brief 确实注入了该自定义技能
    book = client.post("/api/books", json={"title": "技能测试书", "genre": "都市", "premise": "测试"}).json()
    bid = book["id"]
    bound = client.put(f"/api/books/{bid}/skills", json={"skill_ids": [sid]}).json()
    assert bound["customized"] is True and bound["selected_ids"] == [sid]

    ok, brief_txt = _call_mcp(client, "chapter_brief", book_id=bid, number=1, with_rules=True)
    assert ok, brief_txt
    assert "三段之内必反杀" in json.loads(brief_txt)["context"]

    # 4. 外接 Agent 通过 MCP skills 工具读写技能库
    ok, list_txt = _call_mcp(client, "skills", action="list", stage="writing")
    assert ok, list_txt
    assert any(x["id"] == sid for x in json.loads(list_txt)["items"])

    ok, new_txt = _call_mcp(client, "skills", action="save", name="Agent总结技法", stage="writing", body="写打斗时每招带声音和位移。")
    assert ok, new_txt
    aid = json.loads(new_txt)["id"]
    ok, _ = _call_mcp(client, "skills", action="bind_book", book_id=bid, skill_ids=[sid, aid])
    assert ok
    ok, brief2 = _call_mcp(client, "chapter_brief", book_id=bid, number=1, with_rules=True)
    assert ok and "每招带声音和位移" in json.loads(brief2)["context"]

    # 5. 本书显式取消全部写作技能时，不应静默回退注入内置 rules/writing.md
    cleared = client.put(f"/api/books/{bid}/skills", json={"skill_ids": []}).json()
    assert cleared["customized"] is True and cleared["selected_ids"] == []
    ok, brief_empty = _call_mcp(client, "chapter_brief", book_id=bid, number=1, with_rules=True)
    assert ok
    assert "# 正文写法" not in json.loads(brief_empty)["context"]

    # 6. 非写作技能（如 outline）修改后应立即在 system_prompt 中生效
    from app.skills.loader import system_prompt

    builtin_outline = next(x for x in items if x["slug"] == "builtin-rule-outline")
    client.put(f"/api/skills/{builtin_outline['id']}", json={"body": "# 大纲规则\n每卷必须设置双重反转锚点。"})
    assert "每卷必须设置双重反转锚点" in system_prompt("outline")
    client.post(f"/api/skills/{builtin_outline['id']}/reset")
    assert "每卷必须设置双重反转锚点" not in system_prompt("outline")
