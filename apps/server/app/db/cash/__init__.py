"""Cash quyi tizimi — sxema o'rnatish (deploy) va DDL manbasi.

Cash ledger'ning butun tuzilishi `cash_ddl_v1.sql` da (yagona haqiqat manbasi).
ORM modellar (app.models.cash) shu jadvallarга MAP qiladi, ularni YARATMAYDI.
"""
from app.db.cash.deploy import cash_schema_exists, deploy_cash_schema  # noqa: F401
