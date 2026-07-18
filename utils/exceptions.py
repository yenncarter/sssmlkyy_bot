"""Custom application exceptions."""


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ValidationError(AppError):
    """Data validation error."""


class SlotNotAvailableError(AppError):
    """Time slot is already booked."""


class SlotNotFoundError(AppError):
    """Time slot does not exist."""


class DayClosedError(AppError):
    """Working day is closed."""


class DayNotFoundError(AppError):
    """Working day does not exist."""


class AlreadyHasBookingError(AppError):
    """User already has an active booking."""


class BookingNotFoundError(AppError):
    """Booking does not exist."""


class UserBlockedError(AppError):
    """User is blocked."""


class NotSubscribedError(AppError):
    """User is not subscribed to the channel."""


class DuplicateSlotError(AppError):
    """Slot with same time already exists."""


class StaleCallbackError(AppError):
    """Callback data is outdated or invalid."""


class PermissionDeniedError(AppError):
    """User lacks required permissions."""
