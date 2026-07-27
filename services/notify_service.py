"""Notify admin/clients about bookings and reminders."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

from config.settings import Settings
from db.models import Booking
from domain.dates import format_date_short, format_time
from presentation.keyboards.admin import admin_notify_keyboard
from presentation.texts.messages import (
    ADMIN_BOOKING_CANCELLED,
    ADMIN_MONTHLY_REMINDER,
    ADMIN_NEW_BOOKING,
    ADMIN_RECEIPT_ATTACHED,
    REMINDER_24H,
    REMINDER_2H,
)
from services.schedule_service import format_admin_booking_card

logger = logging.getLogger("beauty_bot.notify")


class NotifyService:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self._bot = bot
        self._settings = settings

    async def _send_admins(
        self,
        text: str,
        *,
        markup: InlineKeyboardMarkup | None = None,
        photo_id: str | None = None,
        document_id: str | None = None,
    ) -> None:
        for admin_id in self._settings.admin_telegram_ids:
            try:
                if document_id:
                    await self._bot.send_document(
                        admin_id,
                        document=document_id,
                        caption=text,
                        reply_markup=markup,
                    )
                elif photo_id:
                    await self._bot.send_photo(
                        admin_id,
                        photo=photo_id,
                        caption=text,
                        reply_markup=markup,
                    )
                else:
                    await self._bot.send_message(admin_id, text, reply_markup=markup)
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                logger.error("Failed to notify admin %s: %s", admin_id, exc)
                if document_id or photo_id:
                    try:
                        await self._bot.send_message(admin_id, text, reply_markup=markup)
                    except Exception:
                        logger.exception("Fallback admin notify failed for %s", admin_id)

    async def new_booking_with_receipt(self, booking: Booking) -> None:
        text = ADMIN_NEW_BOOKING.format(card=format_admin_booking_card(booking))
        if booking.receipt_file_id:
            text += ADMIN_RECEIPT_ATTACHED
        markup = admin_notify_keyboard(booking.id, booking.username)
        photo_id = None
        document_id = None
        if booking.receipt_file_id:
            if booking.receipt_file_type == "document":
                document_id = booking.receipt_file_id
            else:
                photo_id = booking.receipt_file_id
        await self._send_admins(
            text,
            markup=markup,
            photo_id=photo_id,
            document_id=document_id,
        )

    async def booking_cancelled(self, booking: Booking, reason: str = "") -> None:
        text = ADMIN_BOOKING_CANCELLED.format(card=format_admin_booking_card(booking))
        if reason:
            text += f"\n\n{reason}"
        await self._send_admins(text)

    async def monthly_schedule_reminder(self) -> None:
        await self._send_admins(ADMIN_MONTHLY_REMINDER)

    async def client_visit_reminder(self, booking: Booking, *, hours: int) -> bool:
        day = booking.slot.working_day.day
        t = booking.slot.start_time
        template = REMINDER_24H if hours == 24 else REMINDER_2H
        text = template.format(
            date=format_date_short(day),
            time=format_time(t),
        )
        try:
            await self._bot.send_message(booking.telegram_user_id, text)
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.error("Client reminder failed for %s: %s", booking.id, exc)
            return False
