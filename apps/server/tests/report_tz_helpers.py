# -*- coding: utf-8 -*-
"""Hisobot testlari uchun do'kon vaqt zonasini tanlash — YARIM TUN TUZOG'I.

MUAMMO. `test_report_scope.py` va `test_mobile_parity.py` modul IMPORT vaqtida `NOW` ni
muzlatadi va faktlarni mahalliy yarim tundan 60 s keyinga (`AT`) yozadi. Hisobot esa
`day_start` ni TASDIQLASH vaqtida hisoblaydi (`app/api/v1/reports.py`). To'liq regressiya
~85 daqiqa davom etadi, ya'ni ikkala lahza orasida mahalliy yarim tun o'tib ketishi mumkin.
O'tsa — `AT < day_start` bo'ladi va HAMMA «bugungi» yig'indi NOLGA tushadi, kompaniya
bo'yicha to'g'ri qiymatlar esa joyida qoladi. Bu ayni belgi bo'yicha tanib olinadi.

ESKI TANLOV NEGA NOTO'G'RI EDI. Ikkala fayl ham zonani «mahalliy yarim tundan ENG KO'P vaqt
o'tgan» bo'yicha tanlardi. Bu — keyingi yarim tunga ENG YAQIN zona. Docstring «kamida ~3 soat
zaxira» deb va'da qilardi, lekin u *o'tgan* vaqtni o'lchardi, *qolgan*ini emas. Kuzatilgan
ikki yurish: import 2026-09-28T19:06Z -> Asia/Baku (+4), yarim tundan 23.1 soat o'tgan, qolgani
**0.9 soat**; import 20:30Z -> Europe/Moscow (+3), 23.5 soat o'tgan, qolgani **0.5 soat**.
Ikkalasi ham 85 daqiqada yarim tunni kesib o'tdi va o'sha 7 ta testni qizil qildi.

TUZATISH. Zona endi keyingi mahalliy yarim tungacha QOLGAN vaqt bo'yicha tanlanadi.
`MIN_SINCE_MIDNIGHT` sharti saqlanadi, chunki `AT` yarim tundan KEYIN joylanishi kerak —
aks holda `_at()` uni `NOW - 1 s` ga qisadi va u yarim tundan OLDINGA tushib ketardi.

⚠️ Bu FAQAT test infratuzilmasi. Hisobot hisob-kitoblari (`reports.py`) TEGILMAGAN.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: To'liq backend regressiyasi ~85 daqiqa (o'lchangan: 65–83 daq). Zaxira bundan sezilarli
#: katta bo'lishi kerak, aks holda tuzatish faqat bugungi davomiylikka moslashgan bo'lardi.
MIN_HEADROOM = timedelta(hours=3)

#: `_at()` faktni mahalliy yarim tun + 60 s ga qo'yadi. Zona yarim tunga juda yaqin bo'lsa,
#: `min(midnight + 60s, NOW - 1s)` fakti yarim tundan OLDINGA tushib ketardi.
MIN_SINCE_MIDNIGHT = timedelta(minutes=5)


def since_midnight(now: datetime, offset_hours: int) -> timedelta:
    """`now` lahzasida `offset_hours` zonasida mahalliy yarim tundan qancha vaqt o'tgan."""
    local = now.astimezone(timezone(timedelta(hours=offset_hours)))
    return timedelta(hours=local.hour, minutes=local.minute, seconds=local.second,
                     microseconds=local.microsecond)


def headroom(now: datetime, offset_hours: int) -> timedelta:
    """Keyingi mahalliy yarim tungacha QOLGAN vaqt — yurish shu oyna ichida tugashi kerak."""
    return timedelta(days=1) - since_midnight(now, offset_hours)


def pick_store_tz(now: datetime, offsets: dict[str, int]) -> str:
    """Keyingi mahalliy yarim tungacha ENG KO'P vaqt qoladigan zona nomi.

    `now` MAJBURIY parametr: tanlov mashinaning haqiqiy soatiga bog'lanib qolmasligi kerak,
    aks holda uni deterministik sinab bo'lmaydi."""
    best, best_left = None, None
    for name, off in sorted(offsets.items()):
        if since_midnight(now, off) < MIN_SINCE_MIDNIGHT:
            continue                                   # AT yarim tundan oldinga tushib ketardi
        left = headroom(now, off)
        if best_left is None or left > best_left:
            best, best_left = name, left
    if best is None:
        # Amalda yetib bo'lmaydigan shox: offsetlar kamida 1 soat bilan ajralgan, ya'ni
        # hammasi bir vaqtda yarim tunning 5 daqiqasida bo'la olmaydi. Fail-safe.
        best = max(sorted(offsets.items()), key=lambda kv: since_midnight(now, kv[1]))[0]
    return best


def pick_store_tz_LEGACY(now: datetime, offsets: dict[str, int]) -> str:
    """ESKI (nuqsonli) tanlov — faqat REGRESSIYA ISBOTI uchun saqlanadi.

    Testlar bu bilan yangi talabning BUZILISHINI ko'rsatadi, ya'ni yangi test eski xulqda
    haqiqatan yiqilishini isbotlaydi. Ishlab chiqarish kodida ISHLATILMAYDI."""
    best, best_since = None, None
    for name, off in sorted(offsets.items()):
        since = since_midnight(now, off)
        if best_since is None or since > best_since:
            best, best_since = name, since
    return best
