"""Beauty Bot — Telegram vitrina for nail master."""

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError
from aiohttp import ClientConnectorError

from app_logging.setup import setup_logging
from handlers import setup_routers
from middlewares.context import BotContextMiddleware
from middlewares.error import ErrorMiddleware
from middlewares.logging_mw import LoggingMiddleware
from middlewares.throttling import ThrottlingMiddleware
from utils.bot_factory import create_bot
from utils.single_instance import acquire, release

logger = setup_logging()


async def main() -> None:
    """Entry point."""
    from config.settings import settings

    bot = create_bot(settings)
    dp = Dispatcher()

    dp.update.middleware(LoggingMiddleware())
    dp.update.middleware(ThrottlingMiddleware())
    dp.update.middleware(BotContextMiddleware(bot))
    dp.update.middleware(ErrorMiddleware())

    dp.include_router(setup_routers())

    from utils.bot_setup import setup_bot_commands
    await setup_bot_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Bot starting...")
    print("Бот запущен. Открой Telegram и напиши боту /start")
    print("Остановка: Ctrl+C\n")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        acquire()
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен")
    except TelegramConflictError:
        print(
            "\nУже запущена другая копия этого бота.\n"
            "\nЧто сделать:"
            "\n  1. Закрой все другие окна с main.py / run.bat"
            "\n  2. Или запусти stop.bat — он остановит лишние копии"
            "\n  3. Потом снова run.bat",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except (ClientConnectorError, TelegramNetworkError):
        print(
            "\nНе удалось подключиться к api.telegram.org\n"
            "\nЭто проблема сети на этом ПК. Решения:"
            "\n  1. python scripts\\check_connection.py  — диагностика"
            "\n  2. PROXY_URL=socks5://127.0.0.1:7891 в .env (порт из VPN)"
            "\n  3. Запуск в облаке — см. DEPLOY.md (рекомендуется)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as exc:
        print(f"\nОшибка запуска: {exc}", file=sys.stderr)
        print("\nПроверь:")
        print("  1. Файл .env в папке beauty_bot")
        print("  2. Запуск: venv\\Scripts\\python.exe main.py")
        print("  3. BOT_TOKEN в .env (от @BotFather)")
        raise SystemExit(1) from exc
    finally:
        release()