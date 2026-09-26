# -*- coding: utf-8 -*-
"""Obuna holati — SO'ROV VAQTIDA hisoblanadi (Phase 6A).

NEGA SOF FUNKSIYA
=================
Holat scheduler'ga TAYANMAYDI. Agar «kim cheklangan» degan qarorni fon vazifasi
yozib qo'yganida, o'sha vazifa 1 soat ishlamasa muddati o'tgan ijarachi yozishda
davom etardi. Shu bois qaror HAR so'rovda vaqtdan qayta hisoblanadi; bazadagi
`status` esa faqat ANIQ operator qarorini (CANCELLED, qo'lda RESTRICT) saqlaydi.

⚠️  Bu modul bazani BILMAYDI va vaqtni O'ZI olmaydi: `now` argument sifatida
    kiradi. Shu sabab chegara holatlarini (davr oxiri, grace boshi/oxiri,
    29-fevral, oy oxiri, vaqt zonasi) oddiy birlik testi bilan qamrash mumkin.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.enums import SubscriptionStatus

#: Obuna yozuvi YO'Q bo'lgan ijarachi holati.
#  ⚠️  Bu «to'lamagan» EMAS, «ro'yxatga OLINMAGAN» degani: mavjud do'konlar
#      (Fayzan ham) shu holatda qoladi va HECH QACHON avtomatik cheklanmaydi.
NOT_ENROLLED = "NOT_ENROLLED"


@dataclass(frozen=True)
class EffectiveState:
    """Hisoblangan holat + majburlash qarori."""
    status: str                 # NOT_ENROLLED | ACTIVE | GRACE | RESTRICTED | CANCELLED
    enrolled: bool
    writes_allowed: bool        # yangi biznes yozuvi mumkinmi
    warn: bool                  # mijozga ogohlantirish ko'rsatilsinmi (GRACE)
    days_left: int | None       # davr oxirigacha (ACTIVE), aks holda None


def effective_state(sub, now: datetime) -> EffectiveState:
    """`sub` — `Subscription` qatori yoki `None`. `now` — timezone-aware UTC.

    Tartib ATAYLAB shunday:
      1. yozuv yo'q            -> NOT_ENROLLED (majburlash yo'q)
      2. CANCELLED             -> RESTRICTED   (aniq operator qarori, vaqtdan ustun)
      3. now < period_end      -> ACTIVE
      4. now < grace_until     -> GRACE        (yozuv MUMKIN, ogohlantirish bilan)
      5. aks holda             -> RESTRICTED
    """
    if sub is None:
        return EffectiveState(NOT_ENROLLED, False, True, False, None)

    if now.tzinfo is None:
        raise ValueError("now timezone-aware bo'lishi SHART (UTC)")

    if sub.status == SubscriptionStatus.CANCELLED.value:
        return EffectiveState(SubscriptionStatus.RESTRICTED.value, True, False, False, None)

    #  ⚠️  Operator QO'LDA cheklagan bo'lsa, muddat hali tugamagan bo'lsa ham cheklov KUCHDA.
    if sub.status == SubscriptionStatus.RESTRICTED.value and sub.restricted_at is not None:
        return EffectiveState(SubscriptionStatus.RESTRICTED.value, True, False, False, None)

    if now < sub.current_period_end:
        left = (sub.current_period_end - now).days
        return EffectiveState(SubscriptionStatus.ACTIVE.value, True, True, False, max(left, 0))
    if now < sub.grace_until:
        return EffectiveState(SubscriptionStatus.GRACE.value, True, True, True, 0)
    return EffectiveState(SubscriptionStatus.RESTRICTED.value, True, False, False, None)
