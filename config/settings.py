"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PORTFOLIO_DIR = BASE_DIR / "images" / "portfolio"
WELCOME_IMAGE = BASE_DIR / "images" / "welcome" / "cover.jpg"
DATA_DIR = BASE_DIR / "data"
# Bothost: persistent volume is /app/data (see https://bothost.ru/docs/database-storage).
BOTHOST_DATA_DIR = Path("/app/data")
BOTHOST_SQLITE_URL = "sqlite+aiosqlite:////app/data/bot.db"


def running_in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    if BOTHOST_DATA_DIR.is_dir():
        return True
    # Bothost / common PaaS markers (best-effort).
    return bool(os.getenv("BOTHOST") or os.getenv("BOTHOST_APP_ID"))


def _default_sqlite_url() -> str:
    if running_in_container():
        BOTHOST_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return BOTHOST_SQLITE_URL
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{(DATA_DIR / 'bot.db').as_posix()}"


def _normalize_database_url(raw: str) -> str:
    """Force container SQLite onto the Bothost volume path."""
    url = raw.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sqlite" in url and running_in_container():
        # Any sqlite URL in container → /app/data/bot.db (volume).
        BOTHOST_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return BOTHOST_SQLITE_URL
    return url

# Local development convenience only. Real deployments (Bothost) set variables
# in the panel, and those must win — a stale .env baked into an image silently
# overriding production secrets is exactly the failure mode to avoid.
load_dotenv(BASE_DIR / ".env", override=False)


def _env(key: str) -> str:
    return (os.getenv(key) or "").strip().strip('"').strip("'")


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    """Parse IDs: `123` or `123,456`. Order matters — first ID is the primary admin."""
    if not raw:
        return ()
    ids: list[int] = []
    seen: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.lstrip("-").isdigit():
            raise ValueError(
                "ADMIN_TELEGRAM_ID(S) must be numeric Telegram user ids "
                "(comma-separated for several admins; first = primary)"
            )
        value = int(part)
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return tuple(ids)


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable application settings."""

    bot_token: str
    channel_link: str
    master_username: str
    master_phone: str
    master_name: str
    log_level: str
    portfolio_dir: Path
    welcome_image: Path
    request_timeout: int
    database_url: str
    # Ordered: first ID is the primary admin (master), rest are support.
    admin_telegram_ids: tuple[int, ...]
    payment_link: str
    prepayment_amount: str
    slot_hold_minutes: int

    @property
    def channel_name(self) -> str:
        username = self.channel_link.rstrip("/").split("/")[-1]
        return username if username.startswith("@") else f"@{username}"

    @property
    def master_url(self) -> str:
        return f"https://t.me/{self.master_username}"

    @property
    def has_admins(self) -> bool:
        return bool(self.admin_telegram_ids)

    @property
    def sqlite_path(self) -> Path | None:
        """Filesystem path of the SQLite file, or None for other backends."""
        marker = ":///"
        if "sqlite" not in self.database_url:
            return None
        _, _, tail = self.database_url.partition(marker)
        return Path(tail) if tail else None

    @property
    def primary_admin_id(self) -> int | None:
        """Master's Telegram id — first entry in ADMIN_TELEGRAM_IDS."""
        return self.admin_telegram_ids[0] if self.admin_telegram_ids else None

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_telegram_ids

    def is_primary_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id == self.primary_admin_id

    @classmethod
    def from_env(cls) -> Settings:
        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token or bot_token == "your_bot_token_here":
            raise ValueError("BOT_TOKEN is not set in environment")

        channel_link = os.getenv("CHANNEL_LINK", "").strip()
        if not channel_link:
            raise ValueError("CHANNEL_LINK is not set in environment")

        master_username = os.getenv("MASTER_USERNAME", "").strip().lstrip("@")
        if not master_username:
            raise ValueError("MASTER_USERNAME is not set in environment")

        timeout_raw = os.getenv("REQUEST_TIMEOUT", "120").strip()
        try:
            request_timeout = int(timeout_raw)
        except ValueError as exc:
            raise ValueError("REQUEST_TIMEOUT must be an integer") from exc
        if request_timeout < 10:
            raise ValueError("REQUEST_TIMEOUT must be >= 10")

        ids_raw = _env("ADMIN_TELEGRAM_IDS")
        single = _env("ADMIN_TELEGRAM_ID")
        # Prefer ADMIN_TELEGRAM_IDS as the source of truth (order = primary first).
        # Legacy ADMIN_TELEGRAM_ID is appended only if missing from the list.
        if not ids_raw:
            ids_raw = single or "0"
        elif single and single not in {
            p.strip() for p in ids_raw.replace(";", ",").split(",")
        }:
            ids_raw = f"{ids_raw},{single}"
        if ids_raw == "0":
            admin_telegram_ids: tuple[int, ...] = ()
        else:
            admin_telegram_ids = _parse_admin_ids(ids_raw)

        payment_link = os.getenv("PAYMENT_LINK", "").strip()
        if not payment_link:
            raise ValueError("PAYMENT_LINK is required (SBP / card / payment URL)")

        database_url = _normalize_database_url(
            os.getenv("DATABASE_URL", "").strip() or _default_sqlite_url()
        )

        hold_raw = os.getenv("SLOT_HOLD_MINUTES", "15").strip()
        try:
            slot_hold_minutes = int(hold_raw)
        except ValueError as exc:
            raise ValueError("SLOT_HOLD_MINUTES must be an integer") from exc

        # Ensure local data dir exists; on Bothost volume is /app/data.
        if "sqlite" in database_url and running_in_container():
            BOTHOST_DATA_DIR.mkdir(parents=True, exist_ok=True)
        else:
            DATA_DIR.mkdir(parents=True, exist_ok=True)

        return cls(
            bot_token=bot_token,
            channel_link=channel_link,
            master_username=master_username,
            master_phone=os.getenv("MASTER_PHONE", "").strip() or "+7 777 666-44-44",
            master_name=os.getenv("MASTER_NAME", "").strip() or "Вика",
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
            portfolio_dir=PORTFOLIO_DIR,
            welcome_image=WELCOME_IMAGE,
            request_timeout=request_timeout,
            database_url=database_url,
            admin_telegram_ids=admin_telegram_ids,
            payment_link=payment_link,
            prepayment_amount=os.getenv("PREPAYMENT_AMOUNT", "").strip() or "500 ₽",
            slot_hold_minutes=max(5, slot_hold_minutes),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def reload_settings() -> Settings:
    """Drop the cache and reload (scripts that patch os.environ first)."""
    get_settings.cache_clear()
    return get_settings()
