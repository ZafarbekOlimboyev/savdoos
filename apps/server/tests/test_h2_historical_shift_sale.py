# -*- coding: utf-8 -*-
"""H2 — TARIXIY SMENA + SOTUV: bitta biznes kuni kanonik servislar bilan.

Doira ATAYLAB tor: tarixiy smena ochish -> tarixiy sotuvlar -> tarixiy yopish.
Xarid, qabul, qaytarish, sanoq, hisobdan chiqarish, kassa amallari BU YERDA EMAS.

Ega qo'ygan 13 qabul mezoni, har biri alohida test:
   1. normal smena ochish/yopish HAMON hozirgi vaqt;
   2. normal `/sales` da ixtiyoriy tarixiy yozuv YO'Q;
   3. demo tenantda tarixiy kontekst bilan >120 kun oldingi smena ochiladi;
   4. shu tarixiy smena ichida sotuv;
   5. `sale.sold_at` — TARIXIY vaqt;
   6. sotuv smena bilan TO'G'RI bog'langan;
   7. smena tarixiy yopiladi;
   8. hisobot sotuvni SHU biznes kunida ko'radi;
   9. ayni deterministik hodisani qayta yurgizish DUBLIKAT yaratmaydi;
  10. tashqi chiqish effekti = 0;
  11. miqdor kontrakti buzilmaydi;
  12. KGS valyuta surati to'g'ri.
(13-mezon — to'liq exact-SHA CI — bu fayldan tashqarida.)

⚠️  TO'G'RIDAN ORM BILAN Shift/CashMovement YOZILMAYDI. Smena faqat
    `services/shifts.open_shift_svc` / `close_shift_svc`, sotuv faqat
    `services/sales.create_sale` orqali. Sahna qurish uchun ORM FAQAT
    do'kon/filial/xodim/mahsulot yaratishda ishlatiladi (biznes hodisa emas).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services import historical as H

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
PLAN = "h2-plan-1"
#  >120 kun — `/sync/push` 60-kunlik klampidan ATAYLAB tashqarida: bu yo'l
#  u klampga TEGMAYDI va unga tayanmaydi.
DEPTH = 130


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _aw(dt):
    """SQLite datetime'ni NAIVE qaytaradi — solishtirishdan oldin UTC ga keltiramiz.

    ⚠️  Bu TEST harness masalasi, ishlab chiqarish nuqsoni EMAS: Postgres
        `timestamptz` ni aware qaytaradi, SQLite esa naive. Normalizatorsiz
        assertion'lar mahalliy to'plamda TypeError bilan qulaydi.
    """
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _demo(currency: str = "KGS", code_prefix: str = "demo"):
    """Demo tenant: do'kon + filial + kassir + token. ORM FAQAT sahna uchun."""
    from app.core.security import create_access_token
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="H2 demo",
                       code=f"{code_prefix}-h2-{uuid.uuid4().hex[:6]}", currency=currency)
        db.add(comp)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01",
                    timezone=TZ, is_active=True, created_at=NOW - timedelta(days=400))
        db.add(br)
        db.flush()
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                       full_name="H2 kassir", phone=f"+9989{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        db.commit()
        tok = create_access_token(str(emp.id), {"role": "ega", "company_id": str(comp.id), "sv": 0})
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


def _mahsulot(d, unit_code="dona", qty=100):
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    with _db() as db:
        u = db.query(Unit).filter_by(code=unit_code).one()
        p = Product(id=uuid.uuid4(), company_id=d["cid"], name=f"H2 {unit_code} {uuid.uuid4().hex[:5]}",
                    article_code="H2-" + uuid.uuid4().hex[:10], sku=uuid.uuid4().hex[:8],
                    unit_id=u.id, base_buy_price=500, base_sell_price=1000, tax_rate=0)
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, branch_id=d["bid"], qty=Decimal(str(qty)),
                         min_qty=0, updated_at=NOW))
        db.commit()
        return p.id


def _no_push(monkeypatch):
    """Tashqi chiqishni KUZATADI (bo'g'ishni emas — chaqiruvni sanaydi)."""
    from app.services import push
    sent: list = []
    monkeypatch.setattr(push, "send_ex", lambda *a, **k: (sent.append(a), (0, []))[1])

    class _S:
        fcm_enabled = True
    monkeypatch.setattr(push, "settings", _S())
    return sent


# ══ TARIXIY KUNNI BAJARUVCHI (H2 ning asosiy oqimi) ═══════════════════════
def _historical_day(d, pid, *, day_offset: int, n_sales: int = 2, plan: str = PLAN):
    """Bitta tarixiy biznes kuni: ochish -> sotuvlar -> yopish.

    FAQAT kanonik servislar. Har hodisaning `client_uuid` i H1 `event_key` dan
    (deterministik), ya'ni qayta yurgizish dublikat yaratmaydi.
    """
    from app.schemas.sales import SaleCreate, SaleItemIn
    from app.services.sales import create_sale
    from app.services.shifts import close_shift_svc, open_shift_svc

    class _Open:
        opening_cash = 100000.0
        terminal_id = None
        till_id = None

    class _Close:
        counted_cash = 0.0

    day = (NOW - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    t_open = day + timedelta(hours=9)
    dkey = f"d-{day_offset:03d}"
    out = {"sales": []}

    with _db() as db:
        emp = db.get(type(_emp(d)), d["eid"])
        comp = _company(d)
        with H.enter(db, comp, plan_id=plan, instant=t_open) as ctx:
            sh = open_shift_svc(_Open(), emp, db, at=t_open,
                                client_uuid=ctx.key(dkey, "shift", "open"))
            out["shift_id"] = sh["id"]
            out["opened_at"] = sh["opened_at"]

        for i in range(n_sales):
            t_sale = day + timedelta(hours=10 + i, minutes=17)
            with H.enter(db, comp, plan_id=plan, instant=t_sale) as ctx:
                sale = create_sale(db, emp, SaleCreate(
                    items=[SaleItemIn(product_id=pid, qty=2, unit_price=1000)],
                    payment_method="cash", given_amount=2000,
                    client_uuid=ctx.key(dkey, "sale", f"{i:02d}")), at=t_sale)
                out["sales"].append({"id": str(sale.id), "sold_at": sale.sold_at,
                                     "shift_id": str(sale.shift_id) if sale.shift_id else None,
                                     "currency": getattr(sale, "currency", None)})

        # ⚠️  YOPISHDA IDEMPOTENTLIK KALITI YO'Q — H2 TOPILMASI.
        #     `close_shift_svc` allaqachon yopilgan smenaga 400 beradi («Smena
        #     allaqachon yopilgan») va bu NORMAL yo'l uchun TO'G'RI gard (ikki
        #     marta yopish taqiqlangan) — uni BO'SHATMAYMIZ. Shu bois qayta
        #     yurgizishda holatni BAJARUVCHI tekshiradi: smena allaqachon
        #     yopilgan bo'lsa, o'sha kun ALLAQACHON yozilgan.
        from app.models.enums import ShiftStatus as _SS
        from app.models.shifts import Shift as _Sh
        _cur = db.get(_Sh, uuid.UUID(out["shift_id"]))
        if _cur is not None and _cur.status == _SS.open:
            t_close = day + timedelta(hours=18)
            with H.enter(db, comp, plan_id=plan, instant=t_close):
                out["close"] = close_shift_svc(uuid.UUID(out["shift_id"]), _Close(), emp, db,
                                               at=t_close)
            out["closed_at"] = t_close
        else:
            out["close"] = {"skipped": "allaqachon yopilgan (qayta yurgizish)"}
    return out


# ══ 1) NORMAL smena — HOZIRGI vaqt ═════════════════════════════════════════
def test_01_normal_smena_HOZIRGI_vaqt(client):
    """Marshrut `at` ni UZATMAYDI — semantika o'zgarmagan."""
    from app.models.shifts import Shift
    d = _demo()
    t0 = datetime.now(timezone.utc)
    r = client.post("/api/v1/shifts/open", headers=d["H"], json={"opening_cash": 1000})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    with _db() as db:
        sh = db.get(Shift, uuid.UUID(sid))
        assert abs((_aw(sh.opened_at) - t0).total_seconds()) < 120, f"opened_at={sh.opened_at}"
        assert sh.client_uuid is None, "normal yo'l client_uuid yozdi"
    rc = client.post(f"/api/v1/shifts/{sid}/close", headers=d["H"], json={"counted_cash": 1000})
    assert rc.status_code == 200, rc.text
    with _db() as db:
        sh = db.get(Shift, uuid.UUID(sid))
        assert abs((_aw(sh.closed_at) - t0).total_seconds()) < 180, f"closed_at={sh.closed_at}"


def test_01b_normal_smena_sxemasida_VAQT_maydoni_YO_Q(client):
    """`OpenShift`/`CloseShift` ga birorta vaqt maydoni QO'SHILMAGAN."""
    from app.api.v1.shifts import CloseShift, OpenShift
    for M in (OpenShift, CloseShift):
        keys = set(M.model_fields.keys())
        assert not (keys & {"at", "opened_at", "closed_at", "occurred_at", "historical"}), \
            f"{M.__name__} ga vaqt maydoni qo'shilgan: {keys}"


# ══ 2) NORMAL /sales — ixtiyoriy tarixiy yozuv YO'Q ═════════════════════════
def test_02_normal_sales_TARIXIY_yozuvga_RUXSAT_BERMAYDI(client):
    """`sold_at` tanada kelsa ham JIM e'tiborsiz qoladi (xulq O'ZGARMAGAN)."""
    from app.models.sales import Sale
    d = _demo()
    pid = _mahsulot(d)
    eski = (NOW - timedelta(days=DEPTH)).isoformat()
    t0 = datetime.now(timezone.utc)
    r = client.post("/api/v1/sales", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 1, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 1000,
        "client_uuid": str(uuid.uuid4()), "sold_at": eski})
    assert r.status_code == 200, r.text
    with _db() as db:
        s = db.get(Sale, uuid.UUID(r.json()["id"]))
        assert abs((_aw(s.sold_at) - t0).total_seconds()) < 120, \
            f"normal /sales TARIXIY yozdi: {s.sold_at}"


def test_02b_servis_kontekstSIZ_at_ni_RAD_etadi(client):
    """⚠️  `at` ning O'ZI yetarli EMAS — kontekst SHART (fail-closed)."""
    d = _demo()

    class _Open:
        opening_cash = 0.0
        terminal_id = None
        till_id = None

    from app.services.shifts import open_shift_svc
    with _db() as db:
        with pytest.raises(RuntimeError, match="kontekst"):
            open_shift_svc(_Open(), _emp(d), db, at=NOW - timedelta(days=DEPTH))


def test_02c_BOSHQA_dokon_konteksti_RAD(client):
    """Bir do'kon kontekstida turib boshqasiga tarixiy yozib bo'lmaydi."""
    d1, d2 = _demo(), _demo()

    class _Open:
        opening_cash = 0.0
        terminal_id = None
        till_id = None

    from app.services.shifts import open_shift_svc
    t = NOW - timedelta(days=DEPTH)
    with _db() as db:
        with H.enter(db, _company(d1), plan_id=PLAN, instant=t):
            with pytest.raises(RuntimeError, match="BOSHQA do'kon"):
                open_shift_svc(_Open(), _emp(d2), db, at=t)


def test_02d_NORMAL_tenant_tarixiy_qobiliyat_OLMAYDI(client):
    """Demo bo'lmagan do'kon kontekstga KIRA OLMAYDI — ya'ni `at` ham mumkin emas."""
    from fastapi import HTTPException
    d = _demo(code_prefix="fayzanx")      # demo/test prefiksi YO'Q
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            with H.enter(db, _company(d), plan_id=PLAN, instant=NOW - timedelta(days=DEPTH)):
                pytest.fail("darvoza o'tkazmasligi kerak edi")
    assert e.value.status_code == 400


# ══ 3..7) TARIXIY KUN: ochish -> sotuvlar -> yopish ═══════════════════════════
def test_03_07_tarixiy_kun_TOLIQ(client, monkeypatch):
    from app.models.sales import Sale
    from app.models.shifts import Shift
    sent = _no_push(monkeypatch)
    d = _demo(currency="KGS")
    pid = _mahsulot(d)
    res = _historical_day(d, pid, day_offset=DEPTH, n_sales=2)

    kutilgan_kun = (NOW - timedelta(days=DEPTH)).date()
    with _db() as db:
        sh = db.get(Shift, uuid.UUID(res["shift_id"]))
        # 3) >120 kun oldingi smena
        assert sh.opened_at.date() == kutilgan_kun, f"opened_at={sh.opened_at}"
        assert (NOW - _aw(sh.opened_at)).days >= 120, (
            f"chuqurlik {(NOW - _aw(sh.opened_at)).days} kun")
        # 7) tarixiy yopilgan
        from app.models.enums import ShiftStatus
        assert sh.status == ShiftStatus.closed, f"status={sh.status}"
        assert sh.closed_at.date() == kutilgan_kun, f"closed_at={sh.closed_at}"
        assert _aw(sh.opened_at) < _aw(sh.closed_at)

        sales = [db.get(Sale, uuid.UUID(s["id"])) for s in res["sales"]]
        # 4) smena ichida sotuv bor
        assert len(sales) == 2
        for s in sales:
            # 5) sold_at TARIXIY
            assert s.sold_at.date() == kutilgan_kun, f"sold_at={s.sold_at}"
            # 6) smena bilan TO'G'RI bog'langan
            assert s.shift_id == sh.id, f"shift_id={s.shift_id} != {sh.id}"
            # sotuv smena oynasi ICHIDA
            assert _aw(sh.opened_at) <= _aw(s.sold_at) <= _aw(sh.closed_at)
            # 12) KGS valyuta surati
            assert (s.currency or "").upper() == "KGS", f"currency={s.currency!r}"

    # 10) tashqi chiqish = 0
    assert sent == [], f"tarixiy kunda tashqi chiqish bo'ldi: {len(sent)}"


# ══ 8) HISOBOT shu biznes kunida ko'radi ═════════════════════════════════════
def test_08_hisobot_SHU_biznes_kunida_koradi(client, monkeypatch):
    _no_push(monkeypatch)
    d = _demo(currency="KGS")
    pid = _mahsulot(d)
    res = _historical_day(d, pid, day_offset=DEPTH, n_sales=2)
    kun = (NOW - timedelta(days=DEPTH)).date().isoformat()

    r = client.get(f"/api/v1/reports/pnl?from_date={kun}&to_date={kun}", headers=d["H"])
    assert r.status_code == 200, r.text
    #  ⚠️  KALIT `gross` (yalpi tushum). `revenue` kaliti javobda YO'Q — faqat
    #      `revenue_known_cost` kabi taqsimlar bor; `.get("revenue")` None berib,
    #      assertion YOLG'ON qulardi.
    j = r.json()
    assert "gross" in j, f"hisobot javobida `gross` yo'q: {sorted(j)[:12]}"
    assert float(j["gross"]) > 0, f"hisobot {kun} da sotuvni KO'RMADI: {r.text[:300]}"

    # NAZORAT: BUGUNGI kunda bu sotuvlar KO'RINMASLIGI kerak
    bugun = NOW.date().isoformat()
    r2 = client.get(f"/api/v1/reports/pnl?from_date={bugun}&to_date={bugun}", headers=d["H"])
    assert r2.status_code == 200, r2.text
    assert float(r2.json()["gross"]) == 0,         f"tarixiy sotuv BUGUNGI hisobotda ko'rindi: {r2.text[:300]}"


# ══ 9) DETERMINISTIK QAYTA YURGIZISH — dublikat YO'Q ═════════════════════════
def test_09_qayta_yurgizish_DUBLIKAT_yaratmaydi(client, monkeypatch):
    from app.models.sales import Sale
    from app.models.shifts import Shift
    _no_push(monkeypatch)
    d = _demo(currency="KGS")
    pid = _mahsulot(d)

    r1 = _historical_day(d, pid, day_offset=DEPTH, n_sales=2)
    with _db() as db:
        n_sh1 = db.query(Shift).filter(Shift.cashier_id == d["eid"]).count()
        n_sl1 = db.query(Sale).filter(Sale.company_id == d["cid"]).count()

    r2 = _historical_day(d, pid, day_offset=DEPTH, n_sales=2)      # AYNI reja, AYNI kalitlar
    with _db() as db:
        n_sh2 = db.query(Shift).filter(Shift.cashier_id == d["eid"]).count()
        n_sl2 = db.query(Sale).filter(Sale.company_id == d["cid"]).count()

    assert n_sh2 == n_sh1 == 1, f"smena DUBLIKAT: {n_sh1} -> {n_sh2}"
    assert n_sl2 == n_sl1 == 2, f"sotuv DUBLIKAT: {n_sl1} -> {n_sl2}"
    assert r2["shift_id"] == r1["shift_id"], "qayta yurgizish BOSHQA smena qaytardi"
    assert [s["id"] for s in r2["sales"]] == [s["id"] for s in r1["sales"]], \
        "qayta yurgizish BOSHQA sotuv id'lari qaytardi"


# ══ 11) MIQDOR KONTRAKTI buzilmaydi ══════════════════════════════════════════
def test_11_miqdor_kontrakti_TARIXIY_yozuvda_HAM_kuchda(client, monkeypatch):
    """Tarixiy kontekst miqdor darvozasini CHETLAB O'TMAYDI."""
    from fastapi import HTTPException

    from app.schemas.sales import SaleCreate, SaleItemIn
    from app.services.sales import create_sale
    from app.services.shifts import open_shift_svc
    _no_push(monkeypatch)
    d = _demo(currency="KGS")
    pid_dona = _mahsulot(d, "dona")
    pid_kg = _mahsulot(d, "kg")

    class _Open:
        opening_cash = 0.0
        terminal_id = None
        till_id = None

    t = (NOW - timedelta(days=DEPTH)).replace(hour=9, minute=0, second=0, microsecond=0)
    with _db() as db:
        comp, emp = _company(d), _emp(d)
        with H.enter(db, comp, plan_id=PLAN, instant=t) as ctx:
            open_shift_svc(_Open(), emp, db, at=t, client_uuid=ctx.key("d", "shift", "open"))
            # `0.5 dona` — RAD
            with pytest.raises(HTTPException) as e:
                create_sale(db, emp, SaleCreate(
                    items=[SaleItemIn(product_id=pid_dona, qty=0.5, unit_price=1000)],
                    payment_method="cash", given_amount=1000,
                    client_uuid=ctx.key("d", "sale", "bad")), at=t)
            assert e.value.status_code == 400
            assert "butun miqdorda" in str(e.value.detail)
        # `0.5 kg` — O'TADI (kasrli birlik buzilmagan)
        t2 = t + timedelta(hours=1)
        with H.enter(db, comp, plan_id=PLAN, instant=t2) as ctx:
            s = create_sale(db, emp, SaleCreate(
                items=[SaleItemIn(product_id=pid_kg, qty=0.5, unit_price=1000)],
                payment_method="cash", given_amount=1000,
                client_uuid=ctx.key("d", "sale", "kg")), at=t2)
            assert s.sold_at.date() == t2.date()


# ══ 12) VALYUTA surati — UZS tenantda UZS ════════════════════════════════════
def test_12_valyuta_surati_TENANT_valyutasidan(client, monkeypatch):
    """Nazorat tomoni: KGS emas, UZS tenantda sotuv UZS bo'ladi."""
    from app.models.sales import Sale
    _no_push(monkeypatch)
    d = _demo(currency="UZS")
    pid = _mahsulot(d)
    res = _historical_day(d, pid, day_offset=DEPTH, n_sales=1, plan="h2-uzs")
    with _db() as db:
        s = db.get(Sale, uuid.UUID(res["sales"][0]["id"]))
        assert (s.currency or "").upper() == "UZS", f"currency={s.currency!r}"


# ══ T0 sharti H2 da ham kuchda ═══════════════════════════════════════════════
def test_T0_belgilangan_demo_tenant_RAD(client):
    """H1 darvozasi H2 yo'lida ham ishlaydi: T0 bor -> kontekst ochilmaydi."""
    from fastapi import HTTPException

    from app.models.settings import Setting
    d = _demo()
    with _db() as db:
        db.add(Setting(id=uuid.uuid4(), company_id=d["cid"], branch_id=None, key="cash",
                       value={"cutover_at": (NOW - timedelta(days=200)).isoformat()}))
        db.commit()
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            with H.enter(db, _company(d), plan_id=PLAN, instant=NOW - timedelta(days=DEPTH)):
                pytest.fail("T0 bor — o'tmasligi kerak")
    assert e.value.status_code == 409 and "T0" in e.value.detail
