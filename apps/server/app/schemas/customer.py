import uuid

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CustomerOut(ORMModel):
    id: uuid.UUID
    code: str
    full_name: str
    phone: str | None = None
    credit_balance: float


class CustomerCreate(BaseModel):
    full_name: str
    phone: str | None = None
    address: str | None = None


class CreditPayment(BaseModel):
    amount: float
    method: str = "cash"
    client_uuid: uuid.UUID | None = None
