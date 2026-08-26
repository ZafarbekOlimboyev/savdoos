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
from app.models.catalog import Product
from app.models.purchasing import Purchase, PurchaseItem, Supplier, SupplierLedger, SupplierPayment
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
