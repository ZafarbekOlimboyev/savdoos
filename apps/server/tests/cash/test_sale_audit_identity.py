# -*- coding: utf-8 -*-
"""Sale / Receipt AUDIT IDENTITY revision testlari (real PostgreSQL).

Har savdo qaysi kassir / smena / FIZIK TILL / terminal / filialда bo'lganини AVTORITETLI (taxminsiz)
saqlashini isbotlaydi: shift->till meros, server-authoritative resolution, klient-override rad,
ledger account == Sale.till_id, refund alohida TILL, snapshot immutability, legacy no-fallback, filtrlar.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.api.v1 import sales as sales_api
from app.api.v1 import shifts as shifts_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry
from app.models.catalog import Product, Unit
from app.models.enums import ShiftStatus
from app.models.inventory import Inventory
from app.models.org import Branch, Company, Terminal
from app.models.sales import Return, Sale
from app.schemas.sales import ReturnCreate, ReturnItemIn, SaleCreate, SaleItemIn
from app.services import sales as sales_svc
from app.services.cash import mode
from app.services.cash import till_identity as ti


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _company(db):
    co = Company(name="AU" + _hex(), code="au" + _hex(), currency="UZS"); db.add(co); db.flush()
    return co


def _branch(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="Filial " + _hex()); db.add(b); db.flush(); return b


def _emp(db, co, br):
    role = db.query(Role).first()
    e = Employee(company_id=co.id, full_name="Kassir " + _hex(), role_id=role.id); db.add(e); db.flush()
    db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush()
    return e


def _terminal(db, br, name=None):
    t = Terminal(branch_id=br.id, name=name or ("T" + _hex())); db.add(t); db.flush(); return t


def _till(db, co, br, code, terminal=None):
    acc = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                      label=ti.till_label(code, terminal.id if terminal else None),
                      created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    db.add(acc); db.flush(); return acc


def _product(db, co, br, sell="10000", stock="1000"):
    unit = Unit(code="dona" + _hex(), name="dona"); db.add(unit); db.flush()
    p = Product(company_id=co.id, article_code="A" + _hex(), name="M" + _hex(), unit_id=unit.id,
                base_buy_price=Decimal("6000"), base_sell_price=Decimal(sell), tax_rate=Decimal("0"))
    db.add(p); db.flush()
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal(stock),
                     updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
    db.commit()
    return p


def _open(db, emp, terminal=None, opening=0):
    return shifts_api.open_shift(shifts_api.OpenShift(opening_cash=opening,
                                 terminal_id=(terminal.id if terminal else None)), emp, db)


def _sale(db, emp, product, qty=1, method="cash", **kw):
    return sales_svc.create_sale(db, emp, SaleCreate(
        items=[SaleItemIn(product_id=product.id, qty=qty)], payment_method=method, **kw))


def _sale_leg(db, co, sale):
    return db.query(CashLedgerEntry).filter(
        CashLedgerEntry.tenant_id == co.id, CashLedgerEntry.source_type == "SALE",
        CashLedgerEntry.source_id == sale.id).all()


# ═══ A) shift TILL -> Sale.till_id ═══════════════════════════════════════════
def test_A_sale_inherits_shift_till(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); till1 = _till(db, co, br, "TILL-01", t1)
    prod = _product(db, co, br)
    _open(db, emp, t1)
    s = _sale(db, emp, prod)
    assert s.till_id == till1.id and s.terminal_id == t1.id and s.cashier_id == emp.id


# ═══ B) same cashier, next shift, different TILL ═════════════════════════════
def test_B_same_cashier_different_till_next_shift(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); t2 = _terminal(db, br)
    till1 = _till(db, co, br, "TILL-01", t1); till2 = _till(db, co, br, "TILL-02", t2)
    prod = _product(db, co, br)
    r1 = _open(db, emp, t1); s1 = _sale(db, emp, prod)
    shifts_api.close_shift(uuid.UUID(r1["id"]), shifts_api.CloseShift(counted_cash=0), emp, db)
    _open(db, emp, t2); s2 = _sale(db, emp, prod)
    assert s1.till_id == till1.id and s2.till_id == till2.id      # bir kassir, farqli fizik TILL


# ═══ C) history preserves both ══════════════════════════════════════════════
def test_C_history_preserves_distinct_tills(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); t2 = _terminal(db, br)
    till1 = _till(db, co, br, "TILL-01", t1); till2 = _till(db, co, br, "TILL-02", t2)
    prod = _product(db, co, br)
    r1 = _open(db, emp, t1); _sale(db, emp, prod)
    shifts_api.close_shift(uuid.UUID(r1["id"]), shifts_api.CloseShift(counted_cash=0), emp, db)
    _open(db, emp, t2); _sale(db, emp, prod)
    tills = {row[0] for row in db.query(Sale.till_id).filter(Sale.cashier_id == emp.id).all()}
    assert tills == {till1.id, till2.id}                          # ikkalasi ham saqlangan


# ═══ D) client sends conflicting till -> rejected (server authoritative) ═════
def test_D_client_conflicting_till_rejected(db, cashenv):
    from fastapi import HTTPException
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); t2 = _terminal(db, br)
    _till(db, co, br, "TILL-01", t1); till2 = _till(db, co, br, "TILL-02", t2)
    prod = _product(db, co, br)
    _open(db, emp, t1)                                            # active shift -> TILL-01
    with pytest.raises(HTTPException) as ei:
        _sale(db, emp, prod, till_id=till2.id)                    # klient TILL-02 yubordi (zid)
    assert ei.value.status_code == 409


# ═══ E) wrong-tenant TILL -> rejected ═══════════════════════════════════════
def test_E_wrong_tenant_till_rejected(db, cashenv):
    from fastapi import HTTPException
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); _till(db, co, br, "TILL-01", t1)
    other = _company(db); obr = _branch(db, other); otill = _till(db, other, obr, "OTHER", _terminal(db, obr))
    prod = _product(db, co, br)
    _open(db, emp, t1)
    with pytest.raises(HTTPException) as ei:
        _sale(db, emp, prod, till_id=otill.id)                    # boshqa tenant TILL'i
    assert ei.value.status_code == 400 and "TILL" in ei.value.detail


# ═══ F) wrong-branch TILL -> rejected ═══════════════════════════════════════
def test_F_wrong_branch_till_rejected(db, cashenv):
    from fastapi import HTTPException
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); _till(db, co, br, "TILL-01", t1)
    br2 = _branch(db, co); till_b2 = _till(db, co, br2, "TILL-B2", _terminal(db, br2))
    prod = _product(db, co, br)
    _open(db, emp, t1)
    with pytest.raises(HTTPException) as ei:
        _sale(db, emp, prod, till_id=till_b2.id)                  # bir tenant, boshqa filial TILL'i
    assert ei.value.status_code == 400


# ═══ G) cash sale -> ledger account == Sale.till_id ═════════════════════════
def test_G_cash_ledger_account_is_sale_till(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); till1 = _till(db, co, br, "TILL-01", t1)
    prod = _product(db, co, br)
    _open(db, emp, t1)
    s = _sale(db, emp, prod)
    legs = _sale_leg(db, co, s)
    assert len(legs) == 1 and legs[0].cash_account_id == till1.id == s.till_id


# ═══ H) card sale -> no cash ledger movement ════════════════════════════════
def test_H_card_sale_no_cash_leg(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); _till(db, co, br, "TILL-01", t1)
    prod = _product(db, co, br)
    _open(db, emp, t1)
    s = _sale(db, emp, prod, method="card")
    assert _sale_leg(db, co, s) == []                            # karta -> naqd ledger harakati YO'Q


# ═══ I) refund from a different TILL; original identity preserved ════════════
def test_I_refund_different_till_preserves_original(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); t2 = _terminal(db, br)
    till1 = _till(db, co, br, "TILL-01", t1); till2 = _till(db, co, br, "TILL-02", t2)
    prod = _product(db, co, br, sell="10000")
    r1 = _open(db, emp, t1); s1 = _sale(db, emp, prod)           # sotuv TILL-01
    shifts_api.close_shift(uuid.UUID(r1["id"]), shifts_api.CloseShift(counted_cash=0), emp, db)
    _open(db, emp, t2, opening=50000)                            # ertasi TILL-02 (naqd bor)
    sales_api._create_return_once(ReturnCreate(
        original_sale_id=s1.id, refund_method="cash",
        items=[ReturnItemIn(product_id=prod.id, qty=1, unit_price=10000)]), emp, db)
    ret = db.query(Return).filter(Return.original_sale_id == s1.id).order_by(Return.created_at.desc()).first()
    db.refresh(s1)
    assert s1.till_id == till1.id                                # asl sotuv identity O'ZGARMADI
    assert ret.till_id == till2.id                              # refund alohida TILL'da bajarildi
    out = db.query(CashLedgerEntry).filter(
        CashLedgerEntry.tenant_id == co.id, CashLedgerEntry.source_type == "RETURN",
        CashLedgerEntry.source_id == ret.id).all()
    assert len(out) == 1 and out[0].cash_account_id == till2.id  # ledger OUT refund TILL'dan


# ═══ J) cashier rename -> snapshot immutable ════════════════════════════════
def test_J_cashier_rename_snapshot_preserved(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); _till(db, co, br, "TILL-01", t1)
    prod = _product(db, co, br)
    _open(db, emp, t1)
    s = _sale(db, emp, prod)
    orig = s.cashier_name_snapshot
    assert orig and orig == emp.full_name
    emp.full_name = "YANGI ISM"; db.add(emp); db.commit()
    db.refresh(s)
    assert s.cashier_name_snapshot == orig                       # rename chekni O'ZGARTIRMAYDI


# ═══ K) till rename -> snapshot immutable ═══════════════════════════════════
def test_K_till_rename_snapshot_preserved(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); till1 = _till(db, co, br, "TILL-01", t1)
    prod = _product(db, co, br)
    _open(db, emp, t1)
    s = _sale(db, emp, prod)
    assert s.till_code_snapshot == "TILL-01"
    till1.label = ti.till_label("TILL-RENAMED", t1.id); db.add(till1); db.commit()
    db.refresh(s)
    assert s.till_code_snapshot == "TILL-01"                     # eski chek audit-xavfsiz


# ═══ L) no TILL provisioned -> till_id None (no fallback) ════════════════════
def test_L_no_till_no_fallback(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)   # TILL provision QILINMAGAN
    prod = _product(db, co, br)
    _open(db, emp, None)                                          # terminalsiz smena
    s = _sale(db, emp, prod)
    assert s.till_id is None                                     # taxmin YO'Q (branch-default fallback yo'q)
    assert _sale_leg(db, co, s) == []                            # noma'lum TILL'ga ledger yozilmaydi


# ═══ M) completed sale identity not silently mutated (idempotent re-create) ══
def test_M_identity_stable_on_idempotent_recreate(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); till1 = _till(db, co, br, "TILL-01", t1)
    prod = _product(db, co, br)
    _open(db, emp, t1)
    cu = uuid.uuid4()
    s1 = _sale(db, emp, prod, client_uuid=cu)
    s2 = _sale(db, emp, prod, client_uuid=cu)                    # bir xil client_uuid -> o'sha chek
    assert s1.id == s2.id and s2.till_id == till1.id and s2.cashier_id == emp.id  # identity o'zgarmadi


# ═══ N) tenant isolation ════════════════════════════════════════════════════
def test_N_tenant_isolation(db, cashenv):
    coA = _company(db); brA = _branch(db, coA); empA = _emp(db, coA, brA)
    _till(db, coA, brA, "TILL-01", _terminal(db, brA)); prodA = _product(db, coA, brA)
    _open(db, empA, None); sA = _sale(db, empA, prodA)
    coB = _company(db)
    b_ids = {row[0] for row in db.query(Sale.id).filter(Sale.company_id == coB.id).all()}
    assert sA.id not in b_ids                                    # A savdosi B tenantda ko'rinmaydi


# ═══ O) filters by cashier / shift / till / terminal / branch ═══════════════
def test_O_audit_filters(db, cashenv):
    co = _company(db); br = _branch(db, co); emp = _emp(db, co, br)
    t1 = _terminal(db, br); t2 = _terminal(db, br)
    till1 = _till(db, co, br, "TILL-01", t1); till2 = _till(db, co, br, "TILL-02", t2)
    prod = _product(db, co, br)
    r1 = _open(db, emp, t1); s1 = _sale(db, emp, prod)
    shifts_api.close_shift(uuid.UUID(r1["id"]), shifts_api.CloseShift(counted_cash=0), emp, db)
    _open(db, emp, t2); s2 = _sale(db, emp, prod)
    # till filter
    assert {r[0] for r in db.query(Sale.id).filter(Sale.till_id == till1.id).all()} == {s1.id}
    assert {r[0] for r in db.query(Sale.id).filter(Sale.till_id == till2.id).all()} == {s2.id}
    # terminal filter
    assert {r[0] for r in db.query(Sale.id).filter(Sale.terminal_id == t1.id).all()} == {s1.id}
    # shift filter
    assert {r[0] for r in db.query(Sale.id).filter(Sale.shift_id == s1.shift_id).all()} == {s1.id}
    # cashier + branch filters (both sales)
    assert {r[0] for r in db.query(Sale.id).filter(Sale.cashier_id == emp.id).all()} == {s1.id, s2.id}
    assert {r[0] for r in db.query(Sale.id).filter(Sale.branch_id == br.id).all()} == {s1.id, s2.id}
