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

from app.api.v1.reports import _TZ_OFFSETS, _store_tz
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
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)  # filialга bog'langan xodим boshqa filial tushumini ko'rmasin
    out = []
    for b in rows:
        if _vb is not None and b.id not in _vb:
            # Filial ro'yxatда qoladi (tanlov/nom uchun), lekin tushum/kassir raqamlari yashiriladi.
            out.append({
                "id": str(b.id), "name": b.name, "address": b.address, "phone": b.phone,
                "cashiers": 0, "sales_today": 0.0, "is_active": b.is_active,
            })
            continue
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
    from app.core.security import norm_phone
    from app.core.validate import require_phone
    phone = norm_phone(data.phone) or None
    require_phone(phone or "")  # noto'g'ri format -> 400
    tz = (data.timezone or "Asia/Tashkent").strip()
    if tz not in _TZ_OFFSETS:  # noma'lum vaqt mintaqasi jimgina Toshkentga tushmasin
        raise HTTPException(400, "Noto'g'ri vaqt mintaqasi")
    now = datetime.now(timezone.utc)
    b = Branch(
        company_id=cid, code=f"F-{count + 1:03d}", name=name[:200],
        address=((data.address or "").strip() or None), phone=phone,
        timezone=tz, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"id": str(b.id), "name": b.name}
