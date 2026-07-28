"""Date and time helpers.

The bot has exactly one clock: Europe/Moscow — the master's phone time.
Every datetime that crosses the persistence boundary must go through
:func:`now_local` / :func:`to_local`, because SQLite silently drops the UTC
offset on write (values come back naive) while Postgres returns aware UTC.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Moscow")


def now_local() -> datetime:
    """Current moment on the bot clock."""
    return datetime.now(LOCAL_TZ)


def to_local(value: datetime | None) -> datetime | None:
    """Normalize a stored datetime to an aware bot-clock datetime."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def today() -> date:
    """Current date on the bot clock."""
    return now_local().date()


def format_date(d: date) -> str:
    """Human-readable Russian date (full)."""
    months = (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    weekdays = (
        "понедельник", "вторник", "среда", "четверг",
        "пятница", "суббота", "воскресенье",
    )
    return f"{d.day} {months[d.month - 1]} {d.year} ({weekdays[d.weekday()]})"


def format_date_short(d: date) -> str:
    """Compact date with year — calendar must stay unambiguous across years."""
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def weekday_short(d: date) -> str:
    """Short weekday for list buttons: пн, вт, …"""
    return ("пн", "вт", "ср", "чт", "пт", "сб", "вс")[d.weekday()]


def format_time(t: time) -> str:
    """Format time as HH:MM."""
    return t.strftime("%H:%M")


def combine_datetime(d: date, t: time) -> datetime:
    """Combine date + time into an aware bot-clock datetime."""
    return datetime.combine(d, t, tzinfo=LOCAL_TZ)
