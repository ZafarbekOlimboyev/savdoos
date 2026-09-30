# -*- coding: utf-8 -*-
"""P9-04 — KO'CHIRISH IDEMPOTENTLIGI HAQIQIY POSTGRES'DA (parallel yozuvchilar).

NEGA SQLite YARAMAYDI: unda parallel yozuvchilar fayl qulfida NAVBATGA turadi,
ya'ni «SELECT-keyin-INSERT» oynasi umuman ochilmaydi va mantiq sinalmagan holda
yashil ko'rinardi. Bu yerda esa AYNI kalit bilan bir vaqtda kelgan so'rovlar
haqiqatan to'qnashadi va yakuniy kafolat BAZA indeksiga tushadi:

    ux_stockmov_client_prod_type (client_uuid, product_id, type)
                                  WHERE client_uuid IS NOT NULL

USHLANADIGAN NUQSONLAR:
  1. Ilova qidiruvi ijarachi doirasisiz bo'lsa — parallel ikki IJARACHIDAN biri
     jimgina «dublikat» bo'lib qolardi (P9-04).
  2. Faqat SELECT'ga tayanilsa — ayni ijarachining parallel takrorlari ikki marta
     qoldiq siljitardi (indeks bo'lmaganda) yoki 500 berardi (retry bo'lmaganda).
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
    # AYNAN production sozlamalari (`db/session.py`).
    return sessionmaker(bind=pg, autoflush=False, expire_on_commit=False, class_=Session)


def _dokon(Sess, *, qty=100):
    """Kompaniya + 2 filial + ombor xodimi + qoldiqli mahsulot."""
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Product, Unit
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    with Sess() as db:
        co = Company(id=uuid.uuid4(), name="P904 " + uuid.uuid4().hex[:6],
                     code="p904" + uuid.uuid4().hex[:8], currency="UZS")
        db.add(co)
        db.flush()
        b1 = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="Markaz",
                    is_active=True, created_at=NOW - timedelta(days=10))
        b2 = Branch(id=uuid.uuid4(), company_id=co.id, code="F02", name="Ikkinchi",
                    is_active=True, created_at=NOW - timedelta(days=5))
        db.add_all([b1, b2])
        db.flush()
        role = db.query(Role).filter(Role.code == "omborchi").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, role_id=role.id,
                     full_name="P904 omborchi",
                     phone="+9987" + str(uuid.uuid4().int)[:8],
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.flush()
        db.add_all([EmployeeBranch(employee_id=e.id, branch_id=b1.id),
                    EmployeeBranch(employee_id=e.id, branch_id=b2.id)])
        unit = db.query(Unit).filter(Unit.code == "dona").first() or db.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=co.id, name="P904 " + uuid.uuid4().hex[:6],
                    article_code="P9-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0,
                    track_lots=False)
        db.add(p)
        db.flush()
        db.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b1.id,
                         qty=Decimal(str(qty)), min_qty=0, updated_at=NOW))
        db.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b2.id,
                         qty=Decimal("0"), min_qty=0, updated_at=NOW))
        db.commit()
        return {"cid": co.id, "b1": b1.id, "b2": b2.id, "emp": e.id, "pid": p.id}


def _call(Sess, d, *, cu, qty=2, frm=None, to=None):
    """HAQIQIY `POST /inventory/transfer` xizmati (retry o'rami bilan birga)."""
    from fastapi import HTTPException

    from app.api.v1.cashops import TransferIn, transfer
    from app.models.auth import Employee
    with Sess() as db:
        emp = db.get(Employee, d["emp"])
        body = TransferIn(client_uuid=cu,
                          from_branch_id=(frm or d["b1"]), to_branch_id=(to or d["b2"]),
                          items=[{"product_id": d["pid"], "qty": qty}])
        try:
            return ("ok", transfer(body, emp, db))
        except HTTPException as e:
            db.rollback()
            return ("http", e.status_code, (e.headers or {}).get("X-Error-Code"))
        except Exception as e:                    # noqa: BLE001
            db.rollback()
            return ("error", f"{type(e).__name__}: {e}")


def _qty(Sess, pid, bid):
    from app.models.inventory import Inventory
    with Sess() as db:
        r = db.query(Inventory).filter(Inventory.product_id == pid,
                                       Inventory.branch_id == bid).first()
        return Decimal(str(r.qty)) if r else None


def _moves(Sess, cid, typ):
    from app.models.inventory import StockMovement
    from app.models.org import Branch
    with Sess() as db:
        return (db.query(StockMovement)
                .join(Branch, Branch.id == StockMovement.branch_id)
                .filter(Branch.company_id == cid, StockMovement.type == typ).count())


def _race(fns, n):
    """`n` oqim BIR VAQTDA (barrier) ishga tushadi."""
    barrier = threading.Barrier(n)

    def one(i):
        barrier.wait(timeout=60)
        return fns[i]()

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(one, range(n)))


# ══ 1. AYNI IJARACHI — 4 PARALLEL, AYNI KALIT -> BITTA TA'SIR ════════════════

def test_c1_ayni_ijarachi_4_parallel_BITTA_kochirish(Sess):
    from app.models.enums import MovementType
    d = _dokon(Sess)
    X = uuid.uuid4()
    res = _race([lambda: _call(Sess, d, cu=X, qty=2)] * N, N)

    oks = [r for r in res if r[0] == "ok"]
    assert len(oks) == N, f"ba'zi oqimlar yiqildi: {res}"
    # Qoldiq AYNAN bir marta siljigan.
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("98.000"), res
    assert _qty(Sess, d["pid"], d["b2"]) == Decimal("2.000"), res
    # Buxgalteriya izi AYNAN bir marta.
    assert _moves(Sess, d["cid"], MovementType.transfer_out) == 1
    assert _moves(Sess, d["cid"], MovementType.transfer_in) == 1
    # Aynan bittasi ASL, qolganlari takror.
    _fresh = [r for r in oks if not (isinstance(r[1], dict) and r[1].get("duplicate"))]
    assert len(_fresh) == 1, f"{len(_fresh)} ta ASL javob (kutilgan 1): {res}"


# ══ 2. IKKI IJARACHI — PARALLEL, AYNI KALIT -> IKKI MUSTAQIL TA'SIR ══════════

def test_c2_ikki_ijarachi_parallel_ayni_kalit_IKKI_kochirish(Sess):
    from app.models.enums import MovementType
    dA = _dokon(Sess)
    dB = _dokon(Sess)
    X = uuid.uuid4()
    res = _race([lambda: _call(Sess, dA, cu=X, qty=3),
                 lambda: _call(Sess, dB, cu=X, qty=7)], 2)
    assert all(r[0] == "ok" for r in res), res
    assert all(not (isinstance(r[1], dict) and r[1].get("duplicate")) for r in res), \
        f"ijarachilardan biri JIMGINA yutildi: {res}"
    assert _qty(Sess, dA["pid"], dA["b1"]) == Decimal("97.000")
    assert _qty(Sess, dA["pid"], dA["b2"]) == Decimal("3.000")
    assert _qty(Sess, dB["pid"], dB["b1"]) == Decimal("93.000")
    assert _qty(Sess, dB["pid"], dB["b2"]) == Decimal("7.000")
    for d in (dA, dB):
        assert _moves(Sess, d["cid"], MovementType.transfer_out) == 1
        assert _moves(Sess, d["cid"], MovementType.transfer_in) == 1


# ══ 3. AYNI KALIT, MODDIY BOSHQA — DETERMINISTIK KONFLIKT ════════════════════

def test_c3_ayni_kalit_boshqa_miqdor_DETERMINISTIK_konflikt(Sess):
    from app.models.enums import MovementType
    d = _dokon(Sess)
    X = uuid.uuid4()
    first = _call(Sess, d, cu=X, qty=2)
    assert first[0] == "ok" and not first[1].get("duplicate"), first
    # Ketma-ket VA parallel — ikkalasi ham AYNI natija berishi kerak.
    second = _call(Sess, d, cu=X, qty=9)
    assert second == ("http", 409, "IDEMPOTENCY_KEY_REUSED"), second
    par = _race([lambda: _call(Sess, d, cu=X, qty=9)] * 3, 3)
    assert all(r == ("http", 409, "IDEMPOTENCY_KEY_REUSED") for r in par), par
    # Qoldiq FAQAT birinchi ko'chirishdan.
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("98.000")
    assert _qty(Sess, d["pid"], d["b2"]) == Decimal("2.000")
    assert _moves(Sess, d["cid"], MovementType.transfer_out) == 1


# ══ 4. PARALLEL ARALASH: AYNI KALIT, YARMI BOSHQA TARKIB ═════════════════════

def test_c4_parallel_aralash_ayni_kalit(Sess):
    """2 ta AYNI + 2 ta MODDIY BOSHQA, hammasi bir vaqtda. Natija: bitta
    ko'chirish, boshqalari takror yoki konflikt — QOLDIQ bir marta siljiydi."""
    from app.models.enums import MovementType
    d = _dokon(Sess)
    X = uuid.uuid4()
    res = _race([lambda: _call(Sess, d, cu=X, qty=5),
                 lambda: _call(Sess, d, cu=X, qty=5),
                 lambda: _call(Sess, d, cu=X, qty=6),
                 lambda: _call(Sess, d, cu=X, qty=6)], 4)
    kinds = [r[0] for r in res]
    assert all(k in ("ok", "http") for k in kinds), res
    for r in res:
        if r[0] == "http":
            assert r[1:] == (409, "IDEMPOTENCY_KEY_REUSED"), r
    moved = _qty(Sess, d["pid"], d["b2"])
    assert moved in (Decimal("5.000"), Decimal("6.000")), (moved, res)
    assert _qty(Sess, d["pid"], d["b1"]) == Decimal("100.000") - moved
    assert _moves(Sess, d["cid"], MovementType.transfer_out) == 1
    assert _moves(Sess, d["cid"], MovementType.transfer_in) == 1
