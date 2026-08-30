import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.enums import MovementType
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch

router = APIRouter(tags=["inventory"])


def _first_branch(db: Session, company_id):
    b = db.query(Branch).filter(Branch.company_id == company_id, Branch.deleted_at.is_(None)).first()
    if not b:
        raise HTTPException(400, "Filial topilmadi")
    return b


def _get_product(db: Session, product_id, company_id):
    p = db.get(Product, product_id)
    if not p or p.company_id != company_id or p.deleted_at is not None:
        raise HTTPException(400, f"Mahsulot topilmadi: {product_id}")
    return p

MOVE_LABEL = {
    "purchase_in": ("Kirim", "in"),
    "return_in": ("Qaytdi", "in"),
    "sale_out": ("Sotildi", "out"),
    "writeoff": ("Hisobdan", "out"),
    "adjustment": ("Tuzatish", "in"),
    "transfer_in": ("Transfer keldi", "in"),
    "transfer_out": ("Transfer ketdi", "out"),
    "count_adjust": ("Inventarizatsiya", "in"),
}


@router.get("/inventory/overview")
def overview(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    bset = visible_branches(emp, db)  # filialга bog'langan xodim — faqat o'z filiali qoldig'i
    total = db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)
    ).count()
    low = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty > 0, Inventory.qty <= Inventory.min_qty)
    )
    out = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= 0)
    )
    today = datetime.now(timezone.utc).date()
    moves_today = (
        db.query(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .filter(Product.company_id == emp.company_id,  # tenant izolyatsiyasi
                func.date(StockMovement.created_at) == today)
    )
    if bset is not None:
        low = low.filter(Inventory.branch_id.in_(bset))
        out = out.filter(Inventory.branch_id.in_(bset))
        moves_today = moves_today.filter(StockMovement.branch_id.in_(bset))
    return {"total_products": total, "low_count": low.count(), "out_count": out.count(), "moves_today": moves_today.count()}


@router.get("/inventory/movements")
def movements(limit: int = 20, product_id: uuid.UUID | None = None,
              emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    from app.models.auth import Employee as Emp

    from app.core.deps import visible_branches
    bset = visible_branches(emp, db)
    query = (
        db.query(StockMovement, Product.name, Emp.full_name)
        .join(Product, Product.id == StockMovement.product_id)
        .outerjoin(Emp, Emp.id == StockMovement.employee_id)
        .filter(Product.company_id == emp.company_id)
    )
    if bset is not None:
        query = query.filter(StockMovement.branch_id.in_(bset))
    if product_id:
        query = query.filter(StockMovement.product_id == product_id)
    rows = query.order_by(StockMovement.created_at.desc()).limit(min(limit, 100)).all()
    out = []
    for m, name, who in rows:
        label, direction = MOVE_LABEL.get(m.type.value, (m.type.value, "in"))
        # Tuzatish/inventarizatsiya IKKI tomonlama — yo'nalish qty ishorasidan
        if m.type.value in ("adjustment", "count_adjust"):
            direction = "out" if float(m.qty) < 0 else "in"
        out.append({
            "type": label,
            "direction": direction,
            "name": name,
            "qty": float(m.qty),
            "employee": who or "—",
            "at": m.created_at,
        })
    return out


class WriteoffIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, allow_inf_nan=False)
    reason: str | None = None  # brak | expired | inventory | ...


@router.post("/inventory/writeoff")
def writeoff(data: WriteoffIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Hisobdan chiqarish (brak/muddati o'tgan/inventar) — qoldiqni kamaytiradi + ledger."""
    branch = _first_branch(db, emp.company_id)
    prod = _get_product(db, data.product_id, emp.company_id)
    qty = Decimal(str(data.qty))
    inv = db.query(Inventory).filter(Inventory.product_id == prod.id, Inventory.branch_id == branch.id).first()
    have = Decimal(str(inv.qty)) if inv else Decimal("0")
    if qty > have:
        raise HTTPException(400, f"Yetarli qoldiq yo'q: {prod.name} (qoldiq: {have:g})")
    now = datetime.now(timezone.utc)
    inv.qty = have - qty
    inv.updated_at = now
    db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.writeoff,
                         qty=-qty, balance_after=inv.qty, ref_type="writeoff", reason=data.reason,
                         employee_id=emp.id, created_at=now))
    db.commit()
    return {"ok": True, "product": prod.name, "new_qty": float(inv.qty)}


class CountItem(BaseModel):
    product_id: uuid.UUID
    counted: float = Field(ge=0, allow_inf_nan=False)


class CountIn(BaseModel):
    items: list[CountItem]


@router.post("/inventory/count")
def stock_count(data: CountIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Inventarizatsiya — sanoq bilan tizim qoldig'ini solishtiradi; farqqa tuzatish yozadi."""
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    branch = _first_branch(db, emp.company_id)
    now = datetime.now(timezone.utc)
    results = []
    changed = 0
    for it in data.items:
        prod = _get_product(db, it.product_id, emp.company_id)
        counted = Decimal(str(it.counted))
        inv = db.query(Inventory).filter(Inventory.product_id == prod.id, Inventory.branch_id == branch.id).first()
        if inv is None:
            inv = Inventory(product_id=prod.id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        old = Decimal(str(inv.qty))
        diff = counted - old
        if diff != 0:
            changed += 1
            inv.qty = counted
            inv.updated_at = now
            if counted > Decimal(str(inv.min_qty or 0)):
                inv.low_alerted = False
            db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.adjustment,
                                 qty=diff, balance_after=counted, ref_type="count", reason="inventarizatsiya",
                                 employee_id=emp.id, created_at=now))
        results.append({"product": prod.name, "old": float(old), "counted": float(counted), "diff": float(diff)})
    db.commit()
    return {"ok": True, "changed": changed, "results": results}


@router.get("/inventory/low")
def low_stock(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    _bset = visible_branches(emp, db)
    q = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= Inventory.min_qty)
    )
    if _bset is not None:
        q = q.filter(Inventory.branch_id.in_(_bset))
    rows = q.order_by(Inventory.qty).all()
    return [{"name": n, "qty": float(q), "min": float(mn)} for n, q, mn in rows]
