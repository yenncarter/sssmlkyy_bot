"""Throttling — light protection, fast UX."""

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config.constants import THROTTLE_RATE


class ThrottlingMiddleware(BaseMiddleware):
    """Soft rate-limit for spam only."""

    def __init__(self) -> None:
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        uid = _user_id(event)
        if uid is None:
            return await handler(event, data)

        now = time.monotonic()
        if now - self._last.get(uid, 0) < THROTTLE_RATE:
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None

        self._last[uid] = now
        return await handler(event, data)


def _user_id(event: TelegramObject) -> int | None:
    if isinstance(event, (Message, CallbackQuery)) and event.from_user:
        return event.from_user.id
    return None
