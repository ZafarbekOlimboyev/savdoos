# -*- coding: utf-8 -*-
"""CH-15B FAZA A.3 (D12 Option B) — QABUL HUJJATI SURATI XARID TAHRIRIDA O'ZGARMAYDI.

QOIDA. `PATCH /purchases/{id}` (`edit_purchase`) bog'langan `Receiving` ning
`final_items`, `total_types` va `total_qty` maydonlariga TEGMAYDI. Ular operator
TASDIQLAGAN qabul LAHZASINING surati; tuzatish esa alohida, joriy yozuvlarda
ko'rinadi (`PurchaseItem`, `Purchase.total`, `Inventory`, `StockBatch`,
`ReceivingCorrection`).

⚠️  NEGA BU QAYTARIB BO'LMAYDIGAN ZARAR EDI. Olib tashlangan kod `name` ni JORIY
    katalogdan o'qirdi (`p.name`). Mahsulot qayta nomlangandan keyin PATCH qilinsa,
    qabul paytidagi nom BUTUNLAY yo'qolardi. `StockMovement` da `name` ham, `unit`
    ham ustun sifatida YO'Q, `qty`/`unit_cost` esa `Numeric(14,3)`/`(14,2)` ga
    yaxlitlanadi — demak bu TO'RT fakt uchun `final_items` YAGONA nusxa edi.
    `test_MAHSULOT_QAYTA_NOMLANSA_asl_nom_QOLADI` aynan shu holatni o'lchaydi.

⚠️  BU YANGI SIYOSAT EMAS. `purchases.py` dagi `_lock_guard` izohi xavfni AYNAN
    shunday ta'riflaydi («eski tahrir yo'li hujjat jamini qatorlardan QAYTA
    hisoblab, tuzatishni jimgina teskari qilardi»), va `lot_correction.py:1186-1188`
    bilan `RECEIVING_CORRECTION.md:54` `final_items` ni «qayta yozilmaydi» deb
    e'lon qiladi. TUZATISH yo'li (`POST /receiving/{id}/corrections`) unga
    allaqachon tegmaydi — bu o'zgarish ikki yo'lni IZCHIL qiladi.

DOIRA (ega ko'rsatmasi): bu `PurchaseItem` ni O'ZGARMAS QILMAYDI. `purchases.py`
hamon qatorni hard delete qiladi va joyida tahrirlaydi — alohida hisob-tarixi
masalasi.

⚠️  `payment="credit"` ATAYLAB: naqd xaridda PATCH fizik kassa hisobini talab
    qiladi va smenasiz FAIL-CLOSED bo'ladi — bu test hisob semantikasini emas,
    HUJJAT SURATINI o'lchaydi.
"""
from __future__ import annotations

import json
import uuid

from tests.test_mobile_parity import _db, _product, _shop


def _qabul(client, d, pid, *, qty=10, cost=700, lots=None):
    """Bitta qatorli QARZ qabuli. `lots` — KUZATUVLI mahsulot uchun MAJBURIY
    (`lots` bermasa server 400 beradi: «miqdor taxmin qilinmaydi»)."""
    qator = {"product_id": str(pid), "qty": qty, "unit_cost": cost, "unit": "dona"}
    if lots is not None:
        qator["lots"] = lots
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [qator],
        "supplier_id": str(d["sup"]), "payment": "credit", "source": "ai",
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    j = r.json()
    det = client.get(f"/api/v1/purchases/{j['purchase_id']}", headers=d["H"])
    assert det.status_code == 200, det.text
    return {"rec": j["receiving_id"], "pur": j["purchase_id"],
            "item": det.json()["items"][0]["id"]}


def _surat(rid):
    """`receivings` qatorining SURAT maydonlari — bayt-aniq solishtirish uchun."""
    from app.models.receiving import Receiving
    with _db() as db:
        r = db.get(Receiving, uuid.UUID(str(rid)))
        assert r is not None
        return json.dumps({"final_items": r.final_items,
                           "total_types": r.total_types,
                           "total_qty": str(r.total_qty)}, sort_keys=True, default=str)


def _patch(client, d, doc, *, qty, cost=700):
    return client.patch(f"/api/v1/purchases/{doc['pur']}", headers=d["H"],
                        json={"items": [{"id": doc["item"], "qty": qty, "unit_cost": cost}],
                              "client_uuid": str(uuid.uuid4())})


# ══ 1. SURAT PATCH DAN KEYIN O'ZGARMAYDI ════════════════════════════════════

def test_SURAT_PATCH_dan_KEYIN_BAYT_ANIQ_OZGARMAYDI(client):
    d = _shop()
    p = _product(d, name="D12 mahsulot", qty=0)
    doc = _qabul(client, d, p["id"], qty=10, cost=700)
    oldin = _surat(doc["rec"])

    r = _patch(client, d, doc, qty=4)

    assert r.status_code == 200, r.text
    assert _surat(doc["rec"]) == oldin, "PATCH qabul suratini O'ZGARTIRDI"


def test_MAHSULOT_QAYTA_NOMLANSA_asl_nom_QOLADI(client):
    """⚠️  ENG MUHIM BAND — qaytarib bo'lmaydigan yo'qotish aynan shu holatda edi."""
    from app.models.catalog import Product

    d = _shop()
    asl_nom = "ASL-NOM-" + uuid.uuid4().hex[:8]
    p = _product(d, name=asl_nom, qty=0)
    doc = _qabul(client, d, p["id"], qty=10, cost=700)

    yangi_nom = "QAYTA-NOMLANGAN-" + uuid.uuid4().hex[:8]
    with _db() as db:
        prod = db.get(Product, uuid.UUID(str(p["id"])))
        prod.name = yangi_nom
        db.commit()

    assert _patch(client, d, doc, qty=4).status_code == 200

    from app.models.receiving import Receiving
    with _db() as db:
        fi = db.get(Receiving, uuid.UUID(doc["rec"])).final_items
    assert fi[0]["name"] == asl_nom, \
        f"qabul paytidagi nom YO'QOLDI: {fi[0]['name']!r} (kutilgan {asl_nom!r})"
    assert yangi_nom not in json.dumps(fi), "joriy katalog nomi hujjatga yozildi"


def test_SURAT_birlik_miqdor_tannarx_va_QATOR_SONI_QOLADI(client):
    d = _shop()
    p = _product(d, name="D12 kg mahsulot", qty=0, weighted=True)   # birlik = kg
    doc = _qabul(client, d, p["id"], qty=10, cost=700)

    assert _patch(client, d, doc, qty=3, cost=555).status_code == 200

    from app.models.receiving import Receiving
    with _db() as db:
        r = db.get(Receiving, uuid.UUID(doc["rec"]))
        fi = r.final_items
        assert len(fi) == 1 and r.total_types == 1, (len(fi), r.total_types)
        assert float(r.total_qty) == 10.0, f"asl jami miqdor o'zgardi: {r.total_qty}"
        assert float(fi[0]["qty"]) == 10.0, fi[0]["qty"]
        assert float(fi[0]["unit_cost"]) == 700.0, fi[0]["unit_cost"]
        assert fi[0]["unit"] == "kg", fi[0]["unit"]


# ══ 2. TUZATISH JORIY YOZUVLARNI HAMON YANGILAYDI ═══════════════════════════

def test_TUZATISH_joriy_biznes_yozuvlarini_YANGILAYDI(client):
    """Option B tuzatish funksiyasini O'CHIRMAYDI — joriy qiymatlar yangilanadi."""
    from app.models.purchasing import Purchase, PurchaseItem

    d = _shop()
    p = _product(d, name="D12 mahsulot", qty=0)
    doc = _qabul(client, d, p["id"], qty=10, cost=700)

    assert _patch(client, d, doc, qty=4, cost=700).status_code == 200

    with _db() as db:
        pur = db.get(Purchase, uuid.UUID(doc["pur"]))
        assert float(pur.total) == 2800.0, f"xarid jami yangilanmadi: {pur.total}"
        it = db.get(PurchaseItem, uuid.UUID(doc["item"]))
        assert float(it.qty) == 4.0, f"qator miqdori yangilanmadi: {it.qty}"
    # API o'quvchisi ham JORIY qiymatni ko'radi
    j = client.get(f"/api/v1/purchases/{doc['pur']}", headers=d["H"]).json()
    assert float(j["total"]) == 2800.0, j["total"]
    assert float(j["items"][0]["qty"]) == 4.0, j["items"][0]


def test_KOMPENSATSIYA_StockMovement_va_QOLDIQ_TOGRI(client):
    """Append-only kompensatsiya: asl kirim qatori QOLADI, tuzatish YANGI qator QO'SHADI."""
    from app.models.inventory import Inventory, StockMovement

    d = _shop()
    p = _product(d, name="D12 mahsulot", qty=0)
    doc = _qabul(client, d, p["id"], qty=10, cost=700)
    pid = uuid.UUID(str(p["id"]))
    with _db() as db:
        oldin = db.query(StockMovement).filter(StockMovement.product_id == pid).count()

    assert _patch(client, d, doc, qty=4, cost=700).status_code == 200

    with _db() as db:
        mvs = db.query(StockMovement).filter(StockMovement.product_id == pid).all()
        assert len(mvs) > oldin, "kompensatsiya harakati QO'SHILMADI"
        # ASL kirim qatori (10 dona) hamon joyida — append-only
        assert any(float(m.qty) == 10.0 for m in mvs), \
            f"asl kirim harakati o'zgardi/yo'qoldi: {[float(m.qty) for m in mvs]}"
        # Qoldiq: 10 kirim, keyin 6 ga kamaytirildi -> 4
        inv = db.query(Inventory).filter(Inventory.product_id == pid).first()
        assert float(inv.qty) == 4.0, f"qoldiq noto'g'ri: {inv.qty}"


def test_StockBatch_received_qty_TEGILMAGAN(client):
    """`StockBatch.received_qty` — asl kelgan miqdor dalili, qayta yozilmaydi."""
    from app.models.inventory import StockBatch

    d = _shop()
    p = _product(d, name="D12 partiyali", qty=0, tracked=True, lots=[0])
    pid = uuid.UUID(str(p["id"]))
    doc = _qabul(client, d, p["id"], qty=10, cost=700,
                 lots=[{"qty": 10, "batch_number": "D12-" + uuid.uuid4().hex[:6]}])
    with _db() as db:
        oldin = {str(b.id): str(b.received_qty)
                 for b in db.query(StockBatch).filter(StockBatch.product_id == pid).all()}
    assert oldin, "sinov sharti: partiya yaratilgan bo'lishi kerak"
    assert any(v == "10.000" or float(v) == 10.0 for v in oldin.values()), \
        f"sinov sharti: 10 lik partiya kutilgan, bor: {oldin!r}"

    r = _patch(client, d, doc, qty=4, cost=700)
    # ⚠️  KUZATUVLI mahsulotda eski tahrir yo'li ATAYLAB rad etiladi (`stock_gate`,
    #     `test_legacy_receiving_gate.py`). Ikki natija ham to'g'ri — bu test
    #     hisob oqimini emas, `received_qty` ning TEGILMAGANINI o'lchaydi.
    assert r.status_code in (200, 409), r.text

    with _db() as db:
        keyin = {str(b.id): str(b.received_qty)
                 for b in db.query(StockBatch).filter(StockBatch.product_id == pid).all()}
    assert keyin == oldin, f"received_qty o'zgardi: {oldin!r} -> {keyin!r}"


# ══ 3. QULF, TENANT, IDEMPOTENTLIK ══════════════════════════════════════════

def test_TUZATILGAN_hujjat_QULFI_409_qaytaradi(client):
    """`_lock_guard` Option B dan OLDIN ishlaydi (:745/:761) — tegilmagan."""
    from app.core import error_codes as EC
    from app.models.receiving import ReceivingCorrection

    d = _shop()
    p = _product(d, name="D12 mahsulot", qty=0)
    doc = _qabul(client, d, p["id"], qty=10, cost=700)
    oldin = _surat(doc["rec"])
    # Tuzatish hodisasini TO'G'RIDAN yozamiz (partiya oqimini chaqirmasdan):
    # `_lock_guard` AYNAN shu jadvalga qaraydi (`doc_has_correction`).
    with _db() as db:
        db.add(ReceivingCorrection(
            company_id=d["cid"], receiving_id=uuid.UUID(doc["rec"]),
            purchase_id=uuid.UUID(doc["pur"]), branch_id=d["bids"][0], employee_id=d["eid"],
            reason="sinov tuzatishi", client_uuid=uuid.uuid4(),
            request_hash="0" * 64, created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc)))
        db.commit()

    r = _patch(client, d, doc, qty=4)

    assert r.status_code == 409, (r.status_code, r.text[:200])
    assert r.headers.get("X-Error-Code") == EC.LOT_CORRECTION_DOC_LOCKED, dict(r.headers)
    assert _surat(doc["rec"]) == oldin, "rad etilgan PATCH suratga tegdi"


def test_TENANT_izolyatsiyasi_va_IDEMPOTENTLIK(client):
    A, B = _shop(), _shop()
    pa = _product(A, name="A mahsulot", qty=0)
    doc = _qabul(client, A, pa["id"], qty=10, cost=700)
    oldin = _surat(doc["rec"])

    # Begona do'kon PATCH qila OLMAYDI va suratga tegmaydi
    rb = client.patch(f"/api/v1/purchases/{doc['pur']}", headers=B["H"],
                      json={"items": [{"id": doc["item"], "qty": 1, "unit_cost": 1}],
                            "client_uuid": str(uuid.uuid4())})
    assert rb.status_code == 404, (rb.status_code, rb.text[:200])
    assert _surat(doc["rec"]) == oldin

    # AYNI client_uuid bilan ikki marta — surat baribir o'zgarmaydi
    cu = str(uuid.uuid4())
    for _ in range(2):
        rr = client.patch(f"/api/v1/purchases/{doc['pur']}", headers=A["H"],
                          json={"items": [{"id": doc["item"], "qty": 4, "unit_cost": 700}],
                                "client_uuid": cu})
        assert rr.status_code == 200, rr.text
    assert _surat(doc["rec"]) == oldin, "takroriy PATCH suratni o'zgartirdi"


# ══ 4. O'QUVCHILAR ASL va JORIY QIYMATNI AJRATADI ═══════════════════════════

def test_OQUVCHILAR_asl_va_JORIY_qiymatlarni_AJRATADI(client):
    """Shartnoma: `GET /receiving/{id}` — ASL hodisa; `GET /purchases/{id}` — JORIY holat.
    Mijoz ikkisini `purchase_status` orqali bog'laydi (mobil `cancelled` ni shundan biladi)."""
    d = _shop()
    p = _product(d, name="D12 mahsulot", qty=0)
    doc = _qabul(client, d, p["id"], qty=10, cost=700)

    assert _patch(client, d, doc, qty=4, cost=700).status_code == 200

    asl = client.get(f"/api/v1/receiving/{doc['rec']}", headers=d["H"]).json()
    joriy = client.get(f"/api/v1/purchases/{doc['pur']}", headers=d["H"]).json()

    # ASL qabul hodisasi
    assert float(asl["total_qty"]) == 10.0, asl["total_qty"]
    assert float(asl["items"][0]["qty"]) == 10.0, asl["items"][0]
    # JORIY tuzatilgan holat
    assert float(joriy["items"][0]["qty"]) == 4.0, joriy["items"][0]
    assert float(joriy["total"]) == 2800.0, joriy["total"]
    # BOG'LOVCHI: joriy xarid holati qabul javobida ham bor
    assert asl["purchase_id"] == doc["pur"]
    assert asl["purchase_status"] in ("received", "debt", "partial", "cancelled"), asl
    # Ro'yxat o'quvchisi ham AYNI ASL qiymatni ko'radi (izchillik)
    royxat = client.get("/api/v1/receiving", headers=d["H"]).json()
    qator = [x for x in royxat if x["id"] == doc["rec"]]
    assert qator and float(qator[0]["total_qty"]) == 10.0, qator
