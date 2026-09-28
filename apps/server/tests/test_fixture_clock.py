# -*- coding: utf-8 -*-
"""`tests/_clock.py` qo'riqchisi — kun oynasiga bog'liq HAMMA fikstura shunga tayanadi.

Bu yerdagi testlar bitta hodisadan o'sgan: to'liq regressiya ikki marta ketma-ket qizil
bo'ldi, chunki fikstura zonasi yarim tunga eng YAQIN zonani tanlardi va uzoq yurish o'sha
yarim tunni kesib o'tardi. Sabab har safar mavhum «0.0 == 900.0» bo'lib ko'rinardi.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

from tests._clock import MIN_HEADROOM, MIN_SINCE, pick_store_tz, seed_moment

#: Kunning har daqiqasi — chorak soatlik namuna chegara holatlarini o'tkazib yuborardi.
_KUN = [datetime(2026, 6, 15, m // 60, m % 60, tzinfo=timezone.utc) for m in range(1440)]


def _local(now: datetime, tz: str):
    from app.api.v1.reports import _TZ_OFFSETS
    return timezone(timedelta(hours=_TZ_OFFSETS[tz]))


def test_ZONA_har_qanday_daqiqada_yarim_tundan_UZOQ():
    """Tanlangan zonada yarim tungacha kafolatlangan zaxira qoladi.

    ⚠️  Mezon teskarisiga ag'darilsa (yarim tundan O'TGAN vaqtni maksimallashtirish) bu
        zaxira BIR daqiqagacha tushadi — test aynan o'sha regressiyani ushlaydi.
    """
    worst = None
    for now in _KUN:
        tz = pick_store_tz(now)
        assert tz is not None, ("nomzod topilmadi", now)
        local = now.astimezone(_local(now, tz))
        since = local.hour * 3600 + local.minute * 60 + local.second
        assert since >= MIN_SINCE, ("zona yarim tundan yetarli o'tmagan", now, tz, since)
        left = 86400 - since
        if worst is None or left < worst[0]:
            worst = (left, f"{now:%H:%M}Z -> {tz}")
    assert worst[0] >= MIN_HEADROOM, (
        "tanlangan zona yarim tunga juda yaqin — uzoq yurish kun oynasini kesib o'tishi mumkin",
        worst)


def test_URUG_har_qanday_daqiqada_dokon_kuni_ICHIDA():
    """`seed_moment()` har doim `[mahalliy yarim tun, now)` oralig'ida."""
    for now in _KUN:
        tz = pick_store_tz(now)
        at = seed_moment(now, tz)
        local = _local(now, tz)
        midnight = now.astimezone(local).replace(hour=0, minute=0, second=0, microsecond=0)
        assert midnight <= at.astimezone(local), (now, tz, at, midnight)
        assert at < now, (now, tz, at)


def test_ZONA_tanlash_mantigi_NUSXALANMAGAN():
    """Bu mantiqning ikkinchi nusxasi paydo bo'lmasin.

    AYNAN shu xato qimmatga tushgan: 98f5b00 mantiqni ikki faylga nusxalagan, biri keyin
    tuzatilib ikkinchisi qolgan va to'liq regressiya (~2 soat) qayta qizil bo'lgan.
    """
    root = pathlib.Path(__file__).parent
    #  `_clock.py` — manbaning o'zi; bu fayl esa izlarni matn sifatida saqlaydi.
    ozi = {"_clock.py", pathlib.Path(__file__).name}
    izlar = ("def _pick_store_tz", "best_since")
    bad = sorted({f.relative_to(root).as_posix()
                  for f in root.rglob("*.py") if f.name not in ozi
                  for t in izlar if t in f.read_text(encoding="utf-8")})
    assert not bad, (
        "zona tanlash mantig'i nusxalangan — `tests/_clock.py` dan import qiling", bad)
