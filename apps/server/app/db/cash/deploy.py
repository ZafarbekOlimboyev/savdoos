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
PHASE1_DDL_PATH = pathlib.Path(__file__).with_name("cash_ddl_phase1.sql")

# Phase 1 (SEYF ochilishi) — `cash.cash_source_type` ga qo'shiladigan YANGI label.
# Ochilish legi RECONSTRUCTION EMAS (u `post_backfill_verification` darvozasining 10 ta
# majburiy tekshiruvidan 5 tasini yiqitardi), shu bois uning O'Z manba turi bor.
PHASE1_SOURCE_TYPE = "ACCOUNT_OPENING"


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


def ensure_phase1_objects(engine: Engine) -> str:
    """Phase 1 (SEYF ochilishi) obyektlari — ADDITIV va IDEMPOTENT.

    Qaytaradi: 'skipped-sqlite' | 'no-cash-schema' | 'ok'.

    ⚠️  NEGA `deploy_cash_schema` NING ICHIDA EMAS. U hammasi-yoki-hech narsa: `cash`
        sxemasi mavjud bo'lsa 'exists' qaytaradi va DDL faylini butunlay o'tkazib
        yuboradi. Ishlab turgan do'kon uchun INKREMENTAL yo'l bugungacha YO'Q edi —
        bu qadam aynan o'sha bo'shliqni yopadi (`PHASE1.md` §5).

    ⚠️  `cash` sxemasi YO'Q bo'lsa HECH NARSA qilmaydi: Phase 1 obyekti cash quyi
        tizimining bir qismi, uni sxemasiz yaratish ma'nosiz (va `cash_accounts` ga
        kompozit FK ham qurilmasdi).

    ⚠️  ENUM labeli ALOHIDA, AUTOCOMMIT ulanishida: `ALTER TYPE … ADD VALUE` PG'da
        tranzaksiya ichida ishlatilsa yangi label O'SHA tranzaksiyada ko'rinmaydi.
    """
    if engine.dialect.name != "postgresql":
        return "skipped-sqlite"
    if not cash_schema_exists(engine):
        return "no-cash-schema"

    # 1) enum labeli — alohida AUTOCOMMIT
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as con:
        con.exec_driver_sql(
            "ALTER TYPE cash.cash_source_type ADD VALUE IF NOT EXISTS %s" % _lit(PHASE1_SOURCE_TYPE))

    # 2) jadval + indeks + trigger + grantlar — BITTA tranzaksiya (qisman qolmasin)
    ddl = PHASE1_DDL_PATH.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(ddl)        # parametrsiz: psycopg3 '%' ni placeholder deb PARSE QILMAYDI
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return "ok"


def _lit(s: str) -> str:
    """SQL satr literali — bu yerda faqat MODUL KONSTANTASI uchun ishlatiladi."""
    return "'" + str(s).replace("'", "''") + "'"
