# -*- coding: utf-8 -*-
"""Cash Ledger — PRODUCTION MIGRATION PREFLIGHT & STATE MACHINE (FAQAT O'QISH / GATE mantiq).

REAL production migratsiyasi uchun operator-runbook toolingi. Bu modul:
  * HECH NARSA YOZMAYDI (ledger insert yo'q, mode o'zgartirmaydi, backup olmaydi). Faqat operator bergan
    dalilni (evidence) tekshiradi va mavjud Phase 0/1/2/3 read-only asboblarni ORKESTRLAYDI.
  * KETMA-KETLIKNI MAJBURLAYDI (state machine): bosqichni O'TKAZIB YUBORIB bo'lmaydi — masalan backfill
    TEKSHIRILMASDAN dual-write yoqib bo'lmaydi.
  * LEDGER_PRIMARY'ни HECH QACHON yoqmaydi/tavsiya qilmaydi (cutover keyingi faza, operator qarori).
  * BLOCK/STOP dalili bo'lmasa — TO'XTATADI (fail loud).

Haqiqiy YOZUV (backfill execute, mode set) ALOHIDA operator qadamlari — bu modulda EMAS. Preflight faqat
ularning OLDIDAGI/KEYINGI GATE'larni baholaydi. Ko'r: PRODUCTION_CASH_MIGRATION_RUNBOOK.md.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.cash.migration import phase0, phase1
from app.services.cash import compare_engine as ce
from app.services.cash import mode as _mode

RUNBOOK_VERSION = "prod-migration-runbook-1.0"

# ═══ STATE MACHINE (bosqich ketma-ketligi majburiy) ══════════════════════════
STAGES = [
    "RELEASE_IDENTITY",     # §2 git working tree clean + deployed==tested commit + synced
    "BACKUP_VERIFIED",      # §3 backup + restore rehearsal verified
    "DISCOVERY_DONE",       # §4 read-only discovery, no blockers
    "TILL_MAPPING_DECIDED",  # §5 multi-cashier A (or B resolved); C -> STOP
    "T0_SELECTED",          # §6 operator T0 recorded
    "DRY_RUN_APPROVED",     # §7 final dry-run BLOCK=0 + REVIEW acked + manifest hash approved
    "BACKFILL_EXECUTED",    # §8 execute_backfill(apply=True) == approved manifest
    "BACKFILL_VERIFIED",    # §9 verify_backfill + reconcile all-zero
    "DUAL_WRITE_ENABLED",   # §10 preconditions ok; DUAL_WRITE_SHADOW yoqildi
    "OBSERVING",            # §11-12 N clean observation cycles
    "CUTOVER_READY",        # readiness READY (Phase 4 gate — cutover'ni O'ZI QILMAYDI)
]
ABORTED = "ABORTED"


def _gate(name, ok, *, action=None, blocking=None, detail=None, **extra) -> dict:
    return {"gate": name, "ok": bool(ok),
            "action": action or ("PROCEED" if ok else "STOP"),
            "blocking": list(blocking or []), "detail": detail, **extra}


def _review_id(r: dict) -> str:
    """REVIEW uchun BARQAROR + AJRALGAN ack id. §19-rereview topilma: execute-level leg-review'lar
    KONSTANT `reason` matniga ega (masalan account-resolution) -> N ta ALOHIDA leg bir xil id'ga
    yig'ilib, bitta ack hammasini o'chirardi. Shu bois AVVAL `plan_id` (har leg uchun NOYOB) ishlatiladi;
    keyin ref/source; oxirida code:scope:reason kompoziti. Plan-level Finding'lar ref/code bilan ajraladi."""
    if r.get("plan_id"):
        return str(r["plan_id"])
    if r.get("ref"):
        return str(r["ref"])
    if r.get("source"):
        # §19-rereview-2 topilma: BITTA leg (bir xil source_ref) HAM out-of-window HAM negative-balance
        # review berishi mumkin (ikkalasi source-keyed, plan_id yo'q) -> reason'ni ham qo'shamiz, aks holда
        # bitta ack ikkalasini o'chirib, ko'rilmagan manfiy-balans shartини jimgina GO'ga o'tkazardi.
        return f"{r['source']}::{r.get('reason', '')}"
    return "|".join(str(r.get(k)) for k in ("code", "scope", "reason") if r.get(k)) or str(r)[:60]


@dataclass
class RunbookState:
    """Migratsiya yugurishining joriy bosqichi + dalillar. advance() KETMA-KETLIKNI majburlaydi."""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stage: str = "INIT"
    history: list = field(default_factory=list)

    def _idx(self, s):
        return STAGES.index(s) if s in STAGES else -1

    def advance(self, target: str, gate: dict) -> dict:
        """target bosqichга o'tishга URINISH. Faqat: (a) KEYINGI bosqich (skip yo'q) VA (b) gate ok ->
        ruxsat. ABORTED istalgan paytда. Aks holда rad (o'tmaydi)."""
        if target == ABORTED:
            self.stage = ABORTED
            self.history.append(("ABORTED", gate))
            return _gate("advance", True, action="ABORT", detail="migratsiya to'xtatildi")
        if self.stage == ABORTED:
            return _gate("advance", False, blocking=["ABORTED holatдан oldinga yurib bo'lmaydi"])
        cur = self._idx(self.stage) if self.stage != "INIT" else -1
        tgt = self._idx(target)
        if tgt != cur + 1:
            return _gate("advance", False, blocking=[
                f"bosqichni O'TKAZIB bo'lmaydi: {self.stage} -> {target} (kutilган: {STAGES[cur+1] if cur+1 < len(STAGES) else 'YO`Q'})"])
        if not gate.get("ok"):
            return _gate("advance", False, blocking=[f"{target} gate O'TMADI: {gate.get('blocking')}"])
        self.stage = target
        self.history.append((target, gate))
        return _gate("advance", True, detail=f"-> {target}")


# ═══ §2 RELEASE IDENTITY / GIT SAFETY ════════════════════════════════════════
def capture_git_state(repo_dir: str | None = None) -> dict:
    """LOCAL git holatini o'qiydi (operator/dry-run uchun; production evidence emas). HEAD SHA, ishchi
    daraxt toza-mi, upstream bilan sync. subprocess — hech narsa o'zgartirmaydi."""
    def _run(*args):
        try:
            return subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True,
                                  timeout=15).stdout.strip()
        except Exception as e:
            return f"<err:{e}>"
    head = _run("rev-parse", "HEAD")
    porcelain = _run("status", "--porcelain")
    ahead = _run("rev-list", "--count", "@{u}..HEAD")
    behind = _run("rev-list", "--count", "HEAD..@{u}")
    return {"head": head, "clean": porcelain == "", "dirty_files": [l for l in porcelain.splitlines() if l],
            "ahead": ahead, "behind": behind}


def git_release_gate(evidence: dict) -> dict:
    """§2: production DEPLOY aynan TASDIQLANGAN commitdan bo'lishini isbotlaydi. Operator dalili:
    {working_tree_clean, tested_commit, deployed_commit, remote_synced}. Barchasi bo'lса PROCEED."""
    b = []
    if not evidence.get("working_tree_clean"):
        b.append("ishchi daraxt TOZA emas (noma'lum local state)")
    tc, dc = evidence.get("tested_commit"), evidence.get("deployed_commit")
    if not tc or not dc:
        b.append("tested_commit / deployed_commit yozilmagan")
    elif tc != dc:
        b.append(f"deployed_commit ({dc}) != tested_commit ({tc}) — noma'lum kod")
    if evidence.get("remote_synced") is not True:
        b.append("remote bilan sync tasdiqlanmagan")
    return _gate("git_release", not b, blocking=b,
                 detail="release tag TAVSIYA etiladi (masalan cash-migration-<sha>); migration run git SHA'ga bog'lanadi")


# ═══ §3 BACKUP GATE (phase0.verify_backup o'rami) ════════════════════════════
def backup_gate(backup_manifest: dict | None) -> dict:
    """§3: backup + RESTORE REHEARSAL tasdiqlangan bo'lishi SHART (backup borligi YETARLI EMAS —
    restore ISHLASHI isbotlansin). Aks holда STOP."""
    r = phase0.verify_backup(backup_manifest)
    return _gate("backup", r["ok"], blocking=([] if r["ok"] else [r["reason"]]),
                 detail="backup OLINMAYDI — operator bergan manifest tekshiriladi; restore_rehearsed+verified SHART")


# ═══ §4 READ-ONLY DISCOVERY ══════════════════════════════════════════════════
def discovery(db: Session, engine: Engine, company_id=None) -> dict:
    """§4: production READ-ONLY kashfiyot — inventory + readiness (PG ver/rollar/imtiyoz/search_path) +
    multi-cashier + shadow reconcile + T0-boundary tayyorlik. HECH QANDAY YOZUV YO'Q."""
    inv = phase0.inventory(db, company_id)
    rc = phase0.readiness_check(engine)
    mappings, map_find = phase0.propose_till_mapping(db, company_id)
    recon = [f.as_dict() for f in phase1.reconcile_shadows(db, company_id)]
    mc = ce.multi_cashier_till_finding(db, company_id)
    blockers = [f.as_dict() for f in map_find if f.as_dict()["severity"] == phase0.BLOCK]
    ok = rc.get("ok") in (True, None) and not blockers and mc["finding"] != "C"
    return _gate("discovery", ok,
                 blocking=([b["message"] for b in blockers] + (["multi-cashier finding C (drawer identity noaniq)"] if mc["finding"] == "C" else [])),
                 detail="read-only", inventory=inv, readiness=rc,
                 till_mappings=[m.__dict__ if hasattr(m, "__dict__") else m for m in mappings],
                 shadow_reconcile=recon, multi_cashier=mc)


# ═══ §5 MULTI-CASHIER / TILL PRODUCTION DECISION ═════════════════════════════
def till_mapping_decision(db: Session, company_id=None, *, terminal_till_provisioned=False) -> dict:
    """§5: A -> current mapping valid; B -> per-terminal TILL provisioning KERAK (provisioned bo'lса
    PROCEED); C -> BLOCK (STOP). one-branch=one-TILL production data KO'RMASDAN majburan olinmaydi."""
    mc = ce.multi_cashier_till_finding(db, company_id)
    f = mc["finding"]
    if f == "A":
        return _gate("till_mapping", True, detail="A: sequential/single -> mapping VALID", finding=mc)
    if f == "B":
        return _gate("till_mapping", terminal_till_provisioned,
                     blocking=([] if terminal_till_provisioned else ["B: per-terminal TILL provisioning kerak (1 terminal = 1 TILL)"]),
                     detail="B: terminal drawer'ni ajratadi", finding=mc)
    return _gate("till_mapping", False, action="STOP",
                 blocking=["C: jismoniy drawer identity DETERMINISTIK emas -> production data kerak; MIGRATION STOP"],
                 finding=mc)


# ═══ §6 T0 SELECTION (operator qaror; struktura + validatsiya) ═══════════════
_T0_REQUIRED = ("t0_utc", "local_tz", "approved_by", "git_sha", "backup_id", "run_id")


def t0_record(**fields) -> dict:
    """§6: operator tanlagan T0'ни STRUKTURALAYDI + majburiy maydonlarni tekshiradi. T0'ни O'ZI
    TANLAMAYDI. Boundary QAT'IY: < T0 -> RECONSTRUCTION, >= T0 -> NORMAL/live."""
    missing = [k for k in _T0_REQUIRED if not fields.get(k)]
    ok = not missing
    return _gate("t0_record", ok, blocking=([f"T0 maydonlari yetishmaydi: {missing}"] if missing else []),
                 detail="ideal T0: low-traffic, barcha TILL smena YOPIQ, offline pending tekshirilgan, "
                        "import to'xtatilgan, backup verified, operatorlar tayyor",
                 record={k: fields.get(k) for k in _T0_REQUIRED})


# ═══ §7 FINAL PRODUCTION DRY-RUN (READ-ONLY; execute_backfill apply=False) ═══
def final_dry_run(db: Session, engine: Engine, *, company_id, t0: str, git_sha=None, backup_id=None,
                  run_id=None, acknowledged_reviews=None) -> dict:
    """§7: haqiqiy yozuvdан OLDIN read-only manifest. GO faqat BLOCK=0 (readiness ok). REVIEW'lar
    operator tomonidan EXPLICIT ack qilinishi (acknowledged_reviews) yoki migrationдан chiqarilishi kerak."""
    from app.db.cash.migration import backfill
    rc = phase0.readiness_check(engine)
    m = backfill.execute_backfill(db, company_id=company_id, t0=t0, apply=False)   # YOZUV YO'Q
    # §19 topilma (MAJOR): execute-level `review` (account/straddle/negative) + PLAN-level REVIEW'lar
    # (RECONCILE_*_SHADOW / CLOSED_SHIFT_UNCOUNTED / NEG_COUNTED_CASH / MANUAL_PAYOUT_REVIEW — phase0/1)
    # HAR IKKALASI ack qilinishi SHART. Ilgari faqat execute-level tekshirilib, plan-level REVIEW'lar
    # jimgina GO'ga o'tardi (runbook §7 va'dasiga zid). Endi plan reja-review'lar ham qamraladi.
    plan = phase1.plan_backfill(db, company_id=company_id, t0=t0)
    all_reviews = [{**r, "review_id": _review_id(r)} for r in (plan.get("review_rows", []) + m.get("review", []))]
    acked = set(acknowledged_reviews or [])
    unacked = [r for r in all_reviews if r["review_id"] not in acked]
    block = m.get("blocked", [])
    go = (m.get("go_no_go") == "GO" and len(block) == 0 and (rc.get("ok") in (True, None)))
    manifest = {
        "kind": "PRODUCTION_DRY_RUN_MANIFEST", "run_id": run_id or m.get("run_id"),
        "git_sha": git_sha, "backup_id": backup_id, "t0": t0, "tenant_scope": str(company_id),
        "candidate_rows": m.get("candidate_rows"), "in_total": m.get("in_total"), "out_total": m.get("out_total"),
        "reconstructed_rows": m.get("reconstructed_rows"), "skipped_shadow_rows": m.get("skipped_shadow_rows"),
        "review_rows": len(all_reviews), "blocked_rows": m.get("blocked_rows"),
        "duplicate_conflicts": len(m.get("duplicate_conflicts", []) if isinstance(m.get("duplicate_conflicts"), list) else []),
        "manifest_hash": m.get("manifest_hash"), "readiness_ok": rc.get("ok"),
        "unacknowledged_reviews": len(unacked),
        "open_reviews": [r["review_id"] for r in unacked][:50],
        "go_no_go": "GO" if go and not unacked else "NO-GO",
    }
    blocking = []
    if len(block) > 0:
        blocking.append(f"BLOCK rows = {len(block)} (0 bo'lishi SHART)")
    if rc.get("ok") is False:
        blocking.append("readiness_check FAIL")
    if unacked:
        blocking.append(f"tasdiqlanmagan REVIEW = {len(unacked)} (operator ack yoki scope'дан chiqarsin)")
    return _gate("final_dry_run", not blocking and go, blocking=blocking,
                 detail="approved manifest_hash keyingi haqiqiy backfill bilan AYNAN mos kelishi kerak",
                 manifest=manifest)


# ═══ §9 POST-BACKFILL VERIFICATION (READ-ONLY) ═══════════════════════════════
def post_backfill_verification(db: Session, executed_manifest: dict, *, company_id, t0: str) -> dict:
    """§9: dual-write YOQILISHIDАN OLDIN majburiy. verify_backfill + reconcile_backfill — barcha
    majburiy shart NOL bo'lishi kerak. Aks holда DUAL_WRITE_SHADOW yoqilmasin (STOP)."""
    from sqlalchemy import func, select

    from app.db.cash.migration import backfill
    from app.models.cash import CashLedgerEntry
    v = backfill.verify_backfill(db, executed_manifest, company_id=company_id)
    r = backfill.reconcile_backfill(db, company_id=company_id, t0=t0)
    # §19 topilma: runbook majburiy ro'yxatidagi "no >= T0 rows backfilled" tekshiruvи — RECONSTRUCTION leg
    # FAQAT < T0 bo'lishi kerak (planner shuni majburlaydi; bu explicit defense-in-depth).
    t0dt = ce._t0_dt(t0)
    # §19-rereview topilma: tenant filtri SHARTLI (verify_backfill/reconcile_backfill bilan izchil) —
    # company_id=None (global run) bo'lса BARCHA tenant skanerlansin, aks holда `tenant_id == None` ->
    # SQL `IS NULL` -> 0 qator -> yolg'on PASS (>= T0 leg sizib ketardi).
    geq = select(func.count(CashLedgerEntry.id)).where(
        CashLedgerEntry.provenance == "RECONSTRUCTION", CashLedgerEntry.device_occurred_at >= t0dt)
    if company_id is not None:
        geq = geq.where(CashLedgerEntry.tenant_id == company_id)
    ge_t0 = db.execute(geq).scalar() or 0
    mandatory = {
        "no_duplicate_business_keys": v.get("no_duplicate_business_keys"),
        "tenant_isolation": v.get("tenant_isolation"),
        "no_shadow_leg_leaked": v.get("no_shadow_leg_leaked"),
        "deterministic_ids": v.get("deterministic_ids"),
        "row_count_matches": v.get("row_count_matches"),
        "in_total_matches": v.get("in_total_matches"),
        "out_total_matches": v.get("out_total_matches"),
        "all_reconstruction_metadata": v.get("all_reconstruction_metadata"),
        "no_ge_t0_backfilled": int(ge_t0) == 0,
        "unexplained_delta_zero": abs(float(r.get("unexplained_delta", 1))) < 0.005,
    }
    failed = [k for k, ok in mandatory.items() if not ok]
    return _gate("post_backfill_verification", not failed, blocking=failed,
                 detail="hammasi PASS bo'lmasa DUAL_WRITE_SHADOW YOQILMAYDI", verify=v, reconcile=r,
                 mandatory=mandatory)


# ═══ §10 ENABLE DUAL_WRITE_SHADOW preconditions (READ-ONLY tekshiruv) ════════
def dual_write_enable_gate(db: Session, *, backfill_verified: bool, deployed_git_sha=None,
                           expected_git_sha=None) -> dict:
    """§10: DUAL_WRITE_SHADOW xavfsiz yoqilishidан OLDIN. backfill VERIFIED bo'lishi SHART; hozirgi
    mode LEDGER_PRIMARY EMAS; ledger_is_authority()==False; deploy SHA mos. Mode'ni O'ZI YOQMAYDI —
    faqat precondition tasdiqlaydi (yoqish alohida operator config qadami)."""
    b = []
    if not backfill_verified:
        b.append("backfill hali VERIFIED emas -> dual-write yoqib bo'lmaydi (§09 gate)")
    try:
        cur = _mode.cash_mode()
    except Exception as e:
        cur = None
        b.append(f"cash_mode() xato ({e}) — LEDGER_PRIMARY guard ishga tushdi (config'ni tekshiring)")
    if cur == _mode.CashMode.LEDGER_PRIMARY:
        b.append("mode allaqачон LEDGER_PRIMARY — bu Phase 2/3'да TAQIQLANGAN")
    if _mode.ledger_is_authority():
        b.append("ledger_is_authority()==True — SHADOW rejimда bo'lmasligi kerak")
    # §19 topilma: versiya dalili YO'Q bo'lса ham BLOCK (git_release_gate kabi — yo'q SHA = hard blocker).
    # Aks holда §2'дан keyingi redeploy stale kod ustidа dual-write yoqib yuborardi.
    if not expected_git_sha or not deployed_git_sha:
        b.append("deployed/expected git SHA berilmagan — deploy versiya tasdig'i yo'q (§2 RELEASE_IDENTITY SHA'sini bering)")
    elif expected_git_sha != deployed_git_sha:
        b.append(f"deploy SHA ({deployed_git_sha}) != kutilган ({expected_git_sha})")
    return _gate("dual_write_enable", not b, blocking=b,
                 detail="target = DUAL_WRITE_SHADOW (LEDGER_PRIMARY EMAS). Yoqgach: smoke event -> legacy "
                        "mutation + AYNAN 1 NORMAL leg -> compare delta 0. Fail -> config revert.",
                 target_mode="DUAL_WRITE_SHADOW")


# ═══ §11-12 OBSERVATION CYCLE + STABILITY POLICY ═════════════════════════════
CONSERVATIVE_STABILITY_POLICY = {
    "minimum_clean_cycles": 14,             # sozlanadigan — operator approval SHART
    "minimum_completed_shift_cycles": 14,
    "maximum_unexplained_delta": 0.0,
    "maximum_missing_events": 0,
    "maximum_extra_events": 0,
    "maximum_duplicates": 0,
    "require_operator_approval": True,
}


def stability_policy(**overrides) -> dict:
    """§12: sozlanadigan barqarorlik siyosati (hard-code EMAS). Konservativ default TAVSIYA, lekin
    operator approval talab qilinadi (duration operator qarori)."""
    p = {**CONSERVATIVE_STABILITY_POLICY, **overrides}
    p["note"] = ("TAVSIYA (konservativ): >=14 to'liq shift-close sikl barcha faol filiallarда nol "
                 "unexplained delta bilan + operator sign-off. DURATION operator siyosati.")
    return p


def observation_cycle(db: Session, *, company_id, t0, run_id=None, git_version=None) -> dict:
    """§11: bitta observation sikl — compare_run + reconcile + readiness snapshot. READ-ONLY —
    accounting data MUTATSIYA QILINMAYDI (faqat natija report/persist qilinadi tashqarida)."""
    run = ce.compare_run(db, company_id=company_id, t0=t0, run_id=run_id, git_version=git_version)
    alerts = alerts_from_run(run)
    return {"kind": "OBSERVATION_CYCLE", "run": run, "operator_report": ce.operator_report(run),
            "alerts": alerts, "clean": run["status"] == "MATCH" and not alerts}


# ═══ §11 CUTOVER READINESS GATE (evaluate_cutover_readiness o'rami) ══════════
def cutover_readiness_gate(db: Session, *, company_id, t0, completed_clean_cycles,
                           criteria=None, backfill_complete=True, multi_till_blocker=False) -> dict:
    r = ce.evaluate_cutover_readiness(db, company_id=company_id, t0=t0,
                                      completed_clean_cycles=completed_clean_cycles,
                                      criteria=criteria, backfill_complete=backfill_complete,
                                      multi_till_blocker=multi_till_blocker)
    return _gate("cutover_readiness", r["readiness"] == "READY",
                 blocking=[x["code"] for x in r["reasons"]], detail="READ-ONLY; LEDGER_PRIMARY O'RNATMAYDI",
                 readiness=r)


# ═══ §14 1C IMPORT PRODUCTION GUARD ══════════════════════════════════════════
def import_1c_guard(sold_at, t0dt, *, mode=None) -> dict:
    """§14: dual-write vaqtида 1C import. sold_at < T0 -> historical (backfill hududi, OK jim import).
    sold_at >= T0 -> jim QABUL QILINMASIN (operator qarori) — tasodifan NORMAL live cash yaratmasin."""
    from app.services.cash.compare_engine import _t0_dt
    s = _t0_dt(sold_at) if not hasattr(sold_at, "tzinfo") else sold_at
    t = _t0_dt(t0dt)
    if s is None or t is None:
        return _gate("import_1c", False, blocking=["sold_at yoki T0 yo'q"])
    if s < t:
        return _gate("import_1c", True, detail="sold_at < T0 -> historical (Phase-1 backfill hududi)")
    return _gate("import_1c", False, action="REVIEW",
                 blocking=[f"sold_at ({s.isoformat()}) >= T0 -> jim import TAQIQLANADI; operator qaror qilsin"],
                 detail="dual-write vaqtida >=T0 import NORMAL live cash yaratmasin")


# ═══ §15 ALERTS ══════════════════════════════════════════════════════════════
def alerts_from_run(run: dict) -> list:
    """§15: compare_run natijasidан alert shartlari. AUTO-REPAIR YO'Q — faqat operator action."""
    mc = run.get("mismatch_counts", {})
    out = []

    def _a(cond, code, severity, ref=None):
        if cond:
            out.append({"code": code, "severity": severity, "scope": run.get("scope"),
                        "source_reference": ref, "detected_at": run.get("completed_at") or run.get("started_at"),
                        "operator_action": "manual investigate (auto-repair YO'Q)"})
    _a(abs(run.get("absolute_delta", 0)) > 0.005, "UNEXPLAINED_DELTA", "critical")
    _a(mc.get(ce.MISSING_LEDGER), "MISSING_LEDGER", "critical")
    _a(mc.get(ce.EXTRA_LEDGER), "EXTRA_LEDGER", "critical")
    _a(run.get("duplicate_conflict_count"), "DUPLICATE_BUSINESS_KEY", "critical")
    _a(mc.get(ce.TENANT_MISMATCH), "CROSS_TENANT", "critical")
    _a(mc.get(ce.UNEXPECTED_RECONSTRUCTION), "UNEXPECTED_RECONSTRUCTION_GE_T0", "critical")
    _a(mc.get(ce.UNEXPECTED_NORMAL_POST), "UNEXPECTED_NORMAL_LT_T0", "critical")
    _a(run.get("exceptions", {}).get("open_total"), "UNRESOLVED_LEDGER_EXCEPTION", "major")
    return out


# ═══ §13 ROLLBACK / ABORT MATRIX (data; DESTRUCTIVE ledger mutation YO'Q) ═════
def rollback_matrix() -> dict:
    """§13: har bosqich uchun abort protsedurasi. Backfill APPEND-ONLY+IMMUTABLE -> "DELETE migrated
    rows" ODDIY rollback EMAS. Legacy AVTORITET saqlanadi (LEDGER_PRIMARY yoqilmagani uchun POS davom etadi)."""
    return {
        "kind": "ROLLBACK_ABORT_MATRIX",
        "A_pre_backfill": "hech qanday ledger yozuv yo'q -> shunchaki TO'XTA (config/state INIT).",
        "B_during_backfill": "execution STOP (idempotent+resume-safe). Yozilган RECONSTRUCTION leg'lar "
                             "IMMUTABLE -> o'chirilMAYDI; keyin manifest bilan davom yoki reversal-migration.",
        "C_after_backfill_before_dual_write": "DUAL_WRITE_SHADOW YOQILMAGAN -> legacy avtoritet, ledger soya "
                                              "qoladi. Anomaliya bo'lса: manifest identify + reversal/corrective "
                                              "ALOHIDA APPROVED migration (destructive DELETE EMAS).",
        "D_dual_write_observation": "mode -> LEGACY_ONLY revert (config) -> ledger yozilishi to'xtaydi; "
                                    "legacy hech qachon avtoritetdан chiqmagan -> POS buzilmaydi.",
        "E_comparison_anomaly": "cutover BLOCK; observation davom; auto-repair YO'Q; ildiz sabab operator "
                                "tomonidan hал qilinadi; kerak bo'lса reversal-migration alohida approval.",
        "invariant": "Backfill immutable/append-only. Recovery = execution stop + manifest identify + "
                     "(kerak bo'lса) approved reversal-migration. Legacy AVTORITET, LEDGER_PRIMARY yoqilmagan.",
    }


# ═══ Ledger-primary TAQIQI (himoya) ══════════════════════════════════════════
def assert_ledger_primary_prohibited() -> dict:
    """Har bir bosqichда: mode LEDGER_PRIMARY EMASligini tasdiqlaydi. Bu task/faza LEDGER_PRIMARY'ni
    YOQMAYDI — agar env bilan yoqilган bo'lса cash_mode() XATO beradi (guard)."""
    try:
        cur = _mode.cash_mode()
        prohibited = cur == _mode.CashMode.LEDGER_PRIMARY
    except Exception:
        prohibited = False   # cash_mode() xato -> LEDGER_PRIMARY guard ishladi (yoqilmagan)
    return _gate("ledger_primary_prohibited", not prohibited,
                 blocking=(["LEDGER_PRIMARY yoqilган — Phase 2/3/preflight'да TAQIQLANGAN"] if prohibited else []),
                 detail="cutover (LEDGER_PRIMARY) keyingi faza — operator qarori, bu tooling yoqmaydi")
