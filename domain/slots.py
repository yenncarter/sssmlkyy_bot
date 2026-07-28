"""Slot grid rules — pure domain, no persistence."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from math import ceil

from domain.exceptions import ValidationError

DEFAULT_OPEN = time(10, 0)
DEFAULT_CLOSE = time(22, 0)
DEFAULT_SLOT_MINUTES = 60
MIN_SLOT_MINUTES = 15

# Any date works: we only care about the time-of-day arithmetic.
_GRID_EPOCH = date(2000, 1, 1)


def generate_slot_times(
    open_time: time,
    close_time: time,
    slot_minutes: int,
) -> list[time]:
    """Starts from open until the last start strictly before close."""
    if slot_minutes < MIN_SLOT_MINUTES:
        raise ValidationError("Шаг слота минимум 15 минут.")
    if open_time >= close_time:
        raise ValidationError("Время открытия должно быть раньше закрытия.")

    times: list[time] = []
    cursor = datetime.combine(_GRID_EPOCH, open_time)
    end = datetime.combine(_GRID_EPOCH, close_time)
    while cursor < end:
        times.append(cursor.time())
        cursor += timedelta(minutes=slot_minutes)
    if not times:
        raise ValidationError("В этом диапазоне не получается ни одного слота.")
    return times


def slots_needed(duration_minutes: int, step_minutes: int) -> int:
    """How many consecutive grid slots a service of this duration occupies."""
    if step_minutes <= 0:
        return 1
    return max(1, ceil(duration_minutes / step_minutes))
