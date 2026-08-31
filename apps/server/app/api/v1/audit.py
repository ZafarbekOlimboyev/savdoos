from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.sync import AuditLog

router = APIRouter(tags=["audit"])

ENTITY_LABEL = {
    "product": "Mahsulot", "category": "Kategoriya", "employee": "Xodim",
    "customer": "Mijoz", "supplier": "Beruvchi", "setting": "Sozlama",
    "branch": "Filial", "company": "Do'kon",
}
ACTION_LABEL = {"create": "qo'shdi", "update": "o'zgartirdi", "delete": "o'chirdi"}


@router.get("/audit")
def audit_list(
    entity: str | None = None,
    limit: int = 100,
    emp: Employee = Depends(require("hisobot.view")),
    db: Session = Depends(get_db),
):
    # TENANT IZOLYATSIYA: AuditLog'da company_id yo'q — actor (xodim) kompaniyasi bo'yicha
    # cheklaymiz. Xodim faqat o'z kompaniyasi obyektlarini o'zgartira oladi, shuning uchun
    # actor.company_id == emp.company_id qatorlar aynan shu kompaniyaniki (boshqa tenant sizmaydi).
    q = (
        db.query(AuditLog, Employee.full_name)
        .join(Employee, Employee.id == AuditLog.actor_id)
        .filter(Employee.company_id == emp.company_id)
        .order_by(AuditLog.created_at.desc())
    )
    if entity:
        q = q.filter(AuditLog.entity == entity)
    rows = q.limit(min(max(limit, 1), 300)).all()
    out = []
    for r, actor in rows:
        payload = r.after or r.before or {}
        name = payload.get("name") if isinstance(payload, dict) else None
        out.append({
            "actor": actor or "—",
            "action": r.action,
            "action_label": ACTION_LABEL.get(r.action, r.action),
            "entity": r.entity,
            "entity_label": ENTITY_LABEL.get(r.entity, r.entity),
            "name": name,
            "at": r.created_at,
        })
    return out
