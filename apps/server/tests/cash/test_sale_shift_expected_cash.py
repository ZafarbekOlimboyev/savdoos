# -*- coding: utf-8 -*-
"""PHASE 2.5 — HAQIQIY OCHIQ SMENA/TILL ustida kutilgan naqd isboti.

Oldingi fayl (`test_sale_cash_posting.py`) ledger LEGI yozilishini isbotladi.
Bu fayl undan bir qadam narida: leg SMENANING KUTILGAN NAQDIGA haqiqatan
ta'sir qiladimi — ya'ni kassir yopilishда ko'radigan raqam to'g'rimi.

    kutilgan = ochilish sanog'i + shu smenaning ledger harakatlari
               (`app/services/cash/tenant.py::ledger_expected_shift_cash`)
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models.catalog import Product, Unit
from app.models.inventory import Inventory
from app.models.sales import Sale
from app.schemas.sales import SaleCreate
from app.services.cash import tenant as _ct
from app.services.sales import create_sale

from tests.cash._factory import make_account, open_shift

NOW = datetime.now(timezone.utc)
OPENING = Decimal("100000")     # smena ochilish sanog'i


def _session(env) -> Session:
    return sessionmaker(bind=env.engine, autoflush=False,
                        expire_on_commit=False, class_=Session)()


class _Env:
    """`CashEnv` bilan bir xil yuza — lekin O'Z kompaniyasi bilan."""

    def __init__(self, engine, company_id, branch_id, employee_id, now):
        self.engine = engine
        self.company_id = company_id
        self.branch_id = branch_id
        self.employee_id = employee_id
        self.now = now


@pytest.fixture()
def shiftenv(cashenv):
    """O'Z ledger-native tenanti + TILL + OCHIQ smena + mahsulot.

    ⚠️  `cashenv` ning umumiy kompaniyasi ISHLATILMAYDI va O'ZGARTIRILMAYDI.
        `ledger_expected_shift_cash()` tenant `ledger_native` bo'lishini talab
        qiladi (`tenant.py:181`), lekin umumiy fixture'ni shunday belgilash
        AYNI sessiyadagi boshqa cash sinovlarining xulqini o'zgartirib yuborardi.
        Shu bois bu yerda alohida tenant quriladi.
    """
    from app.models.auth import Employee, Role
    from app.models.org import Branch, Company
    from app.services.cash import tenant as _ctn
    s0 = _session(cashenv)
    co = Company(id=uuid.uuid4(), name="Smena Co", code="sh" + uuid.uuid4().hex[:8],
                 currency="UZS")
    s0.add(co); s0.flush()
    br = Branch(id=uuid.uuid4(), company_id=co.id, code="BR1", name="Filial",
                timezone="Asia/Tashkent", is_active=True)
    s0.add(br); s0.flush()
    role = s0.query(Role).first()
    if role is None:
        role = Role(id=uuid.uuid4(), code="r" + uuid.uuid4().hex[:6], name="Kassir")
        s0.add(role); s0.flush()
    emp = Employee(id=uuid.uuid4(), company_id=co.id, full_name="Kassir",
                   phone="+9989" + str(uuid.uuid4().int)[:8], role_id=role.id)
    s0.add(emp); s0.flush()
    _ctn.mark_ledger_native(s0, co.id)      # kutilgan naqd SHU bayroqqa tayanadi
    s0.commit()
    env = _Env(cashenv.engine, co.id, br.id, emp.id, cashenv.now)
    s0.close()

    cashenv = env          # quyidagi barcha qadamlar SHU tenantda
    s = _session(cashenv)
    till = make_account(s, cashenv, "TILL")
    sh = open_shift(s, cashenv, till)
    # `cashenv` minimal urug' — birlik jadvali BO'SH bo'lishi mumkin.
    unit = s.query(Unit).first()
    if unit is None:
        unit = Unit(id=uuid.uuid4(), code="dona", name="dona")
        s.add(unit); s.flush()
    p = Product(id=uuid.uuid4(), company_id=cashenv.company_id,
                name="Smena sinov " + uuid.uuid4().hex[:6],
                article_code="S-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
    s.add(p); s.flush()
    s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=cashenv.branch_id,
                    qty=Decimal("10000"), min_qty=0, updated_at=NOW))
    s.commit()
    out = (cashenv, till, sh, p.id)
    s.close()
    return out


def _expected(cashenv, till, sh):
    s = _session(cashenv)
    try:
        v = _ct.ledger_expected_shift_cash(s, cashenv.company_id, sh.id,
                                           till_id=till.id, opening_cash=OPENING)
        return None if v is None else Decimal(str(v))
    finally:
        s.close()


def _emp(s, cashenv):
    from app.models.auth import Employee
    return s.get(Employee, cashenv.employee_id)


def _sell(cashenv, till, pid, *, method="cash", payments=None, qty=1,
          cu=None, honor=False):
    s = _session(cashenv)
    try:
        body = {"items": [{"product_id": str(pid), "qty": qty, "unit_price": 100}],
                "client_uuid": cu or uuid.uuid4(), "till_id": till.id}
        if payments is not None:
            body["payments"] = payments
        else:
            body["payment_method"] = method
            body["given_amount"] = qty * 100 + 1000
        return create_sale(s, _emp(s, cashenv), SaleCreate(**body),
                           honor_price_snapshot=honor)
    finally:
        s.close()


def test_kutilgan_naqd_umuman_HISOBLANADI(shiftenv):
    """Nazorat: funksiya `None` qaytarsa qolgan sinovlar MA'NOSIZ bo'lardi."""
    cashenv, till, sh, pid = shiftenv
    v = _expected(cashenv, till, sh)
    assert v is not None, "ledger-native kutilgan naqd hisoblanmadi — sinov bo'sh"
    assert v == OPENING, f"savdosiz kutilgan naqd ochilish sanog'iga teng emas: {v}"


def test_NAQD_sotuv_kutilgan_naqdni_AYNAN_oshiradi(shiftenv):
    cashenv, till, sh, pid = shiftenv
    before = _expected(cashenv, till, sh)
    _sell(cashenv, till, pid, method="cash", qty=5)      # 5 × 100 = 500
    after = _expected(cashenv, till, sh)
    assert after - before == Decimal("500"), (before, after)


@pytest.mark.parametrize("method", ["card", "qr"])
def test_KARTA_va_QR_kutilgan_naqdni_OSHIRMAYDI(shiftenv, method):
    """Fizik yashikka pul tushmaydi — kutilgan naqd ham qimirlamasligi shart."""
    cashenv, till, sh, pid = shiftenv
    before = _expected(cashenv, till, sh)
    _sell(cashenv, till, pid, method=method, qty=5)
    after = _expected(cashenv, till, sh)
    assert after == before, f"{method}: kutilgan naqd o'zgardi {before} -> {after}"


def test_ARALASH_tolovda_FAQAT_naqd_ulushi_qoshiladi(shiftenv):
    """40 naqd + 60 karta -> kutilgan naqd FAQAT 40 ga oshadi."""
    cashenv, till, sh, pid = shiftenv
    before = _expected(cashenv, till, sh)
    _sell(cashenv, till, pid, qty=1,
          payments=[{"method": "cash", "amount": 40},
                    {"method": "card", "amount": 60}])
    after = _expected(cashenv, till, sh)
    assert after - before == Decimal("40"), (before, after)


def test_TAKROR_kutilgan_naqdni_IKKI_marta_oshirmaydi(shiftenv):
    cashenv, till, sh, pid = shiftenv
    before = _expected(cashenv, till, sh)
    cu = uuid.uuid4()
    a = _sell(cashenv, till, pid, method="cash", qty=3, cu=cu)
    mid = _expected(cashenv, till, sh)
    b = _sell(cashenv, till, pid, method="cash", qty=3, cu=cu)
    after = _expected(cashenv, till, sh)
    assert a.id == b.id, "takror YANGI sotuv yaratdi"
    assert mid - before == Decimal("300"), (before, mid)
    assert after == mid, f"takror kutilgan naqdni yana oshirdi: {mid} -> {after}"


def test_OFFLINE_replay_ham_kutilgan_naqdga_tushadi(shiftenv):
    cashenv, till, sh, pid = shiftenv
    before = _expected(cashenv, till, sh)
    _sell(cashenv, till, pid, method="cash", qty=2, honor=True)
    after = _expected(cashenv, till, sh)
    assert after - before == Decimal("200"), (before, after)


def test_YIQILGAN_sotuv_kutilgan_naqdni_OSHIRMAYDI(shiftenv, monkeypatch):
    """Commit'dan oldin yiqilsa — ledger legi ham, kutilgan naqd ham o'zgarmaydi."""
    cashenv, till, sh, pid = shiftenv
    before = _expected(cashenv, till, sh)
    s_before = _session(cashenv)
    try:
        n_before = s_before.query(Sale).filter(
            Sale.company_id == cashenv.company_id).count()
    finally:
        s_before.close()

    _orig = Session.commit
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("sun'iy xato: commit paytida")
        return _orig(self, *a, **k)
    monkeypatch.setattr(Session, "commit", flaky)
    s = _session(cashenv)
    try:
        with pytest.raises(Exception):
            create_sale(s, _emp(s, cashenv), SaleCreate(
                items=[{"product_id": str(pid), "qty": 4, "unit_price": 100}],
                payment_method="cash", given_amount=1000, till_id=till.id,
                client_uuid=uuid.uuid4()))
    finally:
        s.rollback(); s.close()
    monkeypatch.undo()

    assert _expected(cashenv, till, sh) == before, "yiqilgan sotuv naqdga ta'sir qildi"
    s_after = _session(cashenv)
    try:
        assert s_after.query(Sale).filter(
            Sale.company_id == cashenv.company_id).count() == n_before
    finally:
        s_after.close()


# ══ PHASE 3.5 — QAYTARISH KUTILGAN NAQDNI KAMAYTIRADI ══════════════════════
#
# ⚠️  NEGA QO'SHILDI. Phase 3 staging hisobotida bu tasdiq `expected_cash=None`
#     qaytargan edi va men uni «kuchsiz» deb belgilagandim. Kuchsiz tasdiq —
#     tasdiq emas: u faqat HTTP 200 ni o'lchardi. Bu yerda butun zanjir
#     uchidan-uchiga o'lchanadi:
#
#         ochilish + naqd sotuv − naqd qaytarish == kutilgan naqd
#
#     va karta/QR qaytarish uni NOLGA o'zgartiradi.


def _legacy_shift(cashenv, till):
    """LEGACY `Shift` — naqd qaytarish AYNAN shuni talab qiladi.

    ⚠️  `shiftenv` fixture'i `cash.CashShift` (ledger smenasi) ochadi; naqd
        qaytarish yo'li esa kassirning ESKI `shifts` qatorini qidiradi
        (`sales.py`: «Naqd qaytarish uchun ochiq smena kerak»). Ikkisi
        ATAYLAB alohida — ledger migratsiyasi eski smenani almashtirmagan.
        Shu bois ikkovi ham AYNI TILL bilan ochiladi.
    """
    from app.api.v1 import shifts as shifts_api
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = _session(cashenv)
    try:
        ex = s.query(Shift).filter(Shift.cashier_id == cashenv.employee_id,
                                   Shift.status == ShiftStatus.open).first()
        if ex is not None:
            return ex.id
        r = shifts_api.open_shift(
            shifts_api.OpenShift(opening_cash=float(OPENING), till_id=till.id),
            _emp(s, cashenv), s)
        return uuid.UUID(str(r["id"]))
    finally:
        s.close()


def _ret(cashenv, till, sale_id, pid, qty, *, method="cash", cu=None):
    """Haqiqiy qaytarish yo'li (`_create_return_once`) — qisqa yo'l YO'Q."""
    from app.api.v1.sales import create_return
    from app.schemas.sales import ReturnCreate
    if method == "cash":
        _legacy_shift(cashenv, till)
    s = _session(cashenv)
    try:
        return create_return(ReturnCreate(
            original_sale_id=sale_id, reason="customer", restock=True,
            refund_method=method, client_uuid=cu or uuid.uuid4(),
            items=[{"product_id": str(pid), "qty": qty, "unit_price": 0}]),
            emp=_emp(s, cashenv), db=s)
    finally:
        s.close()


def test_NAQD_qaytarish_kutilgan_naqdni_AYNAN_kamaytiradi(shiftenv):
    """UCHIDAN-UCHIGA: ochilish 100000 + sotuv 200 − qaytarish 50 == 100150."""
    cashenv, till, sh, pid = shiftenv
    assert _expected(cashenv, till, sh) == OPENING, "boshlang'ich holat noto'g'ri"

    sale = _sell(cashenv, till, pid, method="cash", qty=2)      # 2 × 100 = 200
    assert _expected(cashenv, till, sh) == OPENING + Decimal("200")

    r = _ret(cashenv, till, sale.id, pid, 0.5)                  # 0.5 × 100 = 50
    assert Decimal(str(r["total"])) == Decimal("50"), r
    got = _expected(cashenv, till, sh)
    assert got == OPENING + Decimal("150"), (got, OPENING)


@pytest.mark.parametrize("method", ["card", "qr"])
def test_KARTA_QR_qaytarish_kutilgan_naqdni_OZGARTIRMAYDI(shiftenv, method):
    """Bu usullarda kassadan pul CHIQMAYDI — kutilgan naqd qimirlamasin."""
    cashenv, till, sh, pid = shiftenv
    sale = _sell(cashenv, till, pid, payments=[{"method": method, "amount": 200}],
                 qty=2)
    before = _expected(cashenv, till, sh)
    _ret(cashenv, till, sale.id, pid, 1, method=method)
    assert _expected(cashenv, till, sh) == before, method


def test_TAKROR_qaytarish_kutilgan_naqdni_IKKI_marta_kamaytirmaydi(shiftenv):
    cashenv, till, sh, pid = shiftenv
    sale = _sell(cashenv, till, pid, method="cash", qty=3)
    before = _expected(cashenv, till, sh)
    cu = uuid.uuid4()
    r1 = _ret(cashenv, till, sale.id, pid, 1, cu=cu)
    r2 = _ret(cashenv, till, sale.id, pid, 1, cu=cu)
    assert str(r1["id"]) == str(r2["id"]), "takror YANGI qaytarish yaratdi"
    assert before - _expected(cashenv, till, sh) == Decimal("100"), "ikki marta kamaydi"
