# -*- coding: utf-8 -*-
"""DEMO-TARIX LIFECYCLE — HISTORICAL_BUILD -> LIVE_DEMO holat qatlami.

Bu fayl `Setting(key='cash')` qatorining UCH shaklini va ikki o'tishni qulflaydi.
Marshrut (HTTP) testlari alohida: `tests/test_demo_history_routes.py`.

A  `mark_historical_build` shakli: bayroq BOR, `ledger_native`/`cutover_at` YO'Q
B  ASOSIY ILGAK: `mark_ledger_native` qurilish qatorini TEGMAYDI (va teskarisi — toza
   kompaniyada YOZADI, ya'ni test bo'sh emas)
C  `mark_historical_build` mavjud `cash` qatori ustida RAD etiladi (ikki yo'l bilan)
D  `finalize` TO'RT kalitni BIRGA yozadi, bayroqni olib tashlaydi, T0 mikrosekundini saqlaydi
E  `finalize` idempotent: ayni T0 -> duplicate; boshqa T0 -> ziddiyat
F  `finalize` fail-closed rad etishlari (5 holat)
G  OCHIQ XAVF (QAYD ETILGAN NUQSON): buzuq `cutover_at` tarixiy darvozani QAYTA OCHADI
H  `is_historical_build` T0 yo'qligiga TAYANMAYDI (legacy tenant qurilish emas)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.org import Company
from app.models.settings import Setting
from app.services.cash import cutover as _cut
from app.services.cash import tenant as _t

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
#  T0 mikrosekundli ATAYLAB: `finalize` ni `max(occurred_at) + 1 µs` bilan chaqiradi va
#  ISO round-trip mikrosekundni YO'QOTMASLIGI kerak (aks holda oxirgi tarixiy qator
#  `>= T0` bo'lib LIVE tomonga tushardi).
T0 = datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc) + timedelta(microseconds=1)


def db_():
    from app.db.session import SessionLocal
    return SessionLocal()


@pytest.fixture
def db():
    s = db_()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _co(db, prefix="demo"):
    """Do'kon. Kod NOYOB: fayl umumiy seans bazasida ishlaydi."""
    c = Company(id=uuid.uuid4(), name="Demo LC", code=f"{prefix}-lc-{uuid.uuid4().hex[:8]}",
                currency="KGS")
    db.add(c)
    db.flush()
    return c


def _val(db, company_id) -> dict:
    row = (db.query(Setting)
           .filter(Setting.company_id == company_id, Setting.branch_id.is_(None),
                   Setting.key == "cash").first())
    return dict(row.value or {}) if row is not None else {}


def _rows(db, company_id) -> int:
    return int(db.query(Setting)
               .filter(Setting.company_id == company_id, Setting.key == "cash").count())


# ═══ A) qurilish shakli ═════════════════════════════════════════
def test_A_qurilish_shakli(db):
    co = _co(db)
    val = _t.mark_historical_build(db, co.id, at=START, plan_id="plan-7")
    db.flush()

    assert val["historical_build"] is True
    assert val["build_started_at"] == START.isoformat()
    assert val["build_plan_id"] == "plan-7"
    #  ASOSIY: ikkisi ham YO'Q. `ledger_native=true` + `cutover_at=NULL` juftligi
    #  ZARARLI (hisobot ledgerni avtoritet deydi, leg esa jimgina tushib qoladi).
    assert "ledger_native" not in val
    assert "cutover_at" not in val

    assert _t.is_historical_build(db, co.id) is True
    assert _t.is_ledger_native(db, co.id) is False
    assert _t.is_ledger_authoritative(db, co.id) is False
    #  Tarixiy darvozaning 4-sharti AYNAN shuni talab qiladi.
    assert _cut.cutover_at(db, co.id) is None
    assert _cut.cutover_reached(db, co.id) is False
    assert _rows(db, co.id) == 1


def test_A2_tarixiy_darvoza_qurilish_tenantida_OCHIQ(db):
    """`assert_demo_tenant` qurilish tenantini QABUL qiladi — gard YUMSHATILMAGAN holda."""
    from app.services import historical as _H
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START)
    db.flush()
    #  Ko'tarilmasligi KERAK (4-shart: T0 belgilanmagan).
    _H.assert_demo_tenant(db, co, require_empty_history=False)

    #  Teskarisi: normal (ledger-native) tenant RAD etiladi — ya'ni yuqoridagi
    #  tasdiq bo'sh emas.
    co2 = _co(db)
    _t.mark_ledger_native(db, co2.id)
    db.flush()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        _H.assert_demo_tenant(db, co2, require_empty_history=False)
    assert ei.value.status_code == 409
    assert "T0" in ei.value.detail


# ═══ B) ASOSIY ILGAK ═══════════════════════════════════════════
def test_B_mark_ledger_native_qurilish_qatorini_TEGMAYDI(db):
    """`admin.py` dagi `mark_ledger_native(...)` chaqiruvi qurilish tenantida NO-OP.

    SHU ilgak tufayli normal provisioning semantikasini o'zgartirish KERAK EMAS:
    qator oldin urug'lansa, `mark_ledger_native` uni tegmasdan qaytaradi. Shart
    AYNAN qator BORLIGI (`tenant.py` ichidagi `row is not None`), kalitlar EMAS.
    """
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START, plan_id=None)
    db.flush()
    oldin = _val(db, co.id)

    qaytgan = _t.mark_ledger_native(db, co.id)
    db.flush()

    assert _val(db, co.id) == oldin, "qurilish qatori O'ZGARDI"
    assert qaytgan == oldin, "qaytarilgan qiymat mavjud qatorga teng bo'lishi kerak"
    assert "ledger_native" not in _val(db, co.id)
    assert "cutover_at" not in _val(db, co.id)
    assert _rows(db, co.id) == 1, "ikkinchi `cash` qatori yaratildi"
    assert _t.is_historical_build(db, co.id) is True


def test_B2_mark_ledger_native_TOZA_kompaniyada_YOZADI(db):
    """B bo'sh emasligining isboti: ayni funksiya qatorsiz kompaniyada YOZADI."""
    co = _co(db)
    val = _t.mark_ledger_native(db, co.id)
    db.flush()
    assert val["ledger_native"] is True
    assert val["cutover_at"] == val["onboarded_at"]
    assert _t.is_ledger_native(db, co.id) is True
    assert _cut.cutover_reached(db, co.id) is True
    assert _t.is_historical_build(db, co.id) is False


# ═══ C) mavjud qator ustida RAD ═════════════════════════════════
def test_C_qurilish_IKKINCHI_marta_RAD(db):
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START)
    db.flush()
    with pytest.raises(_t.HistoricalBuildConflict) as ei:
        _t.mark_historical_build(db, co.id, at=START)
    assert "ALLAQACHON" in str(ei.value)
    assert _rows(db, co.id) == 1


def test_C2_HAQIQIY_tenantni_qurilishga_tortib_kiritish_RAD(db):
    """NC2: mavjud (ledger-native) do'konni HISTORICAL_BUILD holatiga o'tkazib bo'lmaydi."""
    co = _co(db)
    _t.mark_ledger_native(db, co.id)
    db.flush()
    oldin = _val(db, co.id)
    with pytest.raises(_t.HistoricalBuildConflict):
        _t.mark_historical_build(db, co.id, at=START)
    assert _val(db, co.id) == oldin, "haqiqiy tenantning `cash` qatori o'zgardi"
    assert _t.is_historical_build(db, co.id) is False


# ═══ D) finalize ══════════════════════════════════════════════
def test_D_finalize_TORT_kalitni_BIRGA_yozadi(db):
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START)
    db.flush()

    yangi, created = _t.finalize_historical_build(db, co.id, t0=T0)
    db.flush()

    assert created is True
    assert yangi["ledger_native"] is True
    assert yangi["onboarded_at"] == START.isoformat(), "onboarded_at = build_started_at"
    assert yangi["cutover_at"] == T0.isoformat()
    assert yangi["historical_build_finalized_at"]
    assert "historical_build" not in yangi, "bayroq olib tashlanmadi"
    assert "build_started_at" not in yangi and "build_plan_id" not in yangi

    assert _t.is_historical_build(db, co.id) is False
    assert _t.is_ledger_native(db, co.id) is True
    assert _cut.cutover_reached(db, co.id) is True
    assert _rows(db, co.id) == 1, "finalize ikkinchi qator yaratdi"
    #  MIKROSEKUND SAQLANDI: aks holda oxirgi tarixiy qator `>= T0` bo'lib LIVE
    #  tomonga tushardi (`compare_engine` / `phase1` / `preflight` qoidasi).
    assert _cut.cutover_at(db, co.id) == T0
    assert _cut.cutover_at(db, co.id).microsecond == 1


def test_D2_finalizedan_keyin_tarixiy_darvoza_YOPILADI(db):
    """NC8: finalize'dan keyin yuza O'ZI yopiladi — kod o'zgarishi KERAK EMAS."""
    from fastapi import HTTPException
    from app.services import historical as _H
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START)
    db.flush()
    _H.assert_demo_tenant(db, co, require_empty_history=False)      # OCHIQ

    _t.finalize_historical_build(db, co.id, t0=T0)
    db.flush()

    with pytest.raises(HTTPException) as ei:                        # YOPIQ
        _H.assert_demo_tenant(db, co, require_empty_history=False)
    assert ei.value.status_code == 409
    assert "T0" in ei.value.detail


# ═══ E) idempotentlik ═══════════════════════════════════════
def test_E_finalize_AYNI_T0_bilan_idempotent(db):
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START)
    db.flush()
    birinchi, c1 = _t.finalize_historical_build(db, co.id, t0=T0)
    db.flush()
    ikkinchi, c2 = _t.finalize_historical_build(db, co.id, t0=T0)
    db.flush()

    assert (c1, c2) == (True, False)
    assert ikkinchi["cutover_at"] == birinchi["cutover_at"]
    #  Takror YON TA'SIR BERMAYDI: `finalized_at` ham o'zgarmaydi.
    assert ikkinchi["historical_build_finalized_at"] == birinchi["historical_build_finalized_at"]
    assert _rows(db, co.id) == 1


def test_E2_finalize_BOSHQA_T0_bilan_ZIDDIYAT(db):
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START)
    db.flush()
    _t.finalize_historical_build(db, co.id, t0=T0)
    db.flush()
    oldin = _val(db, co.id)

    with pytest.raises(_t.HistoricalBuildConflict) as ei:
        _t.finalize_historical_build(db, co.id, t0=T0 + timedelta(days=1))
    assert "QAYTA YOZILMAYDI" in str(ei.value)
    assert _val(db, co.id) == oldin, "ziddiyatli urinish qatorni o'zgartirdi"


# ═══ F) fail-closed rad etishlar ═══════════════════════════════
def test_F_finalize_qurilish_BO_LMAGAN_tenantda_RAD(db):
    co = _co(db)
    _t.mark_ledger_native(db, co.id)
    db.flush()
    with pytest.raises(_t.HistoricalBuildConflict) as ei:
        _t.finalize_historical_build(db, co.id, t0=T0)
    assert "HISTORICAL_BUILD holatida emas" in str(ei.value)


def test_F2_finalize_cash_qatori_YO_Q_tenantda_RAD(db):
    co = _co(db)
    with pytest.raises(_t.HistoricalBuildConflict) as ei:
        _t.finalize_historical_build(db, co.id, t0=T0)
    assert "topilmadi" in str(ei.value)


def test_F3_finalize_NAIVE_T0_ni_RAD_etadi(db):
    """Kanonik UTC talab qilinadi — naive datetime jim UTC deb o'qilmaydi."""
    co = _co(db)
    _t.mark_historical_build(db, co.id, at=START)
    db.flush()
    with pytest.raises(_t.HistoricalBuildConflict) as ei:
        _t.finalize_historical_build(db, co.id, t0=datetime(2026, 3, 1, 9, 30))
    assert "timezone-aware" in str(ei.value)
    assert _t.is_historical_build(db, co.id) is True, "rad etilgan urinish holatni o'zgartirdi"


def test_F4_buzuq_build_started_at_RAD(db):
    """`onboarded_at` TAXMIN QILINMAYDI — jim T0 bilan to'ldirish audit yolg'oni bo'lardi."""
    co = _co(db)
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"historical_build": True, "build_started_at": "not-a-date"}))
    db.flush()
    with pytest.raises(_t.HistoricalBuildConflict) as ei:
        _t.finalize_historical_build(db, co.id, t0=T0)
    assert "yaroqsiz" in str(ei.value)


def test_F5_buzilgan_holat_bayroq_va_T0_birga_RAD(db):
    """Qurilish bayrog'i bilan `cutover_at` BIRGA bo'lishi mumkin emas — jim tuzatmaymiz."""
    co = _co(db)
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"historical_build": True, "build_started_at": START.isoformat(),
                          "cutover_at": T0.isoformat()}))
    db.flush()
    with pytest.raises(_t.HistoricalBuildConflict) as ei:
        _t.finalize_historical_build(db, co.id, t0=T0)
    assert "Buzilgan holat" in str(ei.value)


# ═══ G) OCHIQ XAVF — QAYD ETILGAN NUQSON ══════════════════════════
def test_G_buzuq_cutover_at_tarixiy_darvozani_QAYTA_OCHADI(db):
    """⚠️  BU TEST KUTILGAN XULQNI EMAS, MAVJUD NUQSONNI qulflaydi.

    `cutover.cutover_at` yaroqsiz ISO qiymatda `None` qaytaradi (FAIL-OPEN:
    `except (ValueError, TypeError)`). Natijada YAKUNLANGAN demo tenantda `cash`
    qiymati buzilsa, `assert_demo_tenant` ning 4-sharti yana O'TADI va imtiyozli
    tarixiy yuza QAYTA OCHILADI.

    Bu lifecycle tomonidan TUZATILMAGAN va reportda OCHIQ XAVF sifatida qoldirilgan.
    Kimdir `cutover.py` ni fail-closed qilsa BU TEST QIZIL bo'ladi — bu to'g'ri
    signal: o'zgarish ATAYLAB qilinishi va shu yerda qayd etilishi kerak.

    Nimani SAQLAYDI: lifecycle qarorlari T0 yo'qligiga EMAS, `historical_build`
    bayrog'iga tayanadi — shu bois buzuq T0 tenantni "qurilishda" deb
    KO'RSATOLMAYDI va `finalize` qayta ishlamaydi.
    """
    from app.services import historical as _H
    co = _co(db)
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"ledger_native": True, "onboarded_at": START.isoformat(),
                          "cutover_at": "not-a-date",
                          "historical_build_finalized_at": START.isoformat()}))
    db.flush()

    # NUQSON: T0 o'qilmaydi -> darvoza ochiq.
    assert _cut.cutover_at(db, co.id) is None
    assert _cut.cutover_reached(db, co.id) is False
    _H.assert_demo_tenant(db, co, require_empty_history=False)   # ko'tarmaydi (NUQSON)

    # HIMOYA SAQLANADI: holat "qurilish" deb ko'rinmaydi.
    assert _t.is_historical_build(db, co.id) is False
    assert _t.is_ledger_native(db, co.id) is True
    with pytest.raises(_t.HistoricalBuildConflict):
        _t.finalize_historical_build(db, co.id, t0=T0)


# ═══ H) bayroq vs T0 yo'qligi ══════════════════════════════════
def test_H_LEGACY_tenant_qurilish_EMAS(db):
    """T0 yo'q ≠ qurilish. `cash` qatori UMUMAN yo'q legacy tenant — eng keng holat."""
    co = _co(db)
    db.flush()
    assert _cut.cutover_at(db, co.id) is None          # T0 yo'q
    assert _t.is_historical_build(db, co.id) is False  # lekin qurilish EMAS
    assert _t.is_ledger_native(db, co.id) is False
    #  Va `finalize` unga TEGMAYDI.
    with pytest.raises(_t.HistoricalBuildConflict):
        _t.finalize_historical_build(db, co.id, t0=T0)
