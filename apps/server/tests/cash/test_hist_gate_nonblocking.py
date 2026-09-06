# -*- coding: utf-8 -*-
"""§HIST-REVIEW: dalilsiz (HISTORICAL_TILL_UNKNOWN) qatorlar §9 VERIFY gate'ini BLOKLAMASLIGI kerak.

Adversarial review topilmasi: skip qilingan legalar unexplained_delta/verify majburiy shartlarini
buzib, migratsiyani HARD-STOP qilishi mumkin edi. Qoida: dalilsiz tarixiy identity BLOKER EMAS.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db.cash.migration import backfill, preflight as pf
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.customers import Customer, CustomerPayment
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.sales import Return
from app.models.shifts import Shift
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def test_mixed_resolved_and_unknown_does_not_block_verify(db, cashenv):
    """Yarmi DALILLI (yoziladi), yarmi DALILSIZ (skip) -> GO + verify majburiy shartlari PASS."""
    co = Company(name="GT" + _hex(), code="gt" + _hex(), currency="UZS"); db.add(co); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True); db.add(br); db.flush()
    emp = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(emp); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                       label=_ti.till_label("T-" + _hex(), None), created_at=_now())
    db.add(till); db.flush()
    t0 = _now()
    # (a) DALILLI: smena till_id bilan -> Return SHIFT_TILL_ID orqali hal bo'ladi
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=t0 - timedelta(hours=4),
               closed_at=t0 - timedelta(hours=3), opening_cash=Decimal("0"),
               counted_cash=Decimal("0"), status=ShiftStatus.closed, till_id=till.id)
    db.add(sh); db.flush()
    db.add(Return(return_no="RET" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
                  refund_method="cash", total=Decimal("4000"), created_at=t0 - timedelta(hours=3, minutes=30),
                  shift_id=sh.id))
    # (b) DALILSIZ: CustomerPayment (till/shift/terminal yo'q, soya yo'q) -> HISTORICAL_TILL_UNKNOWN
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="A", credit_balance=Decimal("0"))
    db.add(cu); db.flush()
    db.add(CustomerPayment(customer_id=cu.id, amount=Decimal("3000"), method="cash",
                           paid_at=t0 - timedelta(days=200), created_at=t0 - timedelta(days=200),
                           employee_id=emp.id, branch_id=br.id))
    db.commit()

    m = backfill.execute_backfill(db, company_id=co.id, apply=True, t0=t0.isoformat())
    # dalilli qator YOZILDI, dalilsiz qator SKIP + REVIEW
    assert m["go_no_go"] == "GO" and not m["blocked"]
    assert db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "REFUND").count() == 1
    assert db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "DEBT_IN").count() == 0
    unknown = [r for r in m["review"] if r.get("evidence_class") == "HISTORICAL_TILL_UNKNOWN"]
    assert len(unknown) == 1

    # §9 GATE: dalilsiz skip BLOKLAMASIN
    g = pf.post_backfill_verification(db, m, company_id=co.id, t0=t0.isoformat())
    assert g["ok"] is True, f"HISTORICAL_TILL_UNKNOWN §9 verify gate'ini BLOKLADI: {g}"
    assert all(g["mandatory"].values()), g["mandatory"]


def test_all_unknown_does_not_block_verify(db, cashenv):
    """HAMMA qator dalilsiz -> ledger bo'sh, lekin GO + verify PASS (migratsiya to'xtamaydi)."""
    co = Company(name="GT" + _hex(), code="gt" + _hex(), currency="UZS"); db.add(co); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True); db.add(br); db.flush()
    emp = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(emp); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    db.add(CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                       label=_ti.till_label("T-" + _hex(), None), created_at=_now()))
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="A", credit_balance=Decimal("0"))
    db.add(cu); db.flush()
    t0 = _now()
    db.add(CustomerPayment(customer_id=cu.id, amount=Decimal("3000"), method="cash",
                           paid_at=t0 - timedelta(days=200), created_at=t0 - timedelta(days=200),
                           employee_id=emp.id, branch_id=br.id))
    db.commit()
    m = backfill.execute_backfill(db, company_id=co.id, apply=True, t0=t0.isoformat())
    assert m["go_no_go"] == "GO" and m["inserted_rows"] == 0
    g = pf.post_backfill_verification(db, m, company_id=co.id, t0=t0.isoformat())
    assert g["ok"] is True, f"to'liq dalilsiz tenant §9 gate'ini BLOKLADI: {g}"
