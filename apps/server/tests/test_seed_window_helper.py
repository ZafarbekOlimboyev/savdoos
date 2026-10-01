# -*- coding: utf-8 -*-
"""`seed_date_in_window()` — hisobot oynasiga tushadigan sana, KALENDARGA bog'lanmagan.

⚠️  NIMA NOTO'G'RI EDI. `/reports/history/seed` ni ishlatadigan oltita test sanani
    QATTIQ KODLAGAN edi (`05.09.2026`, `12.09.2026`), hisobot esa `?period=month`
    bilan JORIY oy oynasini so'raydi (`reports.py::_window` → `nl.replace(day=1)`,
    do'kon mahalliy zonasida). 2026-10-01 dan boshlab sentabr qatori oynadan chiqdi,
    hamma delta 0 bo'ldi va oltita test BARQAROR qizil bo'lib qoldi — `main` ning
    o'zida ham. Bu flaky emas edi: kalendar o'tib ketgan edi.

Quyidagilar aynan shu holatni qaytarishga qarshi qo'riqchi. Ular SOF funksiyani
(`seed_dt_in_window`) tekshiradi, ya'ni bazaga ham, hozirgi sanaga ham bog'liq emas —
va ATAYLAB hech qanday aniq oyga (sentabr/oktabr 2026) bog'lanmaydi.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from tests.conftest import seed_dt_in_window

SEED_FMT = "%d.%m.%Y %H:%M:%S"
TESTS_DIR = pathlib.Path(__file__).resolve().parent


def _month_start(x: dt.datetime) -> dt.datetime:
    return x.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# Har xil zonalar — hisobot `_store_tz` bo'yicha +3..+7 oralig'ida ishlaydi.
TZS = [dt.timezone(dt.timedelta(hours=h)) for h in (3, 4, 5, 6, 7)]

# Oyning BOSHI, O'RTASI va OXIRI — har bir oy uchun, kabisa yili ham.
CASES = [
    (y, m, d, hh)
    for y in (2026, 2027, 2028)          # 2028 — kabisa
    for m in range(1, 13)
    for d, hh in ((1, 0), (1, 10), (2, 3), (15, 12), (28, 23))
]


@pytest.mark.parametrize("tz", TZS)
@pytest.mark.parametrize("y,m,d,hh", CASES)
def test_natija_HAR_DOIM_oyna_ICHIDA(y, m, d, hh, tz):
    """`oy boshi <= natija <= hozir` — oynaning IKKALA chekkasi ham.

    Oyna: `[oy boshi 00:00 (mahalliy), hozir + 1s)`, va filtr `sold_at >= start`
    (`reports.py:654`), ya'ni oy boshining O'ZI ham qamrab olinadi."""
    now_local = dt.datetime(y, m, d, hh, 37, 11, tzinfo=tz)
    got = seed_dt_in_window(now_local)
    assert _month_start(now_local) <= got <= now_local, (now_local, got)


@pytest.mark.parametrize("y,m,d,hh", CASES)
def test_natija_HAR_DOIM_joriy_oyda(y, m, d, hh):
    """Natija boshqa oyga (ayniqsa OLDINGISIGA) tushib ketmasin — aynan shu
    nuqson oltita testni qizil qilgan edi."""
    now_local = dt.datetime(y, m, d, hh, 5, 0, tzinfo=dt.timezone.utc)
    got = seed_dt_in_window(now_local)
    assert (got.year, got.month) == (now_local.year, now_local.month), (now_local, got)


def test_OY_BOSHIDA_oldingi_oyga_TUSHMAYDI():
    """Oyning 1-kuni, soat 00:30 — «26 soat oldin» oldingi oyga tushardi.
    Clamp uni oy boshiga tortadi."""
    now_local = dt.datetime(2027, 3, 1, 0, 30, tzinfo=dt.timezone.utc)
    got = seed_dt_in_window(now_local)
    assert got == _month_start(now_local)
    assert got <= now_local


def test_OY_ORTASIDA_kechagi_kun_tanlanadi():
    """Imkon bo'lganda sana «tarixiy» bo'lib qoladi — testlarning asl niyati shu."""
    now_local = dt.datetime(2027, 3, 15, 12, 0, tzinfo=dt.timezone.utc)
    got = seed_dt_in_window(now_local)
    assert got == now_local - dt.timedelta(hours=26)
    assert got.day == 14


def test_KABISA_29_fevral_ham_ishlaydi():
    now_local = dt.datetime(2028, 2, 29, 9, 0, tzinfo=dt.timezone.utc)
    got = seed_dt_in_window(now_local)
    assert (got.year, got.month) == (2028, 2)
    assert _month_start(now_local) <= got <= now_local


def test_FORMAT_serverning_parseri_bilan_mos():
    """`history_seed` `%d.%m.%Y %H:%M:%S` ni kutadi (`reports.py`)."""
    now_local = dt.datetime(2027, 7, 9, 18, 44, 2, tzinfo=dt.timezone.utc)
    text = seed_dt_in_window(now_local).strftime(SEED_FMT)
    assert dt.datetime.strptime(text, SEED_FMT) == dt.datetime(2027, 7, 8, 16, 44, 2)


# ── Qo'riqchi: sana QAYTA qattiq kodlanmasin ──────────────────────────────────

@pytest.mark.parametrize("fname", ["test_cost_provenance.py",
                                   "test_history_seed_cost_basis.py"])
def test_history_seed_chaqiruvlari_QATTIQ_sana_ishlatmaydi(fname):
    """`period=month` bilan solishtiriladigan seed qatorlari kalendarga
    bog'lanmasin. Qattiq sana qaytib kelsa — bu test uni ushlaydi."""
    text = (TESTS_DIR / fname).read_text(encoding="utf-8")
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "seed_date_in_window" in code, (
        "%s endi oyna ichidagi sanani ishlatmayapti" % fname)

    # ⚠️  QATTIQ sana HAR QANDAY seed qatorida taqiqlanmaydi — faqat `period=month`
    #     bilan solishtiriladiganlarida. `_row()` (test_history_seed_cost_basis.py:38)
    #     ATAYLAB qattiq yanvar sanasini saqlaydi: uni faqat validatsiya,
    #     idempotentlik va sxema testlari ishlatadi (53, 66, 74, 81, 149-qatorlar) —
    #     ularning birortasi ham hisobot oynasiga qaramaydi, ya'ni kalendar
    #     o'tishi ularga ta'sir qilmaydi.
    ALLOW = ("def _row(",)
    lines = code.splitlines()
    for i, line in enumerate(lines):
        if "revenue" not in line or '"date"' not in line:
            continue
        oldingi = "\n".join(lines[max(0, i - 3):i])
        if any(a in oldingi or a in line for a in ALLOW):
            continue
        assert "seed_date_in_window" in line, (
            "%s: oyna bilan solishtiriladigan seed qatorida QATTIQ sana qaytdi: %s"
            % (fname, line.strip()))
