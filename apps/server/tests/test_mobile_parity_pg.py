# -*- coding: utf-8 -*-
"""PHASE 5G — `GET /cash/custody-preview` REJIMI  ⇒  YOZUVCHI XULQI (haqiqiy Postgres).

⚠️  NEGA PG. Custody qarori `cash.cash_accounts` qatorlariga (TILL/SAFE, ACTIVE/ARCHIVED,
    tenant, filial) qaraydi — bu jadval ATAYLAB faqat Postgres'da (`cash` sxemasi). SQLite'da
    rejimlarning birortasi ham TUG'ILMAYDI (hammasi NOT_REQUIRED), ya'ni sinov «yashil»
    bo'lib hech narsani o'lchamasdi.

HAR REJIM HAQIQIY YOZUVCHI BILAN TEKSHIRILADI (amal bo'yicha):
    NOT_REQUIRED          -> yozuvchi hisobsiz 200
    OPERATOR_MUST_CHOOSE  -> hisobsiz 400 CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER;
                             `options` dagi HAR hisob bilan 200; begona filial yoki
                             ARXIVLANGAN hisob bilan 400 CASH_CUSTODY_ACCOUNT_INVALID;
                             `options` = AYNAN filialning faol hisoblari (begona/arxiv YO'Q)
    SERVER_RESOLVED       -> yozuvchi hisobsiz 200 va AYNAN `resolved` hisobni yozadi
    BLOCKED               -> yozuvchi hisobsiz HAM, tanlov bilan HAM rad etadi (AYNI kod)

Amallar: `receiving_payment` (`POST /receiving/commit`), `debt_payment`
(`POST /customers/{id}/payments`), `supplier_payment` (`POST /suppliers/{id}/payments`),
`collection_destination` (`POST /cash/ops`, type=collection).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`
bilan PG18 servisida ham). Har stsenariy O'Z do'konida — T0 do'kon darajasida.
"""
import uuid
from decimal import Decimal

from fastapi import HTTPException

from app.services.cash import cutover_guard as CG
from tests.test_cash_custody_correction import _dokon, _emp, _hisob, _pul, _smena, _t0
from tests.test_check_defs_pg import pg_target  # noqa: F401
from tests.test_receiving_correction_pg import _baza

REQUIRED = CG.ERR_CUSTODY_REQUIRED
INVALID = CG.ERR_CUSTODY_INVALID


# ══ STSENARIY ═══════════════════════════════════════════════════════════════

def _sc(S, *, t0: bool, shift: str | None):
    """Do'kon (2 filial) + hisoblar: TILL va SAFE (1-filial, pul bilan), begona filial TILL/SAFE,
    ARXIVLANGAN TILL/SAFE. `shift`: None | "till" (smena kassaga bog'langan) | "legacy"."""
    d = _dokon(S, ikkinchi_filial=True)
    acc = {"till": _hisob(S, d), "safe": _hisob(S, d, typ="SAFE"),
           "foreign_till": _hisob(S, d, branch=d["bid2"]),
           "foreign_safe": _hisob(S, d, typ="SAFE", branch=d["bid2"]),
           "arch_till": _hisob(S, d, status="ARCHIVED"),
           "arch_safe": _hisob(S, d, typ="SAFE", status="ARCHIVED")}
    _pul(S, d, acc["till"])
    _pul(S, d, acc["safe"])
    if shift is not None:
        _smena_pul(S, d, till=(acc["till"] if shift == "till" else None))
    if t0:
        _t0(S, d)
    return d, acc


def _smena_pul(S, d, *, till=None):
    """`_smena` + boshlang'ich naqd (inkassa legacy kassa qoldig'i tekshiruvidan o'tsin)."""
    from app.models.shifts import Shift
    sid = _smena(S, d, till=till)
    s = S()
    try:
        s.get(Shift, sid).opening_cash = Decimal("100000")
        s.commit()
    finally:
        s.close()
    return sid


def _preview(S, d, op):
    """HAQIQIY endpoint funksiyasi (marshrut darvozasi ega uchun ochiq)."""
    from app.api.v1.cashops import custody_preview
    s = S()
    try:
        return custody_preview(operation=op, emp=_emp(s, d), db=s)
    finally:
        s.close()


def _run(S, go):
    """Yozuvchini O'Z sessiyasida — (200, javob) yoki (status, detail, kod)."""
    s = S()
    try:
        try:
            return 200, go(s)
        except HTTPException as e:
            return e.status_code, str(e.detail), CG.code_of(e.detail)
    finally:
        s.close()


def _ids(opts):
    return sorted(o["id"] for o in opts)


def _rad(res, kod, status=400):
    assert res[0] == status and res[2] == kod, res


# ══ YOZUVCHILAR ═════════════════════════════════════════════════════════════

def _w_receiving(d, account=None):
    from app.api.v1.receiving import CommitIn, commit

    def go(s):
        return commit(CommitIn(
            items=[{"product_id": str(d["pid"]), "qty": 1, "unit_cost": 50, "unit": "dona",
                    "lots": [{"qty": 1, "batch_number": "P-1"}]}],
            supplier_id=d["sup"], payment="cash", source="manual",
            cash_account_id=(account["id"] if account else None),
            client_uuid=uuid.uuid4()), emp=_emp(s, d), db=s)
    return go


def _recorded_receiving(S, res):
    from app.models.purchasing import Purchase
    s = S()
    try:
        acc = s.get(Purchase, uuid.UUID(res[1]["purchase_id"])).cash_account_id
        return str(acc) if acc else None
    finally:
        s.close()


def _customer(S, d):
    from app.models.customers import Customer
    s = S()
    try:
        c = Customer(id=uuid.uuid4(), company_id=d["cid"], code="M-" + uuid.uuid4().hex[:6],
                     full_name="5G qarzdor", credit_balance=Decimal("100000"))
        s.add(c)
        s.commit()
        d["cust"] = c.id
        return d
    finally:
        s.close()


def _w_debt(d, account=None):
    from app.api.v1.customers import pay_credit
    from app.schemas.customer import CreditPayment
    cu = uuid.uuid4()

    def go(s):
        out = pay_credit(d["cust"], CreditPayment(
            amount=10, method="cash", client_uuid=cu,
            cash_account_id=(account["id"] if account else None)), emp=_emp(s, d), db=s)
        return {**out, "cu": cu}
    return go


def _recorded_debt(S, res):
    from app.models.customers import CustomerPayment
    s = S()
    try:
        p = s.query(CustomerPayment).filter(CustomerPayment.client_uuid == res[1]["cu"]).one()
        return str(p.cash_account_id) if p.cash_account_id else None
    finally:
        s.close()


def _supplier_debt(S, d):
    from app.models.purchasing import Supplier
    s = S()
    try:
        s.get(Supplier, d["sup"]).balance = Decimal("100000")
        s.commit()
        return d
    finally:
        s.close()


def _w_supplier(d, account=None):
    from app.api.v1.purchases import SupplierPaymentIn, pay_supplier
    cu = uuid.uuid4()

    def go(s):
        out = pay_supplier(d["sup"], SupplierPaymentIn(
            amount=10, method="cash", client_uuid=cu,
            cash_account_id=(account["id"] if account else None)), emp=_emp(s, d), db=s)
        return {**out, "cu": cu}
    return go


def _recorded_supplier(S, res):
    from app.models.purchasing import SupplierPayment
    s = S()
    try:
        p = s.query(SupplierPayment).filter(SupplierPayment.client_uuid == res[1]["cu"]).one()
        return str(p.cash_account_id) if p.cash_account_id else None
    finally:
        s.close()


def _w_collection(d, account=None):
    from app.api.v1.cashops import CashOpIn, cash_op

    def go(s):
        return cash_op(CashOpIn(type="collection", amount=10, client_uuid=uuid.uuid4(),
                                destination_safe_id=(account["id"] if account else None)),
                       emp=_emp(s, d), db=s)
    return go


# ══ UMUMIY TEKSHIRUV — BITTA AMAL, HAMMA REJIM ══════════════════════════════

def _parity(S, op, writer, recorded, prep=lambda S, d: d):
    """receiving/debt/supplier uchun AYNI rejim jadvali (`resolve_cash_custody` oilasi)."""
    # NOT_REQUIRED — pre-T0, smenasiz: yozuvchi hisobsiz o'tadi.
    d, acc = _sc(S, t0=False, shift=None)
    d = prep(S, d)
    p = _preview(S, d, op)
    assert p == {"mode": "NOT_REQUIRED", "reason": None, "resolved": None, "options": [],
                 "branch": {"id": str(d["bid"]), "name": "Markaz"}}, p
    res = _run(S, writer(d))
    assert res[0] == 200, res
    assert recorded(S, res) is None, "pre-T0 hisobsiz yozuv hisob O'YLAB TOPDI"

    # OPERATOR_MUST_CHOOSE — post-T0, smenasiz.
    d, acc = _sc(S, t0=True, shift=None)
    d = prep(S, d)
    p = _preview(S, d, op)
    assert (p["mode"], p["reason"], p["resolved"]) == ("OPERATOR_MUST_CHOOSE", REQUIRED, None), p
    assert _ids(p["options"]) == sorted([str(acc["till"]["id"]), str(acc["safe"]["id"])]), p
    assert {o["type"] for o in p["options"]} == {"TILL", "SAFE"}
    assert set(p["options"][0]) == {"id", "type", "code", "currency"}     # yangi oshkorlik YO'Q
    assert p["branch"] == {"id": str(d["bid"]), "name": "Markaz"}
    _rad(_run(S, writer(d)), REQUIRED)
    for bad in ("foreign_till", "foreign_safe", "arch_till", "arch_safe"):
        _rad(_run(S, writer(d, acc[bad])), INVALID)
    for opt in p["options"]:
        res = _run(S, writer(d, {"id": uuid.UUID(opt["id"])}))
        assert res[0] == 200, (opt, res)
        assert recorded(S, res) == opt["id"], (opt, res)

    # SERVER_RESOLVED — post-T0, aktyorning kassaga bog'langan smenasi.
    d, acc = _sc(S, t0=True, shift="till")
    d = prep(S, d)
    p = _preview(S, d, op)
    assert (p["mode"], p["reason"], p["options"]) == ("SERVER_RESOLVED", None, []), p
    assert p["resolved"]["id"] == str(acc["till"]["id"]) and p["resolved"]["type"] == "TILL"
    res = _run(S, writer(d))
    assert res[0] == 200, res
    assert recorded(S, res) == p["resolved"]["id"], "yozuvchi `resolved` dan BOSHQA hisob yozdi"
    _rad(_run(S, writer(d, acc["safe"])), CG.ERR_TILL_SHIFT_MISMATCH)    # smena kassasi USTUN

    # BLOCKED — post-T0, kassasiz (legacy) smena: hisob ham qutqarmaydi.
    d, acc = _sc(S, t0=True, shift="legacy")
    d = prep(S, d)
    p = _preview(S, d, op)
    assert (p["mode"], p["reason"], p["options"]) == (
        "BLOCKED", CG.ERR_LEGACY_SHIFT_NEEDS_TILL, []), p
    _rad(_run(S, writer(d)), CG.ERR_LEGACY_SHIFT_NEEDS_TILL)
    _rad(_run(S, writer(d, acc["till"])), CG.ERR_LEGACY_SHIFT_NEEDS_TILL)


def test_PG_PREVIEW_receiving_payment_REJIM_YOZUVCHI_PARITETI(pg_target):
    eng, S = _baza(pg_target)
    try:
        _parity(S, "receiving_payment", _w_receiving, _recorded_receiving)
    finally:
        eng.dispose()


def test_PG_PREVIEW_debt_payment_REJIM_YOZUVCHI_PARITETI(pg_target):
    eng, S = _baza(pg_target)
    try:
        _parity(S, "debt_payment", _w_debt, _recorded_debt, prep=_customer)
    finally:
        eng.dispose()


def test_PG_PREVIEW_supplier_payment_REJIM_YOZUVCHI_PARITETI(pg_target):
    eng, S = _baza(pg_target)
    try:
        _parity(S, "supplier_payment", _w_supplier, _recorded_supplier, prep=_supplier_debt)
    finally:
        eng.dispose()


def test_PG_TAMINOTCHI_tolovi_SMENASIZ_begona_filial_hisobi_RAD_T0_gacha_HAM(pg_target):
    """§1.7 — smenasiz ta'minotchi to'lovida custody filiali = `actor_branch`.

    ⚠️  ILGARI `branch_id=None` uzatilardi va `require_custody_account` filial tekshiruvini
        O'TKAZIB YUBORARDI: boshqa filial kassasidan naqd chiqarib yuborish mumkin edi (pre-T0
        da aniq hisob BERILSA u ham validatsiya qilinib ISHLATILADI — shu bois ikkala holat)."""
    eng, S = _baza(pg_target)
    try:
        for t0 in (False, True):
            d, acc = _sc(S, t0=t0, shift=None)
            d = _supplier_debt(S, d)
            for bad in ("foreign_till", "foreign_safe"):
                res = _run(S, _w_supplier(d, acc[bad]))
                _rad(res, INVALID)
                assert "boshqa filialga tegishli" in res[1], res
            ok = _run(S, _w_supplier(d, acc["till"]))
            assert ok[0] == 200 and _recorded_supplier(S, ok) == str(acc["till"]["id"]), ok
            assert _preview(S, d, "supplier_payment")["branch"]["id"] == str(d["bid"])
    finally:
        eng.dispose()


def test_PG_PREVIEW_collection_destination_REJIM_YOZUVCHI_PARITETI(pg_target):
    eng, S = _baza(pg_target)
    try:
        # BLOCKED — ochiq smena YO'Q: yozuvchi «Ochiq smena yo'q» (AYNI kod sarlavhada).
        d, acc = _sc(S, t0=True, shift=None)
        p = _preview(S, d, "collection_destination")
        assert (p["mode"], p["reason"], p["options"]) == ("BLOCKED", "OPEN_SHIFT_REQUIRED", []), p
        res = _run(S, _w_collection(d, acc["safe"]))
        assert res[0] == 400 and res[1].startswith("Ochiq smena yo'q"), res

        # OPERATOR_MUST_CHOOSE — kassa quyi tizimi bor joyda T0 dan QAT'I NAZAR.
        for t0 in (False, True):
            d, acc = _sc(S, t0=t0, shift="till")
            p = _preview(S, d, "collection_destination")
            assert (p["mode"], p["reason"], p["resolved"]) == (
                "OPERATOR_MUST_CHOOSE", REQUIRED, None), (t0, p)
            # FAQAT shu filialning FAOL SAFE lari — TILL, begona, arxiv YO'Q.
            assert _ids(p["options"]) == [str(acc["safe"]["id"])], p
            _rad(_run(S, _w_collection(d)), REQUIRED)
            for bad in ("foreign_safe", "arch_safe", "till", "foreign_till"):
                _rad(_run(S, _w_collection(d, acc[bad])), INVALID)
            res = _run(S, _w_collection(d, {"id": uuid.UUID(p["options"][0]["id"])}))
            assert res[0] == 200 and "duplicate" not in res[1], (t0, res)

        # BLOCKED — post-T0 kassasiz (legacy) smena.
        d, acc = _sc(S, t0=True, shift="legacy")
        p = _preview(S, d, "collection_destination")
        assert (p["mode"], p["reason"]) == ("BLOCKED", CG.ERR_LEGACY_SHIFT_NEEDS_TILL), p
        _rad(_run(S, _w_collection(d, acc["safe"])), CG.ERR_LEGACY_SHIFT_NEEDS_TILL)

        # BLOCKED — pre-T0 kassasiz smena: manba (smena kassasi) YO'Q, seyf qutqarmaydi.
        d, acc = _sc(S, t0=False, shift="legacy")
        p = _preview(S, d, "collection_destination")
        assert (p["mode"], p["reason"]) == ("BLOCKED", REQUIRED), p
        res = _run(S, _w_collection(d, acc["safe"]))
        _rad(res, REQUIRED)
        assert "'collection_source'" in res[1], res
    finally:
        eng.dispose()


def test_PG_PREVIEW_HECH_NARSA_YOZMAYDI_va_kuzatuv_jurnaliga_TUSHMAYDI(pg_target, monkeypatch):
    """Ekran har ochilganda qaror QAYTA hisoblanadi: u yozuv qoldirsa yoki `cash_failure`
    jurnalini to'ldirsa, haqiqiy rad etishlar soxtalari orasida yo'qolardi."""
    from app.models.cash import CashLedgerEntry
    from app.services.cash import observability as OBS
    eng, S = _baza(pg_target)
    try:
        yozildi: list = []
        asl = OBS.log_cash_failure
        monkeypatch.setattr(OBS, "log_cash_failure",
                            lambda code, **kw: (yozildi.append(code), asl(code, **kw))[1])
        d, acc = _sc(S, t0=True, shift="legacy")
        d = _supplier_debt(S, _customer(S, d))

        def _sanoq():
            s = S()
            try:
                return s.query(CashLedgerEntry).filter(CashLedgerEntry.tenant_id == d["cid"]).count()
            finally:
                s.close()
        oldin = _sanoq()
        for op in ("receiving_payment", "debt_payment", "supplier_payment",
                   "collection_destination"):
            assert _preview(S, d, op)["mode"] == "BLOCKED", op
        assert yozildi == [] and _sanoq() == oldin, yozildi
        # MANFIY NAZORAT: haqiqiy yozuvchining rad etishi jurnalga TUSHADI.
        _rad(_run(S, _w_receiving(d)), CG.ERR_LEGACY_SHIFT_NEEDS_TILL)
        assert yozildi == [CG.ERR_LEGACY_SHIFT_NEEDS_TILL], yozildi
    finally:
        eng.dispose()


def test_PG_PURCHASE_bloki_OZGARMADI_yadro_BITTA(pg_target):
    """`GET /purchases/{id}.cash_custody` (Phase 5E) va `custody-preview` — AYNI yadro:
    naqd hujjatda smenasiz post-T0 ikkalasi ham OPERATOR_MUST_CHOOSE va AYNI tanlov beradi."""
    from app.api.v1.purchases import purchase_detail
    eng, S = _baza(pg_target)
    try:
        d, acc = _sc(S, t0=False, shift=None)
        res = _run(S, _w_receiving(d, acc["till"]))
        assert res[0] == 200, res
        _t0(S, d)
        s = S()
        try:
            blk = purchase_detail(uuid.UUID(res[1]["purchase_id"]), emp=_emp(s, d),
                                  db=s)["cash_custody"]
        finally:
            s.close()
        p = _preview(S, d, "receiving_payment")
        assert blk["mode"] == p["mode"] == "OPERATOR_MUST_CHOOSE", (blk, p)
        assert blk["options"] == p["options"] and blk["branch"] == p["branch"], (blk, p)
    finally:
        eng.dispose()


def test_PG_PREVIEW_ichki_xatoda_FAIL_CLOSED(pg_target, monkeypatch):
    """Kutilmagan xato «hisob kerak emas» degan MA'NONI bermaydi — BLOCKED, sahifa esa 500 emas."""
    from app.services.cash import custody_preview as CP
    eng, S = _baza(pg_target)
    try:
        d, _acc = _sc(S, t0=False, shift="till")

        def _buzuq(*a, **k):
            raise RuntimeError("sinov: ichki xato")
        monkeypatch.setattr(CP, "decide", _buzuq)
        monkeypatch.setattr(CP, "collection_source", _buzuq)
        for op in ("receiving_payment", "debt_payment", "supplier_payment",
                   "collection_destination"):
            p = _preview(S, d, op)
            assert (p["mode"], p["reason"], p["options"]) == (
                "BLOCKED", CG.ERR_LEDGER_UNAVAILABLE, []), (op, p)
            assert p["branch"]["id"] == str(d["bid"]), (op, p)
    finally:
        eng.dispose()


# ══ INTEGRATSIYA (IC): filial doirasi va mijoz tarixi — HAQIQIY Postgres ═════
#
# ⚠️  NEGA PG HAM. SQLite'da NUMERIC yig'indisi float bo'lib qaytadi; production'da esa
#     `Decimal`. `items_qty` formati, korrelyatsiyali `LIMIT 1` subquery va uuid filial
#     to'plamlari AYNAN production dialektida tekshiriladi.

def test_PG_IC_filial_doirasi_va_mijoz_tarixi(pg_target):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import event

    from app.api.v1.customers import customer_detail
    from app.api.v1.inventory import low_stock, overview
    from app.api.v1.products import product_detail
    from app.models.catalog import Product, Unit
    from app.models.customers import Customer, CustomerPayment
    from app.models.enums import MovementType
    from app.models.inventory import Inventory, StockMovement
    from app.models.sales import Sale, SaleItem, SalePayment
    eng, S = _baza(pg_target)
    now = datetime.now(timezone.utc)
    try:
        d = _customer(S, _dokon(S, ikkinchi_filial=True))
        b1, b2 = d["bid"], d["bid2"]
        s = S()
        try:
            unit = s.query(Unit).first()
            p = Product(id=uuid.uuid4(), company_id=d["cid"], name="IC PG " + uuid.uuid4().hex[:6],
                        article_code="IC-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                        unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
            s.add(p)
            s.flush()
            s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b1, qty=Decimal("1.5"),
                            min_qty=Decimal("3"), updated_at=now))
            s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b2, qty=Decimal("7"),
                            min_qty=Decimal("4"), updated_at=now))
            s.add(StockMovement(product_id=p.id, branch_id=b2, type=MovementType.purchase_in,
                                qty=Decimal("7"), created_at=now))
            cust = s.get(Customer, d["cust"])
            sales = []
            for i, (qtys, pays) in enumerate((([Decimal("1.5"), Decimal("2")], ["card", "cash"]),
                                              ([Decimal("0.125")], []))):
                sale = Sale(id=uuid.uuid4(), receipt_no="IC-" + uuid.uuid4().hex[:8],
                            company_id=d["cid"], branch_id=b1, cashier_id=d["emp"],
                            customer_id=cust.id, subtotal=100, total=100,
                            sold_at=now - timedelta(hours=2 - i))
                s.add(sale)
                s.flush()
                for q in qtys:
                    s.add(SaleItem(sale_id=sale.id, product_id=p.id, name_snapshot="IC",
                                   qty=q, unit_price=100, line_total=q * 100))
                    s.flush()
                for m in pays:
                    s.add(SalePayment(sale_id=sale.id, method_code=m, amount=50, paid_at=now))
                    s.flush()
                sales.append(sale)
            s.add(CustomerPayment(customer_id=cust.id, amount=Decimal("10"), method="qr",
                                  paid_at=now, created_at=now))
            s.commit()
            want = [(str(sales[1].id), sales[1].receipt_no, 0, "0.125", "cash"),
                    (str(sales[0].id), sales[0].receipt_no, 3, "3.500", "card")]
        finally:
            s.close()

        s = S()
        try:
            emp = _emp(s, d)
            n: list = []

            def _sana(*_a, **_k):
                n.append(1)
            event.listen(eng, "before_cursor_execute", _sana)
            try:
                j = customer_detail(d["cust"], emp=emp, db=s)
            finally:
                event.remove(eng, "before_cursor_execute", _sana)
            assert [(r["sale_id"], r["receipt_no"], r["items"], r["items_qty"], r["method"])
                    for r in j["history"]] == want, j["history"]
            assert [(pp["method"], pp["amount"]) for pp in j["payments"]] == [("qr", 10.0)]
            # Tarix: 1 SELECT (subquery'lar ichida) + selectin (qatorlar, to'lovlar) — qatorga
            # BOG'LIQ EMAS. Yuqori chegara: mijoz + tarix(3) + to'lovlar + jami + tashriflar.
            assert len(n) <= 7, len(n)

            assert overview(branch_id=None, emp=emp, db=s)["low_count"] == 1
            assert overview(branch_id=b1, emp=emp, db=s)["low_count"] == 1
            assert overview(branch_id=b2, emp=emp, db=s) == {
                "total_products": 2, "low_count": 0, "out_count": 0, "moves_today": 1}
            low = low_stock(branch_id=b1, emp=emp, db=s)
            assert low == [{"name": p.name, "qty": 1.5, "min": 3.0, "product_id": str(p.id)}], low
            assert low_stock(branch_id=b2, emp=emp, db=s) == []
            k = product_detail(p.id, branch_id=b2, emp=emp, db=s)
            assert (k["stock"], k["min_stock"], k["month_in"]) == (7.0, 4.0, 7.0), k
            k = product_detail(p.id, branch_id=None, emp=emp, db=s)
            assert (k["stock"], k["min_stock"], k["month_in"]) == (8.5, 4.0, 7.0), k
            try:
                overview(branch_id=uuid.uuid4(), emp=emp, db=s)
                raise AssertionError("noma'lum filial qabul qilindi")
            except HTTPException as e:
                assert (e.status_code, e.detail) == (400, "Filial topilmadi")
        finally:
            s.close()
    finally:
        eng.dispose()
