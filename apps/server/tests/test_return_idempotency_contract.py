# -*- coding: utf-8 -*-
"""QAYTARISH KALITI — MODDIY MAYDONLAR KONTRAKTI (DB'siz, sof birlik sinovi).

`app.api.v1.sales._return_ayni_amalmi` qaysi maydonni «moddiy» deb sanashini qadaydi.
Haqiqiy marshrut va haqiqiy Postgres yo'li alohida faylda:
`tests/cash/test_return_idempotency_key.py`.

⚠️  NEGA ALOHIDA QATLAM. Haqiqiy-PG fayli `tests/cash/` da yashaydi va u yerdagi
    conftest pgserver bo'lmasa BUTUN katalogni o'tkazib yuboradi. Solishtirish
    qoidasining o'zi esa bazaga bog'liq emas — shu bois u asosiy (SQLite) to'plamda
    ham yuriladi va mahalliy mashinada ham himoya qiladi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.api.v1.sales import _return_ayni_amalmi
from app.models.enums import ReturnReason
from app.models.sales import Return, ReturnItem
from app.schemas.sales import ReturnCreate

SALE = uuid.uuid4()
P1 = uuid.uuid4()
P2 = uuid.uuid4()


def _saqlangan(*, sale_id=SALE, reason=ReturnReason.customer, restock=True,
               method="cash", satrlar=((P1, "2.000", "100.00"),)) -> Return:
    """Bazaga YOZILMAGAN `Return` — solishtirish sof funksiya, sessiya kerak emas."""
    r = Return(original_sale_id=sale_id, reason=reason, restock=restock,
               refund_method=method)
    r.items = [ReturnItem(product_id=pid, qty=Decimal(q), unit_price=Decimal(p))
               for pid, q, p in satrlar]
    return r


def _kelgan(*, sale_id=SALE, reason="customer", restock=True, method="cash",
            satrlar=((P1, 2.0, 0.0),)) -> ReturnCreate:
    return ReturnCreate(
        original_sale_id=sale_id, reason=reason, restock=restock,
        refund_method=method,
        items=[{"product_id": str(pid), "qty": q, "unit_price": p}
               for pid, q, p in satrlar])


def test_AYNI_sorov_AYNI_deb_sanaladi():
    assert _return_ayni_amalmi(_saqlangan(), _kelgan()) is True


# ══ MODDIY maydonlar — farq qilsa TAKROR EMAS ══════════════════════════════

@pytest.mark.parametrize("kw,label", [
    ({"sale_id": uuid.uuid4()}, "BOSHQA asl chek"),
    ({"reason": "defect"}, "BOSHQA sabab"),
    ({"restock": False}, "omborga QAYTMAYDI"),
    ({"method": "card"}, "BOSHQA to'lov usuli"),
    ({"satrlar": ((P1, 5.0, 0.0),)}, "BOSHQA miqdor"),
    ({"satrlar": ((P2, 2.0, 0.0),)}, "BOSHQA mahsulot"),
    ({"satrlar": ((P1, 2.0, 0.0), (P2, 1.0, 0.0))}, "QO'SHIMCHA satr"),
])
def test_MODDIY_maydon_farq_qilsa_TAKROR_EMAS(kw, label):
    assert _return_ayni_amalmi(_saqlangan(), _kelgan(**kw)) is False, label


def test_SATR_KAMAYSA_ham_TAKROR_EMAS():
    saqlangan = _saqlangan(satrlar=((P1, "2.000", "100.00"), (P2, "1.000", "50.00")))
    assert _return_ayni_amalmi(saqlangan, _kelgan()) is False


# ══ MODDIY BO'LMAGAN maydonlar — farq qilsa ham TAKROR ═════════════════════

def test_UNIT_PRICE_solishtirilMAYDI():
    """Mijoz yuborgan narx MASLAHAT; saqlangan narx SERVER hisoblagan qiymat.

    ⚠️  Agar solishtirilsa, QONUNIY takror ham 409 olardi: POS `unit_price: 0`
        yuboradi, server esa asl chekdan haqiqiy narxni qo'yadi.
    """
    saqlangan = _saqlangan(satrlar=((P1, "2.000", "100.00"),))
    assert _return_ayni_amalmi(saqlangan, _kelgan(satrlar=((P1, 2.0, 0.0),))) is True
    assert _return_ayni_amalmi(saqlangan, _kelgan(satrlar=((P1, 2.0, 999.0),))) is True


def test_MIQDOR_decimal_boyicha_solishtiriladi():
    """`Decimal("2.000")` va `2.0` SON jihatdan teng — satr jihatdan EMAS.

    ⚠️  Satrni solishtirish har qonuniy takrorni 409 qilardi: ustun `Numeric(14,3)`,
        ya'ni bazadan DOIM `2.000` ko'rinishida qaytadi.
    """
    for saqlangan_q, kelgan_q in (("2.000", 2.0), ("2.0", 2.0), ("2", 2.0),
                                  ("0.500", 0.5), ("1.250", 1.25)):
        saqlangan = _saqlangan(satrlar=((P1, saqlangan_q, "100.00"),))
        assert _return_ayni_amalmi(saqlangan, _kelgan(satrlar=((P1, kelgan_q, 0.0),))) \
            is True, (saqlangan_q, kelgan_q)


def test_SATR_TARTIBI_ahamiyatsiz():
    saqlangan = _saqlangan(satrlar=((P1, "2.000", "100.00"), (P2, "1.000", "50.00")))
    kelgan = _kelgan(satrlar=((P2, 1.0, 0.0), (P1, 2.0, 0.0)))
    assert _return_ayni_amalmi(saqlangan, kelgan) is True


def test_SABAB_enum_yoki_satr_bolishi_mumkin():
    """`ex.reason` — ORM enum'i, `data.reason` — satr. Solishtirish ikkisini ham o'qiydi."""
    assert _return_ayni_amalmi(_saqlangan(reason=ReturnReason.customer),
                               _kelgan(reason="customer")) is True
    #  Ba'zi yo'llarda ustun xom satr bo'lib qaytishi mumkin — u ham ishlashi kerak.
    saqlangan = _saqlangan()
    saqlangan.reason = "customer"
    assert _return_ayni_amalmi(saqlangan, _kelgan(reason="customer")) is True


def test_ASL_CHEKSIZ_qaytarish_ham_solishtiriladi():
    """`original_sale_id` NULL bo'lishi mumkin (chek-siz qaytarish) — NULL ham moddiy."""
    assert _return_ayni_amalmi(_saqlangan(sale_id=None), _kelgan(sale_id=None)) is True
    assert _return_ayni_amalmi(_saqlangan(sale_id=None), _kelgan(sale_id=SALE)) is False
    assert _return_ayni_amalmi(_saqlangan(sale_id=SALE), _kelgan(sale_id=None)) is False
