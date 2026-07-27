"""Extensive logic smoke tests for Beauty SZN bot.

Uses an isolated temp SQLite DB — never touches the real DATABASE_URL.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from datetime import date, datetime, timedelta, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from config.settings import reload_settings
from db.models import Booking, BookingStatus, Slot, SlotStatus, WorkingDay
from db.session import create_engine, create_session_factory, init_db
from domain.dates import format_date_short
from domain.exceptions import (
    AlreadyHasBookingError,
    DuplicateSlotError,
    SlotNotAvailableError,
    ValidationError,
)
from handlers import setup_routers
from presentation.keyboards import admin as admin_kb
from presentation.keyboards import booking as bkb
from presentation.keyboards import menu as mkb
from presentation.texts import messages as msg
from services.schedule_service import (
    BookingService,
    ScheduleService,
    parse_day,
    parse_days_column,
    parse_hours_message,
)

# settings.py load_dotenv(override=True) — set throwaway DB *after* that import.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_tmp.name).as_posix()}"
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
            msg_ = f"FAIL {name}" + (f" — {detail}" if detail else "")
            self.errors.append(msg_)
            print(f"  {msg_}")

    def section(self, title: str) -> None:
        print(f"\n=== {title} ===")


async def _day_by_date(schedule: ScheduleService, d: date) -> WorkingDay | None:
    days = await schedule.list_upcoming_days(limit=120)
    for day in days:
        if day.day == d:
            return day
    return None


async def main() -> int:
    t = T()
    engine = create_engine(settings.database_url)
    await init_db(engine)
    sf = create_session_factory(engine)
    schedule = ScheduleService(sf, settings)
    bookings = BookingService(sf, settings)

    # ---------- config / structure ----------
    t.section("Config & routers")
    t.check("admin ids loaded", len(settings.admin_telegram_ids) >= 1, str(settings.admin_telegram_ids))
    t.check("primary admin is first", settings.primary_admin_id == settings.admin_telegram_ids[0])
    t.check("is_admin works", settings.is_admin(settings.primary_admin_id))
    t.check("is_primary_admin works", settings.is_primary_admin(settings.primary_admin_id))
    t.check("is_admin rejects stranger", not settings.is_admin(999999001))
    t.check("stranger not primary", not settings.is_primary_admin(999999001))
    if len(settings.admin_telegram_ids) >= 2:
        support = settings.admin_telegram_ids[1]
        t.check("support is admin", settings.is_admin(support))
        t.check("support is not primary", not settings.is_primary_admin(support))
    try:
        setup_routers()
        t.check("setup_routers()", True)
    except Exception as e:
        t.check("setup_routers()", False, str(e))

    home_kb = str(admin_kb.admin_home_keyboard())
    t.check("no Сводка in home kb", "Сводка" not in home_kb and "stats" not in home_kb.lower())
    t.check("no Сводка in ADMIN_HOME", "Сводка" not in msg.ADMIN_HOME)
    t.check("Записи in home", "Записи" in home_kb)
    t.check("График in home", "График" in home_kb)
    t.check("Настройки in home", "Настройки" in home_kb)

    # ---------- parsers ----------
    t.section("Date / hours parsers")
    y = date.today().year
    d = parse_day("01.10")
    t.check(
        "parse_day 01.10 has year",
        d.month == 10 and d.day == 1 and d.year in {y, y + 1},
    )
    t.check(
        "format_date_short with year",
        format_date_short(date(2026, 10, 1)) == "01.10.2026",
    )
    try:
        parse_day("32.01")
        t.check("parse_day invalid raises", False)
    except ValidationError:
        t.check("parse_day invalid raises", True)
    try:
        parse_day("01.01.2020")
        t.check("parse_day past year rejected", False)
    except ValidationError:
        t.check("parse_day past year rejected", True)

    days, bad = parse_days_column("01.10\n10.10\n11.10")
    t.check("parse_days_column count", len(days) == 3 and not bad)
    days2, _ = parse_days_column("01.10\n01.10\n10.10")
    t.check("parse_days_column dedupe", len(days2) == 2)
    days3, bad3 = parse_days_column("недата\n01.10")
    t.check("parse_days_column bad tokens", len(bad3) == 1 and len(days3) == 1)

    h_open, h_close, step = parse_hours_message("10:00-18:00")
    t.check(
        "parse_hours",
        h_open == time(10, 0) and h_close == time(18, 0) and step == 60,
    )

    # ---------- schedule ----------
    t.section("Schedule: days & hours")
    today = date.today()
    past = today - timedelta(days=1)
    d1 = today + timedelta(days=3)
    d2 = today + timedelta(days=4)
    d3 = today + timedelta(days=5)

    try:
        await schedule.add_day_from_defaults(past)
        t.check("reject past day", False)
    except ValidationError:
        t.check("reject past day", True)

    day1 = await schedule.add_day_from_defaults(d1)
    t.check("add day", day1.day == d1 and len(day1.slots) >= 8)
    n_slots = len(day1.slots)

    try:
        await schedule.add_day_from_defaults(d1)
        t.check("duplicate day rejected", False)
    except DuplicateSlotError:
        t.check("duplicate day rejected", True)

    # Custom hours then re-add must NOT merge default slots back in
    day1 = await schedule.set_day_hours(day1.id, time(12, 0), time(14, 0), 60)
    t.check("set_day_hours shrinks", len(day1.slots) == 2, f"got {len(day1.slots)}")
    t.check("day hours custom", day1.open_time == time(12, 0) and day1.close_time == time(14, 0))
    custom_n = len(day1.slots)
    try:
        await schedule.add_day_from_defaults(d1)
        t.check("re-add custom day blocked", False)
    except DuplicateSlotError:
        t.check("re-add custom day blocked", True)
    day1 = await schedule.get_day(day1.id)
    t.check("custom day unchanged after re-add attempt", len(day1.slots) == custom_n)

    day1 = await schedule.clear_day_override(day1.id)
    t.check(
        "clear_day_override",
        day1.open_time is None and len(day1.slots) == n_slots,
        f"slots={len(day1.slots)} expected={n_slots}",
    )

    created, skipped = await schedule.fill_days([d1, d2, d3])
    t.check("fill_days created 2", created == 2, f"created={created}")
    t.check("fill_days skipped existing", skipped == 1, f"skipped={skipped}")
    days_list = await schedule.list_upcoming_days()
    t.check("list_upcoming has 3", len(days_list) == 3)

    slot0 = day1.slots[0]
    s2 = await schedule.toggle_slot_block(slot0.id)
    t.check("block slot", s2.status == SlotStatus.BLOCKED.value)
    s3 = await schedule.toggle_slot_block(slot0.id)
    t.check("unblock slot", s3.status == SlotStatus.FREE.value)

    # ---------- booking happy path ----------
    t.section("Booking: hold -> confirm -> cancel")
    day1 = await schedule.get_day(day1.id)
    free_slot = next(s for s in day1.slots if s.status == SlotStatus.FREE.value)

    b = await bookings.hold_slot(
        slot_id=free_slot.id,
        user_id=1001,
        username="test_client",
        full_name="Тест Клиент",
        phone="+79990001122",
        service=None,
    )
    t.check("hold pending", b.status == BookingStatus.PENDING_PAYMENT.value)
    t.check("hold duration 60", b.duration_minutes == 60)
    day1 = await schedule.get_day(day1.id)
    held = next(s for s in day1.slots if s.id == free_slot.id)
    t.check("slot held", held.status == SlotStatus.HELD.value)

    other = next(s for s in day1.slots if s.id != free_slot.id and s.status == SlotStatus.FREE.value)
    try:
        await bookings.hold_slot(
            slot_id=other.id,
            user_id=1001,
            username=None,
            full_name="X",
            phone="+7999",
            service=None,
        )
        t.check("double active blocked", False)
    except AlreadyHasBookingError:
        t.check("double active blocked", True)

    try:
        await bookings.hold_slot(
            slot_id=free_slot.id,
            user_id=1002,
            username=None,
            full_name="Y",
            phone="+7888",
            service=None,
        )
        t.check("held not stealable", False)
    except SlotNotAvailableError:
        t.check("held not stealable", True)

    blocked = next(
        s for s in day1.slots if s.status == SlotStatus.FREE.value and s.id != free_slot.id
    )
    await schedule.toggle_slot_block(blocked.id)
    try:
        await bookings.hold_slot(
            slot_id=blocked.id,
            user_id=1002,
            username=None,
            full_name="Y",
            phone="+7888",
            service=None,
        )
        t.check("blocked not bookable", False)
    except SlotNotAvailableError:
        t.check("blocked not bookable", True)
    await schedule.toggle_slot_block(blocked.id)

    b = await bookings.confirm_with_receipt(
        booking_id=b.id,
        user_id=1001,
        receipt_file_id="file_receipt_1",
        receipt_file_type="photo",
    )
    t.check(
        "confirm active",
        b.status == BookingStatus.ACTIVE.value and b.receipt_file_id == "file_receipt_1",
    )
    day1 = await schedule.get_day(day1.id)
    booked = next(s for s in day1.slots if s.id == free_slot.id)
    t.check("slot booked", booked.status == SlotStatus.BOOKED.value)

    try:
        await schedule.delete_day(day1.id)
        t.check("delete day with booking blocked", False)
    except ValidationError:
        t.check("delete day with booking blocked", True)

    try:
        await schedule.toggle_slot_block(free_slot.id)
        t.check("toggle booked blocked", False)
    except ValidationError:
        t.check("toggle booked blocked", True)

    mine = await bookings.list_user_bookings(1001)
    t.check("list_user_bookings", len(mine) == 1)

    by_day = await bookings.list_for_working_day(day1.id)
    t.check("list_for_working_day", len(by_day) == 1)

    b = await bookings.cancel_by_client(b.id, 1001)
    t.check("client cancel", b.status == BookingStatus.CANCELLED.value)
    day1 = await schedule.get_day(day1.id)
    freed = next(s for s in day1.slots if s.id == free_slot.id)
    t.check("slot freed after cancel", freed.status == SlotStatus.FREE.value)

    # ---------- reschedule ----------
    t.section("Booking: reschedule")
    day1 = await schedule.get_day(day1.id)
    s_a = next(s for s in day1.slots if s.status == SlotStatus.FREE.value)
    b = await bookings.hold_slot(
        slot_id=s_a.id,
        user_id=2001,
        username="res",
        full_name="Res",
        phone="+7111",
        service=None,
    )
    b = await bookings.confirm_with_receipt(
        booking_id=b.id, user_id=2001, receipt_file_id="r2", receipt_file_type="photo"
    )
    s_b = next(s for s in day1.slots if s.status == SlotStatus.FREE.value and s.id != s_a.id)
    b2 = await bookings.reschedule(b.id, s_b.id)
    t.check("reschedule moves", b2.slot_id == s_b.id)
    day1 = await schedule.get_day(day1.id)
    t.check(
        "old free after reschedule",
        next(s for s in day1.slots if s.id == s_a.id).status == SlotStatus.FREE.value,
    )
    t.check(
        "new booked after reschedule",
        next(s for s in day1.slots if s.id == s_b.id).status == SlotStatus.BOOKED.value,
    )
    await bookings.cancel_booking(b2.id, by_admin=True)

    # ---------- hold expiry ----------
    t.section("Hold expiry")
    day2 = await _day_by_date(schedule, d2)
    assert day2 is not None
    s = next(x for x in day2.slots if x.status == SlotStatus.FREE.value)
    b = await bookings.hold_slot(
        slot_id=s.id,
        user_id=3001,
        username=None,
        full_name="Hold",
        phone="+7222",
        service=None,
    )
    async with sf() as session:
        slot = await session.get(Slot, s.id)
        assert slot is not None
        slot.held_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()
    n = await schedule.release_expired_holds(force=True)
    t.check("release_expired_holds", n >= 1, f"released={n}")
    expired_b = await bookings.get_booking(b.id)
    t.check("pending cancelled on expiry", expired_b.status == BookingStatus.CANCELLED.value)
    day2 = await schedule.get_day(day2.id)
    t.check(
        "slot free after expiry",
        next(x for x in day2.slots if x.id == s.id).status == SlotStatus.FREE.value,
    )

    # delete day while held should be blocked
    day2b = await _day_by_date(schedule, d2)
    assert day2b is not None
    s_hold = next(x for x in day2b.slots if x.status == SlotStatus.FREE.value)
    b_hold = await bookings.hold_slot(
        slot_id=s_hold.id,
        user_id=3002,
        username=None,
        full_name="Hold2",
        phone="+7223",
        service=None,
    )
    try:
        await schedule.delete_day(day2b.id)
        t.check("delete day with hold blocked", False)
    except ValidationError:
        t.check("delete day with hold blocked", True)
    await bookings.cancel_booking(b_hold.id)

    # ---------- settings ----------
    t.section("Settings")
    ws = await schedule.get_work_settings()
    t.check("get_work_settings", ws is not None)
    await schedule.set_prepayment_amount("2000")
    ws = await schedule.get_work_settings()
    t.check("set_prepayment", ws.prepayment_amount == "2 000 ₽")
    await schedule.set_prepayment_amount("500")
    ws = await schedule.get_work_settings()
    t.check("set_prepayment digits", ws.prepayment_amount == "500 ₽")
    await schedule.set_work_settings(time(10, 0), time(20, 0), 60)
    ws = await schedule.get_work_settings()
    t.check("set_work_settings", ws.open_time == time(10, 0) and ws.close_time == time(20, 0))

    empty = await _day_by_date(schedule, d3)
    assert empty is not None
    # ensure no holds
    await schedule.release_expired_holds(force=True)
    empty = await schedule.get_day(empty.id)
    for s in empty.slots:
        if s.status == SlotStatus.HELD.value:
            # shouldn't happen
            pass
    await schedule.delete_day(empty.id)
    try:
        await schedule.get_day(empty.id)
        t.check("delete empty day", False)
    except Exception:
        t.check("delete empty day", True)

    # ---------- UI smoke ----------
    t.section("UI texts & keyboards")
    t.check(
        "FAQ hub text exists",
        "FAQ" in msg.FAQ and "Выбери" in msg.FAQ,
    )
    t.check(
        "FAQ sections exist",
        "предоплата" in msg.FAQ_BOOKING.lower() and "Гарантия" in msg.FAQ_RULES,
    )
    menu_str = str(mkb.main_menu_keyboard(settings))
    t.check("main_menu has FAQ", "FAQ" in menu_str)
    t.check("main_menu has primary book", msg.BTN_BOOK in menu_str)
    days_kb = str(admin_kb.admin_bookings_days_keyboard([(1, d1, 0), (2, d2, 1)]))
    t.check(
        "bookings days no Сегодня/Завтра",
        "Сегодня" not in days_kb and "Завтра" not in days_kb,
    )
    t.check(
        "schedule hub",
        "Добавить день" in str(admin_kb.admin_schedule_hub_keyboard(days_count=3)),
    )
    t.check("payment kb", msg.BTN_PAY in str(bkb.payment_keyboard(settings)))

    # ---------- cancel <24h ----------
    t.section("Cancel policy <24h")
    async with sf() as session:
        wd = WorkingDay(day=today, open_time=time(0, 0), close_time=time(23, 0), slot_minutes=60)
        session.add(wd)
        await session.flush()
        soon = (datetime.now(timezone.utc) + timedelta(hours=2)).astimezone().time().replace(
            second=0, microsecond=0
        )
        # Use a fixed near time on today that is within 24h
        sl = Slot(
            working_day_id=wd.id,
            start_time=time(23, 0) if datetime.now().hour < 22 else time(23, 30),
            status=SlotStatus.BOOKED.value,
        )
        # Better: set start_time to now+2h in bot local time
        from domain.dates import SAMARA_TZ

        soon_local = datetime.now(SAMARA_TZ) + timedelta(hours=2)
        # If crosses midnight, use today 23:00 and accept test only if visit < 24h (always true for today)
        sl.start_time = soon_local.time().replace(second=0, microsecond=0)
        if soon_local.date() != today:
            # edge at late night — put slot at end of today
            sl.start_time = time(23, 0)
        session.add(sl)
        await session.flush()
        bk = Booking(
            telegram_user_id=5001,
            full_name="Near",
            phone="+7444",
            slot_id=sl.id,
            status=BookingStatus.ACTIVE.value,
            duration_minutes=60,
            confirmed_at=datetime.now(timezone.utc),
        )
        session.add(bk)
        await session.commit()
        bid = bk.id

    try:
        await bookings.cancel_by_client(bid, 5001)
        t.check("client cancel <24h blocked", False, "should have raised")
    except ValidationError as e:
        t.check("client cancel <24h blocked", "24" in str(e), str(e))
    await bookings.cancel_booking(bid, by_admin=True)
    t.check("admin can cancel <24h", True)

    # ---------- multi-admin / handler wiring sanity ----------
    t.section("Handler imports / dead refs")
    import handlers.admin as admin_mod
    import handlers.booking as booking_mod

    t.check("no admin_stats handler", not hasattr(admin_mod, "admin_stats"))
    t.check("booking has receipt handler", hasattr(booking_mod, "booking_receipt"))
    t.check("no week_stats on ScheduleService", not hasattr(ScheduleService, "week_stats"))

    # ---------- summary ----------
    print(f"\n{'=' * 40}")
    print(f"Passed: {t.ok}  Failed: {t.fail}")
    if t.errors:
        print("Failures:")
        for e in t.errors:
            print(" -", e)

    await engine.dispose()
    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass
    return 1 if t.fail else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
