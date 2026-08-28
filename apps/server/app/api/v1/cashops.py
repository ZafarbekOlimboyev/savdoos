"""Egа uchun kassa kirim/chiqim (mobil) + filiallararo transfer.

Kassa operatsiyasi do'kondagi OCHIQ smenaga yoziladi (pul kassada turadi) —
ochiq smena bo'lmasa 400. Transfer: ombordan omborga, ledger transfer_out/in bilan.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.enums import CashMovementType, MovementType, ShiftStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.shifts import CashMovement, Shift

router = APIRouter(tags=["cashops"])


class CashOpIn(BaseModel):
    type: Literal["payin", "expense", "collection"] = "expense"
    amount: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    reason: str | None = Field(default=None, max_length=200)


@router.post("/cash/ops")
def cash_op(data: CashOpIn, emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Kassa kirim (payin) / xarajat (expense) / inkassatsiya (collection) — ochiq smenaga."""
    shift = (
        db.query(Shift)
        .join(Branch, Branch.id == Shift.branch_id)
        .filter(Branch.company_id == emp.company_id, Shift.status == ShiftStatus.open)
        .order_by(Shift.opened_at.desc())
        .first()
    )
    if not shift:
        raise HTTPException(400, "Ochiq smena yo'q — avval kassada smena oching")
    db.add(CashMovement(
        shift_id=shift.id, type=CashMovementType(data.type), amount=Decimal(str(data.amount)),
        reason=data.reason, employee_id=emp.id, created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    return {"ok": True, "shift_id": str(shift.id)}


@router.get("/cash/ops")
def cash_ops_today(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Bugungi kassa harakatlari (kompaniya bo'yicha, oxirgi 50). "Bugun" — do'kon MAHALLIY kuni."""
    from app.api.v1.reports import _store_tz
    LOCAL = _store_tz(db, emp.company_id)
    day0 = (datetime.now(timezone.utc).astimezone(LOCAL)
            .replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc))
    rows = (
        db.query(CashMovement, Employee.full_name)
        .join(Shift, Shift.id == CashMovement.shift_id)
        .join(Branch, Branch.id == Shift.branch_id)
        .outerjoin(Employee, Employee.id == CashMovement.employee_id)
        .filter(Branch.company_id == emp.company_id, CashMovement.created_at >= day0)
        .order_by(CashMovement.created_at.desc())
        .limit(50)
        .all()
    )
    return [{"type": m.type.value, "amount": float(m.amount), "reason": m.reason,
             "employee": who or "—", "at": m.created_at} for m, who in rows]


class TransferItem(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)


class TransferIn(BaseModel):
    from_branch_id: uuid.UUID
    to_branch_id: uuid.UUID
    items: list[TransferItem]
    client_uuid: uuid.UUID | None = None


@router.post("/inventory/transfer")
def transfer(data: TransferIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Filiallararo ko'chirish: from'dan kamayadi (transfer_out), to'ga qo'shiladi (transfer_in)."""
    if data.from_branch_id == data.to_branch_id:
        raise HTTPException(400, "Bir xil filial tanlandi")
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    if data.client_uuid:
        ex = db.query(StockMovement).filter(
            StockMovement.client_uuid == data.client_uuid,
            StockMovement.type == MovementType.transfer_out).first()
        if ex:
            return {"ok": True, "duplicate": True}
    src = db.get(Branch, data.from_branch_id)
    dst = db.get(Branch, data.to_branch_id)
    for b, nm in ((src, "from"), (dst, "to")):
        if not b or b.company_id != emp.company_id or b.deleted_at is not None:
            raise HTTPException(404, f"Filial topilmadi ({nm})")
    now = datetime.now(timezone.utc)
    moved = []
    for i in data.items:
        prod = db.get(Product, i.product_id)
        if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
        qty = Decimal(str(i.qty))
        inv_from = db.query(Inventory).filter(
            Inventory.product_id == prod.id, Inventory.branch_id == src.id).first()
        avail = Decimal(str(inv_from.qty)) if inv_from else Decimal("0")
        if qty > avail:
            raise HTTPException(400, f"Yetarli qoldiq yo'q: {prod.name} (qoldiq: {avail})")
        inv_from.qty = avail - qty
        inv_from.updated_at = now
        inv_to = db.query(Inventory).filter(
            Inventory.product_id == prod.id, Inventory.branch_id == dst.id).first()
        if inv_to is None:
            inv_to = Inventory(product_id=prod.id, branch_id=dst.id, qty=Decimal("0"), updated_at=now)
            db.add(inv_to)
            db.flush()
        inv_to.qty = Decimal(str(inv_to.qty)) + qty
        inv_to.updated_at = now
        if inv_to.qty > Decimal(str(inv_to.min_qty or 0)):
            inv_to.low_alerted = False  # restok — kam-qoldiq ogohlantirishi qayta tiklanadi
        db.add(StockMovement(product_id=prod.id, branch_id=src.id, type=MovementType.transfer_out,
                             qty=-qty, balance_after=inv_from.qty, ref_type="transfer",
                             employee_id=emp.id, client_uuid=data.client_uuid, created_at=now))
        db.add(StockMovement(product_id=prod.id, branch_id=dst.id, type=MovementType.transfer_in,
                             qty=qty, balance_after=inv_to.qty, ref_type="transfer",
                             employee_id=emp.id, created_at=now))
        moved.append({"product": prod.name, "qty": float(qty),
                      "from_left": float(inv_from.qty), "to_now": float(inv_to.qty)})
    db.commit()
    return {"ok": True, "from": src.name, "to": dst.name, "moved": moved}
