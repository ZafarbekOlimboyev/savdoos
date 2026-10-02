# -*- coding: utf-8 -*-
"""P9 KRITIK TUZATISH 3 — KO'CHIRISH KALITINING IJARACHI DOIRASI (P9-04).

KONTRAKT
  `client_uuid` ko'chirishni FAQAT O'Z ijarachisi ichida identifikatsiya qiladi va
  amalning MAZMUNINI o'zgartirish huquqini bermaydi.

  · ayni ijarachi + ayni kalit + ayni mantiqiy ko'chirish -> TAKROR (`duplicate:true`)
  · boshqa ijarachi + ayni kalit                          -> MUTLAQO alohida ko'chirish
  · ayni ijarachi + ayni kalit + moddiy boshqa            -> 409, hech narsa yozilmaydi
  · manba / maqsad / tarkib / miqdor farqi                -> konflikt

⚠️  BAZA KALITI O'ZGARMAGAN: `ux_stockmov_client_prod_type`
    `(client_uuid, product_id, type) WHERE client_uuid IS NOT NULL`. U `product_id`
    orqali allaqachon ijarachi bo'yicha ajratadi (mahsulot bitta kompaniyaniki).
    Nuqson FAQAT ilova qidiruvida edi — migratsiya KERAK EMAS.
"""
import uuid

from tests.test_mobile_parity import _db, _product, _shop

TRANSFER = "/api/v1/inventory/transfer"
CODE = "IDEMPOTENCY_KEY_REUSED"


def _inv(pid, bid):
    from app.models.inventory import Inventory
    with _db() as db:
        r = db.query(Inventory).filter(
            Inventory.product_id == pid, Inventory.branch_id == bid).first()
        return float(r.qty) if r else None


def _moves(cid, typ=None):
    """Shu kompaniyaning zaxira harakatlari — buxgalteriya/audit izi."""
    from app.models.inventory import StockMovement
    from app.models.org import Branch
    with _db() as db:
        q = (db.query(StockMovement)
             .join(Branch, Branch.id == StockMovement.branch_id)
             .filter(Branch.company_id == cid))
        if typ is not None:
            q = q.filter(StockMovement.type == typ)
        return q.all()


def _xfer(client, H, *, cu, frm, to, pid, qty):
    return client.post(TRANSFER, headers=H, json={
        "client_uuid": str(cu), "from_branch_id": str(frm), "to_branch_id": str(to),
        "items": [{"product_id": str(pid), "qty": qty}]})


# ══ 1. QONUNIY TAKROR ════════════════════════════════════════════════════════

def test_t1_ayni_ijarachi_ayni_kochirish_TAKROR(client):
    """Javob yo'qolgan -> qayta yuborish. Qoldiq BIR MARTA siljiydi."""
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    p = _product(d, qty=10, bid=A)
    X = uuid.uuid4()
    r1 = _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=3)
    r2 = _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=3)
    assert r1.status_code == 200 and not r1.json().get("duplicate"), r1.text
    assert r2.status_code == 200 and r2.json().get("duplicate") is True, r2.text
    assert _inv(p["id"], A) == 7.0 and _inv(p["id"], B) == 3.0


def test_t2_stok_va_audit_izi_ANIQ_BIR_MARTA(client):
    """Uch marta yuborilsa ham: 1 chiqim + 1 kirim qatori, qoldiq bir marta."""
    from app.models.enums import MovementType
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    p = _product(d, qty=10, bid=A)
    X = uuid.uuid4()
    for _ in range(3):
        assert _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=2).status_code == 200
    assert len(_moves(d["cid"], MovementType.transfer_out)) == 1
    assert len(_moves(d["cid"], MovementType.transfer_in)) == 1
    assert _inv(p["id"], A) == 8.0 and _inv(p["id"], B) == 2.0


# ══ 2. IJARACHILARARO — MUTLAQO ALOHIDA ══════════════════════════════════════

def test_t3_boshqa_ijarachi_ayni_kalit_ALOHIDA_kochirish(client):
    """P9-04 NING YADROSI: B ning haqiqiy ko'chirishi A ning kaliti sabab
    yutilmasin."""
    dA = _shop(filiallar=2)
    dB = _shop(filiallar=2)
    A1, A2 = dA["bids"][0], dA["bids"][1]
    B1, B2 = dB["bids"][0], dB["bids"][1]
    pA = _product(dA, qty=10, bid=A1)
    pB = _product(dB, qty=10, bid=B1)
    X = uuid.uuid4()

    rA = _xfer(client, dA["H"], cu=X, frm=A1, to=A2, pid=pA["id"], qty=2)
    assert rA.status_code == 200 and not rA.json().get("duplicate")
    rB = _xfer(client, dB["H"], cu=X, frm=B1, to=B2, pid=pB["id"], qty=5)

    assert rB.status_code == 200, rB.text
    assert not rB.json().get("duplicate"), f"B ning ko'chirishi YUTILDI: {rB.json()}"
    assert _inv(pB["id"], B1) == 5.0, "B manbadan chiqmadi"
    assert _inv(pB["id"], B2) == 5.0, "B maqsadga tushmadi"
    # A ning ko'chirishi ham tegilmagan.
    assert _inv(pA["id"], A1) == 8.0 and _inv(pA["id"], A2) == 2.0


def test_t4_ikkala_ijarachi_ham_OZ_audit_iziga_ega(client):
    from app.models.enums import MovementType
    dA, dB = _shop(filiallar=2), _shop(filiallar=2)
    pA = _product(dA, qty=10, bid=dA["bids"][0])
    pB = _product(dB, qty=10, bid=dB["bids"][0])
    X = uuid.uuid4()
    _xfer(client, dA["H"], cu=X, frm=dA["bids"][0], to=dA["bids"][1], pid=pA["id"], qty=1)
    _xfer(client, dB["H"], cu=X, frm=dB["bids"][0], to=dB["bids"][1], pid=pB["id"], qty=1)
    for d in (dA, dB):
        assert len(_moves(d["cid"], MovementType.transfer_out)) == 1
        assert len(_moves(d["cid"], MovementType.transfer_in)) == 1


# ══ 3. MODDIY FARQ — FAIL CLOSED ═════════════════════════════════════════════

def test_t5_ayni_kalit_BOSHQA_miqdor_KONFLIKT(client):
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    p = _product(d, qty=10, bid=A)
    X = uuid.uuid4()
    assert _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=1).status_code == 200
    r = _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=7)
    assert r.status_code == 409, r.text
    assert r.headers.get("X-Error-Code") == CODE, dict(r.headers)
    assert _inv(p["id"], A) == 9.0 and _inv(p["id"], B) == 1.0, "konflikt qoldiqni o'zgartirdi"


def test_t6_ayni_kalit_BOSHQA_mahsulot_KONFLIKT(client):
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    p1 = _product(d, qty=10, bid=A)
    p2 = _product(d, qty=10, bid=A)
    X = uuid.uuid4()
    assert _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p1["id"], qty=1).status_code == 200
    r = _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p2["id"], qty=1)
    assert (r.status_code, r.headers.get("X-Error-Code")) == (409, CODE), r.text
    assert _inv(p2["id"], A) == 10.0


def test_t7_ayni_kalit_BOSHQA_MANBA_KONFLIKT(client):
    d = _shop(filiallar=3)
    A, B, C = d["bids"][0], d["bids"][1], d["bids"][2]
    p = _product(d, qty=10, bid=A)
    _product(d, qty=10, bid=C)
    X = uuid.uuid4()
    assert _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=1).status_code == 200
    # Ayni mahsulot, ayni miqdor — lekin BOSHQA filialdan.
    from app.models.inventory import Inventory
    with _db() as db:
        db.add(Inventory(product_id=p["id"], branch_id=C, qty=5, min_qty=0,
                         updated_at=__import__("datetime").datetime.now(
                             __import__("datetime").timezone.utc)))
        db.commit()
    r = _xfer(client, d["H"], cu=X, frm=C, to=B, pid=p["id"], qty=1)
    assert (r.status_code, r.headers.get("X-Error-Code")) == (409, CODE), r.text
    assert _inv(p["id"], C) == 5.0, "konflikt C filialining qoldig'ini o'zgartirdi"


def test_t8_ayni_kalit_BOSHQA_MAQSAD_KONFLIKT(client):
    """Manba, mahsulot va miqdor bir xil — faqat MAQSAD boshqa.

    Bu tekshiruv kirim oyog'i ham `client_uuid` olgani uchun mumkin (P9-04)."""
    d = _shop(filiallar=3)
    A, B, C = d["bids"][0], d["bids"][1], d["bids"][2]
    p = _product(d, qty=10, bid=A)
    X = uuid.uuid4()
    assert _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=2).status_code == 200
    r = _xfer(client, d["H"], cu=X, frm=A, to=C, pid=p["id"], qty=2)
    assert (r.status_code, r.headers.get("X-Error-Code")) == (409, CODE), r.text
    assert _inv(p["id"], C) is None, "C filialiga jimgina tovar tushdi"
    assert _inv(p["id"], A) == 8.0 and _inv(p["id"], B) == 2.0


def test_t9_kirim_oyogi_KALITNI_oladi(client):
    """Maqsadni tekshirish shunga tayanadi — qulflaymiz."""
    from app.models.enums import MovementType
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    p = _product(d, qty=10, bid=A)
    X = uuid.uuid4()
    assert _xfer(client, d["H"], cu=X, frm=A, to=B, pid=p["id"], qty=1).status_code == 200
    ins = _moves(d["cid"], MovementType.transfer_in)
    assert len(ins) == 1 and str(ins[0].client_uuid) == str(X)
    assert ins[0].branch_id == B


# ══ 4. KALITSIZ KO'CHIRISH — XULQ O'ZGARMAYDI ════════════════════════════════

def test_t10_kalitsiz_kochirish_avvalgidek_ishlaydi(client):
    """`client_uuid` ixtiyoriy bo'lib qoladi — bu tuzatish uni majburiy qilmaydi."""
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    p = _product(d, qty=10, bid=A)
    r = client.post(TRANSFER, headers=d["H"], json={
        "from_branch_id": str(A), "to_branch_id": str(B),
        "items": [{"product_id": str(p["id"]), "qty": 4}]})
    assert r.status_code == 200, r.text
    assert _inv(p["id"], A) == 6.0 and _inv(p["id"], B) == 4.0


# ══ 5. KO'P MAHSULOTLI KO'CHIRISH ════════════════════════════════════════════

def test_t11_kop_mahsulotli_takror_va_konflikt(client):
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    p1 = _product(d, qty=10, bid=A)
    p2 = _product(d, qty=10, bid=A)
    X = uuid.uuid4()
    body = {"client_uuid": str(X), "from_branch_id": str(A), "to_branch_id": str(B),
            "items": [{"product_id": str(p1["id"]), "qty": 2},
                      {"product_id": str(p2["id"]), "qty": 3}]}
    assert client.post(TRANSFER, headers=d["H"], json=body).status_code == 200
    # AYNI tarkib -> takror
    r = client.post(TRANSFER, headers=d["H"], json=body)
    assert r.status_code == 200 and r.json().get("duplicate") is True, r.text
    # Bitta qator olib tashlansa -> tarkib boshqa -> konflikt
    body2 = dict(body, items=[{"product_id": str(p1["id"]), "qty": 2}])
    r2 = client.post(TRANSFER, headers=d["H"], json=body2)
    assert (r2.status_code, r2.headers.get("X-Error-Code")) == (409, CODE), r2.text
    assert _inv(p1["id"], A) == 8.0 and _inv(p2["id"], A) == 7.0
