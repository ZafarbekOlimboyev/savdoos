"""SQLAlchemy 2.0 Base va umumiy mixinlar.

Har jadval loyiha qoidasiga amal qiladi: UUID id, created/updated, soft-delete,
sync uchun row_version, offline uchun client_uuid.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UUID


class Base(DeclarativeBase):
    pass


class PKMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncMixin:
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FullMixin(PKMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """Standart mutable jadval uchun to'liq ustunlar to'plami."""
