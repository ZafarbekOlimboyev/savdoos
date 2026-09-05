# -*- coding: utf-8 -*-
"""Cash Migration CLI · VERIFY backfill (READ-ONLY, dual-write'дан OLDIN majburiy).

Operator: `python -m app.tools.cash_verify --t0 <ISO8601> [--company-id <uuid>]`

HECH NARSA yozmaydi. Bajarilган backfill'ни tekshiradi (verify_backfill + reconcile_backfill,
preflight.post_backfill_verification orkestri):
  duplicate business keys · tenant isolation · manifest parity (row count + IN/OUT) · deterministik id ·
  soya leg leak yo'q · barcha RECONSTRUCTION metadata · >= T0 backfill yo'q · unexplained delta = 0.

Verify manifesti dry-run'дан (execute_backfill apply=False, read-only) qayta hisoblanadi — alohida
manifest fayl saqlash SHART EMAS (deterministik). Exit: 0 = BARCHA majburiy PASS, 3 = biror majburiy
FAIL (dual-write YOQILMASIN), 1 = usage.
"""
from __future__ import annotations

import argparse
import sys

from app.db.cash.migration import backfill, preflight

from app.tools import _common as C


def run(db, company_id, t0, *, as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    C.print_header("VERIFY backfill (read-only)", mode_label="READ-ONLY", company_id=company_id, db=db, t0=t0)

    # Verify-manifest: dry-run (apply=False, YOZUV YO'Q) qayta hisoblab, "existing == approved" deb
    # o'rnatamiz — tugatilган backfill'да ledger'даги RECONSTRUCTION qatorlар soni AYNAN approved_rows.
    m = backfill.execute_backfill(db, company_id=company_id, t0=t0, apply=False)
    verify_manifest = dict(m)
    verify_manifest["inserted_rows"] = 0
    verify_manifest["already_existing_rows"] = m["approved_rows"]

    gate = preflight.post_backfill_verification(db, verify_manifest, company_id=company_id, t0=t0)
    mandatory = gate["mandatory"]
    verify = gate["verify"]
    reconcile = gate["reconcile"]

    if as_json:
        C.emit_json({"kind": "CASH_VERIFY", "ok": gate["ok"], "mandatory": mandatory,
                     "verify": verify, "reconcile": reconcile,
                     "expected_approved_rows": m["approved_rows"]})
    else:
        C.out("")
        C.out("Mandatory checks (hammasi PASS bo'lmasa DUAL_WRITE_SHADOW YOQILMAYDI):")
        for k, ok in mandatory.items():
            C.out(f"   [{'PASS' if ok else 'FAIL'}]  {k}")
        C.out("")
        C.out("Reconcile (legacy-expected vs ledger, per direction):")
        C.out(f"   expected IN/OUT: {reconcile['expected_in']} / {reconcile['expected_out']}")
        C.out(f"   ledger   IN/OUT: {reconcile['ledger_in']} / {reconcile['ledger_out']}")
        C.out(f"   delta    IN/OUT: {reconcile['delta_in']} / {reconcile['delta_out']}")
        C.out(f"   unexplained_delta: {reconcile['unexplained_delta']}")
        C.out(f"   expected RECONSTRUCTION rows (approved): {m['approved_rows']}")

    failed = [k for k, ok in mandatory.items() if not ok]
    C.out("")
    if gate["ok"]:
        C.out("VERDICT: PASS  (barcha majburiy tekshiruv o'tdi — dual-write precondition #9 bajarildi)")
        return C.EXIT_OK
    C.out(f"VERDICT: FAIL  (majburiy tekshiruvlar o'tmadi: {failed}) — DUAL_WRITE_SHADOW YOQILMASIN")
    return C.EXIT_BLOCK


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_verify",
                                description="Verify completed backfill (read-only; dual-write gate #9).")
    p.add_argument("--company-id", default=None, help="Faqat shu tenant (UUID).")
    p.add_argument("--t0", required=True, help="Backfill bilan BIR XIL T0 (ISO8601). MAJBURIY.")
    p.add_argument("--json", action="store_true", help="Natijani JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
    except ValueError:
        C.err(f"XATO: --company-id noto'g'ri UUID: {args.company_id!r}")
        return C.EXIT_USAGE
    if not (args.t0 or "").strip():
        C.err("XATO: --t0 MAJBURIY (backfill bilan bir xil T0).")
        return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id, args.t0.strip(), as_json=args.json)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
