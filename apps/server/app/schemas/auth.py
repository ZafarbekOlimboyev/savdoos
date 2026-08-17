import uuid

from pydantic import BaseModel

from app.schemas.common import ORMModel


class LoginPin(BaseModel):
    pin: str
    company_code: str | None = None


class LoginPassword(BaseModel):
    phone: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    employee: "EmployeeOut"


class EmployeeOut(ORMModel):
    id: uuid.UUID
    full_name: str
    phone: str | None = None
    role_code: str
    role_name: str
    status: str
    permissions: list[str] = []


Token.model_rebuild()
