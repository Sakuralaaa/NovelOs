"""v0.11 完本模式：每本书可选（Book.mode = serial 连载 / wanben 完本），只负责内容生产。

- 完本设置：目标字数、每章字数、每批章数、精修范围、精修待审批时是否暂停、是否连续跑批。
- 字数目标倒推规划：按 target_words / chapter_words 算总章数，给每卷章号区间、本卷危机、高潮章、收束，
  最后一卷安排完整结局；复用 outline 的 总纲→卷→弧→章 结构（卷的规划存在卷节点 beats["wanben"] 里，不另造表）。
- 分批连写：补齐本批章细纲 → 逐章写作+审稿+自动修补+提交（复用 writing.write_next）→ 批末抽检报告（wanben_batch 表）。
  每章写作步骤的断点嵌在批次断点里，进程重启后 POST /api/jobs/{id}/resume 从断点续跑。
- 精修范围：任意章号集合（默认前 10 章，可全书）；范围内的章只写不自动提交，等作者审批（现有 POST /chapters/{id}/commit）。
- 章节迭代：任意已写章按审稿/读者审读问题定点修或整章重写，产出新版本（wanben_iteration 表）供对比采纳，可反复多轮。
"""

from __future__ import annotations

import math
import re
from typing import Any

from sqlmodel import Session, func, select

from app.db import kv_get, kv_set, session_scope
from app.jobs.manager import JobContext, register_resumable, save_checkpoint
from app.llm.gateway import get_gateway
from app.models.tables import Book, Chapter, OutlineNode, WanbenBatch, WanbenIteration, utcnow
from app.services import common, outline, writing
from app.services.common import Conflict, NotFound
from app.services.review import READER_PASS, apply_patches, ending_issue
from app.skills.loader import render, system_prompt

MODES = ("serial", "wanben")
TARGET_PRESETS = (150_000, 200_000, 300_000)
REFINE_SCOPES = ("first_n", "all", "custom", "none")
DEFAULTS: dict[str, Any] = {
    "target_words": 200_000,
    "chapter_words": 2000,
    "batch_size": 10,
    "refine_scope": "first_n",   # first_n：前 golden_chapters 章；all：全书；custom：refine_ranges；none：不设精修范围
    "golden_chapters": 10,
    "refine_ranges": [],         # [[start, end], ...]，单章写成 [n, n]
    "pause_on_unapproved_refine": True,  # 精修范围内有章写好未审批时，批量连写暂停
    "auto_continue": False,
}
CHAPTERS_PER_VOLUME = 60  # 倒推卷数的经验值：约 60 章一卷
MIN_VOLUMES, MAX_VOLUMES = 2, 12
MAX_ITER_ROUNDS = 5

BATCH_KIND = "wanben_batch"
PLAN_KIND = "wanben_plan"
ITERATE_KIND = "wanben_iterate"


def _pause_key(book_id: int) -> str:
    return f"wanben_pause:{book_id}"


def _iter_stop_key(book_id: int) -> str:
    return f"wanben_iter_stop:{book_id}"


# ------------------------------------------------------------------ 设置

def norm_ranges(raw: Any) -> list[list[int]]:
    """把 [[a,b], n, "a-b", ...] 规整成按起点排序、合并过重叠的 [[a,b], ...]。"""
    items: list[tuple[int, int]] = []
    for it in raw or []:
        a = b = None
        if isinstance(it, (list, tuple)) and it:
            a, b = it[0], it[-1]
        elif isinstance(it, int):
            a = b = it
        elif isinstance(it, str):
            m = re.fullmatch(r"\s*(\d+)\s*(?:[-–~～至到]\s*(\d+))?\s*", it)
            if m:
                a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        try:
            a, b = int(a), int(b)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if a > b:
            a, b = b, a
        if b < 1:
            continue
        items.append((max(1, a), b))
    items.sort()
    out: list[list[int]] = []
    for a, b in items:
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def total_chapters_for(target_words: int, chapter_words: int) -> int:
    return max(1, math.ceil(int(target_words) / max(1, int(chapter_words))))


def book_mode(book: Book) -> str:
    return book.mode if book.mode in MODES else "serial"  # 旧库迁移补的空串按连载处理


def raw_settings(book: Book) -> dict[str, Any]:
    st = {**DEFAULTS, **{k: v for k, v in (book.wanben or {}).items() if k in DEFAULTS}}
    st["refine_ranges"] = norm_ranges(st.get("refine_ranges"))
    return st


def refine_numbers(st: dict[str, Any], total: int, written_max: int = 0) -> list[int]:
    scope = st.get("refine_scope") or "first_n"
    upto = max(total, written_max)
    if scope == "none":
        return []
    if scope == "all":
        return list(range(1, upto + 1))
    if scope == "custom":
        nums: set[int] = set()
        for a, b in norm_ranges(st.get("refine_ranges")):
            nums.update(range(a, b + 1))
        return sorted(nums)
    return list(range(1, max(0, int(st.get("golden_chapters") or 0)) + 1))


def _written_max(s: Session, book_id: int) -> int:
    v = s.exec(select(func.max(Chapter.number)).where(Chapter.book_id == book_id)).one()
    return int(v or 0)


def settings_out(s: Session, book: Book) -> dict[str, Any]:
    st = raw_settings(book)
    total = total_chapters_for(st["target_words"], st["chapter_words"])
    nums = refine_numbers(st, total, _written_max(s, book.id or 0))
    return {"book_id": book.id, "mode": book_mode(book), **st, "presets": list(TARGET_PRESETS),
            "total_chapters": total, "refine_numbers": nums, "refine_count": len(nums),
            "reader_threshold": READER_PASS}


def update_settings(s: Session, book: Book, patch: dict[str, Any]) -> dict[str, Any]:
    """PUT /wanben：只改传了的字段。切到完本模式（或已是完本）时，target_words / chapter_words 同步到书的同名字段，
    让大纲、写章用同一个目标。切回连载不动其他数据。"""
    st = raw_settings(book)
    if "mode" in patch and patch["mode"] is not None:
        if patch["mode"] not in MODES:
            raise ValueError("mode 只能是 serial 或 wanben")
        book.mode = patch["mode"]
    for k in DEFAULTS:
        if k in patch and patch[k] is not None:
            st[k] = norm_ranges(patch[k]) if k == "refine_ranges" else patch[k]
    if st["refine_scope"] not in REFINE_SCOPES:
        raise ValueError("refine_scope 只能是 first_n / all / custom / none")
    book.wanben = st
    if book_mode(book) == "wanben":
        book.target_words = int(st["target_words"])
        book.chapter_words = int(st["chapter_words"])
    book.updated_at = utcnow()
    s.add(book)
    s.commit()
    s.refresh(book)
    return settings_out(s, book)


def edit_refine(s: Session, book: Book, action: str, ranges: Any) -> dict[str, Any]:
    """把章/章号范围加入（add）、移出（remove）或替换（set）精修范围。会先把当前范围展开成自定义集合。"""
    st = raw_settings(book)
    total = total_chapters_for(st["target_words"], st["chapter_words"])
    cur = set(refine_numbers(st, total, _written_max(s, book.id or 0)))
    given: set[int] = set()
    for a, b in norm_ranges(ranges):
        given.update(range(a, b + 1))
    if action == "add":
        cur |= given
    elif action == "remove":
        cur -= given
    elif action == "set":
        cur = given
    else:
        raise ValueError("action 只能是 add / remove / set")
    return update_settings(s, book, {"refine_scope": "custom", "refine_ranges": [[n, n] for n in sorted(cur)]})


def require_wanben(book: Book) -> None:
    if book_mode(book) != "wanben":
        raise Conflict("本书是连载模式，请先在完本设置里把模式切换为完本（mode=wanben）")


# ------------------------------------------------------------------ 卷规划读写（存在卷节点 beats["wanben"]）

def _vol_plan(v: OutlineNode) -> dict[str, Any]:
    return dict((v.beats or {}).get("wanben") or {})


def volumes(s: Session, book_id: int) -> list[OutlineNode]:
    return sorted([n for n in common.outline_nodes(s, book_id) if n.level == "volume"], key=lambda n: n.order)


def volume_for(vols: list[OutlineNode], number: int) -> OutlineNode | None:
    for v in vols:
        p = _vol_plan(v)
        if p.get("start") and p.get("end") and int(p["start"]) <= number <= int(p["end"]):
            return v
    return None


def _vol_brief(v: OutlineNode) -> dict[str, Any]:
    p = _vol_plan(v)
    out = {"node_id": v.id, "order": v.order, "title": v.title, "summary": v.summary,
           "start": p.get("start"), "end": p.get("end"), "crisis": p.get("crisis", ""),
           "climax_chapter": p.get("climax_chapter"), "closure": p.get("closure", "")}
    if p.get("finale"):
        out["finale"] = p["finale"]
    return out


def _alloc_ranges(total: int, n_vol: int, min_ends: list[int]) -> list[tuple[int, int]]:
    """按总章数平均切卷区间；已有章细纲的卷，区间至少要盖住它已有的章号。"""
    out: list[tuple[int, int]] = []
    start = 1
    for i in range(n_vol):
        if i == n_vol - 1:
            end = max(total, start, min_ends[i])
        else:
            end = max(round(total * (i + 1) / n_vol), start, min_ends[i])
        out.append((start, end))
        start = end + 1
    return out


def plan_job(book_id: int, ctx: JobContext) -> dict[str, Any]:
    """字数目标倒推规划。没有大纲时先按现有流程生成大纲；已有大纲时只补缺 / 按新目标调整卷区间，返回差异。"""
    with session_scope() as s:
        book = common.get_book(s, book_id)
        require_wanben(book)
        has_outline = bool(common.outline_nodes(s, book_id))
    if not has_outline:
        ctx.progress(5, "还没有大纲：先生成总纲、卷与前两弧")
        outline.generate_outline(book_id, ctx)

    warnings: list[str] = []
    with session_scope() as s:
        book = common.get_book(s, book_id)
        st = raw_settings(book)
        total = total_chapters_for(st["target_words"], st["chapter_words"])
        nodes = common.outline_nodes(s, book_id)
        root = next((n for n in nodes if n.level == "book"), None)
        vols = volumes(s, book_id)
        arcs = [n for n in nodes if n.level == "arc"]
        chs = [n for n in nodes if n.level == "chapter"]
        written = _written_max(s, book_id)
        old_total = int(((root.beats or {}).get("wanben") or {}).get("total_chapters") or 0) if root else 0
        # 每卷已有章细纲的最大章号
        arc_vol = {a.id: a.parent_id for a in arcs}
        vol_max: dict[int, int] = {}
        for c in chs:
            vid = arc_vol.get(c.parent_id)
            if vid is not None:
                vol_max[vid] = max(vol_max.get(vid, 0), c.order)
        floor_total = max([written, *vol_max.values()] or [0])
        if total < floor_total:
            warnings.append(f"按目标字数算出 {total} 章，但已经写/规划到第 {floor_total} 章；总章数按 {floor_total} 章算，"
                            "如要更短，请先删掉多出的章细纲或调整目标字数")
            total = floor_total
        n_vol = min(MAX_VOLUMES, max(MIN_VOLUMES, math.ceil(total / CHAPTERS_PER_VOLUME)))
        # 已有卷比需要的多：后面没有任何章细纲的卷可以删，有章细纲的卷保留
        keep_n = n_vol
        for i, v in enumerate(vols):
            if i >= n_vol and vol_max.get(v.id or 0):
                keep_n = i + 1
        n_vol = max(n_vol, keep_n)
        removed = [v for v in vols[n_vol:]]
        kept = vols[:n_vol]
        min_ends = [vol_max.get(v.id or 0, 0) for v in kept] + [0] * (n_vol - len(kept))
        ranges = _alloc_ranges(total, n_vol, min_ends)
        # 前面的卷已经占满总章数：后面没有章细纲的卷没有章可分，去掉（最后剩下的那一卷承担结局）
        while n_vol > 1 and ranges[-1][0] > total and not min_ends[n_vol - 1]:
            n_vol -= 1
            min_ends = min_ends[:n_vol]
            ranges = _alloc_ranges(total, n_vol, min_ends)
        removed = vols[n_vol:]
        kept = vols[:n_vol]
        before = {v.order: _vol_brief(v) for v in vols}
        vol_info = []
        for i, (a, b) in enumerate(ranges):
            v = kept[i] if i < len(kept) else None
            vol_info.append({"order": i + 1, "start": a, "end": b, "title": v.title if v else "", "summary": v.summary if v else "",
                             **({k: _vol_plan(v).get(k) for k in ("crisis", "climax_chapter", "closure")} if v else {})})
        meta = {**common.kit_meta(s, book), "volumes": vol_info, "total_chapters": total, "written": written}
        user = render("wanben_plan", book_context=common.book_context(s, book), book_summary=(root.summary if root else "") or "（无）",
                      target_words=st["target_words"], chapter_words=st["chapter_words"], total_chapters=total,
                      volumes="\n".join(f"- 第{x['order']}卷（第{x['start']}–{x['end']}章）{x['title'] or '（未命名）'}：{x['summary'] or '（无概要）'}"
                                        for x in vol_info),
                      written=written)
    ctx.progress(40, f"倒推卷纲：{total} 章 / {n_vol} 卷")
    data = get_gateway().chat_json("wanben_plan", system_prompt("outline"), user, meta=meta)
    if not isinstance(data, dict):
        raise ValueError("完本规划结果不是 JSON 对象")
    got = {int(v.get("order") or 0): v for v in (data.get("volumes") or []) if isinstance(v, dict)}
    finale_raw = data.get("finale") if isinstance(data.get("finale"), dict) else {}
    ctx.progress(75, "写入卷纲")
    diff: list[dict[str, Any]] = []
    with session_scope() as s:
        book = common.get_book(s, book_id)
        root = next((n for n in common.outline_nodes(s, book_id) if n.level == "book"), None)
        if root is None:
            root = OutlineNode(book_id=book_id, level="book", order=1, title=book.title, summary="", status="expanded")
            s.add(root)
            s.flush()
        vols = volumes(s, book_id)
        for v in vols[n_vol:]:  # 多出来、且下面没有章细纲的卷：连同空弧一起删
            if v.locked:
                continue
            for a in [n for n in common.outline_nodes(s, book_id) if n.level == "arc" and n.parent_id == v.id]:
                s.delete(a)
            s.delete(v)
        s.flush()
        vols = vols[:n_vol]
        for i, (a, b) in enumerate(ranges):
            order = i + 1
            g = got.get(order) or {}
            v = vols[i] if i < len(vols) else None
            if v is None:
                v = OutlineNode(book_id=book_id, parent_id=root.id, level="volume", order=order,
                                title=str(g.get("title") or f"第{order}卷"), summary=str(g.get("summary") or ""), status="planned")
                s.add(v)
                s.flush()
                action = "added"
            else:
                action = "unchanged"
                if v.locked:
                    pass
                elif not (v.title or "").strip() and g.get("title"):
                    v.title = str(g["title"])[:80]
                if not v.locked and not (v.summary or "").strip() and g.get("summary"):
                    v.summary = str(g["summary"])
            old = _vol_plan(v)
            range_changed = (old.get("start"), old.get("end")) != (a, b)
            plan = dict(old)
            plan["start"], plan["end"] = a, b
            for k in ("crisis", "closure"):
                if g.get(k) and (not plan.get(k) or range_changed):
                    plan[k] = str(g[k])[:300]
                plan.setdefault(k, "")
            cl = g.get("climax_chapter")
            old_cl = plan.get("climax_chapter")
            if not (isinstance(old_cl, int) and a <= old_cl <= b) or range_changed:
                try:
                    cl = int(cl)
                except (TypeError, ValueError):
                    cl = 0
                plan["climax_chapter"] = cl if a <= cl <= b else max(a, b - max(1, (b - a + 1) // 10))
            if not plan.get("crisis"):
                plan["crisis"] = f"第{order}卷的核心麻烦压到主角身上"
            if not plan.get("closure"):
                plan["closure"] = "卷末解决本卷危机，留一个通往下一卷的钩子"
            if order == n_vol:  # 最后一卷：必须有完整结局
                fin = dict(plan.get("finale") or {})
                for k in ("resolution", "last_chapter_beat"):
                    if finale_raw.get(k) and (not fin.get(k) or range_changed):
                        fin[k] = str(finale_raw[k])[:400]
                for k in ("payoffs", "endings"):
                    if isinstance(finale_raw.get(k), list) and (not fin.get(k) or range_changed):
                        fin[k] = [str(x)[:200] for x in finale_raw[k] if x][:10]
                fin.setdefault("resolution", "主线终极冲突在最后几章正面了结，主角付出代价拿到结果")
                fin.setdefault("payoffs", ["全部未回收的长线伏笔在最后一卷回收"])
                fin.setdefault("endings", ["主要人物各有归宿"])
                fin.setdefault("last_chapter_beat", f"第{b}章：结局落地后的收尾一幕，不留悬而未决的主线")
                fin["last_chapter"] = b
                plan["finale"] = fin
            else:
                plan.pop("finale", None)
            if plan != old and action == "unchanged":
                action = "updated"
            v.order = order
            v.beats = {**(v.beats or {}), "wanben": plan}
            s.add(v)
            s.flush()
            entry: dict[str, Any] = {"order": order, "node_id": v.id, "action": action, "after": _vol_brief(v)}
            if action != "added":
                entry["before"] = before.get(order)
                entry["changed"] = sorted(k for k in ("start", "end", "crisis", "climax_chapter", "closure", "finale", "title", "summary")
                                          if (before.get(order) or {}).get(k) != entry["after"].get(k))
            diff.append(entry)
        for v in removed:
            diff.append({"order": v.order, "node_id": v.id, "action": "removed", "before": before.get(v.order)})
        rplan = dict((root.beats or {}).get("wanben") or {})
        ending = str(data.get("ending") or "").strip()
        rplan.update({"total_chapters": total, "target_words": st["target_words"], "chapter_words": st["chapter_words"],
                      "volumes": n_vol, "planned_at": utcnow().isoformat()})
        if ending and (not rplan.get("ending") or old_total != total):
            rplan["ending"] = ending[:300]
        root.beats = {**(root.beats or {}), "wanben": rplan}
        if rplan.get("ending") and "结局" not in (root.summary or ""):
            root.summary = ((root.summary or "") + f"\n全书结局：{rplan['ending']}").strip()
        s.add(root)
        annotate_roles(s, book_id)
        book.updated_at = utcnow()
        s.add(book)
        s.commit()
        vol_out = [_vol_brief(v) for v in volumes(s, book_id)]
    return {"total_chapters": {"before": old_total or None, "after": total}, "volumes": vol_out, "diff": diff,
            "warnings": warnings, "chapter_words": st["chapter_words"], "target_words": st["target_words"]}


def annotate_roles(s: Session, book_id: int) -> int:
    """给本卷高潮章、卷末章、全书最后一章的章细纲标上 wanben_role（写进细纲 JSON，写章提示词能看到）。已写的章不动。"""
    vols = volumes(s, book_id)
    chs = {n.order: n for n in common.outline_nodes(s, book_id) if n.level == "chapter"}
    n_marked = 0
    for i, v in enumerate(vols):
        p = _vol_plan(v)
        if not p.get("end"):
            continue
        roles: dict[int, str] = {}
        if p.get("climax_chapter"):
            roles[int(p["climax_chapter"])] = f"本卷高潮章：本卷危机「{p.get('crisis', '')}」在这一章正面爆发并迎来转折"
        roles.setdefault(int(p["end"]), f"本卷收束章：{p.get('closure', '')}")
        fin = p.get("finale") or {}
        if fin and i == len(vols) - 1:
            roles[int(p["end"])] = (f"全书最后一章（完结章）：{fin.get('last_chapter_beat', '')}；主线了结：{fin.get('resolution', '')}。"
                                    "写成完整结局，不留悬念钩子，不写未完待续")
        for num, text in roles.items():
            node = chs.get(num)
            if node is None or node.status == "written" or node.locked:
                continue
            b = dict(node.beats or {})
            if b.get("wanben_role") != text:
                b["wanben_role"] = text[:300]
                node.beats = b
                s.add(node)
                n_marked += 1
    return n_marked


def plan_summary(s: Session, book_id: int) -> dict[str, Any]:
    nodes = common.outline_nodes(s, book_id)
    root = next((n for n in nodes if n.level == "book"), None)
    rplan = ((root.beats or {}).get("wanben") or {}) if root else {}
    return {"planned": bool(rplan.get("total_chapters")), "total_chapters": rplan.get("total_chapters"),
            "ending": rplan.get("ending", ""), "planned_at": rplan.get("planned_at"),
            "volumes": [_vol_brief(v) for v in volumes(s, book_id)]}


# ------------------------------------------------------------------ 补齐章细纲（按卷区间滚动展开）

def ensure_nodes(book_id: int, upto: int, ctx: Any) -> int:
    """保证第 1..upto 章都有章细纲：在章号所属的卷下找空弧或新建一弧，复用 outline.expand_node 展开 5 章；
    展开越过卷区间末尾的章细纲删掉（下一卷从自己的区间起写）。返回新建的章细纲数。"""
    created = 0
    for _ in range(max(8, upto // 2 + 8)):
        with session_scope() as s:
            n = outline.max_chapter_number(s, book_id) + 1
            if n > upto:
                break
            vols = volumes(s, book_id)
            vol = volume_for(vols, n)
            if vol is None:
                raise Conflict(f"第{n}章不在任何卷的章号区间里，请先做完本规划（POST /wanben/plan）")
            p = _vol_plan(vol)
            arcs = sorted([x for x in common.outline_nodes(s, book_id) if x.level == "arc" and x.parent_id == vol.id], key=lambda x: x.order)
            ch_parents = {x.parent_id for x in common.outline_nodes(s, book_id) if x.level == "chapter"}
            empty = next((a for a in arcs if a.id not in ch_parents), None)
            if empty is None:
                hi = min(n + outline.CHAPTERS_PER_ARC - 1, int(p["end"]))
                bits = [f"本弧覆盖第{n}–{hi}章，推进本卷危机：{p.get('crisis', '')}"]
                if p.get("climax_chapter") and n <= int(p["climax_chapter"]) <= hi:
                    bits.append(f"第{p['climax_chapter']}章是本卷高潮")
                if n <= int(p["end"]) <= hi:
                    bits.append(f"第{p['end']}章收束本卷：{p.get('closure', '')}")
                    fin = p.get("finale") or {}
                    if fin:
                        bits.append(f"全书在第{p['end']}章完结：{fin.get('resolution', '')}")
                empty = OutlineNode(book_id=book_id, parent_id=vol.id, level="arc", order=len(arcs) + 1,
                                    title=f"第{len(arcs) + 1}弧", summary="；".join(bits), status="planned")
                s.add(empty)
                s.commit()
                s.refresh(empty)
            arc_id, vol_end = empty.id or 0, int(p["end"])
        ctx.progress(3, f"补齐章细纲：展开第{n}章起的一弧")
        r = outline.expand_node(arc_id, ctx)
        created += len(r.get("created") or [])
        with session_scope() as s:
            extra = [x for x in common.outline_nodes(s, book_id) if x.level == "chapter" and x.parent_id == arc_id
                     and x.order > vol_end and x.status != "written" and x.chapter_id is None and not x.locked]
            for x in extra:
                s.delete(x)
                created -= 1
            annotate_roles(s, book_id)
            s.commit()
    return created


# ------------------------------------------------------------------ 批次抽检

_OPEN_STRONG = re.compile(r"突然|猛地|一把|怒|冷笑|逼|杀|血|死|滚|跪|拦|抢|骂|欠|债|输|赌|威胁|废物|凭什么|找死|动手|撕|砸|踹|掐|撞|吼|喝道|闭嘴|住手|退婚|开除|赶出|抵押|追债")
_OPEN_PUNCT = re.compile(r"[！？!?]")
_CLIMAX_RX = re.compile(r"[！!]|轰|炸|跪|震|惊|全场|鸦雀无声|反杀|碾压|打脸|翻盘|破境|突破")
_KIND_RX = {"name": re.compile(r"人名|名字|称呼|叫法|出场|角色"), "number": re.compile(r"数字|数值|年龄|金额|钱|万|岁|次数|时间"),
            "power": re.compile(r"战力|境界|等级|修为|实力|级|阶|品|段位|能力")}


def _consistency(review: dict[str, Any], lint: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in (review or {}).get("issues") or []:
        dim = it.get("dimension")
        comment = str(it.get("comment") or "")
        kind = next((k for k, rx in _KIND_RX.items() if rx.search(comment)), "")
        if dim == "continuity" or (dim == "character" and kind == "name") or kind == "power":
            out.append({"kind": kind or "continuity", "severity": it.get("severity"), "quote": str(it.get("quote") or "")[:80],
                        "comment": comment[:160]})
    for it in (lint or {}).get("numeric_conflicts") or []:
        if isinstance(it, dict):
            out.append({"kind": "number", "severity": it.get("severity", "mid"), "quote": str(it.get("quote") or "")[:80],
                        "comment": str(it.get("comment") or it.get("hint") or "")[:160]})
    return out


def chapter_check(ch: Chapter, beats: dict[str, Any], chapter_words: int, in_refine: bool) -> dict[str, Any]:
    """一章的抽检：字数、开头前 100 字是否切入冲突、高潮点、章末钩子、一致性问题、读者分、未过项。纯程序判断。"""
    content = ch.content or ""
    review = ch.review or {}
    lint = ch.lint or {}
    head = re.sub(r"\s+", "", content)[:100]
    hits = sorted(set(_OPEN_STRONG.findall(head)))
    opening_ok = bool(hits) or bool(_OPEN_PUNCT.search(head) and "“" in head)
    paras = [p for p in re.split(r"\n\s*\n", content) if p.strip()]
    peak_i, peak_v = -1, 0
    for i, p in enumerate(paras):
        v = len(_CLIMAX_RX.findall(p))
        if v > peak_v:
            peak_i, peak_v = i, v
    climax = {"planned": str(beats.get("payoff") or "")[:120], "type": beats.get("payoff_type", ""),
              "found": peak_v > 0, "position": round((peak_i + 1) / len(paras), 2) if paras and peak_i >= 0 else None,
              "quote": re.sub(r"\s+", "", paras[peak_i])[:60] if peak_i >= 0 else ""}
    end_issue = ending_issue(content) if content.strip() else None
    tail = re.sub(r"\s+", "", content)[-80:]
    hook = {"planned": str(beats.get("hook_end") or "")[:120], "type": beats.get("hook_type", ""), "tail": tail,
            "ok": bool(content.strip()) and end_issue is None,
            "comment": (end_issue or {}).get("comment", "")}
    reader = review.get("reader") or {}
    rscore = reader.get("score") if isinstance(reader.get("score"), int) else None
    words = ch.words or 0
    lo, hi = int(chapter_words * 0.7), int(chapter_words * 1.5)
    cons = _consistency(review, lint)
    failed: list[str] = []
    if not content.strip():
        failed.append("正文为空（多版本未采纳）")
    if words and not (lo <= words <= hi):
        failed.append(f"字数 {words} 偏离每章目标 {chapter_words}（{lo}–{hi}）")
    if content.strip() and not opening_ok:
        failed.append("开头前 100 字没有切进冲突")
    if content.strip() and not climax["found"]:
        failed.append("没找到明显的高潮点")
    if content.strip() and not hook["ok"]:
        failed.append("章末钩子落空")
    if any(c["severity"] == "high" for c in cons):
        failed.append("有 high 级一致性问题")
    if rscore is not None and rscore < READER_PASS:
        failed.append(f"读者分 {rscore} 低于阈值 {READER_PASS}")
    if review and not review.get("passed"):
        failed.append("审稿未通过")
    return {"number": ch.number, "chapter_id": ch.id, "title": ch.title, "status": ch.status, "in_refine": in_refine,
            "words": words, "words_target": chapter_words, "words_ok": bool(words) and lo <= words <= hi,
            "opening": {"head": head, "conflict": opening_ok, "hits": hits},
            "climax": climax, "hook": hook, "consistency": cons,
            "review_overall": ((review.get("scores") or {}).get("overall")), "review_passed": bool(review.get("passed")),
            "reader_score": rscore, "reader_below_threshold": rscore is not None and rscore < READER_PASS,
            "failed": failed, "passed": not failed}


def build_report(s: Session, book_id: int, chapter_ids: list[int], refine: set[int]) -> dict[str, Any]:
    book = common.get_book(s, book_id)
    st = raw_settings(book)
    items = []
    for cid in chapter_ids:
        ch = s.get(Chapter, cid)
        if ch is None:
            continue
        node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
        items.append(chapter_check(ch, (node.beats if node else None) or {}, int(st["chapter_words"]), ch.number in refine))
    scores = [x["reader_score"] for x in items if x["reader_score"] is not None]
    return {"chapters": items, "summary": {
        "count": len(items), "words": sum(x["words"] for x in items),
        "passed": sum(1 for x in items if x["passed"]), "failed": sum(1 for x in items if not x["passed"]),
        "committed": sum(1 for x in items if x["status"] == "committed"),
        "awaiting_approval": [x["number"] for x in items if x["in_refine"] and x["status"] != "committed"],
        "reader_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "reader_below_threshold": [x["number"] for x in items if x["reader_below_threshold"]],
        "consistency_issues": sum(len(x["consistency"]) for x in items),
    }, "reader_threshold": READER_PASS, "generated_at": utcnow().isoformat()}


def batch_out(b: WanbenBatch, with_report: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"id": b.id, "book_id": b.book_id, "job_id": b.job_id, "seq": b.seq, "start_no": b.start_no, "end_no": b.end_no,
                           "status": b.status, "stop_reason": b.stop_reason, "message": b.message, "chapter_ids": list(b.chapter_ids or []),
                           "created_at": b.created_at.isoformat() if b.created_at else None,
                           "finished_at": b.finished_at.isoformat() if b.finished_at else None}
    rep = b.report or {}
    out["summary"] = rep.get("summary")
    if with_report:
        out["report"] = rep or None
    return out


# ------------------------------------------------------------------ 分批连写

class _BatchSubContext:
    """批量里写单章用的上下文：进度折算到本批；断点嵌进批次断点（chapter_cp），续跑时整批从断点接着写。
    （仿 writing._SubContext，但不是它的子类，所以 write_next 会正常存每一步的断点。）"""

    def __init__(self, parent: JobContext, i: int, n: int, state: dict[str, Any]) -> None:
        self.parent, self.i, self.n, self.state = parent, i, n, state
        self.job_id, self.book_id = parent.job_id, parent.book_id
        self.resume_state = None

    def progress(self, pct: int, message: str = "") -> None:
        self.parent.progress(int((self.i * 100 + pct) / max(1, self.n)), f"[{self.i + 1}/{self.n}] {message}")

    def checkpoint(self, stage: str, state: dict[str, Any], kind: str = "") -> None:
        self.state["chapter_cp"] = dict(state)
        save_checkpoint(self.job_id, f"batch:{self.state.get('batch_id')}:ch:{stage}", self.state, kind=BATCH_KIND, book_id=self.book_id)


def _paused(book_id: int) -> bool:
    with session_scope() as s:
        return bool(kv_get(s, _pause_key(book_id), False))


def set_pause(book_id: int, value: bool) -> None:
    with session_scope() as s:
        kv_set(s, _pause_key(book_id), bool(value))


def _finish_batch(batch_id: int, status: str, reason: str, message: str, refine: set[int]) -> dict[str, Any]:
    with session_scope() as s:
        b = s.get(WanbenBatch, batch_id)
        assert b is not None
        b.status, b.stop_reason, b.message = status, reason, message
        b.report = build_report(s, b.book_id, list(b.chapter_ids or []), refine)
        b.finished_at = utcnow()
        s.add(b)
        s.commit()
        s.refresh(b)
        return batch_out(b, with_report=False)


def batch_job(book_id: int, ctx: JobContext, force: bool = False, resume: dict[str, Any] | None = None) -> dict[str, Any]:
    """分批连写。auto_continue=False：写一批就停；True：连续跑批到目标章数，或遇到失败 / 暂停 / 需要作者处理时停。"""
    state: dict[str, Any] = dict(resume if resume is not None else (ctx.resume_state or {}))
    force = bool(state.get("force", force))
    state["force"] = force
    state.setdefault("batch_ids", [])
    outs: list[dict[str, Any]] = []
    result: dict[str, Any] = {"batch_ids": state["batch_ids"], "stopped": False, "reason": "", "message": ""}
    while True:
        r = _run_one_batch(book_id, ctx, state)
        if r.get("batch"):
            outs.append(r["batch"])
        result.update({"stopped": r["stopped"], "reason": r["reason"], "message": r["message"]})
        state.pop("current", None)
        state.pop("chapter_cp", None)
        with session_scope() as s:
            auto = bool(raw_settings(common.get_book(s, book_id))["auto_continue"])
        if r["stopped"] or not auto:
            break
        save_checkpoint(ctx.job_id, "batch:between", state, kind=BATCH_KIND, book_id=book_id)
    result["batches"] = outs
    with session_scope() as s:
        result["progress"] = progress(s, book_id)
    return result


def _run_one_batch(book_id: int, ctx: JobContext, state: dict[str, Any]) -> dict[str, Any]:
    force = bool(state.get("force"))
    with session_scope() as s:
        book = common.get_book(s, book_id)
        require_wanben(book)
        st = raw_settings(book)
        total = total_chapters_for(st["target_words"], st["chapter_words"])
        rplan = plan_summary(s, book_id)
        if rplan.get("total_chapters"):
            total = max(total, int(rplan["total_chapters"]))
        refine = set(refine_numbers(st, total, _written_max(s, book_id)))
        pause_refine = bool(st["pause_on_unapproved_refine"]) and not force
        pending = list(s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.status != "committed").order_by(Chapter.number)))
        planned = rplan.get("planned")
    cur = state.get("current")
    if cur is None:
        if _paused(book_id):
            return {"stopped": True, "reason": "paused", "message": "已暂停", "batch": None}
        if not planned:
            ctx.progress(2, "还没有完本规划：先按字数目标倒推卷纲")
            plan_job(book_id, ctx)
            with session_scope() as s:
                total = max(total, int(plan_summary(s, book_id).get("total_chapters") or 0))
        other = [c.number for c in pending if c.number not in refine]
        pend_ref = [c.number for c in pending if c.number in refine]
        if other:
            return {"stopped": True, "reason": "pending_chapter",
                    "message": f"第{other[0]}章还没提交（审稿未过或等待选版本），处理后再继续连写", "batch": None}
        if pend_ref and pause_refine:
            return {"stopped": True, "reason": "refine_pending",
                    "message": f"精修范围内第{'、'.join(map(str, pend_ref))}章待审批；审批后继续，或传 force=true / 关闭「精修待审批时暂停」",
                    "batch": None}
        with session_scope() as s:
            start = _written_max(s, book_id) + 1
            if start > total:
                return {"stopped": True, "reason": "target_reached", "message": f"已写满目标 {total} 章", "batch": None}
            end = min(start + int(st["batch_size"]) - 1, total)
            seq = int(s.exec(select(func.count()).where(WanbenBatch.book_id == book_id)).one() or 0) + 1
            b = WanbenBatch(book_id=book_id, job_id=ctx.job_id, seq=seq, start_no=start, end_no=end, status="running")
            s.add(b)
            s.commit()
            s.refresh(b)
            batch_id = b.id or 0
        cur = {"batch_id": batch_id, "start": start, "end": end}
        state["current"] = cur
        state["batch_id"] = batch_id
        state["batch_ids"] = [*state["batch_ids"], batch_id]
        save_checkpoint(ctx.job_id, f"batch:{batch_id}:start", state, kind=BATCH_KIND, book_id=book_id)
    batch_id, start, end = int(cur["batch_id"]), int(cur["start"]), int(cur["end"])
    state["batch_id"] = batch_id
    with session_scope() as s:
        b = s.get(WanbenBatch, batch_id)
        if b is not None and b.status != "running":
            b.status, b.job_id = "running", ctx.job_id
            s.add(b)
            s.commit()
    try:
        ctx.progress(3, f"第{start}–{end}章：补齐章细纲")
        ensure_nodes(book_id, end, ctx)
        n_total = end - start + 1
        while True:
            with session_scope() as s:
                b = s.get(WanbenBatch, batch_id)
                assert b is not None
                done_ids = list(b.chapter_ids or [])
                nxt = _written_max(s, book_id) + 1
                pend_ref = [c.number for c in s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.status != "committed"))
                            if c.number in refine]
            chapter_cp = state.get("chapter_cp") or None
            if chapter_cp and chapter_cp.get("chapter_id"):
                nxt = int(chapter_cp.get("number") or nxt)
            if nxt > end and not chapter_cp:
                return {"stopped": False, "reason": "", "message": f"本批第{start}–{end}章写完",
                        "batch": _finish_batch(batch_id, "done", "", f"本批第{start}–{end}章写完", refine)}
            if _paused(book_id) and not chapter_cp:
                return {"stopped": True, "reason": "paused", "message": "作者暂停",
                        "batch": _finish_batch(batch_id, "paused", "paused", f"已暂停（写到第{nxt - 1}章）", refine)}
            in_refine = nxt in refine
            sub = _BatchSubContext(ctx, min(len(done_ids), n_total - 1), n_total, state)
            r = writing.write_next(book_id, sub, 1, resume=chapter_cp, no_commit=in_refine,  # type: ignore[arg-type]
                                   allow_pending=pend_ref if pend_ref else None)
            state.pop("chapter_cp", None)
            with session_scope() as s:
                b = s.get(WanbenBatch, batch_id)
                assert b is not None
                if r.get("chapter_id") and r["chapter_id"] not in (b.chapter_ids or []):
                    b.chapter_ids = [*(b.chapter_ids or []), int(r["chapter_id"])]
                    s.add(b)
                    s.commit()
            save_checkpoint(ctx.job_id, f"batch:{batch_id}:ch{r.get('number')}", state, kind=BATCH_KIND, book_id=book_id)
            if r.get("committed"):
                continue
            num = r.get("number") or nxt
            if r.get("awaiting_approval"):
                if pause_refine:
                    msg = f"第{num}章在精修范围内，已写好等待审批；审批后继续连写"
                    return {"stopped": True, "reason": "refine_pending", "message": msg,
                            "batch": _finish_batch(batch_id, "stopped", "refine_pending", msg, refine)}
                continue
            reason = "awaiting_adopt" if r.get("awaiting_adopt") else "review_failed"
            msg = f"第{num}章：{r.get('reason') or '未能自动提交'}"
            return {"stopped": True, "reason": reason, "message": msg,
                    "batch": _finish_batch(batch_id, "stopped", reason, msg, refine)}
    except Exception as e:
        _finish_batch(batch_id, "failed", "error", f"出错：{e}"[:500], refine)
        raise


def _resume_batch(job: Any, state: dict[str, Any]) -> Any:
    book_id = int(job.book_id or 0)
    set_pause(book_id, False)
    return lambda ctx: batch_job(book_id, ctx, resume=state)


register_resumable(BATCH_KIND, _resume_batch)


def list_batches(s: Session, book_id: int) -> list[dict[str, Any]]:
    rows = s.exec(select(WanbenBatch).where(WanbenBatch.book_id == book_id).order_by(WanbenBatch.id.desc())).all()  # type: ignore[union-attr]
    return [batch_out(b, with_report=False) for b in rows]


def get_batch(s: Session, book_id: int, batch_id: int) -> dict[str, Any]:
    b = s.get(WanbenBatch, batch_id)
    if b is None or b.book_id != book_id:
        raise NotFound("批次不存在")
    return batch_out(b)


def close_stale_batches(book_id: int) -> int:
    """发起新批次前：任务已不在跑（服务重启后没续跑、被放弃）却还标着 running 的批次，标为 failed。"""
    from app.models.tables import Job

    n = 0
    with session_scope() as s:
        for b in s.exec(select(WanbenBatch).where(WanbenBatch.book_id == book_id, WanbenBatch.status == "running")):
            job = s.get(Job, b.job_id) if b.job_id else None
            if job is None or job.status not in ("queued", "running"):
                b.status, b.stop_reason = "failed", "error"
                b.message = (b.message + "；" if b.message else "") + "任务已中断（未续跑）"
                b.finished_at = utcnow()
                s.add(b)
                n += 1
        s.commit()
    return n


def running_batch(s: Session, book_id: int) -> WanbenBatch | None:
    return s.exec(select(WanbenBatch).where(WanbenBatch.book_id == book_id, WanbenBatch.status == "running")
                  .order_by(WanbenBatch.id.desc())).first()  # type: ignore[union-attr]


# ------------------------------------------------------------------ 精修范围汇总

def refine_summary(s: Session, book_id: int) -> dict[str, Any]:
    book = common.get_book(s, book_id)
    st = raw_settings(book)
    total = total_chapters_for(st["target_words"], st["chapter_words"])
    nums = refine_numbers(st, total, _written_max(s, book_id))
    by_no = {c.number: c for c in s.exec(select(Chapter).where(Chapter.book_id == book_id))}
    pend_iter: dict[int, int] = {}
    for it in s.exec(select(WanbenIteration).where(WanbenIteration.book_id == book_id, WanbenIteration.status == "pending")):
        pend_iter[it.number] = pend_iter.get(it.number, 0) + 1
    rows = []
    for n in nums:
        c = by_no.get(n)
        if c is None:
            rows.append({"number": n, "chapter_id": None, "title": "", "status": "unwritten", "approved": False, "words": 0,
                         "review_overall": None, "review_passed": None, "reader_score": None, "reader_below_threshold": False,
                         "iterations_pending": pend_iter.get(n, 0)})
            continue
        rv = c.review or {}
        reader = rv.get("reader") or {}
        rs = reader.get("score") if isinstance(reader.get("score"), int) else None
        rows.append({"number": n, "chapter_id": c.id, "title": c.title, "status": c.status, "approved": c.status == "committed",
                     "words": c.words, "review_overall": (rv.get("scores") or {}).get("overall"), "review_passed": bool(rv.get("passed")) if rv else None,
                     "reader_score": rs, "reader_below_threshold": rs is not None and rs < READER_PASS,
                     "iterations_pending": pend_iter.get(n, 0)})
    written = [r for r in rows if r["status"] != "unwritten"]
    return {"book_id": book_id, "refine_scope": st["refine_scope"], "golden_chapters": st["golden_chapters"],
            "refine_ranges": st["refine_ranges"], "pause_on_unapproved_refine": st["pause_on_unapproved_refine"],
            "numbers": nums, "total": len(nums), "written": len(written),
            "approved": sum(1 for r in rows if r["approved"]),
            "pending": [r["number"] for r in rows if r["status"] not in ("unwritten", "committed")],
            "unwritten": sum(1 for r in rows if r["status"] == "unwritten"),
            "reader_below_threshold": [r["number"] for r in rows if r["reader_below_threshold"]],
            "all_approved": all(r["approved"] for r in rows) if rows else True,
            "reader_threshold": READER_PASS, "chapters": rows}


# ------------------------------------------------------------------ 进度

def progress(s: Session, book_id: int) -> dict[str, Any]:
    book = common.get_book(s, book_id)
    st = raw_settings(book)
    total = total_chapters_for(st["target_words"], st["chapter_words"])
    plan = plan_summary(s, book_id)
    if plan.get("total_chapters"):
        total = max(total, int(plan["total_chapters"]))
    stats = common.book_stats(s, book_id)
    written_max = _written_max(s, book_id)
    pending_words = int(s.exec(select(func.coalesce(func.sum(Chapter.words), 0))
                               .where(Chapter.book_id == book_id, Chapter.status != "committed")).one() or 0)
    vols = volumes(s, book_id)
    cur_no = min(written_max + 1, total) if written_max < total else total
    vol = volume_for(vols, cur_no)
    last = s.exec(select(WanbenBatch).where(WanbenBatch.book_id == book_id).order_by(WanbenBatch.id.desc())).first()  # type: ignore[union-attr]
    target = int(st["target_words"])
    return {"book_id": book_id, "mode": book_mode(book), "words": stats["words"], "pending_words": pending_words,
            "target_words": target, "ratio": round(min(1.0, stats["words"] / target), 4) if target else 0.0,
            "chapters_committed": stats["chapters"], "chapters_written": written_max, "chapters_total": total,
            "chapters_remaining": max(0, total - written_max),
            "current_volume": ({"order": vol.order, "title": vol.title, "start": _vol_plan(vol).get("start"),
                                "end": _vol_plan(vol).get("end"), "node_id": vol.id} if vol else None),
            "planned": bool(plan.get("planned")), "paused": bool(kv_get(s, _pause_key(book_id), False)),
            "running_batch_id": (running_batch(s, book_id).id if running_batch(s, book_id) else None),  # type: ignore[union-attr]
            "last_batch": batch_out(last, with_report=False) if last else None}


# ------------------------------------------------------------------ 章节迭代

def _scores(review: dict[str, Any] | None) -> dict[str, Any]:
    rv = review or {}
    reader = rv.get("reader") or {}
    return {"overall": (rv.get("scores") or {}).get("overall"),
            "reader": reader.get("score") if isinstance(reader.get("score"), int) else None,
            "passed": bool(rv.get("passed")) if rv else None,
            "issues": len([i for i in rv.get("issues") or [] if i.get("severity") in ("high", "mid")])}


def _delta(a: Any, b: Any) -> Any:
    return (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None


def _issues_instruction(review: dict[str, Any], user_ins: str) -> str:
    lines = []
    for it in (review or {}).get("issues") or []:
        if it.get("severity") in ("high", "mid"):
            lines.append(f"- [{it.get('severity')}/{it.get('dimension')}] 「{str(it.get('quote') or '')[:60]}」：{it.get('comment', '')}")
    reader = (review or {}).get("reader") or {}
    for k in ("drop_points", "complaints", "comment", "summary"):
        v = reader.get(k)
        if isinstance(v, list):
            lines += [f"- 读者：{str(x)[:100]}" for x in v[:4]]
        elif isinstance(v, str) and v.strip():
            lines.append(f"- 读者：{v.strip()[:160]}")
    ins = "按下列审稿与读者审读问题修改本章，保留情节与人名设定：\n" + ("\n".join(lines[:12]) or "- 整体提升追读欲与画面感")
    if user_ins.strip():
        ins += "\n作者额外要求：" + user_ins.strip()
    return ins


def _rewrite_full(chapter_id: int, content: str, instruction: str, route: str | None) -> str:
    """整章重写（同 writing.rewrite_chapter_job 的整章分支，但以本轮的底稿为输入、不读库里的正文）。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        pack, meta, plan = writing._pack_for_chapter(s, ch)  # noqa: SLF001
        number = ch.number
    voices = "\n".join(f"- {n}：{v.get('voice', '')}；口头禅：{'、'.join(v.get('catchphrases') or [])}" for n, v in pack.voices.items()) or "（未设定）"
    user = render("chapter_rewrite", number=number, scope_label="（全章）", chapter_plan=plan, voices=voices, context="",
                  text=content, instruction=instruction)
    out = get_gateway().chat(
        "chapter_rewrite", [{"role": "system", "content": system_prompt("chapter_rewrite", platform=meta.get("platform"))},
                            {"role": "user", "content": user}],
        meta={**meta, "text": content, "instruction": instruction, "scope": "chapter"}, temperature=0.8, route=route,
    )
    new = writing.normalize_paragraphs(writing._clean_rewrite(out))  # noqa: SLF001
    if not new.strip() or len(new) < 0.3 * len(content):
        return content  # 疑似截断：本轮当作没改，由调用方换定点修
    return new


def _patch(chapter_id: int, content: str, review: dict[str, Any]) -> str:
    """定点修：先用审稿补丁逐字替换 high/mid 问题，剩下有原句的问题按描述定点改写（writing.issue_rewrite）。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        _, meta, _ = writing._pack_for_chapter(s, ch)  # noqa: SLF001
    issues = review.get("issues") or []
    pats = review.get("patches") or []
    want = [k for k, p in enumerate(pats) if isinstance(p, dict)
            and (issues[p["issue_ref"]] if isinstance(p.get("issue_ref"), int) and p["issue_ref"] < len(issues) else {}).get("severity") in ("high", "mid")]
    new, applied, _ = apply_patches(content, pats, want) if want else (content, [], [])
    covered = {pats[a["index"]].get("issue_ref") for a in applied}
    rest = [it for k, it in enumerate(issues) if k not in covered and it.get("severity") in ("high", "mid")
            and str(it.get("quote") or "") in new]
    if rest:
        new, _ = writing.issue_rewrite(new, rest, meta)
    return new


def _evaluate_text(chapter_id: int, content: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        pack, meta, plan = writing._pack_for_chapter(s, ch)  # noqa: SLF001
        book = common.get_book(s, ch.book_id)
        review, lint, _ = writing._evaluate(s, book, pack, content, ch.number, plan, meta, ch.id)  # noqa: SLF001
    return review, lint.to_dict()


def iterate_job(book_id: int, params: dict[str, Any], ctx: JobContext, resume: dict[str, Any] | None = None) -> dict[str, Any]:
    """对选中章号逐章迭代 rounds 轮：每轮按上一轮的审稿/读者问题定点修或整章重写，新版本存 wanben_iteration（不改正文）。
    不设自动终止门槛，只记录每轮分数变化；作者随时可 POST /wanben/iterate/stop 让它在本轮结束后停。"""
    state: dict[str, Any] = dict(resume if resume is not None else (ctx.resume_state or {}))
    params = dict(state.get("params") or params)
    state["params"] = params
    done: dict[str, Any] = dict(state.get("done") or {})  # chapter_id -> {"rounds": k, "last": iter_id}
    rounds = max(1, min(MAX_ITER_ROUNDS, int(params.get("rounds") or 1)))
    method = params.get("method") or "auto"
    user_ins = str(params.get("instruction") or "")
    route = params.get("route")
    with session_scope() as s:
        chs = select_chapters(s, book_id, params)
        targets = [(c.id or 0, c.number) for c in chs]
    if not targets:
        raise Conflict("所选范围内没有已写正文的章节")
    out_rows: list[dict[str, Any]] = list(state.get("rows") or [])
    stopped = False
    for ci, (cid, number) in enumerate(targets):
        info = done.get(str(cid)) or {"rounds": 0, "last": None}
        if info["rounds"] >= rounds:
            continue
        with session_scope() as s:
            ch = s.get(Chapter, cid)
            if ch is None:
                continue
            prev = s.get(WanbenIteration, info["last"]) if info.get("last") else None
            base = prev.content if prev else ch.content
            base_review = prev.review if prev else None
            base_lint = prev.lint if prev else None
        if base_review is None:
            ctx.progress(int(ci * 100 / len(targets)), f"第{number}章：先审一遍当前稿")
            base_review, base_lint = _evaluate_text(cid, base)
        for r_i in range(info["rounds"], rounds):
            with session_scope() as s:
                if kv_get(s, _iter_stop_key(book_id), False):
                    stopped = True
            if stopped:
                break
            pct = int((ci + (r_i + 0.5) / rounds) * 100 / len(targets))
            m = method
            if m == "auto":
                highs = len([i for i in base_review.get("issues") or [] if i.get("severity") == "high"])
                rs = _scores(base_review)["reader"]
                m = "rewrite" if (user_ins.strip() or highs >= 3 or (rs is not None and rs < READER_PASS)) else "patch"
            ctx.progress(pct, f"第{number}章 第{r_i + 1}/{rounds}轮：{'整章重写' if m == 'rewrite' else '定点修'}")
            ins = _issues_instruction(base_review, user_ins)
            new = _rewrite_full(cid, base, ins, route) if m == "rewrite" else _patch(cid, base, base_review)
            if new == base and m == "patch":
                m = "rewrite"
                new = _rewrite_full(cid, base, ins, route)
            review, lint = _evaluate_text(cid, new)
            sb, sa = _scores(base_review), _scores(review)
            with session_scope() as s:
                n_prev = int(s.exec(select(func.count()).where(WanbenIteration.chapter_id == cid)).one() or 0)
                it = WanbenIteration(book_id=book_id, chapter_id=cid, number=number, job_id=ctx.job_id, round=n_prev + 1,
                                     method=m, instruction=(user_ins.strip() if m == "patch" else ins)[:2000],
                                     base_content=base, content=new, words=writing.count_words(new),
                                     review=review, lint=lint,
                                     scores={"before": sb, "after": sa,
                                             "delta": {"overall": _delta(sb["overall"], sa["overall"]), "reader": _delta(sb["reader"], sa["reader"])}},
                                     status="pending")
                s.add(it)
                s.commit()
                s.refresh(it)
                out_rows.append(iteration_out(it, with_content=False))
                iid = it.id
            base, base_review, base_lint = new, review, lint
            info = {"rounds": r_i + 1, "last": iid}
            done[str(cid)] = info
            state.update({"done": done, "rows": out_rows})
            save_checkpoint(ctx.job_id, f"iterate:{number}:{r_i + 1}", state, kind=ITERATE_KIND, book_id=book_id)
        if stopped:
            break
    with session_scope() as s:
        kv_set(s, _iter_stop_key(book_id), False)
    return {"iterations": out_rows, "chapters": len(targets), "rounds": rounds, "stopped": stopped}


def _resume_iterate(job: Any, state: dict[str, Any]) -> Any:
    book_id = int(job.book_id or 0)
    return lambda ctx: iterate_job(book_id, state.get("params") or {}, ctx, resume=state)


register_resumable(ITERATE_KIND, _resume_iterate)


def select_chapters(s: Session, book_id: int, params: dict[str, Any]) -> list[Chapter]:
    nums: set[int] = set()
    if params.get("numbers"):
        nums.update(int(x) for x in params["numbers"])
    if params.get("start") or params.get("end"):
        a = int(params.get("start") or params.get("end"))
        b = int(params.get("end") or a)
        nums.update(range(min(a, b), max(a, b) + 1))
    for a, b in norm_ranges(params.get("ranges")):
        nums.update(range(a, b + 1))
    if not nums:
        raise ValueError("请指定章号：start/end、numbers 或 ranges")
    rows = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number.in_(sorted(nums))).order_by(Chapter.number)).all()  # type: ignore[attr-defined]
    return [c for c in rows if (c.content or "").strip()]


def iteration_out(it: WanbenIteration, with_content: bool = True, current: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": it.id, "book_id": it.book_id, "chapter_id": it.chapter_id, "number": it.number, "job_id": it.job_id,
                           "round": it.round, "method": it.method, "instruction": it.instruction, "words": it.words,
                           "scores": it.scores, "status": it.status, "created_at": it.created_at.isoformat() if it.created_at else None}
    if current is not None:
        out["stale"] = it.base_content != current  # 正文在这一版生成后又被改过
    if with_content:
        out["content"] = it.content
        out["base_content"] = it.base_content
        out["review"] = it.review
        out["lint"] = it.lint
    return out


def list_iterations(s: Session, book_id: int, number: int | None = None, chapter_id: int | None = None,
                    status: str | None = None) -> list[dict[str, Any]]:
    q = select(WanbenIteration).where(WanbenIteration.book_id == book_id)
    if number is not None:
        q = q.where(WanbenIteration.number == number)
    if chapter_id is not None:
        q = q.where(WanbenIteration.chapter_id == chapter_id)
    if status:
        q = q.where(WanbenIteration.status == status)
    rows = s.exec(q.order_by(WanbenIteration.number, WanbenIteration.id)).all()  # type: ignore[arg-type]
    cur = {c.id: c.content for c in s.exec(select(Chapter).where(Chapter.book_id == book_id))}
    return [iteration_out(it, with_content=False, current=cur.get(it.chapter_id, "")) for it in rows]


def get_iteration(s: Session, book_id: int, iteration_id: int) -> WanbenIteration:
    it = s.get(WanbenIteration, iteration_id)
    if it is None or it.book_id != book_id:
        raise NotFound("迭代版本不存在")
    return it


def adopt_iteration(book_id: int, iteration_id: int) -> dict[str, Any]:
    """采纳一个迭代版本：旧正文进章节历史（可用现有 /chapters/{id}/undo 撤回），新正文与它的审稿结果落库。"""
    with session_scope() as s:
        it = get_iteration(s, book_id, iteration_id)
        if it.status == "adopted":
            raise Conflict("这个版本已经采纳过了")
        cid, content, review, rnd = it.chapter_id, it.content, it.review, it.round
    ch = writing.apply_rewrite(cid, content, f"完本迭代第{rnd}轮采纳前")
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        assert ch is not None
        if review:
            ch.review = review
        ch.updated_at = utcnow()
        s.add(ch)
        it = s.get(WanbenIteration, iteration_id)
        assert it is not None
        it.status = "adopted"
        s.add(it)
        s.commit()
        return {"iteration": iteration_out(it, with_content=False, current=ch.content), "chapter_id": cid,
                "chapter_status": ch.status, "words": ch.words}


def discard_iteration(book_id: int, iteration_id: int) -> dict[str, Any]:
    with session_scope() as s:
        it = get_iteration(s, book_id, iteration_id)
        if it.status == "adopted":
            raise Conflict("已采纳的版本不能丢弃；要回到旧稿请用章节撤回")
        it.status = "discarded"
        s.add(it)
        s.commit()
        return iteration_out(it, with_content=False)


def request_iterate_stop(book_id: int) -> None:
    with session_scope() as s:
        kv_set(s, _iter_stop_key(book_id), True)


def clear_iterate_stop(book_id: int) -> None:
    with session_scope() as s:
        kv_set(s, _iter_stop_key(book_id), False)


# ------------------------------------------------------------------ 导出

def export_txt(book_id: int) -> tuple[str, str]:
    from app.services.packaging import full_text

    with session_scope() as s:
        title = common.get_book(s, book_id).title
    return title, full_text(book_id)

