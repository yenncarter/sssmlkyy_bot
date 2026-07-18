"""Stop local bot instance and clear Telegram webhook."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / ".bot.pid"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_locked_process() -> None:
    if not LOCK_FILE.exists():
        return
    try:
        pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        LOCK_FILE.unlink(missing_ok=True)
        return

    if _pid_alive(pid):
        print(f"Останавливаю процесс бота PID {pid}...")
        if sys.platform == "win32":
            import subprocess

            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                capture_output=True,
            )
        else:
            os.kill(pid, 15)
    LOCK_FILE.unlink(missing_ok=True)


async def _clear_webhook() -> None:
    sys.path.insert(0, str(ROOT))
    from config.settings import settings
    from utils.bot_factory import create_bot

    bot = create_bot(settings)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("Webhook сброшен.")
    finally:
        await bot.session.close()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _stop_locked_process()
    try:
        asyncio.run(_clear_webhook())
    except Exception as exc:
        print(f"Webhook не сброшен: {exc}")


if __name__ == "__main__":
    main()
