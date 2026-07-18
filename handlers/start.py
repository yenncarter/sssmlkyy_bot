"""Start command handler."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from handlers.ui import send_welcome
from keyboards.reply import START_BUTTON_TEXT
from services.session import mark_started

router = Router(name="start")


@router.message(CommandStart())
@router.message(F.text == START_BUTTON_TEXT)
async def cmd_start(message: Message) -> None:
    """Welcome cover + menu."""
    mark_started(message.from_user.id)
    await send_welcome(message)
