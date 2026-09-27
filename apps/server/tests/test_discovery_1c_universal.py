# -*- coding: utf-8 -*-
"""Yadro UMUMIY bo'lib qolishining statik qo'riqchisi.

Egasining talabi: «Do NOT hardcode Fayzan/Розница 2.3 into the core» va
«Fayzan-specific assumptions remaining: MUST be zero in core».

Bu — niyat emas, TEKSHIRUV. Yadro manbasida konfiguratsiyaga yoki ijarachiga oid biror nom
paydo bo'lsa, shu test yiqiladi. Bilim faqat ikki joyda yashashi mumkin:
  · to'plam ICHIDA (ya'ni ma'lumot sifatida), yoki
  · ixtiyoriy adapterda (`adapters/`, yadrodan TASHQARIDA).
"""
from __future__ import annotations

import pathlib

import pytest

import app.services.discovery_1c as pkg

CORE_DIR = pathlib.Path(pkg.__file__).parent

#: Yadroda uchramasligi KERAK bo'lgan tokenlar.
#
#: CHEGARA QAYERDA: 1C PLATFORMASINING tushunchalari (Справочник, РегистрСведений,
#: ПланВидовХарактеристик, Измерение, Ресурс …) RUXSAT ETILADI — yadroning butun vazifasi
#: aynan shularni modellashtirish va ular har qanday konfiguratsiyada bir xil. Taqiqlanadigani —
#: AMALIY nomlar: muayyan konfiguratsiyada yaratilgan katalog/registr nomlari, mahsulot nomi,
#: ijarachi nomi, mamlakat/valyuta taxminlari.
FORBIDDEN = (
    # ijarachi / do'kon
    "fayzan", "файзан", "faizan",
    # konfiguratsiya oilalari va versiyalari
    "розница", "roznitsa", "управление торговлей", "1с:erp", "1c:erp", "унф", "2.3.5.38",
    # amaliy metadata nomlari — yadro bularni BILMASLIGI kerak
    "номенклатура", "штрихкод", "склад", "виды цен", "весовой", "серии",
    "подключаемого оборудования", "подключаемое оборудование",
    # mamlakat / valyuta taxminlari
    "кыргыз", "сом", "bishkek",
)


def core_files() -> list[pathlib.Path]:
    return sorted(p for p in CORE_DIR.rglob("*.py") if "adapters" not in p.parts)


def test_yadroda_fayl_bor():
    names = {p.name for p in core_files()}
    assert {"__init__.py", "schema.py", "bundle.py", "redact.py"} <= names


@pytest.mark.parametrize("path", core_files(), ids=lambda p: p.name)
def test_yadroda_konfiguratsiyaga_oid_nom_yoq(path: pathlib.Path):
    text = path.read_text(encoding="utf-8").lower()
    hits = sorted({tok for tok in FORBIDDEN if tok in text})
    assert not hits, (
        f"{path.name} da konfiguratsiyaga/ijarachiga oid token(lar): {hits}. "
        "Yadro umumiy bo'lib qolishi kerak — bu bilim to'plam ichida yoki adapterda yashaydi."
    )


def test_nishonlar_binos_tomonida_nomlangan():
    """Nishonlar BIZNING shartnomamiz nomlari bo'lishi kerak, 1C nomlari emas."""
    from app.services.discovery_1c.schema import TARGETS
    for t in TARGETS:
        assert t.isascii(), f"nishon nomi ASCII bo'lishi kerak: {t!r}"
        assert t.replace(".", "").replace("_", "").isalnum(), f"nishon nomi g'alati: {t!r}"


def test_sxema_mahsulot_maydonlarini_qamraydi():
    """`binos-1c-v1` ning 15 mahsulot maydoni + 4 tuzilma bloki qamralgan bo'lsin."""
    from app.services.discovery_1c.schema import BUNDLE_TARGETS
    from app.services.migrator_1c.bundle import PRODUCT_KEYS
    covered = {t.split(".", 1)[1] for t in BUNDLE_TARGETS if t.startswith("products.")}
    assert PRODUCT_KEYS == covered, (
        "discovery nishonlari `binos-1c-v1` mahsulot maydonlari bilan bir xil bo'lishi kerak; "
        f"faqat bundle'da: {sorted(PRODUCT_KEYS - covered)}; faqat discovery'da: {sorted(covered - PRODUCT_KEYS)}"
    )


def test_yadro_1c_ga_ulanmaydi():
    """Yadroda tarmoq/COM/jarayon chaqiruvi bo'lmasligi kerak — u faqat faylni o'qiydi."""
    banned = ("socket", "requests", "urllib", "http.client", "subprocess", "win32com",
              "pythoncom", "ctypes", "comtypes", "psycopg", "sqlalchemy")
    for path in core_files():
        text = path.read_text(encoding="utf-8")
        for tok in banned:
            assert f"import {tok}" not in text and f"from {tok}" not in text, \
                f"{path.name}: yadro {tok!r} ni ishlatmasligi kerak"
