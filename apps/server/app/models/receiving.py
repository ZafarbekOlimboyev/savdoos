import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, FullMixin, PKMixin
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


class ReceivingCorrection(Base, PKMixin):
    """QABUL HUJJATINI TUZATISH HODISASI (Phase 5D) — sarlavha + idempotentlik BITTA qatorda.

    ⚠️  NEGA ALOHIDA HODISA, NEGA HUJJAT TAHRIRI EMAS. `StockBatch.received_qty`
        butun repoda hech qachon qayta yozilmaydi va `Receiving.final_items` —
        qabul LAHZASINING surati. Kelgan miqdorni yoki tannarxni JOYIDA
        tuzatish ikkalasini ham YOLG'ON qilardi: sotilib ketgan tovarning COGS
        surati (`sale_item_lot_allocations.unit_cost`) o'sha eski narxda
        muzlagan. Shu bois tuzatish — TESKARI YOZUV + O'RNIGA QO'YISH, va
        uning o'zi alohida, o'zgarmas hodisa (`services/lot_correction.py`,
        `services/RECEIVING_CORRECTION.md`).

    ⚠️  IDEMPOTENTLIK BAZA DARAJASIDA. `ux_recv_corr_client (company_id,
        client_uuid)` — takror so'rovga qarshi YAGONA tranzaksion kafolat
        (`lot_shortfall_resolution_requests` bilan AYNI naqsh: SELECT-dedup
        klassik TOCTOU va ikki bir vaqtdagi takror qoldiqni IKKI marta
        siljitardi). `request_hash` — so'rov MAZMUNI: ayni `client_uuid` bilan
        BOSHQA mazmun kelsa bu takror EMAS, mijoz xatosi (409).
        `response_json` — birinchi javob; takrorda AYNAN o'zi qaytariladi.

    ⚠️  QATOR YARATILGACH O'ZGARMAYDI va HECH QACHON o'chirilmaydi (`response_json`
        AYNI tranzaksiyada to'ldiriladi). Shu bois `deleted_at` YO'Q va noyob
        indeks QISMAN emas — `deleted_at IS NULL` sharti idempotentlik kalitiga
        «o'chirib qayta yuborish» teshigini ochardi.
    """
    __tablename__ = "receiving_corrections"
    __table_args__ = (
        Index("ux_recv_corr_client", "company_id", "client_uuid", unique=True),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    receiving_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receivings.id"), nullable=False)
    # Hujjat surati: tuzatish AYNAN shu xarid hujjatining summalarini siljitgan.
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchases.id"), nullable=True)
    # ⚠️  HAR DOIM `purchase.branch_id`, hech qachon `actor_branch`: partiyalar va
    #     qoldiq AYNAN hujjat filialida yashaydi. Xodim filialini yozish ko'p
    #     filialli do'konda tuzatishni BOSHQA filial qoldig'iga urardi.
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)      # 3..300, operator matni
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Σ teskari qilingan miqdor × ASL partiya tannarxi (yaxlitlangan o'rtachadan emas).
    reversed_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    # Σ o'rniga qo'yilgan miqdor × TUZATILGAN tannarx.
    replaced_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    # replaced_total − reversed_total (ISHORALI): hujjat jamiga shu qo'shiladi.
    delta_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # audit surati
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
