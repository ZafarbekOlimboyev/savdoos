# -*- coding: utf-8 -*-
"""B3 — AKTIVATSIYADAN OLDINGI CHEKNI QAYTARISH (Phase 5C). SQLite.

HOLAT. Mahsulot kuzatuvsiz sotildi, KEYIN `/lots/enable` yoqildi. Chek qaytganda
orqaga o'raydigan taqsimot YO'Q: `sale_item_lot_allocations` ham, qarz ham yo'q.
Ilgari ikkala `restock` qiymatida ham 409 chiqardi va `restock=False` dagi matn
«omborga qaytarmasdan qaytaring» deb BOSHI BERK maslahat berardi — operator
allaqachon shunday qilyapti edi. Natijada aktivatsiyadan oldingi HAR QANDAY chek
tizimda umuman qaytarib bo'lmasdi (pul tizimdan tashqarida qaytarilardi).

SIYOSAT (D1):
  · `restock=False` — RUXSAT. Partiya, qarz, taqsimot TEGILMAYDI; qoldiq +k keyin
    −k bo'lib NOL qoladi; tannarx asl chek qatoridan (`qty × SaleItem.unit_cost`),
    ya'ni P&L'ga yozilgan AYNI summa. Audit qatori: `return_pre_activation`.
  · `restock=True` — RAD (409, `X-Error-Code: LOT_RETURN_PRE_ACTIVATION`). Tovar
    qaysi partiyadan chiqqani NOMA'LUM; ochilish partiyasiga qo'shish uni HECH
    QACHON tegishli bo'lmagan kogortaga yozib, tarixiy COGS'ni to'qib chiqarardi.

TASNIF TUZILISH BO'YICHA, VAQT BO'YICHA EMAS — `sold_at` ikki tomondan ham
yanglishadi (9-bo'limdagi manfiy nazoratlar aynan shuni ushlaydi).
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from app.models.inventory import (ReturnItemLotAllocation, ReturnItemResolutionAllocation,
                                  ReturnItemShortfallAllocation, SaleItemLotAllocation,
                                  StockBatch, StockMovement)
from app.models.sales import Return, ReturnItem, Sale, SaleItem
from app.models.sync import AuditLog
from app.services import lot_return as LR

from tests.test_lot_fefo_sale import (  # noqa: F401
    NOW,
    D10,
    _db,
    _enable,
    _inv,
    _lots,
    _product,
    _recv,
    _recv_plain,
    _replay,
    _sell,
    ctx,
    sup,
)
from tests.test_lot_return import _ok, _ret_items, _sale_id, _shift

# Server matnlari — AYNAN (lug'at kaliti ham shu; `test_lot_error_texts.py` qo'riqlaydi).
OLDIN_SOTILGAN = ("Bu mahsulot partiya kuzatuvi yoqilishidan OLDIN sotilgan — tovar qaysi "
                  "partiyadan chiqqani NOMA'LUM va tizim uni taxmin qilmaydi. Omborga "
                  "qaytarmasdan (restock'siz) qaytaring.")
BOGLAB_BOLMADI_RESTOCKSIZ = ("Qaytarilayotgan miqdorning {q} donasini asl chek partiyalariga "
                             "bog'lab bo'lmadi. Tizim TAXMIN QILMAYDI — amal BAJARILMADI; "
                             "qo'llab-quvvatlashga murojaat qiling.")
BOGLAB_BOLMADI_RESTOCK = ("Qaytarilayotgan miqdorning {q} donasini asl chek partiyalariga "
                          "bog'lab bo'lmadi. Tizim TAXMIN QILMAYDI — omborga qaytarmasdan "
                          "(restock'siz) qaytaring.")
KOD = "LOT_RETURN_PRE_ACTIVATION"


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _sotuv(client, H, pid, qty, *, method="card", price=100, cu=None, customer=None):
    """Bitta qatorli chek — `card` (smena talab qilmaydi) yoki `cash`/`credit`."""
    body = {"items": [{"product_id": pid, "qty": qty, "unit_price": price}],
            "payment_method": method, "client_uuid": str(cu or uuid.uuid4())}
    if method == "cash":
        body["given_amount"] = price * qty + 10000
    if customer:
        body["customer_id"] = customer
    return client.post("/api/v1/sales", headers=H, json=body)


def _qaytar(client, H, sale_id, pid, qty, *, restock=False, method="card", cu=None):
    if method == "cash":
        _shift(client, H)
    return client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": sale_id, "reason": "customer", "restock": restock,
        "refund_method": method, "client_uuid": str(cu or uuid.uuid4()),
        "items": [{"product_id": pid, "qty": qty, "unit_price": 0}]})


def _oldin_sotilgan_chek(client, H, sup, *, buy=40, stock=10, qty=3, legacy=70,
                         method="card", customer=None):
    """KUZATUVSIZ kirim -> KUZATUVSIZ sotuv -> KEYIN `/lots/enable` (legacy partiya).

    ⚠️  `legacy` narxi ATAYLAB sotuv tannarxidan (`buy`) FARQ qiladi: qaytarish
        tannarxi ochilish partiyasidan olinsa, farq sinovda KO'RINADI.
    """
    pid = _product(client, H, buy=buy)
    assert _recv_plain(client, H, sup, pid, stock, buy).status_code == 200
    s = _sotuv(client, H, pid, qty, method=method, customer=customer)
    assert s.status_code == 200, s.text
    e = _enable(client, H, pid, expiry=False, legacy_unit_cost=legacy)
    assert e.status_code == 200, e.text
    return pid, s.json()["id"], s.json()


def _holat(pid, bid):
    """Qaytarish TEGISHI mumkin bo'lgan hamma narsa — bitta suratda."""
    with _db() as db:
        p = uuid.UUID(pid)
        return {
            "inv": _inv(pid, bid),
            "lots": sorted((b.source_type, Decimal(str(b.remaining_qty))) for b in _lots(pid)),
            "rila": db.query(ReturnItemLotAllocation).filter(
                ReturnItemLotAllocation.product_id == p).count(),
            "risa": db.query(ReturnItemShortfallAllocation).filter(
                ReturnItemShortfallAllocation.product_id == p).count(),
            "rira": db.query(ReturnItemResolutionAllocation).filter(
                ReturnItemResolutionAllocation.product_id == p).count(),
            "ret_items": db.query(ReturnItem).filter(ReturnItem.product_id == p).count(),
            "moves": db.query(StockMovement).filter(StockMovement.product_id == p).count(),
        }


def _returns(sale_id):
    with _db() as db:
        return db.query(Return).filter(
            Return.original_sale_id == uuid.UUID(str(sale_id))).all()


def _audit(entity="return_pre_activation", entity_id=None):
    with _db() as db:
        q = db.query(AuditLog).filter(AuditLog.entity == entity)
        if entity_id is not None:
            q = q.filter(AuditLog.entity_id == uuid.UUID(str(entity_id)))
        return q.all()


def _harakatlar(ret_id):
    with _db() as db:
        rows = db.query(StockMovement).filter(
            StockMovement.ref_id == uuid.UUID(str(ret_id))).all()
        return sorted((m.type.value if hasattr(m.type, "value") else str(m.type),
                       Decimal(str(m.qty)), m.ref_type) for m in rows)


def _naqd(reason):
    from app.models.shifts import CashMovement
    with _db() as db:
        return [(m.type.value if hasattr(m.type, "value") else str(m.type),
                 Decimal(str(m.amount)))
                for m in db.query(CashMovement).filter(CashMovement.reason == reason).all()]


def _status(sale_id):
    with _db() as db:
        s = db.get(Sale, uuid.UUID(str(sale_id)))
        return s.status.value if hasattr(s.status, "value") else str(s.status)


def _si_ids(sale_id, pid):
    with _db() as db:
        return [si.id for si in db.query(SaleItem).filter(
            SaleItem.sale_id == uuid.UUID(str(sale_id)),
            SaleItem.product_id == uuid.UUID(pid)).order_by(SaleItem.id).all()]


# ══ 1. RESTOCK'SIZ — RUXSAT, PARTIYAGA TEGMASDAN ════════════════════════════

def test_OLDIN_sotilgan_chek_RESTOCKSIZ_qaytadi_PARTIYAGA_TEGMASDAN(
        client, admin_headers, ctx, sup):
    """⚠️  ESKI KODDA 409 EDI. Reja (`plan`) bo'sh taqsimotda yiqilib, butun
        qaytarishni bekor qilardi — `restock=False` bo'lsa ham, holbuki bu yo'l
        partiyaga UMUMAN tegmaydi.

    Bu yerda o'lchanadi: 200, qoldiq va partiyalar QIMIRLAMAYDI, taqsimot
    qatorlari (RILA/RISA/RIRA) YO'Q, tannarx ASL CHEKDAN (ochilish partiyasidan
    EMAS), audit izi bor va invariant butun.
    """
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, buy=40, stock=10,
                                       qty=3, legacy=70)
    oldin = _holat(pid, bid)
    assert oldin["lots"] == [("legacy", Decimal("7.000"))], oldin

    r = _qaytar(client, admin_headers, sid, pid, 1, restock=False, method="card")
    assert r.status_code == 200, r.text

    keyin = _holat(pid, bid)
    assert keyin["inv"] == oldin["inv"], "restock'siz qaytarish qoldiqni o'zgartirdi"
    assert keyin["lots"] == oldin["lots"], "partiyaga tovar qaytdi"
    assert (keyin["rila"], keyin["risa"], keyin["rira"]) == (0, 0, 0), keyin
    with _db() as db:
        assert db.query(StockBatch).filter(
            StockBatch.product_id == uuid.UUID(pid)).count() == 1, "yangi partiya tug'ildi"

    ri = _ret_items(pid)[0]
    assert Decimal(str(ri.cost_total)) == Decimal("40.00"), ri.cost_total   # 1 × 40
    assert Decimal(str(ri.cost_unresolved or 0)) == 0, ri.cost_unresolved
    assert Decimal(str(ri.unit_cost)) == Decimal("40.00"), "tannarx ochilish partiyasidan olindi"
    assert ri.sale_item_id == _si_ids(sid, pid)[0], "asl sotuv qatoriga havola yozilmadi"

    ret_id = r.json()["id"]
    assert _harakatlar(ret_id) == [("return_in", Decimal("1.000"), "return"),
                                   ("writeoff", Decimal("-1.000"), "return")], _harakatlar(ret_id)
    jur = _audit(entity_id=ri.id)
    assert len(jur) == 1, "audit izi yo'q"
    assert jur[0].after["restock"] is False and jur[0].after["cost_total"] == 40.0, jur[0].after
    assert jur[0].after["sale_item_ids"] == [str(ri.sale_item_id)], jur[0].after
    assert _status(sid) == "partially_refunded", _status(sid)
    _ok(cid, pid)


def test_RESTOCKSIZ_yolda_CHEGARA_tasdigi_CHAQIRILMAYDI_INVARIANT_esa_TEKSHIRILADI(
        client, admin_headers, ctx, sup, monkeypatch):
    """⚠️  IKKI DARVOZANING TAQDIRI HAR XIL.

    `assert_caps` YOZILGAN taqsimot qatorlarini qayta o'qiydi — bu yo'lda ular
    YO'Q, ya'ni u tekshiradigan narsa ham yo'q (chaqirilsa ham bo'sh natija
    berardi, lekin chaqirilmaydi: `_touched_*` to'plamlari bo'sh).

    Yakuniy invariant darvozasi esa MAJBURIY qoladi: qoldiq +k keyin −k bo'lib
    nolga kelgani AYNAN shu yerda isbotlanadi — kimdir kelajakda bu yo'lni
    qoldiqqa tegadigan qilib o'zgartirsa, darvoza uni ushlaydi.
    """
    from app.services import stock_invariant as SIv
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, qty=3)
    caps, inv_gate = [], []
    asl_caps, asl_ok = LR.assert_caps, SIv.assert_ok
    monkeypatch.setattr(LR, "assert_caps", lambda *a, **k: (caps.append(1), asl_caps(*a, **k))[1])
    monkeypatch.setattr(SIv, "assert_ok", lambda *a, **k: (inv_gate.append(1), asl_ok(*a, **k))[1])

    assert _qaytar(client, admin_headers, sid, pid, 1, restock=False).status_code == 200
    assert caps == [], "tegilmagan chegara tasdig'i chaqirildi"
    assert len(inv_gate) == 1, f"yakuniy invariant darvozasi o'tkazib yuborildi: {inv_gate}"
    _ok(cid, pid)


def test_OLDIN_sotilgan_chek_NAQD_qaytarishi_KASSAGA_bir_marta_yoziladi(
        client, admin_headers, ctx, sup):
    """Pul yo'li partiyaga bog'liq EMAS: smena, till va kassa chiqimi bugungidek."""
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, buy=40, stock=10,
                                       qty=3, legacy=70, method="cash")
    _shift(client, admin_headers)
    smena = client.get("/api/v1/shifts/current", headers=admin_headers).json()
    assert smena, "naqd qaytarish uchun smena ochilmadi"

    r = _qaytar(client, admin_headers, sid, pid, 2, restock=False, method="cash")
    assert r.status_code == 200, r.text
    ret = _returns(sid)[0]
    assert str(ret.shift_id) == smena["id"], "qaytarish smenaga yozilmadi"
    with _db() as db:
        from app.models.shifts import Shift
        sh = db.get(Shift, uuid.UUID(smena["id"]))
        assert ret.till_id == sh.till_id, (ret.till_id, sh.till_id)
    assert _naqd(f"Qaytarish {ret.return_no}") == [
        ("payout", Decimal(str(r.json()["total"])).quantize(Decimal("0.01")))], _naqd(
        f"Qaytarish {ret.return_no}")
    assert _holat(pid, bid)["lots"] == [("legacy", Decimal("7.000"))]
    _ok(cid, pid)


# ══ 2. RESTOCK — RAD, HECH NARSA YOZILMAYDI ═════════════════════════════════

def test_OLDIN_sotilgan_chekni_OMBORGA_qaytarib_BOLMAYDI(client, admin_headers, ctx, sup):
    """⚠️  ESKI KODDA ham 409 edi, lekin BOSHQA (umumiy) matn bilan va KODSIZ.

    Matn endi aniq sababni aytadi va `X-Error-Code` bilan keladi — qo'llab-quvvatlash
    uni matnga qarab emas, kod bo'yicha ajratadi.
    """
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, buy=40, stock=10,
                                       qty=3, legacy=70)
    oldin = _holat(pid, bid)

    r = _qaytar(client, admin_headers, sid, pid, 1, restock=True, method="card")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == OLDIN_SOTILGAN, r.text
    assert r.headers.get("X-Error-Code") == KOD, dict(r.headers)

    assert _returns(sid) == [], "rad etilgan qaytarish hujjat yozdi"
    assert _holat(pid, bid) == oldin, "rad etilgan qaytarish holatni o'zgartirdi"
    assert _audit() == [] or all(a.after["product_id"] != pid for a in _audit()), "audit yozildi"


def test_RAD_etilgach_AYNI_client_uuid_bilan_RESTOCKSIZ_OTADI(client, admin_headers, ctx, sup):
    """Rad etilgan urinish idempotentlik kalitini BAND QILMAYDI (hammasi qaytariladi)."""
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, qty=3)
    cu = uuid.uuid4()
    r1 = _qaytar(client, admin_headers, sid, pid, 1, restock=True, method="card", cu=cu)
    assert r1.status_code == 409 and r1.headers.get("X-Error-Code") == KOD, r1.text
    r2 = _qaytar(client, admin_headers, sid, pid, 1, restock=False, method="card", cu=cu)
    assert r2.status_code == 200, r2.text
    assert len(_returns(sid)) == 1, "ikkinchi urinish ikkinchi hujjat yozdi"
    assert _holat(pid, bid)["ret_items"] == 1


def test_IDEMPOTENT_ayni_client_uuid_IKKI_MARTA_pul_IKKI_MARTA_chiqmaydi(
        client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, qty=3, method="cash")
    cu = uuid.uuid4()
    a = _qaytar(client, admin_headers, sid, pid, 2, restock=False, method="cash", cu=cu)
    b = _qaytar(client, admin_headers, sid, pid, 2, restock=False, method="cash", cu=cu)
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert a.json()["id"] == b.json()["id"], (a.json(), b.json())
    assert len(_returns(sid)) == 1 and _holat(pid, bid)["ret_items"] == 1
    assert len(_naqd(f"Qaytarish {_returns(sid)[0].return_no}")) == 1, "pul ikki marta chiqdi"
    _ok(cid, pid)


# ══ 3. CHEK CHEGARASI VA PUL YO'LLARI ═══════════════════════════════════════

def test_QISMAN_qaytarish_SOTILGANIDAN_oshmaydi(client, admin_headers, ctx, sup):
    """Mahsulot chegarasi (sotilgan − oldin qaytarilgan) TEGILMAGAN."""
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, qty=3)
    assert _qaytar(client, admin_headers, sid, pid, 2, restock=False).status_code == 200
    r = _qaytar(client, admin_headers, sid, pid, 2, restock=False)
    assert r.status_code == 400, r.text
    assert "sotilganidan oshiq" in r.json()["detail"] and "qoldi: 1" in r.json()["detail"], r.text
    assert _qaytar(client, admin_headers, sid, pid, 1, restock=False).status_code == 200
    assert _status(sid) == "refunded", _status(sid)
    _ok(cid, pid)


def test_NASIYA_chek_RESTOCKSIZ_qaytsa_MIJOZ_QARZIDAN_ayiriladi(
        client, admin_headers, ctx, sup):
    from app.models.customers import CreditTransaction, Customer
    cid, bid = ctx
    c = client.post("/api/v1/customers", headers=admin_headers,
                    json={"full_name": "B3 nasiya mijoz", "phone": ""})
    assert c.status_code == 200, c.text
    cust_id = c.json()["id"]
    pid, sid, sj = _oldin_sotilgan_chek(client, admin_headers, sup, qty=3,
                                        method="credit", customer=cust_id)
    with _db() as db:
        qarz0 = Decimal(str(db.get(Customer, uuid.UUID(cust_id)).credit_balance))
    assert qarz0 > 0, "nasiya chek qarz yozmadi — sinov bo'sh"

    r = _qaytar(client, admin_headers, sid, pid, 1, restock=False, method="credit")
    assert r.status_code == 200, r.text
    jami = Decimal(str(r.json()["total"]))
    with _db() as db:
        cust = db.get(Customer, uuid.UUID(cust_id))
        assert Decimal(str(cust.credit_balance)) == qarz0 - jami, cust.credit_balance
        tx = db.query(CreditTransaction).filter(
            CreditTransaction.customer_id == cust.id,
            CreditTransaction.sale_id == uuid.UUID(sid)).all()
        assert [Decimal(str(t.amount)) for t in tx if Decimal(str(t.amount)) < 0] == [-jami], tx
    assert _holat(pid, bid)["lots"] == [("legacy", Decimal("7.000"))]
    _ok(cid, pid)


# ══ 4. RUXSAT — PARTIYA MANTIG'IGA YETIB BORMAYDI ═══════════════════════════

def test_RUXSATSIZ_xodim_TASNIFGA_ham_YETMAYDI(client, admin_headers, ctx, sup, monkeypatch):
    """403 — darvozadan OLDIN. Tasnif chaqiruvlari SANALADI va NOL bo'lishi shart."""
    import contextlib
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, qty=3)
    oldin = _holat(pid, bid)

    phone = "+99893" + str(uuid.uuid4().int % 10_000_000).zfill(7)
    pw = "Toshkent-Kuz-2026"
    emp = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": "B3 omborchi", "phone": phone, "password": pw, "role_code": "omborchi"})
    assert emp.status_code == 200, emp.text
    try:
        lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": pw})
        assert lg.status_code == 200, lg.text
        H = {"Authorization": f"Bearer {lg.json()['access_token']}"}
        chaqiruv = []
        asl = LR.pre_activation_line
        monkeypatch.setattr(LR, "pre_activation_line",
                            lambda *a, **k: (chaqiruv.append(1), asl(*a, **k))[1])
        for restock in (False, True):
            r = _qaytar(client, H, sid, pid, 1, restock=restock, method="card")
            assert r.status_code == 403, r.text
            assert r.json()["detail"] == "Ruxsat yo'q: qaytarishlar.create", r.text
        assert chaqiruv == [], "ruxsatsiz so'rov tasnifga yetib bordi"
        assert _returns(sid) == [] and _holat(pid, bid) == oldin
        # MANFIY NAZORAT: sanovchi ISHLAYDI — ruxsatli so'rov uni oshiradi.
        assert _qaytar(client, admin_headers, sid, pid, 1, restock=False).status_code == 200
        assert len(chaqiruv) == 1, chaqiruv
    finally:
        with contextlib.suppress(Exception):
            client.delete(f"/api/v1/employees/{emp.json()['id']}", headers=admin_headers)


# ══ 5. HISOBOT — RESTOCK'SIZ QAYTARISH COGS'NI TIKLAMAYDI ══════════════════

def test_HISOBOTDA_tushum_qaytadi_COGS_esa_SOTUVDA_qoladi(client, admin_headers, ctx, sup):
    """`restock=False` qoidasi (reports.py: `Return.restock.is_(True)` filtri) —
    aktivatsiyadan oldingi chekda ham AYNI: tushum kamayadi, tannarx qaytmaydi.

    ⚠️  O'LCHOV DELTA BILAN: umumiy sinov bazasida boshqa fayllar ham savdo yozadi.
    """
    cid, bid = ctx
    pid, sid, _ = _oldin_sotilgan_chek(client, admin_headers, sup, buy=40, stock=10, qty=3)
    oldin = client.get("/api/v1/reports/summary", headers=admin_headers)
    assert oldin.status_code == 200, oldin.text
    o = oldin.json()

    r = _qaytar(client, admin_headers, sid, pid, 2, restock=False, method="card")
    assert r.status_code == 200, r.text
    jami = float(r.json()["total"])
    k = client.get("/api/v1/reports/summary", headers=admin_headers).json()

    assert round(o["today_sales"] - k["today_sales"], 2) == round(jami, 2), (o, k)
    # COGS tiklanMADI -> foyda AYNAN tushum qadar kamayadi (2 × 40 = 80 QAYTMAYDI).
    assert round(o["today_profit"] - k["today_profit"], 2) == round(jami, 2), (o, k)
    assert round(o["cogs_variance"] - k["cogs_variance"], 2) == 0.0, (o, k)


# ══ 6. NOMUVOFIQ VA ARALASH QATOR — FAIL-CLOSED ════════════════════════════

def _sia_ochir(sale_item_id, *, provisional=None):
    """Sotuv qatorining taqsimot qatorlarini o'chiradi (nomuvofiq holat modeli)."""
    with _db() as db:
        db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.sale_item_id == sale_item_id).delete()
        si = db.get(SaleItem, sale_item_id)
        si.provisional_qty = provisional
        db.commit()


def test_NOMUVOFIQ_qator_FAIL_CLOSED_va_RESTOCKSIZ_deb_maslahat_BERMAYDI(
        client, admin_headers, ctx, sup):
    """Taqsimot ham, qarz ham yo'q — LEKIN `provisional_qty` NULL emas.

    Bu aktivatsiyadan oldingi qatorning surati EMAS (kuzatuvsiz sotuv
    `provisional_qty` ni HECH QACHON to'ldirmaydi), shu bois tasnif `None` beradi
    va bugungi fail-closed yo'l saqlanadi.

    ⚠️  MUTATSIYA NAZORATI: `sold_untracked` dan `provisional_qty IS NULL` sharti
        olib tashlansa, bu qator «aktivatsiyadan oldingi» deb tasniflanib
        `restock=False` da 200 qaytarardi — sinov QIZIL bo'ladi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 5, 50, D10).status_code == 200
    s = _sotuv(client, admin_headers, pid, 3)
    assert s.status_code == 200, s.text
    si_id = _si_ids(s.json()["id"], pid)[0]
    with _db() as db:
        assert db.get(SaleItem, si_id).provisional_qty is not None, "sinov bo'sh"
    _sia_ochir(si_id, provisional=Decimal("0.000"))
    oldin = _holat(pid, bid)

    r = _qaytar(client, admin_headers, s.json()["id"], pid, 1, restock=False)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == BOGLAB_BOLMADI_RESTOCKSIZ.format(q="1.000"), r.text
    assert "restock'siz" not in r.json()["detail"], "boshi berk maslahat qaytdi"
    assert r.headers.get("X-Error-Code") is None, dict(r.headers)
    assert _returns(s.json()["id"]) == [] and _holat(pid, bid) == oldin
    _ok(cid, pid)


def test_ARALASH_chekda_bir_qator_taqsimotli_bir_qator_taqsimotsiz_FAIL_CLOSED(
        client, admin_headers, ctx, sup):
    """Bir chekda ayni mahsulotning IKKI qatori har xil ko'rinsa — tasnif `None`.

    Tizim «hammasi aktivatsiyadan oldin» deb TAXMIN QILMAYDI: reja tuziladi va
    bog'lab bo'lmagan qism uchun fail-closed 409 beradi, hech narsa yozmasdan.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 8, 50, D10).status_code == 200
    s = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 4, "unit_price": 100},
                  {"product_id": pid, "qty": 4, "unit_price": 100}],
        "payment_method": "card", "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    sid = s.json()["id"]
    ikkinchi = _si_ids(sid, pid)[1]
    _sia_ochir(ikkinchi, provisional=None)     # ikkinchi qator «kuzatuvsiz» ko'rinadi
    oldin = _holat(pid, bid)

    for restock, kutilgan in ((False, BOGLAB_BOLMADI_RESTOCKSIZ.format(q="2.000")),
                              (True, BOGLAB_BOLMADI_RESTOCK.format(q="2.000"))):
        r = _qaytar(client, admin_headers, sid, pid, 6, restock=restock)
        assert r.status_code == 409, (restock, r.text)
        assert r.json()["detail"] == kutilgan, (restock, r.text)
        assert r.headers.get("X-Error-Code") is None, dict(r.headers)
        assert _returns(sid) == [], restock
        assert _holat(pid, bid) == oldin, restock
    _ok(cid, pid)


# ══ 7. MANFIY NAZORATLAR — TASNIF YANGLISHMAYDI ════════════════════════════

def test_NAZORAT_YOQILGANDAN_KEYINGI_chek_IKKALA_restockda_ham_BUGUNGIDEK(
        client, admin_headers, ctx, sup):
    """Kuzatuvli sotilgan chek: `restock=True` partiyaga qaytadi, `restock=False`
    esa partiyaga TEGMAYDI — ikkalasi ham 200 va AUDIT izi `return_lot_attribution`."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 50, D10).status_code == 200
    s = _sotuv(client, admin_headers, pid, 6)
    sid = s.json()["id"]
    assert _inv(pid, bid) == 4

    r1 = _qaytar(client, admin_headers, sid, pid, 2, restock=True)
    assert r1.status_code == 200, r1.text
    assert _inv(pid, bid) == 6 and _holat(pid, bid)["rila"] == 1
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 6

    r2 = _qaytar(client, admin_headers, sid, pid, 2, restock=False)
    assert r2.status_code == 200, r2.text
    assert _inv(pid, bid) == 6, "restock'siz qaytarish qoldiqni o'zgartirdi"
    assert _holat(pid, bid)["rila"] == 1, "restock'siz qaytarish taqsimot yozdi"
    ri = sorted(_ret_items(pid), key=lambda x: x.id)
    assert {Decimal(str(x.cost_total)) for x in ri} == {Decimal("100.00")}   # 2 × 50
    assert _audit() == [] or all(a.after["product_id"] != pid for a in _audit()), (
        "kuzatuvli chek `return_pre_activation` deb yozildi")
    _ok(cid, pid)


def test_NAZORAT_OFFLINE_chek_sold_at_YOQISHDAN_OLDIN_bolsa_ham_TAQSIMOTLI(
        client, admin_headers, ctx, sup):
    """⚠️  VAQT BO'YICHA TASNIFNI USHLAYDI. Offline chek yoqilgandan KEYIN qayta
        yuborilgan, lekin `sold_at` yoqishdan OLDIN. Taqsimot BOR, ya'ni bu chek
        aktivatsiyadan oldingi EMAS: `restock=True` partiyaga qaytadi.

        `sale.sold_at < product.lots_activated_at` qoidasi bo'lsa, bu qaytarish
        409 olardi.
    """
    from app.models.catalog import Product
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=40)
    assert _recv_plain(client, admin_headers, sup, pid, 10, 40).status_code == 200
    assert _enable(client, admin_headers, pid, expiry=False,
                   legacy_unit_cost=70).status_code == 200
    cu = uuid.uuid4()
    rp = _replay(client, admin_headers, pid, 3, cu=cu, sold_at=NOW - timedelta(minutes=30))
    assert rp.json()["results"][0]["ok"] is True, rp.text
    sid = _sale_id(cu)
    with _db() as db:
        s = db.get(Sale, uuid.UUID(sid))
        p = db.get(Product, uuid.UUID(pid))
        assert p.lots_activated_at is not None
        assert s.sold_at.replace(tzinfo=None) < p.lots_activated_at.replace(tzinfo=None), (
            "sinov bo'sh — chek yoqishdan keyin sotilgan ko'rinadi")
        assert db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.product_id == uuid.UUID(pid)).count() == 1

    r = _qaytar(client, admin_headers, sid, pid, 1, restock=True, method="cash")
    assert r.status_code == 200, r.text
    h = _holat(pid, bid)
    assert h["rila"] == 1 and h["lots"] == [("legacy", Decimal("8.000"))], h
    assert _audit() == [] or all(a.after["product_id"] != pid for a in _audit())
    _ok(cid, pid)


def test_NAZORAT_QARZLI_chek_ATRIBUTSIYASIZ_partiya_yaratadi(client, admin_headers, ctx, sup):
    """⚠️  «TAQSIMOT YO'Q» O'ZI YETARLI EMAS. Qarzli (shortfall) qator ham
        taqsimotsiz, lekin u aktivatsiyadan oldingi EMAS — qaytishi bugungidek
        `return_unattributed` partiya va RISA qatorini yaratadi."""
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=60)
    _enable(client, admin_headers, pid)
    cu = uuid.uuid4()
    assert _replay(client, admin_headers, pid, 5, cu=cu).json()["results"][0]["ok"] is True
    sid = _sale_id(cu)
    with _db() as db:
        from app.models.inventory import LotShortfall
        assert db.query(LotShortfall).filter(
            LotShortfall.product_id == uuid.UUID(pid)).count() == 1

    r = _qaytar(client, admin_headers, sid, pid, 2, restock=True, method="cash")
    assert r.status_code == 200, r.text
    h = _holat(pid, bid)
    assert h["lots"] == [("return_unattributed", Decimal("2.000"))], h
    assert h["risa"] == 1, h
    assert _audit() == [] or all(a.after["product_id"] != pid for a in _audit())
    _ok(cid, pid)


def test_NAZORAT_KUZATUVSIZ_mahsulot_qaytarishi_OZGARMAYDI(client, admin_headers, ctx, sup):
    """Kuzatuvsiz mahsulotda tasnif UMUMAN chaqirilmaydi — yo'l bit-darajasida eski."""
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=40)
    assert _recv_plain(client, admin_headers, sup, pid, 5, 40).status_code == 200
    s = _sotuv(client, admin_headers, pid, 5)
    assert s.status_code == 200, s.text
    assert _qaytar(client, admin_headers, s.json()["id"], pid, 2,
                   restock=True).status_code == 200
    assert _inv(pid, bid) == 2
    ri = _ret_items(pid)[0]
    assert Decimal(str(ri.cost_total)) == Decimal("80.00")      # 2 × 40
    assert Decimal(str(ri.cost_unresolved or 0)) == 0
    h = _holat(pid, bid)
    assert (h["rila"], h["risa"], h["rira"]) == (0, 0, 0) and h["lots"] == []
    assert _audit() == [] or all(a.after["product_id"] != pid for a in _audit())
