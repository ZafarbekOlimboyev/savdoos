# -*- coding: utf-8 -*-
"""`POST /api/v1/historical/events` — IMTIYOZLI tarixiy bajarish sirti.

⚠️  BU FAYLDA BIZNES HODISASI ORM BILAN YOZILMAYDI. ORM FAQAT sahna qurishda
    (do'kon/filial/xodim/mahsulot/mijoz/ta'minotchi). Har bir biznes hodisasi
    HTTP orqali, kanonik yozuvchidan o'tadi — sirtning ma'nosi aynan shu.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime.now(timezone.utc)
#  Tarixiy kun: bugundan ancha oldin, lekin `/sync/push` ning 60 kunlik
#  oynasidan ham NARIDA — ya'ni bu yo'l bilan yozib bo'lmaydigan chuqurlik.
D0 = (NOW - timedelta(days=200)).replace(hour=8, minute=0, second=0, microsecond=0)
TZ = "Asia/Bishkek"
_VK = {"X-Vendor-Key": "test-vendor-key"}


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


# ══ SAHNA ════════════════════════════════════════════════════════════════
def _sahna(*, code_prefix="demo", filial_soni=2):
    """Demo do'kon: A filiali (aktor BIRIKTIRILGAN) va B filiali (biriktirilmagan).

    ⚠️  IKKI FILIAL ATAYLAB. 7-darvoza `actor_branch(emp, db).id == branch_id`
        TENGLIGINI talab qiladi. Bitta filialli do'konda `actor_branch` ning
        2-bosqichi (fail-open: «biriktirilmagan bo'lsa birinchi faol filial»)
        baribir o'sha filialni qaytarardi va darvoza TEKSHIRILMAGAN bo'lib
        ko'rinardi. B filiali — darvozani haqiqatan sinaydigan yo'l.
    """
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Product, Unit
    from app.models.customers import Customer
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="D3 tarixiy",
                       code=f"{code_prefix}-d3-{uuid.uuid4().hex[:6]}",
                       currency="KGS")
        db.add(comp)
        db.flush()
        a = Branch(id=uuid.uuid4(), company_id=comp.id, name="A", code="A01",
                   timezone=TZ, is_active=True, created_at=NOW - timedelta(days=400))
        db.add(a)
        b = None
        if filial_soni > 1:
            b = Branch(id=uuid.uuid4(), company_id=comp.id, name="B", code="B01",
                       timezone=TZ, is_active=True,
                       created_at=NOW - timedelta(days=300))
            db.add(b)
        db.flush()
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                       full_name="D3 aktor",
                       phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        db.flush()
        #  Aktor AYNAN A filialiga biriktiriladi (1-bosqich deterministik bo'lsin).
        db.add(EmployeeBranch(employee_id=emp.id, branch_id=a.id))
        #  ⚠️  IKKINCHI AKTOR — B filialiga. Filial-konflikt testini boshqa yo'l
        #      bilan qurib bo'lmaydi: 7-darvoza `actor_branch` TENGLIGINI talab
        #      qiladi, `actor_branch` esa ikki biriktirilgan filialdan eng
        #      eskisini (`created_at`) tanlaydi — ya'ni ayni aktor bilan B ga
        #      yozib bo'lmaydi.
        emp2 = None
        if b is not None:
            emp2 = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                            full_name="D3 aktor B",
                            phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                            status=EmployeeStatus.active, sec_epoch=0)
            db.add(emp2)
            db.flush()
            db.add(EmployeeBranch(employee_id=emp2.id, branch_id=b.id))
        unit = db.query(Unit).filter_by(code="dona").one()
        prod = Product(id=uuid.uuid4(), company_id=comp.id, name="D3 tovar",
                       article_code="D3-" + uuid.uuid4().hex[:10],
                       sku=uuid.uuid4().hex[:8], unit_id=unit.id,
                       base_buy_price=50, base_sell_price=100, tax_rate=0,
                       track_lots=False)
        db.add(prod)
        db.flush()
        #  ⚠️  QOLDIQ ORM BILAN QO'YILADI, API BILAN EMAS. Mahsulotni API orqali
        #      `stock > 0` bilan yaratish BUGUNGI sanali harakat yozadi va
        #      xronologiya gardi keyingi TARIXIY sanoqni rad etardi
        #      (`tests/test_h3a_historical_writers.py` dagi bajaruvchi sharti).
        db.add(Inventory(product_id=prod.id, branch_id=a.id, qty=50, min_qty=0,
                         updated_at=NOW - timedelta(days=400)))
        cust = Customer(id=uuid.uuid4(), company_id=comp.id,
                        code="M" + uuid.uuid4().hex[:10],   # NOT NULL + UNIQUE(company,code)
                        full_name="D3 mijoz",
                        phone=f"+9984{uuid.uuid4().int % 10**7:07d}",
                        credit_balance=50000, credit_limit=1_000_000)
        sup = Supplier(id=uuid.uuid4(), company_id=comp.id, name="D3 ta'minotchi")
        db.add_all([cust, sup])
        db.commit()
        return {"cid": str(comp.id), "a": str(a.id),
                "b": (str(b.id) if b else None), "eid": str(emp.id),
                "eid_b": (str(emp2.id) if emp2 else None),
                "pid": str(prod.id), "cust": str(cust.id), "sup": str(sup.id),
                "code": comp.code, "plan": f"plan-{uuid.uuid4().hex[:8]}"}


def _env(s, *, event_type, payload, seq=None, at=None, branch=None, actor=None,
         plan=None, plan_start=False, **kw):
    return {"company_id": s["cid"], "branch_id": branch or s["a"],
            "actor_employee_id": actor or s["eid"],
            "plan_id": plan or s["plan"], "plan_start": plan_start,
            "occurred_at": (at or D0).isoformat(),
            "event_seq": seq or [uuid.uuid4().hex[:8]],
            "event": {"event_type": event_type, "payload": payload}, **kw}


def _post(client, env, headers=None):
    return client.post("/api/v1/historical/events",
                       headers=_VK if headers is None else headers, json=env)


# ══ 1. QUVUR UCHIDAN-UCHIGA ══════════════════════════════════════════════

def test_SMENA_ochish_TARIXIY_vaqt_bilan(client):
    """Eng oddiy hodisa: smena ochish. Vaqt AYNAN `occurred_at` bo'lsin."""
    from app.models.shifts import Shift
    s = _sahna()
    r = _post(client, _env(s, event_type="shift_open",
                           payload={"opening_cash": 1000}, seq=["d1", "open"]))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["duplicate"] is False, j
    assert j["event_type"] == "shift_open" and j["result_type"] == "shift"
    with _db() as db:
        sh = db.get(Shift, uuid.UUID(j["result_id"]))
        assert sh is not None
        got = sh.opened_at if sh.opened_at.tzinfo else sh.opened_at.replace(tzinfo=timezone.utc)
        assert got == D0, f"opened_at={got}, kutilgan={D0}"
        assert sh.branch_id == uuid.UUID(s["a"])
        assert sh.cashier_id == uuid.UUID(s["eid"])
        #  Kalit qatorga yozilgan bo'lsin — tiklanish zondi shunga tayanadi.
        assert sh.client_uuid is not None


def test_SMENA_ochish_va_YOPISH_zanjiri(client):
    """Ochish -> yopish. `closed_at` tarixiy lahzaga teng (tiklanish guvohi)."""
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = _sahna()
    r1 = _post(client, _env(s, event_type="shift_open",
                            payload={"opening_cash": 1000}, seq=["d1", "open"]))
    assert r1.status_code == 200, r1.text
    sid = r1.json()["result_id"]
    yopilish = D0 + timedelta(hours=9)
    r2 = _post(client, _env(s, event_type="shift_close", at=yopilish,
                            payload={"shift_id": sid, "counted_cash": 1000},
                            seq=["d1", "close"]))
    assert r2.status_code == 200, r2.text
    with _db() as db:
        sh = db.get(Shift, uuid.UUID(sid))
        assert sh.status == ShiftStatus.closed
        got = sh.closed_at if sh.closed_at.tzinfo else sh.closed_at.replace(tzinfo=timezone.utc)
        assert got == yopilish, (
            f"closed_at={got}, kutilgan={yopilish} — bu tiklanishning VAQT "
            f"GUVOHI, u buzilsa `shift_close` tiklanmaydi")


def test_SOTUV_tarixiy_smenada(client):
    """Sotuv: tarixiy smena ochiq, sotuv shu smenaga va shu vaqtga tushadi."""
    from app.models.sales import Sale
    s = _sahna()
    assert _post(client, _env(s, event_type="shift_open",
                              payload={"opening_cash": 0},
                              seq=["d1", "open"])).status_code == 200
    sotuv_vaqti = D0 + timedelta(hours=3)
    r = _post(client, _env(
        s, event_type="sale", at=sotuv_vaqti, seq=["d1", "sale", "01"],
        payload={"items": [{"product_id": s["pid"], "qty": 2, "price": 100}],
                 "payments": [{"method": "cash", "amount": 200}]}))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["result_type"] == "sale"
    with _db() as db:
        sale = db.get(Sale, uuid.UUID(j["result_id"]))
        got = sale.sold_at if sale.sold_at.tzinfo else sale.sold_at.replace(tzinfo=timezone.utc)
        assert got == sotuv_vaqti, f"sold_at={got}, kutilgan={sotuv_vaqti}"
        assert sale.branch_id == uuid.UUID(s["a"])
        #  Kalit = `event_key`, ya'ni SERVER qo'ygan (mijoz bermaydi).
        assert sale.client_uuid is not None


def test_HISOBDAN_CHIQARISH_va_KASSA_amali(client):
    """Yana ikki hodisa turi — dispatch jadvali to'g'ri ulangani."""
    s = _sahna()
    assert _post(client, _env(s, event_type="shift_open",
                              payload={"opening_cash": 5000},
                              seq=["d1", "open"])).status_code == 200
    r = _post(client, _env(
        s, event_type="writeoff", at=D0 + timedelta(hours=1),
        seq=["d1", "writeoff", "01"],
        payload={"product_id": s["pid"], "qty": 3, "reason": "brak",
                 "branch_id": s["a"]}))
    assert r.status_code == 200, r.text
    assert r.json()["result_type"] == "stock_movement"

    r = _post(client, _env(
        s, event_type="cash_payin", at=D0 + timedelta(hours=2),
        seq=["d1", "payin", "01"],
        payload={"type": "payin", "amount": 500, "reason": "kirim"}))
    assert r.status_code == 200, r.text
    assert r.json()["result_type"] == "cash_movement"
