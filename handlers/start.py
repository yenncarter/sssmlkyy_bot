"""Start command handler."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config.settings import Settings
from presentation.keyboards.admin import admin_home_keyboard
from presentation.keyboards.reply import START_BUTTON_ALIASES
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
    if message.from_user:
        session.mark_started(message.from_user.id)

    if settings.is_admin(message.from_user.id if message.from_user else None):
        from presentation.texts.messages import ADMIN_HOME

        await message.answer(
            ADMIN_HOME
            + f"\n\nID: <code>{message.from_user.id}</code>",  # type: ignore[union-attr]
            reply_markup=admin_home_keyboard(),
        )
        return

    await send_welcome(message, settings, media_cache)
