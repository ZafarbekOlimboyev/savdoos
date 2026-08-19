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
    ("products", "is_weighted", "BOOLEAN"),
    ("products", "plu_code", "VARCHAR"),
    ("products", "scale_sync", "BOOLEAN"),
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


def _ensure_indexes():
    # PLU noyobligi uchun kompaniya doirasidagi qisman unique indeks (SQLite + Postgres).
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_products_company_plu "
                             "ON products (company_id, plu_code) WHERE plu_code IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_products_company_plu \u2014 o'tkazib yuborildi ({e})")


def main():
    Base.metadata.create_all(engine)
    _ensure_columns()
    _ensure_indexes()
    print("[OK] Jadvallar yaratildi")


if __name__ == "__main__":
    main()
