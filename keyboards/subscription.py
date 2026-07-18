"""Subscription keyboard — channel only here."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import SubscriptionCallback
from config.constants import CallbackAction
from keyboards.common import back_button, channel_button


def subscription_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(channel_button())
    builder.row(
        InlineKeyboardButton(
            text="✅  Я подписалась",
            callback_data=SubscriptionCallback(action=CallbackAction.CHECK_SUB).pack(),
        ),
    )
    builder.row(back_button())
    return builder.as_markup()
