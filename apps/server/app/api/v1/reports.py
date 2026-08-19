from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Category, Product
from app.models.inventory import Inventory
from app.models.sales import Sale, SaleItem, SalePayment
from app.models.settings import Setting

router = APIRouter(tags=["reports"])


def _range(period: str):
    now = datetime.now(timezone.utc)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "all":
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)  # today


@router.get("/reports/summary")
def summary(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start = _range("today")
    total = db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.company_id == emp.company_id, Sale.sold_at >= start
    ).scalar()
    cost = db.query(func.coalesce(func.sum(Sale.cost_total), 0)).filter(
        Sale.company_id == emp.company_id, Sale.sold_at >= start
    ).scalar()
    tx = db.query(Sale).filter(Sale.company_id == emp.company_id, Sale.sold_at >= start).count()
    pay_rows = (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.company_id == emp.company_id, Sale.sold_at >= start)
        .group_by(SalePayment.method_code)
        .all()
    )
    return {
        "today_sales": float(total),
        "today_profit": float(total) - float(cost),
        "tx_count": tx,
        "payment_breakdown": [{"method": m, "amount": float(a)} for m, a in pay_rows],
    }


@router.get("/reports/pnl")
def pnl(period: str = "month", emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start = _range(period)
    gross = float(db.query(func.coalesce(func.sum(Sale.subtotal), 0)).filter(
        Sale.company_id == emp.company_id, Sale.sold_at >= start).scalar())
    discount = float(db.query(func.coalesce(func.sum(Sale.discount_total), 0)).filter(
        Sale.company_id == emp.company_id, Sale.sold_at >= start).scalar())
    cogs = float(db.query(func.coalesce(func.sum(Sale.cost_total), 0)).filter(
        Sale.company_id == emp.company_id, Sale.sold_at >= start).scalar())
    net = gross - discount
    gross_profit = net - cogs
    opex = round(net * 0.09)
    net_profit = gross_profit - opex
    _tax = db.query(Setting).filter(Setting.company_id == emp.company_id, Setting.key == "tax").first()
    _tv = (_tax.value if _tax else {}) or {}
    _rate = float(_tv.get("rate", 12) or 0) if _tv.get("vat_on") else 0.0
    vat = round(net * _rate / (100 + _rate)) if _rate else 0
    margin = round(net_profit / net * 100) if net else 0
    return {
        "period": period,
        "gross": gross, "discount": discount, "net": net, "cogs": cogs,
        "gross_profit": gross_profit, "opex": opex, "net_profit": net_profit,
        "vat": vat, "vat_rate": _rate, "margin": margin,
    }


@router.get("/reports/top-products")
def top_products(limit: int = 5, period: str = "month", emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start = _range(period)
    rows = (
        db.query(
            SaleItem.name_snapshot,
            func.sum(SaleItem.qty).label("qty"),
            func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost).label("profit"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == emp.company_id, Sale.sold_at >= start)
        .group_by(SaleItem.name_snapshot)
        .order_by(func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost).desc())
        .limit(limit)
        .all()
    )
    return [{"name": n, "qty": float(q), "profit": float(p or 0)} for n, q, p in rows]


@router.get("/reports/sales-dynamics")
def sales_dynamics(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start = _range("today") - timedelta(days=6)
    rows = (
        db.query(func.date(Sale.sold_at).label("d"), func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.company_id == emp.company_id, Sale.sold_at >= start)
        .group_by(func.date(Sale.sold_at))
        .order_by(func.date(Sale.sold_at))
        .all()
    )
    return [{"day": str(d), "sales": float(s)} for d, s in rows]


@router.get("/reports/dashboard")
def dashboard(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    from app.models.customers import Customer, CustomerPayment

    today = datetime.now(timezone.utc).date()
    day_start = _range("today")

    debt_total = float(db.query(func.coalesce(func.sum(Customer.credit_balance), 0)).filter(
        Customer.company_id == emp.company_id).scalar())
    debtors = db.query(Customer).filter(
        Customer.company_id == emp.company_id, Customer.credit_balance > 0).count()
    paid_today = float(db.query(func.coalesce(func.sum(CustomerPayment.amount), 0)).filter(
        func.date(CustomerPayment.paid_at) == today).scalar())

    low = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Inventory.qty <= Inventory.min_qty)
        .order_by(Inventory.qty)
        .limit(6)
        .all()
    )
    wk_start = day_start - timedelta(days=6)
    weekly = (
        db.query(func.date(Sale.sold_at), func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.company_id == emp.company_id, Sale.sold_at >= wk_start)
        .group_by(func.date(Sale.sold_at))
        .order_by(func.date(Sale.sold_at))
        .all()
    )
    pay = (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.company_id == emp.company_id, Sale.sold_at >= day_start)
        .group_by(SalePayment.method_code)
        .all()
    )
    today_total = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.company_id == emp.company_id, Sale.sold_at >= day_start).scalar())
    today_cost = float(db.query(func.coalesce(func.sum(Sale.cost_total), 0)).filter(
        Sale.company_id == emp.company_id, Sale.sold_at >= day_start).scalar())
    return {
        "today_sales": today_total,
        "today_profit": today_total - today_cost,
        "debt": {"total": debt_total, "debtors": debtors, "paid_today": paid_today},
        "low_stock": [{"name": n, "qty": float(q), "min": float(m)} for n, q, m in low],
        "weekly": [{"day": str(d), "sales": float(s)} for d, s in weekly],
        "payments": [{"method": m, "amount": float(a)} for m, a in pay],
    }


@router.get("/reports/alerts")
def alerts(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    low = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Inventory.qty <= Inventory.min_qty)
        .count()
    )
    loss = (
        db.query(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == emp.company_id, SaleItem.unit_price < SaleItem.unit_cost)
        .count()
    )
    return {"low_stock": low, "loss_making": loss}


@router.get("/reports/categories")
def report_categories(period: str = "month", emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start = _range(period)
    rows = (
        db.query(
            Category.name,
            func.sum(SaleItem.line_total),
            func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost),
        )
        .join(Product, Product.id == SaleItem.product_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Category, Category.id == Product.category_id)
        .filter(Sale.company_id == emp.company_id, Sale.sold_at >= start)
        .group_by(Category.name)
        .all()
    )
    out = []
    for n, s, p in rows:
        s = float(s or 0); p = float(p or 0)
        out.append({"name": n, "sales": s, "profit": p, "margin": round(p / s * 100) if s else 0})
    out.sort(key=lambda x: x["profit"], reverse=True)
    return out


@router.get("/reports/alerts/detail")
def alerts_detail(type: str = "low", emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    if type == "low":
        rows = (
            db.query(Product.name, Inventory.qty, Inventory.min_qty)
            .join(Inventory, Inventory.product_id == Product.id)
            .filter(Product.company_id == emp.company_id, Inventory.qty <= Inventory.min_qty)
            .order_by(Inventory.qty)
            .all()
        )
        return [{"name": n, "note": f"Minimal: {float(m):g} dona", "right": f"{float(q):g} dona"} for n, q, m in rows]
    if type == "loss":
        rows = (
            db.query(SaleItem.name_snapshot, SaleItem.unit_price, SaleItem.unit_cost)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(Sale.company_id == emp.company_id, SaleItem.unit_price < SaleItem.unit_cost)
            .limit(50)
            .all()
        )
        return [{"name": n, "note": f"Narx {float(pr):g} < tannarx {float(co):g}", "right": f"−{float(co - pr):g}"} for n, pr, co in rows]
    return []
