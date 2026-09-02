import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.auth import Employee, EmployeePermission
from app.models.enums import EmployeeStatus


def get_current_employee(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Employee:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Avtorizatsiya talab qilinadi")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
        sub = uuid.UUID(str(payload["sub"]))  # sub UUID bo'lmasa ham 401 (xom 500 emas)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token yaroqsiz")
    emp = db.get(Employee, sub)
    if not emp or emp.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Xodim topilmadi")
    # To'xtatilgan/bo'shatilgan xodimning eski tokeni ham ishlamasin
    if emp.status != EmployeeStatus.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Xodim faol emas")
    # Token bekor qilish: parol o'zgarganda/chiqishда sec_epoch oshadi — eski token 'sv' mos kelmaydi.
    # (Eski, 'sv'siz tokenlar => 0, yangi xodimlarда ham sec_epoch=0 — deploy'да hech kim chiqarilmaydi.)
    if int(payload.get("sv", 0) or 0) != int(getattr(emp, "sec_epoch", 0) or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya bekor qilingan — qayta kiring")
    # Do'kon o'chirilgan yoki vendor tomonidan vaqtincha to'xtatilgan bo'lsa — mavjud token ham ishlamasin.
    from app.models.org import Company
    from app.models.settings import Setting
    comp = db.get(Company, emp.company_id)
    if not comp or comp.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Do'kon topilmadi")
    _susp = db.query(Setting).filter(
        Setting.company_id == emp.company_id, Setting.key == "suspended"
    ).first()
    if _susp and (_susp.value or {}).get("on"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning.")
    return emp


# Ruxsat cheklovisiz (hamma narsani ko'radi) rollar — Ega va Administrator.
FULL_ACCESS_ROLES = ("ega", "administrator")


def is_owner(emp: Employee) -> bool:
    """Ega (do'kon egasi) — adminlarni boshqaradi, filial cheklovi yo'q."""
    return emp.role.code == "ega"


def actor_branch(emp: Employee, db: Session):
    """Xodim YOZADIGAN filial: biriktirilgan filial (EmployeeBranch) — bo'lmasa birinchi faol filial.
    Sotuv/writeoff/sanoq/qaytarish shu filialga tushishi kerak (ko'p-filialда to'g'ri yozilishi uchun).
    Ilgari inventory/return doim BIRINCHI filialга yozardi — ko'p-filialда noto'g'ri edi."""
    from app.models.auth import EmployeeBranch
    from app.models.org import Branch
    return (
        db.query(Branch)
        .join(EmployeeBranch, EmployeeBranch.branch_id == Branch.id)
        .filter(EmployeeBranch.employee_id == emp.id, Branch.company_id == emp.company_id,
                Branch.deleted_at.is_(None))
        .first()
        or db.query(Branch)
        .filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None))
        .first()
    )


def visible_branches(emp: Employee, db: Session) -> set | None:
    """Xodim KO'RA oladigan filiallar to'plami. None = cheklovsiz (hamma filial).
    - Ega: doim None (butun kompaniya).
    - Boshqa xodim: biriktirilgan filial(lar) — bitta filialга bog'langan bo'lsa faqat o'sha.
    - Hech qaysi filialга biriktirilmagan bo'lsa: None (kompaniya bo'yicha — moslik)."""
    if emp.role.code == "ega":
        return None
    from app.models.auth import EmployeeBranch
    rows = db.query(EmployeeBranch.branch_id).filter(EmployeeBranch.employee_id == emp.id).all()
    ids = {r[0] for r in rows}
    return ids or None


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
        if emp.role.code in FULL_ACCESS_ROLES:
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
        if emp.role.code in FULL_ACCESS_ROLES:
            return emp
        perms = effective_permissions(emp, db)
        if not any(code in perms for code in permission_codes):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Ruxsat yo'q: {' / '.join(permission_codes)}")
        return emp

    return checker
