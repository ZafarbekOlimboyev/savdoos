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
from sqlalchemy import func
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
    # ⚠️  QARZ ALOHIDA KO'RSATILADI. Invariant ikki hadli
    #     (`Inventory.qty == SUM(partiya) - SUM(qarz)`), shu bois faqat
    #     partiyalarni ko'rsatish raqamlarni ZID qilib ko'rsatardi.
    from app.models.inventory import LotShortfall as _LS
    _debt = (db.query(func.coalesce(func.sum(_LS.qty - _LS.resolved_qty), 0))
             .filter(_LS.company_id == emp.company_id, _LS.branch_id == br.id,
                     _LS.product_id == p.id, _LS.qty > _LS.resolved_qty).scalar())
    return {"product_id": str(p.id), "track_lots": bool(p.track_lots),
            "track_expiry": bool(p.track_expiry), "business_date": biz.isoformat(),
            "inventory_qty": float(inv.qty) if inv else 0.0,
            "unresolved_shortfall_qty": float(_debt or 0),
            "lots": out}


class ResolveShortfallIn(BaseModel):
    """Qarzni HAQIQIY partiyaga bog'lash."""
    stock_batch_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    reason: str = Field(min_length=3, max_length=300)     # AUDIT uchun MAJBURIY
    client_uuid: uuid.UUID | None = None                  # idempotentlik


@router.post("/shortfalls/{shortfall_id}/resolve")
def resolve_shortfall(shortfall_id: uuid.UUID, data: ResolveShortfallIn,
                      emp: Employee = Depends(require("ombor.edit")),
                      db: Session = Depends(get_db)):
    """QARZNI haqiqiy partiyaga yopadi. `Inventory.qty` O'ZGARMAYDI.

    ⚠️  NEGA QOLDIQ O'ZGARMASLIGI SHART. Qoldiq sotuv paytida ALLAQACHON
        kamaytirilgan — tovar jismonan ketgan. Qarz miqdor emas, ATRIBUTSIYA
        (qaysi partiyadan ketgani) qarzi. Shu bois yopish ikki tomonni BARAVAR
        siljitadi:

            partiya.remaining_qty -= k        (SUM(partiya) -= k)
            qarz.resolved_qty     += k        (SUM(qarz)    -= k)

        Ikki hadli invariant esa:
            Inventory.qty == SUM(partiya) - SUM(qarz)
        ya'ni ikkala had ham `k` ga kamayadi va AYIRMA O'ZGARMAYDI. Qoldiqni
        bu yerda qo'shish yoki ayirish MA'LUMOTNI BUZARDI (tovar ikki marta
        hisobga olinardi).

    ⚠️  TARIXIY COGS QAYTA YOZILMAYDI. `SaleItem.cost_total` — o'zgarmas surat.
        Yopishda haqiqiy partiya narxi ma'lum bo'ladi, lekin chek qayta
        hisoblanmaydi (Phase 2.5 talabi: «kelajakdagi narx o'zgarishi tarixiy
        COGS'ni o'zgartirmasin»). Farq qarz qatorida QOLADI va audit orqali
        ko'rinadi — ya'ni u yo'qolmaydi, lekin tarixni ham buzmaydi.
    """
    from app.models.inventory import LotShortfall
    sf = db.get(LotShortfall, shortfall_id)
    if sf is None or sf.company_id != emp.company_id:
        raise HTTPException(404, "Qarz topilmadi")

    # IDEMPOTENTLIK: ayni `client_uuid` bilan yopish allaqachon bo'lgan bo'lsa —
    # qayta qo'llamaymiz (tarmoq uzilishida takror so'rov qarzni IKKI marta
    # yopib, partiyani ortiqcha kamaytirardi).
    if data.client_uuid:
        from app.models.sync import AuditLog as _AL
        dup = (db.query(_AL)
               .filter(_AL.entity == "lot_shortfall_resolve",
                       _AL.entity_id == shortfall_id).all())
        for a in dup:
            if (a.after or {}).get("client_uuid") == str(data.client_uuid):
                return {"ok": True, "duplicate": True, "shortfall_id": str(sf.id),
                        "open_qty": float(sf.qty) - float(sf.resolved_qty)}

    open_qty = Decimal(str(sf.qty)) - Decimal(str(sf.resolved_qty))
    want = Decimal(str(data.qty))
    if want > open_qty:
        raise HTTPException(400, f"Yopilmagan qarz {open_qty}, so'ralgan {want} — "
                                 f"ortiqcha yopib bo'lmaydi")

    b = (db.query(StockBatch).filter(StockBatch.id == data.stock_batch_id)
         .with_for_update().first())
    if b is None or b.company_id != emp.company_id:
        raise HTTPException(404, "Partiya topilmadi")
    if b.product_id != sf.product_id or b.branch_id != sf.branch_id:
        raise HTTPException(400, "Partiya boshqa mahsulot yoki filialga tegishli")
    if Decimal(str(b.remaining_qty)) < want:
        raise HTTPException(400, f"Partiyada yetarli qoldiq yo'q "
                                 f"({b.remaining_qty} < {want}) — jismoniy partiya "
                                 f"MANFIYGA tushmaydi")

    now = datetime.now(timezone.utc)
    b.remaining_qty = Decimal(str(b.remaining_qty)) - want
    b.updated_at = now
    if Decimal(str(b.remaining_qty)) == 0:
        b.status = SI.DEPLETED
    sf.resolved_qty = Decimal(str(sf.resolved_qty)) + want
    if Decimal(str(sf.resolved_qty)) >= Decimal(str(sf.qty)):
        sf.resolved_at = now
    db.flush()

    # ── YAKUNIY DARVOZA: qoldiq O'ZGARMAGANINI isbotlaymiz ──────────────────
    try:
        SI.assert_ok(db, emp.company_id, [sf.product_id])
    except Exception as e:      # noqa: BLE001
        db.rollback()
        raise HTTPException(409, f"Qarzni yopib bo'lmadi — invariant buzilardi: {e}") from e

    audit_log(db, emp.id, "update", "lot_shortfall_resolve", sf.id,
              after={"stock_batch_id": str(b.id), "qty": float(want),
                     "reason": data.reason,
                     "client_uuid": str(data.client_uuid) if data.client_uuid else None,
                     "batch_unit_cost": float(b.unit_cost or 0),
                     "provisional_unit_cost": float(sf.unit_cost or 0)})
    db.commit()
    return {"ok": True, "shortfall_id": str(sf.id),
            "resolved_qty": float(sf.resolved_qty),
            "open_qty": float(sf.qty) - float(sf.resolved_qty),
            "closed": sf.resolved_at is not None}


@router.get("/shortfalls")
def list_shortfalls(branch_id: uuid.UUID | None = None, include_resolved: bool = False,
                    emp: Employee = Depends(require("ombor.view")),
                    db: Session = Depends(get_db)):
    """TAQSIMLANMAGAN QARZLAR — «tovar ketdi, qaysi partiyadan ekani noma'lum».

    ⚠️  HALOL OGOHLANTIRISH: bu FAQAT API. Na POS'da, na Manager'da partiya
        ekrani YO'Q, ya'ni qarzni operator O'ZI ko'ra olmaydi. Yopish oqimi ham
        hali yo'q. Shu bois qarz AUDIT jurnaliga ham yoziladi (sotuv paytida) —
        hech bo'lmaganda iz qoladi. Ekran kelgunicha bu qarz «ko'rinadigan»
        emas, «izlanadigan» holatda.
    """
    from app.models.inventory import LotShortfall as _LS
    q = db.query(_LS).filter(_LS.company_id == emp.company_id)
    if branch_id:
        q = q.filter(_LS.branch_id == branch_id)
    if not include_resolved:
        q = q.filter(_LS.qty > _LS.resolved_qty)
    rows = q.order_by(_LS.created_at.desc()).limit(500).all()
    out = []
    for r in rows:
        prod = db.get(Product, r.product_id)
        out.append({
            "id": str(r.id), "product_id": str(r.product_id),
            "product": prod.name if prod else None,
            "branch_id": str(r.branch_id),
            "sale_item_id": str(r.sale_item_id) if r.sale_item_id else None,
            "qty": float(r.qty), "resolved_qty": float(r.resolved_qty),
            "open_qty": float(r.qty) - float(r.resolved_qty),
            "unit_cost": float(r.unit_cost or 0), "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"count": len(out), "shortfalls": out}
