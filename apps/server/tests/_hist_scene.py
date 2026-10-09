# -*- coding: utf-8 -*-
"""D3 tarixiy sirt testlari uchun UMUMIY sahna. Test fayli EMAS (`_` prefiksi).

⚠️  NEGA ALOHIDA MODUL. Uch test fayli ayni sahnani ishlatadi va sahnani
    test modulidan import qilish uni IKKINCHI instansiya sifatida yuklardi
    (`tests/` paket emas — `__init__.py` YO'Q, qarang `conftest-soya` darsi):
    modul darajasidagi `NOW`/`D0` ikki marta hisoblanib, vaqt taqqoslashlari
    sababsiz siljiydi.

⚠️  BIZNES HODISASI BU YERDA ORM BILAN YOZILMAYDI. ORM FAQAT sahna qurish
    uchun (do'kon/filial/xodim/mahsulot/mijoz/ta'minotchi) — har bir biznes
    hodisasi HTTP orqali kanonik yozuvchidan o'tadi.
"""
import uuid
from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)
#  Tarixiy kun: bugundan ancha oldin va `/sync/push` ning 60 kunlik oynasidan
#  ham NARIDA — ya'ni oddiy kassir yo'li bilan yozib bo'lmaydigan chuqurlik.
D0 = (NOW - timedelta(days=200)).replace(hour=8, minute=0, second=0, microsecond=0)
TZ = "Asia/Bishkek"
VK = {"X-Vendor-Key": "test-vendor-key"}


def db_():
    from app.db.session import SessionLocal
    return SessionLocal()


def sahna(*, code_prefix="demo", filial_soni=2):
    """Demo do'kon: A filiali (aktor biriktirilgan) + B filiali (boshqa aktor).

    ⚠️  IKKI FILIAL ATAYLAB. 7-darvoza `actor_branch(emp, db).id == branch_id`
        TENGLIGINI talab qiladi. Bitta filialli do'konda `actor_branch` ning
        2-bosqichi (fail-open: «biriktirilmagan bo'lsa birinchi faol filial»)
        baribir o'sha filialni qaytarardi va darvoza tekshirilmagan bo'lib
        ko'rinardi.

    ⚠️  IKKINCHI AKTOR ham ATAYLAB: filial-konflikt (Ruling 4) testini boshqa
        yo'l bilan qurib bo'lmaydi, chunki `actor_branch` bir aktorning ikki
        biriktirilgan filialidan eng ESKISINI tanlaydi.
    """
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.catalog import Product, Unit
    from app.models.customers import Customer
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    with db_() as db:
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

        def _emp(nom):
            e = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                         full_name=nom,
                         phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                         status=EmployeeStatus.active, sec_epoch=0)
            db.add(e)
            db.flush()
            return e

        emp = _emp("D3 aktor A")
        db.add(EmployeeBranch(employee_id=emp.id, branch_id=a.id))
        emp2 = None
        if b is not None:
            emp2 = _emp("D3 aktor B")
            db.add(EmployeeBranch(employee_id=emp2.id, branch_id=b.id))

        unit = db.query(Unit).filter_by(code="dona").one()
        prod = Product(id=uuid.uuid4(), company_id=comp.id, name="D3 tovar",
                       article_code="D3-" + uuid.uuid4().hex[:10],
                       sku=uuid.uuid4().hex[:8], unit_id=unit.id,
                       base_buy_price=50, base_sell_price=100, tax_rate=0,
                       track_lots=False)
        db.add(prod)
        db.flush()
        #  ⚠️  QOLDIQ ORM BILAN. Mahsulotni API orqali `stock > 0` bilan
        #      yaratish BUGUNGI sanali harakat yozadi va xronologiya gardi
        #      keyingi TARIXIY sanoqni rad etardi (bajaruvchi sharti).
        db.add(Inventory(product_id=prod.id, branch_id=a.id, qty=50, min_qty=0,
                         updated_at=NOW - timedelta(days=400)))
        cust = Customer(id=uuid.uuid4(), company_id=comp.id,
                        code="M" + uuid.uuid4().hex[:10],
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


def env(s, *, event_type, payload, seq=None, at=None, branch=None, actor=None,
        plan=None, plan_start=False, **kw):
    return {"company_id": s["cid"], "branch_id": branch or s["a"],
            "actor_employee_id": actor or s["eid"],
            "plan_id": plan or s["plan"], "plan_start": plan_start,
            "occurred_at": (at or D0).isoformat(),
            "event_seq": seq or [uuid.uuid4().hex[:8]],
            "event": {"event_type": event_type, "payload": payload}, **kw}


def post(client, envelope, headers=None):
    return client.post("/api/v1/historical/events",
                       headers=VK if headers is None else headers, json=envelope)


def smena_ochish(client, s, *, at=None, opening=0, seq=("d1", "open")):
    """Tarixiy OCHIQ smena — kassa amali va sotuv shuni TALAB qiladi."""
    r = post(client, env(s, event_type="shift_open", at=at,
                         payload={"opening_cash": opening}, seq=list(seq)))
    assert r.status_code == 200, r.text
    return r.json()["result_id"]


def yozuv_yoq(cid):
    """Shu do'konda BIRORTA biznes qatori yo'qligini tasdiqlaydi."""
    from app.models.org import Branch
    from app.models.sales import Sale
    from app.models.shifts import Shift
    with db_() as db:
        assert db.query(Sale.id).filter(
            Sale.company_id == uuid.UUID(cid)).first() is None
        brs = [x.id for x in db.query(Branch).filter(
            Branch.company_id == uuid.UUID(cid)).all()]
        assert db.query(Shift.id).filter(Shift.branch_id.in_(brs)).first() is None


def jurnal(cid, *, event_key=None):
    """Jurnal qatorlari (yoki bittasi) — FRESH sessiyada o'qiladi."""
    from app.models.historical import HistoricalPlanEvent as HPE
    with db_() as db:
        q = db.query(HPE).filter(HPE.company_id == uuid.UUID(cid))
        if event_key is not None:
            return q.filter(HPE.event_key == event_key).one_or_none()
        return q.all()


def kalit(s, *parts, plan=None):
    """Endpoint hisoblaydigan `event_key` — testda AYNI usul bilan."""
    from app.services.historical import event_key
    return event_key(uuid.UUID(s["cid"]), plan or s["plan"], *parts)
