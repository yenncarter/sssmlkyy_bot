"""Reusable handler filters."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config.settings import Settings
from services.schedule_service import BookingService


class IsAdmin(BaseFilter):
    """Router-level admin gate.

    `settings` comes from BotContextMiddleware, which is registered on the
    `update` observer and therefore runs before nested filters.
    """

    async def __call__(
        self,
        event: Message | CallbackQuery,
        settings: Settings,
    ) -> bool:
        user = event.from_user
        return settings.is_admin(user.id if user else None)


class HasReceiptTarget(BaseFilter):
    """Passes when a photo sent out of the blue can be read as a receipt.

    Returning a dict injects `receipt_target` into the handler; returning False
    lets the update fall through to the usual fallback reply.
    """

    async def __call__(
        self,
        message: Message,
        bookings: BookingService,
    ) -> dict[str, object] | bool:
        user = message.from_user
        if user is None:
            return False
        target = await bookings.find_receipt_target(user.id)
        if target is None:
            return False
        return {"receipt_target": target}
