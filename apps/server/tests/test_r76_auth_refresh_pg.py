"""R7.6 — refresh rotation'ning HAQIQIY PostgreSQL'dagi parallelligi.

NEGA ALOHIDA FAYL: SQLite'da haqiqiy parallel tranzaksiya yo'q, atomar
`UPDATE … WHERE refresh_hash = :old` ning CAS xossasini esa FAQAT real
baza isbotlaydi. R7.6 audit talabi: «Safe concurrent refresh handling» va
«deterministic tests for revoke races, concurrent requests».

⚠️  INVARIANT: parallel ikki refresh HECH QACHON sessiyani BEKOR QILMASLIGI
    kerak. Replay faqat ISTE'MOL QILINGAN kredensial grace oynasidan KEYIN
    kelganda aniqlanadi — benign poyga replay DEB HISOBLANMAYDI.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.models.auth import AuthSession, Employee
from app.models.enums import EmployeeStatus
from app.models.org import Company
from app.services import auth_session as AS


@pytest.fixture(scope="module")
def pgengine():
    url = os.environ.get("P0C_TEST_POSTGRES")
    if not url:
        pytest.skip("Dedicated real PostgreSQL unavailable; concurrency NOT VERIFIED")
    parsed = make_url(url)
    assert (parsed.host, parsed.port, parsed.username, parsed.database) == (
        "127.0.0.1", 55483, "p0c_local", "p0c_tests"), "Only isolated local test DB allowed"
    eng = create_engine(url, connect_args={
        "options": "-c statement_timeout=8000 -c lock_timeout=4000"})
    Base.metadata.create_all(eng)
    #  ⚠️  `create_all` MAVJUD jadvalga ustun QO'SHMAYDI. `auth_sessions`
    #      jadvali bu bazada (va PRODUCTION'da) allaqachon bor, lekin R7.6
    #      ning `prev_refresh_hash`/`rotated_at` ustunlari YO'Q. Ularni boot
    #      yo'lining O'ZI qo'shadi (`initdb._ensure_columns` ->
    #      `_ADDED_COLUMNS`), shu bois test AYNI o'sha yo'lni yurgizadi —
    #      "testda boshqa, production'da boshqa" holati bo'lmasin.
    import app.initdb as _initdb
    from app.db import session as _dbsess
    _prev = _dbsess.engine
    _dbsess.engine = eng
    _initdb.engine = eng
    try:
        _initdb._ensure_columns()
    finally:
        _dbsess.engine = _prev
        _initdb.engine = _prev
    yield eng
    eng.dispose()


@pytest.fixture()
def emp(pgengine):
    """O'z kompaniyasi va o'z xodimi — umumiy qatorga tayanmaydi."""
    with pgengine.begin() as conn:
        conn.execute(text("DELETE FROM auth_sessions"))
    with Session(pgengine) as db:
        from app.models.auth import Role
        role = db.scalar(select(Role).where(Role.code == "ega"))
        if role is None:
            role = Role(code="ega", name="Ega")
            db.add(role)
            db.flush()
        comp = Company(name="R76 Sintetik")
        db.add(comp)
        db.flush()
        e = Employee(company_id=comp.id, full_name="R76 Parallel", role_id=role.id,
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.commit()
        return e.id


def _rotate(engine, raw):
    """Alohida ulanishda rotation — natija yoki xato sababi."""
    with Session(engine) as db:
        try:
            _row, new_raw = AS.rotate(db, raw)
            db.commit()
            return ("ok", new_raw)
        except AS.RefreshError as e:
            if e.revoked:
                db.commit()
            else:
                db.rollback()
            return ("err", e.reason)


def _row(engine, employee_id):
    with Session(engine) as db:
        return db.scalar(select(AuthSession).where(
            AuthSession.employee_id == employee_id))


def _new_session(engine, employee_id):
    with Session(engine) as db:
        sid, raw = AS.create(db, employee_id)
        db.commit()
        return sid, raw


# ── 1. PARALLEL ikki refresh: sessiya TIRIK qoladi ──────────────────────────

def test_PARALLEL_ikki_refresh_sessiyani_BEKOR_QILMAYDI(pgengine, emp):
    _sid, raw = _new_session(pgengine, emp)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in
                   [pool.submit(_rotate, pgengine, raw), pool.submit(_rotate, pgengine, raw)]]
    kinds = sorted(k for k, _ in results)
    #  Ikki natija ham "ok" (biri grace orqali) YOKI biri "raced" bo'lishi
    #  mumkin — IKKI holat ham QABUL QILINADI. Taqiqlangan yagona natija:
    #  sessiyaning bekor bo'lishi.
    assert kinds in (["ok", "ok"], ["err", "ok"]), results
    assert all(r != "replay" for k, r in results if k == "err"), \
        f"benign poyga REPLAY deb baholandi: {results}"
    row = _row(pgengine, emp)
    assert row.revoked_at is None, "parallel refresh sessiyani O'LDIRMASLIGI kerak"
    #  Kamida bitta ishlaydigan kredensial qoldi.
    fresh = [v for k, v in results if k == "ok"]
    assert fresh, results
    assert _rotate(pgengine, fresh[-1])[0] == "ok", "oxirgi kredensial ishlashi kerak"


def test_PARALLEL_OLTI_refresh_ham_sessiyani_saqlaydi(pgengine, emp):
    """Ko'proq bosim: hech qanday holatda ham spurious revoke bo'lmasin."""
    _sid, raw = _new_session(pgengine, emp)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [f.result() for f in
                   [pool.submit(_rotate, pgengine, raw) for _ in range(6)]]
    assert all(r != "replay" for k, r in results if k == "err"), results
    assert _row(pgengine, emp).revoked_at is None, results
    assert any(k == "ok" for k, _ in results), results


# ── 2. CAS: ketma-ket rotation eski kredensialni iste'mol qiladi ────────────

def test_ROTATION_ZANJIRI_eski_kredensial_GRACE_dan_keyin_REPLAY(pgengine, emp, monkeypatch):
    _sid, raw1 = _new_session(pgengine, emp)
    kind, raw2 = _rotate(pgengine, raw1)
    assert kind == "ok"
    monkeypatch.setattr(settings, "refresh_grace_seconds", 0)
    assert _rotate(pgengine, raw1) == ("err", "replay")
    row = _row(pgengine, emp)
    assert row.revoked_at is not None
    #  Replay sessiyani o'ldirgani uchun YANGI kredensial ham ishlamaydi.
    assert _rotate(pgengine, raw2)[0] == "err"


# ── 3. REVOKE poygasi: revoke va refresh bir vaqtda ────────────────────────

def test_REVOKE_va_REFRESH_poygasi_FAIL_CLOSED(pgengine, emp):
    _sid, raw = _new_session(pgengine, emp)

    def _revoke():
        with Session(pgengine) as db:
            out = AS.revoke(db, _sid, employee_id=emp)
            db.commit()
            return out

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(_revoke)
        b = pool.submit(_rotate, pgengine, raw)
        revoked, rot = a.result(), b.result()
    assert revoked is True
    #  Sessiya OXIRIDA bekor bo'lgan bo'lishi SHART — poyga qanday tugashidan
    #  qat'i nazar (refresh oldin ulgursa ham, keyin ulgursa ham).
    assert _row(pgengine, emp).revoked_at is not None, rot
    #  Bekor qilingandan keyin HECH QANDAY kredensial ishlamaydi.
    if rot[0] == "ok":
        assert _rotate(pgengine, rot[1])[0] == "err"
    assert _rotate(pgengine, raw)[0] == "err"


# ── 4. KECHIKKAN revoke yangi sessiyaga tegmaydi (audit 4-band) ────────────

def test_KECHIKKAN_revoke_YANGI_sessiyaga_TEGMAYDI(pgengine, emp):
    old_sid, _old_raw = _new_session(pgengine, emp)
    new_sid, new_raw = _new_session(pgengine, emp)
    assert old_sid != new_sid
    with Session(pgengine) as db:
        assert AS.revoke(db, old_sid, employee_id=emp) is True
        db.commit()
    with Session(pgengine) as db:
        assert AS.active(db, new_sid) is not None, "yangi sessiya TIRIK qolishi kerak"
    assert _rotate(pgengine, new_raw)[0] == "ok"


# ── 5. MUDDAT va revoke_all ────────────────────────────────────────────────

def test_MUDDATI_OTGAN_sessiya_rotation_BERMAYDI(pgengine, emp):
    sid, raw = _new_session(pgengine, emp)
    with Session(pgengine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.id == uuid.UUID(sid)))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert _rotate(pgengine, raw) == ("err", "expired")


def test_REVOKE_ALL_hamma_sessiyani_yopadi(pgengine, emp):
    _s1, r1 = _new_session(pgengine, emp)
    _s2, r2 = _new_session(pgengine, emp)
    with Session(pgengine) as db:
        assert AS.revoke_all(db, emp) == 2
        db.commit()
    assert _rotate(pgengine, r1)[0] == "err"
    assert _rotate(pgengine, r2)[0] == "err"
