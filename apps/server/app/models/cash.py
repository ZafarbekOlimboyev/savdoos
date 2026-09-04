"""Cash quyi tizimi — ORM modellar (MAP-only).

MUHIM: bu modellar `cash` sxemasidagi jadvallarга MAP qiladi, ularni YARATMAYDI.
Yagona haqiqat manbasi — `app/db/cash/cash_ddl_v1.sql` (trigger/constraint/index).
Shu sabab modellar ALOHIDA `CashBase` metadata'sida: app'ning `Base.metadata.create_all`
bularга TEGMAYDI (raw DDL sxemani o'rnatadi, ORM faqat o'qish/yozish uchun map qiladi).

Faqat PostgreSQL: jadvallar `cash` schema'sida; enum ustunlari `cash.<type>` PG enum'ига
bog'lanadi (create_type=False — DDL yaratadi).

TENANT BINDING: `tenant_id` — SavdoOS'da bu `companies.id` (tenant = kompaniya).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.types import JSONB, UUID

CASH_SCHEMA = "cash"


class CashBase(DeclarativeBase):
    """Cash modellar uchun alohida metadata — app Base.create_all bunga tegmaydi."""


# ── Enums (DDL cash.* enum turlariga mos) ────────────────────────────────────
class CashAccountType(str, enum.Enum):
    TILL = "TILL"
    SAFE = "SAFE"


class CashAccountStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CashShiftStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class CashPostingKind(str, enum.Enum):
    ON_SHIFT = "ON_SHIFT"
    OFF_SHIFT = "OFF_SHIFT"
    LATE_SYNC = "LATE_SYNC"


class CashDirection(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"


class CashProvenance(str, enum.Enum):
    NORMAL = "NORMAL"
    RECONSTRUCTION = "RECONSTRUCTION"


class CashReconTarget(str, enum.Enum):
    SHIFT = "SHIFT"
    ACCOUNT = "ACCOUNT"


class CashReconState(str, enum.Enum):
    PENDING = "PENDING"
    EXCEPTION = "EXCEPTION"
    RECONCILED = "RECONCILED"


class CashExceptionKind(str, enum.Enum):
    TIMESTAMP_OUT_OF_WINDOW = "TIMESTAMP_OUT_OF_WINDOW"
    UNRESOLVED_OFF_SHIFT = "UNRESOLVED_OFF_SHIFT"
    NEGATIVE_OVERRIDE = "NEGATIVE_OVERRIDE"
    LATE_SYNC_UNACK = "LATE_SYNC_UNACK"


class CashExceptionState(str, enum.Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class CashSourceType(str, enum.Enum):
    SALE = "SALE"
    RETURN = "RETURN"
    CUSTOMER_PAYMENT = "CUSTOMER_PAYMENT"
    SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
    PURCHASE = "PURCHASE"
    PURCHASE_RETURN = "PURCHASE_RETURN"
    CASH_OP = "CASH_OP"
    TRANSFER = "TRANSFER"
    SHIFT_OPEN = "SHIFT_OPEN"


class CashCategory(str, enum.Enum):
    OPENING = "OPENING"
    SALE = "SALE"
    REFUND = "REFUND"
    DEBT_IN = "DEBT_IN"
    SUPPLIER_OUT = "SUPPLIER_OUT"
    PURCHASE_OUT = "PURCHASE_OUT"
    PURCHASE_RETURN = "PURCHASE_RETURN"
    EXPENSE = "EXPENSE"
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    TRANSFER = "TRANSFER"
    BANK_DEPOSIT = "BANK_DEPOSIT"
    ADJUSTMENT = "ADJUSTMENT"


def _pg_enum(pg_name: str, py: "type[enum.Enum]") -> SAEnum:
    """Mavjud PG enum turiga (cash.<pg_name>) bog'lanadi — YARATMAYDI (create_type=False).

    Python tomonda oddiy STRING qiymatlar (chaqiruvchilar .value beradi). Har ustun uchun
    yangi nusxa (bir type obyektini bir nechta ustun ulashmasin)."""
    return SAEnum(
        *[m.value for m in py],
        name=pg_name,
        schema=CASH_SCHEMA,
        create_type=False,
        native_enum=True,
        validate_strings=True,
    )


# ── D. cash_accounts ─────────────────────────────────────────────────────────
class CashAccount(CashBase):
    __tablename__ = "cash_accounts"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # -> companies.id
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # -> branches.id
    type: Mapped[str] = mapped_column(_pg_enum("cash_account_type", CashAccountType))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(
        _pg_enum("cash_account_status", CashAccountStatus), default=CashAccountStatus.ACTIVE.value
    )
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── E. cash_transfers ────────────────────────────────────────────────────────
class CashTransfer(CashBase):
    __tablename__ = "cash_transfers"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_accounts.id")
    )
    to_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_accounts.id")
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── F. shifts (cash sxemasidagi — public.shifts'dan alohida) ─────────────────
class CashShift(CashBase):
    __tablename__ = "shifts"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    cash_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_accounts.id")
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    account_type: Mapped[str] = mapped_column(_pg_enum("cash_account_type", CashAccountType))
    status: Mapped[str] = mapped_column(
        _pg_enum("cash_shift_status", CashShiftStatus), default=CashShiftStatus.OPEN.value
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(BigInteger, default=1)

    # lazy="select" (joined EMAS): `select(CashShift)...with_for_update()` outer-join hosil
    # qilmasin (Postgres FOR UPDATE nullable outer-join tomonига qo'llanmaydi).
    account: Mapped["CashAccount"] = relationship(lazy="select")


# ── G. reconciliation_records ────────────────────────────────────────────────
class ReconciliationRecord(CashBase):
    __tablename__ = "reconciliation_records"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    target_type: Mapped[str] = mapped_column(_pg_enum("cash_recon_target", CashReconTarget))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.shifts.id"), nullable=True
    )
    cash_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_accounts.id"), nullable=True
    )
    account_type: Mapped[str | None] = mapped_column(
        _pg_enum("cash_account_type", CashAccountType), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    ledger_balance_snapshot: Mapped[float] = mapped_column(Numeric(14, 2))
    counted_cash: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    difference: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    state: Mapped[str] = mapped_column(
        _pg_enum("cash_recon_state", CashReconState), default=CashReconState.PENDING.value
    )
    exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── H. cash_ledger_entries (immutable, append-only) ──────────────────────────
class CashLedgerEntry(CashBase):
    __tablename__ = "cash_ledger_entries"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    cash_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_accounts.id")
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    account_type: Mapped[str] = mapped_column(_pg_enum("cash_account_type", CashAccountType))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.shifts.id"), nullable=True
    )
    posting_kind: Mapped[str] = mapped_column(_pg_enum("cash_posting_kind", CashPostingKind))
    source_type: Mapped[str] = mapped_column(_pg_enum("cash_source_type", CashSourceType))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    leg_index: Mapped[int] = mapped_column(Integer, default=0)
    direction: Mapped[str] = mapped_column(_pg_enum("cash_direction", CashDirection))
    category: Mapped[str] = mapped_column(_pg_enum("cash_category", CashCategory))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    device_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_ledger_entries.id"), nullable=True
    )
    transfer_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_transfers.id"), nullable=True
    )
    origin_device_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str] = mapped_column(
        _pg_enum("cash_provenance", CashProvenance), default=CashProvenance.NORMAL.value
    )
    reconstruction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconstruction_source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    account: Mapped["CashAccount"] = relationship(foreign_keys=[cash_account_id], lazy="select")
    shift: Mapped["CashShift | None"] = relationship(foreign_keys=[shift_id], lazy="select")


# ── I. reconciliation_assignments (append-only) ──────────────────────────────
class ReconciliationAssignment(CashBase):
    __tablename__ = "reconciliation_assignments"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_ledger_entries.id")
    )
    assigned_shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.shifts.id")
    )
    cash_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_accounts.id")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── J. negative_cash_approvals (append-only) ─────────────────────────────────
class NegativeCashApproval(CashBase):
    __tablename__ = "negative_cash_approvals"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_ledger_entries.id")
    )
    cash_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_accounts.id")
    )
    direction: Mapped[str] = mapped_column(_pg_enum("cash_direction", CashDirection))
    account_type: Mapped[str] = mapped_column(_pg_enum("cash_account_type", CashAccountType))
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    till_balance_before: Mapped[float] = mapped_column(Numeric(14, 2))
    till_balance_after: Mapped[float] = mapped_column(Numeric(14, 2))
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── K. cash_ledger_exceptions (state mutable) ────────────────────────────────
class CashLedgerException(CashBase):
    __tablename__ = "cash_ledger_exceptions"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{CASH_SCHEMA}.cash_ledger_entries.id")
    )
    kind: Mapped[str] = mapped_column(_pg_enum("cash_exception_kind", CashExceptionKind))
    state: Mapped[str] = mapped_column(
        _pg_enum("cash_exception_state", CashExceptionState), default=CashExceptionState.OPEN.value
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── L. audit_logs (cash sxemasidagi — public.audit_logs'dan alohida) ─────────
class CashAuditLog(CashBase):
    __tablename__ = "audit_logs"
    __table_args__ = {"schema": CASH_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = [
    "CashBase",
    "CashAccount",
    "CashTransfer",
    "CashShift",
    "ReconciliationRecord",
    "CashLedgerEntry",
    "ReconciliationAssignment",
    "NegativeCashApproval",
    "CashLedgerException",
    "CashAuditLog",
    "CashAccountType",
    "CashAccountStatus",
    "CashShiftStatus",
    "CashPostingKind",
    "CashDirection",
    "CashProvenance",
    "CashReconTarget",
    "CashReconState",
    "CashExceptionKind",
    "CashExceptionState",
    "CashSourceType",
    "CashCategory",
]
