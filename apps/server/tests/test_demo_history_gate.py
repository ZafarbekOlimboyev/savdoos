# -*- coding: utf-8 -*-
"""DEMO-TARIX QURILISHI — LIVE KASSA/POS OQIMI YOPIQ (NC3/NC4/NC5).

Qurilish holatida tenant `cutover_at`siz va `ledger_native`siz, ya'ni naqd quyi
tizimi uni LEGACY pre-T0 tenant deb ko'radi — bu naqd darvozalarining ENG
BO'SH holati. Shu bois live oqim ALOHIDA bloklanadi.

A  QAMROV (ikki tomonlama): har bir nomzod marshrut yo to'siladi, yo ATALGAN istisno
B  POLARITY: blok FAIL-CLOSED — nomzod sinfdagi notanish marshrut TO'SILADI
C  ATALGAN pul/zaxira/smena marshrutlari to'silgan (qayta tasniflash ushlanadi)
D  o'qish sinflari va imtiyozli tarixiy yuza HECH QACHON to'silmaydi
E  XULQ: qurilish tenantida `POST /sales` -> 409 HISTORICAL_BUILD_LOCKED
F  XULQ: blok TANA VALIDATSIYASIDAN OLDIN ishlaydi (bo'sh tana ham 409, 422 emas)
G  XULQ: NORMAL tenant bloklanmaydi (test bo'sh emasligining isboti)
H  XULQ: finalize'dan keyin blok O'ZI ochiladi
I  XULQ: tokensiz so'rov 409 EMAS — 401 (fail-open mulohazasi aniq qulflangan)
J  QAMROV: qurilish bloki OBUNA blokidan AJRALGAN (boshqa kod, boshqa status)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import subscription_routes as SR
from app.core.security import create_access_token
from app.models.auth import Employee, Role
from app.models.enums import EmployeeStatus
from app.models.org import Branch, Company
from app.services.cash import tenant as _t

R = SR.SUBSCRIPTION_ROUTE_ACTIONS

#: ATAYLAB QO'LDA yozilgan: pul ko'chadigan, zaxira hujjati yozadigan yoki smena
#  lifecycle'iga tegadigan marshrutlar. Reestrda sinf o'zgarsa yoki kimdir bu
#  marshrutni istisnoga ko'chirsa — C testi QIZIL bo'ladi.
MAJBURIY_TOSILADI = [
    ("POST", "/sales"),
    ("POST", "/sync/push"),
    ("POST", "/returns"),
    ("POST", "/shifts/open"),
    ("POST", "/shifts/{shift_id}/cash"),
    ("POST", "/shifts/{shift_id}/close"),
    ("POST", "/cash/ops"),
    ("POST", "/customers/{customer_id}/payments"),
    ("POST", "/suppliers/{supplier_id}/payments"),
    ("POST", "/purchases"),
    ("POST", "/receiving/commit"),
    ("POST", "/receiving/scan"),
    ("POST", "/inventory/count"),
    ("POST", "/inventory/transfer"),
    ("POST", "/inventory/writeoff"),
    ("POST", "/payments/qr"),
    ("GET", "/payments/qr/{txn_id}"),
    ("POST", "/safes/{safe_id}/opening"),
]


def _nomzodlar():
    return [k for k, v in R.items() if v in SR.HISTORICAL_BUILD_CANDIDATES]


# ═══ A) qamrov ════════════════════════════════════════════════
def test_A_har_nomzod_YO_tosiladi_YO_atalgan_istisno():
    nomzod = _nomzodlar()
    assert len(nomzod) >= 60, f"nomzod soni kutilmaganda kam: {len(nomzod)}"
    for key in nomzod:
        tosildi = SR.blocked_during_historical_build(R[key], key)
        istisno = key in SR.HISTORICAL_BUILD_SETUP_OPEN
        assert tosildi != istisno, f"{key}: na to'silgan na istisno (yoki ikkisi birga)"


def test_A2_istisno_royxatida_ESKIRGAN_yozuv_YOQ():
    """Reestrda bo'lmagan istisno — yozuv xatosi yoki o'chirilgan marshrut."""
    eskirgan = sorted(SR.HISTORICAL_BUILD_SETUP_OPEN - set(R))
    assert not eskirgan, f"istisno reestrda topilmadi: {eskirgan}"


def test_A3_istisnolar_FAQAT_nomzod_sinfdan():
    """O'qish marshrutini istisnoga yozish ma'nosiz — u baribir to'silmaydi."""
    xato = sorted(k for k in SR.HISTORICAL_BUILD_SETUP_OPEN
                  if R.get(k) not in SR.HISTORICAL_BUILD_CANDIDATES)
    assert not xato, f"nomzod bo'lmagan sinf istisnoda: {xato}"


# ═══ B) polarity ═════════════════════════════════════════════
def test_B_FAIL_CLOSED_notanish_biznes_marshruti_TOSILADI():
    """Kelajakda qo'shilgan YANGI pul marshruti jimgina ochiq qolmaydi."""
    yangi = ("POST", "/hali-yoq-boladigan-pul-marshruti")
    assert yangi not in R
    assert SR.blocked_during_historical_build(SR.BLOCK_BUSINESS_WRITE, yangi) is True
    assert SR.blocked_during_historical_build(SR.ALLOW_SHIFT_CLOSE, yangi) is True


def test_B2_kalit_YO_Q_bolsa_ham_TOSILADI():
    assert SR.blocked_during_historical_build(SR.BLOCK_BUSINESS_WRITE, None) is True


# ═══ C) atalgan marshrutlar ═══════════════════════════════════
@pytest.mark.parametrize("key", MAJBURIY_TOSILADI, ids=[f"{m}{p}" for m, p in MAJBURIY_TOSILADI])
def test_C_pul_zaxira_smena_marshruti_TOSILADI(key):
    assert key in R, f"{key} reestrda yo'q — marshrut o'chirilgan yoki nomi o'zgargan"
    assert SR.blocked_during_historical_build(R[key], key) is True, \
        f"{key} qurilish davomida OCHIQ qolgan"


# ═══ D) hech qachon to'silmaydiganlar ══════════════════════════
@pytest.mark.parametrize("key", [("GET", "/products"), ("GET", "/settings"),
                                 ("GET", "/shifts/current"), ("GET", "/shifts/overview"),
                                 ("POST", "/historical/events"),
                                 ("POST", "/reports/history/seed")])
def test_D_oqish_va_imtiyozli_yuza_TOSILMAYDI(key):
    assert key in R
    assert SR.blocked_during_historical_build(R[key], key) is False


def test_D2_imtiyozli_yuza_OUT_OF_SCOPE_bolib_qoladi():
    """Blok `OUT_OF_SCOPE_SYSTEM` erta qaytishidan KEYIN turadi — shu bois
    tarixiy yuzaning ochiqligi tasnifga TAYANADI, qo'shimcha istisnoga emas."""
    assert R[("POST", "/historical/events")] == SR.OUT_OF_SCOPE_SYSTEM
    assert R[("POST", "/reports/history/seed")] == SR.OUT_OF_SCOPE_SYSTEM


# ═══ E–I) XULQ — haqiqiy HTTP ══════════════════════════════════
def _tenant(*, qurilish: bool):
    """Do'kon + filial + 'ega' xodim + token. `cash` qatori COMMIT qilinadi:
    darvoza so'rovning O'Z sessiyasida o'qiydi."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        code = ("demo" if qurilish else "live") + "-gate-" + uuid.uuid4().hex[:8]
        co = Company(id=uuid.uuid4(), name="Gate", code=code, currency="KGS")
        db.add(co)
        db.flush()
        db.add(Branch(id=uuid.uuid4(), company_id=co.id, name="F01", code="F01"))
        role = db.query(Role).filter(Role.code == "ega").first()
        emp = Employee(id=uuid.uuid4(), company_id=co.id, role_id=role.id, full_name="Ega",
                       phone=f"+9984{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        if qurilish:
            _t.mark_historical_build(db, co.id, at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        else:
            _t.mark_ledger_native(db, co.id)
        db.commit()
        tok = create_access_token(str(emp.id),
                                  {"role": "ega", "company_id": str(co.id), "sv": 0})
        return co.id, {"Authorization": f"Bearer {tok}"}
    finally:
        db.close()


def test_E_qurilish_tenantida_sales_409_HISTORICAL_BUILD_LOCKED(client):
    _cid, h = _tenant(qurilish=True)
    r = client.post("/api/v1/sales", json={}, headers=h)
    assert r.status_code == 409, r.text
    assert r.headers.get("X-Error-Code") == "HISTORICAL_BUILD_LOCKED"
    assert "QURILISHI" in r.json()["detail"]


def test_F_blok_TANA_VALIDATSIYASIDAN_OLDIN(client):
    """Bo'sh tana 422 EMAS, 409 beradi — ya'ni blok endpoint tanasiga YETMAYDI
    va yarim yozuv imkoniyati YO'Q."""
    _cid, h = _tenant(qurilish=True)
    for yol, tana in (("/api/v1/shifts/open", {}),
                      ("/api/v1/cash/ops", {}),
                      ("/api/v1/returns", {}),
                      ("/api/v1/sync/push", {})):
        r = client.post(yol, json=tana, headers=h)
        assert r.status_code == 409, f"{yol}: {r.status_code} {r.text[:200]}"
        assert r.headers.get("X-Error-Code") == "HISTORICAL_BUILD_LOCKED", yol


def test_G_NORMAL_tenant_BLOKLANMAYDI(client):
    """E/F bo'sh emasligining isboti: ayni so'rov normal tenantda 409 BERMAYDI."""
    _cid, h = _tenant(qurilish=False)
    r = client.post("/api/v1/sales", json={}, headers=h)
    assert r.status_code != 409, r.text
    assert r.headers.get("X-Error-Code") != "HISTORICAL_BUILD_LOCKED"


def test_H_finalizedan_keyin_blok_OZI_ochiladi(client):
    from app.db.session import SessionLocal
    cid, h = _tenant(qurilish=True)
    r = client.post("/api/v1/sales", json={}, headers=h)
    assert r.status_code == 409                                  # YOPIQ

    db = SessionLocal()
    try:
        _t.finalize_historical_build(
            db, cid, t0=datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(microseconds=1))
        db.commit()
    finally:
        db.close()

    r2 = client.post("/api/v1/sales", json={}, headers=h)        # OCHIQ
    assert r2.status_code != 409, r2.text
    assert r2.headers.get("X-Error-Code") != "HISTORICAL_BUILD_LOCKED"


def test_I_TOKENSIZ_sorov_409_EMAS(client):
    """Darvoza kompaniyani token'dan oladi; token bo'lmasa JIM qaytadi va
    401 ni marshrutning o'z auth qatlami beradi. Bu fail-open ATAYLAB —
    lekin yozuv BARIBIR bo'lmaydi, shu bois test 401 ni TALAB qiladi."""
    r = client.post("/api/v1/sales", json={})
    assert r.status_code in (401, 403), r.text
    assert r.headers.get("X-Error-Code") != "HISTORICAL_BUILD_LOCKED"


# ═══ J) obuna blokidan ajralgan ═════════════════════════════
def test_J_qurilish_bloki_OBUNA_blokidan_AJRALGAN():
    """⚠️  Bu testning uchinchi tasdig'i ilgari DOIMIY `True` edi:
        `SR.HISTORICAL_BUILD_MESSAGE != SR.MESSAGE if hasattr(SR, "MESSAGE") else True`
        — `subscription_routes` da `MESSAGE` YO'Q (u `subscription_gate` da),
        shu bois shart hech qachon tekshirilmasdi. Adversarial ko'rik topdi.
    """
    from app.core import subscription_gate as SG

    assert SR.HISTORICAL_BUILD_ERROR_CODE == "HISTORICAL_BUILD_LOCKED"
    assert SR.ERROR_CODE == "SUBSCRIPTION_RESTRICTED"
    assert SR.HISTORICAL_BUILD_ERROR_CODE != SR.ERROR_CODE
    #  Matnlar ham AJRALGAN — operator ikki holatni aralashtirmasin.
    assert isinstance(SG.MESSAGE, str) and SG.MESSAGE
    assert isinstance(SR.HISTORICAL_BUILD_MESSAGE, str) and SR.HISTORICAL_BUILD_MESSAGE
    assert SR.HISTORICAL_BUILD_MESSAGE != SG.MESSAGE
    #  Va STATUS ham: obuna 403, qurilish 409.
    assert "QURILISHI" in SR.HISTORICAL_BUILD_MESSAGE
