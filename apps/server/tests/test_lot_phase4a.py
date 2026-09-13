# -*- coding: utf-8 -*-
"""PHASE 4A — QARZ YOPISH HODISASI, OG'ISH HISOBI VA QAYTARISH BILAN O'ZARO TA'SIR.

Bu fayl «tarixiy sotuv o'zgarmaydi + yopish alohida buxgalteriya hodisasi +
P&L og'ishni alohida ko'rsatadi» talabini BUTUN zanjir bo'ylab mahkamlaydi:

  1. QISMAN YOPISH   — 10@50: 5@55, 3@48, 2 ochiq (topshiriq misoli, aynan)
  2. IDEMPOTENTLIK   — ayni client_uuid og'ishni ikki marta yozmaydi
  3. YAXLITLASH      — kg miqdorlarda kumulyativ ulush chekdagi taxminni AYNAN yopadi
  4. QAYTARISH A–D   — yopilmagan / qisman / to'liq yopilgandan keyin / U qayta sotilgan
  5. BASIS           — nol so'mlik taxmin «aniq» deb tasniflanmaydi
  6. HISOBOTLAR      — pnl, summary, dashboard, overview, top/detail/categories MOS
  7. QO'RIQCHILAR    — FK ro'yxati, majburiy ustunlar, catalog_reset, FOR KEY SHARE

Postgres (konkurentlik va migratsiya) sinovlari: `tests/test_lot_phase4a_pg.py`.
"""
import ast
import inspect
import uuid
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.models.sales import SaleItem
from app.services import stock_invariant as SI
from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    _db,
    _enable,
    _inv,
    _lots,
    _product,
    _recv,
    _replay,
    _sell,
    ctx,
    sup,
)
from tests.test_lot_return import _resolve, _ret, _sale_id  # noqa: F401

C2 = D("0.01")


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _ok(cid, pid):
    with _db() as db:
        rep = SI.check(db, cid, [uuid.UUID(pid)])
        assert rep.ok, rep.mismatches


def _offline(client, H, pid, qty, price=100):
    cu = uuid.uuid4()
    r = _replay(client, H, pid, qty, price=price, cu=cu)
    assert r.status_code == 200 and r.json()["results"][0]["ok"] is True, r.text
    return _sale_id(cu)


def _sfs(pid):
    from app.models.inventory import LotShortfall
    with _db() as db:
        return (db.query(LotShortfall).filter(LotShortfall.product_id == uuid.UUID(pid))
                .order_by(LotShortfall.created_at, LotShortfall.id).all())


def _events(sf_id):
    from app.models.inventory import LotShortfallResolution as LSR
    with _db() as db:
        return (db.query(LSR).filter(LSR.shortfall_id == sf_id)
                .order_by(LSR.resolved_at, LSR.line_no, LSR.id).all())


def _rira(pid):
    from app.models.inventory import ReturnItemResolutionAllocation as RIRA
    with _db() as db:
        return db.query(RIRA).filter(RIRA.product_id == uuid.UUID(pid)).all()


def _risa(pid):
    from app.models.inventory import ReturnItemShortfallAllocation as RISA
    with _db() as db:
        return db.query(RISA).filter(RISA.product_id == uuid.UUID(pid)).all()


def _lot(pid, *, cost=None, source=None):
    rows = [b for b in _lots(pid)
            if (cost is None or D(str(b.unit_cost)) == D(str(cost)))
            and (source is None or b.source_type == source)]
    assert rows, (cost, source, [(b.source_type, b.unit_cost) for b in _lots(pid)])
    return rows[0]


def _rem(pid, batch_id):
    return [D(str(b.remaining_qty)) for b in _lots(pid) if b.id == batch_id][0]


def _pnl(client, H, **params):
    q = {"period": "month", **params}
    r = client.get("/api/v1/reports/pnl", headers=H, params=q)
    assert r.status_code == 200, r.text
    return r.json()


def _identity(p):
    """cogs == known + estimated + unknown − unlinked − prior + cogs_variance; profit = net − cogs."""
    cogs = (p["cogs_known"] + p["cogs_estimated"] + p["cogs_unknown"]
            - p["cogs_returns_unlinked"] - p["cogs_returns_prior_period"] + p["cogs_variance"])
    assert round(cogs, 2) == round(p["cogs"], 2), (cogs, p)
    assert round(p["net"] - p["cogs"], 2) == round(p["gross_profit"], 2), p


def _d(new, old, key):
    return round(new[key] - old[key], 2)


def _sanani_surish(sale_id, kun):
    from app.models.sales import Sale
    with _db() as db:
        s = db.get(Sale, uuid.UUID(sale_id))
        s.sold_at = s.sold_at - timedelta(days=kun)
        db.commit()


def _si(sale_id, pid):
    with _db() as db:
        return (db.query(SaleItem).filter(SaleItem.sale_id == uuid.UUID(sale_id),
                                          SaleItem.product_id == uuid.UUID(pid))
                .order_by(SaleItem.id).all())


def _snapshot(sale_id, pid):
    from app.models.inventory import SaleItemLotAllocation as SIA
    with _db() as db:
        out = []
        for si in (db.query(SaleItem).filter(SaleItem.sale_id == uuid.UUID(sale_id))
                   .order_by(SaleItem.id).all()):
            allocs = sorted((str(a.stock_batch_id), str(a.qty), str(a.unit_cost))
                            for a in db.query(SIA).filter(SIA.sale_item_id == si.id).all())
            out.append((str(si.id), str(si.qty), str(si.unit_cost), str(si.cost_total),
                        str(si.cost_unresolved), str(si.provisional_qty), str(si.line_total),
                        tuple(allocs)))
        return out


# ══ 1. QISMAN YOPISH — TOPSHIRIQ MISOLI AYNAN ══════════════════════════════

def test_QISMAN_yopish_10x50__5x55__3x48__2_OCHIQ(client, admin_headers, ctx, sup):
    """Qarz 10 dona @50 (taxmin 500). Yopish: 5@55, keyin 3@48. 2 dona ochiq.

    Kutilgan:
      e1: taxmin 250, haqiqiy 275, og'ish +25
      e2: taxmin 150, haqiqiy 144, og'ish −6
      ochiq 2, og'ish jami +19, taxminiy ekspozitsiya 2 × 50 = 100
      invariant saqlanadi, sotuv surati o'zgarmaydi, P&L og'ishni ALOHIDA ko'rsatadi
    """
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    p0 = _pnl(client, H)
    sid = _offline(client, H, pid, 10)
    surat = _snapshot(sid, pid)
    si = _si(sid, pid)[0]
    assert D(str(si.cost_unresolved)) == D("500.00") and D(str(si.provisional_qty)) == 10
    sf = _sfs(pid)[0]
    assert D(str(sf.qty)) == 10 and D(str(sf.unit_cost)) == 50

    assert _recv(client, H, sup, pid, 5, 55, D10).status_code == 200
    assert _recv(client, H, sup, pid, 3, 48, D20).status_code == 200
    x, y = _lot(pid, cost=55), _lot(pid, cost=48)

    r1 = _resolve(client, H, sf.id, batch=x.id, qty=5)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert (j1["open_qty"], j1["variance_now"], j1["kinds"]) == (5.0, 25.0, ["real"]), j1
    r2 = _resolve(client, H, sf.id, batch=y.id, qty=3)
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert (j2["open_qty"], j2["variance_now"], j2["closed"]) == (2.0, -6.0, False), j2
    assert j2["cogs_variance_recognised"] == 19.0 and j2["cogs_variance_net"] == 19.0

    ev = _events(sf.id)
    assert [(e.kind, D(str(e.qty)), D(str(e.provisional_cost)), D(str(e.actual_cost)),
             D(str(e.variance))) for e in ev] == [
        ("real", D("5"), D("250.00"), D("275.00"), D("25.00")),
        ("real", D("3"), D("150.00"), D("144.00"), D("-6.00"))], ev
    # Invariant va jismoniy partiyalar.
    assert _inv(pid, bid) == -2
    assert _rem(pid, x.id) == 0 and _rem(pid, y.id) == 0
    _ok(cid, pid)
    # Tarixiy sotuv BIT-DARAJASIDA o'zgarmagan.
    assert _snapshot(sid, pid) == surat

    lst = client.get("/api/v1/lots/shortfalls", headers=H).json()
    row = [r for r in lst["shortfalls"] if r["id"] == str(sf.id)][0]
    assert row["open_qty"] == 2.0 and row["resolved_real_qty"] == 8.0
    assert row["cogs_variance"] == 19.0 and row["provisional_exposure"] == 100.0
    assert row["legacy_shape"] is False

    p1 = _pnl(client, H)
    assert _d(p1, p0, "cogs_estimated") == 500.0, "sotuvdagi taxmin QAYTA YOZILDI"
    assert _d(p1, p0, "cogs_variance") == 19.0
    assert _d(p1, p0, "cogs") == 519.0
    assert p1["profit_includes_cost_adjustment"] is True
    _identity(p1)

    # Ortiqcha yopish RAD; qolgan 2 dona yopilganda taxmin AYNAN yopiladi.
    assert _recv(client, H, sup, pid, 5, 60, D20).status_code == 200
    z = _lot(pid, cost=60)
    r3 = _resolve(client, H, sf.id, batch=z.id, qty=3)
    assert r3.status_code == 400 and "ortiqcha" in r3.json()["detail"], r3.text
    r4 = _resolve(client, H, sf.id, batch=z.id, qty=2)
    assert r4.status_code == 200 and r4.json()["closed"] is True, r4.text
    assert sum(D(str(e.provisional_cost)) for e in _events(sf.id)) == D(str(si.cost_unresolved))
    _ok(cid, pid)


def test_BIR_sorovda_KOP_partiya_TARTIB_va_TAKROR_partiya_RAD(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    _offline(client, H, pid, 8)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 5, 55, D10)
    _recv(client, H, sup, pid, 3, 48, D20)
    x, y = _lot(pid, cost=55), _lot(pid, cost=48)
    bad = _resolve(client, H, sf.id, allocations=[(x.id, 1), (x.id, 1)])
    assert bad.status_code == 400, bad.text
    r = _resolve(client, H, sf.id, allocations=[(x.id, 5), (y.id, 3)])
    assert r.status_code == 200, r.text
    assert r.json()["kinds"] == ["real", "real"] and r.json()["variance_now"] == 19.0
    ev = _events(sf.id)
    assert [e.line_no for e in ev] == [0, 1]
    assert [D(str(e.provisional_cost)) for e in ev] == [D("250.00"), D("150.00")]
    assert len({e.request_id for e in ev}) == 1
    _ok(cid, pid)


# ══ 2. IDEMPOTENTLIK ═══════════════════════════════════════════════════════

def test_TAKROR_client_uuid_OGISHNI_ikki_marta_yozmaydi(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    _offline(client, H, pid, 4)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 4, 55, D10)
    x = _lot(pid, cost=55)
    cu = uuid.uuid4()
    r1 = _resolve(client, H, sf.id, batch=x.id, qty=2, cu=cu)
    assert r1.status_code == 200 and r1.json()["duplicate"] is False, r1.text
    p1 = _pnl(client, H)
    r2 = _resolve(client, H, sf.id, batch=x.id, qty=2, cu=cu)
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert j2["duplicate"] is True and j2["request_id"] == r1.json()["request_id"], j2
    assert j2["current"]["resolved_qty"] == 2.0
    assert len(_events(sf.id)) == 1, "takror ikkinchi hodisa yozdi"
    assert _rem(pid, x.id) == 2
    assert _pnl(client, H)["cogs_variance"] == p1["cogs_variance"], "og'ish IKKI marta yozildi"
    # Ayni client_uuid bilan BOSHQA mazmun — takror emas, mijoz xatosi.
    r3 = _resolve(client, H, sf.id, batch=x.id, qty=1, cu=cu)
    assert r3.status_code == 409, r3.text
    # client_uuid'siz so'rov qabul qilinmaydi.
    r4 = client.post(f"/api/v1/lots/shortfalls/{sf.id}/resolve", headers=H,
                     json={"stock_batch_id": str(x.id), "qty": 1, "reason": "uuidsiz"})
    assert r4.status_code == 422, r4.text
    _ok(cid, pid)


# ══ 3. KUMULYATIV YAXLITLASH (kg) ══════════════════════════════════════════

def _product_kg(client, H, buy):
    r = client.post("/api/v1/products/bulk", headers=H, json={"items": [
        {"name": f"KG {uuid.uuid4().hex[:8]}", "sell_price": 100, "buy_price": buy,
         "unit_code": "kg", "stock": 0}]})
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def test_KG_miqdorda_KUMULYATIV_ulush_TAXMINNI_aynan_yopadi(client, admin_headers, ctx, sup):
    """2.010 kg @47 — taxmin 94.47. Ikki yopish 1.005 dan: 47.24 + 47.23 = 94.47.

    Qatorma-qator yaxlitlash (round2(47 × 1.005) = 47.24 ikki marta) 94.48 berib,
    taxmin hech qachon AYNAN teskari qilinmasdi.
    """
    H = admin_headers
    cid, bid = ctx
    pid = _product_kg(client, H, 47)
    _enable(client, H, pid)
    sid = _offline(client, H, pid, 2.01)
    si = _si(sid, pid)[0]
    assert D(str(si.cost_unresolved)) == D("94.47"), si.cost_unresolved
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 3, 50, D10)
    x = _lot(pid, cost=50)
    bad = _resolve(client, H, sf.id, batch=x.id, qty=0.0001)
    assert bad.status_code == 400, bad.text
    assert _resolve(client, H, sf.id, batch=x.id, qty=1.005).status_code == 200
    assert _resolve(client, H, sf.id, batch=x.id, qty=1.005).status_code == 200
    ev = _events(sf.id)
    assert [D(str(e.provisional_cost)) for e in ev] == [D("47.24"), D("47.23")]
    assert [D(str(e.variance)) for e in ev] == [D("3.01"), D("3.02")]
    assert sum(D(str(e.provisional_cost)) for e in ev) == D(str(si.cost_unresolved))
    _ok(cid, pid)


# ══ 4. QAYTARISH BILAN O'ZARO TA'SIR ═══════════════════════════════════════

def test_QAYTARISH_A_YOPILMAGAN_qarz(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    sid = _offline(client, H, pid, 10)
    p0 = _pnl(client, H)
    r = _ret(client, H, sid, pid, 4)
    assert r.status_code == 200, r.text
    risa = _risa(pid)
    assert len(risa) == 1 and D(str(risa[0].qty)) == 4
    assert D(str(risa[0].provisional_cost_credit)) == D("200.00")
    assert D(str(_lot(pid, source="return_unattributed").remaining_qty)) == 4
    p1 = _pnl(client, H)
    assert _d(p1, p0, "cogs_estimated") == -200.0 and _d(p1, p0, "cogs_variance") == 0.0
    assert D(str(_sfs(pid)[0].resolved_qty)) == 0
    _identity(p1)
    _ok(cid, pid)
    # Qolgan 6 ham qaytadi, 7-chi — sotilganidan oshadi.
    assert _ret(client, H, sid, pid, 6).status_code == 200
    assert _ret(client, H, sid, pid, 1).status_code == 400
    assert sum(D(str(x.qty)) for x in _risa(pid)) == 10
    _ok(cid, pid)


def test_QAYTARISH_B_QISMAN_yopilgandan_keyin(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    sid = _offline(client, H, pid, 10)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 5, 55, D10)
    x = _lot(pid, cost=55)
    assert _resolve(client, H, sf.id, batch=x.id, qty=5).status_code == 200   # +25
    p0 = _pnl(client, H)

    # 4 dona qaytadi — AVVAL hodisa orqali (X ga), taxmin va og'ish PROPORSIONAL teskari.
    assert _ret(client, H, sid, pid, 4).status_code == 200
    rira = _rira(pid)
    assert len(rira) == 1 and D(str(rira[0].qty)) == 4
    assert D(str(rira[0].provisional_cost_credit)) == D("200.00")
    assert D(str(rira[0].variance_reversed)) == D("20.00")
    assert _rem(pid, x.id) == 4
    p1 = _pnl(client, H)
    assert _d(p1, p0, "cogs_estimated") == -200.0 and _d(p1, p0, "cogs_variance") == -20.0
    _identity(p1)

    # Qolgan 6: hodisadan 1 (50 / 5), dumdan 5 -> U.
    assert _ret(client, H, sid, pid, 6).status_code == 200
    assert sum(D(str(r.qty)) for r in _rira(pid)) == 5
    assert sum(D(str(r.variance_reversed)) for r in _rira(pid)) == D("25.00")
    assert sum(D(str(r.provisional_cost_credit)) for r in _rira(pid)) == D("250.00")
    assert [D(str(r.qty)) for r in _risa(pid)] == [D("5")]
    assert _rem(pid, x.id) == 5
    assert D(str(_lot(pid, source="return_unattributed").remaining_qty)) == 5
    p2 = _pnl(client, H)
    assert _d(p2, p0, "cogs_estimated") == -500.0, "taxmin ikki marta teskari qilindi"
    assert _d(p2, p0, "cogs_variance") == -25.0, "og'ish noto'g'ri teskari qilindi"
    _identity(p2)
    row = [r for r in client.get("/api/v1/lots/shortfalls", headers=H).json()["shortfalls"]
           if r["id"] == str(sf.id)][0]
    assert row["open_qty"] == 5.0 and row["provisional_exposure"] == 0.0, row
    _ok(cid, pid)


def test_QAYTARISH_C_TOLIQ_yopilgandan_keyin(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    p_start = _pnl(client, H)
    sid = _offline(client, H, pid, 10)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 5, 55, D10)
    _recv(client, H, sup, pid, 5, 48, D20)
    x, y = _lot(pid, cost=55), _lot(pid, cost=48)
    r = _resolve(client, H, sf.id, allocations=[(x.id, 5), (y.id, 5)])
    assert r.status_code == 200 and r.json()["closed"] is True, r.text    # +25, −10
    p0 = _pnl(client, H)
    assert _ret(client, H, sid, pid, 10).status_code == 200
    rira = sorted(_rira(pid), key=lambda z: str(z.stock_batch_id) != str(x.id))
    assert [(D(str(z.qty)), D(str(z.provisional_cost_credit)), D(str(z.variance_reversed)))
            for z in rira] == [(D("5"), D("250.00"), D("25.00")),
                               (D("5"), D("250.00"), D("-10.00"))], rira
    assert _rem(pid, x.id) == 5 and _rem(pid, y.id) == 5
    assert _risa(pid) == []
    p1 = _pnl(client, H)
    assert _d(p1, p0, "cogs_estimated") == -500.0 and _d(p1, p0, "cogs_variance") == -15.0
    # Umrbod: chek to'liq qaytdi -> COGS AYNAN 0.
    assert _d(p1, p_start, "cogs") == 0.0, (p_start["cogs"], p1["cogs"])
    _identity(p1)
    _ok(cid, pid)


def test_QAYTARISH_D_qaytgan_U_QAYTA_sotilsa_va_QAYTSA(client, admin_headers, ctx, sup):
    """v3 R1: qayta sotilgan U tovari, qarz yopilgach qaytsa — X ga, og'ish TESKARI.

    Usiz: tovar U ga tushib, qarz yopiq bo'lgani uchun netlab bo'lmasdi; X bir dona
    kam ko'rinib, qaytgan tovar uchun og'ish COGS'da abadiy qolardi.
    """
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    p_start = _pnl(client, H)
    s1 = _offline(client, H, pid, 5)                     # qarz 5 @50
    sf = _sfs(pid)[0]
    assert _ret(client, H, s1, pid, 2).status_code == 200   # U 2
    s2 = _offline(client, H, pid, 1)                     # U dan qayta sotuv
    assert D(str(_si(s2, pid)[0].provisional_qty)) == 1
    assert _recv(client, H, sup, pid, 10, 55, D10).status_code == 200
    u, x = _lot(pid, source="return_unattributed"), _lot(pid, cost=55)
    r = _resolve(client, H, sf.id, allocations=[(u.id, 1), (x.id, 4)])
    assert r.status_code == 200 and r.json()["kinds"] == ["netting", "real"], r.text
    assert r.json()["closed"] is True and r.json()["variance_now"] == 20.0

    # Qayta sotuv mijozi qaytaradi -> qarz hodisasi orqali X ga.
    rr = _ret(client, H, s2, pid, 1)
    assert rr.status_code == 200, rr.text
    s2_si = _si(s2, pid)[0]
    routed = [z for z in _rira(pid) if z.sale_item_id == s2_si.id]
    assert len(routed) == 1 and D(str(routed[0].qty)) == 1, _rira(pid)
    assert D(str(routed[0].provisional_cost_credit)) == D("50.00")
    assert D(str(routed[0].variance_reversed)) == D("5.00")
    assert _rem(pid, x.id) == 7 and _rem(pid, u.id) == 0
    _ok(cid, pid)

    # Asl mijoz qolgan 3 ni qaytaradi -> hodisaning qolgan sig'imidan.
    assert _ret(client, H, s1, pid, 3).status_code == 200
    assert _rem(pid, x.id) == 10 and _rem(pid, u.id) == 0
    assert sum(D(str(z.qty)) for z in _rira(pid)) == 4
    assert sum(D(str(z.variance_reversed)) for z in _rira(pid)) == D("20.00")
    p1 = _pnl(client, H)
    assert _d(p1, p_start, "cogs_estimated") == 0.0
    assert _d(p1, p_start, "cogs_variance") == 0.0
    assert _d(p1, p_start, "cogs") == 0.0, "hamma tovar qaytdi — COGS nol bo'lishi kerak"
    _identity(p1)
    _ok(cid, pid)
    # Qayta sotuvni ikkinchi marta qaytarib bo'lmaydi.
    assert _ret(client, H, s2, pid, 1).status_code == 400


def test_RESTOCKSIZ_qaytarish_OGISHNI_teskari_QILMAYDI(client, admin_headers, ctx, sup):
    """Yaroqsiz tovar qaytsa COGS tiklanmaydi — og'ish ham teskari qilinmaydi."""
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    sid = _offline(client, H, pid, 5)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 5, 55, D10)
    x = _lot(pid, cost=55)
    assert _resolve(client, H, sf.id, batch=x.id, qty=5).status_code == 200
    p0 = _pnl(client, H)
    assert _ret(client, H, sid, pid, 2, restock=False).status_code == 200
    assert _rira(pid) == [] and _risa(pid) == []
    assert _rem(pid, x.id) == 0
    p1 = _pnl(client, H)
    assert _d(p1, p0, "cogs_variance") == 0.0 and _d(p1, p0, "cogs") == 0.0
    _ok(cid, pid)


def test_BIR_qaytarishda_IKKI_qator_HODISANI_ikki_marta_TESKARI_qilmaydi(
        client, admin_headers, ctx, sup):
    """[5, 5] bitta so'rovda: birinchi qator hodisadan, ikkinchisi — DUMDAN (flush tufayli)."""
    from tests.test_lot_return import _shift
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    sid = _offline(client, H, pid, 10)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 5, 55, D10)
    x = _lot(pid, cost=55)
    assert _resolve(client, H, sf.id, batch=x.id, qty=5).status_code == 200
    p0 = _pnl(client, H)
    _shift(client, H)
    r = client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": sid, "reason": "customer", "restock": True,
        "refund_method": "cash", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": 5, "unit_price": 0},
                  {"product_id": pid, "qty": 5, "unit_price": 0}]})
    assert r.status_code == 200, r.text
    assert sum(D(str(z.qty)) for z in _rira(pid)) == 5, "hodisa IKKI marta teskari qilindi"
    assert sum(D(str(z.qty)) for z in _risa(pid)) == 5
    assert _rem(pid, x.id) == 5
    assert D(str(_lot(pid, source="return_unattributed").remaining_qty)) == 5
    p1 = _pnl(client, H)
    assert _d(p1, p0, "cogs_variance") == -25.0 and _d(p1, p0, "cogs_estimated") == -500.0
    _ok(cid, pid)


def test_IKKI_QATORLI_chekda_qarz_qatori_BOSHQA_qator_tovarini_OLMAYDI(
        client, admin_headers, ctx, sup):
    """v3 R2: (2) bosqich shu qatorning HALI TASHQARIDAGI tovari bilan chegaralanadi."""
    H = admin_headers
    cid, bid = ctx
    for _urinish in range(30):
        pid = _product(client, H, buy=50)
        _enable(client, H, pid)
        _recv(client, H, sup, pid, 5, 60, D10)
        cu = uuid.uuid4()
        r = client.post("/api/v1/sync/push", headers=H, json={"sales": [{
            "client_uuid": str(cu), "payment_method": "cash", "given_amount": 100000,
            "items": [{"product_id": pid, "qty": 5, "unit_price": 100},
                      {"product_id": pid, "qty": 5, "unit_price": 100}]}]})
        assert r.status_code == 200 and r.json()["results"][0]["ok"] is True, r.text
        sid = _sale_id(cu)
        lines = _si(sid, pid)                 # id tartibida — qaytarish tartibi
        if D(str(lines[0].cost_unresolved or 0)) > 0:
            break                             # qarz qatori BIRINCHI — sinov holati
    else:
        pytest.fail("30 urinishda qarz qatori birinchi bo'lmadi")
    sf = _sfs(pid)[0]
    y = _lot(pid, cost=60)
    assert _ret(client, H, sid, pid, 2).status_code == 200            # dum -> U 2
    _offline(client, H, pid, 2)                                        # U qayta sotildi
    _recv(client, H, sup, pid, 10, 55, D20)
    x = _lot(pid, cost=55)
    assert _resolve(client, H, sf.id, batch=x.id, qty=5).status_code == 200
    assert _ret(client, H, sid, pid, 8).status_code == 200
    # Qarz qatorining TASHQARIDAGI tovari 3 (5 − 2 dum). Qolgan 5 — Y qatori.
    assert sum(D(str(z.qty)) for z in _rira(pid)) == 3
    assert _rem(pid, x.id) == 8 and _rem(pid, y.id) == 5
    _ok(cid, pid)


def _push(client, H, lines, method="cash"):
    cu = uuid.uuid4()
    r = client.post("/api/v1/sync/push", headers=H, json={"sales": [{
        "client_uuid": str(cu), "payment_method": method, "given_amount": 100000,
        "items": [{"product_id": p, "qty": q, "unit_price": 100} for p, q in lines]}]})
    assert r.status_code == 200 and r.json()["results"][0]["ok"] is True, r.text
    return _sale_id(cu)


def test_QAYTA_sotuvning_IKKI_qatori_AYNI_hodisa_orqali_QAYTADI(client, admin_headers, ctx, sup):
    """Review HIGH: qayta sotuv chekida U tovari IKKI qatorda — ikkalasi ham ayni hodisaga.

    Ilgari `apply` bu holatni «imkonsiz» deb `ReturnAttributionError` otardi (HTTP 500),
    noyob kalit (qaytarish qatori, hodisa) esa uni IntegrityError -> 409 bilan rad etardi.
    """
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    p_start = _pnl(client, H)
    s1 = _offline(client, H, pid, 4)
    sf = _sfs(pid)[0]
    assert _ret(client, H, s1, pid, 4).status_code == 200                 # U 4
    s2 = _push(client, H, [(pid, 2), (pid, 2)])                          # U dan 2 qator
    assert [D(str(z.provisional_qty)) for z in _si(s2, pid)] == [D("2"), D("2")]
    assert _recv(client, H, sup, pid, 10, 55, D10).status_code == 200
    x = _lot(pid, cost=55)
    rr = _resolve(client, H, sf.id, batch=x.id, qty=4)
    assert rr.status_code == 200 and rr.json()["variance_now"] == 20.0, rr.text
    ret = _ret(client, H, s2, pid, 4)
    assert ret.status_code == 200, ret.text
    lines = {z.id for z in _si(s2, pid)}
    routed = [z for z in _rira(pid) if z.sale_item_id in lines]
    assert len(routed) == 2 and {z.sale_item_id for z in routed} == lines, routed
    assert sum(D(str(z.qty)) for z in routed) == 4
    assert sum(D(str(z.provisional_cost_credit)) for z in routed) == D("200.00")
    assert sum(D(str(z.variance_reversed)) for z in routed) == D("20.00")
    assert _rem(pid, x.id) == 10
    p1 = _pnl(client, H)
    assert _d(p1, p_start, "cogs") == 0.0 and _d(p1, p_start, "cogs_variance") == 0.0
    _identity(p1)
    _ok(cid, pid)


def test_AYNI_partiyadan_IKKI_qatorli_chekni_qaytarish_BLOKLANMAYDI(client, admin_headers, ctx, sup):
    """Review MEDIUM (Phase 3 dan): ikki qator AYNI partiyadan — bitta qaytarishda 409 edi.

    Eski noyob kalit (qaytarish qatori, partiya) ikki taqsimot qatorini rad etardi:
    IntegrityError -> 3 urinish -> DOIMIY «Kassa band». Kalit endi sotuv qatorini ham oladi.
    """
    from app.models.inventory import ReturnItemLotAllocation as RILA
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H)
    _enable(client, H, pid)
    _recv(client, H, sup, pid, 10, 50, D10)
    x = _lot(pid, cost=50)
    r = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 4, "unit_price": 100},
                  {"product_id": pid, "qty": 4, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100000, "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _rem(pid, x.id) == 2
    rr = _ret(client, H, r.json()["id"], pid, 8)
    assert rr.status_code == 200, rr.text
    with _db() as db:
        rows = db.query(RILA).filter(RILA.product_id == uuid.UUID(pid)).all()
    assert len(rows) == 2 and {z.stock_batch_id for z in rows} == {x.id}, rows
    assert len({z.sale_item_id for z in rows}) == 2
    assert _rem(pid, x.id) == 10
    _ok(cid, pid)


def test_BOSHQA_filialda_qarz_DUMINI_omborga_qaytarib_BOLMAYDI(client, admin_headers, ctx, sup):
    """Review HIGH: dum U partiyasi boshqa filialda tug'ilsa qarz ABADIY yopilmasdi."""
    from fastapi import HTTPException

    from app.api.v1.sales import _create_return_once
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.org import Branch
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    sid = _push(client, H, [(pid, 5)], method="card")
    sf = _sfs(pid)[0]
    with _db() as db:
        b2 = Branch(id=uuid.uuid4(), company_id=cid, code="F4B" + uuid.uuid4().hex[:5],
                    name="Phase4A boshqa filial", timezone="Asia/Tashkent", is_active=True)
        db.add(b2)
        db.flush()
        role = db.query(Role).filter(Role.code == "ega").first()
        e = Employee(id=uuid.uuid4(), company_id=cid, full_name="Boshqa filial egasi",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=role.id)
        db.add(e)
        db.flush()
        db.add(EmployeeBranch(employee_id=e.id, branch_id=b2.id))
        db.commit()
        e_id, b2_id = e.id, b2.id
    try:
        with _db() as db:
            emp = db.get(Employee, e_id)
            with pytest.raises(HTTPException) as he:
                _create_return_once(ReturnCreate(
                    original_sale_id=uuid.UUID(sid), refund_method="card", restock=True,
                    items=[ReturnItemIn(product_id=uuid.UUID(pid), qty=2)],
                    client_uuid=uuid.uuid4()), emp, db)
            assert he.value.status_code == 409, he.value.detail
            assert "Qarz dumi boshqa filialda" in str(he.value.detail)
            db.rollback()
        assert _risa(pid) == []
        assert [b for b in _lots(pid) if b.source_type == "return_unattributed"] == []
        assert D(str(_sfs(pid)[0].returned_qty or 0)) == 0 and _sfs(pid)[0].id == sf.id
        _ok(cid, pid)
    finally:
        with _db() as db:
            db.query(EmployeeBranch).filter(EmployeeBranch.employee_id == e_id).delete()
            db.query(Employee).filter(Employee.id == e_id).delete()
            db.query(Branch).filter(Branch.id == b2_id).delete()
            db.commit()


def test_TAXMINIY_partiya_BOSHQA_qarzniki_bolsa_yopib_bolmaydi(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    s1 = _offline(client, H, pid, 3)
    _offline(client, H, pid, 3)
    sf1, sf2 = _sfs(pid)
    assert _ret(client, H, s1, pid, 2).status_code == 200
    u1 = _lot(pid, source="return_unattributed")
    r = _resolve(client, H, sf2.id, batch=u1.id, qty=1)
    assert r.status_code == 400 and "BOSHQA" in r.json()["detail"], r.text
    r2 = _resolve(client, H, sf1.id, batch=u1.id, qty=2)
    assert r2.status_code == 200 and r2.json()["kinds"] == ["netting"], r2.text
    assert r2.json()["variance_now"] == 0.0
    _ok(cid, pid)


# ══ 5. BASIS — NOL SO'MLIK TAXMIN «ANIQ» EMAS ══════════════════════════════

def _set_buy(pid, price):
    from app.models.catalog import Product
    with _db() as db:
        db.get(Product, uuid.UUID(pid)).base_buy_price = price
        db.commit()


def test_NOL_tannarxli_taxmin_ANIQ_chelakka_TUSHMAYDI(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _set_buy(pid, 0)
    _enable(client, H, pid)
    p0 = _pnl(client, H)
    sid = _offline(client, H, pid, 3)
    si = _si(sid, pid)[0]
    assert D(str(si.cost_total)) == 0 and D(str(si.cost_unresolved)) == 0
    assert D(str(si.provisional_qty)) == 3
    p1 = _pnl(client, H)
    assert _d(p1, p0, "revenue_known_cost") == 0.0, "nol taxmin ANIQ tushum bo'lib ketdi"
    assert _d(p1, p0, "revenue_estimated_cost") == 300.0
    assert _d(p1, p0, "gross_profit_known") == 0.0
    assert p1["gross_profit_basis"] != "known"
    _identity(p1)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 3, 55, D10)
    x = _lot(pid, cost=55)
    assert _resolve(client, H, sf.id, batch=x.id, qty=3).status_code == 200
    p2 = _pnl(client, H)
    assert _d(p2, p1, "cogs_variance") == 165.0
    _identity(p2)
    _ok(cid, pid)


def test_NOL_taxmin_ARALASH_chekda_MIXED_va_yorliq_MOS(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    q = _product(client, H, buy=40)
    _enable(client, H, q)
    _recv(client, H, sup, q, 2, 40, D10)
    p = _product(client, H, buy=50)
    _set_buy(p, 0)
    _enable(client, H, p)
    p0 = _pnl(client, H)
    r = client.post("/api/v1/sync/push", headers=H, json={"sales": [{
        "client_uuid": str(uuid.uuid4()), "payment_method": "cash", "given_amount": 100000,
        "items": [{"product_id": q, "qty": 2, "unit_price": 100},
                  {"product_id": p, "qty": 3, "unit_price": 100}]}]})
    assert r.status_code == 200 and r.json()["results"][0]["ok"] is True, r.text
    p1 = _pnl(client, H)
    assert _d(p1, p0, "revenue_mixed_cost") == 500.0
    assert _d(p1, p0, "revenue_known_cost") == 0.0
    assert _d(p1, p0, "cogs_known") == 80.0 and _d(p1, p0, "cogs_estimated") == 0.0
    assert p1["gross_profit_basis"] in ("mixed", "partial_unknown"), p1["gross_profit_basis"]
    _identity(p1)


# ══ 6. HISOBOTLAR — OG'ISH HAMMA JOYDA BIR XIL ═════════════════════════════

def _pname(pid):
    from app.models.catalog import Product
    with _db() as db:
        return db.get(Product, uuid.UUID(pid)).name


def _snap_reports(client, H, name):
    g = lambda u, **k: client.get(u, headers=H, params=k).json()  # noqa: E731
    pnl_today = g("/api/v1/reports/pnl", period="today")
    summ = g("/api/v1/reports/summary")
    dash = g("/api/v1/reports/dashboard")
    ov = g("/api/v1/reports/overview", period="day")
    top = g("/api/v1/reports/top-products", period="month", limit=100)
    det = g("/api/v1/reports/detail", period="month")
    cats = g("/api/v1/reports/categories", period="month")
    return {
        "pnl_profit": pnl_today["gross_profit"], "pnl_var": pnl_today["cogs_variance"],
        "sum_profit": summ["today_profit"], "sum_var": summ["cogs_variance"],
        "dash_profit": dash["today_profit"], "dash_var": dash["cogs_variance"],
        "ov_profit": ov["kpi"]["profit"], "ov_var": ov["kpi"]["cogs_variance"],
        "ov_series_cost": round(sum(b["cost"] for b in ov["series"]), 2),
        "top": {x["name"]: x["profit"] for x in top}.get(name),
        "abc": {x["name"]: x["profit"] for x in det["abc"]}.get(name),
        "unranked": det["cogs_variance_unranked"],
        "cats": round(sum(c["profit"] for c in cats), 2),
    }


def test_OGISH_BARCHA_hisobotlarda_BIR_XIL(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    _offline(client, H, pid, 4)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 4, 55, D10)
    x = _lot(pid, cost=55)
    name = _pname(pid)
    a = _snap_reports(client, H, name)
    assert _resolve(client, H, sf.id, batch=x.id, qty=4).status_code == 200   # +20
    b = _snap_reports(client, H, name)
    for k in ("pnl_profit", "sum_profit", "dash_profit", "ov_profit", "top", "abc", "cats"):
        assert round(b[k] - a[k], 2) == -20.0, (k, a[k], b[k])
    for k in ("pnl_var", "sum_var", "dash_var", "ov_var", "ov_series_cost"):
        assert round(b[k] - a[k], 2) == 20.0, (k, a[k], b[k])
    assert b["unranked"] == a["unranked"], "sotilgan mahsulot og'ishi 'unranked' ga tushdi"


def test_FAQAT_OGISHLI_mahsulot_REYTINGGA_kirmaydi_lekin_YOQOLMAYDI(
        client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    sid = _offline(client, H, pid, 2)
    _sanani_surish(sid, 45)                          # sotuv oldingi davrda
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 2, 55, D10)
    x = _lot(pid, cost=55)
    name = _pname(pid)
    a = _snap_reports(client, H, name)
    p0 = _pnl(client, H)
    assert _resolve(client, H, sf.id, batch=x.id, qty=2).status_code == 200   # +10 shu oyda
    b = _snap_reports(client, H, name)
    assert b["top"] is None and b["abc"] is None, "sotilmagan mahsulot reytingga kirdi"
    assert round(b["unranked"] - a["unranked"], 2) == 10.0
    assert round(b["cats"] - a["cats"], 2) == -10.0
    assert _d(_pnl(client, H), p0, "cogs_variance") == 10.0


def test_OGISH_YOPILGAN_davrda_tan_olinadi_SOTUV_davri_QAYTA_yozilmaydi(
        client, admin_headers, ctx, sup):
    from app.models.sales import Sale
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    sid = _offline(client, H, pid, 5)
    _sanani_surish(sid, 45)
    with _db() as db:
        sold = db.get(Sale, uuid.UUID(sid)).sold_at
    rng = {"from_date": (sold - timedelta(days=1)).date().isoformat(),
           "to_date": (sold + timedelta(days=1)).date().isoformat()}
    eski0 = _pnl(client, H, **rng)
    joriy0 = _pnl(client, H)
    sf = _sfs(pid)[0]
    _recv(client, H, sup, pid, 5, 55, D10)
    x = _lot(pid, cost=55)
    assert _resolve(client, H, sf.id, batch=x.id, qty=5).status_code == 200
    assert _pnl(client, H, **rng) == eski0, "sotuv davri JIMGINA qayta yozildi"
    joriy1 = _pnl(client, H)
    assert _d(joriy1, joriy0, "cogs_variance") == 25.0
    _identity(joriy1)


# ══ 7. FILIAL IZOLYATSIYASI ════════════════════════════════════════════════

def test_BOSHQA_filial_qarzi_KORINMAYDI_va_YOPILMAYDI(client, admin_headers, ctx, sup):
    from app.api.v1.lots import list_shortfalls
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.org import Branch
    from app.services import lot_resolution as LRes
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H, buy=50)
    _enable(client, H, pid)
    _offline(client, H, pid, 3)
    sf = _sfs(pid)[0]
    with _db() as db:
        b2 = Branch(id=uuid.uuid4(), company_id=cid, code="F4A" + uuid.uuid4().hex[:5],
                    name="Phase4A izolyatsiya", timezone="Asia/Tashkent", is_active=True)
        db.add(b2)
        db.flush()
        role = db.query(Role).filter(Role.code == "administrator").first()
        e = Employee(id=uuid.uuid4(), company_id=cid, full_name="Filial xodimi",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=role.id)
        db.add(e)
        db.flush()
        db.add(EmployeeBranch(employee_id=e.id, branch_id=b2.id))
        db.commit()
        e_id, b2_id = e.id, b2.id
    try:
        with _db() as db:
            emp = db.get(Employee, e_id)
            with pytest.raises(LRes.ResolutionError) as ei:
                LRes.resolve(db, emp, sf.id, [(uuid.uuid4(), 1)], reason="izolyatsiya",
                             client_uuid=uuid.uuid4())
            assert ei.value.status == 404
            db.rollback()
            out = list_shortfalls(branch_id=None, include_resolved=True, emp=emp, db=db)
            assert str(sf.id) not in {r["id"] for r in out["shortfalls"]}
    finally:
        with _db() as db:
            db.query(EmployeeBranch).filter(EmployeeBranch.employee_id == e_id).delete()
            db.query(Employee).filter(Employee.id == e_id).delete()
            db.query(Branch).filter(Branch.id == b2_id).delete()
            db.commit()


# ══ 8. QO'RIQCHILAR ════════════════════════════════════════════════════════

NEW_TABLES = ("lot_shortfall_resolution_requests", "lot_shortfall_resolutions",
              "return_item_shortfall_allocations", "return_item_resolution_allocations")


def test_FK_royxati_MODEL_bilan_IKKI_tomonlama_MOS():
    import app.models  # noqa: F401
    from app.core import required_schema as rs
    from app.db.base import Base
    lot_tables = {"stock_batches", "sale_item_lot_allocations", "lot_shortfalls",
                  "return_item_lot_allocations", "stock_movement_lot_allocations", *NEW_TABLES}
    assert set(rs.FK_GUARDED_TABLES) == lot_tables
    want = set()
    for t in lot_tables:
        for fk in Base.metadata.tables[t].foreign_keys:
            on = "c" if (fk.ondelete or "").upper() == "CASCADE" else "a"
            want.add((t, (fk.parent.name,), fk.column.table.name, (fk.column.name,), on))
    have = {(f.child, f.cols, f.parent, f.refcols, f.on_delete) for f in rs.REQUIRED_FOREIGN_KEYS}
    assert want - have == set(), f"modelda bor, majburiy ro'yxatda YO'Q: {want - have}"
    assert have - want == set(), f"ro'yxatda bor, modelda YO'Q: {have - want}"


def test_yangi_USTUNLAR_majburiy_va_MIGRATSIYADA():
    import app.models  # noqa: F401
    from app.core import required_schema as rs
    from app.db.base import Base
    from app.initdb import _ADDED_COLUMNS
    added = {(t, c) for t, c, _ in _ADDED_COLUMNS}
    for t in NEW_TABLES:
        for col in Base.metadata.tables[t].columns:
            if col.name == "id":
                continue
            assert (t, col.name) in rs.REQUIRED_COLUMNS, (t, col.name)
            assert (t, col.name) in added, (t, col.name)
    assert ("sale_items", "provisional_qty") in rs.REQUIRED_COLUMNS
    assert ("sale_items", "provisional_qty") in added


def test_CHECK_tariflari_MODEL_bilan_AYNAN_MOS():
    import app.models  # noqa: F401
    from sqlalchemy import CheckConstraint

    from app.core import required_schema as rs
    from app.db.base import Base
    model = {}
    for t in Base.metadata.tables.values():
        for c in t.constraints:
            if isinstance(c, CheckConstraint) and c.name in rs.CHECK_DEFINITIONS:
                model[c.name] = (t.name, " ".join(str(c.sqltext).split()))
    for name, table in rs.REQUIRED_PG_CONSTRAINTS:
        if name == "ck_track_expiry_implies_lots":
            continue            # tarixan faqat migratsiyada (modelda yo'q)
        assert name in model, name
        assert model[name][0] == table
        assert model[name][1] == " ".join(rs.CHECK_DEFINITIONS[name].split()), (name, model[name])


def test_FOR_KEY_SHARE_haqiqatan_KEY_SHARE_bo_lib_render_qilinadi():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.models.catalog import Product
    from app.services import lot_resolution as LRes
    st = select(Product.id).where(Product.id == uuid.uuid4()).with_for_update(
        read=True, key_share=True)
    sql = str(st.compile(dialect=postgresql.dialect()))
    assert "FOR KEY SHARE" in sql, sql
    src = inspect.getsource(LRes._key_share)
    assert "read=True" in src and "key_share=True" in src, "FOR NO KEY UPDATE ga aylanib qoldi"


def test_catalog_reset_REJASI_yangi_jadvallarni_QAMRAYDI():
    import app.models  # noqa: F401
    from app.db.base import Base
    from app.services import catalog_reset as CR
    refs = {t.name for t in Base.metadata.tables.values()
            if any(fk.column.table.name == "products" for fk in t.foreign_keys)}
    assert refs <= CR.KNOWN_PRODUCT_REFERRERS, refs - CR.KNOWN_PRODUCT_REFERRERS
    names = lambda plan: [n for n, _ in plan]  # noqa: E731
    order = names(CR.DELETE_PLAN)
    for t in NEW_TABLES:
        assert t in names(CR.BLOCKERS) and t in names(CR.COUNT_PLAN)
        assert t in names(CR.DIGEST_PLAN) and t in order
    pos = order.index
    assert pos("return_item_resolution_allocations") < pos("lot_shortfall_resolutions")
    assert pos("lot_shortfall_resolutions") < pos("lot_shortfall_resolution_requests")
    for child in NEW_TABLES:
        assert pos(child) < pos("lot_shortfalls") and pos(child) < pos("stock_batches")


def test_variance_reversed_FAQAT_restock_filtri_ostida_O_QILADI():
    """Og'ish teskarisi faqat omborga qaytgan tovar uchun — `_ret_cogs` bilan ayni qoida."""
    import app.api.v1.reports as R
    tree = ast.parse(Path(R.__file__).read_text(encoding="utf-8"))
    hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            src = ast.unparse(node.iter)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.Return)):
            src = ast.unparse(node)
        elif isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            src = ast.unparse(node)
        else:
            continue
        if ".variance_reversed" in src:
            hits += 1
            assert "Return.restock" in src, src[:300]
    assert hits >= 3, "qo'riqchi hech narsani tekshirmadi"


def test_health_ready_LOT_SCHEMA_kaliti_bor(client):
    body = client.get("/api/v1/health/ready").json()
    assert body["checks"]["lot_schema_integrity"] is True, body
