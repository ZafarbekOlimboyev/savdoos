# -*- coding: utf-8 -*-
"""VALYUTA — do'kon sozlamasi; HUJJATDA esa o'zgarmas TRANZAKSIYA SURATI.

Kontrakt (butun mahsulot bo'ylab):
  * `companies.currency` (ISO-4217) do'konning pul BIRLIGINI belgilaydi;
  * UI tili faqat MATNNI tarjima qiladi (klient tomoni: `packages/shared/src/receipt/format.ts`,
    `apps/mobile/lib/currency.dart`);
  * HUJJAT (sotuv, xarid) valyutasi YARATILGANDA suratga olinadi va keyin
    do'kon valyutasi o'zgarsa ham QAYTA YOZILMAYDI.

⚠️  NEGA SHU MODUL BOR. Ilgari `sales.currency` ni hech bir yozuvchi o'rnatmasdi va
    qiymatni ORM ning Python-tomon `default="UZS"` i berardi. `receipt/dto.py` esa
    `sale.currency or company.currency or "UZS"` deb o'qiydi — `'UZS'` truthy bo'lgani
    uchun `company.currency` SOTUV cheki uchun hech qachon so'ralmasdi. Natijada KGS
    do'konda sotuv cheki "so'm", qaytarish cheki (u company'ni to'g'ridan o'qiydi)
    "сом" berardi. 2026-10-03 da production'da JONLI tasdiqlandi (tenant `fayzan1`:
    `company=KGS`, 2 sotuv `sale=UZS`).

    Shu bois valyuta har yozuvchida ANIQ beriladi va yechim bitta joyda turadi:
    ikki nusxa bo'lsa ular yana ajralib ketardi.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session


def normalize(code: str | None) -> str:
    """ISO-4217 kodini normallashtiradi: `" kgs "` -> `"KGS"`; yaroqsiz -> `""`."""
    return (code or "").strip().upper()[:3]


def company_currency(db: Session, company_id: uuid.UUID) -> str:
    """Do'konning valyutasi (normallashtirilgan, bo'sh bo'lmaydi).

    `"UZS"` zaxirasi ikki holatda ishlaydi: (1) kompaniya qatori yo'q — bu FK
    tufayli YETIB BO'LMAYDI (har yozuvchi autentifikatsiya qilingan xodimning
    `company_id` sini beradi); (2) qator bor, lekin valyuta bo'sh — eski tenant.
    Ikkisi ham bugungi `tills.py` xulqi bilan AYNI (jim o'zgarish yo'q).
    """
    from app.models.org import Company
    co = db.get(Company, company_id)
    return normalize(co.currency if co else None) or "UZS"


def sale_currency(db: Session, sale_id: uuid.UUID) -> str | None:
    """Sotuvning SAQLANGAN valyuta surati; sotuv yo'q/bo'sh bo'lsa `None`.

    `returns` jadvalida valyuta ustuni YO'Q, shu bois sotuvga bog'langan
    qaytarishning valyutasi ASL SOTUVDAN o'qiladi.
    """
    from app.models.sales import Sale
    cur = db.query(Sale.currency).filter(Sale.id == sale_id).scalar()
    return normalize(cur) or None
