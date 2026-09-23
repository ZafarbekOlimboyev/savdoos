# -*- coding: utf-8 -*-
"""PHASE 5G — MOBIL PARITET UCHUN BACKEND QO'SHIMCHALARI (SQLite qismi).

Har band ALOHIDA do'konda quriladi (seed do'koni tegilmaydi): sinovlar bir-birining
filiali, katalogi yoki hujjat raqamini KO'RMAYDI va fayllar tartibiga bog'liq emas.

  1. `GET /auth/context`           — kim, ruxsatlar, yozuv filiali, ko'rinadigan filiallar
  2. `GET /products?limit&offset`  — sahifalash; `limit` siz javob AYNAN avvalgidek
  3. `GET /products/scan`          — shtrix-kod / tarozi etiketkasi (POS bilan AYNI qoida)
  4. `GET /receiving[/{id}]`       — xarid havolasi, hujjat raqami, to'lov turi, ta'minotchi
  5. `GET /purchases/{id}`         — HUJJAT filiali va uning biznes sanasi
  6. `GET /cash/custody-preview`   — SQLite qismi (rejim va ruxsat); PG pariteti — `_pg.py` da
  8. `X-Error-Code`                — matn/holat O'ZGARMAGAN, kod qo'shilgan (4 yozuvchi + 403)
  9. GZip                          — siqilgan tana ochilganda AYNAN siqilmagan tana

⚠️  KUTILGAN MATNLAR NUSXA (koddan import EMAS): matn o'zgarsa test uni KO'RISHI kerak —
    desktop lug'ati (`serverErrorsLots.ts`) shu matnlarni kalit sifatida ishlatadi.
"""
from __future__ import annotations

import gzip
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.security import create_access_token

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
HDR = "X-Error-Code"


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


# ══ DO'KON QURISH ═══════════════════════════════════════════════════════════

def _shop(filiallar: int = 1, *, tz: str = TZ) -> dict:
    """Toza do'kon: filial(lar) (`created_at` bo'yicha ANIQ tartib), `ega` + token, ta'minotchi."""
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="5G " + uuid.uuid4().hex[:6],
                       code="g5" + uuid.uuid4().hex[:8], currency="UZS")
        db.add(comp)
        db.flush()
        bids = []
        for i in range(filiallar):
            br = Branch(id=uuid.uuid4(), company_id=comp.id, name=f"F0{i + 1}", code=f"F0{i + 1}",
                        timezone=tz, is_active=True, created_at=NOW - timedelta(days=10 - i))
            db.add(br)
            db.flush()
            bids.append(br.id)
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id, full_name="5G ega",
                       phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        sup = Supplier(id=uuid.uuid4(), company_id=comp.id, name="5G ta'minotchi")
        db.add(sup)
        db.commit()
        return {"cid": comp.id, "code": comp.code, "name": comp.name, "bids": bids,
                "eid": emp.id, "sup": sup.id, "H": _token(emp.id, "ega", comp.id)}


def _token(eid, role, cid) -> dict:
    tok = create_access_token(str(eid), {"role": role, "company_id": str(cid), "sv": 0})
    return {"Authorization": f"Bearer {tok}"}


def _staff(d: dict, role: str, filiallar=()) -> tuple[dict, uuid.UUID]:
    """Berilgan roldagi xodim; `filiallar` — biriktiriladigan filiallar (`EmployeeBranch`)."""
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.enums import EmployeeStatus
    with _db() as db:
        r = db.query(Role).filter(Role.code == role).one()
        e = Employee(id=uuid.uuid4(), company_id=d["cid"], role_id=r.id, full_name=f"5G {role}",
                     phone=f"+9986{uuid.uuid4().int % 10**7:07d}",
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.flush()
        for b in filiallar:
            db.add(EmployeeBranch(employee_id=e.id, branch_id=b))
        db.commit()
        return _token(e.id, role, d["cid"]), e.id


def _product(d: dict, *, name=None, qty=0, bid=None, tracked=False, expiry=False,
             lots=None, barcode=None, weighted=False, plu=None, active=True, deleted=False):
    """Mahsulot + qoldiq. `tracked` bo'lsa `lots` (miqdorlar ro'yxati; standart — bitta
    `qty` lik ochilish partiyasi) yoziladi: Inventory == Σ remaining (invariant)."""
    from app.models.catalog import Product, ProductBarcode, Unit
    from app.models.inventory import Inventory, StockBatch
    from app.services import stock_invariant as SI
    bid = bid or d["bids"][0]
    with _db() as db:
        unit = db.query(Unit).filter(Unit.code == ("kg" if weighted else "dona")).first() \
            or db.query(Unit).first()
        nm = name or ("5G " + uuid.uuid4().hex[:8])
        p = Product(id=uuid.uuid4(), company_id=d["cid"], name=nm,
                    article_code="G-" + uuid.uuid4().hex[:10], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0,
                    is_active=active, is_weighted=weighted, plu_code=plu,
                    deleted_at=(NOW if deleted else None))
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, branch_id=bid, qty=Decimal(str(qty)), min_qty=0,
                         updated_at=NOW))
        if barcode:
            db.add(ProductBarcode(product_id=p.id, company_id=d["cid"], barcode=barcode,
                                  is_primary=True))
        batch_ids = []
        if tracked:
            for q in (lots if lots is not None else ([qty] if qty else [])):
                qq = Decimal(str(q)).quantize(Decimal("0.001"))
                b = StockBatch(id=uuid.uuid4(), company_id=d["cid"], branch_id=bid,
                               product_id=p.id, qty=qq, received_qty=qq, remaining_qty=qq,
                               unit_cost=Decimal("50.00"), status=SI.OPEN, source_type="legacy",
                               client_uuid=uuid.uuid4(), received_at=NOW, created_at=NOW,
                               updated_at=NOW, row_version=1)
                db.add(b)
                batch_ids.append(b.id)
            p.track_lots = True
            p.track_expiry = bool(expiry)
            p.lots_activated_at = NOW
        db.commit()
        return {"id": p.id, "name": nm, "lots": batch_ids}


def _confirm_tz(d: dict, bid=None):
    from app.services import lot_policy as LP
    with _db() as db:
        LP.confirm_tz(db, d["cid"], bid or d["bids"][0])
        db.commit()


def _hdr(r):
    return r.headers.get(HDR)


# ══ 1. /auth/context ════════════════════════════════════════════════════════

def test_CONTEXT_ega_hamma_filialni_korada_tartib_va_biznes_sanasi(client):
    from app.models.org import Branch
    from app.services import lot_policy as LP
    d = _shop(3)
    with _db() as db:
        # O'chirilgan filial ro'yxatga TUSHMAYDI; NOFAOL filial tushadi (is_active=False).
        db.get(Branch, d["bids"][2]).deleted_at = NOW
        db.get(Branch, d["bids"][1]).is_active = False
        db.commit()
        biz = LP.business_date(db, d["bids"][0]).isoformat()
    r = client.get("/api/v1/auth/context", headers=d["H"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["employee"]["id"] == str(d["eid"]) and j["employee"]["role_code"] == "ega"
    assert j["company"] == {"id": str(d["cid"]), "name": d["name"], "code": d["code"]}
    assert j["full_access"] is True and j["branch_scope"] == "all"
    assert "xaridlar.edit" in j["permissions"] and j["permissions"] == sorted(j["permissions"])
    assert [b["id"] for b in j["branches"]] == [str(d["bids"][0]), str(d["bids"][1])]
    assert [b["is_active"] for b in j["branches"]] == [True, False]
    assert j["branches"][0] == {"id": str(d["bids"][0]), "name": "F01", "is_active": True,
                                "timezone": TZ, "business_date": biz}
    assert j["actor_branch"] == {"id": str(d["bids"][0]), "name": "F01", "timezone": TZ,
                                 "business_date": biz}


def test_CONTEXT_biriktirilgan_xodim_faqat_oz_filiali_va_rol_ruxsatlari(client):
    d = _shop(2)
    h, eid = _staff(d, "menejer", filiallar=[d["bids"][1]])
    j = client.get("/api/v1/auth/context", headers=h).json()
    assert j["full_access"] is False and j["branch_scope"] == "assigned"
    assert [b["id"] for b in j["branches"]] == [str(d["bids"][1])]
    assert j["actor_branch"]["id"] == str(d["bids"][1])
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert j["permissions"] == me["permissions"]           # /auth/me bilan AYNI manba
    assert "xaridlar.edit" not in j["permissions"] and "hisobot.view" in j["permissions"]
    assert j["employee"] == {"id": str(eid), "full_name": "5G menejer",
                             "role_code": "menejer", "role_name": me["role_name"]}


def test_CONTEXT_tokensiz_401(client):
    assert client.get("/api/v1/auth/context").status_code == 401


# ══ 2. /products sahifalash ═════════════════════════════════════════════════

def _eski_royxat(d, branch_id=None):
    """Phase 5G dan OLDINGI algoritm: `name` tartibi + BUTUN kompaniya maplari."""
    from app.api.v1 import products as P
    from app.core.deps import visible_branches
    from app.models.auth import Employee
    from app.models.catalog import Product
    with _db() as db:
        emp = db.get(Employee, d["eid"])
        vb = {branch_id} if branch_id else visible_branches(emp, db)
        ps = (db.query(Product).filter(Product.company_id == d["cid"],
                                       Product.deleted_at.is_(None),
                                       Product.is_active.is_(True))
              .order_by(Product.name).all())
        stock, mins = P._stock_map(db, d["cid"], vb), P._min_map(db, d["cid"], vb)
        units, sold = P._unit_map(db), P._sold_map(db, d["cid"])
        return [P._to_out(p, stock, mins, units, sold).model_dump(mode="json") for p in ps]


def test_PRODUCTS_limit_siz_javob_AVVALGIDEK_va_sarlavhasiz(client):
    d = _shop(2)
    for i, q in enumerate((5, 0, 7)):
        _product(d, name=f"Olma {i}", qty=q)
    _product(d, name="Behi", qty=3, bid=d["bids"][1])
    r = client.get("/api/v1/products", headers=d["H"])
    assert r.status_code == 200 and "x-total-count" not in r.headers
    assert r.json() == _eski_royxat(d)
    rb = client.get(f"/api/v1/products?branch_id={d['bids'][1]}", headers=d["H"])
    assert rb.json() == _eski_royxat(d, d["bids"][1])


def test_PRODUCTS_q_qidiruvi_qiymatlari_OZGARMAYDI(client):
    """`q` bilan maplar faqat mos mahsulotlarga hisoblanadi — qiymatlar esa AYNAN o'sha."""
    d = _shop()
    _product(d, name="Sut 1L", qty=4, barcode="4780000000011")
    _product(d, name="Qatiq", qty=9, barcode="4780000000028")
    _product(d, name="Sutli shokolad", qty=2)
    full = {p["id"]: p for p in _eski_royxat(d)}
    for q, names in (("sut", ["Sut 1L", "Sutli shokolad"]), ("0000028", ["Qatiq"]), ("yo'q", [])):
        r = client.get("/api/v1/products", params={"q": q}, headers=d["H"])
        assert r.status_code == 200, r.text
        got = r.json()
        assert [p["name"] for p in got] == names, (q, got)
        assert all(p == full[p["id"]] for p in got), q


def test_PRODUCTS_limit_offset_sahifalar_BARQAROR_va_jami_son(client):
    d = _shop()
    # BIR XIL nomlar — tartib `name, id` bo'lmasa sahifalar orasida takror/yo'qolish bo'lardi.
    ids = [_product(d, name="Bir xil", qty=i)["id"] for i in range(5)]
    ids += [_product(d, name="Anor", qty=1)["id"], _product(d, name="Uzum", qty=2)["id"]]
    _product(d, name="Arxiv", qty=1, active=False)
    got, total = [], None
    for off in (0, 3, 6):
        r = client.get("/api/v1/products", params={"limit": 3, "offset": off}, headers=d["H"])
        assert r.status_code == 200, r.text
        total = r.headers["X-Total-Count"]
        got += r.json()
    assert total == "7"
    want = sorted(_eski_royxat(d), key=lambda p: (p["name"], p["id"]))
    assert got == want                         # takrorsiz, bo'shliqsiz, qiymatlar AYNI
    r = client.get("/api/v1/products", params={"limit": 3, "offset": 50}, headers=d["H"])
    assert r.json() == [] and r.headers["X-Total-Count"] == "7"
    r = client.get("/api/v1/products", params={"limit": 2, "include_archived": 1},
                   headers={**d["H"], "Origin": "http://localhost:5173"})
    assert r.headers["X-Total-Count"] == "8"
    # Brauzer/Electron o'qiy olishi uchun CORS'da OCHIQ (X-Error-Code bilan birga).
    ochiq = {h.strip().lower() for h in
             r.headers.get("access-control-expose-headers", "").split(",")}
    assert {"x-total-count", "x-error-code"} <= ochiq, r.headers


@pytest.mark.parametrize("qs", ["limit=0", "limit=501", "offset=-1", "limit=abc"])
def test_PRODUCTS_limit_chegaralari_422(client, qs):
    d = _shop()
    assert client.get(f"/api/v1/products?{qs}", headers=d["H"]).status_code == 422


def test_PRODUCTS_limit_filial_doirasi_AVVALGIDEK(client):
    d = _shop(2)
    begona = _shop()
    _product(d, name="A", qty=1)
    h, _e = _staff(d, "menejer", filiallar=[d["bids"][0]])
    assert client.get("/api/v1/products", params={"limit": 5, "branch_id": str(begona["bids"][0])},
                      headers=d["H"]).status_code == 400
    assert client.get("/api/v1/products", params={"limit": 5, "branch_id": str(d["bids"][1])},
                      headers=h).status_code == 403


# ══ 3. /products/scan ═══════════════════════════════════════════════════════

def _scan(client, d, code, **kw):
    r = client.get("/api/v1/products/scan", params={"code": code, **kw}, headers=d["H"])
    assert r.status_code == 200, r.text
    return r.json()


def test_SCAN_shtrix_kod_aniq_yetakchi_nollar_arxiv_ham(client):
    d = _shop()
    a = _product(d, name="Nolli", qty=3, barcode="0012345678905")
    arx = _product(d, name="Arxivda", qty=0, barcode="4780000000035", active=False)
    _product(d, name="O'chgan", barcode="4780000000042", deleted=True)
    j = _scan(client, d, " 0012345678905 ")
    assert j["code"] == "0012345678905" and j["kind"] == "barcode"
    assert j["product"]["id"] == str(a["id"]) and j["product"]["stock"] == 3.0
    assert j["candidates"] == [] and j["scale"] is None
    j = _scan(client, d, "4780000000035")
    assert j["kind"] == "barcode" and j["product"]["id"] == str(arx["id"])
    assert j["product"]["is_active"] is False
    assert _scan(client, d, "4780000000042")["kind"] == "none"
    assert _scan(client, d, "12345678905")["kind"] == "none"     # nolsiz — AYNAN moslik
    j = _scan(client, d, "abc")
    assert (j["code"], j["kind"], j["product"], j["scale"]) == ("", "none", None, None)


def test_SCAN_tarozi_etiketkasi_bitta_kop_va_hech_qaysi(client):
    d = _shop()
    w = _product(d, name="Go'sht", qty=10, weighted=True, plu="123")
    _product(d, name="Donali 123", qty=1, plu="0123")          # vaznli EMAS — hisoblanmaydi
    j = _scan(client, d, "2000123012345")
    assert j["kind"] == "scale" and j["product"]["id"] == str(w["id"])
    assert j["scale"] == {"plu": 123, "grams": 1234, "qty": "1.234"}
    assert j["candidates"] == []
    # Ikki vaznli mahsulot AYNI PLU raqamida (eski ma'lumot: "77" va "0077") -> tanlov.
    x = _product(d, name="Pishloq B", weighted=True, plu="0077")
    y = _product(d, name="Pishloq A", weighted=True, plu="77")
    j = _scan(client, d, "2000077005008")
    assert j["kind"] == "ambiguous" and j["product"] is None
    assert [c["id"] for c in j["candidates"]] == [str(y["id"]), str(x["id"])]   # name, id
    assert j["scale"]["qty"] == "0.500"
    j = _scan(client, d, "2000999001002")
    assert j["kind"] == "none" and j["scale"] == {"plu": 999, "grams": 100, "qty": "0.100"}
    assert _scan(client, d, "2000123000005")["scale"] is None     # 0 gramm — vaznli EMAS


def test_SCAN_aniq_shtrix_kod_TAROZIDAN_USTUN_va_begona_dokon_korinmaydi(client):
    d = _shop()
    begona = _shop()
    _product(d, name="Tarozili", weighted=True, plu="123")
    b = _product(d, name="Kodli", barcode="2000123012345")
    _product(begona, name="Begona", barcode="4780000000059")
    j = _scan(client, d, "2000123012345")
    assert j["kind"] == "barcode" and j["product"]["id"] == str(b["id"]) and j["scale"] is None
    assert _scan(client, d, "4780000000059")["kind"] == "none"


def test_SCAN_filial_qoldigi_va_doira(client):
    d = _shop(2)
    p = _product(d, name="Ikki filial", qty=4, barcode="4780000000066")
    with _db() as db:
        from app.models.inventory import Inventory
        db.add(Inventory(product_id=p["id"], branch_id=d["bids"][1], qty=Decimal("6"),
                         min_qty=0, updated_at=NOW))
        db.commit()
    assert _scan(client, d, "4780000000066")["product"]["stock"] == 10.0
    assert _scan(client, d, "4780000000066",
                 branch_id=str(d["bids"][1]))["product"]["stock"] == 6.0
    h, _e = _staff(d, "omborchi", filiallar=[d["bids"][0]])
    r = client.get("/api/v1/products/scan", headers=h,
                   params={"code": "4780000000066", "branch_id": str(d["bids"][1])})
    assert r.status_code == 403, r.text
    r = client.get("/api/v1/products/scan", headers=h, params={"code": "4780000000066"})
    assert r.json()["product"]["stock"] == 4.0                   # faqat o'z filiali
    r = client.get("/api/v1/products/scan", headers=d["H"],
                   params={"code": "1", "branch_id": str(_shop()["bids"][0])})
    assert r.status_code == 400
    assert client.get("/api/v1/products/scan", params={"code": "1"}).status_code == 401


# ══ 4–5. Qabul va xarid hujjati ═════════════════════════════════════════════

def _commit(client, h, items, *, payment="cash", supplier=None, cu=None):
    return client.post("/api/v1/receiving/commit", headers=h, json={
        "items": items, "supplier_id": (str(supplier) if supplier else None),
        "payment": payment, "source": "manual", "client_uuid": str(cu or uuid.uuid4())})


def test_QABUL_royxati_va_tafsiloti_xarid_havolasi_bilan(client):
    d = _shop()
    p = _product(d, name="Kirim", qty=0)
    r1 = _commit(client, d["H"], [{"product_id": str(p["id"]), "qty": 2, "unit_cost": 100,
                                   "unit": "dona"}], payment="credit", supplier=d["sup"])
    r2 = _commit(client, d["H"], [{"product_id": str(p["id"]), "qty": 1, "unit_cost": 100,
                                   "unit": "dona"}], payment="cash")
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    # Qarz to'liq to'lanadi -> hujjat `received` bo'ladi, lekin u baribir QARZ hujjati.
    pay = client.post(f"/api/v1/suppliers/{d['sup']}/payments", headers=d["H"],
                      json={"amount": 200, "method": "card"})
    assert pay.status_code == 200, pay.text
    rows = {x["id"]: x for x in client.get("/api/v1/receiving", headers=d["H"]).json()}
    a, b = rows[r1.json()["receiving_id"]], rows[r2.json()["receiving_id"]]
    assert a["purchase_id"] == r1.json()["purchase_id"] and a["doc_no"] == r1.json()["doc_no"]
    assert (a["payment"], a["supplier"], a["purchase_status"]) == ("credit", "5G ta'minotchi",
                                                                  "received")
    assert (b["payment"], b["supplier"]) == ("cash", "Qabul (mobil)")
    assert a["branch_id"] == str(d["bids"][0]) and a["branch_name"] == "F01"
    det = client.get(f"/api/v1/receiving/{r1.json()['receiving_id']}", headers=d["H"]).json()
    for k in ("purchase_id", "doc_no", "payment", "supplier", "purchase_status", "branch_id"):
        assert det[k] == a[k], k
    assert det["items"][0]["product_id"] == str(p["id"])        # eski maydonlar joyida


def test_XARID_hujjat_filiali_va_biznes_sanasi(client):
    from app.services import lot_policy as LP
    d = _shop(2, tz="Asia/Bishkek")
    h, _e = _staff(d, "omborchi", filiallar=[d["bids"][1]])
    p = _product(d, name="Ikkinchi filial", bid=d["bids"][1])
    r = _commit(client, h, [{"product_id": str(p["id"]), "qty": 1, "unit_cost": 10,
                             "unit": "dona"}], payment="credit", supplier=d["sup"])
    assert r.status_code == 200, r.text
    j = client.get(f"/api/v1/purchases/{r.json()['purchase_id']}", headers=d["H"]).json()
    with _db() as db:
        biz = LP.business_date(db, d["bids"][1]).isoformat()
    assert (j["branch_id"], j["branch_name"], j["business_date"]) == (str(d["bids"][1]), "F02",
                                                                      biz)
    assert j["cash_custody"]["branch"]["id"] == str(d["bids"][1])


# ══ 6. /cash/custody-preview (SQLite: kassa quyi tizimi YO'Q) ═══════════════

OPS = ("receiving_payment", "debt_payment", "supplier_payment", "collection_destination")


def _preview(client, h, op):
    return client.get("/api/v1/cash/custody-preview", params={"operation": op}, headers=h)


def test_PREVIEW_rejimlar_sqlite_da(client):
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    d = _shop()
    for op in OPS[:3]:
        j = _preview(client, d["H"], op).json()
        assert j == {"mode": "NOT_REQUIRED", "reason": None, "resolved": None, "options": [],
                     "branch": {"id": str(d["bids"][0]), "name": "F01"}}, (op, j)
    # Inkassa: ochiq smena YO'Q -> BLOCKED, yozuvchi ham 400 (AYNI kod).
    j = _preview(client, d["H"], "collection_destination").json()
    assert (j["mode"], j["reason"], j["options"]) == ("BLOCKED", "OPEN_SHIFT_REQUIRED", [])
    w = client.post("/api/v1/cash/ops", headers=d["H"],
                    json={"type": "collection", "amount": 10, "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 400 and _hdr(w) == "OPEN_SHIFT_REQUIRED", w.text
    assert w.json()["detail"] == "Ochiq smena yo'q — avval kassada smena oching"
    with _db() as db:
        db.add(Shift(id=uuid.uuid4(), branch_id=d["bids"][0], cashier_id=d["eid"],
                     opened_at=NOW - timedelta(hours=1), opening_cash=Decimal("500"),
                     status=ShiftStatus.open))
        db.commit()
    j = _preview(client, d["H"], "collection_destination").json()
    assert j["mode"] == "NOT_REQUIRED", j                  # kassa quyi tizimi yo'q -> manzilsiz
    w = client.post("/api/v1/cash/ops", headers=d["H"],
                    json={"type": "collection", "amount": 10, "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 200, w.text                    # NOT_REQUIRED => yozuvchi hisobsiz OK


def test_PREVIEW_force_shift_qarz_tolovi_BLOCKED_va_yozuvchi_rad(client):
    from app.models.customers import Customer
    from app.models.settings import Setting
    d = _shop()
    with _db() as db:
        db.add(Setting(company_id=d["cid"], branch_id=None, key="security",
                       value={"force_shift": True}))
        c = Customer(id=uuid.uuid4(), company_id=d["cid"], code="M-1", full_name="Qarzdor",
                     credit_balance=Decimal("100"))
        db.add(c)
        db.commit()
        cid = c.id
    j = _preview(client, d["H"], "debt_payment").json()
    assert (j["mode"], j["reason"]) == ("BLOCKED", "OPEN_SHIFT_REQUIRED"), j
    w = client.post(f"/api/v1/customers/{cid}/payments", headers=d["H"],
                    json={"amount": 10, "method": "cash", "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 400 and _hdr(w) == "OPEN_SHIFT_REQUIRED", w.text
    assert w.json()["detail"] == "Naqd qarz to'lovi uchun ochiq smena kerak — avval smenani oching"
    # Karta — kassa qatnashmaydi, smena ham shart emas.
    w = client.post(f"/api/v1/customers/{cid}/payments", headers=d["H"],
                    json={"amount": 10, "method": "card", "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 200, w.text


def test_PREVIEW_ruxsat_YOZUVCHINIKI(client):
    d = _shop()
    omb, _ = _staff(d, "omborchi")
    men, _ = _staff(d, "menejer")
    kas, _ = _staff(d, "kassir")
    want = {"omborchi": {"receiving_payment", "supplier_payment"},
            "menejer": {"debt_payment", "collection_destination"}, "kassir": set()}
    for nom, h in (("omborchi", omb), ("menejer", men), ("kassir", kas)):
        for op in OPS:
            r = _preview(client, h, op)
            if op in want[nom]:
                assert r.status_code == 200, (nom, op, r.text)
            else:
                assert r.status_code == 403 and _hdr(r) == "PERMISSION_DENIED", (nom, op, r.text)
    r = _preview(client, omb, "debt_payment")
    assert r.json()["detail"] == "Ruxsat yo'q: mijozlar.edit"
    assert _preview(client, d["H"], "sale").status_code == 422
    assert client.get("/api/v1/cash/custody-preview", headers=d["H"]).status_code == 422


def _gate_perms(router, endpoint):
    """Marshrut dependency daraxtidagi `require`/`require_any` ruxsatlari (closure'dan)."""
    from fastapi.routing import APIRoute
    route = next(r for r in router.routes if isinstance(r, APIRoute) and r.endpoint is endpoint)
    out, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        fn = dep.call
        if (getattr(fn, "__module__", None) == "app.core.deps"
                and getattr(fn, "__qualname__", "").endswith(".checker")):
            cells = dict(zip(fn.__code__.co_freevars, (c.cell_contents for c in fn.__closure__)))
            if "permission_code" in cells:
                out.add(cells["permission_code"])
            else:
                out |= set(cells["permission_codes"])
        stack.extend(dep.dependencies)
    return out


def test_PREVIEW_ruxsatlari_YOZUVCHI_marshrutlari_bilan_AYNAN():
    """`PREVIEW_PERMISSIONS` yozuvchi marshrutidagi darvoza bilan AYNI — biri o'zgarsa qizaradi."""
    from app.api.v1 import cashops, customers, purchases, receiving
    from app.services.cash.custody_preview import PREVIEW_PERMISSIONS as PP
    writers = {"receiving_payment": (receiving.router, receiving.commit),
               "debt_payment": (customers.router, customers.pay_credit),
               "supplier_payment": (purchases.router, purchases.pay_supplier),
               "collection_destination": (cashops.router, cashops.cash_op)}
    assert set(PP) == set(writers)
    for op, (router, fn) in writers.items():
        assert _gate_perms(router, fn) == {PP[op]}, op
    assert _gate_perms(cashops.router, cashops.custody_preview) == set(PP.values())


# ══ 8. X-Error-Code — matn va holat O'ZGARMAGAN ═════════════════════════════

def _lot_line(p, qty, lots, cost=700):
    return {"product_id": str(p["id"]), "qty": qty, "unit_cost": cost, "unit": "dona",
            **({"lots": lots} if lots is not None else {})}


def test_KOD_kirim_partiya_xatolari(client):
    from app.services import lot_policy as LP
    d = _shop()
    t = _product(d, name="Kuzatuvli", tracked=True)
    u = _product(d, name="Oddiy")
    ex = _product(d, name="Muddatli", tracked=True, expiry=True)
    cases = [
        (_lot_line(t, 5, None), 400, "LOT_LINES_REQUIRED",
         "'Kuzatuvli' partiya bo'yicha kuzatiladi — har kirim qatori uchun `lots` MAJBURIY. "
         "Miqdor taxmin qilinmaydi."),
        (_lot_line(u, 5, [{"qty": 5}]), 400, "LOT_LINES_FORBIDDEN",
         "'Oddiy' partiya bo'yicha kuzatilmaydi — `lots` berib bo'lmaydi"),
        (_lot_line(t, 5, [{"qty": 2}]), 400, "LOT_QTY_SUM_MISMATCH",
         "'Kuzatuvli': partiyalar yig'indisi 2.000 qator miqdori 5.000 ga TENG EMAS. "
         "Yetishmagan miqdor taxmin qilinmaydi."),
        (_lot_line(t, 1.2345, [{"qty": 1.2345}]), 400, "LOT_QTY_PRECISION",
         "'Kuzatuvli': qator miqdori 1.2345 da uchtadan ORTIQ kasr xonasi bor — miqdor 0.001 "
         "aniqligida beriladi. Miqdor jimgina yaxlitlanmaydi."),
        (_lot_line(t, 2.5, [{"qty": 1.2345}, {"qty": 1.2655}]), 400, "LOT_QTY_PRECISION",
         "'Kuzatuvli': partiya miqdori 1.2345 da uchtadan ORTIQ kasr xonasi bor — miqdor 0.001 "
         "aniqligida beriladi. Miqdor jimgina yaxlitlanmaydi."),
        (_lot_line(t, 1, [{"qty": 1, "expiry_date": "2099-01-01"}]), 400,
         "LOT_EXPIRY_FORBIDDEN",
         "'Kuzatuvli' muddat bo'yicha KUZATILMAYDI — yangi partiyaga `expiry_date` yozib "
         "bo'lmaydi. Avval mahsulotda muddat kuzatuvini yoqing."),
        (_lot_line(ex, 1, [{"qty": 1, "expiry_date": "2099-01-01"}]), 409,
         "LOT_TZ_NOT_CONFIRMED",
         "filial vaqt zonasi ('Asia/Tashkent') TASDIQLANMAGAN. Muddat biznes sanasiga tayanadi "
         "va bir soatlik xato muddatni bir kunga suradi — shu bois zona operator tomonidan ANIQ "
         "tasdiqlanishi kerak."),
    ]
    for item, st, kod, matn in cases:
        r = _commit(client, d["H"], [item])
        assert (r.status_code, _hdr(r), r.json()["detail"]) == (st, kod, matn), r.text
    _confirm_tz(d)
    with _db() as db:
        biz = LP.business_date(db, d["bids"][0])
    kecha = (biz - timedelta(days=1)).isoformat()
    for item, kod, matn in (
            (_lot_line(ex, 1, [{"qty": 1}]), "LOT_EXPIRY_REQUIRED",
             "'Muddatli' muddat bo'yicha kuzatiladi — har partiyada `expiry_date` MAJBURIY. "
             "Noma'lum muddat jimgina qabul qilinmaydi."),
            (_lot_line(ex, 1, [{"qty": 1, "expiry_date": kecha}]), "LOT_EXPIRED",
             f"'Muddatli': {kecha} muddati bugungi biznes sanasi ({biz.isoformat()}) dan OLDIN "
             f"— muddati o'tgan tovar qabul qilinmaydi.")):
        r = _commit(client, d["H"], [item])
        assert (r.status_code, _hdr(r), r.json()["detail"]) == (400, kod, matn), r.text
    ok = _commit(client, d["H"], [_lot_line(ex, 1, [{"qty": 1, "expiry_date": biz.isoformat()}])])
    assert ok.status_code == 200 and _hdr(ok) is None, ok.text          # MANFIY NAZORAT


def _writeoff(client, d, p, qty, lots=None):
    body = {"product_id": str(p["id"]), "qty": qty, "reason": "damaged: sinov",
            "client_uuid": str(uuid.uuid4()), "branch_id": str(d["bids"][0])}
    if lots is not None:
        body["lots"] = [{"stock_batch_id": str(b), "qty": q} for b, q in lots]
    return client.post("/api/v1/inventory/writeoff", headers=d["H"], json=body)


def test_KOD_hisobdan_chiqarish(client):
    d = _shop()
    t = _product(d, name="Kuzatuvli W", qty=10, tracked=True, lots=[5, 5])
    u = _product(d, name="Oddiy W", qty=10)
    a, b = t["lots"]
    yoq = uuid.uuid4()
    cases = [
        (t, 1, None, "LOT_LINES_REQUIRED",
         "Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating — tizim qaysi jismoniy partiya "
         "chiqarilayotganini TAXMIN QILMAYDI."),
        (u, 1, [(a, 1)], "LOT_LINES_FORBIDDEN",
         "Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko'rsatib bo'lmaydi"),
        (t, 1, [(yoq, 1)], "LOT_SELECTION_INVALID", f"Partiya topilmadi: {yoq}"),
        (t, 2, [(a, 1), (a, 1)], "LOT_SELECTION_INVALID", f"Partiya ikki marta ko'rsatilgan: {a}"),
        (t, 4, [(a, 3)], "LOT_QTY_SUM_MISMATCH",
         "Partiyalar yig'indisi (3.000) umumiy miqdorga (4.000) mos emas. Farqni tizim "
         "TAQSIMLAMAYDI — qaysi partiya ekanini operator aytishi shart."),
    ]
    for p, qty, lots, kod, matn in cases:
        r = _writeoff(client, d, p, qty, lots)
        assert (r.status_code, _hdr(r), r.json()["detail"]) == (400, kod, matn), r.text
    r = _writeoff(client, d, t, 6, [(a, 6)])
    assert (r.status_code, _hdr(r)) == (400, "LOT_INSUFFICIENT_REMAINING"), r.text
    assert r.json()["detail"].startswith("Partiyada yetarli qoldiq yo'q (")
    assert r.json()["detail"].endswith(f"): {a} — jismoniy partiya MANFIYGA tushmaydi")
    ok = _writeoff(client, d, t, 2, [(b, 2)])
    assert ok.status_code == 200 and _hdr(ok) is None and ok.json()["cost_total"] == 100.0


def _count(client, d, items):
    return client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": items, "client_uuid": str(uuid.uuid4()), "branch_id": str(d["bids"][0])})


def test_KOD_inventarizatsiya(client):
    d = _shop()
    t = _product(d, name="Kuzatuvli C", qty=8, tracked=True, lots=[3, 5])
    t2 = _product(d, name="Boshqa C", qty=1, tracked=True, lots=[1])
    u = _product(d, name="Oddiy C", qty=2)
    ex = _product(d, name="Muddatli C", qty=0, tracked=True, expiry=True, lots=[])
    a, b = t["lots"]
    cases = [
        ([{"product_id": str(t["id"]), "counted": 8}], 400, "LOT_LINES_REQUIRED",
         "Kuzatuvli C: Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim "
         "partiyalarga TAQSIMLAMAYDI."),
        ([{"product_id": str(u["id"]), "counted": 2,
           "lots": [{"stock_batch_id": str(a), "counted": 1}]}], 400, "LOT_LINES_FORBIDDEN",
         "Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko'rsatib bo'lmaydi"),
        ([{"product_id": str(t["id"]), "counted": 10,
           "lots": [{"stock_batch_id": str(a), "counted": 3}]}], 400, "LOT_COUNT_SUM_MISMATCH",
         "Kuzatuvli C: Partiyalar yig'indisi (8.000) e'lon qilingan umumiy sanoqqa (10.000) mos "
         "emas. Sanalmagan partiyalar TEGILMAYDI (5.000); farqni tizim TAQSIMLAMAYDI."),
        ([{"product_id": str(t["id"]), "counted": 8,
           "lots": [{"stock_batch_id": str(t2["lots"][0]), "counted": 1}]}], 400,
         "LOT_SELECTION_INVALID",
         f"Kuzatuvli C: Partiya boshqa mahsulot yoki filialga tegishli: {t2['lots'][0]}"),
        ([{"product_id": str(t["id"]), "counted": 9,
           "new_lots": [{"qty": 1, "unit_cost": 5, "expiry_date": "2099-01-01"}]}], 400,
         "LOT_EXPIRY_FORBIDDEN",
         "'Kuzatuvli C' muddat bo'yicha KUZATILMAYDI — yangi partiyaga `expiry_date` yozib "
         "bo'lmaydi. Avval mahsulotda muddat kuzatuvini yoqing."),
        ([{"product_id": str(ex["id"]), "counted": 1,
           "new_lots": [{"qty": 1, "unit_cost": 5, "expiry_date": "2099-01-01"}]}], 409,
         "LOT_TZ_NOT_CONFIRMED",
         "filial vaqt zonasi ('Asia/Tashkent') TASDIQLANMAGAN. Muddat biznes sanasiga tayanadi "
         "va bir soatlik xato muddatni bir kunga suradi — shu bois zona operator tomonidan ANIQ "
         "tasdiqlanishi kerak."),
    ]
    for items, st, kod, matn in cases:
        r = _count(client, d, items)
        assert (r.status_code, _hdr(r), r.json()["detail"]) == (st, kod, matn), r.text
    _confirm_tz(d)
    r = _count(client, d, [{"product_id": str(ex["id"]), "counted": 1,
                            "new_lots": [{"qty": 1, "unit_cost": 5}]}])
    assert (r.status_code, _hdr(r), r.json()["detail"]) == (
        400, "LOT_EXPIRY_REQUIRED",
        "'Muddatli C' muddat bo'yicha kuzatiladi — yangi partiyada `expiry_date` MAJBURIY. "
        "Noma'lum muddat jimgina qabul qilinmaydi."), r.text
    ok = _count(client, d, [{"product_id": str(t["id"]), "counted": 7,
                             "lots": [{"stock_batch_id": str(a), "counted": 2}]}])
    assert ok.status_code == 200 and _hdr(ok) is None, ok.text
    assert ok.json()["results"][0]["lots"]["decrements"] == [
        {"stock_batch_id": str(a), "qty": 1.0}]


def test_KOD_kochirish_kuzatuvli_409(client):
    d = _shop(2)
    t = _product(d, name="Kuzatuvli T", qty=5, tracked=True)
    body = {"from_branch_id": str(d["bids"][0]), "to_branch_id": str(d["bids"][1]),
            "items": [{"product_id": str(t["id"]), "qty": 1}], "client_uuid": str(uuid.uuid4())}
    r = client.post("/api/v1/inventory/transfer", headers=d["H"], json=body)
    assert (r.status_code, _hdr(r)) == (409, "TRANSFER_TRACKED_UNSUPPORTED"), r.text
    assert r.json()["detail"] == (
        "«filiallararo ko'chirish» yo'li partiya kuzatuvini qo'llab-quvvatlamaydi, lekin 1 ta "
        "kuzatuvli mahsulot so'raldi. Partiya-darajasidagi amalni ishlating — qoldiqni "
        "partiyalardan ayirmasdan o'zgartirish miqdor invariantini buzardi.")
    u = _product(d, name="Oddiy T", qty=5)
    body["items"] = [{"product_id": str(u["id"]), "qty": 1}]
    body["client_uuid"] = str(uuid.uuid4())
    ok = client.post("/api/v1/inventory/transfer", headers=d["H"], json=body)
    assert ok.status_code == 200 and _hdr(ok) is None, ok.text


def test_KOD_ruxsat_yoq_403_matn_OZGARMAGAN(client):
    d = _shop()
    kas, _ = _staff(d, "kassir")
    omb, _ = _staff(d, "omborchi")
    r = client.post("/api/v1/inventory/writeoff", headers=kas, json={
        "product_id": str(uuid.uuid4()), "qty": 1})
    assert (r.status_code, _hdr(r), r.json()["detail"]) == (
        403, "PERMISSION_DENIED", "Ruxsat yo'q: ombor.edit")
    r = client.post("/api/v1/customers", headers=omb, json={"full_name": "X"})
    assert (r.status_code, _hdr(r), r.json()["detail"]) == (
        403, "PERMISSION_DENIED", "Ruxsat yo'q: mijozlar.edit / kassa.sell")
    # Filial doirasi 403 — ruxsat darvozasi EMAS, kodsiz qoladi.
    d2 = _shop(2)
    h2, _ = _staff(d2, "omborchi", filiallar=[d2["bids"][0]])
    r = client.get("/api/v1/products", params={"branch_id": str(d2["bids"][1])}, headers=h2)
    assert r.status_code == 403 and _hdr(r) is None


# ══ 9. GZip ═════════════════════════════════════════════════════════════════

def test_GZIP_ochilgan_tana_AYNAN_siqilmagan_tana(client):
    d = _shop()
    for i in range(25):
        _product(d, name=f"Siqish {i:02d}", qty=i, barcode=f"47800000{i:05d}")
    url = "/api/v1/products"
    plain = client.get(url, headers={**d["H"], "Accept-Encoding": "identity"})
    assert plain.status_code == 200 and "content-encoding" not in plain.headers
    assert len(plain.content) > 1024
    with client.stream("GET", url, headers={**d["H"], "Accept-Encoding": "gzip"}) as z:
        assert z.status_code == 200 and z.headers.get("content-encoding") == "gzip"
        raw = b"".join(z.iter_raw())
    assert len(raw) < len(plain.content)
    assert gzip.decompress(raw) == plain.content
    # Kichik javob siqilmaydi (minimum_size=1024).
    small = client.get("/api/v1/auth/me", headers={**d["H"], "Accept-Encoding": "gzip"})
    assert small.status_code == 200 and "content-encoding" not in small.headers


# ══ 10. INTEGRATSIYA (IC): filial doirasi va mijoz tarixi ═══════════════════
#
# `GET /inventory/overview`, `GET /inventory/low`, `GET /products/{id}` — ixtiyoriy
# `branch_id` (tekshiruv `GET /products?branch_id=` bilan AYNI yordamchi `_stock_scope`);
# `/inventory/low` qatorlarida `product_id`; mijoz tafsiloti tarixida `sale_id`,
# `receipt_no`, `items_qty`, to'lovlarda `method`. PARAMETRSIZ javob AVVALGIDEK (desktop).

def _json_bytes(obj) -> bytes:
    """FastAPI standart javobi (`jsonable_encoder` + `JSONResponse`) — bayt-bayt taqqoslash uchun."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    return JSONResponse(content=jsonable_encoder(obj)).body


def _json_roundtrip(obj):
    import json
    return json.loads(_json_bytes(obj))


def _inv(pid, bid, qty, mn=0):
    from app.models.inventory import Inventory
    with _db() as db:
        row = db.query(Inventory).filter(Inventory.product_id == pid,
                                         Inventory.branch_id == bid).first()
        if row is None:
            row = Inventory(product_id=pid, branch_id=bid, updated_at=NOW)
            db.add(row)
        row.qty, row.min_qty = Decimal(str(qty)), Decimal(str(mn))
        db.commit()


def _move(pid, bid, typ, qty, at=None):
    from app.models.enums import MovementType
    from app.models.inventory import StockMovement
    with _db() as db:
        db.add(StockMovement(product_id=pid, branch_id=bid, type=MovementType(typ),
                             qty=Decimal(str(qty)), created_at=at or NOW))
        db.commit()


def _eski_overview(eid, bset_override=None):
    """Phase 5G IC dan OLDINGI `GET /inventory/overview` tanasi (AYNAN nusxa; `bset_override`
    berilsa filial to'plami shu, aks holda eski `visible_branches`)."""
    from app.api.v1.reports import _store_tz
    from app.core.deps import visible_branches
    from app.models.auth import Employee
    from app.models.catalog import Product
    from app.models.inventory import Inventory, StockMovement
    with _db() as db:
        emp = db.get(Employee, eid)
        bset = bset_override if bset_override is not None else visible_branches(emp, db)
        total = db.query(Product).filter(
            Product.company_id == emp.company_id, Product.deleted_at.is_(None)).count()
        low = (db.query(Inventory).join(Product, Product.id == Inventory.product_id)
               .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                       Product.is_active.is_(True), Inventory.qty > 0,
                       Inventory.qty <= Inventory.min_qty))
        out = (db.query(Inventory).join(Product, Product.id == Inventory.product_id)
               .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                       Product.is_active.is_(True), Inventory.qty <= 0))
        LOCAL = _store_tz(db, emp.company_id)
        day0 = (datetime.now(timezone.utc).astimezone(LOCAL)
                .replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc))
        moves_today = (db.query(StockMovement).join(Product, Product.id == StockMovement.product_id)
                       .filter(Product.company_id == emp.company_id,
                               StockMovement.created_at >= day0))
        if bset is not None:
            low = low.filter(Inventory.branch_id.in_(bset))
            out = out.filter(Inventory.branch_id.in_(bset))
            moves_today = moves_today.filter(StockMovement.branch_id.in_(bset))
        return {"total_products": total, "low_count": low.count(), "out_count": out.count(),
                "moves_today": moves_today.count()}


def _eski_low(eid, bset_override=None):
    """Phase 5G IC dan OLDINGI `GET /inventory/low` tanasi (AYNAN nusxa)."""
    from app.core.deps import visible_branches
    from app.models.auth import Employee
    from app.models.catalog import Product
    from app.models.inventory import Inventory
    with _db() as db:
        emp = db.get(Employee, eid)
        _bset = bset_override if bset_override is not None else visible_branches(emp, db)
        q = (db.query(Product.name, Inventory.qty, Inventory.min_qty)
             .join(Inventory, Inventory.product_id == Product.id)
             .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                     Product.is_active.is_(True), Inventory.min_qty > 0,
                     Inventory.qty <= Inventory.min_qty))
        if _bset is not None:
            q = q.filter(Inventory.branch_id.in_(_bset))
        rows = q.order_by(Inventory.qty).limit(200).all()
        return [{"name": n, "qty": float(q), "min": float(mn)} for n, q, mn in rows]


def _ombor_dokoni():
    """2 filialli do'kon: kam/tugagan qoldiqlar ikkala filialda, bugungi harakatlar, arxiv tovar.
    Qoldiqlar TAKRORLANMAS (`/inventory/low` tartibi `qty` bo'yicha — teng qiymat bo'lmasin)."""
    d = _shop(2)
    b0, b1 = d["bids"]
    p1 = _product(d, name="Olma", qty=1)["id"]
    _inv(p1, b0, 1, 3)                      # b0: kam (1 <= 3)
    _inv(p1, b1, 10, 3)                     # b1: yetarli
    p2 = _product(d, name="Behi", qty=0)["id"]
    _inv(p2, b0, 0, 1)                      # b0: tugagan (low ro'yxatida ham: 0 <= 1)
    _inv(p2, b1, 2, 5)                      # b1: kam
    p3 = _product(d, name="Nok", qty=0.5, bid=b1)["id"]
    _inv(p3, b1, 0.5, 4)                    # b1: kam (kasr)
    p4 = _product(d, name="Arxiv", qty=0, active=False)["id"]
    _inv(p4, b0, 0, 2)                      # nofaol — hisobga TUSHMAYDI
    _move(p1, b0, "sale_out", -1)
    _move(p2, b0, "writeoff", -1)
    _move(p2, b1, "purchase_in", 2)
    _move(p1, b1, "purchase_in", 5, at=NOW - timedelta(days=40))   # bugun EMAS
    return d, {"p1": p1, "p2": p2, "p3": p3, "p4": p4}


def _xato(r):
    return (r.status_code, r.json().get("detail"), _hdr(r))


def test_IC_OVERVIEW_parametrsiz_AVVALGIDEK_bayt_bayt_filial_bilan_FAQAT_shu_filial(client):
    d, _p = _ombor_dokoni()
    b0, b1 = d["bids"]
    h_men, e_men = _staff(d, "menejer", filiallar=[b0])
    url = "/api/v1/inventory/overview"
    # Parametrsiz: ega (hamma filial) va biriktirilgan xodim — eski algoritm bilan BAYT-BAYT.
    for h, eid in ((d["H"], d["eid"]), (h_men, e_men)):
        r = client.get(url, headers=h)
        assert r.status_code == 200, r.text
        assert r.content == _json_bytes(_eski_overview(eid)), (r.text, _eski_overview(eid))
    assert client.get(url, headers=d["H"]).json() == {
        "total_products": 4, "low_count": 3, "out_count": 1, "moves_today": 3}
    # `branch_id` — BARCHA qoldiq/harakat sonlari FAQAT shu filialniki (katalog hajmi emas).
    j0 = client.get(url, params={"branch_id": str(b0)}, headers=d["H"]).json()
    j1 = client.get(url, params={"branch_id": str(b1)}, headers=d["H"]).json()
    assert j0 == {"total_products": 4, "low_count": 1, "out_count": 1, "moves_today": 2}
    assert j1 == {"total_products": 4, "low_count": 2, "out_count": 0, "moves_today": 1}
    assert j0 == _eski_overview(d["eid"], {b0}) and j1 == _eski_overview(d["eid"], {b1})
    # Biriktirilgan xodim o'z filialini so'rasa — parametrsiz bilan AYNI bayt.
    assert (client.get(url, params={"branch_id": str(b0)}, headers=h_men).content
            == client.get(url, headers=h_men).content)


def test_IC_LOW_product_id_QOSHIMCHA_qolgani_AVVALGIDEK_va_filial_doirasi(client):
    d, p = _ombor_dokoni()
    b0, b1 = d["bids"]
    h_men, e_men = _staff(d, "menejer", filiallar=[b1])
    url = "/api/v1/inventory/low"
    for h, eid in ((d["H"], d["eid"]), (h_men, e_men)):
        rows = client.get(url, headers=h).json()
        assert rows and all(list(r) == ["name", "qty", "min", "product_id"] for r in rows), rows
        eski = [{k: v for k, v in r.items() if k != "product_id"} for r in rows]
        assert _json_bytes(eski) == _json_bytes(_eski_low(eid))   # mavjud kalit/tartib/qiymat AYNI
    rows = client.get(url, headers=d["H"]).json()
    assert [(r["name"], r["qty"], r["product_id"]) for r in rows] == [
        ("Behi", 0.0, str(p["p2"])), ("Nok", 0.5, str(p["p3"])),
        ("Olma", 1.0, str(p["p1"])), ("Behi", 2.0, str(p["p2"]))]
    r0 = client.get(url, params={"branch_id": str(b0)}, headers=d["H"]).json()
    r1 = client.get(url, params={"branch_id": str(b1)}, headers=d["H"]).json()
    assert [(r["name"], r["qty"]) for r in r0] == [("Behi", 0.0), ("Olma", 1.0)]
    assert [(r["name"], r["qty"]) for r in r1] == [("Nok", 0.5), ("Behi", 2.0)]
    assert [{k: v for k, v in r.items() if k != "product_id"} for r in r1] == \
        _eski_low(d["eid"], {b1})
    # `product_id` haqiqatan kartani ochadi (o'sha filial qoldig'i bilan).
    k = client.get(f"/api/v1/products/{r1[0]['product_id']}", params={"branch_id": str(b1)},
                   headers=d["H"]).json()
    assert (k["name"], k["stock"], k["min_stock"]) == ("Nok", 0.5, 4.0)


def test_IC_MAHSULOT_KARTASI_filial_qoldigi_parametrsiz_AVVALGIDEK(client):
    d = _shop(2)
    b0, b1 = d["bids"]
    pid = _product(d, name="Karta", qty=5)["id"]
    _inv(pid, b0, 5, 2)
    _inv(pid, b1, 7, 4)
    _move(pid, b0, "purchase_in", 5)
    _move(pid, b1, "purchase_in", 7)
    _move(pid, b1, "writeoff", -1)
    url = f"/api/v1/products/{pid}"
    KALITLAR = ["id", "article_code", "sku", "name", "category_id", "base_buy_price",
                "base_sell_price", "profit_unit", "margin_pct", "stock", "min_stock",
                "expiry_date", "track_lots", "track_expiry", "sales_7d", "sales_30d",
                "last_sold_at", "month_in", "month_out", "unit_code", "is_active",
                "is_weighted", "plu_code", "scale_sync", "created_by_name", "created_at",
                "barcodes"]
    FIL = ("stock", "min_stock", "month_in", "month_out")

    def nums(j):
        return tuple(j[k] for k in FIL)

    j = client.get(url, headers=d["H"]).json()
    assert list(j) == KALITLAR                              # yangi kalit YO'Q, tartib AYNI
    assert nums(j) == (12.0, 4.0, 12.0, 1.0)                # ega: hamma filial (avvalgidek)
    assert nums(client.get(url, params={"branch_id": str(b0)}, headers=d["H"]).json()) == (
        5.0, 2.0, 5.0, 0.0)
    j1 = client.get(url, params={"branch_id": str(b1)}, headers=d["H"]).json()
    assert nums(j1) == (7.0, 4.0, 7.0, 1.0)
    # Filialga bog'liq bo'lmagan maydonlar (sotuv statistikasi va h.k.) O'ZGARMAYDI.
    assert {k: v for k, v in j1.items() if k not in FIL} == {k: v for k, v in j.items() if k not in FIL}
    # Biriktirilgan xodim: parametrsiz = o'z filiali (avvalgidek) = o'z filiali parametr bilan (bayt).
    h_men, _e = _staff(d, "menejer", filiallar=[b1])
    plain = client.get(url, headers=h_men)
    assert nums(plain.json()) == (7.0, 4.0, 7.0, 1.0)
    assert plain.content == client.get(url, params={"branch_id": str(b1)}, headers=h_men).content
    # Mahsulot yo'q — 404 avvalgidek.
    assert _xato(client.get(f"/api/v1/products/{uuid.uuid4()}", headers=d["H"])) == (
        404, "Mahsulot topilmadi", None)


@pytest.mark.parametrize("marshrut", ["overview", "low", "karta"])
def test_IC_FILIAL_TEKSHIRUVI_products_bilan_AYNAN(client, marshrut):
    """Begona/o'chirilgan/noma'lum filial -> 400, biriktirilmagan -> 403 (kodsiz), buzuq -> 422:
    holat, matn va `X-Error-Code` `GET /products?branch_id=` bilan AYNAN bir xil."""
    from app.models.org import Branch
    d = _shop(3)
    b0, b1, b2 = d["bids"]
    begona = _shop()
    pid = _product(d, name="Tek", qty=1)["id"]
    with _db() as db:
        db.get(Branch, b2).deleted_at = NOW
        db.get(Branch, b1).is_active = False
        db.commit()
    h_men, _e = _staff(d, "menejer", filiallar=[b0])
    url = {"overview": "/api/v1/inventory/overview", "low": "/api/v1/inventory/low",
           "karta": f"/api/v1/products/{pid}"}[marshrut]
    holatlar = [
        (d["H"], str(begona["bids"][0]), 400),     # begona do'kon filiali
        (d["H"], str(b2), 400),                    # o'chirilgan filial
        (d["H"], str(uuid.uuid4()), 400),          # umuman yo'q
        (h_men, str(b1), 403),                     # ko'rish doirasidan tashqari
        (d["H"], "buzuq", 422),
    ]
    for h, bid, status in holatlar:
        r = client.get(url, params={"branch_id": bid}, headers=h)
        etalon = client.get("/api/v1/products", params={"branch_id": bid}, headers=h)
        assert r.status_code == status == etalon.status_code, (bid, r.text, etalon.text)
        if status != 422:
            assert _xato(r) == _xato(etalon), (bid, r.text, etalon.text)
    assert _xato(client.get(url, params={"branch_id": str(b1)}, headers=h_men)) == (
        403, "Ruxsat yo'q: bu filial sizga biriktirilmagan", None)
    assert _xato(client.get(url, params={"branch_id": str(b2)}, headers=d["H"])) == (
        400, "Filial topilmadi", None)
    # Nofaol-lekin-o'chirilmagan filial ega uchun ochiq (products bilan AYNI).
    assert client.get(url, params={"branch_id": str(b1)}, headers=d["H"]).status_code == 200


def test_IC_ruxsat_darvozasi_FILIAL_tekshiruvidan_OLDIN(client):
    """Mavjud darvozalar o'zgarmagan: `hisobot.view` yo'q xodim filial parametri bilan ham
    (hatto begona filial bilan ham) 403 PERMISSION_DENIED oladi — filial haqida ma'lumot yo'q."""
    d = _shop(2)
    begona = _shop()
    kas, _ = _staff(d, "kassir", filiallar=[d["bids"][0]])
    for url in ("/api/v1/inventory/overview", "/api/v1/inventory/low"):
        for bid in (d["bids"][0], begona["bids"][0]):
            r = client.get(url, params={"branch_id": str(bid)}, headers=kas)
            assert _xato(r) == (403, "Ruxsat yo'q: hisobot.view", "PERMISSION_DENIED"), r.text
        assert client.get(url, params={"branch_id": str(d["bids"][0])}).status_code == 401
    assert client.get(f"/api/v1/products/{uuid.uuid4()}",
                      params={"branch_id": str(d["bids"][0])}).status_code == 401


# ── Mijoz tafsiloti ─────────────────────────────────────────────────────────

def _mijoz(d, name="5G mijoz"):
    from app.models.customers import Customer
    with _db() as db:
        c = Customer(id=uuid.uuid4(), company_id=d["cid"], code="M-" + uuid.uuid4().hex[:6],
                     full_name=name, credit_balance=Decimal("0"))
        db.add(c)
        db.commit()
        return c.id


def _sotuv(d, cust, pid, qtys, pays, *, at, voided=False):
    """Chek: `qtys` — qator miqdorlari, `pays` — (usul, summa) ro'yxati KIRITILISH tartibida."""
    from app.models.enums import SaleStatus
    from app.models.sales import Sale, SaleItem, SalePayment
    with _db() as db:
        total = sum(Decimal(str(q)) * 100 for q in qtys)
        s = Sale(id=uuid.uuid4(), receipt_no="C-" + uuid.uuid4().hex[:8], company_id=d["cid"],
                 branch_id=d["bids"][0], cashier_id=d["eid"], customer_id=cust,
                 status=(SaleStatus.voided if voided else SaleStatus.completed),
                 subtotal=total, total=total, sold_at=at)
        db.add(s)
        db.flush()
        for q in qtys:
            db.add(SaleItem(sale_id=s.id, product_id=pid, name_snapshot="X",
                            qty=Decimal(str(q)), unit_price=100,
                            line_total=Decimal(str(q)) * 100))
            db.flush()
        for m, a in pays:
            db.add(SalePayment(sale_id=s.id, method_code=m, amount=a, paid_at=at))
            db.flush()
        db.commit()
        return {"id": s.id, "receipt_no": s.receipt_no}


def _mijoz_tolovi(cust, method, amount, at):
    from app.models.customers import CustomerPayment
    with _db() as db:
        db.add(CustomerPayment(customer_id=cust, amount=amount, method=method, paid_at=at,
                               created_at=at))
        db.commit()


def _eski_tarix(d, cust):
    """Phase 5G IC dan OLDINGI tarix qurilishi (har qator uchun 2 so'rov — AYNAN nusxa)."""
    from sqlalchemy import func
    from app.models.sales import Sale, SaleItem, SalePayment
    with _db() as db:
        sales = (db.query(Sale)
                 .filter(Sale.customer_id == cust, Sale.company_id == d["cid"],
                         Sale.deleted_at.is_(None))
                 .order_by(Sale.sold_at.desc()).limit(10).all())
        history = []
        for s in sales:
            pay = db.query(SalePayment.method_code).filter(SalePayment.sale_id == s.id).first()
            cnt = db.query(func.coalesce(func.sum(SaleItem.qty), 0)).filter(
                SaleItem.sale_id == s.id).scalar()
            history.append({"date": s.sold_at, "items": int(cnt or 0),
                            "amount": float(s.total), "method": pay[0] if pay else "cash"})
        return history


def _sorovlar_soni(client, url, headers) -> int:
    from sqlalchemy import event
    from app.db.session import engine
    n = []

    def _sana(*_a, **_k):
        n.append(1)
    event.listen(engine, "before_cursor_execute", _sana)
    try:
        r = client.get(url, headers=headers)
        assert r.status_code == 200, r.text
    finally:
        event.remove(engine, "before_cursor_execute", _sana)
    return len(n)


def test_IC_MIJOZ_tarixi_chek_havolasi_kasr_miqdor_tolov_usuli(client):
    d = _shop()
    pid = _product(d, name="Tarozi", qty=10, weighted=True)["id"]
    cust = _mijoz(d)
    s1 = _sotuv(d, cust, pid, [1.5, 2], [("card", 100), ("cash", 250)], at=NOW - timedelta(hours=3))
    s2 = _sotuv(d, cust, pid, [1], [], at=NOW - timedelta(hours=2))
    s3 = _sotuv(d, cust, pid, [0.25], [("qr", 25)], at=NOW - timedelta(hours=1), voided=True)
    _mijoz_tolovi(cust, "card", 300, NOW - timedelta(minutes=30))
    _mijoz_tolovi(cust, "cash", 150, NOW - timedelta(minutes=10))
    j = client.get(f"/api/v1/customers/{cust}/detail", headers=d["H"]).json()
    h = j["history"]
    ESKI = ["date", "items", "amount", "method"]
    assert all(list(r) == ESKI + ["sale_id", "receipt_no", "items_qty"] for r in h), h
    # Mavjud maydonlar (butun `items` ham) — eski algoritm bilan AYNAN (kalit tartibi ham).
    assert _json_bytes([{k: r[k] for k in ESKI} for r in h]) == _json_bytes(
        _json_roundtrip(_eski_tarix(d, cust)))
    assert [(r["sale_id"], r["receipt_no"], r["items"], r["items_qty"], r["method"]) for r in h] == [
        (str(s3["id"]), s3["receipt_no"], 0, "0.250", "qr"),
        (str(s2["id"]), s2["receipt_no"], 1, "1.000", "cash"),     # to'lovsiz -> "cash" (avvalgidek)
        (str(s1["id"]), s1["receipt_no"], 3, "3.500", "card"),     # bo'lingan -> BIRINCHI yozilgan
    ]
    assert [(p["method"], p["amount"]) for p in j["payments"]] == [("cash", 150.0), ("card", 300.0)]
    assert all(list(p) == ["date", "amount", "method"] for p in j["payments"])
    assert (j["total_spent"], j["visits"]) == (450.0, 2)          # bekor qilingan hisobsiz (avvalgidek)
    assert list(j) == ["id", "code", "full_name", "phone", "credit_balance", "total_spent",
                       "visits", "history", "payments"]


def test_IC_MIJOZ_tarixi_N_PLUS_1_YOQ_sorovlar_soni_qatorlarga_BOGLIQ_EMAS(client):
    d = _shop()
    pid = _product(d, name="N1", qty=10)["id"]
    bitta, olti = _mijoz(d, "Bitta"), _mijoz(d, "Olti")
    _sotuv(d, bitta, pid, [1], [("cash", 100)], at=NOW - timedelta(hours=1))
    _mijoz_tolovi(bitta, "cash", 10, NOW)
    for i in range(6):
        _sotuv(d, olti, pid, [1, 0.5], [("card", 50), ("cash", 100)], at=NOW - timedelta(hours=i + 1))
        _mijoz_tolovi(olti, "qr", 10, NOW - timedelta(minutes=i))
    n1 = _sorovlar_soni(client, f"/api/v1/customers/{bitta}/detail", d["H"])
    n6 = _sorovlar_soni(client, f"/api/v1/customers/{olti}/detail", d["H"])
    assert n1 == n6, (n1, n6)
    j = client.get(f"/api/v1/customers/{olti}/detail", headers=d["H"]).json()
    assert len(j["history"]) == 6 and {r["items_qty"] for r in j["history"]} == {"1.500"}
