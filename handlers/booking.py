"""Booking contact — available only after subscription."""

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from callbacks.factories import MenuCallback, SubscriptionCallback
from config.constants import CallbackAction
from handlers.ui import delete_message_safe
from keyboards.booking import booking_contact_keyboard
from keyboards.subscription import subscription_keyboard
from services.subscription_service import SubscriptionService
from texts.messages import (
    BOOKING_CONTACT,
    SUBSCRIPTION_FAIL,
    SUBSCRIPTION_OK,
    SUBSCRIPTION_REQUIRED,
)
from utils.text_context import format_message

router = Router(name="booking")


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.BOOK))
async def show_booking(
    callback: CallbackQuery,
    subscription: SubscriptionService,
) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    if not await subscription.is_subscribed(user_id):
        await _show_text(
            callback,
            format_message(SUBSCRIPTION_REQUIRED),
            subscription_keyboard(),
        )
        return
    await _send_contact(callback)


@router.callback_query(SubscriptionCallback.filter(F.action == CallbackAction.CHECK_SUB))
async def check_subscription_and_book(
    callback: CallbackQuery,
    subscription: SubscriptionService,
) -> None:
    user_id = callback.from_user.id
    if await subscription.is_subscribed(user_id):
        await callback.answer(SUBSCRIPTION_OK, show_alert=True)
        await _send_contact(callback)
    else:
        await callback.answer(SUBSCRIPTION_FAIL, show_alert=True)
        await _show_text(
            callback,
            format_message(SUBSCRIPTION_REQUIRED),
            subscription_keyboard(),
        )


async def _send_contact(callback: CallbackQuery) -> None:
    await _show_text(
        callback,
        format_message(BOOKING_CONTACT),
        booking_contact_keyboard(),
    )


async def _show_text(callback: CallbackQuery, text: str, markup) -> None:
    if callback.message.photo:
        await delete_message_safe(callback)
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        return

    try:
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
