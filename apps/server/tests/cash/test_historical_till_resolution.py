# -*- coding: utf-8 -*-
"""HISTORICAL TILL RESOLUTION — retroaktiv TILL taxmini BO'LMASLIGI testlari (real PostgreSQL).

ARXITEKTURA QOIDASI:
    BUGUN yaratilgan ACTIVE TILL — o'tmishdagi tranzaksiya AYNAN o'sha fizik drawer'da bo'lganini
    ISBOTLAMAYDI.  CURRENT TILL PROVISIONING != HISTORICAL TILL EVIDENCE.
Legacy qator uchun TILL FAQAT deterministik TARIXIY dalil bilan hal qilinadi (source.till_id /
source.shift_id->Shift.till_id / tarixiy terminal->TILL / soya->smena->till / explicit historical
mapping). Dalil yo'q -> HISTORICAL_TILL_UNKNOWN (skip + REVIEW), account O'YLAB TOPILMAYDI.

A dalilsiz CustomerPayment, 0 ACTIVE TILL           -> HISTORICAL_TILL_UNKNOWN
B AYNI qator + BUGUN 1 ACTIVE TILL yaratildi        -> HAMON HISTORICAL_TILL_UNKNOWN  (KRITIK)
C dalilsiz SupplierPayment (shift-less)             -> HISTORICAL_TILL_UNKNOWN
D dalilsiz Return                                    -> HISTORICAL_TILL_UNKNOWN
E Shift.till_id dalili                               -> ANIQ TILL (SHIFT_TILL)
F manba till_id dalili                               -> ANIQ TILL (SOURCE_TILL)
G terminal MUTABLE binding                           -> UNKNOWN (KRITIK, §4)
I branch'da 2 ta ACTIVE TILL, dalil yo'q             -> TAXMIN YO'Q
J explicit source/shift mapping                      -> FAQAT mapped qator
M/N noto'g'ri tenant / filial attestatsiyasi          -> BLOCK / RAD
O ARCHIVED drawer                                    -> tarixan HAQIQIY (hal bo'ladi)
P TILL rename                                        -> tarixiy id barqaror
I post-T0 runtime: ACTIVE TILL bilan ishlayveradi    -> runtime readiness buzilmadi
J branch'da TILL yo'q -> runtime readiness signali, TARIXIY bloker EMAS
K idempotentlik / biznes-kalit regressiyasi yo'q
L probe endi "TILL yaratib qayta run qil" DEMAYDI (dalilsiz legacy uchun)
+ source.till_id dalili, soya->smena dalili, oddiy --mapping tarixiy dalil sifatida RAD etiladi
"""
from __future__ import annotations

import json as _json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.cash.migration import backfill, historical_till as HT
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.customers import Customer, CustomerPayment
from app.models.enums import CashMovementType as CMT, ShiftStatus
from app.models.org import Branch, Company, Terminal
from app.models.purchasing import Supplier, SupplierPayment
from app.models.sales import Return
from app.models.shifts import CashMovement, Shift
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _past(days=200):
    return _now() - timedelta(days=days)


def _co(db):
    c = Company(name="HT" + _hex(), code="ht" + _hex(), currency="UZS"); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F" + _hex(), is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, branch=None):
    e = Employee(company_id=co.id, full_name="K" + _hex(), role_id=db.query(Role).first().id)
    db.add(e); db.flush()
    if branch is not None:
        db.add(EmployeeBranch(employee_id=e.id, branch_id=branch.id)); db.flush()
    return e


def _till(db, co, br, terminal=None, status="ACTIVE"):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status=status,
                    label=_ti.till_label("T-" + _hex(), terminal), created_at=_now())
    db.add(a); db.flush(); return a


def _shift(db, br, emp, till=None, terminal=None):
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_past(), closed_at=_past() - timedelta(hours=-2),
               opening_cash=Decimal("0"), status=ShiftStatus.closed,
               till_id=(till.id if till else None), terminal_id=terminal)
    db.add(sh); db.flush(); return sh


def _term(db, br):
    t = Terminal(branch_id=br.id, name="K" + _hex(), is_active=True); db.add(t); db.flush(); return t


def _cust(db, co):
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="A", credit_balance=Decimal("0"))
    db.add(cu); db.flush(); return cu


def _custpay(db, cust, amt, emp, branch=None, when=None):
    when = when or _past()
    p = CustomerPayment(customer_id=cust.id, amount=Decimal(str(amt)), method="cash", paid_at=when,
                        created_at=when, employee_id=emp.id, branch_id=(branch.id if branch else None))
    db.add(p); db.flush(); return p


def _suppay(db, co, amt, emp, name="S"):
    sup = Supplier(company_id=co.id, name=name); db.add(sup); db.flush()
    p = SupplierPayment(supplier_id=sup.id, amount=Decimal(str(amt)), method="cash", paid_at=_past(),
                        created_at=_past(), employee_id=emp.id)
    db.add(p); db.flush(); return p


def _ret(db, co, br, emp, amt, *, till=None, shift=None, terminal=None):
    r = Return(return_no="RET" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
               refund_method="cash", total=Decimal(str(amt)), created_at=_past(),
               till_id=(till.id if till else None), shift_id=(shift.id if shift else None),
               terminal_id=terminal)
    db.add(r); db.flush(); return r


def _shadow(db, shift, mtype, amt, reason, emp, when=None):
    # PRODUKSIYA: soya manba qatori bilan BITTA tranzaksiyada, AYNI now bilan yoziladi
    # (customers.py / purchases.py). Identity ana shu vaqt tengligiga tayanadi.
    m = CashMovement(shift_id=shift.id, type=mtype, amount=Decimal(str(amt)), reason=reason,
                     client_uuid=None, employee_id=emp.id, created_at=(when or _past()))
    db.add(m); db.flush(); return m


def _leg(co, br, src_type, src_id, amt, *, terminal_id=None, shift_id=None, till_id=None, occurred=None):
    return {"tenant_id": str(co.id), "branch_id": (str(br.id) if br else None),
            "terminal_id": (str(terminal_id) if terminal_id else None),
            "shift_id": (str(shift_id) if shift_id else None),
            "till_id": (str(till_id) if till_id else None),
            "source_type": src_type, "source_id": str(src_id), "amount": float(amt),
            "device_occurred_at": (occurred or _past()).isoformat()}


def _resolve(db, co, leg, hist=None):
    ctx = backfill._build_context(db, co.id)
    return backfill.resolve_account(db, leg, ctx, historical_map=hist)


# ═══ A) dalilsiz CustomerPayment, TILL umuman yo'q ═══════════════════════════
def test_A_evidenceless_customer_no_till_is_historical_unknown(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    p = _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()
    acc, info = _resolve(db, co, _leg(co, br, "CUSTOMER_PAYMENT", p.id, 3000))
    assert acc is None
    assert info[0] == "REVIEW" and info[2] == HT.HISTORICAL_TILL_UNKNOWN
    # §1: sabab matni AYNAN talab qilingan shaklda
    assert "deterministic historical TILL evidence absent" in info[1]
    assert "current TILL provisioning is not historical evidence" in info[1]


# ═══ B) KRITIK: BUGUN TILL yaratish o'tmishni HAL QILMAYDI ═══════════════════
def test_B_new_till_today_must_not_resolve_evidenceless_historical_row(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    p = _custpay(db, _cust(db, co), 3000, emp, branch=br)   # shift/till/terminal YO'Q
    _till(db, co, br)                                        # operator BUGUN bitta TILL yaratdi
    db.commit()
    acc, info = _resolve(db, co, _leg(co, br, "CUSTOMER_PAYMENT", p.id, 3000))
    assert acc is None, ("RETROAKTIV TAXMIN: bugungi TILL dalilsiz tarixiy qatorga biriktirildi "
                         f"({info!r}) — CURRENT TILL != HISTORICAL EVIDENCE")
    assert info[2] == HT.HISTORICAL_TILL_UNKNOWN


# ═══ C) dalilsiz SupplierPayment (shift-less, single-branch tenant) ══════════
def test_C_evidenceless_supplier_single_branch_tenant_no_guess(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)   # tenant'da BITTA faol branch
    p = _suppay(db, co, 5000, emp)
    _till(db, co, br)                                        # va BITTA ACTIVE TILL
    db.commit()
    acc, info = _resolve(db, co, _leg(co, None, "SUPPLIER_PAYMENT", p.id, 5000))
    assert acc is None, "single-branch + single-till taxmini SAQLANIB QOLGAN"
    assert info[2] == HT.HISTORICAL_TILL_UNKNOWN


# ═══ D) dalilsiz Return ═════════════════════════════════════════════════════
def test_D_evidenceless_return_is_historical_unknown(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    r = _ret(db, co, br, emp, 4000)                           # till/shift/terminal YO'Q
    _till(db, co, br); db.commit()
    acc, info = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000))
    assert acc is None and info[2] == HT.HISTORICAL_TILL_UNKNOWN


# ═══ E) Shift.till_id dalili -> ANIQ TILL ═══════════════════════════════════
def test_E_shift_till_id_resolves_exactly(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    sh = _shift(db, br, emp, till=till)                       # smena o'sha paytda till_id yozgan
    r = _ret(db, co, br, emp, 4000, shift=sh)
    db.commit()
    acc, rule = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000, shift_id=sh.id))
    assert acc is not None and acc.id == till.id and rule == HT.RULE_SHIFT_TILL


# ═══ E2) manba qatorining O'Z till_id dalili ════════════════════════════════
def test_E2_source_till_id_resolves_exactly(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    r = _ret(db, co, br, emp, 4000, till=till)
    db.commit()
    acc, rule = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000, till_id=till.id))
    assert acc is not None and acc.id == till.id and rule == HT.RULE_SOURCE_TILL


# ═══ G) terminal MUTABLE binding -> UNKNOWN (KRITIK, §4) ════════════════════
def test_G_terminal_only_mutable_binding_is_not_evidence(db, cashenv):
    """§4: terminal->TILL bog'lanishi `cash_accounts.label` MUTABLE satrida (PATCH /tills uni qayta
    yozadi; DB guard faqat tenant/branch/type/currency/id ni himoya qiladi; versiyalangan tarix YO'Q).
    Demak tarixiy terminal_id -> BUGUNGI TILL dalil EMAS: terminal keyin boshqa drawer'ga ko'chsa,
    eski qator NOTO'G'RI drawer'ga tushardi."""
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    term = _term(db, br).id
    _till(db, co, br, terminal=term)                          # BUGUNGI binding (mutable)
    r = _ret(db, co, br, emp, 4000, terminal=term)            # till_id/shift_id YO'Q, faqat terminal
    db.commit()
    acc, info = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000, terminal_id=term))
    assert acc is None, f"terminal YOLG'IZ O'ZI dalil sifatida qabul qilindi ({info!r})"
    assert info[2] == HT.HISTORICAL_TILL_UNKNOWN
    assert HT.TERMINAL_EVIDENCE_SUPPORTED is False


# ═══ F2) soya -> smena -> till_id dalili ════════════════════════════════════
def test_F2_shadow_shift_till_resolves(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    sh = _shift(db, br, emp, till=till)
    t = _past(150)
    p = _custpay(db, _cust(db, co), 3000, emp, branch=None, when=t)   # branch yo'q
    _shadow(db, sh, CMT.payin, 3000, "Qarz to'lovi · A", emp, when=t)  # ZAMONDOSH soya (AYNI vaqt)
    db.commit()
    acc, rule = _resolve(db, co, _leg(co, None, "CUSTOMER_PAYMENT", p.id, 3000, occurred=t))
    assert acc is not None and acc.id == till.id and rule == HT.RULE_SHADOW_SHIFT


# ═══ F3) BOSHQA to'lovning soyasi dalil EMAS (review CRITICAL regressiya testi) ═
def test_F3_other_payments_shadow_is_not_evidence(db, cashenv):
    """§HIST-REVIEW: (tenant+tur+prefiks+summa+xodim) mosligi YETARLI EMAS. Keyinroq, BOSHQA
    filialda, provisioning'dan KEYIN qilingan BOSHQA to'lovning soyasi eski qatorga uning BUGUNGI
    till_id'sini bermasligi kerak — aks holda retroaktiv taxmin qayta ochilardi."""
    co = _co(db); brA = _br(db, co); brB = _br(db, co); emp = _emp(db, co)
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=brA.id))
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=brB.id)); db.flush()
    old = _past(400)
    p_old = _custpay(db, _cust(db, co), 50000, emp, branch=brA, when=old)   # 2024, filial A, SOYASIZ
    till_b = _till(db, co, brB)                                             # BUGUN B'da drawer ochildi
    sh_b = _shift(db, brB, emp, till=till_b)
    _shadow(db, sh_b, CMT.payin, 50000, "Qarz to'lovi · Boshqa", emp, when=_now())  # BOSHQA to'lov
    db.commit()
    acc, info = _resolve(db, co, _leg(co, brA, "CUSTOMER_PAYMENT", p_old.id, 50000, occurred=old))
    assert acc is None, f"boshqa to'lovning soyasi DALIL sifatida qabul qilindi ({info!r})"
    assert info[2] == HT.HISTORICAL_TILL_UNKNOWN


# ═══ G) ko'p ACTIVE TILL + dalil yo'q -> TAXMIN YO'Q ════════════════════════
def test_G_two_active_tills_no_guess(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br); _till(db, co, br)
    p = _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()
    acc, info = _resolve(db, co, _leg(co, br, "CUSTOMER_PAYMENT", p.id, 3000))
    assert acc is None and info[2] == HT.HISTORICAL_TILL_UNKNOWN


# ═══ J) explicit exact source mapping -> FAQAT mapped qator ════════════════
def test_J_explicit_source_mapping_resolves_only_mapped_row(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    p1 = _custpay(db, _cust(db, co), 3000, emp, branch=br)
    p2 = _custpay(db, _cust(db, co), 7000, emp, branch=br)
    db.commit()
    hist = HT.load_historical_map({
        "kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "operator",
        "sources": {f"CUSTOMER_PAYMENT:{p1.id}": str(till.id)}})
    acc1, rule1 = _resolve(db, co, _leg(co, br, "CUSTOMER_PAYMENT", p1.id, 3000), hist)
    assert acc1 is not None and acc1.id == till.id and rule1 == HT.RULE_OP_SOURCE_MAP
    acc2, info2 = _resolve(db, co, _leg(co, br, "CUSTOMER_PAYMENT", p2.id, 7000), hist)
    assert acc2 is None and info2[2] == HT.HISTORICAL_TILL_UNKNOWN   # mapping FAQAT p1 uchun


# ═══ J2) explicit SHIFT mapping ════════════════════════════════════════════
def test_J2_explicit_shift_mapping_resolves(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    sh = _shift(db, br, emp)                                   # smenada till_id YO'Q
    r = _ret(db, co, br, emp, 4000, shift=sh)
    db.commit()
    acc0, info0 = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000, shift_id=sh.id))
    assert acc0 is None and info0[2] == HT.HISTORICAL_TILL_UNKNOWN   # attestatsiyasiz -> noma'lum
    hist = HT.load_historical_map({
        "kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "operator",
        "shifts": {str(sh.id): str(till.id)}})
    acc, rule = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000, shift_id=sh.id), hist)
    assert acc is not None and acc.id == till.id and rule == HT.RULE_OP_SHIFT_MAP


# ═══ M/N) noto'g'ri tenant / noto'g'ri filial attestatsiyasi RAD ETILADI ════
def test_M_wrong_tenant_mapping_blocked(db, cashenv):
    coA = _co(db); brA = _br(db, coA); empA = _emp(db, coA, brA)
    coB = _co(db); brB = _br(db, coB); till_b = _till(db, coB, brB)      # BOSHQA tenant drawer'i
    p = _custpay(db, _cust(db, coA), 3000, empA, branch=brA)
    db.commit()
    hist = HT.load_historical_map({
        "kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "op",
        "sources": {f"CUSTOMER_PAYMENT:{p.id}": str(till_b.id)}})
    acc, info = _resolve(db, coA, _leg(coA, brA, "CUSTOMER_PAYMENT", p.id, 3000), hist)
    assert acc is None and info[0] == "BLOCK" and "cross-tenant" in info[1]


def test_N_wrong_branch_till_rejected(db, cashenv):
    co = _co(db); br1 = _br(db, co); br2 = _br(db, co)
    emp = _emp(db, co, br1)
    till2 = _till(db, co, br2)                                  # BOSHQA filial drawer'i
    p = _custpay(db, _cust(db, co), 3000, emp, branch=br1)
    db.commit()
    hist = HT.load_historical_map({
        "kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "op",
        "sources": {f"CUSTOMER_PAYMENT:{p.id}": str(till2.id)}})
    acc, info = _resolve(db, co, _leg(co, br1, "CUSTOMER_PAYMENT", p.id, 3000), hist)
    assert acc is None and "filial" in info[1]                  # noto'g'ri filial -> RAD


# ═══ O) ARCHIVED drawer tarixan HAQIQIY — bugungi deaktivatsiya tarixni buzmasin ═
def test_O_archived_till_still_resolves_for_history(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br, status="ARCHIVED")                 # BUGUN nafaqada
    sh = _shift(db, br, emp, till=till)
    r = _ret(db, co, br, emp, 4000, shift=sh)
    db.commit()
    acc, rule = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000, shift_id=sh.id))
    assert acc is not None and acc.id == till.id and rule == HT.RULE_SHIFT_TILL
    assert acc.status == "ARCHIVED"     # tarixiy resolution ACTIVE TALAB QILMAYDI


# ═══ P) TILL bugun RENAME qilinsa ham tarixiy id barqaror ══════════════════
def test_P_till_rename_does_not_break_historical_resolution(db, cashenv):
    from app.services.cash import till_identity as _t
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    sh = _shift(db, br, emp, till=till)
    r = _ret(db, co, br, emp, 4000, shift=sh)
    db.commit()
    till.label = _t.till_label("YANGI-NOM", None)               # BUGUN nomi o'zgardi
    db.add(till); db.commit()
    acc, rule = _resolve(db, co, _leg(co, br, "RETURN", r.id, 4000, shift_id=sh.id))
    assert acc is not None and acc.id == till.id and rule == HT.RULE_SHIFT_TILL   # id barqaror


# ═══ H3) oddiy --mapping fayli TARIXIY dalil sifatida RAD etiladi ══════════
def test_H3_current_mapping_file_rejected_as_historical_evidence(db, cashenv):
    current_mapping = {"branches": {str(uuid.uuid4()): {"safe": True, "tills": [{"code": "TILL-01"}]}}}
    with pytest.raises(ValueError, match="kind"):
        HT.load_historical_map(current_mapping)
    with pytest.raises(ValueError, match="attested_by"):
        HT.load_historical_map({"kind": "HISTORICAL_TILL_EVIDENCE", "version": 1,
                                "sources": {f"RETURN:{uuid.uuid4()}": str(uuid.uuid4())}})
    with pytest.raises(ValueError, match="BO'SH"):        # bo'sh attestatsiya = attestatsiya emas
        HT.load_historical_map({"kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "op"})
    for bad in ([1, 2, 3], 12345, {"kind": "HISTORICAL_TILL_EVIDENCE", "version": "abc",
                                   "attested_by": "o"}):
        with pytest.raises(ValueError):                   # buzuq kirish -> TOZA ValueError
            HT.load_historical_map(bad)


# ═══ I) RUNTIME (post-T0) ACTIVE TILL bilan ishlayveradi ════════════════════
def test_I_runtime_current_till_readiness_unaffected(db, cashenv):
    co = _co(db); br = _br(db, co); _emp(db, co, br)
    ctx0 = backfill._build_context(db, co.id)
    assert backfill.current_till_readiness(ctx0, br.id) == HT.CURRENT_TILL_NOT_PROVISIONED
    _till(db, co, br); db.commit()
    ctx1 = backfill._build_context(db, co.id)
    assert backfill.current_till_readiness(ctx1, br.id) is None      # runtime TAYYOR
    assert _ti.resolve_till_exact(db, co.id, br.id) is not None      # runtime yo'li buzilmadi


# ═══ J) TILLsiz branch: runtime signali, TARIXIY bloker EMAS ════════════════
def test_J_no_current_till_is_runtime_signal_not_historical_blocker(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()
    m = backfill.execute_backfill(db, company_id=co.id, apply=False)
    assert m["go_no_go"] == "GO"                                     # GLOBAL BLOKER EMAS
    assert not m["blocked"]                                          # BLOCK emas
    assert any(r.get("evidence_class") == HT.HISTORICAL_TILL_UNKNOWN for r in m["review"])
    ctx = backfill._build_context(db, co.id)
    assert backfill.current_till_readiness(ctx, br.id) == HT.CURRENT_TILL_NOT_PROVISIONED  # ALOHIDA signal


# ═══ K) dalilli qator: yoziladi + idempotent (biznes-kalit regressiyasi yo'q) ═
def test_K_evidenced_row_writes_and_is_idempotent(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br)
    sh = _shift(db, br, emp, till=till)
    _ret(db, co, br, emp, 4000, shift=sh)                            # SHIFT_TILL_ID dalili
    db.commit()
    m1 = backfill.execute_backfill(db, company_id=co.id, apply=True)
    n1 = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "REFUND").count()
    assert n1 == 1 and m1["inserted_rows"] >= 1
    leg = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "REFUND").one()
    assert leg.cash_account_id == till.id                            # AYNAN dalildagi drawer
    assert "till_evidence=" in (leg.reconstruction_reason or "")     # dalil QOIDASI ledger'da
    m2 = backfill.execute_backfill(db, company_id=co.id, apply=True)  # RERUN
    assert db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "REFUND").count() == 1
    assert m2["inserted_rows"] == 0                                  # dublikat YO'Q


# ═══ L) probe: dalilsiz legacy uchun "TILL yaratib qayta run qil" DEMAYDI ═══
def test_L_probe_reports_historical_unknown_not_provision_instruction(db, cashenv):
    import contextlib
    import io
    from sqlalchemy.orm import Session
    from app.tools import cash_reconcile_probe as probe
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br)                                                # BUGUN TILL bor
    _custpay(db, _cust(db, co), 3000, emp, branch=br); db.commit()   # lekin dalil YO'Q
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        probe.main(["--json"], session_factory=(lambda: Session(cashenv.engine)), engine=cashenv.engine)
    out = buf.getvalue()
    rep = _json.loads(out[out.index("{"):out.rindex("}") + 1])
    blk = next(x for x in rep["companies"] if x["company_id"] == str(co.id))["customer_payment"]
    r = blk["rows"][0]
    assert r["classification"] == "HISTORICAL_TILL_UNKNOWN"
    assert r["backfill_eligible"] is False
    assert r["current_till_provisioned"] is True                     # runtime TAYYOR, lekin tarix NOMA'LUM
    assert blk["summary"]["historical_till_unknown"] == 1
    assert "operator provisions TILL, re-run" not in out             # ESKI noto'g'ri ko'rsatma YO'Q


# ═══ Q) SOURCE-SCAN: tarixiy resolution yo'lida retroaktiv fallback QOLMAGAN ═
def test_Q_no_retroactive_fallback_in_historical_path():
    """§2/§13: tarixiy resolution modullarining BAJARILADIGAN kodida (docstring/izohlarsiz)
    joriy holatdan taxmin qiluvchi naqshlar BO'LMASLIGI kerak. Runtime yo'lida qolishi mumkin,
    lekin tarixiy yo'l bilan ARALASHMASIN."""
    import ast
    import pathlib

    def code_only(path):
        """Docstring'larni (proza) olib tashlab FAQAT bajariladigan kodni qaytaradi — aks holda
        'bu naqsh TAQIQLANGAN' deb yozilgan izohning o'zi skanerga tushardi."""
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        for node in ast.walk(tree):
            if not isinstance(node, holders):
                continue
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
        return ast.unparse(tree)

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "db" / "cash" / "migration"
    forbidden = ("single-checkout", "single_checkout", "first active", "first_active",
                 "branch_default", "cashier_default", ".first()")
    for name in ("historical_till.py", "backfill.py"):
        src = code_only(root / name)
        for bad in forbidden:
            assert bad not in src, f"{name} tarixiy yo'lida taqiqlangan naqsh: {bad!r}"
    # terminal qoidasi ATAYLAB yo'q
    assert HT.TERMINAL_EVIDENCE_SUPPORTED is False
    assert not hasattr(HT, "RULE_TERMINAL")
    # yakuniy ierarxiya AYNAN 5 qoida
    assert HT.RULE_ORDER == ("SOURCE_TILL", "SHIFT_TILL", "SHADOW_SHIFT_TILL",
                             "OPERATOR_SOURCE_MAP", "OPERATOR_SHIFT_MAP")


# ═══ R) uchta AJRALGAN tushuncha (§11) ══════════════════════════════════════
def test_R_three_distinct_concepts_are_separate():
    """HISTORICAL_TILL_UNKNOWN (tarixiy identity) != CURRENT_TILL_NOT_PROVISIONED (runtime readiness).
    Uchinchisi — post-T0 runtime rad etish — cutover qatlamida (alohida)."""
    assert HT.HISTORICAL_TILL_UNKNOWN != HT.CURRENT_TILL_NOT_PROVISIONED
    assert HT.HISTORICAL_TILL_UNKNOWN == "HISTORICAL_TILL_UNKNOWN"
    assert HT.CURRENT_TILL_NOT_PROVISIONED == "CURRENT_TILL_NOT_PROVISIONED"
