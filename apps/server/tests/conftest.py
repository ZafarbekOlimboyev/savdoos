"""Pytest sozlamalari — har sinov toza SQLite bazada, seed bilan.

MUHIM: DATABASE_URL app import qilinishidan OLDIN o'rnatiladi (engine import vaqtida yaratiladi).
"""
import os
import pathlib

os.environ.setdefault("DATABASE_URL", "sqlite:///./_pytest.db")
os.environ.setdefault("VENDOR_ADMIN_KEY", "test-vendor-key")
os.environ.setdefault("APP_ENV", "dev")

import pytest  # noqa: E402


# ══ VAQTINCHALIK PostgreSQL KLASTERLARI — KAFOLATLANGAN TOZALASH ═════════════
#
# ⚠️  MUAMMO (o'lchangan, taxmin emas). `pgserver.get_server(...)` 15 faylda 20 marta
#     chaqiriladi; ulardan 11 tasida `cleanup()` UMUMAN yo'q, 4 tasi esa
#     `tempfile.mkdtemp()` ishlatadi — pytest u papkani HECH QACHON tozalamaydi
#     (`tmp_path_factory` dan farqli). Natija: 2026-09-30 da 59 ta `cashpg_test_*`
#     papka (2.57 GB), `pytest-of-Developer` da 15.4 GB va 391 ta yetim
#     `postgres.exe` to'plandi — disk to'lib, to'liq regressiya
#     `OSError: [Errno 28] No space left on device` bilan yiqildi.
#
# ⚠️  NEGA HAR FAYLNI TUZATISH EMAS. 15 faylni tahrirlash kattaroq o'zgarish bo'lardi
#     va YANGI chaqiruv joyi qo'shilganda muammo QAYTARDI. Bu yerda `get_server`
#     BIR MARTA o'raladi: har yaratilgan server RO'YXATGA olinadi va seans oxirida
#     `pytest_sessionfinish` da to'xtatiladi. Yangi chaqiruv joylari ham AVTOMATIK
#     qamraladi.
#
# ⚠️  NEGA `pytest_sessionfinish`. U seans qanday tugashidan QAT'I NAZAR ishlaydi:
#     muvaffaqiyat, assertion, istisno, fikstura setup xatosi va teardown xatosi.
#     Fikstura ichidagi `try/finally` esa FAQAT o'sha fikstura `yield` ga yetgan
#     bo'lsa yordam beradi — setup o'rtasida yiqilsa yordam bermaydi.
_PG_SERVERS: list = []


def _install_pgserver_tracker() -> None:
    try:
        import pgserver
    except ImportError:
        return                      # pgserver yo'q muhit (masalan faqat SQLite)
    if getattr(pgserver, "_savdoos_tracked", False):
        return
    _orig = pgserver.get_server

    def _tracked(path, *a, **kw):
        try:
            srv = _orig(path, *a, **kw)
        except BaseException:
            #  ⚠️  KONSTRUKTOR SERVERNI KO‘TARIB, KEYIN YIQILISHI MUMKIN
            #      (`pg_ctl` timeout’i, nolga teng bo‘lmagan chiqish, yarim
            #      yozilgan `postmaster.pid`). O‘shanda `get_server` QAYTMAYDI
            #      va quyidagi ro‘yxatga olish HECH QACHON bajarilmaydi — ya’ni
            #      ko‘tarilgan postmaster na job obyektiga, na tozalash
            #      ro‘yxatiga tushadi. Shu bois EGALIK SHARTLARI bajarilsa
            #      klasterni shu yerda egallaymiz va istisnoni O‘ZGARTIRMASDAN
            #      qayta ko‘taramiz.
            try:
                from tests import pgown
                if pgown.adopt(path):
                    print(f"[pgown] get_server yiqildi, lekin klaster ko‘tarilgan "
                          f"— egallandi: {path}")
            except Exception as e2:      # noqa: BLE001
                print(f"[pgown] egallab bo‘lmadi ({path}): {e2}")
            raise
        _PG_SERVERS.append((srv, str(path)))
        #  ⚠️  EGALIK BILAN KUZATISH. `_PG_SERVERS` faqat seans OXIRIDA yordam
        #      beradi; `pgown.track` esa postmaster'ni DARHOL Windows job
        #      obyektiga qo'shadi, ya'ni pytden processi QATTIQ o'lsa ham
        #      (`taskkill /F`, `os._exit`) OS job a'zolarini o'zi tugatadi.
        #      O'lchangan: usiz qattiq o'lim 1 yetim postmaster + 5 bola qoldiradi.
        try:
            from tests import pgown
            pgown.track(srv, path)
        except Exception as e:      # noqa: BLE001 — kuzatuv testlarni buzmasin
            print(f"[pgown] kuzatib bo'lmadi ({path}): {e}")
        return srv

    pgserver.get_server = _tracked
    pgserver._savdoos_tracked = True


_install_pgserver_tracker()


def pytest_sessionfinish(session, exitstatus):
    """Seans oxirida HAR vaqtinchalik PG klasterini to'xtatadi va papkasini o'chiradi.

    ⚠️  HAR QADAM ALOHIDA `try`: `cleanup()` yiqilsa ham `rmtree` bajarilishi SHART
        (eski kodda ikkisi bitta `try` da edi — birinchisi yiqilsa ikkinchisiga
        YETIB BORILMASDI va papka diskda qolardi).
    ⚠️  FAQAT O'ZIMIZ YARATGANLARI: ro'yxat shu seansda `get_server` qaytargan
        obyektlardan iborat — begona jarayon yoki papkaga TEGILMAYDI.
    """
    import shutil
    #  ⚠️  AVVAL EGALIK BILAN TO'XTATISH. `pgown.cleanup_all` har klaster uchun
    #      odobli `srv.cleanup()` ni VAQT CHEGARASI bilan chaqiradi, keyin
    #      EGALIGI ISBOTLANGAN process daraxti hamon tirik bo'lsa uni o'zi
    #      to'xtatadi. Nega kerak (o'lchangan):
    #        · `pgserver._cleanup` refcount yozuvini ISH BAJARILISHIDAN OLDIN
    #          o'chiradi, shu bois u yerdagi HAR QANDAY istisno serverni
    #          to'xtatmasdan qoldiradi va `atexit` qayta urinishi ham JIM
    #          erta qaytadi (chiqish kodi 0 — oqish KO'RINMAYDI);
    #        · `.handle_pids.json` da o'lgan eganing pid'i qolsa AYNI natija;
    #        · `pg_ctl -w stop` timeout'siz va butun foydalanuvchi uchun BITTA
    #          global qulf ostida — u cheksiz bloklanishi mumkin.
    try:
        from tests import pgown
        h = pgown.cleanup_all()
        if any(h.values()):
            print(f"[pgown] odobli={h['odobli']} majburiy={h['majburiy']} "
                  f"qolgan={h['qolgan']} papka={h['papka']} "
                  f"tegilmadi={h['tegilmadi']}")
    except Exception as e:      # noqa: BLE001
        print(f"[pgown] cleanup_all yiqildi: {e}")

    #  ⚠️  ZAXIRA YO'L SAQLANADI: `pgown` kuzatmagan server bo'lsa (masalan
    #      `pgserver.get_server` dan tashqari yaratilgan) bu yerda tozalanadi.
    #      `pgown.cleanup_all` allaqachon to'xtatganlari uchun bu bosqich
    #      zararsiz: `cleanup()` ikkinchi marta jim qaytadi.
    stopped = removed = 0
    while _PG_SERVERS:
        srv, path = _PG_SERVERS.pop()
        try:
            srv.cleanup()
            stopped += 1
        except Exception as e:      # noqa: BLE001
            print(f"[pgtmp] cleanup() yiqildi ({path}): {e}")
        try:
            if path and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except Exception as e:      # noqa: BLE001
            print(f"[pgtmp] papkani o'chirib bo'lmadi ({path}): {e}")
    if stopped or removed:
        print(f"[pgtmp] vaqtinchalik PG: {stopped} to'xtatildi, {removed} papka o'chirildi")


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
