"""Global, non-secret receiving AI policy. Never inferred from worker env."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiRequirement(Base):
    __tablename__ = "ai_requirement"
    __table_args__ = (
        CheckConstraint("id = 1", name="ai_requirement_singleton"),
        CheckConstraint("revision > 0 AND protocol_version > 0 AND disclosure_version > 0",
                        name="ai_requirement_versions"),
        CheckConstraint("mode IN ('active', 'paused', 'demo')", name="ai_requirement_mode"),
        CheckConstraint("(mode = 'active' AND provider IN ('gemini', 'anthropic') "
                        "AND provider IS NOT NULL AND model IS NOT NULL AND length(model) > 0) "
                        "OR (mode IN ('paused', 'demo') AND provider IS NULL AND model IS NULL)",
                        name="ai_requirement_target"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(10))
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    disclosure_version: Mapped[int] = mapped_column(Integer)
    disclosure_id: Mapped[str] = mapped_column(String(100))
    protocol_version: Mapped[int] = mapped_column(Integer)
    dispatch_id: Mapped[str] = mapped_column(String(100))
    activated_by: Mapped[str] = mapped_column(String(100))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
