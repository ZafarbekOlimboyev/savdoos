import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
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
    refresh_hash: Mapped[str] = mapped_column(String)
    issued_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
