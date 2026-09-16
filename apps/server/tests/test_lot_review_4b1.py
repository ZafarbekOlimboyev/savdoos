# -*- coding: utf-8 -*-
"""PHASE 4B.1 — MAIN'GA PUSHDAN OLDINGI REVIEW TOPILMALARI.

Har sinov o'zi pinlagan qoida olib tashlansa QIZARADI:

  1. Brauzer floati (1.1 + 2.2) partiya yig'indisini «mos emas» qilmaydi.
  2. Sxema introspeksiyasining bir lahzalik yiqilishi 60 s keshlanmaydi.
  3. `ombor.view` ta'minotchi/xarid va kassir/sotuv narxini OCHMAYDI.
  4. Tafsilot JAMILARI ro'yxat chegarasidan (50) mustaqil.
  5. `status=depleted` filtri tugagan partiyalarni QAYTARADI.
  6. Production shaklida (yoqish yopiq, kuzatuv ham, ma'lumot ham yo'q) bo'lim YOPIQ.
"""
import uuid
from decimal import Decimal

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    _replay,
    _sell,
    ctx,
    sup,
)
from tests.test_lot_permissions import _staff, _tozalash  # noqa: F401


def test_FLOAT_yigindi_hisobdan_chiqarishda_MOS(client, admin_headers, ctx, sup):
    """Manager 1.1 + 2.2 ni float bilan qo'shib 3.3000000000000003 yuboradi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 5, 10, batch="F-A")
    _recv(client, admin_headers, sup, pid, 5, 10, batch="F-B")
    a, b = sorted(_lots(pid), key=lambda x: x.batch_no)
    total = 1.1 + 2.2
    assert total != 3.3                         # NEGATIV NAZORAT: float haqiqatan buzilgan
    r = client.post("/api/v1/inventory/writeoff", headers=admin_headers, json={
        "product_id": pid, "qty": total, "reason": "damaged",
        "lots": [{"stock_batch_id": str(a.id), "qty": 1.1}, {"stock_batch_id": str(b.id), "qty": 2.2}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    a2, b2 = sorted(_lots(pid), key=lambda x: x.batch_no)
    assert Decimal(str(a2.remaining_qty)) == Decimal("3.9")
    assert Decimal(str(b2.remaining_qty)) == Decimal("2.8")


def test_FLOAT_yigindi_sanoqda_MOS(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 1.1, 10, batch="S-A")
    _recv(client, admin_headers, sup, pid, 2.2, 10, batch="S-B")
    a = sorted(_lots(pid), key=lambda x: x.batch_no)[0]
    # Manager: tegilmagan 2.2 + sanalgan 1.1 = float 3.3000000000000003
    r = client.post("/api/v1/inventory/count", headers=admin_headers, json={
        "items": [{"product_id": pid, "counted": 2.2 + 1.1,
                   "lots": [{"stock_batch_id": str(a.id), "counted": 1.1}]}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text


def test_INTROSPEKSIYA_yiqilishi_KESHLANMAYDI(monkeypatch):
    from app.core import required_schema as rs
    from app.services import lot_policy as LP
    LP._SCHEMA_CACHE.clear()
    calls = {"n": 0}

    def flaky(bind):
        calls["n"] += 1
        return ["introspeksiya yiqildi"] if calls["n"] == 1 else []

    monkeypatch.setattr(rs, "missing", flaky)
    bind = object()
    assert LP.schema_problems(bind) == ["introspeksiya yiqildi"]
    # Baza tiklandi — keyingi chaqiruv QAYTA tekshiradi, eski xatoni eslamaydi.
    assert LP.schema_problems(bind) == []
    assert calls["n"] == 2
    LP._SCHEMA_CACHE.clear()


def test_MENEJER_xarid_va_taminotchini_KORMAYDI(client, admin_headers, ctx, sup):
    """`menejer`: ombor.view BOR, xaridlar.view YO'Q."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 3, 10, batch="RX-1")
    lot = str(_lots(pid)[0].id)
    admin = client.get(f"/api/v1/lots/batches/{lot}", headers=admin_headers).json()
    assert admin["supplier"] and admin["source"]["purchase"], "negativ nazorat: admin ko'rishi shart"

    h = _staff(client, admin_headers, "menejer")
    d = client.get(f"/api/v1/lots/batches/{lot}", headers=h).json()
    assert d["supplier"] is None and d["supplier_id"] is None
    assert d["source"]["purchase"] is None
    rows = client.get("/api/v1/lots/batches", headers=h, params={"product_id": pid}).json()["lots"]
    assert rows[0]["supplier"] is None and rows[0]["supplier_id"] is None


def test_OMBORCHI_kassir_va_sotuv_narxini_KORMAYDI(client, admin_headers, ctx, sup):
    """`omborchi`: ombor.view BOR, sotuvlar.view va hisobot.view YO'Q."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 1, 10)
    assert _replay(client, admin_headers, pid, 3).status_code == 200
    sfs = client.get("/api/v1/lots/shortfalls", headers=admin_headers).json()["shortfalls"]
    sf = [x for x in sfs if x["product_id"] == pid][0]
    admin = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=admin_headers).json()
    assert admin["sale"]["unit_price"] is not None, "negativ nazorat: admin ko'rishi shart"

    h = _staff(client, admin_headers, "omborchi")
    d = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=h).json()
    assert d["sale"]["unit_price"] is None and d["sale"]["cashier"] is None
    assert d["sale"]["receipt_no"], "chek raqami qarzni topish uchun QOLISHI kerak"


def test_TAFSILOT_JAMILARI_50_qatordan_KATTA_tarixda_TOGRI(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 60, 10, batch="BAND-1")
    for _ in range(55):
        assert _sell(client, admin_headers, pid, 1).status_code == 200
    lot = str(_lots(pid)[0].id)
    d = client.get(f"/api/v1/lots/batches/{lot}", headers=admin_headers).json()
    assert len(d["sales"]) == 50                          # ro'yxat cheklangan
    assert d["totals"]["sold_qty"] == 55.0, d["totals"]   # jami — cheklanmagan
    assert d["history_counts"]["sales"] == 55
    assert d["received_qty"] - d["totals"]["sold_qty"] == d["remaining_qty"]


def test_DEPLETED_filtri_tugagan_partiyalarni_QAYTARADI(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 2, 10, batch="TUGADI")
    assert _sell(client, admin_headers, pid, 2).status_code == 200
    r = client.get("/api/v1/lots/batches", headers=admin_headers,
                   params={"product_id": pid, "status": "depleted"}).json()
    assert [l["batch_number"] for l in r["lots"]] == ["TUGADI"], r
    r2 = client.get("/api/v1/lots/batches", headers=admin_headers, params={"product_id": pid}).json()
    assert r2["total"] == 0, "standart (ochiq) ro'yxatda tugagan partiya ko'rinmasligi kerak"


def test_PRODUCTION_shaklida_bolim_YOPIQ(client, admin_headers, ctx, monkeypatch):
    """Yoqish yopiq + kuzatuv yo'q + ma'lumot yo'q  =>  section_visible=False."""
    from app.services import lot_policy as LP
    monkeypatch.setattr(LP, "activation_allowed", lambda: False)
    av = client.get("/api/v1/lots/availability", headers=admin_headers).json()
    assert av["activation_allowed"] is False
    # Umumiy sinov bazasida boshqa sinovlar kuzatuvli tovar yaratgan bo'lishi mumkin —
    # shu bois qoidaning O'ZI tekshiriladi: yoqish yopiq bo'lsa ko'rinish FAQAT
    # kuzatuv yoki ma'lumotdan kelib chiqadi. `allowed` ni OR dan olib tashlash
    # yoki qo'shish bu tenglikni buzadi.
    assert av["section_visible"] == bool(av["tracked_products"] > 0 or av["has_lot_data"])


def test_BOLIM_KORINISHI_formulasi_HAQIQAT_JADVALI():
    """Formula endpointdan ajratilgan — production holati DETERMINISTIK tekshiriladi."""
    from app.api.v1.lots_read import section_visible as V
    # production: yoqish yopiq, kuzatuv yo'q, ma'lumot yo'q
    assert V(True, 0, False, False) is False
    # staging, hali yoqilmagan: operator bo'limni TOPISHI kerak
    assert V(True, 0, False, True) is True
    # kuzatuv yoqilgan
    assert V(True, 3, False, False) is True
    # kuzatuv o'chgan, lekin ochiq qarz qolgan — pul ekrandan yo'qolmasin
    assert V(True, 0, True, False) is True
    # ruxsatsiz xodim — hech qachon
    assert V(False, 3, True, True) is False
