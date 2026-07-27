"""One-shot: wipe bookings + working days (slots cascade). Keep work_settings."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, func, select, text

from config.settings import reload_settings
from db.models import Booking, Slot, WorkSettings, WorkingDay
from db.session import create_engine, create_session_factory


async def main() -> None:
    settings = reload_settings()
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
