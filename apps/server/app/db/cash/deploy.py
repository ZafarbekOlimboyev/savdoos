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


TABLE_FQN = "cash.cash_account_openings"
# Parallel boot uchun maslahat qulfi kaliti — BARQAROR konstanta ('savdoos:cash:phase1').
# Maslahat qulfi hech qanday JADVALGA qulf qo'ymaydi; u faqat DDL qo'llash yo'lini
# seriyalaydi va boshqa hech narsani kutdirmaydi.
_PHASE1_LOCK_KEY = 7723019283746501
_PHASE1_TRIGGERS = ("trg_cao_immutable", "trg_cao_no_truncate")
# rol -> shu rol uchun MAJBURIY imtiyoz(lar). Rol yo'q bo'lsa — talab ham yo'q.
_PHASE1_GRANTS = {"cash_readonly": ("SELECT",), "cash_app": ("SELECT",),
                  "cash_posting": ("SELECT", "INSERT"), "cash_admin": ("SELECT",)}


def _sections() -> dict:
    """`cash_ddl_phase1.sql` ni `-- @@SECTION: <nom>` belgilari bo'yicha ajratadi."""
    out, cur = {}, None
    for line in PHASE1_DDL_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("-- @@SECTION:"):
            cur = line.split(":", 1)[1].strip()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def phase1_missing(con) -> dict:
    """FAQAT O'QISH: qaysi Phase 1 obyekti YO'Q. Birorta DDL YUBORILMAYDI.

    ⚠️  `CREATE … IF NOT EXISTS` bu tekshiruvning O'RNINI BOSMAYDI: `ddl_command_start`
        hodisa trigger'i jadval qulfidan OLDIN ishlaydi, ya'ni `IF NOT EXISTS` ham DDL
        sifatida ro'yxatga tushadi va jonli jadvalga ShareLock so'raydi. Ishlab turgan
        do'konda bu yozuvchilarni to'sardi (`tests/test_boot_locks_pg.py`).

    ⚠️  SHAKLNI tekshirmaydi — faqat MAVJUDLIKNI. Nomi to'g'ri, shakli noto'g'ri obyekt
        BU YERDA «bor» hisoblanadi va TEGILMAYDI; uni `schema_readiness` topadi va
        tayyorlik QIZIL bo'ladi (yo'q -> yarat, bor-u noto'g'ri -> tegma)."""
    miss = {}
    miss["enum"] = con.execute(text(
        "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname='cash' AND t.typname='cash_source_type' AND e.enumlabel=:l"),
        {"l": PHASE1_SOURCE_TYPE}).first() is None
    miss["table"] = con.execute(text(
        "SELECT to_regclass(:t)"), {"t": TABLE_FQN}).scalar() is None
    if miss["table"]:
        # Jadval yo'q -> indeks/trigger/grant ham yo'q; ular jadval bo'limi bilan keladi.
        miss["index"] = miss["triggers"] = miss["grants"] = False
        return miss
    miss["index"] = con.execute(text(
        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname='cash' AND c.relname='cao_uq_entry' AND c.relkind='i'")).first() is None
    have_tg = {r[0] for r in con.execute(text(
        "SELECT tg.tgname FROM pg_trigger tg JOIN pg_class t ON t.oid = tg.tgrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname='cash' AND t.relname='cash_account_openings' AND NOT tg.tgisinternal"))}
    miss["triggers"] = any(t not in have_tg for t in _PHASE1_TRIGGERS)
    need_grant = False
    for role, privs in _PHASE1_GRANTS.items():
        if con.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}).first() is None:
            continue                      # rol yo'q -> grant ham talab qilinmaydi
        for p in privs:
            if not con.execute(text("SELECT has_table_privilege(:r, :t, :p)"),
                               {"r": role, "t": TABLE_FQN, "p": p}).scalar():
                need_grant = True
    miss["grants"] = need_grant
    return miss


def ensure_phase1_objects(engine: Engine) -> str:
    """Phase 1 (SEYF ochilishi) obyektlari — ADDITIV, IDEMPOTENT va BARQAROR BOOTDA NOL DDL.

    Qaytaradi: 'skipped-sqlite' | 'no-cash-schema' | 'noop' | 'applied:<bo'limlar>'.

    ⚠️  NEGA `deploy_cash_schema` NING ICHIDA EMAS. U hammasi-yoki-hech narsa: `cash`
        sxemasi mavjud bo'lsa 'exists' qaytaradi va DDL faylini butunlay o'tkazib
        yuboradi. Ishlab turgan do'kon uchun INKREMENTAL yo'l bugungacha YO'Q edi.

    ⚠️  AVVAL O'QIYMIZ, KEYIN YOZAMIZ. Hamma narsa joyida bo'lsa BIRORTA bayonot
        yuborilmaydi — `IF NOT EXISTS` ham DDL bo'lib, jonli jadvalga qulf so'raydi
        (`tests/test_boot_locks_pg.py`: barqaror boot NOL DDL).

    ⚠️  ENUM labeli ALOHIDA, AUTOCOMMIT ulanishida: `ALTER TYPE … ADD VALUE` PG'da
        tranzaksiya ichida ishlatilsa yangi label O'SHA tranzaksiyada ko'rinmaydi.

    ⚠️  MAVJUD trigger/funksiya HECH QACHON almashtirilmaydi (`DROP TRIGGER` yo'q).
    """
    if engine.dialect.name != "postgresql":
        return "skipped-sqlite"
    if not cash_schema_exists(engine):
        return "no-cash-schema"

    with engine.connect() as con:
        miss = phase1_missing(con)
    if not any(miss.values()):
        return "noop"                     # BARQAROR BOOT — birorta DDL yo'q

    # ── PARALLEL BOOT: maslahat qulfi + QULF OSTIDA QAYTA TEKSHIRISH ──────────
    #  ⚠️  `CREATE TABLE IF NOT EXISTS` PostgreSQL'da POYGAGA QARSHI HIMOYA EMAS:
    #      tekshiruv va yaratish atomar emas, shu bois ikki jarayon birga ko'tarilsa
    #      `pg_type_typname_nsp_index` unique violation beradi (test G shuni tutdi).
    #  ⚠️  Maslahat qulfi JADVALGA qulf QO'YMAYDI va u faqat nimadir YETISHMAGANDA
    #      olinadi — barqaror boot yo'li (nol bayonot) tegilmaydi.
    lock = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        lock.exec_driver_sql("SELECT pg_advisory_lock(%d)" % _PHASE1_LOCK_KEY)
        with engine.connect() as con:
            miss = phase1_missing(con)    # qulf ostida: raqib allaqachon qo'shgan bo'lishi mumkin
        if not any(miss.values()):
            return "noop-raced"
        return _apply_phase1(engine, miss)
    finally:
        try:
            lock.exec_driver_sql("SELECT pg_advisory_unlock(%d)" % _PHASE1_LOCK_KEY)
        finally:
            lock.close()


def _apply_phase1(engine: Engine, miss: dict) -> str:
    """FAQAT yetishmagan bo'limlarni qo'llaydi (maslahat qulfi ostida chaqiriladi)."""
    applied = []
    if miss["enum"]:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as con:
            con.exec_driver_sql("ALTER TYPE cash.cash_source_type ADD VALUE IF NOT EXISTS %s"
                                % _lit(PHASE1_SOURCE_TYPE))
        applied.append("enum")

    sec = _sections()
    # Jadval yo'q bo'lsa — jadval+indeks+trigger+grant BIRGA (qisman qolmasin).
    want = (["table", "index", "triggers", "grants"] if miss["table"]
            else [k for k in ("index", "triggers", "grants") if miss[k]])
    body = "\n\n".join(sec[k] for k in want if sec.get(k))
    if body:
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute(body)   # parametrsiz: psycopg3 '%' ni placeholder deb PARSE QILMAYDI
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
        applied.extend(want)
    return "applied:" + ",".join(applied)


def _lit(s: str) -> str:
    """SQL satr literali — bu yerda faqat MODUL KONSTANTASI uchun ishlatiladi."""
    return "'" + str(s).replace("'", "''") + "'"
