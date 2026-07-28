"""Admin panel — progressive disclosure, predictable back stack.

Access control lives on the router (`IsAdmin`), not in every handler. Requests
from non-admins never reach this module; `handlers.admin_guard` answers them.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from callbacks.factories import AdminCallback, BookDayCallback, BookSlotCallback
from config.settings import Settings
from db.models import Booking
from domain.dates import format_date_short, today
from domain.enums import SlotStatus
from domain.exceptions import AppError, DuplicateSlotError
from domain.parsing import (
    normalize_prepayment_amount,
    parse_days_column,
    parse_hours_message,
    safe_echo,
)
from handlers.filters import IsAdmin
from handlers.states import AdminFSM
from presentation.formatters import format_admin_booking_card, format_bot_status, format_hours
from presentation.keyboards.admin import (
    admin_back_schedule_keyboard,
    admin_back_settings_keyboard,
    admin_booking_keyboard,
    admin_bookings_days_keyboard,
    admin_bookings_keyboard,
    admin_confirm_keyboard,
    admin_day_hours_keyboard,
    admin_day_keyboard,
    admin_days_list_keyboard,
    admin_home_keyboard,
    admin_hours_keyboard,
    admin_schedule_hub_keyboard,
    admin_status_keyboard,
)
from presentation.keyboards.booking import days_keyboard, slots_keyboard
from presentation.texts.messages import (
    ADMIN_ADD_DAY_PROMPT,
    ADMIN_BOOKINGS,
    ADMIN_BOOKINGS_EMPTY,
    ADMIN_DAY_HOURS_PROMPT,
    ADMIN_DAYS_LIST,
    ADMIN_DAYS_LIST_EMPTY,
    ADMIN_HOME,
    ADMIN_HOURS,
    ADMIN_HOURS_PROMPT,
    ADMIN_PREPAY_PROMPT,
    ADMIN_SCHEDULE,
    ADMIN_SCHEDULE_EMPTY,
    BTN_CONFIRM_NO,
    BTN_CONFIRM_YES,
    CANCEL_CONFIRM,
)
from presentation.ui.screens import prompt_screen, show_main_menu, show_screen
from services.db_health import DbHealthService
from services.media_cache import MediaCache
from services.notify_service import NotifyService
from services.schedule_service import BookingService, ScheduleService
from services.session import SessionService

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

logger = logging.getLogger("beauty_bot.admin")

Screen = tuple[str, InlineKeyboardMarkup]


async def _schedule_hub(schedule: ScheduleService) -> Screen:
    days = await schedule.list_upcoming_days()
    if not days:
        return ADMIN_SCHEDULE_EMPTY, admin_schedule_hub_keyboard(days_count=0)
    free = sum(
        1 for d in days for s in d.slots if s.status == SlotStatus.FREE.value
    )
    return (
        ADMIN_SCHEDULE.format(days=len(days), free=free),
        admin_schedule_hub_keyboard(days_count=len(days)),
    )


async def _days_list_screen(schedule: ScheduleService) -> Screen:
    days = await schedule.list_upcoming_days()
    if not days:
        return ADMIN_DAYS_LIST_EMPTY, admin_days_list_keyboard([])
    return ADMIN_DAYS_LIST, admin_days_list_keyboard(days)


async def _day_card(schedule: ScheduleService, day_id: int) -> Screen:
    day = await schedule.get_day(day_id)
    work_hours = await schedule.get_work_settings()
    open_t = day.open_time or work_hours.open_time
    close_t = day.close_time or work_hours.close_time
    custom = bool(day.open_time or day.close_time or day.slot_minutes)
    counts = {status: 0 for status in (
        SlotStatus.FREE.value,
        SlotStatus.BOOKED.value,
        SlotStatus.BLOCKED.value,
    )}
    for slot in day.slots:
        if slot.status in counts:
            counts[slot.status] += 1
    lines = [
        f"📅 <b>{format_date_short(day.day)}</b>",
        f"{format_hours(open_t, close_t)}"
        + (" · свои часы" if custom else " · как в настройках"),
        f"Свободно <b>{counts[SlotStatus.FREE.value]}</b>"
        f" · записи <b>{counts[SlotStatus.BOOKED.value]}</b>"
        f" · закрыто <b>{counts[SlotStatus.BLOCKED.value]}</b>",
        "",
        "Нажми время: открыть ↔ закрыть ✨",
        "пусто — свободно · 🔒 запись · ✕ закрыто · ⏳ ждёт чек",
    ]
    return "\n".join(lines), admin_day_keyboard(day.id, day.slots)


async def _bookings_hub(bookings: BookingService) -> Screen:
    days = await bookings.list_booking_days()
    if not days:
        return ADMIN_BOOKINGS_EMPTY, admin_bookings_days_keyboard([])
    return ADMIN_BOOKINGS, admin_bookings_days_keyboard(days)


async def _settings_screen(schedule: ScheduleService, prefix: str = "") -> Screen:
    work_hours = await schedule.get_work_settings()
    text = ADMIN_HOURS.format(
        hours=format_hours(work_hours.open_time, work_hours.close_time),
        amount=work_hours.prepayment_amount,
    )
    return prefix + text, admin_hours_keyboard()


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_HOME, reply_markup=admin_home_keyboard())


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    db_health: DbHealthService,
    media_cache: MediaCache,
) -> None:
    status = await db_health.diagnose(media_cached=media_cache.size)
    await message.answer(
        format_bot_status(status),
        reply_markup=admin_status_keyboard(),
    )


@router.callback_query(AdminCallback.filter(F.action == "home"))
async def admin_home_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show_screen(callback, ADMIN_HOME, admin_home_keyboard(), state=state)


@router.callback_query(AdminCallback.filter(F.action == "client_menu"))
async def admin_client_menu(
    callback: CallbackQuery,
    settings: Settings,
    media_cache: MediaCache,
    session: SessionService,
) -> None:
    await callback.answer()
    session.mark_started(callback.from_user.id)
    await show_main_menu(callback, settings, media_cache)


@router.callback_query(AdminCallback.filter(F.action == "hours"))
async def admin_hours(
    callback: CallbackQuery,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.clear()
    text, markup = await _settings_screen(schedule)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "prepay_edit"))
async def admin_prepay_edit(
    callback: CallbackQuery,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    await callback.answer()
    await state.set_state(AdminFSM.edit_prepay)
    work_hours = await schedule.get_work_settings()
    await show_screen(
        callback,
        ADMIN_PREPAY_PROMPT.format(amount=work_hours.prepayment_amount),
        admin_back_settings_keyboard(),
        state=state,
    )


@router.message(AdminFSM.edit_prepay, F.text)
async def admin_prepay_save(
    message: Message,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    try:
        amount = normalize_prepayment_amount(message.text or "")
        await schedule.set_prepayment_amount(amount)
    except AppError as exc:
        await prompt_screen(message, exc.message, state=state)
        return
    await state.clear()
    text, markup = await _settings_screen(schedule, prefix="Сохранено.\n\n")
    await prompt_screen(message, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "tog_slot"))
async def admin_toggle_slot(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    try:
        slot = await schedule.toggle_slot_block(callback_data.item_id)
        await callback.answer(
            "Закрыто" if slot.status == SlotStatus.BLOCKED.value else "Открыто"
        )
        text, markup = await _day_card(schedule, slot.working_day_id)
        await show_screen(callback, text, markup, state=state)
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)


@router.callback_query(AdminCallback.filter(F.action == "hours_edit"))
async def admin_hours_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminFSM.edit_default_hours)
    await show_screen(
        callback,
        ADMIN_HOURS_PROMPT,
        admin_back_settings_keyboard(),
        state=state,
    )


@router.message(AdminFSM.edit_default_hours, F.text)
async def admin_hours_save(
    message: Message,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    try:
        open_t, close_t, step = parse_hours_message(message.text or "")
        await schedule.set_work_settings(open_t, close_t, step)
    except AppError as exc:
        await prompt_screen(message, exc.message, state=state)
        return
    await state.clear()
    text, markup = await _settings_screen(
        schedule,
        prefix=(
            "Сохранено. Уже открытые дни не меняются сами — "
            "в карточке дня → «Часы дня» → «По умолчанию».\n\n"
        ),
    )
    await prompt_screen(message, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "schedule"))
async def admin_schedule(
    callback: CallbackQuery,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.clear()
    text, markup = await _schedule_hub(schedule)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "days_list"))
async def admin_days_list(
    callback: CallbackQuery,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.clear()
    text, markup = await _days_list_screen(schedule)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "add_day"))
async def admin_add_day_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminFSM.add_day)
    await show_screen(
        callback,
        ADMIN_ADD_DAY_PROMPT,
        admin_back_schedule_keyboard(),
        state=state,
    )


@router.message(AdminFSM.add_day, F.text)
async def admin_add_day_save(
    message: Message,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    days, bad = parse_days_column(message.text or "")
    if not days:
        await prompt_screen(
            message,
            "Не поняла даты.\n\n" + ADMIN_ADD_DAY_PROMPT,
            admin_back_schedule_keyboard(),
            state=state,
        )
        return

    created: list[str] = []
    skipped: list[str] = []
    past: list[str] = []
    for day in days:
        if day < today():
            past.append(format_date_short(day))
            continue
        try:
            await schedule.add_day_from_defaults(day)
            created.append(format_date_short(day))
        except DuplicateSlotError:
            skipped.append(format_date_short(day))
        except AppError as exc:
            logger.warning("День %s не добавлен: %s", day, exc.message)
            bad.append(format_date_short(day))

    await state.clear()
    parts = []
    if created:
        parts.append("Добавлено ✨\n" + "\n".join(f"· {d}" for d in created))
    if skipped:
        parts.append("Уже были 🤍\n" + "\n".join(f"· {d}" for d in skipped))
    if past:
        parts.append("Пропущено (уже прошло):\n" + "\n".join(f"· {d}" for d in past))
    if bad:
        parts.append(
            "Не разобраны:\n" + "\n".join(f"· {safe_echo(d)}" for d in bad[:8])
        )
    if not created and not skipped:
        parts.insert(0, "Ничего не добавилось 🙈")

    text, markup = await _days_list_screen(schedule)
    await prompt_screen(
        message,
        "\n\n".join(parts) + "\n\n" + text,
        markup,
        state=state,
    )


@router.callback_query(AdminCallback.filter(F.action == "day"))
async def admin_day(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    await callback.answer()
    try:
        text, markup = await _day_card(schedule, callback_data.item_id)
    except AppError as exc:
        await show_screen(callback, exc.message, state=state)
        return
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "day_hours"))
async def admin_day_hours_start(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.set_state(AdminFSM.edit_day_hours)
    await state.update_data(edit_day_id=callback_data.item_id)
    await show_screen(
        callback,
        ADMIN_DAY_HOURS_PROMPT,
        admin_day_hours_keyboard(callback_data.item_id),
        state=state,
    )


@router.message(AdminFSM.edit_day_hours, F.text)
async def admin_day_hours_save(
    message: Message,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    data = await state.get_data()
    day_id = data.get("edit_day_id")
    if not day_id:
        await state.clear()
        await prompt_screen(
            message,
            "Не поняла, какой день менять. Открой карточку дня заново.",
            admin_back_schedule_keyboard(),
            state=state,
        )
        return
    try:
        open_t, close_t, step = parse_hours_message(message.text or "")
        day = await schedule.set_day_hours(day_id, open_t, close_t, step)
    except AppError as exc:
        await prompt_screen(message, exc.message, state=state)
        return
    await state.clear()
    text, markup = await _day_card(schedule, day.id)
    await prompt_screen(
        message,
        "Часы обновлены.\n\n" + text,
        markup,
        state=state,
    )


@router.callback_query(AdminCallback.filter(F.action == "day_reset_yes"))
async def admin_day_reset_yes(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    try:
        await schedule.clear_day_override(callback_data.item_id)
        await callback.answer("Как в настройках ✨")
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await state.clear()
    text, markup = await _day_card(schedule, callback_data.item_id)
    await show_screen(
        callback,
        "Готово ✨ часы как в настройках\n\n" + text,
        markup,
        state=state,
    )


@router.callback_query(AdminCallback.filter(F.action == "del_day"))
async def admin_del_day_ask(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    await callback.answer()
    try:
        day = await schedule.get_day(callback_data.item_id)
    except AppError as exc:
        await show_screen(callback, exc.message, state=state)
        return
    await show_screen(
        callback,
        f"<b>Удалить {format_date_short(day.day)}?</b>\n\n"
        "Слоты дня пропадут.\n"
        "Сначала отмени активные записи, если они есть.",
        admin_confirm_keyboard(
            yes_action="del_day_yes",
            no_action="day",
            item_id=callback_data.item_id,
            yes_text="🗑 Удалить",
            no_text="Оставить",
        ),
        state=state,
    )


@router.callback_query(AdminCallback.filter(F.action == "del_day_yes"))
async def admin_del_day_yes(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    try:
        await schedule.delete_day(callback_data.item_id)
        await callback.answer("Удалено")
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    text, markup = await _days_list_screen(schedule)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "bookings"))
async def admin_bookings(
    callback: CallbackQuery,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    await callback.answer()
    text, markup = await _bookings_hub(bookings)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "book_day"))
async def admin_book_day(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    await callback.answer()
    items = await bookings.list_for_working_day(callback_data.item_id)
    label = format_date_short(items[0].slot.working_day.day) if items else "день"
    await _send_bookings_list(callback, bookings, items, f"Записи · {label}", state)


async def _send_bookings_list(
    callback: CallbackQuery,
    bookings: BookingService,
    items: list[Booking],
    title: str,
    state: FSMContext,
) -> None:
    if not items:
        text, markup = await _bookings_hub(bookings)
        await show_screen(
            callback,
            f"<b>{title}</b>\n\nПусто.\n\n{text}",
            markup,
            state=state,
        )
        return
    await show_screen(
        callback,
        f"<b>{title}</b>",
        admin_bookings_keyboard(items),
        state=state,
    )


@router.callback_query(AdminCallback.filter(F.action == "booking"))
async def admin_booking_view(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.clear()
    try:
        booking = await bookings.get_booking(callback_data.item_id)
    except AppError as exc:
        await show_screen(callback, exc.message, state=state)
        return
    await show_screen(
        callback,
        format_admin_booking_card(booking),
        admin_booking_keyboard(booking.id),
        state=state,
    )


@router.callback_query(AdminCallback.filter(F.action == "cancel"))
async def admin_cancel_ask(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    await callback.answer()
    try:
        booking = await bookings.get_booking(callback_data.item_id)
    except AppError as exc:
        await show_screen(callback, exc.message, state=state)
        return
    await show_screen(
        callback,
        CANCEL_CONFIRM.format(details=format_admin_booking_card(booking)),
        admin_confirm_keyboard(
            yes_action="cancel_yes",
            no_action="booking",
            item_id=booking.id,
            yes_text=BTN_CONFIRM_YES,
            no_text=BTN_CONFIRM_NO,
        ),
        state=state,
    )


@router.callback_query(AdminCallback.filter(F.action == "cancel_yes"))
async def admin_cancel_yes(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    bookings: BookingService,
    notify: NotifyService,
    state: FSMContext,
) -> None:
    try:
        booking = await bookings.cancel_booking(callback_data.item_id)
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await callback.answer("Отменено")
    text, markup = await _bookings_hub(bookings)
    await show_screen(callback, "Запись отменена.\n\n" + text, markup, state=state)
    await notify.client_cancelled_by_master(booking)


@router.callback_query(AdminCallback.filter(F.action == "reschedule"))
async def admin_reschedule_start(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    state: FSMContext,
    schedule: ScheduleService,
    bookings: BookingService,
) -> None:
    await callback.answer()
    await state.set_state(AdminFSM.reschedule_pick_day)
    await state.update_data(reschedule_booking_id=callback_data.item_id)
    days = await schedule.list_days_with_free_slots()
    if not days:
        await state.clear()
        text, markup = await _bookings_hub(bookings)
        await show_screen(
            callback,
            "Нет свободных слотов для переноса.\n\n" + text,
            markup,
            state=state,
        )
        return
    await show_screen(
        callback,
        "Новый день:",
        days_keyboard(
            days,
            with_cancel=False,
            back_to_admin=True,
            booking_id=callback_data.item_id,
        ),
        state=state,
    )


@router.callback_query(BookDayCallback.filter(), AdminFSM.reschedule_pick_day)
async def admin_reschedule_day(
    callback: CallbackQuery,
    callback_data: BookDayCallback,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    await callback.answer()
    slots = await schedule.free_slots_for_day(callback_data.day_id)
    if not slots:
        await show_screen(
            callback,
            "В этот день нет свободного времени.\nВыбери другой.",
            state=state,
        )
        return
    data = await state.get_data()
    booking_id = data.get("reschedule_booking_id")
    await state.set_state(AdminFSM.reschedule_pick_time)
    await show_screen(
        callback,
        "Новое время:",
        slots_keyboard(
            slots,
            with_cancel=False,
            back_to_day=False,
            booking_id=booking_id,
        ),
        state=state,
    )


@router.callback_query(BookSlotCallback.filter(), AdminFSM.reschedule_pick_time)
async def admin_reschedule_time(
    callback: CallbackQuery,
    callback_data: BookSlotCallback,
    state: FSMContext,
    bookings: BookingService,
    notify: NotifyService,
) -> None:
    await callback.answer()
    data = await state.get_data()
    booking_id = data.get("reschedule_booking_id")
    if not booking_id:
        await state.clear()
        text, markup = await _bookings_hub(bookings)
        await show_screen(
            callback,
            "Не поняла, какую запись переносить. Открой её заново.\n\n" + text,
            markup,
            state=state,
        )
        return
    try:
        booking = await bookings.reschedule(booking_id, callback_data.slot_id)
    except AppError as exc:
        await state.clear()
        text, markup = await _bookings_hub(bookings)
        await show_screen(callback, exc.message + "\n\n" + text, markup, state=state)
        return
    await state.clear()
    text, markup = await _bookings_hub(bookings)
    await show_screen(
        callback,
        "Перенесено.\n\n" + format_admin_booking_card(booking) + "\n\n" + text,
        markup,
        state=state,
    )
    await notify.client_rescheduled(booking)
