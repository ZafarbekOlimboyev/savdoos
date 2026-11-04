# -*- coding: utf-8 -*-
"""R6.8 §5 — NAQD VA QARZ SOLISHTIRUVI: TAKROR TO'LOV IKKI YOZUV BERMAYDI.

R6.8 P1 (to'lov varaqasi) da kafolat MATNI to'g'rilandi va kalit `DraftGuard`
orqali saqlanadigan bo'ldi. Bu fayl SERVER tomonini qadab qo'yadi: kafolat
haqiqatan bajarilishini, va — eng muhimi — takror to'lov **KASSA** izini ham
ikki marta yozmasligini.

NEGA KASSA MUHIM (R6.7 raqib topilmasi). Har muvaffaqiyatli NAQD qarz
to'lovi uchta yozuv qiladi:

  1. `customer_payments` qatori       (qarz kamayadi)
  2. `cash_movements` (type=payin)    ochiq smenaga  ← smenaning «kutilgan naqd»i
  3. kassa ledgeri `DEBT_IN`          (Postgres'da)

Ikkinchi yozuv paydo bo'lsa zarar IKKI TOMONLAMA: mijoz qoldig'i noto'g'ri
VA smenaning kutilgan naqdi jismonan kelmagan pulga oshadi — smena
yopilishida bu **kassirga yozilgan kamomad** bo'lib chiqadi.

Bu fayl isbotlaydi:
  1. AYNI kalit bilan takror naqd to'lov -> `duplicate: true`, `customer_payments`
     BITTA, `cash_movements` BITTA, qarz BIR MARTA kamaygan;
  2. BOSHQA kalit bilan AYNI summa -> IKKI to'lov (qonuniy: mijoz ikki marta
     to'lashi mumkin) — ya'ni server body bo'yicha dedup QILMAYDI;
  3. qarzdan ortiq to'lov `amt = min(amt, bal)` bilan qisqaradi va javob
     HAQIQATAN yozilgan summani aytadi;
  4. qarz yopilgandan keyin yangi to'lov 400 (bu aynan R6.7 da aniqlangan
     «to'liq to'lovda zarar TASODIFAN to'siladi» holati — endi u ATAYLAB
     qadab qo'yilgan, chunki P1 zarari QISMAN to'lovda ko'rinadi);
  5. ta'minotchi to'lovi AYNI naqshni beradi (`ux_suppay_client_uuid`).

⚠️  SQLite'da kassa ledgeri (`cash.*` sxemasi) YO'Q — `_CM` legacy soyasi esa
    BOR. Shu bois bu yerda `cash_movements` o'lchanadi; ledger parity'si
    `tests/cash/` da alohida sinaladi.
"""
import uuid as _uuid
from decimal import Decimal

import pytest

API = "/api/v1"


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _mk_customer(balance: str = "100000"):
    """Qarzi bor mijoz."""
    from app.models.org import Company
    from app.models.customers import Customer
    s = _db()
    try:
        cid = s.query(Company).filter(Company.code == "demo").one().id
        c = Customer(id=_uuid.uuid4(), company_id=cid, code="R68-" + _uuid.uuid4().hex[:6],
                     full_name="R68 Qarzdor", phone=None,
                     credit_balance=Decimal(balance))
        s.add(c)
        s.commit()
        return str(c.id)
    finally:
        s.close()


def _mk_supplier(balance: str = "100000"):
    from app.models.org import Company
    from app.models.purchasing import Supplier
    s = _db()
    try:
        cid = s.query(Company).filter(Company.code == "demo").one().id
        sup = Supplier(id=_uuid.uuid4(), company_id=cid, name="R68 Ta'minotchi",
                       balance=Decimal(balance))
        s.add(sup)
        s.commit()
        return str(sup.id)
    finally:
        s.close()


def _payments(customer_id: str) -> int:
    from app.models.customers import CustomerPayment
    s = _db()
    try:
        return (s.query(CustomerPayment)
                .filter(CustomerPayment.customer_id == _uuid.UUID(customer_id)).count())
    finally:
        s.close()


def _balance(customer_id: str) -> Decimal:
    from app.models.customers import Customer
    s = _db()
    try:
        return Decimal(str(s.get(Customer, _uuid.UUID(customer_id)).credit_balance))
    finally:
        s.close()


def _cash_moves(reason_like: str) -> int:
    """Shu sabab matnini o'z ichiga olgan kassa harakatlari soni."""
    from app.models.shifts import CashMovement
    s = _db()
    try:
        return (s.query(CashMovement)
                .filter(CashMovement.reason.like(f"%{reason_like}%")).count())
    finally:
        s.close()


def _pay(client, H, customer_id, *, amount, method="cash", cu=None):
    body = {"amount": amount, "method": method}
    if cu is not None:
        body["client_uuid"] = cu
    return client.post(f"{API}/customers/{customer_id}/payments", headers=H, json=body)


@pytest.fixture
def qarzdor(client):
    return _mk_customer("100000")


# ══ 1. AYNI KALIT — BITTA TO'LOV, BITTA KASSA YOZUVI ═════════════════════════

def test_AYNI_kalit_takror_tolov_BITTA_yozuv_va_BITTA_kassa_harakati(client, admin_headers,
                                                                     qarzdor):
    cu = str(_uuid.uuid4())
    oldin_kassa = _cash_moves("R68 Qarzdor")

    r1 = _pay(client, admin_headers, qarzdor, amount=40000, cu=cu)
    assert r1.status_code == 200, r1.text
    assert r1.json().get("duplicate") is not True
    qoldiq = _balance(qarzdor)
    assert qoldiq == Decimal("60000"), r1.text

    r2 = _pay(client, admin_headers, qarzdor, amount=40000, cu=cu)

    assert r2.status_code == 200, r2.text
    assert r2.json().get("duplicate") is True, r2.text
    assert _payments(qarzdor) == 1, "IKKINCHI to'lov qatori yozildi"
    assert _balance(qarzdor) == qoldiq, "qarz IKKI MARTA kamaydi"
    # Kassa izi AYNAN bir martadan ortiq oshmagan (smena yo'q bo'lsa — umuman
    # yozilmaydi; `if _sh` sharti `customers.py:443` da).
    keyin_kassa = _cash_moves("R68 Qarzdor")
    assert keyin_kassa - oldin_kassa <= 1, \
        f"kassa harakati {keyin_kassa - oldin_kassa} marta yozildi — smena «kutilgan naqd»i " \
        "jismonan kelmagan pulga oshardi va kassirga kamomad bo'lib chiqardi"


# ══ 2. BOSHQA KALIT — IKKI QONUNIY TO'LOV ════════════════════════════════════

def test_BOSHQA_kalit_AYNI_summa_IKKI_tolov_yoziladi(client, admin_headers, qarzdor):
    """⚠️  Server tana bo'yicha dedup QILMAYDI va qilmasligi KERAK: mijoz
    ayni summani ikki marta to'lashi butunlay qonuniy."""
    assert _pay(client, admin_headers, qarzdor, amount=30000,
                cu=str(_uuid.uuid4())).status_code == 200
    r2 = _pay(client, admin_headers, qarzdor, amount=30000, cu=str(_uuid.uuid4()))

    assert r2.status_code == 200, r2.text
    assert r2.json().get("duplicate") is not True
    assert _payments(qarzdor) == 2
    assert _balance(qarzdor) == Decimal("40000")


# ══ 3-4. QARZ CHEGARASI ══════════════════════════════════════════════════════

def test_qarzdan_ORTIQ_tolov_qisqaradi_va_javob_HAQIQATAN_yozilganini_aytadi(
        client, admin_headers, qarzdor):
    r = _pay(client, admin_headers, qarzdor, amount=500000, cu=str(_uuid.uuid4()))

    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["paid"])) == Decimal("100000"), r.text
    assert _balance(qarzdor) == Decimal("0")


def test_qarz_YOPILGANDAN_keyin_yangi_tolov_RAD_etiladi(client, admin_headers, qarzdor):
    """⚠️  AYNAN shu shox R6.7 da «to'liq to'lovda zarar TASODIFAN to'siladi»
    deb qayd etilgan edi. Endi u ATAYLAB qadab qo'yilgan: P1 zarari QISMAN
    to'lovda ko'rinadi, ya'ni bu darvoza yolg'on xotirjamlik bermasligi
    kerak."""
    assert _pay(client, admin_headers, qarzdor, amount=100000,
                cu=str(_uuid.uuid4())).status_code == 200
    assert _balance(qarzdor) == Decimal("0")

    r = _pay(client, admin_headers, qarzdor, amount=1000, cu=str(_uuid.uuid4()))

    assert r.status_code == 400, r.text
    assert _payments(qarzdor) == 1
    assert _balance(qarzdor) == Decimal("0")


# ══ 5. TA'MINOTCHI YO'LI — AYNI NAQSH ════════════════════════════════════════

def test_taminotchi_tolovi_AYNI_kalit_bilan_BITTA_yozuv(client, admin_headers):
    from app.models.purchasing import Supplier, SupplierPayment
    sup = _mk_supplier("80000")
    cu = str(_uuid.uuid4())

    r1 = client.post(f"{API}/suppliers/{sup}/payments", headers=admin_headers,
                     json={"amount": 30000, "method": "cash", "client_uuid": cu})
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"{API}/suppliers/{sup}/payments", headers=admin_headers,
                     json={"amount": 30000, "method": "cash", "client_uuid": cu})
    assert r2.status_code == 200, r2.text
    assert r2.json().get("duplicate") is True, r2.text

    s = _db()
    try:
        assert (s.query(SupplierPayment)
                .filter(SupplierPayment.supplier_id == _uuid.UUID(sup)).count()) == 1
        assert Decimal(str(s.get(Supplier, _uuid.UUID(sup)).balance)) == Decimal("50000")
    finally:
        s.close()
