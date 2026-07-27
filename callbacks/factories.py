"""CallbackData factories."""

from aiogram.filters.callback_data import CallbackData

from domain.enums import CallbackAction


class MenuCallback(CallbackData, prefix="menu"):
    action: CallbackAction


class SubscriptionCallback(CallbackData, prefix="sub"):
    action: CallbackAction


class PortfolioCallback(CallbackData, prefix="pf"):
    action: CallbackAction
    page: int = 0


class BookDayCallback(CallbackData, prefix="bday"):
    day_id: int


class BookSlotCallback(CallbackData, prefix="bslot"):
    slot_id: int


class BookServiceCallback(CallbackData, prefix="bsvc"):
    code: str


class BookCancelCallback(CallbackData, prefix="bcancel"):
    noop: int = 0


class BookNavCallback(CallbackData, prefix="bnav"):
    """Navigate within booking FSM without losing progress."""

    step: str  # name | phone | day


class ClientBookingCallback(CallbackData, prefix="cbook"):
    action: str
    booking_id: int = 0


class AdminCallback(CallbackData, prefix="adm"):
    action: str
    item_id: int = 0
