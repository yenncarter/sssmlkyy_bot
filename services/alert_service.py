"""Operational alerts to the master's private chat.

Deliberately dependency-light: this is the channel that has to work when the
database is broken or a background job is crashing, so it touches nothing but
the bot session and the settings.
"""

from __future__ import annotations

import logging
import time
from typing import Final

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from config.settings import Settings
from presentation.texts.alerts import ALERT_PREFIX

logger = logging.getLogger("beauty_bot.alerts")

# One alert per topic per this many seconds. An error storm must not turn the
# bot into its own flood source (Telegram would rate-limit it, and the master
# would stop reading).
DEFAULT_COOLDOWN_SECONDS: Final = 900.0


class AlertService:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._cooldown = cooldown_seconds
        self._sent_at: dict[str, float] = {}

    async def send(self, key: str, text: str, *, force: bool = False) -> bool:
        """Alert the master about `key`. Returns True when a message went out.

        `key` is the topic, not the text: repeated failures of the same kind
        collapse into one message per cooldown window.
        """
        chat_id = self._settings.primary_admin_id
        if chat_id is None:
            logger.warning("Алерт %s не отправлен: ADMIN_TELEGRAM_IDS не задан", key)
            return False

        now = time.monotonic()
        if not force and now - self._sent_at.get(key, -self._cooldown) < self._cooldown:
            logger.debug("Алерт %s подавлен (cooldown)", key)
            return False

        try:
            await self._bot.send_message(
                chat_id,
                ALERT_PREFIX + text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as exc:
            logger.error("Алерт %s не доставлен: %s", key, exc)
            return False

        self._sent_at[key] = now
        logger.info("Алерт %s отправлен мастеру", key)
        return True
