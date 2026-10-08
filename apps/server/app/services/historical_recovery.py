# -*- coding: utf-8 -*-
"""KANONIK HOLAT ZONDLARI — «bu hodisa allaqachon tushganmi?» degan savolga javob.

Bu modul `status='started'` qolgan jurnal qatorini hal qiladi: yozuvchi
commit qilib ulgurgan (W3) yoki umuman yetib bormagan (W2). Jurnalning O'ZI
buni ajrata olmaydi, chunki ikki holatda ham qator AYNI ko'rinadi. Ajratuvchi
— faqat biznes jadvalini O'QISH.

QOIDALAR
========
1. ZOND HECH NARSA YOZMAYDI. Faqat `SELECT`. Yozuvchini «zond» sifatida qayta
   chaqirish TAQIQ: beshta yozuvchi takrorda CHALG'ITUVCHI xato beradi —
   `shift_close` 400 «Smena allaqachon yopilgan», `_pay_supplier_once` 400
   «qarz yo'q» (chunki birinchi urinish qarzni allaqachon yopgan),
   `_cash_op_once` esa 400 «Kassada yetarli naqd yo'q» (birinchi urinishning
   o'z harakati naqdni tushirgan). Bu xatolarni «tushmagan» deb o'qish
   DUBLIKATGA olib borardi.

2. `landed=False` QAYTSA — QAYTA YUBORISH BEXATAR. Sabab: har bir yozuvchi
   o'z tanasini BITTA `db.commit()` bilan yakunlaydi, ya'ni «yarim tushgan»
   holat yo'q. Zond hech narsa topmasa, biznes tranzaksiyasi commit
   BO'LMAGAN (W2) va yozuvchining o'z noyob indeksi hakam bo'lib qoladi.

3. IJARACHI DOIRASI MAJBURIY. `shifts`, `cash_movements`, `stock_movements`
   va `supplier_payments` jadvallarida `company_id` ustuni UMUMAN YO'Q
   (o'lchangan), shu bois doira branch yoki ota-obyekt orqali o'tadi. Ayniqsa
   `ux_cashmov_client_uuid_all` GLOBAL (ijarachi ustuni yo'q), ya'ni
   IntegrityError o'z takrorimizning ISBOTI EMAS — bu `api/v1/cashops.py:225-249`
   da allaqachon yozilgan intizom.

4. SOXTA POZITIVGA QARSHI VAQT GUVOHI. `shift_close` da kalit UMUMAN yo'q
   (yozuvchi `client_uuid` olmaydi, `shifts.client_uuid` ni faqat OCHISH
   yozadi) va legacy `shifts` jadvali YOPGAN xodimni qayd etmaydi — ya'ni
   `status == closed` ni POS orqali yopilgan smena ham qondiradi. Yagona
   portativ atributsiya guvohi — `closed_at`: u `resolve_at(at)` dan yoziladi
   (`services/shifts.py:236`), ya'ni TARIXIY lahzaga teng bo'ladi; odam yoki
   POS yopsa esa devor-soati muhrlanadi. Shu bois to'rt predikatning HAMMASI
   talab qilinadi.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Probe:
    """Zond natijasi. `landed=False` -> qayta yuborish bexatar (qoida 2)."""
    landed: bool
    result_type: str | None = None
    result_id: uuid.UUID | None = None
    detail: dict = field(default_factory=dict)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _uid(v):
    """Payload'dagi matnli id -> UUID; yaroqsiz bo'lsa `None`."""
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError, AttributeError):
        return None


#  ══ 1-4: DTO KALITLI, INDEKS BILAN QO'LLANGAN HODISALAR ═══════════════════
#  Bu to'rtta uchun zond yozuvchining O'Z noyob indeksi predikatini AYNAN
#  takrorlaydi. ⚠️  Yozuvchining oldin-tekshiruvi EMAS: `sale` va `return` da
#  oldin-tekshiruv `deleted_at` ni HISOBGA OLMAYDI, indeks esa oladi
#  (`services/sales.py:151-154` va `initdb.py:722-725`). Zond INDEKS shaklini
#  kuzatishi shart, aks holda yumshoq o'chirilgan hujjat uchun noto'g'ri javob
#  berardi.

def _sale(db: Session, row) -> Probe:
    from app.models.sales import Sale
    s = (db.query(Sale)
         .filter(Sale.client_uuid == row.event_key,
                 Sale.company_id == row.company_id,
                 Sale.deleted_at.is_(None))
         .one_or_none())
    return Probe(True, "sale", s.id) if s else Probe(False)


def _purchase(db: Session, row) -> Probe:
    from app.models.purchasing import Purchase
    p = (db.query(Purchase)
         .filter(Purchase.client_uuid == row.event_key,
                 Purchase.company_id == row.company_id)
         .one_or_none())
    return Probe(True, "purchase", p.id) if p else Probe(False)


def _receiving(db: Session, row) -> Probe:
    from app.models.receiving import Receiving
    r = (db.query(Receiving)
         .filter(Receiving.client_uuid == row.event_key,
                 Receiving.company_id == row.company_id)
         .one_or_none())
    return Probe(True, "receiving", r.id) if r else Probe(False)


def _return(db: Session, row) -> Probe:
    from app.models.sales import Return
    r = (db.query(Return)
         .filter(Return.client_uuid == row.event_key,
                 Return.company_id == row.company_id,
                 Return.deleted_at.is_(None))
         .one_or_none())
    return Probe(True, "return", r.id) if r else Probe(False)


#  ══ 5: SMENA OCHISH — kalit BOR, lekin INDEKS YO'Q ════════════════════════
def _shift_open(db: Session, row) -> Probe:
    """⚠️  `ux_shifts_client_uuid` MAVJUD EMAS (butun repoda topilmaydi).

    Yozuvchining o'zi buni tan oladi (`services/shifts.py:62-68`: «OLDIN-
    TEKSHIRUV, INDEKS KAFOLATI EMAS», qismiy noyob indeks «ATAYLAB bu yerda
    EMAS — ega qaroriga»). Ya'ni bu hodisa uchun YAGONA tranzaksion hakam —
    bizning `ux_hist_plan_event` rezervatsiyamiz, va u dispatch'dan OLDIN
    commit qilingani uchun ayni kalitning ikkinchi dispatch'i yozuvchiga
    UMUMAN yetib bormaydi.

    Kalit qatorga YOZILADI (`shifts.py:163` `client_uuid=client_uuid`) — shu
    bois zond mumkin. `opened_at` vaqt guvohi sifatida QO'SHIMCHA, majburiy
    emas: kalit allaqachon rejaga xos.
    """
    from app.models.shifts import Shift
    s = (db.query(Shift)
         .filter(Shift.client_uuid == row.event_key,
                 Shift.cashier_id == row.actor_employee_id,
                 Shift.branch_id == row.branch_id,
                 Shift.deleted_at.is_(None))
         .one_or_none())
    return Probe(True, "shift", s.id, {"opened_at": str(_utc(s.opened_at))}) if s \
        else Probe(False)


#  ══ 6: SMENA YOPISH — kalit UMUMAN YO'Q ═══════════════════════════════════
def _shift_close(db: Session, row) -> Probe:
    """To'rt predikat — kamrog'i SOXTA POZITIV berardi (qoida 4).

    `result_id` = smenaning O'ZI: u payload'da, ya'ni yozuvchi ishlamasdan ham
    ma'lum. Javobning hammasi qatordan tiklanadi (`counted_cash`,
    `expected_cash`, `difference` — `shifts.py:233-235`).
    """
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    sid = _uid((row.payload or {}).get("shift_id"))
    if sid is None:
        return Probe(False)
    s = db.get(Shift, sid)
    if s is None or s.status != ShiftStatus.closed:
        return Probe(False)
    if s.branch_id != row.branch_id or s.cashier_id != row.actor_employee_id:
        return Probe(False)
    #  VAQT GUVOHI: `closed_at` tarixiy lahzaga TENG bo'lsa — yopgan BIZ edik.
    if _utc(s.closed_at) != _utc(row.occurred_at):
        return Probe(False)
    return Probe(True, "shift", s.id, {
        "id": str(s.id),
        "expected_cash": float(s.expected_cash or 0),
        "counted_cash": float(s.counted_cash or 0),
        "difference": float(s.difference or 0),
    })


#  ══ 7: INVENTARIZATSIYA — 0..N harakat, SHARTLI yoziladi ══════════════════
def _inventory_count(db: Session, row) -> Probe:
    """⚠️  BU YERDA «0 harakat» NOANIQLIK EMAS — bexatar holat.

    Sanoq harakati SHARTLI yoziladi (`api/v1/inventory.py:630`: `if diff != 0
    or ...`), ya'ni HAR BIR qatori qoldiqqa teng bo'lgan sanoq kalitli hech
    narsa yozmaydi. Shu bois zond ikki javob beradi:

      >=1 harakat -> sanoq TUSHGAN. `result_id` yagona qator emas, shu bois
                     jurnal qatorining O'ZI natija havolasi bo'ladi va
                     harakat id'lari `detail` da qayd etiladi.
      0 harakat   -> yo umuman ishlamagan, yo TO'LIQ no-op bo'lgan.

    Ikkinchi holatda qayta yuborish BEXATAR va aynan shu sababli bu hodisa
    «tiklanmaydigan» DEB BELGILANMAYDI: noaniqlik faqat qayta yurish HECH
    NARSANI o'zgartirmaydigan holatda yuzaga keladi. O'lchangan: yozuvchi
    tanasida shartsiz yoziladigan yagona narsa yo'q — `StockMovement` (:639)
    ham, `_audit_log` (:649) ham `if diff != 0` ichida; nol-qoldiqli inventar
    qatori (:541) faqat qator mavjud bo'lmasa qo'shiladi va idempotent; commit esa
    bitta joyda (:699), ya'ni «yarim tushgan» sanoq bo'lishi mumkin emas.

    ⚠️  CHEGARA, OCHIQ AYTILADI: agar bajaruvchi shu hodisadan KEYINGI
        hodisalarni allaqachon yozib, so'ng shu kalitni qayta yuborsa,
        `assert_chronological` uni RAD etadi. Bu loyihalangan fail-closed xulq
        (mutlaq yozuvchini tartibsiz replay buzmasin), nuqson emas.
    """
    from app.models.inventory import StockMovement
    rows = (db.query(StockMovement.id)
            .filter(StockMovement.client_uuid == row.event_key,
                    StockMovement.branch_id == row.branch_id)
            .all())
    if not rows:
        return Probe(False)
    ids = sorted(str(r[0]) for r in rows)
    return Probe(True, "stock_count", row.id,
                 {"changed": len(ids), "movement_ids": ids})


#  ══ 8: HISOBDAN CHIQARISH — harakat SHARTSIZ yoziladi ═════════════════════
def _writeoff(db: Session, row) -> Probe:
    """⚠️  `product_id` MAJBURIY. `ux_stockmov_client_prod_type` ustunlari
        `(client_uuid, product_id, type)` va u GLOBAL (jadvalda `company_id`
        yo'q), shu bois faqat kalit bo'yicha izlash IJARACHI CHEGARASIDAN
        chiqib ketardi. Qo'shimcha `branch_id` — bizning doiramiz.
    """
    from app.models.enums import MovementType
    from app.models.inventory import StockMovement
    pid = _uid((row.payload or {}).get("product_id"))
    if pid is None:
        return Probe(False)
    mv = (db.query(StockMovement)
          .filter(StockMovement.client_uuid == row.event_key,
                  StockMovement.product_id == pid,
                  StockMovement.type == MovementType.writeoff,
                  StockMovement.branch_id == row.branch_id)
          .one_or_none())
    return Probe(True, "stock_movement", mv.id) if mv else Probe(False)


#  ══ 9-10: KASSA AMALI — kalit GLOBAL indeksda ═════════════════════════════
def _cash_op(db: Session, row) -> Probe:
    """Ijarachi doirasi `Shift -> Branch` orqali (jadvalda tenant ustuni yo'q).

    ⚠️  Shu bois IntegrityError o'z takrorimizning ISBOTI EMAS: boshqa
        ijarachining ayni kalitli qatori ham bizning INSERT'ni rad etardi, zond
        esa hech narsa topmasdi. `api/v1/cashops.py:225-249` ayni intizomni
        yozib qo'ygan.
    """
    from app.models.org import Branch
    from app.models.shifts import CashMovement, Shift
    mv = (db.query(CashMovement)
          .join(Shift, Shift.id == CashMovement.shift_id)
          .join(Branch, Branch.id == Shift.branch_id)
          .filter(CashMovement.client_uuid == row.event_key,
                  Branch.company_id == row.company_id)
          .one_or_none())
    return Probe(True, "cash_movement", mv.id,
                 {"shift_id": str(mv.shift_id)}) if mv else Probe(False)


#  ══ 11: MIJOZ QARZ TO'LOVI ════════════════════════════════════════════════
def _customer_payment(db: Session, row) -> Probe:
    """⚠️  Kalit doirasi MIJOZ, do'kon emas: `ux_custpay_client_uuid` ustunlari
        `(customer_id, client_uuid)` (`initdb.py:735-737`).
    """
    from app.models.customers import Customer, CustomerPayment
    cid = _uid((row.payload or {}).get("customer_id"))
    if cid is None:
        return Probe(False)
    pay = (db.query(CustomerPayment)
           .join(Customer, Customer.id == CustomerPayment.customer_id)
           .filter(CustomerPayment.client_uuid == row.event_key,
                   CustomerPayment.customer_id == cid,
                   Customer.company_id == row.company_id)
           .one_or_none())
    return Probe(True, "customer_payment", pay.id) if pay else Probe(False)


#  ══ 12: YETKAZIB BERUVCHIGA TO'LOV ════════════════════════════════════════
def _supplier_payment(db: Session, row) -> Probe:
    """⚠️  Kalit doirasi YETKAZIB BERUVCHI (`(supplier_id, client_uuid)`,
        `initdb.py:738-740`). Jadvalda `company_id` yo'q — doira `Supplier`
        orqali.
    """
    from app.models.purchasing import Supplier, SupplierPayment
    sid = _uid((row.payload or {}).get("supplier_id"))
    if sid is None:
        return Probe(False)
    pay = (db.query(SupplierPayment)
           .join(Supplier, Supplier.id == SupplierPayment.supplier_id)
           .filter(SupplierPayment.client_uuid == row.event_key,
                   SupplierPayment.supplier_id == sid,
                   Supplier.company_id == row.company_id)
           .one_or_none())
    return Probe(True, "supplier_payment", pay.id) if pay else Probe(False)


#: Hodisa turi -> zond. ⚠️  Ro'yxat TO'LIQ bo'lishi SHART: endpoint allowlist'i
#: bilan tengligi test bilan qadalgan (aks holda yangi hodisa turi jimgina
#: tiklanishsiz qolardi va `started` qatori abadiy osilib turardi).
PROBES = {
    "shift_open": _shift_open,
    "shift_close": _shift_close,
    "sale": _sale,
    "purchase": _purchase,
    "receiving": _receiving,
    "return": _return,
    "inventory_count": _inventory_count,
    "writeoff": _writeoff,
    "cash_payin": _cash_op,
    "cash_expense": _cash_op,
    "customer_debt_payment": _customer_payment,
    "supplier_payment": _supplier_payment,
}


def probe(db: Session, row) -> Probe:
    """Kanonik holatni o'qiydi. Hodisa turi noma'lum bo'lsa — fail-closed."""
    fn = PROBES.get(row.event_type)
    if fn is None:
        raise RuntimeError(
            f"tarixiy tiklanish zondi YO'Q: event_type={row.event_type!r} — "
            f"hodisa turi qo'shilib zond yozilmagan")
    return fn(db, row)
