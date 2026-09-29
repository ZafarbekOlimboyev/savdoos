# -*- coding: utf-8 -*-
"""MUSTAQIL QA REPRODUKSIYA — P9 snapshot 482b3f38 (qa/binos-independent-security auditi).

Har bir sinov INVARIANTNI tasdiqlaydi. Nuqsonli kodda sinov QIZIL bo'lishi kutiladi —
bu nuqsonning kuzatiladigan isboti. Tuzatishdan keyin YASHIL bo'lishi shart.

⚠️  SQLite yetarli bo'lgan holatlargina: bular MANTIQ nuqsonlari (dedup doirasi,
    idempotentlik kaliti, smena bog'lash qoidasi) — PG tranzaksiya poygalariga bog'liq
    topilmalar alohida (PENDING, PG bo'shaganda).
"""
import uuid
from datetime import timedelta

from tests.test_mobile_parity import _db, _product, _shop, _staff


def _open_shift(client, H):
    r = client.post("/api/v1/shifts/open", headers=H, json={"opening_cash": 0})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _close_shift(client, H, sid):
    r = client.post(f"/api/v1/shifts/{sid}/close", headers=H, json={"counted_cash": 0})
    assert r.status_code == 200, r.text

PUSH = "/api/v1/sync/push"
SALES = "/api/v1/sales"
TRANSFER = "/api/v1/inventory/transfer"


def _sales_of(cid):
    from app.models.sales import Sale
    with _db() as db:
        return db.query(Sale).filter(Sale.company_id == cid).all()


def _inv_qty(pid, bid):
    from app.models.inventory import Inventory
    with _db() as db:
        row = db.query(Inventory).filter(
            Inventory.product_id == pid, Inventory.branch_id == bid).first()
        return float(row.qty) if row else None


# ══ BINOS-QA-P9-01 · /sync/push client_uuid'siz chekda idempotentlik YO'Q ══════════════
# Invariant: bitta ofline chek — javob yo'qolib retry bo'lsa ham — bazaga BIR marta tushadi
# (yoki server client_uuid'siz chekni RAD etadi). Nuqson: ikkala push ham ok:true,
# ikkita sotuv, stok ikki marta kamayadi (dublikat buxgalteriya + stok korruptsiyasi).

def test_qa01_push_without_client_uuid_duplicates_on_retry(client):
    d = _shop()
    H, _kid = _staff(d, "kassir", filiallar=(d["bids"][0],))
    p = _product(d, qty=10)
    rec = {"payment_method": "cash", "given_amount": 100,
           "items": [{"product_id": str(p["id"]), "qty": 1, "unit_price": 100}]}
    r1 = client.post(PUSH, headers=H, json={"sales": [rec]})
    assert r1.status_code == 200, r1.text
    ok1 = r1.json()["results"][0]
    # Xuddi shu chekni qayta yuborish — klient javobni olmagan (tarmoq uzildi) stsenariysi.
    r2 = client.post(PUSH, headers=H, json={"sales": [rec]})
    assert r2.status_code == 200, r2.text
    ok2 = r2.json()["results"][0]

    sales = _sales_of(d["cid"])
    # INVARIANT: yoki bitta sotuv, yoki ikkinchisi rad etilgan bo'lishi kerak.
    assert len(sales) == 1 or ok2["ok"] is False, (
        f"DUBLIKAT: ikkala push ham qabul qilindi (ok1={ok1}, ok2={ok2}), "
        f"sotuvlar={len(sales)}, stok={_inv_qty(p['id'], d['bids'][0])} (kutilgan 9.0)")


# ══ BINOS-QA-P9-02 · soxta sold_at YOPILGAN (rekonsilatsiya qilingan) smenaga kiradi ═══
# Invariant: smena yopilib expected_cash muzlatilgach, unga yangi savdo JIMGINA
# biriktirilmaydi (LATE_SYNC belgisisiz). Nuqson: kassa.sell tokeni sold_at'ni yopiq
# smena oynasiga qo'yib push qilsa, savdo o'sha yopiq smenaga yoziladi — Z-hisobot
# muzlatilgan, naqd esa o'zgargan (60 kungача orqaga).

def test_qa02_forged_sold_at_binds_into_closed_shift(client):
    from app.models.shifts import Shift
    d = _shop()
    H, kid = _staff(d, "kassir", filiallar=(d["bids"][0],))
    p = _product(d, qty=5)
    sid = _open_shift(client, H)
    _close_shift(client, H, sid)
    with _db() as db:
        sh = db.get(Shift, uuid.UUID(sid))
        opened_at, closed_at, frozen_expected = sh.opened_at, sh.closed_at, sh.expected_cash
    assert closed_at is not None

    cu = uuid.uuid4()
    sold_at = opened_at + (closed_at - opened_at) / 2  # yopiq smena oynasining o'rtasi
    rec = {"client_uuid": str(cu), "payment_method": "cash", "given_amount": 100,
           "sold_at": sold_at.isoformat(),
           "items": [{"product_id": str(p["id"]), "qty": 1, "unit_price": 100}]}
    r = client.post(PUSH, headers=H, json={"sales": [rec]})
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]

    from app.models.sales import Sale
    with _db() as db:
        sale = db.query(Sale).filter(Sale.client_uuid == cu).first()
        sh2 = db.get(Shift, uuid.UUID(sid))
    if res["ok"]:
        assert sale is not None
        # INVARIANT: yopiq smenaga jim biriktirish taqiqlanadi.
        assert str(sale.shift_id) != sid, (
            f"YOPIQ SMENAGA YOZILDI: sale.shift_id={sale.shift_id} == yopiq smena {sid}; "
            f"muzlatilgan expected_cash={frozen_expected} o'zgarmadi (hozir {sh2.expected_cash}), "
            f"lekin smenada endi 100 naqd savdo bor — rekonsilatsiya orqadan buzildi")


# ══ BINOS-QA-P9-03 · boshqa kassirning client_uuid'i bilan replay — savdo YUTILADI ═════
# Invariant: B-kassirning YANGI (boshqa mahsulot/summa) cheki A-kassirning client_uuid'iga
# to'qnashsa, B cheki yo yoziladi, yo ANIQ rad etiladi. Nuqson: dedup faqat
# (company, client_uuid) — B ga 200 OK bilan A'ning sotuvi qaytadi: B pul olgan,
# serverda esa B savdosi YO'Q (yashirin yo'qolgan savdo) va B A'ning chekini ko'radi.

def test_qa03_cross_cashier_uuid_replay_swallows_new_sale(client):
    d = _shop()
    HA, _a = _staff(d, "kassir", filiallar=(d["bids"][0],))
    HB, _b = _staff(d, "kassir", filiallar=(d["bids"][0],))
    p1 = _product(d, qty=10)
    p2 = _product(d, qty=10)
    x = str(uuid.uuid4())

    rA = client.post(SALES, headers=HA, json={
        "client_uuid": x, "payment_method": "cash", "given_amount": 100,
        "items": [{"product_id": str(p1["id"]), "qty": 1, "unit_price": 100}]})
    assert rA.status_code == 200, rA.text

    rB = client.post(SALES, headers=HB, json={
        "client_uuid": x, "payment_method": "cash", "given_amount": 600,
        "items": [{"product_id": str(p2["id"]), "qty": 3, "unit_price": 200}]})

    if rB.status_code == 200:
        # INVARIANT: 200 bo'lsa — bu B'ning O'Z savdosi bo'lishi kerak.
        assert rB.json()["id"] != rA.json()["id"], (
            f"YUTILDI: B-kassir 200 OK bilan A'ning sotuvini oldi (id={rA.json()['id']}); "
            f"B'ning 600 so'mlik cheki bazaga tushmadi, stok p2={_inv_qty(p2['id'], d['bids'][0])} "
            "(kutilgan 7.0)")


# ══ BINOS-QA-P9-04 · transfer dedup'i tenant-skopsiz va material-matchsiz ══════════════
# Invariant: idempotentlik kaliti kompaniya doirasida bo'lishi shart. Nuqson:
# _transfer_once dedup'i StockMovement'ni FAQAT (client_uuid, type) bo'yicha qidiradi —
# B-kompaniya A-kompaniyaning client_uuid'iga to'qnashsa, B'ning HAQIQIY ko'chirishi
# jimgina {"ok":true,"duplicate":true} bilan yutiladi: stok siljimaydi, klient esa
# muvaffaqiyat deb biladi (yo'qolgan inventar harakati, tenantlararo ta'sir).

def test_qa04_transfer_dedup_not_tenant_scoped(client):
    dA = _shop(filiallar=2)
    dB = _shop(filiallar=2)
    pA = _product(dA, qty=10, bid=dA["bids"][0])
    pB = _product(dB, qty=10, bid=dB["bids"][0])
    x = str(uuid.uuid4())

    rA = client.post(TRANSFER, headers=dA["H"], json={
        "client_uuid": x, "from_branch_id": str(dA["bids"][0]), "to_branch_id": str(dA["bids"][1]),
        "items": [{"product_id": str(pA["id"]), "qty": 2}]})
    assert rA.status_code == 200, rA.text
    assert not rA.json().get("duplicate")

    rB = client.post(TRANSFER, headers=dB["H"], json={
        "client_uuid": x, "from_branch_id": str(dB["bids"][0]), "to_branch_id": str(dB["bids"][1]),
        "items": [{"product_id": str(pB["id"]), "qty": 5}]})
    assert rB.status_code == 200, rB.text

    moved_out = _inv_qty(pB["id"], dB["bids"][0])
    moved_in = _inv_qty(pB["id"], dB["bids"][1])
    # INVARIANT: B'ning ko'chirishi BAJARILGAN bo'lishi kerak (5 dona siljigan).
    assert not rB.json().get("duplicate") and moved_out == 5.0 and moved_in == 5.0, (
        f"YUTILDI: B-kompaniya javobi={rB.json()}, stok from={moved_out} to={moved_in} "
        "(kutilgan 5.0/5.0) — begona tenantning client_uuid'i B'ning ko'chirishini bekor qildi")
