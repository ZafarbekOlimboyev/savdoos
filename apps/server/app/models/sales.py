import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, FullMixin, PKMixin
from app.models.enums import ReturnReason, SaleStatus


class Sale(Base, FullMixin):
    """Chek — append-only."""
    __tablename__ = "sales"
    __table_args__ = (UniqueConstraint("company_id", "receipt_no"),)
    receipt_no: Mapped[str] = mapped_column(String)
    uid: Mapped[str | None] = mapped_column(String, nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    cashier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    status: Mapped[SaleStatus] = mapped_column(
        SAEnum(SaleStatus, name="sale_status"), default=SaleStatus.completed
    )
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2))
    discount_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tax_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(14, 2))
    cost_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_offline: Mapped[bool] = mapped_column(Boolean, default=False)
    items: Mapped[list["SaleItem"]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    payments: Mapped[list["SalePayment"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class SaleItem(Base, PKMixin):
    """Chek qatori — narx va tannarx snapshot qilinadi."""
    __tablename__ = "sale_items"
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id", ondelete="CASCADE")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    name_snapshot: Mapped[str] = mapped_column(String)
    article_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    discount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tax_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id"), nullable=True
    )


class SalePayment(Base, PKMixin):
    __tablename__ = "sale_payments"
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id", ondelete="CASCADE")
    )
    method_code: Mapped[str] = mapped_column(String)          # cash|card|qr|credit
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    given_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    change_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    txn_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SaleDiscount(Base, PKMixin):
    __tablename__ = "sale_discounts"
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id", ondelete="CASCADE")
    )
    sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Numeric(14, 2))
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class Return(Base, FullMixin):
    __tablename__ = "returns"
    __table_args__ = (UniqueConstraint("company_id", "return_no"),)
    return_no: Mapped[str] = mapped_column(String)
    original_sale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    cashier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    reason: Mapped[ReturnReason] = mapped_column(
        SAEnum(ReturnReason, name="return_reason"), default=ReturnReason.customer
    )
    restock: Mapped[bool] = mapped_column(Boolean, default=True)   # omborga qaytdi / hisobdan chiqarildi
    refund_method: Mapped[str] = mapped_column(String, default="cash")
    total: Mapped[float] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    items: Mapped[list["ReturnItem"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class ReturnItem(Base, PKMixin):
    __tablename__ = "return_items"
    return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("returns.id", ondelete="CASCADE")
    )
    sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2))
