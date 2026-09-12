# -*- coding: utf-8 -*-
"""PARTIYAGA QAYTARISH — chek asosida, ASL TAQSIMOTNI orqaga o'rash (Phase 3).

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

Usiz uchinchi qaytarish partiyaga sotilganidan KO'PROQ qaytarib,
`remaining_qty` ni `received_qty` dan oshirib yuborardi.

BIR CHEKDA AYNI MAHSULOT IKKI QATORDA
=====================================
`create_sale` qatorlarni birlashtirmaydi, ya'ni bitta chekda ayni mahsulot
IKKI `SaleItem` bo'lishi mumkin va ularning taqsimoti HAR XIL. Eski kod
`cost_of`/`orig_item_of` da OXIRGI qatorni qoldirardi — ya'ni birinchi
qatorning partiyalari ko'rinmasdi. Bu yerda MAHSULOTNING BARCHA qatorlari
(yaratilish tartibida) ko'rib chiqiladi.

QARZ DUMI — QAYTGAN TOVAR QAYERDA YASHAYDI (Phase 3.5)
=====================================================
Sotuvda partiyaga bog'lanmagan miqdor `lot_shortfalls` ga tushgan bo'lishi
mumkin. U tovar HECH QAYSI partiyadan ketmagan — demak qaytganda ham ASL
partiyasi NOMA'LUM.

⚠️  PHASE 3 SHU YERDA XATO QILGAN EDI. U qarzni kamaytirardi va boshqa hech
    narsa qilmasdi. Kitoblar butun qolardi, lekin jismonan qaytgan tovar
    HECH QAYERDA yozilmasdi. O'lchangan:

        sotuv (5, partiyasiz):  qoldiq −5 | partiyalar 0 | qarz 5
        2 dona qaytdi:          qoldiq −3 | partiyalar 0 | qarz 3
        -> javonda 2 dona, tizimda 0.

⚠️  ARIFMETIK CHEKLOV — MODEL TANLOVINI SHU BELGILAYDI. Jismoniy qaytish
    qoldiqni +k qiladi, ya'ni

        +k = Δ(Σpartiya) − Δ(Σqarz)

    Demak model YO partiya yaratadi VA qarzga tegmaydi, YO qarzni kamaytiradi
    VA partiya yaratmaydi. IKKALASI ham bo'lsa qoldiq +2k bo'lishi kerak edi.

    Phase 3.5 BIRINCHISINI tanlaydi:

        qaytarishda: Inventory +k,  ATRIBUTSIYASIZ partiya +k,  qarz o'zgarmas

    Tarixiy qarz («5 dona atributsiyasiz KETDI») — o'tgan fakt; tovarning
    qaytishi — BOSHQA fakt. Ularni netlash ikki har xil hodisani
    aralashtirardi va tovarni ko'rinmas qilardi.

⚠️  «SOTILADIMI?» — ANIQ JAVOB: QARZ YOPILMAGUNCHA YO'Q, VA BU TO'G'RI.
    Qarz ochiq ekan `Inventory.qty` undan k ga past turadi (invariantning
    o'zi shunday), sotuv esa `Inventory.qty` bilan chegaralangan. Ya'ni
    javondagi 2 dona qarz hisobga olinmaguncha sotilmaydi. Bu kamchilik
    emas: tizim «5 dona qayerdan kelgani» ga javob topmasdan turib o'sha
    tovarni sotsa, mavjud bo'lmagan zaxirani sotgan bo'lardi. Qarz
    yopilgach (yoki inventarizatsiya ortiqchani topgach) qoldiq ko'tariladi
    va atributsiyasiz partiya FEFO orqali oddiy sotiladi.

TANNARX — IKKI HADLI, SOTUVDAGIDEK
==================================
    cost_total = Σ(k × asl_partiya_narxi) + cost_unresolved
    cost_unresolved = Σ(k × qarzdagi MUZLATILGAN taxminiy narx)

⚠️  Ikkinchi hadsiz 100% qaytarilgan chek ABADIY zarar qoldirardi: daromad
    0 ga tushardi, tannarxda esa taxminiy ulush qolib ketardi. Sotuv
    (`SaleItem.cost_unresolved`) aynan shu ikki hadni yozadi — qaytarish ham
    shunday yozmasa, hisobotlar hech qachon nolga kelmasdi.
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inventory import (LotShortfall, ReturnItemLotAllocation,
                                  SaleItemLotAllocation, StockBatch)
from app.services import stock_invariant as SI


class ReturnAttributionError(ValueError):
    """Qaytarilayotgan miqdorni asl taqsimotga bog'lab bo'lmadi."""


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def open_debt(sf) -> Decimal:
    """YOPILMAGAN qarz — YAGONA ta'rif.

    ⚠️  `returned_qty` BU YERGA KIRMAYDI (Phase 3.5 tuzatishi). Qarz —
        «shuncha dona atributsiyasiz KETDI» degan TARIXIY fakt. Tovarning
        keyinchalik qaytib kelishi BOSHQA hodisa: u YANGI, atributsiyasiz
        partiya tug'diradi (`apply()` izohiga qarang). Ikkovini netlash
        arifmetik jihatdan mumkin emas — qoldiq +2k bo'lib ketardi — va
        ikki har xil faktni aralashtirardi.

        Phase 3 da `returned_qty` shu ayirmada edi; natijada kitoblar butun
        qolib, jismonan qaytgan tovar HECH QAYERDA yozilmasdi.
    """
    return _d(sf.qty) - _d(sf.resolved_qty)


@dataclass
class ReturnPlan:
    """Bajarishdan OLDIN to'liq hisoblangan reja."""
    lot_lines: list = field(default_factory=list)    # [(sale_item_id, StockBatch, qty, unit_cost)]
    debt_lines: list = field(default_factory=list)   # [(LotShortfall, qty, prov_unit_cost)]

    @property
    def exact_cost(self) -> Decimal:
        return sum((q * c for _si, _b, q, c in self.lot_lines), Decimal("0"))

    @property
    def unresolved_cost(self) -> Decimal:
        return sum((q * c for _sf, q, c in self.debt_lines), Decimal("0"))

    @property
    def total_qty(self) -> Decimal:
        return (sum((q for _si, _b, q, _c in self.lot_lines), Decimal("0"))
                + sum((q for _sf, q, _c in self.debt_lines), Decimal("0")))


def sale_items_for(db: Session, sale_id, product_id) -> list:
    """Chekdagi SHU mahsulotning BARCHA qatorlari — yaratilish tartibida.

    ⚠️  «Oxirgi qator» yetmaydi: bitta chekda ayni mahsulot ikki marta
        bo'lishi mumkin va ularning partiyalari HAR XIL.
    """
    from app.models.sales import SaleItem
    return (db.query(SaleItem)
            .filter(SaleItem.sale_id == sale_id, SaleItem.product_id == product_id)
            .order_by(SaleItem.id).all())


def _returned_so_far(db: Session, sale_item_id) -> dict:
    """{stock_batch_id: qaytarilgan miqdor} — kumulyativ chegara uchun."""
    rows = (db.query(ReturnItemLotAllocation.stock_batch_id,
                     func.coalesce(func.sum(ReturnItemLotAllocation.qty), 0))
            .filter(ReturnItemLotAllocation.sale_item_id == sale_item_id)
            .group_by(ReturnItemLotAllocation.stock_batch_id).all())
    return {str(b): _d(q) for b, q in rows}


def plan(db: Session, *, company_id, branch_id, product_id, sale_items,
         qty: Decimal) -> ReturnPlan:
    """Qaytarilayotgan miqdorni asl taqsimotga bog'laydi. HECH NARSA yozmaydi.

    Qulflar: partiyalar va qarz qatorlari FOR UPDATE olinadi — allokatsiya
    qatori ularga FK bilan bog'lanadi va FK `KEY SHARE` dan keyin `FOR UPDATE`
    so'rash qulfni OSHIRISH bo'lib deadlock tug'dirardi (Phase 2.5 darsi).
    """
    left = _d(qty)
    p = ReturnPlan()
    for si in sale_items:
        if left <= 0:
            break
        done = _returned_so_far(db, si.id)
        # ⚠️  TARTIB DETERMINISTIK BO'LISHI SHART. `created_at` YETMAYDI: bitta
        #     sotuvning barcha ulushlari AYNI `now` bilan yoziladi, ya'ni u
        #     TENGLASHADI va keyingi mezon — tasodifiy UUID — tartibni har
        #     chaqiruvda O'ZGARTIRARDI. Natijada AYNI qaytarish gohida D10 ga,
        #     gohida D20 ga tushardi.
        #
        #     Shu bois tartib SOTUV qoidasining o'zi: muddat bo'yicha (FEFO),
        #     keyin yozuv vaqti, keyin partiya id'si. `expiry_date` ulushda
        #     SURAT sifatida saqlangan — ya'ni tartib partiyaning KEYINGI
        #     o'zgarishlaridan ham himoyalangan.
        allocs = (db.query(SaleItemLotAllocation)
                  .filter(SaleItemLotAllocation.sale_item_id == si.id)
                  .order_by(SaleItemLotAllocation.expiry_date.asc().nullslast(),
                            SaleItemLotAllocation.created_at,
                            SaleItemLotAllocation.stock_batch_id).all())
        for a in allocs:
            if left <= 0:
                break
            cap = _d(a.qty) - done.get(str(a.stock_batch_id), Decimal("0"))
            if cap <= 0:
                continue
            take = min(cap, left)
            b = (db.query(StockBatch).filter(StockBatch.id == a.stock_batch_id)
                 .with_for_update().first())
            if b is None:
                raise ReturnAttributionError(
                    "Asl partiya topilmadi — qaytarishni bog'lab bo'lmaydi")
            # ⚠️  `void` partiya invariant yig'indisidan CHIQARILGAN
            #     (`stock_invariant.EXCLUDED`). Unga qo'shish qoldiqni
            #     partiyalar yig'indisidan AJRATIB yuborardi — JIMGINA emas,
            #     ANIQ rad etamiz.
            if b.status not in SI.QUANTITY_BEARING:
                raise ReturnAttributionError(
                    f"Asl partiya holati '{b.status}' — unga tovar qaytarib "
                    f"bo'lmaydi. Omborga qaytarmasdan (restock'siz) qaytaring.")
            if b.branch_id != branch_id:
                raise ReturnAttributionError(
                    "Asl partiya boshqa filialda — qaytarish shu filialga "
                    "yozilmoqda. Restock'siz qaytaring yoki asl filialda qabul qiling.")
            # `unit_cost` — ASL SOTUVDAGI narx, partiyaning BUGUNGI narxi emas.
            p.lot_lines.append((si.id, b, take, _d(a.unit_cost)))
            left -= take

        if left <= 0:
            break
        # ── QARZ DUMI ────────────────────────────────────────────────────────
        sf = (db.query(LotShortfall)
              .filter(LotShortfall.sale_item_id == si.id)
              .with_for_update().first())
        if sf is not None:
            open_q = open_debt(sf)
            if open_q > 0:
                take = min(open_q, left)
                # Taxminiy narx — qarz qatoridagi MUZLATILGAN qiymat.
                # `base_buy_price` kirimda o'zgargan bo'lishi mumkin va u
                # chekka yozilgan taxminni QAYTA HISOBLAB yuborardi.
                p.debt_lines.append((sf, take, _d(sf.unit_cost)))
                left -= take

    if left > 0:
        raise ReturnAttributionError(
            f"Qaytarilayotgan miqdorning {left} donasini asl chek partiyalariga "
            f"bog'lab bo'lmadi. Tizim TAXMIN QILMAYDI — omborga qaytarmasdan "
            f"(restock'siz) qaytaring.")
    return p


SOURCE_RETURN_UNATTRIBUTED = "return_unattributed"


def apply(db: Session, p: ReturnPlan, *, return_item_id, company_id, branch_id,
          product_id, now: datetime) -> list:
    """Rejani BAJARADI. Qaytaradi: yaratilgan ATRIBUTSIYASIZ partiyalar ro'yxati.

    `Inventory` ni bu funksiya O'ZGARTIRMAYDI — uni chaqiruvchi (qaytarish
    yo'li) o'zining `restock` mantig'i ichida qiladi, chunki u qatorni
    allaqachon qulflagan.
    """
    for si_id, b, q, ucost in p.lot_lines:
        b.remaining_qty = _d(b.remaining_qty) + q
        b.updated_at = now
        # ⚠️  BO'SHAGAN PARTIYA QAYTA OCHILADI. `depleted` — «hozir nol» degani,
        #     «abadiy yopiq» emas; ikkala holat ham miqdor tashiydi
        #     (`QUANTITY_BEARING`), shu bois invariant buzilmaydi. Ochmasdan
        #     qoldirish esa FEFO ni undan sotmaydigan qilib qo'yardi va tovar
        #     javonda turgani holda «yo'q» bo'lib ko'rinardi.
        if b.status == SI.DEPLETED and _d(b.remaining_qty) > 0:
            b.status = SI.OPEN
        # ⚠️  MUDDATI O'TGAN PARTIYA JISMONAN qaytadi va MUDDATI O'TGANLIGICHA
        #     qoladi. Muddat — saqlanadigan holat emas, HISOB (`lot_policy`),
        #     shu bois bu yerda qiladigan ish YO'Q va bu ATAYLAB shunday:
        #     qaytgan tovarni «yangi» qilib ko'rsatish YOLG'ON bo'lardi.
        db.add(ReturnItemLotAllocation(
            id=_uuid.uuid4(), company_id=company_id,
            return_item_id=return_item_id, sale_item_id=si_id,
            stock_batch_id=b.id, product_id=product_id,
            qty=q, unit_cost=ucost, created_at=now))

    # ── QARZ DUMI: JISMONIY TOVAR QAYERDA YASHAYDI ──────────────────────────
    #
    # ⚠️  PHASE 3 XATOSI VA UNING O'LCHOVI. Phase 3 da bu miqdor FAQAT qarzni
    #     kamaytirardi. Kitoblar butun qolardi, lekin jismonan qaytgan tovar
    #     HECH QAYERDA yozilmасdi — o'lchandi:
    #
    #         sotuv (5, partiyasiz):  qoldiq −5 | partiyalar 0 | qarz 5
    #         2 dona qaytdi:          qoldiq −3 | partiyalar 0 | qarz 3
    #         -> javonda 2 dona bor, tizimda ular YO'Q.
    #
    # ⚠️  ARIFMETIK CHEKLOV. Jismoniy qaytish qoldiqni +k qiladi, demak
    #         +k = Δ(Σpartiya) − Δ(Σqarz)
    #     ya'ni model YO partiya yaratadi VA qarzga tegmaydi, YO qarzni
    #     kamaytiradi VA partiya yaratmaydi. IKKALASI ham bo'lsa qoldiq +2k
    #     bo'lishi kerak edi — ya'ni imkonsiz.
    #
    #     Phase 3.5 BIRINCHISINI tanlaydi: tovar qaytdi, demak u PARTIYA
    #     bo'lsin. Tarixiy qarz esa O'ZGARMAYDI — u boshqa, o'tgan hodisa
    #     («5 dona atributsiyasiz ketdi») va uni qaytish bilan netlash ikki
    #     har xil faktni aralashtirardi.
    #
    # ⚠️  ASL PARTIYA TO'QIB CHIQARILMAYDI. Bu tovar qaysi kogortadan kelgani
    #     NOMA'LUM — shu bois `source_type='return_unattributed'`, muddat esa
    #     `NULL` (NOMA'LUM, taxmin QILINMAYDI). Narx — qarz qatoridagi
    #     MUZLATILGAN taxmin: chek o'sha narxda hisoblangan edi.
    yangi = []
    for sf, q, prov in p.debt_lines:
        # `returned_qty` — AUDIT havolasi: «shu qarzning k donasi qaytib keldi».
        # U ochiq qarzni KAMAYTIRMAYDI (yuqoridagi arifmetik cheklov).
        sf.returned_qty = _d(sf.returned_qty) + q
        b = StockBatch(
            id=_uuid.uuid4(), company_id=company_id, product_id=product_id,
            branch_id=branch_id, batch_no=None,
            expiry_date=None,              # NOMA'LUM — ochiq qoldiriladi
            qty=q, received_qty=q, remaining_qty=q,
            unit_cost=prov, status=SI.OPEN,
            source_type=SOURCE_RETURN_UNATTRIBUTED,
            received_at=now, created_at=now, updated_at=now, row_version=1)
        db.add(b)
        yangi.append(b)
    return yangi
