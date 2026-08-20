import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin


class DeviceToken(Base, PKMixin, TimestampMixin):
    """Push (FCM) qurilma tokeni — do'kon bo'yicha, bildirishnoma yuborish uchun."""
    __tablename__ = "device_tokens"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    token: Mapped[str] = mapped_column(String, unique=True)
    platform: Mapped[str | None] = mapped_column(String, nullable=True)  # android|ios
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
