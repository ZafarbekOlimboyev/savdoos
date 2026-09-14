# -*- coding: utf-8 -*-
"""CHECK TA'RIFI — haqiqiy PostgreSQL'da (Phase 4A.1).

⚠️  NEGA. Tayyorlik va `initdb` CHECK'ni ilgari faqat (jadval, nom) bo'yicha
    topardi. To'g'ri nomli, lekin boshqa ifodali (`CHECK (true)`) yoki PG18 dagi
    `NOT ENFORCED` cheklov «joyida» deb o'tardi: himoya yo'q, tayyorlik YASHIL,
    `/lots/enable` OCHIQ, `initdb` esa unga hech qachon tegmasdi.

Bu fayl isbotlaydi:
  · noto'g'ri ta'rif  -> tayyorlik QIZIL (soft), boot YIQILMAYDI, `/lots/enable` 409,
                          `initdb` AYNI ALTER ichida almashtiradi, keyingi boot no-op;
  · zid qatorlar bor  -> almashtirilgan cheklov NOT VALID qoladi, YANGI zid yozuv RAD,
                          qatorlar tuzatilgach `repair_lot_schema` tasdiqlaydi;
  · tahlil qilinmagan -> QIZIL, lekin avtomatik QAYTA YARATILMAYDI;
  · ustun tiplari farq -> kutilgan ifoda ham «noto'g'ri» yoziladi: QAYTA YARATILMAYDI,
                          har boot'da qulf sikli YO'Q (cheklov oid'i o'zgarmaydi);
  · halokatli CHECK yo'q -> `/lots/enable` ham 409 (review), repair tiklaydi;
  · NOT ENFORCED      -> PG18+ da aniqlanadi va almashtiriladi (CI `backend-pg18`); PG<18
                          da bu test OCHIQ skip qilinadi (o'tdi deb ko'rinmaydi), hujum
                          vektori yo'qligi esa alohida testda sintaksis rad etilishi bilan.

⚠️  `pytest.raises` ANIQ istisno turi bilan: `Exception` ichki `assert` ni ham yutib,
    hech narsaga tegmagan so'rovni «rad etildi» deb yolg'on yashil qilardi.

Maqsad-baza: har doim mahalliy pgserver; `SAVDOOS_TEST_PG_URL` berilsa (CI'dagi
postgres:18 servis) — o'sha serverda ham, har test uchun ALOHIDA baza yaratilib.
"""
import os
import subprocess
import sys
import types
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from tests.test_lot_phase4a_pg import SRV, _seed4a

_EXTERNAL = os.getenv("SAVDOOS_TEST_PG_URL", "").strip()
_TARGETS = ["pgserver"] + (["external"] if _EXTERNAL else [])


def _psycopg_url(u: str) -> str:
    for p in ("postgres://", "postgresql://"):
        if u.startswith(p):
            return "postgresql+psycopg://" + u[len(p):]
    return u


@pytest.fixture(params=_TARGETS)
def pg_target(request, tmp_path):
    if request.param == "pgserver":
        pgserver = pytest.importorskip("pgserver")
        srv = pgserver.get_server(str(tmp_path / "pgdata"))
        try:
            yield _psycopg_url(srv.get_uri())
        finally:
            try:
                srv.cleanup()
            except Exception:      # noqa: BLE001
                pass
        return
    from sqlalchemy.engine import make_url
    admin = make_url(_psycopg_url(_EXTERNAL))
    db = f"ckdef_{uuid.uuid4().hex[:12]}"
    aeng = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with aeng.connect() as con:
            con.execute(text(f'CREATE DATABASE "{db}"'))
        yield admin.set(database=db).render_as_string(hide_password=False)
    finally:
        with aeng.connect() as con:
            con.execute(text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        aeng.dispose()


def _initdb(url):
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                       text=True, timeout=900, env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    return r.stdout


def _repair(url):
    return subprocess.run([sys.executable, "-m", "app.tools.repair_lot_schema"], cwd=SRV,
                          capture_output=True, text=True, timeout=300,
                          env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))


def _replace(eng, table, name, clause):
    with eng.begin() as con:
        con.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT {name}, '
                         f"ADD CONSTRAINT {name} {clause}"))


def _catalog(eng, table, name):
    """(oid, pg_get_expr) yoki (None, None)."""
    with eng.connect() as con:
        row = con.execute(text(
            "SELECT c.oid, pg_get_expr(c.conbin, c.conrelid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = :t AND c.conname = :n "
            "AND c.contype = 'c'"), {"t": table, "n": name}).first()
    return (row[0], row[1]) if row else (None, None)


def _server_num(eng) -> int:
    with eng.connect() as con:
        return int(con.execute(text("SHOW server_version_num")).scalar())


def _enable_status(eng) -> int:
    """`/lots/enable` sxema darvozasi — mahsulot qidirilishidan OLDIN ishlaydi.

    409 = darvoza yopdi; 0 = darvozadan O'TIB soxta `db.get` ga yetdi.
    """
    from fastapi import HTTPException

    from app.api.v1.lots import enable_tracking
    fake_db = types.SimpleNamespace(get_bind=lambda: eng)
    try:
        enable_tracking(data=types.SimpleNamespace(product_id=None), emp=None, db=fake_db)
    except HTTPException as e:
        return e.status_code
    except AttributeError:
        return 0
    return 0


def _soft(rs, eng):
    soft = rs.soft_missing(eng)
    assert all(rs.is_soft(m) for m in soft), soft
    return soft


def test_PG_NOTOGRI_tarif_TAYYORLIK_QIZIL_enable_BLOK_initdb_ALMASHTIRADI(pg_target):
    from app.core import required_schema as rs
    _initdb(pg_target)
    eng = create_engine(pg_target)
    try:
        assert rs.ok(eng) == (True, []), rs.ok(eng)
        assert _enable_status(eng) == 0, "to'g'ri sxemada darvoza yopiq — sinov o'lchamaydi"

        # ── ayni nom, ma'nosi boshqa ta'rif — Phase 4A va HALOKATLI sinfdagi CHECK ──
        _replace(eng, "lot_shortfalls", "ck_lot_shortfall_resolved_le_qty", "CHECK (true)")
        _replace(eng, "products", "ck_track_expiry_implies_lots",
                 "CHECK (NOT (track_expiry OR track_lots))")
        soft = _soft(rs, eng)
        assert "cheklov ta'rifi noto'g'ri: ck_lot_shortfall_resolved_le_qty (lot_shortfalls)" \
            in soft, soft
        assert "cheklov ta'rifi noto'g'ri: ck_track_expiry_implies_lots (products)" in soft, soft
        assert rs.fatal_missing(eng) == [], "noto'g'ri ta'rif boot'ni YIQITADIGAN sinfga tushdi"
        assert rs.ok(eng)[0] is False
        assert _enable_status(eng) == 409, "noto'g'ri CHECK bilan partiya kuzatuvi OCHIQ qoldi"

        out = _initdb(pg_target)
        for n in ("ck_lot_shortfall_resolved_le_qty", "ck_track_expiry_implies_lots"):
            assert f"{n}: ta'rifi noto'g'ri edi — ayni tranzaksiyada qayta yaratildi" in out, out
            assert f"{n} tasdiqlandi" in out, out
        assert "ck_4a1_probe_tmp" not in str(_catalog(eng, "lot_shortfalls", "ck_4a1_probe_tmp"))
        assert _catalog(eng, "lot_shortfalls", "ck_4a1_probe_tmp") == (None, None), \
            "sinov nusxasi (probe) jadvalda QOLIB ketdi"
        assert rs.ok(eng) == (True, []), rs.ok(eng)
        assert _enable_status(eng) == 0

        # ── keyingi boot NO-OP: to'g'ri cheklov qayta yaratilmaydi (qulf sikli yo'q) ──
        before = _catalog(eng, "lot_shortfalls", "ck_lot_shortfall_resolved_le_qty")[0]
        again = _initdb(pg_target)
        assert "qayta yaratildi" not in again and "[migrate] ck_" not in again, again[-2000:]
        assert _catalog(eng, "lot_shortfalls", "ck_lot_shortfall_resolved_le_qty")[0] == before
    finally:
        eng.dispose()


def test_PG_NOTOGRI_tarif_ZID_qator_bilan_NOT_VALID_qoladi_XAVFSIZ_yol(pg_target):
    from app.core import required_schema as rs
    _initdb(pg_target)
    eng = create_engine(pg_target)
    try:
        st = _seed4a(eng)
        _replace(eng, "lot_shortfalls", "ck_lot_shortfall_resolved_le_qty", "CHECK (true)")
        # Noto'g'ri cheklov davrida ZID qator kirib qoldi.
        with eng.begin() as con:
            bad = con.execute(text(
                "INSERT INTO lot_shortfalls (id, company_id, branch_id, product_id, qty,"
                " resolved_qty, returned_qty, unit_cost, resolved_cost, created_at) VALUES"
                " (gen_random_uuid(), :c, :b, :p, 1, 2, 0, 1, 0, now()) RETURNING id"),
                {"c": st["cid"], "b": st["bids"][0], "p": st["pid"]}).scalar()

        out = _initdb(pg_target)
        assert "ck_lot_shortfall_resolved_le_qty: ta'rifi noto'g'ri edi" in out, out
        assert "ck_lot_shortfall_resolved_le_qty TASDIQLANMADI" in out, out
        assert "repair_lot_schema" in out, "xavfsiz yo'l ko'rsatilmadi"
        soft = _soft(rs, eng)
        assert "cheklov tasdiqlanmagan: ck_lot_shortfall_resolved_le_qty (lot_shortfalls)" \
            in soft, soft
        assert not any("ta'rifi noto'g'ri" in m for m in soft), "ta'rif tuzatilmadi"
        assert rs.fatal_missing(eng) == []
        assert _enable_status(eng) == 409

        # NOT VALID ham YANGILANGAN zid qatorni rad etadi (qator mavjud — so'rov bo'sh emas).
        with pytest.raises(IntegrityError):
            with eng.begin() as con:
                con.execute(text("UPDATE lot_shortfalls SET resolved_qty = 5 WHERE id = :i"),
                            {"i": bad})
        with eng.begin() as con:
            con.execute(text("UPDATE lot_shortfalls SET resolved_qty = 0 WHERE id = :i"),
                        {"i": bad})
        rr = _repair(pg_target)
        assert rr.returncode == 0, (rr.stdout + rr.stderr)[-1500:]
        assert rs.ok(eng) == (True, []), rs.ok(eng)
    finally:
        eng.dispose()


def test_PG_TAHLIL_qilinmagan_tarif_QIZIL_lekin_QAYTA_YARATILMAYDI(pg_target):
    from app.core import required_schema as rs
    _initdb(pg_target)
    eng = create_engine(pg_target)
    try:
        _replace(eng, "lot_shortfall_resolutions", "ck_lsr_qty_pos", "CHECK (abs(qty) > 0)")
        soft = _soft(rs, eng)
        assert "cheklov ta'rifini tekshirib bo'lmadi: ck_lsr_qty_pos (lot_shortfall_resolutions)" \
            in soft, soft
        assert rs.ok(eng)[0] is False
        assert _enable_status(eng) == 409

        before = _catalog(eng, "lot_shortfall_resolutions", "ck_lsr_qty_pos")
        out = _initdb(pg_target)
        assert "ck_lsr_qty_pos: katalogdagi ta'rifni tahlil qilib bo'lmadi" in out, out
        assert "ck_lsr_qty_pos: ta'rifi noto'g'ri edi" not in out
        assert _catalog(eng, "lot_shortfall_resolutions", "ck_lsr_qty_pos") == before, \
            "tahlil qilinmagan cheklov AVTOMATIK almashtirildi"
        assert rs.ok(eng)[0] is False, "tahlil qilinmagan ta'rif bilan tayyorlik YASHIL"

        _replace(eng, "lot_shortfall_resolutions", "ck_lsr_qty_pos", "CHECK (qty > 0)")
        assert rs.ok(eng) == (True, []), rs.ok(eng)
    finally:
        eng.dispose()


def test_PG_ustun_tiplari_FARQ_qilsa_QAYTA_YARATISH_SIKLI_YOQ(pg_target):
    """review: sxema modeldan og'gan (butun son + numeric) bo'lsa Postgres kutilgan ifodani
    ham keltirish bilan yozadi. Qayta yaratish natijani o'zgartirmaydi — shu bois u HAR
    boot'da jadvalni qulflab qayta yaratmasligi shart; tayyorlik esa QIZIL qoladi."""
    from app.core import required_schema as rs
    _initdb(pg_target)
    eng = create_engine(pg_target)
    try:
        with eng.begin() as con:
            con.execute(text("ALTER TABLE lot_shortfalls ALTER COLUMN resolved_qty DROP DEFAULT, "
                             "ALTER COLUMN resolved_qty TYPE integer USING resolved_qty::integer"))
        oid, expr = _catalog(eng, "lot_shortfalls", "ck_lot_shortfall_resolved_le_qty")
        assert "::numeric" in expr, f"Postgres keltirish qo'shmadi — sinov o'lchamaydi: {expr}"
        soft = _soft(rs, eng)
        assert "cheklov ta'rifi noto'g'ri: ck_lot_shortfall_resolved_le_qty (lot_shortfalls)" \
            in soft, soft

        for held in (False, True):
            # ⚠️  2-boot (re-review): jonli jadvalni boshqa seans O'QIYAPTI (ACCESS SHARE).
            #     Tekshiruv unga ACCESS EXCLUSIVE so'ramasligi shart — so'rasa, 1 s kutish va
            #     byudjet tugaguncha qayta urinish bo'lardi va quyidagi xabar CHIQMASDI.
            lock_con = eng.connect() if held else None
            if lock_con is not None:
                lock_con.begin()
                lock_con.execute(text("LOCK TABLE lot_shortfalls IN ACCESS SHARE MODE"))
            try:
                out = _initdb(pg_target)
            finally:
                if lock_con is not None:
                    lock_con.rollback()
                    lock_con.close()
            assert "qulf byudjeti tugadi" not in out, out
            assert "ck_lot_shortfall_resolved_le_qty: kutilgan ifoda ham shu sxemada tanilmadi" \
                in out, out
            assert "ck_lot_shortfall_resolved_le_qty: ta'rifi noto'g'ri edi" not in out, out
            assert _catalog(eng, "lot_shortfalls", "ck_lot_shortfall_resolved_le_qty")[0] == oid, \
                "cheklov qayta yaratildi — har boot'da qulf sikli"
            assert _catalog(eng, "lot_shortfalls", "ck_4a1_probe_tmp") == (None, None)
        assert rs.ok(eng)[0] is False, "og'gan sxemada tayyorlik YASHIL"
    finally:
        eng.dispose()


def test_PG_halokatli_CHECK_YOQ_bolsa_enable_BLOK_repair_TIKLAYDI(pg_target):
    """review: `ck_track_expiry_implies_lots` yo'qligi faqat `_fatal` da ko'rinadi —
    `/lots/enable` va repair vositasi uni ham ko'rishi shart."""
    from app.core import required_schema as rs
    _initdb(pg_target)
    eng = create_engine(pg_target)
    try:
        with eng.begin() as con:
            con.execute(text("ALTER TABLE products DROP CONSTRAINT ck_track_expiry_implies_lots"))
        assert "cheklov yo'q: ck_track_expiry_implies_lots (products)" in rs.fatal_missing(eng)
        assert rs.soft_missing(eng) == [], "sinov sharti: soft ro'yxat bo'sh bo'lishi kerak"
        assert _enable_status(eng) == 409, "halokatli CHECK yo'q, lekin partiya kuzatuvi OCHIQ"
        rr = _repair(pg_target)
        assert rr.returncode == 0, (rr.stdout + rr.stderr)[-1500:]
        assert "ck_track_expiry_implies_lots qo'shildi" in rr.stdout, rr.stdout
        assert rs.ok(eng) == (True, []), rs.ok(eng)
        assert _enable_status(eng) == 0
    finally:
        eng.dispose()


def test_PG_NOT_ENFORCED_cheklov_ANIQLANADI_va_ALMASHTIRILADI(pg_target):
    from app.core import required_schema as rs
    _initdb(pg_target)
    eng = create_engine(pg_target)
    try:
        if _server_num(eng) < 180000:
            pytest.skip("NOT ENFORCED CHECK faqat PostgreSQL 18+ da mavjud "
                        "(CI backend-pg18 job'ida ishlaydi)")

        st = _seed4a(eng)
        _replace(eng, "products", "ck_track_expiry_implies_lots",
                 "CHECK (NOT track_expiry OR track_lots) NOT ENFORCED")
        soft = _soft(rs, eng)
        assert "cheklov majburlanmagan: ck_track_expiry_implies_lots (products)" in soft, soft
        assert not any("ta'rifi" in m for m in soft), "ta'rif to'g'ri edi, xabar noto'g'ri"
        assert _enable_status(eng) == 409
        # Majburlanmagan cheklov zid yozuvni HAQIQATAN o'tkazib yuboradi.
        with eng.begin() as con:
            n = con.execute(text("UPDATE products SET track_expiry = true, track_lots = false "
                                 "WHERE id = :p"), {"p": st["pid"]}).rowcount
        assert n == 1

        out = _initdb(pg_target)
        assert "ck_track_expiry_implies_lots: NOT ENFORCED edi — ayni tranzaksiyada qayta yaratildi" \
            in out, out
        assert "ck_track_expiry_implies_lots TASDIQLANMADI" in out, out
        soft = _soft(rs, eng)
        assert "cheklov tasdiqlanmagan: ck_track_expiry_implies_lots (products)" in soft, soft
        assert not any("majburlanmagan" in m for m in soft), soft
        # NOT VALID ham YANGILANGAN zid qatorni rad etadi.
        with pytest.raises(IntegrityError):
            with eng.begin() as con:
                con.execute(text("UPDATE products SET track_expiry = true, track_lots = false "
                                 "WHERE id = :p"), {"p": st["pid"]})
        with eng.begin() as con:
            con.execute(text("UPDATE products SET track_expiry = false WHERE id = :p"),
                        {"p": st["pid"]})
        rr = _repair(pg_target)
        assert rr.returncode == 0, (rr.stdout + rr.stderr)[-1500:]
        assert rs.ok(eng) == (True, []), rs.ok(eng)
    finally:
        eng.dispose()


def test_PG18_dan_OLDIN_NOT_ENFORCED_sintaksisi_RAD_etiladi(pg_target):
    """PG<18: CHECK uchun NOT ENFORCED yo'q — hujum vektorining o'zi sintaksisda rad etiladi."""
    from app.core import required_schema as rs
    _initdb(pg_target)
    eng = create_engine(pg_target)
    try:
        if _server_num(eng) >= 180000:
            pytest.skip("PostgreSQL 18+: NOT ENFORCED mavjud — aniqlanishi alohida testda sinaladi")
        with pytest.raises(ProgrammingError):
            _replace(eng, "products", "ck_track_expiry_implies_lots",
                     "CHECK (NOT track_expiry OR track_lots) NOT ENFORCED")
        assert rs.ok(eng) == (True, []), rs.ok(eng)
    finally:
        eng.dispose()
