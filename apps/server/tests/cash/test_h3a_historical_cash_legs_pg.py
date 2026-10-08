# -*- coding: utf-8 -*-
"""H3a — TARIXIY HUJJATLARNING NAQD OYOQLARI (FAQAT Postgres).

NEGA ALOHIDA, POSTGRES'DA
=========================
H3a uchta ledger hook'iga tarixiy paytni uzatdi:
  · `retrofit.on_cash_purchase`      (xarid yaratish + qabul commit)
  · `retrofit.on_cash_refund`        (qaytarish)
  · `retrofit.on_supplier_payment`   (yetkazuvchiga to'lov)
Uchovi `device_occurred_at` bo'lib `adapters` -> `posting._post` ga boradi.

⚠️  BU YO'L SQLite'DA UMUMAN BAJARILMAYDI. `retrofit.dual_write_enabled(db)`
    `cash_enabled(db)` ni talab qiladi va u postgresql bo'lmagan dialektda
    `False`. Ya'ni asosiy to'plam (`tests/test_h3a_historical_writers.py`)
    bu hook'larga uzatilgan `at` ni KO'RMAYDI — u yerda ular GUARDED NO-OP.

⚠️  SHU BOIS BU FAYL BOR. `at` uzatilmay qolsa ham mahalliy to'plam YASHIL
    bo'lardi, leg esa `posting._in_window` tomonidan smena oynasidan TASHQARI
    (`OFF_SHIFT`, `TIMESTAMP_OUT_OF_WINDOW`) deb tasniflanardi. Oqibati JIM:
    `posting.shift_movement_total` FAQAT `ON_SHIFT` ni sanaydi, ya'ni leg
    kunning naqd hikoyasidan tushib qolardi, qatorning o'zi esa butunlay
    sog'lom ko'rinardi. Bu loyihaning ma'lum tuzoq sinfi — SQLite ko'rmaydigan
    narsa Postgres'da sinalishi SHART.

⚠️  TO'G'RIDAN ORM BILAN LEDGER YOZILMAYDI — faqat kanonik yozuvchilar.

⚠️  BARCHA HODISALAR BITTA KUNDA. `posting` smena oynasini
    `CASH_MAX_SHIFT_HOURS` (24 soat) bilan cheklaydi, shu bois tarixiy kun
    ichidagi hodisalar soatlar bilan ajratiladi (payt QAT'IY ortib boradi —
    `balance_after`/tartib dalili uchun ham shu kerak).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services import historical as H

TZ = "Asia/Tashkent"
DEPTH = 150
PLAN = "h3a-cash-pg"


def _aw(dt):
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@pytest.fixture()
def demo(db, cashenv):
    """DEMO tenant (kod `demo-...`, T0 YO'Q) + filial + kassir + ACTIVE TILL.

    `cashenv` ning umumiy kompaniyasi ISHLATILMAYDI: H1 darvozasi `test`/`demo`
    kodli do'konni TALAB qiladi va umumiy fixture'ni qayta nomlash boshqa cash
    testlarini o'zgartirib yuborardi (H2 PG testi bilan ayni sabab).
    """
    from app.models.auth import Employee, Role
    from app.models.cash import CashAccount
    from app.models.catalog import Product, Unit
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    from app.services.cash import till_identity as _ti

    now = datetime.now(timezone.utc)
    comp = Company(id=uuid.uuid4(), name="H3a naqd demo",
                   code=f"demo-h3apg-{uuid.uuid4().hex[:6]}", currency="KGS")
    db.add(comp)
    db.flush()
    br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01",
                timezone=TZ, is_active=True, created_at=now - timedelta(days=400))
    db.add(br)
    db.flush()
    role = db.query(Role).first()
    if role is None:
        role = Role(id=uuid.uuid4(), code="ega", name="Ega")
        db.add(role)
        db.flush()
    emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                   full_name="H3a kassir", phone=f"+9986{uuid.uuid4().int % 10**7:07d}",
                   status=EmployeeStatus.active, sec_epoch=0)
    db.add(emp)
    till = CashAccount(id=uuid.uuid4(), tenant_id=comp.id, branch_id=br.id,
                       type="TILL", currency="KGS", status="ACTIVE",
                       label=_ti.till_label(f"TILL-{uuid.uuid4().hex[:4]}", None),
                       created_at=now)
    db.add(till)
    sup = Supplier(id=uuid.uuid4(), company_id=comp.id, name="H3a yetkazuvchi")
    db.add(sup)
    #  ⚠️  `units` cash test bazasida urug'lanMAGAN bo'lishi mumkin (cash
    #      conftest minimal sxema quradi, to'liq `seed.run()` emas) — H2 PG
    #      testi `Role` uchun aynan shu himoyani ishlatadi. `.one()` bu yerda
    #      butun fiksturani ERROR qilardi.
    u = db.query(Unit).filter_by(code="dona").first()
    if u is None:
        u = Unit(id=uuid.uuid4(), code="dona", name="dona", allow_fraction=False)
        db.add(u)
        db.flush()
    prod = Product(id=uuid.uuid4(), company_id=comp.id, name="H3a dona",
                   article_code="H3APG-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                   unit_id=u.id, base_buy_price=500, base_sell_price=1000, tax_rate=0)
    db.add(prod)
    db.flush()
    #  Qoldiq 0 — zanjirdagi har balans FAQAT zanjir hodisalaridan chiqsin.
    db.add(Inventory(product_id=prod.id, branch_id=br.id, qty=Decimal("0"),
                     min_qty=0, updated_at=now))
    db.commit()
    return {"comp": comp, "emp": emp, "br": br, "till": till, "sup": sup, "prod": prod}


class _Open:
    opening_cash = 100000.0
    terminal_id = None
    till_id = None


def _legs(db, tenant_id):
    from app.models.cash import CashLedgerEntry
    return (db.query(CashLedgerEntry)
            .filter(CashLedgerEntry.tenant_id == tenant_id)
            .order_by(CashLedgerEntry.device_occurred_at).all())


def _tarixiy_kun(db, demo, *, plan=PLAN):
    """Bitta tarixiy kun, BITTA smena oynasi ichida:
    smena 08:00 -> xarid A (KREDIT) 09:00 -> xarid B (NAQD) 09:30
    -> sotuv 10:00 -> qaytarish (NAQD refund) 11:00
    -> yetkazuvchiga to'lov (NAQD) 12:00.

    ⚠️  NEGA IKKI XARID. Naqd xarid darhol to'lanadi va yetkazuvchida QARZ
        QOLDIRMAYDI, shu bois 12:00 dagi to'lov «qarz yo'q» deb 400 bilan rad
        etilardi. KREDITLI xarid A qarzni yaratadi (to'lov shuni yopadi),
        NAQD xarid B esa `on_cash_purchase` hook'ini yondiradi. Ya'ni uchta
        H3a hook'i ham AYNI kunda o'lchanadi.

    ⚠️  BALANSLAR ATAYLAB FARQLI: 10 -> 15 -> 12 -> 14, deltalar +10, +5, -3,
        +2. Juftlik almashsa ham natija BOSHQA chiqadi.
    """
    from app.api.v1.purchases import (SupplierPaymentIn, _create_purchase_once,
                                      _pay_supplier_once)
    from app.api.v1.sales import _create_return_once
    from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
    from app.schemas.sales import ReturnCreate, ReturnItemIn, SaleCreate, SaleItemIn
    from app.services.sales import create_sale
    from app.services.shifts import open_shift_svc

    comp, emp = demo["comp"], demo["emp"]
    pid, sid, till = demo["prod"].id, demo["sup"].id, demo["till"]
    day = (datetime.now(timezone.utc) - timedelta(days=DEPTH)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    T = {"shift": day + timedelta(hours=8),
         "purchase_credit": day + timedelta(hours=9),
         "purchase": day + timedelta(hours=9, minutes=30),
         "sale": day + timedelta(hours=10), "return": day + timedelta(hours=11),
         "suppay": day + timedelta(hours=12)}
    _Open.till_id = till.id

    with H.enter(db, comp, plan_id=plan, instant=T["shift"]) as ctx:
        sh = open_shift_svc(_Open(), emp, db, at=T["shift"],
                            client_uuid=ctx.key("shift", "open"))
    out = {"T": T, "shift_id": uuid.UUID(sh["id"])}

    #  XARID A — KREDIT: yetkazuvchida QARZ yaratadi (naqd oyog'i YO'Q).
    with H.enter(db, comp, plan_id=plan, instant=T["purchase_credit"]) as ctx:
        _create_purchase_once(
            PurchaseCreate(supplier_id=sid, status="debt",
                           items=[PurchaseItemIn(product_id=pid, qty=10, unit_cost=500)],
                           client_uuid=ctx.key("purchase", "credit")),
            emp, db, at=T["purchase_credit"])

    #  XARID B — NAQD: `on_cash_purchase` hook'ini yondiradi.
    with H.enter(db, comp, plan_id=plan, instant=T["purchase"]) as ctx:
        _create_purchase_once(
            PurchaseCreate(supplier_id=sid, status="received",
                           items=[PurchaseItemIn(product_id=pid, qty=5, unit_cost=500)],
                           cash_account_id=till.id, client_uuid=ctx.key("purchase", "cash")),
            emp, db, at=T["purchase"])

    with H.enter(db, comp, plan_id=plan, instant=T["sale"]) as ctx:
        sale = create_sale(db, emp, SaleCreate(
            items=[SaleItemIn(product_id=pid, qty=3, unit_price=1000)],
            payment_method="cash", given_amount=3000,
            client_uuid=ctx.key("sale")), at=T["sale"])
    out["sale_id"] = sale.id

    with H.enter(db, comp, plan_id=plan, instant=T["return"]) as ctx:
        _create_return_once(
            ReturnCreate(original_sale_id=sale.id, restock=True, refund_method="cash",
                         items=[ReturnItemIn(product_id=pid, qty=2, unit_price=1000)],
                         client_uuid=ctx.key("return")),
            emp, db, at=T["return"])

    with H.enter(db, comp, plan_id=plan, instant=T["suppay"]) as ctx:
        _pay_supplier_once(sid, SupplierPaymentIn(amount=1000, method="cash",
                                                  cash_account_id=till.id,
                                                  client_uuid=ctx.key("suppay")),
                           emp, db, at=T["suppay"])
    db.commit()
    return out


def test_naqd_oyoqlari_TARIXIY_paytni_oladi(db, demo):
    """Har legning `device_occurred_at` i AYNAN tarixiy payt bo'lishi SHART."""
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq (cash sxemasi yo'q) — naqd oyoqlari o'lchanmaydi")

    z = _tarixiy_kun(db, demo)
    legs = _legs(db, demo["comp"].id)
    assert legs, "naqd ledger legi UMUMAN yozilmadi — test o'z sahnasini tekshirmayapti"

    kutilgan = {
        "PURCHASE": z["T"]["purchase"],
        "SALE": z["T"]["sale"],
        "RETURN": z["T"]["return"],
        "SUPPLIER_PAYMENT": z["T"]["suppay"],
    }
    korilgan = {}
    for lg in legs:
        src = str(lg.source_type)
        src = src.split(".")[-1] if "." in src else src
        korilgan.setdefault(src, []).append(lg)

    for src, t_k in kutilgan.items():
        assert src in korilgan, \
            f"`{src}` legi YO'Q. Yozilganlar: {sorted(korilgan)}"
        for lg in korilgan[src]:
            assert abs((_aw(lg.device_occurred_at) - t_k).total_seconds()) < 2, \
                (f"`{src}` legining `device_occurred_at` i TARIXIY emas: "
                 f"{lg.device_occurred_at} != {t_k}")


def test_naqd_oyoqlari_ON_SHIFT_va_TARIXIY_smenaga_biriktirilgan(db, demo):
    """Leg tarixiy smena OYNASIGA tushishi va o'sha smenaga biriktirilishi SHART.

    ⚠️  BU TESTNING MAZMUNI: `at` uzatilmasa leg BUGUNGI payt bilan yozilib,
        `posting._in_window` uni oynadan TASHQARI deb tasniflardi (`OFF_SHIFT`)
        va `shift_movement_total` (faqat `ON_SHIFT`) uni kun hisobidan
        JIMGINA chiqarib tashlardi.
    """
    from app.models.cash import CashPostingKind
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq — tasnif o'lchanmaydi")

    z = _tarixiy_kun(db, demo)
    legs = _legs(db, demo["comp"].id)
    assert legs

    off = [(str(lg.source_type), str(lg.posting_kind), lg.device_occurred_at)
           for lg in legs if str(lg.posting_kind).endswith("OFF_SHIFT")]
    assert not off, \
        (f"OYNADAN TASHQARI leg bor: {off}. Ya'ni tarixiy payt uzatilmagan yoki "
         f"smena oynasi bilan mos kelmagan.")

    til_legs = [lg for lg in legs if str(lg.account_type).endswith("TILL")]
    assert til_legs, "TILL legi yo'q — sahna kutilganidek qurilmagan"
    for lg in til_legs:
        assert str(lg.posting_kind).endswith(CashPostingKind.ON_SHIFT.value), \
            f"TILL legi ON_SHIFT emas: {lg.posting_kind} ({lg.source_type})"
        assert lg.shift_id == z["shift_id"], \
            (f"leg BOSHQA smenaga biriktirilgan: {lg.shift_id} != {z['shift_id']} "
             f"({lg.source_type})")


def test_QABUL_vaqti_QALBAKILASHTIRILMAYDI(db, demo):
    """`server_received_at` / `recorded_at` HAQIQIY vaqt bo'lib QOLISHI SHART.

    ⚠️  ATAYLAB ORQAGA SANALMAYDI. Bular — qator HAQIQATAN qachon qabul
        qilingani/yozilgani. Ularni soxtalashtirish replay'ni jonli amaldan
        ajratib turadigan YAGONA audit o'qini yo'q qilardi.
    """
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    z = _tarixiy_kun(db, demo)
    hozir = datetime.now(timezone.utc)
    for lg in _legs(db, demo["comp"].id):
        assert (hozir - _aw(lg.server_received_at)).total_seconds() < 3600, \
            (f"`server_received_at` ORQAGA sanalgan: {lg.server_received_at} "
             f"({lg.source_type}) — bu audit o'qini yo'q qiladi")
        assert (hozir - _aw(lg.recorded_at)).total_seconds() < 3600, \
            f"`recorded_at` ORQAGA sanalgan: {lg.recorded_at} ({lg.source_type})"
        #  Va ikki o'q bir-biridan AJRALGAN bo'lishi kerak: biznes payti
        #  TARIXIY, qabul payti esa HOZIRGI — aynan shu farq replay'ni tanitadi.
        #  ⚠️  BU ASSERTION HAQIQIY NUQSON TOPDI: `on_shift_open` ochilish
        #      floti legiga `device_occurred_at` UZATMAGAN edi (H2 uni faqat
        #      `cash.shifts.opened_at` va reconciliation yozuviga uzatgan),
        #      ya'ni SHIFT_OPEN legi BUGUNGI payt bilan yozilardi va smena
        #      oynasidan tashqarida qolardi. `<` yetarli emas edi —
        #      MASOFA tekshiriladi, aks holda ayni mikrosekundli juftlik ham
        #      «o'tgan» bo'lib ko'rinardi.
        yosh = (_aw(lg.server_received_at) - _aw(lg.device_occurred_at)).total_seconds()
        assert yosh > 86400, \
            (f"leg biznes payti TARIXIY emas: device={lg.device_occurred_at} "
             f"received={lg.server_received_at} farq={yosh:.0f}s "
             f"({lg.source_type}) — `device_occurred_at` uzatilmagan bo'lishi mumkin")


def test_zaxira_harakatlari_ham_TARIXIY_Postgresda(db, demo):
    """Ayni zanjirda zaxira harakatlari ham tarixiy — PG'da ham tasdiqlanadi.

    Mahalliy to'plam buni SQLite'da o'lchaydi; bu yerda AYNI invariant real
    `timestamptz` bilan takrorlanadi (naive/aware farqi gardga ta'sir qilmasin).
    """
    from app.models.inventory import StockMovement
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    z = _tarixiy_kun(db, demo)
    rows = (db.query(StockMovement)
            .filter(StockMovement.product_id == demo["prod"].id,
                    StockMovement.branch_id == demo["br"].id)
            .order_by(StockMovement.created_at).all())
    assert len(rows) == 4,         f"4 harakat kutilgan (kredit xarid/naqd xarid/sotuv/qaytarish): {len(rows)}"
    kutilgan = [(z["T"]["purchase_credit"], Decimal("10"), Decimal("10")),
                (z["T"]["purchase"], Decimal("5"), Decimal("15")),
                (z["T"]["sale"], Decimal("-3"), Decimal("12")),
                (z["T"]["return"], Decimal("2"), Decimal("14"))]
    for (t_k, q_k, b_k), r in zip(kutilgan, rows):
        assert abs((_aw(r.created_at) - t_k).total_seconds()) < 2, \
            f"harakat vaqti TARIXIY emas: {r.created_at} != {t_k}"
        assert Decimal(str(r.qty)) == q_k
        assert Decimal(str(r.balance_after)) == b_k, \
            f"`balance_after` ketma-ketligi buzilgan: {r.balance_after} != {b_k}"


def test_XRONOLOGIYA_gardi_Postgresda_ham_ishlaydi(db, demo):
    """Gard real `timestamptz` bilan ham TARTIBSIZ sanoqni rad etadi.

    ⚠️  SQLite naive, Postgres aware qaytaradi — gard ikki dialektda AYNI
        hukmni berishi SHART, aks holda mahalliy yashil to'plam prod'da
        boshqacha ishlardi.
    """
    from app.api.v1.inventory import CountIn, CountItem, _stock_count_once
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    z = _tarixiy_kun(db, demo)
    t_orqaga = z["T"]["purchase"] + timedelta(minutes=5)    # sotuv/qaytarishdan OLDIN
    with H.enter(db, demo["comp"], plan_id=PLAN, instant=t_orqaga) as ctx:
        with pytest.raises(RuntimeError, match="TARTIBSIZ"):
            _stock_count_once(
                CountIn(items=[CountItem(product_id=demo["prod"].id, counted=99)]),
                demo["emp"], db, at=t_orqaga)
    db.rollback()
