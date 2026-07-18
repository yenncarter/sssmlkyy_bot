"""Application settings loaded from environment variables."""

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
PORTFOLIO_DIR = BASE_DIR / "images" / "portfolio"
WELCOME_IMAGE = BASE_DIR / "images" / "welcome" / "cover.png"

load_dotenv(BASE_DIR / ".env", override=True)


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable application settings."""

    bot_token: str
    channel_id: str | int
    channel_link: str
    master_username: str
    master_phone: str
    master_name: str
    log_level: str
    portfolio_dir: Path
    welcome_image: Path
    proxy_url: str | None
    request_timeout: int

    @property
    def channel_name(self) -> str:
        """Display name for channel link."""
        username = self.channel_link.rstrip("/").split("/")[-1]
        return username if username.startswith("@") else f"@{username}"

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        bot_token = os.getenv("BOT_TOKEN", "")
        if not bot_token:
            raise ValueError("BOT_TOKEN is not set in environment")

        channel_link = os.getenv("CHANNEL_LINK", "")
        if not channel_link:
            raise ValueError("CHANNEL_LINK is not set in environment")

        master_username = os.getenv("MASTER_USERNAME", "").lstrip("@")
        if not master_username:
            raise ValueError("MASTER_USERNAME is not set in environment")

        channel_id_raw = os.getenv("CHANNEL_ID", "@beautysznch")
        if channel_id_raw.lstrip("-").isdigit():
            channel_id: str | int = int(channel_id_raw)
        else:
            channel_id = channel_id_raw if channel_id_raw.startswith("@") else f"@{channel_id_raw}"

        return cls(
            bot_token=bot_token,
            channel_id=channel_id,
            channel_link=channel_link,
            master_username=master_username,
            master_phone=os.getenv("MASTER_PHONE", "+7 777 666-44-44"),
            master_name=os.getenv("MASTER_NAME", "Кайли"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            portfolio_dir=PORTFOLIO_DIR,
            welcome_image=WELCOME_IMAGE,
            proxy_url=os.getenv("PROXY_URL") or None,
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "120")),
        )


settings = Settings.from_env()
