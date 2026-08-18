import uuid
from datetime import date

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CategoryOut(ORMModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None


class ProductOut(ORMModel):
    id: uuid.UUID
    article_code: str
    sku: str | None = None
    name: str
    category_id: uuid.UUID | None = None
    base_buy_price: float
    base_sell_price: float
    tax_rate: float
    is_active: bool
    barcodes: list[str] = []
    stock: float | None = None
    min_stock: float = 0
    unit_code: str | None = None
    expiry_date: date | None = None


class ProductCreate(BaseModel):
    name: str
    article_code: str | None = None
    sku: str | None = None
    category_id: uuid.UUID | None = None
    barcode: str | None = None
    unit_code: str = "dona"
    buy_price: float = 0
    sell_price: float = 0
    stock: float = 0
    min_qty: float = 0
    expiry_date: date | None = None


class ProductBulkCreate(BaseModel):
    items: list[ProductCreate]
