# -*- coding: utf-8 -*-
"""1С Cutover V2 — API (Phase 1: quruq yurish, INITIAL_CREATE, reset dry-run).

Eski `/products/import/*` shartnomasi TEGILMAGAN — Manager UI unga tayanadi.
Bu yo'llar YONIDA turadi va `/catalog/v2/...` prefiksida.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.admin import require_vendor
from app.core.deps import require
from app.db.session import get_db
from app.models.catalog import Unit
from app.models.auth import Employee
from app.models.enums import ImportStatus
from app.schemas.imports_v2 import ImportBodyV2, ImportMode, PreviewOut
from app.models.imports import ImportJob, ImportRow
from app.services import catalog_import_v2 as civ2
from app.services import catalog_commit_v2 as ccv2
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
    job.snapshot_id = (body.snapshot_id or "").strip() or None
    job.content_sha256 = ccv2.canonical_hash(body.rows)
    job.mode = body.mode.value
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


@router.post("/catalog/v2/commit")
def catalog_commit(
    body: ImportBodyV2,
    confirm: str = "",
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    """CUTOVER_REFRESH / INITIAL_CREATE ni QO'LLAYDI (yagona yozuv yo'li).

    `confirm` — vergul bilan ajratilgan maydonlar (`name,unit,...`). Tasdiq
    talab qiladigan o'zgarish shu ro'yxatda bo'lmasa QO'LLANMAYDI.

    ⚠️  DARVOZALAR:
        · `snapshot_id` MAJBURIY — idempotentlik kaliti.
        · `job_id` berilsa, u PREVIEW ishi bo'lishi va xesh MOS kelishi shart.
        · Katalog LIVE bo'lsa CUTOVER_REFRESH va INITIAL_CREATE RAD ETILADI —
          eskirgan 1С snapshot'i jonli qoldiqni bosib keta olmaydi.
    """
    if body.mode is ImportMode.NORMAL_OPERATION:
        raise HTTPException(400, "NORMAL_OPERATION bu yo'l orqali yozmaydi "
                                 "(faqat preview va yangi mahsulot taklifi)")
    if civ2.is_live(db, emp.company_id):
        raise HTTPException(409, "Katalog cutover'i YOPILGAN (LIVE) — "
                                 "1С snapshot'i katalogni o'zgartira olmaydi")
    preview_job = None
    if body.job_id is not None:
        preview_job = db.get(ImportJob, body.job_id)
        if preview_job is None or preview_job.company_id != emp.company_id:
            raise HTTPException(404, "Preview ishi topilmadi")
        if preview_job.status is not ImportStatus.validated:
            raise HTTPException(400, "Ko'rsatilgan ish PREVIEW emas")
    fields = {f.strip() for f in confirm.split(",") if f.strip()}
    bad = fields & ccv2.NEVER_AUTO
    if bad:
        raise HTTPException(400, f"Bu maydonlar bu yo'l orqali o'zgartirilmaydi: {sorted(bad)}")
    # ── 1-BOSQICH: ishni egallaymiz va DARHOL commit qilamiz ────────────
    #    Shunda qatorlar qo'llash yiqilsa ham ish yozuvi (FAILED) QOLADI.
    try:
        job = ccv2.claim(db, emp, body, preview_job)
        db.commit()
    except ccv2.Replayed as r:
        db.rollback()
        out = ccv2._job_result(r.job)
        out["replayed"] = True
        return out
    except ccv2.SnapshotConflict as e:
        db.rollback()
        raise HTTPException(409, f"SNAPSHOT_CONFLICT: {e}") from e
    except ccv2.ImportInProgress as e:
        db.rollback()
        raise HTTPException(409, f"IMPORT_IN_PROGRESS: {e}") from e
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e

    # ── 2-BOSQICH: qatorlar — BITTA tranzaksiya (hammasi yoki hech narsa) ──
    try:
        res = ccv2.apply_job(db, emp, body, _units(db), fields, job)
    except ValueError as e:
        db.rollback()
        _mark_failed(db, emp.company_id, body, str(e))
        raise HTTPException(400, str(e)) from e
    except Exception as e:      # noqa: BLE001
        db.rollback()
        _mark_failed(db, emp.company_id, body, str(e))
        raise HTTPException(500, f"Import yiqildi — qisman yozuv YO'Q, "
                                 f"qayta urinish XAVFSIZ: {e}") from e
    # Katalog sozlamasi manbani QAYD etadi (LIVE qilmaydi — u alohida amal).
    civ2.set_catalog_settings(db, emp.company_id, source_system=body.source_system,
                              last_import_job_id=res["job_id"])
    audit_log(db, emp.id, "import", "catalog", None,
              after={k: res[k] for k in ("job_id", "snapshot_id", "created", "updated",
                                         "barcodes_added", "stock_adjusted")})
    db.commit()
    return res


def _mark_failed(db: Session, company_id, body, err: str) -> None:
    """Yiqilgan ishni FAILED deb belgilaydi — keyingi urinish DAVOM ettiradi."""
    try:
        j = (db.query(ImportJob)
             .filter(ImportJob.company_id == company_id,
                     ImportJob.snapshot_id == (body.snapshot_id or "").strip(),
                     ImportJob.status == ImportStatus.committing).first())
        if j is not None:
            j.status = ImportStatus.failed
            j.error = err[:500]
            db.commit()
    except Exception:           # noqa: BLE001
        db.rollback()


@router.get("/catalog/v2/jobs")
def catalog_jobs(
    limit: int = 20,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    """Import ishlari tarixi — holat, snapshot, xesh, sanoqlar."""
    q = (db.query(ImportJob).filter(ImportJob.company_id == emp.company_id)
         .order_by(ImportJob.created_at.desc()).limit(min(limit, 100)).all())
    return [{"id": str(j.id), "status": j.status.value, "mode": j.mode,
             "snapshot_id": j.snapshot_id, "content_sha256": j.content_sha256,
             "total_rows": j.total_rows, "applied_rows": j.applied_rows or 0,
             "created_at": j.created_at.isoformat() if j.created_at else None,
             "committed_at": j.committed_at.isoformat() if j.committed_at else None,
             "error": j.error} for j in q]


@router.get("/catalog/v2/settings")
def catalog_settings(
    emp: Employee = Depends(require("sozlamalar.view")),
    db: Session = Depends(get_db),
):
    """`settings.catalog` — `settings.cash` dan MUSTAQIL."""
    return civ2.get_catalog_settings(db, emp.company_id)


@router.post("/catalog/v2/cutover-complete")
def catalog_cutover_complete(
    import_job_id: uuid.UUID,
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    """Katalog cutover'ini AYNAN ko'rsatilgan import ishiga bog'lab YOPADI.

    `import_job_id` MAJBURIY: "oxirgi ish" deb taxmin qilish xavfli — operator
    yangi preview qilib, eskisini yopib qo'yishi mumkin edi. Yopilgan holat
    qaysi SNAPSHOT va qaysi MAZMUN xeshi bilan tasdiqlanganini yozib qoldiradi.
    """
    from datetime import datetime, timezone
    cur = civ2.get_catalog_settings(db, emp.company_id)
    if cur.get("cutover_at"):
        raise HTTPException(409, "Katalog cutover'i allaqachon yopilgan")

    job = db.get(ImportJob, import_job_id)
    if job is None or job.company_id != emp.company_id:
        raise HTTPException(404, "Import ishi topilmadi")
    if job.status is not ImportStatus.committed:
        raise HTTPException(409, f"Ish COMMITTED emas (holat: {job.status.value})")
    if job.mode not in (ImportMode.CUTOVER_REFRESH.value, ImportMode.INITIAL_CREATE.value):
        raise HTTPException(409, f"Ish rejimi yaroqsiz: {job.mode}")
    src = cur.get("source_system")
    if src and job.source != src:
        raise HTTPException(409, f"Manba mos emas: katalog '{src}', ish '{job.source}'")
    if not job.snapshot_id or not job.content_sha256:
        raise HTTPException(409, "Ishda snapshot_id/content_sha256 yo'q — yopib bo'lmaydi")

    # ── KEYINGI ish bu ishni ESKIRTIRGANMI ──────────────────────────────
    newer = (db.query(ImportJob)
             .filter(ImportJob.company_id == emp.company_id,
                     ImportJob.created_at > job.created_at,
                     ImportJob.status.in_([ImportStatus.validated, ImportStatus.committing,
                                           ImportStatus.committed, ImportStatus.failed]))
             .order_by(ImportJob.created_at.desc()).all())
    blocking = [j for j in newer if j.snapshot_id and j.snapshot_id != job.snapshot_id]
    if blocking:
        b = blocking[0]
        raise HTTPException(409,
                            f"KEYINGI ish mavjud ({b.status.value}, snapshot '{b.snapshot_id}') — "
                            f"eski snapshot bilan yopib bo'lmaydi")
    if any(j.status in (ImportStatus.committing, ImportStatus.failed) for j in newer):
        raise HTTPException(409, "Tugallanmagan (COMMITTING/FAILED) ish bor")

    bad = (db.query(ImportRow)
           .filter(ImportRow.job_id == job.id,
                   ImportRow.status.in_(["SKIPPED_AMBIGUOUS", "SKIPPED_INVALID"])).count())
    if bad:
        raise HTTPException(409, f"Ishda hal qilinmagan {bad} qator bor (AMBIGUOUS/INVALID)")
    pending = (job.column_mapping or {}).get("confirmation_required", 0)
    if pending:
        raise HTTPException(409, f"Tasdiq kutayotgan {pending} o'zgarish bor")

    val = civ2.set_catalog_settings(
        db, emp.company_id, mode="LIVE", last_import_job_id=str(job.id),
        last_snapshot_id=job.snapshot_id, last_content_sha256=job.content_sha256,
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
        "reset_token": p.token,          # BAJARISH uchun SHU token kerak
        "fingerprint": p.fingerprint,
        "token_ttl_seconds": catalog_reset.TOKEN_TTL_SECONDS,
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


@router.post("/catalog/v2/reset/execute")
def catalog_reset_execute(
    company_id: uuid.UUID,
    reset_token: str,
    confirm_code: str,
    _vendor: bool = Depends(require_vendor),
    db: Session = Depends(get_db),
):
    """PRE_LIVE tenantning DEMO katalogini o'chiradi. BITTA tranzaksiya.

    ⚠️  VENDOR HUQUQI TALAB QILINADI (`require_vendor`): imzolangan vendor
        sessiyasi + ruxsatli IP + rate-limit; production'da xom kalit QABUL
        QILINMAYDI (sessiya /admin/login orqali OTP bilan olinadi). Do'kon
        xodimi — hatto `sozlamalar.edit` huquqi bilan ham — BU AMALNI
        BAJARA OLMAYDI: katalogni yo'q qilish tenant ichidagi amal emas.

    ⚠️  PRODUCTION'DA YOPIQ (`catalog_reset.execution_allowed()`).

    Darvozalar (hammasi FAIL-CLOSED):
      · `reset_token` — dry-run bergan IMZOLANGAN barmoq izi (15 daqiqa)
      · token ichidagi BARCHA sanoqlar tranzaksiya ichida QAYTA o'qiladi va
        bittasi ham farq qilsa 409 (faqat `expect_products` ga tayanilmaydi)
      · katalog LIVE bo'lmasligi
      · birorta biznes hujjati (savdo/smena/kirim/qaytarish/kassa) bo'lmasligi
      · `products` ga NOMA'LUM FK bo'lmasligi
      · `confirm_code` do'kon kodiga mos bo'lishi
    """
    if not catalog_reset.execution_allowed():
        raise HTTPException(403, "Katalog resetini bajarish bu muhitda YOPIQ")
    from app.models.org import Company
    comp = db.get(Company, company_id)
    if comp is None or comp.deleted_at is not None:
        raise HTTPException(404, "Do'kon topilmadi")
    if civ2.is_live(db, company_id):
        raise HTTPException(409, "Katalog LIVE — reset rad etildi")
    if (confirm_code or "").strip() != (comp.code or ""):
        raise HTTPException(400, "confirm_code do'kon kodiga mos kelmadi")
    # Holat TRANZAKSIYA ICHIDA qayta o'qiladi va token bilan solishtiriladi.
    try:
        fp = catalog_reset.verify_token(db, company_id, reset_token)
    except ValueError as e:
        raise HTTPException(409, f"RESET_TOKEN_STALE: {e}") from e
    before = dict(catalog_reset.plan(db, company_id).delete_counts)
    try:
        deleted = catalog_reset.execute(db, company_id)
    except (PermissionError, ValueError) as e:
        db.rollback()
        raise HTTPException(409, str(e)) from e
    except Exception as e:      # noqa: BLE001
        db.rollback()
        raise HTTPException(500, f"Reset yiqildi — tranzaksiya QAYTARILDI: {e}") from e
    audit_log(db, None, "reset", "catalog", company_id,
              before=before, after={"deleted": deleted, "nonce": fp.get("nonce")})
    db.commit()
    return {"deleted": deleted, "before": before, "nonce": fp.get("nonce")}
