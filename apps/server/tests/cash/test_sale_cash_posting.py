# -*- coding: utf-8 -*-
"""PHASE 2.5 — SOTUVNING NAQD LEDGER LEGI (kritik nuqson tuzatildi).

ILDIZ SABAB
===========
`SessionLocal` da `autoflush=False` (`app/db/session.py`). Sotuv yo'li naqd
summani BAZADAN `SUM(SalePayment.amount)` bilan o'qirdi, `SalePayment` qatorlari
esa hali sessiyada KUTIB turgan edi — ya'ni SUM DOIM `0` qaytarardi,
`if _cash_amt > 0` hech qachon bajarilmasdi va `on_cash_sale` HECH QACHON
chaqirilmasdi. Natijada NAQD SOTUV ledger'ga UMUMAN tushmasdi.

⚠️  Faqat SOTUV yo'li kasal edi. Qaytarish (`api/v1/sales.py`) va qarz to'lovi
    (`api/v1/customers.py`) summani TO'G'RIDAN-TO'G'RI uzatadi, shu bois ular
    ishlagan — nuqson aynan SUM-dan-o'qish naqshida edi.

TUZATISH: SUM'dan OLDIN `db.flush()`. Summa ataylab YOZILGAN (butun so'mga
yaxlitlangan, oxirgi leg qoldiqni yutgan) qatorlardan olinadi — ledger haqiqiy
naqd bilan tiyin-ba-tiyin mos bo'lishi uchun.

⚠️  NEGA POSTGRES. `dual_write_enabled()` SQLite'da DOIM `False` (cash sxemasi
    yo'q), ya'ni bu xulqni SQLite'da sinash MUMKIN EMAS — mahalliy to'plam
    nuqsonni ko'ra olmasdi va ko'rmadi ham.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.cash import CashAccount, CashLedgerEntry
from app.models.catalog import Product, Unit
from app.models.inventory import Inventory
from app.models.sales import Sale
from app.schemas.sales import SaleCreate
from app.services.sales import create_sale

from tests.cash._factory import make_account

NOW = datetime.now(timezone.utc)


def _session(env) -> Session:
    """⚠️  ILOVA BILAN AYNI sozlama — `autoflush=False`. Aynan shu sozlama
    nuqsonni tug'dirgan, shu bois test uni TAKRORLASHI shart."""
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=env.engine, autoflush=False,
                        expire_on_commit=False, class_=Session)()


@pytest.fixture()
def env(cashenv):
    """Kompaniya + TILL + kuzatuvsiz mahsulot + qoldiq."""
    s = _session(cashenv)
    till = make_account(s, cashenv, "TILL")
    unit = s.query(Unit).first()
    if unit is None:
        unit = Unit(id=uuid.uuid4(), code="dona", name="dona")
        s.add(unit); s.flush()
    p = Product(id=uuid.uuid4(), company_id=cashenv.company_id,
                name="Naqd sinov " + uuid.uuid4().hex[:6],
                article_code="C-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
    s.add(p); s.flush()
    s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=cashenv.branch_id,
                    qty=Decimal("1000"), min_qty=0, updated_at=NOW))
    s.commit()
    out = (cashenv, till, p.id)
    s.close()
    return out


def _emp(s, cashenv):
    from app.models.auth import Employee
    return s.get(Employee, cashenv.employee_id)


def _sell(cashenv, pid, *, payments=None, method="cash", qty=1, price=100,
          cu=None, till_id=None, honor=False):
    s = _session(cashenv)
    try:
        body = {"items": [{"product_id": str(pid), "qty": qty, "unit_price": price}],
                "client_uuid": cu or uuid.uuid4()}
        if payments is not None:
            body["payments"] = payments
        else:
            body["payment_method"] = method
            body["given_amount"] = qty * price + 1000
        if till_id:
            body["till_id"] = till_id
        return create_sale(s, _emp(s, cashenv), SaleCreate(**body),
                           honor_price_snapshot=honor)
    finally:
        s.close()


def _legs(cashenv, sale_id):
    s = _session(cashenv)
    try:
        return s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id,
            CashLedgerEntry.source_type == "SALE",
            CashLedgerEntry.source_id == sale_id).all()
    finally:
        s.close()


# ══ 1. NAQD SOTUV — AYNAN BITTA LEG ═════════════════════════════════════════

def test_NAQD_sotuv_AYNAN_BITTA_leg_yozadi(env):
    """ASOSIY TUZATISH. Ilgari BITTA HAM leg yozilmasdi."""
    cashenv, till, pid = env
    sale = _sell(cashenv, pid, method="cash", qty=1, price=100, till_id=till.id)
    legs = _legs(cashenv, sale.id)
    assert len(legs) == 1, f"{len(legs)} ta leg (kutilgan 1) — naqd ledger'ga tushmadi"
    leg = legs[0]
    assert leg.direction == "IN"
    assert leg.category == "SALE"
    assert Decimal(str(leg.amount)) == Decimal("100")
    assert leg.cash_account_id == till.id, "leg boshqa kassaga tushdi"


def test_leg_summasi_YOZILGAN_tolovga_TENG(env):
    """Ledger xom so'rovdan emas, SAQLANGAN (yaxlitlangan) summadan olinadi."""
    from app.models.sales import SalePayment
    cashenv, till, pid = env
    sale = _sell(cashenv, pid, method="cash", qty=3, price=333, till_id=till.id)
    s = _session(cashenv)
    try:
        paid = sum((Decimal(str(x.amount)) for x in s.query(SalePayment).filter(
            SalePayment.sale_id == sale.id, SalePayment.method_code == "cash").all()),
            Decimal("0"))
    finally:
        s.close()
    legs = _legs(cashenv, sale.id)
    assert len(legs) == 1
    assert Decimal(str(legs[0].amount)) == paid, (legs[0].amount, paid)


# ══ 2. NAQD BO'LMAGAN USULLAR — LEG YO'Q ════════════════════════════════════

@pytest.mark.parametrize("method", ["card", "qr"])
def test_KARTA_va_QR_naqd_leg_YARATMAYDI(env, method):
    """Kod izohi: «karta/QR qismi ledger'ga tegmaydi» (retrofit.on_cash_sale)."""
    cashenv, till, pid = env
    sale = _sell(cashenv, pid, method=method, till_id=till.id)
    assert _legs(cashenv, sale.id) == [], f"{method} uchun naqd leg yozildi"


def test_ARALASH_tolovda_FAQAT_naqd_ulushi(env):
    """100 naqd + 150 karta -> ledger'da FAQAT 100."""
    cashenv, till, pid = env
    # ⚠️  ONLAYN sotuvda narx MAHSULOTDAN olinadi (`base_sell_price` = 100),
    #     so'rovdagi `unit_price` E'TIBORGA OLINMAYDI (narx-manipulyatsiya
    #     yopiq). Shu bois to'lovlar 100 ga teng bo'lishi shart.
    sale = _sell(cashenv, pid, qty=1, till_id=till.id,
                 payments=[{"method": "cash", "amount": 40},
                           {"method": "card", "amount": 60}])
    legs = _legs(cashenv, sale.id)
    assert len(legs) == 1, f"{len(legs)} ta leg"
    assert Decimal(str(legs[0].amount)) == Decimal("40"), "karta ulushi ham yozildi"


# ══ 3. TAKROR — DUBLIKAT LEG YO'Q ═══════════════════════════════════════════

def test_AYNI_chek_takrori_IKKINCHI_leg_yaratmaydi(env):
    """Idempotentlik biznes kalitida: (tenant, SALE, sale_id, leg_index)."""
    cashenv, till, pid = env
    cu = uuid.uuid4()
    a = _sell(cashenv, pid, method="cash", cu=cu, till_id=till.id)
    b = _sell(cashenv, pid, method="cash", cu=cu, till_id=till.id)
    assert a.id == b.id, "takror YANGI sotuv yaratdi"
    legs = _legs(cashenv, a.id)
    assert len(legs) == 1, f"{len(legs)} ta leg — takror dublikat yozdi"


def test_OFFLINE_replay_ham_BITTA_leg(env):
    """`/sync/push` yo'li (honor_price_snapshot=True) ham to'g'ri post qiladi."""
    cashenv, till, pid = env
    sale = _sell(cashenv, pid, method="cash", till_id=till.id, honor=True)
    legs = _legs(cashenv, sale.id)
    assert len(legs) == 1
    assert Decimal(str(legs[0].amount)) == Decimal("100")


# ══ 4. TRANZAKSIYA BUTUNLIGI ════════════════════════════════════════════════

def test_naqd_postdan_KEYINGI_xato_HAMMASINI_qaytaradi(env, monkeypatch):
    """Naqd leg yozilgach yiqilsa — sotuv ham, leg ham QOLMASIN."""
    from app.services import stock_invariant as SI
    cashenv, till, pid = env
    s = _session(cashenv)
    try:
        before_sales = s.query(Sale).filter(Sale.company_id == cashenv.company_id).count()
        before_legs = s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id).count()
    finally:
        s.close()

    import app.services.sales as S

    def boom(*a, **k):
        raise RuntimeError("sun'iy xato: naqd postdan keyin")
    # Naqd post `db.commit()` dan DARHOL oldin — uni commit bilan orasiga
    # portlatish uchun `commit` ni bir marta yiqitamiz.
    _orig_commit = Session.commit
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("sun'iy xato: commit paytida")
        return _orig_commit(self, *a, **k)
    monkeypatch.setattr(Session, "commit", flaky)

    s2 = _session(cashenv)
    try:
        with pytest.raises(Exception):
            create_sale(s2, _emp(s2, cashenv), SaleCreate(
                items=[{"product_id": str(pid), "qty": 1, "unit_price": 100}],
                payment_method="cash", given_amount=200, till_id=till.id,
                client_uuid=uuid.uuid4()))
    finally:
        s2.rollback(); s2.close()
    monkeypatch.undo()

    s3 = _session(cashenv)
    try:
        assert s3.query(Sale).filter(
            Sale.company_id == cashenv.company_id).count() == before_sales, \
            "yiqilgan sotuv bazada qoldi"
        assert s3.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id).count() == before_legs, \
            "yiqilgan sotuvning naqd legi QOLDI"
    finally:
        s3.close()


# ══ 5. KUTILGAN SMENA NAQDI ═════════════════════════════════════════════════

def test_TILL_dagi_naqd_legi_yigindisi_OSHADI(env):
    """Ledger legi kassadagi naqd yig'indisini HAQIQATAN oshiradi.

    ⚠️  `ledger_expected_shift_cash()` ATAYLAB ishlatilmadi: u `shift_id` talab
        qiladi va ochiq smena qurishni ko'zda tutadi — bu Phase 2.5 mavzusi
        emas. Bu yerda ledger ta'siri TO'G'RIDAN-TO'G'RI o'lchanadi.
    """
    from sqlalchemy import func
    cashenv, till, pid = env

    def till_cash():
        s = _session(cashenv)
        try:
            return Decimal(str(s.query(func.coalesce(func.sum(
                CashLedgerEntry.amount), 0)).filter(
                CashLedgerEntry.tenant_id == cashenv.company_id,
                CashLedgerEntry.cash_account_id == till.id,
                CashLedgerEntry.direction == "IN",
                CashLedgerEntry.category == "SALE").scalar() or 0))
        finally:
            s.close()

    before = till_cash()
    _sell(cashenv, pid, method="cash", qty=5, till_id=till.id)   # 5 × 100
    after = till_cash()
    assert after - before == Decimal("500"), (before, after)
