# -*- coding: utf-8 -*-
"""Migrator V1 — mapping, APPLY semantikasi, idempotentlik va darvozalar (SQLite).

Postgres-ga xos kafolatlar (qulf, parallel apply, Numeric, read-only sessiya, majburiy sysid) —
`test_migrator_1c_pg.py` da (CI: PostgreSQL 18). Har `Review #N` — adversarial review topilmasining
regressiya testi: tuzatishdan OLDIN yiqilgan holat.
"""
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.catalog import Product, ProductBarcode
from app.models.enums import ImportStatus
from app.models.imports import ImportJob
from app.models.inventory import Inventory, StockMovement
from app.services.migrator_1c import classify as C
from app.services.migrator_1c.apply import (AlreadyApplied, DriftError, StaleSnapshotError, apply_migration,
                                            verify_state)
from app.services.migrator_1c.catalog import load_snapshot
from app.services.migrator_1c.guard import ApplyForbidden, assert_apply_allowed, environment_allows_apply
from app.services.migrator_1c.mapping import MappingError, build_plan, build_template
from tests.migrator_1c_helpers import add_product, bundle_dict, g, load, mapping_for, prod, seed_company


@pytest.fixture
def db(client):
    from app.db.session import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _review(db, comp, products, **kw):
    b = load(bundle_dict(products, **kw))
    rep = C.classify(b, load_snapshot(db, comp.code))
    db.rollback()
    return b, rep


def _counts(db, comp):
    pids = [p.id for p in db.query(Product).filter(Product.company_id == comp.id).all()]
    return {"products": len(pids),
            "barcodes": db.query(ProductBarcode).filter(ProductBarcode.company_id == comp.id).count(),
            "movements": db.query(StockMovement).filter(StockMovement.product_id.in_(pids)).count() if pids else 0,
            "jobs": db.query(ImportJob).filter(ImportJob.company_id == comp.id).count(),
            "fp": load_snapshot(db, comp.code).fingerprint}


def _problems(rep, m) -> str:
    with pytest.raises(MappingError) as e:
        build_plan(rep, m)
    return " | ".join(e.value.problems)


def _inv(db, pid, bid):
    r = db.query(Inventory).filter(Inventory.product_id == pid, Inventory.branch_id == bid).first()
    return None if r is None else Decimal(r.qty)


def _add_inv(db, p, br, qty):
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal(qty), min_qty=0,
                     updated_at=datetime.now(timezone.utc)))
    db.flush()


def _bcs(db, pid):
    return {x.barcode for x in db.query(ProductBarcode).filter(ProductBarcode.product_id == pid)}


def _scenario(db):
    comp, (br,) = seed_company(db)
    legacy_bc = add_product(db, comp, br, "Legacy barkodli", barcodes=["4600000000017"], qty="10")
    exact = add_product(db, comp, br, "Exact eski nom", guid=g(2), qty="4", sell="70.00")
    gone = add_product(db, comp, br, "Faqat BinOS", qty="6")
    db.commit()
    products = [
        prod(g(1), "1C barkodli nomi", barcodes=["4600000000017", "4600000000024"], stock=("12.500",), retail="150.50"),
        prod(g(2), "Exact eski nom", stock=("0",), retail="75.00"),
        prod(g(3), "Yangi tovar", code="0000123", article="00000456", barcodes=["0012345678905"],
             stock=("-3",), retail="999.99", purchase="555.55"),
        prod(g(4), "Narxsiz exact bo'lmagan yangi", retail=None, stock=("1",)),
    ]
    return comp, br, legacy_bc, exact, gone, products


def test_toliq_cutover_semantikasi(db):
    comp, br, legacy_bc, exact, gone, products = _scenario(db)
    b, rep = _review(db, comp, products)
    assert [r["classification"] for r in sorted(rep["rows"], key=lambda r: r["guid"])] == \
        ["CANDIDATE", "EXACT_MATCH", "NEW", "NEW"]
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(legacy_bc.id)}},
                    policies={"binos_missing_from_source": "deactivate_and_zero", "missing_price": "skip_row"})
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"], out
    assert out["expected"]["link"] == 2 and out["expected"]["create"] == 1 and out["skipped"] == 1
    assert out["expected"]["deactivate"] == 1

    db.expire_all()
    p1 = db.get(Product, legacy_bc.id)
    assert (p1.source_system, p1.external_id) == ("1c", g(1))
    assert p1.base_sell_price == Decimal("150.50") and p1.name == "Legacy barkodli"      # nom BinOS'dagi (policy)
    new = db.query(Product).filter(Product.company_id == comp.id, Product.external_id == g(3)).one()
    assert (new.article_code, new.sku) == ("00000456", "0000123")                           # oldingi nollar
    assert new.base_sell_price == Decimal("999.99") and new.base_buy_price == Decimal("555.55")
    assert _bcs(db, new.id) == {"0012345678905"}
    assert _bcs(db, p1.id) == {"4600000000017", "4600000000024"}
    assert db.query(Product).filter(Product.company_id == comp.id, Product.external_id == g(4)).count() == 0

    assert _inv(db, p1.id, br.id) == Decimal("12.500")
    assert _inv(db, exact.id, br.id) == Decimal("0")
    assert _inv(db, new.id, br.id) == Decimal("0")                                           # manfiy -> zero (policy)
    g_ = db.get(Product, gone.id)
    assert g_.is_active is False and _inv(db, gone.id, br.id) == Decimal("0") and g_.deleted_at is None

    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    assert job.status is ImportStatus.committed and job.hash_contract_version == 2
    mv = db.query(StockMovement).filter(StockMovement.ref_id == job.id).all()
    assert all(m.ref_type == "1c_cutover" for m in mv)
    opening = [m for m in mv if m.reason.startswith("CUTOVER_OPENING_BALANCE")]
    close = [m for m in mv if m.reason.startswith("CUTOVER_LEGACY_CLOSE ")]
    missing = [m for m in mv if m.reason.startswith("CUTOVER_LEGACY_CLOSE_NOT_IN_1C")]
    assert [(m.product_id, Decimal(m.qty), Decimal(m.balance_after)) for m in opening] == \
        [(p1.id, Decimal("12.500"), Decimal("12.500"))]
    assert sorted((str(m.product_id), Decimal(m.qty)) for m in close) == sorted(
        [(str(p1.id), Decimal("-10")), (str(exact.id), Decimal("-4"))])
    assert [(m.product_id, Decimal(m.qty)) for m in missing] == [(gone.id, Decimal("-6"))]
    assert all(Decimal(m.balance_after) == 0 for m in close + missing)
    assert len({m.client_uuid for m in mv}) == len(mv)
    # Review #33: ochilish yopishdan KEYIN (tartib aniq)
    c1 = next(m for m in close if m.product_id == p1.id)
    assert opening[0].created_at > c1.created_at
    legacy = db.query(StockMovement).filter(StockMovement.product_id == p1.id, StockMovement.ref_type == "product_create").count()
    assert legacy == 1                                                                        # eski tarix saqlangan
    assert db.query(Product).filter(Product.company_id == comp.id, Product.track_lots.is_(True)).count() == 0


def test_takroriy_apply_rad_etiladi_va_hech_narsa_yozilmaydi(db):
    comp, br, legacy_bc, exact, gone, products = _scenario(db)
    b, rep = _review(db, comp, products)
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(legacy_bc.id)}},
                    policies={"missing_price": "skip_row"})
    apply_migration(db, b, rep, m)
    db.commit()
    before = _counts(db, comp)
    with pytest.raises(AlreadyApplied):
        apply_migration(db, b, rep, m)
    db.rollback()
    # AYNI mazmun, BOSHQA fayl (eksport vaqti/ID/format/GUID registri/son yozuvi boshqa) — mazmun xeshi bo'yicha rad
    variant = json.loads(json.dumps(products))
    variant[0]["guid"] = variant[0]["guid"].upper()
    variant[0]["stock"][0]["qty"] = "12.5"
    b2 = load(bundle_dict(list(reversed(variant)), export_id="re-export"), indent=2)
    assert b2.file_sha256 != b.file_sha256 and b2.content_sha256 == b.content_sha256
    with pytest.raises(AlreadyApplied):
        apply_migration(db, b2, rep, m)
    db.rollback()
    assert _counts(db, comp) == before


def test_eskirgan_snapshot_yangisidan_keyin_qollanmaydi(db):
    """Review #25: eski eksport yangisidan keyin qo'llanib, qoldiqni orqaga qaytarardi."""
    comp, (br,) = seed_company(db)
    db.commit()
    newer = load(bundle_dict([prod(g(1), "Tovar", stock=("25",))], snapshot_at="2026-09-20T10:00:00+06:00"))
    rep = C.classify(newer, load_snapshot(db, comp.code))
    db.rollback()
    apply_migration(db, newer, rep, mapping_for(rep, br.id, mode="INITIAL_CREATE"))
    db.commit()
    older = load(bundle_dict([prod(g(1), "Tovar", stock=("40",))], snapshot_at="2026-09-20T09:00:00+06:00"))
    rep_old = C.classify(older, load_snapshot(db, comp.code))
    db.rollback()
    assert rep_old["summary"]["stale_snapshot"] and rep_old["binos"]["newer_or_equal_snapshot_jobs"]
    m = mapping_for(rep_old, br.id)
    assert "eskirgan snapshot" in _problems(rep_old, m)
    before = _counts(db, comp)
    with pytest.raises(StaleSnapshotError):
        apply_migration(db, older, rep_old, m)
    db.rollback()
    assert _counts(db, comp) == before


def test_korib_chiqilgandan_keyin_katalog_ozgarsa_DRIFT_va_yozuv_yoq(db):
    comp, br, legacy_bc, exact, gone, products = _scenario(db)
    b, rep = _review(db, comp, products)
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(legacy_bc.id)}},
                    policies={"missing_price": "skip_row"})
    db.get(Product, gone.id).name = "Kimdir nomini o'zgartirdi"
    db.commit()
    before = _counts(db, comp)
    with pytest.raises(DriftError):
        apply_migration(db, b, rep, m)
    db.rollback()
    assert _counts(db, comp) == before


def test_post_tekshiruv_yiqilsa_hammasi_qaytariladi(db, monkeypatch):
    from app.services.migrator_1c import apply as A
    comp, br, legacy_bc, exact, gone, products = _scenario(db)
    b, rep = _review(db, comp, products)
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(legacy_bc.id)}},
                    policies={"missing_price": "skip_row"})
    before = _counts(db, comp)
    monkeypatch.setattr(A, "verify_state", lambda *a, **k: {"ok": False, "failures": ["sun'iy"]})
    with pytest.raises(A.PostVerifyError):
        apply_migration(db, b, rep, m)
    db.rollback()
    assert _counts(db, comp) == before


def test_post_tekshiruv_bazadagi_buzilishni_tutadi(db):
    """Review #24: stock_by_branch rejani o'zi bilan solishtirardi; barkod egasi, o'chirish tekshirilmasdi."""
    comp, br, legacy_bc, exact, gone, products = _scenario(db)
    b, rep = _review(db, comp, products)
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(legacy_bc.id)}},
                    policies={"missing_price": "skip_row", "binos_missing_from_source": "deactivate_and_zero"})
    out = apply_migration(db, b, rep, m)
    db.commit()
    job = db.get(ImportJob, uuid.UUID(out["job_id"]))
    plan = job.column_mapping["plan"]
    assert verify_state(db, comp.id, job.id, plan)["ok"]

    def broken(mut, needle):
        mut()
        db.flush()
        res = verify_state(db, comp.id, job.id, plan)
        db.rollback()
        assert not res["ok"] and needle in " ".join(res["failures"]), res["failures"]

    broken(lambda: setattr(db.query(Inventory).filter(Inventory.product_id == legacy_bc.id).one(), "qty",
                           Decimal("12.499")), "qoldiq mos emas")
    broken(lambda: setattr(db.query(ProductBarcode).filter(ProductBarcode.product_id == legacy_bc.id,
                                                           ProductBarcode.barcode == "4600000000024").one(),
                           "product_id", exact.id), "barkod rejadagi mahsulotda emas")
    broken(lambda: setattr(db.get(Product, gone.id), "is_active", True), "o'chirilgan")
    broken(lambda: setattr(db.query(StockMovement).filter(StockMovement.ref_id == job.id,
                                                          StockMovement.product_id == gone.id).one(),
                           "qty", Decimal("-5")), "harakatlar rejaga mos emas")
    broken(lambda: setattr(db.get(Product, legacy_bc.id), "base_sell_price", Decimal("1.00")), "sotuv narxi")
    assert verify_state(db, comp.id, job.id, plan)["ok"]


def test_mapping_qaror_va_siyosatlarsiz_rad(db):
    comp, br, legacy_bc, exact, gone, products = _scenario(db)
    b, rep = _review(db, comp, products)
    base = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(legacy_bc.id)}},
                       policies={"missing_price": "skip_row"})
    build_plan(rep, base)                                                   # to'g'ri mapping o'tadi

    def problems(mut):
        mm = json.loads(json.dumps(base))
        mut(mm)
        return _problems(rep, mm)

    assert "ANIQ qaror SHART" in problems(lambda mm: mm["decisions"].update({g(1): {"action": ""}}))
    assert "bog'lanishi mumkin nomzodga" in problems(
        lambda mm: mm["decisions"].update({g(1): {"action": "LINK", "product_id": str(gone.id)}}))
    assert "siyosat 'new_products'" in problems(lambda mm: mm["policies"].pop("new_products"))
    assert "report_sha256" in problems(lambda mm: mm.update({"report_sha256": "0" * 64}))
    assert "approved_by" in problems(lambda mm: mm.update({"approved_by": ""}))
    assert "approved_at" in problems(lambda mm: mm.update({"approved_at": 20260920}))
    assert "warehouse_branch" in problems(lambda mm: mm.update({"warehouse_branch": {}}))
    assert "EXACT_MATCH boshqa" in problems(
        lambda mm: mm["decisions"].update({g(2): {"action": "LINK", "product_id": str(legacy_bc.id)}}))
    assert "INITIAL_CREATE faqat bo'sh" in problems(lambda mm: mm.update({"mode": "INITIAL_CREATE"}))
    assert "noma'lum kalit: extra" in problems(lambda mm: mm.update({"extra": 1}))
    assert "noma'lum kalit 'force'" in problems(lambda mm: mm["decisions"][g(1)].update({"force": True}))
    assert "noma'lum siyosat" in problems(lambda mm: mm["policies"].update({"auto_merge": "yes"}))
    tampered = dict(rep, summary=dict(rep["summary"], new=999))
    with pytest.raises(MappingError, match="tahrirlangan"):
        build_plan(tampered, base)


def test_bloklangan_qatorlar_faqat_aniq_skip_siyosati_bilan(db):
    comp, (br,) = seed_company(db)
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "A"), prod(g(1), "B"), prod(g(2), "C")])
    m = mapping_for(rep, br.id, mode="INITIAL_CREATE")
    m["policies"].pop("blocked_rows")
    with pytest.raises(MappingError, match="blocked_rows"):
        build_plan(rep, m)
    m["policies"]["blocked_rows"] = "skip"
    plan = build_plan(rep, m)
    assert [o["guid"] for o in plan["ops"]] == [g(2)] and len(plan["skipped"]) == 2


def test_bitta_mahsulot_ikki_qarorga_boglanmaydi(db):
    comp, (br,) = seed_company(db)
    a = add_product(db, comp, br, "Chipsi")
    add_product(db, comp, br, "chipsi")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "CHIPSI"), prod(g(2), "Chipsi ")])
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(a.id)},
                                           g(2): {"action": "LINK", "product_id": str(a.id)}})
    assert "allaqachon" in _problems(rep, m)


# ── Review regressiyalari: maqsadga bog'liq darvozalar ───────────────────────
def test_nomalum_birlik_LINK_va_EXACT_qatorda_ham_siyosatni_talab_qiladi(db):
    """Review #1: noma'lum birlik faqat CREATE da tekshirilardi — qop narxi kg mahsulotga yozilardi."""
    comp, (br,) = seed_company(db)
    p = add_product(db, comp, br, "Мука 1 сорт", guid=g(1), qty="7", sell="9000.00", unit_code="kg")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Мука 1 сорт", unit="меш", okei=None, retail="450000.00", stock=("12",))])
    r = rep["rows"][0]
    assert r["classification"] == "EXACT_MATCH" and "UNKNOWN_UNIT" in r["decide"]
    m = mapping_for(rep, br.id, policies={"unknown_unit": "block"})
    assert "noma'lum birlik" in _problems(rep, m)
    m["policies"]["unknown_unit"] = "skip_row"
    m["policies"]["skipped_row_products"] = "keep"
    plan = build_plan(rep, m)
    assert plan["ops"] == [] and plan["skipped"][0]["why"] == "UNKNOWN_UNIT"
    apply_migration(db, b, rep, m)
    db.commit()
    db.expire_all()
    assert db.get(Product, p.id).base_sell_price == Decimal("9000.00") and _inv(db, p.id, br.id) == Decimal("7")


def test_AMBIGUOUS_LINK_tanlangan_nomzod_birligi_va_nomi_tekshiriladi(db):
    """Review #2: AMBIGUOUS -> LINK hech qanday maqsad tekshiruvisiz o'tardi."""
    comp, (br,) = seed_company(db)
    p1 = add_product(db, comp, br, "Сахар", sell="60000.00")
    add_product(db, comp, br, "сахар")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Сахар ", unit="кг", okei="166", retail="12000.00", stock=("25.5",))])
    r = rep["rows"][0]
    assert r["classification"] == "AMBIGUOUS"
    assert {c["unit"] for c in r["candidates"]} == {"differs"}
    dec = {g(1): {"action": "LINK", "product_id": str(p1.id)}}
    m = mapping_for(rep, br.id, decisions=dec)
    m["policies"].pop("unit_differs")
    assert "unit_differs" in _problems(rep, m)
    m["policies"]["unit_differs"] = "block"
    assert "birlik farq qiladi" in _problems(rep, m)
    m["policies"]["unit_differs"] = "keep_binos"                  # Review-2: 1C qiymatlari boshqa birlikka yozilmaydi
    assert "ruxsat" in _problems(rep, m)
    m["policies"].update({"unit_differs": "skip_row", "skipped_row_products": "keep",
                          "binos_missing_from_source": "deactivate_and_zero"})
    plan = build_plan(rep, m)
    assert plan["ops"] == [] and plan["skipped"][0]["why"] == "UNIT_DIFFERS"
    # tanlangan maqsad o'tkazib yuborilgan qator mahsuloti (keep), tanlanmagan nomzod — 1C'da bog'lanmagan
    assert [x["product_id"] for x in plan["kept_unlinked"]] == [str(p1.id)]
    assert plan["kept_unlinked"][0]["reason"] == "skipped_row_products"
    assert all(x["product_id"] != str(p1.id) for x in plan["deactivate"])


def test_GTIN_varianti_boshqa_mahsulotda_skip_barcode_rostdan_tashlaydi(db):
    """Review #3/#13/#28: apply aniq satr bo'yicha tekshirib, 12 xonali egizakni ikkinchi mahsulotga yozardi."""
    comp, (br,) = seed_company(db)
    q = add_product(db, comp, br, "Q", barcodes=["0012345678905"])
    p1 = add_product(db, comp, br, "P1", guid=g(1))
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "P1", barcodes=["012345678905", "4600000000017"])])
    m = mapping_for(rep, br.id, policies={"barcode_owned_by_other": "skip_barcode"})
    plan = build_plan(rep, m)
    op = plan["ops"][0]
    assert op["barcodes_add"] == ["4600000000017"]
    assert op["barcodes_skipped"] == [{"value": "012345678905", "reason": "OWNED_BY_OTHER_PRODUCT", "owners": [str(q.id)]}]
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"]
    assert _bcs(db, p1.id) == {"4600000000017"} and _bcs(db, q.id) == {"0012345678905"}
    m["policies"]["barcode_owned_by_other"] = "block"
    assert "barkod 012345678905 boshqa mahsulotda" in _problems(rep, m)


def test_CREATE_nomzod_barkodi_boshqa_mahsulotda_siyosat_talab_qiladi_va_apply_yiqilmaydi(db):
    """Review #4/#14/#27: reja o'tardi, apply esa DriftError bilan yiqilardi."""
    comp, (br,) = seed_company(db)
    x = add_product(db, comp, br, "Сок вишнёвый", barcodes=["4780000000013"])
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Сок яблочный", barcodes=["4780000000013"])])
    assert rep["rows"][0]["classification"] == "CANDIDATE"
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "CREATE"}})
    m["policies"].pop("barcode_owned_by_other")
    assert "barcode_owned_by_other" in _problems(rep, m)
    m["policies"]["barcode_owned_by_other"] = "skip_barcode"
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"]
    new = db.query(Product).filter(Product.company_id == comp.id, Product.external_id == g(1)).one()
    assert _bcs(db, new.id) == set() and _bcs(db, x.id) == {"4780000000013"}


def test_rad_etilgan_nomzodlar_deactivate_siyosatiga_tushadi(db):
    """Review #8/#40: tanlanmagan AMBIGUOUS nomzodi va CREATE qilingan qatorning nomzodi eski qoldiq bilan qolardi."""
    comp, (br,) = seed_company(db)
    k1 = add_product(db, comp, br, "Кефир", qty="3")
    k2 = add_product(db, comp, br, "кефир", qty="5")
    syr = add_product(db, comp, br, "Сыр", qty="2")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Кефир", stock=("9",)), prod(g(2), "Сыр", stock=("1",))])
    dec = {g(1): {"action": "LINK", "product_id": str(k1.id)}, g(2): {"action": "CREATE"}}
    m = mapping_for(rep, br.id, decisions=dec, policies={"binos_missing_from_source": "deactivate_and_zero"})
    plan = build_plan(rep, m)
    assert {x["product_id"] for x in plan["deactivate"]} == {str(k2.id), str(syr.id)}
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"] and out["post_verify"]["deactivated"] == 2
    db.expire_all()
    for p in (k2, syr):
        assert db.get(Product, p.id).is_active is False and _inv(db, p.id, br.id) == Decimal("0")
    assert _inv(db, k1.id, br.id) == Decimal("9")


def test_otkazib_yuborilgan_qator_mahsuloti_alohida_siyosat(db):
    comp, (br,) = seed_company(db)
    p = add_product(db, comp, br, "Buzuq qoldiqli", guid=g(1), qty="4")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Buzuq qoldiqli", stock=("12,5",))])
    assert rep["rows"][0]["classification"] == "BLOCKED"
    m = mapping_for(rep, br.id)
    m["policies"].pop("skipped_row_products", None)
    assert "skipped_row_products" in _problems(rep, m)
    m["policies"]["skipped_row_products"] = "keep"
    plan = build_plan(rep, m)
    assert plan["deactivate"] == [] and plan["kept_unlinked"][0]["product_id"] == str(p.id)


def test_boshqa_tizim_identitetli_ochirilgan_mahsulot_tiklanmaydi(db):
    """Review #9: REACTIVATE reja o'tib, apply DriftError bilan yiqilardi."""
    comp, (br,) = seed_company(db)
    d = add_product(db, comp, br, "Eski import", deleted=True)
    d.source_system, d.external_id = "excel", "X-17"
    db.commit()
    b, rep = _review(db, comp, [prod(g(5), "Eski import")])
    r = rep["rows"][0]
    assert r["classification"] == "AMBIGUOUS" and "IDENTITY_CONFLICT" in r["decide"]
    m = mapping_for(rep, br.id, decisions={g(5): {"action": "REACTIVATE", "product_id": str(d.id)}})
    assert "REACTIVATE faqat DELETED_MATCH" in _problems(rep, m)
    m["decisions"][g(5)] = {"action": "LINK", "product_id": str(d.id)}
    assert "bog'lanishi mumkin nomzodga" in _problems(rep, m)


def test_xaritalanmagan_filial_qoldigi_aniq_siyosat(db):
    """Review #26: bog'langan mahsulotning boshqa filialdagi eski qoldig'i jimgina qolardi."""
    comp, (f1, f2) = seed_company(db, branches=2)
    px = add_product(db, comp, f1, "PX", guid=g(1), qty="4")
    _add_inv(db, px, f2, "10")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "PX", stock=("7",))])
    m = mapping_for(rep, f1.id)
    m["policies"].pop("unmapped_branch_stock", None)
    assert "unmapped_branch_stock" in _problems(rep, m)
    m["policies"]["unmapped_branch_stock"] = "keep"
    assert build_plan(rep, m)["ops"][0]["stock_final"] == {str(f1.id): "7"}
    m["policies"]["unmapped_branch_stock"] = "close"
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"]
    assert (_inv(db, px.id, f1.id), _inv(db, px.id, f2.id)) == (Decimal("7"), Decimal("0"))
    job = db.get(ImportJob, uuid.UUID(out["job_id"]))
    f2mv = db.query(StockMovement).filter(StockMovement.ref_id == job.id, StockMovement.branch_id == f2.id).one()
    assert Decimal(f2mv.qty) == Decimal("-10") and Decimal(f2mv.balance_after) == 0


def test_yangi_mahsulot_artikuli_boshqa_qatorning_kodi_yoki_artikuli_bolmaydi(db):
    """Review #29: B ning kodi '123' A ning artikuli '123' ni GUID tartibiga qarab egallardi."""
    comp, (br,) = seed_company(db)
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "B", code="123"), prod(g(2), "A", code="A1", article="123")])
    assert "ARTICLE_COLLISION_IN_BUNDLE" in next(r for r in rep["rows"] if r["guid"] == g(2))["decide"]
    m = mapping_for(rep, br.id, mode="INITIAL_CREATE")
    plan = build_plan(rep, m)
    arts = {o["guid"]: o["create"]["article_code"] for o in plan["ops"]}
    assert arts == {g(1): f"1C-{g(1)}", g(2): "A1"}
    m["policies"].pop("article_collision")
    assert "article_collision" in _problems(rep, m)


def test_tiklanayotgan_mahsulot_PLUsi_band_drop_plu(db):
    """Review #30: ux_products_company_plu IntegrityError bilan apply yiqilardi."""
    comp, (br,) = seed_company(db)
    px = add_product(db, comp, br, "Kolbasa eski", guid=g(1), plu="575", deleted=True, unit_code="kg")
    add_product(db, comp, br, "Faol kolbasa", plu="575", unit_code="kg")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Kolbasa eski", unit="кг", okei="166", stock=("2.5",))])
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "REACTIVATE"}}, policies={"plu_collision": "block"})
    assert "PLU'si 575 band" in _problems(rep, m)
    m["policies"]["plu_collision"] = "drop_plu"
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"]
    db.expire_all()
    p = db.get(Product, px.id)
    assert p.deleted_at is None and p.plu_code is None and _inv(db, px.id, br.id) == Decimal("2.500")


def test_PLU_boyicha_nomzod_CREATE_bolsa_PLU_tashlanadi_asl_mahsulot_royxatda(db):
    """Review #7: tarozi mahsuloti PLU'siz dublikat bo'lib yaratilib, asli jimgina qolardi."""
    comp, (br,) = seed_company(db)
    orig = add_product(db, comp, br, "Колбаса докторская", plu="575", unit_code="kg", qty="3")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Колбаса докторская 575Код", unit="кг", okei="166", plu="575")])
    r = rep["rows"][0]
    assert r["classification"] == "CANDIDATE" and r["candidates"][0]["evidence"] == ["plu"]
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "CREATE"}}, policies={"plu_collision": "block"})
    assert "PLU 575 band" in _problems(rep, m)
    m["policies"]["plu_collision"] = "drop_plu"
    plan = build_plan(rep, m)
    assert plan["ops"][0]["create"]["plu"] is None
    assert plan["kept_unlinked"][0]["product_id"] == str(orig.id)


def test_LINK_arxivdagi_mahsulotni_faollashtiradi_va_bu_rejada_korinadi(db):
    comp, (br,) = seed_company(db)
    p = add_product(db, comp, br, "Arxivda")
    p.is_active = False
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Arxivda", stock=("5",))])
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(p.id)}})
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["expected"]["activate"] == 1 and out["post_verify"]["ok"]
    db.expire_all()
    assert db.get(Product, p.id).is_active is True


def test_otkazib_yuborilgan_qator_maqsadi_operator_tanlovidan_olinadi(db):
    """Review-2 blocker: LINK qilingan (yoki BLOCKED qatorning yagona nomzodi bo'lgan) mahsulot
    `skipped_row_products=keep` ga qaramay "1C'da yo'q" deb o'chirilib, qoldig'i nollanardi."""
    comp, (br,) = seed_company(db)
    x = add_product(db, comp, br, "Сахар", qty="10")
    z = add_product(db, comp, br, "сахар ", qty="1")
    milk = add_product(db, comp, br, "Молоко 3,2%", qty="5")
    d1 = add_product(db, comp, br, "Dublikat A", guid=g(9), qty="2")
    d2 = add_product(db, comp, br, "Dublikat B", guid=g(9).upper(), qty="3")
    rej = add_product(db, comp, br, "Rad etilgan nomzod", qty="4")
    db.commit()
    b, rep = _review(db, comp, [
        prod(g(1), "Сахар", retail=None),                               # AMBIGUOUS -> LINK x, keyin narx siyosati o'tkazadi
        prod(g(2), "Молоко 3,2%", stock=("1.2345",)),                   # BLOCKED (aniqlik), yagona nomzod milk
        prod(g(9), "Dublikat"),                                         # BLOCKED IDENTITY_DUPLICATE_IN_BINOS
        prod(g(4), "Rad etilgan nomzod", retail="0"),                   # CANDIDATE -> CREATE, narx 0 -> o'tkaziladi
    ])
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(x.id)},
                                           g(4): {"action": "CREATE"}},
                    policies={"missing_price": "skip_row", "skipped_row_products": "keep",
                              "binos_missing_from_source": "deactivate_and_zero"})
    plan = build_plan(rep, m)
    kept = {k["product_id"]: k["reason"] for k in plan["kept_unlinked"]}
    deact = {k["product_id"]: k["reason"] for k in plan["deactivate"]}
    assert kept == {str(x.id): "skipped_row_products", str(milk.id): "skipped_row_products",
                    str(d1.id): "skipped_row_products", str(d2.id): "skipped_row_products"}
    assert deact == {str(z.id): "binos_missing_from_source", str(rej.id): "binos_missing_from_source"}
    m["policies"]["missing_price"] = "keep_binos_price"
    plan2 = build_plan(rep, m)
    assert str(rej.id) in {k["product_id"] for k in plan2["deactivate"]}   # CREATE qarori — nomzod rad etilgan


def test_MANY_TO_ONE_va_boshqa_manba_GUID_egasi_otkazib_yuborilgan_qator_mahsuloti(db):
    """Review-3 blockerlari: (a) MANY_TO_ONE nishonni tozalagani uchun ikkala qator o'tkazilganda yagona nomzod
    "1C'da yo'q" deb o'chirilardi; (b) GUID'ni 'excel' manbasi bilan saqlagan mahsulot row_targets'ga tushmasdi."""
    comp, (br,) = seed_company(db)
    x = add_product(db, comp, br, "Сахар", qty="10")
    y = add_product(db, comp, br, "Кефир 1л", qty="8")
    y.source_system, y.external_id = "excel", g(7)
    db.commit()
    b, rep = _review(db, comp, [
        prod(g(1), "Сахар", stock=("1.2345",)),                      # BLOCKED (aniqlik) + MANY_TO_ONE
        prod(g(2), "Сахар", stock=("3",)),                           # AMBIGUOUS MANY_TO_ONE -> SKIP
        prod(g(7), "Кефир 2,5% 0,5л", stock=("3",)),                 # BLOCKED GUID_OWNED_BY_OTHER_SOURCE
    ])
    r7 = next(r for r in rep["rows"] if r["guid"] == g(7))
    assert r7["row_targets"] == [str(y.id)] and r7["candidates"][0]["evidence"] == ["guid_other_source"]
    assert next(p for p in rep["binos_live_products"] if p["product_id"] == str(y.id))["status"] == "unresolved_candidate"
    for gg in (g(1), g(2)):
        assert next(r for r in rep["rows"] if r["guid"] == gg)["row_targets"] == [str(x.id)]
    m = mapping_for(rep, br.id, decisions={g(2): {"action": "SKIP"}},
                    policies={"skipped_row_products": "keep", "binos_missing_from_source": "deactivate_and_zero"})
    assert "skipped_row_products" in build_template(rep)["policies"]
    plan = build_plan(rep, m)
    assert {k["product_id"]: k["reason"] for k in plan["kept_unlinked"]} == {
        str(x.id): "skipped_row_products", str(y.id): "skipped_row_products"}
    assert plan["deactivate"] == []


def test_boshqa_identitetli_yagona_nomzod_otkazib_yuborilgan_qator_mahsuloti(db):
    """Review-4 blocker: BLOCKED/SKIP qatorning YAGONA nomzodida boshqa identitet bo'lsa (IDENTITY_CONFLICT),
    u row_targets'ga tushmasdi va skipped_row_products=keep bo'lsa ham o'chirilib, qoldig'i nollanardi."""
    comp, (br,) = seed_company(db)
    x = add_product(db, comp, br, "Кефир 1л", article="KEF-1", qty="8")
    x.source_system, x.external_id = "excel", "EXL-17"
    y = add_product(db, comp, br, "Ряженка", article="RJ-1", qty="5")
    y.source_system, y.external_id = "1c", "00017"                     # V2 importi: GUID emas
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Кефир 1л", article="KEF-1", stock=("3.5005",)),     # BLOCKED
                                prod(g(2), "Ряженка", article="RJ-1", stock=("3",))])           # AMBIGUOUS -> SKIP
    for gg, pp in ((g(1), x), (g(2), y)):
        r = next(r for r in rep["rows"] if r["guid"] == gg)
        assert "IDENTITY_CONFLICT" in r["decide"] and r["row_targets"] == [str(pp.id)]
    m = mapping_for(rep, br.id, decisions={g(2): {"action": "SKIP"}},
                    policies={"skipped_row_products": "keep", "binos_missing_from_source": "deactivate_and_zero"})
    plan = build_plan(rep, m)
    assert plan["deactivate"] == []
    assert {k["product_id"]: k["reason"] for k in plan["kept_unlinked"]} == {
        str(x.id): "skipped_row_products", str(y.id): "skipped_row_products"}
    m["decisions"][g(2)] = {"action": "CREATE"}                          # CREATE — nomzod rad etilgan
    plan2 = build_plan(rep, m)
    assert {k["product_id"]: k["reason"] for k in plan2["deactivate"]} == {str(y.id): "binos_missing_from_source"}


def test_bosh_satr_PLU_ham_tiklashda_toqnashuv(db):
    """Review-4 minor: plu_code '' (indeksda NULL emas) gate'dan o'tib ketardi."""
    comp, (br,) = seed_company(db)
    d = add_product(db, comp, br, "Eski", guid=g(1), deleted=True, unit_code="kg")
    d.plu_code = ""
    live = add_product(db, comp, br, "Faol", unit_code="kg")
    live.plu_code = ""
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Eski", unit="кг", okei="166")])
    assert "REACTIVATE_PLU_CONFLICT" in rep["rows"][0]["decide"]
    assert "plu_collision" in build_template(rep)["policies"]
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "REACTIVATE"}}, policies={"plu_collision": "block"})
    assert "band" in _problems(rep, m)
    m["policies"]["plu_collision"] = "drop_plu"
    assert build_plan(rep, m)["ops"][0]["clear_plu"] is True


def test_EXACT_SKIP_uchun_shablon_skipped_row_products_ni_soraydi(db):
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Чай", guid=g(1), qty="2")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Чай"), prod(g(2), "Кофе", retail=None)])
    tpl = build_template(rep)
    assert "skipped_row_products" in tpl["policies"]
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "SKIP"}})
    plan = build_plan(rep, m)
    assert plan["kept_unlinked"][0]["reason"] == "skipped_row_products"


def test_raqamsiz_PLU_li_ochirilgan_mahsulotni_tiklash_toqnashuvi_aniqlanadi(db):
    """Review-3 major: norm_plu raqamsiz PLU'ni ko'rmasdi — reja o'tib, apply ux_products_company_plu'ga urilardi."""
    comp, (br,) = seed_company(db)
    d = add_product(db, comp, br, "Колбаса весовая", article="ART-D", guid=g(1), deleted=True, unit_code="kg")
    d.plu_code = "12A"
    live = add_product(db, comp, br, "Boshqa", unit_code="kg")
    live.plu_code = "12A"
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Колбаса весовая", unit="кг", okei="166", stock=("1.5",))])
    r = rep["rows"][0]
    assert r["classification"] == "DELETED_MATCH" and "REACTIVATE_PLU_CONFLICT" in r["decide"]
    assert r["candidates"][0]["plu_conflicts"] == [str(live.id)]
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "REACTIVATE"}}, policies={"plu_collision": "block"})
    assert "plu_collision" in build_template(rep)["policies"]
    assert "PLU'si 12A band" in _problems(rep, m)
    m["policies"]["plu_collision"] = "drop_plu"
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"]
    db.expire_all()
    assert db.get(Product, d.id).plu_code is None and db.get(Product, live.id).plu_code == "12A"


def test_maqsadda_bor_barkod_otkazib_yuborilmaydi_va_post_verify_yiqilmaydi(db):
    """Review-2: maqsadda AYNAN shu satr bor, egizagi boshqa mahsulotda — barcodes_skipped'ga tushib,
    post-tekshiruv 'o'tkazib yuborilgan barkod yozilgan' deb yiqilardi."""
    comp, (br,) = seed_company(db)
    t = add_product(db, comp, br, "T", guid=g(1), barcodes=["012345678905"])
    add_product(db, comp, br, "Y", barcodes=["0012345678905"])
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "T", barcodes=["012345678905"])])
    m = mapping_for(rep, br.id, policies={"barcode_owned_by_other": "block"})
    plan = build_plan(rep, m)
    assert plan["ops"][0]["barcodes_existing"] == ["012345678905"] and not plan["ops"][0]["barcodes_skipped"]
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"], out["post_verify"]
    assert _bcs(db, t.id) == {"012345678905"}


def test_nol_kelish_narxi_BinOS_tannarxini_ustiga_yozmaydi(db):
    """Review-2: 1C'dagi to'ldirilmagan '0' kelish narxi COGS'ni nolga tushirardi va hisobotda ko'rinmasdi."""
    comp, (br,) = seed_company(db)
    p = add_product(db, comp, br, "Чай", guid=g(1), sell="20000.00")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Чай", retail="21000.00", purchase="0")])
    r = rep["rows"][0]
    assert "ZERO_PURCHASE_PRICE" in r["info"] and r["purchase_price"] is None and r["purchase_status"] == "zero"
    assert rep["summary"]["purchase_price_zero"] == 1
    assert rep["reconciliation"]["source_1c_raw"]["purchase_price_zero"] == 1 and rep["reconciliation"]["ok"]
    out = apply_migration(db, b, rep, mapping_for(rep, br.id))
    db.commit()
    assert out["expected"]["buy_prices_set"] == 0
    db.expire_all()
    assert db.get(Product, p.id).base_buy_price == Decimal("30.00")
    b2, rep2 = _review(db, comp, [prod(g(1), "Чай", retail="21000.00", purchase="15500.00")],
                       snapshot_at="2026-09-21T09:00:00+06:00")
    assert "PURCHASE_PRICE_CHANGES" in rep2["rows"][0]["info"]


def test_keep_binos_price_narxsiz_arxiv_mahsulotni_faollashtirmaydi(db):
    comp, (br,) = seed_company(db)
    x = add_product(db, comp, br, "Пакет", sell="0.00")
    x.is_active = False
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Пакет", retail=None, stock=("40",))])
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(x.id)}},
                    policies={"missing_price": "keep_binos_price", "skipped_row_products": "keep"})
    plan = build_plan(rep, m)
    assert plan["ops"] == [] and plan["skipped"][0]["why"] == "MISSING_PRICE_NO_BINOS_PRICE"


def test_ochiriladigan_mahsulotning_xaritalanmagan_filial_qoldigi_siyosatga_boysunadi(db):
    """Review-2 / #26: deactivate_and_zero tanlanmagan filialdagi qoldiqni ham nollardi (keep bo'lsa ham)."""
    comp, (f1, f2) = seed_company(db, branches=2)
    y = add_product(db, comp, f1, "Y faqat BinOS", qty="2")
    _add_inv(db, y, f2, "7")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Boshqa tovar")])
    m = mapping_for(rep, f1.id, policies={"binos_missing_from_source": "deactivate_and_zero",
                                          "unmapped_branch_stock": "keep"})
    plan = build_plan(rep, m)
    assert plan["deactivate"][0]["close"] == {str(f1.id): "2.000"}
    out = apply_migration(db, b, rep, m)
    db.commit()
    assert out["post_verify"]["ok"], out["post_verify"]
    assert (_inv(db, y.id, f1.id), _inv(db, y.id, f2.id)) == (Decimal("0"), Decimal("7"))
    db.expire_all()
    assert db.get(Product, y.id).is_active is False


def test_boshqa_manbadagi_ayni_GUID_quruq_yurishda_bloklanadi(db):
    """Review-2: apply/verify GUID'ni manbadan qat'i nazar tekshiradi — dry-run buni oldindan aytmasdi."""
    comp, (br,) = seed_company(db)
    x = add_product(db, comp, br, "Excel import")
    x.source_system, x.external_id = "excel", g(1)
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Butunlay boshqa nom")])
    r = rep["rows"][0]
    assert r["classification"] == "BLOCKED" and "GUID_OWNED_BY_OTHER_SOURCE" in r["block"]


def test_birlik_xaritasi_nuqta_va_probel_bilan_tugasa_ham_apply_drift_bermaydi(db):
    """Review-2: norm_unit_key idempotent emas edi — 'шт .' dry-run'da topilib, apply'da DriftError."""
    comp, (br,) = seed_company(db)
    db.commit()
    b = load(bundle_dict([prod(g(1), "Tovar", unit="бут .", okei=None)]))
    rep = C.classify(b, load_snapshot(db, comp.code), {"Бут .": "dona"})
    db.rollback()
    assert "UNKNOWN_UNIT" not in rep["rows"][0]["decide"] and rep["unit_names_extra"] == {"бут": "dona"}
    out = apply_migration(db, b, rep, mapping_for(rep, br.id, mode="INITIAL_CREATE"))
    db.rollback()
    assert out["post_verify"]["ok"]


def test_product_id_matn_bolmasa_TypeError_emas_MappingError(db):
    comp, (br,) = seed_company(db)
    x = add_product(db, comp, br, "Nomzod")
    db.commit()
    b, rep = _review(db, comp, [prod(g(1), "Nomzod")])
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": [str(x.id)]}})
    assert "product_id matn" in _problems(rep, m)


def test_postgres_allowlistda_yoq_sysid_rad(db, monkeypatch):
    """Review-2 / #38: qayta yaratilgan production (yangi sysid) denylist'dan o'tib ketardi."""
    from app.services.migrator_1c import guard
    new_prod = {"dialect": "postgresql", "system_identifier": "7777777777777777777", "database": "railway"}
    monkeypatch.setattr(guard, "database_identity", lambda _db: dict(new_prod))
    monkeypatch.delenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS", raising=False)
    with pytest.raises(ApplyForbidden, match="ruxsat ro'yxatida yo'q"):
        assert_apply_allowed(db, "7777777777777777777", new_prod)
    monkeypatch.setenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS", "1, 7777777777777777777")
    assert {"1", "7777777777777777777", "7683497876193431618"} <= guard.allowed_system_identifiers()
    with pytest.raises(ApplyForbidden, match="MAJBURIY"):                   # allowlist'dan o'tdi, keyingi shart
        assert_apply_allowed(db, None, new_prod)
    monkeypatch.setenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS", "7674898282858840119")      # production — hech qachon
    assert "7674898282858840119" not in guard.allowed_system_identifiers()
    prod_ident = dict(new_prod, system_identifier="7674898282858840119")
    monkeypatch.setattr(guard, "database_identity", lambda _db: dict(prod_ident))
    with pytest.raises(ApplyForbidden, match="production bazasi"):
        assert_apply_allowed(db, "7674898282858840119", prod_ident)


# ── CLI ─────────────────────────────────────────────────────────────────────
def test_CLI_rehearse_doim_rollback_commit_va_verify_applied(db, tmp_path, monkeypatch, capsys):
    """Review #23/#36: verify-applied har doim DetachedInstanceError bilan yiqilardi."""
    import os

    from app.tools import migrate_1c
    from tests.migrator_1c_synth import write
    comp, (br,) = seed_company(db)
    db.commit()
    path = str(tmp_path / "e.json")
    write(bundle_dict([prod(g(1), "Rehearse tovar", stock=("3",))]), path)
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", "sqlite:///./_pytest.db"))
    rpath, mpath = str(tmp_path / "r.json"), str(tmp_path / "m.json")
    assert migrate_1c.main(["dry-run", "--bundle", path, "--company-code", comp.code, "--out", rpath]) == 0
    rep = json.loads(open(rpath, encoding="utf-8").read())
    m = mapping_for(rep, br.id, mode="INITIAL_CREATE")
    open(mpath, "w", encoding="utf-8-sig").write(json.dumps(m))               # BOM'li mapping ham o'qiladi
    before = _counts(db, comp)
    assert migrate_1c.main(["apply", "--bundle", path, "--report", rpath, "--mapping", mpath, "--rehearse"]) == 0
    db.rollback()
    assert _counts(db, comp) == before
    assert migrate_1c.main(["plan", "--report", rpath, "--mapping", mpath]) == 0
    capsys.readouterr()
    assert migrate_1c.main(["apply", "--bundle", path, "--report", rpath, "--mapping", mpath, "--commit"]) == 0
    job_id = json.loads(capsys.readouterr().out)["job_id"]
    assert migrate_1c.main(["verify-applied", "--company-code", comp.code, "--job-id", job_id]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["ok"] is True and res["job_status"] == "committed" and res["read_only"]["before"]["enforced"]
    dup = dict(m, decisions={g(1): {"action": "SKIP"}})
    t = json.dumps(dup)
    open(mpath, "w", encoding="utf-8").write(t[:-1] + ', "decisions": {}}')                # takror kalit
    from app.services.migrator_1c.bundle import BundleError
    with pytest.raises(BundleError, match="takror kalit"):
        migrate_1c.main(["plan", "--report", rpath, "--mapping", mpath])


# ── DARVOZALAR ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("app_env,platform,allowed", [
    ("dev", None, True), ("test", None, True), ("staging", "staging", True),
    ("production", None, False), (None, None, False), ("", None, False), ("  PROD  ", None, False),
    ("dev", "production", False), ("staging", "production", False),
])
def test_apply_muhit_darvozasi_fail_closed(monkeypatch, app_env, platform, allowed):
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    if platform is None:
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    else:
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", platform)
    assert environment_allows_apply()[0] is allowed


def test_postgres_darvozasi_ijobiy_identifikatsiya_talab_qiladi(db, monkeypatch):
    """Review #38: --expect-system-identifier ixtiyoriy edi, hisobot bazasi solishtirilmasdi."""
    from app.services.migrator_1c import guard
    prod_ident = {"dialect": "postgresql", "system_identifier": "7674898282858840119", "database": "railway"}
    stg = {"dialect": "postgresql", "system_identifier": "7683497876193431618", "database": "railway"}
    monkeypatch.delenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS", raising=False)
    monkeypatch.setattr(guard, "database_identity", lambda _db: dict(prod_ident))
    with pytest.raises(ApplyForbidden, match="production bazasi"):
        assert_apply_allowed(db, "7674898282858840119", prod_ident)
    monkeypatch.setattr(guard, "database_identity", lambda _db: dict(stg))
    with pytest.raises(ApplyForbidden, match="MAJBURIY"):
        assert_apply_allowed(db, None, stg)
    with pytest.raises(ApplyForbidden, match="kutilgan baza"):
        assert_apply_allowed(db, "1111", stg)
    with pytest.raises(ApplyForbidden, match="BOSHQA bazada"):
        assert_apply_allowed(db, stg["system_identifier"], None)
    with pytest.raises(ApplyForbidden, match="BOSHQA bazada"):
        assert_apply_allowed(db, stg["system_identifier"], dict(stg, database="other"))
    monkeypatch.setattr(guard, "database_identity",
                        lambda _db: {"dialect": "sqlite", "system_identifier": None, "database": None})
    with pytest.raises(ApplyForbidden, match="system_identifier yo'q"):
        assert_apply_allowed(db, expect_system_identifier="7683497876193431618")


def test_apply_production_muhitida_yozuvsiz_rad(db, monkeypatch):
    comp, br, legacy_bc, exact, gone, products = _scenario(db)
    b, rep = _review(db, comp, products)
    m = mapping_for(rep, br.id, decisions={g(1): {"action": "LINK", "product_id": str(legacy_bc.id)}},
                    policies={"missing_price": "skip_row"})
    before = _counts(db, comp)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ApplyForbidden):
        apply_migration(db, b, rep, m)
    db.rollback()
    assert _counts(db, comp) == before


def test_V2_yozuv_yollari_va_preview_production_muhitida_403(client, admin_headers, monkeypatch):
    """Review #39: production'dagi preview bekor qilib bo'lmaydigan job yozib, cutover-complete'ni bloklardi."""
    body = {"mode": "CUTOVER_REFRESH", "source_system": "1c", "snapshot_id": "s-" + uuid.uuid4().hex,
            "rows": [{"name": "x", "sell_price": 1, "external_id": g(9)}]}
    monkeypatch.setenv("APP_ENV", "production")
    for path in ("/api/v1/catalog/v2/commit", "/api/v1/catalog/v2/initial-create", "/api/v1/catalog/v2/preview"):
        r = client.post(path, json={**body, "mode": "INITIAL_CREATE"} if "initial" in path else body,
                        headers=admin_headers)
        assert r.status_code == 403, (path, r.text)
    r = client.post(f"/api/v1/catalog/v2/cutover-complete?import_job_id={uuid.uuid4()}", headers=admin_headers)
    assert r.status_code == 403
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    assert client.post("/api/v1/catalog/v2/commit", json=body, headers=admin_headers).status_code == 403
    assert client.post("/api/v1/catalog/v2/preview", json=body, headers=admin_headers).status_code == 403
