# -*- coding: utf-8 -*-
"""`binos-1c-metadata-v1` validatori va NORMALLASHTIRILGAN GRAF testlari.

Bu fayl ikki narsani sinaydi va ikkisini ATAYLAB SINAMAYDI:

SINAYDI:
  · inventarizatsiya hujjatining QAT'IY validatsiyasi (oq ro'yxat, sanoq-matn, takror nom,
    sir shubhasi) — ya'ni buzuq kirish «tayyor tuzilma» bo'lib o'tib ketmasligini;
  · hujjatdan qurilgan grafning shakli va DETERMINIZMI — obyekt, maydon, qirra, `path`,
    aniqlanmagan havolalarning saqlanishi.

SINAMAYDI (va isbotlay olmaydi):
  · fikstura ichidagi nomlarning ma'nosini. Graf TALQIN QILMAYDI, shu bois bu yerda
    «bu maydon mahsulot kodi» degan tasdiq YO'Q va bo'lishi ham mumkin emas;
  · haqiqiy 1C konfiguratsiyasida yig'uvchi ishlashini — fiksturalar TO'QIMA
    (`discovery_1c_metadata_synth` ning bosh izohiga qarang).

⚠️ Graf qurilishi TASDIQ EMAS: obyekt grafda turgani uning mazmuni to'g'ri yoki ko'chirishga
   yaroqli ekanini ISBOTLAMAYDI. Shuning uchun quyida birorta joyda `VERIFIED` yoki
   `HUMAN_CONFIRMED` kutilmaydi — bu kanalda ular umuman yo'q.
"""
from __future__ import annotations

import dataclasses
import pathlib

import pytest

from app.services.discovery_1c import graph as graph_mod
from app.services.discovery_1c.graph import (PATH_SEP, RELATIONSHIP_TYPES, Relationship,
                                             build_graph, graph_stats)
from app.services.discovery_1c.metadata import (METADATA_VERSION, MetadataError,
                                                dump_metadata, unresolved_references,
                                                validate_metadata)
# ⚠️ Zond qatlami SHU FAYLDA sinaladi, chunki bu yerdagi nuqson BITTA: graf manzili
#    (`<obyekt>.<nom>`) ikki qatlamda ham tekshirilmasdi. Ikki qatlamni yonma-yon sinash
#    «qaysi biri to'xtatdi» degan savolni ochiq qoldirmaydi.
from app.services.discovery_1c.probe import (ProbeError, ProbeRequest, assert_no_raw_code,
                                             split_field_target, validate_probe)
from tests.discovery_1c_metadata_synth import (ALL_CONFIGS, CONFIG_SECRET_LEAK,
                                               SECRET_LEAK_EXPECTED, config, doc, field, obj,
                                               section, tabular)


def _rad(doc_: dict) -> str:
    """Hujjat RAD ETILISHINI talab qiladi va xato matnini qaytaradi.

    ⚠️ Xato MATNI shartnoma emas — testlar faqat RAD ETILISHINI va matnda kalit so'z
    borligini qaraydi. Matnni aynan qulflab qo'ysak, izoh tahriri testni yiqitardi."""
    with pytest.raises(MetadataError) as e:
        build_graph(doc_)
    return str(e.value)


# ══════════════════════════════════════════════════════════════════════════════════════════
# TO'G'RI HUJJAT
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_togri_hujjat_validatsiyadan_otadi():
    """Eng qulay fikstura (A) tekshiruvdan o'tadi va aniqlanmagan havola bermaydi."""
    d = config("A")
    assert validate_metadata(d) == ()
    assert d["metadata_version"] == METADATA_VERSION


def test_build_graph_obyekt_maydon_munosabat_quradi():
    """Graf hujjatda AYTILGAN narsani qirralarga aylantiradi — bir bayt qo'shmaydi."""
    g = build_graph(config("G"))

    assert [o.full_name for o in g.objects] == [
        "Catalog.X17", "Catalog.X23", "InformationRegister.ABCD", "RegisterAccumulation.R41"]

    x17 = g.by_full_name("Catalog.X17")
    assert x17 is not None
    assert x17.object_kind == "catalog"
    assert [f.name for f in x17.fields] == ["F1", "F2", "F3"]
    # ⚠️ `hierarchical="false"` = «qaradi va yo'q», `None` = «qaramadi». Ikkisi bir xil emas.
    assert x17.hierarchical is False

    abcd = g.by_full_name("InformationRegister.ABCD")
    assert [(f.name, f.kind) for f in abcd.fields] == [("D1", "dimension"), ("V1", "resource")]
    assert Relationship("InformationRegister.ABCD.D1", "D1",
                        "InformationRegister.ABCD", "dimension_of") in g.relationships
    assert Relationship("InformationRegister.ABCD.V1", "V1",
                        "InformationRegister.ABCD", "resource_of") in g.relationships

    # Qirra turlari shartnomadan chetga chiqmaydi.
    assert {r.relationship_type for r in g.relationships} <= set(RELATIONSHIP_TYPES)


def test_graph_stats_hamma_sanoq_matn():
    """Sanoqlar hujjatga tushadi, shu bois MATN bo'lishi SHART (1-invariant)."""
    st = graph_stats(build_graph(config("G")))
    assert st["objects"] == "4"
    assert st["relationships"] == str(len(build_graph(config("G")).relationships))
    for kalit, qiymat in st.items():
        if isinstance(qiymat, dict):
            assert list(qiymat) == sorted(qiymat), f"{kalit} tartiblanmagan"
            assert all(isinstance(v, str) for v in qiymat.values()), f"{kalit} da son bor"
        else:
            assert isinstance(qiymat, str), f"{kalit} MATN bo'lishi kerak"


# ══════════════════════════════════════════════════════════════════════════════════════════
# OQ RO'YXAT: NOMA'LUM VA TUSHIB QOLGAN KALIT
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_nomalum_kalit_rad_etiladi():
    d = config("A")
    d["objects"][0]["yangi_maydon"] = "nimadir"
    assert "noma'lum kalit" in _rad(d)


def test_hujjat_darajasidagi_nomalum_kalit_rad_etiladi():
    d = config("A")
    d["ai_xulosasi"] = {"product": "Справочник.Товары"}
    assert "noma'lum kalit" in _rad(d)


@pytest.mark.parametrize("kalit", ["synonym", "row_count", "errors", "tabular_sections",
                                   "register_kind", "predefined"])
def test_tushib_qolgan_kalit_rad_etiladi(kalit: str):
    """Tushib qolgan kalit ham RAD: «yozilmadi» va «yo'q» bir xil narsa emas."""
    d = config("A")
    del d["objects"][0][kalit]
    assert "tushib qolgan" in _rad(d)


def test_maydondagi_tushib_qolgan_kalit_rad_etiladi():
    d = config("A")
    del d["objects"][0]["attributes"][0]["string_length"]
    assert "tushib qolgan" in _rad(d)


@pytest.mark.parametrize("notogri_kind", ["Справочник", "catalogue", "CATALOG", "", "table"])
def test_nomalum_kind_rad_etiladi(notogri_kind: str):
    d = config("A")
    d["objects"][0]["kind"] = notogri_kind
    assert "kind noma'lum" in _rad(d)


def test_maydondagi_nomalum_kind_rad_etiladi():
    d = config("A")
    d["objects"][0]["attributes"][0]["kind"] = "rekvizit"
    assert "kind noma'lum" in _rad(d)


# ══════════════════════════════════════════════════════════════════════════════════════════
# SANOQLAR: JSON SONI TAQIQLANGAN, ONLIK NOL SAQLANADI
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("son", [7137, 0, 7137.0, True])
def test_sanoq_json_soni_bolsa_rad(son):
    """`row_count: 7137` — RAD. Sabab: `0000123` soni `123` bo'lib qoladi, PLU yo'qoladi."""
    d = config("A")
    d["objects"][0]["row_count"] = son
    xato = _rad(d)
    assert "JSON SONI" in xato or "JSON soni" in xato


def test_maydon_aniqligi_json_soni_bolsa_rad():
    d = config("A")
    d["objects"][0]["attributes"][0]["string_length"] = 11
    assert "JSON SONI" in _rad(d)


def test_onlik_nol_saqlanadi():
    """«00537» graf ichida AYNAN shu ko'rinishda qoladi — matn sifatida."""
    d = config("A")
    d["objects"][0]["row_count"] = "00537"
    g = build_graph(d)
    saqlangan = g.by_full_name("Справочник.Товары").row_count
    assert saqlangan == "00537"
    assert graph_stats(g)["objects"] == "6"
    # ⚠️ Son bo'lib ketganini bilvosita ham tekshiramiz: `int` ga aylansa bosh nol yo'qoladi.
    assert isinstance(saqlangan, str) and saqlangan.startswith("00")


def test_sanoq_matni_raqamdan_boshqa_narsa_bolsa_rad():
    d = config("A")
    d["objects"][0]["row_count"] = "4 021"
    assert "MATN" in _rad(d)


# ══════════════════════════════════════════════════════════════════════════════════════════
# TAKRORLANGAN NOMLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_full_name_takrorlanishi_rad():
    d = config("A")
    d["objects"].append(dict(d["objects"][0]))
    assert "full_name takrorlangan" in _rad(d)


def test_maydon_nomi_takrorlanishi_rad():
    """Rekvizit va o'lchov bitta manzil maydonini bo'lishadi — takror manzil ikkilanadi."""
    d = doc([obj("InformationRegister.ABCD", "information_register", "ABCD",
                 register_kind="unknown",
                 dimensions=[field("D1", "dimension", "CatalogRef.X17", refs=[])],
                 resources=[field("D1", "resource", "String(13)", length="13")])])
    assert "maydon nomi takrorlangan" in _rad(d)


def test_maydon_va_jadval_bolimi_bir_xil_nomli_bolsa_rad():
    """⚠️ NUQSON TESTI: maydon va jadval bo'limi grafda BIR XIL manzilga ega bo'lardi.

    Ikkalasi ham `<obyekt>.<nom>` shaklida manzillanadi. Ilgari maydonlar o'zaro va
    bo'limlar o'zaro tekshirilardi, o'zaro KESISHUV esa tekshirilmasdi."""
    d = doc([obj("Справочник.X", "catalog", "X",
                 attributes=[field("T1", "attribute", "Строка(9)", length="9")],
                 tabular_sections=[tabular("T1", [field("F1", "attribute", "Строка(9)",
                                                        length="9")])])])
    assert "manzil takrorlangan" in _rad(d)


def test_maydon_va_sanab_otilgan_qiymat_bir_xil_nomli_bolsa_rad():
    """⚠️ NUQSON TESTI: `enum_of` manzili ham shu maydonda yashaydi."""
    d = doc([obj("Перечисление.Z", "enum", "Z",
                 attributes=[field("V1", "attribute", "Строка(9)", length="9")],
                 enum_values=["V1"])])
    assert "manzil takrorlangan" in _rad(d)


def test_sanab_otilgan_qiymatda_nuqta_bolsa_rad():
    """⚠️ NUQSON TESTI: nuqtali qiymat manzilni ikki xil o'qishga imkon berardi.

    `Перечисление.Z` + qiymat `A.B` → `Перечисление.Z.A.B`, bu esa
    `<obyekt>.<bo'lim>.<maydon>` dan farq qilmay qolardi."""
    d = doc([obj("Перечисление.Z", "enum", "Z", enum_values=["A.B"])])
    assert "nuqta" in _rad(d)


def test_havola_nishonida_nuqta_ruxsat_etiladi():
    """⚠️ Qarshi tekshiruv: `reference_targets` da obyektning TO'LIQ nomi turadi (nuqta bilan),
    ya'ni identifikator cheklovi u yerga TARQALMASLIGI kerak."""
    g = build_graph(config("A"))
    birliklar = g.references_from("Справочник.Товары")
    assert [r.target for r in birliklar] == ["Справочник.ЕдиницыИзмерения"]


def test_jadval_bolimi_nomi_takrorlanishi_rad():
    d = doc([obj("Документ.D", "document", "D",
                 tabular_sections=[tabular("S1", [field("F1", "attribute", "Строка(9)",
                                                        length="9")]),
                                   tabular("S1", [field("F2", "attribute", "Строка(9)",
                                                        length="9")])])])
    xato = _rad(d)
    assert "takrorlangan" in xato


# ══════════════════════════════════════════════════════════════════════════════════════════
# HAVOLALAR: MAVJUD VA ANIQLANMAGAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_mavjud_obyektga_havola_qirra_beradi():
    g = build_graph(config("G"))
    assert Relationship("RegisterAccumulation.R41", "D1", "Catalog.X17",
                        "references") in g.relationships
    assert g.unresolved_references == ()


def test_aniqlanmagan_havola_jimgina_yoqolmaydi():
    """⚠️ Hujjatda YO'Q obyektga havola — XATO EMAS, lekin JIMGINA O'CHIRILMAYDI.

    U `unresolved_references` da ham, QIRRA sifatida ham qoladi: bog'lanish rostdan bor,
    faqat nishon obyekt hujjatga tushmagan (konfiguratsiya bo'lak-bo'lak olinishi mumkin)."""
    d = config("G")
    d["objects"][3]["dimensions"].append(
        field("D3", "dimension", "CatalogRef.QQQ", refs=["Catalog.QQQ"]))
    g = build_graph(d)

    assert g.unresolved_references == ("Catalog.QQQ",)
    assert g.by_full_name("Catalog.QQQ") is None, "aniqlanmagan nishon obyekt bo'lib qolmaydi"
    assert Relationship("RegisterAccumulation.R41", "D3", "Catalog.QQQ",
                        "references") in g.relationships
    assert g.referencing("Catalog.QQQ") != (), "havola qirra sifatida ham qolishi SHART"
    # Validator ham xuddi shu javobni beradi (hujjat O'ZGARTIRILMAYDI).
    assert validate_metadata(d) == ("Catalog.QQQ",)
    assert unresolved_references(d) == ("Catalog.QQQ",)


def test_aniqlanmagan_havolalar_tartiblangan_va_takrorsiz():
    d = config("G")
    d["objects"][3]["dimensions"].append(
        field("D3", "dimension", "CatalogRef.ZZZ", refs=["Catalog.ZZZ", "Catalog.AAA"]))
    d["objects"][2]["dimensions"].append(
        field("D2", "dimension", "CatalogRef.ZZZ", refs=["Catalog.ZZZ"]))
    g = build_graph(d)
    assert g.unresolved_references == ("Catalog.AAA", "Catalog.ZZZ")


def test_referencing_va_references_from():
    """Fikstura G: `R41` va `ABCD` ikkisi ham `X17` ga havola qiladi."""
    g = build_graph(config("G"))

    kimlar = g.referencing("Catalog.X17")
    assert [(r.source, r.source_field) for r in kimlar] == [
        ("InformationRegister.ABCD", "D1"), ("RegisterAccumulation.R41", "D1")]
    assert all(r.relationship_type == "references" for r in kimlar)

    kimga = g.references_from("RegisterAccumulation.R41")
    assert [(r.target, r.source_field) for r in kimga] == [
        ("Catalog.X17", "D1"), ("Catalog.X23", "D2")]

    # X23 ga faqat R41 havola qiladi; X17 hech kimga havola qilmaydi.
    assert [r.source for r in g.referencing("Catalog.X23")] == ["RegisterAccumulation.R41"]
    assert g.references_from("Catalog.X17") == ()
    # ⚠️ `references` dan boshqa qirra bu ikki funksiyaga TUSHMAYDI.
    assert all(r.relationship_type == "references"
               for r in kimlar + kimga + g.referencing("Catalog.X23"))


def test_nomalum_obyekt_turi_xato_beradi():
    """Imlo xatosi JIMGINA bo'sh ro'yxat bermasin: bo'sh javob «bu turda yo'q» degani."""
    g = build_graph(config("A"))
    with pytest.raises(MetadataError):
        g.objects_of_kind("catalogue")
    assert len(g.objects_of_kind("catalog")) == 3


# ══════════════════════════════════════════════════════════════════════════════════════════
# JADVAL BO'LIMLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_jadval_bolimi_maydonlari_path_bilan_tushadi():
    """Bo'lim maydoni obyekt maydonlari ichida, lekin `path` bilan ajratilgan holda turadi."""
    d = doc([obj("Справочник.X", "catalog", "X",
                 attributes=[field("A1", "attribute", "Строка(9)", length="9")],
                 tabular_sections=[tabular("S1", [field("F1", "attribute", "Строка(9)",
                                                        length="9"),
                                                  field("F2", "attribute", "Булево")])])])
    g = build_graph(d)
    x = g.by_full_name("Справочник.X")

    assert [f.path for f in x.fields] == ["A1", "S1.F1", "S1.F2"]
    assert x.tabular_section_names == ("S1",)
    assert [f.address for f in x.fields] == [
        "Справочник.X.A1", "Справочник.X.S1.F1", "Справочник.X.S1.F2"]
    # `tabular_section` faqat bo'lim maydonlarida to'ladi.
    assert [f.tabular_section for f in x.fields] == [None, "S1", "S1"]
    assert g.fields_of("Справочник.X") == x.fields

    # Bo'lim maydonining EGASI — bo'lim, obyektning o'zi emas.
    assert Relationship("Справочник.X.S1.F1", "S1.F1", "Справочник.X.S1",
                        "attribute_of") in g.relationships
    assert Relationship("Справочник.X.S1", None, "Справочник.X",
                        "tabular_section_of") in g.relationships


def test_jadval_bolimidagi_havola_obyekt_darajasida_qirra_beradi():
    """Bo'limdagi havola ham obyektdan chiqadi, `source_field` esa BO'LIM yo'li bilan keladi."""
    g = build_graph(config("A"))
    hujjat = [r for r in g.references_from("Справочник.Товары")]
    assert all(PATH_SEP not in (r.source_field or "") for r in hujjat)

    d = doc([obj("Справочник.X", "catalog", "X",
                 attributes=[field("A1", "attribute", "Строка(9)", length="9")],
                 tabular_sections=[tabular("S1", [field("F1", "attribute",
                                                        "СправочникСсылка.X",
                                                        refs=["Справочник.X"])])])])
    g2 = build_graph(d)
    assert Relationship("Справочник.X", "S1.F1", "Справочник.X",
                        "references") in g2.relationships


def test_bolim_maydonlari_egasi_bolim_ichida_takrorlanmaydi():
    d = doc([obj("Справочник.X", "catalog", "X",
                 tabular_sections=[tabular("S1", [field("F1", "attribute", "Булево"),
                                                  field("F1", "attribute", "Булево")])])])
    assert "maydon nomi takrorlangan" in _rad(d)


def test_bir_xil_maydon_nomi_ikki_bolimda_ruxsat():
    """⚠️ Bu takror EMAS: manzil bo'lim nomi bilan ajraladi (`S1.F1` ≠ `S2.F1`)."""
    d = doc([obj("Справочник.X", "catalog", "X",
                 tabular_sections=[tabular("S1", [field("F1", "attribute", "Булево")]),
                                   tabular("S2", [field("F1", "attribute", "Булево")])])])
    g = build_graph(d)
    assert [f.path for f in g.by_full_name("Справочник.X").fields] == ["S1.F1", "S2.F1"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# DETERMINIZM
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("letter", sorted(ALL_CONFIGS))
def test_determinizm_bir_xil_hujjat_bir_xil_graf(letter: str):
    """Bir xil kirish — AYNAN bir xil graf: tuple'lar tartibi ham bir xil."""
    birinchi = build_graph(config(letter))
    ikkinchi = build_graph(config(letter))
    assert birinchi == ikkinchi
    assert birinchi.objects == ikkinchi.objects
    assert birinchi.relationships == ikkinchi.relationships
    assert birinchi.unresolved_references == ikkinchi.unresolved_references
    assert graph_stats(birinchi) == graph_stats(ikkinchi)
    # Hujjat yozilishi ham baytiga teng bo'lishi kerak.
    assert dump_metadata(config(letter)) == dump_metadata(config(letter))


@pytest.mark.parametrize("letter", sorted(ALL_CONFIGS))
def test_graf_tartibi_shartnoma(letter: str):
    """Obyektlar `full_name`, maydonlar `path`, qirralar to'liq kalit bo'yicha tartiblangan."""
    g = build_graph(config(letter))
    nomlar = [o.full_name for o in g.objects]
    assert nomlar == sorted(nomlar)
    for o in g.objects:
        yollar = [f.path for f in o.fields]
        assert yollar == sorted(yollar), f"{o.full_name}: maydonlar tartiblanmagan"
        assert list(o.tabular_section_names) == sorted(o.tabular_section_names)
        assert list(o.enum_values) == sorted(o.enum_values)
        assert list(o.predefined) == sorted(o.predefined)
        for f in o.fields:
            assert list(f.reference_targets) == sorted(set(f.reference_targets))
    kalitlar = [r.sort_key for r in g.relationships]
    assert kalitlar == sorted(kalitlar)
    assert len(set(g.relationships)) == len(g.relationships), "takroriy qirra qolgan"


def test_obyektlar_tartibi_kirish_tartibiga_bogliq_emas():
    """Hujjatdagi obyekt tartibi o'zgarsa ham graf AYNAN bir xil bo'lib qoladi."""
    tog_ri = build_graph(config("G"))
    teskari = config("G")
    teskari["objects"].reverse()
    assert build_graph(teskari) == tog_ri


def test_havola_nishonlari_tartiblanadi():
    """⚠️ Hujjatdagi tartib platformaning tip tavsifi tartibi — MA'NO TASHIMAYDI, shu bois
    graf nishonlarni tartiblaydi. Takror esa validatorda RAD etiladi (grafgacha yetmaydi)."""
    d = config("G")
    d["objects"][3]["dimensions"][0]["reference_targets"] = ["Catalog.X23", "Catalog.X17"]
    g = build_graph(d)
    maydon = [f for f in g.by_full_name("RegisterAccumulation.R41").fields if f.name == "D1"][0]
    assert maydon.reference_targets == ("Catalog.X17", "Catalog.X23")

    takror = config("G")
    takror["objects"][3]["dimensions"][0]["reference_targets"] = ["Catalog.X17", "Catalog.X17"]
    assert "takrorlangan" in _rad(takror)


# ══════════════════════════════════════════════════════════════════════════════════════════
# GRAFDA TALQIN YO'Q — STATIK QO'RIQCHI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_graf_manbasida_konsept_nomi_yoq():
    """⚠️ GRAFDA TALQIN YO'Q. Graf «nima bor» ni tasvirlaydi, «nima ma'nosi» ni EMAS.

    Shu bois `graph.py` manbasida `ai.CONCEPTS` ning birorta nomi (`product`, `barcode` …)
    UCHRAMASLIGI kerak: konsept nomi paydo bo'lishi — talqin grafga sizib kirgani."""
    from app.services.discovery_1c.ai import CONCEPTS

    manba = pathlib.Path(graph_mod.__file__).read_text(encoding="utf-8").lower()
    topilgan = sorted({c for c in CONCEPTS if c in manba})
    assert not topilgan, (
        f"graph.py da konsept nomi(lari): {topilgan}. Graf talqin qilmaydi — ma'no berish "
        "tahlil qatlamining ishi (`ai.py`, `analyst/`)."
    )


def test_graf_ai_qatlamini_import_qilmaydi():
    """Yo'nalish bir tomonlama: tahlil grafga tayanadi, graf tahlilga TAYANMAYDI."""
    manba = pathlib.Path(graph_mod.__file__).read_text(encoding="utf-8")
    for taqiq in ("CONCEPTS", "from .ai", "from .analyst", "import ai", "Hypothesis",
                  "CANDIDATE", "AMBIGUOUS", "HUMAN_CONFIRMED", "VERIFIED"):
        assert taqiq not in manba, f"graph.py da {taqiq!r} bo'lmasligi kerak"


def test_grafda_nishon_va_ishonch_maydoni_yoq():
    """Graf tugunlarida na nishon, na ishonch darajasi, na xarita bo'lishi kerak."""
    g = build_graph(config("A"))
    # ⚠️ `Relationship.target` bu ro'yxatda YO'Q: u qirraning ikkinchi uchi, ya'ni
    #    hujjatda AYTILGAN bog'lanish. Taqiqlangani — TALQIN maydonlari.
    taqiqlangan = {"target_concept", "concept", "confidence", "status", "mapping",
                   "evidence", "score", "hypothesis", "decision"}
    for tugun in (g.objects[0], g.objects[0].fields[0], g.relationships[0]):
        maydonlar = set(vars(tugun))
        assert not (maydonlar & taqiqlangan), (
            f"{type(tugun).__name__} da talqin maydoni: {sorted(maydonlar & taqiqlangan)}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# SIR — FAIL-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_sir_topilgan_hujjat_rad_etiladi():
    """⚠️ Obyekt IZOHIGA tushgan ulanish satri ham tutiladi: sir faqat «sir maydonlarida»
    turmaydi. Yolg'on ijobiy — bir marta qo'lda ko'rish; yolg'on salbiy — mijozning paroli
    hujjat bilan birga tarqaydi."""
    assert SECRET_LEAK_EXPECTED["xulq"] == "RAD_ETILADI"
    xato = _rad(CONFIG_SECRET_LEAK)
    assert "sir shubhasi" in xato
    # ⚠️ Xato matnida sir qiymatining O'ZI chiqmasligi kerak.
    assert "sinovchi" not in xato and "sinov-srv" not in xato


@pytest.mark.parametrize("matn", [
    "parol: 12345",
    "пароль — 12345",
    "kassir@dokon.uz",
    "+998 90 123 45 67",
    "File=D:\\bazalar\\savdo;Usr=admin",
])
def test_izohdagi_sir_shakli_rad_etiladi(matn: str):
    """Sir hujjatning HAR JOYIDA tutiladi — izoh, sinonim, `notes` farq qilmaydi."""
    d = config("A")
    d["notes"].append(matn)
    assert "sir shubhasi" in _rad(d)


def test_sir_obyekt_izohida_ham_tutiladi():
    """⚠️ Sir kalit NOMI bilan emas, QIYMAT shakli bilan tutiladi: hujjatning hamma kaliti
    oq ro'yxatda, ya'ni `password` degan kalit bu hujjatda umuman paydo bo'la olmaydi.
    Shu bois himoya butunlay qiymat naqshlariga tayanadi."""
    d = config("A")
    d["objects"][2]["comment"] = r"eski baza: File=D:\arxiv\savdo.1CD;Usr=admin"
    assert "sir shubhasi" in _rad(d)


# ══════════════════════════════════════════════════════════════════════════════════════════
# BO'SH `objects` — HA; BO'SH `sections` — YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_bosh_objects_qabul_qilinadi():
    """⚠️ Bo'sh `objects` — HAQIQIY javob (yig'uvchi hamma bo'limda yiqilgan bo'lishi mumkin).
    Bo'limlar buni SABABI bilan ko'rsatadi."""
    d = doc([], sections=[section("catalogs", "failed", "ruxsat yo'q"),
                          section("counts", "skipped", "vaqt tugadi")])
    g = build_graph(d)
    assert g.objects == () and g.relationships == () and g.unresolved_references == ()
    assert graph_stats(g)["objects"] == "0"


def test_bosh_sections_rad_etiladi():
    """Bo'sh bo'lim ro'yxati «hech narsa qaralmadi» degani — yig'uvchi nimani urinib
    ko'rganini AYTISHI shart."""
    d = doc([], sections=[])
    assert "bo'sh bo'lmagan ro'yxat" in _rad(d)


def test_yiqilgan_bolim_sababsiz_qolmaydi():
    d = doc([], sections=[section("catalogs", "failed", None)])
    assert "sababsiz qolmaydi" in _rad(d)


def test_ok_bolimda_xato_bolmaydi():
    d = doc([], sections=[section("catalogs", "ok", "nimadir")])
    assert "`ok` bo'limda" in _rad(d)


def test_nomalum_bolim_holati_rad():
    d = doc([], sections=[section("catalogs", "OK", None)])
    assert "status noma'lum" in _rad(d)


# ══════════════════════════════════════════════════════════════════════════════════════════
# HAMMA 15 FIKSTURA
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_fikstura_soni_ontabeshta():
    assert sorted(ALL_CONFIGS) == list("ABCDEFGHIJKLMNO")


@pytest.mark.parametrize("letter", sorted(ALL_CONFIGS))
def test_hamma_fikstura_grafga_aylanadi(letter: str):
    """Har 15 fikstura validatsiyadan o'tadi va bo'sh bo'lmagan grafga aylanadi.

    ⚠️ Bu fikstura ichidagi nomlarning MA'NOSI to'g'ri ekanini ISBOTLAMAYDI — graf talqin
    qilmaydi, u faqat hujjatda aytilgan narsani normallashtiradi."""
    d = config(letter)
    aniqlanmagan = validate_metadata(d)
    g = build_graph(d)

    assert g.objects, f"{letter}: graf bo'sh"
    assert g.relationships, f"{letter}: qirra yo'q"
    assert g.unresolved_references == aniqlanmagan

    # Har bir obyekt o'zining maydonlariga egalik qiladi, manzillar esa noyob.
    manzillar: list[str] = []
    for o in g.objects:
        assert o.object_kind in graph_mod.SOURCE_KINDS
        for f in o.fields:
            assert f.parent_object == o.full_name
            assert f.address == f"{o.full_name}{PATH_SEP}{f.path}"
            manzillar.append(f.address)
        manzillar += [f"{o.full_name}{PATH_SEP}{s}" for s in o.tabular_section_names]
        manzillar += [f"{o.full_name}{PATH_SEP}{v}" for v in o.enum_values]
    assert len(set(manzillar)) == len(manzillar), f"{letter}: manzil takrorlangan"

    # Qirraning har bir uchi yoki grafdagi obyekt, yoki uning ichidagi manzil, yoki
    # ANIQLANMAGAN havola bo'lishi kerak — begona uch bo'lmaydi.
    mavjud = {o.full_name for o in g.objects} | set(manzillar) | set(aniqlanmagan)
    for r in g.relationships:
        assert r.relationship_type in RELATIONSHIP_TYPES
        assert r.source in mavjud, f"{letter}: begona `source` {r.source!r}"
        assert r.target in mavjud, f"{letter}: begona `target` {r.target!r}"


@pytest.mark.parametrize("letter", sorted(ALL_CONFIGS))
def test_hamma_fiksturada_hierarchical_uchulik(letter: str):
    """⚠️ `None` = «yig'uvchi qaramadi», `False` = «qaradi va yo'q». Graf ikkisini
    QO'SHIB YUBORMAYDI."""
    for o in build_graph(config(letter)).objects:
        assert o.hierarchical in (True, False, None)


# ══════════════════════════════════════════════════════════════════════════════════════════
# IDENTIFIKATOR BELGI TO'PLAMI — INYEKSIYA BIR QATLAM PASTDA
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ NUQSON: `full_name` uchun belgi-to'plami darvozasi bor edi, `_ident()` uchun YO'Q.
#: `_IDENT_RE` faqat `FULL_NAME_RE` ni yasash uchun ishlatilardi, `_ident()` ning O'ZI esa
#: (a) bo'sh emas, (b) ichida nuqta yo'q deb tekshirardi — ya'ni MAYDON nomi, JADVAL BO'LIMI
#: nomi va SANAB O'TILGAN QIYMAT qo'shtirnoq, qavs, vergul, probel, nuqtali vergul yoki
#: plyus bilan o'tib ketardi.
#: ⚠️ NEGA BU XAVFLI: uchovi ham grafda `<obyekt>.<nom>` manzili bo'ladi va shu manzil
#: `field_type_details` zondining `target_object` iga AYNAN shunday chiqadi — ya'ni nom
#: operator qo'lidagi 1C shablonidagi SATR LITERALIGA tushadi. Nom ichidagi qo'shtirnoq
#: literalni YOPIB, ortidan yozuvchi amal qo'shish yo'lini ochardi.
INYEKSIYA_BELGILARI = [
    ("qoshtirnoq", '"'),        # BSL satr literalini yopadi
    ("apostrof", "'"),          # SQL uslubidagi literalni yopadi
    ("ochuvchi_qavs", "("),     # amal chaqiruvini boshlaydi
    ("yopuvchi_qavs", ")"),     # chaqiruvni yopadi
    ("vergul", ","),            # argument ajratuvchisi
    ("probel", " "),            # operator va nom orasini ajratadi
    ("nuqtali_vergul", ";"),    # operator ajratuvchisi
    ("plyus", "+"),             # satr birlashtirish
    ("kvadrat_qavs", "["),      # indeks / shablon belgisi
]
INYEKSIYA_IDS = [nomi for nomi, _belgi in INYEKSIYA_BELGILARI]


def _buzuq_nom(belgi: str) -> str:
    """Qonuniy identifikatorga bitta hujum belgisini qistiradi."""
    return f"Tovar{belgi}Nomi"


@pytest.mark.parametrize("belgi", [b for _n, b in INYEKSIYA_BELGILARI], ids=INYEKSIYA_IDS)
def test_maydon_nomi_identifikator_belgi_toplamidan_chiqmaydi(belgi: str):
    """⚠️ NUQSON TESTI: maydon nomi `_IDENT_RE` ga solishtirilmasdi.

    Maydon nomi grafda `<obyekt>.<nom>` manzili bo'ladi va `field_type_details` zondining
    `target_object` iga shu ko'rinishda chiqadi — ya'ni u BAJARISH yo'lidagi qiymat."""
    d = doc([obj("Справочник.X", "catalog", "X",
                 attributes=[field(_buzuq_nom(belgi), "attribute", "Строка(9)", length="9")])])
    xato = _rad(d)
    assert "identifikatori" in xato.lower()
    assert "attributes[0].name" in xato


@pytest.mark.parametrize("belgi", [b for _n, b in INYEKSIYA_BELGILARI], ids=INYEKSIYA_IDS)
def test_jadval_bolimi_maydon_nomi_ham_tekshiriladi(belgi: str):
    """⚠️ Jadval bo'limi ichidagi maydon manzili IKKI bo'lakli (`<obyekt>.<bo'lim>.<maydon>`)
    va u ham AYNAN shu zond turiga nishon bo'ladi."""
    d = doc([obj("Документ.D", "document", "D",
                 tabular_sections=[tabular("S1", [field(_buzuq_nom(belgi), "attribute",
                                                        "Строка(9)", length="9")])])])
    xato = _rad(d)
    assert "identifikatori" in xato.lower()
    assert "tabular_sections[0].attributes[0].name" in xato


@pytest.mark.parametrize("belgi", [b for _n, b in INYEKSIYA_BELGILARI], ids=INYEKSIYA_IDS)
def test_jadval_bolimi_nomi_identifikator_belgi_toplamidan_chiqmaydi(belgi: str):
    """⚠️ Bo'lim nomi ham `<obyekt>.<nom>` manzilini egallaydi (`tabular_section_of` qirrasi)."""
    d = doc([obj("Документ.D", "document", "D",
                 tabular_sections=[tabular(_buzuq_nom(belgi),
                                           [field("F1", "attribute", "Строка(9)", length="9")])])])
    xato = _rad(d)
    assert "identifikatori" in xato.lower()
    assert "tabular_sections[0].name" in xato


@pytest.mark.parametrize("belgi", [b for _n, b in INYEKSIYA_BELGILARI], ids=INYEKSIYA_IDS)
def test_sanab_otilgan_qiymat_identifikator_belgi_toplamidan_chiqmaydi(belgi: str):
    """⚠️ `enum_values` a'zosi ham `<obyekt>.<qiymat>` manzili bo'ladi (`enum_of` qirrasi)."""
    d = doc([obj("Перечисление.Z", "enum", "Z", enum_values=[_buzuq_nom(belgi)])])
    xato = _rad(d)
    assert "identifikatori" in xato.lower()
    assert "enum_values[0]" in xato


@pytest.mark.parametrize("belgi", [b for _n, b in INYEKSIYA_BELGILARI], ids=INYEKSIYA_IDS)
def test_obyekt_nomi_ham_shu_darvozadan_otadi(belgi: str):
    """`name` — `full_name` ning oxirgi bo'lagi, ya'ni u ham identifikator bo'lishi SHART."""
    buzuq = _buzuq_nom(belgi)
    xato = _rad(doc([obj(f"Справочник.{buzuq}", "catalog", buzuq)]))
    assert "identifikatori" in xato.lower() or "full_name" in xato


# ── YOLG'ON IJOBIY QARSHI TEKSHIRUVI ─────────────────────────────────────────────────────
@pytest.mark.parametrize("nom", [
    "Номенклатура",        # kirill
    "ТоварыНаСкладах",     # kirill, uzun
    "X17",                 # lotin + raqam
    "R41",
    "Qoldiq_2",            # lotin + pastki chiziq + raqam
    "_Holat",              # pastki chiziq bilan boshlanadi
    "Коди",                # lokalizatsiya qilingan kirill
    "Nomi",
])
def test_haqiqiy_identifikatorlar_RAD_ETILMAYDI(nom: str):
    """⚠️ ASOSIY YOLG'ON-IJOBIY SINOVI: 1C identifikatorida kirill ham, lotin ham, raqam ham,
    pastki chiziq ham QONUNIY. Darvoza ularning birortasini yo'qotmasligi kerak."""
    d = doc([obj("Справочник.X", "catalog", "X",
                 attributes=[field(nom, "attribute", "Строка(9)", length="9")],
                 tabular_sections=[tabular(f"{nom}Sec",
                                           [field(f"{nom}2", "attribute", "Строка(9)",
                                                  length="9")])])])
    assert validate_metadata(d) == ()
    g = build_graph(d)
    assert [f.name for f in g.by_full_name("Справочник.X").fields] == [nom, f"{nom}2"]


def test_hamma_fikstura_identifikator_darvozasidan_otadi():
    """⚠️ 15 fikstura (A–O) qonuniy 1C nomlarini ishlatadi — darvoza ularni buzmaydi."""
    for letter in sorted(ALL_CONFIGS):
        assert validate_metadata(config(letter)) is not None, letter


# ══════════════════════════════════════════════════════════════════════════════════════════
# IKKINCHI QATLAM: ZOND NISHONI (`assert_no_raw_code`) — MANZIL REJIMI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ NEGA IKKI QATLAM. Inventarizatsiya darvozasi (yuqorida) HUJJAT orqali kelgan nomni
#: tutadi. Zond darvozasi esa grafni BOSHQA yo'l bilan qurgan kodni tutadi (adapter, kelajakdagi
#: ulagich, `dataclasses.replace`). Biri ikkinchisini almashtirmaydi.
#: ⚠️ Ilgari `assert_no_raw_code` FAQAT `;`, `{}` va so'rov/platforma kalit so'zlarini to'sardi —
#: qo'shtirnoq, qavs, vergul, plyus va kvadrat qavs O'TIB KETARDI. Aynan qo'shtirnoq esa BSL
#: satr literalini yopadigan belgi, ya'ni darvozaning eng muhim bo'lagi yo'q edi.
#: ⚠️ NUQTA BU RO'YXATDA YO'Q va bo'lishi ham mumkin emas: `target_object` ning QONUNIY shakli
#: `<obyekt>.<maydon>` (`<obyekt>.<bo'lim>.<maydon>` ham) — nuqtani to'sish zondni o'ldirardi.
ZOND_INYEKSIYA_BELGILARI = [
    ("qoshtirnoq", '"'),
    ("apostrof", "'"),
    ("ochuvchi_qavs", "("),
    ("yopuvchi_qavs", ")"),
    ("vergul", ","),
    ("probel", " "),
    ("nuqtali_vergul", ";"),
    ("plyus", "+"),
    ("ochuvchi_kvadrat_qavs", "["),
    ("yopuvchi_kvadrat_qavs", "]"),
    ("figurali_qavs", "{"),
]
ZOND_IDS = [nomi for nomi, _b in ZOND_INYEKSIYA_BELGILARI]

EGA = "Справочник.Товары"


def _buzuq_maydonli_graf(maydon_nomi: str):
    """Grafni HUJJATDAN CHETLAB O'TIB buzadi: maydon nomi grafda ROSTDAN turadi.

    ⚠️ Shu bois rad etilish sababi «grafda yo'q» BO'LMAYDI — nishon topiladi, va to'xtatuvchi
    yagona narsa xom kod darvozasi bo'lishi kerak."""
    g = build_graph(config("A"))
    ega = g.by_full_name(EGA)
    maydon = dataclasses.replace(ega.fields[0], name=maydon_nomi, path=maydon_nomi)
    yangi_ega = dataclasses.replace(ega, fields=(maydon,) + ega.fields[1:])
    buzuq = dataclasses.replace(
        g, objects=tuple(yangi_ega if o.full_name == EGA else o for o in g.objects))
    return buzuq, f"{EGA}{PATH_SEP}{maydon_nomi}"


@pytest.mark.parametrize("belgi", [b for _n, b in ZOND_INYEKSIYA_BELGILARI], ids=ZOND_IDS)
def test_zond_nishonidagi_kod_belgisi_rad_etiladi(belgi: str):
    """⚠️ NUQSON TESTI: maydon nomi bilan qurilgan MAYDON MANZILI zond darvozasidan o'tardi.

    Manzil grafda bor, ya'ni `split_field_target` uni topadi — demak to'xtatish AYNAN
    `assert_no_raw_code` ning ishi."""
    buzuq, nishon = _buzuq_maydonli_graf(_buzuq_nom(belgi))
    assert split_field_target(nishon, graph=buzuq) is not None, (
        "nishon grafda BOR — rad etilish sababi «grafda yo'q» bo'lmasligi kerak")
    with pytest.raises(ProbeError) as e:
        validate_probe(ProbeRequest(probe_type="field_type_details", target_object=nishon,
                                    reason="tip shakli nomdan mustaqil dalil beradi",
                                    expected_evidence=("type_shape",)), graph=buzuq)
    xato = str(e.value)
    assert "xom kod" in xato
    assert "target_object" in xato


def test_zond_nishonida_NUQTA_qonuniy_qoladi():
    """⚠️ QARSHI TEKSHIRUV: `<obyekt>.<maydon>` — zondning QONUNIY nishon shakli.

    Nuqtani xom kod deb to'sish `field_type_details` ni butunlay o'lik qilardi."""
    g = build_graph(config("A"))
    nishon = f"{EGA}{PATH_SEP}Артикул"
    assert validate_probe(
        ProbeRequest(probe_type="field_type_details", target_object=nishon,
                     reason="tip shakli nomdan mustaqil dalil beradi",
                     expected_evidence=("type_shape",)), graph=g) is None
    # Jadval bo'limi maydoni — IKKI nuqtali manzil ham qonuniy.
    hujjat = g.by_full_name("Документ.РеализацияТоваров")
    bolimli = [f for f in hujjat.fields if PATH_SEP in f.path]
    assert bolimli, "fikstura A da jadval bo'limi maydoni bo'lishi kerak"
    assert validate_probe(
        ProbeRequest(probe_type="field_type_details", target_object=bolimli[0].address,
                     reason="tip shakli nomdan mustaqil dalil beradi",
                     expected_evidence=("type_shape",)), graph=g) is None


def test_obyekt_nishoni_ham_manzil_darvozasidan_otadi():
    """Obyekt nishonli zondlar (`row_count` va boshqalar) ham shu darvozadan o'tadi."""
    g = build_graph(config("A"))
    ega = g.by_full_name(EGA)
    buzuq_nom = f'{EGA}"); Объект.Записать(); Zond("row_count", "X'
    yangi = dataclasses.replace(ega, full_name=buzuq_nom)
    buzuq = dataclasses.replace(
        g, objects=tuple(yangi if o.full_name == EGA else o for o in g.objects))
    assert buzuq.by_full_name(buzuq_nom) is not None
    with pytest.raises(ProbeError) as e:
        validate_probe(ProbeRequest(probe_type="row_count", target_object=buzuq_nom,
                                    reason="qatorlar soni gipotezani tekshiradi",
                                    expected_evidence=("cardinality",)), graph=buzuq)
    assert "xom kod" in str(e.value)
    # ⚠️ Xato matni topilgan bo'lakni QISQARTIRADI — uzun kod jurnalga to'liq ko'chmaydi.
    assert buzuq_nom not in str(e.value)


def test_izoh_matnida_tinish_belgisi_TOSILMAYDI():
    """⚠️ QARSHI TEKSHIRUV (YOLG'ON IJOBIY): manzil rejimi TUSHUNTIRISH matniga TARQAMAYDI.

    Tahlil qatlamining dalil matnlari (`evidence.detail`, `ambiguity`, `notes`) qavs, vergul,
    kvadrat qavs, plyus va qo'shtirnoqni QONUNIY ishlatadi — masalan leksik ball hissasi
    qavs ichida yoziladi. Manzil darvozasini prozaga ham qo'llash o'sha qatlamni o'ldirardi."""
    proza = ("obyekt sinonimi: mos ishoralar ['birlik', \"o'lchov\"] — "
             "leksik ball 1.000 (hissa +0.30)")
    assert assert_no_raw_code(proza, where="sinov") is None
    # Prozada `;` va figurali qavs esa AVVALGIDEK to'siladi — bu darvoza yumshatilmadi.
    for taqiq in ("sabab; DROP", "sabab {kod}"):
        with pytest.raises(ProbeError):
            assert_no_raw_code(taqiq, where="sinov")
