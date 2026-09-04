# -*- coding: utf-8 -*-
"""CashPostingService integratsion testlari (real PostgreSQL / pgserver) — kontrakt v1.0.

47 test: basic posting, account behavior, offline A/B/C/D, idempotency, cash guard,
transfer, reversal, security, reconciliation, concurrency.
"""
from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.auth import Employee, Role
from app.models.cash import (
    CashAccount,
    CashLedgerEntry,
    CashLedgerException,
    CashShift,
    NegativeCashApproval,
    ReconciliationRecord,
)
from app.models.org import Branch, Company
from app.services.cash import adapters, lifecycle
from app.services.cash import repositories as repo
from app.services.cash.commands import PostingCommand, ReversalCommand, TransferCommand
from app.services.cash.errors import CashError, CashPostingError
from app.services.cash.posting import cash_posting_service as svc
from _factory import make_account, new_id, open_shift  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────
def cashier(db, cashenv):
    return db.get(Employee, cashenv.employee_id)


def manager(db, cashenv):
    r = db.query(Role).filter(Role.code == "menejer").first()
    if r is None:
        r = Role(code="menejer", name="Menejer")
        db.add(r)
        db.flush()
    m = Employee(company_id=cashenv.company_id, full_name="Menejer", role_id=r.id)
    db.add(m)
    db.commit()
    return m


def fund(db, emp, till, sh, amount):
    adapters.manual_cash_in(db, emp, cash_account_id=till.id, source_id=new_id(),
                            amount=amount, origin_shift_id=sh.id)


def expect_code(db, code, fn):
    with pytest.raises(CashPostingError) as ei:
        fn()
    db.rollback()
    assert ei.value.code == code, f"expected {code}, got {ei.value.code}: {ei.value}"
    return ei.value


def D(x):
    return Decimal(str(x))


def bal(db, cashenv, acct):
    return repo.account_balance(db, cashenv.company_id, acct.id)


# ── 1–11 basic posting ───────────────────────────────────────────────────────
def test_01_cash_sale(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=new_id(), amount=5000, origin_shift_id=sh.id)
    assert r.posting_kind == "ON_SHIFT" and r.direction == "IN" and r.category == "SALE"
    assert bal(db, cashenv, till) == D("5000.00")


def test_02_cash_refund(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 10000)
    r = adapters.cash_refund(db, emp, cash_account_id=till.id, source_id=new_id(), amount=3000, origin_shift_id=sh.id)
    assert r.direction == "OUT" and r.category == "REFUND"
    assert bal(db, cashenv, till) == D("7000.00")


def test_03_debt_payment(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.debt_payment(db, emp, cash_account_id=till.id, source_id=new_id(), amount=4000, origin_shift_id=sh.id)
    assert r.category == "DEBT_IN" and bal(db, cashenv, till) == D("4000.00")


def test_04_supplier_payment(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 9000)
    r = adapters.supplier_payment(db, emp, cash_account_id=till.id, source_id=new_id(), amount=6000, origin_shift_id=sh.id)
    assert r.category == "SUPPLIER_OUT" and bal(db, cashenv, till) == D("3000.00")


def test_05_cash_purchase(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 9000)
    r = adapters.cash_purchase(db, emp, cash_account_id=till.id, source_id=new_id(), amount=2500, origin_shift_id=sh.id)
    assert r.category == "PURCHASE_OUT" and bal(db, cashenv, till) == D("6500.00")


def test_06_purchase_return(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.purchase_return(db, emp, cash_account_id=till.id, source_id=new_id(), amount=1500, origin_shift_id=sh.id)
    assert r.category == "PURCHASE_RETURN" and bal(db, cashenv, till) == D("1500.00")


def test_07_cash_in(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.manual_cash_in(db, emp, cash_account_id=till.id, source_id=new_id(), amount=2000, origin_shift_id=sh.id)
    assert r.category == "CASH_IN" and r.direction == "IN"


def test_08_cash_out(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 5000)
    r = adapters.manual_cash_out(db, emp, cash_account_id=till.id, source_id=new_id(), amount=1000, origin_shift_id=sh.id)
    assert r.category == "CASH_OUT" and bal(db, cashenv, till) == D("4000.00")


def test_09_expense(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 5000)
    r = adapters.expense(db, emp, cash_account_id=till.id, source_id=new_id(), amount=800, origin_shift_id=sh.id)
    assert r.category == "EXPENSE" and bal(db, cashenv, till) == D("4200.00")


def test_10_adjustment_requires_manager(db, cashenv):
    cash_emp = cashier(db, cashenv); mgr = manager(db, cashenv)
    till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    # kassir -> UNAUTHORIZED
    expect_code(db, CashError.UNAUTHORIZED_OPERATION, lambda: adapters.adjustment(
        db, cash_emp, cash_account_id=till.id, source_id=new_id(), amount=500, direction="IN", origin_shift_id=sh.id))
    # menejer -> OK
    r = adapters.adjustment(db, mgr, cash_account_id=till.id, source_id=new_id(), amount=500, direction="IN", origin_shift_id=sh.id)
    assert r.category == "ADJUSTMENT"


def test_11_opening(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL")
    sh = lifecycle.open_shift(db, emp, cash_account_id=till.id, opening_amount=100000)
    assert sh.status == "OPEN"
    assert bal(db, cashenv, till) == D("100000.00")


# ── 12–15 account behavior ───────────────────────────────────────────────────
def test_12_safe_posting(db, cashenv):
    emp = cashier(db, cashenv); safe = make_account(db, cashenv, "SAFE")
    r = adapters.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=new_id(), amount=50000)
    assert r.posting_kind == "OFF_SHIFT" and r.shift_id is None


def test_13_till_posting(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=new_id(), amount=100, origin_shift_id=sh.id)
    assert r.posting_kind == "ON_SHIFT" and r.shift_id == sh.id


def test_14_safe_cannot_borrow_till_shift(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); safe = make_account(db, cashenv, "SAFE")
    sh = open_shift(db, cashenv, till)
    # SAFE hisobga TILL smenasini berish -> SAFE OFF_SHIFT (смена e'tiborga olinmaydi)
    r = adapters.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=new_id(), amount=100, origin_shift_id=sh.id)
    assert r.posting_kind == "OFF_SHIFT" and r.shift_id is None


def test_15_two_tills_independent(db, cashenv):
    emp = cashier(db, cashenv)
    t1 = make_account(db, cashenv, "TILL"); s1 = open_shift(db, cashenv, t1)
    t2 = make_account(db, cashenv, "TILL"); s2 = open_shift(db, cashenv, t2)
    adapters.cash_sale(db, emp, cash_account_id=t1.id, source_id=new_id(), amount=1000, origin_shift_id=s1.id)
    adapters.cash_sale(db, emp, cash_account_id=t2.id, source_id=new_id(), amount=2000, origin_shift_id=s2.id)
    assert bal(db, cashenv, t1) == D("1000.00") and bal(db, cashenv, t2) == D("2000.00")


# ── 16–20 offline A/B/C/D ────────────────────────────────────────────────────
def test_16_case_a(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=new_id(), amount=100,
                           origin_shift_id=sh.id, device_occurred_at=cashenv.now + timedelta(minutes=5))
    assert r.posting_kind == "ON_SHIFT"


def test_17_case_b(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=new_id(), amount=100,
                           origin_shift_id=sh.id, device_occurred_at=cashenv.now - timedelta(days=2))
    assert r.posting_kind == "OFF_SHIFT" and r.shift_id is None
    assert "TIMESTAMP_OUT_OF_WINDOW" in r.exceptions
    e = db.get(CashLedgerEntry, r.entry_id)
    assert e.device_occurred_at.date() == (cashenv.now - timedelta(days=2)).date()  # saqlangan, clamp yo'q


def test_18_case_c(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    lifecycle.close_shift(db, emp, shift_id=sh.id, counted_cash=0)
    r = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=new_id(), amount=100,
                           origin_shift_id=sh.id, device_occurred_at=cashenv.now + timedelta(minutes=1))
    assert r.posting_kind == "LATE_SYNC" and r.shift_id == sh.id
    assert "LATE_SYNC_UNACK" in r.exceptions


def test_19_case_d_till(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL")
    r = adapters.manual_cash_in(db, emp, cash_account_id=till.id, source_id=new_id(), amount=100)  # origin_shift_id yo'q
    assert r.posting_kind == "OFF_SHIFT" and r.shift_id is None
    assert "UNRESOLVED_OFF_SHIFT" in r.exceptions


def test_20_case_d_safe(db, cashenv):
    emp = cashier(db, cashenv); safe = make_account(db, cashenv, "SAFE")
    r = adapters.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=new_id(), amount=100)
    assert r.posting_kind == "OFF_SHIFT" and r.shift_id is None
    assert r.exceptions == []  # SAFE — anomaliya YO'Q


# ── 21–23 idempotency ────────────────────────────────────────────────────────
def test_21_sequential_duplicate(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    sid = new_id()
    r1 = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=sid, amount=1000, origin_shift_id=sh.id)
    r2 = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=sid, amount=1000, origin_shift_id=sh.id)
    assert r2.is_duplicate and r2.entry_id == r1.entry_id
    assert bal(db, cashenv, till) == D("1000.00")  # bir marta


def test_22_simultaneous_duplicate(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    sid = new_id()

    def do(s):
        e = s.get(Employee, cashenv.employee_id)
        return adapters.cash_sale(s, e, cash_account_id=till.id, source_id=sid, amount=1000, origin_shift_id=sh.id)

    ra, rb = _concurrent(cashenv.engine, do, do)
    results = [r for r in (ra, rb) if not isinstance(r, Exception)]
    # QAT'IY INVARIANT (DB cle_uq_business): AYNAN BITTA ledger satr — dublikat post MUMKIN EMAS
    # (interleaving qanaqa bo'lishidan qat'i nazar). Bu — bu testning haqiqiy xavfsizlik xossasi.
    cnt = db.query(CashLedgerEntry).filter(CashLedgerEntry.source_id == sid).count()
    assert cnt == 1
    created = [r for r in results if not r.is_duplicate]
    assert len(results) >= 1 and len(created) <= 1   # kamida bittasi o'tdi; ikki satr HECH QACHON
    if len(results) == 2:                             # odatдаги holat: 1 CREATED + 1 DUPLICATE
        assert len(created) == 1
        assert any(r.is_duplicate for r in results)


def test_23_duplicate_out_after_cash_consumed(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 5000)
    sid = new_id()
    r1 = adapters.manual_cash_out(db, emp, cash_account_id=till.id, source_id=sid, amount=5000, origin_shift_id=sh.id)
    assert bal(db, cashenv, till) == D("0.00")
    # dublikat OUT retry — INSUFFICIENT_CASH BO'LMASLIGI kerak, canonical qaytadi
    r2 = adapters.manual_cash_out(db, emp, cash_account_id=till.id, source_id=sid, amount=5000, origin_shift_id=sh.id)
    assert r2.is_duplicate and r2.entry_id == r1.entry_id


# ── 24–26 cash guard ─────────────────────────────────────────────────────────
def test_24_insufficient_cash(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    expect_code(db, CashError.INSUFFICIENT_CASH, lambda: adapters.manual_cash_out(
        db, emp, cash_account_id=till.id, source_id=new_id(), amount=1000, origin_shift_id=sh.id))


def test_25_negative_override(db, cashenv):
    mgr = manager(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    r = adapters.manual_cash_out(db, mgr, cash_account_id=till.id, source_id=new_id(), amount=1000,
                                 origin_shift_id=sh.id, allow_negative=True, negative_reason="urgent")
    assert "NEGATIVE_OVERRIDE" in r.exceptions
    assert bal(db, cashenv, till) == D("-1000.00")
    appr = db.query(NegativeCashApproval).filter_by(entry_id=r.entry_id).first()
    assert appr is not None and appr.till_balance_after == D("-1000.00")


def test_26_override_requires_manager(db, cashenv):
    cash_emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    expect_code(db, CashError.UNAUTHORIZED_OPERATION, lambda: adapters.manual_cash_out(
        db, cash_emp, cash_account_id=till.id, source_id=new_id(), amount=1000,
        origin_shift_id=sh.id, allow_negative=True, negative_reason="x"))


# ── 27–32 transfer ───────────────────────────────────────────────────────────
def test_27_till_to_safe(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    safe = make_account(db, cashenv, "SAFE")
    fund(db, emp, till, sh, 10000)
    r = adapters.transfer(db, emp, from_account_id=till.id, to_account_id=safe.id, amount=4000)
    assert len(r.entry_ids) == 2
    assert bal(db, cashenv, till) == D("6000.00") and bal(db, cashenv, safe) == D("4000.00")


def test_28_till_to_till(db, cashenv):
    emp = cashier(db, cashenv)
    t1 = make_account(db, cashenv, "TILL"); s1 = open_shift(db, cashenv, t1)
    t2 = make_account(db, cashenv, "TILL"); open_shift(db, cashenv, t2)
    fund(db, emp, t1, s1, 8000)
    r = adapters.transfer(db, emp, from_account_id=t1.id, to_account_id=t2.id, amount=3000)
    assert bal(db, cashenv, t1) == D("5000.00") and bal(db, cashenv, t2) == D("3000.00")
    assert len(r.entry_ids) == 2


def test_29_safe_to_till(db, cashenv):
    emp = cashier(db, cashenv); safe = make_account(db, cashenv, "SAFE"); till = make_account(db, cashenv, "TILL")
    open_shift(db, cashenv, till)
    adapters.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=new_id(), amount=9000)
    r = adapters.transfer(db, emp, from_account_id=safe.id, to_account_id=till.id, amount=5000)
    assert bal(db, cashenv, safe) == D("4000.00") and bal(db, cashenv, till) == D("5000.00")


def test_30_incomplete_transfer_rollback(db, cashenv):
    # from == to -> INVALID_TRANSFER, hech narsa yozilmaydi
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); open_shift(db, cashenv, till)
    before = db.query(CashLedgerEntry).count()
    expect_code(db, CashError.INVALID_TRANSFER, lambda: adapters.transfer(
        db, emp, from_account_id=till.id, to_account_id=till.id, amount=100))
    assert db.query(CashLedgerEntry).count() == before


def test_31_transfer_vs_shift_close_race(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    safe = make_account(db, cashenv, "SAFE")
    fund(db, emp, till, sh, 10000)

    def do_transfer(s):
        e = s.get(Employee, cashenv.employee_id)
        return adapters.transfer(s, e, from_account_id=till.id, to_account_id=safe.id, amount=3000)

    def do_close(s):
        e = s.get(Employee, cashenv.employee_id)
        return lifecycle.close_shift(s, e, shift_id=sh.id, counted_cash=0)

    ra, rb = _concurrent(cashenv.engine, do_transfer, do_close)
    # deadlock/korruptsiya yo'q; ikki operatsiya ham yakunlanadi (biri LATE_SYNC bo'lishi mumkin)
    errs = [r for r in (ra, rb) if isinstance(r, Exception)]
    assert all(isinstance(e, CashPostingError) for e in errs)  # faqat domen xatolari (crash emas)
    db.expire_all()
    assert bal(db, cashenv, safe) in (D("0.00"), D("3000.00"))  # transfer o'tdi yoki o'tmadi — atomik


def test_32_transfer_idempotency(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    safe = make_account(db, cashenv, "SAFE"); fund(db, emp, till, sh, 10000)
    sid = new_id()
    r1 = adapters.transfer(db, emp, from_account_id=till.id, to_account_id=safe.id, amount=2000, source_id=sid)
    r2 = adapters.transfer(db, emp, from_account_id=till.id, to_account_id=safe.id, amount=2000, source_id=sid)
    assert r2.is_duplicate
    assert bal(db, cashenv, safe) == D("2000.00")  # bir marta


# ── 33–36 reversal ───────────────────────────────────────────────────────────
def test_33_full_reversal(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 5000)
    out = adapters.manual_cash_out(db, emp, cash_account_id=till.id, source_id=new_id(), amount=2000, origin_shift_id=sh.id)
    rev = adapters.reversal(db, emp, reverses_id=out.entry_id, origin_shift_id=sh.id)
    assert rev.direction == "IN"
    assert bal(db, cashenv, till) == D("5000.00")  # OUT bekor qilindi
    orig = db.get(CashLedgerEntry, out.entry_id)
    assert orig.amount == D("2000.00")  # original o'zgarmagan


def test_34_double_reversal(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 5000)
    out = adapters.manual_cash_out(db, emp, cash_account_id=till.id, source_id=new_id(), amount=2000, origin_shift_id=sh.id)
    adapters.reversal(db, emp, reverses_id=out.entry_id, origin_shift_id=sh.id)
    expect_code(db, CashError.ALREADY_REVERSED, lambda: adapters.reversal(
        db, emp, reverses_id=out.entry_id, origin_shift_id=sh.id))


def test_35_reversal_must_be_opposite(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    orig = adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=new_id(), amount=1000, origin_shift_id=sh.id)
    # SAME direction reversal (IN'ni IN bilan) -> INVALID_REVERSAL
    cmd = PostingCommand(cash_account_id=till.id, source_type="SALE", source_id=new_id(), direction="IN",
                         category="ADJUSTMENT", amount=D("1000"), origin_shift_id=sh.id, reverses_id=orig.entry_id)
    expect_code(db, CashError.INVALID_REVERSAL, lambda: svc.post(db, emp, cmd))


def test_36_partial_refund_not_reverses_id(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 5000)
    r = adapters.cash_refund(db, emp, cash_account_id=till.id, source_id=new_id(), amount=1200, origin_shift_id=sh.id)
    e = db.get(CashLedgerEntry, r.entry_id)
    assert e.reverses_id is None and e.category == "REFUND"


# ── 37–40 security / integrity ───────────────────────────────────────────────
def test_37_cross_tenant_account(db, cashenv):
    emp = cashier(db, cashenv)
    co_b = Company(name="Tenant B P2", code="tenant_b_p2", currency="UZS"); db.add(co_b); db.flush()
    br_b = Branch(company_id=co_b.id, code="BP2", name="B"); db.add(br_b); db.commit()
    acc_b = CashAccount(tenant_id=co_b.id, branch_id=br_b.id, type="TILL", currency="UZS",
                        status="ACTIVE", created_at=cashenv.now)
    db.add(acc_b); db.commit()
    # emp (tenant A) B'ning hisobiga posting -> TENANT_MISMATCH
    expect_code(db, CashError.TENANT_MISMATCH, lambda: adapters.manual_cash_in(
        db, emp, cash_account_id=acc_b.id, source_id=new_id(), amount=100))


def test_38_unauthorized_manager_operation(db, cashenv):
    cash_emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    fund(db, cash_emp, till, sh, 5000)
    out = adapters.manual_cash_out(db, cash_emp, cash_account_id=till.id, source_id=new_id(), amount=1000, origin_shift_id=sh.id)
    # reopen — menejer+ ; kassir -> UNAUTHORIZED
    lifecycle.close_shift(db, cash_emp, shift_id=sh.id, counted_cash=4000)
    expect_code(db, CashError.UNAUTHORIZED_OPERATION, lambda: lifecycle.reopen_shift(db, cash_emp, shift_id=sh.id))
    assert out.entry_id is not None


def test_39_archived_account(db, cashenv):
    emp = cashier(db, cashenv)
    arch = make_account(db, cashenv, "TILL", status="ARCHIVED")
    expect_code(db, CashError.ACCOUNT_ARCHIVED, lambda: adapters.manual_cash_in(
        db, emp, cash_account_id=arch.id, source_id=new_id(), amount=100))


def test_40_currency_mismatch(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL", currency="UZS")
    sh = open_shift(db, cashenv, till)
    cmd = PostingCommand(cash_account_id=till.id, source_type="SALE", source_id=new_id(), direction="IN",
                         category="SALE", amount=D("100"), origin_shift_id=sh.id, currency="USD")
    expect_code(db, CashError.CURRENCY_MISMATCH, lambda: svc.post(db, emp, cmd))


# ── 41–44 reconciliation ─────────────────────────────────────────────────────
def test_41_late_sync_does_not_alter_snapshot(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 3000)
    rec = lifecycle.close_shift(db, emp, shift_id=sh.id, counted_cash=3000)
    snap_before = rec.ledger_balance_snapshot
    # LATE_SYNC posting
    adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=new_id(), amount=500,
                       origin_shift_id=sh.id, device_occurred_at=cashenv.now + timedelta(minutes=1))
    db.refresh(rec)
    assert rec.ledger_balance_snapshot == snap_before  # snapshot muzlagan


def test_42_off_shift_assignment(db, cashenv):
    emp = cashier(db, cashenv); mgr = manager(db, cashenv)
    till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    off = adapters.manual_cash_in(db, emp, cash_account_id=till.id, source_id=new_id(), amount=100)  # OFF_SHIFT (Case D)
    a = lifecycle.assign_off_shift(db, mgr, entry_id=off.entry_id, shift_id=sh.id)
    assert a.id is not None
    e = db.get(CashLedgerEntry, off.entry_id)
    assert e.shift_id is None and e.posting_kind == "OFF_SHIFT"  # entry o'zgarmagan


def test_43_safe_account_count(db, cashenv):
    emp = cashier(db, cashenv); safe = make_account(db, cashenv, "SAFE")
    adapters.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=new_id(), amount=70000)
    rec = lifecycle.reconcile_safe(db, emp, cash_account_id=safe.id, counted_cash=69000)
    assert rec.target_type == "ACCOUNT" and rec.ledger_balance_snapshot == D("70000.00")
    assert rec.difference == D("-1000.00")


def test_44_reopen_reclose(db, cashenv):
    mgr = manager(db, cashenv); till = make_account(db, cashenv, "TILL")
    sh = lifecycle.open_shift(db, mgr, cash_account_id=till.id, opening_amount=1000)
    r1 = lifecycle.close_shift(db, mgr, shift_id=sh.id, counted_cash=1000)
    reopened = lifecycle.reopen_shift(db, mgr, shift_id=sh.id)
    assert reopened.status == "OPEN"
    r2 = lifecycle.close_shift(db, mgr, shift_id=sh.id, counted_cash=1000)
    assert r2.seq == r1.seq + 1 and r2.is_current is True
    db.refresh(r1)
    assert r1.is_current is False  # 1:N — faqat oxirgisi current


# ── 45–47 concurrency ────────────────────────────────────────────────────────
def test_45_sale_plus_close(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)

    def do_sale(s):
        e = s.get(Employee, cashenv.employee_id)
        return adapters.cash_sale(s, e, cash_account_id=till.id, source_id=new_id(), amount=1000, origin_shift_id=sh.id)

    def do_close(s):
        e = s.get(Employee, cashenv.employee_id)
        return lifecycle.close_shift(s, e, shift_id=sh.id, counted_cash=0)

    ra, rb = _concurrent(cashenv.engine, do_sale, do_close)
    # (1) crash/deadlock YO'Q — ikkala natijadagi har qanday xato FAQAT domen (CashPostingError)
    #     bo'lishi shart; deadlock/IntegrityError (OperationalError va h.k.) bu assert'ni yiqitadi.
    for r in (ra, rb):
        assert (not isinstance(r, Exception)) or isinstance(r, CashPostingError), f"crash: {r!r}"
    # (2) смена lock serializatsiya qiladi -> sale HAR DOIM yakunlanadi (deadlock yo'q, lock tartibi
    #     account->shift; close faqat shift): ON_SHIFT (close'дан oldin) yoki LATE_SYNC (keyin).
    assert not isinstance(ra, Exception), f"sale kutilmaganda yiqildi: {ra!r}"
    assert ra.posting_kind in ("ON_SHIFT", "LATE_SYNC")
    # (3) close ham yakunlanadi
    assert not isinstance(rb, Exception), f"close kutilmaganda yiqildi: {rb!r}"
    # (4) yakuniy holat izchil: смена CLOSED
    db.expire_all()
    assert db.get(CashShift, sh.id).status == "CLOSED"


def test_46_transfer_plus_close(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    safe = make_account(db, cashenv, "SAFE"); fund(db, emp, till, sh, 5000)

    def do_transfer(s):
        e = s.get(Employee, cashenv.employee_id)
        return adapters.transfer(s, e, from_account_id=till.id, to_account_id=safe.id, amount=2000)

    def do_close(s):
        e = s.get(Employee, cashenv.employee_id)
        return lifecycle.close_shift(s, e, shift_id=sh.id, counted_cash=0)

    ra, rb = _concurrent(cashenv.engine, do_transfer, do_close)
    errs = [r for r in (ra, rb) if isinstance(r, Exception)]
    assert all(isinstance(e, CashPostingError) for e in errs)
    db.expire_all()
    assert bal(db, cashenv, safe) in (D("0.00"), D("2000.00"))


def test_47_concurrent_out_same_till(db, cashenv):
    emp = cashier(db, cashenv); till = make_account(db, cashenv, "TILL"); sh = open_shift(db, cashenv, till)
    fund(db, emp, till, sh, 10000)

    def out_a(s):
        e = s.get(Employee, cashenv.employee_id)
        return adapters.manual_cash_out(s, e, cash_account_id=till.id, source_id=new_id(), amount=7000, origin_shift_id=sh.id)

    def out_b(s):
        e = s.get(Employee, cashenv.employee_id)
        return adapters.manual_cash_out(s, e, cash_account_id=till.id, source_id=new_id(), amount=7000, origin_shift_id=sh.id)

    ra, rb = _concurrent(cashenv.engine, out_a, out_b)
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    errs = [r for r in (ra, rb) if isinstance(r, Exception)]
    # aynan bittasi o'tadi (balans lock serializatsiya qiladi), ikkinchisi INSUFFICIENT_CASH
    assert len(oks) == 1 and len(errs) == 1
    assert errs[0].code == CashError.INSUFFICIENT_CASH
    db.expire_all()
    assert bal(db, cashenv, till) == D("3000.00")


# ── concurrency helper ───────────────────────────────────────────────────────
def _concurrent(engine, fn_a, fn_b):
    barrier = threading.Barrier(2)
    out = {}

    def wrap(key, fn):
        s = Session(engine)
        try:
            barrier.wait(timeout=10)
            out[key] = fn(s)
        except Exception as e:  # noqa: BLE001
            out[key] = e
        finally:
            s.close()

    ta = threading.Thread(target=wrap, args=("a", fn_a))
    tb = threading.Thread(target=wrap, args=("b", fn_b))
    ta.start(); tb.start(); ta.join(); tb.join()
    return out.get("a"), out.get("b")
