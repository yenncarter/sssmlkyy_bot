"""Client booking FSM — name → phone → day → time → receipt."""

from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from callbacks.factories import (
    BookCancelCallback,
    BookDayCallback,
    BookNavCallback,
    BookSlotCallback,
    ClientBookingCallback,
    MenuCallback,
)
from config.settings import Settings
from db.models import Booking
from domain.dates import format_date_short, format_time, now_local, to_local
from domain.enums import BookingStatus, CallbackAction
from domain.exceptions import AppError
from domain.parsing import normalize_full_name, normalize_phone
from handlers.filters import HasReceiptTarget
from handlers.states import BookingFSM
from presentation.formatters import format_client_booking_card
from presentation.keyboards.booking import (
    cancel_confirm_keyboard,
    days_keyboard,
    flow_cancel_keyboard,
    flow_nav_keyboard,
    my_bookings_keyboard,
    no_slots_keyboard,
    payment_keyboard,
    slots_keyboard,
)
from presentation.keyboards.menu import footer_keyboard
from presentation.texts.messages import (
    BOOKING_ALREADY_ACTIVE,
    BOOKING_ASK_DAY,
    BOOKING_ASK_NAME,
    BOOKING_ASK_PHONE,
    BOOKING_ASK_TIME,
    BOOKING_CANCELLED_DONE,
    BOOKING_CANCELLED_FLOW,
    BOOKING_CONFIRMED,
    BOOKING_NO_SLOTS,
    BOOKING_PAYMENT,
    BOOKING_RECEIPT_LATE,
    BOOKING_RECEIPT_WAIT,
    CANCEL_CONFIRM,
    MY_BOOKINGS_EMPTY,
    MY_BOOKINGS_HINT,
)
from presentation.ui.screens import prompt_screen, show_screen, show_text
from services.notify_service import NotifyService
from services.schedule_service import BookingService, ScheduleService

router = Router(name="booking")

FLOW_RESET_TEXT = "Сессия записи сброшена. Начни заново через «Записаться»."


def _hold_minutes_left(booking: Booking, fallback: int) -> int:
    """Minutes left on the hold, on the bot clock.

    held_until is written in Europe/Moscow and comes back naive from SQLite —
    reading it as UTC used to inflate the countdown by three hours.
    """
    held_until = to_local(getattr(booking.slot, "held_until", None))
    if held_until is None:
        return fallback
    seconds = (held_until - now_local()).total_seconds()
    return max(1, int(seconds // 60))


def _render_my_bookings(items: list[Booking]) -> str:
    lines = ["<b>Мои записи</b>\n"]
    for booking in items:
        lines.append(format_client_booking_card(booking))
        lines.append("")
    lines.append(MY_BOOKINGS_HINT)
    return "\n".join(lines)


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.BOOK))
async def book_entry(
    callback: CallbackQuery,
    state: FSMContext,
    bookings: BookingService,
) -> None:
    await callback.answer()
    user = callback.from_user
    if user is None:
        return
    if await bookings.user_has_active_booking(user.id):
        await show_screen(
            callback,
            BOOKING_ALREADY_ACTIVE,
            footer_keyboard(),
            state=state,
        )
        return
    await state.clear()
    await state.set_state(BookingFSM.full_name)
    await show_screen(
        callback,
        BOOKING_ASK_NAME,
        flow_cancel_keyboard(),
        state=state,
    )


@router.message(BookingFSM.full_name, F.text)
async def booking_name(message: Message, state: FSMContext) -> None:
    try:
        name = normalize_full_name(message.text or "")
    except AppError as exc:
        await prompt_screen(
            message,
            exc.message,
            flow_cancel_keyboard(),
            state=state,
        )
        return
    await state.update_data(full_name=name)
    await state.set_state(BookingFSM.phone)
    await prompt_screen(
        message,
        BOOKING_ASK_PHONE,
        flow_nav_keyboard(back_step="name"),
        state=state,
    )


@router.message(BookingFSM.phone, F.text)
async def booking_phone(
    message: Message,
    state: FSMContext,
    schedule: ScheduleService,
    settings: Settings,
) -> None:
    try:
        phone = normalize_phone(message.text or "")
    except AppError as exc:
        await prompt_screen(
            message,
            exc.message,
            flow_nav_keyboard(back_step="name"),
            state=state,
        )
        return
    await state.update_data(phone=phone)
    days = await schedule.list_days_with_free_slots()
    if not days:
        await state.clear()
        await prompt_screen(
            message,
            BOOKING_NO_SLOTS,
            no_slots_keyboard(settings),
            state=state,
        )
        return
    await state.set_state(BookingFSM.choose_day)
    await prompt_screen(message, BOOKING_ASK_DAY, days_keyboard(days), state=state)


@router.callback_query(BookNavCallback.filter(F.step == "name"))
async def booking_nav_name(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(BookingFSM.full_name)
    await show_screen(
        callback,
        BOOKING_ASK_NAME,
        flow_cancel_keyboard(),
        state=state,
    )


@router.callback_query(BookNavCallback.filter(F.step == "phone"))
async def booking_nav_phone(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(BookingFSM.phone)
    await show_screen(
        callback,
        BOOKING_ASK_PHONE,
        flow_nav_keyboard(back_step="name"),
        state=state,
    )


@router.callback_query(BookNavCallback.filter(F.step == "day"))
async def booking_nav_day(
    callback: CallbackQuery,
    state: FSMContext,
    schedule: ScheduleService,
    settings: Settings,
) -> None:
    await callback.answer()
    days = await schedule.list_days_with_free_slots()
    if not days:
        await state.clear()
        await show_screen(
            callback,
            BOOKING_NO_SLOTS,
            no_slots_keyboard(settings),
            state=state,
        )
        return
    await state.set_state(BookingFSM.choose_day)
    await state.update_data(day_id=None)
    await show_screen(callback, BOOKING_ASK_DAY, days_keyboard(days), state=state)


@router.callback_query(BookDayCallback.filter(), BookingFSM.choose_day)
async def booking_choose_day(
    callback: CallbackQuery,
    callback_data: BookDayCallback,
    state: FSMContext,
    schedule: ScheduleService,
    settings: Settings,
) -> None:
    await callback.answer()
    slots = await schedule.free_slots_for_day(callback_data.day_id)
    if not slots:
        days = await schedule.list_days_with_free_slots()
        if not days:
            await state.clear()
            await show_screen(
                callback,
                BOOKING_NO_SLOTS,
                no_slots_keyboard(settings),
                state=state,
            )
            return
        await show_screen(
            callback,
            "На этот день нет свободного времени.\nВыбери другой день.",
            days_keyboard(days),
            state=state,
        )
        return
    await state.update_data(day_id=callback_data.day_id)
    await state.set_state(BookingFSM.choose_time)
    await show_screen(
        callback,
        BOOKING_ASK_TIME,
        slots_keyboard(slots),
        state=state,
    )


@router.callback_query(BookSlotCallback.filter(), BookingFSM.choose_time)
async def booking_choose_slot(
    callback: CallbackQuery,
    callback_data: BookSlotCallback,
    state: FSMContext,
    bookings: BookingService,
    schedule: ScheduleService,
    settings: Settings,
) -> None:
    await callback.answer()
    data = await state.get_data()
    full_name = data.get("full_name")
    phone = data.get("phone")
    if not full_name or not phone:
        # State was truncated (bot restart with MemoryStorage, or a stale button).
        await state.clear()
        await show_screen(callback, FLOW_RESET_TEXT, footer_keyboard(), state=state)
        return
    try:
        booking = await bookings.hold_slot(
            slot_id=callback_data.slot_id,
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=full_name,
            phone=phone,
        )
    except AppError as exc:
        await show_screen(
            callback,
            exc.message,
            flow_nav_keyboard(back_step="day"),
            state=state,
        )
        return

    await state.update_data(booking_id=booking.id)
    await state.set_state(BookingFSM.wait_receipt)
    work_hours = await schedule.get_work_settings()
    amount = work_hours.prepayment_amount or settings.prepayment_amount
    day = booking.slot.working_day.day
    t = booking.slot.start_time
    text = BOOKING_PAYMENT.format(
        hold_minutes=_hold_minutes_left(booking, settings.slot_hold_minutes),
        date=format_date_short(day),
        time=format_time(t),
        amount=amount,
        payment_link=settings.payment_link,
    )
    await show_screen(
        callback,
        text,
        payment_keyboard(settings),
        state=state,
    )


def _receipt_file(message: Message) -> tuple[str, str] | None:
    """(file_id, kind) of the attached receipt, or None if there is none."""
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.document is not None:
        return message.document.file_id, "document"
    return None


async def _confirm_receipt(
    message: Message,
    state: FSMContext,
    bookings: BookingService,
    notify: NotifyService,
    *,
    booking_id: int,
    user_id: int,
    file_id: str,
    file_type: str,
) -> None:
    """Shared tail of both receipt paths: confirm, answer, notify the master."""
    await prompt_screen(
        message,
        BOOKING_RECEIPT_WAIT,
        None,
        state=state,
        delete_user=False,
    )
    try:
        booking = await bookings.confirm_with_receipt(
            booking_id=booking_id,
            user_id=user_id,
            receipt_file_id=file_id,
            receipt_file_type=file_type,
        )
    except AppError as exc:
        await state.clear()
        await prompt_screen(message, exc.message, footer_keyboard(), state=state)
        return

    await state.clear()
    await prompt_screen(
        message,
        BOOKING_CONFIRMED.format(
            date=format_date_short(booking.slot.working_day.day),
            time=format_time(booking.slot.start_time),
        ),
        footer_keyboard(),
        state=state,
        delete_user=False,
    )
    await notify.new_booking_with_receipt(booking)


@router.message(BookingFSM.wait_receipt, F.photo | F.document)
async def booking_receipt(
    message: Message,
    state: FSMContext,
    bookings: BookingService,
    notify: NotifyService,
) -> None:
    data = await state.get_data()
    booking_id = data.get("booking_id")
    if not booking_id or message.from_user is None:
        await state.clear()
        await prompt_screen(
            message,
            FLOW_RESET_TEXT,
            footer_keyboard(),
            state=state,
        )
        return

    attachment = _receipt_file(message)
    if attachment is None:
        await prompt_screen(message, "Пришли фото или файл чека.", state=state)
        return

    await _confirm_receipt(
        message,
        state,
        bookings,
        notify,
        booking_id=booking_id,
        user_id=message.from_user.id,
        file_id=attachment[0],
        file_type=attachment[1],
    )


@router.message(BookingFSM.wait_receipt)
async def booking_receipt_hint(
    message: Message,
    state: FSMContext,
    settings: Settings,
) -> None:
    await prompt_screen(
        message,
        "Нужен именно фото или файл чека — отправь его сюда.",
        payment_keyboard(settings),
        state=state,
    )


@router.message(StateFilter(None), F.photo | F.document, HasReceiptTarget())
async def booking_receipt_recovered(
    message: Message,
    state: FSMContext,
    bookings: BookingService,
    notify: NotifyService,
    receipt_target: Booking,
) -> None:
    """Receipt that arrived without FSM state — after a restart, for example.

    The filter only lets this through when the database says this user really
    owes a payment, so a random photo still gets the usual fallback reply.
    """
    attachment = _receipt_file(message)
    if attachment is None or message.from_user is None:
        return

    file_id, file_type = attachment
    if receipt_target.status == BookingStatus.PENDING_PAYMENT.value:
        await _confirm_receipt(
            message,
            state,
            bookings,
            notify,
            booking_id=receipt_target.id,
            user_id=message.from_user.id,
            file_id=file_id,
            file_type=file_type,
        )
        return

    # Hold already lapsed: the slot may be someone else's now, so hand the
    # receipt to the master instead of quietly resurrecting the booking.
    try:
        booking = await bookings.attach_late_receipt(
            receipt_target.id,
            receipt_file_id=file_id,
            receipt_file_type=file_type,
        )
    except AppError as exc:
        await prompt_screen(message, exc.message, footer_keyboard(), delete_user=False)
        return

    await prompt_screen(
        message,
        BOOKING_RECEIPT_LATE,
        footer_keyboard(),
        delete_user=False,
    )
    await notify.receipt_after_expiry(booking)


@router.callback_query(BookCancelCallback.filter())
async def booking_cancel_flow(
    callback: CallbackQuery,
    state: FSMContext,
    bookings: BookingService,
) -> None:
    await callback.answer()
    data = await state.get_data()
    booking_id = data.get("booking_id")
    if booking_id:
        # Already cancelled or swept away: the screen below is correct anyway.
        with suppress(AppError):
            await bookings.cancel_booking(booking_id)
    await state.clear()
    await show_screen(
        callback,
        BOOKING_CANCELLED_FLOW,
        footer_keyboard(),
        state=state,
    )


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.MY_BOOKINGS))
async def my_bookings(
    callback: CallbackQuery,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    await callback.answer()
    items = await bookings.list_user_bookings(callback.from_user.id)
    if not items:
        await show_text(callback, MY_BOOKINGS_EMPTY, footer_keyboard())
        return
    await show_screen(
        callback,
        _render_my_bookings(items),
        my_bookings_keyboard(items),
        state=state,
    )


@router.callback_query(ClientBookingCallback.filter(F.action == "cancel"))
async def client_cancel_ask(
    callback: CallbackQuery,
    callback_data: ClientBookingCallback,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    await callback.answer()
    try:
        booking = await bookings.get_booking(callback_data.booking_id)
        if booking.telegram_user_id != callback.from_user.id:
            await callback.answer("Это не твоя запись", show_alert=True)
            return
    except AppError as exc:
        await show_screen(callback, exc.message, footer_keyboard(), state=state)
        return
    await show_screen(
        callback,
        CANCEL_CONFIRM.format(details=format_client_booking_card(booking)),
        cancel_confirm_keyboard(booking.id),
        state=state,
    )


@router.callback_query(ClientBookingCallback.filter(F.action == "cancel_yes"))
async def client_cancel_yes(
    callback: CallbackQuery,
    callback_data: ClientBookingCallback,
    bookings: BookingService,
    notify: NotifyService,
    state: FSMContext,
) -> None:
    try:
        booking = await bookings.cancel_by_client(
            callback_data.booking_id,
            callback.from_user.id,
        )
        await callback.answer("Готово")
        await show_screen(
            callback,
            BOOKING_CANCELLED_DONE,
            footer_keyboard(),
            state=state,
        )
        await notify.booking_cancelled(booking, reason="Клиент отменил сам.")
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)


@router.callback_query(ClientBookingCallback.filter(F.action == "cancel_no"))
async def client_cancel_no(
    callback: CallbackQuery,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    await callback.answer()
    items = await bookings.list_user_bookings(callback.from_user.id)
    if not items:
        await show_screen(callback, MY_BOOKINGS_EMPTY, footer_keyboard(), state=state)
        return
    await show_screen(
        callback,
        _render_my_bookings(items),
        my_bookings_keyboard(items),
        state=state,
    )
