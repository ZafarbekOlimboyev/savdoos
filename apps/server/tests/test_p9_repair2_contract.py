# -*- coding: utf-8 -*-
"""P9 KRITIK TUZATISH 2 — IDEMPOTENTLIK KALITINING EGALIGI (P9-03).

KONTRAKT
  `client_uuid` amalni IDENTIFIKATSIYA qiladi; u amalning MAZMUNINI o'zgartirish
  yoki BOSHQA kassirning natijasini olish huquqini BERMAYDI.

  · ayni tenant + ayni kassir + ayni mantiqiy chek + ayni kalit -> TAKROR (mavjud chek)
  · boshqa kassir + ayni kalit                                  -> RAD, A ning cheki BERILMAYDI
  · boshqa tenant + ayni kalit                                  -> TO'QNASHUV YO'Q
  · ayni kassir + ayni kalit, MODDIY boshqa payload             -> RAD (jimgina qabul EMAS)

  Rad: HTTP 400 + `IDEMPOTENCY_KEY_REUSED`. `/sync/push` da `retry:false` —
  dead-letter, chunki kalit abadiy band va qayta urinish HECH QACHON o'tmaydi.

Naqsh manbai — mavjud, ratifikatsiya qilingan `cashops.replay_answer` +
`custody_preview.cash_movement_matches`.
"""
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_mobile_parity import _db, _product, _shop, _staff

PUSH = "/api/v1/sync/push"
SALES = "/api/v1/sales"
CODE = "IDEMPOTENCY_KEY_REUSED"


def _kassir(d, *, filiallar=None):
    return _staff(d, "kassir", filiallar=filiallar or (d["bids"][0],))


def _rec(pid, *, cu, qty=1, price=100, method="cash", sold_at=None, payments=None):
    r = {"client_uuid": str(cu), "payment_method": method,
         "given_amount": float(qty) * price,
         "items": [{"product_id": str(pid), "qty": qty, "unit_price": price}]}
    if sold_at is not None:
        r["sold_at"] = sold_at.isoformat()
    if payments is not None:
        r["payments"] = payments
    return r


def _push(client, H, rec):
    r = client.post(PUSH, headers=H, json={"sales": [rec]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def _sales(cid):
    from app.models.sales import Sale
    with _db() as db:
        return db.query(Sale).filter(Sale.company_id == cid).all()


def _inv(pid, bid):
    from app.models.inventory import Inventory
    with _db() as db:
        r = db.query(Inventory).filter(
            Inventory.product_id == pid, Inventory.branch_id == bid).first()
        return float(r.qty) if r else None


def _reassign(eid, bid):
    from app.models.auth import EmployeeBranch
    with _db() as db:
        db.query(EmployeeBranch).filter(EmployeeBranch.employee_id == eid).delete()
        db.add(EmployeeBranch(employee_id=eid, branch_id=bid))
        db.commit()


# ══ 1. QONUNIY TAKROR — TEGILMAYDI ═══════════════════════════════════════════

def test_r1_ayni_kassir_ayni_payload_TAKROR(client):
    """Javob yo'qolgan -> qayta yuborish. BITTA chek, BITTA chiqim."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    rec = _rec(p["id"], cu=uuid.uuid4())
    a = _push(client, H, rec)
    b = _push(client, H, rec)
    assert a["ok"] is True and b["ok"] is True
    assert a["id"] == b["id"]
    assert len(_sales(d["cid"])) == 1
    assert _inv(p["id"], d["bids"][0]) == 9.0


def test_r2_sold_at_MODDIY_EMAS(client):
    """Klient `sold_at` ni flush paytida qo'yadi — u chekni O'ZGARTIRMAYDI."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    cu = uuid.uuid4()
    now = datetime.now(timezone.utc)
    a = _push(client, H, _rec(p["id"], cu=cu, sold_at=now - timedelta(minutes=5)))
    b = _push(client, H, _rec(p["id"], cu=cu, sold_at=now - timedelta(days=2)))
    assert a["ok"] is True and b["ok"] is True and a["id"] == b["id"]
    assert len(_sales(d["cid"])) == 1


# ══ 2. BOSHQA KASSIR — RAD ═══════════════════════════════════════════════════

def test_r3_boshqa_kassir_ayni_kalit_RAD_va_A_ning_cheki_BERILMAYDI(client):
    """P9-03 NING YADROSI."""
    d = _shop()
    HA, _ = _kassir(d)
    HB, _ = _kassir(d)
    p1 = _product(d, qty=10)
    p2 = _product(d, qty=10)
    X = uuid.uuid4()
    a = _push(client, HA, _rec(p1["id"], cu=X))
    assert a["ok"] is True
    b = _push(client, HB, _rec(p2["id"], cu=X, qty=3, price=200))

    assert b["ok"] is False, f"B ning cheki JIMGINA yutildi: {b}"
    assert b["retry"] is False, "kalit abadiy band — cheksiz retry bo'lmasin"
    assert b["code"] == CODE
    assert b.get("id") is None, "B ga A ning chek id'si berildi"
    assert len(_sales(d["cid"])) == 1
    assert _inv(p2["id"], d["bids"][0]) == 10.0, "rad etilgan chek qoldiqni o'zgartirdi"


def test_r4_boshqa_kassir_AYNI_payload_bilan_ham_RAD(client):
    """Payload bir xil bo'lsa ham, kalit BOSHQA kassirniki — takror emas."""
    d = _shop()
    HA, _ = _kassir(d)
    HB, _ = _kassir(d)
    p = _product(d, qty=10)
    X = uuid.uuid4()
    assert _push(client, HA, _rec(p["id"], cu=X))["ok"] is True
    b = _push(client, HB, _rec(p["id"], cu=X))
    assert (b["ok"], b["code"]) == (False, CODE), b
    assert _inv(p["id"], d["bids"][0]) == 9.0, "faqat A ning chiqimi bo'lishi kerak"


def test_r5_ONLAYN_yolda_ham_RAD(client):
    """`/sales` da ham ayni kontrakt — 400, A ning cheki qaytarilmaydi."""
    d = _shop()
    HA, _ = _kassir(d)
    HB, _ = _kassir(d)
    p = _product(d, qty=10)
    X = str(uuid.uuid4())
    body = {"client_uuid": X, "payment_method": "cash", "given_amount": 100,
            "items": [{"product_id": str(p["id"]), "qty": 1, "unit_price": 100}]}
    rA = client.post(SALES, headers=HA, json=body)
    assert rA.status_code == 200, rA.text
    rB = client.post(SALES, headers=HB, json=body)
    assert rB.status_code == 400, rB.text
    assert rB.headers.get("X-Error-Code") == CODE, dict(rB.headers)
    assert len(_sales(d["cid"])) == 1


# ══ 3. TENANTLARARO — TO'QNASHUV YO'Q ════════════════════════════════════════

def test_r6_boshqa_tenant_ayni_kalit_TOQNASHMAYDI(client):
    d1, d2 = _shop(), _shop()
    H1, _ = _kassir(d1)
    H2, _ = _kassir(d2)
    q1 = _product(d1, qty=10)
    q2 = _product(d2, qty=10)
    X = uuid.uuid4()
    a = _push(client, H1, _rec(q1["id"], cu=X))
    b = _push(client, H2, _rec(q2["id"], cu=X, qty=3, price=200))
    assert a["ok"] is True and b["ok"] is True, (a, b)
    assert a["id"] != b["id"]
    assert _inv(q1["id"], d1["bids"][0]) == 9.0
    assert _inv(q2["id"], d2["bids"][0]) == 7.0


# ══ 4. MODDIY FARQ — FAIL CLOSED ═════════════════════════════════════════════

def test_r7_ayni_kassir_BOSHQA_savat_RAD(client):
    d = _shop()
    H, _ = _kassir(d)
    p1 = _product(d, qty=10)
    p2 = _product(d, qty=10)
    X = uuid.uuid4()
    assert _push(client, H, _rec(p1["id"], cu=X))["ok"] is True
    b = _push(client, H, _rec(p2["id"], cu=X))
    assert (b["ok"], b["code"]) == (False, CODE), b
    assert _inv(p2["id"], d["bids"][0]) == 10.0


def test_r8_ayni_kassir_BOSHQA_miqdor_RAD(client):
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    X = uuid.uuid4()
    assert _push(client, H, _rec(p["id"], cu=X, qty=1))["ok"] is True
    b = _push(client, H, _rec(p["id"], cu=X, qty=4))
    assert (b["ok"], b["code"]) == (False, CODE), b
    assert _inv(p["id"], d["bids"][0]) == 9.0, "faqat birinchi chiqim"


def test_r9_ayni_kassir_BOSHQA_tolov_usuli_RAD(client):
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    X = uuid.uuid4()
    assert _push(client, H, _rec(p["id"], cu=X, method="cash"))["ok"] is True
    b = _push(client, H, _rec(p["id"], cu=X, method="card"))
    assert (b["ok"], b["code"]) == (False, CODE), b


def test_r10_offline_replayda_BOSHQA_NARX_RAD(client):
    """Offline replay'da narx PAYLOAD'dan olinadi — ya'ni jami payload'dan
    deterministik. Savat bir xil, narx boshqa bo'lsa bu BOSHQA pul."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    X = uuid.uuid4()
    assert _push(client, H, _rec(p["id"], cu=X, price=100))["ok"] is True
    b = _push(client, H, _rec(p["id"], cu=X, price=250))
    assert (b["ok"], b["code"]) == (False, CODE), b
    assert _inv(p["id"], d["bids"][0]) == 9.0


# ══ 5. FILIAL — CUSTODY CHEGARASI KESILMAYDI ═════════════════════════════════

def test_r11_kassir_boshqa_filialga_otsa_takror_YANGI_yozuv_YARATMAYDI(client):
    """Kalit ayni, kassir ayni, savat ayni — lekin kassir endi B filialida.

    KONTRAKT: bu TAKROR (kalit ayni mantiqiy chekni ko'rsatadi) — mavjud chek
    qaytariladi va YANGI filialda HECH NARSA yozilmaydi, ya'ni custody chegarasi
    KESILMAYDI. Filial ATAYLAB moddiy maydon EMAS: offline chek soatlab navbatda
    turib, kassir boshqa filialga o'tkazilgandan keyin flush bo'lishi mumkin —
    uni rad etsak qonuniy chek yo'qolardi."""
    from app.models.sales import Sale
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    H, eid = _kassir(d, filiallar=(A,))
    pA = _product(d, qty=10, bid=A)
    _product(d, qty=10, bid=B)                      # B filialida ham qoldiq bor
    X = uuid.uuid4()
    first = _push(client, H, _rec(pA["id"], cu=X))
    assert first["ok"] is True

    _reassign(eid, B)
    again = _push(client, H, _rec(pA["id"], cu=X))
    assert again["ok"] is True and again["id"] == first["id"]
    assert len(_sales(d["cid"])) == 1, "ikkinchi filialda YANGI chek yozildi"
    with _db() as db:
        assert db.query(Sale).filter(Sale.client_uuid == X).one().branch_id == A
    assert _inv(pA["id"], A) == 9.0
    assert _inv(pA["id"], B) is None, "B filialida qoldiq harakati paydo bo'ldi"


# ══ 6. KETMA-KET TAKRORIY YETKAZIB BERISH ════════════════════════════════════

def test_r12_bitta_sorovda_IKKI_MARTA_kelgan_ayni_chek(client):
    """Bitta `/sync/push` tanasida ayni kalit ikki marta — ikkinchisi takror."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    rec = _rec(p["id"], cu=uuid.uuid4())
    r = client.post(PUSH, headers=H, json={"sales": [rec, dict(rec)]})
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert res[0]["ok"] is True and res[1]["ok"] is True
    assert res[0]["id"] == res[1]["id"]
    assert len(_sales(d["cid"])) == 1
    assert _inv(p["id"], d["bids"][0]) == 9.0


def test_r13_bitta_sorovda_ayni_kalit_BOSHQA_tana(client):
    """Bitta tanada ayni kalit, lekin ikkinchisi moddiy boshqa — ikkinchisi RAD."""
    d = _shop()
    H, _ = _kassir(d)
    p1 = _product(d, qty=10)
    p2 = _product(d, qty=10)
    X = uuid.uuid4()
    r = client.post(PUSH, headers=H, json={"sales": [
        _rec(p1["id"], cu=X), _rec(p2["id"], cu=X)]})
    res = r.json()["results"]
    assert res[0]["ok"] is True
    assert (res[1]["ok"], res[1]["code"]) == (False, CODE), res[1]
    assert len(_sales(d["cid"])) == 1
    assert _inv(p2["id"], d["bids"][0]) == 10.0
