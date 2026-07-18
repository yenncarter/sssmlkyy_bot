"""Channel subscription verification."""

import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest

from config.settings import settings

logger = logging.getLogger("beauty_bot.subscription")


class SubscriptionService:
    """Check if user is subscribed to the channel."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def is_subscribed(self, user_id: int) -> bool:
        """Return True if user is a channel member."""
        try:
            member = await self._bot.get_chat_member(
                chat_id=settings.channel_id,
                user_id=user_id,
            )
            return member.status in {
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            }
        except TelegramBadRequest as exc:
            logger.error("Subscription check failed for %s: %s", user_id, exc)
            return False

    @property
    def channel_link(self) -> str:
        """Channel URL for subscribe button."""
        return settings.channel_link
