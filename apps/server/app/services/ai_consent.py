"""Revision-bound company consent. Locks live until caller commit/rollback."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.org import Company
from app.models.settings import Setting
from app.services import ai_requirement as AR

CONSENT_KEY = "ai_consent"


def _row(db, company_id, *, exclusive=False):
    try:
        company = db.scalar(select(Company.id).where(Company.id == company_id)
                            .with_for_update(read=not exclusive))
        if company is None:
            AR.reject(403, "AI_COMPANY_INVALID")
        rows = db.scalars(select(Setting).where(Setting.company_id == company_id,
                          Setting.branch_id.is_(None), Setting.key == CONSENT_KEY)
                          .execution_options(populate_existing=True)).all()
    except SQLAlchemyError:
        AR.reject(503, "AI_REQUIREMENT_UNAVAILABLE")
    if len(rows) > 1:
        AR.reject(503, "AI_CONSENT_INTEGRITY")
    return rows[0] if rows else None


def _status(req, row):
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    granted = req.mode == "active" and req.matches(value)
    previous = value.get("provider")
    return {**req.public(), "required": req.mode == "active", "granted": granted,
            "granted_at": value.get("granted_at") if granted else None,
            "previous_provider": previous if previous in AR.PROVIDERS and previous != req.provider else None}


def status(db: Session, company_id):
    req = AR.locked(db)
    return _status(req, _row(db, company_id))


def grant(db: Session, emp, approved: dict):
    req = AR.locked(db)
    if req.mode != "active" or not req.matches(approved):
        AR.reject(409, "AI_REQUIREMENT_CHANGED")
    row = _row(db, emp.company_id, exclusive=True)
    before = dict(row.value or {}) if row is not None else None
    value = {**req.public(), "granted_at": datetime.now(timezone.utc).isoformat(),
             "employee_id": str(emp.id)}
    if row is None:
        row = Setting(company_id=emp.company_id, key=CONSENT_KEY, value=value)
        db.add(row)
    else:
        row.value, row.row_version = value, row.row_version + 1
    from app.services.audit import log
    log(db, emp.id, "update", "setting", None,
        before={"key": CONSENT_KEY, "value": before},
        after={"key": CONSENT_KEY, "value": value})
    return {"ok": True, **_status(req, row)}


def revoke(db: Session, emp):
    # Revocation must remain possible even if policy is paused, worker stale,
    # or credentials unavailable. It only needs the canonical lock order.
    AR._load(db)
    row = _row(db, emp.company_id, exclusive=True)
    before = dict(row.value or {}) if row is not None else None
    if row is not None:
        row.value = {"revoked_at": datetime.now(timezone.utc).isoformat(),
                     "employee_id": str(emp.id)}
        row.row_version += 1
    from app.services.audit import log
    log(db, emp.id, "update", "setting", None,
        before={"key": CONSENT_KEY, "value": before}, after={"key": CONSENT_KEY, "value": None})
    return {"ok": True}


def require_consent(db: Session, company_id, expected_revision: int):
    req = AR.locked(db)
    if expected_revision != req.revision:
        AR.reject(409, "AI_REQUIREMENT_CHANGED")
    st = _status(req, _row(db, company_id))
    if st["required"] and not st["granted"]:
        AR.reject(403, "AI_CONSENT_REQUIRED")
    return req
