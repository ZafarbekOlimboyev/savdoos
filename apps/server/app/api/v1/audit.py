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
}
ACTION_LABEL = {"create": "qo'shdi", "update": "o'zgartirdi", "delete": "o'chirdi"}


@router.get("/audit")
def audit_list(
    entity: str | None = None,
    limit: int = 100,
    emp: Employee = Depends(require("hisobot.view")),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if entity:
        q = q.filter(AuditLog.entity == entity)
    rows = q.limit(min(limit, 300)).all()
    out = []
    for r in rows:
        actor = db.query(Employee.full_name).filter(Employee.id == r.actor_id).scalar() if r.actor_id else None
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
