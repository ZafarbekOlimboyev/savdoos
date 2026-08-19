import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


class Scale(Base, PKMixin):
    """Do'kondagi elektron tarozi. SavdoOS mahsulotlarni PLU/narx bo'yicha sinxronlaydi;
    apparat bilan aloqa Scale Driver qatlami orqali (brendga bog'liq emas)."""
    __tablename__ = "scales"
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    driver: Mapped[str | None] = mapped_column(String, nullable=True)      # driver kaliti
    connection_type: Mapped[str] = mapped_column(String, default="lan")   # lan | usb
    host: Mapped[str | None] = mapped_column(String, nullable=True)        # IP (lan)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)       # TCP port (lan)
    com_port: Mapped[str | None] = mapped_column(String, nullable=True)    # COM3 (usb)
    baud: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_bits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parity: Mapped[str | None] = mapped_column(String, nullable=True)      # None|Even|Odd
    stop_bits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="disconnected")    # connected|checking|disconnected
    synced_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
