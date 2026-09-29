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
