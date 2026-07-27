"""Centralized error handling."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from domain.exceptions import AppError, StaleCallbackError
from presentation.keyboards.menu import footer_keyboard
from presentation.texts.messages import ERROR_GENERIC, STALE_BUTTON
from presentation.ui.screens import prompt_screen, show_text

logger = logging.getLogger("beauty_bot.error")


class ErrorMiddleware(BaseMiddleware):
    """Catch exceptions and reply safely without leaking internals."""

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
            logger.exception("Unhandled: %s", exc)
            await _reply(event, ERROR_GENERIC, data)
        return None


async def _reply(
    event: TelegramObject,
    text: str,
    data: dict[str, Any] | None = None,
) -> None:
    target = event
    if isinstance(event, Update):
        target = event.callback_query or event.message or event

    if isinstance(target, CallbackQuery):
        try:
            await target.answer()
        except TelegramBadRequest:
            pass
        if target.message:
            try:
                await show_text(target, text, footer_keyboard())
                return
            except Exception:
                try:
                    await target.message.answer(text)
                except TelegramBadRequest:
                    pass
        return

    if isinstance(target, Message):
        state: FSMContext | None = (data or {}).get("state")
        if state is not None:
            try:
                await prompt_screen(
                    target, text, footer_keyboard(), state=state
                )
                return
            except Exception:
                pass
        try:
            await target.answer(text)
        except TelegramBadRequest:
            pass
