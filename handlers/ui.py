"""Welcome screen helpers."""

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

from config.settings import settings
from keyboards.menu import main_menu_keyboard
from keyboards.reply import remove_reply_keyboard
from texts.messages import MAIN_MENU, WELCOME
from utils.text_context import format_message


def welcome_caption() -> str:
    return format_message(WELCOME)


def menu_caption() -> str:
    return format_message(MAIN_MENU)


async def send_welcome(message: Message) -> None:
    """Hide reply Start button, then show cover + inline menu."""
    try:
        remove_msg = await message.answer(
            "🤍",
            reply_markup=remove_reply_keyboard(),
        )
        try:
            await remove_msg.delete()
        except TelegramBadRequest:
            pass
    except TelegramBadRequest:
        pass

    await message.answer_photo(
        photo=FSInputFile(settings.welcome_image),
        caption=welcome_caption(),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def show_main_menu(callback: CallbackQuery) -> None:
    caption = menu_caption()
    markup = main_menu_keyboard()
    photo = FSInputFile(settings.welcome_image)

    if callback.message.photo:
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=markup,
            )
            return
        except TelegramBadRequest:
            pass

    await delete_message_safe(callback)
    await callback.message.answer_photo(
        photo=photo,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def delete_message_safe(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
