# -*- coding: utf-8 -*-
"""CUSTODY + INKASSA (TILL->SAFE) + YOPILGAN SMENA REPLAY (real PostgreSQL).

§1 KONTRAKT: har fizik naqd mutatsiyaning AYNAN fizik custody hisobi bor (TILL yoki SAFE).
§4 INKASSA: TILL -> SAFE JUFT transfer — naqd kompaniya custody'sidan CHIQMAYDI.
§9 YOPILGAN SMENA: oddiy POS replay'i yopilgan/yarashtirilgan smenani O'ZGARTIRMAYDI.

K 2 ta ledger qatori     L TILL OUT X      M SAFE IN X      N bir xil transfer_group
O kompaniya jami fizik naqdi TILL->SAFE dan O'ZGARMAYDI
P noto'g'ri manzil turi RAD   Q safe_id yo'q -> RAD   R takroriy so'rov idempotent
S SAFE->BANK_DEPOSIT jami naqdni AYNAN BIR MARTA kamaytiradi
F/G/H noto'g'ri filial / tenant / ARCHIVED custody RAD    I/J fallback YO'Q
Z/AA/AB yopilgan smena replay RAD    AC/AD ledger va reconciliation O'ZGARMAYDI    AE auto-reopen YO'Q
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1 import cashops as cashops_api
from app.api.v1 import shifts as shifts_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.models.shifts import Shift
from app.services.cash import cutover_guard as CG
from app.services.cash import repositories as repo
from app.services.cash import retrofit as _cr
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _acct(db, co, br, typ, status="ACTIVE", cur="UZS"):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type=typ, currency=cur, status=status,
                    label=(_ti.till_label("T-" + _hex(), None) if typ == "TILL"
                           else _ti.safe_label("SAFE-" + _hex())),
                    created_at=_now())
    db.add(a); db.flush(); return a


def _tenant(db, cashenv):
    # FRESH kompaniya: shared cashenv company'ni ishlatsak, boshqa testning T0 Setting'i va
    # TRANSFER oyoqlari bu testga SIZIB kirardi (shared-DB scoping).
    co = Company(name="CU" + _hex(), code="cu" + _hex(), currency="UZS"); db.add(co); db.flush()
    br = Branch(company_id=co.id, code="C" + _hex(), name="F", is_active=True); db.add(br); db.flush()
    emp = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(emp); db.flush(); db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = _acct(db, co, br, "TILL"); safe = _acct(db, co, br, "SAFE")
    db.commit()
    return co, br, emp, till, safe


def _open_shift(db, br, emp, till, opening="100000"):
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(hours=2),
               opening_cash=Decimal(opening), status=ShiftStatus.open, till_id=till.id)
    db.add(sh); db.commit(); return sh


def _bal(db, co, acc):
    return repo.account_balance(db, co.id, acc.id)


def _collect(db, emp, sh, amount, safe_id, cu=None):
    return shifts_api.add_cash_movement(sh.id, shifts_api.CashMove(
        type="collection", amount=amount, destination_safe_id=safe_id, client_uuid=cu), emp, db)


# ═══ K/L/M/N/O) INKASSA = TILL -> SAFE JUFT TRANSFER ═══════════════════════
def test_KLMNO_collection_is_a_paired_till_to_safe_transfer(db, cashenv):
    co, br, emp, till, safe = _tenant(db, cashenv)
    sh = _open_shift(db, br, emp, till)
    _cr.on_shift_open(db, emp, branch_id=br.id, legacy_shift_id=sh.id,
                      opening_cash=Decimal("100000"), terminal_id=None)
    db.commit()
    total_before = _bal(db, co, till) + _bal(db, co, safe)

    _collect(db, emp, sh, 30000, safe.id)

    legs = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "TRANSFER").all()
    assert len(legs) == 2                                        # K: AYNAN 2 qator
    out = [x for x in legs if x.direction == "OUT"][0]
    inn = [x for x in legs if x.direction == "IN"][0]
    assert out.cash_account_id == till.id and out.amount == Decimal("30000.00")   # L
    assert inn.cash_account_id == safe.id and inn.amount == Decimal("30000.00")   # M
    assert out.transfer_group_id is not None and out.transfer_group_id == inn.transfer_group_id  # N
    # O: kompaniya jami fizik naqdi O'ZGARMAYDI (pul ichkarida ko'chdi)
    assert _bal(db, co, till) + _bal(db, co, safe) == total_before
    assert _bal(db, co, till) == Decimal("70000.00") and _bal(db, co, safe) == Decimal("30000.00")


# ═══ P) noto'g'ri manzil TURI (SAFE emas) -> RAD ═══════════════════════════
def test_P_wrong_destination_type_rejected(db, cashenv):
    co, br, emp, till, _safe = _tenant(db, cashenv)
    till2 = _acct(db, co, br, "TILL"); db.commit()
    sh = _open_shift(db, br, emp, till)
    with pytest.raises(HTTPException) as ei:
        _collect(db, emp, sh, 1000, till2.id)                    # TILL manzil sifatida
    assert CG.ERR_CUSTODY_INVALID in str(ei.value.detail)


# ═══ Q) safe_id berilmagan -> RAD (sukut seyf TANLANMAYDI) ════════════════
def test_Q_missing_safe_id_rejected(db, cashenv):
    co, br, emp, till, safe = _tenant(db, cashenv)
    sh = _open_shift(db, br, emp, till)
    with pytest.raises(HTTPException) as ei:
        _collect(db, emp, sh, 1000, None)
    assert CG.ERR_CUSTODY_REQUIRED in str(ei.value.detail)
    # filialda AYNAN BITTA SAFE bo'lsa ham AVTOMATIK tanlanmaydi
    assert db.query(CashAccount).filter(CashAccount.branch_id == br.id,
                                        CashAccount.type == "SAFE").count() == 1


# ═══ R) takroriy so'rov IDEMPOTENT ════════════════════════════════════════
def test_R_duplicate_collection_is_idempotent(db, cashenv):
    co, br, emp, till, safe = _tenant(db, cashenv)
    sh = _open_shift(db, br, emp, till)
    _cr.on_shift_open(db, emp, branch_id=br.id, legacy_shift_id=sh.id,
                      opening_cash=Decimal("100000"), terminal_id=None)
    db.commit()
    cu = uuid.uuid4()
    _collect(db, emp, sh, 5000, safe.id, cu=cu)
    _collect(db, emp, sh, 5000, safe.id, cu=cu)                  # AYNI client_uuid -> takror
    legs = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "TRANSFER").all()
    assert len(legs) == 2, f"dublikat transfer yozildi: {len(legs)} oyoq"
    assert _bal(db, co, safe) == Decimal("5000.00")


# ═══ S) SAFE -> BANK_DEPOSIT jami naqdni AYNAN BIR MARTA kamaytiradi ══════
def test_S_bank_deposit_reduces_company_cash_once(db, cashenv):
    co, br, emp, till, safe = _tenant(db, cashenv)
    sh = _open_shift(db, br, emp, till)
    _cr.on_shift_open(db, emp, branch_id=br.id, legacy_shift_id=sh.id,
                      opening_cash=Decimal("100000"), terminal_id=None)
    db.commit()
    _collect(db, emp, sh, 40000, safe.id)
    total_after_collection = _bal(db, co, till) + _bal(db, co, safe)
    mid = uuid.uuid4()
    _cr.on_bank_deposit(db, emp, from_safe_id=safe.id, amount=Decimal("40000"), movement_id=mid,
                        commit=True)
    assert _bal(db, co, safe) == Decimal("0.00")
    assert _bal(db, co, till) + _bal(db, co, safe) == total_after_collection - Decimal("40000")
    dep = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "BANK_DEPOSIT").all()
    assert len(dep) == 1 and dep[0].direction == "OUT"           # YAGONA oyoq, transfer EMAS
    assert dep[0].transfer_group_id is None


# ═══ F/G/H) noto'g'ri filial / tenant / ARCHIVED custody -> RAD ═══════════
def test_FGH_custody_validation(db, cashenv):
    co, br, emp, till, safe = _tenant(db, cashenv)
    other_br = Branch(company_id=co.id, code="X" + _hex(), name="B2", is_active=True)
    db.add(other_br); db.flush()
    foreign_safe = _acct(db, co, other_br, "SAFE")               # BOSHQA filial
    archived = _acct(db, co, br, "SAFE", status="ARCHIVED")      # ARXIVLANGAN
    co2 = Company(name="O" + _hex(), code="o" + _hex(), currency="UZS"); db.add(co2); db.flush()
    br2 = Branch(company_id=co2.id, code="Y" + _hex(), name="B", is_active=True); db.add(br2); db.flush()
    alien = _acct(db, co2, br2, "SAFE")                          # BOSHQA tenant
    db.commit()
    for bad, label in ((foreign_safe, "filial"), (archived, "arxiv"), (alien, "tenant")):
        with pytest.raises(HTTPException) as ei:
            CG.require_custody_account(db, company_id=co.id, branch_id=br.id, account_id=bad.id,
                                       operation="collection_destination", expect_type="SAFE")
        assert CG.ERR_CUSTODY_INVALID in str(ei.value.detail), label


# ═══ I/J) fallback YO'Q (yagona TILL / yagona SAFE) ═══════════════════════
def test_IJ_no_single_account_fallback():
    import inspect
    src = inspect.getsource(CG.require_custody_account)
    for bad in ("find_safe", "resolve_till_exact", "single-checkout", ".first()"):
        assert bad not in src, f"custody guard'da fallback: {bad}"


# ═══ Z/AA/AB/AC/AD/AE) YOPILGAN smena replay RAD ═════════════════════════
@pytest.mark.parametrize("op", ["cash_sale", "cash_refund", "cash_op:expense"])
def test_ZAAAB_closed_shift_replay_rejected(db, cashenv, op):
    co, br, emp, till, _s = _tenant(db, cashenv)
    sh = _open_shift(db, br, emp, till)
    sh.status = ShiftStatus.closed; sh.closed_at = _now(); sh.counted_cash = Decimal("100000")
    db.add(sh)
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"cutover_at": (_now() - timedelta(hours=1)).isoformat()}))
    db.commit()
    n_legs = db.query(CLE).filter(CLE.tenant_id == co.id).count()
    with pytest.raises(HTTPException) as ei:
        CG.require_post_t0_till(db, company_id=co.id, branch_id=br.id, operation=op,
                                shift=sh, till_id=till.id)
    assert CG.ERR_CLOSED_SHIFT_REPLAY in str(ei.value.detail)
    db.rollback()
    # AC: ledger O'ZGARMADI
    assert db.query(CLE).filter(CLE.tenant_id == co.id).count() == n_legs
    # AD/AE: smena yopiq QOLDI, counted_cash o'zgarmadi, auto-reopen YO'Q
    fresh = db.get(Shift, sh.id)
    assert fresh.status == ShiftStatus.closed and fresh.closed_at is not None
    assert fresh.counted_cash == Decimal("100000.00")
    assert fresh.till_id == till.id                              # boshqa smenaga biriktirilmadi


# ═══ pre-T0 da yopilgan smena replay'i LEGACY xatti-harakat (regressiya yo'q) ═
def test_pre_t0_closed_shift_replay_not_gated(db, cashenv):
    co, br, emp, till, _s = _tenant(db, cashenv)
    sh = _open_shift(db, br, emp, till)
    sh.status = ShiftStatus.closed; sh.closed_at = _now(); db.add(sh); db.commit()
    acc, enforced = CG.require_post_t0_till(db, company_id=co.id, branch_id=br.id,
                                            operation="cash_sale", shift=sh, till_id=till.id)
    assert enforced is False and acc is None                     # T0 yo'q -> legacy
