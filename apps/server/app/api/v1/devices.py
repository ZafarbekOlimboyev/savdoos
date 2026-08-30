"""Push qurilma tokenlari — mobil ilova FCM tokenini ro'yxatga oladi."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee
from app.db.session import get_db
from app.models.auth import Employee
from app.models.devices import DeviceToken
from app.services import push

router = APIRouter(tags=["devices"])


class RegisterIn(BaseModel):
    token: str
    platform: str | None = None


@router.post("/devices/register")
def register(data: RegisterIn, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """FCM tokenni saqlaydi (bir token — bitta yozuv; do'kon/xodim yangilanadi)."""
    tok = (data.token or "").strip()
    if not tok:
        return {"ok": False}
    now = datetime.now(timezone.utc)
    row = db.query(DeviceToken).filter(DeviceToken.token == tok).first()
    if row:
        row.company_id = emp.company_id
        row.employee_id = emp.id
        row.platform = data.platform
        row.last_seen = now
    else:
        db.add(DeviceToken(company_id=emp.company_id, employee_id=emp.id,
                           token=tok, platform=data.platform, last_seen=now))
    db.commit()
    return {"ok": True}


@router.post("/devices/unregister")
def unregister(data: RegisterIn, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    # TENANT cheklovi: faqat O'Z do'koni tokenini o'chira oladi — aks holда begona kompaniya
    # push-tokenini o'chirib (token bilсa) uni push'дан mahrum qilиш mumkin edi (cross-tenant delete).
    db.query(DeviceToken).filter(
        DeviceToken.token == (data.token or "").strip(),
        DeviceToken.company_id == emp.company_id).delete()
    db.commit()
    return {"ok": True}


@router.post("/devices/test")
def test_push(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """Joriy xodim qurilmalariga sinov bildirishnomasi (push sozlanganini tekshirish)."""
    tokens = [t.token for t in db.query(DeviceToken).filter(
        DeviceToken.company_id == emp.company_id).all()]
    sent = push.send(tokens, "SavdoOS", "Bildirishnoma ishlayapti ✓", {"type": "test"})
    return {"ok": True, "tokens": len(tokens), "sent": sent, "enabled": push.settings.fcm_enabled}
