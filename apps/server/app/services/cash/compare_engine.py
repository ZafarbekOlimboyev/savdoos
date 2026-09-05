# -*- coding: utf-8 -*-
"""Cash Ledger — Migration Phase 3 COMPARE / RECONCILIATION engine (FAQAT O'QISH, auto-repair YO'Q).

Ikki MUSTAQIL buxgalteriya yuzasini uzluksiz solishtiradi (cutover'ni O'ZI HAL QILMAYDI):
  A. LEGACY physical cash  — legacy source jadvallaridan (phase1 event-derivatsiyasi + shadow_compare).
  B. LEDGER physical cash   — cash_ledger_entries (NORMAL=dual-write; RECONSTRUCTION=backfill).

Bir taraf IKKINCHISIDAN OLINMAYDI (tautologiya emas): kutilган hodisalar legacy manbadан
(phase1.plan_backfill deterministik biznes-kalitlari), haqiqiy leg'lar ledger'дан.

QAT'IY: bu modul HECH NARSA yozmaydi — ledger insert yo'q, legacy o'zgartirmaydi, reconciliation
tegmaydi, exception acknowledge qilmaydi, mode o'zgartirmaydi, mismatch REPAIR qilmaydi. Netting bilan
offsetting mismatch YASHIRILMAYDI. EXPLAINED delta ko'rinadi, UNEXPLAINED bloklaydi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.cash.migration import phase1
from app.models.cash import CashAccount, CashLedgerEntry, CashLedgerException
from app.models.org import Branch
from app.models.shifts import CashMovement, Shift
from app.services.cash import repositories as repo
from app.services.cash import shadow_compare as sc

ALGO_VERSION = "phase3-compare-1.0"
_Z = Decimal("0")
_TOL = Decimal("0.005")

# Event-level mismatch toifalari (§03)
MISSING_LEDGER = "MISSING_LEDGER"
EXTRA_LEDGER = "EXTRA_LEDGER"
WRONG_AMOUNT = "WRONG_AMOUNT"
WRONG_DIRECTION = "WRONG_DIRECTION"
WRONG_CATEGORY = "WRONG_CATEGORY"
WRONG_ACCOUNT = "WRONG_ACCOUNT"
WRONG_BRANCH = "WRONG_BRANCH"
WRONG_SHIFT = "WRONG_SHIFT"
WRONG_POSTING_KIND = "WRONG_POSTING_KIND"
WRONG_TIMESTAMP = "WRONG_TIMESTAMP"
DUPLICATE_BUSINESS_KEY = "DUPLICATE_BUSINESS_KEY"
SHADOW_DOUBLE_COUNT = "SHADOW_DOUBLE_COUNT"
TENANT_MISMATCH = "TENANT_MISMATCH"
UNEXPECTED_RECONSTRUCTION = "UNEXPECTED_RECONSTRUCTION"
UNEXPECTED_NORMAL_POST = "UNEXPECTED_NORMAL_POST"


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _ts(iso):
    return phase1._parse_ts(iso) if isinstance(iso, str) else phase1._aware(iso)


def _t0_dt(t0):
    """t0 (datetime YOKI ISO-string) -> aware datetime (shadow_compare uchun). None -> None."""
    if t0 is None:
        return None
    return phase1._parse_ts(t0) if isinstance(t0, str) else phase1._aware(t0)


def _t0_iso(t0):
    """t0 (datetime YOKI ISO-string) -> ISO string (phase1.plan_backfill uchun). None -> None."""
    if t0 is None:
        return None
    return t0 if isinstance(t0, str) else t0.isoformat()


# ═══ Soya aniqlash (shadow_compare bilan izchil (type,prefiks)) ═══════════════
def _is_shadow_movement(db: Session, source_id) -> bool:
    mv = db.get(CashMovement, source_id)
    if mv is None or mv.client_uuid is not None:
        return False
    mt = mv.type.value if hasattr(mv.type, "value") else str(mv.type)
    return phase1._is_shadow(mt, mv.reason, mv.client_uuid)


# ═══ §03 field-level klassifikatsiya (unit-testable) ═════════════════════════
def compare_leg(exp: dict, act, *, expected_account_id=None, t0dt=None) -> list:
    """Kutilган leg (phase1 dict) vs haqiqiy ledger qatori -> mismatch kodlari ro'yxati. FAQAT
    deterministik maydonlar solishtiriladi. expected_account_id berilса WRONG_ACCOUNT tekshiriladi."""
    out = []
    if _D(exp["amount"]) != _D(act.amount):
        out.append(WRONG_AMOUNT)
    if exp["direction"] != act.direction:
        out.append(WRONG_DIRECTION)
    if exp["category"] != act.category:
        out.append(WRONG_CATEGORY)
    if exp.get("branch_id") and str(exp["branch_id"]) != str(act.branch_id):
        out.append(WRONG_BRANCH)
    if expected_account_id is not None and str(expected_account_id) != str(act.cash_account_id):
        out.append(WRONG_ACCOUNT)
    # smena: kutilган ON_SHIFT + aniq shift bo'lса, haqiqiy shift mos kelsin
    if exp.get("posting_kind") == "ON_SHIFT" and exp.get("shift_id"):
        if str(exp["shift_id"]) != str(act.shift_id):
            out.append(WRONG_SHIFT)
    # WRONG_POSTING_KIND — LEKIN LATE_SYNC (offline-first live konstrukt) legitim: expected-side
    # derivatsiyasi uni modellamaydi -> LATE_SYNC'да yolg'on mismatch bermaymiz (§20 dismissed topilma).
    if (exp.get("posting_kind") and act.posting_kind and act.posting_kind != "LATE_SYNC"
            and exp["posting_kind"] != act.posting_kind):
        out.append(WRONG_POSTING_KIND)
    # live hodisa RECONSTRUCTION bilan tiklangan bo'lsa -> UNEXPECTED_RECONSTRUCTION
    if act.provenance != "NORMAL":
        out.append(UNEXPECTED_RECONSTRUCTION)
    # vaqt T0 ustidan siljigan bo'lsa (live hodisa lekin leg < T0)
    if t0dt is not None and act.device_occurred_at is not None and _ts(act.device_occurred_at.isoformat()) < t0dt:
        out.append(WRONG_TIMESTAMP)
    return out


# ═══ §03 EVENT-LEVEL RECONCILIATION ENGINE ═══════════════════════════════════
def reconcile_events(db: Session, company_id, *, t0) -> dict:
    """Kutilган LIVE hodisalar (legacy manba, >= T0) vs haqiqiy ledger leg'lar. Har mismatch operator
    trace uchun yetarli manba ma'lumotини o'z ichiga oladi. AUTO-REPAIR YO'Q.

    T0 MAJBURIY (§20 topilma): Phase-3 tabiатан T0 chegarasiga tayanadi (historical < T0 -> RECONSTRUCTION,
    live >= T0 -> NORMAL). t0=None bo'lса phase1 HAMMANI tarixiy deydi (`legs`), shu bois t0=None'ni
    "hammasi live" deb olish backfill leg'larни UNEXPECTED_RECONSTRUCTION deb belgилар VA hist bo'sh
    bo'lганi uchun UNEXPECTED_NORMAL_POST (double-post) tekshiruvини O'LDIRARDI (anomaliyани YASHIRARди).
    Shu bois t0 ANIQ berilishi SHART — noaniqlik jimgina noto'g'ri natija bermasin (fail loud)."""
    if t0 is None:
        raise ValueError("Phase-3 reconcile T0 chegarasini TALAB qiladi (historical < T0 / live >= T0). "
                         "Fresh tenant (backfill'siz) uchun ham T0 (masalan tenant boshlanishi) bering.")
    plan = phase1.plan_backfill(db, company_id=company_id, t0=_t0_iso(t0))
    live = plan.get("legs_after_t0", [])
    hist = plan.get("legs", [])
    t0dt = _t0_dt(t0)

    live_by_key, hist_by_key = {}, {}
    dup_expected = []
    for l in live:
        k = (str(l["tenant_id"]), l["source_type"], str(l["source_id"]), l["leg_index"])
        if k in live_by_key:
            dup_expected.append(k)
        live_by_key[k] = l
    for l in hist:
        hist_by_key[(str(l["tenant_id"]), l["source_type"], str(l["source_id"]), l["leg_index"])] = l

    # haqiqiy ledger leg'lar (HAR PROVENANCE — UNEXPECTED_* aniqlash uchun). PERF (§15): tenant bo'yicha
    # bir marta yuklanadi (bounded scope = tenant; window uchun aggregate shadow_compare(t0) ishlating).
    q = select(CashLedgerEntry).where(CashLedgerEntry.tenant_id == company_id)
    rows = db.execute(q).scalars().all()
    till_by_branch = {}   # branch -> TILL id cache (WRONG_ACCOUNT uchun)
    # PERF (§15): cross-tenant tekshiruvi uchun tenant hisoblarини BIR SO'ROVда oldindan yuklaymiz (N+1 emas).
    # Cross-tenant leg DDL FK (cle_acct_currency_fk) bilan DB'да imkonsiz — bu defense-in-depth, O(1)/qator.
    own_account_ids = {a for (a,) in db.execute(select(CashAccount.id).where(
        CashAccount.tenant_id == company_id)).all()}

    def _exp_account(l):
        b = l.get("branch_id")
        if not b:
            return None
        if b not in till_by_branch:
            acc = repo.find_account(db, company_id, uuid.UUID(str(b)), "TILL")
            till_by_branch[b] = acc.id if acc else None
        return till_by_branch[b]

    mismatches, matched = [], 0
    seen_keys = set()
    for r in rows:
        key = (str(r.tenant_id), r.source_type, str(r.source_id), r.leg_index)
        if key in seen_keys:
            mismatches.append(_mm(DUPLICATE_BUSINESS_KEY, key, r=r))
        seen_keys.add(key)
        # cross-tenant (account tenant != leg tenant) — O(1) preloaded set (DDL FK undan kuchliroq)
        if r.cash_account_id not in own_account_ids:
            mismatches.append(_mm(TENANT_MISMATCH, key, r=r,
                                  detail=f"account {r.cash_account_id} tenant {company_id}'ники EMAS"))
        if r.provenance == "NORMAL":
            exp = live_by_key.get(key)
            if exp is not None:
                errs = compare_leg(exp, r, expected_account_id=_exp_account(exp), t0dt=t0dt)
                if errs:
                    mismatches.append(_mm("+".join(errs), key, exp=exp, r=r))
                else:
                    matched += 1
            elif key in hist_by_key:
                mismatches.append(_mm(UNEXPECTED_NORMAL_POST, key, r=r,
                                      detail="tarixiy (< T0) hodisa live dual-write qilingan"))
            elif r.source_type == "CASH_OP" and _is_shadow_movement(db, r.source_id):
                mismatches.append(_mm(SHADOW_DOUBLE_COUNT, key, r=r,
                                      detail="soya CashMovement CASH_OP leg sifatida yozilgan"))
            else:
                mismatches.append(_mm(EXTRA_LEDGER, key, r=r, detail="legacy manba yo'q"))
        else:  # RECONSTRUCTION
            if key in live_by_key:
                mismatches.append(_mm(UNEXPECTED_RECONSTRUCTION, key, r=r,
                                      detail="live (>= T0) hodisa backfill qilingan"))
            # RECONSTRUCTION tarixiy hodisa uchun KUTILGAN — mismatch emas

    # MISSING: kutilган live, lekin NORMAL leg yo'q
    normal_keys = {(str(r.tenant_id), r.source_type, str(r.source_id), r.leg_index)
                   for r in rows if r.provenance == "NORMAL"}
    for key, exp in live_by_key.items():
        if key not in normal_keys:
            mismatches.append(_mm(MISSING_LEDGER, key, exp=exp))
    for k in dup_expected:
        mismatches.append(_mm(DUPLICATE_BUSINESS_KEY, k, detail="kutilган hodisalarда takror biznes-kalit"))

    counts: dict = {}
    for m in mismatches:
        for code in m["code"].split("+"):
            counts[code] = counts.get(code, 0) + 1
    return {"matched": matched, "mismatch_total": len(mismatches),
            "mismatch_counts": counts, "mismatches": mismatches[:200],
            "mismatch_truncated": max(0, len(mismatches) - 200)}


def _mm(code, key, *, exp=None, r=None, detail=None) -> dict:
    m = {"code": code, "business_key": {"tenant_id": key[0], "source_type": key[1],
                                        "source_id": key[2], "leg_index": key[3]}}
    if exp is not None:
        m["expected"] = {"amount": exp.get("amount"), "direction": exp.get("direction"),
                         "category": exp.get("category"), "source_ref": (exp.get("reconstruction") or {}).get("source_ref")}
    if r is not None:
        m["actual"] = {"amount": float(r.amount), "direction": r.direction, "category": r.category,
                       "cash_account_id": str(r.cash_account_id), "shift_id": str(r.shift_id) if r.shift_id else None,
                       "posting_kind": r.posting_kind, "provenance": r.provenance,
                       "entry_id": str(r.id)}
    if detail:
        m["detail"] = detail
    return m


# ═══ §06 EXCEPTION-AWARE ═════════════════════════════════════════════════════
def _exception_summary(db: Session, company_id) -> dict:
    q = select(CashLedgerException.kind, CashLedgerException.state, func.count(CashLedgerException.id)).where(
        CashLedgerException.tenant_id == company_id).group_by(
        CashLedgerException.kind, CashLedgerException.state)
    by_kind, open_total = {}, 0
    for kind, state, n in db.execute(q).all():
        by_kind.setdefault(str(kind), {})[str(state)] = int(n)
        if str(state) == "OPEN":
            open_total += int(n)
    return {"open_total": open_total, "by_kind": by_kind}


def _posting_kind_counts(db: Session, company_id) -> dict:
    q = select(CashLedgerEntry.posting_kind, func.count(CashLedgerEntry.id)).where(
        CashLedgerEntry.tenant_id == company_id, CashLedgerEntry.provenance == "NORMAL").group_by(
        CashLedgerEntry.posting_kind)
    d = {str(k): int(n) for k, n in db.execute(q).all()}
    return {"off_shift": d.get("OFF_SHIFT", 0), "late_sync": d.get("LATE_SYNC", 0),
            "on_shift": d.get("ON_SHIFT", 0)}


# ═══ §08 COMPARISON RUN model (deterministik, READ-ONLY) ═════════════════════
def compare_run(db: Session, *, company_id, t0, scope="tenant", run_id=None,
                started_at=None, completed_at=None, git_version=None) -> dict:
    """Bitta deterministik solishtirish yugurishi: aggregate (shadow_compare) + event-level
    (reconcile_events) + exceptions. FAQAT O'QISH — hech narsa yozmaydi/tuzatmaydi. T0 MAJBURIY (§20)."""
    if t0 is None:
        raise ValueError("Phase-3 compare_run T0 chegarasini TALAB qiladi (reconcile_events'ga qarang).")
    agg = sc.compare_tenant(db, company_id, t0=_t0_dt(t0))
    ev = reconcile_events(db, company_id, t0=t0)
    exc = _exception_summary(db, company_id)
    pk = _posting_kind_counts(db, company_id)
    # unexplained = event-level mismatch soni (monetar). explained = OFF_SHIFT/exception (ko'rinadi).
    unexplained = ev["mismatch_total"]
    abs_delta = _D(agg.get("abs_delta", 0))
    status = "MATCH"
    if agg.get("status") == "BLOCK" or ev["mismatch_counts"].get(TENANT_MISMATCH):
        status = "BLOCK"
    elif unexplained > 0 or abs_delta > _TOL or agg.get("status") != "MATCH" or exc["open_total"] > 0:
        status = "REVIEW"
    return {
        "kind": "PHASE3_COMPARE_RUN", "run_id": run_id or "run", "algo_version": ALGO_VERSION,
        "git_version": git_version, "scope": scope, "t0": (t0.isoformat() if hasattr(t0, "isoformat") else t0),
        "started_at": (started_at.isoformat() if hasattr(started_at, "isoformat") else started_at),
        "completed_at": (completed_at.isoformat() if hasattr(completed_at, "isoformat") else completed_at),
        "legacy_in": agg["legacy_in"], "legacy_out": agg["legacy_out"], "legacy_expected": agg["legacy_expected"],
        "ledger_in": agg["ledger_in"], "ledger_out": agg["ledger_out"], "ledger_expected": agg["ledger_expected"],
        "signed_delta": agg["delta"], "absolute_delta": float(abs_delta),
        "unexplained_delta_events": unexplained,
        "divergent_tills": agg.get("divergent_part_count", 0),
        "matched_events": ev["matched"], "mismatch_total": ev["mismatch_total"],
        "mismatch_counts": ev["mismatch_counts"],
        "off_shift_count": pk["off_shift"], "late_sync_count": pk["late_sync"],
        "duplicate_conflict_count": ev["mismatch_counts"].get(DUPLICATE_BUSINESS_KEY, 0),
        "exceptions": exc, "status": status,
        "top_mismatches": ev["mismatches"][:20],
        "aggregate": agg,
        "note": "READ-ONLY. Netting YO'Q (abs). EXPLAINED (off-shift/exception) ko'rinadi, "
                "UNEXPLAINED (event mismatch) bloklaydi. Auto-repair YO'Q.",
    }


# ═══ §16 OPERATOR REPORT (matn) ══════════════════════════════════════════════
def operator_report(run: dict) -> str:
    mc = run["mismatch_counts"]
    lines = [
        "═══ CASH LEDGER · PHASE-3 COMPARE RUN ═══",
        f"run_id: {run['run_id']}   algo: {run['algo_version']}   git: {run.get('git_version')}",
        f"scope: {run['scope']}   T0: {run['t0']}   window: [{run.get('started_at')} .. {run.get('completed_at')}]",
        "",
        f"legacy_expected: {run['legacy_expected']:>16}",
        f"ledger_expected: {run['ledger_expected']:>16}",
        f"signed_delta:    {run['signed_delta']:>16}",
        f"absolute_delta:  {run['absolute_delta']:>16}",
        f"unexplained (event mismatches): {run['unexplained_delta_events']}",
        "",
        f"MATCHED EVENTS:  {run['matched_events']}",
        f"MISSING LEDGER:  {mc.get(MISSING_LEDGER, 0)}    EXTRA LEDGER: {mc.get(EXTRA_LEDGER, 0)}",
        f"WRONG AMOUNT:    {mc.get(WRONG_AMOUNT, 0)}    WRONG SHIFT: {mc.get(WRONG_SHIFT, 0)}    "
        f"WRONG TILL: {mc.get(WRONG_ACCOUNT, 0)}    WRONG CATEGORY: {mc.get(WRONG_CATEGORY, 0)}",
        f"DUPLICATES:      {run['duplicate_conflict_count']}    SHADOW_DOUBLE_COUNT: {mc.get(SHADOW_DOUBLE_COUNT, 0)}    "
        f"TENANT_MISMATCH: {mc.get(TENANT_MISMATCH, 0)}",
        f"UNEXPECTED_RECON: {mc.get(UNEXPECTED_RECONSTRUCTION, 0)}    UNEXPECTED_NORMAL: {mc.get(UNEXPECTED_NORMAL_POST, 0)}",
        "",
        f"OFF_SHIFT: {run['off_shift_count']}    LATE_SYNC: {run['late_sync_count']}    "
        f"EXCEPTIONS(open): {run['exceptions']['open_total']}    divergent_tills: {run['divergent_tills']}",
        "",
        f"STATUS: {run['status']}",
    ]
    if run["top_mismatches"]:
        lines.append("\nTOP MISMATCHES:")
        for m in run["top_mismatches"][:10]:
            bk = m["business_key"]
            ref = (m.get("expected") or {}).get("source_ref") or (m.get("actual") or {}).get("entry_id")
            lines.append(f"  [{m['code']}] {bk['source_type']}:{bk['source_id']}#{bk['leg_index']}  "
                         f"{m.get('detail', '')}  ref={ref}")
    return "\n".join(lines)


# ═══ §09/§17 STABILITY WINDOW + CUTOVER READINESS EVALUATOR (READ-ONLY) ══════
DEFAULT_READINESS_CRITERIA = {
    "required_clean_cycles": 14,     # sozlanadigan — operator siyosati alohida (§09); duration TAXMIN QILINMAYDI
    "max_unexplained_delta": 0.0,
    "max_open_critical_exceptions": 0,
}


def evaluate_cutover_readiness(db: Session, *, company_id, t0=None, run=None,
                               completed_clean_cycles=0, criteria=None,
                               backfill_complete=True, multi_till_blocker=False) -> dict:
    """READ-ONLY: cutover TAYYORmi? READY / NOT_READY + mashina-o'qiladigan sabablar. MODE O'ZGARTIRMAYDI,
    LEDGER_PRIMARY O'RNATMAYDI. Cutover QARORINI O'ZI QABUL QILMAYDI — faqat mezonlarni baholaydi."""
    crit = {**DEFAULT_READINESS_CRITERIA, **(criteria or {})}
    if run is None:
        if t0 is None:
            raise ValueError("evaluate_cutover_readiness: `run` yoki `t0` berilishi SHART (compare_run T0 talab qiladi).")
        run = compare_run(db, company_id=company_id, t0=t0)
    reasons = []
    mc = run["mismatch_counts"]
    if run["unexplained_delta_events"] > 0:
        reasons.append({"code": "UNEXPLAINED_MISMATCH", "count": run["unexplained_delta_events"]})
    if abs(run["absolute_delta"]) > crit["max_unexplained_delta"] + _TOL.__float__():
        reasons.append({"code": "NONZERO_ABSOLUTE_DELTA", "value": run["absolute_delta"]})
    for code in (MISSING_LEDGER, EXTRA_LEDGER, DUPLICATE_BUSINESS_KEY, TENANT_MISMATCH,
                 SHADOW_DOUBLE_COUNT, UNEXPECTED_RECONSTRUCTION, UNEXPECTED_NORMAL_POST):
        if mc.get(code):
            reasons.append({"code": code, "count": mc[code]})
    if run["exceptions"]["open_total"] > crit["max_open_critical_exceptions"]:
        reasons.append({"code": "OPEN_EXCEPTIONS", "count": run["exceptions"]["open_total"]})
    if not backfill_complete:
        reasons.append({"code": "INCOMPLETE_BACKFILL"})
    if multi_till_blocker:
        reasons.append({"code": "MULTI_TILL_MAPPING_BLOCKER"})
    if completed_clean_cycles < crit["required_clean_cycles"]:
        reasons.append({"code": "INSUFFICIENT_OBSERVATION_CYCLES",
                        "have": completed_clean_cycles, "need": crit["required_clean_cycles"]})
    # CATCH-ALL (§20 dismissed topilma himoyasi): run MATCH bo'lmasa -> NOT_READY. Aggregate BLOCK
    # (masalan orphan/structural) aniq sabab bermаса ham, MATCH bo'lмаган run cutover'ni bloklaydi.
    if run["status"] != "MATCH":
        reasons.append({"code": "RUN_NOT_MATCH", "run_status": run["status"]})
    readiness = "READY" if not reasons else "NOT_READY"
    return {"kind": "PHASE3_CUTOVER_READINESS", "readiness": readiness, "reasons": reasons,
            "criteria": crit, "run_status": run["status"], "t0": run["t0"],
            "note": "READ-ONLY EVALUATOR. Mode O'ZGARTIRMAYDI, LEDGER_PRIMARY O'RNATMAYDI. "
                    "Operator observation-duration siyosati ALOHIDA (§09)."}


# ═══ §10 MULTI-CASHIER / ONE-TILL arxitektura topilmasi (READ-ONLY tahlil) ═══
def multi_cashier_till_finding(db: Session, company_id=None) -> dict:
    """Repository-first: legacy bir filialда ko'p kassir smenasiga ruxsat beradi; cash sxema TILL'ga
    BITTA ochiq smena. Har filial uchun: turli kassir + turli terminal_id bormi? -> A/B/C topilma."""
    bq = select(Branch.id, Branch.company_id).where(Branch.deleted_at.is_(None), Branch.is_active.is_(True))
    if company_id is not None:
        bq = bq.where(Branch.company_id == company_id)
    from datetime import datetime as _dt, timezone as _tz
    _FAR = _dt(9999, 1, 1, tzinfo=_tz.utc)
    branches = db.execute(bq).all()
    per_branch, needs_terminal_till, ambiguous = [], 0, 0
    for bid, cid in branches:
        rows = db.execute(select(Shift.cashier_id, Shift.terminal_id, Shift.opened_at, Shift.closed_at)
                          .where(Shift.branch_id == bid)).all()
        # §20 topilma: FAQAT KONKURRENT (bir vaqtда ochiq) turli-kassir smenalari mapping'ni buzadi;
        # ketma-ket (sequential) ko'p kassir cash sxema uchun OK (bir vaqtда bitta ochiq). Oyna kesishishini
        # aniqlaymiz (sweep). closed_at NULL (ochiq) -> uzoq kelajak.
        shifts = sorted([(o, (c or _FAR), cash, term) for cash, term, o, c in rows if o is not None],
                        key=lambda x: x[0])
        concurrent = False
        conc_distinct_term = True
        conc_null_term = False
        active = []   # (closed, cashier, terminal)
        for opened, closed, cashier, terminal in shifts:
            active = [a for a in active if a[0] > opened]
            for aclosed, acashier, aterm in active:
                if acashier != cashier:
                    concurrent = True
                    if terminal is None or aterm is None:
                        conc_null_term = True
                    if terminal == aterm:
                        conc_distinct_term = False
            active.append((closed, cashier, terminal))
        rec = {"branch_id": str(bid), "distinct_cashiers": len({c for _, _, c, _ in shifts}),
               "concurrent_multi_cashier": concurrent}
        if concurrent and conc_distinct_term and not conc_null_term:
            rec["assessment"] = "TERMINAL_DISTINGUISHES"    # konkurrent, turli terminal -> TILL/terminal
            needs_terminal_till += 1
        elif concurrent:
            rec["assessment"] = "AMBIGUOUS"                  # konkurrent, terminal ajratmaydi -> prod data
            ambiguous += 1
        else:
            rec["assessment"] = "SEQUENTIAL_OR_SINGLE_OK"    # konkurrentlik yo'q -> mapping VALID
        per_branch.append(rec)
    if ambiguous > 0:
        finding = "C"   # production data required to decide (shared drawer? terminal null?)
        summary = ("ko'p filialda ko'p kassir bor lekin terminal_id drawer'ni ANIQ ajratmaydi "
                   "(null yoki bitta terminal) -> haqiqiy jismoniy drawer sonini PRODUCTION DATA aniqlaydi.")
    elif needs_terminal_till > 0:
        finding = "B"   # mapping needs additional TILL provisioning (per terminal)
        summary = ("filial(lar)да turli terminal_id bilan ko'p kassir -> har terminal = alohida jismoniy "
                   "drawer ehtimoli; mapping QO'SHIMCHA TILL provisioning talab qiladi (1 terminal = 1 TILL).")
    else:
        finding = "A"   # current mapping valid (<=1 concurrent cashier per branch)
        summary = "har filialда <=1 kassir -> joriy 1-filial=1-TILL mapping VALID."
    return {"kind": "PHASE3_MULTI_CASHIER_FINDING", "finding": finding, "summary": summary,
            "branches_analyzed": len(per_branch), "needs_terminal_till": needs_terminal_till,
            "ambiguous_branches": ambiguous, "per_branch": per_branch[:100],
            "cutover_impact": ("BLOCKS cutover readiness (Phase-3 tooling readiness ALOHIDA)"
                               if finding != "A" else "no cutover blocker"),
            "note": "Ratifikatsiya qilinган sxema AVTOMATIK O'ZGARTIRILMAYDI (§10). Bu READ-ONLY topilma."}


# ═══ §11 1C historical import siyosati (deterministik klassifikatsiya) ═══════
def import_1c_policy() -> dict:
    """reports.py 1C tarixiy sotuv importi: sold_at O'TMISHда, shift_id yo'q -> TARIXIY (backfill hududи),
    LIVE dual-write EMAS. Import endpoint HECH QANDAY retrofit hook chaqirmaydi (on_cash_sale yo'q) ->
    NORMAL ledger cash yaratmaydi (test bilan pinlangan). Cutover siyosati: import < T0 -> Phase-1
    backfill; import >= T0 (bo'lmasligi kerak — importlar tarixiy) -> operator BLOCK/qayta ko'rish."""
    return {"kind": "PHASE3_1C_IMPORT_POLICY",
            "classification": "HISTORICAL_BACKFILL_TERRITORY",
            "live_dual_write": False,
            "rule": "Import endpoint (reports.py) HECH QACHON dual-write hook chaqirmaydi -> NORMAL leg yo'q. "
                    "sold_at bo'yicha: < T0 -> Phase-1 backfill; >= T0 -> operator qaror (tarixiy import "
                    "live cash EMAS). Regressiya testi: import NORMAL leg yaratmaydi.",
            "operator_guard": "dual-write davomida eski cash sotuv importi TASODIFAN NORMAL live ledger "
                              "cash YARATMAYDI (hook yo'q); wiring qo'shilса — sold_at>=T0 bloklanishi kerak."}
