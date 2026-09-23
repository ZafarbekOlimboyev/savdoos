# -*- coding: utf-8 -*-
"""Stsenariy urug'lashining XAVFSIZLIK darvozasi — bazasiz, sof funksiya sinovi.

    apps/server/.venv/Scripts/python -m pytest e2e/mobile/test_scenario_guard.py -q -p no:cacheprovider

`refusal_reasons` production'ni (sysid / APP_ENV / platforma) va noaniq maqsadni RAD etishi,
ruxsat esa faqat ANIQ dev/test/staging + Postgres + yangi `e2e*` do'kon kodida berilishi shart.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scenario as SC  # noqa: E402

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


def test_telefonlar_deterministik_va_ozaro_farqli():
    a = [SC.phone_for("e2emob", i) for i in range(1, 6)]
    assert a == [SC.phone_for("e2emob", i) for i in range(1, 6)]
    assert len(set(a)) == 5 and all(p.startswith("+99899") and len(p) == 13 for p in a)
    assert SC.phone_for("e2emob", 1) != SC.phone_for("e2emob0919", 1)


def test_tarozi_yorligi_POS_formati():
    code = SC.scale_code(4121, 1234)
    assert len(code) == 13 and code.startswith("2004121" "01234")
    assert int(code[1:7]) == 4121 and int(code[7:12]) == 1234
    assert SC.ean13("400638133393") == "4006381333931"      # ma'lum EAN-13 namunasi
