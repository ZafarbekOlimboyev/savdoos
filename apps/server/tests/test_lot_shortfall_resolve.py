# -*- coding: utf-8 -*-
"""PHASE 2.5 — ANIQ vs TAXMINIY COGS, va QARZNI YOPISH oqimi.

Ikki savolga javob beradi:

  1. Offline chekda taqsimlanmagan miqdor bo'lsa, uning tannarxi HAQIQATAN
     noma'lum. Butun qatorni «aniq COGS» deb atash YOLG'ON bo'lardi, shu bois
     taxminiy ulush `SaleItem.cost_unresolved` da ALOHIDA turadi:

         ANIQ     = cost_total - cost_unresolved
         TAXMINIY = cost_unresolved

  2. Qarzni keyinchalik haqiqiy partiyaga yopish `Inventory.qty` ni
     O'ZGARTIRMASLIGI shart — bu ATRIBUTSIYA amali, miqdor amali emas.
"""
import uuid
from decimal import Decimal

from app.models.sales import SaleItem
from app.services import stock_invariant as SI

# Fixtures va yordamchilar bitta joyda turadi (nusxa ko'paytirmaymiz).
from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    _db,
    _enable,
    _inv,
    _lots,
    _product,
    _recv,
    _replay,
    _sell,
    ctx,
    sup,
)


def _sf(client, admin_headers, pid):
    r = client.get("/api/v1/lots/shortfalls", headers=admin_headers)
    assert r.status_code == 200, r.text
    rows = [x for x in r.json()["shortfalls"] if x["product_id"] == pid]
    return rows[0] if rows else None


def _open_lot(pid):
    return [l for l in _lots(pid) if Decimal(str(l.remaining_qty)) > 0][0]


# ══ 1. ANIQ vs TAXMINIY COGS ════════════════════════════════════════════════

def test_QARZLI_sotuvda_COGS_qismi_TAXMINIY(client, admin_headers, ctx, sup):
    """4 dona ANIQ partiyadan, 6 dona TAXMINIY (mahsulotning olish narxidan).

    ⚠️  TAXMIN ASOSI `base_buy_price`, VA U KIRIMDA YANGILANADI. `receiving.py`
        kirim narxi mahsulot narxidan farq qilsa `base_buy_price` ni yangilaydi,
        shu bois bu yerda u 50 ga aylanadi. Test shu qiymatni O'QIB oladi —
        qo'lda yozilgan son keyin jimgina eskirib qolardi.
    """
    from app.models.catalog import Product
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=70)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    assert _replay(client, admin_headers, pid, 10).json()["results"][0]["ok"] is True
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        base = Decimal(str(db.get(Product, uuid.UUID(pid)).base_buy_price))
    aniq = Decimal("4") * Decimal("50")            # haqiqiy partiyadan
    taxmin = Decimal("6") * base                   # qarz ulushi
    assert Decimal(str(si.cost_unresolved)) == taxmin, (si.cost_unresolved, base)
    assert Decimal(str(si.cost_total)) == aniq + taxmin, si.cost_total
    assert (Decimal(str(si.cost_total))
            - Decimal(str(si.cost_unresolved))) == aniq
    assert taxmin > 0, "taxminiy ulush nol — sinov bo'sh bo'lardi"


def test_TOLIQ_taqsimlanganda_TAXMIN_NOL(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 55, D10)
    assert _sell(client, admin_headers, pid, 4).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
    assert Decimal(str(si.cost_unresolved or 0)) == Decimal("0")
    assert Decimal(str(si.cost_total)) == Decimal("220.00")


def test_KUZATUVSIZ_sotuvda_ham_TAXMIN_NOL(client, admin_headers, ctx, sup):
    from tests.test_lot_fefo_sale import _recv_plain
    pid = _product(client, admin_headers, buy=55)
    assert _recv_plain(client, admin_headers, sup, pid, 10, 55).status_code == 200
    assert _sell(client, admin_headers, pid, 2).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
    assert Decimal(str(si.cost_unresolved or 0)) == Decimal("0")


# ══ 2. QARZNI YOPISH — QOLDIQ O'ZGARMAYDI ═══════════════════════════════════

def test_yopish_QOLDIQNI_ozgartirmaydi(client, admin_headers, ctx, sup):
    """partiya -= k va qarz -= k  =>  Inventory.qty AYNI qoladi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 2, 50, D10)
    assert _replay(client, admin_headers, pid, 6).json()["results"][0]["ok"] is True
    assert _inv(pid, bid) == Decimal("-4.000")

    _recv(client, admin_headers, sup, pid, 10, 60, D20)
    inv_before = _inv(pid, bid)
    sf = _sf(client, admin_headers, pid)
    assert sf is not None and sf["open_qty"] == 4.0

    r = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
                    json={"stock_batch_id": str(_open_lot(pid).id), "qty": 4,
                          "reason": "inventarizatsiyada topildi"})
    assert r.status_code == 200, r.text
    assert r.json()["closed"] is True
    assert _inv(pid, bid) == inv_before, "yopish QOLDIQNI o'zgartirdi"
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


def test_yopish_IDEMPOTENT(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 4)
    _recv(client, admin_headers, sup, pid, 10, 60, D20)
    sf = _sf(client, admin_headers, pid)
    body = {"stock_batch_id": str(_open_lot(pid).id), "qty": 2,
            "reason": "takror sinovi", "client_uuid": str(uuid.uuid4())}
    r1 = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve",
                     headers=admin_headers, json=body)
    r2 = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve",
                     headers=admin_headers, json=body)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r2.json().get("duplicate") is True, r2.text
    assert _sf(client, admin_headers, pid)["resolved_qty"] == 2.0, \
        "takror qarzni IKKI marta yopdi"


def test_ORTIQCHA_yopib_bolmaydi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 3)
    _recv(client, admin_headers, sup, pid, 10, 60, D20)
    sf = _sf(client, admin_headers, pid)
    r = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
                    json={"stock_batch_id": str(_open_lot(pid).id), "qty": 99,
                          "reason": "ortiqcha"})
    assert r.status_code == 400, r.text
    assert "ortiqcha" in r.text.lower()


def test_yopish_partiyani_MANFIYGA_tushirmaydi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 5)
    _recv(client, admin_headers, sup, pid, 2, 60, D20)
    sf = _sf(client, admin_headers, pid)
    r = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
                    json={"stock_batch_id": str(_open_lot(pid).id), "qty": 4,
                          "reason": "partiyada yetmaydi"})
    assert r.status_code == 400, r.text
    assert all(Decimal(str(l.remaining_qty)) >= 0 for l in _lots(pid))


def test_yopish_TARIXIY_COGS_ni_QAYTA_YOZMAYDI(client, admin_headers, ctx, sup):
    """Surat o'zgarmas — yopishda haqiqiy narx ma'lum bo'lsa ham chek o'zgarmaydi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 4)
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        before = (Decimal(str(si.cost_total)), Decimal(str(si.cost_unresolved)))
    _recv(client, admin_headers, sup, pid, 10, 999, D20)      # narx butunlay boshqa
    sf = _sf(client, admin_headers, pid)
    assert client.post(
        f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
        json={"stock_batch_id": str(_open_lot(pid).id), "qty": 3,
              "reason": "yopish"}).status_code == 200
    with _db() as db:
        si2 = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        after = (Decimal(str(si2.cost_total)), Decimal(str(si2.cost_unresolved)))
    assert after == before, f"tarixiy COGS qayta yozildi: {before} -> {after}"


def test_yopish_AUDIT_izi_HAR_IKKI_narxni_saqlaydi(client, admin_headers, ctx, sup):
    """Taxminiy va haqiqiy narx ikkalasi ham izda — farq keyin ko'rinadi."""
    from app.models.sync import AuditLog
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 3)
    _recv(client, admin_headers, sup, pid, 10, 60, D20)
    sf = _sf(client, admin_headers, pid)
    client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
                json={"stock_batch_id": str(_open_lot(pid).id), "qty": 1,
                      "reason": "audit sinovi"})
    with _db() as db:
        rows = db.query(AuditLog).filter(
            AuditLog.entity == "lot_shortfall_resolve",
            AuditLog.entity_id == uuid.UUID(sf["id"])).all()
    assert rows, "yopish auditsiz o'tdi"
    a = rows[-1].after
    assert a["reason"] == "audit sinovi"
    assert "provisional_unit_cost" in a and "batch_unit_cost" in a


def test_BOSHQA_mahsulot_partiyasiga_yopib_bolmaydi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    other = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _enable(client, admin_headers, other)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 3)
    _recv(client, admin_headers, sup, other, 10, 60, D20)
    sf = _sf(client, admin_headers, pid)
    r = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
                    json={"stock_batch_id": str(_open_lot(other).id), "qty": 1,
                          "reason": "boshqa mahsulot"})
    assert r.status_code == 400, r.text


def test_qarz_royxati_OCHIQLARNI_koersatadi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 4)
    sf = _sf(client, admin_headers, pid)
    assert sf["open_qty"] == 3.0
    assert sf["sale_item_id"] is not None, "qarz chekka bog'lanmagan"
    body = client.get(f"/api/v1/lots/products/{pid}", headers=admin_headers).json()
    assert body["unresolved_shortfall_qty"] == 3.0
