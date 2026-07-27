"""Portfolio — one photo, cached file_id for fast swipe."""

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputMediaPhoto

from callbacks.factories import MenuCallback, PortfolioCallback
from config.settings import Settings
from domain.enums import CallbackAction
from presentation.keyboards.menu import footer_keyboard
from presentation.keyboards.portfolio import portfolio_keyboard
from presentation.texts.context import format_message
from presentation.texts.messages import PORTFOLIO_CAPTION, PORTFOLIO_EMPTY
from presentation.ui.screens import delete_message_safe, show_text
from services.portfolio_service import PortfolioService

router = Router(name="portfolio")


@router.callback_query(MenuCallback.filter(F.action == CallbackAction.PORTFOLIO))
async def portfolio_from_menu(
    callback: CallbackQuery,
    portfolio: PortfolioService,
    settings: Settings,
) -> None:
    await callback.answer()
    await _show_portfolio(callback, 0, portfolio, settings, from_menu=True)


@router.callback_query(PortfolioCallback.filter())
async def portfolio_navigate(
    callback: CallbackQuery,
    callback_data: PortfolioCallback,
    portfolio: PortfolioService,
    settings: Settings,
) -> None:
    # Counter button — no-op, avoid flicker
    if callback_data.action == CallbackAction.PORTFOLIO:
        await callback.answer()
        return
    await callback.answer()
    await _show_portfolio(
        callback,
        callback_data.page,
        portfolio,
        settings,
        from_menu=False,
    )


async def _show_portfolio(
    callback: CallbackQuery,
    index: int,
    portfolio: PortfolioService,
    settings: Settings,
    from_menu: bool,
) -> None:
    if not portfolio.has_images:
        await show_text(
            callback,
            format_message(PORTFOLIO_EMPTY, settings),
            footer_keyboard(),
        )
        return

    _, index, total = portfolio.get_image_at(index)
    caption = PORTFOLIO_CAPTION.format(current=index + 1, total=total)
    keyboard = portfolio_keyboard(index, total)
    media = portfolio.get_media(index)

    if callback.message.photo and not from_menu:
        try:
            edited = await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=media,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=keyboard,
            )
            # Prefer file_id from the edited message when Telegram returns it
            photo = getattr(edited, "photo", None) if edited is not None else None
            if photo:
                portfolio.remember_file_id(index, photo[-1].file_id)
            elif isinstance(media, str):
                portfolio.remember_file_id(index, media)
            return
        except TelegramBadRequest:
            pass

    if from_menu:
        await delete_message_safe(callback)

    msg = await callback.message.answer_photo(
        photo=media,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    if msg.photo:
        portfolio.remember_file_id(index, msg.photo[-1].file_id)
