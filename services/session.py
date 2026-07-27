"""In-memory session — whether user opened the menu.

Will be replaced by a DB-backed user repository later.
"""

from __future__ import annotations


class SessionService:
    """Track users who have pressed Start in this process lifetime."""

    def __init__(self) -> None:
        self._started: set[int] = set()

    def mark_started(self, user_id: int) -> None:
        self._started.add(user_id)

    def has_started(self, user_id: int) -> bool:
        return user_id in self._started

    def clear(self) -> None:
        self._started.clear()
