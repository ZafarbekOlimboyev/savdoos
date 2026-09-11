# -*- coding: utf-8 -*-
"""1С Cutover V2 — Phase 2 (YOZUV yo'li) testlari.

Qamrov: snapshot idempotentligi (qayta o'ynash / ziddiyat / poyga / davom etish),
CUTOVER_REFRESH maydon siyosati, qoldiq rekonsiliatsiyasi (audit izi bilan),
DELETED_MATCH amallari, katalog resetini BAJARISH va LIVE darvozalari.

⚠️  SALBIY NAZORAT: har kafolat uchun uni BUZADIGAN holat ham sinaladi.
"""
import json
import uuid

import pytest

from app.core.security import create_access_token
from app.models.auth import Employee, Role
from app.models.catalog import Product, ProductBarcode
from app.models.enums import EmployeeStatus, ImportStatus
from app.models.imports import ImportJob, ImportRow
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.services import catalog_commit_v2 as ccv2
from app.services import catalog_reset

V2 = "/api/v1/catalog/v2"
VENDOR = {"X-Vendor-Key": "test-vendor-key"}


def _reset(client, t, **over):
    """Reset BAJARISH — yangi shartnoma: dry-run tokeni + vendor huquqi."""
    tok = over.pop("token", None)
    if tok is None:
        tok = client.post(f"{V2}/reset/dry-run", headers=t["H"]).json().get("reset_token", "")
    cid = over.pop("company_id", t["cid"])
    code = over.pop("confirm_code", t["code"])
    hdr = over.pop("headers", VENDOR)
    return client.post(f"{V2}/reset/execute?company_id={cid}&reset_token={tok}"
                       f"&confirm_code={code}", headers=hdr)


def _live(client, t, job_id):
    return client.post(f"{V2}/cutover-complete?import_job_id={job_id}", headers=t["H"])


def _mk_company(db, code):
    comp = Company(id=uuid.uuid4(), name=f"P2-{code}", code=code, currency="KGS")
    db.add(comp)
    db.flush()
    br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01")
    db.add(br)
    role = db.query(Role).filter(Role.code == "ega").first()
    emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                   full_name="Ega", phone=f"+9986{uuid.uuid4().int % 10**7:07d}",
                   status=EmployeeStatus.active, sec_epoch=0)
    db.add(emp)
    db.commit()
    tok = create_access_token(str(emp.id), {"role": "ega", "company_id": str(comp.id), "sv": 0})
    return comp, br, emp, {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def t(client):
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        comp, br, emp, H = _mk_company(db, "p" + uuid.uuid4().hex[:8])
        yield {"cid": comp.id, "bid": br.id, "eid": emp.id, "code": comp.code, "H": H}


def _row(name, ext=None, **kw):
    d = {"name": name, "sell_price": 10.0, "buy_price": 5.0, "stock": 0.0,
         "barcodes": [], "is_weighted": False}
    if ext:
        d["external_id"] = ext
    d.update(kw)
    return d


def _body(rows, mode="CUTOVER_REFRESH", snap="snap-1", **kw):
    return {"mode": mode, "source_system": "1c", "snapshot_id": snap, "rows": rows, **kw}


def _seed(client, t, rows, snap="seed"):
    r = client.post(f"{V2}/commit", json=_body(rows, mode="INITIAL_CREATE", snap=snap),
                    headers=t["H"])
    assert r.status_code == 200, r.text
    return r.json()


def _state(db, cid):
    pids = [p.id for p in db.query(Product).filter(Product.company_id == cid).all()]
    return {
        "products": len(pids),
        "barcodes": db.query(ProductBarcode).filter(ProductBarcode.company_id == cid).count(),
        "movements": db.query(StockMovement).filter(
            StockMovement.product_id.in_(pids)).count() if pids else 0,
        "qty": float(sum(float(i.qty or 0) for i in db.query(Inventory).filter(
            Inventory.product_id.in_(pids)).all())) if pids else 0.0,
        "sell_sum": float(sum(float(p.base_sell_price or 0) for p in
                              db.query(Product).filter(Product.company_id == cid).all())),
    }


# ══ 0. IDEMPOTENTLIK ═════════════════════════════════════════════════════════

def test_ayni_snapshot_QAYTA_yuborilsa_NOL_yozuv(client, t):
    from app.db.session import SessionLocal
    rows = [_row("A", "G1", stock=4.0, barcodes=["4600949010205"]), _row("B", "G2", stock=1.0)]
    first = _seed(client, t, rows, snap="S-1")
    assert first["replayed"] is False and first["created"] == 2
    with SessionLocal() as db:
        before = _state(db, t["cid"])
    r = client.post(f"{V2}/commit", json=_body(rows, mode="INITIAL_CREATE", snap="S-1"),
                    headers=t["H"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["replayed"] is True, j
    assert j["job_id"] == first["job_id"], "AYNI import_job qaytarilishi shart"
    with SessionLocal() as db:
        assert _state(db, t["cid"]) == before, "qayta o'ynashda YOZUV bo'ldi"


def test_ayni_snapshot_BOSHQA_mazmun_409(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1")], snap="S-2")
    with SessionLocal() as db:
        before = _state(db, t["cid"])
    r = client.post(f"{V2}/commit",
                    json=_body([_row("A", "G1", sell_price=999.0)], snap="S-2"),
                    headers=t["H"])
    assert r.status_code == 409, r.text
    assert "SNAPSHOT_CONFLICT" in r.json()["detail"]
    with SessionLocal() as db:
        assert _state(db, t["cid"]) == before, "ziddiyatda YOZUV bo'ldi"


def test_content_hash_tartibga_BOG_LIQ_EMAS(client, t):
    """Ayni fayl boshqa tartibda kelsa SOXTA ziddiyat bermasin."""
    a, b = _row("A", "G1"), _row("B", "G2")
    _seed(client, t, [a, b], snap="S-3")
    r = client.post(f"{V2}/commit", json=_body([b, a], mode="INITIAL_CREATE", snap="S-3"),
                    headers=t["H"])
    assert r.status_code == 200 and r.json()["replayed"] is True, r.text


def test_snapshot_id_MAJBURIY(client, t):
    r = client.post(f"{V2}/commit",
                    json={"mode": "INITIAL_CREATE", "source_system": "1c",
                          "rows": [_row("A", "G1")]}, headers=t["H"])
    assert r.status_code == 400 and "snapshot_id" in r.json()["detail"]


def test_COMMITTING_holatida_ikkinchi_commit_RAD(client, t):
    """Poyga: bir snapshot uchun IKKI import boshlanmaydi."""
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1")], snap="S-4")
    with SessionLocal() as db:
        j = db.query(ImportJob).filter(ImportJob.company_id == t["cid"],
                                       ImportJob.snapshot_id == "S-4").one()
        j.status = ImportStatus.committing       # "boshqa jarayon ishlayapti"
        db.commit()
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1")], mode="INITIAL_CREATE",
                                               snap="S-4"), headers=t["H"])
    assert r.status_code == 409 and "IMPORT_IN_PROGRESS" in r.json()["detail"], r.text


def test_FAILED_ish_DAVOM_ettiriladi_yangi_ish_ochilmaydi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1"), _row("B", "G2")], snap="S-5")
    with SessionLocal() as db:
        j = db.query(ImportJob).filter(ImportJob.snapshot_id == "S-5").one()
        jid = j.id
        j.status = ImportStatus.failed
        db.commit()
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1"), _row("B", "G2")],
                                               mode="INITIAL_CREATE", snap="S-5"),
                    headers=t["H"])
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] == str(jid), "YANGI ish ochildi — davom ettirilmadi"
    with SessionLocal() as db:
        assert db.query(ImportJob).filter(ImportJob.snapshot_id == "S-5").count() == 1
        assert db.query(Product).filter(Product.company_id == t["cid"]).count() == 2


def test_SALBIY_qayta_ochish_DUBLIKAT_mahsulot_bermaydi(client, t):
    """Davom ettirishda allaqachon qo'llangan qator IKKINCHI marta yaratmasin."""
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1"), _row("B", "G2")], snap="S-6")
    with SessionLocal() as db:
        db.query(ImportJob).filter(ImportJob.snapshot_id == "S-6").one().status = \
            ImportStatus.failed
        db.commit()
    for _ in range(3):
        client.post(f"{V2}/commit", json=_body([_row("A", "G1"), _row("B", "G2")],
                                               mode="INITIAL_CREATE", snap="S-6"),
                    headers=t["H"])
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"]).count() == 2


# ══ 1-2. CUTOVER_REFRESH va MAYDON SIYOSATI ══════════════════════════════════

def test_nom_ozgarishi_AYNI_Product_id_saqlaydi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("Eski", "G1")], snap="R-1")
    with SessionLocal() as db:
        pid = db.query(Product).filter(Product.company_id == t["cid"]).one().id
    r = client.post(f"{V2}/commit?confirm=name",
                    json=_body([_row("Yangi nom", "G1")], snap="R-2"), headers=t["H"])
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == t["cid"]).one()
        assert p.id == pid, "Product.id O'ZGARDI"
        assert p.name == "Yangi nom"
        assert p.external_id == "G1"


def test_nom_TASDIQSIZ_ozgarmaydi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("Eski", "G1")], snap="R-3")
    r = client.post(f"{V2}/commit", json=_body([_row("Yangi", "G1")], snap="R-4"),
                    headers=t["H"])
    assert r.status_code == 200
    assert r.json()["confirmation_required"] == 1, r.json()
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"]).one().name == "Eski"


def test_narx_AVTOMATIK_yangilanadi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", sell_price=10.0, buy_price=5.0)], snap="R-5")
    client.post(f"{V2}/commit",
                json=_body([_row("A", "G1", sell_price=12.0, buy_price=6.0)], snap="R-6"),
                headers=t["H"])
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == t["cid"]).one()
        assert (float(p.base_sell_price), float(p.base_buy_price)) == (12.0, 6.0)


def test_barkod_QOSHILADI_eskisi_saqlanadi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", barcodes=["4600949010205"])], snap="R-7")
    client.post(f"{V2}/commit",
                json=_body([_row("A", "G1", barcodes=["4600949010205", "4780032051640"])],
                           snap="R-8"), headers=t["H"])
    with SessionLocal() as db:
        bcs = {b.barcode for b in db.query(ProductBarcode).filter(
            ProductBarcode.company_id == t["cid"]).all()}
        assert bcs == {"4600949010205", "4780032051640"}


def test_NEVER_AUTO_maydonlari_RAD_etiladi(client, t):
    _seed(client, t, [_row("A", "G1")], snap="R-9")
    r = client.post(f"{V2}/commit?confirm=product_delete",
                    json=_body([_row("A", "G1")], snap="R-10"), headers=t["H"])
    assert r.status_code == 400 and "product_delete" in r.json()["detail"]


def test_AMBIGUOUS_qator_NOL_yozuv(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", barcodes=["4600949010205"]), _row("B", "G2")],
          snap="R-11")
    with SessionLocal() as db:
        before = _state(db, t["cid"])
    # GUID -> A, barkod -> A ning barkodi lekin nom B... ziddiyat yaratamiz:
    r = client.post(f"{V2}/commit",
                    json=_body([_row("X", "G2", barcodes=["4600949010205"])], snap="R-12"),
                    headers=t["H"])
    assert r.status_code == 200
    assert r.json()["skipped"] == 1, r.json()
    with SessionLocal() as db:
        assert _state(db, t["cid"]) == before


def test_MISSING_FROM_SOURCE_tegilmaydi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("Qoladi", "G1"), _row("Yo'q", "G2")], snap="R-13")
    client.post(f"{V2}/commit", json=_body([_row("Qoladi", "G1")], snap="R-14"),
                headers=t["H"])
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"],
                                        Product.deleted_at.is_(None)).count() == 2
        assert db.query(Product).filter(Product.company_id == t["cid"],
                                        Product.is_active.is_(False)).count() == 0


# ══ 3. QOLDIQ REKONSILIATSIYASI ══════════════════════════════════════════════

def _movements(db, cid):
    pids = [p.id for p in db.query(Product).filter(Product.company_id == cid).all()]
    return db.query(StockMovement).filter(StockMovement.product_id.in_(pids)).all()


@pytest.mark.parametrize("old,new,delta", [(10.0, 14.0, 4.0), (10.0, 6.0, -4.0)])
def test_qoldiq_DELTA_harakat_yaratadi(client, t, old, new, delta):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", stock=old)], snap=f"I-{old}-{new}")
    with SessionLocal() as db:
        n0 = len(_movements(db, t["cid"]))
    client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=new)],
                                           snap=f"I2-{old}-{new}"), headers=t["H"])
    with SessionLocal() as db:
        mv = [m for m in _movements(db, t["cid"]) if m.ref_type == ccv2.REF_TYPE
              and float(m.qty) == delta]
        assert len(mv) == 1, [(float(m.qty), m.ref_type) for m in _movements(db, t["cid"])]
        assert float(mv[0].balance_after) == new
        assert mv[0].reason == "1C cutover reconciliation"
        assert len(_movements(db, t["cid"])) == n0 + 1
        inv = db.query(Inventory).join(Product, Product.id == Inventory.product_id).filter(
            Product.company_id == t["cid"]).one()
        assert float(inv.qty) == new


def test_qoldiq_OZGARMASA_harakat_YO_Q(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", stock=10.0)], snap="I-same")
    with SessionLocal() as db:
        n0 = len(_movements(db, t["cid"]))
    client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=10.0)], snap="I-same2"),
                headers=t["H"])
    with SessionLocal() as db:
        assert len(_movements(db, t["cid"])) == n0


def test_SALBIY_qayta_oynashda_IKKINCHI_harakat_YO_Q(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", stock=10.0)], snap="I-r1")
    client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=15.0)], snap="I-r2"),
                headers=t["H"])
    with SessionLocal() as db:
        n1 = len(_movements(db, t["cid"]))
        q1 = float(db.query(Inventory).join(Product, Product.id == Inventory.product_id)
                   .filter(Product.company_id == t["cid"]).one().qty)
    for _ in range(3):
        client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=15.0)], snap="I-r2"),
                    headers=t["H"])
    with SessionLocal() as db:
        assert len(_movements(db, t["cid"])) == n1, "TAKROR harakat yozildi"
        q2 = float(db.query(Inventory).join(Product, Product.id == Inventory.product_id)
                   .filter(Product.company_id == t["cid"]).one().qty)
        assert q2 == q1 == 15.0, "qoldiq IKKI marta siljidi"


def test_rekonsiliatsiya_KASSAGA_tegmaydi(client, t):
    from app.db.session import SessionLocal
    from app.models.sales import Sale
    _seed(client, t, [_row("A", "G1", stock=3.0)], snap="I-c1")
    client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=9.0)], snap="I-c2"),
                headers=t["H"])
    with SessionLocal() as db:
        assert db.query(Sale).filter(Sale.company_id == t["cid"]).count() == 0
        mv = _movements(db, t["cid"])
        assert all(str(m.type).endswith("adjustment") for m in mv), [str(m.type) for m in mv]
        assert {m.ref_type for m in mv} <= {ccv2.REF_TYPE}


# ══ 4. DELETED_MATCH ═════════════════════════════════════════════════════════

def _soft_delete(cid):
    from datetime import datetime, timezone
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == cid).first()
        p.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return p.id


def test_DELETED_MATCH_standart_KEEP_DELETED(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1")], snap="D-1")
    pid = _soft_delete(t["cid"])
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1")], snap="D-2"), headers=t["H"])
    assert r.status_code == 200
    assert r.json()["skipped"] == 1, r.json()
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"]).count() == 1
        assert db.get(Product, pid).deleted_at is not None, "standart bo'yicha tiklandi"


def test_REACTIVATE_ayni_Product_id_saqlaydi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1")], snap="D-3")
    pid = _soft_delete(t["cid"])
    b = _body([_row("A", "G1")], snap="D-4")
    b["deleted_match_actions"] = {"G1": "REACTIVATE_EXISTING"}
    r = client.post(f"{V2}/commit", json=b, headers=t["H"])
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"]).count() == 1
        p = db.get(Product, pid)
        assert p.deleted_at is None and p.is_active is True
        assert p.external_id == "G1", "tashqi identifikatsiya yo'qoldi"


# ══ 5. KATALOG RESETINI BAJARISH ═════════════════════════════════════════════

def test_reset_BAJARILADI_va_faqat_katalogni_ochiradi(client, t):
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", stock=2.0, barcodes=["4600949010205"]),
                      _row("B", "G2", stock=0.0)], snap="X-1")
    r = _reset(client, t)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"]).count() == 0
        assert db.query(ProductBarcode).filter(ProductBarcode.company_id == t["cid"]).count() == 0
        assert db.query(ImportJob).filter(ImportJob.company_id == t["cid"]).count() == 0
        # SAQLANISHI SHART
        assert db.get(Company, t["cid"]) is not None
        assert db.query(Branch).filter(Branch.company_id == t["cid"]).count() == 1
        assert db.query(Employee).filter(Employee.company_id == t["cid"]).count() == 1
        from app.models.catalog import Unit
        assert db.query(Unit).count() >= 4, "GLOBAL birliklar o'chdi!"


def test_reset_notogri_confirm_code_RAD(client, t):
    _seed(client, t, [_row("A", "G1")], snap="X-2")
    r = _reset(client, t, confirm_code="xato")
    assert r.status_code == 400


def test_reset_ESKIRGAN_token_RAD(client, t):
    """`expect_products` o'rniga TOKEN: dry-run'dan keyin katalog o'zgarsa rad etiladi.

    Token BARCHA sanoqlarni ushlab turadi, shu bois mahsulot soni o'zgarmasdan
    turib boshqa narsa o'zgargan holat ham ushlanadi."""
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1")], snap="X-3")
    tok = client.post(f"{V2}/reset/dry-run", headers=t["H"]).json()["reset_token"]
    _seed(client, t, [_row("B", "G2")], snap="X-3b")      # dry-run'dan KEYIN o'zgardi
    r = _reset(client, t, token=tok)
    assert r.status_code == 409 and "RESET_TOKEN_STALE" in r.json()["detail"], r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"]).count() == 2


@pytest.mark.parametrize("kind", ["sale", "shift", "purchase"])
def test_reset_BIZNES_hujjati_BLOKLAYDI(client, t, kind):
    from datetime import datetime, timezone
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1")], snap=f"X-b-{kind}")
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        if kind == "sale":
            from app.models.sales import Sale
            db.add(Sale(id=uuid.uuid4(), receipt_no="R1", company_id=t["cid"],
                        branch_id=t["bid"], cashier_id=t["eid"], subtotal=0, total=0,
                        sold_at=now))
        elif kind == "shift":
            from app.models.shifts import Shift
            db.add(Shift(id=uuid.uuid4(), branch_id=t["bid"], cashier_id=t["eid"],
                         opened_at=now, status="open"))
        else:
            from app.models.purchasing import Purchase, Supplier
            sup = Supplier(id=uuid.uuid4(), company_id=t["cid"], name="Yetkazuvchi")
            db.add(sup)
            db.flush()
            db.add(Purchase(id=uuid.uuid4(), doc_no="P-1", company_id=t["cid"],
                            branch_id=t["bid"], supplier_id=sup.id,
                            purchase_date=now, created_at=now))
        db.commit()
    r = _reset(client, t)
    assert r.status_code == 409, r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == t["cid"]).count() == 1


def test_reset_BOSHQA_tenantga_tegmaydi(client):
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        c1, b1, e1, H1 = _mk_company(db, "q" + uuid.uuid4().hex[:8])
        c2, b2, e2, H2 = _mk_company(db, "q" + uuid.uuid4().hex[:8])
    for H, snap in ((H1, "Y-1"), (H2, "Y-2")):
        client.post(f"{V2}/commit", json=_body([_row("A", "G1"), _row("B", "G2")],
                                               mode="INITIAL_CREATE", snap=snap), headers=H)
    r = _reset(client, {"cid": c1.id, "code": c1.code, "H": H1})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == c1.id).count() == 0
        assert db.query(Product).filter(Product.company_id == c2.id).count() == 2


def test_SALBIY_reset_tranzaksiyasi_QAYTARILADI(client, t, monkeypatch):
    """O'rtada yiqilsa — HECH NARSA o'chmasligi shart."""
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", stock=1.0)], snap="X-tx")
    with SessionLocal() as db:
        before = _state(db, t["cid"])
    orig = catalog_reset.DELETE_PLAN

    def boom(db_, cid):
        raise RuntimeError("sinov uchun uydirma xato")
    monkeypatch.setattr(catalog_reset, "DELETE_PLAN",
                        orig[:1] + [("BOOM", "DELETE FROM jadval_yoq WHERE company_id = :c")])
    r = _reset(client, t)
    assert r.status_code in (409, 500), r.text
    with SessionLocal() as db:
        assert _state(db, t["cid"]) == before, "qisman o'chirish qoldi"


def test_reset_production_da_YOPIQ(client, t, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    r = _reset(client, t)
    assert r.status_code == 403


# ══ 6-7. LIVE DARVOZASI ══════════════════════════════════════════════════════

def _go_live(client, t, job_id):
    r = _live(client, t, job_id)
    assert r.status_code == 200, r.text
    return r.json()


def test_cutover_COMMITTED_ishsiz_YOPILMAYDI(client, t):
    """Preview ishi bilan yopib bo'lmaydi — faqat COMMITTED."""
    r = client.post(f"{V2}/preview", json=_body([_row("A", "G1")], snap="L-pv"), headers=t["H"])
    rr = _live(client, t, r.json()["job_id"])
    assert rr.status_code == 409 and "COMMITTED emas" in rr.json()["detail"], rr.text


def test_cutover_AMBIGUOUS_qator_borligida_YOPILMAYDI(client, t):
    _seed(client, t, [_row("A", "G1", barcodes=["4600949010205"]), _row("B", "G2")],
          snap="L-0")
    j = client.post(f"{V2}/commit", json=_body([_row("X", "G2", barcodes=["4600949010205"])],
                                               snap="L-0b"), headers=t["H"]).json()
    r = _live(client, t, j["job_id"])
    assert r.status_code == 409 and "AMBIGUOUS" in r.json()["detail"], r.text


def test_LIVE_bolgach_CUTOVER_REFRESH_RAD(client, t):
    from app.db.session import SessionLocal
    j = _seed(client, t, [_row("A", "G1", stock=5.0)], snap="L-1")
    val = _go_live(client, t, j["job_id"])
    assert val["mode"] == "LIVE" and val["cutover_at"]
    with SessionLocal() as db:
        before = _state(db, t["cid"])
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=999.0)], snap="L-2"),
                    headers=t["H"])
    assert r.status_code == 409, r.text
    with SessionLocal() as db:
        assert _state(db, t["cid"]) == before, "LIVE'dan keyin qoldiq o'zgardi!"


def test_LIVE_bolgach_reset_RAD(client, t):
    j = _seed(client, t, [_row("A", "G1")], snap="L-3")
    _go_live(client, t, j["job_id"])
    r = _reset(client, t)
    assert r.status_code == 409


def test_LIVE_bolgach_preview_ISHLAYDI(client, t):
    """Post-live: o'qish va TAKLIF qilish mumkin, yozish MUMKIN EMAS."""
    j = _seed(client, t, [_row("A", "G1")], snap="L-4")
    _go_live(client, t, j["job_id"])
    r = client.post(f"{V2}/preview", json=_body([_row("A", "G1", sell_price=77.0),
                                                 _row("Yangi", "G9")], snap="L-5"),
                    headers=t["H"])
    assert r.status_code == 200, r.text
    cls = {x["classification"] for x in r.json()["rows"]}
    assert "NEW" in cls and "UPDATE_PRICE" in cls


def test_cash_cutover_katalog_darvozasini_OCHMAYDI(client, t):
    """SALBIY NAZORAT: kassa cutover'i katalogni LIVE qilmasligi shart."""
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        db.add(Setting(company_id=t["cid"], branch_id=None, key="cash",
                       value={"cutover_at": "2020-01-01T00:00:00Z"}))
        db.commit()
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1")], mode="INITIAL_CREATE",
                                               snap="L-6"), headers=t["H"])
    assert r.status_code == 200, "kassa cutover'i katalog yozuvini bloklab qo'ydi"
    with SessionLocal() as db:
        cat = db.query(Setting).filter(Setting.company_id == t["cid"],
                                       Setting.key == "catalog").one().value
        cash = db.query(Setting).filter(Setting.company_id == t["cid"],
                                        Setting.key == "cash").one().value
        assert cat.get("cutover_at") is None
        assert cash["cutover_at"] == "2020-01-01T00:00:00Z"


def test_NORMAL_OPERATION_yozmaydi(client, t):
    _seed(client, t, [_row("A", "G1")], snap="N-1")
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1", sell_price=50.0)],
                                               mode="NORMAL_OPERATION", snap="N-2"),
                    headers=t["H"])
    assert r.status_code == 400 and "NORMAL_OPERATION" in r.json()["detail"]


# ══ 8. ISH TARIXI ════════════════════════════════════════════════════════════

def test_jobs_tarixi_holat_va_xeshni_koradi(client, t):
    _seed(client, t, [_row("A", "G1")], snap="J-1")
    r = client.get(f"{V2}/jobs", headers=t["H"])
    assert r.status_code == 200
    js = r.json()
    committed = [j for j in js if j["status"] == "committed"]
    assert committed and committed[0]["snapshot_id"] == "J-1"
    assert len(committed[0]["content_sha256"]) == 64
    assert committed[0]["applied_rows"] == 1


def test_qayta_boshlashda_HISOB_YO_QOLSA_HAM_harakat_takrorlanmaydi(client, t):
    """Oxirgi himoya chizig'i: `import_rows` hisobi yo'qolsa ham qoldiq IKKI MARTA siljimasin.

    Qayta boshlashda odatda APPLIED_* qatorlar o'tkazib yuboriladi. Lekin agar
    bu hisob yo'qolsa (yoki qator boshqa yo'l bilan qayta ishlansa), yagona
    to'siq — harakat kaliti (`client_uuid` = uuid5(job, product)) va uning
    `ux_movements_cutover_key` indeksi. Shu holatni ATAYLAB yaratamiz.
    """
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", stock=10.0)], snap="RS-1")
    client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=25.0)], snap="RS-2"),
                headers=t["H"])
    with SessionLocal() as db:
        mv0 = len([m for m in _movements(db, t["cid"]) if m.ref_type == ccv2.REF_TYPE])
        qty0 = float(db.query(Inventory).join(Product, Product.id == Inventory.product_id)
                     .filter(Product.company_id == t["cid"]).one().qty)
        # ISHNI yiqilgan deb belgilaymiz VA hisobni YO'QOTAMIZ
        j = db.query(ImportJob).filter(ImportJob.snapshot_id == "RS-2").one()
        j.status = ImportStatus.failed
        db.query(ImportRow).filter(ImportRow.job_id == j.id).delete()
        db.commit()
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=25.0)], snap="RS-2"),
                    headers=t["H"])
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        mv1 = len([m for m in _movements(db, t["cid"]) if m.ref_type == ccv2.REF_TYPE])
        qty1 = float(db.query(Inventory).join(Product, Product.id == Inventory.product_id)
                     .filter(Product.company_id == t["cid"]).one().qty)
    assert mv1 == mv0, f"TAKROR harakat yozildi: {mv0} -> {mv1}"
    assert qty1 == qty0 == 25.0, f"qoldiq siljidi: {qty0} -> {qty1}"


def test_harakat_kaliti_DB_darajasida_NOYOB(client, t):
    """`ux_movements_cutover_key` — ilova kodini chetlab o'tsa ham to'xtatadi."""
    from sqlalchemy.exc import IntegrityError
    from app.db.session import SessionLocal
    from app.models.enums import MovementType
    _seed(client, t, [_row("A", "G1", stock=1.0)], snap="RS-3")
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == t["cid"]).one()
        key = uuid.uuid4()
        for _ in range(2):
            db.add(StockMovement(product_id=p.id, branch_id=t["bid"],
                                 type=MovementType.adjustment, qty=1, balance_after=1,
                                 ref_type=ccv2.REF_TYPE, reason="sinov",
                                 employee_id=t["eid"], client_uuid=key))
        with pytest.raises(IntegrityError):
            db.commit()


def test_ish_QAYTA_yurgizilsa_qoldiq_SILJIGAN_bolsa_ham_tegilmaydi(client, t):
    """Rekonsiliatsiya BIR MARTA bajariladi — keyin qoldiq o'zgarsa ham QAYTARILMAYDI.

    Bu `client_uuid` kalitining ASOSIY vazifasi. Agar qoldiq manbadagidek qolgan
    bo'lsa, delta=0 bo'lgani uchun baribir harakat bo'lmasdi — ya'ni o'sha holat
    kalitni O'LCHAMAYDI. Bu yerda cutover'dan KEYIN qoldiq siljiydi (masalan
    sotuv), so'ng AYNI ish qayta yurgiziladi: kalit bo'lmasa tizim qoldiqni
    manbaga QAYTARIB, haqiqiy savdoni bekor qilardi.
    """
    from app.db.session import SessionLocal
    _seed(client, t, [_row("A", "G1", stock=10.0)], snap="RS-4")
    client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=30.0)], snap="RS-5"),
                headers=t["H"])
    with SessionLocal() as db:
        # cutover'dan KEYIN qoldiq siljidi (sotuv bo'ldi deylik)
        inv = (db.query(Inventory).join(Product, Product.id == Inventory.product_id)
               .filter(Product.company_id == t["cid"]).one())
        inv.qty = 22.0
        j = db.query(ImportJob).filter(ImportJob.snapshot_id == "RS-5").one()
        j.status = ImportStatus.failed
        db.query(ImportRow).filter(ImportRow.job_id == j.id).delete()
        db.commit()
        mv0 = len([m for m in _movements(db, t["cid"]) if m.ref_type == ccv2.REF_TYPE])
    r = client.post(f"{V2}/commit", json=_body([_row("A", "G1", stock=30.0)], snap="RS-5"),
                    headers=t["H"])
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        qty = float(db.query(Inventory).join(Product, Product.id == Inventory.product_id)
                    .filter(Product.company_id == t["cid"]).one().qty)
        mv1 = len([m for m in _movements(db, t["cid"]) if m.ref_type == ccv2.REF_TYPE])
    assert qty == 22.0, f"qoldiq manbaga QAYTARILDI ({qty}) — haqiqiy harakat bekor qilindi"
    assert mv1 == mv0, f"TAKROR harakat: {mv0} -> {mv1}"
