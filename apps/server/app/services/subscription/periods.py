# -*- coding: utf-8 -*-
"""Davr hisobi va yangilash (Phase 6A/2) — SOF funksiyalar, baza YO'Q.

IKKI XIL DAVR, IKKI XIL QOIDA
=============================
  · `PILOT`  — AYNAN 30 kun (`timedelta(days=30)`). Kalendar bilan ishi yo'q:
    «30 kunlik sinov» aytilgan bo'lsa, u fevralda ham 30 kun bo'lishi kerak.
  · Oylik tijorat tariflari — YILLIK SANA (billing anniversary): 17-okt -> 17-noy.
    Kalendar oyiga (1-sanadan 1-sanagacha) bog'lanmaydi.

OY OXIRI QISQARTIRILADI
=======================
⚠️  31-yanvar + 1 oy = 28-fevral (kabisa yilda 29-fevral), 31-mart + 1 oy = 30-aprel.
    Aks holda `datetime` `ValueError` berardi. Qisqartirish HAR DOIM pastga —
    «keyingi oyning 1-sanasi» ga surish mijozga bir kun ortiqcha berardi va
    keyingi davrni ham surib yuborardi (sana asta-sekin siljiydi).
⚠️  Qisqartirish YOPISHIB QOLMAYDI: davr boshi HAR DOIM asl `started_at` dan
    hisoblanadi, oldingi (qisqartirilgan) davr oxiridan EMAS. Aks holda
    31-yanvarda boshlangan obuna 28-fev -> 28-mar -> 28-apr bo'lib, har oy
    uch kun yo'qotardi.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

#: Pilot davri — aniq kunlar soni (kalendar emas).
PILOT_DAYS = 30
#: Pilot tarifining kodi (`plans.code`).
PILOT_CODE = "PILOT"


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


class RenewalRefused(Exception):
    """Yangilash rad etildi — chaqiruvchi buni 4xx ga aylantiradi."""


def add_months(dt: datetime, months: int) -> datetime:
    """Yillik sana bo'yicha oy qo'shish, oy oxirini qisqartirib.

    31-yan + 1 = 28/29-fev · 31-mar + 1 = 30-apr · 17-okt + 1 = 17-noy.
    Soat/daqiqa/soniya va vaqt zonasi O'ZGARMAYDI.
    """
    if months < 0:
        raise ValueError("months manfiy bo'lmasin")
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def period_end(start: datetime, *, plan_code: str, months: int = 1) -> datetime:
    """Davr oxiri: PILOT uchun aniq 30 kun, qolganlari uchun yillik sana."""
    if plan_code == PILOT_CODE:
        return start + timedelta(days=PILOT_DAYS)
    return add_months(start, months)


def grace_end(period_end_at: datetime, grace_days: int) -> datetime:
    """Grace oxiri. `grace_days=0` -> grace YO'Q (oxiri davr oxiriga teng)."""
    if grace_days < 0:
        raise ValueError("grace_days manfiy bo'lmasin")
    return period_end_at + timedelta(days=grace_days)


def renewal_base(subscription, now: datetime) -> datetime:
    """Yangi davr QAYSI lahzadan boshlanadi.

    | holat                         | baza                        | sabab                        |
    |-------------------------------|-----------------------------|------------------------------|
    | davr hali tugamagan (ACTIVE)  | mavjud `current_period_end` | erta to'lagan kun yo'qotmasin |
    | GRACE                         | `now`                       |                              |
    | muddati o'tgan (RESTRICTED)   | `now`                       |                              |

    ⚠️  `CANCELLED` — TERMINAL. Yangilash uni JIMGINA tiriltirmaydi: bekor qilingan
        obunani qayta ishga tushirish ALOHIDA, aniq amal (reactivation) bo'lishi shart,
        aks holda «to'lov keldi» degan sabab bilan operator qarori bekor bo'lardi.
    ⚠️  QO'LDA CHEKLOV (`MANUAL_RESTRICTION`) bu yerda TEKSHIRILMAYDI va ATAYLAB
        OLIB TASHLANMAYDI: to'lov intizomiy qarorni yashirincha yechmasin. Davr
        uzayadi, lekin do'kon `restore` qilinmaguncha cheklangan qoladi.
    """
    from app.models.enums import SubscriptionStatus

    if subscription.status == SubscriptionStatus.CANCELLED.value:
        raise RenewalRefused(
            "Obuna bekor qilingan — avval qayta faollashtirish kerak")
    if now.tzinfo is None:
        raise ValueError("now timezone-aware bo'lishi SHART (UTC)")
    end = _aware(subscription.current_period_end)
    return end if now < end else now
