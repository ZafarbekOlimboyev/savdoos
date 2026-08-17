import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.auth import Employee, EmployeePermission


def get_current_employee(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Employee:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Avtorizatsiya talab qilinadi")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token yaroqsiz")
    emp = db.get(Employee, uuid.UUID(payload["sub"]))
    if not emp or emp.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Xodim topilmadi")
    return emp


def effective_permissions(emp: Employee, db: Session) -> set[str]:
    """Rol standarti + xodim override (Xodimlar sahifasidagi toggle'lar)."""
    perms = {p.code for p in emp.role.permissions}
    overrides = db.query(EmployeePermission).filter_by(employee_id=emp.id).all()
    from app.models.auth import Permission

    for ov in overrides:
        code = db.get(Permission, ov.permission_id).code
        if ov.allowed:
            perms.add(code)
        else:
            perms.discard(code)
    return perms


def require(permission_code: str):
    """Endpoint uchun ruxsat tekshiruvchi dependency."""

    def checker(
        emp: Employee = Depends(get_current_employee),
        db: Session = Depends(get_db),
    ) -> Employee:
        if emp.role.code == "administrator":
            return emp
        if permission_code not in effective_permissions(emp, db):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Ruxsat yo'q: {permission_code}")
        return emp

    return checker


def require_any(*permission_codes: str):
    """Sanab o'tilgan ruxsatlardan kamida bittasi bo'lsa yetadi (masalan,
    kassir QARZ savdoda yangi mijoz yaratishi: mijozlar.edit YOKI kassa.sell)."""

    def checker(
        emp: Employee = Depends(get_current_employee),
        db: Session = Depends(get_db),
    ) -> Employee:
        if emp.role.code == "administrator":
            return emp
        perms = effective_permissions(emp, db)
        if not any(code in perms for code in permission_codes):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Ruxsat yo'q: {' / '.join(permission_codes)}")
        return emp

    return checker
