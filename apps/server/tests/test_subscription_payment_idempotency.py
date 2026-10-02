# -*- coding: utf-8 -*-
"""Obuna to'lovi — IDEMPOTENTLIK KALITI KONTRAKTI (SAFE-01, 2026-09-30).

NIMA UCHUN BU FAYL BOR
======================
`record_payment` ni `client_uuid=None` bilan ikki marta chaqirish IKKI to'lov qatori
va IKKI davr uzaytirish yozardi. O'lchangan: bir oylik to'lov uchun davr
`2026-04-10 -> 2026-05-10 -> 2026-06-10`, ya'ni 61 kun, ikki audit qatori, ikkala
qatorda ham `client_uuid IS NULL`. `subscription_payments` ATAYLAB append-only
(`FullMixin` yo'q, storno YOZUVCHISI hali yo'q), ya'ni buni keyin TUZATIB BO'LMAYDI.

Sabab uch qatlamda edi:
  1. `find_by_client_uuid` `None` uchun darhol `None` qaytaradi — takror QIDIRUVI
     umuman bajarilmaydi;
  2. `ux_subpay_client_uuid` QISMAN indeks (`WHERE client_uuid IS NOT NULL`) — NULL
     qatorlarni qoplamaydi, va PostgreSQL'da to'liq noyob indeks ham yordam
     bermasdi, chunki `NULL != NULL`;
  3. shu bois SELECT-keyin-INSERT hech qanday to'siqsiz qoladi.

Kontrakt endi YOZUVCHIDA tugallanadi: kalit bo'lmasa qator UMUMAN yozilmaydi.
USTUN nullable QOLADI (sxema migratsiyasi yo'q) — cheklov yozuv yo'lida.

Konkurentlik (haqiqiy qulflar, ikki parallel yetkazib berish) alohida faylda:
`tests/test_subscription_concurrency_pg.py`.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models.org import Company
from app.models.subscription import Subscription, SubscriptionPayment
from app.services.subscription import lifecycle as lc
from app.services.subscription import payments as pay
from tests.test_subscription_lifecycle import (ACTOR, T0, _actor_row, _aw,  # noqa: F401
                                               _db, _enrolled, _events)

AT = T0 + timedelta(days=1)
SUM = Decimal("100000")


def _pay(db, cid, key, *, amount=SUM, method="CASH", currency="UZS", **kw):
    return pay.record_payment(
        db, company_id=cid, client_uuid=key, amount=amount, method=method,
        currency=currency, actor=ACTOR, reason="oylik to'lov", now=AT, **kw)


def _n_pay(db, cid) -> int:
    return (db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.company_id == cid).count())


def _end(db, cid):
    return _aw(db.query(Subscription)
               .filter(Subscription.company_id == cid).one().current_period_end)


def _n_audit(db, cid) -> int:
    return len([e for e in _events(db, cid) if e.action == lc.ACTION_PAYMENT])


# ══ 1. KALIT YO'Q — YOZUV UMUMAN BO'LMAYDI ═════════════════════════════════
#
# ⚠️  Bu fayl asosiy invarianti. Rad etish YOZUVDAN OLDIN, hatto QULFDAN ham
#     oldin bo'ladi — shu bois `to'lovlar == 0` va `davr o'zgarmagan` ikkalasi
#     ham tekshiriladi: biri kamida bo'lsa «rad etdi, lekin yozib qo'ydi» holati
#     sezilmay qolardi.

@pytest.mark.parametrize("key,kod,label", [
    (None, pay.KEY_REQUIRED, "None (JSON `null` ham shu yerga tushadi)"),
    ("", pay.KEY_REQUIRED, "bo'sh satr"),
    ("   ", pay.KEY_REQUIRED, "faqat bo'shliq"),
    ("not-a-uuid", pay.KEY_INVALID, "buzuq UUID"),
    ("123e4567-e89b-12d3-a456", pay.KEY_INVALID, "kesilgan UUID"),
    (123, pay.KEY_INVALID, "butun son"),
    (b"\x00" * 16, pay.KEY_INVALID, "xom baytlar"),
])
def test_KALIT_yaroqsiz_bolsa_RAD_etiladi_va_HECH_NARSA_yozilmaydi(client, key, kod, label):
    with _db() as db:
        cid, _ = _enrolled(db)
        end0 = _end(db, cid)
        with pytest.raises(lc.LifecycleRefused) as e:
            _pay(db, cid, key)
        assert e.value.code == kod, label
        #  YOZUV YO'Q: na to'lov, na davr, na audit.
        assert _n_pay(db, cid) == 0, f"{label}: to'lov qatori yozildi"
        assert _end(db, cid) == end0, f"{label}: davr uzaydi"
        assert _n_audit(db, cid) == 0, f"{label}: audit qatori yozildi"


def test_KALIT_yoq_RAD_etilgandan_KEYIN_sessiya_ISHLAYDI(client):
    """Rad etish sessiyani «needs rollback» da qoldirmasin — keyin to'lov o'tishi kerak."""
    with _db() as db:
        cid, _ = _enrolled(db)
        with pytest.raises(lc.LifecycleRefused):
            _pay(db, cid, None)
        #  AYNI sessiyada haqiqiy kalit bilan to'lov o'tadi.
        _, created = _pay(db, cid, uuid.uuid4())
        assert created is True
        assert _n_pay(db, cid) == 1


def test_KALIT_yoq_RAD_etilishi_chaqiruvchining_ISHIGA_TEGMAYDI(client):
    """`commit=False` da rad etish begona kutilayotgan yozuvni yo'q qilmasin.

    ⚠️  Kalit tekshiruvi BAZAGA TEGMAYDI — ya'ni `db.rollback()` ham, `_refuse()`
        ham chaqirilmaydi. Shu bois chaqiruvchining ishi o'z joyida qoladi.
    """
    with _db() as db:
        cid, _ = _enrolled(db)
        begona = Company(id=uuid.uuid4(), name=f"Begona {uuid.uuid4().hex[:6]}")
        db.add(begona)
        with pytest.raises(lc.LifecycleRefused):
            _pay(db, cid, None, commit=False)
        assert begona in db.new, "kalit darvozasi chaqiruvchining yozuvini yo'q qildi"


# ══ 2. KALIT BOR — TAKROR AYNAN BIR MARTA ══════════════════════════════════

def test_BIRINCHI_tolov_yoziladi(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        end0 = _end(db, cid)
        p, created = _pay(db, cid, uuid.uuid4())
        assert created is True
        assert _n_pay(db, cid) == 1 and _n_audit(db, cid) == 1
        assert _end(db, cid) > end0


def test_AYNI_kalit_bilan_TAKROR_bitta_qator_bitta_davr(client):
    with _db() as db:
        cid, _ = _enrolled(db)
        k = uuid.uuid4()
        p1, c1 = _pay(db, cid, k)
        end1 = _end(db, cid)
        p2, c2 = _pay(db, cid, k)
        assert (c1, c2) == (True, False)
        assert p1.id == p2.id, "takror ASL to'lovni qaytarishi kerak"
        assert _n_pay(db, cid) == 1
        assert _end(db, cid) == end1, "davr ikkinchi marta uzaydi"
        assert _n_audit(db, cid) == 1


def test_JAVOB_YOQOLGANDAN_keyingi_takror_YANGI_sessiyada_ham_bitta(client):
    """Yo'qolgan HTTP javob: klient qayta yuboradi, lekin BOSHQA sessiya/ulanishda.

    ⚠️  Bu jarayon qayta ishga tushishidan keyin ham ishlashi SHART — shu bois
        kalit BAZADA qidiriladi, xotiradagi to'plamda emas.
    """
    k = uuid.uuid4()
    with _db() as db:
        cid, _ = _enrolled(db)
        _, c1 = _pay(db, cid, k)
        end1 = _end(db, cid)
    with _db() as db2:                        # YANGI sessiya = yangi ulanish
        _, c2 = _pay(db2, cid, k)
        assert (c1, c2) == (True, False)
        assert _n_pay(db2, cid) == 1
        assert _end(db2, cid) == end1


def test_UUID_SATRI_qabul_qilinadi_va_AYNI_kalit_deb_taniladi(client):
    """To'g'ri shakldagi satr normallashtiriladi — drayver xatosi emas, kalit.

    ⚠️  Ilgari satr `StatementError: 'str' object has no attribute 'hex'` berardi:
        barqaror ham, tushunarli ham bo'lmagan xato. Endi satr `uuid.UUID` ga
        keltiriladi, ya'ni satr va obyekt AYNI kalit.
    """
    with _db() as db:
        cid, _ = _enrolled(db)
        k = uuid.uuid4()
        _, c1 = _pay(db, cid, str(k))
        _, c2 = _pay(db, cid, k)              # AYNI kalit, boshqa TUR
        assert (c1, c2) == (True, False)
        assert _n_pay(db, cid) == 1
        row = (db.query(SubscriptionPayment)
               .filter(SubscriptionPayment.company_id == cid).one())
        assert row.client_uuid == k, "kalit UUID sifatida saqlanishi kerak"


# ══ 3. IJARACHI DOIRASI — BEGONA TO'LOVLAR QO'SHILIB KETMASIN ══════════════

def test_AYNI_kalit_BOSHQA_ijarachi_TOQNASHMAYDI(client):
    with _db() as db:
        cid_a, _ = _enrolled(db)
        cid_b, _ = _enrolled(db)
        k = uuid.uuid4()
        _, ca = _pay(db, cid_a, k)
        _, cb = _pay(db, cid_b, k)
        _, ca2 = _pay(db, cid_a, k)           # A da takror — RAD
        assert (ca, cb, ca2) == (True, True, False)
        assert _n_pay(db, cid_a) == 1 and _n_pay(db, cid_b) == 1


def test_BOSHQA_kalit_AYNI_ijarachi_QOSHILIB_ketmaydi(client):
    """Ikki HAQIQIY to'lov bir xil summada bo'lsa ham alohida qoladi."""
    with _db() as db:
        cid, _ = _enrolled(db)
        end0 = _end(db, cid)
        _, c1 = _pay(db, cid, uuid.uuid4())
        _, c2 = _pay(db, cid, uuid.uuid4())
        assert (c1, c2) == (True, True)
        assert _n_pay(db, cid) == 2 and _n_audit(db, cid) == 2
        assert _end(db, cid) > end0


# ══ 4. AYNI KALIT, BOSHQA PUL — TAKROR EMAS, RAD ═══════════════════════════
#
# ⚠️  Jimgina birinchi to'lovni qaytarish operatorga YOLG'ON tasdiq berardi: u
#     boshqa summa yubordi, javob esa «to'landi» deb keladi. Ikkinchi qator ham
#     yozib bo'lmaydi — reyestr append-only. Yagona to'g'ri javob: RAD ETISH.

@pytest.mark.parametrize("ozgarish,kw", [
    ("summa", {"amount": Decimal("250000")}),
    ("usul", {"method": "CARD"}),
    ("valyuta", {"currency": "USD"}),
])
def test_AYNI_kalit_BOSHQA_pul_RAD_etiladi(client, ozgarish, kw):
    with _db() as db:
        cid, _ = _enrolled(db)
        k = uuid.uuid4()
        _pay(db, cid, k)
        end1 = _end(db, cid)
        with pytest.raises(lc.LifecycleRefused) as e:
            _pay(db, cid, k, **kw)
        assert e.value.code == pay.KEY_CONFLICT, ozgarish
        #  Birinchi to'lov joyida, ikkinchisi yo'q, davr uzaymagan.
        assert _n_pay(db, cid) == 1
        assert _end(db, cid) == end1
        assert _n_audit(db, cid) == 1


def test_AYNI_kalit_BOSHQA_SABAB_takror_SANALADI(client):
    """`reason` audit izohi — IDENTITET EMAS. Takror boshqa sabab bilan kelishi normal."""
    with _db() as db:
        cid, _ = _enrolled(db)
        k = uuid.uuid4()
        p1, c1 = pay.record_payment(db, company_id=cid, client_uuid=k, amount=SUM,
                                    method="CASH", actor=ACTOR, reason="birinchi", now=AT)
        p2, c2 = pay.record_payment(db, company_id=cid, client_uuid=k, amount=SUM,
                                    method="CASH", actor=ACTOR, reason="takror", now=AT)
        assert (c1, c2) == (True, False) and p1.id == p2.id
        assert _n_pay(db, cid) == 1


def test_TOQNASHUV_RAD_etilgandan_KEYIN_sessiya_ISHLAYDI(client):
    """Toqnashuv `_refuse` orqali ketadi (qulf ostida) — sessiya baribir tirik qolsin."""
    with _db() as db:
        cid, _ = _enrolled(db)
        k = uuid.uuid4()
        _pay(db, cid, k)
        with pytest.raises(lc.LifecycleRefused):
            _pay(db, cid, k, amount=Decimal("1"))
        #  Sessiya ishlaydi: boshqa kalit bilan to'lov o'tadi.
        _, created = _pay(db, cid, uuid.uuid4())
        assert created is True
        assert _n_pay(db, cid) == 2


def test_TOQNASHUV_commit_FALSE_da_chaqiruvchining_ISHIGA_TEGMAYDI(client):
    """`commit=False` da `_refuse` hech narsa qilmaydi — chegara chaqiruvchining."""
    with _db() as db:
        cid, _ = _enrolled(db)
        k = uuid.uuid4()
        _pay(db, cid, k)
        begona = Company(id=uuid.uuid4(), name=f"Begona {uuid.uuid4().hex[:6]}")
        db.add(begona)
        with pytest.raises(lc.LifecycleRefused) as e:
            _pay(db, cid, k, amount=Decimal("7"), commit=False)
        assert e.value.code == pay.KEY_CONFLICT
        assert begona in db.new, "toqnashuv yo'li chaqiruvchining yozuvini yo'q qildi"


# ══ 5. APPEND-ONLY REYESTR — QATOR SONI QAT'IY ═════════════════════════════

def test_KOP_URINISHDAN_keyin_reyestrda_AYNAN_bitta_qator(client):
    """Yaroqsiz kalitlar + toqnashuvlar + takrorlar: bitta haqiqiy to'lov qoladi."""
    with _db() as db:
        cid, _ = _enrolled(db)
        k = uuid.uuid4()
        _, created = _pay(db, cid, k)
        assert created is True
        end1 = _end(db, cid)
        for yaroqsiz in (None, "", "   ", "buzuq", 5):
            with pytest.raises(lc.LifecycleRefused):
                _pay(db, cid, yaroqsiz)
        with pytest.raises(lc.LifecycleRefused):
            _pay(db, cid, k, amount=Decimal("1"))
        for _ in range(3):
            _, c = _pay(db, cid, k)
            assert c is False
        assert _n_pay(db, cid) == 1, "append-only reyestrda bitta qator kutilgan"
        assert _n_audit(db, cid) == 1
        assert _end(db, cid) == end1, "davr AYNAN bir marta uzayishi kerak"
        row = (db.query(SubscriptionPayment)
               .filter(SubscriptionPayment.company_id == cid).one())
        assert row.reversal_of_id is None, "storno qatori paydo bo'ldi"
