# -*- coding: utf-8 -*-
"""Phase 6A/2.5 uchun TAKLIF QILINGAN CHECK ifodalari — HALI ULANMAGAN.

⚠️  BU MODUL BOOT/RUNTIME YO'LIGA ULANMAGAN va Phase 2.5 implementatsiyasi EMAS.
    U faqat beshta ifodani BITTA joyda saqlaydi, shunda PG18 isbot testi bilan
    kelajakdagi runtime ro'yxati (`required_schema.CHECK_DEFINITIONS`) orasida
    nusxa-ko'chirish og'ishi bo'lmasin.
⚠️  Nomlar ATAYLAB `REQUIRED_PG_CONSTRAINTS` da ham, `CHECK_DEFINITIONS` da ham
    YO'Q. Ulanish Phase 2.5 ning O'Z commitida bo'ladi — shu paytgacha bu yerdagi
    hech narsa birorta jadvalga qo'yilmaydi. `tests/test_check_defs_pg.py` buni
    TEST bilan qadab qo'ygan: ulanmaganlik tasodif emas, qaror.

NEGA ALOHIDA ISBOT KERAK
========================
`initdb._ensure_lot_checks` katalogdagi ifodani `check_canon.same_check` bilan
kutilgan ta'rifga solishtiradi. Agar PostgreSQL ifodani kanonizator tanimaydigan
ko'rinishda yozsa, natija `CHECK_DEF_WRONG` bo'lib, cheklov HAR BOOT'da qayta
yaratilardi (yoki `CHECK_DEF_UNPARSED` bo'lib tayyorlik abadiy qizil qolardi).
Mahalliy to'plam PG16 da yuradi, production va staging esa PG18 — shu bois
ifodalar ishlatilishidan OLDIN aynan PG18 da isbotlanadi.
"""
from __future__ import annotations

#: `admin_audit_log` da obuna hodisasi bo'lsa aktor va ikkala snapshot MAJBURIY.
#  LIKE/escape ataylab ishlatilmadi: aniq ro'yxat tasodifiy prefiks mosligini ham
#  yo'q qiladi, kanonizatsiyasi ham soddaroq.
_AUDIT_SUB_ACTIONS = ("'SUBSCRIPTION_CREATE', 'SUBSCRIPTION_CANCEL', "
                      "'SUBSCRIPTION_REACTIVATE', 'SUBSCRIPTION_RESTRICT', "
                      "'SUBSCRIPTION_RESTORE'")

#: Taklif qilingan ifodalar. Kalit — cheklov nomi, qiymat — AYNAN yoziladigan matn.
SUBSCRIPTION_CHECK_DEFS: dict[str, str] = {
    #  `deleted_at` ustuni FIZIK qoladi (create_all DROP COLUMN qilmaydi), lekin
    #  qiymati taqiqlanadi — shu bilan `ux_subscriptions_company` qisman indeksi
    #  TO'LIQ noyoblikka aylanadi: kompaniyaga bitta qator, umrbod.
    "ck_sub_deleted_never": "deleted_at IS NULL",
    #  BIKONDISIONAL, implikatsiya EMAS: `status='ACTIVE'` + qolib ketgan
    #  `restricted_at` ham xuddi teskarisi kabi noqonuniy bo'lsin.
    "ck_sub_restricted_iff": "(status = 'RESTRICTED') = (restricted_at IS NOT NULL)",
    "ck_sub_cancelled_iff": "(status = 'CANCELLED') = (cancelled_at IS NOT NULL)",
    #  `GRACE` ATAYLAB yo'q: u faqat hisoblanadi, hech qachon saqlanmaydi.
    "ck_sub_status_persistable": "status IN ('ACTIVE', 'RESTRICTED', 'CANCELLED')",
    "ck_audit_sub_fields": (
        f"action NOT IN ({_AUDIT_SUB_ACTIONS}) "
        "OR (actor_admin_id IS NOT NULL AND before_summary IS NOT NULL "
        "AND after_summary IS NOT NULL AND reason IS NOT NULL)"),
}

#: Har bir cheklov qaysi MODEL jadvaliga tegishli — probe jadvali ustun TIPLARINI
#  modeldan oladi, ya'ni test bilan model orasida tip og'ishi bo'lishi mumkin emas.
SUBSCRIPTION_CHECK_TABLES: dict[str, str] = {
    "ck_sub_deleted_never": "subscriptions",
    "ck_sub_restricted_iff": "subscriptions",
    "ck_sub_cancelled_iff": "subscriptions",
    "ck_sub_status_persistable": "subscriptions",
    "ck_audit_sub_fields": "admin_audit_log",
}

#: Ifoda qaysi ustunlarga tegadi — probe jadvali AYNAN shularni oladi.
SUBSCRIPTION_CHECK_COLUMNS: dict[str, tuple[str, ...]] = {
    "ck_sub_deleted_never": ("deleted_at",),
    "ck_sub_restricted_iff": ("status", "restricted_at"),
    "ck_sub_cancelled_iff": ("status", "cancelled_at"),
    "ck_sub_status_persistable": ("status",),
    "ck_audit_sub_fields": ("action", "actor_admin_id", "before_summary",
                            "after_summary", "reason"),
}

#: Katalog yozuvlari — SERVERDAN o'qib yozilgan (PG 160002, mahalliy pgserver).
#  PG18 da AYNI matn chiqishi `tests/test_check_defs_pg.py` da DA'VO qilinadi va
#  CI `backend-pg18` job'ida isbotlanadi. Postgres yozuvni o'zgartirsa test qizil
#  bo'ladi — bu kutilgan xulq: kanonizator jim qolib qolmasin.
EXPECTED_CATALOG_RENDERINGS: dict[str, tuple[str, str]] = {
    'ck_sub_deleted_never': (
        '(deleted_at IS NULL)',
        'deleted_at IS NULL'),
    'ck_sub_restricted_iff': (
        "(((status)::text = 'RESTRICTED'::text) = (restricted_at IS NOT NULL))",
        "(status::text = 'RESTRICTED'::text) = (restricted_at IS NOT NULL)"),
    'ck_sub_cancelled_iff': (
        "(((status)::text = 'CANCELLED'::text) = (cancelled_at IS NOT NULL))",
        "(status::text = 'CANCELLED'::text) = (cancelled_at IS NOT NULL)"),
    'ck_sub_status_persistable': (
        "((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'RESTRICTED'::character varying, 'CANCELLED'::character varying])::text[]))",
        "status::text = ANY (ARRAY['ACTIVE'::character varying, 'RESTRICTED'::character varying, 'CANCELLED'::character varying]::text[])"),
    'ck_audit_sub_fields': (
        "(((action)::text <> ALL ((ARRAY['SUBSCRIPTION_CREATE'::character varying, 'SUBSCRIPTION_CANCEL'::character varying, 'SUBSCRIPTION_REACTIVATE'::character varying, 'SUBSCRIPTION_RESTRICT'::character varying, 'SUBSCRIPTION_RESTORE'::character varying])::text[])) OR ((actor_admin_id IS NOT NULL) AND (before_summary IS NOT NULL) AND (after_summary IS NOT NULL) AND (reason IS NOT NULL)))",
        "(action::text <> ALL (ARRAY['SUBSCRIPTION_CREATE'::character varying, 'SUBSCRIPTION_CANCEL'::character varying, 'SUBSCRIPTION_REACTIVATE'::character varying, 'SUBSCRIPTION_RESTRICT'::character varying, 'SUBSCRIPTION_RESTORE'::character varying]::text[])) OR actor_admin_id IS NOT NULL AND before_summary IS NOT NULL AND after_summary IS NOT NULL AND reason IS NOT NULL"),
}
