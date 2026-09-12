# -*- coding: utf-8 -*-
"""PHASE 2 — FEFO SOTUVI + XAVFSIZ FAOLLASHUV.

Har qoida uchun MANFIY nazorat bor (qarang: scratchpad/negctl2.py) — qoida
olib tashlansa mos test QIZIL bo'lishi shart.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.inventory import (Inventory, SaleItemLotAllocation, StockBatch,
                                  StockMovement)
from app.models.sales import Sale, SaleItem
from app.services import lot_fefo as LF
from app.services import lot_policy as LP
from app.services import stock_invariant as SI

NOW = datetime.now(timezone.utc)
D10 = (NOW + timedelta(days=10)).date()
D20 = (NOW + timedelta(days=20)).date()
D30 = (NOW + timedelta(days=30)).date()
PAST = (NOW - timedelta(days=1)).date()


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


@pytest.fixture()
def ctx(client):
    """(company_id, branch_id) — AYNAN xodim yozadigan filial.

    ⚠️  `Branch...first()` ISHLATILMAYDI: u ORDER BY siz nodeterministik va
        to'plamdagi boshqa fayl ikkinchi filial yaratsa (test_lot_receiving.py
        aynan shunday qiladi) bu fixture SOTUV YOZMAYDIGAN filialni qaytarardi —
        natijada sinovlar mahsulotni emas, fayllar tartibini o'lchardi.
        `actor_branch()` — API ning O'ZI ishlatadigan yechim.
    """
    from app.core.deps import actor_branch
    from app.models.auth import Employee
    from app.models.org import Company
    with _db() as db:
        c = db.query(Company).first()
        emp = (db.query(Employee)
               .filter(Employee.company_id == c.id, Employee.deleted_at.is_(None))
               .order_by(Employee.created_at).first())
        b = actor_branch(emp, db)
        yield c.id, b.id


@pytest.fixture()
def sup(client, admin_headers):
    r = client.get("/api/v1/suppliers", headers=admin_headers).json()
    if r:
        return r[0]["id"]
    return client.post("/api/v1/suppliers", headers=admin_headers,
                       json={"name": "FEFO ta'minotchi"}).json()["id"]


def _product(client, admin_headers, buy=55):
    r = client.post("/api/v1/products/bulk", headers=admin_headers, json={"items": [
        {"name": f"FEFO {uuid.uuid4().hex[:8]}", "sell_price": 100, "buy_price": buy,
         "unit_code": "dona", "stock": 0}]})
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def _enable(client, admin_headers, pid, expiry=True, **kw):
    if expiry:
        client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})
    body = {"product_id": pid, "reason": "phase2 sinov", "track_expiry": expiry, **kw}
    return client.post("/api/v1/lots/enable", headers=admin_headers, json=body)


def _recv(client, admin_headers, sup, pid, qty, cost, expiry=None, batch=None):
    lot = {"qty": qty, "unit_cost": cost}
    if expiry:
        lot["expiry_date"] = expiry.isoformat()
    if batch:
        lot["batch_number"] = batch
    return client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": qty, "unit_cost": cost, "unit": "dona",
                   "lots": [lot]}],
        "supplier_id": sup, "payment": "credit",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})


def _recv_plain(client, admin_headers, sup, pid, qty, cost):
    """KUZATUVSIZ mahsulot kirimi — `lots` YUBORILMAYDI (yuborilsa 400, va bu to'g'ri)."""
    return client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": qty, "unit_cost": cost, "unit": "dona"}],
        "supplier_id": sup, "payment": "credit",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})


def _set_stock(pid, bid, qty):
    """Mavjud qoldiq qatorini YANGILAYDI — `/products/bulk` uni allaqachon yaratgan."""
    with _db() as db:
        i = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(pid),
                                       Inventory.branch_id == bid).first()
        if i is None:
            i = Inventory(product_id=uuid.UUID(pid), branch_id=bid, qty=Decimal("0"),
                          min_qty=0, updated_at=NOW)
            db.add(i)
        i.qty = Decimal(str(qty))
        db.commit()


def _sell(client, admin_headers, pid, qty, price=100, cu=None):
    return client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": qty, "unit_price": price}],
        "payment_method": "cash", "given_amount": price * qty + 10000,
        "client_uuid": str(cu or uuid.uuid4())})


def _replay(client, admin_headers, pid, qty, price=100, cu=None, sold_at=None):
    """Offline qayta yuborish — `/sync/push`. Server uchun AVTORITET replay signali."""
    rec = {"client_uuid": str(cu or uuid.uuid4()), "payment_method": "cash",
           "items": [{"product_id": pid, "qty": qty, "unit_price": price}],
           "given_amount": price * qty + 10000}
    if sold_at:
        rec["sold_at"] = sold_at.isoformat()
    return client.post("/api/v1/sync/push", headers=admin_headers, json={"sales": [rec]})


def _allocs(pid):
    with _db() as db:
        return (db.query(SaleItemLotAllocation)
                .filter(SaleItemLotAllocation.product_id == uuid.UUID(pid))
                .order_by(SaleItemLotAllocation.created_at).all())


def _lots(pid):
    with _db() as db:
        return (db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid))
                .order_by(StockBatch.expiry_date.asc().nullslast()).all())


def _inv(pid, bid):
    with _db() as db:
        r = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(pid),
                                       Inventory.branch_id == bid).first()
        return Decimal(str(r.qty)) if r else Decimal("0")


# ══ 1. FEFO TANLOVI ═════════════════════════════════════════════════════════

def test_ENG_YAQIN_muddat_BIRINCHI_ketadi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 55, D20)     # KEYINROQ muddat, OLDIN kelgan
    _recv(client, admin_headers, sup, pid, 10, 57, D10)     # YAQINROQ muddat, KEYIN kelgan
    assert _sell(client, admin_headers, pid, 5).status_code == 200
    a = _allocs(pid)
    assert len(a) == 1
    assert a[0].expiry_date == D10, "kirish tartibi muddatdan ustun keldi — FEFO emas"


def test_sotuv_IKKI_partiyani_qamraydi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 100, 55, D10)
    _recv(client, admin_headers, sup, pid, 60, 57, D20)
    assert _sell(client, admin_headers, pid, 120).status_code == 200
    a = _allocs(pid)
    assert [(Decimal(str(x.qty)), Decimal(str(x.unit_cost))) for x in
            sorted(a, key=lambda z: z.expiry_date)] == [
        (Decimal("100.000"), Decimal("55.00")), (Decimal("20.000"), Decimal("57.00"))]
    lots = {l.expiry_date: l for l in _lots(pid)}
    assert Decimal(str(lots[D10].remaining_qty)) == 0
    assert lots[D10].status == SI.DEPLETED
    assert Decimal(str(lots[D20].remaining_qty)) == Decimal("40.000")
    assert _inv(pid, bid) == Decimal("40.000")


def test_sotuv_UCH_partiyani_qamraydi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    for q, c, e in ((5, 50, D10), (5, 60, D20), (5, 70, D30)):
        _recv(client, admin_headers, sup, pid, q, c, e)
    assert _sell(client, admin_headers, pid, 12).status_code == 200
    a = sorted(_allocs(pid), key=lambda z: z.expiry_date)
    assert [Decimal(str(x.qty)) for x in a] == [Decimal("5.000"), Decimal("5.000"),
                                                Decimal("2.000")]


def test_TENG_muddatda_tartib_DETERMINISTIK(client, admin_headers, ctx, sup):
    """Teng muddat -> received_at -> created_at -> id. Tasodif BO'LMASIN."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 10, D10, batch="BIRINCHI")
    _recv(client, admin_headers, sup, pid, 5, 20, D10, batch="IKKINCHI")
    assert _sell(client, admin_headers, pid, 5).status_code == 200
    a = _allocs(pid)
    assert len(a) == 1
    with _db() as db:
        b = db.get(StockBatch, a[0].stock_batch_id)
    assert b.batch_no == "BIRINCHI", "teng muddatda kirish tartibi buzildi"


def test_MUDDATI_BUGUN_tugaydigan_tovar_SOTILADI(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    with _db() as db:
        biz = LP.business_date(db, bid)
    _recv(client, admin_headers, sup, pid, 5, 55, biz)
    assert _sell(client, admin_headers, pid, 5).status_code == 200


def test_MUDDATI_OTGAN_partiya_sotuvga_KIRMAYDI(client, admin_headers, ctx, sup):
    """Lekin QOLDIQDAN chiqmaydi — tovar javonda turibdi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 55, D10)
    with _db() as db:      # muddatni ORQAGA suramiz
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.expiry_date = PAST
        db.commit()
    r = _sell(client, admin_headers, pid, 1)
    assert r.status_code == 409, r.text
    assert "partiya" in r.text.lower()
    assert _inv(pid, bid) == Decimal("10.000"), "muddati o'tgan tovar qoldiqdan YO'QOLDI"


def test_FAQAT_muddati_otgan_bolsa_MANOLI_xato(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 55, D10)
    with _db() as db:
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.expiry_date = PAST
        db.commit()
    r = _sell(client, admin_headers, pid, 1)
    assert r.status_code == 409
    assert "inventarizatsiya" in r.text.lower()


def test_NULL_muddat_OXIRIDA_ketadi(client, admin_headers, ctx, sup):
    """Noma'lum muddatli (legacy) tovar ma'lum yaroqlidan OLDIN sotilmasin."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _set_stock(pid, bid, 10)      # mavjud qoldiq -> legacy partiya (muddat NULL)
    assert _enable(client, admin_headers, pid, legacy_unit_cost=50).status_code == 200
    _recv(client, admin_headers, sup, pid, 10, 55, D30)     # ma'lum muddat
    assert _sell(client, admin_headers, pid, 5).status_code == 200
    a = _allocs(pid)
    assert len(a) == 1
    assert a[0].expiry_date == D30, "NULL muddatli partiya ma'lum muddatlidan OLDIN ketdi"


def test_track_expiry_FALSE_da_tartib_FIFO(client, admin_headers, ctx, sup):
    """Muddat yo'q -> saralash `received_at` ga tushadi. Bu FEFO emas, FIFO."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 5, 10, None, batch="ESKI")
    _recv(client, admin_headers, sup, pid, 5, 20, None, batch="YANGI")
    assert _sell(client, admin_headers, pid, 5).status_code == 200
    with _db() as db:
        from app.models.catalog import Product
        p = db.get(Product, uuid.UUID(pid))
        assert LF.ordering_mode(p) == LF.MODE_FIFO
        b = db.get(StockBatch, _allocs(pid)[0].stock_batch_id)
    assert b.batch_no == "ESKI"


# ══ 2. TANNARX ══════════════════════════════════════════════════════════════

def test_BITTA_partiyada_tannarx_AYNAN_partiyaniki(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers, buy=999)     # base_buy_price ATAYIN boshqa
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 55, D10)
    assert _sell(client, admin_headers, pid, 4).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
    assert Decimal(str(si.unit_cost)) == Decimal("55.00"), "base_buy_price ishlatildi"


def test_OGIRLANGAN_tannarx_ANIQ(client, admin_headers, ctx, sup):
    """(100×55 + 20×57)/120 = 6640/120 = 55.3333 -> 55.33"""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 100, 55, D10)
    _recv(client, admin_headers, sup, pid, 60, 57, D20)
    assert _sell(client, admin_headers, pid, 120).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
    assert Decimal(str(si.unit_cost)) == Decimal("55.33")


def test_ANIQ_COGS_yaxlitlashda_YOQOLMAYDI(client, admin_headers, ctx, sup):
    """100×55 + 20×57 = 6640.00 AYNAN. Yaxlitlangan o'rtacha 0.40 yo'qotardi.

    ⚠️  Bu test Phase 2 da `Sale.cost_total == SUM(qty × unit_cost)` deb yozilgan
        edi va o'shanda 6639.60 ni tasdiqlar edi — ya'ni XATONI muzlatib
        qo'ygandi. Buxgalteriya haqiqati ulushlar yig'indisi: `unit_cost`
        yaxlitlangan o'rtacha bo'lgani uchun undan qayta ko'paytirish
        TIYINLARNI YO'QOTADI. Endi `SaleItem.cost_total` aniq qiymatni saqlaydi
        va `Sale.cost_total` ANIQ shularning yig'indisi.
    """
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 100, 55, D10)
    _recv(client, admin_headers, sup, pid, 60, 57, D20)
    r = _sell(client, admin_headers, pid, 120)
    assert r.status_code == 200
    with _db() as db:
        sale = db.get(Sale, uuid.UUID(r.json()["id"]))
        items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
        allocs = db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.sale_item_id == items[0].id).all()
    # 1) Qator COGS'i ulushlardan AYNAN kelib chiqadi.
    exact = sum((Decimal(str(a.qty)) * Decimal(str(a.unit_cost)) for a in allocs),
                Decimal("0"))
    assert exact == Decimal("6640.00"), exact
    assert Decimal(str(items[0].cost_total)) == Decimal("6640.00")
    # 2) Chek COGS'i = qatorlar yig'indisi (hisobotlar zid bo'lmasin).
    assert Decimal(str(sale.cost_total)) == sum(
        (Decimal(str(i.cost_total)) for i in items), Decimal("0"))
    # 3) Eski (yaxlitlangan) formula HAQIQATAN farq qiladi — test bo'sh emas.
    rounded = sum((Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in items),
                  Decimal("0"))
    assert rounded == Decimal("6639.60"), rounded
    assert Decimal(str(sale.cost_total)) != rounded


def test_KUZATUVSIZ_sotuvda_ham_cost_total_yoziladi(client, admin_headers, ctx, sup):
    """Ortga moslik: kuzatuvsiz qatorda ham aniq qiymat bo'lsin (qty × narx)."""
    pid = _product(client, admin_headers, buy=55)
    assert _recv_plain(client, admin_headers, sup, pid, 10, 55).status_code == 200
    r = _sell(client, admin_headers, pid, 4)
    assert r.status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        sale = db.get(Sale, si.sale_id)
    assert Decimal(str(si.cost_total)) == Decimal("220.00")
    assert Decimal(str(sale.cost_total)) == Decimal("220.00")


def test_keyingi_narx_TARIXNI_ozgartirmaydi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 55, D10)
    assert _sell(client, admin_headers, pid, 5).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        before = Decimal(str(si.unit_cost))
        a = db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.product_id == uuid.UUID(pid)).first()
        a_before = Decimal(str(a.unit_cost))
        from app.models.catalog import Product
        db.get(Product, uuid.UUID(pid)).base_buy_price = 5000
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.unit_cost = Decimal("9999")
        db.commit()
    with _db() as db:
        si2 = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        a2 = db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.product_id == uuid.UUID(pid)).first()
    assert Decimal(str(si2.unit_cost)) == before
    assert Decimal(str(a2.unit_cost)) == a_before


# ══ 3. HARAKAT VA INVARIANT ═════════════════════════════════════════════════

def test_KOP_partiyada_ham_BITTA_agregat_harakat(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    _recv(client, admin_headers, sup, pid, 5, 60, D20)
    assert _sell(client, admin_headers, pid, 8).status_code == 200
    with _db() as db:
        mv = db.query(StockMovement).filter(
            StockMovement.product_id == uuid.UUID(pid),
            StockMovement.ref_type == "sale").all()
    assert len(mv) == 1, f"{len(mv)} ta sale_out — agregat buzilgan"
    assert Decimal(str(mv[0].qty)) == Decimal("-8.000")


def test_ulushlar_YIGINDISI_SaleItem_qty_ga_TENG(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 7, 50, D10)
    _recv(client, admin_headers, sup, pid, 7, 60, D20)
    assert _sell(client, admin_headers, pid, 11).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        tot = sum((Decimal(str(a.qty)) for a in db.query(SaleItemLotAllocation)
                   .filter(SaleItemLotAllocation.sale_item_id == si.id).all()), Decimal("0"))
    assert tot == Decimal(str(si.qty))


def test_sotuvdan_KEYIN_invariant_saqlanadi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 9, 50, D10)
    assert _sell(client, admin_headers, pid, 4).status_code == 200
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


def test_partiya_MANFIYGA_tushmaydi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = _sell(client, admin_headers, pid, 9)      # qoldiqdan ko'p
    assert r.status_code == 400, r.text           # oddiy qoldiq gvardi tutadi
    assert all(Decimal(str(l.remaining_qty)) >= 0 for l in _lots(pid))


def test_ONLAYN_sotuv_KAMOMAD_partiyasi_YARATMAYDI(client, admin_headers, ctx, sup):
    """Onlayn fail-closed — va bu AYNAN kamomad yo'li emasligi isbotlanadi.

    ⚠️  Ssenariy ATAYLAB invarianti BUTUN: qoldiq 10, partiya 10, lekin hammasi
        muddati o'tgan. Shu bois 409 ni FAQAT «yaroqli partiya yo'q» qoidasi
        berishi mumkin — invariant darvozasi emas. Manfiy nazorat aynan shuni
        talab qildi: avvalgi ssenariyda invariant OLDINDAN buzilgan edi va ikkala
        darvoza ham 409 berardi, ya'ni test qaysi biri ishlaganini ajratmasdi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 55, D10)
    with _db() as db:
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.expiry_date = PAST
        db.commit()
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok, "ssenariy invarianti butun emas"
    r = _sell(client, admin_headers, pid, 5)
    assert r.status_code == 409, r.text
    assert "yaroqli partiya" in r.text, r.text
    from app.models.inventory import LotShortfall as _LS0
    with _db() as db:
        assert db.query(_LS0).filter(_LS0.product_id == uuid.UUID(pid)).count() == 0,         "ONLAYN sotuv kamomad partiyasi yaratdi — bu faqat replay yo'li"
    assert _inv(pid, bid) == Decimal("10.000")


def test_qoldiq_YETARLI_partiya_YETMASA_FAIL_CLOSED(client, admin_headers, ctx, sup):
    """Ma'lumot nomuvofiqligi: `Inventory` 10 deydi, yaroqli partiya 7.

    Jimgina 10 sotib -3 partiya yasash kamomadni KO'RINMAS qilardi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 7, 50, D10)
    with _db() as db:          # qoldiqni ATAYIN ko'paytiramiz (nomuvofiqlik)
        i = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(pid),
                                       Inventory.branch_id == bid).first()
        i.qty = Decimal("10")
        db.commit()
    r = _sell(client, admin_headers, pid, 10)
    assert r.status_code == 409, r.text
    assert _inv(pid, bid) == Decimal("10"), "rad etilgan sotuv qoldiqni o'zgartirdi"
    assert sum(Decimal(str(l.remaining_qty)) for l in _lots(pid)) == Decimal("7.000")


# ══ 4. OFFLINE QAYTA YUBORISH — PUL OLINGAN CHEK YO'QOLMAYDI ════════════════

def test_REPLAY_partiya_yetmasa_ham_CHEK_YOZILADI(client, admin_headers, ctx, sup):
    """ENG MUHIM TEST: pul olingan offline chek HECH QACHON rad etilmaydi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 50, D10)
    r = _replay(client, admin_headers, pid, 10)       # partiya 3, chek 10
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["ok"] is True, res
    with _db() as db:
        assert db.query(Sale).filter(Sale.client_uuid == uuid.UUID(res["client_uuid"])).first()


def test_REPLAY_kamomadi_QARZ_jadvaliga_yoziladi(client, admin_headers, ctx, sup):
    """Phase 2.5: qarz `lot_shortfalls` da. Jismoniy partiya MANFIY BO'LMAYDI.

    ⚠️  Phase 2 da bu test manfiy `stock_batches` qatorini talab qilardi.
        `StockBatch` — JISMONIY qabul kogortasi, manfiy miqdor esa javondagi
        tovar emas; uni o'sha jadvalda saqlash muddat/inventarizatsiya/ko'chirish
        o'quvchilarini yolg'on javobga olib borardi.
    """
    from app.models.inventory import LotShortfall
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 50, D10)
    assert _replay(client, admin_headers, pid, 10).json()["results"][0]["ok"] is True
    # JISMONIY partiyalar hech qachon manfiy emas
    assert all(Decimal(str(l.remaining_qty)) >= 0 for l in _lots(pid)),         [str(l.remaining_qty) for l in _lots(pid)]
    with _db() as db:
        rows = db.query(LotShortfall).filter(
            LotShortfall.product_id == uuid.UUID(pid)).all()
    assert len(rows) == 1, "qarz qatori yaratilmadi"
    assert Decimal(str(rows[0].qty)) == Decimal("7.000")
    assert rows[0].sale_item_id is not None, "qarz chek qatoriga bog'lanmagan"
    assert _inv(pid, bid) == Decimal("-7.000")


def test_REPLAY_dan_KEYIN_ham_invariant_AYNAN_saqlanadi(client, admin_headers, ctx, sup):
    """Kamomad partiyasining butun MA'NOSI shu: invariant buzilmasin."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 50, D10)
    _replay(client, admin_headers, pid, 10)
    with _db() as db:
        rep = SI.check(db, cid, [uuid.UUID(pid)])
        assert rep.ok, [str(m) for m in rep.mismatches]


def test_kamomad_partiyasi_FEFO_MANBAI_EMAS(client, admin_headers, ctx, sup):
    """Manfiy partiya keyingi sotuvda manba bo'lib qolmasin."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 50, D10)
    _replay(client, admin_headers, pid, 10)                    # kamomad -7
    _recv(client, admin_headers, sup, pid, 20, 50, D20)        # yangi tovar keldi
    r = _sell(client, admin_headers, pid, 5)
    assert r.status_code == 200, r.text
    # FAQAT SHU sotuvning ulushlari — avvalgi replay kamomadi tabiiy ravishda bor.
    with _db() as db:
        si = db.query(SaleItem).filter(
            SaleItem.sale_id == uuid.UUID(r.json()["id"])).first()
        for a in db.query(SaleItemLotAllocation).filter(
                SaleItemLotAllocation.sale_item_id == si.id).all():
            b = db.get(StockBatch, a.stock_batch_id)
            assert b.source_type != "shortfall",                 "kamomad partiyasidan MANBA sifatida yechildi"


def test_JISMONIY_partiya_HECH_QACHON_manfiy_emas(client, admin_headers, ctx, sup):
    """To'g'ridan-to'g'ri `candidates()` ustida — saralash tartibiga tayanmasdan.

    ⚠️  Ilgari bu qoida faqat bilvosita sinalardi: kamomad partiyasining muddati
        NULL bo'lgani uchun u saralashda oxirida turardi va sotuv unga umuman
        yetib bormasdi. Ya'ni filtr olib tashlansa ham test YASHIL qolardi —
        manfiy nazorat shuni ko'rsatdi. Endi filtr O'ZI tekshiriladi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 50, D10)
    _replay(client, admin_headers, pid, 10)          # 7 dona qarz tug'iladi
    assert all(Decimal(str(l.remaining_qty)) >= 0 for l in _lots(pid))
    with _db() as db:
        biz = LP.business_date(db, bid)
        cands = LF.candidates(db, company_id=cid, branch_id=bid,
                              product_id=uuid.UUID(pid), biz_date=biz)
        assert all(Decimal(str(c.remaining_qty)) > 0 for c in cands),             f"musbat bo'lmagan partiya nomzod bo'ldi: {[c.remaining_qty for c in cands]}"
        assert all(c.source_type != "shortfall" for c in cands)


def test_AYNI_chek_takrori_YANGI_qarz_YARATMAYDI(client, admin_headers, ctx, sup):
    """Idempotentlik SOTUV darajasida: ayni `client_uuid` -> bitta qarz qatori.

    ⚠️  Phase 2 da qoida «mahsulotga BITTA kamomad partiyasi» edi, chunki qarz
        agregat manfiy partiyada yashardi. Endi qarz CHEK QATORIGA bog'langan —
        ikki HAR XIL chek ikki qarz qatori beradi va bu TO'G'RI (izlanish
        aniqroq). Saqlanishi kerak bo'lgan haqiqiy qoida — AYNI chek takrori
        yangi qator yaratmasligi.
    """
    from app.models.inventory import LotShortfall
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    cu = uuid.uuid4()
    assert _replay(client, admin_headers, pid, 4, cu=cu).json()["results"][0]["ok"] is True
    assert _replay(client, admin_headers, pid, 4, cu=cu).json()["results"][0]["ok"] is True
    with _db() as db:
        n = db.query(LotShortfall).filter(
            LotShortfall.product_id == uuid.UUID(pid)).count()
    assert n == 1, f"{n} ta qarz qatori — takror yangi qarz yaratdi"


def test_HAR_XIL_chek_HAR_BIRI_uchun_qarz(client, admin_headers, ctx, sup):
    """Ikki har xil offline chek -> ikki qarz qatori, har biri o'z chekiga bog'langan."""
    from app.models.inventory import LotShortfall
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    # Zaxira 1 dona. 1-chek 3 ta -> 1 taqsimlandi, 2 QARZ. Partiya endi 0.
    # 2-chek 2 ta -> 0 taqsimlandi, 2 QARZ. Ya'ni [2, 2].
    _replay(client, admin_headers, pid, 3)
    _replay(client, admin_headers, pid, 2)
    with _db() as db:
        rows = db.query(LotShortfall).filter(
            LotShortfall.product_id == uuid.UUID(pid)).all()
    assert len(rows) == 2
    assert all(r.sale_item_id is not None for r in rows)
    assert sorted(Decimal(str(r.qty)) for r in rows) == [Decimal("2.000"), Decimal("2.000")]
    assert _inv(pid, bid) == Decimal("-4.000")


def test_kamomad_AUDITGA_yoziladi(client, admin_headers, ctx, sup):
    """`is_offline` bayrog'i hech qayerda o'qilmaydi — kamomad AUDITDA ko'rinsin."""
    from app.models.sync import AuditLog
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 50, D10)
    _replay(client, admin_headers, pid, 5)
    with _db() as db:
        a = db.query(AuditLog).filter(AuditLog.entity == "sale_lot_shortfall").all()
    assert a, "kamomad auditsiz o'tdi"
    assert a[-1].after["offline_replay"] is True


def test_REPLAY_yetarli_partiya_bolsa_ODDIY_FEFO(client, admin_headers, ctx, sup):
    """Qayta yuborish kamomad YO'LINI majburlamaydi — yetsa oddiy taqsimot."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 10, 50, D10)
    assert _replay(client, admin_headers, pid, 4).json()["results"][0]["ok"] is True
    from app.models.inventory import LotShortfall as _LS0
    with _db() as db:
        assert db.query(_LS0).filter(_LS0.product_id == uuid.UUID(pid)).count() == 0


def test_notanish_mahsulot_DOIMIY_rad_CHEKSIZ_urinish_EMAS(client, admin_headers):
    """`retry=True` bo'lsa outbox abadiy qayta urardi (409 tranzient deb biladi)."""
    r = _replay(client, admin_headers, str(uuid.uuid4()), 1)
    res = r.json()["results"][0]
    assert res["ok"] is False
    assert res.get("retry") is False, "doimiy xato TRANZIENT deb belgilandi"


# ══ 5. IDEMPOTENTLIK ════════════════════════════════════════════════════════

def test_AYNI_chek_qayta_yuborilsa_ULUSH_qayta_hisoblanmaydi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 20, 50, D10)
    cu = uuid.uuid4()
    assert _replay(client, admin_headers, pid, 5, cu=cu).json()["results"][0]["ok"] is True
    inv1, al1 = _inv(pid, bid), len(_allocs(pid))
    assert _replay(client, admin_headers, pid, 5, cu=cu).json()["results"][0]["ok"] is True
    assert _inv(pid, bid) == inv1, "takror qoldiqni YANA kamaytirdi"
    assert len(_allocs(pid)) == al1, "takror YANGI ulush yaratdi"
    with _db() as db:
        assert db.query(StockMovement).filter(
            StockMovement.product_id == uuid.UUID(pid),
            StockMovement.ref_type == "sale").count() == 1
        assert db.query(Sale).filter(Sale.client_uuid == cu).count() == 1


def test_onlayn_takror_ham_BITTA_sotuv(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 20, 50, D10)
    cu = uuid.uuid4()
    r1 = _sell(client, admin_headers, pid, 5, cu=cu)
    r2 = _sell(client, admin_headers, pid, 5, cu=cu)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert len(_allocs(pid)) == 1


# ══ 6. FAOLLASHUV ═══════════════════════════════════════════════════════════

def test_PRODUCTION_da_kuzatuv_YOQILMAYDI(client, admin_headers, monkeypatch):
    """«Hech kim bosmaydi» YETARLI EMAS — darvoza kodda."""
    monkeypatch.setenv("APP_ENV", "production")
    pid = _product(client, admin_headers)
    r = _enable(client, admin_headers, pid, expiry=False)
    assert r.status_code == 403, r.text


def test_muhit_NOMALUM_bolsa_ham_YOQILMAYDI(client, admin_headers, monkeypatch):
    """Fail-closed: belgi yo'qligi ruxsat BERMAYDI (production'da APP_ENV yo'q)."""
    monkeypatch.delenv("APP_ENV", raising=False)
    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=False).status_code == 403


def test_platforma_belgisi_APP_ENV_dan_USTUN(client, admin_headers, monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=False).status_code == 403


def test_faollashuv_VAQTI_ochilish_bilan_AYNI_tranzaksiyada(client, admin_headers, ctx):
    from app.models.catalog import Product
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _set_stock(pid, bid, 5)
    assert _enable(client, admin_headers, pid, expiry=False,
                   legacy_unit_cost=40).status_code == 200
    with _db() as db:
        p = db.get(Product, uuid.UUID(pid))
        lot = db.query(StockBatch).filter(StockBatch.product_id == p.id).first()
    assert p.lots_activated_at is not None
    assert lot is not None
    assert abs((p.lots_activated_at - lot.received_at).total_seconds()) < 1.0


def test_faollashuv_vaqti_MIJOZGA_berilmaydi(client, admin_headers, ctx):
    """Mijoz aks-sado qiladigan belgi hujumchi yozadigan son bo'lardi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    body = client.get(f"/api/v1/lots/products/{pid}", headers=admin_headers).text
    assert "lots_activated_at" not in body
    cat = client.get("/api/v1/products", headers=admin_headers).text
    assert "lots_activated_at" not in cat


def test_kuzatuvni_OCHIRISH_yoli_YOQ():
    """Tarix yo'qolmasin: `track_lots=False` yozadigan kod BO'LMASLIGI shart."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    bad = []
    pat = re.compile(r"track_lots\s*=\s*(False|None|0)\b")
    for f in root.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if pat.search(line) and "default=" not in line and "server_default" not in line:
                bad.append(f"{f.relative_to(root).as_posix()}:{n}")
    assert not bad, f"kuzatuvni o'chiradigan kod bor: {bad}"


# ══ 7. ESKI (KUZATUVSIZ) XULQ O'ZGARMAGAN ═══════════════════════════════════

def test_KUZATUVSIZ_sotuv_ULUSH_yaratmaydi(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    assert _recv_plain(client, admin_headers, sup, pid, 10, 55).status_code == 200
    assert _sell(client, admin_headers, pid, 4).status_code == 200
    assert _allocs(pid) == []
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
    assert Decimal(str(si.unit_cost)) == Decimal("55.00")   # base_buy_price — eski xulq
    assert _inv(pid, bid) == Decimal("6.000")


def test_KUZATUVSIZ_qoldiq_gvardi_ozgarmagan(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    assert _recv_plain(client, admin_headers, sup, pid, 2, 55).status_code == 200
    r = _sell(client, admin_headers, pid, 5)
    assert r.status_code == 400
    assert "Yetarli qoldiq yo'q" in r.text


def test_KUZATUVSIZ_replay_manfiy_qoldiqqa_ruxsat_beradi(client, admin_headers, ctx, sup):
    """Eski qoida: pul olingan offline chek yoziladi, qoldiq manfiyga tushadi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    assert _recv_plain(client, admin_headers, sup, pid, 1, 55).status_code == 200
    assert _replay(client, admin_headers, pid, 4).json()["results"][0]["ok"] is True
    assert _inv(pid, bid) == Decimal("-3.000")
    assert _allocs(pid) == []


# ══ 8. MAJBURIY SXEMA ═══════════════════════════════════════════════════════

def test_PHASE2_ish_vaqti_obyektlari_MAJBURIY():
    from app.core import required_schema as rs
    names = {f"{t}.{c}" for t, c in rs.REQUIRED_COLUMNS}
    assert "products.lots_activated_at" in names
    for c in ("company_id", "sale_item_id", "stock_batch_id", "product_id",
              "qty", "unit_cost", "expiry_date"):
        assert f"sale_item_lot_allocations.{c}" in names, c
    assert ("ux_alloc_item_lot", "sale_item_lot_allocations") in rs.REQUIRED_INDEXES


def test_MAJBURIY_obyektni_migratsiya_TUZATA_olsin():
    """Phase 1 darsi: tuzatish qadami yo'q majburiy obyekt = abadiy boot-loop."""
    from app.core import required_schema as rs
    from app.initdb import _ADDED_COLUMNS
    added = {(t, c) for t, c, _ in _ADDED_COLUMNS}
    yoq = [p for p in rs.REQUIRED_COLUMNS if p not in added]
    assert not yoq, f"migratsiya qo'sha olmaydigan majburiy ustunlar: {yoq}"


def test_RESET_grafida_ulushlar_BOR():
    from app.services import catalog_reset as CR
    for plan in (CR.BLOCKERS, CR.DELETE_PLAN, CR.COUNT_PLAN, CR.DIGEST_PLAN):
        assert "sale_item_lot_allocations" in [n for n, _ in plan]
    d = [n for n, _ in CR.DELETE_PLAN]
    assert d.index("sale_item_lot_allocations") < d.index("stock_batches")


def test_PHASE25_ish_vaqti_obyektlari_MAJBURIY():
    """Sotuv ish vaqti tayanadigan Phase 2.5 obyektlari majburiy bo'lsin."""
    from app.core import required_schema as rs
    names = {f"{a}.{b}" for a, b in rs.REQUIRED_COLUMNS}
    for c in ("sale_items.cost_total", "sale_items.cost_unresolved",
              "doc_counters.company_id", "doc_counters.kind", "doc_counters.next_value",
              "lot_shortfalls.company_id", "lot_shortfalls.branch_id",
              "lot_shortfalls.product_id", "lot_shortfalls.qty",
              "lot_shortfalls.resolved_qty"):
        assert c in names, f"{c} majburiy emas"
    assert ("ux_doc_counter", "doc_counters") in rs.REQUIRED_INDEXES
    # Tezlik indeksi ATAYLAB majburiy EMAS (boot-loop xavfi).
    assert "ix_lot_shortfall_open" not in {i for i, _ in rs.REQUIRED_INDEXES}
