import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.auth import Employee, EmployeePermission
from app.models.enums import EmployeeStatus


def get_current_employee(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Employee:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Avtorizatsiya talab qilinadi")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
        sub = uuid.UUID(str(payload["sub"]))  # sub UUID bo'lmasa ham 401 (xom 500 emas)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token yaroqsiz")
    emp = db.get(Employee, sub)
    if not emp or emp.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Xodim topilmadi")
    # To'xtatilgan/bo'shatilgan xodimning eski tokeni ham ishlamasin
    if emp.status != EmployeeStatus.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Xodim faol emas")
    # Token bekor qilish: parol o'zgarganda/chiqishда sec_epoch oshadi — eski token 'sv' mos kelmaydi.
    # (Eski, 'sv'siz tokenlar => 0, yangi xodimlarда ham sec_epoch=0 — deploy'да hech kim chiqarilmaydi.)
    if int(payload.get("sv", 0) or 0) != int(getattr(emp, "sec_epoch", 0) or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya bekor qilingan — qayta kiring")
    # Do'kon o'chirilgan yoki vendor tomonidan vaqtincha to'xtatilgan bo'lsa — mavjud token ham ishlamasin.
    from app.models.org import Company
    from app.models.settings import Setting
    comp = db.get(Company, emp.company_id)
    if not comp or comp.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Do'kon topilmadi")
    _susp = db.query(Setting).filter(
        Setting.company_id == emp.company_id, Setting.key == "suspended"
    ).first()
    if _susp and (_susp.value or {}).get("on"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning.")
    return emp


# Ruxsat cheklovisiz (hamma narsani ko'radi) rollar — Ega va Administrator.
FULL_ACCESS_ROLES = ("ega", "administrator")


def is_owner(emp: Employee) -> bool:
    """Ega (do'kon egasi) — adminlarni boshqaradi, filial cheklovi yo'q."""
    return emp.role.code == "ega"


def actor_branch(emp: Employee, db: Session):
    """Xodim YOZADIGAN filial: biriktirilgan filial (EmployeeBranch) — bo'lmasa birinchi faol filial.
    Sotuv/writeoff/sanoq/qaytarish shu filialga tushishi kerak (ko'p-filialда to'g'ri yozilishi uchun).
    Ilgari inventory/return doim BIRINCHI filialга yozardi — ko'p-filialда noto'g'ri edi."""
    from app.models.auth import EmployeeBranch
    from app.models.org import Branch
    # ORDER_BY (QA SB-016): .first() tartibsiz nodeterministik edi. NOFAOL (is_active=False)
    # filialga YANGI yozuvlar tushmasin — biriktirilgani nofaol bo'lsa birinchi FAOL filialga.
    return (
        db.query(Branch)
        .join(EmployeeBranch, EmployeeBranch.branch_id == Branch.id)
        .filter(EmployeeBranch.employee_id == emp.id, Branch.company_id == emp.company_id,
                Branch.deleted_at.is_(None), Branch.is_active.is_(True))
        .order_by(Branch.created_at)
        .first()
        or db.query(Branch)
        .filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None),
                Branch.is_active.is_(True))
        .order_by(Branch.created_at)
        .first()
        or db.query(Branch)   # so'nggi chora (hammasi nofaol bo'lsa — bo'sh qolmasin)
        .filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None))
        .order_by(Branch.created_at)
        .first()
    )


def visible_branches(emp: Employee, db: Session) -> set | None:
    """Xodim KO'RA oladigan filiallar to'plami. None = cheklovsiz (hamma filial).
    - Ega: doim None (butun kompaniya).
    - Boshqa xodim: biriktirilgan filial(lar) — bitta filialга bog'langan bo'lsa faqat o'sha.
    - Hech qaysi filialга biriktirilmagan bo'lsa: None (kompaniya bo'yicha — moslik)."""
    if emp.role.code == "ega":
        return None
    from app.models.auth import EmployeeBranch
    rows = db.query(EmployeeBranch.branch_id).filter(EmployeeBranch.employee_id == emp.id).all()
    ids = {r[0] for r in rows}
    return ids or None


def effective_permissions(emp: Employee, db: Session) -> set[str]:
    """Rol standarti + xodim override (Xodimlar sahifasidagi toggle'lar)."""
    perms = {p.code for p in emp.role.permissions}
    overrides = db.query(EmployeePermission).filter_by(employee_id=emp.id).all()
    from app.models.auth import Permission

    for ov in overrides:
        code = db.get(Permission, ov.permission_id).code
        if ov.allowed:
            perms.add(code)
        else:
            perms.discard(code)
    return perms


def require(permission_code: str):
    """Endpoint uchun ruxsat tekshiruvchi dependency."""

    def checker(
        emp: Employee = Depends(get_current_employee),
        db: Session = Depends(get_db),
    ) -> Employee:
        if emp.role.code in FULL_ACCESS_ROLES:
            return emp
        if permission_code not in effective_permissions(emp, db):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Ruxsat yo'q: {permission_code}")
        return emp

    return checker


def require_any(*permission_codes: str):
    """Sanab o'tilgan ruxsatlardan kamida bittasi bo'lsa yetadi (masalan,
    kassir QARZ savdoda yangi mijoz yaratishi: mijozlar.edit YOKI kassa.sell).

    ⚠️  PREDIKAT `has_any` DA. Endpoint darvozasi va maydon yashirish (`field_access`)
        AYNAN bitta funksiyani chaqiradi: ikkisi ikki xil hisoblasa, bir joyda
        yopilgan maydon ikkinchi joyda ochiq qolardi."""

    def checker(
        emp: Employee = Depends(get_current_employee),
        db: Session = Depends(get_db),
    ) -> Employee:
        if not has_any(emp, db, permission_codes):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Ruxsat yo'q: {' / '.join(permission_codes)}")
        return emp

    return checker


# ══ MAYDON DARAJALARI — YAGONA MANBA ══════════════════════════════════════════
#
# ⚠️  Bir xil ma'lumot bir endpointda ALOHIDA ruxsat bilan yopilgan bo'lsa, boshqa
#     endpoint uni o'z javobiga qo'shib, o'sha yopiq eshikni orqa tomondan
#     ochmasligi kerak. Shu bois har daraja BITTA tuple bilan ta'riflanadi va
#     endpoint darvozasi (`require_any(*TIER)`) ham, maydon yashirish
#     (`field_access`) ham aynan shu tuple'ni o'qiydi.
#
# XARID (`PURCHASING_TIER`): ta'minotchi, qabul/xarid hujjatining identifikatori,
#     manbasi va summasi (`/receiving`, `/purchases` shu ruxsatni talab qiladi).
#
# SOTUV HUJJATI (`SALES_DOC_TIER`): `sale_id`, chek raqami (`receipt_no`), `uid`,
#     `sale_item_id`, sotuvni urgan KASSIR va chek bo'yicha sotuv narxlari
#     (`unit_price`, qator summasi). `/sales/find` va `/sales/{id}` darvozasi ham
#     SHU tuple: chek raqami ketma-ket (`#N`) — uni ochgan har ruxsat amalda
#     to'liq sotuv hujjati o'quvchisi. Darvoza tor bo'lsa, maydonda ko'ringan
#     identifikator ochilmay qolardi; keng bo'lsa — yashirish yolg'on bo'lardi.
#     `hisobot.view` kiradi: `/reports/overview` ham chek raqami va kassirni beradi.
#
# XODIM (`STAFF_TIER`): ombor, kassa yoki katalog amalini KIM qilgani
#     (`/inventory/movements`, `/audit`, `/cash/ops` shu ruxsatni talab qiladi).
#     Oddiy ismlar ro'yxati bu daraja EMAS (`/auth/pin-roster`, `/employees`).
PURCHASING_TIER = ("xaridlar.view",)
SALES_DOC_TIER = ("sotuvlar.view", "hisobot.view")
STAFF_TIER = ("hisobot.view",)


def has_any(emp: Employee, db: Session, codes, perms: set[str] | None = None) -> bool:
    """`require_any` semantikasi, istisnosiz: FULL_ACCESS rol — doim ha; aks holda
    samarali ruxsatlardan (rol + override) kamida bittasi.

    ⚠️  YOPIQ STANDART. Noma'lum kod — yo'q; override `allowed=False` rol
        standartini OLIB TASHLAYDI. `perms` berilsa qayta so'ralmaydi (bir so'rovda
        bir necha daraja tekshirilganda)."""
    if emp.role.code in FULL_ACCESS_ROLES:
        return True
    if perms is None:
        perms = effective_permissions(emp, db)
    return any(code in perms for code in codes)


def field_access(emp: Employee, db: Session) -> dict:
    """Uch daraja — BITTA `effective_permissions` hisobidan (override'lar ham kiradi)."""
    perms = None if emp.role.code in FULL_ACCESS_ROLES else effective_permissions(emp, db)
    return {"purchasing": has_any(emp, db, PURCHASING_TIER, perms),
            "sales": has_any(emp, db, SALES_DOC_TIER, perms),
            "staff": has_any(emp, db, STAFF_TIER, perms)}
