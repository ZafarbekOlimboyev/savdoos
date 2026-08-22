"""Vendor admin — mijozlarga akkaunt ochish va parol tiklash.

Bu endpoint'lar OMMAVIY emas: X-Vendor-Key sarlavhasi (settings.vendor_admin_key) talab qilinadi.
Kalit sozlanmagan bo'lsa — butunlay o'chiq (503). Mijozlar o'zi ro'yxatdan o'ta olmaydi;
akkauntlarni faqat biz (vendor) ochamiz va login+parol beramiz.
"""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, norm_phone
from app.db.session import get_db
from app.models.auth import Employee, Role
from app.models.org import Branch, Company
from app.models.settings import PaymentMethod, Setting

router = APIRouter(prefix="/admin", tags=["admin"])

_PLANS = ("start", "start+", "business")
_PAYMENTS = [("cash", "Naqd", True), ("card", "Karta", True), ("qr", "QR", True), ("credit", "Qarz", True)]


def require_vendor(x_vendor_key: str | None = Header(default=None, alias="X-Vendor-Key")):
    if not settings.vendor_admin_key:
        raise HTTPException(503, "Vendor admin o'chirilgan (VENDOR_ADMIN_KEY sozlanmagan)")
    if not x_vendor_key or not hmac.compare_digest(x_vendor_key, settings.vendor_admin_key):
        raise HTTPException(401, "Vendor kaliti noto'g'ri")
    return True


class ProvisionIn(BaseModel):
    company_name: str = Field(min_length=1)
    company_code: str = Field(min_length=2, max_length=40)
    owner_name: str = Field(min_length=1)
    owner_phone: str = Field(min_length=4)
    owner_password: str = Field(min_length=6)
    plan: str = "start"
    currency: str = Field(default="UZS", min_length=3, max_length=3)
    branch_name: str = "Asosiy filial"
    owner_pin: str | None = None


@router.post("/companies")
def provision(data: ProvisionIn, _: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Yangi mijoz: do'kon (tenant) + egа (admin, telefon+parol) + 1 filial + tarif."""
    code = data.company_code.strip().lower()
    plan = data.plan.strip().lower()
    phone = norm_phone(data.owner_phone)
    if not code:
        raise HTTPException(400, "company_code bo'sh bo'lishi mumkin emas")
    if not data.company_name.strip():
        raise HTTPException(400, "company_name bo'sh bo'lishi mumkin emas")
    if not data.owner_name.strip():
        raise HTTPException(400, "owner_name bo'sh bo'lishi mumkin emas")
    if not phone or len(phone) < 5:
        raise HTTPException(400, "owner_phone da kamida 4 raqam bo'lishi kerak")
    if plan not in _PLANS:
        raise HTTPException(400, "plan: start | start+ | business")
    if db.query(Company).filter(Company.code == code, Company.deleted_at.is_(None)).first():
        raise HTTPException(409, "Bu do'kon kodi band")
    if (
        db.query(Employee)
        .filter(Employee.phone == phone, Employee.password_hash.isnot(None), Employee.deleted_at.is_(None))
        .first()
    ):
        raise HTTPException(409, "Bu telefon allaqachon ro'yxatda")
    owner_pin = (data.owner_pin or "").strip()
    if data.owner_pin is not None and (len(owner_pin) < 4 or not owner_pin.isdigit()):
        raise HTTPException(400, "owner_pin kamida 4 raqam bo'lishi kerak")
    role = db.query(Role).filter(Role.code == "administrator").first()
    if not role:
        raise HTTPException(500, "Administrator roli topilmadi — avval seed ishga tushiring")

    company = Company(name=data.company_name.strip(), code=code, currency=data.currency.strip() or "UZS")
    db.add(company)
    db.flush()
    branch = Branch(company_id=company.id, code="F01", name=(data.branch_name.strip() or "Asosiy filial"))
    db.add(branch)
    db.flush()
    for i, (c, n, en) in enumerate(_PAYMENTS):
        db.add(PaymentMethod(company_id=company.id, code=c, name=n, is_enabled=en, sort_order=i))
    db.add(Setting(company_id=company.id, key="plan", value={"plan": plan}))
    db.add(Setting(company_id=company.id, key="store_info",
                   value={"name": company.name, "branch": branch.name}))
    owner = Employee(
        company_id=company.id,
        full_name=data.owner_name.strip(),
        phone=phone,
        role_id=role.id,
        password_hash=hash_password(data.owner_password),
        pin_hash=hash_password(owner_pin) if owner_pin else None,
    )
    db.add(owner)
    db.commit()
    db.refresh(company)
    db.refresh(owner)
    return {
        "ok": True,
        "company_id": str(company.id),
        "company_code": code,
        "branch_id": str(branch.id),
        "owner_id": str(owner.id),
        "owner_phone": phone,
        "plan": plan,
    }


class ResetIn(BaseModel):
    owner_phone: str | None = None      # telefon bo'yicha (odatiy)
    company_code: str | None = None     # yoki do'kon kodi bo'yicha (eski/normallashmagan telefonli do'konni ochish)
    new_password: str = Field(min_length=6)


@router.post("/reset-password")
def reset_password(data: ResetIn, _: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Vendor parol tiklash. `owner_phone` yoki `company_code` bo'yicha.

    `company_code` — eski do'konni (telefonlari normallashmagan, paroli yo'q) ochish uchun:
    do'kon administratorini topib, telefonini normallashtiradi va parol o'rnatadi."""
    target = None
    if data.company_code:
        comp = (
            db.query(Company)
            .filter(Company.code == data.company_code.strip().lower(), Company.deleted_at.is_(None))
            .first()
        )
        if not comp:
            raise HTTPException(404, "Do'kon kodi topilmadi")
        emps = db.query(Employee).filter(
            Employee.company_id == comp.id, Employee.deleted_at.is_(None)).all()
        admins = [e for e in emps if e.role.code == "administrator"]
        target = admins[0] if admins else (emps[0] if emps else None)
    elif data.owner_phone:
        phone = norm_phone(data.owner_phone)
        emps = db.query(Employee).filter(Employee.phone == phone, Employee.deleted_at.is_(None)).all()
        target = next((e for e in emps if e.password_hash), None) or (emps[0] if emps else None)
    else:
        raise HTTPException(400, "owner_phone yoki company_code kerak")
    if not target:
        raise HTTPException(404, "Xodim topilmadi")
    # Telefonni normallashtiramiz (eski bo'sh-joyli formatni tuzatamiz) — login mos kelishi uchun
    norm = norm_phone(target.phone)
    if norm and norm != target.phone:
        clash = db.query(Employee).filter(
            Employee.phone == norm, Employee.password_hash.isnot(None),
            Employee.deleted_at.is_(None), Employee.id != target.id).first()
        if clash:
            raise HTTPException(409, "Bu telefon boshqa akkauntda band")
        target.phone = norm
    target.password_hash = hash_password(data.new_password)
    db.commit()
    return {"ok": True, "owner_id": str(target.id), "owner_phone": target.phone, "name": target.full_name}
