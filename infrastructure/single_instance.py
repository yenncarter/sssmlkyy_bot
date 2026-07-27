"""Prevent multiple local bot instances."""

from __future__ import annotations

import os
import sys
from pathlib import Path

LOCK_FILE = Path(__file__).resolve().parent.parent / ".bot.pid"


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


def acquire() -> None:
    """Exit if another local instance is already running."""
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            old_pid = -1
        if _pid_alive(old_pid):
            print(
                f"\nБот уже запущен на этом ПК (PID {old_pid}).\n"
                "\nЗакрой другое окно run.bat / main.py"
                "\nИли запусти stop.bat — он остановит копию\n",
                file=sys.stderr,
            )
            raise SystemExit(1)
        LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


def release() -> None:
    """Remove lock file for the current process."""
    try:
        if (
            LOCK_FILE.exists()
            and int(LOCK_FILE.read_text(encoding="utf-8").strip()) == os.getpid()
        ):
            LOCK_FILE.unlink()
    except (OSError, ValueError):
        pass
