# -*- coding: utf-8 -*-
"""Umumiy (bo'linadigan) brute-force cheklovi — PostgreSQL asosida.

⚠️  NEGA XOTIRA EMAS. Kassir cheklovlari jarayon xotirasida edi: har deploy'da
    nolga tushardi va instanslar o'rtasida bo'linmasdi. Vendor yo'lida bu naqsh
    allaqachon isbotlangan, shu bois o'sha naqsh takrorlanadi — yangi
    infratuzilma (Redis) qo'shilmaydi, chunki loyihada u YO'Q.

⚠️  DO'KON QATLAMI QATTIQ RAD ETMAYDI. Phase 1 da aynan shu narsa DoS bo'lgan
    edi: `company_code` ni bilgan istalgan kishi 25 ta soxta PIN yuborib butun
    do'konni kassadan uzardi. Shuning uchun do'kon qatlami faqat SEKINLASHTIRADI.

⚠️  SAQLASH ISHLAMASA — YO'L OCHILMAYDI. Cheklovni o'lchay olmagan holatda
    urinishga ruxsat berish "cheklov bor" degan da'voni yolg'onga aylantiradi.
    Kassir yo'lida bu 503 (xizmat vaqtincha yo'q), ya'ni fail-closed.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.models.security import AuthAttempt

# ── Qatlamlar: (max_fails, window_seconds, xabar) ───────────────────────────
IP_TIER = (10, 300, "Juda ko'p urinish — 5 daqiqadan keyin qayta urining")
ACCT_TIER = (12, 900, "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring")
CAND_TIER = (5, 900, "Juda ko'p urinish — birozdan keyin qayta urining")

# Do'kon qatlami — SEKINLASHTIRISH (rad etish EMAS)
STORE_SOFT = 25
STORE_WINDOW = 900
STORE_STEP = 0.25
STORE_DELAY_MAX = 3.0

_MAX_WINDOW = max(IP_TIER[1], ACCT_TIER[1], CAND_TIER[1], STORE_WINDOW)

# ⚠️  TAHDID TAHLILI VA NEGA TUZ `SECRET_KEY` DAN OLINADI.
#
#     4 raqamli PIN fazosi 10 000 ta, ya'ni PIN'ning oddiy `sha256` i rainbow-table
#     bilan bir soniyada qaytariladi. Shu bois nomzod kaliti HMAC bilan tuzlanadi.
#
#     Tuz JARAYONGA XOS BO'LMASLIGI kerak: `os.urandom` bilan har instans BOSHQA
#     kalit hisoblardi va (a) ikki replika bir-birining hisoblagichini KO'RMASDI,
#     (b) har deploy'dan keyin nomzod qatlami NOLGA tushardi — ya'ni "umumiy va
#     restart'dan omon qoladigan cheklov" degan maqsad aynan shu qatlamda
#     bajarilmasdi.
#
#     `SECRET_KEY` esa barcha replikalarda BIR XIL, bazada SAQLANMAYDI va
#     allaqachon kuch siyosatidan o'tadi. Bazani o'qigan tomon kalitlardan PIN'ni
#     tiklay olmaydi. Qolaversa, bu kalitlar faqat NOTO'G'RI urinishlar uchun
#     yoziladi — ya'ni ular hech qachon HAQIQIY PIN'ni oshkor qilmaydi.
def _pin_salt() -> bytes:
    from app.core.config import settings
    return hashlib.sha256(("pin-bucket|" + settings.secret_key).encode()).digest()

_last_prune = [0.0]


def candidate_bucket(company_id, pin: str) -> str:
    """(do'kon, PIN qiymati) uchun qaytarib bo'lmaydigan kalit."""
    mac = hmac.new(_pin_salt(), f"{company_id}|{pin}".encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


def _prune(db) -> None:
    """Eskirgan yozuvlarni tozalaydi — jadval cheksiz o'smasin."""
    now = time.time()
    if now - _last_prune[0] < 300:          # har 5 daqiqada bir marta (arzon)
        return
    _last_prune[0] = now
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_MAX_WINDOW)
    db.execute(delete(AuthAttempt).where(AuthAttempt.occurred_at < cutoff))
    db.commit()


def _count(db, dimension: str, bucket: str, window: int, company_id=None) -> int:
    since = datetime.now(timezone.utc) - timedelta(seconds=window)
    q = (select(func.count()).select_from(AuthAttempt)
         .where(AuthAttempt.dimension == dimension,
                AuthAttempt.bucket == bucket,
                AuthAttempt.occurred_at >= since))
    if company_id is not None:
        q = q.where(AuthAttempt.company_id == company_id)
    return db.execute(q).scalar() or 0


def guard(db, dimension: str, bucket: str, tier: tuple, company_id=None) -> None:
    """Chegara oshsa 429. Oyna bilan cheklangan — DOIMIY blok yo'q."""
    max_fails, window, msg = tier
    try:
        _prune(db)
        n = _count(db, dimension, bucket, window, company_id)
    except HTTPException:
        raise
    except Exception as e:                   # noqa: BLE001
        db.rollback()
        raise HTTPException(503, "Xavfsizlik cheklovini tekshirib bo'lmadi") from e
    if n >= max_fails:
        raise HTTPException(429, msg)


def over_limit(db, dimension: str, bucket: str, tier: tuple, company_id=None) -> bool:
    """Chegara oshganmi — 429 OTMAYDI, faqat javob qaytaradi.

    ⚠️  NEGA ALOHIDA. `guard` 429 otadi va o'sha 429 ba'zi yo'llarda OSHKOR
        QILUVCHI bo'lib qoladi: agar qatlam faqat MA'LUM shartda ishlasa,
        "429 keldi" degan javobning o'zi shu shart bajarilganini tasdiqlaydi.
        Bunday joylarda chaqiruvchi cheklovni qo'llaydi, lekin javobni
        boshqa xatolar bilan BIR XIL qiladi.

    ⚠️  Saqlash ishlamasa — YO'L OCHILMAYDI (fail-closed): `guard` bilan izchil
        ravishda 503 ko'tariladi."""
    max_fails, window, _ = tier
    try:
        _prune(db)
        n = _count(db, dimension, bucket, window, company_id)
    except HTTPException:
        raise
    except Exception as e:                   # noqa: BLE001
        db.rollback()
        raise HTTPException(503, "Xavfsizlik cheklovini tekshirib bo'lmadi") from e
    return n >= max_fails


def record(db, entries) -> None:
    """Muvaffaqiyatsiz urinishlarni qayd etadi: [(dimension, bucket, company_id), ...]."""
    now = datetime.now(timezone.utc)
    try:
        for dimension, bucket, company_id in entries:
            db.add(AuthAttempt(dimension=dimension, bucket=bucket,
                               company_id=company_id, occurred_at=now))
        db.commit()
    except Exception:                        # noqa: BLE001
        db.rollback()
        raise


def clear(db, entries) -> None:
    """Muvaffaqiyatli kirishda tanlangan o'lchovlarni tozalaydi.

    ⚠️  Do'kon qatlami ATAYLAB tozalanmaydi: aks holda insider "9 xato + o'z
        PIN'i bilan 1 kirish" sikli bilan hisoblagichni nolga tushirib,
        hamkasb PIN'ini cheksiz taxmin qilardi."""
    try:
        for dimension, bucket, company_id in entries:
            q = delete(AuthAttempt).where(AuthAttempt.dimension == dimension,
                                          AuthAttempt.bucket == bucket)
            if company_id is not None:
                q = q.where(AuthAttempt.company_id == company_id)
            db.execute(q)
        db.commit()
    except Exception:                        # noqa: BLE001
        db.rollback()


def store_backoff(db, company_id) -> float:
    """Do'kon bo'yicha xatolar ko'p bo'lsa KECHIKISH (rad etish EMAS)."""
    try:
        n = _count(db, "store", str(company_id), STORE_WINDOW, company_id)
    except Exception:                        # noqa: BLE001
        db.rollback()
        return 0.0
    over = n - STORE_SOFT
    if over <= 0:
        return 0.0
    return min(over * STORE_STEP, STORE_DELAY_MAX)
