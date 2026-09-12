# -*- coding: utf-8 -*-
"""PHASE 3 — QAYTARISH VA KASSA LEDGERI (partiya kuzatuvi yoqilgan holda).

Phase 2.5 sotuv tomonini isbotlagan edi. Phase 3 qaytarishni PARTIYAGA
bog'laydi, ya'ni bitta tranzaksiyada endi TO'RT narsa bir vaqtda o'zgaradi:
qoldiq, partiyalar, qarz va KASSA. Shu bois quyidagilar ISBOT talab qiladi:

  1. Naqd qaytarish AYNAN BITTA `OUT / REFUND / RETURN` legi yozadi.
  2. Karta/QR qaytarish HECH QANDAY leg yozmaydi.
  3. Takror yuborish IKKINCHI leg yaratmaydi.
  4. Partiya bosqichidagi XATO naqdni HAM, qaytarishni HAM qaytaradi
     (ikkisi bitta tranzaksiyada — yarim holat qolmaydi).
  5. Hisobdan chiqarish va inventarizatsiya kassaga UMUMAN tegmaydi.

⚠️  NEGA POSTGRES. `dual_write_enabled()` SQLite'da DOIM `False` (cash sxemasi
    yo'q) — bu xulqni SQLite'da sinash MUMKIN EMAS.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models.cash import CashLedgerEntry
from app.models.catalog import Product, Unit
from app.models.inventory import Inventory, StockBatch
from app.schemas.sales import SaleCreate
from app.services.sales import create_sale

from tests.cash._factory import make_account

NOW = datetime.now(timezone.utc)
D10 = (NOW + timedelta(days=10)).date()


def _session(env) -> Session:
    return sessionmaker(bind=env.engine, autoflush=False,
                        expire_on_commit=False, class_=Session)()


def _emp(s, cashenv):
    from app.models.auth import Employee
    return s.get(Employee, cashenv.employee_id)


@pytest.fixture(scope="module")
def till(cashenv):
    """⚠️  MODUL UCHUN BITTA TILL. Har testda yangi TILL yasash filialni
        ko'p-TILL qilib qo'yardi; terminalsiz smenada kassa aniqlanmay,
        ledger legi tushib qolardi. Bu MAHSULOT nuqsoni emas, test artefakti —
        haqiqiy do'konda bir kassir bir drawer'da ishlaydi."""
    s = _session(cashenv)
    try:
        return make_account(s, cashenv, "TILL")
    finally:
        s.close()


@pytest.fixture()
def env(cashenv, till):
    """Kompaniya + TILL + KUZATUVLI mahsulot + bitta partiya."""
    s = _session(cashenv)
    unit = s.query(Unit).first()
    if unit is None:
        unit = Unit(id=uuid.uuid4(), code="dona", name="dona")
        s.add(unit); s.flush()
    p = Product(id=uuid.uuid4(), company_id=cashenv.company_id,
                name="Qaytar sinov " + uuid.uuid4().hex[:6],
                article_code="R-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0,
                track_lots=True, track_expiry=False, lots_activated_at=NOW)
    s.add(p); s.flush()
    s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=cashenv.branch_id,
                    qty=Decimal("100"), min_qty=0, updated_at=NOW))
    s.add(StockBatch(id=uuid.uuid4(), company_id=cashenv.company_id,
                     branch_id=cashenv.branch_id, product_id=p.id,
                     qty=Decimal("100"), received_qty=Decimal("100"),
                     remaining_qty=Decimal("100"), unit_cost=Decimal("50"),
                     expiry_date=D10, status="open", source_type="receiving",
                     client_uuid=uuid.uuid4(), received_at=NOW, created_at=NOW,
                     updated_at=NOW, row_version=1))
    s.commit()
    out = (cashenv, till, p.id)
    s.close()
    return out


@pytest.fixture(autouse=True)
def _shift(cashenv, till):
    """Naqd qaytarish OCHIQ smenani talab qiladi — lekin uni O'ZIMIZDAN keyin
    YOPAMIZ.

    ⚠️  `cashenv` SESSIYA doirasida ULASHILADI. Ochiq smena qoldirilsa,
        keyingi fayllar (`test_sale_cash_posting.py`) o'z TILL'ini aniq
        yuborganда «Yuborilgan TILL ochiq smena kassasiga mos emas» (409)
        bilan yiqilardi. Ya'ni sinov o'z mahsulotini emas, FAYL TARTIBINI
        o'lchardi — kanonik to'plamda aynan shunday bo'ldi.
    """
    from app.api.v1 import shifts as shifts_api
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = _session(cashenv)
    try:
        ex = s.query(Shift).filter(Shift.cashier_id == cashenv.employee_id,
                                   Shift.status == ShiftStatus.open).first()
        mine = ex is None
        if mine:
            # ⚠️  TILL ANIQ YUBORILADI. `cashenv` SESSIYA doirasida ulashiladi
            #     va oldingi fayllar ham TILL yaratadi — filial KO'P-TILL
            #     bo'lib qoladi. Terminalsiz, till'siz smenada kassa
            #     aniqlanmay, ledger legi jimgina tushib qolardi va sinov
            #     mahsulotni emas, FAYL TARTIBINI o'lchardi.
            shifts_api.open_shift(
                shifts_api.OpenShift(opening_cash=1000000, till_id=till.id),
                _emp(s, cashenv), s)
    finally:
        s.close()
    yield
    if not mine:
        return
    s = _session(cashenv)
    try:
        # To'g'ridan-to'g'ri yopamiz: `close_shift` ledger'ga leg yozib,
        # shu faylning O'Z tekshiruvlarini buzardi.
        for sh in s.query(Shift).filter(Shift.cashier_id == cashenv.employee_id,
                                        Shift.status == ShiftStatus.open).all():
            sh.status = ShiftStatus.closed
            sh.closed_at = NOW
        s.commit()
    finally:
        s.close()


def _sell(cashenv, pid, qty=4, price=100):
    s = _session(cashenv)
    try:
        return create_sale(s, _emp(s, cashenv), SaleCreate(
            items=[{"product_id": str(pid), "qty": qty, "unit_price": price}],
            payment_method="cash", given_amount=qty * price + 1000,
            client_uuid=uuid.uuid4()))
    finally:
        s.close()


def _ret(cashenv, sale_id, pid, qty, *, method="cash", restock=True, cu=None):
    from app.api.v1.sales import create_return
    from app.schemas.sales import ReturnCreate
    s = _session(cashenv)
    try:
        return create_return(ReturnCreate(
            original_sale_id=sale_id, reason="customer", restock=restock,
            refund_method=method, client_uuid=cu or uuid.uuid4(),
            items=[{"product_id": str(pid), "qty": qty, "unit_price": 0}]),
            emp=_emp(s, cashenv), db=s)
    finally:
        s.close()


def _legs(cashenv, return_id):
    s = _session(cashenv)
    try:
        return s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id,
            CashLedgerEntry.source_type == "RETURN",
            CashLedgerEntry.source_id == return_id).all()
    finally:
        s.close()


def _lots(cashenv, pid):
    s = _session(cashenv)
    try:
        return [(Decimal(str(b.remaining_qty)), b.status)
                for b in s.query(StockBatch).filter(StockBatch.product_id == pid).all()]
    finally:
        s.close()


# ══ 1. NAQD QAYTARISH — AYNAN BITTA OUT/REFUND LEGI ═════════════════════════

def test_NAQD_qaytarish_AYNAN_BITTA_leg(env):
    cashenv, till, pid = env
    sale = _sell(cashenv, pid, qty=4)
    r = _ret(cashenv, sale.id, pid, 2)
    legs = _legs(cashenv, uuid.UUID(str(r["id"])))
    assert len(legs) == 1, f"{len(legs)} ta leg — bittadan boshqa"
    leg = legs[0]
    assert leg.direction == "OUT", leg.direction
    assert leg.category == "REFUND", leg.category
    assert Decimal(str(leg.amount)) == Decimal(str(r["total"])), (leg.amount, r["total"])
    # Partiya ham qaytdi — kassa va ombor BITTA tranzaksiyada.
    assert _lots(cashenv, pid) == [(Decimal("98.000"), "open")]


@pytest.mark.parametrize("method", ["card", "qr"])
def test_KARTA_va_QR_qaytarish_leg_YARATMAYDI(env, method):
    """Bu usullarda kassadan pul CHIQMAYDI — leg yozish yo'q pulni ko'rsatardi."""
    cashenv, till, pid = env
    s = _session(cashenv)
    try:
        sale = create_sale(s, _emp(s, cashenv), SaleCreate(
            items=[{"product_id": str(pid), "qty": 4, "unit_price": 100}],
            payments=[{"method": method, "amount": 400}],
            client_uuid=uuid.uuid4()))
    finally:
        s.close()
    r = _ret(cashenv, sale.id, pid, 2, method=method)
    assert _legs(cashenv, uuid.UUID(str(r["id"]))) == []


def test_TAKROR_yuborish_IKKINCHI_leg_yaratmaydi(env):
    """⚠️  Ledger idempotentligi (`source_id`) BU YERDA ishlamaydi — har so'rov
        YANGI `Return.id` yaratardi. Haqiqiy himoya — `client_uuid` bo'yicha
        qaytarishning O'ZINI dublikat deb qaytarish (`ux_returns_client_uuid`).
        Shu bois test aynan shuni o'lchaydi.
    """
    cashenv, till, pid = env
    sale = _sell(cashenv, pid, qty=4)
    cu = uuid.uuid4()
    r1 = _ret(cashenv, sale.id, pid, 2, cu=cu)
    r2 = _ret(cashenv, sale.id, pid, 2, cu=cu)
    assert str(r1["id"]) == str(r2["id"]), "takror YANGI qaytarish yaratdi"
    assert len(_legs(cashenv, uuid.UUID(str(r1["id"])))) == 1
    # Partiya ham BIR MARTA qaytdi.
    assert _lots(cashenv, pid) == [(Decimal("98.000"), "open")]


# ══ 2. PARTIYA XATOSI NAQDNI HAM QAYTARADI ══════════════════════════════════

def test_partiya_xatosi_NAQD_legini_HAM_qaytaradi(env, monkeypatch):
    """⚠️  Naqd legi qaytarishdan OLDIN post qilinadi. Keyingi partiya xatosi
        tranzaksiyani bekor qilsa, leg HAM yo'qolishi SHART — aks holda kassada
        chiqmagan pul ko'rinardi va smena hech qachon yopilmasdi.
    """
    from app.services import lot_return as LR
    cashenv, till, pid = env
    sale = _sell(cashenv, pid, qty=4)

    oldin = _lots(cashenv, pid)

    def boom(*a, **kw):
        raise RuntimeError("partiya bosqichida sun'iy xato")
    monkeypatch.setattr(LR, "apply", boom)

    with pytest.raises(RuntimeError):
        _ret(cashenv, sale.id, pid, 2)

    # Na qaytarish, na leg, na partiya o'zgarishi qolsin.
    s = _session(cashenv)
    try:
        from app.models.sales import Return
        assert s.query(Return).filter(
            Return.original_sale_id == sale.id).count() == 0
        # ⚠️  Doira SHU chek bilan cheklanadi: `cashenv` modul bo'yicha
        #     ULASHILADI, ya'ni oldingi testlarning legi qonuniy ravishda
        #     mavjud. Global nol talab qilish testni fayl tartibiga bog'lardi.
        assert s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id,
            CashLedgerEntry.source_type == "RETURN",
            CashLedgerEntry.source_id.in_(
                s.query(Return.id).filter(Return.original_sale_id == sale.id))
        ).count() == 0
    finally:
        s.close()
    assert _lots(cashenv, pid) == oldin, "partiya yarim holatda qoldi"


# ══ 3. OMBOR AMALLARI KASSAGA TEGMAYDI ══════════════════════════════════════

def test_HISOBDAN_CHIQARISH_va_SANOQ_ledgerga_tegmaydi(env):
    """Tashlangan/sanalgan tovar — zaxira hodisasi, kassa hodisasi EMAS."""
    from app.api.v1.inventory import CountIn, WriteoffIn, stock_count, writeoff
    cashenv, till, pid = env
    s = _session(cashenv)
    try:
        b = s.query(StockBatch).filter(StockBatch.product_id == pid).first()
        blot = str(b.id)
        oldin = s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id).count()
    finally:
        s.close()

    s = _session(cashenv)
    try:
        writeoff(WriteoffIn(product_id=pid, qty=3, reason="brak",
                            client_uuid=uuid.uuid4(),
                            lots=[{"stock_batch_id": blot, "qty": 3}]),
                 emp=_emp(s, cashenv), db=s)
    finally:
        s.close()
    s = _session(cashenv)
    try:
        stock_count(CountIn(items=[{"product_id": pid, "counted": 90,
                                    "lots": [{"stock_batch_id": blot, "counted": 90}]}],
                            client_uuid=uuid.uuid4()), emp=_emp(s, cashenv), db=s)
    finally:
        s.close()

    s = _session(cashenv)
    try:
        keyin = s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id).count()
    finally:
        s.close()
    assert keyin == oldin, f"ombor amali ledgerga {keyin - oldin} ta leg yozdi"
