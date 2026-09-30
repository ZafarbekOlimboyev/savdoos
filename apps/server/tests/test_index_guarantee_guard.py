# -*- coding: utf-8 -*-
"""MAJBURIY indeks KAFOLATI yo'q bo'lganda — xulq shartnomasi (ega qarori 2026-09-29).

Qaror:
  · nomi YO'Q            -> boot HALOKATLI (o'zgarmagan);
  · nomi bor, NOYOB EMAS -> boot YASHIL, tayyorlik QIZIL, «sog'lom» DEYILMAYDI;
  · o'sha kafolatga tayangan PUL YOZUVI -> FAIL-CLOSED (`index_guard`).

⚠️  OXIRGI BAND ENG MUHIMI: tayyorlik QIZIL bo'lishi HECH QANDAY yozuvni to'smaydi —
    u monitoring signali. Shu bois quyida «tayyorlik qizil» EMAS, «yozuv RAD ETILDI»
    tekshiriladi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.core import index_guard as ig
from app.core import required_schema as rs


@pytest.fixture(autouse=True)
def _clean_cache():
    ig.reset_cache()
    yield
    ig.reset_cache()


# ═══ 1) SINF: noyob emas -> TAYYORLIK, halokatli EMAS ══════════════════════
def test_noyob_emas_xabari_SOFT_sinfida():
    """Boot to'xtamasligi AYNAN shu tasnifga bog'liq."""
    assert rs.is_soft("indeks noyob EMAS: ux_subpay_client_uuid (subscription_payments)")
    assert rs.is_soft("indeks yaroqsiz: ux_x (t)")
    assert rs.is_soft("indeks holatini tekshirib bo'lmadi")
    #  YO'QLIGI esa HALOKATLI bo'lib qoladi — bu shartnoma o'zgarmadi.
    assert not rs.is_soft("indeks yo'q: ux_subpay_client_uuid")


def test_ota_kalit_xabarlari_ham_SOFT():
    """⚠️  R-DDL xabarlari `soft_missing` ga borardi, lekin `_SOFT_PREFIXES` da YO'Q edi —
    ya'ni `/health/ready` ularni «V2 obyekt yo'q» deb sanardi."""
    assert rs.is_soft("ota-kalit indeksi QISMAN: uq_purchases_company_id (...)")
    assert rs.is_soft("ota-kalit indeksi ustunlari mos emas: uq_employees_company_id (...)")
    assert rs.is_soft("ota-kalit indekslarini o'qib bo'lmadi")


# ═══ 2) GARD: kafolat yo'q -> YOZUV RAD ETILADI ════════════════════════════
class _FakeBind:
    """`_unique_index_states` chaqirig'ini almashtirish uchun minimal qobiq."""


def test_gard_kafolat_yoq_bolsa_409_beradi(monkeypatch):
    monkeypatch.setattr(ig, "index_state", lambda *a, **k: ig.BAD)
    with pytest.raises(HTTPException) as ei:
        ig.require_index(_FakeBind(), "ux_subpay_client_uuid", "subscription_payments",
                         operation="sinov")
    assert ei.value.status_code == 409
    assert ig.SCHEMA_GUARANTEE_MISSING in str(ei.value.detail)
    #  Kod sarlavhada ham — mijoz uni dasturiy taniydi.
    assert ei.value.headers.get("X-Error-Code") == ig.SCHEMA_GUARANTEE_MISSING


def test_gard_kafolat_bor_bolsa_OTKAZADI(monkeypatch):
    monkeypatch.setattr(ig, "index_state", lambda *a, **k: ig.OK)
    ig.require_index(_FakeBind(), "ux_subpay_client_uuid", "subscription_payments",
                     operation="sinov")          # istisno YO'Q


def test_gard_TEKSHIRIB_BOLMASA_ham_RAD_etadi(monkeypatch):
    """«Bilmayman» — «xavfsiz» degani EMAS (fail-closed)."""
    def _boom(*a, **k):
        raise RuntimeError("katalog o'qilmadi")
    monkeypatch.setattr(rs, "_unique_index_states", _boom)
    b = _FakeBind()
    assert ig.index_state(b, "ux_subpay_client_uuid", "subscription_payments") == ig.UNVERIFIABLE
    assert ig.index_healthy(b, "ux_subpay_client_uuid", "subscription_payments") is False


def test_TEKSHIRIB_BOLMAGAN_javob_KESHLANMAYDI(monkeypatch):
    """⚠️  ENG MUHIM TUZATISH. Ilgari o'qish XATOSI ham 30 soniyaga `False` deb
        keshlanardi: bitta o'tkinchi nosozlik sog'lom sxemada ham hamma
        qo'riqlangan yozuvni yarim daqiqaga to'sardi (o'z-o'zini kuchaytiruvchi
        uzilish). «Tekshirib bo'lmadi» KESHLANMASLIGI shart."""
    calls = {"n": 0}

    def _flaky(bind, pairs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("o'tkinchi nosozlik")
        return {pairs[0]: rs.IX_OK}

    monkeypatch.setattr(rs, "_unique_index_states", _flaky)
    b = _FakeBind()
    assert ig.index_state(b, "ux_x", "t") == ig.UNVERIFIABLE   # 1-urinish: nosozlik
    #  KESHLANMAGAN bo'lsa — DARHOL qayta tekshiriladi va sog'lom deb topiladi.
    assert ig.index_state(b, "ux_x", "t") == ig.OK, "nosozlik keshlanib qolgan"
    assert calls["n"] == 2


def test_SHAKL_kolligi_YOQ(monkeypatch):
    """⚠️  `indisunique` YETARLI EMAS: nomi to'g'ri, noyob, lekin BOSHQA ustunli
        yoki predikatsiz indeks kafolatni BERMAYDI (qismiy indekslarda o'tkir)."""
    monkeypatch.setattr(rs, "_unique_index_states",
                        lambda bind, pairs: {pairs[0]: rs.IX_OK})
    monkeypatch.setattr(rs, "index_definition_states",
                        lambda bind: {"ux_print_jobs_original": rs.IX_DEF_WRONG})
    b = _FakeBind()
    assert ig.index_state(b, "ux_print_jobs_original", "print_jobs") == ig.BAD,         "noyob, lekin SHAKLI noto'g'ri indeks o'tkazib yuborildi"


def test_BIND_boyicha_ALOHIDA_keshlanadi(monkeypatch):
    """Bitta jarayon bir nechta bazaga ulanishi mumkin — javob aralashmasin."""
    state = {}

    def _st(bind, pairs):
        return {pairs[0]: state[id(bind)]}

    monkeypatch.setattr(rs, "_unique_index_states", _st)
    b1, b2 = _FakeBind(), _FakeBind()
    state[id(b1)], state[id(b2)] = rs.IX_OK, rs.IX_NOT_UNIQUE
    assert ig.index_state(b1, "ux_x", "t") == ig.OK
    assert ig.index_state(b2, "ux_x", "t") == ig.BAD, "kesh bindlar orasida oqib ketdi"


def test_gard_MATNIDA_obyekt_nomi_YOQ(monkeypatch):
    """Javob do'kon xodimiga ketadi — sxema ichki nomlari oshkor qilinmaydi."""
    monkeypatch.setattr(ig, "index_state", lambda *a, **k: ig.BAD)
    with pytest.raises(HTTPException) as ei:
        ig.require_index(_FakeBind(), "ux_subpay_client_uuid", "subscription_payments",
                         operation="sinov")
    assert "ux_subpay_client_uuid" not in str(ei.value.detail)
    assert "subscription_payments" not in str(ei.value.detail)


# ═══ 3) KESH: tuzatilgandan KEYIN o'ziga keladi ════════════════════════════
def test_kesh_TTL_va_tuzatishdan_keyin_tiklanadi(monkeypatch):
    calls = {"n": 0}

    def _state(bind, pairs):
        calls["n"] += 1
        return {pairs[0]: (rs.IX_OK if calls["n"] > 1 else rs.IX_NOT_UNIQUE)}

    monkeypatch.setattr(rs, "_unique_index_states", _state)
    b = _FakeBind()
    assert ig.index_healthy(b, "ux_x", "t") is False       # 1-chaqiruv: buzuq
    assert ig.index_healthy(b, "ux_x", "t") is False       # KESHDAN (katalogga bormaydi)
    assert calls["n"] == 1, "kesh ishlamadi — har yozuvda katalog so'rovi bo'lardi"
    ig.reset_cache()                                       # operator tuzatdi
    assert ig.index_healthy(b, "ux_x", "t") is True        # tuzatishdan keyin OCHILADI
    assert calls["n"] == 2
# ═══ 4) TTL SOZLAMASI — YAROQSIZ ENV SERVERNI SINDIRMAYDI (SAFE-03) ═══════
#
# ⚠️  NIMA UCHUN BU BO'LIM BOR. `_TTL_SECONDS` MODUL DARAJASIDA hisoblanadi, modul esa
#     qo'riqlangan YOZUVCHILAR ichida LAZY import qilinadi (`doc_seq.allocate:143`,
#     `payments.record_payment`). Ilgari qator `float(os.getenv(...) or 10)` edi, ya'ni
#     `SAVDOOS_INDEX_GUARD_TTL=abc` da:
#       · boot va `python -m app.initdb` OMON qolardi (gard boot'da yuklanmaydi);
#       · lekin har qo'riqlangan yozuv `ValueError` bilan yiqilardi — 409 emas, **500**;
#       · import yiqilgan modul `sys.modules` da QOLMAYDI, ya'ni xato HAR so'rovda
#         qaytadan ko'tarilardi (o'lchangan: 3/3 urinish);
#       · `/health` sog'lom ko'rinardi, `doc_seq` esa HAR SOTUVda chaqiriladi.
#     Ya'ni bitta noto'g'ri env qiymati deploy tekshiruvidan o'tib, keyin har sotuvni
#     jimgina sindirardi. Shu bois pastdagi oxirgi test AYNAN SUBPROCESS'da import
#     qiladi: jarayon ichidagi `_env_ttl()` sinovi modul darajasidagi regressiyani
#     USHLAMAYDI.


@pytest.mark.parametrize("xom,kutilgan,label", [
    (None, 10.0, "UNSET -> default"),
    ("", 10.0, "bo'sh satr -> default"),
    ("   ", 10.0, "faqat bo'shliq -> default"),
    ("abc", 10.0, "harfiy axlat -> default (ilgari ValueError)"),
    ("-1", 10.0, "manfiy -> default"),
    ("-0.001", 10.0, "kichik manfiy -> default"),
    ("0", 0.0, "NOL QONUNIY: keshni o'chirishning hujjatlashtirilgan yo'li"),
    ("0.5", 0.5, "kasr qiymat saqlanadi"),
    ("30", 30.0, "butun son saqlanadi"),
    (" 10 ", 10.0, "bo'shliqli qiymat o'qiladi"),
    ("300", 300.0, "yuqori chegaraning O'ZI qonuniy"),
    ("301", 10.0, "chegaradan 1 s oshgani -> default"),
    ("999999999999", 10.0, "ulkan -> default (ilgari ~31 700 yillik kesh)"),
    ("inf", 10.0, "inf parse bo'ladi, lekin diapazondan tashqari"),
    ("-inf", 10.0, "-inf diapazondan tashqari"),
    ("nan", 10.0, "nan: har qanday taqqoslash False -> default"),
    ("1e400", 10.0, "1e400 -> inf -> default"),
    ("10,5", 10.0, "vergulli kasr (ru locale) -> default"),
])
def test_TTL_env_har_qiymat_uchun_DETERMINISTIK(monkeypatch, xom, kutilgan, label):
    if xom is None:
        monkeypatch.delenv("SAVDOOS_INDEX_GUARD_TTL", raising=False)
    else:
        monkeypatch.setenv("SAVDOOS_INDEX_GUARD_TTL", xom)
    assert ig._env_ttl() == kutilgan, label


@pytest.mark.parametrize("xom", [
    "abc", "-1", "0", "0.5", "999999999999", "inf", "nan", "1e400", "", "   ", "301",
])
def test_TTL_HECH_QANDAY_env_qiymati_CHEGARADAN_oshira_olmaydi(monkeypatch, xom):
    """Fail-open qalqoni: eskirgan musbat javob oynasi QURILISH BO'YICHA cheklangan."""
    monkeypatch.setenv("SAVDOOS_INDEX_GUARD_TTL", xom)
    v = ig._env_ttl()
    assert ig._TTL_MIN <= v <= ig._TTL_MAX, f"{xom!r} -> {v} diapazondan chiqdi"


def test_TTL_yaroqsiz_env_bilan_MODULNI_QAYTA_YUKLASH_yiqilmaydi(monkeypatch):
    """`importlib.reload` — modul darajasidagi ifoda qaytadan bajariladi."""
    import importlib
    monkeypatch.setenv("SAVDOOS_INDEX_GUARD_TTL", "abc")
    try:
        importlib.reload(ig)
        assert ig._TTL_SECONDS == 10.0
    finally:
        monkeypatch.delenv("SAVDOOS_INDEX_GUARD_TTL", raising=False)
        importlib.reload(ig)
    assert ig._TTL_SECONDS == 10.0


def test_TTL_NOL_keshni_OCHIRADI_gard_esa_ishlaydi(monkeypatch):
    """`0` hujjatlashtirilgan «har yozuvda qayta tekshirish» sozlamasi.

    ⚠️  MUSBAT KESH SEMANTIKASI saqlanadi: TTL > 0 da ikkinchi chaqiruv keshdan
        keladi (yuqoridagi `test_kesh_TTL_va_tuzatishdan_keyin_tiklanadi` buni qadaydi),
        TTL == 0 da esa HAR chaqiruv katalogga boradi.
    """
    calls = {"n": 0}

    def _state(bind, pairs):
        calls["n"] += 1
        return {pairs[0]: rs.IX_OK}

    monkeypatch.setattr(rs, "_unique_index_states", _state)
    monkeypatch.setattr(ig, "_TTL_SECONDS", 0.0)
    ig.reset_cache()
    b = _FakeBind()
    assert ig.index_healthy(b, "ux_x", "t") is True
    assert ig.index_healthy(b, "ux_x", "t") is True
    assert calls["n"] == 2, "TTL=0 da kesh o'chishi kerak edi"
    ig.reset_cache()


def test_TTL_default_ga_tushgach_gard_HANUZ_FAIL_CLOSED(monkeypatch):
    """TTL parse tuzatishi indeks tekshiruvini KUCHSIZLANTIRMASIN.

    ⚠️  Bu brifning 4-bandi: TTL sabab `require_index` fail-open bo'lib qolmasin.
    """
    monkeypatch.setenv("SAVDOOS_INDEX_GUARD_TTL", "abc")
    assert ig._env_ttl() == 10.0                      # default'ga tushdi
    for holat in (ig.BAD, ig.UNVERIFIABLE):
        monkeypatch.setattr(ig, "index_state", lambda *a, **k: holat)
        with pytest.raises(HTTPException) as ei:
            ig.require_index(_FakeBind(), "ux_x", "t", operation="sinov")
        assert ei.value.status_code == 409
        assert ig.SCHEMA_GUARANTEE_MISSING in str(ei.value.detail)


@pytest.mark.parametrize("xom", ["abc", "999999999999", "-1", "nan", "10,5"])
def test_SAFE03_YANGI_JARAYONDA_import_va_YOZUV_yoli_yiqilmaydi(xom):
    """HAL QILUVCHI REGRESSIYA — modul darajasidagi parse uchun.

    ⚠️  NEGA SUBPROCESS. Jarayon ichidagi `_env_ttl()` sinovlari modul darajasidagi
        `float(os.getenv(...))` ga QAYTISHNI ushlamaydi: `_env_ttl` baribir mavjud
        bo'lib qolardi va yashil chiqardi. SAFE-03 aynan IMPORT vaqtidagi nuqson,
        shuning uchun uni faqat YANGI jarayonda import qilib isbotlash mumkin.
    ⚠️  Qo'riqlangan yozuv yo'lining o'zi ham import qilinadi (`doc_seq`), chunki
        haqiqiy nuqson aynan shu lazy import orqali so'rov ichiga tushardi.
    """
    import os
    import subprocess
    import sys

    kod = (
        "import app.core.index_guard as g\n"
        "from app.core.index_guard import require_index\n"
        "import app.services.doc_seq as ds\n"
        "assert g._TTL_MIN <= g._TTL_SECONDS <= g._TTL_MAX, g._TTL_SECONDS\n"
        "print('TTL=' + repr(g._TTL_SECONDS))\n"
    )
    env = {**os.environ, "SAVDOOS_INDEX_GUARD_TTL": xom, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-c", kod],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, (
        f"SAVDOOS_INDEX_GUARD_TTL={xom!r} bilan import YIQILDI — har qo'riqlangan "
        f"yozuv 500 beradi:\n{(r.stderr or '')[-500:]}")
    assert "TTL=10.0" in r.stdout, r.stdout
