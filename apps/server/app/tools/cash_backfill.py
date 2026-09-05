# -*- coding: utf-8 -*-
"""Cash Migration CLI · BACKFILL historical ledger legs (< T0, RECONSTRUCTION).

Operator:
  DRY-RUN (default):  `python -m app.tools.cash_backfill --t0 <ISO8601> [--company-id <uuid>]`
  APPLY:              `python -m app.tools.cash_backfill --t0 <ISO> --apply --approved-hash <hash>`

--t0 MAJBURIY (< T0 -> RECONSTRUCTION backfill, >= T0 -> live dual-write hududi). Dry-run yozmaydi
(plan_backfill + execute_backfill apply=False). APPLY uchun --apply VA --approved-hash IKKALASI
kerak — hash dry-run manifestidagi manifest_hash bilan AYNAN mos kelmasa RAD etiladi (hech narsa
yozilmaydi). Yozuv idempotent + append-only (ON CONFLICT DO NOTHING). DELETE/UPDATE YO'Q.

Exit: 0 = GO (dry-run toza yoki apply muvaffaqiyatli), 2 = REVIEW bandlari bor, 3 = BLOCK / NO-GO /
REJECTED_MANIFEST_MISMATCH / failed rows, 1 = usage.
"""
from __future__ import annotations

import argparse
import sys

from app.db.cash.migration import backfill, phase1

from app.tools import _common as C


def _dry_run(db, company_id, t0, *, as_json: bool) -> int:
    plan = phase1.plan_backfill(db, company_id=company_id, t0=t0)
    m = backfill.execute_backfill(db, company_id=company_id, t0=t0, apply=False)   # YOZUV YO'Q

    report = {
        "kind": "CASH_BACKFILL_DRY_RUN",
        "t0": t0,
        "candidate_rows": m["candidate_rows"],
        "approved_rows": m["approved_rows"],
        "in_total": m["in_total"], "out_total": m["out_total"],
        "reconstructed_rows": m["reconstructed_rows"],
        "skipped_shadow_rows": m["skipped_shadow_rows"],
        "after_t0_deferred_to_live": plan["after_t0_deferred_to_live"],
        "blocked_rows": m["blocked_rows"],
        "review_rows": m["review_rows"],
        "duplicate_conflicts": len(plan["duplicate_conflicts"]),
        "go_no_go": m["go_no_go"],
        "manifest_hash": m["manifest_hash"],
        "rows_by_source_type": plan["rows_by_source_type"],
        "block": m["blocked"],
        "review_sample": m["review"][:40],
    }
    if as_json:
        C.emit_json(report)
    else:
        C.out("")
        C.out(f"candidate_rows:        {report['candidate_rows']}")
        C.out(f"approved_rows:         {report['approved_rows']}")
        C.out(f"IN total / OUT total:  {report['in_total']} / {report['out_total']}")
        C.out(f"reconstructed_rows:    {report['reconstructed_rows']}")
        C.out(f"skipped_shadow_rows:   {report['skipped_shadow_rows']}  (soya, double-count oldini oladi)")
        C.out(f"after_t0 (deferred):   {report['after_t0_deferred_to_live']}  (>= T0 -> live dual-write)")
        C.out(f"BLOCK rows:            {report['blocked_rows']}")
        C.out(f"REVIEW rows:           {report['review_rows']}")
        C.out(f"duplicate_conflicts:   {report['duplicate_conflicts']}")
        C.out(f"by source_type:        {report['rows_by_source_type']}")
        C.out("")
        C.out(f"GO/NO-GO:              {report['go_no_go']}")
        C.out(f"MANIFEST HASH:         {report['manifest_hash']}")
        C.out("   (APPLY uchun: --apply --approved-hash <yuqoridagi hash>)")

    if m["go_no_go"] != "GO":
        C.out("")
        C.out(f"VERDICT: BLOCK  (NO-GO: blocked={report['blocked_rows']}, dup={report['duplicate_conflicts']})")
        return C.EXIT_BLOCK
    if m["review_rows"] > 0:
        C.out("")
        C.out(f"VERDICT: REVIEW  (GO, lekin {m['review_rows']} REVIEW band operator e'tiborini kutadi)")
        return C.EXIT_REVIEW
    C.out("")
    C.out("VERDICT: GO  (toza dry-run; approved-hash bilan APPLY qilса bo'ladi)")
    return C.EXIT_OK


def _apply(db, company_id, t0, approved_hash, run_id, batch_size, *, as_json: bool) -> int:
    C.print_apply_warning("THE CASH MIGRATION TABLES (cash.cash_ledger_entries + cash.shifts)")
    m = backfill.execute_backfill(db, company_id=company_id, t0=t0, apply=True,
                                  approved_hash=approved_hash, batch_size=batch_size, run_id=run_id)

    if m.get("status") == "REJECTED_MANIFEST_MISMATCH":
        C.out("")
        C.out("REJECTED: approved-hash dry-run manifest_hash bilan MOS KELMADI — HECH NARSA yozilmadi.")
        C.out(f"   expected (siz bergan): {m['expected_hash']}")
        C.out(f"   actual   (hozirgi):    {m['actual_hash']}")
        C.out("   (Sabab: T0/ma'lumot/scope o'zgargan. Qayta dry-run qilib, yangi hash bilan APPLY qiling.)")
        if as_json:
            C.emit_json({"kind": "CASH_BACKFILL_REJECTED", "manifest": m})
        C.out("")
        C.out("VERDICT: BLOCK  (REJECTED_MANIFEST_MISMATCH)")
        return C.EXIT_BLOCK

    report = {
        "kind": "CASH_BACKFILL_APPLIED", "run_id": m["run_id"], "t0": t0,
        "go_no_go": m["go_no_go"], "wrote_ledger": m["wrote_ledger"],
        "approved_rows": m["approved_rows"],
        "inserted_rows": m["inserted_rows"],
        "already_existing_rows": m["already_existing_rows"],
        "failed_rows": m["failed_rows"],
        "in_total": m["in_total"], "out_total": m["out_total"],
        "reconstructed_rows": m["reconstructed_rows"],
        "manifest_hash": m["manifest_hash"],
    }
    if as_json:
        C.emit_json(report)
    else:
        C.out("")
        C.out(f"run_id:                {report['run_id']}")
        C.out(f"GO/NO-GO:              {report['go_no_go']}   wrote_ledger={report['wrote_ledger']}")
        C.out(f"approved_rows:         {report['approved_rows']}")
        C.out(f"inserted_rows:         {report['inserted_rows']}")
        C.out(f"already_existing_rows: {report['already_existing_rows']}  (idempotent rerun)")
        C.out(f"failed_rows:           {report['failed_rows']}")
        C.out(f"IN / OUT total:        {report['in_total']} / {report['out_total']}")
        C.out(f"reconstructed_rows:    {report['reconstructed_rows']}")

    if m["go_no_go"] != "GO":
        C.out("")
        C.out("VERDICT: BLOCK  (NO-GO — blocking anomaliya; ledger'ga yozilmadi)")
        return C.EXIT_BLOCK
    if m["failed_rows"] > 0:
        C.out("")
        C.out(f"VERDICT: BLOCK  ({m['failed_rows']} qator yozilmadi — operator ko'rsin)")
        return C.EXIT_BLOCK
    C.out("")
    C.out(f"VERDICT: GO  (applied; inserted={m['inserted_rows']}, existing={m['already_existing_rows']}). "
          "Keyingi qadam: cash_verify.")
    return C.EXIT_OK


def run(db, company_id, t0, *, apply: bool, approved_hash, run_id, batch_size, as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    mode_label = "APPLY (writes ledger)" if apply else "DRY-RUN (no writes)"
    C.print_header("BACKFILL historical legs", mode_label=mode_label, company_id=company_id, db=db, t0=t0)
    if apply:
        return _apply(db, company_id, t0, approved_hash, run_id, batch_size, as_json=as_json)
    return _dry_run(db, company_id, t0, as_json=as_json)


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_backfill",
                                description="Backfill historical cash ledger legs (< T0, RECONSTRUCTION).")
    p.add_argument("--company-id", default=None, help="Faqat shu tenant (UUID).")
    p.add_argument("--t0", required=True, help="T0 chegarasi (ISO8601). MAJBURIY.")
    p.add_argument("--run-id", default=None, help="Backfill run id (ixtiyoriy; berilmasa avto).")
    p.add_argument("--apply", action="store_true", help="Haqiqiy yozuv (--approved-hash bilan SHART).")
    p.add_argument("--approved-hash", default=None,
                   help="Dry-run manifest_hash — --apply bilan SHART; mos kelmasa RAD.")
    p.add_argument("--batch-size", type=int, default=500, help="INSERT batch hajmi (default 500).")
    p.add_argument("--json", action="store_true", help="Hisobotni JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
    except ValueError:
        C.err(f"XATO: --company-id noto'g'ri UUID: {args.company_id!r}")
        return C.EXIT_USAGE
    if not (args.t0 or "").strip():
        C.err("XATO: --t0 MAJBURIY (ISO8601 T0 chegarasi).")
        return C.EXIT_USAGE
    if args.apply and not (args.approved_hash or "").strip():
        C.err("XATO: --apply uchun --approved-hash SHART (dry-run manifest_hash). Yozuv bajarilmadi.")
        return C.EXIT_USAGE
    if args.batch_size <= 0:
        C.err("XATO: --batch-size musbat bo'lishi kerak.")
        return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id, args.t0.strip(), apply=args.apply,
                   approved_hash=(args.approved_hash or "").strip() or None,
                   run_id=args.run_id, batch_size=args.batch_size, as_json=args.json)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
