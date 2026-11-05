import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, FullMixin, PKMixin, TimestampMixin
from app.models.enums import EmployeeStatus


class Role(Base, PKMixin, TimestampMixin):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String, unique=True)   # administrator|menejer|omborchi|kassir
    name: Mapped[str] = mapped_column(String)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions", lazy="selectin"
    )


class Permission(Base, PKMixin):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String, unique=True)   # modul.harakat
    module: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class Employee(Base, FullMixin):
    __tablename__ = "employees"
    # ── OTA-KALIT (R-DDL) ────────────────────────────────────────────────────
    #  Kelgusi kompozit FK uchun NOMZOD KALIT:
    #      creditors (company_id, employee_id) -> employees (company_id, id)
    #  (A qarori: kreditor havolasi TENANT bilan birga majburlanadi.) Mavjud
    #  `ux_employees_phone_pw` va `ux_employees_client_uuid` — QISMAN indekslar, FK ota-kaliti
    #  bo'la OLMAYDI. `id` PK bo'lgani uchun (company_id, id) ta'rif bo'yicha noyob.
    __table_args__ = (
        Index("uq_employees_company_id", "company_id", "id", unique=True),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    full_name: Mapped[str] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"))
    pin_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[EmployeeStatus] = mapped_column(
        SAEnum(EmployeeStatus, name="employee_status"), default=EmployeeStatus.active
    )
    hired_at: Mapped[Date | None] = mapped_column(Date, nullable=True)
    # Token bekor qilish uchun "xavfsizlik davri": parol o'zgarganda / chiqishда oshiriladi.
    # Tokenda 'sv' claim'i shu songa teng bo'lmasa — token yaroqsiz (eski/o'g'irlangan token bekor bo'ladi).
    sec_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    role: Mapped["Role"] = relationship(lazy="joined")


class EmployeePermission(Base):
    __tablename__ = "employee_permissions"
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean)


class EmployeeBranch(Base):
    __tablename__ = "employee_branches"
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True
    )


class AuthSession(Base, PKMixin):
    __tablename__ = "auth_sessions"
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE")
    )
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terminals.id"), nullable=True
    )
    #  Refresh kredensiali DETERMINISTIK keyed-hash bilan saqlanadi (HMAC-SHA256,
    #  `core/security.hash_refresh`) — bcrypt EMAS. Sababi: rotation ATOMAR
    #  bo'lishi kerak (`UPDATE … WHERE refresh_hash = :old`), bcrypt'ning
    #  tasodifiy tuzi esa WHERE bilan mos kelishni imkonsiz qiladi. Bu PAROL
    #  emas, yuqori entropiyali tasodifiy token — keyed-hash to'g'ri vosita.
    refresh_hash: Mapped[str] = mapped_column(String)
    #  ISTE'MOL QILINGAN oldingi kredensialning XESHI (plaintext HECH QACHON
    #  saqlanmaydi). Ikki vazifasi bor:
    #    1) GRACE: `rotated_at` dan `refresh_grace_seconds` ichida kelgan
    #       parallel so'rov benign deb qabul qilinadi va QAYTA rotation oladi;
    #    2) REPLAY: o'sha oynadan KEYIN kelsa — iste'mol qilingan tokenning
    #       qayta ishlatilishi, sessiya REVOKE qilinadi (fail-closed).
    #  Ikkisiga ham mos kelmaydigan sir -> 401, lekin REVOKE QILINMAYDI: aks
    #  holda `sid` ni taxmin qilgan hujumchi begona sessiyalarni o'chira olardi.
    prev_refresh_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    rotated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
