# -*- coding: utf-8 -*-
"""Physical TILL/SAFE mapping revision — testlar (real PostgreSQL).

REAL fizik model: BIR FILIAL != BIR TILL. Har fizik checkout/kassa (terminal yoki operator mapping bilan)
= alohida TILL; kassir TILL emas; har branch (odatda) 1 SAFE (shiftless). Fizik checkout dalili yoki
explicit operator mapping bo'lmasa -> AMBIGUOUS (BLOCK). "Ko'p kassir = ko'p TILL" taxmin qilinmaydi.

Ssenariylar (task §9): A–L. Har test O'Z tenant'ini quradi (shared pgserver -> tenant-scoped assert).
"""
from __future__ import annotations

import inspect
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.cash.migration import backfill, phase0, phase1
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry, CashShift
from app.models.enums import SaleStatus, ShiftStatus
from app.models.org import Branch, Company, Terminal
from app.models.sales import Sale, SalePayment
from app.models.shifts import Shift
from app.services.cash import mode
from app.services.cash import retrofit
from app.services.cash import till_identity as ti


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _tenant(db, cashenv):
    co = Company(name="PT" + _hex(), code="pt" + _hex(), currency="UZS"); db.add(co); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="Br"); db.add(br); db.flush()
    db.commit()
    return co, br


def _cashier(db, co, br):
    role = db.query(Role).first()
    e = Employee(company_id=co.id, full_name="K" + _hex(), role_id=role.id); db.add(e); db.flush()
    db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush()
    db.commit()
    return e


def _terminal(db, br, name=None):
    t = Terminal(branch_id=br.id, name=name or ("T" + _hex())); db.add(t); db.flush(); db.commit(); return t


def _shift(db, cashenv, br, emp, *, terminal=None, opening="0", closed=True, hours_ago=4):
    opened = cashenv.now - timedelta(hours=hours_ago)
    sh = Shift(branch_id=br.id, cashier_id=emp.id, terminal_id=(terminal.id if terminal else None),
               opened_at=opened, closed_at=(cashenv.now - timedelta(hours=hours_ago - 1)) if closed else None,
               opening_cash=Decimal(str(opening)), counted_cash=Decimal(str(opening)) if closed else None,
               status=ShiftStatus.closed if closed else ShiftStatus.open)
    db.add(sh); db.flush(); db.commit(); return sh


def _hist_sale(db, cashenv, co, br, emp, amount, *, terminal=None, hours_ago=3):
    sold = cashenv.now - timedelta(hours=hours_ago)
    s = Sale(receipt_no="R" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id, shift_id=None,
             terminal_id=(terminal.id if terminal else None), status=SaleStatus.completed, currency="UZS",
             subtotal=Decimal(str(amount)), total=Decimal(str(amount)), sold_at=sold); db.add(s); db.flush()
    db.add(SalePayment(sale_id=s.id, method_code="cash", amount=Decimal(str(amount)), paid_at=sold))
    db.flush(); db.commit(); return s


def _mapping(br, tills, safe=True):
    return ti.parse_operator_mapping({"branches": {str(br.id): {"safe": safe, "tills": tills}}})


def _provision(db, co, *, mapping=None, stamp_shifts=True):
    m, _ = phase0.propose_till_mapping(db, company_id=co.id, mapping=mapping)
    phase0.provision_accounts(db, m, apply=True, mapping=mapping)
    db.commit()
    if stamp_shifts:
        _stamp_shift_tills(db, co)
    return m


def _stamp_shift_tills(db, co):
    """§HIST: RC7 runtime smena OCHILGANDA Shift.till_id ni YOZADI — bu TARIXIY dalil.
    Testlarda shu holatni simulyatsiya qilamiz (terminal -> o'sha paytdagi drawer).
    DIQQAT: backfill endi terminal->TILL bog'lanishini O'ZI dalil deb QABUL QILMAYDI (§4:
    binding mutable/versiyalanmagan), shu bois dalil smenada saqlangan bo'lishi kerak."""
    from app.models.org import Branch as _B
    for br in db.query(_B).filter(_B.company_id == co.id, _B.deleted_at.is_(None)).all():
        for sh in db.query(Shift).filter(Shift.branch_id == br.id, Shift.till_id.is_(None)).all():
            t = None
            if sh.terminal_id:
                t = ti.find_till_by_terminal(db, co.id, br.id, sh.terminal_id)
            if t is None:
                tl = ti.list_tills(db, co.id, br.id)
                t = tl[0] if len(tl) == 1 else None
            if t is not None:
                sh.till_id = t.id
    db.commit()


def _tills(db, co, br):
    return ti.list_tills(db, co.id, br.id)


def _T0(cashenv):
    return cashenv.now.isoformat()


# ═══ A) 1 branch, 1 terminal, 3 cashier => 1 TILL + 1 SAFE ═══════════════════
def test_A_one_terminal_three_cashiers_one_till(db, cashenv):
    co, br = _tenant(db, cashenv)
    t = _terminal(db, br)
    for _ in range(3):
        e = _cashier(db, co, br)
        _shift(db, cashenv, br, e, terminal=t)          # 3 kassir, BIR terminal (umumiy drawer)
    res = phase0.provision_accounts(db, _[0] if False else None, apply=True,
                                    mapping=None) if False else None
    m, _f = phase0.propose_till_mapping(db, company_id=co.id)
    tills = [x for x in m if x.proposed_type == "TILL"]
    safes = [x for x in m if x.proposed_type == "SAFE"]
    assert len(tills) == 1 and len(safes) == 1 and tills[0].source == "TERMINAL"
    p = phase0.provision_accounts(db, m, apply=True); db.commit()
    assert p["tills_created"] == 1 and p["safes_created"] == 1
    assert len(_tills(db, co, br)) == 1 and ti.find_safe(db, co.id, br.id) is not None


# ═══ B) 1 branch, 3 terminals, 3 cashier => 3 TILL + 1 SAFE ══════════════════
def test_B_three_terminals_three_tills(db, cashenv):
    co, br = _tenant(db, cashenv)
    terms = [_terminal(db, br) for _ in range(3)]
    for t in terms:
        e = _cashier(db, co, br)
        _shift(db, cashenv, br, e, terminal=t)
    m, _f = phase0.propose_till_mapping(db, company_id=co.id)
    tills = [x for x in m if x.proposed_type == "TILL"]
    safes = [x for x in m if x.proposed_type == "SAFE"]
    assert len(tills) == 3 and len(safes) == 1
    assert {x.terminal_id for x in tills} == {t.id for t in terms}
    p = phase0.provision_accounts(db, m, apply=True); db.commit()
    assert p["tills_created"] == 3 and p["safes_created"] == 1
    assert len(_tills(db, co, br)) == 3


# ═══ C) 1 branch, 3 cashier, terminal NULL, no mapping => BLOCK ══════════════
def test_C_terminalless_multi_cashier_no_current_till(db, cashenv):
    # DYNAMIC TILL: 3 kassir terminal SIZ -> fizik kassa soni noma'lum -> CURRENT_BRANCH_NO_ACTIVE_TILL
    # (REVIEW, GLOBAL BLOCK EMAS). Provision uni skip qiladi (soxta TILL yaratmaydi); "kassir=till" TAXMIN YO'Q.
    co, br = _tenant(db, cashenv)
    for _ in range(3):
        e = _cashier(db, co, br)
        _shift(db, cashenv, br, e, terminal=None)       # terminal YO'Q
    m, findings = phase0.propose_till_mapping(db, company_id=co.id)
    tills = [x for x in m if x.proposed_type == "TILL"]
    assert len(tills) == 1 and tills[0].confidence == "AMBIGUOUS"
    assert any(f.code == "CURRENT_BRANCH_NO_ACTIVE_TILL" and f.severity == phase0.REVIEW for f in findings)
    assert not any(f.severity == phase0.BLOCK for f in findings)     # GLOBAL BLOCK EMAS
    p = phase0.provision_accounts(db, m, apply=True); db.commit()
    assert p["tills_created"] == 0 and p["skipped_ambiguous"] >= 1   # provision skip (soxta TILL yo'q)
    assert len(_tills(db, co, br)) == 0


# ═══ D) same as C + explicit 2-TILL operator mapping => 2 TILL + 1 SAFE ══════
def test_D_operator_mapping_resolves_two_tills(db, cashenv):
    co, br = _tenant(db, cashenv)
    for _ in range(3):
        e = _cashier(db, co, br)
        _shift(db, cashenv, br, e, terminal=None)
    mp = _mapping(br, [{"code": "TILL-01", "terminal_id": None, "label": "Kassa 1"},
                       {"code": "TILL-02", "terminal_id": None, "label": "Kassa 2"}])
    m, findings = phase0.propose_till_mapping(db, company_id=co.id, mapping=mp)
    tills = [x for x in m if x.proposed_type == "TILL"]
    assert len(tills) == 2 and all(x.source == "OPERATOR_MAPPING" for x in tills)
    assert not any(f.code == "MULTI_PHYSICAL_DRAWER_UNRESOLVED" for f in findings)
    p = phase0.provision_accounts(db, m, apply=True, mapping=mp); db.commit()
    assert p["tills_created"] == 2 and p["safes_created"] == 1
    codes = {ti.account_checkout_code(a) for a in _tills(db, co, br)}
    assert codes == {"TILL-01", "TILL-02"}


# ═══ E) same cashier: shift1 TILL-A, shift2 TILL-B => valid (cashier != TILL) ═
def test_E_same_cashier_different_tills_by_terminal(db, cashenv):
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    emp = _cashier(db, co, br)
    _shift(db, cashenv, br, emp, terminal=tA, opening="100000", hours_ago=6)   # shift1 -> drawer A
    _shift(db, cashenv, br, emp, terminal=tB, opening="200000", hours_ago=4)   # shift2 -> drawer B (bir kassir)
    _provision(db, co)
    tillA = ti.find_till_by_terminal(db, co.id, br.id, tA.id)
    tillB = ti.find_till_by_terminal(db, co.id, br.id, tB.id)
    assert tillA is not None and tillB is not None and tillA.id != tillB.id
    t0 = _T0(cashenv)
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    m = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True, approved_hash=approved)
    assert m["go_no_go"] == "GO"
    # OPENING legalar HAR SMENANING TERMINAL-TILL'iga tushadi (kassir bir xil bo'lса ham)
    op = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id,
                                          CashLedgerEntry.category == "OPENING").all()
    by_amt = {int(r.amount): r.cash_account_id for r in op}
    assert by_amt[100000] == tillA.id and by_amt[200000] == tillB.id   # cashier identity permanent TILL EMAS


# ═══ F) provision second run => inserted 0 (idempotent) ══════════════════════
def test_F_provision_idempotent_second_run(db, cashenv):
    co, br = _tenant(db, cashenv)
    e = _cashier(db, co, br); _shift(db, cashenv, br, e, terminal=_terminal(db, br))
    m, _f = phase0.propose_till_mapping(db, company_id=co.id)
    p1 = phase0.provision_accounts(db, m, apply=True); db.commit()
    assert p1["tills_created"] == 1 and p1["safes_created"] == 1
    p2 = phase0.provision_accounts(db, m, apply=True); db.commit()
    assert p2["tills_created"] == 0 and p2["safes_created"] == 0 and p2["existing"] >= 2


# ═══ G) backfill ambiguous physical till => no ledger write ══════════════════
def test_G_backfill_no_current_till_review_not_written(db, cashenv):
    # DYNAMIC TILL: branch'да ACTIVE TILL yo'q -> historical legalar REVIEW (skip), LEKIN migration GLOBAL
    # NO-GO EMAS (go=GO). Ledger fizik-account invariantи saqlanadi: TILL'siz leg YOZILMAYDI. Soxta TILL YO'Q.
    co, br = _tenant(db, cashenv)
    e = _cashier(db, co, br)
    _shift(db, cashenv, br, e, terminal=None, opening="50000", hours_ago=5)
    _hist_sale(db, cashenv, co, br, e, "30000", terminal=None)
    _provision(db, co)
    assert len(_tills(db, co, br)) == 0                              # provision skip (soxta TILL yo'q)
    t0 = _T0(cashenv)
    m = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True)
    assert m["go_no_go"] == "GO"                                    # GLOBAL BLOCK EMAS (dinamik TILL)
    assert m["review_rows"] >= 1                                    # TILL'siz legalar REVIEW'ga tushdi
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count() == 0   # YOZUV YO'Q


# ═══ H) backfill exact terminal mapping => correct TILL ═════════════════════
def test_H_backfill_exact_terminal_till(db, cashenv):
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    eA, eB = _cashier(db, co, br), _cashier(db, co, br)
    _shift(db, cashenv, br, eA, terminal=tA); _shift(db, cashenv, br, eB, terminal=tB)   # 2 fizik TILL
    saleA = _hist_sale(db, cashenv, co, br, eA, "12345", terminal=tA)
    _provision(db, co)
    tillA = ti.find_till_by_terminal(db, co.id, br.id, tA.id)
    # §4: terminal->TILL bog'lanishi YOLG'IZ O'ZI tarixiy dalil EMAS (mutable). Dalil sotuvda
    # SAQLANGAN bo'lishi kerak — RC7 runtime aynan shuni yozadi (Sale.till_id).
    saleA.till_id = tillA.id; db.add(saleA); db.commit()
    t0 = _T0(cashenv)
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True, approved_hash=approved)
    leg = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id,
                                           CashLedgerEntry.source_type == "SALE",
                                           CashLedgerEntry.source_id == saleA.id).one()
    assert leg.cash_account_id == tillA.id                           # AYNAN terminal-A TILL'iga


# ═══ I) SAFE no shift (shiftless) ═══════════════════════════════════════════
def test_I_safe_is_shiftless(db, cashenv):
    co, br = _tenant(db, cashenv)
    e = _cashier(db, co, br); _shift(db, cashenv, br, e, terminal=_terminal(db, br))
    _provision(db, co)
    safe = ti.find_safe(db, co.id, br.id)
    assert safe is not None and safe.type == "SAFE"
    # SAFE'да HECH QANDAY cash.shift bo'lmasligi kerak (shiftless)
    assert db.query(CashShift).filter(CashShift.cash_account_id == safe.id).count() == 0


# ═══ J) tenant isolation ════════════════════════════════════════════════════
def test_J_tenant_isolation(db, cashenv):
    coA, brA = _tenant(db, cashenv); eA = _cashier(db, coA, brA)
    _shift(db, cashenv, brA, eA, terminal=_terminal(db, brA))
    coB, brB = _tenant(db, cashenv); eB = _cashier(db, coB, brB)
    _shift(db, cashenv, brB, eB, terminal=_terminal(db, brB))
    _provision(db, coA)                                             # FAQAT coA
    assert len(_tills(db, coA, brA)) == 1
    assert len(_tills(db, coB, brB)) == 0                           # coB tegilmadi (izolyatsiya)
    accA = _tills(db, coA, brA)[0]
    assert accA.tenant_id == coA.id


# ═══ K) CashPostingService exact till routing (runtime) ═════════════════════
def test_K_runtime_exact_till_routing(db, cashenv):
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    eA, eB = _cashier(db, co, br), _cashier(db, co, br)
    _shift(db, cashenv, br, eA, terminal=tA); _shift(db, cashenv, br, eB, terminal=tB)
    _provision(db, co)
    tillA = ti.find_till_by_terminal(db, co.id, br.id, tA.id)
    tillB = ti.find_till_by_terminal(db, co.id, br.id, tB.id)
    empA = db.get(Employee, eA.id)
    # runtime exact resolver: terminal -> aynan TILL
    assert retrofit.resolve_till(db, co.id, br.id, terminal_id=tA.id).id == tillA.id
    assert retrofit.resolve_till(db, co.id, br.id, terminal_id=tB.id).id == tillB.id
    # dual-write (SHADOW default): sotuvни terminal-A bilan post qil -> leg AYNAN TILL-A'да
    sale_id = uuid.uuid4()
    retrofit.on_cash_sale(db, empA, branch_id=br.id, sale_id=sale_id, cash_amount=Decimal("777"),
                          terminal_id=tA.id)
    db.commit()
    leg = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id,
                                           CashLedgerEntry.source_id == sale_id).one()
    assert leg.cash_account_id == tillA.id                          # exact routing (terminal -> TILL)


# ═══ L) old "branch = 1 TILL" fallback absent ═══════════════════════════════
def test_L_no_silent_branch_default_fallback(db, cashenv):
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    eA, eB = _cashier(db, co, br), _cashier(db, co, br)
    _shift(db, cashenv, br, eA, terminal=tA); _shift(db, cashenv, br, eB, terminal=tB)
    _provision(db, co)                                              # 2 TILL bir branch'да
    assert len(_tills(db, co, br)) == 2
    # BEHAVIOR: ko'p-TILL branch + terminal YO'Q -> resolve_till None (ixtiyoriy .first() TANLAMAYDI)
    assert retrofit.resolve_till(db, co.id, br.id, terminal_id=None) is None
    # terminal bilan -> aniq TILL
    assert retrofit.resolve_till(db, co.id, br.id, terminal_id=tA.id) is not None
    # SOURCE: retrofit.resolve_till guarded resolver (resolve_till_exact) ishlatadi, find_account EMAS
    src = inspect.getsource(retrofit.resolve_till)
    assert "resolve_till_exact" in src and "find_account" not in src


# ═══ H2) shift's OWN cash-op resolves to the shift's TILL (multi-TILL, terminal) ═
def test_H2_backfill_cashop_uses_shift_terminal(db, cashenv):
    """Regressiya: ko'p-TILL branch'да smenaning O'Z cashop legi (expense) Shift.terminal_id orqali
    AYNAN o'sha TILL'ga tushishi kerak (sale/opening bilan izchil), REVIEW EMAS."""
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    eA, eB = _cashier(db, co, br), _cashier(db, co, br)
    shA = _shift(db, cashenv, br, eA, terminal=tA, opening="100000", hours_ago=6)
    _shift(db, cashenv, br, eB, terminal=tB, opening="50000", hours_ago=5)   # 2 fizik TILL
    db.add(CashMovement(shift_id=shA.id, type=CashMovementType.expense, amount=Decimal("7000"),
                        reason="hist expense", created_at=cashenv.now - timedelta(hours=5, minutes=30)))
    db.commit()
    _provision(db, co)
    tillA = ti.find_till_by_terminal(db, co.id, br.id, tA.id)
    t0 = _T0(cashenv)
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    m = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True, approved_hash=approved)
    assert m["go_no_go"] == "GO"
    exp = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id,
                                           CashLedgerEntry.category == "EXPENSE").one()
    assert exp.cash_account_id == tillA.id and exp.posting_kind == "ON_SHIFT"   # REVIEW emas, aynan TILL-A


# ═══ M) runtime create paths populate terminal_id -> exact routing (finding #2) ═
def test_M_runtime_create_paths_populate_terminal_and_route(db, cashenv):
    """Finding #2 regressiya: OpenShift.terminal_id -> Shift.terminal_id; sotuv smenaнинг terminal'ини
    MEROS oladi -> dual-write ko'p-TILL branch'да AYNAN o'sha TILL'ga tushadi (runtime threading dead EMAS)."""
    from app.api.v1 import shifts as shifts_api
    from app.services import sales as sales_svc
    from app.schemas.sales import SaleCreate, SaleItemIn
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    from app.models.shifts import Shift as LShift
    from app.models.sales import Sale as LSale
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    emp = _cashier(db, co, br)
    _shift(db, cashenv, br, emp, terminal=tA); _shift(db, cashenv, br, emp, terminal=tB)   # 2 fizik TILL
    _provision(db, co)
    tillA = ti.find_till_by_terminal(db, co.id, br.id, tA.id)
    unit = db.query(Unit).first()
    if unit is None:
        unit = Unit(code="d" + _hex(), name="dona"); db.add(unit); db.flush()
    prod = Product(company_id=co.id, article_code="A" + _hex(), name="M", unit_id=unit.id,
                   base_buy_price=Decimal("1000"), base_sell_price=Decimal("5000")); db.add(prod); db.flush()
    db.add(Inventory(product_id=prod.id, branch_id=br.id, qty=Decimal("100"), updated_at=cashenv.now))
    db.commit()
    empf = db.get(Employee, emp.id)
    # OpenShift terminal_id -> Shift.terminal_id (API path) -> cash.shift TILL-A'да
    r = shifts_api.open_shift(shifts_api.OpenShift(opening_cash=0, terminal_id=tA.id), empf, db)
    sh = db.get(LShift, uuid.UUID(r["id"]))
    assert sh.terminal_id == tA.id
    # naqd sotuv -> Sale smenаdan terminal MEROS oladi -> NORMAL leg TILL-A'да, ON_SHIFT
    sales_svc.create_sale(db, empf, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=1)],
                                               payment_method="cash"))
    db.commit()
    sale = db.query(LSale).filter(LSale.company_id == co.id).order_by(LSale.sold_at.desc()).first()
    assert sale.terminal_id == tA.id                       # smenаdан meros (runtime terminal DEAD emas)
    leg = db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id,
                                           CashLedgerEntry.category == "SALE",
                                           CashLedgerEntry.provenance == "NORMAL").one()
    assert leg.cash_account_id == tillA.id and leg.posting_kind == "ON_SHIFT"


# ═══ N) mapping vs DB mismatch => backfill NO-GO (finding #5) ════════════════
def test_N_backfill_mapping_db_mismatch_blocks(db, cashenv):
    """Finding #5: backfill'ga berilган --mapping provisionланган DB TILL'lari bilan MOS kelmasa ->
    NO-GO (jimgina noto'g'ri TILL'ga yozib ketmaydi)."""
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    eA, eB = _cashier(db, co, br), _cashier(db, co, br)
    _shift(db, cashenv, br, eA, terminal=tA, opening="100000", hours_ago=6)
    _shift(db, cashenv, br, eB, terminal=tB, opening="50000", hours_ago=5)
    _provision(db, co)                                     # TERMINAL detection -> 2 TILL (TERM-tA, TERM-tB)
    assert len(_tills(db, co, br)) == 2
    # operator branch'ни 1 drawer deb DA'VO qiladi (DB'да 2 bor) -> mismatch -> NO-GO
    mp = _mapping(br, [{"code": "TILL-01", "terminal_id": str(tA.id), "label": "Yagona"}])
    t0 = _T0(cashenv)
    m = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True, mapping=mp)
    assert m["go_no_go"] == "NO-GO" and m["mapping_db_mismatch"]   # DB(2) != mapping(1)
    assert db.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == co.id).count() == 0


# ═══ N2) friendly-code mapping on same terminal => NO false-block (F5 re-review) ═
def test_N2_backfill_mapping_friendly_code_same_terminal_ok(db, cashenv):
    """F5 re-review: TERMINAL-provision (code TERM-<uuid>) + operator friendly-code mapping AYNAN o'sha
    terminalга bog'langan -> FALSE-BLOCK YO'Q (fizik identity terminal orqali; code faqat label)."""
    co, br = _tenant(db, cashenv)
    tA = _terminal(db, br)
    eA = _cashier(db, co, br)
    _shift(db, cashenv, br, eA, terminal=tA, opening="100000", hours_ago=6)
    _provision(db, co)                                     # TERMINAL -> 1 TILL code=TERM-<tA>
    assert len(_tills(db, co, br)) == 1
    mp = _mapping(br, [{"code": "TILL-01", "terminal_id": str(tA.id), "label": "Kassa 1"}])  # friendly code, SAME terminal
    t0 = _T0(cashenv)
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False, mapping=mp)["manifest_hash"]
    m = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True, approved_hash=approved, mapping=mp)
    assert m["go_no_go"] == "GO" and not m["mapping_db_mismatch"]   # code farqi -> mismatch EMAS


# ═══ O) sequential multi-cashier, no terminal => till_mapping_decision BLOCK (finding #3) ═
def test_O_till_mapping_decision_dynamic_no_stop(db, cashenv):
    """DYNAMIC TILL: fizik kassa soni noma'lum branch -> till_mapping_decision GLOBAL STOP EMAS (PROCEED),
    LEKIN branches_without_active_till'да ko'rsatadi (informatsion). provision uni skip qiladi (izchil)."""
    from app.db.cash.migration import preflight as pf
    co, br = _tenant(db, cashenv)
    e1, e2 = _cashier(db, co, br), _cashier(db, co, br)
    _shift(db, cashenv, br, e1, terminal=None, hours_ago=6)
    _shift(db, cashenv, br, e2, terminal=None, hours_ago=4)
    g = pf.till_mapping_decision(db, company_id=co.id)
    assert g["ok"] is True and g["branches_without_active_till"]     # PROCEED + informatsion ro'yxat
    m, findings = phase0.propose_till_mapping(db, company_id=co.id)
    assert any(f.code == "CURRENT_BRANCH_NO_ACTIVE_TILL" for f in findings)
    assert not any(f.severity == phase0.BLOCK for f in findings)


# ═══ P) provision --apply ensures the protective unique index (finding #4) ════
def test_P_provision_apply_ensures_unique_index(db, cashenv):
    """Finding #4: provision --apply himoya partial-unique indeksини YARATADI (runbook prozasiga tayanmaydi)."""
    from sqlalchemy import text
    co, br = _tenant(db, cashenv)
    e = _cashier(db, co, br); _shift(db, cashenv, br, e, terminal=_terminal(db, br))
    m, _f = phase0.propose_till_mapping(db, company_id=co.id)
    phase0.provision_accounts(db, m, apply=True); db.commit()
    exists = db.execute(text("SELECT 1 FROM pg_indexes WHERE indexname='ux_cash_accounts_active_identity'")).first()
    assert exists is not None                              # apply path indeksни kafolatladi


# ═══ Q) terminal_id validated on create (F2 hardening) ══════════════════════
def test_Q_terminal_id_validated_on_create(db, cashenv):
    """F2 hardening: OpenShift.terminal_id MAVJUD va SHU filialга tegishli bo'lishi SHART (aks holда
    FK xatosi chalg'ituvchi xabar/sync loop bo'lardi)."""
    from fastapi import HTTPException
    from app.api.v1 import shifts as shifts_api
    co, br = _tenant(db, cashenv)
    _co2, br2 = _tenant(db, cashenv)
    emp = _cashier(db, co, br)
    foreign = _terminal(db, br2)      # boshqa filial terminal
    own = _terminal(db, br)
    empf = db.get(Employee, emp.id)
    with pytest.raises(HTTPException) as ei:
        shifts_api.open_shift(shifts_api.OpenShift(opening_cash=0, terminal_id=foreign.id), empf, db)
    assert ei.value.status_code == 400
    db.rollback()
    with pytest.raises(HTTPException):     # yo'q terminal
        shifts_api.open_shift(shifts_api.OpenShift(opening_cash=0, terminal_id=uuid.uuid4()), empf, db)
    db.rollback()
    r = shifts_api.open_shift(shifts_api.OpenShift(opening_cash=0, terminal_id=own.id), empf, db)  # o'z filial -> OK
    assert r["id"]


# ═══ R) discover: ambiguous branch -> empty skeleton + INPUT REQUIRED (read-only) ═
def test_R_discover_ambiguous_emits_empty_skeleton(db, cashenv, capsys):
    import json as _json
    from app.tools import cash_discover
    co, br = _tenant(db, cashenv)
    e = _cashier(db, co, br)
    _shift(db, cashenv, br, e, terminal=None)          # shift history + terminal NULL -> AMBIGUOUS
    before = db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count()
    rc = cash_discover.main(["--company-id", str(co.id), "--json"],
                            session_factory=(lambda: Session(cashenv.engine)), engine=cashenv.engine)
    out = capsys.readouterr().out
    assert rc == 2                                      # OPERATOR INPUT REQUIRED
    payload = _json.loads(out[out.index("{"):out.rindex("}") + 1])
    sk = payload["mapping_skeleton"]["branches"][str(br.id)]
    assert sk["safe"] is True and sk["tills"] == []     # UNKNOWN -> bo'sh (operator to'ldiradi)
    ev = payload["evidence"][0]
    assert ev["operator_input_required"] is True and ev["physical_checkout_count"] == "UNKNOWN"
    assert db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count() == before   # read-only


# ═══ S) discover: terminal evidence -> auto-filled skeleton ══════════════════
def test_S_discover_terminal_autofills_skeleton(db, cashenv, capsys):
    import json as _json
    from app.tools import cash_discover
    co, br = _tenant(db, cashenv)
    tA, tB = _terminal(db, br), _terminal(db, br)
    eA, eB = _cashier(db, co, br), _cashier(db, co, br)
    _shift(db, cashenv, br, eA, terminal=tA); _shift(db, cashenv, br, eB, terminal=tB)
    rc = cash_discover.main(["--company-id", str(co.id), "--all", "--json"],
                            session_factory=(lambda: Session(cashenv.engine)), engine=cashenv.engine)
    out = capsys.readouterr().out
    payload = _json.loads(out[out.index("{"):out.rindex("}") + 1])
    sk = payload["mapping_skeleton"]["branches"][str(br.id)]
    assert len(sk["tills"]) == 2 and {t["terminal_id"] for t in sk["tills"]} == {str(tA.id), str(tB.id)}
    ev = [e for e in payload["evidence"] if e["branch"]["id"] == str(br.id)][0]
    assert ev["operator_input_required"] is False and ev["physical_checkout_count"] == 2
    assert rc == 0                                      # terminal-resolved -> input shart emas


# ═══ ambiguous backfill + operator mapping resolves => writes ═══════════════
def test_D2_operator_mapping_unblocks_backfill(db, cashenv):
    co, br = _tenant(db, cashenv)
    e = _cashier(db, co, br)
    _shift(db, cashenv, br, e, terminal=None, opening="40000", hours_ago=5)   # terminal NULL -> AMBIGUOUS
    mp = _mapping(br, [{"code": "TILL-01", "terminal_id": None, "label": "Kassa 1"}])
    _provision(db, co, mapping=mp, stamp_shifts=False)              # operator 1 TILL bilan hал qildi
    # stamp_shifts=False: smenada till_id YO'Q -> tarixiy dalil yo'q (joriy mapping dalil EMAS)
    assert len(_tills(db, co, br)) == 1
    t0 = _T0(cashenv)
    # §HIST QAT'IY AJRATISH: oddiy `--mapping` = CURRENT provisioning intent. U TARIXIY dalil EMAS,
    # shu bois dalilsiz eski smena legalari HAMON HISTORICAL_TILL_UNKNOWN (retroaktiv biriktirish YO'Q).
    m0 = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True, mapping=mp)
    assert m0["go_no_go"] == "GO" and m0["inserted_rows"] == 0      # bloklamaydi, lekin TAXMIN ham qilmaydi
    assert any(r.get("evidence_class") == "HISTORICAL_TILL_UNKNOWN" for r in m0["review"])
    # ALOHIDA tarixiy attestatsiya berilgandagina yoziladi
    till = _tills(db, co, br)[0]
    # ANIQ shift attestatsiyasi (yakuniy ierarxiya: sources/shifts; vaqt-oynasi YO'Q)
    hm = {"kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "op",
          "shifts": {str(sh.id): str(till.id) for sh in
                     db.query(Shift).filter(Shift.branch_id == br.id).all()}}
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False, mapping=mp,
                                         historical_map=hm)["manifest_hash"]
    m = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=True, approved_hash=approved,
                                  mapping=mp, historical_map=hm)
    assert m["go_no_go"] == "GO" and m["inserted_rows"] >= 1        # attestatsiya bilan backfill o'tdi
