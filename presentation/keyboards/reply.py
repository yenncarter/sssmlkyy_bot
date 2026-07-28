"""Reply keyboard helpers — strip legacy Start bar from existing chats."""

from __future__ import annotations

from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, ReplyKeyboardRemove

from presentation.texts.messages import BTN_START

START_BUTTON_TEXT = BTN_START
# Legacy label still present on old reply keyboards in existing chats
LEGACY_START_BUTTON_TEXT = "✨  Старт"
START_BUTTON_ALIASES = frozenset({START_BUTTON_TEXT, LEGACY_START_BUTTON_TEXT})


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


async def strip_reply_keyboard(message: Message) -> None:
    """Hide a sticky reply keyboard (Telegram only drops it via an explicit remove)."""
    with suppress(TelegramBadRequest):
        remove_msg = await message.answer("·", reply_markup=remove_reply_keyboard())
        with suppress(TelegramBadRequest):
            await remove_msg.delete()
