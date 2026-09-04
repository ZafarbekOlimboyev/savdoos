import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import CashMovementType, ShiftStatus
from app.models.org import Branch
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift

router = APIRouter(tags=["shifts"])


class OpenShift(BaseModel):
    opening_cash: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)  # Numeric(14,2) overflow oldi


class CloseShift(BaseModel):
    counted_cash: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)  # Numeric(14,2) overflow oldi


class CashMove(BaseModel):
    type: str = "payin"          # payin | payout | expense
    amount: float = Field(default=0, gt=0, le=1e9, allow_inf_nan=False)
    reason: str | None = Field(default=None, max_length=200)
    client_uuid: uuid.UUID | None = None   # offline idempotentlik (retry'да ikki marta emas)


@router.post("/shifts/{shift_id}/cash")
def add_cash_movement(
    shift_id: uuid.UUID,
    data: CashMove,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    # Smena qatorini qulflaymiz — kassa balansi tekshiruvi va yozuv ketma-ket bo'lsin
    # (bir vaqtдаги ikki chiqim kassani manfiyга tushirmasin). SQLite'да no-op.
    s = db.query(Shift).filter(Shift.id == shift_id).with_for_update().first()
    if not s or s.cashier_id != emp.id:
        raise HTTPException(404, "Smena topilmadi")
    if s.status != ShiftStatus.open:
        raise HTTPException(400, "Ochiq smena topilmadi")
    if data.type not in {"payin", "payout", "expense", "collection"}:
        raise HTTPException(400, "Noto'g'ri tur")
    # DEDUP: shu client_uuid bilan harakat allaqачон bo'lsa — qayta yozмаймиз (offline retry).
    if data.client_uuid:
        dup = db.query(CashMovement).filter(
            CashMovement.shift_id == s.id, CashMovement.client_uuid == data.client_uuid).first()
        if dup:
            return {"ok": True, "duplicate": True}
    # Chiqim (payout/expense/collection) kassada mavjud naqddан oshmasin — kassa manfiyга tushmasin.
    if data.type in {"payout", "expense", "collection"}:
        cash_sales = float(db.query(func.coalesce(func.sum(SalePayment.amount), 0))
                           .join(Sale, Sale.id == SalePayment.sale_id)
                           .filter(Sale.shift_id == s.id, SalePayment.method_code == "cash").scalar() or 0)
        rows = (db.query(CashMovement.type, func.coalesce(func.sum(CashMovement.amount), 0))
                .filter(CashMovement.shift_id == s.id).group_by(CashMovement.type).all())
        payin = sum(float(a) for t, a in rows if t == CashMovementType.payin)
        out = sum(float(a) for t, a in rows if t != CashMovementType.payin)
        till = float(s.opening_cash) + cash_sales + payin - out
        if float(data.amount) > till + 0.5:
            raise HTTPException(400, f"Kassada yetarli naqd yo'q (mavjud: {till:g})")
    mtype = CashMovementType(data.type)
    _mv = CashMovement(
        shift_id=s.id, type=mtype, amount=Decimal(str(data.amount)),
        reason=data.reason, employee_id=emp.id, created_at=datetime.now(timezone.utc),
        client_uuid=data.client_uuid,
    )
    db.add(_mv)
    from sqlalchemy.exc import IntegrityError as _IE
    from app.services.cash.errors import CashPostingError as _CPE
    try:
        db.flush()
        # Phase 2b dual-write (guarded): payin->IN·CASH_IN, payout->OUT·CASH_OUT, expense->OUT·EXPENSE,
        # collection->OUT·CASH_OUT. SQLite/xaritalanmagan filialда no-op; source(CashMovement)+ledger
        # BIR tranzaksiyada (atomik). cashops.py `/cash/ops` bilan izchil (u faqat payin/expense/
        # collection'ni qo'llaydi; bu endpoint payout'ни ham — kassir manual naqd topshirishi).
        from app.services.cash import retrofit as _cr
        _cr.on_cash_op(db, emp, branch_id=s.branch_id, kind=data.type, amount=data.amount, movement_id=_mv.id)
        db.commit()
    except _IE:  # bir vaqtдаги dublikat — DB unique indeksi (ux_cashmov_client_uuid) ushlади
        db.rollback()
        return {"ok": True, "duplicate": True}
    except _CPE:
        # Konkurrent dublikat idempotentligi (receiving.py bilan izchil): yutqazgan oqim ledger
        # OUT-sufficiency'да CashPostingError olishi mumkin (g'olib kassani kamaytirib commit qilса),
        # client_uuid guard'gача yetмай. Shu client_uuid'li harakat allaqачон bo'lса — idempotent
        # dublikat; aks holда HAQIQIY domain-xato (yetarsiz naqd) -> qayta ko'taramiz.
        db.rollback()
        if data.client_uuid:
            dup = db.query(CashMovement).filter(
                CashMovement.shift_id == s.id, CashMovement.client_uuid == data.client_uuid).first()
            if dup:
                return {"ok": True, "duplicate": True}
        raise
    return {"ok": True}


@router.get("/shifts/{shift_id}/cash")
def list_cash_movements(
    shift_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    _s = db.get(Shift, shift_id)
    if not _s or _s.cashier_id != emp.id:
        raise HTTPException(404, "Smena topilmadi")
    rows = db.query(CashMovement).filter(CashMovement.shift_id == shift_id).order_by(CashMovement.created_at.desc()).all()
    return [{"type": m.type.value, "amount": float(m.amount), "reason": m.reason, "at": m.created_at} for m in rows]


CASH_LABEL = {"payin": "Naqd kiritish", "payout": "Naqd topshirish", "expense": "Xarajat", "collection": "Inkassa", "opening": "Smena ochildi"}


@router.get("/shifts/{shift_id}/summary")
def shift_summary(
    shift_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    s = db.get(Shift, shift_id)
    if not s or s.cashier_id != emp.id:
        raise HTTPException(404, "Smena topilmadi")
    rows = (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.shift_id == s.id)
        .group_by(SalePayment.method_code)
        .all()
    )
    by_method = {m: float(a) for m, a in rows}
    total_sales = sum(by_method.values())
    receipts = db.query(Sale).filter(Sale.shift_id == s.id).count()
    naqd = by_method.get("cash", 0.0)

    payin = payout = 0.0
    ops = []
    for m in db.query(CashMovement).filter(CashMovement.shift_id == s.id).order_by(CashMovement.created_at).all():
        amt = float(m.amount)
        inc = m.type == CashMovementType.payin
        if inc:
            payin += amt
        else:
            payout += amt
        ops.append({"title": CASH_LABEL.get(m.type.value, m.type.value) + (f" · {m.reason}" if m.reason else ""),
                    "at": m.created_at, "amount": amt, "in": inc})

    # QA SHIFT-4: YOPIQ smena uchun MUZLATILGAN expected_cash ishlatiladi (shifts_overview + Z-hisobot
    # bilan IZCHIL). Ilgari summary status'dan qat'i nazar LIVE hisoblardi — yopilgach kech sinxronlangan
    # offline savdo (PAY-02 sold_at oynasi) live'да chiqib, overview'даги muzlatilgan qiymatдан farq qilardi.
    if s.status == ShiftStatus.closed and s.expected_cash is not None:
        expected = float(s.expected_cash)
    else:
        expected = float(s.opening_cash) + naqd + payin - payout
    return {
        "opening": float(s.opening_cash),
        "total_sales": total_sales,
        "receipts": receipts,
        "by_method": by_method,
        "naqd_sales": naqd,
        "payin": payin,
        "payout": payout,
        "expected": expected,
        "opened_at": s.opened_at,
        "status": s.status.value,
        "ops": ops,
    }


@router.get("/shifts/overview")
def shifts_overview(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Ega/menejer NAZORATI: barcha kassirlar smenаsi (ochiq + so'nggi yopilganlar).
    Har smena: kassir, filial, vaqt, savdo, kutilgan/sanalgan naqd, farq (kam/ortiq)."""
    from app.core.deps import visible_branches
    cid = emp.company_id
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali smenalari
    q = (
        db.query(Shift, Employee.full_name, Branch.name)
        .join(Employee, Employee.id == Shift.cashier_id)
        .outerjoin(Branch, Branch.id == Shift.branch_id)
        .filter(Employee.company_id == cid)
    )
    if _bset is not None:
        q = q.filter(Shift.branch_id.in_(_bset))
    rows = q.order_by(Shift.opened_at.desc()).limit(50).all()
    ids = [s.id for s, _, _ in rows]
    sales_map: dict = {}
    receipts_map: dict = {}
    cash_map: dict = {}
    move_in: dict = {}
    move_out: dict = {}
    if ids:
        for sid, total, cnt in (
            db.query(Sale.shift_id, func.coalesce(func.sum(Sale.total), 0), func.count(Sale.id))
            .filter(Sale.shift_id.in_(ids)).group_by(Sale.shift_id).all()
        ):
            sales_map[sid] = float(total or 0)
            receipts_map[sid] = int(cnt or 0)
        for sid, camt in (
            db.query(Sale.shift_id, func.coalesce(func.sum(SalePayment.amount), 0))
            .join(SalePayment, SalePayment.sale_id == Sale.id)
            .filter(Sale.shift_id.in_(ids), SalePayment.method_code == "cash")
            .group_by(Sale.shift_id).all()
        ):
            cash_map[sid] = float(camt or 0)
        for sid, mtype, amt in (
            db.query(CashMovement.shift_id, CashMovement.type, func.coalesce(func.sum(CashMovement.amount), 0))
            .filter(CashMovement.shift_id.in_(ids)).group_by(CashMovement.shift_id, CashMovement.type).all()
        ):
            if mtype == CashMovementType.payin:
                move_in[sid] = move_in.get(sid, 0.0) + float(amt)
            else:
                move_out[sid] = move_out.get(sid, 0.0) + float(amt)

    out = []
    open_count = 0
    for s, cashier, branch in rows:
        is_open = s.status == ShiftStatus.open
        if is_open:
            open_count += 1
            expected = float(s.opening_cash) + cash_map.get(s.id, 0.0) + move_in.get(s.id, 0.0) - move_out.get(s.id, 0.0)
            counted = None
            diff = None
        else:
            expected = float(s.expected_cash or 0)
            counted = float(s.counted_cash or 0)
            diff = float(s.difference or 0)
        out.append({
            "id": str(s.id), "cashier": cashier, "branch": branch,
            "opened_at": s.opened_at, "closed_at": s.closed_at,
            "opening_cash": float(s.opening_cash),
            "sales": sales_map.get(s.id, 0.0), "receipts": receipts_map.get(s.id, 0),
            "expected": expected, "counted": counted, "difference": diff,
            "status": s.status.value,
        })
    return {"shifts": out, "open_count": open_count}


@router.get("/shifts/current")
def current_shift(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    s = (
        db.query(Shift)
        .filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open)
        .first()
    )
    if not s:
        return None
    return {"id": str(s.id), "opened_at": s.opened_at, "opening_cash": float(s.opening_cash)}


@router.post("/shifts/open")
def open_shift(data: OpenShift, emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    if db.query(Shift).filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open).first():
        raise HTTPException(400, "Ochiq smena allaqachon mavjud")
    # QA RET-6: filial tanlash actor_branch bilan IZCHIL (order_by(created_at) + is_active, 3-bosqichli
    # fallback) — ilgari order_by/is_active-siz .first() NODETERMINISTIK edi va smena filialini Return/
    # payout (actor_branch) filialidan farqlantirib, ko'p-filialда naqd qaytarish payout'i boshqa filialга
    # tushishi mumkin edi. Endi savdo/qaytarish YOZUV filiali bilan bir xil.
    from app.core.deps import actor_branch as _ab
    branch = _ab(emp, db)
    if not branch:
        raise HTTPException(400, "Filial topilmadi — avval filial yarating")
    s = Shift(
        branch_id=branch.id,
        cashier_id=emp.id,
        opened_at=datetime.now(timezone.utc),
        opening_cash=data.opening_cash,
        status=ShiftStatus.open,
    )
    db.add(s)
    try:
        db.flush()
        # Phase 2b dual-write (guarded): cash.shift ochamiz (+ opening float). SQLite/xaritalanmagan
        # filialда no-op. IntegrityError shu try'да tutiladi (bir vaqtдаги ikkinchi ochish).
        from app.services.cash import retrofit as _cr
        _cr.on_shift_open(db, emp, branch_id=branch.id, legacy_shift_id=s.id, opening_cash=data.opening_cash)
        db.commit()
    except IntegrityError:
        # Bir vaqtда ikkinchi oyna smena ochdi (ux_shifts_cashier_open) — mavjudini qaytaramiz.
        db.rollback()
        ex = db.query(Shift).filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open).first()
        if ex:
            return {"id": str(ex.id), "opened_at": ex.opened_at}
        raise HTTPException(400, "Ochiq smena allaqachon mavjud")
    db.refresh(s)
    return {"id": str(s.id), "opened_at": s.opened_at}


@router.post("/shifts/{shift_id}/close")
def close_shift(
    shift_id: uuid.UUID,
    data: CloseShift,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    # QA SHIFT-1: smena qatorini FOR UPDATE bilan QULFLAYMIZ — add_cash_movement/cash_op/cash-refund
    # (hammasi smenani qulflaydi) bilan SERIALIZATSIYA. Ilgari db.get (qulfsiz) edi: yopish paytida
    # commit bo'lgan naqd harakati/savdo muzlatilgan expected_cash'dan tushib qolib (TOCTOU), Z-hisobot
    # soxta ortiqcha/kamomad berardi. Qulf FAQAT shift qatoriда (boshqa lock yo'q) — deadlock bermaydi.
    # Qulf + status qayta-tekshiruvi double-close'ni ham to'sadi (ikkinchisi 'closed' ko'radi).
    s = db.query(Shift).filter(Shift.id == shift_id).with_for_update().first()
    if not s or s.cashier_id != emp.id:
        raise HTTPException(404, "Smena topilmadi")
    if s.status != ShiftStatus.open:
        raise HTTPException(400, "Smena allaqachon yopilgan")
    # tizim kutgan naqd = ochilish + smenadagi naqd savdolar
    cash = (
        db.query(SalePayment)
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.shift_id == s.id, SalePayment.method_code == "cash")
        .all()
    )
    expected = Decimal(str(s.opening_cash)) + sum(Decimal(str(p.amount)) for p in cash)
    for m in db.query(CashMovement).filter(CashMovement.shift_id == s.id).all():
        if m.type == CashMovementType.payin:
            expected += Decimal(str(m.amount))
        elif m.type in (CashMovementType.payout, CashMovementType.expense, CashMovementType.collection):
            expected -= Decimal(str(m.amount))
    s.counted_cash = Decimal(str(data.counted_cash))
    s.expected_cash = expected
    s.difference = s.counted_cash - expected
    s.closed_at = datetime.now(timezone.utc)
    s.status = ShiftStatus.closed
    # Phase 2b dual-write (guarded): cash.shift ni yopamiz + reconciliation snapshot. SQLite'da no-op.
    from app.services.cash import retrofit as _cr
    _cr.on_shift_close(db, emp, branch_id=s.branch_id, counted_cash=data.counted_cash)
    db.commit()
    return {
        "id": str(s.id),
        "expected_cash": float(expected),
        "counted_cash": float(s.counted_cash),
        "difference": float(s.difference),
    }
