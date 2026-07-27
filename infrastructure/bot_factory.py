"""Create Telegram Bot client with network tuning."""

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from config.settings import Settings


def create_bot(settings: Settings) -> Bot:
    """Build Bot session with timeout and safe defaults (no proxy)."""
    session = AiohttpSession(
        timeout=settings.request_timeout,
        limit=20,
    )
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
