# -*- coding: utf-8 -*-
"""Obuna kirish huquqi — SO'ROV VAQTIDA hisoblanadi (Phase 6A/2).

NEGA SOF FUNKSIYA
=================
Qaror scheduler'ga TAYANMAYDI: fon vazifasi bir soat ishlamasa, muddati o'tgan ijarachi
yozishda davom etardi. Shu bois qaror HAR so'rovda vaqtdan qayta hisoblanadi.

SAQLANGAN `status` va HISOBLANGAN holat — IKKI BOSHQA NARSA
===========================================================
Saqlanadigan qiymat FAQAT uchta bo'ladi:

    ACTIVE      — aniq qaror yo'q; qolganini VAQT hal qiladi
    RESTRICTED  — operator QO'LDA chekladi (`restricted_at` to'ldiriladi)
    CANCELLED   — operator bekor qildi (terminal, `cancelled_at`)

⚠️  `GRACE` HECH QACHON bazaga yozilmaydi — u faqat hisoblanadi. Shu sabab saqlangan
    qiymat eskira olmaydi: eskiradigan qiymat umuman saqlanmaydi.
⚠️  Bu ustun AMALLAR JURNALI EMAS. Kim, qachon va nega o'zgartirgani — `admin_audit_log`.

«BOSHQARUVDA EMAS» ≠ «ACTIVE»
=============================
⚠️  Obuna yozuvi YO'Q bo'lsa natija `managed=False` bo'ladi va `effective_status` UMUMAN
    berilmaydi (`None`). Uni `ACTIVE` deb qaytarish eng xavfli chalkashlik bo'lardi:
    keyinchalik kimdir «ACTIVE bo'lsa demak to'lagan» deb hisobot yozardi. Yo'q —
    u «ro'yxatga OLINMAGAN» (grandfathered), pul haqida hech narsa deyilmagan.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.enums import SubscriptionStatus

# ── Sabablar (provenance) — nima uchun aynan shu natija chiqdi ───────────────
REASON_GRANDFATHERED = "GRANDFATHERED"        # obuna yozuvi yo'q -> majburlash o'chiq
REASON_PERIOD_ACTIVE = "PERIOD_ACTIVE"        # to'langan davr ichida
REASON_GRACE_PERIOD = "GRACE_PERIOD"          # davr tugagan, grace davom etmoqda
REASON_EXPIRED = "EXPIRED"                    # grace ham tugagan
REASON_MANUAL_RESTRICTION = "MANUAL_RESTRICTION"   # operator qo'lda chekladi
REASON_CANCELLED = "CANCELLED"                # operator bekor qildi (terminal)


def _aware(dt):
    """Naive `datetime` ni UTC deb o'qiydi.

    ⚠️  SQLite `DateTime(timezone=True)` ni NAIVE qaytaradi (mahalliy `run.bat` yo'li),
        Postgres esa aware. Normallashtirilmasa `now < current_period_end` taqqoslashi
        `TypeError` berardi — ya'ni mahalliy bazada obuna qaroriyoq qulardi.
        Loyiha konvensiyasi: `services/cash/cutover.py:20`, `services/receipt/dto.py:66`.
    """
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SubscriptionAccess:
    """Yagona kanonik natija. Har bir maydon ATAYLAB: enum yolg'iz yetarli emas —
    chaqiruvchi «nega» degan savolga javob bera olishi kerak (admin UI, xato matni, audit)."""
    managed: bool                     # obuna boshqaruvidami
    effective_status: str | None      # ACTIVE | GRACE | RESTRICTED; managed=False -> None
    reason: str
    writes_allowed: bool              # yangi biznes yozuvi mumkinmi
    warn: bool                        # mijozga ogohlantirish (faqat GRACE)
    days_left: int | None             # davr oxirigacha (faqat ACTIVE)


def evaluate_subscription_access(subscription, now: datetime) -> SubscriptionAccess:
    """`subscription` — `Subscription` qatori yoki `None`. `now` — timezone-aware UTC.

    USTUVORLIK (test bilan qulflangan, tartib O'ZGARMAYDI):
      1. yozuv yo'q                          -> managed=False, GRANDFATHERED
      2. CANCELLED                           -> RESTRICTED, CANCELLED          (terminal)
      3. RESTRICTED YOKI `restricted_at`     -> RESTRICTED, MANUAL_RESTRICTION (vaqtdan USTUN)
      4. now <  current_period_end           -> ACTIVE,     PERIOD_ACTIVE
      5. now <  grace_until                  -> GRACE,      GRACE_PERIOD
      6. aks holda                           -> RESTRICTED, EXPIRED
    """
    if subscription is None:
        return SubscriptionAccess(False, None, REASON_GRANDFATHERED, True, False, None)

    if now.tzinfo is None:
        raise ValueError("now timezone-aware bo'lishi SHART (UTC)")

    R = SubscriptionStatus.RESTRICTED.value
    if subscription.status == SubscriptionStatus.CANCELLED.value:
        return SubscriptionAccess(True, R, REASON_CANCELLED, False, False, None)

    #  Qo'lda cheklov VAQTDAN USTUN: muddat hali tugamagan bo'lsa ham kuchda qoladi.
    #  ⚠️  `or`, `and` EMAS — FAIL-CLOSED. Ikki maydon zid bo'lib qolgan qator
    #      (`status='RESTRICTED'` lekin `restricted_at IS NULL`, yoki teskarisi)
    #      ilgari 4-6 bandlarga tushib ketardi va VAQT hal qilardi: qo'lda
    #      cheklangan do'kon muddati tugamaganda yana YOZA OLARDI. Zid holat —
    #      «cheklov yo'q» degani emas, «ma'lumotga ishonib bo'lmaydi» degani, va
    #      bunday paytda kengroq ruxsat berilmaydi.
    #      Sxemada bu holat `ck_sub_restricted_iff` bilan taqiqlangan; bu yerdagi
    #      shart esa CHECK'siz bazada (SQLite, yoki cheklov NOT VALID qolgan
    #      Postgres) ham xavfsiz qoladi — ikkalasi bir-birining o'rnini bosmaydi.
    if subscription.status == R or subscription.restricted_at is not None:
        return SubscriptionAccess(True, R, REASON_MANUAL_RESTRICTION, False, False, None)

    period_end_at = _aware(subscription.current_period_end)
    if now < period_end_at:
        left = (period_end_at - now).days
        return SubscriptionAccess(True, SubscriptionStatus.ACTIVE.value,
                                  REASON_PERIOD_ACTIVE, True, False, max(left, 0))
    if now < _aware(subscription.grace_until):
        return SubscriptionAccess(True, SubscriptionStatus.GRACE.value,
                                  REASON_GRACE_PERIOD, True, True, 0)
    return SubscriptionAccess(True, R, REASON_EXPIRED, False, False, None)
