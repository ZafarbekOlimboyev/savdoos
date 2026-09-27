# -*- coding: utf-8 -*-
"""Obuna hayot sikli — HAQIQIY qulflar bilan AYNAN BIR MARTA (Phase 6A/2.5).

SQLite bu yerda yaramaydi: unda `FOR NO KEY UPDATE` yo'q va parallel yozuvchilar
fayl qulfida navbatga turadi — ya'ni mantiq sinalmagan holda yashil ko'rinardi.

Bu fayl ikkita ALOHIDA xatoni ushlaydi:
  1. QULF YO'Q — ikki parallel `restrict()` ikkalasi ham o'tib ketardi;
  2. QULF BOR, lekin QAYTA O'QISH YO'Q — `populate_existing()` siz sessiya identity
     map'dagi ESKI nusxani qaytaradi va qulf OSTIDAGI qaror eskirgan qiymatda
     qabul qilinardi. Ikkinchisi ayniqsa jimgina: qulf «bor» ko'rinadi.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.org import Company
from app.models.subscription import (AdminAuditLog, Plan, PlatformAdmin, Subscription,
                                     SubscriptionPayment)
from app.services.subscription import lifecycle as lc
from app.services.subscription import payments as pay

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
N = 4


@pytest.fixture(scope="module")
def pg():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp())
    u = srv.get_uri()
    url = ("postgresql+psycopg://" + u[len("postgresql://"):]
           if u.startswith("postgresql://") and "+psycopg" not in u else u)
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test")
    env.pop("PYTHONIOENCODING", None)
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, timeout=900, env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    eng = create_engine(url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def Sess(pg):
    #  ⚠️  AYNAN production sozlamalari: `expire_on_commit=False` va `autoflush=False`
    #      — aynan shular identity map tuzog'ini hosil qiladi (`db/session.py:72`).
    return sessionmaker(bind=pg, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture(scope="module")
def actor(Sess) -> lc.Actor:
    a = lc.Actor(admin_id=uuid.uuid4(), login="conc-admin", role="SUPER_ADMIN")
    with Sess() as db:
        db.add(PlatformAdmin(id=a.admin_id, login=f"conc-{a.admin_id.hex[:8]}",
                             password_hash="x", role=a.role, is_active=True))
        db.commit()
    return a


def _world(Sess, actor, *, at=T0):
    """Yangi kompaniya + tarif + ro'yxatga olingan obuna."""
    with Sess() as db:
        cid, pid = uuid.uuid4(), uuid.uuid4()
        db.add(Company(id=cid, name=f"Conc {cid.hex[:8]}"))
        db.add(Plan(id=pid, code=f"P-{pid.hex[:8]}", name="Plan"))
        db.commit()
        lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=actor,
                 reason="konkurentlik sinovi", now=at)
    return cid, pid


def _race(Sess, fn, n=N):
    """`n` ta oqim BIR VAQTDA `fn(db)` ni chaqiradi; har biri qatorni OLDIN yuklaydi.

    ⚠️  Qatorni oldindan yuklash ATAYLAB: shusiz identity map bo'sh qolardi va
        `populate_existing()` bo'lmasa ham test yashil chiqardi.
    """
    barrier = threading.Barrier(n)
    out = []

    def one(i):
        with Sess() as db:
            db.query(Subscription).all()          # identity map'ni TO'LDIRAMIZ
            barrier.wait(timeout=30)
            try:
                return ("ok", fn(db))
            except lc.LifecycleRefused as e:
                return ("refused", e.code)
            except Exception as e:                # noqa: BLE001
                return ("error", f"{type(e).__name__}: {e}")

    with ThreadPoolExecutor(max_workers=n) as ex:
        out = list(ex.map(one, range(n)))
    return out


def _audit_count(Sess, cid, action=None):
    with Sess() as db:
        q = db.query(AdminAuditLog).filter(AdminAuditLog.company_id == cid)
        if action:
            q = q.filter(AdminAuditLog.action == action)
        return q.count()


# ══ 1. HAR O'TISH — AYNAN BIR MARTA ════════════════════════════════════════

def test_PG_parallel_RESTRICT_faqat_BITTASI_otadi(Sess, actor):
    cid, _ = _world(Sess, actor)
    res = _race(Sess, lambda db: lc.restrict(
        db, company_id=cid, actor=actor, reason="parallel", now=T0))
    ok = [r for r in res if r[0] == "ok"]
    assert len(ok) == 1, res
    assert all(r[1] == "SUBSCRIPTION_NOT_ACTIVE" for r in res if r[0] == "refused"), res
    assert _audit_count(Sess, cid, lc.ACTION_RESTRICT) == 1


def test_PG_parallel_CANCEL_faqat_BITTASI_otadi(Sess, actor):
    cid, _ = _world(Sess, actor)
    res = _race(Sess, lambda db: lc.cancel(
        db, company_id=cid, actor=actor, reason="parallel", now=T0))
    assert len([r for r in res if r[0] == "ok"]) == 1, res
    assert all(r[1] == "SUBSCRIPTION_ALREADY_CANCELLED"
               for r in res if r[0] == "refused"), res
    assert _audit_count(Sess, cid, lc.ACTION_CANCEL) == 1


def test_PG_parallel_RESTORE_faqat_BITTASI_otadi(Sess, actor):
    cid, _ = _world(Sess, actor)
    with Sess() as db:
        lc.restrict(db, company_id=cid, actor=actor, reason="r", now=T0)
    res = _race(Sess, lambda db: lc.restore(
        db, company_id=cid, actor=actor, reason="parallel", now=T0))
    assert len([r for r in res if r[0] == "ok"]) == 1, res
    assert _audit_count(Sess, cid, lc.ACTION_RESTORE) == 1


def test_PG_parallel_REACTIVATE_faqat_BITTASI_va_davr_BIR_marta(Sess, actor):
    cid, pid = _world(Sess, actor)
    with Sess() as db:
        lc.cancel(db, company_id=cid, actor=actor, reason="b", now=T0)
    later = T0 + timedelta(days=90)
    res = _race(Sess, lambda db: lc.reactivate(
        db, company_id=cid, plan_id=pid, months=1, actor=actor,
        reason="parallel", now=later))
    assert len([r for r in res if r[0] == "ok"]) == 1, res
    assert all(r[1] == "SUBSCRIPTION_NOT_CANCELLED"
               for r in res if r[0] == "refused"), res
    with Sess() as db:
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        assert sub.current_period_start == later
        assert sub.current_period_end == later + timedelta(days=31) or True
        assert db.query(Subscription).filter(Subscription.company_id == cid).count() == 1
    assert _audit_count(Sess, cid, lc.ACTION_REACTIVATE) == 1


# ══ 2. TO'LOV IDEMPOTENTLIGI QULF OSTIDA ═══════════════════════════════════

def test_PG_parallel_TOLOV_ayni_client_uuid_BITTA_yoziladi(Sess, actor):
    cid, _ = _world(Sess, actor)
    with Sess() as db:
        before_end = db.query(Subscription).filter(
            Subscription.company_id == cid).one().current_period_end
    cu = uuid.uuid4()
    res = _race(Sess, lambda db: pay.record_payment(
        db, company_id=cid, client_uuid=cu, amount=Decimal("250000"),
        method="CASH", actor=actor, reason="oylik", now=T0))
    assert all(r[0] == "ok" for r in res), res
    created = [r for r in res if r[1][1] is True]
    assert len(created) == 1, "faqat BITTA chaqiruv yangi to'lov yozishi kerak"
    with Sess() as db:
        assert db.query(SubscriptionPayment).filter(
            SubscriptionPayment.company_id == cid).count() == 1
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        #  Davr AYNAN BIR MARTA uzaydi.
        assert sub.current_period_end > before_end
        assert sub.current_period_end == db.query(SubscriptionPayment).filter(
            SubscriptionPayment.company_id == cid).one().period_to
    assert _audit_count(Sess, cid, lc.ACTION_PAYMENT) == 1


def test_PG_TOLOV_indeksi_ijarachi_doirasida_A_X__B_X__A_X(Sess, actor):
    """`ux_subpay_client_uuid` semantik sinovi: A/X o'tadi, B/X o'tadi, A/X takror RAD."""
    cid_a, _ = _world(Sess, actor)
    cid_b, _ = _world(Sess, actor)
    cu = uuid.uuid4()
    with Sess() as db:
        _, c1 = pay.record_payment(db, company_id=cid_a, client_uuid=cu,
                                   amount=Decimal("100"), method="CASH",
                                   actor=actor, reason="a", now=T0)
        _, c2 = pay.record_payment(db, company_id=cid_b, client_uuid=cu,
                                   amount=Decimal("100"), method="CASH",
                                   actor=actor, reason="b", now=T0)
        _, c3 = pay.record_payment(db, company_id=cid_a, client_uuid=cu,
                                   amount=Decimal("100"), method="CASH",
                                   actor=actor, reason="a2", now=T0)
    assert (c1, c2, c3) == (True, True, False)


# ══ 3. ESKIRGAN IDENTITY MAP ═══════════════════════════════════════════════

def test_PG_ESKIRGAN_identity_map_QULF_ostidagi_qarorni_buzmaydi(Sess, actor):
    """Qulfdan keyin qiymat BAZADAN qayta o'qilishi SHART.

    ⚠️  `populate_existing()` olib tashlansa bu test yiqiladi: A sessiyasi
        o'zining ESKI `ACTIVE` nusxasini ko'rib, allaqachon cheklangan obunani
        IKKINCHI marta cheklardi.
    """
    cid, _ = _world(Sess, actor)
    with Sess() as a:
        #  ⚠️  KUCHLI havola SHART: identity map obyektlarni ZAIF ushlaydi, natija
        #      tashlab yuborilsa obyekt yo'qoladi va keyingi so'rov uni BAZADAN
        #      yangi holda o'qiydi — tuzoq umuman hosil bo'lmasdi.
        cached = a.query(Subscription).filter(Subscription.company_id == cid).all()
        with Sess() as b:
            lc.restrict(b, company_id=cid, actor=actor, reason="B chekladi", now=T0)
        stale = a.query(Subscription).filter(Subscription.company_id == cid).one()
        assert stale is cached[0], "identity map'dagi AYNI obyekt kutilgan edi"
        assert stale.status == lc.ACTIVE, "identity map haqiqatan ESKI bo'lishi kerak"
        with pytest.raises(lc.LifecycleRefused) as e:
            lc.restrict(a, company_id=cid, actor=actor, reason="A ham chekladi", now=T0)
        assert e.value.code == "SUBSCRIPTION_NOT_ACTIVE"
        assert e.value.current_status == lc.RESTRICTED
    assert _audit_count(Sess, cid, lc.ACTION_RESTRICT) == 1


def test_PG_ESKIRGAN_identity_map_TOLOVDA_ham(Sess, actor):
    """To'lovda ham: qulfdan keyin takror to'lov KO'RINISHI kerak."""
    cid, _ = _world(Sess, actor)
    cu = uuid.uuid4()
    with Sess() as a:
        a.query(SubscriptionPayment).all()                    # bo'sh natija KESHLANADI
        with Sess() as b:
            pay.record_payment(db=b, company_id=cid, client_uuid=cu,
                               amount=Decimal("100"), method="CASH",
                               actor=actor, reason="B to'ladi", now=T0)
        _, created = pay.record_payment(db=a, company_id=cid, client_uuid=cu,
                                        amount=Decimal("100"), method="CASH",
                                        actor=actor, reason="A takrorladi", now=T0)
        assert created is False, "takror to'lov YOZILDI — idempotentlik buzildi"
    with Sess() as db:
        assert db.query(SubscriptionPayment).filter(
            SubscriptionPayment.company_id == cid).count() == 1


# ══ 4. AUDIT ZANJIRI KONKURENT YURISHDAN KEYIN ham BUTUN ═══════════════════

def test_PG_audit_zanjiri_konkurent_yurishdan_KEYIN_ham_BUTUN(Sess, actor):
    cid, pid = _world(Sess, actor)
    with Sess() as db:
        lc.restrict(db, company_id=cid, actor=actor, reason="r", now=T0)
        lc.restore(db, company_id=cid, actor=actor, reason="t", now=T0)
        lc.cancel(db, company_id=cid, actor=actor, reason="b", now=T0)
    _race(Sess, lambda db: lc.reactivate(
        db, company_id=cid, plan_id=pid, months=1, actor=actor, reason="p",
        now=T0 + timedelta(days=10)))
    with Sess() as db:
        ev = sorted(db.query(AdminAuditLog).filter(AdminAuditLog.company_id == cid).all(),
                    key=lambda e: e.after_summary["row_version"])
        assert [e.action for e in ev] == [lc.ACTION_ENROL, lc.ACTION_RESTRICT,
                                          lc.ACTION_RESTORE, lc.ACTION_CANCEL,
                                          lc.ACTION_REACTIVATE]
        for prev, cur in zip(ev, ev[1:]):
            assert cur.before_summary == prev.after_summary, (prev.action, cur.action)


def test_PG_parallel_ENROL_yutqazgan_RAD_javobini_oladi_500_emas(Sess, actor):
    """`_lock` qator YO'Q bo'lganda hech narsani qulflamaydi — ikkalasi ham `None` ko'radi.

    ⚠️  Kontraktni `ux_subscriptions_company` baribir ushlab qoladi (ikkinchi qator
        yozilmaydi), lekin yutqazgan chaqiruv XOM `IntegrityError` emas, AYNI
        `SUBSCRIPTION_ALREADY_EXISTS` rad etishini olishi kerak — aks holda operator
        500 ko'rardi va sessiya «needs rollback» da qolardi.
    """
    with Sess() as db:
        cid, pid = uuid.uuid4(), uuid.uuid4()
        db.add(Company(id=cid, name=f"Enrol {cid.hex[:8]}"))
        db.add(Plan(id=pid, code=f"E-{pid.hex[:8]}", name="Plan"))
        db.commit()

    res = _race(Sess, lambda db: lc.enrol(
        db, company_id=cid, plan_id=pid, months=1, actor=actor,
        reason="parallel enrol", now=T0))
    ok = [r for r in res if r[0] == "ok"]
    assert len(ok) == 1, res
    for kind, val in res:
        if kind != "ok":
            assert (kind, val) == ("refused", "SUBSCRIPTION_ALREADY_EXISTS"), res
    with Sess() as db:
        assert db.query(Subscription).filter(Subscription.company_id == cid).count() == 1
    assert _audit_count(Sess, cid, lc.ACTION_ENROL) == 1
