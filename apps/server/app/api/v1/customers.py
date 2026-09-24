import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import error_codes as EC
from app.core.deps import get_current_employee, require, require_any
from app.core.security import norm_phone
from app.core.validate import clean_name, require_phone
from app.db.session import get_db
from app.models.auth import Employee
from app.models.customers import CreditTransaction, Customer, CustomerPayment
from app.models.enums import CreditTxnType
from app.schemas.customer import CreditPayment, CustomerCreate, CustomerOut

router = APIRouter(tags=["customers"])


def _q3(v) -> Decimal:
    """Miqdor — 3 xonali o'nlik (NUMERIC 14,3); SQLite float yig'indisi ham barqaror satrga."""
    return Decimal(str(v if v is not None else 0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


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
    # QA OFF-5: idempotentlik — shu client_uuid bilan mijoz ALLAQACHON yaratilgan bo'lsa (response-lost/retry)
    # uni qaytaramiz (dublikat yaratmaymiz). Telefon-tekshiruvдан OLDIN: retry'да telefon 'band' bo'lib 409
    # bermasin (birinchi so'rov mijozni yaratib javob yo'qolgan holat).
    if data.client_uuid:
        _dup = db.query(Customer).filter(
            Customer.company_id == emp.company_id, Customer.client_uuid == data.client_uuid,
            Customer.deleted_at.is_(None)).first()
        if _dup:
            return _dup
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
            client_uuid=data.client_uuid,   # QA OFF-5: idempotentlik kaliti
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
            # QA OFF-5: parallel bir xil client_uuid — DB unique (ux_customers_client_uuid) ushladi; mavjudni qaytaramiz.
            if data.client_uuid and ("client_uuid" in _msg or "ux_customers_client_uuid" in _msg):
                _dup = db.query(Customer).filter(
                    Customer.company_id == emp.company_id, Customer.client_uuid == data.client_uuid,
                    Customer.deleted_at.is_(None)).first()
                if _dup:
                    return _dup
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
    from app.core.deps import field_access, visible_branches
    from app.models.sales import Sale, SaleItem, SalePayment

    c = db.get(Customer, customer_id)
    if not c or c.company_id != emp.company_id or c.deleted_at is not None:  # QA CC-003
        raise HTTPException(404, "Mijoz topilmadi")
    # ⚠️  SOTUV HUJJATI MAYDONLARI (`deps.SALES_DOC_TIER` — `sale_id`, chek raqami)
    #     BU YERDA HAM YOPIQ. Marshrutning o'zi faqat login talab qiladi (mijoz
    #     kartasi), lekin `sale_id` `/sales/{id}` ning, `receipt_no` esa
    #     `/sales/find` ning KALITI — ikkalasi `require_any(*SALES_DOC_TIER)` bilan
    #     yopilgan. Ularni bu javobga shartsiz qo'shish o'sha eshikni ORQA tomondan
    #     ochardi: omborchi (`sotuvlar.view` ham, `hisobot.view` ham yo'q) mijoz
    #     kartasidan chek raqamlarini o'qib olardi.
    # ⚠️  FILIAL DOIRASI ham AYNI: `/sales/{id}` va `/sales/find` ko'rinmaydigan
    #     filial hujjatini 404 qiladi, shu bois bu yerda ham u hujjat OCHILMAYDI.
    #     Qator, sana, summa, miqdor (`items`, `items_qty`) va to'lov usuli QOLADI —
    #     ular mijoz HISOBI (jami/tashriflar bilan izchil), hujjat identifikatori emas.
    # ⚠️  Kalitlar JAVOBDA QOLADI (qiymat `null`) — `lots_read` dagi redaksiya naqshi:
    #     shakl barqaror, mijoz esa "hujjat yo'q" bilan "ruxsat yo'q" ni farqlamasa ham
    #     xulq bir xil (qator OCHILMAYDI), ya'ni klient uchun xavfsiz standart.
    _doc = field_access(emp, db)["sales"]
    _vb = visible_branches(emp, db)
    # Phase 5G: har sotuvning to'lov usuli va miqdor yig'indisi — KORRELYATSIYALI skalyar
    # subquery'lar (bitta SELECT). Ilgari har qator uchun 2 alohida so'rov (N+1) edi; SQL
    # ma'nosi AYNAN o'sha: `WHERE sale_id = <sotuv> LIMIT 1` va `coalesce(sum(qty), 0)`.
    _pay_sq = (select(SalePayment.method_code)
               .where(SalePayment.sale_id == Sale.id)
               .limit(1).correlate(Sale).scalar_subquery())
    _cnt_sq = (select(func.coalesce(func.sum(SaleItem.qty), 0))
               .where(SaleItem.sale_id == Sale.id)
               .correlate(Sale).scalar_subquery())
    sales = (
        db.query(Sale, _pay_sq, _cnt_sq)
        .filter(Sale.customer_id == c.id, Sale.company_id == emp.company_id, Sale.deleted_at.is_(None))
        .order_by(Sale.sold_at.desc())
        .limit(10)
        .all()
    )
    history = []
    for s, pay, cnt in sales:
        _ochiq = _doc and (_vb is None or s.branch_id in _vb)
        history.append({
            "date": s.sold_at, "items": int(cnt or 0),
            "amount": float(s.total), "method": pay if pay is not None else "cash",
            # Phase 5G QO'SHIMCHA maydonlar (mobil: qatordan chekni ochish, kasr miqdor).
            # `items` (butun son) moslik uchun O'ZGARMAGAN; `items_qty` — 3 xonali satr.
            "sale_id": str(s.id) if _ochiq else None,
            "receipt_no": s.receipt_no if _ochiq else None,
            "items_qty": f"{_q3(cnt):f}",
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
        # Phase 5G: `method` — QO'SHIMCHA (saqlangan to'lov usuli: cash|card|qr).
        "payments": [{"date": p.paid_at, "amount": float(p.amount), "method": p.method} for p in pays],
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
            # §7 IDEMPOTENTLIK KONFLIKTI (ta'minotchi to'lovi bilan AYNI qoida —
            # `purchases.pay_supplier`): AYNI kalit (client_uuid) BOSHQA custody hisobi
            # bilan qayta yuborilsa — BALAND OVOZDA rad. Jimgina yangi hisobga post
            # qilish ham, eskisini jimgina saqlab qolish ham auditni YOLG'ON qilardi.
            if (data.cash_account_id is not None and ex.cash_account_id is not None
                    and str(data.cash_account_id) != str(ex.cash_account_id)):
                # Phase 5G.1: saqlangan hisob id'i (mijoz bu so'rovda YUBORMAGAN) matnga EMAS,
                # jurnalga; matn + `X-Error-Code` — `cutover_guard.key_account_conflict`.
                from app.services.cash import cutover_guard as _cg0
                raise _cg0.key_account_conflict(
                    company_id=emp.company_id, operation="debt_payment",
                    stored_account_id=ex.cash_account_id,
                    requested_account_id=data.cash_account_id)
            # ⚠️  `duplicate` — TAKROR EKANI OCHIQ AYTILADI (ta'minotchi to'lovi bilan
            #     izchil). Usiz javob yangi to'lovnikidan FARQ QILMASDI: javobi
            #     yo'qolgan to'lovni qayta yuborgan operator "ikkinchi marta yozildimi?"
            #     degan savolga JAVOB OLMASDI — mobil ilova esa aynan shuni va'da qiladi.
            return {"customer_id": str(c.id), "credit_balance": float(c.credit_balance),
                    "paid": float(ex.amount), "duplicate": True}
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
        from app.models.shifts import CashMovement as _CM
        from app.services.cash import custody_preview as _CP
        # §8 T0 GUARD (_sh HAL QILINGACH): post-T0 naqd qarz to'lovi fizik custody hisobini TALAB
        # qiladi. Smenasiz (off-shift) naqd qabul qilish post-T0 da JIMGINA ruxsat etilmaydi —
        # aks holda naqd pul hech qanday custody yozuvisiz do'konga kirardi.
        from app.services.cash import cutover_guard as _cg
        # §2 CUSTODY REZOLYUTSIYASI (savdo/xarid bilan IZCHIL):
        #   ochiq smena BOR  -> custody = shift.till_id (server avtoritet). Klient boshqa hisob
        #                       yuborsa ZID deb RAD etiladi (smena o'rtasida drawer almashmaydi).
        #   ochiq smena YO'Q -> so'rovdagi AYNAN cash_account_id (ACTIVE TILL yoki SAFE) SHART.
        # TAXMIN YO'Q. Post-T0 da har ikkala shoxobcha ham to'liq validatsiyadan o'tadi.
        # §2 FILIAL DOIRASI: smenasiz holatda ham custody hisobi AKTOR FILIALIGA tegishli
        # bo'lishi SHART. `branch_id=None` uzatilsa `require_custody_account` filial
        # tekshiruvini O'TKAZIB YUBORADI va butun do'kondagi ISTALGAN TILL/SAFE qabul
        # bo'lardi — boshqa filial kassasiga naqd yozib yuborish mumkin edi.
        # ⚠️  Smena va custody filiali YAGONA yordamchidan (`custody_preview.debt_payment_ctx`):
        #     `GET /cash/custody-preview?operation=debt_payment` AYNI kontekstni quruq yuritadi.
        _cust_br, _sh = _CP.debt_payment_ctx(db, emp)
        _dacc, _ = _cg.resolve_cash_custody(db, company_id=emp.company_id,
                                            branch_id=_cust_br,
                                            operation=_CP.OP_DEBT, shift=_sh,
                                            cash_account_id=data.cash_account_id)
        if (_sh is not None and data.cash_account_id is not None
                and str(data.cash_account_id) != str(_sh.till_id)):
            raise HTTPException(409, f"{_cg.ERR_CUSTODY_INVALID}: yuborilgan naqd hisob ochiq "
                                     "smena kassasiga mos emas.",
                                headers=EC.headers(_cg.ERR_CUSTODY_INVALID))
        if _sh:
            db.add(_CM(shift_id=_sh.id, type=_CMT.payin, amount=amt,
                       reason=f"Qarz to'lovi · {c.full_name}", employee_id=emp.id, created_at=now))
        else:
            # QA PAY-03: "smena majburiy" (force_shift) yoqilgan do'konda naqd qarz-to'lovi ochiq
            # smenani TALAB qiladi (savdo bilan IZCHIL — aks holda naqd till 'expected'idan tushib
            # qolardi). Naqd-OUT (qaytarish) doim smena talab qiladi (kassa drain xavfi), naqd-IN'da
            # bunday xavf yo'q — shu bois standart (force_shift o'chiq) menejer/mobil oqimi BUZILMAYDI.
            if _CP.debt_payment_needs_shift(db, emp, _sh):
                from app.core import error_codes as _EC
                raise HTTPException(400, "Naqd qarz to'lovi uchun ochiq smena kerak — avval smenani oching",
                                    headers=_EC.headers(_EC.OPEN_SHIFT_REQUIRED))
    # Phase 2b dual-write (guarded): NAQD qarz to'lovi -> IN·DEBT_IN (karta/QR ledger'ga tegmaydi).
    # §19 PARITY topilma: legacy SOYA (payin CashMovement) FAQAT ochiq smena bo'lса yoziladi (yuqorida
    # `if _sh`). Shu bois ledger DEBT_IN ham FAQAT o'sha holда post qilinsin — aks holда smenasiz naqd
    # qarz-to'lovi (force_shift o'chiq) ledger'ни legacy'дан OSHIRib, systematik ledger>legacy
    # divergensiya berardi. branch = smena filiali (soya bilan izchil; supplier to'lovi naqshiga mos).
    # source(CustomerPayment)+AR+ledger BIR tranzaksiyада (atomik).
    if data.method == "cash" and (_sh or _dacc is not None):
        from app.services.cash import retrofit as _cr
        # Smena bor -> shift.till_id; smenasiz (post-T0) -> AYNAN so'ralgan custody hisobi.
        _acc_id = (_sh.till_id if _sh else _dacc.id)
        _br_id = (_sh.branch_id if _sh else _dacc.branch_id)
        _cr.on_debt_payment(db, emp, branch_id=_br_id, payment_id=pay.id, cash_amount=amt,
                            till_id=_acc_id)       # §4: ledger AYNAN shu hisobga
        if _dacc is not None:
            pay.cash_account_id = _dacc.id         # §2 audit identity
            db.add(pay)
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Bir vaqtда bir xil client_uuid — DB unique indeksi (ux_custpay_client_uuid) ushlади:
        # birinchи so'rov yozди, ikkinчиси bekor. Ikki marta to'lov emas — mavjudni qaytaramiz
        # (yuqoridagi SELECT-dedup bilan AYNI shaklda: `duplicate` + yozilgan summa).
        db.rollback()
        c2 = db.get(Customer, customer_id)
        out = {"customer_id": str(customer_id),
               "credit_balance": float(c2.credit_balance) if c2 else 0.0}
        if data.client_uuid:
            ex2 = (db.query(CustomerPayment)
                   .filter(CustomerPayment.client_uuid == data.client_uuid,
                           CustomerPayment.customer_id == customer_id).first())
            if ex2 is not None:
                out.update({"paid": float(ex2.amount), "duplicate": True})
        return out
    # `paid` — HAQIQATAN yozilgan summa. Ortiqcha to'lov qarz miqdorigacha qisqaradi
    # (`amt = min(amt, bal)`); mijoz bunday holatda kassirga ogohlantirish ko'rsatadi,
    # shu bois yozilgan summa javobda AYTILADI (ta'minotchi to'lovi bilan bir xil shakl).
    return {"customer_id": str(c.id), "credit_balance": float(c.credit_balance),
            "paid": float(amt)}
