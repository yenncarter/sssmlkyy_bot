"""Logging middleware."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger("beauty_bot.middleware")


class LoggingMiddleware(BaseMiddleware):
    """Log incoming updates with duration."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start = time.monotonic()
        user_id = _user_id(event)
        kind = type(event).__name__
        detail = _detail(event)
        logger.debug("← %s user=%s %s", kind, user_id, detail)
        try:
            return await handler(event, data)
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug("→ %s user=%s in %.0fms", kind, user_id, elapsed_ms)


def _user_id(event: TelegramObject) -> str:
    if isinstance(event, (Message, CallbackQuery)) and event.from_user:
        return str(event.from_user.id)
    return "?"


def _detail(event: TelegramObject) -> str:
    if isinstance(event, CallbackQuery):
        return f"cb={event.data!r}"
    if isinstance(event, Message):
        if event.text:
            return f"text={event.text[:40]!r}"
        return f"content={event.content_type}"
    return ""
