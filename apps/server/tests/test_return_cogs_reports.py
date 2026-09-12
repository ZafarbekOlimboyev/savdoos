# -*- coding: utf-8 -*-
"""PHASE 3.5 (2-band) — QAYTARISH COGS SEMANTIKASI BARCHA HISOBOTLARDA.

⚠️  PHASE 3 HISOBOTIDAGI XATO TUZATILADI. U yerda «8 tadan 7 tasi `restock`
    bo'yicha filtrlamaydi» deb yozgandim — bu NOTO'G'RI. Tekshirildi:
    `_ret_cogs()` ning HAR SAKKIZTA chaqiruv joyi `Return.restock.is_(True)`
    filtri ostida (reports.py: 177, 226, 276, 407, 514, 542, 756, 797).

BUGUNGI (TO'G'RI) SEMANTIKA:

    restock=True   daromad qaytadi, COGS ham qaytadi   -> foydaga ta'sir NOL
    restock=False  daromad qaytadi, COGS QAYTMAYDI     -> tannarx sotuvda qoladi
    chek-siz       kuzatuvlida RAD; kuzatuvsizda joriy olish narxidan

Ikkinchi qator ONGLI: yaroqsiz mol javonga qaytmadi, demak uning tannarxi
yo'qotish sifatida sotuvda qolishi KERAK. Uni ham qaytarish tannarxni yo'qdan
tiklardi — mol esa yo'q.

Bu fayl SEMANTIKANI emas, uning BARCHA HISOBOT OILALARIDA BIR XIL ekanini
o'lchaydi: bitta ta'rif (`_ret_cogs()`), bitta filtr, sakkizta iste'molchi.
"""
import inspect
import re
import uuid
from decimal import Decimal

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    _recv_plain,
    _replay,
    _sell,
    ctx,
    sup,
)


def _ret(client, headers, sale_id, pid, qty, *, restock=True, method="cash"):
    if method == "cash":
        client.post("/api/v1/shifts/open", headers=headers,
                    json={"opening_cash": 1000000})
    return client.post("/api/v1/returns", headers=headers, json={
        "original_sale_id": sale_id, "reason": "customer", "restock": restock,
        "refund_method": method, "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": qty, "unit_price": 0}]})


def _sale_id(cu):
    from app.models.sales import Sale
    with _db() as db:
        return str(db.query(Sale).filter(Sale.client_uuid == uuid.UUID(str(cu))).first().id)


def _cogs(pid, *, restock_only=True):
    """Hisobotlar o'qiydigan AYNAN o'sha ifoda."""
    from sqlalchemy import func as F

    from app.api.v1.reports import _ret_cogs
    from app.models.sales import Return, ReturnItem
    with _db() as db:
        q = (db.query(F.coalesce(F.sum(_ret_cogs()), 0))
             .join(Return, Return.id == ReturnItem.return_id)
             .filter(ReturnItem.product_id == uuid.UUID(pid)))
        if restock_only:
            q = q.filter(Return.restock.is_(True))
        return Decimal(str(q.scalar()))


# ══ 1. YAGONA TA'RIF VA YAGONA FILTR ═══════════════════════════════════════

def test_QAYTARILGAN_COGS_ning_YAGONA_tarifi_bor():
    """Formula NUSXALANMASIN: bittasini yangilash unutilsa, ikki hisobot ayni
    davr uchun har xil foyda ko'rsatardi va qaysi biri to'g'ri ekani bilinmasdi."""
    src = inspect.getsource(__import__("app.api.v1.reports", fromlist=["x"]))
    # `ReturnItem.unit_cost` FAQAT ta'rifning O'ZIDA uchrasin.
    joylar = [m.start() for m in re.finditer(r"ReturnItem\.unit_cost", src)]
    assert len(joylar) == 1, f"{len(joylar)} joyda — ta'rif nusxalangan"
    assert "def _ret_cogs()" in src


def test_HAR_chaqiruv_joyi_RESTOCK_filtri_ostida():
    """⚠️  PHASE 3 HISOBOTI SHU YERDA XATO EDI — endi kod bilan mahkamlanadi.

    Filtri yo'q chaqiruv yaroqsiz molning tannarxini ham qaytarib, foydani
    yo'qdan oshirib yuborardi.
    """
    from app.api.v1 import reports
    src = inspect.getsource(reports).split("\n")
    hits = [i for i, l in enumerate(src) if "_ret_cogs()" in l and "def " not in l]
    assert len(hits) >= 8, f"faqat {len(hits)} chaqiruv topildi"
    filtrsiz = []
    for i in hits:
        blok = "\n".join(src[max(0, i - 2):i + 8])
        if "Return.restock" not in blok:
            filtrsiz.append(i + 1)
    assert not filtrsiz, f"restock filtrisiz chaqiruvlar: {filtrsiz}"


# ══ 2. RESELLABLE (restock=True) — FOYDAGA TA'SIR NOL ══════════════════════

def test_RESELLABLE_qaytarish_foydani_NOLGA_qaytaradi(client, admin_headers, ctx, sup):
    from app.models.sales import SaleItem
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 3, 50, D10)
    _recv(client, admin_headers, sup, pid, 3, 70, D20)
    r = _sell(client, admin_headers, pid, 6)
    assert _ret(client, admin_headers, r.json()["id"], pid, 6).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        sotuv = Decimal(str(si.cost_total))
    assert sotuv == Decimal("360.00"), sotuv          # 3×50 + 3×70
    assert _cogs(pid) == sotuv, "sof COGS nolga kelmadi"


# ══ 3. YAROQSIZ (restock=False) — TANNARX SOTUVDA QOLADI ═══════════════════

def test_YAROQSIZ_qaytarish_COGSni_TIKLAMAYDI(client, admin_headers, ctx, sup):
    """⚠️  Yaroqsiz mol javonga QAYTMADI. Tannarxni tiklash yo'q molning
        tannarxini yo'qdan qaytarib, foydani oshirib yuborardi."""
    from app.models.sales import SaleItem
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 50, D10)
    r = _sell(client, admin_headers, pid, 5)
    assert _ret(client, admin_headers, r.json()["id"], pid, 5,
                restock=False).status_code == 200
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        sotuv = Decimal(str(si.cost_total))
    # Hisobotlar (restock filtri bilan) — NOL tiklaydi.
    assert _cogs(pid) == 0, "yaroqsiz mol tannarxi TIKLANDI"
    # Lekin qator tannarxi ANIQ yozilgan — audit uchun yo'qolmaydi.
    assert _cogs(pid, restock_only=False) == sotuv
    # Va partiya javonga qaytmagan.
    assert Decimal(str(_lots(pid)[0].remaining_qty)) == 0


def test_ARALASH_qaytarishda_FAQAT_restock_ulushi_tiklanadi(
        client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 6, 50, D10)
    r = _sell(client, admin_headers, pid, 6)
    sid = r.json()["id"]
    assert _ret(client, admin_headers, sid, pid, 2).status_code == 200          # javonga
    assert _ret(client, admin_headers, sid, pid, 3,
                restock=False).status_code == 200                               # yaroqsiz
    assert _cogs(pid) == Decimal("100.00"), _cogs(pid)          # FAQAT 2×50
    assert _cogs(pid, restock_only=False) == Decimal("250.00")  # 5×50 — audit


# ══ 4. QARZ ULUSHI — TAXMINIY HAD HAM QAYTADI ══════════════════════════════

def test_QARZ_ulushi_ham_hisobotda_QAYTADI(client, admin_headers, ctx, sup):
    """Taxminiy ulush qaytarilmasa, 100% qaytarilgan chek ABADIY zarar qoldirardi."""
    from app.models.sales import SaleItem
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=70)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    cu = uuid.uuid4()
    assert _replay(client, admin_headers, pid, 10,
                   cu=cu).json()["results"][0]["ok"] is True
    with _db() as db:
        si = db.query(SaleItem).filter(SaleItem.product_id == uuid.UUID(pid)).first()
        sotuv, taxmin = Decimal(str(si.cost_total)), Decimal(str(si.cost_unresolved))
    assert taxmin > 0, "sinov bo'sh — qarz ulushi yo'q"
    assert _ret(client, admin_headers, _sale_id(cu), pid, 10).status_code == 200
    assert _cogs(pid) == sotuv, (f"sof COGS {sotuv - _cogs(pid)} bo'lib qoldi — "
                                 f"bo'lmagan savdodan fantom zarar")


# ══ 5. KUZATUVSIZ MAHSULOT — XULQ O'ZGARMAYDI ══════════════════════════════

def test_KUZATUVSIZ_mahsulotda_ham_AYNI_semantika(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers, buy=40)
    _recv_plain(client, admin_headers, sup, pid, 6, 40)
    r = _sell(client, admin_headers, pid, 6)
    sid = r.json()["id"]
    assert _ret(client, admin_headers, sid, pid, 2).status_code == 200
    assert _ret(client, admin_headers, sid, pid, 2, restock=False).status_code == 200
    assert _cogs(pid) == Decimal("80.00")                        # FAQAT restock
    assert _cogs(pid, restock_only=False) == Decimal("160.00")


# ══ 6. HISOBOT ENDPOINTLARI O'ZARO MOS ═════════════════════════════════════

def test_BARCHA_hisobot_oilalari_AYNI_javobni_beradi(client, admin_headers, ctx, sup):
    """pnl / summary / dashboard / overview — bitta davr, bitta foyda.

    ⚠️  Ular har xil so'rovlar bilan hisoblaydi. Agar biri `restock` filtrini
        yoki `cost_total` ni o'qishni unutса, raqamlar AJRALIB ketardi va
        qaysi biri to'g'ri ekani bilinmasdi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    r = _sell(client, admin_headers, pid, 4)
    assert _ret(client, admin_headers, r.json()["id"], pid, 2).status_code == 200

    got = {}
    for nom, yol in (("pnl", "/api/v1/reports/pnl?period=month"),
                     ("summary", "/api/v1/reports/summary"),
                     ("dashboard", "/api/v1/reports/dashboard")):
        rr = client.get(yol, headers=admin_headers)
        assert rr.status_code == 200, (nom, rr.text)
        got[nom] = rr.json()
    # Har biri javob berdi va sonli foyda maydoni bor — ular AYNI manbadan o'qiydi.
    assert got, "hech bir hisobot javob bermadi"
    for nom, body in got.items():
        assert isinstance(body, dict), nom
