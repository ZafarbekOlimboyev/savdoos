# -*- coding: utf-8 -*-
"""PHASE 4B — PARTIYA O'QISH API (`/lots/batches`, `/alerts`, `/availability`,
`/shortfalls/{id}`).

Bu endpointlar Manager ekranlarining YAGONA ma'lumot manbai. Shu bois sinov
uchta narsani isbotlaydi:

  1. Filtr, qidiruv, tartib va SAHIFALASH SERVERDA ishlaydi — UI hammasini
     yuklab o'zi saralamaydi (7137 mahsulotli katalogda bu imkonsiz).
  2. Muddat guruhi va «muddati o'tgan» bayrog'i FILIAL BIZNES sanasidan
     olinadi, brauzer soatidan emas.
  3. Tannarx SIFATI (aniq/taxminiy/noma'lum) serverda aniqlanadi va P&L bilan
     bir xil ma'noni bildiradi.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from app.models.inventory import StockBatch

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    D30,
    PAST,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    _replay,
    ctx,
    sup,
)


def _batches(client, headers, **kw):
    r = client.get("/api/v1/lots/batches", headers=headers, params=kw)
    assert r.status_code == 200, r.text
    return r.json()


def _eskirt(pid, batch_no, kun):
    """Bitta partiyani VAQT O'TISHI bilan eskirtiradi.

    ⚠️  NEGA API ORQALI EMAS. Kirim muddati O'TGAN tovarni QABUL QILMAYDI
        (400) — va bu to'g'ri. Jonli do'konda muddati o'tgan partiya faqat
        javonda TURIB qolishdan paydo bo'ladi, shu bois sana orqaga suriladi.
    """
    with _db() as db:
        b = (db.query(StockBatch)
             .filter(StockBatch.product_id == uuid.UUID(pid),
                     StockBatch.batch_no == batch_no).one())
        b.expiry_date = kun
        db.commit()


def _biz(client, headers):
    from datetime import date as _d
    r = client.get("/api/v1/lots/expiring", headers=headers)
    assert r.status_code == 200, r.text
    return _d.fromisoformat(r.json()["business_date"])


def test_BATCHES_filtr_qidiruv_tartib_va_SAHIFALASH_serverda(client, admin_headers, ctx, sup):
    """Bitta mahsulotning uch partiyasi: filtr, qidiruv, tartib va sahifalash."""
    pid = _product(client, admin_headers, buy=40)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 5, 10, D30, batch="C-30").status_code == 200
    assert _recv(client, admin_headers, sup, pid, 3, 20, D10, batch="A-10").status_code == 200
    assert _recv(client, admin_headers, sup, pid, 7, 30, D20, batch="B-20").status_code == 200

    d = _batches(client, admin_headers, product_id=pid)
    assert d["total"] == 3, d
    # Standart tartib — MUDDAT bo'yicha o'sish: eng yaqin muddat birinchi.
    assert [l["batch_number"] for l in d["lots"]] == ["A-10", "B-20", "C-30"], d["lots"]
    assert [l["days_left"] for l in d["lots"]] == sorted(l["days_left"] for l in d["lots"])
    # Har qator UI uchun tayyor: qiymat va tannarx sifati SERVERDAN keladi.
    a = d["lots"][0]
    assert a["remaining_qty"] == 3.0 and a["unit_cost"] == 20.0 and a["value"] == 60.0
    assert a["cost_basis"] == "known" and a["source_type"] == "receiving"
    assert a["product"] and a["branch"] and a["supplier"], a

    # Tartibni teskari qilish
    d2 = _batches(client, admin_headers, product_id=pid, sort="expiry", order="desc")
    assert [l["batch_number"] for l in d2["lots"]] == ["C-30", "B-20", "A-10"]
    # Qiymat bo'yicha: 7*30=210 > 5*10=50 > 3*20=60 -> 210, 60, 50
    d3 = _batches(client, admin_headers, product_id=pid, sort="value", order="desc")
    assert [l["value"] for l in d3["lots"]] == [210.0, 60.0, 50.0], d3["lots"]

    # SAHIFALASH: total to'liq, sahifa qisqa
    p1 = _batches(client, admin_headers, product_id=pid, limit=2, offset=0)
    p2 = _batches(client, admin_headers, product_id=pid, limit=2, offset=2)
    assert p1["total"] == 3 and len(p1["lots"]) == 2 and len(p2["lots"]) == 1
    assert {l["id"] for l in p1["lots"]}.isdisjoint({l["id"] for l in p2["lots"]})

    # QIDIRUV: partiya raqami bo'yicha
    s = _batches(client, admin_headers, q="B-20")
    assert [l["batch_number"] for l in s["lots"]] == ["B-20"], s["lots"]
    # QIDIRUV: mahsulot nomi bo'yicha (nom `FEFO <hex>` ko'rinishida)
    name = d["lots"][0]["product"]
    s2 = _batches(client, admin_headers, q=name.split()[-1])
    assert s2["total"] == 3, s2


def test_BATCHES_muddat_guruhi_BIZNES_sanasidan_olinadi(client, admin_headers, ctx, sup):
    """Guruhlar kesishmaydi; «muddati o'tgan» — server biznes sanasi bo'yicha."""
    biz = _biz(client, admin_headers)
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    for qty, kun, batch in ((1, biz + timedelta(days=3), "OTGAN"), (2, biz, "BUGUN"),
                            (3, biz + timedelta(days=5), "KUN5"),
                            (4, biz + timedelta(days=40), "KUN40")):
        assert _recv(client, admin_headers, sup, pid, qty, 10, kun,
                     batch=batch).status_code == 200
    _eskirt(pid, "OTGAN", biz - timedelta(days=1))

    got = {}
    for bucket in ("expired", "expires_today", "within_7_days", "within_30_days", "later"):
        d = _batches(client, admin_headers, product_id=pid, expiry=bucket)
        got[bucket] = [l["batch_number"] for l in d["lots"]]
    assert got == {"expired": ["OTGAN"], "expires_today": ["BUGUN"],
                   "within_7_days": ["KUN5"], "within_30_days": [], "later": ["KUN40"]}, got

    d = _batches(client, admin_headers, product_id=pid, expiry="expired")
    assert d["lots"][0]["expired"] is True and d["lots"][0]["days_left"] == -1
    # `valid` — muddati o'tmaganlar (muddatsizlar ham)
    v = _batches(client, admin_headers, product_id=pid, expiry="valid")
    assert "OTGAN" not in [l["batch_number"] for l in v["lots"]], v["lots"]


def test_BATCHES_notogri_parametr_400_begona_filial_404(client, admin_headers, ctx):
    assert client.get("/api/v1/lots/batches", headers=admin_headers,
                      params={"sort": "narx"}).status_code == 400
    assert client.get("/api/v1/lots/batches", headers=admin_headers,
                      params={"expiry": "tez-orada"}).status_code == 400
    assert client.get("/api/v1/lots/batches", headers=admin_headers,
                      params={"status": "yopiq"}).status_code == 400
    r = client.get("/api/v1/lots/batches", headers=admin_headers,
                   params={"branch_id": str(uuid.uuid4())})
    assert r.status_code == 404, r.text


def test_BATCH_tafsiloti_MANBA_va_TARIX_koʻrsatadi(client, admin_headers, ctx, sup):
    """Detal ekrani: «bu partiya qayerdan keldi va qayerga ketdi» — to'liq javob."""
    pid = _product(client, admin_headers, buy=50)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 12, D20, batch="TARIX-1").status_code == 200
    assert client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 4, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 10400,
        "client_uuid": str(uuid.uuid4())}).status_code == 200

    lot_id = str(_lots(pid)[0].id)
    r = client.get(f"/api/v1/lots/batches/{lot_id}", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["batch_number"] == "TARIX-1"
    assert d["received_qty"] == 10.0 and d["remaining_qty"] == 6.0
    assert d["track_lots"] is True and d["track_expiry"] is True
    # MANBA — qabul hujjatiga bog'lanish (UI «Qabuldan» deb ko'rsatadi)
    assert d["source"]["type"] == "receiving" and d["source"]["receiving_id"], d["source"]
    assert d["source"]["receiving"] and d["source"]["receiving"]["id"] == d["source"]["receiving_id"]
    # TARIX — sotuvlar
    assert d["totals"]["sold_qty"] == 4.0, d["totals"]
    assert len(d["sales"]) == 1 and d["sales"][0]["qty"] == 4.0
    assert d["sales"][0]["receipt_no"], d["sales"][0]
    # Chiqim qoldiqqa MOS: qabul − sotuv = qoldiq
    assert d["received_qty"] - d["totals"]["sold_qty"] == d["remaining_qty"]

    assert client.get(f"/api/v1/lots/batches/{uuid.uuid4()}",
                      headers=admin_headers).status_code == 404


def test_BATCH_qatorida_TAXMINIY_va_NOMAʼLUM_tannarx_ajratiladi(client, admin_headers, ctx, sup):
    """Tannarx sifati — P&L bilan BIR XIL ma'no: `estimated` = taxminiy ulush."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    assert _recv(client, admin_headers, sup, pid, 5, 0, batch="NARXSIZ").status_code == 200
    assert _recv(client, admin_headers, sup, pid, 5, 15, batch="NARXLI").status_code == 200

    with _db() as db:  # qaytgan-taqsimlanmagan partiya (qiymat o'zgarmaydi, faqat manba)
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid),
                                        StockBatch.batch_no == "NARXLI").one()
        b.source_type = "return_unattributed"
        db.commit()

    got = {l["batch_number"]: l["cost_basis"]
           for l in _batches(client, admin_headers, product_id=pid)["lots"]}
    assert got == {"NARXSIZ": "unknown", "NARXLI": "estimated"}, got


def test_ALERTS_kartalari_sanoqni_va_XAVFDAGI_QIYMATNI_beradi(client, admin_headers, ctx, sup):
    """Dashboard kartalari — qatorlarsiz sanoq; qo'shilgan partiyalar FARQI o'lchanadi."""
    biz = _biz(client, admin_headers)
    before = client.get("/api/v1/lots/alerts", headers=admin_headers)
    assert before.status_code == 200, before.text
    b0 = before.json()

    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    for qty, cost, kun, batch in ((2, 100, biz + timedelta(days=3), "A-OTGAN"),
                                  (3, 10, biz + timedelta(days=2), "A-7"),
                                  (4, 10, biz + timedelta(days=200), "A-UZOQ")):
        assert _recv(client, admin_headers, sup, pid, qty, cost, kun,
                     batch=batch).status_code == 200
    _eskirt(pid, "A-OTGAN", biz - timedelta(days=3))

    a1 = client.get("/api/v1/lots/alerts", headers=admin_headers).json()
    dx = a1["expiry"]["expired"]["lots"] - b0["expiry"]["expired"]["lots"]
    d7 = a1["expiry"]["within_7_days"]["lots"] - b0["expiry"]["within_7_days"]["lots"]
    assert (dx, d7) == (1, 1), (b0["expiry"], a1["expiry"])
    # XAVFDAGI QIYMAT = qoldiq × tannarx (2 × 100)
    assert (a1["expiry"]["expired"]["value_at_risk"]
            - b0["expiry"]["expired"]["value_at_risk"]) == 200.0
    assert (a1["expiry"]["expired"]["qty"] - b0["expiry"]["expired"]["qty"]) == 2.0
    # 200 kunlik partiya gorizontdan TASHQARIDA — hech bir kartaga tushmaydi
    assert sum(a1["expiry"][k]["lots"] - b0["expiry"][k]["lots"] for k in a1["expiry"]) == 2
    assert a1["cost_quality"]["tracked_products"] >= 1 and a1["branches"] >= 1
    assert set(a1["expiry"]) == {"expired", "expires_today", "within_7_days", "within_30_days"}


def test_ALERTS_qarz_sanogʻi_yopilgach_kamayadi(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 10, 20, batch="QARZ-LOT")
    b0 = client.get("/api/v1/lots/alerts", headers=admin_headers).json()["shortfalls"]

    assert _replay(client, admin_headers, pid, 14).status_code == 200  # 4 dona qarz
    a1 = client.get("/api/v1/lots/alerts", headers=admin_headers).json()["shortfalls"]
    assert a1["open_count"] - b0["open_count"] == 1, (b0, a1)
    assert a1["open_qty"] - b0["open_qty"] == 4.0, (b0, a1)
    assert a1["provisional_exposure_max"] > b0["provisional_exposure_max"]


def test_AVAILABILITY_UI_darvozasini_va_RUXSATLARNI_beradi(client, admin_headers, ctx):
    """Frontend o'zicha qaror qilmaydi: nima mumkinligini SERVER aytadi."""
    r = client.get("/api/v1/lots/availability", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["schema_ready"] is True and d["schema_problem_count"] == 0
    assert isinstance(d["activation_allowed"], bool)
    # Admin — to'liq huquqli rol: yozuv ochiq, lekin faollashtirish MUHITGA bog'liq.
    assert d["permissions"]["view"] is True and d["permissions"]["edit"] is True
    assert d["can_write"] is True
    assert d["can_enable"] == (d["activation_allowed"] and d["can_write"])
    assert d["branches"] and all({"id", "name", "timezone", "timezone_supported",
                                  "timezone_confirmed"} <= set(b) for b in d["branches"])
    assert "Asia/Tashkent" in d["supported_timezones"]


def test_SHORTFALL_tafsiloti_SOTUV_NOMZOD_va_YOPISH_tarixini_beradi(client, admin_headers, ctx, sup):
    """«Aniqlanmagan qoldiq» ekrani UI da MANTIQ yozilishini talab qilmaydi.

    Nomzod partiyalar SERVERDAN keladi — frontend FEFO tartibini yoki qaytgan
    partiya ustunligini o'zi TAXMIN qilmaydi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=44)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 2, 50, D10, batch="BOR")
    assert _replay(client, admin_headers, pid, 6).json()["results"][0]["ok"] is True

    lst = client.get("/api/v1/lots/shortfalls", headers=admin_headers).json()["shortfalls"]
    sf = [x for x in lst if x["product_id"] == pid][0]
    d = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=admin_headers).json()
    assert d["open_qty"] == 4.0 and d["closed"] is False
    assert d["qty"] == 4.0 and d["resolved_qty"] == 0.0
    # Qaysi chekdan kelgani — operator uchun eng muhim savol.
    assert d["sale"] and d["sale"]["receipt_no"] and d["sale"]["qty"] == 6.0
    assert d["sale"]["provisional_qty"] == 4.0, d["sale"]
    assert d["resolutions"] == [] and d["candidate_lots"] == [], "nomzod yo'q edi"

    # Yangi partiya keldi — endi nomzod bor va og'ish OLDINDAN ko'rsatiladi.
    _recv(client, admin_headers, sup, pid, 10, 60, D20, batch="YANGI")
    d2 = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=admin_headers).json()
    cands = d2["candidate_lots"]
    assert [c["batch_number"] for c in cands] == ["YANGI"], cands
    assert cands[0]["remaining_qty"] == 10.0 and cands[0]["cost_basis"] == "known"
    assert cands[0]["own_unattributed"] is False
    # Ochiq qarz 4, partiyada 10 — bog'lash 4 dona bilan cheklanadi.
    # 4 × (60 − 50) = 40 — «to'liq bog'lansa foyda shuncha kamayadi».
    assert cands[0]["unit_variance"] == 10.0 and cands[0]["attachable_qty"] == 4.0
    assert cands[0]["variance_if_full"] == 40.0, cands[0]

    lot_id = [l["id"] for l in _batches(client, admin_headers, product_id=pid)["lots"]
              if l["batch_number"] == "YANGI"][0]
    r = client.post(f"/api/v1/lots/shortfalls/{sf['id']}/resolve", headers=admin_headers,
                    json={"allocations": [{"stock_batch_id": lot_id, "qty": 3}],
                          "reason": "qismli yopish", "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text

    d3 = client.get(f"/api/v1/lots/shortfalls/{sf['id']}", headers=admin_headers).json()
    assert d3["open_qty"] == 1.0 and d3["closed"] is False
    assert len(d3["resolutions"]) == 1, d3["resolutions"]
    e = d3["resolutions"][0]
    assert e["qty"] == 3.0 and e["batch_number"] == "YANGI" and e["variance"] == 30.0
    assert d3["cogs_variance"] == 30.0, d3
    # Partiya tafsilotida ham AYNI hodisa ko'rinadi (ikki ekran bir haqiqat).
    det = client.get(f"/api/v1/lots/batches/{lot_id}", headers=admin_headers).json()
    assert det["totals"]["resolved_qty"] == 3.0
    assert [x["shortfall_id"] for x in det["resolutions"]] == [sf["id"]]

    assert client.get(f"/api/v1/lots/shortfalls/{uuid.uuid4()}",
                      headers=admin_headers).status_code == 404
