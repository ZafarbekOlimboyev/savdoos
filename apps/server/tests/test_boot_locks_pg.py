# -*- coding: utf-8 -*-
"""BOOT QULFLARI — HAQIQIY PostgreSQL'da, HAQIQIY `python -m app.initdb` (`__main__`) yo'li.

⚠️  NEGA SUBPROCESS. Boot'ning `lock_timeout` i `__main__` da PGOPTIONS orqali qo'yiladi;
    jarayon ichidagi `initdb.main()` (conftest) uni OLMAYDI. Shu bois har boot bu yerda
    `start.sh` dagidek alohida jarayon (`SAVDOOS_BOOT_LOCK_TIMEOUT=1s` — sinov tez bo'lsin).

Bu fayl isbotlaydi:
  1. barqaror boot BIRORTA DDL yubormaydi (`ddl_command_start` zondi — qulfdan OLDIN
     ishlaydi); musbat nazorat: bitta indeks tushirilsa zond uni KO'RADI;
  2. `sales`/`doc_counters`/`stock_movements`/`products` da ochiq YOZUVCHI va
     `product_barcodes` da ochiq O'QUVCHI ostida barqaror boot KUTMAYDI (pg_locks);
  3. SALBIY NAZORAT: PG'ning o'zi `CREATE INDEX IF NOT EXISTS` (indeks BOR) va
     `DROP CONSTRAINT IF EXISTS` (cheklov YO'Q) uchun qulfni tekshiruvdan OLDIN so'raydi —
     ya'ni 2-sinov haqiqatan nimanidir o'lchaydi;
  4. tezlik indeksi yo'q + jadval band -> cheklangan vaqt, o'tkaziladi, keyingi boot quradi;
  5. MAJBURIY indeks yo'q + jadval band -> cheklangan vaqtda FATAL (blokerning pid'i bilan);
  6. MAJBURIY ustun yo'q + ochiq o'quvchi -> osilish emas, cheklangan FATAL;
  7. `product_barcodes_barcode_key`: yo'q bo'lsa ACCESS EXCLUSIVE so'ralmaydi; bor bo'lsa
     o'quvchi ostida faqat o'tkaziladi, o'quvchi ketgach tushiriladi;
  8. `create_all`: ota jadval band -> cheklangan FATAL, yarim jadval qolmaydi;
  9. `SAVDOOS_BOOT_LOCK_TIMEOUT` qoidasi Postgres'ning o'zi bilan AYNI: qabul qilinadigan
     qiymat ulanadi, rad etiladigani standartga almashadi — boot crash-loop'ga tushmaydi.

⚠️  Har ushlovchi ulanish `finally` da yopiladi; har boot jarayonining QATTIQ vaqt chegarasi
    bor — eski (cheksiz kutadigan) kodda sinov osilmaydi, `TimeoutExpired` bilan QIZIL bo'ladi.
"""
import contextlib
import os
import subprocess
import sys
import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

import app.initdb as I
from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LT_S = 1.0                                   # sinovdagi boot `lock_timeout` i (soniya)
# Bitta obyekt uchun eng uzun kutish: har urinish `lock_timeout`, orada pauza.
_BUDGET = I._DDL_LOCK_ATTEMPTS * _LT_S + (I._DDL_LOCK_ATTEMPTS - 1) * I._LOCK_RETRY_SLEEP
_SLACK = 60.0                                 # jarayon ishga tushishi + sekin CI
_HARD_TIMEOUT = 420                           # eski kod shu yerda osilib qolardi
_STRONG = {"ShareLock", "ShareRowExclusiveLock", "ExclusiveLock", "AccessExclusiveLock"}


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _boot(url, app=None):
    """(kod, chiqish, soniya). `PGAPPNAME` — pg_locks'da boot seansini aniq topish uchun."""
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test",
               SAVDOOS_BOOT_LOCK_TIMEOUT=f"{_LT_S:g}s", PYTHONIOENCODING="utf-8",
               PGAPPNAME=app or f"savdoos_boot_{uuid.uuid4().hex[:8]}")
    env.pop("PGOPTIONS", None)
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=_HARD_TIMEOUT, env=env)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t0


def _built(url) -> float:
    """Sxema quriladi; BARQAROR boot vaqti qaytadi (byudjetlar shunga nisbatan)."""
    _initdb(url)
    code, out, took = _boot(url)
    assert code == 0, out[-2500:]
    assert "[boot] lock_timeout=1s" in out, "PGOPTIONS boot seansiga yetmadi: " + out[-2500:]
    assert "qulf band" not in out, out[-2500:]
    return took


class _Holder:
    """Boshqa SEANSDA ochiq tranzaksiya — qulfni USHLAB turadi."""

    def __init__(self, eng, sql):
        self.con = eng.connect()
        try:
            self.pid = self.con.execute(text("SELECT pg_backend_pid()")).scalar()
            self.con.execute(text(sql))
        except Exception:
            self.con.close()
            raise

    def close(self):
        try:
            self.con.rollback()
        finally:
            self.con.close()


@contextlib.contextmanager
def _holding(eng, *sqls):
    hs = []
    try:
        for sql in sqls:
            hs.append(_Holder(eng, sql))
        yield hs
    finally:
        for h in hs:
            with contextlib.suppress(Exception):
                h.close()


def _held(eng, pid, table, mode):
    """Ushlovchi qulfni HAQIQATAN olganmi — aks holda sinov hech narsani o'lchamaydi."""
    with eng.connect() as con:
        return bool(con.execute(text(
            "SELECT 1 FROM pg_locks WHERE pid = :p AND granted AND mode = :m "
            "AND relation = to_regclass(:t)"), {"p": pid, "m": mode, "t": f"public.{table}"}).first())


def _regclass(eng, name) -> bool:
    with eng.connect() as con:
        return bool(con.execute(text("SELECT to_regclass(:q) IS NOT NULL"),
                                {"q": f"public.{name}"}).scalar())


def _column(eng, table, col) -> bool:
    with eng.connect() as con:
        return bool(con.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = :t AND column_name = :c"), {"t": table, "c": col}).first())


def _constraint(eng, table, name) -> bool:
    with eng.connect() as con:
        return bool(con.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass(:t) AND conname = :n"),
            {"t": f"public.{table}", "n": name}).first())


def _fatal(out):
    return [ln for ln in out.splitlines() if ln.startswith("[FATAL]")]


class _Sampler(threading.Thread):
    """`application_name` bo'yicha boot seanslarining pg_locks'dagi HAR qulfini yig'adi.

    AUTOCOMMIT: `pg_stat_activity` tranzaksiya ichida KESHLANADI — bitta tranzaksiyada
    so'ralsa yangi seanslar umuman ko'rinmasdi."""

    SQL = text(
        "SELECT a.pid, l.locktype, c.relname, l.mode, l.granted "
        "FROM pg_stat_activity a "
        "LEFT JOIN pg_locks l ON l.pid = a.pid "
        "LEFT JOIN pg_class c ON c.oid = l.relation "
        "WHERE a.application_name = :app AND a.pid <> pg_backend_pid()")

    def __init__(self, url, app):
        super().__init__(daemon=True)
        self.eng = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        self.app, self.halt = app, threading.Event()
        self.pids, self.locks, self.error = set(), set(), None

    def run(self):
        try:
            with self.eng.connect() as con:
                while not self.halt.is_set():
                    for pid, locktype, rel, mode, granted in con.execute(self.SQL, {"app": self.app}):
                        self.pids.add(pid)
                        if mode is not None:
                            self.locks.add((locktype, rel, mode, bool(granted)))
                    time.sleep(0.02)
        except Exception as e:      # noqa: BLE001
            self.error = e

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.halt.set()
        self.join(timeout=30)
        self.eng.dispose()


# ══ 1. BARQAROR BOOT — NOL DDL ══════════════════════════════════════════════

_DDL_PROBE = (
    "CREATE TABLE boot_ddl_log (tag text, query text)",
    "CREATE FUNCTION boot_ddl_log_fn() RETURNS event_trigger LANGUAGE plpgsql AS $$ "
    "BEGIN INSERT INTO public.boot_ddl_log (tag, query) VALUES (tg_tag, current_query()); END $$",
    "CREATE EVENT TRIGGER boot_ddl_probe ON ddl_command_start EXECUTE FUNCTION boot_ddl_log_fn()",
)


def _ddl_log(eng):
    with eng.connect() as con:
        return [(r[0], r[1]) for r in con.execute(text("SELECT tag, query FROM boot_ddl_log"))]


def test_PG_BARQAROR_boot_BIRORTA_DDL_yubormaydi(pg_target):
    """`ddl_command_start` jadval qulfidan OLDIN ishga tushadi — `IF NOT EXISTS` ham ko'rinadi."""
    _built(pg_target)
    eng = create_engine(pg_target)
    try:
        with eng.begin() as con:
            for stmt in _DDL_PROBE:
                con.execute(text(stmt))
        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        ddl = _ddl_log(eng)
        assert ddl == [], ("barqaror boot DDL yubordi (har biri jadvalga qulf so'raydi):\n  "
                           + "\n  ".join(f"{t}: {q[:120]}" for t, q in ddl))

        # MUSBAT NAZORAT: zond boot DDL'ini haqiqatan KO'RADI.
        with eng.begin() as con:
            con.execute(text("DROP INDEX ix_sales_shift"))
            con.execute(text("DELETE FROM boot_ddl_log"))
        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        ddl = _ddl_log(eng)
        assert [t for t, _q in ddl] == ["CREATE INDEX"], ddl
        assert "ix_sales_shift" in ddl[0][1], ddl
    finally:
        eng.dispose()


# ══ 2. BARQAROR BOOT — OCHIQ YOZUVCHI / O'QUVCHI OSTIDA ══════════════════════

_HOT = ("sales", "doc_counters", "stock_movements", "products")


def test_PG_BARQAROR_boot_ochiq_YOZUVCHI_va_OQUVCHI_ostida_KUTMAYDI(pg_target):
    base = _built(pg_target)
    eng = create_engine(pg_target)
    app = f"savdoos_boot_{uuid.uuid4().hex[:8]}"
    try:
        sqls = [f"LOCK TABLE {t} IN ROW EXCLUSIVE MODE" for t in _HOT]
        with _holding(eng, *sqls, "SELECT 1 FROM product_barcodes") as hs:
            for h, t in zip(hs, _HOT):
                assert _held(eng, h.pid, t, "RowExclusiveLock"), f"{t}: ushlovchi qulfsiz"
            assert _held(eng, hs[-1].pid, "product_barcodes", "AccessShareLock")
            with _Sampler(pg_target, app) as s:
                code, out, took = _boot(pg_target, app)
        assert s.error is None, s.error
        assert code == 0, out[-2500:]
        assert s.pids, "boot seansi pg_stat_activity'da ko'rinmadi — sinov o'lchamaydi"
        waited = sorted(x for x in s.locks if not x[3])
        assert not waited, f"barqaror boot qulf KUTDI: {waited}"
        strong = sorted(x for x in s.locks
                        if x[0] == "relation" and x[2] in _STRONG
                        and x[1] and not x[1].startswith("pg_"))
        assert not strong, f"barqaror boot jonli jadvalga kuchli qulf oldi: {strong}"
        assert "qulf band" not in out, out[-2500:]
        assert took < base * 2 + _SLACK, (took, base)
    finally:
        eng.dispose()


# ══ 3. SALBIY NAZORAT — PG QULFNI TEKSHIRUVDAN OLDIN OLADI ═══════════════════

def test_PG_NAZORAT_IF_NOT_EXISTS_va_DROP_IF_EXISTS_qulfni_TEKSHIRUVDAN_OLDIN_oladi(pg_target):
    """Prechek nega shart: obyekt holatidan qat'i nazar, `IF [NOT] EXISTS` qulf KUTADI."""
    _initdb(pg_target)
    eng = create_engine(pg_target)
    ddls = ("CREATE INDEX IF NOT EXISTS ix_sales_shift ON sales (shift_id)",
            "ALTER TABLE product_barcodes DROP CONSTRAINT IF EXISTS product_barcodes_barcode_key")
    try:
        assert _regclass(eng, "ix_sales_shift"), "indeks YO'Q — nazorat o'lchamaydi"
        assert not _constraint(eng, "product_barcodes", "product_barcodes_barcode_key")
        with _holding(eng, "LOCK TABLE sales IN ROW EXCLUSIVE MODE",
                      "SELECT 1 FROM product_barcodes"):
            for ddl in ddls:
                with eng.connect() as con:
                    con.execute(text("SET lock_timeout = '1s'"))
                    t0 = time.monotonic()
                    with pytest.raises(OperationalError) as ei:
                        con.execute(text(ddl))
                    waited = time.monotonic() - t0
                    con.rollback()
                assert getattr(ei.value.orig, "sqlstate", None) == "55P03", (ddl, ei.value)
                assert waited >= 0.9, f"{ddl}: kutmadi ({waited:.2f}s) — nazorat o'lchamaydi"
        # Ushlovchilar ketgach AYNI bayonotlar xatosiz no-op: yuqoridagi xato FAQAT qulfdan.
        with eng.begin() as con:
            con.execute(text("SET LOCAL lock_timeout = '1s'"))
            for ddl in ddls:
                con.execute(text(ddl))
    finally:
        eng.dispose()


# ══ 4–6. HAQIQIY MIGRATSIYA — CHEKLANGAN KUTISH ═════════════════════════════

def test_PG_TEZLIK_indeksi_yoq_jadval_BAND_boot_cheklangan_vaqtda_OTKAZADI(pg_target):
    base = _built(pg_target)
    eng = create_engine(pg_target)
    try:
        with eng.begin() as con:
            con.execute(text("DROP INDEX ix_sales_shift"))
        with _holding(eng, "LOCK TABLE sales IN ROW EXCLUSIVE MODE"):
            code, out, took = _boot(pg_target)
        assert code == 0, "TEZLIK indeksi boot'ni yiqitdi: " + out[-2500:]
        assert "ix_sales_shift: qulf band — 4/5" in out, out[-2500:]
        assert "[migrate] ix_sales_shift — o'tkazib yuborildi" in out, out[-2500:]
        assert "lock timeout" in out and not _fatal(out), out[-2500:]
        assert _BUDGET * 0.9 <= took < base + _BUDGET + _SLACK, (took, base, _BUDGET)
        assert not _regclass(eng, "ix_sales_shift"), "band jadvalda indeks qurilgan bo'lib chiqdi"

        code, out, _ = _boot(pg_target)
        assert code == 0 and "qulf band" not in out, out[-2500:]
        assert _regclass(eng, "ix_sales_shift"), "ushlovchi ketgach indeks qurilmadi"
    finally:
        eng.dispose()


def test_PG_MAJBURIY_indeks_yoq_jadval_BAND_boot_cheklangan_vaqtda_FATAL(pg_target):
    base = _built(pg_target)
    eng = create_engine(pg_target)
    try:
        with eng.begin() as con:
            con.execute(text("DROP INDEX ux_doc_counter"))
        with _holding(eng, "LOCK TABLE doc_counters IN ROW EXCLUSIVE MODE") as (h,):
            code, out, took = _boot(pg_target)
        assert code != 0, "MAJBURIY indeks qurilmay boot YASHIL tugadi: " + out[-2500:]
        fatal = _fatal(out)
        assert fatal and "MAJBURIY indeks yaratilmadi: ux_doc_counter" in fatal[0], out[-2500:]
        for part in ("doc_counters qulfi 5 urinishda", "lock_timeout=1s",
                     f"pid={h.pid} RowExclusiveLock", "lock timeout"):
            assert part in fatal[0], (part, fatal[0])
        assert took < base + _BUDGET + _SLACK, (took, base, _BUDGET)
        assert not _regclass(eng, "ux_doc_counter")

        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert _regclass(eng, "ux_doc_counter")
    finally:
        eng.dispose()


def test_PG_MAJBURIY_ustun_yoq_OQUVCHI_bor_boot_OSILMAYDI_cheklangan_FATAL(pg_target):
    """ADD COLUMN — ACCESS EXCLUSIVE: ochiq bitta SELECT ham ushlab turadi (gate L5 teskarisi)."""
    base = _built(pg_target)
    eng = create_engine(pg_target)
    try:
        from app.core import required_schema as rs
        assert ("stock_batches", "external_lot_id") in rs.REQUIRED_COLUMNS
        with eng.begin() as con:
            con.execute(text("ALTER TABLE stock_batches DROP COLUMN external_lot_id"))
        with _holding(eng, "SELECT 1 FROM stock_batches") as (h,):
            assert _held(eng, h.pid, "stock_batches", "AccessShareLock")
            code, out, took = _boot(pg_target)
        assert code != 0, "MAJBURIY ustun qo'shilmay boot YASHIL tugadi: " + out[-2500:]
        fatal = _fatal(out)
        assert fatal and "MAJBURIY ustun qo'shilmadi: stock_batches.external_lot_id" in fatal[0], \
            out[-2500:]
        for part in ("stock_batches qulfi 5 urinishda", "lock_timeout=1s",
                     f"pid={h.pid} AccessShareLock"):
            assert part in fatal[0], (part, fatal[0])
        assert took < base + _BUDGET + _SLACK, (took, base, _BUDGET)
        assert not _column(eng, "stock_batches", "external_lot_id")

        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert "stock_batches.external_lot_id qo'shildi" in out, out[-2500:]
        assert _column(eng, "stock_batches", "external_lot_id")
    finally:
        eng.dispose()


# ══ 7. product_barcodes — ESKI GLOBAL UNIQUE ════════════════════════════════

def test_PG_barcode_eski_cheklovi_YOQ_bolsa_ACCESS_EXCLUSIVE_soralmaydi_BOR_bolsa_tushiriladi(
        pg_target):
    _built(pg_target)
    eng = create_engine(pg_target)
    name = "product_barcodes_barcode_key"
    try:
        # (a) cheklov YO'Q + ochiq o'quvchi (`pg_dump` o'rnida): so'rov umuman yo'q.
        app = f"savdoos_boot_{uuid.uuid4().hex[:8]}"
        with _holding(eng, "SELECT 1 FROM product_barcodes"):
            with _Sampler(pg_target, app) as s:
                code, out, _ = _boot(pg_target, app)
        assert s.error is None and s.pids, (s.error, s.pids)
        assert code == 0 and "barcode global-unique drop" not in out, out[-2500:]
        assert not [x for x in s.locks if x[1] == "product_barcodes"
                    and x[2] == "AccessExclusiveLock"], s.locks

        # (b) NAZORAT: cheklov BOR + ochiq o'quvchi -> so'rov pg_locks'da KO'RINADI (sampler
        #     ko'r emas), boot esa `lock_timeout` dan keyin faqat o'tkazadi (FATAL emas).
        with eng.begin() as con:
            con.execute(text(f"ALTER TABLE product_barcodes ADD CONSTRAINT {name} UNIQUE (barcode)"))
        app2 = f"savdoos_boot_{uuid.uuid4().hex[:8]}"
        with _holding(eng, "SELECT 1 FROM product_barcodes"):
            with _Sampler(pg_target, app2) as s2:
                code, out, _ = _boot(pg_target, app2)
        assert s2.error is None, s2.error
        assert code == 0, out[-2500:]
        assert ("relation", "product_barcodes", "AccessExclusiveLock", False) in s2.locks, s2.locks
        assert "barcode global-unique drop — o'tkazib yuborildi" in out and "lock timeout" in out, \
            out[-2500:]
        assert _constraint(eng, "product_barcodes", name)

        # (c) o'quvchi yo'q -> tushiriladi.
        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert not _constraint(eng, "product_barcodes", name), "eski global unique qoldi"
    finally:
        eng.dispose()


# ══ 8. create_all — OTA JADVAL BAND ═════════════════════════════════════════

def test_PG_yangi_jadval_OTA_jadval_BAND_create_all_cheklangan_FATAL_yarim_jadval_YOQ(pg_target):
    base = _built(pg_target)
    eng = create_engine(pg_target)
    t = "return_item_resolution_allocations"
    try:
        with eng.begin() as con:
            con.execute(text(f"DROP TABLE {t}"))
        with _holding(eng, "LOCK TABLE returns IN ROW EXCLUSIVE MODE") as (h,):
            code, out, took = _boot(pg_target)
        assert code != 0, "jadval yaratilmay boot YASHIL tugadi: " + out[-2500:]
        fatal = _fatal(out)
        assert fatal and f"yangi jadval yaratilmadi (create_all): {t}" in fatal[0], out[-2500:]
        for part in ("5 urinishda", "lock_timeout=1s", f"returns: pid={h.pid} RowExclusiveLock"):
            assert part in fatal[0], (part, fatal[0])
        assert "create_all: qulf band — 4/5" in out, out[-2500:]
        assert took < base + _BUDGET + _SLACK, (took, base, _BUDGET)
        assert not _regclass(eng, t), "yarim jadval qoldi — create_all tranzaksiyasi qaytmadi"

        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert _regclass(eng, t) and _regclass(eng, "ux_rira_item_resolution")
    finally:
        eng.dispose()


# ══ 9. QULF CHEGARASI QIYMATI — POSTGRES BILAN AYNI QOIDA ════════════════════

_LT_CANDIDATES = ("0", "1", "750ms", "2s", "10min", "24d", "596h", "35791min", "2147483s",
                  "2147483647", "25d", "597h", "35792min", "2147484s", "3000000000", "08s",
                  "010", "5sec", "1.5s", "-1")


def test_PG_lock_timeout_QIYMAT_qoidasi_Postgres_bilan_AYNI_boot_crash_loopga_TUSHMAYDI(pg_target):
    """Startup opsiyasidagi yaroqsiz `lock_timeout` HAR ulanishni FATAL qiladi. Python qoidasi
    (`_boot_lock_timeout_ok`) qabul qilgan HAR qiymatni Postgres ham qabul qilishi SHART — aks
    holda operator qo'ygan qiymat boot'ni butunlay to'xtatardi. Teskarisi xavfsiz: Python
    qat'iyroq bo'lsa (masalan `1.5s`) faqat standart 2s ishlaydi."""
    pg = {}
    for v in _LT_CANDIDATES:
        eng = create_engine(pg_target, poolclass=NullPool,
                            connect_args={"options": f"-c lock_timeout={v}"})
        try:
            with eng.connect() as con:
                con.execute(text("SELECT 1"))
            pg[v] = True
        except OperationalError:
            pg[v] = False
        finally:
            eng.dispose()
    dangerous = [v for v in _LT_CANDIDATES if I._boot_lock_timeout_ok(v) and not pg[v]]
    assert not dangerous, f"Python qabul qiladi, Postgres RAD etadi (boot crash-loop): {dangerous}"
    # Nazorat 1: eski qoida (`\d+(ms|s|min|h|d)?`) o'tkazgan bu qiymatlarni Postgres HAQIQATAN rad
    # etadi — ya'ni yuqoridagi tekshiruv real xavfni o'lchaydi.
    assert [v for v in ("25d", "3000000000", "08s") if pg[v]] == [], pg
    # Nazorat 2: qoida hammasini rad etmaydi — chegaradagi yaroqli qiymatlar o'tadi.
    assert all(I._boot_lock_timeout_ok(v) and pg[v] for v in ("0", "2s", "24d", "2147483647")), pg

    # Rad etiladigan qiymat bilan HAQIQIY boot: yiqilmaydi, standart 2s ishlaydi.
    _initdb(pg_target)
    env = dict(os.environ, DATABASE_URL=pg_target, APP_ENV="test", SAVDOOS_BOOT_LOCK_TIMEOUT="25d",
               PYTHONIOENCODING="utf-8")
    env.pop("PGOPTIONS", None)
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=_HARD_TIMEOUT, env=env)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-2500:]
    assert "SAVDOOS_BOOT_LOCK_TIMEOUT='25d' yaroqsiz" in out, out[-2500:]
    assert "[boot] lock_timeout=2s" in out, out[-2500:]
