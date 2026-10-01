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

# Cash subsystem Postgres talab qiladi. Mahalliy mashinada pgserver bo'lmasa —
# to'plamni o'tkazib yuboramiz. CI'da esa BU MUMKIN EMAS.
#
# ⚠️  Bu conftest darajasidagi skip BUTUN `tests/cash/` KATALOGINI (37 fayl, ~650 test)
#     o'tkazib yuboradi va pytest buni ATIGI BITTA "1 skipped" deb ko'rsatadi. Ya'ni
#     CI 20 soniyada, 28 test bilan YASHIL bo'lardi — cash, migratsiya, backup, purge
#     va tenancy testlarining BIRORTASI ishlamagan holda. Yashil belgi qamrov haqida
#     hech narsa demasdi.
#
#     Shuning uchun CI'da yo'qlik SKIP emas, XATO: gate yolg'on gapirgandan ko'ra
#     buzilgani ma'qul. pgserver `[project.optional-dependencies] dev` da e'lon
#     qilingan; CI `pip install -e ".[dev]"` bilan o'rnatadi.
try:
    import pgserver
except ImportError as e:                                        # pragma: no cover
    if os.getenv("CI"):
        raise RuntimeError(
            "pgserver o'rnatilmagan, lekin CI'da cash/tenancy to'plami MAJBURIY. "
            "Uni o'tkazib yuborish CI'ni 4% qamrov bilan yashil qilardi. "
            'Tuzatish: `pip install -e ".[dev]"`.'
        ) from e
    pytest.skip("pgserver yo'q — cash to'plami mahalliy ravishda o'tkazib yuborildi",
                allow_module_level=True)

os.environ.setdefault("DATABASE_URL", "sqlite:///./_pytest.db")  # app import uchun (biz ishlatmaymiz)
os.environ.setdefault("VENDOR_ADMIN_KEY", "test-vendor-key")
os.environ.setdefault("APP_ENV", "dev")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401  (Base.metadata to'liq bo'lishi uchun)
from app.db.base import Base  # noqa: E402
from app.db.cash.deploy import deploy_cash_schema, ensure_phase1_objects  # noqa: E402
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
    """Seans uchun bitta vaqtinchalik PostgreSQL + to'liq sxema.

    ⚠️  TOZALASH ENDI SHU YERDA EMAS. Ilgari `yield` DAN KEYIN `engine.dispose()` va
        `srv.cleanup()` turardi — ikki nuqsoni bilan: (a) ular BITTA `try` da edi,
        ya'ni `dispose()` yiqilsa `cleanup()` ga YETIB BORILMASDI; (b) setup shu
        `yield` gacha yiqilsa (quyida oltita `assert` bor) teardown UMUMAN
        ishlamasdi va server ham, papka ham qolib ketardi. Ustiga `mkdtemp()`
        papkasi HECH QACHON o'chirilmasdi — 2026-09-30 da 59 ta papka (2.57 GB).

        Endi tozalash `tests/conftest.py` dagi `pytest_sessionfinish` da: u seans
        QANDAY tugashidan qat'i nazar ishlaydi va har yaratilgan serverni
        ro'yxatdan to'xtatib, papkasini o'chiradi. `engine.dispose()` esa kerak
        emas — jarayon tugaydi.
    """
    tmp = tempfile.mkdtemp(prefix="cashpg_test_")
    srv = pgserver.get_server(tmp)
    engine = create_engine(_normalize(srv.get_uri()), future=True)
    # Legacy sxema (companies/branches/employees/... ) — cash FK'lari public.* ga tayanadi
    Base.metadata.create_all(engine)
    # Cash sxemasi — legacy yonida, non-destructive
    res = deploy_cash_schema(engine)
    assert res == "deployed", res
    # Phase 1 (SEYF ochilishi) obyektlari — boot bilan AYNI qadam (`initdb._ensure_cash_phase1`).
    # Bu yerda ham chaqirilishi SHART: aks holda test muhiti prod bootdan farq qilardi.
    # Sxema YANGI qurildi -> Phase 1 obyektlari QO'LLANISHI shart ("applied:…").
    # ⚠️  "noop" bu yerda XATO bo'lardi: u «hammasi joyida» degani, holbuki hozirgina
    #     bo'sh sxema qurildi. Shu bois aniq "applied:" talab qilinadi.
    _p1 = ensure_phase1_objects(engine)
    assert _p1.startswith("applied:"), _p1
    # ikkinchi chaqiruv — BARQAROR holat: birorta DDL yubormasligi SHART
    assert ensure_phase1_objects(engine) == "noop"
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
        # Phase 5G FX-A: kassa amali idempotentligi SMENADAN QAT'I NAZAR (`/cash/ops`
        # smenani har so'rovda qayta hal qiladi — smena doirasidagi noyoblik takrorni
        # o'tkazib yuborardi).
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cashmov_client_uuid_all ON cash_movements (client_uuid) WHERE client_uuid IS NOT NULL",
        # ── `index_guard` QO'RIQLAYDIGAN MAJBURIY indekslar ─────────────────────
        #  ⚠️  NEGA SHU YERDA. `create_all` bu indekslarni YARATMAYDI (ular
        #      `initdb._ensure_indexes` da xom DDL), bu conftest esa `initdb` ni
        #      chaqirmaydi. Gard esa kafolat ISBOTLANMAGAN bo'lsa yozuvni RAD etadi —
        #      ya'ni ularsiz test muhiti PRODUCTIONDAN farq qilib, hujjat raqami
        #      oladigan HAR amal (sotuv/qaytarish/xarid/qabul) 409 olardi.
        #      Ro'yxat `initdb._ensure_indexes` bilan IZCHIL bo'lishi shart.
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_counter ON doc_counters (company_id, kind)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_lot_intake_key ON stock_batches (company_id, client_uuid) WHERE client_uuid IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_recv_corr_client ON receiving_corrections (company_id, client_uuid)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_lsr_request_client ON lot_shortfall_resolution_requests (company_id, client_uuid)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_print_jobs_original ON print_jobs (company_id, doc_type, doc_id) WHERE copy = 'ORIGINAL'",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_products_external_identity ON products (company_id, source_system, external_id) WHERE source_system IS NOT NULL AND external_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_import_jobs_snapshot ON import_jobs (company_id, source, snapshot_id) WHERE snapshot_id IS NOT NULL AND status IN ('committing', 'committed')",
        #  ⚠️  Gard `inventory.writeoff` va `cashops._transfer_once` da ham simlangani
        #      uchun QO'SHILDI. Usiz hisobdan chiqarish/ko'chirish shu muhitda 409 olardi
        #      (o'lchangan: `test_return_cash_posting.py::test_HISOBDAN_CHIQARISH_...`).
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_stockmov_client_prod_type ON stock_movements (client_uuid, product_id, type) WHERE client_uuid IS NOT NULL",
        #  ⚠️  Gard `shifts.open_shift` da ham simlangani uchun QO'SHILDI. Usiz shu
        #      muhitda HAR smena ochish 409 olardi (o'lchangan:
        #      `test_sale_shift_expected_cash.py` naqd qaytarish testlari).
        #      Shakli ATAYLAB `REQUIRED_INDEX_DEFINITIONS` da YO'Q (enum predikat
        #      kanonizatsiya bo'lmaydi) — sabab `tests/test_index_wiring_contract.SHAKLSIZ` da.
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_shifts_cashier_open ON shifts (cashier_id) WHERE status = 'open' AND deleted_at IS NULL",
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
        # Phase 1 ATTESTATSIYASI menejer+ rolini talab qiladi (`_factory.manager`).
        # ⚠️  NEGA SHU YERDA, `_factory` ICHIDA EMAS: rolni test PAYTIDA yaratish `roles`
        #     jadvalini seans O'RTASIDA o'zgartirardi, holbuki 30+ test yordamchisi
        #     `db.query(Role).first()` ni TARTIBSIZ ishlatadi — ya'ni birinchi
        #     attestatsiyadan KEYIN qaysi rol qaytishi aniqlanmagan bo'lib qolardi.
        #     Seans boshida (kassirdan KEYIN) yaratilsa, to'plam BUTUN seans davomida
        #     o'zgarmaydi va `.first()` hamma test uchun BIR XIL javob beradi.
        s.add(Role(code="menejer", name="Menejer")); s.flush()
        emp = Employee(company_id=co.id, full_name="Test Kassir", role_id=role.id)
        s.add(emp); s.flush()
        br = Branch(company_id=co.id, code="BR1", name="Filial")
        s.add(br); s.flush()
        s.commit()
        env = CashEnv(engine=engine, company_id=co.id, branch_id=br.id, employee_id=emp.id, now=now)
    yield env


@pytest.fixture
def db(cashenv):
    s = Session(cashenv.engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()
