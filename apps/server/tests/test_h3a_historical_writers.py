# -*- coding: utf-8 -*-
"""H3a — TARIXIY BIZNES YOZUVCHILARI: vaqt sodiqligi + xronologiya gardi.

DOIRA (ega tasdiqlagan H3a): allaqachon ICHKI bo'lgan 5 yozuvchi —
xarid yaratish, qabul commit, qaytarish, inventarizatsiya, yetkazuvchiga to'lov.
Ajratish talab qiladigan uchtasi (hisobdan chiqarish, kassa amali, mijoz qarzi)
H3b ga tegishli va BU YERDA YO'Q.

EGA QO'YGAN QO'SHIMCHA MAJBURIY DARVOZA
=======================================
«Tarixiy yozuvchi yaratadigan HAR BIR StockMovement / partiya harakati / audit
harakati timestampi tarixiy `at` bilan mos bo'lsin. Stock-count xronologiya
gardi `MAX(stock_movements.created_at) > at` ga tayangani uchun birorta tarixiy
yozuvchi harakatni `now()` bilan muhrlab qo'ymasligi kerak.»

⚠️  NEGA BU DARVOZA GARDNING ISHLASH SHARTI. Gard eng kech harakat vaqtini
    o'qiydi. Agar bitta yozuvchi harakatni BUGUNGI payt bilan yozsa, o'sha
    (mahsulot, filial) uchun `MAX(created_at)` BUGUNGA sakraydi va keyingi HAR
    QANDAY tarixiy sanoq rad etiladi — ya'ni gard haqiqiy xatoni emas, o'z
    tizimining nuqsonini to'sib, rad etishlari ma'nosiz bo'lib qolardi.
    Bitta o'tkazib yuborilgan soat butun mexanizmni buzadi.

⚠️  TO'G'RIDAN ORM BILAN BIZNES HODISASI YOZILMAYDI. Hodisalar faqat kanonik
    yo'ldan: `_create_purchase_once`, `_commit_once`, `_create_return_once`,
    `_stock_count_once`, `_pay_supplier_once`, `create_sale`, `open_shift_svc`.
    ORM FAQAT sahna qurishda (do'kon/filial/xodim/mahsulot/yetkazuvchi).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services import historical as H

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
PLAN = "h3a-plan-1"
#  >120 kun — `/sync/push` 60-kunlik klampidan ATAYLAB tashqarida.
DEPTH = 140


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _aw(dt):
    """SQLite `DateTime(timezone=True)` ni NAIVE qaytaradi — UTC ga keltiramiz.

    ⚠️  TEST harness masalasi, ishlab chiqarish nuqsoni EMAS (Postgres aware
        qaytaradi). Normalizatorsiz assertion'lar `TypeError` bilan qulardi.
    """
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _demo(currency: str = "KGS", code_prefix: str = "demo"):
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="H3a demo",
                       code=f"{code_prefix}-h3a-{uuid.uuid4().hex[:6]}", currency=currency)
        db.add(comp)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01",
                    timezone=TZ, is_active=True, created_at=NOW - timedelta(days=400))
        db.add(br)
        db.flush()
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                       full_name="H3a kassir", phone=f"+9987{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        db.commit()
        from app.core.security import create_access_token
        tok = create_access_token(str(emp.id),
                                  {"role": "ega", "company_id": str(comp.id), "sv": 0})
        return {"cid": comp.id, "bid": br.id, "eid": emp.id, "cur": currency,
                "H": {"Authorization": f"Bearer {tok}"}}


def _emp(d):
    from app.models.auth import Employee
    with _db() as db:
        return db.get(Employee, d["eid"])


def _company(d):
    from app.models.org import Company
    with _db() as db:
        return db.get(Company, d["cid"])


def _mahsulot(d, unit_code="dona", qty=0):
    """Qoldiq ATAYLAB 0: zanjirdagi har balans FAQAT zanjir hodisalaridan chiqsin."""
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    with _db() as db:
        u = db.query(Unit).filter_by(code=unit_code).one()
        p = Product(id=uuid.uuid4(), company_id=d["cid"],
                    name=f"H3a {unit_code} {uuid.uuid4().hex[:5]}",
                    article_code="H3A-" + uuid.uuid4().hex[:10], sku=uuid.uuid4().hex[:8],
                    unit_id=u.id, base_buy_price=500, base_sell_price=1000, tax_rate=0)
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, branch_id=d["bid"], qty=Decimal(str(qty)),
                         min_qty=0, updated_at=NOW))
        db.commit()
        return p.id


def _kuzatuvli_mahsulot(d, qty=0):
    """KUZATUVLI (partiyali) mahsulot. Sahna — ORM, biznes hodisasi emas.

    ⚠️  NEGA ALOHIDA KERAK (o'lchangan): xarid yozuvchisi kuzatuvli mahsulotni
        RAD etadi (`stock_gate.http_assert_untracked`), inventarizatsiyaning
        PARTIYA yo'li va uning AUDIT qatori esa `if _plan is not None:` ichida,
        ya'ni FAQAT kuzatuvli mahsulotda ishlaydi. Demak bitta kuzatuvsiz
        mahsulotli zanjir eganing uch vaqt oilasidan ikkitasini — partiya
        harakati va sanoq auditini — UMUMAN sinalmagan qoldirardi.
    """
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    with _db() as db:
        u = db.query(Unit).filter_by(code="dona").one()
        p = Product(id=uuid.uuid4(), company_id=d["cid"],
                    name=f"H3a kuzatuvli {uuid.uuid4().hex[:5]}",
                    article_code="H3AT-" + uuid.uuid4().hex[:10], sku=uuid.uuid4().hex[:8],
                    unit_id=u.id, base_buy_price=500, base_sell_price=1000, tax_rate=0,
                    track_lots=True)
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, branch_id=d["bid"], qty=Decimal(str(qty)),
                         min_qty=0, updated_at=NOW))
        db.commit()
        return p.id


def _yetkazuvchi(d):
    from app.models.purchasing import Supplier
    with _db() as db:
        s = Supplier(id=uuid.uuid4(), company_id=d["cid"],
                     name=f"H3a yetkazuvchi {uuid.uuid4().hex[:5]}")
        db.add(s)
        db.commit()
        return s.id


def _harakatlar(pid, bid):
    """(created_at, qty, balance_after, type) — VAQT bo'yicha tartiblangan."""
    from app.models.inventory import StockMovement
    with _db() as db:
        rows = (db.query(StockMovement)
                .filter(StockMovement.product_id == pid, StockMovement.branch_id == bid)
                .order_by(StockMovement.created_at, StockMovement.id).all())
        return [(_aw(r.created_at), Decimal(str(r.qty)),
                 None if r.balance_after is None else Decimal(str(r.balance_after)),
                 r.type.value if hasattr(r.type, "value") else str(r.type)) for r in rows]


def _qoldiq(pid, bid):
    from app.models.inventory import Inventory
    with _db() as db:
        inv = (db.query(Inventory)
               .filter(Inventory.product_id == pid, Inventory.branch_id == bid).first())
        return None if inv is None else Decimal(str(inv.qty))


@pytest.fixture(autouse=True)
def _sxema(client):
    """Sxemani `conftest.client` quradi (`initdb.main()` + `seed.run()`).

    ⚠️  Bu testlar yozuvchilarni TO'G'RIDAN chaqiradi (marshrut orqali emas,
        chunki `at` ommaviy sxemada YO'Q va bo'lmasligi ham kerak), shu bois
        `client` ni ANIQ talab qilish SHART — aks holda jadvallar yo'q.
    """
    return client


@pytest.fixture()
def no_push(monkeypatch):
    """Tashqi chiqishni SANAYDI (bo'g'ishni emas) — H2 bilan ayni naqsh."""
    from app.services import push
    sent: list = []
    monkeypatch.setattr(push, "send_ex", lambda *a, **k: (sent.append(a), (0, []))[1])

    class _S:
        fcm_enabled = True
    monkeypatch.setattr(push, "settings", _S())
    return sent


# ══════════════════════════════════════════════════════════════════════════
#  XRONOLOGIK ZANJIR — eganing asosiy talabi
#
#  BALANSLAR ATAYLAB FARQLI: 10 -> 7 -> 9 -> 5, deltalar +10, -3, +2, -4.
#  Hech bir juftlik almashsa ham, bir qadam siljisa ham natija BOSHQA bo'ladi,
#  ya'ni assertion aniq: teng balanslar bo'lsa xato JIMGINA o'tib ketardi.
# ══════════════════════════════════════════════════════════════════════════
def _zanjir(d, pid, sid, *, plan=PLAN):
    """xarid(+10) -> sotuv(-3) -> qaytarish(+2) -> sanoq(=5). FAQAT kanonik yo'l."""
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once
    from app.api.v1.purchases import _create_purchase_once
    from app.api.v1.sales import _create_return_once
    from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
    from app.schemas.sales import ReturnCreate, ReturnItemIn, SaleCreate, SaleItemIn
    from app.services.sales import create_sale
    from app.services.shifts import open_shift_svc

    class _Open:
        opening_cash = 100000.0
        terminal_id = None
        till_id = None

    day = (NOW - timedelta(days=DEPTH)).replace(hour=0, minute=0, second=0, microsecond=0)
    T = {"shift": day + timedelta(hours=8),
         "purchase": day + timedelta(hours=9),
         "sale": day + timedelta(days=1, hours=10),
         "return": day + timedelta(days=2, hours=11),
         "count": day + timedelta(days=3, hours=12)}
    out = {"T": T}
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])

        with H.enter(db, comp, plan_id=plan, instant=T["shift"]) as ctx:
            open_shift_svc(_Open(), emp, db, at=T["shift"],
                           client_uuid=ctx.key("shift", "open"))

        #  1) XARID +10  (status="debt": naqd oyog'i yo'q — zanjir ZAXIRAga qaratilgan)
        with H.enter(db, comp, plan_id=plan, instant=T["purchase"]) as ctx:
            out["purchase"] = _create_purchase_once(
                PurchaseCreate(supplier_id=sid, status="debt",
                               items=[PurchaseItemIn(product_id=pid, qty=10, unit_cost=500)],
                               client_uuid=ctx.key("purchase")),
                emp, db, at=T["purchase"])

        #  2) SOTUV -3
        with H.enter(db, comp, plan_id=plan, instant=T["sale"]) as ctx:
            sale = create_sale(db, emp, SaleCreate(
                items=[SaleItemIn(product_id=pid, qty=3, unit_price=1000)],
                payment_method="cash", given_amount=3000,
                client_uuid=ctx.key("sale")), at=T["sale"])
            out["sale_id"] = sale.id
            out["sold_at"] = _aw(sale.sold_at)

        #  3) QAYTARISH +2 (restock)
        with H.enter(db, comp, plan_id=plan, instant=T["return"]) as ctx:
            out["return"] = _create_return_once(
                ReturnCreate(original_sale_id=out["sale_id"], restock=True,
                             refund_method="cash",
                             items=[ReturnItemIn(product_id=pid, qty=2, unit_price=1000)],
                             client_uuid=ctx.key("return")),
                emp, db, at=T["return"])

        #  4) SANOQ = 5  (MUTLAQ yozuvchi: 9 -> 5, farq -4)
        with H.enter(db, comp, plan_id=plan, instant=T["count"]) as ctx:
            out["count"] = _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=5)],
                        client_uuid=ctx.key("count")),
                emp, db, at=T["count"])
    return out


def test_01_xronologik_zanjir_HARAKAT_vaqtlari_va_BALANS_ketma_ketligi(no_push):
    """Eganing asosiy talabi: harakat timestamplari VA `balance_after` ketma-ketligi."""
    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)
    T = z["T"]

    mv = _harakatlar(pid, d["bid"])
    #  Kutilgan: +10 (10) -> -3 (7) -> +2 (9) -> -4 (5)
    kutilgan = [(T["purchase"], Decimal("10"), Decimal("10")),
                (T["sale"], Decimal("-3"), Decimal("7")),
                (T["return"], Decimal("2"), Decimal("9")),
                (T["count"], Decimal("-4"), Decimal("5"))]
    assert len(mv) == len(kutilgan), \
        f"harakat soni KUTILGANDAN farq: {len(mv)} != {len(kutilgan)} — {mv}"

    for i, ((t_k, q_k, b_k), (t, q, b, tip)) in enumerate(zip(kutilgan, mv)):
        assert abs((t - t_k).total_seconds()) < 2, \
            f"{i}-harakat ({tip}) vaqti TARIXIY emas: {t} != {t_k}"
        assert q == q_k, f"{i}-harakat ({tip}) miqdori: {q} != {q_k}"
        assert b == b_k, \
            (f"{i}-harakat ({tip}) `balance_after` KETMA-KETLIKKA mos emas: "
             f"{b} != {b_k}. To'liq zanjir: {mv}")

    #  Vaqt bo'yicha tartib biznes tartibi bilan AYNI (balanslar farqli bo'lgani
    #  uchun bu tekshiruv haqiqiy kuchga ega).
    vaqtlar = [t for t, _, _, _ in mv]
    assert vaqtlar == sorted(vaqtlar), f"harakatlar VAQT bo'yicha tartiblanmagan: {vaqtlar}"

    assert _qoldiq(pid, d["bid"]) == Decimal("5"), \
        f"yakuniy qoldiq sanoqqa teng bo'lishi SHART: {_qoldiq(pid, d['bid'])}"


def test_02_birorta_harakat_BUGUNGI_sana_bilan_muhrlanMAYDI(no_push):
    """Eganing darvozasi: `now()` bilan muhrlangan harakat BO'LMASIN.

    ⚠️  BU GARDNING ISHLASH SHARTI, shunchaki tartiblilik emas: bugungi sanali
        harakat `MAX(created_at)` ni BUGUNGA ko'tarib, keyingi tarixiy sanoqni
        ma'nosiz ravishda rad etardi.
    """
    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)
    chegara = NOW - timedelta(days=DEPTH - 10)      # zanjir oynasidan ANIQ keyin

    bugungilar = [(t, tip) for t, _, _, tip in _harakatlar(pid, d["bid"]) if t > chegara]
    assert not bugungilar, \
        (f"TARIXIY zanjirda BUGUNGI sanali harakat bor: {bugungilar}. Ya'ni biror "
         f"yozuvchi `now()` bilan muhrlagan va xronologiya gardi ishonchsiz.")

    #  Hujjat sanalari ham tarixiy bo'lishi SHART (ikkinchi vaqt manbai `_biz_date`).
    #  `_create_purchase_once` ORM obyektini qaytaradi (dict EMAS) — do'kon
    #  bo'yicha qayta o'qiymiz, sessiyadan uzilgan obyektga tayanmaymiz.
    from app.models.purchasing import Purchase
    with _db() as db:
        pur = db.query(Purchase).filter(Purchase.company_id == d["cid"]).one()
        assert pur.purchase_date == z["T"]["purchase"].date(), \
            f"`purchase_date` TARIXIY emas: {pur.purchase_date} != {z['T']['purchase'].date()}"
        assert _aw(pur.created_at) < chegara, \
            f"`purchases.created_at` BUGUNGI: {pur.created_at}"


def test_03_qaytarish_created_at_TARIXIY(no_push):
    """`returns.created_at` — `at=` BILAN YOPILMAYDIGAN blocker.

    U `TimestampMixin.server_default=func.now()` dan keladi, ya'ni yozuvchiga
    `at` uzatish YETARLI EMAS edi. Va bu ustun `reports.py` da hisobot davri
    kaliti sifatida 39 joyda ishlatiladi: tuzatilmasa demo HAMMA JOYDA to'g'ri
    ko'rinib, FAQAT qaytarishlar hisobotida yolg'on bo'lardi.
    """
    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)

    from app.models.sales import Return
    with _db() as db:
        rid = z["return"]["id"]
        ret = db.get(Return, uuid.UUID(rid) if isinstance(rid, str) else rid)
        assert ret is not None, f"qaytarish topilmadi: {z['return']}"
        assert abs((_aw(ret.created_at) - z["T"]["return"]).total_seconds()) < 2, \
            (f"`returns.created_at` TARIXIY emas: {ret.created_at} != "
             f"{z['T']['return']} — server_default BOSIB o'tilmagan")


def test_04_audit_izi_ham_TARIXIY(no_push):
    """Ega darvozasi «audit movement» ni ham nomlaydi: `audit_log.created_at`."""
    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)
    chegara = NOW - timedelta(days=DEPTH - 10)

    from app.models.sync import AuditLog
    with _db() as db:
        rows = (db.query(AuditLog)
                .filter(AuditLog.actor_id == d["eid"]).all())
        assert rows, "audit izi UMUMAN yozilmagan — test o'z sahnasini tekshirmayapti"
        kech = [(r.entity, _aw(r.created_at)) for r in rows if _aw(r.created_at) > chegara]
        assert not kech, f"audit izi BUGUNGI sana bilan yozilgan: {kech}"


# ══════════════════════════════════════════════════════════════════════════
#  TARTIBSIZ SANOQ — MUTATSIYADAN OLDIN fail-closed
# ══════════════════════════════════════════════════════════════════════════
def test_05_TARTIBSIZ_sanoq_MUTATSIYADAN_OLDIN_rad_etiladi(no_push):
    """Keyinroq harakat bo'lgan holatda ORQAGA sanalgan sanoq RAD etilishi SHART.

    ⚠️  VA NOL MUTATSIYA: rad etish qulfdan va yozuvdan OLDIN bo'ladi, shu bois
        harakat soni, qoldiq va audit izi O'ZGARMASLIGI shart.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once
    from app.models.sync import AuditLog

    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)

    oldin_mv = _harakatlar(pid, d["bid"])
    oldin_qty = _qoldiq(pid, d["bid"])
    with _db() as db:
        oldin_audit = db.query(AuditLog).filter(AuditLog.actor_id == d["eid"]).count()

    #  Zanjirning ENG KECH harakati `count` paytida. Undan OLDINGI paytga
    #  sanoq yozishga urinamiz — ya'ni TARTIBSIZ.
    t_orqaga = z["T"]["sale"] + timedelta(hours=1)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_orqaga) as ctx:
            with pytest.raises(RuntimeError, match="TARTIBSIZ"):
                _stock_count_once(
                    CountIn(items=[CountItem(product_id=pid, counted=999)],
                            client_uuid=ctx.key("tartibsiz", "sanoq")),
                    emp, db, at=t_orqaga)
        db.rollback()

    assert _harakatlar(pid, d["bid"]) == oldin_mv, \
        "TARTIBSIZ sanoq HARAKAT yozdi — rad etish mutatsiyadan OLDIN emas"
    assert _qoldiq(pid, d["bid"]) == oldin_qty, \
        f"TARTIBSIZ sanoq QOLDIQNI o'zgartirdi: {oldin_qty} -> {_qoldiq(pid, d['bid'])}"
    with _db() as db:
        keyin_audit = db.query(AuditLog).filter(AuditLog.actor_id == d["eid"]).count()
    assert keyin_audit == oldin_audit, \
        f"TARTIBSIZ sanoq AUDIT izi yozdi: {oldin_audit} -> {keyin_audit}"


def test_06_AYNI_paytdagi_sanoq_RAD_ETILMAYDI(no_push):
    """Tenglik xronologiya buzilishi EMAS — u idempotentlik kalitiga tegishli.

    Gard QAT'IY `>` bilan ishlaydi: aks holda ayni paytdagi qardosh hodisa
    (masalan ayni sekunddagi ikkinchi qator) jimgina bloklanardi.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)
    t_ayni = z["T"]["count"]
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_ayni) as ctx:
            #  Xato KO'TARILMASLIGI shart (natija dublikat bo'lishi mumkin —
            #  bu test XRONOLOGIYA gardini o'lchaydi, idempotentlikni emas).
            _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=5)],
                        client_uuid=ctx.key("ayni", "payt", "sanoq")),
                emp, db, at=t_ayni)
        db.commit()


def test_07_KEYINGI_sanoq_OTADI(no_push):
    """To'g'ri tartibda davom etish ISHLAYDI — gard haqiqiy rejani to'smaydi."""
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)
    t_keyin = z["T"]["count"] + timedelta(days=1, hours=3)
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_keyin) as ctx:
            _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=4)],
                        client_uuid=ctx.key("keyingi", "sanoq")),
                emp, db, at=t_keyin)
        db.commit()

    mv = _harakatlar(pid, d["bid"])
    assert len(mv) == 5, f"keyingi sanoq harakat yozmadi: {mv}"
    assert mv[-1][2] == Decimal("4"), f"oxirgi `balance_after` 4 bo'lishi SHART: {mv[-1]}"
    assert abs((mv[-1][0] - t_keyin).total_seconds()) < 2


def test_08_NORMAL_sanoq_ESKI_qatorda_ham_RAD_ETILMAYDI():
    """⚠️  GARD NORMAL YO'LGA TEGMASLIGI shart — kontekst YO'Q, demak gard O'CHIQ.

    Bu eng muhim regressiya tekshiruvi: do'konda 140 kun tegilmagan mahsulot
    bo'lishi MUTLAQO normal va uni bugun sanash RAD ETILMASLIGI kerak.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once
    from app.models.inventory import StockMovement
    from app.models.enums import MovementType

    d = _demo()
    pid = _mahsulot(d, qty=7)
    #  ORM bilan ESKI harakat — bu BIZNES hodisasi emas, sahna (eski qoldiq izi).
    with _db() as db:
        db.add(StockMovement(product_id=pid, branch_id=d["bid"],
                             type=MovementType.adjustment, qty=Decimal("7"),
                             balance_after=Decimal("7"), ref_type="sahna",
                             created_at=NOW - timedelta(days=DEPTH)))
        db.commit()

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        #  Kontekst YO'Q va `at` YO'Q — ODDIY sanoq.
        _stock_count_once(CountIn(items=[CountItem(product_id=pid, counted=9)]), emp, db)
        db.commit()

    assert _qoldiq(pid, d["bid"]) == Decimal("9")
    mv = _harakatlar(pid, d["bid"])
    assert abs((mv[-1][0] - NOW).total_seconds()) < 600, \
        f"NORMAL sanoq HOZIRGI vaqt bilan yozilishi SHART: {mv[-1][0]}"


def test_09_kontekst_FAOL_lekin_at_YOQ_RAD(no_push):
    """Kontekst ichida `at` ni UNUTISH ham xato — jimgina BUGUN yozilmasin."""
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    d = _demo()
    pid = _mahsulot(d, qty=3)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=NOW - timedelta(days=DEPTH)):
            with pytest.raises(RuntimeError, match="`at` berilmadi"):
                _stock_count_once(CountIn(items=[CountItem(product_id=pid, counted=2)]),
                                  emp, db)
        db.rollback()
    assert _qoldiq(pid, d["bid"]) == Decimal("3"), "rad etilgan sanoq qoldiqni o'zgartirdi"


# ══════════════════════════════════════════════════════════════════════════
#  HAR YOZUVCHI: kontekstsiz `at` RAD + normal yo'l HOZIRGI vaqt
# ══════════════════════════════════════════════════════════════════════════
def test_10_har_yozuvchi_kontekstSIZ_at_ni_RAD_etadi():
    """Tarixiy qobiliyat DARVOZAGA bog'langan, marshrutga emas (H1 invarianti)."""
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once
    from app.api.v1.purchases import _create_purchase_once
    from app.schemas.purchase import PurchaseCreate, PurchaseItemIn

    d = _demo()
    pid, sid = _mahsulot(d, qty=5), _yetkazuvchi(d)
    t = NOW - timedelta(days=DEPTH)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with pytest.raises(RuntimeError, match="tarixiy kontekst YO'Q"):
            _stock_count_once(CountIn(items=[CountItem(product_id=pid, counted=2)]),
                              emp, db, at=t)
        db.rollback()
        with pytest.raises(RuntimeError, match="tarixiy kontekst YO'Q"):
            _create_purchase_once(
                PurchaseCreate(supplier_id=sid, status="debt",
                               items=[PurchaseItemIn(product_id=pid, qty=1, unit_cost=100)]),
                emp, db, at=t)
        db.rollback()
    assert _qoldiq(pid, d["bid"]) == Decimal("5")


def test_11_BOSHQA_dokon_konteksti_RAD():
    """Bitta do'kon kontekstida turib boshqasiga tarixiy yozuv QILIB BO'LMAYDI."""
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    a, b = _demo(), _demo()
    pid = _mahsulot(b, qty=4)
    t = NOW - timedelta(days=DEPTH)
    with _db() as db:
        emp_b = db.get(type(_emp(b)), b["eid"])
        with H.enter(db, _company(a), plan_id=PLAN, instant=t):
            with pytest.raises(RuntimeError, match="BOSHQA do'konga"):
                _stock_count_once(CountIn(items=[CountItem(product_id=pid, counted=1)]),
                                  emp_b, db, at=t)
        db.rollback()
    assert _qoldiq(pid, b["bid"]) == Decimal("4")


def test_12_yetkazuvchiga_TOLOV_tarixiy(no_push):
    """`supplier_payments.paid_at` / `created_at` va qarz oyog'i tarixiy bo'lsin."""
    from app.api.v1.purchases import SupplierPaymentIn, _pay_supplier_once

    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)          # `debt` xarid -> yetkazuvchida qarz bor
    t_pay = z["T"]["count"] + timedelta(days=1)
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_pay) as ctx:
            _pay_supplier_once(sid, SupplierPaymentIn(amount=1000, method="cash",
                                                      client_uuid=ctx.key("suppay")),
                               emp, db, at=t_pay)
        db.commit()

    from app.models.purchasing import SupplierPayment
    with _db() as db:
        pay = (db.query(SupplierPayment)
               .filter(SupplierPayment.supplier_id == sid).one())
        assert abs((_aw(pay.paid_at) - t_pay).total_seconds()) < 2, \
            f"`paid_at` TARIXIY emas: {pay.paid_at}"
        assert abs((_aw(pay.created_at) - t_pay).total_seconds()) < 2, \
            f"`created_at` TARIXIY emas: {pay.created_at}"


def test_13_QABUL_commit_tarixiy(no_push):
    """Qabul yo'li: harakat, partiya va hujjat sanasi tarixiy bo'lsin."""
    from app.api.v1.receiving import CommitIn, _commit_once

    d = _demo()
    sid = _yetkazuvchi(d)
    pid = _mahsulot(d)
    t = (NOW - timedelta(days=DEPTH)).replace(hour=9, minute=0, second=0, microsecond=0)
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            _commit_once(CommitIn(supplier_id=sid, payment="credit",
                                  items=[{"product_id": pid, "qty": 6, "unit_cost": 400}],
                                  client_uuid=ctx.key("recv")),
                         emp, db, at=t)
        db.commit()

    mv = _harakatlar(pid, d["bid"])
    assert len(mv) == 1, f"qabul AYNAN bitta harakat yozishi kutilgan: {mv}"
    assert abs((mv[0][0] - t).total_seconds()) < 2, f"qabul harakati TARIXIY emas: {mv[0]}"
    assert mv[0][2] == Decimal("6"), f"`balance_after` 6 bo'lishi SHART: {mv[0]}"

    from app.models.purchasing import Purchase
    with _db() as db:
        pur = db.query(Purchase).filter(Purchase.company_id == d["cid"]).one()
        assert pur.purchase_date == t.date(), \
            f"qabul `purchase_date` TARIXIY emas: {pur.purchase_date} != {t.date()}"


def test_14_tashqi_chiqish_EFFEKTI_NOL(no_push):
    """Tarixiy replay tashqi xabar YUBORMAYDI (H1 bo'g'ish siyosati)."""
    d = _demo()
    #  min_qty ni YUQORI qilamiz: sanoq kam-qoldiq kesishuvini YONDIRADI.
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    from app.models.inventory import Inventory
    with _db() as db:
        inv = db.query(Inventory).filter(Inventory.product_id == pid).one()
        inv.min_qty = 50
        db.commit()

    _zanjir(d, pid, sid)
    assert no_push == [], f"tarixiy replay tashqi xabar yubordi: {no_push}"


# ══════════════════════════════════════════════════════════════════════════
#  BAJARUVCHI (D3) UCHUN SHARTLAR — taxmin emas, SINALGAN
# ══════════════════════════════════════════════════════════════════════════
def test_15_API_orqali_qoldiqli_mahsulot_yaratish_gardni_YOLGON_RAD_ga_olib_keladi(client):
    """⚠️  BAJARUVCHI SHARTI: tarixiy reja boshlanishidan OLDIN mahsulot API orqali
        `stock > 0` bilan YARATILMASIN.

    `POST /products/bulk` qoldiq berilsa `adjustment` harakatini BUGUNGI payt
    bilan yozadi (`api/v1/products.py`). Shundan keyin o'sha (mahsulot, filial)
    uchun `MAX(created_at)` BUGUN bo'lib qoladi va rejadagi HAR QANDAY tarixiy
    sanoq rad etiladi — ya'ni gard haqiqiy xatoni emas, tayyorlash usulini
    jazolaydi. Rad etish sababi ma'lumot haqida TO'G'RI, sabab haqida esa
    butunlay CHALG'ITUVCHI bo'lardi.

    Bu test ayni holatni QAYD ETADI (nuqson deb emas, SHART deb): H2/H3a
    sahna qurishda mahsulotni xom ORM bilan, harakatSIZ yaratadi — shu bois
    bajaruvchi ham AYNAN shunday qilishi kerak.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    d = _demo()
    r = client.post("/api/v1/products/bulk", headers=d["H"], json={"items": [
        {"name": f"H3a API {uuid.uuid4().hex[:5]}", "sell_price": 1000, "buy_price": 500,
         "unit_code": "dona", "stock": 12}]})
    assert r.status_code == 200, r.text
    pid = uuid.UUID(r.json()[0]["id"])

    #  API yo'li BUGUNGI sanali harakat yozgani TASDIQLANADI (sahnaning o'zi).
    mv = _harakatlar(pid, d["bid"])
    assert mv and abs((mv[-1][0] - NOW).total_seconds()) < 600,         f"API yo'li bugungi sanali harakat yozishi KUTILGAN edi: {mv}"

    #  Va shuning uchun tarixiy sanoq RAD etiladi — gard ishlayapti, lekin
    #  sabab TAYYORLASH USULIDA.
    t = NOW - timedelta(days=DEPTH)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            with pytest.raises(RuntimeError, match="TARTIBSIZ"):
                _stock_count_once(
                    CountIn(items=[CountItem(product_id=pid, counted=3)],
                            client_uuid=ctx.key("api", "mahsulot", "sanoq")),
                    emp, db, at=t)
        db.rollback()


def test_16_UTC_bolmagan_at_ham_TOGRI_solishtiriladi(no_push):
    """⚠️  `at` UTC bo'lmagan zonada berilsa ham xronologiya TO'G'RI o'lchanadi.

    O'LCHANGAN XAVF: SQLite `DateTime(timezone=True)` ni saqlaganda `tzinfo` ni
    JIMGINA tashlab, DEVOR-SOATINI yozadi. Ya'ni `+05:00` payt normalizatsiya
    qilinmasa, u keyin UTC deb o'qilib hamma solishtirish 5 soat xato bo'lardi
    va gard JIMGINA noto'g'ri hukm chiqarardi (Postgres'da esa to'g'ri —
    bitta gard, ikki xil javob).
    `resolve_at` endi KANONIK UTC qaytaradi, shu bois ikki dialekt bir xil.
    """
    from datetime import timedelta as _td
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)

    tosh = timezone(_td(hours=5))                      # Asia/Tashkent ofseti
    #  Zanjirning oxirgi harakatidan KEYIN, lekin +05:00 da ifodalangan payt.
    t_keyin = (z["T"]["count"] + _td(days=1)).astimezone(tosh)
    assert t_keyin.utcoffset() == _td(hours=5), "test o'z sahnasini qurmadi"

    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_keyin) as ctx:
            #  RAD ETILMASLIGI shart: bu payt oxirgi harakatdan KEYIN.
            _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=6)],
                        client_uuid=ctx.key("tosh", "sanoq")),
                emp, db, at=t_keyin)
        db.commit()

    mv = _harakatlar(pid, d["bid"])
    #  Saqlangan qiymat UTC bo'lishi SHART (devor-soati +05:00 EMAS).
    assert abs((mv[-1][0] - t_keyin).total_seconds()) < 2,         (f"saqlangan vaqt INSTANT bo'yicha mos emas: {mv[-1][0]} != {t_keyin} "
         f"(UTC: {t_keyin.astimezone(timezone.utc)})")
    assert mv[-1][0].hour == t_keyin.astimezone(timezone.utc).hour,         "saqlangan vaqt +05:00 devor-soati bo'lib qolgan — UTC normalizatsiya ishlamadi"


def test_17_gard_MAHSULOT_doirasida_boshqa_mahsulotni_BLOKLAMAYDI(no_push):
    """⚠️  Gard (mahsulot, filial) doirasida bo'lishi SHART — faqat filial EMAS.

    AYNI filialdagi BOSHQA mahsulotning keyingi harakati bu mahsulotning
    tarixiy sanog'i haqida HECH NARSA demaydi. Doira faqat filialga qo'yilsa,
    bir mahsulotni oldinga surish butun filialdagi tarixiy sanoqlarni
    bloklardi — ya'ni reja mahsulotlarni turli tezlikda yurita olmasdi.

    ⚠️  `stock_movements` da `company_id` ustuni YO'Q: tenant xavfsizligi
        `product_id` ning egalik tekshiruvidan keladi, shu bois proba
        HAR IKKI ustun bilan doiralanishi kerak.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    d = _demo()
    sid = _yetkazuvchi(d)
    pid_a, pid_b = _mahsulot(d), _mahsulot(d)

    #  A mahsuloti bo'yicha KEYINGI paytda zanjir quramiz.
    _zanjir(d, pid_a, sid)

    #  B mahsuloti TEGILMAGAN — uning tarixiy sanog'i O'TISHI shart, garchi
    #  AYNI filialda A bo'yicha ancha keyingi harakatlar mavjud bo'lsa ham.
    t_b = (NOW - timedelta(days=DEPTH)).replace(hour=9, minute=0, second=0, microsecond=0)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_b) as ctx:
            _stock_count_once(
                CountIn(items=[CountItem(product_id=pid_b, counted=3)],
                        client_uuid=ctx.key("b", "sanoq")),
                emp, db, at=t_b)
        db.commit()

    mv_b = _harakatlar(pid_b, d["bid"])
    assert len(mv_b) == 1,         (f"B mahsulotining tarixiy sanog'i BLOKLANDI yoki yozilmadi: {mv_b}. "
         f"Gard doirasi mahsulotni e'tiborga olmayapti.")
    assert abs((mv_b[0][0] - t_b).total_seconds()) < 2
    assert mv_b[0][2] == Decimal("3")


def test_18_gard_hali_FLUSH_qilinmagan_harakatni_HAM_koradi(no_push):
    """⚠️  `autoflush=False` teshigi: kutilayotgan harakat ham hisobga olinsin.

    `db/session.py` da sessiya `autoflush=False` bilan quriladi, ya'ni
    `db.query(...)` oldidan FLUSH bo'lmaydi. Chaqiruvchi sessiyaga `db.add`
    qilgan, lekin hali flush qilinmagan keyingi harakat bo'lsa, gard eskirgan
    `MAX` ni o'qib JIMGINA o'tib ketardi.

    ⚠️  BU LOYIHADA AYNAN SHU MEXANIZM haqiqiy nuqson bergan: `on_cash_sale`
        `autoflush=False` tufayli hech qachon ishlamagan (Phase 2.5 darsi), va
        ayni sabab bilan `sales.py` / `lot_return.py` / `lot_correction.py` da
        aniq `db.flush()` chaqiruvlari bor.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once
    from app.models.enums import MovementType
    from app.models.inventory import StockMovement

    d = _demo()
    pid = _mahsulot(d, qty=5)
    t_sanoq = (NOW - timedelta(days=DEPTH)).replace(hour=9, minute=0, second=0, microsecond=0)
    t_keyin = t_sanoq + timedelta(days=2)          # sanoqdan KEYINGI harakat
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        #  KEYINGI harakat sessiyaga qo'shiladi, lekin ATAYLAB flush QILINMAYDI.
        db.add(StockMovement(product_id=pid, branch_id=d["bid"],
                             type=MovementType.adjustment, qty=Decimal("1"),
                             balance_after=Decimal("6"), ref_type="sahna",
                             created_at=t_keyin))
        assert any(isinstance(o, StockMovement) for o in db.new),             "test o'z sahnasini qurmadi: kutilayotgan qator yo'q"

        with H.enter(db, comp, plan_id=PLAN, instant=t_sanoq) as ctx:
            with pytest.raises(RuntimeError, match="TARTIBSIZ"):
                _stock_count_once(
                    CountIn(items=[CountItem(product_id=pid, counted=2)],
                            client_uuid=ctx.key("flush", "sanoq")),
                    emp, db, at=t_sanoq)
        db.rollback()


# ══════════════════════════════════════════════════════════════════════════
#  PARTIYA HARAKATI + SANOQ AUDITI — eganing darvozasidagi qolgan ikki oila
# ══════════════════════════════════════════════════════════════════════════
def test_19_PARTIYA_harakatlari_va_SANOQ_auditi_TARIXIY(no_push):
    """⚠️  Eganing darvozasi uch oilani nomlaydi: StockMovement, PARTIYA harakati,
        AUDIT harakati. Bu test oxirgi ikkisini qoplaydi.

    Kuzatuvsiz mahsulotli zanjir ularga YETIB BORMAYDI:
      · partiya qatorlari faqat kuzatuvli mahsulotda yaratiladi;
      · sanoqning audit qatori `if _plan is not None:` ichida, ya'ni u ham
        faqat kuzatuvli yo'lda yoziladi.
    """
    from app.api.v1.inventory import CountIn, CountItem, CountLot, _stock_count_once
    from app.api.v1.receiving import CommitIn, _commit_once

    d = _demo()
    sid = _yetkazuvchi(d)
    pid = _kuzatuvli_mahsulot(d)
    day = (NOW - timedelta(days=DEPTH)).replace(hour=0, minute=0, second=0, microsecond=0)
    t_recv, t_count = day + timedelta(hours=9), day + timedelta(days=2, hours=14)
    comp = _company(d)

    #  1) QABUL — partiya yaratadi (kuzatuvli mahsulotda partiya MAJBURIY).
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_recv) as ctx:
            _commit_once(CommitIn(supplier_id=sid, payment="credit",
                                  items=[{"product_id": pid, "qty": 10, "unit_cost": 500,
                                          "lots": [{"qty": 10, "unit_cost": 500}]}],
                                  client_uuid=ctx.key("recv", "lot")),
                         emp, db, at=t_recv)
        db.commit()

    from app.models.inventory import StockBatch
    with _db() as db:
        batches = (db.query(StockBatch)
                   .filter(StockBatch.product_id == pid).all())
        assert len(batches) == 1, f"aynan bitta partiya kutilgan: {len(batches)}"
        b = batches[0]
        bid_lot = b.id
        for nom in ("received_at", "created_at", "updated_at"):
            v = _aw(getattr(b, nom, None))
            assert v is not None, f"partiyada `{nom}` YO'Q"
            assert abs((v - t_recv).total_seconds()) < 2,                 f"partiya `{nom}` TARIXIY emas: {v} != {t_recv}"

    #  2) SANOQ — partiya darajasida; `apply_count` allokatsiya yozadi va
    #     sanoqning AUDIT qatori ham shu shoxda chiqadi.
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_count) as ctx:
            _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=8,
                                         lots=[CountLot(stock_batch_id=bid_lot, counted=8)])],
                        client_uuid=ctx.key("lot", "sanoq")),
                emp, db, at=t_count)
        db.commit()

    #  PARTIYA ALLOKATSIYALARI tarixiy bo'lishi SHART.
    from app.models.inventory import StockMovementLotAllocation as _Alloc
    with _db() as db:
        allocs = db.query(_Alloc).filter(_Alloc.stock_batch_id == bid_lot).all()
        assert allocs, "partiya allokatsiyasi yozilmadi — sanoq partiya yo'lidan ketmagan"
        for a in allocs:
            v = _aw(a.created_at)
            assert abs((v - t_count).total_seconds()) < 2,                 f"allokatsiya `created_at` TARIXIY emas: {v} != {t_count}"

        #  Partiyaning O'ZI ham sanoq paytida yangilanadi.
        b = db.get(StockBatch, bid_lot)
        assert abs((_aw(b.updated_at) - t_count).total_seconds()) < 2,             f"partiya `updated_at` sanoq paytini olmadi: {b.updated_at} != {t_count}"

    #  SANOQ AUDIT qatori — `if _plan is not None:` shoxida.
    from app.models.sync import AuditLog
    with _db() as db:
        rows = (db.query(AuditLog)
                .filter(AuditLog.actor_id == d["eid"],
                        AuditLog.entity == "stock_count").all())
        assert rows, "sanoqning AUDIT qatori yozilmadi (partiya shoxi ishlamagan?)"
        for r in rows:
            assert abs((_aw(r.created_at) - t_count).total_seconds()) < 2,                 f"sanoq auditi TARIXIY emas: {r.created_at} != {t_count}"


def test_20_QAYTA_yurgizilgan_sanoq_GARD_emas_DUBLIKAT_qaytaradi(no_push):
    """⚠️  TAKROR KALITI GARDDAN OLDIN turishi SHART.

    Reja qayta yurgizilganda allaqachon qo'llanilgan sanoq BENIGN dublikat
    bo'lib qolishi kerak — garchi oradan keyingi harakatlar o'tgan bo'lsa ham.
    Gard dedupdan OLDIN qo'yilsa, oddiy offline qayta-yuborish operatorga
    XATO bo'lib ko'rinardi va bajaruvchi rejani qayta yurgiza olmasdi.

    Yozuvchining o'z izohi shu qoidani so'zma-so'z aytadi: «Takror kaliti esa
    BIRINCHI» (`api/v1/inventory.py`).
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once

    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)

    #  Zanjirdagi sanoq AYNI kalit bilan qayta yurgiziladi — undan KEYIN
    #  yana bir harakat yozilgan bo'lsa ham.
    t_keyin = z["T"]["count"] + timedelta(days=1)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_keyin) as ctx:
            _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=4)],
                        client_uuid=ctx.key("keyingi")),
                emp, db, at=t_keyin)
        db.commit()

    oldin_mv = len(_harakatlar(pid, d["bid"]))
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=z["T"]["count"]) as ctx:
            #  AYNI kalit (`_zanjir` ichidagi "count" kaliti) + AYNI payt.
            out = _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=5)],
                        client_uuid=ctx.key("count")),
                emp, db, at=z["T"]["count"])
        db.commit()

    assert out.get("duplicate") is True,         (f"qayta yurgizish DUBLIKAT qaytarmadi: {out}. Gard takror kalitidan "
         f"OLDIN ishlagan bo'lishi mumkin.")
    assert len(_harakatlar(pid, d["bid"])) == oldin_mv,         "dublikat sanoq YANGI harakat yozdi"


def test_21_BOSHQA_FILIALdagi_ayni_mahsulot_BLOKLAMAYDI(no_push):
    """⚠️  Gard (mahsulot, FILIAL) juftligi bo'yicha — faqat mahsulot EMAS.

    Sanoq filial darajasidagi MUTLAQ yozuv: A filialdagi keyingi harakat
    B filialdagi tarixiy sanoq haqida hech narsa demaydi. Doira faqat
    mahsulotga qo'yilsa, bir filialni oldinga surish BOSHQA filiallardagi
    tarixiy sanoqlarni bloklardi.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once
    from app.models.inventory import Inventory
    from app.models.org import Branch

    d = _demo()
    pid, sid = _mahsulot(d), _yetkazuvchi(d)
    z = _zanjir(d, pid, sid)                     # A filialda keyingi harakatlar

    #  IKKINCHI filial + o'sha mahsulotning qoldiq qatori (sahna, ORM).
    with _db() as db:
        br2 = Branch(id=uuid.uuid4(), company_id=d["cid"], name="F02", code="F02",
                     timezone=TZ, is_active=True, created_at=NOW - timedelta(days=400))
        db.add(br2)
        db.flush()
        db.add(Inventory(product_id=pid, branch_id=br2.id, qty=Decimal("0"),
                         min_qty=0, updated_at=NOW))
        db.commit()
        bid2 = br2.id

    t2 = (NOW - timedelta(days=DEPTH)).replace(hour=9, minute=0, second=0, microsecond=0)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t2) as ctx:
            _stock_count_once(
                CountIn(items=[CountItem(product_id=pid, counted=2)], branch_id=bid2,
                        client_uuid=ctx.key("f02", "sanoq")),
                emp, db, at=t2)
        db.commit()

    mv2 = _harakatlar(pid, bid2)
    assert len(mv2) == 1,         (f"B filialdagi tarixiy sanoq BLOKLANDI yoki yozilmadi: {mv2}. "
         f"Gard doirasi filialni e'tiborga olmayapti.")
    assert abs((mv2[0][0] - t2).total_seconds()) < 2
    #  A filial TEGILMAGAN bo'lishi shart.
    assert len(_harakatlar(pid, d["bid"])) == 4, "A filial harakatlari o'zgardi"


def test_22_OMMAVIY_sxemalarda_VAQT_maydoni_YO_Q():
    """⚠️  Ega qat'iy cheklovi: ommaviy so'rov sxemasiga tarixiy vaqt maydoni
        QO'SHILMASIN. Tarixiy qobiliyat DARVOZAGA bog'langan, marshrutga emas.

    Agar `at`/`sold_at`/`occurred_at` kabi maydon sxemaga kirsa, oddiy token
    bilan kelgan HAR QANDAY mijoz tarixiy yozuv so'rashga URINIB ko'rardi —
    va darvozaning o'zi yagona to'siq bo'lib qolardi.
    """
    from app.api.v1.inventory import CountIn, WriteoffIn
    from app.api.v1.purchases import SupplierPaymentIn
    from app.api.v1.receiving import CommitIn
    from app.schemas.purchase import PurchaseCreate
    from app.schemas.sales import ReturnCreate, SaleCreate

    TAQIQ = {"at", "occurred_at", "device_occurred_at", "created_at",
             "purchase_date", "committed_at", "paid_at", "instant"}
    for M in (PurchaseCreate, CommitIn, ReturnCreate, CountIn, WriteoffIn,
              SupplierPaymentIn, SaleCreate):
        maydonlar = set(M.model_fields)
        kesishma = maydonlar & TAQIQ
        #  `SaleCreate.sold_at` — MAVJUD `/sync/push` offline maydoni; u H3a
        #  kiritgan narsa EMAS va unga ataylab tegilmaydi (60-kunlik klamp
        #  bilan cheklangan). Shu bois `sold_at` TAQIQ ro'yxatida YO'Q.
        assert not kesishma,             f"{M.__name__} ommaviy sxemasiga VAQT maydoni kirgan: {sorted(kesishma)}"
