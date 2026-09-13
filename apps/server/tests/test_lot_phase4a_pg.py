# -*- coding: utf-8 -*-
"""PHASE 4A — HAQIQIY POSTGRES: konkurentlik, FK/indeks/CHECK migratsiyasi, legacy baza.

⚠️  NEGA ALOHIDA FAYL VA NEGA SQLITE YETMAYDI. Mahalliy to'plam SQLite'da yuradi:
    u na `FOR UPDATE` qulfini, na FK'ni (PRAGMA foreign_keys o'chiq), na
    `CREATE INDEX CONCURRENTLY` ni, na `pg_constraint` ni biladi. Bu fayldagi
    har kafolat faqat Postgres'da ma'noli va faqat shu yerda isbotlanadi.

Konkurentlik juftlari (topshiriq 8-bandi):
  1. yopish × yopish — AYNI qarz          -> ortiqcha yopish yo'q
  2. yopish × yopish — AYNI partiya       -> partiya manfiyga tushmaydi
  3. yopish × sotuv   — AYNI partiya      -> partiya manfiyga tushmaydi, invariant
  4. yopish × qaytarish — AYNI qarz       -> og'ish ikki marta yo'q, tovar ikki marta yo'q
  5. ayni client_uuid parallel            -> hodisa BIR marta
  6. filiallararo qarama-qarshi qaytarish -> deadlock yo'q
"""
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from tests.test_lot_fefo_concurrency import D10, NOW, _concurrent, _mk, pg  # noqa: F401

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(SRV))


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _seed4a(eng, *, buy=50, branches=1):
    """Kompaniya + filial(lar) + ega + KUZATUVLI mahsulot (qoldiqsiz)."""
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    s = _mk(eng)
    co = Company(id=uuid.uuid4(), name="P4A", code="p" + uuid.uuid4().hex[:8], currency="UZS")
    s.add(co)
    s.flush()
    brs = []
    for i in range(branches):
        b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F0{i + 1}", name=f"B{i + 1}",
                   timezone="Asia/Tashkent", is_active=True)
        s.add(b)
        s.flush()
        brs.append(b.id)
    ega = s.query(Role).filter(Role.code == "ega").first() or s.query(Role).first()
    emps = []
    for i, bid in enumerate(brs):
        e = Employee(id=uuid.uuid4(), company_id=co.id, full_name=f"E{i}",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=ega.id)
        s.add(e)
        s.flush()
        if branches > 1:
            s.add(EmployeeBranch(employee_id=e.id, branch_id=bid))
        emps.append(e.id)
    unit = s.query(Unit).first()
    p = Product(id=uuid.uuid4(), company_id=co.id, name="P4A " + uuid.uuid4().hex[:6],
                article_code="Q-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                unit_id=unit.id, base_buy_price=buy, base_sell_price=100, tax_rate=0,
                track_lots=True, track_expiry=False, lots_activated_at=NOW)
    s.add(p)
    s.flush()
    for bid in brs:
        s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=bid, qty=0, min_qty=0,
                        updated_at=NOW))
    s.commit()
    out = {"cid": co.id, "bids": brs, "emps": emps, "pid": p.id}
    s.close()
    return out


def _receive(eng, cid, bid, pid, qty, cost, expiry=D10):
    from app.models.inventory import Inventory, StockBatch
    s = _mk(eng)
    inv = (s.query(Inventory).filter(Inventory.product_id == pid, Inventory.branch_id == bid)
           .with_for_update().one())
    inv.qty = Decimal(str(inv.qty)) + Decimal(str(qty))
    b = StockBatch(id=uuid.uuid4(), company_id=cid, branch_id=bid, product_id=pid,
                   qty=qty, received_qty=qty, remaining_qty=qty, unit_cost=cost,
                   expiry_date=expiry, status="open", source_type="receiving",
                   client_uuid=uuid.uuid4(), received_at=NOW, created_at=NOW,
                   updated_at=NOW, row_version=1)
    s.add(b)
    s.commit()
    bid_ = b.id
    s.close()
    return bid_


def _sale_fn(emp_id, pid, qty, *, offline=True):
    from app.models.auth import Employee
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale

    def go(s):
        emp = s.get(Employee, emp_id)
        sale = create_sale(s, emp, SaleCreate(
            items=[{"product_id": str(pid), "qty": qty, "unit_price": 100}],
            payment_method="card", given_amount=qty * 100, client_uuid=uuid.uuid4()),
            honor_price_snapshot=offline)
        return sale.id
    return go


def _resolve_fn(emp_id, sf_id, lines, cu=None):
    from app.models.auth import Employee
    from app.services import lot_resolution as LRes

    def go(s):
        return LRes.resolve(s, s.get(Employee, emp_id), sf_id, lines, reason="pg",
                            client_uuid=cu or uuid.uuid4())
    return go


def _return_fn(emp_id, sale_id, pid, qty, restock=True):
    from app.api.v1.sales import _create_return_once
    from app.models.auth import Employee
    from app.schemas.sales import ReturnCreate, ReturnItemIn

    def go(s):
        return _create_return_once(ReturnCreate(
            original_sale_id=sale_id, reason="customer", restock=restock,
            refund_method="card", client_uuid=uuid.uuid4(),
            items=[ReturnItemIn(product_id=pid, qty=qty)]), s.get(Employee, emp_id), s)
    return go


def _run(eng, fn):
    s = _mk(eng)
    try:
        return fn(s)
    finally:
        s.close()


def _shortfalls(eng, pid):
    from app.models.inventory import LotShortfall
    s = _mk(eng)
    try:
        return (s.query(LotShortfall).filter(LotShortfall.product_id == pid)
                .order_by(LotShortfall.created_at, LotShortfall.id).all())
    finally:
        s.close()


def _scalar(eng, sql, **kw):
    with eng.connect() as con:
        return con.execute(text(sql), kw).scalar()


def _assert_sound(eng, cid, pid):
    """Invariant + manfiy partiya yo'q + ortiqcha yopish yo'q + qaytish chegaralari."""
    from app.services import stock_invariant as SI
    s = _mk(eng)
    try:
        rep = SI.check(s, cid, [pid])
        assert rep.ok, [str(m) for m in rep.mismatches]
    finally:
        s.close()
    assert _scalar(eng, "SELECT count(*) FROM stock_batches WHERE product_id=:p "
                        "AND remaining_qty < 0", p=pid) == 0
    assert _scalar(eng, "SELECT count(*) FROM lot_shortfalls WHERE product_id=:p "
                        "AND resolved_qty > qty", p=pid) == 0
    assert _scalar(eng, """
        SELECT count(*) FROM lot_shortfall_resolutions e
        WHERE e.product_id = :p AND e.qty < (
            SELECT coalesce(sum(r.qty), 0) FROM return_item_resolution_allocations r
            WHERE r.resolution_id = e.id)""", p=pid) == 0
    assert _scalar(eng, """
        SELECT count(*) FROM lot_shortfalls sf WHERE sf.product_id = :p AND
          (SELECT coalesce(sum(qty),0) FROM return_item_shortfall_allocations
            WHERE shortfall_id = sf.id)
          + (SELECT coalesce(sum(r.qty),0) FROM return_item_resolution_allocations r
             JOIN lot_shortfall_resolutions e ON e.id = r.resolution_id
             WHERE e.shortfall_id = sf.id AND r.sale_item_id = sf.sale_item_id) > sf.qty
    """, p=pid) == 0


def _no_deadlock(*results):
    for r in results:
        if isinstance(r, OperationalError):
            pytest.fail(f"PG xatosi (deadlock/qulf): {r}")


def _outcome(r):
    from fastapi import HTTPException

    from app.services.lot_resolution import ResolutionError
    if isinstance(r, ResolutionError):
        return ("rad", r.status)
    if isinstance(r, HTTPException):
        return ("rad", r.status_code)
    if isinstance(r, Exception):
        return ("xato", repr(r))
    return ("ok", None)


# ══ 1–6. KONKURENTLIK ══════════════════════════════════════════════════════

def test_PG_yopish_x_yopish_AYNI_qarz_ORTIQCHA_yopmaydi(pg, monkeypatch):
    """⚠️  POYGA OYNASI MAJBURAN OCHIQ. Barrier bilan boshlangan ikki tranzaksiya
        tasodifan ketma-ket bajarilib qolishi mumkin — u holda qulfsiz kod ham
        «to'g'ri» natija berar va sinov qulfni O'LCHAMASDI (manfiy nazorat
        aynan shuni ushladi). Shu bois birinchi yopish invariant tekshiruvi
        oldidan (hodisalar yozilgan, commit hali yo'q) 0.8 s kutadi: qulf bo'lsa
        ikkinchisi Inventory'da navbatda turib YANGI qarzni o'qiydi (400),
        qulf bo'lmasa u ESKI qarzni o'qib ortiqcha yopardi.
    """
    import threading
    import time

    from app.services import lot_resolution as LRes

    slow = threading.local()
    real_assert = LRes.SI.assert_ok

    def held_assert(*a, **kw):
        if getattr(slow, "on", False):
            time.sleep(0.8)
        return real_assert(*a, **kw)

    monkeypatch.setattr(LRes.SI, "assert_ok", held_assert)
    st = _seed4a(pg)
    cid, bid, eid, pid = st["cid"], st["bids"][0], st["emps"][0], st["pid"]
    _run(pg, _sale_fn(eid, pid, 5))
    x = _receive(pg, cid, bid, pid, 10, 55)
    sf = _shortfalls(pg, pid)[0]
    first = _resolve_fn(eid, sf.id, [(x, 4)])

    def slow_first(s):
        slow.on = True
        try:
            return first(s)
        finally:
            slow.on = False

    def second(s):
        time.sleep(0.2)           # birinchisi o'z qulflarini olib ulgursin
        return _resolve_fn(eid, sf.id, [(x, 4)])(s)

    ra, rb = _concurrent(pg, slow_first, second)
    _no_deadlock(ra, rb)
    oc = sorted([_outcome(ra), _outcome(rb)])
    assert oc == [("ok", None), ("rad", 400)], (ra, rb)
    assert _scalar(pg, "SELECT resolved_qty FROM lot_shortfalls WHERE id=:i", i=sf.id) == 4
    assert _scalar(pg, "SELECT count(*) FROM lot_shortfall_resolutions WHERE shortfall_id=:i",
                   i=sf.id) == 1
    _assert_sound(pg, cid, pid)


def test_PG_yopish_x_yopish_AYNI_partiya_MANFIYGA_tushmaydi(pg):
    st = _seed4a(pg)
    cid, bid, eid, pid = st["cid"], st["bids"][0], st["emps"][0], st["pid"]
    _run(pg, _sale_fn(eid, pid, 5))
    _run(pg, _sale_fn(eid, pid, 5))
    x = _receive(pg, cid, bid, pid, 5, 55)
    s1, s2 = _shortfalls(pg, pid)
    ra, rb = _concurrent(pg, _resolve_fn(eid, s1.id, [(x, 4)]), _resolve_fn(eid, s2.id, [(x, 4)]))
    _no_deadlock(ra, rb)
    assert sorted([_outcome(ra), _outcome(rb)]) == [("ok", None), ("rad", 400)], (ra, rb)
    assert _scalar(pg, "SELECT remaining_qty FROM stock_batches WHERE id=:i", i=x) == 1
    _assert_sound(pg, cid, pid)


def test_PG_yopish_x_SOTUV_AYNI_partiya(pg):
    st = _seed4a(pg)
    cid, bid, eid, pid = st["cid"], st["bids"][0], st["emps"][0], st["pid"]
    _run(pg, _sale_fn(eid, pid, 5))
    x = _receive(pg, cid, bid, pid, 5, 55)
    sf = _shortfalls(pg, pid)[0]
    for _ in range(3):
        ra, rb = _concurrent(pg, _resolve_fn(eid, sf.id, [(x, 1)]),
                             _sale_fn(eid, pid, 1, offline=True))
        _no_deadlock(ra, rb)
        assert _outcome(rb)[0] == "ok", rb
        _assert_sound(pg, cid, pid)
    rem = _scalar(pg, "SELECT remaining_qty FROM stock_batches WHERE id=:i", i=x)
    assert rem >= 0


def test_PG_yopish_x_QAYTARISH_AYNI_qarz_IKKI_marta_sanamaydi(pg):
    for _ in range(4):
        # Har urinish — YANGI mahsulot: oldingi urinishning partiyalari keyingi
        # offline sotuvni qoplab, qarz tug'dirmay qo'yardi.
        st = _seed4a(pg)
        cid, bid, eid, pid = st["cid"], st["bids"][0], st["emps"][0], st["pid"]
        sale_id = _run(pg, _sale_fn(eid, pid, 5))
        x = _receive(pg, cid, bid, pid, 5, 55)
        sf = _shortfalls(pg, pid)[0]
        ra, rb = _concurrent(pg, _resolve_fn(eid, sf.id, [(x, 5)]),
                             _return_fn(eid, sale_id, pid, 5))
        _no_deadlock(ra, rb)
        assert _outcome(rb)[0] == "ok", rb
        events = _scalar(pg, "SELECT count(*) FROM lot_shortfall_resolutions "
                             "WHERE shortfall_id=:i", i=sf.id)
        if _outcome(ra)[0] == "ok":
            # yopish avval: qaytarish hodisa orqali X ga; og'ish to'liq teskari
            assert events == 1
            assert _scalar(pg, "SELECT coalesce(sum(variance_reversed),0) FROM "
                               "return_item_resolution_allocations r JOIN "
                               "lot_shortfall_resolutions e ON e.id=r.resolution_id "
                               "WHERE e.shortfall_id=:i", i=sf.id) == Decimal("25.00")
        else:
            # qaytarish avval: dum -> U; javondagi tovarni haqiqiy partiyaga yopish RAD
            assert _outcome(ra) == ("rad", 400) and events == 0, ra
        _assert_sound(pg, cid, pid)


def test_PG_AYNI_client_uuid_parallel_HODISA_bir_marta(pg):
    st = _seed4a(pg)
    cid, bid, eid, pid = st["cid"], st["bids"][0], st["emps"][0], st["pid"]
    _run(pg, _sale_fn(eid, pid, 5))
    x = _receive(pg, cid, bid, pid, 5, 55)
    sf = _shortfalls(pg, pid)[0]
    cu = uuid.uuid4()
    ra, rb = _concurrent(pg, _resolve_fn(eid, sf.id, [(x, 3)], cu),
                         _resolve_fn(eid, sf.id, [(x, 3)], cu))
    _no_deadlock(ra, rb)
    assert _outcome(ra)[0] == "ok" and _outcome(rb)[0] == "ok", (ra, rb)
    assert sorted([ra["duplicate"], rb["duplicate"]]) == [False, True], (ra, rb)
    assert _scalar(pg, "SELECT count(*) FROM lot_shortfall_resolutions WHERE shortfall_id=:i",
                   i=sf.id) == 1
    assert _scalar(pg, "SELECT remaining_qty FROM stock_batches WHERE id=:i", i=x) == 2
    _assert_sound(pg, cid, pid)


def test_PG_filiallararo_QARAMA_QARSHI_qaytarish_DEADLOCK_bermaydi(pg):
    st = _seed4a(pg, branches=2)
    cid, (b1, b2), (e1, e2), pid = st["cid"], st["bids"], st["emps"], st["pid"]
    _receive(pg, cid, b1, pid, 50, 55)
    _receive(pg, cid, b2, pid, 50, 55)
    for _ in range(5):
        s1 = _run(pg, _sale_fn(e1, pid, 2, offline=False))     # B1 dagi xodim
        s2 = _run(pg, _sale_fn(e2, pid, 2, offline=False))     # B2 dagi xodim
        # B2 xodimi B1 chekini, B1 xodimi B2 chekini qaytaradi (restock'siz).
        ra, rb = _concurrent(pg, _return_fn(e2, s1, pid, 1, restock=False),
                             _return_fn(e1, s2, pid, 1, restock=False))
        _no_deadlock(ra, rb)
        assert _outcome(ra)[0] == "ok" and _outcome(rb)[0] == "ok", (ra, rb)
    _assert_sound(pg, cid, pid)


def test_PG_qaytarish_vaqti_YOPISHDAN_oldin_yozilmaydi(pg):
    """v3 R17: qulfda kutgan qaytarish teskari yozuvini yopishdan OLDINGI sanaga qo'ymaydi."""
    st = _seed4a(pg)
    cid, bid, eid, pid = st["cid"], st["bids"][0], st["emps"][0], st["pid"]
    sale_id = _run(pg, _sale_fn(eid, pid, 5))
    x = _receive(pg, cid, bid, pid, 5, 55)
    sf = _shortfalls(pg, pid)[0]
    assert _outcome(_run(pg, _resolve_fn(eid, sf.id, [(x, 5)])))[0] == "ok"
    assert _outcome(_run(pg, _return_fn(eid, sale_id, pid, 5)))[0] == "ok"
    bad = _scalar(pg, """
        SELECT count(*) FROM return_item_resolution_allocations r
        JOIN returns rt ON rt.id = r.return_id
        JOIN lot_shortfall_resolutions e ON e.id = r.resolution_id
        WHERE e.shortfall_id = :i AND rt.created_at < e.resolved_at""", i=sf.id)
    assert bad == 0


# ══ 9. MIGRATSIYA: FK / INDEKS / CHECK — YIQILISH va TIKLANISH ═════════════

@pytest.fixture()
def pg_url(tmp_path):
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(str(tmp_path / "pgdata"))
    try:
        u = srv.get_uri()
        yield ("postgresql+psycopg://" + u[len("postgresql://"):]
               if u.startswith("postgresql://") and "+psycopg" not in u else u)
    finally:
        try:
            srv.cleanup()
        except Exception:      # noqa: BLE001
            pass


def _initdb(url, cwd=SRV):
    return subprocess.run([sys.executable, "-m", "app.initdb"], cwd=cwd,
                          capture_output=True, text=True, timeout=900,
                          env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))


def _fk_state(eng, child, col):
    from app.core import required_schema as rs
    fk = [f for f in rs.REQUIRED_FOREIGN_KEYS if f.child == child and f.cols == (col,)][0]
    with eng.connect() as con:
        return rs.classify_fk(fk, rs.fk_rows(con))


def test_PG_FK_yoq_bolsa_TAYYORLIK_QIZIL_boot_YIQILMAYDI_initdb_TUZATADI(pg_url):
    from app.core import required_schema as rs
    r = _initdb(pg_url)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    eng = create_engine(pg_url)
    try:
        assert rs.ok(eng) == (True, []), rs.ok(eng)
        assert all(s == rs.FK_OK for s, _n in rs.fk_states(eng).values())

        # ── 1) FK YO'Q -> tayyorlik QIZIL, lekin FATAL sinfi BO'SH ─────────────
        st, names = _fk_state(eng, "return_item_lot_allocations", "stock_batch_id")
        with eng.begin() as con:
            for n in names:
                con.execute(text(f'ALTER TABLE return_item_lot_allocations DROP CONSTRAINT "{n}"'))
        ok, missing = rs.ok(eng)
        assert ok is False
        assert any(m.startswith("FK yo'q: return_item_lot_allocations(stock_batch_id)")
                   for m in missing), missing
        assert rs.fatal_missing(eng) == [], "FK holati boot'ni yiqitadigan sinfga tushdi"
        r2 = _initdb(pg_url)
        assert r2.returncode == 0, (r2.stdout + r2.stderr)[-1500:]
        assert "return_item_lot_allocations(stock_batch_id) -> stock_batches(id): tasdiqlandi" \
            in r2.stdout, r2.stdout[-2000:]
        assert _fk_state(eng, "return_item_lot_allocations", "stock_batch_id")[0] == rs.FK_OK
        assert rs.ok(eng)[0], rs.ok(eng)

        # ── 2) YETIM qator bilan -> NOT VALID qo'shiladi, boot DAVOM, repair tiklaydi ──
        st4 = _seed4a(eng)
        sb = _receive(eng, st4["cid"], st4["bids"][0], st4["pid"], 1, 1)
        st, names = _fk_state(eng, "stock_batches", "supplier_id")
        with eng.begin() as con:
            for n in names:
                con.execute(text(f'ALTER TABLE stock_batches DROP CONSTRAINT "{n}"'))
            con.execute(text("UPDATE stock_batches SET supplier_id = gen_random_uuid() "
                             "WHERE id = :i"), {"i": sb})
        r3 = _initdb(pg_url)
        assert r3.returncode == 0, "yetim FK boot'ni YIQITDI: " + (r3.stdout + r3.stderr)[-1500:]
        assert "YETIM" in r3.stdout, r3.stdout[-2000:]
        assert _fk_state(eng, "stock_batches", "supplier_id")[0] == rs.FK_NOT_VALID
        assert rs.fatal_missing(eng) == []
        soft = rs.soft_missing(eng)
        assert any("FK tasdiqlanmagan: stock_batches(supplier_id)" in m for m in soft), soft
        # NOT VALID ham YANGI yozuvni himoya qiladi.
        with pytest.raises(Exception):
            with eng.begin() as con:
                con.execute(text("UPDATE stock_batches SET supplier_id = gen_random_uuid() "
                                 "WHERE id = :i"), {"i": sb})
        with eng.begin() as con:
            con.execute(text("UPDATE stock_batches SET supplier_id = NULL WHERE id = :i"),
                        {"i": sb})
        rr = subprocess.run([sys.executable, "-m", "app.tools.repair_lot_schema"], cwd=SRV,
                            capture_output=True, text=True, timeout=300,
                            env=dict(os.environ, DATABASE_URL=pg_url, APP_ENV="test"))
        assert rr.returncode == 0, (rr.stdout + rr.stderr)[-1500:]
        assert _fk_state(eng, "stock_batches", "supplier_id")[0] == rs.FK_OK
        assert rs.ok(eng)[0], rs.ok(eng)

        # ── 3) SHAKLI NOTO'G'RI FK -> aniqlanadi, AVTOMATIK TEGILMAYDI ─────────
        st, names = _fk_state(eng, "sale_item_lot_allocations", "sale_item_id")
        with eng.begin() as con:
            for n in names:
                con.execute(text(f'ALTER TABLE sale_item_lot_allocations DROP CONSTRAINT "{n}"'))
            con.execute(text("ALTER TABLE sale_item_lot_allocations ADD CONSTRAINT "
                             "fk_wrong_action FOREIGN KEY (sale_item_id) REFERENCES sale_items(id)"))
        assert _fk_state(eng, "sale_item_lot_allocations", "sale_item_id")[0] == rs.FK_WRONG
        r4 = _initdb(pg_url)
        assert r4.returncode == 0, (r4.stdout + r4.stderr)[-1500:]
        assert _fk_state(eng, "sale_item_lot_allocations", "sale_item_id") == \
            (rs.FK_WRONG, ["fk_wrong_action"]), "noto'g'ri FK avtomatik o'zgartirildi"
        assert rs.ok(eng)[0] is False
        with eng.begin() as con:
            con.execute(text("ALTER TABLE sale_item_lot_allocations DROP CONSTRAINT fk_wrong_action"))
            con.execute(text("ALTER TABLE sale_item_lot_allocations ADD FOREIGN KEY (sale_item_id)"
                             " REFERENCES sale_items(id) ON DELETE CASCADE"))
        assert rs.ok(eng)[0], rs.ok(eng)

        # ── 4) IDEMPOTENT: to'g'ri sxemada initdb hech narsa O'ZGARTIRMAYDI ────
        r5 = _initdb(pg_url)
        assert r5.returncode == 0
        assert "[fk]" not in r5.stdout, r5.stdout[-2000:]
    finally:
        eng.dispose()


def test_PG_ix_sale_items_sale_id_CONCURRENTLY_YAROQSIZ_tiklanadi_TAYYORLIKKA_tasir_qilmaydi(pg_url):
    from app.core import required_schema as rs
    assert _initdb(pg_url).returncode == 0
    eng = create_engine(pg_url)
    valid = ("SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c "
             "ON c.oid = i.indexrelid WHERE c.relname = 'ix_sale_items_sale_id'")
    try:
        assert _scalar(eng, valid) is True
        with eng.begin() as con:
            con.execute(text("DROP INDEX ix_sale_items_sale_id"))
        assert rs.ok(eng)[0] is True, "TEZLIK indeksi tayyorlikni qizartirdi"
        assert "tezlik indeksi yo'q: ix_sale_items_sale_id" in rs.performance_missing(eng)
        r = _initdb(pg_url)
        assert r.returncode == 0 and "ix_sale_items_sale_id CONCURRENTLY qurildi" in r.stdout, \
            (r.stdout + r.stderr)[-1500:]
        assert _scalar(eng, valid) is True
        # Yiqilgan CONCURRENTLY holatini simulyatsiya: indeks YAROQSIZ.
        with eng.begin() as con:
            con.execute(text("UPDATE pg_index SET indisvalid = false WHERE indexrelid = "
                             "'public.ix_sale_items_sale_id'::regclass"))
        assert "tezlik indeksi yaroqsiz: ix_sale_items_sale_id" in rs.performance_missing(eng)
        r2 = _initdb(pg_url)
        assert r2.returncode == 0 and "YAROQSIZ" in r2.stdout, (r2.stdout + r2.stderr)[-1500:]
        assert _scalar(eng, valid) is True
        # Indeks planner uchun ISHLATILADIGAN.
        with eng.begin() as con:
            con.execute(text("SET LOCAL enable_seqscan = off"))
            # ⚠️  O'ZGARMAS qiymat: `gen_random_uuid()` VOLATILE — planner uni indeks
            #     kaliti sifatida ishlata olmaydi va sinov indeksni emas, funksiyani o'lchardi.
            plan = "\n".join(r[0] for r in con.execute(text(
                "EXPLAIN SELECT id FROM sale_items "
                "WHERE sale_id = '00000000-0000-0000-0000-000000000001'::uuid")))
        assert "ix_sale_items_sale_id" in plan, plan
    finally:
        eng.dispose()


def test_PG_CHECK_yoq_FATAL_tasdiqlanmagan_SOFT_va_yangi_yozuvni_himoyalaydi(pg_url):
    from app.core import required_schema as rs
    assert _initdb(pg_url).returncode == 0
    eng = create_engine(pg_url)
    try:
        with eng.begin() as con:
            con.execute(text("ALTER TABLE lot_shortfall_resolutions DROP CONSTRAINT "
                             "ck_lsr_variance_identity"))
        # Phase 4A cheklovi YO'Q — tayyorlik QIZIL, lekin boot'ni yiqitadigan sinf EMAS.
        assert rs.fatal_missing(eng) == []
        assert any(m.startswith("lot cheklov yo'q: ck_lsr_variance_identity")
                   for m in rs.soft_missing(eng)), rs.soft_missing(eng)
        assert rs.ok(eng)[0] is False
        r = _initdb(pg_url)
        assert r.returncode == 0 and "ck_lsr_variance_identity qo'shildi" in r.stdout, \
            (r.stdout + r.stderr)[-1500:]
        assert rs.ok(eng)[0], rs.ok(eng)

        # Zid qator bor -> NOT VALID qoladi, boot yiqilmaydi, yangi zid yozuv RAD.
        st4 = _seed4a(eng)
        with eng.begin() as con:
            con.execute(text("ALTER TABLE lot_shortfalls DROP CONSTRAINT "
                             "ck_lot_shortfall_resolved_le_qty"))
            bad = con.execute(text(
                "INSERT INTO lot_shortfalls (id, company_id, branch_id, product_id, qty,"
                " resolved_qty, returned_qty, unit_cost, resolved_cost, created_at) VALUES"
                " (gen_random_uuid(), :c, :b, :p, 1, 2, 0, 1, 0, now()) RETURNING id"),
                {"c": st4["cid"], "b": st4["bids"][0], "p": st4["pid"]}).scalar()
        r2 = _initdb(pg_url)
        assert r2.returncode == 0, "tasdiqlanmagan CHECK boot'ni yiqitdi: " + r2.stdout[-1500:]
        assert rs.fatal_missing(eng) == []
        assert any("cheklov tasdiqlanmagan: ck_lot_shortfall_resolved_le_qty" in m
                   for m in rs.soft_missing(eng))
        with pytest.raises(Exception):
            with eng.begin() as con:
                con.execute(text("UPDATE lot_shortfalls SET resolved_qty = 5 WHERE id = :i"),
                            {"i": bad})
        with eng.begin() as con:
            con.execute(text("UPDATE lot_shortfalls SET resolved_qty = 0 WHERE id = :i"),
                        {"i": bad})
        rr = subprocess.run([sys.executable, "-m", "app.tools.repair_lot_schema"], cwd=SRV,
                            capture_output=True, text=True, timeout=300,
                            env=dict(os.environ, DATABASE_URL=pg_url, APP_ENV="test"))
        assert rr.returncode == 0, (rr.stdout + rr.stderr)[-1500:]
        assert rs.ok(eng)[0], rs.ok(eng)
    finally:
        eng.dispose()


# ══ 9b. MAVJUD (da47aa8) BAZA USTIGA MIGRATSIYA + LEGACY SHAKL ═════════════

BASE_SHA = "da47aa8bc0d3c9db4472940b36d4d2663b6f1110"

_OLD_SEED = r'''
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from app.db.session import SessionLocal
from app.models.auth import Employee, Role
from app.models.catalog import Product, Unit
from app.models.inventory import Inventory, LotShortfall, StockBatch
from app.models.org import Branch, Company
from app.schemas.sales import ReturnCreate, ReturnItemIn, SaleCreate
from app.services.sales import create_sale
from app.api.v1.sales import _create_return_once
from app.api.v1.lots import ResolveShortfallIn, resolve_shortfall
NOW = datetime.now(timezone.utc)
s = SessionLocal()
co = Company(id=uuid.uuid4(), name="Legacy", code="lg" + uuid.uuid4().hex[:6], currency="UZS")
s.add(co); s.flush()
br = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="B", timezone="Asia/Tashkent", is_active=True)
s.add(br); s.flush()
role = s.query(Role).filter(Role.code == "ega").first()
emp = Employee(id=uuid.uuid4(), company_id=co.id, full_name="E", phone="+9989" + str(uuid.uuid4().int)[:8], role_id=role.id)
s.add(emp); s.flush()
unit = s.query(Unit).first()
def prod():
    p = Product(id=uuid.uuid4(), company_id=co.id, name="L" + uuid.uuid4().hex[:6], article_code="L-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8], unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0, track_lots=True, track_expiry=False, lots_activated_at=NOW)
    s.add(p); s.flush()
    s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=br.id, qty=0, min_qty=0, updated_at=NOW)); s.flush()
    return p.id
p1, p2 = prod(), prod()
s.commit()
cid, bid, eid = co.id, br.id, emp.id
def offline(pid, q):
    e = s.get(Employee, eid)
    return create_sale(s, e, SaleCreate(items=[{"product_id": str(pid), "qty": q, "unit_price": 100}], payment_method="card", given_amount=q * 100, client_uuid=uuid.uuid4()), honor_price_snapshot=True).id
sale1 = offline(p1, 5)
inv = s.query(Inventory).filter(Inventory.product_id == p1).first()
inv.qty = Decimal(str(inv.qty)) + 5
x = StockBatch(id=uuid.uuid4(), company_id=cid, branch_id=bid, product_id=p1, qty=5, received_qty=5, remaining_qty=5, unit_cost=55, status="open", source_type="receiving", client_uuid=uuid.uuid4(), received_at=NOW, created_at=NOW, updated_at=NOW, row_version=1)
s.add(x); s.commit()
xid = x.id
sf1 = s.query(LotShortfall).filter(LotShortfall.product_id == p1).first().id
resolve_shortfall(sf1, ResolveShortfallIn(stock_batch_id=xid, qty=2, reason="legacy", client_uuid=uuid.uuid4()), s.get(Employee, eid), s)
sale2 = offline(p2, 3)
_create_return_once(ReturnCreate(original_sale_id=sale2, refund_method="card", restock=True, items=[ReturnItemIn(product_id=p2, qty=1)], client_uuid=uuid.uuid4()), s.get(Employee, eid), s)
sf2 = s.query(LotShortfall).filter(LotShortfall.product_id == p2).first().id
print("SEED", cid, bid, eid, p1, p2, sale1, sale2, sf1, sf2, xid)
'''


def _old_tree(tmp_path):
    try:
        blob = subprocess.run(["git", "-C", ROOT, "archive", BASE_SHA, "apps/server/app"],
                              capture_output=True, timeout=120, check=True).stdout
    except Exception as e:      # noqa: BLE001
        pytest.skip(f"da47aa8 daraxtini olib bo'lmadi: {e}")
    dst = tmp_path / "old"
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        tf.extractall(dst, filter="data")
    return dst / "apps" / "server"


def test_PG_da47aa8_bazasi_USTIGA_4A_migratsiya_va_LEGACY_shakl_FAIL_CLOSED(pg_url, tmp_path):
    from fastapi import HTTPException

    from app.api.v1.reports import pnl
    from app.core import required_schema as rs
    from app.models.auth import Employee
    from app.models.inventory import LotShortfall
    from app.models.sales import SaleItem
    from app.services import lot_resolution as LRes

    old = _old_tree(tmp_path)
    env = dict(os.environ, DATABASE_URL=pg_url, APP_ENV="test")
    r0 = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=old, capture_output=True,
                        text=True, timeout=900, env=env)
    assert r0.returncode == 0, (r0.stdout + r0.stderr)[-1500:]
    seed = subprocess.run([sys.executable, "-c", _OLD_SEED], cwd=old, capture_output=True,
                          text=True, timeout=300, env=env)
    assert seed.returncode == 0 and "SEED" in seed.stdout, (seed.stdout + seed.stderr)[-2000:]
    ids = seed.stdout.strip().splitlines()[-1].split()[1:]
    cid, bid, eid, p1, p2, sale1, sale2, sf1, sf2, xid = [uuid.UUID(v) for v in ids]

    eng = create_engine(pg_url)
    legacy_uq = "return_item_lot_allocations_return_item_id_stock_batch_id_key"
    try:
        assert _scalar(eng, "SELECT to_regclass('public.lot_shortfall_resolutions')") is None
        # da47aa8 bazasida eski (return_item_id, stock_batch_id) noyobligi IKKI shaklda bor.
        assert _scalar(eng, "SELECT count(*) FROM pg_indexes WHERE indexname = 'ux_ret_alloc'") == 1
        assert _scalar(eng, "SELECT count(*) FROM pg_constraint WHERE conname = :n", n=legacy_uq) == 1
        r1 = _initdb(pg_url)
        assert r1.returncode == 0, (r1.stdout + r1.stderr)[-2000:]
        assert "ix_sale_items_sale_id CONCURRENTLY qurildi" in r1.stdout, r1.stdout[-2000:]
        assert "noyobligi olib tashlandi" in r1.stdout, r1.stdout[-2000:]
        assert _scalar(eng, "SELECT count(*) FROM pg_indexes WHERE indexname = 'ux_ret_alloc'") == 0
        assert _scalar(eng, "SELECT count(*) FROM pg_constraint WHERE conname = :n", n=legacy_uq) == 0
        assert _scalar(eng, "SELECT count(*) FROM pg_indexes WHERE indexname = 'ux_ret_alloc_line'") == 1
        ok, missing = rs.ok(eng)
        assert ok, missing
        # Tarixiy qatorlar TEGILMAGAN: provisional_qty NULL.
        s = _mk(eng)
        try:
            assert all(si.provisional_qty is None for si in
                       s.query(SaleItem).filter(SaleItem.sale_id.in_([sale1, sale2])).all())
            b1 = LRes.book(s, s.get(LotShortfall, sf1))
            b2 = LRes.book(s, s.get(LotShortfall, sf2))
            assert b1.legacy and b2.legacy, (b1, b2)
            emp = s.get(Employee, eid)
            for sf in (sf1, sf2):
                with pytest.raises(LRes.ResolutionError) as ei:
                    LRes.resolve(s, emp, sf, [(xid, 1)], reason="4a", client_uuid=uuid.uuid4())
                assert ei.value.status == 409
                s.rollback()
            # Hisobot legacy qatorlar ustida yiqilmaydi va ayniyat butun.
            p = pnl(period="month", from_date=None, to_date=None, emp=s.get(Employee, eid), db=s)
            cogs = (p["cogs_known"] + p["cogs_estimated"] + p["cogs_unknown"]
                    - p["cogs_returns_unlinked"] - p["cogs_returns_prior_period"]
                    + p["cogs_variance"])
            assert round(cogs, 2) == round(p["cogs"], 2), p
            assert p["cogs_variance"] == 0.0
        finally:
            s.close()
        # Legacy qarzli chekni omborga qaytarish FAIL-CLOSED, restock'siz — ruxsat.
        with pytest.raises(HTTPException) as he:
            _run(eng, _return_fn(eid, sale1, p1, 1, restock=True))
        assert he.value.status_code == 409 and "legacy" in str(he.value.detail)
        assert _outcome(_run(eng, _return_fn(eid, sale1, p1, 1, restock=False)))[0] == "ok"
        _assert_sound(eng, cid, p1)
        _assert_sound(eng, cid, p2)
        # Ikkinchi yurish — idempotent.
        r2 = _initdb(pg_url)
        assert r2.returncode == 0 and "[fk]" not in r2.stdout and "CONCURRENTLY" not in r2.stdout
    finally:
        eng.dispose()
