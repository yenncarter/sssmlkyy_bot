"""Date and time helpers (Europe/Moscow — matches master's phone clock)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Master lives in Samara, but local phone/calendar runs on Moscow time (UTC+3).
LOCAL_TZ = ZoneInfo("Europe/Moscow")
SAMARA_TZ = LOCAL_TZ  # back-compat alias used across the codebase
MOSCOW_TZ = LOCAL_TZ

# How far ahead the calendar will allow booking once scheduling ships.
CALENDAR_DAYS_AHEAD: int = 30


def today() -> date:
    """Current date on the bot clock (Moscow / phone time)."""
    return datetime.now(LOCAL_TZ).date()


def max_calendar_date() -> date:
    """Last selectable calendar date for future booking UI."""
    return today() + timedelta(days=CALENDAR_DAYS_AHEAD)


def is_date_in_range(target: date) -> bool:
    """Whether date falls into the bookable window."""
    return today() <= target <= max_calendar_date()


def parse_time(value: str) -> time:
    """Parse HH:MM into time."""
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


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
    """Combine date + time into timezone-aware bot datetime."""
    return datetime.combine(d, t, tzinfo=LOCAL_TZ)
