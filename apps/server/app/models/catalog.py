import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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


class Brand(Base, PKMixin):
    __tablename__ = "brands"
    name: Mapped[str] = mapped_column(String)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    __table_args__ = (UniqueConstraint("company_id", "article_code"),)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    article_code: Mapped[str] = mapped_column(String)          # ARTIKUL (barcode-uzun)
    sku: Mapped[str | None] = mapped_column(String, nullable=True)   # qisqa raqamli kod
    name: Mapped[str] = mapped_column(String)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # yaroqlilik muddati
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True
    )
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
    __tablename__ = "product_barcodes"
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    barcode: Mapped[str] = mapped_column(String, unique=True)
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
