# -*- coding: utf-8 -*-
"""Dynamic TILL lifecycle + migration boundary revision testlari (real PostgreSQL).

Branch 0..N TILL (dinamik add/deactivate), migration BLOCK EMAS; T0'dan keyin exact TILL SHART; TILL CRUD
(create/rename/deactivate/reactivate; referenced -> hard-delete yo'q); concurrency (bir TILL = bir smena
post-T0); SAFE mustaqil; tenant isolation. (A,B,F,K,L,M sale-audit; G,H physical-till faylida qamralgan.)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1 import shifts as shifts_api
from app.api.v1 import tills as tills_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.catalog import Product, Unit
from app.models.enums import ShiftStatus
from app.models.inventory import Inventory
from app.models.org import Branch, Company, Terminal
from app.models.sales import Sale
from app.models.settings import Setting
from app.schemas.sales import SaleCreate, SaleItemIn
from app.services import sales as sales_svc
from app.services.cash import mode, till_identity as ti


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _co(db):
    c = Company(name="DL" + _hex(), code="dl" + _hex(), currency="UZS"); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F" + _hex()); db.add(b); db.flush(); return b


def _emp(db, co, br):
    e = Employee(company_id=co.id, full_name="K" + _hex(), role_id=db.query(Role).first().id)
    db.add(e); db.flush(); db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush(); return e


def _term(db, br):
    t = Terminal(branch_id=br.id, name="T" + _hex()); db.add(t); db.flush(); return t


def _prod(db, co, br):
    u = Unit(code="u" + _hex(), name="dona"); db.add(u); db.flush()
    p = Product(company_id=co.id, article_code="A" + _hex(), name="M" + _hex(), unit_id=u.id,
                base_buy_price=Decimal("6000"), base_sell_price=Decimal("10000"), tax_rate=Decimal("0"))
    db.add(p); db.flush()
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal("1000"),
                     updated_at=datetime.now(timezone.utc)))
    db.commit(); return p


def _open(db, emp, terminal=None, opening=0):
    return shifts_api.open_shift(shifts_api.OpenShift(
        opening_cash=opening, terminal_id=(terminal.id if terminal else None)), emp, db)


def _sale(db, emp, prod, method="cash", **kw):
    return sales_svc.create_sale(db, emp, SaleCreate(
        items=[SaleItemIn(product_id=prod.id, qty=1)], payment_method=method, **kw))


def _set_cutover(db, co, when=None):
    when = when or (datetime.now(timezone.utc) - timedelta(days=1))   # o'tmish -> cutover FAOL
    db.add(Setting(company_id=co.id, branch_id=None, key="cash", value={"cutover_at": when.isoformat()}))
    db.commit()


def _create_till(db, emp, br, code, terminal=None):
    return tills_api.create_till(tills_api.TillCreate(
        branch_id=br.id, code=code, terminal_id=(terminal.id if terminal else None)), emp, db)


# ═══ C) add a TILL later — no migration, existing history unchanged ══════════
def test_C_add_till_later_no_migration(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _term(db, br); t2 = _term(db, br)
    _create_till(db, emp, br, "TILL-01", t1); _create_till(db, emp, br, "TILL-02", t2)
    prod = _prod(db, co, br)
    r1 = _open(db, emp, t1); s1 = _sale(db, emp, prod)
    shifts_api.close_shift(uuid.UUID(r1["id"]), shifts_api.CloseShift(counted_cash=0), emp, db)
    before = {s.id: s.till_id for s in db.query(Sale).filter(Sale.company_id == co.id).all()}
    # KEYINCHALIK yangi kassa qo'shamiz — HECH QANDAY migration talab qilinmaydi
    t3 = _term(db, br); till3 = _create_till(db, emp, br, "TILL-03", t3)
    assert till3["active"] is True
    after = {s.id: s.till_id for s in db.query(Sale).filter(Sale.company_id == co.id).all()}
    assert after == before                                    # eski tarix O'ZGARMADI
    assert len(ti.list_tills(db, co.id, br.id)) == 3          # 3 ACTIVE TILL


# ═══ D) deactivate a TILL — old sales still reference it ════════════════════
def test_D_deactivate_till_old_sales_reference(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t2 = _term(db, br); till2 = _create_till(db, emp, br, "TILL-02", t2)
    prod = _prod(db, co, br)
    _open(db, emp, t2); s = _sale(db, emp, prod)
    assert s.till_id == uuid.UUID(till2["id"])
    shifts_api.close_shift(db.query(__import__("app.models.shifts", fromlist=["Shift"]).Shift).filter_by(
        cashier_id=emp.id).first().id, shifts_api.CloseShift(counted_cash=0), emp, db)
    tills_api.update_till(uuid.UUID(till2["id"]), tills_api.TillUpdate(active=False), emp, db)
    db.refresh(s)
    assert s.till_id == uuid.UUID(till2["id"])                # eski savdo hali o'sha TILL'ni ko'rsatadi
    assert db.get(CashAccount, uuid.UUID(till2["id"])).status == "ARCHIVED"
    assert ti.list_tills(db, co.id, br.id) == []              # ACTIVE list'да yo'q (yangi smena resolve qilmaydi)


# ═══ E) cannot hard-delete a historically used TILL ═════════════════════════
def test_E_cannot_hard_delete_referenced(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _term(db, br); till1 = _create_till(db, emp, br, "TILL-01", t1)
    prod = _prod(db, co, br)
    _open(db, emp, t1); _sale(db, emp, prod)                  # TILL ishlatildi
    with pytest.raises(HTTPException) as ei:
        tills_api.delete_till(uuid.UUID(till1["id"]), emp, db)
    assert ei.value.status_code == 400                        # referenced -> hard-delete taqiqlanadi
    # hech qachon ishlatilmagan TILL -> o'chirsa bo'ladi
    unused = _create_till(db, emp, br, "TILL-UNUSED", _term(db, br))
    assert tills_api.delete_till(uuid.UUID(unused["id"]), emp, db)["ok"] is True


# ═══ I) post-T0 new cash shift without TILL -> rejected ═════════════════════
def test_I_post_t0_shift_without_till_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)   # TILL yaratilmagan
    _set_cutover(db, co)
    with pytest.raises(HTTPException) as ei:
        _open(db, emp, terminal=None)                        # terminalsiz, TILL yo'q, post-T0
    assert ei.value.status_code == 400 and "TILL" in ei.value.detail


# ═══ J) post-T0 cash sale without exact TILL -> rejected ════════════════════
def test_J_post_t0_cash_sale_without_till_rejected(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)   # TILL yo'q
    prod = _prod(db, co, br)
    _set_cutover(db, co)
    with pytest.raises(HTTPException) as ei:
        _sale(db, emp, prod, method="cash")                  # shift-less naqd savdo, post-T0, TILL yo'q
    assert ei.value.status_code == 400 and "TILL" in ei.value.detail
    # karta savdo -> naqd emas -> RAD ETILMAYDI (fizik naqd custody yo'q)
    s = _sale(db, emp, prod, method="card")
    assert s.id is not None


# ═══ N) two different TILLs, parallel shifts, same branch -> valid ══════════
def test_N_parallel_different_tills_ok(db, cashenv):
    co = _co(db); br = _br(db, co)
    eA = _emp(db, co, br); eB = _emp(db, co, br)
    t1 = _term(db, br); t2 = _term(db, br)
    _create_till(db, emp=eA, br=br, code="TILL-01", terminal=t1)
    _create_till(db, emp=eA, br=br, code="TILL-02", terminal=t2)
    _set_cutover(db, co)
    r1 = _open(db, eA, t1); r2 = _open(db, eB, t2)            # turli TILL -> parallel OK
    assert r1["id"] and r2["id"] and r1["id"] != r2["id"]


# ═══ O) same TILL simultaneous shifts (post-T0) -> rejected ═════════════════
def test_O_same_till_concurrent_rejected_post_t0(db, cashenv):
    co = _co(db); br = _br(db, co)
    eA = _emp(db, co, br); eB = _emp(db, co, br)
    t1 = _term(db, br); _create_till(db, emp=eA, br=br, code="TILL-01", terminal=t1)
    _set_cutover(db, co)
    _open(db, eA, t1)                                         # A ochdi TILL-01
    with pytest.raises(HTTPException) as ei:
        _open(db, eB, t1)                                     # B AYNI TILL-01 -> band
    assert ei.value.status_code == 400 and "band" in ei.value.detail


# ═══ P) SAFE independent from TILL count ════════════════════════════════════
def test_P_safe_independent_of_tills(db, cashenv):
    from datetime import datetime as _dt, timezone as _tz
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    safe = CashAccount(tenant_id=co.id, branch_id=br.id, type="SAFE", currency="UZS", status="ACTIVE",
                       label=ti.safe_label(), created_at=_dt.now(_tz.utc)); db.add(safe); db.commit()
    _create_till(db, emp, br, "TILL-01", _term(db, br))
    _create_till(db, emp, br, "TILL-02", _term(db, br))
    till3 = _create_till(db, emp, br, "TILL-03", _term(db, br))
    tills_api.update_till(uuid.UUID(till3["id"]), tills_api.TillUpdate(active=False), emp, db)
    assert ti.find_safe(db, co.id, br.id) is not None         # SAFE TILL soni o'zgarishidan mustaqil
    assert db.query(CashAccount).filter(CashAccount.tenant_id == co.id,
                                        CashAccount.type == "SAFE").count() == 1


# ═══ Q) add a new TILL after cutover and immediately use it ═════════════════
def test_Q_add_till_after_cutover_use_immediately(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    prod = _prod(db, co, br)
    _set_cutover(db, co)                                      # cutover FAOL
    t = _term(db, br); till = _create_till(db, emp, br, "TILL-NEW", t)   # cutover'dan KEYIN yangi kassa
    r = _open(db, emp, t)                                     # darhol ishlatiladi
    s = _sale(db, emp, prod)
    assert r["id"] and s.till_id == uuid.UUID(till["id"])


# ═══ R) tenant isolation (TILL CRUD scoped) ═════════════════════════════════
def test_R_tenant_isolation(db, cashenv):
    coA = _co(db); brA = _br(db, coA); empA = _emp(db, coA, brA)
    tillA = _create_till(db, empA, brA, "TILL-A", _term(db, brA))
    coB = _co(db); brB = _br(db, coB); empB = _emp(db, coB, brB)
    ids_B = {t["id"] for t in tills_api.list_tills(branch_id=None, emp=empB, db=db)}
    assert tillA["id"] not in ids_B                           # A TILL'i B tenantda ko'rinmaydi
    with pytest.raises(HTTPException):                        # B empA TILL'ini o'zgartira olmaydi
        tills_api.update_till(uuid.UUID(tillA["id"]), tills_api.TillUpdate(active=False), empB, db)


# ═══ S) TILL rename snapshot-safe ═══════════════════════════════════════════
def test_S_till_rename_snapshot_safe(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    t1 = _term(db, br); till1 = _create_till(db, emp, br, "TILL-01", t1)
    prod = _prod(db, co, br)
    _open(db, emp, t1); s = _sale(db, emp, prod)
    assert s.till_code_snapshot == "TILL-01"
    tills_api.update_till(uuid.UUID(till1["id"]), tills_api.TillUpdate(code="KASSA-MARKAZIY"), emp, db)
    db.refresh(s)
    assert s.till_code_snapshot == "TILL-01"                  # eski chek snapshot O'ZGARMADI
    assert ti.account_checkout_code(db.get(CashAccount, uuid.UUID(till1["id"]))) == "KASSA-MARKAZIY"
    assert ti.account_terminal_id(db.get(CashAccount, uuid.UUID(till1["id"]))) == t1.id   # terminal SAQLANDI


# ═══ T) deactivate / reactivate lifecycle ═══════════════════════════════════
def test_T_deactivate_reactivate(db, cashenv):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    till = _create_till(db, emp, br, "TILL-01", _term(db, br))
    tid = uuid.UUID(till["id"])
    tills_api.update_till(tid, tills_api.TillUpdate(active=False), emp, db)
    assert db.get(CashAccount, tid).status == "ARCHIVED" and ti.list_tills(db, co.id, br.id) == []
    tills_api.update_till(tid, tills_api.TillUpdate(active=True), emp, db)
    assert db.get(CashAccount, tid).status == "ACTIVE" and len(ti.list_tills(db, co.id, br.id)) == 1
