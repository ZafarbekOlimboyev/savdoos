# -*- coding: utf-8 -*-
"""PHASE 3 — PARTIYAGA QAYTARISH (chek asosida).

ASOSIY QOIDA: qaytarish — SOTUVNING TESKARISI, yangi FEFO qarori EMAS.
Mijoz qaytargan tovar AYNAN o'zi olgan tovar; uni qaytadan FEFO bilan
joylashtirish muddat hisobotini ham, tannarxni ham YOLG'ON qilardi.

Bu fayl to'rt sinfdagi xatoni ushlab turadi:
  1. NOTO'G'RI PARTIYA — qaytarish FEFO bilan «taxmin» qilsa.
  2. NOTO'G'RI TANNARX — `base_buy_price` yoki partiyaning BUGUNGI narxi.
  3. YO'QOLGAN MIQDOR — qarz dumi faqat bitta hadni siljitsa (invariant).
  4. ABADIY FANTOM COGS — taxminiy ulush qaytarishda qaytarilmasa.
"""
import uuid
from decimal import Decimal

from app.models.sales import ReturnItem, SaleItem
from app.services import stock_invariant as SI

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    _db,
    _enable,
    _inv,
    _lots,
    _product,
    _recv,
    _replay,
    _sell,
    ctx,
    sup,
)


def _shift(client, headers):
    """Naqd qaytarish OCHIQ smenani talab qiladi (kassa drain himoyasi).
    Allaqachon ochiq bo'lsa 400 qaytadi — ahamiyatsiz."""
    client.post("/api/v1/shifts/open", headers=headers, json={"opening_cash": 1000000})


def _ret(client, headers, sale_id, pid, qty, restock=True, method="cash", **kw):
    if method == "cash":
        _shift(client, headers)
    return client.post("/api/v1/returns", headers=headers, json={
        "original_sale_id": sale_id, "reason": "customer", "restock": restock,
        "refund_method": method, "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": qty, "unit_price": 0}], **kw})


def _sale_id(cu):
    """`/sync/push` javobi `receipt_no` beradi, `id` emas — chekni o'zimiz topamiz."""
    from app.models.sales import Sale
    with _db() as db:
        row = db.query(Sale).filter(Sale.client_uuid == uuid.UUID(str(cu))).first()
        assert row is not None, "qayta yuborilgan chek topilmadi"
        return str(row.id)


def _by_expiry(pid):
    return sorted(_lots(pid), key=lambda b: (b.expiry_date is None, b.expiry_date))


def _ret_items(pid):
    with _db() as db:
        return (db.query(ReturnItem)
                .filter(ReturnItem.product_id == uuid.UUID(pid)).all())


def _ret_allocs(pid):
    from app.models.inventory import ReturnItemLotAllocation as RA
    with _db() as db:
        return (db.query(RA).filter(RA.product_id == uuid.UUID(pid))
                .order_by(RA.created_at).all())


def _sf(pid):
    from app.models.inventory import LotShortfall
    with _db() as db:
        return (db.query(LotShortfall)
                .filter(LotShortfall.product_id == uuid.UUID(pid)).first())


def _ok(cid, pid):
    with _db() as db:
        rep = SI.check(db, cid, [uuid.UUID(pid)])
        assert rep.ok, rep.mismatches


# ══ 1. ASL PARTIYAGA QAYTADI — FEFO TAXMIN QILMAYDI ═════════════════════════

def test_ASL_partiyaga_qaytadi_FEFO_emas(client, admin_headers, ctx, sup):
    """Sotuv D10 dan yedi. Qaytarish AYNAN D10 ga qaytsin.

    ⚠️  Agar qaytarish FEFO bilan «eng erta muddatliga» yozsa, bu yerda
        TASODIFAN to'g'ri chiqardi — shu bois sotuv D10 ni TO'LIQ yeydi va
        qaytarish paytida eng erta muddatli OCHIQ partiya D20 bo'lib qoladi.
        Ya'ni FEFO qaytarishi D20 ga yozardi va test QIZIL bo'lardi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _recv(client, admin_headers, sup, pid, 6, 70, D20)
    r = _sell(client, admin_headers, pid, 4)          # D10 TO'LIQ ketadi
    assert r.status_code == 200, r.text
    erta, kech = _by_expiry(pid)
    assert Decimal(str(erta.remaining_qty)) == 0 and erta.status == SI.DEPLETED
    assert Decimal(str(kech.remaining_qty)) == 6

    rr = _ret(client, admin_headers, r.json()["id"], pid, 3)
    assert rr.status_code == 200, rr.text
    erta2, kech2 = _by_expiry(pid)
    assert Decimal(str(erta2.remaining_qty)) == 3, "qaytarish ASL partiyaga tushmadi"
    assert Decimal(str(kech2.remaining_qty)) == 6, "FEFO taxmin qildi — begona partiya"
    assert _inv(pid, bid) == 9
    _ok(cid, pid)


def test_BOSHAGAN_partiya_QAYTA_OCHILADI(client, admin_headers, ctx, sup):
    """`depleted` — «hozir nol», «abadiy yopiq» emas.

    Ochilmasa FEFO undan sotmaydi va tovar javonda turgani holda «yo'q»
    bo'lib ko'rinardi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = _sell(client, admin_headers, pid, 5)
    assert _lots(pid)[0].status == SI.DEPLETED
    assert _ret(client, admin_headers, r.json()["id"], pid, 2).status_code == 200
    b = _lots(pid)[0]
    assert b.status == SI.OPEN, "bo'shagan partiya qayta ochilmadi"
    assert Decimal(str(b.remaining_qty)) == 2
    _ok(cid, pid)


def test_KOEP_partiyali_sotuv_YOZILGAN_tartibda_orqaga_oraladi(
        client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 50, D10)
    _recv(client, admin_headers, sup, pid, 5, 70, D20)
    r = _sell(client, admin_headers, pid, 5)          # D10: 3, D20: 2
    assert r.status_code == 200, r.text
    # 4 qaytadi -> YOZILGAN tartib: avval D10 (3), keyin D20 (1)
    assert _ret(client, admin_headers, r.json()["id"], pid, 4).status_code == 200
    erta, kech = _by_expiry(pid)
    assert Decimal(str(erta.remaining_qty)) == 3, erta.remaining_qty
    assert Decimal(str(kech.remaining_qty)) == 4, kech.remaining_qty
    ra = _ret_allocs(pid)
    assert [float(a.qty) for a in ra] == [3.0, 1.0]
    _ok(cid, pid)


# ══ 2. TANNARX — ASL SOTUVDAN ═══════════════════════════════════════════════

def test_COGS_ASL_partiya_narxidan_BUGUNGIDAN_emas(client, admin_headers, ctx, sup):
    """Qaytarish tannarxi sotuv lahzasidagi partiya narxi — o'shandan keyin
    kelgan qimmatroq kirim tarixni O'ZGARTIRMAYDI."""
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=55)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = _sell(client, admin_headers, pid, 4)
    # Sotuvdan KEYIN qimmatroq partiya keladi va `base_buy_price` ni yangilaydi.
    _recv(client, admin_headers, sup, pid, 5, 999, D20)
    assert _ret(client, admin_headers, r.json()["id"], pid, 4).status_code == 200
    ri = [x for x in _ret_items(pid)][0]
    assert Decimal(str(ri.cost_total)) == Decimal("200.00"), ri.cost_total  # 4 x 50
    assert Decimal(str(ri.cost_unresolved or 0)) == 0
    _ok(cid, pid)


def test_COGS_ANIQ_yaxlitlashda_YOQOLMAYDI(client, admin_headers, ctx, sup):
    """Ikki partiyali qaytarishda `qty * o'rtacha` tiyin yo'qotardi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 33.33, D10)
    _recv(client, admin_headers, sup, pid, 3, 66.67, D20)
    r = _sell(client, admin_headers, pid, 6)
    assert _ret(client, admin_headers, r.json()["id"], pid, 6).status_code == 200
    ri = _ret_items(pid)[0]
    aniq = Decimal("3") * Decimal("33.33") + Decimal("3") * Decimal("66.67")
    assert Decimal(str(ri.cost_total)) == aniq, (ri.cost_total, aniq)
    # Sotuv COGS'i bilan AYNAN teng -> to'liq qaytarishda foyda NOL.
    with _db() as db:
        si = db.query(SaleItem).filter(
            SaleItem.product_id == uuid.UUID(pid)).first()
        assert Decimal(str(si.cost_total)) == Decimal(str(ri.cost_total))


# ══ 3. KUMULYATIV HIMOYA ════════════════════════════════════════════════════

def test_BOLAK_BOLAK_qaytarish_partiyani_OSHIRIB_yubormaydi(
        client, admin_headers, ctx, sup):
    """Uch alohida qaytarish hujjati — jami sotilganidan OSHMASIN.

    ⚠️  Asl taqsimot O'ZGARMAYDI (u surat), shu bois har qaytarish uni
        boshidan o'qiydi. `return_item_lot_allocations` bo'lmasa uchinchi
        qaytarish partiyaga YANA 3 qo'shib, `remaining_qty` ni `received_qty`
        dan oshirib yuborardi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 6, 50, D10)
    r = _sell(client, admin_headers, pid, 6)
    sid = r.json()["id"]
    for _ in range(3):
        assert _ret(client, admin_headers, sid, pid, 2).status_code == 200
    b = _lots(pid)[0]
    assert Decimal(str(b.remaining_qty)) == 6
    assert Decimal(str(b.remaining_qty)) <= Decimal(str(b.received_qty))
    assert _inv(pid, bid) == 6
    # To'rtinchisi — sotilganidan oshadi, eski himoya to'xtatadi.
    r4 = _ret(client, admin_headers, sid, pid, 1)
    assert r4.status_code == 400, r4.text
    _ok(cid, pid)


def test_BIR_chekda_IKKI_qator_IKKALASI_ham_oraladi(client, admin_headers, ctx, sup):
    """Bitta chekda ayni mahsulot IKKI qatorda — taqsimotlari HAR XIL.

    ⚠️  Eski kod `orig_item_of` da OXIRGI qatorni qoldirardi, ya'ni birinchi
        qatorning partiyalari KO'RINMASDI va miqdorning bir qismiga partiya
        topilmasdi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _recv(client, admin_headers, sup, pid, 4, 70, D20)
    r = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 4, "unit_price": 100},
                  {"product_id": pid, "qty": 4, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    with _db() as db:
        assert db.query(SaleItem).filter(
            SaleItem.product_id == uuid.UUID(pid)).count() == 2
    assert _ret(client, admin_headers, r.json()["id"], pid, 8).status_code == 200
    erta, kech = _by_expiry(pid)
    assert Decimal(str(erta.remaining_qty)) == 4
    assert Decimal(str(kech.remaining_qty)) == 4
    ri = _ret_items(pid)[0]
    assert Decimal(str(ri.cost_total)) == Decimal("480.00"), ri.cost_total  # 4x50+4x70
    _ok(cid, pid)


# ══ 4. QARZ DUMI — IKKALA HAD SILJIYDI ══════════════════════════════════════

def test_QARZ_dumi_QOLDIQNI_oshiradi_va_QARZNI_kamaytiradi(
        client, admin_headers, ctx, sup):
    """⚠️  IKKALA HAD. Faqat qarzni kamaytirish invariantni AYNAN k ga buzardi.

    `Inventory == Σpartiya − Σqarz`: qarz k ga kamaysa o'ng tomon k ga o'sadi,
    chap tomon qimirlamasa tenglik buziladi va keyingi HAR sotuv fail-closed
    to'xtardi (partiya ekrani esa yo'q — diagnostika ham qilib bo'lmasdi).
    """
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=70)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    # Offline qayta yuborish — 10 ta sotiladi, 4 tasi partiyadan, 6 tasi QARZ.
    _cu = uuid.uuid4()
    rp = _replay(client, admin_headers, pid, 10, cu=_cu)
    assert rp.json()["results"][0]["ok"] is True, rp.text
    sid = _sale_id(_cu)
    sf = _sf(pid)
    assert Decimal(str(sf.qty)) == 6 and Decimal(str(sf.returned_qty or 0)) == 0
    qoldiq0 = _inv(pid, bid)
    _ok(cid, pid)

    assert _ret(client, admin_headers, sid, pid, 10).status_code == 200

    sf2 = _sf(pid)
    assert Decimal(str(sf2.returned_qty)) == 6, "qarz dumi qaytmadi"
    assert Decimal(str(sf2.resolved_qty)) == 0, "qaytish ATRIBUTSIYA deb yozildi"
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 4, "partiya tiklanmadi"
    assert _inv(pid, bid) == qoldiq0 + 10, "qoldiq oshmadi — invariant buzilardi"
    _ok(cid, pid)


def test_TOLIQ_qaytarishda_TAXMINIY_ulush_ham_qaytadi(client, admin_headers, ctx, sup):
    """100% qaytarilgan chekda sof COGS AYNAN NOL bo'lsin.

    ⚠️  Taxminiy ulush qaytarilmasa, bo'lmagan savdodan ABADIY zarar qolardi:
        daromad 0, tannarx esa musbat.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=70)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _cu = uuid.uuid4()
    rp = _replay(client, admin_headers, pid, 10, cu=_cu)
    sid = _sale_id(_cu)
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        sotuv_cogs = Decimal(str(si.cost_total))
        assert Decimal(str(si.cost_unresolved)) > 0, "sinov bo'sh — qarz ulushi yo'q"
    assert _ret(client, admin_headers, sid, pid, 10).status_code == 200
    ri = _ret_items(pid)[0]
    assert Decimal(str(ri.cost_total)) == sotuv_cogs, (ri.cost_total, sotuv_cogs)
    assert Decimal(str(ri.cost_unresolved)) == Decimal(str(si.cost_unresolved))
    # SOF COGS = 0 -> hisobotlarda fantom zarar YO'Q.
    assert sotuv_cogs - Decimal(str(ri.cost_total)) == 0


def test_QARZ_qaytgach_QAYTA_yopib_bolmaydi(client, admin_headers, ctx, sup):
    """Qaytib kelgan tovarni «topdim» deb IKKINCHI marta yopib bo'lmasin."""
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=70)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _cu = uuid.uuid4()
    rp = _replay(client, admin_headers, pid, 10, cu=_cu)
    sid = _sale_id(_cu)
    assert _ret(client, admin_headers, sid, pid, 10).status_code == 200
    sf = _sf(pid)
    # Yangi partiya keladi; operator qarzni yopmoqchi — lekin qarz YO'Q.
    _recv(client, admin_headers, sup, pid, 5, 60, D20)
    b = [x for x in _lots(pid) if Decimal(str(x.remaining_qty)) > 0 and x.unit_cost == 60][0]
    r = client.post(f"/api/v1/lots/shortfalls/{sf.id}/resolve", headers=admin_headers,
                    json={"stock_batch_id": str(b.id), "qty": 1,
                          "reason": "qayta yopishga urinish"})
    assert r.status_code == 400, r.text
    assert "ortiqcha" in r.json()["detail"]
    _ok(cid, pid)


# ══ 5. RESTOCK'SIZ — JAVONGA QAYTMAYDI ══════════════════════════════════════

def test_RESTOCKSIZ_partiyaga_ham_qoldiqqa_ham_TEGMAYDI(
        client, admin_headers, ctx, sup):
    """Yaroqsiz tovar javonga qaytmaydi — lekin TANNARX ANIQ qoladi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = _sell(client, admin_headers, pid, 5)
    qoldiq0 = _inv(pid, bid)
    assert _ret(client, admin_headers, r.json()["id"], pid, 3,
                restock=False).status_code == 200
    assert _inv(pid, bid) == qoldiq0, "restock'siz qaytarish qoldiqni o'zgartirdi"
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 0, "partiyaga tovar qaytdi"
    assert _ret_allocs(pid) == [], "restock'siz qaytarish taqsimot yozdi"
    ri = _ret_items(pid)[0]
    assert Decimal(str(ri.cost_total)) == Decimal("150.00"), ri.cost_total  # 3 x 50
    _ok(cid, pid)


# ══ 6. RAD ETISHLAR ═════════════════════════════════════════════════════════

def test_CHEKSIZ_qaytarish_kuzatuvli_mahsulotda_RAD(client, admin_headers, ctx, sup):
    """Orqaga o'raydigan taqsimot YO'Q — tizim taxmin qilmaydi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = client.post("/api/v1/returns", headers=admin_headers, json={
        "reason": "customer", "restock": True, "refund_method": "credit",
        "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": 1, "unit_price": 10}]})
    assert r.status_code == 409, r.text
    assert "chek raqamisiz" in r.json()["detail"]


def test_VOID_partiyaga_qaytarib_bolmaydi(client, admin_headers, ctx, sup):
    """`void` partiya invariant yig'indisidan CHIQARILGAN — unga qo'shish
    qoldiqni partiyalardan AJRATIB yuborardi. JIMGINA emas, ANIQ rad."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = _sell(client, admin_headers, pid, 5)
    with _db() as db:
        from app.models.inventory import StockBatch
        b = db.query(StockBatch).filter(
            StockBatch.product_id == uuid.UUID(pid)).first()
        b.status = SI.VOID
        db.commit()
    rr = _ret(client, admin_headers, r.json()["id"], pid, 2)
    assert rr.status_code == 409, rr.text
    assert "restock'siz" in rr.json()["detail"]
    # RAD ETILGAN amal HECH NARSA yozmasin.
    assert _ret_items(pid) == []
    assert _ret_allocs(pid) == []


def test_MUDDATI_OTGAN_partiyaga_qaytadi_va_OTGANLIGICHA_qoladi(
        client, admin_headers, ctx, sup):
    """Tovar jismonan qaytadi; «yangi» qilib ko'rsatish YOLG'ON bo'lardi."""
    from tests.test_lot_expiry_report import KECHA, _eskirt
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = _sell(client, admin_headers, pid, 3)
    _eskirt(pid, KECHA)                      # javonda turib muddati o'tdi
    assert _ret(client, admin_headers, r.json()["id"], pid, 3).status_code == 200
    b = _lots(pid)[0]
    assert Decimal(str(b.remaining_qty)) == 5
    assert b.expiry_date == KECHA, "muddat JIMGINA yangilandi"
    assert b.status == SI.OPEN
    e = client.get("/api/v1/lots/expiring", headers=admin_headers).json()
    mine = [x for x in e["lots"] if x["product_id"] == pid]
    assert mine and mine[0]["bucket"] == "expired"
    _ok(cid, pid)


# ══ 7. KUZATUVSIZ XULQ O'ZGARMAYDI ══════════════════════════════════════════

def test_KUZATUVSIZ_qaytarish_ESKICHA(client, admin_headers, ctx, sup):
    from tests.test_lot_fefo_sale import _recv_plain
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=40)
    _recv_plain(client, admin_headers, sup, pid, 5, 40)
    r = _sell(client, admin_headers, pid, 5)
    assert r.status_code == 200, r.text
    assert _ret(client, admin_headers, r.json()["id"], pid, 2).status_code == 200
    assert _inv(pid, bid) == 2
    ri = _ret_items(pid)[0]
    assert Decimal(str(ri.cost_total)) == Decimal("80.00")     # 2 x 40
    assert Decimal(str(ri.cost_unresolved or 0)) == 0
    assert _ret_allocs(pid) == []


# ══ 8. QARZ SOTUV BILAN QAYTARISH ORASIDA YOPILSA ══════════════════════════

def test_QARZ_avval_YOPILSA_qaytarish_TOPILGAN_partiyaga_tushadi(
        client, admin_headers, ctx, sup):
    """Eng nozik ketma-ketlik: sotuv -> qarz -> YOPISH -> qaytarish.

    ⚠️  Yopish «bu miqdor AYNAN shu partiyadan ketgan» degan javobni TOPADI.
        Agar u taqsimotga yozilmasa, keyingi qaytarish miqdorning bir qismiga
        partiya TOPA OLMASDI va butun qaytarish 409 bilan rad etilardi —
        mijoz esa tovarni qo'lida ushlab turgan bo'lardi.

    ⚠️  TANNARX: sotuv taxminiy narxni yozgan, qaytarish esa HAQIQIY narxni
        qaytaradi. Farq — o'sha yopish paytida yozilgan OG'ISH. Uch amal
        yig'indisi NOL beradi, ya'ni pul yo'qolmaydi va yo'qdan paydo bo'lmaydi.
    """
    from decimal import Decimal as D

    from app.models.inventory import LotShortfall
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=70)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _cu = uuid.uuid4()
    rp = _replay(client, admin_headers, pid, 10, cu=_cu)
    assert rp.json()["results"][0]["ok"] is True, rp.text
    sid = _sale_id(_cu)
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        sotuv_cogs = D(str(si.cost_total))
        taxmin = D(str(si.cost_unresolved))
    sf = _sf(pid)
    # ⚠️  TAXMIN ASOSI `base_buy_price`, VA U KIRIMDA YANGILANADI (kirim narxi
    #     50 bo'lgach mahsulot narxi ham 50 ga aylandi). Qo'lda yozilgan son
    #     keyin jimgina eskirardi — qiymat qarz qatoridan O'QIB olinadi.
    taxmin_narx = D(str(sf.unit_cost))

    # Operator qarzni QIMMATROQ partiyaga yopadi.
    _recv(client, admin_headers, sup, pid, 6, 90, D20)
    b90 = [x for x in _lots(pid) if D(str(x.unit_cost)) == 90][0]
    rr = client.post(f"/api/v1/lots/shortfalls/{sf.id}/resolve", headers=admin_headers,
                     json={"stock_batch_id": str(b90.id), "qty": 6, "reason": "topildi"})
    assert rr.status_code == 200, rr.text
    ogish = D(str(rr.json()["cogs_variance"]))
    assert ogish == D("6") * (D("90") - taxmin_narx), (ogish, taxmin_narx)
    _ok(cid, pid)

    # Endi mijoz HAMMASINI qaytaradi — partiya TOPILISHI shart.
    r = _ret(client, admin_headers, sid, pid, 10)
    assert r.status_code == 200, r.text
    ri = _ret_items(pid)[0]
    # 4 x 50 (asl partiya) + 6 x 90 (yopishda topilgan partiya)
    assert D(str(ri.cost_total)) == D("4") * D("50") + D("6") * D("90"), ri.cost_total
    assert D(str(ri.cost_unresolved or 0)) == 0, "qarz allaqachon yopilgan edi"

    # UCH AMAL YIG'INDISI NOL: sotuv − og'ish − qaytarish.
    assert sotuv_cogs + ogish - D(str(ri.cost_total)) == 0, (
        sotuv_cogs, ogish, ri.cost_total)
    assert taxmin > 0, "sinov bo'sh — qarz ulushi yo'q edi"

    with _db() as db:
        row = db.query(LotShortfall).filter(LotShortfall.id == sf.id).first()
        assert D(str(row.returned_qty or 0)) == 0, "yopilgan qarz QAYTA ochildi"
    _ok(cid, pid)


# ══ 9. LOT-DARAJASIDAGI KUMULYATIV CHEGARA (mahsulot chegarasi YETMAYDI) ════

def test_IKKI_qatorli_chekda_PARTIYA_chegarasi_ALOHIDA_ishlaydi(
        client, admin_headers, ctx, sup):
    """⚠️  MAHSULOT DARAJASIDAGI CHEGARA YETARLI EMAS.

    Mavjud himoya «bu chekda shu mahsulotdan sotilganidan ko'p qaytarma»
    deydi. U TO'G'RI, lekin PARTIYA darajasida KO'R:

        chek: qator-1 = 4 dona (A partiyasidan), qator-2 = 4 dona (B dan)
        1-qaytarish 4 dona -> qator-1 orqali A ga 4 qaytadi
        2-qaytarish 4 dona -> mahsulot chegarasi RUXSAT beradi (8-4=4)

    Agar `return_item_lot_allocations` bo'yicha juftlik chegarasi bo'lmasa,
    ikkinchi qaytarish YANA qator-1 dan boshlab A ga 4 qo'shardi: A = 8,
    holbuki unga jami 4 dona kirgan (`remaining_qty > received_qty`) —
    va B hech qachon tiklanmasdi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    _recv(client, admin_headers, sup, pid, 4, 70, D20)
    r = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 4, "unit_price": 100},
                  {"product_id": pid, "qty": 4, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    assert _ret(client, admin_headers, sid, pid, 4).status_code == 200
    assert _ret(client, admin_headers, sid, pid, 4).status_code == 200

    erta, kech = _by_expiry(pid)
    assert Decimal(str(erta.remaining_qty)) == 4, (
        f"A partiyasi {erta.remaining_qty} — juftlik chegarasi ishlamadi")
    assert Decimal(str(kech.remaining_qty)) == 4, (
        f"B partiyasi {kech.remaining_qty} — tiklanmadi")
    for b in (erta, kech):
        assert Decimal(str(b.remaining_qty)) <= Decimal(str(b.received_qty))
    _ok(cid, pid)


# ══ 10. ANIQ COGS HISOBOTGACHA YETIB BORADI ════════════════════════════════

def test_HISOBOTDAGI_qaytarilgan_COGS_ham_ANIQ(client, admin_headers, ctx, sup):
    """⚠️  `ReturnItem.cost_total` ni to'g'ri yozish YETARLI EMAS — hisobot uni
        O'QISHI ham shart. Ilgari 8 ta hisobot `qty × unit_cost` deb QAYTA
        hisoblardi va ko'p partiyali qaytarishda tiyin yo'qotardi.

    Narxlar ataylab shunday tanlangan: o'rtacha yaxlitlanganda farq CHIQADI.
        aniq   = 1×10.00 + 2×10.01 = 30.02
        o'rtacha = ROUND((10.00+20.02)/3) = 10.01 -> 3×10.01 = 30.03
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 1, 10.00, D10)
    _recv(client, admin_headers, sup, pid, 2, 10.01, D20)
    r = _sell(client, admin_headers, pid, 3)
    assert r.status_code == 200, r.text
    assert _ret(client, admin_headers, r.json()["id"], pid, 3).status_code == 200

    ri = _ret_items(pid)[0]
    aniq = Decimal("30.02")
    ortacha = (Decimal(str(ri.qty)) * Decimal(str(ri.unit_cost))
               ).quantize(Decimal("0.01"))
    assert Decimal(str(ri.cost_total)) == aniq, ri.cost_total
    assert ortacha != aniq, "sinov bo'sh — narxlar farq bermadi"

    # ── HISOBOT DARAJASI: `_ret_cogs()` ANIQ qiymatni bersin ────────────────
    from sqlalchemy import func as _f

    from app.api.v1.reports import _ret_cogs
    from app.models.sales import ReturnItem as _RI
    with _db() as db:
        got = db.query(_f.coalesce(_f.sum(_ret_cogs()), 0)).filter(
            _RI.product_id == uuid.UUID(pid)).scalar()
        assert Decimal(str(got)) == aniq, (
            f"hisobot {got} o'qidi, ANIQ qiymat {aniq}")
