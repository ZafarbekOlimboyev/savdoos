"""Pytest sozlamalari — har sinov toza SQLite bazada, seed bilan.

MUHIM: DATABASE_URL app import qilinishidan OLDIN o'rnatiladi (engine import vaqtida yaratiladi).
"""
import os
import pathlib

os.environ.setdefault("DATABASE_URL", "sqlite:///./_pytest.db")
os.environ.setdefault("VENDOR_ADMIN_KEY", "test-vendor-key")
os.environ.setdefault("APP_ENV", "dev")

import pytest  # noqa: E402


def _sqlite_path() -> pathlib.Path:
    """`DATABASE_URL` dagi SQLite fayli — `_pytest.db` ni QATTIQ yozmaslik kerak: parallel
    ishlayotgan ikkinchi pytest (boshqa `DATABASE_URL` bilan) birinchisining bazasini o'chirib
    yuborardi."""
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        p = pathlib.Path(url[len("sqlite:///"):])
        # ⚠️  Faqat `_pytest*` fayli o'chiriladi: tasodifan ishchi bazaga (`savdoos.db`)
        #     qaratilgan DATABASE_URL uni yo'q qilmasin.
        if p.name.startswith("_pytest"):
            return p
    return pathlib.Path("_pytest.db")


@pytest.fixture(scope="session")
def client():
    db = _sqlite_path()
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


# ── UMUMIY BAZA IFLOSLANISHI QO'RIQCHISI (Phase 4A.1) ─────────────────────────
# ⚠️  NEGA. `test_lot_receiving.py::test_TRANSFER_...` seed do'koniga `created_at=NOW`
#     (modul import vaqti — seed filialidan ERTAROQ) bilan ikkinchi filial yozib, uni
#     O'CHIRMASDI. `actor_branch()` eng eski filialni tanlaydi, shu bois KEYINGI fayllarda
#     egа'ning sotuvi qoldig'i yo'q filialga tushardi va `test_lot_foundation.py` faqat
#     fayllar tartibi o'zgarganda qizarardi (da47aa8 dan beri yashirin).
#
#     Qurbon testlar endi o'z mahsulotini yaratadi — ya'ni ular iflos bazani ENDI SEZMAYDI.
#     Shuning uchun ifloslanishning O'ZI shu yerda ushlanadi: partiya/tannarx testlari seed
#     do'konining filiallar to'plamini o'zgartirib qoldirsa, AYNAN o'sha test teardown'da
#     QIZARADI — standart tartibda ham, istalgan tartibda ham.
_FILIAL_QORIQLANADIGAN = ("test_lot_", "test_cost_provenance", "test_return_profit_delta")


def _seed_filiallari():
    from app.db.session import SessionLocal
    from app.models.org import Branch, Company
    db = SessionLocal()
    try:
        c = db.query(Company).order_by(Company.created_at).first()
        if c is None:
            return None
        return sorted(str(b.id) for b in db.query(Branch).filter(Branch.company_id == c.id))
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _seed_filiallari_ozgarmaydi(request):
    fayl = request.node.nodeid.split("::", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
    if not (fayl.startswith(_FILIAL_QORIQLANADIGAN) and "client" in request.fixturenames):
        yield
        return
    request.getfixturevalue("client")
    oldin = _seed_filiallari()
    yield
    keyin = _seed_filiallari()
    assert keyin == oldin, (
        f"{request.node.nodeid} umumiy test bazasidagi seed do'koni FILIALLARINI o'zgartirib "
        f"qoldirdi ({len(oldin or [])} -> {len(keyin or [])}). `actor_branch()` eng eski filialni "
        "tanlaydi — keyingi fayllarning sotuvlari boshqa filialga tushadi. Sinov o'z filialini "
        "`finally` da o'chirsin va `created_at` ni orqaga surmasin.")


# ══════════════════════════════════════════════════════════════════════════════
# HISOBOT OYNASI ICHIDAGI SANA — kalendarga BOG'LANMAGAN
#
# ⚠️  NIMA NOTO'G'RI EDI. `/reports/history/seed` ni ishlatadigan testlar sanani
#     QATTIQ KODLAGAN edi (`05.09.2026`, `12.09.2026`), hisobot esa
#     `?period=month` bilan JORIY oy oynasini so'raydi
#     (`reports.py::_window` -> `nl.replace(day=1)`, do'kon mahalliy zonasida).
#     2026-10-01 dan boshlab sentabr qatori oynadan chiqdi va HAMMA delta 0
#     bo'ldi: 6 ta test BARQAROR qizil bo'lib qoldi (flaky emas — kalendar
#     o'tib ketgani uchun). Bu `main` ning o'zida ham shunday edi.
#
# Yechim: sanani ISHGA TUSHISH PAYTIDAN hisoblash. Ikki kafolat:
#   · `>= oy boshi`  — `_window` oynaning boshini QAMRAB oladi (`sold_at >= start`);
#   · `<= hozir`     — oyna oxiri `hozir + 1s`, ya'ni kelajak qator tushib qolmaydi.
#
# Zona AYNAN hisobot ishlatadigani: `reports.py::_store_tz`. UTC dan hisoblash
# XATO bo'lardi — oy chegarasi atrofida mahalliy sana UTC dan farq qiladi va
# aynan shu farq yuqoridagi nuqsonni keltirib chiqargan edi.
# ══════════════════════════════════════════════════════════════════════════════

def seed_dt_in_window(now_local, hours_back: float = 26.0):
    """Oyna ICHIDAGI vaqt: imkon qadar «kecha», lekin oy boshidan oldin EMAS.

    Sof funksiya — chegara testlari uni istalgan `now_local` bilan chaqiradi
    (`tests/test_seed_window_helper.py`).
    """
    from datetime import timedelta
    month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return max(now_local - timedelta(hours=hours_back), month_start)


def seed_date_in_window(hours_back: float = 26.0) -> str:
    """`/reports/history/seed` formatidagi sana (`DD.MM.YYYY HH:MM:SS`), joriy
    hisobot oynasi ichida kafolatlangan. Do'kon zonasi bazadan o'qiladi."""
    from datetime import datetime, timedelta, timezone

    from app.api.v1.reports import _store_tz
    from app.db.session import SessionLocal
    from app.models.org import Branch

    db = SessionLocal()
    try:
        b = (db.query(Branch).filter(Branch.deleted_at.is_(None))
             .order_by(Branch.created_at).first())
        tz = _store_tz(db, b.company_id) if b else timezone(timedelta(hours=5))
    finally:
        db.close()

    now_local = datetime.now(timezone.utc).astimezone(tz)
    return seed_dt_in_window(now_local, hours_back).strftime("%d.%m.%Y %H:%M:%S")
