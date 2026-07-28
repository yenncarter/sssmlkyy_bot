"""Make a consistent SQLite backup (checkpoint WAL) and print inventory."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "bot.db"
BACKUP_DIR = ROOT / "data" / "backups"


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"bot_consistent_{ts}.db"

    con = sqlite3.connect(SRC)
    con.execute("PRAGMA wal_checkpoint(FULL)")
    con.close()

    shutil.copy2(SRC, dst)

    con = sqlite3.connect(dst)
    days = con.execute("SELECT COUNT(*) FROM working_days").fetchone()[0]
    bookings = con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    active = con.execute(
        "SELECT COUNT(*) FROM bookings WHERE status='active'"
    ).fetchone()[0]
    print(f"backup={dst}")
    print(f"size={dst.stat().st_size}")
    print(f"days={days} bookings={bookings} active={active}")

    print("---ACTIVE---")
    q = """
    SELECT b.id, wd.day, s.start_time, b.full_name, b.phone, b.username
    FROM bookings b
    JOIN slots s ON s.id = b.slot_id
    JOIN working_days wd ON wd.id = s.working_day_id
    WHERE b.status = 'active'
    ORDER BY wd.day, s.start_time
    """
    for row in con.execute(q):
        print("|".join("" if x is None else str(x) for x in row))
    con.close()


if __name__ == "__main__":
    main()
