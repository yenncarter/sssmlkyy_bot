"""Centralized error handling."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message, TelegramObject

from texts.messages import ERROR_GENERIC, STALE_BUTTON

logger = logging.getLogger("beauty_bot.error")


class ErrorMiddleware(BaseMiddleware):
    """Catch exceptions and reply safely."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramRetryAfter as exc:
            await _reply(event, f"⏳ Секундочку… подожди {exc.retry_after} сек.")
        except TelegramBadRequest as exc:
            logger.warning("BadRequest: %s", exc)
            if "query is too old" in str(exc).lower():
                await _reply(event, STALE_BUTTON)
            else:
                await _reply(event, ERROR_GENERIC)
        except Exception as exc:
            logger.exception("Unhandled: %s", exc)
            await _reply(event, ERROR_GENERIC)
        return None


async def _reply(event: TelegramObject, text: str) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            try:
                await event.message.answer(text)
            except TelegramBadRequest:
                pass
    elif isinstance(event, Message):
        await event.answer(text)
