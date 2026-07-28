"""Throttling — soft rate-limit with TTL cleanup."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from config.constants import (
    THROTTLE_BURST,
    THROTTLE_MIN_INTERVAL,
    THROTTLE_REFILL_SECONDS,
    THROTTLE_TTL_SECONDS,
)
from presentation.texts.messages import THROTTLE


@dataclass(slots=True)
class _Budget:
    tokens: float
    updated_at: float


class ThrottlingMiddleware(BaseMiddleware):
    """Drop rapid-fire spam without punishing normal UX.

    Two independent limits, because they solve different problems:

    * `min_interval` swallows accidental double taps on the same button;
    * a token bucket bounds the *sustained* rate. Every screen costs database
      work on a single-writer SQLite file, so an unbounded stream of taps from
      one chat would otherwise degrade the bot for everyone else.
    """

    def __init__(
        self,
        min_interval: float = THROTTLE_MIN_INTERVAL,
        burst: int = THROTTLE_BURST,
        refill_seconds: float = THROTTLE_REFILL_SECONDS,
        ttl: float = THROTTLE_TTL_SECONDS,
    ) -> None:
        self._min_interval = min_interval
        self._burst = max(1, burst)
        self._refill = max(0.05, refill_seconds)
        self._ttl = ttl
        self._budgets: dict[int, _Budget] = {}
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

        if not self._allow(uid, now):
            await _feedback(target, data)
            return None

        return await handler(event, data)

    def _allow(self, uid: int, now: float) -> bool:
        budget = self._budgets.get(uid)
        if budget is None:
            self._budgets[uid] = _Budget(tokens=self._burst - 1, updated_at=now)
            return True

        elapsed = now - budget.updated_at
        if elapsed < self._min_interval:
            return False

        budget.tokens = min(self._burst, budget.tokens + elapsed / self._refill)
        budget.updated_at = now
        if budget.tokens < 1:
            return False
        budget.tokens -= 1
        return True

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self._ttl:
            return
        self._last_cleanup = now
        cutoff = now - self._ttl
        stale = [uid for uid, b in self._budgets.items() if b.updated_at < cutoff]
        for uid in stale:
            del self._budgets[uid]


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
        # Stop the spinner; a throttled tap needs no explanation.
        with suppress(TelegramAPIError):
            await event.answer()
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
    except TelegramAPIError:
        pass
