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


def run(db, company_id, t0, *, mapping, hist_map=None, approved_hash=None, as_json: bool) -> int:
    C.guard_never_primary()
    C.require_postgres_cash(db)
    C.print_header("VERIFY backfill (read-only)", mode_label="READ-ONLY", company_id=company_id, db=db, t0=t0,
                   extra={"mapping": (mapping.source_path or "inline") if mapping else "none"})

    # Verify-manifest: dry-run (apply=False, YOZUV YO'Q) qayta hisoblab, "existing == approved" deb
    # o'rnatamiz — tugatilган backfill'да ledger'даги RECONSTRUCTION qatorlар soni AYNAN approved_rows.
    # mapping applied backfill bilan BIR XIL bo'lishi kerak (aks holда approved_rows farq qiladi).
    # §12 PARITET: verify approved rejani AYNAN qayta hosil qilishi SHART — shu bois backfill bilan
    # BIR XIL historical_map (va mapping) uzatiladi. Usiz attestatsiyali legalar HISTORICAL_TILL_UNKNOWN
    # ga qaytib, row_count_matches YOLG'ON FAIL berardi va dual-write'ni bloklardi.
    m = backfill.execute_backfill(db, company_id=company_id, t0=t0, apply=False, mapping=mapping,
                                  historical_map=hist_map)
    # §12: approved-hash berilgan bo'lsa, INPUT IDENTITY mos kelishi SHART. Mos kelmasa BALAND OVOZDA
    # "input mismatch" — jimgina BOSHQA qatorlar to'plamini qayta hisoblab "PASS" demaydi.
    if approved_hash and str(approved_hash).strip() != m.get("manifest_hash"):
        C.out("")
        C.out("VERIFY INPUT MISMATCH — approved-hash qayta hisoblangan manifest bilan MOS KELMADI.")
        C.out(f"   approved (siz bergan): {str(approved_hash).strip()}")
        C.out(f"   actual   (qayta hisob): {m.get('manifest_hash')}")
        C.out(f"   historical_map_fingerprint: {m.get('historical_map_fingerprint')}")
        C.out(f"   mapping_fingerprint:        {m.get('mapping_fingerprint')}")
        C.out(f"   planner_schema_version:     {m.get('planner_schema_version')}")
        C.out("   Sabab odatda: --historical-till-map yoki --mapping BERILMAGAN/BOSHQA, yoki T0 farq qiladi.")
        if as_json:
            C.emit_json({"kind": "CASH_VERIFY_INPUT_MISMATCH", "expected_hash": str(approved_hash).strip(),
                         "actual_hash": m.get("manifest_hash"),
                         "historical_map_fingerprint": m.get("historical_map_fingerprint"),
                         "mapping_fingerprint": m.get("mapping_fingerprint"),
                         "planner_schema_version": m.get("planner_schema_version")})
        C.out("")
        C.out("VERDICT: BLOCK  (INPUT_MISMATCH — verify approved rejani qayta hosil qilolmadi)")
        return C.EXIT_BLOCK
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
        # §10: ATAYLAB kechiktirilgan tarixiy identity ALOHIDA ko'rsatiladi. expected_in/out'dan
        # allaqachon AYIRILGAN (ular izohlangan), shu bois busiz hisobot "hammasi joyida"day
        # ko'rinardi — 28 qator ledger'dan tashqarida qolgani bilan.
        C.out(f"   deferred_historical_identity: rows={reconcile.get('deferred_historical_identity_rows', 0)}  "
              f"IN={reconcile.get('deferred_historical_identity_in', 0)}  "
              f"OUT={reconcile.get('deferred_historical_identity_out', 0)}")
        C.out("      (dalilsiz tarixiy qatorlar ATAYLAB yozilmadi — bu SUKUT bilan muvaffaqiyat EMAS; "
              "manba jadvallari avtoritet tarixiy dalil bo'lib qoladi)")
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
    p.add_argument("--mapping", default=None,
                   help="Operator TILL mapping (JSON) — backfill'da ishlatilgani bilan BIR XIL bo'lsin.")
    p.add_argument("--historical-till-map", default=None,
                   help=("TARIXIY dalil fayli (kind=HISTORICAL_TILL_EVIDENCE) — backfill'da ishlatilgani "
                         "bilan AYNAN BIR XIL bo'lishi SHART, aks holda approved reja qayta hosil bo'lmaydi."))
    p.add_argument("--approved-hash", default=None,
                   help=("Dry-run/apply manifest_hash. Berilsa, verify qayta hisoblangan hash bilan "
                         "solishtiradi va mos kelmasa INPUT_MISMATCH bilan RAD etadi."))
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
    mapping = None
    if args.mapping:
        try:
            from app.services.cash import till_identity as _ti
            mapping = _ti.load_operator_mapping(args.mapping)
        except (OSError, ValueError) as e:
            C.err(f"XATO: --mapping yuklab bo'lmadi ({args.mapping}): {e}")
            return C.EXIT_USAGE
    hist_map = None
    if args.historical_till_map:
        # AYNI parser + AYNI validatsiya (backfill bilan bir xil) — alohida talqin YO'Q (§12).
        try:
            from app.db.cash.migration import historical_till as _hist
            hist_map = _hist.load_historical_map(args.historical_till_map)
        except (OSError, ValueError) as e:
            C.err(f"XATO: --historical-till-map yuklab bo'lmadi ({args.historical_till_map}): {e}")
            return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id, args.t0.strip(), mapping=mapping, hist_map=hist_map,
                   approved_hash=args.approved_hash, as_json=args.json)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
