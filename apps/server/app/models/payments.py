import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


class QrPayment(Base, PKMixin):
    """XPAY QR to'lov holati — POS shu bo'yicha to'lov tasdiqlanganini kuzatadi."""
    __tablename__ = "qr_payments"
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    txn_id: Mapped[str] = mapped_column(String, unique=True, index=True)  # xpay qr_transaction_id
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    qr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="WAITING")  # WAITING|COMPLETED|CANCELED|ERROR
    # QA PAY-01: QR to'lov qaysi savdo tomonidan ISHLATILGANI — qayta ishlatish (bir QR ikki savdoga)
    # ni to'sadi; qr savdo yozilganda shu yerga sale.id yoziladi (consume).
    sale_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # QA PAY-05: checkout-idempotent QR — bir checkout (client_uuid) uchun bitta QR; modal qayta
    # ochilganda yangi orfan QR yaratilmaydi (mavjud WAITING qaytariladi).
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
