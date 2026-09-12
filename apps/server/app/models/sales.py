import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, FullMixin, PKMixin
from app.models.enums import ReturnReason, SaleStatus


class Sale(Base, FullMixin):
    """Chek — append-only."""
    __tablename__ = "sales"
    __table_args__ = (UniqueConstraint("company_id", "receipt_no"),)
    receipt_no: Mapped[str] = mapped_column(String)
    uid: Mapped[str | None] = mapped_column(String, nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    cashier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=True
    )
    # FIZIK cash drawer identity — cash.cash_accounts(type=TILL).id. Cross-schema (cash schema Postgres-only,
    # SQLite kassada YO'Q) -> DB FK YO'Q, service-validated (same tenant+branch, type TILL, ACTIVE). Audit
    # avtoritetи: qaysi FIZIK kassa/yashik. NULL = noma'lum (cash-disabled/unresolved) — HECH QACHON taxmin emas.
    till_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    status: Mapped[SaleStatus] = mapped_column(
        SAEnum(SaleStatus, name="sale_status"), default=SaleStatus.completed
    )
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2))
    discount_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tax_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(14, 2))
    cost_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_offline: Mapped[bool] = mapped_column(Boolean, default=False)
    # Sale-time SNAPSHOT'lar (audit/receipt immutability) — ID'lar avtoritet, bular FAQAT tarixiy
    # ko'rsatish uchun (kassir/TILL/terminal/filial keyinchalik rename/delete bo'lса ham chek o'zgarmaydi).
    cashier_name_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    branch_name_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    till_code_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    till_label_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    terminal_name_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    items: Mapped[list["SaleItem"]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    payments: Mapped[list["SalePayment"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class SaleItem(Base, PKMixin):
    """Chek qatori — narx va tannarx snapshot qilinadi."""
    __tablename__ = "sale_items"
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id", ondelete="CASCADE")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    name_snapshot: Mapped[str] = mapped_column(String)
    article_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    # ⚠️  KO'RSATISH uchun: og'irlangan o'rtacha, 2 xonaga YAXLITLANGAN. Ko'p
    #     partiyali sotuvda bu BUXGALTERIYA HAQIQATI EMAS — `cost_total` ga qarang.
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # ANIQ qator COGS'i = SUM(ulush.qty × ulush.unit_cost). `qty × unit_cost` dan
    # FARQ qiladi (100×55 + 20×57 = 6640.00, lekin 120 × 55.33 = 6639.60).
    # Tarixiy qatorlarda NULL — hisobotlar `COALESCE` bilan ortga mos o'qiydi.
    cost_total: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # ⚠️  `cost_total` ning TAXMINIY ulushi. Offline chek qayta yuborilganda
    #     yaroqli partiya yetmasa, ketgan tovarning HAQIQIY tannarxi NOMA'LUM
    #     (u qaysi partiyadan ekani aniqlanmagan) — o'sha qismga mahsulotning
    #     joriy olish narxi qo'yiladi. Bu TAXMIN va shunday belgilanadi:
    #
    #         ANIQ COGS      = cost_total - cost_unresolved
    #         TAXMINIY ulush = cost_unresolved   (qarz yopilguncha)
    #
    #     Butun qatorni «aniq» deb atash YOLG'ON bo'lardi.
    cost_unresolved: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    discount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    tax_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id"), nullable=True
    )


class SalePayment(Base, PKMixin):
    __tablename__ = "sale_payments"
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id", ondelete="CASCADE")
    )
    method_code: Mapped[str] = mapped_column(String)          # cash|card|qr|credit
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    given_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    change_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    txn_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SaleDiscount(Base, PKMixin):
    __tablename__ = "sale_discounts"
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id", ondelete="CASCADE")
    )
    sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Numeric(14, 2))
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class Return(Base, FullMixin):
    __tablename__ = "returns"
    __table_args__ = (UniqueConstraint("company_id", "return_no"),)
    return_no: Mapped[str] = mapped_column(String)
    original_sale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    cashier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"))
    # Qaytarishni bajarган smena/TILL (asl savdoникидан FARQ qilishi mumkin — refund ertasi kuni boshqa
    # kassада bo'lиши mumkin). Ledger OUT SHU refund TILL'дан yoziladi; asl sale identity o'zgармайди.
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=True
    )
    till_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # refund fizik TILL (FK yo'q, cross-schema)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    reason: Mapped[ReturnReason] = mapped_column(
        SAEnum(ReturnReason, name="return_reason"), default=ReturnReason.customer
    )
    restock: Mapped[bool] = mapped_column(Boolean, default=True)   # omborga qaytdi / hisobdan chiqarildi
    refund_method: Mapped[str] = mapped_column(String, default="cash")
    total: Mapped[float] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    items: Mapped[list["ReturnItem"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class ReturnItem(Base, PKMixin):
    __tablename__ = "return_items"
    return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("returns.id", ondelete="CASCADE")
    )
    sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # ⚠️  ANIQ QAYTARILGAN TANNARX. `unit_cost` — o'rtacha, ya'ni YAXLITLANGAN.
    #     Hisobotlar bugungacha qaytarilgan COGS'ni `qty * unit_cost` deb QAYTA
    #     hisoblardi (8 joyda). Bitta partiyali qaytarishda bu to'g'ri, lekin
    #     qaytarish IKKI partiyaga bo'linsa (turli `unit_cost`) o'rtachani qayta
    #     ko'paytirish tiyinlarni yo'qotadi — sotuvda AYNAN shu xato o'lchangan
    #     edi (6640.00 o'rniga 6639.60, `sale_items.cost_total` shuning uchun
    #     qo'shilgan). Shu bois qatorlar yig'indisi SHU YERDA aynan saqlanadi.
    #
    #     NULL = eski qator: hisobot `qty * unit_cost` ga qaytadi (coalesce).
    cost_total: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # ⚠️  TAXMINIY ULUSH — `SaleItem.cost_unresolved` ning AYNASI.
    #
    #     Offline chekda partiyaga bog'lanmagan miqdor bo'lsa, sotuv uning
    #     tannarxini TAXMIN qiladi va uni `SaleItem.cost_unresolved` da alohida
    #     saqlaydi. Agar qaytarish FAQAT partiyaga bog'langan ulushni qaytarsa,
    #     100% qaytarilgan chekda ham taxminiy ulush COGS'da ABADIY qolib
    #     ketardi: daromad 0, tannarx esa musbat — ya'ni bo'lmagan savdodan
    #     doimiy zarar. Shu bois qaytarish ham IKKI HADLI:
    #
    #         cost_total = Σ(qty × partiya narxi) + cost_unresolved
    #
    #     Taxminiy had qarz qatoridagi MUZLATILGAN `unit_cost` dan olinadi —
    #     bugungi `base_buy_price` dan EMAS (u kirimda o'zgargan bo'lishi mumkin).
    cost_unresolved: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2))
