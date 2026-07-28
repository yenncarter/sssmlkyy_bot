"""Screen helpers — one active message, no chat spam.

Telegram replaces messages older than ~48 hours with an `InaccessibleMessage`
stub that has only `chat` and `message_id`. Touching any other attribute raises
AttributeError, so every callback screen goes through :func:`screen_message`
and falls back to sending a fresh message into the known chat.
"""

from __future__ import annotations

from contextlib import suppress

from aiogram import Bot
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
CAPTION_LIMIT = 1024


def screen_message(callback: CallbackQuery) -> Message | None:
    """The callback's message, but only if it is still fully readable."""
    message = callback.message
    return message if isinstance(message, Message) else None


def _chat_id(callback: CallbackQuery) -> int | None:
    """Available even for inaccessible messages — enough to send a new screen."""
    message = callback.message
    return message.chat.id if message is not None else None


async def delete_message_safe(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        return
    await _delete_chat_message(callback.bot, message.chat.id, message.message_id)


async def _delete_chat_message(
    bot: Bot | None,
    chat_id: int,
    message_id: int | None,
) -> None:
    if bot is None or not message_id:
        return
    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id, message_id)


async def _send_screen(
    bot: Bot | None,
    chat_id: int | None,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> Message | None:
    if bot is None or chat_id is None:
        return None
    return await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )


async def show_text(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Replace the current callback screen with a text message.

    If the current screen is a photo and the caption fits Telegram's limit,
    edit the caption in place — no photo→text jump.
    """
    message = screen_message(callback)
    if message is None:
        # Stale screen: nothing to edit, but the chat is still reachable.
        await delete_message_safe(callback)
        return await _send_screen(callback.bot, _chat_id(callback), text, markup)

    if message.photo:
        if len(text) <= CAPTION_LIMIT:
            try:
                edited = await message.edit_caption(
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return edited if isinstance(edited, Message) else message
            except TelegramBadRequest:
                pass
        await delete_message_safe(callback)
        return await _send_screen(callback.bot, message.chat.id, text, markup)

    try:
        edited = await message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        return edited if isinstance(edited, Message) else message
    except TelegramBadRequest:
        await delete_message_safe(callback)
        return await _send_screen(callback.bot, message.chat.id, text, markup)


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
        await state.update_data({UI_MSG_KEY: msg.message_id})


async def prompt_screen(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    state: FSMContext | None = None,
    delete_user: bool = True,
) -> Message:
    """After a user text reply: drop the previous UI, send one new screen."""
    bot = message.bot
    chat_id = message.chat.id
    if state is not None:
        data = await state.get_data()
        await _delete_chat_message(bot, chat_id, data.get(UI_MSG_KEY))
    if delete_user:
        with suppress(TelegramBadRequest):
            await message.delete()
    msg = await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    if state is not None:
        await state.update_data({UI_MSG_KEY: msg.message_id})
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
    """Hide the reply Start button, then show cover + inline menu."""
    with suppress(TelegramBadRequest):
        remove_msg = await message.answer("·", reply_markup=remove_reply_keyboard())
        with suppress(TelegramBadRequest):
            await remove_msg.delete()

    msg = await message.answer_photo(
        photo=_welcome_media(settings, media_cache),
        caption=format_message(WELCOME, settings),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(settings),
    )
    if msg.photo:
        await media_cache.remember(WELCOME_CACHE_KEY, msg.photo[-1].file_id)


async def show_main_menu(
    callback: CallbackQuery,
    settings: Settings,
    media_cache: MediaCache,
) -> None:
    caption = format_message(MAIN_MENU, settings)
    markup = main_menu_keyboard(settings)
    media = _welcome_media(settings, media_cache)
    message = screen_message(callback)

    if message is not None and message.photo:
        try:
            edited = await message.edit_media(
                media=InputMediaPhoto(
                    media=media,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=markup,
            )
            photo = getattr(edited, "photo", None) if edited is not None else None
            if photo:
                await media_cache.remember(WELCOME_CACHE_KEY, photo[-1].file_id)
            elif isinstance(media, str):
                await media_cache.remember(WELCOME_CACHE_KEY, media)
            return
        except TelegramBadRequest:
            pass

    # Text screen, stale screen or failed photo edit → restore cover + menu.
    await delete_message_safe(callback)
    chat_id = _chat_id(callback)
    bot = callback.bot
    if bot is None or chat_id is None:
        return
    msg = await bot.send_photo(
        chat_id,
        photo=media,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )
    if msg.photo:
        await media_cache.remember(WELCOME_CACHE_KEY, msg.photo[-1].file_id)
