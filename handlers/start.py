"""Start command handler."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config.settings import Settings
from presentation.keyboards.admin import admin_home_keyboard
from presentation.keyboards.reply import START_BUTTON_ALIASES, strip_reply_keyboard
from presentation.texts.messages import ADMIN_HOME
from presentation.ui.screens import send_welcome
from services.media_cache import MediaCache
from services.session import SessionService

router = Router(name="start")


@router.message(CommandStart())
@router.message(F.text.in_(START_BUTTON_ALIASES))
async def cmd_start(
    message: Message,
    session: SessionService,
    settings: Settings,
    media_cache: MediaCache,
    state: FSMContext,
) -> None:
    await state.clear()
    user_id = message.from_user.id if message.from_user else None
    if user_id is not None:
        session.mark_started(user_id)

    if settings.is_admin(user_id):
        await strip_reply_keyboard(message)
        await message.answer(
            ADMIN_HOME + f"\n\nID: <code>{user_id}</code>",
            reply_markup=admin_home_keyboard(),
        )
        return

    await send_welcome(message, settings, media_cache)
