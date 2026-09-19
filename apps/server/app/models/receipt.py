"""Chek logosi va chop etish hodisalari (Phase 5F).

⚠️  FAQAT BITTA FK — `companies`. Boot'da `create_all` har FK uchun ota jadvalga
    SHARE ROW EXCLUSIVE qulf oladi: ota jadvaldagi bitta ochiq yozuvchi tranzaksiya
    (sotuv, kirim) yangi jadval yaratilishini — ya'ni butun boot'ni — ushlab turardi
    (`BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §1.3–1.4). `branch_id`, `doc_id`,
    `created_by` — FK'siz, xizmat qatlamida tekshiriladi. `companies` FK'si esa
    ATAYLAB qoladi: `tools/tenant_purge` egalikni shu FK'dan topadi.
⚠️  CHECK YO'Q. Holat/nusxa qiymatlari API'da tekshiriladi; CHECK qo'shilsa
    `required_schema.CHECK_DEFINITIONS` + PG renderlari talab qilinardi.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UUID


class ReceiptLogo(Base):
    """Chek logosi — yuklashda BIR MARTA qayta ishlanadi va natija shu qatorda keshlanadi.

    ⚠️  `original` HECH QACHON QAYTARILMAYDI. Mijozga faqat rastrdan QAYTA KODLANGAN
        1-bit PNG va rastrning o'zi beriladi: yuklangan faylning metama'lumoti
        (EXIF, GPS), polyglot dumi (PNG + HTML) yoki boshqa yuki tashqariga chiqmaydi.
        `deferred` — oddiy o'qishda 2 MB'gacha bayt bazadan umuman olinmaydi.
    ⚠️  `id` DETERMINISTIK (uuid5: kompaniya + filial + sha256) — ayni faylni ikki
        marta yuklash IKKINCHI qator yaratmaydi (PK to'qnashuvi = takror).
    ⚠️  O'ZGARMAS. O'chirish endpointi yo'q: logo sozlamadan `logo_id: null` bilan
        uziladi, eski chek nusxasi esa hamon o'z logosiga ishora qila oladi.
    """
    __tablename__ = "receipt_logos"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(20), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    original: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    # Qadoqlangan 1-bit rastr: qatorma-qator, MSB birinchi, 1 = QORA, kenglik 8 ga karrali.
    raster58: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    raster58_w: Mapped[int] = mapped_column(Integer, nullable=False)
    raster58_h: Mapped[int] = mapped_column(Integer, nullable=False)
    raster80: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    raster80_w: Mapped[int] = mapped_column(Integer, nullable=False)
    raster80_h: Mapped[int] = mapped_column(Integer, nullable=False)
    png58: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    png80: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Qisman shart ikki dialektda AYNI matn (`initdb._ensure_indexes` dagi DDL bilan ham).
_ORIGINAL_ONLY = text("copy = 'ORIGINAL'")


class PrintJob(Base):
    """Bitta chop etish URINISHI zanjiri (asl chek yoki nusxa) — FAQAT hodisa jurnali.

    ⚠️  PUL/QOLDIQQA TEGMAYDI. Chop etish sotuv tranzaksiyasidan KEYIN, alohida
        so'rovda yoziladi; printer xatosi sotuvni hech qachon bekor qilmaydi.
    ⚠️  `id` — MIJOZ uuid'i: POS offline ham chop etadi va hisobotni keyin yuboradi,
        ayni `id` qayta kelsa bu takror (holat o'tishi), yangi qator EMAS.
    ⚠️  `ux_print_jobs_original` — hujjatga BITTA asl chek. Ikkinchi kassa/oyna
        ayni chekni «asl» deb chop etsa, u NUSXA bo'lishi shart (409).
    """
    __tablename__ = "print_jobs"
    __table_args__ = (
        Index("ux_print_jobs_original", "company_id", "doc_type", "doc_id", unique=True,
              postgresql_where=_ORIGINAL_ONLY, sqlite_where=_ORIGINAL_ONLY),
        Index("ix_print_jobs_doc", "company_id", "doc_type", "doc_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)      # SALE | RETURN
    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    copy: Mapped[str] = mapped_column(String(16), nullable=False)          # ORIGINAL | REPRINT
    # ORIGINAL = 0; REPRINT = hujjatning shu nusxagacha (o'zi ham) nechta nusxasi bor.
    copy_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)    # PENDING|PRINTED|FAILED
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    printer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
