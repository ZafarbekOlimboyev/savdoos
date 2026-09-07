# -*- coding: utf-8 -*-
"""PRE-T0 CURRENT RUNTIME READINESS testlari (real PostgreSQL).

ASOSIY QOIDA: HISTORICAL_TILL_UNKNOWN YOLG'IZ O'ZI cutover BLOKERI EMAS.
Uchta tushuncha ajratilgan: tarixiy identity / joriy runtime tayyorligi / post-T0 runtime rad etish.

A dalilsiz tarixiy qatorlar cutover tayyorligini BLOKLAMAYDI
B filialda ACTIVE TILL yo'q            -> CURRENT_RUNTIME_NOT_READY
C joriy TILL yaratilsa runtime tayyor, LEKIN tarixiy qator HAMON UNKNOWN
D till_id=NULL ochiq legacy smena      -> CURRENT_RUNTIME_NOT_READY
E legacy smena yopilsa + TILL bor      -> CUTOVER_READY
F T0'dan keyin TILL qo'shish migratsiya TALAB QILMAYDI
G tarixiy unknown soni hisobotda KO'RINADI
H vaqt-oynali mapping wording QOLMAGAN
I kompaniyalararo IZOLYATSIYA (per-company cutover)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db.cash.migration import runtime_readiness as RR
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.customers import Customer, CustomerPayment
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.shifts import Shift
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _co(db):
    c = Company(name="RD" + _hex(), code="rd" + _hex(), currency="UZS"); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, br):
    e = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(e); db.flush(); db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush(); return e


def _till(db, co, br):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                    label=_ti.till_label("T-" + _hex(), None), created_at=_now())
    db.add(a); db.flush(); return a


def _open_shift(db, br, emp, till=None):
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(hours=2),
               opening_cash=Decimal("0"), status=ShiftStatus.open,
               till_id=(till.id if till else None))
    db.add(sh); db.flush(); return sh


def _legacy_unknown_payment(db, co, br, emp):
    """Dalilsiz tarixiy naqd qator (till/shift/terminal YO'Q) -> HISTORICAL_TILL_UNKNOWN."""
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="A", credit_balance=Decimal("0"))
    db.add(cu); db.flush()
    t = _now() - timedelta(days=200)
    p = CustomerPayment(customer_id=cu.id, amount=Decimal("3000"), method="cash", paid_at=t,
                        created_at=t, employee_id=emp.id, branch_id=br.id)
    db.add(p); db.flush(); return p


def _ev(db, co):
    return RR.evaluate(db, company_id=co.id)["per_company"][0]


# ═══ A) tarixiy noaniqlik cutover'ni BLOKLAMAYDI ════════════════════════════
def test_A_historical_unknown_alone_does_not_block_cutover(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br)                                   # joriy runtime TAYYOR
    _legacy_unknown_payment(db, co, br, emp)            # lekin tarixiy dalil YO'Q
    db.commit()
    r = _ev(db, co)
    assert r["historical_identity"]["historical_till_unknown"] >= 1
    assert r["historical_identity_status"] == RR.HISTORICAL_REVIEW
    assert r["historical_identity"]["blocking"] is False
    assert r["status"] == RR.CUTOVER_READY, f"tarixiy noaniqlik BLOKLADI: {r['runtime_blockers']}"


# ═══ B) ACTIVE TILL yo'q -> CURRENT_RUNTIME_NOT_READY ══════════════════════
def test_B_no_active_till_is_runtime_not_ready(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _legacy_unknown_payment(db, co, br, emp)            # TILL YARATILMADI
    db.commit()
    r = _ev(db, co)
    assert r["status"] == RR.CURRENT_RUNTIME_NOT_READY
    codes = [b["code"] for b in r["runtime_blockers"]]
    assert RR.R_NO_ACTIVE_TILL in codes
    assert r["branches_without_active_till"] == 1


# ═══ C) TILL yaratish runtime'ni tayyorlaydi, TARIXNI hal QILMAYDI ═════════
def test_C_creating_till_fixes_runtime_but_not_history(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _legacy_unknown_payment(db, co, br, emp); db.commit()
    before = _ev(db, co)
    assert before["status"] == RR.CURRENT_RUNTIME_NOT_READY
    hist_before = before["historical_identity"]["historical_till_unknown"]

    _till(db, co, br); db.commit()                      # operator BUGUN kassa yaratdi
    after = _ev(db, co)
    assert after["status"] == RR.CUTOVER_READY                       # runtime TAYYOR
    assert after["historical_identity"]["historical_till_unknown"] == hist_before   # TARIX O'ZGARMADI
    assert after["historical_identity_status"] == RR.HISTORICAL_REVIEW


# ═══ D) till_id=NULL ochiq legacy smena -> runtime tayyor EMAS ═════════════
def test_D_untilled_open_legacy_shift_is_runtime_not_ready(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br)                                   # TILL bor
    _open_shift(db, br, emp, till=None)                 # lekin ochiq smena TILL'siz
    db.commit()
    r = _ev(db, co)
    assert r["status"] == RR.CURRENT_RUNTIME_NOT_READY
    assert RR.R_OPEN_SHIFT_NO_TILL in [b["code"] for b in r["runtime_blockers"]]
    assert r["legacy_open_shifts_without_till"] == 1


# ═══ E) smena yopilsa + TILL bor -> CUTOVER_READY ══════════════════════════
def test_E_closing_legacy_shift_makes_ready(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br)
    sh = _open_shift(db, br, emp, till=None); db.commit()
    assert _ev(db, co)["status"] == RR.CURRENT_RUNTIME_NOT_READY
    sh.status = ShiftStatus.closed; sh.closed_at = _now(); db.add(sh); db.commit()
    r = _ev(db, co)
    assert r["status"] == RR.CUTOVER_READY
    assert r["legacy_open_shifts_without_till"] == 0


# ═══ F) T0'dan keyin TILL qo'shish migratsiya TALAB QILMAYDI ═══════════════
def test_F_adding_till_after_t0_needs_no_migration(db, cashenv):
    from app.models.settings import Setting
    co = _co(db); br1 = _br(db, co); _emp(db, co, br1)
    _till(db, co, br1)
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"cutover_at": (_now() - timedelta(days=1)).isoformat()}))
    db.commit()
    r0 = _ev(db, co)
    assert r0["cutover_enforcement"] == "ACTIVE" and r0["status"] == RR.CUTOVER_READY
    # T0'DAN KEYIN yangi filial + yangi kassa qo'shildi — DDL/migratsiya YO'Q, oddiy qator
    br2 = _br(db, co); db.commit()
    assert _ev(db, co)["status"] == RR.CURRENT_RUNTIME_NOT_READY      # yangi filial kassasiz
    _till(db, co, br2); db.commit()
    assert _ev(db, co)["status"] == RR.CUTOVER_READY                  # kassa qo'shildi -> tayyor


# ═══ G) tarixiy unknown soni hisobotda KO'RINADI ═══════════════════════════
def test_G_historical_unknown_count_is_visible(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br)
    _legacy_unknown_payment(db, co, br, emp)
    _legacy_unknown_payment(db, co, br, emp); db.commit()
    rep = RR.evaluate(db, company_id=co.id)
    assert rep["totals"]["historical_till_unknown_rows"] >= 2
    assert rep["totals"]["with_historical_review"] == 1
    assert rep["per_company"][0]["historical_identity"]["historical_till_unknown"] >= 2
    assert "T0 BU YERDA O'RNATILMAYDI" in rep["t0_note"]              # T0 SET qilinmaydi


# ═══ H) vaqt-oynali mapping wording QOLMAGAN ══════════════════════════════
def test_H_no_time_window_mapping_wording_remains():
    """RC10 semantikasi: historical map FAQAT aniq sources/shifts. Operator matnlarida
    'branch+vaqt-oynasi' TAKLIF qilinmasligi kerak (faqat INKOR qilinishi mumkin)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    for rel in ("tools/cash_reconcile_probe.py", "tools/cash_backfill.py",
                "db/cash/migration/historical_till.py"):
        txt = (root / rel).read_text(encoding="utf-8")
        for line in txt.splitlines():
            if "vaqt-oyna" in line.lower() or "branch+vaqt" in line.lower():
                low = line.lower()
                assert ("qo'llanmaydi" in low or "ataylab" in low or "emas" in low), \
                    f"{rel}: vaqt-oynali mapping HAMON taklif qilinmoqda -> {line.strip()}"


# ═══ I) kompaniyalararo IZOLYATSIYA (per-company cutover) ═════════════════
def test_I_per_company_isolation(db, cashenv):
    coA = _co(db); brA = _br(db, coA); empA = _emp(db, coA, brA)
    _till(db, coA, brA)                                  # A tayyor
    coB = _co(db); brB = _br(db, coB); _emp(db, coB, brB)  # B kassasiz
    _legacy_unknown_payment(db, coA, brA, empA)
    db.commit()
    rep = RR.evaluate(db)                                # BARCHA kompaniyalar
    a = next(p for p in rep["per_company"] if p["company_id"] == str(coA.id))
    b = next(p for p in rep["per_company"] if p["company_id"] == str(coB.id))
    assert a["status"] == RR.CUTOVER_READY                        # A alohida TAYYOR
    assert b["status"] == RR.CURRENT_RUNTIME_NOT_READY            # B alohida TAYYOR EMAS
    assert a["historical_identity"]["historical_till_unknown"] >= 1
    assert b["historical_identity"]["historical_till_unknown"] == 0   # A'ning tarixi B'ga sizmadi


# ═══ J) READ-ONLY: hech narsa yozilmaydi (cutover SET emas, TILL yaratilmaydi) ═
def test_J_read_only(db, cashenv):
    from app.models.settings import Setting
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br); _legacy_unknown_payment(db, co, br, emp); db.commit()
    n_acc = db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count()
    n_set = db.query(Setting).filter(Setting.company_id == co.id).count()
    n_sh = db.query(Shift).join(Branch, Branch.id == Shift.branch_id).filter(
        Branch.company_id == co.id).count()
    RR.evaluate(db, company_id=co.id)
    assert db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count() == n_acc
    assert db.query(Setting).filter(Setting.company_id == co.id).count() == n_set
    assert db.query(Shift).join(Branch, Branch.id == Shift.branch_id).filter(
        Branch.company_id == co.id).count() == n_sh
