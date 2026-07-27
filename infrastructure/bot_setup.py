"""Register bot UI on startup."""

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonDefault


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть меню"),
        BotCommand(command="admin", description="Админ-панель"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
