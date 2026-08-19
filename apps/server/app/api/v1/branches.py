"""Filiallar API — do'kon tarmog'i + tarif-limitli filial qo'shish.

Tarif limitlari:
  start  = 1 filial · start+ = 5 filial · business = cheksiz (999).
Tarif Setting(key="plan") da saqlanadi (default: start).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.reports import _store_tz
from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import SaleStatus
from app.models.org import Branch
from app.models.sales import Sale
from app.models.settings import Setting

router = APIRouter(tags=["branches"])

PLAN_LIMITS = {"start": 1, "start+": 5, "business": 999}


def _plan(db: Session, company_id):
    row = db.query(Setting).filter(Setting.company_id == company_id, Setting.key == "plan").first()
    val = (row.value if row else {}) or {}
    plan = val.get("plan", "start")
    return plan, PLAN_LIMITS.get(plan, 1)


class BranchIn(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None
    timezone: str | None = None


@router.get("/branches")
def list_branches(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    cid = emp.company_id
    plan, maxb = _plan(db, cid)
    rows = (
        db.query(Branch)
        .filter(Branch.company_id == cid, Branch.deleted_at.is_(None))
        .order_by(Branch.created_at).all()
    )
    LOCAL = _store_tz(db, cid)
    day0 = datetime.now(timezone.utc).astimezone(LOCAL).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    NOT_VOID = Sale.status != SaleStatus.voided
    out = []
    for b in rows:
        cashiers = db.query(func.count(func.distinct(Sale.cashier_id))).filter(
            Sale.company_id == cid, Sale.branch_id == b.id, NOT_VOID).scalar() or 0
        sales_today = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            Sale.company_id == cid, Sale.branch_id == b.id, NOT_VOID, Sale.sold_at >= day0).scalar())
        out.append({
            "id": str(b.id), "name": b.name, "address": b.address, "phone": b.phone,
            "cashiers": int(cashiers), "sales_today": sales_today, "is_active": b.is_active,
        })
    return {"branches": out, "plan": plan, "max_branches": maxb,
            "count": len(rows), "can_add": len(rows) < maxb}


@router.post("/branches")
def create_branch(data: BranchIn, emp: Employee = Depends(require("sozlamalar.edit")), db: Session = Depends(get_db)):
    cid = emp.company_id
    plan, maxb = _plan(db, cid)
    count = db.query(Branch).filter(Branch.company_id == cid, Branch.deleted_at.is_(None)).count()
    if count >= maxb:
        raise HTTPException(403, detail={"error": "tarif_limit", "plan": plan, "max_branches": maxb})
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(422, "Filial nomi kerak")
    now = datetime.now(timezone.utc)
    b = Branch(
        company_id=cid, code=f"F-{count + 1:03d}", name=name,
        address=(data.address or "").strip() or None, phone=(data.phone or "").strip() or None,
        timezone=(data.timezone or "Asia/Tashkent"), is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"id": str(b.id), "name": b.name}
