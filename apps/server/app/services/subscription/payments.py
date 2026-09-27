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
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from app.models.subscription import SubscriptionPayment
from app.services.subscription import lifecycle as lc
from app.services.subscription.periods import (RenewalRefused, grace_end, period_end,
                                               renewal_base)


def find_by_client_uuid(db, company_id, client_uuid) -> SubscriptionPayment | None:
    """Idempotentlik qidiruvi — IJARACHI DOIRASIDA (global emas)."""
    if client_uuid is None:
        return None
    return (db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.company_id == company_id,
                    SubscriptionPayment.client_uuid == client_uuid)
            .populate_existing()
            .first())


def record_payment(db, *, company_id, client_uuid: uuid.UUID | None,
                   amount: Decimal, method: str, actor: lc.Actor, reason: str,
                   months: int = 1, currency: str = "UZS",
                   reference: str | None = None, note: str | None = None,
                   request_id: str | None = None,
                   now: datetime | None = None) -> tuple[SubscriptionPayment, bool]:
    """To'lovni yozadi va davrni uzaytiradi. Qaytaradi: `(to'lov, yangi_yozildimi)`.

    Takror chaqiruv (ayni `client_uuid`): mavjud to'lovni qaytaradi va HECH NARSA
    o'zgartirmaydi — na ikkinchi to'lov, na ikkinchi uzaytirish, na ikkinchi audit.
    """
    lc._require_reason(reason)
    at = lc._now(now)

    #  1) QULF BIRINCHI — takrorlar shu yerda ketma-ketlashadi.
    sub = lc._lock(db, company_id)
    if sub is None:
        raise lc._refuse(db, lc.LifecycleRefused(
            "SUBSCRIPTION_NOT_FOUND", "kompaniyada obuna yozuvi yo'q"))

    #  2) IDEMPOTENTLIK — qulf OSTIDA.
    existing = find_by_client_uuid(db, company_id, client_uuid)
    if existing is not None:
        #  ⚠️  Qulfni USHLAB chiqmaydi: takror yo'li ham tranzaksiyani YOPADI,
        #      aks holda muvaffaqiyat va takror yo'llari turlicha yakunlanardi.
        db.rollback()
        return existing, False

    #  3) Davr bazasi. `CANCELLED` bu yerda RAD etiladi.
    try:
        base = renewal_base(sub, at)
    except RenewalRefused as e:
        raise lc._refuse(db, lc.LifecycleRefused(
            "SUBSCRIPTION_CANCELLED", str(e), current_status=sub.status)) from e

    code, grace_days = lc.plan_terms(db, sub.plan_id)
    new_end = period_end(base, plan_code=code, months=months)
    before = lc.snapshot(sub)

    pay = SubscriptionPayment(
        company_id=company_id, subscription_id=sub.id, amount=amount,
        currency=currency, method=method, paid_at=at,
        #  Yangilashni HARAKATGA KELTIRGAN to'lov o'z davrini yozadi — reyestr
        #  audit jurnalisiz ham o'qilsin. (Storno qatorlarida ikkalasi bo'sh qoladi.)
        period_from=base, period_to=new_end,
        reference=reference, note=note, client_uuid=client_uuid,
        created_by_admin=actor.admin_id)
    db.add(pay)

    #  4) Davr uzayadi. `status`/`restricted_at` ATAYLAB tegilmaydi.
    sub.current_period_start = base
    sub.current_period_end = new_end
    sub.grace_until = grace_end(new_end, grace_days)
    sub.row_version = (sub.row_version or 0) + 1
    db.flush()

    lc._audit(db, action=lc.ACTION_PAYMENT, company_id=company_id, target_id=sub.id,
              actor=actor, reason=reason, before=before, after=lc.snapshot(sub),
              request_id=request_id)
    db.commit()
    return pay, True
