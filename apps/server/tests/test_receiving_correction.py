# -*- coding: utf-8 -*-
"""PHASE 5D — QABULNI TUZATISH (teskari yozuv + o'rniga qo'yish).

Har sinov ANIQ bitta nuqsonni ushlab turadi — «xususiyat ishlayaptimi» degan
umumiy savolni emas. Ushlanadigan nuqsonlar sinflari:

  1. JIMGINA TAHRIR — partiya atributini (narx/muddat/raqam) joyida qayta yozish.
     `StockBatch.received_qty` butun repoda qayta yozilmaydi va
     `stock_invariant._lot_sums` faqat `remaining_qty` ni yig'adi, ya'ni bunday
     tahrir xavfsizlik to'riga UMUMAN ko'rinmaydi. Tegilgan kogorta esa
     `sale_item_lot_allocations.unit_cost` da MUZLATILGAN — uni tuzatish
     tarixiy COGS'ni yolg'on qilardi.
  2. IKKI MARTA QO'LLASH — takror so'rov qoldiqni, yetkazib beruvchi qarzini va
     kassani ikki marta siljitishi.
  3. «BAJARILDI» DEB YOLG'ON AYTISH — kassa yoki invariant yozilmaganda ham
     operatorga muvaffaqiyat ko'rsatish.
  4. JIMGINA TESKARI QILISH — eski `PATCH /purchases/{id}` yo'li hujjat jamini
     qatorlardan QAYTA hisoblab, tuzatishni bekor qilishi.
  5. TAXMIN — qaysi kogorta, qancha va qanday narxda ekanini tizim o'zi
     o'ylab topishi (bo'sh tanlov, partiyasiz tannarx, taqsimlanmagan farq).

⚠️  SQLite'da kassa quyi tizimi (cash schema) YO'Q: `retrofit` hook'lari
    himoyalangan no-op. Shu bois `LOT_CORRECTION_CASH_UNPOSTABLE` bu yerda
    TABIIY yo'l bilan chiqmaydi va u darvozaning O'ZI sinaladi (hook faol
    bo'lsa-yu, oyoq yozilmasa — rad etish). Poyga sinovlari (ikki seans,
    ikki marta bekor qilish) Postgres faylida.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core import error_codes as EC
from app.models.inventory import StockBatch, StockMovement
from app.services import lot_correction as LC
from app.services import lot_receiving as LR
from app.services import stock_invariant as SI

# Fixtures bitta joyda turadi — nusxa ko'paytirmaymiz (`ctx` AYNAN xodim
# yozadigan filialni beradi; `Branch...first()` nodeterministik bo'lardi).
from tests.test_lot_receiving import (  # noqa: F401
    _db,
    _enable,
    _inv_qty,
    _lots,
    _new_product,
    ctx,
)

NOW = datetime.now(timezone.utc)
FUTURE = (NOW + timedelta(days=120)).date()
PAST = (NOW - timedelta(days=1)).date()

REASON = "nakladnoyda 100 yozilgan, aslida 90 kelgan"


# ══ YORDAMCHILAR ════════════════════════════════════════════════════════════

@pytest.fixture()
def sup(client, admin_headers):
    r = client.get("/api/v1/suppliers", headers=admin_headers).json()
    if r:
        return r[0]["id"]
    return client.post("/api/v1/suppliers", headers=admin_headers,
                       json={"name": "Tuzatish ta'minotchisi"}).json()["id"]


def _commit(client, admin_headers, items, *, supplier=None, payment="credit", cu=None):
    return client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": items, "supplier_id": supplier, "payment": payment,
        "client_uuid": str(cu or uuid.uuid4()), "source": "manual"})


def _line(pid, qty, cost, lots, unit="dona"):
    return {"product_id": pid, "qty": qty, "unit_cost": cost, "unit": unit, "lots": lots}


def _doc(client, admin_headers, supplier, *, qty=100, cost=700, batch="A-1",
         payment="credit", expiry=None, track_expiry=False, pid=None):
    """Kuzatuvli mahsulot + BITTA qatorli qabul. Qaytaradi: to'liq hujjat konteksti."""
    if pid is None:
        pid = _new_product(client, admin_headers)
        assert _enable(client, admin_headers, pid,
                       track_expiry=track_expiry).status_code == 200
    lot = {"qty": qty, "batch_number": batch}
    if expiry is not None:
        lot["expiry_date"] = expiry.isoformat()
    r = _commit(client, admin_headers, [_line(pid, qty, cost, [lot])],
                supplier=supplier, payment=payment)
    assert r.status_code == 200, r.text
    rec_id, pur_id = r.json()["receiving_id"], r.json()["purchase_id"]
    det = client.get(f"/api/v1/purchases/{pur_id}", headers=admin_headers)
    assert det.status_code == 200, det.text
    it = det.json()["items"][0]
    return {"pid": pid, "rec": rec_id, "pur": pur_id, "item": it["id"],
            "lots": it["lots"], "detail": det.json()}


def _batch_id(doc, i=0):
    return doc["lots"][i]["id"]


def _correct(client, headers, rec_id, lines, *, reason=REASON, cu=None,
             cash_account_id=None):
    body = {"client_uuid": str(cu or uuid.uuid4()), "reason": reason, "lines": lines}
    if cash_account_id is not None:
        body["cash_account_id"] = cash_account_id
    return client.post(f"/api/v1/receiving/{rec_id}/corrections", headers=headers,
                       json=body)


def _rev(item_id, batch_id, qty):
    return {"purchase_item_id": item_id,
            "reverse": [{"stock_batch_id": batch_id, "qty": qty}]}


def _code(r):
    return r.headers.get(EC.HEADER)


def _pur(client, admin_headers, pur_id):
    return client.get(f"/api/v1/purchases/{pur_id}", headers=admin_headers)


def _batch(bid):
    with _db() as db:
        return db.get(StockBatch, uuid.UUID(str(bid)))


def _corrections(pur_id):
    from app.models.receiving import ReceivingCorrection
    with _db() as db:
        return (db.query(ReceivingCorrection)
                .filter(ReceivingCorrection.purchase_id == uuid.UUID(str(pur_id)))
                .all())


def _ok(cid, pid):
    """Qoldiq ≡ partiyalar − qarz. Har amaldan KEYIN tekshiriladi."""
    with _db() as db:
        rep = SI.check(db, cid, [uuid.UUID(str(pid))])
        assert rep.ok, rep.mismatches


def _sup_row(sup_id):
    from app.models.purchasing import Supplier
    with _db() as db:
        return db.get(Supplier, uuid.UUID(str(sup_id)))


def _ledger(sup_id):
    from app.models.purchasing import SupplierLedger
    with _db() as db:
        return (db.query(SupplierLedger)
                .filter(SupplierLedger.supplier_id == uuid.UUID(str(sup_id)))
                .order_by(SupplierLedger.created_at).all())


def _movements(pid):
    with _db() as db:
        return (db.query(StockMovement)
                .filter(StockMovement.product_id == uuid.UUID(str(pid)))
                .order_by(StockMovement.created_at).all())


# ⚠️  ROL BO'YICHA BITTA XODIM, SESSIYA BO'YI. Demo do'kon tarifi 10 foydalanuvchi
#     bilan cheklangan va sinov bazasi HAMMA fayl uchun umumiy: har sinovda yangi
#     xodim yaratilsa limit tugab, BOSHQA fayllardagi sinovlar 403 bilan yiqilardi
#     (`test_lot_permissions.py` da aynan shu yuz bergan).
_CACHE: dict = {}


def _staff(client, admin_headers, role):
    if role in _CACHE:
        return {k: v for k, v in _CACHE[role].items() if not k.startswith("__")}
    phone = "+99890" + str(uuid.uuid4().int % 10_000_000).zfill(7)
    pw = "Toshkent-Kuz-2026"
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": f"5D {role}", "phone": phone, "password": pw, "role_code": role})
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
    r = client.post("/api/v1/auth/login/password",
                    json={"phone": "+998901234567", "password": "demo1234"})
    if r.status_code != 200:
        return
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for v in _CACHE.values():
        with contextlib.suppress(Exception):
            client.delete(f"/api/v1/employees/{v['__id']}", headers=h)
    _CACHE.clear()


# ══ 1. RUXSAT — DARVOZA HAR NARSADAN OLDIN ══════════════════════════════════

def test_RUXSATSIZ_xodim_tuzata_olmaydi(client, admin_headers, ctx, sup):
    """Kassir va menejerda `xaridlar.edit` YO'Q — 403 hujjat qidiruvidan OLDIN.

    ⚠️  MAVJUD BO'LMAGAN qabul id'si bilan so'raladi: agar ruxsat darvozasi
        qidiruvdan KEYIN tursa javob 404 bo'lardi va begona xodim hujjat
        MAVJUDLIGINI o'lchab olardi (IDOR).
    """
    yoq = str(uuid.uuid4())
    for role in ("kassir", "menejer"):
        h = _staff(client, admin_headers, role)
        r = _correct(client, h, yoq, [_rev(str(uuid.uuid4()), str(uuid.uuid4()), 1)])
        assert r.status_code == 403, (role, r.status_code, r.text)
        assert "xaridlar.edit" in r.json()["detail"], r.text


def test_OMBORCHI_tuzata_oladi(client, admin_headers, ctx, sup):
    """`xaridlar.edit` bor rol — amal HAQIQATAN o'tadi (403 universal emas)."""
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=20, cost=500)
    h = _staff(client, admin_headers, "omborchi")
    r = _correct(client, h, d["rec"], [_rev(d["item"], _batch_id(d), 5)])
    assert r.status_code == 200, r.text
    assert r.json()["reversed_total"] == 2500.0, r.text
    assert _inv_qty(d["pid"], bid) == Decimal("15.000")
    _ok(cid, d["pid"])


# ══ 2. HUJJAT TOPILISHI ═════════════════════════════════════════════════════

def test_BEGONA_qabul_404_va_403_EMAS(client, admin_headers, sup):
    """Boshqa (yoki mavjud bo'lmagan) qabul — 404, hech qachon 403.

    403 hujjat MAVJUDLIGINI oshkor qilardi; `/receiving/{id}` bilan AYNI qoida.
    """
    r = _correct(client, admin_headers, str(uuid.uuid4()),
                 [_rev(str(uuid.uuid4()), str(uuid.uuid4()), 1)])
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Qabul topilmadi"


def test_PARTIYASIZ_qabul_tuzatish_oqimiga_KIRMAYDI(client, admin_headers, sup):
    """Kuzatuvsiz qabulda tuzatiladigan kogorta YO'Q — operator eski yo'lga yo'naltiriladi.

    Aks holda tuzatish qoldiqni partiyasiz siljitib, «partiya oqimi» niqobida
    oddiy tahrirga aylanardi.
    """
    pid = _new_product(client, admin_headers)          # kuzatuv YOQILMAYDI
    r = _commit(client, admin_headers,
                [{"product_id": pid, "qty": 10, "unit_cost": 700, "unit": "dona"}],
                supplier=sup)
    assert r.status_code == 200, r.text
    det = _pur(client, admin_headers, r.json()["purchase_id"]).json()
    c = _correct(client, admin_headers, r.json()["receiving_id"],
                 [_rev(det["items"][0]["id"], str(uuid.uuid4()), 1)])
    assert c.status_code == 409, c.text
    assert _code(c) == EC.LOT_CORRECTION_NOT_TRACKED, c.headers
    assert c.json()["detail"] == (
        "Bu qabul partiya yaratmagan — tuzatish oqimi faqat partiyali qabul "
        "uchun. Hujjatni oddiy kirim tahriri bilan o'zgartiring.")
    # O'qish yo'li ham AYNI sababni aytadi — operator tugmani bosmasdan biladi.
    assert det["correctable"] is False
    assert det["correction_blocked_reason"] == (
        "Bu qabul partiya yaratmagan — tuzatish oqimi faqat partiyali qabul uchun.")


def test_OCHIRILGAN_filialda_tuzatib_bolmaydi(client, admin_headers, ctx, sup):
    """Filial o'chirilgan bo'lsa qoldiq umuman bo'lmagan joyda o'zgarardi.

    `edit_purchase` bilan IZCHIL: u ham 400 bilan to'xtaydi.
    """
    from app.models.org import Branch
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=300)
    with _db() as db:
        db.get(Branch, bid).deleted_at = datetime.now(timezone.utc)
        db.commit()
    try:
        r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 1)])
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "Xarid filiali o'chirilgan — tuzatib bo'lmaydi"
        blocked = _pur(client, admin_headers, d["pur"]).json()
        assert blocked["correctable"] is False
        assert blocked["correction_blocked_reason"] == (
            "Xarid filiali o'chirilgan — tuzatib bo'lmaydi.")
    finally:
        with _db() as db:
            db.get(Branch, bid).deleted_at = None
            db.commit()
    assert _inv_qty(d["pid"], bid) == Decimal("10.000"), "rad etilgan tuzatish qoldiqni surdi"


# ══ 3. PARTIYA TANLOVI ══════════════════════════════════════════════════════

def test_BOSHQA_qabulning_partiyasi_RAD_etiladi(client, admin_headers, ctx, sup):
    """`lot_writeoff.validate` faqat mahsulot/filialni biladi.

    ⚠️  Bu darvoza bo'lmasa BOSHQA hujjatning kogortasi shu yerdan JIMGINA
        kamayib ketardi: mahsulot ham, filial ham mos keladi.
    """
    cid, bid = ctx
    a = _doc(client, admin_headers, sup, qty=10, cost=700, batch="A-1")
    b = _doc(client, admin_headers, sup, qty=10, cost=700, batch="B-1", pid=a["pid"])
    yot = _batch_id(b)
    r = _correct(client, admin_headers, a["rec"], [_rev(a["item"], yot, 1)])
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == f"Partiya bu qabulga tegishli emas: {yot}"
    assert Decimal(str(_batch(yot).remaining_qty)) == Decimal("10.000")
    _ok(cid, a["pid"])


def test_QOLDIQDAN_ORTIQ_teskari_qilib_bolmaydi(client, admin_headers, ctx, sup):
    """Jismoniy partiya MANFIYGA tushmaydi — barqaror kod bilan 409."""
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=700)
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 11)])
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_EXCEEDS_REMAINING, r.headers
    assert "MANFIYGA tushmaydi" in r.json()["detail"], r.text
    assert "10.000" in r.json()["detail"] and "11.000" in r.json()["detail"], r.text
    assert _inv_qty(d["pid"], bid) == Decimal("10.000")
    _ok(cid, d["pid"])


def test_NOMAVJUD_partiya_400_va_KODSIZ(client, admin_headers, ctx, sup):
    """Shakl xatosi — 400 va barqaror kod YO'Q (kod faqat HOLAT ziddiyatiga).

    ⚠️  Tasnif MATNDAN emas, HOLATDAN chiqadi: `lot_writeoff` xabari bir harf
        o'zgarsa «qoldiq chegarasi» bilan «topilmadi» jimgina almashib qolardi.
    """
    d = _doc(client, admin_headers, sup, qty=10, cost=700)
    yoq = str(uuid.uuid4())
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], yoq, 1)])
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == f"Partiya topilmadi: {yoq}"
    assert _code(r) is None, r.headers


def test_BOSHQA_MAHSULOT_partiyasi_AYNI_qabulda_ham_RAD_etiladi(client, admin_headers,
                                                                ctx, sup):
    """Ikki qatorli qabul: A qatorida B mahsulotining kogortasi ko'rsatilgan."""
    cid, bid = ctx
    p1 = _new_product(client, admin_headers)
    p2 = _new_product(client, admin_headers)
    for p in (p1, p2):
        assert _enable(client, admin_headers, p).status_code == 200
    r = _commit(client, admin_headers,
                [_line(p1, 10, 700, [{"qty": 10, "batch_number": "P1"}]),
                 _line(p2, 5, 500, [{"qty": 5, "batch_number": "P2"}])], supplier=sup)
    assert r.status_code == 200, r.text
    det = _pur(client, admin_headers, r.json()["purchase_id"]).json()
    it1 = [x for x in det["items"] if x["product_id"] == p1][0]
    it2 = [x for x in det["items"] if x["product_id"] == p2][0]
    c = _correct(client, admin_headers, r.json()["receiving_id"],
                 [_rev(it1["id"], it2["lots"][0]["id"], 1)])
    assert c.status_code == 400, c.text
    assert "boshqa mahsulot yoki filialga tegishli" in c.json()["detail"], c.text
    _ok(cid, p1)
    _ok(cid, p2)


# ══ 4. TEGILGANLIK — IDENTIFIKATSIYA TUZATISHINING SHARTI ═══════════════════

def test_SOTILGAN_kogortaning_IDENTIFIKATSIYASI_tuzatilmaydi(client, admin_headers,
                                                             ctx, sup):
    """Tovar ketgan kogortaning narxi/muddati/raqami tarixda ALLAQACHON ishlatilgan.

    ⚠️  `sale_item_lot_allocations.unit_cost` — sotuv LAHZASINING muzlatilgan
        surati. Kogortani o'ldirib o'rniga yangisini qo'yish sotilgan tovarning
        COGS'ini havoda qoldirardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=100, cost=700)
    s = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": d["pid"], "qty": 30, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 50000,
        "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": _batch_id(d), "qty": 70}],
        "replace": [{"qty": 70, "batch_number": "TO'G'RI-1", "unit_cost": 800}],
        "unit_cost": 800}])
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_CONSUMED, r.headers
    assert "30.000 dona allaqachon harakatlangan" in r.json()["detail"], r.text
    assert "faqat MIQDORNI teskari qilish mumkin" in r.json()["detail"], r.text
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("70.000")
    _ok(cid, d["pid"])


def test_SOTILIB_QAYTARILGAN_kogorta_HAM_TEGILGAN(client, admin_headers, ctx, sup):
    """⚠️  `remaining_qty == received_qty` YOLG'IZ YETMAYDI.

    Sotuv + mijoz qaytarishi qoldiqni AYNAN tiklaydi (`lot_return._restock`
    hatto `depleted` partiyani qayta ochadi). Faqat qoldiqqa qaragan darvoza bu
    kogortani «tegilmagan» deb o'tkazib yuborardi — holbuki uning raqami va
    narxi chekda ham, qaytarishda ham ALLAQACHON ishlatilgan.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=40, cost=700)
    s = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": d["pid"], "qty": 10, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 50000,
        "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    client.post("/api/v1/shifts/open", headers=admin_headers, json={"opening_cash": 1000000})
    ret = client.post("/api/v1/returns", headers=admin_headers, json={
        "original_sale_id": s.json()["id"], "reason": "customer", "restock": True,
        "refund_method": "cash", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": d["pid"], "qty": 10, "unit_price": 0}]})
    assert ret.status_code == 200, ret.text
    b = _batch(_batch_id(d))
    assert Decimal(str(b.remaining_qty)) == Decimal(str(b.received_qty)), (
        "sinov bo'sh bo'lardi: qoldiq tiklanmagan")

    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": _batch_id(d), "qty": 40}],
        "replace": [{"qty": 40, "batch_number": "TO'G'RI-2", "unit_cost": 750}],
        "unit_cost": 750}])
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_CONSUMED, r.headers
    _ok(cid, d["pid"])


def test_MIQDOR_teskarisi_kogortani_IDENTIFIKATSIYA_uchun_YOPADI(client, admin_headers,
                                                                 ctx, sup):
    """Birinchi teskari yozuv `stock_movement_lot_allocations` qatori YOZADI.

    ⚠️  Shundan keyin kogorta HECH QACHON «tegilmagan» ko'rinmaydi va
        identifikatsiyasini tuzatib bo'lmaydi. Ya'ni identifikatsiya tuzatishi
        kogortaga BIRINCHI tegish bo'lishi shart. Bu qoida ataylab: allokatsiya
        qatori — kogortadan miqdor CHIQQANINING yozuvi, va uni «o'zimiznikida
        hisobga olmaymiz» deb chetlab o'tish darvozani ichkaridan ochardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=95, cost=700)
    r1 = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 10)])
    assert r1.status_code == 200, r1.text
    r2 = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": _batch_id(d), "qty": 85}],
        "replace": [{"qty": 85, "batch_number": "KEYIN", "unit_cost": 700}],
        "unit_cost": 700}])
    assert r2.status_code == 409, r2.text
    assert _code(r2) == EC.LOT_CORRECTION_CONSUMED, r2.headers
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("85.000")
    _ok(cid, d["pid"])


def test_YOPILMAGAN_partiya_qarzi_tuzatishni_TOSADI(client, admin_headers, ctx, sup):
    """Qarz ochiq ekan QAYSI kogorta ketgani NOMA'LUM.

    ⚠️  Darvoza bo'lmasa tuzatish qarzni jimgina boshqa (qolgan) partiyaga
        surardi: qarz keyinchalik yopilganda u ALLAQACHON o'zgartirilgan
        kogortaga bog'lanib, tannarx tarixini yolg'on qilardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=3, cost=700)
    # Offline chek: partiyada 3 ta bor, chekda 10 ta sotilgan -> 7 qarz.
    rp = client.post("/api/v1/sync/push", headers=admin_headers, json={"sales": [{
        "client_uuid": str(uuid.uuid4()), "payment_method": "cash",
        "items": [{"product_id": d["pid"], "qty": 10, "unit_price": 1000}],
        "given_amount": 20000}]})
    assert rp.status_code == 200, rp.text
    assert rp.json()["results"][0]["ok"] is True, rp.text

    d2 = _doc(client, admin_headers, sup, qty=20, cost=700, batch="QARZ-2", pid=d["pid"])
    r = _correct(client, admin_headers, d2["rec"], [_rev(d2["item"], _batch_id(d2), 1)])
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_SHORTFALL_OPEN, r.headers
    assert "yopilmagan partiya qarzi bor" in r.json()["detail"], r.text
    assert Decimal(str(_batch(_batch_id(d2)).remaining_qty)) == Decimal("20.000")
    # O'qish yo'li ham AYNI predikatdan javob beradi (ekran server bilan ajralmasin),
    # lekin to'siq QATOR darajasida: hujjatning o'zi tuzatish uchun ochiq qoladi.
    det = _pur(client, admin_headers, d2["pur"]).json()
    assert det["correctable"] is True and det["correction_blocked_reason"] is None
    it = det["items"][0]
    assert it["correctable"] is False
    assert it["correction_blocked_reason"] == (
        "Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga "
        "bog'lang, keyin bu qatorni tuzating.")
    assert all(l["correctable"] is False for l in it["lots"]), it["lots"]


def test_QARZ_bitta_QATORNI_tosadi_BOSHQASINI_EMAS(client, admin_headers, ctx, sup):
    """⚠️  3-QATORDAGI QARZ 7-QATORNI TUZATISHGA TO'SQINLIK QILMAYDI.

    Ilgari `correctable` HUJJAT bo'yicha hisoblanardi: bitta mahsulotda ochiq
    qarz bo'lsa butun nakladnoyda «Tuzatish» tugmasi yo'qolardi — holbuki
    server faqat O'SHA mahsulot qatorini rad etadi. Operator esa qarzni yopa
    olmasligi mumkin (uning uchun tovar kerak) va butun hujjat qulflanib
    qolardi.
    """
    cid, bid = ctx
    qarzli = _new_product(client, admin_headers)
    toza = _new_product(client, admin_headers)
    for p in (qarzli, toza):
        assert _enable(client, admin_headers, p).status_code == 200
    # Qarzli mahsulot: 3 dona bor, offline chekda 10 sotilgan -> 7 qarz.
    r0 = _commit(client, admin_headers,
                 [_line(qarzli, 3, 700, [{"qty": 3, "batch_number": "Q-0"}])], supplier=sup)
    assert r0.status_code == 200, r0.text
    rp = client.post("/api/v1/sync/push", headers=admin_headers, json={"sales": [{
        "client_uuid": str(uuid.uuid4()), "payment_method": "cash",
        "items": [{"product_id": qarzli, "qty": 10, "unit_price": 1000}],
        "given_amount": 20000}]})
    assert rp.json()["results"][0]["ok"] is True, rp.text

    r = _commit(client, admin_headers,
                [_line(qarzli, 5, 700, [{"qty": 5, "batch_number": "Q-1"}]),
                 _line(toza, 5, 500, [{"qty": 5, "batch_number": "T-1"}])], supplier=sup)
    assert r.status_code == 200, r.text
    det = _pur(client, admin_headers, r.json()["purchase_id"]).json()
    assert det["correctable"] is True, det["correction_blocked_reason"]
    qator = {x["product_id"]: x for x in det["items"]}
    assert qator[qarzli]["correctable"] is False
    assert qator[toza]["correctable"] is True
    assert qator[toza]["correction_blocked_reason"] is None
    assert all(l["correctable"] for l in qator[toza]["lots"]), qator[toza]["lots"]
    # Toza qator HAQIQATAN tuzatiladi (o'qish yo'li yolg'on umid bermasin).
    c = _correct(client, admin_headers, r.json()["receiving_id"],
                 [_rev(qator[toza]["id"], qator[toza]["lots"][0]["id"], 2)])
    assert c.status_code == 200, c.text
    assert _inv_qty(toza, bid) == Decimal("3.000")
    _ok(cid, toza)


# ══ 5. O'RNIGA QO'YILADIGAN PARTIYA — ODDIY KIRIM DARVOZALARI ═══════════════

def test_ORNIGA_qoyish_MUDDAT_darvozalaridan_OTADI(client, admin_headers, ctx, sup):
    """Tuzatish kirimning YUMSHOQROQ eshigi bo'lib qolmasin.

    `/receiving/commit` muddatsiz yoki muddati o'tgan partiyani rad etadi;
    tuzatish o'sha `validate_line` ni AYNAN chaqiradi va AYNI matnni beradi.
    """
    cid, bid = ctx
    client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})
    d = _doc(client, admin_headers, sup, qty=10, cost=700, expiry=FUTURE,
             track_expiry=True)
    bid_ = _batch_id(d)
    yoq = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": bid_, "qty": 10}],
        "replace": [{"qty": 10, "batch_number": "MUDDATSIZ", "unit_cost": 700}],
        "unit_cost": 700}])
    assert yoq.status_code == 400, yoq.text
    assert "`expiry_date` MAJBURIY" in yoq.json()["detail"], yoq.text

    otgan = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": bid_, "qty": 10}],
        "replace": [{"qty": 10, "expiry_date": PAST.isoformat(), "unit_cost": 700}],
        "unit_cost": 700}])
    assert otgan.status_code == 400, otgan.text
    assert "muddati o'tgan tovar qabul qilinmaydi" in otgan.json()["detail"], otgan.text
    assert Decimal(str(_batch(bid_).remaining_qty)) == Decimal("10.000")
    _ok(cid, d["pid"])


def test_ORNIGA_qoyishda_ANIQLIK_darvozasi_KIRIM_BILAN_AYNI(client, admin_headers, ctx, sup):
    """Uchtadan ortiq kasr xonasi tuzatishda ham RAD etiladi (kirim bilan AYNI).

    ⚠️  TOPILGAN BO'SHLIQ (Phase 5D sinov yozilishida). Xizmat `validate_line` ni
        chaqirar, lekin unga ALLAQACHON `_q3` bilan kvantlangan qiymat uzatardi —
        `_uch_xona` darvozasi HECH QACHON yonmasdi va 9.2345 jimgina 9.235 bo'lib
        yozilardi. Qoldiq ham ayni `_q3` bilan yozilgani uchun invariant BUZILMAS,
        ya'ni hech bir tekshiruv buni ko'rmasdi: ayni raqam ikki eshikda ikki xil
        javob olardi. Endi xizmat XOM qiymat uzatadi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=700)
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": _batch_id(d), "qty": 10}],
        "replace": [{"qty": 9.2345, "unit_cost": 700}],
        "unit_cost": 700}])
    assert r.status_code == 400, r.text
    assert "uchtadan ORTIQ kasr xonasi" in r.json()["detail"], r.text
    # HECH NARSA yozilmadi: asl partiya butun, qoldiq o'zgarmagan.
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("10.000")
    assert _inv_qty(d["pid"], bid) == Decimal("10.000")
    assert len(_lots(d["pid"])) == 1
    _ok(cid, d["pid"])


def test_ODDIY_KIRIM_ayni_miqdorni_RAD_etadi(client, admin_headers, sup):
    """Yuqoridagi bo'shliqning NAZORAT tomoni: eski eshik hamon YOPIQ.

    Ikkala sinov birga turadi — biri boshqasisiz «kirim ham shunday qiladi»
    degan yolg'on taassurot berardi.
    """
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    r = _commit(client, admin_headers,
                [_line(pid, 9.2345, 700, [{"qty": 9.2345}])], supplier=sup)
    assert r.status_code == 400, r.text
    assert "uchtadan ORTIQ kasr xonasi" in r.json()["detail"], r.text


def test_ZONA_TASDIQLANMAGAN_bolsa_ORNIGA_qoyish_409(client, admin_headers, ctx, sup):
    """Muddat kuzatuvi tasdiqlangan vaqt zonasiga tayanadi — tasdiq yo'qolsa 409.

    Bu HOLAT ziddiyati (ma'lumot xatosi emas), `/receiving/commit` bilan AYNI
    tarjima: `TimezoneNotConfigured` -> 409.
    """
    from app.services import catalog_import_v2 as civ2
    from app.services import lot_policy as LP
    cid, bid = ctx
    client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})
    d = _doc(client, admin_headers, sup, qty=10, cost=700, expiry=FUTURE,
             track_expiry=True)
    with _db() as db:
        civ2.set_catalog_settings(db, cid, **{LP.CONFIRM_FIELD: {}})
        db.commit()
    try:
        r = _correct(client, admin_headers, d["rec"], [{
            "purchase_item_id": d["item"],
            "reverse": [{"stock_batch_id": _batch_id(d), "qty": 10}],
            "replace": [{"qty": 10, "expiry_date": FUTURE.isoformat(), "unit_cost": 700}],
            "unit_cost": 700}])
        assert r.status_code == 409, r.text
        assert "TASDIQLANMAGAN" in r.json()["detail"], r.text
    finally:
        client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("10.000")
    _ok(cid, d["pid"])


# ══ 6. SO'ROV SHAKLI ════════════════════════════════════════════════════════

def test_SHAKL_xatolari_400_va_bazaga_TEGMAYDI(client, admin_headers, ctx, sup):
    """Shakl bazaga tegmasdan tekshiriladi — har rad etishda IZ qolmasligi shart."""
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=700)
    b = _batch_id(d)
    holatlar = [
        ([{"purchase_item_id": d["item"], "reverse": [{"stock_batch_id": b, "qty": 1}]},
          {"purchase_item_id": d["item"], "reverse": []}],
         f"Qator ikki marta ko'rsatilgan: {d['item']}"),
        ([{"purchase_item_id": d["item"]}],
         f"Qatorda na teskari qilish, na o'rniga qo'yish bor: {d['item']}"),
        ([{"purchase_item_id": d["item"],
           "reverse": [{"stock_batch_id": b, "qty": 1},
                       {"stock_batch_id": b, "qty": 2}]}],
         f"Partiya ikki marta ko'rsatilgan: {b}"),
        ([{"purchase_item_id": d["item"],
           "reverse": [{"stock_batch_id": b, "qty": 1}],
           "replace": [{"qty": 1, "unit_cost": 700}]}],
         f"O'rniga qo'yiladigan partiya bor, lekin qator tannarxi berilmagan: "
         f"{d['item']}. Tannarx TAXMIN QILINMAYDI."),
        ([{"purchase_item_id": d["item"],
           "reverse": [{"stock_batch_id": b, "qty": 1}], "unit_cost": 900}],
         f"Tannarxni partiyasiz tuzatib bo'lmaydi: {d['item']}. Eski partiyani "
         f"teskari qiling va yangisini `replace` bilan e'lon qiling."),
        ([{"purchase_item_id": str(uuid.uuid4()),
           "reverse": [{"stock_batch_id": b, "qty": 1}]}], "Qator topilmadi: "),
    ]
    for lines, kutilgan in holatlar:
        r = _correct(client, admin_headers, d["rec"], lines)
        assert r.status_code == 400, (kutilgan, r.status_code, r.text)
        assert r.json()["detail"].startswith(kutilgan), (kutilgan, r.text)
    assert not _corrections(d["pur"]), "shakl xatosi TUZATISH sarlavhasini yozdi"
    assert _inv_qty(d["pid"], bid) == Decimal("10.000")


def test_TANNARXNI_PARTIYASIZ_tuzatib_bolmaydi_NEGA(client, admin_headers, sup):
    """`replace` bo'sh, `unit_cost` berilgan — JIMGINA e'tiborsiz qoldirilmaydi.

    ⚠️  `StockBatch.unit_cost` o'zgarmas. Bu qiymatni «shunchaki qabul qilish»
        operatorga narx tuzatildi deb ko'rsatib, aslida hech narsa qilmasdi;
        qo'llash esa muzlatilgan tannarxni qayta yozardi.
    """
    d = _doc(client, admin_headers, sup, qty=5, cost=700)
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": _batch_id(d), "qty": 1}], "unit_cost": 999}])
    assert r.status_code == 400, r.text
    assert r.json()["detail"].startswith("Tannarxni partiyasiz tuzatib bo'lmaydi")
    assert Decimal(str(_batch(_batch_id(d)).unit_cost)) == Decimal("700.00")


def test_MAJBURIY_maydonlar_422(client, admin_headers, sup):
    """`client_uuid` va `reason` — MAJBURIY (pydantic darvozasi servisdan oldin).

    ⚠️  `client_uuid` uchun DEFAULT qo'yish idempotentlikni o'ldirardi: har
        takror so'rov yangi kalit olib, amalni IKKINCHI marta bajarardi.
    """
    d = _doc(client, admin_headers, sup, qty=5, cost=700)
    url = f"/api/v1/receiving/{d['rec']}/corrections"
    lines = [_rev(d["item"], _batch_id(d), 1)]
    assert client.post(url, headers=admin_headers,
                       json={"reason": REASON, "lines": lines}).status_code == 422
    assert client.post(url, headers=admin_headers, json={
        "client_uuid": str(uuid.uuid4()), "reason": "ha", "lines": lines}).status_code == 422
    assert client.post(url, headers=admin_headers, json={
        "client_uuid": str(uuid.uuid4()), "reason": REASON, "lines": []}).status_code == 422


def test_BOSH_qatorlar_servis_darajasida_ham_RAD_etiladi():
    """Servis HTTP'ga tayanmaydi — shakl darvozasi o'z ichida ham to'liq."""
    with pytest.raises(LC.CorrectionError) as e:
        LC._check_shape(LC.CorrectionIn(client_uuid=uuid.uuid4(), reason=REASON, lines=[]))
    assert e.value.status == 400 and e.value.detail == "Kamida bitta qator kerak"
    with pytest.raises(LC.CorrectionError) as e2:
        LC._check_shape(LC.CorrectionIn(client_uuid=uuid.uuid4(), reason="ab", lines=[
            LC.LineIn(purchase_item_id=uuid.uuid4(),
                      reverse=[LC.ReverseIn(stock_batch_id=uuid.uuid4(), qty=Decimal("1"))])]))
    assert e2.value.status == 400 and "sababi" in e2.value.detail


# ══ 7. MUVAFFAQIYATLI OQIMLAR ═══════════════════════════════════════════════

def test_MIQDOR_teskarisi_qoldiqni_va_hujjatni_kamaytiradi(client, admin_headers,
                                                           ctx, sup):
    """«100 emas, 90 keldi» — eng ko'p uchraydigan tuzatish.

    Tarixda hech narsa yolg'on bo'lmaydi: `purchase_items` TEGILMAYDI (ular
    ASLIDA nima yozilganining yozuvi), faqat hosila pul maydonlari siljiydi.
    """
    from app.models.purchasing import PurchaseItem
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=100, cost=700)
    b0 = _batch(_batch_id(d))
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 10)])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["duplicate"] is False
    assert j["reversed_total"] == 7000.0 and j["replaced_total"] == 0.0
    assert j["delta_total"] == -7000.0
    assert j["cancelled"] is False and j["purchase_status"] == "debt"

    b = _batch(_batch_id(d))
    assert Decimal(str(b.remaining_qty)) == Decimal("90.000")
    assert Decimal(str(b.received_qty)) == Decimal(str(b0.received_qty)), (
        "`received_qty` QAYTA YOZILDI — kogorta tarixi yolg'on bo'ldi")
    assert Decimal(str(b.unit_cost)) == Decimal("700.00")
    assert b.status == SI.OPEN
    assert _inv_qty(d["pid"], bid) == Decimal("90.000")

    det = _pur(client, admin_headers, d["pur"]).json()
    assert det["total"] == 63000.0 and det["subtotal"] == 63000.0
    with _db() as db:
        it = db.query(PurchaseItem).filter(
            PurchaseItem.id == uuid.UUID(d["item"])).first()
        assert Decimal(str(it.qty)) == Decimal("100.000"), "xarid qatori QAYTA YOZILDI"
        assert Decimal(str(it.line_total)) == Decimal("70000.00")
    _ok(cid, d["pid"])


def test_TESKARI_yozuv_HARAKATI_APPEND_ONLY(client, admin_headers, ctx, sup):
    """Kirim harakati TEGILMAYDI — kompensatsiya ALOHIDA qator bo'lib qo'shiladi."""
    from app.models.enums import MovementType
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=50, cost=700)
    oldin = _movements(d["pid"])
    assert len(oldin) == 1 and oldin[0].type == MovementType.purchase_in
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 20)])
    assert r.status_code == 200, r.text
    keyin = _movements(d["pid"])
    assert len(keyin) == 2, [m.type for m in keyin]
    assert Decimal(str(keyin[0].qty)) == Decimal("50.000"), "ASL harakat o'zgartirildi"
    kompensatsiya = keyin[1]
    assert kompensatsiya.type == MovementType.adjustment
    assert Decimal(str(kompensatsiya.qty)) == Decimal("-20.000")
    assert kompensatsiya.ref_type == LC.REF_TYPE
    assert Decimal(str(kompensatsiya.unit_cost)) == Decimal("700.00")
    assert Decimal(str(kompensatsiya.balance_after)) == Decimal("30.000")
    _ok(cid, d["pid"])


def test_TOLIQ_teskari_qilish_hujjatni_BEKOR_qiladi(client, admin_headers, ctx, sup):
    """Hamma kogorta teskari qilinsa hujjat `cancelled` + `deleted_at` bo'ladi.

    ⚠️  `paid_amount` TIKLANMAYDI (`edit_purchase` bilan AYNI semantika): u
        kassa artefakti, hujjat jami esa 0. Bekor qilingan hujjat keyingi HAR
        tuzatish uchun 404 — ikkinchi bekor qilish ikkinchi naqd qaytarish
        yozardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=12, cost=700)
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 12)])
    assert r.status_code == 200, r.text
    assert r.json()["cancelled"] is True
    assert r.json()["purchase_status"] == "cancelled"

    assert _pur(client, admin_headers, d["pur"]).status_code == 404
    assert _inv_qty(d["pid"], bid) == Decimal("0.000")
    b = _batch(_batch_id(d))
    assert Decimal(str(b.remaining_qty)) == Decimal("0.000")
    assert b.status == SI.VOID, "tegilmagan, to'liq teskari qilingan kogorta `void` emas"

    ikkinchi = _correct(client, admin_headers, d["rec"],
                        [_rev(d["item"], _batch_id(d), 1)])
    assert ikkinchi.status_code == 404, ikkinchi.text
    assert ikkinchi.json()["detail"] == "Kirim topilmadi"
    _ok(cid, d["pid"])


def test_TEGILGAN_kogorta_DEPLETED_tegilmagani_VOID(client, admin_headers, ctx, sup):
    """`void` — «bu qabul BO'LMAGAN»; `depleted` — «bo'lgan va tugagan».

    ⚠️  Ikkalasi ham miqdor tashimaydi, lekin `void` kogorta qabul tarixidan
        chiqadi. Sotilgan kogortani `void` qilish sotilgan tovarni hech qachon
        kelmagan deb e'lon qilardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=40, cost=700)
    s = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": d["pid"], "qty": 10, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 50000,
        "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 30)])
    assert r.status_code == 200, r.text
    b = _batch(_batch_id(d))
    assert Decimal(str(b.remaining_qty)) == Decimal("0.000")
    assert b.status == SI.DEPLETED, "sotilgan kogorta `void` qilindi"
    _ok(cid, d["pid"])


def test_IDENTIFIKATSIYA_tuzatishi_YANGI_kogorta_tugdiradi(client, admin_headers,
                                                           ctx, sup):
    """Narx/raqam xato kiritilgan — eski kogorta o'ladi, yangisi ANIQ e'lon qilinadi.

    ⚠️  Yangi partiya `doc_key=corr:<id>` bilan tug'iladi. Asl qabulning
        `client_uuid` i bilan yozilsa `create_lots` MAVJUD kogortani QAYTARIB,
        tuzatish jimgina hech narsa qilmasdi (`ux_lot_intake_key`).
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=20, cost=700, batch="XATO")
    eski = _batch_id(d)
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": eski, "qty": 20}],
        "replace": [{"qty": 20, "batch_number": "TO'G'RI", "unit_cost": 850}],
        "unit_cost": 850}])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["reversed_total"] == 14000.0 and j["replaced_total"] == 17000.0
    assert j["delta_total"] == 3000.0 and j["cancelled"] is False

    assert _batch(eski).status == SI.VOID
    assert Decimal(str(_batch(eski).unit_cost)) == Decimal("700.00"), (
        "eski kogorta narxi QAYTA YOZILDI")
    yangi = [b for b in _lots(d["pid"]) if str(b.id) != eski]
    assert len(yangi) == 1, [str(b.id) for b in yangi]
    n = yangi[0]
    assert n.batch_no == "TO'G'RI"
    assert Decimal(str(n.unit_cost)) == Decimal("850.00")
    assert Decimal(str(n.remaining_qty)) == Decimal("20.000")
    assert n.source_type == LR.SOURCE_CORRECTION, n.source_type
    assert str(n.receiving_id) == d["rec"], "yangi kogorta hujjatga bog'lanmagan"
    # Miqdor o'zgarmadi — faqat IDENTIFIKATSIYA.
    assert _inv_qty(d["pid"], bid) == Decimal("20.000")
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 17000.0
    _ok(cid, d["pid"])


def test_KOP_PARTIYAGA_QAYTA_BOLISH(client, admin_headers, ctx, sup):
    """Bitta kogorta deb yozilgani aslida ikki jismoniy partiya edi."""
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=30, cost=700, batch="BITTA")
    eski = _batch_id(d)
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": eski, "qty": 30}],
        "replace": [{"qty": 10, "batch_number": "BO'LAK-1", "unit_cost": 700},
                    {"qty": 20, "batch_number": "BO'LAK-2", "unit_cost": 700}],
        "unit_cost": 700}])
    assert r.status_code == 200, r.text
    assert r.json()["delta_total"] == 0.0, r.text
    yangi = sorted([b for b in _lots(d["pid"]) if str(b.id) != eski],
                   key=lambda b: Decimal(str(b.received_qty)))
    assert [b.batch_no for b in yangi] == ["BO'LAK-1", "BO'LAK-2"]
    assert [Decimal(str(b.remaining_qty)) for b in yangi] == [Decimal("10.000"),
                                                              Decimal("20.000")]
    assert _batch(eski).status == SI.VOID
    assert _inv_qty(d["pid"], bid) == Decimal("30.000")
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 21000.0
    _ok(cid, d["pid"])


def test_TESKARISIZ_SOF_QOSHIMCHA(client, admin_headers, ctx, sup):
    """`reverse` BO'SH — hujjatda 10 yozilgan, aslida 12 kelgan.

    ⚠️  `lot_writeoff.validate` bo'sh tanlovni «partiyalarni ANIQ ko'rsating»
        deb rad etadi — u CHIQARISH uchun yozilgan. Bu yerda teskari qilinadigan
        narsa YO'Q, shu bois u chaqirilmaydi; aks holda eng tabiiy tuzatish
        (kam yozilgan qabul) umuman mumkin bo'lmasdi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=700)
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"], "reverse": [],
        "replace": [{"qty": 2, "batch_number": "QO'SHIMCHA", "unit_cost": 700}],
        "unit_cost": 700}])
    assert r.status_code == 200, r.text
    assert r.json()["reversed_total"] == 0.0
    assert r.json()["replaced_total"] == 1400.0
    assert r.json()["delta_total"] == 1400.0
    assert _inv_qty(d["pid"], bid) == Decimal("12.000")
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 8400.0
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("10.000")
    _ok(cid, d["pid"])


def test_AUDIT_izi_qoladi(client, admin_headers, ctx, sup):
    """Sababsiz/izsiz tuzatish — audit uchun qora teshik bo'lardi."""
    from app.models.sync import AuditLog
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=700)
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 10)])
    assert r.status_code == 200, r.text
    corr_id = r.json()["correction_id"]
    with _db() as db:
        a = (db.query(AuditLog).filter(AuditLog.entity == "receiving",
                                       AuditLog.entity_id == uuid.UUID(corr_id)).first())
        assert a is not None, "tuzatish AUDITSIZ o'tdi"
        assert a.action == "correct"
        assert a.after["reason"] == REASON
        assert a.after["delta_total"] == -7000.0
        c = (db.query(AuditLog).filter(AuditLog.entity == "purchase",
                                       AuditLog.action == "cancel",
                                       AuditLog.entity_id == uuid.UUID(d["pur"])).first())
        assert c is not None, "to'liq bekor qilish AUDITSIZ o'tdi"


# ══ 8. IDEMPOTENTLIK ════════════════════════════════════════════════════════

def test_TAKROR_sorov_BIR_MARTA_qollanadi(client, admin_headers, ctx, sup):
    """Tarmoq uzilishida yuborilgan takror qoldiqni IKKINCHI marta surmasin.

    Takror BIRINCHI javobni AYNAN qaytaradi (`response_json`), shu bois mijoz
    ikki xil natija ko'rmaydi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=50, cost=700)
    cu = uuid.uuid4()
    lines = [_rev(d["item"], _batch_id(d), 10)]
    r1 = _correct(client, admin_headers, d["rec"], lines, cu=cu)
    r2 = _correct(client, admin_headers, d["rec"], lines, cu=cu)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["duplicate"] is False and r2.json()["duplicate"] is True
    assert r2.json()["correction_id"] == r1.json()["correction_id"]
    assert r2.json()["delta_total"] == r1.json()["delta_total"]
    assert len(_corrections(d["pur"])) == 1, "takror IKKINCHI sarlavha yozdi"
    assert _inv_qty(d["pid"], bid) == Decimal("40.000"), "takror qoldiqni IKKI marta surdi"
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("40.000")
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 28000.0
    _ok(cid, d["pid"])


def test_AYNI_client_uuid_BOSHQA_mazmun_409(client, admin_headers, ctx, sup):
    """Takror emas, MIJOZ XATOSI: ayni kalit bilan boshqa so'rov.

    ⚠️  Uni «takror» deb jimgina qabul qilish eng yomon holat bo'lardi: mijoz
        ikkinchi tuzatish bajarildi deb o'ylardi, aslida birinchisining javobi
        qaytgan bo'lardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=50, cost=700)
    cu = uuid.uuid4()
    assert _correct(client, admin_headers, d["rec"],
                    [_rev(d["item"], _batch_id(d), 10)], cu=cu).status_code == 200
    r = _correct(client, admin_headers, d["rec"],
                 [_rev(d["item"], _batch_id(d), 5)], cu=cu)
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_REPLAY_CONFLICT, r.headers
    assert "Yangi so'rov uchun yangi client_uuid bering" in r.json()["detail"]
    assert _inv_qty(d["pid"], bid) == Decimal("40.000")
    assert len(_corrections(d["pur"])) == 1
    _ok(cid, d["pid"])


def test_QATORLAR_TARTIBI_SOROV_MAZMUNIGA_KIRADI():
    """`line_index` partiya kalitiga kiradi — tartib o'zgarsa bu BOSHQA so'rov.

    ⚠️  Kanonik shaklda qatorlarni SARALASH vasvasasi bor edi. U ikki boshqa
        so'rovni bir xil hash qilib, ikkinchisini «takror» deb yutib yuborardi —
        holbuki ular BOSHQA kogortalar tug'dirardi.
    """
    rec = uuid.uuid4()
    a, b = uuid.uuid4(), uuid.uuid4()
    ba, bb = uuid.uuid4(), uuid.uuid4()

    def _in(order):
        return LC.CorrectionIn(client_uuid=uuid.uuid4(), reason=REASON, lines=[
            LC.LineIn(purchase_item_id=x,
                      reverse=[LC.ReverseIn(stock_batch_id=y, qty=Decimal("1"))])
            for x, y in order])
    assert LC.request_hash(rec, _in([(a, ba), (b, bb)])) != \
        LC.request_hash(rec, _in([(b, bb), (a, ba)]))
    # ⚠️  Kalit DETERMINISTIK: aks holda takror so'rov HAR safar «boshqa mazmun»
    #     bo'lib 409 olardi va idempotentlik umuman ishlamasdi.
    assert LC.request_hash(rec, _in([(a, ba), (b, bb)])) == \
        LC.request_hash(rec, _in([(a, ba), (b, bb)]))


def test_MIQDOR_MATN_sifatida_hash_qilinadi():
    """`0.1 + 0.2` float'da 0.30000000000000004 — hash ikki xil bo'lardi."""
    rec = uuid.uuid4()
    it, bt = uuid.uuid4(), uuid.uuid4()

    def _in(q):
        return LC.CorrectionIn(client_uuid=uuid.uuid4(), reason=REASON, lines=[
            LC.LineIn(purchase_item_id=it,
                      reverse=[LC.ReverseIn(stock_batch_id=bt, qty=q)])])
    assert LC.request_hash(rec, _in(Decimal("0.1") + Decimal("0.2"))) == \
        LC.request_hash(rec, _in(Decimal("0.3")))


# ══ 9. PUL TOMONI — QARZ VA KASSA PARITETI ══════════════════════════════════

def test_QARZ_hujjatida_BALANS_va_LEDGER_pariteti(client, admin_headers, ctx, sup):
    """Qarz hujjati tuzatilsa balans AYNAN delta'ga siljiydi.

    ⚠️  `charge` QATORI QO'SHILMAYDI VA OLINMAYDI. Uchta kassa migratsiyasi
        quyi tizimi `ref_type IN ('purchase','receiving') AND type='charge'`
        predikati bo'yicha «bu hujjat kassadan pul chiqarganmi» degan qarorni
        qabul qiladi — tuzatish o'sha predikatga kirsa, hujjat jimgina naqddan
        qarzga (yoki teskari) aylanardi.
    """
    from app.models.enums import CreditTxnType
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=100, cost=700)
    bal0 = Decimal(str(_sup_row(sup).balance or 0))
    n_charge0 = len([x for x in _ledger(sup)
                     if x.type == CreditTxnType.charge
                     and x.ref_type in ("purchase", "receiving")])

    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 10)])
    assert r.status_code == 200, r.text
    assert Decimal(str(_sup_row(sup).balance)) == bal0 - Decimal("7000.00")
    # Ta'minotchi butun fayl bo'yi UMUMIY — AYNAN shu tuzatishning qatori olinadi.
    rows = [x for x in _ledger(sup) if x.ref_type == LC.REF_TYPE
            and str(x.ref_id) == r.json()["correction_id"]]
    assert len(rows) == 1, rows
    adj = rows[0]
    assert adj.type == CreditTxnType.adjustment
    assert Decimal(str(adj.amount)) == Decimal("-7000.00")
    assert Decimal(str(adj.balance_after)) == bal0 - Decimal("7000.00")
    assert str(adj.ref_id) == r.json()["correction_id"]
    n_charge1 = len([x for x in _ledger(sup)
                     if x.type == CreditTxnType.charge
                     and x.ref_type in ("purchase", "receiving")])
    assert n_charge1 == n_charge0, "tuzatish `charge` predikatiga aralashdi"
    assert _pur(client, admin_headers, d["pur"]).json()["status"] == "debt"
    _ok(cid, d["pid"])


def test_NAQD_hujjatda_KASSA_pariteti(client, admin_headers, ctx, sup):
    """Naqd hujjat: qarz ledgeriga TEGILMAYDI, qaytarish HODISASI yoziladi.

    ⚠️  `paid_amount` yangi jamiga tenglashadi (QA PR-004): uni `partial/debt`
        qilish soxta qarz yaratib, `pay_supplier` FIFO'sini buzardi.
    """
    from app.models.purchasing import PurchaseReturn
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=20, cost=700, payment="cash")
    bal0 = Decimal(str(_sup_row(sup).balance or 0))
    cu = uuid.uuid4()
    r = _correct(client, admin_headers, d["rec"],
                 [_rev(d["item"], _batch_id(d), 5)], cu=cu)
    assert r.status_code == 200, r.text
    assert r.json()["purchase_status"] == "received"
    det = _pur(client, admin_headers, d["pur"]).json()
    assert det["total"] == 10500.0 and det["paid_amount"] == 10500.0
    assert Decimal(str(_sup_row(sup).balance or 0)) == bal0, "naqd hujjat qarzni surdi"
    assert not [x for x in _ledger(sup) if x.ref_type == LC.REF_TYPE
                and str(x.ref_id) == r.json()["correction_id"]]
    with _db() as db:
        pr = (db.query(PurchaseReturn)
              .filter(PurchaseReturn.purchase_id == uuid.UUID(d["pur"])).all())
    assert len(pr) == 1, pr
    assert Decimal(str(pr[0].amount)) == Decimal("3500.00")
    assert pr[0].reason == LC.REF_TYPE
    # ⚠️  Qaytarish hodisasining `client_uuid` i TUZATISHNIKI: kassa oyog'i
    #     ham tuzatish bilan AYNI idempotentlik kalitiga bog'lanadi.
    assert str(pr[0].client_uuid) == str(cu)
    _ok(cid, d["pid"])


def test_SQLITE_da_kassa_quyi_tizimi_YOQ_va_bu_NORMAL(client, admin_headers, ctx, sup):
    """Hook `None` qaytarishi SQLite'da AYBDOR holat EMAS — ledger u yerda YO'Q.

    ⚠️  Buni rad etish sababi bo'lса, HAR naqd hujjat tuzatishi SQLite'da 409
        bo'lardi. Rad etish FAQAT dual-write FAOL bo'lganda o'rinli (keyingi
        sinov). Bu sinov chegarani ikkinchi tomondan mixlaydi.
    """
    from app.services.cash import retrofit as CR
    cid, bid = ctx
    with _db() as db:
        assert CR.dual_write_enabled(db) is False, "SQLite'da dual-write yoqilgan?"
    d = _doc(client, admin_headers, sup, qty=10, cost=700, payment="cash")
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 4)])
    assert r.status_code == 200, r.text
    assert _inv_qty(d["pid"], bid) == Decimal("6.000")
    _ok(cid, d["pid"])


def test_KASSA_yozib_bolmasa_tuzatish_BUTUNLAY_BEKOR(client, admin_headers, ctx, sup,
                                                     monkeypatch):
    """Kassa tegilmagan holda «bajarildi» deyilmaydi.

    ⚠️  Bu HAQIQIY holat: legacy tenantда mos `OUT·PURCHASE_OUT` oyog'i yo'q va
        `on_purchase_return` `None` qaytaradi. Darvozasiz hujjat jami, qoldiq va
        partiyalar siljib, kassa esa JOYIDA qolardi — ya'ni baza ichida jimgina
        farq tug'ilardi.
    """
    from app.services.cash import retrofit as CR
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=700, payment="cash")
    monkeypatch.setattr(CR, "dual_write_enabled", lambda db: True)
    monkeypatch.setattr(CR, "on_purchase_return", lambda *a, **k: None)
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 4)])
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_CASH_UNPOSTABLE, r.headers
    assert "tuzatish BEKOR qilindi" in r.json()["detail"], r.text
    assert _inv_qty(d["pid"], bid) == Decimal("10.000")
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("10.000")
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 7000.0
    assert not _corrections(d["pur"])
    _ok(cid, d["pid"])


# ══ 10. YAKUNIY DARVOZA ═════════════════════════════════════════════════════

def test_INVARIANT_buzilsa_tuzatish_IZ_QOLDIRMAYDI(client, admin_headers, ctx, sup,
                                                   monkeypatch):
    """Darvoza COMMIT'dan OLDIN — rad etilgan tuzatish bazada IZ QOLDIRMASIN.

    ⚠️  Aynan shu xato `/receiving/commit` da topilgan edi: tekshiruv
        `db.commit()` dan KEYIN turganda `db.rollback()` hech narsani
        qaytarmasdi — operator 409 ko'rardi, buzilgan qoldiq esa QOLARDI.

    ⚠️  Istisno MATNI operatorga berilmaydi: `InvariantBroken` ichida xom UUID
        va modul nomlari bor.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=30, cost=700)

    def _boom(db, company_id, product_ids):
        raise SI.InvariantBroken("sun'iy buzilish (sinov) — xom UUID 00000000")
    monkeypatch.setattr(LC.SI, "assert_ok", _boom)

    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 10)])
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_INVARIANT_BROKEN, r.headers
    assert r.json()["detail"] == (
        "Tuzatishni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal "
        "BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.")
    assert "sun'iy buzilish" not in r.text, "ichki istisno matni JAVOBGA sizdi"
    assert _inv_qty(d["pid"], bid) == Decimal("30.000")
    assert Decimal(str(_batch(_batch_id(d)).remaining_qty)) == Decimal("30.000")
    assert not _corrections(d["pur"]), "rad etilgan tuzatish SARLAVHA qoldirdi"
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 21000.0


# ══ 11. ESKI TAHRIR YO'LI ═══════════════════════════════════════════════════

def test_TUZATILGAN_hujjatni_ESKI_tahrir_yoli_OCHMAYDI(client, admin_headers, ctx, sup):
    """`PATCH /purchases/{id}` jamini QATORLARDAN qayta hisoblaydi.

    ⚠️  Darvozasiz bitta saqlash tuzatishni JIMGINA teskari qilardi: jami
        `purchase_items` dan tiklanardi (ular tegilmagan), qarz va kassa esa
        tuzatilgan holida qolardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=20, cost=700)
    assert _correct(client, admin_headers, d["rec"],
                    [_rev(d["item"], _batch_id(d), 5)]).status_code == 200
    r = client.patch(f"/api/v1/purchases/{d['pur']}", headers=admin_headers, json={
        "items": [{"id": d["item"], "qty": 20, "unit_cost": 700}]})
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_DOC_LOCKED, r.headers
    assert "yangi tuzatish yarating" in r.json()["detail"], r.text
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 10500.0


def test_TUZATILMAGAN_hujjatda_darvoza_YONMAYDI(client, admin_headers, ctx, sup):
    """MANFIY NAZORAT: qulf «har doim yoqiq» bo'lib qolmasin.

    Kuzatuvli qatorda `PATCH` baribir 409 beradi — lekin BOSHQA sabab bilan
    (`stock_gate`), ya'ni tuzatish kodi sarlavhada BO'LMASLIGI shart.
    """
    d = _doc(client, admin_headers, sup, qty=20, cost=700)
    r = client.patch(f"/api/v1/purchases/{d['pur']}", headers=admin_headers, json={
        "items": [{"id": d["item"], "qty": 10, "unit_cost": 700}]})
    assert r.status_code == 409, r.text
    assert _code(r) != EC.LOT_CORRECTION_DOC_LOCKED, r.headers


# ══ 12. MAJBURIY SXEMA — IDEMPOTENTLIK KALITI ══════════════════════════════

def test_TUZATISH_idempotentlik_indeksi_MAJBURIY():
    """`ux_recv_corr_client` — takrorga qarshi YAGONA tranzaksion kafolat.

    ⚠️  Indeks yo'qolsa `_replay()` SELECT-dedup'ga aylanadi — klassik TOCTOU:
        ikki bir vaqtdagi takror ikkalasi ham «sarlavha yo'q» deb ko'rib,
        qoldiqni, qarzni va kassani IKKI marta siljitardi. Shu bois u
        `REQUIRED_INDEXES` da: `/health/ready` qizil bo'ladi VA `/lots/enable`
        (u `required_schema.missing` ni o'qiydi) aktivatsiyani to'sadi.

    ⚠️  `IDEMPOTENCY_INDEXES` GA ATAYIN KIRITILMAGAN. `test_runtime_columns.py`
        har boot indeksi AYNAN BITTA sinfda bo'lishini talab qiladi va o'sha
        ro'yxatning tarkibini qattiq mixlaydi; ikkala sinfga qo'shish butun
        to'plamni qizartirardi. Bu yerdagi tanlov KUCHLIROQ — ikkala maqsad ham
        `REQUIRED_INDEXES` orqali qoplanadi.
    """
    from app.core import required_schema as rs
    assert ("ux_recv_corr_client", "receiving_corrections") in rs.REQUIRED_INDEXES
    assert "ux_recv_corr_client" not in {n for n, _ in rs.IDEMPOTENCY_INDEXES}
    # Migratsiya MAVJUD bazada ham indeksni tuzata olishi shart (`create_all`
    # mavjud jadvalga indeks qo'shmaydi) — DDL `initdb._ensure_indexes` da.
    import pathlib
    src = (pathlib.Path(rs.__file__).resolve().parents[1] / "initdb.py").read_text(
        encoding="utf-8")
    assert "ux_recv_corr_client" in src, "boot migratsiyasi indeksni qurmaydi"


# ══ 13. O'QISH YO'LI — SERVER QARORI, MIJOZ HISOBI EMAS ═════════════════════

def test_GET_purchases_TUZATISH_KORINISHINI_beradi(client, admin_headers, ctx, sup):
    """Operator tugmani bosishdan OLDIN bilishi kerak: qancha qoldi, qanchasi ketdi.

    ⚠️  Buni frontend O'ZI hisoblab chiqarmasin — aks holda ekran server
        qoidasi (`lot_correction.untouched`) bilan bir kun ajralib ketardi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=40, cost=700, batch="KO'RINISH")
    det = _pur(client, admin_headers, d["pur"]).json()
    assert det["receiving_id"] == d["rec"]
    assert det["correctable"] is True and det["correction_blocked_reason"] is None
    assert det["corrections"] == []
    lot = det["items"][0]["lots"][0]
    assert lot["batch_no"] == "KO'RINISH"
    assert lot["received_qty"] == 40.0 and lot["remaining_qty"] == 40.0
    assert lot["consumed_qty"] == 0.0 and lot["correctable"] is True
    assert lot["status"] == SI.OPEN

    s = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": d["pid"], "qty": 15, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 50000,
        "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 5)])
    assert r.status_code == 200, r.text

    det2 = _pur(client, admin_headers, d["pur"]).json()
    lot2 = det2["items"][0]["lots"][0]
    assert lot2["remaining_qty"] == 20.0
    assert lot2["consumed_qty"] == 20.0, "sotuv + teskari yozuv `consumed` ga kirmadi"
    assert lot2["correctable"] is False, "tegilgan kogorta tuzatish uchun ochiq ko'rindi"
    assert len(det2["corrections"]) == 1
    c = det2["corrections"][0]
    assert c["id"] == r.json()["correction_id"]
    assert c["reason"] == REASON and c["delta_total"] == -3500.0
    assert c["employee"] and c["employee"] != "—"
    _ok(cid, d["pid"])


# ══ 14. TEGILGANLIK DALILI — QARZNI YOPISH KANALI ═══════════════════════════

def _utc(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _shortfall(client, headers, pid):
    r = client.get("/api/v1/lots/shortfalls", headers=headers)
    assert r.status_code == 200, r.text
    rows = [x for x in r.json()["shortfalls"] if x["product_id"] == pid]
    return rows[0] if rows else None


def _sale_by_cu(cu):
    """`/sync/push` javobi `receipt_no` beradi, `id` emas — chekni o'zimiz topamiz."""
    from app.models.sales import Sale
    with _db() as db:
        row = db.query(Sale).filter(Sale.client_uuid == uuid.UUID(str(cu))).first()
        assert row is not None, "offline chek topilmadi"
        return str(row.id)


def test_QARZ_YOPILGAN_kogorta_TEGILMAGAN_KORINMAYDI(client, admin_headers, ctx, sup):
    """⚠️  YOPISH KANALI UCHTA ESKI JADVALDA KO'RINMAYDI.

    Ketma-ketlik: offline chek qarz tug'diradi -> operator qarzni X kogortaga
    YOPADI (X dan 6 dona ketadi va AYNAN uning narxida COGS og'ishi tan
    olinadi) -> mijoz chekni qaytaradi, o'sha 6 dona X ga QAYTADI
    (`return_item_resolution_allocations`).

    Natijada X: qoldiq == kelgan, `sale_item_lot_allocations` BO'SH,
    `stock_movement_lot_allocations` BO'SH, `return_item_lot_allocations`
    BO'SH — ya'ni eski dalil uni «tegilmagan» deb ko'rsatardi va uning partiya
    raqami/narxini tuzatib, kogortani `void` qilib yuborish mumkin edi.
    Holbuki o'sha narx bo'yicha og'ish ALLAQACHON tan olingan.
    """
    cid, bid = ctx
    d1 = _doc(client, admin_headers, sup, qty=4, cost=50, batch="QARZ-ASL")
    cu = uuid.uuid4()
    rp = client.post("/api/v1/sync/push", headers=admin_headers, json={"sales": [{
        "client_uuid": str(cu), "payment_method": "cash",
        "items": [{"product_id": d1["pid"], "qty": 10, "unit_price": 100}],
        "given_amount": 20000}]})
    assert rp.json()["results"][0]["ok"] is True, rp.text

    d2 = _doc(client, admin_headers, sup, qty=6, cost=90, batch="YOPISH", pid=d1["pid"])
    x = _batch_id(d2)
    sf = _shortfall(client, admin_headers, d1["pid"])
    assert sf is not None and sf["open_qty"] == 6.0, sf
    rr = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
                     json={"stock_batch_id": x, "qty": 6,
                           "reason": "inventarizatsiyada topildi",
                           "client_uuid": str(uuid.uuid4())})
    assert rr.status_code == 200, rr.text
    assert rr.json()["closed"] is True, rr.text

    client.post("/api/v1/shifts/open", headers=admin_headers, json={"opening_cash": 1000000})
    ret = client.post("/api/v1/returns", headers=admin_headers, json={
        "original_sale_id": _sale_by_cu(cu), "reason": "customer", "restock": True,
        "refund_method": "cash", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": d1["pid"], "qty": 10, "unit_price": 0}]})
    assert ret.status_code == 200, ret.text
    b = _batch(x)
    assert Decimal(str(b.remaining_qty)) == Decimal(str(b.received_qty)), (
        "sinov bo'sh bo'lardi: kogorta qoldig'i tiklanmagan")

    r = _correct(client, admin_headers, d2["rec"], [{
        "purchase_item_id": d2["item"],
        "reverse": [{"stock_batch_id": x, "qty": 6}],
        "replace": [{"qty": 6, "batch_number": "KECH", "unit_cost": 90}],
        "unit_cost": 90}])
    assert r.status_code == 409, r.text
    assert _code(r) == EC.LOT_CORRECTION_CONSUMED, r.headers
    # GROSS harakat: 6 dona chiqqan (qaytgani AYIRILMAYDI).
    assert "partiyadan 6.000 dona allaqachon harakatlangan" in r.json()["detail"], r.text
    assert _batch(x).status == SI.OPEN, "rad etilgan tuzatish kogortani o'ldirdi"
    _ok(cid, d1["pid"])


def test_SOTILIB_QAYTARILGAN_kogortada_GROSS_harakat_KORSATILADI(client, admin_headers,
                                                                 ctx, sup):
    """`consumed_qty` va rad etish xabari NETTO emas, GROSS bo'lishi shart.

    ⚠️  Netto hisob bilan 15 sotilib 15 qaytgan kogorta «0 dona harakatlangan»
        deb ko'rsatilardi — ya'ni xabar AYNAN o'zi aytayotgan sababni inkor
        qilardi. Kogorta raqami va narxi esa chekda ham, qaytarishda ham
        ALLAQACHON ishlatilgan.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=15, cost=700, batch="GROSS")
    s = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": d["pid"], "qty": 15, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 50000,
        "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    client.post("/api/v1/shifts/open", headers=admin_headers, json={"opening_cash": 1000000})
    ret = client.post("/api/v1/returns", headers=admin_headers, json={
        "original_sale_id": s.json()["id"], "reason": "customer", "restock": True,
        "refund_method": "cash", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": d["pid"], "qty": 15, "unit_price": 0}]})
    assert ret.status_code == 200, ret.text

    lot = _pur(client, admin_headers, d["pur"]).json()["items"][0]["lots"][0]
    assert lot["consumed_qty"] == 15.0, "qaytarish sotuvdan AYIRILDI (netto)"
    assert lot["correctable"] is False
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": _batch_id(d), "qty": 15}],
        "replace": [{"qty": 15, "batch_number": "YANGI", "unit_cost": 700}],
        "unit_cost": 700}])
    assert r.status_code == 409, r.text
    assert "partiyadan 15.000 dona allaqachon harakatlangan" in r.json()["detail"], r.text
    _ok(cid, d["pid"])


# ══ 15. IKKI XIL PUL ASOSI — HUJJAT vs COGS ═════════════════════════════════

def test_PARTIYA_narxi_QATOR_narxidan_FARQ_qilsa_TOLIQ_teskari_NOLGA_tushadi(
        client, admin_headers, ctx, sup):
    """⚠️  HUJJAT PULI QATOR NARXIDA HARAKAT QILADI, PARTIYA NARXIDA EMAS.

    Kirimda partiyalarning O'Z narxi berilishi mumkin (5×600 + 5×700), hujjat
    qatori esa 10×700 = 7000 deb yozilgan va `Purchase.total` AYNAN shundan
    tug'ilgan. Teskari yozuvni partiya narxida (6500) hisoblash hamma tovar
    qaytarilgan hujjatda 500 so'mlik FANTOM qarz qoldirardi: hujjat yopilmas,
    ta'minotchi balansida 500 osilib qolardi.
    """
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    bal0 = Decimal(str(_sup_row(sup).balance or 0))
    r0 = _commit(client, admin_headers, [_line(pid, 10, 700, [
        {"qty": 5, "batch_number": "ARZON", "unit_cost": 600},
        {"qty": 5, "batch_number": "QIMMAT", "unit_cost": 700}])], supplier=sup)
    assert r0.status_code == 200, r0.text
    det = _pur(client, admin_headers, r0.json()["purchase_id"]).json()
    assert det["total"] == 7000.0, det
    assert Decimal(str(_sup_row(sup).balance or 0)) == bal0 + Decimal("7000.00")
    lots = sorted(det["items"][0]["lots"], key=lambda x: x["unit_cost"])
    assert [l["unit_cost"] for l in lots] == [600.0, 700.0], lots

    r = _correct(client, admin_headers, r0.json()["receiving_id"], [{
        "purchase_item_id": det["items"][0]["id"],
        "reverse": [{"stock_batch_id": lots[0]["id"], "qty": 5},
                    {"stock_batch_id": lots[1]["id"], "qty": 5}]}])
    assert r.status_code == 200, r.text
    assert r.json()["reversed_total"] == 7000.0, "hujjat puli PARTIYA narxida hisoblandi"
    assert r.json()["delta_total"] == -7000.0
    assert r.json()["cancelled"] is True, "to'liq qaytgan hujjat yopilmadi"
    assert Decimal(str(_sup_row(sup).balance or 0)) == bal0, "ta'minotchida FANTOM qarz qoldi"
    # COGS asosi esa O'ZGARMAYDI: harakat tannarxi partiyalar bo'yicha (6500/10).
    mv = [m for m in _movements(pid) if m.ref_type == LC.REF_TYPE]
    assert len(mv) == 1 and Decimal(str(mv[0].unit_cost)) == Decimal("650.00"), mv
    _ok(cid, pid)


def test_SOF_IDENTIFIKATSIYA_tuzatishi_PULNI_QIMIRLATMAYDI(client, admin_headers, ctx, sup):
    """Ayni miqdor, ayni narx — delta AYNAN nol bo'lishi SHART.

    ⚠️  Ilgari ikki tomon IKKI XIL yaxlitlanardi: teskari yozuv
        `lot_writeoff.apply` ichida HALF_EVEN bilan, o'rniga qo'yish esa
        partiyama-partiya HALF_UP bilan. 0.5 × 700.01 = 350.005 da ikkalasi
        ajralib, pul qimirlamaydigan tuzatish ta'minotchi balansini 0.01 ga
        surardi.
    """
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    r0 = _commit(client, admin_headers,
                 [_line(pid, 0.5, 700.01, [{"qty": 0.5, "batch_number": "XATO"}], unit="kg")],
                 supplier=sup)
    assert r0.status_code == 200, r0.text
    det = _pur(client, admin_headers, r0.json()["purchase_id"]).json()
    eski_jami = det["total"]
    bal1 = Decimal(str(_sup_row(sup).balance or 0))

    r = _correct(client, admin_headers, r0.json()["receiving_id"], [{
        "purchase_item_id": det["items"][0]["id"],
        "reverse": [{"stock_batch_id": det["items"][0]["lots"][0]["id"], "qty": 0.5}],
        "replace": [{"qty": 0.5, "batch_number": "TO'G'RI", "unit_cost": 700.01}],
        "unit_cost": 700.01}])
    assert r.status_code == 200, r.text
    assert r.json()["delta_total"] == 0.0, r.text
    assert r.json()["reversed_total"] == r.json()["replaced_total"], r.text
    assert _pur(client, admin_headers, det["id"]).json()["total"] == eski_jami
    assert Decimal(str(_sup_row(sup).balance or 0)) == bal1, "pulsiz tuzatish balansni surdi"
    assert not [x for x in _ledger(sup) if x.ref_type == LC.REF_TYPE
                and str(x.ref_id) == r.json()["correction_id"]], "nol delta defterga yozildi"
    _ok(cid, pid)


def test_TIYINDAN_KICHIK_IKKI_QATOR_TOLIQ_teskari_qilinsa_HUJJAT_YOPILADI(
        client, admin_headers, ctx, sup):
    """⚠️  YAXLITLASH BIR MARTA — HUJJAT JAMI BILAN AYNI NUQTADA.

    `Purchase.total` xom yig'indidan BIR MARTA yaxlitlanadi (0.005 + 0.005 =
    0.01). Teskari yozuvni mahsulotma-mahsulot yaxlitlash ikki tiyindan kichik
    qatorlarni 0.00 ga aylantirib, hamma tovar qaytarilgan hujjatni 0.01 bilan
    TIRIK qoldirardi.
    """
    cid, bid = ctx
    p1 = _new_product(client, admin_headers)
    p2 = _new_product(client, admin_headers)
    for p in (p1, p2):
        assert _enable(client, admin_headers, p).status_code == 200
    r0 = _commit(client, admin_headers,
                 [_line(p1, 0.005, 1, [{"qty": 0.005}], unit="kg"),
                  _line(p2, 0.005, 1, [{"qty": 0.005}], unit="kg")], supplier=sup)
    assert r0.status_code == 200, r0.text
    det = _pur(client, admin_headers, r0.json()["purchase_id"]).json()
    assert det["total"] == 0.01, det

    r = _correct(client, admin_headers, r0.json()["receiving_id"],
                 [{"purchase_item_id": it["id"],
                   "reverse": [{"stock_batch_id": it["lots"][0]["id"], "qty": 0.005}]}
                  for it in det["items"]])
    assert r.status_code == 200, r.text
    assert r.json()["reversed_total"] == 0.01, "mahsulotma-mahsulot yaxlitlash tiyinni yedi"
    assert r.json()["delta_total"] == -0.01
    assert r.json()["cancelled"] is True, "to'liq qaytgan hujjat 0.01 bilan tirik qoldi"
    _ok(cid, p1)
    _ok(cid, p2)


# ══ 16. FIFO O'RNI — O'RNIGA QO'YILGAN KOGORTA NAVBAT OXIRIGA SURILMAYDI ════

def test_ORNIGA_qoyilgan_kogorta_ESKI_received_at_ni_OLADI(client, admin_headers, ctx, sup):
    """⚠️  SOF IDENTIFIKATSIYA TUZATISHI FIFO NAVBATINI O'ZGARTIRMASIN.

    Tovar AYNAN o'sha kuni kelgan; faqat partiya raqami xato yozilgan. Yangi
    kogortaga `received_at = now` qo'yilsa u FIFO/FEFO navbatining OXIRIGA
    tushib, keyingi sotuvlarning tannarxini JIMGINA o'zgartirardi.
    `created_at` esa YOZUV vaqti — u ortga surilmaydi.
    """
    cid, bid = ctx
    d = _doc(client, admin_headers, sup, qty=20, cost=700, batch="XATO-RAQAM")
    eski = _batch_id(d)
    kelgan = datetime.now(timezone.utc) - timedelta(days=30)
    with _db() as db:
        db.get(StockBatch, uuid.UUID(eski)).received_at = kelgan
        db.commit()
    r = _correct(client, admin_headers, d["rec"], [{
        "purchase_item_id": d["item"],
        "reverse": [{"stock_batch_id": eski, "qty": 20}],
        "replace": [{"qty": 20, "batch_number": "TO'G'RI-RAQAM", "unit_cost": 700}],
        "unit_cost": 700}])
    assert r.status_code == 200, r.text
    yangi = [b for b in _lots(d["pid"]) if str(b.id) != eski]
    assert len(yangi) == 1, yangi
    n = yangi[0]
    assert abs((_utc(n.received_at) - kelgan).total_seconds()) < 2, (
        "o'rniga qo'yilgan kogorta FIFO navbatining OXIRIGA surildi")
    assert (_utc(n.created_at) - kelgan).days >= 29, (
        "`created_at` ORTGA surildi — yozuv vaqti soxtalashtirildi")
    _ok(cid, d["pid"])


# ══ 17. NAQD CUSTODY — FAQAT PUL QIMIRLAGANDA ══════════════════════════════

def _cutover(cid, when):
    """Kassa T0 (cutover) ni o'rnatadi yoki olib tashlaydi."""
    from app.models.settings import Setting
    with _db() as db:
        row = (db.query(Setting).filter(Setting.company_id == uuid.UUID(str(cid)),
                                        Setting.key == "cash",
                                        Setting.branch_id.is_(None)).first())
        val = dict((row.value if row is not None else None) or {})
        if when is None:
            val.pop("cutover_at", None)
        else:
            val["cutover_at"] = when.isoformat()
        if row is None:
            db.add(Setting(company_id=uuid.UUID(str(cid)), branch_id=None, key="cash",
                           value=val))
        else:
            row.value = val
        db.commit()


def test_PUL_QIMIRLAMASA_KASSA_hisobi_SORALMAYDI(client, admin_headers, ctx, sup):
    """⚠️  CUSTODY `delta_total` MA'LUM BO'LGANDAN KEYIN so'raladi.

    T0 (cutover) o'tgan, smenasiz omborchi naqd hujjatdagi PARTIYA RAQAMINI
    tuzatmoqchi — pul umuman qimirlamaydi. Ilgari custody HAR naqd hujjat
    uchun, delta hisoblanishidan OLDIN so'ralardi va so'rov 400
    (CUSTODY_REQUIRED) bilan yopilardi; Manager esa `cash_account_id`
    YUBORMAYDI, ya'ni qayta urinishning YO'LI yo'q edi.

    Ikkinchi yarmi — MANFIY NAZORAT: pul HAQIQATAN qimirlaganda darvoza HAMON
    yopiq, aks holda tuzatish kassa oyog'ini custody'siz yozib yuborardi.
    """
    cid, bid = ctx
    h = _staff(client, admin_headers, "omborchi")
    d = _doc(client, admin_headers, sup, qty=10, cost=700, payment="cash", batch="T0")
    d2 = _doc(client, admin_headers, sup, qty=10, cost=700, payment="cash", batch="T0-2")
    _cutover(cid, datetime.now(timezone.utc) - timedelta(hours=1))
    try:
        r = _correct(client, h, d["rec"], [{
            "purchase_item_id": d["item"],
            "reverse": [{"stock_batch_id": _batch_id(d), "qty": 10}],
            "replace": [{"qty": 10, "batch_number": "TO'G'RI", "unit_cost": 700}],
            "unit_cost": 700}])
        assert r.status_code == 200, r.text
        assert r.json()["delta_total"] == 0.0, r.text

        r2 = _correct(client, h, d2["rec"], [_rev(d2["item"], _batch_id(d2), 4)])
        assert r2.status_code == 400, r2.text
        assert "cash_account_id" in r2.json()["detail"], r2.text
        assert _inv_qty(d2["pid"], bid) == Decimal("10.000"), "rad etilgan tuzatish qoldiqni surdi"
        assert not _corrections(d2["pur"]), "rad etilgan tuzatish SARLAVHA qoldirdi"
    finally:
        _cutover(cid, None)
    _ok(cid, d["pid"])
    _ok(cid, d2["pid"])


# ══ 18. TA'MINOTCHI HISOBOTI — BITTA MANBA ═════════════════════════════════

def test_TAMINOTCHI_hisoboti_TUZATISHDAN_KEYIN_BIR_XIL_RAQAM(client, admin_headers,
                                                              ctx, sup):
    """⚠️  IKKI MANBA — IKKI XIL RAQAM.

    Hujjat jami `Purchase.total` dan, mahsulot ustuni esa `purchase_items` dan
    olinardi. Tuzatish `purchase_items` ga ATAYLAB tegmaydi (ular «aslida nima
    yozilgan» ning yozuvi) — natijada bitta ekranda 5600 va 7000 birga turardi
    va marja YOLG'ON chiqardi.
    """
    cid, bid = ctx
    s2 = client.post("/api/v1/suppliers", headers=admin_headers,
                     json={"name": "Hisobot ta'minotchisi " + uuid.uuid4().hex[:6]})
    assert s2.status_code == 200, s2.text
    sid = s2.json()["id"]
    d = _doc(client, admin_headers, sid, qty=10, cost=700, batch="HISOBOT")

    rep = client.get(f"/api/v1/suppliers/{sid}", headers=admin_headers).json()
    assert rep["total_purchased"] == 7000.0, rep
    assert [p["cost"] for p in rep["products"]] == [7000.0], rep["products"]

    r = _correct(client, admin_headers, d["rec"], [_rev(d["item"], _batch_id(d), 2)])
    assert r.status_code == 200, r.text
    rep2 = client.get(f"/api/v1/suppliers/{sid}", headers=admin_headers).json()
    assert rep2["total_purchased"] == 5600.0, rep2
    assert [p["cost"] for p in rep2["products"]] == [5600.0], rep2["products"]
    assert rep2["total_purchased"] == sum(p["cost"] for p in rep2["products"])
    assert _pur(client, admin_headers, d["pur"]).json()["total"] == 5600.0
    _ok(cid, d["pid"])
