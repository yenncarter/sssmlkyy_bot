"""Application-wide constants."""

from domain.enums import BookingStatus, CallbackAction

# Re-export for existing imports during transition
__all__ = [
    "BookingStatus",
    "CallbackAction",
    "THROTTLE_RATE",
    "THROTTLE_TTL_SECONDS",
    "PORTFOLIO_EXTENSIONS",
]

# Soft rate-limit between user actions (seconds)
THROTTLE_RATE: float = 0.35

# Drop idle throttle entries after this many seconds
THROTTLE_TTL_SECONDS: float = 600.0

# Portfolio
PORTFOLIO_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
