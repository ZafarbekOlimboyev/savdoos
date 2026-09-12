# -*- coding: utf-8 -*-
"""PHASE 3 — PARTIYA-DARAJASIDAGI HISOBDAN CHIQARISH.

Asosiy qoida: tizim QAYSI partiya tashlanayotganini TAXMIN QILMAYDI.

FEFO — sotuv qoidasi (mijoz javondan oldingisini oladi). Hisobdan chiqarish
esa boshqa amal: operator ANIQ bir jismoniy qadoqni qo'lida ushlab turibdi.
Uni FEFO bilan taxmin qilish eng erta muddatli partiyani kamaytirib, ASLIDA
tashlangan partiyani javonda qoldirardi — muddat hisoboti YOLG'ON bo'lardi.
"""
import uuid
from decimal import Decimal

from app.services import stock_invariant as SI

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    _recv_plain,
    ctx,
    sup,
)


def _wo(client, headers, pid, qty, lots=None, **kw):
    body = {"product_id": pid, "qty": qty, "reason": "muddati o'tgan",
            "client_uuid": str(uuid.uuid4()), **kw}
    if lots is not None:
        body["lots"] = lots
    return client.post("/api/v1/inventory/writeoff", headers=headers, json=body)


def _allocs(mv_id=None):
    from app.models.inventory import StockMovementLotAllocation as A
    with _db() as db:
        q = db.query(A)
        if mv_id:
            q = q.filter(A.stock_movement_id == mv_id)
        return q.all()


def _q(pid):
    """Mahsulot qoldig'i — filialni partiyadan o'qiydi (test har xil ctx'da ishlasin)."""
    from app.models.inventory import Inventory
    with _db() as db:
        r = (db.query(Inventory)
             .filter(Inventory.product_id == uuid.UUID(pid)).first())
        return float(r.qty) if r else 0.0


def _by_expiry(pid):
    return sorted(_lots(pid), key=lambda b: (b.expiry_date is None, b.expiry_date))


# ══ 1. PARTIYA MAJBURIY ═════════════════════════════════════════════════════

def test_KUZATUVLI_mahsulotda_partiyasiz_RAD(client, admin_headers, ctx, sup):
    """Partiyasiz so'rov — 400. Ilgari bu yo'l 409 bilan UMUMAN bloklangan edi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 50, D10).status_code == 200
    r = _wo(client, admin_headers, pid, 3)
    assert r.status_code == 400, r.text
    assert "TAXMIN" in r.json()["detail"]
    assert _q(pid) == 10.0, "rad etilgan amal qoldiqni o'zgartirdi"


def test_KUZATUVSIZ_mahsulotga_partiya_berilsa_RAD(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    assert _recv_plain(client, admin_headers, sup, pid, 5, 10).status_code == 200
    r = _wo(client, admin_headers, pid, 1,
            lots=[{"stock_batch_id": str(uuid.uuid4()), "qty": 1}])
    assert r.status_code == 400, r.text
    assert "kuzatuvi yoqilmagan" in r.json()["detail"]


def test_KUZATUVSIZ_yol_ESKICHA_ishlaydi(client, admin_headers, ctx, sup):
    """Mavjud kuzatuvsiz xulq O'ZGARMAYDI — Phase 3 uni buzmasligi shart."""
    pid = _product(client, admin_headers)
    assert _recv_plain(client, admin_headers, sup, pid, 5, 10).status_code == 200
    r = _wo(client, admin_headers, pid, 2)
    assert r.status_code == 200, r.text
    assert r.json()["new_qty"] == 3.0
    assert "cost_total" not in r.json(), "kuzatuvsiz yo'lda partiya tannarxi yo'q"


# ══ 2. AYNAN KO'RSATILGAN PARTIYA KAMAYADI ══════════════════════════════════

def test_KOERSATILGAN_partiya_kamayadi_boshqasi_TEGILMAYDI(
        client, admin_headers, ctx, sup):
    """FEFO bo'lsa D10 kamayardi. Operator D20 ni tanladi — AYNAN o'sha kamaysin."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 4, 50, D10).status_code == 200
    assert _recv(client, admin_headers, sup, pid, 6, 70, D20).status_code == 200
    erta, kech = _by_expiry(pid)
    assert erta.expiry_date == D10 and kech.expiry_date == D20

    r = _wo(client, admin_headers, pid, 2,
            lots=[{"stock_batch_id": str(kech.id), "qty": 2}])
    assert r.status_code == 200, r.text

    erta2, kech2 = _by_expiry(pid)
    assert Decimal(str(erta2.remaining_qty)) == 4, "FEFO taxmin qildi — noto'g'ri partiya"
    assert Decimal(str(kech2.remaining_qty)) == 4
    assert _q(pid) == 8.0
    assert r.json()["cost_total"] == 140.0, "2 x 70 = ANIQ tannarx"
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


def test_KOEP_partiyaga_bolinadi_va_TAFSILOT_yoziladi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 4, 50, D10).status_code == 200
    assert _recv(client, admin_headers, sup, pid, 6, 70, D20).status_code == 200
    erta, kech = _by_expiry(pid)

    r = _wo(client, admin_headers, pid, 5,
            lots=[{"stock_batch_id": str(erta.id), "qty": 3},
                  {"stock_batch_id": str(kech.id), "qty": 2}])
    assert r.status_code == 200, r.text
    assert r.json()["cost_total"] == 290.0, "3x50 + 2x70 — ANIQ, o'rtachadan emas"

    rows = [a for a in _allocs() if a.product_id == uuid.UUID(pid)]
    assert len(rows) == 2, "partiya tafsiloti yozilmadi"
    assert sum(Decimal(str(a.qty)) for a in rows) == 5
    # ⚠️  BITTA AGREGAT harakat — `ux_stockmov_client_prod_type` boshqasiga
    #     ruxsat ham bermaydi.
    assert len({a.stock_movement_id for a in rows}) == 1
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


def test_partiya_BOSHAGANDA_depleted(client, admin_headers, ctx, sup):
    """Bo'shagan partiya `depleted` — ALOHIDA `written_off` holati YARATILMAYDI.

    Sabab: yangi holat `stock_invariant` ga o'rgatilishi kerak bo'lardi va
    hech qanday yangi ma'lumot bermasdi. «Nega bo'shadi» degan savolga
    `stock_movements` javob beradi.
    """
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 3, 50, D10).status_code == 200
    b = _lots(pid)[0]
    assert _wo(client, admin_headers, pid, 3,
               lots=[{"stock_batch_id": str(b.id), "qty": 3}]).status_code == 200
    b2 = _lots(pid)[0]
    assert Decimal(str(b2.remaining_qty)) == 0
    assert b2.status == SI.DEPLETED
    assert b2.status in SI.KNOWN_STATUSES, "invariant bilmaydigan holat yozildi"


# ══ 3. TIZIM FARQNI TAQSIMLAMAYDI ═══════════════════════════════════════════

def test_YIGINDI_mos_kelmasa_RAD(client, admin_headers, ctx, sup):
    """`Σ lots[].qty != qty` — farqni tizim JIMGINA to'ldirmaydi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 50, D10).status_code == 200
    b = _lots(pid)[0]
    r = _wo(client, admin_headers, pid, 5,
            lots=[{"stock_batch_id": str(b.id), "qty": 3}])
    assert r.status_code == 400, r.text
    assert "mos" in r.json()["detail"]
    assert _q(pid) == 10.0
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 10


def test_partiyada_YETARLI_boelmasa_RAD(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 4, 50, D10).status_code == 200
    assert _recv(client, admin_headers, sup, pid, 6, 70, D20).status_code == 200
    erta, _ = _by_expiry(pid)
    r = _wo(client, admin_headers, pid, 5,
            lots=[{"stock_batch_id": str(erta.id), "qty": 5}])
    assert r.status_code == 400, r.text
    assert "MANFIYGA" in r.json()["detail"]
    assert _q(pid) == 10.0


def test_BEGONA_partiya_RAD(client, admin_headers, ctx, sup):
    """Boshqa mahsulotning partiyasi — 400, va hech narsa o'zgarmaydi."""
    pid = _product(client, admin_headers)
    other = _product(client, admin_headers)
    for p in (pid, other):
        _enable(client, admin_headers, p)
        assert _recv(client, admin_headers, sup, p, 5, 50, D10).status_code == 200
    ob = _lots(other)[0]
    r = _wo(client, admin_headers, pid, 2,
            lots=[{"stock_batch_id": str(ob.id), "qty": 2}])
    assert r.status_code == 400, r.text
    assert _q(pid) == 5.0
    assert Decimal(str(_lots(other)[0].remaining_qty)) == 5


def test_TAKROR_partiya_RAD(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 9, 50, D10).status_code == 200
    b = _lots(pid)[0]
    r = _wo(client, admin_headers, pid, 4,
            lots=[{"stock_batch_id": str(b.id), "qty": 2},
                  {"stock_batch_id": str(b.id), "qty": 2}])
    assert r.status_code == 400, r.text
    assert "ikki marta" in r.json()["detail"]


def test_QOLDIQDAN_oshiq_RAD(client, admin_headers, ctx, sup):
    """Umumiy qoldiq tekshiruvi partiya tekshiruvidan OLDIN ishlaydi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 3, 50, D10).status_code == 200
    b = _lots(pid)[0]
    r = _wo(client, admin_headers, pid, 9,
            lots=[{"stock_batch_id": str(b.id), "qty": 9}])
    assert r.status_code == 400, r.text
    assert "Yetarli qoldiq yo'q" in r.json()["detail"]


# ══ 4. IDEMPOTENTLIK ════════════════════════════════════════════════════════

def test_QAYTA_yuborish_IKKI_marta_kamaytirmaydi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 50, D10).status_code == 200
    b = _lots(pid)[0]
    cu = str(uuid.uuid4())
    body = {"product_id": pid, "qty": 4, "reason": "brak", "client_uuid": cu,
            "lots": [{"stock_batch_id": str(b.id), "qty": 4}]}
    r1 = client.post("/api/v1/inventory/writeoff", headers=admin_headers, json=body)
    r2 = client.post("/api/v1/inventory/writeoff", headers=admin_headers, json=body)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200 and r2.json().get("duplicate") is True, r2.text
    assert _q(pid) == 6.0
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 6
    rows = [a for a in _allocs() if a.product_id == uuid.UUID(pid)]
    assert len(rows) == 1, "takror yuborish ikkinchi tafsilot yozdi"


# ══ 5. KASSAGA TEGMAYDI ═════════════════════════════════════════════════════

def test_hisobdan_chiqarish_KASSAGA_tegmaydi(client, admin_headers, ctx, sup):
    """Tashlangan tovar — zaxira yo'qotishi, kassa amali EMAS."""
    from app.models.shifts import CashMovement
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 5, 50, D10).status_code == 200
    b = _lots(pid)[0]
    with _db() as db:
        oldin = db.query(CashMovement).count()
    assert _wo(client, admin_headers, pid, 2,
               lots=[{"stock_batch_id": str(b.id), "qty": 2}]).status_code == 200
    with _db() as db:
        assert db.query(CashMovement).count() == oldin, "kassa harakati yozildi"


# ══ 6. MAJBURIY SXEMA VA RESET ══════════════════════════════════════════════

def test_PHASE3_obyektlari_MAJBURIY_va_TUZATILADI():
    from app.core import required_schema as rs
    from app.initdb import _ADDED_COLUMNS
    names = {f"{a}.{b}" for a, b in rs.REQUIRED_COLUMNS}
    for c in ("company_id", "stock_movement_id", "stock_batch_id", "product_id",
              "qty", "unit_cost"):
        assert f"stock_movement_lot_allocations.{c}" in names, c
    assert ("ux_smove_alloc", "stock_movement_lot_allocations") in rs.REQUIRED_INDEXES
    # Phase 1 darsi: tuzatish qadami yo'q majburiy obyekt = abadiy boot-loop.
    added = {(t, c) for t, c, _ in _ADDED_COLUMNS}
    assert not [p for p in rs.REQUIRED_COLUMNS if p not in added]
    # Tezlik indeksi ATAYLAB majburiy EMAS.
    assert "ix_smove_alloc_lot" not in {i for i, _ in rs.REQUIRED_INDEXES}


def test_RESET_grafida_harakat_tafsiloti_BOR():
    from app.services import catalog_reset as CR
    for plan in (CR.BLOCKERS, CR.DELETE_PLAN, CR.COUNT_PLAN, CR.DIGEST_PLAN):
        assert "stock_movement_lot_allocations" in [n for n, _ in plan]
    assert "stock_movement_lot_allocations" in CR.KNOWN_PRODUCT_REFERRERS
    d = [n for n, _ in CR.DELETE_PLAN]
    # Tafsilot HAM harakatga, HAM partiyaga FK bilan bog'langan.
    assert d.index("stock_movement_lot_allocations") < d.index("stock_movements")
    assert d.index("stock_movement_lot_allocations") < d.index("stock_batches")
