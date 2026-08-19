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
    qty: float = Field(gt=0)
    unit_cost: float = Field(ge=0)


class PurchaseCreate(BaseModel):
    supplier_id: uuid.UUID
    status: str = "received"           # received | debt
    items: list[PurchaseItemIn]
    client_uuid: uuid.UUID | None = None


class PurchaseOut(ORMModel):
    id: uuid.UUID
    doc_no: str
    supplier_id: uuid.UUID
    status: str
    total: float
