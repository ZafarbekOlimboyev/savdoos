import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from app.db.types import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin
from app.models.enums import ImportStatus


class ImportJob(Base, PKMixin):
    __tablename__ = "import_jobs"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    source: Mapped[str] = mapped_column(String)               # 1c|excel|csv
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[ImportStatus] = mapped_column(
        SAEnum(ImportStatus, name="import_status"), default=ImportStatus.uploaded
    )
    column_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    new_rows: Mapped[int] = mapped_column(Integer, default=0)
    existing_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ── SNAPSHOT IDENTIFIKATSIYASI (Phase 2 idempotentligi) ──────────────────
    # Operator ayni faylni ikki marta yuborsa, ikkinchi urinish YANGI import
    # boshlamasligi kerak. Kalit: (company_id, source, snapshot_id) — unga
    # `ux_import_jobs_snapshot` qisman NOYOB indeksi qo'yilgan (faqat
    # committing/committed holatlarida), ya'ni BITTA snapshot uchun BITTA
    # commit-yo'li DB darajasida kafolatlanadi (poyga ham to'xtatiladi).
    #
    # `content_sha256` — qatorlarning kanonik xesh'i. Ayni snapshot_id boshqa
    # xesh bilan kelsa, bu MANBA O'ZGARGAN degani va 409 bilan rad etiladi.
    snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    # Xesh QAYSI shartnoma bilan hisoblangani. NULL = 1 (shartnoma kiritilishidan
    # oldingi ishlar) — tarixiy xeshlar AYNAN o'sha qoida bilan hisoblangan, shu
    # bois NULL va 1 BIR XIL ma'noni bildiradi.
    #
    # ⚠️  KELAJAKDA `CANON_VERSION = 2` chiqsa, ESKI ish O'Z versiyasi bilan
    #     solishtirilishi SHART. Aks holda yangi deploy eski snapshot'ni qayta
    #     yuborilganда SOXTA `SNAPSHOT_CONFLICT` bergan bo'lardi.
    hash_contract_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_rows: Mapped[int] = mapped_column(Integer, default=0)


class ImportRow(Base, PKMixin):
    __tablename__ = "import_rows"
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_jobs.id", ondelete="CASCADE")
    )
    row_no: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSONB)
    parsed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, default="new")  # new|existing|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True
    )
