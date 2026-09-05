# -*- coding: utf-8 -*-
"""Cash Migration CLI · PREFLIGHT (READ-ONLY discovery).

Operator: `railway run --service savdoos python -m app.tools.cash_preflight [--company-id <uuid>] [--json]`

HECH NARSA yozmaydi. Mavjud read-only asboblarни orkestrlaydi (phase0/phase1/compare_engine):
  PG readiness · inventory (companies/branches/terminals/open shifts) · TILL mapping (A/B/C multi-cashier)
  · currency muammolari · shadow reconcile · BLOCK/REVIEW yig'indisi.

Exit: 0 = READY, 2 = REVIEW (bloklamaydi), 3 = BLOCK (migratsiya to'xtaydi).
"""
from __future__ import annotations

import argparse
import sys

from app.db.cash.migration import phase0, phase1
from app.services.cash import compare_engine as ce

from app.tools import _common as C


def run(db, engine, company_id, *, as_json: bool) -> int:
    C.guard_never_primary()
    C.print_header("PREFLIGHT (read-only discovery)", mode_label="READ-ONLY",
                   company_id=company_id, db=db)

    readiness = phase0.readiness_check(engine)
    inv = phase0.inventory(db, company_id)
    mappings, map_find = phase0.propose_till_mapping(db, company_id)
    open_rows, open_find = phase0.map_open_shifts(db, mappings, company_id)
    dq_find = phase0.data_quality_audit(db, company_id)
    cur_find = phase0.currency_audit(db, company_id)
    shadow_find = phase1.reconcile_shadows(db, company_id)
    multi = ce.multi_cashier_till_finding(db, company_id)

    all_find = C.findings_to_dicts(list(map_find) + list(open_find) + list(dq_find)
                                   + list(cur_find) + list(shadow_find))
    block, review, info = C.split_severity(all_find)

    # multi-cashier: C -> BLOCK (drawer identity noaniq), B -> REVIEW (qo'shimcha TILL kerak), A -> ok
    readiness_ok = readiness.get("ok") in (True, None)   # None = SQLite skip (dev)

    report = {
        "kind": "CASH_PREFLIGHT",
        "readiness": readiness,
        "inventory": inv,
        "till_mappings": [m.as_dict() for m in mappings],
        "ambiguous_mappings": [m.as_dict() for m in mappings if m.confidence == "AMBIGUOUS"],
        "open_shift_mappings": open_rows,
        "open_shift_blocked": [r for r in open_rows if r.get("blocked")],
        "multi_cashier": multi,
        "shadow_reconcile": C.findings_to_dicts(shadow_find),
        "findings_block": block,
        "findings_review": review,
        "findings_info": info,
    }

    if as_json:
        C.emit_json(report)
    else:
        _print_human(report, readiness_ok)

    # ── Verdict / exit ────────────────────────────────────────────────────────
    is_block = bool(block) or not readiness_ok or multi["finding"] == "C"
    is_review = bool(review) or multi["finding"] == "B"
    C.out("")
    if is_block:
        C.out(f"VERDICT: BLOCK  (block findings={len(block)}, readiness_ok={readiness_ok}, "
              f"multi_cashier={multi['finding']})")
        return C.EXIT_BLOCK
    if is_review:
        C.out(f"VERDICT: REVIEW  (review findings={len(review)}, multi_cashier={multi['finding']})")
        return C.EXIT_REVIEW
    C.out("VERDICT: READY  (no blockers, no review items)")
    return C.EXIT_OK


def _print_human(r: dict, readiness_ok: bool) -> None:
    rc = r["readiness"]
    C.out("")
    C.out(f"PG readiness: ok={rc.get('ok')}  {('(' + rc.get('reason', '') + ')') if rc.get('reason') else ''}")
    checks = rc.get("checks") or {}
    for k in ("pg_version_ok", "cash_schema", "roles_ok", "posting_cannot_mutate_ledger",
              "search_path_not_cash_first"):
        if k in checks:
            C.out(f"   - {k}: {checks[k]}")
    tot = r["inventory"].get("totals", {})
    C.out("")
    C.out(f"Inventory (scope): companies={r['inventory'].get('company_count')}  "
          f"branches={tot.get('branches')} (active {tot.get('active_branches')})  "
          f"terminals={tot.get('terminals')}  open_shifts={tot.get('open_shifts')}  "
          f"cashiers={tot.get('cashiers')}")
    C.out(f"   sales={tot.get('sales')} cash_pay={tot.get('cash_sale_payments')} "
          f"purchases={tot.get('purchases')} cash_purchases={tot.get('cash_purchases')} "
          f"cash_movements={tot.get('cash_movements')} returns={tot.get('returns')}")
    mc = r["multi_cashier"]
    C.out("")
    C.out(f"Multi-cashier / TILL finding: {mc['finding']}  ({mc['cutover_impact']})")
    C.out(f"   {mc['summary']}")
    if r["ambiguous_mappings"]:
        C.out(f"   AMBIGUOUS branches: {len(r['ambiguous_mappings'])} (TILL identity/currency noaniq)")
    if r["open_shift_blocked"]:
        C.out(f"   OPEN shifts unmappable: {len(r['open_shift_blocked'])}")
    C.out("")
    C.out(f"Findings: BLOCK={len(r['findings_block'])}  REVIEW={len(r['findings_review'])}  "
          f"INFO={len(r['findings_info'])}")
    for f in r["findings_block"]:
        C.out(f"   [BLOCK]  {f['code']}  {f['scope']}  {f.get('detail', '')}")
    for f in r["findings_review"][:40]:
        C.out(f"   [REVIEW] {f['code']}  {f['scope']}  {f.get('detail', '')}")


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_preflight",
                                description="Cash migration READ-ONLY preflight discovery.")
    p.add_argument("--company-id", default=None, help="Faqat shu tenant (UUID). Berilmasa: barcha tenant.")
    p.add_argument("--json", action="store_true", help="To'liq hisobotni JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
    except ValueError:
        C.err(f"XATO: --company-id noto'g'ri UUID: {args.company_id!r}")
        return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, eng, company_id, as_json=args.json)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
