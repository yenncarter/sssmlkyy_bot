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
        return moment.strftime("%d.%m %H:%M")
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "сейчас"
    if seconds < 3600:
        return f"{seconds // 60}м"
    if seconds < 86400:
        return f"{seconds // 3600}ч"
    days = delta.days
    if days == 1:
        return "1д"
    if days < 14:
        return f"{days}д"
    return moment.strftime("%d.%m.%Y")


def _flag(ok: bool) -> str:
    return "✅" if ok else "❌"


def format_bot_status(status: BotStatus) -> str:
    """Ops dashboard for /status — scan in 3 seconds, not a client card."""
    now = status.collected_at
    problems = status.problems
    n_err = len(problems)

    if not problems:
        head = "🛠 <b>STATUS</b>  ✅"
    elif status.integrity or (
        status.previous_bookings >= 3 and status.bookings_total == 0
    ):
        head = f"🛠 <b>STATUS</b>  ⛔️  <b>{n_err}</b>"
    else:
        head = f"🛠 <b>STATUS</b>  ⚠️  <b>{n_err}</b>"

    lines = [
        head,
        f"<code>{now.strftime('%d.%m.%Y %H:%M')}</code>",
    ]

    if problems:
        lines.append("")
        for problem in problems:
            lines.append(f"⚠️ {escape(problem)}")

    size = _file_size_label(status.db_path) or "—"
    where = "🐳" if status.in_container else "💻"
    path = status.db_path or "managed"
    mtime = (
        _relative_ru(status.db_mtime, now=now)
        if status.db_mtime is not None
        else "—"
    )
    lines.extend(
        [
            "",
            "💾 <b>DB</b>",
            (
                f"{escape(status.backend)} · {where} · <b>{size}</b>"
                f" · ✏️ {mtime}"
            ),
            f"<code>{escape(path)}</code>",
            (
                f"🗄 {_flag(status.storage is None)}"
                f"  🧩 {_flag(status.integrity is None)}"
            ),
        ]
    )
    if status.storage:
        lines.append(f"🗄 {escape(status.storage)}")
    if status.integrity:
        lines.append(f"🧩 {escape(status.integrity)}")

    if status.last_backup is None:
        backup = "❌ нет"
        if status.bookings_total > 0:
            backup += "  ⚠️"
    else:
        stale = (now - status.last_backup) >= BACKUP_STALE_AFTER
        mark = "⚠️" if stale else "✅"
        backup = (
            f"{mark} <b>{status.last_backup.strftime('%d.%m %H:%M')}</b>"
            f" · {_relative_ru(status.last_backup, now=now)}"
        )
    lines.extend(["", f"📦 <b>Backup</b>  {backup}"])

    hist = (
        f" · was <b>{status.previous_bookings}</b>"
        if status.previous_bookings
        else ""
    )
    lines.extend(
        [
            "",
            "📋 <b>Bookings</b>",
            (
                f"🔥 <b>{status.live_bookings}</b>"
                f"   ✅ {status.bookings_active}"
                f"  ⏳ {status.bookings_pending}"
                f"  ❌ {status.bookings_cancelled}"
                f"  🏁 {status.bookings_completed}"
            ),
            f"Σ <b>{status.bookings_total}</b>{hist}",
        ]
    )

    slots_total = status.slots_total
    free_pct = (
        f"{round(100 * status.slots_free / slots_total)}%"
        if slots_total
        else "—"
    )
    lines.extend(
        [
            "",
            "🗓 <b>Slots</b>",
            (
                f"🟢 <b>{status.slots_free}</b>/{slots_total} ({free_pct})"
                f"  ⏳ {status.slots_held}"
                f"  🔒 {status.slots_booked}"
                f"  🚫 {status.slots_blocked}"
            ),
            f"📅 <b>{status.days_upcoming}</b> ahead / {status.days_total} total",
        ]
    )

    lines.extend(["", "📌 <b>Next</b>"])
    if status.next_visits:
        for visit in status.next_visits:
            mark = "⏳" if visit.status == "ждёт оплату" else "✅"
            lines.append(
                f"{mark} <b>{escape(visit.when)}</b> · {escape(visit.name)}"
            )
    else:
        lines.append("—")

    lines.extend(
        [
            "",
            "⚙️ <b>Runtime</b>",
            (
                f"⏱ <b>{status.open_time}–{status.close_time}</b>"
                f" · {status.slot_minutes}м · hold {status.hold_minutes}м"
            ),
            (
                f"💳 {escape(status.prepayment)}"
                f" · 👤 {status.admins}"
                f" · 🖼 {status.media_cached}"
                f" · 📢 {escape(status.channel)}"
            ),
        ]
    )
    return "\n".join(lines)
