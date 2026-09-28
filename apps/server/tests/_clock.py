# -*- coding: utf-8 -*-
"""Fikstura soati — kun oynasiga bog'liq testlar uchun YAGONA manba.

NEGA ALOHIDA MODUL
==================
Bu mantiq ilgari `test_report_scope.py` va `test_mobile_parity.py` da IKKI NUSXA bo'lib
yashagan (98f5b00 ikkalasiga bir vaqtda qo'ygan). Nusxalardan biri tuzatilib ikkinchisi
tuzatilmay qolgani uchun to'liq regressiya qayta qizil bo'ldi. Nusxa qolmasin — manba bitta.

MUAMMO
======
Kun oynasiga bog'liq testlar `NOW` ni MODUL IMPORT bo'lganda muzlatadi va faktlarni
«mahalliy yarim tun + 60 s» ga yozadi. Hisobot esa oynani HAR SO'ROVDA `[mahalliy yarim
tun, hozir]` deb QAYTA hisoblaydi. To'liq to'plam bir-ikki soat yuradi: shu oraliqda
tanlangan zona yarim tunni KESIB o'tsa, oyna ERTANGI kunga suriladi va ekilgan faktlar
«kechagi» bo'lib qoladi — «bugungi» hamma raqam NOLGA aylanadi.

MEZON
=====
⚠️  Zona yarim tundan O'TGAN vaqtga qarab EMAS, yarim tunga QOLGAN vaqtga qarab tanlanadi.
    Ikkisi TESKARI: o'tgani eng ko'p zona = yarim tuniga eng YAQIN zona, ya'ni zaxirasi eng
    KAM. Eski mezon kun davomida 1440 daqiqadan 309 tasida (21%) 70 daqiqalik yurishga ham
    yetmaydigan zaxira berardi; eng yomoni — BIR daqiqa.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: Zona yarim tundan KAMIDA shuncha o'tgan bo'lsin. 120 s AYNAN tanlangan: `seed_moment()`
#  yarim tunga 60 s qo'shadi, demak bu chegara urug'ni `now` dan doim OLDIN qoldiradi va uni
#  qisqartirishga hojat qolmaydi — ya'ni urug' har doim aniq `yarim tun + 60 s`.
MIN_SINCE = 120

#: Tanlangan zonada yarim tungacha kafolatlangan eng kam zaxira (o'lchangan: 3 s 59 d).
#  Offsetlar 3..7 oralig'i 4 soat bo'lgani uchun bundan ko'pini olib bo'lmaydi: +7 zona yarim
#  tundan endigina o'tib `MIN_SINCE` dan tushganda eng yaxshi qolgani +3 bo'ladi.
MIN_HEADROOM = 3 * 3600


def _offsets() -> dict:
    from app.api.v1.reports import _TZ_OFFSETS
    return _TZ_OFFSETS


def _since_midnight(now: datetime, off: int) -> int:
    local = now.astimezone(timezone(timedelta(hours=off)))
    return local.hour * 3600 + local.minute * 60 + local.second


def pick_store_tz(now: datetime) -> str:
    """Yarim tunga eng KO'P vaqt qolgan zonani tanlaydi.

    `MIN_SINCE` pastki chegarasidan tushganlari chetlanadi. Offsetlar bir soat qadam bilan
    borgani uchun ko'pi bilan BITTA zona tushib qoladi, demak nomzod har doim topiladi.
    """
    best, best_left = None, -1
    for name, off in sorted(_offsets().items()):
        since = _since_midnight(now, off)
        left = 86400 - since
        if since >= MIN_SINCE and left > best_left:
            best, best_left = name, left
    return best


def seed_moment(now: datetime, tz: str) -> datetime:
    """Fakt yoziladigan lahza: do'konning BUGUNGI kuni ichida, `now` dan oldin (UTC).

    Yarim tundan 60 s keyin — shunda `period=day|week|month` va soatlik oynalar hammasi
    qamraydi. `MIN_SINCE` tufayli qisqartirish hech qachon ishlamaydi, lekin himoya sifatida
    qoldirilgan: chegara o'zgarsa ham natija `now` dan oldin qoladi.
    """
    local = timezone(timedelta(hours=_offsets()[tz]))
    midnight = now.astimezone(local).replace(hour=0, minute=0, second=0, microsecond=0)
    return min(midnight + timedelta(seconds=60), now - timedelta(seconds=1)).astimezone(timezone.utc)


def assert_seed_inside_store_day(tz: str, at: datetime) -> None:
    """Urug' hali ham do'konning BUGUNGI kunida ekanini TIRIK soat bilan tekshiradi.

    ⚠️  `now` ATAYLAB muzlagan modul konstantasidan OLINMAYDI. Ilgari qo'riqchi import
        lahzasiga tayanardi va shu sababli yarim tun kesib o'tilganda ham yashil qolardi —
        aybni esa hisobot testlari sababsiz nollar bilan ko'tarardi.
    """
    local = timezone(timedelta(hours=_offsets()[tz]))
    live = datetime.now(timezone.utc)
    midnight = live.astimezone(local).replace(hour=0, minute=0, second=0, microsecond=0)
    assert midnight <= at.astimezone(local), (
        "fikstura vaqti do'kon kunidan chiqib ketdi — to'plam import bilan ijro orasida mahalliy "
        "yarim tunni kesib o'tdi, kun oynasi ertangi kunga surildi", tz, at, midnight, live)
    assert at < live, (at, live)
