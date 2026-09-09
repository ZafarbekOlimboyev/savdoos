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
    client_uuid: uuid.UUID | None = None   # QA OFF-5: idempotentlik (response-lost/retry'da dublikat mijoz emas)
    address: str | None = None


class CreditPayment(BaseModel):
    amount: float
    method: str = "cash"
    client_uuid: uuid.UUID | None = None
    # §2 SMENASIZ NAQD uchun AYNAN custody hisobi (ACTIVE TILL yoki SAFE). Ochiq smena bo'lsa
    # custody = shift.till_id (server avtoritet) va bu maydon KERAK EMAS; berilsa smena kassasiga
    # MOS bo'lishi shart. TAXMIN YO'Q: filial-default, yagona-TILL, kassir, terminal — hech biri.
    cash_account_id: uuid.UUID | None = None
