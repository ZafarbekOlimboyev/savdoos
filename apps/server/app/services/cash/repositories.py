"""Cash quyi tizimi — o'qish repositorylari (Phase 1).

Bular keyingi CashPostingService uchun kerak bo'ladigan aniq so'rovlar:
- account resolution (§04)
- balans = Σ(IN) − Σ(OUT) — outflow guard (§07)
- ochiq смена — shift resolution (§05)
- смена kutilayotган naqd — Σ ON_SHIFT
- biznes-kalit qidiruv — idempotency (§10)
- reversal borligini tekshirish (§08)
- transfer leg'lari (§09)
- joriy reconciliation record (§20)

Hech qanday yozish/posting yo'q (keyingi faza).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.cash import (
    CashAccount,
    CashDirection,
    CashLedgerEntry,
    CashPostingKind,
    CashShift,
    CashShiftStatus,
    ReconciliationRecord,
)

_ZERO = Decimal("0")


# ── Account resolution (§04) ─────────────────────────────────────────────────
def get_account(session: Session, tenant_id: uuid.UUID, account_id: uuid.UUID) -> CashAccount | None:
    return session.get(CashAccount, account_id) if _same_tenant(
        session, tenant_id, account_id
    ) else None


def _same_tenant(session: Session, tenant_id: uuid.UUID, account_id: uuid.UUID) -> bool:
    acc = session.get(CashAccount, account_id)
    return acc is not None and acc.tenant_id == tenant_id


def find_account(
    session: Session, tenant_id: uuid.UUID, branch_id: uuid.UUID, type_: str, currency: str | None = None
) -> CashAccount | None:
    """Filial + tur (+ ixtiyoriy valyuta) bo'yicha hisobni topadi (aniq resolution)."""
    stmt = select(CashAccount).where(
        CashAccount.tenant_id == tenant_id,
        CashAccount.branch_id == branch_id,
        CashAccount.type == type_,
    )
    if currency is not None:
        stmt = stmt.where(CashAccount.currency == currency)
    return session.scalars(stmt).first()


def list_accounts(
    session: Session, tenant_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> list[CashAccount]:
    stmt = select(CashAccount).where(CashAccount.tenant_id == tenant_id)
    if branch_id is not None:
        stmt = stmt.where(CashAccount.branch_id == branch_id)
    return list(session.scalars(stmt))


# ── Balans / outflow guard (§07) ─────────────────────────────────────────────
def account_balance(session: Session, tenant_id: uuid.UUID, account_id: uuid.UUID) -> Decimal:
    """current_balance = Σ(IN) − Σ(OUT) — hisobning fizik naqd balansi."""
    signed = func.sum(
        case((CashLedgerEntry.direction == CashDirection.IN.value, CashLedgerEntry.amount),
             else_=-CashLedgerEntry.amount)
    )
    stmt = select(func.coalesce(signed, 0)).where(
        CashLedgerEntry.tenant_id == tenant_id,
        CashLedgerEntry.cash_account_id == account_id,
    )
    return Decimal(str(session.scalar(stmt) or 0))


def shift_expected_cash(session: Session, tenant_id: uuid.UUID, shift_id: uuid.UUID) -> Decimal:
    """expected = Σ(IN) − Σ(OUT) faqat ON_SHIFT leg'lar bo'yicha (смена yopishда)."""
    signed = func.sum(
        case((CashLedgerEntry.direction == CashDirection.IN.value, CashLedgerEntry.amount),
             else_=-CashLedgerEntry.amount)
    )
    stmt = select(func.coalesce(signed, 0)).where(
        CashLedgerEntry.tenant_id == tenant_id,
        CashLedgerEntry.shift_id == shift_id,
        CashLedgerEntry.posting_kind == CashPostingKind.ON_SHIFT.value,
    )
    return Decimal(str(session.scalar(stmt) or 0))


# ── Ochiq смена — shift resolution (§05) ─────────────────────────────────────
def open_shift_for_account(
    session: Session, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> CashShift | None:
    stmt = select(CashShift).where(
        CashShift.tenant_id == tenant_id,
        CashShift.cash_account_id == account_id,
        CashShift.status == CashShiftStatus.OPEN.value,
    )
    return session.scalars(stmt).first()


def get_shift(session: Session, tenant_id: uuid.UUID, shift_id: uuid.UUID) -> CashShift | None:
    sh = session.get(CashShift, shift_id)
    return sh if sh is not None and sh.tenant_id == tenant_id else None


# ── Idempotency — biznes-kalit (§10) ─────────────────────────────────────────
def get_entry_by_business_key(
    session: Session,
    tenant_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
    leg_index: int = 0,
) -> CashLedgerEntry | None:
    stmt = select(CashLedgerEntry).where(
        CashLedgerEntry.tenant_id == tenant_id,
        CashLedgerEntry.source_type == source_type,
        CashLedgerEntry.source_id == source_id,
        CashLedgerEntry.leg_index == leg_index,
    )
    return session.scalars(stmt).first()


# ── Reversal (§08) ───────────────────────────────────────────────────────────
def reversal_of(
    session: Session, tenant_id: uuid.UUID, original_id: uuid.UUID
) -> CashLedgerEntry | None:
    """Berilgan original entry'ning to'liq reversal'ini qaytaradi (bo'lsa)."""
    stmt = select(CashLedgerEntry).where(
        CashLedgerEntry.tenant_id == tenant_id,
        CashLedgerEntry.reverses_id == original_id,
    )
    return session.scalars(stmt).first()


def is_reversed(session: Session, tenant_id: uuid.UUID, original_id: uuid.UUID) -> bool:
    return reversal_of(session, tenant_id, original_id) is not None


# ── Transfer leg'lari (§09) ──────────────────────────────────────────────────
def transfer_legs(
    session: Session, tenant_id: uuid.UUID, group_id: uuid.UUID
) -> list[CashLedgerEntry]:
    stmt = select(CashLedgerEntry).where(
        CashLedgerEntry.tenant_id == tenant_id,
        CashLedgerEntry.transfer_group_id == group_id,
    )
    return list(session.scalars(stmt))


# ── Joriy reconciliation (§20) ───────────────────────────────────────────────
def current_reconciliation(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    shift_id: uuid.UUID | None = None,
    cash_account_id: uuid.UUID | None = None,
) -> ReconciliationRecord | None:
    if (shift_id is None) == (cash_account_id is None):
        raise ValueError("shift_id yoki cash_account_id — aynan bittasi berilishi kerak")
    stmt = select(ReconciliationRecord).where(
        ReconciliationRecord.tenant_id == tenant_id,
        ReconciliationRecord.is_current.is_(True),
    )
    if shift_id is not None:
        stmt = stmt.where(ReconciliationRecord.shift_id == shift_id)
    else:
        stmt = stmt.where(ReconciliationRecord.cash_account_id == cash_account_id)
    return session.scalars(stmt).first()
