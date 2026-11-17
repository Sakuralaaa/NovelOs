"""v0.13 批量后台质检（Job book_batch）：按章节区间批量去 AI 味 / 语感重塑 / 排版 / 审稿 / AI 率检测 / 起章名。

- 改正文的操作（humanize / polish / format）只出新版本进「待采纳」（复用 wanben_iteration，method 记操作名），不直接覆盖；
  书的审批模式为 auto 时直接采纳（旧稿进章节历史可撤回）。
- 改写后复检：options.recheck=true 且配置了朱雀时，新稿再测 AI 率；高于 options.aigc_target 就在新稿上再改一轮，最多 options.max_rounds 轮。
- review / aigc 不改正文，结果写回章节；titles 每章给候选章名，结果在任务 result 里，作者挑了再改。
- 逐章断点：中断后续跑跳过已完成的章；POST /books/{id}/batch/stop 让它在当前章结束后停。
"""

from __future__ import annotations

from typing import Any

from sqlmodel import func, select

from app.db import kv_get, kv_set, session_scope
from app.jobs.manager import JobContext, register_resumable, save_checkpoint
from app.models.tables import Chapter, WanbenIteration
from app.services import chapter_tools, common, wanben, writing
from app.services.common import Conflict

KIND = "book_batch"
OPS = {"humanize": "去 AI 味", "polish": "语感重塑", "format": "排版", "review": "审稿", "aigc": "AI 率检测", "titles": "起章名"}
REWRITE_OPS = ("humanize", "polish", "format")


def _stop_key(book_id: int) -> str:
    return f"batch_stop:{book_id}"


def request_stop(book_id: int) -> None:
    with session_scope() as s:
        kv_set(s, _stop_key(book_id), True)


class _Sub:
    """把单章任务的进度映射到整批进度里。"""

    def __init__(self, ctx: JobContext, lo: int, hi: int, prefix: str) -> None:
        self.ctx, self.lo, self.hi, self.prefix = ctx, lo, hi, prefix
        self.job_id, self.book_id, self.resume_state = ctx.job_id, ctx.book_id, None

    def progress(self, pct: int, message: str = "") -> None:
        self.ctx.progress(self.lo + int((self.hi - self.lo) * max(0, min(100, pct)) / 100), f"{self.prefix}{message}")

    def checkpoint(self, *a: Any, **k: Any) -> None:  # 单章任务不单独存断点
        return None


def _aigc_ratio(text: str) -> float | None:
    from app.services import zhuque

    try:
        r = zhuque.detect(text, True)
    except Exception:  # noqa: BLE001  没配置或检测失败：不复检
        return None
    return r.get("softmax")


def _rewrite_once(op: str, chapter_id: int, content: str, sub: _Sub) -> tuple[str, dict[str, Any]]:
    """对给定底稿做一次 op，返回 (新稿, 附加信息)。不落库。"""
    if op == "format":
        new, msgs = chapter_tools.format_text(content)
        return new, {"notes": msgs}
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        pack, meta, _ = writing._pack_for_chapter(s, ch)  # noqa: SLF001
        lint_b = writing.lint_for(s, ch.book_id, content, ch.number, ch.id)
        review = ch.review if content == ch.content else None
    if op == "humanize":
        new, applied = writing.patch_rewrite(content, review, lint_b, meta)
        return new, {"patches": applied}
    r = writing.polish_voice_job(chapter_id, sub, base=content)  # type: ignore[arg-type]
    return r["after"], {"warnings": r.get("warnings") or []}


def _one_rewrite(book_id: int, op: str, cid: int, number: int, opts: dict[str, Any], sub: _Sub, job_id: int) -> dict[str, Any]:
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        if ch is None or not ch.content.strip():
            return {"status": "skipped", "error": "没有正文"}
        base = ch.content
        auto = not common.chapter_review_mode(common.get_book(s, book_id))
        ai_b = writing.lint_for(s, book_id, base, number, cid).ai_score
    recheck = bool(opts.get("recheck"))
    target = float(opts.get("aigc_target") or 0.5)
    max_rounds = max(1, min(3, int(opts.get("max_rounds") or 1)))
    aigc_b = _aigc_ratio(base) if recheck else None
    cur, info, rounds, aigc_a = base, {}, 0, None
    for r in range(max_rounds):
        sub.progress(int(100 * r / max_rounds), f"第{r + 1}轮")
        new, info = _rewrite_once(op, cid, cur, sub)
        rounds += 1
        if not new.strip() or new == cur:
            break
        cur = new
        if not recheck:
            break
        aigc_a = _aigc_ratio(cur)
        if aigc_a is None or aigc_a <= target:
            break
    if cur == base:
        return {"status": "unchanged", "notes": info.get("notes") or []}
    with session_scope() as s:
        ai_a = writing.lint_for(s, book_id, cur, number, cid).ai_score
        n_prev = int(s.exec(select(func.count()).where(WanbenIteration.chapter_id == cid)).one() or 0)
        none = {"overall": None, "reader": None, "passed": None, "issues": 0}
        it = WanbenIteration(book_id=book_id, chapter_id=cid, number=number, job_id=job_id, round=n_prev + 1, method=op,
                             instruction=f"批量{OPS[op]}" + (f"（{rounds} 轮）" if rounds > 1 else ""), base_content=base, content=cur,
                             words=writing.count_words(cur), review=None, lint=None,
                             scores={"before": {**none, "ai": ai_b, "aigc": aigc_b}, "after": {**none, "ai": ai_a, "aigc": aigc_a},
                                     "delta": {"overall": None, "reader": None, "ai": wanben._delta(ai_b, ai_a), "aigc": wanben._delta(aigc_b, aigc_a)}},  # noqa: SLF001
                             status="pending")
        s.add(it)
        s.commit()
        s.refresh(it)
        iid = it.id or 0
    adopted = False
    if auto:
        wanben.adopt_iteration(book_id, iid)
        adopted = True
    return {"status": "ok", "iteration_id": iid, "adopted": adopted, "ai_before": ai_b, "ai_after": ai_a,
            "aigc_before": aigc_b, "aigc_after": aigc_a, "rounds": rounds, "notes": info.get("notes") or info.get("warnings") or []}


def _one(book_id: int, op: str, cid: int, number: int, opts: dict[str, Any], sub: _Sub, job_id: int) -> dict[str, Any]:
    if op in REWRITE_OPS:
        return _one_rewrite(book_id, op, cid, number, opts, sub, job_id)
    if op == "review":
        r = writing.review_chapter_job(cid, sub)  # type: ignore[arg-type]
        return {"status": "ok", "overall": r.get("overall"), "passed": r.get("passed")}
    if op == "aigc":
        from app.services import zhuque

        r = zhuque.check_chapter(cid, book_id, sub.progress)
        a = r.get("aigc") or {}
        return {"status": "ok", "aigc": a.get("softmax"), "level": a.get("level")}
    if op == "titles":
        r = chapter_tools.chapter_titles(cid, int(opts.get("n") or 5))
        return {"status": "ok", "current": r["current"], "titles": r["titles"][:5]}
    raise ValueError(f"不认识的批量操作：{op}")


def batch_job(book_id: int, params: dict[str, Any], ctx: JobContext, resume: dict[str, Any] | None = None) -> dict[str, Any]:
    state: dict[str, Any] = dict(resume if resume is not None else (ctx.resume_state or {}))
    params = dict(state.get("params") or params)
    state["params"] = params
    op = params.get("op")
    if op not in OPS:
        raise ValueError("op 只能是 humanize / polish / format / review / aigc / titles")
    if op == "aigc" or params.get("options", {}).get("recheck"):
        from app.services import zhuque

        if op == "aigc":
            zhuque.require_configured()
    opts = dict(params.get("options") or {})
    with session_scope() as s:
        chs = wanben.select_chapters(s, book_id, params)
        targets = [(c.id or 0, c.number) for c in chs]
        if resume is None and not ctx.resume_state:
            kv_set(s, _stop_key(book_id), False)
    if not targets:
        raise Conflict("所选范围内没有已写正文的章节")
    rows: list[dict[str, Any]] = list(state.get("rows") or [])
    done = {r["chapter_id"] for r in rows}
    stopped = False
    for k, (cid, number) in enumerate(targets):
        if cid in done:
            continue
        with session_scope() as s:
            if kv_get(s, _stop_key(book_id), False):
                stopped = True
        if stopped:
            break
        lo, hi = int(k * 100 / len(targets)), int((k + 1) * 100 / len(targets))
        sub = _Sub(ctx, lo, max(lo, hi - 1), f"第{number}章 {OPS[op]}：")
        sub.progress(0, "开始")
        try:
            r = _one(book_id, op, cid, number, opts, sub, ctx.job_id)
        except Exception as e:  # noqa: BLE001  单章失败不影响整批
            r = {"status": "failed", "error": str(e)[:200]}
        rows.append({"chapter_id": cid, "number": number, **r})
        state["rows"] = rows
        save_checkpoint(ctx.job_id, f"batch:{op}:{number}", state, kind=KIND, book_id=book_id)
    with session_scope() as s:
        kv_set(s, _stop_key(book_id), False)
    ok = [r for r in rows if r["status"] == "ok"]
    summary: dict[str, Any] = {"ok": len(ok), "failed": len([r for r in rows if r["status"] == "failed"]),
                               "unchanged": len([r for r in rows if r["status"] == "unchanged"]),
                               "skipped": len([r for r in rows if r["status"] == "skipped"])}
    if op in REWRITE_OPS:
        def avg(key: str) -> float | None:
            v = [r[key] for r in ok if isinstance(r.get(key), (int, float))]
            return round(sum(v) / len(v), 3) if v else None
        summary.update({"ai_before": avg("ai_before"), "ai_after": avg("ai_after"), "aigc_before": avg("aigc_before"),
                        "aigc_after": avg("aigc_after"), "pending": len([r for r in ok if not r.get("adopted")])})
    if op == "review":
        sc = [r["overall"] for r in ok if isinstance(r.get("overall"), (int, float))]
        summary["avg_overall"] = round(sum(sc) / len(sc), 1) if sc else None
    if op == "aigc":
        sc = [r["aigc"] for r in ok if isinstance(r.get("aigc"), (int, float))]
        summary["avg_aigc"] = round(sum(sc) / len(sc), 3) if sc else None
    return {"op": op, "op_label": OPS[op], "chapters": len(targets), "rows": rows, "summary": summary, "stopped": stopped}


def _resume(job: Any, state: dict[str, Any]) -> Any:
    book_id = int(job.book_id or 0)
    return lambda ctx: batch_job(book_id, state.get("params") or {}, ctx, resume=state)


register_resumable(KIND, _resume)
