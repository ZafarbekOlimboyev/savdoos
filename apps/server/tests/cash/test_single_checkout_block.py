# -*- coding: utf-8 -*-
"""§4 SINGLE-CHECKOUT — post-T0 EXACT CUSTODY (real PostgreSQL).

RATIFIKATSIYA: T0'dan KEYIN fizik naqd AYNAN identifikatsiyalangan custody talab qiladi.
Taqiqlangan: birinchi TILL · "bitta TILL bor" fallback · filial defaulti · kassir · o'zgaruvchan
terminal inference. T0'GACHA legacy moslik ATAYLAB saqlanadi.

F  post-T0: 1 ta ACTIVE TILL + identity YO'Q -> len(tills)==1 SABABLI MUVAFFAQIYAT BO'LMAYDI
G  post-T0: 2 ta ACTIVE TILL + identity YO'Q -> RAD
H  AYNAN TILL ko'rsatilsa (till_id yoki terminal) -> muvaffaqiyat
I  pre-T0 legacy xulq SAQLANADI (ATAYLAB)
J  ZID terminal dalili single-checkout bilan BOSIB KETILMAYDI (1 TILL bo'lsa ham)
K  resolver darajasidagi shartnoma (reason kodlari)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
import pytest

from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.org import Branch, Company, Terminal
from app.models.settings import Setting
from app.services.cash import retrofit as _cr
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _co(db):
    c = Company(name="SC" + _hex(), code="sc" + _hex(), currency="UZS")
    db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, br):
    e = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(e); db.flush(); db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush(); return e


def _till(db, co, br, code, terminal=None):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                    label=_ti.till_label(code, terminal.id if terminal else None), created_at=_now())
    db.add(a); db.flush(); return a


def _term(db, br):
    t = Terminal(branch_id=br.id, name="T" + _hex()); db.add(t); db.flush(); return t


def _set_t0(db, co, *, past=True):
    when = _now() - timedelta(days=1) if past else _now() + timedelta(days=365)
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"cutover_at": when.isoformat()}))
    db.flush()


def _open_shift(db, co, emp, br, **kw):
    """Haqiqiy endpoint orqali smena ochish (kompozitsiyalangan yo'lni sinaymiz, guardni EMAS)."""
    from app.api.v1.shifts import OpenShift, open_shift
    return open_shift(OpenShift(opening_cash=Decimal("0"), **kw), emp=emp, db=db)


# ═══ F) post-T0: 1 TILL + identity YO'Q -> single-checkout SABABLI o'tmaydi ══
def test_F_post_t0_single_till_without_identity_is_rejected(db, cashenv):
    """ASOSIY REGRESSIYA: ilgari resolve_till_id yagona TILL'ni qaytarardi, shu bois
    shifts.py dagi post-T0 guard (`_till_id is None`) HECH QACHON ishga tushmasdi."""
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br, "TILL-01")                      # AYNAN BITTA ACTIVE TILL
    _set_t0(db, co, past=True); db.commit()

    with pytest.raises(HTTPException) as ei:
        _open_shift(db, co, emp, br)                  # till_id YO'Q, terminal YO'Q
    assert ei.value.status_code == 400
    assert "AYNAN kassa" in ei.value.detail
    assert "AVTOMATIK tanlanmaydi" in ei.value.detail

    # resolver darajasida ham: post-T0 rejimida yagona TILL TANLANMAYDI
    acc, why = _ti.resolve_till_exact(db, co.id, br.id, allow_single_checkout=False)
    assert acc is None and why == _ti.BLOCKED_SINGLE_CHECKOUT


# ═══ G) post-T0: 2 TILL + identity YO'Q -> RAD ═════════════════════════════
def test_G_post_t0_two_tills_without_identity_is_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br, "TILL-01"); _till(db, co, br, "TILL-02")
    _set_t0(db, co, past=True); db.commit()

    with pytest.raises(HTTPException) as ei:
        _open_shift(db, co, emp, br)
    assert ei.value.status_code == 400
    acc, why = _ti.resolve_till_exact(db, co.id, br.id)
    assert acc is None and why == "ambiguous-no-terminal"


# ═══ H) AYNAN identity berilsa -> muvaffaqiyat ═════════════════════════════
def test_H_exact_identity_succeeds_post_t0(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _till(db, co, br, "TILL-01")
    term = _term(db, br); t2 = _till(db, co, br, "TILL-02", terminal=term)
    _set_t0(db, co, past=True); db.commit()

    # (i) klient AYNAN till_id yuboradi
    r1 = _open_shift(db, co, emp, br, till_id=t1.id)
    from app.models.shifts import Shift
    sh1 = db.get(Shift, uuid.UUID(r1["id"]) if isinstance(r1, dict) else r1.id)
    assert str(sh1.till_id) == str(t1.id)
    sh1.status = __import__("app.models.enums", fromlist=["x"]).ShiftStatus.closed
    sh1.closed_at = _now(); db.add(sh1); db.commit()

    # (ii) terminal moslik ham AYNAN dalil
    r2 = _open_shift(db, co, emp, br, terminal_id=term.id)
    sh2 = db.get(Shift, uuid.UUID(r2["id"]) if isinstance(r2, dict) else r2.id)
    assert str(sh2.till_id) == str(t2.id)


# ═══ I) pre-T0 legacy xulq ATAYLAB saqlanadi ═══════════════════════════════
def test_I_pre_t0_legacy_single_checkout_still_allowed(db, cashenv):
    """T0 O'RNATILMAGAN (yoki kelajakda) -> mavjud klientlar SINMAYDI."""
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br, "TILL-01"); db.commit()   # cutover_at YO'Q

    r = _open_shift(db, co, emp, br)                   # identity YO'Q — pre-T0 ruxsat
    from app.models.shifts import Shift
    sh = db.get(Shift, uuid.UUID(r["id"]) if isinstance(r, dict) else r.id)
    assert str(sh.till_id) == str(till.id)             # single-checkout ISHLADI (pre-T0)

    acc, why = _ti.resolve_till_exact(db, co.id, br.id)          # default: ruxsat
    assert acc is not None and why == _ti.SINGLE_CHECKOUT

    # kelajakdagi T0 ham "hali yetmagan" -> legacy
    co2 = _co(db); br2 = _br(db, co2); emp2 = _emp(db, co2, br2)
    _till(db, co2, br2, "TILL-01"); _set_t0(db, co2, past=False); db.commit()
    r2 = _open_shift(db, co2, emp2, br2)
    assert db.get(Shift, uuid.UUID(r2["id"]) if isinstance(r2, dict) else r2.id).till_id is not None


# ═══ J) ZID terminal dalili BOSIB KETILMAYDI ═══════════════════════════════
def test_J_contradicting_terminal_is_not_overridden_by_single_checkout(db, cashenv):
    """Ilgari `len(tills)==1` shoxobchasi terminal tekshiruvidan OLDIN qaytarardi: boshqa
    drawer'ning terminali bilan kelgan so'rov JIMGINA yagona TILL'ga bog'lanardi."""
    co = _co(db); br = _br(db, co)
    _till(db, co, br, "TILL-01")                       # terminalga BOG'LANMAGAN yagona TILL
    other = _term(db, br); db.commit()                 # mos kelmaydigan terminal

    acc, why = _ti.resolve_till_exact(db, co.id, br.id, terminal_id=other.id)
    assert acc is None, "ZID terminal jimgina yagona TILL'ga bog'landi"
    assert why == "unresolved-terminal-no-match"
    # pre-T0 ham shunday — bu DALIL masalasi, T0 masalasi emas
    assert _cr.resolve_till(db, co.id, br.id, terminal_id=other.id) is None


# ═══ K) resolver shartnomasi (reason kodlari) ══════════════════════════════
def test_K_resolver_contract(db, cashenv):
    co = _co(db); br = _br(db, co)
    assert _ti.resolve_till_exact(db, co.id, br.id) == (None, "no-till")

    t1 = _till(db, co, br, "TILL-01"); db.commit()
    assert _ti.resolve_till_exact(db, co.id, br.id) == (t1, _ti.SINGLE_CHECKOUT)
    assert _ti.resolve_till_exact(db, co.id, br.id, allow_single_checkout=False) == (
        None, _ti.BLOCKED_SINGLE_CHECKOUT)

    term = _term(db, br); t2 = _till(db, co, br, "TILL-02", terminal=term); db.commit()
    # terminal dalili post-T0 rejimida HAM ishlaydi (u AYNAN identifikatsiya)
    assert _ti.resolve_till_exact(db, co.id, br.id, terminal_id=term.id,
                                  allow_single_checkout=False) == (t2, "terminal")
    assert _ti.resolve_till_exact(db, co.id, br.id) == (None, "ambiguous-no-terminal")
