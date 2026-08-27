import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import effective_permissions, get_current_employee, require
from app.core.security import hash_password, norm_phone
from app.db.session import get_db
from app.models.auth import Employee, EmployeePermission, Permission, Role
from app.services.audit import log as audit_log

router = APIRouter(tags=["employees"])


def _phone_taken(db: Session, phone: str, exclude_id=None) -> bool:
    """Parolli login uchun telefon global noyob bo'lishi kerak (ux_employees_phone_pw)."""
    q = db.query(Employee).filter(
        Employee.phone == phone,
        Employee.password_hash.isnot(None),
        Employee.deleted_at.is_(None),
    )
    if exclude_id is not None:
        q = q.filter(Employee.id != exclude_id)
    return db.query(q.exists()).scalar()


class EmployeeIn(BaseModel):
    full_name: str
    phone: str | None = None
    role_code: str = "kassir"
    password: str | None = None
    pin: str | None = None  # eskirgan (mobil/backward) — desktop endi parol ishlatadi


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
    # Imtiyoz himoyasi: administrator akkauntini FAQAT administrator yarata oladi
    # (aks holda "xodimlar.edit" ruxsatли menejer o'zini admin qilib olardi).
    if role.code == "administrator" and emp.role.code != "administrator":
        raise HTTPException(403, "Administrator akkauntini faqat administrator yarata oladi")
    phone = norm_phone(data.phone)
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Parol kamida 6 belgi bo'lishi kerak")
        if not phone:
            raise HTTPException(400, "Parolli xodim uchun telefon (login) kerak")
        if _phone_taken(db, phone):
            raise HTTPException(409, "Bu telefon allaqachon band")
    e = Employee(
        company_id=emp.company_id,
        full_name=data.full_name,
        phone=phone or None,
        role_id=role.id,
        password_hash=hash_password(data.password) if data.password else None,
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
    password: str | None = None
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
    # ── Imtiyoz himoyasi (privilege escalation'га qarshi) ──
    # 1) Mavjud administrator akkauntini (parol/PIN/status/rol) FAQAT administrator tahrirlaydi.
    #    Aks holda "xodimlar.edit"ли menejer adminning parolini almashtirib akkauntни egallardi.
    # 2) Administrator rolini biriktirish ham faqat administrator qo'lidan keladi.
    _is_admin = emp.role.code == "administrator"
    if e.role.code == "administrator" and not _is_admin:
        raise HTTPException(403, "Administrator akkauntini faqat administrator tahrirlaydi")
    if data.role_code == "administrator" and not _is_admin:
        raise HTTPException(403, "Administrator rolini faqat administrator biriktiradi")
    if data.full_name is not None:
        e.full_name = data.full_name
    if data.phone is not None:
        e.phone = norm_phone(data.phone) or None
    if data.role_code is not None:
        role = db.query(Role).filter(Role.code == data.role_code).first()
        if role:
            e.role_id = role.id
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Parol kamida 6 belgi bo'lishi kerak")
        if not e.phone:
            raise HTTPException(400, "Parolli xodim uchun telefon (login) kerak")
    # Telefon global noyob bo'lishi kerak — parolli akkaunt (mavjud yoki shu patchda o'rnatilayotgan)
    # uchun. Faqat telefon o'zgartirilsa ham tekshiriladi (aks holda DB indeks 500 berardi).
    if e.phone and (e.password_hash or data.password) and _phone_taken(db, e.phone, exclude_id=e.id):
        raise HTTPException(409, "Bu telefon allaqachon band")
    if data.password:
        e.password_hash = hash_password(data.password)
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
    # Imtiyoz himoyasi: administratorni faqat administrator o'chira oladi (lockout/DoS'га qarshi).
    if e.role.code == "administrator" and emp.role.code != "administrator":
        raise HTTPException(403, "Administrator akkauntini faqat administrator o'chira oladi")
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

    from app.models.enums import SaleStatus
    from app.models.sales import Sale

    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    _valid = Sale.status != SaleStatus.voided
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_sales = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.cashier_id == e.id, Sale.sold_at >= month_start, _valid).scalar())
    tx = db.query(Sale).filter(Sale.cashier_id == e.id, Sale.sold_at >= month_start, _valid).count()
    # So'nggi 6 oylik HAQIQIY savdo (kassir bo'yicha), Python'da oy kesimida guruhlanadi
    # (SQLite/Postgres'да bir xil ishlashi uchun sana-funksiyasiz).
    y, m = now.year, now.month
    buckets: list[tuple[int, int]] = []
    for _i in range(6):
        buckets.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    buckets.reverse()  # eng eski -> eng yangi
    six_start = datetime(buckets[0][0], buckets[0][1], 1, tzinfo=timezone.utc)
    agg: dict[tuple[int, int], float] = {}
    for sold_at, total in db.query(Sale.sold_at, Sale.total).filter(
            Sale.cashier_id == e.id, Sale.sold_at >= six_start, _valid).all():
        if sold_at is None:
            continue
        k = (sold_at.year, sold_at.month)
        agg[k] = agg.get(k, 0.0) + float(total or 0)
    MON = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
    chart = [{"label": MON[mo - 1], "sales": round(agg.get((yr, mo), 0.0), 2)} for yr, mo in buckets]
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
    # Ruxsatlarni qo'lda o'zgartirish — faqat administrator (aks holda o'ziga istalgan
    # ruxsatni, jumladan xodimlar.edit'ni berib imtiyoz oshirishi mumkin edi).
    if emp.role.code != "administrator":
        raise HTTPException(403, "Ruxsatlarni faqat administrator o'zgartira oladi")
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
