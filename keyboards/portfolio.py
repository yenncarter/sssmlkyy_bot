"""Portfolio navigation."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.factories import PortfolioCallback
from config.constants import CallbackAction
from keyboards.common import back_button


def portfolio_keyboard(index: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if total > 1:
        nav: list[InlineKeyboardButton] = []
        if index > 0:
            nav.append(
                InlineKeyboardButton(
                    text="‹",
                    callback_data=PortfolioCallback(
                        action=CallbackAction.PORTFOLIO_PREV,
                        page=index - 1,
                    ).pack(),
                ),
            )
        nav.append(
            InlineKeyboardButton(
                text=f" {index + 1} / {total} ",
                callback_data=PortfolioCallback(
                    action=CallbackAction.PORTFOLIO,
                    page=index,
                ).pack(),
            ),
        )
        if index < total - 1:
            nav.append(
                InlineKeyboardButton(
                    text="›",
                    callback_data=PortfolioCallback(
                        action=CallbackAction.PORTFOLIO_NEXT,
                        page=index + 1,
                    ).pack(),
                ),
            )
        builder.row(*nav)

    builder.row(back_button())
    return builder.as_markup()
