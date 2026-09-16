# -*- coding: utf-8 -*-
"""PARTIYA API (Phase 1) — kuzatuvni yoqish, partiyalarni ko'rish.

⚠️  SOTUV (FEFO) BU YERDA YO'Q. Phase 1 faqat kirimni biladi. Kuzatuvli mahsulot
    Phase 2/3 gacha SOTILMAYDI — eski sotuv yo'li uni `stock_gate` orqali rad
    etadi. Staging'da bu maqbul va ATAYLAB shunday.
"""
from __future__ import annotations

import logging
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

log = logging.getLogger(__name__)

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
    # ── SXEMA YAXLITLIGI DARVOZASI (Phase 4A) ───────────────────────────────
    #  Majburiy FK yoki CHECK joyida bo'lmasa (yetim qatorlar, tasdiqlanmagan
    #  cheklov) boot YIQILMAYDI — lekin YANGI partiya tarixi ham tug'ilmasin:
    #  kuzatuv yoqilgach yoziladigan har qator o'sha kafolatga tayanadi.
    #  ⚠️  `missing` (soft EMAS): halokatli sinfdagi CHECK — `ck_track_expiry_implies_lots`,
    #      track_expiry => track_lots ning YAGONA bazaviy himoyasi — YO'Q bo'lsa ham kuzatuv
    #      yoqilmasin. U faqat `_fatal` da ko'rinadi (Phase 4A.1 review).
    from app.core import required_schema as _rs
    _soft = _rs.missing(db.get_bind())
    if _soft:
        raise HTTPException(
            409, f"Partiya kuzatuvini yoqib bo'lmaydi — sxema yaxlitligi to'liq emas "
                 f"({len(_soft)} ta FK/cheklov tayyor emas). Avval /health/ready yashil "
                 f"bo'lsin.")
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
        # ⚠️  Istisno matni operatorga berilmaydi (xom UUID va ichki nomlar) — jurnalga.
        log.exception("lot enable invariant buzildi: product=%s", p.id)
        raise HTTPException(409, "Kuzatuvni yoqib bo'lmadi — qoldiq va partiyalar mos "
                                 "kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga "
                                 "murojaat qiling.") from e

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
    # Filial izolyatsiyasi — boshqa filial partiyalari ko'rinmasin (IDOR).
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)
    if _vb is not None and br.id not in _vb:
        raise HTTPException(404, "Filial topilmadi")
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
    # YAGONA TA'RIF: qarzni FAQAT `resolved_qty` kamaytiradi
    # (`lot_return.open_debt` bilan bir xil).
    _open_expr = (_LS.qty - _LS.resolved_qty)
    _debt = (db.query(func.coalesce(func.sum(_open_expr), 0))
             .filter(_LS.company_id == emp.company_id, _LS.branch_id == br.id,
                     _LS.product_id == p.id, _open_expr > 0).scalar())
    return {"product_id": str(p.id), "track_lots": bool(p.track_lots),
            "track_expiry": bool(p.track_expiry), "business_date": biz.isoformat(),
            "inventory_qty": float(inv.qty) if inv else 0.0,
            "unresolved_shortfall_qty": float(_debt or 0),
            "lots": out}


class ResolveLineIn(BaseModel):
    stock_batch_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)


class ResolveShortfallIn(BaseModel):
    """Qarzni partiyaga bog'lash — bitta qator YOKI `allocations` (1..50).

    ⚠️  `client_uuid` MAJBURIY (Phase 4A). Yopish pulga ta'sir qiladi (og'ish
        P&L'ga tushadi): tarmoq uzilishida takror so'rov uni IKKI marta tan
        olmasligi kerak, va buning yagona tranzaksion kafolati — `(company_id,
        client_uuid)` noyob indeksi.
    """
    stock_batch_id: uuid.UUID | None = None
    qty: float | None = Field(default=None, gt=0, le=1e9, allow_inf_nan=False)
    allocations: list[ResolveLineIn] | None = Field(default=None, min_length=1,
                                                    max_length=50)
    reason: str = Field(min_length=3, max_length=300)     # AUDIT uchun MAJBURIY
    client_uuid: uuid.UUID


@router.post("/shortfalls/{shortfall_id}/resolve")
def resolve_shortfall(shortfall_id: uuid.UUID, data: ResolveShortfallIn,
                      emp: Employee = Depends(require("ombor.edit")),
                      db: Session = Depends(get_db)):
    """QARZNI partiyaga yopadi — O'ZGARMAS HODISA yozadi. `Inventory.qty` O'ZGARMAYDI.

    ⚠️  NEGA QOLDIQ O'ZGARMASLIGI SHART. Qoldiq sotuv paytida ALLAQACHON
        kamaytirilgan — tovar jismonan ketgan. Qarz miqdor emas, ATRIBUTSIYA
        qarzi. Yopish ikki tomonni BARAVAR siljitadi:

            partiya.remaining_qty -= k        (SUM(partiya) -= k)
            qarz.resolved_qty     += k        (SUM(qarz)    -= k)

        ya'ni `Inventory.qty == SUM(partiya) - SUM(qarz)` ning AYIRMASI o'zgarmaydi.

    ⚠️  TARIXIY SOTUV QAYTA YOZILMAYDI — na `SaleItem`, na `sale_item_lot_
        allocations`. Og'ish `lot_shortfall_resolutions` da o'z SANASI bilan
        yashaydi va P&L uni o'sha davrda ALOHIDA ko'rsatadi
        (`services/lot_resolution.py` izohi).
    """
    from app.services import lot_resolution as LRes
    single = data.stock_batch_id is not None or data.qty is not None
    if single and data.allocations is not None:
        raise HTTPException(400, "Yo `stock_batch_id`+`qty`, yo `allocations` bering — "
                                 "ikkalasini birga emas")
    if data.allocations is not None:
        lines = [(a.stock_batch_id, a.qty) for a in data.allocations]
    elif data.stock_batch_id is not None and data.qty is not None:
        lines = [(data.stock_batch_id, data.qty)]
    else:
        raise HTTPException(400, "Yopish uchun partiya va miqdor ko'rsatilmagan")
    try:
        return LRes.resolve(db, emp, shortfall_id, lines, reason=data.reason,
                            client_uuid=data.client_uuid)
    except LRes.ResolutionError as e:
        db.rollback()
        raise HTTPException(e.status, e.detail) from e


@router.get("/shortfalls")
def list_shortfalls(branch_id: uuid.UUID | None = None, include_resolved: bool = False,
                    emp: Employee = Depends(require("ombor.view")),
                    db: Session = Depends(get_db)):
    """TAQSIMLANMAGAN QARZLAR — «tovar ketdi, qaysi partiyadan ekani noma'lum».

    ⚠️  HALOL OGOHLANTIRISH: bu FAQAT API. Na POS'da, na Manager'da partiya
        ekrani YO'Q, ya'ni qarzni operator O'ZI ko'ra olmaydi.

    ⚠️  OG'ISH HODISALARDAN (Phase 4A). `cogs_variance_recognised` — `real`
        yopishlarda tan olingan, `cogs_variance_reversed` — o'sha tovar
        qaytganda teskari qilingan, `cogs_variance_legacy` — Phase 4A dan
        oldin hodisasiz yopilgan qism (hisoblagichlardan). `cogs_variance` —
        uchalasining sof yig'indisi.

    ⚠️  FILIAL IZOLYATSIYASI — boshqa filial qarzlari ko'rinmaydi (IDOR).
    """
    from app.core.deps import visible_branches
    from app.models.inventory import LotShortfall as _LS
    from app.services import lot_resolution as LRes
    _vb = visible_branches(emp, db)
    q = db.query(_LS).filter(_LS.company_id == emp.company_id)
    if _vb is not None:
        q = q.filter(_LS.branch_id.in_(_vb))
    if branch_id:
        q = q.filter(_LS.branch_id == branch_id)
    if not include_resolved:
        q = q.filter(_LS.qty > _LS.resolved_qty)
    rows = q.order_by(_LS.created_at.desc(), _LS.id).limit(500).all()
    ids = [r.id for r in rows]
    names = dict(db.query(Product.id, Product.name)
                 .filter(Product.id.in_({r.product_id for r in rows})).all()) if rows else {}
    var = LRes.variance_totals(db, ids)
    out = []
    _var = Decimal("0")
    _exp = Decimal("0")
    for r in rows:
        bk = LRes.book(db, r)
        rec, rev = var.get(r.id, (Decimal("0"), Decimal("0")))
        legacy = Decimal("0")
        if bk.events_qty == 0 and LRes.q3(r.resolved_qty) > 0:
            legacy = (LRes.c2(r.resolved_cost)
                      - LRes.c2(LRes.q3(r.resolved_qty) * LRes.c2(r.unit_cost)))
        open_q = LRes.q3(r.qty) - LRes.q3(r.resolved_qty)
        # Hali TAXMINIY qolgan COGS: ochiq qarzdan javonda (o'z U partiyasida)
        # turgan tovar AYIRILADI — uning taxmini inventarda, COGS'da emas.
        exposure = LRes.c2(max(open_q - bk.own_u_remaining, Decimal("0"))
                           * LRes.c2(r.unit_cost))
        net = rec - rev + legacy
        _var += net
        _exp += exposure
        out.append({
            "id": str(r.id), "product_id": str(r.product_id),
            "product": names.get(r.product_id),
            "branch_id": str(r.branch_id),
            "sale_item_id": str(r.sale_item_id) if r.sale_item_id else None,
            "qty": float(r.qty), "resolved_qty": float(r.resolved_qty),
            "resolved_real_qty": float(bk.resolved_real),
            "netted_qty": float(bk.resolved_net),
            "returned_qty": float(r.returned_qty or 0),   # tovar QAYTIB keldi
            "returned_unattributed_on_hand": float(bk.own_u_remaining),
            "open_qty": float(open_q),
            "unit_cost": float(r.unit_cost or 0),        # TAXMINIY
            "resolved_cost": float(r.resolved_cost or 0),
            "cogs_variance_recognised": float(rec),
            "cogs_variance_reversed": float(rev),
            "cogs_variance_legacy": float(legacy),
            "cogs_variance": float(net),
            "provisional_exposure": float(exposure),
            "legacy_shape": bool(bk.legacy),
            "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"count": len(out), "shortfalls": out,
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
