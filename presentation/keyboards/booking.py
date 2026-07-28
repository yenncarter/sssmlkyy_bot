"""Booking flow keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import (
    AdminCallback,
    BookCancelCallback,
    BookDayCallback,
    BookNavCallback,
    BookSlotCallback,
    ClientBookingCallback,
)
from config.settings import Settings
from db.models import Booking, Slot, WorkingDay
from domain.dates import format_date_short, format_time
from presentation.keyboards.menu import back_button
from presentation.texts.messages import (
    BTN_BACK,
    BTN_CANCEL_FLOW,
    BTN_CONFIRM_NO,
    BTN_CONFIRM_YES,
    BTN_PAY,
    BTN_WRITE_MASTER,
)


def _free_windows_label(count: int) -> str:
    n10, n100 = count % 10, count % 100
    if n10 == 1 and n100 != 11:
        word = "окошко"
    elif 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        word = "окошка"
    else:
        word = "окошек"
    return f"{count} {word}"


def flow_cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel only — first step of booking (no back stack yet)."""
    return flow_nav_keyboard(back_step=None)


def flow_nav_keyboard(*, back_step: str | None) -> InlineKeyboardMarkup:
    """Predictable back stack: ← Назад + Отмена on one row when back exists."""
    builder = InlineKeyboardBuilder()
    cancel = InlineKeyboardButton(
        text=BTN_CANCEL_FLOW,
        callback_data=BookCancelCallback().pack(),
    )
    if back_step:
        builder.row(
            InlineKeyboardButton(
                text=BTN_BACK,
                callback_data=BookNavCallback(step=back_step).pack(),
            ),
            cancel,
        )
    else:
        builder.row(cancel)
    return builder.as_markup()


def days_keyboard(
    days: list[tuple[WorkingDay, int]],
    *,
    with_cancel: bool = True,
    back_to_admin: bool = False,
    booking_id: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day, free_count in days:
        label = format_date_short(day.day)
        if free_count > 0:
            label = f"{label} · {_free_windows_label(free_count)}"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=BookDayCallback(day_id=day.id).pack(),
            )
        )
    if with_cancel:
        builder.row(
            InlineKeyboardButton(
                text=BTN_BACK,
                callback_data=BookNavCallback(step="phone").pack(),
            ),
            InlineKeyboardButton(
                text=BTN_CANCEL_FLOW,
                callback_data=BookCancelCallback().pack(),
            ),
        )
    elif back_to_admin:
        if booking_id:
            builder.row(
                InlineKeyboardButton(
                    text=BTN_BACK,
                    callback_data=AdminCallback(
                        action="booking", item_id=booking_id
                    ).pack(),
                )
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text=BTN_BACK,
                    callback_data=AdminCallback(action="bookings").pack(),
                )
            )
    return builder.as_markup()


def slots_keyboard(
    slots: list[Slot],
    *,
    with_cancel: bool = True,
    back_to_day: bool = True,
    booking_id: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for slot in slots:
        row.append(
            InlineKeyboardButton(
                text=format_time(slot.start_time),
                callback_data=BookSlotCallback(slot_id=slot.id).pack(),
            )
        )
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    if with_cancel and back_to_day:
        builder.row(
            InlineKeyboardButton(
                text=BTN_BACK,
                callback_data=BookNavCallback(step="day").pack(),
            ),
            InlineKeyboardButton(
                text=BTN_CANCEL_FLOW,
                callback_data=BookCancelCallback().pack(),
            ),
        )
    elif booking_id is not None:
        builder.row(
            InlineKeyboardButton(
                text=BTN_BACK,
                callback_data=AdminCallback(
                    action="reschedule", item_id=booking_id
                ).pack(),
            )
        )
    return builder.as_markup()


def payment_keyboard(settings: Settings, pay_url: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=BTN_PAY, url=pay_url or settings.payment_link))
    builder.row(
        InlineKeyboardButton(
            text=BTN_CANCEL_FLOW,
            callback_data=BookCancelCallback().pack(),
        )
    )
    return builder.as_markup()


def no_slots_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=BTN_WRITE_MASTER, url=settings.master_url)
    )
    builder.row(back_button())
    return builder.as_markup()


def my_bookings_keyboard(bookings: list[Booking]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        day = b.slot.working_day.day
        t = b.slot.start_time
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 Отменить · {format_date_short(day)} {format_time(t)}",
                callback_data=ClientBookingCallback(
                    action="cancel", booking_id=b.id
                ).pack(),
            )
        )
    builder.row(back_button())
    return builder.as_markup()


def cancel_confirm_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=BTN_CONFIRM_YES,
            callback_data=ClientBookingCallback(
                action="cancel_yes", booking_id=booking_id
            ).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=BTN_CONFIRM_NO,
            callback_data=ClientBookingCallback(
                action="cancel_no", booking_id=booking_id
            ).pack(),
        ),
    )
    return builder.as_markup()
