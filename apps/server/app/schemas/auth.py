import uuid

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginPin(BaseModel):
    pin: str = Field(min_length=4, max_length=12)  # bo'sh PIN bypass'iga qarshi
    company_code: str | None = None


class LoginPassword(BaseModel):
    phone: str = Field(min_length=4)
    password: str = Field(min_length=1)


class ChangePassword(BaseModel):
    old_password: str | None = None
    new_password: str


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
    company_name: str | None = None   # do'kon nomi (mobil eksport sarlavhasi va h.k.)
    permissions: list[str] = []


Token.model_rebuild()
