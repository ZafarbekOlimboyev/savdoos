# -*- coding: utf-8 -*-
"""PHASE 0 — `pay_supplier` QULF INVERSIYASI (haqiqiy PostgreSQL).

NUQSON (tuzatishdan oldin): `pay_supplier` avval `suppliers` ni `FOR UPDATE` qilib,
so'ng FIFO taqsimotda `purchases` qatorlarini QULFSIZ o'qib UPDATE qilardi (qulf
commit paytida implicit `FOR NO KEY UPDATE` sifatida olinadi). Repodagi global qulf
shartnomasi esa TESKARI yo'nalishni belgilaydi — `purchases` -> `suppliers`
(`services/lot_correction.py:53-88`; `edit_purchase` `purchases.py:715` -> `:734`;
qabul tuzatishi `lot_correction.py:789` -> `:809`). Ikki yo'nalish = AB/BA sikli.

Bu fayl uchta narsani isbotlaydi:

  1. MANFIY NAZORAT — eski TARTIB haqiqatan halokatli: `suppliers`-birinchi va
     `purchases`-birinchi ikki tranzaksiya majburiy interleaving bilan `40P01`
     (deadlock) beradi. Sinov sezgir ekanini shu ko'rsatadi.
  2. TUZATISH — `pay_supplier` endi `purchases` ni BIRINCHI qulflaydi. To'g'ridan-to'g'ri
     o'lchanadi: yozuvchi purchases qulfida kutayotganda `suppliers` qatori UCHINCHI
     sessiya uchun HALI HAM bo'sh (`FOR UPDATE NOWAIT` o'tadi). Eski kodda bu NOWAIT
     `55P03` bilan yiqilardi.
  3. PARITY va IDEMPOTENTLIK o'zgarmagan: taqsimot natijasi, `client_uuid` dublikati,
     konkurrent ayni-uuid, va qayta urinishda DUBLIKAT posting yo'qligi.

⚠️  `method="card"` qulf testlarida ATAYLAB: naqd yo'li smena/custody hal qilishni
    talab qiladi va qulf tartibi savoliga shovqin qo'shadi. Naqd yo'li alohida
    (parity va dublikat) testlarda sinaladi.
"""
from __future__ import annotations

import threading
import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.api.v1 import purchases as purchases_api
from app.api.v1.purchases import SupplierPaymentIn as _SPI
from app.models.auth import Employee
from app.models.cash import CashLedgerEntry
from app.models.enums import PurchaseStatus
from app.models.purchasing import Purchase, Supplier, SupplierPayment

from tests.cash.test_retrofit import (_debt_purchase, _open_shift, _setup_product, _stock,
                                      provision)

KUTISH = 20.0


# ═══ yordamchilar ════════════════════════════════════════════════════════════
def _sqlstate(exc) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


def _bloklangan(engine, kutuvchi_pid: int) -> bool:
    """`kutuvchi_pid` hozir boshqa tranzaksiya qulfini kutyaptimi."""
    with engine.connect() as con:
        return bool(con.execute(text("SELECT cardinality(pg_blocking_pids(:p)) > 0"),
                                {"p": kutuvchi_pid}).scalar())


def _kut(shart, xato: str):
    oxiri = time.monotonic() + KUTISH
    while time.monotonic() < oxiri:
        if shart():
            return
        time.sleep(0.02)
    pytest.fail(xato)


def _deadlock_soni(engine) -> int:
    """Shu bazadagi KUMULYATIV deadlock soni (`pg_stat_database`).

    ⚠️  NEGA KERAK: `pay_supplier` da `40P01` qayta urinish o'rami bor, shu bois
        deadlock YUZ BERSA HAM foydalanuvchi uchun ko'rinmaydi. Qulf TARTIBI
        tuzatilganini retry'dan AJRATIB o'lchash uchun hisoblagich o'qiladi.
    """
    with engine.connect() as con:
        return int(con.execute(text(
            "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
        )).scalar() or 0)


def _qarzli_tenant(db, cashenv, *, nechta=1, cost=10000):
    """Filial + xodim + TILL + mahsulot + ta'minotchi + `nechta` qarz xaridi."""
    emp, br, till = provision(db, cashenv)
    prod, sup = _setup_product(db, cashenv)
    _stock(db, cashenv, prod, br)
    for _ in range(nechta):
        _debt_purchase(db, emp, cashenv, prod, sup, qty=1, cost=cost)
    db.commit()
    return emp, br, till, prod, sup


# ═══ 1. MANFIY NAZORAT — eski TARTIB deadlock beradi ═════════════════════════
def test_MANFIY_NAZORAT_eski_qulf_tartibi_deadlock_beradi(db, cashenv):
    """`suppliers`-birinchi × `purchases`-birinchi = `40P01`.

    Bu `pay_supplier` ning ESKI tartibi (`suppliers` FOR UPDATE, keyin `purchases`)
    va kanonik tartib (`purchases` FOR UPDATE, keyin `suppliers`) o'rtasidagi sikl.
    Sinov xom SQL bilan yoziladi — maqsad KOD emas, TARTIBning o'zi halokatli
    ekanini qotirish.
    """
    _emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv)
    pid = db.query(Purchase.id).filter(Purchase.supplier_id == sup.id).scalar()
    sid = sup.id

    a_sup = threading.Event()      # A `suppliers` ni oldi
    b_pur = threading.Event()      # B `purchases` ni oldi
    natija: dict = {}

    def _eski_tartib():            # A: suppliers -> purchases   (ESKI, noto'g'ri)
        with Session(cashenv.engine) as s:
            try:
                s.execute(text("SELECT 1 FROM suppliers WHERE id=:i FOR UPDATE"), {"i": sid}).all()
                a_sup.set()
                b_pur.wait(KUTISH)
                s.execute(text("SELECT 1 FROM purchases WHERE id=:i FOR UPDATE"), {"i": pid}).all()
                s.commit()
                natija["a"] = "ok"
            except DBAPIError as e:
                s.rollback()
                natija["a"] = _sqlstate(e)

    def _kanonik_tartib():         # B: purchases -> suppliers   (KANONIK)
        with Session(cashenv.engine) as s:
            try:
                a_sup.wait(KUTISH)
                s.execute(text("SELECT 1 FROM purchases WHERE id=:i FOR UPDATE"), {"i": pid}).all()
                b_pur.set()
                s.execute(text("SELECT 1 FROM suppliers WHERE id=:i FOR UPDATE"), {"i": sid}).all()
                s.commit()
                natija["b"] = "ok"
            except DBAPIError as e:
                s.rollback()
                natija["b"] = _sqlstate(e)

    ta = threading.Thread(target=_eski_tartib)
    tb = threading.Thread(target=_kanonik_tartib)
    ta.start(); tb.start(); ta.join(KUTISH + 10); tb.join(KUTISH + 10)

    assert "40P01" in (natija.get("a"), natija.get("b")), (
        "eski TARTIB deadlock BERMADI — sinov sezgir emas: %r" % (natija,))


# ═══ 2. TUZATISH — `pay_supplier` `purchases` ni BIRINCHI qulflaydi ══════════
def test_pay_supplier_purchases_ni_BIRINCHI_qulflaydi(db, cashenv):
    """To'g'ridan-to'g'ri o'lchov: yozuvchi purchases qulfida kutganda `suppliers`
    HALI bo'sh.

    B qarz xaridini `FOR UPDATE` bilan ushlab turadi va `suppliers` ga UMUMAN
    tegmaydi. `pay_supplier` (A) shu qatorni kutishi kerak. Kutayotganda uchinchi
    sessiya (C) `suppliers` ni `FOR UPDATE NOWAIT` bilan olishga urinadi:

      * YANGI kod — A hali `suppliers` ni olmagan  -> NOWAIT O'TADI (isbot);
      * ESKI kod — A birinchi navbatda `suppliers` ni olgan bo'lardi -> `55P03`.
    """
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv)
    pid = db.query(Purchase.id).filter(Purchase.supplier_id == sup.id).scalar()
    sid, eid = sup.id, emp.id

    b_ushladi = threading.Event()
    a_tugadi = threading.Event()
    natija: dict = {}

    def _b_purchases_ni_ushlaydi():
        with Session(cashenv.engine) as s:
            s.execute(text("SELECT 1 FROM purchases WHERE id=:i FOR UPDATE"), {"i": pid}).all()
            b_ushladi.set()
            a_tugadi.wait(KUTISH)          # A bloklangani o'lchangach qo'yib yuboradi
            s.rollback()

    def _a_pay_supplier():
        with Session(cashenv.engine) as s:
            natija["pid"] = s.execute(text("SELECT pg_backend_pid()")).scalar()
            e = s.get(Employee, eid)
            try:
                natija["a"] = purchases_api.pay_supplier(
                    sid, _SPI(amount=10000, method="card"), e, s)
            except Exception as exc:       # noqa: BLE001
                s.rollback()
                natija["a"] = exc

    tb = threading.Thread(target=_b_purchases_ni_ushlaydi)
    tb.start()
    assert b_ushladi.wait(KUTISH), "B purchases qatorini ushlamadi"

    ta = threading.Thread(target=_a_pay_supplier)
    ta.start()
    _kut(lambda: "pid" in natija and _bloklangan(cashenv.engine, natija["pid"]),
         "pay_supplier purchases qulfida KUTMADI — purchases birinchi qulflanmagan")

    # ⚠️  ASOSIY ISBOT: A kutyapti, lekin `suppliers` HALI bo'sh.
    with Session(cashenv.engine) as c:
        try:
            c.execute(text("SELECT 1 FROM suppliers WHERE id=:i FOR UPDATE NOWAIT"), {"i": sid}).all()
            suppliers_bosh = True
        except DBAPIError as e:
            suppliers_bosh = False
            assert _sqlstate(e) == "55P03", _sqlstate(e)
        finally:
            c.rollback()

    a_tugadi.set()
    tb.join(KUTISH + 10); ta.join(KUTISH + 10)

    assert suppliers_bosh, (
        "`pay_supplier` purchases qulfida kutayotib `suppliers` ni ALLAQACHON ushlagan "
        "— qulf inversiyasi QAYTGAN")
    assert not isinstance(natija.get("a"), Exception), natija.get("a")
    assert Decimal(str(natija["a"]["paid"])) == Decimal("10000")


def test_pay_supplier_kanonik_yozuvchi_bilan_deadlock_BERMAYDI(db, cashenv):
    """MAJBURIY interleaving: sikl faqat ESKI tartibda paydo bo'ladi.

    Ketma-ketlik (`pg_blocking_pids` bilan o'lchanadi, tasodifiy emas):
      1. B qarz xaridini `FOR UPDATE` qiladi;
      2. A = `pay_supplier` boshlanadi;
      3. A bloklangani KO'RILGACH B `suppliers` ni so'raydi.

    ESKI kod: 2-qadamda A `suppliers` ni olgan -> 3-qadamda B unda bloklanadi ->
              AB/BA sikli -> `40P01`.
    YANGI kod: A `suppliers` ga umuman tegmagan -> B o'tadi, commit qiladi,
              A qulfni olib ishini tugatadi. Ikkisi ham `ok`.
    """
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv)
    pid = db.query(Purchase.id).filter(Purchase.supplier_id == sup.id).scalar()
    sid, eid = sup.id, emp.id
    dl_oldin = _deadlock_soni(cashenv.engine)

    b_ushladi = threading.Event()
    natija: dict = {}

    def _kanonik():
        with Session(cashenv.engine) as s:
            try:
                s.execute(text("SELECT 1 FROM purchases WHERE id=:i FOR UPDATE"), {"i": pid}).all()
                b_ushladi.set()
                #  A bloklangani KO'RILGACH kutamiz — interleaving majburiy
                _kut(lambda: "pid" in natija and _bloklangan(cashenv.engine, natija["pid"]),
                     "A bloklanmadi")
                s.execute(text("SELECT 1 FROM suppliers WHERE id=:i FOR UPDATE"), {"i": sid}).all()
                s.commit()
                natija["b"] = "ok"
            except DBAPIError as e:
                s.rollback()
                natija["b"] = _sqlstate(e)

    def _tolov():
        with Session(cashenv.engine) as s:
            natija["pid"] = s.execute(text("SELECT pg_backend_pid()")).scalar()
            e = s.get(Employee, eid)
            b_ushladi.wait(KUTISH)
            try:
                purchases_api.pay_supplier(sid, _SPI(amount=5000, method="card"), e, s)
                natija["a"] = "ok"
            except DBAPIError as exc:
                s.rollback()
                natija["a"] = _sqlstate(exc)
            except Exception as exc:       # noqa: BLE001
                s.rollback()
                natija["a"] = repr(exc)

    tb = threading.Thread(target=_kanonik)
    ta = threading.Thread(target=_tolov)
    tb.start(); ta.start(); tb.join(KUTISH + 15); ta.join(KUTISH + 15)

    assert natija.get("a") == "ok", natija
    assert natija.get("b") == "ok", natija
    #  ASOSIY O'LCHOV: deadlock UMUMAN bo'lmagan. Retry o'rami `40P01` ni yutib
    #  yuborishi mumkin, shu bois javobga emas, hisoblagichga qaraymiz.
    assert _deadlock_soni(cashenv.engine) == dl_oldin, (
        "deadlock YUZ BERDI (retry yutib yubordi) — qulf tartibi tuzatilmagan")


# ═══ 3. DETERMINISTIK QULF TARTIBI ══════════════════════════════════════════
def test_qulf_tartibi_DETERMINISTIK_va_taqsimot_bilan_AYNI(db, cashenv):
    """Teng `purchase_date`/`created_at` da tartib `id` bilan aniqlanadi.

    Ilgari tartib `(purchase_date, created_at)` edi — teng bo'lganda SQL rejasiga
    bog'liq, ya'ni QULFLASH tartibi ham noaniq bo'lardi. Qulflanadigan ro'yxat
    taqsimot ro'yxati bilan AYNI bo'lishi ham shu yerda qotiriladi.
    """
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv, nechta=3)
    # Uchtasini AYNI sana/vaqtga qo'yamiz — tartib faqat `id` bilan hal bo'ladi
    rows = db.query(Purchase).filter(Purchase.supplier_id == sup.id).all()
    bir_vaqt = rows[0].created_at
    for r in rows:
        r.purchase_date = rows[0].purchase_date
        r.created_at = bir_vaqt
    db.commit()

    kutilgan = sorted(r.id for r in rows)
    qulflangan = purchases_api._lock_supplier_debts(db, emp.company_id, sup.id)
    taqsimot = [p.id for p in purchases_api._supplier_debt_q(db, emp.company_id, sup.id).all()]
    db.rollback()

    assert qulflangan == kutilgan, "qulf tartibi `id` bo'yicha deterministik emas"
    assert taqsimot == qulflangan, "taqsimot tartibi qulf tartibidan FARQ qiladi"


# ═══ 4. PARITY — FIFO taqsimoti o'zgarmagan ═════════════════════════════════
def test_parity_FIFO_taqsimoti_ozgarmagan(db, cashenv):
    """Uch qarzga qisman to'lov: 1-si to'liq, 2-si qisman, 3-si tegilmagan."""
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv, nechta=3, cost=10000)
    rows = db.query(Purchase).filter(Purchase.supplier_id == sup.id).order_by(Purchase.id).all()
    for i, r in enumerate(rows):                    # aniq FIFO: sana bo'yicha ajratamiz
        r.purchase_date = r.purchase_date.replace(day=1 + i)
    db.commit()

    r = purchases_api.pay_supplier(sup.id, _SPI(amount=15000, method="card"), emp, db)
    assert Decimal(str(r["paid"])) == Decimal("15000")

    db.expire_all()
    got = {str(p.id): (Decimal(str(p.paid_amount)), p.status)
           for p in db.query(Purchase).filter(Purchase.supplier_id == sup.id).all()}
    kutilgan = [
        (Decimal("10000"), PurchaseStatus.received),   # 1-qarz to'liq
        (Decimal("5000"), PurchaseStatus.partial),     # 2-qarz qisman
        (Decimal("0"), PurchaseStatus.debt),           # 3-qarz tegilmagan
    ]
    olingan = [got[str(p.id)] for p in
               db.query(Purchase).filter(Purchase.supplier_id == sup.id)
               .order_by(Purchase.purchase_date).all()]
    assert olingan == kutilgan, olingan
    assert Decimal(str(db.get(Supplier, sup.id).balance)) == Decimal("15000")


# ═══ 5. IDEMPOTENTLIK — o'zgarmagan ═════════════════════════════════════════
def test_idempotentlik_client_uuid_OZGARMAGAN(db, cashenv):
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv, cost=20000)
    cu = uuid.uuid4()
    r1 = purchases_api.pay_supplier(sup.id, _SPI(amount=5000, method="card", client_uuid=cu), emp, db)
    r2 = purchases_api.pay_supplier(sup.id, _SPI(amount=5000, method="card", client_uuid=cu), emp, db)

    assert r1.get("duplicate") is None and r2.get("duplicate") is True
    assert db.query(SupplierPayment).filter(SupplierPayment.client_uuid == cu).count() == 1
    assert Decimal(str(db.get(Supplier, sup.id).balance)) == Decimal("15000")


def test_konkurrent_AYNI_client_uuid_bitta_tolov(db, cashenv):
    """Ikki parallel so'rov, ayni `client_uuid` -> BITTA to'lov qatori."""
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv, cost=20000)
    sid, eid, cu = sup.id, emp.id, uuid.uuid4()
    boshla = threading.Barrier(2, timeout=KUTISH)
    natija: list = []

    def _run():
        with Session(cashenv.engine) as s:
            e = s.get(Employee, eid)
            boshla.wait()
            try:
                natija.append(purchases_api.pay_supplier(
                    sid, _SPI(amount=5000, method="card", client_uuid=cu), e, s))
            except Exception as exc:       # noqa: BLE001
                s.rollback()
                natija.append(exc)

    ts = [threading.Thread(target=_run) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(KUTISH + 10)

    xatolar = [x for x in natija if isinstance(x, Exception)]
    assert not xatolar, xatolar
    assert db.query(SupplierPayment).filter(SupplierPayment.client_uuid == cu).count() == 1, (
        "ayni client_uuid IKKI marta yozildi")
    db.expire_all()
    assert Decimal(str(db.get(Supplier, sup.id).balance)) == Decimal("15000")


# ═══ 6. QAYTA URINISH — dublikat posting YO'Q ═══════════════════════════════
def test_qarz_toplami_ozgarsa_qayta_uriniladi_DUBLIKAT_YOQ(db, cashenv, monkeypatch):
    """Qulf ostida qarz to'plami boshqa chiqsa -> rollback + qayta urinish.

    Birinchi urinishda `_lock_supplier_debts` ATAYLAB ESKIRGAN ro'yxat qaytaradi
    (parallel xarid commit bo'lgan holatning aynan o'zi). Natija: bitta to'lov,
    bitta naqd oyoq — DUBLIKAT YO'Q.
    """
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv, nechta=2, cost=10000)
    haqiqiy = purchases_api._lock_supplier_debts
    urinish = {"n": 0}

    def _fake(db_, company_id, supplier_id):
        urinish["n"] += 1
        ids = haqiqiy(db_, company_id, supplier_id)
        return ids[:-1] if urinish["n"] == 1 else ids      # 1-urinishda ESKIRGAN

    monkeypatch.setattr(purchases_api, "_lock_supplier_debts", _fake)
    r = purchases_api.pay_supplier(sup.id, _SPI(amount=12000, method="card"), emp, db)

    assert urinish["n"] == 2, "qayta urinish bo'lmadi"
    assert Decimal(str(r["paid"])) == Decimal("12000")
    assert db.query(SupplierPayment).filter(SupplierPayment.supplier_id == sup.id).count() == 1, (
        "qayta urinish DUBLIKAT to'lov yozdi")


def test_deadlock_40P01_qayta_uriniladi_va_dublikat_YOQ(db, cashenv, monkeypatch):
    """Birinchi urinishda `40P01` -> 500 emas, qayta urinish; bitta to'lov."""
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv, cost=20000)
    haqiqiy = purchases_api._lock_supplier_debts
    urinish = {"n": 0}

    class _Orig:
        sqlstate = "40P01"

    def _fake(db_, company_id, supplier_id):
        urinish["n"] += 1
        if urinish["n"] == 1:
            raise OperationalError("SELECT 1", {}, _Orig())
        return haqiqiy(db_, company_id, supplier_id)

    monkeypatch.setattr(purchases_api, "_lock_supplier_debts", _fake)
    r = purchases_api.pay_supplier(sup.id, _SPI(amount=7000, method="card"), emp, db)

    assert urinish["n"] == 2
    assert Decimal(str(r["paid"])) == Decimal("7000")
    assert db.query(SupplierPayment).filter(SupplierPayment.supplier_id == sup.id).count() == 1


def test_uch_urinish_ham_yiqilsa_409(db, cashenv, monkeypatch):
    """Doimiy `40P01` -> 500 EMAS, 409 (band) — mavjud `create_purchase` naqshi."""
    from fastapi import HTTPException
    emp, _br, _till, _prod, sup = _qarzli_tenant(db, cashenv, cost=20000)

    class _Orig:
        sqlstate = "40P01"

    monkeypatch.setattr(purchases_api, "_lock_supplier_debts",
                        lambda *a, **k: (_ for _ in ()).throw(
                            OperationalError("SELECT 1", {}, _Orig())))
    with pytest.raises(HTTPException) as ei:
        purchases_api.pay_supplier(sup.id, _SPI(amount=7000, method="card"), emp, db)
    assert ei.value.status_code == 409
    assert db.query(SupplierPayment).filter(SupplierPayment.supplier_id == sup.id).count() == 0


# ═══ 7. NAQD yo'li — ledger oyog'i ham DUBLIKATSIZ ═════════════════════════
def test_naqd_tolov_bitta_ledger_oyogi(db, cashenv, monkeypatch):
    """Naqd yo'lida qayta urinish `SUPPLIER_OUT` oyog'ini IKKI marta yozmaydi."""
    emp, _br, till, _prod, sup = _qarzli_tenant(db, cashenv, cost=20000)
    _open_shift(db, emp, 100000)
    haqiqiy = purchases_api._lock_supplier_debts
    urinish = {"n": 0}

    def _fake(db_, company_id, supplier_id):
        urinish["n"] += 1
        ids = haqiqiy(db_, company_id, supplier_id)
        return [] if urinish["n"] == 1 else ids

    monkeypatch.setattr(purchases_api, "_lock_supplier_debts", _fake)
    purchases_api.pay_supplier(sup.id, _SPI(amount=6000, method="cash"), emp, db)

    assert urinish["n"] == 2
    #  ⚠️  DOIRA: `cashenv` SESSIYA-doirasida, ya'ni tenant boshqa testlar bilan
    #      BO'LISHILADI. Oyoqlar SHU to'lov id'si bo'yicha sanaladi, aks holda
    #      to'plamda boshqa testlarning `SUPPLIER_PAYMENT` oyoqlari ham kirardi.
    pays = db.query(SupplierPayment).filter(SupplierPayment.supplier_id == sup.id).all()
    assert len(pays) == 1, "qayta urinish DUBLIKAT to'lov yozdi"
    oyoqlar = (db.query(CashLedgerEntry)
               .filter(CashLedgerEntry.tenant_id == cashenv.company_id,
                       CashLedgerEntry.source_type == "SUPPLIER_PAYMENT",
                       CashLedgerEntry.source_id == pays[0].id).all())
    assert len(oyoqlar) == 1, "qayta urinish ikkinchi ledger oyog'ini yozdi"
    assert Decimal(str(oyoqlar[0].amount)) == Decimal("6000")
