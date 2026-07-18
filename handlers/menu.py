"""Main menu handlers."""

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from callbacks.factories import MenuCallback
from config.constants import CallbackAction
from handlers.ui import show_main_menu
from keyboards.common import footer_keyboard
from texts.messages import ABOUT, CONTACTS, PRICE
from utils.text_context import format_message

router = Router(name="menu")


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.BACK))
async def back_to_menu(callback: CallbackQuery) -> None:
    """Return to welcome menu with cover photo."""
    await callback.answer()
    await show_main_menu(callback)


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.PRICE))
async def show_price(callback: CallbackQuery) -> None:
    await _show_section(callback, format_message(PRICE))


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.ABOUT))
async def show_about(callback: CallbackQuery) -> None:
    await _show_section(callback, format_message(ABOUT))


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.CONTACTS))
async def show_contacts(callback: CallbackQuery) -> None:
    await _show_section(callback, format_message(CONTACTS))


async def _show_section(callback: CallbackQuery, text: str) -> None:
    await callback.answer()
    markup = footer_keyboard()

    if callback.message.photo:
        await _delete_safe(callback)
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


async def _delete_safe(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
