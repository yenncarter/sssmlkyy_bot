"""Domain enums."""

from enum import StrEnum


class CallbackAction(StrEnum):
    """Callback action identifiers for inline keyboards."""

    BOOK = "book"
    MY_BOOKINGS = "my_bookings"
    PRICE = "price"
    PORTFOLIO = "portfolio"
    CHANNEL = "channel"
    ABOUT = "about"
    FAQ = "faq"
    FAQ_BOOKING = "faq_booking"
    FAQ_VISIT = "faq_visit"
    FAQ_RULES = "faq_rules"
    CONTACTS = "contacts"
    CHECK_SUB = "check_sub"
    BACK = "back"
    PORTFOLIO_NEXT = "portfolio_next"
    PORTFOLIO_PREV = "portfolio_prev"
    CANCEL_BOOKING_FLOW = "cancel_booking_flow"


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
    NO_SHOW = "no_show"


class ServiceCode(StrEnum):
    MANICURE = "manicure"
    GEL = "gel"
    REMOVAL = "removal"
    DESIGN = "design"
