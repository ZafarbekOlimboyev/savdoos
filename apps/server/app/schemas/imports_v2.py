# -*- coding: utf-8 -*-
"""1С Cutover V2 — import shartnomasi.

Eski `/products/import/*` shartnomasi (nom+narx+qoldiq, faqat-yaratish) O'ZGARISHSIZ
qoladi — Manager UI unga tayanadi. Bu — YONIDAGI yangi shartnoma.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ImportMode(str, Enum):
    """Rejim ANIQ berilishi shart — "aqlli" avtomatik yangilash YO'Q."""
    INITIAL_CREATE = "INITIAL_CREATE"        # bo'sh katalogga birinchi migratsiya
    CUTOVER_REFRESH = "CUTOVER_REFRESH"      # ishga tushishdan OLDINGI oxirgi snapshot (Phase 2)
    NORMAL_OPERATION = "NORMAL_OPERATION"    # SavdoOS haqiqat manbai (Phase 2)


class RowClass(str, Enum):
    NEW = "NEW"
    UNCHANGED = "UNCHANGED"
    UPDATE_NAME = "UPDATE_NAME"
    UPDATE_PRICE = "UPDATE_PRICE"
    UPDATE_STOCK = "UPDATE_STOCK"
    UPDATE_BARCODES = "UPDATE_BARCODES"
    UPDATE_UNIT = "UPDATE_UNIT"
    UPDATE_MULTIPLE = "UPDATE_MULTIPLE"
    AMBIGUOUS = "AMBIGUOUS"
    DELETED_MATCH = "DELETED_MATCH"
    INVALID = "INVALID"
    MISSING_FROM_SOURCE = "MISSING_FROM_SOURCE"


class DeletedMatchAction(str, Enum):
    """O'chirilgan mahsulotga mos kelganda operator TANLAYDI. Standart — hech narsa."""
    REACTIVATE_EXISTING = "REACTIVATE_EXISTING"
    KEEP_DELETED = "KEEP_DELETED"


class ImportRowV2(BaseModel):
    """Bitta manba qatori. Chegaralar `ProductCreate` bilan IZCHIL."""
    external_id: str | None = Field(default=None, max_length=120)
    name: str = Field(min_length=1, max_length=300)
    article: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, max_length=16)      # 'dona'|'kg'|'litr'|'upak'
    buy_price: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    sell_price: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    stock: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    barcodes: list[str] = Field(default_factory=list, max_length=64)
    is_weighted: bool = False
    plu_code: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, max_length=200)
    source_updated_at: datetime | None = None

    @field_validator("barcodes")
    @classmethod
    def _dedupe(cls, v):
        # Bir qatorда bir xil barkod ikki marta — manba nuqsoni, jimgina tashlanadi.
        seen, out = set(), []
        for b in v:
            s = str(b).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out


class ImportBodyV2(BaseModel):
    mode: ImportMode
    source_system: str = Field(default="1c", max_length=32)
    snapshot_id: str | None = Field(default=None, max_length=120)   # manba eksport belgisi
    file_name: str | None = Field(default=None, max_length=260)
    rows: list[ImportRowV2] = Field(max_length=20000)               # massiv-DoS oldini olish
    # Qaysi o'chirilgan moslik bilan nima qilish — FAQAT commit'da, aniq ko'rsatilganda.
    deleted_match_actions: dict[str, DeletedMatchAction] = Field(default_factory=dict)
    job_id: uuid.UUID | None = None     # mavjud quruq yurish ishini commit qilish uchun

    @field_validator("rows")
    @classmethod
    def _not_empty(cls, v):
        if not v:
            raise ValueError("kamida bitta qator kerak")
        return v


class ChangeOut(BaseModel):
    field: str
    old: str | None = None
    new: str | None = None


class PreviewRowOut(BaseModel):
    row_no: int
    classification: RowClass
    name: str
    external_id: str | None = None
    product_id: uuid.UUID | None = None
    match_level: str | None = None
    changes: list[ChangeOut] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    problem: list[str] = Field(default_factory=list)


class PreviewOut(BaseModel):
    job_id: uuid.UUID
    mode: ImportMode
    source_system: str
    total: int
    counts: dict[str, int]
    rows: list[PreviewRowOut]
    missing_from_source: list[str] = Field(default_factory=list)
    # Preview HECH NARSA yozmaydi — bu maydon shuni ochiq e'lon qiladi.
    wrote_nothing: bool = True
