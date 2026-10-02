# -*- coding: utf-8 -*-
"""AI QATLAMINING INVARIANTLARI — eng muhim darvoza.

⚠️ NIMANI ISBOTLAYDI: tahlil kanalining SHARTNOMASI buzilganda kanal YOPILADI. Har test
   BUZILISHNI ko'rsatib isbotlaydi: «to'g'ri yo'l» o'tgani hech narsani isbotlamaydi, chunki
   fail-open darvoza ham to'g'ri yo'lni o'tkazadi.
⚠️ NIMANI ISBOTLAMAYDI: modelning (yoki `HeuristicAnalyzer` ning) topgan nomzodi TO'G'RI
   ekanini. Bu yerda birorta xarita tasdiqlanmaydi — bu fayl faqat QOIDANI qulflaydi.

QULFLANADIGAN QOIDALAR (vazifadagi tartib bilan):
  1. `VERIFIED` ni bu kanal HECH QACHON chiqarmaydi — sababi xato matnida turadi.
  2. `HUMAN_CONFIRMED` AI chiqishida RAD etiladi: u faqat operatorning ALOHIDA tasdiq
     hujjatidan keladi, model ishonchidan EMAS.
  3–4. Model obyekt ham, maydon ham O'YLAB CHIQARA OLMAYDI — nomzod grafda bo'lishi SHART.
  5. DALILSIZ xulosa yo'q: jimgina taxmin hujjatga yozilmaydi.
  6. KUCHLI dalil turini AI bera olmaydi — avtomat o'zini o'zi tasdiqlay olmaydi.
  7. `AMBIGUOUS` sababsiz, `REJECTED` qarshi dalilsiz bo'lmaydi.
  8. `confidence_score` 0..1 oralig'ida va SON (`bool` emas).
  9. Noma'lum konsept, noma'lum kalit, tushib qolgan kalit — RAD.
 10–11. Yuk FAQAT metadata: sir yo'q, biznes qatori yo'q, sanoqlar MATN, deterministik.
 12–15. `HeuristicAnalyzer` va `NullAnalyzer` chiqishi validatordan O'TADI va taqiqlangan
     darajani CHIQARMAYDI (15 fikstura uchun).
 16. Yadroda va `analyst/` da tarmoq/COM importi, API kaliti YO'Q.
 17. Zond darvozasi: noma'lum tur, grafda yo'q nishon, sababsiz zond, xom kod — RAD.
 18. `coverage()` qaralmagan konseptni TASHLAMAYDI — u `UNKNOWN` bo'lib hisobga olinadi.
 19. SHARTNOMA DARVOZALARIDAGI TUZATILGAN TESHIKLAR (har biri o'z izohi bilan):
     19.1 `allow_human_confirmed` FAQAT `human_confirmed` turini ochadi — qolgan to'rt kuchli
          turni EMAS, va u ham faqat HOLATI mos gipotezada.
     19.2 Odam dalilining `detail` ida KIM va QACHON — struktur tekshiriladi, vaqt `parse_ts` dan.
     19.3 Model yozgan `detail` redaksiya va xom kod darvozalaridan O'TADI (hujjat baytlariga
          tekshirilmagan matn tushmaydi).
     19.4 Analitikning `notes` i CHIQISHDA qoladi — kesilgan nomzod jimgina yo'qolmaydi.
     19.5 `full_name` SHAKLI qat'iy (BSL satr literalini yopib bo'lmaydi) + zond nishoni ham
          xom kod darvozasidan o'tadi.
     19.6 Zond NISHON SHARTNOMASI: `field_type_details` — MAYDON manzili, qolganlari — OBYEKT.

Fiksturalar `discovery_1c_metadata_synth` dan: 15 TO'QIMA konfiguratsiya (A–O). Ularning
birortasi haqiqiy mijoz konfiguratsiyasidan olinmagan va birortasi 1C runtime'da ishlashni
isbotlamaydi (shu faylning bosh izohiga qarang).
"""
from __future__ import annotations

import dataclasses
import math
import pathlib

import pytest

import app.services.discovery_1c as pkg
from app.services.discovery_1c import ai
from app.services.discovery_1c import confirmations as C
from app.services.discovery_1c.bundle import dumps
from app.services.discovery_1c.graph import PATH_SEP, DiscoveryGraph, build_graph
from app.services.discovery_1c.metadata import MetadataError, validate_metadata
from app.services.discovery_1c.probe import (FIELD_TARGET_PROBE_TYPES, PROBE_CATALOG,
                                             TARGET_SEP, ProbeError, ProbeRequest,
                                             assert_no_raw_code, split_field_target,
                                             validate_probe)
from app.services.discovery_1c.schema import (STRONG_EVIDENCE_KINDS, WEAK_EVIDENCE_KINDS)
from app.services.discovery_1c.analyst.heuristics import (HeuristicAnalyzer, NullAnalyzer,
                                                          RecordedAnalyzer, STATE_UNKNOWN,
                                                          coverage)
from tests import discovery_1c_metadata_synth as synth

#: Fikstura harflari — 15 ta konfiguratsiya.
HARFLAR = tuple(sorted(synth.ALL_CONFIGS))

# ── A fiksturasidagi TO'QIMA manzillar ─────────────────────────────────────────────────────
# ⚠️ Nomlar O'YLAB CHIQARILMAYDI: ular AYNAN `discovery_1c_metadata_synth` dagi A hujjatidan
#    olingan. Testda o'ylab chiqarilgan nom ishlatilsa, u grafda yo'q bo'lardi va «grafda
#    yo'q obyekt RAD etiladi» testi boshqa sababdan o'tib ketardi.
MAHSULOT = "Справочник.Товары"
MAHSULOT_MAYDONI = "Артикул"
OMBOR = "Справочник.Склады"
BARKOD_REGISTRI = "РегистрСведений.ШтрихКодыТоваров"
BARKOD_RESURSI = "ШтрихКод"
SOTUV_HUJJATI = "Документ.РеализацияТоваров"
SOTUV_BOLIMI = "Товары"

#: MAYDON MANZILLARI — `field_type_details` zondining nishoni (19.6 bo'limi).
#: ⚠️ Obyektning to'liq nomida HAM nuqta bor, ya'ni manzilni «oxirgi nuqta bo'yicha» ajratib
#:    bo'lmaydi: ajratishni GRAF hal qiladi. Shu bois ikkinchi manzil ataylab uch bo'lakli —
#:    jadval bo'limi ichidagi maydon.
MAHSULOT_MAYDON_MANZILI = f"{MAHSULOT}.{MAHSULOT_MAYDONI}"
SOTUV_BOLIM_MAYDON_MANZILI = f"{SOTUV_HUJJATI}.{SOTUV_BOLIMI}.Цена"

#: Grafda BO'LMAGAN nomlar — «model o'ylab chiqardi» holatini modellashtirish uchun.
YOQ_OBYEKT = "Справочник.BundayObyektYoq"
YOQ_MAYDON = "BundayMaydonYoq"

_GRAFLAR: dict[str, DiscoveryGraph] = {}


def graf(harf: str = "A") -> DiscoveryGraph:
    """Fikstura grafi (keshlangan).

    ⚠️ Kesh xavfsiz: graf frozen dataclass va testlar uni `dataclasses.replace` bilan
       NUSXALAYDI, joyida o'zgartirmaydi."""
    if harf not in _GRAFLAR:
        _GRAFLAR[harf] = build_graph(synth.config(harf))
    return _GRAFLAR[harf]


# ── Xom gipoteza qurish (validatordan O'TMAGAN ma'lumot) ────────────────────────────────────
def dalil(kind: str = "name_match", *, weight: str = "weak",
          detail: str = "obyekt nomi kutilgan atamaga o'xshaydi") -> dict:
    """Bitta XOM dalil lug'ati (`ai.EVIDENCE_KEYS` shaklida)."""
    return {"kind": kind, "detail": detail, "weight": weight}


#: ⚠️ Operator ISM yoki xodim ID si bilan yoziladi, aloqa ma'lumoti bilan EMAS: aks holda
#: tasdiq hujjati do'konning shaxsiy ma'lumotini olib chiqib ketardi (redaksiya darvozasi).
OPERATOR = "Sotuvchi-7 (xodim ID 41)"
#: ⚠️ Vaqt TESTNING KIRISHI, hisoblanmaydi: «hozir» ishlatilsa test determinizmdan ayrilardi.
TASDIQ_VAQTI = "2026-09-30T11:20:00+05:00"


def odam_dalili(*, prefix: str = "tasdiqladi", operator: str = OPERATOR,
                vaqt: str = TASDIQ_VAQTI, izoh: str | None = None) -> dict:
    """Tasdiq kanali yasaydigan `human_confirmed` dalili — SHAKLI `confirmations` dan.

    ⚠️ Shakl bu yerda O'YLAB CHIQARILMAYDI: `confirmations.Confirmation.who_when`
       `operator <KIM> · <QACHON>` beradi va `ai` AYNAN shuni tekshiradi. Ikki tomon bir
       shaklni bilishini `test_odam_dalili_tasdiq_kanali_bilan_bir_xil_shaklda` qulflaydi."""
    detail = f"{prefix}: {ai.HUMAN_WHO_MARKER}{operator}{ai.HUMAN_DETAIL_SEP}{vaqt}"
    if izoh:
        detail = f"{detail}{ai.HUMAN_DETAIL_SEP}{izoh}"
    return dalil(ai.HUMAN_EVIDENCE_KIND, weight="strong", detail=detail)


def zond(**almashtir) -> dict:
    """Bitta XOM zond so'rovi (`probe.PROBE_KEYS` shaklida)."""
    z = {"probe_type": "object_attributes", "target_object": MAHSULOT,
         "reason": "gipotezani tekshirish uchun maydon tarkibi kerak",
         "expected_evidence": ["name_match"]}
    z.update(almashtir)
    return z


def gipoteza(**almashtir) -> dict:
    """Shartnomaga MOS xom gipoteza; `almashtir` bilan bitta joyi buziladi.

    ⚠️ Asos ATAYLAB to'g'ri: shunda har test AYNAN bitta buzilishni o'lchaydi. Agar asos ham
       shubhali bo'lsa, rad etilish sababi noma'lum qolardi."""
    h = {
        "target_concept": "product",
        "candidate_object": MAHSULOT,
        "candidate_field": None,
        "confidence_score": 0.5,
        "evidence": [dalil()],
        "counter_evidence": [],
        "ambiguity": [],
        "required_confirmation": ["operator 1C ekranida obyekt mazmunini ko'rsin"],
        "recommended_next_probe": [zond()],
        "status": ai.STATUS_CANDIDATE,
    }
    h.update(almashtir)
    return h


def tahlil(*gipotezalar: dict) -> dict:
    """To'liq qobiqli tahlil hujjati (`ai.ANALYSIS_KEYS` shaklida)."""
    return {"analysis_version": ai.ANALYSIS_VERSION, "hypotheses": list(gipotezalar),
            "notes": ["sinov uchun qurilgan xom tahlil"]}


def rad(raw, **kw) -> str:
    """Tahlil RAD etilishini talab qiladi va xato MATNINI qaytaradi.

    ⚠️ Xato matni qaytariladi ATAYLAB: darvoza nima uchun yopilganini AYTISHI kerak. Sababsiz
       rad etish keyingi odamni kodni qaytadan o'qishga majbur qiladi."""
    with pytest.raises(ai.AnalysisError) as e:
        ai.validate_analysis(raw, graph=kw.pop("graph", graf()), **kw)
    return str(e.value)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 1 · `VERIFIED` BU KANALDA UMUMAN YO'Q
# ═══════════════════════════════════════════════════════════════════════════════════════════
def test_verified_holati_rad_etiladi():
    """`status="VERIFIED"` — RAD, va xato matnida SABAB turadi."""
    matn = rad([gipoteza(status="VERIFIED")])
    assert "VERIFIED" in matn
    assert "RAD" in matn
    # ⚠️ Sabab SHART: «noma'lum daraja» deb rad etish buzilishni oddiy imlo xatosiga
    #    o'xshatib qo'yardi, holbuki bu shartnomaning buzilishi.
    assert "kuchli dalil" in matn
    for holat in ai.AI_STATUSES:
        assert holat in matn, "xato matni ruxsat etilgan darajalarni sanashi kerak"


def test_verified_kuchli_dalil_bilan_ham_rad_etiladi():
    """Kuchli dalil «biriktirilgani» `VERIFIED` ni oqlamaydi.

    ⚠️ Bu eng xavfli urinish: model o'ziga kuchli dalil YOZIB berib darajani ko'taradi. Shu
       bois holat tekshiruvi dalil tekshiruvidan OLDIN turadi va ikkisi bir-birini almashtira
       olmaydi."""
    matn = rad([gipoteza(status="VERIFIED",
                         evidence=[dalil("human_confirmed", weight="strong",
                                         detail="model o'zini o'zi tasdiqladi")])])
    assert "VERIFIED" in matn


def test_verified_tasdiq_hujjati_rejimida_ham_rad_etiladi():
    """`allow_human_confirmed=True` ham `VERIFIED` ga yo'l bermaydi.

    ⚠️ Bayroq FAQAT odam tasdig'ini ochadi. `VERIFIED` esa discovery to'plamining darajasi va
       u bu kanalda umuman yo'q — bayroq uni ochmaydi."""
    matn = rad([gipoteza(status="VERIFIED")], allow_human_confirmed=True)
    assert "VERIFIED" in matn


def test_verified_shartnoma_lugatida_yoq():
    """Statik invariant: `VERIFIED` holatlar ro'yxatida umuman turmaydi."""
    assert ai.FORBIDDEN_STATUS == "VERIFIED"
    assert ai.FORBIDDEN_STATUS not in ai.STATUSES
    assert ai.FORBIDDEN_STATUS not in ai.AI_STATUSES
    assert set(ai.STATUSES) == {ai.STATUS_CANDIDATE, ai.STATUS_AMBIGUOUS, ai.STATUS_REJECTED,
                               ai.STATUS_HUMAN_CONFIRMED}
    assert set(ai.AI_STATUSES) == {ai.STATUS_CANDIDATE, ai.STATUS_AMBIGUOUS,
                                  ai.STATUS_REJECTED}


def test_yukdagi_shartnoma_taqiqni_ochiq_aytadi():
    """Modelga yuborilgan yuk taqiqni O'ZI aytadi.

    ⚠️ Taqiq yukda ko'rinmasa, model uni buzganida «aytilmagan edi» degan holat chiqardi.
       Darvoza baribir yopiq, lekin taqiqni aytmaslik — tekshirib bo'lmaydigan shartnoma."""
    contract = ai.analyst_payload(graf())["contract"]
    assert contract["forbidden_status"] == "VERIFIED"
    assert ai.STATUS_HUMAN_CONFIRMED not in contract["statuses"]
    # ⚠️ Modelga FAQAT kuchsiz dalil turlari taklif qilinadi: kuchli tur yukda ko'rinsa ham,
    #    validator uni baribir rad etardi — ya'ni yuk yolg'on imkoniyat ko'rsatardi.
    assert contract["allowed_evidence_kinds"] == sorted(WEAK_EVIDENCE_KINDS)
    for kind in STRONG_EVIDENCE_KINDS:
        assert kind not in contract["allowed_evidence_kinds"]


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 2 · `HUMAN_CONFIRMED` FAQAT OPERATORNING ALOHIDA TASDIQ HUJJATIDAN KELADI
# ═══════════════════════════════════════════════════════════════════════════════════════════
def test_human_confirmed_ai_chiqishida_rad_etiladi():
    matn = rad([gipoteza(status=ai.STATUS_HUMAN_CONFIRMED,
                         evidence=[dalil("human_confirmed", weight="strong",
                                         detail="operator ko'rdi")])])
    assert ai.STATUS_HUMAN_CONFIRMED in matn
    assert "tasdiq hujjatidan" in matn


def test_human_confirmed_kuchsiz_dalil_bilan_ham_rad_etiladi():
    """Rad etish sababi — HOLAT, dalilning turi emas.

    ⚠️ Farq muhim: agar kanal faqat «kuchli dalil yo'q» deb rad etsa, model kuchsiz dalil
       bilan `HUMAN_CONFIRMED` yozib qutulib ketardi."""
    matn = rad([gipoteza(status=ai.STATUS_HUMAN_CONFIRMED)])
    assert ai.STATUS_HUMAN_CONFIRMED in matn


def test_ishonch_bali_bir_bolsa_ham_human_confirmed_bermaydi():
    """`confidence_score=1.0` odam ko'rigining o'rnini BOSMAYDI."""
    matn = rad([gipoteza(status=ai.STATUS_HUMAN_CONFIRMED, confidence_score=1.0)])
    assert ai.STATUS_HUMAN_CONFIRMED in matn
    assert "ishonchidan" in matn


def test_human_confirmed_faqat_tasdiq_rejimida_otadi():
    """Bayroq CHAQIRUVCHI kodda yoqiladi — va faqat shu yo'l `HUMAN_CONFIRMED` ni ochadi."""
    hyps = ai.validate_analysis(
        [gipoteza(status=ai.STATUS_HUMAN_CONFIRMED, evidence=[odam_dalili()])],
        graph=graf(), allow_human_confirmed=True)
    assert [h.status for h in hyps] == [ai.STATUS_HUMAN_CONFIRMED]


def test_human_confirmed_kim_va_qachon_dalilini_talab_qiladi():
    """Tasdiq rejimida `human_confirmed` dalili SHART — VA uning `detail` ida KIM va QACHON
    ko'rgani YOZILGAN bo'lishi kerak.

    ⚠️ BU TEST ILGARI O'ZI QULFLAMAGAN NARSANI QULFLAGAN DEB KO'RSATARDI: nomi va docstringi
       «kim va qachon» deyar, tekshiruvi esa FAQAT «dalil umuman yo'q» holatini o'lchardi.
       Shu bois `detail='tasdiqlandi'` (operator YO'Q, vaqt YO'Q) jimgina QABUL qilinardi.
       Yashil turgan, lekin hech narsa qulflamaydigan test eng qimmat nosozlik: u teshikni
       yopiq deb ishontiradi va keyingi odam o'sha joyga qaramaydi."""
    matn = rad([gipoteza(status=ai.STATUS_HUMAN_CONFIRMED)], allow_human_confirmed=True)
    assert "human_confirmed" in matn
    assert "kim va qachon" in matn


def test_bayroq_gipoteza_ichidan_kelmaydi():
    """Model o'zini «odam tasdiqladi» deb E'LON QILA OLMAYDI.

    ⚠️ Gipoteza ichiga qo'yilgan bayroq — noma'lum kalit, ya'ni RAD. Shu bois bayroqni model
       chiqishi bilan yoqib bo'lmaydi: uni faqat tasdiq hujjatini o'qiyotgan kod beradi."""
    matn = rad([gipoteza(allow_human_confirmed=True)])
    assert "noma'lum kalit" in matn
    assert "allow_human_confirmed" in matn


@pytest.mark.parametrize("holat", ["MAYBE", "candidate", "Verified", "OK", " "])
def test_notanish_holat_rad_etiladi(holat: str):
    """Noma'lum daraja JIMGINA `CANDIDATE` ga tushirilmaydi — RAD etiladi."""
    matn = rad([gipoteza(status=holat)])
    assert "status" in matn


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 3–4 · MODEL OBYEKT HAM, MAYDON HAM O'YLAB CHIQARA OLMAYDI
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("nom", [YOQ_OBYEKT, "Справочник.Товар", "Товары", MAHSULOT.lower()])
def test_grafda_yoq_obyekt_rad_etiladi(nom: str):
    """Nomzod obyekt INVENTARIZATSIYA hujjatidan kelishi shart.

    ⚠️ Parametrlar ataylab «yaqin» nomlar: birlik shakl, prefiksi tushirilgan nom va kichik
       harfli nom. Shundagina taqqoslash AYNAN ekani ko'rinadi — «o'xshash» nom o'tmaydi."""
    matn = rad([gipoteza(candidate_object=nom)])
    assert "candidate_object" in matn
    assert "O'YLAB CHIQARA OLMAYDI" in matn


def test_obyektda_yoq_maydon_rad_etiladi():
    matn = rad([gipoteza(candidate_field=YOQ_MAYDON)])
    assert "candidate_field" in matn
    assert "O'YLAB CHIQARILMAYDI" in matn


def test_boshqa_obyektning_maydoni_rad_etiladi():
    """Maydon AYNAN shu obyektda bo'lishi kerak.

    ⚠️ `ШтрихКод` grafda BOR, lekin barkod registrida. Uni mahsulot katalogiga yozib qo'yish —
       mavjud nomni boshqa obyektga ko'chirish, ya'ni eng sezilmas xato turi."""
    assert BARKOD_RESURSI in {f.path for f in graf().fields_of(BARKOD_REGISTRI)}
    matn = rad([gipoteza(target_concept="barcode", candidate_object=MAHSULOT,
                         candidate_field=BARKOD_RESURSI)])
    assert "candidate_field" in matn


def test_jadval_bolimi_va_uning_maydoni_qonuniy_manzil():
    """Bo'lim NOMI ham, bo'lim ichidagi maydon ham qonuniy nomzod manzili.

    ⚠️ Bularni maydon darajasiga majburlash modelni noto'g'ri aniqlikka undardi: qator
       darajasidagi konsept ko'pincha aynan bo'limda yashaydi."""
    hyps = ai.validate_analysis(
        tahlil(gipoteza(target_concept="sale_document", candidate_object=SOTUV_HUJJATI,
                        candidate_field=SOTUV_BOLIMI,
                        recommended_next_probe=[zond(target_object=SOTUV_HUJJATI,
                                                     probe_type="tabular_sections")]),
               gipoteza(target_concept="price", candidate_object=SOTUV_HUJJATI,
                        candidate_field=f"{SOTUV_BOLIMI}.Цена",
                        # ⚠️ Maydon zondining nishoni MAYDON MANZILI (19.6 bo'limiga qarang):
                        #    obyekt nomi berilsa zond bajaruvchi tomonda xato qaytarardi.
                        recommended_next_probe=[zond(
                            target_object=SOTUV_BOLIM_MAYDON_MANZILI,
                            probe_type="field_type_details")])),
        graph=graf())
    assert [h.address for h in hyps] == [f"{SOTUV_HUJJATI}.{SOTUV_BOLIMI}.Цена",
                                         f"{SOTUV_HUJJATI}.{SOTUV_BOLIMI}"]


def test_sanab_otilgan_qiymat_qonuniy_manzil():
    """Sanab o'tilgan qiymat NOMI ham manzil bo'la oladi.

    ⚠️ Fiksturalarda sanab o'tilgan qiymatli obyekt yo'q, shu bois u SHU YERDA quriladi —
       `synth` yasovchilari bilan, ya'ni hujjat baribir `validate_metadata` dan o'tadi."""
    hujjat = synth.doc([
        synth.obj("Перечисление.HolatTurlari", "enum", "HolatTurlari",
                  synonym="Holat turlari", enum_values=("Yangi", "Yopilgan")),
    ])
    g = build_graph(hujjat)
    hyps = ai.validate_analysis(
        [gipoteza(target_concept="sale_document", candidate_object="Перечисление.HolatTurlari",
                  candidate_field="Yopilgan",
                  recommended_next_probe=[zond(target_object="Перечисление.HolatTurlari",
                                               probe_type="enum_values")])],
        graph=g)
    assert hyps[0].candidate_field == "Yopilgan"


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 5 · JIMGINA TAXMIN YO'Q — DALILSIZ XULOSA YOZILMAYDI
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("holat", [ai.STATUS_CANDIDATE, ai.STATUS_AMBIGUOUS])
def test_dalilsiz_gipoteza_rad_etiladi(holat: str):
    matn = rad([gipoteza(status=holat, evidence=[], ambiguity=["ikki nomzod bali yaqin"])])
    assert "dalilsiz" in matn
    assert "taxmin" in matn


@pytest.mark.parametrize("holat", [ai.STATUS_CANDIDATE, ai.STATUS_AMBIGUOUS])
def test_tasdiq_yoli_korsatilmagan_gipoteza_rad_etiladi(holat: str):
    """`required_confirmation` bo'sh — gipoteza tekshirib bo'lmaydigan, ya'ni abadiy CANDIDATE."""
    matn = rad([gipoteza(status=holat, required_confirmation=[],
                         ambiguity=["ikki nomzod bali yaqin"])])
    assert "required_confirmation" in matn


def test_nom_mosligi_ozi_bilan_tasdiq_bermaydi():
    """5-qoida: leksik moslik KUCHSIZ dalil va u darajani ko'tara olmaydi."""
    assert "name_match" in WEAK_EVIDENCE_KINDS
    assert "synonym_match" in WEAK_EVIDENCE_KINDS
    assert not set(WEAK_EVIDENCE_KINDS) & set(STRONG_EVIDENCE_KINDS)
    # Faqat nom mosligi bilan kelgan gipoteza CANDIDATE bo'lib qoladi …
    hyps = ai.validate_analysis([gipoteza(evidence=[dalil("name_match"),
                                                    dalil("synonym_match")])], graph=graf())
    assert hyps[0].status == ai.STATUS_CANDIDATE
    # … va undan yuqorisiga ko'tarilishga urinish RAD etiladi.
    assert "VERIFIED" in rad([gipoteza(status="VERIFIED", evidence=[dalil("name_match")])])
    # Har 15 fiksturada ham leksik moslik YETARLI deb hisoblanmaydi.
    for harf in HARFLAR:
        assert synth.EXPECTED[harf]["leksik_yetarli"] is False


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 6 · AI KUCHLI DALIL BERA OLMAYDI
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kind", sorted(STRONG_EVIDENCE_KINDS))
@pytest.mark.parametrize("joy", ["evidence", "counter_evidence"])
def test_ai_kuchli_dalil_bera_olmaydi(kind: str, joy: str):
    """Kuchli dalil AI kanalida BO'LMAYDI — dalilda ham, QARSHI dalilda ham.

    ⚠️ Qarshi dalil ham tekshiriladi: «arifmetik isbot bilan rad etdim» degan avtomat ham
       o'zini o'zi tasdiqlagan bo'lardi, faqat teskari yo'nalishda."""
    h = gipoteza(status=ai.STATUS_REJECTED,
                 counter_evidence=[dalil("cardinality", detail="qatorlar soni mos emas")])
    h[joy] = [dalil(kind, weight="strong", detail="avtomat shunday dedi")]
    matn = rad([h])
    assert kind in matn
    assert joy in matn
    # ⚠️ Sabab TURGA qarab ikki xil, va bu ataylab: `human_confirmed` ni ODAM kanali bera
    #    oladi (shu bois «AI chiqishida bo'lmaydi»), qolgan to'rt turni esa HECH QANDAY kanal
    #    bermaydi — ular kelajakdagi alohida qadamlarning natijasi. Bitta umumiy matn bu
    #    farqni yashirardi va darvozani tekshirib bo'lmasdi.
    if kind == ai.HUMAN_EVIDENCE_KIND:
        assert "KUCHLI dalil turi AI chiqishida BO'LMAYDI" in matn
    else:
        assert "HECH QANDAY kanal chiqarmaydi" in matn


@pytest.mark.parametrize("kind,vazn", [("human_confirmed", "weak"), ("arithmetic_proof", "weak"),
                                       ("name_match", "strong"), ("cardinality", "strong")])
def test_dalil_vazni_turidan_kelib_chiqadi(kind: str, vazn: str):
    """Vazn E'LONDAN emas, dalil TURIDAN kelib chiqadi.

    ⚠️ `weak` deb e'lon qilingan kuchli tur — darvozani chetlab o'tishga urinish, va u
       ko'rinib turishi kerak. Teskarisi ham xato: kuchsiz turni `strong` deb e'lon qilish."""
    matn = rad([gipoteza(evidence=[dalil(kind, weight=vazn)])])
    assert "vazn dalil TURIDAN kelib chiqadi" in matn


@pytest.mark.parametrize("kind", ["proof", "gut_feeling", "", "NAME_MATCH"])
def test_notanish_dalil_turi_rad_etiladi(kind: str):
    matn = rad([gipoteza(evidence=[dalil(kind)])])
    assert "kind" in matn


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 7 · `AMBIGUOUS` SABABSIZ, `REJECTED` QARSHI DALILSIZ BO'LMAYDI
# ═══════════════════════════════════════════════════════════════════════════════════════════
def test_ambiguous_ikkilanish_sababini_talab_qiladi():
    matn = rad([gipoteza(status=ai.STATUS_AMBIGUOUS, ambiguity=[])])
    assert "ambiguity" in matn
    assert "tanlovdan qochish" in matn


def test_rejected_qarshi_dalilni_talab_qiladi():
    matn = rad([gipoteza(status=ai.STATUS_REJECTED, counter_evidence=[])])
    assert "counter_evidence" in matn
    assert "sababsiz rad etish" in matn


def test_ambiguous_va_rejected_togri_shaklda_otadi():
    """Sabab va qarshi dalil bor bo'lsa — o'tadi. (Darvoza YOPIQ emas, TANLAB yopiladi.)"""
    hyps = ai.validate_analysis(
        tahlil(gipoteza(status=ai.STATUS_AMBIGUOUS,
                        ambiguity=["ikki nomzodning bali yaqin — avtomat tanlov qilinmadi"]),
               gipoteza(candidate_object=OMBOR, status=ai.STATUS_REJECTED,
                        counter_evidence=[dalil("cardinality",
                                                detail="6 qator — mahsulot katalogi uchun kam")],
                        recommended_next_probe=[zond(target_object=OMBOR)])),
        graph=graf())
    assert {h.status for h in hyps} == {ai.STATUS_AMBIGUOUS, ai.STATUS_REJECTED}


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 8 · `confidence_score` — 0..1 ORALIG'IDAGI SON
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("ball", [-0.001, -1.0, 1.001, 2.0,
                                  float("nan"), float("inf"), float("-inf"),
                                  True, False, "0.5", None, [0.5]])
def test_ishonch_bali_oraliqdan_tashqarida_rad_etiladi(ball):
    """⚠️ `bool` ham RAD: Python'da `True == 1`, ya'ni u jimgina «to'liq ishonch» bo'lardi.
       Matn ham RAD: o'lchov bu yerda MATN emas (sanoqlardan farqi izohda tushuntirilgan)."""
    matn = rad([gipoteza(confidence_score=ball)])
    assert "confidence_score" in matn


@pytest.mark.parametrize("kirish,kutilgan", [(0, 0.0), (1, 1.0), (0.0, 0.0), (1.0, 1.0),
                                             (0.1234, 0.123), (0.9995, 1.0)])
def test_ishonch_bali_chegarada_qabul_qilinadi_va_yaxlitlanadi(kirish, kutilgan):
    """⚠️ 3 kasr xonaga yaxlitlash — DETERMINIZM uchun: modelning uzun kasri bayt darajasida
       farqlanadigan hujjat berardi, ma'no esa o'zgarmasdi."""
    hyps = ai.validate_analysis([gipoteza(confidence_score=kirish)], graph=graf())
    assert hyps[0].confidence_score == pytest.approx(kutilgan)
    assert not isinstance(hyps[0].confidence_score, bool)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 9 · NOMA'LUM KONSEPT, NOMA'LUM KALIT, TUSHIB QOLGAN KALIT
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("konsept", ["mahsulot", "PRODUCT", "tovar", "", "products"])
def test_notanish_konsept_rad_etiladi(konsept: str):
    """Konsept ID lari BIZNING shartnomamiz nomlari — ular o'ylab chiqarilmaydi."""
    matn = rad([gipoteza(target_concept=konsept)])
    assert "target_concept" in matn


@pytest.mark.parametrize("kalit", ["mapping", "verified", "confidence", "notes"])
def test_notanish_kalit_rad_etiladi(kalit: str):
    """Model «qo'shimcha maydon» bilan shartnomani KENGAYTIRA olmaydi."""
    matn = rad([gipoteza(**{kalit: "x"})])
    assert "noma'lum kalit" in matn
    assert kalit in matn


@pytest.mark.parametrize("kalit", sorted(ai.HYPOTHESIS_KEYS))
def test_kalit_tushib_qolsa_rad_etiladi(kalit: str):
    """Tushib qolgan kalit ham RAD: `null` bilan «bo'sh» yozish va kalitni umuman
    yozmaslik bir xil narsa emas."""
    matn = rad([{k: v for k, v in gipoteza().items() if k != kalit}])
    assert "tushib qolgan" in matn
    assert kalit in matn


def test_qobiq_versiyasi_va_izohlari_tekshiriladi():
    """Qobiq ixtiyoriy, lekin berilgan bo'lsa QAT'IY tekshiriladi."""
    assert "analysis_version" in rad({"analysis_version": "binos-1c-ai-analysis-v2",
                                      "hypotheses": [gipoteza()], "notes": []})
    assert "notes" in rad({"analysis_version": ai.ANALYSIS_VERSION,
                           "hypotheses": [gipoteza()]})
    # Qobiqsiz (shunchaki ro'yxat) ham, qobiq bilan ham ichki tekshiruv AYNAN bir xil qat'iy.
    assert "VERIFIED" in rad(tahlil(gipoteza(status="VERIFIED")))


def test_takror_manzil_rad_etiladi():
    """Bir manzil uchun ikki gipoteza — RAD: ikkilanish `AMBIGUOUS` bilan aytiladi."""
    matn = rad([gipoteza(), gipoteza(confidence_score=0.7)])
    assert "bir manzil uchun bir nechta gipoteza" in matn
    assert "AMBIGUOUS" in matn


def test_konsept_boyicha_gipoteza_chegarasi():
    """Har obyektni nomzod qilib sanash TAHLIL EMAS — chegara bor."""
    # ⚠️ Manzillar TAKRORSIZ bo'lishi kerak: takror manzil boshqa qoida bilan rad etilardi va
    #    chegara tekshirilmay qolardi. Obyektning O'ZI ham manzil, shu bois `None` qo'shiladi.
    manzillar = [f.path for f in graf().fields_of(MAHSULOT)] + [None]
    assert len(manzillar) > ai.MAX_HYPOTHESES_PER_CONCEPT
    ortiqcha = [gipoteza(target_concept="barcode", candidate_field=p, evidence=[dalil()])
                for p in manzillar[:ai.MAX_HYPOTHESES_PER_CONCEPT + 1]]
    matn = rad(ortiqcha)
    assert "chegara" in matn


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 10 · MAXFIYLIK — YUKDA SIR BO'LMAYDI (fail-closed)
# ═══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Bular HAQIQIY sir EMAS — `redact.VALUE_PATTERNS` ni qo'zg'atadigan SHAKLLAR. Ular
#: obyekt izohiga tushishi eng ehtimolli joy: yig'uvchi izohni 1C dan XOM oladi, operator esa
#: o'sha izohga ulanish satrini yoki parolni yozib qo'ygan bo'lishi mumkin.
SIR_SHAKLLARI = [
    ("пароль: 12345", "kirill parol"),
    ("parol: 12345", "LOTIN parol"),
    ("password: hunter2", "inglizcha parol"),
    ("passwd=hunter2", "qisqartma passwd"),
    ("pwd = hunter2", "qisqartma pwd"),
    ("Usr=operator;Pwd=12345", "1C ulanish satri (foydalanuvchi va parol)"),
    ("srvr=srv-kassa;ref=baza", "1C ulanish satri (server va baza)"),
    ("postgres://operator:sirli@srv/baza", "URL ichidagi login:parol"),
    ("operator@dokon.example.com", "e-mail manzili"),
    ("+998 90 123 45 67", "telefon raqami"),
]


def sirli_graf(matn: str, joy: str) -> DiscoveryGraph:
    """Grafning nusxasi, ichiga sir shakli qo'yilgan.

    ⚠️ Graf `dataclasses.replace` bilan quriladi, hujjatdan EMAS: inventarizatsiya
       validatori sirni O'ZI rad etadi (`CONFIG_SECRET_LEAK`), ya'ni hujjat orqali bu yuk
       darvozasiga umuman yetib borilmasdi. Bu test AYNAN yuk darvozasini sinaydi."""
    o = graf().objects[0]
    if joy == "field_synonym":
        f0 = dataclasses.replace(o.fields[0], synonym=matn)
        o = dataclasses.replace(o, fields=(f0,) + o.fields[1:])
    else:
        o = dataclasses.replace(o, **{joy: matn})
    return dataclasses.replace(graf(), objects=(o,) + graf().objects[1:])


@pytest.mark.parametrize("matn,nima", SIR_SHAKLLARI, ids=[n for _m, n in SIR_SHAKLLARI])
def test_sir_qoshilgan_grafdan_yuk_qurilmaydi(matn: str, nima: str):
    """Sir shubhasi bo'lsa HECH NARSA YUBORILMAYDI (fail-closed).

    ⚠️ Uch joy sinaladi: obyekt izohi, obyekt sinonimi va MAYDON sinonimi. Bittasini qarab
       qolgan ikkitasini qaramaslik — «tekshirdim» degan yolg'on xotirjamlik."""
    for joy in ("comment", "synonym", "field_synonym"):
        with pytest.raises(ai.AnalysisError) as e:
            ai.analyst_payload(sirli_graf(matn, joy))
        assert "sir shubhasi" in str(e.value), f"{joy}: {nima}"
        assert "HECH NARSA YUBORILMAYDI" in str(e.value)


def test_lotin_parol_alohida_tutiladi():
    """⚠️ ALOHIDA TEST: lotin `parol` ilgari TOPILGAN HAQIQIY TESHIK edi.

    Loyihada operator hujjatlari ham, yozishmalar ham lotin o'zbekchada. Faqat kirill
    `парол` va inglizcha shakl qamrab olinganda operator O'Z TILIDA yozgan parol
    redaksiyadan JIMGINA o'tib ketardi. Shu bois teshik o'z testi bilan qulflanadi."""
    for matn in ("parol: 12345", "Parol = 12345", "PAROLI:1234", "parolim — 1234"):
        with pytest.raises(ai.AnalysisError):
            ai.analyst_payload(sirli_graf(matn, "comment"))


def test_sir_xato_matnida_qiymat_korsatilmaydi():
    """⚠️ Xato matni sirning O'ZINI takrorlamaydi: aks holda darvoza sirni jurnal orqali
       tarqatgan bo'lardi — ya'ni tutgan narsasini o'zi chiqarib yuborardi."""
    sir = "Usr=operator;Pwd=juda-maxfiy-qiymat"
    with pytest.raises(ai.AnalysisError) as e:
        ai.analyst_payload(sirli_graf(sir, "comment"))
    assert "juda-maxfiy-qiymat" not in str(e.value)
    assert sir not in str(e.value)


#: ERKIN MATN ichidagi sir shakllari — sir KALIT NOMIDA emas, QIYMAT ichida kelgani.
#: ⚠️ NEGA ALOHIDA RO'YXAT: ilgari `SECRET_KEY_RE` 14 ta sir so'zini bilardi, erkin matn
#:    naqshi esa faqat parol so'zlarini. Ya'ni AYNI BIR sir `{"token": "..."}` shaklida RAD
#:    etilib, `"izoh: token: ..."` shaklida jimgina o'tib ketardi. Bu asimmetriya HAQIQIY
#:    teshik edi va `redact.py` da `inline_secret_key_value` bilan yopilgan; shu bois u
#:    qayta ochilmasligi uchun o'z ro'yxati bilan qulflanadi.
ERKIN_MATN_SIR_SHAKLLARI = [
    ("Пароль базы 12345", "kirill parol, AJRATUVCHISIZ (gap ichida)"),
    ("token: abc123XYZ", "token erkin matnda"),
    ("api_key=sk-12345", "api_key erkin matnda"),
    ("secret: hunter2hunter2", "secret erkin matnda"),
    ("apikey = zzz999", "apikey (pastki chiziqsiz)"),
    ("credentials: aaa111", "credentials"),
    ("private_key: xxx", "private_key"),
    ("conn_str = yyy", "conn_str"),
    ("connection_string: File=D", "connection_string"),
    ("rdp: kassa-server", "rdp — IP siz ham"),
    ("anydesk 123 456 789", "AnyDesk ID"),
    ("AnyDesk: 123 456 789", "AnyDesk ID, ajratuvchi bilan"),
    ("teamviewer 999 888 777", "TeamViewer ID"),
    ("TeamViewer ID 999 888 777", "TeamViewer ID, `ID` so'zi bilan"),
    ("тимвьювер 111 222 333", "TeamViewer KIRILL transliteratsiyada"),
]


@pytest.mark.parametrize("matn,nima", ERKIN_MATN_SIR_SHAKLLARI,
                         ids=[n for _m, n in ERKIN_MATN_SIR_SHAKLLARI])
def test_erkin_matn_ichidagi_sir_ham_tutiladi(matn: str, nima: str):
    """Sir KALIT NOMIDA tutilib, xuddi shu so'z QIYMAT ichida o'tib ketmasligi kerak.

    ⚠️ Yadroning bosh izohi buni ochiq yozadi: «Sir topilsa — to'plam RAD (ulanish satri,
       parol, token, AnyDesk/RDP identifikatori)». Ilgari bu FAQAT kalit nomi uchun
       bajarilardi — test aynan shu asimmetriya yopilganini qulflaydi.
    ⚠️ Uch joy sinaladi (izoh, sinonim, MAYDON sinonimi): yig'uvchi bu maydonlarni 1C dan XOM
       oladi, ya'ni operator sirni uchalasiga ham yozib qo'ygan bo'lishi mumkin. Bittasini
       qarab qolgan ikkitasini qaramaslik — «tekshirdim» degan yolg'on xotirjamlik."""
    for joy in ("comment", "synonym", "field_synonym"):
        with pytest.raises(ai.AnalysisError) as e:
            ai.analyst_payload(sirli_graf(matn, joy))
        assert "sir shubhasi" in str(e.value), f"{joy}: {nima}"
        # ⚠️ Xato matni sirning O'ZINI takrorlamasin — aks holda darvoza tutgan narsasini
        #    jurnal orqali o'zi chiqarib yuborardi.
        assert matn not in str(e.value), f"{joy}: xato matni sirni takrorladi ({nima})"


#: `redact` QAMRAMAYDIGAN, ya'ni yukka VERBATIM tushadigan shakllar.
#: ⚠️ NEGA BU RO'YXAT BOR: `analyst_payload` docstringi ilgari «NIMA YO'Q» ro'yxatida
#:    mijoz/xodim ma'lumoti, narx va qoldiqni sanardi — GO'YO kod ularni to'sadi. Aslida
#:    to'smaydi: `comment`/`synonym`/`errors` 1C dan XOM keladi va odam yozgan HAR QANDAY
#:    matn naqshga tushmasa o'tib ketadi. Da'vo endi haqiqatga moslangan; bu test esa
#:    da'voning YOLG'ON shaklda qaytib kelishini qulflaydi.
#: ⚠️ Bu test «yaxshi» holatni emas, CHEKLOVNI hujjatlashtiradi. Biror shakl kelajakda
#:    QAMRALSA — test yiqiladi va tuzatgan odam docstringdagi da'voni ham yangilashi kerak.
QAMRALMAGAN_SHAKLLAR = [
    ("10.0.0.5", "YALANGOCH IP — portsiz, kontekstsiz"),
    ("baza 1.0.0.1 versiyasi", "versiya shakli — IP dan farqlanmaydi"),
    ("SRV-KASSA", "server/kompyuter NOMI"),
    ("mijoz Aliyev Vali", "MIJOZ ismi izohda"),
    ("kassir Gulnora ishlagan", "XODIM ismi izohda"),
    ("narx 15000 som", "NARX izohda"),
    ("qoldiq 42 dona", "QOLDIQ izohda"),
]


@pytest.mark.parametrize("matn,nima", QAMRALMAGAN_SHAKLLAR,
                         ids=[n for _m, n in QAMRALMAGAN_SHAKLLAR])
def test_qamralmagan_shakllar_yukka_verbatim_tushadi(matn: str, nima: str):
    """CHEKLOV HUJJATI: `redact` bu shakllarni TUTMAYDI, ya'ni ular provayderga ketadi.

    ⚠️ Yalang'och IP va versiya shakli ATAYLAB qamralmagan (`redact.py` ni ko'ring):
       konfiguratsiya versiyasi shaklan AYNAN IP ga o'xshaydi va u HAR BIR eksportda bor,
       ya'ni kontekstsiz naqsh har bir to'plamni rad etib darvozani o'chirishga olib kelardi.
    ⚠️ Ism/narx/qoldiq esa naqsh bilan UMUMAN ajratib bo'lmaydi: «Aliyev Vali» tovar nomidan
       shaklan farq qilmaydi. Kod uni to'smaydi — shu bois docstringda «yo'q» deb YOZILMAYDI.
       Haqiqiy himoya boshqa joyda: yukka biznes QATORI umuman kirmaydi (pastdagi
       `test_yuk_faqat_metadata_kalitlarini_tashiydi`), operator izohi esa kiradi."""
    yuk = ai.analyst_payload(sirli_graf(matn, "comment"))
    assert matn in dumps(yuk), f"{nima}: endi qamraldi — docstring da'vosini YANGILANG"


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 11 · YUK FAQAT METADATA VA DETERMINISTIK
# ═══════════════════════════════════════════════════════════════════════════════════════════
def barglar(node, path: str = ""):
    """Yukning barcha barg qiymatlari: (yo'l, qiymat)."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from barglar(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from barglar(v, f"{path}[{i}]")
    else:
        yield path, node


@pytest.mark.parametrize("harf", HARFLAR)
def test_yukda_son_yoki_bool_yoq(harf: str):
    """7-qoida: sanoqlar MATN. ⚠️ `0000123` soni `123` bo'lib qolardi va PLU yo'qolardi.

    Tekshiruv `graph` bo'limi bo'yicha: `contract.probe_catalog` dagi `read_only: True` —
    KATALOGNING xossasi, ya'ni ataylab mantiqiy qiymat."""
    p = ai.analyst_payload(graf(harf))
    sonlar = [(yol, v) for yol, v in barglar(p["graph"])
              if isinstance(v, (int, float, bool))]
    assert not sonlar, f"yukda JSON soni yoki bool bor: {sonlar[:5]}"
    for yol, v in barglar(p["graph"]):
        assert v is None or isinstance(v, str), f"{yol}: {type(v).__name__}"


def test_yuk_faqat_metadata_kalitlarini_tashiydi():
    """⚠️ Yukda biznes qatori uchun JOY YO'Q: obyekt va maydon lug'atlarining kalitlari
       AYNAN shu ro'yxat. Yangi kalit qo'shilsa shu test yiqiladi va qo'shgan odam
       «bu qator emasmi?» degan savolga javob berishi kerak bo'ladi."""
    p = ai.analyst_payload(graf())
    assert sorted(p) == ["contract", "graph", "payload_version"]
    assert p["payload_version"] == ai.AI_PAYLOAD_VERSION
    assert sorted(p["graph"]) == ["objects", "relationships", "stats", "unresolved_references"]
    assert sorted(p["graph"]["objects"][0]) == [
        "comment", "enum_values", "errors", "fields", "full_name", "hierarchical", "kind",
        "name", "periodicity", "predefined", "register_kind", "row_count", "synonym",
        "tabular_sections"]
    assert sorted(p["graph"]["objects"][0]["fields"][0]) == [
        "kind", "name", "numeric_digits", "numeric_scale", "path", "reference_targets",
        "string_length", "synonym", "type"]


def test_yukda_vaqt_tamgasi_yoq():
    """9-qoida: vaqt O'YLAB CHIQARILMAYDI va shartnomada umuman yo'q.

    ⚠️ Hujjatda vaqt BOR (`collected_at`), yukda esa YO'Q: yuk uni tashimasa, model ham,
       ulagich ham vaqtni «hisoblab» qo'yishga urinmaydi."""
    matn = dumps(ai.analyst_payload(graf()))
    assert "collected_at" not in matn
    assert synth.COLLECTED_AT not in matn


@pytest.mark.parametrize("harf", HARFLAR)
def test_yuk_deterministik(harf: str):
    """Bir xil hujjat -> AYNAN bir xil bayt (mustaqil qurilgan ikki grafdan)."""
    a = dumps(ai.analyst_payload(build_graph(synth.config(harf))))
    b = dumps(ai.analyst_payload(build_graph(synth.config(harf))))
    assert a == b


def test_yuk_notanish_konsept_bilan_qurilmaydi():
    """Konsept ro'yxati KOD o'zgarishi bilan kengayadi, CHAQIRUV bilan emas."""
    with pytest.raises(ai.AnalysisError) as e:
        ai.analyst_payload(graf(), concepts=("product", "mahsulot"))
    assert "noma'lum konsept" in str(e.value)
    with pytest.raises(ai.AnalysisError):
        ai.analyst_payload(graf(), concepts=())


@pytest.mark.parametrize("notogri", [None, {}, "graf", synth.config("A")])
def test_yuk_grafni_talab_qiladi(notogri):
    """Tekshirilmagan hujjatdan yuk qurilmaydi — kirish AYNAN `DiscoveryGraph` bo'lishi kerak."""
    with pytest.raises(ai.AnalysisError):
        ai.analyst_payload(notogri)
    with pytest.raises(ai.AnalysisError):
        ai.validate_analysis([gipoteza()], graph=notogri)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 12–14 · `HeuristicAnalyzer` — 15 FIKSTURA
# ═══════════════════════════════════════════════════════════════════════════════════════════
def heuristik(harf: str):
    """Analitikni yadro shartnomasi bo'yicha ishlatadi: yuk -> tahlil -> XOM natija."""
    g = graf(harf)
    return g, HeuristicAnalyzer().analyze(ai.analyst_payload(g))


@pytest.mark.parametrize("harf", HARFLAR)
def test_heuristik_chiqishi_validatordan_otadi(harf: str):
    """⚠️ Analitikning IMTIYOZI YO'Q: uning ham natijasi ISHONMASDAN tekshiriladi."""
    g, raw = heuristik(harf)
    hyps = ai.validate_analysis(raw, graph=g)
    assert len(hyps) == len(raw["hypotheses"])
    # Har gipotezada dalil BOR: musbat omilsiz nomzod umuman chiqmasligi kerak.
    for h in hyps:
        assert h.evidence, f"{harf}: dalilsiz gipoteza chiqdi — {h.address}"
        assert h.required_confirmation, f"{harf}: tasdiq yo'li yo'q — {h.address}"


def test_heuristik_eng_qulay_fiksturada_nomzod_topadi():
    """A — eng qulay holat: nom, tuzilma va munosabatlar bir yo'nalishda.

    ⚠️ Fikstura izohi buni ochiq yozadi: «Talqin qatlami shu yerda nomzod TOPMASA, qolgan
       14 tasida umuman umid yo'q». Ya'ni bu test heuristika UMUMAN ishlashini ushlaydi —
       bo'sh natija bilan «hamma invariant bajarildi» degan holat bo'lmasin."""
    g, raw = heuristik("A")
    hyps = ai.validate_analysis(raw, graph=g)
    assert hyps, "A fiksturasida birorta nomzod topilmadi"
    assert {h.status for h in hyps} <= set(ai.AI_STATUSES)


@pytest.mark.parametrize("harf", HARFLAR)
def test_heuristik_taqiqlangan_darajani_chiqarmaydi(harf: str):
    """13-qoida: `VERIFIED` ham, `HUMAN_CONFIRMED` ham bu kanaldan CHIQMAYDI."""
    g, raw = heuristik(harf)
    holatlar = {h["status"] for h in raw["hypotheses"]}
    for taqiq in synth.AI_TAQIQLANGAN_HOLATLAR:
        assert taqiq not in holatlar, f"{harf}: analitik {taqiq} chiqardi"
    assert holatlar <= set(ai.AI_STATUSES)
    # ⚠️ Kuchli dalil ham chiqmaydi: daraja pastligi kuchli dalilni oqlamaydi.
    for h in raw["hypotheses"]:
        for e in h["evidence"] + h["counter_evidence"]:
            assert e["weight"] == ai.WEIGHT_WEAK
            assert e["kind"] in WEAK_EVIDENCE_KINDS


@pytest.mark.parametrize("harf", HARFLAR)
def test_heuristik_deterministik(harf: str):
    """14-qoida: bir xil graf -> AYNAN bir xil gipotezalar (bayt-bayt)."""
    g1 = build_graph(synth.config(harf))
    g2 = build_graph(synth.config(harf))
    a = dumps(ai.hypotheses_to_json(
        ai.validate_analysis(HeuristicAnalyzer().analyze(ai.analyst_payload(g1)), graph=g1)))
    b = dumps(ai.hypotheses_to_json(
        ai.validate_analysis(HeuristicAnalyzer().analyze(ai.analyst_payload(g2)), graph=g2)))
    assert a == b


@pytest.mark.parametrize("harf", HARFLAR)
def test_heuristik_kutilgan_xulqni_bajaradi(harf: str):
    """Fikstura KUTILGAN XULQINI bajaradi (qattiq javob EMAS, xulq).

    ⚠️ `EXPECTED` da xarita yozilmaydi: heuristika o'zgarishi mumkin, INVARIANT esa
       o'zgarmaydi — ikkilanish yashirilmasin, qarshi dalil yozilsin."""
    kutilgan = synth.EXPECTED[harf]
    assert set(kutilgan) == set(synth.EXPECTED_KEYS)
    g, raw = heuristik(harf)
    hyps = ai.validate_analysis(raw, graph=g)
    if kutilgan["ambiguous_shart"]:
        amb = [h for h in hyps if h.status == ai.STATUS_AMBIGUOUS]
        assert amb, f"{harf}: ikkilanish YASHIRILDI — {kutilgan['sinaydi']}"
        for h in amb:
            assert h.ambiguity, "AMBIGUOUS bo'lgan gipotezada sabab bo'sh"
    if kutilgan["qarshi_dalil_shart"]:
        assert any(h.counter_evidence for h in hyps), \
            f"{harf}: qarshi dalil yozilmadi — {kutilgan['sinaydi']}"
    if kutilgan["aniqlanmagan_havola_shart"]:
        assert g.unresolved_references, \
            f"{harf}: aniqlanmagan havola JIMGINA o'chirilgan"


@pytest.mark.parametrize("harf", HARFLAR)
def test_heuristik_zondlari_katalogdan_va_chegarada(harf: str):
    """Tavsiya etilgan zondlar KATALOGDAN tanlanadi, chegaradan oshmaydi va NISHONI mos.

    ⚠️ Nishon zond TURIGA qarab tekshiriladi (19.6 bo'limi): `field_type_details` MAYDON
       manzilini oladi, qolganlari OBYEKTNI. Ilgari bu test hamma nishonni OBYEKT deb
       o'lchardi, ya'ni maydon zondi uchun ZID shartnomani o'zi mustahkamlab turardi."""
    g, raw = heuristik(harf)
    for h in raw["hypotheses"]:
        zondlar = h["recommended_next_probe"]
        assert len(zondlar) <= ai.MAX_PROBES_PER_HYPOTHESIS
        for z in zondlar:
            assert z["probe_type"] in PROBE_CATALOG
            if z["probe_type"] in FIELD_TARGET_PROBE_TYPES:
                # Maydon manzili GRAFDA maydon bo'lib hal bo'ladi — va obyekt BO'LMAYDI.
                assert split_field_target(z["target_object"], graph=g) is not None, \
                    f"{harf}: maydon zondining nishoni grafda maydon bo'lib hal bo'lmadi"
                assert g.by_full_name(z["target_object"]) is None
            else:
                assert g.by_full_name(z["target_object"]) is not None


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 15 · `NullAnalyzer` — BO'SH JAVOB HAM JAVOB
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("harf", ["A", "G", "O"])
def test_null_analyzer_validatordan_otadi(harf: str):
    """⚠️ Bo'sh tahlil «hech narsa yo'q» degani EMAS: hamma konsept `UNKNOWN` bo'lib qoladi."""
    g = graf(harf)
    raw = NullAnalyzer().analyze(ai.analyst_payload(g))
    hyps = ai.validate_analysis(raw, graph=g)
    assert hyps == []
    hujjat = ai.hypotheses_to_json(hyps)
    assert hujjat["hypotheses"] == []
    assert hujjat["concepts_unknown"] == sorted(ai.CONCEPTS)
    # ⚠️ Sanoqlar MATN, bo'sh natijada ham.
    assert hujjat["counts"]["hypotheses"] == "0"
    assert hujjat["counts"]["concepts_unknown"] == str(len(ai.CONCEPTS))


def test_null_analyzer_buzuq_yukni_otkazmaydi():
    """Bo'sh javob berish yukni TEKSHIRMASLIK degani emas."""
    with pytest.raises(ai.AnalysisError):
        NullAnalyzer().analyze({"payload_version": "boshqa", "contract": {}, "graph": {}})


def test_recorded_analyzer_buzuq_javobni_ozgartirmaydi():
    """⚠️ Analitik qatlami validatorning O'RNINI BOSMAYDI: oldindan yozilgan buzuq javob
       o'zgarishsiz qaytadi va uni VALIDATOR rad etadi."""
    buzuq = tahlil(gipoteza(status="VERIFIED"))
    analitik = RecordedAnalyzer(fixture=buzuq)
    g = graf()
    qaytgan = analitik.analyze(ai.analyst_payload(g))
    assert qaytgan["hypotheses"][0]["status"] == "VERIFIED"
    assert "VERIFIED" in rad(qaytgan, graph=g)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 16 · STATIK: TARMOQ YO'Q, COM YO'Q, SIR YO'Q
# ═══════════════════════════════════════════════════════════════════════════════════════════
CORE_DIR = pathlib.Path(pkg.__file__).parent

#: ⚠️ `adapters/` ataylab chetlab o'tiladi: u konfiguratsiyaga xos bilim uchun ajratilgan
#: joy (hozircha bo'sh). `analyst/` esa TEKSHIRILADI — u yadrodan tashqarida, lekin xuddi
#: shu qat'iy qoidalarga bo'ysunadi.
def tekshiriladigan_fayllar() -> list[pathlib.Path]:
    return sorted(p for p in CORE_DIR.rglob("*.py") if "adapters" not in p.parts)


def yadro_fayllari() -> list[pathlib.Path]:
    return sorted(p for p in CORE_DIR.rglob("*.py")
                  if "adapters" not in p.parts and "analyst" not in p.parts)


def test_analyst_paketi_topildi():
    """⚠️ Fayl ro'yxati bo'sh qolsa statik testlar JIMGINA yashil bo'lardi."""
    nomlar = {p.name for p in tekshiriladigan_fayllar()}
    assert {"ai.py", "probe.py", "graph.py", "heuristics.py", "lexicon.py"} <= nomlar


@pytest.mark.parametrize("path", tekshiriladigan_fayllar(), ids=lambda p: p.name)
def test_tarmoq_va_com_importi_yoq(path: pathlib.Path):
    """AI qatlami tarmoqqa CHIQMAYDI: u faqat kirishdagi lug'atni o'qiydi.

    ⚠️ Provayder ulagichi (tarmoqqa chiqadigan yagona joy) bu paketdan TASHQARIDA bo'ladi."""
    banned = ("socket", "requests", "urllib", "http", "httpx", "aiohttp", "subprocess",
              "win32com", "pythoncom", "ctypes", "comtypes", "anthropic", "openai")
    text = path.read_text(encoding="utf-8")
    for tok in banned:
        assert f"import {tok}" not in text and f"from {tok}" not in text, \
            f"{path.name}: {tok!r} ishlatilmasligi kerak"


@pytest.mark.parametrize("path", tekshiriladigan_fayllar(), ids=lambda p: p.name)
def test_api_kaliti_yoki_sir_saqlanmaydi(path: pathlib.Path):
    """Kod ichida sir BO'LMAYDI: kalit ham, URL ham, muhit o'zgaruvchisi ham.

    ⚠️ `os.environ`/`getenv` ham taqiqlangan: kalitni muhitdan olgan yadro tarmoqqa
       chiqadigan yadro bo'lib qolardi, va bu diffda «zararsiz» ko'rinardi."""
    banned = ("sk-", "api_key=", "apikey=", "api-key:", "Bearer ", "Authorization",
              "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "os.environ", "getenv",
              "http://", "https://")
    text = path.read_text(encoding="utf-8")
    for tok in banned:
        assert tok not in text, f"{path.name}: {tok!r} kodda turmasligi kerak"


@pytest.mark.parametrize("path", yadro_fayllari(), ids=lambda p: p.name)
def test_yadro_talqin_qatlamini_import_qilmaydi(path: pathlib.Path):
    """⚠️ BOG'LIQLIK BIR TOMONLAMA: `analyst/` yadroni o'qiydi, yadro esa uni BILMAYDI.

    Aks holda talqin bilimi (ko'p tilli lug'at, konsept kutilmalari) yadroga oqib o'tardi va
    taxmin dalilga o'xshab qolardi."""
    text = path.read_text(encoding="utf-8")
    assert "from .analyst" not in text
    assert "import analyst" not in text
    assert "from app.services.discovery_1c.analyst" not in text


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 17 · ZOND DARVOZASI
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("tur", ["run_sql", "object_attributes ", "OBJECT_ATTRIBUTES",
                                 "write_object", ""])
def test_zond_notanish_turi_rad_etiladi(tur: str):
    """Bajariladigan amallar ro'yxati QO'LDA yozilgan — model undan faqat TANLAYDI.

    ⚠️ Parametrlar ataylab «yaqin» yozilishlar: ortiqcha probel bilan va bosh harflar bilan.
       Katalog kaliti AYNAN taqqoslanadi — «tuzatib» qabul qilish model chiqishini jimgina
       o'zgartirish bo'lardi."""
    matn = rad([gipoteza(recommended_next_probe=[zond(probe_type=tur)])])
    assert "probe_type" in matn or "zond turi" in matn


def test_zond_grafda_yoq_nishon_rad_etiladi():
    matn = rad([gipoteza(recommended_next_probe=[zond(target_object=YOQ_OBYEKT)])])
    assert "grafda yo'q" in matn


@pytest.mark.parametrize("sabab", ["", "   "])
def test_zond_sababsiz_rad_etiladi(sabab: str):
    """⚠️ Sababsiz zond operatorning vaqtini so'raydi, lekin nima uchun so'raganini aytmaydi."""
    matn = rad([gipoteza(recommended_next_probe=[zond(reason=sabab)])])
    assert "reason" in matn


@pytest.mark.parametrize("kind", sorted(STRONG_EVIDENCE_KINDS))
def test_zond_kuchli_dalil_kutolmaydi(kind: str):
    """Zond metadata o'qiydi, ya'ni undan FAQAT kuchsiz dalil chiqadi."""
    matn = rad([gipoteza(recommended_next_probe=[zond(expected_evidence=[kind])])])
    assert "KUCHSIZ dalil" in matn


def test_zond_kutilgan_dalilsiz_rad_etiladi():
    matn = rad([gipoteza(recommended_next_probe=[zond(expected_evidence=[])])])
    assert "expected_evidence" in matn


def test_zond_rejasi_chegarasi():
    """⚠️ «Hammasini so'ray» — tahlil emas, ro'yxat ko'chirish."""
    obyekt_turlari = [t for t in sorted(PROBE_CATALOG)
                      if t not in FIELD_TARGET_PROBE_TYPES][:ai.MAX_PROBES_PER_HYPOTHESIS]
    zondlar = [zond(probe_type=t) for t in obyekt_turlari]
    # ⚠️ Maydon nishonli zond ham HISOBGA kiradi: chegara zond turiga qarab yumshamaydi.
    zondlar.append(zond(probe_type="field_type_details",
                        target_object=MAHSULOT_MAYDON_MANZILI))
    matn = rad([gipoteza(recommended_next_probe=zondlar)])
    assert "chegara" in matn


#: ⚠️ Har naqsh ALOHIDA sinaladi: bitta umumiy test o'tsa, qolgan naqshlar ishlamayotgani
#: ko'rinmasdi — va aynan ishlamagan naqsh orqali kod o'tib ketardi.
XOM_KOD = [
    ("Выполнить(«kod»)", "query_keyword_platform"),
    ("ВЫБРАТЬ Nomenklatura", "query_keyword_platform"),
    ("SELECT nomi FROM jadval", "query_keyword"),
    ("Новый Массив yaratiladi", "new_object"),
    ("birinchi amal; ikkinchi amal", "statement_separator"),
    ("{shablon}", "block_braces"),
]


@pytest.mark.parametrize("matn,naqsh", XOM_KOD, ids=[n for _m, n in XOM_KOD])
def test_xom_kod_darvozasi_tutadi(matn: str, naqsh: str):
    """⚠️ Kod bo'lmaydigan joyda kodga O'XSHASH narsa ham turmasligi kerak: biror kun
       ekstraktor shu matnni «izoh» deb so'rov tanasiga qo'shsa, katalog darvozasi aylanib
       o'tilgan bo'lardi."""
    with pytest.raises(ProbeError) as e:
        assert_no_raw_code(matn, where="sinov")
    assert naqsh in str(e.value)


def test_xom_kod_darvozasi_oddiy_matnni_otkazadi():
    """Darvoza hamma narsani rad etmaydi — aks holda sabab yozib bo'lmasdi."""
    assert assert_no_raw_code("operator obyekt mazmunini ekranda ko'rsin", where="sinov") is None


@pytest.mark.parametrize("matn,naqsh", XOM_KOD, ids=[n for _m, n in XOM_KOD])
def test_xom_kod_zond_sababida_ham_tutiladi(matn: str, naqsh: str):
    """Xuddi shu darvoza zond SABABIDA ham ishlaydi (tekshiruv IKKI joyda takrorlanmaydi)."""
    xato = rad([gipoteza(recommended_next_probe=[zond(reason=matn)])])
    assert "xom kod" in xato


@pytest.mark.parametrize("joy", ["ambiguity", "required_confirmation"])
def test_xom_kod_operator_matnlarida_ham_tutiladi(joy: str):
    """⚠️ Ikkilanish sababi va tasdiq talabi OPERATORGA ko'rsatiladi — ular ham darvozadan
       o'tadi, chunki bu matnlar biror kun ekstraktorga izoh bo'lib ketishi mumkin."""
    h = gipoteza(status=ai.STATUS_AMBIGUOUS,
                 ambiguity=["ikki nomzod bali yaqin"],
                 required_confirmation=["operator obyektni ochib ko'rsin"])
    h[joy] = ["ВЫБРАТЬ Tovar"]
    assert "xom kod" in rad([h])


def test_katalogdagi_hamma_zond_faqat_oqiydi():
    """⚠️ `read_only: False` bo'lgan yozuv KATALOGDA BO'LISHI MUMKIN EMAS: yozuvchi zond bu
       qatlamning butun ma'nosini yo'qotadi."""
    katalog = ai.analyst_payload(graf())["contract"]["probe_catalog"]
    assert set(katalog) == set(PROBE_CATALOG)
    for tur, spec in katalog.items():
        assert spec["read_only"] is True, tur
        assert spec["why"].strip() and spec["returns"].strip()


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 18 · QAMROV — QARALMAGAN KONSEPT TASHLANMAYDI
# ═══════════════════════════════════════════════════════════════════════════════════════════
def test_konseptlar_soni_yigirma_uch():
    """Qamrov hisobining asosi: shartnomada 23 konsept bor va ular takrorsiz."""
    assert len(ai.CONCEPTS) == 23
    assert len(set(ai.CONCEPTS)) == 23


@pytest.mark.parametrize("harf", HARFLAR)
def test_qamrov_hamma_konseptni_hisobga_oladi(harf: str):
    """⚠️ Nomzod topilmagan konsept TASHLANMAYDI — u `UNKNOWN` bo'lib hisobda qoladi.
       «Qaralmadi» va «yo'q» bir xil narsa emas, va farqni faqat shu hisob saqlaydi."""
    cov = coverage(graf(harf))
    assert set(cov["concepts"]) == set(ai.CONCEPTS)
    assert cov["counts"]["concepts"] == "23"
    jami = (int(cov["counts"]["covered"]) + int(cov["counts"]["rejected_only"])
            + int(cov["counts"]["unknown"]))
    assert jami == len(ai.CONCEPTS), f"{harf}: konsept hisobdan tushib qoldi"
    # Sanoqlar MATN — bu yerda ham.
    for kalit, qiymat in cov["counts"].items():
        assert isinstance(qiymat, str), kalit


@pytest.mark.parametrize("harf", HARFLAR)
def test_qamrov_nomzodsiz_konseptni_unknown_deb_ataydi(harf: str):
    """`concepts_unknown` va `state=UNKNOWN` AYNAN bir xil to'plamni ko'rsatadi."""
    cov = coverage(graf(harf))
    noma_lum = {c for c, v in cov["concepts"].items() if v["state"] == STATE_UNKNOWN}
    assert set(cov["concepts_unknown"]) == noma_lum
    assert cov["counts"]["unknown"] == str(len(noma_lum))
    for konsept in noma_lum:
        # ⚠️ Qaralmagan konsept hisobda TURADI, lekin unga «eng yaxshi nomzod» YOZILMAYDI:
        #    yo'q nomzodga ball qo'yish taxminni javobga aylantirardi.
        assert cov["concepts"][konsept]["best_score"] is None
        assert cov["concepts"][konsept]["best_address"] is None
        assert cov["concepts"][konsept]["hypotheses"] == "0"


def test_qamrov_bosh_tahlilda_hamma_konsept_unknown():
    """⚠️ Bo'sh tahlil hamma konseptni `UNKNOWN` qiladi — 23 tasi ham hisobda qoladi."""
    cov = coverage(graf("A"), analyzer=NullAnalyzer())
    assert cov["counts"] == {"concepts": "23", "covered": "0", "rejected_only": "0",
                            "unknown": "23", "hypotheses": "0"}
    assert set(cov["concepts_unknown"]) == set(ai.CONCEPTS)
    assert all(v["state"] == STATE_UNKNOWN for v in cov["concepts"].values())


def test_qamrov_validator_rad_etadigan_narsani_hisoblamaydi():
    """⚠️ `coverage()` natijani VALIDATORDAN o'tkazadi: rad etilgan tahlil qamrovga
       «hisoblanib» qolmaydi, u butunlay yiqiladi."""
    with pytest.raises(ai.AnalysisError):
        coverage(graf("A"), analyzer=RecordedAnalyzer(fixture=tahlil(
            gipoteza(status="VERIFIED"))))


def test_qamrov_deterministik():
    """Bir xil graf -> AYNAN bir xil qamrov hujjati."""
    assert dumps(coverage(build_graph(synth.config("A")))) == \
        dumps(coverage(build_graph(synth.config("A"))))


# ═══════════════════════════════════════════════════════════════════════════════════════════
# CHIQISH HUJJATI — TASHLAMASDAN va DETERMINISTIK
# ═══════════════════════════════════════════════════════════════════════════════════════════
def test_chiqish_hujjatida_sanoqlar_matn_va_qaralmagan_konsept_ochiq():
    g, raw = heuristik("A")
    hujjat = ai.hypotheses_to_json(ai.validate_analysis(raw, graph=g))
    assert isinstance(hujjat["counts"]["hypotheses"], str)
    for holat, soni in hujjat["counts"]["by_status"].items():
        assert holat in ai.AI_STATUSES
        assert isinstance(soni, str)
    # ⚠️ Qaralmagan konsept hujjatda OCHIQ turadi — tushirib qoldirilgani keyinchalik
    #    «tekshirilgan va topilmagan» deb o'qilardi.
    qamralgan = {h["target_concept"] for h in hujjat["hypotheses"]}
    assert set(hujjat["concepts_unknown"]) == set(ai.CONCEPTS) - qamralgan
    assert hujjat["counts"]["concepts_unknown"] == str(len(hujjat["concepts_unknown"]))


def test_chiqish_hujjati_tekshirilmagan_lugatni_qabul_qilmaydi():
    """⚠️ `hypotheses_to_json` QAYTA TEKSHIRMAYDI, shu bois u XOM lug'atni umuman olmaydi:
       aks holda tekshirilmagan ma'lumot shu yo'l bilan hujjatga tushib ketardi."""
    with pytest.raises(ai.AnalysisError):
        ai.hypotheses_to_json([gipoteza()])
    with pytest.raises(ai.AnalysisError):
        ai.hypothesis_to_json(gipoteza())


def test_validator_natijasi_deterministik_tartibda():
    """⚠️ Modelning navbati MA'NO TASHIMAYDI: kirish tartibi o'zgarsa ham natija bir xil."""
    birinchi = gipoteza(target_concept="warehouse", candidate_object=OMBOR,
                        recommended_next_probe=[zond(target_object=OMBOR)])
    ikkinchi = gipoteza(target_concept="product", candidate_object=MAHSULOT)
    a = ai.validate_analysis([birinchi, ikkinchi], graph=graf())
    b = ai.validate_analysis([ikkinchi, birinchi], graph=graf())
    assert [h.sort_key for h in a] == [h.sort_key for h in b]
    assert dumps(ai.hypotheses_to_json(a)) == dumps(ai.hypotheses_to_json(b))


def test_dalil_va_matnlar_tartiblanadi():
    """Dalillar, ikkilanish sabablari va zondlar TARTIBLANADI (determinizm).

    ⚠️ Dalil SONI darajaga ta'sir qilmaydi, shu bois tartib ham ma'no tashimaydi — lekin
       chiqish bayt-bayt bir xil bo'lishi kerak."""
    h = gipoteza(
        status=ai.STATUS_AMBIGUOUS,
        evidence=[dalil("type_shape", detail="b tip mos"), dalil("name_match", detail="a nom")],
        ambiguity=["ikkinchi sabab", "birinchi sabab"],
        required_confirmation=["ikkinchi talab", "birinchi talab"],
        recommended_next_probe=[zond(probe_type="row_count"), zond()])
    hyp = ai.validate_analysis([h], graph=graf())[0]
    assert [e.kind for e in hyp.evidence] == ["name_match", "type_shape"]
    assert hyp.ambiguity == ("birinchi sabab", "ikkinchi sabab")
    assert hyp.required_confirmation == ("birinchi talab", "ikkinchi talab")
    assert [p.probe_type for p in hyp.recommended_next_probe] == ["object_attributes",
                                                                  "row_count"]


def test_ishonch_bali_olchov_boligi_uchun_matn_emas():
    """⚠️ `confidence_score` sanoq EMAS, o'lchov: `0.50` va `0.5` bir xil, ya'ni boshidagi
       nol ma'no tashimaydi. Shu bois «sanoqlar MATN» qoidasi unga TEGISHLI EMAS — va
       aynan shu sababdan u yagona son bo'lib qoladi."""
    hujjat = ai.hypotheses_to_json(ai.validate_analysis([gipoteza(confidence_score=0.25)],
                                                        graph=graf()))
    assert hujjat["hypotheses"][0]["confidence_score"] == 0.25
    assert math.isfinite(hujjat["hypotheses"][0]["confidence_score"])


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 19.1 · `allow_human_confirmed` FAQAT ODAM DALILINI OCHADI — GURUHNI EMAS
# ═══════════════════════════════════════════════════════════════════════════════════════════
#: Odam kanali CHIQARMAYDIGAN kuchli dalil turlari.
#: ⚠️ To'rtta tur ataylab ro'yxatdan HISOBLANADI, qo'lda yozilmaydi: `schema` ga beshinchi
#: kuchli tur qo'shilsa, u avtomatik shu testga tushadi. Qo'lda yozilgan ro'yxat ortda qolardi
#: va yangi tur JIMGINA ochiq qolib ketardi.
ODAMSIZ_KUCHLI_TURLAR = sorted(set(STRONG_EVIDENCE_KINDS) - {ai.HUMAN_EVIDENCE_KIND})


def test_odamsiz_kuchli_turlar_royxati_bosh_qolmaydi():
    """⚠️ Ro'yxat bo'sh qolsa, 19.1 testlari JIMGINA yashil bo'lardi (parametrsiz test yo'q)."""
    assert len(ODAMSIZ_KUCHLI_TURLAR) == 4
    assert ai.HUMAN_EVIDENCE_KIND in STRONG_EVIDENCE_KINDS
    # Tasdiq kanali AYNAN shu turni yasaydi — ikki modul bitta nomni bilishi SHART.
    assert ai.HUMAN_EVIDENCE_KIND == C.HUMAN_EVIDENCE_KIND


@pytest.mark.parametrize("kind", ODAMSIZ_KUCHLI_TURLAR)
@pytest.mark.parametrize("joy", ["evidence", "counter_evidence"])
def test_tasdiq_rejimi_odamdan_boshqa_kuchli_turni_ochmaydi(kind: str, joy: str):
    """NUQSON ISBOTI: `allow_human_confirmed` ilgari BESHTA kuchli turni birdan ochardi.

    ⚠️ NEGA HALOKATLI: `schema.confidence_error` migrator darvozasining darajasini
       (`ai.FORBIDDEN_STATUS`) `STRONG_EVIDENCE_KINDS` ning HAR QANDAY a'zosi uchun beradi — ya'ni bayroq aynan MIGRATOR DARVOZASINI ochadigan
       dalil turlarini (arifmetik isbot, kontrakt mosligi, mustaqil manbalar kelishuvi,
       yo'qlik isboti) modelning qo'liga berardi. Tasdiq kanali esa faqat `human_confirmed`
       ni ishlab chiqaradi (`confirmations.HUMAN_EVIDENCE_KIND`), ya'ni qolgan to'rt turni
       hech kim, hech qachon qonuniy yo'l bilan yuborolmaydi.
    ⚠️ Bayroq «manba — ODAM» degani, «kuchli dalil guruhini och» degani EMAS. Farq bitta
       so'zda ko'rinadi, natijasi esa butun ishonch qoidasi."""
    h = gipoteza(status=ai.STATUS_HUMAN_CONFIRMED, evidence=[odam_dalili()])
    h[joy] = list(h[joy]) + [dalil(kind, weight="strong", detail="avtomat shunday dedi")]
    matn = rad([h], allow_human_confirmed=True)
    assert kind in matn
    assert "HECH QANDAY kanal chiqarmaydi" in matn
    assert joy in matn


@pytest.mark.parametrize("holat", [ai.STATUS_CANDIDATE, ai.STATUS_AMBIGUOUS, ai.STATUS_REJECTED])
def test_odam_dalili_faqat_human_confirmed_holatida_ochiladi(holat: str):
    """Tasdiq rejimida ham odam dalili HOLATGA bog'langan: `evidence` da faqat HUMAN_CONFIRMED.

    ⚠️ Aks holda tasdiq holatdan UZILARDI: hujjatda kuchli dalil ko'rinar, holat esa nomzodni
       tasdiqlanmagan qilib qoldirar — va keyin «odam ko'rdimi?» degan savolga hujjatning o'zi
       ikki xil javob berardi."""
    h = gipoteza(status=holat, evidence=[dalil(), odam_dalili()],
                 ambiguity=["ikki nomzodning bali yaqin"],
                 counter_evidence=[dalil("cardinality", detail="qatorlar soni mos emas")])
    matn = rad([h], allow_human_confirmed=True)
    assert ai.HUMAN_EVIDENCE_KIND in matn
    assert "KUCHLI dalil turi AI chiqishida BO'LMAYDI" in matn


@pytest.mark.parametrize("holat", [ai.STATUS_CANDIDATE, ai.STATUS_AMBIGUOUS,
                                   ai.STATUS_HUMAN_CONFIRMED])
def test_odam_qarshi_dalili_faqat_rejected_holatida_ochiladi(holat: str):
    """`counter_evidence` dagi odam dalili faqat `REJECTED` da: «operator RAD ETDI» degani.

    ⚠️ Yo'nalishni RO'YXAT aytadi, turni esa MANBA (`confirmations` izohi): shu bois rad etish
       uchun alohida dalil turi o'ylab chiqarilmaydi. Lekin holat mos kelmasa, hujjatda «odam
       nimani aytgani» noaniq bo'lib qolardi — tasdiq ham, rad etish ham holatga bog'lanadi."""
    foydasiga = [dalil()]
    if holat == ai.STATUS_HUMAN_CONFIRMED:
        foydasiga.append(odam_dalili())
    h = gipoteza(status=holat, evidence=foydasiga,
                 ambiguity=["ikki nomzodning bali yaqin"],
                 counter_evidence=[odam_dalili(prefix="rad etdi", izoh="bu resurs kod emas")])
    matn = rad([h], allow_human_confirmed=True)
    assert ai.HUMAN_EVIDENCE_KIND in matn
    assert "counter_evidence" in matn


def test_odam_dalili_tasdiq_kanali_bilan_bir_xil_shaklda():
    """IKKI TOMON BITTA SHAKLNI BILADI: `confirmations` yasaydi, `ai` tekshiradi.

    ⚠️ Oqim UCHDAN-UCHIGA yuriladi (xususiy funksiya chaqirilmaydi): gipoteza tekshiriladi,
       tasdiq qo'llanadi, natija lug'atga aylanadi va QAYTA validatordan o'tadi. Shakl ikki
       tomonda ajralib ketsa — shu test yiqiladi, ya'ni tasdiq oqimi JIMGINA buzilmaydi."""
    hyps = ai.validate_analysis([gipoteza()], graph=graf())
    tasdiq = {"confirmations_version": C.CONFIRMATIONS_VERSION,
              "confirmations": [{"target_concept": "product", "candidate_object": MAHSULOT,
                                 "candidate_field": None, "decision": C.DECISION_CONFIRM,
                                 "operator": OPERATOR, "decided_at": TASDIQ_VAQTI,
                                 "note": "1C ekranida obyekt tarkibi ko'rildi"}],
              "notes": []}
    [h] = C.apply_confirmations(hyps, tasdiq)
    assert h.status == ai.STATUS_HUMAN_CONFIRMED
    [odam] = [e for e in h.evidence if e.kind == ai.HUMAN_EVIDENCE_KIND]
    assert OPERATOR in odam.detail and TASDIQ_VAQTI in odam.detail
    qayta = ai.validate_analysis([ai.hypothesis_to_json(h)], graph=graf(),
                                 allow_human_confirmed=True)
    assert [x.status for x in qayta] == [ai.STATUS_HUMAN_CONFIRMED]


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 19.2 · ODAM DALILIDA KIM VA QACHON — STRUKTUR TEKSHIRUV
# ═══════════════════════════════════════════════════════════════════════════════════════════
#: Har bir shakl ALOHIDA sinaladi: bitta umumiy test o'tsa, qolgan holatlar tutilmayotgani
#: ko'rinmasdi — va aynan tutilmagan shakl orqali «tasdiq» o'tib ketardi.
YOMON_ODAM_TAFSILOTI = [
    ("tasdiqlandi", "kim ham, qachon ham yo'q — ilgari AYNAN shu QABUL qilinardi"),
    ("tasdiqlandi · 2026-09-30T11:20:00+05:00", "vaqt bor, KIM yo'q (anonim tasdiq)"),
    ("tasdiqladi: operator Sotuvchi-7", "kim bor, QACHON yo'q"),
    ("tasdiqladi: operator  · 2026-09-30T11:20:00+05:00", "operator nomi BO'SH"),
    ("tasdiqladi: operator Sotuvchi-7 · kecha", "vaqt tamg'asi emas, so'z"),
    ("tasdiqladi: operator Sotuvchi-7 · 30.09.2026", "ISO 8601 emas"),
    ("tasdiqladi: operator Sotuvchi-7 · 2026-09-30T11:20:00", "vaqt zonasi (offset) YO'Q"),
    ("tasdiqladi: operator Sotuvchi-7 · 0001-01-01T00:00:00+05:00",
     "to'ldirilmagan sana — ishonarli kalendar oynasidan tashqarida"),
]


@pytest.mark.parametrize("detail,nima", YOMON_ODAM_TAFSILOTI,
                         ids=[str(i) for i, _row in enumerate(YOMON_ODAM_TAFSILOTI)])
def test_odam_dalilida_kim_va_qachon_majburiy(detail: str, nima: str):
    """NUQSON ISBOTI: ilgari FAQAT dalil TURI sanalardi, `detail` esa `_nonempty` dan boshqa
    hech narsadan o'tmasdi — ya'ni `detail='tasdiqlandi'` tasdiq bo'lib o'tib ketardi.

    ⚠️ NEGA MAJBURIY: kim aytganini bilmasdan tasdiqni QAYTARIB TEKSHIRIB bo'lmaydi (kimdan
       so'rash kerakligi bilinmaydi), qachon aytilganini bilmasdan esa uni auditda
       joylashtirib bo'lmaydi (qaysi holatdagi hujjatga qarab aytilgani bilinmaydi). Ikkisi
       yo'q tasdiq — tasdiq EMAS, shunchaki matn.
    ⚠️ Vaqt BU YERDA O'YLAB CHIQARILMAYDI: faqat KELGANI tekshiriladi va u haqiqiy vaqt
       tamg'asi bo'lishi kerak (`parse_ts`: vaqt zonasi bilan, ishonarli kalendar oynasida)."""
    matn = rad([gipoteza(status=ai.STATUS_HUMAN_CONFIRMED,
                         evidence=[dalil(ai.HUMAN_EVIDENCE_KIND, weight="strong",
                                         detail=detail)])],
               allow_human_confirmed=True)
    assert ai.HUMAN_EVIDENCE_KIND in matn, nima


@pytest.mark.parametrize("izoh", [None, "1C ekranida obyekt tarkibi ko'rildi"])
def test_togri_shakldagi_odam_dalili_otadi(izoh):
    """Darvoza hamma narsani rad etmaydi: to'g'ri shakl (izoh bilan ham, izohsiz ham) O'TADI.

    ⚠️ Bu ham KERAK: hech narsani o'tkazmaydigan darvoza tasdiq oqimini butunlay yopardi va
       nuqson «tuzatilgan» ko'rinardi."""
    hyps = ai.validate_analysis([gipoteza(status=ai.STATUS_HUMAN_CONFIRMED,
                                          evidence=[odam_dalili(izoh=izoh)])],
                                graph=graf(), allow_human_confirmed=True)
    assert hyps[0].status == ai.STATUS_HUMAN_CONFIRMED


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 19.3 · MODEL YOZGAN `detail` — REDAKSIYA VA XOM KOD DARVOZALARIDAN O'TADI
# ═══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("matn,nima", SIR_SHAKLLARI, ids=[n for _m, n in SIR_SHAKLLARI])
@pytest.mark.parametrize("joy", ["evidence", "counter_evidence"])
def test_dalil_tafsilotidagi_sir_hujjatga_yozilmaydi(joy: str, matn: str, nima: str):
    """NUQSON ISBOTI: `evidence.detail` / `counter_evidence.detail` hech qachon `redact.scan`
    dan o'tmasdi, `hypotheses_to_json` + `bundle.dumps` esa uni o'zgarishsiz BAYTLARGA yozardi.

    ⚠️ ASIMMETRIYA ataylab qo'yilgan darvozalar YONIDA edi: `ambiguity` va
       `required_confirmation` `assert_no_raw_code` dan o'tardi, `analyst_payload` KIRISHNI
       skanerlardi, `validate_confirmations` skanerlardi — faqat modelning `detail` i qarovsiz
       qolardi. Bitta tekshirilmagan matn maydoni butun redaksiya kafolatini yo'qqa chiqaradi:
       artefakt qo'ldan-qo'lga o'tadi va undagi sir bilan birga tarqaydi."""
    h = gipoteza(status=ai.STATUS_REJECTED,
                 counter_evidence=[dalil("cardinality", detail="qatorlar soni mos emas")])
    h[joy] = [dalil(detail=f"nom mos — {matn}")]
    xato = rad([h])
    assert "sir shubhasi" in xato, nima
    assert joy in xato


def test_sir_dalil_tafsilotidan_hujjat_baytlariga_yetmaydi():
    """⚠️ NUQSONNING JONLI ISBOTI: darvozasiz `bundle.dumps(hypotheses_to_json(...))` ichida
       parol TURARDI. Endi hujjat umuman QURILMAYDI — va xato matni sirni O'ZI ham chiqarmaydi
       (tutgan narsasini jurnal orqali tarqatadigan darvoza darvoza emas)."""
    sir = "nom mos — parol: Qwerty12345!"
    xato = rad([gipoteza(evidence=[dalil(detail=sir)])])
    assert "sir shubhasi" in xato
    assert "Qwerty12345!" not in xato
    # ⚠️ Chiqish funksiyasi ham xom lug'atni olmaydi, ya'ni validatorni chetlab o'tib hujjat
    #    qurish yo'li YO'Q (tekshirilmagan `detail` boshqa yo'ldan ham baytlarga tushmaydi).
    with pytest.raises(ai.AnalysisError):
        ai.hypotheses_to_json([gipoteza(evidence=[dalil(detail=sir)])])


@pytest.mark.parametrize("matn,naqsh", XOM_KOD, ids=[n for _m, n in XOM_KOD])
@pytest.mark.parametrize("joy", ["evidence", "counter_evidence"])
def test_xom_kod_dalil_tafsilotida_ham_tutiladi(joy: str, matn: str, naqsh: str):
    """Xuddi shu darvoza dalil TAFSILOTIDA ham ishlaydi.

    ⚠️ Sabab `ambiguity` dagi bilan bir xil: bu matnlar operatorga ko'rsatiladi va biror kun
       ekstraktorga «izoh» bo'lib ketishi mumkin — kod bo'lmaydigan joyda kodga o'xshash narsa
       turmasligi kerak."""
    h = gipoteza(status=ai.STATUS_REJECTED,
                 counter_evidence=[dalil("cardinality", detail="qatorlar soni mos emas")])
    h[joy] = [dalil(detail=matn)]
    assert "xom kod" in rad([h])


#: Xom kod belgisi BO'LMAGAN sir shakllari.
#: ⚠️ Ajratib olish KERAK: `ambiguity` va `required_confirmation` avval XOM KOD
#: darvozasidan o'tadi, ya'ni ichida `;` bo'lgan shakl boshqa sababdan rad etilardi va
#: REDAKSIYA darvozasi tekshirilmay qolardi (test o'zi o'lchamoqchi bo'lgan narsani o'lchamasdi).
SIR_KODSIZ = [(m, n) for m, n in SIR_SHAKLLARI if ";" not in m and "{" not in m]


@pytest.mark.parametrize("matn,nima", SIR_KODSIZ, ids=[n for _m, n in SIR_KODSIZ])
@pytest.mark.parametrize("joy", ["ambiguity", "required_confirmation"])
def test_operator_matnlarida_ham_sir_tutiladi(joy: str, matn: str, nima: str):
    """Operatorga ko'rsatiladigan matnlar ham REDAKSIYA darvozasidan o'tadi.

    ⚠️ Ilgari bu ikki matn faqat XOM KOD darvozasidan o'tardi, ya'ni ichidagi parol yoki
       ulanish satri jimgina hujjatga yozilardi. Kirishdagi yuk skanerlanib
       (`analyst_payload`), CHIQISHGA ketadigan matn skanerlanmasligi — redaksiya
       kafolatining yarmi, ya'ni kafolatsizlik."""
    h = gipoteza(status=ai.STATUS_AMBIGUOUS, ambiguity=["ikki nomzodning bali yaqin"],
                 required_confirmation=["operator obyektni ochib ko'rsin"])
    h[joy] = [f"tekshirish uchun {matn}"]
    xato = rad([h])
    assert "sir shubhasi" in xato, nima
    assert joy in xato


@pytest.mark.parametrize("matn,nima", SIR_KODSIZ, ids=[n for _m, n in SIR_KODSIZ])
def test_analitik_izohida_ham_sir_tutiladi(matn: str, nima: str):
    """Izoh ham artefaktga yoziladi (19.4), ya'ni u ham skanerlanadi."""
    xato = rad(izohli_tahlil([f"yig'uvchi qaydi: {matn}"]))
    assert "sir shubhasi" in xato, nima
    assert "notes" in xato


def test_analitik_izohida_ham_xom_kod_tutiladi():
    """`notes` ham darvozadan o'tadi: u endi CHIQISHGA ketadi (19.4), ya'ni artefaktga tushadi."""
    xato = rad({"analysis_version": ai.ANALYSIS_VERSION, "hypotheses": [gipoteza()],
                "notes": ["ВЫБРАТЬ Tovar"]})
    assert "xom kod" in xato


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 19.4 · ANALITIKNING `notes` I CHIQISHDA QOLADI — JIM QISISH YO'Q
# ═══════════════════════════════════════════════════════════════════════════════════════════
def izohli_tahlil(izohlar, *gipotezalar: dict) -> dict:
    """Qobiqli tahlil, izohlari BERILGAN tartibda.

    ⚠️ `izohlar` AYNAN berilgan holda uzatiladi (`list()` ga o'ralmaydi): shakl testlari
       ro'yxat BO'LMAGAN qiymatni ham yuboradi, o'rash esa ularni jimgina ro'yxatga
       aylantirib, tekshiruvni ma'nosiz qilardi."""
    return {"analysis_version": ai.ANALYSIS_VERSION,
            "hypotheses": list(gipotezalar) or [gipoteza()], "notes": izohlar}


def test_analitik_izohlari_chiqishga_otadi():
    """NUQSON ISBOTI: `notes` TALAB qilinar, TEKSHIRILAR va keyin JIMGINA TASHLANARDI.

    ⚠️ NEGA MUHIM: aynan izohda «Nomzodlar soni chegaraga QISILGAN konseptlar» xabari keladi —
       `keep_window`/`max_per_concept` tufayli ishonchli nomzod ro'yxatdan CHIQARILGANINING
       YAGONA yozuvi. Izoh tashlansa, operator artefaktda kesilgan nomzodni ko'rmaydi va
       umuman biror narsa kesilganini BILMAYDI, ya'ni «no silent caps» qoidasi jimgina
       buzilardi."""
    qisish = ("Nomzodlar soni chegaraga qisilgan konseptlar: barcode. "
              "Qisilgani «yo'q» degani emas.")
    izohlar = ["birinchi izoh", qisish]
    natija = ai.validate_analysis(izohli_tahlil(izohlar), graph=graf())
    assert ai.analysis_notes(natija) == tuple(izohlar)
    assert natija.notes == tuple(izohlar)
    # ⚠️ TARTIB SAQLANADI: qisish haqidagi ogohlantirish analitik qo'ygan joyda — oxirida —
    #    qoladi. Alifbo tartibi uni o'rtaga surib qo'yardi va operator varaqasida ko'zdan
    #    qochardi (`review._analyzer_notes` ham aynan shu qoidaga amal qiladi).
    assert natija.notes[-1] == qisish
    # Natija AVVALGIDEK oddiy ro'yxat: chaqiruvchilarning birortasi o'zgarmaydi.
    assert isinstance(natija, list)
    assert [h.address for h in natija] == [MAHSULOT]


def test_izoh_qobiqsiz_shaklda_bosh_tuple():
    """⚠️ Qobiqsiz chiqishda izoh YO'Q, va bu «izoh tashlandi» degani emas — «yozilmadi» degani."""
    natija = ai.validate_analysis([gipoteza()], graph=graf())
    assert natija.notes == ()
    assert ai.analysis_notes(natija) == ()
    # Oddiy ro'yxat berilsa ham `analysis_notes` yiqilmaydi (`review` uni shunday chaqiradi).
    assert ai.analysis_notes(list(natija)) == ()


@pytest.mark.parametrize("harf", ["A", "G", "O"])
def test_heuristik_izohlari_validatordan_keyin_yoqolmaydi(harf: str):
    """UCHDAN-UCHIGA: analitik yozgan izohlar validatordan keyin ham AYNAN o'sha holda turadi."""
    g, raw = heuristik(harf)
    natija = ai.validate_analysis(raw, graph=g)
    assert raw["notes"], f"{harf}: analitik umuman izoh yozmadi"
    assert ai.analysis_notes(natija) == tuple(raw["notes"])


def test_null_analyzer_izohi_ham_yoqolmaydi():
    """⚠️ Bo'sh tahlilning izohi ayniqsa muhim: gipoteza yo'q, ya'ni izohdan boshqa hech narsa
       «nega bo'sh» degan savolga javob bermaydi."""
    g = graf("A")
    raw = NullAnalyzer().analyze(ai.analyst_payload(g))
    natija = ai.validate_analysis(raw, graph=g)
    assert natija == []
    assert ai.analysis_notes(natija) == tuple(raw["notes"])


@pytest.mark.parametrize("yomon", [["", "izoh"], [None], "izoh", 7, [["izoh"]]])
def test_izoh_shakli_tekshiriladi(yomon):
    """Izoh CHIQISHGA ketadi, ya'ni uning shakli ham QAT'IY tekshiriladi."""
    matn = rad(izohli_tahlil(yomon))
    assert "notes" in matn


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 19.5 · `full_name` SHAKLI — BSL SATR LITERALINI YOPIB BO'LMAYDI
# ═══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ BU HAQIQIY HUJUM SHAKLI: nom ichida qo'shtirnoq bilan BSL satr literali YOPILADI,
#: ortidan YOZUVCHI amal qo'shiladi va keyingi chaqiruv bilan literal qayta ochiladi. Nom
#: grafga tushar, `validate_probe` dan O'TAR (chunki u rostdan grafda bor), ko'rik artefaktiga
#: `target_object` bo'lib chiqar va operator uni hujjatda ko'rsatilgan shablonga qo'yardi —
#: ya'ni ekstraktorning statik auditi BUTUNLAY aylanib o'tilardi.
BSL_INYEKSIYA = 'Справочник.Tovar"); Объект.Записать(); Zond("row_count", "X'

YOMON_FULL_NAME = [
    (BSL_INYEKSIYA, "Tovar", "qo'shtirnoq, nuqtali vergul va amal chaqiruvi"),
    ('Справочник.Tovar"', "Tovar", "qo'shtirnoq — satr literalini yopadi"),
    ("Справочник.Tovar; DROP", "Tovar", "nuqtali vergul — operator ajratuvchisi"),
    ("Справочник.Tovar)", "Tovar", "qavs — chaqiruvni yopadi"),
    ("Справочник.To varlar", "To varlar", "probel"),
    ("Справочник.Tovar-1", "Tovar-1", "tire — identifikator belgisi emas"),
    ("Справочник", "Справочник", "ajratuvchi nuqta YO'Q"),
    ("Справочник.", "Tovar", "ikkinchi bo'lak BO'SH"),
    (".Tovarlar", "Tovarlar", "prefiks BO'SH"),
    ("Справочник.Tovarlar.Artikul", "Artikul", "ikkitadan KO'P bo'lak — bu manzil, nom emas"),
    ("Справочник.1Tovar", "1Tovar", "identifikator raqam bilan boshlangan"),
]


@pytest.mark.parametrize("full_name,name,nima", YOMON_FULL_NAME,
                         ids=[n for _f, _nm, n in YOMON_FULL_NAME])
def test_full_name_shakli_talab_qilinadi(full_name: str, name: str, nima: str):
    """NUQSON ISBOTI: `full_name` faqat `_nonempty` dan o'tardi — shakl ham, belgi to'plami ham,
    `name` bilan mosligi ham TEKSHIRILMASDI.

    ⚠️ Nima uchun bu inventarizatsiya validatorining ishi: nom SHU YERDAN boshlab ko'chadi
       (graf -> zond nishoni -> ko'rik artefakti -> operator qo'lidagi shablon). Eng ichki
       darvoza eng arzon: keyingi qatlamlarning har biri nomni «bor narsa» deb qabul qiladi."""
    hujjat = synth.doc([synth.obj(full_name, "catalog", name)])
    with pytest.raises(MetadataError) as e:
        validate_metadata(hujjat)
    assert "full_name" in str(e.value) or "name" in str(e.value), nima


def test_full_name_oxirgi_bolagi_name_ga_mos_kelishi_shart():
    """Bitta obyekt IKKI XIL nom bilan yura olmaydi.

    ⚠️ Graf va ko'rik artefakti `full_name` ni ko'rsatadi, tasdiq hujjati esa `name` ni —
       ikkisi bir-birini tekshirmasa, operator NIMANI tasdiqlaganini keyin isbotlab bo'lmasdi."""
    hujjat = synth.doc([synth.obj("Справочник.Tovarlar", "catalog", "Boshqa")])
    with pytest.raises(MetadataError) as e:
        validate_metadata(hujjat)
    assert "`name` ga mos emas" in str(e.value)


@pytest.mark.parametrize("full_name,name", [("Справочник.Товары", "Товары"),
                                            ("Catalog.X17", "X17"),
                                            ("РегистрНакопления.Qoldiq_2", "Qoldiq_2"),
                                            ("Перечисление._Holat", "_Holat")])
def test_haqiqiy_full_name_shakllari_otadi(full_name: str, name: str):
    """Darvoza HAQIQIY nomlarni yo'qotmaydi: kirill, lotin, pastki chiziq, raqamli oxir.

    ⚠️ Cheklov 1C ning O'Z qoidasidan qat'iyroq EMAS — platformada to'liq nom aynan
       `<metadata turi>.<identifikator>` va identifikatorda tinish belgisi bo'lmaydi."""
    assert validate_metadata(synth.doc([synth.obj(full_name, "catalog", name)])) == ()


def test_zond_nishoni_ham_xom_kod_darvozasidan_otadi():
    """IKKINCHI QATLAM: nom qandaydir yo'l bilan grafga tushsa ham, zond darvozasi to'xtatadi.

    ⚠️ Ikki qatlam ham KERAK va biri ikkinchisini almashtirmaydi: inventarizatsiya darvozasi
       HUJJAT orqali kelgan nomni tutadi, zond darvozasi esa grafni BOSHQA yo'l bilan qurgan
       kodni (masalan adapterni yoki kelajakdagi ulagichni) tutadi.
    ⚠️ Ilgari `assert_no_raw_code` FAQAT `reason` ga qo'llanardi, `target_object` ga HECH
       QACHON — ya'ni TUSHUNTIRISH maydoni qo'riqlanar, BAJARISH maydoni qo'riqlanmasdi.
       Graf `dataclasses.replace` bilan quriladi, hujjatdan EMAS: hujjat yo'li allaqachon
       yopilgan (yuqoridagi test) va bu test AYNAN zond darvozasini sinaydi."""
    g = graf()
    o = dataclasses.replace(g.objects[0], full_name=BSL_INYEKSIYA)
    buzuq = dataclasses.replace(g, objects=(o,) + g.objects[1:])
    assert buzuq.by_full_name(BSL_INYEKSIYA) is not None, (
        "nishon grafda BOR — ya'ni rad etilish sababi «grafda yo'q» emas, AYNAN xom kod "
        "bo'lishi kerak")
    with pytest.raises(ProbeError) as e:
        validate_probe(ProbeRequest(probe_type="row_count", target_object=BSL_INYEKSIYA,
                                    reason="qatorlar soni gipotezani tekshiradi",
                                    expected_evidence=("cardinality",)), graph=buzuq)
    assert "xom kod" in str(e.value)
    assert "target_object" in str(e.value)
    # Xato matni topilgan bo'lakni QISQARTIRIB ko'rsatadi — uzun kod jurnalga to'liq ko'chmaydi.
    assert BSL_INYEKSIYA not in str(e.value)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# 19.6 · ZOND NISHON SHARTNOMASI: MAYDON ZONDI — MAYDON MANZILI
# ═══════════════════════════════════════════════════════════════════════════════════════════
def maydon_zondi(**almashtir) -> dict:
    """Maydon nishonli XOM zond so'rovi (`field_type_details`)."""
    z = {"probe_type": "field_type_details", "target_object": MAHSULOT_MAYDON_MANZILI,
         "reason": "maydon tipining aniqligi nomdan mustaqil dalil beradi",
         "expected_evidence": ["type_shape"]}
    z.update(almashtir)
    return z


def test_nishon_shartnomasi_bitta_joyda_va_yukda_aytilgan():
    """Shartnoma KATALOGDA ham aytiladi: model yukda ko'radi, validator undan rad etadi.

    ⚠️ Aytilmagan qoida bo'yicha rad etish — tekshirib bo'lmaydigan shartnoma."""
    assert FIELD_TARGET_PROBE_TYPES == ("field_type_details",)
    # ⚠️ Ajratuvchi IKKI modulda yozilgan (`probe` grafni import QILMAYDI — bog'liqlik bir
    #    tomonlama), shu bois ular AYNAN bir xil ekanini test solishtiradi: ajralib ketsa,
    #    manzil bir tomonda hal bo'lar, ikkinchisida bo'lmasdi.
    assert TARGET_SEP == PATH_SEP
    katalog = ai.analyst_payload(graf())["contract"]["probe_catalog"]
    for tur in FIELD_TARGET_PROBE_TYPES:
        assert tur in katalog
        assert "MAYDON" in katalog[tur]["returns"]


def test_maydon_zondi_maydon_manzilini_qabul_qiladi():
    """NUQSON ISBOTINING TESKARI TOMONI: zond endi UMUMAN natija bera oladi.

    ⚠️ Ilgari ikki tomon ZID talab qilardi — validator OBYEKT, bajaruvchi MAYDON YO'LI — ya'ni
       maydonli nishon validatorda rad etilar, obyektli nishon bajaruvchida xato berardi.
       Katalogda TIRIK ko'rinadigan, amalda O'LIK zond: hech qanday yo'l bilan natija
       bermaydigan darvoza «tekshirdim» degan yolg'on xotirjamlik beradi."""
    hyp = ai.validate_analysis(
        [gipoteza(recommended_next_probe=[maydon_zondi()])], graph=graf())[0]
    assert hyp.recommended_next_probe[0].target_object == MAHSULOT_MAYDON_MANZILI


def test_maydon_zondi_bolim_ichidagi_maydonni_ham_hal_qiladi():
    """Uch bo'lakli manzil (`<obyekt>.<bo'lim>.<maydon>`) ham hal bo'ladi.

    ⚠️ Obyektning to'liq nomida HAM nuqta bor, ya'ni «oxirgi nuqta bo'yicha ajratish» bu
       manzilni buzardi: ajratish GRAFDAN so'raladi (eng uzun obyekt prefiksi), taxmin bilan
       emas."""
    hyp = ai.validate_analysis(
        [gipoteza(target_concept="price", candidate_object=SOTUV_HUJJATI,
                  candidate_field=f"{SOTUV_BOLIMI}.Цена",
                  recommended_next_probe=[maydon_zondi(
                      target_object=SOTUV_BOLIM_MAYDON_MANZILI)])], graph=graf())[0]
    z = hyp.recommended_next_probe[0]
    assert z.target_object == SOTUV_BOLIM_MAYDON_MANZILI
    assert split_field_target(z.target_object, graph=graf()) == (SOTUV_HUJJATI,
                                                                f"{SOTUV_BOLIMI}.Цена")


@pytest.mark.parametrize("nishon,nima", [
    (f"{MAHSULOT}.{YOQ_MAYDON}", "obyekt bor, MAYDON yo'q"),
    (f"{YOQ_OBYEKT}.{MAHSULOT_MAYDONI}", "obyektning O'ZI yo'q"),
    (f"{SOTUV_HUJJATI}.{SOTUV_BOLIMI}", "jadval BO'LIMI maydon emas — uning tipi ham yo'q"),
    (f"{MAHSULOT}.{MAHSULOT_MAYDONI}.{YOQ_MAYDON}", "maydon ichida maydon yo'q"),
])
def test_maydon_zondi_yoq_maydonni_rad_etadi(nishon: str, nima: str):
    """Maydon nomi ham O'YLAB CHIQARILMAYDI: mavjud bo'lmagan maydonga yuborilgan zond eng
    yaxshi holatda xato, eng yomonida — boshqa maydonga tushib ketgan so'rov."""
    matn = rad([gipoteza(recommended_next_probe=[maydon_zondi(target_object=nishon)])])
    assert "target_object" in matn, nima


def test_maydon_zondi_obyekt_nishonini_rad_etadi():
    """Obyekt nishoni bu zond uchun BAJARILMAYDI — shu bois u SHU YERDA to'xtaydi.

    ⚠️ Bajaruvchi tomon maydon YO'LINI talab qiladi va yo'l bo'sh bo'lsa xato qaytaradi, ya'ni
       obyektli nishonni qabul qilish operatorni har safar xato qaytaradigan zond bilan
       yuborish bo'lardi."""
    matn = rad([gipoteza(recommended_next_probe=[maydon_zondi(target_object=MAHSULOT)])])
    assert "MAYDON MANZILI" in matn


@pytest.mark.parametrize("tur", [t for t in sorted(PROBE_CATALOG)
                                 if t not in FIELD_TARGET_PROBE_TYPES])
def test_obyekt_zondlari_maydon_manzilini_rad_etadi(tur: str):
    """Teskari tomoni: qolgan zondlarga MAYDON manzili berilmaydi.

    ⚠️ Bu «grafda yo'q» EMAS — manzil rostdan bor, faqat u OBYEKT emas. Xato matni shu farqni
       AYTADI, aks holda chaqiruvchi nomni «tuzatishga» urinardi va sabab yo'qolardi."""
    matn = rad([gipoteza(recommended_next_probe=[
        zond(probe_type=tur, target_object=MAHSULOT_MAYDON_MANZILI)])])
    assert "MAYDON manzili" in matn
    assert "OBYEKT bilan ishlaydi" in matn
