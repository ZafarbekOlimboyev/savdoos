# -*- coding: utf-8 -*-
"""Autentifikatsiya urinishlari — UMUMIY (bo'linadigan) brute-force holati.

⚠️  NEGA XOTIRADA EMAS. Kassir cheklovlari jarayon xotirasidagi lug'atda edi:
    har deploy'da NOLGA tushardi va instanslar o'rtasida BO'LINMASDI. Ya'ni
    hujumchi deploy kutib yoki boshqa instansga urib cheklovni chetlab o'tardi,
    va "10 xatodan keyin blok" degan kafolat amalda hech narsani kafolatlamasdi.
    Postgres allaqachon bor va vendor yo'lida shu naqsh isbotlangan.

⚠️  `company_id` ATAYLAB nullable. Ikki xil o'lchov bor:

      · TENANTGA TEGISHLI (company_id to'ldirilgan) — nomzod-PIN va do'kon
        qatlamlari. Do'kon o'chirilsa ular ham o'chishi KERAK, shuning uchun
        ular FK grafi orqali tenantga bog'langan.

      · GLOBAL (company_id NULL) — IP qatlami. U do'kon ANIQLANISHIDAN OLDIN
        tekshiriladi va ATAYLAB do'konlar bo'ylab umumiy: aks holda hujumchi
        har so'rovda boshqa `company_code` yuborib, har safar yangi bo'sh
        hisoblagich ochib, IP cheklovini butunlay chetlab o'tardi. Bu qator
        biror do'konning ma'lumoti EMAS, shuning uchun purge uni o'chirmaydi —
        va bu to'g'ri.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UUID


class AuthAttempt(Base):
    """Bitta muvaffaqiyatsiz autentifikatsiya urinishi.

    SIR SAQLANMAYDI: `bucket` — qaytarib bo'lmaydigan kalit (IP, yoki PIN
    qiymatining jarayon-tuzi bilan HMAC'i), `dimension` esa qaysi qatlam ekani."""

    __tablename__ = "auth_attempts"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    # Tenantga tegishli qatlamlar uchun to'ldiriladi; IP qatlamida NULL (yuqoriga qarang).
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    # "ip" | "cand" | "acct" | "store"
    dimension: Mapped[str] = mapped_column(String(16), index=True)
    bucket: Mapped[str] = mapped_column(String(128), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
