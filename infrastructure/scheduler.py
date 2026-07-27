"""Background jobs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from domain.dates import SAMARA_TZ
from services.notify_service import NotifyService
from services.schedule_service import BookingService, ScheduleService

logger = logging.getLogger("beauty_bot.scheduler")


def setup_scheduler(
    schedule: ScheduleService,
    notify: NotifyService,
    bookings: BookingService | None = None,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=str(SAMARA_TZ))

    async def cleanup_holds() -> None:
        try:
            n = await schedule.release_expired_holds(force=True)
            if n:
                logger.info("Released %s expired holds", n)
        except Exception:
            logger.exception("Hold cleanup failed")

    async def cleanup_past_days() -> None:
        try:
            settled = 0
            if bookings is not None:
                settled = await bookings.settle_past_bookings(force=True)
            n = await schedule.purge_past_days(force=True)
            if settled or n:
                logger.info(
                    "Past cleanup: settled=%s purged_days=%s", settled, n
                )
        except Exception:
            logger.exception("Past days cleanup failed")

    async def monthly_reminder() -> None:
        try:
            await notify.monthly_schedule_reminder()
        except Exception:
            logger.exception("Monthly reminder failed")

    async def visit_reminders() -> None:
        if bookings is None:
            return
        try:
            need_24, need_2 = await bookings.due_reminders()
            for b in need_24:
                if await notify.client_visit_reminder(b, hours=24):
                    await bookings.mark_reminded(b.id, kind="24h")
            for b in need_2:
                if await notify.client_visit_reminder(b, hours=2):
                    await bookings.mark_reminded(b.id, kind="2h")
        except Exception:
            logger.exception("Visit reminders failed")

    scheduler.add_job(
        cleanup_holds,
        IntervalTrigger(minutes=2),
        id="cleanup_holds",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_past_days,
        CronTrigger(hour=0, minute=5, timezone=str(SAMARA_TZ)),
        id="cleanup_past_days",
        replace_existing=True,
    )
    # Also sweep periodically in case the bot was offline at midnight
    scheduler.add_job(
        cleanup_past_days,
        IntervalTrigger(hours=6),
        id="cleanup_past_days_interval",
        replace_existing=True,
    )
    scheduler.add_job(
        monthly_reminder,
        CronTrigger(day=1, hour=10, minute=0, timezone=str(SAMARA_TZ)),
        id="monthly_schedule_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        visit_reminders,
        IntervalTrigger(minutes=10),
        id="visit_reminders",
        replace_existing=True,
    )
    return scheduler
