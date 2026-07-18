"""Bot context middleware — inject services."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject

from services.portfolio_service import PortfolioService
from services.subscription_service import SubscriptionService


class BotContextMiddleware(BaseMiddleware):
    """Inject bot services into handler data."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._subscription = SubscriptionService(bot)
        self._portfolio = PortfolioService()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["subscription"] = self._subscription
        data["portfolio"] = self._portfolio
        return await handler(event, data)
