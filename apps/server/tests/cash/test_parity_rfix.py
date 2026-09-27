# -*- coding: utf-8 -*-
"""R-fix — JONLI report/reconciliation parity nuqsonlari (real PostgreSQL).

Bular DIZAYN emas, BUGUNGI kod nuqsonlari: kutilgan tomon (`phase1`) runtime yozayotgan
shakllarni bilmaydi, shu bois `reconcile_events` yolg'on mismatch beradi.

  A  inkassa = TILL->SAFE **TRANSFER JUFTLIGI**; kutilgan tomon bitta `CASH_OP` leg kutardi
     -> 1x MISSING_LEDGER + 2x EXTRA_LEDGER
  B  oddiy bitta oyoqli naqd xarid (NAZORAT — smena ostida)
  C  ko'p oyoqli xarid: uchinchi oyoq ham yig'indiga kiradi
  D  `edit_purchase` summani OSHIRSA -> leg-1 (delta) yoziladi; kutilgan tomon bitta leg kutardi
     -> WRONG_AMOUNT (leg-0) + EXTRA_LEDGER (leg-1)
  E  reversal identiteti (yozuvchi hali YO'Q — shartnoma drift qilmasin)
  F  boshqa `CASH_OP` xatti-harakati O'ZGARMAYDI (nazorat)
  G  MANFIY NAZORAT: haqiqiy ortiqcha/kam/noto'g'ri leg HAMON tutiladi

⚠️  Bu testlar kutilgan tomon tuzatilmaguncha QIZIL. Ular «ko'p leg bo'lsa mayli» degan
    umumiy qoidani sinamaydi — har bir qabul qilingan leg MANBA SHARTNOMASI bo'yicha
    atributlanadi (G guruhi shuni qotiradi).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.api.v1 import purchases as purchases_api
from app.api.v1 import shifts as shifts_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.catalog import Product, Unit
from app.models.org import Branch, Company
from app.models.purchasing import Supplier
from app.models.inventory import Inventory
from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
from app.services.cash import compare_engine as ce
from app.services.cash import mode
from app.services.cash import till_identity as _ti


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _T0():
    """Barcha test amallari SHU chegaradan KEYIN — ya'ni LIVE (dual-write) hududi."""
    return _now() - timedelta(days=1)


def _acct(db, co, br, typ):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type=typ, currency="UZS", status="ACTIVE",
                    label=(_ti.till_label("T-" + _hex(), None) if typ == "TILL"
                           else _ti.safe_label("S-" + _hex())), created_at=_now())
    db.add(a); db.flush(); return a


def _tenant(db):
    """Yangi TENANT + filial + xodim + TILL + SAFE (toza reconcile uchun)."""
    co = Company(name="RF" + _hex(), code="rf" + _hex(), currency="UZS"); db.add(co); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True); db.add(br); db.flush()
    emp = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(emp); db.flush(); db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = _acct(db, co, br, "TILL")
    safe = _acct(db, co, br, "SAFE")
    db.commit()
    return co, br, emp, till, safe


def _product(db, co, br, buy="1000"):
    u = Unit(code="u" + _hex(), name="dona"); db.add(u); db.flush()
    p = Product(company_id=co.id, article_code="A" + _hex(), name="M" + _hex(), unit_id=u.id,
                base_buy_price=Decimal(buy), base_sell_price=Decimal("2000"), tax_rate=Decimal("0"))
    db.add(p); db.flush()
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal("0"), updated_at=_now()))
    db.commit(); return p


def _supplier(db, co):
    s = Supplier(company_id=co.id, name="S" + _hex()); db.add(s); db.commit(); return s


def _open(db, emp, opening=0):
    return uuid.UUID(shifts_api.open_shift(shifts_api.OpenShift(opening_cash=opening), emp, db)["id"])


def _mv(db, emp, sid, mtype, amt, *, safe_id=None, cu=None):
    return shifts_api.add_cash_movement(
        sid, shifts_api.CashMove(type=mtype, amount=amt, client_uuid=cu,
                                 destination_safe_id=safe_id), emp, db)


def _buy(db, emp, sup, prod, qty=1, cost="5000"):
    """NAQD xarid (received) — API yo'li bilan (runtime OUT-PURCHASE_OUT legi yoziladi)."""
    out = purchases_api._create_purchase_once(
        PurchaseCreate(supplier_id=sup.id, status="received",
                       items=[PurchaseItemIn(product_id=prod.id, qty=qty, unit_cost=float(cost))]),
        emp, db)
    return uuid.UUID(str(out.id if hasattr(out, "id") else out["id"]))


def _rec(db, co):
    return ce.reconcile_events(db, co.id, t0=_T0())


def _codes(r):
    return r["mismatch_counts"]


# ═══ A) INKASSA = TRANSFER JUFTLIGI ══════════════════════════════════════════
def test_A_inkassa_juft_transfer_parity(db, cashenv):
    """Runtime `TRANSFER`/`movement_id` ostida IKKI oyoq yozadi (0 OUT TILL, 1 IN SAFE);
    kutilgan tomon esa bitta `CASH_OP` OUT-CASH_OUT legi kutardi."""
    co, br, emp, till, safe = _tenant(db)
    sid = _open(db, emp, opening=10000)
    _mv(db, emp, sid, "collection", 3000, safe_id=safe.id)
    db.commit()

    legs = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.source_type == "TRANSFER").all()
    assert len(legs) == 2, "runtime inkassani JUFT transfer qilib yozadi"
    assert {(x.leg_index, x.direction) for x in legs} == {(0, "OUT"), (1, "IN")}

    r = _rec(db, co)
    assert _codes(r).get(ce.MISSING_LEDGER) is None, "inkassa uchun yolg'on MISSING_LEDGER"
    assert _codes(r).get(ce.EXTRA_LEDGER) is None, "transfer oyoqlari ortiqcha deb belgilanmasin"
    assert r["mismatch_total"] == 0, r["mismatch_counts"]


def test_A2_inkassa_manzil_seyf_tipi_tekshiriladi(db, cashenv):
    """IN oyog'i shu tenantning SEYFiga tushishi SHART. Manba qatorda manzil ustuni YO'Q
    (`cash_movements`), shu bois shartnoma TIP darajasida — «tekshirmaymiz» EMAS.

    Ledger APPEND-ONLY, shu bois yozilgan legni o'zgartirib bo'lmaydi: inkassa qatorini
    ledgersiz yozamiz (LEGACY_ONLY), so'ng AYNI `source_id` ostida TILL->TILL transfer
    post qilamiz — ya'ni manzil SEYF EMAS."""
    from app.models.shifts import CashMovement
    from app.services.cash import adapters as _ad
    co, br, emp, till, safe = _tenant(db)
    sid = _open(db, emp, opening=10000)     # ⚠️ ikkinchi TILL SMENADAN KEYIN: aks holda
    till2 = _acct(db, co, br, "TILL")       #    `resolve_till` noaniq bo'lib shift.till_id=None
    db.commit()
    mode.set_mode(mode.CashMode.LEGACY_ONLY)
    try:
        _mv(db, emp, sid, "collection", 3000, safe_id=safe.id)
    finally:
        mode.reset_mode()
    db.commit()
    mid = db.query(CashMovement.id).filter(CashMovement.shift_id == sid).scalar()
    _ad.transfer(db, emp, from_account_id=till.id, to_account_id=till2.id,
                 amount=Decimal("3000"), source_id=mid, commit=True)
    r = _rec(db, co)
    assert ce.WRONG_ACCOUNT in "+".join(_codes(r)), r["mismatch_counts"]


# ═══ B) NAZORAT: oddiy bitta oyoqli naqd xarid ═══════════════════════════════
def test_B_oddiy_naqd_xarid_parity(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    sup, prod = _supplier(db, co), _product(db, co, br)
    _open(db, emp, opening=100000)
    _buy(db, emp, sup, prod, qty=1, cost="5000")
    db.commit()
    legs = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "PURCHASE_OUT").all()
    assert len(legs) == 1 and legs[0].leg_index == 0
    r = _rec(db, co)
    assert r["mismatch_total"] == 0, r["mismatch_counts"]


# ═══ C) ko'p oyoqli xarid (uch oyoq) ═════════════════════════════════════════
def test_C_kop_oyoqli_xarid_yigindi_bilan_moslashadi(db, cashenv):
    """`on_cash_purchase_increase` immutable append qiladi: leg-0 asl, leg-1.. delta.
    Kutilgan tomon `Purchase.total` ni biladi — ya'ni OYOQLAR YIG'INDISINI."""
    from app.services.cash import retrofit as _cr
    co, br, emp, till, safe = _tenant(db)
    sup, prod = _supplier(db, co), _product(db, co, br)
    _open(db, emp, opening=100000)
    pid = _buy(db, emp, sup, prod, qty=1, cost="5000")
    from app.models.purchasing import Purchase
    pur = db.get(Purchase, pid)
    for extra in (Decimal("1500"), Decimal("500")):
        _cr.on_cash_purchase_increase(db, emp, branch_id=br.id, purchase_id=pid,
                                      extra_amount=extra, cash_account_id=till.id)
        pur.total = Decimal(str(pur.total)) + extra
        pur.paid_amount = Decimal(str(pur.paid_amount or 0)) + extra
        db.add(pur); db.commit()
    legs = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "PURCHASE_OUT").all()
    assert len(legs) == 3 and sum(x.amount for x in legs) == Decimal("7000.00")
    r = _rec(db, co)
    assert r["mismatch_total"] == 0, r["mismatch_counts"]


# ═══ D) edit_purchase summani OSHIRSA -> keyingi leg ═════════════════════════
def test_D_edit_purchase_oshirish_parity(db, cashenv):
    """API yo'li: qty 1 -> 2 (5000 -> 10000). Runtime leg-0 ni O'ZGARTIRMAYDI, delta uchun
    leg-1 yozadi. Kutilgan tomon bitta leg (`total + qaytarishlar`) kutardi."""
    co, br, emp, till, safe = _tenant(db)
    sup, prod = _supplier(db, co), _product(db, co, br)
    _open(db, emp, opening=100000)
    pid = _buy(db, emp, sup, prod, qty=1, cost="5000")
    from app.models.purchasing import PurchaseItem
    it = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pid).one()
    purchases_api.edit_purchase(pid, purchases_api.PurchaseEdit(
        items=[purchases_api.PItemEdit(id=it.id, qty=2, unit_cost=5000)]), emp, db)
    db.commit()

    legs = sorted(db.query(CLE).filter(CLE.tenant_id == co.id,
                                       CLE.category == "PURCHASE_OUT").all(),
                  key=lambda x: x.leg_index)
    assert [x.leg_index for x in legs] == [0, 1]
    assert [x.amount for x in legs] == [Decimal("5000.00"), Decimal("5000.00")]

    r = _rec(db, co)
    assert _codes(r).get(ce.WRONG_AMOUNT) is None, "leg-0 asl summada qoladi — bu XATO emas"
    assert _codes(r).get(ce.EXTRA_LEDGER) is None, "delta legi ortiqcha EMAS"
    assert r["mismatch_total"] == 0, r["mismatch_counts"]


def test_D2_kamaytirish_qaytarish_legi_parity(db, cashenv):
    """Simmetrik tomon (bugun ishlaydi — regressiya qo'riqchisi): summa KAMAYTIRILSA
    `PurchaseReturn` + IN legi yoziladi va ikkala tomon ham moslashadi."""
    co, br, emp, till, safe = _tenant(db)
    sup, prod = _supplier(db, co), _product(db, co, br)
    _open(db, emp, opening=100000)
    pid = _buy(db, emp, sup, prod, qty=2, cost="5000")
    from app.models.purchasing import PurchaseItem
    it = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pid).one()
    purchases_api.edit_purchase(pid, purchases_api.PurchaseEdit(
        items=[purchases_api.PItemEdit(id=it.id, qty=1, unit_cost=5000)]), emp, db)
    db.commit()
    r = _rec(db, co)
    assert r["mismatch_total"] == 0, r["mismatch_counts"]


# ═══ E) REVERSAL identiteti (yozuvchi YO'Q — drift qo'riqchisi) ══════════════
def test_E_reversal_shartnomasi_drift_qilmaydi(db, cashenv):
    """`CashPostingService` reversal shartnomasi: YANGI `source_id`, `leg_index=0`,
    `category=ADJUSTMENT`, teskari yo'nalish. Dizayn ayni shunga tayanadi."""
    import dataclasses

    from app.services.cash import adapters as _ad
    from app.services.cash.commands import ReversalCommand
    co, br, emp, till, safe = _tenant(db)
    _ad.manual_cash_in(db, emp, cash_account_id=till.id, source_id=uuid.uuid4(),
                       amount=Decimal("9000"), commit=True)
    orig = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.category == "CASH_IN").one()

    res = _ad.reversal(db, emp, reverses_id=orig.id, commit=True)
    rev = db.query(CLE).filter(CLE.tenant_id == co.id, CLE.reverses_id == orig.id).one()
    assert str(rev.source_id) != str(orig.source_id), "reversal YANGI source_id oladi"
    assert rev.leg_index == 0
    assert rev.category == "ADJUSTMENT"
    assert rev.direction == "OUT" and orig.direction == "IN"
    assert rev.cash_account_id == orig.cash_account_id
    assert res is not None

    fields = {f.name for f in dataclasses.fields(ReversalCommand)}
    assert "leg_index" not in fields, "ReversalCommand'да leg_index YO'Q — dizayn shunga tayanadi"

    with pytest.raises(Exception):
        _ad.reversal(db, emp, reverses_id=orig.id, commit=True)   # ikkinchi reversal RAD


# ═══ F) NAZORAT: boshqa CASH_OP o'zgarmaydi ══════════════════════════════════
def test_F_boshqa_cashop_ozgarmaydi(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    sid = _open(db, emp, opening=10000)
    _mv(db, emp, sid, "payin", 500)
    _mv(db, emp, sid, "expense", 700)
    _mv(db, emp, sid, "payout", 300)
    db.commit()
    r = _rec(db, co)
    assert r["mismatch_total"] == 0, r["mismatch_counts"]
    assert r["matched"] >= 4      # OPENING + payin + expense + payout


# ═══ G) MANFIY NAZORAT: haqiqiy anomaliya HAMON tutiladi ════════════════════
def test_G1_ortiqcha_xarid_legi_tutiladi(db, cashenv):
    """Yig'indi qoidasi «ko'p leg bo'lsa mayli» EMAS: manbasiz qo'shimcha summa -> WRONG_AMOUNT."""
    from app.services.cash import retrofit as _cr
    co, br, emp, till, safe = _tenant(db)
    sup, prod = _supplier(db, co), _product(db, co, br)
    _open(db, emp, opening=100000)
    pid = _buy(db, emp, sup, prod, qty=1, cost="5000")
    _cr.on_cash_purchase_increase(db, emp, branch_id=br.id, purchase_id=pid,
                                  extra_amount=Decimal("2500"), cash_account_id=till.id)
    db.commit()          # `Purchase.total` ATAYLAB yangilanmadi -> manba yo'q
    r = _rec(db, co)
    assert ce.WRONG_AMOUNT in "+".join(_codes(r)), r["mismatch_counts"]


def test_G2_yoqolgan_xarid_legi_tutiladi(db, cashenv):
    """Kam leg ham tutiladi. Ledger APPEND-ONLY (DB trigger `fn_block_mutation` DELETE'ni
    rad etadi), shu bois legni o'chirmaymiz — dual-write'ni O'CHIRIB umuman yozmaymiz."""
    co, br, emp, till, safe = _tenant(db)
    sup, prod = _supplier(db, co), _product(db, co, br)
    _open(db, emp, opening=100000)
    mode.set_mode(mode.CashMode.LEGACY_ONLY)        # ledger legi YOZILMAYDI
    try:
        _buy(db, emp, sup, prod, qty=1, cost="5000")
    finally:
        mode.reset_mode()
    db.commit()
    assert db.query(CLE).filter(CLE.tenant_id == co.id,
                                CLE.category == "PURCHASE_OUT").count() == 0
    r = _rec(db, co)
    assert _codes(r).get(ce.MISSING_LEDGER) == 1, r["mismatch_counts"]


def test_G3_begona_leg_hamon_ortiqcha(db, cashenv):
    """Manbasiz TRANSFER juftligi (inkassa qatori YO'Q) HAMON EXTRA_LEDGER."""
    from app.services.cash import adapters as _ad
    co, br, emp, till, safe = _tenant(db)
    _open(db, emp, opening=10000)          # qonuniy OPENING legi (moslashadi)
    _ad.transfer(db, emp, from_account_id=till.id, to_account_id=safe.id,
                 amount=Decimal("1000"), source_id=uuid.uuid4(), commit=True)
    r = _rec(db, co)
    assert _codes(r).get(ce.EXTRA_LEDGER) == 2, r["mismatch_counts"]
    assert r["matched"] == 1


# ═══ H) REJIM DARVOZASI: LEGACY_ONLY da ledger'ga HECH NARSA yozilmaydi ══════
def test_H1_legacy_only_inkassa_ledgerga_yozmaydi(db, cashenv):
    """`on_cash_collection` ilgari `cash_enabled` (FAQAT infra) bilan darvozalangan edi —
    `LEGACY_ONLY` rejimda butun deploy ledger'ga yozmasa ham inkassa IKKI leg yozardi."""
    co, br, emp, till, safe = _tenant(db)
    sid = _open(db, emp, opening=10000)
    mode.set_mode(mode.CashMode.LEGACY_ONLY)
    try:
        _mv(db, emp, sid, "collection", 3000, safe_id=safe.id)
        db.commit()
    finally:
        mode.reset_mode()
    assert db.query(CLE).filter(CLE.tenant_id == co.id,
                                CLE.source_type == "TRANSFER").count() == 0


def test_H2_legacy_only_bank_deposit_ledgerga_yozmaydi(db, cashenv):
    from app.services.cash import retrofit as _cr
    co, br, emp, till, safe = _tenant(db)
    mode.set_mode(mode.CashMode.LEGACY_ONLY)
    try:
        assert _cr.on_bank_deposit(db, emp, from_safe_id=safe.id, amount=Decimal("100"),
                                   movement_id=uuid.uuid4(), commit=True) is None
    finally:
        mode.reset_mode()
    assert db.query(CLE).filter(CLE.tenant_id == co.id).count() == 0


def test_H3_darvoza_qardosh_hooklar_bilan_bir_xil(db, cashenv):
    """Manba ko'rigi: naqd hook'larning BIRORTASI rejimni chetlab o'tmasin."""
    import inspect

    from app.services.cash import retrofit as _cr
    src = inspect.getsource(_cr)
    for fn in ("on_cash_collection", "on_bank_deposit"):
        body = src[src.index("def " + fn):]
        body = body[:body.index("\ndef ", 1)]
        assert "dual_write_enabled(db)" in body, fn + " rejim darvozasisiz"
        assert "if not cash_enabled(db)" not in body, fn + " FAQAT infra darvozasi"


# ═══ I) FAIL-LOUD: tenantsiz reconcile yolg'on hisobot berardi ═══════════════
def test_I_tenantsiz_reconcile_rad_etiladi(db, cashenv):
    """`company_id=None` bo'lsa kutilgan tomon HAMMA tenant uchun qurilib, haqiqiy tomon
    `tenant_id IS NULL` (ustun NOT NULL) tufayli BO'SH bo'lardi — ya'ni har hodisa
    MISSING_LEDGER. Endi BALAND OVOZDA rad etiladi."""
    with pytest.raises(ValueError, match="AYNIQ tenant"):
        ce.reconcile_events(db, None, t0=_T0())
