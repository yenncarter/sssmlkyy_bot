"""HTML card rendering. Presentation only — no persistence, no business rules."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from html import escape
from pathlib import Path

from db.models import Booking
from domain.dates import format_date_short, format_time, now_local
from domain.enums import BookingStatus
from services.db_health import BACKUP_STALE_AFTER, BotStatus


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


def _relative_ru(moment: datetime, *, now: datetime | None = None) -> str:
    """Short human delta for status cards."""
    current = now or now_local()
    delta = current - moment
    if delta < timedelta(0):
        return moment.strftime("%d.%m.%Y %H:%M")
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "только что"
    if seconds < 3600:
        return f"{seconds // 60} мин назад"
    if seconds < 86400:
        return f"{seconds // 3600} ч назад"
    days = delta.days
    if days == 1:
        return "вчера"
    if days < 14:
        return f"{days} дн. назад"
    return moment.strftime("%d.%m.%Y %H:%M")


def _pre_block(rows: list[tuple[str, str]], *, key_width: int = 14) -> str:
    """Aligned monospace key/value table (HTML-escaped)."""
    lines = [f"{key:<{key_width}}{value}" for key, value in rows]
    return f"<pre>{escape('\n'.join(lines))}</pre>"


def format_bot_status(status: BotStatus) -> str:
    """Ops /status card: bold section titles + monospace tables."""
    now = status.collected_at
    problems = status.problems
    n_err = len(problems)

    if not problems:
        head = "<b>Статус</b>  ✅  ок"
    elif status.integrity or (
        status.previous_bookings >= 3 and status.bookings_total == 0
    ):
        head = f"<b>Статус</b>  ⛔️  проблем: <b>{n_err}</b>"
    else:
        head = f"<b>Статус</b>  ⚠️  замечаний: <b>{n_err}</b>"

    parts = [
        head,
        f"<pre>{escape(now.strftime('%d.%m.%Y %H:%M'))}</pre>",
    ]

    if problems:
        parts.append("")
        parts.append("<b>Проблемы</b>")
        problem_text = "\n".join(f"{i}. {p}" for i, p in enumerate(problems, 1))
        parts.append(f"<pre>{escape(problem_text)}</pre>")

    size = _file_size_label(status.db_path) or "—"
    mtime = (
        _relative_ru(status.db_mtime, now=now)
        if status.db_mtime is not None
        else "—"
    )
    db_rows = [
        ("движок", status.backend),
        ("где", "контейнер" if status.in_container else "локально"),
        ("размер", size),
        ("путь", status.db_path or "managed (не файл)"),
        ("хранилище", "ok" if status.storage is None else status.storage),
        ("целостность", "ok" if status.integrity is None else status.integrity),
        ("файл изменён", mtime),
    ]
    parts.extend(["", "<b>База</b>", _pre_block(db_rows)])

    if status.last_backup is None:
        backup_rows = [
            ("последний", "нет"),
            ("состояние", "нет бэкапа" if status.bookings_total > 0 else "пусто — ок"),
        ]
    else:
        stale = (now - status.last_backup) >= BACKUP_STALE_AFTER
        backup_rows = [
            ("последний", status.last_backup.strftime("%d.%m.%Y %H:%M")),
            ("назад", _relative_ru(status.last_backup, now=now)),
            ("состояние", "устарел" if stale else "ok"),
        ]
    parts.extend(["", "<b>Бэкап</b>", _pre_block(backup_rows)])

    book_rows = [
        ("живых", str(status.live_bookings)),
        ("активных", str(status.bookings_active)),
        ("ждут оплату", str(status.bookings_pending)),
        ("отменено", str(status.bookings_cancelled)),
        ("завершено", str(status.bookings_completed)),
        ("всего", str(status.bookings_total)),
    ]
    if status.previous_bookings:
        book_rows.append(("раньше было", str(status.previous_bookings)))
    parts.extend(["", "<b>Записи</b>", _pre_block(book_rows)])

    slots_total = status.slots_total
    free_pct = (
        f"{round(100 * status.slots_free / slots_total)}%"
        if slots_total
        else "—"
    )
    slot_rows = [
        ("свободно", f"{status.slots_free} / {slots_total}  ({free_pct})"),
        ("hold", str(status.slots_held)),
        ("занято", str(status.slots_booked)),
        ("закрыто", str(status.slots_blocked)),
        ("дней вперёд", f"{status.days_upcoming} / {status.days_total} всего"),
    ]
    parts.extend(["", "<b>Слоты</b>", _pre_block(slot_rows)])

    parts.append("")
    parts.append("<b>Ближайшие</b>")
    if status.next_visits:
        visit_rows = [
            (visit.when, f"{visit.name}  [{visit.status}]")
            for visit in status.next_visits
        ]
        parts.append(_pre_block(visit_rows, key_width=18))
    else:
        parts.append("<pre>—</pre>")

    cfg_rows = [
        ("часы", f"{status.open_time}–{status.close_time}"),
        ("шаг слота", f"{status.slot_minutes} мин"),
        ("hold", f"{status.hold_minutes} мин"),
        ("предоплата", status.prepayment),
        ("админов", str(status.admins)),
        ("канал", status.channel),
        ("кэш фото", str(status.media_cached)),
    ]
    parts.extend(["", "<b>Конфиг</b>", _pre_block(cfg_rows)])
    return "\n".join(parts)
