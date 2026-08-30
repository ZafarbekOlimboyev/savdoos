from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.settings import Setting

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
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
    # FAQAT-VENDOR kalitlар — do'kon O'ZI o'zgartira olmaydi:
    #  - 'plan': tarif (mijoz o'zini "business"ga ko'tarmasin);
    #  - 'suspended': do'konни to'xtatish/tiklash — vendor nazoratида (aks holда to'xtатилган
    #    do'kon admini o'zини qayta yoqиб, yoki do'konни o'zи lockout qilиб bloklardi).
    if data.key in ("plan", "suspended"):
        raise HTTPException(403, "Bu sozlamani o'zgartirib bo'lmaydi — provayder bilan bog'laning")
    import json as _json
    if len(_json.dumps(data.value)) > 64_000:  # ulkan sozlama payload'ini to'saymiz
        raise HTTPException(400, "Sozlama qiymati juda katta")
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
