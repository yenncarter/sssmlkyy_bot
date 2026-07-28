"""Domain exceptions — ready for booking / payment / admin flows."""


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ValidationError(AppError):
    """Invalid user or admin input."""


class StaleCallbackError(AppError):
    """Callback data is outdated or invalid."""


class PermissionDeniedError(AppError):
    """Caller lacks required permissions."""


class SlotNotAvailableError(AppError):
    """Time slot is already taken."""


class SlotNotFoundError(AppError):
    """Time slot does not exist."""


class DayNotFoundError(AppError):
    """Working day does not exist."""


class AlreadyHasBookingError(AppError):
    """User already has an active booking."""


class BookingNotFoundError(AppError):
    """Booking does not exist."""


class DuplicateSlotError(AppError):
    """Slot with the same time already exists."""
