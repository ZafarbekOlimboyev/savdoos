# -*- coding: utf-8 -*-
"""PHASE 0 YAKUNIY TUZATISH DARVOZASI.

Olti tuzatish: tayyorlik bog'liqligi, partiya holati semantikasi, xesh
shartnomasi versiyasi, kanonik bog'lanish, miqdor semantikasi, vaqt zonasi.
"""
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.core import required_schema as rs
from app.models.catalog import Product
from app.models.inventory import Inventory, StockBatch
from app.schemas.imports_v2 import ImportRowV2
from app.services import lot_policy as LP
from app.services import stock_invariant as SI
from app.services.catalog_commit_v2 import CANON_VERSION, canonical_hash, canonical_hash_v

NOW = datetime.now(timezone.utc)
SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _prod(db, cid, name, *, lots=False, expiry=False):
    from app.models.catalog import Unit
    p = Product(id=uuid.uuid4(), company_id=cid, name=name,
                article_code="G-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                unit_id=db.query(Unit).first().id, base_buy_price=55,
                base_sell_price=70, tax_rate=0, track_lots=lots, track_expiry=expiry)
    db.add(p)
    db.flush()
    return p


def _lot(db, p, bid, qty, *, expiry=None, status="open"):
    b = StockBatch(id=uuid.uuid4(), company_id=p.company_id, product_id=p.id, branch_id=bid,
                   qty=qty, received_qty=qty, remaining_qty=qty, unit_cost=55,
                   expiry_date=expiry, status=status, source_type="purchase",
                   received_at=NOW, created_at=NOW)
    db.add(b)
    db.flush()
    return b


def _inv(db, p, bid, qty):
    i = Inventory(product_id=p.id, branch_id=bid, qty=qty, min_qty=0, updated_at=NOW)
    db.add(i)
    db.flush()
    return i


@pytest.fixture()
def ctx(client):
    from app.models.org import Branch, Company
    with _db() as db:
        c = db.query(Company).first()
        b = db.query(Branch).filter(Branch.company_id == c.id).first()
        yield c.id, b.id


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


def _build(url):
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, env=env, timeout=600)
    assert r.returncode == 0, (r.stdout + r.stderr)[-900:]


# ══ 1. TAYYORLIK ISH VAQTI BOG'LIQLIGIGA ERGASHADI ═══════════════════════════

def test_PHASE0_ish_vaqti_ustunlari_MAJBURIY():
    """Staging bo'shlig'i: Postgres `track_lots` ni yaratmadi, tayyorlik yashil qoldi."""
    for pair in (("products", "track_lots"), ("products", "track_expiry"),
                 ("return_items", "sale_item_id")):
        assert pair in rs.REQUIRED_COLUMNS, f"{pair} tayyorlikda majburiy EMAS"


def test_PHASE1_ustunlari_hali_MAJBURIY_EMAS():
    """Qoida ikki tomonlama — ish vaqti tayanmagan narsa majburiy BO'LMASIN."""
    names = {f"{t}.{c}" for t, c in rs.REQUIRED_COLUMNS}
    for later in ("stock_batches.remaining_qty", "stock_batches.received_qty",
                  "stock_batches.status", "stock_batches.client_uuid"):
        assert later not in names, f"{later} erta majburiy qilingan"


@pytest.mark.parametrize("col", ["track_lots", "track_expiry"])
def test_USTUN_yoq_bolsa_tayyorlik_QIZIL(pg_url, col):
    _build(pg_url)
    eng = create_engine(pg_url)
    assert rs.ok(eng)[0], rs.ok(eng)[1]
    with eng.begin() as con:
        con.execute(text("ALTER TABLE products DROP CONSTRAINT IF EXISTS "
                         "ck_track_expiry_implies_lots"))
        con.execute(text(f"ALTER TABLE products DROP COLUMN {col}"))
    ok, missing = rs.ok(eng)
    assert ok is False
    assert any(col in m for m in missing), missing
    eng.dispose()


def test_CHECK_yoq_bolsa_tayyorlik_QIZIL(pg_url):
    """CHECK — `track_expiry => track_lots` uchun YAGONA himoya."""
    _build(pg_url)
    eng = create_engine(pg_url)
    with eng.begin() as con:
        con.execute(text("ALTER TABLE products DROP CONSTRAINT "
                         "ck_track_expiry_implies_lots"))
    ok, missing = rs.ok(eng)
    assert ok is False
    assert any("ck_track_expiry_implies_lots" in m for m in missing), missing
    eng.dispose()


def test_return_sale_item_id_yoq_bolsa_tayyorlik_QIZIL(pg_url):
    """Jonli qaytarish kodi bu ustunga YOZADI."""
    _build(pg_url)
    eng = create_engine(pg_url)
    with eng.begin() as con:
        con.execute(text("ALTER TABLE return_items DROP COLUMN sale_item_id"))
    ok, missing = rs.ok(eng)
    assert ok is False
    assert any("sale_item_id" in m for m in missing), missing
    eng.dispose()


def test_SQLite_da_CHECK_talab_QILINMAYDI(client):
    """SQLite `ADD CONSTRAINT` ni bilmaydi — u yerda tayyorlik qizil bo'lmasin."""
    from app.db.session import engine
    if engine.dialect.name == "postgresql":
        pytest.skip("bu tekshiruv SQLite uchun")
    ok, missing = rs.ok(engine)
    assert ok, missing


# ══ 2/3. MUDDAT MIQDORNI OLIB TASHLAMAYDI ════════════════════════════════════

def test_MUDDATI_OTGAN_partiya_qoldiqda_QOLADI(client, ctx):
    """10 dona muddati kecha tugagan sut hamon 10 dona."""
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Muddati o'tgan", lots=True)
        _inv(db, p, bid, Decimal("10"))
        _lot(db, p, bid, Decimal("10"), expiry=(NOW - timedelta(days=1)).date())
        db.flush()
        rep = SI.check(db, cid, [p.id])
        assert rep.ok, [str(m) for m in rep.mismatches]
        db.rollback()


def test_TUGAGAN_partiya_yigindida_QOLADI(client, ctx):
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Tugagan", lots=True)
        _inv(db, p, bid, Decimal("5"))
        _lot(db, p, bid, Decimal("5"))
        _lot(db, p, bid, Decimal("0"), status=SI.DEPLETED)
        db.flush()
        assert SI.check(db, cid, [p.id]).ok
        db.rollback()


def test_VOID_partiya_yigindidan_CHIQARILADI(client, ctx):
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Bekor", lots=True)
        _inv(db, p, bid, Decimal("5"))
        _lot(db, p, bid, Decimal("5"))
        _lot(db, p, bid, Decimal("0"), status=SI.VOID)
        db.flush()
        assert SI.check(db, cid, [p.id]).ok
        db.rollback()


def test_status_EXPIRED_ni_OZ_ICHIGA_OLMAYDI():
    """Muddat HOLAT emas — hosila."""
    assert SI.QUANTITY_BEARING == (SI.OPEN, SI.DEPLETED)
    assert not hasattr(SI, "EXPIRED")


# ══ 4. XESH SHARTNOMASI VERSIYASI ════════════════════════════════════════════

def test_yangi_ish_VERSIYANI_saqlaydi(client, admin_headers):
    from app.models.imports import ImportJob
    r = client.post("/api/v1/catalog/v2/preview", json={
        "mode": "CUTOVER_REFRESH", "source_system": "1c", "snapshot_id": "HV-1",
        "rows": [{"name": "Xesh versiya", "external_id": "HV-A", "sell_price": 10,
                  "buy_price": 5, "stock": 0, "barcodes": [], "is_weighted": False}]},
        headers=admin_headers)
    assert r.status_code == 200, r.text
    with _db() as db:
        j = db.get(ImportJob, uuid.UUID(r.json()["job_id"]))
        assert j.hash_contract_version == CANON_VERSION


def test_ESKI_ish_OZ_versiyasi_bilan_solishtiriladi():
    """v2 chiqqanда ham v1 ish v1 qoidasi bilan solishtiriladi."""
    rows = [ImportRowV2(name="Sut", external_id="V-1", buy_price=5)]
    assert canonical_hash_v(rows, 1) == canonical_hash(rows)
    assert canonical_hash_v(rows, None) == canonical_hash(rows)   # NULL = v1
    with pytest.raises(ValueError):
        canonical_hash_v(rows, 2)


def test_HAQIQIY_mazmun_ozgarsa_hamon_ZIDDIYAT():
    """Musbat nazorat: versiya himoyasi haqiqiy o'zgarishni YASHIRMASIN."""
    a = [ImportRowV2(name="Sut", external_id="V-1", buy_price=5)]
    b = [ImportRowV2(name="Sut", external_id="V-1", buy_price=6)]
    assert canonical_hash(a) != canonical_hash(b)


# ══ 5. IKKI TOMONLAMA EGALIK YO'Q ════════════════════════════════════════════

def test_eskirgan_batch_id_HECH_QAYERDA_yozilmaydi():
    """Kanonik yo'nalish BITTA: StockBatch.purchase_item_id."""
    import pathlib
    root = pathlib.Path(SRV) / "app"
    hits = []
    for f in root.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if "batch_id=" in line and "stock_batch_id=" not in line:
                hits.append(f"{f.name}:{n}")
    assert not hits, "eskirgan batch_id YOZILMOQDA: " + ", ".join(hits)


def test_kanonik_bogliqlik_partiyada():
    """Bir qator -> ko'p partiya. Teskarisi emas."""
    assert "purchase_item_id" in StockBatch.__table__.columns


# ══ 6. VAQT ZONASI ═══════════════════════════════════════════════════════════

def test_biznes_sanasi_FILIAL_zonasida(client, ctx):
    """Toshkent 03:30 — UTC hali KECHAGI kun."""
    cid, bid = ctx
    with _db() as db:
        utc_tun = datetime(2026, 10, 10, 22, 30, tzinfo=timezone.utc)
        assert LP.business_date(db, bid, utc_tun).isoformat() == "2026-10-11"
        assert utc_tun.date().isoformat() == "2026-10-10"     # sodda UTC XATO bo'lardi


def test_muddat_chegarasi_BUGUN_hali_yaroqli():
    biz = date(2026, 10, 10)
    assert LP.is_expired(date(2026, 10, 9), biz) is True
    assert LP.is_expired(date(2026, 10, 10), biz) is False     # kun oxirigacha
    assert LP.is_expired(date(2026, 10, 11), biz) is False
    assert LP.is_expired(None, biz) is False                   # NOMA'LUM != o'tgan


def test_vaqt_zonasi_ANIQ_tekshiriladi(client, ctx):
    """Standart `Asia/Tashkent` JIMGINA to'g'ri deb qabul qilinmaydi."""
    from app.models.org import Branch
    cid, bid = ctx
    with _db() as db:
        assert LP.validate_for_expiry(db, bid) in LP._TZ_OFFSETS
        b = db.get(Branch, bid)
        b.timezone = ""
        db.flush()
        with pytest.raises(LP.TimezoneNotConfigured):
            LP.validate_for_expiry(db, bid)
        b.timezone = "Mars/Olympus"
        db.flush()
        with pytest.raises(LP.TimezoneNotConfigured):
            LP.validate_for_expiry(db, bid)
        db.rollback()


def test_yangi_zona_qoshilmagan(client):
    """Zona ro'yxati hisobotlar bilan IZCHIL bo'lib qolsin."""
    from app.api.v1.reports import _TZ_OFFSETS as R
    assert set(LP._TZ_OFFSETS) == set(R), "zona ro'yxatlari AJRALIB ketdi"
