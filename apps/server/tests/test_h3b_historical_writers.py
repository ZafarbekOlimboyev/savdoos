# -*- coding: utf-8 -*-
"""H3b — AJRATISH TALAB QILGAN UCH YOZUVCHI: hisobdan chiqarish, kassa amali,
mijoz qarz to'lovi.

DOIRA (ega tasdiqlagan H3b): `inventory.writeoff`, `cashops.cash_op`,
`customers.pay_credit` + ularga tegishli 3 ledger hook + ekstraksiya majburlagan
`require_index` registr ko'chishlari. Boshqa hech narsa.

EKSTRAKSIYA USULI — VA NEGA TANA O'Z FAYLIDA QOLDI
==================================================
H2 smena tanalarini YANGI servis moduliga (`services/shifts.py`) ko'chirgan.
H3b esa tanani O'Z MODULIDA ichki `_once` funksiyasiga ko'chiradi. Sabab
O'LCHANGAN: `tests/test_lot_error_texts.py` da UCHTA manba ro'yxati
(`SOURCES`, `CASH_SOURCES`, `ID_SOURCES`) aynan `api/v1/inventory.py`,
`api/v1/cashops.py`, `api/v1/customers.py` fayllarini skanerlab, operator
ko'radigan xato matnlarini frontend tarjima lug'atida VA id-oqmasligida
tekshiradi. Tanani boshqa modulga ko'chirish o'sha xabarlarni detektorlardan
JIMGINA chiqarib tashlardi — gard QIZIL BO'LMASDAN, chunki u endi boshqa
faylni skanerlaydi. Audit AU-2 §4.3 bu fayllarni ro'yxatga aynan shu teshik
sababli qo'shgan (oltita xabar bazadan olingan UUID bilan chiqib ketgan edi).
Ustiga `api/v1/*.py` da `_once` konvensiyasi allaqachon ustun (7 namuna).

⚠️  SQLITE NIMANI KO'RSATMAYDI. `retrofit.dual_write_enabled` SQLite'da False,
    ya'ni naqd LEDGER oyoqlari bu faylda GUARDED NO-OP. Ular
    `tests/cash/test_h3b_historical_cash_legs_pg.py` da real Postgres'da
    o'lchanadi. Bu fayl legacy jadvallar va vaqt sodiqligini qoplaydi.

⚠️  BIZNES HODISASI TO'G'RIDAN ORM BILAN YOZILMAYDI — faqat kanonik yo'ldan.
    ORM FAQAT sahna qurishda (do'kon/filial/xodim/mahsulot/mijoz).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services import historical as H

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
PLAN = "h3b-plan-1"
DEPTH = 160


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _hozir():
    """HOZIRNI ASSERTION PAYTIDA o'lchaydi — modul konstantasi `NOW` ni EMAS.

    ⚠️  H3a DARSI: `NOW` import paytida hisoblanadi va to'liq regressiyada
        (~1.5 soat) test moduldan ~25 daqiqa keyin yuradi, ya'ni «hozirmi?»
        assertion'i KOD TO'G'RI bo'lsa ham yiqilardi.
    """
    return datetime.now(timezone.utc)


def _aw(dt):
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _sxema(client):
    """Sxemani `conftest.client` quradi (`initdb` + `seed`).

    Bu testlar yozuvchilarni TO'G'RIDAN chaqiradi (`at` ommaviy sxemada YO'Q),
    shu bois `client` ni ANIQ talab qilish SHART.
    """
    return client


@pytest.fixture()
def no_push(monkeypatch):
    """Tashqi chiqishni SANAYDI (bo'g'ishni emas)."""
    from app.services import push
    sent: list = []
    monkeypatch.setattr(push, "send_ex", lambda *a, **k: (sent.append(a), (0, []))[1])

    class _S:
        fcm_enabled = True
    monkeypatch.setattr(push, "settings", _S())
    return sent


# ══ SAHNA ════════════════════════════════════════════════════════════════
def _demo(currency: str = "KGS", code_prefix: str = "demo"):
    from app.core.security import create_access_token
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="H3b demo",
                       code=f"{code_prefix}-h3b-{uuid.uuid4().hex[:6]}", currency=currency)
        db.add(comp)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01",
                    timezone=TZ, is_active=True, created_at=NOW - timedelta(days=400))
        db.add(br)
        db.flush()
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                       full_name="H3b ega", phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        db.commit()
        tok = create_access_token(str(emp.id),
                                  {"role": "ega", "company_id": str(comp.id), "sv": 0})
        return {"cid": comp.id, "bid": br.id, "eid": emp.id,
                "H": {"Authorization": f"Bearer {tok}"}}


def _emp(d):
    from app.models.auth import Employee
    with _db() as db:
        return db.get(Employee, d["eid"])


def _company(d):
    from app.models.org import Company
    with _db() as db:
        return db.get(Company, d["cid"])


def _mahsulot(d, qty=20, tracked=False):
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    with _db() as db:
        u = db.query(Unit).filter_by(code="dona").one()
        p = Product(id=uuid.uuid4(), company_id=d["cid"],
                    name=f"H3b {'kuzatuvli' if tracked else 'kuzatuvsiz'} {uuid.uuid4().hex[:5]}",
                    article_code="H3B-" + uuid.uuid4().hex[:10], sku=uuid.uuid4().hex[:8],
                    unit_id=u.id, base_buy_price=500, base_sell_price=1000, tax_rate=0,
                    track_lots=tracked)
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, branch_id=d["bid"], qty=Decimal(str(qty)),
                         min_qty=0, updated_at=NOW))
        db.commit()
        return p.id


def _mijoz(d, qarz="50000"):
    """Qarzi BOR mijoz. Boshlang'ich balans — SAHNA (biznes hodisasi emas)."""
    from app.models.customers import Customer
    with _db() as db:
        c = Customer(id=uuid.uuid4(), company_id=d["cid"],
                     code="M" + uuid.uuid4().hex[:10],   # NOT NULL + UNIQUE(company_id, code)
                     full_name=f"H3b mijoz {uuid.uuid4().hex[:5]}",
                     phone=f"+9984{uuid.uuid4().int % 10**7:07d}",
                     credit_balance=Decimal(qarz), credit_limit=Decimal("1000000"))
        db.add(c)
        db.commit()
        return c.id


def _tarixiy_smena(db, comp, emp, t_open, *, plan=PLAN, opening="100000"):
    """Tarixiy OCHIQ smena — `cash_op` ochiq smena TALAB qiladi."""
    from app.services.shifts import open_shift_svc

    class _Open:
        opening_cash = float(opening)
        terminal_id = None
        till_id = None
    with H.enter(db, comp, plan_id=plan, instant=t_open) as ctx:
        sh = open_shift_svc(_Open(), emp, db, at=t_open,
                            client_uuid=ctx.key("shift", "open"))
    return uuid.UUID(sh["id"])


def _harakatlar(pid, bid):
    from app.models.inventory import StockMovement
    with _db() as db:
        return [(_aw(m.created_at), Decimal(str(m.qty)),
                 None if m.balance_after is None else Decimal(str(m.balance_after)),
                 m.type.value if hasattr(m.type, "value") else str(m.type))
                for m in db.query(StockMovement)
                .filter(StockMovement.product_id == pid, StockMovement.branch_id == bid)
                .order_by(StockMovement.created_at, StockMovement.id).all()]


def _qoldiq(pid, bid):
    from app.models.inventory import Inventory
    with _db() as db:
        inv = (db.query(Inventory)
               .filter(Inventory.product_id == pid, Inventory.branch_id == bid).first())
        return None if inv is None else Decimal(str(inv.qty))


# ══════════════════════════════════════════════════════════════════════════
#  1) TARIXIY HISOBDAN CHIQARISH
# ══════════════════════════════════════════════════════════════════════════
def test_01_tarixiy_HISOBDAN_CHIQARISH_vaqti_togri(no_push):
    """`StockMovement.created_at` va `inventory.updated_at` tarixiy bo'lsin."""
    from app.api.v1.inventory import WriteoffIn, _writeoff_once

    d = _demo()
    pid = _mahsulot(d, qty=20)
    t = (NOW - timedelta(days=DEPTH)).replace(hour=10, minute=0, second=0, microsecond=0)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            _writeoff_once(WriteoffIn(product_id=pid, qty=3, reason="brak",
                                      branch_id=d["bid"], client_uuid=ctx.key("wo")),
                           emp, db, at=t)
        db.commit()

    mv = _harakatlar(pid, d["bid"])
    assert len(mv) == 1, f"aynan bitta harakat kutilgan: {mv}"
    t_mv, q, bal, tip = mv[0]
    assert abs((t_mv - t).total_seconds()) < 2, f"harakat vaqti TARIXIY emas: {t_mv} != {t}"
    assert q == Decimal("-3"), f"miqdor: {q}"
    assert bal == Decimal("17"), f"`balance_after`: {bal}"
    assert tip == "writeoff", f"tur: {tip}"
    assert _qoldiq(pid, d["bid"]) == Decimal("17")

    from app.models.inventory import Inventory
    with _db() as db:
        inv = (db.query(Inventory).filter(Inventory.product_id == pid,
                                          Inventory.branch_id == d["bid"]).one())
        assert abs((_aw(inv.updated_at) - t).total_seconds()) < 2, \
            f"`inventory.updated_at` TARIXIY emas: {inv.updated_at}"


def test_02_tarixiy_chiqarish_AUDIT_izi_tarixiy(no_push):
    """Ega darvozasi «audit movement» ni ham nomlaydi.

    ⚠️  AUDIT QATORI FAQAT KUZATUVLI YO'LDA YOZILADI. Chiqarishdagi
        `_audit_log` chaqiruvi `if _plan is not None:` ichida, `_plan` esa
        faqat kuzatuvli mahsulotda to'ladi. Ya'ni kuzatuvsiz mahsulotli test
        bu oilani UMUMAN sinamagan qoldirardi (birinchi variantim shu sababli
        yiqildi — o'sha yerda audit qatori yo'q edi, nuqson emas).

    ⚠️  VA SHU SHOXDA HAQIQIY NUQSON BOR EDI: `at` uzatilmagan. H3a sanoq
        auditiga uni uzatgan, chiqarish auditiga esa yo'q.
    """
    from app.api.v1.inventory import WriteoffIn, WriteoffLot, _writeoff_once
    from app.api.v1.receiving import CommitIn, _commit_once
    from app.models.inventory import StockBatch
    from app.models.purchasing import Supplier
    from app.models.sync import AuditLog

    d = _demo()
    pid = _mahsulot(d, qty=0, tracked=True)
    with _db() as db:
        sup = Supplier(id=uuid.uuid4(), company_id=d["cid"], name="H3b yetk a")
        db.add(sup)
        db.commit()
        sid = sup.id
    day = (NOW - timedelta(days=DEPTH)).replace(hour=0, minute=0, second=0, microsecond=0)
    t_recv, t_wo = day + timedelta(hours=9), day + timedelta(days=1, hours=11)
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_recv) as ctx:
            _commit_once(CommitIn(supplier_id=sid, payment="credit",
                                  items=[{"product_id": pid, "qty": 10, "unit_cost": 400,
                                          "lots": [{"qty": 10, "unit_cost": 400}]}],
                                  client_uuid=ctx.key("recv", "a")),
                         emp, db, at=t_recv)
        db.commit()
    with _db() as db:
        bid_lot = db.query(StockBatch).filter(StockBatch.product_id == pid).one().id

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_wo) as ctx:
            _writeoff_once(WriteoffIn(product_id=pid, qty=2, reason="brak",
                                      branch_id=d["bid"],
                                      lots=[WriteoffLot(stock_batch_id=bid_lot, qty=2)],
                                      client_uuid=ctx.key("wo", "audit")),
                           emp, db, at=t_wo)
        db.commit()

    with _db() as db:
        rows = (db.query(AuditLog)
                .filter(AuditLog.actor_id == d["eid"],
                        AuditLog.entity == "stock_writeoff").all())
        assert rows, "chiqarish AUDIT qatori yozilmadi (kuzatuvli shox ishlamagan?)"
        for r in rows:
            assert abs((_aw(r.created_at) - t_wo).total_seconds()) < 2,                 f"chiqarish auditi TARIXIY emas: {r.created_at} != {t_wo}"


def test_03_tarixiy_chiqarish_PARTIYA_vaqtlari_tarixiy(no_push):
    """Kuzatuvli mahsulotda partiya/allokatsiya vaqtlari ham tarixiy bo'lsin."""
    from app.api.v1.inventory import WriteoffIn, WriteoffLot, _writeoff_once
    from app.api.v1.receiving import CommitIn, _commit_once
    from app.models.inventory import StockBatch, StockMovementLotAllocation
    from app.models.purchasing import Supplier

    d = _demo()
    pid = _mahsulot(d, qty=0, tracked=True)
    with _db() as db:
        sup = Supplier(id=uuid.uuid4(), company_id=d["cid"], name="H3b yetk")
        db.add(sup)
        db.commit()
        sid = sup.id
    day = (NOW - timedelta(days=DEPTH)).replace(hour=0, minute=0, second=0, microsecond=0)
    t_recv, t_wo = day + timedelta(hours=9), day + timedelta(days=1, hours=14)
    comp = _company(d)

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_recv) as ctx:
            _commit_once(CommitIn(supplier_id=sid, payment="credit",
                                  items=[{"product_id": pid, "qty": 10, "unit_cost": 400,
                                          "lots": [{"qty": 10, "unit_cost": 400}]}],
                                  client_uuid=ctx.key("recv")),
                         emp, db, at=t_recv)
        db.commit()
    with _db() as db:
        b = db.query(StockBatch).filter(StockBatch.product_id == pid).one()
        bid_lot = b.id

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t_wo) as ctx:
            _writeoff_once(WriteoffIn(product_id=pid, qty=4, reason="muddati o'tgan",
                                      branch_id=d["bid"],
                                      lots=[WriteoffLot(stock_batch_id=bid_lot, qty=4)],
                                      client_uuid=ctx.key("wo", "lot")),
                           emp, db, at=t_wo)
        db.commit()

    with _db() as db:
        allocs = (db.query(StockMovementLotAllocation)
                  .filter(StockMovementLotAllocation.stock_batch_id == bid_lot).all())
        assert allocs, "partiya allokatsiyasi yozilmadi"
        for a in allocs:
            assert abs((_aw(a.created_at) - t_wo).total_seconds()) < 2, \
                f"allokatsiya `created_at` TARIXIY emas: {a.created_at}"
        b = db.get(StockBatch, bid_lot)
        assert abs((_aw(b.updated_at) - t_wo).total_seconds()) < 2, \
            f"partiya `updated_at` chiqarish paytini olmadi: {b.updated_at}"
    assert _qoldiq(pid, d["bid"]) == Decimal("6")


# ══════════════════════════════════════════════════════════════════════════
#  2) TARIXIY KASSA AMALI (payin / expense)
# ══════════════════════════════════════════════════════════════════════════
def _cash_op_tarixiy(d, *, tur, summa, t, kalit, plan=PLAN, t_open=None):
    from app.api.v1.cashops import CashOpIn, _cash_op_once
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        _tarixiy_smena(db, comp, emp, t_open or (t - timedelta(hours=2)), plan=plan)
        with H.enter(db, comp, plan_id=plan, instant=t) as ctx:
            out = _cash_op_once(CashOpIn(type=tur, amount=summa, reason="H3b",
                                         client_uuid=ctx.key(kalit)),
                                emp, db, at=t)
        db.commit()
    return out


def test_04_tarixiy_KASSA_KIRIMI_vaqti_togri(no_push):
    """`CashMovement.created_at` tarixiy bo'lsin (payin)."""
    from app.models.shifts import CashMovement

    d = _demo()
    t = (NOW - timedelta(days=DEPTH)).replace(hour=12, minute=0, second=0, microsecond=0)
    out = _cash_op_tarixiy(d, tur="payin", summa=5000, t=t, kalit="payin")
    assert out.get("ok") is True, f"{out}"

    with _db() as db:
        rows = (db.query(CashMovement)
                .filter(CashMovement.employee_id == d["eid"]).all())
        assert len(rows) == 1, f"aynan bitta kassa harakati kutilgan: {len(rows)}"
        assert abs((_aw(rows[0].created_at) - t).total_seconds()) < 2, \
            f"`CashMovement.created_at` TARIXIY emas: {rows[0].created_at}"
        assert Decimal(str(rows[0].amount)) == Decimal("5000")


def test_05_tarixiy_KASSA_XARAJATI_vaqti_togri(no_push):
    """`expense` shoxi ham tarixiy vaqtni oladi."""
    from app.models.shifts import CashMovement

    d = _demo()
    t = (NOW - timedelta(days=DEPTH)).replace(hour=13, minute=0, second=0, microsecond=0)
    out = _cash_op_tarixiy(d, tur="expense", summa=3000, t=t, kalit="expense")
    assert out.get("ok") is True, f"{out}"
    with _db() as db:
        rows = (db.query(CashMovement)
                .filter(CashMovement.employee_id == d["eid"]).all())
        assert len(rows) == 1, f"{len(rows)}"
        assert abs((_aw(rows[0].created_at) - t).total_seconds()) < 2, \
            f"TARIXIY emas: {rows[0].created_at}"


# ══════════════════════════════════════════════════════════════════════════
#  3) TARIXIY MIJOZ QARZ TO'LOVI
# ══════════════════════════════════════════════════════════════════════════
def test_06_tarixiy_QARZ_TOLOVI_vaqtlari_togri(no_push):
    """`CustomerPayment.paid_at`/`created_at`, `CreditTransaction.created_at`,
    `CashMovement.created_at` — hammasi tarixiy bo'lsin."""
    from app.api.v1.customers import CreditPayment, _pay_credit_once
    from app.models.customers import CreditTransaction, Customer, CustomerPayment
    from app.models.shifts import CashMovement

    d = _demo()
    cid = _mijoz(d, qarz="50000")
    t = (NOW - timedelta(days=DEPTH)).replace(hour=15, minute=0, second=0, microsecond=0)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        _tarixiy_smena(db, comp, emp, t - timedelta(hours=3))
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            _pay_credit_once(cid, CreditPayment(amount=20000, method="cash",
                                                client_uuid=ctx.key("pay")),
                             emp, db, at=t)
        db.commit()

    with _db() as db:
        pay = db.query(CustomerPayment).filter(CustomerPayment.customer_id == cid).one()
        assert abs((_aw(pay.paid_at) - t).total_seconds()) < 2, f"`paid_at`: {pay.paid_at}"
        assert abs((_aw(pay.created_at) - t).total_seconds()) < 2, \
            f"`created_at`: {pay.created_at}"
        txs = db.query(CreditTransaction).filter(CreditTransaction.customer_id == cid).all()
        assert txs, "`CreditTransaction` yozilmadi"
        for tx in txs:
            assert abs((_aw(tx.created_at) - t).total_seconds()) < 2, \
                f"`CreditTransaction.created_at`: {tx.created_at}"
        cm = db.query(CashMovement).filter(CashMovement.employee_id == d["eid"]).all()
        #  Naqd to'lov kassa harakatini ham yozadi (smena ochiq).
        for m in cm:
            assert abs((_aw(m.created_at) - t).total_seconds()) < 2, \
                f"`CashMovement.created_at`: {m.created_at}"
        c = db.get(Customer, cid)
        assert Decimal(str(c.credit_balance)) == Decimal("30000"), \
            f"qarz balansi: {c.credit_balance}"


# ══════════════════════════════════════════════════════════════════════════
#  4) DETERMINISTIK QAYTA YURGIZISH — DUBLIKAT YO'Q
# ══════════════════════════════════════════════════════════════════════════
def test_07_qayta_yurgizish_CHIQARISHda_dublikat_YARATMAYDI(no_push):
    from app.api.v1.inventory import WriteoffIn, _writeoff_once

    d = _demo()
    pid = _mahsulot(d, qty=20)
    t = (NOW - timedelta(days=DEPTH)).replace(hour=10, minute=0, second=0, microsecond=0)
    comp = _company(d)
    for _urinish in range(2):
        with _db() as db:
            emp = db.get(type(_emp(d)), d["eid"])
            with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
                _writeoff_once(WriteoffIn(product_id=pid, qty=3, reason="brak",
                                          branch_id=d["bid"],
                                          client_uuid=ctx.key("wo", "replay")),
                               emp, db, at=t)
            db.commit()
    mv = _harakatlar(pid, d["bid"])
    assert len(mv) == 1, f"qayta yurgizish DUBLIKAT yaratdi: {mv}"
    assert _qoldiq(pid, d["bid"]) == Decimal("17"), \
        f"qoldiq ikki marta kamaydi: {_qoldiq(pid, d['bid'])}"


def test_08_qayta_yurgizish_KASSA_amalida_dublikat_YARATMAYDI(no_push):
    from app.models.shifts import CashMovement

    d = _demo()
    t = (NOW - timedelta(days=DEPTH)).replace(hour=12, minute=0, second=0, microsecond=0)
    t_open = t - timedelta(hours=2)
    outs = [_cash_op_tarixiy(d, tur="payin", summa=5000, t=t, kalit="payin-replay",
                             t_open=t_open) for _ in range(2)]
    assert outs[1].get("duplicate") is True, f"ikkinchi urinish dublikat emas: {outs[1]}"
    with _db() as db:
        rows = db.query(CashMovement).filter(CashMovement.employee_id == d["eid"]).all()
        assert len(rows) == 1, f"kassa harakati DUBLIKAT: {len(rows)}"


def test_09_qayta_yurgizish_QARZ_TOLOVIda_dublikat_YARATMAYDI(no_push):
    from app.api.v1.customers import CreditPayment, _pay_credit_once
    from app.models.customers import Customer, CustomerPayment

    d = _demo()
    cid = _mijoz(d, qarz="50000")
    t = (NOW - timedelta(days=DEPTH)).replace(hour=15, minute=0, second=0, microsecond=0)
    comp = _company(d)
    kalit = None
    for _urinish in range(2):
        with _db() as db:
            emp = db.get(type(_emp(d)), d["eid"])
            if _urinish == 0:
                _tarixiy_smena(db, comp, emp, t - timedelta(hours=3))
            with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
                kalit = ctx.key("pay", "replay")
                _pay_credit_once(cid, CreditPayment(amount=20000, method="cash",
                                                    client_uuid=kalit),
                                 emp, db, at=t)
            db.commit()
    with _db() as db:
        pays = db.query(CustomerPayment).filter(CustomerPayment.customer_id == cid).all()
        assert len(pays) == 1, f"to'lov DUBLIKAT: {len(pays)}"
        c = db.get(Customer, cid)
        assert Decimal(str(c.credit_balance)) == Decimal("30000"), \
            f"balans ikki marta kamaydi: {c.credit_balance}"


# ══════════════════════════════════════════════════════════════════════════
#  5) YIQILGAN TARIXIY AMAL — NOL QISMIY MUTATSIYA
# ══════════════════════════════════════════════════════════════════════════
def test_10_YIQILGAN_tarixiy_chiqarish_NOL_mutatsiya(no_push):
    """Qoldiqdan ORTIQ chiqarish RAD etilsin va HECH NARSA yozilmasin."""
    from fastapi import HTTPException

    from app.api.v1.inventory import WriteoffIn, _writeoff_once
    from app.models.sync import AuditLog

    d = _demo()
    pid = _mahsulot(d, qty=5)
    t = (NOW - timedelta(days=DEPTH)).replace(hour=10, minute=0, second=0, microsecond=0)
    comp = _company(d)
    with _db() as db:
        oldin_aud = db.query(AuditLog).filter(AuditLog.actor_id == d["eid"]).count()

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            with pytest.raises(HTTPException) as ei:
                _writeoff_once(WriteoffIn(product_id=pid, qty=99, reason="brak",
                                          branch_id=d["bid"], client_uuid=ctx.key("wo", "bad")),
                               emp, db, at=t)
            assert ei.value.status_code == 400, f"{ei.value.status_code}"
        db.rollback()

    assert _harakatlar(pid, d["bid"]) == [], "yiqilgan chiqarish HARAKAT yozdi"
    assert _qoldiq(pid, d["bid"]) == Decimal("5"), "yiqilgan chiqarish QOLDIQNI o'zgartirdi"
    with _db() as db:
        assert db.query(AuditLog).filter(AuditLog.actor_id == d["eid"]).count() == oldin_aud, \
            "yiqilgan chiqarish AUDIT izi yozdi"


def test_11_YIQILGAN_tarixiy_qarz_tolovi_NOL_mutatsiya(no_push):
    """Qarzi YO'Q mijozga to'lov RAD etilsin va hech narsa yozilmasin."""
    from fastapi import HTTPException

    from app.api.v1.customers import CreditPayment, _pay_credit_once
    from app.models.customers import Customer, CustomerPayment

    d = _demo()
    cid = _mijoz(d, qarz="0")
    t = (NOW - timedelta(days=DEPTH)).replace(hour=15, minute=0, second=0, microsecond=0)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            with pytest.raises(HTTPException) as ei:
                _pay_credit_once(cid, CreditPayment(amount=1000, method="cash",
                                                    client_uuid=ctx.key("pay", "bad")),
                                 emp, db, at=t)
            assert ei.value.status_code == 400, f"{ei.value.status_code}"
        db.rollback()
    with _db() as db:
        assert db.query(CustomerPayment).filter(CustomerPayment.customer_id == cid).count() == 0
        assert Decimal(str(db.get(Customer, cid).credit_balance)) == Decimal("0")


# ══════════════════════════════════════════════════════════════════════════
#  6) NORMAL YO'L — HOZIRGI VAQT SAQLANGAN
# ══════════════════════════════════════════════════════════════════════════
def test_12_NORMAL_chiqarish_HOZIRGI_vaqt():
    from app.api.v1.inventory import WriteoffIn, writeoff

    d = _demo()
    pid = _mahsulot(d, qty=20)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        #  MARSHRUT o'rovchisi — pozitsion, AYNAN mavjud testlar kabi.
        writeoff(WriteoffIn(product_id=pid, qty=2, reason="brak", branch_id=d["bid"]),
                 emp, db)
        db.commit()
    mv = _harakatlar(pid, d["bid"])
    assert len(mv) == 1
    assert abs((mv[0][0] - _hozir()).total_seconds()) < 600, \
        f"NORMAL chiqarish HOZIRGI vaqt bilan yozilishi SHART: {mv[0][0]}"


def test_13_NORMAL_kassa_amali_va_qarz_tolovi_HOZIRGI_vaqt():
    from app.api.v1.cashops import CashOpIn, cash_op
    from app.api.v1.customers import CreditPayment, pay_credit
    from app.models.customers import CustomerPayment
    from app.models.enums import ShiftStatus
    from app.models.shifts import CashMovement, Shift

    d = _demo()
    cid = _mijoz(d, qarz="50000")
    #  HOZIRGI ochiq smena — SAHNA (biznes hodisasi emas, `cash_op` uni talab qiladi).
    with _db() as db:
        sh = Shift(id=uuid.uuid4(), branch_id=d["bid"], cashier_id=d["eid"],
                   opened_at=_hozir() - timedelta(hours=1), opening_cash=Decimal("100000"),
                   status=ShiftStatus.open)
        db.add(sh)
        db.commit()
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        cash_op(CashOpIn(type="payin", amount=5000), emp, db)          # pozitsion
        pay_credit(cid, CreditPayment(amount=10000, method="cash"), emp, db)  # pozitsion
        db.commit()
    with _db() as db:
        for m in db.query(CashMovement).filter(CashMovement.employee_id == d["eid"]).all():
            assert abs((_aw(m.created_at) - _hozir()).total_seconds()) < 600, \
                f"NORMAL kassa harakati HOZIRGI vaqt bilan yozilishi SHART: {m.created_at}"
        p = db.query(CustomerPayment).filter(CustomerPayment.customer_id == cid).one()
        assert abs((_aw(p.paid_at) - _hozir()).total_seconds()) < 600, \
            f"NORMAL to'lov HOZIRGI vaqt bilan yozilishi SHART: {p.paid_at}"


# ══════════════════════════════════════════════════════════════════════════
#  7) DARVOZA POLARITESI
# ══════════════════════════════════════════════════════════════════════════
def test_14_kontekstSIZ_at_RAD_etiladi():
    """Tarixiy qobiliyat DARVOZAGA bog'langan, funksiyaga emas (H1 invarianti)."""
    from app.api.v1.cashops import CashOpIn, _cash_op_once
    from app.api.v1.customers import CreditPayment, _pay_credit_once
    from app.api.v1.inventory import WriteoffIn, _writeoff_once

    d = _demo()
    pid = _mahsulot(d, qty=20)
    cid = _mijoz(d)
    t = NOW - timedelta(days=DEPTH)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        for chaqiruv in (
            lambda: _writeoff_once(WriteoffIn(product_id=pid, qty=1, reason="brak",
                                              branch_id=d["bid"]), emp, db, at=t),
            lambda: _cash_op_once(CashOpIn(type="payin", amount=1000), emp, db, at=t),
            lambda: _pay_credit_once(cid, CreditPayment(amount=100, method="cash"),
                                     emp, db, at=t),
        ):
            with pytest.raises(RuntimeError, match="tarixiy kontekst YO'Q"):
                chaqiruv()
            db.rollback()
    assert _qoldiq(pid, d["bid"]) == Decimal("20")


def test_15_kontekst_FAOL_lekin_at_YOQ_RAD():
    """Kontekst ichida `at` ni UNUTISH ham xato — jimgina BUGUN yozilmasin."""
    from app.api.v1.cashops import CashOpIn, _cash_op_once
    from app.api.v1.customers import CreditPayment, _pay_credit_once
    from app.api.v1.inventory import WriteoffIn, _writeoff_once

    d = _demo()
    pid = _mahsulot(d, qty=20)
    cid = _mijoz(d)
    t = NOW - timedelta(days=DEPTH)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t):
            for chaqiruv in (
                lambda: _writeoff_once(WriteoffIn(product_id=pid, qty=1, reason="brak",
                                                  branch_id=d["bid"]), emp, db),
                lambda: _cash_op_once(CashOpIn(type="payin", amount=1000), emp, db),
                lambda: _pay_credit_once(cid, CreditPayment(amount=100, method="cash"),
                                         emp, db),
            ):
                with pytest.raises(RuntimeError, match="`at` berilmadi"):
                    chaqiruv()
                db.rollback()
    assert _qoldiq(pid, d["bid"]) == Decimal("20")


def test_16_BOSHQA_dokon_konteksti_RAD():
    from app.api.v1.inventory import WriteoffIn, _writeoff_once

    a, b = _demo(), _demo()
    pid = _mahsulot(b, qty=20)
    t = NOW - timedelta(days=DEPTH)
    with _db() as db:
        emp_b = db.get(type(_emp(b)), b["eid"])
        with H.enter(db, _company(a), plan_id=PLAN, instant=t):
            with pytest.raises(RuntimeError, match="BOSHQA do'konga"):
                _writeoff_once(WriteoffIn(product_id=pid, qty=1, reason="brak",
                                          branch_id=b["bid"]), emp_b, db, at=t)
        db.rollback()
    assert _qoldiq(pid, b["bid"]) == Decimal("20")


# ══════════════════════════════════════════════════════════════════════════
#  8) OMMAVIY SXEMA VA MARSHRUT MOSLIGI
# ══════════════════════════════════════════════════════════════════════════
def test_17_OMMAVIY_sxemalarda_VAQT_maydoni_YO_Q():
    """Ega qat'iy cheklovi: ommaviy so'rov sxemasiga vaqt maydoni qo'shilmasin."""
    from app.api.v1.cashops import CashOpIn
    from app.api.v1.customers import CreditPayment
    from app.api.v1.inventory import WriteoffIn

    TAQIQ = {"at", "occurred_at", "device_occurred_at", "created_at", "paid_at", "instant"}
    for M in (WriteoffIn, CashOpIn, CreditPayment):
        kesishma = set(M.model_fields) & TAQIQ
        assert not kesishma, \
            f"{M.__name__} sxemasiga VAQT maydoni kirgan: {sorted(kesishma)}"


def test_18_MARSHRUT_imzolari_MOS_qoldi():
    """⚠️  Mavjud testlar yozuvchilarni TO'G'RIDAN, POZITSION chaqiradi.

    Ekstraksiya marshrut NOMINI va parametr TARTIBINI buzmaganini qadaydi:
      · `writeoff(data, emp, db)`                — test_return_cash_posting, test_lot_enable_race_pg
      · `cash_op(data, emp, db)`                 — test_retrofit, test_custody_and_inkassa
      · `pay_credit(customer_id, data, emp, db)` — test_dual_write_parity, test_fresh_tenant_launch,
                                                   test_retrofit
    """
    import inspect

    from app.api.v1.cashops import cash_op
    from app.api.v1.customers import pay_credit
    from app.api.v1.inventory import writeoff

    kutilgan = {
        writeoff: ["data", "emp", "db"],
        cash_op: ["data", "emp", "db"],
        pay_credit: ["customer_id", "data", "emp", "db"],
    }
    for fn, nomlar in kutilgan.items():
        p = list(inspect.signature(fn).parameters)
        assert p == nomlar, f"{fn.__name__} imzosi O'ZGARDI: {p} != {nomlar}"
        #  Marshrutda VAQT parametri BO'LMASLIGI shart (aks holda query param).
        assert "at" not in p, f"{fn.__name__} marshrutiga `at` kirgan — query parametri!"


def test_19_ICHKI_servislar_at_ni_FAQAT_kalit_sozi_bilan_oladi():
    """`at` pozitsion bo'lsa mavjud pozitsion chaqiruvlar uni jimgina to'ldirardi."""
    import inspect

    from app.api.v1.cashops import _cash_op_once
    from app.api.v1.customers import _pay_credit_once
    from app.api.v1.inventory import _writeoff_once

    for fn in (_writeoff_once, _cash_op_once, _pay_credit_once):
        prm = inspect.signature(fn).parameters
        assert "at" in prm, f"{fn.__name__} da `at` YO'Q"
        assert prm["at"].kind is inspect.Parameter.KEYWORD_ONLY, \
            f"{fn.__name__}: `at` KALIT SO'Z bo'lishi SHART, keldi {prm['at'].kind}"


def test_20_tashqi_chiqish_EFFEKTI_NOL(no_push):
    """Tarixiy replay tashqi xabar YUBORMAYDI (H1 bo'g'ish siyosati)."""
    from app.api.v1.inventory import WriteoffIn, _writeoff_once
    from app.models.inventory import Inventory

    d = _demo()
    pid = _mahsulot(d, qty=20)
    with _db() as db:
        inv = db.query(Inventory).filter(Inventory.product_id == pid).one()
        inv.min_qty = 50          # chiqarish kam-qoldiq kesishuvini YONDIRADI
        db.commit()
    t = (NOW - timedelta(days=DEPTH)).replace(hour=10, minute=0, second=0, microsecond=0)
    comp = _company(d)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            _writeoff_once(WriteoffIn(product_id=pid, qty=3, reason="brak",
                                      branch_id=d["bid"], client_uuid=ctx.key("wo", "push")),
                           emp, db, at=t)
        db.commit()
    assert no_push == [], f"tarixiy replay tashqi xabar yubordi: {no_push}"


def test_21_DARVOZA_boshqa_tekshiruvlardan_OLDIN_ishlaydi():
    """⚠️  DARVOZA POZITSIYASI: kontekstsiz `at` BOSHQA tekshiruvlardan OLDIN
        rad etilishi SHART, nafaqat «qachonlardir» rad etilishi.

    `test_14` faqat xato KO'TARILISHINI tekshiradi, QAYERDA ko'tarilishini
    emas — shu bois `assert_gate` olib tashlansa ham u YASHIL qoladi
    (`resolve_at` keyinroq, soat satrida baribir rad etadi). O'LCHANGAN:
    mutatsiya M6 shu sababli qamralmagan edi.

    Bu test farqni ushlaydi: qoldiqdan ORTIQ miqdor bilan, kontekstSIZ `at`
    beriladi. Darvoza BIRINCHI bo'lsa -> `RuntimeError` (tarixiy kontekst
    yo'q). Darvoza KECH bo'lsa -> avval `HTTPException(400, "Yetarli qoldiq
    yo'q")` chiqadi, ya'ni xato CHALG'ITUVCHI va qator allaqachon QULFLANGAN.
    """
    from fastapi import HTTPException

    from app.api.v1.cashops import CashOpIn, _cash_op_once
    from app.api.v1.inventory import WriteoffIn, _writeoff_once

    d = _demo()
    pid = _mahsulot(d, qty=5)
    t = NOW - timedelta(days=DEPTH)
    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        #  CHIQARISH: qty=99 > qoldiq=5 -> kech darvoza 400 berardi.
        try:
            _writeoff_once(WriteoffIn(product_id=pid, qty=99, reason="brak",
                                      branch_id=d["bid"]), emp, db, at=t)
            raise AssertionError("kontekstsiz `at` O'TIB KETDI")
        except RuntimeError as e:
            assert "tarixiy kontekst YO'Q" in str(e), str(e)
        except HTTPException as e:                      # noqa: PERF203
            raise AssertionError(
                f"DARVOZA KECH ishladi: avval {e.status_code} «{e.detail}» chiqdi, "
                f"ya'ni `at` jimgina qabul qilinib qator qulflangan") from e
        db.rollback()

        #  KASSA AMALI: ochiq smena YO'Q -> kech darvoza 400 berardi.
        try:
            _cash_op_once(CashOpIn(type="payin", amount=1000), emp, db, at=t)
            raise AssertionError("kontekstsiz `at` O'TIB KETDI")
        except RuntimeError as e:
            assert "tarixiy kontekst YO'Q" in str(e), str(e)
        except HTTPException as e:                      # noqa: PERF203
            raise AssertionError(
                f"DARVOZA KECH ishladi: avval {e.status_code} «{e.detail}» chiqdi") from e
        db.rollback()

    assert _qoldiq(pid, d["bid"]) == Decimal("5")


def test_22_CHIQARISH_takrori_NOYOB_INDEKS_bilan_ham_toSILADI():
    """⚠️  DEDUP PRE-CHECK va NOYOB INDEKS — ikki QATLAM, biri ikkinchisining
        o'rnini bosmaydi.

    O'LCHANGAN: SELECT-keyin-INSERT pre-check'ini o'chirish dublikat BERMAYDI,
    chunki `ux_stockmov_client_prod_type` (SQLite'da ham NOYOB) ikkinchi
    insert'ni yiqitadi va yozuvchining `except IntegrityError` bloki
    `{"ok": True, "duplicate": True}` qaytaradi. Ya'ni pre-check — qulaylik,
    INDEKS esa KAFOLAT. Kodning o'z izohi shunday deydi: «KONKURRENT takrorni
    faqat noyob indeks to'sadi».

    Shu bois indeks MAVJUDLIGI `require_index` bilan fail-closed qilinadi va
    uning JOYI `tests/test_index_wiring_contract.py` registrida qadalgan —
    H3b ekstraksiyasida registr `_writeoff_once`/`_cash_op_once` ga ko'chdi.

    Bu test ikkinchi qatlamni ANIQ o'lchaydi: javob `duplicate` bo'lsin va
    ikkinchi harakat YOZILMASIN.
    """
    from app.api.v1.inventory import WriteoffIn, _writeoff_once

    d = _demo()
    pid = _mahsulot(d, qty=20)
    t = (NOW - timedelta(days=DEPTH)).replace(hour=10, minute=0, second=0, microsecond=0)
    comp = _company(d)
    javoblar = []
    for _urinish in range(2):
        with _db() as db:
            emp = db.get(type(_emp(d)), d["eid"])
            with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
                javoblar.append(_writeoff_once(
                    WriteoffIn(product_id=pid, qty=3, reason="brak",
                               branch_id=d["bid"], client_uuid=ctx.key("wo", "ix")),
                    emp, db, at=t))
            db.commit()
    assert javoblar[1].get("duplicate") is True, \
        f"ikkinchi urinish `duplicate` qaytarmadi: {javoblar[1]}"
    assert len(_harakatlar(pid, d["bid"])) == 1, "ikkinchi harakat YOZILDI"
    assert _qoldiq(pid, d["bid"]) == Decimal("17")
