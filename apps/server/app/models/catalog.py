import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, ForeignKeyConstraint,
                        Integer, Numeric, String, Text, UniqueConstraint)
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, FullMixin, PKMixin, TimestampMixin
from app.models.enums import PriceType


class Unit(Base, PKMixin):
    __tablename__ = "units"
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    allow_fraction: Mapped[bool] = mapped_column(Boolean, default=False)


class Brand(Base, FullMixin):
    """Mahsulot brendi — HAR DO'KONNING O'ZINIKI.

    NEGA TENANT'GA TEGISHLI: brend katalogi — `categories` bilan bir xil toifadagi
    mahsulot o'lchovi, va `categories` allaqachon `company_id` bilan do'konga
    bog'langan (db/schema.sql da ikkalasi 6 qator oralig'ida turadi). Ikki do'kon
    bitta brend ro'yxatini ulashishi uchun hech qanday sabab yo'q.

    TARIX: `customer_groups` bilan bir xil — e'lon qilingan, lekin hech qachon
    yakunlanmagan (`Brand(...)` chaqiruvi, CRUD, UI, seed — hech biri yo'q).
    `deleted_at` endi `FullMixin` dan keladi (ilgari qo'lda e'lon qilingan edi).

    CROSS-TENANT HIMOYASI: `products` dagi kompozit FK uchun `UNIQUE (company_id, id)`."""

    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_brand_company_name"),
        UniqueConstraint("company_id", "id", name="uq_brand_company_id"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String)


class Category(Base, FullMixin):
    __tablename__ = "categories"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Product(Base, FullMixin):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("company_id", "article_code"),
        # Brend SHU do'konniki bo'lishi SHART (MATCH SIMPLE: brand_id NULL -> o'tkaziladi).
        ForeignKeyConstraint(
            ["company_id", "brand_id"], ["brands.company_id", "brands.id"],
            name="fk_products_brand_same_company",
        ),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    article_code: Mapped[str] = mapped_column(String)          # ARTIKUL (barcode-uzun)
    sku: Mapped[str | None] = mapped_column(String, nullable=True)   # qisqa raqamli kod
    name: Mapped[str] = mapped_column(String)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # yaroqlilik muddati
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    # Guruh bog'lamidagi kabi: FK ustunda EMAS, __table_args__ dagi KOMPOZIT FK'da.
    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("units.id"))
    base_buy_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    base_sell_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tax_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    is_weighted: Mapped[bool] = mapped_column(Boolean, default=False)
    plu_code: Mapped[str | None] = mapped_column(String, nullable=True)   # tarozi PLU kodi (og'irlikli mahsulot)
    scale_sync: Mapped[bool] = mapped_column(Boolean, default=False)       # taroziga yuborilsinmi
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    category: Mapped["Category | None"] = relationship(lazy="joined")
    barcodes: Mapped[list["ProductBarcode"]] = relationship(lazy="selectin")


class ProductBarcode(Base, PKMixin):
    """QA PC-003: barcode noyobligi KOMPANIYA doirasida (ilgari global unique edi —
    ikkinchi do'kon standart zavod EAN'ini ro'yxatga ololmasdi). company_id nullable —
    eski qatorlar migratsiyada backfill qilinadi (initdb)."""
    __tablename__ = "product_barcodes"
    __table_args__ = (UniqueConstraint("company_id", "barcode"),)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    barcode: Mapped[str] = mapped_column(String)
    pack_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=1)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductPrice(Base, PKMixin):
    __tablename__ = "product_prices"
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    kind: Mapped[PriceType] = mapped_column(SAEnum(PriceType, name="price_type"))
    price: Mapped[float] = mapped_column(Numeric(14, 2))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
