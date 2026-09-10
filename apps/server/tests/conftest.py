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
def _reset_rate_limit(request):
    """Har sinovdan oldin login urinishlar sanog'ini tozalaymiz.

    Kassir ham, vendor ham endi BAZADA sanaydi (umumiy holat, deploy'dan omon
    qoladi va instanslar o'rtasida bo'linadi). Testlar ataylab ko'p xato hosil qiladi va ular bir seansda
    to'planib, keyingi testlarni 429 bilan yiqitardi — shu bois ikkalasi ham
    tozalanadi."""

    # ⚠️  Bazaga FAQAT `client` ishlatilgan testlarda tegamiz. Ilgari bu yerda
    #     shartsiz `SessionLocal()` ochilardi — u `client` fixture'idan OLDIN
    #     ishga tushib, SQLite fayliga ulanishni pool'da ushlab qolardi. Windows'da
    #     ochiq fayl o'chirilmaydi, shuning uchun `client` ning `_pytest.db` ni
    #     tozalash qadami `PermissionError` bilan yiqilar va butun to'plam
    #     qulardi. Cash testlari o'z pgserver'ini ishlatadi va bu tozalashga
    #     umuman muhtoj emas.
    if "client" in request.fixturenames:
        request.getfixturevalue("client")    # baza tayyor bo'lishini kafolatlaydi
        from app.db.session import SessionLocal
        from app.models.security import AuthAttempt
        from app.models.vendor import VendorAuthAttempt
        db = SessionLocal()
        try:
            # Kassir yo'li ham endi BAZADA sanaydi (jarayon xotirasida emas) —
            # testlar ataylab ko'p xato hosil qiladi va ular bir seansda
            # to'planib keyingi testlarni 429 bilan yiqitardi.
            db.query(VendorAuthAttempt).delete()
            db.query(AuthAttempt).delete()
            db.commit()
        finally:
            db.close()
    yield
