"""CashPostingService xatolari — loyihaning mavjud konvensiyasiga amal qiladi.

Mavjud servislar `HTTPException(status, message)` ko'taradi; kodli xatolar uchun
`detail={"error": <CODE>, ...}` naqshi ishlatiladi (QA'da ko'rilgan). Shu sabab
`CashPostingError` — HTTPException'ning KENGAYTMASI (yangi framework EMAS): FastAPI
uni avtomatik tutadi, va testlar `.code` bo'yicha tekshira oladi.
"""
from __future__ import annotations

from fastapi import HTTPException


class CashError:
    """Barqaror xato kodlari (kontrakt §15)."""

    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    ACCOUNT_ARCHIVED = "ACCOUNT_ARCHIVED"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    SHIFT_NOT_FOUND = "SHIFT_NOT_FOUND"
    SHIFT_NOT_BELONG_TO_ACCOUNT = "SHIFT_NOT_BELONG_TO_ACCOUNT"
    SHIFT_NOT_OPEN = "SHIFT_NOT_OPEN"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    NEGATIVE_APPROVAL_REQUIRED = "NEGATIVE_APPROVAL_REQUIRED"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    DUPLICATE_BUSINESS_LEG = "DUPLICATE_BUSINESS_LEG"
    ALREADY_REVERSED = "ALREADY_REVERSED"
    INVALID_REVERSAL = "INVALID_REVERSAL"
    INVALID_TRANSFER = "INVALID_TRANSFER"
    INVALID_ACCOUNT_TYPE = "INVALID_ACCOUNT_TYPE"
    UNAUTHORIZED_OPERATION = "UNAUTHORIZED_OPERATION"
    INVALID_INPUT = "INVALID_INPUT"


# Kodga mos HTTP status (default 400)
_STATUS = {
    CashError.UNAUTHORIZED_OPERATION: 403,
    CashError.INSUFFICIENT_CASH: 409,
    CashError.NEGATIVE_APPROVAL_REQUIRED: 409,
    CashError.DUPLICATE_BUSINESS_LEG: 409,
    CashError.ALREADY_REVERSED: 409,
    CashError.SHIFT_NOT_OPEN: 409,
}


class CashPostingError(HTTPException):
    """Domen xatosi — HTTPException kengaytmasi (kod + xabar)."""

    def __init__(self, code: str, message: str, status_code: int | None = None):
        self.code = code
        super().__init__(
            status_code=status_code or _STATUS.get(code, 400),
            detail={"error": code, "message": message},
        )

    def __str__(self) -> str:  # test/log uchun kod ko'rinsin
        return f"{self.code}: {self.detail.get('message')}"
