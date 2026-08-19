# -*- coding: utf-8 -*-
"""Mijozga ko'rsatish uchun boy DEMO ma'lumot. Bazani reset qilgandan (initdb+seed) so'ng ishlatiladi.
   Ishga tushirish:  DATABASE_URL="sqlite:///./savdoos.db" .venv/Scripts/python.exe demo_seed.py
"""
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

random.seed(7)

from app.db.session import SessionLocal
from app.models.auth import Employee
from app.models.catalog import Category, Product, ProductBarcode, Unit
from app.models.customers import CreditTransaction, Customer
from app.models.enums import CreditTxnType, MovementType, SaleStatus, ShiftStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch, Company
from app.models.purchasing import Supplier, SupplierLedger, Purchase, PurchaseItem
from app.models.sales import Sale, SaleItem, SalePayment
from app.models.scales import Scale
from app.models.shifts import Shift

D = lambda x: Decimal(str(x))
now = datetime.now(timezone.utc)

db = SessionLocal()
co = db.query(Company).first()
br = db.query(Branch).first()
admin = db.query(Employee).join(Employee.role).filter(Employee.full_name == "Sardor Aliyev").first()
kassir = db.query(Employee).filter(Employee.full_name == "Dilnoza Rahimova").first()
cashiers = [c for c in (kassir, admin) if c]
units = {u.code: u.id for u in db.query(Unit).all()}
cats = {c.name: c for c in db.query(Category).all()}

def ensure_cat(name):
    if name not in cats:
        n = db.query(Category).filter(Category.company_id == co.id).count()
        c = Category(company_id=co.id, name=name, sort_order=n)
        db.add(c); db.flush(); cats[name] = c
    return cats[name].id

ensure_cat("Mevalar / Sabzavotlar")
ensure_cat("Go'sht / Gastronomiya")

# ── Mahsulotlar: (nom, kategoriya, birlik, kelish, sotish, qoldiq, min, weighed, plu) ──
PRODS = [
    # Ichimliklar
    ("Coca-Cola 1L", "Ichimliklar", "dona", 70, 95, 84, 15, False, None),
    ("Fanta 1L", "Ichimliklar", "dona", 70, 95, 61, 15, False, None),
    ("Pepsi 1L", "Ichimliklar", "dona", 66, 90, 47, 15, False, None),
    ("Suv 1.5L", "Ichimliklar", "dona", 16, 25, 160, 30, False, None),
    ("Sok Piko 1L", "Ichimliklar", "dona", 32, 45, 38, 10, False, None),
    ("Choy Lipton", "Ichimliklar", "dona", 60, 85, 29, 10, False, None),
    ("Kofe Nescafe", "Ichimliklar", "dona", 90, 120, 22, 8, False, None),
    ("Energetik Adrenalin", "Ichimliklar", "dona", 55, 75, 40, 10, False, None),
    # Oziq-ovqat
    ("Non", "Oziq-ovqat", "dona", 11, 18, 90, 20, False, None),
    ("Makaron 400g", "Oziq-ovqat", "dona", 40, 55, 52, 12, False, None),
    ("Guruch 1kg", "Oziq-ovqat", "kg", 85, 110, 44, 10, False, None),
    ("Un 1kg", "Oziq-ovqat", "kg", 36, 48, 60, 15, False, None),
    ("Shakar 1kg", "Oziq-ovqat", "kg", 66, 85, 51, 12, False, None),
    ("Tuz 1kg", "Oziq-ovqat", "dona", 8, 12, 70, 15, False, None),
    ("Yog' 1L", "Oziq-ovqat", "litr", 140, 180, 3, 6, False, None),
    ("Konserva baliq", "Oziq-ovqat", "dona", 70, 95, 26, 8, False, None),
    ("Tomat pastasi", "Oziq-ovqat", "dona", 48, 65, 33, 10, False, None),
    # Sut
    ("Sut 1L", "Sut mahsulotlari", "litr", 58, 75, 48, 12, False, None),
    ("Kefir", "Sut mahsulotlari", "dona", 50, 68, 27, 8, False, None),
    ("Qatiq", "Sut mahsulotlari", "dona", 40, 55, 31, 8, False, None),
    ("Smetana", "Sut mahsulotlari", "dona", 68, 90, 19, 6, False, None),
    ("Sariyog' 200g", "Sut mahsulotlari", "dona", 110, 140, 14, 5, False, None),
    ("Tvorog", "Sut mahsulotlari", "dona", 85, 110, 2, 5, False, None),
    # Shirinliklar
    ("Shokolad Alpen Gold", "Shirinliklar", "dona", 62, 85, 58, 12, False, None),
    ("Pechenye", "Shirinliklar", "dona", 32, 45, 46, 10, False, None),
    ("Vafli", "Shirinliklar", "dona", 26, 38, 40, 10, False, None),
    ("Marmelad", "Shirinliklar", "dona", 44, 60, 24, 8, False, None),
    # Gigiyena
    ("Sovun", "Gigiyena", "dona", 20, 28, 55, 12, False, None),
    ("Shampun", "Gigiyena", "dona", 115, 150, 17, 5, False, None),
    ("Tish pastasi", "Gigiyena", "dona", 55, 75, 4, 6, False, None),
    ("Salfetka", "Gigiyena", "dona", 22, 32, 72, 15, False, None),
    ("Tualet qog'ozi", "Gigiyena", "upak", 32, 45, 38, 10, False, None),
    ("Kir kukuni", "Gigiyena", "dona", 140, 180, 21, 6, False, None),
    # Mevalar / Sabzavotlar (TAROZILI)
    ("Olma", "Mevalar / Sabzavotlar", "kg", 85, 120, 65, 15, True, "101"),
    ("Banan", "Mevalar / Sabzavotlar", "kg", 100, 140, 42, 12, True, "102"),
    ("Kartoshka", "Mevalar / Sabzavotlar", "kg", 30, 45, 120, 25, True, "103"),
    ("Piyoz", "Mevalar / Sabzavotlar", "kg", 22, 35, 95, 20, True, "104"),
    ("Sabzi", "Mevalar / Sabzavotlar", "kg", 26, 40, 70, 18, True, "105"),
    ("Pomidor", "Mevalar / Sabzavotlar", "kg", 65, 90, 38, 12, True, "106"),
    ("Uzum", "Mevalar / Sabzavotlar", "kg", 120, 160, 24, 10, True, "107"),
    # Go'sht / Gastronomiya (TAROZILI)
    ("Mol go'shti", "Go'sht / Gastronomiya", "kg", 520, 650, 18, 8, True, "201"),
    ("Tovuq go'shti", "Go'sht / Gastronomiya", "kg", 300, 380, 27, 10, True, "202"),
    ("Pishloq", "Go'sht / Gastronomiya", "kg", 600, 750, 9, 5, True, "203"),
    ("Kolbasa", "Go'sht / Gastronomiya", "kg", 400, 520, 12, 6, True, "204"),
]

products = []  # (Product, sell, cost)
seq = db.query(Product).filter(Product.company_id == co.id).count()
bc = 4780050000000
for i, (name, cat, unitc, buy, sell, stock, mn, weighed, plu) in enumerate(PRODS):
    if db.query(Product).filter(Product.company_id == co.id, Product.name == name, Product.deleted_at.is_(None)).first():
        continue  # allaqachon bor — o'tkazamiz (idempotent)
    seq += 1
    p = Product(
        company_id=co.id, article_code=f"4-780050-{200 + seq:04d}", sku=str(20000 + seq),
        name=name, category_id=cats[cat].id if cat in cats else None,
        unit_id=units.get(unitc, units["dona"]),
        base_buy_price=buy, base_sell_price=sell, tax_rate=12,
        is_weighted=weighed, plu_code=plu, scale_sync=weighed, created_by=admin.id if admin else None,
    )
    db.add(p); db.flush()
    db.add(ProductBarcode(product_id=p.id, barcode=str(bc + seq), is_primary=True))
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=D(stock), min_qty=D(mn), updated_at=now))
    products.append((p, D(sell), D(buy)))
print(f"[demo] {len(products)} mahsulot qo'shildi (tarozili: {sum(1 for _ in PRODS if _[7])})")

# Barcha mahsulotlar (base seed + demo) sotuv uchun
all_prods = []
for p in db.query(Product).filter(Product.company_id == co.id, Product.deleted_at.is_(None)).all():
    all_prods.append((p, D(p.base_sell_price), D(p.base_buy_price)))

# ── Mijozlar ──
CUSTS = [
    ("Aziz Karimov", "+996 555 12 34 56", 0),
    ("Dilnoza Yusupova", "+996 700 22 33 44", 0),
    ("Rustam Aliyev", "+996 555 88 77 66", 0),
    ("Gulnora Abdullaeva", "+996 770 45 67 89", 0),
    ("Jamshid Rahimov", "+996 555 90 12 34", 45000),
    ("Malika Sobirova", "+996 700 11 22 33", 12500),
    ("Bekzod Nazarov", "+996 555 44 55 66", 78000),
    ("Feruza Karimova", "+996 770 99 88 77", 0),
    ("Otabek Yusupov", "+996 555 33 22 11", 23000),
    ("Kamola Rashidova", "+996 700 55 66 77", 0),
    ("Sanjar Toshmatov", "+996 555 67 89 01", 8000),
    ("Nigora Islomova", "+996 770 12 21 12", 0),
]
customers = []
_ccount = db.query(Customer).filter(Customer.company_id == co.id).count()
for i, (nm, ph, debt) in enumerate(CUSTS):
    c = Customer(company_id=co.id, code=f"M-{3001 + _ccount + i}", full_name=nm, phone=ph, credit_balance=D(debt))
    db.add(c); db.flush()
    if debt:
        db.add(CreditTransaction(customer_id=c.id, type=CreditTxnType.charge, amount=D(debt),
                                 balance_after=D(debt), employee_id=admin.id, created_at=now - timedelta(days=random.randint(2, 20))))
    customers.append(c)
print(f"[demo] {len(customers)} mijoz (qarzdor: {sum(1 for _ in CUSTS if _[2])})")

# ── Yetkazib beruvchilar ──
SUPS = [("Nestle Distribution", "+996 312 90 12 34", 1250000),
        ("MevaSuv MChJ", "+996 312 44 55 66", 0),
        ("Oziq Baza", "+996 555 77 88 99", 340000),
        ("Shirin Savdo", "+996 770 33 44 55", 0),
        ("Gigiena Plus", "+996 312 11 22 33", 185000)]
_added_sup = 0
for nm, ph, bal in SUPS:
    if db.query(Supplier).filter(Supplier.company_id == co.id, Supplier.name == nm, Supplier.deleted_at.is_(None)).first():
        continue  # base seed allaqachon yaratgan — takrorlamaymiz
    _added_sup += 1
    s = Supplier(company_id=co.id, name=nm, phone=ph, balance=D(bal))
    db.add(s); db.flush()
    if bal:
        db.add(SupplierLedger(supplier_id=s.id, type=CreditTxnType.charge, amount=D(bal),
                              balance_after=D(bal), ref_type="opening", created_at=now - timedelta(days=15)))
print(f"[demo] {len(SUPS)} yetkazib beruvchi")

# ── Tarozilar ──
_SCALES = [
    ("Asosiy tarozi", "CAS", "CL5000", "lan", "192.168.1.150", 3001, None, 11, 3),
    ("Go'sht bo'limi tarozisi", "DIGI", "SM-100", "usb", None, None, "COM3", 4, 5),
]
for nm, brand, model, ctype, host, port, com, synced, hrs in _SCALES:
    if db.query(Scale).filter(Scale.company_id == co.id, Scale.name == nm).first():
        continue
    db.add(Scale(company_id=co.id, name=nm, brand=brand, model=model, driver=brand,
                 connection_type=ctype, host=host, port=port, com_port=com, status="connected",
                 synced_count=synced, is_active=True, last_sync_at=now - timedelta(hours=hrs),
                 created_at=now, updated_at=now))
print(f"[demo] {len(_SCALES)} tarozi")

# ── Sotuvlar tarixi: 12 kun, har kuni smena + sotuvlar ──
METHODS = ["cash"] * 55 + ["card"] * 28 + ["qr"] * 12 + ["credit"] * 5
rcpt = 1000
total_sales = 0
cust_debt_add = {}
for dback in range(12, -1, -1):  # 12 kun oldindan bugungacha
    day = (now - timedelta(days=dback)).replace(hour=9, minute=0, second=0, microsecond=0)
    n_sales = random.randint(18, 40) if dback not in (0,) else random.randint(8, 16)
    cash_sum = Decimal("0")
    cashier = random.choice(cashiers)
    sh = Shift(branch_id=br.id, cashier_id=cashier.id, opened_at=day, opening_cash=D(200000),
               status=(ShiftStatus.open if dback == 0 else ShiftStatus.closed))
    db.add(sh); db.flush()
    for _ in range(n_sales):
        t = day + timedelta(minutes=random.randint(10, 600), seconds=random.randint(0, 59))
        nitems = random.randint(1, 6)
        method = random.choice(METHODS)
        cust = random.choice(customers) if method == "credit" else None
        sub = Decimal("0"); cost = Decimal("0")
        sale = Sale(company_id=co.id, branch_id=br.id, cashier_id=cashier.id, shift_id=sh.id,
                    customer_id=cust.id if cust else None, status=SaleStatus.completed,
                    subtotal=Decimal("0"), total=Decimal("0"), cost_total=Decimal("0"),
                    sold_at=t, receipt_no="", uid="")
        db.add(sale); db.flush()
        picks = random.sample(all_prods, min(nitems, len(all_prods)))
        for p, sell, cst in picks:
            if p.is_weighted:
                qty = D(round(random.uniform(0.3, 2.5), 3))
            else:
                qty = D(random.randint(1, 4))
            line = qty * sell
            sub += line; cost += qty * cst
            db.add(SaleItem(sale_id=sale.id, product_id=p.id, name_snapshot=p.name,
                            article_snapshot=p.article_code, qty=qty, unit_price=sell, unit_cost=cst,
                            line_total=line, tax_rate=12, unit_id=p.unit_id))
        rcpt += 1
        sale.subtotal = sub; sale.total = sub; sale.cost_total = cost
        sale.receipt_no = f"#{rcpt}"; sale.uid = t.strftime("%y%m%d") + str(rcpt)
        given = sub if method != "cash" else (sub + D(random.choice([0, 0, 0, 100, 500, 1000])))
        db.add(SalePayment(sale_id=sale.id, method_code=method, amount=sub,
                           given_amount=(given if method == "cash" else None),
                           change_amount=((given - sub) if method == "cash" else None), paid_at=t))
        if method == "cash":
            cash_sum += sub
        if cust:
            cust.credit_balance = D(cust.credit_balance) + sub
            db.add(CreditTransaction(customer_id=cust.id, type=CreditTxnType.charge, amount=sub,
                                     balance_after=D(cust.credit_balance), sale_id=sale.id,
                                     employee_id=cashier.id, created_at=t))
        total_sales += 1
    if dback != 0:
        exp = D(200000) + cash_sum
        sh.expected_cash = exp
        sh.counted_cash = exp + D(random.choice([0, 0, 0, -500, 1000, -200]))
        sh.difference = sh.counted_cash - exp
        sh.closed_at = day + timedelta(hours=12)

db.commit()
print(f"[demo] {total_sales} sotuv (12 kun + bugungi ochiq smena) yaratildi")
print("[OK] DEMO ma'lumot tayyor.")
db.close()
