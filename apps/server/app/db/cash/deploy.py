"""Cash sxemasini o'rnatish (initdb ichidan chaqiriladi).

Cash quyi tizimi FAQAT PostgreSQL: alohida `cash` schema, PL/pgSQL trigger'lar,
deferred constraint trigger'lar, partial/INCLUDE index'lar — bularning hech biri
SQLite'da yo'q. Shuning uchun SQLite (dev/demo) da bu no-op.

Idempotent: `cash` schema allaqachon mavjud bo'lsa qayta o'rnatilmaydi.
Non-destructive: DDL faqat `cash` schema ichida CREATE qiladi va public.* jadvallarга
faqat REFERENCE beradi — hech qanday legacy jadval o'zgartirilmaydi/o'chirilmaydi.

Bitta tranzaksiyada bajariladi (migration plan §17: qisman qo'llanmasin).

DIQQAT (prod): DDL role/GRANT bo'limi CREATEROLE huquqini talab qiladi. Bu huquq
bo'lmagan managed Postgres'da o'sha bo'lim migration owner tomonidan alohida
qo'llanadi (migration plan §21). Superuser/owner bo'lgan muhitda (test pgserver,
odatdagi Railway owner) to'liq ishlaydi.
"""
from __future__ import annotations

import pathlib

from sqlalchemy import text
from sqlalchemy.engine import Engine

DDL_PATH = pathlib.Path(__file__).with_name("cash_ddl_v1.sql")


def cash_schema_exists(engine: Engine) -> bool:
    with engine.connect() as con:
        row = con.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'cash'")
        ).first()
    return row is not None


def deploy_cash_schema(engine: Engine, *, force: bool = False) -> str:
    """Cash DDL'ni o'rnatadi.

    Qaytaradi: 'skipped-sqlite' | 'exists' | 'deployed'.
    """
    if engine.dialect.name != "postgresql":
        return "skipped-sqlite"
    if not force and cash_schema_exists(engine):
        return "exists"
    ddl = DDL_PATH.read_text(encoding="utf-8")
    # RAW DBAPI kursori — parametrsiz cursor.execute(ddl): psycopg3 '%' ni placeholder
    # sifatida PARSE QILMAYDI (PL/pgSQL RAISE '%…' bor). SQLAlchemy exec_driver_sql bo'sh
    # parametr to'plamini uzatib '%' ni parse qilishga urinardi. Butun skript bitta
    # execute'да — server $$…$$ funksiya tanalarini o'zi to'g'ri parse qiladi (';' bo'yicha
    # bo'lmaymiz). Bitta tranzaksiya: xato bo'lsa hammasi qaytadi (migration plan §17).
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(ddl)
        # DDL ichidagi `SET search_path TO cash, public` SEANS darajasida — bu ulanish
        # hovuzga qaytganда oqib ketmasin (aks holda keyingi app so'rovlarида qualify
        # qilinmagan `shifts` -> cash.shifts bo'lib qolardi). Standartга qaytaramiz.
        cur.execute("RESET search_path")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return "deployed"
