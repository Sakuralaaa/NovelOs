"""SQLite 引擎与会话。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.models import tables  # noqa: F401  注册表
from app.models.tables import KV

_engine: Engine | None = None


def init_engine(settings: Settings) -> Engine:
    global _engine
    url = f"sqlite:///{settings.db_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn: Any, _: Any) -> None:  # pragma: no cover - 驱动层
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    SQLModel.metadata.create_all(engine)
    _engine = engine
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("数据库尚未初始化")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """后台任务用：自动关闭的会话（提交需显式调用）。"""
    with Session(get_engine(), expire_on_commit=False) as s:
        yield s


def get_session() -> Iterator[Session]:
    """FastAPI 依赖。"""
    with Session(get_engine(), expire_on_commit=False) as s:
        yield s


def kv_get(s: Session, key: str, default: Any = None) -> Any:
    row = s.get(KV, key)
    return default if row is None or row.value is None else row.value


def kv_set(s: Session, key: str, value: Any) -> None:
    row = s.get(KV, key)
    if row is None:
        s.add(KV(key=key, value=value))
    else:
        row.value = value
        s.add(row)
    s.commit()


__all__ = ["init_engine", "get_engine", "session_scope", "get_session", "kv_get", "kv_set", "select"]
