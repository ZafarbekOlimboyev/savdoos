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


@router.get("/reports/overview")
def overview(period: str = "week", emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Dashboard uchun to'liq davr-analitikasi: KPI+delta, 2-chiziq seriya (savdo+foyda),
    to'lov usullari, top mahsulotlar, kassirlar, so'nggi savdolar."""
    now = datetime.now(timezone.utc)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        start, prev_start, prev_end = day0, day0 - timedelta(days=1), day0
    elif period == "month":
        start = day0.replace(day=1)
        prev_end = start
        prev_start = (start - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # week = so'nggi 7 kun
        period = "week"
        start = day0 - timedelta(days=6)
        prev_start, prev_end = start - timedelta(days=7), start
    cid = emp.company_id

    def agg(s, e):
        row = db.query(
            func.coalesce(func.sum(Sale.total), 0),
            func.coalesce(func.sum(Sale.cost_total), 0),
            func.count(Sale.id),
        ).filter(Sale.company_id == cid, Sale.sold_at >= s, Sale.sold_at < e).one()
        return float(row[0]), float(row[1]), int(row[2])

    total, cost, tx = agg(start, now + timedelta(seconds=1))
    p_total, p_cost, p_tx = agg(prev_start, prev_end)
    profit, p_profit = total - cost, p_total - p_cost
    avg = total / tx if tx else 0.0
    p_avg = p_total / p_tx if p_tx else 0.0

    def delta(cur, prev):
        return round((cur - prev) / prev * 100, 1) if prev else (0.0 if not cur else 100.0)

    # ── Seriya (savdo + foyda) davr bo'yicha ──
    rows = db.query(Sale.sold_at, Sale.total, Sale.cost_total).filter(
        Sale.company_id == cid, Sale.sold_at >= start, Sale.sold_at < now + timedelta(seconds=1)
    ).all()
    buckets: dict = {}
    order: list = []
    for sold_at, tot, cst in rows:
        if period == "day":
            key = sold_at.hour
            label = f"{key:02d}:00"
        elif period == "month":
            key = (sold_at.day - 1) // 7 + 1
            label = str(key)
        else:
            key = sold_at.date().isoformat()
            label = key
        if key not in buckets:
            buckets[key] = {"label": label, "sales": 0.0, "profit": 0.0, "key": key}
            order.append(key)
        buckets[key]["sales"] += float(tot)
        buckets[key]["profit"] += float(tot) - float(cst)
    if period == "week":
        # 7 kunning hammasini ko'rsatamiz (bo'sh kunlar ham)
        buckets, order = {}, []
        for i in range(7):
            d = (start + timedelta(days=i)).date().isoformat()
            buckets[d] = {"label": d, "sales": 0.0, "profit": 0.0, "key": d}
            order.append(d)
        for sold_at, tot, cst in rows:
            d = sold_at.date().isoformat()
            if d in buckets:
                buckets[d]["sales"] += float(tot)
                buckets[d]["profit"] += float(tot) - float(cst)
    order = sorted(order)
    series = {
        "labels": [buckets[k]["label"] for k in order],
        "sales": [round(buckets[k]["sales"], 2) for k in order],
        "profit": [round(buckets[k]["profit"], 2) for k in order],
    }

    # ── To'lov usullari ──
    pay = (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.company_id == cid, Sale.sold_at >= start)
        .group_by(SalePayment.method_code).all()
    )

    # ── Top mahsulotlar ──
    tp = (
        db.query(
            SaleItem.name_snapshot,
            func.sum(SaleItem.qty),
            func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == cid, Sale.sold_at >= start)
        .group_by(SaleItem.name_snapshot)
        .order_by(func.sum(SaleItem.qty).desc()).limit(5).all()
    )

    # ── Kassirlar ──
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == cid).all())
    crows = (
        db.query(Sale.cashier_id, func.coalesce(func.sum(Sale.total), 0), func.count(Sale.id))
        .filter(Sale.company_id == cid, Sale.sold_at >= start)
        .group_by(Sale.cashier_id)
        .order_by(func.coalesce(func.sum(Sale.total), 0).desc()).limit(5).all()
    )
    cashiers = [
        {"name": names.get(c, "—"), "sales": float(s), "tx": int(n), "avg": float(s) / n if n else 0.0}
        for c, s, n in crows
    ]

    # ── So'nggi savdolar ──
    recents = (
        db.query(Sale).filter(Sale.company_id == cid)
        .order_by(Sale.sold_at.desc()).limit(7).all()
    )
    recent = [{
        "receipt_no": s.receipt_no,
        "time": s.sold_at.strftime("%H:%M"),
        "cashier": names.get(s.cashier_id, "—"),
        "method": s.payments[0].method_code if s.payments else "cash",
        "amount": float(s.total),
    } for s in recents]

    return {
        "period": period,
        "kpi": {"sales": total, "profit": profit, "tx": tx, "avg_check": avg},
        "delta": {
            "sales": delta(total, p_total), "profit": delta(profit, p_profit),
            "tx": delta(tx, p_tx), "avg": delta(avg, p_avg),
        },
        "cogs_ratio": (cost / total) if total else 0.72,
        "series": series,
        "payments": [{"method": m, "amount": float(a)} for m, a in pay],
        "top_products": [{"name": n, "qty": float(q or 0), "profit": float(p or 0)} for n, q, p in tp],
        "cashiers": cashiers,
        "recent": recent,
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
