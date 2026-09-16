# -*- coding: utf-8 -*-
"""PHASE 4B — PARTIYA / MUDDAT O'QISH API (Manager ekranlari uchun).

⚠️  FAQAT O'QISH. Bu modul BIRORTA qator yozmaydi. Hisob semantikasi Phase 4A da
    qotirilgan va o'z joyida qoladi; bu yerda faqat operator ekranlari uchun
    kerak bo'lgan ro'yxat, tafsilot, sanoq va «funksiya ochiqmi» ma'lumoti
    yig'iladi.

⚠️  NEGA SERVERDA. «Muddati o'tganmi» — BIZNES sanasi bo'yicha qaror, brauzer
    soati bo'yicha emas: bir kunlik xato muddati o'tgan sutni «yaroqli» qilib
    ko'rsatardi. Shu bois guruh, qolgan kun va xavf ostidagi summa SERVERDA
    hisoblanadi, UI ularni faqat CHIZADI.

⚠️  YO'L NOMLARI ATAYLAB `/lots/batches...`. Bo'sh `/lots/{id}` yo'li mavjud
    `/lots/expiring`, `/lots/shortfalls`, `/lots/products/{id}` bilan
    to'qnashardi — FastAPI birinchi mos yo'lni oladi va `expiring` so'zini UUID
    deb o'qishga urinardi.

⚠️  FILIAL IZOLYATSIYASI. Har so'rov `visible_branches` bilan cheklanadi va
    ANIQ so'ralgan begona filial 404 beradi (`/lots/expiring` bilan bir xil).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.v1.lots import BUCKET_7, BUCKET_30, BUCKET_EXPIRED, BUCKET_TODAY, HORIZON_DAYS
from app.core.deps import require, visible_branches
from app.core.validate import like_escape
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product, ProductBarcode
from app.models.inventory import (LotShortfallResolution, ReturnItemLotAllocation,
                                  SaleItemLotAllocation, StockBatch, StockMovement,
                                  StockMovementLotAllocation)
from app.models.org import Branch
from app.models.purchasing import Purchase, PurchaseItem, Supplier
from app.models.receiving import Receiving
from app.models.sales import Return, ReturnItem, Sale, SaleItem
from app.services import lot_policy as LP
from app.services import stock_invariant as SI

router = APIRouter(prefix="/lots", tags=["lots"])


# ⚠️  KECHIKTIRILGAN IMPORT. `lot_fefo` -> `lot_policy` -> `reports` -> `api/v1/__init__`
#     zanjiri shu modulga qaytadi: modul darajasidagi import AYLANMA bo'lardi
#     (`partially initialized module`). Qiymatlar o'zgarmas, chaqiruv arzon.
def _provisional() -> frozenset:
    from app.services.lot_fefo import PROVISIONAL_SOURCES
    return PROVISIONAL_SOURCES


def _tz_names():
    from app.api.v1.reports import _TZ_OFFSETS
    return sorted(_TZ_OFFSETS)

# Muddat guruhlari — `/lots/expiring` bilan AYNI ta'rif (o'sha yerdan import),
# ustiga UI uchun ikkita qo'shimcha: gorizontdan narigi va muddatsiz.
BUCKET_LATER = "later"
BUCKET_NONE = "no_expiry"
EXPIRY_FILTERS = ("any", BUCKET_EXPIRED, BUCKET_TODAY, BUCKET_7, BUCKET_30, BUCKET_LATER,
                  BUCKET_NONE, "valid")
SORTS = ("expiry", "received", "remaining", "value", "product")
STATUSES = ("any", SI.OPEN, "depleted", "void")

# Tannarx SIFATI — UI dagi ANIQ / TAXMINIY / NOMA'LUM nishonining YAGONA manbai.
#
# ⚠️  «TAXMINIY» — P&L dagi bilan AYNI ma'no: `return_unattributed` partiyasi
#     mijoz qaytargan, lekin qaysi kirimdan ekani noma'lum tovar (narxi
#     muzlatilgan taxmin). Frontend buni O'ZI hisoblab chiqarmasin — aks holda
#     hisobot bilan ekran bir kun ajralib ketardi.
COST_KNOWN, COST_ESTIMATED, COST_UNKNOWN = "known", "estimated", "unknown"


def _cost_basis(b: StockBatch) -> str:
    if (b.source_type or "") in _provisional():
        return COST_ESTIMATED
    if not b.unit_cost or float(b.unit_cost) <= 0:
        return COST_UNKNOWN
    return COST_KNOWN


def _scope_branches(db: Session, emp: Employee, branch_id: uuid.UUID | None) -> list[Branch]:
    """Ko'rinadigan filiallar. ANIQ so'ralgani doirada bo'lmasa — 404."""
    vb = visible_branches(emp, db)
    rows = (db.query(Branch)
            .filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None))
            .order_by(Branch.created_at).all())
    if vb is not None:
        rows = [b for b in rows if b.id in vb]
    if branch_id is not None:
        rows = [b for b in rows if b.id == branch_id]
        if not rows:
            raise HTTPException(404, "Filial topilmadi")
    return rows


def _biz_map(db: Session, branches: list[Branch]) -> dict:
    """Har filialning BIZNES sanasi (o'z vaqt zonasida)."""
    return {b.id: LP.business_date(db, b.id) for b in branches}


def _bucket(expiry: date | None, biz: date) -> str:
    if expiry is None:
        return BUCKET_NONE
    if expiry < biz:
        return BUCKET_EXPIRED
    if expiry == biz:
        return BUCKET_TODAY
    if expiry <= biz + timedelta(days=7):
        return BUCKET_7
    if expiry <= biz + timedelta(days=HORIZON_DAYS):
        return BUCKET_30
    return BUCKET_LATER


def _expiry_condition(kind, biz: dict):
    """Muddat filtri — HAR FILIAL o'z biznes sanasi bilan (OR bo'lib birlashadi)."""
    if not kind or kind == "any":
        return None
    if kind == BUCKET_NONE:
        return StockBatch.expiry_date.is_(None)
    parts = []
    for bid, d in biz.items():
        same = StockBatch.branch_id == bid
        e = StockBatch.expiry_date
        if kind == BUCKET_EXPIRED:
            parts.append(and_(same, e.isnot(None), e < d))
        elif kind == BUCKET_TODAY:
            parts.append(and_(same, e == d))
        elif kind == BUCKET_7:
            parts.append(and_(same, e > d, e <= d + timedelta(days=7)))
        elif kind == BUCKET_30:
            parts.append(and_(same, e > d + timedelta(days=7),
                              e <= d + timedelta(days=HORIZON_DAYS)))
        elif kind == BUCKET_LATER:
            parts.append(and_(same, e > d + timedelta(days=HORIZON_DAYS)))
        elif kind == "valid":
            parts.append(and_(same, or_(e.is_(None), e >= d)))
    return or_(*parts) if parts else None


def _names(db: Session, model, ids) -> dict:
    """id -> ko'rinadigan nom. Xodimda ustun `full_name` deb ataladi."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    col = getattr(model, "name", None) or model.full_name
    return dict(db.query(model.id, col).filter(model.id.in_(ids)).all())


def _units(db: Session, pids) -> dict:
    """product_id -> birlik kodi.

    ⚠️  `Product` da `unit_code` USTUNI YO'Q — kod `units` jadvalida turadi
        (`products.unit_id`). UI «6 dona» va «6 kg» ni farqlashi uchun bu
        JOIN shart: birliksiz miqdor operator uchun ma'nosiz.
    """
    from app.models.catalog import Unit
    pids = {i for i in pids if i}
    if not pids:
        return {}
    return dict(db.query(Product.id, Unit.code)
                .join(Unit, Unit.id == Product.unit_id)
                .filter(Product.id.in_(pids)).all())


def _f(v) -> float:
    return float(v or 0)


def _value(b: StockBatch) -> float:
    return float((Decimal(str(b.remaining_qty or 0)) * Decimal(str(b.unit_cost or 0)))
                 .quantize(Decimal("0.01")))


# ══════════════════════════════════════════════════════════════════════════════
#  PARTIYALAR RO'YXATI
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/batches")
def list_batches(branch_id: uuid.UUID | None = None,
                 product_id: uuid.UUID | None = None,
                 supplier_id: uuid.UUID | None = None,
                 source_type: str | None = None,
                 status: str | None = None,
                 expiry: str | None = None,
                 q: str | None = None,
                 sort: str = "expiry", order: str = "asc",
                 include_depleted: bool = False,
                 limit: int = 50, offset: int = 0,
                 emp: Employee = Depends(require("ombor.view")),
                 db: Session = Depends(get_db)):
    """Kompaniya bo'yicha PARTIYALAR — filtr, qidiruv, tartib va SAHIFALASH bilan.

    ⚠️  SAHIFALASH SERVERDA. Fayzan katalogi 7137 mahsulot — «hammasini yuklab
        brauzerda filtrlash» ekranni ham, bazani ham cho'ktirardi.

    ⚠️  Standart holat (`include_depleted=false`) FAQAT javondagi tovarni
        ko'rsatadi: miqdor tashuvchi holat VA `remaining_qty > 0`.
    """
    if sort not in SORTS:
        raise HTTPException(400, f"Noma'lum tartib: {sort}")
    if expiry is not None and expiry not in EXPIRY_FILTERS:
        raise HTTPException(400, f"Noma'lum guruh: {expiry}")
    if status is not None and status not in STATUSES:
        raise HTTPException(400, f"Noma'lum holat: {status}")
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))

    branches = _scope_branches(db, emp, branch_id)
    if not branches:
        return {"total": 0, "limit": limit, "offset": offset, "business_dates": {}, "lots": []}
    biz = _biz_map(db, branches)

    query = (db.query(StockBatch)
             .filter(StockBatch.company_id == emp.company_id,
                     StockBatch.branch_id.in_([b.id for b in branches])))
    if status and status != "any":
        query = query.filter(StockBatch.status == status)
    else:
        query = query.filter(StockBatch.status.in_(sorted(SI.QUANTITY_BEARING)))
    if not include_depleted:
        query = query.filter(StockBatch.remaining_qty > 0)
    if product_id is not None:
        query = query.filter(StockBatch.product_id == product_id)
    if supplier_id is not None:
        query = query.filter(StockBatch.supplier_id == supplier_id)
    if source_type:
        query = query.filter(StockBatch.source_type == source_type)
    cond = _expiry_condition(expiry, biz)
    if cond is not None:
        query = query.filter(cond)
    if q:
        like = f"%{like_escape(q)}%"
        pid_by_name = (db.query(Product.id)
                       .filter(Product.company_id == emp.company_id,
                               or_(Product.name.ilike(like, escape="\\"),
                                   Product.sku.ilike(like, escape="\\"),
                                   Product.article_code.ilike(like, escape="\\"))))
        pid_by_bc = (db.query(ProductBarcode.product_id)
                     .filter(ProductBarcode.barcode.ilike(like, escape="\\")))
        query = query.filter(or_(StockBatch.batch_no.ilike(like, escape="\\"),
                                 StockBatch.product_id.in_(pid_by_name),
                                 StockBatch.product_id.in_(pid_by_bc)))

    total = query.order_by(None).count()

    asc = (order or "asc").lower() != "desc"
    value_expr = StockBatch.remaining_qty * StockBatch.unit_cost
    col = {"expiry": StockBatch.expiry_date, "received": StockBatch.received_at,
           "remaining": StockBatch.remaining_qty, "value": value_expr,
           "product": StockBatch.product_id}[sort]
    # NULL muddat HAR DOIM oxirida: «muddatsiz» partiya muddat ro'yxatining
    # boshida turib, ro'yxatni ma'nosiz qilib qo'ymasin.
    primary = col.asc().nullslast() if asc else col.desc().nullslast()
    rows = (query.order_by(primary, StockBatch.received_at.asc(), StockBatch.id.asc())
            .limit(limit).offset(offset).all())

    pids = {r.product_id for r in rows}
    prods = _names(db, Product, pids)
    units = _units(db, pids)
    sups = _names(db, Supplier, {r.supplier_id for r in rows})
    bnames = {b.id: b.name for b in branches}
    out = []
    for b in rows:
        d = biz[b.branch_id]
        out.append({
            "id": str(b.id), "branch_id": str(b.branch_id), "branch": bnames.get(b.branch_id),
            "product_id": str(b.product_id), "product": prods.get(b.product_id),
            "unit_code": units.get(b.product_id),
            "batch_number": b.batch_no,
            "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
            "bucket": _bucket(b.expiry_date, d),
            "expired": bool(b.expiry_date and b.expiry_date < d),
            "days_left": (b.expiry_date - d).days if b.expiry_date else None,
            "received_qty": _f(b.received_qty), "remaining_qty": _f(b.remaining_qty),
            "unit_cost": _f(b.unit_cost), "value": _value(b),
            "cost_basis": _cost_basis(b),
            "status": b.status, "source_type": b.source_type,
            "supplier_id": str(b.supplier_id) if b.supplier_id else None,
            "supplier": sups.get(b.supplier_id),
            "received_at": b.received_at.isoformat() if b.received_at else None,
        })
    return {"total": total, "limit": limit, "offset": offset,
            "business_dates": {str(k): v.isoformat() for k, v in biz.items()},
            "lots": out}


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD SANOQLARI — ARZON AGREGAT
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/alerts")
def lot_alerts(branch_id: uuid.UUID | None = None,
               emp: Employee = Depends(require("ombor.view")),
               db: Session = Depends(get_db)):
    """Dashboard kartalari uchun SANOQLAR — qatorlar YUKLANMAYDI.

    ⚠️  ARZON BO'LISHI SHART. Dashboard har ochilganda chaqiriladi, shu bois
        so'rovlar `ix_lot_expiry` qisman indeksining shartiga AYNAN mos: ochiq
        holat, musbat qoldiq, muddati bor va gorizont ichida. Sanoq SQL da
        (`GROUP BY`) hisoblanadi — Python'ga qatorlar olib kelinmaydi.
    """
    from sqlalchemy import case, func

    from app.models.inventory import LotShortfall

    branches = _scope_branches(db, emp, branch_id)
    zero = {"lots": 0, "qty": 0.0, "value_at_risk": 0.0}
    buckets = {k: dict(zero) for k in (BUCKET_EXPIRED, BUCKET_TODAY, BUCKET_7, BUCKET_30)}
    if not branches:
        return {"expiry": buckets, "shortfalls": {"open_count": 0, "open_qty": 0.0,
                                                  "provisional_exposure_max": 0.0},
                "cost_quality": {"estimated_lots": 0, "unknown_cost_lots": 0,
                                 "tracked_products": 0},
                "business_dates": {}, "branches": 0}
    biz = _biz_map(db, branches)
    bids = [b.id for b in branches]

    for b in branches:
        d = biz[b.id]
        e = StockBatch.expiry_date
        bucket_expr = case((e < d, BUCKET_EXPIRED), (e == d, BUCKET_TODAY),
                           (e <= d + timedelta(days=7), BUCKET_7), else_=BUCKET_30)
        rows = (db.query(bucket_expr.label("bk"), func.count(StockBatch.id),
                         func.coalesce(func.sum(StockBatch.remaining_qty), 0),
                         func.coalesce(func.sum(StockBatch.remaining_qty * StockBatch.unit_cost), 0))
                .filter(StockBatch.company_id == emp.company_id,
                        StockBatch.branch_id == b.id,
                        StockBatch.status == SI.OPEN,
                        StockBatch.remaining_qty > 0,
                        e.isnot(None),
                        e <= d + timedelta(days=HORIZON_DAYS))
                .group_by("bk").all())
        for bk, cnt, qty, val in rows:
            t = buckets[bk]
            t["lots"] += int(cnt or 0)
            t["qty"] = float(Decimal(str(t["qty"])) + Decimal(str(qty or 0)))
            t["value_at_risk"] = float((Decimal(str(t["value_at_risk"])) + Decimal(str(val or 0)))
                                       .quantize(Decimal("0.01")))

    # ⚠️  QARZ «TAXMINIY» — ro'yxatdagi `provisional_exposure` bilan AYNI EMAS:
    #     u yerda qarzning O'Z qaytgan partiyasi ayiriladi (qator-ba-qator, qimmat).
    #     Bu yerda YUQORI CHEGARA beriladi va nomi ham shunday: kartani chizish
    #     uchun yetarli, hisobot o'rniga ishlatilmaydi.
    open_expr = LotShortfall.qty - LotShortfall.resolved_qty
    s_cnt, s_qty, s_exp = (db.query(
        func.count(LotShortfall.id), func.coalesce(func.sum(open_expr), 0),
        func.coalesce(func.sum(open_expr * LotShortfall.unit_cost), 0))
        .filter(LotShortfall.company_id == emp.company_id,
                LotShortfall.branch_id.in_(bids), open_expr > 0).one())

    live = [StockBatch.company_id == emp.company_id, StockBatch.branch_id.in_(bids),
            StockBatch.status == SI.OPEN, StockBatch.remaining_qty > 0]
    est = (db.query(func.count(StockBatch.id))
           .filter(*live, StockBatch.source_type.in_(sorted(_provisional()))).scalar() or 0)
    unk = (db.query(func.count(StockBatch.id))
           .filter(*live, StockBatch.unit_cost <= 0).scalar() or 0)
    tracked = (db.query(func.count(Product.id))
               .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                       Product.track_lots.is_(True)).scalar() or 0)
    return {"expiry": buckets,
            "shortfalls": {"open_count": int(s_cnt or 0), "open_qty": _f(s_qty),
                           "provisional_exposure_max": _f(s_exp)},
            "cost_quality": {"estimated_lots": int(est), "unknown_cost_lots": int(unk),
                             "tracked_products": int(tracked)},
            "business_dates": {str(k): v.isoformat() for k, v in biz.items()},
            "branches": len(branches)}


# ══════════════════════════════════════════════════════════════════════════════
#  FUNKSIYA MAVJUDLIGI — UI DARVOZASI
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/availability")
def lot_availability(emp: Employee = Depends(require("ombor.view")),
                     db: Session = Depends(get_db)):
    """UI shu javobga qarab amallarni OCHADI yoki YOPADI.

    ⚠️  BU HAM `ombor.view` TALAB QILADI. Ilgari javob HAR xodimga ochiq edi va
        kassir filiallar ro'yxatini, muhit nomini va kuzatuvli tovar sonini
        ko'ra olardi — bu ma'lumot unga kerak emas. UI uchun yo'qotish yo'q:
        ruxsati yo'q foydalanuvchida partiya bo'limi baribir ko'rinmaydi.

    ⚠️  NEGA KERAK. Production'da partiya kuzatuvi YOPIQ (`/lots/enable` 403).
        Frontend buni O'ZI taxmin qilmasin: muhit nomini brauzerda tekshirish
        yoki 403 ni kutib ko'rish — ikkalasi ham noto'g'ri. Server AYTADI.

    ⚠️  SIR CHIQMAYDI: faqat muhit nomi (u allaqachon ochiq `/health` da bor),
        sxema muammolari SONI (nomlari emas) va ruxsat bayroqlari.
    """
    from app.core import required_schema as rs
    from app.core.deps import FULL_ACCESS_ROLES, effective_permissions

    perms = effective_permissions(emp, db)
    full = emp.role.code in FULL_ACCESS_ROLES

    def can(code: str) -> bool:
        return full or code in perms

    try:
        problems = rs.missing(db.get_bind())
    except Exception:      # noqa: BLE001 — tayyorlik o'qilmasa ham ekran ochilsin
        problems = ["introspeksiya yiqildi"]
    branches = _scope_branches(db, emp, None)
    rows = []
    for b in branches:
        try:
            LP.validate_for_expiry(db, b.id)
            tz_ok = True
        except LP.TimezoneNotConfigured:
            tz_ok = False
        rows.append({"id": str(b.id), "name": b.name, "timezone": b.timezone,
                     "timezone_supported": tz_ok,
                     "timezone_confirmed": bool(LP.tz_confirmed(db, emp.company_id, b.id))})
    tracked = (db.query(Product.id)
               .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                       Product.track_lots.is_(True)).count())
    allowed = bool(LP.activation_allowed())
    env = None
    for _name in ("environment_name", "env_name"):
        fn = getattr(LP, _name, None)
        if callable(fn):
            env = fn()
            break
    return {
        "activation_allowed": allowed,
        "environment": env,
        "schema_ready": not problems,
        "schema_problem_count": len(problems),
        "tracked_products": int(tracked),
        "permissions": {"view": can("ombor.view"), "edit": can("ombor.edit"),
                        "settings": can("sozlamalar.edit"), "reports": can("hisobot.view"),
                        "purchases": can("xaridlar.view")},
        "can_enable": bool(allowed and not problems and can("ombor.edit")),
        "can_write": bool(not problems and can("ombor.edit")),
        "branches": rows,
        "supported_timezones": _tz_names(),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  BITTA PARTIYA — TAFSILOT VA TARIX
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/batches/{lot_id}")
def batch_detail(lot_id: uuid.UUID,
                 emp: Employee = Depends(require("ombor.view")),
                 db: Session = Depends(get_db)):
    """Partiya + MANBASI (qabul/xarid hujjati) + TARIXI (sotuv, qaytarish, harakat, yopish).

    ⚠️  TARIX AGREGATLANMAYDI: har allokatsiya o'z qatori bilan ko'rinadi —
        operator «bu partiyaga nima bo'ldi» degan savolga hujjat darajasida
        javob olishi kerak. Ro'yxatlar 50 tadan cheklangan.
    """
    b = db.get(StockBatch, lot_id)
    if b is None or b.company_id != emp.company_id:
        raise HTTPException(404, "Partiya topilmadi")
    if b.branch_id not in {x.id for x in _scope_branches(db, emp, None)}:
        raise HTTPException(404, "Partiya topilmadi")
    biz = LP.business_date(db, b.branch_id)
    p = db.get(Product, b.product_id)
    br = db.get(Branch, b.branch_id)
    sup = db.get(Supplier, b.supplier_id) if b.supplier_id else None

    source = {"type": b.source_type,
              "receiving_id": str(b.receiving_id) if b.receiving_id else None,
              "purchase_item_id": str(b.purchase_item_id) if b.purchase_item_id else None,
              "external_lot_id": b.external_lot_id, "purchase": None, "receiving": None}
    rec = db.get(Receiving, b.receiving_id) if b.receiving_id else None
    if rec is not None and rec.company_id == emp.company_id:
        source["receiving"] = {
            "id": str(rec.id), "source": rec.source,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "committed_at": rec.committed_at.isoformat() if rec.committed_at else None}
    pur_id = rec.purchase_id if rec is not None else None
    if pur_id is None and b.purchase_item_id:
        pi = db.get(PurchaseItem, b.purchase_item_id)
        pur_id = pi.purchase_id if pi is not None else None
    if pur_id is not None:
        pur = db.get(Purchase, pur_id)
        if pur is not None and pur.company_id == emp.company_id:
            source["purchase"] = {
                "id": str(pur.id), "doc_no": pur.doc_no,
                "purchase_date": pur.purchase_date.isoformat() if pur.purchase_date else None,
                "total": _f(pur.total),
                "status": getattr(pur.status, "value", str(pur.status)),
                "supplier_id": str(pur.supplier_id) if pur.supplier_id else None}

    sales = (db.query(SaleItemLotAllocation, Sale)
             .join(SaleItem, SaleItem.id == SaleItemLotAllocation.sale_item_id)
             .join(Sale, Sale.id == SaleItem.sale_id)
             .filter(SaleItemLotAllocation.stock_batch_id == b.id)
             .order_by(Sale.sold_at.desc()).limit(50).all())
    rets = (db.query(ReturnItemLotAllocation, Return)
            .join(ReturnItem, ReturnItem.id == ReturnItemLotAllocation.return_item_id)
            .join(Return, Return.id == ReturnItem.return_id)
            .filter(ReturnItemLotAllocation.stock_batch_id == b.id)
            .order_by(Return.created_at.desc()).limit(50).all())
    movs = (db.query(StockMovementLotAllocation, StockMovement)
            .join(StockMovement, StockMovement.id == StockMovementLotAllocation.stock_movement_id)
            .filter(StockMovementLotAllocation.stock_batch_id == b.id)
            .order_by(StockMovement.created_at.desc()).limit(50).all())
    res = (db.query(LotShortfallResolution)
           .filter(LotShortfallResolution.stock_batch_id == b.id)
           .order_by(LotShortfallResolution.resolved_at.desc()).limit(50).all())
    emp_names = _names(db, Employee, {m.employee_id for _a, m in movs})

    def _qsum(rows):
        return float(sum((Decimal(str(a.qty or 0)) for a, *_x in rows), Decimal("0")))

    return {
        "id": str(b.id), "branch_id": str(b.branch_id), "branch": br.name if br else None,
        "product_id": str(b.product_id), "product": p.name if p else None,
        "unit_code": _units(db, {p.id}).get(p.id) if p else None,
        "track_lots": bool(p.track_lots) if p else None,
        "track_expiry": bool(p.track_expiry) if p else None,
        "batch_number": b.batch_no,
        "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
        "business_date": biz.isoformat(), "bucket": _bucket(b.expiry_date, biz),
        "expired": bool(b.expiry_date and b.expiry_date < biz),
        "days_left": (b.expiry_date - biz).days if b.expiry_date else None,
        "received_qty": _f(b.received_qty), "remaining_qty": _f(b.remaining_qty),
        "unit_cost": _f(b.unit_cost), "value": _value(b), "cost_basis": _cost_basis(b),
        "status": b.status, "source_type": b.source_type,
        "supplier_id": str(b.supplier_id) if b.supplier_id else None,
        "supplier": sup.name if sup else None,
        "received_at": b.received_at.isoformat() if b.received_at else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        "source": source,
        "totals": {"sold_qty": _qsum(sales), "returned_qty": _qsum(rets),
                   "movement_qty": _qsum(movs),
                   "resolved_qty": float(sum((Decimal(str(r.qty or 0)) for r in res), Decimal("0")))},
        "sales": [{"sale_id": str(s.id), "receipt_no": s.receipt_no,
                   "sold_at": s.sold_at.isoformat() if s.sold_at else None,
                   "qty": _f(a.qty), "unit_cost": _f(a.unit_cost)} for a, s in sales],
        "returns": [{"return_id": str(r.id), "return_no": r.return_no,
                     "created_at": r.created_at.isoformat() if r.created_at else None,
                     "qty": _f(a.qty), "restock": bool(r.restock)} for a, r in rets],
        "movements": [{"movement_id": str(m.id),
                       "type": getattr(m.type, "value", str(m.type)),
                       "qty": _f(a.qty), "reason": m.reason,
                       "employee": emp_names.get(m.employee_id),
                       "created_at": m.created_at.isoformat() if m.created_at else None}
                      for a, m in movs],
        "resolutions": [{"id": str(r.id), "shortfall_id": str(r.shortfall_id), "kind": r.kind,
                         "qty": _f(r.qty), "provisional_cost": _f(r.provisional_cost),
                         "actual_cost": _f(r.actual_cost), "variance": _f(r.variance),
                         "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None}
                        for r in res],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  ANIQLANMAGAN QOLDIQ (SHORTFALL) — TAFSILOT + YOPISH NOMZODLARI
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/shortfalls/{shortfall_id}")
def shortfall_detail(shortfall_id: uuid.UUID,
                     emp: Employee = Depends(require("ombor.view")),
                     db: Session = Depends(get_db)):
    """Bitta qarz: qaysi sotuvdan kelgan, qancha ochiq, oldingi yopishlar va NOMZOD partiyalar.

    ⚠️  NOMZODLAR SHU YERDA BERILADI. Aks holda UI «qaysi partiyalar bilan
        yopish mumkin» ro'yxatini o'zi yig'ardi va FEFO/qaytgan-partiya
        farqini bilmasdan noto'g'ri tanlov taklif qilardi.

    ⚠️  `own_unattributed` — qarzning O'Z qaytgan partiyasi (netting). Uni
        birinchi yopish og'ish tug'dirmaydi; UI shuni oldinga qo'yadi.
    """
    from app.models.inventory import LotShortfall
    from app.services import lot_resolution as LRes

    sf = db.get(LotShortfall, shortfall_id)
    if sf is None or sf.company_id != emp.company_id:
        raise HTTPException(404, "Qarz topilmadi")
    if sf.branch_id not in {x.id for x in _scope_branches(db, emp, None)}:
        raise HTTPException(404, "Qarz topilmadi")

    bk = LRes.book(db, sf)
    rec, rev = LRes.variance_totals(db, [sf.id]).get(sf.id, (Decimal("0"), Decimal("0")))
    legacy = Decimal("0")
    if bk.events_qty == 0 and LRes.q3(sf.resolved_qty) > 0:
        legacy = (LRes.c2(sf.resolved_cost)
                  - LRes.c2(LRes.q3(sf.resolved_qty) * LRes.c2(sf.unit_cost)))
    open_q = LRes.q3(sf.qty) - LRes.q3(sf.resolved_qty)
    exposure = LRes.c2(max(open_q - bk.own_u_remaining, Decimal("0")) * LRes.c2(sf.unit_cost))

    p = db.get(Product, sf.product_id)
    br = db.get(Branch, sf.branch_id)
    sale = None
    if sf.sale_item_id:
        row = (db.query(SaleItem, Sale).join(Sale, Sale.id == SaleItem.sale_id)
               .filter(SaleItem.id == sf.sale_item_id).first())
        if row is not None:
            si, s = row
            cashier = _names(db, Employee, {s.cashier_id}).get(s.cashier_id)
            sale = {"sale_id": str(s.id), "sale_item_id": str(si.id), "receipt_no": s.receipt_no,
                    "sold_at": s.sold_at.isoformat() if s.sold_at else None,
                    "qty": _f(si.qty), "unit_price": _f(si.unit_price),
                    "provisional_qty": _f(getattr(si, "provisional_qty", 0)),
                    "cashier": cashier}

    ev = (db.query(LotShortfallResolution)
          .filter(LotShortfallResolution.shortfall_id == sf.id)
          .order_by(LotShortfallResolution.resolved_at.asc(),
                    LotShortfallResolution.line_no.asc()).limit(200).all())
    lots = {b.id: b for b in db.query(StockBatch)
            .filter(StockBatch.id.in_({e.stock_batch_id for e in ev})).all()} if ev else {}

    cands = (db.query(StockBatch)
             .filter(StockBatch.company_id == emp.company_id,
                     StockBatch.product_id == sf.product_id,
                     StockBatch.branch_id == sf.branch_id,
                     StockBatch.status == SI.OPEN,
                     StockBatch.remaining_qty > 0)
             .order_by(StockBatch.expiry_date.asc().nullslast(),
                       StockBatch.received_at.asc(), StockBatch.id.asc()).limit(100).all())
    biz = LP.business_date(db, sf.branch_id)

    return {
        "id": str(sf.id), "product_id": str(sf.product_id), "product": p.name if p else None,
        "unit_code": _units(db, {p.id}).get(p.id) if p else None,
        "branch_id": str(sf.branch_id), "branch": br.name if br else None,
        "business_date": biz.isoformat(),
        "qty": _f(sf.qty), "resolved_qty": _f(sf.resolved_qty),
        "resolved_real_qty": _f(bk.resolved_real), "netted_qty": _f(bk.resolved_net),
        "returned_qty": _f(sf.returned_qty),
        "returned_unattributed_on_hand": _f(bk.own_u_remaining),
        "open_qty": float(open_q), "closed": bool(open_q <= 0),
        "unit_cost": _f(sf.unit_cost), "resolved_cost": _f(sf.resolved_cost),
        "cogs_variance_recognised": float(rec), "cogs_variance_reversed": float(rev),
        "cogs_variance_legacy": float(legacy), "cogs_variance": float(rec - rev + legacy),
        "provisional_exposure": float(exposure), "legacy_shape": bool(bk.legacy),
        "reason": sf.reason,
        "created_at": sf.created_at.isoformat() if sf.created_at else None,
        "resolved_at": sf.resolved_at.isoformat() if getattr(sf, "resolved_at", None) else None,
        "sale": sale,
        "resolutions": [{
            "id": str(e.id), "kind": e.kind, "line_no": e.line_no, "qty": _f(e.qty),
            "stock_batch_id": str(e.stock_batch_id),
            "batch_number": (lots.get(e.stock_batch_id).batch_no if lots.get(e.stock_batch_id) else None),
            "expiry_date": e.expiry_date.isoformat() if e.expiry_date else None,
            "provisional_unit_cost": _f(e.provisional_unit_cost),
            "actual_unit_cost": _f(e.actual_unit_cost),
            "provisional_cost": _f(e.provisional_cost), "actual_cost": _f(e.actual_cost),
            "variance": _f(e.variance),
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None} for e in ev],
        "candidate_lots": [{
            "id": str(c.id), "batch_number": c.batch_no,
            "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
            "bucket": _bucket(c.expiry_date, biz),
            "days_left": (c.expiry_date - biz).days if c.expiry_date else None,
            "remaining_qty": _f(c.remaining_qty), "unit_cost": _f(c.unit_cost),
            "cost_basis": _cost_basis(c), "source_type": c.source_type,
            "own_unattributed": bool((c.source_type or "") in _provisional()),
            # ⚠️  BIRLIK farqi EMAS, TO'LIQ summa: operator «bu partiyani
            #     tanlasam foyda qancha o'zgaradi» ni ko'rishi kerak. Bog'lash
            #     ochiq qarzdan va partiya qoldig'idan ortiq bo'lolmaydi, shu
            #     bois miqdor ikkovining KICHIGI bilan cheklanadi.
            "unit_variance": float(LRes.c2(Decimal(str(c.unit_cost or 0)))
                                   - LRes.c2(Decimal(str(sf.unit_cost or 0)))),
            "attachable_qty": float(min(open_q, LRes.q3(c.remaining_qty))),
            "variance_if_full": float(LRes.c2(
                min(open_q, LRes.q3(c.remaining_qty))
                * (LRes.c2(Decimal(str(c.unit_cost or 0)))
                   - LRes.c2(Decimal(str(sf.unit_cost or 0))))))}
            for c in cands],
    }
