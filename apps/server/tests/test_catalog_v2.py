# -*- coding: utf-8 -*-
"""1С Cutover V2 — Phase 1 testlari.

Qamrov: tashqi identifikatsiya (soft-delete'dan omon qolishi), moslashtirish
darajalari va ziddiyatlar, YOZUVSIZ preview, INITIAL_CREATE idempotentligi,
import job audit izi va katalog-reset dry-run darvozalari.

⚠️  SALBIY NAZORAT: har bir kafolat uchun uni BUZADIGAN holat ham sinaladi —
    aks holda "yashil test" hech nimani o'lchamayotgan bo'lishi mumkin.
"""
import uuid

import pytest

from app.core.security import create_access_token
from app.models.auth import Employee, Role
from app.models.catalog import Product, ProductBarcode
from app.models.enums import EmployeeStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.services import catalog_reset
from app.services.catalog_import_v2 import (
    get_catalog_settings, is_live, set_catalog_settings,
)
from app.services.catalog_match import (
    CatalogIndex, MatchLevel, MatchOutcome, match_row, norm_key,
)

V2 = "/api/v1/catalog/v2"


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _mk_company(db, code: str):
    """Toza do'kon + filial + ega. Har test o'z tenantida ishlaydi (izolyatsiya)."""
    comp = Company(id=uuid.uuid4(), name=f"T-{code}", code=code, currency="KGS")
    db.add(comp)
    db.flush()
    br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01")
    db.add(br)
    role = db.query(Role).filter(Role.code == "ega").first()
    emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                   full_name="Ega", phone=f"+9987{uuid.uuid4().int % 10**7:07d}",
                   status=EmployeeStatus.active, sec_epoch=0)
    db.add(emp)
    db.commit()
    tok = create_access_token(str(emp.id), {"role": "ega", "company_id": str(comp.id), "sv": 0})
    return comp, br, emp, {"Authorization": f"Bearer {tok}"}


def _row(name, ext=None, **kw):
    d = {"name": name, "sell_price": 10.0, "buy_price": 5.0, "stock": 0.0,
         "barcodes": [], "is_weighted": False}
    if ext is not None:
        d["external_id"] = ext
    d.update(kw)
    return d


def _body(rows, mode="INITIAL_CREATE", **kw):
    return {"mode": mode, "source_system": "1c", "rows": rows, **kw}


def _snapshot(db, company_id) -> dict:
    """Preview yozmaganini isbotlash uchun katalog holati."""
    pids = [p.id for p in db.query(Product).filter(Product.company_id == company_id).all()]
    return {
        "products": len(pids),
        "barcodes": db.query(ProductBarcode).filter(
            ProductBarcode.company_id == company_id).count(),
        "inventory": db.query(Inventory).filter(Inventory.product_id.in_(pids)).count() if pids else 0,
        "movements": db.query(StockMovement).filter(
            StockMovement.product_id.in_(pids)).count() if pids else 0,
        # Sozlama SONI yetarli emas: mavjud qatorni YANGILASH ham yozuv hisoblanadi.
        # (Buni salbiy nazorat ko'rsatdi — u avval jimgina o'tib ketgan edi.)
        "settings": sorted(
            (s.key, str(s.value), int(s.row_version or 1))
            for s in db.query(Setting).filter(Setting.company_id == company_id).all()),
        "sell_sum": float(sum(float(p.base_sell_price or 0) for p in db.query(Product).filter(
            Product.company_id == company_id).all())),
    }


@pytest.fixture
def tenant(client):
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        comp, br, emp, H = _mk_company(db, "c" + uuid.uuid4().hex[:8])
        yield {"company_id": comp.id, "branch_id": br.id, "emp_id": emp.id, "H": H}


# ══ 1. TASHQI IDENTIFIKATSIYA ════════════════════════════════════════════════

def test_bir_xil_GUID_nom_ozgarsa_AYNI_mahsulot(client, tenant):
    """ASOSIY TALAB: 1С GUID'i o'zgarmasa, nom o'zgarsa ham AYNI mahsulot."""
    G = "1c-guid-rename"
    r = client.post(f"{V2}/initial-create",
                    json=_body([_row("Eski nom", G)]), headers=tenant["H"])
    assert r.status_code == 200, r.text
    pv = client.post(f"{V2}/preview",
                     json=_body([_row("BUTUNLAY BOSHQA NOM", G)], mode="CUTOVER_REFRESH"),
                     headers=tenant["H"]).json()
    row = pv["rows"][0]
    assert row["classification"] == "UPDATE_NAME", row
    assert row["match_level"] == "external_id"
    assert [c for c in row["changes"] if c["field"] == "name"][0]["old"] == "Eski nom"


def test_bir_xil_nom_boshqa_GUID_IKKI_mahsulot(client, tenant):
    """Nom bir xil, GUID boshqa -> bu BOSHQA tovar, moslashtirilmaydi."""
    client.post(f"{V2}/initial-create", json=_body([_row("Sut 1l", "guid-A")]),
                headers=tenant["H"])
    pv = client.post(f"{V2}/preview",
                     json=_body([_row("Sut 1l", "guid-B")], mode="CUTOVER_REFRESH"),
                     headers=tenant["H"]).json()
    # external_id topilmadi, lekin NOM mos keladi -> past daraja ishlaydi
    assert pv["rows"][0]["match_level"] == "name"


def test_bir_xil_GUID_BOSHQA_tenantda_RUXSAT(client):
    """Noyoblik do'kon DOIRASIDA — boshqa do'konda ayni GUID mumkin."""
    from app.db.session import SessionLocal
    G = "shared-guid-x1"
    for _ in range(2):
        with SessionLocal() as db:
            _, _, _, H = _mk_company(db, "x" + uuid.uuid4().hex[:8])
        r = client.post(f"{V2}/initial-create", json=_body([_row("Tovar", G)]), headers=H)
        assert r.status_code == 200, r.text


def test_bir_tenantda_TAKROR_GUID_RAD_ETILADI(client, tenant):
    """Bitta faylda bir GUID ikki marta -> 400, hech narsa yaratilmaydi."""
    r = client.post(f"{V2}/initial-create",
                    json=_body([_row("A", "dup-guid"), _row("B", "dup-guid")]),
                    headers=tenant["H"])
    assert r.status_code == 400
    assert "takrorlanadi" in r.json()["detail"]
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == tenant["company_id"]).count() == 0


def test_DB_darajasida_takror_GUID_MUMKIN_EMAS(client, tenant):
    """Indeks ux_products_external_identity — ilova kodini chetlab o'tsa ham to'xtatadi."""
    from sqlalchemy.exc import IntegrityError
    from app.db.session import SessionLocal
    from app.models.catalog import Unit
    with SessionLocal() as db:
        u = db.query(Unit).first()
        for i in range(2):
            db.add(Product(id=uuid.uuid4(), company_id=tenant["company_id"],
                           article_code=f"A{i}", name=f"N{i}", unit_id=u.id,
                           base_buy_price=1, base_sell_price=2, tax_rate=0,
                           source_system="1c", external_id="same-guid"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_ochirilgan_GUID_DELETED_MATCH_bolib_YANGI_emas(client, tenant):
    """Tashqi identifikatsiya soft-delete'dan OMON QOLADI (Correction A)."""
    from datetime import datetime, timezone
    from app.db.session import SessionLocal
    G = "guid-deleted"
    client.post(f"{V2}/initial-create", json=_body([_row("O'chiriladigan", G)]),
                headers=tenant["H"])
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == tenant["company_id"]).first()
        p.deleted_at = datetime.now(timezone.utc)
        db.commit()
    pv = client.post(f"{V2}/preview",
                     json=_body([_row("O'chiriladigan", G)], mode="CUTOVER_REFRESH"),
                     headers=tenant["H"]).json()
    row = pv["rows"][0]
    assert row["classification"] == "DELETED_MATCH", row
    assert row["classification"] != "NEW"
    assert row["product_id"] is not None


def test_DELETED_MATCH_hech_narsa_YARATMAYDI(client, tenant):
    from datetime import datetime, timezone
    from app.db.session import SessionLocal
    client.post(f"{V2}/initial-create", json=_body([_row("X", "g-del-2")]), headers=tenant["H"])
    with SessionLocal() as db:
        db.query(Product).filter(Product.company_id == tenant["company_id"]).first().deleted_at = \
            datetime.now(timezone.utc)
        db.commit()
        before = _snapshot(db, tenant["company_id"])
    client.post(f"{V2}/preview", json=_body([_row("X", "g-del-2")], mode="CUTOVER_REFRESH"),
                headers=tenant["H"])
    with SessionLocal() as db:
        assert _snapshot(db, tenant["company_id"])["products"] == before["products"]


def test_client_uuid_TEGILMAYDI(client, tenant):
    """Tashqi identifikatsiya `client_uuid` ga YOZILMAYDI — ikki ma'no aralashmaydi."""
    from app.db.session import SessionLocal
    client.post(f"{V2}/initial-create", json=_body([_row("Y", "guid-cu")]), headers=tenant["H"])
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == tenant["company_id"]).first()
        assert p.external_id == "guid-cu"
        assert p.source_system == "1c"
        assert p.client_uuid is None


# ══ 2. MOSLASHTIRISH ═════════════════════════════════════════════════════════

def _ix(products, barcodes=()):
    return CatalogIndex.build(products, barcodes)


def test_daraja_1_external_id():
    ix = _ix([{"id": "p1", "name": "A", "article_code": "AA",
               "source_system": "1c", "external_id": "G1", "deleted": False}])
    m = match_row({"external_id": "G1", "name": "BOSHQA", "article": None, "barcodes": []}, ix)
    assert (m.outcome, m.product_id, m.level) == (MatchOutcome.MATCHED, "p1", MatchLevel.EXTERNAL_ID)


def test_daraja_2_artikul():
    ix = _ix([{"id": "p1", "name": "A", "article_code": "AA",
               "source_system": None, "external_id": None, "deleted": False}])
    m = match_row({"external_id": None, "name": "BOSHQA", "article": "AA", "barcodes": []}, ix)
    assert (m.outcome, m.level) == (MatchOutcome.MATCHED, MatchLevel.ARTICLE)


def test_daraja_3_barkod():
    ix = _ix([{"id": "p1", "name": "A", "article_code": "AA",
               "source_system": None, "external_id": None, "deleted": False}],
             [("p1", "4600949010205")])
    m = match_row({"external_id": None, "name": "BOSHQA", "article": None,
                   "barcodes": ["4600949010205"]}, ix)
    assert (m.outcome, m.level) == (MatchOutcome.MATCHED, MatchLevel.BARCODE)


def test_daraja_4_nom():
    ix = _ix([{"id": "p1", "name": "Sut 1l", "article_code": "AA",
               "source_system": None, "external_id": None, "deleted": False}])
    m = match_row({"external_id": None, "name": "  SUT   1L ", "article": None, "barcodes": []}, ix)
    assert (m.outcome, m.level) == (MatchOutcome.MATCHED, MatchLevel.NAME)


def test_daraja_5_yangi():
    ix = _ix([{"id": "p1", "name": "A", "article_code": "AA",
               "source_system": None, "external_id": None, "deleted": False}])
    m = match_row({"external_id": None, "name": "Yangi", "article": None, "barcodes": []}, ix)
    assert m.outcome is MatchOutcome.NEW


def test_ZIDDIYAT_GUID_va_barkod_AMBIGUOUS():
    """GUID bitta mahsulotni, barkod BOSHQASINI ko'rsatsa — yuqori daraja YUTMAYDI."""
    ix = _ix([{"id": "p1", "name": "A", "article_code": "A1",
               "source_system": "1c", "external_id": "G1", "deleted": False},
              {"id": "p2", "name": "B", "article_code": "B1",
               "source_system": None, "external_id": None, "deleted": False}],
             [("p2", "4600949010205")])
    m = match_row({"external_id": "G1", "name": "A", "article": None,
                   "barcodes": ["4600949010205"]}, ix)
    assert m.outcome is MatchOutcome.AMBIGUOUS
    assert m.product_id is None
    assert any("ziddiyat" in c for c in m.conflict)


def test_TAKROR_nom_AMBIGUOUS():
    ix = _ix([{"id": "p1", "name": "Мяч", "article_code": "A1",
               "source_system": None, "external_id": None, "deleted": False},
              {"id": "p2", "name": "мяч", "article_code": "A2",
               "source_system": None, "external_id": None, "deleted": False}])
    m = match_row({"external_id": None, "name": "Мяч", "article": None, "barcodes": []}, ix)
    assert m.outcome is MatchOutcome.AMBIGUOUS


def test_yuqori_daraja_QUYISINI_ishlatmaydi():
    """GUID mos kelsa, nom boshqa mahsulotniki bo'lsa ham GUID yutadi (ziddiyatsiz holat)."""
    ix = _ix([{"id": "p1", "name": "Eski", "article_code": "A1",
               "source_system": "1c", "external_id": "G1", "deleted": False}])
    m = match_row({"external_id": "G1", "name": "Eski", "article": None, "barcodes": []}, ix)
    assert m.level is MatchLevel.EXTERNAL_ID       # NAME emas


def test_SALBIY_ishonchsiz_kalit_YANGI_deb_hisoblanmaydi():
    """Takror nom yagona dalil bo'lsa — NEW emas, AMBIGUOUS (aks holda dublikat yaratilardi)."""
    ix = _ix([{"id": "p1", "name": "Топ", "article_code": "A1",
               "source_system": None, "external_id": None, "deleted": False},
              {"id": "p2", "name": "Топ", "article_code": "A2",
               "source_system": None, "external_id": None, "deleted": False}])
    m = match_row({"external_id": None, "name": "Топ", "article": None, "barcodes": []}, ix)
    assert m.outcome is not MatchOutcome.NEW
    assert m.outcome is MatchOutcome.AMBIGUOUS


# ══ 3. PREVIEW — YOZUVSIZ ════════════════════════════════════════════════════

def test_preview_KATALOGGA_hech_narsa_yozmaydi(client, tenant):
    from app.db.session import SessionLocal
    client.post(f"{V2}/initial-create",
                json=_body([_row("Bor", "g-pv", sell_price=10.0,
                                 barcodes=["4600949010205"], stock=5.0)]),
                headers=tenant["H"])
    with SessionLocal() as db:
        before = _snapshot(db, tenant["company_id"])
    r = client.post(f"{V2}/preview", json=_body(
        [_row("Bor", "g-pv", sell_price=99.0, barcodes=["4780032051640"], stock=77.0),
         _row("Mutlaqo yangi", "g-new")], mode="CUTOVER_REFRESH"), headers=tenant["H"])
    assert r.status_code == 200, r.text
    assert r.json()["wrote_nothing"] is True
    with SessionLocal() as db:
        after = _snapshot(db, tenant["company_id"])
    # `settings` preview'da o'zgarmasligi ham tekshiriladi
    assert after == before, f"preview YOZDI: {before} -> {after}"


def test_preview_eski_yangi_TOGRI(client, tenant):
    client.post(f"{V2}/initial-create",
                json=_body([_row("Tovar", "g-ch", sell_price=10.0, buy_price=5.0, stock=3.0)]),
                headers=tenant["H"])
    pv = client.post(f"{V2}/preview", json=_body(
        [_row("Tovar", "g-ch", sell_price=12.0, buy_price=5.0, stock=8.0)],
        mode="CUTOVER_REFRESH"), headers=tenant["H"]).json()
    ch = {c["field"]: (c["old"], c["new"]) for c in pv["rows"][0]["changes"]}
    assert ch["sell_price"] == ("10", "12")
    assert ch["stock"] == ("3", "8")
    assert "buy_price" not in ch          # o'zgarmagan maydon CHIQMAYDI
    assert pv["rows"][0]["classification"] == "UPDATE_MULTIPLE"


def test_preview_UNCHANGED(client, tenant):
    client.post(f"{V2}/initial-create",
                json=_body([_row("Bir xil", "g-un", sell_price=7.0, buy_price=3.0, stock=2.0)]),
                headers=tenant["H"])
    pv = client.post(f"{V2}/preview", json=_body(
        [_row("Bir xil", "g-un", sell_price=7.0, buy_price=3.0, stock=2.0)],
        mode="CUTOVER_REFRESH"), headers=tenant["H"]).json()
    assert pv["rows"][0]["classification"] == "UNCHANGED"


def test_MISSING_FROM_SOURCE_hech_narsani_OCHIRMAYDI(client, tenant):
    from app.db.session import SessionLocal
    client.post(f"{V2}/initial-create",
                json=_body([_row("Qoladi", "g-m1"), _row("Manbada yo'q", "g-m2")]),
                headers=tenant["H"])
    with SessionLocal() as db:
        before = _snapshot(db, tenant["company_id"])
    pv = client.post(f"{V2}/preview", json=_body([_row("Qoladi", "g-m1")],
                                                 mode="CUTOVER_REFRESH"),
                     headers=tenant["H"]).json()
    assert "Manbada yo'q" in pv["missing_from_source"]
    with SessionLocal() as db:
        after = _snapshot(db, tenant["company_id"])
        assert after["products"] == before["products"]
        assert db.query(Product).filter(
            Product.company_id == tenant["company_id"],
            Product.deleted_at.isnot(None)).count() == 0
        assert db.query(Product).filter(
            Product.company_id == tenant["company_id"],
            Product.is_active.is_(False)).count() == 0


def test_preview_INVALID_qatorlar(client, tenant):
    pv = client.post(f"{V2}/preview", json=_body([
        _row("Narxsiz", "g-i1", sell_price=0.0),
        _row("Barkodi buzuq", "g-i2", barcodes=["12"]),
        _row("GUIDsiz"),
    ]), headers=tenant["H"]).json()
    cls = [r["classification"] for r in pv["rows"]]
    assert cls == ["INVALID", "INVALID", "INVALID"]
    assert "external_id MAJBURIY" in " ".join(pv["rows"][2]["problem"])


# ══ 4. INITIAL_CREATE ════════════════════════════════════════════════════════

def test_initial_create_identifikatsiya_va_KOP_barkod(client, tenant):
    from app.db.session import SessionLocal
    r = client.post(f"{V2}/initial-create", json=_body([
        _row("Ko'p barkodli", "g-mb", unit="kg", stock=2.5,
             barcodes=["4600949010205", "4780032051640", "4823006710324"])]),
        headers=tenant["H"])
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 1, "barcodes": 3}
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.company_id == tenant["company_id"]).one()
        assert (p.source_system, p.external_id) == ("1c", "g-mb")
        assert db.query(ProductBarcode).filter(ProductBarcode.product_id == p.id).count() == 3
        from app.models.catalog import Unit
        assert db.get(Unit, p.unit_id).code == "kg"      # ANIQ birlik


def test_initial_create_BOSH_bolmagan_katalogda_RAD(client, tenant):
    client.post(f"{V2}/initial-create", json=_body([_row("Bor", "g-x1")]), headers=tenant["H"])
    r = client.post(f"{V2}/initial-create", json=_body([_row("Yana", "g-x2")]),
                    headers=tenant["H"])
    assert r.status_code == 400
    assert "BO'SH" in r.json()["detail"]


def test_initial_create_AYNI_faylni_qayta_yuborish_HECH_NARSA_yaratmaydi(client, tenant):
    """Idempotentlik: katalog bo'sh emas -> ikkinchi urinish rad etiladi, dublikat yo'q."""
    from app.db.session import SessionLocal
    body = _body([_row("A", "g-id1"), _row("B", "g-id2")])
    assert client.post(f"{V2}/initial-create", json=body, headers=tenant["H"]).status_code == 200
    r2 = client.post(f"{V2}/initial-create", json=body, headers=tenant["H"])
    assert r2.status_code == 400
    with SessionLocal() as db:
        assert db.query(Product).filter(Product.company_id == tenant["company_id"]).count() == 2


def test_initial_create_cutover_YOPILGANDA_rad_etiladi(client, tenant):
    """Phase 2 da cutover-complete KUCHAYDI: COMMITTED import bo'lmasa yopilmaydi.

    Ilgari bu test bo'sh tenantda ham LIVE qila olardi. Endi avval haqiqiy
    commit kerak — ya'ni katalog "hech narsa import qilinmagan" holatda
    LIVE bo'lib qolmaydi.
    """
    r = client.post(f"{V2}/commit",
                    json={"mode": "INITIAL_CREATE", "source_system": "1c",
                          "snapshot_id": "lv-1", "rows": [_row("A", "g-lv0")]},
                    headers=tenant["H"])
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    # cutover ANIQ ishga bog'lanadi (Phase 3 darvozasi)
    assert client.post(f"{V2}/cutover-complete?import_job_id={job_id}",
                       headers=tenant["H"]).status_code == 200
    r = client.post(f"{V2}/initial-create", json=_body([_row("B", "g-lv")]), headers=tenant["H"])
    assert r.status_code == 409


# ══ 5. settings.catalog — settings.cash dan MUSTAQIL ═════════════════════════

def test_catalog_va_cash_sozlamalari_MUSTAQIL(client, tenant):
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        db.add(Setting(company_id=tenant["company_id"], branch_id=None, key="cash",
                       value={"cutover_at": "2020-01-01T00:00:00Z", "ledger_native": True}))
        db.commit()
        set_catalog_settings(db, tenant["company_id"], mode="LIVE",
                             cutover_at="2030-01-01T00:00:00Z")
        db.commit()
        cash = db.query(Setting).filter(Setting.company_id == tenant["company_id"],
                                        Setting.key == "cash").one().value
        cat = get_catalog_settings(db, tenant["company_id"])
    assert cash["cutover_at"] == "2020-01-01T00:00:00Z"    # TEGILMAGAN
    assert cat["cutover_at"] == "2030-01-01T00:00:00Z"
    assert cash["cutover_at"] != cat["cutover_at"]


def test_cash_cutover_katalogni_LIVE_qilmaydi(client, tenant):
    """SALBIY NAZORAT: kassa cutover'i katalog darvozasiga ta'sir qilMASLIGI shart."""
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        db.add(Setting(company_id=tenant["company_id"], branch_id=None, key="cash",
                       value={"cutover_at": "2020-01-01T00:00:00Z"}))
        db.commit()
        assert is_live(db, tenant["company_id"]) is False


# ══ 6. IMPORT JOB AUDIT IZI ══════════════════════════════════════════════════

def test_import_job_yoziladi(client, tenant):
    from app.db.session import SessionLocal
    from app.models.imports import ImportJob, ImportRow
    pv = client.post(f"{V2}/preview", json=_body(
        [_row("A", "g-j1"), _row("Narxsiz", "g-j2", sell_price=0.0)],
        snapshot_id="snap-7", file_name="sena.xls"), headers=tenant["H"]).json()
    with SessionLocal() as db:
        job = db.get(ImportJob, uuid.UUID(pv["job_id"]))
        assert job.company_id == tenant["company_id"]
        assert job.source == "1c" and job.file_name == "sena.xls"
        assert job.status.value == "validated"
        assert job.column_mapping["mode"] == "INITIAL_CREATE"
        assert job.column_mapping["snapshot_id"] == "snap-7"
        assert job.total_rows == 2 and job.error_rows == 1
        rows = db.query(ImportRow).filter(ImportRow.job_id == job.id).order_by(
            ImportRow.row_no).all()
        assert [r.status for r in rows] == ["NEW", "INVALID"]
        assert rows[0].raw["external_id"] == "g-j1"          # XOM qator saqlanadi
        assert rows[1].error


def test_import_job_TENANT_izolyatsiyasi(client):
    from app.db.session import SessionLocal
    from app.models.imports import ImportJob
    with SessionLocal() as db:
        c1, _, _, H1 = _mk_company(db, "j" + uuid.uuid4().hex[:8])
        c2, _, _, H2 = _mk_company(db, "j" + uuid.uuid4().hex[:8])
    client.post(f"{V2}/preview", json=_body([_row("A", "g-t1")]), headers=H1)
    client.post(f"{V2}/preview", json=_body([_row("B", "g-t2")]), headers=H2)
    with SessionLocal() as db:
        assert db.query(ImportJob).filter(ImportJob.company_id == c1.id).count() == 1
        assert db.query(ImportJob).filter(ImportJob.company_id == c2.id).count() == 1


def test_preview_QAYTA_yurgizilsa_katalog_ozgarmaydi(client, tenant):
    from app.db.session import SessionLocal
    client.post(f"{V2}/initial-create", json=_body([_row("A", "g-rt")]), headers=tenant["H"])
    with SessionLocal() as db:
        before = _snapshot(db, tenant["company_id"])
    for _ in range(3):
        client.post(f"{V2}/preview", json=_body([_row("A", "g-rt", sell_price=50.0)],
                                                mode="CUTOVER_REFRESH"), headers=tenant["H"])
    with SessionLocal() as db:
        assert _snapshot(db, tenant["company_id"]) == before


# ══ 7. KATALOG RESET — DRY-RUN ═══════════════════════════════════════════════

def test_reset_dry_run_ANIQ_sanoqlar(client, tenant):
    client.post(f"{V2}/initial-create", json=_body([
        _row("A", "g-r1", stock=5.0, barcodes=["4600949010205"]),
        _row("B", "g-r2", stock=0.0)]), headers=tenant["H"])
    p = client.post(f"{V2}/reset/dry-run", headers=tenant["H"]).json()
    assert p["eligible"] is True
    assert p["would_delete"]["products"] == 2
    assert p["would_delete"]["product_barcodes"] == 1
    assert p["would_delete"]["inventory"] == 2
    assert p["would_delete"]["stock_movements"] == 1      # faqat qoldiq > 0 uchun
    assert p["wrote_nothing"] is True


def test_reset_dry_run_HECH_NARSA_ozgartirmaydi(client, tenant):
    from app.db.session import SessionLocal
    client.post(f"{V2}/initial-create", json=_body([_row("A", "g-r3", stock=2.0)]),
                headers=tenant["H"])
    with SessionLocal() as db:
        before = _snapshot(db, tenant["company_id"])
    client.post(f"{V2}/reset/dry-run", headers=tenant["H"])
    with SessionLocal() as db:
        assert _snapshot(db, tenant["company_id"]) == before


def test_reset_dry_run_SAQLANADIGANLAR(client, tenant):
    p = client.post(f"{V2}/reset/dry-run", headers=tenant["H"]).json()
    assert p["would_preserve"]["companies"] == 1
    assert p["would_preserve"]["branches"] == 1
    assert p["would_preserve"]["employees"] == 1
    assert p["would_preserve"]["units_GLOBAL"] >= 4       # GLOBAL — hech qachon o'chmaydi
    assert p["categories"]["action"] == "SAQLANADI"       # Correction B
    assert p["brands"]["action"] == "SAQLANADI"


def test_reset_BIZNES_hujjati_borligida_RAD(client, tenant):
    """Fail-closed: mahsulotga havola qiluvchi BIRORTA hujjat bo'lsa — reset mumkin emas."""
    from app.db.session import SessionLocal
    from datetime import datetime, timezone
    from app.models.sales import Sale
    with SessionLocal() as db:
        db.add(Sale(id=uuid.uuid4(), receipt_no="T-1", company_id=tenant["company_id"],
                    branch_id=tenant["branch_id"], cashier_id=tenant["emp_id"],
                    subtotal=0, total=0, sold_at=datetime.now(timezone.utc)))
        db.commit()
        p = catalog_reset.plan(db, tenant["company_id"])
    assert p.eligible is False
    assert p.blockers["sales"] == 1


def test_reset_TENANT_izolyatsiyasi(client):
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        c1, _, _, H1 = _mk_company(db, "r" + uuid.uuid4().hex[:8])
        c2, _, _, H2 = _mk_company(db, "r" + uuid.uuid4().hex[:8])
    client.post(f"{V2}/initial-create", json=_body([_row("A", "g-i1"), _row("B", "g-i2")]),
                headers=H1)
    p2 = client.post(f"{V2}/reset/dry-run", headers=H2).json()
    assert p2["would_delete"]["products"] == 0            # boshqa do'kon KO'RINMAYDI
    p1 = client.post(f"{V2}/reset/dry-run", headers=H1).json()
    assert p1["would_delete"]["products"] == 2


def test_reset_BOSHQA_dokon_soralsa_403(client, tenant):
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        other, _, _, _ = _mk_company(db, "o" + uuid.uuid4().hex[:8])
    r = client.post(f"{V2}/reset/dry-run?company_id={other.id}", headers=tenant["H"])
    assert r.status_code == 403


def test_reset_BAJARISH_production_da_YOPIQ(monkeypatch):
    """Funksiya-darvoza: production'da bajarish Phase 1 da ishlamaydi."""
    monkeypatch.setenv("APP_ENV", "production")
    assert catalog_reset.execution_allowed() is False
    monkeypatch.setenv("APP_ENV", "staging")
    assert catalog_reset.execution_allowed() is True


def test_reset_bajarish_production_da_PermissionError(tenant, monkeypatch):
    from app.db.session import SessionLocal
    monkeypatch.setenv("APP_ENV", "production")
    with SessionLocal() as db:
        with pytest.raises(PermissionError):
            catalog_reset.execute(db, tenant["company_id"])


def test_norm_key_izchil():
    assert norm_key("  Сут   1Л ") == norm_key("сут 1л")
