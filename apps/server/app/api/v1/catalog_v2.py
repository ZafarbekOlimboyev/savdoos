# -*- coding: utf-8 -*-
"""1С Cutover V2 — API (Phase 1: quruq yurish, INITIAL_CREATE, reset dry-run).

Eski `/products/import/*` shartnomasi TEGILMAGAN — Manager UI unga tayanadi.
Bu yo'llar YONIDA turadi va `/catalog/v2/...` prefiksida.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models.catalog import Unit
from app.models.auth import Employee
from app.models.enums import ImportStatus
from app.schemas.imports_v2 import ImportBodyV2, ImportMode, PreviewOut
from app.services import catalog_import_v2 as civ2
from app.services import catalog_reset
from app.services.audit import log as audit_log

router = APIRouter(tags=["catalog-v2"])


def _units(db: Session) -> set[str]:
    return {u.code for u in db.query(Unit).all()}


@router.post("/catalog/v2/preview", response_model=PreviewOut)
def catalog_preview(
    body: ImportBodyV2,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    """QURUQ YURISH — har qatorni tasniflaydi, `eski -> yangi` ni ko'rsatadi.

    ⚠️  KATALOGGA HECH NARSA YOZILMAYDI: Product, Inventory, StockMovement,
        ProductBarcode va Setting TEGILMAYDI. Yagona yozuv — `import_jobs` /
        `import_rows` AUDIT yozuvi (bu quruq yurishning o'zi qayd etilishi kerak;
        u katalog holatiga ta'sir qilmaydi).
    """
    rows, missing = civ2.preview(db, emp.company_id, body, _units(db))
    job = civ2.record_job(db, emp.company_id, emp.id, body, rows, missing,
                          ImportStatus.validated)
    db.commit()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.classification.value] = counts.get(r.classification.value, 0) + 1
    if missing:
        counts["MISSING_FROM_SOURCE"] = len(missing)
    return PreviewOut(job_id=job.id, mode=body.mode, source_system=body.source_system,
                      total=len(rows), counts=counts, rows=rows,
                      missing_from_source=missing, wrote_nothing=True)


@router.post("/catalog/v2/initial-create")
def catalog_initial_create(
    body: ImportBodyV2,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    """INITIAL_CREATE — BO'SH katalogga birinchi migratsiya.

    Mavjud mahsulotni o'zgartiradigan yo'l bu endpointда UMUMAN YO'Q.
    """
    if body.mode is not ImportMode.INITIAL_CREATE:
        raise HTTPException(400, "Bu endpoint faqat INITIAL_CREATE rejimida ishlaydi")
    if civ2.is_live(db, emp.company_id):
        # Cutover yopilgan — eskirgan 1С snapshot'i katalogni qayta qura olmaydi.
        raise HTTPException(409, "Katalog cutover'i YOPILGAN — INITIAL_CREATE rad etildi")
    from app.core.deps import actor_branch
    from app.models.org import Branch
    branch = (actor_branch(emp, db)
              or db.query(Branch).filter(Branch.company_id == emp.company_id,
                                         Branch.deleted_at.is_(None)).first())
    try:
        res = civ2.initial_create(db, emp, body, branch)
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    civ2.set_catalog_settings(db, emp.company_id, source_system=body.source_system)
    audit_log(db, emp.id, "import", "catalog", None,
              after={"mode": body.mode.value, "created": res["created"],
                     "barcodes": res["barcodes"], "snapshot_id": body.snapshot_id})
    db.commit()
    return res


@router.get("/catalog/v2/settings")
def catalog_settings(
    emp: Employee = Depends(require("sozlamalar.view")),
    db: Session = Depends(get_db),
):
    """`settings.catalog` — `settings.cash` dan MUSTAQIL."""
    return civ2.get_catalog_settings(db, emp.company_id)


@router.post("/catalog/v2/cutover-complete")
def catalog_cutover_complete(
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    """Katalog cutover'ini YOPADI — SavdoOS inventarning haqiqat manbaiga aylanadi.

    Shundan keyin CUTOVER_REFRESH abadiy rad etiladi.
    """
    from datetime import datetime, timezone
    cur = civ2.get_catalog_settings(db, emp.company_id)
    if cur.get("cutover_at"):
        raise HTTPException(409, "Katalog cutover'i allaqachon yopilgan")
    val = civ2.set_catalog_settings(
        db, emp.company_id, mode="LIVE",
        cutover_at=datetime.now(timezone.utc).isoformat())
    audit_log(db, emp.id, "update", "catalog_cutover", None, after=val)
    db.commit()
    return val


# ── KATALOG RESETI — Phase 1 da FAQAT DRY-RUN ───────────────────────────────
@router.post("/catalog/v2/reset/dry-run")
def catalog_reset_dry_run(
    company_id: uuid.UUID | None = None,
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    """Reset REJASI — aniq qator sonlari bilan. HECH NARSA O'CHIRILMAYDI.

    `company_id` berilmasa — chaqiruvchining o'z do'koni. Boshqa do'kon
    so'ralsa rad etiladi (tenant izolyatsiyasi).
    """
    target = company_id or emp.company_id
    if str(target) != str(emp.company_id):
        raise HTTPException(403, "Boshqa do'kon katalogiga ruxsat yo'q")
    p = catalog_reset.plan(db, target)
    return {
        "eligible": p.eligible,
        "blockers": p.blockers,
        "would_delete": p.delete_counts,
        "would_preserve": p.preserve_counts,
        "categories": p.categories,
        "brands": p.brands,
        "notes": p.notes,
        "execution_enabled": catalog_reset.execution_allowed(),
        "wrote_nothing": True,
    }
