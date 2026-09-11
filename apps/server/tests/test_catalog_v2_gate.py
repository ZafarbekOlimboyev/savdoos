# -*- coding: utf-8 -*-
"""1С Cutover V2 — PRODUCTION DARVOZASI testlari.

Olti mavzu: (1) tranzaksiya chegarasi HAQIQATDA qanday, (2) reset tokeni,
(3) cutover'ning ANIQ ishga bog'lanishi, (4) xeshning multiset-xavfsizligi,
(5) reset avtorizatsiyasi, (6) salbiy nazoratlar.
"""
import uuid

import pytest
from sqlalchemy import text as _T

from app.core.security import create_access_token
from app.models.auth import Employee, Role
from app.models.catalog import Product, ProductBarcode
from app.models.enums import EmployeeStatus, ImportStatus
from app.models.imports import ImportJob, ImportRow
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch, Company
from app.schemas.imports_v2 import ImportRowV2
from app.services import catalog_commit_v2 as ccv2
from app.services import catalog_reset
from app.services.catalog_commit_v2 import canonical_hash as H

V2 = "/api/v1/catalog/v2"
VENDOR = {"X-Vendor-Key": "test-vendor-key"}


def _mk(db, code):
    comp = Company(id=uuid.uuid4(), name=f"G-{code}", code=code, currency="KGS")
    db.add(comp)
    db.flush()
    br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01")
    db.add(br)
    role = db.query(Role).filter(Role.code == "ega").first()
    emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id, full_name="Ega",
                   phone=f"+9984{uuid.uuid4().int % 10**7:07d}",
                   status=EmployeeStatus.active, sec_epoch=0)
    db.add(emp)
    db.commit()
    tok = create_access_token(str(emp.id), {"role": "ega", "company_id": str(comp.id), "sv": 0})
    return comp, br, emp, {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def g(client):
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        c, b, e, H_ = _mk(db, "g" + uuid.uuid4().hex[:8])
        yield {"cid": c.id, "bid": b.id, "eid": e.id, "code": c.code, "H": H_}


def _row(name, ext=None, **kw):
    d = {"name": name, "sell_price": 10.0, "buy_price": 5.0, "stock": 0.0,
         "barcodes": [], "is_weighted": False}
    if ext:
        d["external_id"] = ext
    d.update(kw)
    return d


def _body(rows, mode="CUTOVER_REFRESH", snap="s", **kw):
    return {"mode": mode, "source_system": "1c", "snapshot_id": snap, "rows": rows, **kw}


def _seed(client, g, rows, snap="seed"):
    r = client.post(f"{V2}/commit", json=_body(rows, mode="INITIAL_CREATE", snap=snap),
                    headers=g["H"])
    assert r.status_code == 200, r.text
    return r.json()


def _state(db, cid):
    pids = [p.id for p in db.query(Product).filter(Product.company_id == cid).all()]
    return {"products": len(pids),
            "barcodes": db.query(ProductBarcode).filter(
                ProductBarcode.company_id == cid).count(),
            "movements": db.query(StockMovement).filter(
                StockMovement.product_id.in_(pids)).count() if pids else 0,
            "rows": db.query(ImportRow).join(
                ImportJob, ImportJob.id == ImportRow.job_id).filter(
                ImportJob.company_id == cid).count()}


# ══ 1. TRANZAKSIYA CHEGARASI — MODEL A (butun import atomik) ═════════════════

def test_ORTADA_yiqilish_HAMMASINI_qaytaradi(client, g, monkeypatch):
    """MODEL A isboti: 5-qatorda yiqilsa, oldingi 4 qator ham YOZILMAYDI."""
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        before = _state(db, g["cid"])
    real = ccv2._apply_row
    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 5:
            raise RuntimeError("sinov uchun uydirma xato (5-qator)")
        return real(*a, **kw)
    monkeypatch.setattr(ccv2, "_apply_row", boom)
    rows = [_row(f"P{i}", f"GG{i}", stock=float(i)) for i in range(1, 9)]
    r = client.post(f"{V2}/commit", json=_body(rows, mode="INITIAL_CREATE", snap="TX-1"),
                    headers=g["H"])
    assert r.status_code == 500, r.text
    with SessionLocal() as db:
        after = _state(db, g["cid"])
    assert after == before, f"QISMAN yozuv qoldi: {before} -> {after}"


def test_yiqilgandan_keyin_ish_FAILED_va_qayta_urinish_NOLDAN(client, g, monkeypatch):
    """Model A da qayta urinish NOLDAN boshlanadi — `import_rows` ham qaytarilgan."""
    from app.db.session import SessionLocal
    real = ccv2._apply_row
    st = {"fail": True, "n": 0}

    def flaky(*a, **kw):
        st["n"] += 1
        if st["fail"] and st["n"] == 3:
            raise RuntimeError("uydirma")
        return real(*a, **kw)
    monkeypatch.setattr(ccv2, "_apply_row", flaky)
    rows = [_row(f"Q{i}", f"HH{i}", stock=1.0) for i in range(1, 6)]
    assert client.post(f"{V2}/commit", json=_body(rows, mode="INITIAL_CREATE", snap="TX-2"),
                       headers=g["H"]).status_code == 500
    with SessionLocal() as db:
        j = db.query(ImportJob).filter(ImportJob.snapshot_id == "TX-2").one()
        assert j.status is ImportStatus.failed, j.status
        assert j.error
        # Model A: qatorlar QAYTARILGAN -> davom ettirish uchun hech narsa yo'q
        assert db.query(ImportRow).filter(ImportRow.job_id == j.id).count() == 0
    st["fail"] = False
    r = client.post(f"{V2}/commit", json=_body(rows, mode="INITIAL_CREATE", snap="TX-2"),
                    headers=g["H"])
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 5, r.json()
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == g["cid"]).count() == 5
        assert db.query(ImportJob).filter(ImportJob.snapshot_id == "TX-2").count() == 1


def test_commit_servisida_db_commit_YO_Q():
    """Tranzaksiya chegarasi ENDPOINTDA — servis o'zi commit qilmaydi."""
    import inspect
    src = inspect.getsource(ccv2)
    assert "db.commit()" not in src, "servis ichida commit bor — model A buziladi"


# ══ 2. RESET TOKENI ══════════════════════════════════════════════════════════

def _token(client, g):
    r = client.post(f"{V2}/reset/dry-run", headers=g["H"])
    assert r.status_code == 200, r.text
    return r.json()


def test_dry_run_TOKEN_va_barmoq_izi_beradi(client, g):
    _seed(client, g, [_row("A", "G1", stock=2.0, barcodes=["4600949010205"])], snap="T-1")
    d = _token(client, g)
    assert d["reset_token"], d
    fp = d["fingerprint"]
    for k in ("company_id", "nonce", "generated_at", "graph", "delete", "blockers"):
        assert k in fp, (k, fp)
    assert fp["delete"]["products"] == 1
    assert fp["company_id"] == str(g["cid"])


def test_token_IMZOSI_soxta_bolsa_RAD(client, g):
    _seed(client, g, [_row("A", "G1")], snap="T-2")
    d = _token(client, g)
    bad = d["reset_token"][:-4] + "AAAA"
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={bad}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 409 and "RESET_TOKEN_STALE" in r.json()["detail"], r.text


@pytest.mark.parametrize("mutate", ["inventory", "barcode", "import_row"])
def test_dry_run_dan_KEYIN_katalog_ozgarsa_RAD(client, g, mutate):
    """`expect_products` yetarli emas — HAR sanoq tekshiriladi."""
    from app.db.session import SessionLocal
    _seed(client, g, [_row("A", "G1", stock=2.0, barcodes=["4600949010205"])], snap=f"T-{mutate}")
    tok = _token(client, g)["reset_token"]
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == g["cid"]).first()
        if mutate == "inventory":
            db.add(Inventory(product_id=p.id, branch_id=uuid.uuid4(), qty=1, min_qty=0,
                             updated_at=p.created_at))
        elif mutate == "barcode":
            db.add(ProductBarcode(product_id=p.id, company_id=g["cid"], barcode="9990001112223"))
        else:
            j = db.query(ImportJob).filter(ImportJob.company_id == g["cid"]).first()
            db.add(ImportRow(job_id=j.id, row_no=999, raw={}, status="X"))
        db.commit()
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 409, r.text
    assert "RESET_TOKEN_STALE" in r.json()["detail"], r.json()
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == g["cid"]).count() == 1


@pytest.mark.parametrize("mutate", ["qty", "narx", "barkod_satri", "nom"])
def test_dry_run_dan_KEYIN_MAZMUN_ozgarsa_RAD(client, g, mutate):
    """SANOQ o'zgarmagan tahrirlar ham tokenni BEKOR qiladi.

    Bu sanoqqa asoslangan izning haqiqiy bo'shlig'i edi: `inventory.qty` joyida
    yangilansa yoki barkod satri tahrirlansa sanoqlar AYNI qolardi va operator
    TASDIQLAGAN holat o'zgargani holda reset o'tib ketardi.
    """
    from app.db.session import SessionLocal
    _seed(client, g, [_row("A", "G1", stock=2.0, barcodes=["4600949010205"])], snap=f"M-{mutate}")
    tok = _token(client, g)["reset_token"]
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == g["cid"]).first()
        before = {t: db.execute(_T(f"SELECT count(*) FROM {t}")).scalar()
                  for t in ("products", "product_barcodes", "inventory")}
        if mutate == "qty":
            inv = db.query(Inventory).filter(Inventory.product_id == p.id).first()
            inv.qty = float(inv.qty) + 3
        elif mutate == "narx":
            p.base_sell_price = float(p.base_sell_price or 0) + 7
        elif mutate == "barkod_satri":
            bc = db.query(ProductBarcode).filter(ProductBarcode.product_id == p.id).first()
            bc.barcode = "9990001112223"
        else:
            p.name = p.name + " TAHRIR"
        db.commit()
        after = {t: db.execute(_T(f"SELECT count(*) FROM {t}")).scalar()
                 for t in ("products", "product_barcodes", "inventory")}
    assert before == after, f"bu sinov SANOQNI o'zgartirmasligi kerak: {before} -> {after}"
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 409, r.text
    assert "mazmun:" in r.json()["detail"], r.json()
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == g["cid"]).count() == 1


def test_MAZMUN_izi_ozgarmasa_token_ISHLAYDI(client, g):
    """Salbiy nazorat: iz qo'shilgani bilan TOZA holatda reset baribir o'tadi."""
    _seed(client, g, [_row("A", "G1", stock=2.0, barcodes=["4600949010205"])], snap="M-OK")
    d = _token(client, g)
    assert "digest" in d["fingerprint"] and d["fingerprint"]["digest"]["inventory"], d["fingerprint"]
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={d['reset_token']}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("kind", ["sale", "shift"])
def test_dry_run_dan_KEYIN_biznes_hujjati_qoshilsa_RAD(client, g, kind):
    from datetime import datetime, timezone
    from app.db.session import SessionLocal
    _seed(client, g, [_row("A", "G1")], snap=f"T-b-{kind}")
    tok = _token(client, g)["reset_token"]
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        if kind == "sale":
            from app.models.sales import Sale
            db.add(Sale(id=uuid.uuid4(), receipt_no="G1", company_id=g["cid"],
                        branch_id=g["bid"], cashier_id=g["eid"], subtotal=0, total=0,
                        sold_at=now))
        else:
            from app.models.shifts import Shift
            db.add(Shift(id=uuid.uuid4(), branch_id=g["bid"], cashier_id=g["eid"],
                         opened_at=now, status="open"))
        db.commit()
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 409, r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == g["cid"]).count() == 1


def test_token_TOZA_holatda_ISHLAYDI(client, g):
    from app.db.session import SessionLocal
    _seed(client, g, [_row("A", "G1", stock=1.0)], snap="T-ok")
    tok = _token(client, g)["reset_token"]
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == g["cid"]).count() == 0


def test_token_BOSHQA_dokonga_ishlamaydi(client, g):
    from app.db.session import SessionLocal
    _seed(client, g, [_row("A", "G1")], snap="T-x")
    tok = _token(client, g)["reset_token"]
    with SessionLocal() as db:
        other, _, _, _ = _mk(db, "g" + uuid.uuid4().hex[:8])
    r = client.post(f"{V2}/reset/execute?company_id={other.id}&reset_token={tok}"
                    f"&confirm_code={other.code}", headers=VENDOR)
    assert r.status_code == 409 and "BOSHQA do'konga" in r.json()["detail"], r.text


def test_graf_ozgarsa_token_KUCHSIZ(client, g, monkeypatch):
    _seed(client, g, [_row("A", "G1")], snap="T-gr")
    tok = _token(client, g)["reset_token"]
    monkeypatch.setattr(catalog_reset, "KNOWN_PRODUCT_REFERRERS",
                        catalog_reset.KNOWN_PRODUCT_REFERRERS | {"yangi_jadval"})
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 409 and "graf" in r.json()["detail"], r.text


# ══ 3. CUTOVER — ANIQ ISHGA BOG'LANISH ═══════════════════════════════════════

def test_cutover_ANIQ_job_id_talab_qiladi(client, g):
    _seed(client, g, [_row("A", "G1")], snap="C-1")
    assert client.post(f"{V2}/cutover-complete", headers=g["H"]).status_code == 422


def test_cutover_COMMITTED_bolmagan_ishni_RAD(client, g):
    from app.db.session import SessionLocal
    r = client.post(f"{V2}/preview", json=_body([_row("A", "G1")], snap="C-2"), headers=g["H"])
    pj = r.json()["job_id"]
    rr = client.post(f"{V2}/cutover-complete?import_job_id={pj}", headers=g["H"])
    assert rr.status_code == 409 and "COMMITTED emas" in rr.json()["detail"], rr.text


def test_cutover_BOSHQA_dokon_ishini_RAD(client, g):
    from app.db.session import SessionLocal
    _seed(client, g, [_row("A", "G1")], snap="C-3")
    with SessionLocal() as db:
        other, _, _, OH = _mk(db, "g" + uuid.uuid4().hex[:8])
    j = _seed(client, {"H": OH, "cid": other.id}, [_row("B", "G2")], snap="C-4")["job_id"]
    r = client.post(f"{V2}/cutover-complete?import_job_id={j}", headers=g["H"])
    assert r.status_code == 404, r.text


def test_cutover_ESKI_snapshot_bilan_yopilmaydi_YANGI_preview_bor(client, g):
    """Yangi preview mavjud bo'lsa, eski snapshot bilan LIVE qilib bo'lmaydi."""
    old = _seed(client, g, [_row("A", "G1")], snap="C-5")["job_id"]
    client.post(f"{V2}/preview", json=_body([_row("A", "G1", sell_price=77.0)], snap="C-6"),
                headers=g["H"])
    r = client.post(f"{V2}/cutover-complete?import_job_id={old}", headers=g["H"])
    assert r.status_code == 409 and "KEYINGI ish" in r.json()["detail"], r.text


def test_cutover_snapshot_va_xeshni_YOZADI(client, g):
    j = _seed(client, g, [_row("A", "G1")], snap="C-7")
    r = client.post(f"{V2}/cutover-complete?import_job_id={j['job_id']}", headers=g["H"])
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["mode"] == "LIVE"
    assert v["last_import_job_id"] == j["job_id"]
    assert v["last_snapshot_id"] == "C-7"
    assert v["last_content_sha256"] == j["content_sha256"]
    assert len(v["last_content_sha256"]) == 64


def test_cutover_manba_mos_kelmasa_RAD(client, g):
    from app.db.session import SessionLocal
    j = _seed(client, g, [_row("A", "G1")], snap="C-8")
    with SessionLocal() as db:
        job = db.get(ImportJob, uuid.UUID(j["job_id"]))
        job.source = "excel"
        db.commit()
    r = client.post(f"{V2}/cutover-complete?import_job_id={j['job_id']}", headers=g["H"])
    assert r.status_code == 409 and "Manba mos emas" in r.json()["detail"], r.text


# ══ 4. XESH — MULTISET ═══════════════════════════════════════════════════════

def _r(**kw):
    d = {"name": "X", "external_id": "G", "sell_price": 10.0, "buy_price": 5.0, "stock": 1.0}
    d.update(kw)
    return ImportRowV2(**d)


def test_xesh_TAKROR_qatorni_YO_QOTMAYDI():
    x = _r()
    assert H([x]) != H([x, x]), "[X] va [X,X] bir xil xesh — multiplik YO'QOLDI"
    assert H([x, x]) != H([x, x, x])


def test_xesh_TARTIBGA_bogliq_emas():
    a, b = _r(name="A", external_id="G1"), _r(name="B", external_id="G2")
    assert H([a, b]) == H([b, a])
    assert H([a, a, b]) != H([a, b, b])


def test_xesh_kanoniklashtirish():
    base = _r(name="A B", external_id="G", sell_price=10.0, buy_price=5.0, stock=1.0)
    assert H([base]) == H([_r(name="  A   B  ", external_id=" G ",
                              sell_price=10, buy_price=5.00, stock=1.000)])
    c1 = _r(barcodes=["111111", "222222"])
    c2 = _r(barcodes=["222222", "111111", "222222"])
    assert H([c1]) == H([c2]), "barkod tartibi/takrori xeshni o'zgartirdi"
    assert H([_r(sell_price=10.0)]) != H([_r(sell_price=10.01)])


# ══ 5. RESET AVTORIZATSIYASI ═════════════════════════════════════════════════

def test_reset_DOKON_XODIMI_uchun_YOPIQ(client, g):
    """Eng muhim salbiy nazorat: `sozlamalar.edit` YETARLI EMAS."""
    from app.db.session import SessionLocal
    _seed(client, g, [_row("A", "G1")], snap="A-1")
    tok = _token(client, g)["reset_token"]
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=g["H"])      # xodim tokeni
    assert r.status_code in (401, 403), r.text
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == g["cid"]).count() == 1


def test_reset_AVTORIZATSIYASIZ_YOPIQ(client, g):
    _seed(client, g, [_row("A", "G1")], snap="A-2")
    tok = _token(client, g)["reset_token"]
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}")
    assert r.status_code in (401, 403), r.text


def test_reset_XATO_vendor_kaliti_YOPIQ(client, g):
    _seed(client, g, [_row("A", "G1")], snap="A-3")
    tok = _token(client, g)["reset_token"]
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers={"X-Vendor-Key": "notogri"})
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("platforma", ["RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID"])
def test_reset_MUHIT_BELGISI_YO_Q_bolsa_YOPIQ(monkeypatch, platforma):
    """PRODUCTION'DAGI HAQIQIY HOLAT: `APP_ENV` UMUMAN o'rnatilmagan.

    Eski kod `(os.getenv("APP_ENV") or "dev")` deb yozilgani uchun bu holat
    "dev" deb hisoblanardi va reset production'da OCHIQ edi. Eski sinov buni
    ko'rmadi: u `APP_ENV=production` ni ANIQ qo'yib tekshirardi, ya'ni
    production'ning HAQIQIY konfiguratsiyasini emas, TAXMINNI sinardi.
    """
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv(platforma, "production")      # boshqariladigan platforma signali
    assert catalog_reset.execution_allowed() is False


def test_reset_MUHIT_BELGISI_YO_Q_bolsa_ENDPOINT_ham_RAD(client, g, monkeypatch):
    """Belgisiz boshqariladigan muhitda endpoint ham o'chirmaydi.

    Bu yerda javob 401 (vendor) yoki 403 (muhit) bo'lishi mumkin — boshqariladigan
    muhitda xom vendor kaliti ham qabul qilinmaydi. MUHIMI: amal BAJARILMAYDI.
    """
    _seed(client, g, [_row("A", "G1")], snap="ENV-1")
    tok = _token(client, g)["reset_token"]
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code in (401, 403), r.text
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == g["cid"]).count() == 1


@pytest.mark.parametrize("env", ["dev", "test", "staging"])
def test_reset_ANIQ_belgi_bilan_OCHIQ(monkeypatch, env):
    """Musbat nazorat: tuzatish resetni HAMMA JOYDA yopib qo'ymadi.

    Bu bo'lmasa `execution_allowed()` ni doim False qilib qo'yish ham sinovni
    yashil qoldirardi va staging'dagi mashqlar jimgina o'lik bo'lardi.
    """
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", env)   # boshqariladigan bo'lsa ham
    assert catalog_reset.execution_allowed() is True


def test_reset_production_da_YOPIQ_vendor_bolsa_ham(client, g, monkeypatch):
    _seed(client, g, [_row("A", "G1")], snap="A-4")
    tok = _token(client, g)["reset_token"]
    monkeypatch.setenv("APP_ENV", "production")
    r = client.post(f"{V2}/reset/execute?company_id={g['cid']}&reset_token={tok}"
                    f"&confirm_code={g['code']}", headers=VENDOR)
    assert r.status_code == 403, r.text
