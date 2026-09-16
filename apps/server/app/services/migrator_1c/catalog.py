# -*- coding: utf-8 -*-
"""BinOS katalogining FAQAT O'QISH ko'rinishi (bitta tenant) va uning barmoq izi.

Barmoq izi quruq yurish hisobotiga kiradi. Apply hisobotni QAYTA hisoblaydi va operator ko'rib
chiqqan hisobot xeshi bilan solishtiradi — ko'rib chiqilgandan keyin katalog bir bayt ham
o'zgargan bo'lsa, apply RAD etiladi.

IDENTITET KANONIK o'qiladi: `source_system` registrsiz ('1c', '1C', kirill '1С'), `external_id`
esa `canon_guid` orqali. Saqlangan matn kanonik shakldan farq qilsa (yoki bitta GUID ikki mahsulotda
bo'lsa) mahsulot `identity_problem` ga tushadi — tasnif uni baribir ANIQ MOS deb topadi (ikkinchi
mahsulot yaratilmaydi), lekin qatorni BLOKLAYDI: avval saqlangan identitet qo'lda tuzatiladi.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.catalog import Product, ProductBarcode, Unit
from app.models.enums import ImportStatus
from app.models.imports import ImportJob
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch, Company
from app.models.settings import Setting

from . import SOURCE_SYSTEM
from .normalize import PRICE_SCALE, QTY_SCALE, canon_guid, normalize_barcode

_SOURCE_ALIASES = {"1c", "1с"}             # lotin 'c' va kirill 'с'


def q3(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(QTY_SCALE)


def q2(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(PRICE_SCALE)


def is_1c_source(s) -> bool:
    return isinstance(s, str) and s.strip().lower() in _SOURCE_ALIASES


def norm_plu(s) -> str | None:
    """BinOS `_norm_plu` bilan AYNI kanonik shakl (yetakchi nolsiz raqam)."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not (t.isascii() and t.isdigit()):
        return None
    return t.lstrip("0") or "0"


def plu_key(s) -> str | None:
    """PLU to'qnashuv kaliti: raqamli PLU — kanonik ('0575' == '575'); raqamsiz (V2 importi har qanday matnni
    saqlagan, masalan '12A') — AYNAN saqlangan satr, chunki `ux_products_company_plu` xom qiymat bo'yicha."""
    if s is None:
        return None
    k = norm_plu(s)
    return k if k is not None else "raw:" + str(s)


@dataclass
class CatalogSnapshot:
    company_id: str
    company_code: str
    units: set[str]
    branches: dict[str, dict]
    products: dict[str, dict]
    barcodes: dict[str, str]                       # barcode -> product_id (kompaniya doirasida noyob)
    barcodes_of: dict[str, set[str]]
    inventory: dict[tuple[str, str], Decimal]      # (product_id, branch_id) -> qty
    catalog_setting: dict
    committed_1c_jobs: list[dict]
    movement_ref_types: dict[str, int]
    fingerprint: str = ""
    by_external: dict[str, set[str]] = field(default_factory=dict)   # kanonik guid -> product_id'lar
    identity_problem: dict[str, str] = field(default_factory=dict)   # product_id -> sabab
    guid_other_source: dict[str, set[str]] = field(default_factory=dict)  # GUID boshqa manba nomi bilan saqlangan
    article_codes: set[str] = field(default_factory=set)             # o'chirilganlari ham (unique cheklov)
    by_article: dict[str, set[str]] = field(default_factory=dict)
    by_barcode_key: dict[str, set[str]] = field(default_factory=dict)
    by_name: dict[str, set[str]] = field(default_factory=dict)
    by_plu: dict[str, set[str]] = field(default_factory=dict)        # FAQAT o'chirilmagan mahsulotlar
    inventory_of: dict[str, dict[str, Decimal]] = field(default_factory=dict)


def load_snapshot(db: Session, company_code: str) -> CatalogSnapshot:
    from app.services.catalog_match import norm_key          # MAVJUD nom kaliti qayta ishlatiladi

    comp = db.query(Company).filter(Company.code == company_code, Company.deleted_at.is_(None)).first()
    if comp is None:
        raise LookupError(f"do'kon topilmadi: {company_code}")
    cid = comp.id
    units_by_id = {str(u.id): u.code for u in db.query(Unit).all()}
    branches = {str(b.id): {"id": str(b.id), "code": b.code, "name": b.name, "is_active": bool(b.is_active),
                            "deleted": b.deleted_at is not None}
                for b in db.query(Branch).filter(Branch.company_id == cid).all()}
    products = {}
    # ⚠️  USTUNLAR so'raladi, Product obyekti EMAS: `Product.barcodes` relationship'i `selectin` —
    #     obyekt so'rovi har 500 mahsulotga qo'shimcha SELECT qilardi (N+1, katalog hajmiga bog'liq).
    cols = (Product.id, Product.name, Product.article_code, Product.sku, Product.source_system, Product.external_id,
            Product.deleted_at, Product.is_active, Product.unit_id, Product.is_weighted, Product.plu_code,
            Product.base_sell_price, Product.base_buy_price, Product.track_lots, Product.track_expiry,
            Product.lots_activated_at)
    for (pid, name, art, sku, ss, ext, deleted_at, is_active, unit_id, is_weighted, plu, sell, buy,
         track_lots, track_expiry, lots_at) in db.query(*cols).filter(Product.company_id == cid).all():
        products[str(pid)] = {
            "id": str(pid), "name": name, "article_code": art, "sku": sku,
            "source_system": ss, "external_id": ext,
            "deleted": deleted_at is not None, "is_active": bool(is_active),
            "unit_code": units_by_id.get(str(unit_id)), "is_weighted": bool(is_weighted),
            "plu_code": plu, "sell_price": str(q2(sell)), "buy_price": str(q2(buy)),
            "track_lots": bool(track_lots), "track_expiry": bool(track_expiry),
            "lots_activated": lots_at is not None,
        }
    barcodes, barcodes_of = {}, {}
    for pid, bc in db.query(ProductBarcode.product_id, ProductBarcode.barcode).filter(
            ProductBarcode.company_id == cid).all():
        barcodes[str(bc)] = str(pid)
        barcodes_of.setdefault(str(pid), set()).add(str(bc))
    inventory = {}
    for pid, bid, qty in (db.query(Inventory.product_id, Inventory.branch_id, Inventory.qty)
                          .join(Product, Product.id == Inventory.product_id)
                          .filter(Product.company_id == cid).all()):
        inventory[(str(pid), str(bid))] = q3(qty)
    st = db.query(Setting).filter(Setting.company_id == cid, Setting.branch_id.is_(None),
                                  Setting.key == "catalog").first()
    jobs = []
    for j in db.query(ImportJob).filter(ImportJob.company_id == cid,
                                        ImportJob.status.in_([ImportStatus.committing, ImportStatus.committed])).all():
        if not is_1c_source(j.source):
            continue
        cm = j.column_mapping or {}
        jobs.append({"id": str(j.id), "snapshot_id": j.snapshot_id, "content_sha256": j.content_sha256,
                     "status": j.status.value, "mode": j.mode, "hash_contract_version": j.hash_contract_version,
                     "snapshot_at": cm.get("snapshot_at"), "export_id": cm.get("export_id"),
                     "migrator": cm.get("migrator")})
    mrt: dict[str, int] = {}
    for rt, n in (db.query(StockMovement.ref_type, func.count(StockMovement.id))
                  .join(Product, Product.id == StockMovement.product_id)
                  .filter(Product.company_id == cid).group_by(StockMovement.ref_type).all()):
        mrt[rt or "-"] = mrt.get(rt or "-", 0) + int(n)

    snap = CatalogSnapshot(company_id=str(cid), company_code=comp.code, units=set(units_by_id.values()),
                           branches=branches, products=products, barcodes=barcodes, barcodes_of=barcodes_of,
                           inventory=inventory, catalog_setting=dict(st.value or {}) if st else {},
                           committed_1c_jobs=sorted(jobs, key=lambda j: j["id"]), movement_ref_types=mrt)
    for pid, p in products.items():
        ext = p["external_id"]
        g = canon_guid(ext.strip())[0] if isinstance(ext, str) else None
        if g and is_1c_source(p["source_system"]):
            snap.by_external.setdefault(g, set()).add(pid)
            if ext != g or p["source_system"] != SOURCE_SYSTEM:
                snap.identity_problem[pid] = "IDENTITY_FORMAT_MISMATCH"
        elif g:
            # apply va post-tekshiruv GUID'ni manbadan qat'i nazar tekshiradi — quruq yurish ham shuni ko'rsin
            snap.guid_other_source.setdefault(g, set()).add(pid)
        if p["article_code"] is not None:
            snap.article_codes.add(p["article_code"])
            if p["article_code"]:
                snap.by_article.setdefault(p["article_code"], set()).add(pid)
        nk = norm_key(p["name"])
        if nk:
            snap.by_name.setdefault(nk, set()).add(pid)
        if not p["deleted"]:
            k = plu_key(p["plu_code"])
            if k is not None:
                snap.by_plu.setdefault(k, set()).add(pid)
    for g, pids in snap.by_external.items():
        if len(pids) > 1:
            for pid in pids:
                snap.identity_problem[pid] = "IDENTITY_DUPLICATE_IN_BINOS"
    for bc, pid in barcodes.items():
        for k in barcode_keys(bc):
            snap.by_barcode_key.setdefault(k, set()).add(pid)
    for (pid, bid), q in inventory.items():
        snap.inventory_of.setdefault(pid, {})[bid] = q
    snap.fingerprint = fingerprint(snap)
    return snap


def barcode_keys(value: str) -> tuple[str, ...]:
    """Egalik qidirish kalitlari — GTIN 12/13 variantlari bilan (tasnif, reja va apply AYNI qoida)."""
    nb = normalize_barcode(value, None)
    return nb.search_keys or (nb.value,)


def barcode_owners(snap: CatalogSnapshot, value: str) -> set[str]:
    out: set[str] = set()
    for k in barcode_keys(value):
        out |= snap.by_barcode_key.get(k, set())
    return out


def fingerprint(s: CatalogSnapshot) -> str:
    """Katalog mazmunining izi (Decimal matnlari, saralangan) — hisobot va apply'ni bog'laydi."""
    doc = {
        "company": [s.company_id, s.company_code],
        "units": sorted(s.units),
        "branches": sorted(json.dumps(b, sort_keys=True) for b in s.branches.values()),
        "products": sorted(json.dumps(p, sort_keys=True, ensure_ascii=False) for p in s.products.values()),
        "barcodes": sorted(f"{pid}\x1f{bc}" for bc, pid in s.barcodes.items()),
        "inventory": sorted(f"{k[0]}\x1f{k[1]}\x1f{v}" for k, v in s.inventory.items()),
        "catalog_setting": json.dumps(s.catalog_setting, sort_keys=True, default=str),
        "jobs": s.committed_1c_jobs,
        "movement_ref_types": s.movement_ref_types,
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
