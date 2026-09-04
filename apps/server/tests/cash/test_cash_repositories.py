# -*- coding: utf-8 -*-
"""Cash o'qish repositorylari — integratsion testlar."""
from __future__ import annotations

from decimal import Decimal

from app.services.cash import repositories as repo
from _factory import build_entry, make_account, new_id, open_shift, post_entry  # noqa: E402


def test_account_balance_in_minus_out(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    post_entry(db, cashenv, till, shift=sh, direction="IN", category="SALE", amount=Decimal("1000"))
    post_entry(db, cashenv, till, shift=sh, direction="IN", category="CASH_IN",
               source_type="CASH_OP", amount=Decimal("500"))
    post_entry(db, cashenv, till, shift=sh, direction="OUT", category="EXPENSE",
               source_type="CASH_OP", amount=Decimal("300"))
    bal = repo.account_balance(db, cashenv.company_id, till.id)
    assert bal == Decimal("1200.00")


def test_shift_expected_cash_on_shift_only(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    post_entry(db, cashenv, till, shift=sh, direction="IN", category="SALE", amount=Decimal("800"))
    # OFF_SHIFT leg — expected'ga kirmasligi kerak
    post_entry(db, cashenv, till, posting_kind="OFF_SHIFT", direction="IN", category="CASH_IN",
               source_type="CASH_OP", amount=Decimal("999"))
    exp = repo.shift_expected_cash(db, cashenv.company_id, sh.id)
    assert exp == Decimal("800.00")


def test_open_shift_lookup(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    found = repo.open_shift_for_account(db, cashenv.company_id, till.id)
    assert found is not None and found.id == sh.id


def test_open_shift_none_when_no_open(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    assert repo.open_shift_for_account(db, cashenv.company_id, till.id) is None


def test_business_key_lookup(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    sid = new_id()
    e = post_entry(db, cashenv, till, shift=sh, source_type="SALE", source_id=sid, leg_index=0)
    found = repo.get_entry_by_business_key(db, cashenv.company_id, "SALE", sid, 0)
    assert found is not None and found.id == e.id
    assert repo.get_entry_by_business_key(db, cashenv.company_id, "SALE", new_id(), 0) is None


def test_reversal_lookup(db, cashenv):
    till = make_account(db, cashenv, "TILL")
    sh = open_shift(db, cashenv, till)
    orig = post_entry(db, cashenv, till, shift=sh, direction="OUT", category="EXPENSE",
                      source_type="CASH_OP")
    assert repo.is_reversed(db, cashenv.company_id, orig.id) is False
    rev = post_entry(db, cashenv, till, shift=sh, reverses_id=orig.id, direction="IN",
                     category="ADJUSTMENT", source_type="CASH_OP")
    assert repo.is_reversed(db, cashenv.company_id, orig.id) is True
    assert repo.reversal_of(db, cashenv.company_id, orig.id).id == rev.id


def test_transfer_legs_lookup(db, cashenv):
    from app.models.cash import CashTransfer
    till = make_account(db, cashenv, "TILL")
    safe = make_account(db, cashenv, "SAFE")
    h = CashTransfer(tenant_id=cashenv.company_id, from_account_id=till.id, to_account_id=safe.id,
                     amount=Decimal("700.00"), currency="UZS", occurred_at=cashenv.now,
                     created_at=cashenv.now)
    db.add(h)
    db.flush()
    sid = new_id()
    # ikkala leg BITTA commit'da — deferred pairing trigger COMMIT'da tekshiradi
    out = build_entry(cashenv, till, posting_kind="OFF_SHIFT", direction="OUT", category="TRANSFER",
                      source_type="TRANSFER", source_id=sid, leg_index=0, transfer_group_id=h.id,
                      amount=Decimal("700.00"))
    inn = build_entry(cashenv, safe, posting_kind="OFF_SHIFT", direction="IN", category="TRANSFER",
                      source_type="TRANSFER", source_id=sid, leg_index=1, transfer_group_id=h.id,
                      amount=Decimal("700.00"))
    db.add_all([out, inn])
    db.commit()
    legs = repo.transfer_legs(db, cashenv.company_id, h.id)
    assert len(legs) == 2
    assert {leg.direction for leg in legs} == {"IN", "OUT"}


def test_find_account_by_branch_type(db, cashenv):
    # yangi filial — bu filialда aynan bitta TILL bo'lsin (boshqa testlar seed filialида
    # ko'p TILL yaratgan; resolution noaniq bo'lmasin)
    from app.models.org import Branch
    br = Branch(company_id=cashenv.company_id, code="BRX", name="Filial X")
    db.add(br)
    db.commit()
    till = make_account(db, cashenv, "TILL", branch_id=br.id)
    found = repo.find_account(db, cashenv.company_id, br.id, "TILL", currency="UZS")
    assert found is not None and found.id == till.id


def test_current_reconciliation(db, cashenv):
    from app.models.cash import ReconciliationRecord
    safe = make_account(db, cashenv, "SAFE")
    r = ReconciliationRecord(tenant_id=cashenv.company_id, target_type="ACCOUNT",
                             cash_account_id=safe.id, account_type="SAFE", seq=1, is_current=True,
                             ledger_balance_snapshot=Decimal("0.00"), state="PENDING",
                             created_at=cashenv.now)
    db.add(r)
    db.commit()
    cur = repo.current_reconciliation(db, cashenv.company_id, cash_account_id=safe.id)
    assert cur is not None and cur.id == r.id
