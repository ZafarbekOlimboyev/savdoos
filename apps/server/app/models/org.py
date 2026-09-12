import uuid

from sqlalchemy import (Boolean, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, FullMixin, PKMixin


class Company(Base, FullMixin):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String)
    # Do'kon login kodi (noyob) — vendor beradi. PIN login shu kod doirasida tekshiriladi.
    code: Mapped[str | None] = mapped_column(String, nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String, nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="UZS")


class Branch(Base, FullMixin):
    __tablename__ = "branches"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Tashkent")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Terminal(Base, FullMixin):
    __tablename__ = "terminals"
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    name: Mapped[str] = mapped_column(String)
    device_uuid: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DocCounter(Base, PKMixin):
    """Kompaniya-doiraviy hujjat raqami hisoblagichi (chek / qaytarish / kirim).

    ⚠️  NEGA JADVAL, NEGA `SEQUENCE` EMAS. Postgres `SEQUENCE` konkurrentlikda
        qulayroq, lekin bekor qilingan tranzaksiyada raqam YO'QOLADI. Chek
        raqami buxgalteriya hujjati: «#1288 dan keyin #1290» uzilishini
        tekshiruvda tushuntirib bo'lmaydi. Hisoblagich qatori tranzaksiya bilan
        birga qaytadi, ya'ni raqamlar UZLUKSIZ qoladi. Narxi — juda qisqa
        serializatsiya oynasi (raqam commit'dan sal oldin olinadi).

    `next_value` — KEYINGI beriladigan raqam emas, OXIRGI BERILGAN raqam:
    `INSERT ... ON CONFLICT DO UPDATE SET next_value = next_value + 1 RETURNING`
    naqshida qaytgan qiymat AYNAN ishlatiladi (`app/services/doc_seq.py`).
    """
    __tablename__ = "doc_counters"
    __table_args__ = (UniqueConstraint("company_id", "kind"),)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)   # sale | return | purchase
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
