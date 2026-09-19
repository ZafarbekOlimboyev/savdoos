# -*- coding: utf-8 -*-
"""PHASE 5F — KANONIK CHEK DTO (`binos.receipt.v1`): `GET /sales/{id}/receipt`,
`GET /returns/{id}/receipt`, `GET /receipt/sample`, `/sync/push` `id`.

Isbotlanadi:
  · summalar SAQLANGAN qiymatlardan; chek HAR DOIM qo'shiladi
        subtotal − line_discount − doc_discount + rounding == total,
    SOTUVDA Σ to'lov == jami; eski (buzuq) ma'lumotda ham qiymatlar o'zgartirilmaydi;
  · pul — aniq 2 xona, miqdor — aniq 3 xona (satr), vaqt — UTC ISO + filial mahalliy vaqti;
  · snapshot'lar (kassir/filial/TILL/terminal/nom) — qayta nomlash eski chekni o'zgartirmaydi;
  · qatorlar SAVAT tartibida (uuid4 id tasodifiy — tartib fizik kiritish tartibidan);
  · mijoz ismi — faqat `show_customer` bo'lsa (maxfiylik, DTO darajasida);
  · o'qish ruxsati `GET /sales/{id}` doirasi + MUALLIF istisnosi (tarixsiz `kassa.sell`
    kassir — faqat O'Z sotuvi; nofaol filial kassiri — o'z hujjati zaxira filialda ham);
    qaytarish — `qaytarishlar.view` yoki faqat O'Z qaytarishi (`qaytarishlar.create`);
  · qaytarish qatori = qty × chop etilgan narx; qatorsiz (tarixiy) sotuvda yaxlitlash 0;
  · namuna `scope=company` — faqat kompaniya shabloni, faqat cheklovsiz xodim;
  · 150 qatorli chek DTO vaqti (o'lchanadi va chop etiladi);
  · SOTUV CHEK KODIDAN MUSTAQIL: DTO quruvchisi yiqilsa ham `POST /sales`, `POST /returns`,
    `/sync/push` 200; sotuv yo'li chek paketini IMPORT QILMAYDI.
"""
import ast
import pathlib
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.receipt import codes as C
from app.services.receipt import errors as RS_E
from app.services.receipt import settings as RS
from tests.test_lot_fefo_sale import _product
from tests.test_receipt_settings import _asosiy, _db, _dokon, _put
from tests.test_sales_read_permissions import _karta_sotuv, _qaytar, _qoldiq, _xodim

SRV = pathlib.Path(__file__).resolve().parents[1]
MONEY = re.compile(r"^\d+\.\d{2}$")
QTY = re.compile(r"^\d+\.\d{3}$")
YOQ = {"detail": "Chek topilmadi"}
QYOQ = {"detail": "Qaytarish topilmadi"}
SOLD = datetime(2026, 9, 19, 3, 32, 11, 654321, tzinfo=timezone.utc)


def _D(s) -> Decimal:
    return Decimal(s)


def _invariant(dto):
    t = dto["totals"]
    for k in ("subtotal", "line_discount", "doc_discount", "total"):
        assert MONEY.match(t[k]), (k, t[k])
    assert re.match(r"^-?\d+\.\d{2}$", t["rounding"]), t
    assert (_D(t["subtotal"]) - _D(t["line_discount"]) - _D(t["doc_discount"]) + _D(t["rounding"])
            == _D(t["total"])), t
    for ln in dto["lines"]:
        assert QTY.match(ln["qty"]), ln
        for k in ("unit_price", "gross", "discount", "total"):
            assert MONEY.match(ln[k]), (k, ln)
    for p in dto["payments"]:
        assert MONEY.match(p["amount"]) and all(p[k] is None or MONEY.match(p[k])
                                                for k in ("given", "change")), p


def _sums_to_total(dto):
    assert sum(_D(p["amount"]) for p in dto["payments"]) == _D(dto["totals"]["total"])


def _filial(client, h, name, **kw):
    r = client.post("/api/v1/branches", headers=h, json={"name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _mijoz(cid, name):
    from app.models.customers import Customer
    with _db() as db:
        c = Customer(company_id=uuid.UUID(cid), code=f"M-{uuid.uuid4().hex[:6]}", full_name=name)
        db.add(c)
        db.commit()
        return str(c.id)


def _orm_sale(d, lines, payments, *, total, doc_disc="0", bid=None, customer=None, uid=None,
              snaps=True, sold_at=SOLD):
    """Sotuvni TO'G'RIDAN yozadi (qoldiq/kassaga tegmaydi) — DTO xaritasini aniq sinash uchun.

    lines: (nom, product_id, qty, narx, chegirma, line_total, unit_id|None)
    payments: (usul, summa, given, change, paid_at)"""
    from app.models.sales import Sale, SaleItem, SalePayment
    with _db() as db:
        n = uuid.uuid4().int % 10**8
        s = Sale(company_id=uuid.UUID(d["cid"]), branch_id=uuid.UUID(bid or d["a1"]),
                 cashier_id=uuid.UUID(d["x"]["kassir@A1"]["id"]),
                 receipt_no=f"#T{n}", uid=uid if uid is not None else f"26091{n}",
                 subtotal=Decimal("0"), discount_total=Decimal(doc_disc), total=Decimal(total),
                 sold_at=sold_at, customer_id=uuid.UUID(customer) if customer else None,
                 cashier_name_snapshot="Kassir Surat" if snaps else None,
                 branch_name_snapshot="Eski filial nomi" if snaps else None,
                 till_code_snapshot="K-02" if snaps else None,
                 terminal_name_snapshot="Kassa-2" if snaps else None)
        for name, pid, q, price, disc, lt, unit_id in lines:
            s.items.append(SaleItem(product_id=uuid.UUID(pid), name_snapshot=name, qty=Decimal(q),
                                    unit_price=Decimal(price), unit_cost=Decimal("0"),
                                    discount=Decimal(disc), line_total=Decimal(lt),
                                    unit_id=unit_id))
        for method, amount, given, change, paid_at in payments:
            s.payments.append(SalePayment(method_code=method, amount=Decimal(amount),
                                          given_amount=Decimal(given) if given else None,
                                          change_amount=Decimal(change) if change else None,
                                          paid_at=paid_at))
        db.add(s)
        db.commit()
        return str(s.id)


def _receipt(client, h, sid):
    r = client.get(f"/api/v1/sales/{sid}/receipt", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def d(client):
    from app.models.catalog import Product, Unit
    ega = _dokon(client, name="QA DTO do'koni")
    H = ega["h"]
    a1 = _filial(client, H, "DTO A1", address="Bishkek, Chuy 1", phone="+996 555 000 111",
                 timezone="Asia/Bishkek")
    a2 = _filial(client, H, "DTO A2")
    x = {"ega": ega,
         "menejer": _xodim(client, H, "menejer"),
         "menejer@A2": _xodim(client, H, "menejer", filial=a2),
         "omborchi": _xodim(client, H, "omborchi"),
         "kassir@A1": _xodim(client, H, "kassir", ism="Kassir Birinchi", filial=a1),
         "kassir2@A1": _xodim(client, H, "kassir", ism="Kassir Ikkinchi", filial=a1),
         "kassir@A2": _xodim(client, H, "kassir", filial=a2),
         "kassir@A1-sotuvlar.view": _xodim(client, H, "kassir", filial=a1,
                                           override={"sotuvlar.view": False})}
    x["begona-ega"] = _dokon(client, plan="start", name="Begona DTO do'koni")
    r = client.put("/api/v1/settings", headers=H, json={"key": "store_info", "value": {
        "name": "Fayz Market", "stir": "301234567", "address": "Toshkent sh.",
        "phone": "+998 71 200 00 00"}})
    assert r.status_code == 200, r.text
    pid = _product(client, H)
    wpid = _product(client, H)
    with _db() as db:
        kg = db.query(Unit).filter(Unit.code == "kg").one()
        p = db.get(Product, uuid.UUID(wpid))
        p.is_weighted, p.unit_id, p.name = True, kg.id, "Pomidor (joriy nom)"
        db.commit()
        dona = db.query(Unit).filter(Unit.code == "dona").one().id
        from app.models.org import Branch
        a1_phone = db.get(Branch, uuid.UUID(a1)).phone          # normallashtirilgan (+996...)
    assert a1_phone and a1_phone.startswith("+996")
    _qoldiq(pid, a1, 10_000)
    sale = _karta_sotuv(client, x["kassir@A1"]["h"], pid, qty=3)
    return {"x": x, "cid": ega["cid"], "a1": a1, "a2": a2, "pid": pid, "wpid": wpid,
            "dona": dona, "sale": sale, "a1_phone": a1_phone}


# ══ 1 · SOTUV XARITASI ═══════════════════════════════════════════════════════
def test_API_sotuv_cheki_SHAKLI_va_invariantlar(client, d):
    s = d["sale"]
    dto = _receipt(client, d["x"]["kassir@A1"]["h"], s["id"])
    assert set(dto) == {"schema", "kind", "test", "provisional", "doc", "store", "actor", "customer",
                        "lines", "totals", "payments", "refund", "original", "barcode", "qr",
                        "logo", "template"}
    assert (dto["schema"], dto["kind"], dto["test"], dto["provisional"]) == (
        "binos.receipt.v1", "SALE", False, False)
    doc = dto["doc"]
    assert (doc["id"], doc["number"], doc["uid"]) == (s["id"], s["receipt_no"], s["uid"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$", doc["issued_at"]), doc
    assert re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", doc["issued_at_local"]), doc
    assert (doc["tz"], doc["is_offline"], doc["status"]) == ("Asia/Bishkek", False, "completed")
    assert dto["store"] == {"name": "Fayz Market", "branch_name": "DTO A1",
                            "address": "Bishkek, Chuy 1", "phone": d["a1_phone"],
                            "stir": "301234567"}
    assert dto["actor"]["cashier"] == "Kassir Birinchi"
    assert [(ln["qty"], ln["unit"], ln["weighted"], ln["total"]) for ln in dto["lines"]] == [
        ("3.000", "dona", False, "300.00")]
    assert dto["payments"] == [{"method": "card", "amount": "300.00", "given": None, "change": None}]
    assert dto["totals"] == {"currency": "UZS", "subtotal": "300.00", "line_discount": "0.00",
                             "doc_discount": "0.00", "rounding": "0.00", "total": "300.00"}
    assert dto["template"] == RS.template_of(RS.BUILTIN)
    assert (dto["barcode"], dto["qr"], dto["logo"], dto["customer"], dto["refund"],
            dto["original"]) == (None,) * 6
    _invariant(dto)
    _sums_to_total(dto)


def test_ORM_sotuv_TOLIQ_xarita_yaxlitlash_chegirma_split_tolov_snapshot(client, d):
    t0 = SOLD
    sid = _orm_sale(d, [
        ("Pomidor", d["wpid"], "0.352", "12000", "0", "4224.00", None),
        ("Non «Buxanka»", d["pid"], "2", "3500", "500", "6500.00", d["dona"]),
        ("Sut 3,2%", d["pid"], "1", "12000.55", "0", "12000.55", None),
    ], [("cash", "10000", "20000", "10000", t0 + timedelta(seconds=2)),
        ("card", "11725", None, None, t0 + timedelta(seconds=1))],
        total="21725", doc_disc="1000")
    dto = _receipt(client, d["x"]["kassir@A1"]["h"], sid)
    assert dto["lines"] == [
        {"name": "Pomidor", "qty": "0.352", "unit": "kg", "weighted": True, "unit_price": "12000.00",
         "gross": "4224.00", "discount": "0.00", "total": "4224.00"},
        {"name": "Non «Buxanka»", "qty": "2.000", "unit": "dona", "weighted": False,
         "unit_price": "3500.00", "gross": "7000.00", "discount": "500.00", "total": "6500.00"},
        {"name": "Sut 3,2%", "qty": "1.000", "unit": "dona", "weighted": False,
         "unit_price": "12000.55", "gross": "12000.55", "discount": "0.00", "total": "12000.55"},
    ]
    assert dto["totals"] == {"currency": "UZS", "subtotal": "23224.55", "line_discount": "500.00",
                             "doc_discount": "1000.00", "rounding": "0.45", "total": "21725.00"}
    # To'lovlar `paid_at` tartibida (karta avval).
    assert dto["payments"] == [
        {"method": "card", "amount": "11725.00", "given": None, "change": None},
        {"method": "cash", "amount": "10000.00", "given": "20000.00", "change": "10000.00"}]
    # Snapshot'lar joriy nomlardan USTUN (filial "DTO A1" deb qayta nomlangan bo'lsa ham).
    assert dto["store"]["branch_name"] == "Eski filial nomi"
    assert dto["actor"] == {"cashier": "Kassir Surat", "till_code": "K-02", "terminal": "Kassa-2"}
    assert (dto["doc"]["issued_at"], dto["doc"]["issued_at_local"]) == (
        "2026-09-19T03:32:11+00:00", "19.09.2026 09:32")         # Bishkek +6
    _invariant(dto)
    _sums_to_total(dto)


def test_SNAPSHOT_yoq_eski_qator_JORIY_nomga_qaytadi(client, d):
    sid = _orm_sale(d, [("X", d["pid"], "1", "100", "0", "100", None)],
                    [("card", "100", None, None, SOLD)], total="100", snaps=False)
    dto = _receipt(client, d["x"]["ega"]["h"], sid)
    assert dto["actor"] == {"cashier": "Kassir Birinchi", "till_code": None, "terminal": None}
    assert dto["store"]["branch_name"] == "DTO A1"


def test_QATORLAR_SAVAT_tartibida(client, d):
    names = [f"Q{i:02d} {uuid.uuid4().hex[:4]}" for i in range(12)]
    sid = _orm_sale(d, [(n, d["pid"], "1", "10", "0", "10", None) for n in names],
                    [("card", "120", None, None, SOLD)], total="120")
    assert [ln["name"] for ln in _receipt(client, d["x"]["ega"]["h"], sid)["lines"]] == names


def test_ESKI_buzuq_malumot_QIYMATLAR_OZGARTIRILMAYDI(client, d):
    """Σ to'lov ≠ jami (eski ma'lumot) — DTO saqlangan qiymatni qaytaradi, to'qimaydi."""
    sid = _orm_sale(d, [("Y", d["pid"], "1", "1000", "0", "1000", None)],
                    [("card", "900", None, None, SOLD)], total="1000")
    dto = _receipt(client, d["x"]["ega"]["h"], sid)
    assert dto["payments"][0]["amount"] == "900.00" and dto["totals"]["total"] == "1000.00"
    _invariant(dto)


def test_QATORSIZ_tarixiy_sotuv_YAXLITLASH_qatori_TOQILMAYDI(client, d):
    """Tarixdan import qilingan smena yig'indisi (qatorsiz sotuv): butun tushum «Yaxlitlash»
    bo'lib chiqmasin — oraliq jami = jami, yaxlitlash 0, invariant saqlanadi."""
    sid = _orm_sale(d, [], [("cash", "1234567", None, None, SOLD)], total="1234567")
    dto = _receipt(client, d["x"]["ega"]["h"], sid)
    assert dto["lines"] == []
    assert dto["totals"] == {"currency": "UZS", "subtotal": "1234567.00", "line_discount": "0.00",
                             "doc_discount": "0.00", "rounding": "0.00", "total": "1234567.00"}
    _invariant(dto)
    _sums_to_total(dto)
    # Chegirmali qatorsiz yozuv ham — yaxlitlash 0.
    sid = _orm_sale(d, [], [("card", "9500", None, None, SOLD)], total="9500", doc_disc="500")
    t = _receipt(client, d["x"]["ega"]["h"], sid)["totals"]
    assert (t["subtotal"], t["doc_discount"], t["rounding"], t["total"]) == (
        "10000.00", "500.00", "0.00", "9500.00")


def test_MIJOZ_faqat_show_customer_bilan_SHTRIX_va_QR_uid(client, d):
    H = d["x"]["ega"]["h"]
    cust = _mijoz(d["cid"], "Aliyev Vali")
    sid = _orm_sale(d, [("Z", d["pid"], "1", "50", "0", "50", None)],
                    [("card", "50", None, None, SOLD)], total="50", customer=cust, uid="2609191288")
    dto = _receipt(client, H, sid)
    assert dto["customer"] is None and dto["barcode"] is None and dto["qr"] is None
    assert _put(client, H, {"show_customer": True, "show_barcode": True, "qr_mode": "receipt_id"},
                d["a1"]).status_code == 200
    try:
        dto = _receipt(client, H, sid)
        assert dto["customer"] == {"name": "Aliyev Vali"}
        assert dto["barcode"] == {"format": "CODE128", "payload": "2609191288",
                                  "modules": C.code128_modules("2609191288")}
        assert dto["qr"]["kind"] == "receipt_id" and dto["qr"]["payload"] == "2609191288"
        assert dto["qr"]["matrix"] == C.qr_matrix("2609191288")
        assert dto["template"]["show_customer"] is True and "qr_url" not in dto["template"]
    finally:
        assert _put(client, H, {"show_customer": None, "show_barcode": None, "qr_mode": None},
                    d["a1"]).status_code == 200


# ══ 2 · QAYTARISH ════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def ret(client, d):
    r = _qaytar(client, d["x"]["kassir@A1"]["h"], d["sale"]["id"], d["pid"])
    assert r.status_code == 200, r.text
    return r.json()


def test_QAYTARISH_cheki_xaritasi(client, d, ret):
    r = client.get(f"/api/v1/returns/{ret['id']}/receipt", headers=d["x"]["kassir@A1"]["h"])
    assert r.status_code == 200, r.text
    dto = r.json()
    assert dto["kind"] == "RETURN" and dto["doc"]["number"] == ret["return_no"]
    assert dto["doc"]["uid"] is None and dto["payments"] == [] and dto["barcode"] is None
    assert dto["refund"] == {"method": "card", "amount": "100.00"}
    assert dto["original"]["number"] == d["sale"]["receipt_no"]
    assert dto["original"]["id"] == d["sale"]["id"] and dto["original"]["uid"] == d["sale"]["uid"]
    [ln] = dto["lines"]
    assert (ln["qty"], ln["unit_price"], ln["total"], ln["discount"]) == ("1.000", "100.00", "100.00",
                                                                          "0.00")
    assert dto["actor"]["cashier"] == "Kassir Birinchi"
    _invariant(dto)


def test_QAYTARISH_chekSIZ_nom_mahsulotdan_yaxlitlash_OCHIQ(client, d):
    from app.models.sales import Return, ReturnItem
    with _db() as db:
        rt = Return(return_no=f"QAY-T{uuid.uuid4().int % 10**6}", company_id=uuid.UUID(d["cid"]),
                    branch_id=uuid.UUID(d["a1"]), cashier_id=uuid.UUID(d["x"]["kassir@A1"]["id"]),
                    refund_method="credit", total=Decimal("333"))
        rt.items.append(ReturnItem(product_id=uuid.UUID(d["wpid"]), qty=Decimal("0.333"),
                                   unit_price=Decimal("1000.99"), unit_cost=Decimal("0"),
                                   line_total=Decimal("333.33")))
        db.add(rt)
        db.commit()
        rid = str(rt.id)
    dto = client.get(f"/api/v1/returns/{rid}/receipt", headers=d["x"]["ega"]["h"]).json()
    assert dto["original"] is None
    assert dto["lines"] == [{"name": "Pomidor (joriy nom)", "qty": "0.333", "unit": "kg",
                             "weighted": True, "unit_price": "1000.99", "gross": "333.33",
                             "discount": "0.00", "total": "333.33"}]
    assert dto["totals"]["rounding"] == "-0.33" and dto["totals"]["total"] == "333.00"
    assert dto["refund"] == {"method": "credit", "amount": "333.00"}
    _invariant(dto)


def test_QAYTARISH_qatori_CHOP_ETILGAN_kopaytma_sarlavha_chegirmasi(client, d):
    """3 × 100, sarlavha chegirmasi 1 (jami 299), 2 dona qaytarish: saqlangan narx
    100·299/300 = 99.666…, `line_total` = 199.33 — alohida yaxlitlangan. Chekda
    «2 × 99,67 = 199,33» noto'g'ri ko'rinardi; qator = 199.34, farq — ochiq yaxlitlashda,
    jami va qaytarilgan summa (199) O'ZGARMAYDI."""
    from app.models.sales import ReturnItem
    h = d["x"]["kassir@A1"]["h"]
    r = client.post("/api/v1/sales", headers=h, json={
        "items": [{"product_id": d["pid"], "qty": 3, "unit_price": 100}], "discount_total": 1,
        "payment_method": "card", "given_amount": 299, "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json()["total"] == 299, r.text
    rr = client.post("/api/v1/returns", headers=h, json={
        "original_sale_id": r.json()["id"], "reason": "customer", "restock": True,
        "refund_method": "card", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": d["pid"], "qty": 2, "unit_price": 0}]})
    assert rr.status_code == 200, rr.text
    with _db() as db:
        [it] = db.query(ReturnItem).filter(ReturnItem.return_id == uuid.UUID(rr.json()["id"])).all()
        stored = _D(str(it.line_total)).quantize(_D("0.01"))
    assert stored == _D("199.33")                  # yozish yo'li o'zgarmagan
    dto = client.get(f"/api/v1/returns/{rr.json()['id']}/receipt", headers=h).json()
    [ln] = dto["lines"]
    assert (ln["qty"], ln["unit_price"], ln["gross"], ln["total"]) == (
        "2.000", "99.67", "199.34", "199.34")
    for ln in dto["lines"]:
        assert (_D(ln["qty"]) * _D(ln["unit_price"])).quantize(_D("0.01")) == _D(ln["total"]), ln
    assert dto["totals"] == {"currency": "UZS", "subtotal": "199.34", "line_discount": "0.00",
                             "doc_discount": "0.00", "rounding": "-0.34", "total": "199.00"}
    assert dto["refund"] == {"method": "card", "amount": "199.00"}
    _invariant(dto)


QAYT_ROLLAR = [("kassir@A1", 200), ("kassir2@A1", 404), ("menejer", 200), ("menejer@A2", 404),
               ("kassir@A2", 404), ("begona-ega", 404), ("omborchi", 403), ("ega", 200)]


@pytest.mark.parametrize("rol,kod", QAYT_ROLLAR, ids=[r for r, _ in QAYT_ROLLAR])
def test_QAYTARISH_cheki_RUXSAT(client, d, ret, rol, kod):
    r = client.get(f"/api/v1/returns/{ret['id']}/receipt", headers=d["x"][rol]["h"])
    assert r.status_code == kod, (rol, r.text)
    if kod == 404:
        assert r.json() == QYOQ
    if kod == 403:
        assert r.json() == {"detail": "Ruxsat yo'q: qaytarishlar.view / qaytarishlar.create"}


def test_QAYTARISH_yoq_va_buzuq_id(client, d):
    h = d["x"]["menejer"]["h"]
    assert client.get(f"/api/v1/returns/{uuid.uuid4()}/receipt", headers=h).json() == QYOQ
    assert client.get("/api/v1/returns/buzuq/receipt", headers=h).status_code == 422


# ══ 3 · SOTUV CHEKI RUXSATI (`GET /sales/{id}` doirasi + MUALLIF istisnosi) ═══
# (rol, chek kodi, `GET /sales/{id}` kodi). Farq FAQAT tarixsiz (`kassa.sell`) kassirda:
# BOSHQANING sotuvi cheki — 404 (oracle yo'q), tarix esa baribir 403.
SOT_ROLLAR = [("ega", 200, 200), ("menejer", 200, 200), ("menejer@A2", 404, 404),
              ("omborchi", 403, 403), ("kassir@A1", 200, 200), ("kassir2@A1", 200, 200),
              ("kassir@A2", 404, 404), ("kassir@A1-sotuvlar.view", 404, 403),
              ("begona-ega", 404, 404)]
_CHEK_403 = {"detail": "Ruxsat yo'q: sotuvlar.view / hisobot.view / kassa.sell"}


@pytest.mark.parametrize("rol,kod,gkod", SOT_ROLLAR, ids=[r for r, _, _ in SOT_ROLLAR])
def test_SOTUV_cheki_RUXSAT_get_sale_doirasi(client, d, rol, kod, gkod):
    h = d["x"][rol]["h"]
    sid = d["sale"]["id"]
    r = client.get(f"/api/v1/sales/{sid}/receipt", headers=h)
    g = client.get(f"/api/v1/sales/{sid}", headers=h)
    assert (r.status_code, g.status_code) == (kod, gkod), (rol, r.text, g.text)
    if kod == 404:
        assert r.json() == YOQ
        assert client.get(f"/api/v1/sales/{uuid.uuid4()}/receipt", headers=h).content == r.content
    if kod == 403:
        assert r.json() == _CHEK_403
        assert g.json() == {"detail": "Ruxsat yo'q: sotuvlar.view / hisobot.view"}
        assert client.get("/api/v1/sales/buzuq/receipt", headers=h).status_code == 403
    if kod != 403:
        assert client.get("/api/v1/sales/buzuq/receipt", headers=h).status_code == 422
    assert client.get(f"/api/v1/sales/{sid}/receipt").status_code == 401


def test_TARIXSIZ_kassir_OZ_sotuvi_chekini_oladi_tarix_YOPIQ_qoladi(client, d):
    """`sotuvlar.view` o'chirilgan kassir (faqat `kassa.sell`): o'zi urgan onlayn sotuvga chek
    chiqadi (chek faqat server DTO'sidan), lekin `GET /sales/{id}` — 403 (tarix yopiq)."""
    x = d["x"]
    h = x["kassir@A1-sotuvlar.view"]["h"]
    own = _karta_sotuv(client, h, d["pid"], qty=2)
    dto = _receipt(client, h, own["id"])
    assert (dto["doc"]["id"], dto["doc"]["number"]) == (own["id"], own["receipt_no"])
    assert dto["totals"]["total"] == "200.00"
    _invariant(dto)
    g = client.get(f"/api/v1/sales/{own['id']}", headers=h)
    assert g.status_code == 403, g.text
    # Boshqa kassirning sotuvi — 404 (mavjud bo'lmagan id bilan AYNI javob).
    r = client.get(f"/api/v1/sales/{d['sale']['id']}/receipt", headers=h)
    assert r.status_code == 404 and r.json() == YOQ
    # Tarix ko'radigan kassirlar uchun hech narsa o'zgarmadi.
    assert client.get(f"/api/v1/sales/{own['id']}/receipt",
                      headers=x["kassir2@A1"]["h"]).status_code == 200
    assert client.get(f"/api/v1/sales/{own['id']}/receipt",
                      headers=x["kassir@A2"]["h"]).status_code == 404


# ══ 3b · NOFAOL FILIAL KASSIRI (sotuv `actor_branch` zaxirasiga tushadi) ═════
@pytest.fixture(scope="module")
def nf(client):
    """Kassir D filialiga biriktirilgan, D NOFAOL: uning sotuvi birinchi faol filialga (A0)
    yoziladi — A0 esa uning ko'rinadigan to'plamida (`{D}`) yo'q."""
    ega = _dokon(client, name="QA nofaol filial do'koni")
    H = ega["h"]
    a0 = _asosiy(client, H)
    dd = _filial(client, H, "NF D")
    ee = _filial(client, H, "NF E")
    kd = _xodim(client, H, "kassir", ism="Kassir D", filial=dd)
    k0 = _xodim(client, H, "kassir", ism="Kassir A0", filial=a0)
    pid = _product(client, H)
    _qoldiq(pid, a0, 1000)
    r = client.patch(f"/api/v1/branches/{dd}", headers=H, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False, r.text
    own = _karta_sotuv(client, kd["h"], pid, qty=1)
    other = _karta_sotuv(client, k0["h"], pid, qty=1)
    assert own["branch_id"] == other["branch_id"] == a0, (own, a0)
    return {"H": H, "cid": ega["cid"], "a0": a0, "dd": dd, "ee": ee, "kd": kd, "k0": k0,
            "pid": pid, "own": own, "other": other}


def _orm_return(nf, cashier_id, total="100"):
    from app.models.sales import Return, ReturnItem
    with _db() as db:
        rt = Return(return_no=f"QAY-NF{uuid.uuid4().int % 10**6}", company_id=uuid.UUID(nf["cid"]),
                    branch_id=uuid.UUID(nf["a0"]), cashier_id=uuid.UUID(cashier_id),
                    refund_method="card", total=Decimal(total))
        rt.items.append(ReturnItem(product_id=uuid.UUID(nf["pid"]), qty=Decimal("1"),
                                   unit_price=Decimal(total), unit_cost=Decimal("0"),
                                   line_total=Decimal(total)))
        db.add(rt)
        db.commit()
        return str(rt.id)


def test_NOFAOL_filial_kassiri_OZ_sotuvi_va_qaytarishi_cheki_va_jurnali(client, nf):
    h = nf["kd"]["h"]
    dto = _receipt(client, h, nf["own"]["id"])
    assert dto["doc"]["number"] == nf["own"]["receipt_no"]
    j = client.post("/api/v1/print-jobs", headers=h, json={
        "id": str(uuid.uuid4()), "doc_type": "SALE", "doc_id": nf["own"]["id"], "copy": "ORIGINAL"})
    assert j.status_code == 201, j.text
    assert client.patch(f"/api/v1/print-jobs/{j.json()['id']}", headers=h,
                        json={"status": "PRINTED"}).status_code == 200
    rid = _orm_return(nf, nf["kd"]["id"])
    r = client.get(f"/api/v1/returns/{rid}/receipt", headers=h)
    assert r.status_code == 200 and r.json()["doc"]["id"] == rid, r.text
    assert client.post("/api/v1/print-jobs", headers=h, json={
        "id": str(uuid.uuid4()), "doc_type": "RETURN", "doc_id": rid,
        "copy": "ORIGINAL"}).status_code == 201


def test_NOFAOL_filial_kassiri_BOSHQANING_hujjati_HAMON_404(client, nf):
    """Muallif istisnosi doirani KENGAYTIRMAYDI: zaxira filialdagi boshqa kassir sotuvi —
    `GET /sales/{id}` bilan AYNI 404, jurnalda ham."""
    h = nf["kd"]["h"]
    oid = nf["other"]["id"]
    r = client.get(f"/api/v1/sales/{oid}/receipt", headers=h)
    assert r.status_code == 404 and r.json() == YOQ
    assert client.get(f"/api/v1/sales/{oid}", headers=h).status_code == 404
    j = client.post("/api/v1/print-jobs", headers=h, json={
        "id": str(uuid.uuid4()), "doc_type": "SALE", "doc_id": oid, "copy": "REPRINT"})
    assert j.status_code == 404 and j.json() == YOQ
    r = client.get(f"/api/v1/returns/{_orm_return(nf, nf['k0']['id'])}/receipt", headers=h)
    assert r.status_code == 404 and r.json() == QYOQ
    # O'sha sotuv o'z egasiga va egaga ochiq.
    assert client.get(f"/api/v1/sales/{oid}/receipt", headers=nf["k0"]["h"]).status_code == 200
    assert client.get(f"/api/v1/sales/{oid}/receipt", headers=nf["H"]).status_code == 200


def test_NOFAOL_filial_kassiri_PROFIL_va_NAMUNA_standart_filial_ANIQ_ham_ochiq(client, nf):
    """Standart (`actor_branch`) va aynan o'sha filial aniq so'ralganda — BIR XIL javob."""
    h = nf["kd"]["h"]
    p = client.get("/api/v1/receipt/profile", headers=h).json()
    assert p["branch_id"] == nf["a0"]
    pa = client.get("/api/v1/receipt/profile", headers=h, params={"branch_id": nf["a0"]})
    assert pa.status_code == 200 and pa.json()["etag"] == p["etag"], pa.text
    s = client.get("/api/v1/receipt/sample", headers=h, params={"branch_id": nf["a0"]})
    assert s.status_code == 200, s.text
    assert s.json()["store"]["branch_name"] == client.get(
        "/api/v1/receipt/sample", headers=h).json()["store"]["branch_name"]
    # Boshqa ko'rinmas filial — hamon 404.
    for path in ("/api/v1/receipt/profile", "/api/v1/receipt/sample"):
        r = client.get(path, headers=h, params={"branch_id": nf["ee"]})
        assert r.status_code == 404 and r.json() == {"detail": "Filial topilmadi"}, path


# ══ 4 · NAMUNA ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kind", ["sale", "mixed", "return", "long"])
def test_NAMUNA_har_tur_invariant_TEST_belgisi(client, d, kind):
    for rol in ("ega", "kassir@A1", "menejer"):
        r = client.get("/api/v1/receipt/sample", headers=d["x"][rol]["h"], params={"kind": kind})
        assert r.status_code == 200, (rol, r.text)
        dto = r.json()
        assert dto["test"] is True and dto["doc"]["id"] is None and dto["doc"]["number"] == "TEST"
        assert dto["kind"] == ("RETURN" if kind == "return" else "SALE")
        _invariant(dto)
        if kind == "return":
            assert dto["refund"]["amount"] == dto["totals"]["total"] and dto["payments"] == []
            assert dto["original"]["number"] == "TEST"
        else:
            _sums_to_total(dto)
    if kind == "mixed":
        assert [p["method"] for p in dto["payments"]] == ["cash", "card", "qr"]
    if kind == "long":
        assert len(dto["lines"]) == 121
        text = " ".join(ln["name"] for ln in dto["lines"])
        for ch in ("ң", "ө", "ү", "ʻ", "Ў", "қ", "ҳ", "М"):
            assert ch in text, ch
        assert any(ln["qty"] == "0.001" and ln["weighted"] for ln in dto["lines"])
        assert _D(dto["totals"]["total"]) >= Decimal("100000000")
        assert _D(dto["totals"]["line_discount"]) > 0 and _D(dto["totals"]["doc_discount"]) > 0


def test_NAMUNA_ruxsat_va_filial(client, d):
    x = d["x"]
    assert client.get("/api/v1/receipt/sample", headers=x["omborchi"]["h"]).status_code == 403
    assert client.get("/api/v1/receipt/sample", headers=x["ega"]["h"],
                      params={"kind": "xyz"}).status_code == 422
    r = client.get("/api/v1/receipt/sample", headers=x["kassir@A1"]["h"],
                   params={"branch_id": d["a2"]})
    assert r.status_code == 404 and r.json() == {"detail": "Filial topilmadi"}
    r = client.get("/api/v1/receipt/sample", headers=x["kassir@A1"]["h"]).json()
    assert r["store"]["branch_name"] == "DTO A1" and r["doc"]["tz"] == "Asia/Bishkek"


def test_NAMUNA_KOMPANIYA_doirasi_filial_ustamasisiz_faqat_cheklovsiz_xodim(client):
    """`scope=company`: Manager kompaniya standartini tahrirlayotganda namuna xodimning
    (`actor_branch`) filial ustamasini emas — kompaniya shablonini, kompaniya do'kon
    ma'lumotini, kompaniya zonasini va faqat kompaniya logosini ko'rsatadi."""
    import base64
    import io

    from PIL import Image
    ega = _dokon(client, name="QA namuna doirasi")
    H = ega["h"]
    a0 = _asosiy(client, H)
    a1 = _filial(client, H, "ND A1")
    assert client.patch(f"/api/v1/branches/{a0}", headers=H,
                        json={"timezone": "Asia/Bishkek"}).status_code == 200
    b = io.BytesIO()
    Image.new("L", (64, 32), 0).save(b, "PNG")
    lg = client.post("/api/v1/receipt/logos", headers=H, json={
        "branch_id": a0, "data_b64": base64.b64encode(b.getvalue()).decode()})
    assert lg.status_code == 201, lg.text
    assert _put(client, H, {"footer": "Kompaniya rahmat", "qr_mode": "store_url",
                            "qr_url": "https://co.uz/"}).status_code == 200
    assert _put(client, H, {"footer": "A0 ustama", "width_mm": 58, "qr_url": "https://a0.uz/",
                            "logo_id": lg.json()["id"]}, a0).status_code == 200
    # Standart (ega → actor_branch = A0): ustama qo'llanadi.
    s = client.get("/api/v1/receipt/sample", headers=H).json()
    assert (s["template"]["footer"], s["template"]["width_mm"], s["qr"]["payload"]) == (
        "A0 ustama", 58, "https://a0.uz/")
    assert s["logo"]["id"] == lg.json()["id"] and s["store"]["branch_name"] is not None
    # Kompaniya doirasi: FAQAT kompaniya qatori.
    for params in ({"scope": "company"}, {"scope": "company", "branch_id": a1},
                   {"scope": "company", "kind": "long"}):
        r = client.get("/api/v1/receipt/sample", headers=H, params=params)
        assert r.status_code == 200, (params, r.text)
        c = r.json()
        assert (c["template"]["footer"], c["template"]["width_mm"], c["qr"]["payload"]) == (
            "Kompaniya rahmat", 80, "https://co.uz/"), params
        assert c["logo"] is None and c["store"]["branch_name"] is None, params
        assert c["doc"]["tz"] == "Asia/Bishkek" and c["test"] is True, params
        _invariant(c)
    # Filialga bog'langan xodim — 403 + barqaror kod (kompaniya tahriri qoidasi bilan AYNI).
    for rol, fil in (("administrator", a1), ("kassir", a1)):
        h = _xodim(client, H, rol, filial=fil)["h"]
        r = client.get("/api/v1/receipt/sample", headers=h, params={"scope": "company"})
        assert r.status_code == 403, (rol, r.text)
        assert r.json() == {"detail": RS_E.SCOPE_COMPANY_FORBIDDEN}
        assert r.headers.get("X-Error-Code") == "RECEIPT_SCOPE_COMPANY_FORBIDDEN"
        assert client.get("/api/v1/receipt/sample", headers=h).status_code == 200, rol
    # Biriktirilmagan menejer (cheklovsiz) — ruxsat; noto'g'ri doira qiymati — 422.
    mh = _xodim(client, H, "menejer")["h"]
    assert client.get("/api/v1/receipt/sample", headers=mh,
                      params={"scope": "company"}).status_code == 200
    assert client.get("/api/v1/receipt/sample", headers=H,
                      params={"scope": "tenant"}).status_code == 422


# ══ 5 · /sync/push — `id` ════════════════════════════════════════════════════
def test_SYNC_PUSH_natijasida_id_takrorda_HAM(client, d):
    h = d["x"]["kassir@A1"]["h"]
    cu = str(uuid.uuid4())
    rec = {"client_uuid": cu, "payment_method": "card", "given_amount": 100,
           "items": [{"product_id": d["pid"], "qty": 1, "unit_price": 100}]}
    r1 = client.post("/api/v1/sync/push", headers=h, json={"sales": [rec]}).json()["results"][0]
    r2 = client.post("/api/v1/sync/push", headers=h, json={"sales": [rec]}).json()["results"][0]
    assert r1["ok"] is True and r2["ok"] is True and r1["id"] == r2["id"], (r1, r2)
    assert set(r1) == {"client_uuid", "ok", "receipt_no", "id"}
    dto = _receipt(client, h, r1["id"])
    assert dto["doc"]["number"] == r1["receipt_no"] and dto["doc"]["is_offline"] is True


# ══ 6 · TEZLIK ═══════════════════════════════════════════════════════════════
def test_TEZLIK_150_qatorli_chek_DTO(client, d):
    from app.models.sales import Sale
    from app.services.receipt.dto import build_sale_receipt
    lines = [(f"Mahsulot {i:03d} — uzun nom, Ўзбекча/Кыргызча ң ө ү", d["wpid"] if i % 3 else d["pid"],
              "1.234" if i % 3 else "2", "15750.50", "10" if i % 7 == 0 else "0",
              str((Decimal("1.234" if i % 3 else "2") * Decimal("15750.50")).quantize(Decimal("0.01"))
                  - (Decimal("10") if i % 7 == 0 else 0)), None)
             for i in range(150)]
    total = sum(Decimal(ln[5]) for ln in lines).quantize(Decimal("1"))
    sid = _orm_sale(d, lines, [("card", str(total), None, None, SOLD)], total=str(total))
    runs = []
    with _db() as db:
        for _ in range(5):
            db.expire_all()
            sale = db.get(Sale, uuid.UUID(sid))
            t0 = time.perf_counter()
            dto = build_sale_receipt(db, sale)
            runs.append((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    via_http = _receipt(client, d["x"]["ega"]["h"], sid)
    http_ms = (time.perf_counter() - t0) * 1000
    print(f"\n[perf] 150 qatorli chek DTO: server qurish min={min(runs):.1f} ms "
          f"o'rtacha={sum(runs) / len(runs):.1f} ms; HTTP {http_ms:.1f} ms")
    assert len(dto["lines"]) == 150 and via_http["lines"] == dto["lines"]
    _invariant(dto)
    assert min(runs) < 1500, runs              # saxiy chegara (odatda ~10–30 ms)
    assert http_ms < 5000, http_ms


# ══ 7 · SOTUV CHEK KODIDAN MUSTAQIL ══════════════════════════════════════════
def test_SOTUV_DTO_quruvchisi_YIQILSA_HAM_yoziladi(client, d, monkeypatch):
    from app.services.receipt import codes, dto, settings as rs

    def boom(*a, **k):
        raise RuntimeError("chek kodi yiqildi")
    for mod, name in ((dto, "build_sale_receipt"), (dto, "build_return_receipt"),
                      (dto, "assemble"), (codes, "code128_modules"), (codes, "qr_matrix"),
                      (rs, "resolve_for_branch"), (rs, "effective")):
        monkeypatch.setattr(mod, name, boom)
    h = d["x"]["kassir@A1"]["h"]
    sale = _karta_sotuv(client, h, d["pid"], qty=2)
    assert sale["receipt_no"].startswith("#")
    r = _qaytar(client, h, sale["id"], d["pid"])
    assert r.status_code == 200, r.text
    p = client.post("/api/v1/sync/push", headers=h, json={"sales": [{
        "client_uuid": str(uuid.uuid4()), "payment_method": "card", "given_amount": 100,
        "items": [{"product_id": d["pid"], "qty": 1, "unit_price": 100}]}]})
    assert p.status_code == 200 and p.json()["accepted"] == 1, p.text
    # SALBIY NAZORAT: yamoq HAQIQATAN faol — chek endpointi aynan shu kodni chaqiradi.
    with pytest.raises(RuntimeError, match="chek kodi yiqildi"):
        client.get(f"/api/v1/sales/{sale['id']}/receipt", headers=h)


_YOZISH_YOLI = ("app/services/sales.py", "app/api/v1/sales.py", "app/api/v1/sync.py")


def _receipt_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names = {a.name for a in node.names}
            if mod.startswith("app.services.receipt") or mod.startswith("app.api.v1.receipts") or (
                    mod in ("app.services", "app.api.v1") and names & {"receipt", "receipts"}):
                bad.append(f"{path.name}:{node.lineno} from {mod} import {sorted(names)}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith(("app.services.receipt", "app.api.v1.receipts")):
                    bad.append(f"{path.name}:{node.lineno} import {a.name}")
    return bad


def test_SOTUV_YOZISH_YOLI_chek_paketini_IMPORT_QILMAYDI(tmp_path):
    bad = [b for f in _YOZISH_YOLI for b in _receipt_imports(SRV / f)]
    assert not bad, bad
    # SALBIY NAZORAT: tekshiruvchi haqiqatan ushlaydi (funksiya ichidagi import ham).
    for src in ("def f():\n    from app.services.receipt import dto\n",
                "from app.services import receipt\n", "import app.api.v1.receipts\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(src, encoding="utf-8")
        assert _receipt_imports(probe), src
    # Jarayon darajasida: sotuv servisini yuklash chek paketini yuklamaydi.
    r = subprocess.run([sys.executable, "-c",
                        "import sys, app.services.sales; "
                        "print(sorted(m for m in sys.modules if m.startswith('app.services.receipt')))"],
                       cwd=SRV, capture_output=True, text=True, timeout=120,
                       env={**__import__('os').environ, "DATABASE_URL": "sqlite://", "APP_ENV": "dev"})
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip() == "[]", r.stdout
