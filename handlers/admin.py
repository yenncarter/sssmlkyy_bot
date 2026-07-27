"""Admin panel — progressive disclosure, predictable back stack."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from callbacks.factories import AdminCallback, BookDayCallback, BookSlotCallback
from config.settings import Settings
from domain.dates import format_date, format_date_short, format_time, today
from domain.exceptions import AppError, DuplicateSlotError
from handlers.states import AdminFSM
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
)
from presentation.keyboards.booking import days_keyboard, slots_keyboard
from presentation.texts.messages import (
    ADMIN_ADD_DAY_PROMPT,
    ADMIN_BOOKINGS,
    ADMIN_BOOKINGS_EMPTY,
    ADMIN_DAY_HOURS_PROMPT,
    ADMIN_DAYS_LIST,
    ADMIN_DAYS_LIST_EMPTY,
    ADMIN_DENIED,
    ADMIN_HOME,
    ADMIN_HOURS,
    ADMIN_HOURS_PROMPT,
    ADMIN_NO_ACCESS,
    ADMIN_PREPAY_PROMPT,
    ADMIN_SCHEDULE,
    ADMIN_SCHEDULE_EMPTY,
    BTN_CONFIRM_NO,
    BTN_CONFIRM_YES,
    CANCEL_CONFIRM,
)
from presentation.ui.screens import prompt_screen, show_screen
from services.media_cache import MediaCache
from services.notify_service import NotifyService
from services.schedule_service import (
    BookingService,
    ScheduleService,
    format_admin_booking_card,
    format_hours,
    parse_days_column,
    parse_hours_message,
)
from services.session import SessionService

router = Router(name="admin")


def _ensure_admin(settings: Settings, user_id: int | None) -> bool:
    return settings.is_admin(user_id)


async def _schedule_hub(schedule: ScheduleService) -> tuple[str, object]:
    days = await schedule.list_upcoming_days()
    if not days:
        return ADMIN_SCHEDULE_EMPTY, admin_schedule_hub_keyboard(days_count=0)
    free = sum(
        1 for d in days for s in d.slots if s.status == "free"
    )
    text = ADMIN_SCHEDULE.format(days=len(days), free=free)
    return text, admin_schedule_hub_keyboard(days_count=len(days))


async def _days_list_screen(schedule: ScheduleService) -> tuple[str, object]:
    days = await schedule.list_upcoming_days()
    if not days:
        return ADMIN_DAYS_LIST_EMPTY, admin_days_list_keyboard([])
    return ADMIN_DAYS_LIST, admin_days_list_keyboard(days)


async def _day_card(schedule: ScheduleService, day_id: int) -> tuple[str, object]:
    day = await schedule.get_day(day_id)
    ws = await schedule.get_work_settings()
    open_t = day.open_time or ws.open_time
    close_t = day.close_time or ws.close_time
    custom = bool(day.open_time or day.close_time or day.slot_minutes)
    free = sum(1 for s in day.slots if s.status == "free")
    booked = sum(1 for s in day.slots if s.status == "booked")
    blocked = sum(1 for s in day.slots if s.status == "blocked")
    lines = [
        f"📅 <b>{format_date_short(day.day)}</b>",
        f"{format_hours(open_t, close_t)}"
        + (" · свои часы" if custom else " · как в настройках"),
        f"Свободно <b>{free}</b> · записи <b>{booked}</b> · закрыто <b>{blocked}</b>",
        "",
        "Нажми время: открыть ↔ закрыть ✨",
        "пусто — свободно · 🔒 запись · ✕ закрыто · ⏳ ждёт чек",
    ]
    return "\n".join(lines), admin_day_keyboard(day.id, day.slots)


async def _bookings_hub(bookings: BookingService) -> tuple[str, object]:
    days = await bookings.list_booking_days()
    if not days:
        return ADMIN_BOOKINGS_EMPTY, admin_bookings_days_keyboard([])
    return ADMIN_BOOKINGS, admin_bookings_days_keyboard(days)


@router.message(Command("admin"))
async def cmd_admin(message: Message, settings: Settings, state: FSMContext) -> None:
    if not _ensure_admin(settings, message.from_user.id if message.from_user else None):
        await message.answer(ADMIN_DENIED)
        return
    await state.clear()
    await message.answer(ADMIN_HOME, reply_markup=admin_home_keyboard())


@router.callback_query(AdminCallback.filter(F.action == "home"))
async def admin_home_cb(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    session.mark_started(callback.from_user.id)
    from presentation.ui.screens import show_main_menu

    await show_main_menu(callback, settings, media_cache)


@router.callback_query(AdminCallback.filter(F.action == "hours"))
async def admin_hours(
    callback: CallbackQuery,
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    await state.clear()
    ws = await schedule.get_work_settings()
    text = ADMIN_HOURS.format(
        hours=format_hours(ws.open_time, ws.close_time),
        amount=ws.prepayment_amount,
    )
    await show_screen(callback, text, admin_hours_keyboard(), state=state)


@router.callback_query(AdminCallback.filter(F.action == "prepay_edit"))
async def admin_prepay_edit(
    callback: CallbackQuery,
    settings: Settings,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminFSM.edit_prepay)
    ws = await schedule.get_work_settings()
    await show_screen(
        callback,
        ADMIN_PREPAY_PROMPT.format(amount=ws.prepayment_amount),
        admin_back_settings_keyboard(),
        state=state,
    )


@router.message(AdminFSM.edit_prepay, F.text)
async def admin_prepay_save(
    message: Message,
    state: FSMContext,
    settings: Settings,
    schedule: ScheduleService,
) -> None:
    if not _ensure_admin(settings, message.from_user.id if message.from_user else None):
        return
    try:
        ws = await schedule.set_prepayment_amount(message.text or "")
    except AppError as exc:
        await prompt_screen(message, exc.message, state=state)
        return
    await state.clear()
    text = "Сохранено.\n\n" + ADMIN_HOURS.format(
        hours=format_hours(ws.open_time, ws.close_time),
        amount=ws.prepayment_amount,
    )
    await prompt_screen(message, text, admin_hours_keyboard(), state=state)


@router.callback_query(AdminCallback.filter(F.action == "tog_slot"))
async def admin_toggle_slot(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    try:
        slot = await schedule.toggle_slot_block(callback_data.item_id)
        await callback.answer("Закрыто" if slot.status == "blocked" else "Открыто")
        text, markup = await _day_card(schedule, slot.working_day_id)
        await show_screen(callback, text, markup, state=state)
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)


@router.callback_query(AdminCallback.filter(F.action == "hours_edit"))
async def admin_hours_edit(
    callback: CallbackQuery,
    settings: Settings,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    schedule: ScheduleService,
) -> None:
    if not _ensure_admin(settings, message.from_user.id if message.from_user else None):
        return
    try:
        open_t, close_t, step = parse_hours_message(message.text or "")
        ws = await schedule.set_work_settings(open_t, close_t, step)
    except AppError as exc:
        await prompt_screen(message, exc.message, state=state)
        return
    except ValueError:
        await prompt_screen(
            message,
            "Формат: <code>10:00-22:00</code>",
            state=state,
        )
        return
    await state.clear()
    text = (
        "Сохранено. Уже открытые дни не меняются сами — "
        "в карточке дня → «Часы дня» → «По умолчанию».\n\n"
        + ADMIN_HOURS.format(
            hours=format_hours(ws.open_time, ws.close_time),
            amount=ws.prepayment_amount,
        )
    )
    await prompt_screen(message, text, admin_hours_keyboard(), state=state)


@router.callback_query(AdminCallback.filter(F.action == "schedule"))
async def admin_schedule(
    callback: CallbackQuery,
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    await state.clear()
    text, markup = await _schedule_hub(schedule)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "days_list"))
async def admin_days_list(
    callback: CallbackQuery,
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    await state.clear()
    text, markup = await _days_list_screen(schedule)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "add_day"))
async def admin_add_day_start(
    callback: CallbackQuery,
    settings: Settings,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    schedule: ScheduleService,
) -> None:
    if not _ensure_admin(settings, message.from_user.id if message.from_user else None):
        return
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
        except AppError:
            skipped.append(format_date_short(day))

    await state.clear()
    parts = []
    if created:
        parts.append("Добавлено ✨\n" + "\n".join(f"· {d}" for d in created))
    if skipped:
        parts.append("Уже были 🤍\n" + "\n".join(f"· {d}" for d in skipped))
    if past:
        parts.append("Пропущено (уже прошло):\n" + "\n".join(f"· {d}" for d in past))
    if bad:
        parts.append("Не разобраны:\n" + "\n".join(f"· {d}" for d in bad[:8]))
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
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    schedule: ScheduleService,
) -> None:
    if not _ensure_admin(settings, message.from_user.id if message.from_user else None):
        return
    data = await state.get_data()
    day_id = data.get("edit_day_id")
    if not day_id:
        await state.clear()
        return
    try:
        open_t, close_t, step = parse_hours_message(message.text or "")
        day = await schedule.set_day_hours(day_id, open_t, close_t, step)
    except AppError as exc:
        await prompt_screen(message, exc.message, state=state)
        return
    except ValueError:
        await prompt_screen(
            message,
            "Формат: <code>11:00-20:00</code>",
            state=state,
        )
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
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    try:
        await schedule.clear_day_override(callback_data.item_id)
        await callback.answer("Как в настройках ✨")
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await state.clear()
    text, markup = await _day_card(schedule, callback_data.item_id)
    await show_screen(callback, "Готово ✨ часы как в настройках\n\n" + text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "del_day"))
async def admin_del_day_ask(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    try:
        day = await schedule.get_day(callback_data.item_id)
    except AppError as exc:
        await show_screen(callback, exc.message, state=state)
        return
    label = format_date_short(day.day)
    await show_screen(
        callback,
        f"<b>Удалить {label}?</b>\n\n"
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
    settings: Settings,
    schedule: ScheduleService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    text, markup = await _bookings_hub(bookings)
    await show_screen(callback, text, markup, state=state)


@router.callback_query(AdminCallback.filter(F.action == "book_day"))
async def admin_book_day(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    settings: Settings,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await callback.answer()
    items = await bookings.list_for_working_day(callback_data.item_id)
    label = format_date_short(items[0].slot.working_day.day) if items else "день"
    await _send_bookings_list(callback, bookings, items, f"Записи · {label}", state)


async def _send_bookings_list(
    callback: CallbackQuery,
    bookings: BookingService,
    items: list,
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
    settings: Settings,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    bookings: BookingService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    bookings: BookingService,
    notify: NotifyService,
    state: FSMContext,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    try:
        booking = await bookings.cancel_booking(callback_data.item_id, by_admin=True)
        await callback.answer("Отменено")
        text, markup = await _bookings_hub(bookings)
        await show_screen(
            callback,
            "Запись отменена.\n\n" + text,
            markup,
            state=state,
        )
        try:
            await callback.bot.send_message(  # type: ignore[union-attr]
                booking.telegram_user_id,
                "Твоя запись отменена мастером. Если это ошибка — напиши напрямую.",
            )
        except Exception:
            pass
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)


@router.callback_query(AdminCallback.filter(F.action == "reschedule"))
async def admin_reschedule_start(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    settings: Settings,
    state: FSMContext,
    schedule: ScheduleService,
    bookings: BookingService,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
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
    settings: Settings,
    state: FSMContext,
    schedule: ScheduleService,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        return
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
    settings: Settings,
    state: FSMContext,
    bookings: BookingService,
) -> None:
    if not _ensure_admin(settings, callback.from_user.id):
        return
    await callback.answer()
    data = await state.get_data()
    booking_id = data.get("reschedule_booking_id")
    if not booking_id:
        await state.clear()
        return
    try:
        booking = await bookings.reschedule(booking_id, callback_data.slot_id)
    except AppError as exc:
        text, markup = await _bookings_hub(bookings)
        await show_screen(callback, exc.message + "\n\n" + text, markup, state=state)
        await state.clear()
        return
    await state.clear()
    text, markup = await _bookings_hub(bookings)
    await show_screen(
        callback,
        "Перенесено.\n\n" + format_admin_booking_card(booking) + "\n\n" + text,
        markup,
        state=state,
    )
    try:
        day = booking.slot.working_day.day
        t = booking.slot.start_time
        await callback.bot.send_message(  # type: ignore[union-attr]
            booking.telegram_user_id,
            f"Мастер перенёс твою запись на {format_date(day)} в {format_time(t)}.",
        )
    except Exception:
        pass
