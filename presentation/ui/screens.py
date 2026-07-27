"""Screen helpers — one active message, no chat spam."""

from __future__ import annotations

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from config.settings import Settings
from presentation.keyboards.menu import main_menu_keyboard
from presentation.keyboards.reply import remove_reply_keyboard
from presentation.texts.context import format_message
from presentation.texts.messages import MAIN_MENU, WELCOME
from services.media_cache import MediaCache


WELCOME_CACHE_KEY = "welcome:cover"
UI_MSG_KEY = "ui_msg_id"


async def delete_message_safe(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass


async def _delete_chat_message(bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


async def show_text(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Replace current callback screen with a text message (edit or delete+send).

    If the current screen is a photo and caption fits Telegram's limit,
    edit caption in place — no photo→text jump.
    """
    if callback.message is None:
        return None

    if callback.message.photo:
        # Caption limit is 1024; keep cover photo when content fits.
        if len(text) <= 1024:
            try:
                edited = await callback.message.edit_caption(
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return edited if isinstance(edited, Message) else callback.message
            except TelegramBadRequest:
                pass
        await delete_message_safe(callback)
        return await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    try:
        edited = await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        return edited if isinstance(edited, Message) else callback.message
    except TelegramBadRequest:
        await delete_message_safe(callback)
        return await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )


async def show_screen(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    state: FSMContext | None = None,
) -> None:
    """Admin/client callback navigation — keep a single screen."""
    msg = await show_text(callback, text, markup)
    if state is not None and msg is not None:
        await state.update_data(**{UI_MSG_KEY: msg.message_id})


async def prompt_screen(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    state: FSMContext | None = None,
    delete_user: bool = True,
) -> Message:
    """
    After a user text reply: remove previous UI (+ optional user message), send one new screen.
    """
    bot = message.bot
    chat_id = message.chat.id
    if state is not None:
        data = await state.get_data()
        await _delete_chat_message(bot, chat_id, data.get(UI_MSG_KEY))
    if delete_user:
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
    msg = await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    if state is not None:
        await state.update_data(**{UI_MSG_KEY: msg.message_id})
    return msg


async def track_prompt(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    state: FSMContext,
) -> Message:
    """Send a prompt and remember its message id (for later cleanup)."""
    msg = await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    await state.update_data(**{UI_MSG_KEY: msg.message_id})
    return msg


def _welcome_media(settings: Settings, media_cache: MediaCache) -> str | FSInputFile:
    cached = media_cache.get(WELCOME_CACHE_KEY)
    if cached:
        return cached
    return FSInputFile(settings.welcome_image)


async def send_welcome(
    message: Message,
    settings: Settings,
    media_cache: MediaCache,
) -> None:
    """Hide reply Start button, then show cover + inline menu."""
    try:
        remove_msg = await message.answer("·", reply_markup=remove_reply_keyboard())
        try:
            await remove_msg.delete()
        except TelegramBadRequest:
            pass
    except TelegramBadRequest:
        pass

    msg = await message.answer_photo(
        photo=_welcome_media(settings, media_cache),
        caption=format_message(WELCOME, settings),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(settings),
    )
    if msg.photo:
        media_cache.set(WELCOME_CACHE_KEY, msg.photo[-1].file_id)


async def show_main_menu(
    callback: CallbackQuery,
    settings: Settings,
    media_cache: MediaCache,
) -> None:
    caption = format_message(MAIN_MENU, settings)
    markup = main_menu_keyboard(settings)
    media = _welcome_media(settings, media_cache)

    if callback.message and callback.message.photo:
        try:
            edited = await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=media,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=markup,
            )
            photo = getattr(edited, "photo", None) if edited is not None else None
            if photo:
                media_cache.set(WELCOME_CACHE_KEY, photo[-1].file_id)
            elif isinstance(media, str):
                media_cache.set(WELCOME_CACHE_KEY, media)
            return
        except TelegramBadRequest:
            pass

    # Text screen or failed photo edit → restore cover + menu.
    await delete_message_safe(callback)
    if callback.message is None:
        return
    msg = await callback.message.answer_photo(
        photo=media,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )
    if msg.photo:
        media_cache.set(WELCOME_CACHE_KEY, msg.photo[-1].file_id)
