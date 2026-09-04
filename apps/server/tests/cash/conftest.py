# -*- coding: utf-8 -*-
"""Cash quyi tizimi integratsion testlari — o'z PostgreSQL serveri (pgserver).

Cash subsystem FAQAT Postgres (schema/trigger/deferred-constraint). Loyihaning asosiy
test to'plami SQLite'da (tests/conftest.py), shuning uchun bu testlar O'ZINING
pgserver + engine'ini ishlatadi (app'ning global SQLite engine'iga tegmaydi).

Fixture'lar:
  cashenv  — (session) pgserver + create_all(legacy) + deploy_cash_schema + seed(company/branch/employee)
  db       — (function) shu engine'ga bog'langan yangi Session
"""
from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

# Cash subsystem Postgres talab qiladi; pgserver bo'lmasa — to'plamni o'tkazib yuboramiz.
pgserver = pytest.importorskip("pgserver")

os.environ.setdefault("DATABASE_URL", "sqlite:///./_pytest.db")  # app import uchun (biz ishlatmaymiz)
os.environ.setdefault("VENDOR_ADMIN_KEY", "test-vendor-key")
os.environ.setdefault("APP_ENV", "dev")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401  (Base.metadata to'liq bo'lishi uchun)
from app.db.base import Base  # noqa: E402
from app.db.cash.deploy import deploy_cash_schema  # noqa: E402
from app.models.auth import Employee, Role  # noqa: E402
from app.models.org import Branch, Company  # noqa: E402


def _normalize(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass
class CashEnv:
    engine: object
    company_id: uuid.UUID
    branch_id: uuid.UUID
    employee_id: uuid.UUID
    now: datetime


@pytest.fixture(scope="session")
def cashenv():
    tmp = tempfile.mkdtemp(prefix="cashpg_test_")
    srv = pgserver.get_server(tmp)
    engine = create_engine(_normalize(srv.get_uri()), future=True)
    # Legacy sxema (companies/branches/employees/... ) — cash FK'lari public.* ga tayanadi
    Base.metadata.create_all(engine)
    # Cash sxemasi — legacy yonida, non-destructive
    res = deploy_cash_schema(engine)
    assert res == "deployed", res
    # PROD idempotentlik indekslari (initdb._ensure_indexes bilan izchil) — create_all bularni
    # YARATMAYDI (raw partial-unique). Ularsiz konkurrent-dublikat dedup (client_uuid race)
    # test bazasida ishlamasди va prodдан farq qilardi (masalan konkurrent receiving 2 leg berardi).
    _prod_idem_indexes = [
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_receivings_client_uuid ON receivings (company_id, client_uuid) WHERE client_uuid IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_purchases_client_uuid ON purchases (company_id, client_uuid) WHERE client_uuid IS NOT NULL AND deleted_at IS NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_suppay_client_uuid ON supplier_payments (supplier_id, client_uuid) WHERE client_uuid IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_custpay_client_uuid ON customer_payments (customer_id, client_uuid) WHERE client_uuid IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_company_client_uuid ON sales (company_id, client_uuid) WHERE client_uuid IS NOT NULL AND deleted_at IS NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_returns_client_uuid ON returns (company_id, client_uuid) WHERE client_uuid IS NOT NULL AND deleted_at IS NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cashmov_client_uuid ON cash_movements (shift_id, client_uuid) WHERE client_uuid IS NOT NULL",
    ]
    with engine.begin() as con:
        for ddl in _prod_idem_indexes:
            con.execute(text(ddl))
    # Minimal seed: kompaniya + rol + xodim + filial
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        co = Company(name="Cash Test Co", code="cashtst", currency="UZS")
        s.add(co); s.flush()
        role = Role(code="cashier_cashtest", name="Cashier")
        s.add(role); s.flush()
        emp = Employee(company_id=co.id, full_name="Test Kassir", role_id=role.id)
        s.add(emp); s.flush()
        br = Branch(company_id=co.id, code="BR1", name="Filial")
        s.add(br); s.flush()
        s.commit()
        env = CashEnv(engine=engine, company_id=co.id, branch_id=br.id, employee_id=emp.id, now=now)
    yield env
    try:
        engine.dispose()
        srv.cleanup()
    except Exception:
        pass


@pytest.fixture
def db(cashenv):
    s = Session(cashenv.engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()
