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
    _add_missing_columns(engine)
    _engine = engine
    return engine


def _add_missing_columns(engine: Engine) -> None:
    """轻量迁移：给已有 SQLite 表补上模型里新增的列（只加列，不改不删）。"""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                if default is None:
                    default = "" if "CHAR" in ddl_type.upper() or "TEXT" in ddl_type.upper() else 0
                lit = f"'{default}'" if isinstance(default, str) else str(int(default))
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type} NOT NULL DEFAULT {lit}'))


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
