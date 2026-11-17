"""v0.15 原著世界库：条目派生、分类筛选、搜索翻页、增改删、AI 扩充、写章注入。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import wait_job
from test_v010 import _source


def test_library_flow(client: TestClient) -> None:
    sid = _source(client)["id"]
    src = client.get(f"/api/fanfic/sources/{sid}").json()
    assert sum(src["entry_counts"].values()) > 0 and "books" in src
    r = client.get(f"/api/fanfic/sources/{sid}/entries", params={"cat": "character"}).json()
    assert r["total"] == r["cats"]["character"] > 0 and all(e["cat"] == "character" for e in r["items"])
    assert r["subs"]
    e = client.post(f"/api/fanfic/sources/{sid}/entries", json={"cat": "world", "sub": "关键物品", "name": "测试神器", "summary": "一把剑"}).json()
    assert e["id"]
    assert client.post(f"/api/fanfic/sources/{sid}/entries", json={"cat": "world", "name": "测试神器"}).status_code == 409
    q = client.get(f"/api/fanfic/sources/{sid}/entries", params={"cat": "world", "q": "神器"}).json()
    assert [x["name"] for x in q["items"]] == ["测试神器"]
    u = client.put(f"/api/fanfic/sources/{sid}/entries/{e['id']}", json={"summary": "一把会说话的剑"}).json()
    assert u["summary"] == "一把会说话的剑"
    p = client.get(f"/api/fanfic/sources/{sid}/entries", params={"size": 6, "page": 2}).json()
    assert p["page"] <= p["pages"]
    j = client.post(f"/api/fanfic/sources/{sid}/expand", json={"cat": "world", "sub": "关键物品", "count": 6}).json()
    j = wait_job(client, j)
    assert j["status"] == "succeeded" and j["result"]["added"] > 0
    assert client.delete(f"/api/fanfic/sources/{sid}/entries/{e['id']}").json()["ok"]
    m = client.put(f"/api/fanfic/sources/{sid}", json={"intro": "简介", "tags": ["玄幻"]}).json()
    assert m["source"]["intro"] == "简介" and m["source"]["tags"] == ["玄幻"]
