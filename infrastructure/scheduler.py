"""Background jobs.

The scheduler is the single owner of housekeeping cadence: request handlers no
longer trigger sweeps, so a burst of traffic cannot turn into a burst of
full-table maintenance queries.

Every job is wrapped by :func:`_guarded`, because an unhandled exception inside
an APScheduler job is invisible by default — the bot keeps answering while
reminders or backups silently stop happening.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from domain.dates import LOCAL_TZ
from presentation.texts.alerts import JOB_FAILED
from services.alert_service import AlertService
from services.backup_service import BackupService
from services.db_health import DbHealthService
from services.notify_service import NotifyService
from services.schedule_service import BookingService, ScheduleService

logger = logging.getLogger("beauty_bot.scheduler")

HOLD_SWEEP_MINUTES = 2
PAST_SWEEP_HOURS = 6
REMINDER_SWEEP_MINUTES = 10
BACKUP_HOUR = 3
BACKUP_MINUTE = 30
HEALTH_HOUR = 9


def _guarded(
    name: str,
    job: Callable[[], Awaitable[None]],
    alerts: AlertService,
) -> Callable[[], Awaitable[None]]:
    """Log and report a failing job instead of losing it silently."""

    async def runner() -> None:
        try:
            await job()
        except Exception as exc:
            logger.exception("Задача %s упала", name)
            await alerts.send(
                f"job.{name}",
                JOB_FAILED.format(job=name, error=type(exc).__name__),
            )

    runner.__name__ = f"job_{name}"
    return runner


def setup_scheduler(
    schedule: ScheduleService,
    notify: NotifyService,
    bookings: BookingService,
    alerts: AlertService,
    db_health: DbHealthService,
    backup: BackupService,
) -> AsyncIOScheduler:
    timezone = str(LOCAL_TZ)
    scheduler = AsyncIOScheduler(timezone=timezone)

    async def cleanup_holds() -> None:
        released = await schedule.release_expired_holds()
        if released:
            logger.info("Освобождено просроченных броней: %s", released)

    async def cleanup_past() -> None:
        settled = await bookings.settle_past_bookings()
        purged = await schedule.purge_past_days()
        if settled or purged:
            logger.info(
                "Прошедшее закрыто: записей=%s, пустых дней удалено=%s",
                settled,
                purged,
            )

    async def monthly_reminder() -> None:
        await notify.monthly_schedule_reminder()

    async def visit_reminders() -> None:
        need_24, need_2 = await bookings.due_reminders()
        for booking, kind, hours in (
            *((b, "24h", 24) for b in need_24),
            *((b, "2h", 2) for b in need_2),
        ):
            # False means "retry later" — do not mark it as sent.
            if await notify.client_visit_reminder(booking, hours=hours):
                await bookings.mark_reminded(booking.id, kind=kind)

    async def nightly_backup() -> None:
        await backup.run()

    async def daily_health() -> None:
        await db_health.check()

    jobs: tuple[tuple[str, Callable[[], Awaitable[None]], object], ...] = (
        ("cleanup_holds", cleanup_holds, IntervalTrigger(minutes=HOLD_SWEEP_MINUTES)),
        (
            "cleanup_past_days",
            cleanup_past,
            CronTrigger(hour=0, minute=5, timezone=timezone),
        ),
        # Also sweep periodically in case the bot was offline at midnight.
        (
            "cleanup_past_days_interval",
            cleanup_past,
            IntervalTrigger(hours=PAST_SWEEP_HOURS),
        ),
        (
            "monthly_schedule_reminder",
            monthly_reminder,
            CronTrigger(day=1, hour=10, minute=0, timezone=timezone),
        ),
        (
            "visit_reminders",
            visit_reminders,
            IntervalTrigger(minutes=REMINDER_SWEEP_MINUTES),
        ),
        (
            "nightly_backup",
            nightly_backup,
            CronTrigger(hour=BACKUP_HOUR, minute=BACKUP_MINUTE, timezone=timezone),
        ),
        (
            "daily_db_health",
            daily_health,
            CronTrigger(hour=HEALTH_HOUR, minute=0, timezone=timezone),
        ),
    )

    for job_id, job, trigger in jobs:
        scheduler.add_job(
            _guarded(job_id, job, alerts),
            trigger,
            id=job_id,
            replace_existing=True,
        )
    return scheduler
