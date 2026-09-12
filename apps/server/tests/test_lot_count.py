# -*- coding: utf-8 -*-
"""PHASE 3 — PARTIYA DARAJASIDAGI INVENTARIZATSIYA (LOT_LEVEL_COUNT).

Ikki qoida bu faylning butun mazmuni:

  1. UMUMIY FARQNI TIZIM TAQSIMLAMAYDI. «10 dona kam chiqdi» qaysi kogortadan
     kam ekanini AYTMAYDI. FEFO bilan taqsimlash muddat hisobotini va tannarxni
     YOLG'ON qilardi.

  2. ORTIQCHA TOPILSA — MAVJUD KOGORTA SHISHIRILMAYDI. Ortiqcha tovarning qabul
     sanasi/muddati/tannarxi NOMA'LUM; uni begona partiyaga qo'shish o'sha
     partiyaning provenansini buzardi. Yangi `source_type='adjustment'` partiya.
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


def _count(client, headers, items, **kw):
    return client.post("/api/v1/inventory/count", headers=headers, json={
        "items": items, "client_uuid": str(uuid.uuid4()), **kw})


def _q(pid):
    from app.models.inventory import Inventory
    with _db() as db:
        r = db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(pid)).first()
        return float(r.qty) if r else 0.0


def _by_expiry(pid):
    return sorted(_lots(pid), key=lambda b: (b.expiry_date is None, b.expiry_date))


def _ok(cid, pid):
    with _db() as db:
        rep = SI.check(db, cid, [uuid.UUID(pid)])
        assert rep.ok, rep.mismatches


# ══ 1. PARTIYA MAJBURIY ═════════════════════════════════════════════════════

def test_PARTIYASIZ_sanoq_RAD(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 50, D10)
    r = _count(client, admin_headers, [{"product_id": pid, "counted": 8}])
    assert r.status_code == 400, r.text
    assert "TAQSIMLAMAYDI" in r.json()["detail"]
    assert _q(pid) == 10.0, "rad etilgan sanoq qoldiqni o'zgartirdi"


def test_KUZATUVSIZ_yol_ESKICHA(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _recv_plain(client, admin_headers, sup, pid, 5, 10)
    r = _count(client, admin_headers, [{"product_id": pid, "counted": 3}])
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == 1
    assert _q(pid) == 3.0


def test_KUZATUVSIZ_mahsulotga_partiya_berilsa_RAD(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _recv_plain(client, admin_headers, sup, pid, 5, 10)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 3,
        "lots": [{"stock_batch_id": str(uuid.uuid4()), "counted": 3}]}])
    assert r.status_code == 400, r.text
    assert "kuzatuvi yoqilmagan" in r.json()["detail"]


# ══ 2. KAM CHIQQANDA — AYNAN KO'RSATILGAN PARTIYA ═══════════════════════════

def test_KAM_chiqqan_partiya_AYNAN_kamayadi(client, admin_headers, ctx, sup):
    """FEFO bo'lsa D10 kamayardi. Operator D20 da kam topdi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _recv(client, admin_headers, sup, pid, 6, 70, D20)
    erta, kech = _by_expiry(pid)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 8,
        "lots": [{"stock_batch_id": str(kech.id), "counted": 4}]}])
    assert r.status_code == 200, r.text
    erta2, kech2 = _by_expiry(pid)
    assert Decimal(str(erta2.remaining_qty)) == 4, "FEFO taxmin qildi"
    assert Decimal(str(kech2.remaining_qty)) == 4
    assert _q(pid) == 8.0
    _ok(cid, pid)


def test_SANALMAGAN_partiya_NOL_deb_tushunilmaydi(client, admin_headers, ctx, sup):
    """Operator bitta partiyani sanadi — qolganini KO'RMAGAN, demak TEGILMAYDI.

    ⚠️  Aks holda javonning bir qismini sanagan operator ko'rmagan partiyalarni
        bilmasdan NOLGA tushirardi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _recv(client, admin_headers, sup, pid, 6, 70, D20)
    erta, kech = _by_expiry(pid)
    # Faqat D10 sanaldi (3 topildi). D20 TEGILMAYDI -> jami 3 + 6 = 9.
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 9,
        "lots": [{"stock_batch_id": str(erta.id), "counted": 3}]}])
    assert r.status_code == 200, r.text
    erta2, kech2 = _by_expiry(pid)
    assert Decimal(str(erta2.remaining_qty)) == 3
    assert Decimal(str(kech2.remaining_qty)) == 6, "sanalmagan partiya o'zgardi"
    assert _q(pid) == 9.0
    _ok(cid, pid)


def test_YIGINDI_mos_kelmasa_RAD(client, admin_headers, ctx, sup):
    """Umumiy son partiyalar yig'indisiga mos kelmasa — farq TAQSIMLANMAYDI."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _recv(client, admin_headers, sup, pid, 6, 70, D20)
    erta, _ = _by_expiry(pid)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 5,      # 3 + 6 = 9 bo'lishi kerak edi
        "lots": [{"stock_batch_id": str(erta.id), "counted": 3}]}])
    assert r.status_code == 400, r.text
    assert "mos emas" in r.json()["detail"]
    assert _q(pid) == 10.0
    _ok(cid, pid)


def test_partiya_NOLGA_tushsa_depleted(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    b = _lots(pid)[0]
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 0,
        "lots": [{"stock_batch_id": str(b.id), "counted": 0}]}])
    assert r.status_code == 200, r.text
    b2 = _lots(pid)[0]
    assert Decimal(str(b2.remaining_qty)) == 0
    assert b2.status == SI.DEPLETED
    assert b2.status in SI.KNOWN_STATUSES
    _ok(cid, pid)


# ══ 3. ORTIQCHA — YANGI PARTIYA, ESKISI SHISHIRILMAYDI ══════════════════════

def test_ORTIQCHA_topilsa_YANGI_partiya(client, admin_headers, ctx, sup):
    """⚠️  Mavjud kogorta SHISHIRILMAYDI — `remaining_qty <= received_qty`
        buzilardi va o'sha kogortaning provenansi YOLG'ON bo'lardi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    manba = _lots(pid)[0]
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 7,
        "lots": [{"stock_batch_id": str(manba.id), "counted": 7}]}])
    assert r.status_code == 200, r.text

    lots = _lots(pid)
    assert len(lots) == 2, "ortiqcha uchun yangi partiya yaratilmadi"
    eski = [x for x in lots if x.id == manba.id][0]
    yangi = [x for x in lots if x.id != manba.id][0]
    assert Decimal(str(eski.remaining_qty)) == 4, "eski kogorta SHISHIRILDI"
    assert Decimal(str(eski.received_qty)) == 4
    assert Decimal(str(yangi.remaining_qty)) == 3
    assert Decimal(str(yangi.received_qty)) == 3
    assert yangi.source_type == "adjustment"
    # Muddat va tannarx TOPILGAN partiyadan ko'chiriladi (operator «shu
    # kogortadan ko'proq chiqdi» deyapti) — taxmin qilingan yangi qiymat emas.
    assert yangi.expiry_date == D10
    assert Decimal(str(yangi.unit_cost)) == 50
    assert _q(pid) == 7.0
    _ok(cid, pid)


def test_HAR_partiya_remaining_received_dan_OSHMAYDI(client, admin_headers, ctx, sup):
    """Phase 3 qarorining butun sababi shu tenglikni saqlash edi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    asl = _lots(pid)[0].id
    # Ketma-ket: ortiqcha -> kam -> yana ortiqcha. Har safar ASL partiya
    # sanaladi, qolganlari (tuzatish partiyalari) TEGILMAYDI.
    for sanoq in (9, 2, 6):
        boshqa = sum(float(x.remaining_qty) for x in _lots(pid) if x.id != asl)
        r = _count(client, admin_headers, [{
            "product_id": pid, "counted": sanoq + boshqa,
            "lots": [{"stock_batch_id": str(asl), "counted": sanoq}]}])
        assert r.status_code == 200, r.text
        for x in _lots(pid):
            assert Decimal(str(x.remaining_qty)) <= Decimal(str(x.received_qty)), (
                f"partiya {x.id} shishdi: {x.remaining_qty} > {x.received_qty}")
        _ok(cid, pid)
    # ASL kogorta hech qachon dastlabki 4 dan oshmadi.
    asl_row = [x for x in _lots(pid) if x.id == asl][0]
    assert Decimal(str(asl_row.received_qty)) == 4


# ══ 4. TAFSILOT, IDEMPOTENTLIK, KASSA ═══════════════════════════════════════

def test_TAFSILOT_yoziladi_va_BITTA_agregat_harakat(client, admin_headers, ctx, sup):
    from app.models.enums import MovementType
    from app.models.inventory import StockMovement, StockMovementLotAllocation as A
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _recv(client, admin_headers, sup, pid, 6, 70, D20)
    erta, kech = _by_expiry(pid)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 7,
        "lots": [{"stock_batch_id": str(erta.id), "counted": 3},
                 {"stock_batch_id": str(kech.id), "counted": 4}]}])
    assert r.status_code == 200, r.text
    with _db() as db:
        mv = db.query(StockMovement).filter(
            StockMovement.product_id == uuid.UUID(pid),
            StockMovement.type == MovementType.adjustment).all()
        assert len(mv) == 1, "agregat emas — bir nechta harakat yozildi"
        rows = db.query(A).filter(A.product_id == uuid.UUID(pid)).all()
        assert len(rows) == 2
        assert sum(Decimal(str(x.qty)) for x in rows) == 3   # 1 + 2 kamaygan
    _ok(cid, pid)


def test_QAYTA_yuborish_IKKI_marta_qollanmaydi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 50, D10)
    b = _lots(pid)[0]
    cu = str(uuid.uuid4())
    body = {"items": [{"product_id": pid, "counted": 6,
                       "lots": [{"stock_batch_id": str(b.id), "counted": 6}]}],
            "client_uuid": cu}
    r1 = client.post("/api/v1/inventory/count", headers=admin_headers, json=body)
    r2 = client.post("/api/v1/inventory/count", headers=admin_headers, json=body)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200 and r2.json().get("duplicate") is True, r2.text
    assert _q(pid) == 6.0
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 6
    _ok(cid, pid)


def test_inventarizatsiya_KASSAGA_tegmaydi(client, admin_headers, ctx, sup):
    from app.models.shifts import CashMovement
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    b = _lots(pid)[0]
    with _db() as db:
        oldin = db.query(CashMovement).count()
    assert _count(client, admin_headers, [{
        "product_id": pid, "counted": 3,
        "lots": [{"stock_batch_id": str(b.id), "counted": 3}]}]).status_code == 200
    with _db() as db:
        assert db.query(CashMovement).count() == oldin
