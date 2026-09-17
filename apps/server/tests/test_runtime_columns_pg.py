# -*- coding: utf-8 -*-
"""ISH VAQTI USTUNLARI / UUID TIP OG'ISHI / IDEMPOTENTLIK INDEKSLARI — HAQIQIY PostgreSQL (Phase 5B.1).

⚠️  NEGA SUBPROCESS. Boot'ning `lock_timeout` i `__main__` da PGOPTIONS orqali qo'yiladi
    (`tests/test_boot_locks_pg.py` bilan ayni yo'l, ayni yordamchilar).

⚠️  PHASE 5C. Boot tipni O'ZGARTIRMAYDI. Eski (a) sinovi — «boot varchar'ni uuid qiladi» —
    OLIB TASHLANDI, chunki u ENDI YO'Q xulqni mixlardi; uning o'rnini `tests/test_uuid_migration_pg.py`
    (operator migratsiyasi: preflight/apply/verify/revert, qulf, darvozalar) egalladi.

Bu fayl isbotlaydi:
  (b) tip og'ishi (UUID bo'lmagan qiymat bilan ham) -> boot exit 0, DDL YUBORILMAYDI, jurnalda
      o'zgarmas TAYYOR EMAS satri (qiymatsiz) + migratsiya maslahati, tayyorlik `column_types=false`;
      qiymat tuzatilgach ham boot TEGMAYDI — faqat ANIQ migratsiya tuzatadi va tayyorlik yashiladi;
  (c) SALBIY NAZORAT (nuqson): varchar ustunda ORM `CashMovement.client_uuid == uuid` 42883
      bilan yiqiladi, migratsiyadan keyin ishlaydi — ya'ni (b) haqiqiy nuqsonni o'lchaydi;
  (d) `ux_sales_company_client_uuid` yo'q + dublikat sotuvlar -> boot exit 0, tayyorlik
      `idempotency_schema=false` (partiya darvozasi OCHIQ); yiqilgan CONCURRENTLY qoldirgan
      YAROQSIZ va noyob BO'LMAGAN ayni nomli indeks ham QIZIL; dublikat olingach boot quradi;
  (e) ko'tarilgan MAJBURIY ustun (`employees.sec_epoch`, yon yo'ldan ko'chgan
      `product_barcodes.company_id`) yo'q + ochiq o'quvchi -> cheklangan FATAL uni nomlaydi;
      o'quvchi ketgach boot ustunni tiklaydi.
"""
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from tests.test_boot_locks_pg import (_BUDGET, _DDL_PROBE, _SLACK, _boot, _built, _column,
                                      _ddl_log, _fatal, _held, _holding, _regclass)
from tests.test_check_defs_pg import pg_target  # noqa: F401

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime.now(timezone.utc)
_UUID_COLS = (("cash_movements", "client_uuid"), ("qr_payments", "sale_id"),
              ("qr_payments", "client_uuid"))


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _types(eng) -> dict[tuple[str, str], str]:
    with eng.connect() as con:
        rows = con.execute(text(
            "SELECT c.relname, a.attname, t.typname FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_type t ON t.oid = a.atttypid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND a.attnum > 0 AND NOT a.attisdropped "
            "AND c.relname IN ('cash_movements', 'qr_payments') "
            "AND a.attname IN ('client_uuid', 'sale_id')")).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


def _to_varchar(eng, cols=_UUID_COLS):
    """Production holati: ustun `_ADDED_COLUMNS` ning eski `VARCHAR` i bilan qo'shilgan."""
    with eng.begin() as con:
        for t, c in cols:
            con.execute(text(f'ALTER TABLE "{t}" ALTER COLUMN "{c}" TYPE varchar USING "{c}"::text'))


def _probe(eng):
    with eng.begin() as con:
        for stmt in _DDL_PROBE:
            con.execute(text(stmt))


def _seed(eng) -> dict:
    """Kompaniya + filial + xodim + ochiq smena (ORM; drift'dan OLDIN)."""
    from app.models.auth import Employee, Role
    from app.models.org import Branch, Company
    from app.models.shifts import Shift
    with Session(eng) as s:
        co = Company(id=uuid.uuid4(), name="RT", code="rt" + uuid.uuid4().hex[:8], currency="UZS")
        s.add(co)
        s.flush()
        br = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="B1",
                    timezone="Asia/Bishkek", is_active=True)
        s.add(br)
        s.flush()
        role = s.query(Role).filter(Role.code == "ega").first() or s.query(Role).first()
        emp = Employee(id=uuid.uuid4(), company_id=co.id, full_name="RT",
                       phone="+9989" + str(uuid.uuid4().int)[:8], role_id=role.id)
        s.add(emp)
        s.flush()
        sh = Shift(id=uuid.uuid4(), branch_id=br.id, cashier_id=emp.id, opened_at=NOW)
        s.add(sh)
        out = {"cid": co.id, "bid": br.id, "eid": emp.id, "shift": sh.id}
        s.commit()
        return out


def _cash_row(con, shift_id, client_uuid, amount):
    con.execute(text(
        "INSERT INTO cash_movements (id, shift_id, type, amount, client_uuid, created_at) "
        "VALUES (:i, :s, 'payin', :a, :c, now())"),
        {"i": uuid.uuid4(), "s": shift_id, "a": amount, "c": client_uuid})


def _qr_row(con, sale_id, client_uuid, amount):
    con.execute(text(
        "INSERT INTO qr_payments (id, txn_id, amount, status, sale_id, client_uuid, created_at, "
        "updated_at) VALUES (:i, :t, :a, 'WAITING', :s, :c, now(), now())"),
        {"i": uuid.uuid4(), "t": "rt-" + uuid.uuid4().hex, "a": amount, "s": sale_id,
         "c": client_uuid})


def _ready(url) -> dict:
    """`/health/ready` — shu bazaga ulangan ALOHIDA jarayonda (ilova engine'i import paytida).

    ⚠️  `config` YASHIL BO'LISHI SHART. Postgres URL'da `settings.is_production` True, ya'ni
        standart SECRET_KEY va conftest'ning vendor kaliti `config` ni DOIM QIZIL qilardi —
        503 har holda chiqar, «yangi kalit tayyorlikni 503 qiladi» tekshiruvi hech narsani
        o'lchamas, «tuzatilgach 200» esa umuman yozib bo'lmasdi. Shu bois siyosatga mos kalit va
        vendor portali o'chiq (`tests/cash/test_backup_restore_chain.py` bilan ayni)."""
    code = ("import json" + chr(10) +
            "from app.api.v1 import health as H" + chr(10) +
            "class R: status_code = 200" + chr(10) +
            "r = R()" + chr(10) +
            "b = H.ready(r)" + chr(10) +
            "print('RESULT ' + json.dumps({'s': r.status_code, 'b': b}))" + chr(10))
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test", PYTHONIOENCODING="utf-8",
               VENDOR_ADMIN_KEY="", SECRET_KEY="Rk7-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0cW")
    env.pop("RAILWAY_ENVIRONMENT_NAME", None)
    env.pop("PGOPTIONS", None)
    r = subprocess.run([sys.executable, "-c", code], cwd=SRV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2500:]
    return json.loads(r.stdout.split("RESULT ", 1)[1].strip())


# ══ (b) BOOT TIPNI O'ZGARTIRMAYDI — DDL YO'Q, TAYYORLIK QIZIL, MIGRATSIYA TUZATADI ══

def _tool_apply(eng):
    """Operator migratsiyasi — jarayon ichida (CLI darvozalari `test_uuid_migration_pg.py` da)."""
    from app.db.migrations import get
    mig = get("2026-09-17.uuid-client-columns-v1")
    with eng.connect() as con:
        report = mig.preflight(con)
    assert report["verdict"] == "READY", report["verdict"]
    with eng.begin() as con:
        return mig.apply(con, reviewed_report=report)


def test_PG_UUID_BOLMAGAN_qiymat_boot_YIQILMAYDI_DDL_YOQ_tayyorlik_QIZIL_MIGRATSIYA_tuzatadi(pg_target):
    import app.initdb as I
    from app.core import required_schema as rs
    _built(pg_target)
    eng = create_engine(pg_target)
    maxfiy = "not-a-uuid-MAXFIY-42"
    try:
        _to_varchar(eng, [("qr_payments", "client_uuid")])
        with eng.begin() as con:
            _qr_row(con, None, maxfiy, 1)
        _probe(eng)

        code, out, _ = _boot(pg_target)
        assert code == 0, "UUID bo'lmagan qiymat boot'ni YIQITDI (crash-loop): " + out[-2500:]
        assert _ddl_log(eng) == [], f"boot tip og'ishida DDL yubordi: {_ddl_log(eng)}"
        assert _types(eng)[("qr_payments", "client_uuid")] == "varchar"
        assert ("[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: "
                "qr_payments.client_uuid") in out, out[-2500:]
        assert I._UUID_MIGRATION_HINT in out, out[-2500:]
        assert maxfiy not in out, "qiymat jurnalga tushdi"
        assert not _fatal(out)
        assert rs.column_type_problems(eng) == ["ustun tipi uuid emas: qr_payments.client_uuid"]
        assert rs.missing(eng) == [], "tip muammosi partiya darvozasiga (`missing`) sizib kirdi"

        res = _ready(pg_target)
        assert res["s"] == 503, res
        checks = res["b"]["checks"]
        assert checks["column_types"] is False, res
        assert checks["idempotency_schema"] is True and checks["catalog_v2_schema"] is True, res
        assert checks["lot_schema_integrity"] is True, res
        # 503 ning YAGONA sababi — shu kalit (`config` va boshqalar yashil).
        assert [k for k, v in checks.items() if v is not True] == ["column_types"], res
        assert "ustun tipi uuid emas: qr_payments.client_uuid" in res["b"]["missing_schema"], res
        assert maxfiy not in json.dumps(res)

        # Qiymat tuzatilgach ham BOOT tegmaydi (Phase 5C): tuzatish — operator migratsiyasi.
        good = str(uuid.uuid4())
        with eng.begin() as con:
            con.execute(text("UPDATE qr_payments SET client_uuid = :g WHERE client_uuid = :b"),
                        {"g": good, "b": maxfiy})
        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert _ddl_log(eng) == [], f"boot qiymat tuzatilgach ALTER yubordi: {_ddl_log(eng)}"
        assert _types(eng)[("qr_payments", "client_uuid")] == "varchar"
        assert _ready(pg_target)["s"] == 503

        # MUSBAT NAZORAT: ANIQ migratsiya tuzatadi va tayyorlik yashil bo'ladi.
        res_apply = _tool_apply(eng)
        assert res_apply["result"] == "APPLIED", res_apply
        assert [tag for tag, _q in _ddl_log(eng)] == ["ALTER TABLE"], _ddl_log(eng)
        assert _types(eng)[("qr_payments", "client_uuid")] == "uuid"
        assert rs.column_type_problems(eng) == []
        res = _ready(pg_target)
        assert res["s"] == 200 and res["b"]["checks"]["column_types"] is True, res
    finally:
        eng.dispose()


# ══ (c) SALBIY NAZORAT — ESKI XULQ: 42883 ═════════════════════════

def test_PG_NAZORAT_varchar_ustunda_ORM_uuid_taqqoslash_42883_MIGRATSIYADAN_keyin_ISHLAYDI(pg_target):
    from app.models.payments import QrPayment
    from app.models.shifts import CashMovement
    _built(pg_target)
    eng = create_engine(pg_target)
    queries = (select(CashMovement.id).where(CashMovement.client_uuid == uuid.uuid4()),
               select(QrPayment.id).where(QrPayment.sale_id == uuid.uuid4()),
               select(QrPayment.id).where(QrPayment.client_uuid == uuid.uuid4()))
    try:
        for q in queries:                                   # nazorat: uuid ustunda ishlaydi
            with Session(eng) as s:
                assert s.execute(q).all() == []
        _to_varchar(eng)
        for q in queries:
            with Session(eng) as s:
                with pytest.raises(ProgrammingError) as ei:
                    s.execute(q).all()
                assert getattr(ei.value.orig, "sqlstate", None) == "42883", ei.value
        _tool_apply(eng)
        for q in queries:
            with Session(eng) as s:
                assert s.execute(q).all() == []
    finally:
        eng.dispose()


# ══ (d) IDEMPOTENTLIK INDEKSI — DUBLIKATLAR USTIDA QURILMAYDI ═════════════════

def _sale(s, ids, client_uuid, receipt_no):
    from app.models.sales import Sale
    s.add(Sale(id=uuid.uuid4(), receipt_no=receipt_no, company_id=ids["cid"], branch_id=ids["bid"],
               cashier_id=ids["eid"], subtotal=1, total=1, sold_at=NOW, client_uuid=client_uuid))


def test_PG_idempotentlik_indeksi_DUBLIKAT_ustida_boot_YASHIL_tayyorlik_QIZIL_partiya_OCHIQ(pg_target):
    from app.core import required_schema as rs
    name = "ux_sales_company_client_uuid"
    ddl = (f"{name} ON sales (company_id, client_uuid) "
           "WHERE client_uuid IS NOT NULL AND deleted_at IS NULL")
    yoq = f"idempotentlik indeksi yo'q: {name} (sales)"
    _built(pg_target)
    eng = create_engine(pg_target)
    try:
        ids = _seed(eng)
        dup = uuid.uuid4()
        with eng.begin() as con:
            con.execute(text(f"DROP INDEX {name}"))
        with Session(eng) as s:
            _sale(s, ids, dup, "RT-1")
            _sale(s, ids, dup, "RT-2")
            s.commit()

        code, out, _ = _boot(pg_target)
        assert code == 0, "dublikat qatorlar boot'ni YIQITDI (crash-loop): " + out[-2500:]
        assert not _fatal(out), out[-2500:]
        assert f"[migrate] {name} — o'tkazib yuborildi" in out, out[-2500:]
        assert f"[schema] TAYYOR EMAS (boot davom etadi) — {yoq}" in out, out[-2500:]
        assert not _regclass(eng, name)
        assert rs.idempotency_missing(eng) == [yoq]
        assert rs.missing(eng) == [], "idempotentlik `missing()` ga sizib kirdi (partiya darvozasi)"
        res = _ready(pg_target)
        assert res["s"] == 503, res
        checks = res["b"]["checks"]
        assert checks["idempotency_schema"] is False, res
        assert checks["catalog_v2_schema"] is True and checks["lot_schema_integrity"] is True, res
        assert checks["column_types"] is True, res
        # 503 ning YAGONA sababi — shu kalit (`config` va boshqalar yashil).
        assert [k for k, v in checks.items() if v is not True] == ["idempotency_schema"], res
        assert res["b"]["missing_schema"] == [yoq], res

        # YAROQSIZ: yiqilgan CONCURRENTLY AYNI nomni qoldiradi — `_index` nom prechegi uni «bor»
        # deydi va DDL yubormaydi; faqat `indisvalid` tekshiruvi buni ko'radi.
        ac = create_engine(pg_target, isolation_level="AUTOCOMMIT")
        try:
            with ac.connect() as con:
                with pytest.raises(IntegrityError):
                    con.execute(text(f"CREATE UNIQUE INDEX CONCURRENTLY {ddl}"))
        finally:
            ac.dispose()
        assert _regclass(eng, name), "yiqilgan CONCURRENTLY indeks qoldirmadi — nazorat o'lchamaydi"
        _probe(eng)
        code, out, _ = _boot(pg_target)
        assert code == 0 and not _fatal(out), out[-2500:]
        assert _ddl_log(eng) == [], _ddl_log(eng)
        assert rs.idempotency_missing(eng) == [f"idempotentlik indeksi yaroqsiz: {name} (sales)"]
        res = _ready(pg_target)
        assert res["s"] == 503, res
        assert [k for k, v in res["b"]["checks"].items() if v is not True] == ["idempotency_schema"], res
        assert res["b"]["missing_schema"] == [f"idempotentlik indeksi yaroqsiz: {name} (sales)"], res

        # NOYOB EMAS: ayni nomli oddiy indeks.
        with eng.begin() as con:
            con.execute(text(f"DROP INDEX {name}"))
            con.execute(text(f"CREATE INDEX {ddl}"))
        assert rs.idempotency_missing(eng) == [f"idempotentlik indeksi noyob emas: {name} (sales)"]
        assert rs.missing(eng) == []

        # MUSBAT NAZORAT: dublikat olib tashlanib, noto'g'ri indeks tushirilgach boot QURADI.
        with eng.begin() as con:
            con.execute(text("DELETE FROM sales WHERE receipt_no = 'RT-2'"))
            con.execute(text(f"DROP INDEX {name}"))
            con.execute(text("DELETE FROM boot_ddl_log"))
        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert rs.idempotency_missing(eng) == []
        res = _ready(pg_target)
        assert res["s"] == 200 and res["b"]["checks"]["idempotency_schema"] is True, res
    finally:
        eng.dispose()


# ══ (e) KO'TARILGAN MAJBURIY USTUN — QULF OSTIDA CHEKLANGAN FATAL ═════════════

@pytest.mark.parametrize("table,col", [("employees", "sec_epoch"),
                                       ("product_barcodes", "company_id")])
def test_PG_KOTARILGAN_majburiy_ustun_yoq_OQUVCHI_bor_cheklangan_FATAL_keyin_TIKLANADI(
        pg_target, table, col):
    """Ilgari ikkalasi ham jim «o'tkazib yuborildi» edi (barkod — qulf chegarasiz yon yo'lda)."""
    from app.core import required_schema as rs
    assert (table, col) in rs.REQUIRED_COLUMNS
    base = _built(pg_target)
    eng = create_engine(pg_target)
    try:
        with eng.begin() as con:
            con.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{col}"'))
        with _holding(eng, f"SELECT 1 FROM {table}") as (h,):
            assert _held(eng, h.pid, table, "AccessShareLock")
            code, out, took = _boot(pg_target)
        assert code != 0, "MAJBURIY ustun qo'shilmay boot YASHIL tugadi: " + out[-2500:]
        fatal = _fatal(out)
        assert fatal and f"MAJBURIY ustun qo'shilmadi: {table}.{col}" in fatal[0], out[-2500:]
        for part in (f"{table} qulfi 5 urinishda", "lock_timeout=1s",
                     f"pid={h.pid} AccessShareLock"):
            assert part in fatal[0], (part, fatal[0])
        assert took < base + _BUDGET + _SLACK, (took, base, _BUDGET)
        assert not _column(eng, table, col)
        assert "[OK] Jadvallar yaratildi" not in out

        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert f"{table}.{col} qo'shildi" in out, out[-2500:]
        assert _column(eng, table, col)
        assert rs.fatal_missing(eng) == []
    finally:
        eng.dispose()
