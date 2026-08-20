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
    ("companies", "code", "VARCHAR"),
    ("inventory", "low_alerted", "BOOLEAN"),
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


def _backfill_company_codes():
    """Eski bazalarda companies.code NULL — PIN login scoping ishlashi uchun
    har mavjud kompaniyaga id'dan olingan noyob kod beramiz (dialekt-neytral)."""
    try:
        with engine.begin() as con:
            rows = con.execute(text(
                "SELECT id FROM companies WHERE code IS NULL AND deleted_at IS NULL"
            )).fetchall()
            for (cid,) in rows:
                code = str(cid).replace("-", "")[:8].lower()
                con.execute(text("UPDATE companies SET code = :c WHERE id = :i"), {"c": code, "i": cid})
                print(f"[migrate] companies.code backfill: {cid} -> {code}")
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] companies.code backfill — o'tkazib yuborildi ({e})")


def _ensure_indexes():
    # PLU noyobligi uchun kompaniya doirasidagi qisman unique indeks (SQLite + Postgres).
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_products_company_plu "
                             "ON products (company_id, plu_code) WHERE plu_code IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_products_company_plu \u2014 o'tkazib yuborildi ({e})")
    # Do'kon kodi noyobligi (bo'sh bo'lmagan, o'chirilmagan) \u2014 SQLite + Postgres.
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_companies_code "
                             "ON companies (code) WHERE code IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_companies_code \u2014 o'tkazib yuborildi ({e})")
    # Parolli akkaunt telefoni global noyob (race'ga qarshi DB-darajada, TOCTOU emas).
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_employees_phone_pw "
                             "ON employees (phone) WHERE phone IS NOT NULL "
                             "AND password_hash IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_employees_phone_pw \u2014 o'tkazib yuborildi ({e})")


def main():
    Base.metadata.create_all(engine)
    _ensure_columns()
    _backfill_company_codes()
    _ensure_indexes()
    print("[OK] Jadvallar yaratildi")


if __name__ == "__main__":
    main()
