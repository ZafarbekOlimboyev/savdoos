# -*- coding: utf-8 -*-
"""PHASE 4B.1 — DARVOZA VA YOZUV YUZASI.

Uch savolga javob beradi:

  1. «Bo'lim ko'rinadimi» qarorini SERVER beradi — UI `tracked_products > 0` ni
     o'zi hisoblasa, o'chirilgan mahsulot ortidagi OCHIQ QARZ bilan birga pul
     ekrandan g'oyib bo'lardi.
  2. Sanoqning takroriy yuborish kaliti DB indeksi bilan AYNAN bir xil —
     begona `client_uuid` boshqa mahsulotning sanog'ini yutib yubormaydi.
  3. Muddat kuzatuvi YO'Q mahsulotga muddatli partiya yozib bo'lmaydi.
"""
import uuid

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    _replay,
    ctx,
    sup,
)


def _av(client, headers):
    r = client.get("/api/v1/lots/availability", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_BOLIM_KORINISHINI_server_aytadi(client, admin_headers, ctx, sup):
    """Kuzatuv yoqilmagan, lekin YOQISH MUMKIN bo'lgan muhitda bo'lim OCHIQ."""
    av = _av(client, admin_headers)
    # Sinov muhiti dev — faollashtirish mumkin, demak bo'lim ko'rinadi.
    assert av["activation_allowed"] is True
    assert av["section_visible"] is True
    assert set(("has_lot_data", "environment", "platform_environment")) <= set(av)
    # ⚠️  MUHIT NOMI ENDI HAQIQIY: ilgari bu maydon HAR DOIM `null` edi.
    assert av["environment"] == "dev"


def test_OCHIQ_QARZ_kuzatuvdan_UZOQ_yashaydi_va_bolim_OCHIQ_qoladi(client, admin_headers, ctx, sup):
    """Mahsulot o'chirilsa `tracked_products` nolga tushishi mumkin — pul esa qoladi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 2, 50)
    assert _replay(client, admin_headers, pid, 6).status_code == 200   # 4 dona qarz

    av = _av(client, admin_headers)
    assert av["has_lot_data"] is True, "ochiq qarz/partiya ko'rinmadi"
    assert av["section_visible"] is True


def test_BEGONA_client_uuid_sanoqni_YUTIB_YUBORMAYDI(client, admin_headers, ctx, sup):
    """Takror kaliti DB indeksi bilan bir xil: (client_uuid, product_id, type)."""
    a = _product(client, admin_headers)
    b = _product(client, admin_headers)
    for pid in (a, b):
        _enable(client, admin_headers, pid, expiry=False)
        _recv(client, admin_headers, sup, pid, 5, 20)
    shared = str(uuid.uuid4())

    la = _lots(a)[0]
    r1 = client.post("/api/v1/inventory/count", headers=admin_headers, json={
        "items": [{"product_id": a, "counted": 4,
                   "lots": [{"stock_batch_id": str(la.id), "counted": 4}]}],
        "client_uuid": shared})
    assert r1.status_code == 200, r1.text
    assert r1.json()["changed"] == 1

    # AYNI kalit, BOSHQA mahsulot — bu DUBLIKAT EMAS va qo'llanishi SHART.
    lb = _lots(b)[0]
    r2 = client.post("/api/v1/inventory/count", headers=admin_headers, json={
        "items": [{"product_id": b, "counted": 3,
                   "lots": [{"stock_batch_id": str(lb.id), "counted": 3}]}],
        "client_uuid": shared})
    assert r2.status_code == 200, r2.text
    assert r2.json().get("duplicate") is not True, "begona kalit sanoqni yutib yubordi"
    from decimal import Decimal
    assert Decimal(str(_lots(b)[0].remaining_qty)) == 3


def test_TAKROR_mahsulot_bir_sorovda_ANIQ_XATO_beradi(client, admin_headers, ctx, sup):
    """Ilgari bu DB darajasida IntegrityError bo'lib, «Ombor band» deb ko'rinardi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 5, 20)
    lot = str(_lots(pid)[0].id)
    r = client.post("/api/v1/inventory/count", headers=admin_headers, json={
        "items": [{"product_id": pid, "counted": 5, "lots": [{"stock_batch_id": lot, "counted": 5}]},
                  {"product_id": pid, "counted": 4, "lots": [{"stock_batch_id": lot, "counted": 4}]}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 400, r.text
    assert "IKKI MARTA" in r.json()["detail"]


def test_MUDDATSIZ_mahsulotga_MUDDATLI_partiya_YOZILMAYDI(client, admin_headers, ctx, sup):
    """FEFO «muddatsiz => NULL» ga tayanadi; bitta sana kogortani jimgina buzardi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 4, 30)
    r = client.post("/api/v1/inventory/count", headers=admin_headers, json={
        "items": [{"product_id": pid, "counted": 6,
                   "new_lots": [{"qty": 2, "unit_cost": 10, "expiry_date": D10.isoformat()}]}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 400, r.text
    assert "KUZATILMAYDI" in r.json()["detail"]
    assert len(_lots(pid)) == 1, "rad etilgan sanoq partiya yaratdi"


def test_MAHSULOT_TAFSILOTI_kuzatuv_belgisini_BERADI(client, admin_headers, ctx, sup):
    """Tahrir formasi muzlagan `expiry_date` ni yozmasligi uchun belgini bilishi shart."""
    pid = _product(client, admin_headers)
    d0 = client.get(f"/api/v1/products/{pid}", headers=admin_headers).json()
    assert (d0["track_lots"], d0["track_expiry"]) == (False, False)   # negativ nazorat
    assert _enable(client, admin_headers, pid).status_code == 200
    d1 = client.get(f"/api/v1/products/{pid}", headers=admin_headers).json()
    assert (d1["track_lots"], d1["track_expiry"]) == (True, True)
