"""Unknown messages — friendly reply with menu."""

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

from config.settings import Settings
from presentation.keyboards.menu import main_menu_keyboard
from presentation.texts.context import format_message
from presentation.texts.messages import PRESS_START, UNKNOWN_MESSAGE
from services.session import SessionService

router = Router(name="fallback")


@router.message(~CommandStart())
async def unknown_message(
    message: Message,
    session: SessionService,
    settings: Settings,
) -> None:
    """Before /start — nudge to open the bot; after — inline menu."""
    user_id = message.from_user.id if message.from_user else 0
    if not session.has_started(user_id):
        await message.answer(
            format_message(PRESS_START, settings),
            parse_mode=ParseMode.HTML,
        )
        return

    await message.answer(
        UNKNOWN_MESSAGE,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(settings),
    )
