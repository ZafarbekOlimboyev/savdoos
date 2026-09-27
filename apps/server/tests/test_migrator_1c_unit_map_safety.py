# -*- coding: utf-8 -*-
"""`--unit-map` ORQA ESHIGI — aniqlangan nuqson, qulflab qo'yilgan.

NIMA TOPILDI. Egasining qarori: massa birligini arifmetik yo'l bilan dona'ga aylantirish
TAQIQLANGAN, va `policies.unit_differs` doim `block`. Lekin operator jadvali shu qarorni
CHETLAB O'TA OLADI:

    --unit-map {"кг": "dona"}

`build_unit_table` (normalize.py:159-173) faqat kalit/qiymat bo'sh emasligini va normallashgan
kalitlar to'qnashmasligini tekshiradi. U qiymat ijarachining `units` jadvalida borligini ham,
MASSA birligi massa kodiga tushishini ham tekshirmaydi. Natijada:

  1. mahsulot `unit_code = "dona"` bo'lib qoladi — `UNIT_DIFFERS` UMUMAN chiqmaydi,
     ya'ni `block` siyosati ishga tushmaydi;
  2. `is_weighted` esa `unit_code == "kg"` dan kelib chiqadi (normalize.py:207), demak
     `False` bo'ladi — tarozi tovari donali bo'lib qoladi va POS etiketkani hech qachon o'qimaydi.

Ya'ni bitta operator jadvali ikkita darvozani birdan ochib yuboradi, hech qanday xato bermay.

NEGA BU YERDA TUZATILMAGAN. Tuzatish `migrator_1c` ning ishlash kodiga tegadi — bu discovery
collector doirasidan TASHQARIDA. Shu bois u ALOHIDA PREREQUISITE sifatida qaytarildi, test esa
nuqsonni qulflab turadi: tuzatilgan kuni bu test XPASS bo'ladi va `xfail` belgisi olinadi.

TAKLIF QILINGAN TUZATISH (yozilmagan): `build_unit_table` massa nomlarini massa BO'LMAGAN kodga
xaritalashni rad etsin, va har bir qiymat ma'lum BinOS birlik kodi ekanini tekshirsin.
"""
from __future__ import annotations

import pytest

from app.services.migrator_1c.normalize import build_unit_table, normalize_product
from tests.migrator_1c_helpers import g, prod
from tests.migrator_1c_synth import PT_RETAIL, WH_MAIN

SELECTION = {"warehouse_guids": [WH_MAIN], "retail_price_type_guid": PT_RETAIL,
             "purchase_price_type_guid": None}


def _kg_product():
    """Tarozi tovari: 1C birligi «кг», `is_weighted` kaliti berilmagan (shartnoma bo'yicha mumkin)."""
    return prod(g(1), "Сыр кг", unit="кг", okei="166", is_weighted=None)


def test_standart_jadvalda_kg_vaznli_boladi():
    """Nazorat: jadval buzilmagan bo'lsa, oqim to'g'ri ishlaydi."""
    np = normalize_product(0, _kg_product(), SELECTION, build_unit_table(None))
    assert np.unit_code == "kg"
    assert np.is_weighted is True


def test_unit_map_hozir_kgni_donaga_aylantiradi():
    """NUQSONNING O'ZI — hozirgi xulq shu, va u JIM.

    Bu test nuqsonni qulflaydi: tuzatilgach u yiqiladi va e'tiborni tortadi."""
    table = build_unit_table({"кг": "dona"})
    np = normalize_product(0, _kg_product(), SELECTION, table)
    assert np.unit_code == "dona"          # massa birligi dona bo'lib qoldi
    assert np.is_weighted is False         # va tarozi tovari donali bo'lib qoldi


@pytest.mark.xfail(reason="PREREQUISITE (collector doirasidan tashqarida): build_unit_table massa "
                          "birligini massa bo'lmagan kodga xaritalashni rad etmaydi",
                   strict=False)
def test_unit_map_massa_birligini_donaga_xaritalay_olmasligi_kerak():
    with pytest.raises(ValueError, match="massa"):
        build_unit_table({"кг": "dona"})


@pytest.mark.xfail(reason="PREREQUISITE (collector doirasidan tashqarida): build_unit_table "
                          "qiymat ma'lum BinOS birlik kodi ekanini tekshirmaydi",
                   strict=False)
def test_unit_map_notanish_binos_kodini_rad_etishi_kerak():
    with pytest.raises(ValueError, match="birlik kodi"):
        build_unit_table({"шт": "qanaqadir_yoq_birlik"})


def test_teskari_yonalish_ham_xavfli():
    """Dona'ni kg'ga xaritalash ham xuddi shunday jim: oddiy tovar tarozi tovari bo'lib qoladi."""
    table = build_unit_table({"шт": "kg"})
    np = normalize_product(0, prod(g(2), "Сок 1л", unit="шт", okei="796", is_weighted=None),
                           SELECTION, table)
    assert np.unit_code == "kg"
    assert np.is_weighted is True          # donali tovar tarozi tovariga aylandi
