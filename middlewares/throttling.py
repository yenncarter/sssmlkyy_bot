"""Throttling — soft rate-limit with TTL cleanup."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from config.constants import THROTTLE_RATE, THROTTLE_TTL_SECONDS
from presentation.texts.messages import THROTTLE


class ThrottlingMiddleware(BaseMiddleware):
    """Drop rapid-fire spam without punishing normal UX."""

    def __init__(
        self,
        rate: float = THROTTLE_RATE,
        ttl: float = THROTTLE_TTL_SECONDS,
    ) -> None:
        self._rate = rate
        self._ttl = ttl
        self._last: dict[int, float] = {}
        self._last_cleanup = time.monotonic()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        target = _unwrap(event)
        uid = _user_id(target)
        if uid is None:
            return await handler(event, data)

        now = time.monotonic()
        self._maybe_cleanup(now)

        if now - self._last.get(uid, 0.0) < self._rate:
            await _feedback(target, data)
            return None

        self._last[uid] = now
        return await handler(event, data)

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self._ttl:
            return
        self._last_cleanup = now
        cutoff = now - self._ttl
        stale = [uid for uid, ts in self._last.items() if ts < cutoff]
        for uid in stale:
            del self._last[uid]


def _unwrap(event: TelegramObject) -> TelegramObject:
    if isinstance(event, Update):
        return (
            event.callback_query
            or event.message
            or event.edited_message
            or event
        )
    return event


def _user_id(event: TelegramObject) -> int | None:
    if isinstance(event, (Message, CallbackQuery)) and event.from_user:
        return event.from_user.id
    return None


async def _feedback(event: TelegramObject, data: dict[str, Any]) -> None:
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        return

    if not isinstance(event, Message):
        return

    # Silent drop only for non-FSM spam; FSM text needs a visible cue.
    state: FSMContext | None = data.get("state")
    if state is None:
        return
    try:
        if await state.get_state() is None:
            return
        await event.answer(THROTTLE)
    except Exception:
        pass
