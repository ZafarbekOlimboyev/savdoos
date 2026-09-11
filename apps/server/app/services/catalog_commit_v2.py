# -*- coding: utf-8 -*-
"""1С Cutover V2 — YOZUV yo'li (Phase 2).

Bu modul katalogga YOZADI. Uch qat'iy kafolat:

1. IDEMPOTENTLIK — `(company_id, source, snapshot_id)` DB darajasida NOYOB
   (`ux_import_jobs_snapshot`, faqat committing/committed). Ayni snapshot ikkinchi
   marta kelsa YANGI import boshlanmaydi: natija QAYTA O'QILADI (`replayed=true`).
   Ayni `snapshot_id` BOSHQA `content_sha256` bilan kelsa — manba o'zgargan,
   409 va NOL yozuv.

2. HECH QANDAY JIM YANGILANISH — har maydon uchun siyosat ANIQ:
   AUTO / CONFIRM_REQUIRED / NEVER_AUTO. Tasdiq talab qiladigan o'zgarish
   operator ro'yxatida bo'lmasa QO'LLANMAYDI va hisobotda ko'rinadi.

3. QOLDIQ FAQAT REKONSILIATSIYA ORQALI — `Inventory.qty` hech qachon audit'siz
   yozilmaydi. Har o'zgarish `StockMovement(adjustment, ref_type='1c_cutover')`
   izini qoldiradi; `client_uuid` (job + mahsulot) takror harakatni DB darajasida
   imkonsiz qiladi. Kassa/ledger/savdo/smenaga TEGILMAYDI.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import Product, ProductBarcode, Unit
from app.models.enums import ImportStatus, MovementType
from app.models.imports import ImportJob, ImportRow
from app.models.inventory import Inventory, StockMovement
from app.schemas.imports_v2 import DeletedMatchAction, ImportMode, RowClass
from app.services import catalog_import_v2 as civ2
from app.services.catalog_match import norm_barcode

REF_TYPE = "1c_cutover"

# ── MAYDON SIYOSATI — jim yangilanish YO'Q ──────────────────────────────────
#
# AUTO             — preview ko'rsatgan bo'lsa avtomatik qo'llanadi
# CONFIRM_REQUIRED — operator ANIQ ro'yxatga kiritmasa QO'LLANMAYDI
# NEVER_AUTO       — bu yo'l orqali UMUMAN qilinmaydi (alohida, ataylab amal kerak)
AUTO = {"buy_price", "sell_price", "barcodes_add", "external_identity"}
CONFIRM_REQUIRED = {"name", "unit", "is_weighted", "plu_code",
                    "barcode_remove", "reactivate", "category"}
NEVER_AUTO = {"barcode_reassign", "product_delete", "archive_missing", "merge_products"}


def _canon_row(r) -> dict:
    """Bitta qatorning KANONIK ko'rinishi — xesh uchun.

    Maqsad: MAZMUNAN bir xil qator DOIM bir xil xesh bersin, mazmun o'zgarsa
    xesh ham o'zgarsin.

      · nom       — chekka probellar olib tashlanadi, ichkilari SIQILADI.
                    Import baribir `strip()` qiladi, shu bois "  A  " va "A"
                    AYNI natija beradi — ular soxta SNAPSHOT_CONFLICT bermasin.
      · barkodlar — TARTIBLANADI va takrorlari olib tashlanadi. Ro'yxat tartibi
                    mazmun EMAS; qo'llash yo'li ham tartiblangan holda ishlaydi,
                    shu bois xesh va xatti-harakat IZCHIL.
      · sonlar    — float ga keltiriladi (10, 10.0, 10.00 -> bir xil).
      · bo'shlar  — None va "" farqlanmaydi.
    """
    d = r.model_dump(mode="json")
    d["name"] = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()
    d["barcodes"] = sorted({str(b).strip() for b in (d.get("barcodes") or []) if str(b).strip()})
    for k in ("buy_price", "sell_price", "stock"):
        d[k] = float(d.get(k) or 0)
    for k in ("external_id", "article", "unit", "plu_code", "category"):
        v = d.get(k)
        d[k] = (str(v).strip() or None) if v is not None else None
    return d


def canonical_hash(rows) -> str:
    """Snapshot mazmunining kanonik sha256'si.

    ⚠️  MULTISET-XAVFSIZ: kanonik satrlar TO'PLAMGA emas, TARTIBLANGAN RO'YXATGA
        yig'iladi va qatorlar SONI ham xeshga kiradi. Shu bois [X] va [X, X]
        TURLICHA xesh beradi — takror qatorning KO'PLIGI yo'qolmaydi. Tartibning
        o'zi esa xeshga ta'sir qilmaydi (ayni fayl boshqa tartibda kelsa soxta
        ziddiyat bo'lmaydi).
    """
    canon = sorted(json.dumps(_canon_row(r), sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False) for r in rows)
    h = hashlib.sha256()
    h.update(str(len(canon)).encode())      # qatorlar SONI ham izda
    h.update(b"\x00")
    for line in canon:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


class SnapshotConflict(Exception):
    """Ayni snapshot_id, BOSHQA mazmun — manba preview'dan keyin o'zgargan."""


class ImportInProgress(Exception):
    """Boshqa jarayon shu snapshot'ni allaqachon commit qilmoqda."""


class Replayed(Exception):
    """Allaqachon COMMITTED — natija qayta o'qiladi, yangi yozuv yo'q."""

    def __init__(self, job: ImportJob):
        self.job = job


def _job_result(job: ImportJob) -> dict:
    cm = job.column_mapping or {}
    return {"job_id": str(job.id), "status": job.status.value,
            "snapshot_id": job.snapshot_id, "content_sha256": job.content_sha256,
            "mode": job.mode, "counts": cm.get("apply_counts", {}),
            "created": cm.get("created", 0), "updated": cm.get("updated", 0),
            "barcodes_added": cm.get("barcodes_added", 0),
            "stock_adjusted": cm.get("stock_adjusted", 0),
            "confirmation_required": cm.get("confirmation_required", 0),
            "skipped": cm.get("skipped", 0),
            "applied_rows": job.applied_rows or 0, "total_rows": job.total_rows,
            "replayed": False}


def claim_commit_job(db: Session, company_id, actor_id, body, content_sha: str,
                     preview_job: ImportJob | None) -> ImportJob:
    """Commit huquqini ATOMAR egallaydi.

    Poygada faqat BITTASI g'olib chiqadi: ikkinchisi `ux_import_jobs_snapshot`
    tufayli IntegrityError oladi va mavjud ishni KUZATADI (jim ikkinchi import
    BOSHLANMAYDI).
    """
    snap = (body.snapshot_id or "").strip()
    if not snap:
        raise ValueError("snapshot_id MAJBURIY (idempotentlik kaliti)")

    existing = (db.query(ImportJob)
                .filter(ImportJob.company_id == company_id,
                        ImportJob.source == body.source_system,
                        ImportJob.snapshot_id == snap,
                        ImportJob.status.in_([ImportStatus.committing,
                                              ImportStatus.committed,
                                              ImportStatus.failed]))
                .order_by(ImportJob.created_at.desc()).first())
    if existing is not None:
        if existing.content_sha256 != content_sha:
            raise SnapshotConflict(
                f"snapshot_id '{snap}' allaqachon boshqa mazmun bilan ishlatilgan "
                f"(kutilgan {existing.content_sha256[:12]}…, kelgan {content_sha[:12]}…)")
        if existing.status is ImportStatus.committed:
            raise Replayed(existing)
        if existing.status is ImportStatus.committing:
            raise ImportInProgress(f"shu snapshot commit qilinmoqda (job {existing.id})")
        # FAILED -> DAVOM ETTIRAMIZ (yangi ish ochmaymiz): qaysi qatorlar
        # qo'llangani `import_rows` da yozilgan, qolgani ustidan davom etiladi.
        existing.status = ImportStatus.committing
        existing.error = None
        db.flush()
        return existing

    job = ImportJob(
        company_id=company_id, source=body.source_system, file_name=body.file_name,
        status=ImportStatus.committing, snapshot_id=snap, content_sha256=content_sha,
        mode=body.mode.value, column_mapping={"mode": body.mode.value,
                                              "preview_job_id": str(preview_job.id) if preview_job else None},
        total_rows=len(body.rows), created_by=actor_id,
        created_at=datetime.now(timezone.utc), applied_rows=0)
    db.add(job)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise ImportInProgress("parallel commit — boshqa jarayon egalladi") from e
    return job


def _applied_rows(db: Session, job_id) -> dict[int, str]:
    """Qaysi qatorlar ALLAQACHON qo'llangan (qayta boshlashda o'tkazib yuboriladi)."""
    return {r.row_no: r.status for r in db.query(ImportRow).filter(
        ImportRow.job_id == job_id, ImportRow.status.like("APPLIED_%")).all()}


def _reconcile_stock(db: Session, job: ImportJob, p: Product, branch, source_qty: float,
                     emp_id, now) -> float:
    """Qoldiqni AUDIT bilan moslashtiradi. Qaytaradi: delta (0 bo'lsa harakat YO'Q).

    ⚠️  `Inventory.qty` to'g'ridan-to'g'ri YOZILMAYDI: har o'zgarish uchun
        `StockMovement` yoziladi. `client_uuid` = uuid5(job_id, product_id) —
        shu bois AYNI ish qayta yurgizilsa IKKINCHI harakat DB darajasida
        mumkin emas va qoldiq ikki marta siljimaydi.
    """
    if branch is None:
        return 0.0
    key = uuid.uuid5(uuid.UUID(str(job.id)), str(p.id))
    # Qator QULFI — parallel sotuv bilan yo'qotish bo'lmasin.
    inv = (db.query(Inventory)
           .filter(Inventory.product_id == p.id, Inventory.branch_id == branch.id)
           .with_for_update().first())
    if inv is None:
        inv = Inventory(product_id=p.id, branch_id=branch.id, qty=0, min_qty=0, updated_at=now)
        db.add(inv)
        db.flush()
        inv = (db.query(Inventory)
               .filter(Inventory.product_id == p.id, Inventory.branch_id == branch.id)
               .with_for_update().first())
    old = float(inv.qty or 0)
    delta = round(float(source_qty) - old, 3)
    if abs(delta) < 1e-9:
        return 0.0            # O'ZGARMAGAN -> HARAKAT YO'Q
    dup = db.query(StockMovement).filter(StockMovement.client_uuid == key).first()
    if dup is not None:
        return 0.0            # qayta yurgizish -> IKKINCHI harakat YO'Q
    inv.qty = source_qty
    inv.updated_at = now
    db.add(StockMovement(
        product_id=p.id, branch_id=branch.id, type=MovementType.adjustment,
        qty=delta, balance_after=source_qty, ref_type=REF_TYPE,
        ref_id=job.id, reason="1C cutover reconciliation",
        employee_id=emp_id, client_uuid=key, created_at=now))
    return delta


def _apply_row(db: Session, job, emp, branch, src, res, ix, confirm: set[str],
               deleted_actions: dict, now) -> tuple[str, dict]:
    """Bitta qatorni QO'LLAYDI. Qaytaradi: (import_rows.status, hisob)."""
    acc = {"created": 0, "updated": 0, "barcodes_added": 0, "stock_adjusted": 0,
           "confirmation_required": 0, "skipped": 0}
    cls = res.classification

    if cls in (RowClass.INVALID, RowClass.AMBIGUOUS):
        acc["skipped"] += 1
        return f"SKIPPED_{cls.value}", acc

    if cls is RowClass.DELETED_MATCH:
        act = deleted_actions.get(src.external_id or "", DeletedMatchAction.KEEP_DELETED)
        if act is not DeletedMatchAction.REACTIVATE_EXISTING:
            acc["skipped"] += 1
            return "SKIPPED_DELETED_MATCH", acc        # STANDART: tegilmaydi
        p = db.get(Product, res.product_id)
        # AYNI Product.id va AYNI tashqi identifikatsiya saqlanadi — ikkinchi
        # mahsulot YARATILMAYDI, tarixiy identifikatsiya bo'linmaydi.
        p.deleted_at = None
        p.is_active = True
        acc["updated"] += 1
        return "APPLIED_REACTIVATED", acc

    if cls is RowClass.NEW:
        seq = db.query(func.count(Product.id)).filter(
            Product.company_id == emp.company_id).scalar() or 0
        unit_map = {u.code: u.id for u in db.query(Unit).all()}
        p = Product(
            id=uuid.uuid4(), company_id=emp.company_id,
            article_code=(src.article or "").strip() or f"4-700000-160{200 + seq + 1:03d}",
            sku=str(10025 + seq + 1), name=src.name.strip(),
            unit_id=unit_map.get(src.unit or "dona", next(iter(unit_map.values()))),
            base_buy_price=src.buy_price, base_sell_price=src.sell_price, tax_rate=0,
            is_weighted=src.is_weighted, plu_code=(src.plu_code or None),
            source_system=job.source, external_id=(src.external_id or "").strip() or None,
            created_by=emp.id)
        db.add(p)
        db.flush()
        acc["created"] += 1
        for raw in sorted(set(src.barcodes)):
            bc = norm_barcode(raw)
            if bc and not db.query(ProductBarcode).filter(
                    ProductBarcode.company_id == emp.company_id,
                    ProductBarcode.barcode == bc).first():
                db.add(ProductBarcode(product_id=p.id, company_id=emp.company_id, barcode=bc))
                acc["barcodes_added"] += 1
        if _reconcile_stock(db, job, p, branch, src.stock, emp.id, now):
            acc["stock_adjusted"] += 1
        return "APPLIED_NEW", acc

    # ── MAVJUD mahsulot: maydon-ba-maydon SIYOSAT ───────────────────────
    p = db.get(Product, res.product_id)
    if p is None:
        acc["skipped"] += 1
        return "SKIPPED_GONE", acc
    touched = False

    # Tashqi identifikatsiyani BIRIKTIRISH — dalil noaniq bo'lmaganda (preview
    # AMBIGUOUS bermagan), bu AUTO: mahsulotning kelajakdagi moslashtirilishini
    # nomdan mustaqil qiladi.
    ext = (src.external_id or "").strip()
    if ext and not p.external_id:
        p.source_system, p.external_id = job.source, ext
        touched = True

    for c in res.changes:
        f = c.field
        if f in ("buy_price", "sell_price"):            # AUTO
            setattr(p, "base_buy_price" if f == "buy_price" else "base_sell_price",
                    src.buy_price if f == "buy_price" else src.sell_price)
            touched = True
        elif f == "barcodes":                            # AUTO (faqat QO'SHISH)
            for raw in sorted(set(src.barcodes)):
                bc = norm_barcode(raw)
                if bc and not db.query(ProductBarcode).filter(
                        ProductBarcode.company_id == emp.company_id,
                        ProductBarcode.barcode == bc).first():
                    db.add(ProductBarcode(product_id=p.id, company_id=emp.company_id,
                                          barcode=bc))
                    acc["barcodes_added"] += 1
        elif f in CONFIRM_REQUIRED:                      # TASDIQ kerak
            if f not in confirm:
                acc["confirmation_required"] += 1
                continue
            if f == "name":
                p.name = src.name.strip()
            elif f == "unit":
                um = {u.code: u.id for u in db.query(Unit).all()}
                if src.unit in um:
                    p.unit_id = um[src.unit]
            touched = True
        elif f == "stock":
            if _reconcile_stock(db, job, p, branch, src.stock, emp.id, now):
                acc["stock_adjusted"] += 1
    if touched:
        acc["updated"] += 1
    return ("APPLIED_UPDATE" if touched or acc["barcodes_added"] or acc["stock_adjusted"]
            else "APPLIED_UNCHANGED"), acc


def claim(db: Session, emp, body, preview_job: ImportJob | None) -> ImportJob:
    """1-BOSQICH: ishni egallaydi. Chaqiruvchi buni ALOHIDA commit qiladi.

    ⚠️  NEGA ALOHIDA TRANZAKSIYA: qatorlarni qo'llash yiqilsa `rollback` butun
        tranzaksiyani qaytaradi. Ish yozuvi HAM o'sha tranzaksiyada yaratilgan
        bo'lsa, u ham yo'qoladi — ya'ni muvaffaqiyatsiz import HECH QANDAY IZ
        qoldirmasdi va operator nima bo'lganini bilmasdi. Ish AVVAL yozib
        qo'yiladi (COMMITTING), so'ng qatorlar alohida tranzaksiyada qo'llanadi.
    """
    content_sha = canonical_hash(body.rows)
    if preview_job is not None and preview_job.content_sha256 != content_sha:
        raise SnapshotConflict(
            "manba preview'dan KEYIN o'zgargan — yangi preview talab qilinadi "
            f"(preview {preview_job.content_sha256[:12]}…, hozir {content_sha[:12]}…)")
    return claim_commit_job(db, emp.company_id, emp.id, body, content_sha, preview_job)


def apply_job(db: Session, emp, body, valid_units: set[str], confirm_fields: set[str],
              job: ImportJob) -> dict:
    """2-BOSQICH: qatorlarni QO'LLAYDI — BITTA tranzaksiyada (MODEL A).

    Chaqiruvchi tranzaksiyani boshqaradi. Yiqilsa `rollback` BARCHA qatorlarni
    qaytaradi (qisman import BO'LMAYDI) va ish FAILED deb belgilanadi; ayni
    snapshot bilan qayta urinish NOLDAN boshlanadi va dublikat yaratmaydi
    (tashqi identifikatsiya + harakat kaliti buni kafolatlaydi).
    """
    done = _applied_rows(db, job.id)

    from app.core.deps import actor_branch
    from app.models.org import Branch
    branch = (actor_branch(emp, db)
              or db.query(Branch).filter(Branch.company_id == emp.company_id,
                                         Branch.deleted_at.is_(None)).first())
    now = datetime.now(timezone.utc)
    rows, _missing = civ2.preview(db, emp.company_id, body, valid_units)
    total = {"created": 0, "updated": 0, "barcodes_added": 0, "stock_adjusted": 0,
             "confirmation_required": 0, "skipped": 0}
    by_class: dict[str, int] = {}
    ix = None
    applied = 0

    for src, res in zip(body.rows, rows):
        by_class[res.classification.value] = by_class.get(res.classification.value, 0) + 1
        if res.row_no in done:
            applied += 1
            continue                      # QAYTA BOSHLASH: bu qator allaqachon qo'llangan
        status, acc = _apply_row(db, job, emp, branch, src, res, ix,
                                 confirm_fields, body.deleted_match_actions, now)
        for k, v in acc.items():
            total[k] += v
        db.add(ImportRow(job_id=job.id, row_no=res.row_no,
                         raw=src.model_dump(mode="json"),
                         parsed={"classification": res.classification.value,
                                 "match_level": res.match_level,
                                 "changes": [c.model_dump() for c in res.changes]},
                         status=status, error="; ".join(res.problem) or None,
                         product_id=res.product_id))
        if status.startswith("APPLIED_"):
            applied += 1

    job.applied_rows = applied
    job.new_rows = total["created"]
    job.existing_rows = total["updated"]
    job.error_rows = total["skipped"]
    job.column_mapping = {**(job.column_mapping or {}), "apply_counts": by_class, **total}
    job.status = ImportStatus.committed
    job.committed_at = now
    out = _job_result(job)
    out.update(total)
    out["replayed"] = False
    return out
