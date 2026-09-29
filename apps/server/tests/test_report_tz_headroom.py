# -*- coding: utf-8 -*-
"""YARIM TUN TUZOG'I — deterministik regressiya.

NIMANI ISBOTLAYDI: hisobot testlari tanlagan do'kon zonasi 85 daqiqalik to'liq regressiya
mahalliy yarim tunni KESIB O'TMASLIGINI kafolatlaydi, va eski tanlov buni kafolatlamasdi.

⚠️ MASHINA SOATIGA BOG'LIQ EMAS. Hamma lahzalar sintetik: sutkaning har daqiqasi bo'ylab
yuriladi. Shu bois isbot yurish qaysi vaqtda bajarilganidan QAT'I NAZAR bir xil.

KUZATILGAN NUQSON (2026-09-29): to'liq regressiyada aynan 7 ta test yiqilardi —
`test_report_scope.py` dagi oltitasi va `test_mobile_parity.py` dagi bittasi. Belgi: javobdagi
HAMMA «bugungi» qiymat 0.0 (`paid_today`, cashflow `in`/`out`, `opening`), bugunga bog'liq
bo'lmaganlari esa TO'G'RI (`total` 500.0, `debtors` 1). Ma'lumot bor edi — u «bugun» deb
sanalmasdi.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.reports import _TZ_OFFSETS
from tests.report_tz_helpers import (MIN_HEADROOM, MIN_SINCE_MIDNIGHT, headroom, pick_store_tz,
                                     pick_store_tz_LEGACY, since_midnight)

#: To'liq regressiyaning o'lchangan davomiyligi (65–83 daq). Zaxira shundan katta bo'lishi kerak.
RUN = timedelta(minutes=85)

#: Sutkaning HAR daqiqasi — sintetik, mashina soatidan mustaqil.
DAY = [datetime(2026, 9, 28, h, m, tzinfo=timezone.utc) for h in range(24) for m in range(60)]

#: Nuqson AYNAN kuzatilgan ikki lahza (jurnal va simulyatsiyadan).
KUZATILGAN = [
    (datetime(2026, 9, 28, 19, 6, tzinfo=timezone.utc), "Asia/Baku"),
    (datetime(2026, 9, 28, 20, 30, tzinfo=timezone.utc), "Europe/Moscow"),
]


def _left(now: datetime, tz: str) -> timedelta:
    return headroom(now, _TZ_OFFSETS[tz])


# ── 1. YANGI TANLOV: sutkaning HAR daqiqasida yetarli zaxira ──────────────────────────────
def test_YANGI_tanlov_sutkaning_HAR_daqiqasida_zaxira_beradi():
    yomon = [(n, _left(n, pick_store_tz(n, _TZ_OFFSETS))) for n in DAY
             if _left(n, pick_store_tz(n, _TZ_OFFSETS)) < MIN_HEADROOM]
    assert not yomon, f"{len(yomon)} daqiqada zaxira {MIN_HEADROOM} dan kam, masalan {yomon[:3]}"


def test_YANGI_tanlov_eng_yomon_holatda_ham_YURISHDAN_uzoq():
    eng_yomon = min(_left(n, pick_store_tz(n, _TZ_OFFSETS)) for n in DAY)
    assert eng_yomon > RUN, f"eng yomon zaxira {eng_yomon} <= yurish {RUN}"


def test_YANGI_tanlov_AT_ni_yarim_tundan_KEYIN_qoldiradi():
    """`_at()` faktni yarim tun + 60 s ga qo'yadi; zona yarim tunga juda yaqin bo'lsa u
    `NOW - 1 s` ga qisilib, yarim tundan OLDINGA tushib ketardi."""
    for n in DAY:
        assert since_midnight(n, _TZ_OFFSETS[pick_store_tz(n, _TZ_OFFSETS)]) >= MIN_SINCE_MIDNIGHT


# ── 2. ESKI TANLOV: shu talabni BUZADI (yangi test eski xulqda haqiqatan yiqiladi) ─────────
def test_ESKI_tanlov_shu_talabni_BUZADI():
    """Tuzatish bo'sh emasligining isboti: eski algoritm sutkaning sezilarli qismida
    yurishdan qisqa zaxira beradi."""
    buzilgan = [n for n in DAY if _left(n, pick_store_tz_LEGACY(n, _TZ_OFFSETS)) < RUN]
    assert buzilgan, "eski tanlov hech qachon yiqilmasa, bu test hech narsani isbotlamaydi"
    ulush = 100.0 * len(buzilgan) / len(DAY)
    assert ulush > 3.0, f"eski tanlov sutkaning atigi {ulush:.1f}% ida yiqiladi — kutilgandan kam"
    print(f"\n[ESKI] sutkaning {ulush:.1f}% ida ({len(buzilgan)}/1440 daqiqa) zaxira {RUN} dan kam")


@pytest.mark.parametrize("now,kutilgan_eski_zona", KUZATILGAN)
def test_KUZATILGAN_yurishlar_eski_xulqda_YIQILADI_yangisida_YIQILMAYDI(now, kutilgan_eski_zona):
    """Haqiqiy jurnaldagi ikki lahza — nazariy emas, o'lchangan."""
    eski = pick_store_tz_LEGACY(now, _TZ_OFFSETS)
    assert eski == kutilgan_eski_zona, f"eski algoritm {eski} tanladi, kutilgani {kutilgan_eski_zona}"
    assert _left(now, eski) < RUN, "kuzatilgan yurish yarim tunni kesmasa, tavsif noto'g'ri"
    assert _left(now, pick_store_tz(now, _TZ_OFFSETS)) >= MIN_HEADROOM


# ── 3. HAQIQIY INVARIANT: AT yurish OXIRIGACHA «bugun» bo'lib qoladi ──────────────────────
def _at_like(now: datetime, tz: str) -> datetime:
    """`test_report_scope._at()` bilan AYNI mantiq: mahalliy yarim tun + 60 s, lekin `now` dan oldin."""
    local = timezone(timedelta(hours=_TZ_OFFSETS[tz]))
    midnight = now.astimezone(local).replace(hour=0, minute=0, second=0, microsecond=0)
    return min(midnight + timedelta(seconds=60), now - timedelta(seconds=1)).astimezone(timezone.utc)


def _day_start_like(at_time: datetime, tz: str) -> datetime:
    """`reports.py` bilan AYNI mantiq: tasdiqlash vaqtidagi mahalliy yarim tun (UTC da)."""
    local = timezone(timedelta(hours=_TZ_OFFSETS[tz]))
    return (at_time.astimezone(local)
            .replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc))


def test_YANGI_tanlovda_AT_yurish_oxirida_ham_BUGUN_bolib_qoladi():
    """ASL NUQSONNING O'ZI, deterministik shaklda.

    `AT` import vaqtida yoziladi, `day_start` esa ~85 daqiqa keyin hisoblanadi. Invariant:
    `AT >= day_start`. Buzilsa — hamma «bugungi» yig'indi nolga tushadi."""
    for now in DAY:
        tz = pick_store_tz(now, _TZ_OFFSETS)
        at = _at_like(now, tz)
        assert at >= _day_start_like(now + RUN, tz), f"{now} / {tz}: AT yurish oxirida 'kecha' bo'lib qoldi"


def test_ESKI_tanlovda_AYNI_invariant_BUZILADI():
    """Xuddi shu invariant eski tanlovda buziladi — ya'ni yuqoridagi test eski xulqni TUTADI."""
    buzilgan = []
    for now in DAY:
        tz = pick_store_tz_LEGACY(now, _TZ_OFFSETS)
        if _at_like(now, tz) < _day_start_like(now + RUN, tz):
            buzilgan.append(now)
    assert buzilgan, "eski tanlov invariantni buzmasa, regressiya isboti yo'q"
    print(f"\n[ESKI] invariant sutkaning {len(buzilgan)}/1440 daqiqasida buziladi "
          f"(masalan {buzilgan[0]:%H:%M}Z)")


def test_IKKALA_hisobot_moduli_AYNI_yordamchidan_foydalanadi():
    """Ilgari har fayl o'z nusxasini saqlardi — shuning uchun NUQSON ham ikkalasida ham bor edi."""
    import tests.test_mobile_parity as mp
    import tests.test_report_scope as rs
    for mod in (rs, mp):
        assert mod.TZ in _TZ_OFFSETS
        assert headroom(mod.NOW, _TZ_OFFSETS[mod.TZ]) >= MIN_HEADROOM, (
            f"{mod.__name__}: zaxira {headroom(mod.NOW, _TZ_OFFSETS[mod.TZ])} — yordamchi ulanmagan?")
