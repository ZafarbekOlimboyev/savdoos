# -*- coding: utf-8 -*-
"""PHASE 3.6 (2- va 3-band) — TANNARXNING KELIB CHIQISHI YO'QOLMASIN.

BU FAYL IKKI JIMLIKNI MAHKAMLAYDI.

⚠️  2-BAND — TAXMIN «ANIQ»GA AYLANMASIN.
    Mijoz qaytargan, lekin QAYSI kogortadan ketgani noma'lum tovar
    `return_unattributed` partiyasi bo'lib qoldiqqa tushadi. Uning narxi —
    sotuv paytidagi `base_buy_price` dan MUZLATILGAN TAXMIN. Shu partiya
    keyin sotilganda `lot_fefo.exact_cost()` uni boshqa partiyalardan
    AJRATMAY «ANIQ COGS» qilib yozardi. Ya'ni:

        qarz taxmini 50  →  mijoz 2 dona qaytardi  →  2 dona @50 taxminiy
                         →  o'sha 2 dona sotildi   →  «ANIQ COGS 100»

    Uchinchi o'qda yolg'on bor: 100 — TAXMIN, va uni aniq deb e'lon qilish
    o'quvchiga qaysi raqamga ishonishni bilish imkonini bermasdi.

⚠️  3-BAND — NOMA'LUM 0 BILAN ALMASHTIRILMASIN.
    `/reports/history/seed` tannarxi noma'lum tarixni `cost_total=0,
    cost_basis='unknown'` qilib yozadi (koeffitsiyent TO'QIB CHIQARILMAYDI).
    Lekin `cogs` shu nollarni ham qo'shar edi — natijada tannarxi NOMA'LUM
    tushum hisobotda TANNARXI NOL tushum bo'lib, uning 100% i foyda bo'lib
    chiqardi. Bu noaniqlik emas, XATO RAQAM.

MANFIY NAZORATLAR (guard'ni orqaga qaytarib qizarishi TEKSHIRILGAN):
  · `provisional_cost` → 0 qaytarsa                       — 1, 2, 3-sinov
  · qaytarishda taxminiy ulush yozilmasa                  — 4-sinov
  · sanoq `source_type` ni «adjustment» ga almashtirsa     — 5-sinov
  · noma'lum tushum ANIQ chelakka tushsa                  — 6, 7-sinov
  · taxminiy tushum ANIQ chelakka tushsa                  — 8-sinov
"""
import uuid
from decimal import Decimal as D

from app.models.sales import ReturnItem, SaleItem

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
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
from tests.test_lot_return import _ret, _sale_id, _sf, _shift


def _si(pid, n=1):
    """Mahsulotning ENG OXIRGI sotuv qatorlari."""
    with _db() as db:
        return (db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid))
                .order_by(SaleItem.rowid.desc() if hasattr(SaleItem, "rowid")
                          else SaleItem.id.desc()).limit(n).all())


def _last_si(client, H, pid, sale_id):
    with _db() as db:
        return (db.query(SaleItem)
                .filter(SaleItem.sale_id == uuid.UUID(sale_id),
                        SaleItem.product_id == uuid.UUID(pid)).one())


def _ri_of(ret_id, pid):
    """AYNAN shu qaytarishning qatori.

    ⚠️  «OXIRGI QAYTARISH» DEB OLISH XATO EDI. `_taxminiy_partiya` ning
        O'ZI ham ayni mahsulotni qaytaradi va uning qatori tasodifan AYNI
        raqamlarni tashiydi (jami 100, taxminiy 100 — faqat boshqa sababdan:
        u qarz dumi, bu esa partiya ulushi). Shu bois «oxirgisini ol» degan
        sinov guard olib tashlanganda ham YASHIL qolardi — ya'ni u hech
        narsani o'lchamasdi. Endi qaytarish ID si bo'yicha olinadi.
    """
    with _db() as db:
        return (db.query(ReturnItem)
                .filter(ReturnItem.return_id == uuid.UUID(ret_id),
                        ReturnItem.product_id == uuid.UUID(pid)).one())


def _pnl(client, H):
    return client.get("/api/v1/reports/pnl?period=month", headers=H).json()


def _asl_cheksiz_qaytarish(client, H, ctx_, pid, *, rev, cost):
    """`original_sale_id IS NULL` qaytarishni TO'G'RIDAN-TO'G'RI bazaga yozadi.

    ⚠️  NEGA API ORQALI EMAS. Bugungi API cheksiz qaytarishni HAR QANDAY pul
        usulida rad etadi (`sales.py`: soxta naqd chiqimga qarshi) va `credit`
        mijozsiz bo'lmaydi — ya'ni API orqali bunday qatorni yaratib BO'LMAYDI.
        Lekin `returns.original_sale_id` ustuni NULL'ga RUXSAT beradi va
        eski/ko'chirilgan ma'lumotda bunday qator BO'LISHI mumkin. Hisobot
        arifmetikasi shunday qatorda ham butun qolishi SHART — aks holda
        OUTER JOIN ning NULL qatori uni HAM «aniq», HAM «bog'lanmagan»
        chelakka qo'shib, ayni pulni IKKI marta ayirardi.
    """
    from datetime import datetime, timezone

    from app.models.auth import Employee
    from app.models.sales import Return, ReturnItem
    cid, bid = ctx_
    with _db() as db:
        emp = db.query(Employee).filter(Employee.company_id == cid).first()
        rid = uuid.uuid4()
        db.add(Return(id=rid, company_id=cid, branch_id=bid, cashier_id=emp.id,
                      original_sale_id=None, reason="customer", restock=True,
                      refund_method="cash", total=rev,
                      return_no=f"QAY-X{uuid.uuid4().hex[:8]}",
                      client_uuid=uuid.uuid4(),
                      created_at=datetime.now(timezone.utc)))
        db.flush()
        db.add(ReturnItem(id=uuid.uuid4(), return_id=rid, sale_item_id=None,
                          product_id=uuid.UUID(pid), qty=1, unit_cost=cost,
                          unit_price=rev, cost_total=cost, cost_unresolved=0,
                          line_total=rev))
        db.commit()


def _taxminiy_partiya(client, H, sup_, pid, qty, buy, bid):
    """QARZ → QAYTARISH → QARZNI YOPISH → SOTUVGA YAROQLI TAXMINIY PARTIYA.

    ⚠️  QARZ NEGA YOPILADI. Ikki hadli invariant:
            Inventory.qty == Σ(partiya) − Σ(yopilmagan qarz)
        Qoldiqsiz offline sotuv `qty` dona qarz yozadi (Inventory −qty).
        Mijoz qaytarsa YANGI, atributsiyasiz partiya tug'iladi (+qty), lekin
        qarz TARIXIY fakt bo'lib OCHIQ qoladi — ya'ni Inventory 0 da turadi va
        taxminiy partiyani SOTIB BO'LMAYDI (4-band: sotuvni MIQDOR cheklaydi).
        Shu bois qarz haqiqiy kirim bilan yopiladi; shundan keyin qoldiq
        taxminiy partiyaning O'ZI bo'lib qoladi — aynan sinaladigan holat.

    ⚠️  QARZNI YOPGAN KIRIM BOSHQA NARXDA (`buy` emas, `buy+40`) — aks holda
        sinov «taxmin qaysi raqamdan kelgani»ni AJRATA olmasdi.
    """
    _enable(client, H, pid)
    cu = uuid.uuid4()
    _replay(client, H, pid, qty, cu=cu)
    assert _ret(client, H, _sale_id(cu), pid, qty).status_code == 200
    lots = [b for b in _lots(pid) if b.source_type == "return_unattributed"]
    assert len(lots) == 1 and D(str(lots[0].remaining_qty)) == D(str(qty)), lots
    assert D(str(lots[0].unit_cost)) == D(str(buy)), "taxmin narxi muzlamadi"

    # Qarzni HUJJATLI partiya bilan yopamiz — u qarz qadar KAMAYADI.
    assert _recv(client, H, sup_, pid, qty, buy + 40, D20).status_code == 200
    sf = _sf(pid)
    b = [x for x in _lots(pid) if D(str(x.unit_cost)) == D(str(buy + 40))][0]
    r = client.post(f"/api/v1/lots/shortfalls/{sf.id}/resolve", headers=H,
                    json={"stock_batch_id": str(b.id), "qty": qty,
                          "reason": "topildi"})
    assert r.status_code == 200, r.text
    assert D(str(_inv(pid, bid))) == D(str(qty)), "qarz yopilgach qoldiq taxminiy"
    return lots[0]


# ══ 1. FOYDALANUVCHI BERGAN SSENARIY — AYNAN ═══════════════════════════════

def test_TAXMINIY_partiya_sotilsa_ANIQ_COGS_deb_YOZILMAYDI(client, admin_headers,
                                                           ctx, sup):
    """qarz@50 → 2 qaytdi → 2 @50 taxminiy → sotildi → TAXMIN 100, aniq EMAS.

    ⚠️  MANFIY NAZORAT: `lot_fefo.provisional_cost` ni `Decimal("0")` ga
        aylantirsang — `cost_unresolved` 0 bo'lib shu sinov QIZARADI.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid, 2, 50, ctx[1])

    r = _sell(client, H, pid, 2)
    assert r.status_code == 200, r.text
    si = _last_si(client, H, pid, r.json()["id"])

    assert D(str(si.cost_total)) == D("100.00"), si.cost_total
    assert D(str(si.cost_unresolved)) == D("100.00"), (
        f"TAXMIN aniq COGS bo'lib ketdi: unresolved={si.cost_unresolved}")


def test_ULUSH_QOSHILMAYDI_butun_ichida(client, admin_headers, ctx, sup):
    """`cost_unresolved` — ULUSH, HAD emas. `cost_total` OSHMAYDI.

    ⚠️  Agar kimdir taxminiy ulushni jamiga QO'SHSA, bir xil pul ikki marta
        sanalib, sotuv 200 turardi va mol tekin qaytgandek ko'rinardi.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid, 2, 50, ctx[1])
    r = _sell(client, H, pid, 2)
    si = _last_si(client, H, pid, r.json()["id"])
    assert D(str(si.cost_unresolved)) <= D(str(si.cost_total))
    assert D(str(si.cost_total)) == D("100.00"), "ulush jamiga QO'SHILDI"


def test_ARALASH_qator_FAQAT_taxminiy_ulushni_belgilaydi(client, admin_headers,
                                                         ctx, sup):
    """1 dona hujjat narxidan + 1 dona taxmindan → jami 140, taxmin 50.

    ⚠️  Eng muhim sinov: «hammasi aniq» ham, «hammasi taxmin» ham NOTO'G'RI.
        Faqat TAXMINIY partiyaning ulushi taxmin bo'lib qolishi kerak.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid, 1, 50, ctx[1])
    assert _recv(client, H, sup, pid, 1, 90, D10).status_code == 200  # HUJJAT narxi 90

    oldin = _pnl(client, H)
    r = _sell(client, H, pid, 2)
    assert r.status_code == 200, r.text
    si = _last_si(client, H, pid, r.json()["id"])
    assert D(str(si.cost_total)) == D("140.00"), si.cost_total
    assert D(str(si.cost_unresolved)) == D("50.00"), (
        f"aralash qatorda ulush noto'g'ri: {si.cost_unresolved}")

    # ⚠️  HISOBOT HAM AYNAN AJRATADI, chekni butunlay bir chelakka TASHLAMAYDI.
    #     Ilgari `EXISTS` ishlatilardi va butun 140 «taxminiy» bo'lib ketardi —
    #     ya'ni ishonish MUMKIN bo'lgan 90 so'm ham taxmin deb yozilardi.
    keyin = _pnl(client, H)
    assert keyin["cogs_known"] - oldin["cogs_known"] == 90.0, (
        f"aniq ulush yo'qoldi: {oldin['cogs_known']} -> {keyin['cogs_known']}")
    assert keyin["cogs_estimated"] - oldin["cogs_estimated"] == 50.0, (
        f"taxminiy ulush noto'g'ri: {keyin['cogs_estimated'] - oldin['cogs_estimated']}")
    # Ikki marta sanalmasin: ikkovining yig'indisi AYNAN qator jami.
    assert ((keyin["cogs_known"] - oldin["cogs_known"])
            + (keyin["cogs_estimated"] - oldin["cogs_estimated"])) == 140.0
    # TUSHUM esa CHEK bo'yicha — aralash chek to'liq «aniq» EMAS.
    assert keyin["revenue_known_cost"] - oldin["revenue_known_cost"] == 0.0
    assert keyin["gross_profit_known"] - oldin["gross_profit_known"] == 0.0


# ══ 2. QAYTARISH — TAXMIN QAYTGANDA ANIQQA AYLANMASIN ══════════════════════

def test_TAXMINIY_sotuv_QAYTSA_ham_taxmin_bolib_qoladi(client, admin_headers,
                                                       ctx, sup):
    """Sotuvda taxmin deb yozilgan summa qaytarishda ANIQ bo'lib chiqmasin.

    ⚠️  Aks holda sotuv (taxmin 100) va qaytarish (aniq 100) bir-birini
        yopmasdi: kitoblarda taxmin jimgina ANIQQA aylanardi.

    ⚠️  `cost_total` O'ZGARMAYDI — 2-band faqat ASOSNI aytadi, RAQAMNI emas.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid, 2, 50, ctx[1])
    r = _sell(client, H, pid, 2)
    rr = _ret(client, H, r.json()["id"], pid, 2)
    assert rr.status_code == 200, rr.text

    ri = _ri_of(rr.json()["id"], pid)
    assert D(str(ri.cost_total)) == D("100.00"), ri.cost_total
    assert D(str(ri.cost_unresolved)) == D("100.00"), (
        f"qaytarishda taxmin ANIQ bo'lib qoldi: {ri.cost_unresolved}")
    assert D(str(ri.cost_unresolved)) <= D(str(ri.cost_total)), "ULUSH > BUTUN"


# ══ 3. SANOQ TESHIGI — BELGI NUSXA BILAN BIRGA KETSIN ══════════════════════

def test_SANOQ_taxminiy_belgini_OCHIRMAYDI(client, admin_headers, ctx, sup):
    """Ortiqcha topilsa narx nusxalanadi — ASOSI ham nusxalanishi SHART.

    ⚠️  NEGA MUHIM. `apply_count` ortiqchani `source_type="adjustment"` qilib
        yozardi. Taxminiy partiyani sanab ortiqcha chiqsa — yagona provenans
        belgisi O'CHIB, taxmin «hujjat narxi»ga aylanib qolardi va uni
        HECH QANDAY so'rov bilan qaytarib topib bo'lmasdi.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    b = _taxminiy_partiya(client, H, sup, pid, 2, 50, ctx[1])

    r = client.post("/api/v1/inventory/count", headers=H, json={
        "items": [{"product_id": pid, "counted": 3,
                   "lots": [{"stock_batch_id": str(b.id), "counted": 3}]}]})
    assert r.status_code == 200, r.text

    # ⚠️  Qarzni yopgan HUJJATLI partiya ham qator bo'lib turadi, lekin
    #     qoldig'i 0 — sanoq yaratgan ortiqchani QOLDIQ bo'yicha ajratamiz.
    yangi = [x for x in _lots(pid)
             if str(x.id) != str(b.id) and D(str(x.remaining_qty)) > 0]
    assert len(yangi) == 1, [(x.source_type, x.remaining_qty) for x in _lots(pid)]
    assert yangi[0].source_type == "return_unattributed", (
        f"sanoq taxminiy belgini O'CHIRDI: {yangi[0].source_type}")
    assert D(str(yangi[0].unit_cost)) == D("50")


# ══ 4. HISOBOT — NOMA'LUM TANNARX 0 BO'LIB KO'RINMASIN (3-band) ════════════

def _seed(client, H, *, rev, ratio=None, basis=None):
    body = {"rows": [{"no": uuid.uuid4().hex[:8],
                      "date": "05.09.2026 10:00:00", "revenue": rev}]}
    if ratio is not None:
        body["cost_ratio"] = ratio
    if basis is not None:
        body["cost_basis"] = basis
    r = client.post("/api/v1/reports/history/seed", headers=H, json=body)
    assert r.status_code == 200, r.text


def test_NOMALUM_tannarxli_tushum_ANIQ_chelakka_TUSHMAYDI(client, admin_headers):
    """`cost_basis='unknown'` tushumi `revenue_known_cost` ga KIRMAYDI.

    ⚠️  Ilgari bu tushum `cogs` ga 0 qo'shib, yalpi foydani o'z summasicha
        OSHIRIB yuborardi va hech qayerda bu aytilmasdi.
    """
    H = admin_headers
    oldin = _pnl(client, H)
    _seed(client, H, rev=500000)
    keyin = _pnl(client, H)

    assert keyin["revenue_cost_unknown"] - oldin["revenue_cost_unknown"] == 500000
    assert keyin["revenue_known_cost"] - oldin["revenue_known_cost"] == 0, (
        "NOMA'LUM tushum ANIQ chelakka tushdi")
    assert keyin["cogs_known"] - oldin["cogs_known"] == 0
    assert keyin["gross_profit_basis"] == "partial_unknown", (
        "yalpi foyda YAGONA ANIQ raqam bo'lib qoldi")


def test_NOMALUM_tushum_ANIQ_foydaga_QOSHILMAYDI(client, admin_headers):
    """`gross_profit_known` noma'lum tushumdan foyda YASAMAYDI.

    ⚠️  AYNAN 3-BANDDAGI TALAB: tannarxi noma'lum tushumni tannarxi NOL deb
        hisoblab, uni butunlay foyda deb ko'rsatish TAQIQLANADI.
    """
    H = admin_headers
    oldin = _pnl(client, H)
    _seed(client, H, rev=500000)
    keyin = _pnl(client, H)

    assert keyin["gross_profit"] - oldin["gross_profit"] == 500000, (
        "yozilgan raqamlar arifmetikasi o'zgarmasligi kerak")
    assert keyin["gross_profit_known"] - oldin["gross_profit_known"] == 0, (
        "NOMA'LUM tushum 100% foyda bo'lib ANIQ foydaga kirdi")


def test_TAXMINIY_tarix_ANIQ_chelakka_TUSHMAYDI(client, admin_headers):
    """`cost_basis='estimated'` tushumi o'z chelagida — «aniq»da emas."""
    H = admin_headers
    oldin = _pnl(client, H)
    _seed(client, H, rev=400000, ratio=0.75, basis="estimated")
    keyin = _pnl(client, H)

    assert keyin["revenue_estimated_cost"] - oldin["revenue_estimated_cost"] == 400000
    assert keyin["cogs_estimated"] - oldin["cogs_estimated"] == 300000
    assert keyin["revenue_known_cost"] - oldin["revenue_known_cost"] == 0, (
        "TAXMINIY tushum ANIQ chelakka tushdi")
    assert keyin["gross_profit_known"] - oldin["gross_profit_known"] == 0


def test_TAXMINIY_PARTIYA_sotuvi_ham_ANIQ_chelakdan_CHIQADI(client, admin_headers,
                                                            ctx, sup):
    """2-band va 3-bandning ULANISH NUQTASI.

    `Sale.cost_basis` bu chekда NULL — lekin `SaleItem.cost_unresolved > 0`.
    NULL «tekshirilgan» degani EMAS; shu bois chek TAXMINIY chelakka tushadi.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid, 2, 50, ctx[1])
    oldin = _pnl(client, H)
    assert _sell(client, H, pid, 2).status_code == 200
    keyin = _pnl(client, H)

    assert keyin["cogs_estimated"] - oldin["cogs_estimated"] == 100.0, (
        "taxminiy partiyadan sotuv TAXMINIY chelakka tushmadi")
    assert keyin["cogs_known"] - oldin["cogs_known"] == 0.0, (
        "taxmin ANIQ chelakda qoldi")


# ══ 5. AYNIYATLAR — CHELAKLAR YIG'INDISI JAMIGA TENG ═══════════════════════

def test_CHELAKLAR_YIGINDISI_jamiga_TENG(client, admin_headers, ctx, sup):
    """Chelaklar TO'LIQ va KESISHMAYDI — aks holda pul yo'qoladi/yasaladi.

    ⚠️  Bu sinov cheksiz (`original_sale_id IS NULL`) qaytarishni HAM
        qamrab oladi: u OUTER JOIN'da `cost_basis IS NULL` bo'lib chiqadi va
        ehtiyot bo'linmasa HAM «aniq», HAM «bog'lanmagan» chelakka tushib,
        ayni pulni IKKI marta ayirardi.
    """
    H = admin_headers
    pid = _product(client, H, buy=60)
    _recv_plain(client, H, sup, pid, 10, 60)
    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 2, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _ret(client, H, r.json()["id"], pid, 1).status_code == 200
    _seed(client, H, rev=300000)
    _seed(client, H, rev=200000, ratio=0.6, basis="estimated")
    _asl_cheksiz_qaytarish(client, H, ctx, pid, rev=100, cost=60)

    p = _pnl(client, H)
    rev_sum = (p["revenue_known_cost"] + p["revenue_estimated_cost"]
               + p["revenue_cost_unknown"]
               - p["returns_unlinked"] - p["returns_prior_period"])
    assert round(rev_sum, 2) == round(p["net"], 2), (p, rev_sum)
    cogs_sum = (p["cogs_known"] + p["cogs_estimated"] + p["cogs_unknown"]
                - p["cogs_returns_unlinked"] - p["cogs_returns_prior_period"])
    assert round(cogs_sum, 2) == round(p["cogs"], 2), (p, cogs_sum)
    assert p["returns_unlinked"] > 0, "cheksiz qaytarish chelagi bo'sh"


def test_BARCHA_foyda_sonlari_ASOSNI_aytadi(client, admin_headers):
    """Ogohlantirish FAQAT P&L da qolmasin — menejer bosh ekranni o'qiydi.

    ⚠️  P&L buxgalteriya hisoboti; kunlik qarorni odam `summary`/`dashboard`/
        `overview` dagi bitta «foyda» raqamiga qarab qabul qiladi. Tannarxi
        noma'lum tushum ULARGA HAM nol tannarx bilan kiradi, ya'ni ayni
        yolg'on o'sha uch joyda ham bor edi. Raqamlar o'zgarmaydi — yonida
        ASOS turadi.
    """
    H = admin_headers
    _seed(client, H, rev=500000)          # bugungi kun EMAS — davr hisobotlari
    for u, k in (("/api/v1/reports/summary", "profit_basis"),
                 ("/api/v1/reports/dashboard", "profit_basis"),
                 ("/api/v1/reports/pnl?period=month", "gross_profit_basis")):
        d = client.get(u, headers=H).json()
        assert k in d, f"{u}: foyda asosi e'lon qilinmagan"
        assert "revenue_cost_unknown" in d, f"{u}: noma'lum tushum ko'rsatilmagan"
    ov = client.get("/api/v1/reports/overview?period=month", headers=H).json()["kpi"]
    assert ov["profit_basis"] == "partial_unknown", ov
    assert ov["revenue_cost_unknown"] >= 500000, ov


def test_TAXMIN_qaytsa_TAXMINIY_chelakda_NETLANADI(client, admin_headers, ctx, sup):
    """Chelak QAYTARISHNI HAM o'z ichiga oladi — «jamidan katta ulush» bo'lmasin.

    ⚠️  ENG NOZIK NUQSON. Agar chelak faqat SOTUV tomonini sanasa, taxminiy
        partiyadan sotilgan chek to'liq qaytarilganda quyidagi absurd chiqardi:

            cogs = 0   «shundan taxminiy = 100»

        Ya'ni ULUSH BUTUNDAN KATTA. Shu bois qaytarish ham ASL CHEK asosiga
        qarab o'z chelagidan AYIRILADI va to'liq qaytarishda delta NOL bo'ladi.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid, 2, 50, ctx[1])

    oldin = _pnl(client, H)
    r = _sell(client, H, pid, 2)
    assert r.status_code == 200, r.text
    assert _pnl(client, H)["cogs_estimated"] - oldin["cogs_estimated"] == 100.0

    assert _ret(client, H, r.json()["id"], pid, 2).status_code == 200
    keyin = _pnl(client, H)
    assert keyin["cogs_estimated"] - oldin["cogs_estimated"] == 0.0, (
        "qaytarish TAXMINIY chelakdan ayirilmadi — ulush jamidan oshib ketardi")
    assert keyin["revenue_estimated_cost"] - oldin["revenue_estimated_cost"] == 0.0
    assert keyin["cogs_estimated"] <= keyin["cogs"] + 0.01 or keyin["cogs"] < 0, (
        f"ULUSH > BUTUN: est={keyin['cogs_estimated']} cogs={keyin['cogs']}")


# ══ 6. DAVR CHEGARASI — BOSHQA DAVR QAYTARISHI OSHKORLIKNI O'CHIRMASIN ═════

def _sanani_surish(sale_id, kun):
    """Chek sanasini ORQAGA suradi — «oldingi davr» holatini yasash uchun."""
    from datetime import timedelta

    from app.models.sales import Sale
    with _db() as db:
        s = db.get(Sale, uuid.UUID(sale_id))
        s.sold_at = s.sold_at - timedelta(days=kun)
        db.commit()


def test_OLDINGI_DAVR_qaytarishi_SHU_DAVR_oshkorligini_OCHIRMAYDI(
        client, admin_headers, ctx, sup):
    """⚠️  ENG JIDDIY NUQSON — DAVRLAR BO'YICHA NETLASH.

    Sotuv oynasi `Sale.sold_at`, qaytarish oynasi `Return.created_at`. Agar
    shu oynadagi qaytarish BOSHQA davrdagi chekka tegishli bo'lsa-yu, uni
    shu davr chelagidan ayirsak — bu davrning taxmin OSHKORLIGI o'chib,
    taxmin ANIQ bo'lib e'lon qilinardi:

        oldingi davr:  taxminiy sotuv (COGS 100 taxmin)
        shu davr:      YANGI taxminiy sotuv (COGS 100 taxmin)
                       + oldingi chekning qaytarilishi
        netlansa ->    cogs_estimated = 0, asos «aniq»  ← YOLG'ON

    Endi oldingi davr qaytarishi ALOHIDA kalitda ko'rsatiladi va chelakka
    TEGMAYDI.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid, 2, 50, ctx[1])

    # ── OLDINGI DAVR cheki ────────────────────────────────────────────────
    eski = _sell(client, H, pid, 2)
    assert eski.status_code == 200, eski.text
    _sanani_surish(eski.json()["id"], 45)        # oldingi oyga suriladi

    # ── SHU DAVRdagi YANGI taxminiy sotuv ─────────────────────────────────
    pid2 = _product(client, H, buy=50)
    _taxminiy_partiya(client, H, sup, pid2, 2, 50, ctx[1])
    oldin = _pnl(client, H)
    assert _sell(client, H, pid2, 2).status_code == 200
    sotuvdan = _pnl(client, H)
    assert sotuvdan["cogs_estimated"] - oldin["cogs_estimated"] == 100.0

    # ── OLDINGI DAVR chekini SHU davrda qaytaramiz ────────────────────────
    assert _ret(client, H, eski.json()["id"], pid, 2).status_code == 200
    keyin = _pnl(client, H)

    assert keyin["cogs_estimated"] == sotuvdan["cogs_estimated"], (
        "oldingi davr qaytarishi SHU davr taxmin oshkorligini O'CHIRDI: "
        f"{sotuvdan['cogs_estimated']} -> {keyin['cogs_estimated']}")
    assert keyin["gross_profit_basis"] in ("mixed", "partial_unknown"), (
        f"asos «aniq» bo'lib qoldi: {keyin['gross_profit_basis']}")
    # Pul YO'QOLMAYDI — u alohida kalitda ko'rinadi.
    assert keyin["returns_prior_period"] - sotuvdan["returns_prior_period"] > 0, (
        "oldingi davr qaytarishi HECH QAYERDA ko'rinmadi")


def test_AYNIYAT_oldingi_davr_qaytarishi_bilan_ham_BUTUN(client, admin_headers,
                                                         ctx, sup):
    """Chelaklar + alohida kalitlar = jami. Pul yo'qolmaydi, yasalmaydi."""
    H = admin_headers
    pid = _product(client, H, buy=60)
    _recv_plain(client, H, sup, pid, 10, 60)
    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 2, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    _sanani_surish(r.json()["id"], 40)
    assert _ret(client, H, r.json()["id"], pid, 1).status_code == 200

    p = _pnl(client, H)
    rev_sum = (p["revenue_known_cost"] + p["revenue_estimated_cost"]
               + p["revenue_cost_unknown"]
               - p["returns_unlinked"] - p["returns_prior_period"])
    assert round(rev_sum, 2) == round(p["net"], 2), (p, rev_sum)
    cogs_sum = (p["cogs_known"] + p["cogs_estimated"] + p["cogs_unknown"]
                - p["cogs_returns_unlinked"] - p["cogs_returns_prior_period"])
    assert round(cogs_sum, 2) == round(p["cogs"], 2), (p, cogs_sum)


def test_QARZ_DUMI_qaytarishi_409_BERMAYDI(client, admin_headers, ctx, sup):
    """Qarz dumini qaytarish ODDIY ish — 409 BERMASLIGI kerak.

    ⚠️  BU SINOV 409 QO'RIQCHISINI O'LCHAYDI. Qo'riqchi shuni tekshiradi:
        `provisional_lot_cost` — `exact_cost` ning QISM-YIG'INDISI, ya'ni
        ULUSH o'z butuni ICHIDA. Agar kimdir uni qarz dumini ham qo'shadigan
        qilib o'zgartirsa (ikki xil hadni ARALASHTIRSA), shu yerda ulush
        butundan oshadi va 409 otiladi — manfiy nazorat aynan shuni sinaydi.

    ⚠️  Ilgari qo'riqcha `_prov + _prov_lot > _exact + _prov` edi; u ikki
        tomondan `_prov` ni qisqartirar, ya'ni HECH QACHON otilmasdi va
        himoya qilaman degan regressiyani UMUMAN ushlamasdi.
    """
    H = admin_headers
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    cu = uuid.uuid4()
    _replay(client, H, pid, 2, cu=cu)            # qoldiqsiz -> QARZ DUMI
    r = _ret(client, H, _sale_id(cu), pid, 2)
    assert r.status_code == 200, f"qarz dumi qaytarishi rad etildi: {r.text}"
    ri = _ri_of(r.json()["id"], pid)
    # Qarz dumi ALOHIDA HAD: jamiga QO'SHILADI, ulush sifatida EMAS.
    assert D(str(ri.cost_total)) == D("100.00"), ri.cost_total
    assert D(str(ri.cost_unresolved)) == D("100.00"), ri.cost_unresolved
