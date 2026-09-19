# -*- coding: utf-8 -*-
"""Chek / logo / chop etish xato MATNLARI va barqaror KODLARI (Phase 5F).

⚠️  MATN — TARJIMA KALITI. `detail` AYNAN shu satr bo'lib mijozga boradi va
    `packages/shared/src/lib/serverErrorsReceipt.ts` lug'atida KALIT sifatida
    qidiriladi (rus/kirill do'konda xom lotin matn chiqmasin). Matnni o'zgartirish
    = tarjimani uzish: `tests/test_receipt_error_texts.py` har matn lug'atda
    AYNAN borligini tekshiradi.
⚠️  KOD — MATNDAN TASHQARIDA (`X-Error-Code`, `app/core/error_codes` naqshi). Kod
    qiymati o'zgarmaydi: mijoz qarorini (masalan «nusxa chop et») shunga quradi.
"""
from fastapi import HTTPException

from app.core.error_codes import HEADER

# ── YANGI matnlar (serverErrorsReceipt.ts da KALIT) ──────────────────────────
SCOPE_COMPANY_FORBIDDEN = ("Ruxsat yo'q: kompaniya chek shablonini faqat barcha filiallarga "
                           "kirish huquqi bor xodim o'zgartiradi")
LOGO_NOT_FOUND = "Logo topilmadi"
LOGO_TOO_LARGE = "Logo fayli juda katta (ko'pi bilan 2 MB)"
LOGO_BAD_FORMAT = "Logo faqat PNG, JPEG yoki WebP bo'lishi mumkin"
LOGO_CORRUPT = "Logo rasmi o'qilmadi yoki buzilgan"
LOGO_DIMENSIONS = "Logo o'lchami juda katta (ko'pi bilan 2048×2048 piksel)"
LOGO_TOO_SMALL = "Logo juda kichik (kamida 16×16 piksel)"
LOGO_ANIMATED = "Animatsiyali rasm logo sifatida qabul qilinmaydi"
# 503: jarayondagi dekodlash joylari band (CPU/xotira chegarasi) — mijoz keyinroq qayta yuboradi.
LOGO_BUSY = "Logo hozir qayta ishlanmoqda — birozdan keyin urinib ko'ring"
RETURN_NOT_FOUND = "Qaytarish topilmadi"
PRINT_ORIGINAL_EXISTS = "Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting"
PRINT_JOB_FINAL = "Chop etish holati yakunlangan — o'zgartirib bo'lmaydi"
PRINT_JOB_INVALID = "Chop etish so'rovi noto'g'ri"
# 409: asl chekni BOSHQA qurilma (boshqa `claim_token`) hozir band qilgan — mijoz NUSXA chop etadi.
PRINT_JOB_BUSY = "Bu chek hozir boshqa qurilmada chop etilmoqda — nusxa chop eting"

NEW_TEXTS = (SCOPE_COMPANY_FORBIDDEN, LOGO_NOT_FOUND, LOGO_TOO_LARGE, LOGO_BAD_FORMAT,
             LOGO_CORRUPT, LOGO_DIMENSIONS, LOGO_TOO_SMALL, LOGO_ANIMATED, LOGO_BUSY,
             RETURN_NOT_FOUND, PRINT_ORIGINAL_EXISTS, PRINT_JOB_FINAL, PRINT_JOB_INVALID,
             PRINT_JOB_BUSY)

# ── DINAMIK matnlar (lug'atda REGEX bilan) ───────────────────────────────────
# `receipt: noma'lum maydon '{f}'` — eski `PUT /settings` matni, moslik uchun AYNAN o'zi.
UNKNOWN_FIELD_TMPL = "receipt: noma'lum maydon '{}'"
INVALID_FIELD_TMPL = "Chek sozlamasi noto'g'ri: {}"

# ── MAVJUD matnlar (avto-generatsiya `serverErrors.ts` da allaqachon bor) ────
BRANCH_NOT_FOUND = "Filial topilmadi"
SALE_NOT_FOUND = "Chek topilmadi"

EXISTING_TEXTS = (BRANCH_NOT_FOUND, SALE_NOT_FOUND)

# ── Barqaror kodlar (`X-Error-Code`) ─────────────────────────────────────────
RECEIPT_SCOPE_COMPANY_FORBIDDEN = "RECEIPT_SCOPE_COMPANY_FORBIDDEN"
PRINT_ORIGINAL_EXISTS_CODE = "PRINT_ORIGINAL_EXISTS"
PRINT_JOB_FINAL_CODE = "PRINT_JOB_FINAL"
PRINT_JOB_INVALID_CODE = "PRINT_JOB_INVALID"
PRINT_JOB_BUSY_CODE = "PRINT_JOB_BUSY"


def invalid_field(field: str) -> HTTPException:
    return HTTPException(400, INVALID_FIELD_TMPL.format(field))


def unknown_field(field) -> HTTPException:
    return HTTPException(400, UNKNOWN_FIELD_TMPL.format(field))


def scope_company_forbidden() -> HTTPException:
    return HTTPException(403, SCOPE_COMPANY_FORBIDDEN,
                         headers={HEADER: RECEIPT_SCOPE_COMPANY_FORBIDDEN})


def branch_not_found() -> HTTPException:
    return HTTPException(404, BRANCH_NOT_FOUND)


def print_job_invalid(status: int = 400) -> HTTPException:
    return HTTPException(status, PRINT_JOB_INVALID, headers={HEADER: PRINT_JOB_INVALID_CODE})


def print_job_busy() -> HTTPException:
    return HTTPException(409, PRINT_JOB_BUSY, headers={HEADER: PRINT_JOB_BUSY_CODE})
