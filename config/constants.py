"""Application-wide constants."""

from enum import StrEnum


class CallbackAction(StrEnum):
    """Callback action identifiers."""

    BOOK = "book"
    MY_BOOKINGS = "my_bookings"
    PRICE = "price"
    PORTFOLIO = "portfolio"
    ABOUT = "about"
    CONTACTS = "contacts"
    CHECK_SUB = "check_sub"
    BACK = "back"
    PORTFOLIO_NEXT = "portfolio_next"
    PORTFOLIO_PREV = "portfolio_prev"


# Throttling
THROTTLE_RATE: float = 0.25

# Portfolio
PORTFOLIO_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
