"""Application lifespan: wire → poll (with reconnect) → shutdown."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp.client_exceptions import ClientError

from app_logging.setup import setup_logging
from config.settings import Settings, get_settings
from handlers import setup_routers
from infrastructure.bot_factory import create_bot
from infrastructure.bot_setup import setup_bot_commands
from infrastructure.container import AppContainer
from infrastructure.scheduler import setup_scheduler
from middlewares.context import BotContextMiddleware
from middlewares.error import ErrorMiddleware
from middlewares.logging_mw import LoggingMiddleware
from middlewares.throttling import ThrottlingMiddleware
from presentation.texts.alerts import LOOP_CRASH
from services.alert_service import AlertService
from services.db_health import LAST_BACKUP_KEY

logger = logging.getLogger("beauty_bot.main")

# Only genuinely transient transport failures belong here. Catching bare OSError
# would swallow real bugs (a missing image file, a broken database path) and
# retry them forever.
_NETWORK_ERRORS = (
    TelegramNetworkError,
    ClientError,
    ConnectionError,
    TimeoutError,
)
_RECONNECT_START_SECONDS = 3
_RECONNECT_MAX_SECONDS = 60
_INITIAL_BACKUP_DELAY_SECONDS = 15


async def _run_polling(dp: Dispatcher, bot: Bot) -> None:
    """Poll with auto-reconnect.

    aiogram retries individual getUpdates calls itself; this loop only covers
    the case where the whole polling task dies on a transport error.
    """
    backoff = _RECONNECT_START_SECONDS
    while True:
        try:
            await dp.start_polling(bot, close_bot_session=False)
            return
        except (TelegramConflictError, asyncio.CancelledError):
            raise
        except _NETWORK_ERRORS as exc:
            logger.warning(
                "Связь с Telegram потеряна (%s: %s). Переподключение через %sс",
                type(exc).__name__,
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)


def _build_dispatcher(container: AppContainer) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Order is significant: ErrorMiddleware is registered first so that it wraps
    # the others and can report failures raised inside throttling or DI as well.
    dp.update.middleware(ErrorMiddleware(container.alerts))
    dp.update.middleware(LoggingMiddleware())
    dp.update.middleware(ThrottlingMiddleware())
    dp.update.middleware(BotContextMiddleware(container))
    dp.include_router(setup_routers())
    return dp


def _log_environment(settings: Settings) -> None:
    if not settings.welcome_image.exists():
        logger.warning("Обложка не найдена: %s", settings.welcome_image)
    if not settings.has_admins:
        logger.warning(
            "ADMIN_TELEGRAM_IDS не задан — админка недоступна никому"
        )
    else:
        logger.info("Админов настроено: %s", len(settings.admin_telegram_ids))
    logger.info("Запуск… db=%s", settings.database_url.split("://")[0])


def _install_loop_handler(alerts: AlertService) -> None:
    """Catch Task exceptions that never reach ErrorMiddleware."""
    loop = asyncio.get_running_loop()
    pending: set[asyncio.Task[bool]] = set()

    def _handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        message = context.get("message", "unknown")
        if exc is not None:
            logger.error("Необработанная ошибка цикла: %s", message, exc_info=exc)
            error_name = type(exc).__name__
        else:
            logger.error("Необработанная ошибка цикла: %s", message)
            error_name = "LoopError"
        with suppress(RuntimeError):
            task = asyncio.create_task(
                alerts.send("loop", LOOP_CRASH.format(error=error_name))
            )
            pending.add(task)
            task.add_done_callback(pending.discard)

    loop.set_exception_handler(_handler)


async def _ensure_backup(container: AppContainer) -> None:
    """If the salon has never had a backup, make one shortly after boot."""
    if container.settings.sqlite_path is None:
        return
    if await container.state.get(LAST_BACKUP_KEY) is not None:
        return
    await asyncio.sleep(_INITIAL_BACKUP_DELAY_SECONDS)
    logger.info("Первого бэкапа ещё не было — делаю сейчас")
    await container.backup.run()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    bot = create_bot(settings)
    container = None
    scheduler = None
    backup_task: asyncio.Task[None] | None = None
    try:
        container = await AppContainer.create(settings, bot)
        _install_loop_handler(container.alerts)
        dp = _build_dispatcher(container)

        await setup_bot_commands(bot)
        await bot.delete_webhook(drop_pending_updates=True)
        _log_environment(settings)
        await container.startup_checks()

        scheduler = setup_scheduler(
            container.schedule,
            container.notify,
            container.bookings,
            container.alerts,
            container.db_health,
            container.backup,
        )
        scheduler.start()
        logger.info("Планировщик запущен")
        backup_task = asyncio.create_task(
            _ensure_backup(container), name="initial_backup"
        )

        await _run_polling(dp, bot)
    finally:
        if backup_task is not None and not backup_task.done():
            backup_task.cancel()
            with suppress(asyncio.CancelledError):
                await backup_task
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        if container is not None:
            await container.shutdown()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен")
    except TelegramConflictError as exc:
        print(
            "\nНа этом токене уже работает другая копия бота."
            "\nОстанови её (локальный процесс или деплой) и запусти снова.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except _NETWORK_ERRORS as exc:
        print(
            "\nНе удалось подключиться к api.telegram.org."
            "\nПроверь сеть на этой машине: python scripts/check_connection.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"\nОшибка запуска: {exc}", file=sys.stderr)
        print(
            "Проверь переменные окружения: "
            "BOT_TOKEN, CHANNEL_LINK, MASTER_USERNAME, PAYMENT_LINK",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
