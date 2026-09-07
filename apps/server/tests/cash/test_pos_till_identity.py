# -*- coding: utf-8 -*-
"""POS EXACT TILL IDENTITY — server tomoni (real PostgreSQL).

Shartnoma: T0'dan keyin server kassani (TILL) HECH QACHON TAXMIN QILMAYDI. Klient AYNAN
till_id yuboradi; smenaga bog'langan naqd amallar Shift.till_id'ni MEROS oladi.

I  post-T0: AYNAN yaroqli till_id bilan smena ochiladi
J  post-T0: till_id YO'Q -> filialda AYNAN BITTA ACTIVE TILL bo'lsa ham RAD
K  post-T0: BOSHQA filial kassasi -> RAD
L  ARCHIVED kassa -> RAD
M  2 ta TILL + aynan tanlangan id -> muvaffaqiyat, Shift AYNAN o'shani saqlaydi
N  smenadagi savdo Shift.till_id'ni meros oladi
O  savdodagi ZID till_id -> RAD (drawer smena o'rtasida almashmaydi)
P  offline replay'dagi ZID till_id -> RAD (jimgina tuzatish YO'Q)
Q  OCHIQ smenasi bor TILL ARXIVLANMAYDI
R  ochiq smenasiz TILL arxivlanadi + POS ro'yxatidan chiqadi
S  POS ro'yxati: FAQAT joriy filial + FAQAT ACTIVE + FAQAT o'z tenanti
T  till_id va terminal_id ZID drawer ko'rsatsa -> RAD (409)
U  ledger AYNAN Shift.till_id ga yoziladi (split-brain qaytmasin)
V  arxivlash tekshiruvi ochiq cash.shift ni ham ko'radi
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
import pytest

from app.api.v1.shifts import OpenShift, open_shift
from app.api.v1.tills import TillUpdate, list_tills, update_till
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.inventory import Inventory
from app.models.catalog import Product, Unit
from app.models.settings import Setting
from app.models.shifts import Shift
from app.services.cash import till_identity as _ti


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _co(db):
    c = Company(name="PT" + _hex(), code="pt" + _hex(), currency="UZS")
    db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, br, role="kassir"):
    r = db.query(Role).filter(Role.code == role).first() or db.query(Role).first()
    e = Employee(company_id=co.id, full_name="K", role_id=r.id)
    db.add(e); db.flush(); db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush(); return e


def _till(db, co, br, code, status="ACTIVE"):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status=status,
                    label=_ti.till_label(code, None), created_at=_now())
    db.add(a); db.flush(); return a


def _t0(db, co, past=True):
    when = _now() - timedelta(days=1) if past else _now() + timedelta(days=365)
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"cutover_at": when.isoformat()}))
    db.flush()


def _prod(db, co, br):
    u = Unit(code="u" + _hex(), name="dona"); db.add(u); db.flush()
    p = Product(company_id=co.id, article_code="A" + _hex(), name="M" + _hex(), unit_id=u.id,
                base_buy_price=Decimal("6000"), base_sell_price=Decimal("10000"),
                tax_rate=Decimal("0"))
    db.add(p); db.flush()
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal("1000"), updated_at=_now()))
    db.flush(); return p


def _open(db, emp, **kw):
    return open_shift(OpenShift(opening_cash=Decimal("0"), **kw), emp=emp, db=db)


def _shift_of(db, res):
    return db.get(Shift, uuid.UUID(res["id"]) if isinstance(res, dict) else res.id)


# ═══ I) post-T0 + aynan till_id -> ochiladi ════════════════════════════════
def test_I_post_t0_explicit_till_opens(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br, "TILL-01"); _t0(db, co); db.commit()
    sh = _shift_of(db, _open(db, emp, till_id=till.id))
    assert str(sh.till_id) == str(till.id)


# ═══ J) post-T0 + till_id YO'Q (1 ta TILL) -> RAD ══════════════════════════
def test_J_post_t0_missing_till_rejected_even_with_one(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _till(db, co, br, "TILL-01"); _t0(db, co); db.commit()
    with pytest.raises(HTTPException) as ei:
        _open(db, emp)
    assert ei.value.status_code == 400 and "AYNAN kassa" in ei.value.detail


# ═══ K) boshqa filial kassasi -> RAD ═══════════════════════════════════════
def test_K_wrong_branch_till_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); other = _br(db, co); emp = _emp(db, co, br)
    foreign = _till(db, co, other, "TILL-01"); _t0(db, co); db.commit()
    with pytest.raises(HTTPException) as ei:
        _open(db, emp, till_id=foreign.id)
    assert ei.value.status_code == 400 and "wrong-branch" in ei.value.detail

    # boshqa TENANT kassasi ham RAD (izolyatsiya)
    co2 = _co(db); br2 = _br(db, co2); alien = _till(db, co2, br2, "TILL-01"); db.commit()
    with pytest.raises(HTTPException) as ei2:
        _open(db, emp, till_id=alien.id)
    assert ei2.value.status_code == 400


# ═══ L) ARCHIVED kassa -> RAD ══════════════════════════════════════════════
def test_L_archived_till_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    arch = _till(db, co, br, "TILL-01", status="ARCHIVED"); _t0(db, co); db.commit()
    with pytest.raises(HTTPException) as ei:
        _open(db, emp, till_id=arch.id)
    assert ei.value.status_code == 400 and "till-not-active" in ei.value.detail


# ═══ M) 2 TILL + aynan tanlov -> AYNAN o'sha saqlanadi ════════════════════
def test_M_two_tills_exact_selection(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _till(db, co, br, "TILL-01"); t2 = _till(db, co, br, "TILL-02")
    _t0(db, co); db.commit()
    sh = _shift_of(db, _open(db, emp, till_id=t2.id))
    assert str(sh.till_id) == str(t2.id) != str(t1.id)


# ═══ N) savdo Shift.till_id'ni MEROS oladi ═════════════════════════════════
def test_N_sale_inherits_shift_till(db, cashenv):
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _till(db, co, br, "TILL-01"); _till(db, co, br, "TILL-02")
    prod = _prod(db, co, br); _t0(db, co); db.commit()
    sh = _shift_of(db, _open(db, emp, till_id=t1.id))
    from app.models.sales import Sale
    from app.schemas.sales import SaleItemIn
    sale = create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)],
                                           client_uuid=uuid.uuid4()))
    row = db.get(Sale, uuid.UUID(sale["id"]) if isinstance(sale, dict) else sale.id)
    assert str(row.till_id) == str(t1.id) == str(sh.till_id)


# ═══ O) savdodagi ZID till_id -> RAD ══════════════════════════════════════
def test_O_conflicting_sale_till_rejected(db, cashenv):
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _till(db, co, br, "TILL-01"); t2 = _till(db, co, br, "TILL-02")
    prod = _prod(db, co, br); _t0(db, co); db.commit()
    _open(db, emp, till_id=t1.id)
    from app.schemas.sales import SaleItemIn
    with pytest.raises(HTTPException) as ei:
        create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)],
                                        client_uuid=uuid.uuid4(), till_id=t2.id))
    assert ei.value.status_code == 409, "drawer smena o'rtasida almashdi"


# ═══ P) offline replay'dagi ZID till_id -> RAD (jimgina tuzatish YO'Q) ════
def test_P_offline_replay_conflict_rejected(db, cashenv):
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _till(db, co, br, "TILL-01"); t2 = _till(db, co, br, "TILL-02")
    prod = _prod(db, co, br); _t0(db, co); db.commit()
    _open(db, emp, till_id=t1.id)
    old = _now() - timedelta(hours=6)
    from app.schemas.sales import SaleItemIn
    with pytest.raises(HTTPException) as ei:      # offline-origin (device_occurred_at o'tmishда)
        create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)],
                                        client_uuid=uuid.uuid4(), till_id=t2.id, sold_at=old),
                    honor_price_snapshot=True)
    assert ei.value.status_code == 409


# ═══ Q) OCHIQ smenasi bor TILL ARXIVLANMAYDI ══════════════════════════════
def test_Q_cannot_archive_till_with_open_shift(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br, "TILL-01"); db.commit()
    _open(db, emp, till_id=till.id)                       # pre-T0 ham till_id ishlaydi
    db.commit()
    with pytest.raises(HTTPException) as ei:
        update_till(till.id, TillUpdate(active=False), emp=emp, db=db)
    assert ei.value.status_code == 409 and "OCHIQ smena" in ei.value.detail
    db.rollback()
    assert db.get(CashAccount, till.id).status == "ACTIVE"   # holat O'ZGARMADI


# ═══ R) ochiq smenasiz TILL arxivlanadi va POS ro'yxatidan chiqadi ════════
def test_R_archive_without_open_shift_and_leaves_pos_list(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    keep = _till(db, co, br, "TILL-01"); gone = _till(db, co, br, "TILL-02"); db.commit()
    before = list_tills(active_only=True, mine=True, emp=emp, db=db)
    assert {t["id"] for t in before} == {str(keep.id), str(gone.id)}

    update_till(gone.id, TillUpdate(active=False), emp=emp, db=db)
    after = list_tills(active_only=True, mine=True, emp=emp, db=db)
    assert {t["id"] for t in after} == {str(keep.id)}       # arxivlangan TANLASH ro'yxatida YO'Q


# ═══ S) POS ro'yxati: joriy filial + ACTIVE + o'z tenanti ═════════════════
def test_S_pos_list_scoping(db, cashenv):
    co = _co(db); mine = _br(db, co); other = _br(db, co)
    emp = _emp(db, co, mine)
    t_mine = _till(db, co, mine, "TILL-01")
    _till(db, co, mine, "TILL-OLD", status="ARCHIVED")     # ARCHIVED -> chiqmaydi
    _till(db, co, other, "TILL-09")                        # boshqa filial -> chiqmaydi
    co2 = _co(db); br2 = _br(db, co2); _till(db, co2, br2, "TILL-01")   # boshqa tenant
    db.commit()

    rows = list_tills(active_only=True, mine=True, emp=emp, db=db)
    assert [r["id"] for r in rows] == [str(t_mine.id)]
    r = rows[0]
    for k in ("id", "code", "label", "status", "branch_id", "currency", "active"):
        assert k in r, f"POS UI uchun {k} maydoni yo'q"
    assert r["branch_id"] == str(mine.id) and r["active"] is True and r["currency"] == "UZS"

    # scoping'siz chaqiruv tenant ichida qoladi (boshqa tenant HECH QACHON ko'rinmaydi)
    all_rows = list_tills(emp=emp, db=db)
    assert all(x["branch_id"] in (str(mine.id), str(other.id)) for x in all_rows)


# ═══ T) till_id va terminal_id ZID -> RAD ══════════════════════════════════
def test_T_conflicting_till_and_terminal_rejected(db, cashenv):
    """Ikkalasi kelsa va BOSHQA-BOSHQA kassani ko'rsatsa, Shift ZID juftlikni SAQLAMASLIGI kerak."""
    from app.models.org import Terminal
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _till(db, co, br, "TILL-01")
    term = Terminal(branch_id=br.id, name="T" + _hex()); db.add(term); db.flush()
    t2 = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                     label=_ti.till_label("TILL-02", term.id), created_at=_now())
    db.add(t2); _t0(db, co); db.commit()

    with pytest.raises(HTTPException) as ei:          # till_id=TILL-01, terminal=TILL-02 niki
        _open(db, emp, till_id=t1.id, terminal_id=term.id)
    assert ei.value.status_code == 409 and "BOSHQA-BOSHQA" in ei.value.detail

    # MOS juftlik esa o'tadi
    sh = _shift_of(db, _open(db, emp, till_id=t2.id, terminal_id=term.id))
    assert str(sh.till_id) == str(t2.id)


# ═══ U) ledger AYNAN Shift.till_id ga yoziladi ════════════════════════════
def test_U_ledger_follows_exact_shift_till(db, cashenv):
    """Ko'p-TILL filialda terminal YO'Q: hook QAYTA RESOLVE qilса `ambiguous` bo'lib ledger legi
    TUSHIB QOLARDI. Endi u AYNAN Shift.till_id ni oladi."""
    from app.api.v1.shifts import CashMove, add_cash_movement
    from app.models.cash import CashLedgerEntry as CLE, CashShift
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _till(db, co, br, "TILL-01"); t2 = _till(db, co, br, "TILL-02")
    _t0(db, co); db.commit()

    sh = _shift_of(db, _open(db, emp, till_id=t2.id))   # terminal YO'Q, 2 ta TILL
    db.commit()
    # cash.shift AYNAN t2 da ochilgan bo'lishi kerak (on_shift_open re-resolve QILMAYDI)
    cs = db.query(CashShift).filter(CashShift.tenant_id == co.id,
                                    CashShift.cash_account_id == t2.id).first()
    assert cs is not None, "cash.shift AYNAN tanlangan kassada ochilmadi"

    add_cash_movement(sh.id, CashMove(type="payin", amount=Decimal("5000"), reason="test"),
                      emp=emp, db=db)
    db.commit()
    legs = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.cash_account_id == t2.id).all()
    assert legs, "ledger legi TUSHIB QOLDI (split-brain)"
    assert not db.query(CLE).filter(CLE.tenant_id == co.id,
                                    CLE.cash_account_id == t1.id).first()   # boshqa kassaga EMAS


# ═══ V) arxivlash ochiq cash.shift ni ham ko'radi ═════════════════════════
def test_V_archive_blocked_by_open_cash_shift(db, cashenv):
    from app.models.cash import CashShift
    from app.models.enums import ShiftStatus as _SS
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _till(db, co, br, "TILL-01"); db.commit()
    sh = _shift_of(db, _open(db, emp, till_id=till.id)); db.commit()

    # Legacy smena YOPILDI, lekin ledger tomonidagi cash.shift OCHIQ qoldi
    sh.status = _SS.closed; sh.closed_at = _now(); db.add(sh); db.commit()
    assert db.query(CashShift).filter(CashShift.cash_account_id == till.id,
                                      CashShift.status == "OPEN").first() is not None

    with pytest.raises(HTTPException) as ei:
        update_till(till.id, TillUpdate(active=False), emp=emp, db=db)
    assert ei.value.status_code == 409
    db.rollback()
    assert db.get(CashAccount, till.id).status == "ACTIVE"
