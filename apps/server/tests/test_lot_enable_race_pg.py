# -*- coding: utf-8 -*-
"""KUZATUVNI YOQISH × YOZUVCHI — HAQIQIY POSTGRES (Phase 5B, W).

POYGA (5ae04e2 da va production 99b1da7 da bor): yozuvchi mahsulot bayrog'ini
`Inventory` qulfidan OLDIN o'qiydi. `/lots/enable` qatorni ushlab bayroq va ochilish
partiyasini commit qilguncha yozuvchi qulfda KUTADI, keyin ESKI «kuzatuvsiz» qaror bilan
davom etadi: FEFO ham, yakuniy darvoza ham o'tkazib yuboriladi va
`Inventory != SUM(partiya)` JIMGINA commit bo'ladi.

⚠️  INTERLEAVING MAJBURIY, TASODIFIY EMAS (`test_lot_tz_confirm_pg._navbat`). Yoqish
    HAQIQIY `enable_tracking` orqali hamma narsani yozadi, lekin commit QILMAY turadi;
    yozuvchi shundan KEYIN boshlanadi — mahsulotni ESKI holda o'qiydi — va u yoqish
    tranzaksiyasini KUTAYOTGANI `pg_blocking_pids` da ko'rilgach yoqish commit qiladi.

Bu fayl isbotlaydi (har holatda IKKALA commit'dan keyin `stock_invariant.check` BUTUN):
  1. qator BOR, ayni filial — yozuvchi yoqish qulfida kutadi (`kutdi`):
       sotuv (onlayn)       -> FEFO bilan sotiladi, ulush yoziladi;
       offline /sync/push   -> ok, ulush yoziladi;
       hisobdan chiqarish   -> 400 (partiya ko'rsatilmagan), yozuvsiz;
       sanoq                -> 400, yozuvsiz;
       qaytarish (restock)  -> ichki qayta urinish, 409 (yoqishdan oldingi chek — B3);
       qaytarish (restock'siz) -> ichki qayta urinish, OK: partiyaga tegilmaydi (B3);
       xarid                -> 409 darvoza, yozuvsiz;
       ko'chirish           -> 409 darvoza, yozuvsiz (HIMOYA — regressiya isboti EMAS, pastga qarang);
  2. qator YO'Q filial — birinchi offline sotuv / kirim yoqishning INSERT'ini kutadi,
     `UNIQUE` da yiqilib o'z retry-o'rami bilan kuzatuvli yo'lga tushadi;
  3. BOSHQA filialdagi yozuvchi ham kutadi — bayroq butun kompaniyaga;
  4. ikki parallel yoqish — ikkinchisi 409, bayroq va audit QAYTA yozilmaydi.

MANFIY NAZORAT — AYNI sinovlar eski kodda (5ae04e2) QIZIL:
  1-band: `kutdi` ham True, lekin invariant BUZILADI (sotuv/offline: qoldiq 8 ≠ partiya 10;
          hisobdan: 8/10; sanoq: 7/10; qaytarish: 9/8; xarid: 15/10);
  ⚠️  ko'chirish holati ESKI kodda ham YASHIL (5ae04e2 da PG'da o'lchandi: `kutdi` True,
      409, invariant butun). Sabab — TASODIFIY serializator: ko'chirish darvozadan OLDIN
      `branches ... FOR UPDATE` oladi, yoqish esa ochilish partiyasini yozganda
      `stock_batches.branch_id` FK'si orqali o'sha filial qatoriga KEY SHARE qo'yadi.
      Ko'chirish aynan shu FILIAL so'rovida navbatga turadi (`pg_stat_activity` bilan
      tekshirildi) va darvozani yoqish commit'idan KEYIN o'qiydi. `cashops.py` dagi
      qulfdan keyingi qayta tekshiruv shu tasodifga tayanmaslik uchun; bu holat uni
      buzilishdan saqlaydi, lekin eski kodni QIZIL qilmaydi. Ko'chirishning qizil isboti —
      SQLite'dagi sun'iy oyna (`test_lot_enable_race.py`).
  2-band: yozuvchi umuman KUTMAYDI va qoldiqni partiyasiz yozadi (-2/0, +5/0);
  3-band: kutmaydi, ikkinchi filialda -2/0;
  4-band: ikkinchi yoqish O'TADI (audit 2 qator).
SQLite'dagi sun'iy oyna bilan AYNI mantiq: `test_lot_enable_race.py`.

⚠️  OSILMAYDI: har ulanishda `lock_timeout`/`statement_timeout`, kutish muddati cheklangan,
    iplar `join(timeout)` bilan (`test_lot_tz_confirm_pg._mk` / `_navbat`).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
Endpoint funksiyalari sessiya bilan TO'G'RIDAN chaqiriladi (TestClient ilova engine'iga bog'langan).
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_lot_tz_confirm_pg import _mk, _navbat

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
# B3 (Phase 5C) — server matni bilan AYNAN.
OLDIN_SOTILGAN = ("Bu mahsulot partiya kuzatuvi yoqilishidan OLDIN sotilgan — tovar qaysi "
                  "partiyadan chiqqani NOMA'LUM va tizim uni taxmin qilmaydi. Omborga "
                  "qaytarmasdan (restock'siz) qaytaring.")


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _baza(url):
    _initdb(url)
    return _mk(url)


def _dokon(S, qoldiq=(10,)):
    """Kompaniya + filial(lar) + har filialga ega + ta'minotchi + KUZATUVSIZ mahsulot.

    `qoldiq[i]` — i-filialdagi `Inventory.qty`; `None` — qator UMUMAN yo'q."""
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="W PG", code="w" + uuid.uuid4().hex[:8],
                     currency="UZS")
        s.add(co)
        s.flush()
        bids = []
        for i, _q in enumerate(qoldiq):
            b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F0{i + 1}", name=f"B{i + 1}",
                       timezone=TZ, is_active=True, created_at=NOW - timedelta(days=10 - i))
            s.add(b)
            s.flush()
            bids.append(b.id)
        ega = s.query(Role).filter(Role.code == "ega").one()
        emps = []
        for i, bid in enumerate(bids):
            e = Employee(id=uuid.uuid4(), company_id=co.id, full_name=f"W{i}",
                         phone="+9989" + str(uuid.uuid4().int)[:8], role_id=ega.id)
            s.add(e)
            s.flush()
            if len(bids) > 1:
                s.add(EmployeeBranch(employee_id=e.id, branch_id=bid))
            emps.append(e.id)
        unit = s.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=co.id, name="W " + uuid.uuid4().hex[:6],
                    article_code="W-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
        s.add(p)
        s.flush()
        for bid, q in zip(bids, qoldiq):
            if q is not None:
                s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=bid,
                                qty=Decimal(str(q)), min_qty=0, updated_at=NOW))
        sup = Supplier(id=uuid.uuid4(), company_id=co.id, name="W ta'minotchi")
        s.add(sup)
        s.commit()
        return {"cid": co.id, "bids": bids, "emps": emps, "pid": p.id, "sup": sup.id}
    finally:
        s.close()


def _holat(S, d):
    from app.models.catalog import Product
    from app.models.inventory import Inventory, LotShortfall, SaleItemLotAllocation, StockBatch
    from app.models.sync import AuditLog
    from app.services import stock_invariant as SI
    s = S()
    try:
        p = s.get(Product, d["pid"])
        inv = {str(b): Decimal(str(q)) for b, q in s.query(Inventory.branch_id, Inventory.qty)
               .filter(Inventory.product_id == d["pid"]).all()}
        lots = sorted((str(b), st, Decimal(str(r))) for b, st, r in s.query(
            StockBatch.branch_id, StockBatch.source_type, StockBatch.remaining_qty)
            .filter(StockBatch.product_id == d["pid"]).all())
        qarz = {str(b): Decimal(str(q)) for b, q in s.query(LotShortfall.branch_id, LotShortfall.qty)
                .filter(LotShortfall.product_id == d["pid"]).all()}
        rep = SI.check(s, d["cid"], [d["pid"]])
        return {
            "tracked": bool(p.track_lots),
            "inv": inv, "lots": lots, "qarz": qarz,
            "allocs": s.query(SaleItemLotAllocation).filter(
                SaleItemLotAllocation.product_id == d["pid"]).count(),
            "audit": s.query(AuditLog).filter(AuditLog.entity == "product_lot_tracking",
                                              AuditLog.entity_id == d["pid"]).count(),
            "buzilish": [str(m) for m in rep.mismatches],
        }
    finally:
        s.close()


def _emp(s, d, i=0):
    from app.models.auth import Employee
    return s.get(Employee, d["emps"][i])


def _yoq(d, *, filial=0, ushlab_tur=True):
    """HAQIQIY `enable_tracking`. `ushlab_tur` — commit o'rniga flush: tranzaksiyani
    `_navbat` commit qiladi (yozuvchi uni kutayotgani ko'rilgach)."""
    from app.api.v1.lots import EnableIn, enable_tracking

    def go(s):
        body = EnableIn(product_id=d["pid"], branch_id=d["bids"][filial],
                        reason="PG poyga: parallel yoqish", legacy_unit_cost=50)
        if not ushlab_tur:
            return enable_tracking(body, emp=_emp(s, d, filial), db=s)
        s.commit = s.flush
        try:
            return enable_tracking(body, emp=_emp(s, d, filial), db=s)
        finally:
            del s.commit
    return go


def _sotuv_body(d, qty=2, **kw):
    from app.schemas.sales import SaleCreate
    return SaleCreate(items=[{"product_id": str(d["pid"]), "qty": qty, "unit_price": 100}],
                      payment_method="card", client_uuid=uuid.uuid4(), **kw)


def _sotuv(d):
    from app.services.sales import create_sale
    return lambda s: create_sale(s, _emp(s, d), _sotuv_body(d)).id


def _offline(d, filial=0):
    from app.api.v1.sync import PushBody, push

    def go(s):
        rec = _sotuv_body(d).model_dump(mode="json")
        rec["sold_at"] = datetime.now(timezone.utc).isoformat()
        return push(PushBody(sales=[rec]), emp=_emp(s, d, filial), db=s)
    return go


def _hisobdan(d):
    from app.api.v1.inventory import WriteoffIn, writeoff
    return lambda s: writeoff(WriteoffIn(product_id=d["pid"], qty=2, reason="brak",
                                         client_uuid=uuid.uuid4()), emp=_emp(s, d), db=s)


def _sanoq(d):
    from app.api.v1.inventory import CountIn, stock_count
    return lambda s: stock_count(CountIn(items=[{"product_id": str(d["pid"]), "counted": 7}],
                                         client_uuid=uuid.uuid4()), emp=_emp(s, d), db=s)


def _qaytarish(d, sale_id, *, restock=True):
    from app.api.v1.sales import create_return
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    return lambda s: create_return(ReturnCreate(
        original_sale_id=sale_id, reason="customer", restock=restock, refund_method="card",
        client_uuid=uuid.uuid4(), items=[ReturnItemIn(product_id=d["pid"], qty=1)]),
        emp=_emp(s, d), db=s)


def _xarid(d):
    from app.api.v1.purchases import create_purchase
    from app.schemas.purchase import PurchaseCreate
    return lambda s: create_purchase(PurchaseCreate(
        supplier_id=d["sup"], status="debt", client_uuid=uuid.uuid4(),
        items=[{"product_id": d["pid"], "qty": 5, "unit_cost": 50}]), emp=_emp(s, d), db=s).id


def _kochirish(d):
    from app.api.v1.cashops import TransferIn, transfer
    return lambda s: transfer(TransferIn(
        from_branch_id=d["bids"][0], to_branch_id=d["bids"][1], client_uuid=uuid.uuid4(),
        items=[{"product_id": d["pid"], "qty": 3}]), emp=_emp(s, d), db=s)


def _kirim(d):
    from app.api.v1.receiving import CommitIn, commit
    return lambda s: commit(CommitIn(
        items=[{"product_id": str(d["pid"]), "qty": 5, "unit_cost": 50, "unit": "dona"}],
        supplier_id=d["sup"], payment="credit", client_uuid=uuid.uuid4(), source="manual"),
        emp=_emp(s, d), db=s)


def _natija(r):
    """("ok", qiymat) yoki (HTTP holati, matn); boshqa istisno — sinov QIZIL."""
    if isinstance(r, HTTPException):
        return r.status_code, r.detail
    assert not isinstance(r, Exception), f"kutilmagan istisno: {r!r}"
    return "ok", r


def _q(v):
    return Decimal(str(v))


# ══ 1. QATOR BOR, AYNI FILIAL — YOZUVCHI YOQISH QULFIDA KUTADI ═══════════════

@pytest.mark.parametrize("yozuvchi", ["sotuv", "offline", "hisobdan", "sanoq", "qaytarish",
                                      "qaytarish_restocksiz", "xarid", "kochirish"])
def test_PG_yoqish_x_yozuvchi_QULFDA_kutadi_INVARIANT_butun(pg_target, yozuvchi):
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(10, None) if yozuvchi == "kochirish" else (10,))
        b0 = str(d["bids"][0])
        if yozuvchi.startswith("qaytarish"):
            # Yoqishdan OLDINGI (kuzatuvsiz) chek — qaytariladigan tovar manbai.
            s = S()
            try:
                sale_id = _sotuv(d)(s)
            finally:
                s.close()
            fn = _qaytarish(d, sale_id, restock=(yozuvchi == "qaytarish"))
        else:
            fn = {"sotuv": _sotuv, "offline": _offline, "hisobdan": _hisobdan,
                  "sanoq": _sanoq, "xarid": _xarid, "kochirish": _kochirish}[yozuvchi](d)
        oldin = _holat(S, d)["inv"]

        r = _navbat(eng, S, _yoq(d), fn)

        h = _holat(S, d)
        assert h["buzilish"] == [], (
            f"{yozuvchi}: qoldiq partiyalardan AJRALDI (eskirgan bayroq): {h} natija={r}")
        assert r["kutdi"] is True, f"yozuvchi yoqish qulfini KUTMADI — oyna ochilmadi: {r}"
        assert _natija(r["a"])[0] == "ok" and r["a"]["ok"] is True, r
        assert h["tracked"] is True and h["audit"] == 1, h
        kod, qiymat = _natija(r["b"])
        if yozuvchi == "sotuv":
            assert kod == "ok", r
            assert h["allocs"] == 1 and h["inv"] == {b0: _q(8)}, h
            assert h["lots"] == [(b0, "legacy", _q(8))], h
        elif yozuvchi == "offline":
            assert kod == "ok" and qiymat["results"][0]["ok"] is True, r
            assert h["allocs"] == 1 and h["inv"] == {b0: _q(8)} and h["qarz"] == {}, h
        elif yozuvchi in ("hisobdan", "sanoq"):
            assert kod == 400, r
            assert h["inv"] == oldin and h["lots"] == [(b0, "legacy", _q(10))], h
        elif yozuvchi == "qaytarish":
            # B3 (Phase 5C): OMBORGA qaytarish RAD — matn endi sababni aytadi va
            # barqaror kod bilan keladi (ilgari umumiy «bog'lab bo'lmadi» edi).
            assert kod == 409 and qiymat == OLDIN_SOTILGAN, r
            assert (r["b"].headers or {}).get("X-Error-Code") == "LOT_RETURN_PRE_ACTIVATION", r
            assert h["inv"] == oldin == {b0: _q(8)} and h["lots"] == [(b0, "legacy", _q(8))], h
        elif yozuvchi == "qaytarish_restocksiz":
            # B3: restock'siz qaytarish O'TADI — partiya ham, qarz ham TEGILMAYDI
            # (qoldiq +1 keyin −1). Ichki qayta urinish yangi bayroq bilan qaror beradi.
            assert kod == "ok", r
            assert h["inv"] == oldin == {b0: _q(8)} and h["lots"] == [(b0, "legacy", _q(8))], h
            assert h["allocs"] == 0 and h["qarz"] == {}, h
        elif yozuvchi == "xarid":
            assert kod == 409 and "xarid (partiyasiz kirim)" in qiymat, r
            assert h["inv"] == oldin and h["lots"] == [(b0, "legacy", _q(10))], h
        else:
            # HIMOYA: eski kodda ham yashil — ko'chirish `branches FOR UPDATE` da kutadi
            # (fayl boshidagi izoh). Kutish qayerda bo'lmasin, natija AYNI bo'lishi shart.
            assert kod == 409 and "filiallararo ko'chirish" in qiymat, r
            assert h["inv"][b0] == _q(10) and h["inv"].get(str(d["bids"][1]), 0) == 0, h
    finally:
        eng.dispose()


# ══ 2. QATOR YO'Q FILIAL — BIRINCHI YOZUVCHI ═════════════════════════════════

@pytest.mark.parametrize("yozuvchi", ["offline", "kirim"])
def test_PG_qatorsiz_filialda_yoqish_x_BIRINCHI_yozuvchi(pg_target, yozuvchi):
    """Qator yo'q edi — eski yoqish hech narsani qulflamasdi va qoldiqni 0 deb yakunlardi.
    Endi yoqish qatorni yaratadi: yozuvchining INSERT'i uni KUTADI, `UNIQUE` da yiqiladi va
    retry-o'rami bilan yangi bayroqni ko'radi."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(None,))
        b0 = str(d["bids"][0])
        r = _navbat(eng, S, _yoq(d), {"offline": _offline, "kirim": _kirim}[yozuvchi](d))
        h = _holat(S, d)
        assert h["buzilish"] == [], f"{yozuvchi}: qatorsiz filialda qoldiq partiyasiz yozildi: {h} {r}"
        assert r["kutdi"] is True, f"yozuvchi yoqishning qatorini KUTMADI: {r}"
        assert _natija(r["a"])[0] == "ok", r
        kod, qiymat = _natija(r["b"])
        if yozuvchi == "offline":
            # Offline chek HECH QACHON rad etilmaydi — yetmagan qism ochiq QARZ bo'ladi.
            assert kod == "ok" and qiymat["results"][0]["ok"] is True, r
            assert h["inv"] == {b0: _q(-2)} and h["qarz"] == {b0: _q(2)}, h
        else:
            assert kod == 400 and "`lots` MAJBURIY" in qiymat, r
            assert h["inv"] == {b0: _q(0)} and h["lots"] == [], h
    finally:
        eng.dispose()


# ══ 3. BOSHQA FILIALDAGI YOZUVCHI ════════════════════════════════════════════

def test_PG_BOSHQA_filialdagi_yozuvchi_ham_yoqishni_KUTADI(pg_target):
    """Kuzatuv — mahsulot bayrog'i, butun kompaniyaga. Eski yoqish faqat tanlangan filial
    qatorini qulflardi: ikkinchi filialdagi offline sotuv kutmasdan kuzatuvsiz yozilardi."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(10, 0))
        b0, b1 = (str(b) for b in d["bids"])
        r = _navbat(eng, S, _yoq(d, filial=0), _offline(d, filial=1))
        h = _holat(S, d)
        assert h["buzilish"] == [], f"ikkinchi filialda qoldiq partiyasiz yozildi: {h} {r}"
        assert r["kutdi"] is True, f"boshqa filialdagi yozuvchi KUTMADI: {r}"
        assert _natija(r["a"])[0] == "ok", r
        kod, qiymat = _natija(r["b"])
        assert kod == "ok" and qiymat["results"][0]["ok"] is True, r
        assert h["inv"] == {b0: _q(10), b1: _q(-2)} and h["qarz"] == {b1: _q(2)}, h
        assert h["lots"] == [(b0, "legacy", _q(10))], h
    finally:
        eng.dispose()


# ══ 4. IKKI PARALLEL YOQISH ══════════════════════════════════════════════════

def test_PG_IKKI_parallel_yoqish_ikkinchisi_409_audit_BITTA(pg_target):
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(0,))
        r = _navbat(eng, S, _yoq(d), _yoq(d, ushlab_tur=False))
        h = _holat(S, d)
        assert h["audit"] == 1, f"ikkinchi yoqish eskirgan bayroq bilan QAYTA yozdi: {h} {r}"
        assert r["kutdi"] is True, r
        assert _natija(r["a"])[0] == "ok", r
        kod, qiymat = _natija(r["b"])
        assert kod == 409 and qiymat.endswith("allaqachon partiya bo'yicha kuzatiladi"), r
        assert h["tracked"] is True and h["buzilish"] == [], h
    finally:
        eng.dispose()
