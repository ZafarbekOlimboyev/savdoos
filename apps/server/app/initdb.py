"""Dev/prod uchun jadvallarni yaratish (Alembic o'rniga tez yo'l) + yengil avto-migratsiya."""
from sqlalchemy import inspect, text

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import engine

# Mavjud jadvalga keyinroq qo'shilgan ustunlar (create_all ularni qo'shmaydi).
# (jadval, ustun, SQL-tur) — SQLite ham, Postgres ham tushunadigan turlar.
_ADDED_COLUMNS = [
    ("products", "sku", "VARCHAR"),
    ("products", "expiry_date", "DATE"),
]


def _ensure_columns():
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for table, col, sqltype in _ADDED_COLUMNS:
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if col in existing:
            continue
        try:
            with engine.begin() as con:
                con.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {sqltype}'))
            print(f"[migrate] {table}.{col} qo'shildi")
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] {table}.{col} — o'tkazib yuborildi ({e})")


def main():
    Base.metadata.create_all(engine)
    _ensure_columns()
    print("[OK] Jadvallar yaratildi")


if __name__ == "__main__":
    main()
