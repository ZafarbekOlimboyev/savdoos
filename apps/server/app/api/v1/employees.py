import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import effective_permissions, get_current_employee, require
from app.core.security import hash_password
from app.db.session import get_db
from app.models.auth import Employee, EmployeePermission, Permission, Role
from app.services.audit import log as audit_log

router = APIRouter(tags=["employees"])


class EmployeeIn(BaseModel):
    full_name: str
    phone: str | None = None
    role_code: str = "kassir"
    pin: str | None = None


@router.get("/employees")
def list_employees(emp: Employee = Depends(require("xodimlar.view")), db: Session = Depends(get_db)):
    rows = (
        db.query(Employee)
        .filter(Employee.company_id == emp.company_id, Employee.deleted_at.is_(None))
        .all()
    )
    return [
        {
            "id": str(e.id),
            "full_name": e.full_name,
            "phone": e.phone,
            "role": e.role.code,
            "role_name": e.role.name,
            "status": e.status.value,
        }
        for e in rows
    ]


@router.post("/employees")
def create_employee(
    data: EmployeeIn,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.code == data.role_code).first()
    if not role:
        raise HTTPException(400, "Rol topilmadi")
    e = Employee(
        company_id=emp.company_id,
        full_name=data.full_name,
        phone=data.phone,
        role_id=role.id,
        pin_hash=hash_password(data.pin) if data.pin else None,
    )
    db.add(e)
    db.flush()
    audit_log(db, emp.id, "create", "employee", e.id, after={"name": e.full_name})
    db.commit()
    db.refresh(e)
    return {"id": str(e.id), "full_name": e.full_name}


class EmployeeEdit(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    role_code: str | None = None
    pin: str | None = None
    status: str | None = None


@router.patch("/employees/{employee_id}")
def edit_employee(
    employee_id: uuid.UUID,
    data: EmployeeEdit,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    from app.models.enums import EmployeeStatus

    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    if data.full_name is not None:
        e.full_name = data.full_name
    if data.phone is not None:
        e.phone = data.phone
    if data.role_code is not None:
        role = db.query(Role).filter(Role.code == data.role_code).first()
        if role:
            e.role_id = role.id
    if data.pin:
        e.pin_hash = hash_password(data.pin)
    if data.status is not None:
        try:
            e.status = EmployeeStatus(data.status)
        except ValueError:
            raise HTTPException(400, "Status noto'g'ri")
    db.commit()
    return {"ok": True}


@router.delete("/employees/{employee_id}")
def delete_employee(
    employee_id: uuid.UUID,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    if e.id == emp.id:
        raise HTTPException(400, "O'zingizni o'chira olmaysiz")
    from datetime import datetime, timezone
    e.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/employees/{employee_id}/stats")
def employee_stats(
    employee_id: uuid.UUID,
    emp: Employee = Depends(require("xodimlar.view")),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app.models.sales import Sale

    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_sales = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.cashier_id == e.id, Sale.sold_at >= month_start).scalar())
    tx = db.query(Sale).filter(Sale.cashier_id == e.id, Sale.sold_at >= month_start).count()
    # 6 oylik ish soati (deterministik namuna)
    months = ["Mar", "Apr", "May", "Iyn", "Iyl", "Avg"]
    seed = sum(ord(ch) for ch in e.full_name)
    chart = [{"label": m, "hours": 160 + (seed + i * 7) % 40} for i, m in enumerate(months)]
    return {"month_sales": month_sales, "tx": tx, "chart": chart}


@router.get("/permissions")
def list_permissions(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    rows = db.query(Permission).order_by(Permission.module, Permission.code).all()
    return [{"code": p.code, "module": p.module} for p in rows]


@router.get("/employees/{employee_id}")
def employee_detail(
    employee_id: uuid.UUID,
    emp: Employee = Depends(require("xodimlar.view")),
    db: Session = Depends(get_db),
):
    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    perms = effective_permissions(e, db)
    return {
        "id": str(e.id), "full_name": e.full_name, "phone": e.phone,
        "role": e.role.code, "role_name": e.role.name, "status": e.status.value,
        "permissions": sorted(perms),
    }


class PermPatch(BaseModel):
    overrides: dict[str, bool]   # {"kassa.sell": true, "hisobot.view": false}


@router.patch("/employees/{employee_id}/permissions")
def set_permissions(
    employee_id: uuid.UUID,
    data: PermPatch,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    code_to_id = {p.code: p.id for p in db.query(Permission).all()}
    role_codes = {p.code for p in e.role.permissions}
    for code, allowed in data.overrides.items():
        pid = code_to_id.get(code)
        if not pid:
            continue
        row = db.query(EmployeePermission).filter_by(employee_id=e.id, permission_id=pid).first()
        # Agar override rol standartiga teng bo'lsa — override o'chiriladi (toza holat)
        if allowed == (code in role_codes):
            if row:
                db.delete(row)
        elif row:
            row.allowed = allowed
        else:
            db.add(EmployeePermission(employee_id=e.id, permission_id=pid, allowed=allowed))
    db.commit()
    return {"ok": True, "permissions": sorted(effective_permissions(e, db))}
