# -*- coding: utf-8 -*-
"""PHASE 5B — PARTIYA TAFSILOTIDA MAYDON DARAJASIDAGI RUXSAT.

`GET /lots/batches/{id}` faqat `ombor.view` talab qiladi. Ombor ma'lumoti
(miqdor, sana, tannarx, jamilar) shu ruxsat bilan ochiq qoladi, lekin uch daraja
ALOHIDA ruxsat bilan yopiladi:

  xarid   — `xaridlar.view`                    : ta'minotchi, qabul/xarid hujjati
  sotuv   — `sotuvlar.view` YOKI `hisobot.view` : `sale_id`, chek raqami
  xodim   — `hisobot.view`                     : harakatni KIM qilgani

⚠️  QATOR VA KALIT HECH QACHON TUSHIRILMAYDI. Yopilgan qiymat — null, ro'yxat
    uzunligi, jamilar va sanoqlar ruxsatga qarab o'zgarmaydi: aks holda «qabul −
    sotuv = qoldiq» va qisqartirish eslatmasi yolg'on bo'lardi.

⚠️  OVERRIDE SINOVLARI ALOHIDA XODIMDA. Umumiy `_staff` keshi boshqa fayllar
    bilan bo'lingan va tarif limiti 10 foydalanuvchi — override unga yozilsa,
    boshqa fayllardagi 403/200 kutuvlari jimgina ag'darilardi.
"""
import contextlib
import uuid

import pytest

from tests.test_lot_fefo_sale import (  # noqa: F401
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


@pytest.fixture()
def partiya(client, admin_headers, ctx, sup):
    """Bitta sotuv va bitta hisobdan chiqarishli partiya — tarixning ikkala turi bor."""
    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=False).status_code == 200
    assert _recv(client, admin_headers, sup, pid, 10, 12, batch="MAYDON-1").status_code == 200
    lot_id = str(_lots(pid)[0].id)
    s = _sell(client, admin_headers, pid, 3)
    assert s.status_code == 200, s.text
    w = client.post("/api/v1/inventory/writeoff", headers=admin_headers, json={
        "product_id": pid, "qty": 2, "reason": "expired",
        "lots": [{"stock_batch_id": lot_id, "qty": 2}], "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 200, w.text
    me = client.get("/api/v1/auth/me", headers=admin_headers)
    assert me.status_code == 200, me.text
    return {"pid": pid, "lot": lot_id, "sale_id": s.json()["id"],
            "admin_name": me.json()["full_name"]}


@contextlib.contextmanager
def _xodim(client, admin_headers, rol, override=None):
    """ALOHIDA xodim (ixtiyoriy override bilan) — blokdan chiqishda O'CHIRILADI."""
    phone = "+99890" + str(uuid.uuid4().int % 10_000_000).zfill(7)
    pw = "Toshkent-Kuz-2026"
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": f"5B maydon {rol}", "phone": phone, "password": pw, "role_code": rol})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    try:
        if override:
            p = client.patch(f"/api/v1/employees/{eid}/permissions", headers=admin_headers,
                             json={"overrides": override})
            assert p.status_code == 200, p.text
            # Override HAQIQATAN qo'llangan — aks holda matritsa rolni o'lchardi, override'ni emas.
            perms = set(p.json()["permissions"])
            for code, allowed in override.items():
                assert (code in perms) is allowed, (code, sorted(perms))
        lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": pw})
        assert lg.status_code == 200, lg.text
        yield {"Authorization": f"Bearer {lg.json()['access_token']}"}
    finally:
        rm = client.delete(f"/api/v1/employees/{eid}", headers=admin_headers)
    # Sinov o'zi yiqilgan bo'lsa bu qatorga yetilmaydi — asl xato yashirinmaydi.
    assert rm.status_code == 200, f"xodim o'chirilmadi — tarif limiti band qoladi: {rm.text}"


def _tafsilot(client, headers, lot_id):
    r = client.get(f"/api/v1/lots/batches/{lot_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _shakl(v):
    """Qiymatsiz SKELET: har darajadagi kalitlar va ro'yxat uzunliklari."""
    if isinstance(v, dict):
        return {k: _shakl(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_shakl(x) for x in v]
    return None


def _ombor_malumoti_OZGARMAGAN(d, admin):
    """Ruxsatdan QAT'I NAZAR bir xil qolishi shart bo'lgan ombor ma'lumoti."""
    for k in ("received_qty", "remaining_qty", "unit_cost", "value", "cost_basis",
              "totals", "history_counts", "history_limit", "returns", "resolutions"):
        assert d[k] == admin[k], (k, d[k], admin[k])
    assert len(d["sales"]) == len(admin["sales"])
    assert len(d["movements"]) == len(admin["movements"])
    for s, a in zip(d["sales"], admin["sales"]):
        assert (s["sold_at"], s["qty"], s["unit_cost"]) == (a["sold_at"], a["qty"], a["unit_cost"])
    for m, a in zip(d["movements"], admin["movements"]):
        assert ((m["movement_id"], m["type"], m["qty"], m["reason"], m["created_at"])
                == (a["movement_id"], a["type"], a["qty"], a["reason"], a["created_at"]))


def test_OMBORCHI_tafsilotda_sotuv_hujjati_va_xodim_ismini_KORMAYDI(client, admin_headers, partiya):
    """`omborchi`: ombor.view va xaridlar.view BOR, sotuvlar.view va hisobot.view YO'Q."""
    admin = _tafsilot(client, admin_headers, partiya["lot"])
    # NEGATIV NAZORAT: to'liq ruxsatli xodim hammasini ko'radi — sinov bo'sh o'tmasin.
    assert admin["sales"][0]["sale_id"] == partiya["sale_id"]
    assert admin["sales"][0]["receipt_no"]
    assert admin["movements"][0]["employee"] == partiya["admin_name"]

    h = _staff(client, admin_headers, "omborchi")
    d = _tafsilot(client, h, partiya["lot"])
    s, m = d["sales"][0], d["movements"][0]
    assert s["sale_id"] is None and s["receipt_no"] is None, s
    assert s["qty"] == 3.0 and s["sold_at"], s
    assert m["employee"] is None, m
    assert m["type"] and m["qty"] == admin["movements"][0]["qty"] and m["reason"] == "expired", m
    # Omborchida xaridlar.view BOR — xarid darajasi yopilmaydi.
    assert d["supplier"] and d["source"]["receiving"], d["source"]
    _ombor_malumoti_OZGARMAGAN(d, admin)
    assert d["received_qty"] - d["totals"]["sold_qty"] - d["totals"]["movement_qty"] == d["remaining_qty"]
    # Bayroq: null «ruxsat yo'q» dan kelgani UI ga aytiladi.
    assert admin["redacted"] == {"purchasing": False, "sales": False, "staff": False}
    assert d["redacted"] == {"purchasing": False, "sales": True, "staff": True}


def test_SHAKL_ruxsatga_qarab_OZGARMAYDI_tafsilot_va_qarz(client, admin_headers, ctx, sup, partiya):
    """Kalitlar har darajada va ro'yxat uzunliklari admin bilan omborchida BIR XIL."""
    h = _staff(client, admin_headers, "omborchi")
    admin = _tafsilot(client, admin_headers, partiya["lot"])
    d = _tafsilot(client, h, partiya["lot"])
    assert d != admin, "negativ nazorat: qiymatlar farq qilishi shart"
    assert _shakl(d) == _shakl(admin)

    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=False).status_code == 200
    assert _recv(client, admin_headers, sup, pid, 1, 10).status_code == 200
    assert _replay(client, admin_headers, pid, 3).status_code == 200
    sfs = client.get("/api/v1/lots/shortfalls", headers=admin_headers).json()["shortfalls"]
    sf = [x for x in sfs if x["product_id"] == pid][0]
    sa = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=admin_headers).json()
    so = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=h).json()
    assert sa["sale"] and so["sale"] and so != sa
    assert _shakl(so) == _shakl(sa)


# (nom, rol, override, xarid, sotuv, xodim) — rol None: `admin_headers` (seed egasi).
MATRITSA = [
    ("ega", None, None, True, True, True),
    ("administrator", "administrator", None, True, True, True),
    ("menejer", "menejer", None, False, True, True),
    ("omborchi", "omborchi", None, True, False, False),
    ("omborchi+sotuvlar.view", "omborchi", {"sotuvlar.view": True}, True, True, False),
    ("omborchi+hisobot.view", "omborchi", {"hisobot.view": True}, True, True, True),
    # sotuv darajasi sotuvlar.view orqali OCHIQ qoladi, xodim darajasi esa yopiladi.
    ("menejer-hisobot.view", "menejer", {"hisobot.view": False}, False, True, False),
    # Rol emas, SAMARALI ruxsat o'lchanadi: kassirdan hammasi olinib, faqat ombor.view berilgan.
    ("faqat-ombor.view", "kassir", {"ombor.view": True, "sotuvlar.view": False,
                                    "kassa.sell": False, "kassa.view": False,
                                    "qaytarishlar.create": False, "mijozlar.view": False},
     False, False, False),
]


@pytest.mark.parametrize("nom,rol,override,xarid,sotuv,xodim", MATRITSA, ids=[m[0] for m in MATRITSA])
def test_RUXSAT_MATRITSASI_rol_va_override_boyicha(client, admin_headers, partiya,
                                                   nom, rol, override, xarid, sotuv, xodim):
    admin = _tafsilot(client, admin_headers, partiya["lot"])

    @contextlib.contextmanager
    def _sarlavha():
        if rol is None:
            yield admin_headers
        elif override is None and rol != "administrator":
            # Standart rol — umumiy kesh (override YO'Q, ya'ni u o'zgartirilmaydi).
            yield _staff(client, admin_headers, rol)
        else:
            with _xodim(client, admin_headers, rol, override) as h:
                yield h

    with _sarlavha() as h:
        d = _tafsilot(client, h, partiya["lot"])
        rows = client.get("/api/v1/lots/batches", headers=h, params={"product_id": partiya["pid"]})
    assert rows.status_code == 200, rows.text

    s, a = d["sales"][0], admin["sales"][0]
    m = d["movements"][0]
    if xarid:
        assert d["supplier"] == admin["supplier"] and d["source"] == admin["source"]
    else:
        assert d["supplier"] is None and d["supplier_id"] is None
        assert d["source"]["receiving"] is None and d["source"]["purchase"] is None
        assert d["source"]["type"] == admin["source"]["type"]
    if sotuv:
        assert (s["sale_id"], s["receipt_no"]) == (partiya["sale_id"], a["receipt_no"])
    else:
        assert s["sale_id"] is None and s["receipt_no"] is None, s
    if xodim:
        assert m["employee"] == partiya["admin_name"]
    else:
        assert m["employee"] is None, m
    _ombor_malumoti_OZGARMAGAN(d, admin)
    assert d["redacted"] == {"purchasing": not xarid, "sales": not sotuv, "staff": not xodim}, nom

    # Ro'yxat ham ruxsatsiz null ni «ta'minotchi yo'q» dan ajratadi.
    lst = rows.json()
    assert (lst["lots"][0]["supplier"] is not None) is xarid
    assert lst["redacted"] == {"purchasing": not xarid}


def test_QARZ_tafsilotida_sale_id_YOPIQ_chek_raqami_QOLADI(client, admin_headers, ctx, sup):
    """Qarz tafsiloti: `sale_id` `/sales/{id}` orqali kassir va narxni ochardi."""
    from app.models.sales import SaleItem
    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=False).status_code == 200
    assert _recv(client, admin_headers, sup, pid, 1, 10).status_code == 200
    assert _replay(client, admin_headers, pid, 3).status_code == 200
    sfs = client.get("/api/v1/lots/shortfalls", headers=admin_headers).json()["shortfalls"]
    sf = [x for x in sfs if x["product_id"] == pid][0]
    with _db() as db:
        sale_id = str(db.get(SaleItem, uuid.UUID(sf["sale_item_id"])).sale_id)

    admin = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=admin_headers).json()
    # NEGATIV NAZORAT: to'liq ruxsat bilan sotuv identifikatori ko'rinadi.
    assert admin["sale"]["sale_id"] == sale_id

    h = _staff(client, admin_headers, "omborchi")
    d = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=h).json()
    assert d["sale"]["sale_id"] is None, d["sale"]
    assert d["sale"]["receipt_no"] == admin["sale"]["receipt_no"], "chek raqami qarzni topish uchun QOLADI"
    assert d["sale"]["qty"] == admin["sale"]["qty"] and d["open_qty"] == admin["open_qty"]
    assert admin["redacted"] == {"sales": False}
    assert d["redacted"] == {"sales": True}


def test_50_dan_KATTA_tarixda_omborchi_jamilari_TOLIQ_sale_id_YOPIQ(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=False).status_code == 200
    assert _recv(client, admin_headers, sup, pid, 60, 10, batch="BAND-5B").status_code == 200
    for _ in range(55):
        assert _sell(client, admin_headers, pid, 1).status_code == 200
    lot = str(_lots(pid)[0].id)
    admin = _tafsilot(client, admin_headers, lot)
    assert all(s["sale_id"] for s in admin["sales"]), "negativ nazorat: admin ko'rishi shart"

    d = _tafsilot(client, _staff(client, admin_headers, "omborchi"), lot)
    assert len(d["sales"]) == 50                          # ro'yxat cheklangan
    assert d["totals"]["sold_qty"] == 55.0, d["totals"]   # jami — cheklanmagan
    assert d["history_counts"]["sales"] == 55
    assert all(s["sale_id"] is None and s["receipt_no"] is None for s in d["sales"])
    assert d["totals"] == admin["totals"] and d["history_counts"] == admin["history_counts"]
    assert d["received_qty"] - d["totals"]["sold_qty"] == d["remaining_qty"]
