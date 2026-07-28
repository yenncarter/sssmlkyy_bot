"""Admin keyboards — progressive disclosure, clean emoji-first buttons."""

from __future__ import annotations

import logging
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import AdminCallback
from db.models import Booking, Slot, WorkingDay
from domain.dates import format_date_short, format_time, weekday_short
from domain.enums import BookingStatus, SlotStatus
from presentation.texts.messages import BTN_BACK

logger = logging.getLogger("beauty_bot.keyboards")

# Telegram rejects inline keyboards with ~100+ rows. Stay below that, and shout
# when a list is actually cut off instead of hiding rows silently.
MAX_LIST_ROWS = 90


def _limited(items: list, what: str) -> list:
    if len(items) > MAX_LIST_ROWS:
        logger.warning(
            "Список «%s» обрезан: %s из %s", what, MAX_LIST_ROWS, len(items)
        )
        return items[:MAX_LIST_ROWS]
    return items


def _back(action: str, item_id: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=BTN_BACK,
        callback_data=AdminCallback(action=action, item_id=item_id).pack(),
    )


def admin_status_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="← Админ-меню",
            callback_data=AdminCallback(action="home").pack(),
        )
    )
    return builder.as_markup()


def admin_home_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📋 Записи клиентов",
            callback_data=AdminCallback(action="bookings").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗓 График работы",
            callback_data=AdminCallback(action="schedule").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⚙️ Настройки",
            callback_data=AdminCallback(action="hours").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="👁 Меню клиента",
            callback_data=AdminCallback(action="client_menu").pack(),
        ),
    )
    return builder.as_markup()


def admin_schedule_hub_keyboard(*, days_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить день",
            callback_data=AdminCallback(action="add_day").pack(),
        ),
    )
    if days_count > 0:
        builder.row(
            InlineKeyboardButton(
                text=f"📅 Все дни · {days_count}",
                callback_data=AdminCallback(action="days_list").pack(),
            ),
        )
    builder.row(_back("home"))
    return builder.as_markup()


def admin_days_list_keyboard(days: list[WorkingDay]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in _limited(days, "дни графика"):
        custom = bool(day.open_time or day.close_time or day.slot_minutes)
        free = sum(1 for s in day.slots if s.status == SlotStatus.FREE.value)
        star = "★ " if custom else ""
        wd = weekday_short(day.day)
        builder.row(
            InlineKeyboardButton(
                text=f"{star}{format_date_short(day.day)} {wd} · {free}",
                callback_data=AdminCallback(action="day", item_id=day.id).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить день",
            callback_data=AdminCallback(action="add_day").pack(),
        )
    )
    builder.row(_back("schedule"))
    return builder.as_markup()


_SLOT_LABEL_PREFIX = {
    SlotStatus.BOOKED.value: "🔒 ",
    SlotStatus.BLOCKED.value: "✕ ",
    SlotStatus.HELD.value: "⏳ ",
}


def admin_day_keyboard(
    day_id: int,
    slots: list[Slot] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if slots:
        row: list[InlineKeyboardButton] = []
        for s in _limited(list(slots), "слоты дня"):
            t = format_time(s.start_time)
            label = f"{_SLOT_LABEL_PREFIX.get(s.status, '')}{t}"
            row.append(
                InlineKeyboardButton(
                    text=label,
                    callback_data=AdminCallback(action="tog_slot", item_id=s.id).pack(),
                )
            )
            if len(row) == 2:
                builder.row(*row)
                row = []
        if row:
            builder.row(*row)

    builder.row(
        InlineKeyboardButton(
            text="🕐 Часы этого дня",
            callback_data=AdminCallback(action="day_hours", item_id=day_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить день",
            callback_data=AdminCallback(action="del_day", item_id=day_id).pack(),
        ),
    )
    builder.row(_back("days_list"))
    return builder.as_markup()


def admin_day_hours_keyboard(day_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="↺ По умолчанию",
            callback_data=AdminCallback(action="day_reset_yes", item_id=day_id).pack(),
        )
    )
    builder.row(_back("day", day_id))
    return builder.as_markup()


def admin_confirm_keyboard(
    *,
    yes_action: str,
    no_action: str,
    item_id: int,
    yes_text: str = "Да",
    no_text: str = "Нет",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=yes_text,
            callback_data=AdminCallback(action=yes_action, item_id=item_id).pack(),
        ),
        InlineKeyboardButton(
            text=no_text,
            callback_data=AdminCallback(action=no_action, item_id=item_id).pack(),
        ),
    )
    return builder.as_markup()


def admin_back_schedule_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_back("schedule"))
    return builder.as_markup()


def admin_back_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_back("hours"))
    return builder.as_markup()


def admin_bookings_days_keyboard(
    day_items: list[tuple[int, date, int]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day_id, day_date, count in _limited(day_items, "дни с записями"):
        builder.row(
            InlineKeyboardButton(
                text=f"📅 {format_date_short(day_date)} · {count}",
                callback_data=AdminCallback(action="book_day", item_id=day_id).pack(),
            )
        )
    builder.row(_back("home"))
    return builder.as_markup()


def admin_notify_keyboard(booking_id: int, username: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📅 Перенести запись",
            callback_data=AdminCallback(action="reschedule", item_id=booking_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Отменить запись",
            callback_data=AdminCallback(action="cancel", item_id=booking_id).pack(),
        ),
    )
    if username:
        builder.row(
            InlineKeyboardButton(
                text="💬 Написать клиенту",
                url=f"https://t.me/{username}",
            )
        )
    return builder.as_markup()


def admin_hours_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🕐 Рабочие часы по умолчанию",
            callback_data=AdminCallback(action="hours_edit").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="💳 Сумма предоплаты",
            callback_data=AdminCallback(action="prepay_edit").pack(),
        ),
    )
    builder.row(_back("home"))
    return builder.as_markup()


def admin_bookings_keyboard(bookings: list[Booking]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in _limited(bookings, "записи"):
        day = b.slot.working_day.day
        t = b.slot.start_time
        mark = "⏳ " if b.status == BookingStatus.PENDING_PAYMENT.value else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{mark}{format_date_short(day)} {format_time(t)} · {b.full_name}",
                callback_data=AdminCallback(action="booking", item_id=b.id).pack(),
            )
        )
    builder.row(_back("bookings"))
    return builder.as_markup()


def admin_booking_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📅 Перенести запись",
            callback_data=AdminCallback(action="reschedule", item_id=booking_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Отменить запись",
            callback_data=AdminCallback(action="cancel", item_id=booking_id).pack(),
        ),
    )
    builder.row(_back("bookings"))
    return builder.as_markup()
