# -*- coding: utf-8 -*-
"""Cash sxema constraint/trigger integratsion testlari (PostgreSQL, pgserver).

Har test o'zining hisob(lar)ini yaratadi (noyob) — testlar bir-biriga xalaqit bermaydi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text

from app.models.cash import (
    CashLedgerEntry,
    CashLedgerException,
    CashShift,
    NegativeCashApproval,
    ReconciliationAssignment,
    ReconciliationRecord,
)
from _factory import (  # noqa: E402
    assert_rejects,
    build_entry,
    make_account,
    new_id,
    open_shift,
    post_entry,
)


# ── happy path ───────────────────────────────────────────────────────────────
def test_normal_sale_on_open_shift_accepts(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = post_entry(db, cashenv, till, shift=sh)
    assert e.id is not None
    assert e.posting_kind == "ON_SHIFT"


# ── currency / branch consistency ────────────────────────────────────────────
def test_currency_mismatch_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL", currency="UZS")
    sh = open_shift(db, cashenv, till)
    assert_rejects(db, lambda: post_entry(db, cashenv, till, shift=sh, currency="USD"),
                   "cle_acct_currency")


def test_branch_mismatch_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = build_entry(cashenv, till, shift=sh, branch_id=new_id())
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_acct_branch")


# ── TILL/SAFE + shift semantics ──────────────────────────────────────────────
def test_shift_on_safe_rejects(db, cashenv):
    safe = make_account(db, cashenv, "SAFE")
    sh = CashShift(tenant_id=cashenv.company_id, cash_account_id=safe.id, branch_id=safe.branch_id,
                   account_type="SAFE", status="OPEN", opened_at=cashenv.now,
                   opened_by=cashenv.employee_id, version=1)
    db.add(sh)
    # sh_type_till CHECK yoki sh_acct_type_fk
    assert_rejects(db, lambda: db.commit())


def test_one_open_shift_per_till(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    open_shift(db, cashenv, till)
    sh2 = CashShift(tenant_id=cashenv.company_id, cash_account_id=till.id, branch_id=till.branch_id,
                    account_type="TILL", status="OPEN", opened_at=cashenv.now,
                    opened_by=cashenv.employee_id, version=1)
    db.add(sh2)
    assert_rejects(db, lambda: db.commit(), "sh_one_open")


def test_on_shift_requires_shift(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    e = build_entry(cashenv, till, posting_kind="ON_SHIFT", shift_id=None)
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_posting_shift")


def test_off_shift_forbids_shift(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = build_entry(cashenv, till, shift=sh, posting_kind="OFF_SHIFT")
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_posting_shift")


def test_safe_leg_cannot_borrow_till_shift(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    safe = make_account(db, cashenv, "SAFE")
    sh = open_shift(db, cashenv, till)
    e = build_entry(cashenv, safe, posting_kind="ON_SHIFT", shift_id=sh.id)
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_shift_fk")


# ── tenant isolation ─────────────────────────────────────────────────────────
def test_tenant_isolation_cross_tenant_account(db, cashenv):
    """Tenant A entry'si Tenant B'ning hisobiга murojaat qila OLMASLIGI.

    tenant_id = A (HAQIQIY kompaniya, base FK companies'ga o'tadi), lekin hisob B'niki —
    shu sabab FAQAT tenant-scoped composite FK (tenant_id, cash_account_id, ...) rad etadi.
    Bu composite FK'lar olib tashlansa test ACCEPT bo'lardi — ya'ni izolyatsiyani chinakam
    tekshiradi (avvalgi random-UUID varianti base companies FK'ga tushib vacuous o'tardi)."""
    from app.models.cash import CashAccount
    from app.models.org import Branch, Company

    # Tenant B — o'z kompaniyasi, filiali va TILL hisobi
    co_b = Company(name="Tenant B", code="tenant_b_iso", currency="UZS")
    db.add(co_b)
    db.flush()
    br_b = Branch(company_id=co_b.id, code="BISO", name="B filial")
    db.add(br_b)
    db.commit()
    acc_b = CashAccount(tenant_id=co_b.id, branch_id=br_b.id, type="TILL", currency="UZS",
                        status="ACTIVE", created_at=cashenv.now)
    db.add(acc_b)
    db.commit()

    # Tenant A (cashenv.company_id — haqiqiy) entry'si B'ning hisobiга ishora qiladi.
    # tenant_id -> companies(A) base FK o'tadi; ammo (tenant_id=A, cash_account_id=B) uchun
    # cash_accounts'да satr yo'q -> cle_acct_* composite FK rad etadi.
    e = build_entry(cashenv, acc_b)   # tenant_id=A, cash_account_id=B's account
    assert e.tenant_id == cashenv.company_id and e.cash_account_id == acc_b.id
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_acct")


# ── immutable ledger ─────────────────────────────────────────────────────────
def test_ledger_update_blocked(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = post_entry(db, cashenv, till, shift=sh)
    assert_rejects(
        db, lambda: db.execute(text("update cash.cash_ledger_entries set amount='2' where id=:i"),
                               {"i": str(e.id)}) or db.commit(), "append-only")


def test_ledger_delete_blocked(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = post_entry(db, cashenv, till, shift=sh)
    assert_rejects(
        db, lambda: db.execute(text("delete from cash.cash_ledger_entries where id=:i"),
                               {"i": str(e.id)}) or db.commit(), "append-only")


def test_ledger_truncate_blocked(db, cashenv):
    assert_rejects(
        db, lambda: db.execute(text("truncate table cash.cash_ledger_entries cascade")) or db.commit(),
        "not permitted")


def test_audit_truncate_blocked(db, cashenv):
    assert_rejects(
        db, lambda: db.execute(text("truncate table cash.audit_logs")) or db.commit(),
        "not permitted")


# ── business uniqueness / idempotency ────────────────────────────────────────
def test_duplicate_business_key_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    sid = new_id()
    post_entry(db, cashenv, till, shift=sh, source_id=sid, source_type="SALE", leg_index=0)
    dup = build_entry(cashenv, till, shift=sh, source_id=sid, source_type="SALE", leg_index=0)
    db.add(dup)
    assert_rejects(db, lambda: db.commit(), "cle_uq_business")


# ── reversal uniqueness ──────────────────────────────────────────────────────
def test_full_reversal_unique(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    orig = post_entry(db, cashenv, till, shift=sh, direction="OUT", category="EXPENSE",
                      source_type="CASH_OP")
    post_entry(db, cashenv, till, shift=sh, reverses_id=orig.id, direction="IN",
               category="ADJUSTMENT", source_type="CASH_OP")
    second = build_entry(cashenv, till, shift=sh, reverses_id=orig.id, direction="IN",
                         category="ADJUSTMENT", source_type="CASH_OP")
    db.add(second)
    assert_rejects(db, lambda: db.commit(), "cle_uq_reverses")


def test_self_reverse_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = build_entry(cashenv, till, shift=sh)
    eid = uuid.uuid4()
    e.id = eid
    e.reverses_id = eid   # self-reference: cle_no_self_rev CHECK reject
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_no_self_rev")


# ── reconstruction metadata ──────────────────────────────────────────────────
def test_reconstruction_requires_both_fields(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    # reason bor, source_ref yo'q -> reject
    e = build_entry(cashenv, till, shift=sh, provenance="RECONSTRUCTION",
                    reconstruction_reason="r")
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_recon_prov")


def test_reconstruction_with_both_accepts(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = post_entry(db, cashenv, till, shift=sh, provenance="RECONSTRUCTION",
                   reconstruction_reason="cash purchase drawer deduction",
                   reconstruction_source_ref="purchase:123")
    assert e.provenance == "RECONSTRUCTION"


def test_normal_with_reason_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    e = build_entry(cashenv, till, shift=sh, provenance="NORMAL", reconstruction_reason="x")
    db.add(e)
    assert_rejects(db, lambda: db.commit(), "cle_recon_prov")


# ── transfer pairing (deferred, COMMIT-time) ─────────────────────────────────
def _transfer_header(db, cashenv, frm, to, amount="500.00"):
    from app.models.cash import CashTransfer
    h = CashTransfer(tenant_id=cashenv.company_id, from_account_id=frm.id, to_account_id=to.id,
                     amount=Decimal(amount), currency=frm.currency, actor_id=cashenv.employee_id,
                     occurred_at=cashenv.now, created_at=cashenv.now)
    db.add(h)
    return h


def test_transfer_incomplete_rejects_at_commit(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    safe = make_account(db, cashenv, "SAFE")
    h = _transfer_header(db, cashenv, till, safe)
    db.flush()
    sid = new_id()
    out = build_entry(cashenv, till, posting_kind="OFF_SHIFT", direction="OUT", category="TRANSFER",
                      source_type="TRANSFER", source_id=sid, leg_index=0,
                      transfer_group_id=h.id, amount=Decimal("500.00"))
    db.add(out)
    assert_rejects(db, lambda: db.commit(), "exactly one OUT and one IN")


def test_transfer_valid_pair_commits(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    safe = make_account(db, cashenv, "SAFE")
    h = _transfer_header(db, cashenv, till, safe, amount="700.00")
    db.flush()
    sid = new_id()
    out = build_entry(cashenv, till, posting_kind="OFF_SHIFT", direction="OUT", category="TRANSFER",
                      source_type="TRANSFER", source_id=sid, leg_index=0,
                      transfer_group_id=h.id, amount=Decimal("700.00"))
    inn = build_entry(cashenv, safe, posting_kind="OFF_SHIFT", direction="IN", category="TRANSFER",
                      source_type="TRANSFER", source_id=sid, leg_index=1,
                      transfer_group_id=h.id, amount=Decimal("700.00"))
    db.add_all([out, inn])
    db.commit()
    assert out.id is not None and inn.id is not None


def test_bank_deposit_single_out_accepts(db, cashenv):
    safe = make_account(db, cashenv, "SAFE")
    e = post_entry(db, cashenv, safe, posting_kind="OFF_SHIFT", direction="OUT",
                   category="BANK_DEPOSIT", source_type="CASH_OP")
    assert e.category == "BANK_DEPOSIT" and e.transfer_group_id is None


# ── SAFE reconciliation (§CF-D4) ─────────────────────────────────────────────
def test_account_reconciliation_on_safe_accepts(db, cashenv):
    safe = make_account(db, cashenv, "SAFE")
    r = ReconciliationRecord(tenant_id=cashenv.company_id, target_type="ACCOUNT",
                             cash_account_id=safe.id, account_type="SAFE", seq=1, is_current=True,
                             ledger_balance_snapshot=Decimal("0.00"), state="PENDING",
                             created_at=cashenv.now)
    db.add(r)
    db.commit()
    assert r.id is not None


def test_account_reconciliation_on_till_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    r = ReconciliationRecord(tenant_id=cashenv.company_id, target_type="ACCOUNT",
                             cash_account_id=till.id, account_type="TILL", seq=1, is_current=True,
                             ledger_balance_snapshot=Decimal("0.00"), state="PENDING",
                             created_at=cashenv.now)
    db.add(r)
    assert_rejects(db, lambda: db.commit(), "rr_account_target_safe")


def test_reconciliation_one_current_per_target(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    r1 = ReconciliationRecord(tenant_id=cashenv.company_id, target_type="SHIFT", shift_id=sh.id,
                              seq=1, is_current=True, ledger_balance_snapshot=Decimal("0.00"),
                              state="PENDING", created_at=cashenv.now)
    db.add(r1)
    db.commit()
    r2 = ReconciliationRecord(tenant_id=cashenv.company_id, target_type="SHIFT", shift_id=sh.id,
                              seq=2, is_current=True, ledger_balance_snapshot=Decimal("0.00"),
                              state="PENDING", created_at=cashenv.now)
    db.add(r2)
    assert_rejects(db, lambda: db.commit(), "rr_current_shift")


# ── Case-B exception ─────────────────────────────────────────────────────────
def test_case_b_exception_accepts_and_unique_open(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    e = post_entry(db, cashenv, till, posting_kind="OFF_SHIFT", direction="IN", category="CASH_IN",
                   source_type="CASH_OP")
    x1 = CashLedgerException(tenant_id=cashenv.company_id, entry_id=e.id,
                             kind="TIMESTAMP_OUT_OF_WINDOW", state="OPEN", created_at=cashenv.now)
    db.add(x1)
    db.commit()
    assert x1.id is not None
    x2 = CashLedgerException(tenant_id=cashenv.company_id, entry_id=e.id,
                             kind="TIMESTAMP_OUT_OF_WINDOW", state="OPEN", created_at=cashenv.now)
    db.add(x2)
    assert_rejects(db, lambda: db.commit(), "cx_one_open_per_kind")


# ── OFF_SHIFT assignment (§CF-D2) ────────────────────────────────────────────
def test_off_shift_assignment_same_account_accepts(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    off = post_entry(db, cashenv, till, posting_kind="OFF_SHIFT", direction="IN", category="CASH_IN",
                     source_type="CASH_OP")
    a = ReconciliationAssignment(tenant_id=cashenv.company_id, entry_id=off.id,
                                 assigned_shift_id=sh.id, cash_account_id=till.id,
                                 actor_id=cashenv.employee_id, assigned_at=cashenv.now)
    db.add(a)
    db.commit()
    assert a.id is not None


def test_off_shift_assignment_cross_account_rejects(db, cashenv):
    till_a = make_account(db, cashenv, "TILL")
    till_b = make_account(db, cashenv, "TILL")
    sh_b = open_shift(db, cashenv, till_b)
    off = post_entry(db, cashenv, till_a, posting_kind="OFF_SHIFT", direction="IN",
                     category="CASH_IN", source_type="CASH_OP")
    # entry(A) -> shift(B), account=A: shift/account FK mos kelmaydi
    a = ReconciliationAssignment(tenant_id=cashenv.company_id, entry_id=off.id,
                                 assigned_shift_id=sh_b.id, cash_account_id=till_a.id,
                                 assigned_at=cashenv.now)
    db.add(a)
    assert_rejects(db, lambda: db.commit(), "ra_shift_account_fk")


def test_assignment_on_on_shift_entry_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    on = post_entry(db, cashenv, till, shift=sh)  # ON_SHIFT
    a = ReconciliationAssignment(tenant_id=cashenv.company_id, entry_id=on.id,
                                 assigned_shift_id=sh.id, cash_account_id=till.id,
                                 assigned_at=cashenv.now)
    db.add(a)
    assert_rejects(db, lambda: db.commit(), "OFF_SHIFT")


# ── negative cash approval (§CF-D5) ──────────────────────────────────────────
def _approval(db, cashenv, entry, account, direction="OUT", account_type="TILL"):
    return NegativeCashApproval(
        tenant_id=cashenv.company_id, entry_id=entry.id, cash_account_id=account.id,
        direction=direction, account_type=account_type, approver_id=cashenv.employee_id,
        reason="manager override", amount=Decimal("10.00"),
        till_balance_before=Decimal("5.00"), till_balance_after=Decimal("-5.00"),
        authorized_at=cashenv.now)


def test_negative_approval_on_out_till_accepts(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    out = post_entry(db, cashenv, till, shift=sh, direction="OUT", category="EXPENSE",
                     source_type="CASH_OP")
    db.add(_approval(db, cashenv, out, till))
    db.commit()


def test_negative_approval_on_in_rejects(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    inn = post_entry(db, cashenv, till, shift=sh, direction="IN", category="SALE")
    db.add(_approval(db, cashenv, inn, till))  # entry IN, approval claims OUT -> FK mismatch
    assert_rejects(db, lambda: db.commit(), "nca_entry_dirtype_fk")


def test_negative_approval_on_safe_rejects(db, cashenv):
    safe = make_account(db, cashenv, "SAFE")
    out = post_entry(db, cashenv, safe, posting_kind="OFF_SHIFT", direction="OUT",
                     category="EXPENSE", source_type="CASH_OP")
    # approval claims TILL (nca_scope), but entry is SAFE -> FK/scope mismatch
    db.add(_approval(db, cashenv, out, safe, direction="OUT", account_type="TILL"))
    assert_rejects(db, lambda: db.commit())
