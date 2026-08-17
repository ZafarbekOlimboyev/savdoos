"""Offline kassa sinxronizatsiyasi — sodda push/pull.

push: kassada offline yaratilgan sotuvlar (client_uuid bilan) → idempotent.
pull: server tomonidagi o'zgargan katalog/mijoz/sozlama (delta).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.customers import Customer
from app.schemas.sales import SaleCreate
from app.services.sales import create_sale

router = APIRouter(prefix="/sync", tags=["sync"])


class PushBody(BaseModel):
    device_uuid: str | None = None
    sales: list[SaleCreate] = []


@router.post("/push")
def push(body: PushBody, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    results = []
    for s in body.sales:
        sale = create_sale(db, emp, s)          # client_uuid orqali idempotent
        results.append({"client_uuid": str(s.client_uuid), "receipt_no": sale.receipt_no})
    return {"accepted": len(results), "results": results}


@router.get("/pull")
def pull(
    since: datetime | None = None,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    since = since or datetime(1970, 1, 1, tzinfo=timezone.utc)
    products = (
        db.query(Product)
        .filter(Product.company_id == emp.company_id, Product.updated_at > since)
        .count()
    )
    customers = (
        db.query(Customer)
        .filter(Customer.company_id == emp.company_id, Customer.updated_at > since)
        .count()
    )
    return {
        "server_time": datetime.now(timezone.utc),
        "changed": {"products": products, "customers": customers},
    }
