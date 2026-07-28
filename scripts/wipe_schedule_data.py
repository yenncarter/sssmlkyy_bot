"""Destructive: wipe bookings + working days (slots cascade). Keeps work_settings.

Deletes the salon's entire history, so it refuses to run without:
  1. an explicit confirmation flag;
  2. an explicit --db=path that must match the configured DATABASE_URL.

Take a backup first: scripts/backup_and_dump_sqlite.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, func, select, text

from config.settings import reload_settings
from db.models import Booking, Slot, WorkingDay, WorkSettings
from db.session import create_engine, create_session_factory

CONFIRM_FLAG = "--yes-delete-everything"


def _db_arg() -> Path | None:
    for arg in sys.argv[1:]:
        if arg.startswith("--db="):
            return Path(arg.removeprefix("--db=")).expanduser().resolve()
    return None


async def main() -> None:
    db_path = _db_arg()
    if CONFIRM_FLAG not in sys.argv or db_path is None:
        print(
            "Этот скрипт удаляет ВСЕ записи и дни графика без возможности отката.\n"
            "Сначала сделай бэкап: python scripts/backup_and_dump_sqlite.py\n"
            "Затем запусти с явным путём к файлу БД:\n"
            f"  python scripts/wipe_schedule_data.py {CONFIRM_FLAG} "
            "--db=C:/path/to/bot.db"
        )
        raise SystemExit(1)

    settings = reload_settings()
    configured = settings.sqlite_path
    if configured is None:
        print("wipe работает только с SQLite. Сейчас DATABASE_URL — не sqlite.")
        raise SystemExit(1)
    if configured.resolve() != db_path:
        print(
            "Путь --db не совпадает с DATABASE_URL — отказ.\n"
            f"  --db={db_path}\n"
            f"  DATABASE_URL → {configured.resolve()}\n"
            "Так нельзя случайно стереть прод, указывая другой файл."
        )
        raise SystemExit(1)

    print(f"Целевая БД: {settings.database_url}")
    print(f"Файл: {db_path}")
    engine = create_engine(settings.database_url)
    sf = create_session_factory(engine)
    async with sf() as session:
        b_before = await session.scalar(select(func.count()).select_from(Booking))
        d_before = await session.scalar(select(func.count()).select_from(WorkingDay))
        s_before = await session.scalar(select(func.count()).select_from(Slot))

        await session.execute(delete(Booking))
        await session.execute(delete(Slot))
        await session.execute(delete(WorkingDay))
        await session.commit()

        if "sqlite" in settings.database_url:
            try:
                await session.execute(
                    text(
                        "DELETE FROM sqlite_sequence "
                        "WHERE name IN ('bookings', 'working_days', 'slots')"
                    )
                )
                await session.commit()
            except Exception:
                await session.rollback()

        b = await session.scalar(select(func.count()).select_from(Booking))
        d = await session.scalar(select(func.count()).select_from(WorkingDay))
        sl = await session.scalar(select(func.count()).select_from(Slot))
        ws = await session.get(WorkSettings, 1)

        print("=== CLEARED ===")
        print(f"removed bookings={b_before} days={d_before} slots={s_before}")
        print(f"now bookings={b} days={d} slots={sl}")
        if ws:
            print(
                "settings kept:",
                ws.open_time,
                "-",
                ws.close_time,
                f"step={ws.slot_minutes}",
                ws.prepayment_amount,
            )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
