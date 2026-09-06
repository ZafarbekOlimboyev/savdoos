# -*- coding: utf-8 -*-
"""Cash Migration CLI · RECONCILE ROW-LEVEL PROBE (STRICTLY READ-ONLY).

Operator (Windows/Railway — `railway run` EMAS; `ssh`):
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_reconcile_probe --json

MAQSAD: RECONCILE_DEBT_SHADOW / RECONCILE_REFUND_SHADOW / RECONCILE_SUPPLIER_SHADOW REVIEW'lari
HAQIQIY data-loss'mi yoki soya-reconciliation false-positive'mi — ROW DARAJASIDA aniqlaydi. Har naqd
manba qatori (CustomerPayment/SupplierPayment/Return) uchun: source id, occurred_at, amount, method,
company, branch, linked shift, SOYA mavjudligi, LEDGER mavjudligi, backfill reconstruct qilinishга
LAYOQATLILIK + sabab, va klassifikatsiya.

KLASSIFIKATSIYA (bitta asosiy qiymat, priority tartibида):
  DATA_INCONSISTENCY        — qattiq ziddiyat (ledger summasi manba != , yoki >1 leg, yoki amount<=0).
  SHADOW_PRESENT            — mos SOYA CashMovement bor (backfill soyaни skip qilib manbadан tiklaydi).
  EXPECTED_LEGACY_NO_SHADOW — SOYA yo'q, LEKIN backfill manbadan deterministik tiklaydi (FALSE-POSITIVE
                              sababи: off-shift/pre-shadow legacy — data-loss EMAS).
  BACKFILL_NOT_ELIGIBLE     — SOYA yo'q VA fizik TILL hal qilinmadi (dinamik TILL yo'q / ko'p-TILL noaniq)
                              -> operator TILL yaratib qayta run qilsin (KECHIKTIRILGAN, yo'qolган EMAS).
  NEEDS_REVIEW              — yuqoridagilardан birortasига toza tushmagan.
`backfill_eligible` (bool) + `backfill_reason` alohida maydonlar — BACKFILL_ELIGIBLE signaliни saqlaydi.

ORPHAN SOYA (shadow > manba): manba qatori bo'lmagan ORTIQCHA soya — summary'да `orphan_shadows` va
reconcile REVIEW sifatida ko'rsatiladi (haqiqiy nomuvofiqlik).

XAVFSIZLIK: HECH NARSA yozmaydi (faqat SELECT + resolve_account read-only); oxirida ROLLBACK+close.
Mode O'ZGARTIRMAYDI, cutover SET qilmaydi, LEDGER_PRIMARY YO'Q. SHAXSIY MAYDON YO'Q (mijoz/ta'minotchi
nomi/telefoni, customer_id/supplier_id, employee_id CHIQARILMAYDI — faqat texnik id/summa/vaqt).
Exit: 0 = REVIEW yo'q (hammasi EXPECTED/OK), 2 = REVIEW/NOT_ELIGIBLE/orphan bor, 1 = usage.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from sqlalchemy import func

from app.db.cash.migration import backfill, phase1
from app.models.cash import CashLedgerEntry as CLE
from app.models.customers import Customer, CustomerPayment
from app.models.enums import CashMovementType as CMT
from app.models.org import Branch, Company
from app.models.purchasing import Supplier, SupplierPayment
from app.models.sales import Return
from app.models.shifts import CashMovement, Shift
from app.tools import _common as C

_TOL = Decimal("0.01")
_ROW_CAP = 500                 # har manba/kompaniya uchun chiqariladigan qatorlar shifti (summary to'liq qoladi)


def _companies(db):
    return db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.code).all()


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _dt(x):
    return x.isoformat() if x is not None else None


# ── soya / ledger mavjudligi (row-level, tenant-scoped) ──────────────────────
def _shadow_count(db, tenant_id, mtype, prefix, *, amount=None, employee_id=None, reason_exact=None) -> int:
    q = (db.query(func.count(CashMovement.id)).join(Shift, Shift.id == CashMovement.shift_id)
         .join(Branch, Branch.id == Shift.branch_id)
         .filter(Branch.company_id == tenant_id, CashMovement.type == mtype,
                 CashMovement.client_uuid.is_(None)))
    if reason_exact is not None:
        q = q.filter(CashMovement.reason == reason_exact)
    else:
        q = q.filter(CashMovement.reason.like(prefix + "%"))
    if amount is not None:
        q = q.filter(CashMovement.amount == _D(amount))
    if employee_id is not None:
        q = q.filter(CashMovement.employee_id == employee_id)
    return int(q.scalar() or 0)


def _shadow_total(db, tenant_id, mtype, prefix) -> int:
    """Manbaга bog'lanmagan holда prefiks bo'yicha BARCHA soyalar (orphan aniqlash uchun)."""
    return _shadow_count(db, tenant_id, mtype, prefix)


def _ledger(db, tenant_id, source_type, source_id):
    rows = db.query(CLE.amount).filter(
        CLE.tenant_id == tenant_id, CLE.source_type == source_type, CLE.source_id == source_id).all()
    return len(rows), sum((_D(a[0]) for a in rows), Decimal("0"))


# ── layoqat (backfill.resolve_account — YAGONA haqiqat manbaи, read-only) ─────
def _eligibility(db, ctx, tenant_id, source_type, source_id, branch_id, amount):
    # amount SHART: resolve_account shift-less yo'lда _resolve_via_shadow(leg["amount"]) o'qiydi.
    leg = {"tenant_id": str(tenant_id), "branch_id": (str(branch_id) if branch_id else None),
           "terminal_id": None, "source_type": source_type, "source_id": str(source_id),
           "amount": float(_D(amount))}
    acc, info = backfill.resolve_account(db, leg, ctx)
    if acc is not None:
        return True, f"resolved TILL ({info})", None
    sev, reason = info
    return False, reason, sev


def _classify(*, shadow_n, ledger_n, ledger_amt, amount, eligible):
    a = _D(amount)
    if ledger_n > 1:
        return "DATA_INCONSISTENCY", f"{ledger_n} ledger legs for one source (expected <=1)"
    if ledger_n == 1 and abs(_D(ledger_amt) - a) > _TOL:
        return "DATA_INCONSISTENCY", f"ledger amount {ledger_amt} != source amount {amount}"
    if a <= 0:
        return "DATA_INCONSISTENCY", f"non-positive cash amount {amount}"
    if shadow_n >= 1:
        return "SHADOW_PRESENT", "matching shadow CashMovement present (backfill skips it, reconstructs source)"
    if eligible:
        return "EXPECTED_LEGACY_NO_SHADOW", "no shadow; backfill reconstructs deterministically from source"
    return "BACKFILL_NOT_ELIGIBLE", "no shadow; physical TILL unresolved -> operator provisions TILL, re-run"


def _row(source_type, category, sid, occurred, amount, branch_id, shift_id, shadow_n, ledger_n,
         ledger_amt, eligible, elig_reason, elig_sev):
    cls, why = _classify(shadow_n=shadow_n, ledger_n=ledger_n, ledger_amt=ledger_amt,
                         amount=amount, eligible=eligible)
    return {"source_type": source_type, "category": category, "source_id": str(sid),
            "occurred_at": _dt(occurred), "amount": float(_D(amount)), "method": "cash",
            "branch_id": (str(branch_id) if branch_id else None),
            "shift_id": (str(shift_id) if shift_id else None),
            "shadow_present": shadow_n > 0, "shadow_count": shadow_n,
            "ledger_present": ledger_n > 0, "ledger_legs": ledger_n,
            "backfill_eligible": eligible, "backfill_reason": elig_reason,
            "backfill_review_severity": elig_sev, "classification": cls, "classification_reason": why}


# ── manba auditlari (per company) ────────────────────────────────────────────
def _audit_customer(db, ctx, c):
    rows = []
    q = (db.query(CustomerPayment.id, CustomerPayment.branch_id, CustomerPayment.created_at,
                  CustomerPayment.amount, CustomerPayment.employee_id)
         .join(Customer, Customer.id == CustomerPayment.customer_id)
         .filter(Customer.company_id == c.id, CustomerPayment.method == "cash"))
    for sid, bid, created, amt, eid in q.all():
        sh = _shadow_count(db, c.id, CMT.payin, "Qarz to'lovi · ", amount=amt, employee_id=eid)
        ln, lamt = _ledger(db, c.id, "CUSTOMER_PAYMENT", sid)
        el, why, sev = _eligibility(db, ctx, c.id, "CUSTOMER_PAYMENT", sid, bid, amt)
        rows.append(_row("CUSTOMER_PAYMENT", "DEBT_IN", sid, created, amt, bid, None, sh, ln, lamt, el, why, sev))
    return rows


def _audit_supplier(db, ctx, c):
    rows = []
    q = (db.query(SupplierPayment.id, SupplierPayment.created_at, SupplierPayment.amount,
                  SupplierPayment.employee_id)
         .join(Supplier, Supplier.id == SupplierPayment.supplier_id)
         .filter(Supplier.company_id == c.id, SupplierPayment.method == "cash"))
    for sid, created, amt, eid in q.all():
        sh = _shadow_count(db, c.id, CMT.payout, "Ta'minotchi · ", amount=amt, employee_id=eid)
        ln, lamt = _ledger(db, c.id, "SUPPLIER_PAYMENT", sid)
        el, why, sev = _eligibility(db, ctx, c.id, "SUPPLIER_PAYMENT", sid, None, amt)  # shift-less
        rows.append(_row("SUPPLIER_PAYMENT", "SUPPLIER_OUT", sid, created, amt, None, None, sh, ln, lamt, el, why, sev))
    return rows


def _audit_return(db, ctx, c):
    rows = []
    q = db.query(Return.id, Return.return_no, Return.branch_id, Return.shift_id, Return.created_at,
                 Return.total).filter(Return.company_id == c.id, Return.refund_method == "cash")
    for sid, rno, bid, shid, created, total in q.all():
        # refund soya reason = f"Qaytarish {return_no}" (return_no company ичида UNIKAL) -> aniq moslik
        sh = _shadow_count(db, c.id, CMT.payout, "Qaytarish", reason_exact=f"Qaytarish {rno}")
        ln, lamt = _ledger(db, c.id, "RETURN", sid)
        el, why, sev = _eligibility(db, ctx, c.id, "RETURN", sid, bid, total)
        rows.append(_row("RETURN", "REFUND", sid, created, total, bid, shid, sh, ln, lamt, el, why, sev))
    return rows


def _summ(rows, shadow_total):
    by_cls: dict = {}
    for r in rows:
        by_cls[r["classification"]] = by_cls.get(r["classification"], 0) + 1
    matched_shadow = sum(r["shadow_count"] for r in rows)
    # ORPHAN = reconcile_shadows semantikasi (shadow_total vs manba SONI): har manba qatori qonuniy ravishда
    # BITTA soyaга mos keladi; manba sonidан ORTIQ soyalar (dublikat/orphan) ORTIQCHA -> REVIEW. Per-row
    # `matched_shadow` (bir qator bir necha dublikatga mos kelishi mumkin) diagnostik, orphan'ni belgilamaydi.
    orphan = max(0, shadow_total - len(rows))
    review = by_cls.get("BACKFILL_NOT_ELIGIBLE", 0) + by_cls.get("DATA_INCONSISTENCY", 0) + orphan
    return {"source_rows": len(rows), "shadow_total": shadow_total, "shadow_matched": matched_shadow,
            "orphan_shadows": orphan, "by_classification": by_cls,
            "eligible": sum(1 for r in rows if r["backfill_eligible"]),
            "not_eligible": sum(1 for r in rows if not r["backfill_eligible"]),
            "review_or_orphan": review}


def _company_block(db, ctx, c) -> dict:
    cust = _audit_customer(db, ctx, c)
    sup = _audit_supplier(db, ctx, c)
    ret = _audit_return(db, ctx, c)
    st_cust = _shadow_total(db, c.id, CMT.payin, "Qarz to'lovi · ")
    st_sup = _shadow_total(db, c.id, CMT.payout, "Ta'minotchi · ")
    st_ret = _shadow_total(db, c.id, CMT.payout, "Qaytarish")
    recon = [f.as_dict() for f in phase1.reconcile_shadows(db, c.id)]
    return {
        "company": c.code, "company_id": str(c.id),
        "customer_payment": {"summary": _summ(cust, st_cust), "rows": cust[:_ROW_CAP],
                             "rows_truncated": max(0, len(cust) - _ROW_CAP)},
        "supplier_payment": {"summary": _summ(sup, st_sup), "rows": sup[:_ROW_CAP],
                             "rows_truncated": max(0, len(sup) - _ROW_CAP)},
        "return": {"summary": _summ(ret, st_ret), "rows": ret[:_ROW_CAP],
                   "rows_truncated": max(0, len(ret) - _ROW_CAP)},
        "reconcile_findings": [{"code": f["code"], "severity": f["severity"], "detail": f["detail"][:240]}
                               for f in recon],
    }


def probe(db) -> dict:
    comps = _companies(db)
    out = []
    for c in comps:
        ctx = backfill._build_context(db, c.id)
        out.append(_company_block(db, ctx, c))
    # verdict: har qanday orphan/DATA_INCONSISTENCY -> REVIEW; NOT_ELIGIBLE -> DEFERRED (operator TILL)
    orphan = sum(b[k]["summary"]["orphan_shadows"] for b in out
                 for k in ("customer_payment", "supplier_payment", "return"))
    inconsistent = sum(b[k]["summary"]["by_classification"].get("DATA_INCONSISTENCY", 0) for b in out
                       for k in ("customer_payment", "supplier_payment", "return"))
    not_elig = sum(b[k]["summary"]["not_eligible"] for b in out
                   for k in ("customer_payment", "supplier_payment", "return"))
    expected = sum(b[k]["summary"]["by_classification"].get("EXPECTED_LEGACY_NO_SHADOW", 0) for b in out
                   for k in ("customer_payment", "supplier_payment", "return"))
    if orphan or inconsistent:
        verdict = "REVIEW_REQUIRED"
    elif not_elig:
        verdict = "DEFERRED_TILL_PROVISION"
    else:
        verdict = "EXPECTED_LEGACY_CLEAN"
    return {"kind": "CASH_RECONCILE_PROBE", "companies": out,
            "totals": {"orphan_shadows": orphan, "data_inconsistency": inconsistent,
                       "backfill_not_eligible": not_elig, "expected_legacy_no_shadow": expected},
            "verdict": verdict}


def _print_human(rep: dict) -> None:
    C.out("")
    for b in rep["companies"]:
        C.out(f"COMPANY {b['company']}:")
        for key, label in (("customer_payment", "CustomerPayment->DEBT_IN"),
                           ("supplier_payment", "SupplierPayment->SUPPLIER_OUT"),
                           ("return", "Return->REFUND")):
            s = b[key]["summary"]
            C.out(f"   {label:<32} rows={s['source_rows']}  shadow_total={s['shadow_total']}  "
                  f"orphan={s['orphan_shadows']}  eligible={s['eligible']}  not_elig={s['not_eligible']}")
            C.out(f"      by_class={s['by_classification']}")
            if b[key]["rows_truncated"]:
                C.out(f"      (+{b[key]['rows_truncated']} rows not printed; summary is complete)")
        for f in b["reconcile_findings"]:
            C.out(f"      reconcile [{f['severity']}] {f['code']}: {f['detail']}")
        C.out("")
    t = rep["totals"]
    C.out(f"TOTALS: expected_legacy_no_shadow={t['expected_legacy_no_shadow']}  "
          f"backfill_not_eligible={t['backfill_not_eligible']}  orphan_shadows={t['orphan_shadows']}  "
          f"data_inconsistency={t['data_inconsistency']}")
    C.out(f"VERDICT: {rep['verdict']}")


def run(db, *, as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    C.print_header("RECONCILE ROW-LEVEL PROBE (read-only)", mode_label="READ-ONLY", company_id=None, db=db)
    rep = probe(db)
    if as_json:
        C.emit_json(rep)
    else:
        _print_human(rep)
    v = rep["verdict"]
    C.out("")
    if v == "EXPECTED_LEGACY_CLEAN":
        C.out("VERDICT: EXPECTED_LEGACY_CLEAN — reconcile REVIEW'lari FALSE-POSITIVE (soyasiz legacy). "
              "Backfill manbadан deterministik tiklaydi; data-loss YO'Q.")
        return C.EXIT_OK
    if v == "DEFERRED_TILL_PROVISION":
        C.out("VERDICT: DEFERRED_TILL_PROVISION — soyasiz legacy (data-loss YO'Q), lekin ba'zi qatorlar "
              "uchun fizik TILL hal qilinmadi -> operator TILL yaratib backfill qayta run qilsin.")
        return C.EXIT_REVIEW
    C.out("VERDICT: REVIEW_REQUIRED — orphan soya yoki ledger nomuvofiqligi -> operator ROW-DARAJADA ko'rsin "
          "(haqiqiy anomaliya, jimgina backfill QILINMAYDI).")
    return C.EXIT_REVIEW


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_reconcile_probe",
                                description="STRICTLY READ-ONLY reconcile row-level probe.")
    p.add_argument("--json", action="store_true", help="To'liq hisobotni JSON sifatida chiqarish.")
    args = p.parse_args(argv)
    _eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, as_json=args.json)
    finally:
        db.rollback()   # STRICTLY READ-ONLY
        db.close()


if __name__ == "__main__":
    sys.exit(main())
