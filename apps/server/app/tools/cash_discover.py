# -*- coding: utf-8 -*-
"""Cash Migration CLI · DISCOVER physical checkouts (READ-ONLY; operator mapping yordamchisi).

Operator: `railway run --service savdoos python -m app.tools.cash_discover [--company-id <uuid>]
            [--branch-id <uuid> ...] [--all] [--skeleton] [--json]`

HECH NARSA yozmaydi. AMBIGUOUS (fizik drawer aniqlanmagan) branch'lar uchun BARCHA read-only dalilni
to'playdi va operatorga to'ldirish uchun mapping JSON SKELETON chiqaradi. Terminal dalili (yoki mavjud
provisioned TILL) ANIQ bo'lsa tills[] AVTO to'ldiriladi; aks holда bo'sh qoldiriladi va "nechta fizik
kassa/yashik?" savoli ko'rsatiladi. "Ko'p kassir = ko'p TILL" HECH QACHON taxmin qilinmaydi.

Default: FAQAT AMBIGUOUS branch'lar. --all -> barcha branch. --branch-id -> aniq branch(lar).
Exit: 0 = hech AMBIGUOUS yo'q (hammasi resolved), 2 = operator input kerak (AMBIGUOUS bor), 1 = usage.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid as _uuid

from sqlalchemy import func

from app.models.org import Branch, Company, Terminal
from app.models.shifts import Shift
from app.models.enums import ShiftStatus
from app.services.cash import till_identity as _ti

from app.tools import _common as C


def _concurrent_multicashier(db, branch_id) -> bool:
    """Bir vaqtда (oyna kesishishi) turli-kassir smenasi bo'lganmi (sweep). FAQAT ma'lumot uchun —
    fizik TILL SONINI ANIQLAMAYDI (kassir != drawer)."""
    from datetime import datetime as _dt, timezone as _tz
    far = _dt(9999, 1, 1, tzinfo=_tz.utc)
    rows = db.query(Shift.cashier_id, Shift.opened_at, Shift.closed_at).filter(
        Shift.branch_id == branch_id, Shift.deleted_at.is_(None), Shift.opened_at.isnot(None)).all()
    shifts = sorted([(o, (c or far), cash) for cash, o, c in rows], key=lambda x: x[0])
    active = []
    for opened, closed, cashier in shifts:
        active = [a for a in active if a[0] > opened]
        if any(ac != cashier for _, ac in active):
            return True
        active.append((closed, cashier))
    return False


def _branch_evidence(db, br, *, mapping=None) -> dict:
    co = db.get(Company, br.company_id)
    terminals = db.query(Terminal).filter(Terminal.branch_id == br.id).all()
    shift_terms = _ti._branch_terminals(db, br.id)        # distinct terminal_id TIRIK smenаlarда {tid: name}
    open_sh = db.query(Shift).filter(
        Shift.branch_id == br.id, Shift.status == ShiftStatus.open, Shift.deleted_at.is_(None)).all()
    hist = db.query(func.count(Shift.id)).filter(
        Shift.branch_id == br.id, Shift.deleted_at.is_(None)).scalar() or 0
    cashiers = db.query(func.count(func.distinct(Shift.cashier_id))).filter(
        Shift.branch_id == br.id, Shift.deleted_at.is_(None)).scalar() or 0
    existing = _ti.list_tills(db, co.id, br.id)
    checkouts, source, conf, detail = _ti.detect_physical_checkouts(db, co.id, br, mapping=mapping)
    resolvable = source in (_ti.SRC_OPERATOR, _ti.SRC_EXISTING, _ti.SRC_TERMINAL)
    checkout_count = len(checkouts) if resolvable else "UNKNOWN"
    return {
        "company": {"id": str(co.id), "code": co.code, "name": co.name, "currency": co.currency},
        "branch": {"id": str(br.id), "code": br.code, "name": br.name, "is_active": br.is_active},
        "terminal_records": [{"id": str(t.id), "name": t.name, "is_active": t.is_active,
                              "device_uuid": t.device_uuid} for t in terminals],
        "shift_terminal_evidence": [{"terminal_id": str(t), "name": n} for t, n in shift_terms.items()],
        "open_shifts": [{"shift_id": str(s.id), "cashier_id": str(s.cashier_id),
                         "terminal_id": (str(s.terminal_id) if s.terminal_id else None),
                         "opened_at": s.opened_at.isoformat() if s.opened_at else None} for s in open_sh],
        "historical_shift_count": int(hist),
        "distinct_cashiers": int(cashiers),
        "concurrent_multi_cashier": _concurrent_multicashier(db, br.id),
        "existing_active_tills": [{"cash_account_id": str(a.id), "checkout_code": _ti.account_checkout_code(a),
                                   "terminal_id": (str(_ti.account_terminal_id(a)) if _ti.account_terminal_id(a) else None)}
                                  for a in existing],
        "detection_source": source,          # OPERATOR_MAPPING | EXISTING | TERMINAL | AMBIGUOUS | NO_ACTIVITY
        "detection_detail": detail,
        "physical_checkout_count": checkout_count,
        "confidence": ("HIGH" if resolvable else ("UNKNOWN" if source == _ti.SRC_AMBIGUOUS else "N/A")),
        "operator_input_required": source == _ti.SRC_AMBIGUOUS,
        "_checkouts": checkouts,             # skeleton uchun (auto-fill)
    }


def _skeleton_entry(ev: dict) -> dict:
    """Bitta branch uchun mapping skeleton yozuvi. Dalil aniq -> tills[] AVTO to'ldiriladi; UNKNOWN -> bo'sh."""
    tills = []
    for ck in ev["_checkouts"]:
        tills.append({"code": ck.checkout_code,
                      "terminal_id": (str(ck.terminal_id) if ck.terminal_id else None),
                      "label": ck.label_human})
    return {"safe": True, "tills": tills}    # tills bo'sh bo'lsa -> operator to'ldiradi


def run(db, company_id, branch_ids, *, only_ambiguous, as_json, emit_skeleton) -> int:
    C.guard_never_primary()
    C.print_header("DISCOVER physical checkouts (read-only)", mode_label="READ-ONLY",
                   company_id=company_id, db=db)

    q = db.query(Branch).filter(Branch.deleted_at.is_(None))
    if company_id is not None:
        q = q.filter(Branch.company_id == company_id)
    if branch_ids:
        q = q.filter(Branch.id.in_(branch_ids))
    branches = q.all()

    evidence = [_branch_evidence(db, br) for br in branches]
    if only_ambiguous and not branch_ids:
        evidence = [e for e in evidence if e["operator_input_required"]]
    ambiguous = [e for e in evidence if e["operator_input_required"]]

    skeleton = {"branches": {e["branch"]["id"]: _skeleton_entry(e) for e in evidence}}

    if as_json:
        C.emit_json({"kind": "CASH_DISCOVER", "evidence": [{k: v for k, v in e.items() if k != "_checkouts"}
                                                           for e in evidence],
                     "mapping_skeleton": skeleton})
    else:
        _print_human(evidence, ambiguous)
        if emit_skeleton:
            C.out("")
            C.out("═══ MAPPING JSON SKELETON (to'ldiring; bo'sh tills[] = operator kiritishi kerak) ═══")
            C.out(json.dumps(skeleton, indent=2, ensure_ascii=False))

    C.out("")
    if ambiguous:
        # DYNAMIC TILL: kassa soni noma'lumligi GLOBAL STOP EMAS (informatsion, exit 2). Operator kerak
        # bo'lganда (T0'дан oldin transact qiladigan branch uchun) kassa qo'shadi — hozir SHART EMAS.
        C.out(f"VERDICT: OPERATOR INPUT (informational)  ({len(ambiguous)} branch: fizik kassa soni hozircha "
              "UNKNOWN — DINAMIK TILL, migration BLOKLANMAYDI. T0'дан keyin transact qiladigan branch uchun "
              "'nechta fizik kassa?' javob berib tills[] to'ldiring yoki POST /tills bilan qo'shing)")
        return C.EXIT_REVIEW
    C.out("VERDICT: RESOLVED  (barcha branch fizik checkout aniq — qo'shimcha input shart emas)")
    return C.EXIT_OK


def _print_human(evidence, ambiguous) -> None:
    C.out("")
    C.out("DISCOVERY TABLE (per branch):")
    C.out(f"   {'Company':<18} {'Branch':<14} {'Branch UUID':<38} {'terms':>5} {'open':>4} "
          f"{'checkouts':>9} {'conf':>8}  input?")
    for e in evidence:
        co = (e['company']['name'] or e['company']['code'])[:18]
        br = (e['branch']['name'] or e['branch']['code'])[:14]
        C.out(f"   {co:<18} {br:<14} {e['branch']['id']:<38} "
              f"{len(e['terminal_records']):>5} {len(e['open_shifts']):>4} "
              f"{str(e['physical_checkout_count']):>9} {e['confidence']:>8}  "
              f"{'YES' if e['operator_input_required'] else 'no'}")
    C.out("")
    C.out("PER-BRANCH EVIDENCE:")
    for e in evidence:
        b = e["branch"]
        C.out(f"  ── {e['company']['name']} / {b['name']} ({b['code']})  [{b['id']}]")
        C.out(f"     source={e['detection_source']}  checkouts={e['physical_checkout_count']}  "
              f"confidence={e['confidence']}  input_required={e['operator_input_required']}")
        C.out(f"     terminal_records={len(e['terminal_records'])}  shift_terminal_evidence="
              f"{len(e['shift_terminal_evidence'])}  historical_shifts={e['historical_shift_count']}  "
              f"cashiers={e['distinct_cashiers']}  concurrent_multi_cashier={e['concurrent_multi_cashier']}")
        for t in e["terminal_records"]:
            C.out(f"        terminal: id={t['id']} name={t['name']} active={t['is_active']} device={t['device_uuid']}")
        for s in e["open_shifts"]:
            C.out(f"        OPEN shift {s['shift_id']}  cashier={s['cashier_id']}  terminal={s['terminal_id']}")
        if e["operator_input_required"]:
            C.out(f"     >>> SAVOL: '{b['name']}' ({b['code']}) filialida NECHTA fizik kassa/yashik (drawer) bor?")


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.tools.cash_discover",
                                description="Read-only physical-checkout discovery + operator mapping skeleton.")
    p.add_argument("--company-id", default=None, help="Faqat shu tenant (UUID).")
    p.add_argument("--branch-id", action="append", default=None,
                   help="Aniq branch (UUID) — takrorlash mumkin. Berilса --all/ambiguous filtri e'tiborsiz.")
    p.add_argument("--all", action="store_true", help="Barcha branch (default: faqat AMBIGUOUS).")
    p.add_argument("--skeleton", action="store_true", default=True,
                   help="Mapping JSON skeleton chiqarish (default: ha).")
    p.add_argument("--no-skeleton", dest="skeleton", action="store_false")
    p.add_argument("--json", action="store_true", help="To'liq natijani JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
        branch_ids = [_uuid.UUID(b) for b in (args.branch_id or [])]
    except ValueError as e:
        C.err(f"XATO: noto'g'ri UUID: {e}")
        return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id, branch_ids, only_ambiguous=not args.all,
                   as_json=args.json, emit_skeleton=args.skeleton)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
