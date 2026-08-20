"""Barcha modellarni bitta joyda ro'yxatga olish (Base.metadata to'liq bo'lishi uchun)."""
from app.models.auth import (  # noqa: F401
    AuthSession,
    Employee,
    EmployeeBranch,
    EmployeePermission,
    Permission,
    Role,
    RolePermission,
)
from app.models.catalog import (  # noqa: F401
    Brand,
    Category,
    Product,
    ProductBarcode,
    ProductPrice,
    Unit,
)
from app.models.customers import (  # noqa: F401
    CreditTransaction,
    Customer,
    CustomerGroup,
    CustomerPayment,
    LoyaltyTransaction,
)
from app.models.imports import ImportJob, ImportRow  # noqa: F401
from app.models.inventory import Inventory, StockBatch, StockMovement  # noqa: F401
from app.models.org import Branch, Company, Terminal  # noqa: F401
from app.models.payments import QrPayment  # noqa: F401
from app.models.receiving import Receiving  # noqa: F401
from app.models.scales import Scale  # noqa: F401
from app.models.purchasing import (  # noqa: F401
    Purchase,
    PurchaseItem,
    Supplier,
    SupplierLedger,
    SupplierPayment,
)
from app.models.sales import (  # noqa: F401
    Return,
    ReturnItem,
    Sale,
    SaleDiscount,
    SaleItem,
    SalePayment,
)
from app.models.settings import PaymentMethod, ReceiptTemplate, Setting, TaxRate  # noqa: F401
from app.models.shifts import CashMovement, Shift  # noqa: F401
from app.models.sync import (  # noqa: F401
    ActivityEvent,
    AuditLog,
    SyncCursor,
    SyncDevice,
    SyncLog,
)
