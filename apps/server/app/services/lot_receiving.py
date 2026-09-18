# -*- coding: utf-8 -*-
"""PARTIYA QABULI (Phase 1) — kirim bitta tranzaksiyada partiya tug'diradi.

Bu modul FAQAT kirimni biladi. Sotuv (FEFO), qaytarish, hisobdan chiqarish va
inventarizatsiya hali partiyani BILMAYDI — ular `stock_gate` orqali kuzatuvli
mahsulotда rad etiladi.

⚠️  BITTA JISMONIY QABUL — BITTA zaxira o'sishi. Bugungi tizimda kirim IKKI yo'l
    bilan keladi: `POST /purchases` (menejer) va `POST /receiving/commit` (mobil
    nakladnoy skani). Ular PARALLEL, bir-birini to'ldirmaydi: qabul o'ZI Purchase
    hujjatini yaratadi. Ya'ni "xarid +10, keyin qabul +10 = +20" holati bugun ham
    YO'Q va bu modul uni kiritmaydi.

⚠️  IDEMPOTENTLIK — HUJJATDAN KELIB CHIQADI. Partiya kaliti tasodifiy emas:

        lot_key = uuid5(NS, f"{company}:{doc_key}:{line_index}:{lot_index}")

    `doc_key` — mijoz yuborgan hujjat `client_uuid` i (retry'da AYNI qoladi), u
    bo'lmasa hujjat id'si. Shu bois ayni qabulni qayta yuborish AYNI partiyaga
    tushadi; `ux_lot_intake_key UNIQUE(company_id, client_uuid)` esa poygada
    ikkinchisini DB darajasida to'sadi.

⚠️  ATRIBUT BO'YICHA BIRLASHTIRISH YO'Q. Keyingi yetkazib berish AYNI partiya
    raqami, AYNI muddat va AYNI narx bilan kelsa ham — bu BOSHQA kogorta.
    Ularning provenansi va `received_at` i har xil.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.inventory import Inventory, StockBatch
from app.services import lot_policy as LP
from app.services import stock_invariant as SI

# Partiya kalitlari uchun barqaror nom maydoni.
LOT_NS = uuid.UUID("6f1d4a52-6b1e-5a2c-9f43-7c0a1b2d3e4f")

# NUMERIC(14,3) — miqdor aniqligi (baza ustuni bilan AYNI).
Q3 = Decimal("0.001")

SOURCE_PURCHASE = "purchase"
SOURCE_RECEIVING = "receiving"
SOURCE_LEGACY = "legacy"
# ⚠️  TUZATISHDA TUG'ILGAN KOGORTA ALOHIDA BELGILANADI (Phase 5D). Uni
#     `receiving` deb yozish provenansni YOLG'ON qilardi: bu partiya yetkazib
#     berish lahzasida emas, hujjat TUZATILGANDA e'lon qilingan (miqdori va
#     narxi operator tuzatgan qiymat). Narx ASOSI baribir ANIQ — hujjatdan
#     keladi — shu bois u `lot_fefo.PROVISIONAL_SOURCES` ga KIRMAYDI va FEFO
#     uni odatdagi kogorta sifatida sotadi.
SOURCE_CORRECTION = "correction"


class LotPayloadError(ValueError):
    """Partiya ma'lumoti noto'g'ri — kirim RAD etiladi (400)."""


@dataclass
class LotIn:
    """Bitta partiya kirimi. `qty` dan boshqa hammasi ixtiyoriy."""
    qty: Decimal
    expiry_date: date | None = None
    batch_number: str | None = None
    unit_cost: Decimal | None = None
    external_lot_id: str | None = None


def lot_key(company_id, doc_key, line_index: int, lot_index: int) -> uuid.UUID:
    """DETERMINISTIK qabul kaliti — retry'da AYNI qiymat."""
    return uuid.uuid5(LOT_NS, f"{company_id}:{doc_key}:{line_index}:{lot_index}")


def is_tracked(product: Product) -> bool:
    return bool(getattr(product, "track_lots", False))


def validate_line(db: Session, company_id, branch_id, product: Product,
                  line_qty: Decimal, lots: list[LotIn] | None,
                  now: datetime | None = None) -> list[LotIn]:
    """Qator + partiyalarni TEKSHIRADI. Hech narsa yozmaydi.

    Kuzatuvsiz mahsulot uchun bugungi xulq butunlay o'zgarishsiz: `lots` berilmasa
    ham kirim o'tadi va partiya YARATILMAYDI.
    """
    if not is_tracked(product):
        if lots:
            raise LotPayloadError(
                f"'{product.name}' partiya bo'yicha kuzatilmaydi — `lots` berib "
                f"bo'lmaydi. Avval partiya kuzatuvini yoqing.")
        return []

    if not lots:
        raise LotPayloadError(
            f"'{product.name}' partiya bo'yicha kuzatiladi — har kirim qatori uchun "
            f"`lots` MAJBURIY. Miqdor taxmin qilinmaydi.")

    # ── ANIQLIK: 3 xonadan ORTIQ kasr RAD etiladi (jimgina yaxlitlash YO'Q) ──
    #  ⚠️  BU DARVOZA QOLDIQ VA PARTIYANI BIR XIL SONDA USHLAB TURADI. Qator
    #      miqdori `Inventory.qty` ga XOM holda qo'shiladi (NUMERIC(14,3) —
    #      Postgres yozuvda YARIM-YUQORIGA yaxlitlaydi), partiya esa shu yerda
    #      `_q` bilan kvantlanadi. 1.2345 kabi miqdorda ikki yo'l ikki xil
    #      qiymat berardi (qoldiq 1.235, partiya 1.234) va kirim yakuniy
    #      invariant darvozasida 409 bilan qulardi — operatorga esa «qo'llab-
    #      quvvatlashga murojaat qiling» deyilardi, holbuki sabab ANIQ va
    #      aytsa bo'ladigan: miqdorda ortiqcha kasr xona bor.
    if not _uch_xona(line_qty):
        raise LotPayloadError(
            f"'{product.name}': qator miqdori {Decimal(str(line_qty))} da uchtadan "
            f"ORTIQ kasr xonasi bor — miqdor 0.001 aniqligida beriladi. Miqdor "
            f"jimgina yaxlitlanmaydi.")
    assert_lot_precision(product, lots)

    # ── Miqdorlar ANIQ mos kelishi shart (Decimal, float EMAS) ──────────────
    total = sum((_q(x.qty) for x in lots), Decimal("0"))
    want = _q(line_qty)
    if total != want:
        raise LotPayloadError(
            f"'{product.name}': partiyalar yig'indisi {total} qator miqdori {want} ga "
            f"TENG EMAS. Yetishmagan miqdor taxmin qilinmaydi.")
    for x in lots:
        if _q(x.qty) <= 0:
            raise LotPayloadError(f"'{product.name}': partiya miqdori musbat bo'lishi shart")

    # ── Muddat ──────────────────────────────────────────────────────────────
    if getattr(product, "track_expiry", False):
        LP.assert_tz_confirmed(db, company_id, branch_id)
        validate_expiry(db, branch_id, product, lots, now)
    else:
        validate_no_expiry(product, lots)
    return lots


def validate_expiry(db: Session, branch_id, product: Product, lots: list[LotIn],
                    now: datetime | None = None) -> None:
    """Muddat kuzatuvidagi partiyalar: har birida muddat BOR va u O'TMAGAN.

    ⚠️  YAGONA QOIDA. Kirim ham, kuzatuvni yoqishdagi ochilish partiyalari ham shu
        yerdan o'tadi — «muddatsiz» yoki «muddati o'tgan» partiya bir eshikda rad
        etilib, ikkinchisidan jimgina kirib qolmasin. Vaqt zonasi tasdig'ini
        chaqiruvchi O'ZI tekshiradi (xatosi 409, bu yerdagilari 400).
    """
    biz = LP.business_date(db, branch_id, now)
    for x in lots:
        if x.expiry_date is None:
            raise LotPayloadError(
                f"'{product.name}' muddat bo'yicha kuzatiladi — har partiyada "
                f"`expiry_date` MAJBURIY. Noma'lum muddat jimgina qabul qilinmaydi.")
        if LP.is_expired(x.expiry_date, biz):
            raise LotPayloadError(
                f"'{product.name}': {x.expiry_date} muddati bugungi biznes sanasi "
                f"({biz}) dan OLDIN — muddati o'tgan tovar qabul qilinmaydi.")


def validate_no_expiry(product: Product, lots: list[LotIn]) -> None:
    """Muddat KUZATILMAYDIGAN mahsulot partiyasida sana bo'lmasligi shart.

    ⚠️  SANOQ BILAN AYNI QOIDA VA AYNI MATN (`inventory.py`, yangi partiyalar). FEFO
        nomzodlari muddati o'tgan partiyani HAR kuzatuvli mahsulotda (FIFO ham)
        chiqarib tashlaydi: o'tgan sana partiyani birinchi kundanoq sotuvdan
        tushirib, tovarni javonda qoldirardi; kelajak sana esa FIFO kogortasini
        jimgina muddat bo'yicha saralashga o'tkazardi. Sanani jimgina tashlab
        yuborish ham yaramaydi — operator uni ANIQ kiritdi, biz faqat AYTAMIZ.
    """
    for x in lots:
        if x.expiry_date is not None:
            raise LotPayloadError(
                f"'{product.name}' muddat bo'yicha KUZATILMAYDI — yangi "
                f"partiyaga `expiry_date` yozib bo'lmaydi. Avval "
                f"mahsulotda muddat kuzatuvini yoqing.")


def _q(v) -> Decimal:
    """NUMERIC(14,3) aniqligida. Float solishtirish ISHLATILMAYDI.

    ⚠️  ROUND_HALF_UP — TASODIFIY EMAS. Ilgari bu yerda Decimal'ning STANDART
        konteksti (ROUND_HALF_EVEN) ishlatilardi va kirim BUTUN tizimda YAGONA
        yarim-juftga yaxlitlovchi joy edi: FEFO (`lot_fefo._q`), hisobdan
        chiqarish (`lot_writeoff`), qarzni yopish (`lot_resolution`), sotuv
        (`services/sales.py`), Postgres NUMERIC yozuvi va frontend `lots.ts:q3`
        — hammasi yarim-YUQORIGA yaxlitlaydi. 1.2345 kabi miqdorda kirim 1.234,
        qoldiq esa 1.235 bo'lib, partiya qoldiqdan JIMGINA ajralardi.
    """
    return Decimal(str(v)).quantize(Q3, rounding=ROUND_HALF_UP)


def _uch_xona(v) -> bool:
    """Miqdorda ko'pi bilan 3 ta kasr xonasi bormi (yaxlitlash KERAK EMASmi)."""
    d = Decimal(str(v))
    return d == d.quantize(Q3, rounding=ROUND_HALF_UP)


def _c(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"))


#  Partiya YARATADIGAN IKKINCHI yo'l — `api/v1/lots.py` ochilish partiyalari — AYNI
#  kvantlash va AYNI aniqlik darvozasidan foydalanadi (Phase 5C review, D-2): u yerda
#  yig'indi Decimal'ning STANDART konteksti (ROUND_HALF_EVEN) bilan solishtirilardi,
#  `create_lots` esa har partiyani `_q` (ROUND_HALF_UP) bilan yozadi. 1.2345 kabi
#  miqdor darvozadan O'TIB, partiya 1.235, qoldiq 1.234 bo'lardi va QAYTARIB
#  BO'LMAYDIGAN yoqish yakuniy invariantda opaque 409 bilan qulardi.
q3 = _q
uch_xona = _uch_xona


def assert_lot_precision(product: Product, lots: list[LotIn]) -> None:
    """Har partiya miqdori 0.001 aniqligida bo'lsin — aks holda ANIQ 400 (jimgina yaxlitlash YO'Q)."""
    for x in lots:
        if not _uch_xona(x.qty):
            raise LotPayloadError(
                f"'{product.name}': partiya miqdori {Decimal(str(x.qty))} da uchtadan "
                f"ORTIQ kasr xonasi bor — miqdor 0.001 aniqligida beriladi. Miqdor "
                f"jimgina yaxlitlanmaydi.")


def create_lots(db: Session, *, company_id, branch_id, product: Product,
                lots: list[LotIn], doc_key, line_index: int, source_type: str,
                default_cost, now: datetime,
                purchase_item_id=None, receiving_id=None,
                supplier_id=None) -> list[StockBatch]:
    """Partiyalarni YARATADI (yoki takrorda mavjudini QAYTARADI).

    ⚠️  `Inventory.qty` BU YERDA o'zgartirilmaydi — uni chaqiruvchi oqim o'z
        qulfi ostida qiladi, so'ng invariant tekshiriladi.

    Tannarx provenansi (ANIQ tartib):
      1. partiyaning O'Z `unit_cost` i (kirimда aniq berilgan)
      2. hujjat qatorining tannarxi (`default_cost`)
      3. shundan keyin ham bo'lmasa — XATO, `base_buy_price` JIMGINA olinmaydi
    """
    out: list[StockBatch] = []
    for idx, x in enumerate(lots):
        cost = x.unit_cost if x.unit_cost is not None else default_cost
        if cost is None:
            raise LotPayloadError(
                f"'{product.name}': partiya tannarxi noma'lum. Kirim narxi yoki "
                f"partiya narxi berilishi shart — mahsulotning joriy olish narxi "
                f"JIMGINA ishlatilmaydi.")
        key = lot_key(company_id, doc_key, line_index, idx)
        existing = (db.query(StockBatch)
                    .filter(StockBatch.company_id == company_id,
                            StockBatch.client_uuid == key).first())
        if existing is not None:
            out.append(existing)          # TAKROR — yangi partiya yaratilmaydi
            continue
        qty = _q(x.qty)
        b = StockBatch(
            id=uuid.uuid4(), company_id=company_id, branch_id=branch_id,
            product_id=product.id,
            batch_no=(x.batch_number or None),
            expiry_date=x.expiry_date,
            qty=qty,                      # eski ustun — moslik uchun birga yoziladi
            received_qty=qty, remaining_qty=qty,
            unit_cost=_c(cost),
            status=SI.OPEN, source_type=source_type,
            purchase_item_id=purchase_item_id, receiving_id=receiving_id,
            external_lot_id=(x.external_lot_id or None),
            supplier_id=supplier_id, client_uuid=key,
            received_at=now, created_at=now, updated_at=now, row_version=1)
        db.add(b)
        try:
            db.flush()
        except IntegrityError:
            # Poyga: boshqa tranzaksiya AYNI kalitni yozib ulgurdi.
            db.rollback()
            raise
        out.append(b)
    return out


def open_legacy_lot(db: Session, *, company_id, branch_id, product: Product,
                    qty: Decimal, unit_cost, reason: str, now: datetime) -> StockBatch:
    """Kuzatuv YOQILGANDA mavjud qoldiq uchun ANIQ ochilish partiyasi.

    ⚠️  MIQDOR O'YLAB TOPILMAYDI: u AYNAN joriy `Inventory.qty`. Muddat va partiya
        raqami `NULL` — ular noma'lum va taxmin qilinmaydi. Tannarx operator
        tomonidan ANIQ tasdiqlanadi.
    """
    q = _q(qty)
    key = uuid.uuid5(LOT_NS, f"legacy:{company_id}:{branch_id}:{product.id}")
    b = StockBatch(
        id=uuid.uuid4(), company_id=company_id, branch_id=branch_id, product_id=product.id,
        batch_no=None, expiry_date=None, qty=q, received_qty=q, remaining_qty=q,
        unit_cost=_c(unit_cost), status=SI.OPEN, source_type=SOURCE_LEGACY,
        external_lot_id=None, client_uuid=key,
        received_at=now, created_at=now, updated_at=now, row_version=1)
    db.add(b)
    db.flush()
    return b


def assert_invariant(db: Session, company_id, product_ids) -> None:
    """Kirimdan KEYIN invariant — buzilgan bo'lsa chaqiruvchi ROLLBACK qiladi."""
    SI.assert_ok(db, company_id, product_ids)


def inventory_for_update(db: Session, product_id, branch_id) -> Inventory | None:
    """Qoldiq qatorini QULFLAB oladi (mavjud naqsh bilan bir xil)."""
    return (db.query(Inventory)
            .filter(Inventory.product_id == product_id, Inventory.branch_id == branch_id)
            .with_for_update().first())
