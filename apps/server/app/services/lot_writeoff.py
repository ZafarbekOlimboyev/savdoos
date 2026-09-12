# -*- coding: utf-8 -*-
"""PARTIYA-DARAJASIDAGI KAMAYTIRISH — hisobdan chiqarish va inventarizatsiya (Phase 3).

NEGA BITTA MODUL
================
Hisobdan chiqarish va sanoq-kamaytirish TURLI biznes amallari, lekin
partiyaga ta'siri AYNAN BIR XIL: aniq ko'rsatilgan partiyalardan miqdor
ayiriladi, qoldiq shunga yarasha kamayadi, va tafsilot yoziladi. Ikki joyda
nusxalash bitta joyda qulf yoki tekshiruv unutilishiga olib kelardi.

⚠️  «QAYSI PARTIYA» NI TIZIM TAXMIN QILMAYDI. FEFO — SOTUV qoidasi: eng erta
    muddatli tovar birinchi ketadi, chunki mijoz javondan oldingisini oladi.
    Hisobdan chiqarish esa BOSHQA amal: operator ANIQ bir jismoniy tovarni
    (singan quti, muddati o'tgan qadoq) qo'lida ushlab turibdi. Uni FEFO bilan
    «taxmin qilish» eng erta muddatli partiyani kamaytirib, ASLIDA tashlangan
    partiyani javonda qoldirardi — ya'ni muddat hisoboti YOLG'ON bo'lardi.
    Shu bois kuzatuvli mahsulotda partiyalar MAJBURIY va ANIQ ko'rsatiladi.

⚠️  YIG'INDI MOS KELISHI SHART. `Σ lots[].qty == qty`. Farqni «qolganini FEFO
    bilan to'ldiramiz» deb jimgina yopish — operator kiritmagan qarorni tizim
    nomidan qabul qilish bo'lardi.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.inventory import StockBatch, StockMovementLotAllocation
from app.services import stock_invariant as SI


class LotSelectionError(ValueError):
    """Operator ko'rsatgan partiyalar yaroqsiz — amal BAJARILMAYDI."""


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def lock_batches(db: Session, ids) -> dict:
    """Partiyalarni DETERMINISTIK tartibda (id bo'yicha) qulflaydi.

    ⚠️  TARTIB TASODIFIY EMAS. Ikki operator bir vaqtda AYNI ikki partiyaga
        teginsa va ular boshqa-boshqa tartibda qulflasa — AB/BA deadlock.
        Global tartib (`id`) buni yo'q qiladi. Sotuv yo'li ham AYNI qoidaga
        amal qiladi: avval `Inventory`, keyin tartiblangan partiyalar.

    ⚠️  QULF FK'DAN OLDIN. `stock_movement_lot_allocations` qatori partiyaga
        FK bilan bog'lanadi va INSERT `FOR KEY SHARE` oladi; keyin `FOR UPDATE`
        so'rash qulf DARAJASINI OSHIRISH bo'lib deadlock tug'dirardi (Phase 2.5
        da aynan shu nasiya sotuvида o'lchangan). Shu bois partiyalar HAR DOIM
        allokatsiya yozilishidan OLDIN qulflanadi.
    """
    out = {}
    for bid in sorted({str(i) for i in ids}):
        b = (db.query(StockBatch).filter(StockBatch.id == _uuid.UUID(bid))
             .with_for_update().first())
        if b is not None:
            out[str(b.id)] = b
    return out


def validate(batches: dict, lines, *, company_id, product_id, branch_id,
             total_qty: Decimal) -> list:
    """Operator tanlovini tekshiradi. Xato bo'lsa — HECH NARSA o'zgarmaydi.

    `lines` — [(stock_batch_id, qty)]. Qaytaradi: [(StockBatch, Decimal qty)].
    """
    if not lines:
        raise LotSelectionError(
            "Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating — tizim "
            "qaysi jismoniy partiya chiqarilayotganini TAXMIN QILMAYDI.")
    seen, plan, ssum = set(), [], Decimal("0")
    for bid, qty in lines:
        key = str(bid)
        if key in seen:
            raise LotSelectionError(f"Partiya ikki marta ko'rsatilgan: {key}")
        seen.add(key)
        q = _d(qty)
        if q <= 0:
            raise LotSelectionError(f"Partiya miqdori musbat bo'lishi kerak: {key}")
        b = batches.get(key)
        if b is None or b.company_id != company_id:
            raise LotSelectionError(f"Partiya topilmadi: {key}")
        if b.product_id != product_id or b.branch_id != branch_id:
            raise LotSelectionError(
                f"Partiya boshqa mahsulot yoki filialga tegishli: {key}")
        # ⚠️  NOMA'LUM HOLAT — FAIL-CLOSED. `void` partiya miqdor tashimaydi
        #     (`stock_invariant.EXCLUDED`), undan ayirish qoldiqni partiyalar
        #     yig'indisidan AJRATIB yuborardi.
        if b.status not in SI.QUANTITY_BEARING:
            raise LotSelectionError(
                f"Partiya holati '{b.status}' — undan miqdor ayirib bo'lmaydi: {key}")
        if _d(b.remaining_qty) < q:
            raise LotSelectionError(
                f"Partiyada yetarli qoldiq yo'q ({b.remaining_qty} < {q}): {key} — "
                f"jismoniy partiya MANFIYGA tushmaydi")
        ssum += q
        plan.append((b, q))
    if ssum != total_qty:
        raise LotSelectionError(
            f"Partiyalar yig'indisi ({ssum}) umumiy miqdorga ({total_qty}) mos "
            f"emas. Farqni tizim TAQSIMLAMAYDI — qaysi partiya ekanini operator "
            f"aytishi shart.")
    return plan


def apply(db: Session, plan: list, *, movement_id, company_id, product_id,
          now: datetime) -> Decimal:
    """Rejani BAJARADI: partiyalarni kamaytiradi va tafsilotni yozadi.

    Qaytaradi: ANIQ tannarx yig'indisi (Σ qty × partiya narxi) — yaxlitlangan
    o'rtachadan qayta hisoblanmaydi.
    """
    cost = Decimal("0")
    for b, q in plan:
        b.remaining_qty = _d(b.remaining_qty) - q
        b.updated_at = now
        # ⚠️  `depleted` — miqdor hayot sikli, sabab EMAS. «Nega bo'shadi»
        #     degan savolga `stock_movements` javob beradi. Alohida
        #     `written_off` holati invariantga YANGI holat o'rgatishni talab
        #     qilardi va hech qanday yangi ma'lumot bermasdi.
        if _d(b.remaining_qty) == 0:
            b.status = SI.DEPLETED
        cost += (q * _d(b.unit_cost))
        db.add(StockMovementLotAllocation(
            id=_uuid.uuid4(), company_id=company_id,
            stock_movement_id=movement_id, stock_batch_id=b.id,
            product_id=product_id, qty=q, unit_cost=_d(b.unit_cost),
            expiry_date=b.expiry_date, created_at=now))
    return cost.quantize(Decimal("0.01"))


# ══ INVENTARIZATSIYA — PARTIYA DARAJASIDA ═══════════════════════════════════
#
# ⚠️  UMUMIY FARQNI TIZIM PARTIYALARGA TAQSIMLAMAYDI. «10 dona kam chiqdi» degan
#     xabar qaysi kogortadan kam ekanini AYTMAYDI. Uni FEFO bilan taqsimlash
#     muddat hisobotini va tannarxni YOLG'ON qilardi — kam chiqqan tovar aslida
#     boshqa partiyadan bo'lishi mumkin.
#
# ⚠️  SANALMAGAN PARTIYA — «NOL» EMAS. Operator ro'yxatga kiritmagan partiya
#     TEGILMAY qoladi. Aks holda bir partiyani sanab, qolganini ko'rmagan
#     operator ularni bilmasdan NOLGA tushirardi.
#
# ⚠️  ORTIQCHA TOPILSA — YANGI PARTIYA. Mavjud kogortani shishirish uning
#     provenansini (qabul sanasi, hujjat, yetkazib beruvchi) YOLG'ON qilardi va
#     `remaining_qty <= received_qty` ni buzardi. Ortiqcha — ALOHIDA
#     `source_type='adjustment'` kogortasi; muddati va tannarxi topilgan
#     partiyadan KO'CHIRILADI (operator «shu kogortadan ko'proq chiqdi» deyapti).


class CountPlan:
    """Bitta mahsulot uchun sanoq rejasi — bajarishdan OLDIN to'liq tekshirilgan."""

    __slots__ = ("decrements", "surpluses", "new_total")

    def __init__(self, decrements, surpluses, new_total):
        self.decrements = decrements    # [(StockBatch, Decimal)] — kamayish
        self.surpluses = surpluses      # [(StockBatch, Decimal)] — ortiqcha (manba partiya)
        self.new_total = new_total      # Decimal — mahsulotning YANGI umumiy qoldig'i


def plan_count(batches: dict, counted_lots, *, open_lots, company_id, product_id,
               branch_id, declared_total: Decimal) -> CountPlan:
    """Sanoq natijasini rejaga aylantiradi.

    `counted_lots` — [(stock_batch_id, counted_qty)] operator SANAGAN partiyalar.
    `open_lots`    — mahsulotning barcha miqdor tashuvchi partiyalari.
    """
    if not counted_lots:
        raise LotSelectionError(
            "Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim "
            "partiyalarga TAQSIMLAMAYDI.")
    seen, dec, sur = set(), [], []
    for bid, cnt in counted_lots:
        key = str(bid)
        if key in seen:
            raise LotSelectionError(f"Partiya ikki marta sanalgan: {key}")
        seen.add(key)
        c = _d(cnt)
        if c < 0:
            raise LotSelectionError(f"Sanoq manfiy bo'lishi mumkin emas: {key}")
        b = batches.get(key)
        if b is None or b.company_id != company_id:
            raise LotSelectionError(f"Partiya topilmadi: {key}")
        if b.product_id != product_id or b.branch_id != branch_id:
            raise LotSelectionError(
                f"Partiya boshqa mahsulot yoki filialga tegishli: {key}")
        if b.status not in SI.QUANTITY_BEARING:
            raise LotSelectionError(
                f"Partiya holati '{b.status}' — uni sanab bo'lmaydi: {key}")
        diff = c - _d(b.remaining_qty)
        if diff < 0:
            dec.append((b, -diff))
        elif diff > 0:
            sur.append((b, diff))

    # SANALMAGAN partiyalar TEGILMAYDI — ularning qoldig'i yig'indiga kiradi.
    tegilmagan = sum((_d(b.remaining_qty) for b in open_lots
                      if str(b.id) not in seen), Decimal("0"))
    sanalgan = sum((_d(c) for _b, c in counted_lots), Decimal("0"))
    hisob = tegilmagan + sanalgan
    if hisob != declared_total:
        raise LotSelectionError(
            f"Partiyalar yig'indisi ({hisob}) e'lon qilingan umumiy sanoqqa "
            f"({declared_total}) mos emas. Sanalmagan partiyalar TEGILMAYDI "
            f"({tegilmagan}); farqni tizim TAQSIMLAMAYDI.")
    return CountPlan(dec, sur, hisob)


def apply_count(db: Session, plan: CountPlan, *, movement_id, company_id,
                product_id, branch_id, now: datetime) -> list:
    """Rejani BAJARADI. Qaytaradi: yaratilgan ortiqcha partiyalar ro'yxati."""
    from app.models.inventory import StockBatch as _SB

    if plan.decrements:
        apply(db, plan.decrements, movement_id=movement_id, company_id=company_id,
              product_id=product_id, now=now)
    yangi = []
    for src, extra in plan.surpluses:
        b = _SB(id=_uuid.uuid4(), company_id=company_id, product_id=product_id,
                branch_id=branch_id, batch_no=src.batch_no,
                expiry_date=src.expiry_date, qty=extra,
                received_qty=extra, remaining_qty=extra,
                unit_cost=_d(src.unit_cost), status=SI.OPEN,
                source_type="adjustment", received_at=now, created_at=now)
        db.add(b)
        yangi.append(b)
        db.flush()
        db.add(StockMovementLotAllocation(
            id=_uuid.uuid4(), company_id=company_id,
            stock_movement_id=movement_id, stock_batch_id=b.id,
            product_id=product_id, qty=extra, unit_cost=_d(src.unit_cost),
            expiry_date=src.expiry_date, created_at=now))
    return yangi
