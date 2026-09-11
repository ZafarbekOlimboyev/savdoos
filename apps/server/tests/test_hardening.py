# -*- coding: utf-8 -*-
"""POST-DEPLOY HARDENING — muhit ro'yxati, fail-closed migratsiya, tayyorlik, build.

Bu faylning mavzusi bitta: **belgining yo'qligi hech qachon ruxsat bermasin va
jimgina o'tmasin.** Production'da `APP_ENV` umuman o'rnatilmagani sababli katalog
reseti ochiq qolgan edi; shu sinf takrorlanmasligi uchun har bir darvoza shu
yerda qat'iy yozilgan.
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

from app.services import catalog_reset

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══ 1. MUHIT — ANIQ RO'YXAT ═══════════════════════════════════════════════════

@pytest.mark.parametrize("env,platform,want", [
    (None,            None,         False),   # belgi YO'Q -> RAD
    ("",              None,         False),   # bo'sh -> RAD
    ("   ",           None,         False),   # faqat probel -> RAD
    ("production",    None,         False),   # aniq production
    ("prod",          None,         False),
    ("PRODUCTION",    None,         False),   # katta harf ham
    ("  production ", None,         False),   # probel bilan
    ("qwerty",        None,         False),   # NOMA'LUM qiymat -> RAD
    ("devel",         None,         False),   # "dev" ga O'XSHASH, lekin EMAS
    ("dev",           "production", False),   # platforma production desa — RAD
    ("staging",       "production", False),
    ("dev",           None,         True),    # mahalliy dev
    ("test",          None,         True),
    ("staging",       "staging",    True),    # Railway staging
    ("  Staging  ",   "staging",    True),    # normallashtiriladi
])
def test_reset_muhit_royxati(monkeypatch, env, platform, want):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    if env is not None:
        monkeypatch.setenv("APP_ENV", env)
    if platform is not None:
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", platform)
    assert catalog_reset.execution_allowed() is want


def test_ruxsat_YO_QLIKDAN_keltirib_chiqarilmaydi(monkeypatch):
    """Salbiy nazorat: production signallarining yo'qligi ruxsat DEGANI EMAS."""
    for k in ("APP_ENV", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID",
              "RAILWAY_PROJECT_ID", "DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    assert catalog_reset.environment_name() == "unknown"
    assert catalog_reset.platform_environment_name() == "unknown"
    assert catalog_reset.execution_allowed() is False


def test_royxat_ANIQ_uchta(monkeypatch):
    """Ro'yxat kengaysa — bu sinov buni ko'rsatadi (jimgina kengaymasin)."""
    assert catalog_reset.RESET_ALLOWED_ENVS == frozenset({"dev", "test", "staging"})


# ══ 2. MAJBURIY SXEMA — TAYYORLIK ════════════════════════════════════════════

def _pg_url():
    """Bir martalik Postgres (testlarda ishlatiladigan `pgserver`). Yo'q bo'lsa skip."""
    pgserver = pytest.importorskip("pgserver")
    return pgserver


def _normalize(url: str) -> str:
    """`pgserver` `postgresql://` beradi — loyiha esa psycopg (v3) drayverini ishlatadi."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@pytest.fixture()
def pg(tmp_path):
    pgserver = _pg_url()
    srv = pgserver.get_server(str(tmp_path / "pgdata"))
    try:
        yield _normalize(srv.get_uri())
    finally:
        try:
            srv.cleanup()
        except Exception:      # noqa: BLE001
            pass


def test_majburiy_sxema_royxati_initdb_bilan_IZCHIL():
    """`required_schema` va `initdb` bir-biridan ajralib ketmasin."""
    from app.core import required_schema as rs
    from app.initdb import _ADDED_COLUMNS
    added = {(t, c) for t, c, _ in _ADDED_COLUMNS}
    for pair in rs.REQUIRED_COLUMNS:
        assert pair in added, f"{pair} `_ADDED_COLUMNS` da yo'q — migratsiya uni qo'shmaydi"


def test_sxema_TOLIQ_bolsa_tayyorlik_YASHIL(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checks"]["catalog_v2_schema"] is True, body
    assert "missing_schema" not in body, body


def test_USTUN_yetishsa_tayyorlik_QIZIL(pg):
    """Izolyatsiya qilingan bir martalik bazada MAJBURIY ustun o'chiriladi."""
    from app.core import required_schema as rs
    eng = create_engine(pg)
    _ENGINE_URL[eng] = pg
    _build(eng)
    ok, missing = rs.ok(eng)
    assert ok, missing
    with eng.begin() as con:
        con.execute(text("DROP INDEX IF EXISTS ux_products_external_identity"))
        con.execute(text("ALTER TABLE products DROP COLUMN source_system"))
    ok, missing = rs.ok(eng)
    assert ok is False
    assert any("products.source_system" in m for m in missing), missing
    with eng.begin() as con:      # TIKLAYMIZ -> yana yashil
        con.execute(text("ALTER TABLE products ADD COLUMN source_system VARCHAR"))
        con.execute(text("CREATE UNIQUE INDEX ux_products_external_identity "
                         "ON products (company_id, source_system, external_id) "
                         "WHERE source_system IS NOT NULL AND external_id IS NOT NULL"))
    ok, missing = rs.ok(eng)
    assert ok, missing
    eng.dispose()


def test_INDEKS_yetishsa_tayyorlik_QIZIL(pg):
    from app.core import required_schema as rs
    eng = create_engine(pg)
    _ENGINE_URL[eng] = pg
    _build(eng)
    with eng.begin() as con:
        con.execute(text("DROP INDEX ux_import_jobs_snapshot"))
    ok, missing = rs.ok(eng)
    assert ok is False
    assert any("ux_import_jobs_snapshot" in m for m in missing), missing
    eng.dispose()


_ENGINE_URL: dict = {}


def _build(eng):
    """Bir martalik bazada to'liq sxemani yaratadi (`initdb` ning o'zi bilan)."""
    env = dict(os.environ, DATABASE_URL=_ENGINE_URL[eng], APP_ENV="test")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


# ══ 3. FAIL-CLOSED MIGRATSIYA ════════════════════════════════════════════════

def test_1_QATLAM_indeks_DDL_yiqilsa_DARHOL_toxtaydi(pg):
    """`_index()` ning O'Z xato yo'li: DDL yiqilsa ishga tushish DARHOL to'xtaydi.

    Xato `_index` ni ALMASHTIRIB emas, uning ICHIDAGI `text()` ni yiqitib hosil
    qilinadi — shunda `_index` ning haqiqiy `try/except` yo'li ishlaydi. (Ilgari
    `_index` ni butunlay almashtirgan edim: xato unga yetib ham bormasdi va sinov
    BEKORGA o'tardi.)
    """
    env = dict(os.environ, DATABASE_URL=pg, APP_ENV="test")
    inject = (
        "import app.initdb as I" + chr(10) +
        "_text = I.text" + chr(10) +
        "def bad(sql, *a, **k):" + chr(10) +
        "    if 'ux_import_jobs_snapshot' in str(sql):" + chr(10) +
        "        raise RuntimeError('SINOV: DDL yiqildi')" + chr(10) +
        "    return _text(sql, *a, **k)" + chr(10) +
        "I.text = bad" + chr(10) +
        "I.main()" + chr(10)
    )
    r = subprocess.run([sys.executable, "-c", inject], cwd=SRV,
                       capture_output=True, text=True, env=env, timeout=300)
    out = r.stdout + r.stderr
    assert r.returncode != 0, "ishga tushish YIQILMADI: " + out
    assert "MAJBURIY indeks yaratilmadi" in out, out[-1200:]
    assert "ux_import_jobs_snapshot" in out


def test_2_QATLAM_indeks_JIMGINA_yaratilmasa_ham_toxtaydi(pg):
    """`CREATE INDEX IF NOT EXISTS` XATO BERMASDAN hech narsa qilmasligi mumkin.

    Agar indeks nomi bilan bir xil nomli JADVAL mavjud bo'lsa, Postgres `IF NOT
    EXISTS` tufayli jimgina o'tkazib yuboradi — qadam «muvaffaqiyatli» ko'rinadi,
    lekin indeks YO'Q. Aynan shu holat uchun ikkinchi qatlam (yakuniy tekshiruv)
    bor va u ishlashi SHART."""
    eng = create_engine(pg)
    with eng.begin() as con:
        con.execute(text("CREATE TABLE ux_import_jobs_snapshot (x int)"))   # nom BAND
    eng.dispose()
    env = dict(os.environ, DATABASE_URL=pg, APP_ENV="test")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, env=env, timeout=300)
    out = r.stdout + r.stderr
    assert r.returncode != 0, "ishga tushish YIQILMADI: " + out
    assert "majburiy sxema yetishmayapti" in out, out[-1200:]
    assert "ux_import_jobs_snapshot" in out


def test_SQLite_da_yiqilmaydi_musbat_nazorat(tmp_path):
    """Musbat nazorat: mahalliy SQLite mosligi SAQLANADI (yiqitib qo'ymadikmi)."""
    db = str(tmp_path / "x.db").replace("\\", "/")
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db}", APP_ENV="test")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


# ══ 4. BUILD METADATA ════════════════════════════════════════════════════════

def test_tayyorlik_BAZA_YARATMAYDI(tmp_path, monkeypatch):
    """Sog'liq tekshiruvi YON TA'SIR sifatida baza YARATMASLIGI kerak.

    Bu haqiqiy nuqson edi: `ready()` majburiy sxemani so'raganda `inspect(engine)`
    ulanish ochardi va SQLite'da bu baza FAYLINI yaratardi. Sinov to'plamida
    natija 212 ta xato bo'ldi — `_pytest.db` band qolib, sessiya fixture'i uni
    o'chira olmadi. Baza yetib bo'lmasa sxema UMUMAN so'ralmasligi kerak.
    """
    import subprocess
    db = tmp_path / "yaratilmasin.db"
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(db).replace(chr(92), "/"),
               APP_ENV="test")
    code = (
        "from app.api.v1 import health as H" + chr(10) +
        "H._check_db = lambda: (False, False)" + chr(10) +
        "class R: status_code = 200" + chr(10) +
        "b = H.ready(R())" + chr(10) +
        "print(b['checks']['catalog_v2_schema'])" + chr(10)
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=SRV,
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().endswith("False"), r.stdout       # fail-closed
    assert not db.exists(), "sog'liq tekshiruvi BAZA YARATDI — yon ta'sir"


def test_build_metadata_ochiq_va_SIRSIZ(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "staging")
    b = client.get("/api/v1/health").json()["build"]
    assert b["commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert b["environment"] == "test"
    assert b["platform_environment"] == "staging"
    blob = str(client.get("/api/v1/health").json()) + str(
        client.get("/api/v1/health/ready").json())
    # ⚠️  Sirning O'ZI assert xabariga QO'YILMAYDI: pytest yiqilganda ikkala
    #     operandni ham chop etadi, ya'ni sizib chiqish aniqlangan LAHZADA
    #     haqiqiy kalit CI jurnaliga tushardi. Shuning uchun faqat NOM aytiladi.
    for name in ("SECRET_KEY", "VENDOR_ADMIN_KEY", "DATABASE_URL"):
        secret = os.getenv(name)
        if secret:
            assert secret not in blob, f"{name} javobda CHIQIB KETDI"
    assert "password" not in blob.lower() and "postgresql://" not in blob


def test_XATO_matni_OMMAVIY_javobga_TUSHMAYDI(monkeypatch, client):
    """Drayver xatosi matni `/health/ready` javobiga CHIQMASLIGI shart.

    `missing()` ilgari `str(e)` ni ro'yxatga qo'shardi. Postgres'da bunday matn
    ichida host, IP, port, baza foydalanuvchisi va to'liq reflection SQL bo'ladi —
    va bu AVTORIZATSIYASIZ endpointga chiqardi.
    """
    from app.core import required_schema as rs

    SIR = "host=maxfiy-host.internal user=maxfiy_user port=5432"

    class _Boom:
        def get_table_names(self):
            raise RuntimeError(SIR)

    monkeypatch.setattr(rs, "inspect", lambda bind: _Boom())
    out = rs.missing(object())
    assert out == ["introspeksiya yiqildi"], out
    assert not any(SIR in m for m in out), "XATO MATNI chiqib ketdi"


def test_production_da_obyekt_NOMLARI_chiqmaydi(monkeypatch, client):
    """Production'da javobda faqat SON bo'ladi, nomlar EMAS."""
    from app.api.v1 import health as H
    monkeypatch.setattr(H, "_check_db", lambda: (True, True))
    monkeypatch.setenv("APP_ENV", "production")
    import app.core.required_schema as rs
    monkeypatch.setattr(rs, "ok", lambda b: (False, ["indeks yo'q: ux_import_jobs_snapshot"]))

    class R:
        status_code = 200
    body = H.ready(R())
    assert "missing_schema" not in body, body
    assert body["missing_schema_count"] == 1, body
    monkeypatch.setenv("APP_ENV", "staging")
    body = H.ready(R())
    assert body["missing_schema"] == ["indeks yo'q: ux_import_jobs_snapshot"], body


def test_build_SHA_OYLAB_TOPILMAYDI(client, monkeypatch):
    """Platforma bermasa — `None`. Yolg'on SHA ko'rsatilmasin."""
    for k in ("RAILWAY_GIT_COMMIT_SHA", "RAILWAY_GIT_COMMIT", "SOURCE_COMMIT",
              "GIT_COMMIT", "APP_COMMIT_SHA"):
        monkeypatch.delenv(k, raising=False)
    assert client.get("/api/v1/health").json()["build"]["commit"] is None


def test_ready_ham_build_beradi(client):
    assert "build" in client.get("/api/v1/health/ready").json()
