"""v0.12 E6 批量质检：按章节区间批量做 消痕 / 语感 / 审稿 / AI 率检测 / 排版 / 改章名。

- 不限章数、不限次数（只受作者自己的模型额度约束）。
- 每次批量是一条 BatchQaRun，区间内每章一条 BatchQaItem；任务（Job kind=book_batch_qa）逐章处理，
  单章失败只把这一章标 failed（带原因），其余照跑；失败章可单独或整批重试。
- 队列可暂停（当前在跑的章跑完就停）、续跑（只跑还没处理的章）；服务重启后任务标 interrupted，可 /jobs/{id}/resume。
- 改写类（消痕、语感、审稿+修、排版、改章名）只出对比稿进「待确认」，作者看过 DIFF 后单章采纳或一键全部采纳才写回；
  采纳前若正文又被改过会拒绝（除非 force），旧正文进章节历史可撤回。
- 改写后自动复检 AI 率（配置了朱雀用朱雀，否则用本地人味分），记录前后变化；可设「高于目标再修一轮，最多 N 轮」。
"""

from __future__ import annotations

import contextvars
import logging
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from sqlmodel import Session, select

from app.db import kv_get, kv_set, session_scope
from app.jobs.manager import JobContext, register_resumable, save_checkpoint
from app.lint.humanlint import count_words
from app.llm.gateway import get_gateway
from app.models.tables import BatchQaItem, BatchQaRun, Book, Chapter, Job, utcnow
from app.services import common, typeset, writing, zhuque
from app.services.common import Conflict, NotFound
from app.skills.loader import PLATFORM_LABEL, render, system_prompt

log = logging.getLogger("novelos.batch_qa")

KIND = "book_batch_qa"
OPS = ("humanize", "polish", "review", "aigc", "format", "titles")
OP_LABEL = {"humanize": "消痕", "polish": "语感重塑", "review": "审稿", "aigc": "AI 率检测", "format": "排版", "titles": "改章名"}
REWRITE_OPS = ("humanize", "polish", "review", "format", "titles")  # 可能产出对比稿的操作（review 需 fix=true）
RECHECK_OPS = ("humanize", "polish", "review")  # 改了正文、需要复检 AI 率的操作
MAX_ROUNDS = 5
MAX_CONCURRENCY = 4
LOCAL_MID, LOCAL_HIGH = 35.0, 60.0  # 本地人味分（0–100，越高越像 AI）的档位，只作参考
ACTIVE_ITEM = ("queued", "running")

DEFAULT_OPTIONS: dict[str, Any] = {
    "concurrency": 1,
    "recheck": True,          # 改写后自动复检 AI 率
    "aigc_engine": "auto",    # auto（有朱雀密钥用朱雀，否则本地人味分）/ zhuque / local
    "aigc_target": None,      # 0–100：复检仍高于它就再修一轮
    "max_rounds": 1,          # 最多几轮（1–5）
    "fix": False,             # 审稿：按审稿补丁定点修，出对比稿
    "auto_adopt": False,      # 生成后直接采纳（默认关：一律先进待确认）
    "skip_committed": False,  # 跳过已提交的章
    "format": {},             # 排版选项：blank_line / indent / punct / split_long
}


def _pause_key(run_id: int) -> str:
    return f"batch_qa_pause:{run_id}"


# ------------------------------------------------------------------ 参数

def norm_options(raw: dict[str, Any] | None) -> dict[str, Any]:
    o = {**DEFAULT_OPTIONS, **{k: v for k, v in (raw or {}).items() if k in DEFAULT_OPTIONS and v is not None}}
    o["concurrency"] = max(1, min(MAX_CONCURRENCY, int(o["concurrency"] or 1)))
    o["max_rounds"] = max(1, min(MAX_ROUNDS, int(o["max_rounds"] or 1)))
    if o["aigc_engine"] not in ("auto", "zhuque", "local"):
        raise ValueError("aigc_engine 只能是 auto / zhuque / local")
    t = o.get("aigc_target")
    o["aigc_target"] = None if t in (None, "") else max(0.0, min(100.0, float(t)))
    o["format"] = {k: bool(v) for k, v in dict(o.get("format") or {}).items() if k in typeset.DEFAULTS}
    for k in ("recheck", "fix", "auto_adopt", "skip_committed"):
        o[k] = bool(o[k])
    return o


def resolve_engine(opt: dict[str, Any]) -> str:
    want = opt.get("aigc_engine") or "auto"
    if want == "local":
        return "local"
    with session_scope() as s:
        configured = zhuque.settings_out(s)["zhuque_configured"]
    if want == "zhuque" and not configured:
        raise Conflict("还没有配置朱雀检测密钥：请到「设置 → 朱雀 AIGC 检测」填写，或把检测方式改成本地人味分")
    return "zhuque" if configured else "local"


# ------------------------------------------------------------------ 建批次

def create_run(book_id: int, op: str, start: int, end: int, options: dict[str, Any] | None = None) -> BatchQaRun:
    if op not in OPS:
        raise ValueError(f"op 只能是 {' / '.join(OPS)}")
    if start < 1 or end < 1:
        raise ValueError("章号从 1 开始")
    a, b = min(start, end), max(start, end)
    opt = norm_options(options)
    if op == "aigc" or (op in RECHECK_OPS and opt["recheck"]):
        resolve_engine(opt)  # 指定了朱雀却没配密钥：建批次前就 409
    with session_scope() as s:
        common.get_book(s, book_id)
        chs = s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.number >= a, Chapter.number <= b)
                     .order_by(Chapter.number)).all()  # type: ignore[arg-type]
        chs = [c for c in chs if (c.content or "").strip()]
        if opt["skip_committed"]:
            chs = [c for c in chs if c.status != "committed"]
        if not chs:
            raise Conflict(f"第{a}–{b}章里没有可处理的章节（没有正文{'或都已提交' if opt['skip_committed'] else ''}）")
        run = BatchQaRun(book_id=book_id, op=op, from_no=a, to_no=b, options=opt, status="queued",
                         message=f"共 {len(chs)} 章排队中")
        s.add(run)
        s.commit()
        s.refresh(run)
        for c in chs:
            s.add(BatchQaItem(run_id=run.id or 0, book_id=book_id, chapter_id=c.id or 0, number=c.number, op=op,
                              base_title=c.title or ""))
        s.commit()
        return run


def get_run(s: Session, book_id: int, run_id: int) -> BatchQaRun:
    run = s.get(BatchQaRun, run_id)
    if run is None or run.book_id != book_id:
        raise NotFound("批量任务不存在")
    return run


def get_item(s: Session, book_id: int, item_id: int) -> BatchQaItem:
    it = s.get(BatchQaItem, item_id)
    if it is None or it.book_id != book_id:
        raise NotFound("批量结果不存在")
    return it


def _items(s: Session, run_id: int) -> list[BatchQaItem]:
    return list(s.exec(select(BatchQaItem).where(BatchQaItem.run_id == run_id).order_by(BatchQaItem.number, BatchQaItem.id)).all())  # type: ignore[arg-type]


def active_job(s: Session, run: BatchQaRun) -> Job | None:
    if not run.job_id:
        return None
    j = s.get(Job, run.job_id)
    return j if j is not None and j.status in ("queued", "running") else None


# ------------------------------------------------------------------ AI 率

def _level_local(v: float) -> str:
    return "high" if v >= LOCAL_HIGH else "mid" if v >= LOCAL_MID else "low"


def _lint(chapter_id: int, text: str) -> Any:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        return writing.lint_for(s, ch.book_id, text, ch.number, ch.id)


def measure(chapter_id: int, text: str, engine: str, reuse: dict[str, Any] | None = None) -> dict[str, Any]:
    """AI 率：{value: 0–100, source: zhuque|local, level, result?（朱雀完整结果，含 segments / content_hash）}。"""
    if engine == "zhuque":
        h = zhuque.content_hash(text)
        if reuse and reuse.get("content_hash") == h and reuse.get("softmax") is not None:
            r = {k: v for k, v in reuse.items() if k not in ("stale", "text", "source")}
            return {"value": round(float(r["softmax"]) * 100, 1), "source": "zhuque", "level": r.get("level"), "result": r, "reused": True}
        r = zhuque.detect(text)
        full = {"checked_at": utcnow().isoformat().replace("+00:00", "Z"), "content_hash": h, **r}
        return {"value": round(float(r["softmax"]) * 100, 1), "source": "zhuque", "level": r["level"], "result": full}
    lint = _lint(chapter_id, text)
    v = round(float(lint.ai_score), 1)
    return {"value": v, "source": "local", "level": _level_local(v)}


def _brief(m: dict[str, Any] | None) -> dict[str, Any] | None:
    """对外的 AI 率（不带朱雀 segments）。"""
    if not m:
        return None
    out = {k: m.get(k) for k in ("value", "source", "level")}
    r = m.get("result") or {}
    if r:
        out["labels_ratio"] = r.get("labels_ratio")
        out["checked_at"] = r.get("checked_at")
    return out


# ------------------------------------------------------------------ 单章处理

class _QuietCtx:
    job_id = 0
    book_id = None

    def progress(self, pct: int = 0, message: str = "") -> None:  # noqa: ARG002
        return None

    def checkpoint(self, *a: Any, **kw: Any) -> None:  # noqa: ARG002
        return None


def _one_round(op: str, chapter_id: int, text: str, rnd: int, opt: dict[str, Any], state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """跑一轮改写，返回（新正文, 本轮信息）。"""
    if op == "humanize":
        with session_scope() as s:
            ch = s.get(Chapter, chapter_id)
            assert ch is not None
            _, meta, _ = writing._pack_for_chapter(s, ch)  # noqa: SLF001
            review = ch.review if (rnd == 1 and text == ch.content) else None
            lint = writing.lint_for(s, ch.book_id, text, ch.number, ch.id)
        new, applied = writing.patch_rewrite(text, review, lint, meta)
        return new, {"patches": applied}
    if op == "polish":
        res = writing.polish_voice_job(chapter_id, _QuietCtx(), text=text)  # type: ignore[arg-type]
        return res["after"], {"checks": res.get("checks"), "warnings": res.get("warnings") or []}
    if op == "review":
        from app.services import wanben

        review = state.pop("review", None)
        if review is None:
            review, _ = wanben._evaluate_text(chapter_id, text)  # noqa: SLF001
        new = wanben._patch(chapter_id, text, review)  # noqa: SLF001
        return new, {"issues_fixed": len([i for i in review.get("issues") or [] if i.get("severity") in ("high", "mid")])}
    raise ValueError(op)


def _rounds(op: str, chapter_id: int, base: str, opt: dict[str, Any], engine: str | None,
            reuse: dict[str, Any] | None, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    recheck = bool(opt["recheck"]) and engine is not None
    target = opt.get("aigc_target")
    metrics: dict[str, Any] = {"rounds": [], "words_before": count_words(base)}
    before = measure(chapter_id, base, engine, reuse) if recheck else None  # type: ignore[arg-type]
    metrics["ai_before"] = before
    text = base
    after = before
    for rnd in range(1, int(opt["max_rounds"]) + 1):
        new, info = _one_round(op, chapter_id, text, rnd, opt, state)
        if not new.strip() or new == text:
            break
        text = new
        after = measure(chapter_id, text, engine) if recheck else None  # type: ignore[arg-type]
        metrics["rounds"].append({"round": rnd, "ai": _brief(after), "words": count_words(text), **info})
        if not recheck or target is None or (after and after["value"] <= target):
            break
    metrics["ai_after"] = after if text != base else None
    metrics["words_after"] = count_words(text)
    if before and metrics["ai_after"]:
        metrics["ai_delta"] = round(metrics["ai_after"]["value"] - before["value"], 1)
    if target is not None and metrics.get("ai_after"):
        metrics["reached_target"] = metrics["ai_after"]["value"] <= target
    return text, metrics


def _clean_title(t: Any) -> str:
    t = str(t or "").strip()
    t = re.sub(r"^第[0-9零〇一二两三四五六七八九十百千万]+章[\s:：、.]*", "", t)
    t = t.strip(" 《》“”\"'「」【】")
    return t[:30]


def _titles(chapter_id: int, opt: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        book = common.get_book(s, ch.book_id)
        near = s.exec(select(Chapter).where(Chapter.book_id == ch.book_id, Chapter.number >= ch.number - 2,
                                            Chapter.number <= ch.number + 2, Chapter.id != ch.id)
                      .order_by(Chapter.number)).all()  # type: ignore[arg-type]
        names = [c.name for c in common.cards(s, ch.book_id) if c.type == "character"]
        platform = writing.book_platform(s, ch.book_id)
        text, number, title = ch.content, ch.number, ch.title or ""
        _ = book
    excerpt = text if len(text) <= 2400 else text[:1600] + "\n……\n" + text[-800:]
    neighbors = "\n".join(f"- 第{c.number}章 {c.title or '（无标题）'}" for c in near) or "（无）"
    user = render("batch_chapter_title", number=number, title=title or "（无）", platform_label=PLATFORM_LABEL.get(platform, platform),
                  neighbors=neighbors, excerpt=excerpt)
    raw = get_gateway().chat_json("batch_chapter_title", system_prompt("batch_chapter_title", platform=platform), user,
                                  meta={"text": text, "number": number, "names": names, "title": title}, role="planner",
                                  temperature=0.9)
    cands = [_clean_title(x) for x in (raw.get("titles") if isinstance(raw, dict) else None) or []]
    cands = [c for c in dict.fromkeys(cands) if 2 <= len(c) <= 20]
    pick = next((c for c in cands if c != title), "")
    return pick, {"candidates": cands, "reason": str((raw or {}).get("reason") or "")[:200] if isinstance(raw, dict) else ""}


def process_item(item_id: int, engine: str | None) -> None:
    """处理一章；任何异常都记到这一章（failed + 原因），不往外抛。"""
    with session_scope() as s:
        it = s.get(BatchQaItem, item_id)
        if it is None:
            return
        run = s.get(BatchQaRun, it.run_id)
        opt = norm_options(run.options if run else {})
        it.status, it.error, it.attempts, it.updated_at = "running", "", (it.attempts or 0) + 1, utcnow()
        s.add(it)
        s.commit()
        op, cid = it.op, it.chapter_id
    try:
        status, fields = _process(op, cid, opt, engine)
    except Exception as e:  # noqa: BLE001
        log.warning("批量%s 第%s章失败：%s", OP_LABEL.get(op, op), item_id, e)
        with session_scope() as s:
            it = s.get(BatchQaItem, item_id)
            if it is not None:
                it.status, it.error, it.updated_at = "failed", (str(e) or e.__class__.__name__)[:1000], utcnow()
                s.add(it)
                s.commit()
        return
    with session_scope() as s:
        it = s.get(BatchQaItem, item_id)
        if it is None:
            return
        for k, v in fields.items():
            setattr(it, k, v)
        it.status, it.updated_at = status, utcnow()
        s.add(it)
        s.commit()
    if status == "pending" and opt["auto_adopt"]:
        try:
            with session_scope() as s:
                bid = s.get(BatchQaItem, item_id).book_id  # type: ignore[union-attr]
            adopt_item(bid, item_id)
        except Exception as e:  # noqa: BLE001  自动采纳失败就留在待确认
            log.info("自动采纳第 %s 项未成功：%s", item_id, e)


def _process(op: str, cid: int, opt: dict[str, Any], engine: str | None) -> tuple[str, dict[str, Any]]:
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        if ch is None:
            raise NotFound("章节已删除")
        if not (ch.content or "").strip():
            return "skipped", {"error": "章节正文为空"}
        base, title, reuse = ch.content, ch.title or "", ch.aigc
        platform = writing.book_platform(s, ch.book_id)
    common_fields: dict[str, Any] = {"base_content": base, "base_title": title}

    if op == "aigc":
        prev = None  # 检测类的「前」= 这一章上一次朱雀检测的结果（没有就不比）
        if reuse and reuse.get("softmax") is not None:
            prev = {"value": round(float(reuse["softmax"]) * 100, 1), "source": "zhuque", "level": reuse.get("level"),
                    "checked_at": reuse.get("checked_at"), "stale": reuse.get("content_hash") != zhuque.content_hash(base)}
        if engine == "zhuque":
            r = zhuque.check_chapter(cid, source="batch")["aigc"]
            now = {"value": round(float(r["softmax"]) * 100, 1), "source": "zhuque", "level": r["level"],
                   "labels_ratio": r.get("labels_ratio"), "checked_at": r.get("checked_at")}
        else:
            now = _brief(measure(cid, base, "local"))
        m = {"ai_before": prev, "ai_after": now, "words_before": count_words(base), "words_after": count_words(base)}
        if prev and now and prev.get("source") == now.get("source"):
            m["ai_delta"] = round(now["value"] - prev["value"], 1)
        return "done", {**common_fields, "content": base, "metrics": m}

    if op == "format":
        new, rep = typeset.format_text(base, opt.get("format"), platform)
        m = {"format": rep, "words_before": count_words(base), "words_after": count_words(new)}
        return ("unchanged" if new == base else "pending"), {**common_fields, "content": new, "metrics": m}

    if op == "titles":
        new_title, info = _titles(cid, opt)
        m = {**info, "words_before": count_words(base), "words_after": count_words(base)}
        return ("pending" if new_title and new_title != title else "unchanged"), {**common_fields, "content": base, "title": new_title or title, "metrics": m}

    state: dict[str, Any] = {}
    if op == "review":
        rv = writing.review_chapter_job(cid, _QuietCtx())  # type: ignore[arg-type]  写回 ch.review / ch.lint，同单章审稿
        with session_scope() as s:
            ch = s.get(Chapter, cid)
            review = (ch.review if ch else None) or {}
        issues = review.get("issues") or []
        summary = {"overall": rv.get("overall"), "passed": rv.get("passed"), "dropped": rv.get("dropped_issues"),
                   "high": len([i for i in issues if i.get("severity") == "high"]),
                   "mid": len([i for i in issues if i.get("severity") == "mid"]),
                   "reader": ((review.get("reader") or {}).get("score"))}
        if not opt["fix"] or not (summary["high"] or summary["mid"]):
            return "done", {**common_fields, "content": base, "metrics": {"review": summary, "words_before": count_words(base),
                                                                         "words_after": count_words(base)}}
        state["review"] = review
        new, m = _rounds(op, cid, base, opt, engine if opt["recheck"] else None, reuse, state)
        m["review"] = summary
        return ("unchanged" if new == base else "pending"), {**common_fields, "content": new, "metrics": _store_metrics(m)}

    new, m = _rounds(op, cid, base, opt, engine if opt["recheck"] else None, reuse, state)
    return ("unchanged" if new == base else "pending"), {**common_fields, "content": new, "metrics": _store_metrics(m)}


def _store_metrics(m: dict[str, Any]) -> dict[str, Any]:
    """入库：ai_before 只留摘要；ai_after 留完整朱雀结果（采纳时写回章节 aigc，正文高亮可直接用）。"""
    out = dict(m)
    out["ai_before"] = _brief(m.get("ai_before"))
    a = m.get("ai_after")
    if a:
        out["ai_after"] = {**(_brief(a) or {}), **({"result": a["result"]} if a.get("result") else {})}
    return out


# ------------------------------------------------------------------ 任务

def _paused(run_id: int) -> bool:
    with session_scope() as s:
        return bool(kv_get(s, _pause_key(run_id), False))


def set_pause(run_id: int, value: bool) -> None:
    with session_scope() as s:
        kv_set(s, _pause_key(run_id), bool(value))


def run_job(run_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        run = s.get(BatchQaRun, run_id)
        if run is None:
            raise NotFound("批量任务不存在")
        for it in _items(s, run_id):
            if it.status == "running":  # 上次中断在半路的章：重新排队
                it.status = "queued"
                s.add(it)
        run.status, run.job_id, run.message, run.updated_at = "running", ctx.job_id, "处理中", utcnow()
        s.add(run)
        s.commit()
        op, book_id, opt = run.op, run.book_id, norm_options(run.options)
        queue = [it.id or 0 for it in _items(s, run_id) if it.status == "queued"]
        total = len(_items(s, run_id))
    save_checkpoint(ctx.job_id, "start", {"run_id": run_id}, kind=KIND, book_id=book_id)
    engine = resolve_engine(opt) if (op == "aigc" or (op in RECHECK_OPS and opt["recheck"])) else None
    label = OP_LABEL.get(op, op)
    paused = False
    done_n = 0
    it_queue = iter(queue)
    with ThreadPoolExecutor(max_workers=int(opt["concurrency"]), thread_name_prefix=f"batchqa-{run_id}") as ex:
        futures: dict[Any, int] = {}
        exhausted = False
        while True:
            while not paused and not exhausted and len(futures) < int(opt["concurrency"]):
                if _paused(run_id):
                    paused = True
                    break
                nxt = next(it_queue, None)
                if nxt is None:
                    exhausted = True
                    break
                cctx = contextvars.copy_context()  # 模型用量记账读 contextvar（Job.kind / book_id），线程池里要带上
                futures[ex.submit(cctx.run, process_item, nxt, engine)] = nxt
            if not futures:
                break
            finished, _ = wait(list(futures), return_when=FIRST_COMPLETED)
            for f in finished:
                futures.pop(f, None)
                done_n += 1
            with session_scope() as s:
                processed = len([i for i in _items(s, run_id) if i.status not in ACTIVE_ITEM])
            ctx.progress(int(processed * 100 / max(1, total)), f"批量{label}：已处理 {processed}/{total} 章")
            save_checkpoint(ctx.job_id, f"item:{processed}/{total}", {"run_id": run_id}, kind=KIND, book_id=book_id)
    summary = build_summary(run_id)
    with session_scope() as s:
        run = s.get(BatchQaRun, run_id)
        assert run is not None
        left = summary["counts"].get("queued", 0)
        run.status = "paused" if (paused and left) else "done"
        run.summary = summary
        run.message = (f"已暂停：处理了 {summary['processed']}/{summary['total']} 章，剩 {left} 章" if run.status == "paused"
                       else f"完成：{_summary_text(summary)}")
        run.updated_at = utcnow()
        run.finished_at = utcnow() if run.status == "done" else None
        s.add(run)
        s.commit()
    return {"run_id": run_id, **summary, "status": "paused" if (paused and left) else "done"}


def _summary_text(sm: dict[str, Any]) -> str:
    c = sm["counts"]
    parts = [f"{sm['processed']}/{sm['total']} 章"]
    if c.get("pending"):
        parts.append(f"待确认 {c['pending']}")
    if c.get("failed"):
        parts.append(f"失败 {c['failed']}")
    ai = sm.get("ai") or {}
    if ai.get("avg_before") is not None and ai.get("avg_after") is not None:
        parts.append(f"AI 率均值 {ai['avg_before']} → {ai['avg_after']}")
    return "，".join(parts)


def _resume(job: Any, state: dict[str, Any]) -> Any:
    run_id = int(state.get("run_id") or 0)
    set_pause(run_id, False)
    return lambda ctx: run_job(run_id, ctx)


register_resumable(KIND, _resume)


def build_summary(run_id: int) -> dict[str, Any]:
    with session_scope() as s:
        items = _items(s, run_id)
    counts: dict[str, int] = {}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1
    pairs = [((it.metrics or {}).get("ai_before"), (it.metrics or {}).get("ai_after")) for it in items]
    pairs = [(a, b) for a, b in pairs if a and b and a.get("value") is not None and b.get("value") is not None]
    afters = [b["value"] for it in items for b in [((it.metrics or {}).get("ai_after"))] if b and b.get("value") is not None]
    ai: dict[str, Any] = {"measured": len(afters), "compared": len(pairs),
                          "source": next((b.get("source") for it in items for b in [((it.metrics or {}).get("ai_after"))] if b), None)}
    if pairs:
        ai["avg_before"] = round(sum(a["value"] for a, _ in pairs) / len(pairs), 1)
        ai["avg_after"] = round(sum(b["value"] for _, b in pairs) / len(pairs), 1)
        ai["avg_delta"] = round(ai["avg_after"] - ai["avg_before"], 1)
        ai["improved"] = len([1 for a, b in pairs if b["value"] < a["value"]])
    elif afters:
        ai["avg_after"] = round(sum(afters) / len(afters), 1)
    reached = [it for it in items if (it.metrics or {}).get("reached_target") is True]
    reviews = [(it.metrics or {}).get("review") for it in items if (it.metrics or {}).get("review")]
    out: dict[str, Any] = {
        "total": len(items), "processed": len([i for i in items if i.status not in ACTIVE_ITEM]), "counts": counts, "ai": ai,
        "reached_target": len(reached),
        "failed": [{"item_id": i.id, "chapter_id": i.chapter_id, "number": i.number, "error": i.error} for i in items if i.status == "failed"],
    }
    if reviews:
        scores = [r["overall"] for r in reviews if isinstance(r.get("overall"), (int, float))]
        out["review"] = {"count": len(reviews), "avg_overall": round(sum(scores) / len(scores), 1) if scores else None,
                         "passed": len([r for r in reviews if r.get("passed")]), "high": sum(int(r.get("high") or 0) for r in reviews),
                         "mid": sum(int(r.get("mid") or 0) for r in reviews)}
    return out


# ------------------------------------------------------------------ 输出

def item_out(it: BatchQaItem, with_content: bool = False, current: Chapter | None = None) -> dict[str, Any]:
    m = dict(it.metrics or {})
    if isinstance(m.get("ai_after"), dict):
        m["ai_after"] = {k: v for k, v in m["ai_after"].items() if k != "result"}
    out: dict[str, Any] = {
        "id": it.id, "run_id": it.run_id, "book_id": it.book_id, "chapter_id": it.chapter_id, "number": it.number, "op": it.op,
        "status": it.status, "error": it.error, "attempts": it.attempts, "base_title": it.base_title, "title": it.title,
        "changed": (it.title != it.base_title) if it.op == "titles" else (it.content != it.base_content and bool(it.content)),
        "metrics": m, "updated_at": it.updated_at.isoformat() if it.updated_at else None,
    }
    if current is not None and it.status == "pending":
        out["stale"] = (current.title or "") != it.base_title if it.op == "titles" else current.content != it.base_content
    if with_content:
        out["base_content"] = it.base_content
        out["content"] = it.content
    return out


def run_out(s: Session, run: BatchQaRun, with_items: bool = False) -> dict[str, Any]:
    items = _items(s, run.id or 0)
    counts: dict[str, int] = {}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1
    job = s.get(Job, run.job_id) if run.job_id else None
    status = run.status
    if status in ("queued", "running") and job is not None and job.status not in ("queued", "running"):
        status = "interrupted" if job.status == "interrupted" else ("failed" if job.status == "failed" else status)
    out: dict[str, Any] = {
        "id": run.id, "book_id": run.book_id, "op": run.op, "op_label": OP_LABEL.get(run.op, run.op), "from": run.from_no, "to": run.to_no,
        "options": run.options, "status": status, "message": run.message, "summary": run.summary, "job_id": run.job_id,
        "job_status": job.status if job else None, "job_error": job.error if job else None,
        "paused_requested": bool(kv_get(s, _pause_key(run.id or 0), False)),
        "total": len(items), "counts": counts, "processed": len([i for i in items if i.status not in ACTIVE_ITEM]),
        "pending": counts.get("pending", 0), "failed": counts.get("failed", 0),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    if with_items:
        cur = {c.id: c for c in s.exec(select(Chapter).where(Chapter.book_id == run.book_id))}
        out["items"] = [item_out(it, current=cur.get(it.chapter_id)) for it in items]
        out["live_summary"] = build_summary(run.id or 0)
    return out


def list_runs(s: Session, book_id: int, limit: int = 30) -> list[dict[str, Any]]:
    runs = s.exec(select(BatchQaRun).where(BatchQaRun.book_id == book_id).order_by(BatchQaRun.id.desc()).limit(limit)).all()  # type: ignore[union-attr]
    return [run_out(s, r) for r in runs]


# ------------------------------------------------------------------ 暂停 / 续跑 / 重试 / 删除

def prepare_resume(book_id: int, run_id: int) -> int:
    """续跑前检查：返回排队章数。正在跑 409；没有剩余章 409。"""
    with session_scope() as s:
        run = get_run(s, book_id, run_id)
        if active_job(s, run) is not None:
            raise Conflict("这批正在处理中")
        n = len([i for i in _items(s, run_id) if i.status in ACTIVE_ITEM])
        if not n:
            raise Conflict("这批没有待处理的章了；失败的章请用「重试」")
    set_pause(run_id, False)
    return n


def prepare_retry(book_id: int, run_id: int, item_ids: list[int] | None = None) -> int:
    """把失败章（或指定的失败章）重新排队，返回排队章数。"""
    with session_scope() as s:
        run = get_run(s, book_id, run_id)
        if active_job(s, run) is not None:
            raise Conflict("这批正在处理中，等它跑完或暂停后再重试")
        want = set(item_ids or [])
        n = 0
        for it in _items(s, run_id):
            if it.status == "failed" and (not want or it.id in want):
                it.status, it.error, it.updated_at = "queued", "", utcnow()
                s.add(it)
                n += 1
            elif want and it.id in want and it.status != "failed":
                raise Conflict(f"第{it.number}章不是失败状态（{it.status}），不需要重试")
        if not n:
            raise Conflict("没有失败的章需要重试")
        run.status, run.message, run.updated_at = "queued", f"重试 {n} 章", utcnow()
        s.add(run)
        s.commit()
    set_pause(run_id, False)
    return n


def pause(book_id: int, run_id: int) -> dict[str, Any]:
    set_pause(run_id, True)
    with session_scope() as s:
        run = get_run(s, book_id, run_id)
        running = active_job(s, run) is not None
        if not running and run.status in ("queued", "running"):
            run.status, run.message = "paused", "已暂停"
            s.add(run)
            s.commit()
    return {"ok": True, "paused": True, "running": running,
            "message": "正在处理的章跑完后暂停" if running else "已暂停；续跑时从没处理的章接着做"}


def delete_run(book_id: int, run_id: int) -> None:
    with session_scope() as s:
        run = get_run(s, book_id, run_id)
        if active_job(s, run) is not None:
            raise Conflict("这批正在处理中，先暂停再删除")
        for it in _items(s, run_id):
            s.delete(it)
        s.delete(run)
        s.commit()
        kv_set(s, _pause_key(run_id), False)


def attach_job(run_id: int, job_id: int) -> None:
    with session_scope() as s:
        run = s.get(BatchQaRun, run_id)
        if run is not None:
            run.job_id = job_id
            s.add(run)
            s.commit()


# ------------------------------------------------------------------ 采纳 / 弃用

def adopt_item(book_id: int, item_id: int, content: str | None = None, title: str | None = None, force: bool = False) -> dict[str, Any]:
    """采纳一章的对比稿：旧正文（或旧标题）进章节历史，可用 /chapters/{id}/undo 撤回。
    content 传入时以它为准（DIFF 里逐段取舍后的结果）。正文在生成对比稿后又改过时 409，除非 force。"""
    with session_scope() as s:
        it = get_item(s, book_id, item_id)
        if it.status != "pending":
            raise Conflict(f"第{it.number}章的结果状态是「{it.status}」，只有待确认的能采纳")
        ch = s.get(Chapter, it.chapter_id)
        if ch is None:
            raise NotFound("章节已删除")
        op, cid, number, label = it.op, it.chapter_id, it.number, f"批量{OP_LABEL.get(it.op, it.op)}前"
        if op == "titles":
            if not force and (ch.title or "") != it.base_title:
                raise Conflict(f"第{number}章的标题在生成候选后又改过；确认覆盖请带 force")
            new_title = _clean_title(title if title is not None else it.title)
            if not new_title:
                raise ValueError("标题不能为空")
            writing.push_history(ch, label)
            ch.title, ch.updated_at = new_title, utcnow()
            s.add(ch)
            it.status, it.title, it.updated_at = "adopted", new_title, utcnow()
            s.add(it)
            s.commit()
            return {"item": item_out(it), "chapter_id": cid, "title": new_title}
        if not force and ch.content != it.base_content:
            raise Conflict(f"第{number}章正文在生成对比稿后又改过；确认覆盖请带 force")
        final = content if content is not None else it.content
        if not final.strip():
            raise ValueError("正文不能为空")
        after = (it.metrics or {}).get("ai_after") or {}
        result = after.get("result") if isinstance(after, dict) else None
    writing.apply_rewrite(cid, final, label)
    with session_scope() as s:
        ch = s.get(Chapter, cid)
        it = s.get(BatchQaItem, item_id)
        assert ch is not None and it is not None
        if result and result.get("content_hash") == zhuque.content_hash(ch.content):  # 复检结果对得上采纳后的正文：直接作为章节 AI 率
            ch.aigc = result
            zhuque.append_history(ch, result, ch.content, source="batch")
            s.add(ch)
        it.status, it.updated_at = "adopted", utcnow()
        if final != it.content:
            it.metrics = {**(it.metrics or {}), "partial": True}
        s.add(it)
        s.commit()
        return {"item": item_out(it), "chapter_id": cid, "words": ch.words}


def adopt_all(book_id: int, run_id: int, force: bool = False) -> dict[str, Any]:
    with session_scope() as s:
        get_run(s, book_id, run_id)
        ids = [(it.id or 0, it.number) for it in _items(s, run_id) if it.status == "pending"]
    adopted: list[int] = []
    skipped: list[dict[str, Any]] = []
    for iid, number in ids:
        try:
            adopt_item(book_id, iid, force=force)
            adopted.append(number)
        except (Conflict, ValueError, NotFound) as e:
            skipped.append({"item_id": iid, "number": number, "reason": str(e)})
    return {"adopted": adopted, "skipped": skipped, "count": len(adopted)}


def discard_item(book_id: int, item_id: int) -> dict[str, Any]:
    with session_scope() as s:
        it = get_item(s, book_id, item_id)
        if it.status != "pending":
            raise Conflict("只有待确认的结果能弃用")
        it.status, it.updated_at = "discarded", utcnow()
        s.add(it)
        s.commit()
        return item_out(it)


def discard_all(book_id: int, run_id: int) -> dict[str, Any]:
    with session_scope() as s:
        get_run(s, book_id, run_id)
        n = 0
        for it in _items(s, run_id):
            if it.status == "pending":
                it.status, it.updated_at = "discarded", utcnow()
                s.add(it)
                n += 1
        s.commit()
    return {"count": n}


def book_title(s: Session, book_id: int) -> str:
    b = s.get(Book, book_id)
    return b.title if b else ""
