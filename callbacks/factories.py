"""CallbackData factories."""

from aiogram.filters.callback_data import CallbackData

from config.constants import CallbackAction


class MenuCallback(CallbackData, prefix="menu"):
    """Main menu callbacks."""

    action: CallbackAction


class SubscriptionCallback(CallbackData, prefix="sub"):
    """Subscription callbacks."""

    action: CallbackAction


class PortfolioCallback(CallbackData, prefix="pf"):
    """Portfolio navigation callbacks."""

    action: CallbackAction
    page: int = 0
