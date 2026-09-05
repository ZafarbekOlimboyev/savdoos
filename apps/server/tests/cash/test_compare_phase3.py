# -*- coding: utf-8 -*-
"""Migration Phase 3 — COMPARE / RECONCILIATION testlari (real PostgreSQL).

Event-level matcher, run model, cutover readiness evaluator, false-match qarshiligi, T0 mikrosekund
chegarasi, multi-cashier + 1C topilmalari, read-only kafolat, konkurrentlik/konvergensiya, tenant izolyatsiya.
FRESH tenant ishlatiladi (shared-DB kontaminatsiyasidan toza reconcile natijasi).
"""
from __future__ import annotations

import types
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert as _pg

from app.api.v1 import shifts as shifts_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry
from app.models.enums import CashMovementType
from app.models.org import Branch, Company
from app.models.shifts import CashMovement, Shift
from app.services.cash import compare_engine as ce
from app.services.cash import mode


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _fresh(db, cashenv):
    """Yangi TENANT (company) + branch + emp(EmployeeBranch) + TILL — toza reconcile uchun."""
    co = Company(name="P3" + _hex(), code="p3" + _hex(), currency="UZS"); db.add(co); db.flush()
    role = db.query(Role).first()
    emp = Employee(company_id=co.id, full_name="K", role_id=role.id); db.add(emp); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="Br"); db.add(br); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS",
                       status="ACTIVE", created_at=cashenv.now); db.add(till)
    db.commit()
    return co, br, emp, till


def _open(db, emp, opening=0):
    return uuid.UUID(shifts_api.open_shift(shifts_api.OpenShift(opening_cash=opening), emp, db)["id"])


def _mv(db, emp, sid, mtype, amt, cu=None):
    return shifts_api.add_cash_movement(sid, shifts_api.CashMove(type=mtype, amount=amt, client_uuid=cu), emp, db)


def _T0(cashenv):
    return cashenv.now - timedelta(days=1)   # barcha live amallar >= T0


def _inject(db, co, till, br, **over):
    v = dict(id=uuid.uuid4(), tenant_id=co.id, cash_account_id=till.id, branch_id=br.id, account_type="TILL",
             shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP", source_id=uuid.uuid4(),
             leg_index=0, direction="IN", category="CASH_IN", amount=Decimal("111"), currency="UZS",
             device_occurred_at=datetime.now(timezone.utc), server_received_at=datetime.now(timezone.utc),
             recorded_at=datetime.now(timezone.utc), idempotency_key="inj-" + _hex(), provenance="NORMAL")
    v.update(over)
    if v["provenance"] == "RECONSTRUCTION":
        v.setdefault("reconstruction_reason", "x"); v.setdefault("reconstruction_source_ref", "y")
    db.execute(_pg(CashLedgerEntry.__table__).values(**v).on_conflict_do_nothing()); db.commit()
    return v


# ═══ UNIT: compare_leg field-level klassifikatsiya ═══════════════════════════
def _act(**kw):
    d = dict(amount=Decimal("100"), direction="IN", category="SALE", branch_id=uuid.uuid4(),
             cash_account_id=uuid.uuid4(), shift_id=None, posting_kind="OFF_SHIFT",
             provenance="NORMAL", device_occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
             id=uuid.uuid4())
    d.update(kw); return types.SimpleNamespace(**d)


def test_compare_leg_all_codes():
    exp = dict(amount="100", direction="IN", category="SALE", branch_id=None, shift_id=None, posting_kind="OFF_SHIFT")
    assert ce.compare_leg(exp, _act()) == []
    assert ce.WRONG_AMOUNT in ce.compare_leg(exp, _act(amount=Decimal("90")))
    assert ce.WRONG_DIRECTION in ce.compare_leg(exp, _act(direction="OUT"))
    assert ce.WRONG_CATEGORY in ce.compare_leg(exp, _act(category="REFUND"))
    assert ce.UNEXPECTED_RECONSTRUCTION in ce.compare_leg(exp, _act(provenance="RECONSTRUCTION"))
    acc = uuid.uuid4()
    assert ce.WRONG_ACCOUNT in ce.compare_leg(exp, _act(cash_account_id=uuid.uuid4()), expected_account_id=acc)
    bexp = dict(exp, branch_id=str(uuid.uuid4()))
    assert ce.WRONG_BRANCH in ce.compare_leg(bexp, _act(branch_id=uuid.uuid4()))
    sexp = dict(exp, posting_kind="ON_SHIFT", shift_id=str(uuid.uuid4()))
    assert ce.WRONG_SHIFT in ce.compare_leg(sexp, _act(posting_kind="ON_SHIFT", shift_id=uuid.uuid4()))
    assert ce.WRONG_POSTING_KIND in ce.compare_leg(dict(exp, posting_kind="ON_SHIFT"), _act(posting_kind="OFF_SHIFT", shift_id=None))
    t0 = datetime(2026, 6, 15, tzinfo=timezone.utc)
    assert ce.WRONG_TIMESTAMP in ce.compare_leg(exp, _act(device_occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc)), t0dt=t0)
    # §20: LATE_SYNC (offline-first live) -> WRONG_POSTING_KIND FIRE ETMAYDI (yolg'on mismatch yo'q)
    assert ce.WRONG_POSTING_KIND not in ce.compare_leg(dict(exp, posting_kind="ON_SHIFT"), _act(posting_kind="LATE_SYNC"))


# ═══ INTEGRATION: reconcile_events ═══════════════════════════════════════════
def test_reconcile_clean(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    _mv(db, emp, sid, "payin", 5000)
    _mv(db, emp, sid, "payout", 3000)
    r = ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert r["mismatch_total"] == 0 and r["matched"] >= 3   # OPENING + payin + payout


def test_reconcile_missing_ledger(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    mode.set_mode("LEGACY_ONLY")
    _mv(db, emp, sid, "expense", 5000)     # legacy bor, ledger YO'Q
    mode.reset_mode()
    r = ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert r["mismatch_counts"].get(ce.MISSING_LEDGER) == 1


def test_reconcile_extra_ledger(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    _open(db, emp, 100000)
    _inject(db, co, till, br, source_type="CASH_OP", source_id=uuid.uuid4())   # legacy manba yo'q
    r = ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert r["mismatch_counts"].get(ce.EXTRA_LEDGER) == 1


def test_reconcile_shadow_double_count(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    # SOYA CashMovement (payout "Qaytarish", client_uuid NULL)
    shadow = CashMovement(shift_id=sid, type=CashMovementType.payout, amount=Decimal("4000"),
                          reason="Qaytarish RET-9", created_at=datetime.now(timezone.utc)); db.add(shadow); db.commit()
    _inject(db, co, till, br, source_type="CASH_OP", source_id=shadow.id, direction="OUT", category="CASH_OUT")
    r = ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert r["mismatch_counts"].get(ce.SHADOW_DOUBLE_COUNT) == 1


def test_reconcile_unexpected_reconstruction(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    mode.set_mode("LEGACY_ONLY")
    _mv(db, emp, sid, "payin", 7000)       # legacy movement, NORMAL leg yo'q
    mode.reset_mode()
    mvrow = db.query(CashMovement).filter(CashMovement.shift_id == sid,
                                          CashMovement.type == CashMovementType.payin).one()
    # live hodisa key'ига RECONSTRUCTION leg (live'ni backfill qilgandek) -> UNEXPECTED_RECONSTRUCTION
    _inject(db, co, till, br, source_type="CASH_OP", source_id=mvrow.id, amount=Decimal("7000"),
            category="CASH_IN", provenance="RECONSTRUCTION")
    r = ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert r["mismatch_counts"].get(ce.UNEXPECTED_RECONSTRUCTION) == 1


def test_reconcile_unexpected_normal_post(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    t0 = cashenv.now
    # < T0 (tarixiy) CashMovement, lekin NORMAL leg (live dual-write qilingandek) -> UNEXPECTED_NORMAL_POST
    old = CashMovement(shift_id=sid, type=CashMovementType.expense, amount=Decimal("2000"),
                       created_at=t0 - timedelta(hours=2)); db.add(old); db.commit()
    _inject(db, co, till, br, source_type="CASH_OP", source_id=old.id, amount=Decimal("2000"),
            direction="OUT", category="EXPENSE", provenance="NORMAL",
            device_occurred_at=t0 - timedelta(hours=2))
    r = ce.reconcile_events(db, co.id, t0=t0)
    assert r["mismatch_counts"].get(ce.UNEXPECTED_NORMAL_POST) == 1


def test_backfill_reconstruction_not_flagged_with_t0(db, cashenv):
    # §20 fix pozitiv tomoni: to'g'ri T0 bilan, < T0 tarixiy hodisaning RECONSTRUCTION leg'i KUTILGAN
    # (UNEXPECTED_RECONSTRUCTION deb belgilanmaydi) — t0=None bo'lган bug'ning aksi.
    co, br, emp, till = _fresh(db, cashenv)
    t0 = cashenv.now
    sid = _open(db, emp, 0)
    old = CashMovement(shift_id=sid, type=CashMovementType.payin, amount=Decimal("3000"),
                       created_at=t0 - timedelta(hours=2)); db.add(old); db.commit()   # < T0 tarixiy
    _inject(db, co, till, br, source_type="CASH_OP", source_id=old.id, amount=Decimal("3000"),
            category="CASH_IN", direction="IN", provenance="RECONSTRUCTION",
            device_occurred_at=t0 - timedelta(hours=2))
    r = ce.reconcile_events(db, co.id, t0=t0)
    assert r["mismatch_counts"].get(ce.UNEXPECTED_RECONSTRUCTION) is None   # tarixiy RECONSTRUCTION OK


def test_reconcile_wrong_amount_integration(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    mode.set_mode("LEGACY_ONLY")
    _mv(db, emp, sid, "payin", 5000)
    mode.reset_mode()
    mvrow = db.query(CashMovement).filter(CashMovement.shift_id == sid,
                                          CashMovement.type == CashMovementType.payin).one()
    _inject(db, co, till, br, source_type="CASH_OP", source_id=mvrow.id, amount=Decimal("9999"),  # NOTO'G'RI
            category="CASH_IN", direction="IN")
    r = ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert r["mismatch_counts"].get(ce.WRONG_AMOUNT) == 1


def test_cross_tenant_leg_db_prevented(db, cashenv):
    # TENANT_MISMATCH DB DARAJАСИДА imkonsiz: cle_acct_currency_fk (tenant_id, cash_account_id, currency)
    # cash_accounts'ga FK -> leg tenant'i account tenant'iga TENG bo'lishi SHART. reconcile'даги
    # TENANT_MISMATCH tekshiruvи defense-in-depth (bu FK undan kuchliroq — hech qachon yozilmaydi).
    from sqlalchemy.exc import IntegrityError
    co, br, emp, till = _fresh(db, cashenv)
    co2, br2, emp2, till2 = _fresh(db, cashenv)   # boshqa tenant TILL
    with pytest.raises(IntegrityError):           # co leg + co2 TILL -> cross-tenant FK BLOCK
        _inject(db, co, till2, br, source_type="CASH_OP", source_id=uuid.uuid4())
    db.rollback()


def test_reconcile_tenant_isolation(db, cashenv):
    coA, brA, empA, tillA = _fresh(db, cashenv)
    coB, brB, empB, tillB = _fresh(db, cashenv)
    _open(db, empA, 100000); _open(db, empB, 55555)
    _inject(db, coB, tillB, brB, source_type="CASH_OP", source_id=uuid.uuid4())   # faqat B'да extra
    rA = ce.reconcile_events(db, coA.id, t0=_T0(cashenv))
    assert rA["mismatch_total"] == 0                          # A B'ning extra'sini KO'RMAYDI
    rB = ce.reconcile_events(db, coB.id, t0=_T0(cashenv))
    assert rB["mismatch_counts"].get(ce.EXTRA_LEDGER) == 1


# ═══ COMPARE RUN + EVALUATOR ═════════════════════════════════════════════════
def test_compare_run_clean_and_ready(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    _mv(db, emp, sid, "payin", 5000)
    run = ce.compare_run(db, company_id=co.id, t0=_T0(cashenv), run_id="r1")
    assert run["status"] == "MATCH" and run["unexplained_delta_events"] == 0
    assert run["absolute_delta"] == 0.0 and run["matched_events"] >= 2
    ready = ce.evaluate_cutover_readiness(db, company_id=co.id, t0=_T0(cashenv), run=run,
                                          completed_clean_cycles=14)
    assert ready["readiness"] == "READY" and ready["reasons"] == []


def test_evaluator_not_ready_reasons(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    run = ce.compare_run(db, company_id=co.id, t0=_T0(cashenv))
    # 1) yetarli sikl yo'q
    r0 = ce.evaluate_cutover_readiness(db, company_id=co.id, run=run, completed_clean_cycles=0)
    assert r0["readiness"] == "NOT_READY"
    assert any(x["code"] == "INSUFFICIENT_OBSERVATION_CYCLES" for x in r0["reasons"])
    # 2) incomplete backfill
    r1 = ce.evaluate_cutover_readiness(db, company_id=co.id, run=run, completed_clean_cycles=14,
                                       backfill_complete=False)
    assert any(x["code"] == "INCOMPLETE_BACKFILL" for x in r1["reasons"]) and r1["readiness"] == "NOT_READY"
    # 3) multi-till blocker
    r2 = ce.evaluate_cutover_readiness(db, company_id=co.id, run=run, completed_clean_cycles=14,
                                       multi_till_blocker=True)
    assert any(x["code"] == "MULTI_TILL_MAPPING_BLOCKER" for x in r2["reasons"])
    # 4) mismatch (extra leg) -> UNEXPLAINED + EXTRA_LEDGER
    _inject(db, co, till, br, source_type="CASH_OP", source_id=uuid.uuid4())
    run2 = ce.compare_run(db, company_id=co.id, t0=_T0(cashenv))
    r3 = ce.evaluate_cutover_readiness(db, company_id=co.id, run=run2, completed_clean_cycles=14)
    assert r3["readiness"] == "NOT_READY"
    codes = {x["code"] for x in r3["reasons"]}
    assert "UNEXPLAINED_MISMATCH" in codes and "EXTRA_LEDGER" in codes


def test_evaluator_never_changes_mode(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    before = mode.cash_mode()
    ce.evaluate_cutover_readiness(db, company_id=co.id, t0=_T0(cashenv), completed_clean_cycles=99)
    assert mode.cash_mode() == before == mode.CashMode.DUAL_WRITE_SHADOW   # cutover QILINMADI


def test_compare_requires_t0(db, cashenv):
    # §20 topilma: T0'siz reconcile provenance semantikasini teskari qilardi (backfill'ni live deb,
    # double-post'ni YASHIRARди). Endi T0 MAJBURIY — jimgina noto'g'ri natija emas, fail loud.
    co, br, emp, till = _fresh(db, cashenv)
    with pytest.raises(ValueError):
        ce.reconcile_events(db, co.id, t0=None)
    with pytest.raises(ValueError):
        ce.compare_run(db, company_id=co.id, t0=None)
    with pytest.raises(ValueError):
        ce.evaluate_cutover_readiness(db, company_id=co.id, t0=None)   # run=None + t0=None


def test_run_offsetting_not_masked(db, cashenv):
    # ikki till offsetting -> run REVIEW, abs_delta > 0 (netting yashirmaydi)
    co, br, emp, till = _fresh(db, cashenv)
    co2 = co   # bir tenant, ikki till
    br2 = Branch(company_id=co.id, code="B" + _hex(), name="Br2"); db.add(br2); db.flush()
    till2 = CashAccount(tenant_id=co.id, branch_id=br2.id, type="TILL", currency="UZS",
                        status="ACTIVE", created_at=cashenv.now); db.add(till2); db.commit()
    _inject(db, co, till, br, direction="IN", category="CASH_IN", amount=Decimal("5000"), source_id=uuid.uuid4())    # +5000
    _inject(db, co, till2, br2, direction="OUT", category="CASH_OUT", amount=Decimal("5000"), source_id=uuid.uuid4())  # -5000 (net 0)
    run = ce.compare_run(db, company_id=co.id, t0=_T0(cashenv))
    assert run["status"] != "MATCH"                  # net 0 BO'LSA HAM MATCH emas
    assert run["absolute_delta"] == 10000.0 and run["divergent_tills"] == 2
    # §20 catch-all: MATCH bo'lmagan run -> evaluator NOT_READY (RUN_NOT_MATCH ham sabablar orasida)
    ready = ce.evaluate_cutover_readiness(db, company_id=co.id, run=run, completed_clean_cycles=14)
    assert ready["readiness"] == "NOT_READY"
    assert any(x["code"] == "RUN_NOT_MATCH" for x in ready["reasons"])


def test_multi_cashier_sequential_ok(db, cashenv):
    # §20: KETMA-KET (non-overlapping) ko'p kassir -> mapping VALID (finding A). Faqat KONKURRENT muhim.
    from app.models.enums import ShiftStatus
    co, br, emp, till = _fresh(db, cashenv)
    role = db.query(Role).first()
    empB = Employee(company_id=co.id, full_name="KB", role_id=role.id); db.add(empB); db.flush()
    db.add(EmployeeBranch(employee_id=empB.id, branch_id=br.id))
    t = cashenv.now
    db.add(Shift(branch_id=br.id, cashier_id=emp.id, opened_at=t - timedelta(hours=4),
                 closed_at=t - timedelta(hours=3), opening_cash=Decimal("0"), status=ShiftStatus.closed))
    db.add(Shift(branch_id=br.id, cashier_id=empB.id, opened_at=t - timedelta(hours=2),
                 closed_at=t - timedelta(hours=1), opening_cash=Decimal("0"), status=ShiftStatus.closed))
    db.commit()
    f = ce.multi_cashier_till_finding(db, company_id=co.id)
    assert f["finding"] == "A" and f["ambiguous_branches"] == 0   # konkurrentlik yo'q -> VALID


# ═══ READ-ONLY kafolat (§13) ═════════════════════════════════════════════════
def test_compare_engine_read_only_source():
    import inspect
    from app.services.cash import compare_engine
    src = inspect.getsource(compare_engine)
    assert "CashLedgerEntry(" not in src                      # ORM ctor yo'q
    assert "session.add" not in src and "db.add" not in src    # yozuv yo'q
    assert "db.commit" not in src and "db.flush" not in src
    assert "insert(CashLedgerEntry" not in src                 # pg_insert yo'q
    assert "UPDATE" not in src.upper().replace("UPDATED", "")   # UPDATE yo'q


def test_compare_run_does_not_write(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000); _mv(db, emp, sid, "payin", 5000)
    n0 = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count()
    ce.compare_run(db, company_id=co.id, t0=_T0(cashenv))
    ce.evaluate_cutover_readiness(db, company_id=co.id, t0=_T0(cashenv), completed_clean_cycles=14)
    ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count() == n0   # o'zgarmadi


# ═══ T0 mikrosekund chegarasi (§07) ══════════════════════════════════════════
def test_t0_microsecond_boundary(db, cashenv):
    from app.db.cash.migration import phase1
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 0)
    t0 = cashenv.now
    us = timedelta(microseconds=1)
    # 3 movement: T0-1us (tarixiy), T0 (live), T0+1us (live)
    for label, ts in (("before", t0 - us), ("at", t0), ("after", t0 + us)):
        db.add(CashMovement(shift_id=sid, type=CashMovementType.payin, amount=Decimal("1000"),
                            reason=label, created_at=ts))
    db.commit()
    plan = phase1.plan_backfill(db, company_id=co.id, t0=t0.isoformat())
    before_keys = {(l["source_type"], l["source_id"]) for l in plan["legs"]}
    after_keys = {(l["source_type"], l["source_id"]) for l in plan["legs_after_t0"]}
    # GAP/OVERLAP yo'q: har hodisa AYNAN bitta tomonda
    assert before_keys.isdisjoint(after_keys)
    cashop_before = [l for l in plan["legs"] if l["source_type"] == "CASH_OP"]
    cashop_after = [l for l in plan["legs_after_t0"] if l["source_type"] == "CASH_OP"]
    # T0-1us -> before; T0 va T0+1us -> after (>= T0 inclusive)
    assert len(cashop_before) == 1 and len(cashop_after) == 2


# ═══ KONKURRENTLIK / KONVERGENSIYA (§14) ═════════════════════════════════════
def test_repeated_compare_converges(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000); _mv(db, emp, sid, "payin", 5000)
    r1 = ce.compare_run(db, company_id=co.id, t0=_T0(cashenv))
    r2 = ce.compare_run(db, company_id=co.id, t0=_T0(cashenv))
    assert (r1["absolute_delta"], r1["mismatch_total"], r1["status"]) == \
           (r2["absolute_delta"], r2["mismatch_total"], r2["status"])   # konvergensiya (barqaror)


def test_compare_sees_atomic_source_and_ledger(db, cashenv):
    # sale+ledger BIR tranzaksiyада -> compare hech qachon yarim-holat ko'rmaydi (payin bor -> leg bor)
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000)
    _mv(db, emp, sid, "payin", 5000)      # source + NORMAL leg atomik commit
    r = ce.reconcile_events(db, co.id, t0=_T0(cashenv))
    assert r["mismatch_counts"].get(ce.MISSING_LEDGER) is None   # yarim-yozilgan (source-siz leg / leg-siz source) yo'q
    assert r["mismatch_counts"].get(ce.EXTRA_LEDGER) is None


# ═══ MULTI-CASHIER / ONE-TILL topilmasi (§10) ════════════════════════════════
def test_multi_cashier_finding_single_ok(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    _open(db, emp, 100000)
    f = ce.multi_cashier_till_finding(db, company_id=co.id)
    assert f["finding"] == "A" and "VALID" in f["summary"]


def test_multi_cashier_finding_ambiguous(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    _open(db, emp, 100000)
    # ikkinchi kassir shu filialда (terminal_id NULL) -> AMBIGUOUS -> finding C
    role = db.query(Role).first()
    empB = Employee(company_id=co.id, full_name="KB", role_id=role.id); db.add(empB); db.flush()
    db.add(EmployeeBranch(employee_id=empB.id, branch_id=br.id)); db.commit()
    _open(db, empB, 50000)
    f = ce.multi_cashier_till_finding(db, company_id=co.id)
    assert f["finding"] == "C" and f["ambiguous_branches"] >= 1
    assert "BLOCKS cutover" in f["cutover_impact"]


def test_multi_cashier_finding_terminal_distinguishes(db, cashenv):
    from app.models.org import Terminal
    co, br, emp, till = _fresh(db, cashenv)
    t1 = Terminal(branch_id=br.id, name="T1"); t2 = Terminal(branch_id=br.id, name="T2")
    db.add_all([t1, t2]); db.flush()
    role = db.query(Role).first()
    empB = Employee(company_id=co.id, full_name="KB", role_id=role.id); db.add(empB); db.flush()
    db.add(EmployeeBranch(employee_id=empB.id, branch_id=br.id)); db.flush()
    # ikki kassir turli terminal
    db.add(Shift(branch_id=br.id, cashier_id=emp.id, terminal_id=t1.id,
                 opened_at=datetime.now(timezone.utc), opening_cash=Decimal("0")))
    db.add(Shift(branch_id=br.id, cashier_id=empB.id, terminal_id=t2.id,
                 opened_at=datetime.now(timezone.utc), opening_cash=Decimal("0")))
    db.commit()
    f = ce.multi_cashier_till_finding(db, company_id=co.id)
    assert f["finding"] == "B" and f["needs_terminal_till"] >= 1


# ═══ 1C historical import siyosati (§11) ═════════════════════════════════════
def test_1c_import_policy_and_no_normal_leg(db, cashenv):
    from app.models.sales import Sale, SalePayment, SaleStatus
    co, br, emp, till = _fresh(db, cashenv)
    t0 = cashenv.now
    # 1C import naqshi: tarixiy Sale + cash SalePayment, shift_id yo'q, HECH QANDAY dual-write hook
    s = Sale(company_id=co.id, branch_id=br.id, cashier_id=emp.id, subtotal=Decimal("50000"),
             total=Decimal("50000"), sold_at=t0 - timedelta(days=10), receipt_no="H" + _hex(),
             status=SaleStatus.completed); db.add(s); db.flush()
    db.add(SalePayment(sale_id=s.id, method_code="cash", amount=Decimal("50000"),
                       paid_at=t0 - timedelta(days=10))); db.commit()
    # NORMAL ledger cash YARATILMADI (import hook chaqirmaydi)
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id,
                                            CashLedgerEntry.provenance == "NORMAL").count() == 0
    # LIVE reconcile (>= T0) bu tarixiy sotuvni live deb KUTMAYDI (< T0 -> backfill hududi)
    r = ce.reconcile_events(db, co.id, t0=t0)
    assert r["mismatch_counts"].get(ce.MISSING_LEDGER) is None
    pol = ce.import_1c_policy()
    assert pol["classification"] == "HISTORICAL_BACKFILL_TERRITORY" and pol["live_dual_write"] is False


# ═══ OPERATOR REPORT (§16) ═══════════════════════════════════════════════════
def test_operator_report_renders(db, cashenv):
    co, br, emp, till = _fresh(db, cashenv)
    sid = _open(db, emp, 100000); _mv(db, emp, sid, "payin", 5000)
    run = ce.compare_run(db, company_id=co.id, t0=_T0(cashenv), run_id="rep1")
    txt = ce.operator_report(run)
    assert "PHASE-3 COMPARE RUN" in txt and "STATUS: MATCH" in txt and "MATCHED EVENTS" in txt
