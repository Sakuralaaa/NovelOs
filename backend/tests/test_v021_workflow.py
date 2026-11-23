"""v0.21 完本短剧流 · 黄金三章先行 + 重纲轻写千字起承转合章纲 + 续写审记 + 新内置技能测试。"""

from __future__ import annotations

import time
from typing import Any


def _wait_job(client: Any, job_id: int, timeout: float = 20.0) -> dict[str, Any]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        j = r.json()
        if j["status"] in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


def test_v021_curated_skills_seeded(client: Any) -> None:
    r = client.get("/api/skills")
    assert r.status_code == 200
    slugs = {it["slug"] for it in r.json()["items"]}
    assert "curated-tomato-shortdrama-plain" in slugs
    assert "curated-heavy-outline-beat" in slugs


def test_v021_heavy_beats_and_context_rendering() -> None:
    from app.services.context import chapter_task_lines
    from app.services.outline import normalize_beats

    raw = {
        "title": "第一刀",
        "goal": "讨回欠债",
        "conflict": "反派拒不认账",
        "起": "刚进门就被泼了一脸茶水，三句对白火药味拉满。",
        "承": "反派仗着人多步步紧逼，主角当场亮出账单。",
        "转": "系统弹出一笔三倍返利，反派当众下跪求饶。",
        "合": "收走铺子钥匙，门口突然开来一辆黑车。",
        "核心场景": "老城区茶馆二楼包间",
        "底层博弈": "主角早就摸清反派挪用公款的底细",
        "本章收益": "收回十万现金与铺子地契",
    }
    beats = normalize_beats(raw, 1, 2100)
    assert beats["stage_qi"].startswith("刚进门就被泼了一脸茶水")
    assert beats["stage_cheng"].startswith("反派仗着人多")
    assert beats["stage_zhuan"].startswith("系统弹出")
    assert beats["stage_he"].startswith("收走铺子钥匙")
    assert beats["core_scene"] == "老城区茶馆二楼包间"
    assert beats["underlying_game"].startswith("主角早就摸清")
    assert beats["chapter_reward"] == "收回十万现金与铺子地契"

    lines = chapter_task_lines(beats, 1, protagonist="陈野")
    joined = "\n".join(lines)
    assert "起承转合详纲" in joined
    assert "起（入局冲突）" in joined
    assert "核心场景：老城区茶馆二楼包间" in joined
    assert "本章收益：收回十万现金与铺子地契" in joined


def test_v021_golden_three_first_then_anchored_outline_and_batch_chapters(client: Any) -> None:
    # 1. 创建一本完本短剧流新书
    b = client.post("/api/books", json={
        "title": "黄金三章测试书", "genre": "都市脑洞", "gender": "male",
        "platform_style": "fanqie", "mode": "wanben", "target_words": 200000, "chapter_words": 2100,
    }).json()
    bid = b["id"]

    # 2. 不先生成大纲，直接跑「黄金三章先行」
    r_g = client.post(f"/api/books/{bid}/chapters/golden-three", json={"instruction": "开头三句强情绪冲突对话"})
    assert r_g.status_code == 200
    j_g = _wait_job(client, r_g.json()["id"])
    assert j_g["status"] == "succeeded", j_g
    assert len(j_g["result"]["chapter_ids"]) == 3

    chs_before = client.get(f"/api/books/{bid}/chapters").json()
    assert [c["number"] for c in chs_before] == [1, 2, 3]
    ch_ids_before = [c["id"] for c in chs_before]

    # 3. 确认前三章后再点「生成大纲」：自动锚定第 1–3 章并保留已有绑定
    r_o = client.post(f"/api/books/{bid}/outline/generate")
    assert r_o.status_code == 200
    j_o = _wait_job(client, r_o.json()["id"])
    assert j_o["status"] == "succeeded", j_o
    assert j_o["result"]["anchored_chapters"] == 3

    nodes = client.get(f"/api/books/{bid}/outline").json()
    ch_nodes = sorted([n for n in nodes if n["level"] == "chapter"], key=lambda x: x["order"])
    assert len(ch_nodes) >= 5
    # 前三章保留为 written 且绑定原 chapter_id
    for idx in range(3):
        assert ch_nodes[idx]["order"] == idx + 1
        assert ch_nodes[idx]["status"] == "written"
        assert ch_nodes[idx]["chapter_id"] == ch_ids_before[idx]

    # 4. 批量生成 6 章千字起承转合章纲
    max_order_before = max(n["order"] for n in ch_nodes)
    r_bc = client.post(f"/api/books/{bid}/outline/batch-chapters", json={
        "count": 6, "heavy": True, "instruction": "加强反转密度",
    })
    assert r_bc.status_code == 200
    j_bc = _wait_job(client, r_bc.json()["id"])
    assert j_bc["status"] == "succeeded", j_bc
    assert j_bc["result"]["count"] == 6
    assert j_bc["result"]["start_chapter"] == max_order_before + 1

    nodes2 = client.get(f"/api/books/{bid}/outline").json()
    new_ch = next(n for n in nodes2 if n["level"] == "chapter" and n["order"] == max_order_before + 1)
    assert new_ch["beats"]["stage_qi"]
    assert new_ch["beats"]["stage_zhuan"]

    # 5. 续写审记：带 instruction 批量连写 2 章
    r_wb = client.post(f"/api/books/{bid}/chapters/write-batch", json={
        "count": 2, "instruction": "零黑话纯大白话，节奏更快",
    })
    assert r_wb.status_code == 200
    j_wb = _wait_job(client, r_wb.json()["id"])
    assert j_wb["status"] == "succeeded", j_wb
    assert len(j_wb["result"]["chapter_ids"]) == 2


def test_v021_mcp_heavy_beats_normalization() -> None:
    from app.api.routes_mcp import _normalize_beats

    out = _normalize_beats({"起": "开场冲突", "承": "加压", "转": "打脸", "合": "留钩子", "本章收益": "一百万"})
    assert out is not None
    assert out["stage_qi"] == "开场冲突"
    assert out["stage_cheng"] == "加压"
    assert out["stage_zhuan"] == "打脸"
    assert out["stage_he"] == "留钩子"
    assert out["chapter_reward"] == "一百万"


def test_v021_clear_heavy_beat_via_outline_update(client: Any) -> None:
    b = client.post("/api/books", json={"title": "清节拍测试", "genre": "都市脑洞", "gender": "male"}).json()
    bid = b["id"]
    j = _wait_job(client, client.post(f"/api/books/{bid}/outline/batch-chapters", json={"count": 1, "heavy": True}).json()["id"])
    assert j["status"] == "succeeded"
    nid = j["result"]["created"][0]
    up = client.put(f"/api/outline/{nid}", json={"beats": {"stage_qi": ""}}).json()
    assert "stage_qi" not in (up.get("beats") or {})

