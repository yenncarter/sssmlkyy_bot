"""Message formatting utilities."""

from config.constants import BookingStatus
from models.booking import Booking
from utils.dates import format_date, format_time


def format_booking(booking: Booking) -> str:
    """Format booking details as HTML."""
    slot = booking.slot
    day = slot.working_day
    status_map = {
        BookingStatus.ACTIVE: "✅ Активна",
        BookingStatus.CANCELLED: "❌ Отменена",
        BookingStatus.COMPLETED: "✔️ Завершена",
    }
    status_text = status_map.get(booking.status, booking.status)
    return (
        f"📅 <b>Дата:</b> {format_date(day.date)}\n"
        f"🕐 <b>Время:</b> {format_time(slot.start_time)}\n"
        f"👤 <b>Имя:</b> {booking.client_name}\n"
        f"📞 <b>Телефон:</b> {booking.client_phone}\n"
        f"📋 <b>Статус:</b> {status_text}"
    )


def format_booking_short(booking: Booking) -> str:
    """Format short booking info."""
    slot = booking.slot
    day = slot.working_day
    return (
        f"{format_date(day.date)} в {format_time(slot.start_time)}"
    )
