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
import uuid
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
from app.models.vendor import VendorAuthAttempt, VendorSession

router = APIRouter(prefix="/admin", tags=["admin"])

# Vendor portal HTML (statik "qobiq" — barcha ma'lumot X-Vendor-Key bilan yuklanadi).
_PORTAL_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "vendor_portal.html")


@router.get("/portal", include_in_schema=False)
def vendor_portal():
    return FileResponse(_PORTAL_HTML, media_type="text/html")

_PLANS = ("start", "start+", "business")
_PAYMENTS = [("cash", "Naqd", True), ("card", "Karta", True), ("qr", "QR", True), ("credit", "Qarz", True)]


# ══ VENDOR XAVFSIZLIGI ══════════════════════════════════════════════════════
#
# TAHDID. `VENDOR_ADMIN_KEY` — CROSS-TENANT kalit: u bilan istalgan do'konni
# yaratish, tarifini o'zgartirish, to'xtatish, parolini tiklash va O'CHIRISH mumkin.
# Uning sizishi butun ko'p-ijarachi tizim sizishi demak. Shu bois production'da u
# YOLG'IZ yetarli bo'lmasligi kerak.
#
# ISHGA TUSHIRISH oqimi:
#     master kalit + MAJBURIY OTP + ruxsat etilgan IP
#          -> qisqa muddatli, BEKOR QILINADIGAN sessiya
#          -> vendor amallari
#
# Production'da `require_vendor` FAQAT sessiyani qabul qiladi. Dev/test'da
# (2FA o'chiq bo'lganda) xom kalit ham o'tadi — bu ATAYLAB va faqat production
# BO'LMAGAN muhitda; `security_config` production'da 2FA yo'qligini KRITIK deb
# belgilaydi, ya'ni bunday production umuman ishga tushmaydi.

# Rate-limit qatlamlari. Chegara oyna bilan belgilangan, ya'ni blok DOIMIY EMAS —
# u o'z-o'zidan tugaydi (operator o'zini abadiy qulflab qo'ymasligi kerak).
_VENDOR_IP_TIER = (5, 900)        # bitta manbadan 15 daqiqada 5 xato
_VENDOR_FLOW_TIER = (20, 3600)    # butun oqim bo'yicha 1 soatda 20 xato

# Bir xil javob. Kalit noto'g'ri, OTP noto'g'ri, sessiya eskirgan yoki bekor
# qilingan — TASHQARIDAN farq qilmaydi. Ilgari 401 matni "kalit noto'g'ri" va
# "2FA yoqilgan, OTP kiriting" deb farqlanardi: bu autentifikatsiyasiz, cheklovsiz
# ORACLE edi — hujumchi OTP'ni bilmasdan turib kalitni taxmin qilishni avtomatlashtira
# olardi va to'g'ri topganini darhol bilardi.
_VENDOR_401 = "Vendor autentifikatsiyasi muvaffaqiyatsiz"


def _vendor_denied(db, bucket_ip: str, reason: str):
    """Bir xil 401 + urinishni qayd etish. Sabab FAQAT ichkarida saqlanadi."""
    _rate_record(db, bucket_ip, reason)
    return HTTPException(401, _VENDOR_401)


def _source_ip(request: Request) -> str:
    """HAQIQIY manba IP — ISHONCHLI proxy modeliga muvofiq.

    Railway edge proxy so'rovni uzatishda haqiqiy peer IP'ni `X-Forwarded-For`
    ning ENG O'NG qismiga qo'shadi. Mijoz o'zi XFF yuborsa (soxta), u CHAP tomonda
    qoladi. Shuning uchun eng chap emas, eng O'NG qiymat olinadi — aks holda
    hujumchi `X-Forwarded-For: <ruxsat-etilgan-IP>` yuborib allowlist'ni chetlab
    o'tardi. IPv6 qiymatlari qavssiz keladi va shundayligicha solishtiriladi."""
    fwd = (request.headers.get("x-forwarded-for") or "").strip()
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else ""


def _check_vendor_ip(request: Request):
    """IP allowlist. Production'da MAJBURIY (`security_config` buni kafolatlaydi)."""
    allowed = settings.vendor_ip_list
    if not allowed:
        # Production'da bu holat boot'da to'xtatilgan bo'ladi; dev'da cheklov yo'q.
        return
    if _source_ip(request) not in allowed:
        raise HTTPException(403, "Bu IP manzilga ruxsat yo'q")


def _key_ok(x_vendor_key: str | None) -> bool:
    if not x_vendor_key or not settings.vendor_admin_key:
        return False
    try:
        return hmac.compare_digest(x_vendor_key, settings.vendor_admin_key)
    except TypeError:
        # ASCII bo'lmagan sarlavha `compare_digest` da TypeError berardi va u
        # ushlanmasdan 500 ga aylanardi — noto'g'ri kalit 401 bo'lishi kerak.
        return False


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


# ── Rate limit — UMUMIY holat (Postgres) ────────────────────────────────────
#
# ⚠️  JARAYON XOTIRASIDA EMAS. Xotiradagi hisoblagich har deploy'da nolga tushadi
#     va instanslar o'rtasida bo'linmaydi — ya'ni hujumchi deploy kutib yoki boshqa
#     instansga urib chetlab o'tardi. Redis loyihada YO'Q (paket ham, servis ham),
#     shu bois mavjud Postgres ishlatiladi: u qayta ishga tushishdan omon qoladi
#     va umumiy. Vendor autentifikatsiyasi kam chastotali, shuning uchun har
#     urinishga bitta yozuv qimmat emas.

def _rate_record(db, bucket: str, reason: str) -> None:
    """Muvaffaqiyatsiz urinishni qayd etadi. SIR yozilmaydi — faqat turkum."""
    db.add(VendorAuthAttempt(bucket=bucket, reason=reason,
                             occurred_at=datetime.now(timezone.utc)))
    db.commit()


def _rate_guard(db, bucket: str, tier: tuple[int, int]) -> None:
    """Chegara oshsa 429. Blok oyna bilan cheklangan — abadiy emas."""
    max_fails, window = tier
    since = datetime.now(timezone.utc) - timedelta(seconds=window)
    n = (db.query(VendorAuthAttempt)
         .filter(VendorAuthAttempt.bucket == bucket,
                 VendorAuthAttempt.occurred_at >= since)
         .count())
    if n >= max_fails:
        raise HTTPException(429, f"Juda ko'p urinish — {window // 60} daqiqadan keyin urining")


def _vendor_rate_check(db, request: Request) -> str:
    """Ikkala o'lchov ham tekshiriladi; IP bucket qaytariladi.

    Baza ishlamasa — FAIL-CLOSED (503). Vendor autentifikatsiyasi cross-tenant,
    shuning uchun himoyani o'lchay olmagan holatda kirishga ruxsat berilmaydi.
    Bu ataylab: jimgina fail-open bu yerda butun tizimni ochib qo'yardi."""
    ip = _source_ip(request) or "unknown"
    bucket_ip = f"ip:{ip}"
    try:
        _rate_guard(db, bucket_ip, _VENDOR_IP_TIER)
        _rate_guard(db, "flow:vendor", _VENDOR_FLOW_TIER)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "Xavfsizlik cheklovini tekshirib bo'lmadi") from e
    return bucket_ip


# ── Sessiya — BEKOR QILINADIGAN ─────────────────────────────────────────────

def _session_key() -> bytes:
    """Sessiya imzo kaliti — vendor_admin_key VA TOTP sirini birlashtiramiz.

    Aks holda FAQAT vendor_admin_key sizgan hujumchi sessiyani o'zi hisoblab, OTP'siz
    soxta sessiya yasab 2FA'ni butunlay chetlab o'tardi. Ikkalasidan birini almashtirish
    esa mavjud BARCHA sessiyalarni bekor qiladi (kalit rotatsiyasi = umumiy chiqish)."""
    secret = (settings.vendor_totp_secret or "").strip()
    return (settings.vendor_admin_key + "|" + secret).encode()


def _mint_session(db, request: Request, hours: int | None = None) -> str:
    """Kalit (+2FA) tekshirilgach beriladigan qisqa muddatli sessiya.

    Token ichida `jti` bor va u bazada qayd etiladi — ya'ni ALOHIDA bekor qilinadi.
    Ilgari token faqat `exp` dan iborat edi: o'g'irlangan token 12 soat ishlayverardi
    va uni to'xtatishning yagona yo'li master kalitni almashtirish edi."""
    ttl = int(hours if hours is not None else settings.vendor_session_hours)
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4()
    exp = now + timedelta(hours=ttl)
    db.add(VendorSession(jti=jti, issued_at=now, expires_at=exp,
                         created_ip=(_source_ip(request) or None)[:64] if _source_ip(request) else None))
    db.commit()
    payload = f"{jti}|{int(exp.timestamp())}"
    sig = hmac.new(_session_key(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + sig


def _as_utc(dt):
    """Naive datetime'ni UTC deb talqin qiladi.

    ⚠️  SQLite `tzinfo` ni SAQLAMAYDI, shuning uchun `DateTime(timezone=True)`
        ustuni ham naive qiymat qaytaradi. Naive qiymatda `.timestamp()` uni
        MAHALLIY vaqt deb hisoblaydi — UTC+5 mashinada bu 5 soatlik siljish
        beradi va 2 soatlik sessiya DARHOL "eskirgan" bo'lib qolardi. Postgres'da
        bu muammo yo'q, ya'ni nosozlik faqat SQLite'da (dev/test) ko'rinardi."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _session_row(db, tok: str | None):
    """Tokenni tekshiradi va AMALDAGI sessiya qatorini qaytaradi (yo'q bo'lsa None)."""
    if not tok or "." not in tok:
        return None
    b64, sig = tok.split(".", 1)
    try:
        payload = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()
        jti_s, exp_s = payload.split("|", 1)
        jti, exp = uuid.UUID(jti_s), int(exp_s)
    except Exception:
        return None
    good = hmac.new(_session_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig):
        return None
    if exp < int(time.time()):
        return None
    row = db.get(VendorSession, jti)
    if row is None or row.revoked_at is not None:
        return None                      # BEKOR QILINGAN yoki noma'lum — imzo yetarli emas
    exp_at = _as_utc(row.expires_at)
    if exp_at and exp_at.timestamp() < time.time():
        return None
    return row


def require_vendor(
    request: Request,
    db: Session = Depends(get_db),
    x_vendor_key: str | None = Header(default=None, alias="X-Vendor-Key"),
    x_vendor_session: str | None = Header(default=None, alias="X-Vendor-Session"),
):
    if not settings.vendor_admin_key:
        raise HTTPException(503, "Vendor admin o'chirilgan (VENDOR_ADMIN_KEY sozlanmagan)")
    _check_vendor_ip(request)
    bucket_ip = _vendor_rate_check(db, request)

    # 1) Imzolangan va BAZADA amaldagi sessiya — asosiy yo'l.
    row = _session_row(db, x_vendor_session)
    if row is not None:
        row.last_seen_at = datetime.now(timezone.utc)
        db.commit()
        return True

    # 2) Xom kalit — FAQAT production BO'LMAGAN muhitda va 2FA o'chiq bo'lganda.
    #    Production'da uzoq umrli master kalit oddiy avtorizatsiya kredensiali
    #    sifatida QABUL QILINMAYDI: u faqat /admin/login orqali sessiya olish uchun.
    if not settings.is_production and not settings.vendor_2fa_on and _key_ok(x_vendor_key):
        return True

    raise _vendor_denied(db, bucket_ip, "session" if x_vendor_session else "key")


class VendorLoginIn(BaseModel):
    otp: str | None = None


@router.post("/login")
def vendor_login(
    data: VendorLoginIn,
    request: Request,
    db: Session = Depends(get_db),
    x_vendor_key: str | None = Header(default=None, alias="X-Vendor-Key"),
):
    """Portalga kirish: kalit + (production'da MAJBURIY) OTP -> sessiya tokeni."""
    if not settings.vendor_admin_key:
        raise HTTPException(503, "Vendor admin o'chirilgan")
    _check_vendor_ip(request)
    bucket_ip = _vendor_rate_check(db, request)

    if not _key_ok(x_vendor_key):
        raise _vendor_denied(db, bucket_ip, "key")

    # Production'da 2FA MAJBURIY. `security_config` sirning mavjudligini boot'da
    # talab qiladi, bu yerda esa OQIM darajasida ikkinchi qatlam: sozlama qandaydir
    # yo'l bilan yo'qolsa ham production kalitni yolg'iz qabul qilmasin.
    if settings.is_production and not settings.vendor_2fa_on:
        raise HTTPException(503, "Vendor 2FA sozlanmagan — production'da kirish yopiq")

    if settings.vendor_2fa_on and not _totp_ok(data.otp):
        raise _vendor_denied(db, bucket_ip, "otp")

    tok = _mint_session(db, request)
    from app.services.audit import log as audit_log
    audit_log(db, None, "login", "vendor_session", None,
              after={"result": "ok", "ip": _source_ip(request) or None})
    db.commit()          # `audit.log` faqat `add` qiladi — yozuv commit talab qiladi
    return {"ok": True, "session": tok, "totp": settings.vendor_2fa_on}


@router.post("/logout")
def vendor_logout(
    request: Request,
    db: Session = Depends(get_db),
    x_vendor_session: str | None = Header(default=None, alias="X-Vendor-Session"),
):
    """Sessiyani BEKOR QILADI. Token darhol yaroqsiz bo'ladi."""
    row = _session_row(db, x_vendor_session)
    if row is None:
        raise HTTPException(401, _VENDOR_401)
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    from app.services.audit import log as audit_log
    audit_log(db, None, "logout", "vendor_session", None,
              after={"result": "revoked", "ip": _source_ip(request) or None})
    db.commit()
    return {"ok": True}


class ProvisionIn(BaseModel):
    company_name: str = Field(min_length=1)
    company_code: str = Field(min_length=2, max_length=40)
    owner_name: str = Field(min_length=1)
    owner_phone: str = Field(min_length=4)
    owner_password: str = Field(min_length=6)
    plan: str = "start"
    currency: str = Field(default="UZS", min_length=3, max_length=3)
    branch_name: str = "Asosiy filial"
    timezone: str | None = None  # QA SB-004: KG (+6) do'kon uchun — hisobot tz shu filialdan olinadi
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
    # QA SB-004: timezone ilgari qabul qilinmasdi — birinchi filial (hisobot tz manbai) doim
    # Asia/Tashkent bo'lib qolardi; +6 (Bishkek) do'kon hisobotlari 1 soat siljirdi.
    from app.api.v1.reports import _TZ_OFFSETS as _TZS
    _tz = (data.timezone or "Asia/Tashkent").strip()
    if _tz not in _TZS:
        raise HTTPException(400, "Noto'g'ri vaqt mintaqasi (timezone)")
    branch = Branch(company_id=company.id, code="F01",
                    name=(data.branch_name.strip() or "Asosiy filial"), timezone=_tz)
    db.add(branch)
    db.flush()
    for i, (c, n, en) in enumerate(_PAYMENTS):
        db.add(PaymentMethod(company_id=company.id, code=c, name=n, is_enabled=en, sort_order=i))
    db.add(Setting(company_id=company.id, key="plan", value={"plan": plan}))
    db.add(Setting(company_id=company.id, key="store_info",
                   value={"name": company.name, "branch": branch.name}))
    # ═══ FRESH (LEDGER-NATIVE) TENANT ═══════════════════════════════════════
    # Yangi do'kon YANGI naqd arxitekturasida BIRINCHI kunidanoq ishlaydi: `ledger_native`
    # bayrog'i + `cutover_at` = SHU lahza. Natijada post-T0 gardlari darhol FAOL bo'ladi va
    # kassa (TILL) HECH QACHON TAXMIN QILINMAYDI — har fizik naqd hodisasi AYNAN TILL/SAFE
    # talab qiladi va ledger legi bilan BIR tranzaksiyada yoziladi.
    # Bu YANGI do'kon uchun HECH NARSANI kesib o'tmaydi (kesiladigan tarix YO'Q), shu bois
    # backfill / tarixiy TILL rekonstruksiyasi / migration marosimi UMUMAN KERAK EMAS.
    from app.services.cash import tenant as _cash_tenant
    _cash_tenant.mark_ledger_native(db, company.id)
    owner = Employee(
        company_id=company.id,
        full_name=data.owner_name.strip(),
        phone=phone,
        role_id=role.id,
        password_hash=hash_password(data.owner_password),
        pin_hash=hash_password(owner_pin) if owner_pin else None,
    )
    db.add(owner)
    db.flush()
    from app.services.audit import log as audit_log
    audit_log(db, None, "create", "company", company.id,
              after={"code": code, "name": company.name, "plan": plan})  # sir YOZILMAYDI
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
        # Do'kon egasi endi 'ega' roli (migratsiyадан keyin). Egани birinchi tanlaymiz, keyin admin.
        admins = sorted([e for e in emps if e.role.code in ("ega", "administrator")],
                        key=lambda e: 0 if e.role.code == "ega" else 1)
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
    # Vendor parolni tikladi -> egaperson HAMMA eski tokeni bekor bo'lsin (change_password bilan izchil).
    target.sec_epoch = int(target.sec_epoch or 0) + 1
    from app.services.audit import log as audit_log
    audit_log(db, None, "update", "company", target.company_id, after={"password_reset": True})
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
        # Egа (do'kon egasi) endi 'ega' roli; agar yo'q bo'lsa administrator. Ega ustuvor.
        if e.role.code in ("ega", "administrator") and (e.company_id not in owners or e.role.code == "ega"):
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
    # 30 kunlik kunlik tushum — do'kon MAHALLIY kuni bo'yicha (UTC func.date emas; +5/+6 da farq).
    from app.api.v1.reports import _store_tz as _stz
    _LC = _stz(db, cid)
    _agg: dict[str, float] = {}
    for _sa, _tot in db.query(Sale.sold_at, Sale.total).filter(
            Sale.company_id == cid, _NV, Sale.sold_at >= d30).all():
        if _sa is None:
            continue
        _d = (_sa if _sa.tzinfo else _sa.replace(tzinfo=timezone.utc)).astimezone(_LC).date().isoformat()
        _agg[_d] = _agg.get(_d, 0.0) + float(_tot or 0)
    daily = [{"date": d, "sales": s} for d, s in sorted(_agg.items())]
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
    _old = (s.value or {}).get("plan") if s else None
    if s:
        s.value = {"plan": plan}
    else:
        db.add(Setting(company_id=cid, key="plan", value={"plan": plan}))
    from app.services.audit import log as audit_log
    audit_log(db, None, "update", "company", cid, before={"plan": _old}, after={"plan": plan})
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
    from app.services.audit import log as audit_log
    audit_log(db, None, "update", "company", cid, after={"suspended": data.suspended})
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
    from app.services.audit import log as audit_log
    audit_log(db, None, "delete", "company", cid, before={"name": c.name})
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

    # ── IKKINCHI GARD: do'konda HAQIQIY savdo bo'lmasin ─────────────────────
    # Kod prefiksi YOLG'IZ yetarli emas. Onboarding paytida do'konga `test-fayzan` yoki
    # `demo-market` kabi kod berish TABIIY (kodni vendor tanlaydi) — va shundan keyin bu
    # endpoint jonli do'konning omborini 6000 donaga "tiklab", oylab soxta savdo/smena/naqd
    # harakati yozib yuborardi. Ya'ni bitta chaqiruv haqiqiy hisobotlarni buzardi.
    #
    # Shu bois: do'konda ALLAQACHON savdo bo'lsa — RAD ETAMIZ. Demo seed FAQAT bo'sh
    # (hali ishlatilmagan) do'konda ma'noga ega. `setup` bo'lagida tekshiramiz: keyingi
    # bo'laklar o'zi yozgan savdolar ustidan davom etadi.
    if data.setup:
        from app.models.sales import Sale as _Sale
        _real = db.query(_Sale.id).filter(_Sale.company_id == cid).first()
        if _real is not None:
            raise HTTPException(
                409, "Bu do'konda ALLAQACHON savdo bor — demo seed RAD ETILDI. "
                     "Demo tarix faqat BO'SH do'konga qo'shiladi (aks holda haqiqiy "
                     "hisobotlar soxta ma'lumot bilan aralashib ketardi).")

    if data.days_from <= data.days_to:
        raise HTTPException(400, "days_from > days_to bo'lishi kerak")
    from app.services.demo_seed import seed_chunk
    res = seed_chunk(db, c, data.days_from, data.days_to, setup=data.setup, finalize=data.finalize)
    return {"ok": True, **res}
