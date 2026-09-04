# -*- coding: utf-8 -*-
"""Migration Phase 1 — Shadow Backfill / Historical Reconstruction — DRY-RUN PLANNER testlari (real PG).

§12 dagi 12 ta test. Planner HECH NARSA yozmaydi (wrote_ledger=False). Har test o'z kompaniyasini
quradi (flush, commit emas -> db fixture rollback izolyatsiya) va plan_backfill'ni SHU tenant'ga scope qiladi.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.db.cash.migration import phase0, phase1
from app.models.auth import Employee, Role
from app.models.cash import CashLedgerEntry
from app.models.customers import Customer, CustomerPayment
from app.models.enums import CashMovementType, CreditTxnType, PurchaseStatus, ShiftStatus
from app.models.org import Branch, Company, Terminal
from app.models.purchasing import Purchase, Supplier, SupplierLedger, SupplierPayment
from app.models.sales import Return, Sale, SalePayment
from app.models.shifts import CashMovement, Shift


def _hex():
    return uuid.uuid4().hex[:8]


def _co(db, cashenv, cur="UZS"):
    c = Company(name="Co" + _hex(), code="c" + _hex(), currency=cur); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="Br", is_active=True); db.add(b); db.flush(); return b


def _emp(db, co):
    e = Employee(company_id=co.id, full_name="Kassir", role_id=db.query(Role).first().id)
    db.add(e); db.flush(); return e


def _shift(db, cashenv, br, emp, opening=0, status=ShiftStatus.open):
    s = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=cashenv.now,
              opening_cash=Decimal(str(opening)), status=status)
    db.add(s); db.flush(); return s


def _sale_cash(db, cashenv, co, br, emp, amount, shift=None, sold_at=None):
    s = Sale(receipt_no="R" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
             shift_id=(shift.id if shift else None), subtotal=Decimal(str(amount)),
             total=Decimal(str(amount)), sold_at=(sold_at or cashenv.now))
    db.add(s); db.flush()
    db.add(SalePayment(sale_id=s.id, method_code="cash", amount=Decimal(str(amount)),
                       paid_at=(sold_at or cashenv.now)))
    db.flush(); return s


def _return_cash(db, cashenv, co, br, emp, total):
    r = Return(return_no="RET" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
               refund_method="cash", total=Decimal(str(total)))
    db.add(r); db.flush(); return r


def _cust_pay_cash(db, cashenv, co, amount):
    c = Customer(company_id=co.id, code="M" + _hex(), full_name="Mijoz", credit_balance=Decimal("0"))
    db.add(c); db.flush()
    p = CustomerPayment(customer_id=c.id, amount=Decimal(str(amount)), method="cash",
                        paid_at=cashenv.now, created_at=cashenv.now)
    db.add(p); db.flush(); return p


def _sup_pay_cash(db, cashenv, co, amount):
    sup = Supplier(company_id=co.id, name="S" + _hex()); db.add(sup); db.flush()
    p = SupplierPayment(supplier_id=sup.id, amount=Decimal(str(amount)), method="cash",
                        paid_at=cashenv.now, created_at=cashenv.now)
    db.add(p); db.flush(); return p


def _mv(db, cashenv, shift, mtype, amount, reason=None):
    m = CashMovement(shift_id=shift.id, type=mtype, amount=Decimal(str(amount)), reason=reason,
                     created_at=cashenv.now)
    db.add(m); db.flush(); return m


# ── §12.1 idempotent rerun ───────────────────────────────────────────────────
def test_idempotent_rerun(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=5000)
    _sale_cash(db, cashenv, co, br, emp, 12000, shift=sh)
    p1 = phase1.plan_backfill(db, company_id=co.id)
    p2 = phase1.plan_backfill(db, company_id=co.id)
    assert [l["plan_id"] for l in p1["legs"]] == [l["plan_id"] for l in p2["legs"]]  # deterministik
    assert p1["in_total"] == p2["in_total"] and p1["total_candidate_rows"] == p2["total_candidate_rows"]


# ── §12.2 business-key uniqueness ────────────────────────────────────────────
def test_business_key_uniqueness(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=5000)
    _sale_cash(db, cashenv, co, br, emp, 10000, shift=sh)
    _sale_cash(db, cashenv, co, br, emp, 20000, shift=sh)
    p = phase1.plan_backfill(db, company_id=co.id)
    keys = [(l["source_type"], l["source_id"], l["leg_index"]) for l in p["legs"]]
    assert len(keys) == len(set(keys))            # har biznes-kalit NOYOB
    assert p["duplicate_conflicts"] == []


# ── §12.3 tenant isolation ───────────────────────────────────────────────────
def test_tenant_isolation(db, cashenv):
    coA = _co(db, cashenv); brA = _br(db, coA); empA = _emp(db, coA)
    _sale_cash(db, cashenv, coA, brA, empA, 10000, shift=_shift(db, cashenv, brA, empA, 0))
    coB = _co(db, cashenv); brB = _br(db, coB); empB = _emp(db, coB)
    _sale_cash(db, cashenv, coB, brB, empB, 99999, shift=_shift(db, cashenv, brB, empB, 0))
    pA = phase1.plan_backfill(db, company_id=coA.id)
    assert pA["rows_by_source_type"].get("SALE") == 1                 # faqat coA sotuvi
    assert all(l["tenant_id"] == str(coA.id) for l in pA["legs"])     # boshqa tenant leg yo'q
    assert pA["in_total"] == 10000.0                                  # 99999 emas


# ── §12.4 no double counting (refund + soya payout) ──────────────────────────
def test_no_double_counting_refund(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=50000)
    ret = _return_cash(db, cashenv, co, br, emp, 8000)
    _mv(db, cashenv, sh, CashMovementType.payout, 8000, reason=f"Qaytarish {ret.return_no}")  # SOYA
    p = phase1.plan_backfill(db, company_id=co.id)
    refunds = [l for l in p["legs"] if l["category"] == "REFUND"]
    assert len(refunds) == 1 and refunds[0]["amount"] == 8000.0        # BIR marta (Return'дан)
    assert not any(l["category"] == "CASH_OUT" for l in p["legs"])     # payout soyasi CASH_OUT emas
    assert p["skipped_shadow_rows"] == 1                               # soya CHIQARIB TASHLANDI


# ── §12.5 charged purchase not reconstructed ─────────────────────────────────
def test_charged_purchase_not_reconstructed(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co)
    sup = Supplier(company_id=co.id, name="S" + _hex()); db.add(sup); db.flush()
    pur = Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=br.id, supplier_id=sup.id,
                   purchase_date=cashenv.now.date(), status=PurchaseStatus.received,  # to'langan -> received
                   subtotal=Decimal("30000"), total=Decimal("30000"), paid_amount=Decimal("30000"))
    db.add(pur); db.flush()
    db.add(SupplierLedger(supplier_id=sup.id, type=CreditTxnType.charge, amount=Decimal("30000"),
                          balance_after=Decimal("30000"), ref_type="purchase", ref_id=pur.id,
                          created_at=cashenv.now)); db.flush()
    p = phase1.plan_backfill(db, company_id=co.id)
    assert not any(l["category"] == "PURCHASE_OUT" for l in p["legs"])   # charge bor -> phantom yo'q


# ── §12.6 shadow movements (debt/supplier) not double-counted ────────────────
def test_shadow_movements_not_double_counted(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=100000)
    cust = _cust_pay_cash(db, cashenv, co, 5000)
    _mv(db, cashenv, sh, CashMovementType.payin, 5000, reason="Qarz to'lovi · Ali")   # debt soyasi
    sup = _sup_pay_cash(db, cashenv, co, 7000)
    _mv(db, cashenv, sh, CashMovementType.payout, 7000, reason="Ta'minotchi · Beta")  # supplier soyasi
    p = phase1.plan_backfill(db, company_id=co.id)
    assert len([l for l in p["legs"] if l["category"] == "DEBT_IN"]) == 1       # BIR marta
    assert len([l for l in p["legs"] if l["category"] == "SUPPLIER_OUT"]) == 1  # BIR marta
    assert not any(l["category"] in ("CASH_IN", "CASH_OUT") for l in p["legs"]) # soyalar CASH_* emas
    assert p["skipped_shadow_rows"] == 2


# ── §12.7 incomplete transfer (legacy'да naqd transfer YO'Q) ─────────────────
def test_no_cash_transfers(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _sale_cash(db, cashenv, co, br, emp, 10000, shift=_shift(db, cashenv, br, emp, 0))
    p = phase1.plan_backfill(db, company_id=co.id)
    # Legacy'да naqd TILL<->SAFE/TILL transfer yo'q ("transfer" endpoint ombor) -> TRANSFER leg yo'q
    assert "TRANSFER" not in p["rows_by_source_type"]
    assert not any(l["category"] == "TRANSFER" for l in p["legs"])


# ── §12.8 missing shift (shiftsiz sotuv -> OFF_SHIFT, crash emas) ─────────────
def test_missing_shift_off_shift(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _sale_cash(db, cashenv, co, br, emp, 10000, shift=None)   # shift_id yo'q
    p = phase1.plan_backfill(db, company_id=co.id)
    sale_leg = next(l for l in p["legs"] if l["category"] == "SALE")
    assert sale_leg["shift_id"] is None and sale_leg["posting_kind"] == "OFF_SHIFT"


# ── §12.9 late/off-shift historical events (shiftli -> ON_SHIFT; shiftsiz -> OFF_SHIFT) ──
def test_on_vs_off_shift_attribution(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=1000)
    _sale_cash(db, cashenv, co, br, emp, 5000, shift=sh)     # shiftli
    _sale_cash(db, cashenv, co, br, emp, 6000, shift=None)   # shiftsiz
    p = phase1.plan_backfill(db, company_id=co.id)
    sales = {l["amount"]: l["posting_kind"] for l in p["legs"] if l["category"] == "SALE"}
    assert sales[5000.0] == "ON_SHIFT" and sales[6000.0] == "OFF_SHIFT"


# ── §12.10 reconstruction metadata ───────────────────────────────────────────
def test_reconstruction_metadata(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=15000)
    p = phase1.plan_backfill(db, company_id=co.id)
    opening = next(l for l in p["legs"] if l["category"] == "OPENING")
    assert opening["provenance"] == "RECONSTRUCTION"
    assert opening["reconstruction"]["source_ref"] == f"shifts:{sh.id}"
    assert opening["reconstruction"]["reason"]                       # bo'sh emas
    assert p["reconstructed_rows"] >= 1


# ── §12.11 T0 boundary ───────────────────────────────────────────────────────
def test_t0_boundary(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=0)
    early = cashenv.now - timedelta(days=2)
    late = cashenv.now + timedelta(days=2)
    _sale_cash(db, cashenv, co, br, emp, 1000, shift=sh, sold_at=early)   # tarixiy
    _sale_cash(db, cashenv, co, br, emp, 2000, shift=sh, sold_at=late)    # live-hudud
    t0 = cashenv.now.isoformat()
    p = phase1.plan_backfill(db, company_id=co.id, t0=t0)
    sale_legs = [l for l in p["legs"] if l["category"] == "SALE"]
    assert len(sale_legs) == 1 and sale_legs[0]["amount"] == 1000.0       # faqat t0'дан OLDIN
    assert p["after_t0_deferred_to_live"] >= 1                            # t0'дан keyin -> live


# ── §12.12 negative/invalid source data ──────────────────────────────────────
def test_negative_source_data_blocks(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=cashenv.now,
               opening_cash=Decimal("-500"), status=ShiftStatus.open)   # MANFIY opening
    db.add(sh); db.flush()
    p = phase1.plan_backfill(db, company_id=co.id)
    assert any(f["code"] == "NEG_OPENING_CASH" and f["severity"] == phase0.BLOCK for f in p["block_rows"])
    assert p["go_no_go"]["decision"] == "NO-GO"                          # BLOCK -> NO-GO
    assert not any(l["category"] == "OPENING" for l in p["legs"])        # manfiy -> leg yaratilmaydi


# ── planner ledger'ga YOZMAYDI (asosiy invariant) ────────────────────────────
def test_plan_writes_no_ledger(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _shift(db, cashenv, br, emp, opening=5000)
    _sale_cash(db, cashenv, co, br, emp, 3000, shift=None)
    before = db.query(CashLedgerEntry).count()
    p = phase1.plan_backfill(db, company_id=co.id)
    assert p["wrote_ledger"] is False
    assert db.query(CashLedgerEntry).count() == before                  # BITTA leg yozilmagan


# ── §14 regressiya: tahrirlangan/bekor naqd xarid — ASL OUT + RETURN offset (ikki hisob emas) ──
def _purchase_return(db, cashenv, co, br, pur, amount):
    from app.models.purchasing import PurchaseReturn
    pr = PurchaseReturn(company_id=co.id, purchase_id=pur.id, branch_id=br.id,
                        amount=Decimal(str(amount)), reason="edit/cancel", created_at=cashenv.now)
    db.add(pr); db.flush(); return pr


def test_edited_down_purchase_original_out(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co)
    sup = Supplier(company_id=co.id, name="S" + _hex()); db.add(sup); db.flush()
    # naqd xarid 100k -> 60k'ga kamaytirilган: total=60k (MUTATED), PurchaseReturn(40k). charge YO'Q.
    pur = Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=br.id, supplier_id=sup.id,
                   purchase_date=cashenv.now.date(), status=PurchaseStatus.received,
                   subtotal=Decimal("60000"), total=Decimal("60000"), paid_amount=Decimal("60000"))
    db.add(pur); db.flush()
    _purchase_return(db, cashenv, co, br, pur, 40000)
    p = phase1.plan_backfill(db, company_id=co.id)
    out = next(l for l in p["legs"] if l["category"] == "PURCHASE_OUT")
    ret = next(l for l in p["legs"] if l["category"] == "PURCHASE_RETURN")
    assert out["amount"] == 100000.0        # ASL chiqim (60k+40k) — mutated 60k EMAS
    assert ret["amount"] == 40000.0
    assert p["net"] == -60000.0             # OUT 100k - IN 40k = 60k chiqim (haqiqiy joriy total)


def test_cancelled_purchase_out_offsets_return(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co)
    sup = Supplier(company_id=co.id, name="S" + _hex()); db.add(sup); db.flush()
    # naqd xarid to'liq BEKOR: status=cancelled, total=0, PurchaseReturn(100k). charge YO'Q.
    pur = Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=br.id, supplier_id=sup.id,
                   purchase_date=cashenv.now.date(), status=PurchaseStatus.cancelled,
                   subtotal=Decimal("0"), total=Decimal("0"), paid_amount=Decimal("100000"))
    db.add(pur); db.flush()
    _purchase_return(db, cashenv, co, br, pur, 100000)
    p = phase1.plan_backfill(db, company_id=co.id)
    out = [l for l in p["legs"] if l["category"] == "PURCHASE_OUT"]
    ret = [l for l in p["legs"] if l["category"] == "PURCHASE_RETURN"]
    assert len(out) == 1 and out[0]["amount"] == 100000.0   # cancelled ham ASL OUT'ga ega
    assert len(ret) == 1 and ret[0]["amount"] == 100000.0
    assert p["net"] == 0.0                                  # OUT 100k - IN 100k = 0 (phantom cash-IN yo'q)


def test_manual_payin_with_client_uuid_not_shadow(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=5000)
    # reason SOYA-prefiksга mos, LEKIN client_uuid BOR -> manual (soya yozувчilar client_uuid qo'ymaydi)
    db.add(CashMovement(shift_id=sh.id, type=CashMovementType.payin, amount=Decimal("2000"),
                        reason="Qarz to'lovi · qo'lda", client_uuid=uuid.uuid4(), created_at=cashenv.now))
    db.flush()
    p = phase1.plan_backfill(db, company_id=co.id)
    assert any(l["category"] == "CASH_IN" and l["amount"] == 2000.0 for l in p["legs"])  # saqlandi
    assert p["skipped_shadow_rows"] == 0                                                  # soya deb chiqarilmadi


def test_t0_tz_offset_instant_split(db, cashenv):
    from datetime import timedelta as _td, timezone as _tz
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=0)
    base = cashenv.now
    _sale_cash(db, cashenv, co, br, emp, 1000, shift=sh, sold_at=base - _td(hours=1))   # instant OLDIN
    _sale_cash(db, cashenv, co, br, emp, 2000, shift=sh, sold_at=base + _td(hours=1))   # instant KEYIN
    # t0 = base, lekin +05:00 offsetда (AYNI instant) — lexical-string boshqacha, INSTANT bir xil
    t0 = base.astimezone(_tz(_td(hours=5))).isoformat()
    p = phase1.plan_backfill(db, company_id=co.id, t0=t0)
    sales = [l for l in p["legs"] if l["category"] == "SALE"]
    assert len(sales) == 1 and sales[0]["amount"] == 1000.0    # INSTANT bo'yicha (before), lexical emas
    assert p["after_t0_deferred_to_live"] == 1
