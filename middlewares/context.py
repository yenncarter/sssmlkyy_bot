"""Bot context middleware — inject container services."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from infrastructure.container import AppContainer


class BotContextMiddleware(BaseMiddleware):
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        c = self._container
        data["container"] = c
        data["settings"] = c.settings
        data["subscription"] = c.subscription
        data["portfolio"] = c.portfolio
        data["session"] = c.session
        data["media_cache"] = c.media_cache
        data["schedule"] = c.schedule
        data["bookings"] = c.bookings
        data["notify"] = c.notify
        return await handler(event, data)
