"""Offline kassa sinxronizatsiyasi — sodda push/pull.

push: kassada offline yaratilgan sotuvlar (client_uuid bilan) → idempotent.
pull: server tomonidagi o'zgargan katalog/mijoz/sozlama (delta).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
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
    device_uuid: str | None = Field(default=None, max_length=100)
    sales: list[dict] = Field(default=[], max_length=1000)   # bir so'rovда ko'pi 1000 chek


def _clamp_sold_at(dt: datetime | None) -> datetime | None:
    """Offline savdo vaqtini oqilona oynага cheklaymiz — kelajак/absurd o'tмиш reklaмаsидан
    hisobот buzилмаsин. Kelajакда >5 daqiqa yoki 60 kundан eski → ishonmaymiz (hozir ishlatilади)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if dt > now + timedelta(minutes=5) or dt < now - timedelta(days=60):
        return None
    return dt


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
            # Offline savdo HAQIQIY vaqtида yozилади (flush vaqtида emas) — kunlik hisobот to'g'ri.
            # honor_price_snapshot (QA PC-001): offline chek KASSADA olingan narxda yoziladi
            sale = create_sale(db, emp, s, at=_clamp_sold_at(s.sold_at),
                               honor_price_snapshot=True)  # client_uuid orqali idempotent
            accepted += 1
            results.append({"client_uuid": str(s.client_uuid) if s.client_uuid else None, "ok": True, "receipt_no": sale.receipt_no})
        except HTTPException as e:               # biznes xatosi ham izolyatsiya qilinadi
            db.rollback()
            # QA OFF-1 (CRITICAL): TRANSIENT (409 'Kassa band' receipt_no retry-exhaustion / 5xx) xato
            # retry:true bilan belgilanadi — client outbox'da SAQLAYDI (keyingi flush qayta uradi). PERMANENT
            # (400 validatsiya/biznes) — ok:false, dead-letter. Ilgari ikkovi ok:false edi → transient xato
            # pul-olingan offline savdoni retry navbatidan chiqarardi (LOST SALE, boss 'no lost transactions').
            _transient = e.status_code >= 500 or e.status_code == 409
            results.append({"client_uuid": str(s.client_uuid) if s.client_uuid else None,
                            "ok": False, "retry": _transient, "error": e.detail})
        except OperationalError:                 # QA OFF-1: deadlock/lock-timeout/ulanish uzilishi — TRANSIENT
            db.rollback()
            results.append({"client_uuid": str(s.client_uuid) if s.client_uuid else None,
                            "ok": False, "retry": True, "error": "transient"})
        except Exception:                        # noqa: BLE001 — DataError (Numeric overflow, PERMANENT) va sh.k.
            # BITTA yomon chek (masalan qty*narx Numeric(14,2)дан oshган) BUTUN navbatни to'xtатмасин
            # va sessiyaни iflos qoldirмасин — rollback + shu yozувни rad, qolganи davom etsin.
            db.rollback()
            results.append({"client_uuid": str(s.client_uuid) if s.client_uuid else None, "ok": False, "error": "server"})
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
