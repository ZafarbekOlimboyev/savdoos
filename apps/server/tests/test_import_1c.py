# -*- coding: utf-8 -*-
"""1С -> SavdoOS konvertori: nom normallashtirish va ustun aniqlash testlari.

Barcha misollar — Fayzan do'konining HAQIQIY 1С eksportidan olingan satrlar
(`sena.xls`, `astatka.xls`, `Список9.xls`). Fayllarning o'zi repo'da yo'q va
CI'da bo'lmaydi, shu bois satrlar shu yerga KO'CHIRIB qo'yilgan — testlar
determinstik va tashqi fayllarsiz ishlaydi.

⚠️  SALBIY NAZORAT: har bir tuzatish uchun ESKI xatti-harakatni qayta tiklab,
    u AYNAN shu tekshiruvda YIQILISHINI isbotlaydigan test bor. Aks holda
    "test yashil" degani tuzatish ishlayotganini bildirmaydi — u shunchaki
    hech nimani o'lchamayotgan bo'lishi mumkin edi.
"""
import importlib.util
import pathlib
import re

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "tools" / "import_1c.py"
_spec = importlib.util.spec_from_file_location("import_1c", _SRC)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


# ── HAQIQIY 1С sarlavhalari ──────────────────────────────────────────────────
H_SENA = {0: "номенклатура, упаковка", 3: "розничная цена", 4: "цена поставщика"}
H_ASTATKA = {0: "номенклатура, ед. изм., упаковка", 3: "упак.", 4: "количество",
             5: "упак.", 6: "количество"}
H_SPISOK9 = {0: "владелец", 1: "упаковка", 2: "штрихкод", 3: "тип штрихкода"}

# ── HAQIQIY nom katakchalari (bir xil mahsulot, ikki fayl) ───────────────────
PAIRS = [
    # (sena katakchasi, astatka katakchasi, kutilgan nom, kutilgan birlik)
    (" 7Up 450ml, ", " 7Up 450ml, шт, ", "7Up 450ml", "шт"),
    (" LA KUBA MOXИТО 450мл, ", " LA KUBA MOXИТО 450мл, шт, ",
     "LA KUBA MOXИТО 450мл", "шт"),
    ("  ZINA Ср для посуды Яблоко л, ", "  ZINA Ср для посуды Яблоко л, шт, ",
     "ZINA Ср для посуды Яблоко л", "шт"),
    # nomning O'ZIDA «, » bor — faqat OXIRGI bo'lak birlik sifatida olinadi
    ("Прокладки Белла лекарс, травы 60 шт, ", "Прокладки Белла лекарс, травы 60 шт, шт, ",
     "Прокладки Белла лекарс, травы 60 шт", "шт"),
    # ichki qo'sh/uch probel SIQILADI — aks holda ko'zga bir xil ko'rinadigan dublikat
    ("Рамен   R1, R2, R3 90гр, ", "Рамен   R1, R2, R3 90гр, шт, ",
     "Рамен R1, R2, R3 90гр", "шт"),
    ("0441 Нутрилак Премиум №2  600г, ", "0441 Нутрилак Премиум №2  600г, шт, ",
     "0441 Нутрилак Премиум №2 600г", "шт"),
    ("MacTea 3 в 1, 18 гр, ", "MacTea 3 в 1, 18 гр, шт, ", "MacTea 3 в 1, 18 гр", "шт"),
    # tarozi tovari — birlik «кг»
    ("Аброй Докторская Варенные 576Код, ", "Аброй Докторская Варенные 576Код, кг, ",
     "Аброй Докторская Варенные 576Код", "кг"),
]

# 1С guruh/jami qatorlari — mahsulot EMAS
GROUP_CELLS = ["Магазин Файзан", "Итого", "Быстрые Тавары, , ", "Десерты, , "]


# ══ NOM NORMALLASHTIRISH ═════════════════════════════════════════════════════

@pytest.mark.parametrize("sena,astatka,name,unit", PAIRS)
def test_nom_ikkala_fayldan_bir_xil_chiqadi(sena, astatka, name, unit):
    """Asosiy talab: narx fayli va qoldiq fayli AYNI kalitni bersin."""
    n1, u1, _ = m.split_1c_name(sena, has_unit=False)
    n2, u2, _ = m.split_1c_name(astatka, has_unit=True)
    assert n1 == name
    assert n2 == name
    assert u1 is None          # sena birlik e'lon qilmaydi
    assert u2 == unit
    assert m.norm_key(n1) == m.norm_key(n2)


def test_ondan_keyingi_vergul_saqlanadi():
    """«0,125» — o'nlik vergul, ajratgich EMAS (undan keyin probel yo'q)."""
    n, u, _ = m.split_1c_name("0,125 up нектар Сок Минонс общ 0,125, ", has_unit=False)
    assert n == "0,125 up нектар Сок Минонс общ 0,125"
    assert u is None


def test_birlik_faqat_sarlavha_e_lon_qilganda_olinadi():
    """sena'da «…, шт» nomning O'ZI bo'lishi mumkin — uni kesib tashlamaymiz."""
    n, u, _ = m.split_1c_name("Салфетки 100 шт, ", has_unit=False)
    assert n == "Салфетки 100 шт"
    assert u is None


@pytest.mark.parametrize("cell", GROUP_CELLS)
def test_guruh_qatori_birlik_bermaydi(cell):
    """Guruh/jami qatorlari birlik maydonini to'ldirmaydi — shundan ajratiladi."""
    _, unit, _ = m.split_1c_name(cell, has_unit=True)
    assert unit is None


def test_haqiqiy_mahsulot_qatori_birlik_beradi():
    for _, astatka, _, unit in PAIRS:
        _, u, _ = m.split_1c_name(astatka, has_unit=True)
        assert u == unit


def test_sarlavha_tuzilishi():
    assert m.name_fields("Номенклатура, Ед. изм., Упаковка") == [
        "Номенклатура", "Ед. изм.", "Упаковка"]
    assert m.header_has_unit("Номенклатура, Ед. изм., Упаковка") is True
    assert m.header_has_unit("Номенклатура, Упаковка") is False
    assert m.header_has_unit("Владелец") is False


def test_norm_key_registr_va_probelga_befarq():
    assert m.norm_key("  7Up   450ML ") == m.norm_key("7up 450ml")


# ══ USTUN ANIQLASH ═══════════════════════════════════════════════════════════

def test_sena_kelish_va_sotish_narxi_TO_G_RI_ustunga_tushadi():
    """«Цена поставщика» = kelish, «Розничная цена» = sotish."""
    mp = m._map_columns(H_SENA, None)
    assert mp.get("buy") == 4, f"kelish narxi topilmadi: {mp}"
    assert mp.get("sell") == 3, f"sotish narxi noto'g'ri: {mp}"
    assert mp.get("name") == 0


def test_astatka_qoldiq_birinchi_miqdor_ustunidan():
    mp = m._map_columns(H_ASTATKA, None)
    assert mp.get("stock") == 4
    assert mp.get("name") == 0


def test_spisok9_barkod_va_nom():
    mp = m._map_columns(H_SPISOK9, None)
    assert mp.get("barcode") == 2
    assert mp.get("name") == 0


# ══ BARKOD QOIDASI (backend bilan bir xil) ═══════════════════════════════════

@pytest.mark.parametrize("raw,want", [
    ("4780032051640", "4780032051640"),      # EAN13
    ("2022000030229", "2022000030229"),
    ("  4600949010205 ", "4600949010205"),
    ("2022000015739333", None),              # 16 raqam — backend rad etadi
    ("12345", None),                         # 6 dan qisqa
    ("", None),
    (None, None),
    ("abc", None),
])
def test_barkod_6_14_raqam(raw, want):
    assert m._digits(raw) == want


# ══ ULASH O'QI VA BIRLASHTIRISH ══════════════════════════════════════════════

def test_ulash_o_qi_hamma_faylda_bor_maydonni_tanlaydi():
    sena = [{"name": "7Up 450ml", "sell": 70.0}]
    astatka = [{"name": "7Up 450ml", "stock": 18.0, "unit": "шт"}]
    s9 = [{"name": "7Up 450ml", "barcode": "4780032051640"}]
    # barkod faqat BITTA faylda bor -> o'q «name» bo'lishi SHART
    assert m._join_axis([sena, astatka, s9]) == "name"
    # barkod HAMMASIDA bo'lsa — aniqroq o'q
    assert m._join_axis([[{"barcode": "4780032051640"}], [{"barcode": "4780032051640"}]]) == "barcode"


def test_birlashtirish_narx_qoldiq_barkodni_bitta_yozuvga_yigadi():
    sena = [{"name": "7Up 450ml", "sell": 70.0, "buy": 45.5}]
    astatka = [{"name": "7Up 450ml", "stock": 18.0, "unit": "шт"}]
    s9 = [{"name": "7Up 450ml", "barcode": "4780032051640"},
          {"name": "7Up 450ml", "barcode": "4780032051657"}]
    out = m.merge([sena, astatka, s9], enrich_only={2})
    assert len(out) == 1
    r = out[0]
    assert (r["sell"], r["buy"], r["stock"], r["unit"]) == (70.0, 45.5, 18.0, "шт")
    assert sorted(r["barcodes"]) == ["4780032051640", "4780032051657"]


def test_boyituvchi_fayl_YANGI_mahsulot_yaratmaydi():
    """Список9'da 44 mingdan ortiq nom bor — ular katalogni belgilamaydi."""
    sena = [{"name": "7Up 450ml", "sell": 70.0}]
    s9 = [{"name": "7Up 450ml", "barcode": "4780032051640"},
          {"name": "Notanish tovar", "barcode": "4780032059999"}]
    out = m.merge([sena, s9], enrich_only={1})
    assert [r["name"] for r in out] == ["7Up 450ml"]


def test_asosiy_barkod_DETERMINISTIK():
    """Qayta yurgizilganda AYNI barkod asosiy bo'lishi shart."""
    rec = [{"name": "X", "sell": 1.0, "barcodes": ["4780032051657", "4780032051640"]}]
    a = m.to_import_rows(rec)[0]
    b = m.to_import_rows([{"name": "X", "sell": 1.0,
                           "barcodes": ["4780032051640", "4780032051657"]}])[0]
    assert a["barcode"] == b["barcode"] == "4780032051640"
    assert a["_extra_barcodes"] == ["4780032051657"]


# ══ SALBIY NAZORAT — ESKI xatti-harakat SHU testlarda YIQILADI ═══════════════

def _old_norm(s):
    """Tuzatishdan OLDINGI normallashtirish: faqat lower() + probel."""
    return re.sub(r"\s+", " ", str(s).strip().lower())


@pytest.mark.parametrize("sena,astatka,_n,_u", PAIRS)
def test_SALBIY_eski_normallashtirish_fayllarni_ULAY_OLMAYDI(sena, astatka, _n, _u):
    """ESKI kod narx va qoldiq faylini hech qachon ulay olmasdi.

    Aynan shu sabab 7832 o'rniga 14667 qator chiqardi: har bir mahsulot IKKI
    MARTA — biri narxsiz, biri qoldiqsiz. Kesishma NOLGA teng edi.
    """
    assert _old_norm(sena) != _old_norm(astatka), (
        "eski normallashtirish kutilmaganda ulandi — salbiy nazorat ma'nosiz")
    # yangi normallashtirish esa ulaydi
    assert m.norm_key(m.split_1c_name(sena, False)[0]) == \
           m.norm_key(m.split_1c_name(astatka, True)[0])


def test_SALBIY_eski_KEYS_kelish_narxini_TOPMAYDI():
    """«Цена поставщика» eski kalitlar ro'yxatida yo'q edi -> buy hech qachon topilmasdi."""
    old_buy = ["цена закупки", "закупочная цена", "закупочная", "себестоимость",
               "закупка", "приход", "kelish narxi", "оптовая", "оптовая цена"]
    assert not any(m._kw_in(kw, H_SENA[4]) for kw in old_buy), \
        "eski kalitlar kutilmaganda mos keldi — salbiy nazorat ma'nosiz"
    # yangi ro'yxat topadi
    assert any(m._kw_in(kw, H_SENA[4]) for kw in m.KEYS["buy"])


def test_SALBIY_eski_har_yozuvli_kalit_ulashni_BUZADI():
    """ESKI `_key` har yozuv uchun alohida o'q tanlardi -> barkod fayli ulanmasdi."""
    sena_rec = {"name": "7Up 450ml", "sell": 70.0}
    s9_rec = {"name": "7Up 450ml", "barcode": "4780032051640"}
    assert m._key(sena_rec, "auto") != m._key(s9_rec, "auto"), \
        "eski kalitlash kutilmaganda mos tushdi — salbiy nazorat ma'nosiz"
    # yagona o'q bilan ular MOS tushadi
    assert m._key(sena_rec, "name") == m._key(s9_rec, "name")


def test_SALBIY_strip_qilingan_katakcha_ajratilmaydi():
    """Katakchani AVVAL strip() qilish oxirgi «, » ajratgichni yo'q qiladi."""
    cell = " 7Up 450ml, шт, "
    assert m.split_1c_name(cell.strip(), has_unit=True)[0] != "7Up 450ml"
    assert m.split_1c_name(cell, has_unit=True)[0] == "7Up 450ml"


def test_ichki_probellar_siqiladi():
    """1С eksportida 532 nomda qo'sh probel bor — ular dublikat mahsulot yaratardi."""
    n, _, _ = m.split_1c_name("0458 Нутрилак Nutrilak Premium №3  с 12мес.  600g, ", has_unit=False)
    assert n == "0458 Нутрилак Nutrilak Premium №3 с 12мес. 600g"
    assert "  " not in n


def test_SALBIY_probel_siqilmasa_nom_bazadagidan_FARQ_qiladi():
    """Backend dublikatni AYNAN satr bo'yicha aniqlaydi — bitta ortiqcha probel yetarli."""
    xom = "0441 Нутрилак Премиум №2  600г, "
    bazadagi = "0441 Нутрилак Премиум №2 600г"
    assert xom.strip().rstrip(",").strip() != bazadagi, "salbiy nazorat ma'nosiz"
    assert m.split_1c_name(xom, has_unit=False)[0] == bazadagi
