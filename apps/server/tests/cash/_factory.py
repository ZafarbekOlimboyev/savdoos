# -*- coding: utf-8 -*-
"""Cash testlari uchun yordamchilar — yaroqli qatorlarni quradi."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.cash import CashAccount, CashLedgerEntry, CashShift


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def make_account(db, env, type_, *, currency="UZS", status="ACTIVE", branch_id=None) -> CashAccount:
    a = CashAccount(
        tenant_id=env.company_id,
        branch_id=branch_id or env.branch_id,
        type=type_,
        currency=currency,
        status=status,
        created_at=env.now,
    )
    db.add(a)
    db.commit()
    return a


def open_shift(db, env, account, *, status="OPEN") -> CashShift:
    sh = CashShift(
        tenant_id=env.company_id,
        cash_account_id=account.id,
        branch_id=account.branch_id,
        account_type=account.type,
        status=status,
        opened_at=env.now,
        opened_by=env.employee_id,
        version=1,
    )
    db.add(sh)
    db.commit()
    return sh


def build_entry(env, account, *, shift=None, **over) -> CashLedgerEntry:
    d = dict(
        tenant_id=env.company_id,
        cash_account_id=account.id,
        branch_id=account.branch_id,
        account_type=account.type,
        shift_id=(shift.id if shift is not None else None),
        posting_kind=("ON_SHIFT" if shift is not None else "OFF_SHIFT"),
        source_type="SALE",
        source_id=uuid.uuid4(),
        leg_index=0,
        direction="IN",
        category="SALE",
        amount=Decimal("1000.00"),
        currency=account.currency,
        device_occurred_at=env.now,
        server_received_at=env.now,
        recorded_at=env.now,
        actor_id=env.employee_id,
        idempotency_key=str(uuid.uuid4()),
        provenance="NORMAL",
    )
    d.update(over)
    return CashLedgerEntry(**d)


def post_entry(db, env, account, *, shift=None, **over) -> CashLedgerEntry:
    e = build_entry(env, account, shift=shift, **over)
    db.add(e)
    db.commit()
    return e


def assert_rejects(db, action, needle: str | None = None):
    """action()' constraint/trigger bilan rad etilishini kutadi; sessiyani tozalaydi."""
    with pytest.raises(Exception) as ei:
        action()
    db.rollback()
    if needle is not None:
        assert needle.lower() in str(ei.value).lower(), f"expected '{needle}' in: {ei.value}"
    return ei.value
