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
    period: str | None = None,   # today | week | month
    q: str | None = None,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from datetime import timedelta

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
    if method:
        mq = db.query(SalePayment.sale_id).filter(SalePayment.method_code == method).subquery()
        query = query.filter(Sale.id.in_(db.query(mq.c.sale_id)))
    if period:
        now = datetime.now(timezone.utc)
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = None
        if start:
            query = query.filter(Sale.sold_at >= start)
    rows = query.order_by(Sale.sold_at.desc()).limit(min(limit, 300)).all()

    out = []
    for s, cashier_name in rows:
        pay = db.query(SalePayment.method_code).filter(SalePayment.sale_id == s.id).first()
        m = pay[0] if pay else "cash"
        cnt = db.query(func.coalesce(func.sum(SaleItem.qty), 0)).filter(SaleItem.sale_id == s.id).scalar()
        first = db.query(SaleItem.name_snapshot).filter(SaleItem.sale_id == s.id).first()
        out.append({
            "id": str(s.id),
            "receipt_no": s.receipt_no,
            "sold_at": s.sold_at,
            "cashier": cashier_name,
            "method": m,
            "item_count": float(cnt or 0),
            "first_item": first[0] if first else "",
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
    from app.models.customers import CreditTransaction, Customer
    from app.models.enums import CashMovementType, CreditTxnType, SaleStatus, ShiftStatus
    from app.models.sales import SaleItem
    from app.models.shifts import CashMovement, Shift

    # Idempotentlik — offline kassa qayta yuborsa ikki marta yozilmaydi
    if data.client_uuid:
        ex = db.query(Return).filter(Return.client_uuid == data.client_uuid).first()
        if ex:
            return {"id": str(ex.id), "return_no": ex.return_no, "total": float(ex.total)}

    if not data.items:
        raise HTTPException(400, "Qaytarish uchun mahsulot tanlanmagan")
    for i in data.items:
        if i.qty <= 0:
            raise HTTPException(400, "Qaytarish miqdori noto'g'ri")

    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    now = datetime.now(timezone.utc)

    # Asl chek bo'yicha limit: har mahsulot uchun (sotilgan − oldin qaytarilgan) dan oshmasin
    original = None
    if data.original_sale_id:
        original = db.get(Sale, data.original_sale_id)
        if not original or original.company_id != emp.company_id:
            raise HTTPException(404, "Asl chek topilmadi")
        sold: dict = {}
        for si in db.query(SaleItem).filter(SaleItem.sale_id == original.id).all():
            sold[si.product_id] = sold.get(si.product_id, Decimal("0")) + Decimal(str(si.qty))
        prev_returns = db.query(Return.id).filter(Return.original_sale_id == original.id).all()
        prev_ids = [r[0] for r in prev_returns]
        if prev_ids:
            for ri in db.query(ReturnItem).filter(ReturnItem.return_id.in_(prev_ids)).all():
                sold[ri.product_id] = sold.get(ri.product_id, Decimal("0")) - Decimal(str(ri.qty))
        for i in data.items:
            left = sold.get(i.product_id)
            if left is None:
                raise HTTPException(400, "Mahsulot bu chekda yo'q")
            if Decimal(str(i.qty)) > left:
                raise HTTPException(400, f"Qaytarish miqdori sotilganidan oshiq (qoldi: {left})")

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
        client_uuid=data.client_uuid,
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

    # Naqd qaytarish — kassirning ochiq smenasidan chiqim (g'azna hisobi to'g'ri bo'lsin)
    if data.refund_method == "cash":
        shift = (
            db.query(Shift)
            .filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open)
            .first()
        )
        if shift:
            db.add(
                CashMovement(
                    shift_id=shift.id,
                    type=CashMovementType.payout,
                    amount=total,
                    reason=f"Qaytarish {ret.return_no}",
                    employee_id=emp.id,
                    created_at=now,
                )
            )

    # Nasiya cheki qaytarilsa — mijoz qarzidan ayiriladi
    if data.refund_method == "credit" and original and original.customer_id:
        cust = db.get(Customer, original.customer_id)
        if cust:
            cust.credit_balance = max(Decimal("0"), Decimal(str(cust.credit_balance)) - total)
            db.add(
                CreditTransaction(
                    customer_id=cust.id,
                    type=CreditTxnType.adjustment,
                    amount=-total,
                    balance_after=cust.credit_balance,
                    sale_id=original.id,
                    employee_id=emp.id,
                    created_at=now,
                )
            )

    # Asl chek statusi
    db.flush()  # joriy qaytarish qatorlari ham hisobga kirsin (autoflush o'chiq)
    if original is not None:
        sold_total: dict = {}
        for si in db.query(SaleItem).filter(SaleItem.sale_id == original.id).all():
            sold_total[si.product_id] = sold_total.get(si.product_id, Decimal("0")) + Decimal(str(si.qty))
        ret_ids = [r[0] for r in db.query(Return.id).filter(Return.original_sale_id == original.id).all()]
        returned: dict = {}
        for ri in db.query(ReturnItem).filter(ReturnItem.return_id.in_(ret_ids)).all():
            returned[ri.product_id] = returned.get(ri.product_id, Decimal("0")) + Decimal(str(ri.qty))
        fully = all(returned.get(pid, Decimal("0")) >= q for pid, q in sold_total.items())
        original.status = SaleStatus.refunded if fully else SaleStatus.partially_refunded

    db.commit()
    return {"id": str(ret.id), "return_no": ret.return_no, "total": float(total)}
