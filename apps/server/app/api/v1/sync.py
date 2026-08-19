"""Offline kassa sinxronizatsiyasi — sodda push/pull.

push: kassada offline yaratilgan sotuvlar (client_uuid bilan) → idempotent.
pull: server tomonidagi o'zgargan katalog/mijoz/sozlama (delta).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.customers import Customer
from app.schemas.sales import SaleCreate
from app.services.sales import create_sale

router = APIRouter(prefix="/sync", tags=["sync"])


class PushBody(BaseModel):
    device_uuid: str | None = None
    sales: list[dict] = []


@router.post("/push")
def push(body: PushBody, emp: Employee = Depends(require("kassa.sell")), db: Session = Depends(get_db)):
    from pydantic import ValidationError
    results = []
    accepted = 0
    for raw in body.sales:
        cu = raw.get("client_uuid") if isinstance(raw, dict) else None
        try:
            s = SaleCreate(**raw)                # sxema xatosi ham butun navbatni to'xtatmaydi
        except ValidationError:
            results.append({"client_uuid": cu, "ok": False, "error": "validation"})
            continue
        try:
            sale = create_sale(db, emp, s)      # client_uuid orqali idempotent
            accepted += 1
            results.append({"client_uuid": str(s.client_uuid) if s.client_uuid else None, "ok": True, "receipt_no": sale.receipt_no})
        except HTTPException as e:               # biznes xatosi ham izolyatsiya qilinadi
            db.rollback()
            results.append({"client_uuid": str(s.client_uuid) if s.client_uuid else None, "ok": False, "error": e.detail})
    return {"accepted": accepted, "failed": len(results) - accepted, "results": results}


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
