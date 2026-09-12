# -*- coding: utf-8 -*-
"""PARTIYA API (Phase 1) — kuzatuvni yoqish, partiyalarni ko'rish.

⚠️  SOTUV (FEFO) BU YERDA YO'Q. Phase 1 faqat kirimni biladi. Kuzatuvli mahsulot
    Phase 2/3 gacha SOTILMAYDI — eski sotuv yo'li uni `stock_gate` orqali rad
    etadi. Staging'da bu maqbul va ATAYLAB shunday.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.inventory import Inventory, StockBatch
from app.models.org import Branch
from app.services import lot_policy as LP
from app.services import lot_receiving as LR
from app.services import stock_invariant as SI
from app.services.audit import log as audit_log

router = APIRouter(prefix="/lots", tags=["lots"])


class OpeningLot(BaseModel):
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(ge=0, le=1e9, allow_inf_nan=False)
    batch_number: str | None = Field(default=None, max_length=64)
    expiry_date: str | None = None


class EnableIn(BaseModel):
    """Kuzatuvni yoqish — MAVJUD qoldiq aniq hisobga olinishi SHART."""
    product_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    track_expiry: bool = False
    reason: str = Field(min_length=3, max_length=300)     # AUDIT uchun MAJBURIY
    # A) aniq partiyalar bilan ochish, yoki B) bitta `legacy` partiyasi
    opening_lots: list[OpeningLot] | None = None
    legacy_unit_cost: float | None = Field(default=None, ge=0, le=1e9,
                                           allow_inf_nan=False)


def _branch(db: Session, emp: Employee, branch_id):
    b = (db.get(Branch, branch_id) if branch_id else
         db.query(Branch).filter(Branch.company_id == emp.company_id,
                                 Branch.deleted_at.is_(None))
         .order_by(Branch.created_at).first())
    if b is None or b.company_id != emp.company_id:
        raise HTTPException(404, "Filial topilmadi")
    return b


@router.post("/enable")
def enable_tracking(data: EnableIn,
                    emp: Employee = Depends(require("ombor.edit")),
                    db: Session = Depends(get_db)):
    """Mahsulot uchun partiya kuzatuvini YOQADI — bitta tranzaksiyada.

    ⚠️  BU SHUNCHAKI BAYROQNI O'ZGARTIRISH EMAS. Mahsulotda allaqachon qoldiq
        bo'lsa, u qaysi partiyalarga tegishli ekani ANIQLANISHI shart. Aks holda
        kuzatuv yoqilgan lahzada `Inventory.qty == SUM(partiyalar)` invarianti
        DARHOL buzilgan bo'lardi.

        Ikki yo'l:
          A) `opening_lots` — operator qoldiqni partiyalarga BO'LADI;
          B) bitta `legacy` partiyasi — miqdor AYNAN joriy qoldiq, muddat va
             partiya raqami NULL (ular NOMA'LUM va taxmin qilinmaydi), tannarx
             esa ANIQ tasdiqlanadi.

        Qoldiq nolga teng bo'lsa — partiya kerak emas.
    """
    # ── XUSUSIYAT DARVOZASI — PRODUCTION'DA YOPIQ (Phase 2) ─────────────────
    #  Eng birinchi tekshiruv: mahsulot qidirilgunga qadar. Kuzatuvni yoqish
    #  QAYTARIB BO'LMAYDIGAN amal — tarix paydo bo'lgach uni o'chirish yo'li yo'q.
    try:
        LP.assert_activation_allowed()
    except LP.LotActivationNotAllowed as e:
        raise HTTPException(403, str(e)) from e
    p = db.get(Product, data.product_id)
    if p is None or p.company_id != emp.company_id or p.deleted_at is not None:
        raise HTTPException(404, "Mahsulot topilmadi")
    if p.track_lots:
        raise HTTPException(409, f"'{p.name}' allaqachon partiya bo'yicha kuzatiladi")
    br = _branch(db, emp, data.branch_id)
    now = datetime.now(timezone.utc)

    # Muddat kuzatuvi — vaqt zonasi ANIQ tasdiqlangan bo'lishi shart.
    if data.track_expiry:
        try:
            LP.assert_tz_confirmed(db, emp.company_id, br.id)
        except LP.TimezoneNotConfigured as e:
            raise HTTPException(409, str(e)) from e

    inv = LR.inventory_for_update(db, p.id, br.id)
    have = Decimal(str(inv.qty)) if inv is not None else Decimal("0")

    made: list[StockBatch] = []
    if have > 0:
        if data.opening_lots:
            lots = []
            for o in data.opening_lots:
                exp = None
                if o.expiry_date:
                    from datetime import date as _d
                    exp = _d.fromisoformat(o.expiry_date)
                lots.append(LR.LotIn(qty=Decimal(str(o.qty)), expiry_date=exp,
                                     batch_number=o.batch_number,
                                     unit_cost=Decimal(str(o.unit_cost))))
            total = sum((Decimal(str(x.qty)) for x in lots), Decimal("0"))
            if total.quantize(Decimal("0.001")) != have.quantize(Decimal("0.001")):
                raise HTTPException(
                    400, f"Ochilish partiyalari yig'indisi {total} joriy qoldiq {have} "
                         f"ga TENG EMAS. Miqdor taxmin qilinmaydi.")
            made = LR.create_lots(
                db, company_id=emp.company_id, branch_id=br.id, product=p, lots=lots,
                doc_key=f"opening:{p.id}", line_index=0,
                source_type="opening", default_cost=None, now=now)
        else:
            if data.legacy_unit_cost is None:
                raise HTTPException(
                    400, "Mavjud qoldiq bor: `opening_lots` bering yoki `legacy_unit_cost` "
                         "ni ANIQ ko'rsating. Mahsulotning joriy olish narxi JIMGINA "
                         "ishlatilmaydi.")
            made = [LR.open_legacy_lot(
                db, company_id=emp.company_id, branch_id=br.id, product=p, qty=have,
                unit_cost=Decimal(str(data.legacy_unit_cost)), reason=data.reason, now=now)]

    # ── Bayroqlar AYNI tranzaksiyada ────────────────────────────────────────
    p.track_lots = True
    p.track_expiry = bool(data.track_expiry)
    # ⚠️  FAOLLASHUV CHEGARASI — SERVER SOATI, MIJOZGA HECH QACHON BERILMAYDI.
    #     Bu `now` ochilish partiyalari yaratilgan AYNI `now` va AYNI tranzaksiya:
    #     «qachondan boshlab kuzatiladi» va «qaysi qoldiqdan boshlab» bitta
    #     ajralmas fakt bo'lishi shart.
    #
    #     Nega mijozga berilmaydi: POS hech qachon hech qanday server revizyasini
    #     tasdiqlamaydi (`packages/shared` da katalog `rev` ni yuboradigan joy
    #     YO'Q), demak mijoz aks-sado qiladigan har qanday «epoch» yoki versiya
    #     shunchaki so'rov tanasidagi, hujumchi yozadigan son bo'lardi va HECH
    #     NARSANI isbotlamasdi. Shu bois bu belgi FAQAT tasnif/hisobot uchun —
    #     chekni QABUL QILISH qaroriga umuman ta'sir qilmaydi.
    p.lots_activated_at = now
    db.flush()

    # ── YAKUNIY DARVOZA ─────────────────────────────────────────────────────
    try:
        SI.assert_ok(db, emp.company_id, [p.id])
    except Exception as e:      # noqa: BLE001
        db.rollback()
        raise HTTPException(409, f"Kuzatuvni yoqib bo'lmadi — miqdor invarianti "
                                 f"buzilgan bo'lardi: {e}") from e

    audit_log(db, emp.id, "update", "product_lot_tracking", p.id,
              after={"track_lots": True, "track_expiry": bool(data.track_expiry),
                     "lots_activated_at": now.isoformat(),
                     "opening_qty": float(have), "lots": len(made),
                     "reason": data.reason})
    db.commit()
    return {"ok": True, "product_id": str(p.id), "track_lots": True,
            "track_expiry": bool(data.track_expiry),
            "opening_qty": float(have), "lots_created": len(made),
            "lot_ids": [str(b.id) for b in made]}


class ConfirmTzIn(BaseModel):
    branch_id: uuid.UUID | None = None


@router.post("/timezone/confirm")
def confirm_timezone(data: ConfirmTzIn,
                     emp: Employee = Depends(require("sozlamalar.edit")),
                     db: Session = Depends(get_db)):
    """Filial vaqt zonasini muddat kuzatuvi uchun ANIQ tasdiqlaydi.

    Sintaktik yaroqlilik yetarli emas: `Asia/Tashkent` standarti boshqa
    mamlakatdagi do'kon uchun ham "yaroqli" ko'rinadi, lekin bir soatlik farq
    muddat sanasini bir kunga surib yuboradi.
    """
    br = _branch(db, emp, data.branch_id)
    try:
        name = LP.confirm_tz(db, emp.company_id, br.id)
    except LP.TimezoneNotConfigured as e:
        raise HTTPException(400, str(e)) from e
    audit_log(db, emp.id, "update", "expiry_timezone", br.id, after={"timezone": name})
    db.commit()
    return {"ok": True, "branch_id": str(br.id), "timezone": name, "confirmed": True}


@router.get("/products/{product_id}")
def product_lots(product_id: uuid.UUID, branch_id: uuid.UUID | None = None,
                 include_depleted: bool = False,
                 emp: Employee = Depends(require("ombor.view")),
                 db: Session = Depends(get_db)):
    """Mahsulotning partiyalari. Muddat holati HISOBLANADI, saqlanmaydi."""
    p = db.get(Product, product_id)
    if p is None or p.company_id != emp.company_id:
        raise HTTPException(404, "Mahsulot topilmadi")
    br = _branch(db, emp, branch_id)
    q = (db.query(StockBatch)
         .filter(StockBatch.product_id == p.id, StockBatch.branch_id == br.id))
    if not include_depleted:
        q = q.filter(StockBatch.remaining_qty > 0)
    biz = LP.business_date(db, br.id)
    out = []
    for b in q.order_by(StockBatch.expiry_date.asc().nullslast(),
                        StockBatch.received_at.asc(), StockBatch.id.asc()).all():
        out.append({
            "id": str(b.id), "batch_number": b.batch_no,
            "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
            "expired": LP.is_expired(b.expiry_date, biz),
            "received_qty": float(b.received_qty or 0),
            "remaining_qty": float(b.remaining_qty or 0),
            "unit_cost": float(b.unit_cost or 0), "status": b.status,
            "source_type": b.source_type,
            "received_at": b.received_at.isoformat() if b.received_at else None,
        })
    inv = (db.query(Inventory)
           .filter(Inventory.product_id == p.id, Inventory.branch_id == br.id).first())
    return {"product_id": str(p.id), "track_lots": bool(p.track_lots),
            "track_expiry": bool(p.track_expiry), "business_date": biz.isoformat(),
            "inventory_qty": float(inv.qty) if inv else 0.0, "lots": out}
