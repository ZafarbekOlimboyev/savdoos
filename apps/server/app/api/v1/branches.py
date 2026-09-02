"""Filiallar API — do'kon tarmog'i + tarif-limitli filial qo'shish, tahrir, deaktivatsiya, o'chirish.

Tarif limitlari:
  start  = 1 filial · start+ = 5 filial · business = cheksiz (999).
Tarif Setting(key="plan") da saqlanadi (default: start).
"""
import re
import uuid as _uuidmod
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.reports import _TZ_OFFSETS, _store_tz
from app.core.deps import FULL_ACCESS_ROLES, effective_permissions, get_current_employee, require, visible_branches
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import SaleStatus
from app.models.org import Branch, Company
from app.models.sales import Return, Sale
from app.models.settings import Setting

router = APIRouter(tags=["branches"])

PLAN_LIMITS = {"start": 1, "start+": 5, "business": 999}


def _plan(db: Session, company_id):
    row = db.query(Setting).filter(Setting.company_id == company_id, Setting.key == "plan").first()
    val = (row.value if row else {}) or {}
    plan = val.get("plan", "start")
    return plan, PLAN_LIMITS.get(plan, 1)


class BranchIn(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None
    timezone: str | None = None


class BranchEdit(BaseModel):
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    timezone: str | None = None
    is_active: bool | None = None


def _norm_branch_phone(raw: str | None) -> str | None:
    """QA SB-012: 'abc' kabi kiritma JIMGINA null bo'lib saqlanardi — endi aniq 400."""
    from app.core.security import norm_phone
    from app.core.validate import require_phone
    if raw is not None and raw.strip() and not norm_phone(raw):
        raise HTTPException(400, "Telefon raqami noto'g'ri. Masalan: +996 700 123 456")
    phone = norm_phone(raw) or None
    require_phone(phone or "")
    return phone


def _dup_name(db: Session, company_id, name: str, exclude_id=None) -> bool:
    """QA SB-010: bir xil nomli filial chalkashlik — endi rad etiladi (katta-kichik farqsiz)."""
    q = db.query(Branch).filter(
        Branch.company_id == company_id, Branch.deleted_at.is_(None),
        func.lower(Branch.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(Branch.id != exclude_id)
    return db.query(q.exists()).scalar()


@router.get("/branches")
def list_branches(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    cid = emp.company_id
    plan, maxb = _plan(db, cid)
    rows = (
        db.query(Branch)
        .filter(Branch.company_id == cid, Branch.deleted_at.is_(None))
        .order_by(Branch.created_at).all()
    )
    LOCAL = _store_tz(db, cid)
    day0 = datetime.now(timezone.utc).astimezone(LOCAL).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    NOT_VOID = Sale.status != SaleStatus.voided
    _vb = visible_branches(emp, db)  # filialга bog'langan xodим boshqa filial tushumini ko'rmasin
    # QA SB-002: tushum/kassir raqamlari RUXSAT talab qiladi — ilgari HAR xodim (kassir ham,
    # biriktirilmagani esa BUTUN kompaniya bo'yicha) kunlik tushumni ko'rardi.
    _can_rev = emp.role.code in FULL_ACCESS_ROLES or "hisobot.view" in effective_permissions(emp, db)
    out = []
    for b in rows:
        visible = _can_rev and (_vb is None or b.id in _vb)
        if not visible:
            # Filial ro'yxatда qoladi (tanlov/nom uchun), raqamlar yashirin. visible=False —
            # frontend detail sahifasини ochmasin (QA SB-017: begona nom ostida o'z raqamlari chiqardi).
            out.append({
                "id": str(b.id), "name": b.name, "address": b.address, "phone": b.phone,
                "timezone": b.timezone, "cashiers": 0, "sales_today": 0.0,
                "is_active": b.is_active, "visible": False,
            })
            continue
        # QA SB-018: 'kassirlar' butun tarix bo'yicha edi — endi BUGUN sotganlar (karta semantikasi).
        cashiers = db.query(func.count(func.distinct(Sale.cashier_id))).filter(
            Sale.company_id == cid, Sale.branch_id == b.id, NOT_VOID, Sale.sold_at >= day0).scalar() or 0
        gross = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            Sale.company_id == cid, Sale.branch_id == b.id, NOT_VOID, Sale.sold_at >= day0).scalar())
        # QA SB-009: qaytarish NETlanadi — Dashboard/summary bilan bir xil raqam.
        ret = float(db.query(func.coalesce(func.sum(Return.total), 0)).filter(
            Return.company_id == cid, Return.branch_id == b.id, Return.created_at >= day0).scalar())
        out.append({
            "id": str(b.id), "name": b.name, "address": b.address, "phone": b.phone,
            "timezone": b.timezone, "cashiers": int(cashiers), "sales_today": gross - ret,
            "is_active": b.is_active, "visible": True,
        })
    return {"branches": out, "plan": plan, "max_branches": maxb,
            "count": len(rows), "can_add": len(rows) < maxb}


def _next_code(db: Session, company_id) -> str:
    """QA SB-007: F-{count+1} soft-delete/parallelда dublikat berardi. Endi BARCHA (o'chirilgan
    ham) filiallar ichida eng katta raqamiy suffiks + 1 (Company qulfi ostida chaqiriladi)."""
    mx = 0
    for (code,) in db.query(Branch.code).filter(Branch.company_id == company_id).all():
        m = re.search(r"(\d+)$", code or "")
        if m:
            mx = max(mx, int(m.group(1)))
    return f"F-{mx + 1:03d}"


@router.post("/branches")
def create_branch(data: BranchIn, emp: Employee = Depends(require("sozlamalar.edit")), db: Session = Depends(get_db)):
    cid = emp.company_id
    # QULF (QA SB-007): tarif-limit va kod-generatsiya check-then-act poyga edi (5-limitда 7 filial,
    # ommaviy kod-dublikat). Company qatorини FOR UPDATE qulflab, yaratishни KETMA-KET qilamiz.
    db.query(Company).filter(Company.id == cid).with_for_update().first()
    plan, maxb = _plan(db, cid)
    count = db.query(Branch).filter(Branch.company_id == cid, Branch.deleted_at.is_(None)).count()
    if count >= maxb:
        raise HTTPException(403, detail={"error": "tarif_limit", "plan": plan, "max_branches": maxb})
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(422, "Filial nomi kerak")
    if _dup_name(db, cid, name):
        raise HTTPException(409, "Bu nomli filial allaqachon mavjud")
    phone = _norm_branch_phone(data.phone)
    tz = (data.timezone or "Asia/Tashkent").strip()
    if tz not in _TZ_OFFSETS:  # noma'lum vaqt mintaqasi jimgina Toshkentga tushmasin
        raise HTTPException(400, "Noto'g'ri vaqt mintaqasi")
    now = datetime.now(timezone.utc)
    b = Branch(
        company_id=cid, code=_next_code(db, cid), name=name[:200],
        address=((data.address or "").strip() or None), phone=phone,
        timezone=tz, is_active=True,
        created_at=now, updated_at=now,
    )
    from sqlalchemy.exc import IntegrityError as _IE
    from app.services.audit import log as audit_log
    try:
        db.add(b)
        db.flush()
        audit_log(db, emp.id, "create", "branch", b.id, after={"name": b.name, "code": b.code})
        db.commit()
    except _IE:
        db.rollback()
        raise HTTPException(409, "Filial kodi band — qayta urining")
    db.refresh(b)
    return {"id": str(b.id), "name": b.name}


def _own_branch(db: Session, branch_id, company_id) -> Branch:
    b = db.get(Branch, branch_id)
    if not b or b.company_id != company_id or b.deleted_at is not None:
        raise HTTPException(404, "Filial topilmadi")
    return b


@router.patch("/branches/{branch_id}")
def edit_branch(
    branch_id: _uuidmod.UUID,
    data: BranchEdit,
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    """QA SB-003/SB-004: filial tahriri (nom/manzil/telefon/timezone/is_active) — ilgari umuman
    yo'q edi (timezone abadiy, xato nom tuzatib bo'lmasdi, deaktivatsiya imkonsiz)."""
    b = _own_branch(db, branch_id, emp.company_id)
    before = {"name": b.name, "is_active": b.is_active, "timezone": b.timezone}
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(422, "Filial nomi kerak")
        if _dup_name(db, emp.company_id, name, exclude_id=b.id):
            raise HTTPException(409, "Bu nomli filial allaqachon mavjud")
        b.name = name[:200]
    if data.address is not None:
        b.address = data.address.strip() or None
    if data.phone is not None:
        b.phone = _norm_branch_phone(data.phone)
    if data.timezone is not None:
        tz = data.timezone.strip()
        if tz not in _TZ_OFFSETS:
            raise HTTPException(400, "Noto'g'ri vaqt mintaqasi")
        # DIQQAT: hisobot vaqt mintaqasi ENG BIRINCHI filialdan olinadi (_store_tz) — birinchi
        # filial tz'sini o'zgartirish keyingi yozuvlar talqinini o'zgartiradi (eski kunlar qayta
        # hisoblanmaydi, faqat yangi yozuvlar yangi tz'da bucketlanadi).
        b.timezone = tz
    if data.is_active is not None:
        if data.is_active is False:
            active_others = db.query(Branch).filter(
                Branch.company_id == emp.company_id, Branch.deleted_at.is_(None),
                Branch.is_active.is_(True), Branch.id != b.id).count()
            if active_others == 0:
                raise HTTPException(400, "Oxirgi faol filialni o'chirib bo'lmaydi")
        b.is_active = data.is_active
    b.updated_at = datetime.now(timezone.utc)
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "update", "branch", b.id, before=before,
              after={"name": b.name, "is_active": b.is_active, "timezone": b.timezone})
    db.commit()
    return {"ok": True, "id": str(b.id), "name": b.name, "is_active": b.is_active}


@router.delete("/branches/{branch_id}")
def delete_branch(
    branch_id: _uuidmod.UUID,
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    """QA SB-003: filialni o'chirish (soft) — himoyalar bilan: oxirgi filial, biriktirilgan
    xodim, ochiq smena yoki qoldiq bo'lsa o'chirilmaydi (avval ko'chirish/yopish kerak)."""
    b = _own_branch(db, branch_id, emp.company_id)
    # QA WH-003 (TOCTOU): filial qatori FOR UPDATE — parallel transfer (u ham Branch'ni qulflaydi)
    # guard va deleted_at orasida stok kiritolmaydi.
    db.query(Branch).filter(Branch.id == b.id).with_for_update().first()
    others = db.query(Branch).filter(
        Branch.company_id == emp.company_id, Branch.deleted_at.is_(None), Branch.id != b.id).count()
    if others == 0:
        raise HTTPException(400, "Yagona filialni o'chirib bo'lmaydi")
    from app.models.auth import EmployeeBranch
    if db.query(EmployeeBranch.employee_id).filter(EmployeeBranch.branch_id == b.id).first():
        raise HTTPException(400, "Filialga biriktirilgan xodimlar bor — avval ularni boshqa filialga o'tkazing")
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    if db.query(Shift.id).filter(Shift.branch_id == b.id, Shift.status == ShiftStatus.open).first():
        raise HTTPException(400, "Filialda ochiq smena bor — avval smenani yoping")
    from app.models.inventory import Inventory
    # QA WH-003: YIG'INDI emas QATOR-DARAJADA tekshiramiz — oversell'dagi manfiy qator musbat
    # stokni yashirib (masalan +50 va -60 -> sum -10) filial o'chib, 50 dona tovar o'chik
    # filialda qamalib g'oyib bo'lardi. FOR UPDATE — parallel transfer bilan TOCTOU yopiq
    # (transfer ham endi filial qatorlarini qulflaydi).
    _nonzero = (db.query(Inventory)
                .filter(Inventory.branch_id == b.id, Inventory.qty != 0)
                .with_for_update().first())
    if _nonzero is not None:
        raise HTTPException(400, "Filialda qoldiq bor — avval boshqa filialga ko'chiring (transfer)")
    b.deleted_at = datetime.now(timezone.utc)
    b.is_active = False
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "delete", "branch", b.id, before={"name": b.name, "code": b.code})
    db.commit()
    return {"ok": True}
