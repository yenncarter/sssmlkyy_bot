"""Restore local SQLite dump into a target DATABASE_URL (Postgres or SQLite).

Usage:
  set DATABASE_URL=postgresql+asyncpg://...
  python scripts/restore_sqlite_to_target.py

Source defaults to newest data/backups/bot_consistent_*.db
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from datetime import date, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select

from db.models import Booking, Slot, WorkingDay, WorkSettings
from db.session import create_engine, create_session_factory, init_db


def _latest_backup() -> Path:
    backups = sorted((ROOT / "data" / "backups").glob("bot_consistent_*.db"), reverse=True)
    if backups:
        return backups[0]
    live = ROOT / "data" / "bot.db"
    if live.exists():
        return live
    raise SystemExit("No SQLite backup found")


def _parse_time(v: str | None) -> time | None:
    if not v:
        return None
    s = str(v).split(".")[0]
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    s = str(v).replace("T", " ").split(".")[0]
    return datetime.fromisoformat(s)


def _load_sqlite(path: Path) -> dict:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    data = {
        "work_settings": [dict(r) for r in con.execute("SELECT * FROM work_settings")],
        "working_days": [dict(r) for r in con.execute("SELECT * FROM working_days ORDER BY id")],
        "slots": [dict(r) for r in con.execute("SELECT * FROM slots ORDER BY id")],
        "bookings": [dict(r) for r in con.execute("SELECT * FROM bookings ORDER BY id")],
    }
    con.close()
    return data


async def restore(target_url: str, source: Path) -> None:
    dump = _load_sqlite(source)
    print(f"source={source}")
    print(
        f"rows days={len(dump['working_days'])} "
        f"slots={len(dump['slots'])} bookings={len(dump['bookings'])}"
    )
    print(f"target={target_url.split('://')[0]}://…")

    if target_url.startswith("postgres://"):
        target_url = target_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif target_url.startswith("postgresql://"):
        target_url = target_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_engine(target_url)
    await init_db(engine)
    sf = create_session_factory(engine)

    async with sf() as session:
        # Wipe schedule tables, keep structure
        await session.execute(delete(Booking))
        await session.execute(delete(Slot))
        await session.execute(delete(WorkingDay))
        await session.commit()

    id_day: dict[int, int] = {}
    id_slot: dict[int, int] = {}

    async with sf() as session:
        for ws in dump["work_settings"]:
            existing = await session.get(WorkSettings, 1)
            if existing is None:
                session.add(
                    WorkSettings(
                        id=1,
                        open_time=_parse_time(ws["open_time"]) or time(10, 0),
                        close_time=_parse_time(ws["close_time"]) or time(22, 0),
                        slot_minutes=int(ws["slot_minutes"] or 60),
                        prepayment_amount=ws.get("prepayment_amount") or "500 ₽",
                    )
                )
            else:
                existing.open_time = _parse_time(ws["open_time"]) or existing.open_time
                existing.close_time = _parse_time(ws["close_time"]) or existing.close_time
                existing.slot_minutes = int(ws["slot_minutes"] or existing.slot_minutes)
                if ws.get("prepayment_amount"):
                    existing.prepayment_amount = ws["prepayment_amount"]
        await session.commit()

        for d in dump["working_days"]:
            old_id = int(d["id"])
            day = WorkingDay(
                day=date.fromisoformat(str(d["day"])),
                open_time=_parse_time(d.get("open_time")),
                close_time=_parse_time(d.get("close_time")),
                slot_minutes=d.get("slot_minutes"),
            )
            session.add(day)
            await session.flush()
            id_day[old_id] = day.id
        await session.commit()

        for s in dump["slots"]:
            old_id = int(s["id"])
            wd_old = int(s["working_day_id"])
            slot = Slot(
                working_day_id=id_day[wd_old],
                start_time=_parse_time(s["start_time"]),
                status=s["status"],
                held_by_user_id=s.get("held_by_user_id"),
                held_until=_parse_dt(s.get("held_until")),
            )
            session.add(slot)
            await session.flush()
            id_slot[old_id] = slot.id
        await session.commit()

        for b in dump["bookings"]:
            booking = Booking(
                slot_id=id_slot[int(b["slot_id"])],
                telegram_user_id=int(b["telegram_user_id"]),
                username=b.get("username"),
                full_name=b["full_name"],
                phone=b["phone"],
                service_code=b.get("service_code"),
                service_title=b.get("service_title"),
                duration_minutes=b.get("duration_minutes"),
                status=b["status"],
                receipt_file_id=b.get("receipt_file_id"),
                receipt_file_type=b.get("receipt_file_type"),
                created_at=_parse_dt(b.get("created_at")) or datetime.utcnow(),
                confirmed_at=_parse_dt(b.get("confirmed_at")),
                cancelled_at=_parse_dt(b.get("cancelled_at")),
                reminded_24h=bool(b.get("reminded_24h") or 0),
                reminded_2h=bool(b.get("reminded_2h") or 0),
            )
            session.add(booking)
        await session.commit()

        days_n = (await session.execute(select(WorkingDay))).scalars().all()
        books = (await session.execute(select(Booking))).scalars().all()
        active = [x for x in books if x.status == "active"]
        print(f"restored days={len(days_n)} bookings={len(books)} active={len(active)}")

    await engine.dispose()


async def main() -> None:
    target = (os.getenv("RESTORE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not target:
        raise SystemExit(
            "Set RESTORE_DATABASE_URL (prod) or DATABASE_URL.\n"
            "Example: RESTORE_DATABASE_URL=postgresql://... "
            "python scripts/restore_sqlite_to_target.py"
        )
    # Safety: refuse overwriting local live db unless forced
    if "bot.db" in target and os.getenv("ALLOW_LOCAL_OVERWRITE") != "1":
        print("Refusing to wipe local bot.db without ALLOW_LOCAL_OVERWRITE=1")
        raise SystemExit(2)
    await restore(target, _latest_backup())


if __name__ == "__main__":
    asyncio.run(main())
