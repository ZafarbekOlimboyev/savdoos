from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import effective_permissions, get_current_employee
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.auth import Employee
from app.schemas.auth import EmployeeOut, LoginPassword, LoginPin, Token

router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.post("/login", response_model=Token)
def login_pin(data: LoginPin, db: Session = Depends(get_db)):
    candidates = (
        db.query(Employee)
        .filter(Employee.pin_hash.isnot(None), Employee.deleted_at.is_(None))
        .all()
    )
    for e in candidates:
        if verify_password(data.pin, e.pin_hash):
            token = create_access_token(str(e.id), {"role": e.role.code})
            return Token(access_token=token, employee=employee_out(e, db))
    raise HTTPException(401, "PIN noto'g'ri")


@router.post("/login/password", response_model=Token)
def login_password(data: LoginPassword, db: Session = Depends(get_db)):
    e = (
        db.query(Employee)
        .filter(Employee.phone == data.phone, Employee.deleted_at.is_(None))
        .first()
    )
    if not e or not verify_password(data.password, e.password_hash):
        raise HTTPException(401, "Telefon yoki parol noto'g'ri")
    token = create_access_token(str(e.id), {"role": e.role.code})
    return Token(access_token=token, employee=employee_out(e, db))


@router.get("/me", response_model=EmployeeOut)
def me(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    return employee_out(emp, db)
