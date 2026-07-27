"""Logging configuration."""

from __future__ import annotations

import logging as stdlib_logging
import sys
from pathlib import Path

from config.settings import BASE_DIR, settings


def setup_logging() -> stdlib_logging.Logger:
    """Configure and return the root application logger."""
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    formatter = stdlib_logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = stdlib_logging.getLogger("beauty_bot")
    root_logger.handlers.clear()
    root_logger.setLevel(settings.log_level)
    root_logger.propagate = False

    console_handler = stdlib_logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = stdlib_logging.FileHandler(
        log_dir / "bot.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stdlib_logging.getLogger("aiogram").setLevel(stdlib_logging.WARNING)
    stdlib_logging.getLogger("aiohttp").setLevel(stdlib_logging.WARNING)

    return root_logger
