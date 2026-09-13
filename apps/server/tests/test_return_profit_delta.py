# -*- coding: utf-8 -*-
"""PHASE 3.6 (1-band) — QAYTARISHNING FOYDAGA TA'SIRI, RAQAM BILAN.

⚠️  PHASE 3.5 HISOBOTIMDAGI NOANIQ IBORA TUZATILADI. U yerda «restock=True —
    yalpi foydaga ta'sir NOL» deb yozgandim. Bu ikki har xil narsani
    ARALASHTIRADI:

        QAYTARISHNING O'ZI (delta):  daromad −100, COGS −60, foyda −40
        AMALDAN KEYINGI HOLAT:       daromad 0,   COGS 0,   foyda 0

    Delta NOL EMAS — u aynan sotuv yaratgan foydani BEKOR QILADI. Nol
    bo'ladigan narsa — sotuv va qaytarish JAMI.

    Kod HAR DOIM to'g'ri edi; noto'g'ri bo'lgani — mening iborам. Shu bois
    bu yerda KOD O'ZGARTIRILMAYDI, faqat raqamlar MAHKAMLANADI.

⚠️  YAROQSIZ (restock=False) QAYTARISH BOSHQACHA:

        delta:  daromad −100, COGS 0, foyda −100
        keyin:  daromad 0,    COGS 60, sof natija −60

    Ya'ni tannarx SOTUVDA QOLADI — mol javonga qaytmadi, uni tiklash yo'q
    molning tannarxini yo'qdan qaytarib, foydani oshirib yuborardi.
"""
import uuid
from decimal import Decimal

from tests.test_lot_fefo_sale import (  # noqa: F401
    _db,
    _product,
    _recv_plain,
    ctx,
    sup,
)

REV = 100          # bitta dona × 100
COST = 60          # olish narxi
GP = REV - COST    # 40


def _sell_one(client, H, pid):
    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 1, "unit_price": REV}],
        "payment_method": "cash", "given_amount": 10000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ret(client, H, sid, pid, *, restock=True):
    client.post("/api/v1/shifts/open", headers=H, json={"opening_cash": 9999999})
    return client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": sid, "reason": "customer", "restock": restock,
        "refund_method": "cash", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": 1, "unit_price": 0}]})


def _named(rows, nom, maydon="profit", *, limit=None):
    """Mahsulot qatorini NOM bo'yicha topadi (`product_id` emas).

    ⚠️  «QATOR YO'Q» IKKI XIL MA'NO BERADI, VA ULARNI AJRATISH SHART:

          · hali SOTUV bo'lmagan            -> foyda haqiqatan 0.0 (bazaviy
                                               surat aynan shunday);
          · REYTINGDAN CHIQIB KETGAN        -> qiymat NOMA'LUM, 0.0 emas.

        Ilgari ikkalasiga ham jimgina 0.0 qaytardi va bu YASHIRIN FLAKE
        yaratardi: `top-products` standart `limit=5` bilan chaqilardi, umumiy
        to'plam o'sgani sayin o'lchanayotgan mahsulot ro'yxatdan tushib
        qolardi va sinov «foyda −40 ga o'zgardi» deb NOTO'G'RI xulosa
        chiqarardi — aslida u RAQAMNI emas, REYTINGNI o'lchagan bo'lardi.

        Farqlovchi belgi — ro'yxat KESILGANMI: qatorlar soni limitga yetgan
        bo'lsa, yo'qlik ikki ma'noli va sinov DARHOL to'xtaydi.
    """
    rows = rows or []
    for x in rows:
        if x.get("name") == nom:
            return float(x.get(maydon) or 0)
    if limit is not None and len(rows) >= limit:
        return None   # KESILGAN — qiymat NOMA'LUM, 0.0 DEB O'QILMAYDI
    return 0.0        # ro'yxat to'liq va qator yo'q -> sotuv bo'lmagan


def _snap(client, H, nom):
    """BARCHA foyda ko'rsatadigan iste'molchilar bitta suratda."""
    g = lambda u: client.get(u, headers=H).json()          # noqa: E731
    pnl = g("/api/v1/reports/pnl?period=month")
    ov = g("/api/v1/reports/overview?period=month")
    det = g("/api/v1/reports/detail?period=month")
    return {
        "pnl.net": pnl["net"],
        "pnl.cogs": pnl["cogs"],
        "pnl.gross_profit": pnl["gross_profit"],
        "pnl.returns": pnl["returns"],
        "summary.profit": g("/api/v1/reports/summary")["today_profit"],
        "dashboard.profit": g("/api/v1/reports/dashboard")["today_profit"],
        "overview.kpi.profit": ov["kpi"]["profit"],
        # ⚠️  `limit=100` ATAYIN: standart 5 bo'lib, umumiy to'plamdagi boshqa
        #     mahsulotlar ko'paysa o'lchanayotgan mahsulot reytingdan chiqib
        #     ketardi va sinov RAQAMNI emas, REYTINGNI o'lchardi.
        "top.profit": _named(
            g("/api/v1/reports/top-products?period=month&limit=100"), nom, limit=100),
        # `/reports/detail` mahsulot qatorlarini `abc` kalitida qaytaradi va
        # ro'yxatni QATTIQ 60 qatorga kesadi (`reports.py`: `prods[:60]`) —
        # parametri YO'Q. Umumiy to'plamda 60 dan ko'p mahsulot sotilgan
        # bo'lsa, o'lchanayotgan mahsulot ro'yxatga tushmasligi MUMKIN va bu
        # hisobotning HAQIQIY xususiyati, nuqson emas. Shu bois kesilgan
        # holat `None` bilan belgilanadi va TEKSHIRUVDAN CHIQARIB tashlanadi —
        # 0.0 deb o'qilsa, sinov «foyda o'zgarmadi» deb YOLG'ON aytardi.
        "detail.profit": _named(det.get("abc"), nom, limit=60),
    }


def _delta(a, b):
    """Ikkala suratda ham O'LCHANGAN kalitlar bo'yicha delta.

    ⚠️  `None` = «ro'yxat kesilgan, qiymat noma'lum». Uni 0.0 deb olish
        o'lchovni YOLG'ONGA aylantirardi, shu bois kalit butunlay tushib
        qoladi va sinov uni tekshirmaydi (qaysi kalit tushgani quyida
        AYTIB o'tiladi).
    """
    return {k: round(b[k] - a[k], 2) for k in a
            if a.get(k) is not None and b.get(k) is not None}


def _nom(client, H):
    """Mahsulot va uning NOMI — hisobotlar nom bo'yicha guruhlaydi."""
    from app.models.catalog import Product
    pid = _product(client, H, buy=COST)
    with _db() as db:
        return pid, db.get(Product, uuid.UUID(pid)).name


# ══ 1. TO'LIQ RESTOCK QAYTARISH ═════════════════════════════════════════════

def test_TOLIQ_RESTOCK_qaytarish_deltasi_AYNAN_teskari(client, admin_headers, ctx, sup):
    """delta = (−100, −60, −40); keyin = (0, 0, 0).

    ⚠️  «Delta nol» degan da'vo NOTO'G'RI bo'lardi: u qaytarishni umuman
        hisobga olmagan bo'lardi va sotuv foydasi kitoblarda QOLIB ketardi.
    """
    H = admin_headers
    pid, nom = _nom(client, H)
    _recv_plain(client, H, sup, pid, 10, COST)
    oldin = _snap(client, H, nom)
    sid = _sell_one(client, H, pid)
    sotuvdan = _snap(client, H, nom)
    assert _delta(oldin, sotuvdan)["pnl.gross_profit"] == float(GP), "sotuv bo'sh"

    assert _ret(client, H, sid, pid).status_code == 200
    keyin = _snap(client, H, nom)
    d = _delta(sotuvdan, keyin)

    assert d["pnl.net"] == -float(REV), d
    assert d["pnl.cogs"] == -float(COST), d
    assert d["pnl.gross_profit"] == -float(GP), d
    assert d["pnl.returns"] == float(REV), d
    _ISTEMOLCHI = ("summary.profit", "dashboard.profit", "overview.kpi.profit",
                   "top.profit", "detail.profit")
    for k in _ISTEMOLCHI:
        if k not in d:
            continue          # kesilgan ro'yxat — yuqoridagi izohga qarang
        assert d[k] == -float(GP), (k, d[k])
    # FAQAT `detail.profit` tushishi mumkin (60 qatorlik ABC kesilishi).
    # Boshqasi tushsa — bu kesilish emas, o'lchov BUZILGANI.
    _olchandi = [k for k in _ISTEMOLCHI if k in d]
    assert len(_olchandi) >= len(_ISTEMOLCHI) - 1, (
        f"kutilganidan ko'p iste'molchi o'lchanmadi: {_olchandi}")

    # ── SOTUV + QAYTARISH = NOL ────────────────────────────────────────────
    jami = _delta(oldin, keyin)
    for k, v in jami.items():
        if k == "pnl.returns":
            assert v == float(REV), k     # qaytarish hajmi ko'rinadi
        else:
            assert v == 0.0, (k, v)


# ══ 2. YAROQSIZ (restock=False) QAYTARISH ═══════════════════════════════════

def test_YAROQSIZ_qaytarish_deltasi_COGSni_TIKLAMAYDI(client, admin_headers, ctx, sup):
    """delta = (−100, 0, −100); keyin = daromad 0, COGS 60, sof natija −60."""
    H = admin_headers
    pid, nom = _nom(client, H)
    _recv_plain(client, H, sup, pid, 10, COST)
    oldin = _snap(client, H, nom)
    sid = _sell_one(client, H, pid)
    sotuvdan = _snap(client, H, nom)

    assert _ret(client, H, sid, pid, restock=False).status_code == 200
    keyin = _snap(client, H, nom)
    d = _delta(sotuvdan, keyin)

    assert d["pnl.net"] == -float(REV), d
    assert d["pnl.cogs"] == 0.0, f"yaroqsiz mol tannarxi TIKLANDI: {d}"
    assert d["pnl.gross_profit"] == -float(REV), d
    _ISTEMOLCHI = ("summary.profit", "dashboard.profit", "overview.kpi.profit",
                   "top.profit", "detail.profit")
    for k in _ISTEMOLCHI:
        if k not in d:
            continue          # kesilgan ro'yxat — yuqoridagi izohga qarang
        assert d[k] == -float(REV), (k, d[k])
    # FAQAT `detail.profit` tushishi mumkin (60 qatorlik ABC kesilishi).
    # Boshqasi tushsa — bu kesilish emas, o'lchov BUZILGANI.
    _olchandi = [k for k in _ISTEMOLCHI if k in d]
    assert len(_olchandi) >= len(_ISTEMOLCHI) - 1, (
        f"kutilganidan ko'p iste'molchi o'lchanmadi: {_olchandi}")

    # ── SOTUV + YAROQSIZ QAYTARISH = −TANNARX ──────────────────────────────
    jami = _delta(oldin, keyin)
    assert jami["pnl.net"] == 0.0, jami
    assert jami["pnl.cogs"] == float(COST), f"tannarx sotuvda QOLMADI: {jami}"
    assert jami["pnl.gross_profit"] == -float(COST), jami


# ══ 3. QISMAN QAYTARISH — PROPORSIONAL ══════════════════════════════════════

def test_QISMAN_qaytarish_PROPORSIONAL(client, admin_headers, ctx, sup):
    """2 dan 1 tasi qaytsa — aynan yarmi bekor bo'ladi."""
    H = admin_headers
    pid, nom = _nom(client, H)
    _recv_plain(client, H, sup, pid, 10, COST)
    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 2, "unit_price": REV}],
        "payment_method": "cash", "given_amount": 10000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    sotuvdan = _snap(client, H, nom)
    assert _ret(client, H, r.json()["id"], pid).status_code == 200
    d = _delta(sotuvdan, _snap(client, H, nom))
    assert d["pnl.net"] == -float(REV), d
    assert d["pnl.cogs"] == -float(COST), d
    assert d["pnl.gross_profit"] == -float(GP), d
