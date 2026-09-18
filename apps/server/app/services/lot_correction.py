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
    ishlatilgan bo'lishi mumkin. Shu bois BESHALA kanal ham ALOHIDA
    tekshiriladi (`alloc_sums`): sotuv, harakat, qaytarish, QARZNI YOPISH va
    yopilgan qarzning qaytishi.

QULF TARTIBI (GLOBAL — yangi tartib O'YLAB TOPILMAYDI)
======================================================
  1. takror qidiruvi — QULFSIZ (tez yo'l)
  2. FK ota qatorlari FOR KEY SHARE (do'kon, filial, xodim, qabul, mahsulotlar)
  3. `Purchase` FOR UPDATE -> refresh -> `deleted_at` QAYTA tekshiruvi
  4. `Supplier` FOR UPDATE -> `Purchase` QAYTA refresh (QA PR-008)
  5. `Inventory` FOR UPDATE — mahsulot id'si bo'yicha TARTIBLANGAN
     (so'rov qatorlari + SHU QABULNING boshqa kogortalari — pastga qarang)
  6. `StockBatch` FOR UPDATE (`lot_writeoff.lock_batches`, id tartibida) —
     so'rovdagi partiyalar VA hujjatning qolgan kogortalari
  7. hodisa INSERT'lari -> flush
  8. naqd oyoq YOZILADIGAN bo'lsa `resolve_cash_custody` (qulfsiz o'qish)
  9. `stock_invariant.assert_ok` -> commit

⚠️  CUSTODY NEGA QULFLARDAN KEYIN. `cutover_guard.resolve_cash_custody` FAQAT
    `Setting`, `Shift` va `CashAccount` ni O'QIYDI — birorta qator QULFI
    OLMAYDI, shu bois uni `Inventory`/`StockBatch` dan KEYIN chaqirish yuqoridagi
    tartibni BUZMAYDI. Ilgari u HAR naqd hujjat uchun, `delta_total` MA'LUM
    BO'LISHIDAN OLDIN chaqirilardi: pul UMUMAN qimirlamaydigan tuzatish (muddat
    yoki partiya raqami xatosi) ham smenasiz menejerga `CUSTODY_REQUIRED` bilan
    yopilardi va Manager `cash_account_id` yubormagani uchun qayta urinishning
    YO'LI yo'q edi. `purchases.py` ham AYNI naqsh bilan ishlaydi: custody
    `_ret_amt` shoxlari ICHIDA aniqlanadi.

⚠️  QULF DOIRASI HUJJATNIKI, SO'ROVNIKI EMAS. «Hujjat TO'LIQ teskari qilindimi»
    qarori shu qabulning HAMMA kogortasiga qaraydi — shu bois ular ham
    QULFLANADI. Aks holda qaror hech kim qulflamagan qatorlarni o'qirdi va
    parallel yozuvchi hujjatni jimgina `cancelled` qilib qo'yardi (yoki haqli
    bekor qilishga to'sqinlik qilardi).

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
from app.models.inventory import (LotShortfallResolution, ReturnItemLotAllocation,
                                  ReturnItemResolutionAllocation, SaleItemLotAllocation,
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

# Kassa gardiga beriladigan amal nomi — YOZUVCHI va O'QISH ko'rinishi uchun BITTA
# qiymat (u kuzatuv jurnalida `op` bo'lib chiqadi; ikki xil nom bir amalni ikkiga
# bo'lib ko'rsatardi).
CASH_OPERATION = "receiving_correction_cash"


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


def _fits(value) -> tuple[Decimal, bool]:
    """`Numeric(14,2)` sig'imi — xom 500 (numeric overflow) o'rniga aniq 400.

    ⚠️  MATN CHAQIRUV JOYIDA TUG'ILADI, BU YERDA EMAS. Ilgari bu funksiya
        `f"{label} juda katta ..."` deb yozardi va lug'at `$1` o'rniga LOTIN
        yorlig'ini qo'yib, rus tilidagi jumla ichida o'zbekcha bo'lak
        qoldirardi. Endi har rad etish — ALOHIDA statik matn (`serverErrorsLots.ts`).
    """
    v = _c2(value)
    return v, (-NUMERIC_14_2_MAX <= v <= NUMERIC_14_2_MAX)


# ══ TEGILGANLIK DALILI ══════════════════════════════════════════════════════

# Kogortadan miqdor CHIQARADIGAN yoki unga QAYTARADIGAN kanallar — TARTIB
# `alloc_sums` qaytaradigan beshlik bilan AYNI. Ro'yxat to'liq bo'lishi SHART:
# tushib qolgan kanal kogortani «tegilmagan» ko'rsatib, uning identifikatsiyasini
# tuzatishga (ya'ni tarixda ALLAQACHON ishlatilgan narxni o'chirishga) yo'l ochadi.
_ALLOC_MODELS = (SaleItemLotAllocation,             # sotuv — chiqish
                 StockMovementLotAllocation,        # hisobdan chiqarish/sanoq/tuzatish — chiqish
                 ReturnItemLotAllocation,           # mijoz qaytarishi — kirish
                 LotShortfallResolution,            # partiya qarzini yopish — chiqish
                 ReturnItemResolutionAllocation)    # yopilgan qarzning qaytishi — kirish


def alloc_sums(db: Session, batch_ids) -> dict:
    """{partiya_id(str): (sotuv, harakat, qaytarish, yopish, yopish_qaytishi)}.

    ⚠️  BESHALA JADVAL HAM KERAK. `remaining_qty == received_qty` YOLG'IZ yolg'on
        guvoh: sotilib keyin qaytarilgan kogortada u AYNAN tiklanadi. Kirish
        kanallari ALOHIDA qaytariladi — ular «tegilgan» dalilini KAMAYTIRMAYDI.

    ⚠️  YOPISH KANALI (`lot_shortfall_resolutions`) UZOQ VAQT TUSHIB QOLGAN EDI.
        Qarzni yopish kogortadan miqdor OLADI va uning narxida COGS og'ishini
        TAN OLADI; tovar keyin qaytsa (`return_item_resolution_allocations`)
        qoldiq AYNAN tiklanadi va uchta eski jadvalda BIRORTA qator qolmaydi —
        ya'ni og'ishi allaqachon hisobga olingan kogorta «tegilmagan» bo'lib
        ko'rinardi va uni `void` qilib yuborish mumkin edi.
    """
    ids = [b for b in batch_ids if b is not None]
    out = {str(b): [Decimal("0")] * len(_ALLOC_MODELS) for b in ids}
    if not ids:
        return {}
    for i, model in enumerate(_ALLOC_MODELS):
        rows = db.execute(
            select(model.stock_batch_id, func.coalesce(func.sum(model.qty), 0))
            .where(model.stock_batch_id.in_(ids))
            .group_by(model.stock_batch_id)).all()
        for bid, total in rows:
            if str(bid) in out:
                out[str(bid)][i] = _q3(total)
    return {k: tuple(v) for k, v in out.items()}


def moved(sums) -> Decimal:
    """Kogortadan CHIQQAN miqdor: sotuv + harakat + qarz yopishi.

    ⚠️  QAYTISHLAR AYIRILMAYDI. Ilgari bu hisob qaytarishni sotuvdan ayirardi va
        sotilib-qaytarilgan kogortani rad etayotgan xabar operatorga «0 dona
        allaqachon harakatlangan» derdi — ya'ni xabar aynan o'zi aytayotgan
        sababni INKOR qilardi. «Tegilganlik» — GROSS harakat: qaytib kelgan
        tovar kogorta raqami va narxi tarixda ishlatilganini BEKOR QILMAYDI.
    """
    if not sums:
        return Decimal("0")
    sale, move, _ret, resolved, _res_ret = sums
    return _q3(sale) + _q3(move) + _q3(resolved)


def untouched(batch: StockBatch, sums) -> bool:
    """Kogorta IDENTIFIKATSIYASI hali tuzatilishi mumkinmi (tarixda ishlatilmaganmi)."""
    if _q3(batch.remaining_qty) != _q3(batch.received_qty):
        return False
    if not sums:
        return True
    return all(_q3(v) == 0 for v in sums)


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


def is_charged(db: Session, purchase, supplier) -> bool:
    """Hujjat ta'minotchi defteriga CHARGE yozganmi — ya'ni QARZ hujjatimi.

    ⚠️  YAGONA TA'RIF. Tuzatishning pul yo'li AYNAN shu javobga bog'langan: `True` ->
        ta'minotchi balansi siljiydi va KASSA UMUMAN qatnashmaydi (custody ham
        so'ralmaydi); `False` -> naqd oyoq yoziladi. O'qish ko'rinishi (`cash_custody`
        bloki) ham shu yerdan o'qiydi — ikki joyda ikki xil predikat bo'lsa, ekran
        operatorga kassa hisobini so'rab, server esa uni umuman ishlatmasdi.

    ⚠️  `Purchase.status` DAN HOSIL QILINMAYDI. To'liq to'langan qarz hujjati
        `received` bo'lib qoladi (`purchases.py` dagi `"payment"` maydoni aynan shu
        sababdan YOLG'ON gapiradi), holbuki u ledgerda CHARGE bilan yozilgan.

    ⚠️  `ref_type` IKKI xil bo'lishi mumkin: Manager xaridi 'purchase', mobil
        kredit-qabul 'receiving' (QA PR-001). Faqat 'purchase' izlash mobil manbali
        qarzni naqd deb ko'rsatardi."""
    if supplier is None:
        return False
    return db.query(SupplierLedger.id).filter(
        SupplierLedger.supplier_id == purchase.supplier_id,
        SupplierLedger.ref_type.in_(("purchase", "receiving")),
        SupplierLedger.ref_id == purchase.id,
        SupplierLedger.type == CreditTxnType.charge).first() is not None


def actor_open_shift(db: Session, emp):
    """Xodimning OCHIQ smenasi (yoki None) — custody rezolyutsiyasining kirish sharti.

    ⚠️  «XODIMNING» — filialning yoki kassaning EMAS. Custody qoidasi (§2) AYNI
        shu xodimning ochiq smenasiga qaraydi; boshqa kassirning smenasi bu yerga
        HECH QACHON kirmaydi (`cutover_guard` moduli izohi: «boshqa kassirning
        smenasi» — taqiqlangan taxminlar ro'yxatida)."""
    from app.models.enums import ShiftStatus as _ShSt
    from app.models.shifts import Shift as _Shift
    return (db.query(_Shift).filter(_Shift.cashier_id == emp.id,
                                    _Shift.status == _ShSt.open).first())


# ══ KASSA CUSTODY — O'QISH KO'RINISHI (§A.3) ════════════════════════════════
#
# ⚠️  SERVER HAL QILADI, EKRAN FAQAT CHIZADI. «Qaysi kassadan pul qaytadi?» degan
#     savolga javobni mijoz HISOBLAMAYDI: u yozuvchi bilan AYNI funksiyadan
#     (`cutover_guard.preview_cash_custody` -> `resolve_cash_custody`) o'qiladi.
#     Ikki joyda ikki xil hisob operatorga «mumkin» deb ko'rsatib, server 400
#     berardi — bu blok aynan shu ajralishni IMKONSIZ qiladi.
#
# ⚠️  BU DARVOZA EMAS. Blok HECH NARSANI taqiqlamaydi va HECH NARSANI ochmaydi:
#     yozuvchi o'z tekshiruvini baribir o'zi bajaradi. Blok yo'qolsa yoki
#     xato hisoblansa — eng yomoni operator noto'g'ri ko'rsatma ko'radi, pul
#     yo'li esa o'zgarmaydi.

MODE_NOT_APPLICABLE = "NOT_APPLICABLE"      # qarz hujjati — kassa UMUMAN qatnashmaydi
MODE_NOT_REQUIRED = "NOT_REQUIRED"          # pre-T0: server o'zi hal qiladi yoki legacy fallback
MODE_SERVER_RESOLVED = "SERVER_RESOLVED"    # ochiq smena kassasi — mijoz HECH NARSA yubormaydi
MODE_OPERATOR_MUST_CHOOSE = "OPERATOR_MUST_CHOOSE"   # smenasiz post-T0: hisob AYNAN tanlanadi
MODE_BLOCKED = "BLOCKED"                    # shu aktyor bu hujjatni tuzata olmaydi


def _account_out(acc) -> dict:
    """Kassa hisobining EKRANGA chiqadigan bo'lagi — id/type/code/currency, TAMOM.

    ⚠️  `label`, `terminal_id`, `branch_id`, `status` BERILMAYDI: bu blok
        `GET /tills` allaqachon har autentifikatsiyalangan xodimga ochib
        beradigan ma'lumotdan QAT'IY KAM bo'lishi shart (yangi oshkorlik yo'q)."""
    from app.services.cash import till_identity as _ti
    return {"id": str(acc.id), "type": str(acc.type),
            "code": _ti.account_checkout_code(acc), "currency": str(acc.currency)}


def custody_options(db: Session, company_id, branch_id) -> list:
    """HUJJAT filialining FAOL (ACTIVE) TILL va SAFE hisoblari — tanlov ro'yxati.

    ⚠️  FAQAT HUJJAT FILIALI. Pul qaytadigan joy hujjat qayerda yozilgan bo'lsa
        o'sha filialda; boshqa filial hisobi ro'yxatga tushsa, operator uni
        tanlab, server esa `CASH_CUSTODY_ACCOUNT_INVALID` bilan rad etardi.
    ⚠️  ARXIVLANGAN hisob ham ro'yxatga tushmaydi — AYNI sababdan.
    ⚠️  Kassa quyi tizimi yo'q bo'lsa (SQLite/dev) ro'yxat BO'SH: `CashAccount`
        jadvali u yerda UMUMAN mavjud emas va so'rov xom xato berardi."""
    from app.services.cash import retrofit as _cr
    from app.services.cash import till_identity as _ti
    if not _cr.cash_enabled(db):
        return []
    return [_account_out(a) for a in (list(_ti.list_tills(db, company_id, branch_id))
                                      + list(_ti.list_safes(db, company_id, branch_id)))]


def legacy_fallback_resolves(db: Session, company_id, branch_id) -> bool:
    """PRE-T0 da hisobsiz yozuv O'TADIMI — ya'ni legacy yo'l DRAWER topadimi.

    ⚠️  PRE-T0 «HISOB KERAK EMAS» DEGANI EMAS. `resolve_cash_custody` T0'gacha
        hisobsiz (None, False) qaytaradi va yozuvchi kassa oyog'ini
        `cash_account_id=None` bilan yozadi — o'shanda `retrofit._shift_ctx`
        drawer'ni O'ZI qidiradi (`resolve_till`). Bir filialda BIR NECHTA faol
        TILL bo'lsa u ATAYLAB hech nimani tanlamaydi (branch-default YO'Q),
        hook `None` qaytaradi va yozuvchi `LOT_CORRECTION_CASH_UNPOSTABLE`
        bilan RAD etadi — ekran esa «hech narsa kerak emas» deb turardi.
        Shu bois o'qish ko'rinishi AYNI resolverni chaqiradi.

    ⚠️  KASSA QUYI TIZIMI YO'Q BO'LSA — `True`. U yerda (SQLite/dev, xaritalanmagan
        filial) yozuvchi ham hech narsa yozmaydi va HECH QACHON rad etmaydi
        (`_correct_once` §13: rad etish FAQAT `dual_write_enabled` da)."""
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        return True
    return _cr.resolve_till(db, company_id, branch_id) is not None


def cash_custody_view(db: Session, emp, pur) -> dict:
    """`GET /purchases/{id}` uchun QO'SHIMCHA, faqat O'QISH bloki (§A.3).

    Qaytaradi: {mode, reason, resolved, options, branch}. Har rejim pastda.

    ⚠️  «PUL QIMIRLAYDIMI» QARORI BU YERDA EMAS. Server hujjat darajasidagi
        holatni aytadi; tuzatishning O'ZI pulni siljitadimi (`ret_amt != 0`) —
        bu operator qoralamasiga bog'liq va uni ekran hisoblaydi (§A.4). Server
        tomonda ham custody AYNAN shu shart ichida so'raladi (`_correct_once` §13).
    """
    from app.models.org import Branch
    from app.models.purchasing import Supplier
    from app.services.cash import cutover_guard as _cg
    branch = db.get(Branch, pur.branch_id)
    out = {"mode": MODE_NOT_APPLICABLE, "reason": None, "resolved": None, "options": [],
           "branch": ({"id": str(branch.id), "name": branch.name} if branch is not None
                      else None)}
    try:
        # R0 — QARZ hujjati: kassa oyog'i UMUMAN yozilmaydi, hisob ham so'ralmaydi.
        sup = db.get(Supplier, pur.supplier_id) if pur.supplier_id else None
        if is_charged(db, pur, sup):
            return out
        # Qaror YOZUVCHINING O'Z kodidan. `cash_account_id` ATAYLAB berilmaydi:
        # bu «hech narsa yubormasam nima bo'ladi?» degan savol, ya'ni ekran
        # ko'rsatishi kerak bo'lgan boshlang'ich holat.
        #
        # ⚠️  PRE-T0 DA HAM YUGURTIRILADI. Ilgari `enforcement_active` yolg'on
        #     bo'lsa blok darhol NOT_REQUIRED qaytarardi — holbuki T0'gacha ham
        #     naqd oyoq uchun DRAWER topilishi shart va ko'p-TILL filialda
        #     legacy fallback uni ATAYLAB topmaydi (`legacy_fallback_resolves`).
        #     Ekran «hech narsa kerak emas» deb turardi, yozuvchi esa
        #     `LOT_CORRECTION_CASH_UNPOSTABLE` bilan rad etardi.
        shift = actor_open_shift(db, emp)
        acc, _enforced, code = _cg.preview_cash_custody(
            db, company_id=emp.company_id, branch_id=pur.branch_id,
            operation=CASH_OPERATION, shift=shift, cash_account_id=None)
        if not _cg.enforcement_active(db, emp.company_id):
            # R8/R9 — pre-T0. Server smenadan hal qilgan (acc) yoki legacy
            # fallback drawer topadigan bo'lsa ekran HECH NARSA ko'rsatmaydi va
            # yubormaydi (bugungi Fayzan aynan shu holatda: `cutover_at` yo'q).
            if code is None and (acc is not None
                                 or legacy_fallback_resolves(db, emp.company_id,
                                                             pur.branch_id)):
                out["mode"] = MODE_NOT_REQUIRED
                return out
            # ⚠️  TANLOV FAQAT U HAQIQATAN QUTQARADIGAN HOLATDA. Aktyorning ochiq
            #     smenasi kassaga BOG'LANGAN bo'lsa (`shift.till_id` bor), lekin
            #     o'sha kassa yaroqsiz bo'lsa — `resolve_cash_custody` smena
            #     shoxida hisobni RAD etadi (TILL_SHIFT_MISMATCH), ya'ni aniq
            #     hisob ham yordam bermaydi: bu BLOKLANGAN holat, picker emas.
            if code is None and getattr(shift, "till_id", None) is None:
                out["mode"] = MODE_OPERATOR_MUST_CHOOSE
                out["reason"] = _cg.ERR_CUSTODY_REQUIRED
                out["options"] = custody_options(db, emp.company_id, pur.branch_id)
                return out
            out["mode"] = MODE_BLOCKED
            out["reason"] = code or _cg.ERR_CUSTODY_INVALID
            return out
        if code is None and acc is not None:
            out["mode"] = MODE_SERVER_RESOLVED          # R2 — smenaning kassasi
            out["resolved"] = _account_out(acc)
            return out
        if code == _cg.ERR_CUSTODY_REQUIRED:
            out["mode"] = MODE_OPERATOR_MUST_CHOOSE     # R6 — smenasiz post-T0
            out["reason"] = code
            out["options"] = custody_options(db, emp.company_id, pur.branch_id)
            return out
        # R4 (begona filial smenasi) / R5 (till'siz legacy smena) va boshqa kassa
        # rad etishlari: TANLOV KO'RSATILMAYDI — explicit hisob ham qutqarmaydi
        # (`resolve_cash_custody`: smena shoxi hisobdan OLDIN hal bo'ladi).
        out["mode"] = MODE_BLOCKED
        out["reason"] = code or _cg.ERR_LEDGER_UNAVAILABLE
        return out
    except Exception:       # noqa: BLE001
        # ⚠️  FAIL-CLOSED: kutilmagan xato «hisob kerak emas» degan MA'NONI bermaydi.
        #     Ayni paytda butun hujjat sahifasi 500 bo'lib ketmaydi ham — blok
        #     QO'SHIMCHA maydon, u tufayli kirimni ko'rish imkoni yo'qolmasin.
        log.exception("cash_custody bloki hisoblanmadi: company=%s purchase=%s",
                      emp.company_id, pur.id)
        # Tranzaksiya buzilgan bo'lishi mumkin (masalan mavjud bo'lmagan jadval) —
        # uni tozalamasak, hujjat sahifasining QOLGAN o'qishlari ham yiqilardi.
        # Bu yo'lda YOZUV yo'q, shu bois qaytarishga hech narsa yo'q.
        db.rollback()
        return {"mode": MODE_BLOCKED, "reason": _cg.ERR_LEDGER_UNAVAILABLE,
                "resolved": None, "options": [], "branch": out["branch"]}


# ══ IKKI XIL PUL ASOSI — ADASHTIRMASLIK UCHUN ALOHIDA ═══════════════════════
#
# COGS (ZAXIRA) ASOSI — Σ miqdor × PARTIYA narxi (`StockBatch.unit_cost`).
#     Harakatning `unit_cost` i va `stock_movement_lot_allocations` suratlari
#     AYNAN shundan chiqadi: ular «qaysi jismoniy tovar qancha turardi» degan
#     savolga javob beradi.
#
# HUJJAT ASOSI — Σ miqdor × KOGORTANING HUJJAT NARXI (`doc_unit_cost`).
#     `Purchase.total` ning o'zi AYNAN shu asosda tug'ilgan (`receiving.commit`:
#     Σ qty × unit_cost), shu bois hujjat jami, `paid_amount`, ta'minotchi
#     tuzatishi va kassa oyog'i ham SHU asosda harakat qilishi SHART.
#
# ⚠️  IKKALASI BIR-BIRINING O'RNIGA ISHLATILMAYDI. Partiyaning O'Z narxi qator
#     narxidan farq qilsa (kirimda `lots[].unit_cost` berilgan), COGS asosi bilan
#     hujjatni kamaytirish TO'LIQ teskari qilingan hujjatda ham ta'minotchida
#     FANTOM qarz qoldirardi (yoki hujjat jamini MANFIYGA tushirib, to'liq
#     teskari qilishni UMUMAN imkonsiz qilardi).

def doc_unit_cost(batch, line_unit_cost) -> Decimal:
    """Bitta KOGORTANING hujjat asosidagi birlik narxi — YAGONA qoida.

    ⚠️  TUZATISH TUG'DIRGAN KOGORTANING HUJJAT QIYMATI — O'SHA TUZATISH KITOBGA
        OLGAN NARX, ya'ni kogortaning O'Z `unit_cost` i. Sabab oddiy: hujjat
        jamini (`Purchase.total`) va pulni AYNAN o'sha narx siljitgan
        (`doc_replace_value` — kogorta tug'ilgan narx), va `purchase_items`
        ATAYLAB qayta yozilmaydi (ular «aslida nima yozilgan» ning yozuvi).
        Bunday kogortani KEYIN asl qator narxida teskari qilish:
          · oshirib-keyin-teskari juftida kassadan chiqqan pulni tovarsiz
            QOLDIRARDI (chiqqan 15000, qaytgan 10000, qo'lda 0 dona);
          · kamaytirib-keyin-teskari juftida hujjat jamini MANFIYGA tushirib,
            to'liq bekor qilishni UMUMAN imkonsiz qilardi.
        Qolgan hamma kogorta (`purchase`/`receiving`/`legacy`/`adjustment`)
        hujjatga AYNAN qator narxida tushgan, shu bois ular qator narxida
        teskari qilinadi.

    ⚠️  COGS ASOSI BU YERDAN OLINMAYDI. Harakatning `unit_cost` i va
        `stock_movement_lot_allocations` suratlari HAR DOIM `StockBatch.unit_cost`
        dan chiqadi (`lot_writeoff.apply`) — bu funksiya ularga TEGMAYDI. Ikkisi
        tuzatish kogortasida TENG bo'lib chiqadi (u ham narxni hujjatdan oladi),
        lekin bu TASODIF emas, TA'RIF: kogortaning e'lon qilingan narxi.
    """
    if str(getattr(batch, "source_type", "") or "") == LR.SOURCE_CORRECTION:
        return _c2(batch.unit_cost)
    return _c2(line_unit_cost)


def doc_reverse_value(plan, line_unit_cost) -> Decimal:
    """Teskari yozuvning HUJJAT asosidagi ANIQ qiymati — KOGORTA bo'yicha.

    `plan` — `lot_writeoff.validate` qaytargan [(StockBatch, miqdor)] ro'yxati.

    ⚠️  QATOR × QATOR NARXI EMAS, KOGORTA × KOGORTA HUJJAT NARXI. Bitta qatorda
        turli manbali kogortalar (asl qabul + oldingi tuzatish qo'ygan) birga
        kelishi mumkin; ularni bitta narx bilan ko'paytirish yuqoridagi ikkala
        buzilishni tug'dirardi.

    ⚠️  KVANTLASH BU YERDA EMAS. `Purchase.total` butun hujjat uchun BIR MARTA
        yaxlitlanadi (`receiving.commit` xom yig'indini `Numeric(14,2)` ga
        yozadi), shu bois teskari yozuv ham BIR MARTA — hamma qator yig'ilgandan
        KEYIN — yaxlitlanishi shart. Qatorma-qator yaxlitlash ikkita tiyindan
        kichik qatorni to'liq teskari qilganda 0.01 ortiqcha ayirib, hujjat
        jamini MANFIY qilardi (va tuzatish rad etilardi).
    """
    return sum((_q3(q) * doc_unit_cost(b, line_unit_cost) for b, q in plan),
               Decimal("0"))


def doc_replace_value(lots, line_unit_cost) -> Decimal:
    """O'rniga qo'yishning HUJJAT asosidagi ANIQ qiymati — HAR PARTIYA bo'yicha.

    `lots` — (miqdor, partiya narxi | None) juftlari; narx berilmasa qatorning
    TUZATILGAN narxi ishlatiladi.

    ⚠️  PARTIYA NARXI BERILSA — AYNAN O'SHA NARX, QATORNIKI EMAS. Tug'iladigan
        kogorta `unit_cost` ini ham AYNAN shundan oladi (`create_lots`:
        partiyaning o'z narxi, bo'lmasa `default_cost`), `doc_unit_cost` esa
        keyinchalik uni AYNAN shu narxda teskari qiladi. Ikki tomon ajralsa,
        tuzatish qo'ygan kogortani TO'LIQ teskari qilish hujjatni nolga
        tushirmasdi — ya'ni tuzatilayotgan nuqson boshqa eshikdan qaytardi.

    ⚠️  ODDIY QABUL YO'LIDA BU QOIDA EMAS (`receiving.commit`: hujjat jami Σ qty ×
        QATOR narxi, partiya narxi esa faqat COGS uchun) — shu bois qabul
        kogortasining hujjat narxi qator narxi bo'lib qoladi (`doc_unit_cost`).
        Tuzatish esa hujjatning O'ZINI qayta e'lon qiladi va uning har partiyasi
        hujjatga e'lon qilingan narxida tushadi."""
    return sum((_q3(q) * _c2(c if c is not None else line_unit_cost)
                for q, c in lots), Decimal("0"))


def deltas_by_product(db: Session, company_id, purchase_ids) -> dict:
    """{mahsulot_id(str): tuzatishlar jami deltasi} — HUJJAT asosida.

    Hisobotlar `purchase_items` ni yig'adi, lekin tuzatish o'sha qatorlarga
    ATAYLAB tegmaydi (ular «aslida nima yozilgan» ning yozuvi) — faqat hosila
    `Purchase.total` siljiydi. Shu bois hisobot ikki xil raqam ko'rsatardi:
    hujjat jami TUZATILGAN, mahsulot ustuni esa TUZATILMAGAN. Delta shu yerda,
    `_correct_once` bilan AYNI hisobdan (`doc_unit_cost`) qayta tiklanadi.

    ⚠️  KOGORTALAR PAYLOAD'DAN QAYTA O'QILADI. Teskari yozuv qiymati kogorta
        MANBASIGA bog'liq (`doc_unit_cost`), shu bois bu yerda ham AYNI
        partiyalar yuklanadi: qator narxi bilan ko'paytirish hisobotni hujjat
        jamidan yana ajratib yuborardi — ya'ni tuzatilgan oldingi tuzatish
        mahsulot ustunida boshqa raqam berardi.
    """
    ids = [p for p in purchase_ids if p is not None]
    if not ids:
        return {}
    rows = db.execute(select(ReceivingCorrection.payload).where(
        ReceivingCorrection.company_id == company_id,
        ReceivingCorrection.purchase_id.in_(ids))).all()
    if not rows:
        return {}
    items = {str(it.id): it for it in db.query(PurchaseItem)
             .filter(PurchaseItem.purchase_id.in_(ids)).all()}
    bids = set()
    for (payload,) in rows:
        for ln in ((payload or {}).get("lines") or []):
            for x in (ln.get("reverse") or []):
                try:
                    bids.add(_uuid.UUID(str(x.get("stock_batch_id"))))
                except (ValueError, AttributeError, TypeError):
                    # ⚠️  BUZILGAN PAYLOAD HISOBOTNI YIQITMAYDI. Topilmagan kogorta
                    #     `doc_unit_cost` da qator narxiga tushadi — bu hujjatning
                    #     eski (tuzatishsiz) asosi, ya'ni TAXMIN emas.
                    continue
    batches = ({str(b.id): b for b in db.query(StockBatch).filter(
        StockBatch.company_id == company_id,
        StockBatch.id.in_(sorted(bids, key=str))).all()} if bids else {})
    out: dict = {}
    for (payload,) in rows:
        for ln in ((payload or {}).get("lines") or []):
            it = items.get(str(ln.get("purchase_item_id")))
            if it is None:
                continue        # qator o'chirilgan — delta'ni TAXMIN QILMAYMIZ
            plan = [(batches.get(str(x.get("stock_batch_id"))), x.get("qty"))
                    for x in (ln.get("reverse") or [])]
            rv = doc_reverse_value(plan, it.unit_cost)
            pv = doc_replace_value(
                [(x.get("qty"), x.get("unit_cost")) for x in (ln.get("replace") or [])],
                ln.get("unit_cost") or 0)
            key = str(it.product_id)
            out[key] = out.get(key, Decimal("0")) + (pv - rv)
    return out


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


def _custody(db: Session, emp, *, branch_id, cash_account_id):
    """§2 CUSTODY — naqd oyoq HAQIQATAN yoziladigan bo'lsa CHAQIRILADI.

    ⚠️  KECHIKTIRISH ATAYLAB (modul izohidagi qulf tartibiga qarang). Bu yerda
        hech qanday qator QULFLANMAYDI (`Setting`, `Shift`, `CashAccount` —
        oddiy o'qish), shu bois chaqiruvni `Inventory`/`StockBatch` qulflaridan
        keyinga surish tartibni buzmaydi. Pul qimirlamaydigan tuzatish esa
        kassa hisobini UMUMAN so'ramaydi — aks holda smenasiz menejer muddat
        xatosini ham tuzata olmasdi (`purchases.py` bilan AYNI naqsh).
    """
    from app.services.cash import cutover_guard as _cg
    sh = actor_open_shift(db, emp)
    # §2 CUSTODY: smena bor -> shift.till_id; smenasiz -> so'rovdagi EXPLICIT
    # `cash_account_id`. Filial/kassir bo'yicha TAXMIN QILINMAYDI.
    acc, _ = _cg.resolve_cash_custody(
        db, company_id=emp.company_id, branch_id=branch_id,
        operation=CASH_OPERATION, shift=sh, cash_account_id=cash_account_id)
    return acc


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

    # ⚠️  QARZ HUJJATIMI — `is_charged` YAGONA ta'rifi (o'qish ko'rinishi ham AYNI
    #     funksiyani chaqiradi, shu bois ekran bilan yozuvchi ajralib keta olmaydi).
    _charged = is_charged(db, pur, sup)

    # ── 6) NAQD CUSTODY — §13 GA KECHIKTIRILGAN (modul izohi: QULF TARTIBI) ──
    #  Kassa hisobi FAQAT naqd oyoq yoziladigan bo'lsa so'raladi; bu yerda
    #  `delta_total` hali NOMA'LUM.

    # ── 7) QOLDIQ QATORLARI — mahsulot id'si bo'yicha TARTIBLANGAN FOR UPDATE ──
    #  ⚠️  DOIRA HUJJATNIKI. «Hujjat TO'LIQ teskari qilindimi» qarori shu
    #      qabulning HAMMA kogortasiga qaraydi, shu bois ularning mahsulotlari
    #      ham (so'rovda yo'q bo'lsa ham) shu yerda qulflanadi — qaror faqat
    #      TRANZAKSIYA NAZORAT QILADIGAN qatorlarga tayanishi shart.
    doc_rows = db.execute(select(StockBatch.id, StockBatch.product_id).where(
        StockBatch.company_id == emp.company_id,
        StockBatch.receiving_id == rec.id)).all()
    invs: dict = {}
    for pid in sorted({r[1] for r in doc_rows} | set(pids), key=str):
        inv = LR.inventory_for_update(db, pid, branch.id)
        if inv is None:
            # Qoldiq qatorisiz mahsulot FAQAT so'rov qatorlari uchun to'siq:
            # hujjatning begona kogortasi bu tuzatishda o'zgarmaydi.
            if pid in pids:
                raise CorrectionError(
                    409, f"'{products[pid].name}': qoldiq qatori topilmadi — tuzatib "
                         f"bo'lmaydi")
            continue
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
    #  ⚠️  SO'ROVDAGILAR + HUJJATNING QOLGAN KOGORTALARI birgalikda, BITTA
    #      tartiblangan o'tishda qulflanadi: «to'liq teskari qilindimi» qarori
    #      shu qatorlarga tayanadi va ular tranzaksiya nazoratida bo'lishi shart.
    batches = LW.lock_batches(db, [r.stock_batch_id for ln in data.lines
                                   for r in ln.reverse] + [bid for bid, _p in doc_rows])
    doc_batches = [batches[str(bid)] for bid, _p in doc_rows if str(bid) in batches]
    sums = alloc_sums(db, [b.id for b in batches.values()])

    now = datetime.now(timezone.utc)
    plans: dict = {}          # product_id(str) -> [(StockBatch, Decimal)]
    new_lots: list = []       # (line_index, LineIn, product, [LotIn], received_at)
    void_ids: set = set()     # to'liq teskari qilinsa `void` bo'ladigan kogortalar
    # HUJJAT asosi (ANIQ, kvantlanmagan) — `doc_unit_cost` izohiga qarang.
    doc_reversed = Decimal("0")
    doc_replaced = Decimal("0")

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
                        409, f"'{prod.name}': partiyadan {moved(sums.get(str(b.id)))} "
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
            # ⚠️  FIFO O'RNI SAQLANADI. Qator AYNAN bitta kogortani teskari qilsa,
            #     o'rniga qo'yilgan partiya o'sha kogortaning `received_at` ini
            #     oladi: sof identifikatsiya tuzatishi (raqam/muddat xatosi)
            #     tovarni FIFO/FEFO navbatining OXIRIGA surib, keyingi
            #     sotuvlarning tannarxini JIMGINA o'zgartirmasin. Bir nechta
            #     kogorta bir qatorda birlashsa qaysi sana ekani NOMA'LUM —
            #     unda `now` (taxmin qilinmaydi). `created_at` HAR DOIM hozir.
            rcv_at = plan[0][0].received_at if len(plan) == 1 else None
            new_lots.append((idx, ln, prod, lots, rcv_at))

        # HUJJAT asosi — IKKALA tomon shu yerda, AYNI hisobdan: teskari yozuv
        # HAR KOGORTANING hujjat narxida (`doc_unit_cost` — tuzatish tug'dirgan
        # kogortada uning O'Z narxi, qolganida qator narxi), o'rniga qo'yish esa
        # qatorning TUZATILGAN narxida.
        # ⚠️  MIQDOR `validate_line` DAN KEYIN kvantlanadi: u uchtadan ortiq kasr
        #     xonasini RAD etadi, ya'ni bu yerda `_q3` hech narsani yashirmaydi.
        doc_reversed += doc_reverse_value(plan, items[ln.purchase_item_id].unit_cost)
        doc_replaced += doc_replace_value(
            [(x.qty, x.unit_cost) for x in ln.replace], ln.unit_cost)

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
            # ⚠️  COGS ASOSI, HUJJAT ASOSI EMAS (`doc_unit_cost` izohi): `apply`
            #     ANIQ Σ miqdor × PARTIYA narxini qaytaradi va u FAQAT harakat
            #     tannarxiga ketadi. Hujjat jami esa KOGORTANING HUJJAT narxida
            #     siljiydi (odatdagi kogortada — qator narxi).
            cost = LW.apply(db, plan, movement_id=mv_rev, company_id=emp.company_id,
                            product_id=pid, now=now)
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
        for _idx, _ln, _lprod, _lots, _rcv_at in new_lots:
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
                    now=now, received_at=_rcv_at, receiving_id=rec.id,
                    supplier_id=pur.supplier_id):
                add_qty += _q3(b.received_qty)
                # COGS asosi (harakat tannarxi uchun) — ANIQ, kvantlanmagan.
                add_cost += _q3(b.received_qty) * _c2(b.unit_cost)
                made.append(b)
        if add_qty > 0:
            inv.qty = _q3(inv.qty) + add_qty
            inv.updated_at = now
            if inv.qty > _q3(inv.min_qty or 0):
                inv.low_alerted = False   # min ustiga chiqdi — keyingi tushishda ogohlantiriladi
            db.add(StockMovement(
                id=_uuid.uuid4(), product_id=pid, branch_id=branch.id,
                type=MovementType.purchase_in, qty=add_qty,
                unit_cost=_c2(add_cost / add_qty), balance_after=inv.qty,
                ref_type=REF_TYPE, ref_id=corr.id, employee_id=emp.id, created_at=now))

    # ⚠️  BIR MARTA KVANTLASH — `doc_reverse_value` izohiga qarang: `Purchase.total`
    #     ning o'zi xom yig'indidan bir marta yaxlitlangan, shu bois teskari
    #     yozuv ham shunday yaxlitlansa TO'LIQ teskari qilish AYNAN nolga tushadi.
    reversed_total, _ok = _fits(doc_reversed)
    if not _ok:
        raise CorrectionError(
            400, "Teskari qilingan summa juda katta — miqdor yoki narxni tekshiring")
    replaced_total, _ok = _fits(doc_replaced)
    if not _ok:
        raise CorrectionError(
            400, "O'rniga qo'yilgan summa juda katta — miqdor yoki narxni tekshiring")
    delta_total, _ok = _fits(replaced_total - reversed_total)
    if not _ok:
        raise CorrectionError(
            400, "Tuzatish summasi juda katta — miqdor yoki narxni tekshiring")
    corr.reversed_total = reversed_total
    corr.replaced_total = replaced_total
    corr.delta_total = delta_total

    # ── 11) HUJJAT SUMMALARI ────────────────────────────────────────────────
    #  ⚠️  `purchase_items` TEGILMAYDI: ular ASLIDA nima yozilganining yozuvi.
    #      Faqat HOSILA pul maydonlari siljiydi.
    old_total = _c2(pur.total)
    paid = _c2(pur.paid_amount or 0)
    new_total, _ok = _fits(old_total + delta_total)
    if not _ok:
        raise CorrectionError(
            400, "Hujjat jami summasi juda katta — miqdor yoki narxni tekshiring")
    if new_total < 0:
        raise CorrectionError(
            409, "Tuzatish hujjat jamini MANFIY qilardi — amal bajarilmadi. "
                 "Hujjatni qo'llab-quvvatlash bilan ko'rib chiqing.")
    db.flush()
    # Hujjat TO'LIQ teskari qilindimi: shu tranzaksiya QULFLAGAN kogortalarning
    # birortasida ham qoldiq qolmagan VA o'rniga yangi kogorta qo'yilmagan.
    # ⚠️  QAROR QULFLANGAN QATORLARDAN. Ilgari bu savolga qulfsiz SELECT javob
    #     berardi: parallel yozuvchi (qaytarish/sanoq) shu qabulning BOSHQA
    #     kogortasini o'zgartirsa, hujjat jimgina bekor bo'lib ketardi yoki
    #     haqli bekor qilish o'tmasdi.
    fully_reversed = (not made) and all(_q3(b.remaining_qty) == 0 for b in doc_batches)

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
        # ⚠️  CUSTODY AYNAN SHU YERDA. Summa qimirlamasa (sof identifikatsiya
        #     tuzatishi — muddat, partiya raqami) kassa hisobi UMUMAN
        #     so'ralmaydi: `purchases.py` ham `_ret_amt` shoxlari ichida
        #     so'raydi. Ilgari u yuqorida, HAR naqd hujjat uchun so'ralardi va
        #     smenasiz menejer pul tegmaydigan xatoni ham tuzata olmasdi.
        acc = _custody(db, emp, branch_id=pur.branch_id,
                       cash_account_id=data.cash_account_id) if ret_amt != 0 else None
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
