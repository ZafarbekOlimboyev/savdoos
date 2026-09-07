# -*- coding: utf-8 -*-
"""PURCHASE CUSTODY — explicit cash_account_id (real PostgreSQL).

§2 QOIDA:  ochiq smena BOR  -> custody = shift.till_id
           ochiq smena YO'Q -> custody = so'rovdagi EXPLICIT cash_account_id (TILL yoki SAFE)
TAXMIN YO'Q: filial-default / birinchi TILL / yagona TILL / kassir / terminal / implicit SAFE.

A smenali xarid, hisob berilmagan  -> shift.till_id
B smenali + AYNI hisob             -> o'tadi
C smenali + BOSHQA hisob           -> RAD
D smenasiz post-T0, hisobsiz       -> RAD
E smenasiz post-T0 + ACTIVE TILL   -> o'tadi
F smenasiz post-T0 + ACTIVE SAFE   -> o'tadi
G/H/I/J noto'g'ri tenant / filial / valyuta / ARCHIVED -> RAD
K/L purchase-return IN (TILL / SAFE)   M increase OUT   N receiving OUT   O to'lovsiz -> leg YO'Q
P retry idempotent   Q retry BOSHQA hisob -> RAD   R fallback YO'Q
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.models.shifts import Shift
from app.services.cash import cutover_guard as CG
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _acct(db, co, br, typ, status="ACTIVE", cur="UZS"):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type=typ, currency=cur, status=status,
                    label=(_ti.till_label("T-" + _hex(), None) if typ == "TILL"
                           else _ti.safe_label("S-" + _hex())), created_at=_now())
    db.add(a); db.flush(); return a


def _tenant(db, *, t0_ago_hours=1):
    co = Company(name="PC" + _hex(), code="pc" + _hex(), currency="UZS"); db.add(co); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True); db.add(br); db.flush()
    emp = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(emp); db.flush(); db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = _acct(db, co, br, "TILL"); safe = _acct(db, co, br, "SAFE")
    if t0_ago_hours is not None:
        db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                       value={"cutover_at": (_now() - timedelta(hours=t0_ago_hours)).isoformat()}))
    db.commit()
    return co, br, emp, till, safe


def _shift(db, br, emp, till):
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(hours=2),
               opening_cash=Decimal("0"), status=ShiftStatus.open, till_id=till.id)
    db.add(sh); db.commit(); return sh


def _fund(db, emp, acc, amount="50000"):
    """OUT post qilish uchun hisobni to'ldiramiz (naqd yetarli bo'lsin)."""
    from app.services.cash import adapters as _ad
    _ad.manual_cash_in(db, emp, cash_account_id=acc.id, source_id=uuid.uuid4(),
                       amount=Decimal(amount), commit=True)


def _resolve(db, co, br, **kw):
    op = kw.pop("op", "cash_purchase")
    return CG.resolve_cash_custody(db, company_id=co.id, branch_id=br.id, operation=op, **kw)


# ═══ A) smenali xarid, hisob berilmagan -> shift.till_id ═══════════════════
def test_A_shift_bound_uses_shift_till(db, cashenv):
    co, br, emp, till, _s = _tenant(db)
    sh = _shift(db, br, emp, till)
    acc, enforced = _resolve(db, co, br, shift=sh, cash_account_id=None)
    assert enforced is True and acc.id == till.id


# ═══ B) smenali + AYNI hisob -> o'tadi ════════════════════════════════════
def test_B_shift_bound_with_same_account_ok(db, cashenv):
    co, br, emp, till, _s = _tenant(db)
    sh = _shift(db, br, emp, till)
    acc, enforced = _resolve(db, co, br, shift=sh, cash_account_id=till.id)
    assert enforced is True and acc.id == till.id


# ═══ C) smenali + BOSHQA hisob -> RAD (override YO'Q) ═════════════════════
def test_C_shift_bound_with_different_account_rejected(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    other = _acct(db, co, br, "TILL"); db.commit()
    sh = _shift(db, br, emp, till)
    for bad in (other.id, safe.id):
        with pytest.raises(HTTPException) as ei:
            _resolve(db, co, br, shift=sh, cash_account_id=bad)
        assert CG.ERR_TILL_SHIFT_MISMATCH in str(ei.value.detail)


# ═══ D) smenasiz post-T0, hisobsiz -> RAD ════════════════════════════════
def test_D_shiftless_post_t0_without_account_rejected(db, cashenv):
    co, br, _e, _t, _s = _tenant(db)
    with pytest.raises(HTTPException) as ei:
        _resolve(db, co, br, shift=None, cash_account_id=None)
    assert CG.ERR_CUSTODY_REQUIRED in str(ei.value.detail)


# ═══ E/F) smenasiz post-T0 + ACTIVE TILL / SAFE -> o'tadi ════════════════
@pytest.mark.parametrize("kind", ["TILL", "SAFE"])
def test_EF_shiftless_with_explicit_account_ok(db, cashenv, kind):
    co, br, _e, till, safe = _tenant(db)
    want = till if kind == "TILL" else safe
    acc, enforced = _resolve(db, co, br, shift=None, cash_account_id=want.id)
    assert enforced is True and acc.id == want.id and str(acc.type) == kind


# ═══ G/H/I/J) tenant / filial / valyuta / ARCHIVED -> RAD ════════════════
def test_GHIJ_invalid_accounts_rejected(db, cashenv):
    co, br, _e, _t, _s = _tenant(db)
    br2 = Branch(company_id=co.id, code="X" + _hex(), name="B2", is_active=True); db.add(br2); db.flush()
    wrong_branch = _acct(db, co, br2, "TILL")
    wrong_cur = _acct(db, co, br, "TILL", cur="USD")
    archived = _acct(db, co, br, "TILL", status="ARCHIVED")
    co2 = Company(name="O" + _hex(), code="o" + _hex(), currency="UZS"); db.add(co2); db.flush()
    br3 = Branch(company_id=co2.id, code="Y" + _hex(), name="B", is_active=True); db.add(br3); db.flush()
    alien = _acct(db, co2, br3, "TILL")
    db.commit()
    for bad, label in ((alien, "tenant"), (wrong_branch, "branch"), (archived, "archived")):
        with pytest.raises(HTTPException) as ei:
            _resolve(db, co, br, shift=None, cash_account_id=bad.id)
        assert CG.ERR_CUSTODY_INVALID in str(ei.value.detail), label
    with pytest.raises(HTTPException) as ei:                      # I: valyuta
        _resolve(db, co, br, shift=None, cash_account_id=wrong_cur.id, currency="UZS")
    assert CG.ERR_CUSTODY_INVALID in str(ei.value.detail)


# ═══ K/L/N) hook'lar EXPLICIT hisobga post qiladi (TILL va SAFE) ═════════
@pytest.mark.parametrize("kind", ["TILL", "SAFE"])
def test_KL_purchase_return_posts_to_explicit_account(db, cashenv, kind):
    from app.services.cash import retrofit as _cr
    co, br, emp, till, safe = _tenant(db)
    target = till if kind == "TILL" else safe
    _fund(db, emp, target)
    pid = uuid.uuid4()
    _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=pid, cash_amount=Decimal("5000"),
                         cash_account_id=target.id)              # avval OUT (gate uchun)
    db.commit()
    _cr.on_purchase_return(db, emp, branch_id=br.id, purchase_id=pid,
                           purchase_return_id=uuid.uuid4(), cash_amount=Decimal("2000"),
                           cash_account_id=target.id)
    db.commit()
    leg = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "PURCHASE_RETURN").one()
    assert leg.cash_account_id == target.id and leg.direction == "IN"


@pytest.mark.parametrize("kind", ["TILL", "SAFE"])
def test_N_cash_purchase_posts_to_explicit_account(db, cashenv, kind):
    from app.services.cash import retrofit as _cr
    co, br, emp, till, safe = _tenant(db)
    target = till if kind == "TILL" else safe
    _fund(db, emp, target)
    _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=uuid.uuid4(),
                         cash_amount=Decimal("5000"), cash_account_id=target.id)
    db.commit()
    leg = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "PURCHASE_OUT").one()
    assert leg.cash_account_id == target.id and leg.direction == "OUT"


# ═══ M) increase OUT explicit hisobga ════════════════════════════════════
def test_M_purchase_increase_uses_explicit_account(db, cashenv):
    from app.services.cash import retrofit as _cr
    co, br, emp, till, safe = _tenant(db)
    _fund(db, emp, safe)
    pid = uuid.uuid4()
    _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=pid, cash_amount=Decimal("5000"),
                         cash_account_id=safe.id)
    db.commit()
    _cr.on_cash_purchase_increase(db, emp, branch_id=br.id, purchase_id=pid,
                                  extra_amount=Decimal("1500"), cash_account_id=safe.id)
    db.commit()
    legs = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "PURCHASE_OUT").all()
    assert len(legs) == 2 and all(x.cash_account_id == safe.id for x in legs)
    assert sorted(x.amount for x in legs) == [Decimal("1500.00"), Decimal("5000.00")]


# ═══ O) to'lovsiz (kredit) -> naqd leg YO'Q ══════════════════════════════
def test_O_no_payment_no_cash_leg(db, cashenv):
    from app.services.cash import retrofit as _cr
    co, br, emp, till, _s = _tenant(db)
    _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=uuid.uuid4(),
                         cash_amount=Decimal("0"), cash_account_id=till.id)
    db.commit()
    assert db.query(CLE).filter(CLE.tenant_id == co.id).count() == 0


# ═══ P) AYNI hisob bilan retry -> idempotent (dublikat leg YO'Q) ═════════
def test_P_retry_same_account_idempotent(db, cashenv):
    from app.services.cash import retrofit as _cr
    co, br, emp, till, _s = _tenant(db)
    _fund(db, emp, till)
    pid = uuid.uuid4()
    for _ in range(2):
        _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=pid,
                             cash_amount=Decimal("5000"), cash_account_id=till.id)
        db.commit()
    assert db.query(CLE).filter(CLE.tenant_id == co.id,
                                CLE.category == "PURCHASE_OUT").count() == 1


# ═══ Q) retry BOSHQA hisob bilan -> RAD (409) ════════════════════════════
def test_Q_retry_with_conflicting_account_rejected(db, cashenv):
    from app.api.v1 import purchases as purchases_api
    from app.models.enums import PurchaseStatus
    from app.models.purchasing import Purchase, Supplier
    from app.schemas.purchase import PurchaseCreate
    co, br, emp, till, safe = _tenant(db)
    sup = Supplier(company_id=co.id, name="S"); db.add(sup); db.flush()
    cu = uuid.uuid4()
    pur = Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=br.id, supplier_id=sup.id,
                   purchase_date=_now().date(), status=PurchaseStatus.received,
                   subtotal=Decimal("1000"), total=Decimal("1000"), paid_amount=Decimal("1000"),
                   client_uuid=cu, cash_account_id=till.id)
    db.add(pur); db.commit()
    data = PurchaseCreate(supplier_id=sup.id, status="received", items=[],
                          client_uuid=cu, cash_account_id=safe.id)
    with pytest.raises(HTTPException) as ei:
        purchases_api._create_purchase_once(data, emp, db)
    assert ei.value.status_code == 409 and CG.ERR_CUSTODY_INVALID in str(ei.value.detail)


# ═══ R) filial/yagona-TILL/kassir FALLBACK YO'Q ══════════════════════════
def test_R_no_fallback_in_resolver():
    import inspect
    src = inspect.getsource(CG.resolve_cash_custody)
    for bad in ("resolve_till_exact", "find_safe", "single-checkout", "first()", "list_tills"):
        assert bad not in src, f"resolver'da fallback: {bad}"
