import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import require, visible_branches
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Category, Product
from app.models.enums import SaleStatus
from app.models.inventory import Inventory
from app.models.org import Branch
from app.models.sales import Return, ReturnItem, Sale, SaleItem, SalePayment
from app.models.settings import Setting

router = APIRouter(tags=["reports"])

# Do'kon mahalliy vaqti (DST yo'q — sobit offset aniq). Filial timezone'idan olinadi.
_TZ_OFFSETS = {
    "Asia/Bishkek": 6, "Asia/Almaty": 6, "Asia/Qyzylorda": 5, "Asia/Tashkent": 5,
    "Asia/Samarkand": 5, "Asia/Dushanbe": 5, "Asia/Ashgabat": 5, "Asia/Yekaterinburg": 5,
    "Asia/Novosibirsk": 7, "Europe/Moscow": 3, "Asia/Baku": 4, "Asia/Tbilisi": 4, "Asia/Yerevan": 4,
}


def _store_tz(db: Session, company_id) -> timezone:
    b = (
        db.query(Branch)
        .filter(Branch.company_id == company_id, Branch.deleted_at.is_(None))
        .order_by(Branch.created_at)
        .first()
    )
    name = (b.timezone if b and b.timezone else "Asia/Tashkent")
    return timezone(timedelta(hours=_TZ_OFFSETS.get(name, 5)))


def _range(period: str):
    now = datetime.now(timezone.utc)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "all":
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)  # today


def _window(db: Session, company_id, period: str, from_date: str | None = None, to_date: str | None = None):
    """(start_utc, end_utc) — Sale.sold_at filtri uchun. from/to berilsa ixtiyoriy sana oralig'i
    (do'kon mahalliy kuni), aks holda preset (today/week/month/all) hozirgi vaqtgacha."""
    LOCAL = _store_tz(db, company_id)
    now_utc = datetime.now(timezone.utc)
    if from_date and to_date:
        try:
            fd = datetime.strptime(from_date, "%Y-%m-%d")
            td = datetime.strptime(to_date, "%Y-%m-%d")
            day0 = now_utc.astimezone(LOCAL).replace(hour=0, minute=0, second=0, microsecond=0)
            s = day0.replace(year=fd.year, month=fd.month, day=fd.day)
            e = day0.replace(year=td.year, month=td.month, day=td.day) + timedelta(days=1)
            if e <= s:
                e = s + timedelta(days=1)
            return s.astimezone(timezone.utc), e.astimezone(timezone.utc)
        except ValueError:
            pass
    nl = now_utc.astimezone(LOCAL)
    if period == "week":
        sl = nl.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    elif period == "month":
        sl = nl.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "all":
        sl = datetime(1970, 1, 1, tzinfo=LOCAL)
    else:
        sl = nl.replace(hour=0, minute=0, second=0, microsecond=0)
    return sl.astimezone(timezone.utc), now_utc + timedelta(seconds=1)


@router.get("/reports/summary")
def summary(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    # "Bugun" — do'kon mahalliy kalendar kuni (dashboard/overview/pnl/hourly bilan IZCHIL, UTC emas)
    LOCAL = _store_tz(db, emp.company_id)
    start = (
        datetime.now(timezone.utc).astimezone(LOCAL)
        .replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    )
    from app.core.deps import visible_branches
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali hisoboti
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _rb = (Return.branch_id.in_(_bset),) if _bset is not None else ()
    _NV = Sale.status != SaleStatus.voided
    total = db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.company_id == emp.company_id, _NV, Sale.sold_at >= start, *_sb
    ).scalar()
    cost = db.query(func.coalesce(func.sum(Sale.cost_total), 0)).filter(
        Sale.company_id == emp.company_id, _NV, Sale.sold_at >= start, *_sb
    ).scalar()
    tx = db.query(Sale).filter(Sale.company_id == emp.company_id, _NV, Sale.sold_at >= start, *_sb).count()
    # Qaytarishlar NET (overview/dashboard bilan izchil)
    r_rev = float(db.query(func.coalesce(func.sum(Return.total), 0)).filter(
        Return.company_id == emp.company_id, Return.created_at >= start, *_rb).scalar())
    r_cost = float(db.query(func.coalesce(func.sum(ReturnItem.qty * ReturnItem.unit_cost), 0))
                   .join(Return, Return.id == ReturnItem.return_id)
                   .filter(Return.company_id == emp.company_id, Return.restock.is_(True),
                           Return.created_at >= start, *_rb).scalar())
    pay_map: dict = {}
    for m, a in (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.company_id == emp.company_id, _NV, Sale.sold_at >= start, *_sb)
        .group_by(SalePayment.method_code)
        .all()
    ):
        pay_map[m] = pay_map.get(m, 0.0) + float(a)
    for m, a in (
        db.query(Return.refund_method, func.coalesce(func.sum(Return.total), 0))
        .filter(Return.company_id == emp.company_id, Return.created_at >= start, *_rb)
        .group_by(Return.refund_method)
        .all()
    ):
        pay_map[m] = pay_map.get(m, 0.0) - float(a)
    return {
        "today_sales": float(total) - r_rev,
        "today_profit": (float(total) - r_rev) - (float(cost) - r_cost),
        "tx_count": tx,
        "payment_breakdown": [{"method": m, "amount": a} for m, a in pay_map.items()],
    }


@router.get("/reports/pnl")
def pnl(period: str = "month", from_date: str | None = None, to_date: str | None = None,
        emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    cid = emp.company_id
    start, end = _window(db, cid, period, from_date, to_date)
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _rb = (Return.branch_id.in_(_bset),) if _bset is not None else ()
    NOT_VOID = Sale.status != SaleStatus.voided
    gross = float(db.query(func.coalesce(func.sum(Sale.subtotal), 0)).filter(
        Sale.company_id == cid, NOT_VOID, Sale.sold_at >= start, Sale.sold_at < end, *_sb).scalar())
    discount = float(db.query(func.coalesce(func.sum(Sale.discount_total), 0)).filter(
        Sale.company_id == cid, NOT_VOID, Sale.sold_at >= start, Sale.sold_at < end, *_sb).scalar())
    cogs = float(db.query(func.coalesce(func.sum(Sale.cost_total), 0)).filter(
        Sale.company_id == cid, NOT_VOID, Sale.sold_at >= start, Sale.sold_at < end, *_sb).scalar())
    ret_rev = float(db.query(func.coalesce(func.sum(Return.total), 0)).filter(
        Return.company_id == cid, Return.created_at >= start, Return.created_at < end, *_rb).scalar())
    ret_cost = float(db.query(func.coalesce(func.sum(ReturnItem.qty * ReturnItem.unit_cost), 0))
                     .join(Return, Return.id == ReturnItem.return_id)
                     .filter(Return.company_id == cid, Return.restock.is_(True),
                             Return.created_at >= start, Return.created_at < end, *_rb).scalar())
    net = gross - discount - ret_rev              # sof tushum (qaytarish ayirilgan)
    cogs_net = cogs - ret_cost
    gross_profit = net - cogs_net                 # YALPI foyda (operatsion xarajatsiz)
    _tax = db.query(Setting).filter(Setting.company_id == cid, Setting.key == "tax").first()
    _tv = (_tax.value if _tax else {}) or {}
    _rate = float(_tv.get("rate", 12) or 0) if _tv.get("vat_on") else 0.0
    vat = round(net * _rate / (100 + _rate)) if _rate else 0
    margin = round(gross_profit / net * 100) if net else 0
    return {
        "period": period,
        "gross": gross, "discount": discount, "returns": ret_rev, "net": net, "cogs": cogs_net,
        "gross_profit": gross_profit, "opex": 0, "net_profit": gross_profit,
        "vat": vat, "vat_rate": _rate, "margin": margin,
    }


@router.get("/reports/top-products")
def top_products(limit: int = 5, period: str = "month", from_date: str | None = None, to_date: str | None = None,
                 emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start, end = _window(db, emp.company_id, period, from_date, to_date)
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    rows = (
        db.query(
            SaleItem.name_snapshot,
            func.sum(SaleItem.qty).label("qty"),
            func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost).label("profit"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == emp.company_id, Sale.status != SaleStatus.voided, Sale.sold_at >= start, Sale.sold_at < end, *_sb)
        .group_by(SaleItem.name_snapshot)
        .order_by(func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost).desc())
        .limit(limit)
        .all()
    )
    return [{"name": n, "qty": float(q), "profit": float(p or 0)} for n, q, p in rows]


@router.get("/reports/sales-dynamics")
def sales_dynamics(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start = _range("today") - timedelta(days=6)
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    rows = (
        db.query(func.date(Sale.sold_at).label("d"), func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.company_id == emp.company_id, Sale.sold_at >= start, *_sb)
        .group_by(func.date(Sale.sold_at))
        .order_by(func.date(Sale.sold_at))
        .all()
    )
    return [{"day": str(d), "sales": float(s)} for d, s in rows]


@router.get("/reports/dashboard")
def dashboard(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    from app.models.customers import Customer, CustomerPayment
    from app.core.deps import visible_branches

    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _rb = (Return.branch_id.in_(_bset),) if _bset is not None else ()
    _ib = (Inventory.branch_id.in_(_bset),) if _bset is not None else ()
    _LOCAL = _store_tz(db, emp.company_id)
    _nl = datetime.now(timezone.utc).astimezone(_LOCAL)
    day_start = _nl.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    debt_total = float(db.query(func.coalesce(func.sum(Customer.credit_balance), 0)).filter(
        Customer.company_id == emp.company_id).scalar())
    debtors = db.query(Customer).filter(
        Customer.company_id == emp.company_id, Customer.credit_balance > 0).count()
    paid_today = float(
        db.query(func.coalesce(func.sum(CustomerPayment.amount), 0))
        .join(Customer, Customer.id == CustomerPayment.customer_id)
        .filter(Customer.company_id == emp.company_id, CustomerPayment.paid_at >= day_start)
        .scalar())

    low = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= Inventory.min_qty, *_ib)
        .order_by(Inventory.qty)
        .limit(6)
        .all()
    )
    _NV = Sale.status != SaleStatus.voided
    wk_start = day_start - timedelta(days=6)
    # Haftalik seriya — MAHALLIY kun bo'yicha bucketlanadi (UTC label siljishi bo'lmasin)
    _wk: dict = {}
    for _sa, _tot in db.query(Sale.sold_at, Sale.total).filter(
        Sale.company_id == emp.company_id, _NV, Sale.sold_at >= wk_start, *_sb
    ).all():
        if _sa.tzinfo is None:
            _sa = _sa.replace(tzinfo=timezone.utc)
        _d = _sa.astimezone(_LOCAL).date().isoformat()
        _wk[_d] = _wk.get(_d, 0.0) + float(_tot)
    weekly = sorted(_wk.items())
    pay_map: dict = {}
    for m, a in (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.company_id == emp.company_id, _NV, Sale.sold_at >= day_start, *_sb)
        .group_by(SalePayment.method_code)
        .all()
    ):
        pay_map[m] = pay_map.get(m, 0.0) + float(a)
    # Qaytarishlar NETlanadi (overview bilan izchil): summa refund_method'dan ayiriladi
    for m, a in (
        db.query(Return.refund_method, func.coalesce(func.sum(Return.total), 0))
        .filter(Return.company_id == emp.company_id, Return.created_at >= day_start, *_rb)
        .group_by(Return.refund_method)
        .all()
    ):
        pay_map[m] = pay_map.get(m, 0.0) - float(a)
    pay = [(m, a) for m, a in pay_map.items()]
    today_total = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.company_id == emp.company_id, _NV, Sale.sold_at >= day_start, *_sb).scalar())
    today_cost = float(db.query(func.coalesce(func.sum(Sale.cost_total), 0)).filter(
        Sale.company_id == emp.company_id, _NV, Sale.sold_at >= day_start, *_sb).scalar())
    r_rev_t = float(db.query(func.coalesce(func.sum(Return.total), 0)).filter(
        Return.company_id == emp.company_id, Return.created_at >= day_start, *_rb).scalar())
    r_cost_t = float(db.query(func.coalesce(func.sum(ReturnItem.qty * ReturnItem.unit_cost), 0))
                     .join(Return, Return.id == ReturnItem.return_id)
                     .filter(Return.company_id == emp.company_id, Return.restock.is_(True),
                             Return.created_at >= day_start, *_rb).scalar())
    return {
        "today_sales": today_total - r_rev_t,
        "today_profit": (today_total - r_rev_t) - (today_cost - r_cost_t),
        "debt": {"total": debt_total, "debtors": debtors, "paid_today": paid_today},
        "low_stock": [{"name": n, "qty": float(q), "min": float(m)} for n, q, m in low],
        "weekly": [{"day": str(d), "sales": float(s)} for d, s in weekly],
        "payments": [{"method": m, "amount": float(a)} for m, a in pay],
    }


@router.get("/reports/overview")
def overview(period: str = "week", branch_id: str | None = None,
             from_date: str | None = None, to_date: str | None = None,
             emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Dashboard davr-analitikasi — HAQIQIY & aniq: do'kon mahalliy vaqti, qaytarishlar
    ayirilgan (net), like-for-like delta, per-bucket real P&L, yalpi foyda (opex yo'q)."""
    cid = emp.company_id
    LOCAL = _store_tz(db, cid)

    def to_local(dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL)

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(LOCAL)
    day0 = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Ixtiyoriy sana oralig'i (from_date..to_date, YYYY-MM-DD) — mavjud period yo'llariga tegmaydi ──
    custom = None
    if from_date and to_date:
        try:
            fd = datetime.strptime(from_date, "%Y-%m-%d")
            td = datetime.strptime(to_date, "%Y-%m-%d")
            custom = True
        except ValueError:
            custom = None

    if custom:
        period = "range"  # kunlik bucket (bkey else-shoxi)
        start = day0.replace(year=fd.year, month=fd.month, day=fd.day)
        end_local = day0.replace(year=td.year, month=td.month, day=td.day) + timedelta(days=1)
        if end_local <= start:
            end_local = start + timedelta(days=1)
        length = end_local - start
        prev_start = start - length
        prev_end = start
        sq, eq = start.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
        psq, peq = prev_start.astimezone(timezone.utc), prev_end.astimezone(timezone.utc)
    else:
        if period == "day":
            start = day0
            prev_start = start - timedelta(days=1)
        elif period == "month":
            start = day0.replace(day=1)
            prev_start = (start - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            period = "week"
            start = day0 - timedelta(days=6)
            prev_start = start - timedelta(days=7)
        elapsed = now_local - start
        prev_end = prev_start + elapsed  # o'tgan davrni SHU nuqtagacha kesamiz -> adolatli delta
        # DB filtri UTC'da (SQLite/Postgres bir xil): mahalliy chegaralarni UTC'ga o'giramiz
        sq, eq = start.astimezone(timezone.utc), now_utc + timedelta(seconds=1)
        psq, peq = prev_start.astimezone(timezone.utc), prev_end.astimezone(timezone.utc)
    NOT_VOID = Sale.status != SaleStatus.voided
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali(lari)
    _bid = None
    if branch_id:
        try:
            _bid = uuid.UUID(str(branch_id))
        except (ValueError, AttributeError):
            _bid = None
    # Filialга bog'langan foydalanuvchi ruxsatsiz filialga "pivot" qila olmasin —
    # ko'rina olmaydigan filial so'ralса, uni e'tiborsiz qoldiramiz (o'z filial(lar)iga qaytamiz)
    if _bset is not None and _bid is not None and _bid not in _bset:
        _bid = None
    if _bid:
        br_sale = [Sale.branch_id == _bid]
        br_ret = [Return.branch_id == _bid]
    elif _bset is not None:
        br_sale = [Sale.branch_id.in_(_bset)]
        br_ret = [Return.branch_id.in_(_bset)]
    else:
        br_sale = []
        br_ret = []

    def sales_agg(a, b):
        row = db.query(
            func.coalesce(func.sum(Sale.total), 0),
            func.coalesce(func.sum(Sale.cost_total), 0),
            func.count(Sale.id),
        ).filter(Sale.company_id == cid, NOT_VOID, *br_sale, Sale.sold_at >= a, Sale.sold_at < b).one()
        return float(row[0]), float(row[1]), int(row[2])

    def returns_agg(a, b):
        rrev = float(db.query(func.coalesce(func.sum(Return.total), 0)).filter(
            Return.company_id == cid, *br_ret, Return.created_at >= a, Return.created_at < b).scalar())
        # COGS faqat mol OMBORGA qaytganda (restock) tiklanadi; yaroqsiz mol tannarxi yo'qolgan
        rcost = float(db.query(func.coalesce(func.sum(ReturnItem.qty * ReturnItem.unit_cost), 0))
                      .join(Return, Return.id == ReturnItem.return_id)
                      .filter(Return.company_id == cid, Return.restock.is_(True), *br_ret,
                              Return.created_at >= a, Return.created_at < b).scalar())
        return rrev, rcost

    g_sales, g_cost, tx = sales_agg(sq, eq)
    r_rev, r_cost = returns_agg(sq, eq)
    revenue = g_sales - r_rev
    profit = revenue - (g_cost - r_cost)
    avg = revenue / tx if tx else 0.0

    pg_sales, pg_cost, p_tx = sales_agg(psq, peq)
    pr_rev, pr_cost = returns_agg(psq, peq)
    p_revenue = pg_sales - pr_rev
    p_profit = p_revenue - (pg_cost - pr_cost)
    p_avg = p_revenue / p_tx if p_tx else 0.0

    def delta(cur, prev):
        if prev is None or prev <= 0:  # bo'sh/manfiy baza -> foiz bermaymiz (UI "yangi")
            return None
        return round((cur - prev) / prev * 100, 1)

    # ── Per-bucket real P&L seriyasi ──
    srows = db.query(Sale.sold_at, Sale.subtotal, Sale.discount_total, Sale.total, Sale.cost_total).filter(
        Sale.company_id == cid, NOT_VOID, *br_sale, Sale.sold_at >= sq, Sale.sold_at < eq).all()
    rrows = db.query(Return.created_at, Return.total, Return.refund_method).filter(
        Return.company_id == cid, *br_ret, Return.created_at >= sq, Return.created_at < eq).all()
    rcrows = db.query(Return.created_at, ReturnItem.qty, ReturnItem.unit_cost).join(
        Return, Return.id == ReturnItem.return_id).filter(
        Return.company_id == cid, Return.restock.is_(True), *br_ret,
        Return.created_at >= sq, Return.created_at < eq).all()
    prows = db.query(Sale.sold_at, SalePayment.method_code, SalePayment.amount).join(
        SalePayment, SalePayment.sale_id == Sale.id).filter(
        Sale.company_id == cid, NOT_VOID, *br_sale, Sale.sold_at >= sq, Sale.sold_at < eq).all()

    def bkey(dt):
        loc = to_local(dt)
        if period == "day":
            return loc.hour, f"{loc.hour:02d}:00"
        if period == "month":
            w = (loc.day - 1) // 7 + 1
            return w, str(w)
        d = loc.date().isoformat()
        return d, d

    buckets, order = {}, []

    def ensure(key, label):
        if key not in buckets:
            buckets[key] = {"label": label, "subtotal": 0.0, "discount": 0.0, "gross": 0.0,
                            "cost": 0.0, "returns": 0.0, "rcost": 0.0, "tx": 0,
                            "pays": {"cash": 0.0, "card": 0.0, "qr": 0.0, "credit": 0.0}}
            order.append(key)
        return buckets[key]

    if period == "week":
        for i in range(7):
            d = (start + timedelta(days=i)).date().isoformat()
            ensure(d, d)

    for sold_at, sub, disc, tot, cst in srows:
        b = ensure(*bkey(sold_at))
        b["subtotal"] += float(sub); b["discount"] += float(disc)
        b["gross"] += float(tot); b["cost"] += float(cst); b["tx"] += 1
    for created_at, rtot, rmethod in rrows:
        b = ensure(*bkey(created_at))
        b["returns"] += float(rtot)
        # Pul qaytarilgan usuldan ayiramiz — kassa/karta tile'lari haqiqiy tushumni ko'rsatsin
        m = rmethod if rmethod in b["pays"] else "cash"
        b["pays"][m] -= float(rtot)
    for created_at, q, uc in rcrows:
        ensure(*bkey(created_at))["rcost"] += float(q) * float(uc)
    for sold_at, method, amt in prows:
        b = ensure(*bkey(sold_at))
        b["pays"][method if method in b["pays"] else "cash"] += float(amt)

    series = []
    for k in sorted(order):
        b = buckets[k]
        ns, nc = b["gross"] - b["returns"], b["cost"] - b["rcost"]
        series.append({
            "label": b["label"], "subtotal": round(b["subtotal"], 2), "discount": round(b["discount"], 2),
            "returns": round(b["returns"], 2), "sales": round(ns, 2), "cost": round(nc, 2),
            "profit": round(ns - nc, 2), "tx": b["tx"],
            "pays": {m: round(v, 2) for m, v in b["pays"].items()},
        })

    # ── To'lov usullari (yig'ilgan; qarz -> alohida, "kelib tushgan pul" emas) ──
    pt = {"cash": 0.0, "card": 0.0, "qr": 0.0, "credit": 0.0}
    for _sa, method, amt in prows:
        pt[method if method in pt else "cash"] += float(amt)
    for _ca, rtot, rmethod in rrows:  # pul qaytarilgan usulni netlash
        pt[rmethod if rmethod in pt else "cash"] -= float(rtot)
    payments = [{"method": m, "amount": round(pt[m], 2)} for m in ("cash", "card", "qr") if pt[m]]

    # ── Top mahsulotlar (DAROMAD bo'yicha — kg/dona aralashmasin) ──
    tp = (db.query(SaleItem.name_snapshot, func.sum(SaleItem.line_total), func.sum(SaleItem.qty))
          .join(Sale, Sale.id == SaleItem.sale_id)
          .filter(Sale.company_id == cid, NOT_VOID, *br_sale, Sale.sold_at >= sq, Sale.sold_at < eq)
          .group_by(SaleItem.name_snapshot)
          .order_by(func.sum(SaleItem.line_total).desc()).limit(5).all())

    # ── Kassirlar (voided'siz) ──
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == cid).all())
    crows = (db.query(Sale.cashier_id, func.coalesce(func.sum(Sale.total), 0), func.count(Sale.id))
             .filter(Sale.company_id == cid, NOT_VOID, *br_sale, Sale.sold_at >= sq, Sale.sold_at < eq)
             .group_by(Sale.cashier_id)
             .order_by(func.coalesce(func.sum(Sale.total), 0).desc()).limit(5).all())
    cashiers = [{"name": names.get(c, "\u2014"), "sales": float(x), "tx": int(n),
                 "avg": float(x) / n if n else 0.0} for c, x, n in crows]

    # ── So'nggi savdolar ──
    recents = db.query(Sale).filter(Sale.company_id == cid, NOT_VOID, *br_sale).order_by(Sale.sold_at.desc()).limit(7).all()
    recent = [{"receipt_no": r.receipt_no, "time": to_local(r.sold_at).strftime("%H:%M"),
               "cashier": names.get(r.cashier_id, "\u2014"),
               "method": r.payments[0].method_code if r.payments else "cash",
               "amount": float(r.total),
               "refunded": r.status in (SaleStatus.refunded, SaleStatus.partially_refunded)}
              for r in recents]

    # ── Filiallar (HAQIQIY — Sale.branch_id; soxta emas) ──
    branch_rows = db.query(Branch.id, Branch.name).filter(
        Branch.company_id == cid, Branch.deleted_at.is_(None)).all()
    if _bset is not None:  # filialга bog'langan — faqat o'z filial(lar)ini ko'rsatamiz
        branch_rows = [(bid, bname) for bid, bname in branch_rows if bid in _bset]
    branches = []
    for bid, bname in branch_rows:
        bs = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            Sale.company_id == cid, Sale.branch_id == bid, NOT_VOID, Sale.sold_at >= sq, Sale.sold_at < eq).scalar())
        pbs = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            Sale.company_id == cid, Sale.branch_id == bid, NOT_VOID, Sale.sold_at >= psq, Sale.sold_at < peq).scalar())
        branches.append({"name": bname, "sales": bs, "growth": (round((bs - pbs) / pbs * 100, 1) if pbs > 0 else None)})
    branches.sort(key=lambda z: z["sales"], reverse=True)

    # ── Soliq sozlamasi (QQS faqat ro'yxatdan o'tgan bo'lsa) ──
    _tax = db.query(Setting).filter(Setting.company_id == cid, Setting.key == "tax").first()
    _tv = (_tax.value if _tax else {}) or {}
    vat_on = bool(_tv.get("vat_on"))
    vat_rate = float(_tv.get("rate", 12) or 0) if vat_on else 0.0

    return {
        "period": period,
        "tz_hours": int(LOCAL.utcoffset(None).total_seconds() // 3600),
        "kpi": {"sales": revenue, "profit": profit, "tx": tx, "avg_check": avg},
        "delta": {"sales": delta(revenue, p_revenue), "profit": delta(profit, p_profit),
                  "tx": delta(tx, p_tx), "avg": delta(avg, p_avg)},
        "series": series,
        "payments": payments,
        "credit_total": round(pt["credit"], 2),
        "top_products": [{"name": n, "revenue": float(rev or 0), "qty": float(q or 0)} for n, rev, q in tp],
        "cashiers": cashiers,
        "recent": recent,
        "branches": branches,
        "branch_count": len(branch_rows),
        "vat_on": vat_on,
        "vat_rate": vat_rate,
    }


@router.get("/reports/alerts")
def alerts(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _ib = (Inventory.branch_id.in_(_bset),) if _bset is not None else ()
    low = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= Inventory.min_qty, *_ib)
        .count()
    )
    loss = (
        db.query(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == emp.company_id, SaleItem.unit_price < SaleItem.unit_cost, *_sb)
        .count()
    )
    return {"low_stock": low, "loss_making": loss}


@router.get("/reports/categories")
def report_categories(period: str = "month", from_date: str | None = None, to_date: str | None = None,
                      emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    start, end = _window(db, emp.company_id, period, from_date, to_date)
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    rows = (
        db.query(
            Category.name,
            func.sum(SaleItem.line_total),
            func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost),
        )
        .join(Product, Product.id == SaleItem.product_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Category, Category.id == Product.category_id)
        .filter(Sale.company_id == emp.company_id, Sale.status != SaleStatus.voided, Sale.sold_at >= start, Sale.sold_at < end, *_sb)
        .group_by(Category.name)
        .all()
    )
    out = []
    for n, s, p in rows:
        s = float(s or 0); p = float(p or 0)
        out.append({"name": n, "sales": s, "profit": p, "margin": round(p / s * 100) if s else 0})
    out.sort(key=lambda x: x["profit"], reverse=True)
    return out


@router.get("/reports/detail")
def report_detail(period: str = "month", from_date: str | None = None, to_date: str | None = None,
                  emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Batafsil: qaytarish/bekor xulosasi + ABC analiz (foyda bo'yicha 80/95% kesim)."""
    start, end = _window(db, emp.company_id, period, from_date, to_date)
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _rb = (Return.branch_id.in_(_bset),) if _bset is not None else ()
    # Qaytarishlar
    ret_rows = db.query(Return).filter(
        Return.company_id == emp.company_id, Return.created_at >= start, Return.created_at < end, *_rb).all()
    ret_count = len(ret_rows)
    ret_sum = float(sum(float(r.total or 0) for r in ret_rows))
    voided = db.query(Sale).filter(
        Sale.company_id == emp.company_id, Sale.status == SaleStatus.voided,
        Sale.sold_at >= start, Sale.sold_at < end, *_sb).count()

    # ABC — mahsulot kesimida foyda (NOT_VOID)
    rows = (
        db.query(
            SaleItem.name_snapshot,
            func.sum(SaleItem.qty),
            func.sum(SaleItem.line_total),
            func.sum(SaleItem.line_total - SaleItem.qty * SaleItem.unit_cost),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == emp.company_id, Sale.status != SaleStatus.voided,
                Sale.sold_at >= start, Sale.sold_at < end, *_sb)
        .group_by(SaleItem.name_snapshot)
        .all()
    )
    prods = [{"name": n, "units": float(q or 0), "revenue": float(rv or 0), "profit": float(p or 0)}
             for n, q, rv, p in rows]
    prods.sort(key=lambda x: x["profit"], reverse=True)
    total_profit = sum(max(p["profit"], 0) for p in prods) or 1.0
    cum = 0.0
    a_share = 0.0
    for p in prods:
        cum += max(p["profit"], 0)
        ratio = cum / total_profit
        p["cls"] = "A" if ratio <= 0.80 or cum == max(p["profit"], 0) else ("B" if ratio <= 0.95 else "C")
        p["share"] = round(max(p["profit"], 0) / total_profit * 100, 1)
    a_share = round(sum(p["share"] for p in prods if p["cls"] == "A"), 0)
    return {
        "returns": {"count": ret_count, "sum": ret_sum, "voided": voided},
        "abc": prods[:60],
        "a_share": a_share,
    }


@router.get("/reports/cashflow")
def cashflow(period: str = "day", from_date: str | None = None, to_date: str | None = None,
             emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Naqd oqim: kirim (savdo/qarz qaytdi/qo'shimcha) va chiqim (xarajat/inkassa/qaytarish/beruvchi),
    hamda kassada qolgan naqd. Do'kon mahalliy kuni yoki ixtiyoriy sana oralig'i; company-scoped."""
    from app.models.customers import Customer, CustomerPayment
    from app.models.enums import CashMovementType
    from app.models.purchasing import Supplier, SupplierPayment
    from app.models.shifts import CashMovement, Shift

    start, end = _window(db, emp.company_id, period, from_date, to_date)
    _NV = Sale.status != SaleStatus.voided
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _rb = (Return.branch_id.in_(_bset),) if _bset is not None else ()
    _shb = (Shift.branch_id.in_(_bset),) if _bset is not None else ()

    def _pay(method):
        return float(
            db.query(func.coalesce(func.sum(SalePayment.amount), 0))
            .join(Sale, Sale.id == SalePayment.sale_id)
            .filter(Sale.company_id == emp.company_id, _NV, Sale.sold_at >= start, Sale.sold_at < end,
                    SalePayment.method_code == method, *_sb).scalar())

    cash_sales, card, qr = _pay("cash"), _pay("card"), _pay("qr")
    # Nasiya (qarz) savdo — pul hozir kirmaydi (faqat balansga yoziladi)
    credit_sales = _pay("credit")
    # Qarz qaytdi (naqd) — mijoz to'lovlari
    # Filialга bog'langан xodим uchun — faqat o'z filialida qabul qilingan naqd (kassa balansi
    # to'g'ri chiqsin). CustomerPayment.branch_id bor; filialsiz (NULL) to'lov shu filialга yozilmaydi.
    _cpb = (CustomerPayment.branch_id.in_(_bset),) if _bset is not None else ()
    credit_back_cash = float(
        db.query(func.coalesce(func.sum(CustomerPayment.amount), 0))
        .join(Customer, Customer.id == CustomerPayment.customer_id)
        .filter(Customer.company_id == emp.company_id, CustomerPayment.method == "cash",
                CustomerPayment.paid_at >= start, CustomerPayment.paid_at < end, *_cpb).scalar())
    # Kassa harakatlari (shift orqali company)
    def _cash_mv(t):
        return float(
            db.query(func.coalesce(func.sum(CashMovement.amount), 0))
            .join(Shift, Shift.id == CashMovement.shift_id)
            .join(Branch, Branch.id == Shift.branch_id)
            .filter(Branch.company_id == emp.company_id, CashMovement.type == t,
                    CashMovement.created_at >= start, CashMovement.created_at < end, *_shb).scalar())

    payin = _cash_mv(CashMovementType.payin)
    expense = _cash_mv(CashMovementType.expense)
    collection = _cash_mv(CashMovementType.collection)
    payout = _cash_mv(CashMovementType.payout)  # "naqd topshirish" — ilgari chiqimga kirmasdi
    # Naqd qaytarish (mijozga)
    refund_cash = float(db.query(func.coalesce(func.sum(Return.total), 0)).filter(
        Return.company_id == emp.company_id, Return.refund_method == "cash",
        Return.created_at >= start, Return.created_at < end, *_rb).scalar())
    # Beruvchiga naqd to'lov. SupplierPayment'да filial yo'q (ta'minot company-darajali), shuning uchun
    # filialга bog'langan xodим uchun uni kassa balansiga QO'SHMAYMIZ (aks holда boshqa filial to'lovi
    # bu filial kassasini kamaytirib ko'rsatardi).
    if _bset is not None:
        sup_cash = 0.0
    else:
        sup_cash = float(
            db.query(func.coalesce(func.sum(SupplierPayment.amount), 0))
            .join(Supplier, Supplier.id == SupplierPayment.supplier_id)
            .filter(Supplier.company_id == emp.company_id, SupplierPayment.method == "cash",
                    SupplierPayment.paid_at >= start, SupplierPayment.paid_at < end).scalar())
    # Boshlang'ich naqd (davrда ochilgan smenalar)
    opening = float(db.query(func.coalesce(func.sum(Shift.opening_cash), 0))
                    .join(Branch, Branch.id == Shift.branch_id)
                    .filter(Branch.company_id == emp.company_id,
                            Shift.opened_at >= start, Shift.opened_at < end, *_shb).scalar())

    kirim = cash_sales + credit_back_cash + payin
    chiqim = expense + collection + refund_cash + sup_cash + payout
    kassada = opening + kirim - chiqim
    return {
        "period": period,
        "in": {"naqd_savdo": cash_sales, "qarz_qaytdi": credit_back_cash, "qoshimcha": payin, "jami": kirim},
        "out": {"xarajat": expense, "inkassatsiya": collection + payout, "qaytarish": refund_cash, "beruvchiga": sup_cash, "jami": chiqim},
        "opening": opening,
        "kassada": kassada,
        "noncash": {"karta": card, "qr": qr, "nasiya": credit_sales},
    }


@router.get("/reports/hourly")
def report_hourly(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Bugungi savdo soatlar bo'yicha (mahalliy vaqt zonasi)."""
    _LOCAL = _store_tz(db, emp.company_id)
    _nl = datetime.now(timezone.utc).astimezone(_LOCAL)
    day_start = _nl.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    buckets = {h: 0.0 for h in range(24)}
    for sa, tot in db.query(Sale.sold_at, Sale.total).filter(
        Sale.company_id == emp.company_id, Sale.status != SaleStatus.voided, Sale.sold_at >= day_start, *_sb
    ).all():
        if sa.tzinfo is None:
            sa = sa.replace(tzinfo=timezone.utc)
        buckets[sa.astimezone(_LOCAL).hour] += float(tot)
    return [{"hour": h, "sales": buckets[h]} for h in range(24)]


@router.get("/reports/alerts/detail")
def alerts_detail(type: str = "low", emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _ib = (Inventory.branch_id.in_(_bset),) if _bset is not None else ()
    if type == "low":
        rows = (
            db.query(Product.name, Inventory.qty, Inventory.min_qty)
            .join(Inventory, Inventory.product_id == Product.id)
            .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= Inventory.min_qty, *_ib)
            .order_by(Inventory.qty)
            .all()
        )
        return [{"name": n, "note": f"Minimal: {float(m):g} dona", "right": f"{float(q):g} dona"} for n, q, m in rows]
    if type == "loss":
        rows = (
            db.query(SaleItem.name_snapshot, SaleItem.unit_price, SaleItem.unit_cost)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(Sale.company_id == emp.company_id, SaleItem.unit_price < SaleItem.unit_cost, *_sb)
            .limit(50)
            .all()
        )
        return [{"name": n, "note": f"Narx {float(pr):g} < tannarx {float(co):g}", "right": f"−{float(co - pr):g}"} for n, pr, co in rows]
    return []


@router.get("/reports/inventory-value")
def inventory_value(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Ombor qiymati: tannarx bo'yicha jami, potensial sotuv/foyda, kategoriya kesimi, top mahsulotlar."""
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _ib = (Inventory.branch_id.in_(_bset),) if _bset is not None else ()
    rows = (
        db.query(Product.name, Product.category_id, Inventory.qty,
                 Product.base_buy_price, Product.base_sell_price)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Inventory.qty > 0, *_ib)
        .all()
    )
    cat_names = dict(db.query(Category.id, Category.name).filter(Category.company_id == emp.company_id).all())
    total_cost = 0.0
    total_retail = 0.0
    items = []
    by_cat: dict = {}
    for name, cat_id, qty, buy, sell in rows:
        q = float(qty or 0)
        val = q * float(buy or 0)
        total_cost += val
        total_retail += q * float(sell or 0)
        items.append({"name": name, "qty": q, "value": round(val, 2)})
        cn = cat_names.get(cat_id, "—")
        by_cat[cn] = by_cat.get(cn, 0.0) + val
    items.sort(key=lambda x: x["value"], reverse=True)
    cats = sorted(({"name": k, "value": round(v, 2)} for k, v in by_cat.items()),
                  key=lambda x: x["value"], reverse=True)
    return {
        "total_cost": round(total_cost, 2),
        "total_retail": round(total_retail, 2),
        "potential_profit": round(total_retail - total_cost, 2),
        "item_count": len(items),
        "by_category": cats[:12],
        "top_items": items[:20],
    }


@router.get("/reports/dead-stock")
def dead_stock(days: int = 30, emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Sekin/o'lik tovarlar: qoldig'i bor, lekin oxirgi `days` kunda sotilmagan (pul omborда yotibdi)."""
    days = max(7, min(int(days or 30), 365))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali
    _sb = (Sale.branch_id.in_(_bset),) if _bset is not None else ()
    _ib = (Inventory.branch_id.in_(_bset),) if _bset is not None else ()
    last_sold = dict(
        db.query(SaleItem.product_id, func.max(Sale.sold_at))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == emp.company_id, Sale.status != SaleStatus.voided, *_sb)
        .group_by(SaleItem.product_id).all()
    )
    rows = (
        db.query(Product.id, Product.name, Inventory.qty, Product.base_buy_price)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Inventory.qty > 0, *_ib)
        .all()
    )
    out = []
    for pid, name, qty, buy in rows:
        ls = last_sold.get(pid)
        if ls is not None:
            if ls.tzinfo is None:
                ls = ls.replace(tzinfo=timezone.utc)
            if ls >= cutoff:
                continue  # yaqinda sotilgan -> o'lik emas
        q = float(qty or 0)
        out.append({"name": name, "qty": q, "value": round(q * float(buy or 0), 2),
                    "last_sold": ls.date().isoformat() if ls is not None else None,
                    "days_idle": ((now - ls).days if ls is not None else None)})
    out.sort(key=lambda x: x["value"], reverse=True)
    return {"days": days, "count": len(out),
            "frozen_value": round(sum(x["value"] for x in out), 2), "items": out[:60]}


@router.get("/reports/debtors")
def debtors(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Mijoz qarzlari: balans>0 bo'lgan mijozlar, oxirgi to'lov va necha kundan beri."""
    from app.models.customers import Customer, CustomerPayment
    rows = (
        db.query(Customer.id, Customer.full_name, Customer.phone, Customer.credit_balance)
        .filter(Customer.company_id == emp.company_id, Customer.deleted_at.is_(None),
                Customer.credit_balance > 0)
        .order_by(Customer.credit_balance.desc()).all()
    )
    last_pay = dict(
        db.query(CustomerPayment.customer_id, func.max(CustomerPayment.paid_at))
        .join(Customer, Customer.id == CustomerPayment.customer_id)
        .filter(Customer.company_id == emp.company_id).group_by(CustomerPayment.customer_id).all()
    )
    now = datetime.now(timezone.utc)
    out = []
    for cid_, name, phone, bal in rows:
        lp = last_pay.get(cid_)
        if lp is not None and lp.tzinfo is None:
            lp = lp.replace(tzinfo=timezone.utc)
        out.append({"name": name, "phone": phone, "balance": float(bal or 0),
                    "last_payment": lp.date().isoformat() if lp is not None else None,
                    "days_since": ((now - lp).days if lp is not None else None)})
    return {"total": round(sum(x["balance"] for x in out), 2), "count": len(out), "rows": out}


# ── 1С tarixidan smenali savdolarni tizimga kiritish (real Sale yozuvlari) ──
class HistSaleRow(BaseModel):
    date: str            # "12.01.2026 15:24:07" yoki "12.01.2026"
    revenue: float
    no: str = ""         # 1C hujjat raqami (idempotentlik uchun)


class HistSeedBody(BaseModel):
    rows: list[HistSaleRow]
    cost_ratio: float = 0.77   # tannarx = tushum * ratio (yalpi foyda uchun)


@router.post("/reports/history/seed")
def history_seed(
    body: HistSeedBody,
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    """1С smenali tushum-yig'indilarini real Sale yozuvlari qilib kiritadi (tarixiy sana bilan).
    Har bir yozuv = bitta smena jami (tovar qatorlarisiz). Idempotent (client_uuid)."""
    branch = db.query(Branch).filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first()
    if not branch:
        raise HTTPException(400, "Filial topilmadi")
    ratio = min(max(float(body.cost_ratio), 0.0), 1.0)
    ns = uuid.UUID("0000000f-1c00-0000-0000-000000000000")
    added = skipped = 0
    for i, r in enumerate(body.rows):
        rev = round(float(r.revenue or 0))
        if rev <= 0:
            skipped += 1
            continue
        cu = uuid.uuid5(ns, f"{emp.company_id}|{r.no or i}|{r.date}")
        if db.query(Sale.id).filter(Sale.client_uuid == cu, Sale.company_id == emp.company_id).first():
            skipped += 1
            continue
        sold = None
        for fmt_ in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                sold = datetime.strptime((r.date or "").strip(), fmt_)
                break
            except ValueError:
                continue
        if sold is None:
            skipped += 1
            continue
        # 1C sanalari do'konning MAHALLIY vaqti — UTC deb olsak kun/soat kesimlari
        # 5-6 soatga siljib, "kechagi" savdo boshqa kunga tushardi.
        sold = sold.replace(tzinfo=_store_tz(db, emp.company_id)).astimezone(timezone.utc)
        sale = Sale(
            company_id=emp.company_id, branch_id=branch.id, cashier_id=emp.id,
            sold_at=sold, subtotal=rev, discount_total=0, tax_total=0, total=rev,
            cost_total=round(rev * ratio), status=SaleStatus.completed,
            receipt_no=f"H{(r.no or '').replace('-', '').replace(' ', '') or cu.hex[:12]}",
            client_uuid=cu, is_offline=False,
        )
        db.add(sale)
        db.flush()
        db.add(SalePayment(sale_id=sale.id, method_code="cash", amount=rev,
                           given_amount=None, change_amount=None, paid_at=sold))
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}
