"""Application lifespan: wire → poll (with reconnect) → shutdown."""

from __future__ import annotations

import asyncio
import sys

from aiogram import Dispatcher
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import ClientConnectorError
from aiohttp.client_exceptions import ClientError

from app_logging.setup import setup_logging
from config.settings import get_settings
from handlers import setup_routers
from infrastructure.bot_factory import create_bot
from infrastructure.bot_setup import setup_bot_commands
from infrastructure.container import AppContainer
from infrastructure.scheduler import setup_scheduler
from infrastructure.single_instance import acquire, release
from middlewares.context import BotContextMiddleware
from middlewares.error import ErrorMiddleware
from middlewares.logging_mw import LoggingMiddleware
from middlewares.throttling import ThrottlingMiddleware

logger = setup_logging()

_NETWORK_ERRORS = (
    TelegramNetworkError,
    ClientConnectorError,
    ClientError,
    ConnectionError,
    OSError,
    TimeoutError,
)


async def _run_polling(dp: Dispatcher, bot) -> None:
    """Poll with auto-reconnect on flaky network drops."""
    backoff = 3
    while True:
        try:
            await dp.start_polling(bot, close_bot_session=False)
            return
        except TelegramConflictError:
            raise
        except asyncio.CancelledError:
            raise
        except _NETWORK_ERRORS as exc:
            logger.warning(
                "Telegram connection lost (%s: %s). Reconnect in %ss",
                type(exc).__name__,
                exc,
                backoff,
            )
            print(
                f"\nСвязь с Telegram пропала ({type(exc).__name__}). "
                f"Переподключение через {backoff} сек…",
                flush=True,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def main() -> None:
    settings = get_settings()
    bot = create_bot(settings)
    container = None
    scheduler = None
    try:
        container = await AppContainer.create(settings, bot)
        dp = Dispatcher(storage=MemoryStorage())

        dp.update.middleware(LoggingMiddleware())
        dp.update.middleware(ThrottlingMiddleware())
        dp.update.middleware(BotContextMiddleware(container))
        dp.update.middleware(ErrorMiddleware())

        dp.include_router(setup_routers())

        await setup_bot_commands(bot)
        await bot.delete_webhook(drop_pending_updates=True)

        if not settings.welcome_image.exists():
            logger.warning("Welcome image missing: %s", settings.welcome_image)
        else:
            logger.info("Welcome image: %s", settings.welcome_image.name)

        if not settings.has_admins:
            logger.warning(
                "ADMIN_TELEGRAM_ID(S) not set — укажи numeric ID админа в .env"
            )
        else:
            logger.info(
                "Admin access configured for %s id(s)",
                len(settings.admin_telegram_ids),
            )

        scheduler = setup_scheduler(
            container.schedule, container.notify, container.bookings
        )
        scheduler.start()
        logger.info("Scheduler started")

        logger.info("Bot starting… db=%s", settings.database_url.split("://")[0])
        print("Бот запущен. Открой Telegram и напиши боту /start")
        print("Админ: /admin")
        print("Остановка: Ctrl+C\n")
        await _run_polling(dp, bot)
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        if container is not None:
            await container.shutdown()
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
    except _NETWORK_ERRORS:
        print(
            "\nНе удалось подключиться к api.telegram.org\n"
            "\nПроверь сеть / VPN на этом ПК, либо запускай бота в облаке "
            "(см. DEPLOY.md).\n"
            "Диагностика: python scripts\\check_connection.py",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as exc:
        print(f"\nОшибка запуска: {exc}", file=sys.stderr)
        print("\nПроверь:")
        print("  1. Файл .env (BOT_TOKEN, ADMIN_TELEGRAM_ID, PAYMENT_LINK, …)")
        print("  2. Запуск: venv\\Scripts\\python.exe main.py")
        print("  3. ADMIN_TELEGRAM_ID в .env")
        raise SystemExit(1) from exc
    finally:
        release()
