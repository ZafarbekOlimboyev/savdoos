import uuid

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SupplierOut(ORMModel):
    id: uuid.UUID
    name: str
    phone: str | None = None
    balance: float


class PurchaseItemIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(ge=0, le=1e9, allow_inf_nan=False)


class PurchaseCreate(BaseModel):
    supplier_id: uuid.UUID
    status: str = "received"           # received | debt
    items: list[PurchaseItemIn] = Field(max_length=5000)
    client_uuid: uuid.UUID | None = None
    # §1 EXPLICIT CUSTODY: smenasiz naqd amali uchun fizik hisob (TILL yoki SAFE) AYNAN
    # ko'rsatiladi. Ochiq smena bo'lsa server shift.till_id ni ishlatadi va bu maydon unga
    # TENG bo'lishi kerak (override QILIB BO'LMAYDI). Legacy/pre-T0 uchun nullable.
    cash_account_id: uuid.UUID | None = None


class PurchaseOut(ORMModel):
    id: uuid.UUID
    doc_no: str
    supplier_id: uuid.UUID
    status: str
    total: float
