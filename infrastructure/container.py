"""Application DI container."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config.settings import Settings
from db.session import create_engine, create_session_factory, init_db
from services.media_cache import MediaCache
from services.notify_service import NotifyService
from services.portfolio_service import PortfolioService
from services.schedule_service import BookingService, ScheduleService
from services.session import SessionService
from services.subscription_service import SubscriptionService


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    bot: Bot
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    subscription: SubscriptionService
    portfolio: PortfolioService
    session: SessionService
    media_cache: MediaCache
    schedule: ScheduleService
    bookings: BookingService
    notify: NotifyService

    @classmethod
    async def create(cls, settings: Settings, bot: Bot) -> AppContainer:
        engine = create_engine(settings.database_url)
        await init_db(engine)
        session_factory = create_session_factory(engine)
        media_cache = MediaCache()
        return cls(
            settings=settings,
            bot=bot,
            engine=engine,
            session_factory=session_factory,
            subscription=SubscriptionService(bot, settings),
            portfolio=PortfolioService(settings.portfolio_dir, media_cache),
            session=SessionService(),
            media_cache=media_cache,
            schedule=ScheduleService(session_factory, settings),
            bookings=BookingService(session_factory, settings),
            notify=NotifyService(bot, settings),
        )

    async def shutdown(self) -> None:
        await self.engine.dispose()
