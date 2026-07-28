"""Database health checks with alerts to the master.

The failure mode this exists for: on an ephemeral disk the bot looks perfectly
healthy — it boots, answers, creates an empty schema — and nobody notices the
data is gone until a client asks why her appointment vanished. So every boot
compares reality against what the previous boot saw and says so out loud.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from config.settings import BOTHOST_DATA_DIR, Settings, running_in_container
from db.models import Booking, Slot, WorkingDay, WorkSettings
from domain.dates import format_date_short, format_time, now_local, to_local, today
from domain.enums import BookingStatus, SlotStatus
from domain.slots import DEFAULT_CLOSE, DEFAULT_OPEN, DEFAULT_SLOT_MINUTES
from presentation.texts.alerts import (
    BACKUP_STALE,
    DB_CONFLICT,
    DB_CORRUPT,
    DB_EMPTY,
    DB_SHRANK,
    DB_STATUS,
    DB_STORAGE,
)
from services.alert_service import AlertService
from services.app_state import AppStateStore

logger = logging.getLogger("beauty_bot.db_health")

BOOKINGS_SEEN_KEY = "db.bookings_seen"
LAST_BACKUP_KEY = "db.last_backup_at"

# Below this we assume a young salon, not a data loss.
EMPTY_ALERT_MIN_HISTORY = 3
# Losing more than this share of bookings between boots is not normal usage.
SHRINK_ALERT_RATIO = 0.5
BACKUP_STALE_AFTER = timedelta(days=3)
NEXT_VISITS_LIMIT = 5


@dataclass(frozen=True, slots=True)
class DbReport:
    backend: str
    days: int
    bookings: int
    active: int
    previous_bookings: int
    storage: str | None
    integrity: str | None
    last_backup: datetime | None

    @property
    def healthy(self) -> bool:
        return self.storage is None and self.integrity is None

    def as_log_line(self) -> str:
        return (
            f"БД {self.backend}: дней={self.days}, записей={self.bookings} "
            f"(активных={self.active}), было={self.previous_bookings}"
        )


@dataclass(frozen=True, slots=True)
class NextVisit:
    when: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class BotStatus:
    """Full diagnostic card for /status — read-only, never mutates data."""

    collected_at: datetime
    backend: str
    db_path: str | None
    in_container: bool
    storage: str | None
    integrity: str | None
    days_total: int
    days_upcoming: int
    slots_free: int
    slots_held: int
    slots_booked: int
    slots_blocked: int
    bookings_active: int
    bookings_pending: int
    bookings_cancelled: int
    bookings_completed: int
    bookings_total: int
    previous_bookings: int
    last_backup: datetime | None
    media_cached: int
    open_time: str
    close_time: str
    slot_minutes: int
    prepayment: str
    hold_minutes: int
    admins: int
    next_visits: tuple[NextVisit, ...]

    @property
    def healthy(self) -> bool:
        return self.storage is None and self.integrity is None

    @property
    def problems(self) -> list[str]:
        out: list[str] = []
        if self.storage:
            out.append(self.storage)
        if self.integrity:
            out.append(f"целостность: {self.integrity}")
        if (
            self.bookings_total > 0
            and (
                self.last_backup is None
                or now_local() - self.last_backup >= BACKUP_STALE_AFTER
            )
        ):
            out.append("бэкап устарел или отсутствует")
        if (
            self.previous_bookings >= EMPTY_ALERT_MIN_HISTORY
            and self.bookings_total == 0
        ):
            out.append(f"база пуста, раньше было {self.previous_bookings} записей")
        elif (
            self.previous_bookings >= EMPTY_ALERT_MIN_HISTORY
            and self.bookings_total < self.previous_bookings * SHRINK_ALERT_RATIO
        ):
            out.append(
                f"записей стало меньше: {self.previous_bookings} → {self.bookings_total}"
            )
        return out


class DbHealthService:
    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        state: AppStateStore,
        alerts: AlertService,
    ) -> None:
        self._engine = engine
        self._sf = session_factory
        self._settings = settings
        self._state = state
        self._alerts = alerts

    async def check(
        self,
        *,
        schema_conflicts: list[str] | None = None,
        announce: bool = False,
    ) -> DbReport:
        """Inspect the database, alert on anything alarming, log the rest.

        `announce=True` also sends a status card to the master — used on boot
        so she sees the numbers without opening the hosting panel.
        """
        report = await self._collect()
        logger.info(report.as_log_line())

        if report.storage:
            logger.error("Хранилище БД: %s", report.storage)
            await self._alerts.send("db.storage", DB_STORAGE.format(detail=report.storage))

        if report.integrity:
            logger.error("Целостность БД: %s", report.integrity)
            await self._alerts.send(
                "db.corrupt", DB_CORRUPT.format(detail=report.integrity), force=True
            )

        for conflict in schema_conflicts or []:
            await self._alerts.send("db.conflict", DB_CONFLICT.format(detail=conflict))

        await self._alert_on_data_loss(report)
        await self._alert_on_stale_backup(report)
        if announce:
            await self._announce(report)
        await self._state.set_int(BOOKINGS_SEEN_KEY, report.bookings)
        return report

    async def diagnose(self, *, media_cached: int = 0) -> BotStatus:
        """Build a full status card. Does not send alerts and does not write state."""
        settings = self._settings
        storage = self._check_storage()
        integrity = await self._check_integrity()
        previous = await self._state.get_int(BOOKINGS_SEEN_KEY)
        last_backup = _parse_timestamp(await self._state.get(LAST_BACKUP_KEY))

        days_total = days_upcoming = 0
        slots = {s.value: 0 for s in SlotStatus}
        by_status = {s.value: 0 for s in BookingStatus}
        open_t, close_t, step = DEFAULT_OPEN, DEFAULT_CLOSE, DEFAULT_SLOT_MINUTES
        prepayment = settings.prepayment_amount
        next_visits: list[NextVisit] = []

        try:
            async with self._sf() as session:
                days_total = await session.scalar(
                    select(func.count()).select_from(WorkingDay)
                ) or 0
                days_upcoming = await session.scalar(
                    select(func.count())
                    .select_from(WorkingDay)
                    .where(WorkingDay.day >= today())
                ) or 0

                for status, count in (
                    await session.execute(
                        select(Slot.status, func.count())
                        .group_by(Slot.status)
                    )
                ).all():
                    slots[str(status)] = int(count)

                for status, count in (
                    await session.execute(
                        select(Booking.status, func.count())
                        .group_by(Booking.status)
                    )
                ).all():
                    by_status[str(status)] = int(count)

                ws = await session.get(WorkSettings, 1)
                if ws is not None:
                    open_t, close_t = ws.open_time, ws.close_time
                    step = ws.slot_minutes or DEFAULT_SLOT_MINUTES
                    prepayment = ws.prepayment_amount or prepayment

                upcoming = list(
                    await session.scalars(
                        select(Booking)
                        .join(Slot, Booking.slot_id == Slot.id)
                        .join(WorkingDay, Slot.working_day_id == WorkingDay.id)
                        .where(
                            Booking.status.in_(
                                (
                                    BookingStatus.ACTIVE.value,
                                    BookingStatus.PENDING_PAYMENT.value,
                                )
                            ),
                            WorkingDay.day >= today(),
                        )
                        .options(
                            selectinload(Booking.slot).selectinload(Slot.working_day)
                        )
                        .order_by(WorkingDay.day, Slot.start_time)
                        .limit(NEXT_VISITS_LIMIT)
                    )
                )
                for booking in upcoming:
                    day = booking.slot.working_day.day
                    start = booking.slot.start_time
                    label = (
                        "ждёт оплату"
                        if booking.status == BookingStatus.PENDING_PAYMENT.value
                        else "активна"
                    )
                    next_visits.append(
                        NextVisit(
                            when=f"{format_date_short(day)} · {format_time(start)}",
                            name=booking.full_name,
                            status=label,
                        )
                    )
        except SQLAlchemyError:
            logger.exception("Не удалось собрать диагностику")

        db_path = settings.sqlite_path
        return BotStatus(
            collected_at=now_local(),
            backend=settings.database_url.split("://")[0],
            db_path=str(db_path) if db_path else None,
            in_container=running_in_container(),
            storage=storage,
            integrity=integrity,
            days_total=days_total,
            days_upcoming=days_upcoming,
            slots_free=slots.get(SlotStatus.FREE.value, 0),
            slots_held=slots.get(SlotStatus.HELD.value, 0),
            slots_booked=slots.get(SlotStatus.BOOKED.value, 0),
            slots_blocked=slots.get(SlotStatus.BLOCKED.value, 0),
            bookings_active=by_status.get(BookingStatus.ACTIVE.value, 0),
            bookings_pending=by_status.get(BookingStatus.PENDING_PAYMENT.value, 0),
            bookings_cancelled=by_status.get(BookingStatus.CANCELLED.value, 0),
            bookings_completed=by_status.get(BookingStatus.COMPLETED.value, 0),
            bookings_total=sum(by_status.values()),
            previous_bookings=previous,
            last_backup=last_backup,
            media_cached=media_cached,
            open_time=format_time(open_t),
            close_time=format_time(close_t),
            slot_minutes=step,
            prepayment=prepayment,
            hold_minutes=settings.slot_hold_minutes,
            admins=len(settings.admin_telegram_ids),
            next_visits=tuple(next_visits),
        )

    async def _announce(self, report: DbReport) -> None:
        backup = (
            report.last_backup.strftime("%d.%m.%Y %H:%M")
            if report.last_backup is not None
            else "ещё не было"
        )
        await self._alerts.send(
            "db.status",
            DB_STATUS.format(
                days=report.days,
                bookings=report.bookings,
                active=report.active,
                storage=report.storage or "ок",
                integrity=report.integrity or "ок",
                backup=backup,
            ),
            force=True,
        )

    async def _alert_on_data_loss(self, report: DbReport) -> None:
        previous = report.previous_bookings
        if previous < EMPTY_ALERT_MIN_HISTORY:
            return
        if report.bookings == 0:
            logger.error("БД пуста, а раньше было записей: %s", previous)
            await self._alerts.send(
                "db.empty", DB_EMPTY.format(expected=previous), force=True
            )
            return
        if report.bookings < previous * SHRINK_ALERT_RATIO:
            logger.error("Записей стало меньше: %s → %s", previous, report.bookings)
            await self._alerts.send(
                "db.shrank",
                DB_SHRANK.format(expected=previous, actual=report.bookings),
            )

    async def _alert_on_stale_backup(self, report: DbReport) -> None:
        if report.bookings == 0:
            return  # nothing to lose yet
        last = report.last_backup
        if last is not None and now_local() - last < BACKUP_STALE_AFTER:
            return
        detail = (
            "последний бэкап: " + last.strftime("%d.%m.%Y %H:%M")
            if last is not None
            else "бэкапов ещё не было"
        )
        logger.warning("Бэкап устарел: %s", detail)
        await self._alerts.send("db.backup_stale", BACKUP_STALE.format(detail=detail))

    async def _collect(self) -> DbReport:
        days = bookings = active = 0
        try:
            async with self._sf() as session:
                days = await session.scalar(
                    select(func.count()).select_from(WorkingDay)
                ) or 0
                bookings = await session.scalar(
                    select(func.count()).select_from(Booking)
                ) or 0
                active = await session.scalar(
                    select(func.count())
                    .select_from(Booking)
                    .where(Booking.status == BookingStatus.ACTIVE.value)
                ) or 0
        except SQLAlchemyError:
            logger.exception("Не удалось прочитать статистику БД")

        raw_backup = await self._state.get(LAST_BACKUP_KEY)
        return DbReport(
            backend=self._settings.database_url.split("://")[0],
            days=days,
            bookings=bookings,
            active=active,
            previous_bookings=await self._state.get_int(BOOKINGS_SEEN_KEY),
            storage=self._check_storage(),
            integrity=await self._check_integrity(),
            last_backup=_parse_timestamp(raw_backup),
        )

    def _check_storage(self) -> str | None:
        """Is the SQLite file where it can actually survive a restart?"""
        db_path = self._settings.sqlite_path
        if db_path is None:
            return None  # managed backend: not our problem

        directory = db_path.parent
        if not directory.is_dir():
            return f"каталог {directory} не существует"
        if not os.access(directory, os.W_OK):
            return f"каталог {directory} недоступен для записи"
        if running_in_container() and BOTHOST_DATA_DIR not in db_path.parents:
            return (
                f"файл БД лежит вне постоянного тома: {db_path} "
                f"(ожидается внутри {BOTHOST_DATA_DIR})"
            )
        return None

    async def _check_integrity(self) -> str | None:
        if self._settings.sqlite_path is None:
            return None
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(text("PRAGMA integrity_check"))
                rows = [str(row[0]) for row in result.fetchall()]
        except SQLAlchemyError as exc:
            return f"проверка не выполнена: {exc}"
        if rows == ["ok"]:
            return None
        return "; ".join(rows[:3])


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return to_local(datetime.fromisoformat(raw))
    except ValueError:
        logger.warning("Некорректная дата бэкапа в app_state: %r", raw)
        return None
