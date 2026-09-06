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
  EXPECTED_LEGACY_NO_SHADOW — SOYA yo'q, LEKIN TARIXIY TILL DALILI bor -> backfill deterministik tiklaydi
                              (FALSE-POSITIVE sababi: off-shift/pre-shadow legacy — data-loss EMAS).
  HISTORICAL_TILL_UNKNOWN   — SOYA yo'q VA deterministik TARIXIY TILL dalili YO'Q.
                              MUHIM: bu "TILL yaratib qayta run qil" DEGANI EMAS —
                              CURRENT TILL PROVISIONING != HISTORICAL TILL EVIDENCE.
                              Qator dalil/attestatsiya bo'lguncha ledger'dan TASHQARIDA (skip+REVIEW).
                              BLOKER EMAS: T0-oldinga migratsiya davom etadi.
  BACKFILL_NOT_ELIGIBLE     — boshqa sabab (masalan cross-tenant) — operator ROW-DARAJADA ko'rsin.
`backfill_eligible` + `historical_evidence_rule` (qaysi DALIL hal qildi) + `evidence_class` maydonlari.
`current_till_provisioned` — ALOHIDA RUNTIME signali (branch'da bugun ACTIVE TILL bormi); u tarixiy
identity bilan ARALASHTIRILMAYDI. Batafsil: HISTORICAL_TILL_RESOLUTION.md.

ORPHAN SOYA (shadow > manba): manba qatori bo'lmagan ORTIQCHA soya — summary'да `orphan_shadows` va
reconcile REVIEW sifatida ko'rsatiladi (haqiqiy nomuvofiqlik).

XAVFSIZLIK: HECH NARSA yozmaydi (faqat SELECT + resolve_account read-only); oxirida ROLLBACK+close.
Mode O'ZGARTIRMAYDI, cutover SET qilmaydi, LEDGER_PRIMARY YO'Q. SHAXSIY MAYDON YO'Q (mijoz/ta'minotchi
nomi/telefoni, customer_id/supplier_id, employee_id CHIQARILMAYDI — faqat texnik id/summa/vaqt).
Exit: 0 = EXPECTED_LEGACY_CLEAN, 2 = REVIEW (orphan / inconsistency / DEFERRED_HISTORICAL_IDENTITY).
DEFERRED_HISTORICAL_IDENTITY ATAYLAB 3 (BLOCK) EMAS — u migratsiyani to'xtatmaydi.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from sqlalchemy import func

from app.db.cash.migration import backfill, historical_till as _hist, phase1
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


def _cur_ready(ctx, branch_id):
    """RUNTIME signali: branch'da BUGUN ACTIVE TILL bormi. Bu TARIXIY dalil EMAS — faqat T0-keyingi
    yangi naqd faoliyat uchun tayyorlik. Eski qatorning drawer'ini aniqlashда ISHLATILMAYDI."""
    if not branch_id:
        return None
    return bool(ctx["tills_by_branch"].get(str(branch_id)))


# ── TARIXIY dalil (backfill.resolve_account — YAGONA haqiqat manbaи, read-only) ─
def _eligibility(db, ctx, tenant_id, source_type, source_id, branch_id, amount, *,
                 till_id=None, shift_id=None, terminal_id=None, occurred=None):
    """(eligible, reason, severity, evidence_class_or_rule).

    Manba qatorining TARIXIY dalillari (till_id/shift_id/terminal_id) UZATILADI — phase1 legalari
    bilan AYNAN bir xil (aks holda probe backfill'dan farq qilib yolg'on hisobot berardi)."""
    leg = {"tenant_id": str(tenant_id), "branch_id": (str(branch_id) if branch_id else None),
           "terminal_id": (str(terminal_id) if terminal_id else None),
           "till_id": (str(till_id) if till_id else None),
           "shift_id": (str(shift_id) if shift_id else None),
           "source_type": source_type, "source_id": str(source_id), "amount": float(_D(amount)),
           # device_occurred_at SHART: usiz vaqt-oynali attestatsiya probe'da ishlamay, backfill'dan
           # FARQ qilardi (probe production haqida yolg'on hisobot berardi).
           "device_occurred_at": _dt(occurred)}
    acc, info = backfill.resolve_account(db, leg, ctx)
    if acc is not None:
        return True, f"historical evidence: {info}", None, info      # info = dalil QOIDASI
    sev, reason, ev_class = info
    return False, reason, sev, ev_class


def _classify(*, shadow_n, ledger_n, ledger_amt, amount, eligible, evidence_class):
    """Bitta asosiy klassifikatsiya. MUHIM AJRATISH: dalilsiz LEGACY qator HISTORICAL_TILL_UNKNOWN —
    u "TILL yaratib qayta run qil" DEGANI EMAS (bugungi TILL o'tmish uchun dalil emas)."""
    a = _D(amount)
    if ledger_n > 1:
        return "DATA_INCONSISTENCY", f"{ledger_n} ledger legs for one source (expected <=1)"
    if ledger_n == 1 and abs(_D(ledger_amt) - a) > _TOL:
        return "DATA_INCONSISTENCY", f"ledger amount {ledger_amt} != source amount {amount}"
    if a <= 0:
        return "DATA_INCONSISTENCY", f"non-positive cash amount {amount}"
    # DIQQAT (§HIST-REVIEW): DISPOZITSIYA birinchi. Agar tarixiy TILL hal qilinmagan bo'lsa, backfill
    # qatorni SKIP qiladi — soya bor-yo'qligidan QAT'I NAZAR. Ilgari SHADOW_PRESENT ustun edi va probe
    # "backfill manbadan tiklaydi" deb YOLG'ON hisobot berardi.
    if not eligible and evidence_class == _hist.HISTORICAL_TILL_UNKNOWN:
        return "HISTORICAL_TILL_UNKNOWN", (
            "deterministic historical TILL evidence absent; current TILL provisioning is not historical "
            "evidence. Row is SKIPPED and stays outside the authoritative ledger until historical "
            "evidence or an explicit operator attestation exists. NOT a migration blocker."
            + (" (a shadow CashMovement exists, but its shift carries no till_id)" if shadow_n else ""))
    if shadow_n >= 1:
        return "SHADOW_PRESENT", "matching shadow CashMovement present (backfill skips it, reconstructs source)"
    if eligible:
        return "EXPECTED_LEGACY_NO_SHADOW", "no shadow; historical TILL evidence found -> deterministic reconstruct"
    if evidence_class == _hist.HISTORICAL_TILL_UNKNOWN:
        return "HISTORICAL_TILL_UNKNOWN", (
            "no shadow AND no deterministic historical TILL evidence (no source till_id / shift till_id / "
            "terminal binding / contemporaneous shadow). Provisioning a TILL today does NOT prove which "
            "drawer this past row used -> row stays outside the authoritative ledger until explicit "
            "historical evidence or an operator historical attestation exists. NOT a migration blocker.")
    return "BACKFILL_NOT_ELIGIBLE", f"unresolved ({evidence_class})"


def _row(source_type, category, sid, occurred, amount, branch_id, shift_id, shadow_n, ledger_n,
         ledger_amt, eligible, elig_reason, elig_sev, evidence_class, current_till_ready):
    cls, why = _classify(shadow_n=shadow_n, ledger_n=ledger_n, ledger_amt=ledger_amt,
                         amount=amount, eligible=eligible, evidence_class=evidence_class)
    return {"source_type": source_type, "category": category, "source_id": str(sid),
            "occurred_at": _dt(occurred), "amount": float(_D(amount)), "method": "cash",
            "branch_id": (str(branch_id) if branch_id else None),
            "shift_id": (str(shift_id) if shift_id else None),
            "shadow_present": shadow_n > 0, "shadow_count": shadow_n,
            "ledger_present": ledger_n > 0, "ledger_legs": ledger_n,
            "backfill_eligible": eligible, "backfill_reason": elig_reason,
            "backfill_review_severity": elig_sev,
            "historical_evidence_rule": (evidence_class if eligible else None),
            "evidence_class": (None if eligible else evidence_class),
            # RUNTIME tayyorligi — TARIXIY identity'dan MUSTAQIL signal (aralashtirilmaydi)
            "current_till_provisioned": current_till_ready,
            "classification": cls, "classification_reason": why}


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
        el, why, sev, ev = _eligibility(db, ctx, c.id, "CUSTOMER_PAYMENT", sid, bid, amt, occurred=created)
        rows.append(_row("CUSTOMER_PAYMENT", "DEBT_IN", sid, created, amt, bid, None, sh, ln, lamt,
                         el, why, sev, ev, _cur_ready(ctx, bid)))
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
        el, why, sev, ev = _eligibility(db, ctx, c.id, "SUPPLIER_PAYMENT", sid, None, amt, occurred=created)  # shift-less
        rows.append(_row("SUPPLIER_PAYMENT", "SUPPLIER_OUT", sid, created, amt, None, None, sh, ln, lamt,
                         el, why, sev, ev, None))
    return rows


def _audit_return(db, ctx, c):
    rows = []
    q = db.query(Return.id, Return.return_no, Return.branch_id, Return.shift_id, Return.created_at,
                 Return.total, Return.till_id, Return.terminal_id).filter(
                     Return.company_id == c.id, Return.refund_method == "cash")
    for sid, rno, bid, shid, created, total, till, term in q.all():
        # refund soya reason = f"Qaytarish {return_no}" (return_no company ичида UNIKAL) -> aniq moslik
        sh = _shadow_count(db, c.id, CMT.payout, "Qaytarish", reason_exact=f"Qaytarish {rno}")
        ln, lamt = _ledger(db, c.id, "RETURN", sid)
        el, why, sev, ev = _eligibility(db, ctx, c.id, "RETURN", sid, bid, total,
                                        till_id=till, shift_id=shid, terminal_id=term, occurred=created)
        rows.append(_row("RETURN", "REFUND", sid, created, total, bid, shid, sh, ln, lamt,
                         el, why, sev, ev, _cur_ready(ctx, bid)))
    return rows


def _summ(rows, shadow_total):
    by_cls: dict = {}
    for r in rows:
        by_cls[r["classification"]] = by_cls.get(r["classification"], 0) + 1
    matched_shadow = sum(r["shadow_count"] for r in rows)
    # ORPHAN = manbaga BOG'LAB BO'LMAYDIGAN soyalar. §HIST-REVIEW: ilgari `shadow_total - len(rows)`
    # (NET) edi — 1 ta haqiqiy orphan soya + 1 ta soyasiz legacy qator BIR-BIRINI YO'Q QILIB, haqiqiy
    # nomuvofiqlikni YASHIRARDI. Endi maxraj = soyaga MOS KELGAN qatorlar soni.
    rows_with_shadow = sum(1 for r in rows if r["shadow_count"] > 0)
    orphan = max(0, shadow_total - rows_with_shadow)
    # DIQQAT: klassifikatsiya kalitini QATTIQ yozmaymiz — nom o'zgarsa jimgina 0 bo'lib ketardi.
    review = sum(n for k, n in by_cls.items() if k not in ("EXPECTED_LEGACY_NO_SHADOW", "SHADOW_PRESENT")) + orphan
    return {"source_rows": len(rows), "shadow_total": shadow_total, "shadow_matched": matched_shadow,
            "rows_with_shadow": rows_with_shadow,
            "orphan_shadows": orphan, "by_classification": by_cls,
            "historical_till_unknown": by_cls.get("HISTORICAL_TILL_UNKNOWN", 0),
            "current_till_missing": sum(1 for r in rows if r["current_till_provisioned"] is False),
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
    # verdict: orphan/DATA_INCONSISTENCY -> REVIEW; dalilsiz legacy -> HISTORICAL_TILL_UNKNOWN
    # (TILL provisioning bu qatorlarni HAL QILMAYDI); faqat runtime TILL yetishmasa -> DEFERRED_CURRENT.
    orphan = sum(b[k]["summary"]["orphan_shadows"] for b in out
                 for k in ("customer_payment", "supplier_payment", "return"))
    inconsistent = sum(b[k]["summary"]["by_classification"].get("DATA_INCONSISTENCY", 0) for b in out
                       for k in ("customer_payment", "supplier_payment", "return"))
    not_elig = sum(b[k]["summary"]["not_eligible"] for b in out
                   for k in ("customer_payment", "supplier_payment", "return"))
    expected = sum(b[k]["summary"]["by_classification"].get("EXPECTED_LEGACY_NO_SHADOW", 0) for b in out
                   for k in ("customer_payment", "supplier_payment", "return"))
    hist_unknown = sum(b[k]["summary"]["historical_till_unknown"] for b in out
                       for k in ("customer_payment", "supplier_payment", "return"))
    cur_missing = sum(b[k]["summary"]["current_till_missing"] for b in out
                      for k in ("customer_payment", "supplier_payment", "return"))
    if orphan or inconsistent:
        verdict = "REVIEW_REQUIRED"
    elif hist_unknown:
        verdict = "DEFERRED_HISTORICAL_IDENTITY"
    elif not_elig:
        verdict = "BACKFILL_NOT_ELIGIBLE"
    else:
        verdict = "EXPECTED_LEGACY_CLEAN"
    return {"kind": "CASH_RECONCILE_PROBE", "companies": out,
            "totals": {"orphan_shadows": orphan, "data_inconsistency": inconsistent,
                       "backfill_not_eligible": not_elig, "expected_legacy_no_shadow": expected,
                       "historical_till_unknown": hist_unknown,
                       "current_till_not_provisioned_rows": cur_missing},
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
          f"historical_till_unknown={t['historical_till_unknown']}  "
          f"orphan_shadows={t['orphan_shadows']}  data_inconsistency={t['data_inconsistency']}")
    C.out(f"        (runtime-only signal) rows in a branch with no ACTIVE TILL today: "
          f"{t['current_till_not_provisioned_rows']}  — separate concern, NOT historical evidence")
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
    if v == "DEFERRED_HISTORICAL_IDENTITY":
        C.out("VERDICT: DEFERRED_HISTORICAL_IDENTITY — soyasiz legacy (data-loss YO'Q), LEKIN bu qatorlar uchun")
        C.out("  DETERMINISTIK TARIXIY TILL DALILI YO'Q (manba till_id / smena till_id / terminal / soya yo'q).")
        C.out("  DIQQAT: BUGUN TILL YARATISH BU QATORLARNI HAL QILMAYDI — bugungi provisioning o'tmish uchun")
        C.out("  dalil EMAS. Qatorlar dalil/attestatsiya paydo bo'lguncha avtoritet ledger'dan TASHQARIDA")
        C.out("  qoladi (skip + REVIEW). Bu T0-oldinga migratsiyani BLOKLAMAYDI.")
        C.out("  Hal qilish: explicit historical mapping (kind=HISTORICAL_TILL_EVIDENCE; aniq source_id")
        C.out("  yoki branch+vaqt-oynasi, `evidence` attestatsiyasi bilan).")
        return C.EXIT_REVIEW      # ATAYLAB EXIT_BLOCK(3) EMAS — bu bloker emas, kechiktirilgan identity
    if v == "BACKFILL_NOT_ELIGIBLE":
        C.out("VERDICT: BACKFILL_NOT_ELIGIBLE — qatorlar boshqa sababdan hal qilinmadi (masalan cross-tenant) "
              "-> operator ROW-DARAJADA ko'rsin.")
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
