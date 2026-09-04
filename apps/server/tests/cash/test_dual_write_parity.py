# -*- coding: utf-8 -*-
"""Migration Phase 2 — DUAL-WRITE SHADOW parity testlari (real PostgreSQL).

Legacy AVTORITET; ledger SOYA. Har live cash hodisa uchun isbotlaymiz:
  legacy physical expected cash == ledger (NORMAL) expected cash  (delta = 0).
shadow_compare mustaqil hisoblaydi (ledger'ni legacy tarafда o'qimaydi -> tautologiya emas).
Detektsiya (missing/extra/wrong), mode gate, T0 chegarasi, konkurrentlik, rollback, no-auto-repair.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.api.v1 import customers as customers_api
from app.api.v1 import purchases as purchases_api
from app.api.v1 import sales as sales_api
from app.api.v1 import shifts as shifts_api
from app.models.auth import Employee
from app.models.cash import CashLedgerEntry
from app.models.shifts import CashMovement
from app.services.cash import mode, shadow_compare as sc
from app.services.cash.errors import CashError, CashPostingError

# reusable harness (bir xil pgserver conftest)
from tests.cash.test_retrofit import (
    _add_move, _cash_sale, _customer, _debt_purchase, _edit_qty, _open_shift,
    _received_purchase, _setup_product, _stock, bal, provision,
)


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _close(db, emp, shift_id, counted):
    return shifts_api.close_shift(uuid.UUID(str(shift_id)), shifts_api.CloseShift(counted_cash=counted), emp, db)


def _refund(db, emp, sale, prod, qty):
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    return sales_api.create_return(ReturnCreate(original_sale_id=sale.id, refund_method="cash",
                                                items=[ReturnItemIn(product_id=prod.id, qty=qty)]), emp, db)


def _pay_debt(db, emp, cust, amount):
    from app.schemas.customer import CreditPayment
    return customers_api.pay_credit(cust.id, CreditPayment(amount=amount, method="cash"), emp, db)


def _pay_supplier(db, emp, sup, amount):
    from app.api.v1.purchases import SupplierPaymentIn
    return purchases_api.pay_supplier(sup.id, SupplierPaymentIn(amount=amount, method="cash"), emp, db)


# ═══ FULL LIVE SEQUENCE — the delta=0 proof (item 11/18 shape) ════════════════
def test_full_live_sequence_parity(db, cashenv):
    emp, br, till = provision(db, cashenv)
    r = _open_shift(db, emp, 500000)                       # 1) OPENING +500000
    sid = uuid.UUID(r["id"])
    prod, sup = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br, qty=200)
    sale = _cash_sale(db, emp, prod, 2)                    # 2) SALE +30000 (price 15000)
    cust = _customer(db, cashenv, credit=50000)
    _pay_debt(db, emp, cust, 20000)                        # 3) DEBT_IN +20000 (+shadow payin)
    _add_move(db, emp, sid, "payin", 5000)                # 4) CASH_IN +5000
    _add_move(db, emp, sid, "expense", 3000)              # 5) EXPENSE -3000
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)  # 6) PURCHASE_OUT -100000
    _edit_qty(db, emp, pur.id, item, 15, 10000)           # 7) increase -> PURCHASE_OUT leg-1 -50000
    _edit_qty(db, emp, pur.id, item, 12, 10000)           # 8) decrease -> PURCHASE_RETURN +30000
    _debt_purchase(db, emp, cashenv, prod, sup, qty=4, cost=10000)   # sup.balance = 40000 (debt, no cash)
    _pay_supplier(db, emp, sup, 40000)                    # 9) SUPPLIER_OUT -40000 (+shadow payout)
    _refund(db, emp, sale, prod, 2)                       # 10) REFUND -30000 (+shadow payout)
    _add_move(db, emp, sid, "payout", 7000)               # 11) CASH_OUT -7000

    # SHIFT-daraja parity (yopishдан oldin)
    cmp_sh = sc.compare_shift(db, cashenv.company_id, sid)
    assert cmp_sh["status"] == "MATCH", cmp_sh
    assert cmp_sh["delta"] == 0.0
    assert cmp_sh["ledger_expected"] == 355000.0 == cmp_sh["legacy_expected"]

    # TILL-daraja parity (eng robust — off-shift/xarid atribusiyasidan mustaqil)
    cmp_till = sc.compare_till(db, cashenv.company_id, till.id)
    assert cmp_till["status"] == "MATCH" and cmp_till["delta"] == 0.0

    _close(db, emp, sid, 355000)                          # 12) close (frozen snapshot = expected)
    cmp_sh2 = sc.compare_shift(db, cashenv.company_id, sid)
    assert cmp_sh2["delta"] == 0.0                        # close hisobни o'zgartirmadi

    # SNAPSHOT (read-only) — bu TILL snapshot ichida delta 0 bilan ko'rinadi.
    # (tenant-wide total_delta shared test-DB'да boshqa testlar till'lari tufayli 0 emas — prod'да
    #  har tenant izolyatsiya; demo (fresh tenant) tenant-wide 0'ни ko'rsatadi.)
    snap = sc.snapshot(db, company_id=cashenv.company_id)
    assert snap["kind"] == "PHASE2_SHADOW_COMPARISON_SNAPSHOT"
    till_parts = [p for t in snap["tenants"] for p in t.get("parts", [])
                  if p.get("cash_account_id") == str(till.id)]
    assert len(till_parts) == 1 and till_parts[0]["delta"] == 0.0


# ═══ PER-EVENT parity ════════════════════════════════════════════════════════
def test_sale_parity(db, cashenv):
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    prod, _ = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    _cash_sale(db, emp, prod, 3)     # 45000
    c = sc.compare_till(db, cashenv.company_id, till.id)
    assert c["status"] == "MATCH" and c["delta"] == 0.0 and c["ledger_in"] == 45000.0


def test_manual_cash_parity_all_types(db, cashenv):
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])
    _add_move(db, emp, sid, "payin", 10000)
    _add_move(db, emp, sid, "payout", 4000)
    _add_move(db, emp, sid, "expense", 3000)
    _add_move(db, emp, sid, "collection", 2000)
    c = sc.compare_shift(db, cashenv.company_id, sid)
    assert c["status"] == "MATCH" and c["delta"] == 0.0
    assert c["legacy_expected"] == 101000.0    # 100000 +10000 -4000 -3000 -2000


def test_purchase_lifecycle_parity(db, cashenv):
    # create -> increase -> decrease -> increase -> partial return -> ... net parity har qadamda
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 1000000)["id"])
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)   # 100k
    assert sc.compare_shift(db, cashenv.company_id, sid)["delta"] == 0.0
    _edit_qty(db, emp, pur.id, item, 15, 10000)   # +50k -> 150k
    assert sc.compare_shift(db, cashenv.company_id, sid)["delta"] == 0.0
    _edit_qty(db, emp, pur.id, item, 12, 10000)   # -30k -> 120k
    assert sc.compare_shift(db, cashenv.company_id, sid)["delta"] == 0.0
    _edit_qty(db, emp, pur.id, item, 20, 10000)   # +80k -> 200k
    assert sc.compare_shift(db, cashenv.company_id, sid)["delta"] == 0.0
    _edit_qty(db, emp, pur.id, item, 5, 10000)    # -150k -> 50k (partial return)
    c = sc.compare_shift(db, cashenv.company_id, sid)
    assert c["delta"] == 0.0 and c["legacy_breakdown"]["net_cash_purchases"] == 50000.0
    # asl leg-0 O'ZGARMAGAN
    legs = db.query(CashLedgerEntry).filter(CashLedgerEntry.source_type == "PURCHASE",
                                            CashLedgerEntry.source_id == pur.id,
                                            CashLedgerEntry.leg_index == 0).one()
    assert legs.amount == Decimal("100000.00")


def test_purchase_full_cancel_parity(db, cashenv):
    from app.api.v1.purchases import PurchaseEdit
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 500000)["id"])
    prod, sup = _setup_product(db, cashenv)
    pur, item = _received_purchase(db, emp, prod, sup, qty=10, cost=10000)   # 100k
    purchases_api.edit_purchase(pur.id, PurchaseEdit(items=[], removed=[item]), emp, db)   # to'liq bekor
    c = sc.compare_shift(db, cashenv.company_id, sid)
    assert c["delta"] == 0.0 and c["legacy_breakdown"]["net_cash_purchases"] == 0.0   # naqd qaytdi


def test_shadow_no_double_count_parity(db, cashenv):
    # refund/supplier/debt soya CashMovement'lari ledger'га qo'shimcha leg BERMAYDI -> delta 0
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 300000)
    prod, sup = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    sale = _cash_sale(db, emp, prod, 3)   # 45000
    cust = _customer(db, cashenv, 50000)
    _pay_debt(db, emp, cust, 20000)
    _debt_purchase(db, emp, cashenv, prod, sup, qty=3, cost=10000)
    _pay_supplier(db, emp, sup, 30000)
    _refund(db, emp, sale, prod, 1)       # 15000 refund
    c = sc.compare_till(db, cashenv.company_id, till.id)
    assert c["status"] == "MATCH" and c["delta"] == 0.0
    # ledger'да soyalarдан CASH_IN/CASH_OUT paydo bo'lmadi (faqat DEBT_IN/SUPPLIER_OUT/REFUND)
    cats = {e.category for e in db.query(CashLedgerEntry).filter(
        CashLedgerEntry.cash_account_id == till.id).all()}
    assert {"DEBT_IN", "SUPPLIER_OUT", "REFUND"} <= cats


# ═══ DETECTION (missing / extra / wrong) ═════════════════════════════════════
def test_detect_missing_ledger_via_legacy_only(db, cashenv):
    # DUAL faol: manual payout ledger leg yaratadi. Keyin LEGACY_ONLY'да yana payout -> ledger leg YO'Q
    # -> legacy chiqim oshadi, ledger o'zgarmaydi -> delta != 0 (REVIEW), missing detektsiya.
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])
    _add_move(db, emp, sid, "payin", 10000)
    assert sc.compare_shift(db, cashenv.company_id, sid)["delta"] == 0.0
    mode.set_mode("LEGACY_ONLY")
    _add_move(db, emp, sid, "expense", 5000)   # legacy yozadi, ledger NO-OP (LEGACY_ONLY)
    mode.reset_mode()
    c = sc.compare_shift(db, cashenv.company_id, sid)
    assert c["status"] == "REVIEW" and c["delta"] == 5000.0   # ledger legacy'дан 5000 KO'P (chiqim yozilmadi)


def test_event_trace_missing_and_present(db, cashenv):
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 50000)["id"])
    _add_move(db, emp, sid, "payout", 4000)
    mv = db.query(CashMovement).filter(CashMovement.shift_id == sid).order_by(
        CashMovement.created_at.desc()).first()
    tr = sc.event_trace(db, cashenv.company_id, "CASH_OP", mv.id)
    assert tr["missing"] is False and tr["ledger_leg_count"] == 1
    assert tr["legs"][0]["category"] == "CASH_OUT" and tr["legs"][0]["amount"] == 4000.0
    # yo'q hodisa
    tr2 = sc.event_trace(db, cashenv.company_id, "CASH_OP", uuid.uuid4())
    assert tr2["missing"] is True and tr2["ledger_leg_count"] == 0


def test_detect_extra_and_wrong_amount(db, cashenv):
    # to'g'ridan-to'g'ri BUZUQ NORMAL leg kiritamiz (noto'g'ri summa) -> till delta buzuladi
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    base = sc.compare_till(db, cashenv.company_id, till.id)
    assert base["delta"] == 0.0
    from sqlalchemy.dialects.postgresql import insert as _pg
    db.execute(_pg(CashLedgerEntry.__table__).values(
        id=uuid.uuid4(), tenant_id=cashenv.company_id, cash_account_id=till.id, branch_id=br.id,
        account_type="TILL", shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP",
        source_id=uuid.uuid4(), leg_index=0, direction="IN", category="CASH_IN", amount=Decimal("999"),
        currency="UZS", device_occurred_at=cashenv.now, server_received_at=cashenv.now,
        recorded_at=cashenv.now, idempotency_key="extra", provenance="NORMAL").on_conflict_do_nothing())
    db.commit()
    c = sc.compare_till(db, cashenv.company_id, till.id)
    assert c["status"] == "REVIEW" and c["delta"] == 999.0   # ortiqcha ledger IN legacy'да yo'q


# ═══ MODE GATE ═══════════════════════════════════════════════════════════════
def test_mode_legacy_only_writes_no_ledger(db, cashenv):
    emp, br, till = provision(db, cashenv)
    mode.set_mode("LEGACY_ONLY")
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])   # OPENING ledger YO'Q
    _add_move(db, emp, sid, "payin", 5000)                # ledger YO'Q
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.cash_account_id == till.id).count() == 0
    # legacy esa ishlaydi (CashMovement bor)
    assert db.query(CashMovement).filter(CashMovement.shift_id == sid).count() == 1


def test_mode_shadow_is_default_and_not_authority(db, cashenv):
    assert mode.cash_mode() == mode.CashMode.DUAL_WRITE_SHADOW   # default
    assert mode.dual_write_active() is True
    assert mode.ledger_is_authority() is False                   # SHADOW -> ledger o'qish avtoritet EMAS


def test_ledger_primary_env_guarded(monkeypatch):
    # env LEDGER_PRIMARY qo'shimcha ALLOW flag'siz -> fail-safe XATO (tasodifiy cutover to'siladi)
    mode.reset_mode()
    monkeypatch.setenv("SAVDOOS_CASH_MODE", "LEDGER_PRIMARY")
    monkeypatch.delenv("SAVDOOS_CASH_ALLOW_PRIMARY", raising=False)
    with pytest.raises(RuntimeError):
        mode.cash_mode()
    # ALLOW flag bilan -> ruxsat (lekin biz bu task'да YOQMAYMIZ)
    monkeypatch.setenv("SAVDOOS_CASH_ALLOW_PRIMARY", "1")
    assert mode.cash_mode() == mode.CashMode.LEDGER_PRIMARY


# ═══ T0 BOUNDARY (item 9) ════════════════════════════════════════════════════
def test_t0_business_key_prevents_double_post(db, cashenv):
    # Bir hodisa HAM backfill (RECONSTRUCTION) HAM dual-write (NORMAL) bo'lса cle_uq_business BUZILADI
    # -> ikki marta post MUMKIN EMAS (T0 overlap himoyasi DB darajасида).
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.dialects.postgresql import insert as _pg
    emp, br, till = provision(db, cashenv)
    sx = uuid.uuid4()
    common = dict(tenant_id=cashenv.company_id, cash_account_id=till.id, branch_id=br.id,
                  account_type="TILL", shift_id=None, posting_kind="OFF_SHIFT", source_type="SALE",
                  source_id=sx, leg_index=0, direction="IN", category="SALE", amount=Decimal("10000"),
                  currency="UZS", device_occurred_at=cashenv.now, server_received_at=cashenv.now,
                  recorded_at=cashenv.now)
    db.execute(_pg(CashLedgerEntry.__table__).values(
        id=uuid.uuid4(), idempotency_key="recon", provenance="RECONSTRUCTION",
        reconstruction_reason="x", reconstruction_source_ref="y", **common))
    db.commit()
    with pytest.raises(IntegrityError):   # AYNI biznes-kalit NORMAL -> unique buzildi
        db.execute(_pg(CashLedgerEntry.__table__).values(
            id=uuid.uuid4(), idempotency_key="normal", provenance="NORMAL", **common))
        db.commit()
    db.rollback()


def test_t0_provenance_and_exact_boundary(db, cashenv):
    from datetime import timedelta
    from sqlalchemy.dialects.postgresql import insert as _pg
    emp, br, till = provision(db, cashenv)
    t0 = cashenv.now
    # pre-T0 backfill leg (RECONSTRUCTION) — compare NORMAL tarafдан CHIQARIB TASHLANADI
    db.execute(_pg(CashLedgerEntry.__table__).values(
        id=uuid.uuid4(), tenant_id=cashenv.company_id, cash_account_id=till.id, branch_id=br.id,
        account_type="TILL", shift_id=None, posting_kind="OFF_SHIFT", source_type="SALE",
        source_id=uuid.uuid4(), leg_index=0, direction="IN", category="SALE", amount=Decimal("77777"),
        currency="UZS", device_occurred_at=t0 - timedelta(hours=1), server_received_at=cashenv.now,
        recorded_at=cashenv.now, idempotency_key="pre", provenance="RECONSTRUCTION",
        reconstruction_reason="x", reconstruction_source_ref="y").on_conflict_do_nothing())
    db.commit()
    # live (>= T0) dual-write sotuv
    _open_shift(db, emp, 0)
    prod, _ = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    _cash_sale(db, emp, prod, 2)   # 30000, "hozir" (>= T0)
    c = sc.compare_till(db, cashenv.company_id, till.id, t0=t0)
    # ledger NORMAL tarafi FAQAT live sotuv (77777 RECONSTRUCTION HISOBGA OLINMADI) -> legacy(>=T0) bilan 0
    assert c["status"] == "MATCH" and c["delta"] == 0.0 and c["ledger_in"] == 30000.0


# ═══ CONCURRENCY (item 14) ═══════════════════════════════════════════════════
def test_concurrent_manual_payout_parity(db, cashenv):
    from tests.cash.test_posting_service import _concurrent
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])
    cu, empid = uuid.uuid4(), emp.id

    def do(s):
        e = s.get(Employee, empid)
        return shifts_api.add_cash_movement(sid, shifts_api.CashMove(
            type="payout", amount=6000, client_uuid=cu), e, s)
    ra, rb = _concurrent(cashenv.engine, do, do)
    assert not isinstance(ra, Exception) and not isinstance(rb, Exception)
    # AYNI BITTA leg, legacy/ledger divergensiya yo'q
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.cash_account_id == till.id,
                                            CashLedgerEntry.category == "CASH_OUT").count() == 1
    assert sc.compare_shift(db, cashenv.company_id, sid)["delta"] == 0.0


# ═══ ROLLBACK on ledger error -> parity saqlanadi (hech nima yozilmadi) ══════
def test_rollback_on_ledger_error_keeps_parity(db, cashenv):
    from fastapi import HTTPException
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 5000)["id"])
    with pytest.raises(HTTPException):
        _add_move(db, emp, sid, "payout", 9000)   # 9000 > 5000 -> rad
    db.rollback()
    c = sc.compare_shift(db, cashenv.company_id, sid)
    assert c["delta"] == 0.0    # na legacy na ledger yozildi -> parity


# ═══ NO AUTO-REPAIR ══════════════════════════════════════════════════════════
def test_snapshot_no_auto_repair(db, cashenv):
    emp, br, till = provision(db, cashenv)
    sid = uuid.UUID(_open_shift(db, emp, 100000)["id"])
    mode.set_mode("LEGACY_ONLY")
    _add_move(db, emp, sid, "expense", 8000)   # ledger'siz -> delta yaratadi
    mode.reset_mode()
    s1 = sc.snapshot(db, company_id=cashenv.company_id)
    s2 = sc.snapshot(db, company_id=cashenv.company_id)
    assert s1["total_abs_delta"] == s2["total_abs_delta"] > 0.0   # takror hisob -> BIR XIL (tuzatilmadi)
    assert db.query(CashLedgerEntry).filter(
        CashLedgerEntry.cash_account_id == till.id, CashLedgerEntry.category == "EXPENSE").count() == 0


# ═══ TENANT ISOLATION ════════════════════════════════════════════════════════
def test_compare_tenant_isolation(db, cashenv):
    # boshqa tenant kerak — yangi kompaniya (cashenv bitta kompaniya beradi, shu bois till orqali izolyatsiya)
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 100000)
    prod, _ = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    _cash_sale(db, emp, prod, 2)
    c = sc.compare_till(db, cashenv.company_id, till.id)
    # bu till leg'lari FAQAT shu tenant'ники
    for e in db.query(CashLedgerEntry).filter(CashLedgerEntry.cash_account_id == till.id).all():
        assert e.tenant_id == cashenv.company_id
    assert c["delta"] == 0.0


# ═══ DIRECT-WRITE invariant — shadow_compare O'QIYDI, yozmaydi ════════════════
def test_shadow_compare_is_read_only(db, cashenv):
    import inspect
    from app.services.cash import shadow_compare
    src = inspect.getsource(shadow_compare)
    assert "CashLedgerEntry(" not in src       # ORM ctor yo'q
    assert ".add(" not in src and "insert(" not in src.replace("# ", "")   # yozuv yo'q


# ═══ §19 ADVERSARIAL-REVIEW FIX REGRESSIONLARI ═══════════════════════════════

# [1]+[4] roll-up/snapshot NET signed delta offsetting'ni YASHIRMAYDI (false MATCH tuzatildi)
def test_rollup_offsetting_not_masked():
    parts = [
        {"legacy_in": 100.0, "legacy_out": 0.0, "ledger_in": 105.0, "ledger_out": 0.0, "delta": 5.0, "status": "REVIEW"},
        {"legacy_in": 100.0, "legacy_out": 0.0, "ledger_in": 95.0, "ledger_out": 0.0, "delta": -5.0, "status": "REVIEW"},
    ]
    r = sc._rollup("tenant", {"tenant_id": "t"}, parts)
    assert r["delta"] == 0.0                 # net teng-qarama-qarshi bekor bo'ldi
    assert r["abs_delta"] == 10.0            # LEKIN absolyut YASHIRMAYDI
    assert r["divergent_part_count"] == 2
    assert r["status"] == "REVIEW"           # MATCH EMAS (ilgari yolg'on MATCH edi)
    # hammasi MATCH bo'lса -> MATCH
    ok = [{"legacy_in": 10.0, "legacy_out": 0.0, "ledger_in": 10.0, "ledger_out": 0.0, "delta": 0.0, "status": "MATCH"}]
    assert sc._rollup("tenant", {}, ok)["status"] == "MATCH"


# [4] snapshot HONEST maydonlar: divergent_till_count bor, soxta event_mismatch_count YO'Q
def test_snapshot_report_fields_honest(db, cashenv):
    snap = sc.snapshot(db, company_id=cashenv.company_id)
    assert "divergent_till_count" in snap and isinstance(snap["divergent_till_count"], int)
    assert "total_abs_delta" in snap
    assert "event_mismatch_count" not in snap    # soxta qattiq-0 maydon olib tashlandi


# [3] smenasiz naqd qarz-to'lovi -> DEBT_IN leg YO'Q (parity; ilgari ledger>legacy divergensiya)
def test_debt_payment_no_shift_no_ledger_parity(db, cashenv):
    emp, br, till = provision(db, cashenv)          # smena OCHILMAYDI
    cust = _customer(db, cashenv, 50000)
    _pay_debt(db, emp, cust, 20000)                 # cash, lekin ochiq smena yo'q
    # legacy: CustomerPayment + AR yangilandi, LEKIN soya CashMovement YO'Q (smena yo'q)
    from app.models.customers import CustomerPayment
    assert db.query(CustomerPayment).filter(CustomerPayment.customer_id == cust.id).count() == 1
    # ledger: DEBT_IN leg YO'Q (soya bilan izchil) -> divergensiya yo'q
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.cash_account_id == till.id,
                                            CashLedgerEntry.category == "DEBT_IN").count() == 0
    assert sc.compare_till(db, cashenv.company_id, till.id)["delta"] == 0.0
    db.refresh(cust)
    assert cust.credit_balance == Decimal("30000.00")   # AR baribir kamaydi (legacy avtoritet)


def test_debt_payment_with_shift_still_posts(db, cashenv):
    # regressiya: ochiq smena bo'lса DEBT_IN DAVOM etadi (fix normal yo'lni sindirmadi)
    emp, br, till = provision(db, cashenv)
    _open_shift(db, emp, 0)
    cust = _customer(db, cashenv, 50000)
    _pay_debt(db, emp, cust, 20000)
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.cash_account_id == till.id,
                                            CashLedgerEntry.category == "DEBT_IN").count() == 1


# [5] ikkinchi kassir shu filialда smena ochsa legacy SINDIRILMAYDI (cash-constraint stricter)
def test_second_cashier_same_branch_no_legacy_break(db, cashenv):
    from app.models.auth import EmployeeBranch
    from app.models.cash import CashShift
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift as LegacyShift
    empA, br, till = provision(db, cashenv)
    _open_shift(db, empA, 100000)                   # A -> cash.shift bor
    roleid = db.get(Employee, empA.id).role_id
    empB = Employee(company_id=cashenv.company_id, full_name="Kassir B", role_id=roleid)
    db.add(empB); db.flush()
    db.add(EmployeeBranch(employee_id=empB.id, branch_id=br.id)); db.commit()
    rB = _open_shift(db, empB, 50000)               # B -> legacy MUVAFFAQ (400 EMAS)
    assert rB.get("id")
    shB = db.query(LegacyShift).filter(LegacyShift.cashier_id == empB.id,
                                       LegacyShift.status == ShiftStatus.open).first()
    assert shB is not None                          # B'ning legacy smenasi OCHIQ (sindirilmadi)
    # TILL'да FAQAT BITTA ochiq cash.shift (A'ники; B skip qilindi)
    assert db.query(CashShift).filter(CashShift.cash_account_id == till.id,
                                      CashShift.status == "OPEN").count() == 1
    # MA'LUM CHEKLOV HALOL-SURFACING: B'ning opening float (50000) ledger'да YO'Q (cash.shift skip) ->
    # compare_till bu anomaliyani REVIEW bilan KO'RSATADI (YASHIRMAYDI) — cutover go/no-go operator uchun.
    ct = sc.compare_till(db, cashenv.company_id, till.id)
    assert ct["status"] == "REVIEW"                 # divergensiya SURFACED (false MATCH emas)
    assert ct["delta"] == -50000.0                  # ledger legacy'дан B'ning 50000 opening'iga kam


def test_concurrent_second_cashier_open_no_break(db, cashenv):
    from tests.cash.test_posting_service import _concurrent
    from app.models.auth import EmployeeBranch
    from app.models.cash import CashShift
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift as LegacyShift
    empA, br, till = provision(db, cashenv)
    roleid = db.get(Employee, empA.id).role_id
    empB = Employee(company_id=cashenv.company_id, full_name="KB", role_id=roleid)
    db.add(empB); db.flush()
    db.add(EmployeeBranch(employee_id=empB.id, branch_id=br.id)); db.commit()
    aid, bid = empA.id, empB.id

    def opA(s):
        return shifts_api.open_shift(shifts_api.OpenShift(opening_cash=100000), s.get(Employee, aid), s)

    def opB(s):
        return shifts_api.open_shift(shifts_api.OpenShift(opening_cash=50000), s.get(Employee, bid), s)
    ra, rb = _concurrent(cashenv.engine, opA, opB)
    assert not isinstance(ra, Exception) and not isinstance(rb, Exception)   # hech biri hard-fail emas
    # ikkala kassir legacy smenasi OCHIQ (sindirilmadi)
    assert db.query(LegacyShift).filter(LegacyShift.cashier_id.in_([aid, bid]),
                                        LegacyShift.status == ShiftStatus.open).count() == 2
    # TILL'да ko'pi bilan BITTA ochiq cash.shift (cash-constraint hurmat qilindi)
    assert db.query(CashShift).filter(CashShift.cash_account_id == till.id,
                                      CashShift.status == "OPEN").count() == 1
