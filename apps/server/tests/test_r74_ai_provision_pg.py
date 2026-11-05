"""R7.4 — AI siyosatini PROVISION qilish: baza darajasidagi gard + `paused` qator.

NEGA BU FAYL BOR (R7.3 topilmasi): `app/db/migrations/m2026_10_17_ai_requirement.sql`
ni deploy yo'lida HECH NARSA bajarmaydi — `start.sh` faqat `initdb` + `seed` yurgizadi,
`schema_migrate` reyestri esa faqat UUID migratsiyasini import qiladi. Jadvalni va
uning CHECK cheklovlarini `Base.metadata.create_all` yaratadi (model
`app/models/__init__.py` da ro'yxatdan o'tgan), lekin TRIGGER va ekilgan QATOR
faqat o'sha `.sql` da yashaydi.

Oqibati HAYOTIY: `AR.activate()` → `_load(db, exclusive=True)` → qator yo'q bo'lsa
503. Ya'ni QATOR BO'LMASA AI NI HECH QACHON YOQIB BO'LMAYDI.

Bu testlar AYNAN o'sha qisman holatni (jadval BOR, trigger va qator YO'Q) qayta
yaratadi va `provision()` uni tuzatishini — AI ni YOQMASDAN — isbotlaydi.

⚠️  Fikstura `.sql` ni teardown'da QAYTA qo'llaydi: bu modul trigger'ni olib
    tashlaydi, va `test_ai_requirement_pg.py` ayni bazada ishlaydi.
"""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  — modellarni ro'yxatdan o'tkazadi
from app.core.config import settings
from app.db.base import Base
from app.models.ai_requirement import AiRequirement
from app.services import ai_requirement as AR

MIGRATION = Path(__file__).parents[1] / "app/db/migrations/m2026_10_17_ai_requirement.sql"
TRIGGER = "ai_requirement_revision_guard"


def _apply_sql(engine):
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(MIGRATION.read_text(encoding="utf-8-sig"))


@pytest.fixture(scope="module")
def pgengine():
    url = os.environ.get("P0C_TEST_POSTGRES")
    if not url:
        pytest.skip("Dedicated real PostgreSQL unavailable; provision NOT VERIFIED")
    parsed = make_url(url)
    assert (parsed.host, parsed.port, parsed.username, parsed.database) == (
        "127.0.0.1", 55483, "p0c_local", "p0c_tests"), "Only isolated local test DB allowed"
    eng = create_engine(url, connect_args={
        "options": "-c statement_timeout=8000 -c lock_timeout=4000"})
    Base.metadata.create_all(eng)
    _apply_sql(eng)
    yield eng
    _apply_sql(eng)          # keyingi modullar uchun TIKLASH
    eng.dispose()


@pytest.fixture()
def virgin(pgengine):
    """PRODUCTION-SHAKLIDAGI qisman holat: jadval + CHECK bor, trigger va qator YO'Q.

    Aynan `create_all` dan keyin, `.sql` dan OLDIN qanday bo'lsa — shunday.
    """
    _strip(pgengine)
    yield pgengine
    _apply_sql(pgengine)     # yield'dan KEYIN ham tozalash (izolyatsiya tuzog'i)


def _strip(engine):
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {TRIGGER} ON ai_requirement")
        conn.exec_driver_sql(f"DROP FUNCTION IF EXISTS {TRIGGER}()")
        conn.exec_driver_sql("TRUNCATE ai_requirement")   # TRUNCATE qator trigger'ini qo'zg'atmaydi


def _objects(engine) -> dict:
    with engine.connect() as conn:
        return {
            "trigger": conn.execute(text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid='public.ai_requirement'::regclass"
                " AND NOT tgisinternal AND tgname=:n"), {"n": TRIGGER}).scalar(),
            "function": conn.execute(text(
                "SELECT count(*) FROM pg_proc WHERE proname=:n"), {"n": TRIGGER}).scalar(),
            "rows": conn.execute(text("SELECT count(*) FROM ai_requirement")).scalar(),
        }


def _row(engine):
    with Session(engine) as db:
        return db.scalar(select(AiRequirement).where(AiRequirement.id == 1))


def _seed(engine, **changes):
    args = dict(id=1, revision=1, mode="paused", provider=None, model=None,
                disclosure_version=1, disclosure_id=AR.DISCLOSURE_ID,
                protocol_version=2, dispatch_id=AR.DISPATCH_ID, activated_by="test")
    args.update(changes)
    with Session(engine) as db:
        db.add(AiRequirement(**args))
        db.commit()


# ── 0. IKKI YO'L AJRALIB KETMASLIGI (PG kerak emas) ────────────────────────

def _plpgsql_body(sql: str) -> str:
    """`LANGUAGE plpgsql AS $$ ... $$` orasidagi tanani bo'shliqsiz normallashtiradi."""
    head = sql.index("$$")
    tail = sql.index("$$", head + 2)
    return " ".join(sql[head + 2:tail].split())


def test_PROVISION_SQL_MIGRATSIYA_bilan_AYNI():
    """Gard tanasi ikki joyda: `.sql` faylda va `provision()` ichida.

    Ular AJRALIB KETSA, qo'lda `.sql` yurgizgan baza bilan `--provision`
    yurgizgan baza BOSHQA himoyaga ega bo'lardi — shu test buni to'sadi.
    """
    assert _plpgsql_body(AR._GUARD_FUNCTION_SQL) == _plpgsql_body(
        MIGRATION.read_text(encoding="utf-8-sig"))


def test_PROVISION_ekilgan_QIYMATLAR_sql_bilan_AYNI():
    """`.sql` ning INSERT qatori va `provision()` ning urug'i AYNI bo'lsin."""
    sql = MIGRATION.read_text(encoding="utf-8-sig")
    assert "VALUES (1,1,'paused',NULL,NULL,1," in sql.replace(" ", " ")
    assert f"'{AR.DISCLOSURE_ID}'" in sql
    assert f"'{AR.DISPATCH_ID}'" in sql
    assert f",{AR.PROTOCOL_VERSION}," in sql.replace("'", "").replace(" ", "")


# ── 1. BLOKER MAVJUDLIGI: provision'siz aktivatsiya IMKONSIZ ────────────────

def test_QATOR_YOQ_bolsa_AKTIVATSIYA_IMKONSIZ(virgin):
    """R7.4 ning sababi: `activate` qatorni YARATMAYDI, u faqat CAS qiladi."""
    assert _objects(virgin)["rows"] == 0
    with Session(virgin) as db, pytest.raises(HTTPException) as err:
        AR.activate(db, expected_revision=1, mode="active", provider="gemini",
                    model="synthetic-model", actor="test")
    assert err.value.status_code == 503
    assert err.value.headers["X-Error-Code"] == "AI_REQUIREMENT_UNAVAILABLE"


# ── 2. PROVISION: qatorni ekadi, lekin AI ni YOQMAYDI ───────────────────────

def test_PROVISION_PAUSED_ekadi_va_AI_OCHIQ_qoladi(virgin):
    with Session(virgin) as db:
        out = AR.provision(db, actor="r74-test")
        db.commit()
    assert out["row"] == "SEEDED"
    row = _row(virgin)
    assert (row.revision, row.mode, row.provider, row.model) == (1, "paused", None, None)
    assert (row.disclosure_id, row.disclosure_version) == (AR.DISCLOSURE_ID, 1)
    assert (row.protocol_version, row.dispatch_id) == (AR.PROTOCOL_VERSION, AR.DISPATCH_ID)
    assert row.activated_by == "r74-test"
    # AI HAMON O'CHIQ — fail-closed, faqat xato KODI aniqlashdi.
    with Session(virgin) as db, pytest.raises(HTTPException) as err:
        AR.locked(db)
    assert err.value.status_code == 503
    assert err.value.headers["X-Error-Code"] == "AI_REQUIREMENT_PAUSED"


def test_PROVISION_triggerni_ORNATADI(virgin):
    with Session(virgin) as db:
        AR.provision(db, actor="r74-test")
        db.commit()
    assert _objects(virgin) == {"trigger": 1, "function": 1, "rows": 1}
    # Reviziya sakrashi TAQIQ
    with virgin.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(text("UPDATE ai_requirement SET revision=revision+5"))
    # Orqaga qaytish TAQIQ
    with virgin.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(text("UPDATE ai_requirement SET revision=revision-1"))
    # O'chirish TAQIQ
    with virgin.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(text("DELETE FROM ai_requirement"))


def test_PROVISION_IDEMPOTENT(virgin):
    with Session(virgin) as db:
        first = AR.provision(db, actor="r74-test")
        db.commit()
    with Session(virgin) as db:
        second = AR.provision(db, actor="r74-boshqa")
        db.commit()
    assert first["row"] == "SEEDED" and second["row"] == "ALREADY_PRESENT"
    assert second["guard"] == "ALREADY_PRESENT"
    assert _objects(virgin) == {"trigger": 1, "function": 1, "rows": 1}
    row = _row(virgin)
    assert (row.revision, row.mode, row.activated_by) == (1, "paused", "r74-test")


# ── 3. MAVJUD QATORGA TEGMAYDI ──────────────────────────────────────────────

def test_PROVISION_mavjud_ACTIVE_qatorga_TEGMAYDI(virgin):
    _seed(virgin, revision=7, mode="active", provider="gemini", model="synthetic-model",
          activated_by="egasi")
    with Session(virgin) as db:
        out = AR.provision(db, actor="r74-test")
        db.commit()
    assert out["row"] == "ALREADY_PRESENT"
    row = _row(virgin)
    assert (row.revision, row.mode, row.provider, row.activated_by) == (
        7, "active", "gemini", "egasi")


def test_PROVISION_nokanonik_qatorni_OZGARTIRMAYDI_balki_XABAR_QILADI(virgin):
    _seed(virgin, protocol_version=3)
    with Session(virgin) as db:
        out = AR.provision(db, actor="r74-test")
        db.commit()
    assert out["row"] == "ALREADY_PRESENT"
    assert out["canonical"] is False
    assert _row(virgin).protocol_version == 3      # TEGILMAGAN
    with Session(virgin) as db, pytest.raises(HTTPException) as err:
        AR.locked(db)
    assert err.value.headers["X-Error-Code"] == "AI_WORKER_FENCED"


# ── 4. RELIZ BLOKERINI OCHADI ───────────────────────────────────────────────

def test_PROVISION_dan_KEYIN_AKTIVATSIYA_MUMKIN(virgin, monkeypatch):
    with Session(virgin) as db:
        AR.provision(db, actor="r74-test")
        db.commit()
    with Session(virgin) as db:
        revision = AR.activate(db, expected_revision=1, mode="active", provider="gemini",
                               model="synthetic-model", actor="egasi")
        db.commit()
    assert revision == 2

    # KREDENSIAL YO'Q: aktivatsiyadan KEYIN ham fail-closed. Ya'ni provision + activate
    # o'zi rasmni tashqariga chiqarmaydi — kalit ALOHIDA shart.
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with Session(virgin) as db, pytest.raises(HTTPException) as err:
        AR.locked(db)
    assert err.value.headers["X-Error-Code"] == "AI_CREDENTIAL_UNAVAILABLE"

    # Kalit bor: AI ENDI ishlaydi — reliz blokeri ochildi.
    monkeypatch.setattr(settings, "gemini_api_key", "synthetic-gemini")
    with Session(virgin) as db:
        req = AR.locked(db)
    assert (req.mode, req.provider, req.revision) == ("active", "gemini", 2)
    assert req.credential == "synthetic-gemini"


# ── 5. CLI: rehearse saqlamaydi, commit saqlaydi, siyosat argumentlari RAD ──

def _cli(*argv, url):
    env = dict(os.environ, DATABASE_URL=url)
    return subprocess.run([sys.executable, "-m", "app.tools.ai_requirement", *argv],
                          capture_output=True, text=True, env=env,
                          cwd=str(Path(__file__).parents[1]))


def test_CLI_provision_REHEARSE_saqlamaydi(virgin):
    url = os.environ["P0C_TEST_POSTGRES"]
    r = _cli("--provision", "--actor", "egasi",
             "--expect-system-identifier", _sysid(virgin),
             "--expect-database", "p0c_tests", url=url)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REHEARSED" in r.stdout
    assert _objects(virgin) == {"trigger": 0, "function": 0, "rows": 0}


def test_CLI_provision_COMMIT_saqlaydi(virgin):
    url = os.environ["P0C_TEST_POSTGRES"]
    r = _cli("--provision", "--actor", "egasi", "--commit",
             "--expect-system-identifier", _sysid(virgin),
             "--expect-database", "p0c_tests", url=url)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PROVISIONED" in r.stdout
    assert _objects(virgin) == {"trigger": 1, "function": 1, "rows": 1}
    assert _row(virgin).mode == "paused"


def test_CLI_provision_SIYOSAT_argumentlari_bilan_RAD_ETILADI(virgin):
    url = os.environ["P0C_TEST_POSTGRES"]
    r = _cli("--provision", "--actor", "egasi", "--mode", "active",
             "--expect-system-identifier", _sysid(virgin),
             "--expect-database", "p0c_tests", url=url)
    assert r.returncode != 0
    # ⚠️  Vakuum yashildan himoya: rad etish AYNAN `--provision` qoidasidan kelsin,
    #     argparse'ning «majburiy argument yo'q» xatosidan EMAS.
    assert "--provision" in r.stderr and "--mode" in r.stderr
    assert "required" not in r.stderr
    assert _objects(virgin)["rows"] == 0


def test_CLI_AKTIVATSIYA_imzosi_OZGARMADI(virgin):
    """Regressiya gardi: `--provision` siz eski chaqiruv AYNAN avvalgidek ishlaydi."""
    url = os.environ["P0C_TEST_POSTGRES"]
    _seed(virgin, revision=1, mode="paused")
    r = _cli("--expected-revision", "1", "--mode", "demo", "--actor", "egasi",
             "--confirm-fenced-workers-only", "--commit",
             "--expect-system-identifier", _sysid(virgin),
             "--expect-database", "p0c_tests", url=url)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ACTIVATED revision=2" in r.stdout
    assert _row(virgin).mode == "demo"


def _sysid(engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(
            text("SELECT system_identifier::text FROM pg_control_system()")).scalar())


# ── 6. Kirish validatsiyasi (PG kerak emas — gard ulanishdan OLDIN ishlaydi) ──

def test_PROVISION_bosh_ACTOR_ni_RAD_ETADI():
    """Provenans majburiy: kim provision qilganini qator tashiydi."""
    with pytest.raises(HTTPException) as err:
        AR.provision(object(), actor="   ")
    assert err.value.status_code == 422
    assert err.value.headers["X-Error-Code"] == "AI_REQUIREMENT_INVALID"


def test_PROVISION_POSTGRES_dan_boshqasida_RAD_ETADI():
    """Trigger va `ON CONFLICT` PostgreSQL semantikasiga tayanadi — SQLite'da YO'Q."""
    class Sqlite:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        AR.provision(Sqlite(), actor="egasi")
