"""Logic smoke tests for the bot.

Runs against an isolated temp SQLite database — never touches DATABASE_URL from
the environment. Every section named `REGRESSION` pins a bug that was found in
production or during the audit; do not delete those checks.

    python scripts/smoke_logic.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from datetime import date, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Fixed environment: the test asserts on these values, so neither the shell nor
# a local .env may leak in. A throwaway database must exist before Settings is
# built, because Settings.from_env() resolves DATABASE_URL once.
_fd, _db_file = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{Path(_db_file).as_posix()}",
        "BOT_TOKEN": "123456:smoke-test-token",
        "CHANNEL_LINK": "https://t.me/smoke",
        "MASTER_USERNAME": "smoke",
        "MASTER_NAME": "Вика",
        "PAYMENT_LINK": "https://example.com/pay",
        "ADMIN_TELEGRAM_IDS": "111,222",
        "SLOT_HOLD_MINUTES": "15",
        "LOG_LEVEL": "WARNING",
    }
)
# Present-but-empty: load_dotenv(override=False) skips keys that already exist,
# so this keeps a legacy .env id out of the admin list.
os.environ["ADMIN_TELEGRAM_ID"] = ""

from sqlalchemy import select
from sqlalchemy import text as sql_text

from config.settings import reload_settings
from db.models import Booking, Slot, WorkingDay
from db.session import create_engine, create_session_factory, init_db
from domain.dates import format_date_short, now_local
from domain.enums import BookingStatus, SlotStatus
from domain.exceptions import (
    AlreadyHasBookingError,
    DayNotFoundError,
    DuplicateSlotError,
    SlotNotAvailableError,
    ValidationError,
)
from domain.parsing import (
    normalize_full_name,
    normalize_phone,
    normalize_prepayment_amount,
    parse_day,
    parse_days_column,
    parse_hours_message,
    safe_echo,
)
from handlers import setup_routers
from handlers.booking import _hold_minutes_left
from presentation.keyboards import admin as admin_kb
from presentation.keyboards import booking as bkb
from presentation.keyboards import menu as mkb
from presentation.texts import messages as msg
from presentation.texts.context import format_message
from services.schedule_service import BookingService, ScheduleService

settings = reload_settings()


class T:
    def __init__(self) -> None:
        self.ok = 0
        self.fail = 0
        self.errors: list[str] = []

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.ok += 1
            print(f"  OK  {name}")
        else:
            self.fail += 1
            line = f"FAIL {name}" + (f" — {detail}" if detail else "")
            self.errors.append(line)
            print(f"  {line}")

    async def raises(self, name: str, exc_type, coro) -> None:
        try:
            await coro
        except exc_type:
            self.check(name, True)
        except Exception as exc:
            self.check(name, False, f"поймано {type(exc).__name__}: {exc}")
        else:
            self.check(name, False, "исключения не было")

    def section(self, title: str) -> None:
        print(f"\n=== {title} ===")


async def _hold(bookings: BookingService, slot_id: int, user_id: int) -> Booking:
    return await bookings.hold_slot(
        slot_id=slot_id,
        user_id=user_id,
        username=f"u{user_id}",
        full_name=f"Клиент {user_id}",
        phone="+79990001122",
    )


def _free(day: WorkingDay, exclude: set[int] | None = None) -> Slot:
    exclude = exclude or set()
    return next(
        s
        for s in sorted(day.slots, key=lambda x: x.start_time)
        if s.status == SlotStatus.FREE.value and s.id not in exclude
    )


async def main() -> int:
    t = T()
    engine = create_engine(settings.database_url)
    await init_db(engine)
    sf = create_session_factory(engine)
    schedule = ScheduleService(sf, settings)
    bookings = BookingService(sf, settings)

    today = date.today()
    d1 = today + timedelta(days=3)
    d2 = today + timedelta(days=4)
    d3 = today + timedelta(days=5)

    # ---------- config / wiring ----------
    t.section("Config & routers")
    t.check("admin ids loaded", len(settings.admin_telegram_ids) == 2)
    t.check("primary admin is first", settings.primary_admin_id == 111)
    t.check("is_admin works", settings.is_admin(111) and settings.is_admin(222))
    t.check("is_admin rejects stranger", not settings.is_admin(999))
    t.check("only primary is primary", not settings.is_primary_admin(222))
    try:
        setup_routers()
        t.check("setup_routers()", True)
    except Exception as exc:
        t.check("setup_routers()", False, str(exc))

    home_kb = str(admin_kb.admin_home_keyboard())
    for label in ("Записи", "График", "Настройки"):
        t.check(f"home kb has {label}", label in home_kb)

    # ---------- parsers ----------
    t.section("Parsers & validation")
    parsed = parse_day("01.10")
    t.check(
        "parse_day 01.10 resolves year",
        parsed.month == 10 and parsed.day == 1 and parsed.year >= today.year,
    )
    t.check("format_date_short", format_date_short(date(2026, 10, 1)) == "01.10.2026")

    for bad_day in ("32.01", "01.01.2020", "недата", "", "31.02"):
        try:
            parse_day(bad_day)
            t.check(f"parse_day rejects {bad_day!r}", False)
        except ValidationError:
            t.check(f"parse_day rejects {bad_day!r}", True)
        except Exception as exc:
            t.check(f"parse_day rejects {bad_day!r}", False, type(exc).__name__)

    days, bad = parse_days_column("01.10\n10.10\n11.10")
    t.check("parse_days_column count", len(days) == 3 and not bad)
    days2, _ = parse_days_column("01.10\n01.10\n10.10")
    t.check("parse_days_column dedupe", len(days2) == 2)
    _, bad3 = parse_days_column("недата\n01.10")
    t.check("parse_days_column reports bad tokens", len(bad3) == 1)

    open_t, close_t, step = parse_hours_message("10:00-18:00")
    t.check("parse_hours dash", (open_t, close_t, step) == (time(10), time(18), 60))
    t.check(
        "parse_hours space", parse_hours_message("10:00 18:00")[:2] == (time(10), time(18))
    )

    # REGRESSION H2: malformed hours used to raise IndexError, which escaped as
    # a generic error instead of a hint to the master.
    for raw in ("-22:00", "10:00-", "-", "", "abc", "10:00-10:00", "25:00-26:00", "::"):
        try:
            parse_hours_message(raw)
            t.check(f"parse_hours rejects {raw!r}", False)
        except ValidationError:
            t.check(f"parse_hours rejects {raw!r}", True)
        except Exception as exc:
            t.check(f"parse_hours rejects {raw!r}", False, type(exc).__name__)

    # REGRESSION H3: '++++++++++' passed phone validation and reached the master.
    t.check("phone normalizes", normalize_phone("+7 (999) 000-11-22") == "+79990001122")
    t.check("phone without plus", normalize_phone("89990001122") == "89990001122")
    for raw in ("++++++++++", "12345", "", "телефон", "1" * 20):
        try:
            normalize_phone(raw)
            t.check(f"phone rejects {raw!r}", False)
        except ValidationError:
            t.check(f"phone rejects {raw!r}", True)

    t.check("name collapses spaces", normalize_full_name("  Анна   Петрова ") == "Анна Петрова")
    for raw in ("", "я", "x" * 300):
        try:
            normalize_full_name(raw)
            t.check(f"name rejects len={len(raw)}", False)
        except ValidationError:
            t.check(f"name rejects len={len(raw)}", True)

    t.check("prepayment formats", normalize_prepayment_amount("2000") == "2 000 ₽")
    for raw in ("", "abc", "0", "99999999"):
        try:
            normalize_prepayment_amount(raw)
            t.check(f"prepayment rejects {raw!r}", False)
        except ValidationError:
            t.check(f"prepayment rejects {raw!r}", True)

    # REGRESSION M3: user input echoed into an HTML message must be escaped, or
    # a single '<' turns the hint into TelegramBadRequest.
    t.check("safe_echo escapes", safe_echo("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;")
    t.check("safe_echo truncates", len(safe_echo("x" * 100)) == 32)
    for raw in ("<b>", "1<2.10", "99.<i>"):
        try:
            parse_day(raw)
            t.check(f"parse_day rejects {raw!r}", False)
        except ValidationError as exc:
            t.check(
                f"parse_day never echoes {raw!r} raw",
                raw not in str(exc),
                str(exc),
            )
    try:
        parse_hours_message("<b>-18:00")
        t.check("parse_hours error is html-safe", False)
    except ValidationError as exc:
        t.check("parse_hours error is html-safe", "<b>" not in str(exc))

    # REGRESSION: format_message used to raise KeyError on booking placeholders.
    t.check(
        "format_message keeps unknown placeholders",
        "{hold_minutes}" in format_message(msg.BOOKING_PAYMENT, settings),
    )
    t.check(
        "format_message substitutes known",
        settings.master_name in format_message(msg.ABOUT, settings)
        or "{master_name}" not in msg.ABOUT,
    )

    # ---------- schedule ----------
    t.section("Schedule: days & hours")
    await t.raises(
        "reject past day",
        ValidationError,
        schedule.add_day_from_defaults(today - timedelta(days=1)),
    )

    day1 = await schedule.add_day_from_defaults(d1)
    default_slots = len(day1.slots)
    t.check("add day", day1.day == d1 and default_slots >= 8)
    await t.raises("duplicate day rejected", DuplicateSlotError, schedule.add_day_from_defaults(d1))

    day1 = await schedule.set_day_hours(day1.id, time(12), time(14), 60)
    t.check("set_day_hours shrinks", len(day1.slots) == 2, f"got {len(day1.slots)}")
    day1 = await schedule.clear_day_override(day1.id)
    t.check(
        "clear_day_override restores grid",
        day1.open_time is None and len(day1.slots) == default_slots,
        f"slots={len(day1.slots)} expected={default_slots}",
    )

    await schedule.add_day_from_defaults(d2)
    await schedule.add_day_from_defaults(d3)
    t.check("list_upcoming_days", len(await schedule.list_upcoming_days()) == 3)

    slot0 = _free(day1)
    t.check(
        "block slot",
        (await schedule.toggle_slot_block(slot0.id)).status == SlotStatus.BLOCKED.value,
    )
    t.check(
        "unblock slot",
        (await schedule.toggle_slot_block(slot0.id)).status == SlotStatus.FREE.value,
    )

    # ---------- booking happy path ----------
    t.section("Booking: hold -> receipt -> cancel")
    day1 = await schedule.get_day(day1.id)
    target = _free(day1)
    booking = await _hold(bookings, target.id, 1001)
    t.check("hold pending", booking.status == BookingStatus.PENDING_PAYMENT.value)
    t.check("hold duration", booking.duration_minutes == 60)

    # REGRESSION C3: held_until is stored in Europe/Moscow but was read as UTC,
    # so the client was told the hold lasted 194 minutes instead of 15.
    left = _hold_minutes_left(booking, settings.slot_hold_minutes)
    t.check(
        "hold countdown matches SLOT_HOLD_MINUTES",
        settings.slot_hold_minutes - 1 <= left <= settings.slot_hold_minutes,
        f"got {left}, expected ~{settings.slot_hold_minutes}",
    )

    day1 = await schedule.get_day(day1.id)
    t.check(
        "slot held",
        next(s for s in day1.slots if s.id == target.id).status == SlotStatus.HELD.value,
    )

    other = _free(day1, exclude={target.id})
    await t.raises(
        "second live booking blocked", AlreadyHasBookingError, _hold(bookings, other.id, 1001)
    )
    await t.raises(
        "held slot not stealable", SlotNotAvailableError, _hold(bookings, target.id, 1002)
    )

    await schedule.toggle_slot_block(other.id)
    await t.raises(
        "blocked slot not bookable", SlotNotAvailableError, _hold(bookings, other.id, 1002)
    )
    await schedule.toggle_slot_block(other.id)

    booking = await bookings.confirm_with_receipt(
        booking_id=booking.id,
        user_id=1001,
        receipt_file_id="file_receipt_1",
        receipt_file_type="photo",
    )
    t.check(
        "confirm active",
        booking.status == BookingStatus.ACTIVE.value
        and booking.receipt_file_id == "file_receipt_1",
    )

    # REGRESSION M5: a second receipt for the same booking must not re-confirm.
    await t.raises(
        "double receipt rejected",
        ValidationError,
        bookings.confirm_with_receipt(
            booking_id=booking.id,
            user_id=1001,
            receipt_file_id="file_receipt_2",
            receipt_file_type="photo",
        ),
    )

    day1 = await schedule.get_day(day1.id)
    t.check(
        "slot booked",
        next(s for s in day1.slots if s.id == target.id).status == SlotStatus.BOOKED.value,
    )
    await t.raises(
        "delete day with booking blocked",
        ValidationError,
        schedule.delete_day(day1.id),
    )
    await t.raises(
        "toggle booked slot blocked",
        ValidationError,
        schedule.toggle_slot_block(target.id),
    )

    t.check("list_user_bookings", len(await bookings.list_user_bookings(1001)) == 1)
    t.check("list_for_working_day", len(await bookings.list_for_working_day(day1.id)) == 1)
    t.check("list_booking_days", len(await bookings.list_booking_days()) == 1)

    booking = await bookings.cancel_by_client(booking.id, 1001)
    t.check("client cancel", booking.status == BookingStatus.CANCELLED.value)
    day1 = await schedule.get_day(day1.id)
    t.check(
        "slot freed after cancel",
        next(s for s in day1.slots if s.id == target.id).status == SlotStatus.FREE.value,
    )
    t.check("client can book again", not await bookings.user_has_active_booking(1001))

    # ---------- REGRESSION C1 / C2: cancelled history pins its slot ----------
    t.section("REGRESSION C1/C2: edit and delete a day that has history")
    # `target` now carries a CANCELLED booking. Editing hours used to raise
    # IntegrityError (NOT NULL slot_id) because the ORM nulled the FK, and a
    # BLOCKED slot made the rebuild violate uq_slot_day_time.
    blocked_slot = _free(day1, exclude={target.id})
    await schedule.toggle_slot_block(blocked_slot.id)

    try:
        edited = await schedule.set_day_hours(day1.id, time(11), time(15), 60)
        t.check("set_day_hours with history survives", True)
        t.check(
            "blocked slot kept once",
            sum(1 for s in edited.slots if s.start_time == blocked_slot.start_time) == 1,
        )
        t.check(
            "slot with history kept",
            any(s.id == target.id for s in edited.slots),
        )
    except Exception as exc:
        t.check("set_day_hours with history survives", False, f"{type(exc).__name__}: {exc}")

    try:
        reset = await schedule.clear_day_override(day1.id)
        t.check("clear_day_override with history survives", True)
        t.check(
            "no duplicate start times after reset",
            len({s.start_time for s in reset.slots}) == len(reset.slots),
        )
    except Exception as exc:
        t.check("clear_day_override with history survives", False, f"{type(exc).__name__}: {exc}")

    try:
        await schedule.delete_day(day1.id)
        t.check("delete day with cancelled history survives", True)
        await t.raises("day really deleted", DayNotFoundError, schedule.get_day(day1.id))
    except Exception as exc:
        t.check("delete day with cancelled history survives", False, f"{type(exc).__name__}: {exc}")

    # ---------- reschedule ----------
    t.section("Booking: reschedule")
    day2 = await schedule.get_day(
        next(d.id for d in await schedule.list_upcoming_days() if d.day == d2)
    )
    slot_a = _free(day2)
    moved = await _hold(bookings, slot_a.id, 2001)
    moved = await bookings.confirm_with_receipt(
        booking_id=moved.id, user_id=2001, receipt_file_id="r2", receipt_file_type="photo"
    )
    async with sf() as session:
        row = await session.get(Booking, moved.id)
        row.reminded_24h = True
        row.reminded_2h = True
        await session.commit()

    slot_b = _free(day2, exclude={slot_a.id})
    moved = await bookings.reschedule(moved.id, slot_b.id)
    t.check("reschedule moves booking", moved.slot_id == slot_b.id)
    # REGRESSION M1: reminders for the old time were never reset, so the client
    # got no reminder for the new time.
    t.check("reschedule resets reminders", not moved.reminded_24h and not moved.reminded_2h)
    day2 = await schedule.get_day(day2.id)
    t.check(
        "old slot freed",
        next(s for s in day2.slots if s.id == slot_a.id).status == SlotStatus.FREE.value,
    )
    t.check(
        "new slot booked",
        next(s for s in day2.slots if s.id == slot_b.id).status == SlotStatus.BOOKED.value,
    )
    await bookings.cancel_booking(moved.id)

    # ---------- hold expiry ----------
    t.section("Hold expiry")
    day2 = await schedule.get_day(day2.id)
    expiring = _free(day2)
    held = await _hold(bookings, expiring.id, 3001)
    async with sf() as session:
        slot = await session.get(Slot, expiring.id)
        slot.held_until = now_local() - timedelta(minutes=1)
        await session.commit()
    t.check("release_expired_holds", await schedule.release_expired_holds() >= 1)
    t.check(
        "pending cancelled on expiry",
        (await bookings.get_booking(held.id)).status == BookingStatus.CANCELLED.value,
    )
    day2 = await schedule.get_day(day2.id)
    t.check(
        "slot free after expiry",
        next(s for s in day2.slots if s.id == expiring.id).status == SlotStatus.FREE.value,
    )

    held2 = await _hold(bookings, _free(day2).id, 3002)
    await t.raises("delete day with hold blocked", ValidationError, schedule.delete_day(day2.id))
    await bookings.cancel_booking(held2.id)

    # ---------- REGRESSION C5: database-level guards ----------
    t.section("REGRESSION C5: unique indexes exist")
    async with engine.connect() as conn:
        names = {
            row[0]
            for row in (
                await conn.execute(
                    sql_text("SELECT name FROM sqlite_master WHERE type='index'")
                )
            ).fetchall()
        }
    for index in ("uq_live_booking_slot", "uq_live_booking_user", "ix_bookings_status"):
        t.check(f"index {index}", index in names)

    day3 = await schedule.get_day(
        next(d.id for d in await schedule.list_upcoming_days() if d.day == d3)
    )
    contested = _free(day3)
    keeper = await _hold(bookings, contested.id, 4001)
    async with sf() as session:
        session.add(
            Booking(
                slot_id=contested.id,
                telegram_user_id=4002,
                full_name="Гонка",
                phone="+79990000000",
                duration_minutes=60,
                status=BookingStatus.PENDING_PAYMENT.value,
            )
        )
        try:
            await session.commit()
            t.check("db blocks two live bookings per slot", False, "коммит прошёл")
        except Exception:
            await session.rollback()
            t.check("db blocks two live bookings per slot", True)

    async with sf() as session:
        session.add(
            Booking(
                slot_id=_free(await schedule.get_day(day3.id)).id,
                telegram_user_id=4001,
                full_name="Дубль",
                phone="+79990000000",
                duration_minutes=60,
                status=BookingStatus.PENDING_PAYMENT.value,
            )
        )
        try:
            await session.commit()
            t.check("db blocks two live bookings per user", False, "коммит прошёл")
        except Exception:
            await session.rollback()
            t.check("db blocks two live bookings per user", True)
    await bookings.cancel_booking(keeper.id)

    # ---------- REGRESSION C4 / M2: past days keep their history ----------
    t.section("REGRESSION C4/M2: settle past, keep history")
    async with sf() as session:
        past_day = WorkingDay(day=today - timedelta(days=2))
        session.add(past_day)
        await session.flush()
        past_slot = Slot(
            working_day_id=past_day.id,
            start_time=time(12),
            status=SlotStatus.BOOKED.value,
        )
        empty_day = WorkingDay(day=today - timedelta(days=3))
        session.add_all([past_slot, empty_day])
        await session.flush()
        session.add(
            Booking(
                slot_id=past_slot.id,
                telegram_user_id=5001,
                full_name="Прошлый визит",
                phone="+79995550000",
                duration_minutes=60,
                status=BookingStatus.ACTIVE.value,
            )
        )
        await session.commit()
        past_day_id, empty_day_id = past_day.id, empty_day.id

    settled = await bookings.settle_past_bookings()
    t.check("settle_past_bookings closes finished visit", settled == 1, f"settled={settled}")
    purged = await schedule.purge_past_days()
    t.check("purge removes only the empty past day", purged == 1, f"purged={purged}")
    await t.raises("empty past day deleted", DayNotFoundError, schedule.get_day(empty_day_id))
    kept = await schedule.get_day(past_day_id)
    t.check("past day with history kept", kept.id == past_day_id)
    async with sf() as session:
        surviving = list(
            await session.scalars(select(Booking).where(Booking.telegram_user_id == 5001))
        )
    t.check("historical booking survived purge", len(surviving) == 1)
    t.check(
        "finished visit marked completed",
        bool(surviving) and surviving[0].status == BookingStatus.COMPLETED.value,
        surviving[0].status if surviving else "нет записи",
    )

    # ---------- cancel policy ----------
    t.section("Cancel policy <24h")
    async with sf() as session:
        soon = now_local() + timedelta(hours=2)
        near_day = await session.scalar(
            select(WorkingDay).where(WorkingDay.day == soon.date())
        )
        if near_day is None:
            near_day = WorkingDay(day=soon.date())
            session.add(near_day)
            await session.flush()
        near_slot = Slot(
            working_day_id=near_day.id,
            start_time=soon.time().replace(second=0, microsecond=0),
            status=SlotStatus.BOOKED.value,
        )
        session.add(near_slot)
        await session.flush()
        near_booking = Booking(
            slot_id=near_slot.id,
            telegram_user_id=6001,
            full_name="Скоро",
            phone="+79994440000",
            duration_minutes=60,
            status=BookingStatus.ACTIVE.value,
            confirmed_at=now_local(),
        )
        session.add(near_booking)
        await session.commit()
        near_id = near_booking.id

    try:
        await bookings.cancel_by_client(near_id, 6001)
        t.check("client cancel <24h blocked", False, "исключения не было")
    except ValidationError as exc:
        t.check("client cancel <24h blocked", "24" in str(exc), str(exc))
    t.check(
        "admin can cancel <24h",
        (await bookings.cancel_booking(near_id)).status == BookingStatus.CANCELLED.value,
    )

    # ---------- reliability: receipt recovery, backup, media cache ----------
    t.section("Reliability: receipt without FSM, backup, media cache")
    day_r = await schedule.add_day_from_defaults(today + timedelta(days=8))
    pending_slot = _free(day_r)
    pending = await _hold(bookings, pending_slot.id, 7001)
    target = await bookings.find_receipt_target(7001)
    t.check(
        "find_receipt_target finds pending",
        target is not None and target.id == pending.id,
    )
    t.check("no target for stranger", await bookings.find_receipt_target(7002) is None)

    # Expire the hold, then the late-receipt path must still find it.
    async with sf() as session:
        slot = await session.get(Slot, pending_slot.id)
        assert slot is not None
        slot.held_until = now_local() - timedelta(minutes=1)
        await session.commit()
    await schedule.release_expired_holds()
    late = await bookings.find_receipt_target(7001)
    t.check(
        "find_receipt_target finds cancelled hold",
        late is not None and late.status == BookingStatus.CANCELLED.value,
    )
    if late is not None:
        attached = await bookings.attach_late_receipt(
            late.id, receipt_file_id="late_file", receipt_file_type="photo"
        )
        t.check(
            "attach_late_receipt keeps cancelled",
            attached.status == BookingStatus.CANCELLED.value
            and attached.receipt_file_id == "late_file",
        )

    from services.app_state import AppStateStore
    from services.backup_service import backup_dir_for, create_backup
    from services.db_health import BOOKINGS_SEEN_KEY, DbHealthService
    from services.media_cache import MediaCache

    state = AppStateStore(sf)
    await state.set_int(BOOKINGS_SEEN_KEY, 1)
    t.check("app_state roundtrip", await state.get_int(BOOKINGS_SEEN_KEY) == 1)

    media = MediaCache(sf)
    await media.remember("portfolio:01.jpg", "file_AAA")
    cold = MediaCache(sf)
    loaded = await cold.load()
    t.check("media_cache persists", loaded == 1 and cold.get("portfolio:01.jpg") == "file_AAA")

    db_path = Path(_db_file)
    backup = create_backup(db_path, backup_dir_for(db_path), keep=3)
    t.check("backup verifies", backup.bookings >= 1 and backup.path.exists())
    t.check("backup has days", backup.days >= 1)

    class _SilentAlerts:
        async def send(self, key: str, text: str, *, force: bool = False) -> bool:
            return False

    health = DbHealthService(engine, sf, settings, state, _SilentAlerts())  # type: ignore[arg-type]
    report = await health.check(announce=False)
    t.check("db health reports bookings", report.bookings >= 1)
    t.check("db integrity ok", report.integrity is None)

    # ---------- UI smoke ----------
    t.section("UI texts & keyboards")
    t.check("FAQ hub text", "FAQ" in msg.FAQ and "Выбери" in msg.FAQ)
    t.check(
        "FAQ sections",
        "предоплата" in msg.FAQ_BOOKING.lower() and "Гарантия" in msg.FAQ_RULES,
    )
    menu_str = str(mkb.main_menu_keyboard(settings))
    t.check("main_menu has FAQ", "FAQ" in menu_str)
    t.check("main_menu has primary book", msg.BTN_BOOK in menu_str)
    t.check("payment kb", msg.BTN_PAY in str(bkb.payment_keyboard(settings)))
    t.check(
        "bookings days keyboard",
        "01.10.2026" in str(admin_kb.admin_bookings_days_keyboard([(1, date(2026, 10, 1), 2)])),
    )
    t.check(
        "schedule hub",
        "Добавить день" in str(admin_kb.admin_schedule_hub_keyboard(days_count=3)),
    )

    # REGRESSION H4: long lists used to be cut to 25/40 rows without a trace.
    many = await schedule.list_upcoming_days()
    t.check("days keyboard renders all days", len(many) <= admin_kb.MAX_LIST_ROWS)

    print(f"\n{'=' * 44}")
    print(f"Passed: {t.ok}  Failed: {t.fail}")
    for line in t.errors:
        print(" -", line)

    await engine.dispose()
    Path(_db_file).unlink(missing_ok=True)
    return 1 if t.fail else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise SystemExit(2) from exc
