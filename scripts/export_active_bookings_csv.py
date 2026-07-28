"""Export bookings to UTF-8 CSV for emergency recovery."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "backups"
# Prefer latest consistent backup, else live db
cands = sorted(SRC.glob("bot_consistent_*.db"), reverse=True)
DB = cands[0] if cands else ROOT / "data" / "bot.db"
OUT = ROOT / "data" / "backups" / "active_bookings_restore.csv"
SQL_OUT = ROOT / "data" / "backups" / "restore_inventory.txt"


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = list(
        con.execute(
            """
            SELECT b.id, b.status, wd.day, s.start_time, b.full_name, b.phone,
                   b.username, b.telegram_user_id, b.service_title,
                   b.duration_minutes, b.created_at, b.receipt_file_id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN working_days wd ON wd.id = s.working_day_id
            WHERE b.status = 'active'
            ORDER BY wd.day, s.start_time
            """
        )
    )
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            [
                "id",
                "status",
                "day",
                "time",
                "full_name",
                "phone",
                "username",
                "telegram_user_id",
                "service",
                "duration",
                "created_at",
                "has_receipt",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["id"],
                    r["status"],
                    r["day"],
                    str(r["start_time"])[:5],
                    r["full_name"],
                    r["phone"],
                    r["username"] or "",
                    r["telegram_user_id"],
                    r["service_title"] or "",
                    r["duration_minutes"] or "",
                    r["created_at"],
                    "yes" if r["receipt_file_id"] else "no",
                ]
            )

    days = con.execute("SELECT day FROM working_days ORDER BY day").fetchall()
    with SQL_OUT.open("w", encoding="utf-8") as f:
        f.write(f"source={DB}\n")
        f.write(f"active={len(rows)}\n")
        f.write("days=" + ",".join(d[0] for d in days) + "\n")
        for r in rows:
            f.write(
                f"{r['day']} {str(r['start_time'])[:5]} | {r['full_name']} | "
                f"{r['phone']} | @{r['username'] or '-'} | tg={r['telegram_user_id']}\n"
            )
    con.close()
    print(f"csv={OUT}")
    print(f"txt={SQL_OUT}")
    print(f"active={len(rows)}")


if __name__ == "__main__":
    main()
