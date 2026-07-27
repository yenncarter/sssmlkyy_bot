"""Async database engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import time

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.base import Base
from db.models import WorkSettings


def create_engine(database_url: str) -> AsyncEngine:
    kwargs: dict = {"echo": False}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(database_url, **kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_on_connect(dbapi_conn, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _sqlite_add_column_if_missing(
    conn,
    table: str,
    column: str,
    ddl_type: str,
) -> None:
    rows = await conn.execute(text(f"PRAGMA table_info({table})"))
    cols = {row[1] for row in rows.fetchall()}
    if column not in cols:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        dialect = conn.engine.dialect.name
        sqlite_cols = [
            ("working_days", "open_time", "TIME"),
            ("working_days", "close_time", "TIME"),
            ("working_days", "slot_minutes", "INTEGER"),
            ("work_settings", "prepayment_amount", "VARCHAR(64) DEFAULT '1 000 ₽'"),
            ("bookings", "service_code", "VARCHAR(32)"),
            ("bookings", "service_title", "VARCHAR(64)"),
            ("bookings", "duration_minutes", "INTEGER"),
            ("bookings", "reminded_24h", "BOOLEAN DEFAULT 0"),
            ("bookings", "reminded_2h", "BOOLEAN DEFAULT 0"),
        ]
        pg_cols = [
            "ALTER TABLE working_days ADD COLUMN IF NOT EXISTS open_time TIME",
            "ALTER TABLE working_days ADD COLUMN IF NOT EXISTS close_time TIME",
            "ALTER TABLE working_days ADD COLUMN IF NOT EXISTS slot_minutes INTEGER",
            "ALTER TABLE work_settings ADD COLUMN IF NOT EXISTS prepayment_amount VARCHAR(64) DEFAULT '1 000 ₽'",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS service_code VARCHAR(32)",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS service_title VARCHAR(64)",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS duration_minutes INTEGER",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminded_24h BOOLEAN DEFAULT FALSE",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminded_2h BOOLEAN DEFAULT FALSE",
        ]
        if dialect == "sqlite":
            for table, col, ddl in sqlite_cols:
                await _sqlite_add_column_if_missing(conn, table, col, ddl)
        elif dialect == "postgresql":
            for stmt in pg_cols:
                await conn.execute(text(stmt))

    factory = create_session_factory(engine)
    async with factory() as session:
        existing = await session.get(WorkSettings, 1)
        if existing is None:
            session.add(
                WorkSettings(
                    id=1,
                    open_time=time(10, 0),
                    close_time=time(22, 0),
                    slot_minutes=60,
                    prepayment_amount="1 000 ₽",
                )
            )
            await session.commit()
        elif not getattr(existing, "prepayment_amount", None):
            existing.prepayment_amount = "1 000 ₽"
            await session.commit()


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
