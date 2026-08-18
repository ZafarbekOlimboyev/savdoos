import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import CashMovementType, ShiftStatus
from app.models.org import Branch
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift

router = APIRouter(tags=["shifts"])


class OpenShift(BaseModel):
    opening_cash: float = 0


class CloseShift(BaseModel):
    counted_cash: float = 0


class CashMove(BaseModel):
    type: str = "payin"          # payin | payout | expense
    amount: float = 0
    reason: str | None = None


@router.post("/shifts/{shift_id}/cash")
def add_cash_movement(
    shift_id: uuid.UUID,
    data: CashMove,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    s = db.get(Shift, shift_id)
    if not s or s.status != ShiftStatus.open:
        raise HTTPException(400, "Ochiq smena topilmadi")
    if data.type not in {"payin", "payout", "expense", "collection"}:
        raise HTTPException(400, "Noto'g'ri tur")
    mtype = CashMovementType(data.type)
    db.add(CashMovement(
        shift_id=s.id, type=mtype, amount=Decimal(str(data.amount)),
        reason=data.reason, employee_id=emp.id, created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    return {"ok": True}


@router.get("/shifts/{shift_id}/cash")
def list_cash_movements(
    shift_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    rows = db.query(CashMovement).filter(CashMovement.shift_id == shift_id).order_by(CashMovement.created_at.desc()).all()
    return [{"type": m.type.value, "amount": float(m.amount), "reason": m.reason, "at": m.created_at} for m in rows]


CASH_LABEL = {"payin": "Naqd kiritish", "payout": "Naqd topshirish", "expense": "Xarajat", "collection": "Inkassa", "opening": "Smena ochildi"}


@router.get("/shifts/{shift_id}/summary")
def shift_summary(
    shift_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    s = db.get(Shift, shift_id)
    if not s:
        raise HTTPException(404, "Smena topilmadi")
    rows = (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.shift_id == s.id)
        .group_by(SalePayment.method_code)
        .all()
    )
    by_method = {m: float(a) for m, a in rows}
    total_sales = sum(by_method.values())
    receipts = db.query(Sale).filter(Sale.shift_id == s.id).count()
    naqd = by_method.get("cash", 0.0)

    payin = payout = 0.0
    ops = []
    for m in db.query(CashMovement).filter(CashMovement.shift_id == s.id).order_by(CashMovement.created_at).all():
        amt = float(m.amount)
        inc = m.type == CashMovementType.payin
        if inc:
            payin += amt
        else:
            payout += amt
        ops.append({"title": CASH_LABEL.get(m.type.value, m.type.value) + (f" · {m.reason}" if m.reason else ""),
                    "at": m.created_at, "amount": amt, "in": inc})

    expected = float(s.opening_cash) + naqd + payin - payout
    return {
        "opening": float(s.opening_cash),
        "total_sales": total_sales,
        "receipts": receipts,
        "by_method": by_method,
        "naqd_sales": naqd,
        "payin": payin,
        "payout": payout,
        "expected": expected,
        "opened_at": s.opened_at,
        "status": s.status.value,
        "ops": ops,
    }


@router.get("/shifts/current")
def current_shift(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    s = (
        db.query(Shift)
        .filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open)
        .first()
    )
    if not s:
        return None
    return {"id": str(s.id), "opened_at": s.opened_at, "opening_cash": float(s.opening_cash)}


@router.post("/shifts/open")
def open_shift(data: OpenShift, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    if db.query(Shift).filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open).first():
        raise HTTPException(400, "Ochiq smena allaqachon mavjud")
    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    s = Shift(
        branch_id=branch.id,
        cashier_id=emp.id,
        opened_at=datetime.now(timezone.utc),
        opening_cash=data.opening_cash,
        status=ShiftStatus.open,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": str(s.id), "opened_at": s.opened_at}


@router.post("/shifts/{shift_id}/close")
def close_shift(
    shift_id: uuid.UUID,
    data: CloseShift,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    s = db.get(Shift, shift_id)
    if not s:
        raise HTTPException(404, "Smena topilmadi")
    if s.status != ShiftStatus.open:
        raise HTTPException(400, "Smena allaqachon yopilgan")
    # tizim kutgan naqd = ochilish + smenadagi naqd savdolar
    cash = (
        db.query(SalePayment)
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.shift_id == s.id, SalePayment.method_code == "cash")
        .all()
    )
    expected = Decimal(str(s.opening_cash)) + sum(Decimal(str(p.amount)) for p in cash)
    for m in db.query(CashMovement).filter(CashMovement.shift_id == s.id).all():
        if m.type == CashMovementType.payin:
            expected += Decimal(str(m.amount))
        elif m.type in (CashMovementType.payout, CashMovementType.expense, CashMovementType.collection):
            expected -= Decimal(str(m.amount))
    s.counted_cash = Decimal(str(data.counted_cash))
    s.expected_cash = expected
    s.difference = s.counted_cash - expected
    s.closed_at = datetime.now(timezone.utc)
    s.status = ShiftStatus.closed
    db.commit()
    return {
        "id": str(s.id),
        "expected_cash": float(expected),
        "counted_cash": float(s.counted_cash),
        "difference": float(s.difference),
    }
