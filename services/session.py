"""In-memory session — whether user opened the menu."""

_started: set[int] = set()


def mark_started(user_id: int) -> None:
    _started.add(user_id)


def has_started(user_id: int) -> bool:
    return user_id in _started
