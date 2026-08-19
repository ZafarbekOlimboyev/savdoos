import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.scales import Scale
from app.services.scales.base import Conn, ScaleProduct
from app.services.scales.registry import brands as supported_brands
from app.services.scales.registry import driver_for

router = APIRouter(tags=["scales"])


class ScaleOut(BaseModel):
    id: str
    name: str
    brand: str | None = None
    model: str | None = None
    connection_type: str
    host: str | None = None
    port: int | None = None
    com_port: str | None = None
    baud: int | None = None
    status: str
    synced_count: int
    last_sync_at: datetime | None = None
    is_active: bool


class ScaleIn(BaseModel):
    name: str
    brand: str | None = None
    model: str | None = None
    connection_type: str = "lan"      # lan | usb
    host: str | None = None
    port: int | None = None
    com_port: str | None = None
    baud: int | None = None
    data_bits: int | None = None
    parity: str | None = None
    stop_bits: int | None = None


class ScaleUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    com_port: str | None = None
    baud: int | None = None
    status: str | None = None
    is_active: bool | None = None


class TestIn(BaseModel):
    connection_type: str = "lan"
    host: str | None = None
    port: int | None = None
    com_port: str | None = None
    baud: int | None = None
    brand: str | None = None            # "auto" yoki tanlangan
    model: str | None = None


def _out(s: Scale) -> ScaleOut:
    return ScaleOut(
        id=str(s.id), name=s.name, brand=s.brand, model=s.model,
        connection_type=s.connection_type, host=s.host, port=s.port,
        com_port=s.com_port, baud=s.baud, status=s.status,
        synced_count=s.synced_count, last_sync_at=s.last_sync_at, is_active=s.is_active,
    )


@router.get("/scales/brands")
def scale_brands(emp: Employee = Depends(get_current_employee)):
    return {"brands": supported_brands()}


@router.get("/scales/ports")
def scale_ports(emp: Employee = Depends(get_current_employee)):
    # Real serverда pyserial orqali aniqlanadi; bu yerda demo ro'yxati.
    return {"ports": [
        {"port": "COM3", "label": "COM3 - CAS Scale"},
        {"port": "COM5", "label": "COM5 - USB Serial Device"},
    ]}


@router.post("/scales/test")
def test_connection(data: TestIn, emp: Employee = Depends(require("sozlamalar.edit"))):
    want_brand = None if (not data.brand or data.brand == "auto") else data.brand
    conn = Conn(connection_type=data.connection_type, host=data.host, port=data.port,
                com_port=data.com_port, baud=data.baud)
    res = driver_for(want_brand).probe(conn, want_brand, data.model)
    return {
        "ok": res.ok, "brand": res.brand, "model": res.model,
        "supported": res.supported, "message": res.message,
    }


@router.get("/scales", response_model=list[ScaleOut])
def list_scales(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    rows = db.query(Scale).filter(Scale.company_id == emp.company_id).order_by(Scale.created_at).all()
    return [_out(s) for s in rows]


@router.post("/scales", response_model=ScaleOut)
def create_scale(data: ScaleIn, emp: Employee = Depends(require("sozlamalar.edit")), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    brand = None if (not data.brand or data.brand == "auto") else data.brand
    s = Scale(
        company_id=emp.company_id, name=data.name.strip() or "Tarozi",
        brand=brand, model=data.model, driver=(brand or "generic"),
        connection_type=data.connection_type, host=data.host, port=data.port,
        com_port=data.com_port, baud=data.baud, data_bits=data.data_bits,
        parity=data.parity, stop_bits=data.stop_bits,
        status="connected", synced_count=0, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.patch("/scales/{scale_id}", response_model=ScaleOut)
def update_scale(scale_id: uuid.UUID, data: ScaleUpdate,
                 emp: Employee = Depends(require("sozlamalar.edit")), db: Session = Depends(get_db)):
    s = db.get(Scale, scale_id)
    if not s or s.company_id != emp.company_id:
        raise HTTPException(404, "Tarozi topilmadi")
    if data.status is not None and data.status not in {"connected", "checking", "disconnected"}:
        raise HTTPException(400, "Noto'g'ri holat")
    for f in ("name", "host", "port", "com_port", "baud", "status", "is_active"):
        v = getattr(data, f)
        if v is not None:
            setattr(s, f, v)
    s.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.delete("/scales/{scale_id}")
def delete_scale(scale_id: uuid.UUID, emp: Employee = Depends(require("sozlamalar.edit")), db: Session = Depends(get_db)):
    s = db.get(Scale, scale_id)
    if not s or s.company_id != emp.company_id:
        raise HTTPException(404, "Tarozi topilmadi")
    db.delete(s)
    db.commit()
    return {"ok": True}


def _weighted_products(db: Session, company_id) -> list[Product]:
    return (
        db.query(Product)
        .filter(Product.company_id == company_id, Product.deleted_at.is_(None),
                Product.is_weighted.is_(True), Product.scale_sync.is_(True))
        .order_by(Product.name)
        .all()
    )


@router.get("/scales/sync-preview")
def sync_preview(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    items = [
        {"plu": p.plu_code or "—", "name": p.name, "price_per_kg": float(p.base_sell_price)}
        for p in _weighted_products(db, emp.company_id)
    ]
    return {"count": len(items), "items": items}


@router.post("/scales/{scale_id}/sync")
def sync_scale(scale_id: uuid.UUID, emp: Employee = Depends(require("sozlamalar.edit")), db: Session = Depends(get_db)):
    s = db.get(Scale, scale_id)
    if not s or s.company_id != emp.company_id:
        raise HTTPException(404, "Tarozi topilmadi")
    prods = _weighted_products(db, emp.company_id)
    payload = [ScaleProduct(plu=p.plu_code or "", name=p.name, price_per_kg=float(p.base_sell_price)) for p in prods]
    conn = Conn(connection_type=s.connection_type, host=s.host, port=s.port, com_port=s.com_port, baud=s.baud)
    sent = driver_for(s.brand).sync_products(conn, payload)
    now = datetime.now(timezone.utc)
    s.synced_count = sent
    s.last_sync_at = now
    s.status = "connected"
    s.updated_at = now
    db.commit()
    return {"synced": sent, "total": len(payload)}
