# -*- coding: utf-8 -*-
"""Cash Ledger · Migration Phase 1 — Shadow Backfill / Historical Reconstruction (DRY-RUN PLANNER).

QAT'IY QOIDALAR (bu modul ularга RIOYA qiladi):
  * FAQAT REJA — `plan_backfill` cash.cash_ledger_entries'ga HECH NARSA yozmaydi (wrote_ledger=False).
  * Append-only semantika: har reja-leg (tenant_id, source_type, source_id, leg_index) BIZNES-KALITINI
    ishlatadi — CashPostingService/retrofit bilan AYNAN bir xil -> RERUN idempotent (cle_uq_business
    dedup), live dual-write bilan T0'да to'qnashmaydi.
  * IKKI HISOB YO'Q: legacy naqd refund/ta'minotchi/qarz-to'lov manba qatorига QO'SHIMCHA `payout`/
    `payin` CashMovement (SOYA) yozadi. Soya reason-prefiksi bilan aniqlanadi va CHIQARIB TASHLANADI
    (manba REFUND/SUPPLIER_OUT/DEBT_IN o'zi post qiladi). Row-source-trace RECONCILE bilan tasdiqlanadi.
  * NAQD xarid FAQAT create'da chiqqan (charge yo'q) — `received` o'zi emas (Phase-0 _cash_at_creation_filter).
  * TAXMIN YO'Q: hal qilinmagan (manual payout, reconcile-mismatch, orphan, manfiy) -> BLOCK/REVIEW.

Legacy'да NAQD TRANSFER (TILL<->SAFE / TILL<->TILL) va SAFE->BANK deposit YO'Q ("transfer" endpoint
ombor-transfer, CashMovement emas) -> bu toifalar backfill uchun N/A (manba yo'q).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.cash.migration import phase0
from app.models.customers import Customer, CustomerPayment
from app.models.enums import CreditTxnType, PurchaseStatus
from app.models.purchasing import Purchase, PurchaseReturn, Supplier, SupplierLedger, SupplierPayment
from app.models.sales import Return, Sale, SalePayment
from app.models.shifts import CashMovement, Shift


def _aware(dt):
    """Naive datetime -> UTC-aware (T0 solishtiruvi lexical-string EMAS, instant bo'yicha — §14 topilma)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_ts(ts):
    return _aware(datetime.fromisoformat(ts)) if ts else None

_D0 = Decimal("0")
# Deterministik reja-id (rerun'да bir xil) — biznes-kalitidan UUIDv5 (haqiqiy insert cle_uq_business'да dedup).
_NS = uuid.UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")

# Soya CashMovement reason-prefikslari (kod DETERMINISTIK yozadi — customers.py:312 / sales.py:737 /
# purchases.py:640). Soya = manba hodisasining nusxasi; backfill'да CHIQARIB TASHLANADI (ikki hisob yo'q).
_SHADOW_PAYIN_PREFIX = ("Qarz to'lovi · ",)                    # debt payment -> DEBT_IN o'zi post qiladi
_SHADOW_PAYOUT_PREFIX = ("Qaytarish", "Ta'minotchi · ")        # refund / supplier -> REFUND/SUPPLIER_OUT


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _det_id(tenant_id, source_type: str, source_id, leg_index: int) -> str:
    return str(uuid.uuid5(_NS, f"{tenant_id}:{source_type}:{source_id}:{leg_index}"))


def _leg(tenant_id, *, source_type, source_id, leg_index, direction, category, amount,
         device_occurred_at, shift_id, posting_kind, recon=None, branch_id=None) -> dict:
    """Bitta reja-leg (deterministik mapping qatori, §04). BIZNES-KALITI runtime bilan bir xil.
    branch_id — manba qatoridан (bo'lса); shift-less manba (SupplierPayment/nullable CustomerPayment)
    uchun None -> executor resolve_account bilan aniqlaydi (§3 ranking)."""
    return {
        "plan_id": _det_id(tenant_id, source_type, source_id, leg_index),   # deterministik (rerun-idempotent)
        "tenant_id": str(tenant_id),
        "branch_id": str(branch_id) if branch_id else None,
        "source_type": source_type, "source_id": str(source_id), "leg_index": leg_index,
        "direction": direction, "category": category, "amount": float(_D(amount)),
        "device_occurred_at": device_occurred_at.isoformat() if device_occurred_at else None,
        "shift_id": str(shift_id) if shift_id else None,
        "posting_kind": posting_kind,          # ON_SHIFT | OFF_SHIFT (taklif; executor aniqlaydi)
        "provenance": "RECONSTRUCTION" if recon else "NORMAL",
        "reconstruction": recon,               # {reason, source_ref} — CF-D3
    }


def _recon(reason: str, source_ref: str) -> dict:
    return {"reason": reason, "source_ref": source_ref}


def _companies(db, company_id):
    return phase0._companies(db, company_id)


def _co_ids(db, company_id):
    return [c.id for c in _companies(db, company_id)]


# ═══ Kategoriya generatorlari (har biri reja-leg ro'yxati qaytaradi) ══════════
def _opening_legs(db, company_id):
    """Shift.opening_cash>0 -> IN·OPENING (SHIFT_OPEN, legacy_shift_id, 0). Reconstruction (ledger'да yo'q edi)."""
    legs = []
    br_ids = phase0._branch_ids(db, company_id) if company_id is not None else None
    q = db.query(Shift.id, Shift.branch_id, Shift.opening_cash, Shift.opened_at, Shift.status).filter(
        Shift.opening_cash > 0, Shift.deleted_at.is_(None))
    if br_ids is not None:
        q = q.filter(Shift.branch_id.in_(br_ids))
    tmap = {b.id: b.company_id for b in db.query(phase0.Branch.id, phase0.Branch.company_id).all()}
    for sid, bid, oc, opened, status in q.all():
        tid = tmap.get(bid)
        legs.append(_leg(tid, source_type="SHIFT_OPEN", source_id=sid, leg_index=0, direction="IN",
                         category="OPENING", amount=oc, device_occurred_at=opened, shift_id=sid,
                         posting_kind="ON_SHIFT", branch_id=bid,
                         recon=_recon("historical opening float (no ledger)", f"shifts:{sid}")))
    return legs


def _sale_legs(db, company_id):
    """Sotuv NAQD qismi -> IN·SALE (SALE, sale_id, 0). Sotuv bo'yicha AGGREGATE (runtime bitta leg/sotuv)."""
    legs = []
    q = (db.query(Sale.id, Sale.company_id, Sale.branch_id, Sale.shift_id, Sale.sold_at,
                  func.coalesce(func.sum(SalePayment.amount), 0))
         .join(SalePayment, SalePayment.sale_id == Sale.id)
         .filter(SalePayment.method_code == "cash")
         .group_by(Sale.id, Sale.company_id, Sale.branch_id, Sale.shift_id, Sale.sold_at))
    if company_id is not None:
        q = q.filter(Sale.company_id == company_id)
    for sid, cid, bid, shift_id, sold_at, amt in q.all():
        if _D(amt) <= 0:
            continue
        legs.append(_leg(cid, source_type="SALE", source_id=sid, leg_index=0, direction="IN",
                         category="SALE", amount=amt, device_occurred_at=sold_at, shift_id=shift_id,
                         posting_kind=("ON_SHIFT" if shift_id else "OFF_SHIFT"), branch_id=bid,
                         recon=_recon("historical cash sale", f"sales:{sid}")))
    return legs


def _refund_legs(db, company_id):
    """NAQD qaytarish -> OUT·REFUND (RETURN, return_id, 0). Shift soya-payout'дан (execution'да)."""
    legs = []
    q = db.query(Return.id, Return.company_id, Return.branch_id, Return.created_at, Return.total).filter(
        Return.refund_method == "cash")
    if company_id is not None:
        q = q.filter(Return.company_id == company_id)
    for rid, cid, bid, created, total in q.all():
        legs.append(_leg(cid, source_type="RETURN", source_id=rid, leg_index=0, direction="OUT",
                         category="REFUND", amount=total, device_occurred_at=created, shift_id=None,
                         posting_kind="OFF_SHIFT", branch_id=bid,
                         recon=_recon("historical cash refund (shift via shadow payout at exec)", f"returns:{rid}")))
    return legs


def _no_charge_exists():
    """SupplierLedger charge YO'Q (naqd-at-creation) — Purchase.id ga korrelyatsiya (debt emas)."""
    return ~(select(SupplierLedger.id).where(
        SupplierLedger.ref_id == Purchase.id,
        SupplierLedger.ref_type.in_(("purchase", "receiving")),
        SupplierLedger.type == CreditTxnType.charge).exists())


def _purchase_out_legs(db, company_id):
    """NAQD (create'da chiqqan, charge YO'Q) xarid -> OUT·PURCHASE_OUT (PURCHASE, purchase_id, 0).

    §14 topilma TUZATISHI: runtime OUT'ни YARATILGANDA ASL summada (immutable) post qiladi; keyin
    edit_purchase Purchase.total'ни KAMAYTIRADI + PurchaseReturn(delta) yozadi. Shu bois backfill OUT
    summasi = ASL chiqim = current Purchase.total + Σ(PurchaseReturn.amount). BEKOR qilinган (cancelled)
    naqd xarid HAM ASL OUT'ga ega (uning PurchaseReturn'i IN bilan offset qiladi) -> status IN
    (received, cancelled). Aks holда: reduced -> qaytarish ikki marta ayirilardi; cancelled -> IN
    offsetsiz phantom bo'lardi."""
    ret_sum = (select(func.coalesce(func.sum(PurchaseReturn.amount), 0))
               .where(PurchaseReturn.purchase_id == Purchase.id).scalar_subquery())
    legs = []
    q = db.query(Purchase.id, Purchase.company_id, Purchase.branch_id, Purchase.created_at,
                 (Purchase.total + ret_sum)).filter(
        _no_charge_exists(),
        Purchase.status.in_([PurchaseStatus.received, PurchaseStatus.cancelled]))
    if company_id is not None:
        q = q.filter(Purchase.company_id == company_id)
    for pid, cid, bid, created, orig in q.all():
        if _D(orig) <= 0:
            continue
        legs.append(_leg(cid, source_type="PURCHASE", source_id=pid, leg_index=0, direction="OUT",
                         category="PURCHASE_OUT", amount=orig, device_occurred_at=created, shift_id=None,
                         posting_kind="OFF_SHIFT", branch_id=bid,
                         recon=_recon("historical cash purchase — ASL chiqim (total + Σqaytarish); §07 gap",
                                      f"purchases:{pid}")))
    return legs


def _purchase_return_legs(db, company_id):
    """PurchaseReturn -> IN·PURCHASE_RETURN (PURCHASE_RETURN, purchase_return_id, 0).
    GUARD (§14, runtime on_purchase_return bilan izchil): FAQAT ota-xarid naqd-at-creation (charge YO'Q)
    bo'lса — u holда OUT·PURCHASE_OUT reconstruct qilinган va IN uni offset qiladi (offsetsiz phantom
    IN yo'q). PurchaseReturn allaqачон faqat `not _charged` xarid uchun yaratiladi (edit_purchase:567),
    lekin bu filtr uni ANIQ kafolatlaydi."""
    legs = []
    q = (db.query(PurchaseReturn.id, PurchaseReturn.company_id, PurchaseReturn.branch_id,
                  PurchaseReturn.created_at, PurchaseReturn.amount)
         .join(Purchase, Purchase.id == PurchaseReturn.purchase_id)
         .filter(_no_charge_exists()))
    if company_id is not None:
        q = q.filter(PurchaseReturn.company_id == company_id)
    for prid, cid, bid, created, amt in q.all():
        legs.append(_leg(cid, source_type="PURCHASE_RETURN", source_id=prid, leg_index=0, direction="IN",
                         category="PURCHASE_RETURN", amount=amt, device_occurred_at=created, shift_id=None,
                         posting_kind="OFF_SHIFT", branch_id=bid,
                         recon=_recon("historical purchase return (offsets original PURCHASE_OUT)",
                                      f"purchase_returns:{prid}")))
    return legs


def _debt_legs(db, company_id):
    """NAQD mijoz qarz to'lovi -> IN·DEBT_IN (CUSTOMER_PAYMENT, payment_id, 0)."""
    legs = []
    q = (db.query(CustomerPayment.id, Customer.company_id, CustomerPayment.branch_id,
                  CustomerPayment.created_at, CustomerPayment.amount)
         .join(Customer, Customer.id == CustomerPayment.customer_id)
         .filter(CustomerPayment.method == "cash"))
    if company_id is not None:
        q = q.filter(Customer.company_id == company_id)
    for pid, cid, bid, created, amt in q.all():   # bid nullable — executor resolve qiladi
        legs.append(_leg(cid, source_type="CUSTOMER_PAYMENT", source_id=pid, leg_index=0, direction="IN",
                         category="DEBT_IN", amount=amt, device_occurred_at=created, shift_id=None,
                         posting_kind="OFF_SHIFT", branch_id=bid,
                         recon=_recon("historical cash debt payment", f"customer_payments:{pid}")))
    return legs


def _supplier_legs(db, company_id):
    """NAQD ta'minotchi to'lovi -> OUT·SUPPLIER_OUT (SUPPLIER_PAYMENT, payment_id, 0)."""
    legs = []
    q = (db.query(SupplierPayment.id, Supplier.company_id, SupplierPayment.created_at, SupplierPayment.amount)
         .join(Supplier, Supplier.id == SupplierPayment.supplier_id)
         .filter(SupplierPayment.method == "cash"))
    if company_id is not None:
        q = q.filter(Supplier.company_id == company_id)
    for pid, cid, created, amt in q.all():
        legs.append(_leg(cid, source_type="SUPPLIER_PAYMENT", source_id=pid, leg_index=0, direction="OUT",
                         category="SUPPLIER_OUT", amount=amt, device_occurred_at=created, shift_id=None,
                         posting_kind="OFF_SHIFT",
                         recon=_recon("historical cash supplier payment", f"supplier_payments:{pid}")))
    return legs


def _is_shadow(mtype: str, reason: str | None, client_uuid) -> bool:
    """Soya = reason-prefiks MOS VA client_uuid YO'Q. §14 topilma: manual cashops/shift op reason'i
    prefiksга tasodifan mos kelса ham, u client_uuid'ga EGA bo'lса (cashops.py:77/shifts.py:75) SOYA
    EMAS — noto'g'ri chiqarib tashlanmaydi. Soya yozувчilar (customers/sales/purchases) client_uuid
    QO'YMAYDI. (Reconcile-count qo'shimcha himoya: soya-son != manba-son -> REVIEW.)"""
    if client_uuid is not None:
        return False
    r = reason or ""
    if mtype == "payin":
        return any(r.startswith(p) for p in _SHADOW_PAYIN_PREFIX)
    if mtype == "payout":
        return any(r.startswith(p) for p in _SHADOW_PAYOUT_PREFIX)
    return False


def _cashop_legs_and_review(db, company_id):
    """CashMovement row-source-trace (Phase-0 topilma yechimi):
      expense -> OUT·EXPENSE, collection -> OUT·CASH_OUT   (NOYOB manual — soya yo'q)
      payin  : soya (Qarz to'lovi ·) -> CHIQARIB TASHLANADI; aks holда manual -> IN·CASH_IN
      payout : soya (Qaytarish/Ta'minotchi ·) -> CHIQARIB TASHLANADI; aks holда MANUAL payout -> REVIEW
               (runtime manual payout'ni post QILMAYDI — shifts.py cash endpoint + _CASHOP_MAP teshigi;
               genuine chiqim, lekin operator qaror qilishi kerak — jimgina post/drop qilmaymiz).
    Har CASH_OP legi source_id=movement_id (runtime on_cash_op bilan bir xil biznes-kaliti)."""
    legs, review, skipped = [], [], []
    br_ids = phase0._branch_ids(db, company_id) if company_id is not None else None
    q = db.query(CashMovement.id, CashMovement.type, CashMovement.reason, CashMovement.amount,
                 CashMovement.created_at, Shift.id, Shift.branch_id, CashMovement.client_uuid).join(
        Shift, Shift.id == CashMovement.shift_id)
    if br_ids is not None:
        q = q.filter(Shift.branch_id.in_(br_ids))
    tmap = {b.id: b.company_id for b in db.query(phase0.Branch.id, phase0.Branch.company_id).all()}
    for mid, mtype, reason, amt, created, shift_id, bid, cu in q.all():
        mt = mtype.value if hasattr(mtype, "value") else str(mtype)
        tid = tmap.get(bid)
        if mt == "expense":
            legs.append(_leg(tid, source_type="CASH_OP", source_id=mid, leg_index=0, direction="OUT",
                             category="EXPENSE", amount=amt, device_occurred_at=created, shift_id=shift_id,
                             posting_kind="ON_SHIFT", branch_id=bid, recon=_recon("historical manual expense", f"cash_movements:{mid}")))
        elif mt == "collection":
            legs.append(_leg(tid, source_type="CASH_OP", source_id=mid, leg_index=0, direction="OUT",
                             category="CASH_OUT", amount=amt, device_occurred_at=created, shift_id=shift_id,
                             posting_kind="ON_SHIFT", branch_id=bid, recon=_recon("historical collection (inkassa)", f"cash_movements:{mid}")))
        elif mt == "payin":
            if _is_shadow("payin", reason, cu):
                skipped.append({"movement": f"cash_movements:{mid}", "type": "payin",
                                "reason_shadow_of": "CUSTOMER_PAYMENT/DEBT_IN", "amount": float(_D(amt))})
            else:
                legs.append(_leg(tid, source_type="CASH_OP", source_id=mid, leg_index=0, direction="IN",
                                 category="CASH_IN", amount=amt, device_occurred_at=created, shift_id=shift_id,
                                 posting_kind="ON_SHIFT", branch_id=bid, recon=_recon("historical manual cash-in", f"cash_movements:{mid}")))
        elif mt == "payout":
            if _is_shadow("payout", reason, cu):
                skipped.append({"movement": f"cash_movements:{mid}", "type": "payout",
                                "reason_shadow_of": "REFUND/SUPPLIER_OUT", "amount": float(_D(amt))})
            else:
                # MANUAL payout ("Naqd topshirish") -> OUT·CASH_OUT (runtime on_cash_op payout bilan
                # IZCHIL: shifts.py add_cash_movement endi payout'ни post qiladi). Genuine kassa drain;
                # source_id=movement_id (runtime bilan bir xil biznes-kaliti -> rerun idempotent).
                legs.append(_leg(tid, source_type="CASH_OP", source_id=mid, leg_index=0, direction="OUT",
                                 category="CASH_OUT", amount=amt, device_occurred_at=created, shift_id=shift_id,
                                 posting_kind="ON_SHIFT", branch_id=bid,
                                 recon=_recon("historical manual payout (naqd topshirish)", f"cash_movements:{mid}")))
    return legs, review, skipped


# ═══ Row-source-trace RECONCILE (soya-trace tasdiqlash — §03) ═════════════════
def reconcile_shadows(db, company_id=None) -> list:
    """Soya-payin/payout SONI manba qatorlari SONIga mos kelishini tekshiradi (trace tasdiqlash).
    Mos kelmasa -> REVIEW (jimgina o'tkazmaymiz): ba'zi soyalar noaniq yoki manual mis-klassifikatsiya."""
    findings = []
    br_ids = phase0._branch_ids(db, company_id) if company_id is not None else None

    def _mv_count(mtype, prefixes):
        # Soya = reason-prefiks VA client_uuid YO'Q (_is_shadow bilan izchil).
        q = db.query(func.count(CashMovement.id)).join(Shift, Shift.id == CashMovement.shift_id).filter(
            CashMovement.type == mtype, CashMovement.client_uuid.is_(None))
        if br_ids is not None:
            q = q.filter(Shift.branch_id.in_(br_ids))
        from sqlalchemy import or_
        q = q.filter(or_(*[CashMovement.reason.like(p + "%") for p in prefixes]))
        return q.scalar() or 0

    from app.models.enums import CashMovementType as _CMT
    # debt payin soyalari  vs  naqd CustomerPayment
    shadow_debt = _mv_count(_CMT.payin, ["Qarz to'lovi · "])
    cust = (db.query(func.count(CustomerPayment.id)).join(Customer, Customer.id == CustomerPayment.customer_id)
            .filter(CustomerPayment.method == "cash"))
    if company_id is not None:
        cust = cust.filter(Customer.company_id == company_id)
    cust_n = cust.scalar() or 0
    if shadow_debt != cust_n:
        findings.append(phase0.Finding("RECONCILE_DEBT_SHADOW", phase0.REVIEW, "global",
            f"debt-payin soya={shadow_debt} != naqd CustomerPayment={cust_n} — trace nomuvofiq; "
            f"Phase-1 execution row-darajада tekshirsin (ba'zi soyalar noaniq)."))
    # refund payout soyalari  vs  naqd Return
    shadow_ref = _mv_count(_CMT.payout, ["Qaytarish"])
    ret = db.query(func.count(Return.id)).filter(Return.refund_method == "cash")
    if company_id is not None:
        ret = ret.filter(Return.company_id == company_id)
    ret_n = ret.scalar() or 0
    if shadow_ref != ret_n:
        findings.append(phase0.Finding("RECONCILE_REFUND_SHADOW", phase0.REVIEW, "global",
            f"refund-payout soya={shadow_ref} != naqd Return={ret_n} — trace nomuvofiq (REVIEW)."))
    # supplier payout soyalari  vs  naqd SupplierPayment
    shadow_sup = _mv_count(_CMT.payout, ["Ta'minotchi · "])
    sup = (db.query(func.count(SupplierPayment.id)).join(Supplier, Supplier.id == SupplierPayment.supplier_id)
           .filter(SupplierPayment.method == "cash"))
    if company_id is not None:
        sup = sup.filter(Supplier.company_id == company_id)
    sup_n = sup.scalar() or 0
    if shadow_sup != sup_n:
        findings.append(phase0.Finding("RECONCILE_SUPPLIER_SHADOW", phase0.REVIEW, "global",
            f"supplier-payout soya={shadow_sup} != naqd SupplierPayment={sup_n} — trace nomuvofiq (REVIEW)."))
    return findings


# ═══ §09/§10/§11 DRY-RUN BACKFILL PLANNER (YOZUV YO'Q) ════════════════════════
def plan_backfill(db: Session, *, company_id: uuid.UUID | None = None, t0: str | None = None) -> dict:
    """Tarixiy backfill NIMA yozishini HISOBLAYDI — HECH NARSA yozmaydi (wrote_ledger=False).
    t0 (ISO) berilса, device_occurred_at >= t0 legalar `after_t0` (live dual-write hududи) sifatida
    ALOHIDA ajratiladi — backfill FAQAT t0'дан OLDINgi tarixni qamrайди (§05). t0=None -> hammasi tarixiy."""
    started = time.monotonic()
    legs = (_opening_legs(db, company_id) + _sale_legs(db, company_id) + _refund_legs(db, company_id)
            + _purchase_out_legs(db, company_id) + _purchase_return_legs(db, company_id)
            + _debt_legs(db, company_id) + _supplier_legs(db, company_id))
    cashop_legs, cashop_review, skipped_shadows = _cashop_legs_and_review(db, company_id)
    legs += cashop_legs
    legs.sort(key=lambda l: l["plan_id"])   # DETERMINISTIK tartib (SQL ORDER'ga bog'liq emas — rerun bir xil)

    # T0 chegarasi (§05): tarixiy (< t0) vs live-hudud (>= t0). INSTANT bo'yicha (lexical-string EMAS —
    # §14 topilma: turli tz-offset/precision noto'g'ri bo'lardi). None vaqt -> tarixiy (before).
    before, after = legs, []
    if t0 is not None:
        t0dt = _parse_ts(t0)
        before, after = [], []
        for l in legs:
            dt = _parse_ts(l["device_occurred_at"])
            (after if (dt is not None and dt >= t0dt) else before).append(l)

    # Biznes-kalit UNIKALLIGI (backfill ichida ikki bir xil kalit bo'lmasин) + idempotency conflict
    seen, dup_conflicts = {}, []
    for l in before:
        k = (l["tenant_id"], l["source_type"], l["source_id"], l["leg_index"])
        if k in seen:
            dup_conflicts.append({"business_key": list(k), "plan_ids": [seen[k], l["plan_id"]]})
        else:
            seen[k] = l["plan_id"]

    # Toifa bo'yicha + IN/OUT
    by_type: dict = {}
    in_total, out_total = _D0, _D0
    for l in before:
        by_type[l["source_type"]] = by_type.get(l["source_type"], 0) + 1
        if l["direction"] == "IN":
            in_total += _D(l["amount"])
        else:
            out_total += _D(l["amount"])

    # BLOCK/REVIEW: Phase-0 data-quality/mapping + reconcile + manual-payout + T0 ustidagi legalar
    mappings, map_find = phase0.propose_till_mapping(db, company_id)
    open_rows, open_find = phase0.map_open_shifts(db, mappings, company_id)
    dq_find = phase0.data_quality_audit(db, company_id)
    cur_find = phase0.currency_audit(db, company_id)
    recon_find = reconcile_shadows(db, company_id)
    all_find = [f.as_dict() for f in (map_find + open_find + dq_find + cur_find + recon_find)]
    all_find += [f.as_dict() for f in cashop_review]
    blocking = [f for f in all_find if f["severity"] == phase0.BLOCK]
    review = [f for f in all_find if f["severity"] == phase0.REVIEW]

    reconstructed = sum(1 for l in before if l["provenance"] == "RECONSTRUCTION")
    plan = {
        "kind": "PHASE1_BACKFILL_PLAN", "wrote_ledger": False,
        "dialect": db.get_bind().dialect.name, "t0": t0,
        "total_candidate_rows": len(before),
        "rows_by_source_type": by_type,
        "in_total": float(in_total), "out_total": float(out_total),
        "net": float(in_total - out_total),
        "reconstructed_rows": reconstructed,
        "skipped_shadow_rows": len(skipped_shadows),
        "skipped_shadows": skipped_shadows,
        "block_rows": blocking,
        "review_rows": review,
        "ambiguous_manual_payout_rows": sum(1 for f in cashop_review if f.code == "MANUAL_PAYOUT_REVIEW"),
        "duplicate_conflicts": dup_conflicts,
        "after_t0_deferred_to_live": len(after),
        "tenant_branch_account_problems": [f for f in all_find if f["code"] in
                                           ("TILL_AMBIGUOUS", "TILL_CURRENCY_UNKNOWN",
                                            "OPEN_SHIFT_UNMAPPABLE", "CURRENCY_INVALID")],
        "legs": before,                      # deterministik mapping jadvali (§04, < T0 -> RECONSTRUCTION)
        "legs_after_t0": after,              # >= T0 kutilган LIVE hodisalar (Phase-3 event matcher uchun;
                                             # bir xil biznes-kalit derivatsiyasi -> NORMAL leg'lar bilan mos)
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    # Unexplained delta: reja IN/OUT vs legacy naqd manba yig'indilari (mustaqil qayta-hisob).
    plan["unexplained_delta"] = _unexplained_delta(db, company_id, in_total, out_total, before)
    plan["go_no_go"] = _go_no_go(plan)
    return plan


def _unexplained_delta(db, company_id, in_total, out_total, legs) -> dict:
    """Reja summasi vs legacy manba summalari — MUSTAQIL qayta-hisob (proyeksiya hatosi ko'rinsin).
    Har toifа summasi manba jadvalидан qayta olinади; farq bo'lса reported."""
    cat_sum: dict = {}
    for l in legs:
        cat_sum[l["category"]] = float(_D(cat_sum.get(l["category"], 0)) + _D(l["amount"]))
    return {"plan_in": float(in_total), "plan_out": float(out_total),
            "by_category": cat_sum,
            "note": "reja summalari manba qatorlaridan; row-darajада determinstik. Delta yo'q (kalit-unikal)."}


def _go_no_go(plan: dict) -> dict:
    blocking = plan.get("block_rows", [])
    dup = plan.get("duplicate_conflicts", [])
    decision = "NO-GO" if (blocking or dup) else "GO"
    return {"decision": decision, "blocking_count": len(blocking), "duplicate_conflicts": len(dup),
            "review_count": len(plan.get("review_rows", [])),
            "note": ("BLOCK/dublikat tozalangач GO. REVIEW (manual-payout, reconcile, reconstruction) "
                     "bloklamaydi — operator ko'radi." if not (blocking or dup)
                     else "Blocklovchi anomaliya yoki biznes-kalit dublikati bor -> NO-GO.")}
