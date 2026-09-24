# -*- coding: utf-8 -*-
"""XATO GIGIYENASI — MIJOZ O'QIY OLADIGAN JAVOBDA ICHKI ID, SQL VA STEK BO'LMASIN (Phase 5G.1, B3).

QOIDA (bitta, hamma marshrut uchun AYNI): rad etish tanasida
  · mijoz SHU so'rovda YUBORMAGAN UUID bo'lmasin (yo'l, tana, query'dagi id'lar — ruxsat;
    bazadan o'qilgan `shift.till_id`, `acc.branch_id`, saqlangan `cash_account_id` — YO'Q);
  · `Traceback` / `psycopg` / `sqlalchemy` / `SELECT ` / `relation "` / `File "` kabi ichki
    lug'at bo'lmasin (sxema nomi `cash` va rejim doimiysi `LEGACY_ONLY` ham);
  · barqaror kod bor bo'lsa u `X-Error-Code` sarlavhasida ham yursin.

⚠️  RUXSAT RO'YXATI BO'SH — bu paketning maqsadi shu. Qoida MATNNI emas, XULQNI o'lchaydi:
    server matni o'zgarsa sinov yashil qoladi, yangi xabar bazadan id olib chiqsa QIZARADI.

IKKI QATLAM:
  SQLite (TestClient, HAQIQIY HTTP) — mobil ilova urishi mumkin bo'lgan har rad etish:
    /auth/context, /products/scan, kirim, sanoq, hisobdan chiqarish, ko'chirish, tuzatish,
    /cash/ops, /shifts/{id}/cash, mijoz/ta'minotchi to'lovi. Kassa gardining CashAccount
    jadvaliga tegmaydigan rad etishlari (C10/C15/C16/C17) ham shu yerda.
  PostgreSQL (`pg_target`) — `cash.cash_accounts` ga qaraydigan gard rad etishlari
    (C3/C8/C13/C14) va ledger yozib bo'lmasligi (C18 + 503). Har rad etishda kuzatuv
    jurnali (`savdoos.cash`) xabardan chiqarilgan id'ni STRUKTURALI maydonda saqlagani
    ham tekshiriladi — aks holda «tuzatish» diagnostikani o'chirgan bo'lardi.

MANFIY NAZORAT: qoidaning o'zi soxta javobda QIZIL bo'lishi isbotlanadi (`test_QOIDA_...`).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core import error_codes as EC
from app.services.cash import cutover_guard as CG
from tests.test_cash_custody_correction import (_emp as _pg_emp, _hisob, _kamaytir, _qabul,
                                                _smena as _pg_smena, _t0)
from tests.test_check_defs_pg import pg_target  # noqa: F401  (fixture: har test — toza PG)
from tests.test_mobile_parity import (_commit, _count, _db, _lot_line, _product, _shop,
                                      _smena, _smena_yop, _staff, _token, _writeoff)
from tests.test_receiving_correction import (  # noqa: F401  (fixtures: sup, ctx)
    _batch_id, _correct, _doc, _rev, ctx, sup)

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Ichki lug'at — operator ko'radigan matnda HECH QACHON.
FORBIDDEN = ("Traceback", "psycopg", "sqlalchemy", "SELECT ", "INSERT ", 'relation "', 'File "',
             "stock_invariant", "LEGACY_ONLY", "`cash`")
HDR = EC.HEADER
NOW = datetime.now(timezone.utc)


# ══ QOIDA ═══════════════════════════════════════════════════════════════════

def _ids(*objs) -> set[str]:
    """Berilgan matn/obyektlardagi BARCHA UUID'lar (kichik harf)."""
    out: set[str] = set()
    for o in objs:
        if o is None:
            continue
        s = o if isinstance(o, str) else json.dumps(o, default=str)
        out |= {m.lower() for m in UUID_RE.findall(s)}
    return out


def hygienic(status, text: str, headers, *, sent: set, code: str | None = None,
             statuses=None) -> None:
    """QOIDA: javob tanasida mijoz yubormagan id yo'q; ichki lug'at yo'q; kod sarlavhada."""
    leak = _ids(text) - {s.lower() for s in sent}
    assert not leak, f"javobda mijoz YUBORMAGAN id: {sorted(leak)} | tana: {text!r}"
    for bad in FORBIDDEN:
        assert bad not in text, f"ichki lug'at {bad!r} javobda: {text!r}"
    if code is not None:
        got = (headers or {}).get(HDR)
        assert got == code, f"{HDR}={got!r}, kutilgan {code!r} | tana: {text!r}"
    if statuses is not None:
        assert status in statuses, (status, text)


def _r(resp, *, sent=(), code=None, statuses=None):
    """TestClient javobi — qoida + (ixtiyoriy) holat/kod; javobni qaytaradi."""
    sent_ids = _ids(*sent) if not isinstance(sent, set) else sent
    hygienic(resp.status_code, resp.text, resp.headers, sent=sent_ids, code=code,
             statuses=statuses)
    return resp


def _detail(resp) -> str:
    try:
        return str(resp.json().get("detail"))
    except Exception:            # noqa: BLE001
        return resp.text


def _t0_setting(cid, *, hours_ago=1):
    """T0 (cutover) o'tmishda — gard majburlash rejimi FAOL (SQLite'da ham o'qiladi)."""
    from app.models.settings import Setting
    with _db() as db:
        row = (db.query(Setting).filter(Setting.company_id == cid, Setting.key == "cash",
                                        Setting.branch_id.is_(None)).first())
        val = {"cutover_at": (NOW - timedelta(hours=hours_ago)).isoformat()}
        if row is None:
            db.add(Setting(company_id=cid, branch_id=None, key="cash", value=val))
        else:
            row.value = {**(row.value or {}), **val}
        db.commit()


def _customer(d, *, debt="100000"):
    from app.models.customers import Customer
    with _db() as db:
        c = Customer(id=uuid.uuid4(), company_id=d["cid"], code="M-" + uuid.uuid4().hex[:6],
                     full_name="Gigiyena qarzdor", credit_balance=Decimal(debt))
        db.add(c)
        db.commit()
        return c.id


def _supplier_debt(d, *, debt="100000"):
    from app.models.purchasing import Supplier
    with _db() as db:
        db.get(Supplier, d["sup"]).balance = Decimal(debt)
        db.commit()


# ══ MANFIY NAZORAT — QOIDA BO'SH EMAS ═══════════════════════════════════════

def test_QOIDA_soxta_javobda_QIZIL_yuborilgan_idda_YASHIL():
    """UUID regex'idagi bitta xato butun faylni doimiy yashil qilardi — qoidani sinaymiz."""
    yot = str(uuid.uuid4())
    with pytest.raises(AssertionError, match="YUBORMAGAN id"):
        hygienic(400, f"KOD: hisob boshqa filialga tegishli ({yot} != x).", {}, sent=set())
    # Mijoz o'zi yuborgan id — ruxsat (masalan «Partiya topilmadi: <id>»).
    hygienic(400, f"Partiya topilmadi: {yot}", {}, sent={yot})
    # Katta/kichik harf farqi qoidani aldamaydi.
    hygienic(400, f"Partiya topilmadi: {yot.upper()}", {}, sent={yot})
    for bad in FORBIDDEN:
        with pytest.raises(AssertionError, match="ichki lug'at"):
            hygienic(500, f"xato: {bad} qator", {}, sent=set())
    with pytest.raises(AssertionError, match=HDR):
        hygienic(400, "KOD: matn", {}, sent=set(), code="KOD")
    hygienic(400, "KOD: matn", {HDR: "KOD"}, sent=set(), code="KOD")


# ══ SQLite — /auth/context ══════════════════════════════════════════════════

def test_AUTH_CONTEXT_har_rad_etish_toza(client):
    d = _shop()
    url = "/api/v1/auth/context"
    _r(client.get(url), statuses={401})
    _r(client.get(url, headers={"Authorization": "Bearer yaroqsiz.token.xx"}), statuses={401})
    yoq = uuid.uuid4()
    _r(client.get(url, headers=_token(yoq, "ega", d["cid"])), statuses={401})
    # Sessiya bekor qilingan (sv mos emas)
    from app.core.security import create_access_token
    tok = create_access_token(str(d["eid"]), {"role": "ega", "company_id": str(d["cid"]), "sv": 7})
    _r(client.get(url, headers={"Authorization": f"Bearer {tok}"}), statuses={401})
    # Do'kon to'xtatilgan -> 403
    from app.models.settings import Setting
    with _db() as db:
        db.add(Setting(company_id=d["cid"], branch_id=None, key="suspended", value={"on": True}))
        db.commit()
    try:
        _r(client.get(url, headers=d["H"]), statuses={403})
    finally:
        with _db() as db:
            db.query(Setting).filter(Setting.company_id == d["cid"],
                                     Setting.key == "suspended").delete()
            db.commit()


# ══ SQLite — /products/scan ═════════════════════════════════════════════════

def test_SCAN_filial_rad_etishlari_toza(client):
    d = _shop(2)
    h, _ = _staff(d, "omborchi", filiallar=[d["bids"][0]])
    begona = _shop()
    url = "/api/v1/products/scan"
    _r(client.get(url, params={"code": "123", "branch_id": str(d["bids"][1])}, headers=h),
       sent=(str(d["bids"][1]),), statuses={403})
    _r(client.get(url, params={"code": "123", "branch_id": str(begona["bids"][0])}, headers=h),
       sent=(str(begona["bids"][0]),), statuses={400})
    _r(client.get(url, params={"code": "123", "branch_id": str(uuid.uuid4())}, headers=d["H"]),
       statuses={400})


# ══ SQLite — kirim (/receiving/commit) ══════════════════════════════════════

def test_KIRIM_rad_etishlari_toza(client):
    d = _shop()
    t = _product(d, name="Kuz", tracked=True)
    u = _product(d, name="Odd")
    ex = _product(d, name="Mud", tracked=True, expiry=True)
    yoq_prod = uuid.uuid4()
    _r(_commit(client, d["H"], []), statuses={400})
    _r(_commit(client, d["H"], [_lot_line(u, 1, None)], supplier=uuid.uuid4()), statuses={404})
    body = [{"product_id": str(yoq_prod), "qty": 1, "unit_cost": 5, "unit": "dona"}]
    _r(_commit(client, d["H"], body), sent=(str(yoq_prod),), statuses={400})
    for item, code in ((_lot_line(t, 5, None), "LOT_LINES_REQUIRED"),
                       (_lot_line(u, 5, [{"qty": 5}]), "LOT_LINES_FORBIDDEN"),
                       (_lot_line(t, 5, [{"qty": 2}]), "LOT_QTY_SUM_MISMATCH"),
                       (_lot_line(t, 1.2345, [{"qty": 1.2345}]), "LOT_QTY_PRECISION"),
                       (_lot_line(ex, 1, [{"qty": 1, "expiry_date": "2099-01-01"}]),
                        "LOT_TZ_NOT_CONFIRMED")):
        _r(_commit(client, d["H"], [item]), sent=(item,), code=code, statuses={400, 409})


# ══ SQLite — sanoq / hisobdan chiqarish / ko'chirish ════════════════════════

def test_SANOQ_rad_etishlari_toza(client):
    d = _shop()
    t = _product(d, name="Kuz C", qty=8, tracked=True, lots=[3, 5])
    t2 = _product(d, name="Bosh C", qty=1, tracked=True, lots=[1])
    u = _product(d, name="Odd C", qty=2)
    a, _b = t["lots"]
    _r(_count(client, d, []), statuses={400})
    ikki = [{"product_id": str(u["id"]), "counted": 1}, {"product_id": str(u["id"]), "counted": 2}]
    _r(_count(client, d, ikki), sent=(ikki,), statuses={400})
    for items, code in (
            ([{"product_id": str(t["id"]), "counted": 8}], "LOT_LINES_REQUIRED"),
            ([{"product_id": str(u["id"]), "counted": 2,
               "lots": [{"stock_batch_id": str(a), "counted": 1}]}], "LOT_LINES_FORBIDDEN"),
            ([{"product_id": str(t["id"]), "counted": 10,
               "lots": [{"stock_batch_id": str(a), "counted": 3}]}], "LOT_COUNT_SUM_MISMATCH"),
            ([{"product_id": str(t["id"]), "counted": 8,
               "lots": [{"stock_batch_id": str(t2["lots"][0]), "counted": 1}]}],
             "LOT_SELECTION_INVALID")):
        _r(_count(client, d, items), sent=(items,), code=code, statuses={400})


def test_HISOBDAN_CHIQARISH_rad_etishlari_toza(client):
    d = _shop()
    t = _product(d, name="Kuz W", qty=10, tracked=True, lots=[5, 5])
    u = _product(d, name="Odd W", qty=10)
    a, _b = t["lots"]
    yoq = uuid.uuid4()
    kas, _ = _staff(d, "kassir")
    _r(client.post("/api/v1/inventory/writeoff", headers=kas,
                   json={"product_id": str(u["id"]), "qty": 1}),
       sent=(str(u["id"]),), code="PERMISSION_DENIED", statuses={403})
    _r(_writeoff(client, d, u, 99), sent=(str(u["id"]), str(d["bids"][0])), statuses={400})
    for p, qty, lots, code in ((t, 1, None, "LOT_LINES_REQUIRED"),
                               (u, 1, [(a, 1)], "LOT_LINES_FORBIDDEN"),
                               (t, 1, [(yoq, 1)], "LOT_SELECTION_INVALID"),
                               (t, 4, [(a, 3)], "LOT_QTY_SUM_MISMATCH"),
                               (t, 6, [(a, 6)], "LOT_INSUFFICIENT_REMAINING")):
        r = _writeoff(client, d, p, qty, lots)
        _r(r, sent=(str(p["id"]), str(d["bids"][0]), [str(b) for b, _q in (lots or [])]),
           code=code, statuses={400})


def test_KOCHIRISH_rad_etishlari_toza(client):
    d = _shop(2)
    t = _product(d, name="Kuz T", qty=5, tracked=True)
    u = _product(d, name="Odd T", qty=1)
    url = "/api/v1/inventory/transfer"
    src, dst = str(d["bids"][0]), str(d["bids"][1])
    yoq = str(uuid.uuid4())

    def go(body):
        return client.post(url, headers=d["H"], json=body)
    base = {"from_branch_id": src, "to_branch_id": dst, "client_uuid": str(uuid.uuid4())}
    _r(go({**base, "to_branch_id": src, "items": [{"product_id": str(u["id"]), "qty": 1}]}),
       sent=(base, str(u["id"])), statuses={400})
    _r(go({**base, "items": []}), sent=(base,), statuses={400})
    _r(go({**base, "to_branch_id": yoq, "items": [{"product_id": str(u["id"]), "qty": 1}]}),
       sent=(base, yoq, str(u["id"])), statuses={404})
    # Noma'lum mahsulot: bugun 3x qayta urinish tugab 409 «band» bilan chiqadi (cashops.py
    # ko'chirish o'rami — B3 doirasidan tashqari, hisobotda qayd etilgan); tana toza.
    _r(go({**base, "items": [{"product_id": yoq, "qty": 1}]}), sent=(base, yoq),
       statuses={400, 409})
    _r(go({**base, "items": [{"product_id": str(u["id"]), "qty": 50}]}),
       sent=(base, str(u["id"])), statuses={400})
    _r(go({**base, "items": [{"product_id": str(t["id"]), "qty": 1}]}),
       sent=(base, str(t["id"])), code="TRANSFER_TRACKED_UNSUPPORTED", statuses={409})


# ══ SQLite — tuzatish (/receiving/{id}/corrections) ═════════════════════════

def test_TUZATISH_rad_etishlari_toza_va_KODLI(client, admin_headers, ctx, sup):
    """Shakl xatolari ham barqaror kod bilan yuradi (5G.1): `LOT_SELECTION_INVALID`,
    `LOT_QTY_PRECISION` (`lot_correction` ilgari `e.code` ni tashlab yuborardi),
    zona 409 -> `LOT_TZ_NOT_CONFIRMED`."""
    from app.services import catalog_import_v2 as civ2
    from app.services import lot_policy as LP
    cid, _bid = ctx
    d = _doc(client, admin_headers, sup, qty=10, cost=700)
    yoq_rec = str(uuid.uuid4())
    _r(_correct(client, admin_headers, yoq_rec, [_rev(d["item"], _batch_id(d), 1)]),
       sent=(yoq_rec, d["item"], _batch_id(d)), statuses={404})
    yoq = str(uuid.uuid4())
    _r(_correct(client, admin_headers, d["rec"], [_rev(d["item"], yoq, 1)]),
       sent=(d["rec"], d["item"], yoq), code=EC.LOT_SELECTION_INVALID, statuses={400})
    aniqlik = [{"purchase_item_id": d["item"],
                "reverse": [{"stock_batch_id": _batch_id(d), "qty": 10}],
                "replace": [{"qty": 9.2345, "batch_number": "A-2", "unit_cost": 700}],
                "unit_cost": 700}]
    _r(_correct(client, admin_headers, d["rec"], aniqlik),
       sent=(d["rec"], aniqlik), code=EC.LOT_QTY_PRECISION, statuses={400})
    # Zona tasdig'i yo'qolgan -> 409, kod sarlavhada.
    future = (NOW + timedelta(days=120)).date()
    client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})
    d2 = _doc(client, admin_headers, sup, qty=10, cost=700, expiry=future, track_expiry=True)
    with _db() as db:
        civ2.set_catalog_settings(db, cid, **{LP.CONFIRM_FIELD: {}})
        db.commit()
    try:
        zona = [{"purchase_item_id": d2["item"],
                 "reverse": [{"stock_batch_id": _batch_id(d2), "qty": 10}],
                 "replace": [{"qty": 10, "expiry_date": future.isoformat(), "unit_cost": 700}],
                 "unit_cost": 700}]
        _r(_correct(client, admin_headers, d2["rec"], zona),
           sent=(d2["rec"], zona), code=EC.LOT_TZ_NOT_CONFIRMED, statuses={409})
    finally:
        client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})


# ══ SQLite — /cash/ops va /shifts/{id}/cash ═════════════════════════════════

def test_CASH_OPS_rad_etishlari_toza_va_KASSA_GARDI_SARLAVHALI(client):
    d = _shop()
    url = "/api/v1/cash/ops"
    _r(client.post(url, headers=d["H"], json={"type": "payin", "amount": 10}),
       code=EC.OPEN_SHIFT_REQUIRED, statuses={400})
    _, k1 = _staff(d, "kassir")
    s1 = _smena(d, k1, opening="1000")
    cu = str(uuid.uuid4())
    assert client.post(url, headers=d["H"],
                       json={"type": "payin", "amount": 10, "client_uuid": cu}).status_code == 200
    _r(client.post(url, headers=d["H"], json={"type": "expense", "amount": 20, "client_uuid": cu}),
       sent=(cu,), code=EC.IDEMPOTENCY_KEY_REUSED, statuses={409})
    _r(client.post(url, headers=d["H"], json={"type": "expense", "amount": 999999}),
       statuses={400})
    # T0 o'tdi, smena LEGACY (kassasiz): gard rad etadi — KOD SARLAVHADA ham yursin.
    _t0_setting(d["cid"])
    r = _r(client.post(url, headers=d["H"], json={"type": "payin", "amount": 10}),
           code=CG.ERR_LEGACY_SHIFT_NEEDS_TILL, statuses={400})
    assert _detail(r).startswith(CG.ERR_LEGACY_SHIFT_NEEDS_TILL + ":"), r.text
    _smena_yop(s1)


def test_SHIFT_CASH_rad_etishlari_toza_va_KASSA_GARDI_SARLAVHALI(client):
    d = _shop()
    h, k1 = _staff(d, "kassir")
    h2, k2 = _staff(d, "kassir")
    s1 = _smena(d, k1, opening="1000")
    s2 = _smena(d, k2, opening="1000")
    _r(client.post(f"/api/v1/shifts/{s2}/cash", headers=h, json={"type": "payin", "amount": 5}),
       sent=(str(s2),), statuses={404})
    _r(client.post(f"/api/v1/shifts/{s1}/cash", headers=h, json={"type": "expense", "amount": 99999}),
       sent=(str(s1),), statuses={400})
    cu = str(uuid.uuid4())
    assert client.post(f"/api/v1/shifts/{s1}/cash", headers=h,
                       json={"type": "payin", "amount": 5, "client_uuid": cu}).status_code == 200
    _r(client.post(f"/api/v1/shifts/{s1}/cash", headers=h,
                   json={"type": "payin", "amount": 6, "client_uuid": cu}),
       sent=(str(s1), cu), code=EC.IDEMPOTENCY_KEY_REUSED, statuses={409})
    _smena_yop(s2)
    _r(client.post(f"/api/v1/shifts/{s2}/cash", headers=h2, json={"type": "payin", "amount": 5}),
       sent=(str(s2),), statuses={400})
    _t0_setting(d["cid"])
    r = _r(client.post(f"/api/v1/shifts/{s1}/cash", headers=h, json={"type": "payin", "amount": 5}),
           sent=(str(s1),), code=CG.ERR_LEGACY_SHIFT_NEEDS_TILL, statuses={400})
    assert _detail(r).startswith(CG.ERR_LEGACY_SHIFT_NEEDS_TILL + ":"), r.text


# ══ SQLite — mijoz qarz to'lovi ═════════════════════════════════════════════

def test_MIJOZ_TOLOVI_rad_etishlari_toza(client):
    d = _shop()
    cid_c = _customer(d)
    yoq = uuid.uuid4()
    url = f"/api/v1/customers/{cid_c}/payments"
    _r(client.post(f"/api/v1/customers/{yoq}/payments", headers=d["H"],
                   json={"amount": 10, "method": "card"}), sent=(str(yoq),), statuses={404})
    _r(client.post(url, headers=d["H"], json={"amount": 10, "method": "crypto"}),
       sent=(str(cid_c),), statuses={400})
    _r(client.post(url, headers=d["H"], json={"amount": -1, "method": "card"}),
       sent=(str(cid_c),), statuses={400})
    qarzsiz = _customer(d, debt="0")
    _r(client.post(f"/api/v1/customers/{qarzsiz}/payments", headers=d["H"],
                   json={"amount": 10, "method": "card"}), sent=(str(qarzsiz),), statuses={400})


def test_MIJOZ_TOLOVI_kalit_BOSHQA_hisob_bilan_SAQLANGAN_id_SIZMAYDI(client):
    """T12 (audit): birinchi to'lov hisob A bilan yozilgan; ayni `client_uuid` hisob B bilan
    qayta kelsa — 409 `CASH_CUSTODY_ACCOUNT_INVALID`, va tanada A YO'Q (mijoz A ni bu
    so'rovda yubormagan). Ilgari `customers.py` A ni matnga yozardi. Kod sarlavhada ham."""
    from app.models.customers import CustomerPayment
    d = _shop()
    c = _customer(d)
    kalit, a_hisob, b_hisob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with _db() as db:
        db.add(CustomerPayment(id=uuid.uuid4(), customer_id=c, amount=Decimal("10"),
                               method="cash", paid_at=NOW, employee_id=d["eid"],
                               client_uuid=kalit, cash_account_id=a_hisob, created_at=NOW))
        db.commit()
    body = {"amount": 10, "method": "cash", "client_uuid": str(kalit),
            "cash_account_id": str(b_hisob)}
    r = _r(client.post(f"/api/v1/customers/{c}/payments", headers=d["H"], json=body),
           sent=(str(c), body), code=CG.ERR_CUSTODY_INVALID, statuses={409})
    assert str(a_hisob) not in r.text, r.text
    assert _detail(r).startswith(CG.ERR_CUSTODY_INVALID + ":"), r.text


def test_MIJOZ_TOLOVI_KASSA_GARDI_smena_kassasi_id_SIZMAYDI_va_SARLAVHALI(client):
    """C15/C17 SQLite'da ham tug'iladi (CashAccount jadvaliga tegmasdan):
      · ochiq smena kassasi T, so'rovda B != T -> TILL_DOES_NOT_MATCH_SHIFT — tanada T YO'Q;
      · T0 o'tgan, smenasiz, hisobsiz naqd -> CASH_CUSTODY_ACCOUNT_REQUIRED."""
    from app.models.shifts import Shift
    d = _shop()
    c = _customer(d)
    url = f"/api/v1/customers/{c}/payments"
    # Egа'ning O'Z ochiq smenasi (custody qoidasi AYNI xodimning smenasiga qaraydi).
    smena_kassasi = uuid.uuid4()
    s1 = _smena(d, d["eid"])
    with _db() as db:
        db.get(Shift, s1).till_id = smena_kassasi
        db.commit()
    b_hisob = str(uuid.uuid4())
    body = {"amount": 10, "method": "cash", "cash_account_id": b_hisob}
    r = _r(client.post(url, headers=d["H"], json=body), sent=(str(c), body),
           code=CG.ERR_TILL_SHIFT_MISMATCH, statuses={400})
    assert str(smena_kassasi) not in r.text, r.text
    _smena_yop(s1)
    _t0_setting(d["cid"])
    r = _r(client.post(url, headers=d["H"], json={"amount": 10, "method": "cash"}), sent=(str(c),),
           code=CG.ERR_CUSTODY_REQUIRED, statuses={400})
    assert _detail(r).startswith(CG.ERR_CUSTODY_REQUIRED + ":"), r.text


# ══ SQLite — ta'minotchi to'lovi ════════════════════════════════════════════

def test_TAMINOTCHI_TOLOVI_rad_etishlari_toza(client):
    d = _shop()
    yoq = uuid.uuid4()
    url = f"/api/v1/suppliers/{d['sup']}/payments"
    _r(client.post(f"/api/v1/suppliers/{yoq}/payments", headers=d["H"],
                   json={"amount": 10, "method": "card"}), sent=(str(yoq),), statuses={404})
    _r(client.post(url, headers=d["H"], json={"amount": 10, "method": "crypto"}),
       sent=(str(d["sup"]),), statuses={400})
    _r(client.post(url, headers=d["H"], json={"amount": 10, "method": "card"}),
       sent=(str(d["sup"]),), statuses={400})           # qarz yo'q
    _supplier_debt(d)
    _t0_setting(d["cid"])
    r = _r(client.post(url, headers=d["H"], json={"amount": 10, "method": "cash"}),
           sent=(str(d["sup"]),), code=CG.ERR_CUSTODY_REQUIRED, statuses={400})
    assert _detail(r).startswith(CG.ERR_CUSTODY_REQUIRED + ":"), r.text


def test_TAMINOTCHI_TOLOVI_kalit_BOSHQA_hisob_bilan_SAQLANGAN_id_SIZMAYDI(client):
    """T12 (audit) — `purchases.pay_supplier` (B2 paketi tuzatgan): saqlangan hisob A tanada YO'Q,
    kod prefiks + sarlavhada; matn `customers.pay_credit` bilan AYNI jumla."""
    from app.models.purchasing import SupplierPayment
    d = _shop()
    _supplier_debt(d)
    kalit, a_hisob, b_hisob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with _db() as db:
        db.add(SupplierPayment(id=uuid.uuid4(), supplier_id=d["sup"], amount=Decimal("10"),
                               method="cash", paid_at=NOW, employee_id=d["eid"],
                               client_uuid=kalit, cash_account_id=a_hisob, created_at=NOW))
        db.commit()
    body = {"amount": 10, "method": "cash", "client_uuid": str(kalit),
            "cash_account_id": str(b_hisob)}
    r = _r(client.post(f"/api/v1/suppliers/{d['sup']}/payments", headers=d["H"], json=body),
           sent=(str(d["sup"]), body), code=CG.ERR_CUSTODY_INVALID, statuses={409})
    assert str(a_hisob) not in r.text, r.text
    assert _detail(r) == CG.KEY_ACCOUNT_CONFLICT_TEXT, r.text     # bitta matn, uch yo'l


def test_XARID_kalit_BOSHQA_hisob_bilan_SAQLANGAN_id_SIZMAYDI(client):
    """T12 (audit) — `purchases.create_purchase` (B2 paketi tuzatgan): saqlangan hisob A tanada YO'Q."""
    from datetime import date
    from app.models.enums import PurchaseStatus
    from app.models.purchasing import Purchase
    d = _shop()
    p = _product(d)
    kalit, a_hisob, b_hisob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with _db() as db:
        db.add(Purchase(id=uuid.uuid4(), doc_no="KIR-HYG-" + uuid.uuid4().hex[:6],
                        company_id=d["cid"], branch_id=d["bids"][0], supplier_id=d["sup"],
                        employee_id=d["eid"], purchase_date=date.today(),
                        status=PurchaseStatus.received, cash_account_id=a_hisob,
                        client_uuid=kalit, subtotal=5, total=5, paid_amount=5))
        db.commit()
    body = {"supplier_id": str(d["sup"]), "status": "received",
            "items": [{"product_id": str(p["id"]), "qty": 1, "unit_cost": 5}],
            "client_uuid": str(kalit), "cash_account_id": str(b_hisob)}
    r = _r(client.post("/api/v1/purchases", headers=d["H"], json=body), sent=(body,),
           code=CG.ERR_CUSTODY_INVALID, statuses={409})
    assert str(a_hisob) not in r.text, r.text
    assert _detail(r) == CG.KEY_ACCOUNT_CONFLICT_TEXT, r.text


# ══ SQLite — 502 AI skan: yuqori oqim matni AYNAN uzatilmaydi ════════════════

def test_SKAN_502_yuqori_oqim_matni_UZATILMAYDI_kod_SARLAVHADA(client, monkeypatch):
    from app.api.v1 import receiving as _RV
    d = _shop()
    sir = f"Traceback (most recent call last): psycopg.OperationalError relation \"x\" {uuid.uuid4()}"
    monkeypatch.setattr(_RV, "read_invoice", lambda *_a, **_k: ([], "error:" + sir[:120]))
    r = _r(client.post("/api/v1/receiving/scan", headers=d["H"],
                       json={"image_b64": "QUJD", "media_type": "image/jpeg"}),
           code="AI_SCAN_FAILED", statuses={502})
    assert "OperationalError" not in r.text and sir[:30] not in r.text, r.text


# ══ PostgreSQL — kassa gardi: CashAccount'ga qaraydigan rad etishlar ═════════

def _cash_failures(caplog) -> list[dict]:
    out = []
    for m in caplog.messages:
        try:
            j = json.loads(m)
        except Exception:        # noqa: BLE001
            continue
        if isinstance(j, dict) and j.get("evt") == "cash_failure":
            out.append(j)
    return out


def _log_has(caplog, code: str, **fields) -> dict:
    """`savdoos.cash` jurnalida `code` li qator BOR va STRUKTURALI maydonlari mos."""
    rows = [j for j in _cash_failures(caplog) if j.get("code") == code]
    assert rows, f"jurnalda {code} yo'q: {caplog.messages[-5:]}"
    for j in rows:
        if all(str(j.get(k)) == str(v) for k, v in fields.items()):
            return j
    raise AssertionError(f"{code} qatorlarida {fields} yo'q: {rows}")


def _pg_env():
    from tests.test_mobile_parity_pg import (_customer as _pg_customer, _run, _sc,
                                             _supplier_debt as _pg_supdebt, _w_collection,
                                             _w_debt, _w_receiving, _w_supplier)
    from tests.test_receiving_correction_pg import _baza
    return dict(_baza=_baza, _sc=_sc, _run=_run, _w_receiving=_w_receiving, _w_debt=_w_debt,
                _w_supplier=_w_supplier, _w_collection=_w_collection, _customer=_pg_customer,
                _supplier_debt=_pg_supdebt)


def _wire(res, *, sent, code, statuses=(400,)):
    """`_run` natijasi (status, detail, prefiks-kod, sarlavha-kod) — qoida + kod ikkala yo'lda."""
    assert res[0] in statuses, res
    hygienic(res[0], res[1], {HDR: res[3]}, sent=_ids(*sent), code=code)
    assert res[2] == code, res
    return res


def test_PG_KASSA_GARDI_bazadan_olingan_id_TANADA_YOQ_JURNALDA_BOR(pg_target, caplog):
    """C3 (smena kassasi yo'q), C8 (hisob begona filialda), C13 (kassa begona filialda),
    C15 (so'rov hisobi != smena kassasi), C10/C17 (kodli, id'siz), tuzatishning naqd oyog'i.
    Har birida: tanada mijoz yubormagan id YO'Q, kod sarlavhada, jurnalda id STRUKTURALI."""
    from app.models.shifts import Shift
    caplog.set_level(logging.WARNING, logger="savdoos.cash")
    E = _pg_env()
    eng, S = E["_baza"](pg_target)
    try:
        # C8 — smenasiz ta'minotchi to'lovi, hisob BEGONA filialda (acc.branch_id bazadan).
        d, acc = E["_sc"](S, t0=True, shift=None)
        E["_supplier_debt"](S, d)
        res = _wire(E["_run"](S, E["_w_supplier"](d, acc["foreign_till"])),
                    sent=(str(d["sup"]), str(acc["foreign_till"]["id"])), code=CG.ERR_CUSTODY_INVALID)
        assert str(d["bid2"]) not in res[1] and "boshqa filialga tegishli" in res[1], res
        _log_has(caplog, CG.ERR_CUSTODY_INVALID, account_id=acc["foreign_till"]["id"],
                 branch_id=d["bid2"], company_id=d["cid"], op="supplier_payment")

        # C15 — smena kassasi T, so'rovda SAFE: T tanada YO'Q.
        d, acc = E["_sc"](S, t0=True, shift="till")
        res = _wire(E["_run"](S, E["_w_receiving"](d, acc["safe"])),
                    sent=(str(d["pid"]), str(d["sup"]), str(acc["safe"]["id"])),
                    code=CG.ERR_TILL_SHIFT_MISMATCH)
        assert str(acc["till"]["id"]) not in res[1], res
        _log_has(caplog, CG.ERR_TILL_SHIFT_MISMATCH, till_id=acc["till"]["id"],
                 account_id=acc["safe"]["id"], company_id=d["cid"])

        # C3 (ID-UNSENT shoxobcha) — smena kassasi bazada YO'Q hisobga ishora qiladi.
        d, acc = E["_sc"](S, t0=True, shift="till")
        yoq_till = uuid.uuid4()
        s = S()
        try:
            for sh in s.query(Shift).filter(Shift.cashier_id == d["emp"]).all():
                sh.till_id = yoq_till
            s.commit()
        finally:
            s.close()
        res = _wire(E["_run"](S, E["_w_receiving"](d)), sent=(str(d["pid"]), str(d["sup"])),
                    code=CG.ERR_CUSTODY_INVALID)
        assert str(yoq_till) not in res[1], res
        _log_has(caplog, CG.ERR_CUSTODY_INVALID, account_id=yoq_till, company_id=d["cid"])

        # C13 — smena A filialida, kassasi B filialida: acc.branch_id tanada YO'Q.
        d, acc = E["_sc"](S, t0=True, shift=None)
        _pg_smena(S, d, till=acc["foreign_till"])
        s = S()
        try:
            for sh in s.query(Shift).filter(Shift.cashier_id == d["emp"]).all():
                sh.opening_cash = Decimal("100000")
            s.commit()
        finally:
            s.close()
        res = _wire(E["_run"](S, E["_w_collection"](d, acc["safe"])),
                    sent=(str(acc["safe"]["id"]),), code=CG.ERR_TILL_INVALID)
        assert str(d["bid2"]) not in res[1] and str(acc["foreign_till"]["id"]) not in res[1], res
        _log_has(caplog, CG.ERR_TILL_INVALID, till_id=acc["foreign_till"]["id"],
                 branch_id=d["bid2"], company_id=d["cid"])

        # C17 / C10 — kodli, id'siz; sarlavha ham.
        d, acc = E["_sc"](S, t0=True, shift=None)
        E["_customer"](S, d)
        _wire(E["_run"](S, E["_w_debt"](d)), sent=(str(d["cust"]),), code=CG.ERR_CUSTODY_REQUIRED)
        d, acc = E["_sc"](S, t0=True, shift="legacy")
        _wire(E["_run"](S, E["_w_receiving"](d)), sent=(str(d["pid"]), str(d["sup"])),
              code=CG.ERR_LEGACY_SHIFT_NEEDS_TILL)

        # Tuzatishning naqd oyog'i (audit 19-qator): `lot_correction._custody` -> gard.
        d, acc = E["_sc"](S, t0=False, shift=None)
        _qabul(S, d, account=acc["till"])
        _t0(S, d)
        with pytest.raises(HTTPException) as ei:
            _kamaytir(S, d)
        hygienic(ei.value.status_code, str(ei.value.detail), ei.value.headers or {},
                 sent=_ids(str(d["rec"]), str(d["item"]), str(d["batch"])),
                 code=CG.ERR_CUSTODY_REQUIRED, statuses={400})

        # C1 / C14 — gard darajasida (yagona kompozitor `_fail`): yopilgan smena replay'i
        # va so'rov kassasi != smena kassasi. Ikkalasida ham smena/kassa id'i tanada YO'Q.
        d, acc = E["_sc"](S, t0=True, shift="till")
        till2 = _hisob(S, d)
        s = S()
        try:
            sh = s.query(Shift).filter(Shift.cashier_id == d["emp"]).one()
            with pytest.raises(HTTPException) as ei:
                CG.require_post_t0_till(s, company_id=d["cid"], branch_id=d["bid"],
                                        operation="cash_sale", shift=sh, till_id=till2["id"])
            hygienic(400, str(ei.value.detail), ei.value.headers or {}, sent=_ids(str(till2["id"])),
                     code=CG.ERR_TILL_SHIFT_MISMATCH)
            assert str(sh.till_id) not in str(ei.value.detail)
            _log_has(caplog, CG.ERR_TILL_SHIFT_MISMATCH, shift_id=sh.id, till_id=till2["id"])
            from app.models.enums import ShiftStatus
            sh.status = ShiftStatus.closed
            sh.closed_at = NOW
            s.flush()
            with pytest.raises(HTTPException) as ei:
                CG.reject_closed_shift_replay(s, company_id=d["cid"], shift=sh,
                                              operation="offline_cash_sale")
            hygienic(400, str(ei.value.detail), ei.value.headers or {}, sent=set(),
                     code=CG.ERR_CLOSED_SHIFT_REPLAY)
            assert str(sh.id) not in str(ei.value.detail)
            _log_has(caplog, CG.ERR_CLOSED_SHIFT_REPLAY, shift_id=sh.id, company_id=d["cid"],
                     op="offline_cash_sale")
            s.rollback()
        finally:
            s.close()
    finally:
        eng.dispose()


def test_PG_LEDGER_YOZILMASA_sxema_va_rejim_nomi_TANADA_YOQ_503_ham_KODLI(pg_target, caplog):
    """C18: `LedgerUnavailable` matni (`cash` sxemasi, `LEGACY_ONLY`) FAQAT jurnalga; operator
    barqaror kod + xavfsiz jumla oladi — 400 (gard) va 503 (`services/sales.py`) da AYNI kod,
    prefiks VA sarlavha bilan. «LEDGER-NATIVE» so'zi qoladi (do'kon rejimi, id emas)."""
    from app.models.settings import Setting
    from app.schemas.sales import SaleCreate, SaleItemIn
    from app.services import sales as _sales
    from app.services.cash import mode as _mode
    caplog.set_level(logging.WARNING, logger="savdoos.cash")
    E = _pg_env()
    eng, S = E["_baza"](pg_target)
    try:
        d, acc = E["_sc"](S, t0=True, shift="till")
        s = S()
        try:
            row = (s.query(Setting).filter(Setting.company_id == d["cid"], Setting.key == "cash",
                                           Setting.branch_id.is_(None)).one())
            row.value = {**(row.value or {}), "ledger_native": True}
            s.commit()
        finally:
            s.close()
        _mode.set_mode("LEGACY_ONLY")
        try:
            res = _wire(E["_run"](S, E["_w_receiving"](d)), sent=(str(d["pid"]), str(d["sup"])),
                        code=CG.ERR_LEDGER_UNAVAILABLE)
            assert "LEDGER-NATIVE" in res[1], res
            j = _log_has(caplog, CG.ERR_LEDGER_UNAVAILABLE, company_id=d["cid"])
            assert "LEGACY_ONLY" in j.get("detail", ""), j     # ichki sabab JURNALDA
            # 503 — naqd savdo (`services/sales.py`), AYNI kod prefiks + sarlavha.
            s = S()
            try:
                with pytest.raises(HTTPException) as ei:
                    _sales.create_sale(s, _pg_emp(s, d), SaleCreate(
                        items=[SaleItemIn(product_id=d["pid"], qty=1)], payment_method="cash",
                        client_uuid=uuid.uuid4()))
                assert ei.value.status_code == 503, (ei.value.status_code, ei.value.detail)
                hygienic(503, str(ei.value.detail), ei.value.headers or {},
                         sent=_ids(str(d["pid"])), code=CG.ERR_LEDGER_UNAVAILABLE)
                assert str(ei.value.detail).startswith(CG.ERR_LEDGER_UNAVAILABLE + ":")
                assert "LEDGER-NATIVE" in str(ei.value.detail)
                s.rollback()
            finally:
                s.close()
        finally:
            _mode.reset_mode()
    finally:
        eng.dispose()
