"""联网核实：生成前先让模型列出“拿不准的现实事实”，再交给路由里的搜索模型查证。

- 只有在任务路由里配置了「联网搜索」模型时才会运行，否则直接返回空字符串，不产生任何额外调用。
- 查证结果按问题缓存 30 天，同一本书反复生成不会重复搜索。
- 任何一步失败都只记日志、不打断主流程。
"""

from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.db import kv_get, kv_set, session_scope
from app.llm.gateway import get_gateway

log = logging.getLogger("novelos.research")

MAX_QUERIES = 3
CACHE_TTL = 30 * 24 * 3600
LOG_KEY = "research_log"

PLAN_SYSTEM = (
    "你是网文创作的资料把关人。阅读下面的创作材料，找出其中涉及现实世界、写错会被读者挑刺的具体事实："
    "历史年代与事件、地理与城市细节、职业流程与行话、法律医疗金融常识、真实品牌与科技、体育赛事规则、"
    "近期社会热点等。纯虚构设定（修炼体系、异世界地名、架空人物）不需要查。\n"
    f"只挑你确实拿不准、且会影响内容的，最多 {MAX_QUERIES} 个，写成可以直接拿去搜索的中文问题。"
    "一个都没有就返回空数组。只输出 JSON：{\"queries\": [\"问题1\", \"问题2\"]}"
)


def _cache_key(q: str) -> str:
    return "research:" + hashlib.sha1(q.strip().encode()).hexdigest()[:16]


def _lookup(q: str, context: str) -> str | None:
    key = _cache_key(q)
    with session_scope() as s:
        hit = kv_get(s, key)
    if isinstance(hit, dict) and time.time() - float(hit.get("t", 0)) < CACHE_TTL and hit.get("a"):
        return str(hit["a"])
    ans = get_gateway().search(q, context)
    if ans:
        with session_scope() as s:
            kv_set(s, key, {"q": q, "a": ans, "t": time.time()})
            s.commit()
    return ans


def _log(book_id: int | None, task: str, items: list[dict[str, str]]) -> None:
    if not items:
        return
    with session_scope() as s:
        logs: list[dict[str, Any]] = list(kv_get(s, LOG_KEY, []) or [])
        for it in items:
            logs.append({"book_id": book_id, "task": task, "q": it["q"], "a": it["a"], "t": int(time.time())})
        kv_set(s, LOG_KEY, logs[-200:])
        s.commit()


def research_notes(task: str, material: str, book_id: int | None = None, ctx: Any = None, pct: int | None = None) -> str:
    """返回可直接拼进 prompt 的「联网核实资料」段落；未配置搜索模型或无需核实时返回空字符串。"""
    gw = get_gateway()
    try:
        if not gw.has_search():
            return ""
        plan = gw.chat_json("research_plan", PLAN_SYSTEM, material[:6000], role="reviewer", temperature=0.2)
        qs = plan.get("queries") if isinstance(plan, dict) else plan
        queries = [str(q).strip() for q in (qs or []) if str(q).strip()][:MAX_QUERIES]
    except Exception:  # noqa: BLE001
        log.exception("联网核实：列问题失败")
        return ""
    if not queries:
        return ""
    if ctx is not None and pct is not None:
        ctx.progress(pct, f"联网核实 {len(queries)} 个不确定的事实")
    def one(q: str) -> dict[str, str] | None:
        try:
            a = _lookup(q, material[:600])
        except Exception:  # noqa: BLE001
            log.warning("联网核实失败：%s", q, exc_info=True)
            return None
        return {"q": q, "a": a.strip()} if a else None

    # 多 agent 搜索单条可能要几分钟，几个问题并发查
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        found = [x for x in pool.map(one, queries) if x]
    _log(book_id, task, found)
    if not found:
        return ""
    body = "\n\n".join(f"问：{x['q']}\n答：{x['a']}" for x in found)
    return (
        "\n\n【联网核实资料】以下是针对本次内容中现实细节的查证结果，写作时以此为准；"
        "与设定冲突时优先保证设定自洽，但不要写出与现实常识相悖的细节。\n" + body
    )


def recent_logs(book_id: int | None = None, limit: int = 30) -> list[dict[str, Any]]:
    with session_scope() as s:
        logs = list(kv_get(s, LOG_KEY, []) or [])
    if book_id is not None:
        logs = [x for x in logs if x.get("book_id") == book_id]
    return list(reversed(logs[-limit:]))
