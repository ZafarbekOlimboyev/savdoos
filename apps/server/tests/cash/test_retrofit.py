# -*- coding: utf-8 -*-
"""Phase 2b — biznes-servis retrofit integratsion testlari (real PostgreSQL).

HAQIQIY retrofit qilingan endpoint/servis funksiyalarини Postgres'da chaqiradi (TILL
xaritalangan) va ledger leg'lari + source qatorlari + atomiklik + gap-yopilishini tekshiradi.
SQLite'да guard cash'ni no-op qiladi (mavjud 28 test buni isbotlaydi).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.api.v1 import cashops as cashops_api
from app.api.v1 import purchases as purchases_api
from app.api.v1 import shifts as shifts_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry, CashShift
from app.models.catalog import Product, Unit
from app.models.org import Branch
from app.models.purchasing import Purchase, Supplier
from app.models.shifts import CashMovement
from app.models.shifts import Shift as LegacyShift
from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
from app.services.cash import repositories as repo
from app.services.cash.errors import CashError, CashPostingError


def _hex():
    return uuid.uuid4().hex[:8]


def provision(db, cashenv):
    """Yangi filial + xodim(EmployeeBranch) + TILL — har test izolyatsiya (resolve_till noaniq bo'lmasin)."""
    role_id = db.get(Employee, cashenv.employee_id).role_id
    br = Branch(company_id=cashenv.company_id, code="R" + _hex(), name="Retro filial")
    db.add(br); db.flush()
    emp = Employee(company_id=cashenv.company_id, full_name="Retro Kassir", role_id=role_id)
    db.add(emp); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = CashAccount(tenant_id=cashenv.company_id, branch_id=br.id, type="TILL",
                       currency="UZS", status="ACTIVE", created_at=cashenv.now)
    db.add(till)
    db.commit()
    return emp, br, till


def bal(db, cashenv, till):
    return repo.account_balance(db, cashenv.company_id, till.id)


def _open_shift(db, emp, opening):
    return shifts_api.open_shift(shifts_api.OpenShift(opening_cash=opening), emp, db)


# ── shift lifecycle dual-write ───────────────────────────────────────────────
def test_shift_open_dual_write(db, cashenv):
    emp, br, till = provision(db, cashenv)
    r = _open_shift(db, emp, 100000)
    assert r["id"]
    cs = repo.open_shift_for_account(db, cashenv.company_id, till.id)
    assert cs is not None and cs.status == "OPEN"      # cash.shift ochildi
    assert bal(db, cashenv, till) == Decimal("100000.00")   # IN·OPENING


def test_shift_close_dual_write(db, cashenv):
    emp, br, till = provision(db, cashenv)
    r = _open_shift(db, emp, 5000)
    shifts_api.close_shift(uuid.UUID(r["id"]), shifts_api.CloseShift(counted_cash=5000), emp, db)
    cs = db.execute(
        __import__("sqlalchemy").select(CashShift).where(CashShift.cash_account_id == till.id)
    ).scalars().first()
    assert cs.status == "CLOSED"
    from app.models.cash import ReconciliationRecord
    rec = db.query(ReconciliationRecord).filter_by(shift_id=cs.id, is_current=True).first()
    assert rec is not None and rec.ledger_balance_snapshot == Decimal("5000.00")


# ── manual cash op dual-write ────────────────────────────────────────────────
def test_cash_op_dual_write(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    cashops_api.cash_op(cashops_api.CashOpIn(type="payin", amount=5000), emp, db)
    assert bal(db, cashenv, till) == Decimal("105000.00")   # IN·CASH_IN
    cashops_api.cash_op(cashops_api.CashOpIn(type="expense", amount=3000, reason="x"), emp, db)
    assert bal(db, cashenv, till) == Decimal("102000.00")   # OUT·EXPENSE
    # ledger toifasi to'g'ri
    kinds = {e.category for e in db.query(CashLedgerEntry).filter(CashLedgerEntry.cash_account_id == till.id).all()}
    assert {"OPENING", "CASH_IN", "EXPENSE"} <= kinds


def test_idempotent_cash_op(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    cu = uuid.uuid4()
    cashops_api.cash_op(cashops_api.CashOpIn(type="payin", amount=5000, client_uuid=cu), emp, db)
    cashops_api.cash_op(cashops_api.CashOpIn(type="payin", amount=5000, client_uuid=cu), emp, db)  # dublikat
    # legacy CashMovement bir marta (client_uuid dedup) + ledger leg bir marta
    mv = db.query(CashMovement).filter(CashMovement.client_uuid == cu).count()
    assert mv == 1
    assert bal(db, cashenv, till) == Decimal("105000.00")   # ikki marta emas


# ── CASH PURCHASE GAP (§07) — the critical proof ─────────────────────────────
def _setup_product(db, cashenv):
    unit = db.query(Unit).first()   # birliklar global (company_id yo'q)
    if unit is None:
        unit = Unit(code="dona_" + _hex(), name="dona")
        db.add(unit); db.flush()
    prod = Product(company_id=cashenv.company_id, article_code="A" + _hex(), name="Mahsulot",
                   unit_id=unit.id, base_buy_price=Decimal("10000"), base_sell_price=Decimal("15000"))
    db.add(prod)
    sup = Supplier(company_id=cashenv.company_id, name="Yetkazuvchi")
    db.add(sup)
    db.commit()
    return prod, sup


def test_cash_purchase_closes_gap(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    prod, sup = _setup_product(db, cashenv)
    before = bal(db, cashenv, till)
    data = PurchaseCreate(supplier_id=sup.id, status="received",
                          items=[PurchaseItemIn(product_id=prod.id, qty=3, unit_cost=10000)])
    pur = purchases_api.create_purchase(data, emp, db)
    # legacy Purchase yozildi
    assert db.query(Purchase).filter(Purchase.id == pur.id).first() is not None
    # KASSA endi kamaydi — OUT·PURCHASE_OUT (ilgari teshik: kassa jimgina o'zgармасди)
    after = bal(db, cashenv, till)
    assert after == before - Decimal("30000.00"), f"gap NOT closed: {before} -> {after}"
    leg = db.query(CashLedgerEntry).filter(
        CashLedgerEntry.source_id == pur.id, CashLedgerEntry.category == "PURCHASE_OUT").first()
    assert leg is not None and leg.direction == "OUT" and leg.amount == Decimal("30000.00")


def test_cash_purchase_atomicity_insufficient(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 10000)   # oz naqd
    prod, sup = _setup_product(db, cashenv)
    data = PurchaseCreate(supplier_id=sup.id, status="received",
                          items=[PurchaseItemIn(product_id=prod.id, qty=5, unit_cost=10000)])  # total 50000 > 10000
    with pytest.raises(CashPostingError) as ei:
        purchases_api.create_purchase(data, emp, db)
    assert ei.value.code == CashError.INSUFFICIENT_CASH
    db.rollback()
    # ATOMIK: Purchase HAM, ledger leg HAM yozilmagan
    assert db.query(Purchase).filter(Purchase.supplier_id == sup.id).count() == 0
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "PURCHASE_OUT",
                                            CashLedgerEntry.cash_account_id == till.id).count() == 0


def test_split_cash_sale_uses_persisted_amount(db, cashenv):
    """Split naqd sotuvda ledger leg YOZILGAN (yaxlitlangan) SalePayment'ga teng bo'lishi kerak —
    so'rovdagi xom kasr summaga EMAS (review MINOR)."""
    from sqlalchemy import func as _func
    from app.models.inventory import Inventory
    from app.models.sales import SalePayment
    from app.schemas.sales import PaymentSplit, SaleCreate, SaleItemIn
    from app.services import sales as sales_svc

    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    unit = db.query(Unit).first() or Unit(code="dona_" + _hex(), name="dona")
    if unit.id is None:
        db.add(unit); db.flush()
    prod = Product(company_id=cashenv.company_id, article_code="A" + _hex(), name="Narx4263",
                   unit_id=unit.id, base_buy_price=Decimal("1000"), base_sell_price=Decimal("4263"))
    db.add(prod); db.flush()
    db.add(Inventory(product_id=prod.id, branch_id=br.id, qty=Decimal("10"), updated_at=cashenv.now))
    db.commit()
    # total = 4263; split: cash 4162.5 (yaxlitlanadi 4163), card 100.5 (oxirgi leg = qoldiq 100)
    data = SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)],
                      payments=[PaymentSplit(method="cash", amount=4162.5),
                                PaymentSplit(method="card", amount=100.5)])
    sale = sales_svc.create_sale(db, emp, data)
    persisted = db.query(_func.coalesce(_func.sum(SalePayment.amount), 0)).filter(
        SalePayment.sale_id == sale.id, SalePayment.method_code == "cash").scalar()
    leg = db.query(CashLedgerEntry).filter(
        CashLedgerEntry.source_id == sale.id, CashLedgerEntry.category == "SALE").first()
    assert leg is not None
    assert leg.amount == persisted            # ledger == YOZILGAN naqd
    assert leg.amount == Decimal("4163.00")   # xom 4162.5 EMAS


def _stock(db, cashenv, prod, br, qty=100):
    from app.models.inventory import Inventory
    db.add(Inventory(product_id=prod.id, branch_id=br.id, qty=Decimal(str(qty)), updated_at=cashenv.now))
    db.commit()


def _cash_sale(db, emp, prod, qty):
    from app.schemas.sales import SaleCreate, SaleItemIn
    from app.services import sales as sales_svc
    return sales_svc.create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=qty)],
                                                     payment_method="cash"))


# ── refund (OUT·REFUND) ──────────────────────────────────────────────────────
def test_refund_cash(db, cashenv):
    from app.api.v1 import sales as sales_api
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    prod, _ = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    sale = _cash_sale(db, emp, prod, 2)
    before = bal(db, cashenv, till)
    sales_api.create_return(ReturnCreate(original_sale_id=sale.id, refund_method="cash",
                                         items=[ReturnItemIn(product_id=prod.id, qty=2)]), emp, db)
    leg = db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "REFUND", CashLedgerEntry.cash_account_id == till.id).first()
    assert leg is not None and leg.direction == "OUT"
    assert leg.reverses_id is None          # partial refund reversal EMAS
    assert bal(db, cashenv, till) == before - leg.amount   # naqd kamaydi


def test_refund_duplicate(db, cashenv):
    from app.api.v1 import sales as sales_api
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    prod, _ = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    sale = _cash_sale(db, emp, prod, 2)
    cu = uuid.uuid4()
    d = ReturnCreate(original_sale_id=sale.id, refund_method="cash", client_uuid=cu,
                     items=[ReturnItemIn(product_id=prod.id, qty=1)])
    sales_api.create_return(d, emp, db)
    sales_api.create_return(d, emp, db)   # dublikat
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "REFUND", CashLedgerEntry.cash_account_id == till.id).count() == 1


def test_refund_rollback_insufficient(db, cashenv):
    """Bo'sh kassada naqd qaytarish RAD etiladi VA dual-write chegarasi ATOMIK: na Return, na REFUND
    ledger leg qoladi. DIQQAT (§11 topilma): create_return'da legacy RET-5 guard (sales.py:730 —
    `total > _till + 0.5`) on_cash_refund hook'idan (sales.py:781) OLDIN ishlaydi, shu bois bu yerda
    HTTPException(400) tushadi — ledger INSUFFICIENT_CASH EMAS. Muhimi: guard leg YOZILISHIDAN oldin
    rad etadi (leg sizmaydi). Ledger sufficiency tarmog'i test_refund_hook_insufficient_ledger'da."""
    from fastapi import HTTPException
    from app.api.v1 import sales as sales_api
    from app.models.sales import Return
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    prod, _ = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    sale = _cash_sale(db, emp, prod, 2)   # till = 30000
    cashops_api.cash_op(cashops_api.CashOpIn(type="collection", amount=30000), emp, db)  # kassani bo'shatdik
    assert bal(db, cashenv, till) == Decimal("0.00")
    before_returns = db.query(Return).count()
    with pytest.raises(HTTPException) as ei:   # bo'sh kassada 30000 naqd qaytarish -> legacy RET-5 rad
        sales_api.create_return(ReturnCreate(original_sale_id=sale.id, refund_method="cash",
                                             items=[ReturnItemIn(product_id=prod.id, qty=2)]), emp, db)
    assert ei.value.status_code == 400
    db.rollback()
    assert db.query(Return).count() == before_returns   # Return YOZILMAGAN (atomik)
    assert db.query(CashLedgerEntry).filter(   # REFUND leg SIZMAGAN — guard leg-dan oldin rad etdi
        CashLedgerEntry.category == "REFUND", CashLedgerEntry.cash_account_id == till.id).count() == 0


def test_refund_hook_insufficient_ledger(db, cashenv):
    """CashPostingService'ning REFUND uchun INSUFFICIENT_CASH tarmog'ini TO'G'RIDAN-TO'G'RI qamrab oladi.
    Endpoint orqali bu yetib bo'lmaydi (legacy RET-5 guard butun-som summalar uchun har doim teng-yoki-
    qattiqroq, ledger sufficiency'dan oldin rad etadi — test_refund_rollback_insufficient'ga qarang), shu
    bois hook'ni bevosita chaqiramiz: bo'sh kassada (ledger balans 0) 50000 OUT·REFUND -> INSUFFICIENT_CASH,
    commit=False bo'lgani uchun leg yozilmaydi (atomik)."""
    from app.services.cash import retrofit as _cr
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)   # ochiq smena, kassa bo'sh (ledger balans 0)
    with pytest.raises(CashPostingError) as ei:
        _cr.on_cash_refund(db, emp, branch_id=br.id, return_id=uuid.uuid4(), cash_amount=50000)
    assert ei.value.code == CashError.INSUFFICIENT_CASH
    db.rollback()
    assert db.query(CashLedgerEntry).filter(
        CashLedgerEntry.category == "REFUND", CashLedgerEntry.cash_account_id == till.id).count() == 0


# ── customer debt payment (IN·DEBT_IN) ───────────────────────────────────────
def _customer(db, cashenv, credit=50000):
    from app.models.customers import Customer
    c = Customer(company_id=cashenv.company_id, code="M" + _hex(), full_name="Qarzdor",
                 credit_balance=Decimal(str(credit)))
    db.add(c); db.commit()
    return c


def test_debt_payment_cash(db, cashenv):
    from app.api.v1 import customers as customers_api
    from app.schemas.customer import CreditPayment
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    c = _customer(db, cashenv, 50000)
    before = bal(db, cashenv, till)
    customers_api.pay_credit(c.id, CreditPayment(amount=20000, method="cash"), emp, db)
    leg = db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "DEBT_IN", CashLedgerEntry.cash_account_id == till.id).first()
    assert leg is not None and leg.direction == "IN" and leg.amount == Decimal("20000.00")
    assert bal(db, cashenv, till) == before + Decimal("20000.00")
    db.refresh(c)
    assert c.credit_balance == Decimal("30000.00")   # AR kamaydi


def test_debt_payment_card_no_leg(db, cashenv):
    from app.api.v1 import customers as customers_api
    from app.schemas.customer import CreditPayment
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    c = _customer(db, cashenv, 50000)
    customers_api.pay_credit(c.id, CreditPayment(amount=20000, method="card"), emp, db)
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "DEBT_IN", CashLedgerEntry.cash_account_id == till.id).count() == 0
    db.refresh(c)
    assert c.credit_balance == Decimal("30000.00")   # AR baribir kamaydi (karta)


def test_debt_payment_duplicate(db, cashenv):
    from app.api.v1 import customers as customers_api
    from app.schemas.customer import CreditPayment
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    c = _customer(db, cashenv, 50000)
    cu = uuid.uuid4()
    customers_api.pay_credit(c.id, CreditPayment(amount=20000, method="cash", client_uuid=cu), emp, db)
    customers_api.pay_credit(c.id, CreditPayment(amount=20000, method="cash", client_uuid=cu), emp, db)
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "DEBT_IN", CashLedgerEntry.cash_account_id == till.id).count() == 1
    assert bal(db, cashenv, till) == Decimal("20000.00")


# ── supplier payment (OUT·SUPPLIER_OUT) ──────────────────────────────────────
def _debt_purchase(db, emp, cashenv, prod, sup, qty, cost):
    return purchases_api.create_purchase(PurchaseCreate(
        supplier_id=sup.id, status="debt",
        items=[PurchaseItemIn(product_id=prod.id, qty=qty, unit_cost=cost)]), emp, db)


def test_supplier_payment_cash(db, cashenv):
    from app.api.v1.purchases import SupplierPaymentIn as _SPI
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    prod, sup = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    _debt_purchase(db, emp, cashenv, prod, sup, qty=3, cost=10000)   # sup.balance += 30000
    before = bal(db, cashenv, till)
    purchases_api.pay_supplier(sup.id, _SPI(amount=30000, method="cash"), emp, db)
    leg = db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "SUPPLIER_OUT", CashLedgerEntry.cash_account_id == till.id).first()
    assert leg is not None and leg.direction == "OUT" and leg.amount == Decimal("30000.00")
    assert bal(db, cashenv, till) == before - Decimal("30000.00")
    db.refresh(sup)
    assert sup.balance == Decimal("0.00")   # AP to'landi


def test_supplier_payment_insufficient_rollback(db, cashenv):
    from app.api.v1.purchases import SupplierPaymentIn as _SPI
    from app.models.purchasing import SupplierPayment
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 5000)    # oz naqd
    prod, sup = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    _debt_purchase(db, emp, cashenv, prod, sup, qty=5, cost=10000)   # sup.balance = 50000
    with pytest.raises(CashPostingError) as ei:
        purchases_api.pay_supplier(sup.id, _SPI(amount=50000, method="cash"), emp, db)  # > till
    assert ei.value.code == CashError.INSUFFICIENT_CASH
    db.rollback()
    # ATOMIK: SupplierPayment YOZILMAGAN, ledger leg yo'q, sup.balance o'zgармаган
    assert db.query(SupplierPayment).filter(SupplierPayment.supplier_id == sup.id).count() == 0
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "SUPPLIER_OUT",
                                            CashLedgerEntry.cash_account_id == till.id).count() == 0


def test_supplier_payment_duplicate(db, cashenv):
    from app.api.v1.purchases import SupplierPaymentIn as _SPI
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    prod, sup = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    _debt_purchase(db, emp, cashenv, prod, sup, qty=3, cost=10000)
    cu = uuid.uuid4()
    purchases_api.pay_supplier(sup.id, _SPI(amount=30000, method="cash", client_uuid=cu), emp, db)
    purchases_api.pay_supplier(sup.id, _SPI(amount=30000, method="cash", client_uuid=cu), emp, db)
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.category == "SUPPLIER_OUT", CashLedgerEntry.cash_account_id == till.id).count() == 1


def test_debt_purchase_no_cash_leg(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    prod, sup = _setup_product(db, cashenv)
    before = bal(db, cashenv, till)
    data = PurchaseCreate(supplier_id=sup.id, status="debt",   # QARZ — naqd chiqmaydi
                          items=[PurchaseItemIn(product_id=prod.id, qty=2, unit_cost=10000)])
    pur = purchases_api.create_purchase(data, emp, db)
    assert bal(db, cashenv, till) == before   # kassa o'zgarmadi
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.source_id == pur.id).count() == 0


# ── purchase return (IN·PURCHASE_RETURN) — source-identity correction ─────────
# NAQD (received) xarid `edit_purchase`da kamaytirilса/bekor qilinса, alohida PurchaseReturn
# hodisasi yaratiladi va IN·PURCHASE_RETURN posting qilinади (source_type=PURCHASE_RETURN,
# source_id=return_id) — create'даги PURCHASE·purchase_id·0 leg bilan TO'QNASHMAYDI.
def _received_purchase(db, emp, prod, sup, qty, cost):
    from app.models.purchasing import PurchaseItem
    pur = purchases_api.create_purchase(PurchaseCreate(
        supplier_id=sup.id, status="received",
        items=[PurchaseItemIn(product_id=prod.id, qty=qty, unit_cost=cost)]), emp, db)
    it = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pur.id).first()
    return pur, it.id


def _edit_qty(db, emp, pur_id, item_id, new_qty, cost, cu=None):
    from app.api.v1.purchases import PItemEdit, PurchaseEdit
    return purchases_api.edit_purchase(pur_id, PurchaseEdit(
        items=[PItemEdit(id=item_id, qty=new_qty, unit_cost=cost)], removed=[], client_uuid=cu), emp, db)


def _pr_legs(db, till):
    return db.query(CashLedgerEntry).filter(
        CashLedgerEntry.source_type == "PURCHASE_RETURN", CashLedgerEntry.cash_account_id == till.id)


def test_purchase_return_first(db, cashenv):
    from app.models.purchasing import PurchaseReturn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)   # OUT 100000 -> till 100000
    before = bal(db, cashenv, till)
    _edit_qty(db, emp, pur.id, item, 8, 10000)   # 100k -> 80k => qaytarish 20000
    legs = _pr_legs(db, till).all()
    assert len(legs) == 1
    leg = legs[0]
    assert leg.direction == "IN" and leg.category == "PURCHASE_RETURN" and leg.amount == Decimal("20000.00")
    assert leg.reverses_id is None                       # reversal EMAS
    assert bal(db, cashenv, till) == before + Decimal("20000.00")
    prs = db.query(PurchaseReturn).filter(PurchaseReturn.purchase_id == pur.id).all()
    assert len(prs) == 1 and prs[0].amount == Decimal("20000.00")
    assert leg.source_id == prs[0].id                    # ledger source_id == return HODISA id'si
    assert leg.source_id != pur.id                       # asl xarid id'si EMAS


def test_purchase_return_second_independent(db, cashenv):
    # §07 ssenariysi: xarid 100k, qaytarish #1 20k, qaytarish #2 30k — MUSTAQIL leg'lar, TO'QNASHUV YO'Q
    from app.models.purchasing import PurchaseReturn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    _edit_qty(db, emp, pur.id, item, 8, 10000)   # qaytarish #1 = 20000
    _edit_qty(db, emp, pur.id, item, 5, 10000)   # 80k -> 50k => qaytarish #2 = 30000
    legs = _pr_legs(db, till).all()
    assert len(legs) == 2
    assert sorted(l.amount for l in legs) == [Decimal("20000.00"), Decimal("30000.00")]
    assert legs[0].source_id != legs[1].source_id                       # mustaqil manba id'lari
    assert all(l.leg_index == 0 and l.source_type == "PURCHASE_RETURN" for l in legs)
    assert db.query(PurchaseReturn).filter(PurchaseReturn.purchase_id == pur.id).count() == 2


def test_purchase_return_duplicate_first(db, cashenv):
    from app.models.purchasing import PurchaseReturn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    _edit_qty(db, emp, pur.id, item, 8, 10000)   # qaytarish 20000
    mid = bal(db, cashenv, till)
    _edit_qty(db, emp, pur.id, item, 8, 10000)   # AYNAN o'sha tahrir -> konvergensiya delta=0 (idempotent)
    assert _pr_legs(db, till).count() == 1          # ikkinchi qaytarish YO'Q
    assert bal(db, cashenv, till) == mid            # kassa o'zgarmadi
    assert db.query(PurchaseReturn).filter(PurchaseReturn.purchase_id == pur.id).count() == 1


def test_purchase_return_duplicate_second(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    _edit_qty(db, emp, pur.id, item, 8, 10000)   # #1
    _edit_qty(db, emp, pur.id, item, 5, 10000)   # #2
    mid = bal(db, cashenv, till)
    _edit_qty(db, emp, pur.id, item, 5, 10000)   # #2 replay -> delta 0
    assert _pr_legs(db, till).count() == 2
    assert bal(db, cashenv, till) == mid


def test_purchase_and_return_coexist(db, cashenv):
    # ASL FIX: PURCHASE·purchase_id·0 (OUT) va PURCHASE_RETURN·return_id·0 (IN) bir xil xarid uchun
    # BIRGA yashaydi — ilgari ikkalasi PURCHASE·purchase_id·0 bo'lib cle_uq_business'da to'qnashardi.
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    _edit_qty(db, emp, pur.id, item, 8, 10000)   # to'qnashuv bo'lганda bu IntegrityError bilan yiqilardi
    out_leg = db.query(CashLedgerEntry).filter(
        CashLedgerEntry.source_type == "PURCHASE", CashLedgerEntry.source_id == pur.id,
        CashLedgerEntry.cash_account_id == till.id).one()
    ret_leg = _pr_legs(db, till).one()
    assert out_leg.category == "PURCHASE_OUT" and out_leg.direction == "OUT"
    assert ret_leg.category == "PURCHASE_RETURN" and ret_leg.direction == "IN"
    assert ret_leg.source_id != pur.id           # qaytarish manbasi asl xarid EMAS


def test_purchase_return_partial_not_reversal(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    _edit_qty(db, emp, pur.id, item, 7, 10000)   # 100k -> 70k, QISMAN qaytarish 30000
    leg = _pr_legs(db, till).one()
    assert leg.amount == Decimal("30000.00")     # faqat delta (butun 100k EMAS)
    assert leg.reverses_id is None               # reversal EMAS (mustaqil IN·PURCHASE_RETURN)
    db.refresh(pur)
    assert pur.status.value == "received" and pur.total == Decimal("70000.00")   # hali received, qisman


def test_purchase_return_full_cancel(db, cashenv):
    from app.api.v1.purchases import PurchaseEdit
    from app.models.purchasing import PurchaseReturn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    before = bal(db, cashenv, till)   # 100000
    purchases_api.edit_purchase(pur.id, PurchaseEdit(items=[], removed=[item]), emp, db)  # to'liq bekor
    leg = _pr_legs(db, till).one()
    assert leg.amount == Decimal("100000.00")   # to'liq naqd qaytdi
    assert bal(db, cashenv, till) == before + Decimal("100000.00")
    assert db.query(PurchaseReturn).filter(PurchaseReturn.purchase_id == pur.id).count() == 1


def test_purchase_return_rollback_atomic(db, cashenv):
    # commit=False: hook leg'ni FLUSH qiladi (chaqiruvchi txn'iga qo'shiladi), lekin COMMIT qilmaydi —
    # chaqiruvchi rollback qilса, leg SIZMAYDI (source+ledger atomik).
    from app.services.cash import retrofit as _cr
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    pid = uuid.uuid4()
    _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=pid, cash_amount=50000)  # create OUT leg
    db.commit()
    _cr.on_purchase_return(db, emp, branch_id=br.id, purchase_id=pid, purchase_return_id=uuid.uuid4(), cash_amount=15000)
    assert _pr_legs(db, till).count() == 1    # flush qilingan (bor)
    db.rollback()
    assert _pr_legs(db, till).count() == 0    # rollback -> yo'q (auto-commit qilinmagan)


def _new_tenant(db, cashenv):
    from app.models.auth import Role
    from app.models.org import Company
    co = Company(name="T2 Co", code="t2" + _hex(), currency="UZS")
    db.add(co); db.flush()
    role = Role(code="cashier_" + _hex(), name="Cashier2")
    db.add(role); db.flush()
    emp = Employee(company_id=co.id, full_name="T2 Kassir", role_id=role.id)
    db.add(emp); db.flush()
    br = Branch(company_id=co.id, code="R" + _hex(), name="T2 filial")
    db.add(br); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS",
                       status="ACTIVE", created_at=cashenv.now)
    db.add(till); db.commit()
    return emp, br, till


def test_purchase_return_tenant_isolation(db, cashenv):
    from app.services.cash import retrofit as _cr
    emp1, br1, till1 = provision(db, cashenv)
    _open_shift(db, emp1, 100000)
    emp2, br2, till2 = _new_tenant(db, cashenv)
    _cr.on_shift_open(db, emp2, branch_id=br2.id, legacy_shift_id=uuid.uuid4(), opening_cash=100000)
    db.flush()
    pid = uuid.uuid4()        # AYNAN bir xil purchase_id VA return_id, IKKI tenant
    same_ret = uuid.uuid4()
    _cr.on_cash_purchase(db, emp1, branch_id=br1.id, purchase_id=pid, cash_amount=40000)   # tenant1 OUT
    _cr.on_cash_purchase(db, emp2, branch_id=br2.id, purchase_id=pid, cash_amount=40000)   # tenant2 OUT (same pid)
    _cr.on_purchase_return(db, emp1, branch_id=br1.id, purchase_id=pid, purchase_return_id=same_ret, cash_amount=10000)
    _cr.on_purchase_return(db, emp2, branch_id=br2.id, purchase_id=pid, purchase_return_id=same_ret, cash_amount=10000)
    db.commit()
    # cle_uq_business (tenant_id, ...) — bir xil source_id ikki tenantда TO'QNASHMAYDI
    assert _pr_legs(db, till1).count() == 1
    assert _pr_legs(db, till2).count() == 1


def test_purchase_return_source_uniqueness(db, cashenv):
    from app.services.cash import retrofit as _cr
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    pid = uuid.uuid4()
    _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=pid, cash_amount=50000)   # create OUT leg
    pr_id = uuid.uuid4()
    _cr.on_purchase_return(db, emp, branch_id=br.id, purchase_id=pid, purchase_return_id=pr_id, cash_amount=10000)
    db.commit()
    r2 = _cr.on_purchase_return(db, emp, branch_id=br.id, purchase_id=pid, purchase_return_id=pr_id, cash_amount=10000)  # bir xil manba
    assert r2.is_duplicate                       # cle_uq_business -> yangi leg EMAS
    assert _pr_legs(db, till).count() == 1
    _cr.on_purchase_return(db, emp, branch_id=br.id, purchase_id=pid, purchase_return_id=uuid.uuid4(), cash_amount=5000)  # boshqa manba
    db.commit()
    assert _pr_legs(db, till).count() == 2       # mustaqil leg


def test_debt_purchase_reduction_no_return_leg(db, cashenv):
    # `not _charged` GUARD (load-bearing): QARZ (debt) xarid kamaytirilса kassa TEGILMAYDI — qaytarish
    # EMAS, AP tuzatish (naqd create'да chiqмаган; SupplierLedger orqali balans kamaydi). Guard olib
    # tashlansa bu test yiqiladi (phantom IN·PURCHASE_RETURN paydo bo'lardi -> SUPPLIER_OUT bilan ikki hisob).
    from app.api.v1.purchases import SupplierPaymentIn as _SPI
    from app.models.purchasing import PurchaseItem, PurchaseReturn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    prod, sup = _setup_product(db, cashenv)
    pur = purchases_api.create_purchase(PurchaseCreate(
        supplier_id=sup.id, status="debt",
        items=[PurchaseItemIn(product_id=prod.id, qty=10, unit_cost=10000)]), emp, db)   # charge 100k, paid 0
    purchases_api.pay_supplier(sup.id, _SPI(amount=80000, method="cash"), emp, db)         # paid_amount=80000 (partial)
    item = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pur.id).first().id
    _edit_qty(db, emp, pur.id, item, 7, 10000)   # 100k -> 70k: paid(80k)-new(70k)=10k>0 LEKIN _charged -> guard
    assert _pr_legs(db, till).count() == 0        # PHANTOM ledger leg YO'Q
    # PurchaseReturn ROW ham yaratilmaydi — bu `not _charged` guard'ni HAQIQATAN pin qiladi: OUT-leg
    # gate (Fix-2) faqat ledger leg'ni to'sadi, row'ni EMAS; guard olib tashlansa debt xarid uchun
    # soxta PurchaseReturn row yaratilib bu assert yiqiladi (§11 re-review topilmasi).
    assert db.query(PurchaseReturn).filter(PurchaseReturn.purchase_id == pur.id).count() == 0


def test_purchase_return_skips_without_out_leg(db, cashenv):
    # Mos OUT·PURCHASE_OUT bo'lmasa (mobil receiving naqd xaridi / parallel-run pre-cutover) qaytarish
    # PHANTOM naqd yozmaydi — hook skip qiladi (kassa o'zgarmaydi). §11 topilma: receiving on_cash_purchase
    # chaqirmaydi -> _charged=False bo'lса ham OUT leg yo'q.
    from app.services.cash import retrofit as _cr
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    before = bal(db, cashenv, till)
    r = _cr.on_purchase_return(db, emp, branch_id=br.id, purchase_id=uuid.uuid4(),   # OUT leg YO'Q
                               purchase_return_id=uuid.uuid4(), cash_amount=20000)
    assert r is None
    assert _pr_legs(db, till).count() == 0
    assert bal(db, cashenv, till) == before       # kassa o'zgarmadi (phantom IN yo'q)


def test_purchase_return_cancel_is_one_shot(db, cashenv):
    # To'liq bekordan keyin xaridni QAYTA tahrirlab bo'lmaydi (deleted_at) — IKKINCHI PurchaseReturn
    # yozilmaydi. §11 topilma: guard pre-lock (line 367) + qulf OSTIDA qayta tekshir (race'ga qarshi).
    from fastapi import HTTPException
    from app.api.v1.purchases import PurchaseEdit
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    purchases_api.edit_purchase(pur.id, PurchaseEdit(items=[], removed=[item]), emp, db)  # to'liq bekor -> 1 return
    assert _pr_legs(db, till).count() == 1
    after = bal(db, cashenv, till)
    with pytest.raises(HTTPException) as ei:
        purchases_api.edit_purchase(pur.id, PurchaseEdit(items=[], removed=[]), emp, db)  # bekor qilinganni qayta tahrir
    assert ei.value.status_code == 404
    db.rollback()
    assert _pr_legs(db, till).count() == 1        # IKKINCHI qaytarish YO'Q
    assert bal(db, cashenv, till) == after


# ── receiving naqd xaridi (OUT·PURCHASE_OUT) — §07 create-side teshigini receiving'да yopadi ──
def _receive(db, emp, prod, qty, cost, payment="cash", cu=None, supplier_id=None):
    from app.api.v1 import receiving as rec_api
    from app.api.v1.receiving import CommitIn, CommitItem
    return rec_api.commit(CommitIn(
        items=[CommitItem(product_id=prod.id, qty=qty, unit_cost=cost)],
        payment=payment, client_uuid=cu, supplier_id=supplier_id), emp, db)


def _out_leg(db, till, purchase_id=None):
    q = db.query(CashLedgerEntry).filter(
        CashLedgerEntry.category == "PURCHASE_OUT", CashLedgerEntry.cash_account_id == till.id)
    if purchase_id is not None:
        q = q.filter(CashLedgerEntry.source_id == purchase_id)
    return q


def test_receiving_cash_creates_out_leg(db, cashenv):   # §08.1
    from app.models.purchasing import Purchase
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    before = bal(db, cashenv, till)
    r = _receive(db, emp, prod, qty=10, cost=10000)   # total 100000
    pid = uuid.UUID(r["purchase_id"])
    leg = _out_leg(db, till, pid).one()
    assert leg.direction == "OUT" and leg.category == "PURCHASE_OUT"
    assert leg.source_type == "PURCHASE" and leg.source_id == pid and leg.leg_index == 0
    assert bal(db, cashenv, till) == before - Decimal("100000.00")
    pur = db.get(Purchase, pid)
    assert pur.status.value == "received" and pur.paid_amount == Decimal("100000.00")


def test_receiving_cash_amount_equals_persisted(db, cashenv):   # §08.2
    from app.models.purchasing import Purchase
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 500000)
    prod, sup = _setup_product(db, cashenv)
    r = _receive(db, emp, prod, qty=7, cost=13000)   # total 91000
    pid = uuid.UUID(r["purchase_id"])
    pur = db.get(Purchase, pid); db.refresh(pur)
    leg = _out_leg(db, till, pid).one()
    assert leg.amount == pur.total == pur.paid_amount == Decimal("91000.00")   # PERSISTED, xom emas


def test_receiving_credit_no_cash_leg(db, cashenv):   # §08.3
    from app.models.purchasing import Purchase
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    before = bal(db, cashenv, till)
    r = _receive(db, emp, prod, qty=10, cost=10000, payment="credit", supplier_id=sup.id)
    pid = uuid.UUID(r["purchase_id"])
    assert _out_leg(db, till, pid).count() == 0    # KREDIT -> naqd leg YO'Q
    assert bal(db, cashenv, till) == before         # kassa o'zgarmadi
    pur = db.get(Purchase, pid)
    assert pur.status.value == "debt" and pur.paid_amount == Decimal("0.00")
    db.refresh(sup)
    assert sup.balance == Decimal("100000.00")      # SupplierLedger charge (qarz)


def test_receiving_duplicate_no_double_leg(db, cashenv):   # §08.4
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    cu = uuid.uuid4()
    _receive(db, emp, prod, qty=10, cost=10000, cu=cu)
    r2 = _receive(db, emp, prod, qty=10, cost=10000, cu=cu)   # dublikat (bir xil client_uuid)
    assert r2.get("duplicate") is True
    assert _out_leg(db, till).count() == 1
    assert bal(db, cashenv, till) == Decimal("100000.00")   # 200000 - 100000, BIR marta


def test_receiving_insufficient_rolls_back(db, cashenv):   # §08.5 (ledger fail -> business rollback)
    from app.models.purchasing import Purchase
    from app.models.receiving import Receiving
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 5000)    # oz naqd
    prod, sup = _setup_product(db, cashenv)
    with pytest.raises(CashPostingError) as ei:
        # client_uuid BOR, lekin konkurrent g'olib YO'Q -> fix dublikat deb MASK QILMASLIGI kerak (raise)
        _receive(db, emp, prod, qty=10, cost=10000, cu=uuid.uuid4())   # 100000 > 5000
    assert ei.value.code == CashError.INSUFFICIENT_CASH
    db.rollback()
    # ATOMIK: Purchase, Receiving, ledger — HECH BIRI yozilmagan
    assert db.query(Purchase).filter(Purchase.branch_id == br.id).count() == 0
    assert db.query(Receiving).filter(Receiving.branch_id == br.id).count() == 0
    assert _out_leg(db, till).count() == 0


def test_receiving_then_purchase_return(db, cashenv):   # §08.6
    from app.models.purchasing import PurchaseItem
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    r = _receive(db, emp, prod, qty=10, cost=10000)   # OUT 100000
    pid = uuid.UUID(r["purchase_id"])
    item = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pid).first().id
    _edit_qty(db, emp, pid, item, 8, 10000)   # 100k -> 80k => IN·PURCHASE_RETURN 20000
    ret = _pr_legs(db, till).one()
    assert ret.amount == Decimal("20000.00") and ret.source_type == "PURCHASE_RETURN"
    assert ret.reverses_id is None
    assert _out_leg(db, till, pid).count() == 1   # OUT + RETURN to'liq zanjir


def test_receiving_credit_paid_then_reduce_no_phantom(db, cashenv):   # §08.7
    from app.api.v1.purchases import SupplierPaymentIn as _SPI
    from app.models.purchasing import PurchaseItem, PurchaseReturn
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    r = _receive(db, emp, prod, qty=10, cost=10000, payment="credit", supplier_id=sup.id)   # debt, OUT YO'Q
    pid = uuid.UUID(r["purchase_id"])
    purchases_api.pay_supplier(sup.id, _SPI(amount=80000, method="cash"), emp, db)            # paid_amount=80000
    item = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pid).first().id
    _edit_qty(db, emp, pid, item, 7, 10000)   # paid(80k)-new(70k)=10k>0 LEKIN _charged + OUT leg yo'q
    assert _pr_legs(db, till).count() == 0                                                    # PHANTOM IN yo'q
    assert db.query(PurchaseReturn).filter(PurchaseReturn.purchase_id == pid).count() == 0


def test_receiving_tenant_isolation(db, cashenv):   # §08.8
    from app.models.catalog import Product, Unit
    from app.services.cash import retrofit as _cr
    emp1, br1, till1 = provision(db, cashenv)
    _open_shift(db, emp1, 200000)
    prod1, sup1 = _setup_product(db, cashenv)
    emp2, br2, till2 = _new_tenant(db, cashenv)
    _cr.on_shift_open(db, emp2, branch_id=br2.id, legacy_shift_id=uuid.uuid4(), opening_cash=200000)
    db.commit()
    unit = db.query(Unit).first()
    prod2 = Product(company_id=emp2.company_id, article_code="A" + _hex(), name="T2 mahsulot",
                    unit_id=unit.id, base_buy_price=Decimal("10000"), base_sell_price=Decimal("15000"))
    db.add(prod2); db.commit()
    r1 = _receive(db, emp1, prod1, qty=10, cost=10000)
    r2 = _receive(db, emp2, prod2, qty=10, cost=10000)
    assert _out_leg(db, till1).count() == 1
    assert _out_leg(db, till2).count() == 1
    assert _out_leg(db, till1, uuid.UUID(r2["purchase_id"])).count() == 0   # boshqa tenant legi ko'rinmaydi


def test_receiving_archived_account_rolls_back(db, cashenv):   # §08.9
    from app.models.purchasing import Purchase
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    prod, sup = _setup_product(db, cashenv)
    till.status = "ARCHIVED"; db.add(till); db.commit()   # hisob arxivlandi
    with pytest.raises(CashPostingError) as ei:
        _receive(db, emp, prod, qty=10, cost=10000)
    assert ei.value.code == CashError.ACCOUNT_ARCHIVED
    db.rollback()
    assert db.query(Purchase).filter(Purchase.branch_id == br.id).count() == 0   # qabul rollback


def test_receiving_currency_guard_direct(db, cashenv):   # §08.10
    # Receiving on_cash_purchase HECH QACHON valyuta bermaydi (hisob valyutasiga tenglashadi) -> receiving
    # orqali CURRENCY_MISMATCH yuz bermaydi. Domain-error ROLLBACK yo'lini bevosita isbotlaymiz.
    from app.services.cash import adapters
    emp, br, till = provision(db, cashenv)   # UZS till
    _open_shift(db, emp, 200000)
    with pytest.raises(CashPostingError) as ei:
        adapters.cash_purchase(db, emp, cash_account_id=till.id, source_id=uuid.uuid4(),
                               amount=10000, origin_shift_id=None, currency="USD", commit=False)
    assert ei.value.code == CashError.CURRENCY_MISMATCH
    db.rollback()
    assert _out_leg(db, till).count() == 0


def test_receiving_out_leg_rolls_back_with_txn(db, cashenv):   # §08.11 (business fail -> ledger rollback)
    # commit=False: OUT leg receiving tranzaksiyasiga qo'shiladi (flush), COMMIT qilinmaydi — chaqiruvchi
    # tomon fail bo'lса (commit'gача rollback) leg SIZMAYDI. receiving'да OUT'дан keyingi yagona amal =
    # Receiving insert + commit; commit unique-race'да fail bo'lса shu semantика leg'ni tozalaydi.
    from app.services.cash import retrofit as _cr
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 200000)
    pid = uuid.uuid4()
    _cr.on_cash_purchase(db, emp, branch_id=br.id, purchase_id=pid, cash_amount=30000)
    assert _out_leg(db, till, pid).count() == 1   # flush qilingan
    db.rollback()                                   # biznes tomon fail simulyatsiyasi
    assert _out_leg(db, till, pid).count() == 0     # leg SIZDI (atomik)


def test_receiving_ledger_failure_rolls_back_inventory(db, cashenv):   # §08.12 (ledger fail -> ombor rollback)
    from app.models.inventory import Inventory, StockMovement
    from app.models.purchasing import Purchase
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 5000)   # yetarsiz
    prod, sup = _setup_product(db, cashenv)
    assert db.query(Inventory).filter(Inventory.product_id == prod.id, Inventory.branch_id == br.id).first() is None
    with pytest.raises(CashPostingError):
        _receive(db, emp, prod, qty=10, cost=10000)   # 100000 > 5000 -> ledger fail
    db.rollback()
    # LEDGER fail -> ombor/StockMovement/Purchase HECH BIRI yozilmagan ("naqdsiz ombor yo'q")
    assert db.query(Inventory).filter(Inventory.product_id == prod.id, Inventory.branch_id == br.id).first() is None
    assert db.query(StockMovement).filter(
        StockMovement.product_id == prod.id, StockMovement.ref_type == "receiving").count() == 0
    assert db.query(Purchase).filter(Purchase.branch_id == br.id).count() == 0


def test_receiving_concurrent_duplicate_one_leg(db, cashenv):   # §06 concurrent duplicate
    from app.api.v1 import receiving as rec_api
    from app.api.v1.receiving import CommitIn, CommitItem
    from tests.cash.test_posting_service import _concurrent
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 500000)
    prod, sup = _setup_product(db, cashenv)
    cu = uuid.uuid4()
    empid, pid_prod = emp.id, prod.id

    def do(s):
        e = s.get(Employee, empid)
        return rec_api.commit(CommitIn(items=[CommitItem(product_id=pid_prod, qty=10, unit_cost=10000)],
                                       payment="cash", client_uuid=cu), e, s)
    _concurrent(cashenv.engine, do, do)
    # bir xil client_uuid -> ux_receivings_client_uuid + early-check: AYNI BITTA OUT leg (DB-kafolat)
    assert _out_leg(db, till).count() == 1
    assert bal(db, cashenv, till) == Decimal("400000.00")   # 500000 - 100000, bir marta


def test_receiving_concurrent_duplicate_insufficient_window(db, cashenv):   # §13 topilma regressiya
    # G'olib oqim kassani kamaytиргandan keyin, YUTQAZGAN dublikat (bir xil client_uuid) OUT-sufficiency'да
    # CashPostingError(INSUFFICIENT_CASH) olardi (commit-time client_uuid guard'gача yetmай) -> idempotentlik
    # BUZILARDI. Fix: CashPostingError'da client_uuid dublikat bo'lса duplicate qaytadi. Float 1x<..<2x
    # oynasi (bittasi o'tadi, ikkinchisi sufficiency'да yiqиларди). supplier_id UMUMIY -> supplier qulfида
    # serializatsiya (deterministik: yutqazgan g'olibдан keyin ishlaydi).
    from app.api.v1 import receiving as rec_api
    from app.api.v1.receiving import CommitIn, CommitItem
    from tests.cash.test_posting_service import _concurrent
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 150000)   # 1x < float < 2x
    prod, sup = _setup_product(db, cashenv)
    cu = uuid.uuid4()
    empid, pid_prod, sid = emp.id, prod.id, sup.id

    def do(s):
        e = s.get(Employee, empid)
        return rec_api.commit(CommitIn(items=[CommitItem(product_id=pid_prod, qty=10, unit_cost=10000)],
                                       payment="cash", client_uuid=cu, supplier_id=sid), e, s)
    ra, rb = _concurrent(cashenv.engine, do, do)
    # HECH BIRI hard-fail bermaydi (yutqazgan -> duplicate, INSUFFICIENT_CASH EMAS)
    assert not isinstance(ra, CashPostingError) and not isinstance(rb, CashPostingError)
    assert not isinstance(ra, Exception) and not isinstance(rb, Exception)
    # AYNI BITTA OUT leg, kassa bir marta kamaydi (150k -> 50k), yutqazgan idempotent duplicate
    assert _out_leg(db, till).count() == 1
    assert bal(db, cashenv, till) == Decimal("50000.00")
    assert (ra.get("duplicate") is True) or (rb.get("duplicate") is True)


# ═══ RUNTIME CASH GAP RETROFIT — shifts.py manual cash + purchase increase ════

def _add_move(db, emp, shift_id, mtype, amount, cu=None, reason=None):
    return shifts_api.add_cash_movement(shift_id, shifts_api.CashMove(
        type=mtype, amount=amount, reason=reason, client_uuid=cu), emp, db)


def _cashop_legs(db, till, category):
    return db.query(CashLedgerEntry).filter(
        CashLedgerEntry.cash_account_id == till.id, CashLedgerEntry.category == category)


# ── §01: shifts.py add_cash_movement — HAR TUR ledger'ga ulanadi (ilgari HECH BIRI) ──
def test_manual_cash_movement_all_types_dual_write(db, cashenv):
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])
    _add_move(db, emp, sid, "payin", 5000)         # IN·CASH_IN
    assert bal(db, cashenv, till) == Decimal("105000.00")
    _add_move(db, emp, sid, "payout", 4000)        # OUT·CASH_OUT (manual naqd topshirish)
    assert bal(db, cashenv, till) == Decimal("101000.00")
    _add_move(db, emp, sid, "expense", 1000)       # OUT·EXPENSE
    assert bal(db, cashenv, till) == Decimal("100000.00")
    _add_move(db, emp, sid, "collection", 2000)    # OUT·CASH_OUT
    assert bal(db, cashenv, till) == Decimal("98000.00")
    cats = [e.category for e in db.query(CashLedgerEntry).filter(
        CashLedgerEntry.cash_account_id == till.id).all()]
    assert cats.count("CASH_OUT") == 2 and "CASH_IN" in cats and "EXPENSE" in cats


# ── §02: MANUAL PAYOUT identity — OUT·CASH_OUT, source_type=CASH_OP, source_id=movement.id ──
def test_manual_payout_identity_and_direction(db, cashenv):
    from app.models.enums import CashMovementType as _CMT
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 50000)["id"])
    _add_move(db, emp, sid, "payout", 12000, reason="Naqd topshirish")
    leg = _cashop_legs(db, till, "CASH_OUT").one()
    assert leg.direction == "OUT" and leg.source_type == "CASH_OP" and leg.leg_index == 0
    mv = db.query(CashMovement).filter(CashMovement.shift_id == sid,
                                       CashMovement.type == _CMT.payout).one()
    assert leg.source_id == mv.id                  # runtime on_cash_op bilan bir xil biznes-kaliti
    assert bal(db, cashenv, till) == Decimal("38000.00")


# ── §07: repeated manual cash request (idempotent — client_uuid) ──────────────
def test_manual_cash_idempotent_repeat(db, cashenv):
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])
    cu = uuid.uuid4()
    _add_move(db, emp, sid, "payout", 5000, cu=cu)
    d = _add_move(db, emp, sid, "payout", 5000, cu=cu)     # takror -> dublikat
    assert d.get("duplicate") is True
    assert db.query(CashMovement).filter(CashMovement.client_uuid == cu).count() == 1
    assert _cashop_legs(db, till, "CASH_OUT").count() == 1
    assert bal(db, cashenv, till) == Decimal("95000.00")   # bir marta


# ── §07: manual payout kassadan oshsa — legacy guard rad etadi, leg SIZMAYDI ──
def test_manual_payout_exceeds_till_rejected(db, cashenv):
    from fastapi import HTTPException
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 5000)["id"])
    with pytest.raises(HTTPException) as ei:
        _add_move(db, emp, sid, "payout", 9000)   # 9000 > 5000
    assert ei.value.status_code == 400
    db.rollback()
    assert _cashop_legs(db, till, "CASH_OUT").count() == 0
    assert bal(db, cashenv, till) == Decimal("5000.00")


# ── §07: rollback on ledger error — hook DARAJASIDA yetarsiz ledger (payout) ──
def test_manual_payout_hook_insufficient_ledger(db, cashenv):
    from app.services.cash import retrofit as _cr
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)    # ledger balans 0
    with pytest.raises(CashPostingError) as ei:
        _cr.on_cash_op(db, emp, branch_id=br.id, kind="payout", amount=8000, movement_id=uuid.uuid4())
    assert ei.value.code == CashError.INSUFFICIENT_CASH
    db.rollback()
    assert _cashop_legs(db, till, "CASH_OUT").count() == 0


# ── §07: concurrent duplicate manual cash -> AYNI BITTA leg ───────────────────
def test_manual_cash_concurrent_duplicate(db, cashenv):
    from tests.cash.test_posting_service import _concurrent
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])
    cu, empid = uuid.uuid4(), emp.id

    def do(s):
        e = s.get(Employee, empid)
        return shifts_api.add_cash_movement(sid, shifts_api.CashMove(
            type="payout", amount=5000, client_uuid=cu), e, s)
    ra, rb = _concurrent(cashenv.engine, do, do)
    assert not isinstance(ra, CashPostingError) and not isinstance(rb, CashPostingError)
    assert not isinstance(ra, Exception) and not isinstance(rb, Exception)
    assert db.query(CashMovement).filter(CashMovement.client_uuid == cu).count() == 1
    assert _cashop_legs(db, till, "CASH_OUT").count() == 1        # AYNI BITTA leg
    assert bal(db, cashenv, till) == Decimal("95000.00")
    assert (ra.get("duplicate") is True) or (rb.get("duplicate") is True)


# ── §10: SOYA payout DOUBLE-POST YO'Q — supplier to'lovi soyasi CASH_OUT bermaydi ──
def test_supplier_shadow_payout_not_double_posted(db, cashenv):
    from app.api.v1.purchases import SupplierPaymentIn as _SPI
    from app.models.enums import CashMovementType as _CMT
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    prod, sup = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    _debt_purchase(db, emp, cashenv, prod, sup, qty=3, cost=10000)   # sup.balance = 30000
    purchases_api.pay_supplier(sup.id, _SPI(amount=30000, method="cash"), emp, db)
    assert _cashop_legs(db, till, "SUPPLIER_OUT").count() == 1       # haqiqiy leg
    assert _cashop_legs(db, till, "CASH_OUT").count() == 0           # soya ikki marta hisoblanmadi
    # legacy shadow CashMovement esa MAVJUD (legacy expected_cash uchun) — bu test xodimiga scope
    assert db.query(CashMovement).filter(CashMovement.employee_id == emp.id,
                                         CashMovement.type == _CMT.payout).count() == 1


# ── §03: PURCHASE INCREASE — qo'shimcha OUT leg (immutable; asl leg-0 o'zgarmaydi) ──
def _purchase_out_legs(db, till):
    return db.query(CashLedgerEntry).filter(
        CashLedgerEntry.source_type == "PURCHASE", CashLedgerEntry.category == "PURCHASE_OUT",
        CashLedgerEntry.cash_account_id == till.id).order_by(CashLedgerEntry.leg_index)


def test_purchase_increase_adds_immutable_out_leg(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 500000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)   # OUT leg-0 100000
    before = bal(db, cashenv, till)
    _edit_qty(db, emp, pur.id, item, 15, 10000)   # 100k -> 150k => qo'shimcha OUT 50000
    legs = _purchase_out_legs(db, till).all()
    assert len(legs) == 2
    assert legs[0].leg_index == 0 and legs[0].amount == Decimal("100000.00")   # ASL O'ZGARMAGAN
    assert legs[1].leg_index == 1 and legs[1].amount == Decimal("50000.00")    # faqat DELTA
    assert legs[1].source_id == pur.id and legs[1].direction == "OUT"
    assert bal(db, cashenv, till) == before - Decimal("50000.00")
    db.refresh(pur)
    assert pur.total == Decimal("150000.00")


# ── §07: repeated purchase increase (idempotent — no-op edit yangi leg qo'shmaydi) ──
def test_purchase_increase_idempotent(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 500000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    _edit_qty(db, emp, pur.id, item, 15, 10000)   # +50000 (leg-1)
    _edit_qty(db, emp, pur.id, item, 15, 10000)   # AYNI holat -> delta 0 -> yangi leg yo'q
    assert _purchase_out_legs(db, till).count() == 2   # leg-0 + leg-1 (ikkinchi edit no-op)
    assert bal(db, cashenv, till) == Decimal("350000.00")   # 500k - 150k, bir marta


# ── §07: no-op edit — na return na increase leg ──────────────────────────────
def test_purchase_edit_noop_no_leg(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 500000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)
    n0 = _purchase_out_legs(db, till).count()
    _edit_qty(db, emp, pur.id, item, 10, 10000)   # AYNAN o'sha qty/cost -> delta 0
    assert _purchase_out_legs(db, till).count() == n0   # yangi OUT leg yo'q
    assert _pr_legs(db, till).count() == 0               # return leg ham yo'q


# ── §03: increase keyin decrease -> to'g'ri net (ikki tomon birga) ────────────
def test_purchase_increase_then_decrease_net(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 500000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)   # OUT 100k
    _edit_qty(db, emp, pur.id, item, 15, 10000)   # +50k (leg-1) -> total 150k
    _edit_qty(db, emp, pur.id, item, 12, 10000)   # 150k -> 120k => return 30k
    outs = sum(l.amount for l in _purchase_out_legs(db, till).all())
    rets = sum(l.amount for l in _pr_legs(db, till).all())
    assert outs == Decimal("150000.00") and rets == Decimal("30000.00")   # net OUT = 120k
    db.refresh(pur)
    assert pur.total == Decimal("120000.00")   # = net (150k OUT - 30k RETURN)


# ── §03: leg-0 yo'q bo'lsa increase SKIP (phantom yo'q; backfill current_total orqali) ──
def test_purchase_increase_skips_without_out_leg(db, cashenv):
    from app.services.cash import retrofit as _cr
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    r = _cr.on_cash_purchase_increase(db, emp, branch_id=br.id, purchase_id=uuid.uuid4(),
                                      extra_amount=20000)   # leg-0 YO'Q
    assert r is None
    assert _purchase_out_legs(db, till).count() == 0        # phantom OUT yozilmadi


# ── §07: increase yetarsiz ledger -> BUTUN edit rollback (atomik) ─────────────
def test_purchase_increase_rollback_insufficient(db, cashenv):
    from fastapi import HTTPException
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 120000)
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)   # OUT 100k -> till 20k
    with pytest.raises(HTTPException):
        _edit_qty(db, emp, pur.id, item, 40, 10000)   # +300k, till 20k -> INSUFFICIENT_CASH
    db.rollback()
    assert _purchase_out_legs(db, till).count() == 1    # faqat leg-0 (qo'shimcha yozilmadi)
    p2 = db.get(Purchase, pur.id)
    assert p2.total == Decimal("100000.00")             # edit ROLLBACK (summa/stok tiklandi)
