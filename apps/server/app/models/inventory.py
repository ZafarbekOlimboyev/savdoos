import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String,
                        UniqueConstraint)
from sqlalchemy import Enum as SAEnum
from app.db.types import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin
from app.models.enums import MovementType


class Inventory(Base, PKMixin):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("product_id", "branch_id"),)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    reserved_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    min_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    max_qty: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    # Kam-qoldiq push allaqachon yuborilganmi (dedup: min ostiga tushganda 1 marta, restokda 0)
    low_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(default=1)


class StockBatch(Base, PKMixin):
    """PARTIYA — bitta qabul kogortasining jismoniy qoldig'i.

    ⚠️  MIQDOR INVARIANTI. Kuzatuvli (`products.track_lots`) mahsulot uchun:

            Inventory.qty == SUM(remaining_qty)  [status='open', ayni company+branch+product]

        Ikkalasi DOIM ayni tranzaksiyada o'zgaradi. Buzilsa — jimgina tuzatilmaydi
        va taxmin qilinmaydi: partiyaga oid amal FAIL-CLOSED to'xtaydi
        (`app/services/stock_invariant.py`).

    ⚠️  IDENTIFIKATSIYA — QABUL KOGORTASI, atributlar EMAS. Bir xil `batch_no` +
        `expiry_date` + `unit_cost` bilan kelgan IKKINCHI yetkazib berish ALOHIDA
        partiya bo'ladi: ularning provenansi va `received_at` i har xil. Faqat AYNI
        qabul amalining takroriy urinishi (`client_uuid`) ayni partiyani qayta
        ishlatadi.
    """
    __tablename__ = "stock_batches"
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    batch_no: Mapped[str | None] = mapped_column(String, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # ── MIQDOR SEMANTIKASI ───────────────────────────────────────────────
    #
    #  received_qty  — DASTLABKI qabul miqdori. Yaratilgandan keyin
    #                  O'ZGARMAYDI. U "bu partiyaga qancha kirgan" degan savolga
    #                  javob beradi va provenansning bir qismi.
    #  remaining_qty — SHU LAHZADAGI jismoniy miqdor. Faqat shu kamayadi/ortadi.
    #
    #  `remaining_qty` ni ORTTIRADIGAN amallar va ularning `received_qty` ga
    #  ta'siri:
    #
    #    qabul (yaratilish)      received = remaining = kirgan miqdor   [o'rnatiladi]
    #    mijoz qaytarishi        remaining += qty                       [o'zgarmaydi]
    #    kirim bekor qilish      remaining -= qty                       [o'zgarmaydi]
    #    filialga ko'chirish     YANGI partiya yaratiladi               [manba tegilmaydi]
    #    musbat inventarizatsiya hali ANIQLANMAGAN (Phase 4)            [—]
    #
    #  ⚠️  TUZATISH. Ilgari "qaytarish `remaining_qty` ni `received_qty` dan
    #      oshirishi mumkin" deb yozgan edim — bu NOTO'G'RI. Chek asosidagi
    #      qaytarish AYNI partiyadan ketgan miqdorni qaytaradi, ya'ni u eng ko'pi
    #      bilan dastlabki miqdorgacha tiklanadi. Bugungi va Phase 1-3 amallari
    #      uchun `remaining_qty <= received_qty` HAQIQAT.
    #
    #      Cheklov SHUNGA QARAMAY qo'yilmaydi: partiya-darajasidagi musbat
    #      inventarizatsiya (Phase 4) semantikasi hali hal qilinmagan. Agar
    #      sanoq partiyada kutilganidan KO'P topsa, to'g'ri javob mavjud
    #      partiyani shishirish emas, alohida tuzatish partiyasi yaratish
    #      bo'lishi mumkin. Qaror qabul qilinmaguncha cheklov qo'yilsa, uni
    #      keyin OLIB TASHLASH kerak bo'lardi.
    #
    #  `qty` — ESKI nom, hech qachon yozilmagan (production'da 0 qator).
    #  Moslik uchun qoladi va `remaining_qty` bilan birga yoziladi.
    qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    received_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    remaining_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # open | depleted | written_off — FEFO faqat `open` dan tanlaydi
    status: Mapped[str] = mapped_column(String, default="open")
    # purchase | receiving | return | count | legacy | shortfall
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # KANONIK bog'lanish: bir xarid/qabul qatori -> KO'P partiya (bir qatorda
    # ayni tovar har xil muddat bilan kelishi mumkin). Teskari tomondagi
    # `purchase_items.batch_id` ESKIRGAN va yozilmaydi.
    purchase_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_items.id"), nullable=True
    )
    # ⚠️  BITTA JISMONIY QABUL — BITTA zaxira o'sishi. Xarid yaratish
    #     (`POST /purchases`) va qabul tasdiqlash (`POST /receiving/commit`) —
    #     IKKI YO'L, lekin bir yuk ular orqali IKKI MARTA o'tmasligi kerak.
    #     `receiving_id` qaysi qabul hujjati partiyani tug'dirganini yozadi;
    #     xarid orqali kelgan partiyada u NULL bo'ladi. Idempotentlikni esa
    #     `client_uuid` ta'minlaydi — u ikkala yo'lda ham BITTA kalit.
    receiving_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_lot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True
    )
    # QABUL IDEMPOTENTLIGI — takroriy yetkazib berish ikkinchi partiya YARATMAYDI
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)


class SaleItemLotAllocation(Base, PKMixin):
    """Sotuv qatorining QAYSI partiyalardan yeganini yozadi.

    ⚠️  NEGA ALOHIDA JADVAL. Bitta sotuv qatori bir nechta partiyani yeyishi mumkin,
        `stock_movements` esa buni yoza olmaydi: `ux_stockmov_client_prod_type`
        (client_uuid, product_id, type) BITTA amal uchun (mahsulot, tur) bo'yicha
        ATIGI BITTA harakat qatoriga ruxsat beradi. Shu bois harakat AGREGAT
        bo'lib qoladi (-120), partiya tafsiloti esa shu yerda yashaydi.

        SUM(allocation.qty) == sale_item.qty   (kuzatuvli sotuv uchun)

    `unit_cost` — O'SHA partiyaning narxi, O'ZGARMAS surat. `SaleItem.unit_cost`
    esa shularning og'irlangan o'rtachasi; hisobotlar bugungidek undan o'qiydi.
    """
    __tablename__ = "sale_item_lot_allocations"
    __table_args__ = (UniqueConstraint("sale_item_id", "stock_batch_id"),)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    sale_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id", ondelete="CASCADE")
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)   # surat
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LotShortfall(Base, PKMixin):
    """TAQSIMLANMAGAN QARZ — tovar ketgan, lekin qaysi partiyadan ekani NOMA'LUM.

    ⚠️  NEGA ALOHIDA JADVAL, NEGA MANFIY PARTIYA EMAS. Phase 2 da bu qarz
        `stock_batches` ga MANFIY `remaining_qty` bilan yozilardi. Lekin
        `StockBatch` ning o'z ta'rifi — JISMONIY qabul kogortasi (yuqoridagi
        docstring), manfiy miqdor esa jismoniy tovar EMAS. Bir jadvalda ikki xil
        ma'noli qator saqlash keyinchalik har bir o'quvchini («bu partiya
        javonda turibdimi?») noto'g'ri javobga olib borardi: muddat hisoboti,
        inventarizatsiya, ko'chirish, EXACT_LOT — hammasi uni tovar deb o'qirdi.

        Endi JISMONIY partiya HAR DOIM `remaining_qty >= 0`, qarz esa shu yerda.

    ⚠️  INVARIANT ENDI IKKI HADLI (`stock_invariant.py`):

            Inventory.qty == SUM(partiya remaining_qty) - SUM(yopilmagan qarz)

        Bu SODDALIKNI YO'QOTADI va buni ochiq aytish kerak: endi `SUM(
        remaining_qty)` ni YOLG'IZ o'qigan har qanday kod NOTO'G'RI javob oladi.
        Shu bois yagona to'g'ri o'quvchi — `stock_invariant.check()`, va qolgan
        joylar undan foydalanishi shart.

    `sale_item_id` — qarzni tug'dirgan chek qatori (izlanish uchun). Eski
    manfiy partiyalardan KO'CHIRILGAN qatorlarda u NULL bo'ladi: o'sha qarz
    aggregat edi va qaysi chekdan kelganini tiklab bo'lmaydi — buni o'ylab
    topish emas, NULL qoldirish halolroq.
    """
    __tablename__ = "lot_shortfalls"
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id", ondelete="CASCADE"), nullable=True)
    qty: Mapped[float] = mapped_column(Numeric(14, 3))          # MUSBAT qarz
    resolved_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class StockMovement(Base, PKMixin):
    """Immutable fakt-ledger: har zaxira harakati."""
    __tablename__ = "stock_movements"
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id"), nullable=True
    )
    type: Mapped[MovementType] = mapped_column(SAEnum(MovementType, name="movement_type"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    balance_after: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String, nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
