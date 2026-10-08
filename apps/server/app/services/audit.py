"""Audit jurnali — kim nima yaratdi/o'zgartirdi/o'chirdi.

Har muhim mutatsiyada chaqiriladi: log(db, actor_id, "create"|"update"|"delete", entity, id, before, after).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.sync import AuditLog


def log(
    db: Session,
    actor_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    *,
    at: datetime | None = None,
) -> None:
    """`at` — TARIXIY payt (H3a). Berilmasa HOZIR — xulq bayt-bayt AVVALGIDEK.

    ⚠️  NEGA KERAK: tarixiy hujjat audit izi BUGUNGI payt bilan yozilsa, audit
        jurnali hujjatning O'ZI bilan ZIDDIYATGA tushardi — «kim qachon nima
        qildi» savoliga ikki xil javob chiqardi va replay'ni jonli amaldan
        ajratib bo'lmasdi.
    """
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before=before,
            after=after,
            created_at=(at if at is not None else datetime.now(timezone.utc)),
        )
    )
