"""Subscription keyboard."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import SubscriptionCallback
from config.settings import Settings
from domain.enums import CallbackAction
from presentation.keyboards.menu import back_button, channel_button
from presentation.texts.messages import BTN_CHECK_SUB


def subscription_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(channel_button(settings))
    builder.row(
        InlineKeyboardButton(
            text=BTN_CHECK_SUB,
            callback_data=SubscriptionCallback(action=CallbackAction.CHECK_SUB).pack(),
        ),
    )
    builder.row(back_button())
    return builder.as_markup()
