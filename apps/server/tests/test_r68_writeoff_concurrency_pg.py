# -*- coding: utf-8 -*-
"""R6.8 P0-1 — HISOBDAN CHIQARISH PARALLEL YOZUVCHILAR, HAQIQIY POSTGRES.

NEGA SQLite YARAMAYDI: unda parallel yozuvchilar fayl qulfida NAVBATGA turadi,
ya'ni «SELECT-keyin-INSERT» oynasi ochilmaydi va mantiq sinalmagan holda
yashil ko'rinadi. Bu yerda AYNI kalit bilan bir vaqtda kelgan so'rovlar
haqiqatan to'qnashadi va yakuniy kafolat BAZA indeksiga tushadi:

    ux_stockmov_client_prod_type (client_uuid, product_id, type)
                                  WHERE client_uuid IS NOT NULL

USHLANADIGAN NUQSON (R6.8 da topilgan, bu faylning manfiy nazorati bilan
o'lchangan): KUZATUVLI mahsulotda harakat qatori `db.flush()` da INSERT
qilinadi (`inventory.py`, `if _plan is not None:` shoxi) va u yagona
`try/except IntegrityError` blokidan TASHQARIDA edi — o'sha blok faqat
`db.commit()` ni o'raydi. Natijada:

  · KUZATUVSIZ mahsulot: INSERT faqat `commit` da -> ikkinchi so'rov
    `duplicate: true` olardi (to'g'ri);
  · KUZATUVLI mahsulot: INSERT `flush` da -> ikkinchi so'rov TUTILMAGAN
    `IntegrityError`, ya'ni **500**. Qo'shni yozuvchilar
    (`/inventory/transfer`, `/inventory/count`) allaqachon qayta urinish
    o'ramiga ega edi, hisobdan chiqarish esa EMAS.

Bu fayl isbotlaydi (har holatda IKKI commit'dan keyin):
  1. kuzatuvSIZ, 4 parallel, AYNI kalit -> qoldiq BIR MARTA kamayadi, bitta
     harakat qatori, aynan bittasi ASL javob;
  2. KUZATUVLI, 4 parallel, AYNI kalit -> 500 YO'Q, qoldiq BIR MARTA
     kamayadi, partiya qoldig'i BIR MARTA kamayadi, allokatsiya qatorlari
     AYNAN bitta harakatga tegishli, tannarx BIR MARTA hisoblanadi;
  3. KUZATUVLI, 2 parallel, BOSHQA kalit, AYNI tana -> biri 200, ikkinchisi
     409 `WRITEOFF_DUPLICATE_SUSPECTED` (darvoza poyga ostida ham ishlaydi);
  4. ikki BOSHQA do'kon, AYNI kalit -> IKKI mustaqil chiqarish (indeks
     global, shu bois ilova doirasi SHART).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
N = 4


#  ⚠️  IKKI NISHON (R6.9 §3). Ilgari bu fayl FAQAT `pgserver` (o'rnatilgan
#      PostgreSQL **16**) da ishlardi va `external` parametri YO'Q edi — shu
#      bois uni CI ning `backend-pg18` job'iga (`-k external`) qo'shib
#      bo'lmasdi: `-k external` hamma testni deselect qilardi.
#
#      Endi `pg_target` (`test_check_defs_pg.py:41`) bilan AYNI naqsh:
#        · `pgserver`  — asosiy `backend` job'ida, PG16;
#        · `external`  — `SAVDOOS_TEST_PG_URL` bo'lsa, ya'ni CI da PG **18**.
#
#      Qulf tartibi, qisman UNIQUE indeks va `IntegrityError` xulqi versiyaga
#      bog'liq emas deb TAXMIN QILINMAYDI — endi ikkalasida ham O'LCHANADI.
_EXTERNAL = os.getenv("SAVDOOS_TEST_PG_URL", "").strip()
_TARGETS = ["pgserver"] + (["external"] if _EXTERNAL else [])


def _psycopg(u: str) -> str:
    for pre in ("postgres://", "postgresql://"):
        if u.startswith(pre) and "+psycopg" not in u:
            return "postgresql+psycopg://" + u[len(pre):]
    return u


def _initdb(url: str) -> None:
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test")
    env.pop("PYTHONIOENCODING", None)
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, timeout=900, env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]


@pytest.fixture(scope="module", params=_TARGETS)
def pg(request):
    if request.param == "pgserver":
        pgserver = pytest.importorskip("pgserver")
        srv = pgserver.get_server(tempfile.mkdtemp())
        url = _psycopg(srv.get_uri())
        _initdb(url)
        eng = create_engine(url)
        try:
            yield eng
        finally:
            eng.dispose()
        return

    #  ⚠️  HAR YURISH O'Z BAZASIDA. Bu fayl global qisman UNIQUE indeksni
    #      (`ux_stockmov_client_prod_type`) o'lchaydi — boshqa testlar bilan
    #      BIR bazani baham ko'rish o'lchovni ifloslantirardi.
    from sqlalchemy.engine import make_url
    from sqlalchemy import text as _text
    admin = make_url(_psycopg(_EXTERNAL))
    dbname = f"r68wo_{uuid.uuid4().hex[:12]}"
    aeng = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with aeng.connect() as con:
            con.execute(_text(f'CREATE DATABASE "{dbname}"'))
        url = admin.set(database=dbname).render_as_string(hide_password=False)
        _initdb(url)
        eng = create_engine(url)
        try:
            yield eng
        finally:
            eng.dispose()
    finally:
        with aeng.connect() as con:
            con.execute(_text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        aeng.dispose()


@pytest.fixture(scope="module")
def Sess(pg):
    # AYNAN production sozlamalari (`db/session.py`).
    return sessionmaker(bind=pg, autoflush=False, expire_on_commit=False, class_=Session)


# ══ FIKSTURALAR ══════════════════════════════════════════════════════════════

def _dokon(Sess, *, qty=100, tracked=False):
    """Kompaniya + filial + ombor xodimi + qoldiqli mahsulot (ixtiyoriy partiya)."""
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Product, Unit
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory, StockBatch
    from app.models.org import Branch, Company
    with Sess() as db:
        co = Company(id=uuid.uuid4(), name="R68W " + uuid.uuid4().hex[:6],
                     code="r68w" + uuid.uuid4().hex[:8], currency="UZS")
        db.add(co)
        db.flush()
        b1 = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="Markaz",
                    is_active=True, timezone="Asia/Tashkent",
                    created_at=NOW - timedelta(days=10))
        db.add(b1)
        db.flush()
        role = db.query(Role).filter(Role.code == "omborchi").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, role_id=role.id,
                     full_name="R68W omborchi",
                     phone="+9987" + str(uuid.uuid4().int)[:8],
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.flush()
        db.add(EmployeeBranch(employee_id=e.id, branch_id=b1.id))
        unit = db.query(Unit).filter(Unit.code == "dona").first() or db.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=co.id, name="R68W " + uuid.uuid4().hex[:6],
                    article_code="R68W-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0,
                    track_lots=tracked)
        db.add(p)
        db.flush()
        db.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b1.id,
                         qty=Decimal(str(qty)), min_qty=0, updated_at=NOW))
        lot_id = None
        if tracked:
            lot = StockBatch(id=uuid.uuid4(), company_id=co.id, product_id=p.id,
                             branch_id=b1.id, received_qty=Decimal(str(qty)),
                             remaining_qty=Decimal(str(qty)), unit_cost=Decimal("50.00"),
                             received_at=NOW, created_at=NOW)
            db.add(lot)
            db.flush()
            lot_id = lot.id
        db.commit()
        return {"cid": co.id, "b1": b1.id, "emp": e.id, "pid": p.id, "lot": lot_id}


def _call(Sess, d, *, cu, qty=2, lots=None, confirm=False):
    """HAQIQIY `POST /inventory/writeoff` — marshrut tanasi AYNAN."""
    from fastapi import HTTPException

    from app.api.v1.inventory import WriteoffIn, writeoff
    from app.models.auth import Employee
    with Sess() as db:
        emp = db.get(Employee, d["emp"])
        body = WriteoffIn(product_id=d["pid"], qty=qty, reason="brak", client_uuid=cu,
                          branch_id=d["b1"], lots=lots, confirm_duplicate=confirm)
        try:
            return ("ok", writeoff(body, emp, db))
        except HTTPException as e:
            db.rollback()
            return ("http", e.status_code, (e.headers or {}).get("X-Error-Code"))
        except Exception as e:                    # noqa: BLE001
            db.rollback()
            return ("error", f"{type(e).__name__}: {e}")


def _race(fns, n):
    """`n` oqim BIR VAQTDA (barrier) ishga tushadi."""
    barrier = threading.Barrier(n)

    def one(i):
        barrier.wait(timeout=60)
        return fns[i]()

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(one, range(n)))


def _qty(Sess, pid, bid):
    from app.models.inventory import Inventory
    with Sess() as db:
        r = db.query(Inventory).filter(Inventory.product_id == pid,
                                       Inventory.branch_id == bid).first()
        return Decimal(str(r.qty)) if r else None


def _moves(Sess, pid):
    from app.models.enums import MovementType
    from app.models.inventory import StockMovement
    with Sess() as db:
        return (db.query(StockMovement)
                .filter(StockMovement.product_id == pid,
                        StockMovement.type == MovementType.writeoff).count())


def _lot_remaining(Sess, lot_id):
    from app.models.inventory import StockBatch
    with Sess() as db:
        return Decimal(str(db.get(StockBatch, lot_id).remaining_qty))


def _allocs(Sess, pid):
    """(allokatsiya qatorlari soni, ular tegishli HARAKATLAR soni, jami miqdor)."""
    from app.models.inventory import StockMovementLotAllocation as A
    from app.models.inventory import StockBatch
    with Sess() as db:
        rows = (db.query(A)
                .join(StockBatch, StockBatch.id == A.stock_batch_id)
                .filter(StockBatch.product_id == pid).all())
        return (len(rows), len({r.stock_movement_id for r in rows}),
                sum((Decimal(str(r.qty)) for r in rows), Decimal("0")))


# ══ 1. KUZATUVSIZ — 4 PARALLEL, AYNI KALIT ═══════════════════════════════════

def test_w1_kuzatuvsiz_4_parallel_ayni_kalit_BITTA_chiqarish(Sess):
    d = _dokon(Sess, qty=100, tracked=False)
    X = uuid.uuid4()
    res = _race([lambda: _call(Sess, d, cu=X, qty=2)] * N, N)

    assert all(r[0] == "ok" for r in res), f"ba'zi oqimlar yiqildi: {res}"
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("98.000"), res
    assert _moves(Sess, d["pid"]) == 1, f"harakat qatori bir martadan ko'p: {res}"
    _fresh = [r for r in res if not (isinstance(r[1], dict) and r[1].get("duplicate"))]
    assert len(_fresh) == 1, f"{len(_fresh)} ta ASL javob (kutilgan 1): {res}"


# ══ 2. KUZATUVLI — 4 PARALLEL, AYNI KALIT (ASOSIY NUQSON) ════════════════════

def test_w2_KUZATUVLI_4_parallel_ayni_kalit_500_YOQ_va_partiya_bir_marta(Sess):
    """⚠️  MANFIY NAZORAT: `inventory.py` dagi `try: db.flush() except _IE:`
    o'rami olib tashlansa oqimlarning bir qismi `error: IntegrityError...`
    (ya'ni 500) qaytaradi va `_moves` 1 bo'lsa ham javob YOLG'ON bo'ladi."""
    d = _dokon(Sess, qty=100, tracked=True)
    X = uuid.uuid4()
    lots = [{"stock_batch_id": str(d["lot"]), "qty": 2}]
    res = _race([lambda: _call(Sess, d, cu=X, qty=2, lots=lots)] * N, N)

    xatolar = [r for r in res if r[0] == "error"]
    assert not xatolar, f"tutilmagan istisno (500) — `flush` o'rami ishlamadi: {xatolar}"
    assert all(r[0] == "ok" for r in res), f"ba'zi oqimlar yiqildi: {res}"

    # Qoldiq BIR MARTA.
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("98.000"), res
    # Harakat qatori BIR.
    assert _moves(Sess, d["pid"]) == 1, res
    # Partiya qoldig'i BIR MARTA kamaygan.
    assert _lot_remaining(Sess, d["lot"]) == Decimal("98.000"), res
    # Allokatsiya qatorlari AYNAN BITTA harakatga tegishli va jami 2.
    qatorlar, harakatlar, jami = _allocs(Sess, d["pid"])
    assert harakatlar == 1, f"allokatsiyalar {harakatlar} ta harakatga tegishli: {res}"
    assert jami == Decimal("2.000"), f"allokatsiya jami {jami}: {res}"
    # Tannarx BIR MARTA: 2 × 50.00 = 100.00 (faqat ASL javobda).
    asl = [r[1] for r in res if isinstance(r[1], dict) and not r[1].get("duplicate")]
    assert len(asl) == 1, f"{len(asl)} ta ASL javob: {res}"
    assert Decimal(str(asl[0]["cost_total"])) == Decimal("100.00"), asl


# ══ 3. BOSHQA KALIT, AYNI TANA — DARVOZA POYGA OSTIDA ════════════════════════

def test_w3_boshqa_kalit_ayni_tana_parallel_BITTA_otadi(Sess):
    """So'nggi-o'xshash darvozasi `created_at` oynasiga tayanadi, ya'ni BIR
    VAQTDA kelgan ikki so'rovning birinchisi hali commit qilmagan bo'lishi
    mumkin. Shunday holatda IKKALASI ham o'tishi MUMKIN — lekin `Inventory`
    qator qulfi ularni ketma-ket qiladi va ikkinchisi birinchisining
    commit'ini KO'RADI.

    ⚠️  SHU BOIS TASDIQ YUMSHOQ: «kamida bittasi 409» DEMAYMIZ, balki
        «qoldiq va partiya BARAVAR» hamda «o'tgan chiqarishlar soni harakat
        qatorlari soniga TENG» deymiz — ya'ni darvoza qancha ushlasa ushlaydi,
        lekin HISOB hech qachon buzilmaydi."""
    d = _dokon(Sess, qty=100, tracked=True)
    lots = [{"stock_batch_id": str(d["lot"]), "qty": 2}]
    res = _race([lambda: _call(Sess, d, cu=uuid.uuid4(), qty=2, lots=lots)] * 2, 2)

    xatolar = [r for r in res if r[0] == "error"]
    assert not xatolar, f"tutilmagan istisno: {xatolar}"
    otgan = [r for r in res if r[0] == "ok"]
    tosilgan = [r for r in res if r[0] == "http"]
    assert len(otgan) + len(tosilgan) == 2, res
    for r in tosilgan:
        assert r[1] == 409 and r[2] == "WRITEOFF_DUPLICATE_SUSPECTED", res

    # HISOB BUZILMAYDI: har o'tgan chiqarish AYNAN bitta harakat va partiya
    # qoldig'i shunga mos kamaygan.
    n = len(otgan)
    assert _moves(Sess, d["pid"]) == n, res
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("100.000") - Decimal(2 * n), res
    assert _lot_remaining(Sess, d["lot"]) == Decimal("100.000") - Decimal(2 * n), res
    _, harakatlar, jami = _allocs(Sess, d["pid"])
    assert harakatlar == n, res
    assert jami == Decimal(2 * n), res


def test_w4_ketma_ket_boshqa_kalit_ayni_tana_IKKINCHISI_409(Sess):
    """Poyga YO'Q holat — aynan P0 ssenariysi: birinchi chiqarish YOZILGAN,
    javob klientga yetmagan, operator YANGI kalit bilan qaytadan yuborgan."""
    d = _dokon(Sess, qty=100, tracked=True)
    lots = [{"stock_batch_id": str(d["lot"]), "qty": 2}]

    r1 = _call(Sess, d, cu=uuid.uuid4(), qty=2, lots=lots)
    assert r1[0] == "ok", r1
    r2 = _call(Sess, d, cu=uuid.uuid4(), qty=2, lots=lots)

    assert r2[0] == "http" and r2[1] == 409, r2
    assert r2[2] == "WRITEOFF_DUPLICATE_SUSPECTED", r2
    assert _moves(Sess, d["pid"]) == 1, "IKKINCHI yozuv qilindi"
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("98.000")
    assert _lot_remaining(Sess, d["lot"]) == Decimal("98.000"), "partiya ikki marta kamaydi"

    # TASDIQLANGAN takror esa O'TADI va ikkinchi yozuv BAJARILADI.
    r3 = _call(Sess, d, cu=uuid.uuid4(), qty=2, lots=lots, confirm=True)
    assert r3[0] == "ok", r3
    assert _moves(Sess, d["pid"]) == 2, r3
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("96.000")
    assert _lot_remaining(Sess, d["lot"]) == Decimal("96.000")


# ══ 4. IKKI IJARACHI, AYNI KALIT — INDEKS GLOBAL ═════════════════════════════

def test_w5_ikki_dokon_ayni_kalit_IKKI_mustaqil_chiqarish(Sess):
    """`ux_stockmov_client_prod_type` da `company_id` YO'Q (`stock_movements`
    da bu ustun umuman yo'q). Ilova qidiruvi `product_id` bilan cheklangani
    uchun boshqa do'konning ayni kaliti BU amalni «dublikat» qilib yutib
    yubormaydi — `product_id` do'konga xos."""
    dA = _dokon(Sess, qty=100, tracked=False)
    dB = _dokon(Sess, qty=100, tracked=False)
    X = uuid.uuid4()
    res = _race([lambda: _call(Sess, dA, cu=X, qty=3),
                 lambda: _call(Sess, dB, cu=X, qty=3)], 2)

    assert all(r[0] == "ok" for r in res), res
    assert _qty(Sess, dA["pid"], dA["b1"]) == Decimal("97.000"), res
    assert _qty(Sess, dB["pid"], dB["b1"]) == Decimal("97.000"), res
    assert _moves(Sess, dA["pid"]) == 1, res
    assert _moves(Sess, dB["pid"]) == 1, res
