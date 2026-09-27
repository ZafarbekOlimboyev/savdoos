# -*- coding: utf-8 -*-
"""Obuna hayot sikli — O'TISH MATRITSASI, AUDIT va TO'LOV IDEMPOTENTLIGI (Phase 6A/2.5).

Bu fayl mahsulot kontraktini qulflaydi:
  · kompaniyaga BITTA qator, umrbod — qayta obuna INSERT emas, `reactivate()`;
  · `CANCELLED -> ACTIVE` faqat `reactivate()` orqali, boshqa amal buni qila olmaydi;
  · `started_at` o'zgarmas, `cancelled_at`/`restricted_at` esa FAQAT joriy holat;
  · har o'tish AYNI tranzaksiyada bitta audit qatori yozadi va zanjir uzilmaydi;
  · to'lov takrori na ikkinchi to'lov, na ikkinchi uzaytirish, na ikkinchi audit beradi.

Konkurentlik (haqiqiy qulflar) alohida faylda: `tests/test_subscription_concurrency_pg.py`.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.org import Company
from app.models.subscription import (AdminAuditLog, Plan, Subscription,
                                     SubscriptionPayment)
from app.services.subscription import lifecycle as lc
from app.services.subscription import payments as pay
from app.services.subscription.state import (REASON_CANCELLED, REASON_MANUAL_RESTRICTION,
                                             REASON_PERIOD_ACTIVE,
                                             evaluate_subscription_access)

T0 = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)
ACTOR = lc.Actor(admin_id=uuid.uuid4(), login="vendor-admin", role="SUPER_ADMIN")


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


@pytest.fixture(autouse=True)
def _actor_row(client):
    """Aktor BAZADA bo'lsin: `admin_audit_log.actor_admin_id` -> `platform_admins.id` FK.

    ⚠️  FK SQLite'da ham majburlanadi (`PRAGMA foreign_keys`), ya'ni «auditni kim
        yozdi» savoli havolasiz qolmaydi.
    """
    from app.models.subscription import PlatformAdmin
    with _db() as db:
        if db.get(PlatformAdmin, ACTOR.admin_id) is None:
            db.add(PlatformAdmin(id=ACTOR.admin_id, login=f"va-{ACTOR.admin_id.hex[:10]}",
                                 password_hash="x", role=ACTOR.role, is_active=True))
            db.commit()


def _company(db, label="Test do'kon") -> uuid.UUID:
    c = Company(id=uuid.uuid4(), name=f"{label} {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return c.id


def _plan(db, code="START") -> uuid.UUID:
    p = Plan(id=uuid.uuid4(), code=f"{code}-{uuid.uuid4().hex[:6]}", name=code)
    db.add(p)
    db.commit()
    return p.id


def _world(db):
    return _company(db), _plan(db)


def _aw(dt):
    """SQLite naive qaytaradi — taqqoslashdan oldin UTC deb o'qiladi."""
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _events(db, company_id) -> list[AdminAuditLog]:
    """Audit zanjiri — `row_version` bo'yicha.

    ⚠️  `created_at` bo'yicha tartiblash YETARLI EMAS: bir soniyadagi ikki o'tish
        teng chiqadi. Har o'tish `row_version` ni oshiradi, ya'ni
        `after_summary["row_version"]` QAT'IY o'suvchi tartib kaliti.
    """
    rows = (db.query(AdminAuditLog)
            .filter(AdminAuditLog.company_id == company_id).all())
    return sorted(rows, key=lambda e: e.after_summary.get("row_version", 0))


def _enrolled(db, *, at=T0):
    cid, pid = _world(db)
    lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
             reason="pilot boshlandi", now=at)
    return cid, pid


# ══ 1. O'TISH MATRITSASI ════════════════════════════════════════════════════

def test_ENROL_yozuv_yoq_bolsa_ACTIVE_yaratadi(client):
    with _db() as db:
        cid, pid = _world(db)
        sub = lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                       reason="ro'yxatga olindi", now=T0)
        assert (sub.status, sub.started_at, sub.current_period_start) == (lc.ACTIVE, T0, T0)
        assert sub.cancelled_at is None and sub.restricted_at is None
        assert sub.deleted_at is None


def test_ENROL_IKKINCHI_marta_RAD_etiladi(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        with pytest.raises(lc.LifecycleRefused) as e:
            lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                     reason="takror", now=T0)
        assert e.value.code == "SUBSCRIPTION_ALREADY_EXISTS"
        assert db.query(Subscription).filter(Subscription.company_id == cid).count() == 1


@pytest.mark.parametrize("op", ["restrict", "restore", "cancel", "reactivate"])
def test_YOZUV_YOQ_bolsa_hamma_amal_RAD(client, op):
    with _db() as db:
        cid, pid = _world(db)
        kw = {"company_id": cid, "actor": ACTOR, "reason": "x", "now": T0}
        if op == "reactivate":
            kw |= {"plan_id": pid, "months": 1}
        with pytest.raises(lc.LifecycleRefused) as e:
            getattr(lc, op)(db, **kw)
        assert e.value.code == "SUBSCRIPTION_NOT_FOUND"


def test_RESTRICT_va_RESTORE_aylanasi(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        s = lc.restrict(db, company_id=cid, actor=ACTOR, reason="qarzdorlik", now=T0)
        assert (s.status, s.restricted_at) == (lc.RESTRICTED, T0)
        s = lc.restore(db, company_id=cid, actor=ACTOR, reason="to'ladi", now=T0)
        assert (s.status, s.restricted_at) == (lc.ACTIVE, None)


def test_RESTRICT_faqat_ACTIVE_dan(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="1", now=T0)
        with pytest.raises(lc.LifecycleRefused) as e:
            lc.restrict(db, company_id=cid, actor=ACTOR, reason="2", now=T0)
        assert e.value.code == "SUBSCRIPTION_NOT_ACTIVE"
        assert e.value.current_status == lc.RESTRICTED


def test_RESTORE_CANCELLED_qatorni_RAD_etadi_IKKINCHI_yol_YOQ(client):
    """⚠️  `state.py` CANCELLED ni operatorga RESTRICTED ko'rsatadi — `restore()`
    SAQLANGAN qiymatga qarab uni rad etadi, aks holda bu ikkinchi tiriltirish yo'li bo'lardi."""
    with _db() as db:
        cid, _ = _enrolled(db)
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="ketdi", now=T0)
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        assert evaluate_subscription_access(sub, T0).effective_status == lc.RESTRICTED
        with pytest.raises(lc.LifecycleRefused) as e:
            lc.restore(db, company_id=cid, actor=ACTOR, reason="tiklamoqchi", now=T0)
        assert e.value.code == "SUBSCRIPTION_NOT_RESTRICTED"
        db.refresh(sub)
        assert sub.status == lc.CANCELLED


def test_CANCEL_ACTIVE_va_RESTRICTED_dan_mumkin_TAKRORI_RAD(client):
    with _db() as db:
        for pre in (None, "restrict"):
            cid, _ = _enrolled(db)
            if pre:
                lc.restrict(db, company_id=cid, actor=ACTOR, reason="r", now=T0)
            s = lc.cancel(db, company_id=cid, actor=ACTOR, reason="bekor", now=T0)
            assert (s.status, s.cancelled_at, s.restricted_at) == (lc.CANCELLED, T0, None)
            with pytest.raises(lc.LifecycleRefused) as e:
                lc.cancel(db, company_id=cid, actor=ACTOR, reason="yana", now=T0)
            assert e.value.code == "SUBSCRIPTION_ALREADY_CANCELLED"


def test_REACTIVATE_faqat_CANCELLED_dan(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        with pytest.raises(lc.LifecycleRefused) as e:
            lc.reactivate(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                          reason="erta", now=T0)
        assert e.value.code == "SUBSCRIPTION_NOT_CANCELLED"


def test_REACTIVATE_YANGI_qator_YARATMAYDI_va_davr_HOZIRDAN(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        first = db.query(Subscription).filter(Subscription.company_id == cid).one()
        row_id, started = first.id, first.started_at
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="bekor", now=T0)
        later = T0 + timedelta(days=200)
        s = lc.reactivate(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                          reason="qaytdi", now=later)
        assert db.query(Subscription).filter(Subscription.company_id == cid).count() == 1
        assert s.id == row_id, "YANGI qator yaratilgan — kontrakt buzildi"
        assert s.started_at == started, "`started_at` O'ZGARMASLIGI kerak"
        assert s.current_period_start == later, "yangi davr REAKTIVATSIYA vaqtidan"
        assert s.current_period_end > later
        assert s.cancelled_at is None and s.status == lc.ACTIVE


def test_REACTIVATE_eski_davrni_UZAYTIRMAYDI(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        old_end = db.query(Subscription).filter(Subscription.company_id == cid).one().current_period_end
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="b", now=T0)
        later = T0 + timedelta(days=400)
        s = lc.reactivate(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                          reason="q", now=later)
        assert s.current_period_start == later
        assert s.current_period_end != old_end + timedelta(days=31)


def test_QAYTA_bekor_qilinsa_cancelled_at_OXIRGISINI_korsatadi(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="1", now=T0)
        t2 = T0 + timedelta(days=100)
        lc.reactivate(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                      reason="q", now=t2)
        t3 = t2 + timedelta(days=10)
        s = lc.cancel(db, company_id=cid, actor=ACTOR, reason="2", now=t3)
        assert s.cancelled_at == t3, "`cancelled_at` — JORIY holat, tarix emas"


# ══ 2. SXEMA INVARIANTLARI (CHECK'lar SQLite'da ham ishlaydi) ═══════════════

def test_CHECK_deleted_at_YOZIB_BOLMAYDI(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        sub.deleted_at = T0
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_CHECK_GRACE_saqlab_BOLMAYDI(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        sub.status = "GRACE"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


@pytest.mark.parametrize("field,status", [("restricted_at", lc.RESTRICTED),
                                          ("cancelled_at", lc.CANCELLED)])
def test_CHECK_bikondisional_zid_holatni_RAD(client, field, status):
    with _db() as db:
        cid, _ = _enrolled(db)
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        sub.status = status                      # vaqt tamg'asi BERILMAYDI
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# ══ 3. AUDIT ═══════════════════════════════════════════════════════════════

def test_AUDIT_har_otish_uchun_BITTA_qator_va_MAJBURIY_maydonlar(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="r", now=T0)
        lc.restore(db, company_id=cid, actor=ACTOR, reason="t", now=T0)
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="b", now=T0)
        lc.reactivate(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                      reason="q", now=T0 + timedelta(days=1))
        ev = _events(db, cid)
        assert [e.action for e in ev] == [lc.ACTION_ENROL, lc.ACTION_RESTRICT,
                                          lc.ACTION_RESTORE, lc.ACTION_CANCEL,
                                          lc.ACTION_REACTIVATE]
        for e in ev:
            assert e.actor_admin_id == ACTOR.admin_id
            assert (e.actor_login, e.actor_role) == (ACTOR.login, ACTOR.role)
            assert e.target_type == lc.TARGET_TYPE and e.target_id is not None
            assert e.reason and e.before_summary and e.after_summary
            assert e.created_at is not None


def test_AUDIT_zanjiri_UZILMAYDI_before_N_eq_after_N_minus_1(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="r", now=T0)
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="b", now=T0)
        lc.reactivate(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                      reason="q", now=T0 + timedelta(days=5))
        ev = _events(db, cid)
        for prev, cur in zip(ev, ev[1:]):
            assert cur.before_summary == prev.after_summary, (prev.action, cur.action)


def test_AUDIT_bekor_qilish_FAKTI_qatordan_yoqolsa_ham_auditda_QOLADI(client):
    with _db() as db:
        cid, pid = _enrolled(db)
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="bekor qilindi", now=T0)
        lc.reactivate(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                      reason="qaytdi", now=T0 + timedelta(days=30))
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        assert sub.cancelled_at is None, "joriy holatda tozalangan bo'lishi kerak"
        ev = [e for e in _events(db, cid) if e.action == lc.ACTION_CANCEL]
        assert len(ev) == 1 and ev[0].after_summary["cancelled_at"] == T0.isoformat()
        assert ev[0].reason == "bekor qilindi"


def test_AUDIT_snapshot_JSON_ga_seriyalanadi(client):
    """⚠️  Engine `json_serializer`siz — xom `datetime` JSONB ga yozilsa TypeError."""
    with _db() as db:
        cid, _ = _enrolled(db)
        ev = _events(db, cid)[0]
        json.dumps(ev.before_summary)
        json.dumps(ev.after_summary)
        assert isinstance(ev.after_summary["started_at"], str)
        assert isinstance(ev.after_summary["plan_id"], str)
        assert ev.before_summary == {"exists": False}


def test_AUDIT_sababsiz_amal_RAD(client):
    with _db() as db:
        cid, pid = _world(db)
        with pytest.raises(lc.LifecycleRefused) as e:
            lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                     reason="   ", now=T0)
        assert e.value.code == "SUBSCRIPTION_REASON_REQUIRED"


# ══ 4. TO'LOV / YANGILASH ═══════════════════════════════════════════════════

def test_TOLOV_davrni_uzaytiradi_va_period_from_to_yozadi(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        old = db.query(Subscription).filter(Subscription.company_id == cid).one().current_period_end
        p, created = pay.record_payment(db, company_id=cid, client_uuid=uuid.uuid4(),
                                        amount=Decimal("120000"), method="CASH",
                                        actor=ACTOR, reason="oylik", now=T0)
        assert created is True
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        assert sub.current_period_end > old
        assert (_aw(p.period_from), _aw(p.period_to)) == (_aw(old), _aw(sub.current_period_end))


def test_TOLOV_TAKRORI_ikkinchi_marta_HECH_NARSA_qilmaydi(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        cu = uuid.uuid4()
        p1, c1 = pay.record_payment(db, company_id=cid, client_uuid=cu,
                                    amount=Decimal("100"), method="CASH",
                                    actor=ACTOR, reason="oylik", now=T0)
        end1 = db.query(Subscription).filter(Subscription.company_id == cid).one().current_period_end
        n_audit = len(_events(db, cid))
        p2, c2 = pay.record_payment(db, company_id=cid, client_uuid=cu,
                                    amount=Decimal("100"), method="CASH",
                                    actor=ACTOR, reason="oylik", now=T0)
        assert (c1, c2) == (True, False)
        assert p1.id == p2.id
        assert db.query(SubscriptionPayment).filter(
            SubscriptionPayment.company_id == cid).count() == 1
        assert db.query(Subscription).filter(
            Subscription.company_id == cid).one().current_period_end == end1
        assert len(_events(db, cid)) == n_audit


def test_TOLOV_idempotentligi_IJARACHI_doirasida(client):
    """Ayni `client_uuid` BOSHQA kompaniyada — bu ALOHIDA to'lov."""
    with _db() as db:
        cid_a, _ = _enrolled(db)
        cid_b, _ = _enrolled(db)
        cu = uuid.uuid4()
        _, ca = pay.record_payment(db, company_id=cid_a, client_uuid=cu,
                                   amount=Decimal("100"), method="CASH",
                                   actor=ACTOR, reason="a", now=T0)
        _, cb = pay.record_payment(db, company_id=cid_b, client_uuid=cu,
                                   amount=Decimal("100"), method="CASH",
                                   actor=ACTOR, reason="b", now=T0)
        assert (ca, cb) == (True, True), "boshqa ijarachi to'silmasligi kerak"


def test_TOLOV_CANCELLED_obunani_TIRILTIRMAYDI(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="b", now=T0)
        with pytest.raises(lc.LifecycleRefused) as e:
            pay.record_payment(db, company_id=cid, client_uuid=uuid.uuid4(),
                               amount=Decimal("100"), method="CASH",
                               actor=ACTOR, reason="to'lov", now=T0)
        assert e.value.code == "SUBSCRIPTION_CANCELLED"
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        assert sub.status == lc.CANCELLED


def test_TOLOV_QOLDA_CHEKLOVNI_yechmaydi(client):
    """Davr uzayadi, lekin intizomiy qaror pul bilan bekor bo'lmaydi."""
    with _db() as db:
        cid, _ = _enrolled(db)
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="qarz", now=T0)
        pay.record_payment(db, company_id=cid, client_uuid=uuid.uuid4(),
                           amount=Decimal("100"), method="CASH",
                           actor=ACTOR, reason="to'ladi", now=T0)
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        assert (sub.status, _aw(sub.restricted_at)) == (lc.RESTRICTED, T0)
        a = evaluate_subscription_access(sub, T0)
        assert (a.effective_status, a.reason) == (lc.RESTRICTED, REASON_MANUAL_RESTRICTION)
        assert a.writes_allowed is False


# ══ 5. GRANDFATHERING ══════════════════════════════════════════════════════

def test_GRANDFATHERED_kompaniya_yozuvsiz_OCHIQ_qoladi(client):
    with _db() as db:
        cid = _company(db)
        assert db.query(Subscription).filter(Subscription.company_id == cid).count() == 0
        a = evaluate_subscription_access(None, T0)
        assert (a.managed, a.writes_allowed) == (False, True)
        assert a.effective_status is None


def test_BEKOR_qilingan_obuna_qatori_OCHIRILMAYDI(client):
    """Grandfathered holatga QAYTISH uchun qator o'chirilmaydi — `deleted_at` NULL qoladi."""
    with _db() as db:
        cid, _ = _enrolled(db)
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="b", now=T0)
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        assert sub.deleted_at is None
        a = evaluate_subscription_access(sub, T0)
        assert (a.managed, a.reason) == (True, REASON_CANCELLED)
        assert a.writes_allowed is False


# ══ 6. RESTRICTED KONTRAKTI — SERVER TOMONIDA ══════════════════════════════
#
# ⚠️  Qaror HAR SO'ROVDA bazadagi qatordan qayta hisoblanadi (`state.py`), ya'ni
#     fon vazifasi kechiksa ham muddati o'tgan ijarachi yoza olmaydi. UI da
#     tugmani yashirish MAJBURLASH EMAS — bu testlar server qarorini qulflaydi.

from app.services.subscription import policy as P  # noqa: E402

#  `RESTRICTED` da OCHIQ qoladigan toifalar: operator to'lash uchun ham kira
#  olishi va ma'lumotini ko'chirib olishi kerak.
_OCHIQ = (P.AUTH, P.BILLING, P.ADMIN, P.READ)
#  YAGONA istisno: ochiq smenani YOPISH — u yangi biznes hodisasi emas, ochiq
#  hodisani yakunlaydi. To'silsa kassada ochiq smena qolib, ertasi kuni yangi
#  smena ham ochilmasdi.
_XAVFSIZ = (P.SHIFT_CLOSE,)


def _access(db, company_id):
    """AYNAN so'rov yo'lidagidek: qatorni bazadan o'qib, qarorni qayta hisoblaydi."""
    sub = (db.query(Subscription)
           .filter(Subscription.company_id == company_id).one_or_none())
    return evaluate_subscription_access(sub, datetime.now(timezone.utc))


def test_RESTRICTED_yangi_biznes_yozuvini_TOSADI(client):
    with _db() as db:
        cid, _ = _enrolled(db, at=datetime.now(timezone.utc))
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="qarz")
        a = _access(db, cid)
        assert (a.effective_status, a.writes_allowed) == (lc.RESTRICTED, False)
        for cat in (P.SALE, P.RECEIVING, P.INVENTORY_COUNT, P.WRITE_OFF, P.TRANSFER,
                    P.CASH_OP, P.SHIFT_OPEN, P.CUSTOMER_DEBT, P.PRODUCT, P.BRANCH):
            assert P.is_allowed(cat, a.effective_status, managed=a.managed) is False, cat


def test_RESTRICTED_oqish_billing_va_SMENA_YOPISH_ochiq(client):
    with _db() as db:
        cid, _ = _enrolled(db, at=datetime.now(timezone.utc))
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="qarz")
        a = _access(db, cid)
        for cat in _OCHIQ + _XAVFSIZ:
            assert P.is_allowed(cat, a.effective_status, managed=a.managed) is True, cat


def test_RESTRICTED_smena_OCHISH_bilan_YOPISH_farqlanadi(client):
    """Ochiq smenani yopish MUMKIN, yangisini ochish MUMKIN EMAS."""
    with _db() as db:
        cid, _ = _enrolled(db, at=datetime.now(timezone.utc))
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="q")
        a = _access(db, cid)
        assert P.is_allowed(P.SHIFT_CLOSE, a.effective_status, managed=a.managed) is True
        assert P.is_allowed(P.SHIFT_OPEN, a.effective_status, managed=a.managed) is False


def test_ACTIVE_hamma_toifa_ochiq_RESTORE_dan_KEYIN_qaytadi(client):
    """Qaror KESHLANMAYDI: qator o'zgarsa, keyingi hisob DARHOL boshqacha."""
    with _db() as db:
        cid, _ = _enrolled(db, at=datetime.now(timezone.utc))
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="q")
        assert _access(db, cid).writes_allowed is False
        lc.restore(db, company_id=cid, actor=ACTOR, reason="to'ladi")
        a = _access(db, cid)
        assert (a.effective_status, a.writes_allowed) == (lc.ACTIVE, True)
        for cat in sorted(P.ALL_CATEGORIES):
            assert P.is_allowed(cat, a.effective_status, managed=a.managed) is True, cat


def test_CANCELLED_ham_yangi_yozuvni_TOSADI(client):
    with _db() as db:
        cid, _ = _enrolled(db, at=datetime.now(timezone.utc))
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="ketdi")
        a = _access(db, cid)
        assert (a.effective_status, a.reason) == (lc.RESTRICTED, REASON_CANCELLED)
        assert P.is_allowed(P.SALE, a.effective_status, managed=a.managed) is False
        assert P.is_allowed(P.SHIFT_CLOSE, a.effective_status, managed=a.managed) is True


def test_GRANDFATHERED_kompaniyada_hamma_toifa_ochiq(client):
    with _db() as db:
        cid = _company(db)
        a = _access(db, cid)
        assert a.managed is False
        for cat in sorted(P.ALL_CATEGORIES):
            assert P.is_allowed(cat, a.effective_status, managed=a.managed) is True, cat


# ══ 7. SQLITE / run.bat YO'LI ══════════════════════════════════════════════

def test_SQLITE_boot_CHECKlarni_yaratadi_va_MAJBURLAYDI(client):
    """Mahalliy SQLite bazada ham cheklovlar HAQIQATAN ishlaydi.

    ⚠️  PG-ga xos migratsiya (`_ensure_lot_checks`, `_ensure_subpay_idempotency_index`)
        SQLite'da o'tkazib yuboriladi — lekin `create_all` CHECK'larni `CREATE TABLE`
        ichida chiqaradi, ya'ni mahalliy baza himoyasiz qolmaydi.
    """
    import sqlalchemy as sa

    from app.db.session import engine
    assert engine.dialect.name == "sqlite", "bu test mahalliy SQLite yo'li uchun"
    sql = sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n")
    with engine.connect() as c:
        subs = c.execute(sql, {"n": "subscriptions"}).scalar() or ""
        audit = c.execute(sql, {"n": "admin_audit_log"}).scalar() or ""
    for name in ("ck_sub_deleted_never", "ck_sub_restricted_iff",
                 "ck_sub_cancelled_iff", "ck_sub_status_persistable"):
        assert name in subs, name
    assert "ck_audit_sub_fields" in audit
    #  Majburlash HAQIQIY ekani yuqoridagi `test_CHECK_*` testlarida sinaladi.


def test_SQLITE_indeks_KOMPOZIT_yaratiladi(client):
    import sqlalchemy as sa

    from app.db.session import engine
    with engine.connect() as c:
        ddl = c.execute(sa.text(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='ux_subpay_client_uuid'")).scalar() or ""
    assert "company_id" in ddl and "client_uuid" in ddl, ddl


# ══ 8. GRACE OYNASI — TARIFDAN, kodda qotib qolmagan ═══════════════════════
#
# ⚠️  Ilgari uchala yozuvchi ham `grace_end(..., 0)` uzatardi: `grace_until`
#     `current_period_end` ga TENG bo'lib qolar, `state.py` dagi GRACE tarmog'i esa
#     HECH QACHON ishlamasdi. Ya'ni ijarachi davr chegarasida ogohlantirishsiz
#     to'g'ridan-to'g'ri bloklanardi — `policy.py` aynan buni taqiqlaydi.

def test_GRACE_oynasi_TARIFDAN_olinadi(client):
    with _db() as db:
        cid, pid = _world(db)
        plan = db.get(Plan, pid)
        assert plan.grace_days and plan.grace_days > 0, "tarif standarti kutilgan edi"
        sub = lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                       reason="grace sinovi", now=T0)
        assert _aw(sub.grace_until) > _aw(sub.current_period_end), \
            "grace oynasi NOLGA teng — GRACE tarmog'i o'lik qoladi"
        assert (_aw(sub.grace_until) - _aw(sub.current_period_end)).days == plan.grace_days


def test_GRACE_oynasi_ICHIDA_yozuv_OCHIQ_va_OGOHLANTIRISH_bor(client):
    from app.services.subscription.state import REASON_GRACE_PERIOD
    with _db() as db:
        cid, pid = _world(db)
        sub = lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                       reason="g", now=T0)
        ichida = _aw(sub.current_period_end) + timedelta(hours=1)
        assert ichida < _aw(sub.grace_until)
        a = evaluate_subscription_access(sub, ichida)
        assert (a.effective_status, a.reason) == ("GRACE", REASON_GRACE_PERIOD)
        assert (a.writes_allowed, a.warn) == (True, True)


def test_GRACE_tugagach_yozuv_YOPILADI(client):
    from app.services.subscription.state import REASON_EXPIRED
    with _db() as db:
        cid, pid = _world(db)
        sub = lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                       reason="g", now=T0)
        keyin = _aw(sub.grace_until) + timedelta(seconds=1)
        a = evaluate_subscription_access(sub, keyin)
        assert (a.effective_status, a.reason) == (lc.RESTRICTED, REASON_EXPIRED)
        assert a.writes_allowed is False


def test_TOLOV_ham_GRACE_oynasini_TARIFDAN_yozadi(client):
    with _db() as db:
        cid, pid = _world(db)
        lc.enrol(db, company_id=cid, plan_id=pid, months=1, actor=ACTOR,
                 reason="g", now=T0)
        pay.record_payment(db, company_id=cid, client_uuid=uuid.uuid4(),
                           amount=Decimal("100"), method="CASH",
                           actor=ACTOR, reason="oylik", now=T0)
        sub = db.query(Subscription).filter(Subscription.company_id == cid).one()
        plan = db.get(Plan, pid)
        assert (_aw(sub.grace_until) - _aw(sub.current_period_end)).days == plan.grace_days


# ══ 9. RAD ETISH TRANZAKSIYANI YOPADI ══════════════════════════════════════
#
# ⚠️  Rad etish yo'li ilgari qulfni USHLAB chiqardi — na commit, na rollback.
#     Chaqiruvchi uchun bu shuni anglatardi: muvaffaqiyatda sessiyaning bog'liq
#     bo'lmagan kutilayotgan ishi SAQLANARDI, rad etishda esa YO'QOLARDI.

def test_RAD_etilgan_amaldan_KEYIN_sessiya_ISHLAYDI(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        lc.restrict(db, company_id=cid, actor=ACTOR, reason="r", now=T0)
        with pytest.raises(lc.LifecycleRefused):
            lc.restrict(db, company_id=cid, actor=ACTOR, reason="takror", now=T0)
        #  Sessiya «needs rollback» holatida qolmagan bo'lsin.
        assert db.query(Subscription).filter(Subscription.company_id == cid).count() == 1
        lc.restore(db, company_id=cid, actor=ACTOR, reason="t", now=T0)


def test_RAD_etilgan_TOLOV_takroridan_KEYIN_ham_sessiya_ISHLAYDI(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        cu = uuid.uuid4()
        pay.record_payment(db, company_id=cid, client_uuid=cu, amount=Decimal("100"),
                           method="CASH", actor=ACTOR, reason="1", now=T0)
        _, created = pay.record_payment(db, company_id=cid, client_uuid=cu,
                                        amount=Decimal("100"), method="CASH",
                                        actor=ACTOR, reason="2", now=T0)
        assert created is False
        assert db.query(SubscriptionPayment).filter(
            SubscriptionPayment.company_id == cid).count() == 1
        lc.cancel(db, company_id=cid, actor=ACTOR, reason="b", now=T0)
