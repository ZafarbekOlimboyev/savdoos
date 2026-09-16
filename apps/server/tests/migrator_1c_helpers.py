# -*- coding: utf-8 -*-
"""Migrator V1 testlari uchun umumiy yordamchilar (pytest to'plamiga kirmaydi)."""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from tests.migrator_1c_synth import PT_PURCHASE, PT_RETAIL, WH_MAIN, WH_SECOND, finalize, to_bytes


def g(n: int) -> str:
    """Deterministik GUID (test uchun)."""
    return str(uuid.UUID(int=0xA1C0000000000000 << 64 | n, version=4))


def prod(guid, name, *, code=None, article=None, unit="шт", okei="796", barcodes=(), retail="100.00",
         purchase="60.00", stock=("5",), kind="goods", **kw) -> dict:
    d = {"guid": guid, "code": code, "article": article, "name": name, "kind": kind, "is_folder": False,
         "deletion_mark": False, "has_characteristics": False, "has_series": False,
         "unit": {"name": unit, "code": okei} if unit is not None else None,
         "is_weighted": None, "plu": None,
         "barcodes": [{"value": b, "type": "EAN13"} for b in barcodes],
         "prices": ([{"price_type_guid": PT_RETAIL, "value": retail}]
                    + ([{"price_type_guid": PT_PURCHASE, "value": purchase}] if purchase is not None else [])),
         "stock": [{"warehouse_guid": WH_MAIN, "qty": q} for q in stock]}
    d.update(kw)
    return d


def bundle_dict(products, *, export_id="exp-1", snapshot_at="2026-09-20T09:00:00+06:00", manifest_override=None) -> dict:
    d = {
        "schema_version": "binos-1c-v1", "source_system": "1c", "export_id": export_id,
        "exported_at": "2026-09-20T09:00:05+06:00", "snapshot_at": snapshot_at,
        "infobase": {"platform_version": "8.3.TEST", "configuration_name": "TEST", "configuration_version": "1"},
        "extractor": {"name": "test", "version": "1"},
        "warehouses": [{"guid": WH_MAIN, "code": "1", "name": "Основной"}, {"guid": WH_SECOND, "code": "2", "name": "Склад 2"}],
        "price_types": [{"guid": PT_RETAIL, "code": "1", "name": "Розничная"},
                        {"guid": PT_PURCHASE, "code": "2", "name": "Закупочная"}],
        "selection": {"warehouse_guids": [WH_MAIN], "retail_price_type_guid": PT_RETAIL,
                      "purchase_price_type_guid": PT_PURCHASE},
        "products": list(products),
    }
    finalize(d)
    if manifest_override:
        d["manifest"].update(manifest_override)
    return d


def load(d: dict, indent=None):
    from app.services.migrator_1c.bundle import load_bytes
    raw = to_bytes(d, indent=indent)
    return load_bytes(raw, hashlib.sha256(raw).hexdigest())


def seed_company(db, code=None, branches=1):
    from app.models.org import Branch, Company
    comp = Company(id=uuid.uuid4(), name="M1C", code=code or ("m1c" + uuid.uuid4().hex[:8]), currency="KGS")
    db.add(comp)
    db.flush()
    brs = []
    for i in range(branches):
        b = Branch(id=uuid.uuid4(), company_id=comp.id, code=f"F0{i + 1}", name=f"F0{i + 1}", timezone="Asia/Bishkek")
        db.add(b)
        brs.append(b)
    db.flush()
    return comp, brs


def add_product(db, comp, branch, name, *, article=None, barcodes=(), qty="0", sell="50.00", guid=None,
                deleted=False, plu=None, unit_code="dona", legacy_movement=True):
    from datetime import datetime, timezone

    from app.models.catalog import Product, ProductBarcode, Unit
    from app.models.enums import MovementType
    from app.models.inventory import Inventory, StockMovement
    unit = db.query(Unit).filter(Unit.code == unit_code).first()
    p = Product(id=uuid.uuid4(), company_id=comp.id, article_code=article or ("A-" + uuid.uuid4().hex[:10]),
                sku=None, name=name, unit_id=unit.id, base_buy_price=Decimal("30.00"), base_sell_price=Decimal(sell),
                tax_rate=0, is_weighted=False, plu_code=plu, source_system="1c" if guid else None, external_id=guid,
                deleted_at=datetime.now(timezone.utc) if deleted else None)
    db.add(p)
    db.flush()
    for i, b in enumerate(barcodes):
        db.add(ProductBarcode(product_id=p.id, company_id=comp.id, barcode=b, is_primary=(i == 0)))
    db.add(Inventory(product_id=p.id, branch_id=branch.id, qty=Decimal(qty), min_qty=0,
                     updated_at=datetime.now(timezone.utc)))
    if legacy_movement and Decimal(qty) != 0:
        db.add(StockMovement(product_id=p.id, branch_id=branch.id, type=MovementType.adjustment, qty=Decimal(qty),
                             balance_after=Decimal(qty), ref_type="product_create", reason="legacy",
                             created_at=datetime.now(timezone.utc)))
    db.flush()
    return p


def all_policies() -> dict:
    return {"new_products": "create", "blocked_rows": "skip", "negative_stock": "zero",
            "missing_price": "keep_binos_price", "unknown_unit": "skip_row", "unit_differs": "skip_row",
            "invalid_barcode": "skip_barcode", "barcode_owned_by_other": "skip_barcode",
            "article_collision": "generate_article", "plu_collision": "drop_plu",
            "binos_missing_from_source": "keep", "names": "keep_binos", "unmapped_branch_stock": "close",
            "skipped_row_products": "keep"}


def mapping_for(report: dict, branch_id, decisions=None, policies=None, mode="CUTOVER_REFRESH") -> dict:
    from app.services.migrator_1c.mapping import build_template
    m = build_template(report)
    m["mode"] = mode
    m["approved_by"] = "test-operator"
    m["approved_at"] = "2026-09-20T10:00:00+06:00"
    m["warehouse_branch"] = {w: str(branch_id) for w in m["warehouse_branch"]}
    pol = all_policies()
    pol.update(policies or {})
    m["policies"] = {k: pol[k] for k in m["policies"]} | {k: v for k, v in (policies or {}).items()}
    m.pop("_policy_choices", None)
    dec = {}
    for guid, d in m["decisions"].items():
        dec[guid] = {"action": ""}
    dec.update(decisions or {})
    m["decisions"] = dec
    return m


def with_database(report: dict, ident: dict) -> dict:
    """Hisobotga CLI dry-run qo'shadigan `database` bo'limi (apply ko'rib chiqilgan bazani talab qiladi)."""
    return {**report, "database": {k: ident[k] for k in ("dialect", "system_identifier", "database")}}


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True, default=str)
