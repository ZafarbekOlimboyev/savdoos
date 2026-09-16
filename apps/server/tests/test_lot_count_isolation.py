# -*- coding: utf-8 -*-
"""PHASE 4B.1 — SANOQDAGI YANGI PARTIYA: IZOLYATSIYA VA DARVOZALAR.

Yangi partiya — tizimga HUJJATSIZ kiradigan yagona yo'l. Shu bois uning
atrofidagi har chegara ALOHIDA sinov bilan mixlanadi va har rad javobining
yonida NEGATIV NAZORAT turadi: AYNI so'rov ruxsat berilgan sharoitda O'TADI.
Aks holda «rad etildi» sinovi boshqa sababdan (validatsiya, fixture xatosi)
yashil bo'lib, izolyatsiyani emas, tasodifni o'lchardi.

  1. Begona tenant mahsuloti — rad, va rad etishdan OLDIN hech qanday qator
     yaratilmaydi (egalik qulfdan oldin tekshiriladi).
  2. Mavjud bo'lmagan mahsulot — «Mahsulot topilmadi», «Ombor band» emas.
  3. Boshqa filialga biriktirilgan xodim — begona filialga partiya yoza olmaydi.
  4. Zona tasdig'i kuchini yo'qotsa — muddatli yangi partiya rad (qabul bilan
     AYNI), mavjud partiyalarni sanash esa ochiq qoladi.
  5. Jami partiya qatorlari chegarasi.
  6. `diff == 0`, lekin partiya tarkibi o'zgargan — `qty = 0` harakat qonuniy.
"""
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

from tests.test_lot_count import _count, _ok
from tests.test_lot_count_new_lots import _new
from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D30,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    ctx,
    sup,
)


@contextmanager
def _inventory_inserts(pid):
    """So'rov davomida shu mahsulot uchun `Inventory` qatori FLUSH qilinsa — yozib oladi.

    ⚠️  NEGA SESSIYA HODISASI. Rad javobidan keyin tranzaksiya orqaga qaytadi,
        shu bois bazaga qarab «qator yaratilmagan» deb isbotlab bo'lmaydi —
        eski tartib ham oxirida iz qoldirmasdi. Farq faqat YOZISH URINISHIDA.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from app.models.inventory import Inventory
    seen = []

    def _hook(session, flush_context, instances):
        for o in session.new:
            if isinstance(o, Inventory) and str(o.product_id) == str(pid):
                seen.append(o)

    event.listen(Session, "before_flush", _hook)
    try:
        yield seen
    finally:
        event.remove(Session, "before_flush", _hook)


def _foreign_product():
    """Boshqa kompaniya + filial + KUZATUVLI mahsulot (to'g'ridan-to'g'ri bazaga)."""
    from app.models.catalog import Product, Unit
    from app.models.org import Branch, Company
    with _db() as db:
        co = Company(id=uuid.uuid4(), name="Begona", code="bg" + uuid.uuid4().hex[:8],
                     currency="UZS")
        db.add(co)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=co.id, code="BG1", name="Begona filial",
                    timezone="Asia/Tashkent", is_active=True)
        db.add(br)
        db.flush()
        p = Product(id=uuid.uuid4(), company_id=co.id, name="Begona " + uuid.uuid4().hex[:6],
                    article_code="BG-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=db.query(Unit).first().id, base_buy_price=50,
                    base_sell_price=100, tax_rate=0, track_lots=True, track_expiry=False)
        db.add(p)
        db.commit()
        return co.id, br.id, p.id


def _drop_foreign(co_id, br_id, p_id):
    from app.models.catalog import Product
    from app.models.org import Branch, Company
    with _db() as db:
        db.query(Product).filter(Product.id == p_id).delete()
        db.query(Branch).filter(Branch.id == br_id).delete()
        db.query(Company).filter(Company.id == co_id).delete()
        db.commit()


# ══ 1. BEGONA TENANT ═════════════════════════════════════════════════════════

def test_BEGONA_tenant_mahsuloti_RAD_va_QATOR_YARATILMAYDI(client, admin_headers, ctx, sup):
    from app.models.inventory import Inventory, StockBatch
    H = admin_headers
    co_id, br_id, fpid = _foreign_product()
    try:
        item = {"product_id": str(fpid), "counted": 3, "new_lots": [_new(3, 60, batch="BEGONA")]}
        with _inventory_inserts(fpid) as ins:
            r = _count(client, H, [item])
        assert r.status_code == 400, r.text
        assert "Mahsulot topilmadi" in r.json()["detail"]
        assert ins == [], "egalik tekshiruvidan OLDIN begona mahsulotga qator yozildi"
        with _db() as db:
            assert db.query(Inventory).filter(Inventory.product_id == fpid).count() == 0
            assert db.query(StockBatch).filter(StockBatch.product_id == fpid).count() == 0
    finally:
        _drop_foreign(co_id, br_id, fpid)

    # NEGATIV NAZORAT: AYNI so'rov O'Z mahsulotida o'tadi va partiya tug'iladi.
    cid, bid = ctx
    pid = _product(client, H)
    _enable(client, H, pid, expiry=False)
    r = _count(client, H, [{"product_id": pid, "counted": 3,
                            "new_lots": [_new(3, 60, batch="OZIMIZNIKI")]}])
    assert r.status_code == 200, r.text
    assert [b.batch_no for b in _lots(pid)] == ["OZIMIZNIKI"]
    _ok(cid, pid)


def test_MAVJUD_BOLMAGAN_mahsulot_OMBOR_BAND_deb_korsatilmaydi(client, admin_headers, ctx, sup):
    """Postgres'da eski tartib FK buzilishini retry-o'ramiga uzatib 409 berardi."""
    ghost = uuid.uuid4()
    with _inventory_inserts(ghost) as ins:
        r = _count(client, admin_headers, [{"product_id": str(ghost), "counted": 1,
                                            "new_lots": [_new(1, 10)]}])
    assert r.status_code == 400, r.text
    assert "Mahsulot topilmadi" in r.json()["detail"]
    assert "band" not in r.json()["detail"]
    assert ins == []


def test_BEGONA_kompaniya_filialiga_sanoq_RAD(client, admin_headers, ctx, sup):
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H)
    _enable(client, H, pid, expiry=False)
    co_id, br_id, fpid = _foreign_product()
    try:
        r = _count(client, H, [{"product_id": pid, "counted": 2, "new_lots": [_new(2, 10)]}],
                   branch_id=str(br_id))
        assert r.status_code == 400 and "Filial topilmadi" in r.json()["detail"], r.text
        assert _lots(pid) == []
    finally:
        _drop_foreign(co_id, br_id, fpid)

    # NEGATIV NAZORAT: AYNI so'rov O'Z filiali bilan o'tadi.
    r2 = _count(client, H, [{"product_id": pid, "counted": 2, "new_lots": [_new(2, 10)]}],
                branch_id=str(bid))
    assert r2.status_code == 200, r2.text
    assert [b.branch_id for b in _lots(pid)] == [bid]
    _ok(cid, pid)


# ══ 2. FILIAL DOIRASI ════════════════════════════════════════════════════════

def test_BOSHQA_filial_xodimi_BEGONA_filialga_partiya_yoza_OLMAYDI(client, admin_headers, ctx, sup):
    import pytest
    from fastapi import HTTPException

    from app.api.v1.inventory import CountIn, _stock_count_once
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.inventory import Inventory, StockBatch, StockMovement, StockMovementLotAllocation
    from app.models.org import Branch
    from app.models.sync import AuditLog
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H)
    _enable(client, H, pid, expiry=False)
    with _db() as db:
        b2 = Branch(id=uuid.uuid4(), company_id=cid, code="F4C" + uuid.uuid4().hex[:5],
                    name="4B.1 ikkinchi filial", timezone="Asia/Tashkent", is_active=True)
        db.add(b2)
        db.flush()
        role = db.query(Role).filter(Role.code == "omborchi").first()
        e = Employee(id=uuid.uuid4(), company_id=cid, full_name="Ikkinchi filial omborchisi",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=role.id)
        db.add(e)
        db.flush()
        db.add(EmployeeBranch(employee_id=e.id, branch_id=b2.id))
        db.commit()
        e_id, b2_id = e.id, b2.id

    def body(branch):
        return CountIn(items=[{"product_id": pid, "counted": 3,
                               "new_lots": [_new(3, 40, batch="FILIAL")]}],
                       client_uuid=uuid.uuid4(), branch_id=branch)

    try:
        with _db() as db:
            emp = db.get(Employee, e_id)
            with pytest.raises(HTTPException) as he:
                _stock_count_once(body(bid), emp, db)
            assert he.value.status_code == 403, he.value.detail
            assert "biriktirilmagan" in he.value.detail
            db.rollback()
        assert _lots(pid) == []

        # NEGATIV NAZORAT: AYNI xodim, AYNI so'rov — O'Z filialida o'tadi.
        with _db() as db:
            emp = db.get(Employee, e_id)
            out = _stock_count_once(body(b2_id), emp, db)
        assert out["changed"] == 1, out
        got = _lots(pid)
        assert [(b.branch_id, b.batch_no) for b in got] == [(b2_id, "FILIAL")]
        _ok(cid, pid)
    finally:
        with _db() as db:
            mv = [m.id for m in db.query(StockMovement).filter(StockMovement.branch_id == b2_id)]
            if mv:
                db.query(StockMovementLotAllocation).filter(
                    StockMovementLotAllocation.stock_movement_id.in_(mv)).delete(synchronize_session=False)
            db.query(StockMovement).filter(StockMovement.branch_id == b2_id).delete()
            db.query(StockBatch).filter(StockBatch.branch_id == b2_id).delete()
            db.query(Inventory).filter(Inventory.branch_id == b2_id).delete()
            db.query(AuditLog).filter(AuditLog.actor_id == e_id).delete()
            db.query(EmployeeBranch).filter(EmployeeBranch.employee_id == e_id).delete()
            db.query(Employee).filter(Employee.id == e_id).delete()
            db.query(Branch).filter(Branch.id == b2_id).delete()
            db.commit()


# ══ 3. ZONA TASDIG'I ═════════════════════════════════════════════════════════

def test_ZONA_tasdigi_yoqolsa_MUDDATLI_yangi_partiya_RAD_sanash_OCHIQ(client, admin_headers, ctx, sup):
    from app.models.org import Branch
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H)
    assert _enable(client, H, pid).status_code == 200
    assert _recv(client, H, sup, pid, 4, 50, D10).status_code == 200
    manba = _lots(pid)[0]
    pid_nx = _product(client, H)                       # partiyali, lekin MUDDATSIZ
    assert _enable(client, H, pid_nx, expiry=False).status_code == 200
    with _db() as db:
        old_tz = db.get(Branch, bid).timezone
        # Tanilgan, lekin TASDIQLANMAGAN zona: tasdiq zona NOMI bilan saqlangan.
        db.get(Branch, bid).timezone = "Asia/Almaty" if old_tz != "Asia/Almaty" else "Asia/Bishkek"
        db.commit()
    try:
        r = _count(client, H, [{"product_id": pid, "counted": 6,
                                "lots": [{"stock_batch_id": str(manba.id), "counted": 4}],
                                "new_lots": [_new(2, 50, batch="ZONA", expiry=D30)]}])
        assert r.status_code == 409, r.text
        assert "TASDIQLANMAGAN" in r.json()["detail"]
        assert [(b.batch_no, float(b.remaining_qty)) for b in _lots(pid)] == [(manba.batch_no, 4.0)]

        # QABUL YO'LI AYNI HOLATDA AYNI JAVOBNI BERADI — ikki eshik bir xil.
        rr = _recv(client, H, sup, pid, 1, 50, D30)
        assert rr.status_code == 409 and "TASDIQLANMAGAN" in rr.json()["detail"], rr.text

        # NEGATIV NAZORAT: muddat kuzatilmaydigan tovarning yangi partiyasi zonaga
        # TAYANMAYDI — AYNI zona holatida o'tadi.
        rn = _count(client, H, [{"product_id": pid_nx, "counted": 2,
                                 "new_lots": [_new(2, 50, batch="ZONASIZ")]}])
        assert rn.status_code == 200, rn.text
        _ok(cid, pid_nx)

        # NEGATIV NAZORAT: mavjud partiyani sanash sana YOZMAYDI — ochiq qoladi.
        r2 = _count(client, H, [{"product_id": pid, "counted": 3,
                                 "lots": [{"stock_batch_id": str(manba.id), "counted": 3}]}])
        assert r2.status_code == 200, r2.text
        _ok(cid, pid)
    finally:
        with _db() as db:
            db.get(Branch, bid).timezone = old_tz
            db.commit()

    # NEGATIV NAZORAT 2: zona qaytgach AYNI yangi partiya o'tadi.
    r3 = _count(client, H, [{"product_id": pid, "counted": 5,
                             "lots": [{"stock_batch_id": str(manba.id), "counted": 3}],
                             "new_lots": [_new(2, 50, batch="ZONA", expiry=D30)]}])
    assert r3.status_code == 200, r3.text
    _ok(cid, pid)


# ══ 4. HAJM CHEGARASI ════════════════════════════════════════════════════════

def test_JAMI_partiya_qatorlari_CHEGARALANADI(client, admin_headers):
    from app.api.v1.inventory import MAX_COUNT_LOT_LINES

    def items(n_items):
        return [{"product_id": str(uuid.uuid4()), "counted": 0,
                 "lots": [{"stock_batch_id": str(uuid.uuid4()), "counted": 0}
                          for _ in range(200)]} for _ in range(n_items)]

    assert MAX_COUNT_LOT_LINES == 2000
    r = _count(client, admin_headers, items(11))            # 2200 qator
    assert r.status_code == 400, r.text
    assert r.json()["detail"].startswith("Bitta so'rovda 2200 ta partiya qatori — chegara 2000.")

    # `new_lots` ham SANALADI: 2000 sanalgan + 1 yangi = 2001.
    extra = items(10) + [{"product_id": str(uuid.uuid4()), "counted": 1,
                          "new_lots": [_new(1, 0)]}]
    r1 = _count(client, admin_headers, extra)
    assert r1.status_code == 400, r1.text
    assert r1.json()["detail"].startswith("Bitta so'rovda 2001 ta partiya qatori")

    # NEGATIV NAZORAT: aynan chegarada so'rov KEYINGI tekshiruvga o'tadi.
    r2 = _count(client, admin_headers, items(10))           # 2000 qator
    assert r2.status_code == 400, r2.text
    assert "chegara" not in r2.json()["detail"]


# ══ 5. JAMI O'ZGARMASA HAM TARKIB O'ZGARADI ══════════════════════════════════

def test_DIFF_NOL_lekin_tarkib_ozgarsa_NOL_harakat_QONUNIY(client, admin_headers, ctx, sup):
    from app.models.inventory import StockMovement
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H)
    _enable(client, H, pid, expiry=False)
    assert _recv(client, H, sup, pid, 4, 50).status_code == 200
    manba = _lots(pid)[0]

    r = _count(client, H, [{"product_id": pid, "counted": 4,
                            "lots": [{"stock_batch_id": str(manba.id), "counted": 1}],
                            "new_lots": [_new(3, 60, batch="ALMASHDI")]}])
    assert r.status_code == 200, r.text
    row = r.json()["results"][0]
    assert row["diff"] == 0 and r.json()["changed"] == 1
    assert len(row["lots"]["decrements"]) == 1 and len(row["lots"]["created"]) == 1
    with _db() as db:
        mv = (db.query(StockMovement)
              .filter(StockMovement.product_id == uuid.UUID(pid), StockMovement.ref_type == "count")
              .all())
        assert [Decimal(str(m.qty)) for m in mv] == [Decimal("0")]
    assert sorted((b.batch_no or "", float(b.remaining_qty)) for b in _lots(pid)) == \
        sorted([(manba.batch_no or "", 1.0), ("ALMASHDI", 3.0)])
    _ok(cid, pid)


# ══ 6. MUDDATI O'TGAN TOPILMA — QABULDAN FARQLI RAVISHDA QABUL QILINADI ═════

def test_SANOQDA_muddati_OTGAN_topilma_QAYD_etiladi_QABULDA_esa_RAD(client, admin_headers, ctx, sup):
    """Javondan topilgan muddati o'tgan qadoq JISMONAN bor: uni rad etish tovarni
    tizimdan yashirib, hisobdan chiqarishni imkonsiz qilardi. Ta'minotchidan esa
    bunday tovar QABUL QILINMAYDI — ikki qoida ataylab farq qiladi."""
    H = admin_headers
    cid, bid = ctx
    pid = _product(client, H)
    assert _enable(client, H, pid).status_code == 200
    past = date.today() - timedelta(days=3)

    rr = _recv(client, H, sup, pid, 2, 50, past)
    assert rr.status_code == 400 and "qabul qilinmaydi" in rr.json()["detail"], rr.text
    assert _lots(pid) == []

    r = _count(client, H, [{"product_id": pid, "counted": 2,
                            "new_lots": [_new(2, 50, batch="ESKI", expiry=past)]}])
    assert r.status_code == 200, r.text
    assert [(b.batch_no, b.expiry_date) for b in _lots(pid)] == [("ESKI", past)]
    _ok(cid, pid)


# ══ 7. TAKROR KALITI EGALIKDAN OLDIN ═════════════════════════════════════════

def test_QOLLANGAN_sanoq_qayta_yuborilsa_mahsulot_OCHIRILGAN_bolsa_ham_DUBLIKAT(client, admin_headers, ctx, sup):
    """Operatorga bajarilgan amal xato bo'lib qaytmasin: kalit egalikdan OLDIN."""
    from datetime import datetime, timezone

    from app.models.catalog import Product
    H = admin_headers
    pid = _product(client, H)
    cu = str(uuid.uuid4())
    item = [{"product_id": pid, "counted": 5}]
    r = client.post("/api/v1/inventory/count", headers=H, json={"items": item, "client_uuid": cu})
    assert r.status_code == 200 and r.json()["changed"] == 1, r.text
    with _db() as db:
        db.get(Product, uuid.UUID(pid)).deleted_at = datetime.now(timezone.utc)
        db.commit()
    try:
        again = client.post("/api/v1/inventory/count", headers=H,
                            json={"items": item, "client_uuid": cu})
        assert again.status_code == 200 and again.json().get("duplicate") is True, again.text
        # NEGATIV NAZORAT: YANGI kalit bilan AYNI so'rov egalik tekshiruvida to'xtaydi.
        fresh = _count(client, H, item)
        assert fresh.status_code == 400 and "Mahsulot topilmadi" in fresh.json()["detail"], fresh.text
    finally:
        with _db() as db:
            db.get(Product, uuid.UUID(pid)).deleted_at = None
            db.commit()
