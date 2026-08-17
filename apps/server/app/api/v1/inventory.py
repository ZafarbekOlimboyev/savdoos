from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.inventory import Inventory, StockMovement

router = APIRouter(tags=["inventory"])

MOVE_LABEL = {
    "purchase_in": ("Kirim", "in"),
    "return_in": ("Qaytdi", "in"),
    "sale_out": ("Sotildi", "out"),
    "writeoff": ("Hisobdan", "out"),
    "adjustment": ("Tuzatish", "in"),
}


@router.get("/inventory/overview")
def overview(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    total = db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)
    ).count()
    low = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Inventory.qty > 0, Inventory.qty <= Inventory.min_qty)
        .count()
    )
    out = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Inventory.qty <= 0)
        .count()
    )
    today = datetime.now(timezone.utc).date()
    moves_today = db.query(StockMovement).filter(func.date(StockMovement.created_at) == today).count()
    return {"total_products": total, "low_count": low, "out_count": out, "moves_today": moves_today}


@router.get("/inventory/movements")
def movements(limit: int = 20, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    from app.models.auth import Employee as Emp

    rows = (
        db.query(StockMovement, Product.name, Emp.full_name)
        .join(Product, Product.id == StockMovement.product_id)
        .outerjoin(Emp, Emp.id == StockMovement.employee_id)
        .filter(Product.company_id == emp.company_id)
        .order_by(StockMovement.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    out = []
    for m, name, who in rows:
        label, direction = MOVE_LABEL.get(m.type.value, (m.type.value, "in"))
        out.append({
            "type": label,
            "direction": direction,
            "name": name,
            "qty": float(m.qty),
            "employee": who or "—",
            "at": m.created_at,
        })
    return out


@router.get("/inventory/low")
def low_stock(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    rows = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Inventory.qty <= Inventory.min_qty)
        .order_by(Inventory.qty)
        .all()
    )
    return [{"name": n, "qty": float(q), "min": float(mn)} for n, q, mn in rows]
