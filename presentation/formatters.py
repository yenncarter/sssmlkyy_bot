"""HTML card rendering. Presentation only — no persistence, no business rules."""

from __future__ import annotations

from datetime import time
from html import escape
from pathlib import Path

from db.models import Booking
from domain.dates import format_date_short, format_time
from domain.enums import BookingStatus
from services.db_health import BotStatus


def format_hours(open_t: time, close_t: time) -> str:
    return f"{format_time(open_t)}–{format_time(close_t)}"


def format_admin_booking_card(booking: Booking) -> str:
    """Compact card for master: who / when / contact."""
    day = booking.slot.working_day.day
    start = booking.slot.start_time
    uname = f"@{escape(booking.username)}" if booking.username else "нет username"
    lines = [
        f"<b>Запись #{booking.id}</b>",
        f"📅 <b>{format_date_short(day)}</b> · {format_time(start)}",
        "",
        f"<b>{escape(booking.full_name)}</b>",
        escape(booking.phone),
        uname,
    ]
    if booking.status == BookingStatus.PENDING_PAYMENT.value:
        lines.extend(["", "⏳ ждёт оплату"])
    return "\n".join(lines)


def format_client_booking_card(booking: Booking) -> str:
    day = booking.slot.working_day.day
    start = booking.slot.start_time
    lines = [f"✨ <b>{format_date_short(day)} · {format_time(start)}</b>"]
    if booking.status == BookingStatus.PENDING_PAYMENT.value:
        lines.append("ждёт оплату")
    return "\n".join(lines)


def _file_size_label(path: str | None) -> str | None:
    if not path:
        return None
    try:
        size = Path(path).stat().st_size
    except OSError:
        return None
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size / (1024 * 1024):.1f} МБ"


def format_bot_status(status: BotStatus) -> str:
    """Phone-friendly diagnostic card for /status."""
    stamp = status.collected_at.strftime("%d.%m.%Y %H:%M")
    problems = status.problems
    if not problems:
        verdict = "✅ <b>Всё в порядке</b>"
    elif status.integrity or (
        status.previous_bookings >= 3 and status.bookings_total == 0
    ):
        verdict = "⛔️ <b>Нужно внимание</b>"
    else:
        verdict = "⚠️ <b>Есть замечания</b>"

    lines = [
        "🛠 <b>Состояние бота</b>",
        f"<code>{stamp}</code>",
        "",
        verdict,
    ]
    for problem in problems:
        lines.append(f"· {escape(problem)}")

    path = status.db_path or "managed (не файл)"
    size = _file_size_label(status.db_path)
    path_line = escape(path) + (f" · {size}" if size else "")
    lines.extend(
        [
            "",
            "<b>База</b>",
            f"· {escape(status.backend)}",
            f"· {path_line}",
            f"· хранилище: {'ок' if status.storage is None else escape(status.storage)}",
            f"· целостность: {'ок' if status.integrity is None else escape(status.integrity)}",
            f"· контейнер: {'да' if status.in_container else 'нет (локально)'}",
        ]
    )

    lines.extend(
        [
            "",
            "<b>Записи</b>",
            f"· активных: {status.bookings_active}",
            f"· ждут оплату: {status.bookings_pending}",
            f"· отменено: {status.bookings_cancelled}",
            f"· завершено: {status.bookings_completed}",
            f"· всего: {status.bookings_total}"
            + (
                f" (раньше: {status.previous_bookings})"
                if status.previous_bookings
                else ""
            ),
        ]
    )

    lines.extend(
        [
            "",
            "<b>График</b>",
            f"· дней вперёд: {status.days_upcoming} (всего {status.days_total})",
            (
                f"· слоты: свободно {status.slots_free} · бронь {status.slots_held} · "
                f"занято {status.slots_booked} · закрыто {status.slots_blocked}"
            ),
        ]
    )

    if status.next_visits:
        lines.extend(["", "<b>Ближайшие</b>"])
        for visit in status.next_visits:
            lines.append(
                f"· {escape(visit.when)} — {escape(visit.name)} "
                f"<i>({escape(visit.status)})</i>"
            )
    else:
        lines.extend(["", "<b>Ближайшие</b>", "· нет живых записей"])

    if status.last_backup is None:
        backup_line = "ещё не было"
    else:
        backup_line = status.last_backup.strftime("%d.%m.%Y %H:%M")
    lines.extend(["", "<b>Бэкап</b>", f"· {backup_line}"])

    lines.extend(
        [
            "",
            "<b>Настройки</b>",
            f"· часы {status.open_time}–{status.close_time} · шаг {status.slot_minutes} мин",
            f"· предоплата {escape(status.prepayment)} · hold {status.hold_minutes} мин",
            f"· админов: {status.admins}",
            f"· кэш фото: {status.media_cached}",
        ]
    )
    return "\n".join(lines)
