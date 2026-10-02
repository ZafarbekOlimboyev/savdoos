# -*- coding: utf-8 -*-
"""AI ANALITIK SHARTNOMASI — `binos-1c-ai-analysis-v1` (provayderdan MUSTAQIL).

⚠️ BU FAYLDA BIRORTA PROVAYDER KODI YO'Q: model nomi, API kaliti, tarmoq chaqiruvi, hech biri.
   Bu yerda faqat SHARTNOMA yashaydi: modelga NIMA yuboriladi (`analyst_payload`), modeldan
   NIMA qaytishi kerak (`Hypothesis`), qaytgani QANDAY tekshiriladi (`validate_analysis`) va
   natija QANDAY yoziladi (`hypotheses_to_json`). Provayder ulagichi yadrodan TASHQARIDA
   bo'ladi va shu uchta nuqtadan boshqa hech narsani bilmaydi.

NEGA SHUNDAY BO'LINGAN. Model — DALIL MANBASI EMAS, GIPOTEZA MANBASI. U metadata nomlariga
qarab «bu maydon shu konseptga to'g'ri keladi» deb TAXMIN qiladi, taxmin esa tasdiq emas.
Shu bois:
  · modelning eng yuqori chiqishi — `CANDIDATE`, va u ham DALIL bilan keladi;
  · `VERIFIED` ni model ham, yig'uvchi ham, bu modul ham CHIQARA OLMAYDI (`FORBIDDEN_STATUS`);
  · `HUMAN_CONFIRMED` faqat OPERATORNING alohida tasdiq hujjatidan keladi — model
    ishonchidan EMAS, `confidence_score` qanchalik yuqori bo'lishidan qat'i nazar.

KUCHGA KIRITILADIGAN INVARIANTLAR:
  1. Model obyekt yoki maydon O'YLAB CHIQARA OLMAYDI: `candidate_object` grafda, ko'rsatilgan
     bo'lsa `candidate_field` ham shu obyektda bo'lishi SHART.
  2. DALILSIZ XULOSA YO'Q: `CANDIDATE` va `AMBIGUOUS` kamida bitta dalil talab qiladi,
     `REJECTED` — kamida bitta qarshi dalil, `AMBIGUOUS` — kamida bitta ikkilanish sababi.
  3. Model KUCHLI dalil turini chiqara olmaydi (`schema.STRONG_EVIDENCE_KINDS`): o'zini o'zi
     tasdiqlaydigan tahlil butun ishonch qoidasini ma'nosiz qiladi.
  4. NOM MOSLIGI o'zi bilan hech narsani tasdiqlamaydi — u `name_match`, ya'ni KUCHSIZ dalil,
     va daraja `CANDIDATE` dan oshmaydi.
  5. Qaralmagan konsept TASHLANMAYDI: `hypotheses_to_json` unga gipoteza yo'qligini
     `concepts_unknown` da OCHIQ yozadi. «Qaralmadi» ≠ «yo'q».
  6. Noma'lum kalit — RAD, tushib qolgan kalit ham — RAD. Model «qo'shimcha maydon» bilan
     shartnomani kengaytira olmaydi.
  7. Sanoqlar MATN. `confidence_score` esa SANOQ EMAS, u o'lchov — pastdagi izohga qarang.
  8. Determinizm: dalillar, ikkilanishlar, zondlar tartiblanadi; bir xil kirish — AYNAN bir
     xil bayt. Modelning navbati ma'no tashimaydi.
  9. Vaqt bu yerda O'YLAB CHIQARILMAYDI: shartnomada umuman vaqt tamg'asi yo'q, u kirishdagi
     hujjatlarda (inventarizatsiya, tasdiq hujjati) yashaydi. Kelgan vaqt esa TEKSHIRILADI:
     odam tasdig'ining `detail` idagi vaqt tamg'asi `parse_ts` dan o'tadi.
 10. JIM QISISH YO'Q: analitikning `notes` i CHIQISHDA qoladi (`AnalysisResult.notes`,
     `analysis_notes()`), chunki kesilgan nomzod haqidagi yagona xabar aynan izohda keladi.
 11. MODEL YOZGAN HAR QANDAY MATN darvozadan o'tadi: `ambiguity`, `required_confirmation`,
     `notes` va dalillarning `detail` i — hammasi `redact.scan` va `assert_no_raw_code` dan.
     Bitta tekshirilmagan matn maydoni butun redaksiya kafolatini yo'qqa chiqaradi.

Bu modulda birorta konfiguratsiya nomi YO'Q. `CONCEPTS` — BIZNING shartnomamiz nomlari
(ASCII, snake_case); qaysi obyekt qaysi konseptga to'g'ri kelishi — MA'LUMOT, ya'ni grafdan
keladigan va odam tasdiqlaydigan narsa.
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from . import redact as redaction
from .bundle import DiscoveryError
from .graph import DiscoveryGraph, graph_stats
from .probe import (ProbeError, ProbeRequest, assert_no_raw_code, catalog_to_json,
                    probe_from_json, probe_to_json, validate_probe_plan)
from .schema import EVIDENCE_KINDS, STRONG_EVIDENCE_KINDS, WEAK_EVIDENCE_KINDS
from ..migrator_1c.bundle import BundleError, parse_ts

AI_PAYLOAD_VERSION = "binos-1c-ai-payload-v1"
ANALYSIS_VERSION = "binos-1c-ai-analysis-v1"

# ── Konseptlar: BinOS tomonidagi ma'no birliklari ───────────────────────────────────────────
# ⚠️ Bular BIZNING shartnomamiz ID lari, 1C nomlari EMAS. Ataylab ASCII va snake_case: ular
#    JSON kaliti bo'lib yuradi, kodda taqqoslanadi va tarjimaga bog'liq bo'lmasligi kerak.
# ⚠️ Konsept — NISHON EMAS. `schema.TARGETS` ko'chirish uchun kerak bo'lgan aniq maydonlar
#    ro'yxati; konsept esa undan kengroq ma'no birligi (masalan «sotuv hujjati» degan tushuncha
#    bitta maydon emas). Ikkisini qo'shib yuborish — ko'chirish rejasini tahlilga aralashtirish.
CONCEPTS = (
    # tovar va uning o'ziga xosligi
    "product",
    "sku_article",
    "barcode",
    "unit_of_measure",
    "product_variant",
    # ombor va harakat
    "warehouse",
    "stock_balance",
    "stock_movement",
    "goods_receipt",
    # kontragentlar
    "supplier",
    "customer",
    "counterparty",
    # sotuv hujjatlari
    "sale_document",
    "sales_return",
    # pul
    "price",
    "cost",
    "tax_vat",
    # partiya va muddat
    "batch_lot",
    "expiry_date",
    # kassa va xodim
    "cash_register",
    "employee_cashier",
    # tarozi
    "scale_plu",
    "weighted_product",
)

# ── Holatlar ───────────────────────────────────────────────────────────────────────────────
STATUS_CANDIDATE = "CANDIDATE"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_REJECTED = "REJECTED"
STATUS_HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
STATUSES = (STATUS_CANDIDATE, STATUS_AMBIGUOUS, STATUS_REJECTED, STATUS_HUMAN_CONFIRMED)

#: Model CHIQARISHI mumkin bo'lgan holatlar — `HUMAN_CONFIRMED` dan TASHQARI hammasi.
#: ⚠️ `HUMAN_CONFIRMED` shartnomada BOR, lekin u AI kanalidan kelmaydi: uni faqat operatorning
#: alohida tasdiq hujjati keltiradi (`validate_analysis(..., allow_human_confirmed=True)`).
#: Model ishonchi 1.0 bo'lsa ham bu holatni bera olmaydi — ishonch odam ko'rigining o'rnini
#: bosmaydi.
AI_STATUSES = tuple(s for s in STATUSES if s != STATUS_HUMAN_CONFIRMED)

#: ⚠️ `VERIFIED` BU KANALDA UMUMAN YO'Q va bo'lishi ham mumkin emas.
#: Sabab: `schema.confidence_error` bo'yicha `VERIFIED` faqat KUCHLI dalil (odam tasdig'i,
#: arifmetik isbot, kontrakt mosligi, mustaqil manbalar kelishuvi, yo'qlik isboti) bilan
#: beriladi. Model bu dalillarning birortasini ham keltira olmaydi: u faqat metadatani
#: o'qiydi. Shu bois `VERIFIED` ni chiqargan tahlil xato emas — u SHARTNOMANI BUZGAN tahlil,
#: va aynan shu nom bilan RAD etiladi (jimgina `CANDIDATE` ga tushirilmaydi: pasaytirish
#: buzilishni yashirardi).
FORBIDDEN_STATUS = "VERIFIED"

# ── Dalil vazni ────────────────────────────────────────────────────────────────────────────
WEIGHT_WEAK = "weak"
WEIGHT_STRONG = "strong"
EVIDENCE_WEIGHTS = (WEIGHT_WEAK, WEIGHT_STRONG)

#: Odam ko'rigining dalil TURI — `schema.STRONG_EVIDENCE_KINDS` ichidagi YAGONA tur, u ham
#: faqat tasdiq kanalida ochiladi (`confirmations.HUMAN_EVIDENCE_KIND` bilan AYNAN bir xil matn).
#: ⚠️ NEGA ALOHIDA KONSTANTA: ilgari «kuchli dalil» butun BIR GURUH bo'lib ochilardi. Tasdiq
#:    kanali esa faqat SHU turni ishlab chiqaradi, qolgan to'rtta kuchli tur (arifmetik isbot,
#:    kontrakt mosligi, mustaqil manbalar kelishuvi, yo'qlik isboti) hech qanday kanaldan
#:    KELMAYDI — ular kelajakdagi alohida qadamlarning natijasi. Guruhni ochish esa aynan
#:    MIGRATOR DARVOZASINI modelning qo'liga berardi: `schema.confidence_error` bo'yicha
#:    `FORBIDDEN_STATUS` darajasi HAR QANDAY kuchli dalil bilan beriladi.
HUMAN_EVIDENCE_KIND = "human_confirmed"

#: `human_confirmed` dalilining `detail` i ICHIDAGI shakl: `… operator <KIM> · <QACHON> …`
#: ⚠️ Shakl `confirmations` da YASALADI (`Confirmation.who_when`), bu yerda esa TEKSHIRILADI.
#:    Matn TAXMIN QILINMAYDI: ikki modul bir xil ikki konstantani ishlatadi, va agar tasdiq
#:    tomoni shaklni o'zgartirsa, shu darvoza yiqiladi — jimgina o'tib ketmaydi.
#: ⚠️ NEGA KERAK: «kim va qachon» yozilmagan tasdiqni qaytarib tekshirib bo'lmaydi (kimdan
#:    so'rash, qaysi holatdagi hujjatga qarab aytilgani bilinmaydi), ya'ni u tasdiq EMAS.
#:    `detail='tasdiqlandi'` ilgari QABUL qilinardi — bu eng yumshoq va eng qimmat teshik edi.
HUMAN_WHO_MARKER = "operator "
HUMAN_DETAIL_SEP = " · "

#: Bitta konseptga nechta gipoteza ruxsat etiladi.
#: ⚠️ Chegara bor, chunki har obyektni nomzod qilib sanab chiqish TAHLIL EMAS: model tanlashi
#: va tanlab bo'lmagan joyni `AMBIGUOUS` deb ochiq aytishi kerak.
MAX_HYPOTHESES_PER_CONCEPT = 8

#: Bitta gipoteza tavsiya qila oladigan zondlar chegarasi (`probe.MAX_PROBES_DEFAULT` — butun
#: reja uchun). ⚠️ Kichik chegara modelni eng ko'p ma'lumot beradigan zondni tanlashga majburlaydi.
MAX_PROBES_PER_HYPOTHESIS = 4

# ── Kalit oq ro'yxatlari ───────────────────────────────────────────────────────────────────
ANALYSIS_KEYS = {"analysis_version", "hypotheses", "notes"}
HYPOTHESIS_KEYS = {"target_concept", "candidate_object", "candidate_field", "confidence_score",
                   "evidence", "counter_evidence", "ambiguity", "required_confirmation",
                   "recommended_next_probe", "status"}
EVIDENCE_KEYS = {"kind", "detail", "weight"}

#: 1C uchulik mantiqi yukka MATN bo'lib chiqadi.
#: ⚠️ `"unknown"` = «yig'uvchi qaramadi», `"false"` = «qaradi va yo'q». Modelga `null` yuborilsa
#: u buni «yo'q» deb o'qib ketishi mumkin, shu bois farq MATNDA ochiq turadi.
TRISTATE_TEXT = {True: "true", False: "false", None: "unknown"}


class AnalysisError(DiscoveryError):
    """AI (yoki tasdiq hujjati) chiqishi shartnomaga mos emas — O'QILMAYDI.

    `DiscoveryError` dan meros: discovery hujjatlarini o'qiydigan mavjud kod bitta `except`
    bilan bularni ham qamrab oladi."""


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise AnalysisError(msg)


def _keys(obj, allowed: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = sorted(set(obj) - allowed)
    _need(not extra, f"{where}: noma'lum kalit(lar) {extra} — {ANALYSIS_VERSION} da yo'q")
    missing = sorted(allowed - set(obj))
    _need(not missing, f"{where}: kalit(lar) tushib qolgan {missing}")


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and v.strip(), f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    return v


def _text_tuple(v, where: str) -> tuple[str, ...]:
    """Matnlar ro'yxati -> tartiblangan, takrorsiz tuple. Bo'sh element — RAD."""
    _need(isinstance(v, (list, tuple)), f"{where} matnlar ro'yxati bo'lishi kerak")
    for i, x in enumerate(v):
        _nonempty(x, f"{where}[{i}]")
    # ⚠️ Tartiblanadi: modelning navbati ma'no tashimaydi, chiqish esa bayt-bayt bir xil
    #    bo'lishi kerak.
    return tuple(sorted({x.strip() for x in v}))


def _no_secret(text: str, where: str) -> None:
    """Matnda sir shubhasi bo'lsa RAD (fail-closed), va xato SIRNING O'ZINI takrorlamaydi.

    ⚠️ Modelning (yoki tasdiq hujjatining) ERKIN MATNI hujjat baytlariga yoziladi va artefakt
       qo'ldan-qo'lga o'tadi. Shu bois kirishdagi yuk qanday skanerlansa (`analyst_payload`),
       CHIQISHGA ketadigan matn ham AYNAN shunday skanerlanadi: bir tomonni qo'riqlab
       ikkinchisini qo'riqlamaslik — redaksiya kafolatining yarmi, ya'ni kafolatsizlik.
    ⚠️ `redact.scan` lug'at/ro'yxat kutadi, shu bois matn bitta kalitli lug'atga o'raladi.
       Kalit nomi ATAYLAB neytral (`detail`): sirga o'xshash kalit nomi skanerni o'zi
       qo'zg'atardi va har matn rad etilardi."""
    findings = redaction.scan({"detail": text})
    _need(not findings,
          f"{where}: sir shubhasi bor — HUJJATGA YOZILMAYDI: "
          + "; ".join(str(f) for f in findings[:10]))


def _notes_tuple(v, where: str) -> tuple[str, ...]:
    """Analitikning izohlari: bo'sh bo'lmagan matnlar, TARTIBI SAQLANGAN holda.

    ⚠️ Bu yerda `_text_tuple` ISHLATILMAYDI, garchi shakl bir xil bo'lsa ham: `_text_tuple`
       tartiblaydi va takrorni birlashtiradi. Izohlar esa CHIQISHGA ketadi va ular analitik
       yozgan NAVBATDA o'qilishi kerak — qisish haqidagi ogohlantirish oxirida keladi, alifbo
       tartibi esa uni o'rtaga surib qo'yardi (`review._analyzer_notes` ham aynan shu qoidaga
       amal qiladi). Determinizm bundan buzilmaydi: kirish tartibi o'zi deterministik.
    ⚠️ Takror izoh TASHLANMAYDI: u analitikning o'z matni, va uni jimgina olib tashlash
       «nima yozilganini» o'zgartirish bo'lardi."""
    _need(isinstance(v, (list, tuple)), f"{where} matnlar ro'yxati bo'lishi kerak")
    return tuple(_nonempty(x, f"{where}[{i}]") for i, x in enumerate(v))


@contextmanager
def _probe_gate(where: str):
    """Zond darvozasining xatosini `AnalysisError` ga o'raydi (`metadata.py` naqshi bilan bir xil).

    ⚠️ Xato MATNI SAQLANADI va sabab zanjiri (`from e`) uzilmaydi: chaqiruvchi nima uchun rad
       etilganini ko'rishi kerak. O'rash faqat TURNI birlashtiradi — `validate_analysis` dan
       chiqadigan xato har doim `AnalysisError`, ya'ni chaqiruvchi ikki turni ushlab yurmaydi."""
    try:
        yield
    except ProbeError as e:
        msg = str(e)
        # Manzil ikki marta yozilmasin: ba'zi xatolar manzilni o'zi bilan olib keladi.
        raise AnalysisError(msg if msg.startswith(where) else f"{where}: {msg}") from e


# ── Dalil ──────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Evidence:
    """Bitta dalil: turi, tafsiloti va VAZNI.

    `kind`   — `schema.EVIDENCE_KINDS` dan (lug'at bitta joyda turadi, bu yerda takrorlanmaydi).
    `detail` — dalilning o'zi: nimaga asoslanib shunday deyilgani.
    `weight` — `weak` yoki `strong`; turdan KELIB CHIQADI va unga mos bo'lishi SHART.

    ⚠️ `weight` ATAYLAB alohida maydon, garchi u turdan hisoblansa ham: model o'zi bergan
       dalilni qanday baholayotganini AYTIB qo'yishi kerak, chunki `weak` deb yozilgan joyda
       `strong` tur ko'rsatilishi — shartnomani chetlab o'tishga urinish, va u ko'rinib turadi.
    ⚠️ Model KUCHLI dalil bera OLMAYDI: `human_confirmed` odam ko'rigidan, `arithmetic_proof`
       hisobdan, `absence_proven` esa butun metadatani sanab chiqishdan keladi. Modelning
       «men tekshirdim» degani dalil emas."""

    kind: str
    detail: str
    weight: str


def _human_detail(detail: str, where: str) -> None:
    """`human_confirmed` dalilining `detail` i KIM va QACHON ni olib kelishini talab qiladi.

    Tekshiruv STRUKTUR, matnni «o'qib tushunish» emas: `confirmations.Confirmation.who_when`
    yasagan shakl izlanadi — `operator <KIM>` · `<QACHON>` — va vaqt tamg'asi HAQIQIY vaqt
    tamg'asi bo'lishi uchun `parse_ts` ga beriladi (vaqt zonasi bilan ISO 8601, ishonarli
    kalendar oynasi).

    ⚠️ Vaqt BU YERDA O'YLAB CHIQARILMAYDI (9-invariant): faqat KELGANI tekshiriladi. «Kecha»,
       «bugun» yoki yilsiz sana auditda joylashtirib bo'lmaydigan tasdiq degani.
    ⚠️ Operator nomida ajratuvchi (` · `) bo'lsa tasdiq RAD etiladi: shakl ikki xil o'qilib
       qolmasligi kerak, va bu cheklov nomni yozishning oddiy yo'lini yopmaydi."""
    joy = detail.find(HUMAN_WHO_MARKER)
    _need(joy >= 0,
          f"{where}: {HUMAN_EVIDENCE_KIND!r} dalilida KIM tasdiqlagani yo'q — `detail` ichida "
          f"{HUMAN_WHO_MARKER!r} bo'lagi va operatorning nomi bo'lishi SHART. ANONIM TASDIQ "
          f"YO'Q: kim aytganini bilmasdan tasdiqni qaytarib tekshirib bo'lmaydi, ya'ni u "
          f"tasdiq emas")
    bo_laklar = detail[joy + len(HUMAN_WHO_MARKER):].split(HUMAN_DETAIL_SEP)
    _need(len(bo_laklar) >= 2 and bo_laklar[0].strip(),
          f"{where}: {HUMAN_EVIDENCE_KIND!r} dalilining `detail` i "
          f"`{HUMAN_WHO_MARKER}<KIM>{HUMAN_DETAIL_SEP}<QACHON>` shaklida bo'lishi kerak — "
          f"kim va qachon ko'rgani AYRIM-AYRIM o'qiladigan bo'lishi SHART (tasdiq hujjati "
          f"aynan shu shaklni yasaydi)")
    when = bo_laklar[1].strip()
    try:
        parse_ts(when, f"{where} ({HUMAN_EVIDENCE_KIND} vaqti)")
    except BundleError as e:
        raise AnalysisError(
            f"{where}: {HUMAN_EVIDENCE_KIND!r} dalilida QACHON tasdiqlangani vaqt tamg'asi "
            f"emas — {e}") from e


def _evidence(raw, *, where: str, allow_human: bool) -> Evidence:
    """Bitta dalil. `allow_human=True` — FAQAT `human_confirmed` turini ochadi, boshqa hech nimani.

    ⚠️ IKKI DARVOZA, IKKI SABAB (ilgari bittasi ikkinchisining o'rniga ishlardi):
       · TUR bo'yicha — ochiladigan yagona kuchli tur `HUMAN_EVIDENCE_KIND`. Qolgan to'rt
         kuchli tur HAR QANDAY rejimda RAD: ularni ishlab chiqaradigan kanal HOZIRCHA YO'Q,
         va ular `schema.confidence_error` bo'yicha MIGRATOR darvozasini ochadi.
       · HOLAT bo'yicha — chaqiruvchi (`_validate_hypothesis`) `allow_human` ni faqat mos
         holatdagi gipotezaga beradi. Ilgari bayroq «kuchli dalil guruhini ochish» degani edi,
         ya'ni tasdiq hujjatini o'qish rejimi modelga arifmetik isbot yozish huquqini ham
         berardi — teshik AYNAN shu guruh kengligida edi."""
    _keys(raw, EVIDENCE_KEYS, where)
    kind = _nonempty(raw["kind"], f"{where}.kind")
    _need(kind in EVIDENCE_KINDS,
          f"{where}.kind noma'lum: {kind!r} — ruxsat etilgani {list(EVIDENCE_KINDS)}")
    detail = _nonempty(raw["detail"], f"{where}.detail")
    weight = _nonempty(raw["weight"], f"{where}.weight")
    _need(weight in EVIDENCE_WEIGHTS,
          f"{where}.weight {list(EVIDENCE_WEIGHTS)} dan biri bo'lishi kerak, kelgani {weight!r}")

    kutilgan_vazn = WEIGHT_STRONG if kind in STRONG_EVIDENCE_KINDS else WEIGHT_WEAK
    _need(weight == kutilgan_vazn,
          f"{where}: {kind!r} dalili {kutilgan_vazn!r} vaznda bo'lishi kerak, "
          f"kelgani {weight!r} — vazn dalil TURIDAN kelib chiqadi, e'londan emas")

    if kind not in WEAK_EVIDENCE_KINDS:
        # ⚠️ Avval TUR: `human_confirmed` dan boshqa kuchli tur hech qanday rejimda o'tmaydi.
        _need(kind == HUMAN_EVIDENCE_KIND,
              f"{where}.kind {kind!r} — bu KUCHLI dalil turini HECH QANDAY kanal chiqarmaydi: "
              f"arifmetik isbot, kontrakt mosligi, mustaqil manbalar kelishuvi va yo'qlik "
              f"isboti alohida qadamlarning natijasi, tahlil yoki tasdiq hujjatining e'loni "
              f"emas. Ochiladigan yagona kuchli tur — {HUMAN_EVIDENCE_KIND!r}")
        # ⚠️ Keyin HOLAT: tur to'g'ri bo'lsa ham, uni faqat odam kanali bera oladi.
        _need(allow_human,
              f"{where}.kind {kind!r} — KUCHLI dalil turi AI chiqishida BO'LMAYDI: model o'zini "
              f"o'zi tasdiqlay olmaydi. Kuchli dalil ({', '.join(STRONG_EVIDENCE_KINDS)}) faqat "
              f"operatorning alohida tasdiq hujjatidan keladi")
        _human_detail(detail, where)
    return Evidence(kind=kind, detail=detail, weight=weight)


def _evidence_tuple(v, *, where: str, allow_human: bool) -> tuple[Evidence, ...]:
    _need(isinstance(v, (list, tuple)), f"{where} ro'yxat bo'lishi kerak")
    rows = tuple(_evidence(x, where=f"{where}[{i}]", allow_human=allow_human)
                 for i, x in enumerate(v))
    # ⚠️ MODEL YOZGAN MATN REDAKSIYA VA XOM KOD DARVOZALARIDAN O'TADI. Ilgari `ambiguity` va
    #    `required_confirmation` o'tardi, `detail` esa O'TMASDI — va aynan `detail`
    #    `hypotheses_to_json` orqali hujjat BAYTLARIGA yoziladi. Ya'ni model (yoki uning
    #    yukini o'zgartirgan kim) izohga parol yoki ulanish satrini yozib yuborsa, u
    #    artefakt bilan birga qo'ldan-qo'lga o'tardi; kodga o'xshash matn esa biror kun
    #    ekstraktorga «izoh» bo'lib ketishi mumkin. Darvoza KIRISHDA turadi — hujjat
    #    yozilishidan OLDIN, chunki chiqishda to'xtatish «tekshirmasdan yozib qo'yish» ni
    #    allaqachon sodir bo'lgan qilardi.
    for i, e in enumerate(rows):
        _no_secret(e.detail, f"{where}[{i}].detail")
    with _probe_gate(where):
        for i, e in enumerate(rows):
            assert_no_raw_code(e.detail, where=f"{where}[{i}].detail")
    # ⚠️ Tartiblanadi (tur, tafsilot): determinizm uchun. Dalil SONI darajaga ta'sir qilmaydi,
    #    shu bois tartib ham ma'no tashimaydi.
    return tuple(sorted(rows, key=lambda e: (e.kind, e.detail)))


# ── Gipoteza ───────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Hypothesis:
    """Bitta gipoteza: konsept <- grafdagi nomzod obyekt/maydon, dalili bilan.

    ⚠️ GIPOTEZA XARITA EMAS. U «shunday bo'lishi mumkin» degani, «shunday» degani emas.
       Ko'chirish rejasiga faqat odam tasdiqlagan gipoteza tushadi.
    ⚠️ `confidence_score` — modelning O'Z bahosi, DALIL EMAS. U holatni ko'tarmaydi: 0.99 ham
       `CANDIDATE` bo'lib qoladi. Baho faqat odam ko'rigining NAVBATINI belgilashga yaraydi.
    ⚠️ `required_confirmation` — odam AYNAN nimani ko'rishi kerakligi. Bu maydon bo'sh bo'lsa
       gipoteza tekshirib bo'lmaydigan bo'ladi, ya'ni u hech qachon tasdiqdan o'tmaydi."""

    target_concept: str
    candidate_object: str
    candidate_field: str | None
    confidence_score: float
    evidence: tuple[Evidence, ...]
    counter_evidence: tuple[Evidence, ...]
    ambiguity: tuple[str, ...]
    required_confirmation: tuple[str, ...]
    recommended_next_probe: tuple[ProbeRequest, ...]
    status: str

    @property
    def address(self) -> str:
        """Nomzodning to'liq manzili: `<obyekt>` yoki `<obyekt>.<maydon>`."""
        if self.candidate_field is None:
            return self.candidate_object
        return f"{self.candidate_object}.{self.candidate_field}"

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.target_concept, self.candidate_object, self.candidate_field or "",
                self.status)


@runtime_checkable
class DiscoveryAIAnalyzer(Protocol):
    """Provayder ulagichining SHARTNOMASI — yadro faqat shu shaklni biladi.

    Ulagich (Claude, boshqa model, yoki hatto qo'lda yozilgan qoidalar to'plami) shu
    protokolni bajaradi:

        payload = analyst_payload(graph)             # XAVFSIZ yuk: faqat metadata
        raw = analyzer.analyze(payload)              # provayder ishi, yadrodan TASHQARIDA
        hyps = validate_analysis(raw, graph=graph)   # ISHONMASDAN tekshirish

    `analyze` KIRISHI  — `analyst_payload` qaytargan lug'at, boshqa hech narsa: ulagich unga
    biznes qatori, sir yoki ulanish ma'lumoti QO'SHMAYDI.
    `analyze` CHIQISHI — `ANALYSIS_KEYS` shaklidagi lug'at (yoki gipoteza lug'atlari ro'yxati).
    `Hypothesis` obyektlari EMAS: chiqish provayderdan kelgan XOM ma'lumot va u tekshirilmagan.

    ⚠️ Yadro `analyze` natijasiga ISHONMAYDI. Ulagich qanday yozilganidan qat'i nazar, natija
       `validate_analysis` dan o'tadi; o'tmasa — RAD. Validatordan o'tmagan chiqish keyingi
       qadamga UMUMAN yetib bormaydi.
    ⚠️ Ulagich tarmoqqa chiqishi mumkin, LEKIN YADRODA EMAS: bu fayl va butun `discovery_1c`
       yadrosi tarmoqqa chiqmaydi va buni testlar tekshiradi.
    ⚠️ `analyze` dan HUMAN_CONFIRMED kelsa — RAD. Odam tasdig'i model kanalidan o'tmaydi."""

    def analyze(self, payload: dict) -> dict:
        ...


# ── Provayderga yuboriladigan XAVFSIZ yuk ──────────────────────────────────────────────────
def _field_payload(f) -> dict:
    """Bitta maydonning SHAKLI — QIYMATI emas.

    ⚠️ `numeric_digits` / `numeric_scale` / `string_length` MATN bo'lib keladi va shundayligicha
       ketadi (`binos-1c-metadata-v1` 1-invarianti)."""
    return {
        "name": f.name,
        "path": f.path,
        "synonym": f.synonym,
        "kind": f.kind,
        "type": f.value_type,
        "reference_targets": list(f.reference_targets),
        "numeric_digits": f.numeric_digits,
        "numeric_scale": f.numeric_scale,
        "string_length": f.string_length,
    }


def _object_payload(o) -> dict:
    return {
        "full_name": o.full_name,
        "kind": o.object_kind,
        "name": o.name,
        "synonym": o.synonym,
        "comment": o.comment,
        "hierarchical": TRISTATE_TEXT[o.hierarchical],
        "row_count": o.row_count,
        "register_kind": o.register_kind,
        "periodicity": o.periodicity,
        "tabular_sections": list(o.tabular_section_names),
        "enum_values": list(o.enum_values),
        "predefined": list(o.predefined),
        "fields": [_field_payload(f) for f in o.fields],
        "errors": list(o.errors),
    }


def analyst_payload(graph: DiscoveryGraph, *, concepts=CONCEPTS) -> dict:
    """Provayderga yuboriladigan XAVFSIZ yuk: FAQAT metadata + shartnoma.

    NIMA BOR: obyekt nomlari, sinonimlar, izohlar, maydon nomlari va XOM tip tavsiflari,
    havolalar, registr shakli, sanab o'tilgan qiymat NOMLARI, sanoqlar (MATN), grafdagi
    bog'lanishlar, aniqlanmagan havolalar va shartnomaning o'zi (konseptlar, holatlar,
    ruxsat etilgan dalil turlari, zond katalogi).

    ⚠️ NIMA YO'Q — va buni KOD MAJBURLAYDI (faqat shu ikki sinf):
       · BIZNES QATORI. Yuk FAQAT `DiscoveryGraph` metadatasidan quriladi; qator o'qish yo'li
         bu yerda UMUMAN yo'q, `row_count` esa qatorning o'zi emas, SANOG'I (MATN). Kalitlar
         ro'yxati `test_yuk_faqat_metadata_kalitlarini_tashiydi` bilan qulflangan — yangi
         kalit qo'shgan odam «bu qator emasmi?» degan savolga javob berishi kerak bo'ladi.
       · `redact.scan()` TUTADIGAN shakllar: parol (to'rt tilda, ajratuvchisiz ham),
         token/api_key/credential/private_key, 1C ulanish satri, URL ichidagi login:parol,
         e-mail, telefon, PEM kalit bloki, masofaviy kirish ID si (AnyDesk/TeamViewer/RDP),
         Windows fayl yo'li, UNC tarmoq yo'li va `IP:port`.
       Model MA'NO topishi uchun qatorlar KERAK EMAS — unga tuzilma yetadi. Qator yuborilsa,
       do'konning ma'lumoti uchinchi tomon xizmatiga ketardi.
    ⚠️ QAMRALMAGAN, OCHIQ AYTILADI — quyidagilar yukka VERBATIM tushadi:
       · YALANG'OCH IP (portsiz) va versiya shakli — `10.0.0.5`, `1.0.0.1`. ATAYLAB:
         konfiguratsiya versiyasi shaklan AYNAN shunday ko'rinadi va HAR BIR eksportda bor,
         ya'ni kontekstsiz naqsh har bir to'plamni rad etardi (`redact.py` ga qarang).
       · server/kompyuter NOMI (`SRV-KASSA`): host nomini tovar nomidan ajratib bo'lmaydi.
       · `comment`/`synonym`/`errors` ichidagi odam yozgan HAR QANDAY matn — MIJOZ yoki XODIM
         ismi, NARX, QOLDIQ ham. Bu maydonlar 1C dan XOM keladi, naqshga tushmagani o'tadi.
       ⚠️ Ya'ni bu yuk «shaxsiy ma'lumotsiz» deb DA'VO QILINMAYDI: u faqat SIR va mashinaning
          ICHKI TUZILMASI bo'yicha tekshirilgan. Cheklov `QAMRALMAGAN_SHAKLLAR` testida
          hujjatlashtirilgan — yolg'on kafolat yozishdan ko'ra chegarani aytish yaxshi.
    ⚠️ Tekshiruv FAIL-CLOSED: shubha bo'lsa ISTISNO tashlanadi va hech narsa yuborilmaydi.
       Yolg'on ijobiy — bir marta qo'lda ko'rish; yolg'on salbiy — mijozning sirini
       tashqariga yuborish.
    ⚠️ Yukda VAQT TAMG'ASI yo'q: u bu yerda o'ylab chiqarilardi, kirishda esa yo'q.

    DETERMINIZM: graf allaqachon tartiblangan, ro'yxatlar shu tartibda ko'chiriladi, lug'at
    kalitlari esa yozishda tartiblanadi (`bundle.dumps`)."""
    _need(isinstance(graph, DiscoveryGraph),
          f"analyst_payload `DiscoveryGraph` kutadi, kelgani {type(graph).__name__}")
    _need(isinstance(concepts, (list, tuple)) and len(concepts) > 0,
          "concepts bo'sh bo'lmagan ro'yxat bo'lishi kerak")
    notanish = sorted({c for c in concepts if c not in CONCEPTS})
    _need(not notanish,
          f"noma'lum konsept(lar) {notanish} — shartnomada yo'q. Konsept ro'yxati KOD "
          f"o'zgarishi bilan kengayadi, chaqiruv bilan emas")

    payload = {
        "payload_version": AI_PAYLOAD_VERSION,
        "contract": {
            "concepts": sorted(set(concepts)),
            "statuses": list(AI_STATUSES),
            "forbidden_status": FORBIDDEN_STATUS,
            "allowed_evidence_kinds": sorted(WEAK_EVIDENCE_KINDS),
            "evidence_weights": list(EVIDENCE_WEIGHTS),
            "max_hypotheses_per_concept": str(MAX_HYPOTHESES_PER_CONCEPT),
            "max_probes_per_hypothesis": str(MAX_PROBES_PER_HYPOTHESIS),
            "probe_catalog": catalog_to_json(),
        },
        "graph": {
            "objects": [_object_payload(o) for o in graph.objects],
            "relationships": [
                {"source": r.source, "source_field": r.source_field, "target": r.target,
                 "relationship_type": r.relationship_type}
                for r in graph.relationships
            ],
            "unresolved_references": list(graph.unresolved_references),
            "stats": graph_stats(graph),
        },
    }

    findings = redaction.scan(payload)
    _need(not findings,
          "yukda sir shubhasi bor — HECH NARSA YUBORILMAYDI: "
          + "; ".join(str(f) for f in findings[:10]))
    return payload


# ── Validator ──────────────────────────────────────────────────────────────────────────────
def _confidence(v, where: str) -> float:
    """`confidence_score` — 0..1 oralig'idagi o'lchov.

    ⚠️ Bu SANOQ EMAS, shu bois «sanoqlar MATN» qoidasi unga tegishli emas: o'lchovda boshidagi
       nol ma'no tashimaydi (`0.50` va `0.5` bir xil), sanoqda esa tashiydi.
    ⚠️ `bool` RAD etiladi: Python'da `True == 1`, ya'ni `True` jimgina «to'liq ishonch» bo'lib
       o'tib ketardi.
    ⚠️ Determinizm uchun 3 kasr xonaga yaxlitlanadi: modelning uzun kasri bayt darajasida
       farqlanadigan chiqish berardi, ma'no esa o'zgarmaydi."""
    _need(isinstance(v, (int, float)) and not isinstance(v, bool),
          f"{where} son bo'lishi kerak (0..1), kelgani {v!r}")
    x = float(v)
    _need(math.isfinite(x), f"{where} chekli son bo'lishi kerak, kelgani {v!r}")
    _need(0.0 <= x <= 1.0, f"{where} 0..1 oralig'ida bo'lishi kerak, kelgani {x!r}")
    return round(x, 3)


def _field_addresses(graph: DiscoveryGraph, full_name: str) -> set[str]:
    """Obyekt ICHIDA ko'rsatilishi mumkin bo'lgan manzillar.

    ⚠️ Maydon yo'llaridan tashqari JADVAL BO'LIMI nomi va SANAB O'TILGAN QIYMAT nomi ham
       qonuniy manzil: «bu konsept shu bo'limda yashaydi» degan gipoteza ma'noli, va uni
       maydon darajasiga majburlash modelni noto'g'ri aniqlikka undardi."""
    o = graph.by_full_name(full_name)
    if o is None:
        return set()
    return ({f.path for f in o.fields} | set(o.tabular_section_names) | set(o.enum_values))


def _validate_hypothesis(raw, *, where: str, graph: DiscoveryGraph,
                         allow_human_confirmed: bool) -> Hypothesis:
    _keys(raw, HYPOTHESIS_KEYS, where)

    # ── Holat ──
    status = _nonempty(raw["status"], f"{where}.status")
    _need(status != FORBIDDEN_STATUS,
          f"{where}.status = {FORBIDDEN_STATUS!r} — RAD. Bu darajani AI ham, yig'uvchi ham "
          f"CHIQARA OLMAYDI: u faqat kuchli dalil bilan beriladi va bu kanalda kuchli dalil "
          f"yo'q. Ruxsat etilgani: {', '.join(AI_STATUSES)}")
    if status == STATUS_HUMAN_CONFIRMED and not allow_human_confirmed:
        _need(False,
              f"{where}.status = {STATUS_HUMAN_CONFIRMED!r} — RAD. Odam tasdig'i AI kanalidan "
              f"o'tmaydi: u operatorning ALOHIDA tasdiq hujjatidan keladi, modelning "
              f"ishonchidan EMAS")
    _need(status in STATUSES,
          f"{where}.status noma'lum: {status!r} — ruxsat etilgani {list(AI_STATUSES)}")

    # ── Konsept ──
    concept = _nonempty(raw["target_concept"], f"{where}.target_concept")
    _need(concept in CONCEPTS,
          f"{where}.target_concept noma'lum: {concept!r} — konsept ID lari BIZNING "
          f"shartnomamiz nomlari, ular o'ylab chiqarilmaydi")

    # ── Nomzod obyekt va maydon ──
    obj = _nonempty(raw["candidate_object"], f"{where}.candidate_object")
    _need(graph.by_full_name(obj) is not None,
          f"{where}.candidate_object grafda yo'q: {obj!r} — model obyekt O'YLAB CHIQARA "
          f"OLMAYDI. Nomzod inventarizatsiya hujjatidan kelishi SHART")

    field = raw["candidate_field"]
    _need(field is None or isinstance(field, str),
          f"{where}.candidate_field matn yoki null bo'lishi kerak")
    if field is not None:
        _nonempty(field, f"{where}.candidate_field")
        mavjud = _field_addresses(graph, obj)
        _need(field in mavjud,
              f"{where}.candidate_field {obj!r} obyektida yo'q: {field!r} — maydon nomi ham "
              f"O'YLAB CHIQARILMAYDI (obyektda bor manzillar soni: {len(mavjud)})")

    score = _confidence(raw["confidence_score"], f"{where}.confidence_score")

    # ── Dalillar ──
    # ⚠️ `allow_human_confirmed` O'ZI hech narsani ochmaydi: u faqat «manba — ODAM KANALI»
    #    degani. Dalil esa IKKI darvozadan o'tadi — TUR (`_evidence`: yagona ochiladigan kuchli
    #    tur `human_confirmed`) va HOLAT (shu yerda):
    #      · `evidence` ichida odam dalili -> faqat `HUMAN_CONFIRMED` gipotezada («tasdiqladi»),
    #      · `counter_evidence` ichida     -> faqat `REJECTED` gipotezada («rad etdi»).
    #    Sabab: tasdiq kanali AYNAN shu ikki yozuvni yasaydi (`confirmations._apply_one`), tur
    #    bilimning MANBASINI, ro'yxat esa YO'NALISHINI aytadi. `CANDIDATE` yoki `AMBIGUOUS`
    #    gipotezaga «odam ko'rdi» dalilini biriktirish tasdiqni holatdan uzib qo'yardi: hujjatda
    #    kuchli dalil ko'rinar, holat esa uni hech qayerda tasdiqlanmagan qilib qoldirardi.
    # ⚠️ ILGARI BU YERDA TESHIK BOR EDI: bayroq `_evidence` ga «kuchli dalil guruhini och» deb
    #    uzatilardi, ya'ni u `arithmetic_proof`, `contract_match`, `cross_source_agreement` va
    #    `absence_proven` ni HAM ochardi — aynan `schema.confidence_error` da `FORBIDDEN_STATUS`
    #    darajasini beradigan turlarni. Tasdiq kanali esa faqat `human_confirmed` ni yasaydi.
    evidence = _evidence_tuple(raw["evidence"], where=f"{where}.evidence",
                               allow_human=(allow_human_confirmed
                                            and status == STATUS_HUMAN_CONFIRMED))
    counter = _evidence_tuple(raw["counter_evidence"], where=f"{where}.counter_evidence",
                              allow_human=(allow_human_confirmed
                                           and status == STATUS_REJECTED))
    ambiguity = _text_tuple(raw["ambiguity"], f"{where}.ambiguity")
    confirmation = _text_tuple(raw["required_confirmation"], f"{where}.required_confirmation")

    # ── Holat <-> dalil muvofiqligi ──
    if status in (STATUS_CANDIDATE, STATUS_AMBIGUOUS):
        _need(evidence,
              f"{where}: {status} dalilsiz BO'LMAYDI — dalilsiz gipoteza shunchaki taxmin, "
              f"va taxmin hujjatga yozilmaydi (qaralmagan joy boshqa yerda UNKNOWN bo'ladi)")
        _need(confirmation,
              f"{where}: {status} uchun `required_confirmation` bo'sh bo'lmasligi kerak — "
              f"odam NIMANI ko'rishi aytilmagan gipoteza hech qachon tasdiqdan o'tmaydi")
    if status == STATUS_AMBIGUOUS:
        _need(ambiguity,
              f"{where}: AMBIGUOUS bo'lgan gipotezada `ambiguity` BO'SH BO'LMAYDI — "
              f"ikkilanish sababi aytilmasa, u ikkilanish emas, tanlovdan qochish")
    if status == STATUS_REJECTED:
        _need(counter,
              f"{where}: REJECTED bo'lgan gipotezada `counter_evidence` BO'SH BO'LMAYDI — "
              f"sababsiz rad etish ham xuddi sababsiz tasdiq kabi tekshirib bo'lmaydigan")
    if status == STATUS_HUMAN_CONFIRMED:
        # ⚠️ Odam tasdig'i AYNAN `human_confirmed` dalili bilan keladi va uning `detail` ida
        #    KIM va QACHON tasdiqlagani turadi (`schema.STRONG_EVIDENCE_KINDS` izohi).
        #    Dalilning O'ZI bor-yo'qligi SHU YERDA, `detail` ning shakli esa `_human_detail` da
        #    tekshiriladi: ilgari faqat birinchisi bajarilardi, ya'ni `detail='tasdiqlandi'`
        #    (kim YO'Q, vaqt YO'Q) qabul qilinar va tasdiq tekshirib bo'lmaydigan bo'lib qolardi.
        _need(any(e.kind == HUMAN_EVIDENCE_KIND for e in evidence),
              f"{where}: {STATUS_HUMAN_CONFIRMED} uchun `human_confirmed` dalili SHART — "
              f"kim va qachon tasdiqlagani `detail` da yozilishi kerak")

    # ── Tavsiya etilgan zondlar ──
    xom_zondlar = raw["recommended_next_probe"]
    _need(isinstance(xom_zondlar, (list, tuple)),
          f"{where}.recommended_next_probe ro'yxat bo'lishi kerak")
    # ⚠️ Zondlar KATALOG darvozasidan o'tadi: noma'lum tur, grafda yo'q nishon, sababsiz zond
    #    yoki xom kod — RAD. Tekshiruv `probe.py` da, chunki bajaruvchi tomon ham AYNAN shu
    #    qoidaga bo'ysunadi va qoida IKKI joyda takrorlanmasligi kerak.
    with _probe_gate(f"{where}.recommended_next_probe"):
        zondlar = tuple(
            p if isinstance(p, ProbeRequest)
            else probe_from_json(p, where=f"{where}.recommended_next_probe[{i}]")
            for i, p in enumerate(xom_zondlar)
        )
        zondlar = validate_probe_plan(zondlar, graph=graph,
                                      max_probes=MAX_PROBES_PER_HYPOTHESIS)

    # ⚠️ Ikkilanish sabablari va tasdiq talablari ham XOM KOD darvozasidan o'tadi: bu matnlar
    #    operatorga ko'rsatiladi va biror kun ekstraktorga izoh bo'lib ketishi mumkin.
    with _probe_gate(where):
        for i, s in enumerate(ambiguity):
            assert_no_raw_code(s, where=f"{where}.ambiguity[{i}]")
        for i, s in enumerate(confirmation):
            assert_no_raw_code(s, where=f"{where}.required_confirmation[{i}]")
    # ⚠️ Redaksiya darvozasi ham SHU IKKI matnga qo'llanadi (dalil `detail` i bilan bir xil
    #    sabab): ular hujjat baytlariga yoziladi va artefakt bilan birga tarqaydi. Ilgari bu
    #    matnlar faqat XOM KOD darvozasidan o'tardi, ya'ni ichidagi parol yoki ulanish satri
    #    jimgina o'tib ketardi.
    for i, s in enumerate(ambiguity):
        _no_secret(s, f"{where}.ambiguity[{i}]")
    for i, s in enumerate(confirmation):
        _no_secret(s, f"{where}.required_confirmation[{i}]")

    return Hypothesis(
        target_concept=concept,
        candidate_object=obj,
        candidate_field=field,
        confidence_score=score,
        evidence=evidence,
        counter_evidence=counter,
        ambiguity=ambiguity,
        required_confirmation=confirmation,
        recommended_next_probe=zondlar,
        status=status,
    )


class AnalysisResult(list):
    """`validate_analysis` natijasi: gipotezalar RO'YXATI + analitikning `notes` i.

    `list` dan MEROS ataylab: natija avvalgidek oddiy ro'yxat bo'lib ishlaydi (`len`, iteratsiya,
    `== []`, tartiblash), ya'ni chaqiruvchilarning birortasi o'zgarmaydi — lekin `notes` endi
    YO'QOLMAYDI.

    `notes` GA QANDAY YETILADI:
        natija = validate_analysis(raw, graph=graph)
        natija.notes              # tuple[str, ...] — analitik yozgan TARTIBDA, tekshirilgan
        analysis_notes(natija)    # AYNAN o'sha, lekin oddiy ro'yxat berilsa ham ishlaydi

    KO'RIK ARTEFAKTIGA (`review.py` — U BOSHQA MODUL, bu yerdan chaqirilmaydi):
        review.build_review(natija, graph=graph, analyzer_name=..., analyzer_version=...,
                            analyzer_notes=analysis_notes(natija))
    ya'ni `build_review` ning `analyzer_notes` parametriga AYNAN shu tuple beriladi. Izohlar
    tartiblanmaydi va birlashtirilmaydi, chunki artefaktda ular yozilgan navbatda o'qiladi.

    ⚠️ NEGA `notes` CHIQISHGA KERAK: analitik kesilgan nomzodlar haqida AYNAN shu yerda xabar
       beradi («nomzodlar soni chegaraga qisilgan konseptlar»). Ilgari `notes` talab qilinar,
       tekshirilar va keyin JIMGINA TASHLANARDI — ya'ni `keep_window`/`max_per_concept` tufayli
       olib tashlangan ishonchli nomzodning YAGONA yozuvi yo'qolardi va operator artefaktda
       hech narsa kesilganini BILMASDI. Bu «no silent caps» qoidasining buzilishi edi.
    ⚠️ `notes` XULOSA EMAS: undan daraja ham, xarita ham o'qilmaydi. U faqat ko'rik artefaktiga
       yoziladigan izoh (`review.build_review` uni shu yerdan oladi)."""

    __slots__ = ("notes",)

    def __init__(self, rows=(), *, notes=()):
        super().__init__(rows)
        self.notes: tuple[str, ...] = tuple(notes)


def analysis_notes(result) -> tuple[str, ...]:
    """Tahlil natijasining `notes` i — oddiy ro'yxat berilsa bo'sh tuple.

    ⚠️ ATAYLAB KECHIRIMLI: chaqiruvchi (masalan `review.build_review`) gipotezalarni qo'lda
       yig'ilgan ro'yxat bilan ham bera oladi, va bunda «izoh yo'q» — XATO EMAS. Lekin
       `validate_analysis` dan kelgan natijada izoh BOR bo'lsa, u shu yo'l bilan artefaktga
       o'tadi va jimgina tashlanmaydi."""
    izohlar = getattr(result, "notes", ())
    _need(isinstance(izohlar, tuple) and all(isinstance(s, str) for s in izohlar),
          f"notes matnlar tuple'i bo'lishi kerak, kelgani {type(izohlar).__name__}")
    return izohlar


def _analysis_rows(raw) -> tuple[list, tuple[str, ...]]:
    """Chiqishning tashqi qobig'i: to'liq hujjat yoki shunchaki gipotezalar ro'yxati.

    Qaytaradi: `(gipotezalar, notes)`.

    ⚠️ Ikki shakl ATAYLAB qabul qilinadi: qobiq (`analysis_version`) BIZNING qo'shimchamiz,
       modelning ishi esa gipotezalar. Qobiqni majburlash ulagichni versiyani O'ZI yozishga
       undardi, ya'ni versiya modelning so'ziga aylanardi. Ichki tekshiruv esa ikki holatda
       ham AYNAN bir xil qat'iy.
    ⚠️ Qobiqsiz shaklda `notes` YO'Q va bu bo'sh tuple bilan ko'rsatiladi — «izoh yozilmadi»
       degani, «izoh tashlandi» degani EMAS."""
    if isinstance(raw, (list, tuple)):
        return list(raw), ()
    _keys(raw, ANALYSIS_KEYS, "analysis")
    _need(raw["analysis_version"] == ANALYSIS_VERSION,
          f"analysis.analysis_version {ANALYSIS_VERSION!r} bo'lishi kerak, "
          f"kelgani {raw['analysis_version']!r}")
    _need(isinstance(raw["hypotheses"], (list, tuple)),
          "analysis.hypotheses ro'yxat bo'lishi kerak")
    # ⚠️ `notes` tekshiriladi va CHIQISHGA o'tadi (`AnalysisResult.notes`), lekin gipotezaga
    #    aylanmaydi: u operator uchun izoh va uning ichida XULOSA bo'lishi mumkin emas. Izohdan
    #    xulosa o'qish — dalilsiz tasdiq. Ilgari izoh bu yerda tekshirilar va shu zahoti
    #    tashlanardi; kesilgan nomzod haqidagi yagona xabar shunda yo'qolardi.
    izohlar = _notes_tuple(raw["notes"], "analysis.notes")
    with _probe_gate("analysis.notes"):
        for i, s in enumerate(izohlar):
            assert_no_raw_code(s, where=f"analysis.notes[{i}]")
    for i, s in enumerate(izohlar):
        _no_secret(s, f"analysis.notes[{i}]")
    return list(raw["hypotheses"]), izohlar


def validate_analysis(raw, *, graph: DiscoveryGraph,
                      allow_human_confirmed: bool = False) -> AnalysisResult:
    """AI chiqishini ISHONMASDAN tekshiradi. Xato — `AnalysisError`.

    `allow_human_confirmed=False` (ODATIY) — AI kanali: `HUMAN_CONFIRMED` ham, kuchli dalil
    ham RAD etiladi. `VERIFIED` esa har qanday rejimda RAD.

    `allow_human_confirmed=True` — manba OPERATORNING ALOHIDA TASDIQ HUJJATI. Faqat shu
    rejimda `HUMAN_CONFIRMED` va kuchli dalil turlari qabul qilinadi.
    ⚠️ Bu bayroqni model chiqishiga QO'YIB BO'LMAYDI: uni chaqiruvchi kod, tasdiq hujjatini
       o'qiyotganini bilgan holda, o'zi beradi. Bayroq chiqish ICHIDAN kelmaydi — aks holda
       model o'zini «odam tasdig'i» deb e'lon qilardi.

    Qaytaradi: DETERMINISTIK tartibdagi `AnalysisResult` — `Hypothesis` larning ro'yxati
    (oddiy `list` bo'lib ishlaydi) va analitikning izohlari `.notes` da (`analysis_notes()`
    ham shuni beradi). ⚠️ Izoh CHIQISHDA qoladi, chunki kesilgan nomzod haqidagi yagona xabar
    aynan izohda keladi — u tashlansa, operator hech narsa kesilganini bilmasdi.
    Kirish O'ZGARTIRILMAYDI."""
    _need(isinstance(graph, DiscoveryGraph),
          f"validate_analysis `DiscoveryGraph` kutadi, kelgani {type(graph).__name__}")
    rows, izohlar = _analysis_rows(raw)

    hyps = [
        _validate_hypothesis(r, where=f"analysis.hypotheses[{i}]", graph=graph,
                             allow_human_confirmed=allow_human_confirmed)
        for i, r in enumerate(rows)
    ]

    # ⚠️ Bir MANZIL uchun ikki gipoteza — RAD. Ular bir-birini jimgina almashtirardi yoki
    #    bir xil narsa haqida ikki xil daraja berardi; ikkilanish esa `AMBIGUOUS` bilan
    #    aytiladi, takror yozuv bilan emas.
    manzillar = [(h.target_concept, h.address) for h in hyps]
    dupes = sorted({f"{c} <- {a}" for c, a in manzillar if manzillar.count((c, a)) > 1})
    _need(not dupes,
          f"bir manzil uchun bir nechta gipoteza: {dupes} — ikkilanish AMBIGUOUS bilan "
          f"aytiladi, takror yozuv bilan emas")

    # ⚠️ Konsept bo'yicha chegara: har obyektni nomzod qilib sanash tahlil emas.
    for concept in sorted({h.target_concept for h in hyps}):
        soni = sum(1 for h in hyps if h.target_concept == concept)
        _need(soni <= MAX_HYPOTHESES_PER_CONCEPT,
              f"{concept!r} uchun {soni} ta gipoteza — chegara {MAX_HYPOTHESES_PER_CONCEPT}. "
              f"Model tanlashi va tanlab bo'lmaganini AMBIGUOUS deb aytishi kerak")

    return AnalysisResult(sorted(hyps, key=lambda h: h.sort_key), notes=izohlar)


# ── Chiqish ────────────────────────────────────────────────────────────────────────────────
def unknown_concepts(hyps) -> tuple[str, ...]:
    """Birorta gipoteza tegmagan konseptlar — ular `UNKNOWN` bo'lib yoziladi.

    ⚠️ Bu ro'yxat ATAYLAB bor: qaralmagan konseptni jimgina tashlab ketish «yo'q» degan
       xulosaga o'xshab qolardi. «Qaralmadi» va «yo'q» bir xil narsa emas, va farqni faqat
       shu ro'yxat saqlaydi."""
    qamralgan = {h.target_concept for h in hyps}
    return tuple(c for c in sorted(CONCEPTS) if c not in qamralgan)


def _evidence_to_json(e: Evidence) -> dict:
    return {"kind": e.kind, "detail": e.detail, "weight": e.weight}


def hypothesis_to_json(h: Hypothesis) -> dict:
    """Bitta gipotezaning determinstik lug'ati."""
    _need(isinstance(h, Hypothesis),
          f"hypothesis_to_json `Hypothesis` kutadi, kelgani {type(h).__name__}")
    return {
        "target_concept": h.target_concept,
        "candidate_object": h.candidate_object,
        "candidate_field": h.candidate_field,
        # ⚠️ Yaxlitlangan o'lchov (validatorda 3 kasr xona) — bir xil kirish bir xil bayt beradi.
        "confidence_score": h.confidence_score,
        "evidence": [_evidence_to_json(e) for e in h.evidence],
        "counter_evidence": [_evidence_to_json(e) for e in h.counter_evidence],
        "ambiguity": list(h.ambiguity),
        "required_confirmation": list(h.required_confirmation),
        "recommended_next_probe": [probe_to_json(p) for p in h.recommended_next_probe],
        "status": h.status,
    }


def hypotheses_to_json(hyps) -> dict:
    """Gipotezalarni hujjatga aylantiradi — DETERMINISTIK va TASHLAMASDAN.

    ⚠️ `concepts_unknown` — qaralmagan konseptlar. Ular hujjatda OCHIQ turadi, chunki
       tushirib qoldirilgan konsept keyinchalik «tekshirilgan va topilmagan» deb o'qilardi.
    ⚠️ Sanoqlar MATN (`binos-1c-metadata-v1` 1-invarianti bilan bir xil sabab).
    ⚠️ Bu funksiya QAYTA TEKSHIRMAYDI: kirishda faqat `validate_analysis` qaytargan
       `Hypothesis` obyektlari bo'lishi kerak, xom lug'at emas. Shu bois tekshirilmagan
       ma'lumot bu yo'l bilan hujjatga tusha olmaydi."""
    _need(isinstance(hyps, (list, tuple)), "hypotheses_to_json ro'yxat kutadi")
    # ⚠️ TUR TEKSHIRUVI TARTIBLASHDAN OLDIN: `sort_key` — `Hypothesis` ning xossasi, ya'ni xom
    #    lug'at berilsa tartiblash `AttributeError` bilan yiqilardi va tekshiruvga umuman
    #    yetib borilmasdi. Chaqiruvchi esa bu kanalning xatosini bitta `except AnalysisError`
    #    bilan ushlaydi, ya'ni o'ralmagan `AttributeError` uni chetlab o'tardi.
    for i, h in enumerate(hyps):
        _need(isinstance(h, Hypothesis),
              f"hypotheses_to_json[{i}] `Hypothesis` kutadi, kelgani {type(h).__name__} — "
              f"bu funksiya QAYTA TEKSHIRMAYDI, shu bois xom lug'at umuman qabul qilinmaydi")
    rows = sorted(hyps, key=lambda h: h.sort_key) if hyps else []
    holat_bo_yicha: dict[str, int] = {}
    for h in rows:
        holat_bo_yicha[h.status] = holat_bo_yicha.get(h.status, 0) + 1

    return {
        "analysis_version": ANALYSIS_VERSION,
        "hypotheses": [hypothesis_to_json(h) for h in rows],
        "concepts_unknown": list(unknown_concepts(rows)),
        "counts": {
            "hypotheses": str(len(rows)),
            "by_status": {k: str(holat_bo_yicha[k]) for k in sorted(holat_bo_yicha)},
            "concepts_unknown": str(len(unknown_concepts(rows))),
        },
    }
