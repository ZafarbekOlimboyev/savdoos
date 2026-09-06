# -*- coding: utf-8 -*-
"""Cash T0 boundary READ-ONLY probe CLI testlari (real PostgreSQL).

cash_t0_probe: cutover state · ledger inventory · account inventory · dual-write boundary · prior-backfill
detection · open legacy shifts · reconciliation · T0 candidate. STRICTLY READ-ONLY (mutation yo'q, sir yo'q).
Har test FRESH company (shared-DB scoping).
"""
from __future__ import annotations

import json as _json
import uuid
from datetime import timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert as _pg
from sqlalchemy.orm import Session

from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company, Terminal
from app.models.settings import Setting
from app.models.shifts import Shift
from app.services.cash import mode
from app.tools import cash_t0_probe as probe


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _co(db):
    c = Company(name="T0" + _hex(), code="t0" + _hex(), currency="UZS"); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F" + _hex()); db.add(b); db.flush(); return b


def _till(db, co, br, status="ACTIVE"):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status=status,
                    label="TILL code=T-" + _hex() + " terminal=NONE",
                    created_at=__import__("datetime").datetime.now(timezone.utc))
    db.add(a); db.flush(); return a


def _safe(db, co, br):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="SAFE", currency="UZS", status="ACTIVE",
                    label="SAFE code=SAFE", created_at=__import__("datetime").datetime.now(timezone.utc))
    db.add(a); db.flush(); return a


def _inject(db, co, till, br, *, provenance, device, recorded=None, idem=None):
    now = __import__("datetime").datetime.now(timezone.utc)
    v = dict(id=uuid.uuid4(), tenant_id=co.id, cash_account_id=till.id, branch_id=br.id, account_type="TILL",
             shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP", source_id=uuid.uuid4(),
             leg_index=0, direction="IN", category="CASH_IN", amount=Decimal("100"), currency="UZS",
             device_occurred_at=device, server_received_at=(recorded or device),
             recorded_at=(recorded or now), idempotency_key=(idem or ("runtime-" + _hex())),
             provenance=provenance)
    if provenance == "RECONSTRUCTION":
        v.setdefault("reconstruction_reason", "x"); v.setdefault("reconstruction_source_ref", "y")
        v["idempotency_key"] = idem or ("backfill:test:" + _hex())
    db.execute(_pg(CLE.__table__).values(**v).on_conflict_do_nothing()); db.commit()


def _run_json(cashenv):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = probe.main(["--json"], session_factory=(lambda: Session(cashenv.engine)), engine=cashenv.engine)
    out = buf.getvalue()
    rep = _json.loads(out[out.index("{"):out.rindex("}") + 1])
    return rc, rep, out


def _co_row(rep, section, co):
    key = "code" if section in ("ledger_inventory", "cutover_state") else "company"
    return next((x for x in rep[section] if x.get(key) == co.code), None)


def _t0(rep, co):
    return next(x for x in rep["t0_candidate"]["per_company"] if x["company"] == co.code)


# ═══ A) empty ledger ═════════════════════════════════════════════════════════
def test_A_empty_ledger(db, cashenv):
    co = _co(db); _br(db, co); db.commit()
    _, rep, _o = _run_json(cashenv)
    li = _co_row(rep, "ledger_inventory", co)
    assert li["total_rows"] == 0 and li["prior_backfill"] == "NO"
    assert _t0(rep, co)["status"] == "NO_LEDGER_ACTIVITY"


# ═══ B) NORMAL runtime rows only ════════════════════════════════════════════
def test_B_normal_only(db, cashenv):
    co = _co(db); br = _br(db, co); till = _till(db, co, br)
    _inject(db, co, till, br, provenance="NORMAL", device=cashenv.now - timedelta(hours=5))
    _, rep, _o = _run_json(cashenv)
    li = _co_row(rep, "ledger_inventory", co)
    assert li["provenance"].get("NORMAL") == 1 and li["reconstruction_rows"] == 0
    assert li["earliest_NORMAL_device_occurred_at"] is not None and li["prior_backfill"] == "NO"
    assert _t0(rep, co)["status"] == "NOT_PROVABLE_LEDGER_ALONE"


# ═══ C) RECONSTRUCTION rows only ════════════════════════════════════════════
def test_C_reconstruction_only(db, cashenv):
    co = _co(db); br = _br(db, co); till = _till(db, co, br)
    _inject(db, co, till, br, provenance="RECONSTRUCTION", device=cashenv.now - timedelta(hours=10))
    _, rep, _o = _run_json(cashenv)
    li = _co_row(rep, "ledger_inventory", co)
    assert li["reconstruction_rows"] == 1 and li["backfill_idempotency_keys"] == 1
    assert li["prior_backfill"] == "YES"
    assert _t0(rep, co)["status"] == "NOT_PROVABLE_NO_RUNTIME"


# ═══ D) NORMAL + RECONSTRUCTION clean boundary -> PROVABLE ══════════════════
def test_D_clean_boundary_provable(db, cashenv):
    co = _co(db); br = _br(db, co); till = _till(db, co, br)
    _inject(db, co, till, br, provenance="RECONSTRUCTION", device=cashenv.now - timedelta(hours=10))
    _inject(db, co, till, br, provenance="NORMAL", device=cashenv.now - timedelta(hours=5))
    _, rep, _o = _run_json(cashenv)
    t = _t0(rep, co)
    assert t["status"] == "PROVABLE" and t["candidate_window"][0] and t["candidate_window"][1]
    assert _co_row(rep, "ledger_inventory", co)["prior_backfill"] == "YES"


# ═══ E) overlap detected -> NOT_PROVABLE_OVERLAP ════════════════════════════
def test_E_overlap_not_provable(db, cashenv):
    co = _co(db); br = _br(db, co); till = _till(db, co, br)
    # recon device LATER than normal device -> recon_max >= normal_min -> overlap
    _inject(db, co, till, br, provenance="RECONSTRUCTION", device=cashenv.now - timedelta(hours=2))
    _inject(db, co, till, br, provenance="NORMAL", device=cashenv.now - timedelta(hours=5))
    _, rep, _o = _run_json(cashenv)
    assert _t0(rep, co)["status"] == "NOT_PROVABLE_OVERLAP"


# ═══ F) open legacy shift till=NULL -> LEGACY_UNKNOWN ═══════════════════════
def test_F_open_shift_no_till(db, cashenv):
    co = _co(db); br = _br(db, co)
    role = db.query(Role).first()
    emp = Employee(company_id=co.id, full_name="K", role_id=role.id); db.add(emp); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=cashenv.now, opening_cash=Decimal("0"),
               status=ShiftStatus.open, till_id=None); db.add(sh); db.commit()
    _, rep, _o = _run_json(cashenv)
    row = next(x for x in rep["open_legacy_shifts"] if x["shift_id"] == str(sh.id))
    assert row["classify"] == "LEGACY_UNKNOWN" and row["till_id"] is None


# ═══ G) open shift with TILL -> HAS_TILL ════════════════════════════════════
def test_G_open_shift_has_till(db, cashenv):
    co = _co(db); br = _br(db, co); till = _till(db, co, br)
    role = db.query(Role).first()
    emp = Employee(company_id=co.id, full_name="K", role_id=role.id); db.add(emp); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=cashenv.now, opening_cash=Decimal("0"),
               status=ShiftStatus.open, till_id=till.id); db.add(sh); db.commit()
    _, rep, _o = _run_json(cashenv)
    row = next(x for x in rep["open_legacy_shifts"] if x["shift_id"] == str(sh.id))
    assert row["classify"] == "HAS_TILL" and row["till_id"] == str(till.id)


# ═══ H/I/J) cutover unset / set-not-reached / reached ═══════════════════════
def test_H_cutover_unset(db, cashenv):
    co = _co(db); _br(db, co); db.commit()
    _, rep, _o = _run_json(cashenv)
    c = _co_row(rep, "cutover_state", co)
    assert c["cutover_at"] is None and c["enforcement"] == "inactive"


def test_I_cutover_set_not_reached(db, cashenv):
    co = _co(db); _br(db, co)
    future = (cashenv.now + timedelta(days=3650)).isoformat()
    db.add(Setting(company_id=co.id, branch_id=None, key="cash", value={"cutover_at": future})); db.commit()
    _, rep, _o = _run_json(cashenv)
    c = _co_row(rep, "cutover_state", co)
    assert c["cutover_at"] is not None and c["enforcement"] == "inactive"


def test_J_cutover_reached(db, cashenv):
    co = _co(db); _br(db, co)
    past = (cashenv.now - timedelta(days=1)).isoformat()
    db.add(Setting(company_id=co.id, branch_id=None, key="cash", value={"cutover_at": past})); db.commit()
    _, rep, _o = _run_json(cashenv)
    c = _co_row(rep, "cutover_state", co)
    assert c["enforcement"] == "ACTIVE"


# ═══ K) account inventory ACTIVE/ARCHIVED/SAFE ══════════════════════════════
def test_K_account_inventory(db, cashenv):
    co = _co(db); br = _br(db, co)
    _till(db, co, br, status="ACTIVE"); _till(db, co, br, status="ARCHIVED"); _safe(db, co, br)
    db.commit()
    _, rep, _o = _run_json(cashenv)
    a = next(x for x in rep["cash_account_inventory"] if x["company"] == co.code and x["branch_id"] == str(br.id))
    assert a["active_till"] == 1 and a["archived_till"] == 1 and a["safe"] == 1


# ═══ L) reconciliation output present ═══════════════════════════════════════
def test_L_reconciliation_section(db, cashenv):
    co = _co(db); _br(db, co); db.commit()
    _, rep, _o = _run_json(cashenv)
    assert "reconciliation_reviews" in rep and isinstance(rep["reconciliation_reviews"], list)


# ═══ M) secrets not printed ═════════════════════════════════════════════════
def test_M_no_secrets(db, cashenv):
    co = _co(db); _br(db, co); db.commit()
    _, _rep, out = _run_json(cashenv)
    assert str(cashenv.engine.url) not in out
    assert "sqlite:///./_pytest.db" not in out and "DATABASE_URL present:" in out


# ═══ N) strictly read-only (no mutation) ════════════════════════════════════
def test_N_read_only(db, cashenv):
    co = _co(db); br = _br(db, co); till = _till(db, co, br)
    _inject(db, co, till, br, provenance="NORMAL", device=cashenv.now - timedelta(hours=5)); db.commit()
    n_cle = db.query(CLE).filter(CLE.tenant_id == co.id).count()
    n_acc = db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count()
    n_set = db.query(Setting).filter(Setting.company_id == co.id).count()
    _run_json(cashenv)
    assert db.query(CLE).filter(CLE.tenant_id == co.id).count() == n_cle
    assert db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count() == n_acc
    assert db.query(Setting).filter(Setting.company_id == co.id).count() == n_set   # cutover SET qilinmadi
