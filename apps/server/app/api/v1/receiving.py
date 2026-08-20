"""Mobil "Tovar qabul qilish" — nakladnoy skani → AI o'qish → moslash → omborga kirim.

Xavfsizlik: AI natijasi FAQAT taklif; ombor faqat foydalanuvchi tasdig'idan keyin o'zgaradi.
Har qabul audit uchun saqlanadi (rasm + AI dastlabki + yakuniy tahrir)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product, Unit
from app.models.enums import MovementType, PurchaseStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.purchasing import Purchase, PurchaseItem, Supplier
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
    product_id: uuid.UUID
    qty: float = Field(gt=0, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    ai_name: str | None = None
    unit: str | None = None


class CommitIn(BaseModel):
    items: list[CommitItem]
    image_b64: str | None = None
    source: str = "ai"
    ai_raw: list = []
    supplier_id: uuid.UUID | None = None
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

    units = {u.id: u.code for u in db.query(Unit).all()}
    now = datetime.now(timezone.utc)
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in data.items)
    seq = db.query(Purchase).filter(Purchase.company_id == emp.company_id).count()
    pur = Purchase(
        doc_no=f"KIR-{1042 + seq + 1}", company_id=emp.company_id, branch_id=branch.id,
        supplier_id=sup.id, employee_id=emp.id, purchase_date=date.today(),
        status=PurchaseStatus.received, subtotal=total, total=total, paid_amount=total,
    )
    db.add(pur)
    db.flush()

    results = []
    final_items = []
    total_qty = Decimal("0")
    for i in data.items:
        prod = db.get(Product, i.product_id)
        if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
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

    rec = Receiving(
        company_id=emp.company_id, branch_id=branch.id, employee_id=emp.id, purchase_id=pur.id,
        source=data.source, image_b64=data.image_b64, ai_raw=data.ai_raw, final_items=final_items,
        total_types=len(final_items), total_qty=total_qty, committed_at=now, client_uuid=data.client_uuid,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"ok": True, "receiving_id": str(rec.id), "purchase_id": str(pur.id),
            "doc_no": pur.doc_no, "results": results,
            "total_types": len(final_items), "total_qty": float(total_qty)}


@router.get("/receiving")
def history(limit: int = 50, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == emp.company_id).all())
    rows = (
        db.query(Receiving)
        .filter(Receiving.company_id == emp.company_id, Receiving.committed_at.isnot(None))
        .order_by(Receiving.committed_at.desc())
        .limit(min(limit, 200)).all()
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
