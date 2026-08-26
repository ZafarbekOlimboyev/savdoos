import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import CreditTxnType, MovementType, PurchaseStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.catalog import Product, Unit
from app.models.purchasing import Purchase, PurchaseItem, Supplier, SupplierLedger, SupplierPayment
from app.models.receiving import Receiving
from app.schemas.purchase import PurchaseCreate, PurchaseOut, SupplierOut

router = APIRouter(tags=["purchases"])


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    return (
        db.query(Supplier)
        .filter(Supplier.company_id == emp.company_id, Supplier.deleted_at.is_(None))
        .order_by(Supplier.name)
        .all()
    )


class SupplierIn(BaseModel):
    name: str
    phone: str | None = None


@router.post("/suppliers", response_model=SupplierOut)
def create_supplier(
    data: SupplierIn,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    s = Supplier(company_id=emp.company_id, name=data.name, phone=data.phone)
    db.add(s)
    db.flush()
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "create", "supplier", s.id, after={"name": s.name})
    db.commit()
    db.refresh(s)
    return s


class SupplierEdit(BaseModel):
    name: str | None = None
    phone: str | None = None


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def edit_supplier(
    supplier_id: uuid.UUID,
    data: SupplierEdit,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    s = db.get(Supplier, supplier_id)
    if not s or s.company_id != emp.company_id:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    if data.name is not None:
        s.name = data.name
    if data.phone is not None:
        s.phone = data.phone
    db.commit()
    db.refresh(s)
    return s


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(
    supplier_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    s = db.get(Supplier, supplier_id)
    if not s or s.company_id != emp.company_id:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    from datetime import datetime, timezone
    s.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/purchases")
def list_purchases(emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    rows = (
        db.query(Purchase, Supplier.name)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .filter(Purchase.company_id == emp.company_id, Purchase.deleted_at.is_(None))
        .order_by(Purchase.purchase_date.desc(), Purchase.doc_no.desc())
        .all()
    )
    return [
        {
            "id": str(p.id),
            "doc_no": p.doc_no,
            "supplier": name,
            "date": p.purchase_date.isoformat(),
            "total": float(p.total),
            "status": p.status.value,
        }
        for p, name in rows
    ]


@router.post("/purchases", response_model=PurchaseOut)
def create_purchase(
    data: PurchaseCreate,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    if data.client_uuid:
        ex = db.query(Purchase).filter(
            Purchase.client_uuid == data.client_uuid, Purchase.company_id == emp.company_id
        ).first()
        if ex:
            return ex
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    sup = db.get(Supplier, data.supplier_id)
    if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    now = datetime.now(timezone.utc)
    seq = db.query(Purchase).filter(Purchase.company_id == emp.company_id).count()
    status = PurchaseStatus.debt if data.status == "debt" else PurchaseStatus.received
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in data.items)

    pur = Purchase(
        doc_no=f"KIR-{1042 + seq + 1}",
        company_id=emp.company_id,
        branch_id=branch.id,
        supplier_id=data.supplier_id,
        employee_id=emp.id,
        purchase_date=date.today(),
        status=status,
        subtotal=total,
        total=total,
        paid_amount=Decimal("0") if status == PurchaseStatus.debt else total,
        client_uuid=data.client_uuid,
    )
    db.add(pur)
    db.flush()

    for i in data.items:
        prod = db.get(Product, i.product_id)
        if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
        qty = Decimal(str(i.qty))
        cost = Decimal(str(i.unit_cost))
        db.add(
            PurchaseItem(
                purchase_id=pur.id, product_id=i.product_id, qty=qty, unit_cost=cost,
                line_total=qty * cost,
            )
        )
        inv = (
            db.query(Inventory)
            .filter(Inventory.product_id == i.product_id, Inventory.branch_id == branch.id)
            .first()
        )
        if inv is None:
            inv = Inventory(product_id=i.product_id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        inv.qty = Decimal(str(inv.qty)) + qty
        inv.updated_at = now
        db.add(
            StockMovement(
                product_id=i.product_id, branch_id=branch.id, type=MovementType.purchase_in,
                qty=qty, unit_cost=cost, balance_after=inv.qty, ref_type="purchase",
                ref_id=pur.id, employee_id=emp.id, created_at=now,
            )
        )

    # qarzga bo'lsa — beruvchi balansi oshadi
    if status == PurchaseStatus.debt:
        sup = db.get(Supplier, data.supplier_id)
        sup.balance = Decimal(str(sup.balance)) + total
        db.add(
            SupplierLedger(
                supplier_id=sup.id, type=CreditTxnType.charge, amount=total,
                balance_after=sup.balance, ref_type="purchase", ref_id=pur.id, created_at=now,
            )
        )

    db.commit()
    db.refresh(pur)
    return pur


# ═══ KIRIM (xarid hujjati) BATAFSIL + TAHRIR ═══
@router.get("/purchases/{purchase_id}")
def purchase_detail(
    purchase_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.view")),
    db: Session = Depends(get_db),
):
    """Bitta kirim + uning jonli mahsulot qatorlari (tahrirlash uchun)."""
    pur = db.get(Purchase, purchase_id)
    if not pur or pur.company_id != emp.company_id or pur.deleted_at is not None:
        raise HTTPException(404, "Kirim topilmadi")
    sup = db.get(Supplier, pur.supplier_id) if pur.supplier_id else None
    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    units = {u.id: u.code for u in db.query(Unit).all()}
    rows = (
        db.query(PurchaseItem, Product.name, Product.unit_id, Product.base_sell_price)
        .join(Product, Product.id == PurchaseItem.product_id)
        .filter(PurchaseItem.purchase_id == pur.id)
        .all()
    )
    items = []
    for it, pname, unit_id, sell in rows:
        inv = None
        if branch:
            inv = (
                db.query(Inventory)
                .filter(Inventory.product_id == it.product_id, Inventory.branch_id == branch.id)
                .first()
            )
        items.append({
            "id": str(it.id), "product_id": str(it.product_id), "name": pname,
            "qty": float(it.qty), "unit_cost": float(it.unit_cost), "line_total": float(it.line_total),
            "sell_price": float(sell or 0),
            "unit": units.get(unit_id, "dona"), "stock": float(inv.qty) if inv else 0.0,
        })
    return {
        "id": str(pur.id), "doc_no": pur.doc_no,
        "supplier": sup.name if sup else "—",
        "supplier_id": str(pur.supplier_id) if pur.supplier_id else None,
        "date": pur.purchase_date.isoformat(), "status": pur.status.value,
        "payment": "credit" if pur.status in (PurchaseStatus.debt, PurchaseStatus.partial) else "cash",
        "subtotal": float(pur.subtotal), "total": float(pur.total), "paid_amount": float(pur.paid_amount or 0),
        "items": items,
    }


class PItemEdit(BaseModel):
    id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    sell_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)  # mahsulot sotish narxi


class PurchaseEdit(BaseModel):
    items: list[PItemEdit] = []       # mavjud qatorlarni qty/narx bilan yangilash
    removed: list[uuid.UUID] = []      # o'chiriladigan qator id'lari
    client_uuid: uuid.UUID | None = None


@router.patch("/purchases/{purchase_id}")
def edit_purchase(
    purchase_id: uuid.UUID,
    data: PurchaseEdit,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    """Kirim mahsulotlarini tahrirlash: qty/narx o'zgartirish yoki qatorni o'chirish.
    Ombor qoldig'i (append-only StockMovement=adjustment), xarid jami va — hali qarz bo'lsa —
    yetkazib beruvchi balansi mos ravishda AVTO to'g'rilanadi. StockMovement immutable —
    eski yozuv o'zgармaydi, faqat kompensatsiya (tuzatish) harakati qo'shiladi."""
    pur = db.get(Purchase, purchase_id)
    if not pur or pur.company_id != emp.company_id or pur.deleted_at is not None:
        raise HTTPException(404, "Kirim topilmadi")
    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    if not branch:
        raise HTTPException(400, "Filial topilmadi")
    sup = db.get(Supplier, pur.supplier_id) if pur.supplier_id else None
    now = datetime.now(timezone.utc)

    existing = {it.id: it for it in db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pur.id).all()}
    for rid in data.removed:
        if rid not in existing:
            raise HTTPException(400, "Qator topilmadi")
    for upd in data.items:
        if upd.id not in existing:
            raise HTTPException(400, "Qator topilmadi")

    _names: dict = {}

    def _pname(pid):
        if pid not in _names:
            p = db.get(Product, pid)
            _names[pid] = p.name if p else str(pid)
        return _names[pid]

    def _reconcile(product_id, delta, cost):
        """inv.qty += delta (ishorali); tuzatish harakati qo'shiladi. Qoldiq manfiy bo'lmasin."""
        if delta == 0:
            return
        inv = (
            db.query(Inventory)
            .filter(Inventory.product_id == product_id, Inventory.branch_id == branch.id)
            .first()
        )
        cur = Decimal(str(inv.qty)) if inv else Decimal("0")
        new_qty = cur + delta
        if new_qty < 0:
            raise HTTPException(400, f"Ombor qoldig'i yetarli emas: {_pname(product_id)} (qoldiq {cur})")
        if inv is None:
            inv = Inventory(product_id=product_id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        inv.qty = new_qty
        inv.updated_at = now
        db.add(StockMovement(
            product_id=product_id, branch_id=branch.id, type=MovementType.adjustment,
            qty=delta, unit_cost=cost, balance_after=inv.qty, ref_type="purchase_edit",
            ref_id=pur.id, employee_id=emp.id, created_at=now,
        ))

    old_total = Decimal(str(pur.total))

    # 1) O'chirish
    for rid in data.removed:
        it = existing.pop(rid)
        _reconcile(it.product_id, -Decimal(str(it.qty)), Decimal(str(it.unit_cost)))
        db.delete(it)

    # 2) Yangilash (qty/narx)
    for upd in data.items:
        it = existing.get(upd.id)
        if it is None:
            continue
        new_qty = Decimal(str(upd.qty))
        new_cost = Decimal(str(upd.unit_cost))
        _reconcile(it.product_id, new_qty - Decimal(str(it.qty)), new_cost)
        it.qty = new_qty
        it.unit_cost = new_cost
        it.line_total = new_qty * new_cost
        # Sotish narxi berilsa — mahsulot kartochkasi ham yangilanadi
        if upd.sell_price is not None and upd.sell_price > 0:
            prod = db.get(Product, it.product_id)
            if prod is not None and Decimal(str(upd.sell_price)) != Decimal(str(prod.base_sell_price)):
                prod.base_sell_price = Decimal(str(upd.sell_price))

    db.flush()
    remaining = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pur.id).all()
    new_total = sum((Decimal(str(it.line_total)) for it in remaining), Decimal("0"))

    # Yetkazib beruvchi qarzini to'g'rilash — faqat hali to'lanmagan qismi (outstanding) o'zgarsa
    paid = Decimal(str(pur.paid_amount or 0))
    old_out = max(Decimal("0"), old_total - paid)
    new_out = max(Decimal("0"), new_total - paid)
    delta_out = new_out - old_out
    if sup is not None and delta_out != 0:
        sup.balance = Decimal(str(sup.balance or 0)) + delta_out
        db.add(SupplierLedger(
            supplier_id=sup.id, type=CreditTxnType.adjustment, amount=delta_out,
            balance_after=sup.balance, ref_type="purchase_edit", ref_id=pur.id, created_at=now,
        ))

    pur.subtotal = new_total
    pur.total = new_total
    if not remaining:
        pur.status = PurchaseStatus.cancelled
        pur.deleted_at = now
    elif new_total <= paid:
        pur.status = PurchaseStatus.received
    elif paid > 0:
        pur.status = PurchaseStatus.partial
    else:
        pur.status = PurchaseStatus.debt

    # Bog'langan Receiving snapshotini yangilaymiz (tarix/hisobot izchil bo'lsin)
    rec = db.query(Receiving).filter(Receiving.purchase_id == pur.id).first()
    if rec is not None:
        umap = {u.id: u.code for u in db.query(Unit).all()}
        fi, tq = [], Decimal("0")
        for it in remaining:
            p = db.get(Product, it.product_id)
            fi.append({"product_id": str(it.product_id), "name": p.name if p else "",
                       "qty": float(it.qty), "unit_cost": float(it.unit_cost), "ai_name": None,
                       "unit": umap.get(p.unit_id if p else None, "dona")})
            tq += Decimal(str(it.qty))
        rec.final_items = fi
        rec.total_types = len(fi)
        rec.total_qty = tq

    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "edit", "purchase", pur.id, after={"total": float(new_total), "items": len(remaining)})
    db.commit()
    return {"ok": True, "id": str(pur.id), "total": float(new_total),
            "cancelled": len(remaining) == 0, "status": pur.status.value}


class SupplierPaymentIn(BaseModel):
    amount: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    method: str = "cash"
    client_uuid: uuid.UUID | None = None   # offline idempotentlik (qayta yuborishда ikki marta to'lamaslik)


@router.post("/suppliers/{supplier_id}/payments")
def pay_supplier(
    supplier_id: uuid.UUID,
    data: SupplierPaymentIn,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    if data.method not in {"cash", "card", "qr"}:
        raise HTTPException(400, f"Noto'g'ri to'lov usuli: {data.method}")
    # Idempotentlik — offline qayta yuborish ikki marta to'lamasin (mijoz pay_credit bilan izchil)
    if data.client_uuid:
        ex = (
            db.query(SupplierPayment)
            .filter(SupplierPayment.client_uuid == data.client_uuid, SupplierPayment.supplier_id == sup.id)
            .first()
        )
        if ex:
            return {"supplier_id": str(sup.id), "balance": float(sup.balance), "paid": float(ex.amount), "duplicate": True}
    now = datetime.now(timezone.utc)
    # Overpayment — qarzdan oshig'i qabul qilinmaydi (mijoz pay_credit bilan izchil)
    bal = Decimal(str(sup.balance or 0))
    amt = min(Decimal(str(data.amount)), bal) if bal > 0 else Decimal("0")
    if amt <= 0:
        raise HTTPException(400, "Bu yetkazib beruvchiga qarz yo'q")
    pay = SupplierPayment(supplier_id=sup.id, amount=amt, method=data.method, paid_at=now,
                          employee_id=emp.id, created_at=now, client_uuid=data.client_uuid)
    db.add(pay)
    db.flush()
    sup.balance = bal - amt
    db.add(SupplierLedger(
        supplier_id=sup.id, type=CreditTxnType.payment, amount=-amt,
        balance_after=sup.balance, ref_type="payment", ref_id=pay.id, created_at=now,
    ))
    # To'lovni eng eski qarzdagi xaridlarga taqsimlaymiz (paid_amount/status yangilanadi)
    remaining = amt
    debts = (
        db.query(Purchase)
        .filter(Purchase.company_id == emp.company_id, Purchase.supplier_id == sup.id,
                Purchase.status == PurchaseStatus.debt)
        .order_by(Purchase.purchase_date, Purchase.created_at)
        .all()
    )
    for pur in debts:
        if remaining <= 0:
            break
        due = Decimal(str(pur.total)) - Decimal(str(pur.paid_amount or 0))
        if due <= 0:
            pur.status = PurchaseStatus.received
            continue
        pay_part = min(due, remaining)
        pur.paid_amount = Decimal(str(pur.paid_amount or 0)) + pay_part
        remaining -= pay_part
        if Decimal(str(pur.paid_amount)) >= Decimal(str(pur.total)):
            pur.status = PurchaseStatus.received
    db.commit()
    return {"supplier_id": str(sup.id), "balance": float(sup.balance), "paid": float(amt)}


@router.get("/suppliers/{supplier_id}/ledger")
def supplier_ledger(
    supplier_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.view")),
    db: Session = Depends(get_db),
):
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.company_id != emp.company_id:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    rows = (
        db.query(SupplierLedger)
        .filter(SupplierLedger.supplier_id == supplier_id)
        .order_by(SupplierLedger.created_at.desc())
        .all()
    )
    return [
        {"type": r.type.value, "amount": float(r.amount), "balance_after": float(r.balance_after),
         "ref_type": r.ref_type, "at": r.created_at}
        for r in rows
    ]


@router.get("/suppliers/{supplier_id}")
def supplier_detail(
    supplier_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.view")),
    db: Session = Depends(get_db),
):
    """Yetkazib beruvchi batafsili: qarz (balans), xaridlar tarixi, yetkazgan mahsulotlar."""
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")

    # Xarid hujjatlari (so'nggi)
    purchases = (
        db.query(Purchase)
        .filter(Purchase.company_id == emp.company_id, Purchase.supplier_id == supplier_id,
                Purchase.deleted_at.is_(None))
        .order_by(Purchase.purchase_date.desc(), Purchase.doc_no.desc())
        .all()
    )
    purchase_count = len(purchases)
    total_purchased = float(sum((p.total for p in purchases), Decimal("0")))
    recent = [
        {"id": str(p.id), "doc_no": p.doc_no, "date": p.purchase_date.isoformat(),
         "total": float(p.total), "status": p.status.value}
        for p in purchases[:40]
    ]

    # Yetkazgan mahsulotlar (agregat: nom + jami miqdor + jami summa)
    prod_rows = (
        db.query(Product.name,
                 func.coalesce(func.sum(PurchaseItem.qty), 0),
                 func.coalesce(func.sum(PurchaseItem.qty * PurchaseItem.unit_cost), 0))
        .join(PurchaseItem, PurchaseItem.product_id == Product.id)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.company_id == emp.company_id, Purchase.supplier_id == supplier_id,
                Purchase.deleted_at.is_(None))
        .group_by(Product.id, Product.name)
        .order_by(func.sum(PurchaseItem.qty * PurchaseItem.unit_cost).desc())
        .all()
    )
    products = [
        {"name": name, "qty": float(qty or 0), "cost": float(cost or 0)}
        for name, qty, cost in prod_rows
    ]

    return {
        "id": str(sup.id), "name": sup.name, "phone": sup.phone,
        "balance": float(sup.balance),
        "purchase_count": purchase_count,
        "total_purchased": total_purchased,
        "product_types": len(products),
        "products": products,
        "recent_purchases": recent,
    }
