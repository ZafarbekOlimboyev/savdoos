import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from app.db.types import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


class SyncDevice(Base, PKMixin):
    """Kassa qurilmasi — OPERATOR TELEMETRIYASI (hisobot uchun, boshqaruv uchun EMAS).

    NEGA KERAK: buzuvchi naqd relizidan oldin operator "barcha faol kassalar kerakli
    versiyadami?" degan savolga JAVOB BERA OLISHI kerak. Ilgari `app_version` ustuni bor edi,
    lekin mijoz uni HECH QACHON to'ldirmasdi — ya'ni server qaysi qurilmada qaysi build
    ishlayotganini bilmasdi va yagona yo'l kassirdan "Sozlamalar" ekranini o'qishni so'rash edi.

    HISOBOT XOLIS: `pending_ops`/`failed_ops` — QURILMA aytgan son. Server ularni O'YLAB
    TOPMAYDI va "navbat bo'sh" deb TAXMIN QILMAYDI: hech qachon xabar bermagan qurilma uchun
    qiymat NULL bo'lib qoladi (nol EMAS) — "bilmayman" va "bo'sh" ARALASHTIRILMAYDI."""

    __tablename__ = "sync_devices"
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    device_uuid: Mapped[str] = mapped_column(String, unique=True)
    app_version: Mapped[str | None] = mapped_column(String, nullable=True)
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ── Operator konteksti: qurilmani DO'KON va FILIALga bog'laydi ────────────────
    # Ilgari faqat nullable `terminal_id` bor edi — terminal ro'yxatdan o'tmagan qurilma
    # hech qanday filialga bog'lanmasdi va "F01 kassalari tayyormi?" savoliga javob yo'q edi.
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    app_name: Mapped[str | None] = mapped_column(String, nullable=True)      # pos | manager
    platform: Mapped[str | None] = mapped_column(String, nullable=True)      # win32 | darwin | ...
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ── Offline navbat (QURILMA xabar qiladi; NULL = hech qachon xabar bermagan) ──
    pending_ops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_ops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncLog(Base, PKMixin):
    __tablename__ = "sync_log"
    device_uuid: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)            # push|pull
    entity: Mapped[str] = mapped_column(String)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    op: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ok")  # ok|duplicate|error
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    device_uuid: Mapped[str] = mapped_column(String, primary_key=True)
    entity: Mapped[str] = mapped_column(String, primary_key=True)
    last_pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String)
    entity: Mapped[str] = mapped_column(String)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    event_type: Mapped[str] = mapped_column(String)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
