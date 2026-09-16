# -*- coding: utf-8 -*-
"""Migrator V1 — QURUQ YURISH tasnifi (SQLite, haqiqiy ORM bilan).

Asosiy kafolatlar:
  · faqat GUID bir xil bo'lsa EXACT_MATCH; artikul/barkod/nom/PLU -> CANDIDATE (hech qachon bog'lanmaydi)
  · boshqa identitetli mahsulot -> AMBIGUOUS + IDENTITY_CONFLICT (LINK imkonsiz, EXACT qatorni bloklamaydi)
  · bir nechta 1C qatori bitta mahsulotga (GUID'siz dalil) -> hammasi AMBIGUOUS + MANY_TO_ONE
  · takror GUID / fayl ichidagi takror barkod -> HAR nusxa BLOCKED (tartibga bog'liq emas)
  · saqlangan identitet kanonik emas (registr, '1C') -> EXACT topiladi, lekin BLOCKED (NEW EMAS)
  · rekonsiliatsiya — hisob ayniyati: 1C xom = preview + BLOCKED + EXCLUDED
  · quruq yurish bazaga HECH NARSA yozmaydi (katalog barmoq izi va import_jobs o'zgarmaydi)
"""
import json
import os
import random
from decimal import Decimal

import pytest

from app.services.migrator_1c import classify as C
from app.services.migrator_1c.catalog import load_snapshot
from tests.migrator_1c_helpers import add_product, bundle_dict, g, load, prod, seed_company
from tests.migrator_1c_synth import WH_MAIN, WH_SECOND, finalize, write


@pytest.fixture
def db(client):
    from app.db.session import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _rep(db, comp, products, unit_names=None, mutate=None, **kw):
    d = bundle_dict(products, **kw)
    if mutate:
        mutate(d)
        finalize(d)
    b = load(d)
    snap = load_snapshot(db, comp.code)
    return C.classify(b, snap, unit_names), snap


def _row(rep, guid):
    return next(r for r in rep["rows"] if r["guid"] == guid)


def _live(rep, pid):
    return next(x for x in rep["binos_live_products"] if x["product_id"] == str(pid))


def test_faqat_GUID_exact_qolganlari_candidate_hech_qachon_bogllanmaydi(db):
    comp, (br,) = seed_company(db)
    p_guid = add_product(db, comp, br, "Guid mahsulot", guid=g(1), qty="3")
    p_bc = add_product(db, comp, br, "Barkodli", barcodes=["4600000000017"], qty="10")
    p_name = add_product(db, comp, br, "Faqat nom bilan")
    p_art = add_product(db, comp, br, "Artikulli", article="000777")
    db.commit()
    rep, _ = _rep(db, comp, [
        prod(g(1), "Guid mahsulot (1C nomi boshqacha)"),
        prod(g(2), "1C barkod", barcodes=["4600000000017"]),
        prod(g(3), "  faqat   NOM bilan "),
        prod(g(4), "1C artikul", article="000777"),
        prod(g(5), "Butunlay yangi"),
    ])
    assert _row(rep, g(1))["classification"] == "EXACT_MATCH" and _row(rep, g(1))["target_product_id"] == str(p_guid.id)
    for guid, pid, ev in ((g(2), p_bc.id, "barcode"), (g(3), p_name.id, "name"), (g(4), p_art.id, "article")):
        r = _row(rep, guid)
        assert r["classification"] == "CANDIDATE", r
        assert r["exact_product_id"] is None and r["target_product_id"] == str(pid)
        assert r["candidates"][0]["evidence"] == [ev] and r["candidates"][0]["linkable"] is True
    assert _row(rep, g(5))["classification"] == "NEW"
    assert "NAME_DIFFERS" in _row(rep, g(1))["info"]
    s = rep["summary"]
    assert (s["exact_match"], s["candidate"], s["new"]) == (1, 3, 1)


def test_boshqa_GUIDli_mahsulotga_nom_mos_kelsa_AMBIGUOUS_IDENTITY_CONFLICT_link_mumkin_emas(db):
    """V2 preview bu holatni `match_level=name` bilan MOS deb hisoblardi (test_catalog_v2:110)."""
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Sut 1l", guid=g(10))
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(11), "Sut 1l")])
    r = _row(rep, g(11))
    assert r["classification"] == "AMBIGUOUS" and "IDENTITY_CONFLICT" in r["decide"] and not r["block"]
    assert r["candidates"][0]["claimed"] is True and r["candidates"][0]["linkable"] is False


def test_EXACT_qator_boshqa_qatorning_band_nomzodi_tufayli_bloklanmaydi(db):
    """Review #5: GUID'li P1 ga nom bilan mos YANGI 1C qatori MANY_TO_ONE orqali EXACT qatorni ham bloklardi."""
    comp, (br,) = seed_company(db)
    p1 = add_product(db, comp, br, "Нон Тандыр", guid=g(1))
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(1), "Нон Тандыр"), prod(g(2), "Нон тандыр")])
    assert _row(rep, g(1))["classification"] == "EXACT_MATCH" and _row(rep, g(1))["target_product_id"] == str(p1.id)
    r2 = _row(rep, g(2))
    assert r2["classification"] == "AMBIGUOUS" and "IDENTITY_CONFLICT" in r2["decide"]
    assert rep["summary"]["many_to_one_rows"] == 0 and rep["summary"]["blocked"] == 0


def test_bir_nechta_1C_qatori_bitta_mahsulotga_hammasi_AMBIGUOUS_MANY_TO_ONE(db):
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Non", barcodes=["4600000000024"])
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(20), "Non"), prod(g(21), "Non oq", barcodes=["4600000000024"])])
    for guid in (g(20), g(21)):
        r = _row(rep, guid)
        assert r["classification"] == "AMBIGUOUS" and "MANY_TO_ONE" in r["decide"], r
        assert r["target_product_id"] is None
    assert rep["summary"]["many_to_one_rows"] == 2


def test_takror_GUID_va_takror_barkod_har_nusxa_bloklanadi_tartibdan_qati_nazar(db):
    comp, _ = seed_company(db)
    db.commit()
    ps = [prod(g(30), "A"), prod(g(30), "B"), prod(g(31), "C", barcodes=["4600000000031"]),
          prod(g(32), "D", barcodes=["4600000000031"]), prod(g(33), "E", barcodes=["012345678905"]),
          prod(g(34), "F", barcodes=["0012345678905"])]
    for order in (ps, list(reversed(ps))):
        rep, _ = _rep(db, comp, order)
        blocked = {(r["name"], tuple(r["block"])) for r in rep["rows"] if r["classification"] == "BLOCKED"}
        assert blocked == {("A", ("DUPLICATE_GUID",)), ("B", ("DUPLICATE_GUID",)),
                           ("C", ("BARCODE_COLLISION_IN_BUNDLE",)), ("D", ("BARCODE_COLLISION_IN_BUNDLE",)),
                           ("E", ("BARCODE_COLLISION_IN_BUNDLE",)), ("F", ("BARCODE_COLLISION_IN_BUNDLE",))}
        # Review #44: 12/13 xonali GTIN to'qnashuvi IKKI marta sanalmaydi
        assert rep["summary"]["barcode_collisions_in_bundle"] == 2
        assert rep["summary"]["barcode_collision_rows"] == 4


def test_GUID_sanoqlari_jami_qatorlarga_teng(db):
    """Review #47: noyob + takror + yo'q + buzuq = jami; rekonsiliatsiya kanonik GUID'larni sanaydi."""
    comp, _ = seed_company(db)
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(1), "a"), prod(g(1).upper(), "b"), prod("not-a-guid", "c"),
                             prod("   ", "d"), prod(g(2), "e")])
    s = rep["summary"]
    assert (s["valid_unique_guid_rows"], s["duplicate_guid_rows"], s["duplicate_guid_distinct"],
            s["missing_guid_rows"], s["invalid_guid_rows"]) == (1, 2, 1, 1, 1)
    assert sum((s["valid_unique_guid_rows"], s["duplicate_guid_rows"], s["missing_guid_rows"],
                s["invalid_guid_rows"])) == s["total_1c_products"]
    raw = rep["reconciliation"]["source_1c_raw"]
    assert (raw["guid_valid_distinct"], raw["guid_missing_or_invalid_rows"]) == (2, 2)
    assert rep["reconciliation"]["ok"]


def test_ikki_BinOS_mahsulotiga_mos_nom_AMBIGUOUS_ikkala_nomzod_hal_qilinmagan(db):
    comp, (br,) = seed_company(db)
    a = add_product(db, comp, br, "Chipsi")
    b = add_product(db, comp, br, "chipsi")
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(40), "CHIPSI")])
    r = _row(rep, g(40))
    assert r["classification"] == "AMBIGUOUS"
    assert {c["product_id"] for c in r["candidates"]} == {str(a.id), str(b.id)}
    assert _live(rep, a.id)["status"] == _live(rep, b.id)["status"] == "unresolved_candidate"


def test_ochirilgan_GUIDli_mahsulot_DELETED_MATCH(db):
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Eski", guid=g(50), deleted=True)
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(50), "Eski")])
    assert _row(rep, g(50))["classification"] == "DELETED_MATCH"


def test_saqlangan_identitet_katta_harfda_yoki_1C_bolsa_NEW_emas_BLOCKED(db):
    """Review #6/#11: registrga sezgir qidiruv ikkinchi mahsulot yaratib, aslini o'chirib yuborardi."""
    comp, (br,) = seed_company(db)
    up = add_product(db, comp, br, "Eski nom", guid=g(60).upper())
    src = add_product(db, comp, br, "Boshqa eski", guid=g(61))
    src.source_system = "1C"
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(60), "Butunlay yangi nom"), prod(g(61), "Yana yangi nom")])
    for guid, p in ((g(60), up), (g(61), src)):
        r = _row(rep, guid)
        assert r["classification"] == "BLOCKED" and "IDENTITY_FORMAT_MISMATCH" in r["block"], r
        assert r["exact_product_id"] == str(p.id)
    assert rep["summary"]["new"] == 0 and rep["summary"]["identity_format_mismatch_rows"] == 2


def test_exact_mahsulot_barkodi_boshqa_mahsulotda_qaror_talab_qiladi_GTIN_varianti_bilan(db):
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Asl", guid=g(60))
    other = add_product(db, comp, br, "Boshqa", barcodes=["012345678905"])
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(60), "Asl", barcodes=["0012345678905"])])
    r = _row(rep, g(60))
    assert r["classification"] == "EXACT_MATCH" and "BARCODE_OWNED_BY_OTHER_PRODUCT" in r["decide"]
    assert r["barcodes"][0]["owners"] == [str(other.id)]
    assert _live(rep, other.id)["status"] == "unresolved_candidate"


def test_PLU_nomzod_dalili_va_toqnashuv(db):
    """Review #7: PLU bo'yicha mos tarozi mahsuloti NEW bo'lib, PLU'siz dublikat yaratilardi."""
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Kolbasa", plu="575", guid=g(70), unit_code="kg")
    pish = add_product(db, comp, br, "Колбаса докторская", plu="576", unit_code="kg")
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(70), "Kolbasa", unit="кг", okei="166", plu="00575"),
                             prod(g(71), "Колбаса докторская 576Код", unit="кг", okei="166", plu="576")])
    assert "PLU_COLLISION" not in _row(rep, g(70))["decide"]        # o'z PLU'si
    r = _row(rep, g(71))
    assert r["classification"] == "CANDIDATE" and r["target_product_id"] == str(pish.id)
    assert r["candidates"][0]["evidence"] == ["plu"] and r["plu_owners"] == [str(pish.id)]


def test_tiklanadigan_mahsulot_PLUsi_band(db):
    """Review #30: REACTIVATE ux_products_company_plu ga urilib apply yiqilardi."""
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Eski kolbasa", plu="575", guid=g(80), deleted=True, unit_code="kg")
    add_product(db, comp, br, "Faol kolbasa", plu="575", unit_code="kg")
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(80), "Eski kolbasa", unit="кг", okei="166")])
    r = _row(rep, g(80))
    assert r["classification"] == "DELETED_MATCH" and "REACTIVATE_PLU_CONFLICT" in r["decide"]
    assert r["candidates"][0]["plu_conflicts"]


def test_birlik_BinOS_jadvalida_yoq_bolsa_UNKNOWN_UNIT_hatto_xarita_bilan(db):
    """Review #15/#46: xarita BinOS'da yo'q kodni ko'rsatsa apply KeyError bilan yiqilardi."""
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Sim", guid=g(90))
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(90), "Sim", unit="бухта", okei="999"), prod(g(91), "Kabel", unit="бухта")],
                  unit_names={"Бухта": "metr"})
    for guid in (g(90), g(91)):
        assert "UNKNOWN_UNIT" in _row(rep, guid)["decide"]
    assert rep["summary"]["unknown_unit_names"] == ["бухта->metr"]
    assert rep["unit_names_extra"] == {"бухта": "metr"}
    assert _row(rep, g(90))["candidates"][0]["unit"] == "unverifiable"


def test_EXCLUDED_qatorlar_hisoblagichlarni_shishirmaydi(db):
    """Review #43: papka/xizmat qatorlari narxsiz/birliksiz/qoldiqsiz deb sanalardi."""
    comp, _ = seed_company(db)
    db.commit()
    folder = prod(g(1), "Papka", unit=None, retail=None, purchase=None, stock=(), is_folder=True)
    service = prod(g(2), "Yetkazish", unit="услуга", retail=None, stock=(), kind="service")
    rep, _ = _rep(db, comp, [folder, service, prod(g(3), "Tovar")])
    s = rep["summary"]
    assert (s["excluded"], s["new"]) == (2, 1)
    assert s["excluded_by_reason"] == {"folder": 1, "kind:service": 1}
    assert (s["retail_price_absent"], s["unknown_unit_rows"], s["missing_stock_rows"], s["zero_stock_rows"]) == (0, 0, 0, 0)
    assert s["unknown_unit_names"] == []
    from app.services.migrator_1c.mapping import build_template
    assert "missing_price" not in build_template(rep)["policies"]
    assert "unknown_unit" not in build_template(rep)["policies"]


def test_1Cda_yoq_va_hal_qilinmagan_BinOS_mahsulotlari_holati(db):
    """Review #40: AMBIGUOUS/EXCLUDED/EXACT qatorlarining nomzodlari 1C'da BOR deb yashirinib qolardi."""
    comp, (br,) = seed_company(db)
    keep = add_product(db, comp, br, "1C'da bor", barcodes=["4600000000055"])
    gone = add_product(db, comp, br, "Faqat BinOS'da", qty="4")
    marked = add_product(db, comp, br, "O'chirishga belgilangan", qty="2")
    exact = add_product(db, comp, br, "Exact", guid=g(81))
    dup = add_product(db, comp, br, "exact")
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(80), "x", barcodes=["4600000000055"]),
                             prod(g(82), "O'chirishga belgilangan", deletion_mark=True),
                             prod(g(81), "Exact")])
    assert _live(rep, keep.id)["status"] == "targeted"
    assert _live(rep, exact.id)["status"] == "targeted"
    assert _live(rep, gone.id)["status"] == "not_in_source" and _live(rep, gone.id)["inventory"] == {str(br.id): "4.000"}
    assert _live(rep, marked.id)["status"] == "unresolved_candidate"
    assert _live(rep, dup.id)["status"] == "unresolved_candidate"
    s = rep["summary"]
    assert (s["binos_targeted"], s["binos_unresolved_candidates"], s["binos_not_in_source"]) == (2, 2, 1)


def test_rekonsiliatsiya_hisob_ayniyati_EXCLUDED_BLOCKED_preview(db):
    """Review #41: preview xom hisobning nusxasi edi va EXCLUDED/BLOCKED qoldig'ini ham ko'rsatardi."""
    comp, _ = seed_company(db)
    db.commit()
    rep, _ = _rep(db, comp, [
        prod(g(90), "a", stock=("10.500",), retail="100.00", barcodes=["4600000000062", "4600000000079"]),
        prod(g(91), "b", stock=("0",), retail="5.25", barcodes=["4600000000086", "4600000000086"]),
        prod(g(92), "c", stock=(), retail=None),
        prod(g(93), "d", stock=("-2",), retail="999999.99"),
        prod(g(94), "o'chirilgan", stock=("100",), retail="1.00", deletion_mark=True),
        prod(g(95), "aniqlik", stock=("1.2345",), retail="3.00"),
        prod(g(96), "buzuq qty", stock=("12,5",), retail="4.00"),
    ])
    rc = rep["reconciliation"]
    assert rc["ok"] is True, {k: v for k, v in rc["identities"].items() if not v["ok"]}
    raw, pv, bl, ex = rc["source_1c_raw"], rc["buckets"]["migratable"], rc["buckets"]["blocked"], rc["buckets"]["excluded"]
    assert raw["sku_count"] == 7 and (pv["sku_count"], bl["sku_count"], ex["sku_count"]) == (4, 2, 1)
    assert Decimal(raw["stock_total_qty"]) == Decimal("109.7345")
    assert pv["stock_total_qty"] == "8.500" and Decimal(bl["stock_total_qty"]) == Decimal("1.2345")
    assert ex["stock_total_qty"] == "100"
    assert raw["invalid_qty_rows_selected"] == 1 == bl["invalid_qty_rows_selected"]
    assert raw["barcode_entries"] == 4 and pv["barcodes_kept"] == 3 and pv["barcode_duplicates_dropped"] == 1
    assert (pv["retail_price_absent"], pv["retail_price_positive"]) == (1, 3)
    assert (pv["retail_price_min"], pv["retail_price_max"]) == ("5.25", "999999.99")
    assert (pv["zero_stock_products"], pv["negative_stock_products"], pv["missing_stock_products"]) == (1, 1, 1)


def test_manfiy_va_narx_tariflari_bir_xil_ikki_ombor(db):
    """Review #45: xulosa (qator×ombor) va rekonsiliatsiya (mahsulot jami) turli manfiy sonini berardi."""
    comp, _ = seed_company(db)
    db.commit()
    p = prod(g(1), "a", stock=("10",), retail="12,50")
    p["stock"].append({"warehouse_guid": WH_SECOND, "qty": "-3"})

    def two_wh(d):
        d["selection"]["warehouse_guids"] = [WH_MAIN, WH_SECOND]
    rep, _ = _rep(db, comp, [p, prod(g(2), "b", retail="0")], mutate=two_wh)
    s, raw = rep["summary"], rep["reconciliation"]["source_1c_raw"]
    assert s["negative_stock_rows"] == 1 and s["negative_stock_products"] == 1
    assert raw["negative_stock_rows_selected"] == 1
    assert (s["retail_price_invalid"], s["retail_price_zero"], s["retail_price_absent"]) == (1, 1, 0)
    assert (raw["retail_price_invalid"], raw["retail_price_zero"], raw["retail_price_absent"]) == (1, 1, 0)
    assert rep["reconciliation"]["ok"]


def test_tanlanmagan_ombor_qoldigi_korinadi_va_bayroqlar_malumotdan(db):
    """Review #42: tanlanmagan ombordagi qoldiq hisobotda umuman ko'rinmasdi."""
    comp, _ = seed_company(db)
    db.commit()
    ps = []
    for i in range(3):
        p = prod(g(i + 1), f"p{i}", stock=())
        p["stock"] = [{"warehouse_guid": WH_SECOND, "qty": "250.000"}]
        ps.append(p)
    rep, _ = _rep(db, comp, ps)
    s, raw = rep["summary"], rep["reconciliation"]["source_1c_raw"]
    assert s["stock_only_in_unselected_warehouse_rows"] == 3 and s["missing_stock_rows"] == 0
    assert Decimal(s["unselected_warehouse_stock_qty"]) == Decimal("750")
    assert Decimal(raw["stock_by_warehouse_all"][WH_SECOND]) == Decimal("750")
    assert s["warehouses_with_stock"] == [WH_SECOND] and s["multiple_warehouses"] is False
    assert s["multiple_price_types"] is True                        # chakana + kelish narxlari to'ldirilgan
    one = _rep(db, comp, [prod(g(9), "x", purchase=None)])[0]["summary"]
    assert one["multiple_price_types"] is False and one["multiple_warehouses"] is False


def test_PLU_toqnashuv_qatorlari_ikki_marta_sanalmaydi(db):
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "D", guid=g(1), plu="576", deleted=True, unit_code="kg")
    add_product(db, comp, br, "L", plu="576", unit_code="kg")
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(1), "D", unit="кг", okei="166", plu="575"),
                             prod(g(2), "Yangi", unit="кг", okei="166", plu="575")])
    assert set(_row(rep, g(1))["decide"]) >= {"PLU_COLLISION", "REACTIVATE_PLU_CONFLICT"}
    assert rep["summary"]["plu_collision_rows"] == 2


def test_bir_xil_artikul_minglab_qatorda_kvadratik_emas(db):
    """Review-2: used_by_other har chaqiruvda to'plam nusxasini yaratardi (45k qatorda 109 s)."""
    import time
    comp, _ = seed_company(db)
    db.commit()
    snap = load_snapshot(db, comp.code)
    ps = [prod(g(i + 1), f"T{i}", article="-", barcodes=()) for i in range(12000)]
    b = load(bundle_dict(ps))
    t0 = time.time()
    rep = C.classify(b, snap)
    assert rep["summary"]["article_collision_rows"] == 12000
    assert time.time() - t0 < 30, time.time() - t0


def test_manifest_jami_mos_kelmasa_rekonsiliatsiya_MOS_EMAS(db):
    comp, _ = seed_company(db)
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(95), "a", stock=("3",))],
                  manifest_override={"stock_qty_by_warehouse": {WH_MAIN: "4"}})
    assert rep["reconciliation"]["ok"] is False
    assert rep["reconciliation"]["manifest"]["diffs"][WH_MAIN] == {"manifest": "4", "recomputed": "3"}


def test_quruq_yurish_deterministik_va_yozuvsiz(db):
    from app.models.imports import ImportJob
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "Mavjud", barcodes=["4600000000086"], qty="2")
    db.commit()
    ps = [prod(g(100 + i), f"Tovar {i}", barcodes=[f"47000000001{i:02d}"]) for i in range(30)]
    ps.append(prod(g(200), "yangi", barcodes=["4600000000086"]))
    jobs_before = db.query(ImportJob).count()
    fp_before = load_snapshot(db, comp.code).fingerprint
    r1, _ = _rep(db, comp, ps)
    r2, _ = _rep(db, comp, ps)
    assert r1["report_sha256"] == r2["report_sha256"] and C.report_json(r1) == C.report_json(r2)
    shuffled = list(ps)
    random.Random(1).shuffle(shuffled)
    r3, _ = _rep(db, comp, shuffled)
    strip = lambda rep: [{k: v for k, v in x.items() if k != "row"} for x in rep["rows"]]  # noqa: E731
    assert strip(r1) == strip(r3) and r1["summary"] == r3["summary"]
    db.rollback()
    assert load_snapshot(db, comp.code).fingerprint == fp_before
    assert db.query(ImportJob).count() == jobs_before


def test_CLI_quruq_yurish_read_only_ijobiy_va_negativ_isbot(db, tmp_path, monkeypatch):
    from app.tools import migrate_1c
    comp, (br,) = seed_company(db)
    add_product(db, comp, br, "CLI mahsulot", barcodes=["4600000000093"])
    db.commit()
    path = str(tmp_path / "export.json")
    write(bundle_dict([prod(g(300), "CLI", barcodes=["4600000000093"])]), path)
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", "sqlite:///./_pytest.db"))
    out = str(tmp_path / "report.json")
    rc = migrate_1c.main(["dry-run", "--bundle", path, "--company-code", comp.code, "--out", out])
    assert rc == 0
    rep = json.loads(open(out, encoding="utf-8").read())
    for k in ("before", "after"):
        proof = rep["read_only_proof"][k]
        assert proof["enforced"] is True and proof["query_only"] == 1 and proof["probe"].startswith("rejected")
    assert rep["database"] == {"dialect": "sqlite", "system_identifier": None, "database": None}
    assert rep["report_sha256"] == C.report_hash(rep)
    assert _row(rep, g(300))["classification"] == "CANDIDATE"


def test_CLI_notogri_sqlite_yoli_fayl_yaratmaydi(tmp_path, monkeypatch):
    from app.tools import migrate_1c
    path = str(tmp_path / "export.json")
    write(bundle_dict([prod(g(1), "A")]), path)
    ghost = tmp_path / "yoq.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{ghost}")
    with pytest.raises(SystemExit, match="topilmadi"):
        migrate_1c.main(["dry-run", "--bundle", path, "--company-code", "x", "--out", str(tmp_path / "r.json")])
    assert not ghost.exists()


def test_prove_read_only_yozuvchi_sessiyada_PermissionError(db):
    """Review #37: har qanday xato 'ENFORCED' deb yozilardi; yozuvchi sessiya isbot bermasligi SHART."""
    from app.services.migrator_1c.guard import prove_read_only
    with pytest.raises(PermissionError, match="query_only"):
        prove_read_only(db)


def test_prove_read_only_boshqa_xatoni_isbot_deb_qabul_qilmaydi(db, monkeypatch):
    from sqlalchemy import text

    from app.services.migrator_1c import guard
    db.execute(text("PRAGMA query_only = ON"))
    try:
        orig_execute = db.execute

        def fake(stmt, *a, **k):
            if "UPDATE companies" in str(stmt):
                return orig_execute(text("UPDATE yoq_jadval SET x = 1"))      # 'no such table' — read-only EMAS
            return orig_execute(stmt, *a, **k)
        monkeypatch.setattr(db, "execute", fake)
        with pytest.raises(PermissionError, match="NOANIQ"):
            guard.prove_read_only(db)
    finally:
        monkeypatch.undo()
        db.execute(text("PRAGMA query_only = OFF"))


def test_CLI_sha_yon_fayli_buzilsa_rad(tmp_path):
    from app.services.migrator_1c.bundle import BundleError
    from app.tools import migrate_1c
    path = str(tmp_path / "e.json")
    write(bundle_dict([prod(g(1), "A")]), path)
    with open(path + ".sha256", "w") as f:
        f.write("0" * 64)
    with pytest.raises(BundleError):
        migrate_1c.main(["verify-bundle", "--bundle", path])
    os.remove(path + ".sha256")
    with pytest.raises(BundleError, match="yon fayli topilmadi"):
        migrate_1c.main(["verify-bundle", "--bundle", path])


def test_lot_kuzatuvli_maqsad_bloklanadi(db):
    comp, (br,) = seed_company(db)
    p = add_product(db, comp, br, "Kuzatuvli", guid=g(400))
    p.track_lots = True
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(400), "Kuzatuvli")])
    r = _row(rep, g(400))
    assert r["classification"] == "BLOCKED" and "TARGET_LOT_TRACKED" in r["block"]
    assert rep["binos"]["tracked_products"] == 1


def test_decimal_matnlari_hisobotda_aniq(db):
    comp, _ = seed_company(db)
    db.commit()
    rep, _ = _rep(db, comp, [prod(g(500), "a", stock=("0.125",), retail="12345.67", purchase="0.01")])
    r = _row(rep, g(500))
    assert (r["stock_total"], r["retail_price"], r["purchase_price"]) == ("0.125", "12345.67", "0.01")
    assert Decimal(r["stock_total"]) == Decimal("0.125")
