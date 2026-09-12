import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String,
                        UniqueConstraint)
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
    """PARTIYA — bitta qabul kogortasining jismoniy qoldig'i.

    ⚠️  MIQDOR INVARIANTI. Kuzatuvli (`products.track_lots`) mahsulot uchun:

            Inventory.qty == SUM(remaining_qty)  [status='open', ayni company+branch+product]

        Ikkalasi DOIM ayni tranzaksiyada o'zgaradi. Buzilsa — jimgina tuzatilmaydi
        va taxmin qilinmaydi: partiyaga oid amal FAIL-CLOSED to'xtaydi
        (`app/services/stock_invariant.py`).

    ⚠️  IDENTIFIKATSIYA — QABUL KOGORTASI, atributlar EMAS. Bir xil `batch_no` +
        `expiry_date` + `unit_cost` bilan kelgan IKKINCHI yetkazib berish ALOHIDA
        partiya bo'ladi: ularning provenansi va `received_at` i har xil. Faqat AYNI
        qabul amalining takroriy urinishi (`client_uuid`) ayni partiyani qayta
        ishlatadi.
    """
    __tablename__ = "stock_batches"
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    batch_no: Mapped[str | None] = mapped_column(String, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # `qty` ESKI nom — hech qachon yozilmagan (production'da 0 qator). Yangi kod
    # `remaining_qty` bilan ishlaydi; `qty` ustuni MOSLIK uchun qoladi va
    # `remaining_qty` bilan birga yoziladi, toki eski o'quvchi qolmaguncha.
    qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    received_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    remaining_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # open | depleted | written_off — FEFO faqat `open` dan tanlaydi
    status: Mapped[str] = mapped_column(String, default="open")
    # purchase | receiving | return | count | legacy | shortfall
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    purchase_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_items.id"), nullable=True
    )
    receiving_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_lot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True
    )
    # QABUL IDEMPOTENTLIGI — takroriy yetkazib berish ikkinchi partiya YARATMAYDI
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)


class SaleItemLotAllocation(Base, PKMixin):
    """Sotuv qatorining QAYSI partiyalardan yeganini yozadi.

    ⚠️  NEGA ALOHIDA JADVAL. Bitta sotuv qatori bir nechta partiyani yeyishi mumkin,
        `stock_movements` esa buni yoza olmaydi: `ux_stockmov_client_prod_type`
        (client_uuid, product_id, type) BITTA amal uchun (mahsulot, tur) bo'yicha
        ATIGI BITTA harakat qatoriga ruxsat beradi. Shu bois harakat AGREGAT
        bo'lib qoladi (-120), partiya tafsiloti esa shu yerda yashaydi.

        SUM(allocation.qty) == sale_item.qty   (kuzatuvli sotuv uchun)

    `unit_cost` — O'SHA partiyaning narxi, O'ZGARMAS surat. `SaleItem.unit_cost`
    esa shularning og'irlangan o'rtachasi; hisobotlar bugungidek undan o'qiydi.
    """
    __tablename__ = "sale_item_lot_allocations"
    __table_args__ = (UniqueConstraint("sale_item_id", "stock_batch_id"),)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    sale_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id", ondelete="CASCADE")
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)   # surat
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
