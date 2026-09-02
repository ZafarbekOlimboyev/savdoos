import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.deps import effective_permissions, get_current_employee
from app.core.security import create_access_token, hash_password, norm_phone, verify_password
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import EmployeeStatus
from app.models.org import Company
from app.schemas.auth import ChangePassword, EmployeeOut, LoginPassword, LoginPin, Token

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Brute-force himoya: sliding-window (xotirada; Railway 1 instans, ko'p instansда Redis).
# IKKI qatlam: (1) IP bo'yicha — bitta manbadan ko'p urinishga qarshi;
# (2) HISOB bo'yicha (IP'дан mustaqil) — attacker IP almashtirsa ham bitta hisob/do'kon
#     bloklanadi (distributed brute-force'га qarshi). Ikkalasidan biri oshsa — 429.
_ATTEMPTS: dict[str, list[float]] = {}

# Tier'lar: (max_fails, window_seconds, xabar)
_IP = (10, 300.0, "Juda ko'p urinish — 5 daqiqadan keyin qayta urining")
_ACCT = (12, 900.0, "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring")
_STORE = (25, 900.0, "Juda ko'p urinish — 15 daqiqadan keyin urinib ko'ring")


_MAX_WINDOW = 900.0   # eng uzun tier oynasi
_last_sweep = [0.0]


def _sweep(now: float):
    """Eskirgan kalitlarni tozalaydi — aks holда attacker turli company_code/phone yuborib
    _ATTEMPTS lug'atini cheksiz o'stirib xotirani tugatishi mumkin edi (memory-DoS)."""
    if now - _last_sweep[0] < 60:   # har 60 soniyada bir marta (arzon)
        return
    _last_sweep[0] = now
    dead = [k for k, ts in _ATTEMPTS.items() if not ts or now - max(ts) >= _MAX_WINDOW]
    for k in dead:
        _ATTEMPTS.pop(k, None)


def _guard(key: str, tier: tuple):
    max_fails, window, msg = tier
    now = time.time()
    _sweep(now)
    fails = [t for t in _ATTEMPTS.get(key, []) if now - t < window]
    # BO'SH ro'yxatni SAQLAMAYMIZ — har (ehtimol soxta) kalit uchun abadiy yozuv qolmasin.
    if fails:
        _ATTEMPTS[key] = fails
    else:
        _ATTEMPTS.pop(key, None)
    if len(fails) >= max_fails:
        raise HTTPException(429, msg)


def _rate_fail(*keys: str):
    now = time.time()
    for k in keys:
        _ATTEMPTS.setdefault(k, []).append(now)


def _rate_ok(*keys: str):
    for k in keys:
        _ATTEMPTS.pop(k, None)


def _client_ip(request) -> str:
    """HAQIQIY mijoz IP'si. Railway edge proxy ortida request.client.host DOIM proxy IP (barcha
    mijoz uchun BIR XIL) — shu bois rate-limit IP kaliti GLOBAL bo'lib qolib, bitta attacker 10 xato
    bilan BARCHA tenantларни login'дан bloklardi (cross-tenant DoS). Ishonchli proxy XFF'ning ENG
    O'NG qismiga haqiqiy peer'ni qo'shadi (admin._check_vendor_ip bilan izchil)."""
    fwd = request.headers.get("x-forwarded-for", "") if request else ""
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if (request and request.client) else "?"


def _is_suspended(db: Session, company_id) -> bool:
    """Vendor do'konni vaqtincha to'xtatganmi (Setting key='suspended')."""
    from app.models.settings import Setting
    s = db.query(Setting).filter(Setting.company_id == company_id, Setting.key == "suspended").first()
    return bool(s and (s.value or {}).get("on"))


_SUSPENDED_MSG = "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning."


def employee_out(e: Employee, db: Session) -> EmployeeOut:
    comp = db.get(Company, e.company_id)
    return EmployeeOut(
        id=e.id,
        full_name=e.full_name,
        phone=e.phone,
        role_code=e.role.code,
        role_name=e.role.name,
        status=e.status.value,
        company_name=comp.name if comp else None,
        permissions=sorted(effective_permissions(e, db)),
    )


def _token(e: Employee, db: Session) -> Token:
    token = create_access_token(str(e.id), {
        "role": e.role.code,
        "company_id": str(e.company_id),
        "sv": int(e.sec_epoch or 0),  # token bekor qilish davri (parol/chiqishда oshadi)
    })
    return Token(access_token=token, employee=employee_out(e, db))


# Telefon MAVJUD emasligини javob vaqtidan bilib olishга yo'l qo'ymaslik uchun (timing enumeration),
# nomzod topilmasa ham bir marta soxta bcrypt qiyoslash bajaramiz — ikkala yo'l bir xil vaqt oladi.
_DUMMY_HASH = hash_password("savdoos-timing-guard")


@router.post("/login", response_model=Token)
def login_pin(data: LoginPin, request: Request, db: Session = Depends(get_db)):
    """Kassir PIN login — FAQAT bitta do'kon (company_code) doirasida tekshiriladi.

    Kod berilsa — o'sha do'kon xodimlari orasidan qidiradi. Berilmasa — faqat bazada
    bitta kompaniya bo'lgandagina ruxsat (eski o'rnatmalar bilan moslik); ko'p bo'lsa
    company_code talab qilinadi (aks holda boshqa do'konga kirib ketish xavfi)."""
    ip = _client_ip(request)
    # IP kaliti KODdan MUSTAQIL — aks holda har yangi (soxta) kod yangi bo'sh kalit ochib,
    # do'kon-kodi enumeratsiyasi rate-limitni butunlay chetlab o'tardi.
    ipk = f"pin-ip:{ip}"
    _guard(ipk, _IP)

    if data.company_code:
        comp = (
            db.query(Company)
            .filter(Company.code == data.company_code.strip().lower(), Company.deleted_at.is_(None))
            .first()
        )
        if not comp:
            _rate_fail(ipk)  # kod terish (enumeratsiya) ham xato sifatida sanaladi
            raise HTTPException(401, "Do'kon kodi topilmadi")
        company_id = comp.id
    else:
        comp_ids = db.query(Company.id).filter(Company.deleted_at.is_(None)).all()
        if len(comp_ids) > 1:
            raise HTTPException(400, "Do'kon kodi kerak (company_code)")
        if not comp_ids:
            raise HTTPException(401, "Do'kon topilmadi")  # fail-closed: filtrsiz qidirmaymiz
        company_id = comp_ids[0][0]

    # Hisob (do'kon) qatlami — IP almashtirilса ham bitta do'kon PIN'iga hujum bloklanadi
    storek = f"pin-store:{company_id}"
    _guard(storek, _STORE)

    q = db.query(Employee).filter(
        Employee.company_id == company_id,
        Employee.pin_hash.isnot(None),
        Employee.deleted_at.is_(None),
        Employee.status == EmployeeStatus.active,  # to'xtatilgan/bo'shatilgan kira olmaydi
    )
    for e in q.all():
        if verify_password(data.pin, e.pin_hash):
            # Suspend tekshiruvi PIN TASDIQLANGACH (parol oqimi bilan izchil) — aks holda
            # kredensialsiz har kim (faqat do'kon kodini bilib) suspend holatини bilib olardi.
            if _is_suspended(db, company_id):
                _rate_ok(ipk)
                raise HTTPException(403, _SUSPENDED_MSG)
            # MUHIM: muvaffaqiyatda faqat IP kalitini tozalaymiz. Do'kon-darajali hisoblagich
            # SAQLANADI — aks holda insider "9 xato + o'z PIN'i bilan 1 kirish" sikli bilan
            # hisoblagichni nolga tushirib, hamkasb PIN'ini cheksiz brute-force qilardi.
            _rate_ok(ipk)
            return _token(e, db)
    _rate_fail(ipk, storek)
    raise HTTPException(401, "PIN noto'g'ri")


@router.post("/login/password", response_model=Token)
def login_password(data: LoginPassword, request: Request, db: Session = Depends(get_db)):
    """Egа/admin login — telefon + parol. Telefon global noyob (parolli akkaunt uchun)."""
    phone = norm_phone(data.phone)
    if not phone:
        raise HTTPException(401, "Telefon yoki parol noto'g'ri")  # bo'sh-normallashgan telefon match bo'lmasin
    ip = _client_ip(request)
    ipk = f"pw-ip:{ip}"
    acctk = f"pw-acct:{phone}"       # IP'дан mustaqil — bitta telefonга distributed hujum bloklanadi
    _guard(ipk, _IP)
    _guard(acctk, _ACCT)
    candidates = (
        db.query(Employee)
        .filter(
            Employee.phone == phone,
            Employee.password_hash.isnot(None),
            Employee.deleted_at.is_(None),
        )
        .all()
    )
    for e in candidates:
        if verify_password(data.password, e.password_hash):
            if e.status != EmployeeStatus.active:
                break  # faol emas — parol to'g'ri ekanini OSHKOR QILMAYMIZ (umumiy xato)
            comp = db.get(Company, e.company_id)
            if not comp or comp.deleted_at is not None:
                break  # o'chirilgan do'kon — umumiy xato bilan yashiramiz
            if _is_suspended(db, e.company_id):
                # to'g'ri parol tasdiqlandi — bloklashni tozalab, aniq sabab beramiz
                _rate_ok(ipk, acctk)
                raise HTTPException(403, _SUSPENDED_MSG)
            _rate_ok(ipk, acctk)
            return _token(e, db)
    if not candidates:
        # Telefon ro'yxatda yo'q — bcrypt ishga tushmagan bo'lardi; javob vaqti ochib
        # qo'ymasligi uchun soxta qiyoslash qilamiz (timing enumeration'га qarshi).
        verify_password(data.password, _DUMMY_HASH)
    _rate_fail(ipk, acctk)
    raise HTTPException(401, "Telefon yoki parol noto'g'ri")


@router.post("/password")
def change_password(
    data: ChangePassword,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Foydalanuvchi o'z parolini o'zgartiradi. Mavjud parol bo'lsa — eskisini tasdiqlaydi."""
    new = data.new_password or ""
    if len(new) < 6:
        raise HTTPException(400, "Yangi parol kamida 6 belgi bo'lishi kerak")
    rk = f"chpw:{emp.id}"           # eski parolni cheksiz taxmin qilishga yo'l qo'ymaymiz
    _guard(rk, _ACCT)
    if emp.password_hash:
        if not data.old_password or not verify_password(data.old_password, emp.password_hash):
            _rate_fail(rk)
            raise HTTPException(401, "Joriy parol noto'g'ri")
    _rate_ok(rk)
    # PIN-only akkaunt parolli akkauntga aylanayotgan bo'lsa — telefon GLOBAL noyob bo'lishi shart
    # (aks holda ux_employees_phone_pw partial-unique indeksi xom 500 berardi; edit_employee bilan izchil).
    if not emp.password_hash:
        if not emp.phone:
            raise HTTPException(400, "Parol o'rnatish uchun avval telefon (login) qo'shilishi kerak")
        _clash = db.query(Employee).filter(
            Employee.phone == emp.phone, Employee.password_hash.isnot(None),
            Employee.deleted_at.is_(None), Employee.id != emp.id).first()
        if _clash:
            raise HTTPException(409, "Bu telefon boshqa akkauntda band")
    emp.password_hash = hash_password(new)
    # Parol o'zgardi — barcha ESKI tokenlar bekor bo'lsin (o'g'irlangan/boshqa qurilma sessiyalari).
    emp.sec_epoch = int(emp.sec_epoch or 0) + 1
    db.commit()
    db.refresh(emp)
    # Joriy qurilma chiqib qolmasligi uchun yangi (amaldagi) token qaytaramiz — mijoz uni almashtiradi.
    return {"ok": True, "access_token": create_access_token(str(emp.id), {
        "role": emp.role.code, "company_id": str(emp.company_id), "sv": int(emp.sec_epoch or 0),
    })}


@router.post("/logout")
def logout(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """Server tomonda chiqish — sec_epoch oshadi, shu xodimning HAMMA tokeni bekor bo'ladi.
    (O'g'irlangan token endi mahalliy 'chiqish' bilan ham amalda bekor qilinadi.)"""
    emp.sec_epoch = int(emp.sec_epoch or 0) + 1
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=EmployeeOut)
def me(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    return employee_out(emp, db)
