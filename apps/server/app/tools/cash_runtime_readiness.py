# -*- coding: utf-8 -*-
"""Cash Migration CLI · PER-COMPANY RUNTIME READINESS (STRICTLY READ-ONLY).

Operator (Windows/Railway — `railway run` EMAS, chunki Windows Railway internal hostname'ini resolve
qilolmaydi; `ssh` ishlatiladi):
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_runtime_readiness
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_runtime_readiness --json
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_runtime_readiness \\
        --company-id <UUID> --json

`runtime_readiness.evaluate()` ustidagi QAYTA ISHLATILADIGAN operator qobig'i. APPLY REJIMI YO'Q —
bu CLI'да `--apply` degan bayroq UMUMAN mavjud emas.

═══ NIMA QILMAYDI (qat'iy) ══════════════════════════════════════════════════
  · cutover_at (T0) O'RNATMAYDI          · TILL/SAFE yaratmaydi
  · smena ochmaydi/yopmaydi              · cash mode'ni o'zgartirmaydi
  · ledger'ga yozmaydi, backfill qilmaydi
  · sir (DATABASE_URL/host/user/parol) chiqarmaydi
  · mijoz shaxsiy ma'lumotini chiqarmaydi (ism/telefon/qarz — YO'Q)
Faqat SELECT; oxirida session ROLLBACK + close.

═══ IKKI XIL "TILL YO'Q" ARALASHTIRILMAYDI (§5) ═════════════════════════════
  JORIY TILL YARATISH  ->  T0'DAN KEYINGI runtime'ni ishlatadi.
  TARIXIY IDENTITY     ->  BUGUNGI TILL BILAN HAL BO'LMAYDI. Bu CLI hech qachon
                            "tarixni tuzatish uchun kassa yarating" DEMAYDI.

Exit: 0 = barcha ko'rilgan kompaniyalar CUTOVER_READY, 2 = kamida bittasi
CURRENT_RUNTIME_NOT_READY, 1 = usage (noto'g'ri --company-id).
"""
from __future__ import annotations

import argparse
import sys

from app.db.cash.migration import runtime_readiness as RR
from app.tools import _common as C

KIND = "CASH_PER_COMPANY_RUNTIME_READINESS"

# §3: ANIQ sabab kodlari — mavhum "REVIEW" EMAS. Operator har kod uchun nima qilishni biladi.
REASON_CATALOG = {
    RR.R_NO_ACTIVE_TILL: ("Naqd bilan ishlaydigan filialda BUGUN ACTIVE TILL yo'q -> T0'dan keyin "
                          "o'sha filial naqd smena ocholmaydi."),
    RR.R_OPEN_SHIFT_NO_TILL: ("Ochiq legacy smenaning kassasi YO'Q yoki YAROQSIZ (ARCHIVED / boshqa "
                              "filial / boshqa tenant / mavjud emas) — T0'dan keyin runtime uni RAD "
                              "etadi, ya'ni smena naqd qabul qilolmaydi."),
    RR.R_RECON_ANOMALY: ("Haqiqiy nomuvofiqlik (ORTIQCHA/orphan soya) — ifodalagan naqd tiklanmasligi "
                         "mumkin; row-darajada tekshirilsin."),
    RR.R_SCHEMA_NOT_READY: "cash sxemasi (Postgres) deploy qilinmagan — runtime custody ishlamaydi.",
    RR.R_GUARD_NOT_READY: ("Markaziy post-T0 darvozasi yo'q — cutover'dan keyin TILL'siz naqd amallar "
                           "jimgina o'tib ketardi."),
    RR.R_OFFLINE_SYNC: ("POS qurilmalarining offline navbati bo'sh ekanini TIZIM ISBOTLAY OLMAYDI — "
                        "operator tasdig'i SHART."),
}

# §5: tarixiy identity siyosati — HECH QACHON "kassa yarating" tavsiyasi bilan aralashtirilmaydi.
HISTORICAL_POLICY = {
    "blocking": False,
    "rule": ("HISTORICAL_TILL_UNKNOWN — o'tmishdagi drawer identity'sini ISBOTLAB bo'lmaydi. Bunday "
             "qatorlar ledger'dan TASHQARIDA qoladi, manba jadvallari avtoritet tarixiy dalil bo'lib "
             "qoladi. Bu cutover BLOKERI EMAS va T0 uchun attestatsiya SHART EMAS."),
    "do_not": ("BUGUN TILL yaratish TARIXIY identity'ni HAL QILMAYDI. Joriy TILL provisioning FAQAT "
               "T0'dan keyingi runtime uchun. Tarixni faqat ANIQ dalil (saqlangan till_id, smena "
               "bog'lanishi, imzolangan drawer varaqasi) hal qiladi."),
}


def _schema_gate(db) -> None:
    """§8: Postgres + cash sxemasi SHART. Yo'q bo'lsa ANIQ kod bilan baland rad etadi (jim emas)."""
    if not C.is_postgres(db) or not C.has_cash_schema(db):
        C.err(f"BLOCKER: {RR.R_SCHEMA_NOT_READY} — {REASON_CATALOG[RR.R_SCHEMA_NOT_READY]}")
    C.require_postgres_cash(db)


def _cutover_decision(per: list) -> dict:
    """§7: T0 qarori shartlari. Tool NIMANI tekshira oladi va NIMANI tekshira OLMAYDI — ochiq ayriladi.
    Qurilma navbati BO'SH deb AVTOMATIK e'lon QILINMAYDI."""
    ready = [p["company"] for p in per if p["status"] == RR.CUTOVER_READY]
    blocked = [p["company"] for p in per if p["status"] != RR.CUTOVER_READY]
    # Tool tekshira OLADIGAN shartlar — HAR biri PASS/FAIL sifatida, "tekshirildi" deb YOLG'ON aytmasdan.
    checks = [
        (RR.R_NO_ACTIVE_TILL, "naqd bilan ishlaydigan har filialda ACTIVE TILL bor"),
        (RR.R_OPEN_SHIFT_NO_TILL, "har ochiq legacy smena AYNAN yaroqli joriy TILL'ga bog'langan"),
        (RR.R_RECON_ANOMALY, "haqiqiy reconciliation anomaliyasi yo'q (INFO/EXPECTED_LEGACY sanalmaydi)"),
        (RR.R_SCHEMA_NOT_READY, "cash sxemasi deploy qilingan (Postgres)"),
        (RR.R_GUARD_NOT_READY, "markaziy post-T0 guard mavjud"),
    ]
    verified = []
    for code, label in checks:
        failing = [p["company"] for p in per
                   if code in [b["code"] for b in p["runtime_blockers"]]]
        verified.append({"code": code, "check": label,
                         "state": ("FAIL" if failing else "PASS"),
                         "failing_companies": failing})
    return {
        "tool_verified": verified,
        "operator_confirmation_required": [
            {"code": RR.R_OFFLINE_SYNC, "state": RR.OPERATOR_CONFIRMATION_REQUIRED,
             "detail": ("HAR BIR POS qurilmasi kutilayotgan offline navbatini yuborsin va navbat = 0 "
                        "ekani TASDIQLANSIN. Tool buni tekshira OLMAYDI.")},
            {"code": "CASH_OPERATIONS_PAUSED", "state": RR.OPERATOR_CONFIRMATION_REQUIRED,
             "detail": "cutover lahzasida naqd amallar qisqa pauza qilinsin."},
            {"code": "BACKUP_AND_RESTORE_REHEARSAL", "state": RR.OPERATOR_CONFIRMATION_REQUIRED,
             "detail": "backup olinsin VA tiklash mashqi tekshirilsin."},
            {"code": "T0_INSTANT_CHOSEN_DELIBERATELY", "state": RR.OPERATOR_CONFIRMATION_REQUIRED,
             "detail": "T0 ONGLI ravishda, tinch lahzada tanlansin (tool T0'ni O'RNATMAYDI)."},
        ],
        "device_queue": {"state": RR.OPERATOR_CONFIRMATION_REQUIRED,
                         "claim": "NOT_VERIFIABLE_BY_TOOL",
                         "detail": ("Bu tool qurilma navbati bo'sh ekanini KO'RA OLMAYDI va "
                                    "'navbat bo'sh' deb E'LON QILMAYDI.")},
        "companies_ready_for_operator_decision": ready,
        "companies_blocked": blocked,
        "t0_set_by_this_tool": False,
    }


def build_report(db, *, company_id=None) -> dict:
    """Read-only hisobot: runtime_readiness.evaluate + operator qatlami (§2/§3/§5/§7)."""
    rep = dict(RR.evaluate(db, company_id=company_id))
    rep["kind"] = KIND
    rep["scope"] = ("SINGLE_COMPANY" if company_id is not None else "ALL_COMPANIES")
    rep["apply_mode"] = "NONE"           # bu CLI'да apply YO'Q
    rep["read_only"] = True
    rep["reason_catalog"] = REASON_CATALOG
    rep["historical_identity_policy"] = HISTORICAL_POLICY
    rep["cutover_decision"] = _cutover_decision(rep["per_company"])
    return rep


def _print_company(p: dict) -> None:
    C.out("")
    C.out("-" * 74)
    C.out(f" {p['company']}  ({p['name'][:32]})   -> {p['status']}")
    C.out(f"   company_id:  {p['company_id']}")
    C.out(f"   cutover_at:  {p['cutover_at'] or 'UNSET'}   enforcement={p['cutover_enforcement']}")
    C.out(f"   schema_ready={str(p['schema_ready']).lower()}   "
          f"post_t0_guard={'OK' if p['post_t0_guard_available'] else RR.R_GUARD_NOT_READY}")

    C.out("   FILIALLAR (ACTIVE TILL / ACTIVE SAFE / naqd bilan ishlaydimi):")
    for b in p["branches"]:
        flag = "" if (b["active_tills"] or not b["cash_transacting"]) else f"   <- {RR.R_NO_ACTIVE_TILL}"
        C.out(f"      {b['code']:<12} TILL={b['active_tills']:<3} SAFE={b['active_safes']:<3} "
              f"naqd={'ha' if b['cash_transacting'] else 'yoq'}{flag}")
    if not p["branches"]:
        C.out("      (faol filial yo'q)")
    # §4: SAFE HAR filial uchun TALAB QILINMAYDI — u faqat inkassa/SAFE custody kerak bo'lganda.
    C.out("   SAFE: majburiy EMAS. SAFE faqat inkassa (TILL->SAFE) yoki SAFE custody ishlatilsa kerak;")
    C.out("         SAFE yo'qligi cutover BLOKERI EMAS.")
    if p["idle_branches_without_till"]:
        C.out(f"   INFO: naqd faoliyati yo'q, kassasiz filial(lar): "
              f"{', '.join(p['idle_branches_without_till'])} — BLOKER EMAS.")

    C.out(f"   OCHIQ LEGACY SMENALAR: jami={p['open_shifts_total']}  "
          f"TILL bilan={p['open_shifts_with_till']}  TILL'siz={p['legacy_open_shifts_without_till']}")
    for s in p["legacy_open_shifts"]:
        # §6: FAQAT texnik identifikatorlar — mijoz ismi/telefoni/qarzi CHIQARILMAYDI.
        tail = "OK" if s["has_till"] else f"{RR.R_OPEN_SHIFT_NO_TILL} (till_state={s['till_state']})"
        C.out(f"      shift={s['shift_id']}  branch={s['branch_id']}  opened={s['opened_at']}  "
              f"till={s['till_id'] or 'NULL'}  {tail}")

    h = p["historical_identity"]
    C.out(f"   TARIXIY IDENTITY: {p['historical_identity_status']}  "
          f"review_rows={h['historical_till_unknown']}  (blocking={str(h['blocking']).lower()})")
    C.out(f"      {HISTORICAL_POLICY['do_not']}")

    C.out(f"   RECONCILIATION: anomaliya={len(p['reconciliation_anomalies'])}  "
          f"informational={len(p['reconciliation_informational'])}")
    for f in p["reconciliation_anomalies"][:20]:
        C.out(f"      [{f['severity']}] {f['code']}  {f['detail'][:150]}")

    C.out(f"   OFFLINE SYNC BARRIER: {p['offline_sync_barrier']}")
    for c in p["operator_confirmations"]:
        C.out(f"      {c['code']}: {c['fix']}")

    if p["runtime_blockers"]:
        C.out("   SABABLAR (aniq kodlar):")
        for b in p["runtime_blockers"]:
            C.out(f"      {b['code']} (x{b['count']})")
            C.out(f"         nima: {REASON_CATALOG.get(b['code'], '')}")
            C.out(f"         yechim: {b['fix']}")
    else:
        C.out("   SABABLAR: yo'q — joriy runtime tayyor.")


def _print_human(rep: dict) -> None:
    for p in rep["per_company"]:
        _print_company(p)
    t = rep["totals"]
    C.out("")
    C.out("=" * 74)
    C.out(f" JAMI: kompaniya={t['companies']}  CUTOVER_READY={t['cutover_ready']}  "
          f"CURRENT_RUNTIME_NOT_READY={t['runtime_not_ready']}")
    C.out(f"       tarixiy review kompaniyalar={t['with_historical_review']}  "
          f"tarixiy unknown qatorlar={t['historical_till_unknown_rows']} (BLOKER EMAS)")
    cd = rep["cutover_decision"]
    C.out("")
    C.out(" T0 QARORI — TOOL TEKSHIRA OLGANI:")
    for x in cd["tool_verified"]:
        tail = ("  <- " + ", ".join(x["failing_companies"])) if x["failing_companies"] else ""
        C.out(f"   [{x['state']}] {x['check']}{tail}")
    C.out(" T0 QARORI — OPERATOR TASDIG'I SHART (tool tekshira OLMAYDI):")
    for x in cd["operator_confirmation_required"]:
        C.out(f"   [{x['state']}] {x['code']}: {x['detail']}")
    C.out(f"   device_queue: {cd['device_queue']['claim']} — {cd['device_queue']['detail']}")
    C.out("")
    C.out(" ESLATMA: bu tool T0'ni O'RNATMAYDI, kassa/seyf YARATMAYDI, smena YOPMAYDI.")


def run(db, *, as_json: bool, company_id=None) -> int:
    C.set_stdout_json_only(as_json)   # --json: stdout FAQAT JSON (`| jq` uchun); qolgani stderr'ga
    C.guard_never_primary()
    _schema_gate(db)
    C.print_header("PER-COMPANY RUNTIME READINESS (read-only)", mode_label="READ-ONLY",
                   company_id=company_id, db=db, extra={"APPLY MODE": "NONE (mavjud emas)"})
    rep = build_report(db, company_id=company_id)
    if not rep["per_company"]:
        if company_id is not None:
            C.err("COMPANY_NOT_FOUND: berilgan --company-id bo'yicha faol kompaniya topilmadi.")
        else:
            C.err("NO_COMPANIES: bazada faol kompaniya yo'q — baholanadigan narsa yo'q.")
        return C.EXIT_USAGE
    if as_json:
        C.emit_json(rep)
    else:
        _print_human(rep)
    C.out("")
    if rep["totals"]["runtime_not_ready"] == 0:
        C.out(f"VERDICT: {RR.CUTOVER_READY} — joriy runtime tayyor. T0 hamon OPERATOR qarori "
              f"(offline sync + pauza + backup tasdiqlansin).")
        return C.EXIT_OK
    C.out(f"VERDICT: {RR.CURRENT_RUNTIME_NOT_READY} — "
          f"{rep['totals']['runtime_not_ready']} ta kompaniyada sabab(lar) bor (yuqorida aniq kodlar).")
    return C.EXIT_REVIEW


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m app.tools.cash_runtime_readiness",
        description="STRICTLY READ-ONLY per-company pre-T0 runtime readiness. Apply rejimi YO'Q.")
    p.add_argument("--json", action="store_true", help="To'liq hisobotni JSON sifatida chiqarish.")
    p.add_argument("--company-id", default=None,
                   help="Bitta tenant uchun baholash (UUID). Berilmasa — barcha kompaniyalar.")
    args = p.parse_args(argv)
    try:
        company_id = C.parse_company_id(args.company_id)
    except ValueError:
        C.err("USAGE: --company-id to'g'ri UUID bo'lishi kerak.")
        return C.EXIT_USAGE
    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, as_json=args.json, company_id=company_id)
    finally:
        db.rollback()   # STRICTLY READ-ONLY: hech qanday yozuv saqlanmaydi
        db.close()
        C.set_stdout_json_only(False)   # global bayroqni TIKLA (boshqa CLI'ga sizib ketmasin)


if __name__ == "__main__":
    sys.exit(main())
