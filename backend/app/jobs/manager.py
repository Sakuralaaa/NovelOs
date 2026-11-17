"""任务系统：进程内 asyncio 后台任务 + 数据库 Job 表。

- 生成类接口立即返回 Job（queued），后台 asyncio 任务里用 to_thread 执行同步工作函数。
- 工作函数拿到 JobContext，可上报进度；返回值（dict）写入 result。
- 服务启动时把遗留的 queued/running 任务标为 failed（进程内任务无法恢复）。
- v0.9.4 断点续跑：多步任务用 ctx.checkpoint(stage, state) 把已完成步骤写进 job_checkpoint 表；
  重启后有断点、且该 kind 注册了续跑函数的任务标为 interrupted（不是 failed），
  POST /api/jobs/{id}/resume 用同一个 Job 从最后完成的步骤继续（ctx.resume_state 拿到断点）。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from sqlmodel import select

from app.db import session_scope
from app.models.tables import Job, JobCheckpoint, utcnow

log = logging.getLogger("novelos.jobs")

_tasks: set[asyncio.Task[None]] = set()
_book_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: int, book_id: int | None, resume_state: dict[str, Any] | None = None) -> None:
        self.job_id = job_id
        self.book_id = book_id
        self.resume_state = resume_state  # v0.9.4：续跑时为上次的断点 state，否则 None

    def checkpoint(self, stage: str, state: dict[str, Any], kind: str = "") -> None:
        """v0.9.4：记录最后完成的步骤（整份 state 覆盖写）。"""
        save_checkpoint(self.job_id, stage, state, kind=kind, book_id=self.book_id)

    def progress(self, pct: int, message: str = "") -> None:
        with session_scope() as s:
            job = s.get(Job, self.job_id)
            if job is None:
                return
            job.progress = max(0, min(100, int(pct)))
            if message:
                job.message = message
            job.updated_at = utcnow()
            s.add(job)
            s.commit()


Worker = Callable[[JobContext], dict[str, Any] | None]
# v0.9.4：kind → 续跑工厂 (job, checkpoint_state) -> Worker；工作函数从 ctx.resume_state 接着做
ResumeFactory = Callable[[Job, dict[str, Any]], Worker]
_resumers: dict[str, ResumeFactory] = {}
RESUMABLE_STATUSES = ("interrupted", "failed")


class NotResumable(Exception):
    pass


def register_resumable(kind: str, factory: ResumeFactory) -> None:
    _resumers[kind] = factory


def save_checkpoint(job_id: int, stage: str, state: dict[str, Any], kind: str = "", book_id: int | None = None) -> None:
    with session_scope() as s:
        cp = s.get(JobCheckpoint, job_id)
        if cp is None:
            job = s.get(Job, job_id)
            cp = JobCheckpoint(job_id=job_id, kind=kind or (job.kind if job else ""), book_id=book_id if book_id is not None else (job.book_id if job else None))
        cp.stage = stage
        cp.state = dict(state)
        cp.updated_at = utcnow()
        s.add(cp)
        s.commit()


def load_checkpoint(job_id: int) -> JobCheckpoint | None:
    with session_scope() as s:
        return s.get(JobCheckpoint, job_id)


def clear_checkpoint(job_id: int) -> None:
    with session_scope() as s:
        cp = s.get(JobCheckpoint, job_id)
        if cp is not None:
            s.delete(cp)
            s.commit()


def resume_info(job: Job | None) -> dict[str, Any]:
    """GET /api/jobs/{id} 的 v0.9.4 字段：resumable（能否续跑）、checkpoint（最后完成的步骤，没有为 null）。"""
    if job is None or job.id is None:
        return {"resumable": False, "checkpoint": None}
    cp = load_checkpoint(job.id)
    ok = cp is not None and job.status in RESUMABLE_STATUSES and job.kind in _resumers
    info = None
    if cp is not None:
        st = cp.state or {}
        info = {"stage": cp.stage, "resumes": cp.resumes, "updated_at": cp.updated_at.isoformat() if cp.updated_at else None,
                "chapter_id": st.get("chapter_id"), "number": st.get("number"), "scenes_total": len(st.get("scenes") or []) or None,
                "scenes_done": len(((st.get("partial") or {}).get("texts")) or []) if st.get("partial") else None,
                "variants_done": len(st.get("variants_done") or [])}
    return {"resumable": ok, "checkpoint": info}


def book_lock(book_id: int) -> threading.Lock:
    with _locks_guard:
        if book_id not in _book_locks:
            _book_locks[book_id] = threading.Lock()
        return _book_locks[book_id]


def create_job(kind: str, book_id: int | None = None, message: str = "排队中", ref: str = "") -> Job:
    with session_scope() as s:
        job = Job(kind=kind, book_id=book_id, status="queued", message=message, ref=ref)
        s.add(job)
        s.commit()
        s.refresh(job)
        return job


def _finish(job_id: int, *, status: str, result: dict[str, Any] | None = None, error: str | None = None, message: str = "") -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        job.status = status
        if status == "succeeded":
            job.progress = 100
        job.result = result
        job.error = error
        if message:
            job.message = message
        job.updated_at = utcnow()
        s.add(job)
        s.commit()


def _run_sync(job_id: int, book_id: int | None, fn: Worker, lock_book: bool, kind: str = "",
              resume_state: dict[str, Any] | None = None) -> None:
    from app.llm import usage as usage_log

    token = usage_log.set_job_context(kind, book_id, job_id)  # v0.9.3：模型调用记用量时读 Job.kind / book_id
    try:
        _run_sync_inner(job_id, book_id, fn, lock_book, resume_state)
    finally:
        usage_log.reset_job_context(token)


def _run_sync_inner(job_id: int, book_id: int | None, fn: Worker, lock_book: bool,
                    resume_state: dict[str, Any] | None = None) -> None:
    ctx = JobContext(job_id, book_id, resume_state)
    lock = book_lock(book_id) if (lock_book and book_id is not None) else None
    if lock is not None and not lock.acquire(timeout=0.1):
        ctx.progress(0, "等待同一本书的其他写作任务完成")
        lock.acquire()
    try:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job:
                job.status = "running"
                job.message = "续跑中" if resume_state is not None else "运行中"
                job.updated_at = utcnow()
                s.add(job)
                s.commit()
        result = fn(ctx) or {}
        clear_checkpoint(job_id)  # 成功后断点作废
        _finish(job_id, status="succeeded", result=result, message="完成")
    except Exception as e:  # noqa: BLE001
        log.error("任务 %s 失败：%s\n%s", job_id, e, traceback.format_exc())
        _finish(job_id, status="failed", error=str(e) or e.__class__.__name__, message="失败")
    finally:
        if lock is not None:
            lock.release()


def find_active(kind: str, ref: str) -> Job | None:
    """同一对象上同类、还在排队/运行的任务（用来去重：重复点击直接返回已有任务）。"""
    with session_scope() as s:
        return s.exec(select(Job).where(Job.kind == kind, Job.ref == ref, Job.status.in_(["queued", "running"]))  # type: ignore[attr-defined]
                      .order_by(Job.id.desc())).first()  # type: ignore[union-attr]


def submit(kind: str, fn: Worker, book_id: int | None = None, lock_book: bool = False, ref: str = "") -> Job:
    """创建 Job 并在后台运行。必须在事件循环中调用（async 路由）。ref 标记任务关联的对象（如 "rank_item:12"）。"""
    job = create_job(kind, book_id, ref=ref)
    job_id = job.id or 0

    async def runner() -> None:
        await asyncio.to_thread(_run_sync, job_id, book_id, fn, lock_book, kind)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(runner())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        # 没有事件循环（例如在脚本中直接调用）：退化为线程
        threading.Thread(target=_run_sync, args=(job_id, book_id, fn, lock_book, kind), daemon=True).start()
    return job


def _resubmit(job: Job, fn: Worker, lock_book: bool, resume_state: dict[str, Any]) -> None:
    job_id, book_id, kind = job.id or 0, job.book_id, job.kind

    async def runner() -> None:
        await asyncio.to_thread(_run_sync, job_id, book_id, fn, lock_book, kind, resume_state)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(runner())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        threading.Thread(target=_run_sync, args=(job_id, book_id, fn, lock_book, kind, resume_state), daemon=True).start()


def resume(job_id: int, lock_book: bool = True) -> Job:
    """v0.9.4：从断点续跑（同一个 Job id）。不可续跑抛 NotResumable（路由转 409），任务不存在抛 LookupError。"""
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise LookupError("任务不存在")
        cp = s.get(JobCheckpoint, job_id)
        if job.status not in RESUMABLE_STATUSES:
            raise NotResumable(f"任务状态为 {job.status}，只有中断（interrupted）或失败（failed）的任务能续跑")
        if job.kind not in _resumers:
            raise NotResumable(f"{job.kind} 类任务不支持续跑，请重新发起")
        if cp is None:
            raise NotResumable("这个任务没有断点记录，请重新发起")
        state = dict(cp.state or {})
        cp.resumes = (cp.resumes or 0) + 1
        s.add(cp)
        job.status = "queued"
        job.error = None
        job.message = f"排队续跑（从「{cp.stage}」之后继续）"
        job.updated_at = utcnow()
        s.add(job)
        s.commit()
        s.refresh(job)
    fn = _resumers[job.kind](job, state)
    _resubmit(job, fn, lock_book, state)
    return job


def recover_on_startup() -> int:
    """把上次进程遗留的 queued/running 任务标为中断：
    有断点且可续跑的标 interrupted（可 POST /api/jobs/{id}/resume），其余标 failed（同旧行为）。"""
    n = 0
    with session_scope() as s:
        for job in s.exec(select(Job).where(Job.status.in_(["queued", "running"]))):  # type: ignore[attr-defined]
            cp = s.get(JobCheckpoint, job.id) if job.id is not None else None
            if cp is not None and job.kind in _resumers:
                job.status = "interrupted"
                job.error = f"服务重启，任务中断（已完成到「{cp.stage}」），可续跑"
                job.message = "已中断，可续跑"
            else:
                job.status = "failed"
                job.error = "服务重启，任务中断，请重新发起"
                job.message = "已中断"
            job.updated_at = utcnow()
            s.add(job)
            n += 1
        s.commit()
    return n
