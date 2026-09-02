"""Demo do'kon uchun ORQAGA SANALGAN tarix generatori (test/sotuv ko'rgazma uchun).

Faqat vendor (admin.py) orqali, kodi "test"/"demo" bilan boshlanadigan do'konlarга.
create_sale xizmatini `at=` bilan qayta ishlatadi — chek raqami, ombor ledger, foyda,
qarz — hammasi HAQIQIY sotuvdek to'g'ri chiqadi. Bo'laklab (kun oralig'i) chaqiriladi.
"""
import random
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from app.core.security import hash_password, norm_phone
from app.models.auth import Employee, Role
from app.models.catalog import Category, Product, ProductBarcode, Unit
from app.models.customers import Customer
from app.models.enums import CashMovementType, ShiftStatus
from app.models.inventory import Inventory
from app.models.org import Branch
from app.models.purchasing import Supplier
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift
from app.schemas.sales import SaleCreate, SaleItemIn
from app.services.sales import create_sale

# name, category, buy, sell, min, unit
CATALOG = [
    ("Coca-Cola 0.5L", "Ichimliklar", 5500, 8000, 15, "dona"),
    ("Pepsi 0.5L", "Ichimliklar", 5200, 7500, 15, "dona"),
    ("Fanta 0.5L", "Ichimliklar", 5500, 8000, 15, "dona"),
    ("Suv 1.5L", "Ichimliklar", 2500, 4000, 20, "dona"),
    ("Sok 1L", "Ichimliklar", 7000, 11000, 10, "dona"),
    ("Non", "Oziq-ovqat", 2000, 3000, 20, "dona"),
    ("Shakar 1kg", "Oziq-ovqat", 8000, 11000, 10, "kg"),
    ("Guruch 1kg", "Oziq-ovqat", 12000, 16000, 10, "kg"),
    ("Tuxum 10ta", "Oziq-ovqat", 14000, 18000, 8, "upak"),
    ("Yog' 1L", "Oziq-ovqat", 18000, 24000, 6, "litr"),
    ("Makaron", "Oziq-ovqat", 6000, 9000, 10, "dona"),
    ("Sut 1L", "Sut mahsulotlari", 8000, 12000, 12, "litr"),
    ("Kefir", "Sut mahsulotlari", 7000, 10000, 10, "dona"),
    ("Tvorog", "Sut mahsulotlari", 11000, 15000, 6, "dona"),
    ("Qatiq 0.5L", "Sut mahsulotlari", 5000, 8000, 10, "dona"),
    ("Shokolad", "Shirinliklar", 6000, 10000, 12, "dona"),
    ("Pechenye", "Shirinliklar", 4000, 7000, 12, "dona"),
    ("Konfet 1kg", "Shirinliklar", 20000, 28000, 5, "kg"),
    ("Sovun", "Gigiyena", 3000, 5000, 10, "dona"),
    ("Shampun", "Gigiyena", 14000, 20000, 5, "dona"),
    ("Tish pastasi", "Gigiyena", 7000, 11000, 6, "dona"),
    ("Salfetka", "Gigiyena", 3000, 5000, 15, "dona"),
]
CUSTOMERS = [
    ("Akbar Toshmatov", "+998901234501", 0),
    ("Malika Yusupova", "+998912345602", 0),
    ("Jasur Karimov", "+998933456703", 0),
    ("Nodira Rahimova", "+998944567804", 0),
    ("Sanjar Umarov", "+998975678905", 0),
    ("Feruza Aliyeva", "+998906789006", 0),
]
SUPPLIERS = [
    ("MevaSuv MChJ", "+998712004050", 0),
    ("Nestle Distribution", "+998712441122", 3150000),
    ("Oziq Baza", "+998903332211", 0),
    ("Shirin Savdo", "+998935556677", 2100000),
    ("Gigiena Plus", "+998978889900", 0),
]


def _tz_dt(d, hh, mm):
    return datetime.combine(d, time(hh, mm), tzinfo=timezone.utc)


def _ensure_setup(db, company, branch):
    """Birlik/kategoriya/mahsulot(+qoldiq)/mijoz/yetkazib beruvchi/kassir — yetishmasa yaratadi."""
    # allow_oversell — seed davomida qoldiq tugasa ham sotuv to'xtamasin
    from app.models.settings import Setting
    sec = db.query(Setting).filter(Setting.company_id == company.id, Setting.key == "security").first()
    val = dict(sec.value or {}) if sec else {}
    val["allow_oversell"] = True
    if sec:
        sec.value = val
    else:
        db.add(Setting(company_id=company.id, key="security", value=val))

    units = {u.code: u for u in db.query(Unit).all()}

    def unit(code):
        if code not in units:
            u = Unit(code=code, name=code.capitalize(), allow_fraction=code in ("kg", "litr"))
            db.add(u); db.flush(); units[code] = u
        return units[code]

    cats = {c.name: c for c in db.query(Category).filter(Category.company_id == company.id).all()}

    def cat(name):
        if name not in cats:
            c = Category(company_id=company.id, name=name, sort_order=len(cats))
            db.add(c); db.flush(); cats[name] = c
        return cats[name]

    now = datetime.now(timezone.utc)
    have = db.query(Product).filter(Product.company_id == company.id, Product.deleted_at.is_(None)).count()
    if have < 12:
        for i, (name, catn, buy, sell, mn, un) in enumerate(CATALOG):
            exists = db.query(Product).filter(
                Product.company_id == company.id, Product.name == name, Product.deleted_at.is_(None)).first()
            if exists:
                continue
            p = Product(
                company_id=company.id, article_code=f"D-{7000 + i:04d}", sku=str(50000 + i),
                name=name, category_id=cat(catn).id, unit_id=unit(un).id,
                base_buy_price=buy, base_sell_price=sell, tax_rate=0,
            )
            db.add(p); db.flush()
            db.add(ProductBarcode(product_id=p.id, company_id=company.id, barcode=f"478{company.id.int % 1000000:06d}{i:03d}"))
            db.add(Inventory(product_id=p.id, branch_id=branch.id, qty=6000, min_qty=mn, updated_at=now))

    # yetarli qoldiq (eski mahsulotlarga ham) — seed davomida tugamasligi uchun
    for inv in (
        db.query(Inventory).join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == company.id).all()
    ):
        if float(inv.qty) < 3000:
            inv.qty = 6000
            inv.updated_at = now

    if db.query(Customer).filter(Customer.company_id == company.id).count() < 3:
        for i, (name, phone, debt) in enumerate(CUSTOMERS):
            db.add(Customer(company_id=company.id, code=f"M-{1001 + i}",
                            full_name=name, phone=phone, credit_balance=debt))
    if db.query(Supplier).filter(Supplier.company_id == company.id).count() < 3:
        for name, phone, bal in SUPPLIERS:
            db.add(Supplier(company_id=company.id, name=name, phone=phone, balance=bal))

    # kamida 2 kassir (smena egasi) — parolli, login qilinmaydi (seed ichkarida)
    kass = [e for e in db.query(Employee).filter(
        Employee.company_id == company.id, Employee.deleted_at.is_(None)).all()
        if e.role.code in ("kassir", "administrator")]
    if len([e for e in kass if e.role.code == "kassir"]) < 2:
        role = db.query(Role).filter(Role.code == "kassir").first()
        for nm in ("Aziz Karimov", "Dilnoza Yusupova", "Bek Toshmatov"):
            ph = norm_phone("+99890" + str(random.randint(1000000, 9999999)))
            db.add(Employee(company_id=company.id, full_name=nm, phone=ph, role_id=role.id,
                            password_hash=hash_password("kassir123")))
    db.flush()


def seed_chunk(db, company, days_from: int, days_to: int, setup: bool = False, finalize: bool = False) -> dict:
    """[today-days_from, today-days_to) oralig'i uchun smena+sotuv yozadi."""
    branch = db.query(Branch).filter(
        Branch.company_id == company.id, Branch.deleted_at.is_(None)).order_by(Branch.created_at).first()
    if not branch:
        raise ValueError("Filial topilmadi")
    if setup:
        _ensure_setup(db, company, branch)

    cashiers = [e for e in db.query(Employee).filter(
        Employee.company_id == company.id, Employee.deleted_at.is_(None)).all()
        if e.role.code in ("kassir", "administrator")]
    products = db.query(Product).filter(
        Product.company_id == company.id, Product.deleted_at.is_(None)).all()
    customers = db.query(Customer).filter(Customer.company_id == company.id).all()
    if not cashiers or not products:
        raise ValueError("Kassir yoki mahsulot yo'q")

    today = datetime.now(timezone.utc).date()
    n_sales = n_shifts = 0
    for d in range(days_from, days_to, -1):
        day = today - timedelta(days=d)
        if day.weekday() == 6 and random.random() < 0.5:  # ba'zi yakshanbalar yopiq
            continue
        active = random.sample(cashiers, k=min(len(cashiers), random.randint(2, 3)))
        for ci, emp in enumerate(active):
            opening = random.choice([200000, 300000, 500000])
            sh = Shift(branch_id=branch.id, cashier_id=emp.id, opened_at=_tz_dt(day, 9, 0),
                       opening_cash=opening, status=ShiftStatus.open,
                       created_at=_tz_dt(day, 9, 0), updated_at=_tz_dt(day, 9, 0))
            db.add(sh); db.flush()
            n_shifts += 1
            cash_in = Decimal("0")
            for _ in range(random.randint(4, 11)):
                k = random.randint(1, 4)
                items = [SaleItemIn(product_id=random.choice(products).id, qty=random.randint(1, 4))
                         for _ in range(k)]
                method = random.choice(["cash", "cash", "cash", "card", "qr", "credit"])
                cust_id = random.choice(customers).id if (method == "credit" and customers) else None
                hh = random.randint(9, 19); mm = random.randint(0, 59)
                # allow_oversell yoqilgan + kirish to'g'ri — create_sale har sotuvni O'ZI commit qiladi
                sale = create_sale(db, emp, SaleCreate(
                    items=items, payment_method=method, customer_id=cust_id), at=_tz_dt(day, hh, mm))
                n_sales += 1
                if method == "cash":
                    cash_in += Decimal(str(sale.total))
            payin = Decimal("0"); payout = Decimal("0")
            if random.random() < 0.4:
                amt = Decimal(str(random.choice([50000, 100000])))
                db.add(CashMovement(shift_id=sh.id, type=CashMovementType.payin, amount=amt,
                                    reason="Qo'shimcha naqd", employee_id=emp.id, created_at=_tz_dt(day, 13, 0)))
                payin += amt
            if random.random() < 0.5:
                amt = Decimal(str(random.choice([20000, 30000, 40000])))
                db.add(CashMovement(shift_id=sh.id, type=CashMovementType.expense, amount=amt,
                                    reason=random.choice(["Kanstovar", "Tushlik", "Yetkazish"]),
                                    employee_id=emp.id, created_at=_tz_dt(day, 15, 0)))
                payout += amt
            expected = Decimal(str(opening)) + cash_in + payin - payout
            diff = Decimal(str(random.choice([0, 0, 0, 0, -20000, 15000, -5000, 30000, -50000])))
            sh.expected_cash = expected
            sh.counted_cash = max(Decimal("0"), expected + diff)
            sh.difference = sh.counted_cash - expected
            sh.closed_at = _tz_dt(day, 20, 0)
            sh.status = ShiftStatus.closed
        db.flush()

    if finalize:
        # Ombor realizmi: bir nechta mahsulotni kam/tugagan qilamiz + muddat qo'yamiz
        now = datetime.now(timezone.utc)
        invs = (db.query(Inventory).join(Product, Product.id == Inventory.product_id)
                .filter(Product.company_id == company.id).limit(6).all())
        for j, inv in enumerate(invs):
            if j == 0:
                inv.qty = 0                       # tugagan
            elif j in (1, 2):
                inv.qty = max(Decimal("1"), Decimal(str(inv.min_qty)) - 2)  # kam qolgan
            inv.updated_at = now
        # muddati yaqin/o'tgan mahsulotlar
        prods = db.query(Product).filter(
            Product.company_id == company.id, Product.deleted_at.is_(None)).limit(5).all()
        for j, p in enumerate(prods):
            if j == 3:
                p.expiry_date = today + timedelta(days=4)   # yaqin
            elif j == 4:
                p.expiry_date = today - timedelta(days=3)    # o'tgan

    db.commit()
    return {"days": f"{days_from}->{days_to}", "sales": n_sales, "shifts": n_shifts}
