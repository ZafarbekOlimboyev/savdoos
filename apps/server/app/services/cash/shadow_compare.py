# -*- coding: utf-8 -*-
"""Cash Ledger — Phase 2 SHADOW COMPARISON servisi (FAQAT O'QISH, auto-repair YO'Q).

Legacy AVTORITET; ledger SOYA. Bu servis ikki TARAFNI MUSTAQIL hisoblaydi va solishtiradi:

  A. LEGACY expected physical cash — FAQAT legacy source jadvallaridan
     (Shift.opening_cash, cash SalePayment, CashMovement payin/payout/expense/collection,
      Purchase/SupplierLedger). Ledger'ni HECH QACHON o'qimaydi (tautologiya emas).
  B. LEDGER expected physical cash — FAQAT cash_ledger_entries dual-write (provenance=NORMAL) leg'lardan.

Legacy'ning MA'LUM ko'r nuqtasi (naqd xarid) fizik summaga qo'shiladi: legacy naqd matematikasi
CashMovement'ga tayanadi, xarid esa CashMovement yozmaydi — shu bois "physical" legacy = naqd-mat
MINUS net naqd xaridlar (Purchase.total, not_charged). Ledger buni PURCHASE_OUT/PURCHASE_RETURN bilan
tutadi. Algebraik ayniyat: ledger_expected == legacy_physical_expected (delta=0) — dual-write to'g'ri bo'lsa.

provenance=NORMAL + ixtiyoriy t0: Phase-1 backfill (RECONSTRUCTION, < T0) Phase-2 dual-write'дан
AJRATILADI. Snapshot/trace READ-ONLY — hech nima yozmaydi, deltalar YASHIRILMAYDI/normallashtirilmaydi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.cash import CashAccount, CashLedgerEntry
from app.models.enums import CashMovementType, CreditTxnType
from app.models.org import Branch
from app.models.purchasing import Purchase, PurchaseReturn, SupplierLedger
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift

_Z = Decimal("0")
_TOL = Decimal("0.005")   # butun-som quantize'дан keyin AYNIY kutiladi; float shovqin uchun kichik chek


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _status(delta: Decimal, blocked: bool = False) -> str:
    if blocked:
        return "BLOCK"
    return "MATCH" if abs(delta) <= _TOL else "REVIEW"


# ═══ CASH PURCHASE predikati (not_charged) — legacy manba, ledger'siz ══════════
def _charged_purchase_ids(db: Session, company_id) -> set:
    """SupplierLedger'ga CHARGE yozgan (debt/nasiya) xaridlar id'lari — bular naqd EMAS (kassa
    tegmagan). Runtime `_charged` + backfill filtri bilan izchil. TENANT'ga scope (§19 topilma:
    company_id endi HAQIQATAN ishlatiladi — Supplier orqali)."""
    from app.models.purchasing import Supplier
    rows = db.execute(select(SupplierLedger.ref_id).join(
        Supplier, Supplier.id == SupplierLedger.supplier_id).where(
        Supplier.company_id == company_id,
        SupplierLedger.ref_type.in_(("purchase", "receiving")),
        SupplierLedger.type == CreditTxnType.charge)).all()
    return {r[0] for r in rows if r[0] is not None}


def _cash_purchase_net(db: Session, company_id, branch_id, t0, opened=None, closed=None) -> Decimal:
    """Branch bo'yicha NAQD (not_charged) xaridlarning NET fizik chiqishi = Σ Purchase.total.
    Net = joriy total (increase qo'shadi, return ayiradi -> joriy total = net; cancelled -> total 0).
    t0/oyna berilса created_at bo'yicha filtr (smena-daraja atribusiyasi)."""
    charged = _charged_purchase_ids(db, company_id)
    q = select(Purchase.id, Purchase.total, Purchase.created_at).where(
        Purchase.company_id == company_id, Purchase.branch_id == branch_id)
    total = _Z
    for pid, ptotal, created in db.execute(q).all():
        if pid in charged:
            continue                      # debt xarid — kassa tegmagan
        if t0 is not None and created is not None and created < t0:
            continue
        if opened is not None and created is not None and not (opened <= created <= (closed or created)):
            continue
        total += _D(ptotal)
    return total


# ═══ LEGACY tarafi (source jadvallardan; ledger O'QILMAYDI) ═══════════════════
def _legacy_movement_sums(db: Session, shift_ids, t0):
    sums = {"payin": _Z, "payout": _Z, "expense": _Z, "collection": _Z}
    if not shift_ids:
        return sums
    q = select(CashMovement.type, CashMovement.amount, CashMovement.created_at).where(
        CashMovement.shift_id.in_(list(shift_ids)))
    for mtype, amt, created in db.execute(q).all():
        if t0 is not None and created is not None and created < t0:
            continue
        mt = mtype.value if hasattr(mtype, "value") else str(mtype)
        if mt in sums:
            sums[mt] += _D(amt)
    return sums


def _legacy_cash_sales(db: Session, sale_filter, t0) -> Decimal:
    q = select(func.coalesce(func.sum(SalePayment.amount), 0)).select_from(SalePayment).join(
        Sale, Sale.id == SalePayment.sale_id).where(SalePayment.method_code == "cash", sale_filter)
    if t0 is not None:
        q = q.where(Sale.sold_at >= t0)
    return _D(db.execute(q).scalar())


def _branch_of(db: Session, company_id, cash_account_id):
    acc = db.get(CashAccount, cash_account_id)
    if acc is None or acc.tenant_id != company_id:
        return None
    return acc.branch_id


# ═══ LEDGER tarafi (FAQAT NORMAL dual-write leg'lar) ══════════════════════════
def _ledger_flows(db: Session, company_id, *, cash_account_id=None, shift_id=None, on_shift_only=False):
    """(in, out) — provenance=NORMAL leg'lar. cash_account_id -> hisob bo'yicha; shift_id -> smena
    bo'yicha (on_shift_only=True -> ON_SHIFT filtri)."""
    signed_in = func.coalesce(func.sum(CashLedgerEntry.amount).filter(
        CashLedgerEntry.direction == "IN"), 0)
    signed_out = func.coalesce(func.sum(CashLedgerEntry.amount).filter(
        CashLedgerEntry.direction == "OUT"), 0)
    q = select(signed_in, signed_out).where(
        CashLedgerEntry.tenant_id == company_id,
        CashLedgerEntry.provenance == "NORMAL")
    if cash_account_id is not None:
        q = q.where(CashLedgerEntry.cash_account_id == cash_account_id)
    if shift_id is not None:
        q = q.where(CashLedgerEntry.shift_id == shift_id)
    if on_shift_only:
        q = q.where(CashLedgerEntry.posting_kind == "ON_SHIFT")
    row = db.execute(q).first()
    return _D(row[0]), _D(row[1])


# ═══ PUBLIC: solishtirish darajalari ═════════════════════════════════════════
def compare_shift(db: Session, company_id, legacy_shift_id, *, t0=None) -> dict:
    """Bitta legacy smena: legacy physical expected vs ledger ON_SHIFT expected.
    cash.shift.id == legacy shift id (runtime alignment) -> ledger shift_id = legacy_shift_id.

    DIQQAT (§19 minor topilma): naqd XARID smena-atribusiyasi create-vaqti oynasiga tayanadi
    (Purchase.created_at). Agar xarid BOSHQA smenada oshirilса/qaytarilса, ledger o'sha edit-vaqti
    smenasiga leg yozadi -> bu SMENA-daraja delta noaniq bo'ladi (ikki smenaда REVIEW). compare_till
    (hisob-daraja, smena-agnostik) DOIM to'g'ri (deltalar bekor bo'ladi) — cutover go/no-go uchun
    compare_till/compare_tenant ishlating. Bir-smena hayot-tsikli (odatiy) -> aniq."""
    sh = db.get(Shift, legacy_shift_id)
    if sh is None:
        return {"level": "shift", "shift_id": str(legacy_shift_id), "status": "BLOCK",
                "reason": "legacy smena topilmadi"}
    br = db.get(Branch, sh.branch_id)
    if br is None or br.company_id != company_id:      # §19 topilma: tenant guard (branch->company)
        return {"level": "shift", "shift_id": str(legacy_shift_id), "status": "BLOCK",
                "reason": "smena boshqa tenant'ники / branch topilmadi"}
    opened, closed = sh.opened_at, sh.closed_at
    opening = _D(sh.opening_cash) if (t0 is None or (opened is not None and opened >= t0)) else _Z
    cash_sales = _legacy_cash_sales(db, Sale.shift_id == sh.id, t0)
    mv = _legacy_movement_sums(db, [sh.id], t0)
    net_purch = _cash_purchase_net(db, company_id, sh.branch_id, t0, opened=opened, closed=closed)
    legacy_in = opening + cash_sales + mv["payin"]
    legacy_out = mv["payout"] + mv["expense"] + mv["collection"] + net_purch
    legacy_expected = legacy_in - legacy_out
    ledger_in, ledger_out = _ledger_flows(db, company_id, shift_id=legacy_shift_id, on_shift_only=True)
    ledger_expected = ledger_in - ledger_out
    delta = ledger_expected - legacy_expected
    return {
        "level": "shift", "tenant_id": str(company_id), "branch_id": str(sh.branch_id),
        "shift_id": str(legacy_shift_id),
        "legacy_in": float(legacy_in), "legacy_out": float(legacy_out),
        "legacy_expected": float(legacy_expected),
        "ledger_in": float(ledger_in), "ledger_out": float(ledger_out),
        "ledger_expected": float(ledger_expected),
        "delta": float(delta), "status": _status(delta),
        "legacy_breakdown": {"opening": float(opening), "cash_sales": float(cash_sales),
                             "payin": float(mv["payin"]), "payout": float(mv["payout"]),
                             "expense": float(mv["expense"]), "collection": float(mv["collection"]),
                             "net_cash_purchases": float(net_purch)},
    }


def compare_till(db: Session, company_id, cash_account_id, *, t0=None) -> dict:
    """Bitta TILL (branch) — barcha faoliyat (smena + off-shift) yig'indisi. ENG ROBUST daraja:
    xarid/off-shift smena-atribusiyasidan mustaqil. Fizik legacy vs ledger NORMAL."""
    branch_id = _branch_of(db, company_id, cash_account_id)
    if branch_id is None:
        return {"level": "till", "cash_account_id": str(cash_account_id), "status": "BLOCK",
                "reason": "TILL topilmadi / boshqa tenant"}
    # legacy: branch bo'yicha BARCHA smenalar (opening + payin/payout/... ) + BARCHA naqd sotuvlar + net xarid
    sh_q = select(Shift.id, Shift.opening_cash, Shift.opened_at).where(Shift.branch_id == branch_id)
    opening = _Z
    shift_ids = []
    for sid, ocash, opened in db.execute(sh_q).all():
        shift_ids.append(sid)
        if t0 is None or (opened is not None and opened >= t0):
            opening += _D(ocash)
    cash_sales = _legacy_cash_sales(db, Sale.branch_id == branch_id, t0)
    mv = _legacy_movement_sums(db, shift_ids, t0)
    net_purch = _cash_purchase_net(db, company_id, branch_id, t0)
    legacy_in = opening + cash_sales + mv["payin"]
    legacy_out = mv["payout"] + mv["expense"] + mv["collection"] + net_purch
    legacy_expected = legacy_in - legacy_out
    ledger_in, ledger_out = _ledger_flows(db, company_id, cash_account_id=cash_account_id)
    ledger_expected = ledger_in - ledger_out
    delta = ledger_expected - legacy_expected
    return {
        "level": "till", "tenant_id": str(company_id), "branch_id": str(branch_id),
        "cash_account_id": str(cash_account_id),
        "legacy_in": float(legacy_in), "legacy_out": float(legacy_out),
        "legacy_expected": float(legacy_expected),
        "ledger_in": float(ledger_in), "ledger_out": float(ledger_out),
        "ledger_expected": float(ledger_expected),
        "delta": float(delta), "status": _status(delta),
        "legacy_breakdown": {"opening": float(opening), "cash_sales": float(cash_sales),
                             "payin": float(mv["payin"]), "payout": float(mv["payout"]),
                             "expense": float(mv["expense"]), "collection": float(mv["collection"]),
                             "net_cash_purchases": float(net_purch)},
    }


def compare_branch(db: Session, company_id, branch_id, *, t0=None) -> dict:
    """Branch = uning ACTIVE TILL(lar)i yig'indisi."""
    tills = db.execute(select(CashAccount.id).where(
        CashAccount.tenant_id == company_id, CashAccount.branch_id == branch_id,
        CashAccount.type == "TILL")).all()
    parts = [compare_till(db, company_id, t[0], t0=t0) for t in tills]
    return _rollup("branch", {"tenant_id": str(company_id), "branch_id": str(branch_id)}, parts)


def compare_tenant(db: Session, company_id, *, t0=None) -> dict:
    """Tenant = uning barcha TILL'lari yig'indisi."""
    tills = db.execute(select(CashAccount.id).where(
        CashAccount.tenant_id == company_id, CashAccount.type == "TILL")).all()
    parts = [compare_till(db, company_id, t[0], t0=t0) for t in tills]
    return _rollup("tenant", {"tenant_id": str(company_id)}, parts)


def _rollup(level, base, parts) -> dict:
    li = sum((_D(p.get("legacy_in", 0)) for p in parts), _Z)
    lo = sum((_D(p.get("legacy_out", 0)) for p in parts), _Z)
    di = sum((_D(p.get("ledger_in", 0)) for p in parts), _Z)
    do = sum((_D(p.get("ledger_out", 0)) for p in parts), _Z)
    net_delta = (di - do) - (li - lo)
    # §19 topilma (MAJOR false-negative): status NET signed delta'дан HISOBLANMASIN — teng-va-qarama-qarshi
    # bola deltalari 0'ga bekor bo'lиб yolg'on MATCH berardi. Status = ANY bola REVIEW/BLOCK bo'lса
    # eskaladsin; miqdor uchun ABSOLYUT delta ishlatiladi (offsetting'ni yashirmaydi).
    abs_delta = sum((abs(_D(p.get("delta", 0))) for p in parts), _Z)
    divergent = [p for p in parts if p.get("status") != "MATCH"]
    blocked = any(p.get("status") == "BLOCK" for p in parts)
    status = "BLOCK" if blocked else ("REVIEW" if (divergent or abs_delta > _TOL) else "MATCH")
    return {**base, "level": level,
            "legacy_in": float(li), "legacy_out": float(lo), "legacy_expected": float(li - lo),
            "ledger_in": float(di), "ledger_out": float(do), "ledger_expected": float(di - do),
            "delta": float(net_delta), "abs_delta": float(abs_delta),
            "divergent_part_count": len(divergent), "status": status,
            "parts": parts}


# ═══ EVENT-LEVEL parity (item 5) ═════════════════════════════════════════════
def event_trace(db: Session, company_id, source_type, source_id) -> dict:
    """Bitta biznes hodisa: kutilган ledger biznes-kaliti(lari) vs HAQIQIY ledger qatori(lari).
    Aniqlaydi: missing leg / extra leg / wrong direction / wrong amount / duplicate business key."""
    rows = db.execute(select(CashLedgerEntry).where(
        CashLedgerEntry.tenant_id == company_id,
        CashLedgerEntry.source_type == source_type,
        CashLedgerEntry.source_id == source_id).order_by(CashLedgerEntry.leg_index)).scalars().all()
    legs = [{"leg_index": r.leg_index, "direction": r.direction, "category": r.category,
             "amount": float(r.amount), "cash_account_id": str(r.cash_account_id),
             "shift_id": str(r.shift_id) if r.shift_id else None, "posting_kind": r.posting_kind,
             "provenance": r.provenance} for r in rows]
    keys = [(r.leg_index) for r in rows]
    dup = len(keys) != len(set(keys))
    return {"source_type": source_type, "source_id": str(source_id),
            "ledger_leg_count": len(rows), "legs": legs,
            "duplicate_business_key": dup,
            "missing": len(rows) == 0}


# ═══ SNAPSHOT / observability (items 6, 15) — READ-ONLY ═══════════════════════
def snapshot(db: Session, *, company_id=None, t0=None, comparison_timestamp=None) -> dict:
    """READ-ONLY Phase-2 solishtirish snapshot: har tenant/till delta, event-mismatch soni,
    hal qilinmagan OFF_SHIFT/exception soni. HECH NIMA YOZMAYDI, deltalar YASHIRILMAYDI."""
    if company_id is not None:
        tenants = [company_id]
    else:
        tenants = [t[0] for t in db.execute(select(CashAccount.tenant_id).distinct()).all()]
    tenant_reports = []
    total_delta = _Z
    total_abs_delta = _Z
    divergent_tills = 0
    total_unresolved = 0
    any_review = any_block = False
    for tid in tenants:
        trep = compare_tenant(db, tid, t0=t0)
        total_delta += _D(trep["delta"])
        total_abs_delta += _D(trep.get("abs_delta", 0))
        divergent_tills += int(trep.get("divergent_part_count", 0))
        if trep["status"] == "BLOCK":
            any_block = True
        elif trep["status"] == "REVIEW":
            any_review = True
        # off-shift (unresolved) NORMAL leg soni
        off = db.execute(select(func.count(CashLedgerEntry.id)).where(
            CashLedgerEntry.tenant_id == tid, CashLedgerEntry.provenance == "NORMAL",
            CashLedgerEntry.posting_kind == "OFF_SHIFT")).scalar() or 0
        total_unresolved += int(off)
        trep["unresolved_off_shift"] = int(off)
        tenant_reports.append(trep)
    # §19 topilma: status ANY divergent tenant'дан eskaladsin (NET delta EMAS). event_mismatch_count
    # (avval qattiq 0 edi -> yolg'on toza) o'rniga HAQIQIY divergent_till_count.
    status = "BLOCK" if any_block else ("REVIEW" if (any_review or total_abs_delta > _TOL) else "MATCH")
    return {
        "kind": "PHASE2_SHADOW_COMPARISON_SNAPSHOT",
        "comparison_timestamp": comparison_timestamp,
        "t0": (t0.isoformat() if hasattr(t0, "isoformat") else t0),
        "tenant_count": len(tenant_reports),
        "total_delta": float(total_delta),
        "total_abs_delta": float(total_abs_delta),
        "divergent_till_count": divergent_tills,
        "unresolved_off_shift_count": total_unresolved,
        "status": status,
        "tenants": tenant_reports,
        "note": "READ-ONLY. delta=ledger(NORMAL)-legacy(physical); status ANY divergent till'дан "
                "(net EMAS, abs). Auto-repair YO'Q.",
    }
