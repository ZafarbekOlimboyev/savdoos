"""Vendor admin — mijozlarga akkaunt ochish va parol tiklash.

Bu endpoint'lar OMMAVIY emas: X-Vendor-Key sarlavhasi (settings.vendor_admin_key) talab qilinadi.
Kalit sozlanmagan bo'lsa — butunlay o'chiq (503). Mijozlar o'zi ro'yxatdan o'ta olmaydi;
akkauntlarni faqat biz (vendor) ochamiz va login+parol beramiz.
"""
import base64
import hashlib
import hmac
import os
import struct
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, norm_phone
from app.db.session import get_db
from app.models.auth import Employee, Role
from app.models.catalog import Product
from app.models.enums import SaleStatus
from app.models.org import Branch, Company
from app.models.sales import Sale
from app.models.settings import PaymentMethod, Setting

router = APIRouter(prefix="/admin", tags=["admin"])

# Vendor portal HTML (statik "qobiq" — barcha ma'lumot X-Vendor-Key bilan yuklanadi).
_PORTAL_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "vendor_portal.html")


@router.get("/portal", include_in_schema=False)
def vendor_portal():
    return FileResponse(_PORTAL_HTML, media_type="text/html")

_PLANS = ("start", "start+", "business")
_PAYMENTS = [("cash", "Naqd", True), ("card", "Karta", True), ("qr", "QR", True), ("credit", "Qarz", True)]


def _check_vendor_ip(request: Request):
    """Ixtiyoriy IP-allowlist — sozlangan bo'lsa, faqat ruxsat etilgan IP'lardан (kalit sizsa ham himoya)."""
    allowed = settings.vendor_ip_list
    if not allowed:
        return
    ip = request.client.host if request.client else ""
    # Reverse-proxy (Railway) ortida haqiqiy IP X-Forwarded-For'ning birinchi qismida
    fwd = request.headers.get("x-forwarded-for", "")
    real_ip = fwd.split(",")[0].strip() if fwd else ip
    if real_ip not in allowed and ip not in allowed:
        raise HTTPException(403, "Bu IP manzilga ruxsat yo'q")


def _key_ok(x_vendor_key: str | None) -> bool:
    return bool(x_vendor_key) and hmac.compare_digest(x_vendor_key, settings.vendor_admin_key)


def _totp_ok(code: str | None) -> bool:
    """RFC 6238 TOTP (SHA-1, 30s, 6 raqam), ±1 oyna. Sir bo'sh bo'lsa — 2FA o'chiq (True)."""
    secret = settings.vendor_totp_secret.strip().replace(" ", "").upper()
    if not secret:
        return True
    if not code or not code.strip().isdigit():
        return False
    try:
        key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    except Exception:
        return False
    counter = int(time.time() // 30)
    want = code.strip().zfill(6)
    for w in (counter - 1, counter, counter + 1):
        h = hmac.new(key, struct.pack(">Q", w), hashlib.sha1).digest()
        o = h[-1] & 0x0F
        val = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000
        if hmac.compare_digest(f"{val:06d}", want):
            return True
    return False


def _mint_session(hours: int = 12) -> str:
    """Kalit (+2FA) tekshirilgach beriladigan qisqa muddatli imzolangan sessiya tokeni."""
    exp = str(int(time.time()) + hours * 3600)
    sig = hmac.new(settings.vendor_admin_key.encode(), exp.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(exp.encode()).decode().rstrip("=") + "." + sig


def _session_ok(tok: str | None) -> bool:
    if not tok or "." not in tok:
        return False
    b64, sig = tok.split(".", 1)
    try:
        exp = int(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode())
    except Exception:
        return False
    if exp < int(time.time()):
        return False
    good = hmac.new(settings.vendor_admin_key.encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig)


def require_vendor(
    request: Request,
    x_vendor_key: str | None = Header(default=None, alias="X-Vendor-Key"),
    x_vendor_session: str | None = Header(default=None, alias="X-Vendor-Session"),
):
    if not settings.vendor_admin_key:
        raise HTTPException(503, "Vendor admin o'chirilgan (VENDOR_ADMIN_KEY sozlanmagan)")
    _check_vendor_ip(request)
    # 1) Imzolangan sessiya tokeni — /admin/login orqali (kalit + 2FA) olingan. Har doim qabul.
    if _session_ok(x_vendor_session):
        return True
    # 2) Kalit bilan to'g'ridan-to'g'ri — FAQAT 2FA O'CHIQ bo'lganда (API/curl/testlar uchun).
    #    2FA yoqilса, kalit yetмaydi — avval /admin/login orqali OTP bilan sessiya olinadi.
    if not settings.vendor_2fa_on and _key_ok(x_vendor_key):
        return True
    if settings.vendor_2fa_on and _key_ok(x_vendor_key):
        raise HTTPException(401, "2FA yoqilgan — /admin/login orqali OTP bilan kiring")
    raise HTTPException(401, "Vendor kaliti noto'g'ri")


class VendorLoginIn(BaseModel):
    otp: str | None = None


@router.post("/login")
def vendor_login(
    data: VendorLoginIn,
    request: Request,
    x_vendor_key: str | None = Header(default=None, alias="X-Vendor-Key"),
):
    """Portalга kirish: kalit (+2FA yoqilса OTP) tekshiriladi, qisqa muddatли sessiya tokeni beriladi."""
    if not settings.vendor_admin_key:
        raise HTTPException(503, "Vendor admin o'chirilgan")
    _check_vendor_ip(request)
    if not _key_ok(x_vendor_key):
        raise HTTPException(401, "Vendor kaliti noto'g'ri")
    if settings.vendor_2fa_on:
        if not (data.otp or "").strip():
            raise HTTPException(401, "2FA kodini kiriting (Google Authenticator)")
        if not _totp_ok(data.otp):
            raise HTTPException(401, "OTP kodi noto'g'ri")
    return {"ok": True, "session": _mint_session(), "totp": settings.vendor_2fa_on}


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
    from app.core.validate import valid_phone
    if not phone or not valid_phone(phone):
        raise HTTPException(400, "owner_phone noto'g'ri. Masalan: +996 700 123 456")
    if not code.isalnum():  # do'kon kodi faqat harf/raqam (URL/login uchun xavfsiz)
        raise HTTPException(400, "company_code faqat harf va raqamlardan iborat bo'lsin")
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
    # Yangi do'kon egasi — 'ega' roli (eng yuqori). Ega topilmasa administratorга tushamiz (moslik).
    role = (db.query(Role).filter(Role.code == "ega").first()
            or db.query(Role).filter(Role.code == "administrator").first())
    if not role:
        raise HTTPException(500, "Rol topilmadi — avval seed/initdb ishga tushiring")

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


# ═══════════════ VENDOR PORTAL — do'konlar (tenant) boshqaruvi + statistika ═══════════════
_NV = Sale.status != SaleStatus.voided


def _parse_cid(company_id: str):
    import uuid as _uuid
    try:
        return _uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(400, "company_id noto'g'ri")


def _suspended_set(db: Session) -> set:
    """Barcha to'xtatilgan do'konlar (Setting key='suspended', value.on=True) — bir so'rovda."""
    return {s.company_id for s in db.query(Setting).filter(Setting.key == "suspended").all()
            if (s.value or {}).get("on")}


def _is_suspended(db: Session, cid) -> bool:
    s = db.query(Setting).filter(Setting.company_id == cid, Setting.key == "suspended").first()
    return bool(s and (s.value or {}).get("on"))


@router.get("/overview")
def admin_overview(_: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Global ko'rsatkichlar: do'konlar, faol (30 kun), jami tushum, xodimlar."""
    now = datetime.now(timezone.utc)
    d30 = now - timedelta(days=30)
    total_companies = db.query(func.count(Company.id)).filter(Company.deleted_at.is_(None)).scalar()
    total_sales = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(_NV).scalar())
    sales_30d = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(_NV, Sale.sold_at >= d30).scalar())
    employees = db.query(func.count(Employee.id)).filter(Employee.deleted_at.is_(None)).scalar()
    active_30d = db.query(func.count(func.distinct(Sale.company_id))).filter(_NV, Sale.sold_at >= d30).scalar()
    return {
        "companies": int(total_companies or 0),
        "active_30d": int(active_30d or 0),
        "total_sales": total_sales,
        "sales_30d": sales_30d,
        "employees": int(employees or 0),
    }


@router.get("/companies")
def admin_companies(_: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Barcha do'konlar (tenant) + har biri bo'yicha statistika."""
    comps = db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.created_at.desc().nullslast()).all()
    now = datetime.now(timezone.utc)
    d30 = now - timedelta(days=30)

    def _grp(query):
        return {row[0]: row[1:] for row in query}

    sales = _grp(db.query(Sale.company_id, func.coalesce(func.sum(Sale.total), 0),
                          func.count(Sale.id), func.max(Sale.sold_at)).filter(_NV).group_by(Sale.company_id).all())
    s30 = {cid: float(t or 0) for cid, t in db.query(Sale.company_id, func.sum(Sale.total)).filter(_NV, Sale.sold_at >= d30).group_by(Sale.company_id).all()}
    emps = {cid: int(n) for cid, n in db.query(Employee.company_id, func.count(Employee.id)).filter(Employee.deleted_at.is_(None)).group_by(Employee.company_id).all()}
    prods = {cid: int(n) for cid, n in db.query(Product.company_id, func.count(Product.id)).filter(Product.deleted_at.is_(None)).group_by(Product.company_id).all()}
    brs = {cid: int(n) for cid, n in db.query(Branch.company_id, func.count(Branch.id)).filter(Branch.deleted_at.is_(None)).group_by(Branch.company_id).all()}
    plans = {s.company_id: (s.value or {}).get("plan") for s in db.query(Setting).filter(Setting.key == "plan").all()}
    suspended = _suspended_set(db)
    owners: dict = {}
    for e in db.query(Employee).filter(Employee.deleted_at.is_(None), Employee.password_hash.isnot(None)).all():
        if e.role.code == "administrator" and e.company_id not in owners:
            owners[e.company_id] = {"name": e.full_name, "phone": e.phone}

    out = []
    for c in comps:
        s = sales.get(c.id, (0, 0, None))
        out.append({
            "id": str(c.id), "name": c.name, "code": c.code, "currency": c.currency,
            "plan": plans.get(c.id) or "start",
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "branches": brs.get(c.id, 0), "employees": emps.get(c.id, 0), "products": prods.get(c.id, 0),
            "sales_total": float(s[0] or 0), "tx": int(s[1] or 0),
            "last_sale": s[2].isoformat() if s[2] else None,
            "sales_30d": s30.get(c.id, 0.0),
            "owner": owners.get(c.id),
            "suspended": c.id in suspended,
        })
    return {"companies": out}


@router.get("/companies/{company_id}")
def admin_company_detail(company_id: str, _: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Bitta do'kon batafsili: xodimlar, so'nggi savdolar, kunlik dinamika (30 kun)."""
    import uuid as _uuid
    try:
        cid = _uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(400, "company_id noto'g'ri")
    c = db.get(Company, cid)
    if not c or c.deleted_at is not None:
        raise HTTPException(404, "Do'kon topilmadi")
    now = datetime.now(timezone.utc)
    d30 = now - timedelta(days=30)
    emps = db.query(Employee).filter(Employee.company_id == cid, Employee.deleted_at.is_(None)).all()
    employees = [{"name": e.full_name, "phone": e.phone, "role": e.role.code, "status": e.status.value} for e in emps]
    recent = db.query(Sale).filter(Sale.company_id == cid, _NV).order_by(Sale.sold_at.desc()).limit(10).all()
    recent_sales = [{"receipt_no": r.receipt_no, "at": r.sold_at.isoformat() if r.sold_at else None, "total": float(r.total)} for r in recent]
    # 30 kunlik kunlik tushum
    rows = db.query(func.date(Sale.sold_at), func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.company_id == cid, _NV, Sale.sold_at >= d30).group_by(func.date(Sale.sold_at)).all()
    daily = [{"date": str(d), "sales": float(t or 0)} for d, t in rows]
    total = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(Sale.company_id == cid, _NV).scalar())
    plan_s = db.query(Setting).filter(Setting.company_id == cid, Setting.key == "plan").first()
    return {
        "id": str(c.id), "name": c.name, "code": c.code, "currency": c.currency,
        "plan": (plan_s.value or {}).get("plan") if plan_s else "start",
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "total_sales": total,
        "suspended": _is_suspended(db, cid),
        "employees": employees,
        "recent_sales": recent_sales,
        "daily": daily,
    }


class PlanIn(BaseModel):
    plan: str


@router.patch("/companies/{company_id}/plan")
def admin_set_plan(company_id: str, data: PlanIn, _: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Do'kon tarifini o'zgartirish."""
    import uuid as _uuid
    try:
        cid = _uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(400, "company_id noto'g'ri")
    plan = data.plan.strip().lower()
    if plan not in _PLANS:
        raise HTTPException(400, "plan: start | start+ | business")
    c = db.get(Company, cid)
    if not c or c.deleted_at is not None:
        raise HTTPException(404, "Do'kon topilmadi")
    s = db.query(Setting).filter(Setting.company_id == cid, Setting.key == "plan").first()
    if s:
        s.value = {"plan": plan}
    else:
        db.add(Setting(company_id=cid, key="plan", value={"plan": plan}))
    db.commit()
    return {"ok": True, "plan": plan}


class SuspendIn(BaseModel):
    suspended: bool


@router.patch("/companies/{company_id}/suspend")
def admin_suspend(company_id: str, data: SuspendIn, _: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Do'konni vaqtincha to'xtatish/qayta yoqish. To'xtatilganда login bloklanadi (403).

    Ma'lumot O'CHIRILMAYDI — faqat kirish yopiladi (to'lov kechikkanда va h.k.). Setting flag."""
    cid = _parse_cid(company_id)
    c = db.get(Company, cid)
    if not c or c.deleted_at is not None:
        raise HTTPException(404, "Do'kon topilmadi")
    s = db.query(Setting).filter(Setting.company_id == cid, Setting.key == "suspended").first()
    if data.suspended:
        if s:
            s.value = {"on": True}
        else:
            db.add(Setting(company_id=cid, key="suspended", value={"on": True}))
    elif s:
        db.delete(s)
    db.commit()
    return {"ok": True, "suspended": data.suspended}


@router.delete("/companies/{company_id}")
def admin_delete_company(company_id: str, _: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """Do'konni o'chirish — YUMSHOQ (soft): deleted_at o'rnatiladi, ma'lumot bazada qoladi
    va tiklash mumkin. Barcha so'rovlar deleted_at.is_(None) bo'yicha filtrlaydi; login yopiladi."""
    cid = _parse_cid(company_id)
    c = db.get(Company, cid)
    if not c or c.deleted_at is not None:
        raise HTTPException(404, "Do'kon topilmadi")
    c.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "deleted": True}


class SeedDemoIn(BaseModel):
    days_from: int = Field(default=180, ge=1, le=400)
    days_to: int = Field(default=0, ge=0, le=399)
    setup: bool = False
    finalize: bool = False


@router.post("/companies/{company_id}/seed-demo")
def admin_seed_demo(company_id: str, data: SeedDemoIn, _: bool = Depends(require_vendor), db: Session = Depends(get_db)):
    """TEST/DEMO do'konga ORQAGA SANALGAN tarix qo'shadi (sotuv + smena + ombor harakati).
    Xavfsizlik: FAQAT kodi 'test'/'demo' bilan boshlanadigan do'konga (haqiqiy do'kon himoyalanadi).
    Bo'laklab chaqiriladi: birinchi (eng eski) bo'lak setup=true, oxirgi bo'lak finalize=true."""
    cid = _parse_cid(company_id)
    c = db.get(Company, cid)
    if not c or c.deleted_at is not None:
        raise HTTPException(404, "Do'kon topilmadi")
    code = (c.code or "").lower()
    if not (code.startswith("test") or code.startswith("demo")):
        raise HTTPException(400, "Faqat 'test'/'demo' kodli do'konga ruxsat (haqiqiy do'kon himoyalangan)")
    if data.days_from <= data.days_to:
        raise HTTPException(400, "days_from > days_to bo'lishi kerak")
    from app.services.demo_seed import seed_chunk
    res = seed_chunk(db, c, data.days_from, data.days_to, setup=data.setup, finalize=data.finalize)
    return {"ok": True, **res}
