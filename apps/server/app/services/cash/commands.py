"""CashPostingService — kirish (command) va natija (result) tiplari.

Ichki, tiplangan buyruq obyektlari (dataclass). Ustunlar manbasi bo'yicha ajratilgan:
  - CLIENT-supplied: cash_account_id, source_type/source_id/leg_index, direction, category,
    amount, currency, device_occurred_at, origin_shift_id, idempotency_key, origin_device_id,
    provenance, reconstruction_*, reverses_id, allow_negative/negative_reason.
  - SERVER-generated: tenant_id (emp.company_id'dan — clientга ISHONILMAYDI), server_received_at,
    recorded_at, resolved shift_id/posting_kind, transfer_group_id.
  - SERVER-validated: currency == account, account tenant/ACTIVE, timestamp, sufficiency.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class PostingCommand:
    # ── client-supplied (majburiy) ──
    cash_account_id: uuid.UUID
    source_type: str            # CashSourceType.value
    source_id: uuid.UUID
    direction: str              # "IN" | "OUT"
    category: str               # CashCategory.value
    amount: Decimal
    # ── client-supplied (ixtiyoriy) ──
    origin_shift_id: uuid.UUID | None = None
    leg_index: int = 0
    currency: str | None = None                 # None -> account currency
    device_occurred_at: datetime | None = None  # None -> online (server now)
    idempotency_key: str | None = None
    origin_device_id: str | None = None
    provenance: str = "NORMAL"                   # NORMAL | RECONSTRUCTION
    reconstruction_reason: str | None = None
    reconstruction_source_ref: str | None = None
    reverses_id: uuid.UUID | None = None
    transfer_group_id: uuid.UUID | None = None   # ichki (transfer method beradi)
    # ── manfiy-naqd override (TILL) ──
    allow_negative: bool = False
    negative_reason: str | None = None
    # ── server tomonда to'ldiriladi (clientга ishonilmaydi) ──
    tenant_id: uuid.UUID | None = None


@dataclass
class TransferCommand:
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal
    source_id: uuid.UUID
    currency: str | None = None
    device_occurred_at: datetime | None = None
    idempotency_key: str | None = None
    origin_device_id: str | None = None
    tenant_id: uuid.UUID | None = None


@dataclass
class ReversalCommand:
    reverses_id: uuid.UUID
    source_id: uuid.UUID           # yangi manba identifikatori (original'niki EMAS)
    cash_account_id: uuid.UUID
    origin_shift_id: uuid.UUID | None = None
    device_occurred_at: datetime | None = None
    idempotency_key: str | None = None
    reason: str | None = None
    tenant_id: uuid.UUID | None = None


IDEMPOTENCY_CREATED = "CREATED"
IDEMPOTENCY_DUPLICATE = "DUPLICATE_RETURNED"


@dataclass
class PostingResult:
    entry_ids: list[uuid.UUID]
    cash_account_id: uuid.UUID | None
    shift_id: uuid.UUID | None
    posting_kind: str | None
    amount: Decimal
    direction: str | None
    category: str | None
    currency: str | None
    device_occurred_at: datetime | None
    recorded_at: datetime | None
    idempotency: str = IDEMPOTENCY_CREATED
    exceptions: list[str] = field(default_factory=list)
    transfer_group_id: uuid.UUID | None = None

    @property
    def entry_id(self) -> uuid.UUID | None:
        return self.entry_ids[0] if self.entry_ids else None

    @property
    def is_duplicate(self) -> bool:
        return self.idempotency == IDEMPOTENCY_DUPLICATE
