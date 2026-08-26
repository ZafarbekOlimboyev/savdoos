"""Pytest sozlamalari — har sinov toza SQLite bazada, seed bilan.

MUHIM: DATABASE_URL app import qilinishidan OLDIN o'rnatiladi (engine import vaqtida yaratiladi).
"""
import os
import pathlib

os.environ.setdefault("DATABASE_URL", "sqlite:///./_pytest.db")
os.environ.setdefault("VENDOR_ADMIN_KEY", "test-vendor-key")
os.environ.setdefault("APP_ENV", "dev")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    db = pathlib.Path("_pytest.db")
    if db.exists():
        db.unlink()
    from app import initdb, seed
    initdb.main()
    seed.run()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c
    try:
        db.unlink()
    except OSError:
        pass


@pytest.fixture
def admin_headers(client):
    r = client.post("/api/v1/auth/login/password", json={"phone": "+998901234567", "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Har sinovdan oldin login urinishlar sanog'ini tozalaymiz (in-memory)."""
    from app.api.v1 import auth
    auth._ATTEMPTS.clear()
    yield
