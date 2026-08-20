import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin
from app.models.enums import MovementType


class Inventory(Base, PKMixin):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("product_id", "branch_id"),)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    reserved_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    min_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    max_qty: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    # Kam-qoldiq push allaqachon yuborilganmi (dedup: min ostiga tushganda 1 marta, restokda 0)
    low_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(default=1)


class StockBatch(Base, PKMixin):
    __tablename__ = "stock_batches"
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    batch_no: Mapped[str | None] = mapped_column(String, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockMovement(Base, PKMixin):
    """Immutable fakt-ledger: har zaxira harakati."""
    __tablename__ = "stock_movements"
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id"), nullable=True
    )
    type: Mapped[MovementType] = mapped_column(SAEnum(MovementType, name="movement_type"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    balance_after: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String, nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
