"""Portfolio — one photo, cached file_id for fast swipe."""

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputMediaPhoto

from callbacks.factories import MenuCallback, PortfolioCallback
from config.constants import CallbackAction
from handlers.ui import delete_message_safe as _delete_safe
from keyboards.common import footer_keyboard
from keyboards.portfolio import portfolio_keyboard
from services.portfolio_service import PortfolioService
from texts.messages import PORTFOLIO_CAPTION, PORTFOLIO_EMPTY
from utils.text_context import format_message

router = Router(name="portfolio")


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.PORTFOLIO))
async def portfolio_from_menu(
    callback: CallbackQuery,
    portfolio: PortfolioService,
) -> None:
    await callback.answer()
    await _show_portfolio(callback, 0, portfolio, from_menu=True)


@router.callback_query(PortfolioCallback.filter())
async def portfolio_navigate(
    callback: CallbackQuery,
    callback_data: PortfolioCallback,
    portfolio: PortfolioService,
) -> None:
    await callback.answer()
    await _show_portfolio(callback, callback_data.page, portfolio, from_menu=False)


async def _show_portfolio(
    callback: CallbackQuery,
    index: int,
    portfolio: PortfolioService,
    from_menu: bool,
) -> None:
    if not portfolio.has_images:
        await _render_text(
            callback,
            format_message(PORTFOLIO_EMPTY),
            from_menu=from_menu,
        )
        return

    _, index, total = portfolio.get_image_at(index)
    caption = PORTFOLIO_CAPTION.format(current=index + 1, total=total)
    keyboard = portfolio_keyboard(index, total)
    media = portfolio.get_media(index)

    if callback.message.photo and not from_menu:
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=media, caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=keyboard,
            )
            if callback.message.photo:
                portfolio.remember_file_id(index, callback.message.photo[-1].file_id)
            return
        except TelegramBadRequest:
            pass

    if from_menu:
        await _delete_safe(callback)

    msg = await callback.message.answer_photo(
        photo=media,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    if msg.photo:
        portfolio.remember_file_id(index, msg.photo[-1].file_id)


async def _render_text(
    callback: CallbackQuery,
    text: str,
    from_menu: bool,
) -> None:
    markup = footer_keyboard()
    if from_menu and not callback.message.photo:
        try:
            await callback.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            return
        except TelegramBadRequest:
            pass

    if from_menu:
        await _delete_safe(callback)

    await callback.message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
