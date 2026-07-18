"""Logging middleware."""

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger("beauty_bot.middleware")


class LoggingMiddleware(BaseMiddleware):
    """Log incoming updates."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start = time.monotonic()
        user_id = _user_id(event)
        logger.info("Update: %s user=%s", type(event).__name__, user_id)
        try:
            return await handler(event, data)
        finally:
            logger.debug("Handled in %.0fms", (time.monotonic() - start) * 1000)


def _user_id(event: TelegramObject) -> str:
    if isinstance(event, (Message, CallbackQuery)) and event.from_user:
        return str(event.from_user.id)
    return "?"
