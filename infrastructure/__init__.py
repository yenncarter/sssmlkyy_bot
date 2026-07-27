"""Infrastructure — Telegram client, process lock, DI container."""

from infrastructure.bot_factory import create_bot
from infrastructure.bot_setup import setup_bot_commands
from infrastructure.container import AppContainer
from infrastructure.single_instance import acquire, release

__all__ = [
    "AppContainer",
    "acquire",
    "create_bot",
    "release",
    "setup_bot_commands",
]
