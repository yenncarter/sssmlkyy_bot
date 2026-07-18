"""Re-export keyboard helpers."""

from keyboards.menu import (
    back_button,
    back_to_menu_keyboard,
    channel_button,
    footer_keyboard,
    main_menu_keyboard,
)

# backward compat name
menu_button = back_button

__all__ = [
    "back_button",
    "back_to_menu_keyboard",
    "channel_button",
    "footer_keyboard",
    "main_menu_keyboard",
    "menu_button",
]
