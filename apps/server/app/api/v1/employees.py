import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import FULL_ACCESS_ROLES, effective_permissions, get_current_employee, require
from app.core.security import hash_password, norm_phone, verify_password
from app.db.session import get_db
from app.models.auth import Employee, EmployeePermission, Permission, Role
from app.services.audit import log as audit_log

router = APIRouter(tags=["employees"])


# Faqat Ega boshqaradigan rollar (admin/ega akkauntlarini pastroq rol tahrirlay olmaydi).
_MANAGED_ROLES = ("ega", "administrator")

# Rol darajalari — override orqali xodimlar.edit olgan PAST rol o'zidan yuqori (no-admin) rol
# yaratib/tayinlab, o'sha akkaunt orqali imtiyoz oshira olmasin (masalan kassir -> menejer).
_ROLE_RANK = {"kassir": 1, "omborchi": 2, "menejer": 3, "administrator": 4, "ega": 5}


def _check_role_ceiling(emp: Employee, target_role_code: str):
    """Tayinlanayotgan rol tayinlovchining o'z darajasidan yuqori bo'lmasin (ega/admin cheklovsiz —
    ular uchun alohida make_admin/ega qoidalari bor)."""
    if emp.role.code in FULL_ACCESS_ROLES:
        return
    if _ROLE_RANK.get(target_role_code, 99) > _ROLE_RANK.get(emp.role.code, 0):
        raise HTTPException(403, "O'z darajangizdan yuqori rol tayinlay olmaysiz")


def _can_make_admin(emp: Employee, db: Session) -> bool:
    """Boshqani ADMINISTRATOR qila oladimi: Ega doim; admin faqat Ega 'make_admin' bergan bo'lsa."""
    from app.core.deps import effective_permissions
    return emp.role.code == "ega" or "xodimlar.make_admin" in effective_permissions(emp, db)


def _active_admin_count(db: Session, company_id) -> int:
    """Do'kondagi FAOL rahbarlar (Ega + Administrator) soni — oxirgisini yo'qotib
    do'konни boshqaruvsiz/qulflangan qoldirmaslik uchun (lockout himoyasi)."""
    from app.models.enums import EmployeeStatus
    return (
        db.query(Employee)
        .join(Role, Employee.role_id == Role.id)
        .filter(
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
            Employee.status == EmployeeStatus.active,
            Role.code.in_(_MANAGED_ROLES),
        )
        .count()
    )


def _active_admin_count_locked(db: Session, company_id) -> int:
    """_active_admin_count bilan bir xil, LEKIN faol admin qatorlarini avval FOR UPDATE bilan
    qulflaydi. "Oxirgi admin" tekshiruvi check-then-act TOCTOU edi: ikki admin AYNI PAYTDA
    o'chirilsa (yoki lavozimi tushirilsa), ikkalasi ham count=2 o'qib o'tib ketib, do'kon 0
    adminli qolardi. Umumiy admin qatorlarini qulflab, bunday operatsiyalar KETMA-KET bajariladi:
    ikkinchisi birinchisi commit qilgach yangilangan (kamaygan) sonni ko'radi va to'g'ri rad
    etiladi. (SQLite'da with_for_update no-op, biroq u yozuvlarni tranzaksiya darajasida
    seriallashtiradi — u yerda ham xavfsiz.)"""
    from app.models.enums import EmployeeStatus
    ids = (
        db.query(Employee.id)
        .join(Role, Employee.role_id == Role.id)
        .filter(
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
            Employee.status == EmployeeStatus.active,
            Role.code.in_(_MANAGED_ROLES),
        )
        .order_by(Employee.id)             # barqaror tartib — deadlock oldini oladi
        .with_for_update(of=Employee)      # faqat employee qatorlarini qulflaymiz (Role emas)
        .all()
    )
    return len(ids)


def _active_ega_count_locked(db: Session, company_id) -> int:
    """FAOL 'ega' rollilar soni (FOR UPDATE bilan). Oxirgi Egani demote/deactivate/delete qilib
    bo'lmaydi — aks holda hech kim 'ega' tayinlay olmay (faqat Ega tayinlaydi), admin/ega
    boshqaruvi qulflanib qolardi (tiklash faqat vendor/restart orqali)."""
    from app.models.enums import EmployeeStatus
    ids = (
        db.query(Employee.id)
        .join(Role, Employee.role_id == Role.id)
        .filter(
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
            Employee.status == EmployeeStatus.active,
            Role.code == "ega",
        )
        .order_by(Employee.id)
        .with_for_update(of=Employee)
        .all()
    )
    return len(ids)


def _has_open_shift(db: Session, employee_id) -> bool:
    """Xodimда ochiq smena bormi — bo'lsa to'xtatib/o'chirib bo'lmaydi (aks holда smena
    yopilmay qolardi: yopish kassirning O'ZIni talab qiladi, u esa kira olmaydi)."""
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    return db.query(Shift.id).filter(
        Shift.cashier_id == employee_id, Shift.status == ShiftStatus.open).first() is not None


def _phone_taken(db: Session, phone: str, exclude_id=None) -> bool:
    """Parolli login uchun telefon global noyob bo'lishi kerak (ux_employees_phone_pw)."""
    q = db.query(Employee).filter(
        Employee.phone == phone,
        Employee.password_hash.isnot(None),
        Employee.deleted_at.is_(None),
    )
    if exclude_id is not None:
        q = q.filter(Employee.id != exclude_id)
    return db.query(q.exists()).scalar()


def _valid_phone(phone: str) -> bool:
    """Telefon formati tekshiruvi. norm_phone'дан keyin '+' + raqamlar keladi.
    +996/+998 (Qirg'iziston/O'zbekiston) — aynan 12 raqam (kod 3 + abonent 9).
    Boshqa davlat kodi — 10..15 raqam (E.164 mantiqiy oralig'i)."""
    digits = phone[1:] if phone.startswith("+") else phone
    if not digits.isdigit():
        return False
    if phone.startswith(("+996", "+998")):
        return len(digits) == 12
    return 10 <= len(digits) <= 15


def _phone_dup_in_company(db: Session, company_id, phone: str, exclude_id=None) -> bool:
    """Telefon do'kon ichida takrorlanmasin (parolli ham, parolsiz ham — har xodim yagona raqam)."""
    q = db.query(Employee).filter(
        Employee.company_id == company_id,
        Employee.phone == phone,
        Employee.deleted_at.is_(None),
    )
    if exclude_id is not None:
        q = q.filter(Employee.id != exclude_id)
    return db.query(q.exists()).scalar()


def _check_phone(db: Session, company_id, phone: str, exclude_id=None):
    """Format + takror tekshiruvi (bo'sh telefon — tekshirilmaydi, ixtiyoriy)."""
    if not phone:
        return
    if not _valid_phone(phone):
        raise HTTPException(400, "Telefon raqami noto'g'ri. Masalan: +996 700 123 456")
    if _phone_dup_in_company(db, company_id, phone, exclude_id):
        raise HTTPException(409, "Bu telefon do'konda allaqachon band")


def _pin_taken(db: Session, company_id, pin: str, exclude_id=None) -> bool:
    """Do'konда shu PIN allaqachon ishlatilyaptimi (login PIN bo'yicha — noyob bo'lishi shart:
    aks holда login ikki xodimдан birini tanlab, savdo boshqa nomга yozilib ketardi)."""
    from app.core.security import verify_password
    q = db.query(Employee).filter(
        Employee.company_id == company_id, Employee.deleted_at.is_(None),
        Employee.pin_hash.isnot(None),
    )
    if exclude_id is not None:
        q = q.filter(Employee.id != exclude_id)
    return any(verify_password(pin, e.pin_hash) for e in q.all())


def _check_pin(db: Session, company_id, pin: str, exclude_id=None):
    """PIN formati + do'kon ichida noyoblik. Bo'sh PIN — ixtiyoriy, o'tkaziladi.
    AYNAN 4 raqam: POS PIN-pad qat'iy 4 raqamda avto-yuboradi — uzunroq PIN'li xodim POS'dan
    umuman kira olmasdi (server/mobil/POS shartnomasi endi bir xil). Eski uzun PIN'lar login'da
    ishlashda davom etadi; keyingi tahrirda 4 xonaga almashtiriladi."""
    if not pin:
        return
    if not pin.isdigit() or len(pin) != 4:
        raise HTTPException(400, "PIN aynan 4 ta raqamdan iborat bo'lishi kerak")
    if _pin_taken(db, company_id, pin, exclude_id):
        raise HTTPException(409, "Bu PIN do'konda allaqachon ishlatilgan")


def _set_branch(db: Session, employee_id, branch_id: str | None, company_id):
    """Xodimni bitta filialga biriktiradi (avvalgisini almashtiradi).
    branch_id bo'sh/None -> biriktiruvni olib tashlaydi."""
    from app.models.auth import EmployeeBranch
    from app.models.org import Branch
    db.query(EmployeeBranch).filter(EmployeeBranch.employee_id == employee_id).delete()
    bid = (branch_id or "").strip()
    if not bid:
        return
    try:
        buid = uuid.UUID(bid)
    except ValueError:
        raise HTTPException(400, "Filial ID noto'g'ri")
    br = db.get(Branch, buid)
    if not br or br.company_id != company_id or br.deleted_at is not None:
        raise HTTPException(400, "Filial topilmadi")
    if not br.is_active:
        raise HTTPException(400, "Filial nofaol — avval faollashtiring")
    db.add(EmployeeBranch(employee_id=employee_id, branch_id=buid))


def _branch_map(db: Session, company_id) -> dict:
    """{employee_id: 'Filial nomi'} — bir so'rovda (ro'yxat uchun)."""
    from app.models.auth import EmployeeBranch
    from app.models.org import Branch
    out: dict = {}
    for eid, bname in (
        db.query(EmployeeBranch.employee_id, Branch.name)
        .join(Branch, Branch.id == EmployeeBranch.branch_id)
        .filter(Branch.company_id == company_id, Branch.deleted_at.is_(None))
        .all()
    ):
        out.setdefault(eid, []).append(bname)
    return {k: ", ".join(v) for k, v in out.items()}


class EmployeeIn(BaseModel):
    full_name: str
    phone: str | None = None
    role_code: str = "kassir"
    password: str | None = None
    pin: str | None = None  # eskirgan (mobil/backward) — desktop endi parol ishlatadi
    branch_id: str | None = None  # ixtiyoriy — xodimni filialga biriktirish
    client_uuid: uuid.UUID | None = None  # idempotentlik: double-click/retry dublikat xodim yaratmasin


@router.get("/employees")
def list_employees(emp: Employee = Depends(require("xodimlar.view")), db: Session = Depends(get_db)):
    rows = (
        db.query(Employee)
        .filter(Employee.company_id == emp.company_id, Employee.deleted_at.is_(None))
        .all()
    )
    bmap = _branch_map(db, emp.company_id)
    return [
        {
            "id": str(e.id),
            "full_name": e.full_name,
            "phone": e.phone,
            "role": e.role.code,
            "role_name": e.role.name,
            "status": e.status.value,
            "branch": bmap.get(e.id),
        }
        for e in rows
    ]


@router.post("/employees")
def create_employee(
    data: EmployeeIn,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    # Idempotentlik: double-click/tarmoq-retry AYNI so'rovni ikki marta yubormasin — dublikat
    # xodim yaratilmaydi, mavjudi qaytariladi (kompaniya-doirali).
    if data.client_uuid:
        ex = db.query(Employee).filter(
            Employee.company_id == emp.company_id, Employee.client_uuid == data.client_uuid,
            Employee.deleted_at.is_(None)).first()
        if ex:
            return {"id": str(ex.id), "full_name": ex.full_name, "duplicate": True}
    role = db.query(Role).filter(Role.code == data.role_code).first()
    if not role:
        raise HTTPException(400, "Rol topilmadi")
    # Imtiyoz himoyasi:
    #  - 'ega' rolini FAQAT Ega tayinlaydi.
    #  - 'administrator' rolini Ega, YOKI Ega 'make_admin' bergan admin tayinlaydi.
    #  - override bilan xodimlar.edit olgan past rol o'z darajasidan yuqori rol yarata olmaydi.
    if role.code == "ega" and emp.role.code != "ega":
        raise HTTPException(403, "Ega rolini faqat Ega tayinlaydi")
    if role.code == "administrator" and not _can_make_admin(emp, db):
        raise HTTPException(403, "Administrator tayinlash huquqi yo'q — Ega bilan bog'laning")
    _check_role_ceiling(emp, role.code)
    from app.core.validate import clean_name
    full_name = clean_name(data.full_name, "Ism")
    phone = norm_phone(data.phone)
    if data.pin:
        # PIN noyobligi hash tufayli DB-indeks bilan himoyalanmaydi (check-then-act TOCTOU):
        # kompaniya qatorini qulflab, PIN yaratish/tahrirlashni KETMA-KET bajaramiz — parallel
        # ikki so'rov bir xil PIN o'tkazib yubormasin (PIN login birinchi mosini tanlab,
        # savdo boshqa xodim nomiga yozilardi).
        from app.models.org import Company as _Comp
        db.query(_Comp).filter(_Comp.id == emp.company_id).with_for_update().first()
    _check_phone(db, emp.company_id, phone)  # format + do'kon ichida takror (parolli/parolsiz)
    _check_pin(db, emp.company_id, data.pin or "")  # PIN format + noyoblik
    # QA VEN-01: tarif bo'yicha xodim limiti (max_users) — create_branch/PLAN_LIMITS bilan izchil.
    # Faqat mavjud (o'chirilmagan) xodimlar sanaladi; limit yangi yaratishni bloklaydi, mavjudini emas.
    from app.api.v1.branches import user_limit as _user_limit
    _plan_u, _maxu = _user_limit(db, emp.company_id)
    _ucount = db.query(Employee).filter(
        Employee.company_id == emp.company_id, Employee.deleted_at.is_(None)).count()
    if _ucount >= _maxu:
        raise HTTPException(403, detail={"error": "tarif_limit", "plan": _plan_u, "max_users": _maxu})
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Parol kamida 6 belgi bo'lishi kerak")
        if not phone:
            raise HTTPException(400, "Parolli xodim uchun telefon (login) kerak")
        if _phone_taken(db, phone):  # parolli login uchun GLOBAL noyoblik ham (login telefon bo'yicha)
            raise HTTPException(409, "Bu telefon allaqachon band")
    e = Employee(
        company_id=emp.company_id,
        full_name=full_name,
        phone=phone or None,
        role_id=role.id,
        password_hash=hash_password(data.password) if data.password else None,
        pin_hash=hash_password(data.pin) if data.pin else None,
        client_uuid=data.client_uuid,
    )
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.add(e)
        db.flush()  # unique-to'qnashuv (parallel telefon) AYNAN shu yerda otiladi — try ichida bo'lsin
        if data.branch_id:
            _set_branch(db, e.id, data.branch_id, emp.company_id)
        # AUDIT: ROL ham yozilsin — administrator yaratilishi izsiz qolmasin (imtiyoz kuzatuvi).
        audit_log(db, emp.id, "create", "employee", e.id,
                  after={"name": e.full_name, "role": role.code, "phone": phone or None,
                         "branch": data.branch_id or None})
        db.commit()
    except _IE:
        # Parallel bir xil telefon (ux_employees_phone_pw) — xom 500 emas, tushunarli 409.
        db.rollback()
        if data.client_uuid:
            ex2 = db.query(Employee).filter(
                Employee.company_id == emp.company_id, Employee.client_uuid == data.client_uuid,
                Employee.deleted_at.is_(None)).first()
            if ex2:
                return {"id": str(ex2.id), "full_name": ex2.full_name, "duplicate": True}
        raise HTTPException(409, "Bu telefon allaqachon band")
    db.refresh(e)
    return {"id": str(e.id), "full_name": e.full_name}


class EmployeeEdit(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    role_code: str | None = None
    password: str | None = None
    pin: str | None = None
    status: str | None = None
    branch_id: str | None = None  # None=tegmaymiz, ""=olib tashlash, qiymat=biriktirish
    old_password: str | None = None  # O'ZINI tahrirlashda parol/PIN almashtirish uchun majburiy


@router.patch("/employees/{employee_id}")
def edit_employee(
    employee_id: uuid.UUID,
    data: EmployeeEdit,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    from app.models.enums import EmployeeStatus

    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    # ── Imtiyoz himoyasi (privilege escalation'га qarshi) ──
    _is_owner = emp.role.code == "ega"
    # 1) Admin/Ega akkauntini FAQAT Ega boshqaradi (o'zini asosiy maydonlarда tahrirlash bundan mustasno).
    if e.role.code in _MANAGED_ROLES and not _is_owner and e.id != emp.id:
        raise HTTPException(403, "Administrator/Ega akkauntini faqat Ega boshqaradi")
    # 2) Rol biriktirish: ega — faqat Ega; administrator — Ega yoki make_admin bergan admin.
    if data.role_code == "ega" and not _is_owner:
        raise HTTPException(403, "Ega rolini faqat Ega tayinlaydi")
    if data.role_code == "administrator" and not _can_make_admin(emp, db):
        raise HTTPException(403, "Administrator tayinlash huquqi yo'q — Ega bilan bog'laning")
    # 3) O'zini o'zi tahrirlaganda: rol yoki holatni o'zgartira olmaydi (faqat Ega boshqasiga).
    if e.id == emp.id and not _is_owner and (data.role_code is not None or data.status is not None):
        raise HTTPException(403, "O'z rolingizni yoki holatingizni o'zgartira olmaysiz")
    # 3b) O'ZINI tahrirlashda parol/PIN almashtirish JORIY parolni talab qiladi (/auth/password
    # bilan izchil) — o'g'irlangan/qarovsiz sessiya akkauntni doimiy egallab ololmasin.
    # BOSHQA xodim parolini tiklash (admin-reset) — avvalgidek old_password'siz (to'g'ri oqim).
    if e.id == emp.id and (data.password or data.pin):
        _cur = emp.password_hash or emp.pin_hash
        if not data.old_password or not verify_password(data.old_password, _cur):
            raise HTTPException(401, "Joriy parolni tasdiqlang (old_password) — o'z parolingizni almashtirish uchun")
    # 3c) Rol darajasi: override bilan xodimlar.edit olgan past rol o'zidan yuqori rol tayinlamasin.
    if data.role_code is not None:
        _check_role_ceiling(emp, data.role_code)
    # ── Oxirgi rahbar himoyasi (do'konни boshqaruvsiz/qulflangan qoldirmaslik) ──
    # e HOZIR faol Ega/admin bo'lsa va uni to'xtatish/rolini pasaytirish do'konni 0 ta faol
    # rahbarга tushirsa — rad etamiz (tiklash faqat vendor orqali bo'lib qolmasligi uchun).
    if e.role.code in _MANAGED_ROLES and e.status == EmployeeStatus.active:
        _demoting = data.role_code is not None and data.role_code not in _MANAGED_ROLES
        _deactivating = data.status is not None and data.status != EmployeeStatus.active.value
        if (_demoting or _deactivating) and _active_admin_count_locked(db, emp.company_id) <= 1:
            raise HTTPException(400, "Oxirgi faol rahbarni (Ega/administrator) to'xtatib/o'zgartirib bo'lmaydi")
    # ── Oxirgi EGA himoyasi ── 'ega'ni faqat Ega tayinlay oladi; oxirgi faol Ega o'zini (yoki
    # boshqa yo'l bilan) pasaytirsa/to'xtatsa, do'konda hech kim ega/admin boshqara olmay qolardi.
    if e.role.code == "ega" and e.status == EmployeeStatus.active:
        _demote_ega = data.role_code is not None and data.role_code != "ega"
        _deact_ega = data.status is not None and data.status != EmployeeStatus.active.value
        if (_demote_ega or _deact_ega) and _active_ega_count_locked(db, emp.company_id) <= 1:
            raise HTTPException(400, "Oxirgi faol Egani pasaytirib/to'xtatib bo'lmaydi — avval boshqa Ega tayinlang")
    if data.full_name is not None:
        from app.core.validate import clean_name
        e.full_name = clean_name(data.full_name, "Ism")
    if data.phone is not None:
        _newphone = norm_phone(data.phone) or None
        # Parolli akkauntdan telefonni olib tashlab bo'lmaydi — telefon LOGIN, usiz akkaunt
        # "zombi" bo'lib qoladi (kira olmaydi); yagona Ega o'zini butunlay qulflashi mumkin edi.
        if _newphone is None and e.password_hash:
            raise HTTPException(400, "Parolli akkauntdan telefonni olib tashlab bo'lmaydi (telefon — login)")
        e.phone = _newphone
        _check_phone(db, emp.company_id, e.phone or "", exclude_id=e.id)  # format + do'kon ichida takror
    if data.role_code is not None:
        role = db.query(Role).filter(Role.code == data.role_code).first()
        if not role:
            raise HTTPException(400, "Rol topilmadi")   # noma'lum rol jimgina o'tib ketmasin
        e.role_id = role.id
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Parol kamida 6 belgi bo'lishi kerak")
        if not e.phone:
            raise HTTPException(400, "Parolli xodim uchun telefon (login) kerak")
    # Telefon global noyob bo'lishi kerak — parolli akkaunt (mavjud yoki shu patchda o'rnatilayotgan)
    # uchun. Faqat telefon o'zgartirilsa ham tekshiriladi (aks holda DB indeks 500 berardi).
    if e.phone and (e.password_hash or data.password) and _phone_taken(db, e.phone, exclude_id=e.id):
        raise HTTPException(409, "Bu telefon allaqachon band")
    if data.password:
        e.password_hash = hash_password(data.password)
    if data.pin:
        # PIN TOCTOU himoyasi: kompaniya qatorini qulflab, PIN o'rnatishlar KETMA-KET bajariladi
        from app.models.org import Company as _Comp
        db.query(_Comp).filter(_Comp.id == emp.company_id).with_for_update().first()
        _check_pin(db, emp.company_id, data.pin, exclude_id=e.id)  # PIN format + do'kon noyobligi
        e.pin_hash = hash_password(data.pin)
    if data.status is not None:
        try:
            _new_status = EmployeeStatus(data.status)
        except ValueError:
            raise HTTPException(400, "Status noto'g'ri")
        if _new_status != EmployeeStatus.active and _has_open_shift(db, e.id):
            raise HTTPException(400, "Xodimда ochiq smena bor — avval smenani yopish kerak")
        e.status = _new_status
    if data.branch_id is not None:
        _set_branch(db, e.id, data.branch_id, emp.company_id)
    # PAROL/PIN tiklandi -> o'sha xodimning HAMMA eski tokeni bekor bo'lsin (change_password bilan
    # izchil: kompromis-javob ssenariysi). sec_epoch oshsa deps.get_current_employee eski 'sv'ni rad etadi.
    if data.password or data.pin:
        e.sec_epoch = int(e.sec_epoch or 0) + 1
    # AUDIT: rol/status/parol/filial o'zgarishi iz qoldirsin (kim, kimni, nima) — parol EMAS.
    audit_log(db, emp.id, "update", "employee", e.id,
              after={"name": e.full_name, "role": data.role_code, "status": data.status,
                     "branch": str(data.branch_id) if data.branch_id else None,
                     "password_reset": data.password is not None or data.pin is not None})
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Parallel telefon to'qnashuvi (ux_employees_phone_pw) — xom 500 emas, tushunarli 409.
        db.rollback()
        raise HTTPException(409, "Bu telefon allaqachon band")
    return {"ok": True}


@router.delete("/employees/{employee_id}")
def delete_employee(
    employee_id: uuid.UUID,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    if e.id == emp.id:
        raise HTTPException(400, "O'zingizni o'chira olmaysiz")
    # AVTORIZATSIYA holat-tekshiruvдан OLDIN: ruxsati yo'q xodим (ega bo'lмаган) administrator/ega
    # akkауntига umuman tegа olmасин — ochiq smena bor-yo'qлигидан qat'i nazar 403 (403 > 400).
    if e.role.code in _MANAGED_ROLES and emp.role.code != "ega":
        raise HTTPException(403, "Administrator/Ega akkauntini faqat Ega o'chira oladi")
    if _has_open_shift(db, e.id):
        raise HTTPException(400, "Xodimда ochiq smena bor — avval smenani yopish kerak")
    # Oxirgi faol administratorни o'chirib do'konни adminsiz qoldirib bo'lmaydi.
    from app.models.enums import EmployeeStatus
    if (e.role.code in _MANAGED_ROLES and e.status == EmployeeStatus.active
            and _active_admin_count_locked(db, emp.company_id) <= 1):
        raise HTTPException(400, "Oxirgi faol rahbarni (Ega/administrator) o'chirib bo'lmaydi")
    # Oxirgi faol EGA ham o'chirilmaydi — 'ega'ni faqat Ega tayinlay oladi (boshqaruv qulfi oldini olish).
    if (e.role.code == "ega" and e.status == EmployeeStatus.active
            and _active_ega_count_locked(db, emp.company_id) <= 1):
        raise HTTPException(400, "Oxirgi faol Egani o'chirib bo'lmaydi — avval boshqa Ega tayinlang")
    from datetime import datetime, timezone
    e.deleted_at = datetime.now(timezone.utc)
    audit_log(db, emp.id, "delete", "employee", e.id,
              before={"name": e.full_name, "role": e.role.code})
    db.commit()
    return {"ok": True}


@router.get("/employees/{employee_id}/stats")
def employee_stats(
    employee_id: uuid.UUID,
    emp: Employee = Depends(require("xodimlar.view")),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app.models.enums import SaleStatus
    from app.models.sales import Sale

    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    _valid = Sale.status != SaleStatus.voided
    # Oy chegaralari va guruhlash do'kon MAHALLIY vaqtida (hisobotlar bilan izchil) — ilgari UTC oy
    # edi, +5/+6 do'konда oy 1-kuni birinchi ~5 soat savdosi oldingi oyга tushib ketardi.
    from app.api.v1.reports import _store_tz
    LOCAL = _store_tz(db, e.company_id)
    now_l = datetime.now(timezone.utc).astimezone(LOCAL)
    month_start = now_l.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_sales = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.cashier_id == e.id, Sale.sold_at >= month_start, _valid).scalar())
    tx = db.query(Sale).filter(Sale.cashier_id == e.id, Sale.sold_at >= month_start, _valid).count()
    # So'nggi 6 oylik HAQIQIY savdo (kassir bo'yicha), Python'da MAHALLIY oy kesimida guruhlanadi.
    y, m = now_l.year, now_l.month
    buckets: list[tuple[int, int]] = []
    for _i in range(6):
        buckets.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    buckets.reverse()  # eng eski -> eng yangi
    six_start = datetime(buckets[0][0], buckets[0][1], 1, tzinfo=LOCAL).astimezone(timezone.utc)
    agg: dict[tuple[int, int], float] = {}
    for sold_at, total in db.query(Sale.sold_at, Sale.total).filter(
            Sale.cashier_id == e.id, Sale.sold_at >= six_start, _valid).all():
        if sold_at is None:
            continue
        _sl = (sold_at if sold_at.tzinfo else sold_at.replace(tzinfo=timezone.utc)).astimezone(LOCAL)
        k = (_sl.year, _sl.month)
        agg[k] = agg.get(k, 0.0) + float(total or 0)
    MON = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
    chart = [{"label": MON[mo - 1], "sales": round(agg.get((yr, mo), 0.0), 2)} for yr, mo in buckets]
    return {"month_sales": month_sales, "tx": tx, "chart": chart}


@router.get("/permissions")
def list_permissions(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    rows = db.query(Permission).order_by(Permission.module, Permission.code).all()
    return [{"code": p.code, "module": p.module} for p in rows]


@router.get("/employees/{employee_id}")
def employee_detail(
    employee_id: uuid.UUID,
    emp: Employee = Depends(require("xodimlar.view")),
    db: Session = Depends(get_db),
):
    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    perms = effective_permissions(e, db)
    from app.models.auth import EmployeeBranch
    from app.models.org import Branch
    brow = (
        db.query(Branch.id, Branch.name)
        .join(EmployeeBranch, EmployeeBranch.branch_id == Branch.id)
        .filter(EmployeeBranch.employee_id == e.id, Branch.deleted_at.is_(None))
        .first()
    )
    return {
        "id": str(e.id), "full_name": e.full_name, "phone": e.phone,
        "role": e.role.code, "role_name": e.role.name, "status": e.status.value,
        "branch_id": str(brow[0]) if brow else None,
        "branch": brow[1] if brow else None,
        "permissions": sorted(perms),
    }


class PermPatch(BaseModel):
    overrides: dict[str, bool]   # {"kassa.sell": true, "hisobot.view": false}


@router.patch("/employees/{employee_id}/permissions")
def set_permissions(
    employee_id: uuid.UUID,
    data: PermPatch,
    emp: Employee = Depends(require("xodimlar.edit")),
    db: Session = Depends(get_db),
):
    # Ruxsatlarni qo'lda o'zgartirish: Ega — istalgan xodimга; administrator — faqat PASTROQ
    # rollarga (admin/ega'ga TEGA OLMAYDI, aks holda o'ziga make_admin berib imtiyoz oshirardi).
    e = db.get(Employee, employee_id)
    if not e or e.company_id != emp.company_id:
        raise HTTPException(404, "Xodim topilmadi")
    if emp.role.code not in _MANAGED_ROLES:
        raise HTTPException(403, "Ruxsatlarni faqat Ega yoki administrator o'zgartira oladi")
    if e.role.code in _MANAGED_ROLES and emp.role.code != "ega":
        raise HTTPException(403, "Administrator/Ega ruxsatlarини faqat Ega o'zgartiradi")
    # IMTIYOZ SHIFTI HIMOYASI: "admin qilish" (make_admin) huquqini FAQAT Ega bera oladi.
    # Aks holda admin pastroq rolli "puppet"ga make_admin berib, o'sha orqali yangi admin
    # yasab, Ega nazoratini chetlab o'tardi (adversarial audit topgan HIGH teshik).
    if data.overrides.get("xodimlar.make_admin") is True and emp.role.code != "ega":
        raise HTTPException(403, "\"Admin qilish\" huquqini faqat Ega beradi")
    code_to_id = {p.code: p.id for p in db.query(Permission).all()}
    role_codes = {p.code for p in e.role.permissions}
    for code, allowed in data.overrides.items():
        pid = code_to_id.get(code)
        if not pid:
            continue
        row = db.query(EmployeePermission).filter_by(employee_id=e.id, permission_id=pid).first()
        # Agar override rol standartiga teng bo'lsa — override o'chiriladi (toza holat)
        if allowed == (code in role_codes):
            if row:
                db.delete(row)
        elif row:
            row.allowed = allowed
        else:
            db.add(EmployeePermission(employee_id=e.id, permission_id=pid, allowed=allowed))
    # AUDIT: huquq berish/olib tashlash (make_admin ham) iz qoldirsin — imtiyoz o'zgarishi kuzatilsin.
    audit_log(db, emp.id, "update", "employee", e.id,
              after={"name": e.full_name, "permissions": data.overrides})
    db.commit()
    return {"ok": True, "permissions": sorted(effective_permissions(e, db))}
