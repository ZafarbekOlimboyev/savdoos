# -*- coding: utf-8 -*-
"""Cash migration CUTOVER (T0) boundary — runtime enforcement helper.

DYNAMIC TILL model: T0'dan OLDIN legacy tarix fizik-TILL identity'siz bo'lishi mumkin (till_id NULL —
HISTORY_UNKNOWN). T0'dan KEYIN esa har YANGI naqd faoliyat AYNAN ACTIVE TILL talab qiladi (smena, naqd
savdo/qaytarish, payin/payout/expense/collection). Bu modul faqat "T0'ga yetdikmi?" degan savolga javob
beradi; enforcement API/servis qatlamida (open_shift, create_sale, ...).

T0 manbai: company Setting(key='cash').value['cutover_at'] (ISO8601). Belgilanmagan -> cutover yo'q
(eski guarded xatti-harakat davom etadi — backward-compat). Faqat cash_enabled (Postgres + cash schema)
muhitда ma'noga ega; SQLite/offline kassa cash schema'siz -> chaqiruvchi cash_enabled bilan gate qiladi.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def cutover_at(db: Session, company_id) -> datetime | None:
    """Company'ning cash T0 (cutover) vaqti yoki None (belgilanmagan). Setting(key='cash').cutover_at."""
    from app.models.settings import Setting
    row = db.query(Setting).filter(Setting.company_id == company_id, Setting.key == "cash",
                                   Setting.branch_id.is_(None)).first()
    val = ((row.value if row else None) or {})
    raw = val.get("cutover_at")
    if not raw:
        return None
    try:
        return _aware(datetime.fromisoformat(str(raw)))
    except (ValueError, TypeError):
        return None


def cutover_reached(db: Session, company_id, at: datetime | None = None) -> bool:
    """T0 belgilanган VA `at` (default hozir) >= T0 bo'lsa True. Belgilanmagan -> False (enforcement yo'q)."""
    t0 = cutover_at(db, company_id)
    if t0 is None:
        return False
    now = _aware(at or datetime.now(timezone.utc))
    return now >= t0
