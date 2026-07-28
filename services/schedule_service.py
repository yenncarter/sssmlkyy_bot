"""Schedule and booking services.

Concurrency note: `with_for_update()` is a no-op on SQLite (SQLAlchemy drops
`FOR UPDATE`), so row locks must never be the only guard. Correctness relies on
the partial unique indexes created in `db.session.init_db`:

* `uq_live_booking_slot` — at most one live booking per slot;
* `uq_live_booking_user` — at most one live booking per client.

Both are enforced by the database and translated back into domain errors here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from config.settings import Settings
from db.models import Booking, Slot, WorkingDay, WorkSettings
from domain.dates import combine_datetime, now_local, to_local, today
from domain.enums import BookingStatus, SlotStatus
from domain.exceptions import (
    AlreadyHasBookingError,
    BookingNotFoundError,
    DayNotFoundError,
    DuplicateSlotError,
    PermissionDeniedError,
    SlotNotAvailableError,
    SlotNotFoundError,
    ValidationError,
)
from domain.slots import (
    DEFAULT_CLOSE,
    DEFAULT_OPEN,
    DEFAULT_SLOT_MINUTES,
    generate_slot_times,
    slots_needed,
)

# Statuses that occupy a slot and block the client from booking again.
LIVE_BOOKING_STATUSES = (
    BookingStatus.PENDING_PAYMENT.value,
    BookingStatus.ACTIVE.value,
)
BUSY_SLOT_STATUSES = frozenset(
    {SlotStatus.BOOKED.value, SlotStatus.HELD.value}
)
# Upper bound for calendar screens — keeps a single query bounded.
MAX_CALENDAR_DAYS = 90
CLIENT_CANCEL_CUTOFF = timedelta(hours=24)
# How long after a hold lapsed a receipt is still recognised as belonging to it.
LATE_RECEIPT_GRACE = timedelta(hours=3)


@dataclass(frozen=True, slots=True)
class WorkHours:
    """Immutable snapshot of the singleton work_settings row."""

    open_time: time
    close_time: time
    slot_minutes: int
    prepayment_amount: str


class ScheduleService:
    """Working days, slot grid and salon-wide settings."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._settings = settings
        self._work_hours: WorkHours | None = None

    # --- work settings -------------------------------------------------

    async def get_work_settings(self) -> WorkHours:
        """Cached: the row changes a few times a year, but is read constantly."""
        if self._work_hours is not None:
            return self._work_hours
        async with self._sf() as session:
            row = await session.get(WorkSettings, 1)
            if row is None:
                row = WorkSettings(
                    id=1,
                    open_time=DEFAULT_OPEN,
                    close_time=DEFAULT_CLOSE,
                    slot_minutes=DEFAULT_SLOT_MINUTES,
                )
                session.add(row)
                await session.commit()
            self._work_hours = _snapshot(row)
            return self._work_hours

    async def set_work_settings(
        self,
        open_time: time,
        close_time: time,
        slot_minutes: int,
    ) -> WorkHours:
        generate_slot_times(open_time, close_time, slot_minutes)  # validate
        async with self._sf() as session:
            row = await session.get(WorkSettings, 1)
            if row is None:
                row = WorkSettings(id=1, prepayment_amount="1 000 ₽")
                session.add(row)
            row.open_time = open_time
            row.close_time = close_time
            row.slot_minutes = slot_minutes
            await session.commit()
            self._work_hours = _snapshot(row)
            return self._work_hours

    async def set_prepayment_amount(self, amount: str) -> WorkHours:
        """`amount` must already be normalized by domain.parsing."""
        async with self._sf() as session:
            row = await session.get(WorkSettings, 1)
            if row is None:
                raise ValidationError("Настройки не найдены.")
            row.prepayment_amount = amount
            await session.commit()
            self._work_hours = _snapshot(row)
            return self._work_hours

    def cached_work_hours(self) -> WorkHours | None:
        """Snapshot without I/O — lets callers avoid opening a nested session."""
        return self._work_hours

    # --- days ----------------------------------------------------------

    async def add_day_with_times(
        self,
        day: date,
        times: list[time],
        *,
        open_time: time | None = None,
        close_time: time | None = None,
        slot_minutes: int | None = None,
    ) -> WorkingDay:
        if day < today():
            raise ValidationError("Нельзя добавить прошедшую дату.")
        if not times:
            raise ValidationError("Добавь хотя бы одно время.")

        unique_times = sorted(set(times))
        async with self._sf() as session:
            exists = await session.scalar(
                select(WorkingDay.id).where(WorkingDay.day == day)
            )
            if exists is not None:
                # Never merge default hours into an existing day — it would
                # silently overwrite the master's custom hours.
                raise DuplicateSlotError("Этот день уже есть в графике.")

            created = WorkingDay(
                day=day,
                open_time=open_time,
                close_time=close_time,
                slot_minutes=slot_minutes,
            )
            session.add(created)
            await session.flush()
            for start in unique_times:
                session.add(
                    Slot(
                        working_day_id=created.id,
                        start_time=start,
                        status=SlotStatus.FREE.value,
                    )
                )
            day_id = created.id
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateSlotError("Этот день уже есть в графике.") from exc

        return await self.get_day(day_id)

    async def add_day_from_defaults(self, day: date) -> WorkingDay:
        ws = await self.get_work_settings()
        times = generate_slot_times(ws.open_time, ws.close_time, ws.slot_minutes)
        return await self.add_day_with_times(day, times)

    async def set_day_hours(
        self,
        day_id: int,
        open_time: time,
        close_time: time,
        slot_minutes: int,
        *,
        rebuild_free_slots: bool = True,
    ) -> WorkingDay:
        times = generate_slot_times(open_time, close_time, slot_minutes)
        async with self._sf() as session:
            day = await self._load_day(session, day_id)
            day.open_time = open_time
            day.close_time = close_time
            day.slot_minutes = slot_minutes
            if rebuild_free_slots:
                await self._rebuild_free_slots(session, day, times)
            await session.commit()
        return await self.get_day(day_id)

    async def clear_day_override(self, day_id: int) -> WorkingDay:
        """Reset day to global defaults and rebuild free slots."""
        ws = await self.get_work_settings()
        times = generate_slot_times(ws.open_time, ws.close_time, ws.slot_minutes)
        async with self._sf() as session:
            day = await self._load_day(session, day_id)
            day.open_time = None
            day.close_time = None
            day.slot_minutes = None
            await self._rebuild_free_slots(session, day, times)
            await session.commit()
        return await self.get_day(day_id)

    async def _rebuild_free_slots(
        self,
        session: AsyncSession,
        day: WorkingDay,
        times: list[time],
    ) -> None:
        """Replace the free-slot grid for `day`.

        Two kinds of rows must survive, or the rebuild corrupts data:

        * slots carrying a live booking (BOOKED / HELD);
        * slots referenced by *any* booking row, including cancelled ones —
          the FK is RESTRICT, so deleting them raises IntegrityError;
        * slots the master closed by hand (BLOCKED) — re-inserting the same
          start_time would violate `uq_slot_day_time`.
        """
        wanted = set(times)
        keep_times: set[time] = set()

        slot_ids = [s.id for s in day.slots if s.id is not None]
        referenced: set[int] = set()
        if slot_ids:
            referenced = set(
                await session.scalars(
                    select(Booking.slot_id).where(Booking.slot_id.in_(slot_ids))
                )
            )

        for slot in list(day.slots):
            if slot.status in BUSY_SLOT_STATUSES:
                keep_times.add(slot.start_time)
                continue
            if slot.status == SlotStatus.BLOCKED.value:
                keep_times.add(slot.start_time)
                continue
            if slot.id in referenced:
                # Historical booking pins this row. Keep it, but take it out of
                # the offer if it is no longer part of the working grid.
                keep_times.add(slot.start_time)
                if slot.start_time not in wanted:
                    slot.status = SlotStatus.BLOCKED.value
                continue
            await session.delete(slot)

        await session.flush()
        for start in times:
            if start in keep_times:
                continue
            session.add(
                Slot(
                    working_day_id=day.id,
                    start_time=start,
                    status=SlotStatus.FREE.value,
                )
            )

    async def delete_day(self, day_id: int) -> None:
        async with self._sf() as session:
            day = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots).selectinload(Slot.bookings))
            )
            if day is None:
                raise DayNotFoundError("День не найден.")
            if any(s.status in BUSY_SLOT_STATUSES for s in day.slots):
                raise ValidationError(
                    "Нельзя удалить день с записями или бронью. Сначала отмени их."
                )
            # Historical bookings hold an FK on the slots; drop them explicitly,
            # otherwise the ORM tries to NULL a NOT NULL column.
            for slot in day.slots:
                for booking in list(slot.bookings):
                    await session.delete(booking)
            await session.flush()
            await session.delete(day)
            await session.commit()

    async def get_day(self, day_id: int) -> WorkingDay:
        async with self._sf() as session:
            return await self._load_day(session, day_id)

    @staticmethod
    async def _load_day(session: AsyncSession, day_id: int) -> WorkingDay:
        day = await session.scalar(
            select(WorkingDay)
            .where(WorkingDay.id == day_id)
            .options(selectinload(WorkingDay.slots))
        )
        if day is None:
            raise DayNotFoundError("День не найден.")
        return day

    async def list_upcoming_days(self, limit: int = MAX_CALENDAR_DAYS) -> list[WorkingDay]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(WorkingDay)
                .where(WorkingDay.day >= today())
                .options(selectinload(WorkingDay.slots))
                .order_by(WorkingDay.day)
                .limit(limit)
            )
            return list(rows)

    async def list_days_with_free_slots(self) -> list[tuple[WorkingDay, int]]:
        days = await self.list_upcoming_days()
        now = now_local()
        out: list[tuple[WorkingDay, int]] = []
        for day in days:
            free = sum(
                1 for s in day.slots if self.is_bookable_slot(s, day.day, now)
            )
            if free:
                out.append((day, free))
        return out

    async def free_slots_for_day(self, day_id: int) -> list[Slot]:
        async with self._sf() as session:
            day = await self._load_day(session, day_id)
            if day.day < today():
                return []
            now = now_local()
            return sorted(
                (s for s in day.slots if self.is_bookable_slot(s, day.day, now)),
                key=lambda s: s.start_time,
            )

    async def toggle_slot_block(self, slot_id: int) -> Slot:
        """Free <-> blocked. Cannot toggle booked/held."""
        async with self._sf() as session:
            slot = await session.get(Slot, slot_id)
            if slot is None:
                raise SlotNotFoundError("Слот не найден.")
            if slot.status == SlotStatus.FREE.value:
                slot.status = SlotStatus.BLOCKED.value
            elif slot.status == SlotStatus.BLOCKED.value:
                slot.status = SlotStatus.FREE.value
            else:
                raise ValidationError(
                    "Этот слот занят записью — сначала отмени запись."
                )
            await session.commit()
            await session.refresh(slot)
            return slot

    # --- availability predicates ---------------------------------------

    @staticmethod
    def is_effectively_free(slot: Slot, now: datetime) -> bool:
        """FREE, or a hold that has already lapsed."""
        if slot.status == SlotStatus.FREE.value:
            return True
        if slot.status == SlotStatus.HELD.value:
            held_until = to_local(slot.held_until)
            return held_until is not None and held_until < now
        return False

    @classmethod
    def is_bookable_slot(cls, slot: Slot, day: date, now: datetime) -> bool:
        """Free (or expired hold) and not in the past by the bot clock."""
        if not cls.is_effectively_free(slot, now):
            return False
        return combine_datetime(day, slot.start_time) > now

    # --- housekeeping (scheduler owns the cadence) ----------------------

    async def release_expired_holds(self) -> int:
        """Free lapsed holds and cancel the pending bookings behind them."""
        now = now_local()
        async with self._sf() as session:
            slots = list(
                await session.scalars(
                    select(Slot).where(Slot.status == SlotStatus.HELD.value)
                )
            )
            expired = [
                slot
                for slot in slots
                if (held := to_local(slot.held_until)) is None or held < now
            ]
            if not expired:
                return 0

            expired_ids = [slot.id for slot in expired]
            pending = list(
                await session.scalars(
                    select(Booking).where(
                        Booking.slot_id.in_(expired_ids),
                        Booking.status == BookingStatus.PENDING_PAYMENT.value,
                    )
                )
            )
            for booking in pending:
                booking.status = BookingStatus.CANCELLED.value

            for slot in expired:
                slot.status = SlotStatus.FREE.value
                slot.held_by_user_id = None
                slot.held_until = None

            await session.commit()
            return len(expired_ids)

    async def purge_past_days(self) -> int:
        """Drop past days that carry no history at all.

        Days with bookings are kept: the booking rows are the salon's only
        record of who came and what was paid, and they cannot outlive their
        slot (FK RESTRICT + `Booking.slot` is required for rendering).
        """
        cutoff = today()
        async with self._sf() as session:
            days = list(
                await session.scalars(
                    select(WorkingDay)
                    .where(WorkingDay.day < cutoff)
                    .options(
                        selectinload(WorkingDay.slots).selectinload(Slot.bookings)
                    )
                )
            )
            removed = 0
            for day in days:
                if any(slot.bookings for slot in day.slots):
                    continue
                await session.delete(day)
                removed += 1
            if removed:
                await session.commit()
            return removed


def _snapshot(row: WorkSettings) -> WorkHours:
    return WorkHours(
        open_time=row.open_time,
        close_time=row.close_time,
        slot_minutes=row.slot_minutes or DEFAULT_SLOT_MINUTES,
        prepayment_amount=row.prepayment_amount or "1 000 ₽",
    )


# --- Booking ---------------------------------------------------------------


class BookingService:
    """Client bookings: hold → receipt → active, plus admin operations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._settings = settings
        self._schedule = ScheduleService(session_factory, settings)

    # --- helpers -------------------------------------------------------

    async def _step_for_day(self, session: AsyncSession, day: WorkingDay) -> int:
        if day.slot_minutes:
            return day.slot_minutes
        cached = self._schedule.cached_work_hours()
        if cached is not None:
            return cached.slot_minutes
        # Read on the caller's session: opening another one mid-transaction is
        # how you get "database is locked" on SQLite.
        row = await session.get(WorkSettings, 1)
        return (row.slot_minutes if row else None) or DEFAULT_SLOT_MINUTES

    @staticmethod
    def _visit_start(booking: Booking) -> datetime:
        return combine_datetime(
            booking.slot.working_day.day, booking.slot.start_time
        )

    def _visit_end(self, booking: Booking, step: int) -> datetime:
        duration = booking.duration_minutes or step
        return self._visit_start(booking) + timedelta(minutes=duration)

    async def _block_slots(
        self, session: AsyncSession, booking: Booking
    ) -> list[Slot]:
        """Consecutive slots occupied by this booking, starting at booking.slot."""
        day = booking.slot.working_day
        if not day.slots:
            await session.refresh(day, attribute_names=["slots"])
        step = await self._step_for_day(session, day)
        need = slots_needed(booking.duration_minutes or step, step)
        ordered = sorted(day.slots, key=lambda s: s.start_time)
        index = next(
            (i for i, s in enumerate(ordered) if s.id == booking.slot_id), None
        )
        if index is None:
            # Slot was moved out of this day — nothing sane to unblock.
            return []
        return ordered[index : index + need]

    async def _apply_block_status(
        self,
        session: AsyncSession,
        booking: Booking,
        status: str,
        *,
        clear_hold: bool,
    ) -> None:
        if booking.slot is None or booking.slot.working_day is None:
            reloaded = await session.scalar(
                select(Booking)
                .where(Booking.id == booking.id)
                .options(
                    selectinload(Booking.slot)
                    .selectinload(Slot.working_day)
                    .selectinload(WorkingDay.slots)
                )
            )
            if reloaded is None:
                raise BookingNotFoundError("Запись не найдена.")
            booking = reloaded
        elif not booking.slot.working_day.slots:
            await session.refresh(booking.slot.working_day, attribute_names=["slots"])

        for slot in await self._block_slots(session, booking):
            slot.status = status
            if clear_hold:
                slot.held_by_user_id = None
                slot.held_until = None
            else:
                slot.held_by_user_id = booking.telegram_user_id

    async def _free_block(self, session: AsyncSession, booking: Booking) -> None:
        await self._apply_block_status(
            session, booking, SlotStatus.FREE.value, clear_hold=True
        )

    async def _settle_user_past(
        self, session: AsyncSession, user_id: int, now: datetime
    ) -> None:
        """Close out one client's finished/expired bookings.

        Needed before every availability check: `uq_live_booking_user` counts
        live rows regardless of date, so a stale row would wrongly block the
        client from booking again.
        """
        bookings = list(
            await session.scalars(
                select(Booking)
                .where(
                    Booking.telegram_user_id == user_id,
                    Booking.status.in_(LIVE_BOOKING_STATUSES),
                )
                .options(
                    selectinload(Booking.slot)
                    .selectinload(Slot.working_day)
                    .selectinload(WorkingDay.slots)
                )
            )
        )
        changed = False
        for booking in bookings:
            step = await self._step_for_day(session, booking.slot.working_day)
            if self._visit_end(booking, step) > now:
                continue
            booking.status = (
                BookingStatus.COMPLETED.value
                if booking.status == BookingStatus.ACTIVE.value
                else BookingStatus.CANCELLED.value
            )
            await self._apply_block_status(
                session, booking, SlotStatus.FREE.value, clear_hold=True
            )
            changed = True
        if changed:
            await session.flush()

    @staticmethod
    async def _count_live(session: AsyncSession, user_id: int) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(Booking)
                .where(
                    Booking.telegram_user_id == user_id,
                    Booking.status.in_(LIVE_BOOKING_STATUSES),
                )
            )
            or 0
        )

    # --- client flow ---------------------------------------------------

    async def user_has_active_booking(self, user_id: int) -> bool:
        now = now_local()
        async with self._sf() as session:
            await self._settle_user_past(session, user_id, now)
            has_live = await self._count_live(session, user_id) > 0
            await session.commit()
            return has_live

    async def hold_slot(
        self,
        *,
        slot_id: int,
        user_id: int,
        username: str | None,
        full_name: str,
        phone: str,
        duration_minutes: int | None = None,
    ) -> Booking:
        now = now_local()
        hold_until = now + timedelta(minutes=self._settings.slot_hold_minutes)

        async with self._sf() as session:
            await self._settle_user_past(session, user_id, now)
            if await self._count_live(session, user_id):
                raise AlreadyHasBookingError(
                    "У тебя уже есть активная запись. "
                    "Сначала отмени её или дождись визита."
                )

            slot = await session.scalar(
                select(Slot)
                .where(Slot.id == slot_id)
                .options(selectinload(Slot.working_day).selectinload(WorkingDay.slots))
                .with_for_update()
            )
            if slot is None:
                raise SlotNotFoundError("Слот не найден.")

            day = slot.working_day
            if day.day < today():
                raise SlotNotAvailableError("Этот день уже прошёл. Выбери другую дату.")

            step = await self._step_for_day(session, day)
            duration = duration_minutes or step
            need = slots_needed(duration, step)
            block = _consecutive_block(day.slots, slot.id, need)
            if len(block) < need or not all(
                ScheduleService.is_bookable_slot(s, day.day, now) for s in block
            ):
                raise SlotNotAvailableError(
                    "Это время уже недоступно. Выбери другое окошко."
                )

            stale = list(
                await session.scalars(
                    select(Booking).where(
                        Booking.slot_id.in_([s.id for s in block]),
                        Booking.status == BookingStatus.PENDING_PAYMENT.value,
                    )
                )
            )
            for booking in stale:
                booking.status = BookingStatus.CANCELLED.value

            for slot_in_block in block:
                slot_in_block.status = SlotStatus.HELD.value
                slot_in_block.held_by_user_id = user_id
                slot_in_block.held_until = hold_until

            booking = Booking(
                slot_id=block[0].id,
                telegram_user_id=user_id,
                username=username,
                full_name=full_name,
                phone=phone,
                duration_minutes=duration,
                status=BookingStatus.PENDING_PAYMENT.value,
            )
            session.add(booking)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise _map_booking_conflict(exc) from exc
            booking_id = booking.id

        return await self.get_booking(booking_id)

    async def confirm_with_receipt(
        self,
        *,
        booking_id: int,
        user_id: int,
        receipt_file_id: str,
        receipt_file_type: str,
    ) -> Booking:
        now = now_local()
        async with self._sf() as session:
            booking = await session.scalar(
                select(Booking)
                .where(Booking.id == booking_id)
                .options(
                    selectinload(Booking.slot)
                    .selectinload(Slot.working_day)
                    .selectinload(WorkingDay.slots)
                )
                .with_for_update()
            )
            if booking is None or booking.telegram_user_id != user_id:
                raise BookingNotFoundError("Запись не найдена.")
            if booking.status != BookingStatus.PENDING_PAYMENT.value:
                raise ValidationError("Эта запись уже обработана.")

            slot = booking.slot
            held_until = to_local(slot.held_until)
            if (
                slot.status != SlotStatus.HELD.value
                or slot.held_by_user_id != user_id
                or held_until is None
                or held_until < now
            ):
                booking.status = BookingStatus.CANCELLED.value
                await self._free_block(session, booking)
                await session.commit()
                raise SlotNotAvailableError(
                    "Время ожидания оплаты истекло. Начни запись заново."
                )

            # Conditional UPDATE: two receipts sent back to back must not both
            # win (SQLite gives us no row lock to lean on).
            result = await session.execute(
                update(Booking)
                .where(
                    Booking.id == booking_id,
                    Booking.status == BookingStatus.PENDING_PAYMENT.value,
                )
                .values(
                    status=BookingStatus.ACTIVE.value,
                    receipt_file_id=receipt_file_id,
                    receipt_file_type=receipt_file_type,
                    confirmed_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if not result.rowcount:
                await session.rollback()
                raise ValidationError("Эта запись уже обработана.")

            # `booking` is intentionally left untouched by the ORM: it is not
            # dirty, so the stale in-memory status is never flushed back.
            await self._apply_block_status(
                session, booking, SlotStatus.BOOKED.value, clear_hold=True
            )
            await session.commit()

        return await self.get_booking(booking_id)

    async def find_receipt_target(self, user_id: int) -> Booking | None:
        """The booking an unexpected photo from this user is a receipt for.

        FSM state lives in process memory, so a redeploy in the minute between
        «Оплатить» and sending the receipt used to leave the client with a
        useless «не поняла» — money paid, no booking. The pending row in the
        database is the durable record, so it is what we look at.
        """
        async with self._sf() as session:
            pending = await session.scalar(
                self._booking_query()
                .where(
                    Booking.telegram_user_id == user_id,
                    Booking.status == BookingStatus.PENDING_PAYMENT.value,
                )
                .order_by(Booking.id.desc())
                .limit(1)
            )
            if pending is not None:
                return pending

            # The hold lapsed while the bot was down, or the sweep cancelled it.
            # The money is still real, so the master must see the receipt.
            cutoff = now_local() - LATE_RECEIPT_GRACE
            return await session.scalar(
                self._booking_query()
                .where(
                    Booking.telegram_user_id == user_id,
                    Booking.status == BookingStatus.CANCELLED.value,
                    Booking.receipt_file_id.is_(None),
                    Booking.created_at >= cutoff,
                )
                .order_by(Booking.id.desc())
                .limit(1)
            )

    async def attach_late_receipt(
        self,
        booking_id: int,
        *,
        receipt_file_id: str,
        receipt_file_type: str,
    ) -> Booking:
        """Record a receipt that arrived after the hold expired.

        The status stays CANCELLED on purpose: the slot may already belong to
        somebody else, and only the master can decide what to do about it.
        """
        async with self._sf() as session:
            booking = await session.get(Booking, booking_id)
            if booking is None:
                raise BookingNotFoundError("Запись не найдена.")
            if booking.receipt_file_id:
                raise ValidationError("Чек по этой записи уже получен.")
            booking.receipt_file_id = receipt_file_id
            booking.receipt_file_type = receipt_file_type
            if not booking.note:
                booking.note = "Оплата пришла после истечения брони"
            await session.commit()
        return await self.get_booking(booking_id)

    async def cancel_booking(self, booking_id: int) -> Booking:
        async with self._sf() as session:
            booking = await session.scalar(
                select(Booking)
                .where(Booking.id == booking_id)
                .options(
                    selectinload(Booking.slot)
                    .selectinload(Slot.working_day)
                    .selectinload(WorkingDay.slots)
                )
                .with_for_update()
            )
            if booking is None:
                raise BookingNotFoundError("Запись не найдена.")
            if booking.status == BookingStatus.CANCELLED.value:
                return booking
            booking.status = BookingStatus.CANCELLED.value
            await self._free_block(session, booking)
            await session.commit()
        return await self.get_booking(booking_id)

    async def cancel_by_client(self, booking_id: int, user_id: int) -> Booking:
        booking = await self.get_booking(booking_id)
        if booking.telegram_user_id != user_id:
            raise PermissionDeniedError("Это не твоя запись.")
        if booking.status not in LIVE_BOOKING_STATUSES:
            raise ValidationError("Эту запись уже нельзя отменить.")
        if (
            booking.status == BookingStatus.ACTIVE.value
            and self._visit_start(booking) - now_local() < CLIENT_CANCEL_CUTOFF
        ):
            raise ValidationError(
                "Отмена меньше чем за 24 часа до визита — напиши мастеру 🤍"
            )
        return await self.cancel_booking(booking_id)

    async def reschedule(self, booking_id: int, new_slot_id: int) -> Booking:
        now = now_local()
        async with self._sf() as session:
            booking = await session.scalar(
                select(Booking)
                .where(Booking.id == booking_id)
                .options(
                    selectinload(Booking.slot)
                    .selectinload(Slot.working_day)
                    .selectinload(WorkingDay.slots)
                )
                .with_for_update()
            )
            if booking is None:
                raise BookingNotFoundError("Запись не найдена.")
            if booking.status not in LIVE_BOOKING_STATUSES:
                raise ValidationError("Эту запись нельзя перенести.")

            new_slot = await session.scalar(
                select(Slot)
                .where(Slot.id == new_slot_id)
                .options(selectinload(Slot.working_day).selectinload(WorkingDay.slots))
                .with_for_update()
            )
            if new_slot is None:
                raise SlotNotFoundError("Новый слот не найден.")

            new_day = new_slot.working_day
            step = await self._step_for_day(session, new_day)
            need = slots_needed(booking.duration_minutes or step, step)
            new_block = _consecutive_block(new_day.slots, new_slot.id, need)
            if not new_block:
                raise SlotNotFoundError("Новый слот не найден.")

            old_block_ids = {s.id for s in await self._block_slots(session, booking)}
            if len(new_block) < need or not all(
                ScheduleService.is_effectively_free(s, now) or s.id in old_block_ids
                for s in new_block
            ):
                raise SlotNotAvailableError("Новое время уже занято.")

            await self._free_block(session, booking)
            booking.slot_id = new_block[0].id
            booking.slot = new_block[0]
            # The visit moved: previously sent reminders no longer apply.
            booking.reminded_24h = False
            booking.reminded_2h = False

            if booking.status == BookingStatus.ACTIVE.value:
                await self._apply_block_status(
                    session, booking, SlotStatus.BOOKED.value, clear_hold=True
                )
            else:
                hold_until = now + timedelta(
                    minutes=self._settings.slot_hold_minutes
                )
                for slot_in_block in new_block:
                    slot_in_block.status = SlotStatus.HELD.value
                    slot_in_block.held_by_user_id = booking.telegram_user_id
                    slot_in_block.held_until = hold_until

            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise _map_booking_conflict(exc) from exc

        return await self.get_booking(booking_id)

    # --- queries -------------------------------------------------------

    async def get_booking(self, booking_id: int) -> Booking:
        async with self._sf() as session:
            booking = await session.scalar(
                self._booking_query().where(Booking.id == booking_id)
            )
            if booking is None:
                raise BookingNotFoundError("Запись не найдена.")
            return booking

    async def list_user_bookings(self, user_id: int) -> list[Booking]:
        async with self._sf() as session:
            rows = await session.scalars(
                self._live_bookings_query().where(
                    Booking.telegram_user_id == user_id,
                    WorkingDay.day >= today(),
                )
            )
            return list(rows)

    async def list_for_working_day(self, working_day_id: int) -> list[Booking]:
        async with self._sf() as session:
            rows = await session.scalars(
                self._live_bookings_query().where(
                    Slot.working_day_id == working_day_id
                )
            )
            return list(rows)

    async def list_booking_days(self) -> list[tuple[int, date, int]]:
        """(working_day_id, date, count) for upcoming days that have bookings.

        Aggregated in SQL: building this from a limited booking list used to
        drop whole days once the salon had more than 50 upcoming bookings.
        """
        async with self._sf() as session:
            rows = await session.execute(
                select(WorkingDay.id, WorkingDay.day, func.count(Booking.id))
                .join(Slot, Slot.working_day_id == WorkingDay.id)
                .join(Booking, Booking.slot_id == Slot.id)
                .where(
                    WorkingDay.day >= today(),
                    Booking.status.in_(LIVE_BOOKING_STATUSES),
                )
                .group_by(WorkingDay.id, WorkingDay.day)
                .order_by(WorkingDay.day)
            )
            return [(day_id, day, count) for day_id, day, count in rows]

    @staticmethod
    def _booking_query():
        """Booking with its slot and day loaded — enough to render any card."""
        return select(Booking).options(
            selectinload(Booking.slot).selectinload(Slot.working_day)
        )

    @staticmethod
    def _live_bookings_query():
        return (
            select(Booking)
            .join(Slot, Booking.slot_id == Slot.id)
            .join(WorkingDay, Slot.working_day_id == WorkingDay.id)
            .where(Booking.status.in_(LIVE_BOOKING_STATUSES))
            .options(selectinload(Booking.slot).selectinload(Slot.working_day))
            .order_by(WorkingDay.day, Slot.start_time)
        )

    # --- reminders / housekeeping --------------------------------------

    async def due_reminders(self) -> tuple[list[Booking], list[Booking]]:
        """Return (need_24h, need_2h) active bookings."""
        now = now_local()
        async with self._sf() as session:
            items = list(
                await session.scalars(
                    select(Booking)
                    .join(Slot, Booking.slot_id == Slot.id)
                    .join(WorkingDay, Slot.working_day_id == WorkingDay.id)
                    .where(
                        Booking.status == BookingStatus.ACTIVE.value,
                        WorkingDay.day >= today(),
                    )
                    .options(
                        selectinload(Booking.slot).selectinload(Slot.working_day)
                    )
                )
            )
        need_24: list[Booking] = []
        need_2: list[Booking] = []
        for booking in items:
            delta = self._visit_start(booking) - now
            if not booking.reminded_24h and (
                timedelta(hours=23) <= delta <= timedelta(hours=25)
            ):
                need_24.append(booking)
            if not booking.reminded_2h and (
                timedelta(hours=1, minutes=45) <= delta <= timedelta(hours=2, minutes=15)
            ):
                need_2.append(booking)
        return need_24, need_2

    async def mark_reminded(self, booking_id: int, *, kind: str) -> None:
        column = {"24h": "reminded_24h", "2h": "reminded_2h"}.get(kind)
        if column is None:
            raise ValidationError(f"Unknown reminder kind: {kind}")
        async with self._sf() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking_id)
                .values(**{column: True})
                .execution_options(synchronize_session=False)
            )
            await session.commit()

    async def settle_past_bookings(self) -> int:
        """Mark finished visits completed and expire stale pending ones."""
        now = now_local()
        async with self._sf() as session:
            bookings = list(
                await session.scalars(
                    select(Booking)
                    .join(Slot, Booking.slot_id == Slot.id)
                    .join(WorkingDay, Slot.working_day_id == WorkingDay.id)
                    .where(
                        Booking.status.in_(LIVE_BOOKING_STATUSES),
                        WorkingDay.day <= today(),
                    )
                    .options(
                        selectinload(Booking.slot)
                        .selectinload(Slot.working_day)
                        .selectinload(WorkingDay.slots)
                    )
                )
            )
            settled = 0
            for booking in bookings:
                step = await self._step_for_day(session, booking.slot.working_day)
                if self._visit_end(booking, step) > now:
                    continue
                booking.status = (
                    BookingStatus.COMPLETED.value
                    if booking.status == BookingStatus.ACTIVE.value
                    else BookingStatus.CANCELLED.value
                )
                await self._apply_block_status(
                    session, booking, SlotStatus.FREE.value, clear_hold=True
                )
                settled += 1
            if settled:
                await session.commit()
            return settled


def _consecutive_block(slots: list[Slot], start_slot_id: int, need: int) -> list[Slot]:
    """`need` slots starting at `start_slot_id`, in time order. [] if not found."""
    ordered = sorted(slots, key=lambda s: s.start_time)
    index = next((i for i, s in enumerate(ordered) if s.id == start_slot_id), None)
    if index is None:
        return []
    return ordered[index : index + need]


def _map_booking_conflict(exc: IntegrityError) -> Exception:
    """Translate a unique-index violation into the right domain error."""
    detail = str(getattr(exc, "orig", exc))
    if "uq_live_booking_user" in detail:
        return AlreadyHasBookingError(
            "У тебя уже есть активная запись. "
            "Сначала отмени её или дождись визита."
        )
    return SlotNotAvailableError("Это время уже недоступно. Выбери другое окошко.")
