# -*- coding: utf-8 -*-
"""Migrator V1 — bundle formati va normallashtirish (bazasiz unit testlar).

Har kafolat uchun SALBIY nazorat ham bor: buzilgan holat AYNAN rad etilishi yoki
AYNAN kodlanishi tekshiriladi.
"""
import hashlib
import json
import random
from decimal import Decimal

import pytest

from app.services.migrator_1c import bundle as B
from app.services.migrator_1c.normalize import (
    build_unit_table, canon_guid, fits_scale, gtin_key, normalize_barcode, normalize_product, parse_decimal,
    resolve_unit,
)
from tests.migrator_1c_helpers import bundle_dict, g, load, prod
from tests.migrator_1c_synth import PT_PURCHASE, PT_RETAIL, WH_MAIN, WH_SECOND, to_bytes, write

SEL = {"warehouse_guids": [WH_MAIN], "retail_price_type_guid": PT_RETAIL, "purchase_price_type_guid": None}
TABLE = build_unit_table(None)


def N(p, sel=SEL, table=TABLE):
    return normalize_product(0, p, sel, table)


# ── Fayl imzosi va tuzilma ───────────────────────────────────────────────────
def test_sha256_tekshiriladi_va_buzilgan_fayl_rad_etiladi():
    raw = to_bytes(bundle_dict([prod(g(1), "A")]))
    ok = B.load_bytes(raw, hashlib.sha256(raw).hexdigest())
    assert ok.file_sha256 == hashlib.sha256(raw).hexdigest()
    tampered = raw.replace(b'"5"', b'"6"')
    assert tampered != raw
    with pytest.raises(B.BundleError, match="SHA256 mos emas"):
        B.load_bytes(tampered, hashlib.sha256(raw).hexdigest())


def test_sidecar_formati_va_BOM():
    h = "a" * 64
    assert B.read_sidecar(f"{h}  export.json\n") == h
    assert B.read_sidecar(h.upper()) == h
    assert B.read_sidecar("﻿" + h + "  export.json\r\n") == h
    for bad in ("", "xyz", "a" * 63):
        with pytest.raises(B.BundleError):
            B.read_sidecar(bad)


def test_BOMli_sidecar_fayli_qabul_qilinadi(tmp_path):
    """1C `КодировкаТекста.UTF8` va PowerShell 5.1 `-Encoding utf8` BOM yozadi."""
    path = str(tmp_path / "e.json")
    sha = write(bundle_dict([prod(g(1), "A")]), path)
    with open(path + ".sha256", "wb") as f:
        f.write(b"\xef\xbb\xbf" + f"{sha}  e.json\r\n".encode())
    assert B.load_file(path).file_sha256 == sha


def test_utf8_bom_qabul_qilinadi_xesh_esa_xom_baytlardan():
    d = bundle_dict([prod(g(1), "Молоко")])
    raw = to_bytes(d, bom=True)
    b = B.load_bytes(raw, hashlib.sha256(raw).hexdigest())
    assert b.file_sha256 == hashlib.sha256(raw).hexdigest()
    assert b.content_sha256 == load(d).content_sha256        # BOM mazmunni o'zgartirmaydi


@pytest.mark.parametrize("patch,match", [
    (lambda t: t.replace('"code": "0000123"', '"code": 123'), "int"),
    (lambda t: t.replace('"qty": "5"', '"qty": 5.0'), "float"),
    (lambda t: t.replace('"qty": "5"', '"qty": NaN'), "NaN"),
])
def test_identifikator_yoki_miqdor_JSON_son_bolsa_butun_fayl_rad(patch, match):
    t = to_bytes(bundle_dict([prod(g(1), "A", code="0000123")])).decode()
    raw = patch(t).encode()
    with pytest.raises(B.BundleError, match=match):
        B.load_bytes(raw, None)


def test_takror_kalit_rad_etiladi():
    t = to_bytes(bundle_dict([prod(g(1), "A")])).decode()
    raw = t.replace('"kind": "goods"', '"kind": "goods", "kind": "service"').encode()
    with pytest.raises(B.BundleError, match="takror kalit"):
        B.load_bytes(raw, None)


@pytest.mark.parametrize("where", ["top", "product", "unit", "barcode", "manifest"])
def test_nomalum_kalit_rad_etiladi(where):
    d = bundle_dict([prod(g(1), "A", barcodes=["4600000000017"])])
    target = {"top": d, "product": d["products"][0], "unit": d["products"][0]["unit"],
              "barcode": d["products"][0]["barcodes"][0], "manifest": d["manifest"]}[where]
    target["extra_field"] = "x"
    with pytest.raises(B.BundleError, match="noma'lum kalit"):
        load(d)


def test_manifest_sanoqlari_fayl_bilan_mos_kelmasa_rad():
    d = bundle_dict([prod(g(1), "A", barcodes=["4600000000017"])])
    d["manifest"]["barcode_count"] = "2"
    with pytest.raises(B.BundleError, match="barcode_count"):
        load(d)


@pytest.mark.parametrize("bad", ["²", "١", "1 ", "-1", "1.0", "", "9" * 13])
def test_manifest_sanogi_faqat_ASCII_raqam_BundleError_ValueError_emas(bad):
    d = bundle_dict([prod(g(1), "A")])
    d["manifest"]["product_count"] = bad
    with pytest.raises(B.BundleError):
        load(d)


def test_manifest_qoldiq_kalitlari_AYNAN_tanlangan_omborlar():
    d = bundle_dict([prod(g(1), "A")])
    d["manifest"]["stock_qty_by_warehouse"][WH_SECOND] = "0"
    with pytest.raises(B.BundleError, match="tanlangan omborlar"):
        load(d)


def test_nomalum_ombor_va_tanlov_rad_etiladi():
    d = bundle_dict([prod(g(1), "A")])
    d["products"][0]["stock"] = [{"warehouse_guid": "ffffffff-ffff-4fff-8fff-ffffffffffff", "qty": "1"}]
    d["manifest"]["stock_row_count"] = "1"
    with pytest.raises(B.BundleError, match="noma'lum ombor"):
        load(d)
    d2 = bundle_dict([prod(g(1), "A")])
    d2["selection"]["warehouse_guids"] = ["ffffffff-ffff-4fff-8fff-ffffffffffff"]
    d2["manifest"]["stock_qty_by_warehouse"] = {"ffffffff-ffff-4fff-8fff-ffffffffffff": "0"}
    with pytest.raises(B.BundleError, match="warehouse_guids"):
        load(d2)


def test_tuzilma_GUIDlari_kichik_harfli_kanonik():
    d = bundle_dict([prod(g(1), "A")])
    d["selection"]["retail_price_type_guid"] = PT_RETAIL.upper()
    with pytest.raises(B.BundleError, match="kichik harfli"):
        load(d)


def test_kelish_narxi_turi_chakana_bilan_bir_xil_bolsa_rad():
    d = bundle_dict([prod(g(1), "A")])
    d["selection"]["purchase_price_type_guid"] = d["selection"]["retail_price_type_guid"]
    with pytest.raises(B.BundleError, match="BIR XIL"):
        load(d)


@pytest.mark.parametrize("ts", ["2026-09-20T09:00:00", "20.09.2026 09:00", "2026-09-20"])
def test_snapshot_vaqti_zonasiz_rad(ts):
    d = bundle_dict([prod(g(1), "A")], snapshot_at=ts)
    with pytest.raises(B.BundleError, match="snapshot_at"):
        load(d)


def test_schema_version_va_source_system_qatiy():
    d = bundle_dict([prod(g(1), "A")])
    d["schema_version"] = "binos-1c-v2"
    with pytest.raises(B.BundleError, match="schema_version"):
        load(d)
    d = bundle_dict([prod(g(1), "A")])
    d["source_system"] = "1C"
    with pytest.raises(B.BundleError, match="source_system"):
        load(d)


def test_mazmun_xeshi_tartib_va_formatdan_mustaqil_mazmun_ozgarsa_ozgaradi():
    ps = [prod(g(i), f"P{i}", barcodes=[f"47000000000{i:02d}"]) for i in range(1, 8)]
    a = load(bundle_dict(ps))
    shuffled = list(ps)
    random.Random(3).shuffle(shuffled)
    b = load(bundle_dict(shuffled, export_id="other-export"), indent=2)
    assert a.file_sha256 != b.file_sha256
    assert a.content_sha256 == b.content_sha256              # eksport vaqti/ID, tartib, format — mazmun emas
    ps2 = [dict(p) for p in ps]
    ps2[3] = dict(ps2[3], stock=[{"warehouse_guid": WH_MAIN, "qty": "6"}])
    assert load(bundle_dict(ps2)).content_sha256 != a.content_sha256
    # ko'plik yo'qolmaydi: [X] va [X, X] turli
    assert load(bundle_dict([ps[0]])).content_sha256 != load(bundle_dict([ps[0], ps[0]])).content_sha256


def test_mazmun_xeshi_KANONIK_GUID_registri_son_yozuvi_null_va_yoq_kalit():
    """Review #12: ayni ma'lumotni qayta eksport qilish (boshqa extractor versiyasi) ayni xesh bersin."""
    base = [prod(g(1), "A", stock=("12.5",), retail="100.5", barcodes=["4600000000017"]),
            prod(g(2), "B", stock=("0",), retail="7.00")]
    a = load(bundle_dict(base))
    variant = json.loads(json.dumps(base))
    variant[0]["guid"] = variant[0]["guid"].upper()
    variant[0]["stock"][0]["qty"] = "12.500"
    variant[0]["prices"][0]["value"] = "100.50"
    variant[1]["stock"][0]["qty"] = "0.000"
    variant[1]["prices"][0]["value"] = "7"
    for k in ("plu", "is_weighted"):
        variant[0].pop(k)                                    # yo'q kalit == null
    variant[0]["barcodes"][0]["value"] = " 4600000000017 "
    b = load(bundle_dict(variant, export_id="extractor-v2"))
    assert a.content_sha256 == b.content_sha256
    changed = json.loads(json.dumps(base))
    changed[0]["stock"][0]["qty"] = "12.501"
    assert load(bundle_dict(changed)).content_sha256 != a.content_sha256
    snap2 = load(bundle_dict(base, snapshot_at="2026-09-20T10:00:00+06:00"))
    assert snap2.content_sha256 != a.content_sha256          # boshqa snapshot vaqti — boshqa mazmun
    same_instant = load(bundle_dict(base, snapshot_at="2026-09-20T03:00:00+00:00"))
    assert same_instant.content_sha256 == a.content_sha256   # ayni lahza, boshqa offset


# ── GUID, Decimal, barkod, birlik ───────────────────────────────────────────
def test_guid_kanonik_shakli():
    u = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
    assert canon_guid(u) == (u.lower(), None)
    assert canon_guid(None) == (None, "MISSING_GUID")
    assert canon_guid("") == (None, "MISSING_GUID")
    for bad in ("{" + u + "}", u.replace("-", ""), " " + u, u + "\n", "00000000-0000-0000-0000-000000000000",
                "0000123", "３F2504E0-4F89-11D3-9A0C-0305E82C3301"):
        assert canon_guid(bad)[1] == "INVALID_GUID", bad


def test_decimal_faqat_qatiy_ASCII_matn():
    assert parse_decimal("12.345") == (Decimal("12.345"), None)
    assert parse_decimal("-25.500") == (Decimal("-25.500"), None)
    assert parse_decimal(None) == (None, None)
    for bad in ("1e3", "1,5", " 1", "1.", ".5", "+1", "NaN", "Infinity", "12\n", "120\n", "１２.５", "٣", "٥٠\n",
                "1" * 21, "1." + "1" * 13):
        assert parse_decimal(bad)[1] == "INVALID_NUMBER", repr(bad)


def test_juda_katta_son_dry_runni_yiqitmaydi():
    """Review #16/#49: 26+ xonali son InvalidOperation bilan butun eksportni yiqitardi."""
    big20 = "9" * 20
    n = N(prod(g(1), "A", stock=(big20,), retail=big20 + ".99"))
    assert {"QTY_OUT_OF_RANGE", "PRICE_OUT_OF_RANGE"} <= n.block
    huge = N(prod(g(1), "A", stock=("1" + "0" * 26,), retail="1" * 27))
    assert {"INVALID_QTY", "INVALID_PRICE"} <= huge.block
    assert fits_scale(Decimal("1" * 20 + ".001"), 3) and not fits_scale(Decimal("1" * 20 + ".0001"), 3)


def test_aniqlik_yoqolishi_yuvarlanmaydi_bloklanadi():
    n = N(prod(g(1), "A", stock=("1.2345",), retail="10.005", purchase=None))
    assert {"PRECISION_LOSS_QTY", "PRECISION_LOSS_PRICE"} <= n.block
    assert n.stock_total == Decimal("1.2345")               # qiymat O'ZGARTIRILMAGAN
    ok = N(prod(g(1), "A", stock=("1.2340",), retail="10.50", purchase=None))
    assert not ({"PRECISION_LOSS_QTY", "PRECISION_LOSS_PRICE"} & ok.block)


def test_juda_katta_miqdor_chegarasi():
    ok = N(prod(g(1), "A", stock=("99999999999.999",)))
    assert "QTY_OUT_OF_RANGE" not in ok.block and ok.stock_total == Decimal("99999999999.999")
    bad = N(prod(g(1), "A", stock=("100000000000",)))
    assert "QTY_OUT_OF_RANGE" in bad.block


def test_oldingi_nollar_saqlanadi():
    n = N(prod(g(1), "A", code="0000123", article="00000456", barcodes=["0012345678905"], plu="00575"))
    assert (n.code, n.article) == ("0000123", "00000456")
    assert n.barcodes[0].value == "0012345678905"
    assert n.plu == "575" and n.plu_source == "00575" and "PLU_LEADING_ZEROS" in n.info


def test_raqam_bolmagan_barkod_tozalanmaydi_buzuq_deb_belgilanadi():
    b = normalize_barcode("ABC-123456", "CODE128")
    assert (b.value, b.valid, b.search_keys) == ("ABC-123456", False, ())
    n = N(prod(g(1), "A", barcodes=["ABC-123456", "4600000000017"]))
    assert "INVALID_BARCODE" in n.decide and not n.block    # boshqa yaroqli barkod qatorni bloklamaydi
    t = normalize_barcode("  4780000000013 ", "EAN13")
    assert t.value == "4780000000013" and t.valid
    upc = normalize_barcode("012345678905", "UPC")
    assert "0012345678905" in upc.search_keys and upc.value == "012345678905"
    assert gtin_key("012345678905") == gtin_key("0012345678905") == "0012345678905"
    assert not normalize_barcode("４６００００００００１７", None).valid          # to'liq kenglikdagi raqamlar


def test_takror_barkod_bitta_qatorda_sanaladi():
    n = N(prod(g(1), "A", barcodes=["4600000000017", " 4600000000017"]))
    assert len(n.barcodes) == 1 and n.barcodes_dup_dropped == 1 and "DUPLICATE_BARCODE_IN_ROW" in n.info


def test_birlik_faqat_aniq_jadval():
    assert resolve_unit({"name": "шт", "code": "796"}, TABLE)[2] == "dona"
    assert resolve_unit({"name": "Кг.", "code": None}, TABLE)[2] == "kg"
    assert resolve_unit({"name": "бухта", "code": "796"}, TABLE)[2] is None     # nom bor -> OKEI fallback YO'Q
    assert resolve_unit({"name": "", "code": "166"}, TABLE)[2] == "kg"          # nom yo'q -> OKEI
    assert resolve_unit({"name": "бухта", "code": None}, build_unit_table({"Бухта": "upak"}))[2] == "upak"
    n = N(prod(g(1), "A", unit="бухта", okei="999"))
    assert n.unit_code is None                       # UNKNOWN_UNIT kodi tasnifda (BinOS birliklari bilan) qo'yiladi


@pytest.mark.parametrize("bad", [{"пачка.": "upak", "Пачка": "dona"}, {"x": 1}, {"x": ""}, {"": "dona"},
                                 {"x": None}, {".": "dona"}, {" . .": "dona"}])
def test_birlik_xaritasi_toqnashuv_va_tip_rad(bad):
    """Review #20: normallashganda to'qnashuvchi kalitlar dry-run va apply'da TURLI natija berardi."""
    with pytest.raises(ValueError):
        build_unit_table(bad)
    assert build_unit_table({"пачка.": "upak", "Пачка": "upak"})["пачка"] == "upak"   # bir xil qiymat — ruxsat


def test_birlik_kaliti_normallashuvi_idempotent():
    from app.services.migrator_1c.normalize import norm_unit_key
    for k in ("шт .", "Бут. .", " кг..", "упак", "l i t r . "):
        assert norm_unit_key(norm_unit_key(k)) == norm_unit_key(k), k
    assert norm_unit_key("шт .") == "шт"


def test_manfiy_qoldiq_va_narxsiz_qator_rad_etilmaydi_tasniflanadi():
    n = N(prod(g(1), "A", stock=("-25.500",), retail=None))
    assert {"NEGATIVE_STOCK", "MISSING_PRICE"} <= n.decide and not n.block
    assert n.retail_status == "absent" and n.negative_stock_rows == 1
    z = N(prod(g(1), "A", retail="0"))
    assert "ZERO_PRICE" in z.decide and z.retail_status == "zero"
    neg = N(prod(g(1), "A", retail="-1.00"))
    assert "NEGATIVE_PRICE" in neg.block and neg.retail_status == "negative"
    inv = N(prod(g(1), "A", retail="12,50"))
    assert "INVALID_PRICE" in inv.block and inv.retail_status == "invalid"


def test_tanlanmagan_ombor_qoldigi_jamiga_kirmaydi_lekin_korinadi():
    p = prod(g(1), "A", stock=("7",))
    p["stock"].append({"warehouse_guid": WH_SECOND, "qty": "100"})
    n = N(p)
    assert n.stock_total == Decimal("7") and "STOCK_IN_UNSELECTED_WAREHOUSE" in n.info
    assert n.stock_unselected == {WH_SECOND: Decimal("100")}
    only = N(prod(g(1), "A", stock=()) | {"stock": [{"warehouse_guid": WH_SECOND, "qty": "3"}]})
    assert "STOCK_ONLY_IN_UNSELECTED_WAREHOUSE" in only.info and "MISSING_STOCK" not in only.info
    none = N(prod(g(1), "A", stock=()))
    assert "MISSING_STOCK" in none.info and "ZERO_STOCK" not in none.info       # Review-2: qator yo'q != 0 qoldiq
    bad_unsel = N(prod(g(1), "A", stock=()) | {"stock": [{"warehouse_guid": WH_SECOND, "qty": "1 250"}]})
    assert "INVALID_QTY_UNSELECTED_WAREHOUSE" in bad_unsel.info and "MISSING_STOCK" not in bad_unsel.info
    assert bad_unsel.invalid_qty_unselected_rows == 1
    assert "ZERO_STOCK" in N(prod(g(1), "A", stock=("0",))).info
    two = {"warehouse_guids": [WH_MAIN, WH_SECOND], "retail_price_type_guid": PT_RETAIL, "purchase_price_type_guid": None}
    pm = prod(g(1), "A", stock=("5",))
    pm["stock"].append({"warehouse_guid": WH_SECOND, "qty": "-5"})
    assert "ZERO_STOCK" not in N(pm, two).info                                  # Review-3: +5/-5 != 0 qoldiq


def test_kelish_narxi_tanlangan_turdan():
    sel = dict(SEL, purchase_price_type_guid=PT_PURCHASE)
    n = N(prod(g(1), "A", retail="100.00", purchase="61.50"), sel)
    assert (n.retail_price, n.purchase_price) == (Decimal("100.00"), Decimal("61.50"))


def test_unicode_nom_ozgarmaydi():
    name = "Ўзбекча кирилл: «Қатиқ» ЁЎҚҒҲ — ёғли 3,5%"
    n = N(prod(g(1), "  " + name + " "))
    assert n.name == name and "WHITESPACE_TRIMMED" in n.info


def test_xarakteristika_bloklanadi_seriya_faqat_malumot():
    c = N(prod(g(1), "A", has_characteristics=True))
    s = N(prod(g(1), "A", has_series=True))
    assert "CHARACTERISTICS_UNSUPPORTED" in c.block
    assert "LOT_DATA_PRESENT" in s.info and not s.block


def test_json_dumps_roundtrip_float_yoq():
    d = bundle_dict([prod(g(1), "A", stock=("12.345",), retail="12345.67")])
    t = json.dumps(d)
    assert '"12.345"' in t                                   # matn sifatida


def test_buzuq_tiplar_BundleError_bilan_rad_TypeError_emas():
    """Review-2: massiv narx turi, yolg'iz surrogate va type=null takror barkod yuklovchini yiqitardi."""
    d = bundle_dict([prod(g(1), "A")])
    d["products"][0]["prices"][0]["price_type_guid"] = [PT_RETAIL]
    with pytest.raises(B.BundleError, match="narx turi"):
        load(d)
    d = bundle_dict([prod(g(1), "A")])
    d["products"][0]["stock"][0]["warehouse_guid"] = {"g": WH_MAIN}
    with pytest.raises(B.BundleError, match="ombor"):
        load(d)
    raw = to_bytes(bundle_dict([prod(g(1), "SURR")])).replace(b'"SURR"', b'"A\\ud800"')
    with pytest.raises(B.BundleError, match="surrogate"):
        B.load_bytes(raw, None)
    d = bundle_dict([prod(g(1), "A")])
    d["products"][0]["barcodes"] = [{"value": "4600000000093", "type": None}, {"value": "4600000000093", "type": "EAN13"}]
    finalize_counts(d)
    assert load(d).content_sha256


def finalize_counts(d):
    from tests.migrator_1c_synth import finalize
    finalize(d)


def test_28_xonadan_uzun_qiymat_jamida_yuvarlanmaydi():
    """#16/#49 qoldiq: 20+12 xonali qoldiq yig'indisi 28 xonali kontekstda yuvarlanib, BUTUN eksportni to'xtatardi."""
    from app.services.migrator_1c.catalog import CatalogSnapshot
    from app.services.migrator_1c.classify import classify
    big = "9999999999999999.999999999999"                       # 28 xona; jami 29 xona
    b = load(bundle_dict([prod(g(1), "Katta", stock=(big,)), prod(g(2), "Oddiy", stock=("0.000000000002",))]))
    snap = CatalogSnapshot(company_id="c", company_code="c", units={"dona"}, branches={}, products={}, barcodes={},
                           barcodes_of={}, inventory={}, catalog_setting={}, committed_1c_jobs=[], movement_ref_types={})
    rep = classify(b, snap)
    assert rep["reconciliation"]["ok"], [k for k, v in rep["reconciliation"]["identities"].items() if not v["ok"]]
    assert "QTY_OUT_OF_RANGE" in next(r for r in rep["rows"] if r["guid"] == g(1))["block"]


def test_manifest_jami_20_xonadan_oshsa_ham_fayl_yuklanadi():
    """Review-3: qator 20 xonali bo'lishi mumkin, N qatorning jami esa undan oshadi — butun eksport rad etilardi."""
    from app.services.migrator_1c.catalog import CatalogSnapshot
    from app.services.migrator_1c.classify import classify
    b = load(bundle_dict([prod(g(1), "Katta", stock=("99999999999999999999.999999999999",)),
                          prod(g(2), "Oddiy", stock=("5",))]))
    assert b.data["manifest"]["stock_qty_by_warehouse"][WH_MAIN] == "100000000000000000004.999999999999"
    snap = CatalogSnapshot(company_id="c", company_code="c", units={"dona"}, branches={}, products={}, barcodes={},
                           barcodes_of={}, inventory={}, catalog_setting={}, committed_1c_jobs=[], movement_ref_types={})
    rep = classify(b, snap)
    assert rep["reconciliation"]["ok"]
    assert [r["classification"] for r in sorted(rep["rows"], key=lambda r: r["guid"])] == ["BLOCKED", "NEW"]


def test_operator_JSON_fayllari_qatiy_oqiladi():
    """Review #19: mapping'dagi takror GUID qarori jimgina oxirgisi bilan almashardi."""
    with pytest.raises(B.BundleError, match="takror kalit"):
        B.strict_json_loads('{"decisions": {"g": {"action": "SKIP"}, "g": {"action": "LINK"}}}', allow_int=True)
    with pytest.raises(B.BundleError):
        B.strict_json_loads('{"approved_by": NaN}', allow_int=True)
    with pytest.raises(B.BundleError):
        B.strict_json_loads('{"x": 1.5}', allow_int=True)
    assert B.strict_json_loads('{"row": 12}', allow_int=True) == {"row": 12}
