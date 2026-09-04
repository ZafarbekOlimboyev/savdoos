# -*- coding: utf-8 -*-
"""Migration Phase 1 — HISTORICAL BACKFILL EXECUTOR testlari (real PostgreSQL).

§14 ssenariylar. Executor migration-owner append (ON CONFLICT idempotent). Har test o'z kompaniyasини
quradi; execute_backfill COMMIT qiladi (shared pgserver'да qoladi) -> barcha assert TENANT-scoped.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.db.cash.migration import backfill, phase0, phase1
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry, CashShift
from app.models.customers import Customer, CustomerPayment
from app.models.enums import CashMovementType, PurchaseStatus, ShiftStatus
from app.models.org import Branch, Company
from app.models.purchasing import Purchase, PurchaseReturn, Supplier, SupplierPayment
from app.models.sales import Return, Sale, SalePayment
from app.models.shifts import CashMovement, Shift


def _hex():
    return uuid.uuid4().hex[:8]


def _co(db, cur="UZS"):
    c = Company(name="Co" + _hex(), code="c" + _hex(), currency=cur); db.add(c); db.flush(); return c


def _br(db, co, active=True):
    b = Branch(company_id=co.id, code="B" + _hex(), name="Br", is_active=active); db.add(b); db.flush(); return b


def _emp(db, co, branch=None):
    e = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id); db.add(e); db.flush()
    if branch is not None:
        db.add(EmployeeBranch(employee_id=e.id, branch_id=branch.id)); db.flush()
    return e


def _provision(db, co):
    phase0.provision_accounts(db, apply=True)     # index'siz (shared DB pollution'ga qarshi); idempotent


def _shift(db, cashenv, br, emp, opening=0, closed=True, opened=None, closed_at=None):
    opened = opened or (cashenv.now - timedelta(hours=2))
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=opened,
               closed_at=(closed_at or (cashenv.now - timedelta(hours=1))) if closed else None,
               opening_cash=Decimal(str(opening)),
               status=ShiftStatus.closed if closed else ShiftStatus.open)
    db.add(sh); db.flush(); return sh


def _sale(db, cashenv, co, br, emp, amt, shift=None, sold_at=None):
    s = Sale(receipt_no="R" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
             shift_id=(shift.id if shift else None), subtotal=Decimal(str(amt)), total=Decimal(str(amt)),
             sold_at=(sold_at or (cashenv.now - timedelta(minutes=90)))); db.add(s); db.flush()
    db.add(SalePayment(sale_id=s.id, method_code="cash", amount=Decimal(str(amt)),
                       paid_at=(sold_at or cashenv.now))); db.flush(); return s


def _mv(db, cashenv, shift, mtype, amt, reason=None, cu=None, emp=None):
    m = CashMovement(shift_id=shift.id, type=mtype, amount=Decimal(str(amt)), reason=reason,
                     client_uuid=cu, employee_id=(emp.id if emp else None),
                     created_at=cashenv.now - timedelta(minutes=80)); db.add(m); db.flush(); return m


def _led(db, co):
    return db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id)


# ── §14.1/2/6/26: first exec, rerun 0-dup, deterministic uuid, dry-run parity ──
def test_first_execution_and_idempotent_rerun(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, opening=100000)
    _sale(db, cashenv, co, br, emp, 15000, shift=sh)
    _provision(db, co)
    m1 = backfill.execute_backfill(db, company_id=co.id, apply=True)
    assert m1["go_no_go"] == "GO" and m1["inserted_rows"] == 2 and m1["already_existing_rows"] == 0
    assert _led(db, co).count() == 2
    m2 = backfill.execute_backfill(db, company_id=co.id, apply=True)      # RERUN
    assert m2["inserted_rows"] == 0 and m2["already_existing_rows"] == 2  # 0 dublikat
    assert _led(db, co).count() == 2
    assert m1["manifest_hash"] == m2["manifest_hash"]                     # deterministik
    # deterministik uuid5 id
    r = _led(db, co).first()
    assert r.id == uuid.uuid5(phase1._NS, f"cle:{r.tenant_id}:{r.source_type}:{r.source_id}:{r.leg_index}")


# ── §14.4: manifest mismatch rejection ───────────────────────────────────────
def test_manifest_mismatch_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _sale(db, cashenv, co, br, emp, 15000, shift=_shift(db, cashenv, br, emp, 5000))
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=False)      # reja (yozuv yo'q)
    bad = backfill.execute_backfill(db, company_id=co.id, apply=True, approved_hash="deadbeef")
    assert bad["status"] == "REJECTED_MANIFEST_MISMATCH" and bad["wrote_ledger"] is False
    assert _led(db, co).count() == 0                                     # hech narsa yozilmadi
    # §16 fix: REJECTED cash.shifts HAM yozmasin (reconstruct_shifts gate'дан keyin)
    assert db.query(CashShift).filter(CashShift.tenant_id == co.id).count() == 0
    good = backfill.execute_backfill(db, company_id=co.id, apply=True, approved_hash=m["manifest_hash"])
    assert good["inserted_rows"] >= 1                                    # to'g'ri hash -> yoziladi
    assert db.query(CashShift).filter(CashShift.tenant_id == co.id).count() == 1   # GO -> ENDI yozildi


# ── §14.3: partial-batch failure + resume ────────────────────────────────────
def test_partial_then_resume(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 100000)
    for i in range(5):
        _sale(db, cashenv, co, br, emp, 1000 + i, shift=sh)
    _provision(db, co)
    m1 = backfill.execute_backfill(db, company_id=co.id, apply=True, batch_size=2)   # kichik batch
    first = _led(db, co).count()
    assert first == m1["inserted_rows"] and first >= 1
    m2 = backfill.execute_backfill(db, company_id=co.id, apply=True, batch_size=2)   # RESUME
    assert m2["inserted_rows"] == 0                                       # hammasi bor -> davom, dublikat yo'q
    assert _led(db, co).count() == first


# ── §14.7: tenant isolation ──────────────────────────────────────────────────
def test_tenant_isolation(db, cashenv):
    coA = _co(db); brA = _br(db, coA); empA = _emp(db, coA, brA)
    _sale(db, cashenv, coA, brA, empA, 10000, shift=_shift(db, cashenv, brA, empA, 0))
    coB = _co(db); brB = _br(db, coB); empB = _emp(db, coB, brB)
    _sale(db, cashenv, coB, brB, empB, 99999, shift=_shift(db, cashenv, brB, empB, 0))
    _provision(db, coA); _provision(db, coB)
    backfill.execute_backfill(db, company_id=coA.id, apply=True)
    assert all(r.tenant_id == coA.id for r in _led(db, coA).all())
    assert _led(db, coA).filter(CashLedgerEntry.category == "SALE").first().amount == Decimal("10000.00")
    assert _led(db, coB).count() == 0                                    # coB tegilmadi


# ── §14.8/9: explicit branch + single-branch resolution ──────────────────────
def test_explicit_and_single_branch_resolution(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _sale(db, cashenv, co, br, emp, 5000, shift=_shift(db, cashenv, br, emp, 0))   # explicit branch
    # SupplierPayment (branch yo'q) -> single-branch tenant -> shu TILL
    sup = Supplier(company_id=co.id, name="S"); db.add(sup); db.flush()
    db.add(SupplierPayment(supplier_id=sup.id, amount=Decimal("3000"), method="cash",
                           paid_at=cashenv.now, created_at=cashenv.now, employee_id=emp.id)); db.flush()
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    assert m["go_no_go"] == "GO"
    assert _led(db, co).filter(CashLedgerEntry.category == "SUPPLIER_OUT").count() == 1   # single-branch resolved


# ── §14.10: shadow-shift branch resolution (multi-branch tenant) ─────────────
def test_shadow_branch_resolution(db, cashenv):
    co = _co(db); br1 = _br(db, co); br2 = _br(db, co)   # MULTI-branch -> single-branch fallback yo'q
    emp = _emp(db, co)                                    # emp ko'p filialda (branch bog'lamaymiz)
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br1.id))
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br2.id)); db.flush()
    sh2 = _shift(db, cashenv, br2, emp, 50000)
    sup = Supplier(company_id=co.id, name="Beta"); db.add(sup); db.flush()
    db.add(SupplierPayment(supplier_id=sup.id, amount=Decimal("7000"), method="cash",
                           paid_at=cashenv.now, created_at=cashenv.now, employee_id=emp.id)); db.flush()
    _mv(db, cashenv, sh2, CashMovementType.payout, 7000, reason="Ta'minotchi · Beta", emp=emp)  # SOYA -> br2
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    leg = _led(db, co).filter(CashLedgerEntry.category == "SUPPLIER_OUT").one()
    acc = db.get(CashAccount, leg.cash_account_id)
    assert acc.branch_id == br2.id                       # soya orqali br2 TILL


# ── §14.11: EmployeeBranch resolution ────────────────────────────────────────
def test_employee_branch_resolution(db, cashenv):
    co = _co(db); br1 = _br(db, co); br2 = _br(db, co)   # multi-branch
    emp = _emp(db, co, br1)                               # emp FAQAT br1'ga bog'langan
    sup = Supplier(company_id=co.id, name="S"); db.add(sup); db.flush()
    db.add(SupplierPayment(supplier_id=sup.id, amount=Decimal("4000"), method="cash",
                           paid_at=cashenv.now, created_at=cashenv.now, employee_id=emp.id)); db.flush()
    _provision(db, co)                                    # br1 va br2 uchun TILL
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    leg = _led(db, co).filter(CashLedgerEntry.category == "SUPPLIER_OUT").one()
    acc = db.get(CashAccount, leg.cash_account_id)
    assert acc.branch_id == br1.id                       # employee sole branch


# ── §14.12: ambiguous account -> REVIEW (never guess) ────────────────────────
def test_ambiguous_account_review(db, cashenv):
    co = _co(db); br1 = _br(db, co); br2 = _br(db, co)   # multi-branch
    emp = _emp(db, co)                                    # emp bog'lanmagan (0 branch)
    sup = Supplier(company_id=co.id, name="S"); db.add(sup); db.flush()
    db.add(SupplierPayment(supplier_id=sup.id, amount=Decimal("4000"), method="cash",
                           paid_at=cashenv.now, created_at=cashenv.now, employee_id=emp.id)); db.flush()
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    assert any(r["severity"] == "REVIEW" for r in m["review"])           # aniqlanmadi -> REVIEW
    assert _led(db, co).filter(CashLedgerEntry.category == "SUPPLIER_OUT").count() == 0  # yozilmadi (taxmin yo'q)


# ── §14.13: opening precedes same-timestamp OUT (deterministik tartib) ────────
def test_opening_before_same_time_out(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t = cashenv.now - timedelta(hours=2)
    sh = _shift(db, cashenv, br, emp, 3000, opened=t, closed_at=cashenv.now)   # opening 3000 @ t
    m = CashMovement(shift_id=sh.id, type=CashMovementType.expense, amount=Decimal("3000"),
                     reason="x", created_at=t)          # expense 3000 @ AYNI t
    db.add(m); db.flush()
    _provision(db, co)
    mm = backfill.execute_backfill(db, company_id=co.id, apply=True)
    # OPENING (SHIFT_OPEN rank 0) BIRINCHI -> +3000 keyin -3000 = 0 (manfiy emas). Expense oldin bo'lса
    # -3000 -> MANFIY bo'lardi. Shu bois MANFIY review YO'Q -> tartib to'g'ri.
    assert not any("MANFIY" in r["reason"] for r in mm["review"] if isinstance(r.get("reason"), str))


# ── §14.14/15/16: ON_SHIFT / OFF_SHIFT out-of-window / no-shift ──────────────
def test_shift_attribution(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 100000, opened=cashenv.now - timedelta(hours=2),
                closed_at=cashenv.now - timedelta(hours=1))
    _sale(db, cashenv, co, br, emp, 5000, shift=sh, sold_at=cashenv.now - timedelta(minutes=90))  # IN window
    _sale(db, cashenv, co, br, emp, 6000, shift=sh, sold_at=cashenv.now - timedelta(days=5))       # OUT window
    _sale(db, cashenv, co, br, emp, 7000, shift=None)                                              # no shift
    _provision(db, co)
    backfill.execute_backfill(db, company_id=co.id, apply=True)
    by_amt = {r.amount: r.posting_kind for r in _led(db, co).filter(CashLedgerEntry.category == "SALE").all()}
    assert by_amt[Decimal("5000.00")] == "ON_SHIFT"
    assert by_amt[Decimal("6000.00")] == "OFF_SHIFT"     # oynadan tashqarida -> OFF_SHIFT
    assert by_amt[Decimal("7000.00")] == "OFF_SHIFT"     # shiftsiz -> OFF_SHIFT


# ── §14.17/18/19: T0 straddle -> REVIEW; before T0 in; at/after T0 not inserted ──
def test_t0_boundary_and_straddle(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    # yopiq smena, sotuvlar t0 atrofida
    sh = _shift(db, cashenv, br, emp, 0, opened=cashenv.now - timedelta(hours=3),
                closed_at=cashenv.now - timedelta(hours=2))
    _sale(db, cashenv, co, br, emp, 1000, shift=sh, sold_at=cashenv.now - timedelta(hours=2, minutes=30))  # < T0
    _sale(db, cashenv, co, br, emp, 2000, shift=None, sold_at=cashenv.now + timedelta(hours=1))            # >= T0
    _provision(db, co)
    t0 = cashenv.now.isoformat()
    m = backfill.execute_backfill(db, company_id=co.id, apply=True, t0=t0)
    sales = _led(db, co).filter(CashLedgerEntry.category == "SALE").all()
    assert len(sales) == 1 and sales[0].amount == Decimal("1000.00")     # faqat < T0
    # straddle: OCHIQ smena T0'ни kesadi -> REVIEW, yozilmaydi
    co2 = _co(db); br_s = _br(db, co2); emp_s = _emp(db, co2, br_s)
    sh_open = _shift(db, cashenv, br_s, emp_s, 50000, closed=False, opened=cashenv.now - timedelta(hours=1))
    _provision(db, co2)
    m2 = backfill.execute_backfill(db, company_id=co2.id, apply=True, t0=cashenv.now.isoformat())
    assert any("T0" in r["reason"] for r in m2["review"])
    assert _led(db, co2).filter(CashLedgerEntry.category == "OPENING").count() == 0   # straddle -> yozilmadi


# ── §14.20: negative historical running cash -> REVIEW but faithful ──────────
def test_negative_running_review_but_faithful(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 0)                  # opening 0
    ret = Return(return_no="RET" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
                 refund_method="cash", total=Decimal("5000")); db.add(ret); db.flush()   # OUT 5000 -> manfiy
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    assert any("MANFIY" in r["reason"] for r in m["review"])             # manfiy -> REVIEW
    assert _led(db, co).filter(CashLedgerEntry.category == "REFUND").count() == 1  # SODIQ yoziladi (clamp yo'q)


# ── §14.21/22/23: refund/supplier/debt SHADOW no double count ────────────────
def test_shadows_no_double_count(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 100000)
    ret = Return(return_no="RET" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
                 refund_method="cash", total=Decimal("4000")); db.add(ret); db.flush()
    _mv(db, cashenv, sh, CashMovementType.payout, 4000, reason=f"Qaytarish {ret.return_no}")   # refund soya
    sup = Supplier(company_id=co.id, name="S"); db.add(sup); db.flush()
    db.add(SupplierPayment(supplier_id=sup.id, amount=Decimal("6000"), method="cash",
                           paid_at=cashenv.now, created_at=cashenv.now, employee_id=emp.id)); db.flush()
    _mv(db, cashenv, sh, CashMovementType.payout, 6000, reason="Ta'minotchi · S")             # supplier soya
    cust = Customer(company_id=co.id, code="M" + _hex(), full_name="Ali", credit_balance=Decimal("0")); db.add(cust); db.flush()
    db.add(CustomerPayment(customer_id=cust.id, amount=Decimal("3000"), method="cash",
                           paid_at=cashenv.now, created_at=cashenv.now, employee_id=emp.id)); db.flush()
    _mv(db, cashenv, sh, CashMovementType.payin, 3000, reason="Qarz to'lovi · Ali")           # debt soya
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    assert _led(db, co).filter(CashLedgerEntry.category == "REFUND").count() == 1
    assert _led(db, co).filter(CashLedgerEntry.category == "SUPPLIER_OUT").count() == 1
    assert _led(db, co).filter(CashLedgerEntry.category == "DEBT_IN").count() == 1
    assert _led(db, co).filter(CashLedgerEntry.category.in_(("CASH_IN", "CASH_OUT"))).count() == 0  # soya yo'q
    assert backfill.verify_backfill(db, m, company_id=co.id)["no_shadow_leg_leaked"] is True   # §16 fix: soya sizmadi


# ── §14.24/25: edited/cancelled purchase math ────────────────────────────────
def test_edited_and_cancelled_purchase_math(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sup = Supplier(company_id=co.id, name="S"); db.add(sup); db.flush()
    # kamaytirilган: total=60k (mutated), PurchaseReturn 40k -> OUT 100k + IN 40k = net 60k
    pur = Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=br.id, supplier_id=sup.id,
                   purchase_date=cashenv.now.date(), status=PurchaseStatus.received,
                   subtotal=Decimal("60000"), total=Decimal("60000"), paid_amount=Decimal("60000")); db.add(pur); db.flush()
    db.add(PurchaseReturn(company_id=co.id, purchase_id=pur.id, branch_id=br.id,
                          amount=Decimal("40000"), reason="edit", created_at=cashenv.now)); db.flush()
    _provision(db, co)
    backfill.execute_backfill(db, company_id=co.id, apply=True)
    out = _led(db, co).filter(CashLedgerEntry.category == "PURCHASE_OUT").one()
    ret = _led(db, co).filter(CashLedgerEntry.category == "PURCHASE_RETURN").one()
    assert out.amount == Decimal("100000.00") and ret.amount == Decimal("40000.00")   # ASL OUT + qaytarish


# ── §14.27: verification detects a non-conforming (mutated) ledger row ───────
def test_verification_detects_bad_row(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _sale(db, cashenv, co, br, emp, 5000, shift=_shift(db, cashenv, br, emp, 0))
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    # bir ledger qatorига YARAMAS id bilan qo'shamiz (deterministik EMAS) -> verify ushlashi kerak
    till = db.query(CashAccount).filter(CashAccount.tenant_id == co.id, CashAccount.type == "TILL").first()
    from sqlalchemy.dialects.postgresql import insert as _pg
    db.execute(_pg(CashLedgerEntry.__table__).values(
        id=uuid.uuid4(), tenant_id=co.id, cash_account_id=till.id, branch_id=br.id, account_type="TILL",
        shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP", source_id=uuid.uuid4(), leg_index=0,
        direction="IN", category="CASH_IN", amount=Decimal("1"), currency="UZS",
        device_occurred_at=cashenv.now, server_received_at=cashenv.now, recorded_at=cashenv.now,
        idempotency_key="bad", provenance="RECONSTRUCTION", reconstruction_reason="x",
        reconstruction_source_ref="y").on_conflict_do_nothing()); db.commit()
    v = backfill.verify_backfill(db, m, company_id=co.id)
    assert v["deterministic_ids"] is False                # yaramas id ushlandi


# ── §14.28: reconciliation zero-delta ────────────────────────────────────────
def test_reconciliation_zero_delta(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 100000)
    _sale(db, cashenv, co, br, emp, 15000, shift=sh)
    _provision(db, co)
    backfill.execute_backfill(db, company_id=co.id, apply=True)
    r = backfill.reconcile_backfill(db, company_id=co.id)
    assert r["delta_in"] == 0.0 and r["delta_out"] == 0.0 and r["unexplained_delta"] == 0.0


# ── §14.5: business-key collision (bir manba -> bitta leg) ────────────────────
def test_business_key_single_leg(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 5000)
    s = _sale(db, cashenv, co, br, emp, 10000, shift=sh)
    # bir sotuvга ikkinchi naqd payment (split) -> AGGREGATE -> bitta SALE leg
    db.add(SalePayment(sale_id=s.id, method_code="cash", amount=Decimal("2000"), paid_at=cashenv.now)); db.flush()
    _provision(db, co)
    backfill.execute_backfill(db, company_id=co.id, apply=True)
    legs = _led(db, co).filter(CashLedgerEntry.category == "SALE").all()
    assert len(legs) == 1 and legs[0].amount == Decimal("12000.00")      # bitta leg, yig'indi


# ── §14.10-parity: apply=False yozmaydi ──────────────────────────────────────
def test_apply_false_writes_nothing(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _sale(db, cashenv, co, br, emp, 5000, shift=_shift(db, cashenv, br, emp, 0))
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=False)
    assert m["wrote_ledger"] is False and m["inserted_rows"] == 0
    assert _led(db, co).count() == 0


# ── §14.29: direct-write audit — FAQAT runtime posting.py + migration backfill.py yozadi ──
def test_direct_write_audit_whitelist():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    ctor_writers, insert_writers = set(), set()
    for p in root.rglob("*.py"):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        rel = str(p.relative_to(root)).replace("\\", "/")
        if "class CashLedgerEntry" in txt:
            continue                                     # model ta'rifi — yozувчи emas
        if re.search(r"CashLedgerEntry\s*\(", txt):
            ctor_writers.add(rel)                        # ORM konstruktori (runtime posting)
        if re.search(r"insert\(\s*CashLedgerEntry", txt):
            insert_writers.add(rel)                      # pg_insert(...) (migration append)
    assert ctor_writers == {"services/cash/posting.py"}, ctor_writers
    assert insert_writers == {"db/cash/migration/backfill.py"}, insert_writers


# ═══ §16 ADVERSARIAL-REVIEW FIX REGRESSIONLARI ═══════════════════════════════

def _mkleg(**over):
    base = {"tenant_id": "t", "source_type": "SALE", "source_id": "s", "leg_index": 0, "amount": "10",
            "direction": "IN", "category": "SALE", "cash_account_id": "a", "account_branch_id": "b",
            "currency": "UZS", "posting_kind": "OFF_SHIFT", "shift_id": None,
            "device_occurred_at": "2026-01-01T00:00:00+00:00"}
    base.update(over); return base


# ── §16 fix#1: manifest hash avtoritativ ustunlarni (vaqt/currency/branch) qamraydi ──
def test_manifest_hash_covers_authoritative_columns():
    h0 = backfill._manifest_hash([_mkleg()], None, "sc")
    # faqat device_occurred_at farq qilса -> hash O'ZGARSIN (aks holда noto'g'ri vaqtli qator o'tardi)
    assert backfill._manifest_hash([_mkleg(device_occurred_at="2026-06-06T00:00:00+00:00")], None, "sc") != h0
    assert backfill._manifest_hash([_mkleg(currency="USD")], None, "sc") != h0          # currency
    assert backfill._manifest_hash([_mkleg(account_branch_id="z")], None, "sc") != h0   # branch
    assert backfill._manifest_hash([_mkleg()], None, "sc") == h0                        # deterministik


# ── §16 fix#3: batch poison -> per-row fallback (bitta xato qator qolganini yo'qotmaydi) ──
def test_batch_poison_per_row_fallback(db, cashenv, monkeypatch):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 100000)
    for i in range(4):
        _sale(db, cashenv, co, br, emp, 1000 + i, shift=sh)
    _provision(db, co)
    real, seen = backfill._insert_batch, []
    def fake(dbx, batch):
        seen.append(len(batch))
        if len(batch) > 1:
            dbx.rollback(); return None            # batch "zaharlanган" simulyatsiyasi -> fallback
        return real(dbx, batch)
    monkeypatch.setattr(backfill, "_insert_batch", fake)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True, batch_size=500)
    assert any(n > 1 for n in seen) and any(n == 1 for n in seen)   # avval batch, keyin per-row
    assert m["inserted_rows"] == _led(db, co).count() >= 5           # hamma qator baribir yozildi
    assert m["failed_rows"] == 0


# ── §16 fix#4: ON_SHIFT leg account != smena account -> OFF_SHIFT + REVIEW (jim FK-fail yo'q) ──
def test_on_shift_account_mismatch_downgrades(db, cashenv):
    sid = str(uuid.uuid4())
    window = {sid: (cashenv.now - timedelta(hours=2), cashenv.now - timedelta(hours=1))}
    leg = _mkleg(shift_id=sid, cash_account_id="ACC-B", posting_kind="ON_SHIFT",
                 device_occurred_at=(cashenv.now - timedelta(minutes=90)).isoformat())
    leg["posting_kind_proposed"] = "ON_SHIFT"
    pk, out_sid, note = backfill._attribute_shift(leg, window, set(), {sid: "ACC-A"})   # smena=ACC-A, leg=ACC-B
    assert pk == "OFF_SHIFT" and out_sid is None
    assert note is not None and note[0] == "REVIEW" and "nomuvofiq" in note[1]


# ── §16 fix#5: cross-tenant guard — resolved TILL boshqa tenant'ники bo'lса BLOCK ──
def test_resolve_account_cross_tenant_blocked(db, cashenv):
    coA = _co(db); coB = _co(db); brB = _br(db, coB)
    _provision(db, coB)                                             # coB uchun TILL
    tillB = db.query(CashAccount).filter(CashAccount.tenant_id == coB.id, CashAccount.type == "TILL").first()
    # ctx coB TILL'ini beradi, lekin leg coA tenant'ига tegishli -> guard BLOCK qilishi kerak
    ctx = {"tills": {str(brB.id): tillB}, "active_branches": {}, "emp_br": {}}
    leg = _mkleg(tenant_id=str(coA.id), branch_id=str(brB.id))
    acc, res = backfill.resolve_account(db, leg, ctx)
    assert acc is None and res[0] == "BLOCK" and "cross-tenant" in res[1]


# ── §16 fix#6-negative: soya sizsa verify uni USHLAYDI (tautologiya emas) ──
def test_verify_detects_shadow_leak(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 100000)
    shadow = _mv(db, cashenv, sh, CashMovementType.payout, 4000, reason="Qaytarish RET-X")  # client_uuid=None
    _provision(db, co)
    till = db.query(CashAccount).filter(CashAccount.tenant_id == co.id, CashAccount.type == "TILL").first()
    from sqlalchemy.dialects.postgresql import insert as _pg
    # SOYA movement'ining id'si CASH_OP leg source_id sifatida yozilса -> double-count -> verify False
    db.execute(_pg(CashLedgerEntry.__table__).values(
        id=uuid.uuid4(), tenant_id=co.id, cash_account_id=till.id, branch_id=br.id, account_type="TILL",
        shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP", source_id=shadow.id, leg_index=0,
        direction="OUT", category="CASH_OUT", amount=Decimal("4000"), currency="UZS",
        device_occurred_at=cashenv.now, server_received_at=cashenv.now, recorded_at=cashenv.now,
        idempotency_key="leak", provenance="RECONSTRUCTION", reconstruction_reason="x",
        reconstruction_source_ref="y").on_conflict_do_nothing()); db.commit()
    v = backfill.verify_backfill(db, {"inserted_rows": 1, "already_existing_rows": 0,
                                      "in_total": 0.0, "out_total": 4000.0}, company_id=co.id)
    assert v["no_shadow_leg_leaked"] is False                       # soya sizishi ushlandi


# ── §16-review fix: soya-tekshiruv (TYPE,prefiks)-scoped -> genuine expense yolg'on-pozitiv YO'Q ──
def test_shadow_check_type_scoped_no_false_positive(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, cashenv, br, emp, 100000)
    # HAQIQIY expense — reason "Qaytarish..." prefiksга mos, LEKIN type=expense (payout emas), client_uuid NULL.
    # Planner buni CASH_OP/EXPENSE leg qilib yozadi; soya-tekshiruv uni SOYA deb belgilamasligi kerak.
    _mv(db, cashenv, sh, CashMovementType.expense, 3000, reason="Qaytarish tovar buzuq")
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)
    assert _led(db, co).filter(CashLedgerEntry.category == "EXPENSE").count() == 1
    v = backfill.verify_backfill(db, m, company_id=co.id)
    assert v["no_shadow_leg_leaked"] is True and v["all_ok"] is True   # type-scoped -> yolg'on-pozitiv yo'q


# ── §16 fix#7: OCHIQ smena T0'siz ham DOIM straddle -> REVIEW (soxta closed_at yo'q) ──
def test_open_shift_always_straddle_without_t0(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _shift(db, cashenv, br, emp, 50000, closed=False, opened=cashenv.now - timedelta(hours=1))  # OCHIQ smena
    _provision(db, co)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True)   # t0=None
    assert _led(db, co).filter(CashLedgerEntry.category == "OPENING").count() == 0   # yozilmadi
    assert any(("T0" in r["reason"] or "ochiq" in r["reason"]) for r in m["review"])
    assert db.query(CashShift).filter(CashShift.tenant_id == co.id).count() == 0     # cash.shift ham yo'q
