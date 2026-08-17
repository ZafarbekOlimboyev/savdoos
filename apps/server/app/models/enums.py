import enum


class EmployeeStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    terminated = "terminated"


class ShiftStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class SaleStatus(str, enum.Enum):
    completed = "completed"
    voided = "voided"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


class PurchaseStatus(str, enum.Enum):
    draft = "draft"
    received = "received"
    paid = "paid"
    partial = "partial"
    debt = "debt"
    cancelled = "cancelled"


class ReturnReason(str, enum.Enum):
    customer = "customer"
    defective = "defective"
    wrong_item = "wrong_item"
    expired = "expired"
    other = "other"


class CreditTxnType(str, enum.Enum):
    charge = "charge"
    payment = "payment"
    adjustment = "adjustment"
    writeoff = "writeoff"


class MovementType(str, enum.Enum):
    purchase_in = "purchase_in"
    sale_out = "sale_out"
    return_in = "return_in"
    writeoff = "writeoff"
    adjustment = "adjustment"
    transfer_in = "transfer_in"
    transfer_out = "transfer_out"
    count_adjust = "count_adjust"


class CashMovementType(str, enum.Enum):
    opening = "opening"
    sale_cash = "sale_cash"
    payin = "payin"
    payout = "payout"
    expense = "expense"
    collection = "collection"
    closing = "closing"


class PriceType(str, enum.Enum):
    buy = "buy"
    sell = "sell"


class ImportStatus(str, enum.Enum):
    uploaded = "uploaded"
    validated = "validated"
    committing = "committing"
    committed = "committed"
    failed = "failed"
