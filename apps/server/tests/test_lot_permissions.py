# -*- coding: utf-8 -*-
"""PHASE 4B — PARTIYA EKRANLARI KIMGA OCHIQ.

⚠️  FRONTEND HIMOYA EMAS. Manager menyuni ruxsat bo'yicha yashiradi, lekin
    ekranni yashirish — himoya emas: so'rovni qo'lda yuborish mumkin. Shu bois
    HAR endpoint serverda tekshiriladi va bu fayl aynan shuni isbotlaydi.

Standart rollar (`app/seed.py`):
    kassir    — ombor ruxsati YO'Q  -> na o'qish, na yozish
    menejer   — `ombor.view`        -> o'qish HA, yozish YO'Q
    omborchi  — `ombor.view/edit`   -> ikkalasi ham
"""
import uuid

import pytest

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    ctx,
    sup,
)

READS = ("/api/v1/lots/batches", "/api/v1/lots/alerts", "/api/v1/lots/expiring",
         "/api/v1/lots/shortfalls", "/api/v1/lots/availability")


# ⚠️  ROL BO'YICHA BITTA XODIM, SESSIYA BO'YI. Demo do'kon tarifi 10 foydalanuvchi
#     bilan cheklangan va sinov bazasi HAMMA fayl uchun umumiy: har sinovda yangi
#     xodim yaratilsa, limit tugab, BOSHQA fayllardagi sinovlar 403 bilan yiqilardi
#     (aynan shu yuz berdi — 3 ta xavfsizlik sinovi qizil bo'ldi).
_CACHE: dict = {}


def _staff(client, admin_headers, role):
    if role in _CACHE:
        return _CACHE[role]
    phone = "+99890" + str(uuid.uuid4().int % 10_000_000).zfill(7)
    pw = "Toshkent-Kuz-2026"
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": f"4B {role}", "phone": phone, "password": pw, "role_code": role})
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": pw})
    assert lg.status_code == 200, lg.text
    _CACHE[role] = {"Authorization": f"Bearer {lg.json()['access_token']}",
                    "__id": r.json()["id"]}
    return {k: v for k, v in _CACHE[role].items() if not k.startswith("__")}


@pytest.fixture(scope="module", autouse=True)
def _tozalash(client):
    """Fayl tugagach sinov xodimlarini o'chiradi — tarif limitini band qilmasin."""
    yield
    import contextlib
    c = client
    r = c.post("/api/v1/auth/login/password",
               json={"phone": "+998901234567", "password": "demo1234"})
    if r.status_code != 200:
        return
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for v in _CACHE.values():
        with contextlib.suppress(Exception):
            c.delete(f"/api/v1/employees/{v['__id']}", headers=h)
    _CACHE.clear()


@pytest.fixture()
def tracked(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 5, 40, D10, batch="RUX-1").status_code == 200
    return pid, str(_lots(pid)[0].id)


def test_KASSIR_partiya_maʼlumotini_KORA_OLMAYDI(client, admin_headers, tracked):
    """Kassir uchun bu ekranlar YO'Q — server ham shunday deydi."""
    _pid, lot_id = tracked
    h = _staff(client, admin_headers, "kassir")
    # Tafsilot HAQIQIY partiya bilan: 403 «topilmadi» (404) dan emas, ruxsatdan kelsin.
    for path in READS + (f"/api/v1/lots/batches/{lot_id}",):
        assert client.get(path, headers=h).status_code == 403, path


def test_KASSIR_hisobdan_chiqara_ham_sanay_ham_OLMAYDI(client, admin_headers, tracked):
    pid, lot_id = tracked
    h = _staff(client, admin_headers, "kassir")
    w = client.post("/api/v1/inventory/writeoff", headers=h, json={
        "product_id": pid, "qty": 1, "lots": [{"stock_batch_id": lot_id, "qty": 1}],
        "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 403, w.text
    c = client.post("/api/v1/inventory/count", headers=h, json={
        "items": [{"product_id": pid, "counted": 5,
                   "lots": [{"stock_batch_id": lot_id, "counted": 5}]}],
        "client_uuid": str(uuid.uuid4())})
    assert c.status_code == 403, c.text
    # Qoldiq TEGILMAGAN
    from decimal import Decimal
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 5


def test_MENEJER_KORADI_lekin_OZGARTIRA_OLMAYDI(client, admin_headers, tracked):
    """`ombor.view` — ro'yxat va tafsilot ochiq; yozuv amallari YOPIQ."""
    pid, lot_id = tracked
    h = _staff(client, admin_headers, "menejer")
    for path in READS:
        assert client.get(path, headers=h).status_code == 200, path
    d = client.get(f"/api/v1/lots/batches/{lot_id}", headers=h)
    assert d.status_code == 200, d.text

    # Server O'ZI aytadi: ko'rish ha, yozish yo'q — UI shu javobga tayanadi.
    av = client.get("/api/v1/lots/availability", headers=h).json()
    assert av["permissions"]["view"] is True and av["permissions"]["edit"] is False
    assert av["can_write"] is False and av["can_enable"] is False

    w = client.post("/api/v1/inventory/writeoff", headers=h, json={
        "product_id": pid, "qty": 1, "lots": [{"stock_batch_id": lot_id, "qty": 1}],
        "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 403, w.text
    e = client.post("/api/v1/lots/enable", headers=h, json={
        "product_id": pid, "reason": "ruxsatsiz urinish"})
    assert e.status_code == 403, e.text


def test_OMBORCHI_partiya_amallarini_BAJARADI(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 6, 30, D10, batch="RUX-2").status_code == 200
    lot_id = str(_lots(pid)[0].id)
    h = _staff(client, admin_headers, "omborchi")
    av = client.get("/api/v1/lots/availability", headers=h).json()
    assert av["permissions"]["edit"] is True and av["can_write"] is True
    w = client.post("/api/v1/inventory/writeoff", headers=h, json={
        "product_id": pid, "qty": 2, "reason": "expired",
        "lots": [{"stock_batch_id": lot_id, "qty": 2}], "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 200, w.text
    from decimal import Decimal
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 4


def test_QARZNI_YOPISH_faqat_ombor_EDIT_bilan(client, admin_headers, tracked):
    """Yopish foydaga ta'sir qiladi — «ko'rish» huquqi yetmaydi."""
    h = _staff(client, admin_headers, "menejer")
    r = client.post(f"/api/v1/lots/shortfalls/{uuid.uuid4()}/resolve", headers=h, json={
        "stock_batch_id": str(uuid.uuid4()), "qty": 1, "client_uuid": str(uuid.uuid4())})
    # 403 — MAVJUD EMASLIGI (404) dan OLDIN: ruxsat darvozasi birinchi.
    assert r.status_code == 403, r.text
