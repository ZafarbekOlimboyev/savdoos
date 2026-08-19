"""Savdo yaratish — chek + qatorlar (snapshot) + ombor harakati + qarz daftari.

Bitta tranzaksiyada: sale, sale_items (narx/tannarx muzlatiladi), sale_payment,
stock_movements (sale_out), inventory kamayadi, nasiya bo'lsa credit_transactions.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.customers import CreditTransaction, Customer
from app.models.enums import CreditTxnType, MovementType, ShiftStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.sales import Sale, SaleItem, SalePayment
from app.models.shifts import Shift
from app.schemas.sales import SaleCreate


def _D(x) -> Decimal:
    return Decimal(str(x or 0))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_sale(db: Session, emp, data: SaleCreate) -> Sale:
    # 1) Idempotentlik — offline kassa qayta push qilsa ikki marta yozilmaydi
    # (kompaniya bo'yicha cheklangan — boshqa tenant'ning client_uuid'i mos kelmasin)
    if data.client_uuid:
        existing = db.query(Sale).filter(
            Sale.client_uuid == data.client_uuid, Sale.company_id == emp.company_id
        ).first()
        if existing:
            return existing

    if not data.items:
        raise HTTPException(400, "Savat bo'sh")

    if data.payment_method not in {"cash", "card", "qr", "credit"}:
        raise HTTPException(400, f"Noto'g'ri to'lov usuli: {data.payment_method}")

    branch = (
        db.query(Branch)
        .filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None))
        .first()
    )
    if not branch:
        raise HTTPException(400, "Filial topilmadi")

    shift = (
        db.query(Shift)
        .filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open)
        .first()
    )
    if shift is None:
        # Sozlamalarda "smena majburiy" yoqilgan bo'lsa — ochiq smenasiz savdo taqiqlanadi
        from app.models.settings import Setting
        _sec = db.query(Setting).filter(
            Setting.company_id == emp.company_id, Setting.key == "security"
        ).first()
        if ((_sec.value if _sec else {}) or {}).get("force_shift"):
            raise HTTPException(400, "Ochiq smena yo'q — avval smenani oching")

    now = _now()
    sale = Sale(
        company_id=emp.company_id,
        branch_id=branch.id,
        cashier_id=emp.id,
        shift_id=shift.id if shift else None,
        customer_id=data.customer_id,
        subtotal=Decimal("0"),
        discount_total=_D(data.discount_total),
        total=Decimal("0"),
        cost_total=Decimal("0"),
        tax_total=Decimal("0"),
        sold_at=now,
        receipt_no="TMP",
        client_uuid=data.client_uuid,
    )
    db.add(sale)
    db.flush()  # sale.id kerak

    subtotal = Decimal("0")
    cost_total = Decimal("0")
    items_discount = Decimal("0")
    for it in data.items:
        p = db.get(Product, it.product_id)
        if not p or p.company_id != emp.company_id or p.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {it.product_id}")
        qty = _D(it.qty).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if qty <= 0:
            raise HTTPException(400, "Miqdor noto'g'ri")
        price = _D(p.base_sell_price)
        ucost = _D(p.base_buy_price)
        idisc = _D(it.discount)
        if idisc > qty * price:
            raise HTTPException(400, "Chegirma mahsulot summasidan oshdi")
        line = qty * price - idisc

        inv = (
            db.query(Inventory)
            .filter(Inventory.product_id == p.id, Inventory.branch_id == branch.id)
            .first()
        )
        available = _D(inv.qty) if inv is not None else Decimal("0")
        if qty > available:
            raise HTTPException(400, f"Yetarli qoldiq yo'q: {p.name} (qoldiq: {available})")

        subtotal += qty * price
        cost_total += qty * ucost
        items_discount += idisc

        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=p.id,
                name_snapshot=p.name,
                article_snapshot=p.article_code,
                qty=qty,
                unit_price=price,          # SNAPSHOT
                unit_cost=ucost,           # SNAPSHOT (marja analitikasi)
                discount=idisc,
                tax_rate=p.tax_rate,
                line_total=line,
                unit_id=p.unit_id,
            )
        )

        if inv is None:
            inv = Inventory(product_id=p.id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        inv.qty = _D(inv.qty) - qty
        inv.updated_at = now
        db.add(
            StockMovement(
                product_id=p.id,
                branch_id=branch.id,
                type=MovementType.sale_out,
                qty=-qty,
                unit_cost=ucost,
                balance_after=inv.qty,
                ref_type="sale",
                ref_id=sale.id,
                employee_id=emp.id,
                created_at=now,
            )
        )

    total = subtotal - items_discount - _D(data.discount_total)
    if total < 0:
        raise HTTPException(400, "Chegirma jami summadan oshib ketdi")
    sale.subtotal = subtotal
    sale.cost_total = cost_total
    sale.total = total

    seq = db.query(Sale).filter(Sale.company_id == emp.company_id).count()
    sale.receipt_no = f"#{1287 + seq}"
    sale.uid = now.strftime("%y%m%d") + str(1287 + seq)

    method = data.payment_method
    given = _D(data.given_amount) if data.given_amount is not None else total
    if method == "cash" and given < total:
        raise HTTPException(400, "Berilgan summa yetarli emas")
    db.add(
        SalePayment(
            sale_id=sale.id,
            method_code=method,
            amount=total,
            given_amount=given if method == "cash" else None,
            change_amount=(given - total) if method == "cash" else None,
            paid_at=now,
        )
    )

    # Nasiya (qarz) — mijoz balansiga yoziladi
    if method == "credit":
        if not data.customer_id:
            raise HTTPException(400, "Nasiya uchun mijoz tanlanishi shart")
        cust = db.get(Customer, data.customer_id)
        if not cust or cust.company_id != emp.company_id:
            raise HTTPException(400, "Mijoz topilmadi")
        cust.credit_balance = _D(cust.credit_balance) + total
        db.add(
            CreditTransaction(
                customer_id=cust.id,
                type=CreditTxnType.charge,
                amount=total,
                balance_after=cust.credit_balance,
                sale_id=sale.id,
                employee_id=emp.id,
                created_at=now,
            )
        )

    db.commit()
    db.refresh(sale)
    return sale
