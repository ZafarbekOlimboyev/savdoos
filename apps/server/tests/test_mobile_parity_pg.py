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
    """Yozuvchini O'Z sessiyasida — (200, javob) yoki (status, detail, kod, SARLAVHA kodi).

    ⚠️  TO'RTINCHI element — `HTTPException.headers[X-Error-Code]`, ya'ni HTTP mijoz
        HAQIQATAN ko'radigan qiymat (FastAPI uni javob sarlavhasiga o'zgarishsiz
        qo'yadi; SQLite faylida AYNI shart TestClient bilan o'lchanadi). Uchinchi
        element matn prefiksidan o'qiladi — `KEY_REUSED_TEXT` o'sha kod bilan
        BOSHLANGANI uchun u yolg'iz o'zi sarlavha kontraktini ISBOTLAMAYDI."""
    s = S()
    try:
        try:
            return 200, go(s)
        except HTTPException as e:
            return (e.status_code, str(e.detail), CG.code_of(e.detail),
                    (e.headers or {}).get("X-Error-Code"))
    finally:
        s.close()


def _ids(opts):
    return sorted(o["id"] for o in opts)


def _rad(res, kod, status=400):
    assert res[0] == status and res[2] == kod, res


def _kalit_band(res):
    """«Kalit band» rad etishining TO'LIQ kontrakti: 409 + SARLAVHA kodi + matn prefiksi.

    ⚠️  `res[2]` (`CG.code_of`) bu yerda DOIM None: `IDEMPOTENCY_KEY_REUSED` kassa
        custody kodlari ro'yxatida emas. Shu bois eski «kod YOKI matn ichida» sharti
        matn disjunksiyasi hisobiga HAR DOIM yashil edi va sarlavhani UMUMAN
        o'lchamasdi — mijoz (`errors.dart`, `serverErrorsCash.ts`) esa AYNAN
        `X-Error-Code` ga qarab tarjima qiladi. Endi ikkalasi ALOHIDA tekshiriladi."""
    assert res[0] == 409, res
    assert res[3] == "IDEMPOTENCY_KEY_REUSED", f"X-Error-Code sarlavhasi: {res[3]!r}"
    assert str(res[1]).startswith("IDEMPOTENCY_KEY_REUSED:"), res[1]


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


# ══ FX-A. PUL IDEMPOTENTLIGI — HAQIQIY POSTGRES ═════════════════════════════
#
# ⚠️  NEGA PG. Bu yerdagi kafolat — DB NOYOBLIK INDEKSI va QATOR QULFI. SQLite'da
#     `with_for_update` bezarar no-op, noyoblik poygasi esa umuman tug'ilmaydi.

def _hozir():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _kassir(S, d, ism="FXA kassir"):
    """Qo'shimcha kassir (bir kassirda BITTA ochiq smena — `ux_shifts_cashier_open`)."""
    from app.models.auth import Employee, Role
    s = S()
    try:
        r = s.query(Role).filter(Role.code == "kassir").one()
        e = Employee(id=uuid.uuid4(), company_id=d["cid"], full_name=ism,
                     phone="+9987" + str(uuid.uuid4().int)[:8], role_id=r.id)
        s.add(e)
        s.commit()
        return e.id
    finally:
        s.close()


def _smena_ochiq(S, d, cashier, *, opening="3000000", soat=0):
    """`soat` — `opened_at` ni ORQAGA suradi: `cash_op_shift` ENG YANGI ochiq smenani
    tanlaydi, shu bois «eski smena» va «yangi smena» ATAYLAB aniq tartibda."""
    from datetime import timedelta
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = S()
    try:
        sh = Shift(id=uuid.uuid4(), branch_id=d["bid"], cashier_id=cashier,
                   opened_at=_hozir() - timedelta(hours=soat), opening_cash=Decimal(opening),
                   status=ShiftStatus.open)
        s.add(sh)
        s.commit()
        return sh.id
    finally:
        s.close()


def _smena_yop(S, sid):
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = S()
    try:
        sh = s.get(Shift, sid)
        sh.status = ShiftStatus.closed
        sh.closed_at = _hozir()
        s.commit()
    finally:
        s.close()


def _cashop(d, *, tur="expense", summa=10, cu):
    from app.api.v1.cashops import CashOpIn, cash_op

    def go(s):
        return cash_op(CashOpIn(type=tur, amount=summa, client_uuid=cu), emp=_emp(s, d), db=s)
    return go


def _mv_qator(S, shift_id, cu, summa="10"):
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement
    return CashMovement(shift_id=shift_id, type=CashMovementType.expense,
                        amount=Decimal(summa), created_at=_hozir(), client_uuid=cu)


def _mv_rows(S, cu):
    from app.models.shifts import CashMovement
    s = S()
    try:
        return [(str(m.shift_id), m.type.value, float(m.amount)) for m in
                s.query(CashMovement).filter(CashMovement.client_uuid == cu)
                .order_by(CashMovement.created_at).all()]
    finally:
        s.close()


def test_PG_FXA_KASSA_kalit_NOYOBLIGI_SMENADAN_QATI_NAZAR(pg_target):
    """DB KAFOLATI. `ux_cashmov_client_uuid_all` — `(client_uuid)`, SMENA ICHIDA emas.

    Ilgari yagona indeks `(shift_id, client_uuid)` edi: AYNI kalit BOSHQA smenaga
    bemalol yozilardi — ya'ni «ikki marta yozilmaydi» va'dasi ortida DB to'sig'i
    YO'Q edi. Buni jonli Postgres katalogi va HAQIQIY INSERT isbotlaydi."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    eng, S = _baza(pg_target)
    try:
        with eng.connect() as con:
            df = con.execute(text(
                "SELECT pg_get_indexdef(i.indexrelid), i.indisunique FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = "
                "'ux_cashmov_client_uuid_all'")).first()
        assert df is not None, "ux_cashmov_client_uuid_all indeksi YO'Q"
        assert df[1] is True and "(client_uuid)" in df[0], df[0]
        assert "shift_id" not in df[0], df[0]
        assert "client_uuid IS NOT NULL" in df[0], df[0]

        d = _dokon(S)
        k1, k2 = _kassir(S, d, "FXA k1"), _kassir(S, d, "FXA k2")
        s1, s2 = _smena_ochiq(S, d, k1), _smena_ochiq(S, d, k2)
        cu = uuid.uuid4()
        s = S()
        try:
            s.add(_mv_qator(S, s1, cu))
            s.commit()
        finally:
            s.close()
        s = S()
        try:
            s.add(_mv_qator(S, s2, cu))
            try:
                s.commit()
                raise AssertionError("BOSHQA smenaga ayni client_uuid YOZILDI — indeks smena doirasida")
            except IntegrityError:
                s.rollback()
        finally:
            s.close()
        assert len(_mv_rows(S, cu)) == 1
    finally:
        eng.dispose()


def test_PG_FXA_KASSA_SMENA_ALMASHSA_takror_IKKINCHI_PULNI_YOZMAYDI(pg_target):
    """Marshrut xulqi: javob yo'qolgan, POS smenani yopib yangisini ochgan — TAKROR
    BIRINCHI amalning javobini oladi va yangi smenaga PUL YOZILMAYDI."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        k1, k2 = _kassir(S, d, "FXA a"), _kassir(S, d, "FXA b")
        s1 = _smena_ochiq(S, d, k1)
        cu = uuid.uuid4()
        r1 = _run(S, _cashop(d, summa=2000000, cu=cu))
        assert r1 == (200, {"ok": True, "shift_id": str(s1)}), r1
        _smena_yop(S, s1)
        s2 = _smena_ochiq(S, d, k2)
        r2 = _run(S, _cashop(d, summa=2000000, cu=cu))
        assert r2 == (200, {"ok": True, "shift_id": str(s1), "duplicate": True}), (r2, str(s2))
        assert _mv_rows(S, cu) == [(str(s1), "expense", 2000000.0)], _mv_rows(S, cu)
    finally:
        eng.dispose()


def test_PG_FXA_KASSA_PARALLEL_TAKROR_bitta_yozuv_va_DUPLICATE(pg_target):
    """POYGA: birinchi so'rov hali COMMIT qilmagan (SELECT-dedup uni KO'RMAYDI).

    Ikkinchisi yozmoqchi bo'ladi -> noyoblik indeksida KUTADI -> birinchisi commit
    qiladi -> ikkinchisi 23505 oladi. Kutilgan xulq: PUL BIR MARTA, javob esa
    BIRINCHI amalniki (`duplicate: true`) — «yozildi» degan YOLG'ON javob EMAS."""
    from tests.test_lot_tz_confirm_pg import _navbat
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        k1, k2 = _kassir(S, d, "FXA poyga a"), _kassir(S, d, "FXA poyga b")
        s1 = _smena_ochiq(S, d, k1, soat=3)      # ESKI smena — birinchi urinish shunga tushgan
        s2 = _smena_ochiq(S, d, k2, soat=0)      # YANGI smena — marshrut endi SHUNI tanlaydi
        cu = uuid.uuid4()

        def birinchi(s):
            s.add(_mv_qator(S, s1, cu))          # hali COMMIT QILINMAGAN birinchi urinish
            return "yozdi"

        r = _navbat(eng, S, birinchi, _cashop(d, summa=10, cu=cu))
        assert not isinstance(r.get("b"), Exception), r
        assert r["kutdi"] is True, f"ikkinchi so'rov indeks qulfini KUTMADI — poyga oynasi yo'q: {r}"
        # Javob — BIRINCHI amalniki (ESKI smena), yangi smenaga PUL YOZILMAYDI.
        assert r["b"] == {"ok": True, "shift_id": str(s1), "duplicate": True}, (r["b"], str(s2))
        assert _mv_rows(S, cu) == [(str(s1), "expense", 10.0)], _mv_rows(S, cu)
    finally:
        eng.dispose()


def test_PG_FXA_KASSA_smena_qulfi_FOR_NO_KEY_UPDATE(pg_target):
    """QULF INTIZOMI. Smena qatoriga FK'li INSERT (CashMovement) ota qatordan KEY
    SHARE oladi; `FOR UPDATE` u bilan TO'QNASHADI (kutish/deadlock), `FOR NO KEY
    UPDATE` esa yo'q. Marshrut AYNAN ikkinchisini ishlatishi shart."""
    from sqlalchemy import event, text
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement, Shift
    from tests.test_lot_tz_confirm_pg import _navbat
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        k1 = _kassir(S, d, "FXA qulf")
        s1 = _smena_ochiq(S, d, k1)
        sql: list = []

        def _sana(conn, cur, statement, *a, **k):
            sql.append(statement)
        event.listen(eng, "before_cursor_execute", _sana)
        try:
            assert _run(S, _cashop(d, summa=10, cu=uuid.uuid4()))[0] == 200
        finally:
            event.remove(eng, "before_cursor_execute", _sana)
        qulflar = [q for q in sql if "FOR NO KEY UPDATE" in q]
        assert qulflar and all("shifts" in q for q in qulflar), qulflar
        assert not [q for q in sql if "FOR UPDATE" in q and "FOR NO KEY UPDATE" not in q], \
            [q for q in sql if "FOR UPDATE" in q]

        # NEGA MUHIM: ochiq `FOR NO KEY UPDATE` FK'li INSERT'ni BLOKLAMAYDI.
        def birinchi(s):
            return str(s.query(Shift).filter(Shift.id == s1)
                       .with_for_update(key_share=True).first().id)

        def ikkinchi(s):
            s.execute(text("SET LOCAL lock_timeout = '3000ms'"))
            s.add(CashMovement(shift_id=s1, type=CashMovementType.payin, amount=Decimal("1"),
                               created_at=_hozir()))
            s.flush()
            return "insert OK"

        r = _navbat(eng, S, birinchi, ikkinchi)
        assert r.get("b") == "insert OK", r
    finally:
        eng.dispose()


def test_PG_FXA_MIJOZ_TOLOVI_takror_DUPLICATE_boshqa_hisob_bilan_RAD(pg_target):
    """Mijoz qarz to'lovi — ta'minotchi to'lovi bilan AYNI idempotentlik kontrakti:
    ayni kalit + ayni hisob -> `duplicate: true` (yozuv YO'Q); ayni kalit + BOSHQA
    custody hisobi -> 409 (jimgina boshqa hisobga post qilish AUDITNI buzardi)."""
    from app.api.v1.customers import pay_credit
    from app.models.customers import CustomerPayment
    from app.schemas.customer import CreditPayment
    eng, S = _baza(pg_target)
    try:
        d, acc = _sc(S, t0=True, shift=None)
        d = _customer(S, d)
        cu = uuid.uuid4()

        def _pay(account):
            def go(s):
                return pay_credit(d["cust"], CreditPayment(
                    amount=10, method="cash", client_uuid=cu,
                    cash_account_id=account["id"]), emp=_emp(s, d), db=s)
            return go

        r1 = _run(S, _pay(acc["till"]))
        assert r1[0] == 200 and "duplicate" not in r1[1], r1
        r2 = _run(S, _pay(acc["till"]))
        assert r2[0] == 200, r2
        assert r2[1] == {**r1[1], "paid": 10.0, "duplicate": True}, r2[1]
        r3 = _run(S, _pay(acc["safe"]))
        _rad(r3, INVALID, status=409)
        s = S()
        try:
            assert s.query(CustomerPayment).filter(CustomerPayment.client_uuid == cu).count() == 1
        finally:
            s.close()
    finally:
        eng.dispose()


def _pos_cash(d, shift_id, *, tur="payin", summa=70000, cu, reason=None, seyf=None):
    """POS yo'li (`POST /shifts/{id}/cash`) — smenani AYNAN ko'rsatadi."""
    from app.api.v1.shifts import CashMove, add_cash_movement

    def go(s):
        return add_cash_movement(shift_id, CashMove(
            type=tur, amount=summa, reason=reason, client_uuid=cu,
            destination_safe_id=(seyf["id"] if seyf else None)), emp=_emp(s, d), db=s)
    return go


def test_PG_FX2A_POS_ESKI_KALIT_yangi_smenaga_kirsa_409_PUL_YOQOLMAYDI(pg_target):
    """BLOCKER (PG): `ux_cashmov_client_uuid_all` jadval bo'ylab noyob — eski kalit
    yangi smenaga kirsa INSERT 23505 beradi. Ilgari bu shartsiz «duplicate: true»
    bo'lib ok qaytardi: kassirning HAQIQIY yangi naqd amali qator ham, ledger legi
    ham, jurnal yozuvi ham qoldirmay YO'QOLARDI. Endi — 409, ochiq-oydin."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        k1 = _kassir(S, d, "FX2A pos")
        s1 = _smena_ochiq(S, d, k1)
        cu = uuid.uuid4()
        # Kassir o'z smenasiga yozadi (emp = kassir bo'lishi shart: marshrut egasini tekshiradi).
        d1 = dict(d, emp=k1)
        r1 = _run(S, _pos_cash(d1, s1, cu=cu))
        assert r1 == (200, {"ok": True}), r1
        _smena_yop(S, s1)
        s2 = _smena_ochiq(S, d, k1)
        r2 = _run(S, _pos_cash(d1, s2, cu=cu))
        assert r2[0] == 409, r2
        _kalit_band(r2)
        # PUL: faqat birinchi smenada, ikkinchisida YOZILMAGAN.
        assert _mv_rows(S, cu) == [(str(s1), "payin", 70000.0)], _mv_rows(S, cu)
        # Yangi kalit bilan o'sha amal muammosiz yoziladi.
        r3 = _run(S, _pos_cash(d1, s2, cu=uuid.uuid4()))
        assert r3 == (200, {"ok": True}), r3
    finally:
        eng.dispose()


def test_PG_FX2A_KASSA_KALIT_BOSHQA_AMALGA_ishlatilsa_409(pg_target):
    """`/cash/ops`: ayni kalit BOSHQA summa bilan — takror EMAS, 409 va yozilmaydi."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        k1 = _kassir(S, d, "FX2A ops")
        s1 = _smena_ochiq(S, d, k1)
        cu = uuid.uuid4()
        assert _run(S, _cashop(d, summa=10, cu=cu)) == (200, {"ok": True, "shift_id": str(s1)})
        r = _run(S, _cashop(d, summa=99, cu=cu))
        assert r[0] == 409, r
        _kalit_band(r)
        assert _mv_rows(S, cu) == [(str(s1), "expense", 10.0)], _mv_rows(S, cu)
    finally:
        eng.dispose()


# ══ FX3-A. INKASSA TAKRORI — MANZIL SEYF MODDIY MAYDON ══════════════════════
#
# ⚠️  NEGA. `client_uuid` amalni IDENTIFIKATSIYA qiladi, uning MAZMUNINI o'zgartirish
#     huquqini bermaydi. Inkassada MAZMUN — «qancha» emas, «QAYSI SEYFGA» ham: javobi
#     yo'qolgan inkassa BOSHQA seyf bilan qayta yuborilsa va server «dublikat: ok»
#     desa, pul BIRINCHI seyfda qoladi, kassir esa IKKINCHISIGA yozilgan deb biladi —
#     ikki seyf sanog'i bir inkassaga ayro tushadi va buni ekranda HECH NARSA
#     ko'rsatmaydi (`GET /shifts/{id}/cash` manzilni umuman bermaydi).

def _inkassa(d, *, cu, seyf, summa=10, reason=None):
    """`POST /cash/ops` inkassa — manzil seyf AYNAN ko'rsatiladi."""
    from app.api.v1.cashops import CashOpIn, cash_op

    def go(s):
        return cash_op(CashOpIn(type="collection", amount=summa, reason=reason, client_uuid=cu,
                                destination_safe_id=seyf["id"]), emp=_emp(s, d), db=s)
    return go


def _ochiq_smena(S, d):
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = S()
    try:
        return s.query(Shift).filter(Shift.branch_id == d["bid"],
                                     Shift.status == ShiftStatus.open).one().id
    finally:
        s.close()


def _inkassa_oyoqlari(S, cu):
    """Shu kalitli inkassaning LEDGER oyoqlari: {leg_index: hisob_id}. Manzil — 1-oyoq (IN)."""
    from app.models.cash import CashLedgerEntry
    from app.models.shifts import CashMovement
    s = S()
    try:
        mv = s.query(CashMovement).filter(CashMovement.client_uuid == cu).one()
        rows = (s.query(CashLedgerEntry.leg_index, CashLedgerEntry.cash_account_id)
                .filter(CashLedgerEntry.source_type == "TRANSFER",
                        CashLedgerEntry.source_id == mv.id).all())
        return {int(i): str(a) for i, a in rows}
    finally:
        s.close()


def _qoldiq(S, d, acc):
    from app.services.cash import repositories as _repo
    s = S()
    try:
        return float(_repo.account_balance(s, d["cid"], acc["id"]))
    finally:
        s.close()


def test_PG_FX3A_INKASSA_TAKRORI_BOSHQA_SEYFGA_409_PUL_BIRINCHI_SEYFDA(pg_target):
    """AYNI kalit + AYNI summa/izoh + BOSHQA SEYF = TAKROR EMAS -> 409, yozuv YO'Q.

    Ilgari `cash_movement_matches` faqat (smena, tur, summa, izoh) ni solishtirardi:
    ikkinchi seyf bilan kelgan so'rov `{"ok": true, "duplicate": true}` olardi. Ikkala
    yozuvchi (`POST /cash/ops` va `POST /shifts/{id}/cash`) ham AYNI yordamchiga
    tayanadi, shu bois ikkalasi ham shu yerda o'lchanadi."""
    eng, S = _baza(pg_target)
    try:
        d, acc = _sc(S, t0=True, shift="till")
        seyf2 = _hisob(S, d, typ="SAFE")
        sid = _ochiq_smena(S, d)

        # ── 1) `POST /cash/ops` (mobil/ega yo'li) ──────────────────────────────
        cu = uuid.uuid4()
        r1 = _run(S, _inkassa(d, cu=cu, seyf=acc["safe"], summa=10, reason="Kechki"))
        assert r1[0] == 200 and "duplicate" not in r1[1], r1
        r2 = _run(S, _inkassa(d, cu=cu, seyf=seyf2, summa=10, reason="Kechki"))
        assert r2[0] == 409, r2
        _kalit_band(r2)
        # PUL: birinchi seyfda; ikkinchisiga bir tiyin ham tushmagan; qator BITTA.
        assert _inkassa_oyoqlari(S, cu)[1] == str(acc["safe"]["id"]), _inkassa_oyoqlari(S, cu)
        assert _qoldiq(S, d, seyf2) == 0.0
        assert len(_mv_rows(S, cu)) == 1, _mv_rows(S, cu)
        # AYNI seyf bilan HAQIQIY takror — avvalgidek `duplicate` (regressiya yo'q).
        r3 = _run(S, _inkassa(d, cu=cu, seyf=acc["safe"], summa=10, reason="Kechki"))
        assert r3[0] == 200 and r3[1].get("duplicate") is True, r3
        assert len(_mv_rows(S, cu)) == 1, _mv_rows(S, cu)

        # ── 2) `POST /shifts/{id}/cash` (POS kassir yo'li) ─────────────────────
        cu2 = uuid.uuid4()
        p1 = _run(S, _pos_cash(d, sid, tur="collection", summa=10, cu=cu2, seyf=acc["safe"]))
        assert p1 == (200, {"ok": True}), p1
        p2 = _run(S, _pos_cash(d, sid, tur="collection", summa=10, cu=cu2, seyf=seyf2))
        assert p2[0] == 409, p2
        _kalit_band(p2)
        assert _inkassa_oyoqlari(S, cu2)[1] == str(acc["safe"]["id"]), _inkassa_oyoqlari(S, cu2)
        assert _qoldiq(S, d, seyf2) == 0.0
        assert len(_mv_rows(S, cu2)) == 1, _mv_rows(S, cu2)
        p3 = _run(S, _pos_cash(d, sid, tur="collection", summa=10, cu=cu2, seyf=acc["safe"]))
        assert p3 == (200, {"ok": True, "duplicate": True}), p3
    finally:
        eng.dispose()


def test_PG_FX3A_INKASSA_POYGA_QULF_OSTIDA_va_INSERT_xatosida_HAM_409(pg_target):
    """Takror TEKSHIRUVI UCH JOYDA: qulfdan oldin, qulf ostida va INSERT 23505 da.

    Javob yo'qolganda so'rov PARALLEL kelishi mumkin — birinchisi hali COMMIT
    qilmagan bo'lsa qulfdan oldingi dedup uni KO'RMAYDI. Manzil tekshiruvi faqat
    birinchi joyda bo'lsa, boshqa seyfli so'rov qolgan ikki yo'ldan «dublikat»
    bo'lib o'tib ketardi."""
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement, Shift
    from app.services.cash import retrofit as _cr
    from tests.test_lot_tz_confirm_pg import _navbat

    def _ikkinchi(d, cu, seyf):
        """Yozuvchi + rad etishni TUPLE ga o'giradi (`_navbat` istisnoni saqlab qo'yadi)."""
        def go(s):
            try:
                return 200, _inkassa(d, cu=cu, seyf=seyf)(s)
            except HTTPException as e:
                return (e.status_code, str(e.detail), CG.code_of(e.detail),
                        (e.headers or {}).get("X-Error-Code"))
        return go

    def _birinchi(d, sid, cu, seyf, *, qulf: bool):
        """HAQIQIY birinchi urinish: CashMovement + TILL->SAFE transfer, COMMITSIZ."""
        def go(s):
            q = s.query(Shift).filter(Shift.id == sid)
            sh = (q.with_for_update(key_share=True) if qulf else q).first()
            mv = CashMovement(shift_id=sid, type=CashMovementType.collection,
                              amount=Decimal("10"), created_at=_hozir(), client_uuid=cu)
            s.add(mv)
            s.flush()
            _cr.on_cash_collection(s, _emp(s, d), from_till_id=sh.till_id,
                                   to_safe_id=seyf["id"], amount=10, movement_id=mv.id)
            return "yozdi"
        return go

    eng, S = _baza(pg_target)
    try:
        # ── A) QULF OSTIDAGI dedup: birinchi urinish SMENA qatorini ushlab turadi ──
        d, acc = _sc(S, t0=True, shift="till")
        seyf2 = _hisob(S, d, typ="SAFE")
        sid, cu = _ochiq_smena(S, d), uuid.uuid4()
        r = _navbat(eng, S, _birinchi(d, sid, cu, acc["safe"], qulf=True),
                    _ikkinchi(d, cu, seyf2))
        assert not isinstance(r.get("b"), Exception), r
        assert r["kutdi"] is True, f"ikkinchi so'rov qulfni KUTMADI — poyga oynasi yo'q: {r}"
        _kalit_band(r["b"])
        assert _inkassa_oyoqlari(S, cu)[1] == str(acc["safe"]["id"])
        assert _qoldiq(S, d, seyf2) == 0.0 and len(_mv_rows(S, cu)) == 1

        # ── B) INSERT 23505: birinchi urinish smenani QULFLAMAYDI, ikkinchisi
        #      ikkala dedupdan ham o'tib, noyoblik indeksida yiqiladi ──────────
        d2, acc2 = _sc(S, t0=True, shift="till")
        seyf2b = _hisob(S, d2, typ="SAFE")
        sid2, cu2 = _ochiq_smena(S, d2), uuid.uuid4()
        r2 = _navbat(eng, S, _birinchi(d2, sid2, cu2, acc2["safe"], qulf=False),
                     _ikkinchi(d2, cu2, seyf2b))
        assert not isinstance(r2.get("b"), Exception), r2
        assert r2["kutdi"] is True, f"ikkinchi so'rov indeks qulfini KUTMADI: {r2}"
        _kalit_band(r2["b"])
        assert _inkassa_oyoqlari(S, cu2)[1] == str(acc2["safe"]["id"])
        assert _qoldiq(S, d2, seyf2b) == 0.0 and len(_mv_rows(S, cu2)) == 1

        # ── C) AYNI POYGA, POS YO'LIDA (`POST /shifts/{id}/cash`) — bu marshrutda
        #      dedup BITTA (u allaqachon qulf ostida), ya'ni 23505 tarmog'i YAGONA
        #      ikkinchi himoya. Kassirlar kundalik inkassani AYNAN shu yerdan
        #      qiladi. ─────────────────────────────────────────────────────────
        d3, acc3 = _sc(S, t0=True, shift="till")
        seyf2c = _hisob(S, d3, typ="SAFE")
        sid3, cu3 = _ochiq_smena(S, d3), uuid.uuid4()

        def _pos_ikkinchi(s):
            try:
                return 200, _pos_cash(d3, sid3, tur="collection", summa=10, cu=cu3,
                                      seyf=seyf2c)(s)
            except HTTPException as e:
                return (e.status_code, str(e.detail), CG.code_of(e.detail),
                        (e.headers or {}).get("X-Error-Code"))

        r3 = _navbat(eng, S, _birinchi(d3, sid3, cu3, acc3["safe"], qulf=False), _pos_ikkinchi)
        assert not isinstance(r3.get("b"), Exception), r3
        assert r3["kutdi"] is True, f"POS so'rovi indeks qulfini KUTMADI: {r3}"
        _kalit_band(r3["b"])
        assert _inkassa_oyoqlari(S, cu3)[1] == str(acc3["safe"]["id"])
        assert _qoldiq(S, d3, seyf2c) == 0.0 and len(_mv_rows(S, cu3)) == 1
    finally:
        eng.dispose()


# ══ FX3-A. TAKROR KALIT TUZATISH TOOLI — HAQIQIY POSTGRES ═══════════════════

def test_PG_FX3A_CLI_takror_kalitlar_MAQSAD_DARVOZASI_va_SOYASIZ_tuzatish(pg_target):
    """`app.tools.cash_uuid_dupes` toolining ASL maqsadi Postgres (SQLite'da emas).

    Bu yerda o'lchanadi: (1) `--apply` maqsad klasterni AYNAN talab qiladi va
    tasdiqsiz HECH NARSA yozmaydi; (2) bo'shatilgan kalit NULL emas — native
    `uuid` ustuniga deterministik qiymat yoziladi (SQLite CHAR(32) bilan AYNI
    kod yo'li, boshqa saqlash formati); (3) tuzatishdan keyin noyob indeks
    QURILADI."""
    from datetime import timedelta

    from sqlalchemy import text
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement
    from app.tools import cash_uuid_dupes as CLI
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        k1 = _kassir(S, d, "FX3A cli")
        s1, s2 = _smena_ochiq(S, d, k1, soat=3), _smena_ochiq(S, d, _kassir(S, d, "FX3A cli2"))
        cu = uuid.uuid4()
        s = S()
        try:
            s.execute(text("DROP INDEX IF EXISTS ux_cashmov_client_uuid_all"))
            for sid, summa, soat in ((s1, "11000", 3), (s2, "22000", 0)):
                s.add(CashMovement(shift_id=sid, type=CashMovementType.payin,
                                   amount=Decimal(summa), client_uuid=cu,
                                   created_at=_hozir() - timedelta(hours=soat)))
            s.commit()
            sysid = str(s.execute(text(
                "SELECT system_identifier::text FROM pg_control_system()")).scalar())
        finally:
            s.close()

        # 1) Maqsad klastersiz APPLY — RAD (exit 1), baza TEGILMAYDI.
        assert CLI.main(["--json", "--apply", "--yes"], session_factory=S) == 1
        assert len(_mv_rows(S, cu)) == 2, "rad etilgan apply baribir yozdi"
        # 2) Boshqa klaster aytilsa — ham RAD.
        assert CLI.main(["--json", "--apply", "--yes",
                         "--expect-system-identifier", "1"], session_factory=S) == 1
        assert len(_mv_rows(S, cu)) == 2
        # 3) To'g'ri klaster + (efemer klaster ruxsat ro'yxatida emas) aniq tasdiq.
        assert CLI.main(["--json", "--apply", "--yes",
                         "--expect-system-identifier", sysid, "--allow-production",
                         "--confirm-production-system-identifier", sysid],
                        session_factory=S) == 0
        s = S()
        try:
            rows = sorted(s.query(CashMovement).filter(
                CashMovement.shift_id.in_([s1, s2])).all(), key=lambda m: m.created_at)
            assert [float(m.amount) for m in rows] == [11000.0, 22000.0], rows
            assert rows[0].client_uuid == cu, "ENG ESKI qator kalitni SAQLAMADI"
            assert rows[1].client_uuid is not None, "kalit NULL — qator «soya»ga aylandi"
            assert rows[1].client_uuid == CLI.released_key(rows[1].id), rows[1].client_uuid
            # To'siq yo'q: noyob indeks endi QURILADI.
            s.execute(text("CREATE UNIQUE INDEX ux_cashmov_client_uuid_all "
                           "ON cash_movements (client_uuid) WHERE client_uuid IS NOT NULL"))
            s.commit()
        finally:
            s.close()
    finally:
        eng.dispose()
