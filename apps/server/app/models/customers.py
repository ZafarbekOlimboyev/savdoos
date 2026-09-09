import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, ForeignKeyConstraint,
                        Numeric, String, Text, UniqueConstraint)
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, FullMixin, PKMixin
from app.models.enums import CreditTxnType


class CustomerGroup(Base, FullMixin):
    """Mijoz segmenti / sadoqat darajasi — HAR DO'KONNING O'ZINIKI.

    NEGA TENANT'GA TEGISHLI: `discount_pct` — do'konning O'Z narx siyosati
    ("ulgurji mijozga 10%"). Ikki do'kon bitta chegirma jadvalini ULASHISHI
    mantiqan noto'g'ri. Sxemaning o'z izohi ham shuni aytadi: "segment / sadoqat
    darajasi" (db/schema.sql).

    TARIX: jadval dastlabki sxemada e'lon qilingan, LEKIN hech qachon yakunlanmagan —
    na CRUD, na UI, na seed, na birorta `CustomerGroup(...)` chaqiruvi bo'lgan. Hech
    kim qator yaratmagani uchun `company_id` yo'qligi ko'rinmas nuqson bo'lib qolgan.
    Do'konlar 0 bo'lgan paytda tuzatildi (backfill talab qilinmadi).

    CROSS-TENANT HIMOYASI: `UNIQUE (company_id, id)` — bu `customers` dagi KOMPOZIT
    FK uchun nishon. Oddiy FK `customers.group_id` ni BOSHQA do'kon guruhiga
    ko'rsatishga ruxsat berardi; kompozit FK buni BAZA DARAJASIDA imkonsiz qiladi
    (aynan `cash` sxemasidagi `(tenant_id, id)` naqshi)."""

    __tablename__ = "customer_groups"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_cgroup_company_name"),
        UniqueConstraint("company_id", "id", name="uq_cgroup_company_id"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String)
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)


class Customer(Base, FullMixin):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        # CROSS-TENANT BOG'LANISH IMKONSIZ: guruh SHU do'konniki bo'lishi SHART.
        # MATCH SIMPLE semantikasi: `group_id` NULL bo'lsa tekshiruv o'tkazib
        # yuboriladi, ya'ni "guruhsiz mijoz" o'z-o'zidan yaroqli holat.
        ForeignKeyConstraint(
            ["company_id", "group_id"],
            ["customer_groups.company_id", "customer_groups.id"],
            name="fk_customers_group_same_company",
        ),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String)                 # M-1001
    full_name: Mapped[str] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # DIQQAT: guruh bog'lami KOMPOZIT FK bilan himoyalangan (quyidagi __table_args__).
    # Bu yerda ustunning O'ZIDA FK YO'Q — aks holda ikkita FK bo'lib, oddiysi
    # cross-tenant bog'lanishga yo'l ochib qolardi.
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    credit_balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    credit_limit: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    loyalty_points: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CreditTransaction(Base, PKMixin):
    """Qarz daftari — mijoz balansining asl manbai."""
    __tablename__ = "credit_transactions"
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    type: Mapped[CreditTxnType] = mapped_column(SAEnum(CreditTxnType, name="credit_txn_type"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    balance_after: Mapped[float] = mapped_column(Numeric(14, 2))
    sale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_payments.id"), nullable=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerPayment(Base, PKMixin):
    __tablename__ = "customer_payments"
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    method: Mapped[str] = mapped_column(String, default="cash")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # §2 audit identity: naqd qaysi FIZIK hisobga tushgani (TILL yoki SAFE). Additive+nullable.
    cash_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoyaltyTransaction(Base, PKMixin):
    __tablename__ = "loyalty_transactions"
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    points: Mapped[float] = mapped_column(Numeric(14, 2))
    sale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
