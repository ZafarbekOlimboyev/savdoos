# -*- coding: utf-8 -*-
"""DETERMINISTIK ANALITIK — `ai.DiscoveryAIAnalyzer` protokolining model'siz bajarilishi.

⚠️ BU FAYL YADRODAN TASHQARIDA. Yadro (`discovery_1c` ning o'zi) bu paketni import qilmaydi:
   bog'liqlik BIR TOMONLAMA. Sabab — TALQIN bilimi (ko'p tilli lug'at, konsept kutilmalari)
   deterministik yadrodan AJRATILGAN bo'lishi kerak, aks holda taxmin dalilga o'xshab qolardi.

⚠️ TARMOQ YO'Q, MODEL YO'Q, SIR YO'Q. `HeuristicAnalyzer` faqat `ai.analyst_payload` qaytargan
   lug'atni o'qiydi. U bir vaqtda ikki narsa: testlar uchun ishonchli «fake» va haqiqiy
   ASOSIY CHIZIQ — kelajakdagi model shu chiziqdan yaxshi ishlashini isbotlashi kerak.

PROVAYDER ABSTRAKSIYASI. `ai.DiscoveryAIAnalyzer` — `analyze(payload) -> dict` shaklidagi
Protocol. Kelajakda Claude, OpenAI, Gemini yoki mahalliy model ulagichi AYNAN shu protokolni
bajarib ulanishi mumkin: ulagich yukni oladi, xom lug'at qaytaradi, yadro esa unga ISHONMASDAN
`ai.validate_analysis` bilan tekshiradi. Bu faylda bunday ulagich KODI YOZILMAYDI — u alohida
qadam va u tarmoqqa chiqadigan yagona joy bo'ladi.

QAT'IY QOIDALAR:
  · `VERIFIED` ham, `HUMAN_CONFIRMED` ham CHIQMAYDI. Eng yuqorisi — `CANDIDATE`.
    Buni `_assert_no_forbidden_status` import paytidagi jadval tekshiruvi kabi qat'iy
    ushlaydi va u chiqishda HAR SAFAR bajariladi.
  · DALILSIZ GIPOTEZA CHIQMAYDI: musbat omil topilmasa nomzod umuman yozilmaydi.
  · Ball TUSHUNTIRILADI: har omilning NOMI va HISSASI dalilning `detail` ida turadi, ya'ni
    `confidence_score` qanday yig'ilgani hujjatdan o'qiladi. Ball TALQIN emas, hisob.
  · IKKILANISH YASHIRILMAYDI: bir konsept uchun ikki yoki ko'proq nomzodning bali yaqin bo'lsa
    holat `AMBIGUOUS` bo'ladi va `ambiguity` ga IKKALA nomzod yoziladi. Jimgina bittasini
    tanlash TAQIQLANGAN.
  · QARALMAGAN KONSEPT TASHLANMAYDI: `coverage()` har konseptning holatini qaytaradi va
    nomzodsiz qolganini `UNKNOWN` deb ATAYDI. «Qaralmadi» va «yo'q» bir xil narsa emas.
  · Determinizm: bir xil graf -> AYNAN bir xil gipotezalar, tartiblangan.
  · Vaqt O'YLAB CHIQARILMAYDI: bu faylda vaqt tamg'asi umuman yo'q.

BALL QANDAY YIG'ILADI (tushuntirish, sehr emas):

    confidence_score = 0..1 ga qisilgan (musbat omillar yig'indisi - qarshi omillar yig'indisi)

Omillar mustaqil va har biri ALOHIDA dalil bo'lib yoziladi: leksik moslik (KUCHSIZ), obyekt
turining kutilmaga mosligi, munosabat dalili (kim kimga havola qiladi), tip shakli, registr
shakli va sanoq mantiqiyligi. Qarshi omillar ham xuddi shunday ochiq: chalg'ituvchi nom,
ierarxiya (papka bo'lishi mumkin), havolaning yo'qligi, kutilgan maydonning yo'qligi.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field as dc_field

from ..ai import (AI_PAYLOAD_VERSION, ANALYSIS_VERSION, CONCEPTS, FORBIDDEN_STATUS,
                  MAX_HYPOTHESES_PER_CONCEPT, MAX_PROBES_PER_HYPOTHESIS, STATUS_AMBIGUOUS,
                  STATUS_CANDIDATE, STATUS_HUMAN_CONFIRMED, STATUS_REJECTED, WEIGHT_WEAK,
                  AnalysisError, analyst_payload, unknown_concepts, validate_analysis)
from ..probe import PROBE_CATALOG, TARGET_SEP as PROBE_TARGET_SEP
from .lexicon import (ANY_CONCEPT, CONCEPT_CLUES, MISLEADING_CLUES, LexiconError, lexical_score,
                      misleading_hits, tokens, type_matches)


class AnalystError(AnalysisError):
    """Analitikka berilgan yuk tushunarli emas yoki jadvallari shartnomaga mos emas.

    `ai.AnalysisError` dan meros: chaqiruvchi tahlil kanalining hamma xatosini bitta `except`
    bilan ushlaydi."""


# ── Obyekt turi bo'yicha kutilmalar ────────────────────────────────────────────────────────
#: Konsept -> shu konsept yashashi MUMKIN bo'lgan 1C obyekt turlari (`schema.SOURCE_KINDS`).
#: ⚠️ Bu RO'YXAT, tanlov emas: bitta konsept bir necha turda yashashi mumkin (masalan narx
#:    registrda ham, katalog rekvizitida ham bo'ladi). Ro'yxatga tushmagan tur — QARSHI DALIL,
#:    RAD emas: kengaytirilgan konfiguratsiyada g'ayrioddiy joylashuv uchraydi.
CONCEPT_OBJECT_KINDS: dict[str, tuple[str, ...]] = {
    "barcode": ("catalog", "information_register"),
    "batch_lot": ("accumulation_register", "catalog"),
    "cash_register": ("catalog", "document"),
    "cost": ("accumulation_register", "information_register"),
    "counterparty": ("catalog",),
    "customer": ("catalog",),
    "employee_cashier": ("catalog",),
    "expiry_date": ("catalog", "information_register"),
    "goods_receipt": ("document",),
    "price": ("catalog", "information_register"),
    "product": ("catalog",),
    "product_variant": ("catalog", "chart_of_characteristic_types"),
    "sale_document": ("document",),
    "sales_return": ("document",),
    "scale_plu": ("catalog", "information_register"),
    "sku_article": ("catalog",),
    "stock_balance": ("accumulation_register",),
    "stock_movement": ("accumulation_register", "document"),
    "supplier": ("catalog",),
    "tax_vat": ("catalog", "enum", "information_register"),
    "unit_of_measure": ("catalog", "enum"),
    "warehouse": ("catalog",),
    "weighted_product": ("catalog",),
}

#: Maydon darajasida ham qidiriladigan konseptlar (rekvizit, o'lchov, resurs yoki jadval
#: bo'limi). Qolganlari faqat OBYEKT darajasida qidiriladi.
FIELD_LEVEL_CONCEPTS = ("barcode", "batch_lot", "cost", "expiry_date", "price",
                        "product_variant", "scale_plu", "sku_article", "tax_vat",
                        "unit_of_measure", "weighted_product")

#: Maydoni MAHSULOT katalogida turishi kutiladigan konseptlar.
#: ⚠️ Shu ro'yxat struktura dalilini maydon darajasiga olib kiradi: nomi hech narsa demaydigan
#:    maydon mahsulot nomzodi katalogida turgani uchun ham nomzod bo'la oladi.
PRODUCT_FIELD_CONCEPTS = ("barcode", "batch_lot", "expiry_date", "product_variant", "scale_plu",
                          "sku_article", "unit_of_measure", "weighted_product")

#: Mahsulot katalogiga HAVOLA QILISHI kutiladigan konseptlar.
#: ⚠️ ENG KUCHLI STRUKTURA SIGNALI SHU YERDA: qoldiq va barkod registrlari mahsulot katalogiga
#:    havola qiladi. Shu bois NOMSIZ (yoki tanib bo'lmaydigan nomli) konfiguratsiyada ham
#:    «ko'p registr havola qiladigan katalog» mahsulot nomzodi bo'la oladi, undan keyin esa
#:    unga havola qiladiganlar o'z konseptlariga nomzod bo'ladi.
REFERENCES_PRODUCT = ("barcode", "batch_lot", "cost", "goods_receipt", "price", "sale_document",
                      "sales_return", "scale_plu", "stock_balance", "stock_movement",
                      "weighted_product")

#: Registr turi kutilmasi (`metadata.REGISTER_KINDS`).
CONCEPT_REGISTER_KIND: dict[str, str] = {
    "cost": "balance",
    "stock_balance": "balance",
    "stock_movement": "turnover",
}

#: Maydon tipining kutilgan TURKUMI (`lexicon.TYPE_CLUES` kalitlari).
CONCEPT_TYPE_KIND: dict[str, str] = {
    "barcode": "string",
    "cost": "number",
    "expiry_date": "date",
    "price": "number",
    "scale_plu": "number",
    "sku_article": "string",
    "tax_vat": "number",
    "weighted_product": "boolean",
}

#: Satr uzunligi oralig'i (ikki chegara ham QO'SHILADI).
#: ⚠️ Barkod uchun 8..14: qisqa (EAN-8) dan uzun (EAN-13 va ichki prefiksli) gacha. Oraliqdan
#:    tashqarida bo'lishi QARSHI DALIL, RAD emas — konfiguratsiya maydonni ataylab kengroq
#:    e'lon qilgan bo'lishi mumkin.
CONCEPT_STRING_LEN: dict[str, tuple[int, int]] = {"barcode": (8, 14)}

#: Maydonning kasr xona soni kutilmasi (MATN — sanoqlar hujjatda matn bo'lib keladi).
CONCEPT_NUMERIC_SCALE: dict[str, tuple[str, ...]] = {"cost": ("2",), "price": ("2",)}

#: Registr RESURSining kasr xona soni kutilmasi.
CONCEPT_RESOURCE_SCALE: dict[str, tuple[str, ...]] = {
    "cost": ("2",),
    "price": ("2",),
    "stock_balance": ("3",),
    "stock_movement": ("3",),
}

#: Ierarxiya (papka/sinf) shubhasi bo'ladigan konseptlar.
HIERARCHY_SUSPECT = ("batch_lot", "cash_register", "counterparty", "customer",
                     "employee_cashier", "product", "supplier", "unit_of_measure", "warehouse")

#: Sanoq mantiqiyligi: katta ro'yxat kutiladigan va kichik ro'yxat kutiladigan konseptlar.
ROW_COUNT_LARGE = ("barcode", "product")
ROW_COUNT_SMALL = ("cash_register", "employee_cashier", "unit_of_measure", "warehouse")
ROW_COUNT_LARGE_MIN = 100
ROW_COUNT_SMALL_MAX = 1000

#: Registr turlari — «kim havola qiladi» hisobida faqat shular sanaladi.
REGISTER_KINDS_SET = ("accumulation_register", "information_register")


# ── Omil vaznlari ──────────────────────────────────────────────────────────────────────────
#: ⚠️ Vaznlar ATAYLAB bitta joyda va OCHIQ: ball «model shunday dedi» emas, shu jadvalning
#:    yig'indisi. Vaznni o'zgartirish — ko'rinadigan o'zgarish, va uni testlar qulflaydi.
#: ⚠️ LEKSIK VAZNLARNING YIG'INDISI O'ZI BILAN 1.0 GA YETADI, va bu ataylab EMAS edi:
#:    `W_NAME + W_SYNONYM + W_OBJECT_KIND + W_CARDINALITY` = 1.00, ya'ni nomi va sinonimi
#:    mukammal mos, turi kutilgan va sanog'i mantiqiy bo'lgan katalog struktura dalili
#:    BO'LMASA HAM eng yuqori ballni olardi. Qarshi omillar bu yerda YORDAM BERMAYDI:
#:    `C_NO_REFERENCE` faqat `product` konseptida qo'llanadi, qolgan 22 konsept uchun
#:    havolaning yo'qligi hech qanday jarima bermaydi.
#: ⚠️ SHU BOIS chegara ALOHIDA turadi: `NO_STRUCTURE_CEILING` — struktura dalili bo'lmagan
#:    nomzodning yuqori chegarasi. U jadvalning o'zini o'zgartirmaydi, oshiqchasini OCHIQ
#:    qarshi omil qilib yozadi (`_cap_lexical`), ya'ni ball baribir omillar yig'indisi
#:    bo'lib qoladi.
W_NAME = 0.45
W_SYNONYM = 0.30
W_COMMENT = 0.10
W_FIELD_NAME = 0.45
W_FIELD_SYNONYM = 0.25
W_OBJECT_KIND = 0.20
W_REGISTER_KIND = 0.15
W_REL_PRODUCT = 0.30
W_REL_TO_PRODUCT = 0.30
W_REL_WAREHOUSE = 0.15
W_TYPE_SHAPE = 0.20
W_VALUE_DOMAIN = 0.25
W_RESOURCE_SHAPE = 0.20
W_CARDINALITY = 0.10
W_IN_PRODUCT_OBJECT = 0.20

C_MISLEADING = 0.20
C_MISLEADING_MAX_HITS = 2
C_HIERARCHICAL = 0.10
C_NO_REFERENCE = 0.20
C_WRONG_KIND = 0.25
C_WRONG_REGISTER_KIND = 0.10
C_WRONG_TYPE = 0.15
C_OUT_OF_DOMAIN = 0.20
C_MISSING_RESOURCE = 0.20
C_WRONG_CARDINALITY = 0.10
C_REFERENCE_FIELD = 0.30

#: Musbat omillar yig'indisi shundan kichik bo'lsa gipoteza UMUMAN chiqarilmaydi.
#: ⚠️ Chegara bor, chunki juda kuchsiz nomzod operatorning vaqtini yeydi va ro'yxatni shovqin
#:    bilan to'ldiradi. Chegaradan o'tmagan nomzod «RAD etilgan» EMAS — u shunchaki qaralmagan,
#:    va konsept nomzodsiz qolsa `coverage()` uni `UNKNOWN` deb ataydi.
MIN_POSITIVE = 0.12

#: Leksik dalil UMUMAN bo'lmaganda talab qilinadigan chegara.
#: ⚠️ IKKI CHEGARA ATAYLAB. Obyekt turining kutilmaga mos kelishi O'ZI BILAN dalil EMAS:
#:    har katalog har «katalogda yashaydigan» konseptga nomzod bo'lib ketardi, ya'ni ro'yxat
#:    ko'chirilardi, tahlil qilinmasdi. Shu bois nomsiz (tanib bo'lmaydigan nomli) nomzod
#:    o'tishi uchun HAQIQIY struktura vazni kerak — masalan munosabat dalili bilan birga.
MIN_POSITIVE_STRUCTURAL = 0.45

#: Leksik dalil bera oladigan omillar. Qolganlari faqat QO'LLAB-QUVVATLAYDI.
LEXICAL_FACTOR_NAMES = ("maydon nomi", "maydon sinonimi", "obyekt izohi", "obyekt nomi",
                        "obyekt sinonimi")

#: STRUKTURA DALILI BO'LMAGAN nomzodning YUQORI CHEGARASI.
#: ⚠️ NEGA KERAK: nomi va sinonimi mukammal mos katalog (turi kutilgan, sanog'i mantiqiy)
#:    struktura dalilisiz ham 1.000 ball olardi — ya'ni LEKSIK MOSLIK O'ZI BILAN eng yuqori
#:    ishonchga yetardi. Bu modulning birinchi qoidasiga («leksik moslik KUCHSIZ dalil»)
#:    to'g'ridan-to'g'ri zid, va `confidence_score` odam ko'rigining NAVBATINI belgilagani
#:    uchun zarari ham amaliy: tekshirilmagan taxmin navbatning boshiga chiqardi.
#: ⚠️ CHEGARA JIMGINA QIRQMAYDI: oshiqcha qism `_cap_lexical` da OCHIQ qarshi omil bo'lib
#:    yoziladi (`leksik to'yinish`), ya'ni ball baribir omillar yig'indisi bo'lib qoladi va
#:    hujjatdan O'QILADI.
#: ⚠️ Chegara RAD ETMAYDI va nomzodni ro'yxatdan chiqarmaydi — u faqat «bu nomzod hali
#:    strukturaga tayanmaydi» degan haqiqatni ballda ko'rsatadi.
NO_STRUCTURE_CEILING = 0.60

#: Eng yaxshi nomzoddan shundan ko'proq orqada qolgan nomzod ro'yxatdan chiqariladi.
#: ⚠️ NEGA KERAK: kuchli nomzod bor joyda kuchsiz nomzodlarni ham yozib chiqish «hammasini
#:    sanab chiqish» bo'lardi. Kuchli nomzod YO'Q bo'lsa (masalan nomlar tanib bo'lmaydigan
#:    bo'lsa) darcha hech narsani kesmaydi va kuchsiz nomzodlar ro'yxatda qoladi — aynan shunda
#:    ular ma'lumot beradi.
#: ⚠️ Darchadan chiqib ketgan nomzod «RAD etilgan» EMAS: konsept nomzodsiz qolmagani uchun
#:    `coverage()` uni `UNKNOWN` ham demaydi. U shunchaki navbatda orqada.
KEEP_WINDOW = 0.25

#: Ikki nomzod bali shundan yaqin bo'lsa — `AMBIGUOUS`.
#: ⚠️ Chegara ataylab SEZGIR: yaqin ballni jimgina tartiblab bittasini tanlash — aynan
#:    «jimgina taxmin», va u taqiqlangan.
AMBIGUITY_DELTA = 0.08

#: Mahsulot nomzodi bo'lishi uchun kerak bo'lgan eng kichik registr havolalari soni.
PRODUCT_REF_MIN = 2
#: Registr havolasi yetmasa, zaxira sifatida olinadigan eng ko'p katalog soni.
PRODUCT_FALLBACK_MAX = 3


# ── Omil ───────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Factor:
    """Bitta baholash omili: nomi, dalil turi, HISSASI va sababi.

    `score` ISHORALI: musbat — dalil, manfiy — qarshi dalil. Hissа dalilning `detail` iga
    yoziladi, ya'ni ball qanday yig'ilgani hujjatdan O'QILADI."""

    name: str
    kind: str
    score: float
    why: str

    @property
    def detail(self) -> str:
        return f"{self.name}: {self.why} (hissa {self.score:+.3f})"

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.name, self.why)


def _evidence_json(factors) -> list[dict]:
    """Omillarni dalil lug'atlariga aylantiradi — tartiblangan.

    ⚠️ Vazn HAR DOIM `weak`: bu qatlam KUCHLI dalil turini chiqara olmaydi va chiqarmasligi
       kerak (`ai._evidence` buni ushlaydi). Avtomat o'zini o'zi tasdiqlay olmaydi."""
    return [{"kind": f.kind, "detail": f.detail, "weight": WEIGHT_WEAK}
            for f in sorted(factors, key=lambda x: x.sort_key)]


# ── Yuk indeksi ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Index:
    """Yukdan bir marta hisoblangan qidiruv indeksi.

    ⚠️ `product_like` — FAQAT STRUKTURA bo'yicha topilgan nomzodlar: nomga umuman qaralmaydi.
       Shu bois u tanib bo'lmaydigan nomli konfiguratsiyada ham ishlaydi, va u LEKSIK dalildan
       MUSTAQIL — ikki mustaqil signal ustma-ust tushsa ball ikki omildan yig'iladi."""

    objects: tuple[dict, ...]
    ref_in: dict[str, tuple[str, ...]] = dc_field(default_factory=dict)
    ref_out: dict[str, tuple[str, ...]] = dc_field(default_factory=dict)
    reg_ref_in: dict[str, tuple[str, ...]] = dc_field(default_factory=dict)
    product_like: tuple[str, ...] = ()


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise AnalystError(msg)


def _text(v) -> str:
    return v if isinstance(v, str) else ""


def _int_or_none(v) -> int | None:
    """Sanoq MATNIDAN butun son. `None` — «yig'uvchi sanamadi», 0 EMAS."""
    if not isinstance(v, str) or not v.isdigit():
        return None
    return int(v)


def _build_index(payload) -> _Index:
    """Yukni tekshiradi va indeks quradi. Tushunarsiz yuk — RAD (fail-closed).

    ⚠️ Yuk versiyasi tekshiriladi: boshqa shakldagi lug'atni «iloji boricha» o'qish jimgina
       bo'sh tahlil berardi, bo'sh tahlil esa «hech narsa topilmadi» deb o'qilardi."""
    _need(isinstance(payload, dict), f"yuk lug'at bo'lishi kerak, kelgani {type(payload).__name__}")
    _need(payload.get("payload_version") == AI_PAYLOAD_VERSION,
          f"yuk versiyasi {AI_PAYLOAD_VERSION!r} bo'lishi kerak, "
          f"kelgani {payload.get('payload_version')!r}")
    graph = payload.get("graph")
    _need(isinstance(graph, dict), "yuk.graph lug'at bo'lishi kerak")
    objects = graph.get("objects")
    relationships = graph.get("relationships")
    _need(isinstance(objects, list), "yuk.graph.objects ro'yxat bo'lishi kerak")
    _need(isinstance(relationships, list), "yuk.graph.relationships ro'yxat bo'lishi kerak")
    contract = payload.get("contract")
    _need(isinstance(contract, dict) and isinstance(contract.get("concepts"), list),
          "yuk.contract.concepts ro'yxat bo'lishi kerak")

    turlar = {_text(o.get("full_name")): _text(o.get("kind")) for o in objects}
    kiruvchi: dict[str, set[str]] = {}
    chiquvchi: dict[str, set[str]] = {}
    registrdan: dict[str, set[str]] = {}
    for r in relationships:
        if not isinstance(r, dict) or r.get("relationship_type") != "references":
            continue
        manba, nishon = _text(r.get("source")), _text(r.get("target"))
        if not manba or not nishon:
            continue
        kiruvchi.setdefault(nishon, set()).add(manba)
        chiquvchi.setdefault(manba, set()).add(nishon)
        if turlar.get(manba) in REGISTER_KINDS_SET:
            registrdan.setdefault(nishon, set()).add(manba)

    # ⚠️ Mahsulot nomzodlari FAQAT strukturadan: eng ko'p registr havola qiladigan kataloglar.
    #    Teng hollarda to'liq nom bo'yicha tartiblanadi — determinizm uchun.
    kataloglar = [o for o in objects if _text(o.get("kind")) == "catalog"]
    tartib = sorted(
        kataloglar,
        key=lambda o: (-len(registrdan.get(_text(o.get("full_name")), ())),
                       -len(kiruvchi.get(_text(o.get("full_name")), ())),
                       _text(o.get("full_name"))),
    )
    kuchli = [_text(o.get("full_name")) for o in tartib
              if len(registrdan.get(_text(o.get("full_name")), ())) >= PRODUCT_REF_MIN]
    if not kuchli:
        # Zaxira: registr havolasi kam bo'lsa ham eng ko'p havola olgan kataloglar nomzod
        # bo'la oladi. ⚠️ Havolasi UMUMAN yo'q katalog nomzod bo'lmaydi — bunday katalogda
        # struktura dalili yo'q, faqat nom qoladi va nom o'zi bilan yetarli emas.
        kuchli = [_text(o.get("full_name")) for o in tartib
                  if kiruvchi.get(_text(o.get("full_name")))][:PRODUCT_FALLBACK_MAX]

    return _Index(
        objects=tuple(objects),
        ref_in={k: tuple(sorted(v)) for k, v in sorted(kiruvchi.items())},
        ref_out={k: tuple(sorted(v)) for k, v in sorted(chiquvchi.items())},
        reg_ref_in={k: tuple(sorted(v)) for k, v in sorted(registrdan.items())},
        product_like=tuple(sorted(kuchli)),
    )


# ── Leksik omillar ─────────────────────────────────────────────────────────────────────────
def _lexical_factor(concept: str, text: str, *, name: str, kind: str, weight: float):
    """Matnning leksik mosligini omilga aylantiradi, yoki `None` (moslik yo'q).

    ⚠️ Bu omil KUCHSIZ. Uning o'zi bilan chiqqan gipoteza ham `CANDIDATE` dan oshmaydi va
       `required_confirmation` bilan odam ko'rigiga yuboriladi."""
    if not text.strip():
        return None
    ball, mos = lexical_score(text, concept)
    if ball <= 0.0:
        return None
    return _Factor(name=name, kind=kind, score=round(weight * ball, 3),
                   why=f"mos ishoralar {list(mos)} — leksik ball {ball:.3f}")


def _misleading_factors(concept: str, text: str, *, name: str) -> list[_Factor]:
    """Chalg'ituvchi shakllar — QARSHI DALIL (ball pasayadi, sabab yoziladi).

    ⚠️ KONSEPT BERILISHI SHART. Har sabab konseptga XOS: «tur/sinf — sotiladigan birlik emas»
       degan qarshi dalil `product` uchun to'g'ri, `product_variant` uchun esa TO'G'RI SO'ZNI
       jarimaga aylantirardi (u konseptning O'ZI turlar ro'yxati), `price` uchun esa haqiqiy
       nishonni — narx TURLARI katalogini — ro'yxatdan chiqarardi. Filtrlash `lexicon`
       jadvalida turadi, bu yerda esa faqat vazn qo'llanadi."""
    natija: list[_Factor] = []
    for clue, sabab in misleading_hits(text, concept)[:C_MISLEADING_MAX_HITS]:
        natija.append(_Factor(name=name, kind="name_match", score=-C_MISLEADING,
                              why=f"chalg'ituvchi shakl {clue!r} — {sabab}"))
    return natija


# ── Obyekt darajasidagi omillar ────────────────────────────────────────────────────────────
def _object_factors(concept: str, obj: dict, index: _Index) -> tuple[list[_Factor], list[_Factor]]:
    """Obyektning shu konseptga nomzodligi uchun musbat va qarshi omillar."""
    musbat: list[_Factor] = []
    qarshi: list[_Factor] = []
    to_liq = _text(obj.get("full_name"))
    tur = _text(obj.get("kind"))

    for matn, nom, dalil, vazn in (
        (_text(obj.get("name")), "obyekt nomi", "name_match", W_NAME),
        (_text(obj.get("synonym")), "obyekt sinonimi", "synonym_match", W_SYNONYM),
        (_text(obj.get("comment")), "obyekt izohi", "synonym_match", W_COMMENT),
    ):
        omil = _lexical_factor(concept, matn, name=nom, kind=dalil, weight=vazn)
        if omil is not None:
            musbat.append(omil)

    kutilgan = CONCEPT_OBJECT_KINDS[concept]
    if tur in kutilgan:
        musbat.append(_Factor("obyekt turi", "type_shape", W_OBJECT_KIND,
                              f"turi {tur!r} — konsept uchun kutilgan turlardan biri"))
    else:
        qarshi.append(_Factor("obyekt turi", "type_shape", -C_WRONG_KIND,
                              f"turi {tur!r} kutilgan turlardan emas ({list(kutilgan)})"))

    kutilgan_registr = CONCEPT_REGISTER_KIND.get(concept)
    registr_turi = obj.get("register_kind")
    if kutilgan_registr is not None and isinstance(registr_turi, str):
        if registr_turi == kutilgan_registr:
            musbat.append(_Factor("registr shakli", "type_shape", W_REGISTER_KIND,
                                  f"registr turi {registr_turi!r} — kutilganiga mos"))
        elif registr_turi != "unknown":
            qarshi.append(_Factor("registr shakli", "type_shape", -C_WRONG_REGISTER_KIND,
                                  f"registr turi {registr_turi!r}, kutilgani "
                                  f"{kutilgan_registr!r}"))

    kutilgan_kasr = CONCEPT_RESOURCE_SCALE.get(concept)
    if kutilgan_kasr is not None:
        resurslar = [f for f in obj.get("fields", []) if _text(f.get("kind")) == "resource"]
        mos_resurs = [f for f in resurslar if _text(f.get("numeric_scale")) in kutilgan_kasr]
        if mos_resurs:
            musbat.append(_Factor(
                "resurs shakli", "type_shape", W_RESOURCE_SHAPE,
                f"resurs {_text(mos_resurs[0].get('path'))!r} kasr xonasi "
                f"{list(kutilgan_kasr)} kutilmasiga mos"))
        elif resurslar:
            qarshi.append(_Factor(
                "resurs shakli", "type_shape", -C_MISSING_RESOURCE,
                f"birorta resursning kasr xonasi {list(kutilgan_kasr)} kutilmasiga mos emas"))

    registr_havolalari = index.reg_ref_in.get(to_liq, ())
    hamma_havola = index.ref_in.get(to_liq, ())
    if concept == "product":
        if registr_havolalari:
            ulush = min(len(registr_havolalari), 3) / 3.0
            musbat.append(_Factor(
                "munosabat (kim havola qiladi)", "structural_link",
                round(W_REL_PRODUCT * ulush, 3),
                f"{len(registr_havolalari)} registr shu obyektga havola qiladi — "
                f"markaziy katalog belgisi"))
        if not hamma_havola:
            qarshi.append(_Factor("munosabat (kim havola qiladi)", "structural_link",
                                  -C_NO_REFERENCE,
                                  "birorta obyekt bu obyektga havola qilmaydi"))

    if concept in REFERENCES_PRODUCT:
        mahsulotga = [t for t in index.ref_out.get(to_liq, ()) if t in index.product_like]
        if mahsulotga:
            musbat.append(_Factor(
                "munosabat (kimga havola qiladi)", "structural_link", W_REL_TO_PRODUCT,
                f"struktura bo'yicha mahsulot nomzodi {mahsulotga[0]!r} ga havola qiladi"))

    if concept == "warehouse" and registr_havolalari:
        musbat.append(_Factor("munosabat (kim havola qiladi)", "structural_link",
                              W_REL_WAREHOUSE,
                              f"{len(registr_havolalari)} registr o'lchovi shu katalogga "
                              f"havola qiladi"))

    if concept in HIERARCHY_SUSPECT and obj.get("hierarchical") == "true":
        qarshi.append(_Factor("ierarxiya", "type_shape", -C_HIERARCHICAL,
                              "obyekt ierarxik — papka yoki sinf ro'yxati bo'lishi mumkin"))

    soni = _int_or_none(obj.get("row_count"))
    if soni is not None:
        if concept in ROW_COUNT_LARGE:
            if soni >= ROW_COUNT_LARGE_MIN:
                musbat.append(_Factor("sanoq mantiqiyligi", "cardinality", W_CARDINALITY,
                                      f"{soni} qator — katta ro'yxat kutilmasiga mos"))
            else:
                qarshi.append(_Factor("sanoq mantiqiyligi", "cardinality", -C_WRONG_CARDINALITY,
                                      f"{soni} qator — kutilgan katta ro'yxat uchun juda kam"))
        elif concept in ROW_COUNT_SMALL:
            if soni <= ROW_COUNT_SMALL_MAX:
                musbat.append(_Factor("sanoq mantiqiyligi", "cardinality", W_CARDINALITY,
                                      f"{soni} qator — kichik ro'yxat kutilmasiga mos"))
            else:
                qarshi.append(_Factor("sanoq mantiqiyligi", "cardinality", -C_WRONG_CARDINALITY,
                                      f"{soni} qator — kutilgan kichik ro'yxat uchun juda ko'p"))

    qarshi.extend(_misleading_factors(concept, _text(obj.get("name")), name="obyekt nomi"))
    qarshi.extend(_misleading_factors(concept, _text(obj.get("synonym")),
                                      name="obyekt sinonimi"))
    return (musbat, qarshi)


# ── Maydon darajasidagi omillar ────────────────────────────────────────────────────────────
def _field_factors(concept: str, obj: dict, fld: dict,
                   index: _Index) -> tuple[list[_Factor], list[_Factor]]:
    """Maydonning (yoki jadval bo'limining) shu konseptga nomzodligi uchun omillar."""
    musbat: list[_Factor] = []
    qarshi: list[_Factor] = []

    for matn, nom, dalil, vazn in (
        (_text(fld.get("name")), "maydon nomi", "name_match", W_FIELD_NAME),
        (_text(fld.get("synonym")), "maydon sinonimi", "synonym_match", W_FIELD_SYNONYM),
    ):
        omil = _lexical_factor(concept, matn, name=nom, kind=dalil, weight=vazn)
        if omil is not None:
            musbat.append(omil)

    egasi = _text(obj.get("full_name"))
    if concept in PRODUCT_FIELD_CONCEPTS and egasi in index.product_like:
        musbat.append(_Factor(
            "munosabat (egasi obyekt)", "structural_link", W_IN_PRODUCT_OBJECT,
            "maydon struktura bo'yicha mahsulot nomzodi bo'lgan obyektda turadi"))
    elif concept in REFERENCES_PRODUCT:
        # ⚠️ Maydonning O'ZI havola qilmasa ham, EGASI obyekt mahsulot nomzodiga havola qilishi
        #    dalil: bunday registr mahsulot bo'yicha kalitlangan, ya'ni uning maydonlari
        #    mahsulotga tegishli qiymat saqlaydi.
        egasining_havolasi = [t for t in index.ref_out.get(egasi, ())
                              if t in index.product_like]
        if egasining_havolasi:
            musbat.append(_Factor(
                "munosabat (egasi obyekt)", "structural_link", W_IN_PRODUCT_OBJECT,
                f"maydonning egasi obyekt mahsulot nomzodi "
                f"{egasining_havolasi[0]!r} ga havola qiladi"))

    # ⚠️ SKALYAR KUTILADIGAN KONSEPT UCHUN HAVOLA MAYDONI — QARSHI DALIL. Mahsulot katalogiga
    #    havola qiladigan o'lchov MAHSULOTNI ko'rsatadi, barkodni yoki narxni EMAS: u havola
    #    saqlaydi, satr yoki son saqlamaydi. Bu farqni yo'qotsa, har registrning mahsulot
    #    o'lchovi barkod nomzodi bo'lib ketardi — aynan shu xato juda ishonchli ko'rinadi.
    nishonlar = fld.get("reference_targets") or []
    skalyar_kutiladi = concept in CONCEPT_TYPE_KIND
    if nishonlar and skalyar_kutiladi:
        qarshi.append(_Factor(
            "maydon tipi", "type_shape", -C_REFERENCE_FIELD,
            "maydon havola tipida — kutilgan skalyar qiymatni o'zida saqlay olmaydi"))

    # ⚠️ Maydonning O'ZI mahsulot nomzodiga havola qilishi — struktura dalili: partiya yoki
    #    o'lchov birligi aynan shunday bog'lanadi, va bu bog'lanish NOMDAN mustaqil.
    mahsulotga = [t for t in nishonlar if t in index.product_like]
    if mahsulotga and concept in REFERENCES_PRODUCT and not skalyar_kutiladi:
        musbat.append(_Factor(
            "munosabat (maydon havolasi)", "structural_link", W_REL_TO_PRODUCT,
            f"maydon struktura bo'yicha mahsulot nomzodi {mahsulotga[0]!r} ga havola qiladi"))

    tip_matni = _text(fld.get("type"))
    kutilgan_turkum = CONCEPT_TYPE_KIND.get(concept)
    if kutilgan_turkum is not None and tip_matni:
        if type_matches(tip_matni, kutilgan_turkum):
            musbat.append(_Factor("tip mosligi", "type_shape", W_TYPE_SHAPE,
                                  f"tip tavsifi {kutilgan_turkum!r} turkumiga mos"))
        else:
            boshqa = sorted(t for t in ("boolean", "date", "number", "string")
                            if t != kutilgan_turkum and type_matches(tip_matni, t))
            # ⚠️ Ishora TOPILMAGANI qarshi dalil EMAS: platforma tipni kutilmagan so'z bilan
            #    yozgan bo'lishi mumkin. Qarshi dalil faqat BOSHQA turkum aniq tanilganda.
            if boshqa:
                qarshi.append(_Factor("tip mosligi", "type_shape", -C_WRONG_TYPE,
                                      f"tip {boshqa[0]!r} turkumiga o'xshaydi, kutilgani "
                                      f"{kutilgan_turkum!r}"))

    oraliq = CONCEPT_STRING_LEN.get(concept)
    uzunlik = _int_or_none(fld.get("string_length"))
    if oraliq is not None and uzunlik is not None:
        past, yuqori = oraliq
        if past <= uzunlik <= yuqori:
            musbat.append(_Factor("qiymat shakli", "value_domain", W_VALUE_DOMAIN,
                                  f"satr uzunligi {uzunlik} — kutilgan {past}..{yuqori} "
                                  f"oralig'ida"))
        else:
            qarshi.append(_Factor("qiymat shakli", "value_domain", -C_OUT_OF_DOMAIN,
                                  f"satr uzunligi {uzunlik} kutilgan {past}..{yuqori} "
                                  f"oralig'idan tashqarida"))

    kutilgan_kasr = CONCEPT_NUMERIC_SCALE.get(concept)
    kasr = _text(fld.get("numeric_scale"))
    if kutilgan_kasr is not None and kasr:
        if kasr in kutilgan_kasr:
            musbat.append(_Factor("tip mosligi", "type_shape", W_TYPE_SHAPE,
                                  f"kasr xonasi {kasr!r} — kutilganiga mos"))
        else:
            qarshi.append(_Factor("tip mosligi", "type_shape", -C_WRONG_TYPE,
                                  f"kasr xonasi {kasr!r}, kutilgani {list(kutilgan_kasr)}"))

    qarshi.extend(_misleading_factors(concept, _text(fld.get("name")), name="maydon nomi"))
    qarshi.extend(_misleading_factors(concept, _text(fld.get("synonym")),
                                      name="maydon sinonimi"))
    return (musbat, qarshi)


def _pseudo_fields(obj: dict) -> list[dict]:
    """Maydonlar + JADVAL BO'LIMLARI + SANAB O'TILGAN QIYMATLAR (hammasi qonuniy manzil).

    ⚠️ Jadval bo'limi ataylab qo'shiladi: qator darajasidagi konsept (masalan barkod ro'yxati)
       ko'pincha aynan bo'limda yashaydi, va uni maydon darajasiga majburlash nomzodni
       KO'RINMAY qoldirardi.
    ⚠️ SANAB O'TILGAN QIYMAT ham manzil: `ai._field_addresses` uni QONUNIY deb e'lon qiladi,
       `_probes` esa `enum_values` zondini tavsiya qiladi va `CONCEPT_OBJECT_KINDS` da
       `tax_vat` hamda `unit_of_measure` uchun `enum` turadi. Ya'ni shartnoma sanoq
       qiymatida gipoteza kutadi; ularsiz analitik `Перечисление` ichidagi konseptni HECH
       QACHON ko'rsata olmasdi — sanoq qiymatida yashagan soliq stavkasi yoki o'lchov
       birligi jimgina yo'qolardi.
    ⚠️ Sanoq qiymatining TIPI ham, uzunligi ham YO'Q (`""`/`None`): u qiymatning NOMI. Bo'sh
       tip `_field_factors` da dalil YO'QLIGI deb o'qiladi, qarshi dalil deb emas."""
    natija = [f for f in obj.get("fields", []) if isinstance(f, dict)]
    for nom, turkum in (("tabular_sections", "tabular_section"),
                        ("enum_values", "enum_value")):
        for qiymat in obj.get(nom, []):
            if isinstance(qiymat, str) and qiymat:
                natija.append({"name": qiymat, "path": qiymat, "synonym": None,
                               "kind": turkum, "type": "", "reference_targets": [],
                               "numeric_digits": None, "numeric_scale": None,
                               "string_length": None})
    return natija


# ── Zondlar ────────────────────────────────────────────────────────────────────────────────
def _probes(concept: str, obj: dict, field_path: str | None, *,
            status: str, index: _Index) -> list[dict]:
    """Tavsiya etiladigan keyingi zondlar — `probe.PROBE_CATALOG` dan, ustuvorlik tartibida.

    ⚠️ Zond MAJBURIY emas, lekin u gipotezani TEKSHIRILADIGAN qiladi: nima so'rash kerakligi
       aytilmagan gipoteza faqat taxmin bo'lib qolardi.
    ⚠️ Har zond FAQAT O'QIYDI — buni katalogning o'zi kafolatlaydi (`read_only` import paytida
       tekshiriladi), shu bois bu yerda «xavfsizmi» degan qaror qayta qabul qilinmaydi.
    ⚠️ NISHON SHAKLI ZOND TURIDAN kelib chiqadi (`probe.FIELD_TARGET_PROBE_TYPES`):
       `field_type_details` MAYDON manzilini oladi, qolganlari OBYEKTNI. Shartnoma
       `probe` da yozilgan va u shu yerda TAXMIN QILINMAYDI."""
    to_liq = _text(obj.get("full_name"))
    tur = _text(obj.get("kind"))
    maydonsiz = field_path is None and concept in FIELD_LEVEL_CONCEPTS
    #: ⚠️ HAQIQIY maydon yo'llari. Jadval bo'limi nomi va sanab o'tilgan qiymat ham nomzod
    #: MANZILI bo'la oladi (`_pseudo_fields`), lekin ular MAYDON emas — ya'ni maydon tipini
    #: so'raydigan zondni ular ustida bajarib bo'lmaydi va u umuman taklif qilinmaydi.
    haqiqiy_maydonlar = {_text(f.get("path")) for f in obj.get("fields", [])
                         if isinstance(f, dict)}
    reja: list[dict] = []

    def qo_sh(probe_type: str, sabab: str, kutilgan: tuple[str, ...], *,
              nishon: str | None = None) -> None:
        if probe_type not in PROBE_CATALOG:
            raise AnalystError(f"zond turi katalogda yo'q: {probe_type!r}")
        reja.append({"probe_type": probe_type, "target_object": nishon or to_liq,
                     "reason": sabab, "expected_evidence": sorted(kutilgan)})

    if maydonsiz:
        # ⚠️ Maydon aniqlanmagan holat: obyektning maydon tarkibi va qator darajasidagi
        #    tuzilmasi bilinmasa gipotezani tekshirib bo'lmaydi, kim havola qilishi esa
        #    obyektning haqiqiy rolini nomdan ko'ra aniq ko'rsatadi.
        qo_sh("object_attributes",
              f"{concept} uchun aniq maydon topilmadi — maydon tarkibi kerak",
              ("name_match", "type_shape"))
        qo_sh("tabular_sections",
              f"{concept} qator darajasidagi bo'limda yashashi mumkin",
              ("name_match", "structural_link"))
        qo_sh("referencing_objects",
              "kim shu obyektga havola qilishi uning haqiqiy rolini ochadi",
              ("structural_link",))
    if status == STATUS_AMBIGUOUS and not maydonsiz:
        qo_sh("referencing_objects",
              "nomzodlar bali yaqin — havola qiluvchilar tanlovni hal qilishi mumkin",
              ("structural_link",))
    if tur in REGISTER_KINDS_SET:
        qo_sh("register_shape",
              "registrning o'lchov va resurs taqsimoti gipotezani tasdiqlaydi yoki rad etadi",
              ("cardinality", "type_shape"))
    if tur == "enum":
        qo_sh("enum_values",
              "konsept sanab o'tilgan qiymatlar ichida yashiringan bo'lishi mumkin",
              ("value_domain",))
    if field_path is not None and field_path in haqiqiy_maydonlar:
        # ⚠️ Nishon MAYDON MANZILI (`<obyekt>.<maydon>`): zond BITTA maydonning tip
        #    tafsilotini o'qiydi, ya'ni obyekt nomini berish «bajarilmaydigan zond» bo'lardi.
        qo_sh("field_type_details",
              "maydon tipining aniqligi va uzunligi nomdan mustaqil dalil beradi",
              ("type_shape",), nishon=f"{to_liq}{PROBE_TARGET_SEP}{field_path}")
    if _int_or_none(obj.get("row_count")) is None:
        qo_sh("row_count",
              "qatorlar soni bilinmasa gipotezaning kattaligi mantiqiyligi tekshirilmaydi",
              ("cardinality",))
    if not index.ref_in.get(to_liq) and not maydonsiz:
        qo_sh("referencing_objects",
              "obyektga havola ko'rinmadi — havola qiluvchilar ro'yxati kerak",
              ("structural_link",))
    # ⚠️ ZAXIRA ZOND: birorta qoida ishlamasa ham gipoteza TEKSHIRILADIGAN bo'lib qolishi kerak.
    #    Zondsiz gipoteza operatorga «ishonaver» deyishdan boshqa yo'l qoldirmaydi, va aynan
    #    shunday gipotezalar hujjatda abadiy CANDIDATE bo'lib yotib qoladi.
    qo_sh("object_attributes",
          "gipotezani tekshirish uchun obyektning maydon tarkibi kerak",
          ("name_match", "type_shape"))

    # ⚠️ Takror zond tashlanadi (bir obyektga bir turdagi zond BIR MARTA), chegara esa
    #    `ai.MAX_PROBES_PER_HYPOTHESIS`: kichik chegara eng ko'p ma'lumot beradigan zondni
    #    tanlashga majburlaydi.
    ko_rilgan: set[str] = set()
    yakun: list[dict] = []
    for z in reja:
        if z["probe_type"] in ko_rilgan:
            continue
        ko_rilgan.add(z["probe_type"])
        yakun.append(z)
        if len(yakun) >= MAX_PROBES_PER_HYPOTHESIS:
            break
    return yakun


# ── Nomzod ─────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Candidate:
    """Ichki nomzod: gipoteza lug'atiga aylanishdan OLDINGI holat."""

    concept: str
    object_name: str
    field_path: str | None
    positive: tuple[_Factor, ...]
    negative: tuple[_Factor, ...]

    @property
    def address(self) -> str:
        if self.field_path is None:
            return self.object_name
        return f"{self.object_name}.{self.field_path}"

    @property
    def has_lexical(self) -> bool:
        """Nomzodda LEKSIK dalil bormi (nom, sinonim yoki izoh mosligi).

        ⚠️ Bu savol kerak, chunki leksik dalilsiz nomzoddan ko'proq struktura vazni talab
           qilinadi (`MIN_POSITIVE_STRUCTURAL`)."""
        return any(f.name in LEXICAL_FACTOR_NAMES for f in self.positive)

    @property
    def positive_sum(self) -> float:
        return round(sum(f.score for f in self.positive), 3)

    @property
    def negative_sum(self) -> float:
        return round(-sum(f.score for f in self.negative), 3)

    @property
    def raw_score(self) -> float:
        """QISILMAGAN yig'indi: musbat omillar - qarshi omillar.

        ⚠️ Kerak, chunki chegaraga urilgan nomzodning oshiqchasi QISILGAN balldan emas, XOM
           yig'indidan hisoblanadi: 1.012 ni 1.0 deb olib chegara ayirilsa natija chegaraga
           TUSHMAY qolardi (0.612 ≠ 0.600) va chegara jimgina noaniq ishlardi."""
        return round(self.positive_sum - self.negative_sum, 3)

    @property
    def score(self) -> float:
        """0..1 ga qisilgan ball. Qisish OCHIQ: omillar yig'indisi 1 dan oshsa ham ball 1.0."""
        return round(max(0.0, min(1.0, self.positive_sum - self.negative_sum)), 3)

    @property
    def has_structure(self) -> bool:
        """Nomzodda STRUKTURA dalili bormi (`structural_link` turidagi musbat omil).

        ⚠️ Struktura dalili obyektning konfiguratsiyadagi ROLINI ko'rsatadi va nomdan
           MUSTAQIL — shu bois «nom o'zi bilan yetarli emas» qoidasining o'lchovi aynan shu."""
        return any(f.kind == "structural_link" for f in self.positive)

    @property
    def sort_key(self) -> tuple[float, str]:
        """Tartib: ball kamayishi, keyin manzil — teng ballda ham AYNAN bir xil tartib."""
        return (-self.score, self.address)


def _cap_lexical(cand: _Candidate) -> _Candidate:
    """Struktura dalili BO'LMAGAN nomzodni `NO_STRUCTURE_CEILING` dan yuqoriga chiqarmaydi.

    ⚠️ NEGA KERAK: vaznlar jadvalining leksik qismi (`W_NAME + W_SYNONYM`) obyekt turi va
       sanoq bonuslari bilan birga 1.000 ga yetadi, ya'ni nomi mukammal mos katalog HAVOLASIZ
       va REGISTRSIZ konfiguratsiyada ham eng yuqori ishonchni olardi. «Leksik moslik KUCHSIZ
       dalil» degan qoida shunda faqat izohda qolardi, ballda esa buzilardi.
    ⚠️ QIRQIM YASHIRIN EMAS: oshiqcha qism qarshi OMIL bo'lib yoziladi, ya'ni
       `confidence_score` baribir omillar yig'indisi bo'lib qoladi va sabab hujjatda turadi.
    ⚠️ RAD ETMAYDI: nomzod ro'yxatda qoladi, faqat navbatning boshiga chiqmaydi."""
    if cand.has_structure:
        return cand
    xom = cand.raw_score
    if xom <= NO_STRUCTURE_CEILING:
        return cand
    ortiqcha = round(xom - NO_STRUCTURE_CEILING, 3)
    omil = _Factor(
        "leksik to'yinish", "name_match", -ortiqcha,
        f"struktura dalili yo'q — leksik moslik o'zi bilan {NO_STRUCTURE_CEILING:.3f} dan "
        f"yuqoriga chiqmaydi (xom yig'indi {xom:.3f})")
    return _Candidate(cand.concept, cand.object_name, cand.field_path, cand.positive,
                      cand.negative + (omil,))


def _confirmations(cand: _Candidate) -> list[str]:
    """Odam AYNAN nimani ko'rishi kerak.

    ⚠️ Bo'sh bo'lmasligi SHART (`ai._validate_hypothesis`): tekshirish yo'li aytilmagan gipoteza
       hech qachon tasdiqdan o'tmaydi, ya'ni u abadiy `CANDIDATE` bo'lib qolardi."""
    satrlar = [
        f"operator 1C ekranida `{cand.address}` ni ochib, mazmuni `{cand.concept}` konseptiga "
        f"mos ekanini ko'rsin",
        f"nomzod BinOS tomonidagi qaysi nishonga tushishi yozib berilsin, "
        f"chunki leksik moslik o'zi bilan xarita bermaydi",
    ]
    if cand.field_path is not None:
        satrlar.append(
            "maydonning bir nechta qatoridagi qiymat shakli kutilganiga mos ekani ko'rsatilsin")
    if cand.negative:
        satrlar.append("qarshi dalillar ro'yxati alohida ko'rib chiqilsin, "
                       "ular ballni pasaytirgan")
    return satrlar


def _hypothesis_json(cand: _Candidate, *, status: str, ambiguity: list[str],
                     index: _Index, obj: dict) -> dict:
    """Nomzodni gipoteza lug'atiga aylantiradi (`ai.HYPOTHESIS_KEYS` shaklida).

    ⚠️ `status` bu yerda TEKSHIRILADI: taqiqlangan daraja chiqib ketmasligi kodda ushlanadi,
       validatorning mehribonligiga tashlab qo'yilmaydi."""
    _assert_allowed_status(status)
    return {
        "target_concept": cand.concept,
        "candidate_object": cand.object_name,
        "candidate_field": cand.field_path,
        "confidence_score": cand.score,
        "evidence": _evidence_json(cand.positive),
        "counter_evidence": _evidence_json(cand.negative),
        "ambiguity": list(ambiguity),
        "required_confirmation": _confirmations(cand),
        "recommended_next_probe": _probes(cand.concept, obj, cand.field_path,
                                          status=status, index=index),
        "status": status,
    }


def _assert_allowed_status(status: str) -> None:
    """Chiqishda FAQAT `CANDIDATE`, `AMBIGUOUS`, `REJECTED` bo'lishi mumkin.

    ⚠️ `VERIFIED` ham, `HUMAN_CONFIRMED` ham bu kanaldan CHIQMAYDI. `ai.validate_analysis` ham
       ularni rad etadi, lekin tekshiruv IKKI joyda ataylab: bu qatlam noto'g'ri daraja
       yozishga umuman urinmasligi kerak, va urinish darhol ko'rinishi kerak."""
    if status in (FORBIDDEN_STATUS, STATUS_HUMAN_CONFIRMED):
        raise AnalystError(
            f"analitik {status!r} darajasini CHIQARA OLMAYDI — u faqat kuchli dalil yoki "
            f"operatorning alohida tasdiq hujjatidan keladi")
    if status not in (STATUS_AMBIGUOUS, STATUS_CANDIDATE, STATUS_REJECTED):
        raise AnalystError(f"noma'lum daraja {status!r}")


# ── Analitiklar ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class HeuristicAnalyzer:
    """`ai.DiscoveryAIAnalyzer` ni DETERMINISTIK bajaradigan analitik (model YO'Q).

    Ishlatilishi yadro shartnomasi bilan bir xil:

        payload = ai.analyst_payload(graph)
        raw = HeuristicAnalyzer().analyze(payload)
        hyps = ai.validate_analysis(raw, graph=graph)

    ⚠️ U «fake» ham, ASOSIY CHIZIQ ham: testlar uni mock o'rnida ishlatadi, kelajakdagi model
       esa shu chiziqdan yaxshi ishlashini ISBOTLASHI kerak. Shu bois uning natijasi ham
       validatordan o'tadi — imtiyozi yo'q.
    ⚠️ `min_positive` va `ambiguity_delta` — sozlanadigan chegaralar, lekin ULAR BALLNI
       TALQIN QILMAYDI: birinchisi juda kuchsiz nomzodni chiqarmaydi, ikkinchisi yaqin ballni
       `AMBIGUOUS` deb ataydi. Ikkalasi ham gipotezaning MAZMUNIGA tegmaydi."""

    min_positive: float = MIN_POSITIVE
    min_positive_structural: float = MIN_POSITIVE_STRUCTURAL
    ambiguity_delta: float = AMBIGUITY_DELTA
    keep_window: float = KEEP_WINDOW
    max_per_concept: int = MAX_HYPOTHESES_PER_CONCEPT

    def analyze(self, payload: dict) -> dict:
        """Yukdan gipotezalar quradi. Chiqish `ai.validate_analysis` dan O'TADI."""
        index = _build_index(payload)
        so_ralgan = tuple(payload["contract"]["concepts"])
        notanish = sorted(c for c in so_ralgan if c not in CONCEPTS or c not in CONCEPT_CLUES)
        _need(not notanish,
              f"noma'lum yoki lug'atsiz konsept(lar) {notanish} — ishoralar lug'ati "
              f"`ai.CONCEPTS` bilan bir xil bo'lishi kerak")

        by_name = {_text(o.get("full_name")): o for o in index.objects}
        gipotezalar: list[dict] = []
        qisilgan: list[str] = []

        for concept in sorted(set(so_ralgan)):
            nomzodlar = self._candidates(concept, index)
            if not nomzodlar:
                continue
            tartib = sorted(nomzodlar, key=lambda c: c.sort_key)
            # ⚠️ Darcha: kuchli nomzod bor joyda undan ancha orqada qolganlar ro'yxatdan
            #    chiqadi. Kuchli nomzod yo'q bo'lsa darcha hech narsani kesmaydi.
            eng_yuqori = tartib[0].score
            tanlangan = [c for c in tartib if eng_yuqori - c.score <= self.keep_window]
            if len(tanlangan) < len(tartib) or len(tanlangan) > self.max_per_concept:
                qisilgan.append(concept)
            tanlangan = tanlangan[:self.max_per_concept]

            # ⚠️ RAD ETILADIGAN NOMZODLAR AVVAL AJRATILADI. Noaniqlik FAQAT TIRIK nomzodlar
            #    orasida hisoblanadi, chunki rad etilgan nomzod tanlovning tomoni EMAS.
            #    Ikkisi aralashsa ikki zarar chiqardi: (1) artefakt o'z-o'ziga qarama-qarshi
            #    bo'lardi — «A va B orasida tanlay olmadim» deyilardi, B esa shu hujjatda
            #    RAD etilgan bo'lib turardi; (2) YOLG'ON AMBIGUOUS — yakka haqiqiy nomzod
            #    RAD etilgan obyekt tufayli `CANDIDATE` dan `AMBIGUOUS` ga tushirilardi.
            tirik = [c for c in tanlangan if c.score > 0.0]
            yaqinlar = []
            if tirik:
                yetakchi = tirik[0].score
                yaqinlar = [c for c in tirik if yetakchi - c.score <= self.ambiguity_delta]
            yaqin_manzillar = {c.address for c in yaqinlar}
            ikkilanish_bor = len(yaqinlar) >= 2

            for cand in tanlangan:
                if cand.score <= 0.0:
                    status = STATUS_REJECTED
                elif ikkilanish_bor and cand.address in yaqin_manzillar:
                    status = STATUS_AMBIGUOUS
                else:
                    status = STATUS_CANDIDATE

                ambiguity: list[str] = []
                if status == STATUS_AMBIGUOUS:
                    boshqalar = [c for c in yaqinlar if c.address != cand.address]
                    ambiguity.append(
                        f"`{cand.address}` (ball {cand.score:.3f}) va "
                        + " va ".join(f"`{c.address}` (ball {c.score:.3f})" for c in boshqalar)
                        + " ballari yaqin — avtomat tanlov QILINMADI")
                    ambiguity.append(
                        "tanlovni operator hal qilsin yoki havola qiluvchilar zondining "
                        "natijasi kutilsin")
                if status == STATUS_REJECTED and not cand.negative:
                    # ⚠️ Sababsiz rad etish TAQIQLANGAN (`ai._validate_hypothesis`), shu bois
                    #    qarshi dalili yo'q nomzod RAD deb yozilmaydi — u umuman chiqmaydi.
                    continue

                gipotezalar.append(_hypothesis_json(
                    cand, status=status, ambiguity=ambiguity, index=index,
                    obj=by_name[cand.object_name]))

        izohlar = [
            "HeuristicAnalyzer DETERMINISTIK: model ham, tarmoq chaqiruvi ham ishlatilmaydi — "
            "bir xil graf AYNAN bir xil gipotezalarni beradi.",
            "confidence_score = musbat omillar yig'indisidan qarshi omillar ayirilib, 0..1 ga "
            "qisilgan o'lchov. Har omilning nomi va hissasi dalil tafsilotida yozilgan, ya'ni "
            "ball TALQIN emas, hisob.",
            "Eng yuqori holat CANDIDATE. VERIFIED bu kanalda umuman yo'q, HUMAN_CONFIRMED esa "
            "faqat operatorning alohida tasdiq hujjatidan keladi.",
            "Leksik moslik KUCHSIZ dalil: nom to'g'ri ko'ringani xaritani tasdiqlamaydi.",
        ]
        if qisilgan:
            izohlar.append(
                "Nomzodlar soni chegaraga qisilgan konseptlar: " + ", ".join(sorted(qisilgan))
                + ". Qisilgani «yo'q» degani emas.")

        return {"analysis_version": ANALYSIS_VERSION, "hypotheses": gipotezalar,
                "notes": izohlar}

    def _yetarli(self, cand: _Candidate) -> bool:
        """Nomzod ro'yxatga tushishga yetarli dalilga egami.

        ⚠️ MUSBAT OMILSIZ nomzod HECH QACHON tushmaydi: dalilsiz gipoteza shunchaki taxmin va
           taxmin hujjatga yozilmaydi.
        ⚠️ LEKSIK dalilsiz nomzoddan IKKI narsa talab qilinadi: yuqoriroq chegara
           (`min_positive_structural`) VA kamida bitta MUNOSABAT dalili. Sabab: tip shakli
           o'zi bilan nom qo'ya olmaydi — 8..14 uzunlikdagi har satr maydoni barkod nomzodi
           bo'lib ketardi, obyekt turining mosligi esa har katalogni har «katalogda
           yashaydigan» konseptga nomzod qilardi. Munosabat esa AYNAN shu obyektning
           konfiguratsiyadagi ROLINI ko'rsatadi."""
        if not cand.positive:
            return False
        if cand.has_lexical:
            return cand.positive_sum >= self.min_positive
        if not cand.has_structure:
            return False
        return cand.positive_sum >= self.min_positive_structural

    def _candidates(self, concept: str, index: _Index) -> list[_Candidate]:
        """Konsept uchun hamma nomzod — obyekt va (kerak bo'lsa) maydon darajasida.

        ⚠️ Musbat omili YO'Q nomzod ro'yxatga TUSHMAYDI: dalilsiz gipoteza shunchaki taxmin.
        ⚠️ Chegaradan o'tmagan nomzod ham tushmaydi, lekin bu «RAD» degani emas — konsept
           nomzodsiz qolsa `coverage()` uni `UNKNOWN` deb ataydi."""
        natija: list[_Candidate] = []
        for obj in index.objects:
            to_liq = _text(obj.get("full_name"))
            if not to_liq:
                continue

            musbat, qarshi = _object_factors(concept, obj, index)
            nomzod = _Candidate(concept, to_liq, None, tuple(musbat), tuple(qarshi))
            if self._yetarli(nomzod):
                # ⚠️ Chegara RO'YXATGA TUSHISHDAN KEYIN qo'llanadi: u nomzodni chiqarib
                #    tashlamaydi, faqat strukturaga tayanmagan ballni pasaytiradi.
                natija.append(_cap_lexical(nomzod))

            if concept not in FIELD_LEVEL_CONCEPTS:
                continue
            for fld in _pseudo_fields(obj):
                f_musbat, f_qarshi = _field_factors(concept, obj, fld, index)
                maydon = _Candidate(concept, to_liq, _text(fld.get("path")),
                                    tuple(f_musbat), tuple(f_qarshi))
                if self._yetarli(maydon):
                    natija.append(_cap_lexical(maydon))

        # Bir manzil uchun bitta nomzod (`ai.validate_analysis` takrorni RAD etadi).
        # ⚠️ Teng ballda MANZIL bo'yicha tanlanadi, «birinchi kelgani» bo'yicha EMAS: obyektlar
        #    tartibiga bog'liq tanlov kirishning tartibi o'zgarganda javobni ham o'zgartirardi.
        ko_rilgan: dict[str, _Candidate] = {}
        for cand in natija:
            avvalgi = ko_rilgan.get(cand.address)
            if avvalgi is None or cand.score > avvalgi.score:
                ko_rilgan[cand.address] = cand
        return [ko_rilgan[k] for k in sorted(ko_rilgan)]


@dataclass(frozen=True)
class NullAnalyzer:
    """HECH NARSA qaytarmaydigan analitik — testlar uchun.

    ⚠️ Bu «buzuq» analitik EMAS: u shartnomaga to'liq mos, bo'sh javob beradi. Uning vazifasi —
       «tahlil yo'q» holatining ham to'g'ri o'tishini isbotlash. Bo'sh tahlil «hech narsa yo'q»
       degani emas: hamma konsept `UNKNOWN` bo'lib qoladi va `coverage()` shuni ochiq aytadi."""

    def analyze(self, payload: dict) -> dict:
        _build_index(payload)   # yuk baribir TEKSHIRILADI — buzuq yuk jimgina o'tmaydi
        return {
            "analysis_version": ANALYSIS_VERSION,
            "hypotheses": [],
            "notes": ["NullAnalyzer ataylab hech qanday gipoteza chiqarmaydi — hamma konsept "
                      "UNKNOWN bo'lib qoladi, va bu «yo'q» degani emas."],
        }


@dataclass(frozen=True)
class RecordedAnalyzer:
    """OLDINDAN YOZILGAN javobni qaytaradigan analitik — testlar uchun.

    ⚠️ U HECH NARSANI TEKSHIRMAYDI va tekshirmasligi kerak: uning maqsadi — validator haqiqiy
       provayderdan kelishi mumkin bo'lgan har qanday xom javobni to'g'ri rad etishini yoki
       qabul qilishini sinash. Shu bois buzuq fixture ham o'zgarishsiz qaytariladi.
    ⚠️ Javob NUSXASI qaytadi: chaqiruvchi natijani o'zgartirsa, keyingi chaqiruv shu
       o'zgarishni ko'rmasligi kerak, aks holda test tartibiga bog'liq bo'lib qolardi."""

    fixture: object

    def analyze(self, payload: dict) -> dict:
        _need(isinstance(payload, dict),
              f"yuk lug'at bo'lishi kerak, kelgani {type(payload).__name__}")
        return copy.deepcopy(self.fixture)


# ── Qamrov ─────────────────────────────────────────────────────────────────────────────────
#: Konseptning qamrov holatlari.
#: ⚠️ `REJECTED_ONLY` va `UNKNOWN` FARQ QILADI: birinchisi «qaradik va qarshi dalil topdik»,
#:    ikkinchisi «umuman nomzod topilmadi». Ikkisini qo'shib yuborish «qaralmadi» ni «yo'q»
#:    deb o'qish bo'lardi.
STATE_COVERED = "COVERED"
STATE_REJECTED_ONLY = "REJECTED_ONLY"
STATE_UNKNOWN = "UNKNOWN"


def coverage(graph, *, analyzer=None) -> dict:
    """Har konseptning qamrov holati — QARALMAGANINI ham ATAB.

    Oqim yadroning shartnomasi bilan bir xil: yuk quriladi, analitik chaqiriladi, natija
    `ai.validate_analysis` dan O'TADI. Shu bois `coverage()` validator rad etadigan narsani
    hisobga olib qo'ymaydi.

    ⚠️ Sanoqlar MATN (`binos-1c-metadata-v1` 1-invarianti bilan bir xil sabab). `best_score`
       esa SANOQ EMAS, u o'lchov — shu bois son bo'lib qoladi yoki `null` bo'ladi.
    ⚠️ `concepts_unknown` `ai.unknown_concepts` dan keladi, ya'ni bu yerda qaytadan
       hisoblanmaydi: bitta haqiqat bitta joyda turadi."""
    analyzer = HeuristicAnalyzer() if analyzer is None else analyzer
    payload = analyst_payload(graph)
    hyps = validate_analysis(analyzer.analyze(payload), graph=graph)

    bo_yicha: dict[str, list] = {c: [] for c in CONCEPTS}
    for h in hyps:
        bo_yicha.setdefault(h.target_concept, []).append(h)

    noma_lum = unknown_concepts(hyps)
    konseptlar: dict[str, dict] = {}
    for concept in sorted(CONCEPTS):
        rows = bo_yicha.get(concept, [])
        holatlar: dict[str, int] = {}
        for h in rows:
            holatlar[h.status] = holatlar.get(h.status, 0) + 1
        if not rows:
            holat = STATE_UNKNOWN
        elif all(h.status == STATUS_REJECTED for h in rows):
            holat = STATE_REJECTED_ONLY
        else:
            holat = STATE_COVERED
        # ⚠️ Eng yaxshi nomzod: ball KAMAYISHI, keyin manzil O'SISHI bo'yicha — teng ballda ham
        #    AYNAN bir xil javob. «Eng yaxshi» bu yerda «to'g'ri» degani EMAS, faqat navbat.
        eng_yaxshi = min(rows, key=lambda h: (-h.confidence_score, h.address)) if rows else None
        konseptlar[concept] = {
            "state": holat,
            "hypotheses": str(len(rows)),
            "by_status": {k: str(holatlar[k]) for k in sorted(holatlar)},
            "best_score": None if eng_yaxshi is None else eng_yaxshi.confidence_score,
            "best_address": None if eng_yaxshi is None else eng_yaxshi.address,
        }

    qamralgan = sum(1 for c in konseptlar.values() if c["state"] == STATE_COVERED)
    rad = sum(1 for c in konseptlar.values() if c["state"] == STATE_REJECTED_ONLY)
    return {
        "concepts": konseptlar,
        "concepts_unknown": list(noma_lum),
        "counts": {
            "concepts": str(len(CONCEPTS)),
            "covered": str(qamralgan),
            "rejected_only": str(rad),
            "unknown": str(len(noma_lum)),
            "hypotheses": str(len(hyps)),
        },
    }


# ── Lug'at qamrovining invarianti (import paytida) ─────────────────────────────────────────
def _check_concept_tables() -> None:
    """Jadvallar `ai.CONCEPTS` bilan AYNAN bir xil konseptlarni qamrasin.

    ⚠️ `assert` ATAYLAB ISHLATILMAYDI (`probe._check_catalog` bilan bir xil sabab): `assert`
       optimizatsiya rejimida o'chadi, ya'ni lug'atsiz qolgan konsept jimgina hech qachon
       nomzod olmasdi va bu «konfiguratsiyada yo'q» degan xulosaga o'xshab qolardi."""
    tushib = sorted(c for c in CONCEPTS if c not in CONCEPT_CLUES)
    if tushib:
        raise LexiconError(
            f"lug'atsiz konsept(lar) {tushib} — `CONCEPT_CLUES` `ai.CONCEPTS` ni TO'LIQ "
            f"qamrashi kerak, aks holda konsept jimgina nomzodsiz qolardi")
    ortiqcha = sorted(c for c in CONCEPT_CLUES if c not in CONCEPTS)
    if ortiqcha:
        raise LexiconError(
            f"shartnomada yo'q konsept(lar) {ortiqcha} — konsept ID lari `ai.CONCEPTS` da "
            f"yashaydi va o'ylab chiqarilmaydi")

    tushib_tur = sorted(c for c in CONCEPTS if c not in CONCEPT_OBJECT_KINDS)
    if tushib_tur:
        raise AnalystError(
            f"obyekt turi kutilmasi yo'q konsept(lar) {tushib_tur} — struktura dalili "
            f"bo'lmasa nomzod faqat nomga tayanardi")
    for concept, kinds in CONCEPT_OBJECT_KINDS.items():
        if concept not in CONCEPTS:
            raise AnalystError(f"CONCEPT_OBJECT_KINDS da shartnomada yo'q konsept: {concept!r}")
        if list(kinds) != sorted(set(kinds)) or not kinds:
            raise AnalystError(
                f"CONCEPT_OBJECT_KINDS[{concept!r}] bo'sh bo'lmagan, tartiblangan va takrorsiz "
                f"bo'lishi kerak")

    for nom, ro_yxat in (("FIELD_LEVEL_CONCEPTS", FIELD_LEVEL_CONCEPTS),
                         ("PRODUCT_FIELD_CONCEPTS", PRODUCT_FIELD_CONCEPTS),
                         ("REFERENCES_PRODUCT", REFERENCES_PRODUCT),
                         ("HIERARCHY_SUSPECT", HIERARCHY_SUSPECT),
                         ("ROW_COUNT_LARGE", ROW_COUNT_LARGE),
                         ("ROW_COUNT_SMALL", ROW_COUNT_SMALL)):
        if list(ro_yxat) != sorted(set(ro_yxat)):
            raise AnalystError(f"{nom} tartiblangan va takrorsiz bo'lishi kerak")
        yo_q = sorted(c for c in ro_yxat if c not in CONCEPTS)
        if yo_q:
            raise AnalystError(f"{nom} da shartnomada yo'q konsept(lar): {yo_q}")

    # ⚠️ Chalg'ituvchi ishoraning konsept ro'yxati ham SHARTNOMADAN: lug'at o'zi
    #    `CONCEPT_CLUES` ga qarab tekshiradi, bu yerda esa `ai.CONCEPTS` bilan solishtiriladi.
    #    Noto'g'ri yozilgan konsept ID si jarimani jimgina O'CHIRIB qo'yardi.
    for clue, (_sabab, konseptlar) in MISLEADING_CLUES.items():
        yo_q = sorted(c for c in konseptlar if c != ANY_CONCEPT and c not in CONCEPTS)
        if yo_q:
            raise AnalystError(
                f"MISLEADING_CLUES[{clue!r}] da shartnomada yo'q konsept(lar): {yo_q}")

    for zond in ("enum_values", "field_type_details", "object_attributes",
                 "referencing_objects", "register_shape", "row_count", "tabular_sections"):
        if zond not in PROBE_CATALOG:
            raise AnalystError(f"tavsiya etiladigan zond katalogda yo'q: {zond!r} — zond turi "
                               f"KOD o'zgarishi bilan qo'shiladi")

    # ⚠️ Tokenlashtirish jadvali ishlayotganiga ishonch: bo'sh chiqish butun leksik qatlamni
    #    jimgina o'chirib qo'yardi.
    if not tokens("plu_code") == ("plu", "code"):
        raise LexiconError("tokenlashtirish buzilgan: pastki tire so'z ajratuvchisi bo'lishi kerak")


_check_concept_tables()
