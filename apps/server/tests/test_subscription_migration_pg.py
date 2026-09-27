# -*- coding: utf-8 -*-
"""Phase 6A/2.5 sxema migratsiyasi — YANGI va YANGILANGAN baza TENG bo'lsin.

NEGA BU FAYL BOR
================
`create_all` MAVJUD jadvalga CHECK ham, ustun ham qo'shmaydi; `_index()` esa indeks
mavjudligini FAQAT NOM bo'yicha tekshiradi. Ya'ni AYNI kod ikki xil sxema berishi
mumkin edi: yangi bazada 4 ta CHECK va kompozit indeks, gate commit'ida (`43560b2`)
tug'ilgan bazada esa 0 ta CHECK va global indeks — model «kompozit» deb turganda.
O'lchangan farq: fresh-only 7, upgraded-only 1. Bu fayl farq NOLGA tushganini
qulflaydi va tuzatish yo'llari ishlashini isbotlaydi.

Obyekt NOMI bor-yo'qligini tekshirish YETARLI EMAS — `indkey`, predikat va CHECK
ta'riflari to'liq solishtiriladi.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

P6A_TABLES = ["plans", "subscriptions", "subscription_payments",
              "platform_admins", "admin_audit_log"]
P6A_CHECKS = ["ck_sub_deleted_never", "ck_sub_restricted_iff", "ck_sub_cancelled_iff",
              "ck_sub_status_persistable", "ck_audit_sub_fields"]
OLD_INDEX_DDL = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_subpay_client_uuid "
                 "ON subscription_payments (client_uuid) WHERE client_uuid IS NOT NULL")


# ══ Yordamchilar ════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pgbase():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp())
    u = srv.get_uri()
    yield ("postgresql+psycopg://" + u[len("postgresql://"):]
           if u.startswith("postgresql://") and "+psycopg" not in u else u)


def _db(pgbase: str, name: str) -> str:
    """Bir martalik baza yaratadi va uning DSN'ini qaytaradi.

    ⚠️  DSN SATR KESISH BILAN QURILMAYDI. Linux'da `pgserver` UNIX-SOKET beradi
        (`postgresql+psycopg://user@/postgres?host=%2Ftmp%2F...`) — o'sha yerda
        oxirgi `/` gacha kesish DSN'ni buzadi va ulanish yiqiladi. Windows'da esa
        TCP (`...@127.0.0.1:5432/postgres`) bo'lgani uchun xato KO'RINMAY qolardi:
        mahalliy to'plam yashil, CI (ubuntu) qizil. `make_url(...).set(database=...)`
        ikkala shaklni ham to'g'ri tutadi — repo naqshi:
        `tests/test_check_defs_pg.py:78-82`.
    """
    eng = create_engine(pgbase, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as con:
            con.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            con.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        eng.dispose()
    return make_url(pgbase).set(database=name).render_as_string(hide_password=False)


def _initdb(url: str, *, inject: str | None = None) -> str:
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test")
    env.pop("PYTHONIOENCODING", None)
    cmd = [sys.executable, "-c", inject] if inject else [sys.executable, "-m", "app.initdb"]
    r = subprocess.run(cmd, cwd=SRV, capture_output=True, text=True, timeout=900, env=env)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-2500:]
    return out


def fingerprint(url: str) -> list[str]:
    """Sxemaning SEMANTIK barmoq izi — nom emas, TA'RIF."""
    eng = create_engine(url)
    lines: list[str] = []
    try:
        with eng.connect() as c:
            for r in c.execute(text(
                "SELECT table_name, column_name, data_type, character_maximum_length, "
                "       is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND (table_name = ANY(:t) "
                "   OR (table_name='companies' AND column_name='status'))"
            ), {"t": P6A_TABLES}):
                lines.append("col\t" + "\t".join("" if v is None else str(v) for v in r))
            for r in c.execute(text(
                "SELECT rel.relname, con.conname, pg_get_constraintdef(con.oid), "
                "       con.convalidated "
                "FROM pg_constraint con JOIN pg_class rel ON rel.oid=con.conrelid "
                "JOIN pg_namespace n ON n.oid=rel.relnamespace "
                "WHERE n.nspname='public' AND rel.relname = ANY(:t) "
                "  AND con.contype IN ('c','f')"), {"t": P6A_TABLES}):
                lines.append("con\t" + "\t".join(str(v) for v in r))
            for r in c.execute(text(
                "SELECT rel.relname, idx.relname, i.indisunique, i.indisvalid, "
                "       pg_get_indexdef(i.indexrelid), "
                "       (SELECT array_agg(a.attname ORDER BY k.ord) "
                "          FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) "
                "          JOIN pg_attribute a ON a.attrelid=i.indrelid "
                "                             AND a.attnum=k.attnum) "
                "FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid "
                "JOIN pg_class rel ON rel.oid=i.indrelid "
                "JOIN pg_namespace n ON n.oid=rel.relnamespace "
                "WHERE n.nspname='public' AND rel.relname = ANY(:t)"), {"t": P6A_TABLES}):
                lines.append("idx\t" + "\t".join(str(v) for v in r))
            for r in c.execute(text(
                "SELECT rel.relname, t.tgname, pg_get_triggerdef(t.oid) "
                "FROM pg_trigger t JOIN pg_class rel ON rel.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=rel.relnamespace "
                "WHERE n.nspname='public' AND NOT t.tgisinternal "
                "  AND rel.relname = ANY(:t)"), {"t": P6A_TABLES}):
                lines.append("trg\t" + "\t".join(str(v) for v in r))
    finally:
        eng.dispose()
    return sorted(lines)


def _make_gate_shaped(url: str) -> None:
    """Bazani `43560b2` HOLATIGA qaytaradi: 5 CHECK yo'q, indeks GLOBAL, 2 ustun yo'q.

    ⚠️  Bu «eski kodni yurgizish» emas, ESKI SXEMANI tiklash: aynan shu uchta farq
        `43560b2` da boot qilingan bazani hozirgidan ajratib turadi.
    """
    eng = create_engine(url)
    try:
        with eng.begin() as c:
            for name in P6A_CHECKS:
                tbl = "admin_audit_log" if name == "ck_audit_sub_fields" else "subscriptions"
                c.execute(text(f'ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {name}'))
            c.execute(text("ALTER TABLE admin_audit_log DROP COLUMN IF EXISTS actor_login"))
            c.execute(text("ALTER TABLE admin_audit_log DROP COLUMN IF EXISTS actor_role"))
            c.execute(text("DROP INDEX IF EXISTS ux_subpay_client_uuid"))
            c.execute(text("CREATE UNIQUE INDEX ux_subpay_client_uuid ON "
                           "subscription_payments (client_uuid) "
                           "WHERE client_uuid IS NOT NULL"))
    finally:
        eng.dispose()


def _index_shape(url: str):
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            return c.execute(text(
                "SELECT i.indisunique, pg_get_expr(i.indpred, i.indrelid), "
                "       (SELECT array_agg(a.attname ORDER BY k.ord) "
                "          FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) "
                "          JOIN pg_attribute a ON a.attrelid=i.indrelid "
                "                             AND a.attnum=k.attnum) "
                "FROM pg_index i JOIN pg_class c2 ON c2.oid=i.indexrelid "
                "JOIN pg_namespace n ON n.oid=c2.relnamespace "
                "WHERE n.nspname='public' AND c2.relname='ux_subpay_client_uuid'")).first()
    finally:
        eng.dispose()


def _seed_minimal(url: str) -> tuple[str, str]:
    """Bitta kompaniya va tarif — FK'lar qanoatlansin.

    ⚠️  ORM orqali: `companies` da NOT NULL, lekin default'i PYTHON tomonida bo'lgan
        ustunlar bor (`currency`) — xom `INSERT` ularni to'ldirmasdi.
    """
    from sqlalchemy.orm import Session

    from app.models.org import Company
    from app.models.subscription import Plan
    eng = create_engine(url)
    cid, pid = uuid.uuid4(), uuid.uuid4()
    try:
        with Session(eng) as s:
            s.add(Company(id=cid, name=f"M-{cid.hex[:6]}"))
            s.add(Plan(id=pid, code=f"P-{pid.hex[:8]}", name="P"))
            s.commit()
    finally:
        eng.dispose()
    return str(cid), str(pid)


def _pay(url: str, company_id: str, client_uuid: str):
    eng = create_engine(url)
    try:
        with eng.begin() as c:
            c.execute(text(
                "INSERT INTO subscription_payments "
                "(id, company_id, amount, currency, method, paid_at, client_uuid) "
                "VALUES (gen_random_uuid(), :c, 100, 'UZS', 'CASH', now(), :u)"),
                {"c": company_id, "u": client_uuid})
    finally:
        eng.dispose()


# ══ 1. PARITY ══════════════════════════════════════════════════════════════

def test_PG_FRESH_va_YANGILANGAN_sxema_TENG(pgbase):
    fresh = _db(pgbase, "p6a_fresh")
    _initdb(fresh)

    upg = _db(pgbase, "p6a_upg")
    _initdb(upg)
    _make_gate_shaped(upg)
    #  Gate holatida farq HAQIQATAN bor bo'lsin — aks holda test hech nimani isbotlamasdi.
    assert fingerprint(upg) != fingerprint(fresh), "gate holati tiklanmadi"
    out = _initdb(upg)
    assert "ux_subpay_client_uuid: (client_uuid) -> (company_id, client_uuid)" in out

    only_fresh = [l for l in fingerprint(fresh) if l not in fingerprint(upg)]
    only_upg = [l for l in fingerprint(upg) if l not in fingerprint(fresh)]
    assert (only_fresh, only_upg) == ([], []), {
        "faqat_fresh": only_fresh[:6], "faqat_upgraded": only_upg[:6]}


def test_PG_IKKINCHI_boot_IDEMPOTENT(pgbase):
    url = _db(pgbase, "p6a_idem")
    _initdb(url)
    before = fingerprint(url)
    out = _initdb(url)
    assert fingerprint(url) == before
    assert "ux_subpay_client_uuid:" not in out, "indeks IKKINCHI marta ko'chirildi"
    assert "ck_sub_deleted_never qo'shildi" not in out


# ══ 2. INDEKS MIGRATSIYASI ═════════════════════════════════════════════════

def test_PG_ESKI_indeks_XAVFSIZ_kochiriladi_va_SEMANTIKA_ozgaradi(pgbase):
    url = _db(pgbase, "p6a_idx")
    _initdb(url)
    _make_gate_shaped(url)
    assert list(_index_shape(url)[2]) == ["client_uuid"]

    #  ESKI shaklda: boshqa kompaniya AYNI kalitni ishlata OLMAYDI.
    a, _ = _seed_minimal(url)
    b, _ = _seed_minimal(url)
    cu = str(uuid.uuid4())
    _pay(url, a, cu)
    with pytest.raises(Exception):
        _pay(url, b, cu)

    _initdb(url)
    uniq, pred, keys = _index_shape(url)
    assert (uniq, list(keys), pred) == (True, ["company_id", "client_uuid"],
                                        "(client_uuid IS NOT NULL)")
    #  YANGI shaklda: A/X o'tgan, B/X o'tadi, A/X takror RAD.
    _pay(url, b, cu)
    with pytest.raises(Exception):
        _pay(url, a, cu)


def test_PG_NOMALUM_indeks_TEGILMAYDI_fail_closed(pgbase):
    """Kutilmagan ta'rif JIMGINA qayta yozilmaydi — operator qo'ygan cheklov o'chmasin."""
    url = _db(pgbase, "p6a_idx_unknown")
    _initdb(url)
    eng = create_engine(url)
    try:
        with eng.begin() as c:
            c.execute(text("DROP INDEX ux_subpay_client_uuid"))
            #  Boshqacha shakl: NOYOB EMAS va predikatsiz.
            c.execute(text("CREATE INDEX ux_subpay_client_uuid ON "
                           "subscription_payments (client_uuid)"))
    finally:
        eng.dispose()
    out = _initdb(url)
    uniq, pred, keys = _index_shape(url)
    assert (uniq, pred, list(keys)) == (False, None, ["client_uuid"]), \
        "kutilmagan indeks O'ZGARTIRILDI — fail-closed buzildi"
    assert "KUTILMAGAN ta'rif" in out, out[-600:]


# ══ 3. IFLOS MA'LUMOT ══════════════════════════════════════════════════════

def test_PG_IFLOS_malumot_boot_YASHIL_tayyorlik_QIZIL_yangi_yozuv_BLOK(pgbase):
    url = _db(pgbase, "p6a_dirty")
    _initdb(url)
    _make_gate_shaped(url)
    cid, pid = _seed_minimal(url)

    eng = create_engine(url)
    try:
        with eng.begin() as c:      # ZID tarixiy qator (cheklovlar hali yo'q)
            c.execute(text(
                "INSERT INTO subscriptions (id, company_id, plan_id, started_at, "
                "current_period_start, current_period_end, grace_until, status, row_version) "
                "VALUES (gen_random_uuid(), :c, :p, now(), now(), now()+interval '30 day', "
                "        now()+interval '30 day', 'RESTRICTED', 1)"), {"c": cid, "p": pid})

        out = _initdb(url)          # boot YIQILMAYDI
        assert "ck_sub_restricted_iff TASDIQLANMADI" in out, out[-900:]

        with eng.connect() as c:
            st = dict(c.execute(text(
                "SELECT conname, convalidated FROM pg_constraint con "
                "JOIN pg_class r ON r.oid=con.conrelid "
                "WHERE r.relname IN ('subscriptions','admin_audit_log') "
                "  AND con.contype='c'")).all())
        assert st["ck_sub_restricted_iff"] is False, st
        assert all(v for k, v in st.items() if k != "ck_sub_restricted_iff"), st

        with eng.connect() as c:    # TARIXIY qator QAYTA YOZILMAGAN
            row = c.execute(text("SELECT status, restricted_at FROM subscriptions")).one()
        assert (row[0], row[1]) == ("RESTRICTED", None), "tarixiy qator o'zgartirilgan"

        with pytest.raises(Exception):   # YANGI zid yozuv — BLOK
            with eng.begin() as c:
                c.execute(text(
                    "INSERT INTO subscriptions (id, company_id, plan_id, started_at, "
                    "current_period_start, current_period_end, grace_until, status, row_version) "
                    "VALUES (gen_random_uuid(), :c, :p, now(), now(), now(), now(), "
                    "        'RESTRICTED', 1)"), {"c": cid, "p": pid})

        #  TAYYORLIK QIZIL — `soft_missing` orqali.
        from app.core import required_schema as rs
        ok, missing = rs.ok(eng)
        assert ok is False and any("ck_sub_restricted_iff" in m for m in missing), missing

        #  Operator qatorni TUZATGACH — tasdiqlanadi.
        with eng.begin() as c:
            c.execute(text("UPDATE subscriptions SET restricted_at = now()"))
        _initdb(url)
        with eng.connect() as c:
            v = c.execute(text(
                "SELECT convalidated FROM pg_constraint con JOIN pg_class r "
                "ON r.oid=con.conrelid WHERE con.conname='ck_sub_restricted_iff'")).scalar()
        assert v is True
        assert rs.ok(eng)[0] is True
    finally:
        eng.dispose()


# ══ 4. ROLLBACK ════════════════════════════════════════════════════════════

def test_PG_ROLLBACK_eski_kod_yoli_sxemani_BUZMAYDI(pgbase):
    """`43560b2` kodiga qaytilganda nima bo'lishini AYNI kod yo'li bilan tekshiradi.

    Eski boot ikki ish qilardi: (a) ESKI DDL bilan `_index(...)` chaqirardi,
    (b) `_ensure_lot_checks` ni O'Z ro'yxati bilan yurgizardi — unda 5 ta yangi nom
    YO'Q, ya'ni ularga tegmasdi. (a) shu yerda AYNAN o'sha funksiya va AYNAN o'sha
    eski DDL satri bilan takrorlanadi.
    """
    url = _db(pgbase, "p6a_rollback")
    _initdb(url)
    before = fingerprint(url)

    inject = (
        "import app.initdb as I\n"
        f"I._index({OLD_INDEX_DDL!r}, 'ux_subpay_client_uuid')\n"
        "print('[rollback] eski _index chaqirildi')\n")
    out = _initdb(url, inject=inject)
    assert "[rollback] eski _index chaqirildi" in out

    uniq, pred, keys = _index_shape(url)
    assert list(keys) == ["company_id", "client_uuid"], \
        "eski kod indeksni ESKI shaklga qaytardi — nom qisqa tutashuvi ishlamadi"
    assert fingerprint(url) == before, "rollback sxemani o'zgartirdi"
