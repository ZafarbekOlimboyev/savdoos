# -*- coding: utf-8 -*-
"""QABUL HUJJATINI TUZATISH (Phase 5D) — O'ZGARMAS TESKARI YOZUV + O'RNIGA QO'YISH.

NEGA JOYIDA TAHRIR EMAS
=======================
Nakladnoy noto'g'ri kiritilgan (10 o'rniga 100, boshqa muddat, boshqa narx)
bo'lsa, «qatorni to'g'rilash» eng tabiiy ko'rinadi. U ISHLAMAYDI:

⚠️  `StockBatch.received_qty` butun repoda HECH QAYERDA qayta yozilmaydi va
    `stock_invariant._lot_sums` faqat `remaining_qty` ni yig'adi — ya'ni
    partiya ATRIBUTLARINI tahrirlash xavfsizlik to'riga UMUMAN ko'rinmaydi.
    Bundan ham yomoni: `sale_item_lot_allocations.unit_cost` — SOTUV
    LAHZASINING muzlatilgan surati. Tovar ketganidan keyin partiya narxini
    qayta yozish tarixiy COGS'ni YOLG'ON qilardi.

⚠️  «Bekor qilib qayta qabul qilish» ham ishlamaydi: partiya kaliti
    `uuid5(company:doc_key:line_index:lot_index)` va `create_lots` takroriy
    kalitda MAVJUD partiyani QAYTARADI; `/receiving/commit` esa `client_uuid`
    bo'yicha dedup qilib, hech narsa qo'llamasdan `duplicate: true` beradi.
    Yangi `client_uuid` bilan qayta yuborish esa eski kogortani JONLI qoldirib,
    yoniga ikkinchisini qo'shardi.

⚠️  Inventarizatsiya (sanoq) yo'li ham to'g'ri javob emas: u ortiqchani
    `source_type='adjustment'` bilan PROVENANSI NOMA'LUM kogorta qilib
    tug'diradi va yetkazib beruvchi/kassa bog'lanishini butunlay yo'qotadi.

Shu bois tuzatish — ALOHIDA, O'ZGARMAS HODISA:

    teskari yozuv (mavjud kogorta kamayadi)  +  o'rniga qo'yish (yangi kogorta)

Batafsil qaror va rad etishlar: `app/services/RECEIVING_CORRECTION.md`.

IKKI XIL TUZATISH — IKKI XIL QATTIQLIK
======================================
  MIQDOR tuzatishi   — «100 emas, 90 keldi». Tarixda hech narsa yolg'on
                       bo'lmaydi: qoldiqdan ortiqchasi olib tashlanadi.
                       Qisman sotilgan kogortada ham RUXSAT (faqat qoldiq
                       chegarasi).
  IDENTIFIKATSIYA     — «narx/muddat/partiya raqami xato». Bu eski kogortani
                       o'ldirib, o'rniga yangisini tug'diradi, shu bois eski
                       kogorta TEGILMAGAN bo'lishi SHART: sotilgan,
                       qaytarilgan yoki harakatga tushgan partiyaning
                       identifikatsiyasi tarixda ALLAQACHON ishlatilgan.

⚠️  `remaining_qty == received_qty` YOLG'IZ YETMAYDI. Sotuv + mijoz qaytarishi
    qoldiqni AYNAN tiklaydi (`lot_return._restock` hatto `depleted` partiyani
    qayta ochadi) — ya'ni «tegilmagan» ko'rinadigan kogorta aslida chekda
    ishlatilgan bo'lishi mumkin. Shu bois uchala allokatsiya jadvali ham
    ALOHIDA tekshiriladi.

QULF TARTIBI (GLOBAL — yangi tartib O'YLAB TOPILMAYDI)
======================================================
  1. takror qidiruvi — QULFSIZ (tez yo'l)
  2. FK ota qatorlari FOR KEY SHARE (do'kon, filial, xodim, qabul, mahsulotlar)
  3. `Purchase` FOR UPDATE -> refresh -> `deleted_at` QAYTA tekshiruvi
  4. `Supplier` FOR UPDATE -> `Purchase` QAYTA refresh (QA PR-008)
  5. smena + `resolve_cash_custody` (faqat NAQD hujjat)
  6. `Inventory` FOR UPDATE — mahsulot id'si bo'yicha TARTIBLANGAN
  7. `StockBatch` FOR UPDATE (`lot_writeoff.lock_batches`, id tartibida)
  8. hodisa INSERT'lari -> flush -> `stock_invariant.assert_ok` -> commit

⚠️  OTA QATORLAR NEGA OLDINDAN KEY SHARE. Hodisa INSERT'i FK orqali ota
    qatorga KEY SHARE oladi; uni keyinroq birinchi marta olish ota qatorni
    FOR UPDATE ushlab turgan tranzaksiya bilan qulf halqasi tug'dirardi
    (Phase 2.5 darsi, `lot_resolution` bilan AYNI naqsh).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core import error_codes as EC
from app.models.enums import CreditTxnType, MovementType, PurchaseStatus
from app.models.inventory import (ReturnItemLotAllocation, SaleItemLotAllocation,
                                  StockBatch, StockMovement,
                                  StockMovementLotAllocation)
from app.models.purchasing import (Purchase, PurchaseItem, PurchaseReturn, Supplier,
                                   SupplierLedger)
from app.models.receiving import Receiving, ReceivingCorrection
from app.services import lot_policy as LP
from app.services import lot_receiving as LR
from app.services import lot_writeoff as LW
from app.services import stock_invariant as SI

log = logging.getLogger(__name__)

Q = Decimal("0.001")      # NUMERIC(14,3) — miqdor
C = Decimal("0.01")       # NUMERIC(14,2) — pul
NUMERIC_14_2_MAX = Decimal("999999999999.99")

MAX_LINES = 200
MAX_LOTS = 50
REASON_MIN, REASON_MAX = 3, 300

# `stock_movements.ref_type` va `supplier_ledger.ref_type` — TUZATISHNING
# yagona belgisi. Hisobotlar va kassa migratsiyasi `('purchase', 'receiving')`
# predikatiga tayanadi; tuzatish ALOHIDA nom oladi va o'sha predikatga
# HECH QACHON kirmaydi (pastdagi «YETKAZIB BERUVCHI» izohiga qarang).
REF_TYPE = "receiving_correction"


def _q3(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(Q, rounding=ROUND_HALF_UP)


def _c2(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(C, rounding=ROUND_HALF_UP)


class CorrectionError(Exception):
    """HTTP holati bilan rad etish — API qatlami `HTTPException` ga o'giradi.

    `code` — ixtiyoriy barqaror kod (`app/core/error_codes.py`); API uni
    `X-Error-Code` sarlavhasiga qo'yadi, MATNGA qo'shmaydi
    (`lot_resolution.ResolutionError` bilan AYNI naqsh)."""

    def __init__(self, status: int, detail: str, code: str | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


# ══ SO'ROV SHAKLI — HTTP'DAN MUSTAQIL ═══════════════════════════════════════

@dataclass
class ReverseIn:
    """Mavjud kogortadan teskari qilinadigan miqdor."""
    stock_batch_id: _uuid.UUID
    qty: Decimal


@dataclass
class ReplaceIn:
    """O'rniga qo'yiladigan YANGI kogorta (oddiy kirim partiyasi bilan AYNI shakl)."""
    qty: Decimal
    batch_number: str | None = None
    expiry_date: date | None = None
    unit_cost: Decimal | None = None


@dataclass
class LineIn:
    purchase_item_id: _uuid.UUID
    reverse: list[ReverseIn] = field(default_factory=list)
    replace: list[ReplaceIn] = field(default_factory=list)
    unit_cost: Decimal | None = None      # tuzatilgan qator tannarxi


@dataclass
class CorrectionIn:
    client_uuid: _uuid.UUID
    reason: str
    cash_account_id: _uuid.UUID | None = None
    lines: list[LineIn] = field(default_factory=list)


def canonical(receiving_id, data: CorrectionIn) -> dict:
    """So'rovning KANONIK shakli — `request_hash` va audit surati uchun BITTA manba.

    ⚠️  QATORLAR TARTIBI SAQLANADI (saralanmaydi): `line_index` partiya kalitiga
        (`uuid5(... line_index ...)`) kiradi, ya'ni tartib o'zgarsa bu BOSHQA
        so'rov. Miqdor va pul MATN sifatida, ustun ANIQLIGIDA yoziladi — float
        `0.1 + 0.2` ni ikki xil hash qilardi.
    """
    return {
        "receiving_id": str(receiving_id),
        "reason": data.reason,
        "cash_account_id": (str(data.cash_account_id)
                            if data.cash_account_id is not None else None),
        "lines": [{
            "purchase_item_id": str(ln.purchase_item_id),
            "unit_cost": (str(_c2(ln.unit_cost)) if ln.unit_cost is not None else None),
            "reverse": [{"stock_batch_id": str(r.stock_batch_id), "qty": str(_q3(r.qty))}
                        for r in ln.reverse],
            "replace": [{"qty": str(_q3(x.qty)),
                         "batch_number": (x.batch_number or None),
                         "expiry_date": (x.expiry_date.isoformat()
                                         if x.expiry_date is not None else None),
                         "unit_cost": (str(_c2(x.unit_cost))
                                       if x.unit_cost is not None else None)}
                        for x in ln.replace],
        } for ln in data.lines],
    }


def request_hash(receiving_id, data: CorrectionIn) -> str:
    return hashlib.sha256(
        json.dumps(canonical(receiving_id, data), sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest()


def _check_shape(data: CorrectionIn) -> None:
    """So'rov SHAKLI — bazaga tegmasdan. Xato bo'lsa HECH NARSA o'zgarmaydi."""
    reason = (data.reason or "").strip()
    if not (REASON_MIN <= len(reason) <= REASON_MAX):
        raise CorrectionError(
            400, f"Tuzatish sababi {REASON_MIN}..{REASON_MAX} belgidan iborat bo'lishi "
                 f"shart — sababsiz tuzatish audit izini bo'sh qoldirardi.")
    if not data.lines:
        raise CorrectionError(400, "Kamida bitta qator kerak")
    if len(data.lines) > MAX_LINES:
        raise CorrectionError(
            400, f"Bitta so'rovda {len(data.lines)} ta qator — chegara {MAX_LINES}. "
                 f"Tuzatishni bir necha so'rovga bo'lib yuboring.")
    seen_items, seen_batches = set(), set()
    for ln in data.lines:
        key = str(ln.purchase_item_id)
        if key in seen_items:
            raise CorrectionError(400, f"Qator ikki marta ko'rsatilgan: {key}")
        seen_items.add(key)
        if len(ln.reverse) > MAX_LOTS or len(ln.replace) > MAX_LOTS:
            raise CorrectionError(
                400, f"Bitta qatorda {MAX_LOTS} tadan ortiq partiya — tuzatishni "
                     f"bo'lib yuboring.")
        if not ln.reverse and not ln.replace:
            raise CorrectionError(
                400, f"Qatorda na teskari qilish, na o'rniga qo'yish bor: {key}")
        for r in ln.reverse:
            # ⚠️  PARTIYA BUTUN SO'ROVDA BIR MARTA. `lot_writeoff.validate` takrorni
            #     FAQAT bitta qator ichida ko'radi; ayni partiya ikki qatorda kelsa
            #     u ikki marta kamayardi.
            bkey = str(r.stock_batch_id)
            if bkey in seen_batches:
                raise CorrectionError(400, f"Partiya ikki marta ko'rsatilgan: {bkey}")
            seen_batches.add(bkey)
        if ln.replace:
            if ln.unit_cost is None:
                raise CorrectionError(
                    400, f"O'rniga qo'yiladigan partiya bor, lekin qator tannarxi "
                         f"berilmagan: {key}. Tannarx TAXMIN QILINMAYDI.")
            if _c2(ln.unit_cost) < 0:
                raise CorrectionError(400, "Qator tannarxi manfiy bo'lishi mumkin emas")
        elif ln.unit_cost is not None:
            # ⚠️  TANNARXNI PARTIYASIZ TUZATIB BO'LMAYDI. `StockBatch.unit_cost`
            #     o'zgarmas; narxni «shunchaki» yangilash hujjat bilan kogortani
            #     JIMGINA ajratardi. Narx tuzatilsa — eski kogorta teskari qilinib,
            #     yangisi ANIQ e'lon qilinadi.
            raise CorrectionError(
                400, f"Tannarxni partiyasiz tuzatib bo'lmaydi: {key}. Eski partiyani "
                     f"teskari qiling va yangisini `replace` bilan e'lon qiling.")


def _guard_total(value, label: str) -> Decimal:
    """`Numeric(14,2)` sig'imi — xom 500 (numeric overflow) o'rniga aniq 400."""
    v = _c2(value)
    if v > NUMERIC_14_2_MAX or v < -NUMERIC_14_2_MAX:
        raise CorrectionError(400, f"{label} juda katta — miqdor yoki narxni tekshiring")
    return v


# ══ TEGILGANLIK DALILI ══════════════════════════════════════════════════════

def alloc_sums(db: Session, batch_ids) -> dict:
    """{partiya_id(str): (sotuv, harakat, qaytarish)} — allokatsiya YIG'INDILARI.

    ⚠️  UCHALA JADVAL HAM KERAK. `remaining_qty == received_qty` YOLG'IZ yolg'on
        guvoh: sotilib keyin qaytarilgan kogortada u AYNAN tiklanadi. Qaytarish
        yig'indisi ALOHIDA qaytariladi — u «tegilgan» dalilini KAMAYTIRMAYDI,
        faqat `consumed()` hisobiga kiradi.
    """
    ids = [b for b in batch_ids if b is not None]
    out = {str(b): [Decimal("0"), Decimal("0"), Decimal("0")] for b in ids}
    if not ids:
        return {}
    for i, model in enumerate((SaleItemLotAllocation, StockMovementLotAllocation,
                               ReturnItemLotAllocation)):
        rows = db.execute(
            select(model.stock_batch_id, func.coalesce(func.sum(model.qty), 0))
            .where(model.stock_batch_id.in_(ids))
            .group_by(model.stock_batch_id)).all()
        for bid, total in rows:
            if str(bid) in out:
                out[str(bid)][i] = _q3(total)
    return {k: (v[0], v[1], v[2]) for k, v in out.items()}


def consumed(sums) -> Decimal:
    """Partiyadan HAQIQATAN ketgan miqdor: sotuv + harakat − qaytarish."""
    sale, move, ret = sums if sums else (Decimal("0"),) * 3
    return _q3(sale) + _q3(move) - _q3(ret)


def untouched(batch: StockBatch, sums) -> bool:
    """Kogorta IDENTIFIKATSIYASI hali tuzatilishi mumkinmi (tarixda ishlatilmaganmi)."""
    if _q3(batch.remaining_qty) != _q3(batch.received_qty):
        return False
    sale, move, ret = sums if sums else (Decimal("0"),) * 3
    return _q3(sale) == 0 and _q3(move) == 0 and _q3(ret) == 0


def open_shortfall_products(db: Session, company_id, product_ids, branch_id) -> list:
    """YOPILMAGAN atributsiya qarzi bor mahsulotlar — INVARIANTNING O'Z ta'rifi bilan."""
    if not product_ids:
        return []
    sums = SI._shortfall_sums(db, company_id, list(product_ids))
    return [pid for pid in product_ids
            if sums.get((str(pid), str(branch_id)), Decimal("0")) > 0]


def doc_has_correction(db: Session, company_id, purchase_id) -> bool:
    """Hujjatda tuzatish bormi — `PATCH /purchases/{id}` darvozasi shu yerdan o'qiydi."""
    return db.execute(
        select(ReceivingCorrection.id)
        .where(ReceivingCorrection.company_id == company_id,
               ReceivingCorrection.purchase_id == purchase_id).limit(1)).first() is not None


# ══ IDEMPOTENTLIK ═══════════════════════════════════════════════════════════

def _visible(db: Session, emp, branch_id) -> bool:
    from app.core.deps import visible_branches
    vb = visible_branches(emp, db)
    return vb is None or branch_id in vb


def _replay(db: Session, emp, receiving_id, client_uuid, h: str):
    """Ayni `client_uuid` allaqachon yozilganmi. Yozilgan bo'lsa — BIRINCHI javob."""
    hdr = db.execute(select(ReceivingCorrection).where(
        ReceivingCorrection.company_id == emp.company_id,
        ReceivingCorrection.client_uuid == client_uuid)).scalar_one_or_none()
    if hdr is None:
        return None
    if str(hdr.receiving_id) != str(receiving_id) or hdr.request_hash != h:
        raise CorrectionError(
            409, "Bu client_uuid BOSHQA tuzatish so'rovida ishlatilgan — takror emas. "
                 "Yangi so'rov uchun yangi client_uuid bering.",
            code=EC.LOT_CORRECTION_REPLAY_CONFLICT)
    # Filial izolyatsiyasi takrorda ham amal qiladi (IDOR): begona filial hujjati
    # mavjudligi ham bilinmasin.
    if not _visible(db, emp, hdr.branch_id):
        raise CorrectionError(404, "Qabul topilmadi")
    try:
        stored = json.loads(hdr.response_json or "null")
    except ValueError:
        stored = None
    if not isinstance(stored, dict):
        # Birinchi tranzaksiya hali commit qilmagan (yoki yarim qolgan) — javob YO'Q.
        raise CorrectionError(409, "Tuzatish so'rovi yakunlanmagan — qayta urinib ko'ring")
    return {**stored, "duplicate": True}


def _key_share(db: Session, model, pk) -> None:
    if pk is None:
        return
    db.execute(select(model.id).where(model.id == pk)
               .with_for_update(read=True, key_share=True))


# ══ ASOSIY OQIM ═════════════════════════════════════════════════════════════

def correct(db: Session, emp, receiving_id, data: CorrectionIn) -> dict:
    """Qabulni tuzatadi. Muvaffaqiyatda COMMIT qiladi; rad etishda `CorrectionError`.

    ⚠️  QAYTA URINISH — `/lots/enable` siklining AYNI shakli. `IntegrityError`
        (ayni `client_uuid` poygasi) da g'olib tranzaksiyaning javobi
        qaytariladi; `40P01` (deadlock) da tranzaksiya TO'LIQ qaytgan, qayta
        urinish xavfsiz (500 emas).
    """
    _check_shape(data)
    h = request_hash(receiving_id, data)
    last: Exception | None = None
    for _try in range(3):
        try:
            return _correct_once(db, emp, receiving_id, data, h)
        except IntegrityError as e:
            db.rollback()
            dup = _replay(db, emp, receiving_id, data.client_uuid, h)
            if dup is not None:
                return dup
            last = e
        except OperationalError as e:
            if getattr(getattr(e, "orig", None), "sqlstate", None) != "40P01":
                raise
            db.rollback()
            last = e
    raise CorrectionError(409, "Qabul hujjati band — qayta urinib ko'ring") from last


def _correct_once(db: Session, emp, receiving_id, data: CorrectionIn, h: str) -> dict:
    from app.models.auth import Employee
    from app.models.catalog import Product
    from app.models.org import Branch, Company
    from app.services.audit import log as audit_log

    # ── 1) TAKROR — QULFSIZ TEZ YO'L ────────────────────────────────────────
    dup = _replay(db, emp, receiving_id, data.client_uuid, h)
    if dup is not None:
        return dup

    # ── 2) HUJJATLAR (qulfsiz o'qish; hammasi qulf ostida QAYTA tekshiriladi) ──
    rec = db.get(Receiving, receiving_id)
    if rec is None or rec.company_id != emp.company_id:
        raise CorrectionError(404, "Qabul topilmadi")
    # ⚠️  BEGONA FILIAL — 404, HECH QACHON 403: 403 hujjat MAVJUDLIGINI oshkor
    #     qilardi (IDOR), `/receiving/{id}` bilan AYNI qoida.
    if not _visible(db, emp, rec.branch_id):
        raise CorrectionError(404, "Qabul topilmadi")
    if rec.purchase_id is None:
        raise CorrectionError(404, "Kirim topilmadi")
    pur0 = db.get(Purchase, rec.purchase_id)
    if pur0 is None or pur0.company_id != emp.company_id or pur0.deleted_at is not None:
        raise CorrectionError(404, "Kirim topilmadi")
    if not _visible(db, emp, pur0.branch_id):
        raise CorrectionError(404, "Kirim topilmadi")
    # ⚠️  FILIAL — HUJJATNIKI, `actor_branch` EMAS. Partiyalar va qoldiq AYNAN shu
    #     filialda; xodim filialiga yozish qoldiqni boshqa filialga surardi.
    #     O'chirilgan filialda tuzatish BLOKLANADI (`edit_purchase` bilan izchil):
    #     aks holda qoldiq umuman bo'lmagan joyda o'zgarardi.
    branch = db.query(Branch).filter(Branch.id == pur0.branch_id,
                                     Branch.deleted_at.is_(None)).first()
    if branch is None:
        raise CorrectionError(400, "Xarid filiali o'chirilgan — tuzatib bo'lmaydi")

    # Bu qabul UMUMAN partiya tug'dirganmi (aks holda tuzatiladigan kogorta yo'q).
    if db.execute(select(StockBatch.id).where(
            StockBatch.company_id == emp.company_id,
            StockBatch.receiving_id == rec.id).limit(1)).first() is None:
        raise CorrectionError(
            409, "Bu qabul partiya yaratmagan — tuzatish oqimi faqat partiyali qabul "
                 "uchun. Hujjatni oddiy kirim tahriri bilan o'zgartiring.",
            code=EC.LOT_CORRECTION_NOT_TRACKED)

    items = {it.id: it for it in db.query(PurchaseItem)
             .filter(PurchaseItem.purchase_id == pur0.id).all()}
    for ln in data.lines:
        if ln.purchase_item_id not in items:
            raise CorrectionError(400, f"Qator topilmadi: {ln.purchase_item_id}")
    pid_of = {str(ln.purchase_item_id): items[ln.purchase_item_id].product_id
              for ln in data.lines}
    pids = sorted({pid_of[str(ln.purchase_item_id)] for ln in data.lines}, key=str)
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()}
    for pid in pids:
        p = products.get(pid)
        if p is None or p.company_id != emp.company_id or p.deleted_at is not None:
            raise CorrectionError(400, f"Mahsulot topilmadi: {pid}")

    # ── 3) FK OTA QATORLARI — FOR KEY SHARE (Inventory qulfidan OLDIN) ──────
    _key_share(db, Company, emp.company_id)
    _key_share(db, Branch, branch.id)
    _key_share(db, Employee, emp.id)
    _key_share(db, Receiving, rec.id)
    for pid in pids:
        _key_share(db, Product, pid)

    # ── 4) HUJJAT QULFI -> REFRESH -> `deleted_at` QAYTA ────────────────────
    #  ⚠️  Yuqoridagi tekshiruv qulfdan OLDIN edi: parallel to'liq bekor qilish
    #      (yoki boshqa tuzatish) shu orada commit qilgan bo'lsa, biz o'chirilgan
    #      hujjatni IKKINCHI marta bekor qilib, ikkinchi naqd qaytarish yozardik.
    pur = db.query(Purchase).filter(Purchase.id == pur0.id).with_for_update().first()
    if pur is None:
        raise CorrectionError(404, "Kirim topilmadi")
    db.refresh(pur)
    # ⚠️  TAKROR TEKSHIRUVI `deleted_at` DAN OLDIN. Birinchi so'rov hujjatni TO'LIQ
    #     bekor qilgan bo'lsa (`deleted_at` o'rnatilgan), ayni `client_uuid` bilan
    #     kelgan takror pastdagi 404 ga urilardi — ya'ni operatorga «hujjat yo'q»
    #     deyilardi, holbuki uning o'z so'rovi BAJARILGAN. Takror HAR DOIM birinchi
    #     javobni qaytaradi, natija hujjatga nima qilgan bo'lishidan qat'i nazar.
    dup = _replay(db, emp, receiving_id, data.client_uuid, h)
    if dup is not None:
        db.rollback()
        return dup
    if pur.deleted_at is not None:
        raise CorrectionError(404, "Kirim topilmadi")

    # ── 5) TA'MINOTCHI QULFI -> HUJJATNI QAYTA REFRESH (QA PR-008) ──────────
    #  Ta'minotchi qulfini olgunimizcha parallel to'lov `paid_amount` ni
    #  o'zgartirgan bo'lishi mumkin — holat shu qiymatdan hisoblanadi.
    sup = (db.query(Supplier).filter(Supplier.id == pur.supplier_id)
           .with_for_update().first() if pur.supplier_id else None)
    db.refresh(pur)

    # TAKROR — TA'MINOTCHI QULFIDAN KEYIN YANA BIR BOR. Yuqoridagi tekshiruv
    # hujjat qulfi ostida edi; bu yerda esa ta'minotchi qulfida kutib turgan
    # takror uchun (birinchi so'rov shu orada commit qilishi mumkin).
    dup = _replay(db, emp, receiving_id, data.client_uuid, h)
    if dup is not None:
        db.rollback()
        return dup

    # ⚠️  QARZ HUJJATIMI — `purchases.py` BILAN AYNI PREDIKAT. `ref_type` IKKI xil
    #     bo'lishi mumkin: Manager xaridi 'purchase', mobil kredit-qabul
    #     'receiving' (QA PR-001). Faqat 'purchase' izlash mobil manbali qarzni
    #     tuzatishda balansni UMUMAN qimirlatmasdi.
    _charged = sup is not None and db.query(SupplierLedger.id).filter(
        SupplierLedger.supplier_id == pur.supplier_id,
        SupplierLedger.ref_type.in_(("purchase", "receiving")),
        SupplierLedger.ref_id == pur.id,
        SupplierLedger.type == CreditTxnType.charge).first() is not None

    # ── 6) NAQD CUSTODY — smena + cutover darvozasi (faqat naqd hujjat) ─────
    acc = None
    if not _charged:
        from app.models.enums import ShiftStatus as _ShSt
        from app.models.shifts import Shift as _Shift
        from app.services.cash import cutover_guard as _cg
        _sh = (db.query(_Shift).filter(_Shift.cashier_id == emp.id,
                                       _Shift.status == _ShSt.open).first())
        # §2 CUSTODY: smena bor -> shift.till_id; smenasiz -> so'rovdagi EXPLICIT
        # `cash_account_id`. Filial/kassir bo'yicha TAXMIN QILINMAYDI.
        acc, _ = _cg.resolve_cash_custody(
            db, company_id=emp.company_id, branch_id=pur.branch_id,
            operation="receiving_correction_cash", shift=_sh,
            cash_account_id=data.cash_account_id)

    # ── 7) QOLDIQ QATORLARI — mahsulot id'si bo'yicha TARTIBLANGAN FOR UPDATE ──
    invs: dict = {}
    for pid in pids:
        inv = LR.inventory_for_update(db, pid, branch.id)
        if inv is None:
            raise CorrectionError(
                409, f"'{products[pid].name}': qoldiq qatori topilmadi — tuzatib "
                     f"bo'lmaydi")
        invs[str(pid)] = inv

    # YOPILMAGAN QARZ — qulf ostida (parallel sotuv qoldiq qatorini ushlaydi).
    bad = open_shortfall_products(db, emp.company_id, pids, branch.id)
    if bad:
        raise CorrectionError(
            409, f"'{products[bad[0]].name}': yopilmagan partiya qarzi bor — avval "
                 f"qarzni partiyaga bog'lang. Qarz ochiq ekan qaysi kogorta ketgani "
                 f"NOMA'LUM va tuzatish uni jimgina boshqa partiyaga surardi.",
            code=EC.LOT_CORRECTION_SHORTFALL_OPEN)

    # ── 8) PARTIYALAR — `lot_writeoff.lock_batches` (id tartibida FOR UPDATE) ──
    batches = LW.lock_batches(db, [r.stock_batch_id for ln in data.lines
                                   for r in ln.reverse])
    sums = alloc_sums(db, [b.id for b in batches.values()])

    now = datetime.now(timezone.utc)
    plans: dict = {}          # product_id(str) -> [(StockBatch, Decimal)]
    new_lots: list = []       # (line_index, LineIn, product, [LotIn])
    void_ids: set = set()     # to'liq teskari qilinsa `void` bo'ladigan kogortalar

    for idx, ln in enumerate(data.lines):
        prod = products[pid_of[str(ln.purchase_item_id)]]
        lines = [(r.stock_batch_id, r.qty) for r in ln.reverse]
        # ⚠️  PARTIYA SHU QABULNIKI BO'LISHI SHART. `lot_writeoff.validate` faqat
        #     mahsulot/filialni biladi — boshqa hujjatning kogortasi bu yerdan
        #     JIMGINA kamayib ketardi.
        for bid, _qty in lines:
            b = batches.get(str(bid))
            if b is not None and str(b.receiving_id or "") != str(rec.id):
                raise CorrectionError(
                    400, f"Partiya bu qabulga tegishli emas: {bid}")
        # ⚠️  `reverse` BO'SH BO'LISHI MUMKIN — bu SOF QO'SHIMCHA (hujjatda 10 deb
        #     yozilgan, aslida 12 kelgan). `lot_writeoff.validate` bo'sh ro'yxatni
        #     «partiyalarni ANIQ ko'rsating» deb rad etadi — u CHIQARISH uchun
        #     yozilgan va bo'sh tanlov u yerda haqiqatan xato. Bu yerda esa
        #     teskari qilinadigan narsa YO'Q, shu bois tekshiruv ham kerak emas.
        plan: list = []
        try:
            if lines:
                plan = LW.validate(
                    batches, lines, company_id=emp.company_id, product_id=prod.id,
                    branch_id=branch.id,
                    total_qty=sum((_q3(q) for _b, q in lines), Decimal("0")))
        except LW.LotSelectionError as e:
            # ⚠️  QOLDIQ CHEGARASI — BARQAROR KOD BILAN 409, qolgani 400. Sababni
            #     MATNDAN emas, HOLATDAN aniqlaymiz: xabar bir harf o'zgarsa
            #     tasnif jimgina buzilardi.
            for bid, qty in lines:
                b = batches.get(str(bid))
                if b is not None and _q3(b.remaining_qty) < _q3(qty):
                    raise CorrectionError(
                        409, f"'{prod.name}': partiyada {_q3(b.remaining_qty)} qoldi, "
                             f"{_q3(qty)} teskari qilinmoqda — jismoniy partiya "
                             f"MANFIYGA tushmaydi.",
                        code=EC.LOT_CORRECTION_EXCEEDS_REMAINING) from e
            raise CorrectionError(400, str(e)) from e

        if ln.replace:
            # ── IDENTIFIKATSIYA TUZATISHI: kogorta TEGILMAGAN bo'lishi SHART ──
            for b, _q in plan:
                if not untouched(b, sums.get(str(b.id))):
                    raise CorrectionError(
                        409, f"'{prod.name}': partiyadan {consumed(sums.get(str(b.id)))} "
                             f"dona allaqachon harakatlangan — uning partiya raqami, "
                             f"muddati va tannarxini tuzatib bo'lmaydi. Tegilgan "
                             f"kogortada faqat MIQDORNI teskari qilish mumkin.",
                        code=EC.LOT_CORRECTION_CONSUMED)
            try:
                lots = LR.validate_line(
                    db, emp.company_id, branch.id, prod,
                    # ⚠️  XOM QIYMAT — KVANTLANMAGAN. `validate_line` ichida
                    #     `_uch_xona` uchtadan ortiq kasr xonasini RAD etadi; bu
                    #     yerda `_q3` bilan oldindan yaxlitlansa, darvoza HECH
                    #     QACHON ishlamasdi va 9.2345 jimgina 9.235 bo'lib
                    #     yozilardi (kirim yo'lida esa 400 beriladi).
                    sum((Decimal(str(x.qty)) for x in ln.replace), Decimal("0")),
                    [LR.LotIn(qty=Decimal(str(x.qty)), expiry_date=x.expiry_date,
                              batch_number=x.batch_number,
                              unit_cost=(_c2(x.unit_cost) if x.unit_cost is not None
                                         else None))
                     for x in ln.replace], now)
            except LR.LotPayloadError as e:
                raise CorrectionError(400, str(e)) from e
            except LP.TimezoneNotConfigured as e:
                raise CorrectionError(409, str(e)) from e
            new_lots.append((idx, ln, prod, lots))

        for b, q in plan:
            # ⚠️  `void` DALILI HOZIR YIG'ILADI. `lot_writeoff.apply` har partiyaga
            #     `stock_movement_lot_allocations` qatorini YOZADI — undan KEYIN
            #     hech bir kogorta «tegilmagan» ko'rinmaydi.
            if untouched(b, sums.get(str(b.id))) and _q3(b.remaining_qty) == _q3(q):
                void_ids.add(str(b.id))
        plans.setdefault(str(prod.id), []).extend(plan)

    # ── 9) TUZATISH SARLAVHASI — IDEMPOTENTLIKNING TRANZAKSION KAFOLATI ─────
    corr = ReceivingCorrection(
        id=_uuid.uuid4(), company_id=emp.company_id, receiving_id=rec.id,
        purchase_id=pur.id, branch_id=branch.id, employee_id=emp.id,
        reason=data.reason.strip(), client_uuid=data.client_uuid, request_hash=h,
        reversed_total=Decimal("0"), replaced_total=Decimal("0"),
        delta_total=Decimal("0"), payload=canonical(receiving_id, data), created_at=now)
    db.add(corr)
    # ANIQ flush: noyob indeks to'qnashuvi AYNAN shu qadamda chiqadi va hodisa
    # qatorlaridan OLDIN sarlavha bazaga tushadi (`lot_resolution` bilan AYNI).
    db.flush()

    # ── 10) TESKARI YOZUV VA O'RNIGA QO'YISH — MAHSULOT BO'YICHA ────────────
    reversed_total = Decimal("0")
    replaced_total = Decimal("0")
    made: list = []
    for pid in pids:
        key = str(pid)
        prod = products[pid]
        inv = invs[key]
        plan = plans.get(key, [])
        rev_qty = sum((q for _b, q in plan), Decimal("0"))
        if rev_qty > 0:
            new_qty = _q3(inv.qty) - rev_qty
            if new_qty < 0:
                # `purchases._reconcile` bilan AYNI matn va AYNI sabab.
                raise CorrectionError(
                    400, f"Ombor qoldig'i yetarli emas: {prod.name} (qoldiq {_q3(inv.qty)})")
            inv.qty = new_qty
            inv.updated_at = now
            mv_rev = _uuid.uuid4()
            mv = StockMovement(
                id=mv_rev, product_id=pid, branch_id=branch.id,
                type=MovementType.adjustment, qty=-rev_qty,
                unit_cost=None, balance_after=inv.qty, ref_type=REF_TYPE,
                ref_id=corr.id, employee_id=emp.id, created_at=now)
            db.add(mv)
            # Harakat qatori allokatsiya FK'sidan OLDIN mavjud bo'lishi SHART.
            db.flush()
            cost = LW.apply(db, plan, movement_id=mv_rev, company_id=emp.company_id,
                            product_id=pid, now=now)
            reversed_total += cost
            # ⚠️  AGREGAT harakatning tannarxi — ANIQ yig'indidan HOSILA (teskarisi
            #     emas): yaxlitlangan o'rtachani qayta ko'paytirish partiya
            #     tafsiloti bilan tiyinlarda ajralardi. Tafsilot
            #     `stock_movement_lot_allocations` da.
            mv.unit_cost = _c2(cost / rev_qty)
            # ⚠️  `void` — QABUL BEKOR QILINGAN kogorta; u miqdor TASHIMAYDI va
            #     `remaining_qty == 0` bo'lishi SHART (`stock_invariant` izohi, baza
            #     majburlamaydi). Shart aynan shu yerda tekshiriladi: `apply` dan
            #     keyin qoldiq noldan farq qilsa kogorta `depleted` bo'lib qoladi.
            for b, _q in plan:
                if str(b.id) in void_ids and _q3(b.remaining_qty) == 0:
                    b.status = SI.VOID

        add_qty, add_cost = Decimal("0"), Decimal("0")
        for _idx, _ln, _lprod, _lots in new_lots:
            if _lprod.id != pid:
                continue
            # ⚠️  YANGI HUJJAT KALITI. `doc_key` tuzatish id'siga bog'lanadi: asl
            #     qabulning `client_uuid` i bilan yozilsa `create_lots` MAVJUD
            #     kogortani QAYTARIB, tuzatish jimgina hech narsa qilmasdi
            #     (`ux_lot_intake_key` ayni kalitni ikkinchi marta yozdirmaydi).
            for b in LR.create_lots(
                    db, company_id=emp.company_id, branch_id=branch.id, product=_lprod,
                    lots=_lots, doc_key=f"corr:{corr.id}", line_index=_idx,
                    source_type=LR.SOURCE_CORRECTION, default_cost=_c2(_ln.unit_cost),
                    now=now, receiving_id=rec.id, supplier_id=pur.supplier_id):
                add_qty += _q3(b.received_qty)
                add_cost += _c2(_q3(b.received_qty) * _c2(b.unit_cost))
                made.append(b)
        if add_qty > 0:
            replaced_total += add_cost
            inv.qty = _q3(inv.qty) + add_qty
            inv.updated_at = now
            if inv.qty > _q3(inv.min_qty or 0):
                inv.low_alerted = False   # min ustiga chiqdi — keyingi tushishda ogohlantiriladi
            db.add(StockMovement(
                id=_uuid.uuid4(), product_id=pid, branch_id=branch.id,
                type=MovementType.purchase_in, qty=add_qty,
                unit_cost=_c2(add_cost / add_qty), balance_after=inv.qty,
                ref_type=REF_TYPE, ref_id=corr.id, employee_id=emp.id, created_at=now))

    reversed_total = _guard_total(reversed_total, "Teskari qilingan summa")
    replaced_total = _guard_total(replaced_total, "O'rniga qo'yilgan summa")
    delta_total = _guard_total(replaced_total - reversed_total, "Tuzatish summasi")
    corr.reversed_total = reversed_total
    corr.replaced_total = replaced_total
    corr.delta_total = delta_total

    # ── 11) HUJJAT SUMMALARI ────────────────────────────────────────────────
    #  ⚠️  `purchase_items` TEGILMAYDI: ular ASLIDA nima yozilganining yozuvi.
    #      Faqat HOSILA pul maydonlari siljiydi.
    old_total = _c2(pur.total)
    paid = _c2(pur.paid_amount or 0)
    new_total = _guard_total(old_total + delta_total, "Hujjat jami summasi")
    if new_total < 0:
        raise CorrectionError(
            409, "Tuzatish hujjat jamini MANFIY qilardi — amal bajarilmadi. "
                 "Hujjatni qo'llab-quvvatlash bilan ko'rib chiqing.")
    db.flush()
    # Hujjat TO'LIQ teskari qilindimi: bu qabulning birorta kogortasida qoldiq yo'q.
    fully_reversed = db.execute(select(StockBatch.id).where(
        StockBatch.company_id == emp.company_id,
        StockBatch.receiving_id == rec.id,
        StockBatch.remaining_qty > 0).limit(1)).first() is None

    pur.subtotal = new_total
    pur.total = new_total
    cancelled = False
    if new_total == 0 and fully_reversed:
        pur.status = PurchaseStatus.cancelled
        pur.deleted_at = now
        cancelled = True
    elif not _charged:
        # QA PR-004: naqd (received) xarid ledgerga charge yozmagan; `paid_amount`
        # kassa artefakti. Uni `partial/debt` qilish soxta qarz yaratib,
        # `pay_supplier` FIFO'sini buzardi.
        pur.status = PurchaseStatus.received
        pur.paid_amount = new_total
    elif new_total <= paid:
        pur.status = PurchaseStatus.received
    elif paid > 0:
        pur.status = PurchaseStatus.partial
    else:
        pur.status = PurchaseStatus.debt

    # ── 12) YETKAZIB BERUVCHI QARZI ─────────────────────────────────────────
    #  ⚠️  `charge` QATORI QO'SHILMAYDI VA OLINMAYDI. Uchta kassa migratsiyasi
    #      quyi tizimi `ref_type IN ('purchase','receiving') AND type='charge'`
    #      predikati bo'yicha «bu hujjat kassadan pul chiqarganmi» degan qarorni
    #      qabul qiladi — tuzatish o'sha predikatga kirsa, hujjat jimgina naqddan
    #      qarzga (yoki teskari) aylanardi.
    if _charged and delta_total != 0:
        sup.balance = _c2(sup.balance or 0) + delta_total
        db.add(SupplierLedger(
            supplier_id=sup.id, type=CreditTxnType.adjustment, amount=delta_total,
            balance_after=sup.balance, ref_type=REF_TYPE, ref_id=corr.id,
            created_at=now))

    # ── 13) KASSA — FAQAT NAQD HUJJAT ───────────────────────────────────────
    #  Kassa ledgeri APPEND-ONLY (DB trigger UPDATE/DELETE ni to'sadi): kamayish
    #  TESKARI yozuv bilan emas, QARAMA-QARSHI oyoq bilan aks ettiriladi.
    if not _charged:
        from app.services.cash import retrofit as _cr
        ret_amt = paid - new_total
        posted = None
        if ret_amt > 0:
            pr = PurchaseReturn(company_id=pur.company_id, purchase_id=pur.id,
                                branch_id=pur.branch_id, amount=ret_amt,
                                reason=REF_TYPE, employee_id=emp.id,
                                client_uuid=data.client_uuid, created_at=now)
            db.add(pr)
            db.flush()      # pr.id — ledger `source_id`; autoflush=False (Phase 2.5 darsi)
            posted = _cr.on_purchase_return(
                db, emp, branch_id=pur.branch_id, purchase_id=pur.id,
                purchase_return_id=pr.id, cash_amount=ret_amt,
                cash_account_id=(acc.id if acc is not None else None))
            if acc is not None:
                pr.cash_account_id = acc.id          # §5 audit identity
                db.add(pr)
        elif ret_amt < 0:
            posted = _cr.on_cash_purchase_increase(
                db, emp, branch_id=pur.branch_id, purchase_id=pur.id,
                extra_amount=(new_total - paid),
                cash_account_id=(acc.id if acc is not None else None))
        # ⚠️  «KASSA TEGILMAGAN HOLDA MUVAFFAQIYAT» — TAQIQ. Hook `None` qaytarishi
        #     kassa quyi tizimi FAOL bo'lganda AYBDOR holat: mos OUT oyog'i yo'q
        #     (legacy tenant) yoki custody hisobi yaroqsiz. Kassa quyi tizimi
        #     umuman yo'q bo'lsa (SQLite / xaritalanmagan filial) hook HAR DOIM
        #     `None` qaytaradi va bu NORMAL — u yerda ledger mavjud emas.
        if ret_amt != 0 and posted is None and _cr.dual_write_enabled(db):
            raise CorrectionError(
                409, "Naqd hujjat summasi o'zgardi, lekin kassa yozuvini yozib "
                     "bo'lmadi — tuzatish BEKOR qilindi. Kassa tegilmagan holda "
                     "'bajarildi' deb aytilmaydi; qo'llab-quvvatlashga murojaat qiling.",
                code=EC.LOT_CORRECTION_CASH_UNPOSTABLE)

    # ── 14) AUDIT + YAKUNIY DARVOZA ─────────────────────────────────────────
    #  ⚠️  `Receiving.final_items` QAYTA YOZILMAYDI: u qabul lahzasining surati,
    #      tuzatish esa ALOHIDA hodisa. Uni yangilash «nakladnoyda shunday
    #      yozilgan edi» degan savolga javob beradigan yagona yozuvni o'chirardi.
    audit_log(db, emp.id, "correct", "receiving", corr.id,
              after={"receiving_id": str(rec.id), "purchase_id": str(pur.id),
                     "client_uuid": str(data.client_uuid), "reason": corr.reason,
                     "lines": len(data.lines),
                     "reversed_total": float(reversed_total),
                     "replaced_total": float(replaced_total),
                     "delta_total": float(delta_total),
                     "lots_created": len(made), "lots_voided": len(void_ids),
                     "status": pur.status.value})
    if cancelled:
        audit_log(db, emp.id, "cancel", "purchase", pur.id,
                  after={"doc_no": pur.doc_no, "correction_id": str(corr.id),
                         "total": float(new_total)})

    db.flush()
    try:
        SI.assert_ok(db, emp.company_id, pids)
    except Exception as e:      # noqa: BLE001
        # ⚠️  ISTISNO MATNI OPERATORGA BERILMAYDI: `InvariantBroken` ichida xom
        #     UUID, `≠` belgisi va modul nomlari bor. Kontekst ROLLBACK'DAN OLDIN
        #     olinadi (rollback obyektlarni eskirtiradi).
        _ctx = (str(emp.company_id), str(branch.id), str(rec.id), str(corr.id))
        log.exception("tuzatish invarianti buzildi [%s]: company=%s branch=%s "
                      "receiving=%s correction=%s", EC.LOT_INVARIANT_BROKEN, *_ctx)
        db.rollback()
        raise CorrectionError(
            409, "Tuzatishni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal "
                 "BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.",
            code=EC.LOT_INVARIANT_BROKEN) from e

    resp = {"ok": True, "correction_id": str(corr.id), "receiving_id": str(rec.id),
            "purchase_id": str(pur.id),
            "reversed_total": float(reversed_total),
            "replaced_total": float(replaced_total),
            "delta_total": float(delta_total),
            "purchase_status": pur.status.value, "cancelled": cancelled}
    corr.response_json = json.dumps(resp, sort_keys=True)
    db.commit()
    return {**resp, "duplicate": False}
