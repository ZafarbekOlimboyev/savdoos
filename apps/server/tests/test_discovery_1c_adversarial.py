# -*- coding: utf-8 -*-
"""ADVERSARIAL FIKSTURA TESTLARI — `HeuristicAnalyzer` ning A–O ustidagi XULQI.

⚠️⚠️ BU FAYL «TO'G'RI JAVOB»NI QULFLAMAYDI. Heuristika ballari o'zgarishi mumkin va bu o'zi
     bilan nuqson EMAS: vaznlar jadvali (`analyst/heuristics.py`) ataylab ochiq va sozlanadi.
     Nuqson — INVARIANTNING buzilishi: `VERIFIED` chiqishi, `HUMAN_CONFIRMED` ning AI
     kanalidan o'tishi, ikkilanishning yashirilishi, qarshi dalilning yozilmasligi,
     qaralmagan konseptning jimgina tushib qolishi, tekshirib bo'lmaydigan zond taklifi.
     Shu bois pastdagi tasdiqlar BALLNI emas, XULQNI o'lchaydi.

⚠️⚠️ BU FAYL HAQIQIY 1C DA HECH NARSANI ISBOTLAMAYDI. Fiksturalar sintetik va nomlari to'qima
     (`tests/discovery_1c_metadata_synth.py` ning boshidagi izohga qarang). Bu yerda yashil
     natija «ekstraktor mijoz bazasida ishlaydi» degani EMAS — u faqat talqin qatlami turli
     tuzilmalarga qanday javob berishini qulflaydi.

QAMRALGAN INVARIANTLAR:
  1. Hamma 15 konfiguratsiyada birorta gipotezada `VERIFIED` ham, `HUMAN_CONFIRMED` ham YO'Q,
     va ikkisi AI kanaliga QO'LDAN qo'yilsa validator RAD etadi.
  2. Dalil HAR DOIM kuchsiz: avtomat o'zini o'zi tasdiqlay olmaydi.
  3. Qaralmagan konsept TASHLANMAYDI — u `UNKNOWN` bo'lib ro'yxatda qoladi.
  4. Har bir taklif qilingan zond katalog darvozasidan O'TADI (faqat-o'qish, grafdagi nishon).
  5. Dalilsiz yoki tekshirish yo'li aytilmagan gipoteza CHIQMAYDI.
  6. Ko'rik artefakti DETERMINISTIK: bir xil kirish — aynan bir xil bayt; kirish tartibi
     o'zgarishi ham natijani o'zgartirmaydi.
  7. Odam tasdig'i AJRALGAN: `apply_confirmations` dan oldin `HUMAN_CONFIRMED` yo'q, keyin bor,
     va tasdiq `confidence_score` ni O'ZGARTIRMAYDI.
  8. Fikstura-ba-fikstura xulq: A–F nomzod topadi, G faqat strukturadan topadi, H/I/O qarshi
     dalil yozadi, J ikkilanishni AYTADI, K registrdagi kodni topadi, L jimgina taxmin
     qilmaydi, M xarakteristika zanjirini ko'rsatadi, N ombor yo'qligini yashirmaydi.
  9. BAHOLASHNING O'Z NUQSONLARI (fayl oxiridagi bo'lim): chalg'ituvchi jarima KONSEPTGA
     bog'langan, RAD etilgan nomzod ikkilanishga sanalmaydi, struktura dalilisiz nom mosligi
     yuqori chegaradan oshmaydi, sanab o'tilgan qiymat ham nomzod manzili bo'la oladi.
     ⚠️ Bu to'rttasi ham BUZILISHNI o'lchaydi: har biri tuzatishdan OLDIN yiqilardi.
"""
from __future__ import annotations

import copy
import re

import pytest

from app.services.discovery_1c.ai import (AI_STATUSES, CONCEPTS, FORBIDDEN_STATUS,
                                          MAX_PROBES_PER_HYPOTHESIS, STATUS_AMBIGUOUS,
                                          STATUS_CANDIDATE, STATUS_HUMAN_CONFIRMED,
                                          STATUS_REJECTED, WEIGHT_WEAK, AnalysisError,
                                          analyst_payload, hypotheses_to_json, unknown_concepts,
                                          validate_analysis)
from app.services.discovery_1c.bundle import dumps
from app.services.discovery_1c.confirmations import (CONFIRMATIONS_VERSION, DECISION_CONFIRM,
                                                     apply_confirmations)
from app.services.discovery_1c.graph import build_graph
from app.services.discovery_1c.probe import validate_probe, validate_probe_plan
from app.services.discovery_1c.review import (build_operator_worksheet, build_review,
                                              dumps_review)
from app.services.discovery_1c.schema import WEAK_EVIDENCE_KINDS
from app.services.discovery_1c.analyst.heuristics import (NO_STRUCTURE_CEILING, STATE_UNKNOWN,
                                                          HeuristicAnalyzer, coverage)
from app.services.discovery_1c.analyst.lexicon import (ANY_CONCEPT, MISLEADING_CLUES,
                                                       misleading_hits)
from tests.discovery_1c_metadata_synth import (ALL_CONFIGS, EXPECTED, EXPECTED_KEYS, XULQLAR,
                                               config, doc, field, obj)

#: Hamma fikstura harfi — tartiblangan (determinizm: yurishlar bir-biriga o'xshasin).
HARFLAR = tuple(sorted(ALL_CONFIGS))

#: A–F bir XIL tuzilmani olti tilda takrorlaydi: nomzod ikkalasida ham topilishi kerak.
TIL_HARFLARI = ("A", "B", "C", "D", "E", "F")

#: LEKSIK dalil turlari. ⚠️ Faqat shu ikkisi nomdan keladi; qolganlari (`structural_link`,
#: `type_shape`, `value_domain`, `cardinality`, `fill_ratio`) nomdan MUSTAQIL.
LEKSIK_DALIL_TURLARI = ("name_match", "synonym_match")

#: Tahlilchining nomi va versiyasi — ko'rik artefakti uchun MAJBURIY.
#: ⚠️ `UNVERIFIED` ataylab: bu analitik birorta haqiqiy konfiguratsiyada tasdiqlanmagan.
TAHLILCHI = ("HeuristicAnalyzer", "0.1.0-UNVERIFIED")

#: ⚠️ Tasdiq vaqti FIKSTURANING KIRISHI, hisoblanmaydi: `Date.now()` kabi narsa determinizmni
#: buzardi va bir xil kirish har yurishda boshqa bayt berardi.
QAROR_VAQTI = "2026-09-30T12:00:00+05:00"


# ── Yordamchilar ───────────────────────────────────────────────────────────────────────────
#: Tahlil KESHI. ⚠️ Kesh xavfsiz: `Hypothesis` va graf `frozen`, ya'ni test ularni
#: o'zgartira olmaydi. Xom lug'at esa HAR SAFAR qaytadan yasaladi (`xom`), chunki uni
#: buzib sinaydigan testlar bor.
_KESH: dict[str, tuple] = {}


def tahlil(harf: str):
    """`(graf, gipotezalar)` — fikstura harfi bo'yicha, yadro shartnomasining AYNI oqimi.

    Oqim ataylab to'liq: yuk quriladi, analitik chaqiriladi, natija `validate_analysis` dan
    O'TADI. Ya'ni bu testlar validator rad etadigan narsani hisobga olib qo'ymaydi."""
    if harf not in _KESH:
        graf = build_graph(config(harf))
        gipotezalar = validate_analysis(HeuristicAnalyzer().analyze(analyst_payload(graf)),
                                        graph=graf)
        _KESH[harf] = (graf, gipotezalar)
    return _KESH[harf]


def xom(harf: str) -> tuple:
    """`(graf, xom lug'at)` — analitikning TEKSHIRILMAGAN chiqishi (buzib sinash uchun)."""
    graf = build_graph(config(harf))
    return (graf, HeuristicAnalyzer().analyze(analyst_payload(graf)))


def konsept(gipotezalar, nom: str) -> list:
    """Bitta konseptning gipotezalari — tartibi `validate_analysis` dan kelgan holda."""
    return [h for h in gipotezalar if h.target_concept == nom]


def manzillar(rows) -> set[str]:
    return {h.address for h in rows}


def dalil_turlari(h) -> set[str]:
    return {e.kind for e in h.evidence}


def qarshi_matn(h) -> str:
    """Qarshi dalillarning tafsilotlari bitta matnda — SABAB ko'rinadimi degan savol uchun."""
    return " ".join(e.detail for e in h.counter_evidence)


def baytlar(doc) -> str:
    """Hujjatdan chiqadigan gipotezalarning DETERMINISTIK bayt ko'rinishi."""
    graf = build_graph(doc)
    gipotezalar = validate_analysis(HeuristicAnalyzer().analyze(analyst_payload(graf)),
                                    graph=graf)
    return dumps(hypotheses_to_json(gipotezalar))


def korik(harf: str) -> dict:
    graf, gipotezalar = tahlil(harf)
    return build_review(gipotezalar, graph=graf, analyzer_name=TAHLILCHI[0],
                        analyzer_version=TAHLILCHI[1])


def tasdiq_hujjati(h, *, qaror: str = DECISION_CONFIRM, izoh=None) -> dict:
    """Bitta gipoteza haqidagi OPERATOR tasdig'i — AI chiqishidan AJRALGAN hujjat."""
    return {
        "confirmations_version": CONFIRMATIONS_VERSION,
        "confirmations": [{
            "target_concept": h.target_concept,
            "candidate_object": h.candidate_object,
            "candidate_field": h.candidate_field,
            "decision": qaror,
            "operator": "Operator Sinov",
            "decided_at": QAROR_VAQTI,
            "note": izoh,
        }],
        "notes": [],
    }


# ── Fikstura to'plamining o'z butunligi ────────────────────────────────────────────────────
def test_kutilgan_xulq_jadvali_hamma_fiksturani_qamraydi():
    """`EXPECTED` va `ALL_CONFIGS` AYNAN bir xil harflarni qamrasin.

    ⚠️ Bu tekshiruv kerak, chunki jadvalga tushmagan fikstura JIMGINA sinalmay qolardi: testlar
       yashil bo'lardi, qamrov esa kamaygan bo'lardi va buni hech narsa aytmasdi."""
    assert sorted(EXPECTED) == list(HARFLAR)
    for harf, yozuv in sorted(EXPECTED.items()):
        assert set(yozuv) == set(EXPECTED_KEYS), f"{harf}: kutilgan xulq shakli buzilgan"
        assert yozuv["xulq"] in XULQLAR, f"{harf}: noma'lum xulq nomi {yozuv['xulq']!r}"
        # ⚠️ `leksik_yetarli` HAR JOYDA `False` bo'lishi SHART: nom mosligi o'zi bilan
        #    tasdiqlangan xarita bermaydi (5-qoida). Bu izohda emas, INVARIANTDA turishi kerak.
        assert yozuv["leksik_yetarli"] is False, (
            f"{harf}: leksik moslik hech qachon yetarli bo'la olmaydi")


@pytest.mark.parametrize("harf", HARFLAR)
def test_fikstura_grafga_aylanadi(harf: str):
    """Har fikstura `validate_metadata` dan o'tib graf bo'lsin — aks holda qolgan testlar
    nimani o'lchayotgani noma'lum bo'lardi."""
    graf, _ = tahlil(harf)
    assert graf.objects, f"{harf}: grafda obyekt yo'q"
    # ⚠️ Aniqlanmagan havola JIMGINA O'CHIRILMAYDI: u grafda saqlanadi va `EXPECTED` uni
    #    kutilmaning bir qismi deb ataydi («qaralmadi» ≠ «yo'q»).
    kutilgan = EXPECTED[harf]["aniqlanmagan_havola_shart"]
    assert bool(graf.unresolved_references) == kutilgan, (
        f"{harf}: aniqlanmagan havolalar {graf.unresolved_references} — kutilgani {kutilgan}")


# ── 1-qoida: `VERIFIED` va `HUMAN_CONFIRMED` bu kanalda YO'Q ───────────────────────────────
@pytest.mark.parametrize("harf", HARFLAR)
def test_birorta_gipotezada_taqiqlangan_holat_yoq(harf: str):
    """Analitik FAQAT `CANDIDATE`/`AMBIGUOUS`/`REJECTED` chiqaradi.

    ⚠️ `VERIFIED` — bu kanalda umuman yo'q: u faqat KUCHLI dalil bilan beriladi, analitik esa
       metadatadan boshqa hech narsani o'qimaydi.
    ⚠️ `HUMAN_CONFIRMED` shartnomada BOR, lekin u operatorning ALOHIDA hujjatidan keladi —
       modelning yoki bu qatlamning ishonchidan EMAS."""
    _, gipotezalar = tahlil(harf)
    for h in gipotezalar:
        assert h.status != FORBIDDEN_STATUS, f"{harf}: {h.address} uchun {FORBIDDEN_STATUS}"
        assert h.status != STATUS_HUMAN_CONFIRMED, (
            f"{harf}: {h.address} odam tasdig'ini O'ZI e'lon qildi")
        assert h.status in AI_STATUSES, f"{harf}: {h.address} holati {h.status!r}"


@pytest.mark.parametrize("harf", HARFLAR)
@pytest.mark.parametrize("holat", (FORBIDDEN_STATUS, STATUS_HUMAN_CONFIRMED))
def test_taqiqlangan_holat_qolda_qoyilsa_validator_rad_etadi(harf: str, holat: str):
    """Chiqishga taqiqlangan daraja QO'LDAN qo'yilsa — RAD, jimgina pasaytirilmaydi.

    ⚠️ Bu tekshiruv analitikka ishonmaydi: haqiqiy provayder ulagichi shu ikki holatni
       yozib yuborishi mumkin, va yadro unga ISHONMASDAN tekshirishi kerak."""
    graf, raw = xom(harf)
    buzuq = copy.deepcopy(raw)
    assert buzuq["hypotheses"], f"{harf}: gipoteza yo'q — sinov ma'nosiz"
    buzuq["hypotheses"][0]["status"] = holat
    with pytest.raises(AnalysisError):
        validate_analysis(buzuq, graph=graf)


# ── 2-qoida: dalil HAR DOIM kuchsiz ────────────────────────────────────────────────────────
@pytest.mark.parametrize("harf", HARFLAR)
def test_dalil_hamisha_kuchsiz(harf: str):
    """Avtomat KUCHLI dalil turini chiqara olmaydi — o'zini o'zi tasdiqlash imkonsiz."""
    _, gipotezalar = tahlil(harf)
    for h in gipotezalar:
        for e in tuple(h.evidence) + tuple(h.counter_evidence):
            assert e.kind in WEAK_EVIDENCE_KINDS, (
                f"{harf}: {h.address} kuchli dalil turini chiqardi: {e.kind!r}")
            assert e.weight == WEIGHT_WEAK, (
                f"{harf}: {h.address} dalil vazni {e.weight!r} — turdan kelib chiqishi kerak")


# ── 4-qoida: dalilsiz va tekshirib bo'lmaydigan gipoteza chiqmaydi ─────────────────────────
@pytest.mark.parametrize("harf", HARFLAR)
def test_har_gipoteza_dalil_va_tekshirish_yoli_bilan_keladi(harf: str):
    """Xulosa dalil bilan, ikkilanish sababi bilan, rad etish qarshi dalil bilan keladi.

    ⚠️ `required_confirmation` bo'sh bo'lsa gipoteza tekshirib bo'lmaydigan bo'ladi, ya'ni u
       hujjatda abadiy `CANDIDATE` bo'lib yotib qolardi — shu bois u ham invariant."""
    _, gipotezalar = tahlil(harf)
    for h in gipotezalar:
        if h.status in (STATUS_CANDIDATE, STATUS_AMBIGUOUS):
            assert h.evidence, f"{harf}: {h.address} — {h.status} dalilsiz"
            assert h.required_confirmation, (
                f"{harf}: {h.address} — odam NIMANI ko'rishi aytilmagan")
        if h.status == STATUS_AMBIGUOUS:
            assert h.ambiguity, f"{harf}: {h.address} — ikkilanish sababi aytilmagan"
        if h.status == STATUS_REJECTED:
            assert h.counter_evidence, f"{harf}: {h.address} — sababsiz rad etilgan"


# ── 3-qoida: qaralmagan konsept TASHLANMAYDI ───────────────────────────────────────────────
@pytest.mark.parametrize("harf", HARFLAR)
def test_nomzodsiz_konseptlar_unknown_bolib_royxatda_qoladi(harf: str):
    """«Qaralmadi» ≠ «yo'q»: nomzodsiz konsept OCHIQ `UNKNOWN` bo'lib turadi.

    ⚠️ Tushirib qoldirilgan konsept keyinchalik «tekshirilgan va topilmagan» deb o'qilardi, va
       aynan shu o'qish 1C dan ko'chirishda maydonni jimgina yo'qotardi."""
    graf, gipotezalar = tahlil(harf)
    qamralgan = {h.target_concept for h in gipotezalar}
    noma_lum = set(unknown_concepts(gipotezalar))

    assert qamralgan | noma_lum == set(CONCEPTS), (
        f"{harf}: konsept ro'yxatidan tushib qolgan: "
        f"{sorted(set(CONCEPTS) - (qamralgan | noma_lum))}")
    assert not (qamralgan & noma_lum), (
        f"{harf}: konsept bir vaqtda qamralgan ham, noma'lum ham: "
        f"{sorted(qamralgan & noma_lum)}")

    qamrov = coverage(graf)
    assert list(qamrov["concepts_unknown"]) == sorted(noma_lum)
    for nom in sorted(noma_lum):
        assert qamrov["concepts"][nom]["state"] == STATE_UNKNOWN, (
            f"{harf}: {nom} nomzodsiz, lekin qamrovda {qamrov['concepts'][nom]['state']!r}")
    # ⚠️ Sanoqlar MATN (`binos-1c-metadata-v1` 1-invarianti): `0000123` soni `123` bo'lib
    #    qolardi va boshidagi nollar bilan birga ma'no yo'qolardi.
    for kalit, qiymat in sorted(qamrov["counts"].items()):
        assert isinstance(qiymat, str), f"{harf}: qamrov sanog'i {kalit} MATN emas: {qiymat!r}"


# ── 6-qoida: zondlar KATALOG darvozasidan o'tadi ───────────────────────────────────────────
@pytest.mark.parametrize("harf", HARFLAR)
def test_taklif_qilingan_zondlar_katalog_darvozasidan_otadi(harf: str):
    """Har zond: katalogdagi tur, GRAFDAGI nishon, sababi bor, kutilgan dalili KUCHSIZ.

    ⚠️ Grafda yo'q nishonga yuborilgan zond eng yaxshi holatda xato, eng yomonida — boshqa
       obyektga tushib ketgan so'rov. Shu bois tekshiruv gipoteza-ba-gipoteza bajariladi."""
    graf, gipotezalar = tahlil(harf)
    for h in gipotezalar:
        for z in h.recommended_next_probe:
            validate_probe(z, graph=graf)
        # ⚠️ Reja BUTUNLIGICHA ham darvozadan o'tadi: takrorni birlashtirish va chegara
        #    (`MAX_PROBES_PER_HYPOTHESIS`) shartnomaning bir qismi.
        reja = validate_probe_plan(h.recommended_next_probe, graph=graf,
                                   max_probes=MAX_PROBES_PER_HYPOTHESIS)
        assert len(reja) == len(h.recommended_next_probe), (
            f"{harf}: {h.address} rejasida takroriy zond bor")


# ── 8-qoida: determinizm ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("harf", HARFLAR)
def test_korik_artefakti_deterministik(harf: str):
    """Bir xil kirish — AYNAN bir xil bayt, ya'ni ikki ko'rikni diff bilan solishtirish mumkin."""
    graf1 = build_graph(config(harf))
    h1 = validate_analysis(HeuristicAnalyzer().analyze(analyst_payload(graf1)), graph=graf1)
    graf2 = build_graph(config(harf))
    h2 = validate_analysis(HeuristicAnalyzer().analyze(analyst_payload(graf2)), graph=graf2)
    birinchi = dumps_review(build_review(h1, graph=graf1, analyzer_name=TAHLILCHI[0],
                                         analyzer_version=TAHLILCHI[1]))
    ikkinchi = dumps_review(build_review(h2, graph=graf2, analyzer_name=TAHLILCHI[0],
                                         analyzer_version=TAHLILCHI[1]))
    assert birinchi == ikkinchi, f"{harf}: ko'rik artefakti bayt-bayt bir xil emas"

    doc = korik(harf)
    # ⚠️ Artefakt `VERIFIED` ni HECH QANDAY yo'l bilan olib chiqmasligi kerak — sanoqlar ham
    #    shu holatni bilmasligi kerak.
    assert FORBIDDEN_STATUS not in doc["counts"]["by_status"]
    assert doc["warnings"], f"{harf}: artefakt o'z ogohlantirishisiz chiqdi"
    # Operator varaqasi ham yasalsin: u `_validate_review` dan o'tadi va bo'sh bo'lmaydi.
    varaq = build_operator_worksheet(doc)
    assert "OPERATOR KO'RIGI" in varaq


@pytest.mark.parametrize("harf", HARFLAR)
def test_obyekt_tartibi_natijani_ozgartirmaydi(harf: str):
    """Kirish TARTIBI natijaga ta'sir qilmaydi: yig'uvchi obyektlarni boshqa navbatda bergani
    tahlilni o'zgartirmasligi kerak.

    ⚠️ NEGA KERAK: teng ballda «birinchi kelgani» bo'yicha tanlov jimgina boshqa javob berardi,
       va ikki yurishning natijasi sababsiz farq qilardi."""
    asl = config(harf)
    teskari = config(harf)
    teskari["objects"] = list(reversed(teskari["objects"]))
    for o in teskari["objects"]:
        for ro_yxat in ("attributes", "dimensions", "resources", "tabular_sections"):
            o[ro_yxat] = list(reversed(o[ro_yxat]))
    assert baytlar(asl) == baytlar(teskari), (
        f"{harf}: obyekt/maydon tartibi o'zgarganda tahlil ham o'zgardi")


# ── 7-qoida: odam tasdig'i AJRALGAN ────────────────────────────────────────────────────────
@pytest.mark.parametrize("harf", HARFLAR)
def test_odam_tasdigi_ajralgan_oqimdan_keladi(harf: str):
    """`HUMAN_CONFIRMED` ga YAGONA yo'l — `apply_confirmations`.

    ⚠️ Tasdiq `confidence_score` ni KO'TARMAYDI: ball — analitikning O'Z bahosi, tasdiq esa
       BOSHQA TURDAGI bilim (ekranda ko'rilgan narsa). Ikkisini qo'shib yuborish «ball yuqori
       edi» degan gapni «odam ko'rdi» degan ma'noga aylantirardi.
    ⚠️ Tasdiqlanmagan gipoteza BIR BAYT ham o'zgarmasligi kerak."""
    _, gipotezalar = tahlil(harf)
    assert gipotezalar, f"{harf}: gipoteza yo'q — sinov ma'nosiz"
    assert all(h.status != STATUS_HUMAN_CONFIRMED for h in gipotezalar), (
        f"{harf}: tasdiqdan OLDIN ham HUMAN_CONFIRMED bor")

    nishon = gipotezalar[0]
    keyin = apply_confirmations(gipotezalar, tasdiq_hujjati(nishon))
    by_key = {(h.target_concept, h.address): h for h in keyin}

    tasdiqlangan = by_key[(nishon.target_concept, nishon.address)]
    assert tasdiqlangan.status == STATUS_HUMAN_CONFIRMED
    assert any(e.kind == "human_confirmed" for e in tasdiqlangan.evidence), (
        f"{harf}: tasdiqda KIM va QACHON yozilmagan")
    assert tasdiqlangan.confidence_score == nishon.confidence_score, (
        f"{harf}: tasdiq ballni o'zgartirdi — ikki o'lchov qo'shilib ketdi")

    boshqalar = [h for h in gipotezalar if (h.target_concept, h.address)
                 != (nishon.target_concept, nishon.address)]
    for h in boshqalar:
        assert by_key[(h.target_concept, h.address)] == h, (
            f"{harf}: {h.address} tasdiqlanmagan, lekin o'zgardi")


# ── A–F: nom turli tillarda, xulq bir xil ──────────────────────────────────────────────────
@pytest.mark.parametrize("harf", TIL_HARFLARI)
def test_til_fiksturalarida_mahsulot_nomzodi_topiladi(harf: str):
    """A–F: mahsulot uchun kamida bitta nomzod, va u `CANDIDATE`/`AMBIGUOUS` dan oshmaydi.

    ⚠️ Agar talqin qatlami A da ishlab B–F da ishlamasa, u ma'noni emas LUG'ATNI o'qigan
       bo'ladi — va bu nuqson har bir «o'zi uchun moslashtirilgan» do'konda chiqadi."""
    _, gipotezalar = tahlil(harf)
    rows = konsept(gipotezalar, "product")
    assert rows, f"{harf}: mahsulot uchun birorta nomzod topilmadi"
    for h in rows:
        assert h.status in (STATUS_CANDIDATE, STATUS_AMBIGUOUS), (
            f"{harf}: mahsulot nomzodi holati {h.status!r} — kutilgani CANDIDATE/AMBIGUOUS")
        assert h.evidence and h.required_confirmation


# ── G: NOMDAN hech narsa bilinmaydi ────────────────────────────────────────────────────────
def test_g_nomzodni_faqat_strukturadan_topadi():
    """G: sinonim yo'q, izoh yo'q, nomlar `X17`/`R41`/`ABCD`/`F1`. Struktura esa TO'LIQ.

    ⚠️ Bu spetsifikatsiyaning 9-bandi: nomdan hech narsa chiqmaydigan konfiguratsiyada ham
       nomzod TOPILISHI kerak, va uning dalili `structural_link` bo'lishi SHART.
    ⚠️ ISBOTLAMAYDI: `Catalog.X17` ning mahsulot ekanini. Struktura dalili ham KUCHSIZ."""
    _, gipotezalar = tahlil("G")
    rows = konsept(gipotezalar, "product")
    assert rows, "G: struktura saqlangan bo'lsa ham mahsulot nomzodi topilmadi"
    assert "Catalog.X17" in manzillar(rows), (
        f"G: registrlar havola qiladigan katalog nomzod bo'lmadi — {sorted(manzillar(rows))}")
    for h in rows:
        assert "structural_link" in dalil_turlari(h), (
            f"G: {h.address} strukturaga tayanmagan — dalillari {sorted(dalil_turlari(h))}")

    # ⚠️ G da LEKSIK dalil BO'LMASLIGI kerak — birorta gipotezada ham. Agar paydo bo'lsa,
    #    demak lug'at ma'nosiz nomga (masalan `ABCD`) tasodifan mos kelgan, ya'ni ishoralar
    #    ro'yxati YOLG'ON dalil berayotgan bo'ladi.
    for h in gipotezalar:
        leksik = dalil_turlari(h) & set(LEKSIK_DALIL_TURLARI)
        assert not leksik, f"G: {h.address} tushunarsiz nomdan leksik dalil oldi: {sorted(leksik)}"


# ── H: nomi mos, ma'nosi boshqa ────────────────────────────────────────────────────────────
def test_h_aldaydigan_nom_jimgina_tanlanmaydi():
    """H: `Справочник.Товары` nomi mos, lekin ichida hujjat shablonlari va unga birorta registr
    havola QILMAYDI; registrlar esa `Справочник.КарточкиУчета` ga havola qiladi.

    ⚠️ Nom bo'yicha ishlagan talqin `Товары` ni tanlaydi va JIMGINA xato qiladi. Shu bois:
       (1) nomi mos obyekt uchun QARSHI DALIL yozilishi shart,
       (2) struktura ko'rsatgan obyekt ham nomzod bo'lib chiqishi shart,
       (3) natija AMBIGUOUS bo'lishi yoki struktura USTUN kelishi kerak."""
    _, gipotezalar = tahlil("H")
    rows = konsept(gipotezalar, "product")
    joy = {h.address: h for h in rows}
    nomi_mos = joy.get("Справочник.Товары")
    struktura = joy.get("Справочник.КарточкиУчета")

    assert nomi_mos is not None, "H: nomi mos katalog umuman ko'rinmadi — dalil yashirildi"
    assert nomi_mos.counter_evidence, "H: nomi mos katalog uchun qarshi dalil yozilmagan"
    assert "havola qilmaydi" in qarshi_matn(nomi_mos), (
        f"H: havola YO'QLIGI qarshi dalilda ko'rinmadi — {qarshi_matn(nomi_mos)!r}")
    assert struktura is not None, (
        "H: struktura ko'rsatgan katalog nomzod bo'lmadi — «kim havola qiladi» dalili "
        f"yo'qolgan; bori: {sorted(joy)}")

    ikkilanish_bor = any(h.status == STATUS_AMBIGUOUS for h in rows)
    struktura_ustun = struktura.confidence_score > nomi_mos.confidence_score
    assert ikkilanish_bor or struktura_ustun, (
        "H: nom bo'yicha JIMGINA tanlandi — ikkilanish ham aytilmadi, struktura ham ustun "
        f"kelmadi (nom {nomi_mos.confidence_score}, struktura {struktura.confidence_score})")


# ── I: mahsulotga o'xshagan, lekin mahsulot EMAS ───────────────────────────────────────────
def test_i_mahsulotga_oxshagan_past_ball_va_qarshi_dalil_oladi():
    """I: `Справочник.ТоварныеГруппы` nomi mos va ierarxik, lekin unga birorta registr havola
    qilmaydi; haqiqiy obyekt esa inventarizatsiyadan TASHQARIDA qolgan.

    ⚠️ To'g'ri javob — «BU HUJJATDA topilmadi», «mahsulot yo'q» EMAS. Shu bois aniqlanmagan
       havola grafda SAQLANADI va nomzod past ballda, qarshi dalili bilan chiqadi."""
    graf, gipotezalar = tahlil("I")
    assert graf.unresolved_references, (
        "I: hujjatda yo'q obyektga qilingan havola jimgina o'chirilgan — ma'lumot yo'qoldi")

    rows = konsept(gipotezalar, "product")
    for h in rows:
        # ⚠️ Chegara ATAYLAB kengroq (0.5): ball o'zgarishi mumkin, lekin nomi mos, havolasiz,
        #    ierarxik katalog HECH QACHON ishonchli javob bo'lib chiqmasligi kerak.
        assert h.confidence_score <= 0.5, (
            f"I: {h.address} ishonchli nomzod bo'lib chiqdi (ball {h.confidence_score})")
        assert h.counter_evidence, f"I: {h.address} uchun qarshi dalil yozilmagan"

    guruhlar = [h for h in rows if h.address == "Справочник.ТоварныеГруппы"]
    assert guruhlar, "I: nomi mos katalog umuman ko'rinmadi — qarshi dalil ham yo'qoldi"
    matn = qarshi_matn(guruhlar[0])
    assert "ierarxi" in matn, f"I: ierarxiya qarshi dalilda ko'rinmadi — {matn!r}"
    assert "havola qilmaydi" in matn, f"I: havola yo'qligi qarshi dalilda ko'rinmadi — {matn!r}"


# ── J: IKKITA jiddiy mahsulot nomzodi ──────────────────────────────────────────────────────
def test_j_ikki_mahsulot_katalogi_ambiguous_boladi():
    """J: ikkisi ham katalog, ikkisining nomi ham mos, ikkisiga ham alohida balans registri
    havola qiladi, shtrix-kod o'lchovi IKKALASIGA birga havola qiladi.

    ⚠️ Jimgina bittasini tanlash — eng xavfli natija: u xato bo'lsa ham ishonchli KO'RINADI.
    ⚠️ Shu bois `ambiguity` da IKKALA nomzod ko'rsatilishi SHART: ikkinchisi aytilmasa,
       operator tanlov borligini bilmaydi."""
    _, gipotezalar = tahlil("J")
    rows = konsept(gipotezalar, "product")
    joy = manzillar(rows)
    ikkovi = {"Справочник.ТоварыОсновные", "Справочник.ТоварыДополнительные"}
    assert ikkovi <= joy, f"J: ikki nomzoddan biri tushib qoldi — {sorted(joy)}"

    for h in rows:
        if h.address not in ikkovi:
            continue
        assert h.status == STATUS_AMBIGUOUS, (
            f"J: {h.address} holati {h.status!r} — tanlab bo'lmaydigan joyda AMBIGUOUS kerak")
        matn = " ".join(h.ambiguity)
        for boshqa in sorted(ikkovi):
            assert boshqa.split(".", 1)[1] in matn, (
                f"J: {h.address} ikkilanishida {boshqa} aytilmagan — {matn!r}")


# ── K: shtrix-kod alohida registrda ────────────────────────────────────────────────────────
def test_k_shtrix_kod_registrda_topiladi_va_zond_taklif_qilinadi():
    """K: mahsulot katalogida 13 uzunlikdagi satr UMUMAN yo'q — kod faqat registrda.

    ⚠️ Katalog maydonlarini kezib chiqib «kod yo'q» degan xulosaga kelgan talqin xato qiladi.
    ⚠️ ISBOTLAMAYDI: `Строка(13)` ning shtrix-kod ekanini — uzunlik kuchsiz dalil, shu bois
       nomzod bilan birga TEKSHIRUV zondi ham kelishi kerak."""
    _, gipotezalar = tahlil("K")
    registr = "РегистрСведений.КодыУпаковок"
    rows = konsept(gipotezalar, "barcode")
    registrdagi = [h for h in rows if h.candidate_object == registr]
    assert registrdagi, (
        f"K: barkod nomzodi registrda topilmadi — bori: {sorted(manzillar(rows))}")

    for h in registrdagi:
        assert h.recommended_next_probe, f"K: {h.address} uchun zond taklif qilinmagan"
    # ⚠️ Registrning SHAKLI (o'lchov/resurs taqsimoti) so'ralishi kerak: K da registrda IKKI
    #    resurs bor, ya'ni «registrning yagona resursi — kod» degan taxmin zond bilan yopiladi.
    hamma_zond = {z.probe_type for h in registrdagi for z in h.recommended_next_probe}
    assert "register_shape" in hamma_zond, (
        f"K: registr shakli so'ralmadi — taklif qilingan zondlar {sorted(hamma_zond)}")


# ── L: o'lchov birligi BILVOSITA ───────────────────────────────────────────────────────────
def test_l_birlik_bilvosita_bolsa_jimgina_taxmin_qilinmaydi():
    """L: mahsulot → `КлассификаторЕдиниц` → `БазовыеЕдиницы`, ya'ni birlik IKKI havola orqali.

    ⚠️ Bir qadamda to'xtagan talqin klassifikatorni birlik deb o'qiydi. Kutilgan xulq: birlik
       `UNKNOWN` bo'lib qolishi YOKI nomzod dalili va ZOND taklifi bilan chiqishi. Bir qadamlik
       javob (klassifikator yoki mahsulotning o'z havola maydoni) JIMGINA tanlanmasligi kerak:
       agar u nomzod bo'lib chiqsa — shubha qarshi dalilda yoki ikkilanishda KO'RINISHI shart."""
    _, gipotezalar = tahlil("L")
    rows = konsept(gipotezalar, "unit_of_measure")

    bir_qadamlik = {"Справочник.КлассификаторЕдиниц",
                    "Справочник.Изделия.ЕдиницаХранения"}
    for h in rows:
        assert h.status in (STATUS_CANDIDATE, STATUS_AMBIGUOUS), (
            f"L: {h.address} holati {h.status!r}")
        assert h.evidence, f"L: {h.address} dalilsiz"
        assert h.required_confirmation, f"L: {h.address} tekshirish yo'lisiz"
        assert h.recommended_next_probe, (
            f"L: {h.address} uchun zond taklif qilinmagan — zanjirni ochadigan savol yo'q")
        if h.address in bir_qadamlik:
            assert h.counter_evidence or h.ambiguity, (
                f"L: bir qadamlik javob {h.address} shubhasiz tanlandi — zanjirning qolgan "
                f"qadami yo'qoldi")


# ── M: xarakteristikalar havola orqali ─────────────────────────────────────────────────────
def test_m_xarakteristika_nomzod_yoki_zond_bilan_ochiladi():
    """M: qo'shimcha maydonlar obyektning O'Z rekvizit ro'yxatida ko'rinmaydi — zanjir
    `Продукты` → `ПланВидовХарактеристик.СвойстваПродуктов` → `Справочник.ЗначенияСвойств`.

    ⚠️ ISBOTLAMAYDI: zanjirdan o'tib qiymat O'QISHNI. Reja tarkibini ko'rish qiymat qaysi
       jadvalda saqlanganini bilish EMAS — shu bois nomzod YOKI zond yetarli javob."""
    graf, gipotezalar = tahlil("M")
    reja_obyekti = "ПланВидовХарактеристик.СвойстваПродуктов"
    assert graf.by_full_name(reja_obyekti) is not None, "M: fikstura o'zgargan"

    rows = konsept(gipotezalar, "product_variant")
    zanjir_zondi = any(z.target_object in (reja_obyekti, "Справочник.ЗначенияСвойств")
                       for h in gipotezalar for z in h.recommended_next_probe)
    assert rows or zanjir_zondi, (
        "M: xarakteristika uchun na nomzod, na zond taklifi chiqdi — zanjir jimgina yo'qoldi")
    for h in rows:
        assert h.evidence and h.required_confirmation
        assert h.status in (STATUS_CANDIDATE, STATUS_AMBIGUOUS), (
            f"M: {h.address} holati {h.status!r}")


# ── N: qoldiq registrining g'alati o'lchovlari ─────────────────────────────────────────────
def test_n_ombor_olchovi_yoqligi_yashirilmaydi():
    """N: balans registrida OMBOR O'LCHOVI YO'Q — o'rnida `MasulJoy` va `Partiya` turadi.

    ⚠️ Qoldiq registri nomzodi TOPILISHI kerak (registr rostdan qoldiq registri), lekin ombor
       o'lchovining yo'qligi qarshi dalilda yoki NOANIQLIKDA ko'rinishi shart.
    ⚠️ ISBOTLAMAYDI: `MasulJoy` ning ombor EMASLIGINI — hujjatdan buni bilib bo'lmaydi, shu
       bois javob nomzod darajasida qolishi kerak."""
    _, gipotezalar = tahlil("N")
    qoldiq = konsept(gipotezalar, "stock_balance")
    assert "РегистрНакопления.QoldiqHarakati" in manzillar(qoldiq), (
        f"N: qoldiq registri nomzod bo'lmadi — bori {sorted(manzillar(qoldiq))}")

    ombor = konsept(gipotezalar, "warehouse")
    if not ombor:
        # ⚠️ Nomzod umuman yo'qligi ham TO'G'RI javob: konsept `UNKNOWN` bo'lib qoladi.
        assert "warehouse" in unknown_concepts(gipotezalar)
        return
    for h in ombor:
        assert not (dalil_turlari(h) & set(LEKSIK_DALIL_TURLARI)), (
            f"N: {h.address} ombor nomiga o'xshamaydi, lekin leksik dalil oldi")
        assert h.status == STATUS_AMBIGUOUS or h.counter_evidence or h.ambiguity, (
            f"N: {h.address} ombor deb shubhasiz taklif qilindi — ombor o'lchovi yo'qligi "
            f"hech qayerda ko'rinmadi")


# ── O: dalil va qarshi dalil QARAMA-QARSHI ─────────────────────────────────────────────────
def test_o_dalil_va_qarshi_dalil_birga_chiqadi():
    """O: `Справочник.Товары` nomi mukammal mos, lekin bo'sh va havolasiz;
    `Справочник.УчетныеЕдиницы` nomi mahsulotdan uzoq, lekin registrlar unga havola qiladi.

    ⚠️ H dan farqi: H da yolg'on nomzodning boshqa ma'nosi hujjatda AYTILGAN (shablonlar), O da
       esa hech qanday tushuntirish yo'q — faqat bo'sh struktura. Shu bois O da IKKI TOMON ham
       yozilishi kerak: dalil VA qarshi dalil, holat esa AMBIGUOUS."""
    _, gipotezalar = tahlil("O")
    rows = konsept(gipotezalar, "product")
    joy = {h.address: h for h in rows}
    nomi_mos = joy.get("Справочник.Товары")
    struktura = joy.get("Справочник.УчетныеЕдиницы")

    assert nomi_mos is not None, "O: nomi mos katalog ko'rinmadi — qarama-qarshilik yashirildi"
    assert struktura is not None, (
        f"O: struktura ko'rsatgan katalog nomzod bo'lmadi — bori {sorted(joy)}")
    assert nomi_mos.evidence, "O: nomi mos katalogning dalili yozilmagan"
    assert nomi_mos.counter_evidence, "O: nomi mos katalogning qarshi dalili yozilmagan"
    assert nomi_mos.status == STATUS_AMBIGUOUS, (
        f"O: qarama-qarshi dalil holati {nomi_mos.status!r} — kutilgani AMBIGUOUS")
    assert struktura.status == STATUS_AMBIGUOUS, (
        f"O: struktura nomzodi holati {struktura.status!r} — kutilgani AMBIGUOUS")


# ═══════════════════════════════════════════════════════════════════════════════════════════
# BAHOLASHNING O'Z NUQSONLARI — ko'rikda topilgan va SHU YERDA qulflangan
# ⚠️ Pastdagi testlar «to'g'ri ball»ni emas, BUZILISHNI o'lchaydi: har biri tuzatishdan OLDIN
#    yiqilardi va aynan nuqsonni ko'rsatardi. Ular ballni emas, INVARIANTni qulflaydi.
# ═══════════════════════════════════════════════════════════════════════════════════════════
#: Ikkilanish matnidagi manzillar teskari apostrof ichida yoziladi (`_hypothesis_json`).
MANZIL_RE = re.compile(r"`([^`]+)`")


def _kod_maydoni(uzunlik: str = "3") -> dict:
    return field("Код", "standard_attribute", f"Строка({uzunlik})", length=uzunlik)


def _nom_maydoni(uzunlik: str = "30") -> dict:
    return field("Наименование", "standard_attribute", f"Строка({uzunlik})", length=uzunlik)


def hujjat_tahlili(d, *, analyzer=None) -> tuple:
    """`(graf, gipotezalar)` — SHU testlar uchun yozilgan hujjatdan, yadro oqimi bilan.

    ⚠️ `tahlil()` dan farqi: u A–O harflari bilan ishlaydi, bu esa ixtiyoriy hujjat bilan.
       Nuqsonlarning ba'zisi A–O da KO'RINMAYDI (masalan havolasiz, nomi mukammal mos
       konfiguratsiya fikstura to'plamida yo'q), shu bois ular uchun alohida hujjat kerak."""
    graf = build_graph(d)
    tahlilchi = HeuristicAnalyzer() if analyzer is None else analyzer
    return (graf, validate_analysis(tahlilchi.analyze(analyst_payload(graf)), graph=graf))


# ── NUQSON 1: chalg'ituvchi jarima KONSEPTGA BOG'LANMAGAN edi ──────────────────────────────
#: «Turlar ro'yxati» nomli UCHTA obyekt, ularning har biri O'Z konsepti uchun QONUNIY nishon.
#: ⚠️ `Справочник.ВидыЦен` — `schema.BUNDLE_TARGETS` dagi `price_types` AYNAN shu obyekt.
TURLAR_HUJJATI = doc([
    obj("Справочник.ВидыЦен", "catalog", "ВидыЦен", synonym="Виды цен", row_count="5",
        attributes=[_kod_maydoni(), _nom_maydoni()]),
    obj("Справочник.ВидыСтавокНДС", "catalog", "ВидыСтавокНДС", synonym="Виды ставок НДС",
        row_count="4", attributes=[_kod_maydoni(), _nom_maydoni()]),
    obj("ПланВидовХарактеристик.ВидыХарактеристик", "chart_of_characteristic_types",
        "ВидыХарактеристик", synonym="Виды характеристик", row_count="9",
        attributes=[_kod_maydoni(), _nom_maydoni()]),
])

#: Konsept -> shu konsept uchun QONUNIY «turlar» obyekti.
TURLAR_NISHONI = {
    "price": "Справочник.ВидыЦен",
    "tax_vat": "Справочник.ВидыСтавокНДС",
    "product_variant": "ПланВидовХарактеристик.ВидыХарактеристик",
}


def test_chalgituvchi_ishora_konseptga_bogliq():
    """`misleading_hits` KONSEPTNI so'rasin va jarimani faqat mos konseptga qo'llasin.

    ⚠️ NUQSON: sabab («tur/sinf — sotiladigan birlik emas») konseptga XOS edi, jarima esa
       23 konseptning HAMMASIGA qo'llanardi. Natijada TO'G'RI so'z jarimaga aylanardi:
       `ВидыЦен` `price` uchun -0.400 olardi, `ВидыХарактеристик` esa `product_variant`
       uchun — holbuki bu konseptlarning O'ZI turlar ro'yxati."""
    # `Виды` — `product` uchun ROSTDAN aldovchi: turkum ro'yxatini sotiladigan tovar deb
    # o'qish eng ko'p uchraydigan xato.
    assert "vidy" in {clue for clue, _ in misleading_hits("ВидыЦен", "product")}, \
        "taksonomiya ishorasi butunlay o'chib ketdi — qarshi dalil qayerdan keladi?"

    # ...lekin konseptning O'ZI turlar ro'yxati bo'lsa, bu TO'G'RI so'z.
    for konsept, nishon in sorted(TURLAR_NISHONI.items()):
        nom = nishon.split(".", 1)[1]
        assert misleading_hits(nom, konsept) == (), (
            f"{konsept}: {nom!r} uchun jarima yozildi — holbuki «tur» bu konseptda TO'G'RI "
            f"so'z, va jarima haqiqiy nishonni pasaytiradi")

    # ⚠️ Jadvalning SHAKLI ham invariant: har ishora QAYSI konseptlar uchun aldovchi ekanini
    #    AYTISHI shart. Konseptsiz yozuv «hammasiga qo'llanadi» degan jimgina qoidani
    #    qaytarib olib kelardi.
    for clue, yozuv in sorted(MISLEADING_CLUES.items()):
        sabab, konseptlar = yozuv
        assert sabab.strip(), f"{clue!r}: sababsiz qarshi dalil"
        assert konseptlar, f"{clue!r}: konsept ro'yxati bo'sh — ishora hech qachon ishlamaydi"
        assert ANY_CONCEPT in konseptlar or set(konseptlar) <= set(CONCEPTS), (
            f"{clue!r}: shartnomada yo'q konsept(lar) {sorted(set(konseptlar) - set(CONCEPTS))}")


@pytest.mark.parametrize("konsept_nomi", sorted(TURLAR_NISHONI))
def test_turlar_katalogi_tur_sozi_uchun_jarima_olmaydi(konsept_nomi: str):
    """Uchidan biri: «turlar» obyekti O'Z konseptida qarshi dalil OLMAYDI.

    ⚠️ NUQSON: `ВидыЦен` `price` uchun 0.875 dan 0.475 ga tushardi va keyin `KEEP_WINDOW`
       uni ro'yxatdan BUTUNLAY chiqarib tashlardi — ya'ni jarima `binos-1c-v1` ning haqiqiy
       nishonini (`price_types`) o'chirardi."""
    _, gipotezalar = hujjat_tahlili(TURLAR_HUJJATI)
    nishon = TURLAR_NISHONI[konsept_nomi]
    rows = [h for h in konsept(gipotezalar, konsept_nomi) if h.address == nishon]
    assert rows, (
        f"{konsept_nomi}: {nishon} nomzod bo'lmadi — bori "
        f"{sorted(manzillar(konsept(gipotezalar, konsept_nomi)))}")
    for h in rows:
        assert "chalg'ituvchi" not in qarshi_matn(h), (
            f"{konsept_nomi}: {nishon} «tur» so'zi uchun jarima oldi — {qarshi_matn(h)!r}")


# ── NUQSON 2: noaniqlik RAD ETILGAN nomzodni ham sanardi ───────────────────────────────────
def _registr(nom: str) -> dict:
    """Mahsulot nomzodiga havola qiladigan balans registri (nomi MA'NOSIZ: `R1`, `R2`)."""
    return obj(f"РегистрНакопления.{nom}", "accumulation_register", nom,
               register_kind="balance", row_count="900",
               dimensions=[field("D1", "dimension", "СправочникСсылка.Товары",
                                 refs=["Справочник.Товары"])],
               resources=[field("Q", "resource", "Число(15,3)", digits="15", scale="3")])


#: TIRIK nomzod (nomi + struktura) va RAD etiladigan nomzod (nomi mos, lekin guruh, ierarxik,
#: havolasiz) BITTA hujjatda — nuqson faqat shunday ko'rinadi.
RAD_VA_TIRIK = doc([
    obj("Справочник.Товары", "catalog", "Товары", synonym="Товары", row_count="5000",
        attributes=[_kod_maydoni("11"), _nom_maydoni("100")]),
    obj("Справочник.ТоварныеГруппы", "catalog", "ТоварныеГруппы", synonym="Товарные группы",
        hierarchical="true", row_count="42",
        attributes=[_kod_maydoni("11"), _nom_maydoni("100")]),
    _registr("R1"),
    _registr("R2"),
])

#: ⚠️ Chegaralar ATAYLAB kengaytirilgan (ikkisi ham `HeuristicAnalyzer` ning ochiq sozlamasi):
#: standart chegara bilan rad etilgan nomzod darchadan chiqib ketardi va nuqson KO'RINMASDI.
#: Kengaytirish nuqsonni YARATMAYDI — u faqat uni ko'rinadigan qiladi.
KENG_DARCHA = dict(ambiguity_delta=1.0, keep_window=1.0)


def test_rad_etilgan_nomzod_ikkilanishga_sanalmaydi():
    """RAD etilgan nomzod tanlovning TOMONI emas — u ikkilanishga sanalmaydi.

    ⚠️ NUQSON: `yaqinlar` `STATUS_REJECTED` shoxidan OLDIN hisoblanardi, ya'ni 0.0 ballli
       nomzod ham ikkilanishga tushardi. Ikki zarar: (1) artefakt O'Z-O'ZIGA QARAMA-QARSHI
       bo'lardi — «A va B orasida tanlay olmadim» deyilardi, B esa shu hujjatda RAD etilgan
       bo'lib turardi; (2) YOLG'ON AMBIGUOUS — yakka haqiqiy nomzod RAD etilgan obyekt
       tufayli `CANDIDATE` dan `AMBIGUOUS` ga tushirilardi."""
    _, gipotezalar = hujjat_tahlili(RAD_VA_TIRIK,
                                   analyzer=HeuristicAnalyzer(**KENG_DARCHA))
    joy = {h.address: h for h in konsept(gipotezalar, "product")}
    tirik = joy.get("Справочник.Товары")
    rad = joy.get("Справочник.ТоварныеГруппы")
    assert tirik is not None, f"tirik nomzod yo'qoldi — bori {sorted(joy)}"
    assert rad is not None, f"rad etiladigan nomzod yo'qoldi — bori {sorted(joy)}"
    assert rad.status == STATUS_REJECTED, (
        f"fikstura o'zgargan: {rad.address} holati {rad.status!r}, kutilgani REJECTED")

    assert tirik.status == STATUS_CANDIDATE, (
        f"YOLG'ON AMBIGUOUS: yakka tirik nomzod {tirik.address} RAD etilgan nomzod tufayli "
        f"{tirik.status!r} bo'ldi — ikkilanish matni {tirik.ambiguity}")
    assert not tirik.ambiguity, (
        f"tirik nomzodga ikkilanish yozildi: {tirik.ambiguity}")


@pytest.mark.parametrize("harf", HARFLAR)
def test_ikkilanish_rad_etilgan_manzilni_tilga_olmaydi(harf: str):
    """INVARIANT: `ambiguity` da nomi aytilgan manzil SHU artefaktda rad etilgan bo'lmasin.

    ⚠️ NEGA INVARIANT: o'z-o'ziga qarama-qarshi artefakt operatorni eng yomon yo'lga
       boshlaydi — u rad etilgan obyektni «ikkinchi variant» deb o'qiydi va uni tekshirib
       vaqt yo'qotadi, yoki tanlaydi."""
    _, gipotezalar = tahlil(harf)
    rad_etilgan = {(h.target_concept, h.address) for h in gipotezalar
                   if h.status == STATUS_REJECTED}
    for h in gipotezalar:
        if h.status != STATUS_AMBIGUOUS:
            continue
        for manzil in MANZIL_RE.findall(" ".join(h.ambiguity)):
            assert (h.target_concept, manzil) not in rad_etilgan, (
                f"{harf}: {h.address} ikkilanishida RAD etilgan {manzil!r} tilga olingan — "
                f"artefakt o'z-o'ziga qarama-qarshi")


# ── NUQSON 3: LEKSIK TO'YINISH — nom o'zi bilan eng yuqori ballga yetardi ──────────────────
#: HAVOLA UMUMAN YO'Q, REGISTR UMUMAN YO'Q — faqat kataloglar va MUKAMMAL mos nomlar.
#: ⚠️ Bunday konfiguratsiya A–O fikstura to'plamida yo'q, shu bois nuqson o'sha yerda
#:    ko'rinmasdi: struktura dalili bor joyda chegara hech narsani o'zgartirmaydi.
FAQAT_NOM = doc([
    obj("Справочник.ЕдиницыИзмерения", "catalog", "ЕдиницыИзмерения",
        synonym="Единицы измерения", row_count="14",
        attributes=[_kod_maydoni(), _nom_maydoni("20")]),
    obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="6",
        attributes=[_kod_maydoni("9"), _nom_maydoni("50")]),
])


@pytest.mark.parametrize("konsept_nomi,nishon", sorted([
    ("unit_of_measure", "Справочник.ЕдиницыИзмерения"),
    ("warehouse", "Справочник.Склады"),
]))
def test_struktura_dalilisiz_nom_mosligi_chegaradan_oshmaydi(konsept_nomi: str, nishon: str):
    """Faqat NOM mos bo'lganda ball yuqori chegaradan PAST qolsin.

    ⚠️ NUQSON: `W_NAME + W_SYNONYM + W_OBJECT_KIND + W_CARDINALITY` = 1.00, ya'ni havolasiz va
       registrsiz katalog ham 1.000 ball olardi — leksik moslik O'ZI BILAN eng yuqori
       ishonchga yetardi. `confidence_score` odam ko'rigining NAVBATINI belgilagani uchun
       zarari amaliy: tekshirilmagan taxmin navbatning boshiga chiqardi.
    ⚠️ Bu test MUAYYAN BALLNI qulflamaydi — u chegarani qulflaydi, va sababning hujjatda
       YOZILGANINI talab qiladi (qirqim jimgina bo'lmasin)."""
    _, gipotezalar = hujjat_tahlili(FAQAT_NOM)
    rows = [h for h in konsept(gipotezalar, konsept_nomi) if h.address == nishon]
    assert rows, (
        f"{konsept_nomi}: {nishon} nomzod bo'lmadi — chegara nomzodni RAD ETMASLIGI kerak, "
        f"faqat ballini pasaytiradi")
    for h in rows:
        assert "structural_link" not in dalil_turlari(h), (
            f"fikstura o'zgargan: {nishon} struktura dalili oldi — sinov ma'nosiz")
        assert h.confidence_score <= NO_STRUCTURE_CEILING, (
            f"{konsept_nomi}: {nishon} struktura dalilisiz {h.confidence_score} ball oldi — "
            f"leksik moslik O'ZI BILAN {NO_STRUCTURE_CEILING} dan yuqoriga chiqmasligi kerak")
        assert "to'yinish" in qarshi_matn(h), (
            f"{konsept_nomi}: chegara JIMGINA qirqdi — sabab qarshi dalilda yozilmagan "
            f"({qarshi_matn(h)!r})")


@pytest.mark.parametrize("harf", HARFLAR)
def test_chegara_hamma_fiksturada_kuchda(harf: str):
    """INVARIANT: struktura dalili bo'lmagan gipoteza chegaradan oshmaydi — 15 fiksturada ham.

    ⚠️ Chegara faqat maxsus hujjatda ishlashi «tuzatildi» degani emas: qoida UMUMIY bo'lishi
       kerak, aks holda keyingi fikstura uni jimgina aylanib o'tardi."""
    _, gipotezalar = tahlil(harf)
    for h in gipotezalar:
        if "structural_link" in dalil_turlari(h):
            continue
        assert h.confidence_score <= NO_STRUCTURE_CEILING, (
            f"{harf}: {h.address} ({h.target_concept}) struktura dalilisiz "
            f"{h.confidence_score} ball oldi")


# ── NUQSON 4: sanab o'tilgan qiymat manzili UMUMAN qaralmasdi ──────────────────────────────
#: ⚠️ `ai._field_addresses` sanab o'tilgan qiymat NOMINI qonuniy manzil deb e'lon qiladi,
#:    `probe` esa `enum_values` zondini beradi va `CONCEPT_OBJECT_KINDS` da `tax_vat` hamda
#:    `unit_of_measure` uchun `enum` turadi — ya'ni shartnoma sanoq qiymatida gipoteza KUTADI.
SANOQ_QIYMATLARI = doc([
    obj("Перечисление.ЕдиницыХранения", "enum", "ЕдиницыХранения",
        synonym="Единицы хранения",
        enum_values=("ЕдиницаВеса", "Килограмм", "Штука")),
])


def test_sanab_otilgan_qiymat_ham_nomzod_manzili_boladi():
    """Sanoq qiymati nomzod MANZILI bo'la olsin.

    ⚠️ NUQSON: `_pseudo_fields` faqat maydonlar va jadval bo'limlarini qaytarardi, ya'ni
       analitik `Перечисление` ichidagi konseptni HECH QACHON ko'rsata olmasdi — sanoq
       qiymatida yashagan o'lchov birligi yoki soliq stavkasi jimgina yo'qolardi, va bu
       «konfiguratsiyada yo'q» deb o'qilardi."""
    _, gipotezalar = hujjat_tahlili(SANOQ_QIYMATLARI)
    rows = konsept(gipotezalar, "unit_of_measure")
    kutilgan = "Перечисление.ЕдиницыХранения.ЕдиницаВеса"
    assert kutilgan in manzillar(rows), (
        f"sanoq qiymati nomzod manzili bo'lmadi — bori {sorted(manzillar(rows))}")

    qiymat = [h for h in rows if h.address == kutilgan][0]
    assert qiymat.candidate_field == "ЕдиницаВеса", (
        f"manzil maydon nomi bo'lib emas, boshqa shaklda yozildi: {qiymat.candidate_field!r}")
    assert qiymat.evidence and qiymat.required_confirmation
    # ⚠️ Zond ham SHARTNOMADAN: sanoq qiymatidagi gipotezani tekshirish yo'li — qiymatlar
    #    ro'yxatini o'qish.
    assert "enum_values" in {z.probe_type for z in qiymat.recommended_next_probe}, (
        f"sanoq qiymati uchun `enum_values` zondi taklif qilinmadi — "
        f"{sorted(z.probe_type for z in qiymat.recommended_next_probe)}")
