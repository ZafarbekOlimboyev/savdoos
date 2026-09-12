# -*- coding: utf-8 -*-
"""PARTIYA POYDEVORI (Phase 0) — sxema, invariant, identifikatsiya, xesh shartnomasi.

Bu bosqichда FEFO ham, muddat ogohlantirishlari ham YO'Q. Bu yerda sinaladigan
narsa bitta: partiya ish vaqti boshlanganда uni jimgina buzadigan tuzoqlar
yopilganmi.
"""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text

from app.models.catalog import Product
from app.models.inventory import Inventory, SaleItemLotAllocation, StockBatch
from app.schemas.imports_v2 import ImportRowV2
from app.services import stock_gate
from app.services import stock_invariant as SI
from app.services.catalog_commit_v2 import CANON_FIELDS, CANON_VERSION, canonical_hash

NOW = datetime.now(timezone.utc)


def _plist(r):
    """`/products` shakli: ro'yxat yoki {"items": [...]}; ikkalasini ham qabul qilamiz."""
    j = r.json()
    return j["items"] if isinstance(j, dict) else j


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _prod(db, company_id, name="Coca-Cola 1L", *, lots=False, expiry=False):
    from app.models.catalog import Unit
    u = db.query(Unit).first()
    p = Product(id=uuid.uuid4(), company_id=company_id, name=name,
                article_code="LOT-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                unit_id=u.id, base_buy_price=55, base_sell_price=70, tax_rate=0,
                track_lots=lots, track_expiry=expiry)
    db.add(p)
    db.flush()
    return p


def _lot(db, p, branch_id, qty, *, expiry=None, cost=55, client_uuid=None, status="open"):
    b = StockBatch(id=uuid.uuid4(), company_id=p.company_id, product_id=p.id,
                   branch_id=branch_id, qty=qty, received_qty=qty, remaining_qty=qty,
                   unit_cost=cost, expiry_date=expiry, status=status,
                   source_type="purchase", client_uuid=client_uuid,
                   received_at=NOW, created_at=NOW)
    db.add(b)
    db.flush()
    return b


def _inv(db, p, branch_id, qty):
    i = Inventory(product_id=p.id, branch_id=branch_id, qty=qty, min_qty=0, updated_at=NOW)
    db.add(i)
    db.flush()
    return i


@pytest.fixture()
def ctx(client):
    """Sinov do'koni — mavjud seed'dan birinchi kompaniya/filial."""
    from app.models.org import Branch, Company
    with _db() as db:
        c = db.query(Company).first()
        b = db.query(Branch).filter(Branch.company_id == c.id).first()
        yield c.id, b.id


# ══ 1. SXEMA ═════════════════════════════════════════════════════════════════

def test_sxema_yangi_obyektlar_YARATILADI(client):
    from app.db.session import engine
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("stock_batches")}
    for need in ("company_id", "received_qty", "remaining_qty", "status", "source_type",
                 "purchase_item_id", "receiving_id", "external_lot_id", "supplier_id",
                 "client_uuid", "updated_at", "row_version"):
        assert need in cols, f"stock_batches.{need} yo'q"
    assert "sale_item_lot_allocations" in insp.get_table_names()
    pcols = {c["name"] for c in insp.get_columns("products")}
    assert {"track_lots", "track_expiry"} <= pcols
    rcols = {c["name"] for c in insp.get_columns("return_items")}
    assert "sale_item_id" in rcols


def test_mavjud_mahsulotlar_KUZATUVSIZ_qoladi(client):
    """Fayzan'ning 7137 tasi kabi — hech qanday backfill YO'Q."""
    with _db() as db:
        total = db.query(Product).count()
        tracked = db.query(Product).filter(Product.track_lots.is_(True)).count()
        assert total > 0
        assert tracked == 0, "backfill bo'lgan — Phase 0 da bu MUMKIN EMAS"


def test_partiya_qatorlari_YARATILMAGAN(client):
    with _db() as db:
        assert db.query(StockBatch).count() == 0
        assert db.query(SaleItemLotAllocation).count() == 0


def test_track_expiry_track_lots_ni_TALAB_qiladi(client, ctx):
    """Postgres'da CHECK, SQLite'da ilova qatlami — qoida IKKALASIDA ham bor."""
    from app.db.session import engine
    cid, _ = ctx
    if engine.dialect.name != "postgresql":
        pytest.skip("CHECK faqat Postgres'da; qoida ilova qatlamida sinaladi")
    with _db() as db:
        p = _prod(db, cid, "CHECK sinovi", lots=False, expiry=True)
        with pytest.raises(Exception):
            db.commit()


# ══ 2. MIQDOR INVARIANTI ═════════════════════════════════════════════════════

def test_invariant_MOS_kelganda_tinch(client, ctx):
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Inv OK", lots=True)
        _inv(db, p, bid, Decimal("160"))
        _lot(db, p, bid, Decimal("100"), expiry=None)
        _lot(db, p, bid, Decimal("60"), expiry=None)
        db.flush()
        rep = SI.check(db, cid, [p.id])
        assert rep.ok, [str(m) for m in rep.mismatches]
        assert rep.checked == 1
        SI.assert_ok(db, cid, [p.id])
        db.rollback()


def test_invariant_MOS_KELMASA_topiladi(client, ctx):
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Inv BUZUQ", lots=True)
        _inv(db, p, bid, Decimal("160"))
        _lot(db, p, bid, Decimal("100"))          # ataylab 60 tasi yo'q
        db.flush()
        rep = SI.check(db, cid, [p.id])
        assert not rep.ok
        assert rep.mismatches[0].delta == Decimal("60")
        with pytest.raises(SI.InvariantBroken) as e:
            SI.assert_ok(db, cid, [p.id])
        assert "invarianti BUZILGAN" in str(e.value)
        db.rollback()


def test_YOPILGAN_partiya_yigindiga_KIRMAYDI(client, ctx):
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Yopilgan", lots=True)
        _inv(db, p, bid, Decimal("10"))
        _lot(db, p, bid, Decimal("10"))
        _lot(db, p, bid, Decimal("99"), status="written_off")   # hisobga OLINMAYDI
        db.flush()
        assert SI.check(db, cid, [p.id]).ok
        db.rollback()


def test_KUZATUVSIZ_mahsulot_tekshirilmaydi(client, ctx):
    """Bugungi 7137 mahsulot — partiyasi yo'q va bo'lishi ham shart emas."""
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Kuzatuvsiz", lots=False)
        _inv(db, p, bid, Decimal("500"))
        db.flush()
        rep = SI.check(db, cid, [p.id])
        assert rep.ok and rep.checked == 0
        db.rollback()


# ══ 3. ESKI YOZUVCHILAR DARVOZASI ════════════════════════════════════════════

def test_eski_yol_KUZATUVLI_mahsulotga_TEGA_OLMAYDI(client, ctx):
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Darvoza", lots=True)
        db.flush()
        with pytest.raises(stock_gate.TrackedProductNotSupported) as e:
            stock_gate.assert_untracked(db, [p.id], "inventarizatsiya")
        assert "inventarizatsiya" in str(e.value)
        db.rollback()


def test_darvoza_KUZATUVSIZ_uchun_ochiq(client, ctx):
    """Musbat nazorat: darvoza hamma narsani bloklab qo'ymadi."""
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Darvoza ochiq", lots=False)
        db.flush()
        stock_gate.assert_untracked(db, [p.id], "inventarizatsiya")   # xato BO'LMASIN
        db.rollback()


def test_inventarizatsiya_ENDPOINTI_kuzatuvlini_RAD_etadi(client, admin_headers, ctx):
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Sanoq rad", lots=True)
        db.commit()
        pid = str(p.id)
    r = client.post("/api/v1/inventory/count",
                    json={"items": [{"product_id": pid, "counted": 5}],
                          "client_uuid": str(uuid.uuid4())}, headers=admin_headers)
    assert r.status_code in (400, 409, 500), r.text
    assert "partiya" in r.text.lower()


# ══ 4. PARTIYA IDENTIFIKATSIYASI ═════════════════════════════════════════════

def test_AYNI_qabul_takrori_AYNI_partiyani_ishlatadi(client, ctx):
    """Idempotentlik kaliti — qabul AMALI (client_uuid), atributlar EMAS."""
    from sqlalchemy.exc import IntegrityError
    cid, bid = ctx
    key = uuid.uuid4()
    with _db() as db:
        p = _prod(db, cid, "Takror qabul", lots=True)
        _lot(db, p, bid, Decimal("100"), client_uuid=key)
        db.commit()
        pid = p.id
    with _db() as db:
        p = db.get(Product, pid)
        with pytest.raises(IntegrityError):
            _lot(db, p, bid, Decimal("100"), client_uuid=key)     # AYNI kalit
            db.commit()
        db.rollback()


def test_BIR_XIL_atributli_ikkinchi_qabul_ALOHIDA_partiya(client, ctx):
    """Muddat + partiya raqami + narx bir xil bo'lsa ham — ALOHIDA kogorta."""
    cid, bid = ctx
    exp = (NOW + timedelta(days=30)).date()
    with _db() as db:
        p = _prod(db, cid, "Ikki kogorta", lots=True)
        a = _lot(db, p, bid, Decimal("50"), expiry=exp, cost=55, client_uuid=uuid.uuid4())
        b = _lot(db, p, bid, Decimal("50"), expiry=exp, cost=55, client_uuid=uuid.uuid4())
        db.flush()
        assert a.id != b.id, "bir xil atributlar BIRLASHTIRILDI — bu XATO"
        assert db.query(StockBatch).filter(StockBatch.product_id == p.id).count() == 2
        db.rollback()


# ══ 5. TAQSIMOT SXEMASI ══════════════════════════════════════════════════════

def test_bitta_qator_KOP_taqsimot_qabul_qiladi(client, ctx):
    """120 dona = A dan 100 + B dan 20. Yig'indi qatorga TENG."""
    from app.models.sales import Sale, SaleItem
    from app.models.enums import SaleStatus
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Taqsimot", lots=True)
        A = _lot(db, p, bid, Decimal("100"), cost=55)
        B = _lot(db, p, bid, Decimal("60"), cost=57)
        from app.models.auth import Employee as _E
        emp = db.query(_E).filter(_E.company_id == cid).first()
        s = Sale(id=uuid.uuid4(), company_id=cid, branch_id=bid, receipt_no="LOT-1",
                 cashier_id=emp.id, status=SaleStatus.completed, subtotal=0, total=0, sold_at=NOW,
                 created_at=NOW)
        db.add(s)
        db.flush()
        si = SaleItem(id=uuid.uuid4(), sale_id=s.id, product_id=p.id, qty=Decimal("120"),
                      name_snapshot=p.name, unit_price=70, unit_cost=Decimal("55.33"),
                      line_total=0, unit_id=p.unit_id)
        db.add(si)
        db.flush()
        for lot, q in ((A, Decimal("100")), (B, Decimal("20"))):
            db.add(SaleItemLotAllocation(
                id=uuid.uuid4(), company_id=cid, sale_item_id=si.id, stock_batch_id=lot.id,
                product_id=p.id, qty=q, unit_cost=lot.unit_cost,
                expiry_date=lot.expiry_date, created_at=NOW))
        db.flush()
        allocs = db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.sale_item_id == si.id).all()
        assert len(allocs) == 2
        assert sum(Decimal(str(a.qty)) for a in allocs) == Decimal(str(si.qty))
        # og'irlangan o'rtacha = (100*55 + 20*57)/120 = 55.333…
        w = sum(Decimal(str(a.qty)) * Decimal(str(a.unit_cost)) for a in allocs) / Decimal("120")
        assert round(w, 2) == Decimal("55.33")
        db.rollback()


def test_AYNI_partiya_ikki_marta_taqsimlanmaydi(client, ctx):
    from sqlalchemy.exc import IntegrityError
    from app.models.sales import Sale, SaleItem
    from app.models.enums import SaleStatus
    cid, bid = ctx
    with _db() as db:
        p = _prod(db, cid, "Takror taqsimot", lots=True)
        A = _lot(db, p, bid, Decimal("100"))
        from app.models.auth import Employee as _E
        emp = db.query(_E).filter(_E.company_id == cid).first()
        s = Sale(id=uuid.uuid4(), company_id=cid, branch_id=bid, receipt_no="LOT-2",
                 cashier_id=emp.id, status=SaleStatus.completed, subtotal=0, total=0, sold_at=NOW,
                 created_at=NOW)
        db.add(s)
        db.flush()
        si = SaleItem(id=uuid.uuid4(), sale_id=s.id, product_id=p.id, qty=Decimal("5"),
                      name_snapshot=p.name, unit_price=70, unit_cost=55, line_total=0,
                      unit_id=p.unit_id)
        db.add(si)
        db.flush()
        for _ in range(2):
            db.add(SaleItemLotAllocation(
                id=uuid.uuid4(), company_id=cid, sale_item_id=si.id, stock_batch_id=A.id,
                product_id=p.id, qty=Decimal("5"), unit_cost=55, created_at=NOW))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


# ══ 6. IMPORT XESH SHARTNOMASI ═══════════════════════════════════════════════

def _old_hash(rows):
    """Shartnoma kiritilishidan OLDINGI algoritm — butun model dump."""
    def canon(r):
        d = r.model_dump(mode="json")
        d["name"] = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()
        d["barcodes"] = sorted({str(b).strip() for b in (d.get("barcodes") or []) if str(b).strip()})
        for k in ("buy_price", "sell_price", "stock"):
            d[k] = float(d.get(k) or 0)
        for k in ("external_id", "article", "unit", "plu_code", "category"):
            v = d.get(k)
            d[k] = (str(v).strip() or None) if v is not None else None
        return d
    import hashlib
    canon_lines = sorted(json.dumps(canon(r), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False) for r in rows)
    h = hashlib.sha256()
    h.update(str(len(canon_lines)).encode())
    h.update(b"\x00")
    for line in canon_lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


ROWS = [
    [ImportRowV2(name="Sut 1l", external_id="G-A", buy_price=55, sell_price=70, stock=10,
                 barcodes=["4600949010205", "4780032051640"], article="A1", unit="dona",
                 plu_code="575", category="Sut")],
    [ImportRowV2(name="  Non   oq  ", stock=5)],
    [ImportRowV2(name="X"), ImportRowV2(name="X")],
    [ImportRowV2(name="X"), ImportRowV2(name="Y"), ImportRowV2(name="Y")],
]


@pytest.mark.parametrize("rows", ROWS)
def test_xesh_ESKI_qiymatni_SAQLAYDI(rows):
    """Shartnoma kiritilishi mavjud snapshot xeshlarini O'ZGARTIRMASLIGI SHART."""
    assert canonical_hash(rows) == _old_hash(rows)


def test_YANGI_IXTIYORIY_maydon_xeshni_OZGARTIRMAYDI():
    """Asosiy kafolat: kelajakdagi `track_lots`/`lots[]` eski xeshni buzmasin.

    Modelга sun'iy maydon qo'shib, ayni qator uchun xesh o'zgarmasligini
    tekshiramiz. Ilgari `model_dump()` butun modelni olgani uchun bu xesh
    O'ZGARARDI va commit qilingan snapshot soxta ziddiyat bergan bo'lardi.
    """
    from pydantic import Field, create_model
    base = ImportRowV2(name="Sut 1l", external_id="G-A", buy_price=55, stock=3,
                       barcodes=["4600949010205"])
    before = canonical_hash([base])

    Extended = create_model("ExtendedRow", __base__=ImportRowV2,
                            track_lots=(bool, Field(default=False)),
                            lots=(list, Field(default_factory=list)))
    ext = Extended(name="Sut 1l", external_id="G-A", buy_price=55, stock=3,
                   barcodes=["4600949010205"], track_lots=True,
                   lots=[{"batch_number": "L-1", "qty": 3}])
    assert "track_lots" in ext.model_dump(), "sinov o'z shartini buzdi"
    assert canonical_hash([ext]) == before, "YANGI MAYDON eski xeshni o'zgartirdi"


def test_shartnoma_ANIQ_royxat_va_VERSIYALANGAN():
    assert CANON_VERSION == 1
    assert len(CANON_FIELDS) == 12
    assert "track_lots" not in CANON_FIELDS and "lots" not in CANON_FIELDS


def test_xesh_MULTISET_xavfsizligi_SAQLANDI():
    X = ImportRowV2(name="X")
    assert canonical_hash([X]) != canonical_hash([X, X])
    assert canonical_hash([X, X]) != canonical_hash([X, X, X])
    Y = ImportRowV2(name="Y")
    assert canonical_hash([X, Y]) == canonical_hash([Y, X])
    assert canonical_hash([X, X, Y]) != canonical_hash([X, Y, Y])


def test_xesh_barkod_va_son_normallashtirish_SAQLANDI():
    a = ImportRowV2(name="Z", barcodes=["222", "111", "222"], buy_price=10, sell_price=10.0)
    b = ImportRowV2(name="Z", barcodes=["111", "222"], buy_price=10.00, sell_price=10)
    assert canonical_hash([a]) == canonical_hash([b])


# ══ 7. QAYTARISH HAVOLASI ════════════════════════════════════════════════════

def test_CHEK_asosidagi_qaytarish_sale_item_id_ni_TOLDIRADI(client, admin_headers):
    from app.models.sales import Return, ReturnItem, Sale, SaleItem
    # Naqd qaytarish OCHIQ SMENA talab qiladi (mavjud biznes qoidasi).
    client.post("/api/v1/shifts/open", headers=admin_headers, json={"opening_cash": 100000})
    r = client.get("/api/v1/products", headers=admin_headers)
    assert r.status_code == 200, r.text
    prod = next(p for p in _plist(r) if (p.get("stock") or 0) > 2)

    sale = client.post("/api/v1/sales", json={
        "items": [{"product_id": prod["id"], "qty": 2}],
        "payment_method": "cash",
        "client_uuid": str(uuid.uuid4())}, headers=admin_headers)
    assert sale.status_code == 200, sale.text
    sale_id = sale.json()["id"]

    up = sale.json()["items"][0]["unit_price"]
    ret = client.post("/api/v1/returns", json={
        "original_sale_id": sale_id, "reason": "customer", "refund_method": "cash",
        "restock": True,
        "items": [{"product_id": prod["id"], "qty": 1, "unit_price": up}],
        "client_uuid": str(uuid.uuid4())}, headers=admin_headers)
    assert ret.status_code == 200, ret.text

    with _db() as db:
        ri = (db.query(ReturnItem).join(Return, Return.id == ReturnItem.return_id)
              .filter(Return.id == uuid.UUID(ret.json()["id"])).first())
        assert ri is not None
        assert ri.sale_item_id is not None, "chek asosidagi qaytarish qatorga bog'lanmadi"
        si = db.get(SaleItem, ri.sale_item_id)
        assert si is not None and str(si.sale_id) == sale_id
        assert Decimal(str(ri.unit_cost)) == Decimal(str(si.unit_cost))


# ══ 8. ESKI XULQ ═════════════════════════════════════════════════════════════

def test_kuzatuvsiz_mahsulot_SOTUVI_ozgarmagan(client, admin_headers):
    """Bugungi oqim butunlay o'zgarishsiz ishlashда davom etadi."""
    r = client.get("/api/v1/products", headers=admin_headers)
    prod = next(p for p in _plist(r) if (p.get("stock") or 0) > 1)
    before = prod["stock"]
    s = client.post("/api/v1/sales", json={
        "items": [{"product_id": prod["id"], "qty": 1}],
        "payment_method": "cash",
        "client_uuid": str(uuid.uuid4())}, headers=admin_headers)
    assert s.status_code == 200, s.text
    with _db() as db:
        inv = db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(prod["id"])).first()
        assert Decimal(str(inv.qty)) == Decimal(str(before)) - 1
        assert db.query(SaleItemLotAllocation).count() == 0, "partiya yozuvi paydo bo'ldi"
