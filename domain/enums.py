"""Domain enums."""

from enum import StrEnum


class CallbackAction(StrEnum):
    """Callback action identifiers for inline keyboards."""

    BOOK = "book"
    MY_BOOKINGS = "my_bookings"
    PRICE = "price"
    PORTFOLIO = "portfolio"
    ABOUT = "about"
    FAQ = "faq"
    FAQ_BOOKING = "faq_booking"
    FAQ_VISIT = "faq_visit"
    FAQ_RULES = "faq_rules"
    CONTACTS = "contacts"
    BACK = "back"
    PORTFOLIO_NEXT = "portfolio_next"
    PORTFOLIO_PREV = "portfolio_prev"


class SlotStatus(StrEnum):
    FREE = "free"
    HELD = "held"
    BOOKED = "booked"
    BLOCKED = "blocked"  # closed by admin (lunch / personal)


class BookingStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
