# -*- coding: utf-8 -*-
"""PHASE 5B — ICHKI XATO MATNI OPERATORGA SIZMAYDI (sotuv / qaytarish / qarzni yopish).

Phase 4B.1 (a9d3a7e) hisobdan chiqarish, sanoq, kuzatuvni yoqish, kirim va
qaytarish invariantida xom istisno matnini (UUID, `≠`, modul nomlari) javobdan
olib tashlagan edi. To'rtta darvoza o'shanda TUSHIB QOLGAN:

  (a) sotuvning yakuniy darvozasi (`services/sales.py`) — baza xatosida
      `[SQL: ...]` va parametrlarni ham uzatardi;
  (b) qaytarish chegaralari (`lot_return.assert_caps` qatorlari);
  (c) qaytarish tannarx asosi (ichki summalar va atamalar);
  (d) qarzni yopish invarianti (`services/lot_resolution.py`).

Shartnoma HAR darvozada bir xil:
  · HTTP holati 409 QOLADI (`/sync/push` uchun tranzient — chek yo'qolmaydi);
  · `detail` — lug'atdagi ANIQ matn, xom tafsilotsiz;
  · barqaror kod `X-Error-Code` sarlavhasida (matnga prefiks EMAS);
  · tafsilot server JURNALIDA;
  · hech narsa yozilmaydi.

Har qoida uchun MANFIY nazorat bor: buzilishsiz ayni oqim 200 beradi — ya'ni
409 aynan shu darvozadan kelgani isbotlanadi.
"""
import logging
import uuid
from decimal import Decimal

import pytest

from app.models.inventory import (Inventory, LotShortfall, LotShortfallResolution,
                                  ReturnItemLotAllocation)
from app.models.sales import Return, Sale
from app.services import lot_return as LR
from app.services import stock_invariant as SI

from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    _allocs,
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
from tests.test_lot_return import _resolve, _ret, _sf

SALE_409 = ("Savdoni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; "
            "qo'llab-quvvatlashga murojaat qiling.")
RETURN_409 = ("Qaytarishni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; "
              "qo'llab-quvvatlashga murojaat qiling.")
RESOLVE_409 = ("Qarzni yopib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; "
               "qo'llab-quvvatlashga murojaat qiling.")
# Javobda HECH QACHON ko'rinmasligi kerak bo'lgan ichki belgilar.
ICHKI = ("≠", "stock_invariant", "QUANTITY_BEARING", "InvariantBroken", "[SQL", "Traceback")


# ⚠️  ROL BO'YICHA BITTA XODIM, FAYL BO'YI — `test_lot_permissions.py` naqshi.
#     Demo tarifi 10 foydalanuvchi va baza hamma fayl uchun umumiy. O'sha faylning
#     keshi ATAYLAB ishlatilmaydi: uni bu fayl to'ldirib, o'sha fayl tozalasa (yoki
#     aksincha) xodim boshqa faylning ostidan o'chib ketardi.
_CACHE: dict = {}


def _staff(client, admin_headers, role):
    if role not in _CACHE:
        phone = "+99893" + str(uuid.uuid4().int % 10_000_000).zfill(7)
        pw = "Toshkent-Kuz-2026"
        r = client.post("/api/v1/employees", headers=admin_headers, json={
            "full_name": f"5B {role}", "phone": phone, "password": pw, "role_code": role})
        assert r.status_code == 200, r.text
        lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": pw})
        assert lg.status_code == 200, lg.text
        _CACHE[role] = {"Authorization": f"Bearer {lg.json()['access_token']}",
                        "__id": r.json()["id"]}
    return {k: v for k, v in _CACHE[role].items() if not k.startswith("__")}


@pytest.fixture(scope="module", autouse=True)
def _tozalash(client):
    """Fayl tugagach sinov xodimlarini o'chiradi — tarif limitini band qilmasin."""
    yield
    import contextlib
    r = client.post("/api/v1/auth/login/password",
                    json={"phone": "+998901234567", "password": "demo1234"})
    if r.status_code != 200:
        return
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for v in _CACHE.values():
        with contextlib.suppress(Exception):
            client.delete(f"/api/v1/employees/{v['__id']}", headers=h)
    _CACHE.clear()


@pytest.fixture()
def jurnal(caplog):
    caplog.set_level(logging.INFO)
    return caplog


def _buzish(pid, bid, qty):
    """`Inventory.qty` ni partiyalardan ATAYLAB ajratadi — invariant buziladi."""
    with _db() as db:
        i = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(pid),
                                       Inventory.branch_id == bid).first()
        i.qty = Decimal(str(qty))
        db.commit()


def _lot_sum(pid):
    return sum((Decimal(str(b.remaining_qty)) for b in _lots(pid)), Decimal("0"))


def _sale_by_cu(cu):
    with _db() as db:
        return db.query(Sale).filter(Sale.client_uuid == uuid.UUID(str(cu))).count()


def _sizmagan(r, *extra):
    """Javob matnida ichki belgi ham, berilgan identifikatorlar ham YO'Q."""
    for s in ICHKI + tuple(str(x) for x in extra):
        assert s not in r.text, f"{s!r} javobga sizib chiqdi: {r.text}"


def _sell_card(client, headers, pid, qty, price=100, cu=None):
    """KARTA sotuv — karta qaytarishi smena talab qilmaydi (naqd qaytarish talab qiladi)."""
    return client.post("/api/v1/sales", headers=headers, json={
        "items": [{"product_id": pid, "qty": qty, "unit_price": price}],
        "payment_method": "card", "client_uuid": str(cu or uuid.uuid4())})


def _return_count(sale_id):
    with _db() as db:
        return db.query(Return).filter(Return.original_sale_id == uuid.UUID(sale_id)).count()


def _ret_allocs(pid):
    with _db() as db:
        return (db.query(ReturnItemLotAllocation)
                .filter(ReturnItemLotAllocation.product_id == uuid.UUID(pid)).count())


# ══ (a) SOTUV DARVOZASI ═════════════════════════════════════════════════════

def test_SOTUV_invarianti_buzilsa_409_ANIQ_matn_UUID_SIZMAYDI(client, admin_headers, ctx, sup,
                                                             jurnal):
    """Qoldiq 9, partiyalar 10. Sotuv qoldiq guard'idan va FEFO'dan o'tadi,
    yakuniy darvozada yiqiladi — ilgari javobda xom `Mismatch` matni turardi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 55, D10).status_code == 200
    _buzish(pid, bid, 9)
    cu = uuid.uuid4()

    r = _sell(client, admin_headers, pid, 1, cu=cu)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == SALE_409
    assert r.headers.get("X-Error-Code") == "LOT_INVARIANT_BROKEN"
    _sizmagan(r, pid, bid, cid)

    # Hech narsa yozilmadi
    assert _inv(pid, bid) == Decimal("9.000")
    assert _lot_sum(pid) == Decimal("10.000")
    assert _sale_by_cu(cu) == 0
    assert _allocs(pid) == []
    # Tafsilot JURNALDA
    assert pid in jurnal.text and "LOT_INVARIANT_BROKEN" in jurnal.text
    assert "InvariantBroken" in jurnal.text


def test_SOTUV_buzilishsiz_OTADI_va_FEFO_matni_OZGARMAGAN(client, admin_headers, ctx, sup):
    """MANFIY NAZORAT: ayni oqim buzilishsiz 200 — 409 aynan darvozadan edi.
    FEFO rad etishi esa o'z operator matnini SAQLAYDI (u ichki xato emas)."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 55, D10).status_code == 200
    r = _sell(client, admin_headers, pid, 1)
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Error-Code") is None
    assert _inv(pid, bid) == Decimal("9.000") and _lot_sum(pid) == Decimal("9.000")

    # Qoldiq 10, yaroqli partiya 7 -> FEFO 409 (darvoza EMAS) — matn va kod yo'q.
    pid2 = _product(client, admin_headers)
    _enable(client, admin_headers, pid2)
    assert _recv(client, admin_headers, sup, pid2, 7, 50, D10).status_code == 200
    _buzish(pid2, bid, 10)
    r2 = _sell(client, admin_headers, pid2, 10)
    assert r2.status_code == 409, r2.text
    assert "yaroqli partiya" in r2.json()["detail"], r2.text
    assert r2.headers.get("X-Error-Code") is None


def test_SOTUV_darvozasidagi_BAZA_xatosi_SQL_matnini_SIZDIRMAYDI(client, admin_headers, ctx, sup,
                                                               monkeypatch, jurnal):
    """Darvoza SELECT'idagi `OperationalError` ilgari `[SQL: ...]`, parametrlar va
    sqlalche.me havolasi bilan javobga tushardi."""
    from sqlalchemy.exc import OperationalError
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 55, D10).status_code == 200

    def boom(*a, **k):
        raise OperationalError(
            "SELECT stock_batches.status FROM stock_batches "
            "WHERE stock_batches.company_id = %(company_id_1)s",
            {"company_id_1": str(cid)}, Exception("canceling statement due to lock timeout"))
    monkeypatch.setattr(SI, "assert_ok", boom)

    cu = uuid.uuid4()
    r = _sell(client, admin_headers, pid, 1, cu=cu)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == SALE_409
    assert r.headers.get("X-Error-Code") == "LOT_INVARIANT_BROKEN"
    for s in ("[SQL", "stock_batches", "sqlalche.me", "lock timeout", "parameters", str(cid)):
        assert s not in r.text, f"{s!r} javobga sizib chiqdi"
        assert s in jurnal.text, f"{s!r} jurnalga tushmadi — tafsilot YO'QOLDI"
    assert _sale_by_cu(cu) == 0
    assert _inv(pid, bid) == Decimal("10.000") and _lot_sum(pid) == Decimal("10.000")


def test_OFFLINE_replay_darvozada_TRANZIENT_qoladi_va_KOD_beradi(client, admin_headers, ctx, sup):
    """`/sync/push`: 409 tranzient — pul olingan chek outbox'da QOLADI; `code` qo'shimcha."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 55, D10).status_code == 200
    _buzish(pid, bid, 9)
    cu = uuid.uuid4()
    r = _replay(client, admin_headers, pid, 1, cu=cu)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["ok"] is False
    assert res["retry"] is True, "invariant 409 dead-letter bo'ldi — pul olingan chek YO'QOLADI"
    assert res["error"] == SALE_409
    assert res["code"] == "LOT_INVARIANT_BROKEN"
    _sizmagan(r, pid, bid)
    assert _sale_by_cu(cu) == 0
    assert _inv(pid, bid) == Decimal("9.000") and _lot_sum(pid) == Decimal("10.000")

    # Doimiy (400) xato: kod YO'Q, retry YO'Q — mavjud semantika o'zgarmagan.
    r2 = _replay(client, admin_headers, str(uuid.uuid4()), 1)
    res2 = r2.json()["results"][0]
    assert res2["ok"] is False and res2["retry"] is False and res2["code"] is None


# ══ (b) QAYTARISH CHEGARALARI ═══════════════════════════════════════════════

def _tracked_card_sale(client, headers, sup, qty=5):
    pid = _product(client, headers)
    _enable(client, headers, pid)
    assert _recv(client, headers, sup, pid, 10, 50, D10).status_code == 200
    r = _sell_card(client, headers, pid, qty)
    assert r.status_code == 200, r.text
    return pid, r.json()["id"]


def test_QAYTARISH_chegara_buzilishi_UUID_va_USTUN_nomlarini_SIZDIRMAYDI(
        client, admin_headers, ctx, sup, monkeypatch, jurnal):
    cid, bid = ctx
    pid, sid = _tracked_card_sale(client, admin_headers, sup)
    inv0, lots0 = _inv(pid, bid), _lot_sum(pid)
    begona = uuid.uuid4()
    monkeypatch.setattr(LR, "assert_caps", lambda db, **kw: [
        f"qarz {begona}: returned_qty 1 != Σ dum 0",
        f"qator {uuid.uuid4()} partiya {uuid.uuid4()}: qaytgan 2 > 1"])

    r = _ret(client, admin_headers, sid, pid, 2, method="card")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == RETURN_409
    assert r.headers.get("X-Error-Code") == "LOT_RETURN_CAPS_VIOLATED"
    _sizmagan(r, begona, pid, sid)
    for s in ("returned_qty", "Σ", "qarz ", "chegarasi buzilardi"):
        assert s not in r.text, f"{s!r} javobga sizib chiqdi"
    # Hech narsa yozilmadi
    assert _return_count(sid) == 0
    assert _ret_allocs(pid) == 0
    assert _inv(pid, bid) == inv0 and _lot_sum(pid) == lots0
    # Buzilishlar JURNALDA — hammasi
    assert str(begona) in jurnal.text and "returned_qty" in jurnal.text
    assert "LOT_RETURN_CAPS_VIOLATED" in jurnal.text


def test_QAYTARISH_buzilishsiz_OTADI(client, admin_headers, ctx, sup):
    """MANFIY NAZORAT: chegara va tannarx darvozalari o'tkazganda qaytarish yoziladi."""
    cid, bid = ctx
    pid, sid = _tracked_card_sale(client, admin_headers, sup)
    r = _ret(client, admin_headers, sid, pid, 2, method="card")
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Error-Code") is None
    assert _return_count(sid) == 1 and _ret_allocs(pid) == 1
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


# ══ (c) QAYTARISH TANNARX ASOSI ═════════════════════════════════════════════

def test_QAYTARISH_tannarx_asosi_nomuvofiq_SUMMALARNI_SIZDIRMAYDI(
        client, admin_headers, ctx, sup, monkeypatch, jurnal):
    """Taxminiy partiya ulushi aniq summadan katta — dasturiy invariant, operator xatosi emas."""
    cid, bid = ctx
    pid, sid = _tracked_card_sale(client, admin_headers, sup)
    inv0, lots0 = _inv(pid, bid), _lot_sum(pid)
    real_plan = LR.plan

    class _Buzuq(LR.ReturnPlan):
        @property
        def provisional_lot_cost(self):
            return self.exact_cost + Decimal("777.77")

    def buzuq_plan(db, **kw):
        p = real_plan(db, **kw)
        return _Buzuq(lot_lines=p.lot_lines, event_lines=p.event_lines,
                      debt_lines=p.debt_lines, shortfall_ids=p.shortfall_ids)
    monkeypatch.setattr(LR, "plan", buzuq_plan)

    r = _ret(client, admin_headers, sid, pid, 1, method="card")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == RETURN_409
    assert r.headers.get("X-Error-Code") == "LOT_COST_BASIS_INCONSISTENT"
    # exact = 1 × 50.00; taxminiy = 827.77 — ikkalasi ham javobda YO'Q
    for s in ("827.77", "777.77", "50.00", "Tannarx asosi", "ulush"):
        assert s not in r.text, f"{s!r} javobga sizib chiqdi"
    _sizmagan(r, pid, sid)
    assert _return_count(sid) == 0 and _ret_allocs(pid) == 0
    assert _inv(pid, bid) == inv0 and _lot_sum(pid) == lots0
    assert "827.77" in jurnal.text and "LOT_COST_BASIS_INCONSISTENT" in jurnal.text


# ══ (d) QARZNI YOPISH ═══════════════════════════════════════════════════════

def _shortfall(client, headers, sup, bid):
    """2 partiya + 6 offline sotuv -> qarz 4; keyin 10 lik YANGI partiya.
    Invariant: qoldiq 6 == partiyalar 10 − qarz 4."""
    pid = _product(client, headers)
    _enable(client, headers, pid)
    assert _recv(client, headers, sup, pid, 2, 50, D10).status_code == 200
    assert _replay(client, headers, pid, 6).json()["results"][0]["ok"] is True
    assert _recv(client, headers, sup, pid, 10, 60, D20).status_code == 200
    sf = _sf(pid)
    lot = [b for b in _lots(pid) if Decimal(str(b.remaining_qty)) > 0][0]
    assert _inv(pid, bid) == Decimal("6.000")
    return pid, sf, lot


def _events(sf_id):
    with _db() as db:
        return db.query(LotShortfallResolution).filter(
            LotShortfallResolution.shortfall_id == sf_id).count()


def _resolved(sf_id):
    with _db() as db:
        return Decimal(str(db.get(LotShortfall, sf_id).resolved_qty or 0))


def test_YOPISH_invarianti_buzilsa_409_UUID_SIZMAYDI(client, admin_headers, ctx, sup,
                                                    monkeypatch, jurnal):
    cid, bid = ctx
    pid, sf, lot = _shortfall(client, admin_headers, sup, bid)

    def boom(db, company_id, product_ids=None):
        raise SI.InvariantBroken(
            f"Partiya miqdor invarianti BUZILGAN — amal bajarilmadi. mahsulot {pid} "
            f"filial {bid}: qoldiq 6.000 ≠ partiyalar 8.000 (farq -2.000)")
    monkeypatch.setattr(SI, "assert_ok", boom)

    r = _resolve(client, admin_headers, sf.id, batch=lot.id, qty=2)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == RESOLVE_409
    assert r.headers.get("X-Error-Code") == "LOT_RESOLVE_INVARIANT_BROKEN"
    _sizmagan(r, pid, bid, sf.id, lot.id)
    assert "invariant buzilardi" not in r.text
    # Hech narsa yozilmadi
    assert _resolved(sf.id) == Decimal("0.000")
    assert _events(sf.id) == 0
    assert Decimal(str([b for b in _lots(pid) if b.id == lot.id][0].remaining_qty)) == 10
    assert _inv(pid, bid) == Decimal("6.000")
    assert pid in jurnal.text and str(sf.id) in jurnal.text
    assert "LOT_RESOLVE_INVARIANT_BROKEN" in jurnal.text


def test_YOPISH_buzilishsiz_OTADI(client, admin_headers, ctx, sup):
    """MANFIY NAZORAT: ayni yopish buzilishsiz 200 va hodisa yoziladi."""
    cid, bid = ctx
    pid, sf, lot = _shortfall(client, admin_headers, sup, bid)
    r = _resolve(client, admin_headers, sf.id, batch=lot.id, qty=2)
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Error-Code") is None
    assert _resolved(sf.id) == Decimal("2.000") and _events(sf.id) == 1


# ══ PHASE 4B.1 DARVOZALARI — MATN O'ZGARMAGAN, KOD QO'SHILGAN ═══════════════

def test_HISOBDAN_CHIQARISH_darvozasi_KOD_beradi_matn_OZGARMAGAN(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 8, 50, D10).status_code == 200
    lot_id = str(_lots(pid)[0].id)
    _buzish(pid, bid, 9)
    r = client.post("/api/v1/inventory/writeoff", headers=admin_headers, json={
        "product_id": pid, "qty": 2, "reason": "brak", "client_uuid": str(uuid.uuid4()),
        "lots": [{"stock_batch_id": lot_id, "qty": 2}]})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == ("Hisobdan chiqarib bo'lmadi — partiya va qoldiq mos kelmadi. "
                                  "Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.")
    assert r.headers.get("X-Error-Code") == "LOT_INVARIANT_BROKEN"
    _sizmagan(r, pid, bid)
    assert _inv(pid, bid) == Decimal("9.000") and _lot_sum(pid) == Decimal("8.000")


def test_KIRIM_darvozasi_KOD_beradi_matn_OZGARMAGAN(client, admin_headers, ctx, sup):
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 8, 50, D10).status_code == 200
    _buzish(pid, bid, 9)
    r = _recv(client, admin_headers, sup, pid, 5, 50, D20)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == ("Partiya va qoldiq mos kelmadi — kirim BEKOR qilindi. "
                                  "Qo'llab-quvvatlashga murojaat qiling.")
    assert r.headers.get("X-Error-Code") == "LOT_INVARIANT_BROKEN"
    _sizmagan(r, pid, bid)
    assert _inv(pid, bid) == Decimal("9.000") and _lot_sum(pid) == Decimal("8.000")


def test_CORS_X_Error_Code_sarlavhasini_OCHADI(client, admin_headers, ctx, sup):
    """Electron renderer (Origin: null) nostandart sarlavhani faqat `expose` bo'lsa o'qiydi."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 55, D10).status_code == 200
    _buzish(pid, bid, 9)
    r = client.post("/api/v1/sales", headers={**admin_headers, "Origin": "null"}, json={
        "items": [{"product_id": pid, "qty": 1, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 10000, "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 409, r.text
    exposed = r.headers.get("access-control-expose-headers", "")
    assert "x-error-code" in exposed.lower(), dict(r.headers)


# ══ RUXSAT MATRITSASI ═══════════════════════════════════════════════════════
#   /sales, /sync/push  — kassa.sell           : kassir HA,  omborchi/menejer YO'Q
#   /returns            — qaytarishlar.create  : menejer HA, omborchi YO'Q
#   /lots/.../resolve   — ombor.edit           : omborchi HA, kassir/menejer YO'Q
#   ega (admin_headers) — hammasi.
#
# ⚠️  Ruxsatsiz rol partiya mantig'iga UMUMAN yetmasligi kerak (403, 409 emas):
#     darvoza chaqiruvlari SANALADI va nol bo'lishi shart. Ruxsatli ikki rol esa
#     BAYTMA-BAYT bir xil javob oladi — hech bir rol ko'proq ichki tafsilot ko'rmaydi.

def _sanovchi(monkeypatch, module, name):
    calls = []
    orig = getattr(module, name)

    def spy(*a, **k):
        calls.append(1)
        return orig(*a, **k)
    monkeypatch.setattr(module, name, spy)
    return calls


def _rad(r, perm, *ids):
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == f"Ruxsat yo'q: {perm}"
    assert "mos kelmadi" not in r.text
    _sizmagan(r, *ids)


def test_RUXSAT_SOTUV_kassa_sell(client, admin_headers, ctx, sup, monkeypatch):
    from app.core.deps import actor_branch
    from app.models.auth import Employee
    cid, bid = ctx
    kassir = _staff(client, admin_headers, "kassir")
    with _db() as db:
        emp = db.get(Employee, uuid.UUID(_CACHE["kassir"]["__id"]))
        assert actor_branch(emp, db).id == bid, "kassir boshqa filialga sotadi — sinov bo'sh"
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 10, 55, D10).status_code == 200
    _buzish(pid, bid, 9)
    calls = _sanovchi(monkeypatch, SI, "assert_ok")

    for role in ("omborchi", "menejer"):
        h = _staff(client, admin_headers, role)
        _rad(_sell(client, h, pid, 1), "kassa.sell", pid, bid)
        _rad(_replay(client, h, pid, 1), "kassa.sell", pid, bid)
    assert calls == [], "ruxsatsiz so'rov partiya darvozasiga yetib bordi"

    ra = _sell(client, admin_headers, pid, 1)
    rk = _sell(client, kassir, pid, 1)
    assert len(calls) == 2, "ruxsatli so'rovlar darvozaga yetmadi — matritsa bo'sh"
    for r in (ra, rk):
        assert r.status_code == 409, r.text
        assert r.headers.get("X-Error-Code") == "LOT_INVARIANT_BROKEN"
    assert ra.content == rk.content
    assert ra.json()["detail"] == SALE_409
    assert _inv(pid, bid) == Decimal("9.000") and _allocs(pid) == []


def test_RUXSAT_QAYTARISH_qaytarishlar_create(client, admin_headers, ctx, sup, monkeypatch):
    cid, bid = ctx
    pid, sid = _tracked_card_sale(client, admin_headers, sup)
    begona = uuid.uuid4()
    calls = []

    def buzuq(db, **kw):
        calls.append(1)
        return [f"qarz {begona}: returned_qty 1 != Σ dum 0"]
    monkeypatch.setattr(LR, "assert_caps", buzuq)

    _rad(_ret(client, _staff(client, admin_headers, "omborchi"), sid, pid, 1, method="card"),
         "qaytarishlar.create", begona, pid, sid)
    assert calls == [], "ruxsatsiz so'rov qaytarish darvozasiga yetib bordi"

    ra = _ret(client, admin_headers, sid, pid, 1, method="card")
    rm = _ret(client, _staff(client, admin_headers, "menejer"), sid, pid, 1, method="card")
    assert len(calls) == 2, "ruxsatli so'rovlar darvozaga yetmadi — matritsa bo'sh"
    for r in (ra, rm):
        assert r.status_code == 409, r.text
        assert r.headers.get("X-Error-Code") == "LOT_RETURN_CAPS_VIOLATED"
        _sizmagan(r, begona)
    assert ra.content == rm.content
    assert ra.json()["detail"] == RETURN_409
    assert _return_count(sid) == 0


def test_RUXSAT_QARZNI_YOPISH_ombor_edit(client, admin_headers, ctx, sup, monkeypatch):
    cid, bid = ctx
    pid, sf, lot = _shortfall(client, admin_headers, sup, bid)
    _buzish(pid, bid, 5)              # 5 != 10 − 4
    calls = _sanovchi(monkeypatch, SI, "assert_ok")

    for role in ("kassir", "menejer"):
        _rad(_resolve(client, _staff(client, admin_headers, role), sf.id, batch=lot.id, qty=2),
             "ombor.edit", pid, bid, sf.id)
    assert calls == [], "ruxsatsiz so'rov yopish darvozasiga yetib bordi"

    ra = _resolve(client, admin_headers, sf.id, batch=lot.id, qty=2)
    ro = _resolve(client, _staff(client, admin_headers, "omborchi"), sf.id, batch=lot.id, qty=2)
    assert len(calls) == 2, "ruxsatli so'rovlar darvozaga yetmadi — matritsa bo'sh"
    for r in (ra, ro):
        assert r.status_code == 409, r.text
        assert r.headers.get("X-Error-Code") == "LOT_RESOLVE_INVARIANT_BROKEN"
        _sizmagan(r, pid, bid, sf.id)
    assert ra.content == ro.content
    assert ra.json()["detail"] == RESOLVE_409
    assert _resolved(sf.id) == Decimal("0.000") and _events(sf.id) == 0
