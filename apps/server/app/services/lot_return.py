# -*- coding: utf-8 -*-
"""PARTIYAGA QAYTARISH — chek asosida, ASL TAQSIMOTNI orqaga o'rash (Phase 3 → 4A).

QOIDA: QAYTARISH — SOTUVNING TESKARISI, YANGI FEFO QARORI EMAS
==============================================================
Mijoz qaytargan tovar AYNAN o'zi olgan tovar. Uni qaytadan FEFO bilan
joylashtirish — «eng erta muddatlisiga qo'shamiz» — jismoniy haqiqatni
buzardi: mijoz D20 partiyasidan olgan bo'lsa-yu, qaytarish uni D10 ga
yozsa, muddat hisoboti ham, tannarx ham YOLG'ON bo'lardi.

Shu bois qaytarish `sale_item_lot_allocations` ni — sotuv lahzasining
O'ZGARMAS suratini — YOZILGAN TARTIBDA orqaga o'raydi.

KUMULYATIV HIMOYA
=================
Bitta chek bo'lak-bo'lak, bir necha marta qaytarilishi mumkin. Asl taqsimot
O'ZGARMAYDI (u surat), shu bois «bu partiyaga qancha qaytarilgan edi?» degan
savolga `return_item_lot_allocations` javob beradi:

    Σ(qaytarilgan[sale_item, partiya]) <= asl_taqsimot[sale_item, partiya].qty

BIR CHEKDA AYNI MAHSULOT IKKI QATORDA
=====================================
`create_sale` qatorlarni birlashtirmaydi, ya'ni bitta chekda ayni mahsulot
IKKI `SaleItem` bo'lishi mumkin va ularning taqsimoti HAR XIL. MAHSULOTNING
BARCHA qatorlari (id tartibida — chek ichida BARQAROR) ko'rib chiqiladi.

⚠️  CHEKLOV (e'lon qilingan). Ayni mahsulotning ikki qatori bo'lsa, qaysi
    qatorning tovari qaytgani jismonan NOMA'LUM. Tartib chek ichida
    deterministik, lekin «to'g'ri» emas — faqat izchil. Jami miqdor va umrbod
    COGS tartibdan mustaqil; davr bo'yicha bo'linish va kogorta joyi esa yo'q.

HAR SOTUV QATORI UCHUN UCH BOSQICH (Phase 4A)
=============================================
  (1) sotuv lahzasidagi TAQSIMOT      -> asl partiya, ANIQ narxda
  (2) qarzning HAQIQIY yopish hodisasi -> yopishda topilgan partiya; kredit
      chekdagi TAXMIN ulushi (taxminiy chelak) + tan olingan og'ish TESKARI
  (3) qarz DUMI (hali atributsiyasiz)  -> yangi `return_unattributed` (U) partiya

⚠️  NEGA (2) KERAK. Phase 3 da yopish sotuv suratiga yangi taqsimot qatori
    QO'SHARDI va qaytarish uni (1) orqali «aniq» narxda qaytarardi: chekda
    TAXMIN yozilgan summa qaytishda ANIQ bo'lib chiqib, ikki chelak bir-birini
    yopmasdi. 4A da surat tegilmaydi — atributsiya hodisada yashaydi va
    qaytarish uni hodisa orqali teskari qiladi.

⚠️  (2) CHEGARASI — shu qatorning HALI TASHQARIDAGI tovari:
        out = qty − qaytgan_dum − shu_qatordan_hodisa_orqali_qaytgan
    Hodisalar sig'imi bundan KATTA bo'lishi mumkin (U tovari qayta sotilgan
    bo'lsa, hodisa o'sha QAYTA SOTUV tovarini ham qoplaydi). Chegarasiz (2)
    ikki qatorli chekda BOSHQA qatorning tovarini o'g'irlardi.

QAYTA SOTILGAN U TOVARI QAYTSA (v3 R1)
======================================
Qarz dumi qaytib U partiyaga tushgan, U dan qayta sotilgan, keyin qarz HAQIQIY
partiyaga yopilgan (hodisa o'sha qayta sotuv tovarini ham qoplagan). Endi
qayta sotuv mijozi qaytarsa, tovar (1) bo'yicha U ga tushardi — lekin qarz
allaqachon yopilgan: U da netlab bo'lmaydigan tovar qolardi, X partiya esa
bir dona kam ko'rinardi va og'ish qaytgan tovar uchun COGS'da osilib qolardi.

Qoida: U ga qo'yish `own_U(S) > ochiq_qarz(S)` holatini keltirib chiqarsa,
ORTIQCHASI S ning haqiqiy hodisasi orqali qaytariladi (X ga, og'ish teskari).
Natija: `own_U(S) <= ochiq_qarz(S)` HAR DOIM (post-apply tasdig'i e).

QARZ DUMI — JISMONIY TOVAR QAYERDA YASHAYDI (Phase 3.5)
=====================================================
Jismoniy qaytish qoldiqni +k qiladi, ya'ni `+k = Δ(Σpartiya) − Δ(Σqarz)`.
Model partiya yaratadi VA qarzga tegmaydi: Inventory +k, U partiya +k, qarz
o'zgarmas. Tarixiy qarz — o'tgan fakt; tovarning qaytishi — boshqa fakt.

⚠️  «SOTILADIMI?» — sotuvni faqat MIQDOR cheklaydi (`Inventory.qty`); ochiq
    qarz sotuvni O'ZI bloklamaydi.

TANNARX — IKKI HADLI, SOTUVDAGIDEK
==================================
    cost_total      = Σ(k × asl_partiya_narxi) + unresolved_cost
    unresolved_cost = Σ (2) kreditlari + Σ (3) kreditlari   (TAXMINIY chelak)

(2) va (3) kreditlari KUMULYATIV yaxlitlanadi: to'liq qaytarishda ular chekdagi
taxminni tiyinigacha teskari qiladi.
"""
from __future__ import annotations

import uuid as _uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.inventory import (RESOLUTION_REAL, LotShortfall, LotShortfallResolution,
                                  ReturnItemLotAllocation, ReturnItemResolutionAllocation,
                                  ReturnItemShortfallAllocation, SaleItemLotAllocation,
                                  StockBatch)
from app.services import lot_resolution as LRes
from app.services import stock_invariant as SI

_ZERO = Decimal("0")


class ReturnAttributionError(ValueError):
    """Qaytarilayotgan miqdorni asl taqsimotga bog'lab bo'lmadi."""


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def open_debt(sf) -> Decimal:
    """YOPILMAGAN qarz — YAGONA ta'rif: `qty − resolved_qty`.

    ⚠️  `returned_qty` BU YERGA KIRMAYDI (Phase 3.5 tuzatishi). Qaytgan tovar
        YANGI, atributsiyasiz partiya tug'diradi; uni qarzdan ham ayirish
        qoldiqni +2k qilishni talab qilardi.
    """
    return _d(sf.qty) - _d(sf.resolved_qty)


@dataclass
class EventLine:
    """(2) bosqich qatori: haqiqiy yopish hodisasi orqali qaytish."""
    sale_item_id: object
    event: LotShortfallResolution
    batch: StockBatch
    qty: Decimal
    credit: Decimal               # chekdagi TAXMIN ulushi (taxminiy chelakdan chiqadi)
    variance_reversed: Decimal    # tan olingan og'ishning teskarisi (ishorasi hodisaniki)


@dataclass
class DebtLine:
    """(3) bosqich qatori: qarz DUMI qaytishi -> U partiya."""
    shortfall: LotShortfall
    qty: Decimal
    credit: Decimal
    unit_cost: Decimal


@dataclass
class ReturnPlan:
    """Bajarishdan OLDIN to'liq hisoblangan reja."""
    lot_lines: list = field(default_factory=list)    # [(sale_item_id, StockBatch, qty, unit_cost)]
    event_lines: list = field(default_factory=list)  # [EventLine]
    debt_lines: list = field(default_factory=list)   # [DebtLine]
    shortfall_ids: set = field(default_factory=set)  # tegilgan qarzlar (post-apply tasdig'i)

    @property
    def exact_cost(self) -> Decimal:
        return sum((q * c for _si, _b, q, c in self.lot_lines), _ZERO)

    @property
    def unresolved_cost(self) -> Decimal:
        """(2) + (3) kreditlari — `exact_cost` ga QO'SHILADIGAN alohida had.

        ⚠️  `exact_cost` bilan KESISHMAYDI: u `lot_lines` dan, bu `event_lines`
            va `debt_lines` dan. Chaqiruvchi ikkalasini QO'SHADI.
        """
        return (sum((e.credit for e in self.event_lines), _ZERO)
                + sum((d.credit for d in self.debt_lines), _ZERO))

    @property
    def provisional_lot_cost(self) -> Decimal:
        """`exact_cost` ning TAXMINIY ULUSHI (Phase 3.6, 2-band) — ULUSH, HAD EMAS.

        Taxminiy (`return_unattributed`) partiyadan sotilgan tovar qaytsa,
        `lot_lines` uni o'sha partiyaga QAYTA yozadi va `exact_cost` uni aniq
        COGS bo'lib teskari qiladi — shu ulush «taxmin» deb AYTILADI.
        """
        from app.services.lot_fefo import is_provisional
        return sum((q * c for _si, b, q, c in self.lot_lines if is_provisional(b)), _ZERO)

    @property
    def variance_reversed(self) -> Decimal:
        return sum((e.variance_reversed for e in self.event_lines), _ZERO)

    @property
    def total_qty(self) -> Decimal:
        return (sum((q for _si, _b, q, _c in self.lot_lines), _ZERO)
                + sum((e.qty for e in self.event_lines), _ZERO)
                + sum((d.qty for d in self.debt_lines), _ZERO))


def sale_items_for(db: Session, sale_id, product_id) -> list:
    """Chekdagi SHU mahsulotning BARCHA qatorlari — id tartibida (chek ichida barqaror)."""
    from app.models.sales import SaleItem
    return (db.query(SaleItem)
            .filter(SaleItem.sale_id == sale_id, SaleItem.product_id == product_id)
            .order_by(SaleItem.id).all())


def _own_u_map(db: Session, batch_ids) -> dict:
    """{U partiya id: qarz id} — faqat qarz dumi qaytishidan tug'ilgan partiyalar."""
    ids = [b for b in batch_ids if b is not None]
    if not ids:
        return {}
    return dict(db.execute(
        select(ReturnItemShortfallAllocation.created_batch_id,
               ReturnItemShortfallAllocation.shortfall_id)
        .where(ReturnItemShortfallAllocation.created_batch_id.in_(ids))).all())


def _returned_so_far(db: Session, sale_item_id, allocs=None) -> dict:
    """{stock_batch_id: qaytarilgan miqdor} — kumulyativ chegara uchun.

    ⚠️  Yo'naltirilgan (v3 R1) qaytishlar ham HISOBGA OLINADI. Qayta sotilgan U
        tovari qarz hodisasi orqali qaytganda `return_item_lot_allocations`
        yozilmaydi (tovar U ga emas, X ga tushdi) — lekin u shu qatorning U
        ulushidan qaytgan. Hisobga olinmasa, ayni ulush ikkinchi marta
        qaytarilishi mumkin edi. U ulushlariga taqsimot tartibida to'ldiriladi.
    """
    rows = (db.query(ReturnItemLotAllocation.stock_batch_id,
                     func.coalesce(func.sum(ReturnItemLotAllocation.qty), 0))
            .filter(ReturnItemLotAllocation.sale_item_id == sale_item_id)
            .group_by(ReturnItemLotAllocation.stock_batch_id).all())
    done = {str(b): LRes.q3(q) for b, q in rows}
    if not allocs:
        return done
    routed = db.execute(
        select(LotShortfallResolution.shortfall_id,
               func.coalesce(func.sum(ReturnItemResolutionAllocation.qty), 0))
        .join(LotShortfallResolution,
              LotShortfallResolution.id == ReturnItemResolutionAllocation.resolution_id)
        .where(ReturnItemResolutionAllocation.sale_item_id == sale_item_id,
               or_(LotShortfallResolution.sale_item_id.is_(None),
                   LotShortfallResolution.sale_item_id != sale_item_id))
        .group_by(LotShortfallResolution.shortfall_id)).all()
    if not routed:
        return done
    u_of = _own_u_map(db, [a.stock_batch_id for a in allocs])
    for sid, rq in routed:
        rq = LRes.q3(rq)
        for a in allocs:
            if rq <= 0:
                break
            if u_of.get(a.stock_batch_id) != sid:
                continue
            k = str(a.stock_batch_id)
            room = LRes.q3(a.qty) - done.get(k, _ZERO)
            t = min(room, rq)
            if t > 0:
                done[k] = done.get(k, _ZERO) + t
                rq -= t
    return done


class _State:
    """Bitta `plan()` ichidagi keshlar va kutilayotgan (hali yozilmagan) miqdorlar."""

    def __init__(self):
        self.sf: dict = {}                       # id -> (LotShortfall, Book)
        self.events: dict = {}                   # shortfall id -> [hodisa]
        self.reversed: dict = {}                 # shortfall id -> {event id: qaytgan}
        self.pending_ev = defaultdict(lambda: _ZERO)
        self.pending_tail = defaultdict(lambda: _ZERO)
        self.pending_u = defaultdict(lambda: _ZERO)
        self.pending_own = defaultdict(lambda: _ZERO)


def _lock_shortfall(db: Session, st: _State, *, sf_id=None, sale_item_id=None):
    """Qarzni FOR UPDATE (yangi qiymatlar bilan) + hosila hisob. Partiyadan OLDIN."""
    if sf_id is not None and sf_id in st.sf:
        return st.sf[sf_id]
    q = db.query(LotShortfall)
    q = (q.filter(LotShortfall.id == sf_id) if sf_id is not None
         else q.filter(LotShortfall.sale_item_id == sale_item_id))
    sf = q.with_for_update().populate_existing().first()
    if sf is None:
        return None, None
    if sf.id in st.sf:
        return st.sf[sf.id]
    st.sf[sf.id] = (sf, LRes.book(db, sf))
    return st.sf[sf.id]


def _lock_batch(db: Session, batch_id):
    return (db.query(StockBatch).filter(StockBatch.id == batch_id)
            .with_for_update().populate_existing().first())


def _check_restock_target(b, branch_id, what: str):
    # ⚠️  `void` partiya invariant yig'indisidan CHIQARILGAN — unga qo'shish
    #     qoldiqni partiyalar yig'indisidan AJRATIB yuborardi.
    if b.status not in SI.QUANTITY_BEARING:
        raise ReturnAttributionError(
            f"{what} holati '{b.status}' — unga tovar qaytarib bo'lmaydi. "
            f"Omborga qaytarmasdan (restock'siz) qaytaring.")
    if b.branch_id != branch_id:
        raise ReturnAttributionError(
            f"{what} boshqa filialda — qaytarish shu filialga yozilmoqda. "
            f"Restock'siz qaytaring yoki asl filialda qabul qiling.")


def _own_line_reversed(db: Session, sf) -> Decimal:
    """Qarz qatorining O'Z tovaridan hodisa orqali qaytgani (yo'naltirilganlar kirmaydi)."""
    if sf.sale_item_id is None:
        return _ZERO
    return LRes.q3(db.execute(
        select(func.coalesce(func.sum(ReturnItemResolutionAllocation.qty), 0))
        .join(LotShortfallResolution,
              LotShortfallResolution.id == ReturnItemResolutionAllocation.resolution_id)
        .where(LotShortfallResolution.shortfall_id == sf.id,
               ReturnItemResolutionAllocation.sale_item_id == sf.sale_item_id)).scalar())


def _take_events(db: Session, st: _State, p: ReturnPlan, sf, want: Decimal, sale_item_id,
                 branch_id, restock: bool) -> Decimal:
    """Qarzning HAQIQIY hodisalaridan `want` gacha oladi. Qaytaradi: olingan miqdor.

    Tartib DETERMINISTIK: (resolved_at, muddat NULLS LAST, line_no, id).
    Kredit va og'ish teskarisi KUMULYATIV proporsional — monoton, ishora
    almashmaydi va hodisa to'liq qaytganda AYNAN nolga keladi.
    """
    if want <= 0:
        return _ZERO
    if sf.id not in st.events:
        st.events[sf.id] = (db.query(LotShortfallResolution)
                            .filter(LotShortfallResolution.shortfall_id == sf.id,
                                    LotShortfallResolution.kind == RESOLUTION_REAL)
                            .order_by(LotShortfallResolution.resolved_at,
                                      LotShortfallResolution.expiry_date.asc().nullslast(),
                                      LotShortfallResolution.line_no,
                                      LotShortfallResolution.id).all())
        st.reversed[sf.id] = {rid: LRes.q3(q) for rid, q in db.execute(
            select(ReturnItemResolutionAllocation.resolution_id,
                   func.coalesce(func.sum(ReturnItemResolutionAllocation.qty), 0))
            .join(LotShortfallResolution,
                  LotShortfallResolution.id == ReturnItemResolutionAllocation.resolution_id)
            .where(LotShortfallResolution.shortfall_id == sf.id)
            .group_by(ReturnItemResolutionAllocation.resolution_id)).all()}
    got = _ZERO
    for ev in st.events[sf.id]:
        if got >= want:
            break
        before = st.reversed[sf.id].get(ev.id, _ZERO) + st.pending_ev[ev.id]
        avail = LRes.q3(ev.qty) - before
        if avail <= 0:
            continue
        t = min(avail, want - got)
        b = _lock_batch(db, ev.stock_batch_id) if restock else db.get(StockBatch, ev.stock_batch_id)
        if b is None:
            raise ReturnAttributionError("Yopish hodisasining partiyasi topilmadi — "
                                         "qaytarishni bog'lab bo'lmaydi")
        if restock:
            _check_restock_target(b, branch_id, "Yopishda topilgan partiya")
        after = before + t
        eq = LRes.q3(ev.qty)
        pc, var = LRes.c2(ev.provisional_cost), LRes.c2(ev.variance)
        credit = LRes.c2(pc * after / eq) - LRes.c2(pc * before / eq)
        vrev = LRes.c2(var * after / eq) - LRes.c2(var * before / eq)
        p.event_lines.append(EventLine(sale_item_id, ev, b, t, credit, vrev))
        st.pending_ev[ev.id] += t
        got += t
    return got


def plan(db: Session, *, company_id, branch_id, product_id, sale_items,
         qty: Decimal, restock: bool = True) -> ReturnPlan:
    """Qaytarilayotgan miqdorni atributsiyaga bog'laydi. HECH NARSA yozmaydi.

    ⚠️  AVVAL FLUSH. Sessiya `autoflush=False`: bir qaytarishda ayni mahsulot
        IKKI qatorda kelsa, ikkinchi qator birinchisining (hali yozilmagan)
        taqsimot/hodisa qatorlarini KO'RMASDI va ayni ulushni IKKI marta
        qaytarardi.

    QULF TARTIBI (chaqiruvchi Inventory'ni allaqachon ushlab turadi):
        qarz FOR UPDATE -> partiya FOR UPDATE. Har qator uchun qarz partiyadan
        OLDIN — `lot_resolution.resolve` bilan bir xil.
    """
    from app.services.lot_fefo import is_provisional  # noqa: F401 (hujjat: U = taxminiy)
    db.flush()
    left = LRes.q3(qty)
    p = ReturnPlan()
    st = _State()
    for si in sale_items:
        if left <= 0:
            break
        sf, bk = _lock_shortfall(db, st, sale_item_id=si.id)
        if sf is not None and bk.legacy and restock:
            raise ReturnAttributionError(
                "Bu chek qatorining qarzi Phase 4A dan oldin hodisasiz o'zgargan (legacy "
                "shakl) — partiyaga qaytarib bo'lmaydi. Omborga qaytarmasdan "
                "(restock'siz) qaytaring.")

        # ── (1) SOTUV LAHZASIDAGI TAQSIMOT ──────────────────────────────────
        # ⚠️  TARTIB DETERMINISTIK: muddat (FEFO), yozuv vaqti, partiya id'si.
        allocs = (db.query(SaleItemLotAllocation)
                  .filter(SaleItemLotAllocation.sale_item_id == si.id)
                  .order_by(SaleItemLotAllocation.expiry_date.asc().nullslast(),
                            SaleItemLotAllocation.created_at,
                            SaleItemLotAllocation.stock_batch_id).all())
        done = _returned_so_far(db, si.id, allocs)
        u_of = _own_u_map(db, [a.stock_batch_id for a in allocs])
        for a in allocs:
            if left <= 0:
                break
            cap = LRes.q3(a.qty) - done.get(str(a.stock_batch_id), _ZERO)
            if cap <= 0:
                continue
            take = min(cap, left)
            routed = _ZERO
            s_id = u_of.get(a.stock_batch_id)
            S = None
            if s_id is not None and restock:
                S, sbk = _lock_shortfall(db, st, sf_id=s_id)
                if S is not None and not sbk.legacy:
                    open_s = LRes.q3(S.qty) - LRes.q3(S.resolved_qty)
                    over = sbk.own_u_remaining + st.pending_u[s_id] + take - open_s
                    routed = max(_ZERO, min(take, over))
            b = _lock_batch(db, a.stock_batch_id)
            if b is None:
                raise ReturnAttributionError(
                    "Asl partiya topilmadi — qaytarishni bog'lab bo'lmaydi")
            keep = take - routed
            if keep > 0 and restock:
                _check_restock_target(b, branch_id, "Asl partiya")
            if routed > 0:
                got = _take_events(db, st, p, S, routed, si.id, branch_id, restock)
                if got < routed:
                    raise ReturnAttributionError(
                        f"Qayta sotilgan atributsiyasiz tovarning {routed - got} donasini "
                        f"qarzning yopish hodisasiga bog'lab bo'lmadi — tizim TAXMIN "
                        f"QILMAYDI. Omborga qaytarmasdan (restock'siz) qaytaring.")
                p.shortfall_ids.add(s_id)
            if keep > 0:
                # `unit_cost` — ASL SOTUVDAGI narx, partiyaning BUGUNGI narxi emas.
                p.lot_lines.append((si.id, b, keep, _d(a.unit_cost)))
                if s_id is not None:
                    st.pending_u[s_id] += keep
                    p.shortfall_ids.add(s_id)
            left -= take

        if left <= 0 or sf is None:
            continue
        p.shortfall_ids.add(sf.id)
        unit = LRes.c2(sf.unit_cost)
        if bk.legacy:
            # restock=False: Phase 3 semantikasi — faqat tannarx, qator yozilmaydi.
            tail_cap = max(_ZERO, LRes.q3(sf.qty) - LRes.q3(sf.resolved_qty)
                           - LRes.q3(sf.returned_qty) - st.pending_tail[sf.id])
            r_before = LRes.q3(sf.returned_qty) + st.pending_tail[sf.id]
        else:
            # ── (2) HAQIQIY YOPISH HODISALARI ───────────────────────────────
            own_rev = _own_line_reversed(db, sf) + st.pending_own[sf.id]
            out = max(_ZERO, LRes.q3(sf.qty) - bk.returned_tail
                      - st.pending_tail[sf.id] - own_rev)
            got2 = _take_events(db, st, p, sf, min(left, out), si.id, branch_id, restock)
            st.pending_own[sf.id] += got2
            left -= got2
            # ── (3) QARZ DUMI ───────────────────────────────────────────────
            # ⚠️  Qaytgan dum AYIRILADI (Phase 3.6 da ayirilmasdi — dumdan qaytgan
            #     tovar qayta-qayta qaytarilishi mumkin edi).
            tail_cap = min(max(_ZERO, LRes.q3(sf.qty) - bk.resolved_real
                               - bk.returned_tail - st.pending_tail[sf.id]),
                           max(_ZERO, out - got2))
            r_before = bk.returned_tail + st.pending_tail[sf.id]
        t = min(left, tail_cap)
        if t > 0 and restock and sf.branch_id != branch_id:
            # ⚠️  DUM FAQAT QARZ FILIALIGA (review HIGH). U partiya boshqa filialda
            #     tug'ilsa, qarzni endi HECH NARSA yopa olmasdi: netting faqat qarz
            #     filialidagi partiyani qabul qiladi, haqiqiy yopish esa javondagi
            #     U ni ayirib chegarani 0 ga tushirardi — qarz abadiy ochiq, X esa
            #     javondagidan ko'p ko'rinardi. (1) va (2) dagi filial qoidasi bilan bir xil.
            raise ReturnAttributionError(
                "Qarz dumi boshqa filialda — qaytarish shu filialga yozilmoqda. "
                "Restock'siz qaytaring yoki asl filialda qabul qiling.")
        if t > 0:
            # Taxminiy narx — qarz qatoridagi MUZLATILGAN qiymat; kredit KUMULYATIV.
            credit = LRes.cumulative_share(unit, r_before, t)
            p.debt_lines.append(DebtLine(sf, t, credit, unit))
            st.pending_tail[sf.id] += t
            if restock:
                st.pending_u[sf.id] += t
            left -= t

    if left > 0:
        raise ReturnAttributionError(
            f"Qaytarilayotgan miqdorning {left} donasini asl chek partiyalariga "
            f"bog'lab bo'lmadi. Tizim TAXMIN QILMAYDI — omborga qaytarmasdan "
            f"(restock'siz) qaytaring.")
    return p


SOURCE_RETURN_UNATTRIBUTED = "return_unattributed"


def apply(db: Session, p: ReturnPlan, *, return_id, return_item_id, company_id, branch_id,
          product_id, now: datetime) -> list:
    """Rejani BAJARADI. Qaytaradi: yaratilgan ATRIBUTSIYASIZ (U) partiyalar ro'yxati.

    `Inventory` ni bu funksiya O'ZGARTIRMAYDI — uni chaqiruvchi o'zining
    `restock` mantig'i ichida qiladi, chunki u qatorni allaqachon qulflagan.
    """
    def _restock(b, q):
        b.remaining_qty = _d(b.remaining_qty) + q
        b.updated_at = now
        # ⚠️  BO'SHAGAN PARTIYA QAYTA OCHILADI — `depleted` «hozir nol», «abadiy
        #     yopiq» emas. Muddati o'tgan partiya ham JISMONAN qaytadi va
        #     muddati o'tganligicha qoladi (muddat — hisob, holat emas).
        if b.status == SI.DEPLETED and _d(b.remaining_qty) > 0:
            b.status = SI.OPEN

    for si_id, b, q, ucost in p.lot_lines:
        _restock(b, q)
        db.add(ReturnItemLotAllocation(
            id=_uuid.uuid4(), company_id=company_id,
            return_item_id=return_item_id, sale_item_id=si_id,
            stock_batch_id=b.id, product_id=product_id,
            qty=q, unit_cost=ucost, created_at=now))

    # ── (2) HODISA ORQALI QAYTISH ───────────────────────────────────────────
    #  Bitta qaytarish qatori ayni hodisaga bir necha marta tegishi mumkin:
    #  qayta sotuv chekida ayni mahsulot IKKI qatorda bo'lib, ikkalasi ham ayni
    #  qarzning U partiyasidan yegan bo'lsa, ikkalasining qaytishi ayni hodisaga
    #  yo'naltiriladi. Yozuv (hodisa, QAYTGAN sotuv qatori) bo'yicha — noyob kalit
    #  ham shu (`ux_rira_item_resolution`), chunki qatorma-qator chegara
    #  (`_returned_so_far`) aynan `sale_item_id` ga tayanadi. Bir juftlikka bir necha
    #  bo'lak tushsa yig'iladi: kumulyativ kreditlar teleskopik, yig'indi aniq.
    merged: dict = {}
    for e in p.event_lines:
        _restock(e.batch, e.qty)
        k = (e.event.id, e.sale_item_id)
        if k in merged:
            m = merged[k]
            m["qty"] += e.qty
            m["credit"] += e.credit
            m["vrev"] += e.variance_reversed
        else:
            merged[k] = {"ev": e.event, "si": e.sale_item_id, "qty": e.qty,
                         "credit": e.credit, "vrev": e.variance_reversed}
    for m in merged.values():
        ev = m["ev"]
        db.add(ReturnItemResolutionAllocation(
            id=_uuid.uuid4(), company_id=company_id, return_id=return_id,
            return_item_id=return_item_id, resolution_id=ev.id, sale_item_id=m["si"],
            stock_batch_id=ev.stock_batch_id, product_id=product_id, branch_id=branch_id,
            qty=m["qty"], provisional_cost_credit=m["credit"],
            variance_reversed=m["vrev"], created_at=now))

    # ── (3) QARZ DUMI: JISMONIY TOVAR QAYERDA YASHAYDI ──────────────────────
    #  ⚠️  ASL PARTIYA TO'QIB CHIQARILMAYDI: `source_type='return_unattributed'`,
    #      muddat `NULL` (NOMA'LUM), narx — qarzdagi MUZLATILGAN taxmin.
    yangi = []
    for d in p.debt_lines:
        sf = d.shortfall
        # `returned_qty` — AUDIT hisoblagichi; ochiq qarzni KAMAYTIRMAYDI.
        sf.returned_qty = _d(sf.returned_qty) + d.qty
        b = StockBatch(
            id=_uuid.uuid4(), company_id=company_id, product_id=product_id,
            branch_id=branch_id, batch_no=None,
            expiry_date=None,
            qty=d.qty, received_qty=d.qty, remaining_qty=d.qty,
            unit_cost=d.unit_cost, status=SI.OPEN,
            source_type=SOURCE_RETURN_UNATTRIBUTED,
            received_at=now, created_at=now, updated_at=now, row_version=1)
        db.add(b)
        # ⚠️  ANIQ flush: `created_batch_id` FK — U partiya havola qatoridan OLDIN
        #     bazaga tushishi SHART (aloqasiz jadvallar tasodifiy tartibda yoziladi).
        db.flush()
        db.add(ReturnItemShortfallAllocation(
            id=_uuid.uuid4(), company_id=company_id, return_id=return_id,
            return_item_id=return_item_id, shortfall_id=sf.id, created_batch_id=b.id,
            product_id=product_id, branch_id=branch_id, qty=d.qty,
            provisional_unit_cost=d.unit_cost, provisional_cost_credit=d.credit,
            created_at=now))
        yangi.append(b)
    return yangi


def assert_caps(db: Session, *, return_id, shortfall_ids, sale_item_ids) -> list[str]:
    """POST-APPLY tasdig'i (v3 R3) — reja chegarasini BAZA qatorlaridan qayta isbotlaydi.

    Reja xotirada hisoblangan; bu tekshiruv yozilgan qatorlarni SQL bilan
    o'qiydi. Kelajakdagi o'zgarish chegarani buzsa, u JIMGINA o'tmaydi — butun
    qaytarish 409 bilan qaytariladi. Qaytaradi: buzilishlar ro'yxati (bo'sh = ok).
    """
    db.flush()
    bad: list[str] = []
    LS, LSR = LotShortfall, LotShortfallResolution
    RISA, RIRA = ReturnItemShortfallAllocation, ReturnItemResolutionAllocation

    def _sum(stmt) -> Decimal:
        return LRes.q3(db.execute(stmt).scalar())

    for sid in sorted(shortfall_ids, key=str):
        row = db.execute(select(LS.qty, LS.resolved_qty, LS.returned_qty, LS.sale_item_id)
                         .where(LS.id == sid)).first()
        if row is None:
            continue
        qty, rq, retq, s_si = LRes.q3(row[0]), LRes.q3(row[1]), LRes.q3(row[2]), row[3]
        risa_all = _sum(select(func.coalesce(func.sum(RISA.qty), 0))
                        .where(RISA.shortfall_id == sid))
        risa_this = _sum(select(func.coalesce(func.sum(RISA.qty), 0))
                         .where(RISA.shortfall_id == sid, RISA.return_id == return_id))
        real = _sum(select(func.coalesce(func.sum(LSR.qty), 0))
                    .where(LSR.shortfall_id == sid, LSR.kind == RESOLUTION_REAL))
        # a) shu qaytarishning dumi — dum chegarasidan oshmasin
        if risa_this > max(_ZERO, qty - real - (risa_all - risa_this)):
            bad.append(f"qarz {sid}: dum {risa_this} > ruxsat {max(_ZERO, qty - real - (risa_all - risa_this))}")
        # b) qarz qatorining o'z tovari qty dan ko'p qaytmasin
        own_rev = _ZERO
        if s_si is not None:
            own_rev = _sum(select(func.coalesce(func.sum(RIRA.qty), 0))
                           .join(LSR, LSR.id == RIRA.resolution_id)
                           .where(LSR.shortfall_id == sid, RIRA.sale_item_id == s_si))
        if risa_all + own_rev > qty:
            bad.append(f"qarz {sid}: qaytgan {risa_all + own_rev} > sotilgan {qty}")
        # c) har hodisa o'z miqdoridan ko'p qaytmasin
        for eid, eq, rev in db.execute(
                select(LSR.id, LSR.qty, func.coalesce(func.sum(RIRA.qty), 0))
                .outerjoin(RIRA, RIRA.resolution_id == LSR.id)
                .where(LSR.shortfall_id == sid)
                .group_by(LSR.id, LSR.qty)).all():
            if LRes.q3(rev) > LRes.q3(eq):
                bad.append(f"hodisa {eid}: qaytgan {LRes.q3(rev)} > {LRes.q3(eq)}")
        # e) javondagi o'z U tovari ochiq qarzdan oshmasin
        own_u = _sum(select(func.coalesce(func.sum(StockBatch.remaining_qty), 0))
                     .join(RISA, RISA.created_batch_id == StockBatch.id)
                     .where(RISA.shortfall_id == sid,
                            StockBatch.status.in_(sorted(SI.QUANTITY_BEARING))))
        if own_u > qty - rq:
            bad.append(f"qarz {sid}: javondagi U {own_u} > ochiq qarz {qty - rq}")
        # f) hisoblagich hodisalar bilan mos
        if retq != risa_all:
            bad.append(f"qarz {sid}: returned_qty {retq} != Σ dum {risa_all}")

    SIA, RILA = SaleItemLotAllocation, ReturnItemLotAllocation
    for si in sorted({s for s in sale_item_ids if s is not None}, key=str):
        allocs = {b: LRes.q3(q) for b, q in db.execute(
            select(SIA.stock_batch_id, func.coalesce(func.sum(SIA.qty), 0))
            .where(SIA.sale_item_id == si).group_by(SIA.stock_batch_id)).all()}
        for b, q in db.execute(
                select(RILA.stock_batch_id, func.coalesce(func.sum(RILA.qty), 0))
                .where(RILA.sale_item_id == si).group_by(RILA.stock_batch_id)).all():
            # d) taqsimot bo'yicha qaytish asl ulushdan oshmasin
            if LRes.q3(q) > allocs.get(b, _ZERO):
                bad.append(f"qator {si} partiya {b}: qaytgan {LRes.q3(q)} > "
                           f"{allocs.get(b, _ZERO)}")
    return bad
