import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from app.db.types import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


class PaymentMethod(Base, PKMixin):
    __tablename__ = "payment_methods"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String)                 # cash|card|qr|credit
    name: Mapped[str] = mapped_column(String)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class TaxRate(Base, PKMixin):
    __tablename__ = "tax_rates"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String)
    rate: Mapped[float] = mapped_column(Numeric(5, 2))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ReceiptTemplate(Base, PKMixin):
    __tablename__ = "receipt_templates"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    header: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer: Mapped[str | None] = mapped_column(Text, nullable=True)
    show_barcode: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class Setting(Base, PKMixin):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("company_id", "branch_id", "key"),)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    key: Mapped[str] = mapped_column(String)                  # features|payments|store_info|tax|receipt
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
