# -*- coding: utf-8 -*-
"""Chop etish JURNALI — asl chek / nusxa hodisalari (Phase 5F).

⚠️  FAQAT JURNAL. Bu modul `print_jobs` dan boshqa jadvalga YOZMAYDI: sotuv,
    qaytarish, qoldiq, kassa, smena — hech biriga tegmaydi. Chop etish sotuv
    commit'idan KEYIN, alohida so'rovda yuz beradi; printer xatosi sotuvni bekor
    qilmaydi va jurnal yozuvi yo'qolsa ham hujjat o'zgarmaydi.
⚠️  `id` — MIJOZ uuid'i (POS offline chop etib, hisobotni keyin yuboradi). Ayni `id`
    qayta kelsa — bu takror, holat O'TISHI sifatida qo'llanadi (yangi qator emas).
⚠️  ASL CHEK BITTA. `ux_print_jobs_original` — ikki oyna ayni hujjatni bir vaqtda
    «asl» deb yozsa, ikkinchisi 409 oladi va NUSXA chop etishi kerak.
⚠️  NUSXA RAQAMI qulf ostida: Postgres'da hujjat bo'yicha `pg_advisory_xact_lock` —
    ikki parallel nusxa AYNI raqamni olmaydi (SQLite yozuvchilarni baribir ketma-ket qo'yadi).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.error_codes import HEADER
from app.services.receipt import errors as E
from app.services.receipt.access import readable_doc
from app.services.receipt.settings import clean_line, parse_uuid

DOC_TYPES = ("SALE", "RETURN")
COPIES = ("ORIGINAL", "REPRINT")
STATUSES = ("PENDING", "PRINTED", "FAILED")
MAX_ATTEMPTS = 1000
_TRANSPORT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,24}$")
# `pg_advisory_xact_lock(int4, int4)` nomlar fazosi — boshqa advisory qulflar bilan to'qnashmasin.
_LOCK_NS = 0x5052_4A42          # "PRJB"

_PATCH_FIELDS = ("status", "error", "attempts", "printer", "transport")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# ── KIRISHNI TEKSHIRISH (hammasi 400 PRINT_JOB_INVALID) ─────────────────────
def _enum(v, allowed):
    if isinstance(v, str) and v in allowed:
        return v
    raise E.print_job_invalid()


def _uuid(v):
    u = parse_uuid(v)
    if u is None:
        raise E.print_job_invalid()
    return u


def _optional_fields(body: dict, out: dict) -> dict:
    if "status" in body:
        out["status"] = _enum(body["status"], STATUSES)
    if "attempts" in body:
        a = body["attempts"]
        if type(a) is not int or not (0 <= a <= MAX_ATTEMPTS):
            raise E.print_job_invalid()
        out["attempts"] = a
    if "error" in body:
        v = body["error"]
        if v is not None and not isinstance(v, str):
            raise E.print_job_invalid()
        out["error"] = clean_line(v, 300) if v is not None else None
    if "printer" in body:
        v = body["printer"]
        if v is not None and not isinstance(v, str):
            raise E.print_job_invalid()
        out["printer"] = clean_line(v, 120) if v is not None else None
    if "transport" in body:
        v = body["transport"]
        if v is not None and (not isinstance(v, str) or not _TRANSPORT_RE.match(v)):
            raise E.print_job_invalid()
        out["transport"] = v
    return out


def parse_create(body) -> dict:
    if not isinstance(body, dict):
        raise E.print_job_invalid()
    out = {"id": _uuid(body.get("id")), "doc_type": _enum(body.get("doc_type"), DOC_TYPES),
           "doc_id": _uuid(body.get("doc_id")), "copy": _enum(body.get("copy"), COPIES),
           "status": "PENDING", "attempts": 0}
    return _optional_fields(body, out)


def parse_patch(body) -> dict:
    if not isinstance(body, dict):
        raise E.print_job_invalid()
    return _optional_fields(body, {})


def parse_doc_ref(doc_type, doc_id):
    """`GET /print-jobs` so'rov parametrlari. `TEST` — hujjat turi EMAS (namuna jurnalga
    tushmaydi)."""
    return _enum(doc_type, DOC_TYPES), _uuid(doc_id)


# ── HOLAT O'TISHI ────────────────────────────────────────────────────────────
def apply_transition(job, data: dict, now: datetime) -> None:
    """PENDING/FAILED → istalgan; PRINTED → PRINTED (hech narsa o'zgarmaydi);
    PRINTED → boshqa — 409 (chop etilgan chek «chop etilmagan» bo'lib qolmaydi).
    `attempts` faqat O'SADI (eskirgan hisobot sanoqni kamaytirmaydi)."""
    new_status = data.get("status")
    if job.status == "PRINTED":
        if new_status in (None, "PRINTED"):
            return
        raise HTTPException(409, E.PRINT_JOB_FINAL, headers={HEADER: E.PRINT_JOB_FINAL_CODE})
    if new_status is not None:
        job.status = new_status
    if "attempts" in data:
        job.attempts = max(job.attempts or 0, data["attempts"])
    for f in ("printer", "transport"):
        if f in data:
            setattr(job, f, data[f])
    if "error" in data:
        job.error = data["error"]
    elif new_status == "PRINTED":
        job.error = None
    if job.status == "PRINTED" and job.printed_at is None:
        job.printed_at = now
    job.updated_at = now


def _doc_lock(db: Session, company_id, doc_type: str, doc_id) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    key = int.from_bytes(hashlib.sha256(f"{company_id}:{doc_type}:{doc_id}".encode()).digest()[:4],
                         "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:ns, :k)"), {"ns": _LOCK_NS, "k": key})


def _locked_job(db: Session, job_id):
    from app.models.receipt import PrintJob
    return (db.query(PrintJob).filter(PrintJob.id == job_id)
            .with_for_update().populate_existing().first())


def _as_duplicate(db: Session, emp, job, data: dict):
    if job.company_id != emp.company_id:
        raise E.print_job_invalid(404)            # boshqa do'kon id'si — hech narsa ochilmaydi
    if (job.doc_type, job.doc_id, job.copy) != (data["doc_type"], data["doc_id"], data["copy"]):
        raise E.print_job_invalid()               # ayni id, BOSHQA hujjat — mijoz xatosi
    readable_doc(db, emp, job.doc_type, job.doc_id)
    apply_transition(job, data, _now())
    return job, False


def create_job(db: Session, emp, data: dict):
    """(qator, yangi_mi). COMMIT QILMAYDI (chaqiruvchi qiladi)."""
    from app.models.receipt import PrintJob
    existing = _locked_job(db, data["id"])
    if existing is not None:
        return _as_duplicate(db, emp, existing, data)
    doc = readable_doc(db, emp, data["doc_type"], data["doc_id"])
    cid = emp.company_id
    same_doc = (PrintJob.company_id == cid, PrintJob.doc_type == data["doc_type"],
                PrintJob.doc_id == data["doc_id"])
    if data["copy"] == "ORIGINAL":
        if db.query(PrintJob.id).filter(*same_doc, PrintJob.copy == "ORIGINAL").first() is not None:
            raise _original_exists()
        copy_no = 0
    else:
        _doc_lock(db, cid, data["doc_type"], data["doc_id"])
        copy_no = int(db.query(func.count(PrintJob.id))
                      .filter(*same_doc, PrintJob.copy == "REPRINT").scalar() or 0) + 1
    now = _now()
    job = PrintJob(id=data["id"], company_id=cid, branch_id=doc.branch_id,
                   doc_type=data["doc_type"], doc_id=data["doc_id"], copy=data["copy"],
                   copy_no=copy_no, status=data["status"], attempts=data["attempts"],
                   error=data.get("error"), printer=data.get("printer"),
                   transport=data.get("transport"), created_by=emp.id, created_at=now,
                   updated_at=now, printed_at=now if data["status"] == "PRINTED" else None)
    sp = db.begin_nested()
    try:
        db.add(job)
        db.flush()
        sp.commit()
    except IntegrityError:
        sp.rollback()
        # Poyga: ayni `id` parallel keldi (PK) yoki boshqa oyna asl chekni oldinroq yozdi.
        again = _locked_job(db, data["id"])
        if again is not None:
            return _as_duplicate(db, emp, again, data)
        if data["copy"] == "ORIGINAL":
            raise _original_exists() from None
        raise
    return job, True


def _original_exists() -> HTTPException:
    return HTTPException(409, E.PRINT_ORIGINAL_EXISTS,
                         headers={HEADER: E.PRINT_ORIGINAL_EXISTS_CODE})


def patch_job(db: Session, emp, job_id, data: dict):
    job = _locked_job(db, job_id)
    if job is None or job.company_id != emp.company_id:
        raise E.print_job_invalid(404)
    readable_doc(db, emp, job.doc_type, job.doc_id)
    apply_transition(job, data, _now())
    return job


def list_jobs(db: Session, emp, doc_type: str, doc_id) -> list:
    from app.models.receipt import PrintJob
    readable_doc(db, emp, doc_type, doc_id)
    return (db.query(PrintJob)
            .filter(PrintJob.company_id == emp.company_id, PrintJob.doc_type == doc_type,
                    PrintJob.doc_id == doc_id)
            .order_by(PrintJob.created_at, PrintJob.id).all())


def job_out(job, duplicate: bool | None = None) -> dict:
    out = {"id": str(job.id), "doc_type": job.doc_type, "doc_id": str(job.doc_id), "copy": job.copy,
           "copy_no": job.copy_no, "status": job.status, "attempts": job.attempts,
           "error": job.error, "printer": job.printer, "transport": job.transport,
           "created_at": _iso(job.created_at), "updated_at": _iso(job.updated_at),
           "printed_at": _iso(job.printed_at)}
    if duplicate is not None:
        out["duplicate"] = duplicate
    return out
