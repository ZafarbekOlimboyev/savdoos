import uuid
from datetime import date

from pydantic import BaseModel, Field, field_validator

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
    # ── PHASE 4B ────────────────────────────────────────────────────────
    #  ⚠️  Manager katalogda «bu tovar partiya bo'yicha kuzatiladimi?» ni
    #      KO'RSATISHI shart: inventarizatsiya va hisobdan chiqarish oqimi
    #      kuzatuvli tovarda PARTIYA darajasida bo'ladi. Ilgari buni bilish
    #      uchun har mahsulotga alohida `/lots/products/{id}` chaqirish kerak
    #      edi — 7137 mahsulotli katalogda bu imkonsiz.
    #  `lots_activated_at` ATAYLAB chiqarilmaydi (model izohi): u tasnif
    #      uchun server sanasi, mijoz qaroriga ta'sir qilmaydi.
    track_lots: bool = False
    track_expiry: bool = False


class ScaleScanOut(BaseModel):
    """Vaznli etiketkadan o'qilgan qism (`services/scale_barcode.py`)."""
    plu: int
    grams: int
    qty: str            # kilogramm, AYNAN 3 kasr xonali satr: "1.234"


class ProductScanOut(BaseModel):
    """`GET /products/scan` (Phase 5G) — skaner kodi bo'yicha SERVER qarori.

    kind:
      barcode   — `ProductBarcode` AYNAN mos (arxivlangan mahsulot ham; `is_active` ko'rinadi)
      scale     — vaznli etiketka, bitta PLU mos: `product` + `scale.qty`
      ambiguous — vaznli etiketka, bir nechta mahsulot shu PLU'da: `candidates`
      none      — hech narsa topilmadi (`scale` vaznli etiketka bo'lsa to'ldiriladi)"""
    code: str
    kind: str
    product: ProductOut | None = None
    candidates: list[ProductOut] = []
    scale: ScaleScanOut | None = None


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
    client_uuid: uuid.UUID | None = None   # QA PC-007: retry/2-tab idempotentligi

    @field_validator("expiry_date", mode="before")
    @classmethod
    def _empty_expiry(cls, v):
        # QA PC-024: UI bo'sh satr yuborsa 422 emas — None (PATCH bilan izchil)
        return None if v == "" else v


class ProductBulkCreate(BaseModel):
    items: list[ProductCreate] = Field(max_length=10000)
