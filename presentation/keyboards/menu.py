"""Main menu and shared buttons."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import MenuCallback
from config.settings import Settings, settings as default_settings
from domain.enums import CallbackAction
from presentation.texts.messages import (
    BTN_ABOUT,
    BTN_BACK_MENU,
    BTN_BOOK,
    BTN_CHANNEL,
    BTN_CONTACTS,
    BTN_FAQ,
    BTN_FAQ_BACK,
    BTN_MY_BOOKINGS,
    BTN_PORTFOLIO,
    BTN_PRICE,
    BTN_SUBSCRIBE,
)


def channel_button(settings: Settings | None = None) -> InlineKeyboardButton:
    cfg = settings or default_settings
    return InlineKeyboardButton(text=BTN_SUBSCRIBE, url=cfg.channel_link)


def menu_channel_button(settings: Settings | None = None) -> InlineKeyboardButton:
    cfg = settings or default_settings
    return InlineKeyboardButton(text=BTN_CHANNEL, url=cfg.channel_link)


def back_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=BTN_BACK_MENU,
        callback_data=MenuCallback(action=CallbackAction.BACK).pack(),
    )


def footer_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(back_button())
    return builder.as_markup()


def main_menu_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Primary CTA full-width, then comfortable 2-column rows."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=BTN_BOOK,
            callback_data=MenuCallback(action=CallbackAction.BOOK).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=BTN_MY_BOOKINGS,
            callback_data=MenuCallback(action=CallbackAction.MY_BOOKINGS).pack(),
        ),
        InlineKeyboardButton(
            text=BTN_PORTFOLIO,
            callback_data=MenuCallback(action=CallbackAction.PORTFOLIO).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=BTN_PRICE,
            callback_data=MenuCallback(action=CallbackAction.PRICE).pack(),
        ),
        InlineKeyboardButton(
            text=BTN_FAQ,
            callback_data=MenuCallback(action=CallbackAction.FAQ).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=BTN_ABOUT,
            callback_data=MenuCallback(action=CallbackAction.ABOUT).pack(),
        ),
        InlineKeyboardButton(
            text=BTN_CONTACTS,
            callback_data=MenuCallback(action=CallbackAction.CONTACTS).pack(),
        ),
    )
    builder.row(menu_channel_button(settings))
    return builder.as_markup()


def faq_hub_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📅 Запись и предоплата",
            callback_data=MenuCallback(action=CallbackAction.FAQ_BOOKING).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🌸 Визит и подготовка",
            callback_data=MenuCallback(action=CallbackAction.FAQ_VISIT).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="✨ Гарантия и отмена",
            callback_data=MenuCallback(action=CallbackAction.FAQ_RULES).pack(),
        ),
    )
    builder.row(back_button())
    return builder.as_markup()


def faq_section_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=BTN_FAQ_BACK,
            callback_data=MenuCallback(action=CallbackAction.FAQ).pack(),
        ),
    )
    return builder.as_markup()
