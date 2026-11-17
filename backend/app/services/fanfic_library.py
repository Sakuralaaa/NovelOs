"""v0.15 原著世界库：每部原著一个永久设定库，四大类（世界设定 / 角色档案 / 剧情时间线 / 关系索引）+ 子分类。

- 条目存在 FanficSource.entries；第一次打开时从设定卡（cards）派生，之后提炼/联网补充出的新内容按「类别+名字」去重并入。
- 设定卡仍是写章注入的精简核心；世界库是更大的资料库，写章时按书的简介/补充里提到的名字挑相关条目注入。
- 同一部原著的所有同人书共用这一个库（建书时选同一份原著资料即复用）。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import FanficSource
from app.skills.loader import render, system_prompt

CATS = {"world": "世界设定", "character": "角色档案", "timeline": "剧情时间线", "relation": "关系索引"}
WORLD_SUBS = ["力量体系", "世界规则", "关键物品", "组织势力", "地理地点", "制度社会", "历史背景", "其他设定"]
REL_SUBS = [("亲情", ("父", "母", "兄", "弟", "姐", "妹", "儿", "女", "亲", "家")), ("师徒", ("师", "徒")),
            ("伴侣", ("恋", "妻", "夫", "爱", "伴侣", "情侣", "未婚")), ("宿敌", ("敌", "仇", "对手", "杀")),
            ("同伴", ("同伴", "伙伴", "队友", "兄弟", "朋友", "挚友", "生死", "同学"))]
MAX_ENTRIES = 3000
EXPAND_MAX = 40
_POWER_RE = re.compile(r"境界|等级|魂环|修炼|功法|血脉|力量|魂力|斗气|灵力|阶")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _eid() -> str:
    return uuid.uuid4().hex[:12]


def _s(v: Any, n: int) -> str:
    return (v if isinstance(v, str) else "" if v is None else str(v)).strip()[:n]


def norm_entry(e: dict[str, Any], keep_id: bool = True) -> dict[str, Any] | None:
    cat = e.get("cat") if e.get("cat") in CATS else None
    name = _s(e.get("name"), 60)
    if not cat or not name:
        return None
    sub = _s(e.get("sub"), 20) or {"world": "其他设定", "character": "其他角色", "timeline": "剧情时间线", "relation": "其他关系"}[cat]
    tags = [_s(t, 12) for t in (e.get("tags") or []) if isinstance(t, str) and t.strip()][:8]
    out = {"id": (_s(e.get("id"), 24) if keep_id else "") or _eid(), "cat": cat, "sub": sub, "name": name,
           "summary": _s(e.get("summary"), 200), "detail": _s(e.get("detail"), 2000), "tags": tags}
    try:
        out["order"] = int(e.get("order") or 0)
    except (TypeError, ValueError):
        out["order"] = 0
    return out


def _rel_sub(rel: str) -> str:
    for sub, kws in REL_SUBS:
        if any(k in rel for k in kws):
            return sub
    return "其他关系"


def _role_sub(role: str) -> str:
    if not role:
        return "其他角色"
    if "主角" in role and "配" not in role:
        return "主角"
    if "反派" in role or "敌" in role:
        return "反派"
    if "配角" in role:
        return "主要配角"
    return role[:8]


def derive(cards: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从设定卡派生世界库条目（不带 id，入库时补）。"""
    c = cards or {}
    out: list[dict[str, Any]] = []
    w = c.get("world") or {}
    for i, r in enumerate(w.get("rules") or []):
        if not isinstance(r, str) or not r.strip():
            continue
        name = re.split(r"[：:，,。；;]", r.strip())[0][:16] or f"规则 {i + 1}"
        out.append({"cat": "world", "sub": "力量体系" if _POWER_RE.search(r) else "世界规则", "name": name, "summary": r.strip()})
    for l in w.get("locations") or []:
        if isinstance(l, dict) and l.get("name"):
            out.append({"cat": "world", "sub": "地理地点", "name": l["name"], "summary": l.get("desc") or ""})
    for f in c.get("factions") or []:
        if isinstance(f, dict) and f.get("name"):
            mem = "、".join(f.get("members") or [])
            out.append({"cat": "world", "sub": "组织势力", "name": f["name"], "summary": "；".join(x for x in (f.get("stance"), f.get("notes")) if x),
                        "detail": f"成员：{mem}" if mem else "", "tags": list(f.get("members") or [])[:6]})
    for ch in c.get("characters") or []:
        if not isinstance(ch, dict) or not ch.get("name"):
            continue
        bits = [("别称", "、".join(ch.get("aliases") or [])), ("性格", ch.get("personality")), ("说话方式", ch.get("speech_style")),
                ("口癖", "、".join(ch.get("catchphrases") or [])), ("能力", "、".join(ch.get("abilities") or [])),
                ("上限", "、".join(ch.get("limits") or [])), ("备注", ch.get("notes"))]
        out.append({"cat": "character", "sub": _role_sub(str(ch.get("role") or "")), "name": ch["name"],
                    "summary": ch.get("personality") or ch.get("role") or "", "detail": "\n".join(f"{k}：{v}" for k, v in bits if v)})
        for r in ch.get("relations") or []:
            if isinstance(r, dict) and r.get("target"):
                out.append({"cat": "relation", "sub": _rel_sub(str(r.get("relation") or "")), "name": f"{ch['name']} — {r['target']}",
                            "summary": r.get("relation") or "", "tags": [ch["name"], r["target"]]})
    for i, t in enumerate(c.get("timeline") or []):
        if isinstance(t, dict) and t.get("event"):
            out.append({"cat": "timeline", "sub": "剧情时间线", "name": str(t["event"])[:40], "summary": t.get("impact") or "",
                        "tags": list(t.get("characters") or [])[:6], "order": t.get("order") or i + 1})
    for sc in c.get("scenes") or []:
        if isinstance(sc, dict) and sc.get("title"):
            out.append({"cat": "timeline", "sub": "名场面", "name": sc["title"], "summary": sc.get("summary") or "",
                        "tags": list(sc.get("characters") or [])[:6]})
    return out


def _key(e: dict[str, Any]) -> tuple[str, str]:
    return e["cat"], re.sub(r"\s", "", e["name"]).lower()


def merge(base: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """按（类别, 名字）去重并入；已有条目只补空字段，不覆盖作者改过的内容。"""
    cur = [x for x in (norm_entry(e) for e in base) if x]
    idx = {_key(e): i for i, e in enumerate(cur)}
    added = 0
    for raw in new:
        e = norm_entry(raw, keep_id=False)
        if not e:
            continue
        k = _key(e)
        if k in idx:
            old = cur[idx[k]]
            for f in ("summary", "detail"):
                if not old.get(f) and e.get(f):
                    old[f] = e[f]
            continue
        if len(cur) >= MAX_ENTRIES:
            break
        idx[k] = len(cur)
        cur.append(e)
        added += 1
    return cur, added


def ensure(r: FanficSource) -> bool:
    """库为空但有设定卡时派生一次；返回是否改动。"""
    if r.entries:
        return False
    ents, n = merge([], derive(r.cards))
    if not n:
        return False
    r.entries = ents
    if not r.intro:
        r.intro = _s(((r.cards or {}).get("world") or {}).get("summary"), 400)
    return True


def sync_from_cards(r: FanficSource) -> int:
    """提炼/补充后把设定卡里的新内容并进世界库。"""
    ents, n = merge(list(r.entries or []), derive(r.cards))
    r.entries = ents
    if not r.intro:
        r.intro = _s(((r.cards or {}).get("world") or {}).get("summary"), 400)
    return n


def counts(r: FanficSource) -> dict[str, int]:
    out = {k: 0 for k in CATS}
    for e in r.entries or []:
        if e.get("cat") in out:
            out[e["cat"]] += 1
    return out


def _get(s: Session, source_id: int) -> FanficSource:
    from app.services.fanfic import _get as g

    r = g(s, source_id)
    if ensure(r):
        s.add(r)
        s.commit()
        s.refresh(r)
    return r


def list_entries(source_id: int, cat: str | None, sub: str | None, q: str | None, page: int, size: int) -> dict[str, Any]:
    with session_scope() as s:
        r = _get(s, source_id)
        ents = [x for x in (norm_entry(e) for e in r.entries or []) if x]
    in_cat = [e for e in ents if not cat or e["cat"] == cat]
    subs: dict[str, int] = {}
    for e in in_cat:
        subs[e["sub"]] = subs.get(e["sub"], 0) + 1
    order = WORLD_SUBS if cat == "world" else []
    sub_list = sorted(subs.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99, -kv[1]))
    kw = (q or "").strip().lower()
    items = [e for e in in_cat if (not sub or e["sub"] == sub)
             and (not kw or kw in (e["name"] + e["summary"] + e["detail"] + " ".join(e["tags"])).lower())]
    if cat == "timeline":
        items.sort(key=lambda e: (e["sub"] == "名场面", e["order"] or 10**6))
    size = max(6, min(size, 120))
    pages = max(1, -(-len(items) // size))
    page = max(1, min(page, pages))
    cats = {k: 0 for k in CATS}
    for e in ents:
        cats[e["cat"]] += 1
    return {"items": items[(page - 1) * size: page * size], "total": len(items), "page": page, "pages": pages,
            "cats": cats, "subs": [{"sub": k, "count": v} for k, v in sub_list], "all": len(ents)}


def _save(s: Session, r: FanficSource, ents: list[dict[str, Any]]) -> None:
    r.entries = ents
    r.updated_at = _now()
    s.add(r)
    s.commit()


def add_entry(source_id: int, body: dict[str, Any]) -> dict[str, Any]:
    from app.services.fanfic import FanficError

    e = norm_entry(body, keep_id=False)
    if not e:
        raise FanficError("类别和名字必填", 422)
    with session_scope() as s:
        r = _get(s, source_id)
        ents = list(r.entries or [])
        if len(ents) >= MAX_ENTRIES:
            raise FanficError(f"一部原著最多 {MAX_ENTRIES} 条", 422)
        if any(_key(x) == _key(e) for x in (norm_entry(y) for y in ents) if x):
            raise FanficError(f"已经有「{e['name']}」这一条了", 409)
        _save(s, r, ents + [e])
    return e


def update_entry(source_id: int, eid: str, body: dict[str, Any]) -> dict[str, Any]:
    from app.services.common import NotFound

    with session_scope() as s:
        r = _get(s, source_id)
        ents = list(r.entries or [])
        k = next((i for i, x in enumerate(ents) if x.get("id") == eid), None)
        if k is None:
            raise NotFound("条目不存在")
        e = norm_entry({**ents[k], **{f: v for f, v in body.items() if f in ("cat", "sub", "name", "summary", "detail", "tags", "order")}, "id": eid})
        if not e:
            from app.services.fanfic import FanficError
            raise FanficError("类别和名字必填", 422)
        ents[k] = e
        _save(s, r, ents)
    return e


def delete_entry(source_id: int, eid: str) -> None:
    with session_scope() as s:
        r = _get(s, source_id)
        _save(s, r, [x for x in r.entries or [] if x.get("id") != eid])


def update_meta(source_id: int, intro: str | None, tags: list[str] | None) -> None:
    with session_scope() as s:
        r = _get(s, source_id)
        if intro is not None:
            r.intro = intro.strip()[:600]
        if tags is not None:
            r.tags = [t.strip()[:12] for t in tags if t and t.strip()][:12]
        r.updated_at = _now()
        s.add(r)
        s.commit()


def expand(source_id: int, cat: str, sub: str, hint: str, count: int, ctx: JobContext) -> dict[str, Any]:
    """AI 扩充某一类（可指定子分类）：有联网搜索就先检索，再整理成条目；按名字去重并入。"""
    from app.services.fanfic import FANFIC_SEARCH_SYSTEM, FanficError, search_mode

    if cat not in CATS:
        raise FanficError("类别不对", 422)
    count = max(5, min(count, EXPAND_MAX))
    with session_scope() as s:
        r = _get(s, source_id)
        work = r.title
        have = [e["name"] for e in (norm_entry(x) for x in r.entries or []) if e and e["cat"] == cat][:200]
    label = CATS[cat] + (f"·{sub}" if sub else "")
    material = ""
    mode = search_mode()
    if mode == "web":
        ctx.progress(10, f"联网检索《{work}》{label}")
        q = f"《{work}》{label}的详细资料" + (f"，重点：{hint}" if hint else "") + "，尽量多列条目，每条写清名字和要点"
        try:
            material = (get_gateway().search(q, "已有条目：" + "、".join(have[:80]), system=FANFIC_SEARCH_SYSTEM) or "")[:12000]
        except Exception as e:  # noqa: BLE001
            ctx.progress(30, f"联网检索失败，改用模型已知资料：{str(e)[:60]}")
    ctx.progress(50, f"整理{label}条目")
    user = render("fanfic_entries", work=work, cat=CATS[cat], sub=sub or "不限（自己判断子分类）", count=count,
                  subs="、".join(WORLD_SUBS) if cat == "world" else "按角色定位（主角/主要配角/反派/…）" if cat == "character"
                  else "剧情时间线 或 名场面" if cat == "timeline" else "亲情/师徒/伴侣/宿敌/同伴/其他关系",
                  have="、".join(have) or "（暂无）", hint=hint or "无", material=material or "（没有联网资料，只写你确定的原著设定，不确定的不写）")
    data = get_gateway().chat_json("fanfic_entries", system_prompt("fanfic_entries"), user, role="reviewer",
                                   meta={"work": work, "cat": cat, "sub": sub, "count": count, "have": have})
    raw = (data or {}).get("entries") if isinstance(data, dict) else data
    new = [{**e, "cat": cat, **({"sub": sub} if sub else {})} for e in (raw or []) if isinstance(e, dict)][:count]
    ctx.progress(90, "并入世界库")
    with session_scope() as s:
        r = _get(s, source_id)
        ents, added = merge(list(r.entries or []), new)
        _save(s, r, ents)
    return {"source_id": source_id, "added": added, "cat": cat}


def context_lines(src: FanficSource, text: str, fidelity: str, budget: int = 900) -> list[str]:
    """写章注入：力量体系/世界规则要点 + 书的简介/补充里点到名字的条目。"""
    ents = [x for x in (norm_entry(e) for e in src.entries or []) if x]
    if not ents:
        return []
    picked: list[dict[str, Any]] = []
    if fidelity != "loose":
        picked += [e for e in ents if e["cat"] == "world" and e["sub"] in ("力量体系", "世界规则")][:6]
    hit = [e for e in ents if e["cat"] in ("world", "character", "timeline") and len(e["name"]) >= 2 and e["name"] in text and e not in picked]
    picked += hit[:10]
    out, used = [], 0
    for e in picked:
        line = f"- [{e['sub']}] {e['name']}：{e['summary'] or e['detail'][:80]}"
        if used + len(line) > budget:
            break
        out.append(line)
        used += len(line)
    return (["原著世界库相关条目："] + out) if out else []
