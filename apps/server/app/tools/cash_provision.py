# -*- coding: utf-8 -*-
"""Cash Migration CLI · PROVISION cash accounts (TILL / optional SAFE).

Operator:
  DRY-RUN (default): `railway run --service savdoos python -m app.tools.cash_provision [--company-id <uuid>]`
  APPLY:             `... python -m app.tools.cash_provision --apply [--skip-ambiguous] [--include-safe]`

Mapping'дан TILL (ixtiyoriy SAFE) CashAccount yaratadi — IDEMPOTENT (mavjud bo'lса o'tkazadi).
Faqat cash_accounts yoziladi — LEDGER'ga HECH NARSA yozilmaydi. AMBIGUOUS filial (noaniq TILL/valyuta)
default'да --apply'ни TO'XTATADI (operator hал qilгунча); ataylab o'tkazish --skip-ambiguous bilan.

Exit: 0 = ok, 2 = ambiguous branch(lar) bor (dry-run yoki apply'да o'tkazildi), 3 = refuse (apply
+ ambiguous, --skip-ambiguous'siz), 1 = usage.
"""
from __future__ import annotations

import argparse
import sys

from app.db.cash.migration import phase0

from app.tools import _common as C


def run(db, company_id, *, apply: bool, include_safe: bool, skip_ambiguous: bool,
        as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    mode_label = "APPLY (writes cash_accounts)" if apply else "DRY-RUN (no writes)"
    C.print_header("PROVISION cash accounts", mode_label=mode_label, company_id=company_id, db=db,
                   extra={"include_safe": include_safe})

    mappings, findings = phase0.propose_till_mapping(db, company_id)
    fd = C.findings_to_dicts(findings)
    block, review, info = C.split_severity(fd)
    ambiguous = [m for m in mappings if m.confidence == "AMBIGUOUS"]

    # 1) DOIM avval reja (apply=False) — operator ko'radi.
    plan = phase0.provision_accounts(db, mappings, apply=False, include_safe=include_safe)

    _print_plan(mappings, ambiguous, plan, block, as_json=as_json)

    # 2) AMBIGUOUS bo'lса --apply'ни to'xtatamiz (aniq --skip-ambiguous bo'lmasa).
    if apply and ambiguous and not skip_ambiguous:
        C.out("")
        C.out(f"REFUSED: {len(ambiguous)} ta AMBIGUOUS filial bor (TILL/valyuta identity noaniq). "
              "Ular provisionlanmaydi. Ataylab qolganini yaratish uchun --skip-ambiguous bering, "
              "yoki avval AMBIGUOUS'ни hal qiling (preflight'ga qarang).")
        return C.EXIT_BLOCK

    # 3) APPLY — provision_accounts idempotent, faqat cash_accounts, ledger YO'Q.
    applied = plan
    if apply:
        C.print_apply_warning("cash.cash_accounts (TILL/SAFE) — ledger'ga EMAS")
        applied = phase0.provision_accounts(db, mappings, apply=True, include_safe=include_safe)
        db.commit()
        C.out(f"APPLIED: created={applied['to_create']}  already_existing={applied['existing']}  "
              f"skipped_ambiguous={applied['skipped_ambiguous']}")
        if as_json:
            C.emit_json({"kind": "CASH_PROVISION_APPLIED", "result": applied})

    # ── Verdict / exit ────────────────────────────────────────────────────────
    C.out("")
    if ambiguous:
        C.out(f"VERDICT: REVIEW  ({len(ambiguous)} AMBIGUOUS filial provisionlanmadi — operator hal qiladi)")
        return C.EXIT_REVIEW
    C.out(f"VERDICT: OK  (to_create={applied['to_create']}, existing={applied['existing']}, "
          f"applied={bool(apply)})")
    return C.EXIT_OK


def _print_plan(mappings, ambiguous, plan, block, *, as_json: bool) -> None:
    if as_json:
        C.emit_json({"kind": "CASH_PROVISION_PLAN",
                     "till_mappings": [m.as_dict() for m in mappings],
                     "ambiguous": [m.as_dict() for m in ambiguous],
                     "plan": plan, "block_findings": block})
        return
    C.out("")
    C.out(f"TILL mapping (branch = 1 TILL): {len(mappings)} branch(lar)")
    for m in mappings:
        C.out(f"   {m.branch_code:>10}  {m.proposed_type}  conf={m.confidence:<9} cur={m.currency or '?':<4} "
              f"{m.reason}")
    C.out("")
    C.out("Provision plan (idempotent):")
    for p in plan["plan"]:
        acc = f"  id={p.get('cash_account_id')}" if p.get("cash_account_id") else ""
        C.out(f"   branch={p['branch_id']}  type={p['type']}  action={p['action']}{acc}")
    C.out("")
    C.out(f"SUMMARY: to_create={plan['to_create']}  existing={plan['existing']}  "
          f"skip_ambiguous={plan['skipped_ambiguous']}")


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_provision",
                                description="Provision cash TILL/SAFE accounts (idempotent; ledger'ga yozmaydi).")
    p.add_argument("--company-id", default=None, help="Faqat shu tenant (UUID).")
    p.add_argument("--apply", action="store_true", help="Haqiqiy yozuv (default: DRY-RUN reja).")
    p.add_argument("--include-safe", action="store_true", help="TILL bilan birga SAFE ham yaratsin.")
    p.add_argument("--skip-ambiguous", action="store_true",
                   help="--apply'да AMBIGUOUS filiallarни ATAYLAB o'tkazib, qolganini provisionlash.")
    p.add_argument("--json", action="store_true", help="Reja/natijani JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
    except ValueError:
        C.err(f"XATO: --company-id noto'g'ri UUID: {args.company_id!r}")
        return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id, apply=args.apply, include_safe=args.include_safe,
                   skip_ambiguous=args.skip_ambiguous, as_json=args.json)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
