"""Mobil "Tovar qabul qilish" — nakladnoy skani → AI o'qish → moslash → omborga kirim.

Xavfsizlik: AI natijasi FAQAT taklif; ombor faqat foydalanuvchi tasdig'idan keyin o'zgaradi.
Har qabul audit uchun saqlanadi (rasm + AI dastlabki + yakuniy tahrir)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product, ProductBarcode, Unit
from app.models.enums import CreditTxnType, MovementType, PurchaseStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.purchasing import Purchase, PurchaseItem, Supplier, SupplierLedger
from app.models.receiving import Receiving
from app.services.receiving_ai import match_products, read_invoice

router = APIRouter(tags=["receiving"])

_DEFAULT_SUPPLIER = "Qabul (mobil)"


class ScanIn(BaseModel):
    image_b64: str
    media_type: str = "image/jpeg"


@router.post("/receiving/scan")
def scan(data: ScanIn, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """Rasmni AI bilan o'qib, mavjud mahsulotlar bilan moslashtiradi. OMBORNI O'ZGARTIRMAYDI."""
    units = {u.id: u.code for u in db.query(Unit).all()}
    prods = (
        db.query(Product)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None))
        .all()
    )
    plist = [{"id": str(p.id), "name": p.name, "unit_code": units.get(p.unit_id, "dona"),
              "base_buy_price": float(p.base_buy_price)} for p in prods]
    names = [p["name"] for p in plist]
    rows, source = read_invoice(data.image_b64, data.media_type, names)
    if source.startswith("error:"):
        raise HTTPException(502, f"AI o'qishda xato: {source[6:]}")
    items = match_products(rows, plist)
    return {"source": source, "items": items, "ai_raw": rows}


class CommitItem(BaseModel):
    product_id: uuid.UUID | None = None       # mavjud mahsulot
    new_name: str | None = Field(default=None, max_length=200)  # yoki yangi mahsulot (bazada yo'q)
    new_sell_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    new_category_id: uuid.UUID | None = None  # yangi mahsulot uchun kategoriya (ixtiyoriy)
    new_barcode: str | None = Field(default=None, max_length=64)  # skanerlangan shtrix-kod (bazada yo'q bo'lsa mahsulotga biriktiriladi)
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    ai_name: str | None = None
    unit: str | None = None


class CommitIn(BaseModel):
    items: list[CommitItem]
    image_b64: str | None = None
    source: str = "ai"
    ai_raw: list = []
    supplier_id: uuid.UUID | None = None
    payment: Literal["cash", "credit"] = "cash"   # qarzga olindi -> beruvchi balansi oshadi
    client_uuid: uuid.UUID | None = None


@router.post("/receiving/commit")
def commit(data: CommitIn, emp: Employee = Depends(require("xaridlar.edit")), db: Session = Depends(get_db)):
    if data.client_uuid:
        ex = db.query(Receiving).filter(
            Receiving.client_uuid == data.client_uuid, Receiving.company_id == emp.company_id
        ).first()
        if ex:
            return {"ok": True, "receiving_id": str(ex.id), "duplicate": True}
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")

    branch = db.query(Branch).filter(
        Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first()
    if not branch:
        raise HTTPException(400, "Filial topilmadi")

    # Yetkazib beruvchi — berilmasa "Qabul (mobil)" avto
    sup = None
    if data.supplier_id:
        sup = db.get(Supplier, data.supplier_id)
        if not sup or sup.company_id != emp.company_id:
            raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    if sup is None:
        sup = db.query(Supplier).filter(
            Supplier.company_id == emp.company_id, Supplier.name == _DEFAULT_SUPPLIER,
            Supplier.deleted_at.is_(None)).first()
        if sup is None:
            sup = Supplier(company_id=emp.company_id, name=_DEFAULT_SUPPLIER)
            db.add(sup)
            db.flush()

    all_units = db.query(Unit).all()
    units = {u.id: u.code for u in all_units}
    default_unit_id = all_units[0].id if all_units else None
    now = datetime.now(timezone.utc)
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in data.items)
    is_credit = data.payment == "credit"
    seq = db.query(Purchase).filter(Purchase.company_id == emp.company_id).count()
    pur = Purchase(
        doc_no=f"KIR-{1042 + seq + 1}", company_id=emp.company_id, branch_id=branch.id,
        supplier_id=sup.id, employee_id=emp.id, purchase_date=date.today(),
        status=PurchaseStatus.debt if is_credit else PurchaseStatus.received,
        subtotal=total, total=total, paid_amount=Decimal("0") if is_credit else total,
    )
    db.add(pur)
    db.flush()

    results = []
    final_items = []
    total_qty = Decimal("0")
    for i in data.items:
        # Yangi mahsulot uchun kategoriya (berilsa — shu kompaniyaniki bo'lishi shart)
        cat_id = None
        if i.new_category_id:
            from app.models.catalog import Category as _Cat
            _c = db.get(_Cat, i.new_category_id)
            if _c and _c.company_id == emp.company_id and _c.deleted_at is None:
                cat_id = _c.id
        if i.product_id:
            prod = db.get(Product, i.product_id)
            if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
                raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
        elif i.new_name and i.new_name.strip():
            nm = i.new_name.strip()
            # Dedup: shu nomli faol mahsulot bo'lsa — yangisini yaratmay, o'shanga kirim qilamiz
            existing = (
                db.query(Product)
                .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                        func.lower(Product.name) == nm.lower())
                .first()
            )
            if existing is not None:
                prod = existing
            else:
                # Bazada yo'q — yangi mahsulot (kelish narxi = unit_cost, sotish = new_sell yoki +20%)
                cost0 = Decimal(str(i.unit_cost))
                sell0 = Decimal(str(i.new_sell_price)) if i.new_sell_price is not None else (cost0 * Decimal("1.2"))
                pseq = db.query(Product).filter(Product.company_id == emp.company_id).count()
                prod = Product(company_id=emp.company_id, name=nm, category_id=cat_id,
                               article_code=f"R-{1000 + pseq + 1}", sku=str(20000 + pseq + 1),
                               unit_id=default_unit_id, base_buy_price=cost0, base_sell_price=sell0,
                               tax_rate=Decimal("12"))
                db.add(prod)
                db.flush()
        else:
            raise HTTPException(400, "Mahsulot yoki yangi nom kerak")
        # Narxlar yangilanishi: kelish narxi (unit_cost>0) va sotish narxi (new_sell_price berilsa)
        # bazadagidan farq qilsa — mahsulot kartochkasida ham yangilanadi (foydalanuvchi so'rovi).
        if i.unit_cost and Decimal(str(i.unit_cost)) != Decimal(str(prod.base_buy_price)):
            prod.base_buy_price = Decimal(str(i.unit_cost))
        if i.new_sell_price is not None and Decimal(str(i.new_sell_price)) > 0 \
                and Decimal(str(i.new_sell_price)) != Decimal(str(prod.base_sell_price)):
            prod.base_sell_price = Decimal(str(i.new_sell_price))
        if cat_id and prod.category_id is None:
            prod.category_id = cat_id
        # Kirim kelgan mahsulot arxivda bo'lsa — avtomatik faolga qaytadi (qoldiq endi bor)
        if not prod.is_active:
            prod.is_active = True
        # Skanerlangan shtrix-kod bazada yo'q bo'lsa — shu mahsulotga biriktiramiz
        # (yangi mahsulotga ham, mavjudga ham; band bo'lsa jimgina o'tkazamiz)
        if i.new_barcode:
            bc = "".join(ch for ch in i.new_barcode if ch.isdigit())
            if bc and not db.query(ProductBarcode).filter(ProductBarcode.barcode == bc).first():
                db.add(ProductBarcode(product_id=prod.id, barcode=bc, is_primary=False))
        qty, cost = Decimal(str(i.qty)), Decimal(str(i.unit_cost))
        total_qty += qty
        db.add(PurchaseItem(purchase_id=pur.id, product_id=prod.id, qty=qty,
                            unit_cost=cost, line_total=qty * cost))
        inv = db.query(Inventory).filter(
            Inventory.product_id == prod.id, Inventory.branch_id == branch.id).first()
        old_qty = float(inv.qty) if inv else 0.0
        if inv is None:
            inv = Inventory(product_id=prod.id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        inv.qty = Decimal(str(inv.qty)) + qty
        inv.updated_at = now
        if inv.qty > Decimal(str(inv.min_qty or 0)):
            inv.low_alerted = False  # min ustiga chiqdi — keyingi tushishda yana ogohlantiriladi
        db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.purchase_in,
                            qty=qty, unit_cost=cost, balance_after=inv.qty, ref_type="receiving",
                            ref_id=pur.id, employee_id=emp.id, created_at=now))
        _uc = units.get(prod.unit_id, "dona")
        results.append({"product": prod.name, "old_qty": old_qty, "added": float(qty),
                        "new_qty": float(inv.qty), "unit": _uc})
        final_items.append({"product_id": str(prod.id), "name": prod.name, "qty": float(qty),
                            "unit_cost": float(cost), "ai_name": i.ai_name, "unit": i.unit or _uc})

    # Qarzga olindi — yetkazib beruvchi balansi oshadi (biz qarzmiz)
    if is_credit:
        sup.balance = Decimal(str(sup.balance or 0)) + total
        db.add(SupplierLedger(supplier_id=sup.id, type=CreditTxnType.charge, amount=total,
                              balance_after=sup.balance, ref_type="receiving", ref_id=pur.id, created_at=now))

    rec = Receiving(
        company_id=emp.company_id, branch_id=branch.id, employee_id=emp.id, purchase_id=pur.id,
        source=data.source, image_b64=data.image_b64, ai_raw=data.ai_raw, final_items=final_items,
        total_types=len(final_items), total_qty=total_qty, committed_at=now, client_uuid=data.client_uuid,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"ok": True, "receiving_id": str(rec.id), "purchase_id": str(pur.id),
            "doc_no": pur.doc_no, "results": results, "payment": data.payment,
            "supplier": sup.name, "total_types": len(final_items), "total_qty": float(total_qty)}


@router.get("/receiving")
def history(limit: int = 50, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == emp.company_id).all())
    rows = (
        db.query(Receiving)
        .filter(Receiving.company_id == emp.company_id, Receiving.committed_at.isnot(None))
        .order_by(Receiving.committed_at.desc())
        .limit(max(1, min(limit, 200))).all()
    )
    return [{
        "id": str(r.id), "at": r.committed_at, "source": r.source,
        "employee": names.get(r.employee_id, "—"),
        "total_types": r.total_types, "total_qty": float(r.total_qty),
    } for r in rows]


@router.get("/receiving/{receiving_id}")
def detail(receiving_id: uuid.UUID, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    r = db.get(Receiving, receiving_id)
    if not r or r.company_id != emp.company_id:
        raise HTTPException(404, "Qabul topilmadi")
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == emp.company_id).all())
    return {
        "id": str(r.id), "at": r.committed_at, "source": r.source,
        "employee": names.get(r.employee_id, "—"),
        "total_types": r.total_types, "total_qty": float(r.total_qty),
        "items": r.final_items, "ai_raw": r.ai_raw, "image_b64": r.image_b64,
    }
