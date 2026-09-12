# -*- coding: utf-8 -*-
"""FEFO TAQSIMOTI (Phase 2) — sotuvda qaysi partiyadan qancha ketishini hal qiladi.

NOMLASH HALOL BO'LSIN
=====================
«FEFO» = First-Expired-First-Out. Bu nom FAQAT `track_expiry=True` mahsulot uchun
to'g'ri. `track_expiry=False` bo'lganda barcha partiyalarda `expiry_date IS NULL`
va saralash `received_at` ga tushadi — ya'ni bu AMALDA **FIFO** (kirish tartibi).
Ikkalasini bir nom bilan atash keyinchalik «nega muddati kechroq tovar oldin
ketdi?» degan noto'g'ri kutish tug'dirardi. Shu bois `ordering_mode()` qaysi
semantika ishlaganini ANIQ qaytaradi va hisobotlarga ham shu nom chiqadi.

SARALASH TARTIBI (aynan `ix_lot_fefo` ustunlar tartibi)
        expiry_date ASC NULLS LAST,
        received_at ASC,
        created_at  ASC,
        id          ASC
`id` oxirgi tayanch — ikki partiya hamma narsada teng bo'lsa ham tartib
DETERMINISTIK bo'lishi shart, aks holda ikki kassa bir xil savatni har xil
partiyadan yechib, keyin hisobotlar farq qilardi.

NULL MUDDAT SIYOSATI (`track_expiry=True` uchun)
        NULL — «muddat NOMA'LUM», «muddatsiz» EMAS.
    NULLS LAST tanlandi: ma'lum va yaroqli muddatli tovar OLDIN ketadi, noma'lum
    muddatli (legacy/ochilish) partiya esa faqat ma'lumlari tugagach ishlatiladi.
    Muqobil variant — noma'lum muddatli tovarni umuman sotmaslik — chakana savdo
    uchun YOMONROQ: `POST /lots/enable` da ochilgan legacy partiya do'kondagi
    HAQIQIY tovar bo'lib, uni sotib bo'lmasa do'kon ishlay olmay qolardi.

⚠️  KAMOMAD PARTIYASI (`source_type='shortfall'`) FEFO MANBAI EMAS.
    Nomzodlar `remaining_qty > 0` bilan filtrlanadi, kamomad partiyasi esa MANFIY —
    demak u hech qachon manba sifatida tanlanmaydi. `ix_lot_fefo` ham aynan shu
    shart bilan qurilgan (initdb.py), ya'ni filtr indeksga ham mos.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.inventory import SaleItemLotAllocation, StockBatch
from app.services import lot_receiving as LR
from app.services import stock_invariant as SI

# Miqdor NUMERIC(14,3), pul NUMERIC(14,2) — model bilan AYNAN bir xil.
Q = Decimal("0.001")
C = Decimal("0.01")

MODE_FEFO = "fefo"        # muddat bo'yicha (track_expiry=True)
MODE_FIFO = "fifo"        # kirish tartibi bo'yicha (track_expiry=False)

# ⚠️  ESKIRGAN. Phase 2 da kamomad `stock_batches` ga MANFIY qator bo'lib
#     tushardi va `source_type='shortfall'` deb belgilanardi. Phase 2.5 da qarz
#     `lot_shortfalls` jadvaliga ko'chirildi — jismoniy partiya endi HECH QACHON
#     manfiy emas. Bu doimiy FAQAT eski qatorlarni KO'CHIRISH uchun qoldi
#     (`initdb._migrate_shortfall_lots`) va yangi partiyaga YOZILMAYDI.
LEGACY_SOURCE_SHORTFALL = "shortfall"


class InsufficientLots(ValueError):
    """Qoldiq yetarli ko'rinadi, lekin yaroqli partiyalar yetmaydi.

    ⚠️  Bu MA'LUMOT NOMUVOFIQLIGI alomati, oddiy «tovar tugadi» emas. Jimgina
        manfiy partiya yasab sotib yuborish miqdor invariantini buzardi va
        kamomadni KO'RINMAS qilardi. Shu bois onlayn sotuv FAIL-CLOSED.
    """


def _q(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Q, rounding=ROUND_HALF_UP)


def _c(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(C, rounding=ROUND_HALF_UP)


@dataclass
class Alloc:
    """Bitta partiyadan olinadigan ulush. `unit_cost` — O'SHA partiyaniki."""
    batch: StockBatch
    qty: Decimal
    unit_cost: Decimal


def ordering_mode(product: Product) -> str:
    """Qaysi semantika ishlayapti — hisobot va xabarlar shuni aytsin."""
    return MODE_FEFO if getattr(product, "track_expiry", False) else MODE_FIFO


def candidates(db: Session, *, company_id, branch_id, product_id,
               biz_date: date | None, include_expired: bool = False,
               lock: bool = False) -> list[StockBatch]:
    """Sotuvga YAROQLI partiyalar, FEFO/FIFO tartibida.

    Chiqarib tashlanadi:
      · `void`                — miqdor tashimaydi (stock_invariant.EXCLUDED);
      · `remaining_qty <= 0`  — tugagan, va kamomad partiyasi ham SHU YERDA tushadi;
      · muddati o'tgan        — `include_expired=False` bo'lsa (odatiy sotuv).

    ⚠️  Muddati o'tgan partiya QOLDIQDAN chiqarilmaydi — u javonda turibdi va
        `Inventory.qty` da hisobga olinadi. Bu yerda u faqat AVTOMATIK sotuvdan
        chetlatiladi.
    """
    q = (db.query(StockBatch)
         .filter(StockBatch.company_id == company_id,
                 StockBatch.branch_id == branch_id,
                 StockBatch.product_id == product_id,
                 StockBatch.status.in_(sorted(SI.QUANTITY_BEARING)),
                 StockBatch.remaining_qty > 0))
    if not include_expired and biz_date is not None:
        q = q.filter((StockBatch.expiry_date.is_(None))
                     | (StockBatch.expiry_date >= biz_date))
    q = q.order_by(StockBatch.expiry_date.asc().nullslast(),
                   StockBatch.received_at.asc(),
                   StockBatch.created_at.asc(),
                   StockBatch.id.asc())
    if lock:
        # ⚠️  QULF TARTIBI VA BU QULFNING HAQIQIY ROLI.
        #
        #     Chaqiruvchi bu paytda mahsulotning `Inventory` qatorini allaqachon
        #     `with_for_update` bilan ushlab turadi (sotuv ham, qabul ham shunday
        #     qiladi), va u GLOBAL tartibda (`sorted(product_id)`) olinadi. Demak
        #     AYNI mahsulotga tegayotgan ikki tranzaksiya partiyalarga yetib
        #     kelishdan OLDIN `Inventory` qatorida navbatga turadi — partiya
        #     qulflari orasida halqa (deadlock) hosil bo'la olmaydi.
        #
        #     HALOL BO'LAYLIK: aynan shu sababdan OVERSELL'ni to'sadigan narsa
        #     `Inventory` qulfi, bu yerdagi qulf EMAS. Manfiy nazorat buni
        #     isbotladi: shu `FOR UPDATE` ni olib tashlaganda ham «ikki kassa bir
        #     partiyani sotdi» sinovi YASHIL qoldi. Qulf baribir saqlanadi —
        #     u `Inventory` qulfini OLMAYDIGAN kelajakdagi yozuvchiga qarshi
        #     ikkinchi qatlam (masalan partiya tahriri yoki ko'chirish). Uni
        #     «oversell shu yerda to'siladi» deb o'qish XATO bo'lardi.
        q = q.with_for_update()
    return q.all()


def plan(batches: list[StockBatch], want: Decimal) -> tuple[list[Alloc], Decimal]:
    """Tartiblangan partiyalardan `want` miqdorni yechadi. HECH NARSA YOZMAYDI.

    Qaytaradi: (ulushlar, YETISHMAGAN miqdor). Yetishmagan 0 bo'lsa — to'liq
    qoplandi.
    """
    left = _q(want)
    out: list[Alloc] = []
    for b in batches:
        if left <= 0:
            break
        have = _q(b.remaining_qty)
        if have <= 0:
            continue
        take = have if have < left else left
        out.append(Alloc(batch=b, qty=_q(take), unit_cost=_c(b.unit_cost)))
        left = _q(left - take)
    return out, left


def weighted_unit_cost(allocs: list[Alloc], fallback: Decimal) -> Decimal:
    """Ulushlarning OG'IRLANGAN o'rtacha tannarxi — `SaleItem.unit_cost` uchun.

        Σ(qty × unit_cost) / Σ(qty)

    ⚠️  NEGA AYNAN BU QIYMAT SAQLANADI. Hisobotlar IKKI xil o'qiydi:
        `Sale.cost_total` (reports.py) va `SaleItem.qty × SaleItem.unit_cost`
        (reports.py, qator-darajali foyda). Bugun bu ikkisi AYNAN teng. Shu bois
        `cost_total` ham SHU yaxlitlangan qiymatdan hisoblanadi — aks holda bitta
        ekranda ikki xil foyda ko'rinardi.

        Yaxlitlash qoldig'i (birlik uchun eng ko'pi 0.005 so'm) partiyalarda
        YO'QOLMAYDI: `sale_item_lot_allocations` har partiyaning ANIQ narxini
        saqlaydi, ya'ni haqiqiy COGS doim tiklanadi.
    """
    tot = sum((a.qty for a in allocs), Decimal("0"))
    if tot <= 0:
        return _c(fallback)
    money = sum((a.qty * a.unit_cost for a in allocs), Decimal("0"))
    return _c(money / tot)


def exact_cost(allocs: list[Alloc]) -> Decimal:
    """ANIQ COGS — `Σ(qty × unit_cost)`, og'irlangan o'rtachadan HISOBLANMAYDI.

    ⚠️  NEGA ALOHIDA QIYMAT KERAK. Og'irlangan o'rtacha 2 xonaga yaxlitlanadi va
        undan qayta ko'paytirilsa ANIQ summa YO'QOLADI:

            100×55 + 20×57            = 6640.00   (haqiqiy)
            120 × 55.33 (yaxlitlangan) = 6639.60   (0.40 yo'qoldi)

        Buxgalteriya haqiqati birinchi qatorda. Shu bois `SaleItem.cost_total`
        AYNAN shu funksiyadan yoziladi, `unit_cost` esa faqat KO'RSATISH va
        birlik-darajasidagi taqqoslash uchun qoladi (masalan «tannarxdan arzon
        sotildi» hisoboti).

    Har ko'paytma o'zi 2 xonaga yaxlitlanadi (pul modeli NUMERIC(14,2)), so'ng
    qo'shiladi — ya'ni natija saqlanadigan ustunga AYNAN sig'adi.
    """
    return sum((_c(a.qty * a.unit_cost) for a in allocs), Decimal("0"))


def record_shortfall(db: Session, *, company_id, branch_id, product: Product,
                     sale_item_id, qty: Decimal, now: datetime, reason: str | None = None):
    """TAQSIMLANMAGAN QARZNI yozadi. JISMONIY partiyaga TEGMAYDI.

    ⚠️  NEGA PARTIYA EMAS. Phase 2 da yetishmagan miqdor `stock_batches` ga
        MANFIY qator bo'lib tushardi. Lekin `StockBatch` — jismoniy qabul
        kogortasi; manfiy miqdor javonda turgan tovar EMAS. Uni o'sha jadvalda
        saqlash muddat hisoboti, inventarizatsiya va ko'chirishni yolg'on
        javobga olib borardi. Endi jismoniy partiya HAR DOIM `>= 0`, qarz esa
        `lot_shortfalls` da (`Inventory.qty == SUM(partiya) - SUM(qarz)`).

    ⚠️  «JIMGINA PARTIYA O'YLAB TOPISH» EMAS: bu qator ataylab QARZ deb
        nomlangan, chek qatoriga bog'langan va yopilmaguncha ochiq turadi.

    Tannarx: mahsulotning joriy olish narxi. Bu TAXMIN va shunday deb
    belgilangan — qarzning haqiqiy partiyasi ta'rifan noma'lum. Kuzatuvsiz
    sotuv ham aynan shu narxni ishlatadi, ya'ni yangi noaniqlik kiritilmaydi.
    """
    from app.models.inventory import LotShortfall
    row = LotShortfall(
        id=uuid.uuid4(), company_id=company_id, branch_id=branch_id,
        product_id=product.id, sale_item_id=sale_item_id,
        qty=_q(qty), resolved_qty=Decimal("0"),
        unit_cost=_c(getattr(product, "base_buy_price", 0)),
        reason=reason or "offline replay: yaroqli partiya yetmadi",
        created_at=now)
    db.add(row)
    return row


def shortfall_cost(product: Product, qty: Decimal) -> Decimal:
    """Qarz qismining COGS'i — aniq COGS yig'indisiga qo'shiladi."""
    return _c(_q(qty) * _c(getattr(product, "base_buy_price", 0)))


def apply(db: Session, *, sale_item_id, company_id, allocs: list[Alloc],
          now: datetime) -> None:
    """Ulushlarni YOZADI va partiyalar qoldig'ini kamaytiradi.

    `status` yangilanadi: qoldiq 0 ga tushsa `depleted`. Ikkalasi ham miqdor
    tashiydi (`QUANTITY_BEARING`), ya'ni invariant o'zgarmaydi — bu faqat
    hayot sikli belgisi.
    """
    for a in allocs:
        b = a.batch
        b.remaining_qty = _q(_q(b.remaining_qty) - a.qty)
        b.updated_at = now
        if _q(b.remaining_qty) == 0:
            b.status = SI.DEPLETED
        db.add(SaleItemLotAllocation(
            id=uuid.uuid4(), company_id=company_id, sale_item_id=sale_item_id,
            stock_batch_id=b.id, product_id=b.product_id,
            qty=a.qty, unit_cost=a.unit_cost,
            expiry_date=b.expiry_date, created_at=now))
