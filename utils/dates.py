"""Date and time utility functions."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from config.constants import CALENDAR_DAYS_AHEAD

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def today() -> date:
    """Return current date in Moscow timezone."""
    return datetime.now(MOSCOW_TZ).date()


def max_calendar_date() -> date:
    """Return the last selectable calendar date."""
    return today() + timedelta(days=CALENDAR_DAYS_AHEAD)


def is_date_in_range(target: date) -> bool:
    """Check if date is within booking range."""
    return today() <= target <= max_calendar_date()


def parse_time(value: str) -> time:
    """Parse HH:MM string to time object."""
    parts = value.split(":")
    return time(int(parts[0]), int(parts[1]))


def format_date(d: date) -> str:
    """Format date for display."""
    months = (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    weekdays = (
        "понедельник", "вторник", "среда", "четверг",
        "пятница", "суббота", "воскресенье",
    )
    return f"{d.day} {months[d.month - 1]} {d.year} ({weekdays[d.weekday()]})"


def format_time(t: time) -> str:
    """Format time for display."""
    return t.strftime("%H:%M")


def combine_datetime(d: date, t: time) -> datetime:
    """Combine date and time into timezone-aware datetime."""
    return datetime.combine(d, t, tzinfo=MOSCOW_TZ)


def booking_datetime(d: date, t: time) -> datetime:
    """Alias for combine_datetime."""
    return combine_datetime(d, t)
