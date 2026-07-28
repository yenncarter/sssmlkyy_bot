"""Parsing and normalization of admin/client free-text input.

Every function here is total: it either returns a valid domain value or raises
:class:`ValidationError` with a message that is safe to show to the user.
No other exception type may escape.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from html import escape

from domain.dates import today
from domain.exceptions import ValidationError
from domain.slots import DEFAULT_SLOT_MINUTES, generate_slot_times

NAME_MIN_LEN = 2
NAME_MAX_LEN = 100
PHONE_MIN_DIGITS = 10
PHONE_MAX_DIGITS = 15  # ITU-T E.164
PREPAYMENT_MAX = 1_000_000

_DAY_SPLIT_RE = re.compile(r"[\s,;]+")
_HOURS_HINT = "Формат: <code>10:00-22:00</code>"


def parse_times_line(raw: str) -> list[time]:
    """Parse '10:00, 11:30, 13:00' or multiline times."""
    parts = [p.strip() for p in raw.replace(";", ",").replace("\n", ",").split(",")]
    times: list[time] = []
    for part in parts:
        if not part:
            continue
        hh, _, mm = part.partition(":")
        try:
            times.append(time(int(hh), int(mm)))
        except ValueError as exc:
            raise ValidationError(
                f"Не поняла время «{safe_echo(part)}». Формат: 10:00, 11:30, 13:00"
            ) from exc
    return times


def _single_time(raw: str) -> time:
    """One time value, or a validation error — never IndexError."""
    times = parse_times_line(raw)
    if not times:
        raise ValidationError(_HOURS_HINT)
    return times[0]


def parse_hours_message(raw: str) -> tuple[time, time, int]:
    """
    Parse open–close hours. Slot step is always DEFAULT_SLOT_MINUTES (hourly).
    Formats: 10:00-22:00 | 10:00 22:00
    Trailing numbers (legacy step) are ignored.
    """
    cleaned = raw.strip().lower().replace("–", "-").replace("—", "-")
    parts = cleaned.replace(",", " ").split()
    if not parts:
        raise ValidationError(_HOURS_HINT)

    if "-" in parts[0]:
        left, _, right = parts[0].partition("-")
        open_t = _single_time(left)
        close_t = _single_time(right)
    elif len(parts) >= 2:
        open_t = _single_time(parts[0])
        close_t = _single_time(parts[1])
    else:
        raise ValidationError(_HOURS_HINT)

    step = DEFAULT_SLOT_MINUTES
    generate_slot_times(open_t, close_t, step)
    return open_t, close_t, step


def parse_day(raw: str) -> date:
    """Accept DD.MM, DD.MM.YYYY, DD.MM.YY, YYYY-MM-DD.

    DD.MM is stored as a real calendar date with year:
    this year if still upcoming, otherwise next year (bot clock).
    Dates in the past are rejected.
    """
    raw = raw.strip()
    parsed: date | None = None
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue

    if parsed is None:
        parsed = _parse_day_month(raw)

    if parsed < today():
        raise ValidationError(
            f"Дата {parsed.day:02d}.{parsed.month:02d}.{parsed.year} уже прошла."
        )
    return parsed


def _parse_day_month(raw: str) -> date:
    """DD.MM → nearest upcoming occurrence."""
    day_part, sep, month_part = raw.partition(".")
    if not sep:
        raise ValidationError(
            "Дата в формате <code>01.10</code> или <code>01.10.2026</code>"
        )
    try:
        day_n = int(day_part)
        month_n = int(month_part)
    except ValueError as exc:
        raise ValidationError(
            "Дата в формате <code>01.10</code> или <code>01.10.2026</code>"
        ) from exc

    now = today()
    for year in (now.year, now.year + 1):
        try:
            candidate = date(year, month_n, day_n)
        except ValueError:
            continue  # 29.02 in a non-leap year — try the next one
        if candidate >= now:
            return candidate
    raise ValidationError(f"Такой даты не существует: {safe_echo(raw)}")


def parse_days_column(raw: str) -> tuple[list[date], list[str]]:
    """Parse one or many dates from a column / list → (valid, bad_tokens)."""
    chunks = [c for c in _DAY_SPLIT_RE.split(raw.strip()) if c]
    days: list[date] = []
    seen: set[date] = set()
    errors: list[str] = []
    for part in chunks:
        try:
            parsed = parse_day(part)
        except ValidationError:
            errors.append(part)
            continue
        if parsed not in seen:
            seen.add(parsed)
            days.append(parsed)
    return days, errors


def normalize_full_name(raw: str) -> str:
    """Collapse whitespace and bound the length (DB column is 128 chars)."""
    name = " ".join((raw or "").split())
    if len(name) < NAME_MIN_LEN:
        raise ValidationError("Слишком коротко. Напиши имя ещё раз.")
    if len(name) > NAME_MAX_LEN:
        raise ValidationError("Слишком длинное имя — напиши покороче 🤍")
    return name


def normalize_phone(raw: str) -> str:
    """Keep digits only; preserve a leading +. Rejects junk like '++++++++++'."""
    raw = (raw or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS:
        raise ValidationError("Укажи номер телефона полностью.")
    return f"+{digits}" if raw.startswith("+") else digits


def normalize_prepayment_amount(raw: str) -> str:
    """Master types digits only; always store as «N ₽»."""
    text = (raw or "").strip().lower()
    for junk in ("₽", "руб.", "руб", "р.", "р"):
        text = text.replace(junk, "")
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValidationError("Напиши сумму числом — например 500")
    value = int(digits)
    if value < 1 or value > PREPAYMENT_MAX:
        raise ValidationError("Сумма должна быть от 1 до 1 000 000")
    pretty = f"{value:,}".replace(",", " ")
    return f"{pretty} ₽"


def safe_echo(raw: str, limit: int = 32) -> str:
    """Echo user input back into an HTML message without breaking parse_mode.

    Anything the user typed may contain `<`, which Telegram rejects as broken
    HTML — the master would see a generic error instead of the hint.
    """
    return escape(raw[:limit])
