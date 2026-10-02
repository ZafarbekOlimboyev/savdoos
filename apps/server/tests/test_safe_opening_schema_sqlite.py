# -*- coding: utf-8 -*-
"""Phase 1 — SEYF ochilishi: SQLite QAMROVI (`PHASE1.md` §5, test T-19 SQLite qismi).

`cash` quyi tizimi ATAYLAB faqat PostgreSQL'da: `cash_enabled`,
`require_ledger_writable`, `is_ledger_authoritative` — hammasi ayni qamrov.
Shu bois SQLite'da:

  · boot YASHIL qoladi (Phase 1 qadami no-op);
  · `cash.cash_account_openings` YARATILMAYDI;
  · tayyorlik QIZIL BO'LMAYDI (yolg'on ogohlantirish yo'q);
  · `CashAccountOpening` modeli `Base.metadata.create_all` ga TUSHMAYDI
    (u `CashBase` da — MAP-only).
"""
import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # apps/server
TBL = "cash_account_openings"


def _boot(db_path):
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                       text=True, timeout=900,
                       env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))
    return url, r


def test_sqlite_boot_yashil_va_obyekt_yaratilmaydi(tmp_path):
    url, r = _boot(tmp_path / "p1.db")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    eng = create_engine(url, future=True)
    try:
        names = set(inspect(eng).get_table_names())
        assert TBL not in names, f"SQLite'da {TBL} YARATILDI — cash qamrovi buzildi"
        from app.services.cash import schema_readiness as sr
        assert sr.opening_schema_problems(eng) == [], "SQLite'da YOLG'ON qizil"
        assert sr.opening_schema_ok(eng) is True
    finally:
        eng.dispose()


def test_sqlite_ikkinchi_boot_no_op(tmp_path):
    p = tmp_path / "p1b.db"
    _, r1 = _boot(p)
    assert r1.returncode == 0
    _, r2 = _boot(p)
    assert r2.returncode == 0, (r2.stdout + r2.stderr)[-1200:]


def test_model_app_metadata_ga_tushmaydi():
    """`CashAccountOpening` — `CashBase` da; `Base.metadata.create_all` unga TEGMAYDI."""
    from app.db.base import Base
    from app.models.cash import CashAccountOpening, CashBase
    assert CashAccountOpening.__table__.schema == "cash"
    assert f"cash.{TBL}" in CashBase.metadata.tables
    assert not any(t.name == TBL for t in Base.metadata.tables.values()), \
        "model app Base metadata'siga tushib qolgan — SQLite'da create_all uni quradi"
