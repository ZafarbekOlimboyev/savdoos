# -*- coding: utf-8 -*-
"""`binos-1c-discovery-v1` lug'atlari va ISHONCH QOIDASI.

Bu fayl — sxemaning so'z boyligi. Unda birorta konfiguratsiya nomi YO'Q: nishonlar BinOS
tomonidagi maydonlar (bizning shartnomamiz), manba turlari esa 1C ning UMUMIY metadata
tushunchalari. Qaysi obyekt qaysi nishonga to'g'ri kelishi — to'plam ichidagi MA'LUMOT,
bu yerdagi qattiq bilim emas.
"""
from __future__ import annotations

# ── Nishonlar: ekstraktor bir kun to'ldirishi kerak bo'lgan BinOS maydonlari ────────────────
# 19 tasi `binos-1c-v1` dan (15 mahsulot maydoni + 4 tuzilma bloki), 4 tasi faqat discovery
# uchun (tarozi va ulangan uskuna) — ular bundle'ga chiqmaydi, lekin D27 shular bilan yopiladi.
BUNDLE_TARGETS = (
    "warehouses",
    "price_types",
    "selection.retail_price_type",
    "selection.purchase_price_type",
    "products.guid",
    "products.code",
    "products.article",
    "products.name",
    "products.kind",
    "products.is_folder",
    "products.deletion_mark",
    "products.has_characteristics",
    "products.has_series",
    "products.unit",
    "products.is_weighted",
    "products.plu",
    "products.barcodes",
    "products.prices",
    "products.stock",
)
DISCOVERY_ONLY_TARGETS = (
    "scale.plu_source",          # PLU qiymatlari 1C da qayerda turadi (D27) — yoki «yo'q»
    "scale.barcode_prefix",      # etiketka prefiksi 1C da sozlanadimi yoki tarozidami
    "scale.exchange_rule",       # offline almashinuv qoidasi (agar 1C tarozini boshqarsa)
    "equipment.connected",       # ulangan uskuna metadatasi umuman bormi
)
TARGETS = BUNDLE_TARGETS + DISCOVERY_ONLY_TARGETS

# ── Manba turlari: 1C metadata modelining umumiy tushunchalari ──────────────────────────────
SOURCE_KINDS = (
    "catalog",                       # Справочник
    "document",                      # Документ
    "information_register",          # РегистрСведений
    "accumulation_register",         # РегистрНакопления
    "chart_of_characteristic_types", # ПланВидовХарактеристик (BSP qo'shimcha rekvizitlari shu turda)
    "enum",                          # Перечисление
    "constant",                      # Константа
    "common_attribute",              # ОбщийРеквизит
    "attribute",                     # Реквизит (obyekt ichida)
    "dimension",                     # Измерение (registr ichida)
    "resource",                      # Ресурс (registr ichida)
    "tabular_section",               # Табличная часть
    "standard_attribute",            # Ссылка, Код, Наименование, ПометкаУдаления, ЭтоГруппа
    "virtual_table",                 # registrning virtual jadvali (platforma tushunchasi)
    "computed",                      # bir nechta manbadan hisoblanadi (masalan qator darajasidagi bool)
    "absent",                        # bu konfiguratsiyada YO'Q — bu ham to'liq javob
)

# ── Dalil turlari ───────────────────────────────────────────────────────────────────────────
# KUCHSIZ: o'zi bilan faqat CANDIDATE bera oladi. Nom mosligi hech qachon isbot emas —
# kengaytirilgan yoki o'zgartirilgan konfiguratsiyada nom bir xil, ma'no boshqa bo'lishi mumkin.
WEAK_EVIDENCE_KINDS = (
    "name_match",        # obyekt/maydon nomi kutilgan atamaga o'xshaydi
    "synonym_match",     # sinonimi mos
    "type_shape",        # tipi mos (masalan resurs — son, 3 kasr xona)
    "cardinality",       # qatorlar soni katalogga nisbatan mantiqiy
    "fill_ratio",        # to'ldirilganlik ulushi
    "value_domain",      # qiymatlar shakli (masalan 1–5 xonali raqam satri)
    "structural_link",   # o'lchovi nomenklatura katalogiga havola
)
# KUCHLI: `VERIFIED` ni FAQAT shular bera oladi.
STRONG_EVIDENCE_KINDS = (
    "human_confirmed",       # odam ekranda ko'rdi va tasdiqladi (kim va qachon — `detail` da)
    "arithmetic_proof",      # arifmetik isbot (masalan kg narxi × vazn = etiketkadagi summa)
    "contract_match",        # BinOS shartnomasi bilan aynan mos (masalan EAN-13 nazorat raqami)
    "cross_source_agreement",# ikki MUSTAQIL manba bir xil javob berdi
    "absence_proven",        # yo'qligi isbotlandi: butun metadata sanab chiqildi va topilmadi
)
EVIDENCE_KINDS = WEAK_EVIDENCE_KINDS + STRONG_EVIDENCE_KINDS

CONFIDENCE_VERIFIED = "VERIFIED"
CONFIDENCE_CANDIDATE = "CANDIDATE"
CONFIDENCE_UNKNOWN = "UNKNOWN"
CONFIDENCES = (CONFIDENCE_VERIFIED, CONFIDENCE_CANDIDATE, CONFIDENCE_UNKNOWN)


def confidence_error(confidence: str, evidence_kinds: list[str], source_kind: str | None) -> str | None:
    """Ishonch darajasi dalillar bilan haqlimi? Xato matnini qaytaradi, yoki `None`.

    QOIDA (egasining talabi): nom to'g'ri ko'ringani uchun CANDIDATE avtomatik VERIFIED
    bo'lib qolmaydi. Shuning uchun daraja dalil TURI bilan chegaralangan, dalil SONI bilan emas:
    yuzta `name_match` ham bitta `human_confirmed` o'rnini bosmaydi.
    """
    if confidence == CONFIDENCE_UNKNOWN:
        if evidence_kinds:
            return "UNKNOWN darajasida dalil bo'lmasligi kerak — dalil bor bo'lsa CANDIDATE yozing"
        return None

    if not evidence_kinds:
        return f"{confidence} darajasi kamida bitta dalil talab qiladi"

    if confidence == CONFIDENCE_CANDIDATE:
        return None

    # VERIFIED
    strong = [k for k in evidence_kinds if k in STRONG_EVIDENCE_KINDS]
    if not strong:
        return ("VERIFIED faqat kuchli dalil bilan beriladi "
                f"({', '.join(STRONG_EVIDENCE_KINDS)}); berilgani: {', '.join(sorted(set(evidence_kinds)))}")
    if source_kind == "absent" and "absence_proven" not in strong:
        return "source_kind='absent' VERIFIED bo'lishi uchun `absence_proven` dalili SHART"
    return None
