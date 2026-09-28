# -*- coding: utf-8 -*-
"""Migrator V1 testlari uchun umumiy yordamchilar (pytest to'plamiga kirmaydi)."""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from tests.migrator_1c_synth import PT_PURCHASE, PT_RETAIL, WH_MAIN, WH_SECOND, finalize, to_bytes


DEFAULT_EXPORTED_AT = "2026-09-20T09:00:05+06:00"


def _exported_after(snapshot_at: str, seconds: int = 5) -> str:
    """Kesimdan `seconds` soniya keyingi eksport vaqti — shartnomadagi namuna bilan bir xil naqsh.

    Qattiq yozilgan `exported_at` bo'lmaydi: test kesim vaqtini oldinga surganda eksport vaqti
    ham u bilan birga suriladi, aks holda `snapshot_at <= exported_at` invarianti yiqiladi."""
    from datetime import datetime, timedelta
    try:
        ts = datetime.fromisoformat(snapshot_at)
    except (TypeError, ValueError):
        ts = None
    if ts is None or ts.tzinfo is None:
        # Test ataylab buzuq `snapshot_at` beryapti — eksport vaqtini SOG'LOM qoldiramiz, aks holda
        # validator `exported_at` dan shikoyat qilib, sinov tekshirayotgan xatoni yashirib qo'yadi.
        return DEFAULT_EXPORTED_AT
    return (ts + timedelta(seconds=seconds)).isoformat()


def fresh_snapshot(hours_ago: float = 1.0) -> str:
    """HOZIRGA nisbatan kesim vaqti — yangilik darvozasi (`freshness.py`) uchun.

    Fikstura vaqtni QATTIQ yozmaydi: 24 soatlik darvoza o'rnatilgach, qattiq yozilgan sana
    bir kunda eskirib, butun to'plamni qizil qilardi."""
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=6))
    return (datetime.now(tz) - timedelta(hours=hours_ago)).isoformat()


#: Standart kesim JARAYON BOSHIDA bir marta hisoblanadi. Nega: mazmun xeshi testlari ikki
#: bundle'ni qurib xeshlarini solishtiradi — har chaqiruvda yangi vaqt ularni buzardi.
#: Aniq bir lahza kerak bo'lsa, test `snapshot_at=` ni ochiq beradi.
_DEFAULT_SNAPSHOT = fresh_snapshot()


def default_snapshot() -> str:
    """Fikstura standart kesimi (jarayon boshida bir marta hisoblangan)."""
    return _DEFAULT_SNAPSHOT


def shift_snapshot(hours: float, base: str | None = None) -> str:
    """Standart kesimni `hours` soatga suradi (manfiy — o'tmishga)."""
    from datetime import datetime, timedelta
    return (datetime.fromisoformat(base or _DEFAULT_SNAPSHOT) + timedelta(hours=hours)).isoformat()


def as_utc(iso: str) -> str:
    """AYNI lahza, lekin `+00:00` ofsetida — ofset ekvivalentligi testlari uchun."""
    from datetime import datetime, timezone
    return datetime.fromisoformat(iso).astimezone(timezone.utc).isoformat()


def source_copy_for(snapshot_at: str, sha: str = "a" * 64, size: str = "3221225472",
                    method: str = "DT_EXPORT", artifact: str = "dt") -> dict:
    """`source_copy` bloki — `source_snapshot_at` DOIM bundle kesimiga teng."""
    return {"sha256": sha, "byte_size": size, "source_snapshot_at": snapshot_at,
            "copy_method": method, "original_artifact_type": artifact}

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


def bundle_dict(products, *, export_id="exp-1", snapshot_at=None, manifest_override=None,
                source_copy=None) -> dict:
    snapshot_at = _DEFAULT_SNAPSHOT if snapshot_at is None else snapshot_at
    d = {
        "schema_version": "binos-1c-v1", "source_system": "1c", "export_id": export_id,
        # Eksport DOIM kesimdan keyin (shartnoma invarianti: snapshot_at <= exported_at).
        "exported_at": _exported_after(snapshot_at), "snapshot_at": snapshot_at,
        "source_copy": source_copy_for(snapshot_at) if source_copy is None else source_copy,
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
    m["prepared_by"] = "test-operator"
    m["prepared_at"] = "2026-09-20T10:00:00+06:00"
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
