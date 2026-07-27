"""Channel subscription verification."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config.settings import Settings

logger = logging.getLogger("beauty_bot.subscription")

_ACTIVE = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.RESTRICTED,
}


class SubscriptionService:
    """Check if user is subscribed to the channel."""

    def __init__(self, bot: Bot, settings: Settings) -> None:
        self._bot = bot
        self._settings = settings

    async def is_subscribed(self, user_id: int) -> bool:
        """Return True if user is a channel member (incl. restricted)."""
        try:
            member = await self._bot.get_chat_member(
                chat_id=self._settings.channel_id,
                user_id=user_id,
            )
            return member.status in _ACTIVE
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.error("Subscription check failed for %s: %s", user_id, exc)
            return False

    @property
    def channel_link(self) -> str:
        return self._settings.channel_link
