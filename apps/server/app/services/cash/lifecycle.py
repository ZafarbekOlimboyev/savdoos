"""Cash смена hayot-tsikli + reconciliation operatsiyalari (posting bilan bir servis qatlami).

open/close/reopen смена, OFF_SHIFT assignment, SAFE account count. Hammasi BITTA
tranzaksiyada; смена qatori FOR UPDATE bilan lock qilinadi (sale-vs-close race).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cash import (
    CashAccount,
    CashShift,
    CashShiftStatus,
    ReconciliationAssignment,
    ReconciliationRecord,
)
from app.services.cash import repositories as repo
from app.services.cash.commands import PostingResult
from app.services.cash.errors import CashError, CashPostingError
from app.services.cash.posting import _D, _is_manager_plus, _now, cash_posting_service


def open_shift(db: Session, emp, *, cash_account_id, opening_amount=0, origin_device_id=None,
               device_occurred_at=None) -> CashShift:
    """TILL smenasini ochadi (+ ochilish floatи bo'lsa IN·OPENING). Bitta ochiq смена kafolati DDL'да."""
    tenant = getattr(emp, "company_id", None)
    acct = db.get(CashAccount, cash_account_id)
    if acct is None or acct.tenant_id != tenant:
        raise CashPostingError(CashError.ACCOUNT_NOT_FOUND, "Hisob topilmadi")
    if acct.type != "TILL":
        raise CashPostingError(CashError.INVALID_ACCOUNT_TYPE, "Faqat TILL smena ochadi")
    now = _now()
    sh = CashShift(tenant_id=tenant, cash_account_id=acct.id, branch_id=acct.branch_id,
                   account_type="TILL", status=CashShiftStatus.OPEN.value, opened_at=now,
                   opened_by=getattr(emp, "id", None), version=1)
    db.add(sh)
    db.commit()
    if _D(opening_amount) > 0:
        from app.services.cash import adapters
        adapters.opening_float(db, emp, cash_account_id=acct.id, source_id=uuid.uuid4(),
                               amount=opening_amount, origin_shift_id=sh.id,
                               device_occurred_at=device_occurred_at or now,
                               origin_device_id=origin_device_id)
    db.refresh(sh)
    return sh


def close_shift(db: Session, emp, *, shift_id, counted_cash) -> ReconciliationRecord:
    """Смена yopadi + reconciliation snapshot yozadi (snapshot = Σ ON_SHIFT expected)."""
    tenant = getattr(emp, "company_id", None)
    sh = db.execute(select(CashShift).where(
        CashShift.tenant_id == tenant, CashShift.id == shift_id
    ).with_for_update()).scalar_one_or_none()
    if sh is None:
        raise CashPostingError(CashError.SHIFT_NOT_FOUND, "Смена topilmadi")
    if sh.status == CashShiftStatus.CLOSED.value:
        raise CashPostingError(CashError.SHIFT_NOT_OPEN, "Смена allaqachon yopilgan")
    expected = repo.shift_expected_cash(db, tenant, sh.id)
    diff = _D(counted_cash) - expected
    now = _now()
    sh.status = CashShiftStatus.CLOSED.value
    sh.closed_at = now
    sh.closed_by = getattr(emp, "id", None)
    rec = _new_recon(db, tenant, shift_id=sh.id, snapshot=expected, counted=_D(counted_cash),
                     diff=diff, now=now)
    db.add(rec)
    db.commit()
    return rec


def reopen_shift(db: Session, emp, *, shift_id) -> CashShift:
    """Yopilgan smenani qayta ochadi — menejer+ (§18). 1:N reconciliation (yangi seq keyin)."""
    if not _is_manager_plus(emp):
        raise CashPostingError(CashError.UNAUTHORIZED_OPERATION, "Reopen uchun menejer+ kerak")
    tenant = getattr(emp, "company_id", None)
    sh = db.execute(select(CashShift).where(
        CashShift.tenant_id == tenant, CashShift.id == shift_id
    ).with_for_update()).scalar_one_or_none()
    if sh is None:
        raise CashPostingError(CashError.SHIFT_NOT_FOUND, "Смена topilmadi")
    if sh.status != CashShiftStatus.CLOSED.value:
        raise CashPostingError(CashError.SHIFT_NOT_OPEN, "Faqat yopilgan смена qayta ochiladi")
    sh.status = CashShiftStatus.OPEN.value
    sh.closed_at = None
    sh.closed_by = None
    sh.version = (sh.version or 1) + 1
    db.commit()
    db.refresh(sh)
    return sh


def assign_off_shift(db: Session, emp, *, entry_id, shift_id, reason=None) -> ReconciliationAssignment:
    """OFF_SHIFT leg'ni bir hisobning smenasiga biriktiradi — menejer+ (§18).

    Entry o'zgarmaydi (shift_id NULL qoladi). DDL: entry OFF_SHIFT bo'lishi + shift/entry
    bir hisobда bo'lishi majbur."""
    if not _is_manager_plus(emp):
        raise CashPostingError(CashError.UNAUTHORIZED_OPERATION, "Assignment uchun menejer+ kerak")
    tenant = getattr(emp, "company_id", None)
    entry = repo.get_entry_by_business_key  # noqa: F841 (kalit — quyida to'g'ridan-to'g'ri get)
    from app.models.cash import CashLedgerEntry
    e = db.get(CashLedgerEntry, entry_id)
    if e is None or e.tenant_id != tenant:
        raise CashPostingError(CashError.INVALID_INPUT, "Entry topilmadi")
    a = ReconciliationAssignment(tenant_id=tenant, entry_id=e.id, assigned_shift_id=shift_id,
                                 cash_account_id=e.cash_account_id, actor_id=getattr(emp, "id", None),
                                 reason=reason, assigned_at=_now())
    db.add(a)
    db.commit()
    return a


def reconcile_safe(db: Session, emp, *, cash_account_id, counted_cash) -> ReconciliationRecord:
    """SAFE hisob sanog'i — ACCOUNT-target reconciliation (SAFE-only, DDL)."""
    tenant = getattr(emp, "company_id", None)
    acct = db.get(CashAccount, cash_account_id)
    if acct is None or acct.tenant_id != tenant:
        raise CashPostingError(CashError.ACCOUNT_NOT_FOUND, "Hisob topilmadi")
    if acct.type != "SAFE":
        raise CashPostingError(CashError.INVALID_ACCOUNT_TYPE, "ACCOUNT-count faqat SAFE uchun")
    snapshot = repo.account_balance(db, tenant, acct.id)
    now = _now()
    rec = _new_recon(db, tenant, cash_account_id=acct.id, account_type="SAFE", snapshot=snapshot,
                     counted=_D(counted_cash), diff=_D(counted_cash) - snapshot, now=now)
    db.add(rec)
    db.commit()
    return rec


# ── ichki ────────────────────────────────────────────────────────────────────
def _new_recon(db, tenant, *, shift_id=None, cash_account_id=None, account_type=None,
               snapshot, counted, diff, now) -> ReconciliationRecord:
    # oldingi is_current -> False, yangi seq
    if shift_id is not None:
        col_filter = ReconciliationRecord.shift_id == shift_id
        target_type = "SHIFT"
    else:
        col_filter = ReconciliationRecord.cash_account_id == cash_account_id
        target_type = "ACCOUNT"
    prior = db.execute(select(ReconciliationRecord).where(
        ReconciliationRecord.tenant_id == tenant, col_filter,
        ReconciliationRecord.is_current.is_(True)
    ).with_for_update()).scalars().all()
    for p in prior:
        p.is_current = False
    db.flush()
    max_seq = db.execute(select(func.coalesce(func.max(ReconciliationRecord.seq), 0)).where(
        ReconciliationRecord.tenant_id == tenant, col_filter
    )).scalar() or 0
    return ReconciliationRecord(
        tenant_id=tenant, target_type=target_type, shift_id=shift_id,
        cash_account_id=cash_account_id, account_type=account_type, seq=max_seq + 1,
        is_current=True, ledger_balance_snapshot=snapshot, counted_cash=counted,
        difference=diff, state="PENDING", created_at=now,
    )
