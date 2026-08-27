from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.settings import Setting

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    key: str
    value: dict


@router.get("/settings")
def get_settings(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    rows = db.query(Setting).filter(Setting.company_id == emp.company_id).all()
    return {r.key: r.value for r in rows}


@router.put("/settings")
def put_setting(
    data: SettingsIn,
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    # Tarif (plan) — do'kon O'ZI o'zgartira olmaydi. Faqat vendor (admin portal)
    # PATCH /admin/companies/{id}/plan orqali. Mijoz o'zini "business"ga ko'tarib olmasin.
    if data.key == "plan":
        raise HTTPException(403, "Tarifni o'zgartirib bo'lmaydi — provayder bilan bog'laning")
    row = (
        db.query(Setting)
        .filter(Setting.company_id == emp.company_id, Setting.branch_id.is_(None), Setting.key == data.key)
        .first()
    )
    if row:
        row.value = data.value
        row.row_version += 1
    else:
        row = Setting(company_id=emp.company_id, key=data.key, value=data.value)
        db.add(row)
    db.commit()
    return {data.key: data.value}
