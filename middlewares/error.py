"""Centralized error handling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from domain.exceptions import AppError, StaleCallbackError
from presentation.keyboards.menu import footer_keyboard
from presentation.texts.alerts import CRASH
from presentation.texts.messages import ERROR_GENERIC, STALE_BUTTON
from presentation.ui.screens import prompt_screen, show_text
from services.alert_service import AlertService

logger = logging.getLogger("beauty_bot.error")


class ErrorMiddleware(BaseMiddleware):
    """Catch exceptions and reply safely without leaking internals."""

    def __init__(self, alerts: AlertService | None = None) -> None:
        self._alerts = alerts

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramRetryAfter as exc:
            await _reply(
                event,
                f"Подожди {exc.retry_after} сек. и попробуй ещё раз.",
                data,
            )
        except StaleCallbackError:
            await _reply(event, STALE_BUTTON, data)
        except TelegramForbiddenError:
            # User blocked the bot mid-flow: nothing to reply to.
            logger.info("Чат недоступен, обработчик прерван")
        except AppError as exc:
            logger.warning("AppError: %s", exc.message)
            await _reply(event, exc.message or ERROR_GENERIC, data)
        except TelegramBadRequest as exc:
            logger.warning("BadRequest: %s", exc)
            text = str(exc).lower()
            if "query is too old" in text or "query id is invalid" in text:
                await _reply(event, STALE_BUTTON, data)
            else:
                await _reply(event, ERROR_GENERIC, data)
        except Exception as exc:
            # CancelledError is a BaseException — shutdown is never swallowed here.
            update_id = _update_id(event)
            logger.exception("Unhandled (update=%s): %s", update_id, exc)
            await _reply(event, ERROR_GENERIC, data)
            await self._alert(exc, update_id)
        return None

    async def _alert(self, exc: Exception, update_id: int | str) -> None:
        """Tell the master the bot stumbled — logs alone are never read in time."""
        if self._alerts is None:
            return
        try:
            await self._alerts.send(
                "crash",
                CRASH.format(error=type(exc).__name__, update_id=update_id),
            )
        except TelegramAPIError:
            logger.warning("Не удалось отправить алерт о падении", exc_info=True)


def _update_id(event: TelegramObject) -> int | str:
    """Correlates the traceback with the raw update in the Bothost logs."""
    return event.update_id if isinstance(event, Update) else "?"


async def _reply(
    event: TelegramObject,
    text: str,
    data: dict[str, Any] | None = None,
) -> None:
    target = event
    if isinstance(event, Update):
        target = event.callback_query or event.message or event

    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):
            await target.answer()
        if target.message is None:
            return
        try:
            await show_text(target, text, footer_keyboard())
            return
        except TelegramAPIError:
            logger.warning("Не удалось показать экран ошибки", exc_info=True)
        # Last resort: `target.message` may be an InaccessibleMessage stub, so
        # go through the bot with the chat id instead of Message.answer().
        if target.bot is not None:
            with suppress(TelegramAPIError):
                await target.bot.send_message(target.message.chat.id, text)
        return

    if isinstance(target, Message):
        state: FSMContext | None = (data or {}).get("state")
        if state is not None:
            try:
                await prompt_screen(
                    target, text, footer_keyboard(), state=state
                )
                return
            except TelegramAPIError:
                logger.warning("Не удалось показать экран ошибки", exc_info=True)
        with suppress(TelegramAPIError):
            await target.answer(text)
