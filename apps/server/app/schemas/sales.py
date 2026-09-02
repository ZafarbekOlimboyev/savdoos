import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SaleItemIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(default=1, gt=0, le=1e9, allow_inf_nan=False)   # 0/manfiy/cheksiz taqiqlanadi
    discount: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)  # Numeric(14,2) doirasida
    # QA PC-001: POS savatdagi narx-SNAPSHOT. Onlayn savdoda server E'TIBORGA OLMAYDI
    # (o'z narxidan hisoblaydi); FAQAT /sync/push (offline replay) honor qiladi — chunki
    # naqd allaqachon shu narxda olingan, flush paytidagi yangi narxda yozish kassani buzardi.
    unit_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)


class PaymentSplit(BaseModel):
    method: str                            # cash|card|qr|credit
    amount: float = Field(gt=0, le=1e9, allow_inf_nan=False)  # SalePayment.amount Numeric(14,2)


class SaleCreate(BaseModel):
    items: list[SaleItemIn] = Field(max_length=1000)
    payment_method: str = "cash"          # cash|card|qr|credit (yagona to'lov)
    payments: list[PaymentSplit] | None = None  # aralash (split) to'lov — berilsa payment_method e'tiborsiz
    given_amount: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)  # Numeric(14,2)
    customer_id: uuid.UUID | None = None
    discount_total: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)  # Numeric(14,2) overflow oldi
    client_uuid: uuid.UUID | None = None  # offline idempotentlik
    # Offline savdo HAQIQIY vaqti (kassада yaratilған payt). FAQAT /sync/push honor qiladi va
    # oqilona oynага cheklaydi — aks holда flush vaqti stamp'lanиб kunlik hisobot buzилаrди.
    sold_at: datetime | None = None
    # QA PC-001: POS ko'rsatgan JAMI (mijoz to'lagan summa). Onlayn savdoda server o'z
    # hisobidan >1 so'm farq ko'rsa 409 qaytaradi — kassir savatni yangilab qayta uradi.
    # Bo'lmasa (eski POS/mobil) tekshiruv o'tkazilmaydi (backward-compat).
    expected_total: float | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)


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
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_price: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)


class ReturnCreate(BaseModel):
    original_sale_id: uuid.UUID | None = None
    reason: str = "customer"
    restock: bool = True
    refund_method: str = "cash"
    items: list[ReturnItemIn] = Field(max_length=1000)
    client_uuid: uuid.UUID | None = None
