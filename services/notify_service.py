"""Outbound notifications to the master and to clients.

This is the bot-facing notification adapter, not a domain service: it owns
message text, keyboards and Telegram delivery semantics on purpose, so that
handlers and the scheduler never deal with Telegram error classes themselves.

Delivery contract — every `_send*` returns True when the message must not be
retried (delivered, or permanently undeliverable) and False only when a later
retry could still succeed. Callers use that to decide whether to mark a
reminder as sent.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup

from config.settings import Settings
from db.models import Booking
from domain.dates import format_date, format_date_short, format_time
from presentation.formatters import format_admin_booking_card
from presentation.keyboards.admin import admin_notify_keyboard
from presentation.texts.messages import (
    ADMIN_BOOKING_CANCELLED,
    ADMIN_MONTHLY_REMINDER,
    ADMIN_NEW_BOOKING,
    ADMIN_RECEIPT_ATTACHED,
    ADMIN_RECEIPT_LATE,
    CLIENT_CANCELLED_BY_MASTER,
    CLIENT_RESCHEDULED,
    REMINDER_2H,
    REMINDER_24H,
)

logger = logging.getLogger("beauty_bot.notify")

# Telegram asks for a pause; anything longer than this is not worth blocking a
# scheduler job for — the next run will pick the message up again.
MAX_RETRY_AFTER_SECONDS = 30


def _receipt_attachment(booking: Booking) -> tuple[str | None, str | None]:
    """(photo_id, document_id) for the stored receipt, if any."""
    if not booking.receipt_file_id:
        return None, None
    if booking.receipt_file_type == "document":
        return None, booking.receipt_file_id
    return booking.receipt_file_id, None


class NotifyService:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self._bot = bot
        self._settings = settings

    async def _deliver(
        self,
        chat_id: int,
        text: str,
        *,
        markup: InlineKeyboardMarkup | None = None,
        photo_id: str | None = None,
        document_id: str | None = None,
    ) -> None:
        if document_id:
            await self._bot.send_document(
                chat_id,
                document=document_id,
                caption=text,
                reply_markup=markup,
            )
        elif photo_id:
            await self._bot.send_photo(
                chat_id,
                photo=photo_id,
                caption=text,
                reply_markup=markup,
            )
        else:
            await self._bot.send_message(chat_id, text, reply_markup=markup)

    async def _send(
        self,
        chat_id: int,
        text: str,
        *,
        markup: InlineKeyboardMarkup | None = None,
        photo_id: str | None = None,
        document_id: str | None = None,
    ) -> bool:
        """See the delivery contract in the module docstring."""
        for attempt in (1, 2):
            try:
                await self._deliver(
                    chat_id,
                    text,
                    markup=markup,
                    photo_id=photo_id,
                    document_id=document_id,
                )
                return True
            except TelegramRetryAfter as exc:
                if attempt == 2 or exc.retry_after > MAX_RETRY_AFTER_SECONDS:
                    logger.warning(
                        "Flood limit for %s: retry after %ss, отложено",
                        chat_id,
                        exc.retry_after,
                    )
                    return False
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                # Blocked the bot or deleted the account: retrying forever would
                # just re-hit the API on every scheduler tick.
                logger.info("Чат %s недоступен (бот заблокирован)", chat_id)
                return True
            except TelegramBadRequest as exc:
                if photo_id or document_id:
                    logger.warning(
                        "Вложение не отправлено в %s (%s) — отправляю текстом",
                        chat_id,
                        exc,
                    )
                    return await self._send(chat_id, text, markup=markup)
                logger.error("Сообщение в %s отклонено: %s", chat_id, exc)
                return True
            except TelegramNetworkError as exc:
                logger.warning("Сеть недоступна для %s: %s", chat_id, exc)
                return False
        return False

    async def _send_admins(
        self,
        text: str,
        *,
        markup: InlineKeyboardMarkup | None = None,
        photo_id: str | None = None,
        document_id: str | None = None,
    ) -> None:
        for admin_id in self._settings.admin_telegram_ids:
            delivered = await self._send(
                admin_id,
                text,
                markup=markup,
                photo_id=photo_id,
                document_id=document_id,
            )
            if not delivered:
                logger.error("Мастер %s не получил уведомление", admin_id)

    async def new_booking_with_receipt(self, booking: Booking) -> None:
        text = ADMIN_NEW_BOOKING.format(card=format_admin_booking_card(booking))
        if booking.receipt_file_id:
            text += ADMIN_RECEIPT_ATTACHED
        photo_id, document_id = _receipt_attachment(booking)
        await self._send_admins(
            text,
            markup=admin_notify_keyboard(booking.id, booking.username),
            photo_id=photo_id,
            document_id=document_id,
        )

    async def receipt_after_expiry(self, booking: Booking) -> None:
        """Client paid after the hold lapsed — the master has to sort it out."""
        text = ADMIN_RECEIPT_LATE.format(card=format_admin_booking_card(booking))
        photo_id, document_id = _receipt_attachment(booking)
        await self._send_admins(text, photo_id=photo_id, document_id=document_id)

    async def booking_cancelled(self, booking: Booking, reason: str = "") -> None:
        text = ADMIN_BOOKING_CANCELLED.format(card=format_admin_booking_card(booking))
        if reason:
            text += f"\n\n{reason}"
        await self._send_admins(text)

    async def monthly_schedule_reminder(self) -> None:
        await self._send_admins(ADMIN_MONTHLY_REMINDER)

    async def client_visit_reminder(self, booking: Booking, *, hours: int) -> bool:
        template = REMINDER_24H if hours == 24 else REMINDER_2H
        text = template.format(
            date=format_date_short(booking.slot.working_day.day),
            time=format_time(booking.slot.start_time),
        )
        return await self._send(booking.telegram_user_id, text)

    async def client_cancelled_by_master(self, booking: Booking) -> bool:
        return await self._send(booking.telegram_user_id, CLIENT_CANCELLED_BY_MASTER)

    async def client_rescheduled(self, booking: Booking) -> bool:
        text = CLIENT_RESCHEDULED.format(
            date=format_date(booking.slot.working_day.day),
            time=format_time(booking.slot.start_time),
        )
        return await self._send(booking.telegram_user_id, text)
