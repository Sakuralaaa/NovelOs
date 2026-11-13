"""任务系统：进程内 asyncio 后台任务 + 数据库 Job 表。

- 生成类接口立即返回 Job（queued），后台 asyncio 任务里用 to_thread 执行同步工作函数。
- 工作函数拿到 JobContext，可上报进度；返回值（dict）写入 result。
- 服务启动时把遗留的 queued/running 任务标为 failed（进程内任务无法恢复）。
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
from app.models.tables import Job, utcnow

log = logging.getLogger("novelos.jobs")

_tasks: set[asyncio.Task[None]] = set()
_book_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: int, book_id: int | None) -> None:
        self.job_id = job_id
        self.book_id = book_id

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


def _run_sync(job_id: int, book_id: int | None, fn: Worker, lock_book: bool) -> None:
    ctx = JobContext(job_id, book_id)
    lock = book_lock(book_id) if (lock_book and book_id is not None) else None
    if lock is not None and not lock.acquire(timeout=0.1):
        ctx.progress(0, "等待同一本书的其他写作任务完成")
        lock.acquire()
    try:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job:
                job.status = "running"
                job.message = "运行中"
                job.updated_at = utcnow()
                s.add(job)
                s.commit()
        result = fn(ctx) or {}
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
        await asyncio.to_thread(_run_sync, job_id, book_id, fn, lock_book)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(runner())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        # 没有事件循环（例如在脚本中直接调用）：退化为线程
        threading.Thread(target=_run_sync, args=(job_id, book_id, fn, lock_book), daemon=True).start()
    return job


def recover_on_startup() -> int:
    """把上次进程遗留的 queued/running 任务标为 failed。"""
    n = 0
    with session_scope() as s:
        for job in s.exec(select(Job).where(Job.status.in_(["queued", "running"]))):  # type: ignore[attr-defined]
            job.status = "failed"
            job.error = "服务重启，任务中断，请重新发起"
            job.message = "已中断"
            job.updated_at = utcnow()
            s.add(job)
            n += 1
        s.commit()
    return n
