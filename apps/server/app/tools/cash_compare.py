# -*- coding: utf-8 -*-
"""Cash Migration CLI · COMPARE (Phase-3 observation, READ-ONLY).

Operator: `python -m app.tools.cash_compare --t0 <ISO8601> [--company-id <uuid>] [--report]
            [--clean-cycles N]`

HECH NARSA yozmaydi/tuzatmaydi (auto-repair YO'Q). Bitta deterministik solishtirish yugurishi:
  compare_run (aggregate + event-level reconcile + exceptions) · operator_report (matn) ·
  evaluate_cutover_readiness (READ-ONLY — LEDGER_PRIMARY O'RNATMAYDI, cutover qarorини O'ZI qilmaydi).

Netting YO'Q (absolute delta) — teng-qarama-qarshi xatolar bir-birini yashira olmaydi. --report
operator matnini chiqaradi; --clean-cycles readiness'даги observation-cycle mezoni uchun.

Exit: 0 = MATCH, 2 = REVIEW, 3 = BLOCK, 1 = usage.
"""
from __future__ import annotations

import argparse
import sys

from app.services.cash import compare_engine as ce

from app.tools import _common as C


def run(db, company_id, t0, *, report: bool, clean_cycles: int, run_id, as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    C.print_header("COMPARE (Phase-3, read-only)", mode_label="READ-ONLY",
                   company_id=company_id, db=db, t0=t0)

    cr = ce.compare_run(db, company_id=company_id, t0=t0, run_id=run_id)
    readiness = ce.evaluate_cutover_readiness(db, company_id=company_id, t0=t0, run=cr,
                                              completed_clean_cycles=clean_cycles)

    if as_json:
        C.emit_json({"kind": "CASH_COMPARE", "run": cr, "readiness": readiness})
    else:
        C.out("")
        C.out(f"STATUS:                {cr['status']}")
        C.out(f"legacy_expected:       {cr['legacy_expected']}")
        C.out(f"ledger_expected:       {cr['ledger_expected']}")
        C.out(f"signed_delta:          {cr['signed_delta']}")
        C.out(f"absolute_delta:        {cr['absolute_delta']}   (netting YO'Q)")
        C.out(f"matched_events:        {cr['matched_events']}")
        C.out(f"mismatch_total:        {cr['mismatch_total']}")
        C.out(f"mismatch_counts:       {cr['mismatch_counts']}")
        C.out(f"off_shift / late_sync: {cr['off_shift_count']} / {cr['late_sync_count']}")
        C.out(f"exceptions (open):     {cr['exceptions']['open_total']}")
        C.out(f"divergent_tills:       {cr['divergent_tills']}")
        C.out("")
        C.out(f"CUTOVER READINESS:     {readiness['readiness']}  "
              f"(clean_cycles={clean_cycles}/{readiness['criteria']['required_clean_cycles']})")
        if readiness["reasons"]:
            C.out(f"   NOT_READY reasons: {[x['code'] for x in readiness['reasons']]}")
        C.out("   (READ-ONLY baholovchi — LEDGER_PRIMARY O'RNATILMAYDI; cutover keyingi faza operator qarori.)")
        if report:
            C.out("")
            C.out(ce.operator_report(cr))

    C.out("")
    if cr["status"] == "BLOCK":
        C.out("VERDICT: BLOCK  (unexplained mismatch / tenant mismatch / aggregate BLOCK)")
        return C.EXIT_BLOCK
    if cr["status"] == "REVIEW":
        C.out("VERDICT: REVIEW  (divergence/exception bor — MATCH emas; observation davom etsin)")
        return C.EXIT_REVIEW
    C.out("VERDICT: MATCH  (toza compare run)")
    return C.EXIT_OK


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_compare",
                                description="Phase-3 compare + cutover readiness (READ-ONLY).")
    p.add_argument("--company-id", default=None, help="Faqat shu tenant (UUID).")
    p.add_argument("--t0", required=True, help="T0 chegarasi (ISO8601). MAJBURIY (compare T0 talab qiladi).")
    p.add_argument("--run-id", default=None, help="Compare run id (ixtiyoriy).")
    p.add_argument("--report", action="store_true", help="To'liq operator matn hisobotini chiqarish.")
    p.add_argument("--clean-cycles", type=int, default=0,
                   help="Tugatilган toza observation sikllar soni (readiness mezoni uchun).")
    p.add_argument("--json", action="store_true", help="Natijani JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
    except ValueError:
        C.err(f"XATO: --company-id noto'g'ri UUID: {args.company_id!r}")
        return C.EXIT_USAGE
    if not (args.t0 or "").strip():
        C.err("XATO: --t0 MAJBURIY (ISO8601 T0 chegarasi).")
        return C.EXIT_USAGE
    if args.clean_cycles < 0:
        C.err("XATO: --clean-cycles manfiy bo'la olmaydi.")
        return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id, args.t0.strip(), report=args.report,
                   clean_cycles=args.clean_cycles, run_id=args.run_id, as_json=args.json)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
