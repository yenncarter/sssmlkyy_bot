"""In-memory Telegram file_id cache for media."""

from __future__ import annotations


class MediaCache:
    """Cache Telegram file_id values to avoid re-uploading local files."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._ids.get(key)

    def set(self, key: str, file_id: str) -> None:
        self._ids[key] = file_id

    def clear(self) -> None:
        self._ids.clear()
