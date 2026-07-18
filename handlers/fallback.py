"""Unknown messages — friendly reply with menu."""

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

from keyboards.menu import main_menu_keyboard
from keyboards.reply import start_reply_keyboard
from services.session import has_started
from texts.messages import PRESS_START, UNKNOWN_MESSAGE

router = Router(name="fallback")


@router.message(~CommandStart())
async def unknown_message(message: Message) -> None:
    """Before start — only the Start button; after — inline menu."""
    if not has_started(message.from_user.id):
        await message.answer(
            PRESS_START,
            parse_mode=ParseMode.HTML,
            reply_markup=start_reply_keyboard(),
        )
        return

    await message.answer(
        UNKNOWN_MESSAGE,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )
