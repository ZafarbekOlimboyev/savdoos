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

SOURCE_SHORTFALL = "shortfall"


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


def shortfall_lot(db: Session, *, company_id, branch_id, product: Product,
                  now: datetime) -> StockBatch:
    """Mahsulotning KAMOMAD partiyasi — bittadan ortiq bo'lmaydi (idempotent).

    ⚠️  NEGA MANFIY PARTIYA. Offline chek qayta yuborilganda tovar do'kondan
        JISMONAN chiqib bo'lgan va pul olingan. Agar yaroqli partiya yetmasa,
        uchta yo'l bor edi:

          (a) chekni rad etish        -> pul olingan savdo daftarga TUSHMAYDI;
          (b) qoldiqni jimgina kamaytirib partiyaga tegmaslik
                                      -> `Inventary.qty == Σ remaining_qty`
                                         invarianti BUZILADI va butun partiya
                                         quyi tizimi fail-closed bo'lib qoladi;
          (c) MANFIY kamomad partiyasi -> invariant AYNAN saqlanadi, kamomad esa
                                         nomlangan, ko'rinadigan QARZ bo'lib
                                         qoladi.

        (c) tanlandi. Bu «jimgina partiya o'ylab topish» EMAS: qator ataylab
        MANFIY, `source_type='shortfall'`, FEFO nomzodlariga TUSHMAYDI va
        `GET /lots/products/{id}` da alohida ko'rinadi.

    Kalit `client_uuid` ga yoziladi va `ux_lot_intake_key` (UNIQUE(company_id,
    client_uuid)) uni DB darajasida yagona qiladi — poygada ham ikkinchisi
    yaratilmaydi.
    """
    key = uuid.uuid5(LR.LOT_NS, f"offline_shortfall:{company_id}:{branch_id}:{product.id}")
    b = (db.query(StockBatch)
         .filter(StockBatch.company_id == company_id,
                 StockBatch.client_uuid == key)
         .with_for_update().first())
    if b is not None:
        return b
    b = StockBatch(
        id=uuid.uuid4(), company_id=company_id, branch_id=branch_id,
        product_id=product.id, batch_no=None, expiry_date=None,
        qty=Decimal("0"), received_qty=Decimal("0"), remaining_qty=Decimal("0"),
        # Tannarx: mahsulotning joriy olish narxi. Bu TAXMIN va shunday deb
        # belgilangan — kamomadning haqiqiy partiyasi NOMA'LUM, chunki u
        # umuman qayd etilmagan tovar. Kuzatuvsiz sotuv ham aynan shu narxni
        # ishlatadi (sales.py), ya'ni bu yerda yangi noaniqlik kiritilmaydi.
        unit_cost=_c(getattr(product, "base_buy_price", 0)),
        status=SI.OPEN, source_type=SOURCE_SHORTFALL, client_uuid=key,
        received_at=now, created_at=now, updated_at=now, row_version=1)
    db.add(b)
    db.flush()
    return b


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
        if _q(b.remaining_qty) == 0 and b.source_type != SOURCE_SHORTFALL:
            b.status = SI.DEPLETED
        db.add(SaleItemLotAllocation(
            id=uuid.uuid4(), company_id=company_id, sale_item_id=sale_item_id,
            stock_batch_id=b.id, product_id=b.product_id,
            qty=a.qty, unit_cost=a.unit_cost,
            expiry_date=b.expiry_date, created_at=now))


def take_shortfall(db: Session, *, company_id, branch_id, product: Product,
                   qty: Decimal, now: datetime) -> Alloc:
    """Yetishmagan miqdorni kamomad partiyasiga YOZADI (u yanada manfiylashadi)."""
    b = shortfall_lot(db, company_id=company_id, branch_id=branch_id,
                      product=product, now=now)
    return Alloc(batch=b, qty=_q(qty), unit_cost=_c(b.unit_cost))
