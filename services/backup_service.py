"""SQLite backups: consistent snapshot, verified, rotated, sent off-site.

Off-site here means the master's Telegram chat. It needs no credentials, no
extra service and no billing, and the file lands on a device that is not the
one that just lost the data — which is the only property that matters.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from config.settings import Settings
from domain.dates import now_local
from presentation.texts.alerts import BACKUP_CAPTION, BACKUP_FAILED
from services.alert_service import AlertService
from services.app_state import AppStateStore
from services.db_health import LAST_BACKUP_KEY

logger = logging.getLogger("beauty_bot.backup")

KEEP_BACKUPS = 7
BACKUP_PREFIX = "bot_"
# Telegram rejects bot documents above 50 MB; this database is orders of
# magnitude smaller, so hitting the limit means something is very wrong.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class BackupError(RuntimeError):
    """Backup could not be created or failed verification."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    size: int
    days: int
    bookings: int
    active: int


def backup_dir_for(db_path: Path) -> Path:
    """Backups live next to the database — same volume, same lifecycle."""
    return db_path.parent / "backups"


def create_backup(
    db_path: Path,
    backup_dir: Path,
    *,
    keep: int = KEEP_BACKUPS,
) -> BackupResult:
    """Create a verified snapshot of a live SQLite database.

    Blocking — call through `asyncio.to_thread`. Uses `VACUUM INTO`, which is
    the only way to copy a WAL database consistently while writers are active:
    copying the file by hand can miss everything still sitting in the -wal.
    """
    if not db_path.exists():
        raise BackupError(f"файл БД не найден: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_local().strftime("%Y%m%d_%H%M%S")
    destination = backup_dir / f"{BACKUP_PREFIX}{stamp}.db"
    if destination.exists():
        raise BackupError(f"бэкап уже существует: {destination.name}")

    try:
        source = sqlite3.connect(str(db_path))
        try:
            source.execute("VACUUM INTO ?", (str(destination),))
        finally:
            source.close()
    except sqlite3.Error as exc:
        raise BackupError(f"снимок не создан: {exc}") from exc

    result = _verify(destination)
    _rotate(backup_dir, keep)
    return result


def _verify(path: Path) -> BackupResult:
    """A backup nobody opened is not a backup."""
    try:
        con = sqlite3.connect(str(path))
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise BackupError(f"копия повреждена: {integrity}")
            days = con.execute("SELECT COUNT(*) FROM working_days").fetchone()[0]
            bookings = con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
            active = con.execute(
                "SELECT COUNT(*) FROM bookings WHERE status = 'active'"
            ).fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise BackupError(f"копия не читается: {exc}") from exc

    return BackupResult(
        path=path,
        size=path.stat().st_size,
        days=days,
        bookings=bookings,
        active=active,
    )


def _rotate(backup_dir: Path, keep: int) -> None:
    dumps = sorted(
        backup_dir.glob(f"{BACKUP_PREFIX}*.db"),
        key=lambda p: p.name,
        reverse=True,
    )
    for stale in dumps[max(1, keep):]:
        try:
            stale.unlink()
        except OSError as exc:
            logger.warning("Старый бэкап %s не удалён: %s", stale.name, exc)


def pretty_size(size: int) -> str:
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size / (1024 * 1024):.1f} МБ"


class BackupService:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        state: AppStateStore,
        alerts: AlertService,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._state = state
        self._alerts = alerts

    async def run(self) -> BackupResult | None:
        """Snapshot, verify, ship to the master, remember when. Never raises."""
        db_path = self._settings.sqlite_path
        if db_path is None:
            logger.info("Бэкап пропущен: managed-БД бэкапится на стороне хостинга")
            return None

        try:
            result = await asyncio.to_thread(
                create_backup, db_path, backup_dir_for(db_path)
            )
        except BackupError as exc:
            logger.error("Бэкап не создан: %s", exc)
            await self._alerts.send("backup.failed", BACKUP_FAILED.format(detail=str(exc)))
            return None

        logger.info(
            "Бэкап готов: %s (%s, записей=%s)",
            result.path.name,
            pretty_size(result.size),
            result.bookings,
        )
        await self._state.set(LAST_BACKUP_KEY, now_local().isoformat())
        await self._deliver(result)
        return result

    async def _deliver(self, result: BackupResult) -> None:
        chat_id = self._settings.primary_admin_id
        if chat_id is None:
            logger.warning("Бэкап никуда не отправлен: ADMIN_TELEGRAM_IDS не задан")
            return
        if result.size > MAX_UPLOAD_BYTES:
            detail = f"файл слишком большой для Telegram: {pretty_size(result.size)}"
            logger.error("Бэкап не отправлен: %s", detail)
            await self._alerts.send("backup.too_big", BACKUP_FAILED.format(detail=detail))
            return

        caption = BACKUP_CAPTION.format(
            date=_stamp_to_human(result.path.name),
            days=result.days,
            bookings=result.bookings,
            active=result.active,
            size=pretty_size(result.size),
        )
        try:
            await self._bot.send_document(
                chat_id,
                document=FSInputFile(result.path),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        except TelegramAPIError as exc:
            logger.error("Бэкап не отправлен мастеру: %s", exc)
            await self._alerts.send(
                "backup.not_sent",
                BACKUP_FAILED.format(detail=f"копия создана, но не отправлена: {exc}"),
            )


def _stamp_to_human(filename: str) -> str:
    """`bot_20260728_033000.db` → `28.07.2026 03:30`."""
    stamp = filename.removeprefix(BACKUP_PREFIX).removesuffix(".db")
    try:
        return datetime.strptime(stamp, "%Y%m%d_%H%M%S").strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return stamp
