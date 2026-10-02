# -*- coding: utf-8 -*-
"""P9-05 — ONLAYN SAVDONING POYGALARI, HAQIQIY POSTGRES.

ASL TOPILMA (mustaqil QA, BINOS-QA-P9-05, P0):
  «`close_shift` Shift'ni FOR UPDATE bilan qulflaydi va `expected_cash` ni muzlatadi,
   savdo yo'li esa yopilgan holatga REAKSIYA QILMAYDI. READ COMMITTED'da: savdo tx
   smena=open o'qiydi -> close tx qulf oladi, muzlatadi, commit -> savdo tx keyin
   commit -> savdo YOPIQ smenada, muzlatilgan expected'dan TASHQARIDA.»

PHASE 3A NIMANI YOPGAN: smena qatori endi `FOR NO KEY UPDATE` + `populate_existing()`
bilan qayta o'qiladi, ya'ni holat O'QISHI izchil (eskirgan ORM nusxasi yo'q) va
`close_shift` ning `FOR UPDATE` i bilan o'zaro istisno bor.

NIMA OCHIQ QOLGAN: qulfdan keyin HOLAT bo'yicha QAROR yo'q. Agar `close_shift` qulfni
BIRINCHI olsa, savdo keyin qulfni oladi, CLOSED ni ko'radi — va baribir davom etadi.

⚠️  NEGA FAQAT POSTGRES: SQLite'da yozuvchilar fayl qulfida navbatga turadi, ya'ni bu
    oyna umuman ochilmaydi va mantiq sinalmagan holda yashil ko'rinardi.

⚠️  OFFLINE replay (`honor_price_snapshot`) shoxi ATAYLAB yopilgan smenaga bog'lanadi
    (Phase 3A Case C / LATE_SYNC, ega tomonidan ratifikatsiya qilingan) — bu fayl unga
    TEGMAYDI va uni alohida sinov bilan QO'RIQLAYDI.
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
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def pg():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp())
    u = srv.get_uri()
    url = ("postgresql+psycopg://" + u[len("postgresql://"):]
           if u.startswith("postgresql://") and "+psycopg" not in u else u)
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test")
    env.pop("PYTHONIOENCODING", None)
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, timeout=900, env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    eng = create_engine(url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def Sess(pg):
    # AYNAN production sozlamalari (`db/session.py`): identity-map tuzoqlari saqlanadi.
    return sessionmaker(bind=pg, autoflush=False, expire_on_commit=False, class_=Session)


# ══ FIKSTURA ════════════════════════════════════════════════════════════════

def _dokon(Sess, *, qty=1000, kassirlar=1):
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Product, Unit
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    with Sess() as db:
        co = Company(id=uuid.uuid4(), name="P905 " + uuid.uuid4().hex[:6],
                     code="p905" + uuid.uuid4().hex[:8], currency="UZS")
        db.add(co)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="Markaz",
                    is_active=True, created_at=NOW - timedelta(days=10))
        db.add(br)
        db.flush()
        role = db.query(Role).filter(Role.code == "kassir").one()
        emps = []
        for i in range(kassirlar):
            e = Employee(id=uuid.uuid4(), company_id=co.id, role_id=role.id,
                         full_name=f"P905 kassir {i}",
                         phone="+9985" + str(uuid.uuid4().int)[:8],
                         status=EmployeeStatus.active, sec_epoch=0)
            db.add(e)
            db.flush()
            db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id))
            emps.append(e.id)
        unit = db.query(Unit).filter(Unit.code == "dona").first() or db.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=co.id, name="P905 " + uuid.uuid4().hex[:6],
                    article_code="P905-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0,
                    track_lots=False)
        db.add(p)
        db.flush()
        db.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=br.id,
                         qty=Decimal(str(qty)), min_qty=0, updated_at=NOW))
        db.commit()
        return {"cid": co.id, "bid": br.id, "emps": emps, "emp": emps[0], "pid": p.id}


def _open_shift(Sess, d, emp_id=None):
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    with Sess() as db:
        sh = Shift(id=uuid.uuid4(), branch_id=d["bid"], cashier_id=(emp_id or d["emp"]),
                   opened_at=NOW - timedelta(hours=1), opening_cash=Decimal("0"),
                   status=ShiftStatus.open)
        db.add(sh)
        db.commit()
        return sh.id


def _sell(Sess, d, *, cu=None, emp_id=None, qty=1, price=100, method="cash"):
    """HAQIQIY onlayn savdo (`POST /sales` xizmati, `at=None`)."""
    from fastapi import HTTPException

    from app.models.auth import Employee
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    with Sess() as db:
        emp = db.get(Employee, emp_id or d["emp"])
        body = SaleCreate(client_uuid=cu, payment_method=method,
                          items=[{"product_id": d["pid"], "qty": qty, "unit_price": price}],
                          given_amount=qty * price)
        try:
            s = create_sale(db, emp, body)
            db.commit()
            return ("ok", s.id, s.shift_id)
        except HTTPException as e:
            db.rollback()
            return ("http", e.status_code, (e.headers or {}).get("X-Error-Code"))
        except Exception as e:                    # noqa: BLE001
            db.rollback()
            return ("error", f"{type(e).__name__}: {e}")


def _close(Sess, d, sid, counted=0):
    """HAQIQIY `close_shift` (`FOR UPDATE` + expected muzlatish)."""
    from fastapi import HTTPException

    from app.api.v1.shifts import CloseShift, close_shift
    from app.models.auth import Employee
    with Sess() as db:
        emp = db.get(Employee, d["emp"])
        try:
            return ("ok", close_shift(sid, CloseShift(counted_cash=counted), emp, db))
        except HTTPException as e:
            db.rollback()
            return ("http", e.status_code)


def _shift(Sess, sid):
    from app.models.shifts import Shift
    with Sess() as db:
        s = db.get(Shift, sid)
        return {"status": s.status.value if hasattr(s.status, "value") else str(s.status),
                "expected": Decimal(str(s.expected_cash)) if s.expected_cash is not None else None,
                "counted": Decimal(str(s.counted_cash)) if s.counted_cash is not None else None,
                "difference": Decimal(str(s.difference)) if s.difference is not None else None}


def _sales_in_shift(Sess, sid):
    from app.models.sales import Sale
    with Sess() as db:
        return db.query(Sale).filter(Sale.shift_id == sid).all()


def _cash_in_shift(Sess, sid):
    """Smenaga bog'langan savdolarning NAQD to'lovlari yig'indisi."""
    with Sess() as db:
        return Decimal(str(db.execute(text(
            "SELECT COALESCE(SUM(sp.amount),0) FROM sale_payments sp "
            "JOIN sales s ON s.id = sp.sale_id "
            "WHERE s.shift_id = :sid AND sp.method_code = 'cash'"),
            {"sid": str(sid)}).scalar()))


def _counts(Sess, d):
    from app.models.inventory import StockMovement
    from app.models.sales import Sale, SalePayment
    with Sess() as db:
        sales = db.query(Sale).filter(Sale.company_id == d["cid"]).count()
        pays = db.execute(text(
            "SELECT count(*) FROM sale_payments sp JOIN sales s ON s.id = sp.sale_id "
            "WHERE s.company_id = :c"), {"c": str(d["cid"])}).scalar()
        movs = db.query(StockMovement).filter(StockMovement.product_id == d["pid"]).count()
        return {"sales": sales, "payments": pays, "movements": movs}


def _qty(Sess, d):
    from app.models.inventory import Inventory
    with Sess() as db:
        r = db.query(Inventory).filter(Inventory.product_id == d["pid"],
                                       Inventory.branch_id == d["bid"]).first()
        return Decimal(str(r.qty))


def _race(fns):
    """Barrier bilan sinxron ishga tushirish."""
    n = len(fns)
    barrier = threading.Barrier(n)

    def one(i):
        barrier.wait(timeout=60)
        return fns[i]()

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(one, range(n)))


# ══ 1. YOPILISH POYGASI — P9-05 NING YADROSI ════════════════════════════════

def test_r1_yopilish_bilan_poyga_savdo_MUZLATILGAN_smenaga_tushmaydi(Sess):
    """INVARIANT: Z-hisobot muzlatilgach, unga yangi savdo QO'SHILMAYDI.

    Ikki tx bir vaqtda: biri savdo, biri yopish. Qulf ularni ketma-ketlashtiradi,
    natija esa IKKI holatdan BIRI bo'lishi SHART:
      A) savdo qulfni birinchi oldi -> savdo smenada VA muzlatilgan `expected` uni
         O'Z ICHIGA OLADI;
      B) yopish birinchi -> savdo bu smenaga BOG'LANMAYDI.

    Nuqson: (B) holatida savdo baribir yopilgan smenaga bog'lanardi va
    `expected_cash` uni qamramasdi — Z-hisobot abadiy noto'g'ri qolardi."""
    d = _dokon(Sess)
    sid = _open_shift(Sess, d)
    res = _race([lambda: _sell(Sess, d, cu=uuid.uuid4(), qty=1, price=100),
                 lambda: _close(Sess, d, sid, counted=100)])
    sale_res, close_res = res[0], res[1]
    assert sale_res[0] in ("ok", "http"), sale_res
    assert close_res[0] == "ok", close_res

    sh = _shift(Sess, sid)
    assert sh["status"] == "closed", sh
    bound = _sales_in_shift(Sess, sid)
    cash = _cash_in_shift(Sess, sid)

    if bound:
        # (A) savdo smenaga bog'langan -> muzlatilgan expected uni QAMRASHI shart.
        assert sh["expected"] == cash, (
            f"MUZLATILGAN Z-HISOBOT BUZILDI: smenada {len(bound)} ta savdo, naqdi {cash}, "
            f"muzlatilgan expected_cash={sh['expected']} — farq {cash - sh['expected']} "
            f"abadiy yarashtirilmay qoladi (sale={sale_res}, close={close_res})")
    else:
        # (B) savdo bog'lanmagan -> expected 0 va savdo boshqa joyda (yoki rad etilgan).
        assert sh["expected"] == Decimal("0.00"), sh


def test_r2_poyga_KO_P_MARTA_hech_qachon_muzlatilgan_hisobotni_buzmaydi(Sess):
    """Ayni poyga 6 marta — timing har safar boshqa bo'ladi, invariant esa bir xil."""
    for i in range(6):
        d = _dokon(Sess)
        sid = _open_shift(Sess, d)
        _race([lambda: _sell(Sess, d, cu=uuid.uuid4(), qty=1, price=100),
               lambda: _close(Sess, d, sid, counted=100)])
        sh = _shift(Sess, sid)
        cash = _cash_in_shift(Sess, sid)
        if _sales_in_shift(Sess, sid):
            assert sh["expected"] == cash, (
                f"[{i}] muzlatilgan expected={sh['expected']} != smenadagi naqd {cash}")
        else:
            assert sh["expected"] == Decimal("0.00"), (i, sh)


def test_r2b_DETERMINISTIK_case_B_yopish_qulfni_BIRINCHI_oladi(Sess, monkeypatch):
    """Poygani TIMINGGA qoldirmasdan MAJBURLAYMIZ (case B).

    `Shift` ustidagi `with_for_update()` chaqirilishidan AYNAN OLDIN smenani
    BOSHQA tranzaksiyada yopamiz va commit qilamiz. Ya'ni savdo yo'li smenani
    «ochiq» deb tanlagan, lekin qulfni olganda u ALLAQACHON yopilgan bo'ladi —
    bu P9-05 ning aynan zaif tartibi.

    Deterministik bo'lgani uchun MUTATSIYA ISBOTI shu sinovga tayanadi."""
    from sqlalchemy.orm import Query

    from app.models.shifts import Shift
    d = _dokon(Sess)
    sid = _open_shift(Sess, d)
    holat = {"n": 0}
    real = Query.with_for_update

    def wrap(self, *a, **kw):
        if holat["n"] == 0 and any(c.get("entity") is Shift for c in self.column_descriptions):
            holat["n"] += 1
            _close(Sess, d, sid, counted=0)       # BOSHQA tx: yopadi va COMMIT qiladi
        return real(self, *a, **kw)

    monkeypatch.setattr(Query, "with_for_update", wrap)
    r = _sell(Sess, d, cu=uuid.uuid4(), qty=1, price=100)
    monkeypatch.undo()

    assert holat["n"] == 1, "poyga hook ishlamadi — smena qulfi chaqirilmadi"
    sh = _shift(Sess, sid)
    assert sh["status"] == "closed" and sh["expected"] == Decimal("0.00"), sh
    bound = _sales_in_shift(Sess, sid)
    assert bound == [], (
        f"MUZLATILGAN SMENAGA BOG'LANDI: {len(bound)} ta savdo, naqdi "
        f"{_cash_in_shift(Sess, sid)}, muzlatilgan expected_cash={sh['expected']} "
        f"(savdo natijasi: {r})")


def test_r2c_sold_at_YOQ_offline_chek_ham_HIMOYALANGAN(Sess, monkeypatch):
    """SHOX SHARTI MOSLIGI (adversarial ko'rikda topilgan teshik).

    `/sync/push` chekining `sold_at` i yo'q yoki oynadan tashqarida bo'lsa
    `_clamp_sold_at` `None` qaytaradi. U holda `honor_price_snapshot=True`
    bo'lsa-da smena ONLAYN selektor bilan tanlanadi (`status == open`).
    Gard `not honor_price_snapshot` deb yozilganda bu kirish CHETLAB O'TILARDI
    va yopilish poygasi aynan shu yerda ochiq qolardi.

    Bu sinov aynan shu kirishni deterministik poyga bilan tekshiradi."""
    from sqlalchemy.orm import Query

    from app.models.auth import Employee
    from app.models.shifts import Shift
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    d = _dokon(Sess)
    sid = _open_shift(Sess, d)
    holat = {"n": 0}
    real = Query.with_for_update

    def wrap(self, *a, **kw):
        if holat["n"] == 0 and any(c.get("entity") is Shift for c in self.column_descriptions):
            holat["n"] += 1
            _close(Sess, d, sid, counted=0)
        return real(self, *a, **kw)

    monkeypatch.setattr(Query, "with_for_update", wrap)
    with Sess() as db:
        emp = db.get(Employee, d["emp"])
        body = SaleCreate(client_uuid=uuid.uuid4(), payment_method="cash",
                          items=[{"product_id": d["pid"], "qty": 1, "unit_price": 100}],
                          given_amount=100)
        try:
            # AYNAN `/sync/push` ning soat-klampidan keyingi chaqiruvi: at=None,
            # honor_price_snapshot=True.
            create_sale(db, emp, body, at=None, honor_price_snapshot=True)
            db.commit()
        except Exception:                          # noqa: BLE001 — rad ham maqbul
            db.rollback()
    monkeypatch.undo()

    assert holat["n"] == 1, "poyga hook ishlamadi"
    sh = _shift(Sess, sid)
    assert sh["status"] == "closed" and sh["expected"] == Decimal("0.00"), sh
    assert _sales_in_shift(Sess, sid) == [], (
        f"MUZLATILGAN SMENAGA BOG'LANDI (sold_at yo'q offline chek): naqdi "
        f"{_cash_in_shift(Sess, sid)}, muzlatilgan expected_cash={sh['expected']}")


def test_r3_yopilgandan_KEYIN_onlayn_savdo_yopiq_smenaga_bogLANMAYDI(Sess):
    """Poyga emas, aniq ketma-ketlik: smena yopilgan, keyin onlayn savdo keladi.

    Onlayn izlash `status == open` bo'yicha boradi, ya'ni yopiq smena TANLANMAYDI —
    bu sinov shu xulqni QULFLAYDI (kelajakdagi o'zgarish uni buzmasin)."""
    d = _dokon(Sess)
    sid = _open_shift(Sess, d)
    assert _close(Sess, d, sid, counted=0)[0] == "ok"
    r = _sell(Sess, d, cu=uuid.uuid4())
    if r[0] == "ok":
        assert r[2] != sid, f"onlayn savdo YOPIQ smenaga bog'landi: {r}"
    assert _sales_in_shift(Sess, sid) == []
    assert _shift(Sess, sid)["expected"] == Decimal("0.00")


# ══ 2. AYNI MANTIQIY SAVDONING PARALLEL TAKRORI ═════════════════════════════

def test_r4_4_parallel_ayni_uuid_ayni_payload_BITTA_tasir(Sess):
    """INVARIANT: bitta mantiqiy savdo -> bitta chek, bitta chiqim, bitta to'lov."""
    d = _dokon(Sess)
    _open_shift(Sess, d)
    X = uuid.uuid4()
    before = _qty(Sess, d)
    res = _race([lambda: _sell(Sess, d, cu=X, qty=2, price=100)] * 4)

    oks = [r for r in res if r[0] == "ok"]
    assert len(oks) == 4, f"ba'zi oqimlar yiqildi: {res}"
    assert len({str(r[1]) for r in oks}) == 1, f"BIR NECHTA chek yaratildi: {res}"
    c = _counts(Sess, d)
    assert c["sales"] == 1, c
    assert c["payments"] == 1, c
    assert c["movements"] == 1, c
    assert before - _qty(Sess, d) == Decimal("2.000"), (before, _qty(Sess, d))


def test_r5_4_parallel_ayni_uuid_MODDIY_BOSHQA_deterministik(Sess):
    """Ayni kalit, boshqa savat: bittasi yoziladi, qolganlari DETERMINISTIK 400
    `IDEMPOTENCY_KEY_REUSED` oladi (P9-03 kontrakti konkurrentlikda ham)."""
    d = _dokon(Sess)
    _open_shift(Sess, d)
    X = uuid.uuid4()
    before = _qty(Sess, d)
    res = _race([lambda: _sell(Sess, d, cu=X, qty=1, price=100),
                 lambda: _sell(Sess, d, cu=X, qty=1, price=100),
                 lambda: _sell(Sess, d, cu=X, qty=5, price=100),
                 lambda: _sell(Sess, d, cu=X, qty=5, price=100)])
    for r in res:
        assert r[0] in ("ok", "http"), r
        if r[0] == "http":
            assert r[1:] == (400, "IDEMPOTENCY_KEY_REUSED"), r
    c = _counts(Sess, d)
    assert c["sales"] == 1, (c, res)
    assert c["payments"] == 1 and c["movements"] == 1, (c, res)
    moved = before - _qty(Sess, d)
    assert moved in (Decimal("1.000"), Decimal("5.000")), (moved, res)


def test_r6_TURLI_uuid_parallel_savdolar_BARCHASI_yoziladi(Sess):
    """Qonuniy parallel savdolar keraksiz serializatsiya yoki birlashtirilmasin."""
    d = _dokon(Sess)
    _open_shift(Sess, d)
    before = _qty(Sess, d)
    res = _race([lambda: _sell(Sess, d, cu=uuid.uuid4(), qty=1, price=100) for _ in range(4)])
    assert all(r[0] == "ok" for r in res), res
    assert len({str(r[1]) for r in res}) == 4, f"cheklar birlashtirildi: {res}"
    c = _counts(Sess, d)
    assert c["sales"] == 4 and c["payments"] == 4 and c["movements"] == 4, c
    assert before - _qty(Sess, d) == Decimal("4.000")


def test_r7_ayni_tenant_BOSHQA_kassir_ayni_uuid_parallel(Sess):
    """P9-03 egalik kontrakti konkurrentlikda: bittasi yoziladi, boshqasi RAD."""
    d = _dokon(Sess, kassirlar=2)
    _open_shift(Sess, d, d["emps"][0])
    _open_shift(Sess, d, d["emps"][1])
    X = uuid.uuid4()
    res = _race([lambda: _sell(Sess, d, cu=X, emp_id=d["emps"][0], qty=1),
                 lambda: _sell(Sess, d, cu=X, emp_id=d["emps"][1], qty=3)])
    oks = [r for r in res if r[0] == "ok"]
    bad = [r for r in res if r[0] == "http"]
    assert len(oks) == 1 and len(bad) == 1, res
    assert bad[0][1:] == (400, "IDEMPOTENCY_KEY_REUSED"), bad
    assert _counts(Sess, d)["sales"] == 1


def test_r8_TURLI_tenant_ayni_uuid_parallel_IKKALASI_yoziladi(Sess):
    dA = _dokon(Sess)
    dB = _dokon(Sess)
    _open_shift(Sess, dA)
    _open_shift(Sess, dB)
    X = uuid.uuid4()
    res = _race([lambda: _sell(Sess, dA, cu=X, qty=2),
                 lambda: _sell(Sess, dB, cu=X, qty=3)])
    assert all(r[0] == "ok" for r in res), res
    assert _counts(Sess, dA)["sales"] == 1 and _counts(Sess, dB)["sales"] == 1
    assert _qty(Sess, dA) == Decimal("998.000") and _qty(Sess, dB) == Decimal("997.000")


# ══ 3. 3A CASE C QO'RIQCHISI — BU FIX UNGA TEGMASIN ═════════════════════════

def test_r9_3A_CASE_C_offline_replay_yopiq_smenaga_BOGLANADI(Sess):
    """RATIFIKATSIYA QILINGAN xulq (ega qarori, CR1): offline replay o'z yopilgan
    smenasiga bog'lanadi. P9-05 tuzatishi FAQAT onlayn shoxga tegishi kerak —
    bu sinov buni qo'riqlaydi."""
    from app.models.auth import Employee
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    d = _dokon(Sess)
    sid = _open_shift(Sess, d)
    sotilgan = NOW - timedelta(minutes=30)        # smena oynasi ichida
    assert _close(Sess, d, sid, counted=0)[0] == "ok"
    with Sess() as db:
        emp = db.get(Employee, d["emp"])
        body = SaleCreate(client_uuid=uuid.uuid4(), payment_method="card",
                          items=[{"product_id": d["pid"], "qty": 1, "unit_price": 100}],
                          given_amount=100)
        s = create_sale(db, emp, body, at=sotilgan, honor_price_snapshot=True)
        db.commit()
        got = s.shift_id
    assert str(got) == str(sid), (
        f"3A Case C BUZILDI: offline replay o'z yopilgan smenasiga bog'lanmadi ({got})")
