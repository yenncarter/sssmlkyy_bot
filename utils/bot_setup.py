"""Register bot UI on startup."""

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonDefault


async def setup_bot_commands(bot: Bot) -> None:
    """Hide the commands menu pill — navigation via Start button and inline keys."""
    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть меню"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
