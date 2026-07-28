"""Async database engine, session factory and schema bootstrap.

There is no migration tool here on purpose: the bot is deployed by git push to
Bothost with no place to run a migration step. Instead every schema change must
be expressed as an idempotent statement in :func:`init_db`, so that booting an
old database converges to the current schema.
"""

from __future__ import annotations

import logging

from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.base import Base
from db.models import WorkSettings
from domain.slots import DEFAULT_CLOSE, DEFAULT_OPEN, DEFAULT_SLOT_MINUTES

logger = logging.getLogger("beauty_bot.db")

_LIVE_STATUS_SQL = "status IN ('pending_payment', 'active')"

# Indexes that must exist on databases created before they were introduced.
# create_all() only builds indexes together with a brand-new table.
_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_bookings_user_status",
        "CREATE INDEX IF NOT EXISTS ix_bookings_user_status "
        "ON bookings (telegram_user_id, status)",
    ),
    (
        "ix_bookings_status",
        "CREATE INDEX IF NOT EXISTS ix_bookings_status ON bookings (status)",
    ),
    (
        "ix_slots_status_held_until",
        "CREATE INDEX IF NOT EXISTS ix_slots_status_held_until "
        "ON slots (status, held_until)",
    ),
    (
        "uq_live_booking_slot",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_live_booking_slot "
        f"ON bookings (slot_id) WHERE {_LIVE_STATUS_SQL}",
    ),
    (
        "uq_live_booking_user",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_live_booking_user "
        f"ON bookings (telegram_user_id) WHERE {_LIVE_STATUS_SQL}",
    ),
)

_DUPLICATE_PROBES: dict[str, str] = {
    "uq_live_booking_slot": (
        f"SELECT slot_id, COUNT(*) c FROM bookings WHERE {_LIVE_STATUS_SQL} "
        "GROUP BY slot_id HAVING COUNT(*) > 1"
    ),
    "uq_live_booking_user": (
        f"SELECT telegram_user_id, COUNT(*) c FROM bookings WHERE {_LIVE_STATUS_SQL} "
        "GROUP BY telegram_user_id HAVING COUNT(*) > 1"
    ),
}

_SQLITE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("working_days", "open_time", "TIME"),
    ("working_days", "close_time", "TIME"),
    ("working_days", "slot_minutes", "INTEGER"),
    ("work_settings", "prepayment_amount", "VARCHAR(64) DEFAULT '1 000 ₽'"),
    ("bookings", "service_code", "VARCHAR(32)"),
    ("bookings", "service_title", "VARCHAR(64)"),
    ("bookings", "duration_minutes", "INTEGER"),
    ("bookings", "reminded_24h", "BOOLEAN DEFAULT 0"),
    ("bookings", "reminded_2h", "BOOLEAN DEFAULT 0"),
    ("bookings", "receipt_file_id", "VARCHAR(256)"),
    ("bookings", "receipt_file_type", "VARCHAR(16)"),
    ("bookings", "confirmed_at", "DATETIME"),
)

_PG_COLUMNS: tuple[str, ...] = (
    "ALTER TABLE working_days ADD COLUMN IF NOT EXISTS open_time TIME",
    "ALTER TABLE working_days ADD COLUMN IF NOT EXISTS close_time TIME",
    "ALTER TABLE working_days ADD COLUMN IF NOT EXISTS slot_minutes INTEGER",
    "ALTER TABLE work_settings ADD COLUMN IF NOT EXISTS prepayment_amount "
    "VARCHAR(64) DEFAULT '1 000 ₽'",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS service_code VARCHAR(32)",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS service_title VARCHAR(64)",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS duration_minutes INTEGER",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminded_24h BOOLEAN DEFAULT FALSE",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminded_2h BOOLEAN DEFAULT FALSE",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS receipt_file_id VARCHAR(256)",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS receipt_file_type VARCHAR(16)",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ",
)


def create_engine(database_url: str) -> AsyncEngine:
    kwargs: dict = {"echo": False, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(database_url, **kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_on_connect(dbapi_conn, _connection_record) -> None:
            cursor = dbapi_conn.cursor()
            # foreign_keys is off by default in SQLite; without it the RESTRICT
            # on bookings.slot_id is decorative.
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


async def _ensure_indexes(engine: AsyncEngine) -> list[str]:
    """Create each index in its own transaction; report what refused to build.

    A failing unique index means the data already violates the invariant. That
    is never fixed automatically: silently cancelling one of two conflicting
    bookings would destroy a real appointment. The conflicts are described back
    to the caller instead, so the master can resolve them in the admin panel.
    """
    problems: list[str] = []
    for name, ddl in _INDEXES:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
        except SQLAlchemyError as exc:
            logger.error("Индекс %s не создан: %s", name, exc)
            problems.extend(await _describe_duplicates(engine, name))
    return problems


async def _describe_duplicates(engine: AsyncEngine, index_name: str) -> list[str]:
    probe = _DUPLICATE_PROBES.get(index_name)
    if probe is None:
        return [f"индекс {index_name} не создан"]
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(probe))).fetchall()
    except SQLAlchemyError as exc:
        logger.error("Не удалось проверить дубли для %s: %s", index_name, exc)
        return [f"индекс {index_name} не создан, проверка дублей не удалась"]

    problems = []
    for key, count in rows:
        detail = (
            f"{index_name}: ключ {key} имеет {count} активных записей — "
            "отмени лишние, затем перезапусти бота"
        )
        logger.error(detail)
        problems.append(detail)
    return problems


async def init_db(engine: AsyncEngine) -> list[str]:
    """Converge the schema and return unresolved data conflicts, if any."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        dialect = conn.engine.dialect.name
        if dialect == "sqlite":
            for table, col, ddl in _SQLITE_COLUMNS:
                await _sqlite_add_column_if_missing(conn, table, col, ddl)
        elif dialect == "postgresql":
            for stmt in _PG_COLUMNS:
                await conn.execute(text(stmt))

    conflicts = await _ensure_indexes(engine)

    factory = create_session_factory(engine)
    async with factory() as session:
        existing = await session.get(WorkSettings, 1)
        if existing is None:
            session.add(
                WorkSettings(
                    id=1,
                    open_time=DEFAULT_OPEN,
                    close_time=DEFAULT_CLOSE,
                    slot_minutes=DEFAULT_SLOT_MINUTES,
                    prepayment_amount="1 000 ₽",
                )
            )
            await session.commit()
        elif not existing.prepayment_amount:
            existing.prepayment_amount = "1 000 ₽"
            await session.commit()

    return conflicts
