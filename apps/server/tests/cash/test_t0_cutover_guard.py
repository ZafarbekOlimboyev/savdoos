# -*- coding: utf-8 -*-
"""T0 CUTOVER GUARD — post-T0 fizik naqd amallari uchun markaziy darvoza (real PostgreSQL).

QOIDA: T0'dan keyin HECH QANDAY fizik naqd mutatsiya AYNAN TILL'siz o'tmasin. TAXMIN YO'Q.

A pre-T0 legacy smena (till=NULL) naqd amali RUXSAT (legacy moslik)
B AYNI smena T0'ni kesib o'tadi -> RAD (LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER)
C/D/E/F post-T0 sale / refund / shift-cash / cash-op -> RAD
G post-T0 aniq ACTIVE TILL bilan -> RUXSAT
I ARCHIVED TILL -> RAD          J noto'g'ri filial -> RAD        K noto'g'ri tenant -> RAD
L offline: T0'dan OLDIN sodir + keyin sinxron -> RUXSAT (till TAXMIN QILINMAYDI)
M offline: T0'dan KEYIN sodir, till yo'q -> RAD
M2 offline: vaqt ISBOTLANMAGAN -> XAVFSIZ tomonga RAD
N offline: post-T0 aniq till bilan -> RUXSAT
O filial/kassir/yagona-TILL fallback YO'Q
+ §18 manifest parity: P/Q/T/U/W
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.cash.migration import backfill, historical_till as HT, preflight as pf
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.customers import Customer, CustomerPayment
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.models.shifts import Shift
from app.services.cash import cutover_guard as CG
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _co(db):
    c = Company(name="CG" + _hex(), code="cg" + _hex(), currency="UZS"); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, br):
    e = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(e); db.flush(); db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush(); return e


def _till(db, co, br, status="ACTIVE"):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status=status,
                    label=_ti.till_label("T-" + _hex(), None), created_at=_now())
    db.add(a); db.flush(); return a


def _shift(db, br, emp, till=None, opened=None):
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=(opened or _now() - timedelta(hours=3)),
               opening_cash=Decimal("0"), status=ShiftStatus.open,
               till_id=(till.id if till else None))
    db.add(sh); db.flush(); return sh


def _set_t0(db, co, when):
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"cutover_at": when.isoformat()})); db.flush()


def _guard(db, co, br, *, shift=None, till_id=None, op="cash_op", occ=None, proven=True):
    return CG.require_post_t0_till(db, company_id=co.id, branch_id=br.id if br else None,
                                   operation=op, shift=shift, till_id=till_id,
                                   occurred_at=occ, occurred_at_proven=proven)


# ═══ A) PRE-T0: legacy smena (till=NULL) naqd amali RUXSAT ══════════════════
def test_A_pre_t0_legacy_untilled_shift_allowed(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, br, emp, till=None)                 # T0 belgilanmagan
    db.commit()
    acc, enforced = _guard(db, co, br, shift=sh)
    assert acc is None and enforced is False            # legacy moslik


# ═══ B) AYNI smena T0'ni kesib o'tdi -> QAT'IY RAD ═════════════════════════
def test_B_legacy_shift_crossing_t0_is_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, br, emp, till=None, opened=_now() - timedelta(days=2))
    _set_t0(db, co, _now() - timedelta(days=1))          # T0 smenadan KEYIN keldi
    db.commit()
    with pytest.raises(HTTPException) as ei:
        CG.cutover_open_shift_gate(db, company_id=co.id, shift=sh, operation="cash_op")
    assert CG.ERR_LEGACY_SHIFT_NEEDS_TILL in str(ei.value.detail)
    assert ei.value.status_code == 400


# ═══ C/D/E/F) post-T0 sale / refund / shift-cash / cash-op -> RAD ══════════
@pytest.mark.parametrize("op", ["cash_sale", "cash_refund", "cash:payout", "cash_op:expense"])
def test_CDEF_post_t0_operations_rejected_on_untilled_shift(db, cashenv, op):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    sh = _shift(db, br, emp, till=None)
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    with pytest.raises(HTTPException) as ei:
        _guard(db, co, br, shift=sh, op=op)
    assert CG.ERR_LEGACY_SHIFT_NEEDS_TILL in str(ei.value.detail)


# ═══ G) post-T0 aniq ACTIVE TILL -> RUXSAT ═════════════════════════════════
def test_G_post_t0_with_exact_active_till_succeeds(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    sh = _shift(db, br, emp, till=till)
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    acc, enforced = _guard(db, co, br, shift=sh, op="cash_sale")
    assert enforced is True and acc is not None and acc.id == till.id


# ═══ H) refund boshqa HAQIQIY joriy TILL'dan -> RUXSAT (asl sotuv TILL'i shart emas) ═
def test_H_refund_from_a_different_valid_current_till(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br)                                    # asl sotuv kassasi
    till_b = _till(db, co, br)                           # boshqa haqiqiy joriy kassa
    sh = _shift(db, br, emp, till=till_b)
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    acc, enforced = _guard(db, co, br, shift=sh, till_id=till_b.id, op="cash_refund")
    assert enforced is True and acc.id == till_b.id      # refund TILL avtoritet


# ═══ I) ARCHIVED TILL joriy runtime uchun RAD ══════════════════════════════
def test_I_archived_till_rejected_for_runtime(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    arch = _till(db, co, br, status="ARCHIVED")
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    with pytest.raises(HTTPException) as ei:
        _guard(db, co, br, till_id=arch.id, op="cash_sale")
    assert CG.ERR_TILL_INVALID in str(ei.value.detail)


# ═══ J) noto'g'ri FILIAL TILL'i -> RAD ═════════════════════════════════════
def test_J_wrong_branch_till_rejected(db, cashenv):
    co = _co(db); br1 = _br(db, co); br2 = _br(db, co); _emp(db, co, br1)
    till2 = _till(db, co, br2)
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    with pytest.raises(HTTPException) as ei:
        _guard(db, co, br1, till_id=till2.id, op="cash_sale")
    assert CG.ERR_TILL_INVALID in str(ei.value.detail)


# ═══ K) noto'g'ri TENANT TILL'i -> RAD ═════════════════════════════════════
def test_K_wrong_tenant_till_rejected(db, cashenv):
    coA = _co(db); brA = _br(db, coA); _emp(db, coA, brA)
    coB = _co(db); brB = _br(db, coB); tillB = _till(db, coB, brB)
    _set_t0(db, coA, _now() - timedelta(hours=1)); db.commit()
    with pytest.raises(HTTPException) as ei:
        _guard(db, coA, brA, till_id=tillB.id, op="cash_sale")
    assert CG.ERR_TILL_INVALID in str(ei.value.detail)


# ═══ T) KRITIK (§6): post-T0 QABUL + sold_at pre-T0 + TILL yo'q -> RAD ═════
def test_T_post_t0_receipt_with_pre_t0_sold_at_and_no_till_rejected(db, cashenv):
    """§6 ARXITEKTURA O'ZGARISHI: klient `sold_at` majburlash qaroriga TA'SIR QILMAYDI.
    Ilgari pre-T0 sold_at legacy ozodlik berardi -> POS eski sana yozib T0'ni chetlab o'tardi."""
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    _till(db, co, br)                                    # filialda TILL bor (lekin TAXMIN QILINMAYDI)
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    pre_t0 = _now() - timedelta(days=3)                  # klient "T0'dan oldin sotildi" deydi
    with pytest.raises(HTTPException) as ei:
        _guard(db, co, br, op="offline_cash_sale", occ=pre_t0, proven=True)
    assert CG.ERR_TILL_REQUIRED in str(ei.value.detail)


# ═══ V) klient sold_at guard QARORINI O'ZGARTIRA OLMAYDI ══════════════════
def test_V_client_sold_at_cannot_change_guard_decision(db, cashenv):
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    till = _till(db, co, br)
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    for occ, proven in ((_now() - timedelta(days=30), True), (_now(), True), (None, False)):
        with pytest.raises(HTTPException):               # TILL'siz -> HAR DOIM rad
            _guard(db, co, br, op="offline_cash_sale", occ=occ, proven=proven)
        acc, enforced = _guard(db, co, br, till_id=till.id, op="offline_cash_sale",
                               occ=occ, proven=proven)   # aniq TILL -> HAR DOIM o'tadi
        assert enforced is True and acc.id == till.id


# ═══ W) PRE-T0 server qabuli legacy xatti-harakatni SAQLAYDI ══════════════
def test_W_pre_t0_server_acceptance_keeps_legacy_behaviour(db, cashenv):
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    _set_t0(db, co, _now() + timedelta(days=365)); db.commit()   # T0 hali KELMAGAN
    acc, enforced = _guard(db, co, br, op="cash_sale", occ=_now(), proven=True)
    assert enforced is False and acc is None


# ═══ M) offline: T0'DAN KEYIN sodir, TILL yo'q -> RAD ══════════════════════
def test_M_offline_event_after_t0_without_till_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    _till(db, co, br)
    _set_t0(db, co, _now() - timedelta(days=1)); db.commit()
    with pytest.raises(HTTPException) as ei:
        _guard(db, co, br, op="offline_cash_sale", occ=_now(), proven=True)
    assert CG.ERR_TILL_REQUIRED in str(ei.value.detail)


# ═══ M2) offline: vaqt ISBOTLANMAGAN -> XAVFSIZ tomonga RAD (pre-T0 deb hisoblamaydi) ═
def test_M2_offline_unproven_time_is_treated_as_post_t0(db, cashenv):
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    _till(db, co, br)
    _set_t0(db, co, _now() - timedelta(days=1)); db.commit()
    with pytest.raises(HTTPException) as ei:
        _guard(db, co, br, op="offline_cash_sale", occ=None, proven=False)
    assert CG.ERR_TILL_REQUIRED in str(ei.value.detail)


# ═══ N) offline: post-T0 ANIQ till bilan -> RUXSAT ═════════════════════════
def test_N_offline_post_t0_with_exact_till_succeeds(db, cashenv):
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    till = _till(db, co, br)
    _set_t0(db, co, _now() - timedelta(days=1)); db.commit()
    acc, enforced = _guard(db, co, br, till_id=till.id, op="offline_cash_sale",
                           occ=_now(), proven=True)
    assert enforced is True and acc.id == till.id


# ═══ O) filial / yagona-TILL / kassir FALLBACK YO'Q ════════════════════════
def test_O_no_branch_or_single_till_fallback(db, cashenv):
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    _till(db, co, br)                                    # filialda AYNAN BITTA ACTIVE TILL
    _set_t0(db, co, _now() - timedelta(hours=1)); db.commit()
    with pytest.raises(HTTPException) as ei:              # baribir TAXMIN QILINMAYDI
        _guard(db, co, br, shift=None, till_id=None, op="cash_sale")
    assert CG.ERR_TILL_REQUIRED in str(ei.value.detail)
    import inspect
    src = inspect.getsource(CG)
    for bad in ("single-checkout", "resolve_till_exact", "first()"):
        assert bad not in src, f"guard'da taxmin naqshi: {bad}"
    # DIQQAT (§4 topilma): yuqoridagi skan FAQAT cutover_guard modulini ko'radi va shu bois
    # KOMPOZITSIYALANGAN endpoint yo'lidagi fallback'ni USHLAY OLMAYDI — guard `till_id` ni
    # QAYTA RESOLVE qilmaydi, uni faqat VALIDATSIYA qiladi. Haqiqiy post-T0 qamrov
    # tests/cash/test_single_checkout_block.py (F-K) da: u endpointni chaqiradi.
    from tests.cash import test_single_checkout_block as _sc
    assert hasattr(_sc, "test_F_post_t0_single_till_without_identity_is_rejected")


# ═══ §18 MANIFEST PARITY ═══════════════════════════════════════════════════
def _mini_tenant(db):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="A", credit_balance=Decimal("0"))
    db.add(cu); db.flush()
    t = _now() - timedelta(days=200)
    p = CustomerPayment(customer_id=cu.id, amount=Decimal("3000"), method="cash", paid_at=t,
                        created_at=t, employee_id=emp.id, branch_id=br.id)
    db.add(p); db.commit()
    return co, br, till, p


def _hmap(p, till):
    return {"kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "op",
            "sources": {f"CUSTOMER_PAYMENT:{p.id}": str(till.id)}}


# P/Q) backfill dry-run va preflight AYNI map bilan AYNI hash beradi
def test_PQ_backfill_and_preflight_produce_same_hash(db, cashenv):
    co, _br_, till, p = _mini_tenant(db)
    t0 = _now().isoformat()
    hm = _hmap(p, till)
    m = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False, historical_map=hm)
    g = pf.final_dry_run(db, cashenv.engine, company_id=co.id, t0=t0, git_sha="x", backup_id="b",
                         run_id="r", historical_map=hm, ack_historical_unknown=True)
    assert g["manifest"]["manifest_hash"] == m["manifest_hash"], "preflight/backfill hash DRIFT"


# U) attestatsiya o'zgarsa manifest hash O'ZGARADI
def test_U_changed_historical_map_changes_hash(db, cashenv):
    co, br, till, p = _mini_tenant(db)
    till2 = _till(db, co, br); db.commit()
    t0 = _now().isoformat()
    h1 = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False,
                                   historical_map=_hmap(p, till))["manifest_hash"]
    h2 = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False,
                                   historical_map=_hmap(p, till2))["manifest_hash"]
    h0 = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    assert h1 != h2 and h1 != h0 and h2 != h0


# T) map'siz verify AYNI rejani qayta hosil QILOLMAYDI -> hash farq qiladi (input mismatch)
def test_T_verify_without_map_cannot_reproduce_approved_plan(db, cashenv):
    co, _b, till, p = _mini_tenant(db)
    t0 = _now().isoformat()
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False,
                                         historical_map=_hmap(p, till))["manifest_hash"]
    without = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    assert approved != without, "map'siz qayta hisob AYNI hash berdi — mismatch aniqlanmaydi"


# V/W) aggregate ack skip qilingan TO'PLAMNI pinlaydi; to'plam o'zgarsa digest o'zgaradi
def test_VW_aggregate_ack_digest_pins_skipped_set(db, cashenv):
    co, br, _t, _p = _mini_tenant(db)
    emp = db.query(Employee).filter(Employee.company_id == co.id).first()
    t0 = _now().isoformat()
    d1 = backfill.execute_backfill(db, company_id=co.id, t0=t0,
                                   apply=False)["historical_unknown_ack_digest"]
    assert d1 != "none" and d1.startswith("1:")
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="B", credit_balance=Decimal("0"))
    db.add(cu); db.flush()
    tt = _now() - timedelta(days=150)
    db.add(CustomerPayment(customer_id=cu.id, amount=Decimal("9000"), method="cash", paid_at=tt,
                           created_at=tt, employee_id=emp.id, branch_id=br.id)); db.commit()
    d2 = backfill.execute_backfill(db, company_id=co.id, t0=t0,
                                   apply=False)["historical_unknown_ack_digest"]
    assert d2.startswith("2:") and d2 != d1        # yangi dalilsiz qator -> eski tasdiq YAROQSIZ
