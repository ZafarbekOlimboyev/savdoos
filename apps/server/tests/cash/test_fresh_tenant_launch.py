# -*- coding: utf-8 -*-
"""FRESH (LEDGER-NATIVE) TENANT — birinchi kundan aniq naqd custody (real PostgreSQL).

Yangi savdogar YANGI arxitekturada BIRINCHI kunidanoq ishlaydi:
  · backfill YO'Q · tarixiy TILL rekonstruksiyasi YO'Q · migration marosimi YO'Q
  · har fizik naqd hodisasi AYNAN TILL/SAFE talab qiladi (pre-T0 fallback YO'Q)

A  yangi kompaniya LEDGER-NATIVE bo'lib yaratiladi (cutover_at = onboarding lahzasi)
B  onboarding holati: kassasiz -> CASH_SETUP_REQUIRED, kassa qo'shilgach -> POS_READY
C  §21 SMOKE: 2 kassa -> TILL-02 tanlanadi -> naqd/karta/qaytarish/xarajat -> aniq matematika
D  karta/QR savdo FIZIK naqd ledgeriga TEGMAYDI
E  §14 SAFE'siz inkassa: bir oyoqli OUT YOZILMAYDI
F  SAFE ATAYLAB yaratiladi (avtomatik EMAS) va shundan keyin inkassa juft oyoqli bo'ladi
G  §22 RAD ETISHLAR: kassasiz smena / boshqa filial / arxivlangan / till_id yo'q / zid
H  §22 idempotentlik: takroriy replay ikki marta yozmaydi
I  §18 tenant izolyatsiyasi: boshqa do'kon kassasi RAD etiladi
J  §23 migration vositalari KERAK EMAS (discover/provision/backfill chaqirilmaydi)
K  §16 NAQD XARID Z-hisobotda SOXTA KAMOMAD bermaydi (ledger avtoritet)
L  ledger-native do'kon JIMGINA legacy'ga TUSHMAYDI (LEGACY_ONLY -> baland xato)
M  §9 CARRYOVER: yashikda qolgan pul IKKI MARTA hisoblanmaydi
N  §2 smenasiz naqd qarz to'lovi AYNAN custody bilan ishlaydi (custody'siz RAD)
O  §12 xarid qaytarishi ledger legini JIMGINA TUSHIRMAYDI
P  §6 inkassa: 0/1/N seyf, juft oyoq, bir xil transfer_group, jami naqd O'ZGARMAYDI
Q  §16 kengaytirilgan smoke: to'liq birinchi kun matematikasi
R  kamomad KITOBGA olinadi — keyingi smenalarga QAYTA-QAYTA yozilmaydi
S  reconciliation snapshot Z-hisobot bilan BIR XIL manbadan
T  menejer nazorati kassir ekrani bilan BIR XIL kutilgan naqd
U  smenasiz qarz to'lovi custody'si AKTOR FILIALIGA cheklangan
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
import pytest

from app.api.v1.shifts import CashMove, OpenShift, add_cash_movement, close_shift, open_shift
from app.api.v1.tills import (SafeCreate, TillCreate, TillUpdate, cash_setup_state, create_safe,
                              create_till, list_tills, update_till)
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.catalog import Product, Unit
from app.models.enums import ShiftStatus
from app.models.inventory import Inventory
from app.models.org import Branch, Company
from app.models.sales import Sale
from app.schemas.sales import SaleCreate, SaleItemIn
from app.services.cash import tenant as _t
from app.services.sales import create_sale


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


# ── FRESH tenant qurish (admin.provision bilan bir xil yo'l) ─────────────────
def _fresh_company(db):
    """Yangi do'kon: kompaniya + F01 filial + ega. admin.provision qiladigan ishning
    cash-ga tegishli qismi — `mark_ledger_native`."""
    co = Company(name="Yangi" + _hex(), code="new" + _hex(), currency="UZS")
    db.add(co); db.flush()
    br = Branch(company_id=co.id, code="F01", name="Asosiy filial", is_active=True)
    db.add(br); db.flush()
    _t.mark_ledger_native(db, co.id)          # ← admin.provision shuni chaqiradi
    role = db.query(Role).filter(Role.code == "ega").first() or db.query(Role).first()
    emp = Employee(company_id=co.id, full_name="Ega", role_id=role.id)
    db.add(emp); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id)); db.flush()
    db.commit()
    return co, br, emp


def _product(db, co, br, price="10000"):
    u = Unit(code="u" + _hex(), name="dona"); db.add(u); db.flush()
    p = Product(company_id=co.id, article_code="A" + _hex(), name="M" + _hex(), unit_id=u.id,
                base_buy_price=Decimal("6000"), base_sell_price=Decimal(price),
                tax_rate=Decimal("0"))
    db.add(p); db.flush()
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal("1000"), updated_at=_now()))
    db.commit(); return p


def _till(db, emp, br, code):
    return create_till(TillCreate(branch_id=br.id, code=code), emp=emp, db=db)


def _open(db, emp, till_id, opening="0"):
    return open_shift(OpenShift(opening_cash=Decimal(opening), till_id=uuid.UUID(str(till_id))),
                      emp=emp, db=db)


def _legs(db, co, account_id=None):
    q = db.query(CLE).filter(CLE.tenant_id == co.id)
    if account_id is not None:
        q = q.filter(CLE.cash_account_id == uuid.UUID(str(account_id)))
    return q.all()


# ═══ A) yangi kompaniya LEDGER-NATIVE ══════════════════════════════════════
def test_A_new_company_is_ledger_native(db, cashenv):
    from app.services.cash import cutover as _cut
    co, br, emp = _fresh_company(db)

    assert _t.is_ledger_native(db, co.id) is True
    cfg = _t.cash_config(db, co.id)
    assert cfg["ledger_native"] is True and cfg["cutover_at"] == cfg["onboarded_at"]
    # ASOSIY: post-T0 gardlari BIRINCHI daqiqadan FAOL -> pre-T0 fallback YO'Q
    assert _cut.cutover_reached(db, co.id) is True

    # IDEMPOTENT: qayta chaqirish mavjud T0'ni qayta yozmaydi
    first = cfg["cutover_at"]
    _t.mark_ledger_native(db, co.id); db.commit()
    assert _t.cash_config(db, co.id)["cutover_at"] == first


# ═══ B) onboarding holati ══════════════════════════════════════════════════
def test_B_onboarding_state(db, cashenv):
    co, br, emp = _fresh_company(db)
    st = cash_setup_state(emp=emp, db=db)
    assert st["ledger_native"] is True
    assert st["state"] == _t.CASH_SETUP_REQUIRED and st["cash_setup_complete"] is False
    b0 = st["branches"][0]
    assert b0["active_tills"] == 0 and b0["can_open_cash_shift"] is False
    assert b0["collection_available"] is False        # SAFE yo'q -> inkassa yo'q
    assert "nechta REAL fizik kassa" in st["question"]

    _till(db, emp, br, "TILL-01")
    st2 = cash_setup_state(emp=emp, db=db)
    assert st2["state"] == _t.POS_READY and st2["cash_setup_complete"] is True
    assert st2["branches"][0]["can_open_cash_shift"] is True


# ═══ C) §21 SMOKE: to'liq birinchi kun ═════════════════════════════════════
def test_C_day_one_smoke(db, cashenv):
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")

    t1 = _till(db, emp, br, "TILL-01")               # C) ikkita REAL kassa
    t2 = _till(db, emp, br, "TILL-02")
    assert t1["id"] != t2["id"]

    sh = _open(db, emp, t2["id"])                    # D/E) kassir TILL-02 ni tanladi
    db.commit()
    from app.models.shifts import Shift
    srow = db.get(Shift, uuid.UUID(sh["id"]))
    assert str(srow.till_id) == t2["id"]

    # F) naqd savdo 100 000
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    # G) karta savdo 50 000 — FIZIK naqdga TA'SIR QILMAYDI
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=5)],
                                    payment_method="card", client_uuid=uuid.uuid4()))
    # I) xarajat 10 000
    add_cash_movement(srow.id, CashMove(type="expense", amount=Decimal("10000"), reason="test"),
                      emp=emp, db=db)
    db.commit()

    # H) naqd qaytarish 20 000 — savdodan ikkita dona
    sale = db.query(Sale).filter(Sale.company_id == co.id,
                                 Sale.total == Decimal("100000")).first()
    from app.api.v1 import sales as sales_api
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    sales_api.create_return(ReturnCreate(original_sale_id=sale.id, refund_method="cash",
                                         items=[ReturnItemIn(product_id=prod.id, qty=2)]),
                            emp, db)
    db.commit()

    # ── FIZIK NAQD MATEMATIKASI: 0 + 100000 - 20000 - 10000 = 70000 ──────────
    legs = _legs(db, co, t2["id"])
    assert legs, "ledger legi yozilmadi"
    net = sum((Decimal(str(l.amount)) if l.direction == "IN" else -Decimal(str(l.amount)))
              for l in legs)
    assert net == Decimal("70000"), f"fizik naqd noto'g'ri: {net}"
    # karta savdosi ledgerga TUSHMAGAN (aks holda 120000 bo'lardi)
    assert not any(Decimal(str(l.amount)) == Decimal("50000") for l in legs)
    # TILL-01 (tanlanmagan kassa) UMUMAN tegilmagan
    assert _legs(db, co, t1["id"]) == []

    # K) smenani yopish
    res = close_shift(srow.id, type("X", (), {"counted_cash": Decimal("70000")})(), emp=emp, db=db)
    assert Decimal(str(res["expected_cash"])) == Decimal("70000")
    assert Decimal(str(res["difference"])) == Decimal("0")


# ═══ D) karta/QR ledgerga tegmaydi (alohida, aniq) ═════════════════════════
def test_D_non_cash_writes_no_cash_ledger(db, cashenv):
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br)
    till = _till(db, emp, br, "TILL-01")
    _open(db, emp, till["id"]); db.commit()

    before = len(_legs(db, co))
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=3)],
                                    payment_method="card", client_uuid=uuid.uuid4()))
    db.commit()
    assert len(_legs(db, co)) == before, "karta savdosi FIZIK naqd ledgeriga yozildi"


# ═══ E) §14 SAFE'siz inkassa -> bir oyoqli OUT YOZILMAYDI ═════════════════
def test_E_collection_without_safe_is_rejected(db, cashenv):
    from app.models.shifts import CashMovement
    co, br, emp = _fresh_company(db)
    till = _till(db, emp, br, "TILL-01")
    sh = _open(db, emp, till["id"], opening="50000"); db.commit()
    from app.models.shifts import Shift
    srow = db.get(Shift, uuid.UUID(sh["id"]))

    assert cash_setup_state(emp=emp, db=db)["branches"][0]["collection_available"] is False
    n_legs, n_mov = len(_legs(db, co)), db.query(CashMovement).count()

    with pytest.raises(HTTPException) as ei:          # destination_safe_id YO'Q
        add_cash_movement(srow.id, CashMove(type="collection", amount=Decimal("10000")),
                          emp=emp, db=db)
    assert ei.value.status_code in (400, 409)
    db.rollback()
    # NA legacy qator, NA ledger legi yozilgan — bir oyoqli OUT YO'Q
    assert len(_legs(db, co)) == n_legs and db.query(CashMovement).count() == n_mov


# ═══ F) SAFE ATAYLAB yaratiladi; keyin inkassa juft oyoqli ════════════════
def test_F_safe_is_explicit_then_collection_pairs(db, cashenv):
    co, br, emp = _fresh_company(db)
    till = _till(db, emp, br, "TILL-01")
    # AVTOMATIK SAFE YO'Q — kassa yaratilgani SAFE keltirib chiqarmaydi
    assert db.query(CashAccount).filter(CashAccount.tenant_id == co.id,
                                        CashAccount.type == "SAFE").count() == 0

    safe = create_safe(SafeCreate(branch_id=br.id), emp=emp, db=db)   # operator ATAYLAB so'radi
    assert safe["type"] == "SAFE" and safe["active"] is True
    assert cash_setup_state(emp=emp, db=db)["branches"][0]["collection_available"] is True

    sh = _open(db, emp, till["id"], opening="50000"); db.commit()
    from app.models.shifts import Shift
    srow = db.get(Shift, uuid.UUID(sh["id"]))
    add_cash_movement(srow.id, CashMove(type="collection", amount=Decimal("30000"),
                                        destination_safe_id=uuid.UUID(safe["id"])),
                      emp=emp, db=db)
    db.commit()

    till_net = sum((Decimal(str(l.amount)) if l.direction == "IN" else -Decimal(str(l.amount)))
                   for l in _legs(db, co, till["id"]))
    safe_net = sum((Decimal(str(l.amount)) if l.direction == "IN" else -Decimal(str(l.amount)))
                   for l in _legs(db, co, safe["id"]))
    assert till_net == Decimal("20000")        # 50000 opening - 30000 inkassa
    assert safe_net == Decimal("30000")        # seyfga TUSHDI — pul yo'qolmadi
    assert till_net + safe_net == Decimal("50000")


# ═══ G) §22 RAD ETISHLAR ═══════════════════════════════════════════════════
def test_G_rejections(db, cashenv):
    co, br, emp = _fresh_company(db)

    # 1) kassasiz smena ochish MUMKIN EMAS (fresh tenant -> post-T0 faol)
    with pytest.raises(HTTPException) as e1:
        open_shift(OpenShift(opening_cash=Decimal("0")), emp=emp, db=db)
    assert e1.value.status_code == 400 and "AYNAN kassa" in e1.value.detail

    till = _till(db, emp, br, "TILL-01")
    other = Branch(company_id=co.id, code="F02", name="Ikkinchi", is_active=True)
    db.add(other); db.flush()
    foreign = create_till(TillCreate(branch_id=other.id, code="TILL-09"), emp=emp, db=db)
    db.commit()

    # 2) boshqa FILIAL kassasi
    with pytest.raises(HTTPException) as e2:
        _open(db, emp, foreign["id"])
    assert e2.value.status_code == 400

    # 3) ARXIVLANGAN kassa
    arch = _till(db, emp, br, "TILL-OLD")
    update_till(uuid.UUID(arch["id"]), TillUpdate(active=False), emp=emp, db=db); db.commit()
    with pytest.raises(HTTPException) as e3:
        _open(db, emp, arch["id"])
    assert e3.value.status_code == 400 and "till-not-active" in e3.value.detail

    # 4) ARXIVLANGAN kassa POS ro'yxatida YO'Q
    codes = {t["code"] for t in list_tills(active_only=True, mine=True, emp=emp, db=db)}
    assert "TILL-OLD" not in codes and "TILL-01" in codes


# ═══ H) §22 idempotentlik: takroriy replay ikki marta yozmaydi ════════════
def test_H_duplicate_replay_is_idempotent(db, cashenv):
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br)
    till = _till(db, emp, br, "TILL-01")
    _open(db, emp, till["id"]); db.commit()

    cu = uuid.uuid4()
    payload = SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)], payment_method="cash",
                         client_uuid=cu)
    create_sale(db, emp, payload); db.commit()
    n_sales = db.query(Sale).filter(Sale.company_id == co.id).count()
    n_legs = len(_legs(db, co))

    create_sale(db, emp, payload)          # AYNAN o'sha client_uuid — replay
    db.commit()
    assert db.query(Sale).filter(Sale.company_id == co.id).count() == n_sales
    assert len(_legs(db, co)) == n_legs, "replay ikkinchi ledger legini yozdi"


# ═══ I) §18 tenant izolyatsiyasi ═══════════════════════════════════════════
def test_I_cross_tenant_till_rejected(db, cashenv):
    coA, brA, empA = _fresh_company(db)
    coB, brB, empB = _fresh_company(db)
    alien = create_till(TillCreate(branch_id=brB.id, code="TILL-01"), emp=empB, db=db)
    db.commit()

    with pytest.raises(HTTPException) as ei:           # A do'kon B ning kassasini ishlatolmaydi
        _open(db, empA, alien["id"])
    assert ei.value.status_code == 400

    # A ning ro'yxatida B ning kassasi KO'RINMAYDI
    ids = {t["id"] for t in list_tills(active_only=True, mine=True, emp=empA, db=db)}
    assert alien["id"] not in ids
    # cash-setup holati ham FAQAT o'z filiallarini ko'rsatadi
    st = cash_setup_state(emp=empA, db=db)
    assert {b["branch_id"] for b in st["branches"]} == {str(brA.id)}


# ═══ J) §23 migration vositalari KERAK EMAS ═══════════════════════════════
def test_J_no_migration_dependency(db, cashenv):
    """Fresh tenant to'liq ishlaydi, migration modullariga TEGMASDAN."""
    import sys
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br)
    till = _till(db, emp, br, "TILL-01")
    _open(db, emp, till["id"]); db.commit()

    called = []
    for name in ("app.db.cash.migration.backfill", "app.db.cash.migration.phase1",
                 "app.db.cash.migration.historical_till", "app.tools.cash_discover",
                 "app.tools.cash_provision"):
        mod = sys.modules.get(name)
        if mod is not None:
            for fn in ("plan_backfill", "reconcile_backfill", "resolve", "load_historical_map",
                       "propose_till_mapping", "provision_accounts"):
                if hasattr(mod, fn):
                    orig = getattr(mod, fn)

                    def _trap(*a, _n=f"{name}.{fn}", **k):
                        called.append(_n)
                        raise AssertionError(f"fresh tenant migration vositasini chaqirdi: {_n}")
                    setattr(mod, fn, _trap)
                    called.append(("__restore__", mod, fn, orig))
    try:
        create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)],
                                        payment_method="cash", client_uuid=uuid.uuid4()))
        db.commit()
    finally:
        for item in called:
            if isinstance(item, tuple) and item and item[0] == "__restore__":
                setattr(item[1], item[2], item[3])
    assert not [c for c in called if isinstance(c, str)], f"migration chaqirildi: {called}"
    assert len(_legs(db, co, till["id"])) >= 1        # va ledger legi YOZILDI


# ═══ K) §16 naqd XARID Z-hisobotda soxta kamomad bermaydi ═════════════════
def test_K_cash_purchase_does_not_create_false_shortage(db, cashenv):
    """Legacy formula FAQAT SalePayment + CashMovement ni sanaydi. Naqd xarid ledgerga OUT
    yozadi, CashMovement YOZMAYDI -> Z-hisobot xarid summasiga TENG SOXTA KAMOMAD berardi."""
    from app.api.v1.purchases import create_purchase
    from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
    from app.models.purchasing import Supplier
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br, "TILL-01")
    sh = _open(db, emp, till["id"], opening="100000"); db.commit()
    from app.models.shifts import Shift
    srow = db.get(Shift, uuid.UUID(sh["id"]))

    sup = Supplier(company_id=co.id, name="T" + _hex()); db.add(sup); db.commit()
    # NAQD xarid 30 000 — kassadan CHIQADI (ledger OUT), CashMovement YO'Q
    create_purchase(PurchaseCreate(supplier_id=sup.id, status="received",
                                   items=[PurchaseItemIn(product_id=prod.id, qty=5,
                                                         unit_cost=6000)],
                                   cash_account_id=uuid.UUID(till["id"])), emp=emp, db=db)
    db.commit()

    till_bal = sum((Decimal(str(l.amount)) if l.direction == "IN" else -Decimal(str(l.amount)))
                   for l in _legs(db, co, till["id"]))
    assert till_bal == Decimal("70000"), f"ledger fizik naqdi noto'g'ri: {till_bal}"

    # Kassir yashikda 70 000 sanaydi -> FARQ 0 bo'lishi SHART (soxta kamomad EMAS)
    res = close_shift(srow.id, type("X", (), {"counted_cash": Decimal("70000")})(), emp=emp, db=db)
    assert Decimal(str(res["expected_cash"])) == Decimal("70000"),         f"Z-hisobot soxta kamomad berdi: kutilgan={res['expected_cash']}"
    assert Decimal(str(res["difference"])) == Decimal("0")


# ═══ L) ledger-native do'kon JIMGINA legacy'ga tushmaydi ═════════════════
def test_L_ledger_native_never_degrades_silently(db, cashenv):
    from app.services.cash import mode as _mode
    from app.services.cash import tenant as _tn
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br)
    till = _till(db, emp, br, "TILL-01")
    _open(db, emp, till["id"]); db.commit()

    _mode.set_mode("LEGACY_ONLY")               # ledger yozilmaydigan global rejim
    try:
        # Qo'riqchi darajasida: BALAND xato
        with pytest.raises(_tn.LedgerUnavailable):
            _tn.require_ledger_writable(db, co.id)
        # Endpoint darajasida: naqd savdo 503 — JIMGINA legacy qator YOZILMAYDI
        n_sales = db.query(Sale).filter(Sale.company_id == co.id).count()
        with pytest.raises(HTTPException) as ei:
            create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)],
                                            payment_method="cash", client_uuid=uuid.uuid4()))
        assert ei.value.status_code == 503 and "LEDGER-NATIVE" in ei.value.detail
        db.rollback()
        assert db.query(Sale).filter(Sale.company_id == co.id).count() == n_sales
    finally:
        _mode.reset_mode()

    # LEGACY do'konga TEGMAYDI — u uchun bu holat qonuniy
    legacy = Company(name="Eski" + _hex(), code="old" + _hex(), currency="UZS")
    db.add(legacy); db.commit()
    assert _tn.is_ledger_native(db, legacy.id) is False
    _mode.set_mode("LEGACY_ONLY")
    try:
        _tn.require_ledger_writable(db, legacy.id)        # xato KO'TARMAYDI
    finally:
        _mode.reset_mode()


def _safe(db, emp, br, code="SAFE"):
    return create_safe(SafeCreate(branch_id=br.id, code=code), emp=emp, db=db)


def _bal(db, co, account_id):
    return sum((Decimal(str(l.amount)) if l.direction == "IN" else -Decimal(str(l.amount)))
               for l in _legs(db, co, account_id))


def _close(db, emp, shift_id, counted):
    return close_shift(shift_id, type("X", (), {"counted_cash": Decimal(str(counted))})(),
                       emp=emp, db=db)


# ═══ M) §9 CARRYOVER: qolgan pul ikki marta hisoblanmaydi ═════════════════
def test_M_carryover_does_not_double_count(db, cashenv):
    """Smena 1: 0 + 100000 naqd savdo -> yopiladi (100000 yashikda QOLADI).
    Smena 2: kassir 100000 SANAYDI -> bu YANGI pul EMAS. Ledger balansi 100000 bo'lib qolishi
    SHART, 200000 EMAS. `opening_cash` SANOQ, fizik IN emas."""
    from app.models.shifts import Shift
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br, "TILL-01")

    sh1 = _open(db, emp, till["id"], opening="0"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    assert _bal(db, co, till["id"]) == Decimal("100000")
    _close(db, emp, db.get(Shift, uuid.UUID(sh1["id"])).id, "100000"); db.commit()
    assert _bal(db, co, till["id"]) == Decimal("100000")   # yopish pul KO'CHIRMAYDI

    # Smena 2 — kassir AYNAN o'sha 100000 ni sanaydi
    sh2 = _open(db, emp, till["id"], opening="100000"); db.commit()
    assert _bal(db, co, till["id"]) == Decimal("100000"), "ochilish sanogi IKKI MARTA hisoblandi"

    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=5)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    assert _bal(db, co, till["id"]) == Decimal("150000")
    res = _close(db, emp, db.get(Shift, uuid.UUID(sh2["id"])).id, "150000")
    assert Decimal(str(res["difference"])) == Decimal("0")

    # Kassir HAQIQATAN pul QO'SHSA — u YOZILADI (delta > 0)
    _open(db, emp, till["id"], opening="200000"); db.commit()
    assert _bal(db, co, till["id"]) == Decimal("200000")   # +50000 qoshildi


# ═══ N) §2 smenasiz naqd qarz to'lovi AYNAN custody bilan ════════════════
def test_N_debt_payment_explicit_custody(db, cashenv):
    from app.api.v1.customers import pay_credit
    from app.models.customers import Customer, CustomerPayment
    from app.schemas.customer import CreditPayment
    co, br, emp = _fresh_company(db)
    till = _till(db, emp, br, "TILL-01")
    safe = _safe(db, emp, br)
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="Mijoz",
                  credit_balance=Decimal("500000"))
    db.add(cu); db.commit()

    # custody YO'Q + smena YO'Q -> RAD
    with pytest.raises(HTTPException) as ei:
        pay_credit(cu.id, CreditPayment(amount=30000, method="cash", client_uuid=uuid.uuid4()),
                   emp=emp, db=db)
    assert ei.value.status_code == 400
    db.rollback()

    # AYNAN SAFE korsatilsa -> IN osha seyfga
    pay_credit(cu.id, CreditPayment(amount=30000, method="cash", client_uuid=uuid.uuid4(),
                                    cash_account_id=uuid.UUID(safe["id"])), emp=emp, db=db)
    db.commit()
    assert _bal(db, co, safe["id"]) == Decimal("30000")
    assert _bal(db, co, till["id"]) == Decimal("0")
    row = db.query(CustomerPayment).filter(CustomerPayment.customer_id == cu.id).first()
    assert str(row.cash_account_id) == safe["id"]          # audit identity saqlandi

    # KARTA to'lovi FIZIK ledgerga TEGMAYDI
    n = len(_legs(db, co))
    pay_credit(cu.id, CreditPayment(amount=10000, method="card", client_uuid=uuid.uuid4()),
               emp=emp, db=db)
    db.commit()
    assert len(_legs(db, co)) == n


# ═══ O) §12 xarid qaytarishi legni jimgina tushirmaydi ═══════════════════
def test_O_purchase_return_posts_without_original_leg(db, cashenv):
    """Ledger-native do'konda BUGUNGI fizik hodisa OZI-OZIGA YETARLI — eski leg-0 bolmasa ham."""
    from app.api.v1.purchases import create_purchase, edit_purchase
    from app.api.v1.purchases import PItemEdit, PurchaseEdit
    from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
    from app.models.purchasing import Supplier
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br)
    till = _till(db, emp, br, "TILL-01")
    _open(db, emp, till["id"], opening="500000"); db.commit()
    sup = Supplier(company_id=co.id, name="T" + _hex()); db.add(sup); db.commit()

    # Xaridni leg-0 YOZILMAY yaratamiz — mobil receiving / cash aktivlashuvidan OLDIN yaratilgan
    # xarid holati. Ledger APPEND-ONLY (DB trigger DELETE ni bloklaydi), shu bois legni keyin
    # o'chirib bo'lmaydi: uni UMUMAN yozdirmaymiz.
    from app.services.cash import retrofit as _rt
    _orig_hook = _rt.on_cash_purchase
    _rt.on_cash_purchase = lambda *a, **k: None
    try:
        r = create_purchase(PurchaseCreate(supplier_id=sup.id, status="received",
                                           items=[PurchaseItemIn(product_id=prod.id, qty=10,
                                                                 unit_cost=6000)],
                                           cash_account_id=uuid.UUID(till["id"])),
                            emp=emp, db=db)
        db.commit()
    finally:
        _rt.on_cash_purchase = _orig_hook
    pid = uuid.UUID(r["id"]) if isinstance(r, dict) else r.id
    assert not db.query(CLE).filter(CLE.tenant_id == co.id, CLE.source_type == "PURCHASE",
                                    CLE.source_id == pid, CLE.leg_index == 0).first(),         "leg-0 yozilib qoldi — ssenariy noto'g'ri"
    base = _bal(db, co, till["id"])
    assert base == Decimal("500000")                        # OUT legi yozilmadi

    # Summani KAMAYTIRAMIZ -> taminotchi naqd QAYTARADI -> IN yozilishi SHART
    from app.models.purchasing import PurchaseItem
    _it = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pid).first()
    edit_purchase(pid, PurchaseEdit(items=[PItemEdit(id=_it.id, qty=5, unit_cost=6000)],
                                    cash_account_id=uuid.UUID(till["id"])), emp=emp, db=db)
    db.commit()
    assert _bal(db, co, till["id"]) > base, "qaytarish legi JIMGINA TUSHIB QOLDI"


# ═══ P) §6 inkassa: 0/1/N seyf, juft oyoq, jami o'zgarmaydi ══════════════
def test_P_collection_pairs_and_conserves_cash(db, cashenv):
    from app.models.shifts import Shift
    co, br, emp = _fresh_company(db)
    till = _till(db, emp, br, "TILL-01")
    sh = _open(db, emp, till["id"], opening="100000"); db.commit()
    srow = db.get(Shift, uuid.UUID(sh["id"]))

    # A) 0 SEYF -> RAD, ledger TEGILMAYDI
    n = len(_legs(db, co))
    with pytest.raises(HTTPException):
        add_cash_movement(srow.id, CashMove(type="collection", amount=Decimal("40000")),
                          emp=emp, db=db)
    db.rollback()
    assert len(_legs(db, co)) == n

    s1 = _safe(db, emp, br, "SAFE-01")
    other_br = Branch(company_id=co.id, code="F02", name="Ikkinchi", is_active=True)
    db.add(other_br); db.flush()
    foreign_safe = _safe(db, emp, other_br, "SAFE-09"); db.commit()

    # G) BOSHQA FILIAL seyfi -> RAD
    with pytest.raises(HTTPException):
        add_cash_movement(srow.id, CashMove(type="collection", amount=Decimal("40000"),
                                            destination_safe_id=uuid.UUID(foreign_safe["id"])),
                          emp=emp, db=db)
    db.rollback()

    # I) ARXIVLANGAN seyf -> RAD
    arch = _safe(db, emp, br, "SAFE-OLD")
    db.query(CashAccount).filter(CashAccount.id == uuid.UUID(arch["id"])).update(
        {"status": "ARCHIVED"}); db.commit()
    with pytest.raises(HTTPException):
        add_cash_movement(srow.id, CashMove(type="collection", amount=Decimal("40000"),
                                            destination_safe_id=uuid.UUID(arch["id"])),
                          emp=emp, db=db)
    db.rollback()

    # D/E/F) TOGRI inkassa — juft oyoq, bitta transfer_group, JAMI ozgarmaydi
    total_before = _bal(db, co, till["id"]) + _bal(db, co, s1["id"])
    add_cash_movement(srow.id, CashMove(type="collection", amount=Decimal("40000"),
                                        destination_safe_id=uuid.UUID(s1["id"])),
                      emp=emp, db=db)
    db.commit()
    assert _bal(db, co, till["id"]) == Decimal("60000")
    assert _bal(db, co, s1["id"]) == Decimal("40000")
    assert _bal(db, co, till["id"]) + _bal(db, co, s1["id"]) == total_before   # F) jami OZGARMADI

    groups = {l.transfer_group_id for l in _legs(db, co) if l.transfer_group_id is not None}
    assert len(groups) == 1, "juft oyoq bitta transfer_group da emas"


# ═══ Q) §16 kengaytirilgan smoke ══════════════════════════════════════════
def test_Q_extended_day_one_math(db, cashenv):
    from app.api.v1.customers import pay_credit
    from app.api.v1.purchases import create_purchase, edit_purchase
    from app.models.customers import Customer
    from app.models.purchasing import Supplier
    from app.models.shifts import Shift
    from app.api.v1.purchases import PItemEdit, PurchaseEdit
    from app.schemas.customer import CreditPayment
    from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")
    t1 = _till(db, emp, br, "TILL-01")
    t2 = _till(db, emp, br, "TILL-02")
    safe = _safe(db, emp, br)
    sh = _open(db, emp, t2["id"], opening="0"); db.commit()
    srow = db.get(Shift, uuid.UUID(sh["id"]))

    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))   # +100000
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=5)],
                                    payment_method="card", client_uuid=uuid.uuid4()))   # karta: 0
    db.commit()

    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="M",
                  credit_balance=Decimal("100000"))
    db.add(cu); db.commit()
    pay_credit(cu.id, CreditPayment(amount=30000, method="cash", client_uuid=uuid.uuid4()),
               emp=emp, db=db); db.commit()                                             # +30000

    sup = Supplier(company_id=co.id, name="T" + _hex()); db.add(sup); db.commit()
    r = create_purchase(PurchaseCreate(supplier_id=sup.id, status="received",
                                       items=[PurchaseItemIn(product_id=prod.id, qty=4,
                                                             unit_cost=5000)],
                                       cash_account_id=uuid.UUID(t2["id"])), emp=emp, db=db)
    db.commit()                                                                          # -20000
    pid = uuid.UUID(r["id"]) if isinstance(r, dict) else r.id
    from app.models.purchasing import PurchaseItem
    _it = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pid).first()
    edit_purchase(pid, PurchaseEdit(items=[PItemEdit(id=_it.id, qty=3, unit_cost=5000)],
                                    cash_account_id=uuid.UUID(t2["id"])), emp=emp, db=db)
    db.commit()                                                                          # +5000
    add_cash_movement(srow.id, CashMove(type="expense", amount=Decimal("10000"), reason="x"),
                      emp=emp, db=db); db.commit()                                       # -10000

    assert _bal(db, co, t2["id"]) == Decimal("105000")

    add_cash_movement(srow.id, CashMove(type="collection", amount=Decimal("40000"),
                                        destination_safe_id=uuid.UUID(safe["id"])),
                      emp=emp, db=db); db.commit()

    assert _bal(db, co, t2["id"]) == Decimal("65000")
    assert _bal(db, co, safe["id"]) == Decimal("40000")
    assert _bal(db, co, t2["id"]) + _bal(db, co, safe["id"]) == Decimal("105000")
    assert _bal(db, co, t1["id"]) == Decimal("0")          # tanlanmagan kassa TEGILMAGAN

    res = _close(db, emp, srow.id, "65000")
    assert Decimal(str(res["expected_cash"])) == Decimal("65000")
    assert Decimal(str(res["difference"])) == Decimal("0")


# ═══ R) BLOCKER: kamomad KEYINGI smenalarga O'TMAYDI ═════════════════════
def test_R_shortage_is_not_recharged_to_next_shift(db, cashenv):
    """Kassir yashikda ledgerdan KAM sanasa: farq KO'RINADI, lekin KEYINGI smenaga O'TMAYDI.

    Kutilgan naqd OCHILISH SANOG'IGA ankorlangani uchun har smena FAQAT O'Z oynasi uchun javob
    beradi. Yashik BALANSIGA ankorlansa, o'sha BITTA yo'qotish HAR KEYINGI smenaga qayta-qayta
    kamomad bo'lib yozilardi. Farqni yozib yuborish (ADJUSTMENT) ATAYLAB menejer+ ishi (§18)."""
    from app.models.shifts import Shift
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br, "TILL-01")

    sh1 = _open(db, emp, till["id"], opening="0"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    assert _bal(db, co, till["id"]) == Decimal("100000")

    # Yashikda 10 000 YETISHMAYDI (yo'qolgan/xato sanoq)
    res1 = _close(db, emp, db.get(Shift, uuid.UUID(sh1["id"])).id, "90000")
    db.commit()
    assert Decimal(str(res1["expected_cash"])) == Decimal("100000")
    assert Decimal(str(res1["difference"])) == Decimal("-10000")     # kamomad KO'RINDI

    # Farq ATAYLAB avtomatik kitobga OLINMAYDI (ADJUSTMENT = menejer+ nazorati, §18):
    # kassir o'zi kam sanab naqdni jimgina hisobdan chiqara olmasin. Ledger balansi
    # hal qilinmagan farqni KO'RSATIB turadi.
    assert _bal(db, co, till["id"]) == Decimal("100000")
    assert not [l for l in _legs(db, co, till["id"]) if l.category == "ADJUSTMENT"]

    # Keyingi smena: AYNAN o'sha 90000 sanaydi -> farq 0 (kamomad TAKRORLANMAYDI)
    sh2 = _open(db, emp, till["id"], opening="90000"); db.commit()
    res2 = _close(db, emp, db.get(Shift, uuid.UUID(sh2["id"])).id, "90000")
    assert Decimal(str(res2["expected_cash"])) == Decimal("90000")   # ANKOR = ochilish sanog'i
    assert Decimal(str(res2["difference"])) == Decimal("0"), "kamomad keyingi smenaga O'TDI"


# ═══ S) reconciliation snapshot Z-hisobot bilan BIR XIL ══════════════════
def test_S_reconciliation_matches_z_report(db, cashenv):
    """Kechadan pul qolgan yashikda snapshot (faqat shu smena legilari) balansdan kichik
    bo'lib, solishtiruv YOLG'ON ORTIQCHA ko'rsatardi."""
    from app.models.cash import ReconciliationRecord as RR
    from app.models.shifts import Shift
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br, "TILL-01")

    sh1 = _open(db, emp, till["id"], opening="0"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    _close(db, emp, db.get(Shift, uuid.UUID(sh1["id"])).id, "100000"); db.commit()

    # Smena 2: 100000 KECHADAN qoladi + 50000 yangi savdo
    sh2 = _open(db, emp, till["id"], opening="100000"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=5)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    s2 = db.get(Shift, uuid.UUID(sh2["id"]))
    res = _close(db, emp, s2.id, "150000"); db.commit()

    assert Decimal(str(res["expected_cash"])) == Decimal("150000")
    assert Decimal(str(res["difference"])) == Decimal("0")
    rec = db.query(RR).filter(RR.shift_id == s2.id).first()
    assert rec is not None
    # snapshot Z-hisobot bilan BIR XIL bo'lishi SHART (50000 emas!)
    assert Decimal(str(rec.ledger_balance_snapshot)) == Decimal("150000"), \
        f"snapshot Z-hisobotdan farq qildi: {rec.ledger_balance_snapshot}"
    assert Decimal(str(rec.difference)) == Decimal("0")


# ═══ T) menejer nazorati kassir ekrani bilan BIR XIL ═════════════════════
def test_T_overview_matches_cashier_screen(db, cashenv):
    """Bitta OCHIQ smena uchun kassir va menejer ikki xil 'kutilgan naqd' ko'rmasin."""
    from app.api.v1.shifts import shift_summary, shifts_overview
    from app.models.shifts import Shift
    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br, "TILL-01")

    sh1 = _open(db, emp, till["id"], opening="0"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    _close(db, emp, db.get(Shift, uuid.UUID(sh1["id"])).id, "100000"); db.commit()

    sh2 = _open(db, emp, till["id"], opening="100000"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=3)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    s2 = db.get(Shift, uuid.UUID(sh2["id"]))

    cashier_view = shift_summary(s2.id, emp=emp, db=db)
    manager_view = shifts_overview(emp=emp, db=db)
    row = next(r for r in manager_view["shifts"] if r["id"] == str(s2.id))
    assert float(cashier_view["expected"]) == float(row["expected"]), \
        f"kassir {cashier_view['expected']} vs menejer {row['expected']}"
    assert float(cashier_view["expected"]) == 130000.0     # 100000 qolgan + 30000 savdo


# ═══ U) smenasiz qarz to'lovi BOSHQA FILIAL kassasini QABUL QILMAYDI ════
def test_U_debt_custody_is_branch_scoped(db, cashenv):
    from app.api.v1.customers import pay_credit
    from app.models.customers import Customer
    from app.schemas.customer import CreditPayment
    co, br, emp = _fresh_company(db)
    _till(db, emp, br, "TILL-01")
    other = Branch(company_id=co.id, code="F02", name="Ikkinchi", is_active=True)
    db.add(other); db.flush()
    foreign = _till(db, emp, other, "TILL-09")            # BOSHQA filial kassasi
    db.commit()

    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="M",
                  credit_balance=Decimal("500000"))
    db.add(cu); db.commit()

    with pytest.raises(HTTPException) as ei:
        pay_credit(cu.id, CreditPayment(amount=30000, method="cash", client_uuid=uuid.uuid4(),
                                        cash_account_id=uuid.UUID(foreign["id"])), emp=emp, db=db)
    assert ei.value.status_code == 400
    db.rollback()
    assert _bal(db, co, foreign["id"]) == Decimal("0")    # boshqa filial kassasiga YOZILMADI
