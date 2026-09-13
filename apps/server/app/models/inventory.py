import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, Text, UniqueConstraint)
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
    #    musbat inventarizatsiya YANGI partiya (source_type='adjustment') [manba tegilmaydi]
    #
    #  ⚠️  TUZATISH. Ilgari "qaytarish `remaining_qty` ni `received_qty` dan
    #      oshirishi mumkin" deb yozgan edim — bu NOTO'G'RI. Chek asosidagi
    #      qaytarish AYNI partiyadan ketgan miqdorni qaytaradi, ya'ni u eng ko'pi
    #      bilan dastlabki miqdorgacha tiklanadi. Bugungi va Phase 1-3 amallari
    #      uchun `remaining_qty <= received_qty` HAQIQAT.
    #
    #      Phase 3 QARORI: sanoq partiyada kutilganidan KO'P topsa, mavjud
    #      partiya SHISHIRILMAYDI — `source_type='adjustment'` bilan ALOHIDA
    #      partiya yaratiladi. Sabab: ortiqcha topilgan tovarning qabul sanasi,
    #      muddati va tannarxi NOMA'LUM; uni begona kogortaga qo'shish o'sha
    #      kogortaning provenansini (va muddat hisobotini) YOLG'ON qilardi.
    #      Shu qaror tufayli `remaining_qty <= received_qty` HAR DOIM saqlanadi.
    #
    #      Cheklov SHUNGA QARAMAY DB darajasida qo'yilmaydi: mavjud jonli
    #      bazalarда tekshirilmagan qatorlar bo'lsa CHECK qo'shish migratsiyani
    #      TO'XTATARDI. Qoida kod darajasida va testlar bilan ushlanadi.
    #
    #  `qty` — ESKI nom, hech qachon yozilmagan (production'da 0 qator).
    #  Moslik uchun qoladi va `remaining_qty` bilan birga yoziladi.
    qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    received_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    remaining_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # ⚠️  FAQAT: open | depleted | void. Boshqa har qanday qiymat
    #     `stock_invariant.UnknownLotStatus` bilan FAIL-CLOSED to'xtatadi
    #     (`stock_invariant.KNOWN_STATUSES`) — bu ataylab shunday.
    #
    #     ILGARI BU YERDA `written_off` yozilgan edi va u YOLG'ON: hech bir kod
    #     uni yozmaydi, `stock_invariant` esa uni BILMAYDI. Hisobdan chiqarish
    #     (Phase 3) alohida holat YARATMAYDI — u `remaining_qty` ni kamaytiradi
    #     va nolga yetsa partiya `depleted` bo'ladi. «Nega nolga tushdi» degan
    #     savolga `stock_movements` (type=writeoff, reason=...) javob beradi;
    #     buni holatga ko'chirish invariantga yangi holat o'rgatishni talab
    #     qilardi va hech qanday yangi ma'lumot bermasdi.
    #
    #     FEFO faqat `open` dan tanlaydi (`lot_fefo.candidates`).
    status: Mapped[str] = mapped_column(String, default="open")
    # HAQIQATDA YOZILADIGAN qiymatlar (ro'yxat kod bilan TEKSHIRILADI):
    #   purchase   — xarid orqali (`lot_receiving.SOURCE_PURCHASE`)
    #   receiving  — qabul hujjati (`SOURCE_RECEIVING`)
    #   legacy     — kuzatuv yoqilganda mavjud qoldiqdan (`SOURCE_LEGACY`)
    #   opening    — `POST /lots/enable` ochilish partiyasi
    #   adjustment — inventarizatsiya ORTIQCHA topgan miqdor (Phase 3)
    #   return_unattributed — mijoz QAYTARGAN, lekin asl kogortasi NOMA'LUM
    #        miqdor (Phase 3.5). Faqat QARZ dumi qaytganda tug'iladi:
    #        sotuvda partiyaga bog'lanmagan tovar qaytsa, uni ixtiyoriy
    #        kogortaga yozish YOLG'ON bo'lardi. `expiry_date` NULL —
    #        NOMA'LUM, taxmin QILINMAYDI; narx qarz qatoridagi MUZLATILGAN
    #        taxmin (chek o'sha narxda hisoblangan edi).
    #   shortfall  — ESKIRGAN, faqat migratsiyada (`lot_fefo.LEGACY_SOURCE_SHORTFALL`)
    # ⚠️  `return` va `count` HECH QACHON yozilmagan — ilgari shu yerda sanab
    #     o'tilgan edi va o'quvchini «qaytarish yangi partiya yaratadi» degan
    #     NOTO'G'RI xulosaga olib borardi. Qaytarish ASL partiyaga qaytadi.
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


class ReturnItemLotAllocation(Base, PKMixin):
    """Qaytarish qatorining QAYSI partiyalarga qaytganini yozadi (Phase 3).

    ⚠️  NEGA KERAK — KUMULYATIV HIMOYA. Bitta chek bir necha marta, bo'lak-bo'lak
        qaytarilishi mumkin. Har qaytarish asl taqsimotni (`sale_item_lot_
        allocations`) «orqaga o'raydi», lekin ASL taqsimot O'ZGARMAYDI (u sotuv
        lahzasining surati). Demak «bu partiyaga qancha qaytarilgan edi?» degan
        savolga javob beradigan ALOHIDA yozuv kerak — usiz uchinchi qaytarish
        partiyaga sotilganidan KO'PROQ qaytarib, `remaining_qty` ni
        `received_qty` dan oshirib yuborardi.

            Σ(qaytarilgan[sale_item, partiya]) <= asl_taqsimot[sale_item, partiya].qty

    `unit_cost` — ASL sotuvdagi partiya narxi, o'zgarmas surat. Qaytarish
    tannarxi HAR DOIM shundan olinadi: na `base_buy_price`, na partiyaning
    BUGUNGI narxi, na oxirgi xarid narxi.
    """
    __tablename__ = "return_item_lot_allocations"
    # ⚠️  NOYOBLIK (qaytarish qatori, SOTUV QATORI, partiya) — Phase 4A tuzatishi.
    #     Ilgari (qaytarish qatori, partiya) edi: bitta chekda ayni mahsulot ikki
    #     qatorda AYNI partiyadan sotilgan bo'lsa, ularni bitta qaytarishda qaytarish
    #     ikki qator yozar va noyob kalitga urilib, 3 urinishdan keyin DOIMIY 409
    #     berardi. Kumulyativ chegara (`lot_return._returned_so_far`) baribir
    #     (sotuv qatori, partiya) bo'yicha — kalit shunga moslashtirildi.
    __table_args__ = (
        Index("ux_ret_alloc_line", "return_item_id", "sale_item_id", "stock_batch_id",
              unique=True),
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    return_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("return_items.id", ondelete="CASCADE")
    )
    # ASL sotuv qatori — kumulyativ chegara AYNAN shu juftlik bo'yicha o'lchanadi.
    sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=True
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))          # MUSBAT
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockMovementLotAllocation(Base, PKMixin):
    """OMBOR HARAKATINING qaysi partiyalarga tegganini yozadi (Phase 3).

    ⚠️  NEGA `StockMovement.batch_id` EMAS. U ustun modelda bor, lekin
        ATAYLAB yozilmaydi va Phase 1 da undan voz kechilgan: bitta harakat
        BIR NECHTA partiyaga tegishi mumkin, bitta `batch_id` esa faqat
        bittasini ko'rsatardi — ya'ni ko'p partiyali amalda u YOLG'ON yoki
        NULL bo'lardi. Bundan tashqari `ux_stockmov_client_prod_type`
        (client_uuid, product_id, type) bitta amal uchun ATIGI BITTA harakat
        qatoriga ruxsat beradi, shu bois harakat AGREGAT bo'lib qolishi SHART.

        SUM(allocation.qty) == ABS(stock_movement.qty)

    ⚠️  NEGA AUDIT JURNALI YETMAYDI. Yopish (`lot_shortfalls`) tajribasi shuni
        ko'rsatdi: JSON blob'iga yozilgan tafsilotni hech bir hisobot YIG'A
        olmaydi. «Muddat tufayli qancha yo'qotdik va qaysi kogortadan» degan
        savol aynan shu jadvalсиз javobsiz qolardi.

    `qty` — DOIM MUSBAT (harakat yo'nalishi `stock_movements.qty` da).
    `unit_cost` — O'SHA partiyaning narxi, o'zgarmas surat.
    """
    __tablename__ = "stock_movement_lot_allocations"
    __table_args__ = (UniqueConstraint("stock_movement_id", "stock_batch_id"),)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    stock_movement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_movements.id", ondelete="CASCADE")
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))          # MUSBAT
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
    # ⚠️  Ortiqcha yopish BAZA darajasida imkonsiz (Phase 4A). Invariant
    #     (`stock_invariant._shortfall_sums`) faqat MUSBAT ochiq qarzni yig'adi —
    #     ya'ni `resolved_qty > qty` bo'lib qolsa u JIMGINA nolga tushib, qoldiq
    #     farqini «invariant buzildi» degan tushunarsiz xatoga aylantirardi.
    __table_args__ = (
        CheckConstraint("resolved_qty <= qty", name="ck_lot_shortfall_resolved_le_qty"),
    )
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
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)   # TAXMINIY
    # ⚠️  HAQIQIY tannarxning YIG'INDISI — yopish paytida topilgan partiya
    #     narxi (Σ k × partiya.unit_cost). `unit_cost` esa sotuv lahzasidagi
    #     TAXMIN. Ikkisining farqi — COGS OG'ISHI:
    #
    #         og'ish = resolved_cost − resolved_qty × unit_cost
    #
    #     Bu og'ish tarixiy `SaleItem.cost_total` ni QAYTA YOZMAYDI (Phase 2.5
    #     qoidasi), lekin YO'QOLMAYDI ham: SQL bilan yig'ib olinadi. Ilgari u
    #     faqat `AuditLog` JSON'ida edi — hech bir hisobot uni yig'a olmasdi.
    resolved_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    # ⚠️  QARZ IKKI SABABGA KO'RA KAMAYADI VA ULAR ARALASHTIRILMAYDI:
    #
    #       resolved_qty — ATRIBUTSIYA topildi: tovar haqiqatan ketgan, lekin
    #                      endi qaysi partiyadan ekani ma'lum. Partiya ham
    #                      o'sha payt k ga kamayadi (qoldiq qimirlamaydi).
    #       returned_qty — TOVAR QAYTIB KELDI: u umuman ketmagan bo'lib chiqdi.
    #                      Qoldiq k ga OSHADI, birorta partiya tegilmaydi.
    #
    #     Ikkalasini bitta ustunga yig'ish COGS og'ishini BUZARDI: og'ish
    #     `resolved_cost − resolved_qty × unit_cost` bo'lib, qaytarish
    #     `resolved_qty` ni oshirса-yu `resolved_cost` ni oshirmasa (oshirishi
    #     ham mumkin emas — partiya topilmadi), yo'qdan og'ish paydo bo'lardi.
    #
    #     YOPILMAGAN QARZ = qty − resolved_qty − returned_qty
    returned_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


# ══ PHASE 4A — QARZ YOPISH HODISALARI (buxgalteriya jurnali) ═════════════════
#
# ⚠️  NEGA HODISA JADVALLARI. Phase 3 da yopish ikki narsani O'ZGARTIRARDI:
#     `lot_shortfalls` hisoblagichlari va `sale_item_lot_allocations` (sotuv
#     surati). Og'ish esa faqat `resolved_cost − resolved_qty × unit_cost`
#     ayirmasi edi — QACHON tan olingani, qaysi partiyadan, qisman yopishlar
#     orasida qanday taqsimlangani yo'qolardi, va sotuv surati jimgina qayta
#     yozilardi.
#
#     Endi har yopish QATORI o'zgarmas hodisa: miqdor, taxminiy va haqiqiy
#     summa, og'ish va tan olingan vaqt. Sotuv surati (`SaleItem`,
#     `sale_item_lot_allocations`) TEGILMAYDI. Hisobotlar og'ishni SHU yerdan
#     `resolved_at` davriga yig'adi.
#
# ⚠️  FK'LAR ATAYLAB `NO ACTION`. Dalilni o'chirish JIM `CASCADE` bilan emas,
#     BALAND ovozda yiqilishi kerak.

RESOLUTION_REAL = "real"          # tovar HAQIQIY partiyadan ketgan edi
RESOLUTION_NETTING = "netting"    # qaytib kelgan (U) tovar o'z qarziga netlandi
RESOLUTION_KINDS = (RESOLUTION_REAL, RESOLUTION_NETTING)


class LotShortfallResolutionRequest(Base, PKMixin):
    """Yopish SO'ROVI — idempotentlik sarlavhasi.

    ⚠️  NEGA ALOHIDA JADVAL. Phase 3 idempotentligi `AuditLog` JSON'ini
        skanerlardi: tranzaksion kafolati yo'q (ikki bir vaqtdagi takror ikkalasi
        ham «yo'q» deb o'qib, qarzni IKKI marta yopardi). `(company_id,
        client_uuid)` noyob indeksi buni BAZA darajasida imkonsiz qiladi.

    `request_hash` — so'rov MAZMUNI (qatorlar). Ayni `client_uuid` bilan BOSHQA
    mazmun kelsa — bu takror emas, mijoz xatosi (409).
    """
    __tablename__ = "lot_shortfall_resolution_requests"
    __table_args__ = (
        Index("ux_lsr_request_client", "company_id", "client_uuid", unique=True),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    shortfall_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lot_shortfalls.id"), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LotShortfallResolution(Base, PKMixin):
    """Bitta yopish QATORI — O'ZGARMAS buxgalteriya hodisasi.

        variance = actual_cost − provisional_cost      (CHECK bilan pinlangan)

    `provisional_cost` KUMULYATIV yaxlitlanadi (`lots.resolve_shortfall`):
    qarz to'liq yopilganda Σ provisional_cost == round2(p × qty) == sotuvdagi
    taxmin — ya'ni yopishlar yig'indisi chekdagi taxminni AYNAN teskari qiladi.
    """
    __tablename__ = "lot_shortfall_resolutions"
    __table_args__ = (
        Index("ux_lsr_request_lot", "request_id", "stock_batch_id", unique=True),
        CheckConstraint("qty > 0", name="ck_lsr_qty_pos"),
        # ⚠️  FAQAT POSTGRES'DA. SQLite NUMERIC'ni suzuvchi REAL sifatida saqlaydi:
        #     50.25 − 47.24 = 3.0100000000000016 ≠ 3.01, ya'ni aniq tenglik
        #     to'g'ri yozuvni ham RAD etardi. Postgres NUMERIC — aniq; tayyorlik va
        #     `_ensure_lot_checks` ham bu cheklovni faqat Postgres'da talab qiladi.
        CheckConstraint("variance = actual_cost - provisional_cost",
                        name="ck_lsr_variance_identity").ddl_if(dialect="postgresql"),
        CheckConstraint("kind IN ('real', 'netting')", name="ck_lsr_kind"),
        CheckConstraint("kind <> 'netting' OR variance = 0", name="ck_lsr_netting_zero"),
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lot_shortfall_resolution_requests.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    shortfall_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lot_shortfalls.id"), nullable=False)
    sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=True)
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id"), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)   # surat
    qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    provisional_unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    actual_unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    provisional_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    actual_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    variance: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReturnItemShortfallAllocation(Base, PKMixin):
    """Qarz DUMIning qaytishi — «k dona atributsiyasiz tovar qaytib keldi».

    Ilgari bu faqat `lot_shortfalls.returned_qty` hisoblagichi va audit JSON
    edi: qaysi qaytarish, qaysi U partiya — SQL bilan tiklab bo'lmasdi. Netlash
    (`kind='netting'`) aynan shu havola orqali «bu U partiya SHU qarzniki»
    ekanini isbotlaydi.
    """
    __tablename__ = "return_item_shortfall_allocations"
    __table_args__ = (
        Index("ux_risa_item_shortfall", "return_item_id", "shortfall_id", unique=True),
        CheckConstraint("qty > 0", name="ck_risa_qty_pos"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("returns.id"), nullable=False)
    return_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("return_items.id"), nullable=False)
    shortfall_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lot_shortfalls.id"), nullable=False)
    created_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    provisional_unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    provisional_cost_credit: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReturnItemResolutionAllocation(Base, PKMixin):
    """HAQIQIY yopish bilan atributlangan tovarning qaytishi.

    Sotuvda taxmin (p) bilan yozilgan, keyin partiya X ga (a) yopilgan tovar
    qaytsa: chekdagi taxmin `provisional_cost_credit` bilan TEXKARI qilinadi
    (TAXMINIY chelak), yopishda tan olingan og'ish esa `variance_reversed`
    bilan qaytariladi. Ikkalasi yig'ilib aynan `a` ni beradi — ya'ni X ga
    qaytgan tovar X narxida qaytadi va og'ish ikki marta qolmaydi.
    """
    __tablename__ = "return_item_resolution_allocations"
    __table_args__ = (
        Index("ux_rira_item_resolution", "return_item_id", "resolution_id", "sale_item_id",
              unique=True),
        CheckConstraint("qty > 0", name="ck_rira_qty_pos"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("returns.id"), nullable=False)
    return_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("return_items.id"), nullable=False)
    resolution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lot_shortfall_resolutions.id"), nullable=False)
    # ⚠️  QAYSI SOTUV QATORI qaytdi. Hodisaning `sale_item_id` si bilan FARQ
    #     qilishi mumkin: qarzning qaytib kelgan (U) tovari qayta sotilib, o'sha
    #     QAYTA SOTUV qaytsa, u qarzning haqiqiy hodisasi orqali qaytariladi
    #     (`lot_return.plan`, v3 R1). Chegaralar (qarz qatorining o'z tovari
    #     qancha tashqarida) aynan shu ustunga tayanadi.
    sale_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=False)
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_batches.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    provisional_cost_credit: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    variance_reversed: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
