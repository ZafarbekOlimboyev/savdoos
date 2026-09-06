# -*- coding: utf-8 -*-
"""Cash Migration CLI · T0 BOUNDARY PROBE (STRICTLY READ-ONLY).

Operator (Windows/Railway — `railway run` EMAS, chunki Windows Railway internal hostname'ini resolve
qilolmaydi; `ssh` ishlatiladi):
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_t0_probe --json

Phase-1 backfill DRY-RUN'ga o'tishдан OLDIN mavjud ledger holati + T0 chegarasini READ-ONLY aniqlaydi.
HECH NARSA yozmaydi: faqat SELECT + phase1.reconcile_shadows (read-only); oxirида session ROLLBACK+close.
Mode O'ZGARTIRMAYDI, cutover_at O'RNATMAYDI, LEDGER_PRIMARY YO'Q, DDL/DELETE/INSERT/UPDATE YO'Q.

Bo'limlar: cutover state · ledger inventory · cash-account inventory · dual-write boundary · prior-backfill
detection · open legacy shifts · reconciliation reviews · T0 candidate evaluation.
Exit: 0 = T0 candidate PROVABLE, 2 = NOT_PROVABLE / T0_NOT_DETERMINED, 1 = usage.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import func

from app.db.cash.migration import phase1
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift
from app.services.cash import cutover as _cut

from app.tools import _common as C


def _companies(db):
    return db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.code).all()


def _dt(x):
    return x.isoformat() if x is not None else None


# ── §2 cutover state ─────────────────────────────────────────────────────────
def _cutover_state(db, comps) -> list[dict]:
    out = []
    for c in comps:
        t0 = _cut.cutover_at(db, c.id)
        out.append({"company_id": str(c.id), "code": c.code, "name": c.name,
                    "cutover_at": _dt(t0),
                    "enforcement": ("ACTIVE" if _cut.cutover_reached(db, c.id) else "inactive")})
    return out


# ── §3 ledger inventory + §5 dual-write boundary + §6 prior backfill ─────────
def _ledger_inventory(db, comps) -> list[dict]:
    rows = []
    for c in comps:
        base = db.query(CLE).filter(CLE.tenant_id == c.id)
        total = base.count()
        r = {"company_id": str(c.id), "code": c.code, "total_rows": total}
        if total == 0:
            r.update(device_occurred_min=None, device_occurred_max=None, recorded_min=None, recorded_max=None,
                     posting_kind={}, source_type={}, provenance={}, distinct_cash_accounts=0,
                     rows_with_shift=0, rows_without_shift=0,
                     earliest_NORMAL_device_occurred_at=None, earliest_NORMAL_recorded_at=None,
                     reconstruction_rows=0, backfill_idempotency_keys=0)
        else:
            def _agg(fn, col, **filt):
                q = db.query(fn(col)).filter(CLE.tenant_id == c.id)
                for k, v in filt.items():
                    q = q.filter(getattr(CLE, k) == v)
                return q.scalar()
            r.update(
                device_occurred_min=_dt(_agg(func.min, CLE.device_occurred_at)),
                device_occurred_max=_dt(_agg(func.max, CLE.device_occurred_at)),
                recorded_min=_dt(_agg(func.min, CLE.recorded_at)),
                recorded_max=_dt(_agg(func.max, CLE.recorded_at)),
                posting_kind={k: n for k, n in db.query(CLE.posting_kind, func.count()).filter(
                    CLE.tenant_id == c.id).group_by(CLE.posting_kind).all()},
                source_type={k: n for k, n in db.query(CLE.source_type, func.count()).filter(
                    CLE.tenant_id == c.id).group_by(CLE.source_type).all()},
                provenance={k: n for k, n in db.query(CLE.provenance, func.count()).filter(
                    CLE.tenant_id == c.id).group_by(CLE.provenance).all()},
                distinct_cash_accounts=db.query(func.count(func.distinct(CLE.cash_account_id))).filter(
                    CLE.tenant_id == c.id).scalar(),
                rows_with_shift=base.filter(CLE.shift_id.isnot(None)).count(),
                rows_without_shift=base.filter(CLE.shift_id.is_(None)).count(),
                earliest_NORMAL_device_occurred_at=_dt(_agg(func.min, CLE.device_occurred_at, provenance="NORMAL")),
                earliest_NORMAL_recorded_at=_dt(_agg(func.min, CLE.recorded_at, provenance="NORMAL")),
                reconstruction_rows=base.filter(CLE.provenance == "RECONSTRUCTION").count(),
                backfill_idempotency_keys=db.query(func.count()).filter(
                    CLE.tenant_id == c.id, CLE.idempotency_key.like("backfill:%")).scalar(),
            )
        rows.append(r)
    return rows


# ── §4 cash-account inventory (per company/branch) ──────────────────────────
def _account_inventory(db, comps) -> list[dict]:
    out = []
    for c in comps:
        agg = {}
        for bid, typ, st, n in db.query(
                CashAccount.branch_id, CashAccount.type, CashAccount.status, func.count()).filter(
                CashAccount.tenant_id == c.id).group_by(
                CashAccount.branch_id, CashAccount.type, CashAccount.status).all():
            d = agg.setdefault(str(bid), {"branch_id": str(bid), "active_till": 0, "archived_till": 0, "safe": 0})
            if typ == "TILL" and st == "ACTIVE":
                d["active_till"] += n
            elif typ == "TILL":
                d["archived_till"] += n
            elif typ == "SAFE":
                d["safe"] += n
        for d in agg.values():
            out.append({"company": c.code, **d})
    return out


# ── §7 open legacy shifts + cash activity ────────────────────────────────────
def _open_shifts(db, comps) -> list[dict]:
    co_by_id = {c.id: c for c in comps}
    out = []
    for s in db.query(Shift).filter(Shift.status == ShiftStatus.open, Shift.deleted_at.is_(None)).all():
        br = db.get(Branch, s.branch_id)
        co = co_by_id.get(br.company_id) if br else None
        cash_pay = db.query(func.count()).select_from(SalePayment).join(
            Sale, Sale.id == SalePayment.sale_id).filter(
            Sale.shift_id == s.id, SalePayment.method_code == "cash").scalar()
        movs = db.query(func.count()).filter(CashMovement.shift_id == s.id).scalar()
        out.append({"shift_id": str(s.id), "company": (co.code if co else None),
                    "branch_id": str(s.branch_id), "cashier_id": str(s.cashier_id),
                    "opened_at": _dt(s.opened_at),
                    "till_id": (str(s.till_id) if s.till_id else None),
                    "terminal_id": (str(s.terminal_id) if s.terminal_id else None),
                    "classify": ("HAS_TILL" if s.till_id else "LEGACY_UNKNOWN"),
                    "cash_sale_payments": int(cash_pay or 0), "cash_movements": int(movs or 0)})
    return out


# ── §8 reconciliation reviews (read-only) ────────────────────────────────────
def _reconciliation(db, comps) -> list[dict]:
    out = []
    for c in comps:
        for f in phase1.reconcile_shadows(db, c.id):
            d = f.as_dict()
            out.append({"company": c.code, "code": d["code"], "severity": d["severity"],
                        "scope": d["scope"], "detail": d["detail"][:240]})
    return out


# ── §6 prior backfill (per company) + §9 T0 candidate ───────────────────────
def _prior_backfill(inv_row: dict) -> str:
    if inv_row["total_rows"] == 0:
        return "NO"
    return "YES" if (inv_row["reconstruction_rows"] > 0 or inv_row["backfill_idempotency_keys"] > 0) else "NO"


def _t0_candidate(db, comps, inv) -> dict:
    """Ledger-alone evidence bilan T0 chegarasini baholaydi (SET qilmaydi). Qoida: recon < T0 <= runtime,
    overlap YO'Q, gap YO'Q. Ledger'да tarixiy taraf bo'lmasa (backfill hali yo'q) -> ledger-alone ISBOTLAB
    BO'LMAYDI (tarixiy hodisalar legacy jadvallarда)."""
    per = []
    provable_all = True
    any_activity = False
    for c, r in zip(comps, inv):
        recon_n = r["reconstruction_rows"] if r["total_rows"] else 0
        normal_n = (r["provenance"].get("NORMAL", 0) if r["total_rows"] else 0)
        rec = {"company": c.code, "reconstruction_rows": recon_n, "normal_rows": normal_n}
        if r["total_rows"] == 0:
            rec.update(status="NO_LEDGER_ACTIVITY", reason="ledger bo'sh — runtime dual-write hali yozmagan")
            per.append(rec); continue
        any_activity = True
        # RECONSTRUCTION max device vs NORMAL min device
        recon_max = db.query(func.max(CLE.device_occurred_at)).filter(
            CLE.tenant_id == c.id, CLE.provenance == "RECONSTRUCTION").scalar()
        normal_min = db.query(func.min(CLE.device_occurred_at)).filter(
            CLE.tenant_id == c.id, CLE.provenance == "NORMAL").scalar()
        rec.update(reconstruction_device_max=_dt(recon_max), normal_device_min=_dt(normal_min))
        if recon_n and normal_n:
            if recon_max is not None and normal_min is not None and recon_max < normal_min:
                rec.update(status="PROVABLE", candidate_window=[_dt(recon_max), _dt(normal_min)],
                           reason="recon(<T0) va NORMAL(>=T0) ORASIDA toza chegara (overlap yo'q)")
            else:
                provable_all = False
                rec.update(status="NOT_PROVABLE_OVERLAP",
                           reason="RECONSTRUCTION device_max >= NORMAL device_min -> overlap")
        elif normal_n and not recon_n:
            provable_all = False
            rec.update(status="NOT_PROVABLE_LEDGER_ALONE",
                       candidate_hint=_dt(normal_min),
                       reason=("backfill hali yo'q; ledger'да faqat NORMAL. Tarixiy hodisalar legacy "
                               "jadvallarда -> ledger-alone T0 ISBOTLAMAYDI. Nomzod ~ earliest NORMAL "
                               "(dual-write start); operator T0'ni tasdiqlaydi (toza instant, backup)."))
        else:  # recon only
            provable_all = False
            rec.update(status="NOT_PROVABLE_NO_RUNTIME",
                       reason="faqat RECONSTRUCTION; runtime NORMAL yo'q -> dual-write boshlanmagan")
        per.append(rec)
    if not any_activity:
        overall = "T0_NOT_DETERMINED"
    elif provable_all:
        overall = "PROVABLE"
    else:
        overall = "NOT_PROVABLE"
    return {"candidate_status": overall, "per_company": per,
            "rule": "historical RECONSTRUCTION < T0 <= runtime NORMAL; no overlap, no unexplained gap. "
                    "T0 operator qarori (toza instant, barcha TILL smena yopiq, backup verified) — tool SET qilmaydi."}


def probe(db) -> dict:
    comps = _companies(db)
    inv = _ledger_inventory(db, comps)
    for r in inv:
        r["prior_backfill"] = _prior_backfill(r)
    return {
        "kind": "CASH_T0_PROBE",
        "cutover_state": _cutover_state(db, comps),
        "ledger_inventory": inv,
        "cash_account_inventory": _account_inventory(db, comps),
        "open_legacy_shifts": _open_shifts(db, comps),
        "reconciliation_reviews": _reconciliation(db, comps),
        "t0_candidate": _t0_candidate(db, comps, inv),
    }


def _print_human(rep: dict) -> None:
    C.out("")
    C.out("CUTOVER STATE (per company):")
    for c in rep["cutover_state"]:
        C.out(f"   {c['code']:<10} {c['name'][:24]:<24} cutover_at={c['cutover_at'] or 'UNSET':<28} "
              f"enforcement={c['enforcement']}")
    C.out("")
    C.out("LEDGER INVENTORY (per company):")
    for r in rep["ledger_inventory"]:
        C.out(f"   {r['code']:<10} rows={r['total_rows']}  prior_backfill={r['prior_backfill']}")
        if r["total_rows"]:
            C.out(f"      device[{r['device_occurred_min']} .. {r['device_occurred_max']}]  "
                  f"recorded[{r['recorded_min']} .. {r['recorded_max']}]")
            C.out(f"      provenance={r['provenance']}  posting_kind={r['posting_kind']}")
            C.out(f"      source_type={r['source_type']}")
            C.out(f"      accounts={r['distinct_cash_accounts']}  with_shift={r['rows_with_shift']}  "
                  f"without_shift={r['rows_without_shift']}  recon_rows={r['reconstruction_rows']}  "
                  f"backfill_keys={r['backfill_idempotency_keys']}")
            C.out(f"      earliest_NORMAL: device={r['earliest_NORMAL_device_occurred_at'] or 'UNKNOWN'}  "
                  f"recorded={r['earliest_NORMAL_recorded_at'] or 'UNKNOWN'}")
    C.out("")
    C.out("CASH ACCOUNT INVENTORY (per branch):")
    for a in rep["cash_account_inventory"]:
        C.out(f"   {a['company']:<10} branch={a['branch_id']}  ACTIVE_TILL={a['active_till']}  "
              f"ARCHIVED_TILL={a['archived_till']}  SAFE={a['safe']}")
    if not rep["cash_account_inventory"]:
        C.out("   (no cash accounts provisioned)")
    C.out("")
    C.out(f"OPEN LEGACY SHIFTS ({len(rep['open_legacy_shifts'])}):")
    for s in rep["open_legacy_shifts"]:
        C.out(f"   {s['shift_id']}  {s['company']}  branch={s['branch_id']}  cashier={s['cashier_id']}  "
              f"till={s['till_id'] or 'NULL'}  {s['classify']}  opened={s['opened_at']}  "
              f"cash_pay={s['cash_sale_payments']}  cash_mov={s['cash_movements']}")
    C.out("")
    C.out(f"RECONCILIATION REVIEWS ({len(rep['reconciliation_reviews'])}):")
    for f in rep["reconciliation_reviews"][:60]:
        C.out(f"   [{f['severity']}] {f['company']} {f['code']}  {f['scope']}  {f['detail']}")
    C.out("")
    t0 = rep["t0_candidate"]
    C.out(f"T0 CANDIDATE: {t0['candidate_status']}")
    for p in t0["per_company"]:
        C.out(f"   {p['company']:<10} {p['status']}  {p.get('reason', '')}")


def run(db, *, as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    C.print_header("T0 BOUNDARY PROBE (read-only)", mode_label="READ-ONLY", company_id=None, db=db)
    rep = probe(db)
    if as_json:
        C.emit_json(rep)
    else:
        _print_human(rep)
    status = rep["t0_candidate"]["candidate_status"]
    C.out("")
    if status == "PROVABLE":
        C.out("VERDICT: T0 candidate PROVABLE (clean recon<T0<=runtime boundary) — operator tasdiqlasin")
        return C.EXIT_OK
    C.out(f"VERDICT: {status}  (T0 chegarasi ledger-alone bilan isbotlanmadi — operator qarori + prereq'lar)")
    return C.EXIT_REVIEW


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_t0_probe",
                                description="STRICTLY READ-ONLY T0 boundary + ledger-state probe.")
    p.add_argument("--json", action="store_true", help="To'liq hisobotni JSON sifatida chiqarish.")
    args = p.parse_args(argv)
    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, as_json=args.json)
    finally:
        db.rollback()   # STRICTLY READ-ONLY: hech qanday yozuv commit qilinmaydi
        db.close()


if __name__ == "__main__":
    sys.exit(main())
