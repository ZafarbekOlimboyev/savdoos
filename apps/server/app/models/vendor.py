# -*- coding: utf-8 -*-
"""Vendor (cross-tenant) xavfsizlik holati — sessiyalar va urinishlar.

⚠️  NEGA BAZADA, REDIS'DA EMAS. Loyihada Redis YO'Q: `redis` paketi bog'liqlikda
    e'lon qilinmagan, Railway'da bunday servis mavjud emas, `settings.redis_url`
    esa hech qayerdan o'qilmaydigan qoldiq. Yangi infratuzilma qo'shish bu bosqich
    doirasidan tashqarida bo'lardi. Postgres esa ALLAQACHON bor va kerakli
    xossalarni beradi: qayta ishga tushishdan omon qoladi va bir nechta instans
    o'rtasida umumiy. Vendor autentifikatsiyasi kam chastotali (operator amallari),
    shu bois har urinishga bitta yozuv qimmat emas — kassir PIN yo'lidan farqli
    o'laroq, u bu bosqichda ataylab tegilmaydi.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UUID


class VendorSession(Base):
    """Vendor portali sessiyasi — BEKOR QILINADIGAN.

    Ilgari sessiya `base64(exp).hmac` dan iborat edi: ichida faqat muddat bor,
    server tomonda hech qanday holat yo'q. Ya'ni o'g'irlangan token 12 soat davomida
    ishlayverardi va uni to'xtatishning YAGONA yo'li master kalitni almashtirish edi
    (bu esa boshqa hamma narsani ham sindirardi). Endi har sessiya `jti` bilan shu
    yerda qayd etiladi, ya'ni bittasini alohida bekor qilish mumkin."""

    __tablename__ = "vendor_sessions"

    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Manba — tergov uchun. IP maxfiy ma'lumot emas va allowlist bilan birga ishlatiladi.
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class VendorAuthAttempt(Base):
    """Vendor autentifikatsiya urinishi — rate-limit uchun surilma oyna.

    FAQAT metama'lumot saqlanadi: kalit (IP yoki oqim nomi), natija turkumi va vaqt.
    Kalitning O'ZI, OTP va boshqa sirlar HECH QACHON yozilmaydi."""

    __tablename__ = "vendor_auth_attempts"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    # Rate-limit o'lchovi: "ip:<manba>" yoki "flow:login" / "flow:otp"
    bucket: Mapped[str] = mapped_column(String(128), index=True)
    # "key" | "otp" | "session" | "ip" — QAYSI komponent yiqilgani (sir emas)
    reason: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
