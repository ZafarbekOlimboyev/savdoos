# -*- coding: utf-8 -*-
"""PHASE 5B — `/products?tracked=` AGREGATLARI FAQAT QAYTADIGAN MAHSULOTLAR UCHUN.

⚠️  NEGA. `tracked=true` ro'yxatni SERVERDA toraytirardi, lekin qoldiq / min /
    sotilgan xaritalari baribir do'konning HAMMA mahsuloti bo'yicha hisoblanardi.
    Production smoke'da (7137 mahsulot) BO'SH javob ham ~200 ms olardi — partiya
    ekranlari faollashtirilganda har tanlovchi so'rovi shu narxni to'lardi.

Tuzatish faqat NARXNI o'zgartiradi, MA'NONI emas. Bu fayl isbotlaydi:
  · qiymatlar (stock, min_stock, sold_qty, track_lots, track_expiry) MUSTAQIL oracle bilan AYNAN;
  · filial doirasi kanonik `visible_branches` yoki tasdiqlangan `branch_id` — actor_branch EMAS;
    `sold_qty` avvalgidek KOMPANIYA bo'yicha;
  · bo'sh natijada ham `branch_id` tekshiruvi (400/403) OLDIN ishlaydi;
  · bo'sh natija -> `inventory`/`sale_items` ga BITTA ham agregat so'rov yo'q;
  · `tracked` bilan agregat `IN (SELECT ...)` bilan toraytiriladi, id RO'YXATI bilan emas;
    `tracked`'siz yo'lning SQL'i O'ZGARMAGAN (POS sync, Dashboard, mobil shu yo'lda);
  · ruxsat o'zgarmagan: endpoint faqat autentifikatsiya talab qiladi, har rol 200.

⚠️  ALOHIDA DO'KONLAR. Demo do'kon (umumiy baza) va uning keshlangan xodimlari
    (`test_lot_permissions._staff`) TEGILMAYDI: har do'kon, filial va xodim shu faylda
    ORM orqali yaratiladi — tarif limiti band qilinmaydi.
"""
import contextlib
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select

P = "/api/v1/products"
ICHIDA, TASHQARIDA = 5, 40          # sotuv necha kun oldin: 30 kunlik oyna ICHIDA / TASHQARISIDA
NOW = datetime.now(timezone.utc)

# `inventory` yoki `sale_items` ga tegadigan har so'rov — agregat (qoldiq/min/sotilgan).
_AGG = re.compile(r"\b(inventory|sale_items)\b")


def _m(nom, tl=False, te=False, faol=True, kat=None, inv=None, sotuv=(), barkod=None, ochirilgan=False):
    """Katalog qatori: inv = {filial: (qty, min_qty)}, sotuv = [(filial, qty, necha_kun_oldin)]."""
    return {"nom": nom, "track_lots": tl, "track_expiry": te, "faol": faol, "kat": kat,
            "inv": inv or {}, "sotuv": list(sotuv), "barkod": barkod, "ochirilgan": ochirilgan}


KATALOG = (
    _m("Qatiq kuzatuvli", tl=True, te=True, kat="K1", inv={"A": ("7", "2"), "B": ("5", "4")},
       sotuv=[("A", "3", ICHIDA), ("B", "2", ICHIDA), ("A", "11", TASHQARIDA)]),
    _m("Sut kuzatuvli", tl=True, kat="K2", inv={"A": ("9.5", "1")},
       sotuv=[("B", "1.5", ICHIDA)], barkod="4600000123456"),
    _m("Tuz kuzatuvli qoldiqsiz", tl=True),
    _m("Qatiq oddiy", kat="K1", inv={"A": ("20", "5"), "B": ("30", "6")},
       sotuv=[("A", "4", ICHIDA), ("B", "6", TASHQARIDA)]),
    _m("Non oddiy", kat="K2", inv={"B": ("12", "3")}, sotuv=[("B", "2.5", ICHIDA)],
       barkod="4600000999888"),
    _m("Qatiq arxiv kuzatuvli", tl=True, te=True, faol=False, kat="K1",
       inv={"A": ("3", "1"), "B": ("8", "9")}, sotuv=[("A", "1", ICHIDA)]),
    _m("Qatiq arxiv oddiy", faol=False, kat="K2", inv={"A": ("2", "0")}),
    _m("Qatiq ochirilgan kuzatuvli", tl=True, kat="K1", inv={"A": ("50", "7")},
       sotuv=[("A", "8", ICHIDA)], ochirilgan=True),
)

# (rol, biriktirilgan filial) — kalit `rol@filial`.
XODIMLAR = (("ega", None), ("administrator", None), ("administrator", "A"), ("menejer", None),
            ("menejer", "B"), ("omborchi", "A"), ("kassir", "A"), ("kassir", None))


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _dokon(db, belgi, katalog, *, koef=1, xodimlar=XODIMLAR):
    """Alohida do'kon: A, B filiallar + o'chirilgan D filial, K1/K2 kategoriya, katalog,
    qoldiq, sotuvlar va xodimlar. `koef` — ikkinchi do'kon miqdorlari farq qilishi uchun."""
    from app.core.security import create_access_token
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Category, Product, ProductBarcode, Unit
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.sales import Sale, SaleItem

    co = Company(id=uuid.uuid4(), name=f"5B {belgi}", code="tr" + uuid.uuid4().hex[:10], currency="UZS")
    db.add(co)
    db.flush()
    fil = {}
    for kod in ("A", "B", "D"):
        b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F-{kod}", name=f"Filial {kod}",
                   timezone="Asia/Tashkent", is_active=True,
                   deleted_at=NOW if kod == "D" else None)
        db.add(b)
        db.flush()
        fil[kod] = b.id

    x = {}
    for rol, f in xodimlar:
        role = db.query(Role).filter(Role.code == rol).one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, role_id=role.id, full_name=f"5B {rol}",
                     phone="+99893" + str(uuid.uuid4().int % 10_000_000).zfill(7),
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.flush()
        if f:
            db.add(EmployeeBranch(employee_id=e.id, branch_id=fil[f]))
        tok = create_access_token(str(e.id), {"role": rol, "company_id": str(co.id), "sv": 0})
        x[f"{rol}@{f or '-'}"] = {"id": e.id, "H": {"Authorization": f"Bearer {tok}"}}
    kassir_id = next(iter(x.values()))["id"]

    kat = {}
    for k in ("K1", "K2"):
        c = Category(id=uuid.uuid4(), company_id=co.id, name=f"{k} {belgi}")
        db.add(c)
        kat[k] = c.id
    db.flush()
    unit = db.query(Unit).filter(Unit.code == "dona").one()

    p, n = {}, 0
    for i, r in enumerate(katalog):
        pr = Product(id=uuid.uuid4(), company_id=co.id, article_code=f"5B-{belgi}-{i:02d}", sku=None,
                     name=r["nom"], unit_id=unit.id, category_id=kat.get(r["kat"]),
                     base_buy_price=Decimal("5"), base_sell_price=Decimal("10"), tax_rate=0,
                     is_active=r["faol"], track_lots=r["track_lots"], track_expiry=r["track_expiry"],
                     lots_activated_at=NOW if r["track_lots"] else None,
                     deleted_at=NOW if r["ochirilgan"] else None)
        db.add(pr)
        db.flush()
        if r["barkod"]:
            db.add(ProductBarcode(product_id=pr.id, company_id=co.id, barcode=r["barkod"]))
        for f, (qty, mn) in r["inv"].items():
            db.add(Inventory(id=uuid.uuid4(), product_id=pr.id, branch_id=fil[f],
                             qty=Decimal(qty) * koef, min_qty=Decimal(mn) * koef, updated_at=NOW))
        for f, qty, kun in r["sotuv"]:
            n += 1
            q = Decimal(qty) * koef
            s = Sale(id=uuid.uuid4(), receipt_no=f"5B-{belgi}-{n}", company_id=co.id, branch_id=fil[f],
                     cashier_id=kassir_id, subtotal=q * 10, total=q * 10,
                     sold_at=NOW - timedelta(days=kun))
            db.add(s)
            db.flush()
            db.add(SaleItem(id=uuid.uuid4(), sale_id=s.id, product_id=pr.id, name_snapshot=r["nom"],
                            qty=q, unit_price=10, line_total=q * 10))
        db.flush()
        p[r["nom"]] = {**r, "id": pr.id, "article": pr.article_code, "kat_id": kat.get(r["kat"])}
    return {"cid": co.id, "fil": fil, "kat": kat, "p": p, "x": x}


@pytest.fixture(scope="module")
def dokonlar(client):
    """T — asosiy; U — AYNI nomli katalog (x100 miqdor); V — kuzatuvli mahsuloti YO'Q do'kon."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        t = _dokon(db, "T", KATALOG)
        u = _dokon(db, "U", KATALOG, koef=100, xodimlar=(("ega", None),))
        v = _dokon(db, "V", [r for r in KATALOG if not r["track_lots"]], xodimlar=(("ega", None),))
        db.commit()
    finally:
        db.close()
    return {"T": t, "U": u, "V": v}


def _kutilgan(d, *, q=None, tracked=None, archived=False, include_archived=False, kat=None):
    """Qaysi mahsulotlar qaytishi kerak — seed spetsifikatsiyasidan, nom bo'yicha tartibda."""
    out = []
    for r in d["p"].values():
        if r["ochirilgan"]:
            continue
        if not include_archived and r["faol"] != (not archived):
            continue
        if kat is not None and r["kat_id"] != d["kat"][kat]:
            continue
        if tracked is not None and r["track_lots"] != tracked:
            continue
        if q and not (q.lower() in r["nom"].lower() or q.lower() in r["article"].lower()
                      or (r["barkod"] and q.lower() in r["barkod"])):
            continue
        out.append(r)
    return sorted(out, key=lambda r: r["nom"])


def _vaqt(v):
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _oracle(db, company_id, pids, doira):
    """MUSTAQIL hisob: xom `inventory`/`sale_items` qatorlari SQL bilan olinadi, yig'indi
    Python'da. `products.py` yordamchilari CHAQIRILMAYDI. doira=None — hamma filial."""
    from app.models.inventory import Inventory
    from app.models.sales import Sale, SaleItem
    pids = list(pids)
    stock, mins, sold = defaultdict(Decimal), {}, defaultdict(Decimal)
    if pids:
        for pid, bid, qty, mn in db.execute(
                select(Inventory.product_id, Inventory.branch_id, Inventory.qty, Inventory.min_qty)
                .where(Inventory.product_id.in_(pids))).all():
            if doira is not None and bid not in doira:
                continue
            stock[pid] += Decimal(str(qty))
            mins[pid] = max(mins.get(pid, Decimal(str(mn))), Decimal(str(mn)))
        chegara = datetime.now(timezone.utc) - timedelta(days=30)
        for pid, qty, sold_at in db.execute(
                select(SaleItem.product_id, SaleItem.qty, Sale.sold_at)
                .join(Sale, Sale.id == SaleItem.sale_id)
                .where(Sale.company_id == company_id, SaleItem.product_id.in_(pids))).all():
            if _vaqt(sold_at) >= chegara:
                sold[pid] += Decimal(str(qty))
    return {pid: {"stock": float(stock.get(pid, 0)), "min_stock": float(mins.get(pid, 0)),
                  "sold_qty": float(sold.get(pid, 0))} for pid in pids}


def _solishtir(db, d, body, kutilgan, doira, tartib=True):
    """Javob tartibi va har maydon oracle bilan AYNAN. tartib=False — faqat to'plam (Postgres
    collation'i nom tartibini Python `sorted` dan boshqacha qo'yishi mumkin)."""
    if not tartib:
        body = sorted(body, key=lambda x: x["id"])
        kutilgan = sorted(kutilgan, key=lambda r: str(r["id"]))
    assert [x["id"] for x in body] == [str(r["id"]) for r in kutilgan], (
        [x["name"] for x in body], [r["nom"] for r in kutilgan])
    orc = _oracle(db, d["cid"], [r["id"] for r in kutilgan], doira)
    for x, r in zip(body, kutilgan):
        o = orc[r["id"]]
        olingan = (x["stock"], x["min_stock"], x["sold_qty"], x["track_lots"], x["track_expiry"])
        kerak = (o["stock"], o["min_stock"], o["sold_qty"], r["track_lots"], r["track_expiry"])
        assert olingan == kerak, (r["nom"], x, o)


@contextlib.contextmanager
def _sql():
    """Bajarilgan HAR so'rov (matn, parametrlar) — `before_cursor_execute`."""
    from app.db.session import engine
    got = []

    def _ol(conn, cursor, statement, params, context, executemany):
        got.append((statement, params))

    event.listen(engine, "before_cursor_execute", _ol)
    try:
        yield got
    finally:
        event.remove(engine, "before_cursor_execute", _ol)


def _agregatlar(got):
    return [(s, p) for s, p in got if _AGG.search(s)]


def _url(**kw):
    return P + ("?" + "&".join(f"{k}={v}" for k, v in kw.items()) if kw else "")


# ══ 1 · PARITET: har variant × har aktyor — mustaqil oracle bilan AYNAN ═══════

VARIANTLAR = (
    {},
    {"tracked": "true"},
    {"tracked": "false"},
    {"tracked": "true", "q": "qatiq"},
    {"tracked": "true", "q": "0123456"},              # barkod orqali
    {"tracked": "true", "branch_id": "A"},
    {"tracked": "false", "branch_id": "A"},
    {"tracked": "true", "include_archived": "true"},
    {"tracked": "true", "archived": "true"},
    {"archived": "true"},
    {"include_archived": "true"},
    {"tracked": "true", "category_id": "K1"},
    {"tracked": "false", "category_id": "K2"},
)
# aktyor -> (xodim kaliti, kanonik ko'rish doirasi)
AKTYORLAR = {"ega": ("ega@-", None), "A_ga_boglangan": ("omborchi@A", {"A"}),
             "boglanmagan": ("menejer@-", None)}


def _vid(v):
    return "&".join(f"{k}={x}" for k, x in v.items()) or "none"


@pytest.mark.parametrize("aktyor", list(AKTYORLAR))
@pytest.mark.parametrize("variant", VARIANTLAR, ids=_vid)
def test_PARITET_har_variant_MUSTAQIL_oracle_bilan_AYNAN(client, dokonlar, variant, aktyor):
    from app.db.session import SessionLocal
    d = dokonlar["T"]
    kalit, doira = AKTYORLAR[aktyor]
    so = dict(variant)
    if "branch_id" in so:
        doira = {so["branch_id"]}
        so["branch_id"] = d["fil"][so["branch_id"]]
    if "category_id" in so:
        so["category_id"] = d["kat"][so["category_id"]]
    r = client.get(_url(**so), headers=d["x"][kalit]["H"])
    assert r.status_code == 200, r.text
    kutilgan = _kutilgan(
        d, q=variant.get("q"),
        tracked=None if "tracked" not in variant else variant["tracked"] == "true",
        archived=variant.get("archived") == "true",
        include_archived=variant.get("include_archived") == "true", kat=variant.get("category_id"))
    assert kutilgan, "variant bo'sh — sinov hech narsani o'lchamaydi"
    db = SessionLocal()
    try:
        _solishtir(db, d, r.json(), kutilgan, None if doira is None else {d["fil"][f] for f in doira})
    finally:
        db.close()


# ══ 2 · FILIAL MA'NOSI — kanonik doira, actor_branch EMAS ═══════════════════

def _bitta(client, d, nom, kalit, **kw):
    r = client.get(_url(tracked="true", **kw), headers=d["x"][kalit]["H"])
    assert r.status_code == 200, r.text
    x = [i for i in r.json() if i["name"] == nom]
    assert len(x) == 1, r.json()
    return x[0]["stock"], x[0]["min_stock"], x[0]["sold_qty"]


def test_tracked_true_FILIAL_doirasi_KANONIK_actor_branch_EMAS(client, dokonlar):
    """⚠️  Ega uchun actor_branch — birinchi filial (A). Agar `tracked=true` jimgina
    actor_branch'ga o'tsa, ega 12 emas 7 ko'rardi. `sold_qty` — KOMPANIYA bo'yicha:
    A ga bog'langan xodim B dagi sotuvni ham ko'radi (avvalgi xulq, o'zgarmaydi)."""
    d = dokonlar["T"]
    fa, fb = d["fil"]["A"], d["fil"]["B"]
    # Qatiq: A 7/2, B 5/4; sotuv 3(A)+2(B) oyna ichida, 11(A) tashqarida.
    assert _bitta(client, d, "Qatiq kuzatuvli", "ega@-") == (12.0, 4.0, 5.0)
    assert _bitta(client, d, "Qatiq kuzatuvli", "omborchi@A") == (7.0, 2.0, 5.0)
    assert _bitta(client, d, "Qatiq kuzatuvli", "menejer@-") == (12.0, 4.0, 5.0)
    assert _bitta(client, d, "Qatiq kuzatuvli", "ega@-", branch_id=fa) == (7.0, 2.0, 5.0)
    assert _bitta(client, d, "Qatiq kuzatuvli", "ega@-", branch_id=fb) == (5.0, 4.0, 5.0)
    # Sut: faqat A da qoldiq, yagona sotuv B da.
    assert _bitta(client, d, "Sut kuzatuvli", "omborchi@A") == (9.5, 1.0, 1.5)
    assert _bitta(client, d, "Sut kuzatuvli", "menejer@B") == (0.0, 0.0, 1.5)
    assert _bitta(client, d, "Sut kuzatuvli", "ega@-", branch_id=fb) == (0.0, 0.0, 1.5)
    assert _bitta(client, d, "Tuz kuzatuvli qoldiqsiz", "ega@-") == (0.0, 0.0, 0.0)


# ══ 3 · SALBIY NAZORAT — bo'sh natija tekshiruvni CHETLAB O'TMAYDI ═══════════

def test_BOSH_natijada_ham_branch_id_TEKSHIRUVI_OLDIN_403_400(client, dokonlar):
    """⚠️  `return []` tekshiruvdan OLDIN tursa, begona/ruxsatsiz filial 400/403 o'rniga
    jimgina 200 [] olardi. Har holat moslik BOR va YO'Q natijada sinaladi."""
    t, u = dokonlar["T"], dokonlar["U"]
    hA, ega = t["x"]["omborchi@A"]["H"], t["x"]["ega@-"]["H"]
    for q in ({}, {"q": "hech-qanday-mos-yoq"}):
        # (a) A ga bog'langan xodim — B filiali: 403
        for tracked in ("true", "false"):
            r = client.get(_url(tracked=tracked, branch_id=t["fil"]["B"], **q), headers=hA)
            assert r.status_code == 403, (tracked, q, r.text)
        # (b) boshqa do'kon filiali: 400
        r = client.get(_url(tracked="true", branch_id=u["fil"]["A"], **q), headers=ega)
        assert r.status_code == 400, (q, r.text)
        # (c) o'chirilgan filial: 400 (bog'lanmagan xodim uchun ham)
        for h in (ega, t["x"]["menejer@-"]["H"]):
            r = client.get(_url(tracked="true", branch_id=t["fil"]["D"], **q), headers=h)
            assert r.status_code == 400, (q, r.text)
        # nomavjud filial: 400
        r = client.get(_url(tracked="true", branch_id=uuid.uuid4(), **q), headers=ega)
        assert r.status_code == 400, (q, r.text)
    # NAZORAT: o'z filiali ruxsat etiladi — 403 hamma narsaga qaytmayapti.
    ok = client.get(_url(tracked="true", branch_id=t["fil"]["A"]), headers=hA)
    assert ok.status_code == 200 and ok.json(), ok.text


def test_kuzatuvlisiz_dokon_BOSH_royxat_va_NOL_agregat_sorov(client, dokonlar):
    """Asosiy narx nuqsoni: hech narsa qaytmasa, qoldiq/min/sotilgan hisoblanmaydi."""
    v, t = dokonlar["V"], dokonlar["T"]
    hv = v["x"]["ega@-"]["H"]
    with _sql() as got:
        r = client.get(_url(tracked="true"), headers=hv)
    assert r.status_code == 200 and r.json() == [], r.text
    assert got, "tinglovchi hech narsa ushlamadi — sinov o'lchamayapti"
    assert _agregatlar(got) == [], [s for s, _ in _agregatlar(got)]

    # T do'koni, mos kelmaydigan qidiruv — xuddi shunday.
    with _sql() as got:
        r = client.get(_url(tracked="true", q="hech-qanday-mos-yoq"), headers=t["x"]["omborchi@A"]["H"])
    assert r.status_code == 200 and r.json() == [], r.text
    assert _agregatlar(got) == []

    # NAZORAT: natija BO'LSA agregatlar ishlaydi va tinglovchi ularni ko'radi.
    with _sql() as got:
        r = client.get(_url(tracked="false"), headers=hv)
    assert r.status_code == 200 and len(r.json()) == len(_kutilgan(v, tracked=False)) > 0, r.text
    assert len(_agregatlar(got)) == 3, [s for s, _ in got]


def test_boshqa_dokon_mahsuloti_va_ARXIV_ochirilgan_KORINMAYDI(client, dokonlar):
    t, u = dokonlar["T"], dokonlar["U"]
    begona = {str(r["id"]) for r in u["p"].values()}
    for so in ({"tracked": "true"}, {"tracked": "true", "include_archived": "true"},
               {"tracked": "true", "q": "qatiq"}, {"tracked": "false"}):
        body = client.get(_url(**so), headers=t["x"]["ega@-"]["H"]).json()
        assert body and not ({x["id"] for x in body} & begona), so
        # U da miqdorlar x100 — aralashsa T qiymatlari kattalashardi.
        assert all(x["stock"] < 100 and x["sold_qty"] < 100 for x in body), body
    ids = {x["name"] for x in client.get(_url(tracked="true"), headers=t["x"]["ega@-"]["H"]).json()}
    assert "Qatiq arxiv kuzatuvli" not in ids and "Qatiq ochirilgan kuzatuvli" not in ids, ids
    assert "Qatiq kuzatuvli" in ids                                        # nazorat
    ids = {x["name"] for x in client.get(_url(tracked="true", include_archived="true"),
                                         headers=t["x"]["ega@-"]["H"]).json()}
    assert "Qatiq arxiv kuzatuvli" in ids and "Qatiq ochirilgan kuzatuvli" not in ids, ids


# ══ 4 · SQL SHAKLI ═════════════════════════════════════════════════════════

def test_tracked_AGREGATLAR_IN_SELECT_bilan_TORAYADI_id_royxati_EMAS(client, dokonlar):
    """⚠️  Python id ro'yxati bind-parametr chegarasiga uriladi (SQLite 999, psycopg 65535)
    va minglab kuzatuvli mahsulotda so'rovni shishiradi. Cheklov SQL SUBQUERY bo'lishi shart."""
    t = dokonlar["T"]
    cheklov = re.compile(r"\b(inventory|sale_items)\.product_id IN \(SELECT products\.id\s+FROM products\b")
    hamma = {p["id"] for p in t["p"].values()}
    for kalit, so in (("ega@-", {}), ("omborchi@A", {}), ("ega@-", {"q": "qatiq"}),
                      ("ega@-", {"branch_id": t["fil"]["B"]}),
                      ("menejer@-", {"include_archived": "true"})):
        with _sql() as got:
            r = client.get(_url(tracked="true", **so), headers=t["x"][kalit]["H"])
        assert r.status_code == 200 and r.json(), r.text
        agg = _agregatlar(got)
        assert len(agg) == 3, [s for s, _ in agg]
        for s, prm in agg:
            assert cheklov.search(s), s
            assert "track_lots IS" in s, s
            assert not re.search(r"product_id IN \(\?", s), s
            matn = s + repr(prm)
            for pid in hamma:
                assert pid.hex not in matn and str(pid) not in matn, (pid, s, prm)


def _eski_agregatlar(db, company_id, branches):
    """Tuzatishdan OLDINGI `_stock_map` / `_min_map` / `_sold_map` — AYNAN o'sha qurilish
    shu yerga KO'CHIRILGAN (`products.py` yordamchilari CHAQIRILMAYDI)."""
    from app.models.catalog import Product
    from app.models.inventory import Inventory
    from app.models.sales import Sale, SaleItem
    q = (db.query(Inventory.product_id, func.sum(Inventory.qty))
         .join(Product, Product.id == Inventory.product_id)
         .filter(Product.company_id == company_id))
    if branches is not None:
        q = q.filter(Inventory.branch_id.in_(branches))
    q.group_by(Inventory.product_id).all()
    q = (db.query(Inventory.product_id, func.max(Inventory.min_qty))
         .join(Product, Product.id == Inventory.product_id)
         .filter(Product.company_id == company_id))
    if branches is not None:
        q = q.filter(Inventory.branch_id.in_(branches))
    q.group_by(Inventory.product_id).all()
    since = datetime.now(timezone.utc) - timedelta(days=30)
    (db.query(SaleItem.product_id, func.coalesce(func.sum(SaleItem.qty), 0))
     .join(Sale, Sale.id == SaleItem.sale_id)
     .filter(Sale.company_id == company_id, Sale.sold_at >= since)
     .group_by(SaleItem.product_id)
     .all())


def _niqob(got):
    """Vaqt parametri (`since`) har chaqiruvda farq qiladi — faqat u niqoblanadi.
    SQLite parametrlari — kortej, psycopg'niki — lug'at (nomli)."""
    vaqt = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:")

    def _v(v):
        return "<since>" if isinstance(v, datetime) or (isinstance(v, str) and vaqt.match(v)) else v

    return [(s, tuple(sorted((k, _v(v)) for k, v in p.items())) if isinstance(p, dict)
             else tuple(_v(v) for v in (p or ()))) for s, p in got]


@pytest.mark.parametrize("kalit,filial", [("ega@-", None), ("omborchi@A", None), ("ega@-", "B")])
def test_tracked_SIZ_yol_SQL_OZGARMAGAN(client, dokonlar, kalit, filial):
    """POS sync, Dashboard, Mahsulotlar, mobil — `tracked` yubormaydi. Ularning agregat
    so'rovlari tuzatishdan oldingisi bilan MATN va parametr bo'yicha AYNAN."""
    from app.db.session import SessionLocal
    t = dokonlar["T"]
    so = {"branch_id": t["fil"][filial]} if filial else {}
    with _sql() as got:
        r = client.get(_url(**so), headers=t["x"][kalit]["H"])
    assert r.status_code == 200 and r.json(), r.text
    yangi = _niqob(_agregatlar(got))
    doira = {t["fil"][filial]} if filial else ({t["fil"]["A"]} if kalit == "omborchi@A" else None)
    db = SessionLocal()
    try:
        with _sql() as eski:
            _eski_agregatlar(db, t["cid"], doira)
    finally:
        db.close()
    assert len(yangi) == 3 and yangi == _niqob(eski), (yangi, _niqob(eski))
    assert all("IN (SELECT products.id" not in s for s, _ in yangi)


# ══ 5 · RUXSAT MATRITSASI — `tracked` autentifikatsiyadan boshqa narsa talab qilmaydi ══

@pytest.mark.parametrize("kalit,doira", [
    ("ega@-", None), ("administrator@-", None), ("administrator@A", {"A"}),
    ("menejer@-", None), ("menejer@B", {"B"}), ("omborchi@A", {"A"}),
    ("kassir@A", {"A"}), ("kassir@-", None),
])
def test_RUXSAT_matritsasi_har_rol_200_va_doira_KANONIK(client, dokonlar, kalit, doira):
    from app.db.session import SessionLocal
    t = dokonlar["T"]
    r = client.get(_url(tracked="true"), headers=t["x"][kalit]["H"])
    assert r.status_code == 200, (kalit, r.text)
    kutilgan = _kutilgan(t, tracked=True)
    db = SessionLocal()
    try:
        _solishtir(db, t, r.json(), kutilgan, None if doira is None else {t["fil"][f] for f in doira})
    finally:
        db.close()
    qatiq = next(x for x in r.json() if x["name"] == "Qatiq kuzatuvli")
    kutilgan_qoldiq = {None: 12.0, "A": 7.0, "B": 5.0}[None if doira is None else next(iter(doira))]
    assert qatiq["stock"] == kutilgan_qoldiq, (kalit, qatiq)


def test_RUXSAT_tokensiz_401(client, dokonlar):
    """NAZORAT: autentifikatsiya talabi o'z joyida — `tracked` uni chetlab o'tmaydi."""
    assert client.get(_url(tracked="true")).status_code == 401
    yaroqsiz = {"Authorization": "Bearer yaroqsiz"}
    assert client.get(_url(tracked="true"), headers=yaroqsiz).status_code == 401
