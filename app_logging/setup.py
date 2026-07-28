"""Logging configuration."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config.settings import BASE_DIR, Settings

LOG_FILE_BYTES = 2 * 1024 * 1024
LOG_FILE_BACKUPS = 3

_FORMATTER = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_logging(settings: Settings) -> logging.Logger:
    """Configure and return the root application logger.

    stdout is the primary sink — that is what the Bothost panel shows. The file
    handler is a best-effort local convenience: it rotates (an unbounded log
    would eventually fill the container disk) and is skipped entirely when the
    filesystem is read-only.
    """
    root_logger = logging.getLogger("beauty_bot")
    root_logger.handlers.clear()
    root_logger.setLevel(settings.log_level)
    root_logger.propagate = False

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(_FORMATTER)
    root_logger.addHandler(console_handler)

    file_handler = _build_file_handler()
    if file_handler is not None:
        root_logger.addHandler(file_handler)

    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    return root_logger


def _build_file_handler() -> logging.Handler | None:
    try:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "bot.log",
            maxBytes=LOG_FILE_BYTES,
            backupCount=LOG_FILE_BACKUPS,
            encoding="utf-8",
        )
    except OSError:
        # Read-only or ephemeral filesystem — stdout is enough.
        return None
    handler.setFormatter(_FORMATTER)
    return handler
