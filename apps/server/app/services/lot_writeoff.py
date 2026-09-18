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
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models.inventory import StockBatch, StockMovementLotAllocation
from app.services import stock_invariant as SI


class LotSelectionError(ValueError):
    """Operator ko'rsatgan partiyalar yaroqsiz — amal BAJARILMAYDI."""


# ⚠️  KVANTLASH TASODIFIY EMAS. Brauzer miqdorlarni FLOAT bilan qo'shadi va
#     1.1 + 2.2 serverga 3.3000000000000003 bo'lib keladi. Aynan tenglikni xom
#     float ustida tekshirish operatorga «yig'indi mos emas» degan YOLG'ON xato
#     berardi — u AYNAN 3.3 kiritgan bo'lsa ham. Baza aniqligi NUMERIC(14,3),
#     shu bois taqqoslashdan oldin hamma miqdor shu aniqlikka keltiriladi
#     (`lot_receiving._q()` bilan bir xil qoida).
Q3 = Decimal("0.001")


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Q3, rounding=ROUND_HALF_UP)


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
    # ⚠️  IKKALA TOMON BIR XIL ANIQLIKDA. Faqat partiyalar kvantlanib, umumiy
    #     miqdor xom qolsa, 1.1 + 2.2 = 3.3000000000000003 hamon «mos emas»
    #     bo'lardi — ya'ni tuzatish yarim qolardi.
    total_qty = _d(total_qty)
    if ssum != total_qty:
        raise LotSelectionError(
            f"Partiyalar yig'indisi ({ssum}) umumiy miqdorga ({total_qty}) mos "
            f"emas. Farqni tizim TAQSIMLAMAYDI — qaysi partiya ekanini operator "
            f"aytishi shart.")
    return plan


def apply(db: Session, plan: list, *, movement_id, company_id, product_id,
          now: datetime) -> Decimal:
    """Rejani BAJARADI: partiyalarni kamaytiradi va tafsilotni yozadi.

    Qaytaradi: ANIQ tannarx yig'indisi (Σ qty × partiya narxi) — YAXLITLANMAGAN.

    ⚠️  YAXLITLASH CHAQIRUVCHIDA, BU YERDA EMAS. Ilgari bu funksiya yig'indini
        `quantize(0.01)` bilan — ya'ni Decimal kontekstining JIM sukut rejimi
        HALF_EVEN bilan — yaxlitlardi, holbuki butun repo pulni HALF_UP
        yaxlitlaydi. Qiymat ikki xil maqsadga ketadi (harakat tannarxi va
        hujjat puli), ular esa turli nuqtada yaxlitlanadi: yig'indini shu
        yerda kesish chaqiruvchidan tiyin ma'lumotini OLIB QO'YARDI va ikki
        chaqiruvchida ikki xil yo'l bilan qayta paydo bo'lardi.
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
    return cost


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
#
# ⚠️  TANNARX «TOPILGAN» EMAS, NUSXALANGAN. Manba partiyaning narxi hujjatdan
#     kelgan bo'lsa — ortiqchaniki ham hujjat narxi. Manba TAXMINIY bo'lsa
#     (`return_unattributed`), ortiqchaniki ham TAXMIN bo'lib qoladi va
#     `apply_count` buni `source_type` da SAQLAB o'tadi (Phase 3.6). Sanoq
#     tovar TOPADI, narx TOPMAYDI.


class CountPlan:
    """Bitta mahsulot uchun sanoq rejasi — bajarishdan OLDIN to'liq tekshirilgan."""

    __slots__ = ("decrements", "surpluses", "new_total", "new_lots")

    def __init__(self, decrements, surpluses, new_total, new_lots=()):
        self.decrements = decrements    # [(StockBatch, Decimal)] — kamayish
        self.surpluses = surpluses      # [(StockBatch, Decimal)] — ortiqcha (manba partiya)
        self.new_total = new_total      # Decimal — mahsulotning YANGI umumiy qoldig'i
        # ⚠️  PHASE 4B. Operator javondan TIZIMDA YO'Q partiyani topishi mumkin
        #     (boshqa muddat, boshqa qadoq). Uni mavjud partiyaga «ortiqcha» qilib
        #     yozish muddat hisobotini YOLG'ON qilardi: narx va muddat manba
        #     partiyadan NUSXALANARDI. Shu bois yangi partiya ANIQ e'lon qilinadi.
        self.new_lots = list(new_lots)  # [{qty, unit_cost, batch_no, expiry_date, reason}]


def plan_count(batches: dict, counted_lots, *, open_lots, company_id, product_id,
               branch_id, declared_total: Decimal, new_lots=()) -> CountPlan:
    """Sanoq natijasini rejaga aylantiradi.

    `counted_lots` — [(stock_batch_id, counted_qty)] operator SANAGAN partiyalar.
    `open_lots`    — mahsulotning barcha miqdor tashuvchi partiyalari.
    `new_lots`     — operator TOPGAN, tizimda yo'q partiyalar (Phase 4B):
                     [{qty, unit_cost, batch_no, expiry_date, reason}].
    """
    new_lots = list(new_lots or ())
    if not counted_lots and not new_lots:
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
    yangi = Decimal("0")
    for nl in new_lots:
        q = _d(nl.get("qty"))
        if q <= 0:
            raise LotSelectionError("Yangi partiya miqdori musbat bo'lishi kerak.")
        if _d(nl.get("unit_cost")) < 0:
            raise LotSelectionError("Yangi partiya tannarxi manfiy bo'lishi mumkin emas.")
        yangi += q
    hisob = tegilmagan + sanalgan + yangi
    declared_total = _d(declared_total)       # ayni sabab: ikkala tomon ham NUMERIC(14,3)
    if hisob != declared_total:
        raise LotSelectionError(
            f"Partiyalar yig'indisi ({hisob}) e'lon qilingan umumiy sanoqqa "
            f"({declared_total}) mos emas. Sanalmagan partiyalar TEGILMAYDI "
            f"({tegilmagan}); farqni tizim TAQSIMLAMAYDI.")
    return CountPlan(dec, sur, hisob, new_lots)


def apply_count(db: Session, plan: CountPlan, *, movement_id, company_id,
                product_id, branch_id, now: datetime) -> list:
    """Rejani BAJARADI. Qaytaradi: yaratilgan ortiqcha partiyalar ro'yxati."""
    from app.models.inventory import StockBatch as _SB

    if plan.decrements:
        apply(db, plan.decrements, movement_id=movement_id, company_id=company_id,
              product_id=product_id, now=now)
    yangi = []
    from app.services.lot_fefo import PROVISIONAL_SOURCES as _PROV
    for src, extra in plan.surpluses:
        # ⚠️  TANNARX ASOSI NUSXA BILAN BIRGA KETADI (Phase 3.6, 2-band).
        #     Ortiqcha partiya `src.unit_cost` ni NUSXALAYDI. Agar manba
        #     `return_unattributed` bo'lsa, o'sha narx MUZLATILGAN TAXMIN edi —
        #     lekin belgini `"adjustment"` ga almashtirish uni O'CHIRARDI va
        #     taxmin sanoq orqali «hujjat narxi»ga aylanib chiqardi. Narx
        #     nusxalansa, uning ASOSI ham nusxalanishi SHART; aks holda
        #     provenans sanoqda YO'QOLIB, qayta tiklab bo'lmasdi.
        _st = src.source_type if src.source_type in _PROV else "adjustment"
        b = _SB(id=_uuid.uuid4(), company_id=company_id, product_id=product_id,
                branch_id=branch_id, batch_no=src.batch_no,
                expiry_date=src.expiry_date, qty=extra,
                received_qty=extra, remaining_qty=extra,
                unit_cost=_d(src.unit_cost), status=SI.OPEN,
                source_type=_st, received_at=now, created_at=now)
        db.add(b)
        yangi.append(b)
        db.flush()
        db.add(StockMovementLotAllocation(
            id=_uuid.uuid4(), company_id=company_id,
            stock_movement_id=movement_id, stock_batch_id=b.id,
            product_id=product_id, qty=extra, unit_cost=_d(src.unit_cost),
            expiry_date=src.expiry_date, created_at=now))
    # ── PHASE 4B: OPERATOR E'LON QILGAN YANGI PARTIYALAR ─────────────────────
    #  ⚠️  Bu partiyalar `adjustment` manbasi bilan tug'iladi va narxi OPERATOR
    #      kiritgan narx: u hujjat narxi EMAS. Manba turi `receiving` qilib
    #      qo'yilsa, taxminiy narx keyinchalik «hujjat bilan tasdiqlangan» bo'lib
    #      ko'rinardi — provenans YOLG'ON bo'lardi.
    for nl in plan.new_lots:
        q = _d(nl.get("qty"))
        c = _d(nl.get("unit_cost"))
        b = _SB(id=_uuid.uuid4(), company_id=company_id, product_id=product_id,
                branch_id=branch_id, batch_no=(nl.get("batch_no") or None),
                expiry_date=nl.get("expiry_date"), qty=q,
                received_qty=q, remaining_qty=q, unit_cost=c, status=SI.OPEN,
                source_type="adjustment", received_at=now, created_at=now)
        db.add(b)
        yangi.append(b)
        db.flush()
        db.add(StockMovementLotAllocation(
            id=_uuid.uuid4(), company_id=company_id,
            stock_movement_id=movement_id, stock_batch_id=b.id,
            product_id=product_id, qty=q, unit_cost=c,
            expiry_date=nl.get("expiry_date"), created_at=now))
    return yangi
