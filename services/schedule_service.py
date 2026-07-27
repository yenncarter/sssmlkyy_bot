"""Schedule and booking domain services."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from math import ceil
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from config.settings import Settings
from db.models import Booking, Slot, WorkSettings, WorkingDay
from domain.dates import (
    SAMARA_TZ,
    combine_datetime,
    format_date,
    format_date_short,
    format_time,
    today,
)
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
from domain.services_catalog import Service, get_service


DEFAULT_OPEN = time(10, 0)
DEFAULT_CLOSE = time(22, 0)
DEFAULT_SLOT_MINUTES = 60
# Hot paths call cleanup often; scheduler does a full pass every 2 min.
_HOLD_CLEANUP_MIN_INTERVAL = 45.0
_PAST_PURGE_MIN_INTERVAL = 60.0


def _utcnow() -> datetime:
    """«Now» on the bot clock (Moscow / phone time)."""
    return datetime.now(tz=SAMARA_TZ)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=SAMARA_TZ)
    return dt.astimezone(SAMARA_TZ)


def generate_slot_times(
    open_time: time,
    close_time: time,
    slot_minutes: int,
) -> list[time]:
    """Starts from open until the last start strictly before close."""
    if slot_minutes < 15:
        raise ValidationError("Шаг слота минимум 15 минут.")
    if open_time >= close_time:
        raise ValidationError("Время открытия должно быть раньше закрытия.")

    times: list[time] = []
    cursor = datetime.combine(date.today(), open_time)
    end = datetime.combine(date.today(), close_time)
    while cursor < end:
        times.append(cursor.time())
        cursor += timedelta(minutes=slot_minutes)
    if not times:
        raise ValidationError("В этом диапазоне не получается ни одного слота.")
    return times


class ScheduleService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._settings = settings
        self._last_hold_cleanup = 0.0
        self._last_past_purge = 0.0

    async def get_work_settings(self) -> WorkSettings:
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
                await session.refresh(row)
            return row

    async def set_work_settings(
        self,
        open_time: time,
        close_time: time,
        slot_minutes: int,
    ) -> WorkSettings:
        generate_slot_times(open_time, close_time, slot_minutes)  # validate
        async with self._sf() as session:
            row = await session.get(WorkSettings, 1)
            if row is None:
                row = WorkSettings(id=1)
                session.add(row)
            row.open_time = open_time
            row.close_time = close_time
            row.slot_minutes = slot_minutes
            await session.commit()
            await session.refresh(row)
            return row

    async def _effective_hours(
        self,
        day: WorkingDay | None = None,
    ) -> tuple[time, time, int]:
        ws = await self.get_work_settings()
        if day is None:
            return ws.open_time, ws.close_time, ws.slot_minutes
        return (
            day.open_time or ws.open_time,
            day.close_time or ws.close_time,
            day.slot_minutes or ws.slot_minutes,
        )

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
            existing = await session.scalar(
                select(WorkingDay).where(WorkingDay.day == day).options(
                    selectinload(WorkingDay.slots)
                )
            )
            if existing is not None:
                # Do not merge default hours into an existing day (would corrupt
                # custom day hours). Caller treats this as "already exists".
                raise DuplicateSlotError("Этот день уже есть в графике.")

            existing = WorkingDay(
                day=day,
                open_time=open_time,
                close_time=close_time,
                slot_minutes=slot_minutes,
            )
            session.add(existing)
            await session.flush()

            for t in unique_times:
                session.add(
                    Slot(
                        working_day_id=existing.id,
                        start_time=t,
                        status=SlotStatus.FREE.value,
                    )
                )
            day_id = existing.id
            await session.commit()

        async with self._sf() as session:
            result = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            assert result is not None
            return result

    async def add_day_from_defaults(self, day: date) -> WorkingDay:
        open_t, close_t, step = await self._effective_hours()
        times = generate_slot_times(open_t, close_t, step)
        return await self.add_day_with_times(day, times)

    async def fill_days(
        self,
        days: list[date],
        *,
        weekdays_only: bool = False,
    ) -> tuple[int, int]:
        """Create days with default hours. Returns (created, skipped)."""
        created = 0
        skipped = 0
        for day in days:
            if weekdays_only and day.weekday() >= 5:
                continue
            if day < today():
                continue
            try:
                await self.add_day_from_defaults(day)
                created += 1
            except DuplicateSlotError:
                skipped += 1
            except ValidationError:
                skipped += 1
        return created, skipped

    async def fill_next_n_days(self, n: int, *, weekdays_only: bool = False) -> tuple[int, int]:
        start = today()
        days = [start + timedelta(days=i) for i in range(n)]
        return await self.fill_days(days, weekdays_only=weekdays_only)

    async def fill_rest_of_month(self, *, weekdays_only: bool = False) -> tuple[int, int]:
        start = today()
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        days: list[date] = []
        cur = start
        while cur <= end:
            days.append(cur)
            cur += timedelta(days=1)
        return await self.fill_days(days, weekdays_only=weekdays_only)

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
            day = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            if day is None:
                raise DayNotFoundError("День не найден.")

            day.open_time = open_time
            day.close_time = close_time
            day.slot_minutes = slot_minutes

            if rebuild_free_slots:
                keep_times = {
                    s.start_time
                    for s in day.slots
                    if s.status in {SlotStatus.BOOKED.value, SlotStatus.HELD.value}
                }
                for s in list(day.slots):
                    if s.status == SlotStatus.FREE.value:
                        await session.delete(s)
                await session.flush()
                for t in times:
                    if t in keep_times:
                        continue
                    session.add(
                        Slot(
                            working_day_id=day.id,
                            start_time=t,
                            status=SlotStatus.FREE.value,
                        )
                    )
            await session.commit()
            day_id = day.id

        async with self._sf() as session:
            result = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            assert result is not None
            return result

    async def clear_day_override(self, day_id: int) -> WorkingDay:
        """Reset day to global defaults and rebuild free slots."""
        ws = await self.get_work_settings()
        times = generate_slot_times(ws.open_time, ws.close_time, ws.slot_minutes)
        async with self._sf() as session:
            day = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            if day is None:
                raise DayNotFoundError("День не найден.")
            day.open_time = None
            day.close_time = None
            day.slot_minutes = None
            keep = {
                s.start_time
                for s in day.slots
                if s.status in {SlotStatus.BOOKED.value, SlotStatus.HELD.value}
            }
            for s in list(day.slots):
                if s.status == SlotStatus.FREE.value:
                    await session.delete(s)
            await session.flush()
            for t in times:
                if t in keep:
                    continue
                session.add(
                    Slot(
                        working_day_id=day.id,
                        start_time=t,
                        status=SlotStatus.FREE.value,
                    )
                )
            await session.commit()
            out_id = day.id

        return await self.get_day(out_id)

    async def get_day(self, day_id: int) -> WorkingDay:
        async with self._sf() as session:
            day = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            if day is None:
                raise DayNotFoundError("День не найден.")
            return day

    async def list_upcoming_days(self, limit: int = 60) -> list[WorkingDay]:
        await self.purge_past_days()
        await self.release_expired_holds()
        async with self._sf() as session:
            result = await session.scalars(
                select(WorkingDay)
                .where(WorkingDay.day >= today())
                .options(selectinload(WorkingDay.slots))
                .order_by(WorkingDay.day)
                .limit(limit)
            )
            return list(result)

    async def list_days_with_free_slots(self) -> list[tuple[WorkingDay, int]]:
        await self.purge_past_days()
        await self.release_expired_holds()
        async with self._sf() as session:
            days = list(
                await session.scalars(
                    select(WorkingDay)
                    .where(WorkingDay.day >= today())
                    .options(selectinload(WorkingDay.slots))
                    .order_by(WorkingDay.day)
                )
            )
            out: list[tuple[WorkingDay, int]] = []
            now = _utcnow()
            for day in days:
                free = sum(
                    1
                    for s in day.slots
                    if self._is_bookable_slot(s, day.day, now)
                )
                if free:
                    out.append((day, free))
            return out

    async def free_slots_for_day(self, day_id: int) -> list[Slot]:
        await self.release_expired_holds()
        async with self._sf() as session:
            day = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            if day is None:
                raise DayNotFoundError("День не найден.")
            if day.day < today():
                return []
            now = _utcnow()
            return [
                s for s in day.slots if self._is_bookable_slot(s, day.day, now)
            ]

    async def purge_past_days(self, *, force: bool = False) -> int:
        """Drop days before today. Keeps bot calendar in sync with the wall clock."""
        now_mono = monotonic()
        if (
            not force
            and now_mono - self._last_past_purge < _PAST_PURGE_MIN_INTERVAL
        ):
            return 0
        self._last_past_purge = now_mono

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
            if not days:
                return 0

            live = {
                BookingStatus.PENDING_PAYMENT.value,
                BookingStatus.ACTIVE.value,
            }
            removed = 0
            for day in days:
                has_live = any(
                    b.status in live
                    for s in day.slots
                    for b in s.bookings
                )
                if has_live:
                    # Past active booking is a data anomaly — leave for manual review.
                    continue
                for slot in day.slots:
                    for booking in list(slot.bookings):
                        await session.delete(booking)
                await session.delete(day)
                removed += 1
            if removed:
                await session.commit()
            return removed

    async def delete_day(self, day_id: int) -> None:
        async with self._sf() as session:
            day = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            if day is None:
                raise DayNotFoundError("День не найден.")
            # BOOKED or HELD: slots are FK-restricted by live bookings — refuse cleanly
            busy = {
                SlotStatus.BOOKED.value,
                SlotStatus.HELD.value,
            }
            if any(s.status in busy for s in day.slots):
                raise ValidationError(
                    "Нельзя удалить день с записями или бронью. Сначала отмени их."
                )
            await session.delete(day)
            await session.commit()

    async def release_expired_holds(self, *, force: bool = False) -> int:
        now_mono = monotonic()
        if (
            not force
            and now_mono - self._last_hold_cleanup < _HOLD_CLEANUP_MIN_INTERVAL
        ):
            return 0
        self._last_hold_cleanup = now_mono

        now = _utcnow()
        async with self._sf() as session:
            slots = list(
                await session.scalars(
                    select(Slot).where(Slot.status == SlotStatus.HELD.value)
                )
            )
            if not slots:
                return 0

            expired_ids = [
                slot.id
                for slot in slots
                if (held := _aware(slot.held_until)) is None or held < now
            ]
            if not expired_ids:
                return 0

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

            by_id = {s.id: s for s in slots}
            for slot_id in expired_ids:
                slot = by_id[slot_id]
                slot.status = SlotStatus.FREE.value
                slot.held_by_user_id = None
                slot.held_until = None

            await session.commit()
            return len(expired_ids)

    @staticmethod
    def _is_effectively_free(slot: Slot, now: datetime) -> bool:
        if slot.status == SlotStatus.FREE.value:
            return True
        if slot.status == SlotStatus.HELD.value:
            held_until = _aware(slot.held_until)
            return held_until is not None and held_until < now
        return False

    @classmethod
    def _is_bookable_slot(cls, slot: Slot, day: date, now: datetime) -> bool:
        """Free (or expired hold) and not in the past by bot clock."""
        if not cls._is_effectively_free(slot, now):
            return False
        start = combine_datetime(day, slot.start_time)
        return start > now

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
                raise ValidationError("Этот слот занят записью — сначала отмени запись.")
            await session.commit()
            await session.refresh(slot)
            return slot

    async def set_prepayment_amount(self, amount: str) -> WorkSettings:
        normalized = _normalize_prepayment_amount(amount)
        async with self._sf() as session:
            row = await session.get(WorkSettings, 1)
            if row is None:
                raise ValidationError("Настройки не найдены.")
            row.prepayment_amount = normalized
            await session.commit()
            await session.refresh(row)
            return row

# --- Booking ---


class BookingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._settings = settings
        self._last_settle = 0.0

    @staticmethod
    def _slots_needed(duration_minutes: int, step: int) -> int:
        return max(1, ceil(duration_minutes / step))

    async def user_has_active_booking(self, user_id: int) -> bool:
        await self.settle_past_bookings()
        async with self._sf() as session:
            q = select(func.count()).select_from(Booking).where(
                Booking.telegram_user_id == user_id,
                Booking.status.in_(
                    [
                        BookingStatus.PENDING_PAYMENT.value,
                        BookingStatus.ACTIVE.value,
                    ]
                ),
            )
            return bool(await session.scalar(q))

    async def free_starts_for_service(self, day_id: int, service: Service) -> list[Slot]:
        await ScheduleService(self._sf, self._settings).release_expired_holds()
        async with self._sf() as session:
            day = await session.scalar(
                select(WorkingDay)
                .where(WorkingDay.id == day_id)
                .options(selectinload(WorkingDay.slots))
            )
            if day is None:
                raise DayNotFoundError("День не найден.")
            ws = await session.get(WorkSettings, 1)
            step = day.slot_minutes or (ws.slot_minutes if ws else 60)
            need = self._slots_needed(service.duration_minutes, step)
            now = _utcnow()
            slots = sorted(day.slots, key=lambda s: s.start_time)
            starts: list[Slot] = []
            for i in range(len(slots) - need + 1):
                block = slots[i : i + need]
                if all(ScheduleService._is_effectively_free(s, now) for s in block):
                    starts.append(block[0])
            return starts

    async def hold_slot(
        self,
        *,
        slot_id: int,
        user_id: int,
        username: str | None,
        full_name: str,
        phone: str,
        service: Service | None = None,
    ) -> Booking:
        if await self.user_has_active_booking(user_id):
            raise AlreadyHasBookingError(
                "У тебя уже есть активная запись. Сначала отмени её или дождись визита."
            )

        hold_until = _utcnow() + timedelta(minutes=self._settings.slot_hold_minutes)
        async with self._sf() as session:
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
                raise SlotNotAvailableError(
                    "Этот день уже прошёл. Выбери другую дату."
                )
            ws = await session.get(WorkSettings, 1)
            step = day.slot_minutes or (ws.slot_minutes if ws else 60)
            duration = service.duration_minutes if service else step
            need = self._slots_needed(duration, step)
            now = _utcnow()
            ordered = sorted(day.slots, key=lambda s: s.start_time)
            try:
                idx = next(i for i, s in enumerate(ordered) if s.id == slot.id)
            except StopIteration as exc:
                raise SlotNotFoundError("Слот не найден.") from exc
            block = ordered[idx : idx + need]
            if len(block) < need or not all(
                ScheduleService._is_bookable_slot(s, day.day, now) for s in block
            ):
                raise SlotNotAvailableError(
                    "Это время уже недоступно. Выбери другое окошко."
                )

            for s in block:
                stale = await session.scalar(
                    select(Booking).where(
                        Booking.slot_id == s.id,
                        Booking.status == BookingStatus.PENDING_PAYMENT.value,
                    )
                )
                if stale:
                    stale.status = BookingStatus.CANCELLED.value
                s.status = SlotStatus.HELD.value
                s.held_by_user_id = user_id
                s.held_until = hold_until

            booking = Booking(
                slot_id=block[0].id,
                telegram_user_id=user_id,
                username=username,
                full_name=full_name.strip(),
                phone=phone.strip(),
                service_code=service.code.value if service else None,
                service_title=service.title if service else None,
                duration_minutes=duration,
                status=BookingStatus.PENDING_PAYMENT.value,
            )
            session.add(booking)
            await session.commit()
            await session.refresh(booking)
            return await self.get_booking(booking.id)

    async def confirm_with_receipt(
        self,
        *,
        booking_id: int,
        user_id: int,
        receipt_file_id: str,
        receipt_file_type: str,
    ) -> Booking:
        async with self._sf() as session:
            booking = await session.scalar(
                select(Booking)
                .where(Booking.id == booking_id)
                .options(
                    selectinload(Booking.slot)
                    .selectinload(Slot.working_day)
                    .selectinload(WorkingDay.slots),
                )
                .with_for_update()
            )
            if booking is None or booking.telegram_user_id != user_id:
                raise BookingNotFoundError("Запись не найдена.")
            if booking.status != BookingStatus.PENDING_PAYMENT.value:
                raise ValidationError("Эта запись уже обработана.")

            slot = booking.slot
            now = _utcnow()
            held_until = _aware(slot.held_until)
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

            booking.status = BookingStatus.ACTIVE.value
            booking.receipt_file_id = receipt_file_id
            booking.receipt_file_type = receipt_file_type
            booking.confirmed_at = now
            await self._apply_block_status(
                session, booking, SlotStatus.BOOKED.value, clear_hold=True
            )
            await session.commit()
            await session.refresh(booking)
            return await self.get_booking(booking.id)

    async def _block_slots(self, session: AsyncSession, booking: Booking) -> list[Slot]:
        day = booking.slot.working_day
        if day.slots is None or not day.slots:
            await session.refresh(day, attribute_names=["slots"])
        ws = await session.get(WorkSettings, 1)
        step = day.slot_minutes or (ws.slot_minutes if ws else 60)
        duration = booking.duration_minutes or step
        need = self._slots_needed(duration, step)
        ordered = sorted(day.slots, key=lambda s: s.start_time)
        idx = next(i for i, s in enumerate(ordered) if s.id == booking.slot_id)
        return ordered[idx : idx + need]

    async def _apply_block_status(
        self,
        session: AsyncSession,
        booking: Booking,
        status: str,
        *,
        clear_hold: bool,
    ) -> None:
        # ensure relationships loaded
        if booking.slot is None or booking.slot.working_day is None:
            booking = await session.scalar(
                select(Booking)
                .where(Booking.id == booking.id)
                .options(selectinload(Booking.slot).selectinload(Slot.working_day).selectinload(WorkingDay.slots))
            )
            assert booking is not None
        elif not booking.slot.working_day.slots:
            await session.refresh(booking.slot.working_day, attribute_names=["slots"])

        for s in await self._block_slots(session, booking):
            s.status = status
            if clear_hold:
                s.held_by_user_id = None
                s.held_until = None
            else:
                s.held_by_user_id = booking.telegram_user_id

    async def _free_block(self, session: AsyncSession, booking: Booking) -> None:
        await self._apply_block_status(
            session, booking, SlotStatus.FREE.value, clear_hold=True
        )

    async def cancel_booking(self, booking_id: int, *, by_admin: bool = False) -> Booking:
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
            await session.refresh(booking)
            return booking

    async def cancel_by_client(self, booking_id: int, user_id: int) -> Booking:
        booking = await self.get_booking(booking_id)
        if booking.telegram_user_id != user_id:
            raise PermissionDeniedError("Это не твоя запись.")
        if booking.status not in {
            BookingStatus.ACTIVE.value,
            BookingStatus.PENDING_PAYMENT.value,
        }:
            raise ValidationError("Эту запись уже нельзя отменить.")
        visit = combine_datetime(booking.slot.working_day.day, booking.slot.start_time)
        if booking.status == BookingStatus.ACTIVE.value and visit - _utcnow() < timedelta(hours=24):
            raise ValidationError(
                "Отмена меньше чем за 24 часа до визита — напиши мастеру 🤍"
            )
        return await self.cancel_booking(booking_id)

    async def list_user_bookings(self, user_id: int) -> list[Booking]:
        async with self._sf() as session:
            result = await session.scalars(
                select(Booking)
                .join(Slot)
                .join(WorkingDay)
                .where(
                    Booking.telegram_user_id == user_id,
                    Booking.status.in_(
                        [BookingStatus.ACTIVE.value, BookingStatus.PENDING_PAYMENT.value]
                    ),
                    WorkingDay.day >= today(),
                )
                .options(selectinload(Booking.slot).selectinload(Slot.working_day))
                .order_by(WorkingDay.day, Slot.start_time)
            )
            return list(result)

    async def list_booking_days(self) -> list[tuple[int, date, int]]:
        """(working_day_id, date, bookings_count) for upcoming days with bookings."""
        items = await self.list_upcoming()
        counts: dict[int, tuple[date, int]] = {}
        for b in items:
            day = b.slot.working_day
            prev = counts.get(day.id)
            counts[day.id] = (day.day, (prev[1] if prev else 0) + 1)
        return sorted(
            [(did, d, c) for did, (d, c) in counts.items()],
            key=lambda x: x[1],
        )

    async def list_for_working_day(self, working_day_id: int) -> list[Booking]:
        async with self._sf() as session:
            result = await session.scalars(
                select(Booking)
                .join(Slot)
                .where(
                    Slot.working_day_id == working_day_id,
                    Booking.status.in_(
                        [BookingStatus.ACTIVE.value, BookingStatus.PENDING_PAYMENT.value]
                    ),
                )
                .options(selectinload(Booking.slot).selectinload(Slot.working_day))
                .order_by(Slot.start_time)
            )
            return list(result)

    async def list_for_date(self, day: date) -> list[Booking]:
        async with self._sf() as session:
            result = await session.scalars(
                select(Booking)
                .join(Slot)
                .join(WorkingDay)
                .where(
                    WorkingDay.day == day,
                    Booking.status.in_(
                        [BookingStatus.ACTIVE.value, BookingStatus.PENDING_PAYMENT.value]
                    ),
                )
                .options(selectinload(Booking.slot).selectinload(Slot.working_day))
                .order_by(Slot.start_time)
            )
            return list(result)

    async def due_reminders(self) -> tuple[list[Booking], list[Booking]]:
        """Return (need_24h, need_2h) active bookings."""
        now = _utcnow()
        async with self._sf() as session:
            items = list(
                await session.scalars(
                    select(Booking)
                    .join(Slot)
                    .join(WorkingDay)
                    .where(
                        Booking.status == BookingStatus.ACTIVE.value,
                        WorkingDay.day >= today(),
                    )
                    .options(selectinload(Booking.slot).selectinload(Slot.working_day))
                )
            )
        need_24: list[Booking] = []
        need_2: list[Booking] = []
        for b in items:
            visit = combine_datetime(b.slot.working_day.day, b.slot.start_time)
            delta = visit - now
            if not b.reminded_24h and timedelta(hours=23) <= delta <= timedelta(hours=25):
                need_24.append(b)
            if not b.reminded_2h and timedelta(hours=1, minutes=45) <= delta <= timedelta(hours=2, minutes=15):
                need_2.append(b)
        return need_24, need_2

    async def mark_reminded(self, booking_id: int, *, kind: str) -> None:
        async with self._sf() as session:
            booking = await session.get(Booking, booking_id)
            if booking is None:
                return
            if kind == "24h":
                booking.reminded_24h = True
            elif kind == "2h":
                booking.reminded_2h = True
            await session.commit()

    async def settle_past_bookings(self, *, force: bool = False) -> int:
        """Mark past visits completed / expire stale pending — unblock clients."""
        now_mono = monotonic()
        if (
            not force
            and now_mono - self._last_settle < _PAST_PURGE_MIN_INTERVAL
        ):
            return 0
        self._last_settle = now_mono

        now = _utcnow()
        async with self._sf() as session:
            bookings = list(
                await session.scalars(
                    select(Booking)
                    .where(
                        Booking.status.in_(
                            [
                                BookingStatus.PENDING_PAYMENT.value,
                                BookingStatus.ACTIVE.value,
                            ]
                        )
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
                start = combine_datetime(
                    booking.slot.working_day.day, booking.slot.start_time
                )
                if start > now:
                    continue
                if booking.status == BookingStatus.ACTIVE.value:
                    booking.status = BookingStatus.COMPLETED.value
                else:
                    booking.status = BookingStatus.CANCELLED.value
                await self._apply_block_status(
                    session,
                    booking,
                    SlotStatus.FREE.value,
                    clear_hold=True,
                )
                settled += 1
            if settled:
                await session.commit()
            return settled

    async def reschedule(self, booking_id: int, new_slot_id: int) -> Booking:
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
            if booking.status not in {
                BookingStatus.ACTIVE.value,
                BookingStatus.PENDING_PAYMENT.value,
            }:
                raise ValidationError("Эту запись нельзя перенести.")

            new_slot = await session.scalar(
                select(Slot)
                .where(Slot.id == new_slot_id)
                .options(selectinload(Slot.working_day).selectinload(WorkingDay.slots))
                .with_for_update()
            )
            if new_slot is None:
                raise SlotNotFoundError("Новый слот не найден.")

            now = _utcnow()
            ws = await session.get(WorkSettings, 1)
            new_day = new_slot.working_day
            step = new_day.slot_minutes or (ws.slot_minutes if ws else 60)
            duration = booking.duration_minutes or step
            need = self._slots_needed(duration, step)
            ordered = sorted(new_day.slots, key=lambda s: s.start_time)
            try:
                idx = next(i for i, s in enumerate(ordered) if s.id == new_slot.id)
            except StopIteration as exc:
                raise SlotNotFoundError("Новый слот не найден.") from exc
            new_block = ordered[idx : idx + need]

            def _slot_free(s: Slot) -> bool:
                if s.status == SlotStatus.FREE.value:
                    return True
                if s.status == SlotStatus.HELD.value:
                    until = _aware(s.held_until)
                    return until is not None and until < now
                return False

            # Allow moving within the same booking's current block
            old_block_ids = {s.id for s in await self._block_slots(session, booking)}
            if len(new_block) < need or not all(
                _slot_free(s) or s.id in old_block_ids for s in new_block
            ):
                raise SlotNotAvailableError("Новое время уже занято.")

            await self._free_block(session, booking)
            booking.slot_id = new_block[0].id
            # refresh relationship for _apply_block_status
            booking.slot = new_block[0]
            if booking.status == BookingStatus.ACTIVE.value:
                await self._apply_block_status(
                    session, booking, SlotStatus.BOOKED.value, clear_hold=True
                )
            else:
                hold_until = now + timedelta(minutes=self._settings.slot_hold_minutes)
                for s in new_block:
                    s.status = SlotStatus.HELD.value
                    s.held_by_user_id = booking.telegram_user_id
                    s.held_until = hold_until

            await session.commit()
            return await self.get_booking(booking.id)

    async def get_booking(self, booking_id: int) -> Booking:
        async with self._sf() as session:
            booking = await session.scalar(
                select(Booking)
                .where(Booking.id == booking_id)
                .options(selectinload(Booking.slot).selectinload(Slot.working_day))
            )
            if booking is None:
                raise BookingNotFoundError("Запись не найдена.")
            return booking

    async def list_upcoming(self, limit: int = 50) -> list[Booking]:
        async with self._sf() as session:
            result = await session.scalars(
                select(Booking)
                .join(Slot)
                .join(WorkingDay)
                .where(
                    Booking.status.in_(
                        [
                            BookingStatus.ACTIVE.value,
                            BookingStatus.PENDING_PAYMENT.value,
                        ]
                    ),
                    WorkingDay.day >= today(),
                )
                .options(selectinload(Booking.slot).selectinload(Slot.working_day))
                .order_by(WorkingDay.day, Slot.start_time)
                .limit(limit)
            )
            return list(result)


def format_booking_status(status: str) -> str:
    labels = {
        BookingStatus.PENDING_PAYMENT.value: "ждёт оплату",
        BookingStatus.ACTIVE.value: "подтверждена",
        BookingStatus.CANCELLED.value: "отменена",
        BookingStatus.COMPLETED.value: "завершена",
        BookingStatus.NO_SHOW.value: "не пришла",
    }
    return labels.get(status, status)


def format_admin_booking_card(booking: Booking) -> str:
    """Compact card for master: who / when / contact. No service leftovers."""
    import html

    day = booking.slot.working_day.day
    t = booking.slot.start_time
    uname = (
        f"@{html.escape(booking.username)}"
        if booking.username
        else "нет username"
    )
    lines = [
        f"<b>Запись #{booking.id}</b>",
        f"📅 <b>{format_date_short(day)}</b> · {format_time(t)}",
        "",
        f"<b>{html.escape(booking.full_name)}</b>",
        html.escape(booking.phone),
        uname,
    ]
    if booking.status == BookingStatus.PENDING_PAYMENT.value:
        lines.extend(["", "⏳ ждёт оплату"])
    return "\n".join(lines)


def format_client_booking_card(booking: Booking) -> str:
    day = booking.slot.working_day.day
    t = booking.slot.start_time
    lines = [f"✨ <b>{format_date_short(day)} · {format_time(t)}</b>"]
    if booking.status == BookingStatus.PENDING_PAYMENT.value:
        lines.append("ждёт оплату")
    return "\n".join(lines)


def format_booking_card(booking: Booking) -> str:
    """Admin-oriented card (kept for callers)."""
    return format_admin_booking_card(booking)


def parse_times_line(raw: str) -> list[time]:
    """Parse '10:00, 11:30, 13:00' or multiline times."""
    parts = [p.strip() for p in raw.replace(";", ",").replace("\n", ",").split(",")]
    times: list[time] = []
    for part in parts:
        if not part:
            continue
        try:
            hh, mm = part.split(":")
            times.append(time(int(hh), int(mm)))
        except ValueError as exc:
            raise ValidationError(
                f"Не поняла время «{part}». Формат: 10:00, 11:30, 13:00"
            ) from exc
    return times


def parse_hours_message(raw: str) -> tuple[time, time, int]:
    """
    Parse open–close hours. Slot step is always DEFAULT_SLOT_MINUTES (hourly).
    Formats: 10:00-22:00 | 10:00 22:00
    Trailing numbers (legacy step) are ignored.
    """
    cleaned = raw.strip().lower().replace("–", "-").replace("—", "-")
    parts = cleaned.replace(",", " ").split()
    if not parts:
        raise ValidationError("Формат: <code>10:00-22:00</code>")

    if "-" in parts[0]:
        left, right = parts[0].split("-", 1)
        open_t = parse_times_line(left)[0]
        close_t = parse_times_line(right)[0]
    elif len(parts) >= 2:
        open_t = parse_times_line(parts[0])[0]
        close_t = parse_times_line(parts[1])[0]
    else:
        raise ValidationError("Формат: <code>10:00-22:00</code>")

    step = DEFAULT_SLOT_MINUTES
    generate_slot_times(open_t, close_t, step)
    return open_t, close_t, step


def format_hours(open_t: time, close_t: time, step: int | None = None) -> str:
    return f"{format_time(open_t)}–{format_time(close_t)}"


def _normalize_prepayment_amount(raw: str) -> str:
    """Master types digits only; always store as «N ₽»."""
    text = (raw or "").strip().lower()
    for junk in ("₽", "руб.", "руб", "р.", "р"):
        text = text.replace(junk, "")
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValidationError("Напиши сумму числом — например 500")
    value = int(digits)
    if value < 1 or value > 1_000_000:
        raise ValidationError("Сумма должна быть от 1 до 1 000 000")
    pretty = f"{value:,}".replace(",", " ")
    return f"{pretty} ₽"


def parse_day(raw: str) -> date:
    """Accept DD.MM, DD.MM.YYYY, YYYY-MM-DD.

    DD.MM is stored as a real calendar date with year:
    this year if still upcoming, otherwise next year (bot clock).
    Explicit years in the past are rejected.
    """
    raw = raw.strip()
    parsed: date | None = None
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue

    if parsed is None:
        try:
            day_n, month_n = raw.split(".", 1)
            d = int(day_n)
            m = int(month_n)
            now = today()
            candidate = date(now.year, m, d)
            if candidate < now:
                candidate = date(now.year + 1, m, d)
            parsed = candidate
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                "Дата в формате <code>01.10</code> или <code>01.10.2026</code>"
            ) from exc

    if parsed < today():
        raise ValidationError(
            f"Дата {parsed.day:02d}.{parsed.month:02d}.{parsed.year} уже прошла."
        )
    return parsed


def parse_days_column(raw: str) -> tuple[list[date], list[str]]:
    """
    Parse one or many dates from a column / list.
    Returns (valid_dates, bad_tokens).
    """
    import re

    chunks = [c for c in re.split(r"[\s,;]+", raw.strip()) if c]
    days: list[date] = []
    seen: set[date] = set()
    errors: list[str] = []
    for part in chunks:
        try:
            d = parse_day(part)
        except ValidationError:
            errors.append(part)
            continue
        if d not in seen:
            seen.add(d)
            days.append(d)
    return days, errors

def normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if len(digits) < 10:
        raise ValidationError("Укажи номер телефона полностью.")
    return digits
