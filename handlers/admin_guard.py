"""Denial responses for admin entry points.

`handlers.admin` is gated by a router-level `IsAdmin` filter, so non-admin
updates fall through to this router. It exists to keep the previous UX (an
explicit refusal instead of a silently spinning button) without repeating an
access check inside every admin handler.

Must be included immediately after the admin router.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from callbacks.factories import AdminCallback
from presentation.texts.messages import ADMIN_DENIED, ADMIN_NO_ACCESS

router = Router(name="admin_guard")
logger = logging.getLogger("beauty_bot.admin")


@router.message(Command("admin"))
async def admin_denied(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    logger.warning("Отказ в доступе к /admin для %s", user_id)
    await message.answer(ADMIN_DENIED)


@router.message(Command("status"))
async def status_denied(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    logger.warning("Отказ в доступе к /status для %s", user_id)
    await message.answer(ADMIN_DENIED)


@router.callback_query(AdminCallback.filter())
async def admin_callback_denied(callback: CallbackQuery) -> None:
    logger.warning(
        "Отказ в доступе к админ-колбэку для %s: %s",
        callback.from_user.id,
        callback.data,
    )
    await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
