"""Reply keyboard — Start at the bottom."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from presentation.texts.messages import BTN_START

START_BUTTON_TEXT = BTN_START
# Legacy label still present on old reply keyboards in existing chats
LEGACY_START_BUTTON_TEXT = "✨  Старт"
START_BUTTON_ALIASES = frozenset({START_BUTTON_TEXT, LEGACY_START_BUTTON_TEXT})


def start_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=START_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Нажми «Старт»",
    )


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
