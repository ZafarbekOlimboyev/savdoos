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


# ══ PHASE 6A — OBUNA PLATFORMASI ════════════════════════════════════════════
#
# ⚠️  BU YERDAGI QIYMATLAR KATTA HARFDA va ustunlarda `SAEnum` EMAS, oddiy
#     `String` bo'lib saqlanadi. Ikkala qaror ham ataylab:
#
#     1. KATTA HARF — bu qiymatlar admin API va majburlash shartnomasining
#        TASHQI qismi (`X-Error-Code`, obuna holati). Fayl ichidagi eski
#        enum'lar kichik harfda, lekin ular ichki; bular chiqadi.
#     2. `String`, `SAEnum` EMAS — `SAEnum` Postgres'da NATIVE enum TIPI
#        yaratadi. Mavjud jadvalga ustun qo'shish yo'li (`initdb._ADDED_COLUMNS`)
#        esa faqat oddiy tur nomlarini biladi ("VARCHAR", "UUID", ...) va tip
#        yaratmaydi — `companies.status` shu yo'l bilan qo'shiladi. Bundan
#        tashqari native enum'ga yangi qiymat qo'shish DDL talab qiladi
#        (`ALTER TYPE ... ADD VALUE`, tranzaksiyada cheklangan), `String` da esa
#        bu oddiy kod o'zgarishi.
#
#     Ya'ni bu sinflar — VALIDATSIYA va yagona haqiqat manbai, ustun turi emas.


class CompanyStatus(str, enum.Enum):
    """Do'konning OPERATSION holati — obuna holatidan MUTLAQO ALOHIDA.

    `ACTIVE`    — normal ishlaydi.
    `SUSPENDED` — vendor to'xtatgan (to'lov emas, intizomiy/operatsion sabab).
    `CLOSED`    — do'kon yopilgan; tarixiy ma'lumot SAQLANADI, hard-delete YO'Q.
    """
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SubscriptionStatus(str, enum.Enum):
    """Obuna holati — do'kon operatsion holatidan ALOHIDA.

    Saqlangan qiymat KESH va ANIQ bekor qilish uchun; muddat bo'yicha qaror
    HAR SO'ROVDA qayta hisoblanadi (`services/subscription/state.py`).
    """
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    RESTRICTED = "RESTRICTED"
    CANCELLED = "CANCELLED"


class PlatformAdminRole(str, enum.Enum):
    """Platforma operatori roli — ijarachi rollari (owner/manager/cashier) bilan
    HECH QANDAY aloqasi yo'q va ular bir-birini QONDIRMAYDI."""
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    SUPPORT_READONLY = "SUPPORT_READONLY"


class SubscriptionPaymentMethod(str, enum.Enum):
    """Qo'lda kiritilgan to'lov usuli.

    ⚠️  Nom `PaymentMethod` EMAS: u nom `models/settings.py` da JADVAL sifatida
        band (do'konning kassa to'lov usullari) — ikkisi boshqa narsa.
    """
    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    QR = "QR"
    OTHER = "OTHER"
