"""v0.16 一键成书：选题或同人建好的书，一路跑到完本。

流程（一个后台任务 kind=autopilot，按书加锁；断点存在 auto_run.state 和任务断点里，重启后可续跑）：
  setup  同人书先导入原著设定、生成原创主角；补全设定库（已有的卡不覆盖）；切到完本模式
  plan   按字数目标倒推卷纲（已规划过就跳过）
  write  逐批连写（复用 wanben._run_one_batch），批次在卷末与开篇边界截断；每批后：
         - 自愈（v0.17 按章逐章）：每章写完没提交（审稿没过、精修章），马上带完整上下文和读者意见整章重写，最多 2 轮；
           新稿不到目标字数 85% 不用、分数不更高不换；过审就提交接着写，2 轮还没过就停下标「待你看」，不往下写
         - 开篇确认（关键时刻模式）：开篇 N 章写完停下等作者看
         - 卷末复盘：本卷前情回顾 + 长期状态 + 问题 + 下一卷 3 个走向；全自动按推荐项走，关键时刻模式停下等作者点选
         - 渠道全挂：等 1 / 5 / 15 分钟各重试一次，还不行就停下，可续跑
         - 本次运行花费到上限就停
  done   写满目标章数
作者导向（决策点里写的要求）进写章上下文（context.build_context_pack 调 guidance_lines）。
"""

from __future__ import annotations

import time
from typing import Any

from sqlmodel import Session, select

from app.db import kv_get, kv_set, session_scope
from app.jobs.manager import JobContext, find_active, load_checkpoint, register_resumable, save_checkpoint, submit
from app.llm.gateway import LLMError, get_gateway
from app.models.tables import AutoDecision, AutoRun, Book, Chapter, Fact, utcnow
from app.services import common, outline, wanben, writing
from app.services.common import Conflict, NotFound
from app.skills.loader import render, system_prompt

KIND = "autopilot"
LEVELS = ("full", "guided")
STOP_KINDS = ("opening", "volume")
DEFAULTS: dict[str, Any] = {
    "level": "full",                 # full 全自动；guided 关键时刻问我
    "stop_on": ["opening", "volume"],  # 关键时刻模式下停下来的决策点
    "target_words": 300_000,
    "chapter_words": 2000,
    "batch_size": 10,
    "golden_chapters": 10,           # 开篇章数：多一轮打磨，关键时刻模式写完停下确认
    "max_cost_cny": 0.0,             # 本次运行花费上限，0 不限
}
RETRY_WAITS = (60, 300, 900)
MAX_EVENTS = 200
GOLDEN_READER_MIN = 8  # 开篇章读者分低于这个再打磨（最多 HEAL_ROUNDS 轮；过审了就放行，不为它停下）
HEAL_ROUNDS = 2        # v0.17 自愈重写最多轮数
HEAL_MIN_RATIO = 0.85  # v0.17 自愈新稿字数不到目标字数的这个比例不采用
OPEN_STATUSES = ("running", "waiting", "paused", "stopped")
LEVEL_LABEL = {"full": "全自动", "guided": "关键时刻问我"}


class _Halt(Exception):
    def __init__(self, status: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message


def _settings_key(book_id: int) -> str:
    return f"autopilot:settings:{book_id}"


def _pause_key(book_id: int) -> str:
    return f"autopilot:pause:{book_id}"


def _ref(book_id: int) -> str:
    return f"autopilot:{book_id}"


# ------------------------------------------------------------------ 设置

def norm_settings(raw: dict[str, Any] | None, book: Book | None = None) -> dict[str, Any]:
    st = dict(DEFAULTS)
    if book is not None:
        if book.target_words and book.target_words >= 50_000:
            st["target_words"] = int(book.target_words)
        if book.chapter_words:
            st["chapter_words"] = int(book.chapter_words)
    for k, v in (raw or {}).items():
        if k in DEFAULTS and v is not None:
            st[k] = v
    if st["level"] not in LEVELS:
        raise ValueError("模式只能是全自动或关键时刻问我")
    st["stop_on"] = [x for x in (st.get("stop_on") or []) if x in STOP_KINDS]
    st["target_words"] = max(10_000, min(5_000_000, int(st["target_words"])))
    st["chapter_words"] = max(1000, min(6000, int(st["chapter_words"])))
    st["batch_size"] = max(1, min(30, int(st["batch_size"])))
    st["golden_chapters"] = max(0, min(30, int(st["golden_chapters"])))
    st["max_cost_cny"] = max(0.0, float(st["max_cost_cny"] or 0))
    return st


def get_settings(s: Session, book_id: int) -> dict[str, Any]:
    book = common.get_book(s, book_id)
    return norm_settings(kv_get(s, _settings_key(book_id), None), book)


def save_settings(s: Session, book_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    book = common.get_book(s, book_id)
    cur = kv_get(s, _settings_key(book_id), None) or {}
    st = norm_settings({**cur, **{k: v for k, v in patch.items() if v is not None}}, book)
    kv_set(s, _settings_key(book_id), st)
    run = open_run(s, book_id)
    if run is not None:
        run.settings = st
        s.add(run)
        s.commit()
    return st


# ------------------------------------------------------------------ 运行记录

def latest_run(s: Session, book_id: int) -> AutoRun | None:
    return s.exec(select(AutoRun).where(AutoRun.book_id == book_id).order_by(AutoRun.id.desc())).first()  # type: ignore[union-attr]


def open_run(s: Session, book_id: int) -> AutoRun | None:
    r = latest_run(s, book_id)
    return r if r is not None and r.status in OPEN_STATUSES else None


def _event(run_id: int, kind: str, text: str) -> None:
    with session_scope() as s:
        r = s.get(AutoRun, run_id)
        if r is None:
            return
        r.events = [*(r.events or []), {"at": utcnow().isoformat(), "kind": kind, "text": text[:300]}][-MAX_EVENTS:]
        r.updated_at = utcnow()
        s.add(r)
        s.commit()


def _bump(run_id: int, key: str, n: int = 1) -> None:
    with session_scope() as s:
        r = s.get(AutoRun, run_id)
        if r is None:
            return
        st = dict(r.stats or {})
        st[key] = int(st.get(key) or 0) + n
        r.stats = st
        s.add(r)
        s.commit()


def _set(run_id: int, **kw: Any) -> None:
    with session_scope() as s:
        r = s.get(AutoRun, run_id)
        if r is None:
            return
        for k, v in kw.items():
            setattr(r, k, v)
        r.updated_at = utcnow()
        s.add(r)
        s.commit()


def _flag(run_id: int, ch: Chapter, reason: str, blocking: bool = False) -> None:
    with session_scope() as s:
        r = s.get(AutoRun, run_id)
        if r is None:
            return
        flags = [f for f in (r.flags or []) if f.get("chapter_id") != ch.id]
        flags.append({"chapter_id": ch.id, "number": ch.number, "title": ch.title, "reason": reason[:200],
                      "at": utcnow().isoformat(), "resolved": False, "blocking": blocking})
        r.flags = flags[-300:]
        s.add(r)
        s.commit()


def guidance_lines(s: Session, book_id: int, number: int) -> list[str]:
    """写第 number 章时生效的作者导向（一键成书决策点里写的要求）。"""
    r = latest_run(s, book_id)
    if r is None:
        return []
    out = []
    for g in r.guidance or []:
        lo, hi = int(g.get("from_chapter") or 0), g.get("to_chapter")
        if number >= lo and (hi is None or number <= int(hi)) and str(g.get("text") or "").strip():
            out.append(str(g["text"]).strip()[:300])
    return out[-6:]


def _add_guidance(run_id: int, text: str, lo: int, hi: int | None, source: str) -> None:
    text = text.strip()
    if not text:
        return
    with session_scope() as s:
        r = s.get(AutoRun, run_id)
        if r is None:
            return
        r.guidance = [*(r.guidance or []), {"text": text[:300], "from_chapter": lo, "to_chapter": hi, "source": source,
                                            "at": utcnow().isoformat()}][-30:]
        s.add(r)
        s.commit()


# ------------------------------------------------------------------ 启停

def start(book_id: int, patch: dict[str, Any] | None = None) -> tuple[AutoRun, Any]:
    """开始（或继续）一键成书。已有没结束的运行就接着跑；全部结束过就新开一次。"""
    if find_active(KIND, _ref(book_id)):
        raise Conflict("这本书的一键成书已经在跑了")
    with session_scope() as s:
        common.get_book(s, book_id)
        st = save_settings(s, book_id, patch or {})
        run = open_run(s, book_id)
        if run is None:
            run = AutoRun(book_id=book_id, status="running", stage="setup", settings=st, state={}, stats={})
            s.add(run)
            s.commit()
            s.refresh(run)
            first = True
        else:
            if s.exec(select(AutoDecision).where(AutoDecision.run_id == run.id, AutoDecision.status == "pending")).first():
                raise Conflict("还有待拍板的决策点，先选一个走向")
            run.status, run.stop_reason, run.message, run.settings = "running", "", "", st
            s.add(run)
            s.commit()
            s.refresh(run)
            first = False
        kv_set(s, _pause_key(book_id), False)
        run_id = run.id or 0
    _event(run_id, "start", f"{'开始' if first else '继续'}一键成书（{LEVEL_LABEL[st['level']]}，目标 {st['target_words'] // 10000} 万字）")
    job = submit(KIND, lambda ctx: run_job(book_id, ctx), book_id=book_id, lock_book=True, ref=_ref(book_id))
    _set(run_id, job_id=job.id)
    with session_scope() as s:
        return s.get(AutoRun, run_id), job  # type: ignore[return-value]


def pause(book_id: int) -> dict[str, Any]:
    with session_scope() as s:
        kv_set(s, _pause_key(book_id), True)
    wanben.set_pause(book_id, True)
    with session_scope() as s:
        run = open_run(s, book_id)
        active = find_active(KIND, _ref(book_id))
        if run is not None and not active and run.status == "running":
            run.status, run.stop_reason, run.message = "paused", "paused", "已暂停"
            s.add(run)
            s.commit()
    return {"ok": True, "running": bool(find_active(KIND, _ref(book_id)))}


def _paused(book_id: int) -> bool:
    with session_scope() as s:
        return bool(kv_get(s, _pause_key(book_id), False))


# ------------------------------------------------------------------ 主循环

def run_job(book_id: int, ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        run = open_run(s, book_id)
        if run is None:
            raise Conflict("没有进行中的一键成书")
        run.job_id, run.status, run.stop_reason, run.message = ctx.job_id, "running", "", ""
        s.add(run)
        s.commit()
        run_id = run.id or 0
        state = dict(run.state or {})
        kv_set(s, _pause_key(book_id), False)
    wanben.set_pause(book_id, False)
    batch_state: dict[str, Any] = dict(state.get("batch") or {})
    cp = load_checkpoint(int(state.get("last_job_id") or 0) or ctx.job_id)
    if cp is not None and isinstance(cp.state, dict) and "batch_ids" in cp.state:
        batch_state = dict(cp.state)
    state["last_job_id"] = ctx.job_id
    batch_state.pop("force", None)  # v0.17：不再无条件放行，精修章写完由按章自愈审批
    batch_state.setdefault("batch_ids", [])
    try:
        out = _drive(book_id, run_id, ctx, state, batch_state)
    except _Halt as h:
        _set(run_id, status=h.status, stop_reason=h.reason, message=h.message, state={**state, "batch": batch_state})
        _event(run_id, h.reason, h.message)
        return {"run_id": run_id, "status": h.status, "reason": h.reason, "message": h.message}
    except Exception as e:  # noqa: BLE001
        msg = f"出错停下：{e}"[:500]
        _set(run_id, status="stopped", stop_reason="error", message=msg, state={**state, "batch": batch_state})
        _event(run_id, "error", msg)
        raise
    return out


def _save(run_id: int, ctx: JobContext, state: dict[str, Any], batch_state: dict[str, Any], stage: str) -> None:
    _set(run_id, state={**state, "batch": batch_state}, stage=stage)
    save_checkpoint(ctx.job_id, f"autopilot:{stage}", batch_state, kind=KIND)


def _retry(run_id: int, book_id: int, what: str, fn: Any) -> Any:
    """渠道出错：等 1 / 5 / 15 分钟各重试一次；预算用完直接停。模型输出解析失败（不是 JSON 等）马上再试，最多 2 次。"""
    bad_output = 0
    i = 0
    while True:
        try:
            return fn()
        except (ValueError, KeyError) as e:
            bad_output += 1
            if bad_output > 2:
                raise
            _bump(run_id, "retries")
            _event(run_id, "retry", f"{what}：模型输出没解析出来，马上重试（{str(e)[:100]}）")
            continue
        except LLMError as e:
            msg = str(e)
            if "预算" in msg:
                raise _Halt("stopped", "budget", msg[:300]) from e
            _bump(run_id, "llm_failures")
            if i >= len(RETRY_WAITS):
                raise _Halt("stopped", "llm_down", f"{what}：模型渠道连续出错，已重试 {len(RETRY_WAITS)} 次后停下（{msg[:160]}）。"
                            "检查渠道或设好备用路由后点继续") from e
            wait = RETRY_WAITS[i]
            i += 1
            _event(run_id, "retry", f"{what}：渠道出错，{wait // 60} 分钟后重试（{msg[:120]}）")
            _bump(run_id, "retries")
            t0 = time.time()
            while time.time() - t0 < wait:
                if _paused(book_id):
                    raise _Halt("paused", "paused", "已暂停") from e
                time.sleep(2)


def _check_cost(run_id: int, book_id: int) -> None:
    from app.llm import archive

    with session_scope() as s:
        r = s.get(AutoRun, run_id)
        cap = float(((r.settings if r else None) or {}).get("max_cost_cny") or 0)
        if not cap or r is None:
            return
        used = archive.spent(s, book_id=book_id, since=r.started_at)
    if used >= cap:
        raise _Halt("stopped", "budget", f"本次一键成书已花 ¥{used:.2f}，到了上限 ¥{cap:.2f}。调高上限后点继续")


def _drive(book_id: int, run_id: int, ctx: JobContext, state: dict[str, Any], batch_state: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        run = s.get(AutoRun, run_id)
        assert run is not None
        stage = run.stage
        st = norm_settings(run.settings)
    if stage in ("setup", "bible"):
        ctx.progress(2, "准备设定")
        _retry(run_id, book_id, "准备设定", lambda: _setup(book_id, run_id, ctx, st))
        stage = "plan"
        _save(run_id, ctx, state, batch_state, stage)
    if stage == "plan":
        with session_scope() as s:
            planned = wanben.plan_summary(s, book_id).get("planned")
        if not planned:
            ctx.progress(5, "倒推卷纲")
            r = _retry(run_id, book_id, "倒推卷纲", lambda: wanben.plan_job(book_id, ctx))
            _event(run_id, "plan", f"卷纲已规划：{(r or {}).get('total_chapters', {}).get('after', '?')} 章 / {len((r or {}).get('volumes') or [])} 卷")
        stage = "write"
        _save(run_id, ctx, state, batch_state, stage)
    while True:
        if _paused(book_id):
            raise _Halt("paused", "paused", "已暂停")
        _check_cost(run_id, book_id)
        _heal_pending(book_id, run_id, st, ctx)
        _decision_points(book_id, run_id, st, state, ctx)
        _save(run_id, ctx, state, batch_state, "write")
        with session_scope() as s:
            prog = wanben.progress(s, book_id)
        if prog["chapters_written"] >= prog["chapters_total"]:
            _set(run_id, status="done", stage="done", stop_reason="", message="全书写完",
                 finished_at=utcnow(), state={**state, "batch": batch_state})
            _event(run_id, "done", f"全书完结：{prog['chapters_total']} 章，{prog['words']} 字")
            return {"run_id": run_id, "status": "done", "chapters": prog["chapters_total"], "words": prog["words"]}
        _clamp_batch(book_id, st, state)

        def on_chapter(res: dict[str, Any]) -> str:  # v0.17 按章自愈：写完一章马上审批，不过就停
            n = int(res.get("number") or 0)
            ctx.progress(95, f"第{n}章：自动审批")
            return _retry(run_id, book_id, f"第{n}章自愈",
                          lambda: heal_chapter(book_id, run_id, int(res["chapter_id"]), golden=n <= int(st["golden_chapters"])))

        r = _retry(run_id, book_id, "连写", lambda: wanben._run_one_batch(book_id, ctx, batch_state, on_chapter))  # noqa: SLF001
        batch_state.pop("current", None)
        batch_state.pop("chapter_cp", None)
        r = r or {}
        if r.get("batch"):
            b = r["batch"]
            _event(run_id, "batch", f"第{b.get('start_no')}–{b.get('end_no')}章：{b.get('message') or r.get('message') or ''}")
        if r.get("reason") == "paused":
            raise _Halt("paused", "paused", "已暂停")
        if r.get("reason") == "needs_review":
            _save(run_id, ctx, state, batch_state, "write")
            raise _Halt("waiting", "needs_review", r.get("message") or "有一章待你看")
        if r.get("stopped") and r.get("reason") in ("pending_chapter", "refine_pending", "awaiting_adopt", "review_failed"):
            continue  # 下一轮先按章自愈再接着写
        _save(run_id, ctx, state, batch_state, "write")


def _setup(book_id: int, run_id: int, ctx: JobContext, st: dict[str, Any]) -> None:
    from app.services import fanfic, planning

    with session_scope() as s:
        book = common.get_book(s, book_id)
        if common.chapter_review_mode(book):
            book.approval_mode, book.agent_auto_apply = "auto", True
            s.add(book)
            s.commit()
            _event(run_id, "setup", "审批模式切到自动（一键成书要自动采纳和提交）")
        is_ff = bool(book.fanfic)
        prot = (book.fanfic or {}).get("protagonist") if is_ff else None
        have = common.cards(s, book_id, include_deprecated=True)
        imported = any((c.data or {}).get("from_fanfic_source") for c in have)
    if is_ff and not imported:
        ctx.progress(3, "导入原著设定")
        try:
            r = fanfic.import_cards(book_id, list(fanfic.IMPORT_PARTS))
            _event(run_id, "setup", f"导入原著设定 {len(r.get('cards') or [])} 条")
        except Exception as e:  # noqa: BLE001
            _event(run_id, "setup", f"原著设定没导入：{e}"[:200])
    if is_ff and isinstance(prot, dict) and prot.get("source") == "oc" and not prot.get("card_id"):
        ctx.progress(4, "生成原创主角")
        fanfic.generate_oc(book_id, ctx)
        _event(run_id, "setup", "原创主角已写进设定库")
    with session_scope() as s:
        have = common.cards(s, book_id)
        prot_card = common.protagonist(s, book_id)
        has_cheat = any(c.type in ("cheat", "power") for c in have)
    if is_ff or len(have) < 8 or prot_card is None or not has_cheat:
        ctx.progress(6, "补全设定库")
        r = planning.generate_bible(book_id, ctx, keep_existing=True)
        _event(run_id, "setup", f"设定库补了 {r.get('cards', 0)} 张卡")
    with session_scope() as s:
        book = common.get_book(s, book_id)
        wanben.update_settings(s, book, {"mode": "wanben", "target_words": st["target_words"], "chapter_words": st["chapter_words"],
                                         "batch_size": st["batch_size"], "auto_continue": False, "refine_scope": "first_n",
                                         "golden_chapters": st["golden_chapters"], "pause_on_unapproved_refine": False})
    _event(run_id, "setup", f"切到完本模式：{st['target_words'] // 10000} 万字，每章约 {st['chapter_words']} 字")


def _clamp_batch(book_id: int, st: dict[str, Any], state: dict[str, Any]) -> None:
    """批次在开篇边界和卷末截断，好在这些地方停下复盘。"""
    with session_scope() as s:
        book = common.get_book(s, book_id)
        nxt = wanben._written_max(s, book_id) + 1  # noqa: SLF001
        vols = wanben.volumes(s, book_id)
        v = wanben.volume_for(vols, nxt)
        limit = int(wanben._vol_plan(v).get("end") or nxt) if v else nxt + st["batch_size"] - 1  # noqa: SLF001
        g = int(st["golden_chapters"])
        if g and nxt <= g:
            limit = min(limit, g)
        bs = max(1, min(int(st["batch_size"]), limit - nxt + 1))
        if int(wanben.raw_settings(book)["batch_size"]) != bs:
            wanben.update_settings(s, book, {"batch_size": bs})


# ------------------------------------------------------------------ 自愈

def _score(review: dict[str, Any] | None) -> tuple[int, int, int]:
    sc = wanben._scores(review)  # noqa: SLF001
    return (1 if sc["passed"] else 0, int(sc["reader"] or 0), int(sc["overall"] or 0))


def _heal_pending(book_id: int, run_id: int, st: dict[str, Any], ctx: JobContext) -> None:
    """继续运行时：前面停下没提交的章先处理（按章号逐章）；还没过就停在这里待你看，不往下写。"""
    with session_scope() as s:
        pend = [(c.id or 0, c.number) for c in s.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.status != "committed")
                                                     .order_by(Chapter.number))]
    for cid, number in pend:
        ctx.progress(95, f"第{number}章：自动审批")
        verdict = _retry(run_id, book_id, f"第{number}章自愈",
                         lambda: heal_chapter(book_id, run_id, cid, golden=number <= int(st["golden_chapters"])))
        if verdict != "committed":
            raise _Halt("waiting", "needs_review", f"第{number}章自动修了 {HEAL_ROUNDS} 轮还没过审，待你看")


def heal_chapter(book_id: int, run_id: int, chapter_id: int, golden: bool = False) -> str:
    """一章没提交（审稿没过、精修章等审批）：
    - 没选版本的先采纳最高分版本；
    - 过审：开篇章读者分不到 GOLDEN_READER_MIN 时再打磨，其余直接提交；
    - 没过审：带完整上下文和审稿问题 + 读者意见整章重写，最多 HEAL_ROUNDS 轮；新稿字数不到目标 85% 不用，
      分数不比原稿高不换；过审就提交；
    - 还没过：标「待你看」，返回 needs_review，调用方停下不往下写。
    作者改过正文后再点继续：正文变了就重审一次，过审就提交；没改还没过的不再自动重写，继续等作者。
    返回 committed / needs_review。"""
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        if ch is None or ch.status == "committed":
            return "committed"
        need_adopt = not ch.content.strip() and bool(ch.variants)
        best = max(ch.variants, key=writing._variant_score) if need_adopt else None  # noqa: SLF001
    if best is not None:
        writing.adopt_variant(chapter_id, int(best["id"]))
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        content, review = ch.content, dict(ch.review or {})
        number = ch.number
        guide = "；".join(guidance_lines(s, book_id, number))
    if not content.strip():
        raise Conflict(f"第{number}章正文为空，没法自动提交")
    heal = dict(review.get("heal") or {})
    if heal.get("exhausted"):
        if heal.get("content_hash") == writing._content_hash(content) and not review.get("passed"):  # noqa: SLF001
            return _needs_review(run_id, chapter_id, number, review)
        review, _ = wanben._evaluate_text(chapter_id, content)  # noqa: SLF001
        _save_review(chapter_id, review, {**heal, "content_hash": writing._content_hash(content)})  # noqa: SLF001
        if not review.get("passed"):
            return _needs_review(run_id, chapter_id, number, review)
        return _commit(run_id, chapter_id, number, healed=False)
    if not review or "passed" not in review:
        review, _ = wanben._evaluate_text(chapter_id, content)  # noqa: SLF001
    sc = _score(review)
    target = writing.target_words(chapter_id)
    rounds = int(heal.get("rounds") or 0)
    improved = False
    def reader_low(rv: dict[str, Any]) -> bool:
        r = (rv.get("reader") or {}).get("score")
        return golden and isinstance(r, int) and r < GOLDEN_READER_MIN

    while rounds < HEAL_ROUNDS and (not sc[0] or reader_low(review)):
        rounds += 1
        new = writing.rewrite_full(chapter_id, content, wanben._issues_instruction(review, guide))  # noqa: SLF001
        words = writing.count_words(new)
        if not new.strip() or new == content:
            _event(run_id, "heal", f"第{number}章第 {rounds} 轮重写没给出新稿")
        elif words < HEAL_MIN_RATIO * target:
            _event(run_id, "heal", f"第{number}章第 {rounds} 轮重写只有 {words} 字（目标 {target} 字），不采用")
        else:
            rv2, _ = wanben._evaluate_text(chapter_id, new)  # noqa: SLF001
            sc2 = _score(rv2)
            if sc2 > sc:
                writing.apply_rewrite(chapter_id, new, f"一键成书自愈第 {rounds} 轮前")
                _event(run_id, "heal", f"第{number}章第 {rounds} 轮整章重写，读者分 {sc[1]} → {sc2[1]}，综合分 {sc[2]} → {sc2[2]}")
                content, review, sc, improved = new, rv2, sc2, True
            else:
                _event(run_id, "heal", f"第{number}章第 {rounds} 轮重写没比原稿好（读者分 {sc2[1]}，综合分 {sc2[2]}），保留原稿")
        _save_review(chapter_id, review, {"rounds": rounds})
    if sc[0]:
        return _commit(run_id, chapter_id, number, healed=improved)
    _save_review(chapter_id, review, {"rounds": rounds, "exhausted": True, "content_hash": writing._content_hash(content)})  # noqa: SLF001
    return _needs_review(run_id, chapter_id, number, review)


def _save_review(chapter_id: int, review: dict[str, Any], heal: dict[str, Any]) -> None:
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        ch.review = writing.carry_review(ch.review, {**review, "heal": {**heal, "at": utcnow().isoformat()}})
        s.add(ch)
        s.commit()


def _commit(run_id: int, chapter_id: int, number: int, healed: bool) -> str:
    writing.commit_chapter(chapter_id)
    if healed:
        _bump(run_id, "healed")
    with session_scope() as s:  # 之前标过待你看的章，作者改好过审了就从清单上划掉
        r = s.get(AutoRun, run_id)
        if r is not None and any(f.get("chapter_id") == chapter_id and not f.get("resolved") for f in r.flags or []):
            r.flags = [{**f, "resolved": True} if f.get("chapter_id") == chapter_id else f for f in r.flags or []]
            s.add(r)
            s.commit()
    return "committed"


def _needs_review(run_id: int, chapter_id: int, number: int, review: dict[str, Any]) -> str:
    highs = [str(i.get("comment") or "") for i in review.get("issues") or [] if i.get("severity") == "high"]
    reader = review.get("reader") or {}
    reason = highs[0] if highs else (f"读者分 {reader['score']}：{reader.get('verdict') or ''}" if isinstance(reader.get("score"), int)
                                     else "审稿没过")
    with session_scope() as s:
        ch = s.get(Chapter, chapter_id)
        assert ch is not None
        already = False
        r = s.get(AutoRun, run_id)
        if r is not None:
            already = any(f.get("chapter_id") == chapter_id and f.get("blocking") and not f.get("resolved") for f in r.flags or [])
    _flag(run_id, ch, reason, blocking=True)
    if not already:
        _bump(run_id, "needs_review")
        _event(run_id, "needs_review", f"第{number}章自动修了 {HEAL_ROUNDS} 轮还没过审，停下待你看：{reason}")
    return "needs_review"


def accept_flag(book_id: int, chapter_id: int) -> dict[str, Any]:
    """作者看过「待你看」的章，选择放行：照现在的正文提交，划掉清单，之后点继续接着写。"""
    with session_scope() as s:
        run = latest_run(s, book_id)
        ch = s.get(Chapter, chapter_id)
        if ch is None or ch.book_id != book_id:
            raise NotFound("章节不存在")
        if not ch.content.strip():
            raise Conflict("这一章正文为空，先采纳一个版本")
        committed = ch.status == "committed"
    if not committed:
        writing.commit_chapter(chapter_id)
    if run is not None:
        resolve_flag(book_id, chapter_id)
        _event(run.id or 0, "accept", f"第{ch.number}章作者放行")
    return {"ok": True, "chapter_id": chapter_id}


# ------------------------------------------------------------------ 决策点

def _decision_points(book_id: int, run_id: int, st: dict[str, Any], state: dict[str, Any], ctx: JobContext) -> None:
    guided = st["level"] == "guided"
    with session_scope() as s:
        pend = s.exec(select(AutoDecision).where(AutoDecision.run_id == run_id, AutoDecision.status == "pending")).first()
        if pend is not None:
            raise _Halt("waiting", "decision", f"等你拍板：{pend.title}")
        written = max([c.number for c in common.committed_chapters(s, book_id)] or [0])
    g = int(st["golden_chapters"])
    if g and written >= g and not state.get("opening_done"):
        state["opening_done"] = True
        if guided and "opening" in st["stop_on"]:
            with session_scope() as s:
                d = AutoDecision(book_id=book_id, run_id=run_id, kind="opening", title=f"开篇 {g} 章写完了，确认方向",
                                 context="先读一读开篇。没问题就接着写；想调整写下要求，后面每章都会照着写。",
                                 options=[{"title": "开篇没问题，接着写", "summary": "", "turns": []}], recommended=0)
                s.add(d)
                s.commit()
            raise _Halt("waiting", "decision", f"等你拍板：开篇 {g} 章写完了，确认方向")
    with session_scope() as s:
        vols = wanben.volumes(s, book_id)
        todo = [(i, v.order) for i, v in enumerate(vols)
                if int(wanben._vol_plan(v).get("end") or 0) and int(wanben._vol_plan(v)["end"]) <= written  # noqa: SLF001
                and not (v.beats or {}).get("recap")]
        n_vol = len(vols)
    for i, order in todo:
        ctx.progress(96, f"第{order}卷写完：卷末复盘")
        data = _retry(run_id, book_id, f"第{order}卷复盘", lambda: volume_review(book_id, order))
        _bump(run_id, "volumes_reviewed")
        probs = data.get("problems") or []
        _event(run_id, "review", f"第{order}卷复盘完成" + (f"，发现 {len(probs)} 个问题" if probs else ""))
        if i + 1 >= n_vol or not data.get("options"):
            continue
        with session_scope() as s:
            opts = data["options"]
            rec = int(data.get("recommended") or 0)
            opts[rec] = {**opts[rec], "later": data.get("later") or []}
            d = AutoDecision(book_id=book_id, run_id=run_id, kind="volume", volume=order,
                             title=f"第{order}卷写完了，选第{order + 1}卷走向",
                             context=str(data.get("recap") or "")[:800] + ("\n问题：" + "；".join(probs) if probs else ""),
                             options=opts, recommended=rec)
            s.add(d)
            s.commit()
            s.refresh(d)
            did = d.id or 0
        if guided and "volume" in st["stop_on"]:
            raise _Halt("waiting", "decision", f"等你拍板：第{order}卷写完了，选第{order + 1}卷走向")
        apply_decision(did, rec, "", auto=True)


def answer(book_id: int, decision_id: int, choice: int | None, custom: str) -> dict[str, Any]:
    with session_scope() as s:
        d = s.get(AutoDecision, decision_id)
        if d is None or d.book_id != book_id:
            raise NotFound("决策点不存在")
        if d.status != "pending":
            raise Conflict("这个决策点已经拍过板了")
        if choice is None and not custom.strip():
            raise ValueError("选一个走向，或者写下你的要求")
        if choice is not None and not (0 <= choice < len(d.options or [])):
            raise ValueError("选项不存在")
    apply_decision(decision_id, choice, custom, auto=False)
    run, job = start(book_id)
    return {"run_id": run.id, "job_id": job.id}


def apply_decision(decision_id: int, choice: int | None, custom: str, auto: bool) -> None:
    with session_scope() as s:
        d = s.get(AutoDecision, decision_id)
        assert d is not None
        run_id, kind, vol_order = d.run_id, d.kind, d.volume
        opts = list(d.options or [])
        rec = d.recommended
        d.status, d.choice, d.custom, d.answered_at = ("auto" if auto else "answered"), choice, custom.strip()[:1000], utcnow()
        s.add(d)
        s.commit()
        book_id = d.book_id
        st = norm_settings((s.get(AutoRun, run_id) or AutoRun(book_id=book_id)).settings)
    if kind == "opening":
        _add_guidance(run_id, custom, int(st["golden_chapters"]) + 1, None, "开篇确认")
        _event(run_id, "decision", "开篇确认：接着写" + (f"，要求：{custom.strip()[:80]}" if custom.strip() else ""))
        return
    opt = opts[choice] if choice is not None and 0 <= choice < len(opts) else None
    with session_scope() as s:
        vols = wanben.volumes(s, book_id)
        nv = vols[vol_order] if vol_order < len(vols) else None
        if nv is None:
            return
        p = wanben._vol_plan(nv)  # noqa: SLF001
        lo, hi = int(p.get("start") or 0), int(p.get("end") or 0)
        if not nv.locked and (opt or custom.strip()):
            if opt:
                if opt.get("title"):
                    nv.title = str(opt["title"])[:80]
                summ = str(opt.get("summary") or nv.summary or "")
                turns = [str(x) for x in opt.get("turns") or [] if x]
                if turns:
                    summ += "\n关键转折：" + "；".join(turns)
                nv.summary = summ
                plan = dict(p)
                for k in ("crisis", "closure"):
                    if opt.get(k):
                        plan[k] = str(opt[k])[:300]
                nv.beats = {**(nv.beats or {}), "wanben": plan, "direction": {k: opt.get(k) for k in ("title", "summary", "turns", "why")}}
            if custom.strip():
                nv.summary = (nv.summary or "") + f"\n作者要求：{custom.strip()[:300]}"
            s.add(nv)
        if opt is not None and choice == rec:
            by_order = {v.order: v for v in vols}
            for it in opt.get("later") or []:
                v = by_order.get(int(it.get("order") or 0)) if isinstance(it, dict) else None
                if v is None or v.locked or v.order <= vol_order + 1 or not str(it.get("summary") or "").strip():
                    continue
                v.summary = str(it["summary"])[:600]
                s.add(v)
        wanben.annotate_roles(s, book_id)
        s.commit()
    if custom.strip():
        _add_guidance(run_id, custom, lo, hi or None, f"第{vol_order + 1}卷")
    label = opt.get("title") if opt else "按作者要求"
    _event(run_id, "decision", f"第{vol_order + 1}卷走向：{label}{'（自动按推荐）' if auto else ''}")


# ------------------------------------------------------------------ 卷末复盘

SUMMARY_BUDGET = 6000


def volume_review(book_id: int, order: int) -> dict[str, Any]:
    """卷末复盘：前情回顾 + 长期状态 + 问题 + 下一卷走向选项。回顾存进卷节点 beats["recap"]，写章时当长期记忆。"""
    with session_scope() as s:
        book = common.get_book(s, book_id)
        vols = wanben.volumes(s, book_id)
        v = next(x for x in vols if x.order == order)
        p = wanben._vol_plan(v)  # noqa: SLF001
        a, b = int(p.get("start") or 1), int(p.get("end") or 1)
        chs = [c for c in common.committed_chapters(s, book_id) if a <= c.number <= b]
        per = max(40, SUMMARY_BUDGET // max(1, len(chs)))
        summaries = "\n".join(f"第{c.number}章 {c.title}：{(c.summary or '')[:per]}" for c in chs) or "（无）"
        cards = {c.id: c for c in common.cards(s, book_id)}
        prot = common.protagonist(s, book_id)
        facts = list(s.exec(select(Fact).where(Fact.book_id == book_id, Fact.to_chapter == None)))  # noqa: E711
        facts.sort(key=lambda f: (0 if prot and f.entity_id == prot.id else 1, -(f.from_chapter or 0)))
        state = "\n".join(f"- {(cards[f.entity_id].name if f.entity_id in cards else '全书')}·{f.key}：{f.value}"[:120]
                          for f in facts[:40]) or "（无）"
        opens = common.open_foreshadows(s, book_id)
        fs = "\n".join(f"- {f.desc}（第{f.planted_ch}章埋，{outline.foreshadow_age_label(f, b)}）" for f in opens[:15]) or "（无）"
        beats = [x for x in outline.chapter_beats_list(s, book_id) if a <= int(x["number"]) <= b]
        pacing = "\n".join(f"- {x}" for x in outline.pacing_audit(beats, opens, b)) or "（无）"
        run = latest_run(s, book_id)
        guide = "\n".join(f"- {g.get('text')}" for g in (run.guidance if run else []) or []) or "（无）"
        nxt = next((x for x in vols if x.order == order + 1), None)
        np_ = wanben._vol_plan(nxt) if nxt else {}  # noqa: SLF001
        next_plan = (f"第{order + 1}卷（第{np_.get('start')}–{np_.get('end')}章）{nxt.title}：{nxt.summary}；危机：{np_.get('crisis', '')}；"
                     f"收束：{np_.get('closure', '')}" if nxt else "（没有下一卷，这是最后一卷）")
        later = "\n".join(f"- 第{x.order}卷 {x.title}：{(x.summary or '')[:120]}" for x in vols if x.order > order + 1) or "（无）"
        root = next((n for n in common.outline_nodes(s, book_id) if n.level == "book"), None)
        ending = (((root.beats or {}).get("wanben") or {}).get("ending") if root else "") or "（未定）"
        total = int(wanben.plan_summary(s, book_id).get("total_chapters") or b)
        meta = {**common.kit_meta(s, book), "volume": order}
        user = render("volume_review", book_context=common.book_context(s, book, with_cards=False), ending=ending, volume=order,
                      start=a, end=b, volume_plan=f"{v.title}：{v.summary}；危机：{p.get('crisis', '')}；收束：{p.get('closure', '')}",
                      summaries=summaries, state=state, foreshadows=fs, pacing=pacing, guidance=guide, next_plan=next_plan,
                      later=later, remaining=max(0, total - b))
    data = get_gateway().chat_json("volume_review", system_prompt("outline"), user, meta=meta)
    if not isinstance(data, dict):
        raise ValueError("卷末复盘结果不是 JSON 对象")
    opts = []
    for o in data.get("options") or []:
        if isinstance(o, dict) and (o.get("title") or o.get("summary")):
            opts.append({"title": str(o.get("title") or "")[:80], "summary": str(o.get("summary") or "")[:600],
                         "crisis": str(o.get("crisis") or "")[:300], "closure": str(o.get("closure") or "")[:300],
                         "turns": [str(x)[:120] for x in o.get("turns") or [] if x][:4], "why": str(o.get("why") or "")[:200]})
    opts = opts[:3]
    try:
        rec = int(data.get("recommended") or 0)
    except (TypeError, ValueError):
        rec = 0
    out = {"recap": str(data.get("recap") or "").strip()[:800],
           "state": [str(x)[:160] for x in data.get("state") or [] if x][:10],
           "problems": [str(x)[:200] for x in data.get("problems") or [] if x][:6],
           "options": opts, "recommended": rec if 0 <= rec < len(opts) else 0,
           "later": [x for x in data.get("later") or [] if isinstance(x, dict)][:20]}
    with session_scope() as s:
        v = next(x for x in wanben.volumes(s, book_id) if x.order == order)
        v.beats = {**(v.beats or {}), "recap": {"text": out["recap"] or f"第{order}卷已写完", "state": out["state"],
                                                "problems": out["problems"], "at": utcnow().isoformat()}}
        s.add(v)
        s.commit()
    return out


# ------------------------------------------------------------------ 输出

def decision_out(d: AutoDecision) -> dict[str, Any]:
    return {"id": d.id, "kind": d.kind, "volume": d.volume, "title": d.title, "context": d.context,
            "options": [{k: v for k, v in o.items() if k != "later"} for o in d.options or []],
            "recommended": d.recommended, "status": d.status, "choice": d.choice, "custom": d.custom,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "answered_at": d.answered_at.isoformat() if d.answered_at else None}


def run_out(r: AutoRun) -> dict[str, Any]:
    return {"id": r.id, "status": r.status, "stage": r.stage, "stop_reason": r.stop_reason, "message": r.message,
            "job_id": r.job_id, "settings": r.settings or {}, "stats": r.stats or {},
            "events": list(reversed(r.events or []))[:80], "flags": [f for f in r.flags or [] if not f.get("resolved")],
            "flags_total": len(r.flags or []), "guidance": r.guidance or [],
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def overview(s: Session, book_id: int) -> dict[str, Any]:
    from app.llm import archive

    book = common.get_book(s, book_id)
    run = latest_run(s, book_id)
    out: dict[str, Any] = {"book_id": book_id, "settings": get_settings(s, book_id), "run": run_out(run) if run else None,
                           "decisions": [], "progress": None, "cost": 0.0, "running": bool(find_active(KIND, _ref(book_id))),
                           "fanfic": bool(book.fanfic), "recaps": []}
    if run is not None:
        ds = list(s.exec(select(AutoDecision).where(AutoDecision.run_id == run.id).order_by(AutoDecision.id.desc())))
        out["decisions"] = [decision_out(d) for d in ds[:12]]
        out["cost"] = round(archive.spent(s, book_id=book_id, since=run.started_at), 2)
    if wanben.book_mode(book) == "wanben":
        out["progress"] = wanben.progress(s, book_id)
        out["recaps"] = [{"order": v.order, "title": v.title, **((v.beats or {}).get("recap") or {})}
                         for v in wanben.volumes(s, book_id) if (v.beats or {}).get("recap")]
    return out


def resolve_flag(book_id: int, chapter_id: int) -> None:
    with session_scope() as s:
        run = latest_run(s, book_id)
        if run is None:
            raise NotFound("没有一键成书记录")
        run.flags = [{**f, "resolved": True} if f.get("chapter_id") == chapter_id else f for f in run.flags or []]
        s.add(run)
        s.commit()


def _resume(job: Any, state: dict[str, Any]) -> Any:
    book_id = int(job.book_id or 0)
    return lambda ctx: run_job(book_id, ctx)


register_resumable(KIND, _resume)

