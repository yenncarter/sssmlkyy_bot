"""Booking contact keyboard."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from keyboards.common import back_button


def booking_contact_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"💬  Написать · {settings.master_name}",
            url=f"https://t.me/{settings.master_username}",
        ),
    )
    builder.row(back_button())
    return builder.as_markup()
