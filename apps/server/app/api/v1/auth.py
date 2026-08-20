import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.deps import effective_permissions, get_current_employee
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import EmployeeStatus
from app.models.org import Company
from app.schemas.auth import ChangePassword, EmployeeOut, LoginPassword, LoginPin, Token

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Brute-force himoya: oddiy sliding-window (xotirada; Railway 1 instans).
# Ko'p instans bo'lsa keyin Redis'ga ko'chiriladi.
_ATTEMPTS: dict[str, list[float]] = {}
_MAX_FAILS = 10
_WINDOW_S = 300.0


def _rate_guard(key: str):
    now = time.time()
    fails = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW_S]
    _ATTEMPTS[key] = fails
    if len(fails) >= _MAX_FAILS:
        raise HTTPException(429, "Juda ko'p urinish — 5 daqiqadan keyin qayta urining")


def _rate_fail(key: str):
    _ATTEMPTS.setdefault(key, []).append(time.time())


def _rate_ok(key: str):
    _ATTEMPTS.pop(key, None)


def employee_out(e: Employee, db: Session) -> EmployeeOut:
    return EmployeeOut(
        id=e.id,
        full_name=e.full_name,
        phone=e.phone,
        role_code=e.role.code,
        role_name=e.role.name,
        status=e.status.value,
        permissions=sorted(effective_permissions(e, db)),
    )


def _token(e: Employee, db: Session) -> Token:
    token = create_access_token(str(e.id), {"role": e.role.code, "company_id": str(e.company_id)})
    return Token(access_token=token, employee=employee_out(e, db))


@router.post("/login", response_model=Token)
def login_pin(data: LoginPin, request: Request, db: Session = Depends(get_db)):
    """Kassir PIN login — FAQAT bitta do'kon (company_code) doirasida tekshiriladi.

    Kod berilsa — o'sha do'kon xodimlari orasidan qidiradi. Berilmasa — faqat bazada
    bitta kompaniya bo'lgandagina ruxsat (eski o'rnatmalar bilan moslik); ko'p bo'lsa
    company_code talab qilinadi (aks holda boshqa do'konga kirib ketish xavfi)."""
    ip = request.client.host if request.client else "?"
    rk = f"pin:{ip}:{(data.company_code or '-').strip().lower()}"
    _rate_guard(rk)

    if data.company_code:
        comp = (
            db.query(Company)
            .filter(Company.code == data.company_code.strip().lower(), Company.deleted_at.is_(None))
            .first()
        )
        if not comp:
            raise HTTPException(401, "Do'kon kodi topilmadi")
        company_id = comp.id
    else:
        comp_ids = db.query(Company.id).filter(Company.deleted_at.is_(None)).all()
        if len(comp_ids) > 1:
            raise HTTPException(400, "Do'kon kodi kerak (company_code)")
        if not comp_ids:
            raise HTTPException(401, "Do'kon topilmadi")  # fail-closed: filtrsiz qidirmaymiz
        company_id = comp_ids[0][0]

    q = db.query(Employee).filter(
        Employee.company_id == company_id,
        Employee.pin_hash.isnot(None),
        Employee.deleted_at.is_(None),
        Employee.status == EmployeeStatus.active,  # to'xtatilgan/bo'shatilgan kira olmaydi
    )
    for e in q.all():
        if verify_password(data.pin, e.pin_hash):
            _rate_ok(rk)
            return _token(e, db)
    _rate_fail(rk)
    raise HTTPException(401, "PIN noto'g'ri")


@router.post("/login/password", response_model=Token)
def login_password(data: LoginPassword, request: Request, db: Session = Depends(get_db)):
    """Egа/admin login — telefon + parol. Telefon global noyob (parolli akkaunt uchun)."""
    phone = (data.phone or "").strip()
    ip = request.client.host if request.client else "?"
    rk = f"pw:{ip}:{phone}"
    _rate_guard(rk)
    candidates = (
        db.query(Employee)
        .filter(
            Employee.phone == phone,
            Employee.password_hash.isnot(None),
            Employee.deleted_at.is_(None),
        )
        .all()
    )
    for e in candidates:
        if verify_password(data.password, e.password_hash):
            if e.status != EmployeeStatus.active:
                raise HTTPException(401, "Xodim faol emas")
            _rate_ok(rk)
            return _token(e, db)
    _rate_fail(rk)
    raise HTTPException(401, "Telefon yoki parol noto'g'ri")


@router.post("/password")
def change_password(
    data: ChangePassword,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Foydalanuvchi o'z parolini o'zgartiradi. Mavjud parol bo'lsa — eskisini tasdiqlaydi."""
    new = data.new_password or ""
    if len(new) < 6:
        raise HTTPException(400, "Yangi parol kamida 6 belgi bo'lishi kerak")
    if emp.password_hash:
        if not data.old_password or not verify_password(data.old_password, emp.password_hash):
            raise HTTPException(401, "Joriy parol noto'g'ri")
    emp.password_hash = hash_password(new)
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=EmployeeOut)
def me(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    return employee_out(emp, db)
