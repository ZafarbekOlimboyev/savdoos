# -*- coding: utf-8 -*-
"""Phase 1 — SEYF ochilishi: MARSHRUT xulqi (T-22 va §7).

⚠️  `Depends(...)` bu yerda bajarilmaydi: marshrut FUNKSIYALARI to'g'ridan-to'g'ri
    chaqiriladi (cash to'plamida TestClient yo'q — u SQLite'da, cash esa Postgres'da).
    RUXSAT SIMLARI alohida sinaladi: `tests/test_safe_opening_permission.py`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1 import tills as tills_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.org import Branch, Company
from app.services.cash import safe_opening as so
from app.services.cash import till_identity as _ti
from app.services.cash.errors import CashError, CashPostingError

REF = "AKT-22"


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _tenant(db, *, role_code="menejer"):
    co = Company(name="A" + _hex(), code="a" + _hex(), currency="UZS")
    db.add(co)
    db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(br)
    db.flush()
    role = db.query(Role).filter(Role.code == role_code).first()
    if role is None:
        role = Role(code=role_code, name=role_code)
        db.add(role)
        db.flush()
    emp = Employee(company_id=co.id, full_name="M", role_id=role.id)
    db.add(emp)
    db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    safe = CashAccount(tenant_id=co.id, branch_id=br.id, type="SAFE", currency="UZS",
                       status="ACTIVE", label=_ti.safe_label("S-" + _hex()), created_at=_now())
    db.add(safe)
    db.commit()
    emp.role
    return co, br, emp, safe


def _attest_body(kind="COUNTED", amount=480000.0, at=None, ref=REF):
    return tills_api.SafeOpeningAttest(kind=kind, counted_amount=amount,
                                       counted_at=(at or _now()), attestation_ref=ref)


# ═══ T-22a) UNKNOWN -> balance NULL (0 EMAS) ═══════════════════════════════
def test_22a_unknown_balans_null(db, cashenv):
    co, br, emp, safe = _tenant(db)
    out = tills_api.safe_balance(safe_id=safe.id, emp=emp, db=db)
    assert out["opening"]["state"] == "UNKNOWN"
    assert out["operational"] is False
    assert out["balance"] is None, "UNKNOWN da 0 KO'RSATILMAYDI (yolg'on 'bo'sh seyf')"
    assert out["opening"]["amount"] is None


# ═══ T-22b) COUNTED -> hosil qilingan balans + ochilish summasi ════════════
def test_22b_counted_balans_va_ochilish(db, cashenv):
    co, br, emp, safe = _tenant(db)
    res = tills_api.attest_safe_opening(safe_id=safe.id, data=_attest_body(), emp=emp, db=db)
    assert res["result"] == "created"
    out = tills_api.safe_balance(safe_id=safe.id, emp=emp, db=db)
    assert out["opening"]["state"] == "COUNTED"
    assert out["operational"] is True
    assert Decimal(out["balance"]) == Decimal("480000.00")
    assert Decimal(out["opening"]["amount"]) == Decimal("480000.00")
    assert out["opening"]["attestation_ref"] == REF
    assert out["as_of"] is not None


# ═══ T-22c) KNOWN_ZERO -> balans 0, ochilish summasi YO'Q ══════════════════
def test_22c_known_zero(db, cashenv):
    co, br, emp, safe = _tenant(db)
    tills_api.attest_safe_opening(safe_id=safe.id,
                                  data=_attest_body(kind="KNOWN_ZERO", amount=0.0),
                                  emp=emp, db=db)
    out = tills_api.safe_balance(safe_id=safe.id, emp=emp, db=db)
    assert out["opening"]["state"] == "KNOWN_ZERO"
    assert out["operational"] is True
    assert Decimal(out["balance"]) == Decimal("0")
    assert out["opening"]["amount"] is None      # summa YO'Q (leg ham yo'q)


# ═══ T-22d) BOSHQA TENANT -> 404 (mavjudlik oshkor QILINMAYDI) ════════════
def test_22d_boshqa_tenant_404(db, cashenv):
    co1, br1, emp1, safe1 = _tenant(db)
    co2, br2, emp2, safe2 = _tenant(db)
    for fn in (lambda: tills_api.safe_balance(safe_id=safe2.id, emp=emp1, db=db),
               lambda: tills_api.attest_safe_opening(safe_id=safe2.id, data=_attest_body(),
                                                     emp=emp1, db=db)):
        with pytest.raises(HTTPException) as ei:
            fn()
        db.rollback()
        assert ei.value.status_code == 404


# ═══ T-22e) TILL id bilan seyf marshruti -> 404 ═══════════════════════════
def test_22e_till_id_bilan_404(db, cashenv):
    co, br, emp, safe = _tenant(db)
    till = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS",
                       status="ACTIVE", label=_ti.till_label("T-" + _hex(), None),
                       created_at=_now())
    db.add(till)
    db.commit()
    with pytest.raises(HTTPException) as ei:
        tills_api.safe_balance(safe_id=till.id, emp=emp, db=db)
    assert ei.value.status_code == 404


# ═══ T-22f) marshrut IDEMPOTENT / 409 shartnomasi ═════════════════════════
def test_22f_marshrut_idempotent_va_409(db, cashenv):
    co, br, emp, safe = _tenant(db)
    at = _now()
    r1 = tills_api.attest_safe_opening(safe_id=safe.id, data=_attest_body(at=at), emp=emp, db=db)
    r2 = tills_api.attest_safe_opening(safe_id=safe.id, data=_attest_body(at=at), emp=emp, db=db)
    assert r1["result"] == "created" and r2["result"] == "duplicate"
    # ⚠️  `status` — HISOB holati, attestatsiya natijasi EMAS (kalit to'qnashuvi)
    assert r1["status"] == "ACTIVE"
    assert r1["opening_id"] == r2["opening_id"]
    with pytest.raises(CashPostingError) as ei:
        tills_api.attest_safe_opening(safe_id=safe.id,
                                      data=_attest_body(amount=1.0, at=at), emp=emp, db=db)
    db.rollback()
    assert ei.value.code == CashError.SAFE_OPENING_CONFLICT


# ═══ §7) BALANS marshruti kassirning kodlarini QABUL QILMAYDI ═════════════
def test_balans_darvozasi_kassirsiz():
    """Seyf qoldig'i — PUL ma'lumoti: `kassa.sell`/`kassa.view` UNI OCHMAYDI."""
    perms = set(tills_api.SAFE_BALANCE_READ_PERMS)
    assert "kassa.sell" not in perms and "kassa.view" not in perms
    assert "hisobot.view" in perms and "kassa.attest" in perms
    # ro'yxat darvozasi O'ZGARMAGAN (regressiya bo'lmasin)
    assert tills_api.TILL_READ_PERMS == ("kassa.sell", "kassa.view", "sozlamalar.view",
                                         "sozlamalar.edit", "hisobot.view")
