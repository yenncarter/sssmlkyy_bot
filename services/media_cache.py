"""Telegram file_id cache: in-memory reads, database writes.

Reads stay synchronous because they happen while building a screen; the whole
table is preloaded once at startup. Writes are async and persist, so a restart
no longer forces a re-upload of every image.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import MediaFile

logger = logging.getLogger("beauty_bot.media")


class MediaCache:
    """Cache Telegram file_id values to avoid re-uploading local files."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._sf = session_factory
        self._ids: dict[str, str] = {}

    async def load(self) -> int:
        """Warm the in-memory map from the database. Returns the row count."""
        if self._sf is None:
            return 0
        try:
            async with self._sf() as session:
                rows = (
                    await session.execute(select(MediaFile.key, MediaFile.file_id))
                ).all()
        except SQLAlchemyError:
            logger.exception("Не удалось загрузить кэш file_id")
            return 0
        self._ids = {key: file_id for key, file_id in rows}
        return len(self._ids)

    def get(self, key: str) -> str | None:
        return self._ids.get(key)

    @property
    def size(self) -> int:
        return len(self._ids)

    async def remember(self, key: str, file_id: str) -> None:
        if self._ids.get(key) == file_id:
            return
        self._ids[key] = file_id
        if self._sf is None:
            return
        try:
            async with self._sf() as session:
                row = await session.get(MediaFile, key)
                if row is None:
                    session.add(MediaFile(key=key, file_id=file_id))
                else:
                    row.file_id = file_id
                await session.commit()
        except SQLAlchemyError:
            # In-memory copy still works for this process lifetime.
            logger.exception("Не удалось сохранить file_id для %s", key)
