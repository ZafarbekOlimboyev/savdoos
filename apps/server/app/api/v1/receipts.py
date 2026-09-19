# -*- coding: utf-8 -*-
"""Chek: shablon sozlamasi, logo, kassa profili, namuna, kanonik DTO, chop etish jurnali (Phase 5F).

⚠️  HAMMASI COMMIT'DAN KEYIN. Bu routerdagi hech bir endpoint sotuv/qaytarish yozish
    yo'lida chaqirilmaydi va sotuv/qaytarish/qoldiq/kassa jadvallariga YOZMAYDI.
    Yozadiganlari faqat: `settings` (key=receipt), `receipt_logos`, `print_jobs`, `audit_logs`.
⚠️  FILIAL IZOLYATSIYASI (`app.services.receipt.settings.visible_branch/write_scope`):
    begona/ko'rinmas/o'chirilgan filial — bir xil 404; kompaniya shabloni — faqat
    filial cheklovisiz xodim.
⚠️  Tana `Any` sifatida olinadi va QO'LDA tekshiriladi: xatolar pydantic 422 ro'yxati
    emas, tarjima qilinadigan barqaror matn (+ `X-Error-Code`) bo'lsin.
"""
import hashlib
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.deps import (SALES_DOC_TIER, actor_branch, has_any, require, require_any,
                           visible_branches)
from app.db.session import get_db
from app.models.auth import Employee
from app.models.org import Branch, Company
from app.services.receipt import dto as RD
from app.services.receipt import errors as E
from app.services.receipt import jobs as RJ
from app.services.receipt import logo as RL
from app.services.receipt import sample as RSample
from app.services.receipt import settings as RS
from app.services.receipt.access import readable_return, readable_sale
from app.services.receipt.codes import qr_block

router = APIRouter(tags=["receipt"])

PROFILE_PERMS = ("kassa.sell", "sotuvlar.view", "sozlamalar.view", "qaytarishlar.create")
SAMPLE_PERMS = ("sozlamalar.view", "kassa.sell")
RETURN_RECEIPT_PERMS = ("qaytarishlar.view", "qaytarishlar.create")
# Onlayn chek faqat server DTO'sidan: sotuv huquqi bor kassir O'Z chekini chop eta olsin.
SALE_RECEIPT_PERMS = (*SALES_DOC_TIER, "kassa.sell")
PRINT_PERMS = ("kassa.sell", "sotuvlar.view", "qaytarishlar.create", "qaytarishlar.view")


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _default_branch(db: Session, emp: Employee, branch_id: str | None) -> Branch:
    """Aniq filial — ko'rinishi shart; berilmasa xodim YOZADIGAN filial (`actor_branch`):
    kassa profili sotuv aynan tushadigan filialniki bo'lishi kerak.

    ⚠️  `actor_branch` HAM ko'rinadigan hisoblanadi (ko'rinadigan ∪ {actor_branch}).
        Biriktirilgan filiali nofaol kassirning sotuvi zaxira filialga tushadi; o'sha
        filialni standart yo'l beradi-yu, aniq so'ralganda 404 berish — bir savolga ikki
        javob bo'lardi."""
    ab = actor_branch(emp, db)
    if branch_id is not None:
        if ab is not None and RS.parse_uuid(branch_id) == ab.id:
            return ab
        return RS.visible_branch(db, emp, branch_id)
    if ab is None:
        raise E.branch_not_found()
    return ab


def _settings_view(db: Session, emp: Employee, branch: Branch | None) -> dict:
    company = db.get(Company, emp.company_id)
    eff, cval, bval = RS.resolve_for_branch(db, emp.company_id, branch)
    vis = visible_branches(emp, db)
    can_edit = has_any(emp, db, ("sozlamalar.edit",))
    q = db.query(Branch.id, Branch.name).filter(Branch.company_id == emp.company_id,
                                                 Branch.deleted_at.is_(None))
    if vis is not None:
        q = q.filter(Branch.id.in_(vis))
    branches = [{"id": str(i), "name": n}
                for i, n in q.order_by(Branch.created_at, Branch.id).all()]
    logo = RL.accessible_logo(db, emp.company_id, branch.id if branch else None, eff.get("logo_id"))
    return {
        "scope": {"branch_id": str(branch.id) if branch else None,
                  "company_editable": can_edit and vis is None,
                  "branch_editable": branch is not None and can_edit},
        "branches": branches,
        # Qatorlar TOZALANGAN holda (`clean_stored`): UI ko'rsatadigan «ustama» maydonlar
        # aynan `effective` ga ta'sir qiladiganlari bilan bir xil bo'lsin.
        "company": RS.clean_stored(cval),
        "branch": RS.clean_stored(bval) if branch is not None and bval is not None else None,
        "effective": eff,
        "store": RS.resolve_store(db, company, branch, eff),
        "logo": RL.logo_out(logo) if logo is not None else None,
    }


# ── SHABLON SOZLAMASI ────────────────────────────────────────────────────────
@router.get("/receipt/settings")
def get_receipt_settings(
    branch_id: str | None = None,
    emp: Employee = Depends(require("sozlamalar.view")),
    db: Session = Depends(get_db),
):
    branch = RS.visible_branch(db, emp, branch_id) if branch_id is not None else None
    return _settings_view(db, emp, branch)


@router.put("/receipt/settings")
def put_receipt_settings(
    body: Any = Body(None),
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    if not isinstance(body, dict) or not isinstance(body.get("value"), dict):
        raise E.invalid_field("value")
    branch = RS.write_scope(db, emp, body.get("branch_id"))     # ruxsat — validatsiyadan OLDIN
    patch = RS.validate_receipt_patch(body["value"])
    RS.write_receipt_settings(db, emp, branch, patch)
    db.commit()
    return _settings_view(db, emp, branch)


# ── LOGO ─────────────────────────────────────────────────────────────────────
@router.post("/receipt/logos")
def upload_logo(
    response: Response,
    body: Any = Body(None),
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    if not isinstance(body, dict):
        raise HTTPException(400, E.LOGO_CORRUPT)
    branch = RS.write_scope(db, emp, body.get("branch_id"))
    raw = RL.decode_b64(body.get("data_b64"))
    bid = branch.id if branch else None
    row = RL.existing_logo(db, emp.company_id, bid, raw)
    processed = None
    if row is None:
        # ⚠️  CPU ishidan OLDIN ulanish hovuzga qaytadi: dekodlash soniyalab cho'zilsa ham
        #     pooled ulanish «idle in transaction» bo'lib turmaydi (faqat o'qishlar edi —
        #     yo'qotiladigan yozuv yo'q). `emp` keyin kerak bo'lsa qayta o'qiladi.
        db.rollback()
        processed = RL.process(raw)
    row, created = (RL.store_logo(db, emp, bid, raw, processed=processed) if row is None
                    else (row, False))
    db.commit()
    response.status_code = 201 if created else 200
    return {**RL.logo_out(row), "duplicate": not created}


@router.get("/receipt/logos/{logo_id}")
def get_logo(
    logo_id: str,
    emp: Employee = Depends(require("sozlamalar.view")),
    db: Session = Depends(get_db),
):
    from app.models.receipt import ReceiptLogo
    lid = RS.parse_uuid(logo_id)
    row = db.get(ReceiptLogo, lid) if lid is not None else None
    if row is None or row.company_id != emp.company_id:
        raise HTTPException(404, E.LOGO_NOT_FOUND)
    if row.branch_id is not None:
        vis = visible_branches(emp, db)
        if vis is not None and row.branch_id not in vis:
            raise HTTPException(404, E.LOGO_NOT_FOUND)
    return RL.logo_out(row)


# ── KASSA PROFILI ────────────────────────────────────────────────────────────
def profile_body(db: Session, emp: Employee, branch: Branch) -> dict:
    company = db.get(Company, emp.company_id)
    eff, _, _ = RS.resolve_for_branch(db, emp.company_id, branch)
    logo = None
    if eff["show_logo"] and eff["logo_id"]:
        row = RL.accessible_logo(db, emp.company_id, branch.id, eff["logo_id"])
        if row is not None:
            logo = {"id": str(row.id), "sha256": row.sha256, "variants": RL.variants_out(row)}
    store_qr = None
    if eff["qr_mode"] == "store_url" and eff["qr_url"]:
        b = qr_block("store_url", eff["qr_url"])
        store_qr = {"payload": b["payload"], "size": b["size"], "matrix": b["matrix"]}
    return {"branch_id": str(branch.id), "effective": eff,
            "store": RS.resolve_store(db, company, branch, eff), "logo": logo, "store_qr": store_qr}


@router.get("/receipt/profile")
def receipt_profile(
    branch_id: str | None = None,
    known_etag: str | None = None,
    emp: Employee = Depends(require_any(*PROFILE_PERMS)),
    db: Session = Depends(get_db),
):
    """Kassa offline chop etishi uchun: shablon + do'kon + logo bitlari + do'kon QR.

    `etag` — javob tanasining kanonik JSON sha256'i: kassa har 5 daqiqada so'raydi va
    o'zgarmagan bo'lsa logo baytlarini qayta yuklamaydi (`unchanged: true`)."""
    branch = _default_branch(db, emp, branch_id)
    body = profile_body(db, emp, branch)
    etag = hashlib.sha256(_canonical(body)).hexdigest()
    if known_etag is not None and known_etag == etag:
        return {"etag": etag, "unchanged": True}
    return {"etag": etag, **body}


# ── NAMUNA (bazaga yozmaydi) ─────────────────────────────────────────────────
@router.get("/receipt/sample")
def receipt_sample(
    kind: Literal["sale", "mixed", "return", "long"] = "sale",
    branch_id: str | None = None,
    scope: Literal["branch", "company"] = "branch",
    emp: Employee = Depends(require_any(*SAMPLE_PERMS)),
    db: Session = Depends(get_db),
):
    """`scope=company` — FAQAT kompaniya standarti (filial ustamasisiz): Manager kompaniya
    shablonini tahrirlayotganda namuna/sinov chop etish xodimning filial ustamasini emas,
    aynan tahrirlanayotgan shablonni ko'rsatsin. Kompaniya doirasi — faqat filial
    cheklovisiz xodim (`company_editable` bilan AYNI qoida); `branch_id` e'tiborsiz."""
    if scope == "company":
        if visible_branches(emp, db) is not None:
            raise E.scope_company_forbidden()
        return RSample.build_sample(db, emp, None, kind)
    branch = _default_branch(db, emp, branch_id)
    return RSample.build_sample(db, emp, branch, kind)


# ── HUJJAT CHEKI (kanonik DTO) ───────────────────────────────────────────────
@router.get("/sales/{sale_id}/receipt")
def sale_receipt(
    sale_id: uuid.UUID,
    emp: Employee = Depends(require_any(*SALE_RECEIPT_PERMS)),
    db: Session = Depends(get_db),
):
    """`GET /sales/{id}` doirasi + MUALLIF istisnosi (`access.readable_sale`): `kassa.sell`
    (tarixsiz) kassir faqat O'Z sotuvi chekini oladi; `GET /sales/{id}` o'zgarmaydi."""
    sale = readable_sale(db, emp, sale_id, check_perm=False)
    return RD.build_sale_receipt(db, sale)


@router.get("/returns/{return_id}/receipt")
def return_receipt(
    return_id: uuid.UUID,
    emp: Employee = Depends(require_any(*RETURN_RECEIPT_PERMS)),
    db: Session = Depends(get_db),
):
    ret = readable_return(db, emp, return_id, check_perm=False)
    return RD.build_return_receipt(db, ret)


# ── CHOP ETISH JURNALI ───────────────────────────────────────────────────────
@router.post("/print-jobs")
def create_print_job(
    response: Response,
    body: Any = Body(None),
    emp: Employee = Depends(require_any(*PRINT_PERMS)),
    db: Session = Depends(get_db),
):
    data = RJ.parse_create(body)
    job, created = RJ.create_job(db, emp, data)
    db.commit()
    response.status_code = 201 if created else 200
    return RJ.job_out(job, duplicate=not created)


@router.patch("/print-jobs/{job_id}")
def patch_print_job(
    job_id: str,
    body: Any = Body(None),
    emp: Employee = Depends(require_any(*PRINT_PERMS)),
    db: Session = Depends(get_db),
):
    jid = RS.parse_uuid(job_id)
    if jid is None:
        raise E.print_job_invalid(404)
    data = RJ.parse_patch(body)
    job = RJ.patch_job(db, emp, jid, data)
    db.commit()
    return RJ.job_out(job)


@router.get("/print-jobs")
def list_print_jobs(
    doc_type: str | None = None,
    doc_id: str | None = None,
    emp: Employee = Depends(require_any(*PRINT_PERMS)),
    db: Session = Depends(get_db),
):
    dt, did = RJ.parse_doc_ref(doc_type, doc_id)
    return [RJ.job_out(j) for j in RJ.list_jobs(db, emp, dt, did)]
