import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import MovementType, ReturnReason
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.sales import Return, ReturnItem, Sale
from app.schemas.sales import ReturnCreate, SaleCreate, SaleOut
from app.services.sales import create_sale

router = APIRouter(tags=["sales"])


@router.post("/sales", response_model=SaleOut)
def new_sale(
    data: SaleCreate,
    emp: Employee = Depends(require("kassa.sell")),
    db: Session = Depends(get_db),
):
    return create_sale(db, emp, data)


@router.get("/sales/cashiers")
def sale_cashiers(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    from app.models.auth import Employee as Emp

    rows = (
        db.query(Emp.full_name)
        .join(Sale, Sale.cashier_id == Emp.id)
        .filter(Sale.company_id == emp.company_id)
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


@router.get("/sales")
def list_sales(
    limit: int = 50,
    method: str | None = None,
    cashier: str | None = None,
    q: str | None = None,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.models.auth import Employee as Emp
    from app.models.sales import SaleItem, SalePayment

    query = (
        db.query(Sale, Emp.full_name)
        .join(Emp, Emp.id == Sale.cashier_id)
        .filter(Sale.company_id == emp.company_id, Sale.deleted_at.is_(None))
    )
    if q:
        query = query.filter(Sale.receipt_no.ilike(f"%{q}%"))
    if cashier:
        query = query.filter(Emp.full_name == cashier)
    rows = query.order_by(Sale.sold_at.desc()).limit(min(limit, 300)).all()

    out = []
    for s, cashier_name in rows:
        pay = db.query(SalePayment.method_code).filter(SalePayment.sale_id == s.id).first()
        m = pay[0] if pay else "cash"
        if method and method != m:
            continue
        cnt = db.query(func.coalesce(func.sum(SaleItem.qty), 0)).filter(SaleItem.sale_id == s.id).scalar()
        out.append({
            "id": str(s.id),
            "receipt_no": s.receipt_no,
            "sold_at": s.sold_at,
            "cashier": cashier_name,
            "method": m,
            "item_count": float(cnt or 0),
            "total": float(s.total),
        })
    return out


@router.get("/sales/find")
def find_sale(
    q: str,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Chekni UID (barcode) yoki chek raqami bo'yicha topish — Qaytarishlar uchun.
    Har mahsulot barcode'i bilan (skanerlab tasdiqlash uchun)."""
    from app.models.auth import Employee as Emp
    from app.models.catalog import ProductBarcode
    from app.models.sales import SaleItem, SalePayment

    term = q.strip().lstrip("#")
    if not term:
        raise HTTPException(400, "Bo'sh so'rov")
    sale = (
        db.query(Sale)
        .filter(
            Sale.company_id == emp.company_id,
            Sale.deleted_at.is_(None),
            (Sale.uid == term) | (Sale.receipt_no == term) | (Sale.receipt_no == "#" + term),
        )
        .first()
    )
    if not sale:
        raise HTTPException(404, "Chek topilmadi")
    cashier = db.query(Emp.full_name).filter(Emp.id == sale.cashier_id).scalar()
    method = db.query(SalePayment.method_code).filter(SalePayment.sale_id == sale.id).first()
    items = []
    for it in db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all():
        bc = db.query(ProductBarcode.barcode).filter(ProductBarcode.product_id == it.product_id).first()
        items.append({
            "product_id": str(it.product_id),
            "name": it.name_snapshot,
            "qty": float(it.qty),
            "unit_price": float(it.unit_price),
            "barcode": bc[0] if bc else "",
        })
    return {
        "id": str(sale.id), "receipt_no": sale.receipt_no, "uid": sale.uid or "",
        "method": method[0] if method else "cash", "sold_at": sale.sold_at,
        "cashier": cashier, "total": float(sale.total), "items": items,
    }


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(
    sale_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    sale = db.get(Sale, sale_id)
    if not sale or sale.company_id != emp.company_id:
        raise HTTPException(404, "Chek topilmadi")
    return sale


@router.post("/returns")
def create_return(
    data: ReturnCreate,
    emp: Employee = Depends(require("qaytarishlar.create")),
    db: Session = Depends(get_db),
):
    if data.client_uuid:
        ex = db.query(Return).filter(Return.client_uuid == data.client_uuid).first()
        if ex:
            return {"id": str(ex.id), "return_no": ex.return_no}

    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    now = datetime.now(timezone.utc)
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_price)) for i in data.items)
    seq = db.query(Return).filter(Return.company_id == emp.company_id).count()
    ret = Return(
        return_no=f"QAY-{1000 + seq + 1}",
        original_sale_id=data.original_sale_id,
        company_id=emp.company_id,
        branch_id=branch.id,
        cashier_id=emp.id,
        reason=ReturnReason(data.reason),
        restock=data.restock,
        refund_method=data.refund_method,
        total=total,
    )
    db.add(ret)
    db.flush()
    for i in data.items:
        line = Decimal(str(i.qty)) * Decimal(str(i.unit_price))
        db.add(
            ReturnItem(
                return_id=ret.id,
                product_id=i.product_id,
                qty=i.qty,
                unit_price=i.unit_price,
                line_total=line,
            )
        )
        if data.restock:  # omborga qaytdi
            inv = (
                db.query(Inventory)
                .filter(Inventory.product_id == i.product_id, Inventory.branch_id == branch.id)
                .first()
            )
            if inv:
                inv.qty = Decimal(str(inv.qty)) + Decimal(str(i.qty))
                inv.updated_at = now
            db.add(
                StockMovement(
                    product_id=i.product_id,
                    branch_id=branch.id,
                    type=MovementType.return_in,
                    qty=Decimal(str(i.qty)),
                    ref_type="return",
                    ref_id=ret.id,
                    employee_id=emp.id,
                    created_at=now,
                )
            )
        else:  # hisobdan chiqarildi
            db.add(
                StockMovement(
                    product_id=i.product_id,
                    branch_id=branch.id,
                    type=MovementType.writeoff,
                    qty=Decimal(str(-i.qty)),
                    ref_type="return",
                    ref_id=ret.id,
                    employee_id=emp.id,
                    created_at=now,
                )
            )
    db.commit()
    return {"id": str(ret.id), "return_no": ret.return_no, "total": float(total)}
