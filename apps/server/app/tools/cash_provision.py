# -*- coding: utf-8 -*-
"""Cash Migration CLI · PROVISION cash accounts (FIZIK TILL(lar) + branch SAFE).

Operator:
  DRY-RUN (default): `railway run --service savdoos python -m app.tools.cash_provision [--company-id <uuid>]`
  APPLY:             `... python -m app.tools.cash_provision --apply [--mapping <path>] [--skip-ambiguous]`

REAL fizik model: BIR FILIAL != BIR TILL. Har fizik checkout/kassa (terminal yoki operator mapping bilan
aniqlanган) = alohida TILL; har branch (odatda) 1 SAFE. Fizik checkout aniqlash: OPERATOR_MAPPING >
EXISTING > TERMINAL > AMBIGUOUS. Terminal dalili YO'Q va operator mapping yo'q -> AMBIGUOUS (APPLY BLOCK).
"Ko'p kassir = ko'p TILL" HECH QACHON taxmin qilinmaydi. Faqat cash_accounts yoziladi — LEDGER'ga YO'Q.

--mapping <path>: operator explicit TILL mapping (JSON) — AMBIGUOUS branch'larni hал qiladi.

Exit: 0 = ok, 2 = ambiguous branch(lar) bor (dry-run yoki --skip-ambiguous bilan o'tkazildi),
3 = refuse (apply + ambiguous, --skip-ambiguous'siz), 1 = usage.
"""
from __future__ import annotations

import argparse
import sys

from app.db.cash.migration import phase0
from app.services.cash import till_identity as _ti

from app.tools import _common as C


def run(db, company_id, *, apply: bool, mapping, skip_ambiguous: bool, as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    mode_label = "APPLY (writes cash_accounts)" if apply else "DRY-RUN (no writes)"
    C.print_header("PROVISION cash accounts (physical drawer)", mode_label=mode_label,
                   company_id=company_id, db=db,
                   extra={"mapping": (mapping.source_path or "inline") if mapping else "none"})

    mappings, findings = phase0.propose_till_mapping(db, company_id, mapping=mapping)
    fd = C.findings_to_dicts(findings)
    block, review, info = C.split_severity(fd)
    ambiguous = [m for m in mappings if m.confidence == "AMBIGUOUS"]

    # 1) DOIM avval reja (apply=False) — operator ko'radi.
    plan = phase0.provision_accounts(db, mappings, apply=False, mapping=mapping)
    _print_plan(mappings, ambiguous, plan, block, as_json=as_json)

    # 2) DYNAMIC TILL: AMBIGUOUS (fizik drawer hozircha noma'lum) branch --apply'ni TO'XTATMAYDI —
    # resolvable TILL/SAFE'lar provisionlanadi, ambiguous branch SKIP qilinadi (soxta TILL YO'Q). Operator
    # keyinroq --mapping / POST /tills bilan qo'shadi. --skip-ambiguous endi no-op (backward-compat).
    _ = skip_ambiguous

    # 3) APPLY — provision_accounts idempotent (fizik identity dedup), faqat cash_accounts, ledger YO'Q.
    applied = plan
    if apply:
        C.print_apply_warning("cash.cash_accounts (TILL/SAFE) — ledger'ga EMAS")
        applied = phase0.provision_accounts(db, mappings, apply=True, mapping=mapping)
        db.commit()
        C.out(f"APPLIED: tills_created={applied['tills_created']}  safes_created={applied['safes_created']}  "
              f"already_existing={applied['existing']}  skipped_ambiguous={applied['skipped_ambiguous']}")
        if as_json:
            C.emit_json({"kind": "CASH_PROVISION_APPLIED", "result": applied})

    # ── Verdict / exit ────────────────────────────────────────────────────────
    C.out("")
    if ambiguous:
        C.out(f"VERDICT: REVIEW  ({len(ambiguous)} AMBIGUOUS branch provisionlanmadi — operator --mapping "
              "yoki terminal_id bilan hал qilsin)")
        return C.EXIT_REVIEW
    C.out(f"VERDICT: OK  (tills_created={applied['tills_created']}, safes_created={applied['safes_created']}, "
          f"existing={applied['existing']}, applied={bool(apply)})")
    return C.EXIT_OK


def _all_safes(mappings):
    return [m for m in mappings if m.proposed_type == "SAFE"]


def _print_plan(mappings, ambiguous, plan, block, *, as_json: bool) -> None:
    if as_json:
        C.emit_json({"kind": "CASH_PROVISION_PLAN",
                     "auto_safes_not_requested": [m.branch_code for m in _all_safes(mappings)
                                                  if m.source == "AUTO_SAFE_NOT_REQUESTED"],
                     "mappings": [m.as_dict() for m in mappings],
                     "ambiguous": [m.as_dict() for m in ambiguous],
                     "plan": plan, "block_findings": block})
        return
    # Per-branch: detected physical checkouts / TILL / SAFE with source + confidence.
    by_branch: dict = {}
    for m in mappings:
        by_branch.setdefault((m.branch_code, str(m.branch_id)), []).append(m)
    C.out("")
    C.out("Physical drawer model (branch -> fizik checkouts):")
    for (code, _bid), items in by_branch.items():
        tills = [m for m in items if m.proposed_type == "TILL"]
        safes = [m for m in items if m.proposed_type == "SAFE"]
        amb = [m for m in tills if m.confidence == "AMBIGUOUS"]
        if amb:
            C.out(f"   Branch {code}: AMBIGUOUS  (fizik drawer aniqlanmadi — operator --mapping/terminal kerak)")
            continue
        C.out(f"   Branch {code}: {len(tills)} TILL + {len(safes)} SAFE")
        for m in tills:
            term = m.terminal_id or "-"
            C.out(f"      TILL {m.checkout_code:<16} terminal={term}  source={m.source}  conf={m.confidence}")
        for m in safes:
            C.out(f"      SAFE {m.checkout_code:<16} source={m.source}")
            if m.source == "AUTO_SAFE_NOT_REQUESTED":
                # §2: branch = 0..N SAFE; SAFE AVTOMATIK TALAB QILINMAYDI. Operator so'ramagan
                # SAFE'ni JIMGINA yaratmaymiz — bu yerda BALAND ogohlantiramiz.
                C.out("         !! AUTO-SAFE: operator bu SAFE'ni SO'RAMAGAN (mapping'da branch yo'q "
                      "yoki 'safe' kaliti yozilmagan). SAFE MAJBURIY EMAS — kerak bo'lmasa "
                      "mapping'ga \"safe\": false qo'shing.")
    C.out("")
    C.out("Provision plan (idempotent — fizik identity dedup):")
    for p in plan["plan"]:
        acc = f"  id={p.get('cash_account_id')}" if p.get("cash_account_id") else ""
        C.out(f"   branch={p['branch_id']}  {p['type']:<4} {str(p.get('checkout_code')):<16} "
              f"action={p['action']}  source={p.get('source')}{acc}")
    C.out("")
    auto_safes = sum(1 for m in _all_safes(mappings) if m.source == "AUTO_SAFE_NOT_REQUESTED")
    C.out(f"SUMMARY: tills={plan['tills_created']}  safes={plan['safes_created']}  "
          f"existing={plan['existing']}  skip_ambiguous={plan['skipped_ambiguous']}")
    if auto_safes:
        C.out(f"OGOHLANTIRISH: {auto_safes} ta SAFE operator SO'RAMASDAN rejalashtirilgan "
              "(AUTO_SAFE_NOT_REQUESTED). SAFE faqat inkassa (TILL->SAFE) yoki SAFE custody uchun "
              "kerak — kerak bo'lmasa mapping'da \"safe\": false bering.")


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_provision",
                                description="Provision physical TILL(s) + branch SAFE (idempotent; ledger'ga yozmaydi).")
    p.add_argument("--company-id", default=None, help="Faqat shu tenant (UUID).")
    p.add_argument("--apply", action="store_true", help="Haqiqiy yozuv (default: DRY-RUN reja).")
    p.add_argument("--mapping", default=None,
                   help="Operator explicit TILL mapping (JSON fayl yo'li) — AMBIGUOUS branch'larni hал qiladi.")
    p.add_argument("--skip-ambiguous", action="store_true",
                   help="--apply'да AMBIGUOUS branch'larни ATAYLAB o'tkazib, qolganini provisionlash.")
    p.add_argument("--json", action="store_true", help="Reja/natijani JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
    except ValueError:
        C.err(f"XATO: --company-id noto'g'ri UUID: {args.company_id!r}")
        return C.EXIT_USAGE
    mapping = None
    if args.mapping:
        try:
            mapping = _ti.load_operator_mapping(args.mapping)
        except (OSError, _ti.MappingError, ValueError) as e:
            C.err(f"XATO: --mapping yuklab bo'lmadi ({args.mapping}): {e}")
            return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id, apply=args.apply, mapping=mapping,
                   skip_ambiguous=args.skip_ambiguous, as_json=args.json)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
