import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require, require_any
from app.db.session import get_db
from app.models.auth import Employee
from app.models.customers import CreditTransaction, Customer, CustomerPayment
from app.models.enums import CreditTxnType
from app.schemas.customer import CreditPayment, CustomerCreate, CustomerOut

router = APIRouter(tags=["customers"])


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    q: str | None = None,
    only_debt: bool = False,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    query = db.query(Customer).filter(
        Customer.company_id == emp.company_id, Customer.deleted_at.is_(None)
    )
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Customer.full_name.ilike(like), Customer.phone.ilike(like)))
    if only_debt:
        query = query.filter(Customer.credit_balance > 0)
    return query.order_by(Customer.full_name).all()


@router.post("/customers", response_model=CustomerOut)
def create_customer(
    data: CustomerCreate,
    # Kassir ham QARZ savdoda yangi mijoz yarata oladi (dizayn: "Yangi mijoz" tab)
    emp: Employee = Depends(require_any("mijozlar.edit", "kassa.sell")),
    db: Session = Depends(get_db),
):
    seq = db.query(Customer).filter(Customer.company_id == emp.company_id).count()
    c = Customer(
        company_id=emp.company_id,
        code=f"M-{1001 + seq}",
        full_name=data.full_name,
        phone=data.phone,
        address=data.address,
    )
    db.add(c)
    db.flush()
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "create", "customer", c.id, after={"name": c.full_name})
    db.commit()
    db.refresh(c)
    return c


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    return c


class CustomerEdit(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    address: str | None = None


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def edit_customer(
    customer_id: uuid.UUID,
    data: CustomerEdit,
    emp: Employee = Depends(require("mijozlar.edit")),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    if data.full_name is not None:
        c.full_name = data.full_name
    if data.phone is not None:
        c.phone = data.phone
    if data.address is not None:
        c.address = data.address
    db.commit()
    db.refresh(c)
    return c


@router.delete("/customers/{customer_id}")
def delete_customer(
    customer_id: uuid.UUID,
    emp: Employee = Depends(require("mijozlar.edit")),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    if c.credit_balance and c.credit_balance > 0:
        raise HTTPException(400, "Qarzi bor mijozni o'chirib bo'lmaydi")
    from datetime import datetime, timezone
    c.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/customers/{customer_id}/detail")
def customer_detail(
    customer_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.models.sales import Sale, SaleItem, SalePayment

    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    sales = (
        db.query(Sale)
        .filter(Sale.customer_id == c.id, Sale.deleted_at.is_(None))
        .order_by(Sale.sold_at.desc())
        .limit(10)
        .all()
    )
    history = []
    for s in sales:
        pay = db.query(SalePayment.method_code).filter(SalePayment.sale_id == s.id).first()
        cnt = db.query(func.coalesce(func.sum(SaleItem.qty), 0)).filter(SaleItem.sale_id == s.id).scalar()
        history.append({
            "date": s.sold_at, "items": int(cnt or 0),
            "amount": float(s.total), "method": pay[0] if pay else "cash",
        })
    pays = (
        db.query(CustomerPayment)
        .filter(CustomerPayment.customer_id == c.id)
        .order_by(CustomerPayment.paid_at.desc())
        .limit(10)
        .all()
    )
    total_spent = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(Sale.customer_id == c.id).scalar())
    return {
        "id": str(c.id), "code": c.code, "full_name": c.full_name, "phone": c.phone,
        "credit_balance": float(c.credit_balance),
        "total_spent": total_spent,
        "visits": len(sales),
        "history": history,
        "payments": [{"date": p.paid_at, "amount": float(p.amount)} for p in pays],
    }


@router.post("/customers/{customer_id}/payments")
def pay_credit(
    customer_id: uuid.UUID,
    data: CreditPayment,
    emp: Employee = Depends(require("mijozlar.edit")),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    amt = Decimal(str(data.amount))
    if amt <= 0:
        raise HTTPException(400, "Summa noto'g'ri")
    now = datetime.now(timezone.utc)
    pay = CustomerPayment(
        customer_id=c.id, amount=amt, method=data.method, paid_at=now, employee_id=emp.id, created_at=now
    )
    db.add(pay)
    db.flush()
    c.credit_balance = max(Decimal("0"), Decimal(str(c.credit_balance)) - amt)
    db.add(
        CreditTransaction(
            customer_id=c.id,
            type=CreditTxnType.payment,
            amount=-amt,
            balance_after=c.credit_balance,
            payment_id=pay.id,
            employee_id=emp.id,
            created_at=now,
        )
    )
    db.commit()
    return {"customer_id": str(c.id), "credit_balance": float(c.credit_balance)}
