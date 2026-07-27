"""FSM states for booking and admin flows."""

from aiogram.fsm.state import State, StatesGroup


class BookingFSM(StatesGroup):
    full_name = State()
    phone = State()
    choose_day = State()
    choose_time = State()
    wait_receipt = State()


class AdminFSM(StatesGroup):
    add_day = State()
    edit_default_hours = State()
    edit_day_hours = State()
    edit_prepay = State()
    reschedule_pick_day = State()
    reschedule_pick_time = State()
