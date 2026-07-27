"""Portfolio navigation — full-width nav when few actions."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import PortfolioCallback
from domain.enums import CallbackAction
from presentation.keyboards.menu import back_button
from presentation.texts.messages import BTN_PORTFOLIO_NEXT, BTN_PORTFOLIO_PREV


def portfolio_keyboard(index: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if total > 1:
        has_prev = index > 0
        has_next = index < total - 1
        if has_prev and has_next:
            builder.row(
                InlineKeyboardButton(
                    text=BTN_PORTFOLIO_PREV,
                    callback_data=PortfolioCallback(
                        action=CallbackAction.PORTFOLIO_PREV,
                        page=index - 1,
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=BTN_PORTFOLIO_NEXT,
                    callback_data=PortfolioCallback(
                        action=CallbackAction.PORTFOLIO_NEXT,
                        page=index + 1,
                    ).pack(),
                ),
            )
        elif has_prev:
            builder.row(
                InlineKeyboardButton(
                    text=BTN_PORTFOLIO_PREV,
                    callback_data=PortfolioCallback(
                        action=CallbackAction.PORTFOLIO_PREV,
                        page=index - 1,
                    ).pack(),
                ),
            )
        elif has_next:
            builder.row(
                InlineKeyboardButton(
                    text=BTN_PORTFOLIO_NEXT,
                    callback_data=PortfolioCallback(
                        action=CallbackAction.PORTFOLIO_NEXT,
                        page=index + 1,
                    ).pack(),
                ),
            )

    builder.row(back_button())
    return builder.as_markup()
