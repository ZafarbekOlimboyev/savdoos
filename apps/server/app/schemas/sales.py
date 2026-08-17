import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class SaleItemIn(BaseModel):
    product_id: uuid.UUID
    qty: float = 1
    discount: float = 0


class SaleCreate(BaseModel):
    items: list[SaleItemIn]
    payment_method: str = "cash"          # cash|card|qr|credit
    given_amount: float | None = None
    customer_id: uuid.UUID | None = None
    discount_total: float = 0
    client_uuid: uuid.UUID | None = None  # offline idempotentlik


class SaleItemOut(ORMModel):
    product_id: uuid.UUID
    name_snapshot: str
    qty: float
    unit_price: float
    line_total: float


class SaleOut(ORMModel):
    id: uuid.UUID
    receipt_no: str
    uid: str | None = None
    status: str
    subtotal: float
    discount_total: float
    total: float
    cost_total: float
    sold_at: datetime
    items: list[SaleItemOut] = []


class ReturnItemIn(BaseModel):
    product_id: uuid.UUID
    qty: float
    unit_price: float


class ReturnCreate(BaseModel):
    original_sale_id: uuid.UUID | None = None
    reason: str = "customer"
    restock: bool = True
    refund_method: str = "cash"
    items: list[ReturnItemIn]
    client_uuid: uuid.UUID | None = None
