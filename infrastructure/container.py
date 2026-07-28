"""Application DI container."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config.settings import Settings
from db.session import create_engine, create_session_factory, init_db
from services.alert_service import AlertService
from services.app_state import AppStateStore
from services.backup_service import BackupService
from services.db_health import DbHealthService, DbReport
from services.media_cache import MediaCache
from services.notify_service import NotifyService
from services.portfolio_service import PortfolioService
from services.schedule_service import BookingService, ScheduleService
from services.session import SessionService

logger = logging.getLogger("beauty_bot.container")


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    bot: Bot
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    state: AppStateStore
    alerts: AlertService
    portfolio: PortfolioService
    session: SessionService
    media_cache: MediaCache
    schedule: ScheduleService
    bookings: BookingService
    notify: NotifyService
    db_health: DbHealthService
    backup: BackupService
    schema_conflicts: list[str]

    @classmethod
    async def create(cls, settings: Settings, bot: Bot) -> AppContainer:
        engine = create_engine(settings.database_url)
        schema_conflicts = await init_db(engine)
        session_factory = create_session_factory(engine)

        state = AppStateStore(session_factory)
        alerts = AlertService(bot, settings)
        media_cache = MediaCache(session_factory)
        cached = await media_cache.load()
        logger.info("Кэш file_id загружен: %s записей", cached)

        return cls(
            settings=settings,
            bot=bot,
            engine=engine,
            session_factory=session_factory,
            state=state,
            alerts=alerts,
            portfolio=PortfolioService(settings.portfolio_dir, media_cache),
            session=SessionService(),
            media_cache=media_cache,
            schedule=ScheduleService(session_factory, settings),
            bookings=BookingService(session_factory, settings),
            notify=NotifyService(bot, settings),
            db_health=DbHealthService(engine, session_factory, settings, state, alerts),
            backup=BackupService(bot, settings, state, alerts),
            schema_conflicts=schema_conflicts,
        )

    async def startup_checks(self) -> DbReport:
        """Report on the database before serving anyone."""
        return await self.db_health.check(
            schema_conflicts=self.schema_conflicts,
            announce=True,
        )

    async def shutdown(self) -> None:
        await self.engine.dispose()
