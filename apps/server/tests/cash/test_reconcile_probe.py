# -*- coding: utf-8 -*-
"""Cash RECONCILE row-level READ-ONLY probe testlari (real PostgreSQL).

cash_reconcile_probe: har naqd manba qatori (CustomerPayment/SupplierPayment/Return) uchun soya/ledger
mavjudligi + backfill layoqati + klassifikatsiya. STRICTLY READ-ONLY (mutation yo'q, shaxsiy maydon yo'q).
Har test FRESH company (shared-DB scoping); global verdict FAQAT orphan kafolatланган testlarда tekshiriladi.

A CustomerPayment soyasiz+reconstructable -> EXPECTED_LEGACY_NO_SHADOW
B SupplierPayment soyasiz+reconstructable -> EXPECTED_LEGACY_NO_SHADOW
C Return soyasiz+reconstructable         -> EXPECTED_LEGACY_NO_SHADOW
D orphan soya (manba yo'q)               -> orphan>0, reconcile REVIEW, verdict REVIEW_REQUIRED
E dublikat soya (2 soya / 1 manba)       -> orphan>0, REVIEW
F ledger amount mismatch                 -> DATA_INCONSISTENCY
G noto'g'ri source-mapping (prefix/yo'nalish izolyatsiyasi)
H tenant izolyatsiyasi
I fizik TILL yo'q -> BACKFILL_NOT_ELIGIBLE (taxmin YO'Q)
J strictly read-only (mutation yo'q, cutover SET emas)
K shaxsiy maydon chiqmaydi (ism/telefon/customer_id/employee_id)
"""
from __future__ import annotations

import json as _json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert as _pg
from sqlalchemy.orm import Session

from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.customers import Customer, CustomerPayment
from app.models.enums import CashMovementType as CMT, ShiftStatus
from app.models.org import Branch, Company
from app.models.sales import Return
from app.models.settings import Setting
from app.models.purchasing import Supplier, SupplierPayment
from app.models.shifts import CashMovement, Shift
from app.services.cash import mode
from app.tools import cash_reconcile_probe as probe


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _co(db):
    c = Company(name="RC" + _hex(), code="rc" + _hex(), currency="UZS"); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F" + _hex(), is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, branch=None):
    e = Employee(company_id=co.id, full_name="K" + _hex(), role_id=db.query(Role).first().id)
    db.add(e); db.flush()
    if branch is not None:
        db.add(EmployeeBranch(employee_id=e.id, branch_id=branch.id)); db.flush()
    return e


def _till(db, co, br):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                    label="TILL code=T-" + _hex() + " terminal=NONE", created_at=_now())
    db.add(a); db.flush(); return a


def _shift(db, co, br, emp):
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(hours=2),
               closed_at=_now() - timedelta(hours=1), opening_cash=Decimal("0"), status=ShiftStatus.closed)
    db.add(sh); db.flush(); return sh


def _cust(db, co, name="Ali"):
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name=name, credit_balance=Decimal("0"))
    db.add(cu); db.flush(); return cu


def _custpay(db, cust, amt, emp, branch=None, method="cash"):
    p = CustomerPayment(customer_id=cust.id, amount=Decimal(str(amt)), method=method, paid_at=_now(),
                        created_at=_now(), employee_id=emp.id, branch_id=(branch.id if branch else None))
    db.add(p); db.flush(); return p


def _sup(db, co, name="Supplier"):
    s = Supplier(company_id=co.id, name=name); db.add(s); db.flush(); return s


def _suppay(db, sup, amt, emp, method="cash"):
    p = SupplierPayment(supplier_id=sup.id, amount=Decimal(str(amt)), method=method, paid_at=_now(),
                        created_at=_now(), employee_id=emp.id)
    db.add(p); db.flush(); return p


def _ret(db, co, br, emp, amt, method="cash"):
    r = Return(return_no="RET" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
               refund_method=method, total=Decimal(str(amt)), created_at=_now())
    db.add(r); db.flush(); return r


def _shadow(db, shift, mtype, amt, reason, emp=None):
    m = CashMovement(shift_id=shift.id, type=mtype, amount=Decimal(str(amt)), reason=reason,
                     client_uuid=None, employee_id=(emp.id if emp else None), created_at=_now())
    db.add(m); db.flush(); return m


def _run_json(cashenv):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = probe.main(["--json"], session_factory=(lambda: Session(cashenv.engine)), engine=cashenv.engine)
    out = buf.getvalue()
    rep = _json.loads(out[out.index("{"):out.rindex("}") + 1])
    return rc, rep, out


def _block(rep, co, section):
    b = next(x for x in rep["companies"] if x["company_id"] == str(co.id))
    return b[section]


# ═══ A) CustomerPayment soyasiz + reconstructable -> EXPECTED_LEGACY_NO_SHADOW ═
def test_A_customer_no_shadow_expected_legacy(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); _till(db, co, br)
    _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()
    _rc, rep, _o = _run_json(cashenv)
    sec = _block(rep, co, "customer_payment")
    assert sec["summary"]["source_rows"] == 1
    assert sec["summary"]["by_classification"].get("EXPECTED_LEGACY_NO_SHADOW") == 1
    r = sec["rows"][0]
    assert r["classification"] == "EXPECTED_LEGACY_NO_SHADOW"
    assert r["shadow_present"] is False and r["backfill_eligible"] is True and r["ledger_present"] is False


# ═══ B) SupplierPayment soyasiz + reconstructable (single-branch) ═════════════
def test_B_supplier_no_shadow_expected_legacy(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); _till(db, co, br)
    _suppay(db, _sup(db, co), 5000, emp); db.commit()   # branch yo'q -> single-branch tenant -> shu TILL
    _rc, rep, _o = _run_json(cashenv)
    sec = _block(rep, co, "supplier_payment")
    assert sec["summary"]["source_rows"] == 1
    assert sec["rows"][0]["classification"] == "EXPECTED_LEGACY_NO_SHADOW"
    assert sec["rows"][0]["backfill_eligible"] is True


# ═══ C) Return soyasiz + reconstructable -> EXPECTED_LEGACY_NO_SHADOW ═════════
def test_C_return_no_shadow_expected_legacy(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); _till(db, co, br)
    _ret(db, co, br, emp, 4000); db.commit()
    _rc, rep, _o = _run_json(cashenv)
    sec = _block(rep, co, "return")
    assert sec["summary"]["source_rows"] == 1
    assert sec["rows"][0]["classification"] == "EXPECTED_LEGACY_NO_SHADOW"
    assert sec["rows"][0]["backfill_eligible"] is True


# ═══ D) orphan soya (manba yo'q) -> orphan>0, reconcile REVIEW, verdict REVIEW ═
def test_D_orphan_shadow_review(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); sh = _shift(db, co, br, emp); _till(db, co, br)
    _shadow(db, sh, CMT.payin, 9000, "Qarz to'lovi · Orphan", emp=emp)  # SOYA bor, CustomerPayment YO'Q
    db.commit()
    _rc, rep, _o = _run_json(cashenv)
    sec = _block(rep, co, "customer_payment")
    assert sec["summary"]["source_rows"] == 0
    assert sec["summary"]["orphan_shadows"] == 1
    recon = _block_recon(rep, co)
    assert any(f["code"] == "RECONCILE_DEBT_SHADOW" and f["severity"] == "REVIEW" for f in recon)
    assert rep["verdict"] == "REVIEW_REQUIRED"        # orphan -> global REVIEW kafolatланган


def _block_recon(rep, co):
    return next(x for x in rep["companies"] if x["company_id"] == str(co.id))["reconcile_findings"]


# ═══ E) dublikat soya (2 soya / 1 manba) -> orphan>0, REVIEW ═════════════════
def test_E_duplicate_shadow_review(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); sh = _shift(db, co, br, emp); _till(db, co, br)
    cust = _cust(db, co)
    _custpay(db, cust, 3000, emp, branch=br)
    _shadow(db, sh, CMT.payin, 3000, "Qarz to'lovi · Ali", emp=emp)     # 1-soya (mos)
    _shadow(db, sh, CMT.payin, 3000, "Qarz to'lovi · Ali", emp=emp)     # 2-soya (DUBLIKAT -> ortiqcha)
    db.commit()
    _rc, rep, _o = _run_json(cashenv)
    sec = _block(rep, co, "customer_payment")
    assert sec["summary"]["source_rows"] == 1 and sec["summary"]["shadow_total"] == 2
    assert sec["summary"]["orphan_shadows"] == 1          # 2 soya - 1 manba(matched) = 1 ortiqcha
    assert any(f["code"] == "RECONCILE_DEBT_SHADOW" and f["severity"] == "REVIEW" for f in _block_recon(rep, co))
    assert rep["verdict"] == "REVIEW_REQUIRED"


# ═══ F) ledger amount mismatch -> DATA_INCONSISTENCY ═════════════════════════
def _inject_ledger(db, co, till, br, source_type, source_id, amount):
    v = dict(id=uuid.uuid4(), tenant_id=co.id, cash_account_id=till.id, branch_id=br.id, account_type="TILL",
             shift_id=None, posting_kind="OFF_SHIFT", source_type=source_type, source_id=source_id,
             leg_index=0, direction="IN", category="DEBT_IN", amount=Decimal(str(amount)), currency="UZS",
             device_occurred_at=_now(), server_received_at=_now(), recorded_at=_now(),
             idempotency_key="probe-test-" + _hex(), provenance="RECONSTRUCTION",
             reconstruction_reason="x", reconstruction_source_ref="y")
    db.execute(_pg(CLE.__table__).values(**v).on_conflict_do_nothing()); db.commit()


def test_F_ledger_amount_mismatch_inconsistency(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); till = _till(db, co, br)
    p = _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()
    _inject_ledger(db, co, till, br, "CUSTOMER_PAYMENT", p.id, 9999)    # ledger 9999 != manba 3000
    _rc, rep, _o = _run_json(cashenv)
    r = _block(rep, co, "customer_payment")["rows"][0]
    assert r["ledger_present"] is True and r["classification"] == "DATA_INCONSISTENCY"
    assert rep["verdict"] == "REVIEW_REQUIRED"


# ═══ G) source-mapping izolyatsiyasi (prefix/yo'nalish) ══════════════════════
def test_G_source_mapping_isolation(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); sh = _shift(db, co, br, emp); _till(db, co, br)
    # FAQAT debt soyasi (payin, "Qarz to'lovi · ") -> supplier(payout)/return(payout) ta'sirlanmaydi
    _shadow(db, sh, CMT.payin, 3000, "Qarz to'lovi · Ali", emp=emp)
    _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()
    _rc, rep, _o = _run_json(cashenv)
    assert _block(rep, co, "customer_payment")["summary"]["shadow_total"] == 1
    assert _block(rep, co, "supplier_payment")["summary"]["shadow_total"] == 0   # payin != payout prefiksi
    assert _block(rep, co, "return")["summary"]["shadow_total"] == 0
    assert _block(rep, co, "customer_payment")["rows"][0]["classification"] == "SHADOW_PRESENT"


# ═══ H) tenant izolyatsiyasi ═════════════════════════════════════════════════
def test_H_tenant_isolation(db, cashenv):
    coA = _co(db); brA = _br(db, coA); empA = _emp(db, coA, brA); _till(db, coA, brA)
    shA = _shift(db, coA, brA, empA)
    _custpay(db, _cust(db, coA), 3000, empA, branch=brA)
    _shadow(db, shA, CMT.payin, 3000, "Qarz to'lovi · Ali", emp=empA)
    coB = _co(db); brB = _br(db, coB); _emp(db, coB, brB); _till(db, coB, brB)   # B bo'sh
    db.commit()
    _rc, rep, _o = _run_json(cashenv)
    assert _block(rep, coB, "customer_payment")["summary"]["source_rows"] == 0
    assert _block(rep, coB, "customer_payment")["summary"]["shadow_total"] == 0   # A soyasi B'ga sizmadi
    assert _block(rep, coA, "customer_payment")["summary"]["shadow_total"] == 1


# ═══ I) fizik TILL yo'q -> BACKFILL_NOT_ELIGIBLE (taxmin YO'Q) ════════════════
def test_I_no_till_not_eligible_no_guess(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)   # TILL PROVISION QILINMAGAN
    _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()
    _rc, rep, _o = _run_json(cashenv)
    r = _block(rep, co, "customer_payment")["rows"][0]
    assert r["classification"] == "BACKFILL_NOT_ELIGIBLE"
    assert r["backfill_eligible"] is False and r["backfill_review_severity"] == "REVIEW"
    assert _block(rep, co, "customer_payment")["summary"]["not_eligible"] == 1


# ═══ J) strictly read-only (mutation yo'q, cutover SET emas) ══════════════════
def test_J_read_only_no_mutation(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); sh = _shift(db, co, br, emp); _till(db, co, br)
    _custpay(db, _cust(db, co), 3000, emp, branch=br)
    _shadow(db, sh, CMT.payin, 3000, "Qarz to'lovi · Ali", emp=emp); db.commit()
    n_mv = db.query(CashMovement).count()
    n_cp = db.query(CustomerPayment).count()
    n_cle = db.query(CLE).filter(CLE.tenant_id == co.id).count()
    n_set = db.query(Setting).filter(Setting.company_id == co.id).count()
    _run_json(cashenv)
    assert db.query(CashMovement).count() == n_mv
    assert db.query(CustomerPayment).count() == n_cp
    assert db.query(CLE).filter(CLE.tenant_id == co.id).count() == n_cle
    assert db.query(Setting).filter(Setting.company_id == co.id).count() == n_set   # cutover SET qilinmadi


# ═══ K) shaxsiy maydon chiqmaydi (ism/customer_id/employee_id) ════════════════
def test_K_no_sensitive_output(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); _till(db, co, br)
    cust = _cust(db, co, name="SECRETCUSTOMERNAME")
    sup = _sup(db, co, name="SECRETSUPPLIERNAME")
    _custpay(db, cust, 3000, emp, branch=br)
    _suppay(db, sup, 5000, emp); db.commit()
    _rc, _rep, out = _run_json(cashenv)
    assert "SECRETCUSTOMERNAME" not in out and "SECRETSUPPLIERNAME" not in out
    assert str(cust.id) not in out and str(sup.id) not in out and str(emp.id) not in out
    assert str(cashenv.engine.url) not in out and "DATABASE_URL present:" in out


# ═══ L) sof holat: source bor, soya bor, orphan yo'q -> row SHADOW_PRESENT ════
def test_L_clean_shadow_present(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); sh = _shift(db, co, br, emp); _till(db, co, br)
    _suppay(db, _sup(db, co), 5000, emp)
    _shadow(db, sh, CMT.payout, 5000, "Ta'minotchi · S", emp=emp); db.commit()
    _rc, rep, _o = _run_json(cashenv)
    sec = _block(rep, co, "supplier_payment")
    assert sec["summary"]["orphan_shadows"] == 0
    assert sec["rows"][0]["classification"] == "SHADOW_PRESENT" and sec["rows"][0]["shadow_present"] is True


# ═══ M) human-mode chiqishi + exit-code shartnomasi (orphan -> EXIT_REVIEW=2) ═
def test_M_human_output_and_exit_code(db, cashenv):
    import io
    import contextlib
    from app.tools import _common as _C
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br); sh = _shift(db, co, br, emp); _till(db, co, br)
    _shadow(db, sh, CMT.payin, 1000, "Qarz to'lovi · Orphan2", emp=emp); db.commit()   # orphan -> REVIEW
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = probe.main([], session_factory=(lambda: Session(cashenv.engine)), engine=cashenv.engine)
    out = buf.getvalue()
    assert rc == _C.EXIT_REVIEW                     # orphan bor -> REVIEW exit
    assert "VERDICT:" in out and "COMPANY" in out    # human printer ishladi (JSON emas)
    assert "{" not in out.split("VERDICT:")[0][:50]  # JSON dump emas
