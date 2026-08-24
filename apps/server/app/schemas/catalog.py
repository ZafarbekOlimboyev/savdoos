import uuid
from datetime import date

from pydantic import BaseModel, Field

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
    is_weighted: bool = False
    plu_code: str | None = None
    scale_sync: bool = False
    sold_qty: float = 0   # so'nggi 30 kunda sotilgan miqdor (POS aqlli tartib uchun)


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    article_code: str | None = Field(default=None, max_length=120)
    sku: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    barcode: str | None = Field(default=None, max_length=64)
    unit_code: str = "dona"
    buy_price: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    sell_price: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    stock: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    min_qty: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    is_weighted: bool = False
    plu_code: str | None = None
    scale_sync: bool = False
    expiry_date: date | None = None


class ProductBulkCreate(BaseModel):
    items: list[ProductCreate] = Field(max_length=10000)
