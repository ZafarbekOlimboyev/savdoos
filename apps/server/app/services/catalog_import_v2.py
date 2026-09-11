# -*- coding: utf-8 -*-
"""1С Cutover V2 — quruq yurish (preview) va INITIAL_CREATE.

QAT'IY KAFOLATLAR:
  · `preview()` BAZAGA HECH NARSA YOZMAYDI — na Product, na Inventory, na
    StockMovement, na ProductBarcode, na Setting. Import ishi (ImportJob) ham
    ATAYLAB alohida tranzaksiyada, chaqiruvchi tomonidan yoziladi.
  · `initial_create()` FAQAT bo'sh katalogga ishlaydi va o'zgartirish (update)
    yo'lini UMUMAN o'z ichiga olmaydi — CUTOVER_REFRESH Phase 2 da.
  · Tashqi identifikatsiya (`source_system` + `external_id`) yoziladi va DB
    darajasida noyob — takror GUID mumkin emas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.catalog import Category, Product, ProductBarcode, Unit
from app.models.enums import ImportStatus, MovementType
from app.models.imports import ImportJob, ImportRow
from app.models.inventory import Inventory, StockMovement
from app.models.settings import Setting
from app.schemas.imports_v2 import ChangeOut, ImportMode, PreviewRowOut, RowClass
from app.services.catalog_match import (
    CatalogIndex, MatchOutcome, match_row, norm_barcode, norm_key,
)

CATALOG_SETTING_KEY = "catalog"      # ⚠️ `cash` kaliti bilan HECH QACHON aralashtirilmaydi


# ── settings.catalog — kassa `cutover_at` idan MUTLAQO MUSTAQIL ─────────────
def get_catalog_settings(db: Session, company_id) -> dict:
    """`settings.catalog` ni qaytaradi (yo'q bo'lsa — standart PRE_LIVE).

    ⚠️  `settings.cash.cutover_at` KASSA/LEDGER migratsiyasini bildiradi va bu
        yerga UMUMAN aloqasi yo'q. Ikkalasi alohida `settings` qatorlari —
        biri ikkinchisini hech qachon o'qimaydi va yozmaydi.
    """
    row = db.query(Setting).filter(
        Setting.company_id == company_id, Setting.branch_id.is_(None),
        Setting.key == CATALOG_SETTING_KEY).first()
    val = dict(row.value or {}) if row else {}
    val.setdefault("mode", "PRE_LIVE")
    val.setdefault("cutover_at", None)
    val.setdefault("source_system", None)
    val.setdefault("last_import_job_id", None)
    val.setdefault("last_snapshot_id", None)
    val.setdefault("last_content_sha256", None)
    return val


def set_catalog_settings(db: Session, company_id, **patch) -> dict:
    """`settings.catalog` ni yangilaydi. `settings.cash` ga TEGMAYDI."""
    row = db.query(Setting).filter(
        Setting.company_id == company_id, Setting.branch_id.is_(None),
        Setting.key == CATALOG_SETTING_KEY).first()
    cur = get_catalog_settings(db, company_id)
    cur.update({k: v for k, v in patch.items() if v is not None})
    if row is None:
        row = Setting(company_id=company_id, branch_id=None,
                      key=CATALOG_SETTING_KEY, value=cur)
        db.add(row)
    else:
        row.value = cur
        row.row_version = (row.row_version or 1) + 1
    return cur


def is_live(db: Session, company_id) -> bool:
    """Katalog cutover YOPILGANMI (SavdoOS haqiqat manbai)."""
    s = get_catalog_settings(db, company_id)
    return s.get("mode") == "LIVE" or bool(s.get("cutover_at"))


# ── Katalog indeksi ─────────────────────────────────────────────────────────
def build_index(db: Session, company_id) -> CatalogIndex:
    """Moslashtirish uchun katalog ko'rinishi. FAQAT O'QISH.

    O'CHIRILGAN mahsulotlar HAM kiritiladi: tashqi identifikatsiya soft-delete'dan
    omon qoladi, shu bois ularni ko'rmaslik yangi mahsulot yaratishga (va tarixiy
    identifikatsiyaning ikkiga bo'linishiga) olib kelardi.
    """
    prods = db.query(Product).filter(Product.company_id == company_id).all()
    units = {u.id: u.code for u in db.query(Unit).all()}
    rows = [{
        "id": p.id, "name": p.name, "article_code": p.article_code,
        "source_system": p.source_system, "external_id": p.external_id,
        "deleted": p.deleted_at is not None,
        "buy_price": float(p.base_buy_price or 0), "sell_price": float(p.base_sell_price or 0),
        "unit_code": units.get(p.unit_id), "is_weighted": bool(p.is_weighted),
        "plu_code": p.plu_code, "is_active": bool(p.is_active),
    } for p in prods]
    bcs = [(b.product_id, b.barcode) for b in db.query(ProductBarcode).filter(
        ProductBarcode.company_id == company_id).all()]
    return CatalogIndex.build(rows, bcs)


def _stock_map(db: Session, company_id) -> dict[str, float]:
    """product_id -> jami qoldiq (barcha filiallar)."""
    out: dict[str, float] = {}
    q = (db.query(Inventory.product_id, Inventory.qty)
         .join(Product, Product.id == Inventory.product_id)
         .filter(Product.company_id == company_id))
    for pid, qty in q.all():
        out[str(pid)] = out.get(str(pid), 0.0) + float(qty or 0)
    return out


def _barcodes_of(db: Session, company_id) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for b in db.query(ProductBarcode).filter(ProductBarcode.company_id == company_id).all():
        out.setdefault(str(b.product_id), set()).add(b.barcode)
    return out


def _row_problems(r) -> list[str]:
    """Backend qoidalarining AYNI nusxasi — server rad etadigan qatorni OLDIN topamiz."""
    bad = []
    if not (r.name or "").strip():
        bad.append("nom bo'sh")
    if r.sell_price <= 0:
        bad.append("sotish narxi <= 0")
    if r.buy_price < 0:
        bad.append("kelish narxi manfiy")
    if r.stock < 0:
        bad.append("qoldiq manfiy")
    for b in r.barcodes:
        if norm_barcode(b) is None:
            bad.append(f"barkod 6-14 raqam emas: {b}")
    return bad


# ── PREVIEW — YOZUVSIZ ──────────────────────────────────────────────────────
def preview(db: Session, company_id, body, valid_units: set[str]) -> tuple[list[PreviewRowOut], list[str]]:
    """Har manba qatorini tasniflaydi. BAZAGA HECH NARSA YOZILMAYDI.

    Qaytaradi: (qator natijalari, manbada yo'q mahsulot nomlari).
    """
    ix = build_index(db, company_id)
    stock = _stock_map(db, company_id)
    have_bc = _barcodes_of(db, company_id)
    seen_ext: dict[str, int] = {}
    matched_ids: set[str] = set()
    out: list[PreviewRowOut] = []

    for i, r in enumerate(body.rows, start=1):
        problems = _row_problems(r)
        if r.unit and r.unit not in valid_units:
            problems.append(f"noma'lum o'lchov birligi: {r.unit}")
        ext = (r.external_id or "").strip()
        if ext:
            # Bitta faylда bir GUID ikki marta — manba buzuq; ikkalasi ham INVALID.
            if ext in seen_ext:
                problems.append(f"external_id fayl ichida takrorlanadi ({seen_ext[ext]}-qator)")
            seen_ext.setdefault(ext, i)
        if body.mode == ImportMode.INITIAL_CREATE and not ext:
            problems.append("INITIAL_CREATE uchun external_id MAJBURIY")

        if problems:
            out.append(PreviewRowOut(row_no=i, classification=RowClass.INVALID, name=r.name,
                                     external_id=ext or None, problem=problems))
            continue

        m = match_row({"external_id": ext, "article": r.article,
                       "barcodes": r.barcodes, "name": r.name},
                      ix, body.source_system)

        if m.outcome is MatchOutcome.AMBIGUOUS:
            out.append(PreviewRowOut(row_no=i, classification=RowClass.AMBIGUOUS, name=r.name,
                                     external_id=ext or None, evidence=m.evidence,
                                     problem=m.conflict))
            continue
        if m.outcome is MatchOutcome.NEW:
            out.append(PreviewRowOut(row_no=i, classification=RowClass.NEW, name=r.name,
                                     external_id=ext or None, evidence=m.evidence))
            continue
        if m.outcome is MatchOutcome.DELETED_MATCH:
            # Ikkinchi Product YARATILMAYDI — operator qarori kerak.
            out.append(PreviewRowOut(
                row_no=i, classification=RowClass.DELETED_MATCH, name=r.name,
                external_id=ext or None, product_id=uuid.UUID(str(m.product_id)),
                match_level=m.level.value, evidence=m.evidence,
                problem=["mos kelgan mahsulot O'CHIRILGAN — REACTIVATE_EXISTING yoki "
                         "KEEP_DELETED tanlanishi kerak"]))
            matched_ids.add(str(m.product_id))
            continue

        pid = str(m.product_id)
        matched_ids.add(pid)
        cur = ix.products[pid]
        changes: list[ChangeOut] = []
        if norm_key(cur["name"]) != norm_key(r.name) or cur["name"] != r.name:
            changes.append(ChangeOut(field="name", old=cur["name"], new=r.name))
        if abs(cur["buy_price"] - r.buy_price) > 1e-9:
            changes.append(ChangeOut(field="buy_price", old=f"{cur['buy_price']:g}",
                                     new=f"{r.buy_price:g}"))
        if abs(cur["sell_price"] - r.sell_price) > 1e-9:
            changes.append(ChangeOut(field="sell_price", old=f"{cur['sell_price']:g}",
                                     new=f"{r.sell_price:g}"))
        old_qty = stock.get(pid, 0.0)
        if abs(old_qty - r.stock) > 1e-9:
            changes.append(ChangeOut(field="stock", old=f"{old_qty:g}", new=f"{r.stock:g}"))
        new_bc = {b for b in (norm_barcode(x) for x in r.barcodes) if b} - have_bc.get(pid, set())
        if new_bc:
            changes.append(ChangeOut(field="barcodes", old=str(len(have_bc.get(pid, set()))),
                                     new="+" + ",".join(sorted(new_bc))))
        if r.unit and cur["unit_code"] and r.unit != cur["unit_code"]:
            changes.append(ChangeOut(field="unit", old=cur["unit_code"], new=r.unit))

        kinds = {c.field for c in changes}
        if not kinds:
            cls = RowClass.UNCHANGED
        elif len(kinds) > 1:
            cls = RowClass.UPDATE_MULTIPLE
        else:
            cls = {"name": RowClass.UPDATE_NAME, "buy_price": RowClass.UPDATE_PRICE,
                   "sell_price": RowClass.UPDATE_PRICE, "stock": RowClass.UPDATE_STOCK,
                   "barcodes": RowClass.UPDATE_BARCODES, "unit": RowClass.UPDATE_UNIT}[kinds.pop()]
        out.append(PreviewRowOut(row_no=i, classification=cls, name=r.name,
                                 external_id=ext or None, product_id=uuid.UUID(pid),
                                 match_level=m.level.value, changes=changes,
                                 evidence=m.evidence))

    # ⚠️  MANBADA YO'Q — faqat RO'YXAT. Hech qachon o'chirmaydi va arxivlamaydi:
    #     sababi noma'lum (1С da nomi o'zgargan? eksport to'liq emas? tovar olib
    #     tashlangan?) va buni faqat do'kon egasi ayta oladi.
    missing = [ix.products[pid]["name"] for pid in ix.products
               if pid not in matched_ids and pid not in ix.deleted]
    return out, sorted(missing)


# ── IMPORT JOB — mavjud jadvallar ULANADI (parallel audit modeli QURILMAYDI) ──
def record_job(db: Session, company_id, actor_id, body, rows: list[PreviewRowOut],
               missing: list[str], status: ImportStatus) -> ImportJob:
    """Quruq yurish/commit natijasini `import_jobs` + `import_rows` ga yozadi."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.classification.value] = counts.get(r.classification.value, 0) + 1
    job = ImportJob(
        company_id=company_id, source=body.source_system,
        file_name=body.file_name, status=status,
        column_mapping={"mode": body.mode.value, "snapshot_id": body.snapshot_id,
                        "counts": counts, "missing_from_source": len(missing)},
        total_rows=len(rows),
        new_rows=counts.get(RowClass.NEW.value, 0),
        existing_rows=sum(v for k, v in counts.items()
                          if k.startswith("UPDATE") or k == RowClass.UNCHANGED.value),
        error_rows=counts.get(RowClass.INVALID.value, 0) + counts.get(RowClass.AMBIGUOUS.value, 0),
        created_by=actor_id, created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()
    for src, res in zip(body.rows, rows):
        db.add(ImportRow(
            job_id=job.id, row_no=res.row_no,
            raw=src.model_dump(mode="json"),
            parsed={"classification": res.classification.value,
                    "match_level": res.match_level,
                    "changes": [c.model_dump() for c in res.changes],
                    "evidence": res.evidence},
            status=res.classification.value,
            error="; ".join(res.problem) or None,
            product_id=res.product_id,
        ))
    return job


# ── INITIAL_CREATE — faqat YARATISH, yangilash yo'li YO'Q ───────────────────
def initial_create(db: Session, emp, body, branch) -> dict:
    """Bo'sh katalogga birinchi migratsiya. Faqat NEW qatorlar yoziladi.

    ⚠️  Bu funksiyada MAVJUD mahsulotni o'zgartiradigan birorta yo'l YO'Q.
        CUTOVER_REFRESH Phase 2 da alohida quriladi.
    """
    company_id = emp.company_id
    n_prod = db.query(Product).filter(
        Product.company_id == company_id, Product.deleted_at.is_(None)).count()
    if n_prod:
        raise ValueError(f"INITIAL_CREATE faqat BO'SH katalogga: hozir {n_prod} mahsulot bor")

    unit_map = {u.code: u.id for u in db.query(Unit).all()}
    if not unit_map:
        raise ValueError("o'lchov birliklari topilmadi")
    cats = {c.name.strip().lower(): c.id for c in db.query(Category).filter(
        Category.company_id == company_id, Category.deleted_at.is_(None)).all()}
    now = datetime.now(timezone.utc)
    seq = db.query(Product).filter(Product.company_id == company_id).count()
    made = 0
    n_bc = 0
    seen_ext: set[str] = set()
    seen_art: set[str] = set()
    seen_bc: set[str] = set()

    for i, r in enumerate(body.rows, start=1):
        ext = (r.external_id or "").strip()
        if not ext:
            raise ValueError(f"{i}-qator: INITIAL_CREATE uchun external_id MAJBURIY")
        if ext in seen_ext:
            raise ValueError(f"{i}-qator: external_id fayl ichida takrorlanadi: {ext}")
        seen_ext.add(ext)
        bad = _row_problems(r)
        if bad:
            raise ValueError(f"{i}-qator: " + "; ".join(bad))
        if r.unit and r.unit not in unit_map:
            raise ValueError(f"{i}-qator: noma'lum o'lchov birligi: {r.unit}")

        seq += 1
        art = (r.article or "").strip() or f"4-700000-160{200 + seq:03d}"
        if art in seen_art:
            raise ValueError(f"{i}-qator: artikul fayl ichida takrorlanadi: {art}")
        seen_art.add(art)

        p = Product(
            id=uuid.uuid4(), company_id=company_id,
            article_code=art, sku=str(10025 + seq), name=r.name.strip(),
            category_id=cats.get((r.category or "").strip().lower()),
            unit_id=unit_map[r.unit] if r.unit else unit_map.get("dona", next(iter(unit_map.values()))),
            base_buy_price=r.buy_price, base_sell_price=r.sell_price, tax_rate=0,
            is_weighted=r.is_weighted, plu_code=(r.plu_code or None),
            source_system=body.source_system, external_id=ext,   # TASHQI IDENTIFIKATSIYA
            created_by=emp.id,
        )
        db.add(p)
        made += 1
        # KO'P BARKOD: eski import bittasini olardi — bu yerda hammasi yoziladi.
        for raw in r.barcodes:
            bc = norm_barcode(raw)
            if not bc or bc in seen_bc:
                continue
            seen_bc.add(bc)
            db.add(ProductBarcode(product_id=p.id, company_id=company_id,
                                  barcode=bc, is_primary=(bc == norm_barcode(r.barcodes[0]))))
            n_bc += 1
        if branch is not None:
            db.add(Inventory(product_id=p.id, branch_id=branch.id, qty=r.stock,
                             min_qty=0, updated_at=now))
            if r.stock > 0:
                db.add(StockMovement(
                    product_id=p.id, branch_id=branch.id, type=MovementType.adjustment,
                    qty=r.stock, balance_after=r.stock, unit_cost=r.buy_price,
                    ref_type="cutover_initial", reason="1C INITIAL_CREATE",
                    employee_id=emp.id, created_at=now))
    return {"created": made, "barcodes": n_bc}
