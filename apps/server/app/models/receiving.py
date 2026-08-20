import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, FullMixin
from app.db.types import JSONB, UUID


class Receiving(Base, FullMixin):
    """Mobil ilova orqali nakladnoy skani → omborga kirim. Audit uchun to'liq iz saqlanadi:
    original rasm, AI o'qigan dastlabki natija, foydalanuvchi tahrirlagan yakuniy natija."""
    __tablename__ = "receivings"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"))
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchases.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String, default="ai")     # ai | demo | manual
    image_b64: Mapped[str | None] = mapped_column(Text, nullable=True)   # original rasm (audit)
    ai_raw: Mapped[list] = mapped_column(JSONB, default=list)     # AI o'qigan dastlabki qatorlar
    final_items: Mapped[list] = mapped_column(JSONB, default=list)  # tasdiqlangan yakuniy qatorlar
    total_types: Mapped[int] = mapped_column(Integer, default=0)
    total_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
