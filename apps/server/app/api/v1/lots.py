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
    # YAGONA TA'RIF: qarz `resolved_qty` (atributsiya topildi) VA
    # `returned_qty` (tovar qaytib keldi) ga ko'ra kamayadi.
    _open_expr = (_LS.qty - _LS.resolved_qty - func.coalesce(_LS.returned_qty, 0))
    _debt = (db.query(func.coalesce(func.sum(_open_expr), 0))
             .filter(_LS.company_id == emp.company_id, _LS.branch_id == br.id,
                     _LS.product_id == p.id, _open_expr > 0).scalar())
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
    # ⚠️  QULF TARTIBI: Inventory -> qarz -> partiya. HAR uch yozuvchi (sotuv,
    #     qaytarish, yopish) AYNAN shu tartibda oladi — teskarisi AB/BA deadlock.
    #
    # ⚠️  QARZ QATORI QULFLANADI. Ilgari bu `db.get(...)` edi — qulfsiz. Yopish
    #     `resolved_qty` ga MUTLAQ qiymat yozadi, ya'ni ikki yozuvchi (yopish va
    #     partiya-darajasidagi qaytarish) bir vaqtда `qty - resolved_qty` ni
    #     o'qib, ikkinchisi birinchisining natijasini BOSIB ketardi (lost
    #     update). Ikkalasi ham endi shu qatorni FOR UPDATE oladi.
    _sf0 = db.get(LotShortfall, shortfall_id)
    if _sf0 is None or _sf0.company_id != emp.company_id:
        raise HTTPException(404, "Qarz topilmadi")
    (db.query(Inventory)
     .filter(Inventory.product_id == _sf0.product_id,
             Inventory.branch_id == _sf0.branch_id).with_for_update().first())
    sf = (db.query(LotShortfall).filter(LotShortfall.id == shortfall_id)
          .with_for_update().first())
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
                from app.services.lot_return import open_debt as _od
                return {"ok": True, "duplicate": True, "shortfall_id": str(sf.id),
                        "open_qty": float(_od(sf))}

    # ⚠️  YAGONA TA'RIF — `returned_qty` ham qarzni kamaytiradi (tovar qaytib
    #     kelgan). Uni unutish allaqachon qaytgan tovarni IKKINCHI marta
    #     yopishga ruxsat berardi.
    from app.services.lot_return import open_debt as _open_debt
    open_qty = _open_debt(sf)
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
    # ⚠️  HAQIQIY TANNARX YOZIB QO'YILADI. Sotuv paytida bu miqdorning tannarxi
    #     TAXMIN qilingan edi (`sf.unit_cost`); endi haqiqiy partiya narxi
    #     ma'lum. Tarixiy `SaleItem.cost_total` QAYTA YOZILMAYDI, lekin farq ham
    #     YO'QOLMAYDI: `resolved_cost − resolved_qty × unit_cost` — COGS og'ishi,
    #     va u SQL bilan yig'iladi. Ilgari bu faqat `AuditLog` JSON'ida edi,
    #     ya'ni hech bir hisobot uni yig'a olmasdi.
    sf.resolved_cost = (Decimal(str(sf.resolved_cost or 0))
                        + (want * Decimal(str(b.unit_cost or 0)))
                        ).quantize(Decimal("0.01"))
    if _open_debt(sf) <= 0:
        sf.resolved_at = now

    # ⚠️  TOPILGAN ATRIBUTSIYA YOZIB QO'YILADI. Yopish «bu miqdor AYNAN shu
    #     partiyadan ketgan» degan faktni ANIQLAYDI. Ilgari bu fakt hech qayerda
    #     saqlanmasdi va natijada sotuv qatorining taqsimoti CHALA qolardi:
    #
    #         Σ(taqsimot) + ochiq_qarz == sale_item.qty
    #
    #     Yopishdan keyin qarz nolga tushardi-yu, taqsimot o'sмasdi — ya'ni
    #     tenglik BUZILARDI. Keyinchalik o'sha chek qaytarilса, qaytarish
    #     miqdorning bir qismiga partiya TOPA OLMASDI. Endi topilgan
    #     atributsiya asl taqsimotga QO'SHILADI.
    #
    #     Bu TARIXNI QAYTA YOZISH EMAS: `SaleItem.cost_total` tegilmaydi, faqat
    #     «qaysi partiyadan» degan, sotuv paytida NOMA'LUM bo'lgan javob
    #     to'ldiriladi. Shu bois taqsimot qatoridagi `unit_cost` (haqiqiy) chek
    #     tannarxidan (taxminiy) FARQ qilishi mumkin — bu og'ishning o'zi.
    if sf.sale_item_id is not None:
        from app.models.inventory import SaleItemLotAllocation as _SIA
        _ex = (db.query(_SIA)
               .filter(_SIA.sale_item_id == sf.sale_item_id,
                       _SIA.stock_batch_id == b.id)
               .with_for_update().first())
        if _ex is not None:
            _ex.qty = Decimal(str(_ex.qty)) + want
        else:
            db.add(_SIA(id=uuid.uuid4(), company_id=emp.company_id,
                        sale_item_id=sf.sale_item_id, stock_batch_id=b.id,
                        product_id=sf.product_id, qty=want,
                        unit_cost=Decimal(str(b.unit_cost or 0)),
                        expiry_date=b.expiry_date, created_at=now))
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
                     # OG'ISH — shu yopish hodisasining O'ZI uchun (sanasi bilan).
                     "variance": float((want * Decimal(str(b.unit_cost or 0)))
                                       - (want * Decimal(str(sf.unit_cost or 0)))),
                     "client_uuid": str(data.client_uuid) if data.client_uuid else None,
                     "batch_unit_cost": float(b.unit_cost or 0),
                     "provisional_unit_cost": float(sf.unit_cost or 0)})
    db.commit()
    return {"ok": True, "shortfall_id": str(sf.id),
            "resolved_qty": float(sf.resolved_qty),
            "open_qty": float(_open_debt(sf)),
            "resolved_cost": float(sf.resolved_cost or 0),
            # OG'ISH = haqiqiy − taxminiy (yopilgan miqdor uchun).
            "cogs_variance": float(Decimal(str(sf.resolved_cost or 0))
                                   - (Decimal(str(sf.resolved_qty))
                                      * Decimal(str(sf.unit_cost or 0)))),
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
    from app.services import lot_return as _LRo
    q = db.query(_LS).filter(_LS.company_id == emp.company_id)
    if branch_id:
        q = q.filter(_LS.branch_id == branch_id)
    if not include_resolved:
        q = q.filter(_LS.qty > (_LS.resolved_qty
                                + func.coalesce(_LS.returned_qty, 0)))
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
            "returned_qty": float(r.returned_qty or 0),   # tovar QAYTIB keldi
            "open_qty": float(_LRo.open_debt(r)),
            "unit_cost": float(r.unit_cost or 0),        # TAXMINIY
            "resolved_cost": float(r.resolved_cost or 0),  # HAQIQIY (yig'indi)
            "cogs_variance": float(Decimal(str(r.resolved_cost or 0))
                                   - (Decimal(str(r.resolved_qty))
                                      * Decimal(str(r.unit_cost or 0)))),
            # Hali TAXMINIY qolgan ulush — yopilmagan qarzning pul o'lchovi.
            "provisional_exposure": float(_LRo.open_debt(r)
                                          * Decimal(str(r.unit_cost or 0))),
            "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    _var = sum(Decimal(str(x["cogs_variance"])) for x in out) if out else Decimal("0")
    _exp = sum(Decimal(str(x["provisional_exposure"])) for x in out) if out else Decimal("0")
    return {"count": len(out), "shortfalls": out,
            # ⚠️  Og'ish YO'QOLMAYDI. Tarixiy chek qayta yozilmaydi, lekin
            #     «taxmin qancha noto'g'ri chiqdi» degan savol SQL bilan
            #     yig'iladi — ilgari javob faqat AuditLog JSON'ida edi.
            "total_cogs_variance": float(_var),
            "total_provisional_exposure": float(_exp)}


# ══ MUDDAT HISOBOTI (Phase 3) ═══════════════════════════════════════════════
#
# ⚠️  INDEKS AVVAL, SO'ROV KEYIN. So'rov ATAYLAB `ix_lot_expiry` ning qisman
#     shartiga (`initdb.py`) AYNAN mos yozilgan:
#
#         ON stock_batches (company_id, expiry_date)
#         WHERE remaining_qty > 0 AND status = 'open' AND expiry_date IS NOT NULL
#
#     Shu bois `WHERE` da uchala shart ham SAQLANADI — bittasi tushib qolsa
#     Postgres qisman indeksdan FOYDALANA OLMAY to'liq jadval skanerlardi.
#     `branch_id` ATAYLAB indeksda YO'Q: uni old tomonga qo'yish kompaniya
#     bo'yicha so'rovni indeksdan mahrum qilardi (Postgres'da skip-scan yo'q),
#     filialni keyin filtrlash esa arzon — diapazon allaqachon 30 kun bilan
#     chegaralangan.
#
# ⚠️  MUDDAT SAQLANMAYDI, HISOBLANADI (`lot_policy`). Shu bois chegara sanalar
#     filialning BIZNES sanasidan olinadi, UTC'dan emas.

BUCKET_EXPIRED = "expired"
BUCKET_TODAY = "expires_today"
BUCKET_7 = "within_7_days"
BUCKET_30 = "within_30_days"
BUCKETS = (BUCKET_EXPIRED, BUCKET_TODAY, BUCKET_7, BUCKET_30)

# Eng uzoq gorizont — so'rov diapazonini cheklaydi (to'liq skanerlamasin).
HORIZON_DAYS = 30


def _bucket_of(expiry, biz):
    """Partiya qaysi guruhga tushadi. Chegaralar KESISHMAYDI."""
    from datetime import timedelta as _td
    if expiry < biz:
        return BUCKET_EXPIRED
    if expiry == biz:
        return BUCKET_TODAY
    if expiry <= biz + _td(days=7):
        return BUCKET_7
    if expiry <= biz + _td(days=HORIZON_DAYS):
        return BUCKET_30
    return None


@router.get("/expiring")
def expiring_lots(branch_id: uuid.UUID | None = None, bucket: str | None = None,
                  product_id: uuid.UUID | None = None,
                  limit: int = 200, offset: int = 0,
                  emp: Employee = Depends(require("ombor.view")),
                  db: Session = Depends(get_db)):
    """Muddati o'tgan va o'tayotgan partiyalar + XAVF OSTIDAGI SUMMA.

    ⚠️  HALOL OGOHLANTIRISH: bu FAQAT API. Na POS'da, na Manager'da partiya
        ekrani YO'Q (`packages/shared` da bitta ham `track_lots` ishlatuvchi
        ekran topilmadi). Hisobot mavjud, lekin uni ko'radigan ekran yo'q —
        buni «tayyor» deb ko'rsatish yolg'on bo'lardi.

    ⚠️  «Muddati o'tgan» — HOLAT EMAS. Partiya `status` i `open` bo'lib qoladi
        va u qoldiqda hisobga olinaveradi (invariant buzilmaydi). Uni javondan
        olib tashlash — ALOHIDA, ONGLI amal (hisobdan chiqarish).
    """
    from datetime import timedelta as _td

    if bucket is not None and bucket not in BUCKETS:
        raise HTTPException(400, f"Noma'lum guruh: {bucket}")
    limit = max(1, min(int(limit or 200), 1000))
    offset = max(0, int(offset or 0))

    br = _branch(db, emp, branch_id)
    # Filial izolyatsiyasi — boshqa filial partiyalari ko'rinmasin (IDOR).
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)
    if _vb is not None and br.id not in _vb:
        raise HTTPException(404, "Filial topilmadi")

    biz = LP.business_date(db, br.id)
    horizon = biz + _td(days=HORIZON_DAYS)

    q = (db.query(StockBatch)
         .filter(StockBatch.company_id == emp.company_id,
                 # ── ix_lot_expiry qisman shartining AYNAN o'zi ──
                 StockBatch.remaining_qty > 0,
                 StockBatch.status == SI.OPEN,
                 StockBatch.expiry_date.isnot(None),
                 # ── diapazon: indeks bo'yicha oraliq skanerlash ──
                 StockBatch.expiry_date <= horizon,
                 # ── filial: indeksdan KEYIN, arzon filtr ──
                 StockBatch.branch_id == br.id))
    if product_id is not None:
        q = q.filter(StockBatch.product_id == product_id)

    rows = q.order_by(StockBatch.expiry_date.asc(),
                      StockBatch.received_at.asc(),
                      StockBatch.id.asc()).all()

    summary = {b: {"lots": 0, "qty": 0.0, "value_at_risk": 0.0} for b in BUCKETS}
    out = []
    for b in rows:
        g = _bucket_of(b.expiry_date, biz)
        if g is None:               # gorizontdan tashqarida (himoya)
            continue
        qty = Decimal(str(b.remaining_qty or 0))
        value = (qty * Decimal(str(b.unit_cost or 0))).quantize(Decimal("0.01"))
        s = summary[g]
        s["lots"] += 1
        s["qty"] += float(qty)
        s["value_at_risk"] = float(Decimal(str(s["value_at_risk"])) + value)
        if bucket is not None and g != bucket:
            continue
        out.append({
            "id": str(b.id), "bucket": g,
            "product_id": str(b.product_id),
            "batch_number": b.batch_no,
            "expiry_date": b.expiry_date.isoformat(),
            "days_left": (b.expiry_date - biz).days,
            "remaining_qty": float(qty),
            "unit_cost": float(b.unit_cost or 0),
            "value_at_risk": float(value),
            "source_type": b.source_type,
        })

    page = out[offset:offset + limit]
    # Mahsulot nomlari — FAQAT ko'rsatiladigan sahifa uchun (N+1 ni cheklaymiz).
    if page:
        _pids = {uuid.UUID(r["product_id"]) for r in page}
        _names = dict(db.query(Product.id, Product.name)
                      .filter(Product.id.in_(_pids)).all())
        for r in page:
            r["product"] = _names.get(uuid.UUID(r["product_id"]))
    return {"branch_id": str(br.id), "business_date": biz.isoformat(),
            "horizon_days": HORIZON_DAYS, "summary": summary,
            "total": len(out), "offset": offset, "limit": limit,
            "lots": page}
