# -*- coding: utf-8 -*-
"""Q2/Q3 — BIRLIK DARVOZASI HAR YOZUVCHIDA (uchdan-uchiga, HTTP orqali).

Isbotlanadi, har bir miqdor-yozuvchi yo'l uchun:
  1. bo'linmas birlikda (`dona`) KASR miqdor -> **400**;
  2. rad etilganda **hech qanday qism-o'zgarish YO'Q** (qoldiq TEGILMAGAN);
  3. ayni yo'l BUTUN miqdor bilan ishlaydi (darvoza yaroqlini to'smaydi);
  4. kasrli birlik (`kg`) KASR miqdor bilan ishlaydi (regressiya YO'Q);
  5. AGREGATSIYA yuvishi to'siladi (`0.5 + 0.5` -> 400, `1` emas).

⚠️  NEGA HTTP ORQALI. `test_unit_gate.py` validatorning O'ZINI o'lchaydi. Bu fayl
    esa DARVOZA QO'YILGAN JOYNI o'lchaydi: tekshiruv mutatsiyadan, qulflardan va
    arifmetikadan OLDIN turganini faqat uchdan-uchiga so'rov isbotlaydi.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.models.auth import Employee, Role
from app.models.catalog import Product, Unit
from app.models.enums import EmployeeStatus
from app.models.inventory import Inventory
from app.models.org import Branch, Company
from app.models.purchasing import Supplier

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"

# ⚠️  MATN NUSXASI ATAYLAB (repo naqshi): koddan import qilsak, matn o'zgarganini
#     test KO'RMASDI — o'zgargan matn o'zgargan kutilma bilan birga kelardi.
KUTILGAN = "Bu mahsulot faqat butun miqdorda o'lchanadi — kasr miqdor kiritilmaydi"


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _dokon(filiallar: int = 1) -> dict:
    """Toza do'kon: filial(lar) ANIQ tartibda, `ega` + token, ta'minotchi."""
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="Birlik darvozasi",
                       code="ug" + uuid.uuid4().hex[:8], currency="UZS")
        db.add(comp)
        db.flush()
        bids = []
        for i in range(filiallar):
            br = Branch(id=uuid.uuid4(), company_id=comp.id, name=f"F0{i + 1}",
                        code=f"F0{i + 1}", timezone=TZ, is_active=True,
                        created_at=NOW - timedelta(days=10 - i))
            db.add(br)
            db.flush()
            bids.append(br.id)
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                       full_name="Darvoza ega", phone=f"+9987{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        sup = Supplier(id=uuid.uuid4(), company_id=comp.id, name="Darvoza ta'minotchi")
        db.add(sup)
        db.commit()
        tok = create_access_token(str(emp.id), {"role": "ega", "company_id": str(comp.id),
                                                "sv": 0})
        return {"cid": comp.id, "bids": bids, "eid": emp.id, "sup": sup.id,
                "H": {"Authorization": f"Bearer {tok}"}}


def _mahsulot(d: dict, unit_code: str, *, qty=0, bid=None):
    """Berilgan BIRLIK kodidagi mahsulot + boshlang'ich qoldiq (to'g'ridan bazada).

    Boshlang'ich qoldiq ATAYLAB API orqali EMAS: `/products/bulk` ning o'zi endi
    darvozali, ya'ni sahna qurish uni ham sinardi va yiqilish sababi ikkilanardi.
    """
    bid = bid or d["bids"][0]
    with _db() as db:
        u = db.query(Unit).filter_by(code=unit_code).one()
        p = Product(id=uuid.uuid4(), company_id=d["cid"],
                    name=f"{unit_code.upper()} " + uuid.uuid4().hex[:6],
                    article_code="U-" + uuid.uuid4().hex[:10], sku=uuid.uuid4().hex[:8],
                    unit_id=u.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, branch_id=bid, qty=Decimal(str(qty)),
                         min_qty=0, updated_at=NOW))
        db.commit()
        return p.id


def _qoldiq(pid, bid) -> Decimal:
    with _db() as db:
        inv = (db.query(Inventory)
               .filter(Inventory.product_id == pid, Inventory.branch_id == bid).first())
        return Decimal(str(inv.qty)) if inv else Decimal("0")


def _harakatlar(pid) -> int:
    from app.models.inventory import StockMovement
    with _db() as db:
        return db.query(StockMovement).filter(StockMovement.product_id == pid).count()


def _rad(r, *, nima: str = ""):
    """Javob DARVOZA matni bilan 400 bo'lsin (boshqa sababli 400 emas)."""
    assert r.status_code == 400, f"{nima}: kutilgan 400, keldi {r.status_code}: {r.text[:300]}"
    det = r.json().get("detail")
    assert isinstance(det, str) and KUTILGAN in det, f"{nima}: darvoza matni yo'q: {det!r}"
    return det


# == 1) SOTUV (`POST /sales`) ================================================
def test_sotuv_kasr_dona_RAD_qoldiq_tegilmagan(client):
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 0.5, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100, "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="sotuv")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000"), "RAD etilgan sotuv qoldiqni siljitdi"
    assert _harakatlar(pid) == 0, "RAD etilgan sotuv ombor harakati yozdi"


def test_sotuv_butun_dona_OTADI(client):
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 2, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 200, "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("8.000")


def test_sotuv_kasr_KG_OTADI(client):
    """REGRESSIYA NAZORATI — tarozi mahsuloti kasr sotiladi va BUZILMASIN."""
    d = _dokon()
    pid = _mahsulot(d, "kg", qty=10)
    r = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 0.426, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100, "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("9.574")


def test_sotuv_AGREGATSIYA_YUVISHI(client):
    """Savatda ayni mahsulot IKKI qatorda: `0.5 + 0.5 = 1` — jami butun, RAD."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 0.5, "unit_price": 100},
                  {"product_id": str(pid), "qty": 0.5, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100, "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="sotuv agregatsiyasi")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")


def test_sotuv_qty_TENG_qoldiq_OTADI(client):
    """Mavjud invariant: `qty == stock` RUXSAT (darvoza buni to'smasin)."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=3)
    r = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 3, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 300, "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("0.000")


# == 2) OFFLINE SINXRONLASH (`POST /sync/push`) — DEAD-LETTER ================
def test_sync_push_kasr_dona_RETRY_EMAS(client):
    """⚠️  CHEKSIZ QAYTA URINISH BO'LMASIN.

    `/sync/push` xatoni HTTP holati bo'yicha klassifikatsiya qiladi: `>=500` yoki
    `409` -> TRANZIENT (`retry: True`, klient outbox'da saqlab QAYTA uradi).
    Miqdor xatosi hech qachon o'z-o'zidan tuzalmaydi, shu bois darvoza 400 beradi
    va natija `retry: False` (dead-letter) bo'lishi SHART.
    """
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/sync/push", headers=d["H"], json={"sales": [{
        "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": str(pid), "qty": 0.5, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100}]})
    assert r.status_code == 200, r.text          # konvert OK, ichidagi natija xato
    res = r.json()["results"][0]
    assert res["ok"] is False, res
    assert res.get("retry") is False, f"miqdor xatosi QAYTA URINILADIGAN deb belgilandi: {res}"
    assert KUTILGAN in str(res.get("error", "")), res
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")


# == 3) QAYTARISH (`POST /returns`) ==========================================
def test_qaytarish_kasr_dona_RAD(client):
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    s = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 2, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 200, "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    oldin = _qoldiq(pid, d["bids"][0])
    r = client.post("/api/v1/returns", headers=d["H"], json={
        "original_sale_id": s.json()["id"], "reason": "customer", "restock": True,
        "refund_method": "cash", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": str(pid), "qty": 0.5, "unit_price": 100}]})
    _rad(r, nima="qaytarish")
    assert _qoldiq(pid, d["bids"][0]) == oldin, "RAD etilgan qaytarish qoldiqni siljitdi"


# == 4) XARID (`POST /purchases`) ============================================
def test_xarid_kasr_dona_RAD(client):
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=0)
    r = client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "received",
        "items": [{"product_id": str(pid), "qty": 1.5, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="xarid")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("0.000")
    assert _harakatlar(pid) == 0


def test_xarid_butun_OTADI_kg_kasr_OTADI(client):
    d = _dokon()
    p_dona = _mahsulot(d, "dona", qty=0)
    p_kg = _mahsulot(d, "kg", qty=0)
    r = client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "received",
        "items": [{"product_id": str(p_dona), "qty": 5, "unit_cost": 700},
                  {"product_id": str(p_kg), "qty": 2.25, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(p_dona, d["bids"][0]) == Decimal("5.000")
    assert _qoldiq(p_kg, d["bids"][0]) == Decimal("2.250")


# == 5) XARID TAHRIRI (`PATCH /purchases/{id}`) — DELTA YUVISHI ==============
def test_xarid_tahriri_DELTA_YUVISHI_TOSILADI(client):
    """⚠️  `6.5 - 5 = 1.5` emas, `5 -> 6.5` ning O'ZI yaroqsiz.

    Tahrir qoldiqni ISHORALI delta bilan siljitadi. Agar darvoza deltani
    o'lchasa, `qty: 2.5` ni `qty: 1.5` ustiga yozish delta `+1` bo'lib O'TARDI
    va `purchase_items.qty` bazada `2.5 dona` bo'lib qolardi. Shu bois darvoza
    XOM `upd.qty` ni (YANGI QIYMATNI) o'lchaydi.
    """
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=0)
    r = client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "received",
        "items": [{"product_id": str(pid), "qty": 5, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    pur = r.json()["id"]
    it = client.get(f"/api/v1/purchases/{pur}", headers=d["H"]).json()["items"][0]
    oldin = _qoldiq(pid, d["bids"][0])
    e = client.patch(f"/api/v1/purchases/{pur}", headers=d["H"], json={
        "items": [{"id": it["id"], "qty": 6.5, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    _rad(e, nima="xarid tahriri")
    assert _qoldiq(pid, d["bids"][0]) == oldin, "RAD etilgan tahrir qoldiqni siljitdi"
    with _db() as db:
        from app.models.purchasing import PurchaseItem
        assert Decimal(str(db.get(PurchaseItem, uuid.UUID(it["id"])).qty)) == Decimal("5.000")


# == 6) KIRIM (`POST /receiving/commit`) =====================================
def test_kirim_kasr_dona_RAD(client):
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=0)
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 0.5, "unit_cost": 100, "unit": "dona"}],
        "supplier_id": str(d["sup"]), "payment": "cash",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    _rad(r, nima="kirim")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("0.000")
    assert _harakatlar(pid) == 0


def test_kirim_YANGI_mahsulot_birlik_KODIDAN(client):
    """⚠️  Mahsulot HALI YO'Q: birlik `unit` KODI bo'yicha yechiladi.

    Kirim qatori yangi mahsulot ham yarata oladi (`product_id` yo'q, `new_name` +
    `unit`). Unda birlikni mahsulot orqali yechib BO'LMAYDI — darvoza kod
    bo'yicha yechadi, aks holda bu yo'l darvozani BUTUNLAY chetlab o'tardi.
    """
    d = _dokon()
    nom = "Yangi dona " + uuid.uuid4().hex[:6]
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"new_name": nom, "qty": 0.5, "unit_cost": 100, "unit": "dona",
                   "new_sell_price": 150}],
        "supplier_id": str(d["sup"]), "payment": "cash",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    _rad(r, nima="kirim (yangi mahsulot)")
    with _db() as db:
        assert db.query(Product).filter(Product.company_id == d["cid"],
                                        Product.name == nom).first() is None, \
            "RAD etilgan kirim mahsulot yaratdi"


def test_kirim_YANGI_mahsulot_KG_kasr_OTADI(client):
    d = _dokon()
    nom = "Yangi kg " + uuid.uuid4().hex[:6]
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"new_name": nom, "qty": 0.5, "unit_cost": 100, "unit": "kg",
                   "new_sell_price": 150}],
        "supplier_id": str(d["sup"]), "payment": "cash",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert r.status_code == 200, r.text


# == 7) HISOBDAN CHIQARISH (`POST /inventory/writeoff`) ======================
def test_hisobdan_chiqarish_kasr_dona_RAD(client):
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/inventory/writeoff", headers=d["H"], json={
        "product_id": str(pid), "qty": 0.25, "reason": "brak",
        "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="hisobdan chiqarish")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")
    assert _harakatlar(pid) == 0


def test_hisobdan_chiqarish_butun_OTADI(client):
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/inventory/writeoff", headers=d["H"], json={
        "product_id": str(pid), "qty": 3, "reason": "brak",
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("7.000")


# == 8) SANOQ (`POST /inventory/count`) =====================================
def test_sanoq_kasr_dona_RAD(client):
    """Sanoq qoldiqni MUTLAQ yozadi — `counted=7.5 dona` fizik ma'nosiz."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": [{"product_id": str(pid), "counted": 7.5}],
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="sanoq")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000"), "RAD etilgan sanoq qoldiqni yozdi"
    assert _harakatlar(pid) == 0


def test_sanoq_NOL_va_butun_OTADI(client):
    """`counted=0` BUTUN (va `ge=0` ruxsat) — darvoza nolni to'smasin."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": [{"product_id": str(pid), "counted": 0}],
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("0.000")


def test_sanoq_ikkinchi_qator_buzuq_BIRINCHISI_YOZILMAYDI(client):
    """⚠️  QISM-MUTATSIYA YO'Q. Butun so'rov mutatsiyadan OLDIN tekshiriladi."""
    d = _dokon()
    p_ok = _mahsulot(d, "dona", qty=10)
    p_bad = _mahsulot(d, "dona", qty=10)
    r = client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": [{"product_id": str(p_ok), "counted": 7},
                  {"product_id": str(p_bad), "counted": 7.5}],
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="sanoq (ikki qator)")
    assert _qoldiq(p_ok, d["bids"][0]) == Decimal("10.000"), \
        "birinchi qator YOZILDI (qism-mutatsiya)"
    assert _qoldiq(p_bad, d["bids"][0]) == Decimal("10.000")


def test_sanoq_kasr_KG_OTADI(client):
    d = _dokon()
    pid = _mahsulot(d, "kg", qty=10)
    r = client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": [{"product_id": str(pid), "counted": 7.25}],
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("7.250")


# == 9) FILIALLARARO KO'CHIRISH (`POST /inventory/transfer`) =================
def test_kochirish_kasr_dona_RAD(client):
    d = _dokon(filiallar=2)
    pid = _mahsulot(d, "dona", qty=10, bid=d["bids"][0])
    r = client.post("/api/v1/inventory/transfer", headers=d["H"], json={
        "from_branch_id": str(d["bids"][0]), "to_branch_id": str(d["bids"][1]),
        "items": [{"product_id": str(pid), "qty": 1.5}],
        "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="ko'chirish")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")
    assert _qoldiq(pid, d["bids"][1]) == Decimal("0")


def test_kochirish_AGREGATSIYA_YUVISHI(client):
    """⚠️  BU YO'LDA YUVILISH JONLI EDI.

    `_transfer_once` (QA WH-004) ayni mahsulotning qatorlarini QO'SHADI:
    `0.5 + 0.5 = 1`. Validatsiya yig'indidan KEYIN bo'lsa, yaroqsiz so'rov
    yaroqli BUTUN ko'chirishga aylanardi va yarim dona hech qayerda
    ko'rinmasdi. Shu bois darvoza XOM `data.items` bo'yicha.
    """
    d = _dokon(filiallar=2)
    pid = _mahsulot(d, "dona", qty=10, bid=d["bids"][0])
    r = client.post("/api/v1/inventory/transfer", headers=d["H"], json={
        "from_branch_id": str(d["bids"][0]), "to_branch_id": str(d["bids"][1]),
        "items": [{"product_id": str(pid), "qty": 0.5},
                  {"product_id": str(pid), "qty": 0.5}],
        "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="ko'chirish agregatsiyasi")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")
    assert _qoldiq(pid, d["bids"][1]) == Decimal("0")


def test_kochirish_butun_OTADI(client):
    d = _dokon(filiallar=2)
    pid = _mahsulot(d, "dona", qty=10, bid=d["bids"][0])
    r = client.post("/api/v1/inventory/transfer", headers=d["H"], json={
        "from_branch_id": str(d["bids"][0]), "to_branch_id": str(d["bids"][1]),
        "items": [{"product_id": str(pid), "qty": 4}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("6.000")
    assert _qoldiq(pid, d["bids"][1]) == Decimal("4.000")


# == 10) MAHSULOT YARATISH (`POST /products/bulk`) ==========================
def test_mahsulot_yaratish_kasr_boshlangich_qoldiq_RAD(client):
    """Boshlang'ich qoldiq ham FIZIK miqdor (`Inventory` + `adjustment` harakati)."""
    d = _dokon()
    nom = "Bulk dona " + uuid.uuid4().hex[:6]
    r = client.post("/api/v1/products/bulk", headers=d["H"], json={"items": [
        {"name": nom, "unit_code": "dona", "buy_price": 50, "sell_price": 100,
         "stock": 2.5}]})
    _rad(r, nima="mahsulot yaratish")
    with _db() as db:
        assert db.query(Product).filter(Product.company_id == d["cid"],
                                        Product.name == nom).first() is None


def test_mahsulot_yaratish_IKKINCHI_qator_buzuq_BIRINCHISI_YARATILMAYDI(client):
    """⚠️  QISM-YARATISH YO'Q — darvoza loop'dan OLDIN, butun so'rov bo'yicha."""
    d = _dokon()
    n1 = "Bulk OK " + uuid.uuid4().hex[:6]
    n2 = "Bulk BAD " + uuid.uuid4().hex[:6]
    r = client.post("/api/v1/products/bulk", headers=d["H"], json={"items": [
        {"name": n1, "unit_code": "dona", "buy_price": 50, "sell_price": 100, "stock": 3},
        {"name": n2, "unit_code": "dona", "buy_price": 50, "sell_price": 100, "stock": 0.5}]})
    _rad(r, nima="mahsulot yaratish (ikki qator)")
    with _db() as db:
        qoldi = db.query(Product).filter(Product.company_id == d["cid"],
                                         Product.name.in_([n1, n2])).count()
    assert qoldi == 0, f"{qoldi} ta mahsulot JIMGINA yaratildi (qism-yozuv)"


def test_mahsulot_yaratish_KG_kasr_OTADI(client):
    d = _dokon()
    r = client.post("/api/v1/products/bulk", headers=d["H"], json={"items": [
        {"name": "Bulk kg " + uuid.uuid4().hex[:6], "unit_code": "kg",
         "buy_price": 50, "sell_price": 100, "stock": 2.5}]})
    assert r.status_code == 200, r.text


# == 11) BIRLIK ALMASHTIRISH (`PATCH /products/{id}`) =======================
def test_birlik_almashtirish_KASR_qoldiqda_RAD(client):
    """⚠️  RETROAKTIV BUZILISH. `kg` (3.5) -> `dona` bo'lsa qoldiq `3.5 dona`
        bo'lib qolardi va boshqa BARCHA darvozalar chetlab o'tilardi."""
    d = _dokon()
    pid = _mahsulot(d, "kg", qty=Decimal("3.5"))
    r = client.patch(f"/api/v1/products/{pid}", headers=d["H"],
                     json={"unit_code": "dona"})
    assert r.status_code == 400, r.text
    assert "bo'linmas birlikka" in r.json()["detail"], r.text
    with _db() as db:
        u = db.query(Unit).filter_by(code="kg").one()
        assert db.get(Product, pid).unit_id == u.id, "birlik ALMASHDI"


def test_birlik_almashtirish_BUTUN_qoldiqda_OTADI(client):
    d = _dokon()
    pid = _mahsulot(d, "kg", qty=Decimal("4"))
    r = client.patch(f"/api/v1/products/{pid}", headers=d["H"],
                     json={"unit_code": "dona"})
    assert r.status_code == 200, r.text
    with _db() as db:
        u = db.query(Unit).filter_by(code="dona").one()
        assert db.get(Product, pid).unit_id == u.id


def test_birlik_almashtirish_KASRLI_birlikka_OTADI(client):
    """`dona` -> `kg`: yangi birlik kasr ruxsat beradi, hech narsa tekshirilmaydi."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=Decimal("4"))
    r = client.patch(f"/api/v1/products/{pid}", headers=d["H"], json={"unit_code": "kg"})
    assert r.status_code == 200, r.text


# == 12) PARTIYA KUZATUVINI YOQISH (`POST /lots/enable`) ====================
def test_partiya_yoqish_AGREGATSIYA_YUVISHI(client):
    """⚠️  `lot_policy` faqat `SUM(opening_lots) == Inventory.qty` ni talab qiladi.

    Ya'ni butun qoldiq `2` ni `0.5 + 1.5` ga bo'lish YIG'INDI tekshiruvidan
    O'TARDI va bo'linmas birlikda yarim dona partiya tug'ilardi.
    """
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=2)
    r = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(pid), "branch_id": str(d["bids"][0]),
        "reason": "boshlang'ich partiyalar",
        "opening_lots": [{"qty": 0.5, "unit_cost": 50}, {"qty": 1.5, "unit_cost": 50}]})
    # Darvoza aktivatsiya/sxema darvozalaridan KEYIN turadi: 403/409 bo'lsa bu
    # muhit kuzatuvni umuman ochmaydi va darvozani o'lchab bo'lmaydi.
    if r.status_code in (403, 409):
        pytest.skip(f"kuzatuv bu muhitda ochilmaydi ({r.status_code}) — darvoza o'lchanmadi")
    _rad(r, nima="partiya yoqish")
    with _db() as db:
        assert db.get(Product, pid).track_lots is not True, \
            "RAD etilgan yoqish bayroqni qo'ydi"


# == 13) QABULNI TUZATISH (`POST /receiving/{id}/corrections`) ==============
def _kuzatuvli_kirim(client, d, *, qty=10):
    """Kuzatuvli `dona` mahsulot + partiyali qabul. -> (pid, rec, item, batch)."""
    pid = _mahsulot(d, "dona", qty=0)
    e = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(pid), "branch_id": str(d["bids"][0]),
        "reason": "kuzatuvni yoqish"})
    if e.status_code != 200:
        pytest.skip(f"kuzatuv ochilmadi ({e.status_code}): {e.text[:160]}")
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": qty, "unit_cost": 700, "unit": "dona",
                   "lots": [{"qty": qty, "batch_number": "A-1"}]}],
        "supplier_id": str(d["sup"]), "payment": "credit",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert r.status_code == 200, r.text
    det = client.get(f"/api/v1/purchases/{r.json()['purchase_id']}", headers=d["H"])
    assert det.status_code == 200, det.text
    it = det.json()["items"][0]
    return pid, r.json()["receiving_id"], it["id"], it["lots"][0]["id"]


def test_qabul_tuzatishi_kasr_TESKARI_RAD(client):
    """⚠️  `reverse[].qty` FIZIK miqdor — kogorta `remaining_qty` dan ayiriladi.

    So'rov tanasida `product_id` YO'Q: mahsulot `purchase_item_id` orqali
    yechiladi. Darvoza `lot_correction` chaqiruvidan OLDIN.
    """
    d = _dokon()
    pid, rec, item, batch = _kuzatuvli_kirim(client, d, qty=10)
    r = client.post(f"/api/v1/receiving/{rec}/corrections", headers=d["H"], json={
        "client_uuid": str(uuid.uuid4()), "reason": "nakladnoyda 10, aslida 9.5",
        "lines": [{"purchase_item_id": item,
                   "reverse": [{"stock_batch_id": batch, "qty": 0.5}]}]})
    _rad(r, nima="qabul tuzatishi (teskari)")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")


def test_qabul_tuzatishi_kasr_ORNIGA_QOYISH_RAD(client):
    """`replace[].qty` ham FIZIK miqdor — yangi kogorta yaratadi."""
    d = _dokon()
    pid, rec, item, batch = _kuzatuvli_kirim(client, d, qty=10)
    r = client.post(f"/api/v1/receiving/{rec}/corrections", headers=d["H"], json={
        "client_uuid": str(uuid.uuid4()), "reason": "partiya raqami xato edi",
        "lines": [{"purchase_item_id": item,
                   "reverse": [{"stock_batch_id": batch, "qty": 2}],
                   "replace": [{"qty": 1.5, "batch_number": "A-2", "unit_cost": 700}]}]})
    _rad(r, nima="qabul tuzatishi (o'rniga qo'yish)")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")


def test_qabul_tuzatishi_butun_DARVOZADAN_OTADI(client):
    """Darvoza yaroqli tuzatishni TO'SMAYDI (natija 200 yoki boshqa sabab, lekin
    BIRLIK xatosi EMAS)."""
    d = _dokon()
    pid, rec, item, batch = _kuzatuvli_kirim(client, d, qty=10)
    r = client.post(f"/api/v1/receiving/{rec}/corrections", headers=d["H"], json={
        "client_uuid": str(uuid.uuid4()), "reason": "nakladnoyda 10, aslida 9",
        "lines": [{"purchase_item_id": item,
                   "reverse": [{"stock_batch_id": batch, "qty": 1}]}]})
    assert KUTILGAN not in r.text, f"yaroqli tuzatish BIRLIK xatosi oldi: {r.text[:300]}"


# == 14) QARZNI YOPISH (`POST /lots/shortfalls/{id}/resolve`) ===============
def _qarz(d, pid, *, qty=Decimal("5")):
    """`lot_shortfalls` qatorini TO'G'RIDAN bazada ochadi.

    ⚠️  SAHNA ATAYLAB BAZADA. Qarz faqat kuzatuvli mahsulotni partiya qoplamagan
        holda sotganda tug'iladi — uni API orqali qurish bu testni DARVOZA
        o'rniga qarz tug'ilish mexanikasini o'lchaydigan qilib qo'yardi.
    """
    from app.models.inventory import LotShortfall
    with _db() as db:
        sf = LotShortfall(id=uuid.uuid4(), company_id=d["cid"], branch_id=d["bids"][0],
                          product_id=pid, qty=qty, resolved_qty=0, unit_cost=Decimal("50"),
                          resolved_cost=0, returned_qty=0, created_at=NOW)
        db.add(sf)
        db.commit()
        return sf.id


def test_qarz_yopish_kasr_dona_RAD(client):
    """Yopish `StockBatch.remaining_qty` ni kamaytiradi — FIZIK partiya miqdori."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=0)
    sf = _qarz(d, pid)
    r = client.post(f"/api/v1/lots/shortfalls/{sf}/resolve", headers=d["H"], json={
        "stock_batch_id": str(uuid.uuid4()), "qty": 0.5,
        "reason": "qarzni partiyaga bog'lash", "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="qarzni yopish")


def test_qarz_yopish_AGREGATSIYA_YUVISHI(client):
    """`allocations` yig'indisi butun bo'lsa ham HAR QATOR alohida tekshiriladi."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=0)
    sf = _qarz(d, pid)
    r = client.post(f"/api/v1/lots/shortfalls/{sf}/resolve", headers=d["H"], json={
        "allocations": [{"stock_batch_id": str(uuid.uuid4()), "qty": 0.5},
                        {"stock_batch_id": str(uuid.uuid4()), "qty": 1.5}],
        "reason": "qarzni partiyaga bog'lash", "client_uuid": str(uuid.uuid4())})
    _rad(r, nima="qarzni yopish (agregatsiya)")


def test_qarz_yopish_butun_DARVOZADAN_OTADI(client):
    """Butun miqdor darvozadan o'tadi (keyin boshqa sabab bilan rad etilishi
    mumkin — lekin BIRLIK xatosi EMAS)."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=0)
    sf = _qarz(d, pid)
    r = client.post(f"/api/v1/lots/shortfalls/{sf}/resolve", headers=d["H"], json={
        "stock_batch_id": str(uuid.uuid4()), "qty": 2,
        "reason": "qarzni partiyaga bog'lash", "client_uuid": str(uuid.uuid4())})
    assert KUTILGAN not in r.text, f"butun yopish BIRLIK xatosi oldi: {r.text[:300]}"


# == 15) FAIL-OPEN TESHIKLARI (ko'rikda topilgan, YOPILGAN) =================
#
# Bu blok darvozaning O'ZIDAGI ikki teshigini qadaydi. Ular «kasr miqdor
# o'tmaydi» degan umumiy sinovlar bilan KO'RINMASDI: yo'l 200 qaytarardi va
# mahsulot kasr `dona` bo'lib TUG'ILARDI.

@pytest.mark.parametrize("unit_qiymati, nima", [
    ("DONA", "KATTA HARF — darvoza kodni topmasdi, yozuvchi esa .lower() bilan topardi"),
    ("Dona", "aralash harf — AYNI mexanizm"),
    (None, "BERILMAGAN (`unit: str | None = None`) — zaxira birlik `dona` bo'lardi"),
    ("", "bo'sh satr — AYNI zaxira"),
    ("shtuka", "NOMA'LUM kod — AYNI zaxira"),
])
def test_kirim_YANGI_mahsulot_birlik_YORLIGI_bilan_CHETLAB_OTILMAYDI(client, unit_qiymati, nima):
    """⚠️  Darvoza KLIENT yorlig'ini emas, YECHILGAN `unit_id` ni o'lchaydi.

    Yozuvchi yangi mahsulot birligini
    `unit_by_code.get((i.unit or "").strip().lower()) or default_unit_id`
    bilan yechadi. Darvoza xom satrni o'lchaganda bu ikki ifoda AJRALARDI:
    yorliq darvozada topilmasa tekshiruv o'tkazib yuborilardi, mahsulot esa
    baribir `dona` bo'lib yaratilardi. Endi ikki joy AYNI ifodani ishlatadi.
    """
    d = _dokon()
    nom = "Teshik " + uuid.uuid4().hex[:6]
    item = {"new_name": nom, "qty": 0.5, "unit_cost": 100, "new_sell_price": 150}
    if unit_qiymati is not None:
        item["unit"] = unit_qiymati
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [item], "supplier_id": str(d["sup"]), "payment": "cash",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    _rad(r, nima=f"kirim ({nima})")
    with _db() as db:
        qoldi = db.query(Product).filter(Product.company_id == d["cid"],
                                         Product.name == nom).first()
    assert qoldi is None, "RAD etilgan kirim kasr `dona` mahsulot yaratdi"


@pytest.mark.parametrize("unit_qiymati", ["kg", "KG", "Litr"])
def test_kirim_YANGI_mahsulot_KASRLI_birlik_HARQANDAY_harfda_OTADI(client, unit_qiymati):
    """Nazorat tomoni: yechim `.lower()` qilgani uchun `KG` ham kasrli birlik."""
    d = _dokon()
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"new_name": "Kasrli " + uuid.uuid4().hex[:6], "qty": 0.5,
                   "unit_cost": 100, "unit": unit_qiymati, "new_sell_price": 150}],
        "supplier_id": str(d["sup"]), "payment": "cash",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert r.status_code == 200, r.text


def test_partiya_yoqish_LEGACY_shoxi_KASR_qoldiqda_RAD(client):
    """⚠️  `opening_lots` BERILMAGAN shox — darvoza bu yerda NO-OP edi.

    `open_legacy_lot(qty=have)` joriy qoldiqni AYNAN O'ZGARMAS kogortaga
    muhrlaydi. Eski ma'lumotda qoldiq kasr bo'lsa (`3.5 dona`), yoqish — qaytarib
    BO'LMAYDIGAN amal — buzuq boshlang'ich holatni abadiy yozib qo'yardi.
    """
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=Decimal("3.5"))       # ESKI ma'lumot: kasr `dona`
    r = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(pid), "branch_id": str(d["bids"][0]),
        "reason": "meros qoldiqni muhrlash", "legacy_unit_cost": 50})
    if r.status_code in (403, 409):
        pytest.skip(f"kuzatuv bu muhitda ochilmaydi ({r.status_code})")
    assert r.status_code == 400, r.text
    assert KUTILGAN in r.json()["detail"], r.text
    assert "JORIY qoldig'i kasr" in r.json()["detail"], r.text
    with _db() as db:
        assert db.get(Product, pid).track_lots is not True, \
            "RAD etilgan yoqish bayroqni qo'ydi"


def test_partiya_yoqish_LEGACY_shoxi_BUTUN_qoldiqda_OTADI(client):
    """Nazorat: qoldiq butun bo'lsa meros shoxi AVVALGIDEK ishlaydi."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=4)
    r = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(pid), "branch_id": str(d["bids"][0]),
        "reason": "meros qoldiqni muhrlash", "legacy_unit_cost": 50})
    if r.status_code in (403, 409):
        pytest.skip(f"kuzatuv bu muhitda ochilmaydi ({r.status_code})")
    assert r.status_code == 200, r.text


def test_partiya_yoqish_KASR_qoldiq_lekin_KASRLI_birlik_OTADI(client):
    """`kg` da `3.5` YARAMLI — darvoza faqat bo'linmas birlikka tegadi."""
    d = _dokon()
    pid = _mahsulot(d, "kg", qty=Decimal("3.5"))
    r = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(pid), "branch_id": str(d["bids"][0]),
        "reason": "meros qoldiqni muhrlash", "legacy_unit_cost": 50})
    if r.status_code in (403, 409):
        pytest.skip(f"kuzatuv bu muhitda ochilmaydi ({r.status_code})")
    assert r.status_code == 200, r.text


# == 16) MEROS MA'LUMOTNI TUZATISH YO'LI YOPILMASIN ========================
def _meros_kasr_qator(client, d):
    """Xarid hujjati + qatori, keyin qator miqdori BAZADA kasrga aylantiriladi.

    ⚠️  ATAYLAB TO'G'RIDAN BAZADA: endi bunday qatorni API orqali yaratib
        bo'lmaydi (aynan shuning uchun darvoza bor). Bu MEROS holatini
        modellashtirish, darvozani chetlab o'tish emas.
    """
    pid = _mahsulot(d, "dona", qty=0)
    r = client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "received",
        "items": [{"product_id": str(pid), "qty": 5, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    pur = r.json()["id"]
    it_id = client.get(f"/api/v1/purchases/{pur}", headers=d["H"]).json()["items"][0]["id"]
    from app.models.purchasing import PurchaseItem
    with _db() as db:
        it = db.get(PurchaseItem, uuid.UUID(it_id))
        it.qty = Decimal("0.500")
        it.line_total = Decimal("350.00")
        db.commit()
    return pur, it_id


def test_xarid_tahriri_FAQAT_NARXNI_tuzatish_MEROS_kasr_qatorda_OTADI(client):
    """⚠️  O'ZGARMAGAN miqdorda darvoza YONMASLIGI SHART.

    Eski ma'lumotda `0.5 dona` qatori bo'lsa, uning NARXINI tuzatish so'rovi
    YANGI yaroqsiz miqdor YOZMAYDI — mavjudini saqlaydi. Darvoza `upd.qty` ni
    shartsiz o'lchasa, meros ma'lumotni tuzatishning bu yo'li ham yopilardi.
    """
    d = _dokon()
    pur, it_id = _meros_kasr_qator(client, d)
    e = client.patch(f"/api/v1/purchases/{pur}", headers=d["H"], json={
        "items": [{"id": it_id, "qty": 0.5, "unit_cost": 800}],
        "client_uuid": str(uuid.uuid4())})
    assert KUTILGAN not in e.text, f"narx tuzatishi BIRLIK xatosi oldi: {e.text[:300]}"


def test_xarid_tahriri_MEROS_qatorni_YANA_kasrga_ozgartirish_RAD(client):
    """Nazorat: miqdor O'ZGARSA (kasrdan boshqa kasrga ham) darvoza YONADI."""
    d = _dokon()
    pur, it_id = _meros_kasr_qator(client, d)
    e = client.patch(f"/api/v1/purchases/{pur}", headers=d["H"], json={
        "items": [{"id": it_id, "qty": 0.75, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    _rad(e, nima="xarid tahriri (kasr -> boshqa kasr)")


# == 17) MAVJUD INVARIANTLAR BUZILMAGAN (regressiya nazorati) ===============
def test_qty_qoldiqdan_KATTA_hamon_RAD_lekin_BOSHQA_sabab(client):
    """⚠️  Darvoza mavjud «qoldiq yetarli emas» tekshiruvini ALMASHTIRMAYDI.

    Ikki rad etish MUSTAQIL: biri birlik butunligi, boshqasi qoldiq chegarasi.
    Agar darvoza xato joyga qo'yilgan bo'lsa (masalan qoldiq tekshiruvidan
    KEYIN), bu test ko'rsatardi: BUTUN lekin ortiqcha miqdor BIRLIK xatosini
    olardi va operator «kasr miqdor» degan ma'nosiz maslahatni ko'rardi.
    """
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=3)
    r = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 5, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 500, "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 400, r.text
    assert KUTILGAN not in r.text, f"qoldiq xatosi BIRLIK xatosi bo'lib keldi: {r.text[:200]}"
    assert _qoldiq(pid, d["bids"][0]) == Decimal("3.000")


def test_RAD_etilgan_sotuvdan_keyin_AYNI_client_uuid_HAMON_BO_SH(client):
    """⚠️  IDEMPOTENTLIK KALITI YONMAYDI.

    Darvoza hech narsa yozmasligi kerak — `Sale` qatori ham, idempotentlik izi
    ham. Aks holda klient tuzatilgan miqdor bilan QAYTA yuborganda server
    «bu allaqachon bor» deb YOLG'ON muvaffaqiyat qaytarardi (yoki 409 berardi)
    va savdo YO'QOLARDI.
    """
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    cu = str(uuid.uuid4())
    r1 = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 0.5, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100, "client_uuid": cu})
    _rad(r1, nima="sotuv (birinchi urinish)")
    # AYNI kalit bilan TUZATILGAN miqdor — o'tishi SHART
    r2 = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 1, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100, "client_uuid": cu})
    assert r2.status_code == 200, r2.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("9.000")
    from app.models.sales import Sale
    with _db() as db:
        n = db.query(Sale).filter(Sale.company_id == d["cid"]).count()
    assert n == 1, f"{n} ta sotuv qatori (RAD etilgan urinish ham yozilgan)"


def test_sync_push_RAD_etilgandan_keyin_TUZATILGAN_qayta_yuborish_OTADI(client):
    """Offline zanjir: dead-letter -> operator tuzatadi -> AYNI kalit bilan qayta."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    cu = str(uuid.uuid4())
    r1 = client.post("/api/v1/sync/push", headers=d["H"], json={"sales": [{
        "client_uuid": cu,
        "items": [{"product_id": str(pid), "qty": 0.5, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100}]})
    assert r1.json()["results"][0].get("retry") is False, r1.text
    r2 = client.post("/api/v1/sync/push", headers=d["H"], json={"sales": [{
        "client_uuid": cu,
        "items": [{"product_id": str(pid), "qty": 2, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 200}]})
    res = r2.json()["results"][0]
    assert res.get("ok") is True, r2.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("8.000")


def test_sync_push_YAROQLI_sotuv_IKKI_marta_IDEMPOTENT(client):
    """Darvoza mavjud idempotentlikni buzmaganini qadaydi (AYNI kalit, AYNI savat)."""
    d = _dokon()
    pid = _mahsulot(d, "dona", qty=10)
    cu, savat = str(uuid.uuid4()), [{"product_id": str(pid), "qty": 2, "unit_price": 100}]
    body = {"sales": [{"client_uuid": cu, "items": savat,
                       "payment_method": "cash", "given_amount": 200}]}
    a1 = client.post("/api/v1/sync/push", headers=d["H"], json=body)
    a2 = client.post("/api/v1/sync/push", headers=d["H"], json=body)
    assert a1.json()["results"][0]["ok"] is True, a1.text
    assert a2.json()["results"][0]["ok"] is True, a2.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("8.000"), "ikki marta kamaydi"
