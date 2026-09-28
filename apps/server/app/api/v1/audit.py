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
    # Phase 5F — chek shabloni (kompaniya/filial) va logo yuklash
    "receipt_settings": "Chek shabloni", "receipt_logo": "Chek logosi",
    # 1C cutover — do'kon tarixidagi eng katta yozuv hodisasi. Yorliqsiz u jurnalda
    # xom slug bo'lib ko'rinardi.
    "catalog_1c_migration": "1C migratsiyasi", "catalog": "Katalog",
}
ACTION_LABEL = {"create": "qo'shdi", "update": "o'zgartirdi", "delete": "o'chirdi",
                "import": "ko'chirdi", "reset": "tozaladi"}


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
    #
    # ⚠️ INNER JOIN ATAYLAB. Uni LEFT JOIN ga aylantirib `actor_id IS NULL` qatorlarni ham
    # ko'rsatish — IJARACHILAR ARO SIZISH bo'lardi: bunday qatorlarni vendor konsoli yozadi
    # (`admin.py` — do'kon yaratish/o'chirish, parol tiklash, tarif) va ular BOSHQA
    # kompaniyalarning ma'lumotini tashiydi. `audit_log` da `company_id` yo'q, ya'ni ularni
    # qaysi ijarachiga tegishli ekanini isbotlaydigan dalil ham yo'q.
    #
    # 1C cutover endi bu yerda KO'RINADI, chunki `apply` aktyorsiz umuman ishlamaydi
    # (`migrator_1c/actor.py`): aktyor — maqsad do'konning faol, ruxsatli xodimi, demak
    # quyidagi JOIN unga mos keladi. Ilgari u `actor_id=NULL` bilan yozilardi va abadiy
    # ko'rinmasdi — buni JOIN emas, NULL aktyor yashirardi.
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
            # Cutover qatorida `entity_id` — import job identifikatori (`apply.py`), ya'ni
            # `GET /catalog/v2/jobs` ga bog'lanish kaliti. Usiz jurnal qatori boshi berk ko'cha.
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "at": r.created_at,
        })
    return out
