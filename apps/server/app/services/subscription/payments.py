# -*- coding: utf-8 -*-
"""Obuna to'lovi va davr yangilash — idempotent yozuvchi (Phase 6A/2.5).

TARTIB MUHIM: AVVAL QULF, KEYIN IDEMPOTENTLIK
=============================================
⚠️  Obuna qatori `FOR NO KEY UPDATE` bilan BIRINCHI qulflanadi va shundan KEYIN
    `(company_id, client_uuid)` bo'yicha takror qidiriladi. Teskari tartibda ikki
    parallel takror ikkalasi ham «to'lov yo'q» deb ko'rib, davrni IKKI marta
    uzaytirardi. Qulf birinchi bo'lgani uchun ikkinchi chaqiruv birinchisining
    commit'ini kutadi va qulfdan keyin to'lovni KO'RADI.
⚠️  `ux_subpay_client_uuid` `(company_id, client_uuid)` — bu OXIRGI to'siq, birinchi
    emas: qidiruv tez yo'l, indeks esa kafolat.

QAYTA TIRILTIRISH YO'Q
======================
⚠️  `renewal_base` `CANCELLED` da rad etadi — to'lov bekor qilingan obunani
    TIRILTIRMAYDI. Buning yagona yo'li `lifecycle.reactivate()`.
⚠️  QO'LDA CHEKLOV (`RESTRICTED`) to'lov bilan YECHILMAYDI: davr uzayadi, lekin
    `status`/`restricted_at` tegilmaydi. Intizomiy qaror pul bilan bekor bo'lmasin.

KALIT YO'Q BO'LSA — RAD ETILADI (SAFE-01, 2026-09-30)
====================================================
⚠️  `ux_subpay_client_uuid` QISMAN indeks: `WHERE client_uuid IS NOT NULL`. Ya'ni
    kalitsiz (`NULL`) qatorni u QOPLAMAYDI — va PostgreSQL'da to'liq noyob indeks
    ham yordam bermasdi, chunki `NULL != NULL`. Shu bois kafolat BAZADA emas, shu
    YOZUVCHIDA tugallanadi: kalit bo'lmasa qator UMUMAN yozilmaydi.
⚠️  NEGA FAIL-CLOSED. Ilgari `client_uuid=None` bilan ayni to'lovning takrori
    IKKI qator va IKKI davr uzaytirish berardi (o'lchangan: bir oylik to'lov uchun
    61 kun). Jadval ATAYLAB append-only (`FullMixin` yo'q, storno YOZUVCHISI hali
    yo'q), ya'ni buni keyin TUZATIB BO'LMAYDI. Shuning uchun «ikkinchi qaytarib
    bo'lmaydigan to'lov» o'rniga BARQAROR rad etish tanlandi.
⚠️  USTUN NULLABLE QOLADI va bu ataylab: mavjud qatorlar va kelajakdagi storno
    qatorlari uchun sxema o'zgarmaydi. Cheklov YOZUV yo'lida, USTUNDA emas — shu
    bois sxema migratsiyasi ham KERAK EMAS.
⚠️  Kodlar (barqaror, mashina o'qiy oladigan):
      `SUBSCRIPTION_PAYMENT_KEY_REQUIRED` — kalit yo'q yoki bo'sh;
      `SUBSCRIPTION_PAYMENT_KEY_INVALID`  — kalit buzuq yoki noto'g'ri tur;
      `SUBSCRIPTION_PAYMENT_KEY_CONFLICT` — AYNI kalit, BOSHQA pul.
    Oxirgisi «begona to'lovlarni bir-biriga qo'shib yuborish» ning qalqoni: kalit
    qayta ishlatilgan, lekin summa/valyuta/usul boshqa bo'lsa — bu takror EMAS, va
    jimgina birinchi to'lovni qaytarish operatorga YOLG'ON tasdiq berardi.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from app.models.subscription import SubscriptionPayment
from app.services.subscription import lifecycle as lc
from app.services.subscription.periods import (RenewalRefused, grace_end, period_end,
                                               renewal_base)


#: Rad etish kodlari — chaqiruvchi `X-Error-Code` ga aylantiradi.
KEY_REQUIRED = "SUBSCRIPTION_PAYMENT_KEY_REQUIRED"
KEY_INVALID = "SUBSCRIPTION_PAYMENT_KEY_INVALID"
KEY_CONFLICT = "SUBSCRIPTION_PAYMENT_KEY_CONFLICT"


def require_client_uuid(client_uuid) -> uuid.UUID:
    """Idempotentlik kalitini tekshiradi va NORMALLASHTIRADI. Bazaga TEGMAYDI.

    ⚠️  BAZAGA TEGMAYDI va shu MUHIM: chaqiruv qulfdan ham, yozuvdan ham OLDIN
        bo'ladi, ya'ni rad etish tranzaksiyaga hech narsa qilmaydi — `_refuse()`
        ham, `db.rollback()` ham kerak emas (`_require_reason` bilan ayni naqsh).
    ⚠️  Satr QABUL QILINADI, lekin faqat TO'G'RI shakldagisi. Aks holda ustun
        turi (`UUID`) drayver darajasida `'str' object has no attribute 'hex'`
        bilan yiqilardi — operatorga hech narsa aytmaydigan, barqaror ham bo'lmagan
        xato. Endi shakl shu yerda, ANIQ kod bilan tekshiriladi.
    """
    if client_uuid is None:
        raise lc.LifecycleRefused(
            KEY_REQUIRED, "to'lov idempotentlik kaliti (`client_uuid`) SHART: "
                          "kalitsiz takror chaqiruv ikkinchi to'lovni yozardi")
    if isinstance(client_uuid, uuid.UUID):
        return client_uuid
    if isinstance(client_uuid, str):
        matn = client_uuid.strip()
        if not matn:
            raise lc.LifecycleRefused(
                KEY_REQUIRED, "to'lov idempotentlik kaliti bo'sh — kalit SHART")
        try:
            return uuid.UUID(matn)
        except ValueError as e:
            raise lc.LifecycleRefused(
                KEY_INVALID,
                f"to'lov idempotentlik kaliti UUID emas: {matn!r}") from e
    raise lc.LifecycleRefused(
        KEY_INVALID, "to'lov idempotentlik kaliti UUID bo'lishi SHART, berilgani "
                     f"{type(client_uuid).__name__}")


def _pul(v) -> Decimal | None:
    """Summani taqqoslash uchun `Decimal`ga keltiradi (SQLite float qaytarishi mumkin)."""
    return None if v is None else Decimal(str(v))


def _ayni_pulmi(existing: SubscriptionPayment, *, amount, currency, method) -> bool:
    """Takror chaqiruv AYNI to'lovnimi — PUL maydonlari bo'yicha.

    ⚠️  `months` taqqoslanMAYDI va bu ma'lum cheklov: yozilgan qatorda faqat
        natija (`period_from`/`period_to`) bor, so'ralgan `months` emas, va uni
        qayta hisoblash tarif shartlarini takror o'qishni talab qilardi. Ya'ni ayni
        kalit bilan BOSHQA `months` yuborilsa, birinchi berilgan davr qaytariladi.
        Qolgan blokerlar bilan birga hisobotda ochiq qoldirildi.
    """
    return (_pul(existing.amount) == _pul(amount)
            and existing.currency == currency
            and existing.method == method)


def find_by_client_uuid(db, company_id, client_uuid) -> SubscriptionPayment | None:
    """Idempotentlik qidiruvi — IJARACHI DOIRASIDA (global emas).

    ⚠️  `None` uchun `None` qaytaradi — bu ZONDLASH uchun, YOZUV yo'li uchun emas:
        `record_payment` kalitni `require_client_uuid()` bilan ALLAQACHON talab
        qilgan, ya'ni yozuv yo'lida bu shox YETIB BO'LMAYDIGAN (SAFE-01).
    """
    if client_uuid is None:
        return None
    return (db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.company_id == company_id,
                    SubscriptionPayment.client_uuid == client_uuid)
            .populate_existing()
            .first())


def record_payment(db, *, company_id, client_uuid: uuid.UUID | str | None,
                   amount: Decimal, method: str, actor: lc.Actor, reason: str,
                   months: int = 1, currency: str = "UZS",
                   reference: str | None = None, note: str | None = None,
                   request_id: str | None = None, now: datetime | None = None,
                   commit: bool = True) -> tuple[SubscriptionPayment, bool]:
    """To'lovni yozadi va davrni uzaytiradi. Qaytaradi: `(to'lov, yangi_yozildimi)`.

    Takror chaqiruv (ayni `client_uuid`): mavjud to'lovni qaytaradi va HECH NARSA
    o'zgartirmaydi — na ikkinchi to'lov, na ikkinchi uzaytirish, na ikkinchi audit.
    """
    lc._require_reason(reason)
    #  ⚠️  KALIT — BIRINCHI DARVOZA (SAFE-01). Bazaga tegmasdan, qulfdan oldin:
    #      kalitsiz chaqiruv shu yerda tugaydi va HECH QANDAY yozuv bo'lmaydi.
    key = require_client_uuid(client_uuid)
    lc._assert_owner(db, commit)
    #  0) IDEMPOTENTLIK KAFOLATI BORMI — YOZUVDAN OLDIN (fail-closed).
    #
    #  ⚠️  NEGA TAYYORLIK YETARLI EMAS. `ux_subpay_client_uuid` — YAGONA baza-darajasidagi
    #      to'siq: model `__table_args__` da u QISMAN noyob INDEKS (`WHERE client_uuid IS
    #      NOT NULL`), va PostgreSQL'da qismiy indeksni UNIQUE CONSTRAINT qilib bo'lmaydi,
    #      ya'ni MUQOBIL cheklov mavjud ham emas. Indeks noyob bo'lmasa quyidagi
    #      SELECT-keyin-INSERT (2-qadam) klassik TOCTOU bo'lib qoladi: ikki parallel
    #      qayta-yuborish IKKI to'lov va IKKI davr uzaytirish yozadi — bittasi to'langan,
    #      ikkitasi berilgan. Jadval esa ATAYLAB append-only (storno yozuvchisi YO'Q),
    #      ya'ni buni keyin TUZATIB BO'LMAYDI.
    #
    #  ⚠️  `/health/ready` QIZIL bo'lishi bu yozuvni TO'SMAYDI — u monitoring signali.
    #      Shu bois darvoza AYNAN shu yerda (ega qarori, 2026-09-29).
    from app.core.index_guard import require_index
    require_index(db, "ux_subpay_client_uuid", "subscription_payments",
                  operation="subscription_payment")
    at = lc._now(now)

    #  1) QULF BIRINCHI — takrorlar shu yerda ketma-ketlashadi.
    sub = lc._lock(db, company_id, commit=commit)
    if sub is None:
        raise lc._refuse(db, lc.LifecycleRefused(
            "SUBSCRIPTION_NOT_FOUND", "kompaniyada obuna yozuvi yo'q"), commit)

    #  2) IDEMPOTENTLIK — qulf OSTIDA.
    existing = find_by_client_uuid(db, company_id, key)
    if existing is not None:
        #  ⚠️  AYNI KALIT, BOSHQA PUL — bu takror EMAS. Birinchi to'lovni jimgina
        #      qaytarish operatorga «to'landi» deb YOLG'ON tasdiq berardi (u boshqa
        #      summa yubordi). Ikkinchi qator ham yozib bo'lmaydi: reyestr
        #      append-only va storno yozuvchisi yo'q. Shu bois BARQAROR rad etish.
        if not _ayni_pulmi(existing, amount=amount, currency=currency, method=method):
            raise lc._refuse(db, lc.LifecycleRefused(
                KEY_CONFLICT,
                f"idempotentlik kaliti {key} allaqachon BOSHQA to'lov uchun "
                f"ishlatilgan (yozilgan: {existing.amount} {existing.currency} "
                f"{existing.method}; so'ralgan: {amount} {currency} {method})",
                current_status=sub.status), commit)
        #  ⚠️  Egalik XIZMATDA bo'lsa qulf bo'shatiladi; chaqiruvchining
        #      tranzaksiyasida bo'lsak TEGMAYMIZ — bekor qilish uning qarori.
        if commit:
            db.rollback()
        return existing, False

    #  3) Davr bazasi. `CANCELLED` bu yerda RAD etiladi.
    try:
        base = renewal_base(sub, at)
    except RenewalRefused as e:
        raise lc._refuse(db, lc.LifecycleRefused(
            "SUBSCRIPTION_CANCELLED", str(e), current_status=sub.status), commit) from e

    code, grace_days = lc.plan_terms(db, sub.plan_id)
    new_end = period_end(base, plan_code=code, months=months)
    before = lc.snapshot(sub)

    pay = SubscriptionPayment(
        company_id=company_id, subscription_id=sub.id, amount=amount,
        currency=currency, method=method, paid_at=at,
        #  Yangilashni HARAKATGA KELTIRGAN to'lov o'z davrini yozadi — reyestr
        #  audit jurnalisiz ham o'qilsin. (Storno qatorlarida ikkalasi bo'sh qoladi.)
        period_from=base, period_to=new_end,
        reference=reference, note=note, client_uuid=key,
        created_by_admin=actor.admin_id)
    db.add(pay)

    #  4) Davr uzayadi. `status`/`restricted_at` ATAYLAB tegilmaydi.
    sub.current_period_start = base
    sub.current_period_end = new_end
    sub.grace_until = grace_end(new_end, grace_days)
    sub.row_version = (sub.row_version or 0) + 1
    db.flush([pay, sub])

    ev = lc._audit(db, action=lc.ACTION_PAYMENT, company_id=company_id,
                   target_id=sub.id, actor=actor, reason=reason, before=before,
                   after=lc.snapshot(sub), request_id=request_id)
    lc._finish(db, commit, [pay, sub, ev])
    return pay, True
