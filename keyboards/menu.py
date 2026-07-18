"""Keyboard labels and builders."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import MenuCallback
from config.constants import CallbackAction
from config.settings import settings


def channel_button() -> InlineKeyboardButton:
    """Only for subscription flow."""
    return InlineKeyboardButton(text="📢  Подписаться", url=settings.channel_link)


def back_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=MenuCallback(action=CallbackAction.BACK).pack(),
    )


def footer_keyboard() -> InlineKeyboardMarkup:
    """Single back button."""
    builder = InlineKeyboardBuilder()
    builder.row(back_button())
    return builder.as_markup()


back_to_menu_keyboard = footer_keyboard


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows = [
        ("💅  Записаться", CallbackAction.BOOK),
        ("🖼  Портфолио", CallbackAction.PORTFOLIO),
        ("💎  Прайс", CallbackAction.PRICE),
        ("✨  О Кайли", CallbackAction.ABOUT),
        ("📍  Контакты", CallbackAction.CONTACTS),
    ]
    for text, action in rows:
        builder.button(text=text, callback_data=MenuCallback(action=action).pack())
    builder.adjust(2, 2, 1)
    return builder.as_markup()
