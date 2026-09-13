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
from decimal import Decimal  # noqa: F401

import pytest

from tests.test_lot_fefo_sale import (
    _db,
    _product,
    _recv_plain,
)


@pytest.fixture()
def ayri(client):
    """ALOHIDA do'kon: (sarlavhalar, ta'minotchi).

    ⚠️  NEGA UMUMIY SEED DO'KONI EMAS. Hisobotlar mahsulot foydasini REYTING
        orqali beradi: `top-products` eng ko'pi 100 qator, `detail.abc` qattiq
        60 qator. Yaroqsiz qaytarishdan keyin mahsulot foydasi MANFIY bo'ladi
        va reytingning ENG OXIRIGA tushadi. Umumiy seansda boshqa fayllar
        100 dan ortiq mahsulot sotgach, o'lchanayotgan qator ro'yxatdan
        chiqib ketdi va sinov (to'g'ri ravishda) «o'lchanmay qoldi» deb
        qizardi — ya'ni u RAQAMNI emas, TO'PLAM HAJMINI o'lchayotgan edi.
        Alohida do'konda reytingda faqat shu sinov mahsulotlari bor: kalit
        HAR DOIM o'lchanadi va natija fayllar tartibiga bog'liq emas.
    """
    phone = f"+99895{uuid.uuid4().int % 10000000:07d}"
    code = f"rp{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/companies", headers={"X-Vendor-Key": "test-vendor-key"},
                    json={"company_name": "QA foyda deltasi", "company_code": code,
                          "owner_name": "QA Ega", "owner_phone": phone,
                          "owner_password": "Toshkent-Bahor-2026", "plan": "start"})
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password",
                     json={"phone": phone, "password": "Toshkent-Bahor-2026"})
    assert lg.status_code == 200, lg.text
    H = {"Authorization": f"Bearer {lg.json()['access_token']}"}
    s = client.post("/api/v1/suppliers", headers=H, json={"name": "Foyda deltasi ta'minotchi"})
    assert s.status_code == 200, s.text
    return H, s.json()["id"]

_ISTEMOLCHI = ("summary.profit", "dashboard.profit", "overview.kpi.profit",
               "top.profit", "detail.profit")

REV = 100          # bitta dona × 100
COST = 60          # olish narxi
GP = REV - COST    # 40


def _sell_one(client, H, pid):
    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 1, "unit_price": REV}],
        "payment_method": "card", "given_amount": REV,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ret(client, H, sid, pid, *, restock=True):
    # ⚠️  KARTA, naqd emas: alohida do'kon cutover'dan keyin yaratiladi va naqd
    #     qaytarish aniq kassa (TILL) bilan smena talab qiladi. Foyda/COGS
    #     hisobi to'lov usuliga bog'liq EMAS — bu sinov kassani o'lchamaydi.
    return client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": sid, "reason": "customer", "restock": restock,
        "refund_method": "card", "client_uuid": str(uuid.uuid4()),
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


# ⚠️  ILGARI BU YERDA `detail.profit` KECHIRILARDI: umumiy seed do'konida `abc`
#     ro'yxati (QATTIQ 60 qator) boshqa fayllar mahsulotlari bilan to'lib, nol/
#     manfiy foydali qator ro'yxatga tushmasdi. Keyin xuddi shu kasallik
#     `top.profit` ga ham yuqdi (100 qator) va sinov to'plam hajmiga qarab
#     qizarib qoldi. Sinovlar endi `ayri` — ALOHIDA do'konda: reytingda faqat
#     o'z mahsulotlari, shu bois BESH iste'molchining HAMMASI o'lchanadi va
#     bironta ham kalit kechirilmaydi.
_KUTILGAN_YOQ: frozenset = frozenset()


def _tushgan_kalitlarni_tekshir(d):
    """Kalit o'lchanmay qolsa — FAQAT e'lon qilingani kechiriladi.

    ⚠️  ILGARI BU SANOQ EDI (`len(...) >= len(...) - 1`) va u NOMNI
        tekshirmasdi: istalgan bitta iste'molchi jimgina tushib qolsa ham
        yashil qolardi, ya'ni sinov kamayganini HECH KIM sezmasdi.
    """
    for k in _ISTEMOLCHI:
        if k not in d:
            assert k in _KUTILGAN_YOQ, (
                f"'{k}' JIMGINA o'lchanmay qoldi — ro'yxat kesilgan bo'lsa "
                f"sabab AYTILISHI, aks holda sinov tuzatilishi kerak")


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

def test_TOLIQ_RESTOCK_qaytarish_deltasi_AYNAN_teskari(client, ayri):
    """delta = (−100, −60, −40); keyin = (0, 0, 0).

    ⚠️  «Delta nol» degan da'vo NOTO'G'RI bo'lardi: u qaytarishni umuman
        hisobga olmagan bo'lardi va sotuv foydasi kitoblarda QOLIB ketardi.
    """
    H, sup = ayri
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
    for k in _ISTEMOLCHI:
        if k not in d:
            continue          # kesilgan ro'yxat — yuqoridagi izohga qarang
        assert d[k] == -float(GP), (k, d[k])
    _tushgan_kalitlarni_tekshir(d)

    # ── SOTUV + QAYTARISH = NOL ────────────────────────────────────────────
    jami = _delta(oldin, keyin)
    for k, v in jami.items():
        if k == "pnl.returns":
            assert v == float(REV), k     # qaytarish hajmi ko'rinadi
        else:
            assert v == 0.0, (k, v)


# ══ 2. YAROQSIZ (restock=False) QAYTARISH ═══════════════════════════════════

def test_YAROQSIZ_qaytarish_deltasi_COGSni_TIKLAMAYDI(client, ayri):
    """delta = (−100, 0, −100); keyin = daromad 0, COGS 60, sof natija −60."""
    H, sup = ayri
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
    for k in _ISTEMOLCHI:
        if k not in d:
            continue          # kesilgan ro'yxat — yuqoridagi izohga qarang
        assert d[k] == -float(REV), (k, d[k])
    _tushgan_kalitlarni_tekshir(d)

    # ── SOTUV + YAROQSIZ QAYTARISH = −TANNARX ──────────────────────────────
    jami = _delta(oldin, keyin)
    assert jami["pnl.net"] == 0.0, jami
    assert jami["pnl.cogs"] == float(COST), f"tannarx sotuvda QOLMADI: {jami}"
    assert jami["pnl.gross_profit"] == -float(COST), jami


# ══ 3. QISMAN QAYTARISH — PROPORSIONAL ══════════════════════════════════════

def test_QISMAN_qaytarish_PROPORSIONAL(client, ayri):
    """2 dan 1 tasi qaytsa — aynan yarmi bekor bo'ladi."""
    H, sup = ayri
    pid, nom = _nom(client, H)
    _recv_plain(client, H, sup, pid, 10, COST)
    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 2, "unit_price": REV}],
        "payment_method": "card", "given_amount": 2 * REV,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    sotuvdan = _snap(client, H, nom)
    assert _ret(client, H, r.json()["id"], pid).status_code == 200
    d = _delta(sotuvdan, _snap(client, H, nom))
    assert d["pnl.net"] == -float(REV), d
    assert d["pnl.cogs"] == -float(COST), d
    assert d["pnl.gross_profit"] == -float(GP), d


# ══ 4. ABC HISOBOTI — QAYTARISH NETLANISHI ══════════════════════════════════

def test_ABC_hisoboti_qaytarishni_NETLAYDI(client, ayri):
    """`/reports/detail` dagi `abc` foydasi qaytarishni AYIRADI.

    ⚠️  NEGA ALOHIDA SINOV KERAK BO'LDI. Yuqoridagi ikki sinov ham
        `detail.profit` ni o'lchamoqchi bo'ladi, lekin TO'LIQ qaytarishdan
        keyin mahsulot foydasi NOL bo'ladi va `abc` ro'yxati foyda bo'yicha
        saralanib 60 qatorga kesilgani uchun qator ro'yxatdan TUSHIB qoladi.
        Natijada `reports.py` dagi ABC netlash hadi (`e[3] -= ...`) BUTUNLAY
        sinovsiz qolgan edi: uni o'chirib tashlasa ham to'plam yashil qolardi.

    ⚠️  SHU BOIS IKKI NARSA BOSHQACHA:
          1. summalar KATTA — qator reytingda BIRINCHILARDA turadi va
             kesilishga tushmaydi;
          2. qaytarish QISMAN — foyda musbat qoladi, ya'ni qator ikkala
             suratda ham ro'yxatda bo'ladi.
    """
    H, sup = ayri
    BIG_REV, BIG_COST = 5_000_000, 3_000_000
    pid, nom = _nom(client, H)
    with _db() as db:                       # tannarxni KATTA qilamiz
        from app.models.catalog import Product
        p = db.get(Product, uuid.UUID(pid))
        p.base_buy_price = BIG_COST
        p.base_sell_price = BIG_REV
        db.commit()
    _recv_plain(client, H, sup, pid, 10, BIG_COST)

    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 2, "unit_price": BIG_REV}],
        "payment_method": "card", "given_amount": 2 * BIG_REV,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text

    det = client.get("/api/v1/reports/detail?period=month", headers=H).json()
    rows = det.get("abc") or []
    oldin = _named(rows, nom, limit=60)
    assert oldin == float(2 * (BIG_REV - BIG_COST)), (
        f"ABC foydasi kutilgandek emas: {oldin}")

    # QISMAN qaytarish — foyda musbat qoladi, qator ro'yxatda turaveradi.
    assert _ret(client, H, r.json()["id"], pid).status_code == 200
    det2 = client.get("/api/v1/reports/detail?period=month", headers=H).json()
    keyin = _named(det2.get("abc") or [], nom, limit=60)
    assert keyin == float(BIG_REV - BIG_COST), (
        f"ABC qaytarishni NETLAMADI: {oldin} -> {keyin}")
    assert keyin - oldin == -float(BIG_REV - BIG_COST)
