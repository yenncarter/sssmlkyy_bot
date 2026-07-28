"""Print bot clock + DB integrity snapshot."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text

from config.settings import reload_settings
from db.models import Booking, Slot, WorkingDay, WorkSettings
from db.session import create_engine, create_session_factory, init_db
from domain.dates import LOCAL_TZ, format_date_short, now_local, today
from domain.parsing import parse_day
from services.schedule_service import ScheduleService


async def main() -> None:
    now = now_local()
    print("=== BOT CLOCK ===")
    print(f"timezone: {LOCAL_TZ}  (= phone / Moscow)")
    print(f"now:      {now.strftime('%d.%m.%Y %H:%M:%S')} (UTC{now.strftime('%z')})")
    print(f"today:    {format_date_short(today())}")
    print(f"utc:      {datetime.now(ZoneInfo('UTC')).strftime('%H:%M:%S')}")

    # year resolve demo
    d = parse_day("01.10")
    print(f"parse 01.10 -> {format_date_short(d)}")

    settings = reload_settings()
    engine = create_engine(settings.database_url)
    await init_db(engine)
    sf = create_session_factory(engine)
    schedule = ScheduleService(sf, settings)

    async with sf() as session:
        async with engine.connect() as conn:
            fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
            jm = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        ws = await session.get(WorkSettings, 1)
        days_n = await session.scalar(select(func.count()).select_from(WorkingDay))
        slots_n = await session.scalar(select(func.count()).select_from(Slot))
        books_n = await session.scalar(select(func.count()).select_from(Booking))
        orphan = await session.scalar(
            text(
                "SELECT COUNT(*) FROM slots s "
                "LEFT JOIN working_days w ON w.id = s.working_day_id "
                "WHERE w.id IS NULL"
            )
        )
        past_n = await session.scalar(
            select(func.count())
            .select_from(WorkingDay)
            .where(WorkingDay.day < today())
        )
        print("\n=== DB ===")
        print(f"url: {settings.database_url}")
        print(f"foreign_keys={fk} journal={jm}")
        print(
            f"settings: {ws.open_time}-{ws.close_time} / "
            f"{ws.slot_minutes} / {ws.prepayment_amount}"
        )
        print(f"days={days_n} slots={slots_n} bookings={books_n}")
        print(f"orphan_slots={orphan} past_days={past_n}")

    purged = await schedule.purge_past_days()
    print(f"purge_past_days={purged} (дни с историей записей не удаляются)")

    print("\n=== CONFIG ===")
    print(f"bot_id: {settings.bot_token.split(':')[0]}")
    print(f"admins: {list(settings.admin_telegram_ids)} (primary={settings.primary_admin_id})")
    print(f"channel: {settings.channel_link}")
    print(f"master: @{settings.master_username} {settings.master_phone}")
    print(f"welcome: {settings.welcome_image.exists()}")
    print(f"payment: {bool(settings.payment_link)}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
