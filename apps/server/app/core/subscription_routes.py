# -*- coding: utf-8 -*-
"""Obuna majburlashi uchun MARSHRUT TASNIFI — `RESTRICTED` ijarachi nimani qila oladi.

⚠️  RUXSAT KODI BO'YICHA XARITALASH YARAMAYDI. Ayni kod o'qish va yozuvda birga
    ishlatiladi: `hisobot.view` ham `GET /reports/*` ni, ham `POST /cash/ops` ni
    qo'riqlaydi; `kassa.sell` ham `GET /payments/config` ni, ham `POST /sales` ni.
    Shu bois tasnif MARSHRUT darajasida, aniq ro'yxat bilan beriladi.

⚠️  METOD + YO'L bo'yicha kalit, faqat yo'l bo'yicha EMAS. Uchta yo'l sinflarga
    bo'linib ketadi: `/shifts/{shift_id}/cash`, `/cash/ops`, `/print-jobs` —
    ularning GET va POST variantlari HAR XIL sinfda.

⚠️  TASNIF HANDLER XULQIDAN olingan, metoddan emas. `POST /catalog/v2/preview`
    javobida `wrote_nothing: True` qaytaradi, lekin `import_jobs` ga YOZADI;
    `GET /payments/qr/{txn_id}` esa GET bo'lsa ham `db.commit()` qiladi. Nom yoki
    metod bo'yicha darvoza qurmang.

⚠️  YANGI MARSHRUT — MAJBURIY TASNIF. `tests/test_subscription_enforcement.py`
    dagi qamrov qo'riqchisi tasniflanmagan marshrutni QIZIL qiladi, ya'ni yangi
    endpoint majburlashdan jimgina sirg'alib o'ta olmaydi.
"""
from __future__ import annotations

from app.services.subscription import policy

#: Faqat o'qish/hisobot — `RESTRICTED` da ham OCHIQ.
ALLOW_READ = "ALLOW_READ"
ALLOW_REPORT = "ALLOW_REPORT"
#: Ijarachining O'Z ma'lumotini fayl qilib chiqarish. Hozircha bitta ham yo'q —
#: Phase 4A qarzidagi `.xls` eksport qo'shilsa, SHU YERGA yozilishi shart.
ALLOW_EXPORT = "ALLOW_EXPORT"
#: Operatorning o'z sessiyasi/qurilmasi/hisob-kitobi — to'lash uchun ham kira olsin.
ALLOW_ACCOUNT_BILLING = "ALLOW_ACCOUNT_BILLING"
#: YAGONA ISTISNO: ALLAQACHON OCHIQ smenani yopish.
ALLOW_SHIFT_CLOSE = "ALLOW_SHIFT_CLOSE"
#: Yangi biznes holati — `RESTRICTED` da TO'SILADI.
BLOCK_BUSINESS_WRITE = "BLOCK_BUSINESS_WRITE"
#: Ijarachiga tegishli emas: vendor portali, sog'liq zondi, tashqi webhook.
OUT_OF_SCOPE_SYSTEM = "OUT_OF_SCOPE_SYSTEM"

ALL_CLASSES = frozenset({
    ALLOW_READ, ALLOW_REPORT, ALLOW_EXPORT, ALLOW_ACCOUNT_BILLING,
    ALLOW_SHIFT_CLOSE, BLOCK_BUSINESS_WRITE, OUT_OF_SCOPE_SYSTEM,
})

#: Ijarachi kontekstisiz marshrutlar — darvoza ularda kompaniyani ANIQLAY OLMAYDI.
#  ⚠️  Ularni «ruxsat» deb o'tkazish EMAS, darvozadan BUTUNLAY chiqarish kerak:
#      XPAY webhook'i haqiqiy chaqiruvda ham ijarachi tokeni bilan kelmaydi.
NO_TENANT_CONTEXT = frozenset({
    ("GET", "/health"), ("GET", "/health/ready"), ("POST", "/payments/xpay/webhook"),
})

#: Marshrut sinfi -> `policy` toifasi. `evaluate_subscription_access` AUTHORITATIVE
#  bo'lib qoladi: darvoza qarorni SHU matritsadan oladi, o'zi o'ylab topmaydi.
#  ⚠️  `BUSINESS_WRITE` a'zolari matritsada TENG (`policy.is_allowed` ularni
#      ajratmaydi) — vakil sifatida `policy.SALE` olindi.
CLASS_TO_CATEGORY = {
    ALLOW_READ: policy.READ,
    ALLOW_REPORT: policy.READ,
    ALLOW_EXPORT: policy.READ,
    ALLOW_ACCOUNT_BILLING: policy.BILLING,
    ALLOW_SHIFT_CLOSE: policy.SHIFT_CLOSE,
    BLOCK_BUSINESS_WRITE: policy.SALE,
}

#: Javob sarlavhasi — barqaror kod, umumiy 403 emas.
ERROR_CODE = "SUBSCRIPTION_RESTRICTED"

#: (METOD, yo'l) -> sinf. Yo'llar `/api/v1` prefiksisiz.
SUBSCRIPTION_ROUTE_ACTIONS: dict[tuple[str, str], str] = {
    # ── TO'SILADI — yangi biznes holati (62) ─────────────────────────
    ("DELETE", "/branches/{branch_id}"): BLOCK_BUSINESS_WRITE,
    ("DELETE", "/categories/{category_id}"): BLOCK_BUSINESS_WRITE,
    ("DELETE", "/customers/{customer_id}"): BLOCK_BUSINESS_WRITE,
    ("DELETE", "/employees/{employee_id}"): BLOCK_BUSINESS_WRITE,
    ("DELETE", "/products/{product_id}"): BLOCK_BUSINESS_WRITE,
    ("DELETE", "/scales/{scale_id}"): BLOCK_BUSINESS_WRITE,
    ("DELETE", "/suppliers/{supplier_id}"): BLOCK_BUSINESS_WRITE,
    ("DELETE", "/tills/{till_id}"): BLOCK_BUSINESS_WRITE,
    ("GET", "/payments/qr/{txn_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/branches/{branch_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/categories/{category_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/customers/{customer_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/employees/{employee_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/employees/{employee_id}/permissions"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/print-jobs/{job_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/products/{product_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/purchases/{purchase_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/scales/{scale_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/suppliers/{supplier_id}"): BLOCK_BUSINESS_WRITE,
    ("PATCH", "/tills/{till_id}"): BLOCK_BUSINESS_WRITE,
    ("POST", "/branches"): BLOCK_BUSINESS_WRITE,
    ("POST", "/cash/ops"): BLOCK_BUSINESS_WRITE,
    ("POST", "/catalog/v2/commit"): BLOCK_BUSINESS_WRITE,
    ("POST", "/catalog/v2/cutover-complete"): BLOCK_BUSINESS_WRITE,
    ("POST", "/catalog/v2/initial-create"): BLOCK_BUSINESS_WRITE,
    ("POST", "/catalog/v2/preview"): BLOCK_BUSINESS_WRITE,
    ("POST", "/categories"): BLOCK_BUSINESS_WRITE,
    ("POST", "/customers"): BLOCK_BUSINESS_WRITE,
    ("POST", "/customers/{customer_id}/payments"): BLOCK_BUSINESS_WRITE,
    ("POST", "/employees"): BLOCK_BUSINESS_WRITE,
    ("POST", "/inventory/count"): BLOCK_BUSINESS_WRITE,
    ("POST", "/inventory/transfer"): BLOCK_BUSINESS_WRITE,
    ("POST", "/inventory/writeoff"): BLOCK_BUSINESS_WRITE,
    ("POST", "/lots/enable"): BLOCK_BUSINESS_WRITE,
    ("POST", "/lots/shortfalls/{shortfall_id}/resolve"): BLOCK_BUSINESS_WRITE,
    ("POST", "/lots/timezone/confirm"): BLOCK_BUSINESS_WRITE,
    ("POST", "/payments/qr"): BLOCK_BUSINESS_WRITE,
    ("POST", "/print-jobs"): BLOCK_BUSINESS_WRITE,
    ("POST", "/products/archive-empty"): BLOCK_BUSINESS_WRITE,
    ("POST", "/products/barcodes/import"): BLOCK_BUSINESS_WRITE,
    ("POST", "/products/bulk"): BLOCK_BUSINESS_WRITE,
    ("POST", "/products/categorize"): BLOCK_BUSINESS_WRITE,
    ("POST", "/products/import/commit"): BLOCK_BUSINESS_WRITE,
    ("POST", "/purchases"): BLOCK_BUSINESS_WRITE,
    ("POST", "/receipt/logos"): BLOCK_BUSINESS_WRITE,
    ("POST", "/receiving/commit"): BLOCK_BUSINESS_WRITE,
    ("POST", "/receiving/scan"): BLOCK_BUSINESS_WRITE,
    ("POST", "/receiving/{receiving_id}/corrections"): BLOCK_BUSINESS_WRITE,
    ("POST", "/reports/history/seed"): BLOCK_BUSINESS_WRITE,
    ("POST", "/returns"): BLOCK_BUSINESS_WRITE,
    ("POST", "/safes"): BLOCK_BUSINESS_WRITE,
    ("POST", "/sales"): BLOCK_BUSINESS_WRITE,
    ("POST", "/scales"): BLOCK_BUSINESS_WRITE,
    ("POST", "/scales/{scale_id}/sync"): BLOCK_BUSINESS_WRITE,
    ("POST", "/shifts/open"): BLOCK_BUSINESS_WRITE,
    ("POST", "/shifts/{shift_id}/cash"): BLOCK_BUSINESS_WRITE,
    ("POST", "/suppliers"): BLOCK_BUSINESS_WRITE,
    ("POST", "/suppliers/{supplier_id}/payments"): BLOCK_BUSINESS_WRITE,
    ("POST", "/sync/push"): BLOCK_BUSINESS_WRITE,
    ("POST", "/tills"): BLOCK_BUSINESS_WRITE,
    ("PUT", "/receipt/settings"): BLOCK_BUSINESS_WRITE,
    ("PUT", "/settings"): BLOCK_BUSINESS_WRITE,

    # ── YAGONA yozuv istisnosi — ochiq smenani yopish (1) ────────────
    ("POST", "/shifts/{shift_id}/close"): ALLOW_SHIFT_CLOSE,

    # ── Operatorning o'z hisobi/qurilmasi (8) ────────────────────────
    ("POST", "/auth/login"): ALLOW_ACCOUNT_BILLING,
    ("POST", "/auth/login/password"): ALLOW_ACCOUNT_BILLING,
    ("POST", "/auth/logout"): ALLOW_ACCOUNT_BILLING,
    ("POST", "/auth/password"): ALLOW_ACCOUNT_BILLING,
    ("POST", "/devices/register"): ALLOW_ACCOUNT_BILLING,
    ("POST", "/devices/unregister"): ALLOW_ACCOUNT_BILLING,
    ("POST", "/employees/{employee_id}/unlock"): ALLOW_ACCOUNT_BILLING,
    ("POST", "/fleet/heartbeat"): ALLOW_ACCOUNT_BILLING,

    # ── Hisobot o'qishlari (21) ──────────────────────────────────────
    ("GET", "/employees/{employee_id}/stats"): ALLOW_REPORT,
    ("GET", "/inventory/low"): ALLOW_REPORT,
    ("GET", "/inventory/overview"): ALLOW_REPORT,
    ("GET", "/reports/alerts"): ALLOW_REPORT,
    ("GET", "/reports/alerts/detail"): ALLOW_REPORT,
    ("GET", "/reports/cashflow"): ALLOW_REPORT,
    ("GET", "/reports/categories"): ALLOW_REPORT,
    ("GET", "/reports/dashboard"): ALLOW_REPORT,
    ("GET", "/reports/dead-stock"): ALLOW_REPORT,
    ("GET", "/reports/debtors"): ALLOW_REPORT,
    ("GET", "/reports/detail"): ALLOW_REPORT,
    ("GET", "/reports/hourly"): ALLOW_REPORT,
    ("GET", "/reports/inventory-value"): ALLOW_REPORT,
    ("GET", "/reports/overview"): ALLOW_REPORT,
    ("GET", "/reports/pnl"): ALLOW_REPORT,
    ("GET", "/reports/sales-dynamics"): ALLOW_REPORT,
    ("GET", "/reports/summary"): ALLOW_REPORT,
    ("GET", "/reports/top-products"): ALLOW_REPORT,
    ("GET", "/sales/summary"): ALLOW_REPORT,
    ("GET", "/shifts/overview"): ALLOW_REPORT,
    ("GET", "/shifts/{shift_id}/summary"): ALLOW_REPORT,

    # ── Oddiy o'qishlar (67) ─────────────────────────────────────────
    ("GET", "/audit"): ALLOW_READ,
    ("GET", "/auth/context"): ALLOW_READ,
    ("GET", "/auth/me"): ALLOW_READ,
    ("GET", "/auth/pin-roster"): ALLOW_READ,
    ("GET", "/branches"): ALLOW_READ,
    ("GET", "/cash-setup"): ALLOW_READ,
    ("GET", "/cash/custody-preview"): ALLOW_READ,
    ("GET", "/cash/ops"): ALLOW_READ,
    ("GET", "/catalog/v2/jobs"): ALLOW_READ,
    ("GET", "/catalog/v2/settings"): ALLOW_READ,
    ("GET", "/categories"): ALLOW_READ,
    ("GET", "/customers"): ALLOW_READ,
    ("GET", "/customers/{customer_id}"): ALLOW_READ,
    ("GET", "/customers/{customer_id}/detail"): ALLOW_READ,
    ("GET", "/employees"): ALLOW_READ,
    ("GET", "/employees/{employee_id}"): ALLOW_READ,
    ("GET", "/fleet/devices"): ALLOW_READ,
    ("GET", "/inventory/movements"): ALLOW_READ,
    ("GET", "/lots/alerts"): ALLOW_READ,
    ("GET", "/lots/availability"): ALLOW_READ,
    ("GET", "/lots/batches"): ALLOW_READ,
    ("GET", "/lots/batches/{lot_id}"): ALLOW_READ,
    ("GET", "/lots/expiring"): ALLOW_READ,
    ("GET", "/lots/products/{product_id}"): ALLOW_READ,
    ("GET", "/lots/shortfalls"): ALLOW_READ,
    ("GET", "/lots/shortfalls/{shortfall_id}"): ALLOW_READ,
    ("GET", "/payments/config"): ALLOW_READ,
    ("GET", "/permissions"): ALLOW_READ,
    ("GET", "/print-jobs"): ALLOW_READ,
    ("GET", "/products"): ALLOW_READ,
    ("GET", "/products/by-barcode/{code}"): ALLOW_READ,
    ("GET", "/products/catalog-version"): ALLOW_READ,
    ("GET", "/products/guess-category"): ALLOW_READ,
    ("GET", "/products/scan"): ALLOW_READ,
    ("GET", "/products/{product_id}"): ALLOW_READ,
    ("GET", "/purchases"): ALLOW_READ,
    ("GET", "/purchases/{purchase_id}"): ALLOW_READ,
    ("GET", "/receipt/logos/{logo_id}"): ALLOW_READ,
    ("GET", "/receipt/profile"): ALLOW_READ,
    ("GET", "/receipt/sample"): ALLOW_READ,
    ("GET", "/receipt/settings"): ALLOW_READ,
    ("GET", "/receiving"): ALLOW_READ,
    ("GET", "/receiving/{receiving_id}"): ALLOW_READ,
    ("GET", "/returns"): ALLOW_READ,
    ("GET", "/returns/{return_id}/receipt"): ALLOW_READ,
    ("GET", "/safes"): ALLOW_READ,
    ("GET", "/sales"): ALLOW_READ,
    ("GET", "/sales/cashiers"): ALLOW_READ,
    ("GET", "/sales/find"): ALLOW_READ,
    ("GET", "/sales/{sale_id}"): ALLOW_READ,
    ("GET", "/sales/{sale_id}/receipt"): ALLOW_READ,
    ("GET", "/scales"): ALLOW_READ,
    ("GET", "/scales/brands"): ALLOW_READ,
    ("GET", "/scales/ports"): ALLOW_READ,
    ("GET", "/scales/sync-preview"): ALLOW_READ,
    ("GET", "/settings"): ALLOW_READ,
    ("GET", "/shifts/current"): ALLOW_READ,
    ("GET", "/shifts/{shift_id}/cash"): ALLOW_READ,
    ("GET", "/suppliers"): ALLOW_READ,
    ("GET", "/suppliers/{supplier_id}"): ALLOW_READ,
    ("GET", "/suppliers/{supplier_id}/ledger"): ALLOW_READ,
    ("GET", "/sync/pull"): ALLOW_READ,
    ("GET", "/tills"): ALLOW_READ,
    ("POST", "/catalog/v2/reset/dry-run"): ALLOW_READ,
    ("POST", "/devices/test"): ALLOW_READ,
    ("POST", "/products/import/preview"): ALLOW_READ,
    ("POST", "/scales/test"): ALLOW_READ,

    # ── Ijarachiga tegishli emas (vendor/sog'liq/webhook) (16) ───────
    ("DELETE", "/admin/companies/{company_id}"): OUT_OF_SCOPE_SYSTEM,
    ("GET", "/admin/companies"): OUT_OF_SCOPE_SYSTEM,
    ("GET", "/admin/companies/{company_id}"): OUT_OF_SCOPE_SYSTEM,
    ("GET", "/admin/overview"): OUT_OF_SCOPE_SYSTEM,
    ("GET", "/admin/portal"): OUT_OF_SCOPE_SYSTEM,
    ("GET", "/health"): OUT_OF_SCOPE_SYSTEM,
    ("GET", "/health/ready"): OUT_OF_SCOPE_SYSTEM,
    ("PATCH", "/admin/companies/{company_id}/plan"): OUT_OF_SCOPE_SYSTEM,
    ("PATCH", "/admin/companies/{company_id}/suspend"): OUT_OF_SCOPE_SYSTEM,
    ("POST", "/admin/companies"): OUT_OF_SCOPE_SYSTEM,
    ("POST", "/admin/companies/{company_id}/seed-demo"): OUT_OF_SCOPE_SYSTEM,
    ("POST", "/admin/login"): OUT_OF_SCOPE_SYSTEM,
    ("POST", "/admin/logout"): OUT_OF_SCOPE_SYSTEM,
    ("POST", "/admin/reset-password"): OUT_OF_SCOPE_SYSTEM,
    ("POST", "/catalog/v2/reset/execute"): OUT_OF_SCOPE_SYSTEM,
    ("POST", "/payments/xpay/webhook"): OUT_OF_SCOPE_SYSTEM,
}
