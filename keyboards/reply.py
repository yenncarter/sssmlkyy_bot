"""Reply keyboard — large Start button at the bottom."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

START_BUTTON_TEXT = "✨  Старт"


def start_reply_keyboard() -> ReplyKeyboardMarkup:
    """Single large Start button."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=START_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Нажми «Старт», чтобы открыть меню",
    )


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
