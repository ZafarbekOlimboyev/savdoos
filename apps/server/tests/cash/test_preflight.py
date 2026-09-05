# -*- coding: utf-8 -*-
"""Production migration PREFLIGHT / runbook tooling testlari (real PostgreSQL).

Gate mantiq + state machine + read-only kafolat. Barcha gate operator dalilини tekshiradi yoki mavjud
Phase 0/1/2/3 read-only asboblarni orkestrlaydi — HECH NARSA YOZMAYDI (backfill execute alohida qadam).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.cash.migration import backfill, phase0, preflight as pf
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry
from app.models.enums import CashMovementType, ShiftStatus
from app.models.shifts import CashMovement, Shift
from app.services.cash import mode

from tests.cash.test_compare_phase3 import _fresh, _inject, _open


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


# ═══ §2 GIT RELEASE / deployment mismatch ════════════════════════════════════
def test_git_release_gate():
    assert pf.git_release_gate({"working_tree_clean": False, "tested_commit": "a",
                                "deployed_commit": "a", "remote_synced": True})["ok"] is False   # dirty
    assert pf.git_release_gate({"working_tree_clean": True, "tested_commit": "a",
                                "deployed_commit": "b", "remote_synced": True})["ok"] is False   # mismatch
    assert pf.git_release_gate({"working_tree_clean": True, "tested_commit": "a",
                                "deployed_commit": "a", "remote_synced": False})["ok"] is False  # not synced
    assert pf.git_release_gate({"working_tree_clean": True, "tested_commit": "a",
                                "deployed_commit": "a", "remote_synced": True})["ok"] is True


# ═══ §3 BACKUP / restore rehearsal ═══════════════════════════════════════════
def test_backup_gate():
    assert pf.backup_gate(None)["ok"] is False                                   # yo'q
    base = {"snapshot_ref": "s", "taken_at": "t", "operator": "o", "checksum": "c"}
    assert pf.backup_gate({**base, "restore_rehearsed": False, "verified": True})["ok"] is False   # rehearsal yo'q
    assert pf.backup_gate({**base, "restore_rehearsed": True, "verified": False})["ok"] is False   # verified yo'q
    assert pf.backup_gate({**base, "restore_rehearsed": True, "verified": True})["ok"] is True


# ═══ §5 MULTI-CASHIER / TILL decision (A/B/C) ════════════════════════════════
def test_till_mapping_decision_A(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    _open(db, emp, 100000)
    assert pf.till_mapping_decision(db, co.id)["ok"] is True    # A -> valid


def _two_concurrent_cashiers(db, cashenv, terminals=(None, None)):
    from app.models.org import Terminal
    co, br, emp, till = _fresh(db, cashenv)
    role = db.query(Role).first()
    empB = Employee(company_id=co.id, full_name="KB", role_id=role.id); db.add(empB); db.flush()
    db.add(EmployeeBranch(employee_id=empB.id, branch_id=br.id)); db.flush()
    t = cashenv.now
    tids = []
    for term in terminals:
        if term is not None:
            tm = Terminal(branch_id=br.id, name=term); db.add(tm); db.flush(); tids.append(tm.id)
        else:
            tids.append(None)
    db.add(Shift(branch_id=br.id, cashier_id=emp.id, terminal_id=tids[0],
                 opened_at=t - timedelta(hours=1), closed_at=None, opening_cash=Decimal("0"), status=ShiftStatus.open))
    db.add(Shift(branch_id=br.id, cashier_id=empB.id, terminal_id=tids[1],
                 opened_at=t - timedelta(minutes=30), closed_at=None, opening_cash=Decimal("0"), status=ShiftStatus.open))
    db.commit()
    return co, br


def test_till_mapping_decision_C_blocks(db, cashenv):
    co, br = _two_concurrent_cashiers(db, cashenv, terminals=(None, None))   # konkurrent, terminal NULL
    g = pf.till_mapping_decision(db, co.id)
    assert g["ok"] is False and g["action"] == "STOP" and g["finding"]["finding"] == "C"


def test_till_mapping_decision_B_needs_provisioning(db, cashenv):
    co, br = _two_concurrent_cashiers(db, cashenv, terminals=("T1", "T2"))   # konkurrent, turli terminal
    assert pf.till_mapping_decision(db, co.id, terminal_till_provisioned=False)["ok"] is False   # STOP
    assert pf.till_mapping_decision(db, co.id, terminal_till_provisioned=True)["ok"] is True      # provisioned -> OK


# ═══ §6 T0 selection ═════════════════════════════════════════════════════════
def test_t0_record():
    assert pf.t0_record(t0_utc="2026-01-01T00:00:00+00:00")["ok"] is False   # maydonlar yetishmaydi
    full = dict(t0_utc="2026-01-01T00:00:00+00:00", local_tz="Asia/Tashkent", approved_by="op",
                git_sha="abc", backup_id="bk1", run_id="r1")
    assert pf.t0_record(**full)["ok"] is True


# ═══ §4/§7/§9 backfill integration (historical < T0) ═════════════════════════
def _historical_tenant(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    t0 = cashenv.now
    # counted_cash O'RNATILGAN (opening 100000 + payin 5000) -> CLOSED_SHIFT_UNCOUNTED REVIEW yo'q -> toza GO
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=t0 - timedelta(hours=4),
               closed_at=t0 - timedelta(hours=3), opening_cash=Decimal("100000"),
               counted_cash=Decimal("105000"), status=ShiftStatus.closed); db.add(sh); db.flush()
    db.add(CashMovement(shift_id=sh.id, type=CashMovementType.payin, amount=Decimal("5000"),
                        reason="hist", created_at=t0 - timedelta(hours=3, minutes=30))); db.commit()
    return co, br, emp, till, t0


def test_final_dry_run_blocks_unacked_plan_review(db, cashenv):
    # §19 fix: PLAN-level REVIEW (CLOSED_SHIFT_UNCOUNTED — counted_cash yo'q) endi GO'ни bloklaydi (ack talab)
    co, br, emp, till = _fresh(db, cashenv)
    t0 = cashenv.now
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=t0 - timedelta(hours=4),
               closed_at=t0 - timedelta(hours=3), opening_cash=Decimal("100000"),
               status=ShiftStatus.closed); db.add(sh); db.flush()   # counted_cash=None -> REVIEW
    db.add(CashMovement(shift_id=sh.id, type=CashMovementType.payin, amount=Decimal("5000"),
                        created_at=t0 - timedelta(hours=3, minutes=30))); db.commit()
    g = pf.final_dry_run(db, cashenv.engine, company_id=co.id, t0=t0.isoformat())
    assert g["ok"] is False and g["manifest"]["go_no_go"] == "NO-GO"        # ack qilinmagan REVIEW
    assert g["manifest"]["unacknowledged_reviews"] >= 1 and g["manifest"]["open_reviews"]
    # operator open_reviews'ni ack qiladi -> GO
    g2 = pf.final_dry_run(db, cashenv.engine, company_id=co.id, t0=t0.isoformat(),
                          acknowledged_reviews=g["manifest"]["open_reviews"])
    assert g2["ok"] is True and g2["manifest"]["go_no_go"] == "GO"


def test_discovery_read_only(db, cashenv):
    co, br, emp, till, t0 = _historical_tenant(db, cashenv)
    n0 = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count()
    g = pf.discovery(db, cashenv.engine, co.id)
    assert "inventory" in g and "readiness" in g and "multi_cashier" in g
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count() == n0   # yozuv yo'q


def test_final_dry_run_go_and_read_only(db, cashenv):
    co, br, emp, till, t0 = _historical_tenant(db, cashenv)
    n0 = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count()
    g = pf.final_dry_run(db, cashenv.engine, company_id=co.id, t0=t0.isoformat(),
                         git_sha="abc", backup_id="bk1", run_id="r1")
    assert g["ok"] is True and g["manifest"]["go_no_go"] == "GO"
    assert g["manifest"]["manifest_hash"] and g["manifest"]["blocked_rows"] == 0
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count() == n0   # dry-run YOZMADI


def test_post_backfill_verification_pass_and_fail(db, cashenv):
    co, br, emp, till, t0 = _historical_tenant(db, cashenv)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True, t0=t0.isoformat())   # HAQIQIY (test DB)
    assert m["go_no_go"] == "GO" and m["inserted_rows"] >= 1
    g = pf.post_backfill_verification(db, m, company_id=co.id, t0=t0.isoformat())
    assert g["ok"] is True and all(g["mandatory"].values())
    # buzuq qator kiritamiz -> verify FAIL -> STOP
    _inject(db, co, till, br, source_type="CASH_OP", source_id=uuid.uuid4(), provenance="RECONSTRUCTION",
            device_occurred_at=t0 - timedelta(hours=2))
    g2 = pf.post_backfill_verification(db, m, company_id=co.id, t0=t0.isoformat())
    assert g2["ok"] is False   # non-deterministik/qo'shimcha qator -> majburiy shart buzildi


def test_review_id_distinct_per_leg():
    # §19-rereview fix: KONSTANT reason + ALOHIDA plan_id -> ALOHIDA ack id (over-broad ack yo'q)
    const = "account aniqlanmadi (multi-branch; explicit/shadow/employee yo'q) — operator"
    assert pf._review_id({"plan_id": "p1", "reason": const}) == "p1"
    assert pf._review_id({"plan_id": "p2", "reason": const}) == "p2"        # bir xil reason, farqli id
    assert pf._review_id({"plan_id": "p1", "reason": const}) != pf._review_id({"plan_id": "p2", "reason": const})
    # plan-level Finding ref bilan ajraladi; source-review source bilan
    assert pf._review_id({"code": "C", "ref": "shifts:x"}) != pf._review_id({"code": "C", "ref": "shifts:y"})
    # §19-rereview-2 fix: bir xil source, FARQLI reason (out-of-window vs negative) -> FARQLI id
    assert pf._review_id({"source": "cash_movements:M", "reason": "oynadan tashqarida"}) != \
           pf._review_id({"source": "cash_movements:M", "reason": "running balance MANFIY"})


def test_no_ge_t0_check_global_company_none(db, cashenv):
    # §19-rereview fix: company_id=None (global) -> >= T0 RECONSTRUCTION leg baribir USHLANADI
    # (ilgari `tenant_id == None` -> IS NULL -> 0 qator -> yolg'on PASS edi).
    co, br, emp, till, t0 = _historical_tenant(db, cashenv)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True, t0=t0.isoformat())
    _inject(db, co, till, br, source_type="CASH_OP", source_id=uuid.uuid4(), provenance="RECONSTRUCTION",
            device_occurred_at=t0 + timedelta(hours=1))   # >= T0
    g = pf.post_backfill_verification(db, m, company_id=None, t0=t0.isoformat())
    assert g["mandatory"]["no_ge_t0_backfilled"] is False


def test_post_backfill_ge_t0_rows_blocked(db, cashenv):
    # §19 fix: >= T0 RECONSTRUCTION leg (noto'g'ri hudud) -> no_ge_t0_backfilled FAIL -> STOP
    co, br, emp, till, t0 = _historical_tenant(db, cashenv)
    m = backfill.execute_backfill(db, company_id=co.id, apply=True, t0=t0.isoformat())
    assert pf.post_backfill_verification(db, m, company_id=co.id, t0=t0.isoformat())["mandatory"]["no_ge_t0_backfilled"] is True
    _inject(db, co, till, br, source_type="CASH_OP", source_id=uuid.uuid4(), provenance="RECONSTRUCTION",
            device_occurred_at=t0 + timedelta(hours=1))   # >= T0 -> historical hududдан tashqari
    g = pf.post_backfill_verification(db, m, company_id=co.id, t0=t0.isoformat())
    assert g["mandatory"]["no_ge_t0_backfilled"] is False and g["ok"] is False


# ═══ §10 DUAL_WRITE_SHADOW enable preconditions ══════════════════════════════
def test_dual_write_enable_requires_backfill_verified(db, cashenv):
    assert pf.dual_write_enable_gate(db, backfill_verified=False)["ok"] is False   # verify yo'q -> STOP
    g = pf.dual_write_enable_gate(db, backfill_verified=True, deployed_git_sha="a", expected_git_sha="a")
    assert g["ok"] is True and g["target_mode"] == "DUAL_WRITE_SHADOW"
    # SHA mos emas -> STOP
    assert pf.dual_write_enable_gate(db, backfill_verified=True, deployed_git_sha="a", expected_git_sha="b")["ok"] is False
    # §19 fix: SHA BERILMAGAN -> BLOCK (versiya tasdig'i yo'q -> stale deploy xavfi)
    assert pf.dual_write_enable_gate(db, backfill_verified=True)["ok"] is False
    assert any("SHA" in b for b in pf.dual_write_enable_gate(db, backfill_verified=True)["blocking"])


def test_dual_write_enable_blocks_ledger_primary(db, cashenv):
    mode.set_mode("LEDGER_PRIMARY")   # test override (bu task YOQMAYDI — faqat guard tekshiruvi)
    g = pf.dual_write_enable_gate(db, backfill_verified=True)
    assert g["ok"] is False and any("LEDGER_PRIMARY" in b for b in g["blocking"])


def test_ledger_primary_prohibited_gate(db, cashenv):
    assert pf.assert_ledger_primary_prohibited()["ok"] is True    # default SHADOW
    mode.set_mode("LEDGER_PRIMARY")
    assert pf.assert_ledger_primary_prohibited()["ok"] is False   # yoqilган -> taqiqlangan


# ═══ §11-12 observation + readiness ══════════════════════════════════════════
def test_observation_cycle_read_only(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    from tests.cash.test_compare_phase3 import _mv, _T0
    _mv(db, emp, sid, "payin", 5000)
    n0 = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count()
    cyc = pf.observation_cycle(db, company_id=co.id, t0=_T0(cashenv), run_id="obs1")
    assert cyc["clean"] is True and "PHASE-3 COMPARE RUN" in cyc["operator_report"]
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count() == n0


def test_cutover_readiness_gate_ready_and_insufficient(db, cashenv):
    from tests.cash.test_compare_phase3 import _mv, _T0
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000); _mv(db, emp, sid, "payin", 5000)
    # yetarli toza sikl -> READY
    g = pf.cutover_readiness_gate(db, company_id=co.id, t0=_T0(cashenv), completed_clean_cycles=14)
    assert g["ok"] is True and g["readiness"]["readiness"] == "READY"
    # yetarli emas -> NOT_READY
    g0 = pf.cutover_readiness_gate(db, company_id=co.id, t0=_T0(cashenv), completed_clean_cycles=0)
    assert g0["ok"] is False and "INSUFFICIENT_OBSERVATION_CYCLES" in g0["blocking"]


def test_cutover_readiness_gate_mismatch_blocks(db, cashenv):
    from tests.cash.test_compare_phase3 import _T0
    co, br, emp, till = _fresh(db, cashenv)
    _open(db, emp, 100000)
    _inject(db, co, till, br, source_type="CASH_OP", source_id=uuid.uuid4())   # EXTRA leg
    g = pf.cutover_readiness_gate(db, company_id=co.id, t0=_T0(cashenv), completed_clean_cycles=14)
    assert g["ok"] is False and "EXTRA_LEDGER" in g["blocking"]


# ═══ §14 1C import guard ═════════════════════════════════════════════════════
def test_import_1c_guard():
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert pf.import_1c_guard(t0 - timedelta(days=1), t0)["ok"] is True     # < T0 historical OK
    g = pf.import_1c_guard(t0 + timedelta(seconds=1), t0)                   # >= T0 -> block/REVIEW
    assert g["ok"] is False and g["action"] == "REVIEW"


# ═══ §13 STATE MACHINE / rollback ════════════════════════════════════════════
def test_state_machine_enforces_sequence():
    st = pf.RunbookState()
    # skip -> rad
    assert st.advance("BACKUP_VERIFIED", {"ok": True})["ok"] is False and st.stage == "INIT"
    # ketma-ket -> ok
    assert st.advance("RELEASE_IDENTITY", {"ok": True})["ok"] is True and st.stage == "RELEASE_IDENTITY"
    # gate FAIL -> o'tmaydi
    assert st.advance("BACKUP_VERIFIED", {"ok": False, "blocking": ["x"]})["ok"] is False
    assert st.stage == "RELEASE_IDENTITY"
    # dual-write'ga sakrash -> rad (backfill verify'siz)
    assert st.advance("DUAL_WRITE_ENABLED", {"ok": True})["ok"] is False
    # ABORTED istalgan paytda
    assert st.advance(pf.ABORTED, {"ok": True})["action"] == "ABORT" and st.stage == pf.ABORTED
    assert st.advance("BACKUP_VERIFIED", {"ok": True})["ok"] is False   # abortdan keyin oldinga yo'q


def test_full_sequence_reaches_cutover_ready():
    st = pf.RunbookState()
    for stage in pf.STAGES:
        r = st.advance(stage, {"ok": True})
        assert r["ok"] is True, (stage, r)
    assert st.stage == "CUTOVER_READY"


def test_rollback_matrix_no_destructive_ledger():
    m = pf.rollback_matrix()
    assert all(k in m for k in ("A_pre_backfill", "B_during_backfill", "C_after_backfill_before_dual_write",
                                "D_dual_write_observation", "E_comparison_anomaly"))
    joined = " ".join(str(v) for v in m.values())
    assert "DELETE" in joined and "EMAS" in joined      # DELETE oddiy rollback EMAS deb aytilgan
    assert "append-only" in joined.lower() or "APPEND-ONLY" in joined


# ═══ §12 stability policy configurable ═══════════════════════════════════════
def test_stability_policy_configurable():
    p = pf.stability_policy()
    assert p["minimum_clean_cycles"] == 14 and p["maximum_unexplained_delta"] == 0.0
    assert p["require_operator_approval"] is True
    p2 = pf.stability_policy(minimum_clean_cycles=30)
    assert p2["minimum_clean_cycles"] == 30    # sozlanadigan (hard-code emas)


# ═══ §15 alerts ══════════════════════════════════════════════════════════════
def test_alerts_from_run():
    clean = {"absolute_delta": 0.0, "mismatch_counts": {}, "duplicate_conflict_count": 0,
             "exceptions": {"open_total": 0}, "scope": "tenant"}
    assert pf.alerts_from_run(clean) == []
    bad = {"absolute_delta": 500.0, "mismatch_counts": {"MISSING_LEDGER": 2, "EXTRA_LEDGER": 1},
           "duplicate_conflict_count": 0, "exceptions": {"open_total": 3}, "scope": "tenant"}
    codes = {a["code"] for a in pf.alerts_from_run(bad)}
    assert {"UNEXPLAINED_DELTA", "MISSING_LEDGER", "EXTRA_LEDGER", "UNRESOLVED_LEDGER_EXCEPTION"} <= codes
