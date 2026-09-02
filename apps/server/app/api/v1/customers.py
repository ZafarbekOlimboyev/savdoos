import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require, require_any
from app.core.security import norm_phone
from app.core.validate import clean_name, require_phone
from app.db.session import get_db
from app.models.auth import Employee
from app.models.customers import CreditTransaction, Customer, CustomerPayment
from app.models.enums import CreditTxnType
from app.schemas.customer import CreditPayment, CustomerCreate, CustomerOut

router = APIRouter(tags=["customers"])


def _check_customer_phone(db: Session, company_id, phone: str, exclude_id=None):
    """Format + do'kon ichida takror (bo'sh telefon — o'tkaziladi, ixtiyoriy)."""
    if not phone:
        return
    require_phone(phone)  # noto'g'ri format -> 400
    dup = db.query(Customer.id).filter(
        Customer.company_id == company_id,
        Customer.deleted_at.is_(None),
        Customer.phone == phone,
    )
    if exclude_id is not None:
        dup = dup.filter(Customer.id != exclude_id)
    if dup.first():
        raise HTTPException(409, "Bu telefon do'konda allaqachon band")


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    q: str | None = None,
    only_debt: bool = False,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    query = db.query(Customer).filter(
        Customer.company_id == emp.company_id, Customer.deleted_at.is_(None)
    )
    if q:
        from app.core.validate import like_escape
        like = f"%{like_escape(q)}%"
        query = query.filter(or_(Customer.full_name.ilike(like, escape="\\"), Customer.phone.ilike(like, escape="\\")))
    if only_debt:
        query = query.filter(Customer.credit_balance > 0)
    return query.order_by(Customer.full_name).all()


@router.post("/customers", response_model=CustomerOut)
def create_customer(
    data: CustomerCreate,
    # Kassir ham QARZ savdoda yangi mijoz yarata oladi (dizayn: "Yangi mijoz" tab)
    emp: Employee = Depends(require_any("mijozlar.edit", "kassa.sell")),
    db: Session = Depends(get_db),
):
    full_name = clean_name(data.full_name, "Mijoz nomi")
    phone = norm_phone(data.phone) or None
    _check_customer_phone(db, emp.company_id, phone)  # format + do'kon ichida takror
    # QA CC-004/CC-005: kod (M-N) count() asosida — parallel create'da bir xil kod -> UniqueConstraint
    # 500 berardi; telefon ham DB-unique (ux_customers_company_phone). Retry-o'ram: to'qnashuvda
    # rollback + yangi count. Telefon dublikati aniq 409 (app-check chetlab o'tган poyga uchun ham).
    from sqlalchemy.exc import IntegrityError as _IE
    from app.services.audit import log as audit_log
    for _try in range(6):
        # QA CC-005: max raqamli suffiks+1 (count() emas) — soft-o'chirilgan/bo'shliqli kodlarga
        # chidamli va poyga ostida tezroq konvergensiya (count() bir xil qiymatda qotib qolardi).
        _codes = [c[0] for c in db.query(Customer.code).filter(
            Customer.company_id == emp.company_id, Customer.code.like("M-%")).all()]
        _mx = 1000
        for _cd in _codes:
            try:
                _mx = max(_mx, int(_cd.split("-", 1)[1]))
            except (ValueError, IndexError):
                pass
        seq = _mx - 1000 + _try  # _try — parallel to'qnashuvda kodni surib beradi
        c = Customer(
            company_id=emp.company_id,
            code=f"M-{1001 + seq}",
            full_name=full_name,
            phone=phone,
            address=data.address,
        )
        db.add(c)
        try:
            db.flush()
            audit_log(db, emp.id, "create", "customer", c.id, after={"name": c.full_name})
            db.commit()
            db.refresh(c)
            return c
        except _IE as e:
            db.rollback()
            _msg = str(getattr(e, "orig", e)).lower()
            if "phone" in _msg:
                raise HTTPException(409, "Bu telefon do'konda allaqachon band")
            # kod to'qnashuvi — keyingi urinishda yangi count
    raise HTTPException(409, "Mijoz yaratishda to'qnashuv — qayta urining")


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id or c.deleted_at is not None:  # QA CC-003: soft-o'chirilgan ochilmasin
        raise HTTPException(404, "Mijoz topilmadi")
    return c


class CustomerEdit(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    address: str | None = None


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def edit_customer(
    customer_id: uuid.UUID,
    data: CustomerEdit,
    emp: Employee = Depends(require("mijozlar.edit")),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id or c.deleted_at is not None:  # QA CC-003: soft-o'chirilgan tahrirlanmasin
        raise HTTPException(404, "Mijoz topilmadi")
    before = {"name": c.full_name, "phone": c.phone}
    if data.full_name is not None:
        c.full_name = clean_name(data.full_name, "Mijoz nomi")
    if data.phone is not None:
        phone = norm_phone(data.phone) or None
        _check_customer_phone(db, emp.company_id, phone, exclude_id=c.id)  # format + takror
        c.phone = phone
    if data.address is not None:
        c.address = data.address
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "update", "customer", c.id,
              before=before, after={"name": c.full_name, "phone": c.phone})
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:  # QA CC-004: telefon DB-unique poygasi (app-check TOCTOU chetlab o'tsa)
        db.rollback()
        raise HTTPException(409, "Bu telefon do'konda allaqachon band")
    db.refresh(c)
    return c


@router.delete("/customers/{customer_id}")
def delete_customer(
    customer_id: uuid.UUID,
    emp: Employee = Depends(require("mijozlar.edit")),
    db: Session = Depends(get_db),
):
    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Mijoz topilmadi")
    # Manfiy balans = do'kon mijozga qarzdor (avans/ortiqcha to'lov) — u ham o'chirishga to'siq
    # (delete_supplier bilan bir xil invariant): hisob-kitob nolga kelмагунча o'chirilмайди.
    if c.credit_balance and c.credit_balance != 0:
        raise HTTPException(400, "Hisob-kitobi ochiq (qarz yoki avans) mijozni o'chirib bo'lmaydi")
    from datetime import datetime, timezone
    c.deleted_at = datetime.now(timezone.utc)
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "delete", "customer", c.id,
              before={"name": c.full_name, "phone": c.phone})
    db.commit()
    return {"ok": True}


@router.get("/customers/{customer_id}/detail")
def customer_detail(
    customer_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.models.sales import Sale, SaleItem, SalePayment

    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id or c.deleted_at is not None:  # QA CC-003
        raise HTTPException(404, "Mijoz topilmadi")
    sales = (
        db.query(Sale)
        .filter(Sale.customer_id == c.id, Sale.company_id == emp.company_id, Sale.deleted_at.is_(None))
        .order_by(Sale.sold_at.desc())
        .limit(10)
        .all()
    )
    history = []
    for s in sales:
        pay = db.query(SalePayment.method_code).filter(SalePayment.sale_id == s.id).first()
        cnt = db.query(func.coalesce(func.sum(SaleItem.qty), 0)).filter(SaleItem.sale_id == s.id).scalar()
        history.append({
            "date": s.sold_at, "items": int(cnt or 0),
            "amount": float(s.total), "method": pay[0] if pay else "cash",
        })
    pays = (
        db.query(CustomerPayment)
        .filter(CustomerPayment.customer_id == c.id)
        .order_by(CustomerPayment.paid_at.desc())
        .limit(10)
        .all()
    )
    from app.models.enums import SaleStatus as _SSt
    _valid = Sale.status != _SSt.voided
    # Jami xarid — BEKOR qilingan cheklarsiz; Tashriflar — to'liq son (ilgari
    # oxirgi-10 ro'yxat uzunligi bo'lib, 10 da "qotib" qolardi)
    total_spent = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.customer_id == c.id, Sale.company_id == emp.company_id,
        Sale.deleted_at.is_(None), _valid).scalar())
    visits = db.query(func.count(Sale.id)).filter(
        Sale.customer_id == c.id, Sale.company_id == emp.company_id,
        Sale.deleted_at.is_(None), _valid).scalar() or 0
    return {
        "id": str(c.id), "code": c.code, "full_name": c.full_name, "phone": c.phone,
        "credit_balance": float(c.credit_balance),
        "total_spent": total_spent,
        "visits": int(visits),
        "history": history,
        "payments": [{"date": p.paid_at, "amount": float(p.amount)} for p in pays],
    }


@router.post("/customers/{customer_id}/payments")
def pay_credit(
    customer_id: uuid.UUID,
    data: CreditPayment,
    emp: Employee = Depends(require("mijozlar.edit")),
    db: Session = Depends(get_db),
):
    # QATOR QULFI: bir vaqtда ikki to'lov/savdo balansни STALE o'qib yo'qotmasin.
    c = db.query(Customer).filter(Customer.id == customer_id).with_for_update().first()
    if not c or c.company_id != emp.company_id or c.deleted_at is not None:  # QA CC-003
        raise HTTPException(404, "Mijoz topilmadi")
    if data.method not in {"cash", "card", "qr"}:
        raise HTTPException(400, f"Noto'g'ri to'lov usuli: {data.method}")
    if data.client_uuid:
        # Idempotentlik SHU mijoz doirasida (boshqa mijozning bir xil client_uuid'i o'chirilmasin)
        ex = (
            db.query(CustomerPayment)
            .filter(CustomerPayment.client_uuid == data.client_uuid,
                    CustomerPayment.customer_id == c.id)
            .first()
        )
        if ex:
            return {"customer_id": str(c.id), "credit_balance": float(c.credit_balance)}
    amt = Decimal(str(data.amount))
    if not amt.is_finite() or amt <= 0:
        raise HTTPException(400, "Summa noto'g'ri")
    bal = Decimal(str(c.credit_balance))
    if bal <= 0:
        raise HTTPException(400, "Qarz yo'q")
    amt = min(amt, bal)   # ortiqcha to'lov qarz miqdorigacha qo'llanadi (ledger izchil)
    now = datetime.now(timezone.utc)
    # FILIAL: to'lov qabul qilingan filialни yozamiz — aks holда filialга bog'langan xodим uchun
    # hisobot (cashflow) bu naqд qarz-to'lovни kassaга QO'SHMASdi (branch_id NULL -> IN(...) mos kelmaydi).
    from app.core.deps import actor_branch as _actor_branch
    _ab = _actor_branch(emp, db)
    pay = CustomerPayment(
        customer_id=c.id, amount=amt, method=data.method, paid_at=now, employee_id=emp.id, created_at=now,
        client_uuid=data.client_uuid, branch_id=(_ab.id if _ab else None),
    )
    db.add(pay)
    db.flush()
    c.credit_balance = max(Decimal("0"), Decimal(str(c.credit_balance)) - amt)
    db.add(
        CreditTransaction(
            customer_id=c.id,
            type=CreditTxnType.payment,
            amount=-amt,
            balance_after=c.credit_balance,
            payment_id=pay.id,
            employee_id=emp.id,
            created_at=now,
        )
    )
    # NAQD qarz to'lovi kassaga tushadi — qabul qilgan xodimning OCHIQ smenasiga payin
    # yoziladi (aks holda smena "kutilgan naqd" bilan haqiqiy kassa mos kelmasdi).
    if data.method == "cash":
        from app.models.enums import CashMovementType as _CMT
        from app.models.enums import ShiftStatus as _ShSt
        from app.models.shifts import CashMovement as _CM
        from app.models.shifts import Shift as _Shift
        _sh = db.query(_Shift).filter(_Shift.cashier_id == emp.id, _Shift.status == _ShSt.open).first()
        if _sh:
            db.add(_CM(shift_id=_sh.id, type=_CMT.payin, amount=amt,
                       reason=f"Qarz to'lovi · {c.full_name}", employee_id=emp.id, created_at=now))
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Bir vaqtда bir xil client_uuid — DB unique indeksi (ux_custpay_client_uuid) ushlади:
        # birinchи so'rov yozди, ikkinчиси bekor. Ikki marta to'lov emas — mavjudni qaytaramiz.
        db.rollback()
        c2 = db.get(Customer, customer_id)
        return {"customer_id": str(customer_id), "credit_balance": float(c2.credit_balance) if c2 else 0.0}
    return {"customer_id": str(c.id), "credit_balance": float(c.credit_balance)}
