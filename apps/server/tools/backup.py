"""SavdoOS — ma'lumotlar bazasi zaxirasi (backup).

Ishlatish (o'z kompyuteringizда, DATABASE_URL bilan):
    # Postgres (Railway) — pg_dump kerak (postgresql-client o'rnatilgan bo'lsin):
    DATABASE_URL="postgresql://user:pass@host:5432/db" python tools/backup.py

    # yoki Railway CLI orqali (env avtomatik):
    railway run --service savdoos python tools/backup.py

Natija: backups/savdoos_YYYYMMDD_HHMMSS.sql (Postgres) yoki .db nusxa (SQLite).

TAVSIYA: buni kunlik cron/vazifaga qo'ying va faylni BOSHQA joyga (Google Drive, S3,
tashqi disk) ko'chiring. Eng ishonchlisi — Railway → Postgres → Backups'ni ham yoqish.
"""
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def main() -> int:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("XATO: DATABASE_URL berilmagan.")
        return 1
    out_dir = pathlib.Path(os.getenv("BACKUP_DIR", "backups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if url.startswith("sqlite"):
        src = url.split("///", 1)[-1] if "///" in url else "savdoos.db"
        dst = out_dir / f"savdoos_{stamp}.db"
        shutil.copy2(src, dst)
        print(f"OK (SQLite): {dst}")
        return 0

    # Postgres — pg_dump
    norm = url
    if norm.startswith("postgres://"):
        norm = "postgresql://" + norm[len("postgres://"):]
    if "+psycopg" in norm:
        norm = norm.replace("+psycopg", "")
    dst = out_dir / f"savdoos_{stamp}.sql"
    if shutil.which("pg_dump") is None:
        print("XATO: pg_dump topilmadi. postgresql-client o'rnating (masalan: apt install postgresql-client).")
        return 2
    try:
        with open(dst, "wb") as f:
            subprocess.run(["pg_dump", "--no-owner", "--no-privileges", norm], stdout=f, check=True)
        print(f"OK (Postgres): {dst}  ({dst.stat().st_size // 1024} KB)")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"XATO: pg_dump muvaffaqiyatsiz ({e.returncode}).")
        return 3


if __name__ == "__main__":
    sys.exit(main())
