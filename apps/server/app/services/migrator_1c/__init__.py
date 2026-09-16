# -*- coding: utf-8 -*-
"""Fayzan 1C Migrator V1 — BIR MARTALIK, READ-ONLY 1C -> BinOS migratsiyasi.

Bu DOIMIY sinxronizatsiya EMAS. Yo'nalish FAQAT 1C -> BinOS; BinOS 1C'ga hech narsa yozmaydi.

Oqim (har bosqich alohida modul):

    bundle.py     1C eksport fayli (binos-1c-v1): SHA256, manifest, qat'iy tiplar
    normalize.py  Decimal / GUID / barkod / birlik — yo'qotishsiz kanonik ko'rinish
    catalog.py    BinOS katalogining FAQAT O'QISH ko'rinishi + barmoq izi
    classify.py   quruq yurish: toifalar, ziddiyatlar, rekonsiliatsiya (YOZUVSIZ)
    mapping.py    operator tasdiqlagan qarorlar -> deterministik reja
    apply.py      rejani qo'llash (Phase 5A da production'da TAQIQLANGAN)
    guard.py      muhit / baza identiteti darvozalari

QAYTA ISHLATILGAN MAVJUD YADRO (parallel engine qurilmagan):
  · `catalog_match.norm_key`           — nom kaliti (NFKC + casefold)
  · `ux_products_external_identity`   — (company_id, source_system, external_id) noyobligi
  · `ux_import_jobs_snapshot`         — bitta snapshot uchun bitta commit
  · `ux_movements_cutover_key`        — ref_type='1c_cutover' harakati takrorlanmaydi
  · `import_jobs` / `settings.catalog`— audit izi va PRE_LIVE/LIVE darvozasi
  · `catalog_reset.environment_name` / `platform_environment_name` — fail-closed muhit
  · `stock_gate.tracked_ids`          — partiya kuzatuvi yoqilgan mahsulotga tegilmaydi
"""

SCHEMA_VERSION = "binos-1c-v1"
MAPPING_SCHEMA_VERSION = "binos-1c-mapping-v1"
REPORT_SCHEMA_VERSION = "binos-1c-dryrun-v1"
SOURCE_SYSTEM = "1c"
MOVEMENT_REF_TYPE = "1c_cutover"          # ux_movements_cutover_key shu ref_type'ga bog'langan
CONTENT_HASH_VERSION = 2                  # import_jobs.hash_contract_version (v1 = V2 float xeshi)

# Phase 5A: bu tizimlarga APPLY HECH QACHON ruxsat etilmaydi (kodda qat'iy).
PRODUCTION_SYSTEM_IDENTIFIERS = frozenset({"7674898282858840119"})
# APPLY faqat shu ro'yxatdagi (production BO'LMAGAN) Postgres klasterlarida — staging demo bazasi.
# Vaqtinchalik mahalliy/CI klonlari `MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS` bilan qo'shiladi (guard.py).
NON_PRODUCTION_SYSTEM_IDENTIFIERS = frozenset({"7683497876193431618"})
