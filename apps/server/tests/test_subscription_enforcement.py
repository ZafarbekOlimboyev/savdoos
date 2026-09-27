# -*- coding: utf-8 -*-
"""Obuna majburlashi MARSHRUT chegarasida + QAMROV qo'riqchisi (Phase 6A/2.5).

⚠️  UI da tugmani yashirish majburlash EMAS. Bu yerda HAQIQIY HTTP so'rov yuboriladi
    va server javobi tekshiriladi.

QAMROV FAIL-CLOSED
==================
Yangi endpoint qo'shilib tasniflanmasa, u majburlashdan JIMGINA sirg'alib o'tmaydi:
  · `test_QAMROV_*` tasniflanmagan marshrutni QIZIL qiladi;
  · darvozaning o'zi ham reestrda yo'q O'ZGARTIRUVCHI marshrutni TO'SADI.
Ya'ni qo'riqchi ham, ish vaqti ham bir xil tomonga yiqiladi.

TESTLAR NIMANI DA'VO QILADI
===========================
⚠️  «Ruxsat» testlari 200 ni TALAB QILMAYDI — marshrut o'z sababi bilan 400/422
    berishi mumkin. Ular faqat OBUNA DARVOZASI to'smaganini tekshiradi
    (`X-Error-Code != SUBSCRIPTION_RESTRICTED`). Shunda test endpoint'ning
    biznes qoidalari o'zgarganda sinmaydi, lekin darvoza teshilsa — sinadi.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.subscription_gate import MUTATING, classify_key
from app.core.subscription_routes import (ALL_CLASSES, ALLOW_ACCOUNT_BILLING,
                                          ALLOW_EXPORT, ALLOW_READ, ALLOW_REPORT,
                                          ALLOW_SHIFT_CLOSE, BLOCK_BUSINESS_WRITE,
                                          ERROR_CODE, NO_TENANT_CONTEXT,
                                          OUT_OF_SCOPE_SYSTEM,
                                          SUBSCRIPTION_ROUTE_ACTIONS)
from app.core.security import create_access_token
from app.models.org import Company
from app.models.subscription import Plan, PlatformAdmin
from app.services.subscription import lifecycle as lc
from tests.test_mobile_permission_matrix import _routes

PFX = "/api/v1"
ACTOR = lc.Actor(admin_id=uuid.uuid4(), login="enf-admin", role="SUPER_ADMIN")


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


# ══ 1. QAMROV QO'RIQCHISI ══════════════════════════════════════════════════

def test_QAMROV_har_bir_marshrut_ANIQ_tasniflangan(client):
    """Tasniflanmagan marshrut — TEST QIZIL. Bu qoidaning butun mohiyati."""
    live = {(m, p) for m, p in _routes()}
    yoq = sorted(live - set(SUBSCRIPTION_ROUTE_ACTIONS) - NO_TENANT_CONTEXT)
    assert not yoq, (
        "quyidagi marshrutlar obuna tasnifisiz qoldi — "
        "`app/core/subscription_routes.py` ga yozing", yoq)


def test_QAMROV_reestrda_ESKIRGAN_yozuv_YOQ(client):
    live = {(m, p) for m, p in _routes()}
    eskirgan = sorted(set(SUBSCRIPTION_ROUTE_ACTIONS) - live)
    assert not eskirgan, ("reestrda mavjud bo'lmagan marshrut bor", eskirgan)


def test_QAMROV_sinflar_MA_LUM(client):
    noma = {c for c in SUBSCRIPTION_ROUTE_ACTIONS.values()} - ALL_CLASSES
    assert not noma, noma


def test_QAMROV_ozgartiruvchi_marshrut_STANDART_TOSILADI(client):
    """O'zgartiruvchi marshrut ALLOW bo'lsa — ANIQ istisno bo'lishi shart."""
    ruxsat_etilgan_yozuvlar = {ALLOW_ACCOUNT_BILLING, ALLOW_SHIFT_CLOSE,
                               OUT_OF_SCOPE_SYSTEM}
    shubhali = sorted((m, p, c) for (m, p), c in SUBSCRIPTION_ROUTE_ACTIONS.items()
                      if m in MUTATING and c not in ruxsat_etilgan_yozuvlar
                      and c != BLOCK_BUSINESS_WRITE)
    #  Yozmaydigan POST'lar (diagnostika/oldindan ko'rish) — ALLOW_READ bo'lishi mumkin,
    #  lekin ular ATAYLAB sanab o'tilgan bo'lsin, tasodifan emas.
    kutilgan_yozmaydiganlar = {
        ("POST", "/scales/test"), ("POST", "/devices/test"),
        ("POST", "/products/import/preview"), ("POST", "/catalog/v2/reset/dry-run"),
    }
    qolgan = [t for t in shubhali if (t[0], t[1]) not in kutilgan_yozmaydiganlar]
    assert not qolgan, ("o'zgartiruvchi marshrut ALLOW qilingan — sababini "
                        "`kutilgan_yozmaydiganlar` ga yozing yoki BLOCK qiling", qolgan)


def test_QAMROV_smena_yopish_istisnosi_AYNAN_BITTA(client):
    """Istisno umumiy naqd-yozuv bypass'iga aylanmasin."""
    istisno = sorted(k for k, v in SUBSCRIPTION_ROUTE_ACTIONS.items()
                     if v == ALLOW_SHIFT_CLOSE)
    assert istisno == [("POST", "/shifts/{shift_id}/close")], istisno
    #  Eng xavfli o'xshash: ochiq smenaga IXTIYORIY naqd harakat yozadi.
    assert SUBSCRIPTION_ROUTE_ACTIONS[("POST", "/shifts/{shift_id}/cash")] \
        == BLOCK_BUSINESS_WRITE
    assert SUBSCRIPTION_ROUTE_ACTIONS[("POST", "/cash/ops")] == BLOCK_BUSINESS_WRITE
    assert SUBSCRIPTION_ROUTE_ACTIONS[("POST", "/shifts/open")] == BLOCK_BUSINESS_WRITE


def test_QAMROV_TASNIFLANMAGAN_marshrut_darvozada_TOSILADI(client):
    """Ish vaqti ham fail-closed: reestrda yo'q o'zgartiruvchi marshrut BLOCK."""
    yangi = ("POST", "/yangi/endpoint")
    assert yangi not in SUBSCRIPTION_ROUTE_ACTIONS
    assert classify_key(yangi, "POST") == BLOCK_BUSINESS_WRITE
    assert classify_key(("DELETE", "/yangi/endpoint"), "DELETE") == BLOCK_BUSINESS_WRITE
    assert classify_key(("PATCH", "/yangi/endpoint"), "PATCH") == BLOCK_BUSINESS_WRITE
    assert classify_key(("GET", "/yangi/endpoint"), "GET") == ALLOW_READ


def test_QAMROV_eksport_sinfi_hozircha_BOSH(client):
    """Hech bir marshrut fayl eksport qilmaydi. `.xls` qo'shilsa — SHU YERGA."""
    assert not [k for k, v in SUBSCRIPTION_ROUTE_ACTIONS.items() if v == ALLOW_EXPORT]


# ══ 2. HAQIQIY SO'ROVLAR ═══════════════════════════════════════════════════

@pytest.fixture(scope="module")
def tenant(client):
    """Alohida ijarachi + `ega` roli bilan xodim (ruxsat darvozalari o'tsin)."""
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    with _db() as db:
        cid, pid = uuid.uuid4(), uuid.uuid4()
        db.add(Company(id=cid, name=f"Enf {cid.hex[:8]}"))
        db.add(Plan(id=pid, code=f"ENF-{pid.hex[:8]}", name="Enf"))
        db.add(PlatformAdmin(id=ACTOR.admin_id, login=f"enf-{ACTOR.admin_id.hex[:8]}",
                             password_hash="x", role=ACTOR.role, is_active=True))
        #  ⚠️  Ota qatorlar OLDIN yozilsin: `Employee.company_id` da ORM
        #      munosabati yo'q (xom `ForeignKey`), ya'ni flush tartibi
        #      kafolatlanmagan va SQLite'da FK majburlanadi.
        db.flush()
        role = db.query(Role).filter(Role.code == "ega").one()
        eid = uuid.uuid4()
        db.add(Employee(id=eid, company_id=cid, role_id=role.id, full_name="Enf ega",
                        phone=f"+9987{uuid.uuid4().int % 10**7:07d}",
                        status=EmployeeStatus.active, sec_epoch=0))
        db.commit()
    tok = create_access_token(str(eid), {"role": "ega", "company_id": str(cid), "sv": 0})
    return {"cid": cid, "pid": pid, "eid": eid,
            "H": {"Authorization": f"Bearer {tok}"}}


def _set_state(tenant, state, *, now=None):
    """Ijarachini kerakli holatga keltiradi (`None` = grandfathered)."""
    at = now or datetime.now(timezone.utc)
    with _db() as db:
        from app.models.subscription import Subscription
        sub = db.query(Subscription).filter(
            Subscription.company_id == tenant["cid"]).one_or_none()
        if state is None:
            assert sub is None, "grandfathered holat uchun yozuv bo'lmasligi kerak"
            return
        if sub is None:
            lc.enrol(db, company_id=tenant["cid"], plan_id=tenant["pid"], months=1,
                     actor=ACTOR, reason="majburlash sinovi", now=at)
            sub = db.query(Subscription).filter(
                Subscription.company_id == tenant["cid"]).one()
        if state == "RESTRICTED" and sub.status != lc.RESTRICTED:
            lc.restrict(db, company_id=tenant["cid"], actor=ACTOR, reason="sinov", now=at)
        elif state == "ACTIVE" and sub.status != lc.ACTIVE:
            lc.restore(db, company_id=tenant["cid"], actor=ACTOR, reason="sinov", now=at)


def _blocked(r) -> bool:
    return r.status_code == 403 and r.headers.get("X-Error-Code") == ERROR_CODE


#  Har bandi uchun VAKIL marshrut. Tanaga ataylab e'tibor berilmaydi: darvoza
#  endpoint mantig'idan OLDIN ishlaydi, ya'ni 422 ham «to'silmadi» degani.
_OQISH = [("GET", "/products"), ("GET", "/customers"), ("GET", "/sales")]
_HISOBOT = [("GET", "/reports/summary"), ("GET", "/reports/pnl"),
            ("GET", "/inventory/overview")]
_HISOB = [("POST", "/fleet/heartbeat"), ("POST", "/devices/register")]
_YOZUV = [("POST", "/sales"), ("POST", "/returns"), ("POST", "/purchases"),
          ("POST", "/receiving/commit"), ("POST", "/inventory/count"),
          ("POST", "/inventory/writeoff"), ("POST", "/cash/ops"),
          ("POST", "/shifts/open"), ("POST", "/products/bulk"),
          ("PUT", "/settings")]


def _call(client, tenant, method, path):
    fn = getattr(client, method.lower())
    kw = {"headers": tenant["H"]}
    if method in MUTATING:
        kw["json"] = {}
    return fn(PFX + path, **kw)


@pytest.mark.parametrize("method,path", _OQISH)
def test_RESTRICTED_oqish_OTADI(client, tenant, method, path):
    _set_state(tenant, "RESTRICTED")
    assert not _blocked(_call(client, tenant, method, path))


@pytest.mark.parametrize("method,path", _HISOBOT)
def test_RESTRICTED_hisobot_OTADI(client, tenant, method, path):
    _set_state(tenant, "RESTRICTED")
    assert not _blocked(_call(client, tenant, method, path))


@pytest.mark.parametrize("method,path", _HISOB)
def test_RESTRICTED_hisob_billing_OTADI(client, tenant, method, path):
    _set_state(tenant, "RESTRICTED")
    assert not _blocked(_call(client, tenant, method, path))


@pytest.mark.parametrize("method,path", _YOZUV)
def test_RESTRICTED_biznes_yozuvi_403_BARQAROR_KOD_bilan(client, tenant, method, path):
    _set_state(tenant, "RESTRICTED")
    r = _call(client, tenant, method, path)
    assert r.status_code == 403, (method, path, r.status_code, r.text[:200])
    assert r.headers.get("X-Error-Code") == ERROR_CODE, dict(r.headers)


def test_RESTRICTED_smena_YOPISH_darvozadan_OTADI(client, tenant):
    """Ochiq smenani yopish — YAGONA ruxsat etilgan yozuv."""
    _set_state(tenant, "RESTRICTED")
    r = client.post(f"{PFX}/shifts/{uuid.uuid4()}/close",
                    headers=tenant["H"], json={"counted_cash": 0})
    #  Smena topilmasligi mumkin (404/400) — MUHIMI: obuna darvozasi to'smadi.
    assert not _blocked(r), (r.status_code, dict(r.headers))


def test_RESTRICTED_smena_OCHISH_esa_TOSILADI(client, tenant):
    _set_state(tenant, "RESTRICTED")
    assert _blocked(client.post(f"{PFX}/shifts/open", headers=tenant["H"], json={}))


@pytest.mark.parametrize("method,path", _YOZUV)
def test_ACTIVE_ayni_yozuvlar_darvozadan_OTADI(client, tenant, method, path):
    _set_state(tenant, "ACTIVE")
    assert not _blocked(_call(client, tenant, method, path))


def test_GRACE_ichida_yozuv_darvozadan_OTADI(client, tenant):
    """Grace — «to'lov kechikkan, lekin ish to'xtamaydi»."""
    from app.models.subscription import Subscription
    _set_state(tenant, "ACTIVE")
    with _db() as db:
        sub = db.query(Subscription).filter(
            Subscription.company_id == tenant["cid"]).one()
        #  Davrni O'TGAN, grace'ni esa HALI OCHIQ qilamiz (bevosita, hayot sikli
        #  amali emas: bu vaqt o'tishini taqlid qiladi).
        now = datetime.now(timezone.utc)
        sub.current_period_end = now - timedelta(hours=1)
        sub.grace_until = now + timedelta(days=2)
        db.commit()
    assert not _blocked(_call(client, tenant, "POST", "/sales"))
    with _db() as db:      # holatni qaytaramiz
        sub = db.query(Subscription).filter(
            Subscription.company_id == tenant["cid"]).one()
        sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
        sub.grace_until = datetime.now(timezone.utc) + timedelta(days=33)
        db.commit()


def test_GRANDFATHERED_yozuvsiz_ijarachi_TEGILMAYDI(client, admin_headers):
    """Obuna yozuvi YO'Q demo do'kon — eski xulq o'zgarmaydi."""
    from app.models.subscription import Subscription
    with _db() as db:
        assert db.query(Subscription).count() >= 0
    r = client.post(f"{PFX}/sales", headers=admin_headers, json={})
    assert not _blocked(r), (r.status_code, dict(r.headers))
    assert not _blocked(client.get(f"{PFX}/products", headers=admin_headers))
