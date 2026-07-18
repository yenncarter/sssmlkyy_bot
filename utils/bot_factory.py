"""Create Telegram Bot client with network tuning."""

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from config.settings import Settings


def create_bot(settings: Settings) -> Bot:
    """Build Bot session with optional proxy and safe defaults for Windows."""
    session_kwargs: dict = {"timeout": settings.request_timeout, "limit": 20}

    if settings.proxy_url:
        session_kwargs["proxy"] = settings.proxy_url

    session = AiohttpSession(**session_kwargs)
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
