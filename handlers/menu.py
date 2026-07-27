"""Main menu handlers."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from callbacks.factories import MenuCallback
from config.settings import Settings
from domain.enums import CallbackAction
from presentation.keyboards.menu import (
    faq_hub_keyboard,
    faq_section_keyboard,
    footer_keyboard,
)
from presentation.texts.context import format_message
from presentation.texts.messages import (
    ABOUT,
    CONTACTS,
    FAQ,
    FAQ_BOOKING,
    FAQ_RULES,
    FAQ_VISIT,
    PRICE,
)
from presentation.ui.screens import show_main_menu, show_text
from services.media_cache import MediaCache
from services.schedule_service import BookingService

router = Router(name="menu")


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.BACK))
async def back_to_menu(
    callback: CallbackQuery,
    settings: Settings,
    media_cache: MediaCache,
    state: FSMContext,
    bookings: BookingService,
) -> None:
    await callback.answer()
    data = await state.get_data()
    booking_id = data.get("booking_id")
    if booking_id:
        try:
            await bookings.cancel_booking(booking_id)
        except Exception:
            pass
    await state.clear()
    await show_main_menu(callback, settings, media_cache)


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.PRICE))
async def show_price(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show_text(callback, format_message(PRICE, settings), footer_keyboard())


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.FAQ))
async def show_faq(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show_text(callback, format_message(FAQ, settings), faq_hub_keyboard())


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.FAQ_BOOKING))
async def show_faq_booking(
    callback: CallbackQuery, settings: Settings, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    await show_text(
        callback, format_message(FAQ_BOOKING, settings), faq_section_keyboard()
    )


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.FAQ_VISIT))
async def show_faq_visit(
    callback: CallbackQuery, settings: Settings, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    await show_text(
        callback, format_message(FAQ_VISIT, settings), faq_section_keyboard()
    )


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.FAQ_RULES))
async def show_faq_rules(
    callback: CallbackQuery, settings: Settings, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    await show_text(
        callback, format_message(FAQ_RULES, settings), faq_section_keyboard()
    )


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.ABOUT))
async def show_about(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show_text(callback, format_message(ABOUT, settings), footer_keyboard())


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.CONTACTS))
async def show_contacts(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show_text(callback, format_message(CONTACTS, settings), footer_keyboard())
