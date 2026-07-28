"""Persistent key/value store for operational state.

Used by health checks and backups — the values must outlive the container, so
they cannot live in the process memory.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import AppState

logger = logging.getLogger("beauty_bot.app_state")


class AppStateStore:
    """Never raises: a broken state table must not take the bot down with it."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get(self, key: str) -> str | None:
        try:
            async with self._sf() as session:
                return await session.scalar(
                    select(AppState.value).where(AppState.key == key)
                )
        except SQLAlchemyError:
            logger.exception("Не удалось прочитать app_state[%s]", key)
            return None

    async def set(self, key: str, value: str) -> None:
        try:
            async with self._sf() as session:
                row = await session.get(AppState, key)
                if row is None:
                    session.add(AppState(key=key, value=value))
                else:
                    row.value = value
                await session.commit()
        except SQLAlchemyError:
            logger.exception("Не удалось записать app_state[%s]", key)

    async def get_int(self, key: str, default: int = 0) -> int:
        raw = await self.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            logger.warning("app_state[%s] не число: %r", key, raw)
            return default

    async def set_int(self, key: str, value: int) -> None:
        await self.set(key, str(value))
