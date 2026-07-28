"""Make a verified SQLite backup on demand and print an inventory.

Same code path as the nightly job in the bot (services/backup_service.py), so a
manual backup is never subtly different from an automatic one.

    python scripts/backup_and_dump_sqlite.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import reload_settings
from services.backup_service import (
    BackupError,
    backup_dir_for,
    create_backup,
    pretty_size,
)


def main() -> None:
    settings = reload_settings()
    db_path = settings.sqlite_path
    if db_path is None:
        print(f"Не SQLite ({settings.database_url.split('://')[0]}) — бэкап не нужен.")
        raise SystemExit(1)

    try:
        result = create_backup(db_path, backup_dir_for(db_path))
    except BackupError as exc:
        print(f"Бэкап не сделан: {exc}")
        raise SystemExit(1) from exc

    print(f"backup={result.path}")
    print(f"size={pretty_size(result.size)}")
    print(f"days={result.days} bookings={result.bookings} active={result.active}")
    _print_active(result.path)


def _print_active(path: Path) -> None:
    query = """
    SELECT b.id, wd.day, s.start_time, b.full_name, b.phone, b.username
    FROM bookings b
    JOIN slots s ON s.id = b.slot_id
    JOIN working_days wd ON wd.id = s.working_day_id
    WHERE b.status = 'active'
    ORDER BY wd.day, s.start_time
    """
    print("---ACTIVE---")
    con = sqlite3.connect(str(path))
    try:
        for row in con.execute(query):
            print("|".join("" if value is None else str(value) for value in row))
    finally:
        con.close()


if __name__ == "__main__":
    main()
