# -*- coding: utf-8 -*-
"""Stsenariy urug'lashining XAVFSIZLIK darvozasi — bazasiz, sof funksiya sinovi.

    apps/server/.venv/Scripts/python -m pytest e2e/mobile/test_scenario_guard.py -q -p no:cacheprovider

`refusal_reasons` production'ni (sysid / APP_ENV / platforma) va noaniq maqsadni RAD etishi,
ruxsat esa faqat ANIQ dev/test/staging + Postgres + yangi `e2e*` do'kon kodida berilishi shart.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_e2e as RE  # noqa: E402
import scenario as SC  # noqa: E402
import start_backend as SB  # noqa: E402

PG = {"dialect": "postgresql", "system_identifier": "7000000000000000001", "database": "e2e"}
PROD = {**PG, "system_identifier": "7674898282858840119"}
URL = "postgresql+psycopg://x@localhost/e2e"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)


def _r(**kw):
    kw.setdefault("identity", PG)
    return SC.refusal_reasons(URL, **kw)


def test_ruxsat_dev_test_postgres_yangi_e2e_kodi():
    assert _r(tenant_code="e2emob") == []


@pytest.mark.parametrize("env", [None, "", "production", "prod", "PRODUCTION", "unknown", "demo"])
def test_APP_ENV_aniq_bolmasa_RAD(monkeypatch, env):
    if env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", env)
    assert any("APP_ENV" in r for r in _r(tenant_code="e2emob"))


def test_production_sysid_HAR_DOIM_RAD_hatto_APP_ENV_test_bilan():
    bad = _r(identity=PROD, tenant_code="e2emob")
    assert any("PRODUCTION klasteri" in r for r in bad), bad


def test_migratsiya_darvozasidagi_HAR_production_sysid_RAD():
    """Ro'yxat bitta joyda kengaysa (guard.py), stsenariy ham uni avtomatik rad etadi."""
    sys.path.insert(0, str(SC.SERVER_DIR))
    from app.db.migrations.guard import PRODUCTION_SYSTEM_IDENTIFIERS
    assert PRODUCTION_SYSTEM_IDENTIFIERS
    for sysid in PRODUCTION_SYSTEM_IDENTIFIERS:
        bad = _r(identity={**PG, "system_identifier": sysid}, tenant_code="e2emob")
        assert any("PRODUCTION klasteri" in r for r in bad), (sysid, bad)


@pytest.mark.parametrize("platform", ["production", "prod"])
def test_platforma_production_RAD(monkeypatch, platform):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", platform)
    assert any("platforma" in r for r in _r(tenant_code="e2emob"))


def test_sqlite_RAD_kassa_custody_faqat_postgres():
    assert any("Postgres emas" in r for r in _r(identity={"dialect": "sqlite"}, tenant_code="e2emob"))


def test_staging_ANIQ_maqsad_talab_qiladi(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    assert any("MAJBURIY" in r for r in _r(tenant_code="e2emob0919"))
    assert any("kutilgan baza" in r for r in _r(tenant_code="e2emob0919", expect_system_identifier="123"))
    assert _r(tenant_code="e2emob0919", expect_system_identifier=PG["system_identifier"]) == []


@pytest.mark.parametrize("code", ["fayzan1", "demo", "mob", "e2e-mob", "e2e mob", "E2Emob"])
def test_dokon_kodi_faqat_ajratilgan_e2e_prefiksi(code):
    assert any("do'kon kodi" in r for r in _r(tenant_code=code)), code


# ══ ISHGA TUSHIRGICHLAR: darvoza env'ga TEGILMAGAN holatda ishlashi shart ════
#
# Sof funksiya (`refusal_reasons`) APP_ENV yo'qligini rad etadi — lekin buni
# HAQIQIY yo'lda ham qilishi kerak: agar ishga tushirgich darvozadan OLDIN
# APP_ENV='test' qo'yib qo'ysa, himoya hech qachon ishlamaydi.

def _no_db(monkeypatch, *, identity=None):
    """Bazaga ulanmaydigan identitet + do'kon tekshiruvi darvozadan keyin."""
    monkeypatch.setattr(SC, "database_identity", lambda url: dict(identity or PG))


def _spy_gate(monkeypatch, seen: dict):
    real = SC.assert_allowed

    def spy(url, **kw):
        seen["APP_ENV"] = os.environ.get("APP_ENV")
        seen["DATABASE_URL"] = os.environ.get("DATABASE_URL")
        return real(url, **kw)

    monkeypatch.setattr(SC, "assert_allowed", spy)


def test_start_backend_darvozani_env_TEGILMAGAN_holatda_ishlatadi(monkeypatch, tmp_path):
    """`APP_ENV` yo'q: ishga tushirgich uni O'ZI qo'ymasin — RAD etsin."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@localhost/e2e")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    seen: dict = {}
    _no_db(monkeypatch)
    _spy_gate(monkeypatch, seen)

    def never(*a, **kw):  # noqa: ANN002, ANN003
        raise AssertionError("darvozadan keyin ham davom etdi")

    monkeypatch.setattr(SC, "tenant_exists", never)
    monkeypatch.setattr(SC, "seed", never)

    rc = SB.main(["--port", "0", "--manifest", str(tmp_path / "m.json")])
    assert rc == 3, "APP_ENV'siz ishga tushirish RAD etilishi kerak"
    assert seen["APP_ENV"] is None, "darvoza APP_ENV O'RNATILGANDAN KEYIN ishlagan"
    assert os.environ.get("APP_ENV") is None, "rad etilgan yurish env'ni o'zgartirib ketdi"


def test_start_backend_production_klasterini_RAD_etadi(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@localhost/e2e")
    _no_db(monkeypatch, identity=PROD)
    monkeypatch.setattr(SC, "tenant_exists", lambda *a, **kw: False)
    assert SB.main(["--port", "0", "--manifest", str(tmp_path / "m.json")]) == 3


def test_prepare_env_APP_ENV_ni_hech_qachon_qoymaydi(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    SB._prepare_env("postgresql+psycopg://x@localhost/e2e")
    assert os.environ.get("APP_ENV") is None, "_prepare_env APP_ENV'ni to'ldirmasin"
    assert os.environ["DATABASE_URL"].endswith("/e2e")
    assert len(os.environ["SECRET_KEY"]) >= 32


def test_run_e2e_APP_ENV_yoq_bolsa_backendni_ishga_TUSHIRMAYDI(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)

    def never(*a, **kw):  # noqa: ANN002, ANN003
        raise AssertionError("backend ishga tushirildi — darvoza ishlamadi")

    monkeypatch.setattr(RE.subprocess, "Popen", never)
    monkeypatch.setattr(RE, "_healthy", never)
    assert RE.main([]) != 0
    assert os.environ.get("APP_ENV") is None


@pytest.mark.parametrize("env", ["test", "dev", "staging"])
def test_run_e2e_ANIQ_muhitni_ozgartirmaydi(monkeypatch, env, tmp_path):
    """Ruxsat etilgan APP_ENV — darvozadan o'tadi va QAYTA yozilmaydi."""
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setattr(RE, "RUN", tmp_path / "run")  # haqiqiy .run/ papkasiga tegmaymiz
    calls: dict = {}

    def fake_popen(cmd, **kw):  # noqa: ANN001, ANN003
        calls["env"] = kw["env"].get("APP_ENV")
        raise SystemExit(0)  # bu yerdan narisiga sinov kerak emas

    monkeypatch.setattr(RE.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(RE, "_healthy", lambda base: False)
    with pytest.raises(SystemExit):
        RE.main([])
    assert calls["env"] == env


def test_telefonlar_deterministik_va_ozaro_farqli():
    a = [SC.phone_for("e2emob", i) for i in range(1, 6)]
    assert a == [SC.phone_for("e2emob", i) for i in range(1, 6)]
    assert len(set(a)) == 5 and all(p.startswith("+99899") and len(p) == 13 for p in a)
    assert SC.phone_for("e2emob", 1) != SC.phone_for("e2emob0919", 1)


def test_tarozi_yorligi_POS_formati():
    code = SC.scale_code(4121, 1234)
    assert len(code) == 13 and code.startswith("27" "04121" "01234")
    assert code[:2] == "27" and code[2:7] == "04121" and int(code[7:12]) == 1234
    assert SC.ean13(code[:12]) == code            # nazorat raqami endi TEKSHIRILADI
    assert SC.ean13("400638133393") == "4006381333931"      # ma'lum EAN-13 namunasi
