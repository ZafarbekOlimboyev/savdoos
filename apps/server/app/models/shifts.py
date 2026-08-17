import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, FullMixin, PKMixin
from app.models.enums import CashMovementType, ShiftStatus


class Shift(Base, FullMixin):
    __tablename__ = "shifts"
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    cashier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opening_cash: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    expected_cash: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    counted_cash: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    difference: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[ShiftStatus] = mapped_column(
        SAEnum(ShiftStatus, name="shift_status"), default=ShiftStatus.open
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CashMovement(Base, PKMixin):
    __tablename__ = "cash_movements"
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="CASCADE")
    )
    type: Mapped[CashMovementType] = mapped_column(SAEnum(CashMovementType, name="cash_movement_type"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
