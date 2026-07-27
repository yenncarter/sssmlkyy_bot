"""Check connectivity to Telegram Bot API."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main() -> None:
    """Run network diagnostics."""
    from aiogram.utils.token import validate_token

    from config.settings import settings
    from infrastructure.bot_factory import create_bot

    print("=== Проверка сети для бота ===\n")
    print(f"Таймаут: {settings.request_timeout} сек\n")

    validate_token(settings.bot_token)
    print("[1/2] Формат BOT_TOKEN — OK")

    bot = create_bot(settings)
    try:
        me = await bot.get_me()
        print(f"[2/2] Связь с Telegram — OK (@{me.username})")
        print("\nМожно запускать: python main.py")
    except Exception as exc:
        print(f"[2/2] Связь с Telegram — ОШИБКА:\n      {exc}")
        print("\n--- Что делать ---")
        print("1. Включи системный VPN (Happ и т.п.), если Telegram режется.")
        print("2. Или запускай бота в облаке — см. DEPLOY.md")
        raise SystemExit(1) from exc
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
