"""Boshlang'ich ma'lumot: kompaniya, filial, rollar/ruxsatlar, birliklar, to'lov
usullari, kategoriyalar, demo mahsulot/mijoz, xodimlar (Administrator PIN 1234).

Idempotent: kompaniya mavjud bo'lsa qayta yozmaydi.
"""
from datetime import datetime, timezone

import app.models  # noqa: F401
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.auth import Employee, Permission, Role, RolePermission
from app.models.catalog import Category, Product, ProductBarcode, Unit
from app.models.customers import Customer
from app.models.inventory import Inventory
from app.models.org import Branch, Company, Terminal
from app.models.purchasing import Supplier
from app.models.settings import PaymentMethod, Setting, TaxRate

NOW = datetime.now(timezone.utc)

# ruxsatlar: modul.harakat
PERMISSIONS = [
    ("kassa.sell", "kassa"), ("kassa.view", "kassa"),
    ("sotuvlar.view", "sotuvlar"),
    ("qaytarishlar.create", "qaytarishlar"), ("qaytarishlar.view", "qaytarishlar"),
    ("mijozlar.view", "mijozlar"), ("mijozlar.edit", "mijozlar"),
    ("mahsulotlar.view", "mahsulotlar"), ("mahsulotlar.edit", "mahsulotlar"),
    ("ombor.view", "ombor"), ("ombor.edit", "ombor"),
    ("xaridlar.view", "xaridlar"), ("xaridlar.edit", "xaridlar"),
    ("hisobot.view", "hisobot"),
    ("xodimlar.view", "xodimlar"), ("xodimlar.edit", "xodimlar"),
    ("sozlamalar.view", "sozlamalar"), ("sozlamalar.edit", "sozlamalar"),
]

ROLES = {
    "administrator": ("Administrator", "ALL"),
    "menejer": ("Menejer", [
        "sotuvlar.view", "qaytarishlar.create", "qaytarishlar.view", "mijozlar.view",
        "mijozlar.edit", "mahsulotlar.view", "mahsulotlar.edit", "ombor.view",
        "hisobot.view", "sozlamalar.view",
    ]),
    "omborchi": ("Omborchi", [
        "mahsulotlar.view", "mahsulotlar.edit", "ombor.view", "ombor.edit",
        "xaridlar.view", "xaridlar.edit",
    ]),
    "kassir": ("Kassir", [
        "kassa.sell", "kassa.view", "sotuvlar.view", "qaytarishlar.create", "mijozlar.view",
    ]),
}

UNITS = [("dona", "Dona", False), ("kg", "Kilogramm", True), ("litr", "Litr", True), ("upak", "Upak", False)]

CATEGORIES = ["Ichimliklar", "Oziq-ovqat", "Sut mahsulotlari", "Shirinliklar", "Gigiyena"]

# name, barcode, category, buy, sell, stock, min, unit
CATALOG = [
    ("Coca-Cola 0.5L", "4780012340015", "Ichimliklar", 55, 80, 48, 10, "dona"),
    ("Pepsi 0.5L", "4780012340022", "Ichimliklar", 52, 75, 36, 10, "dona"),
    ("Fanta 0.5L", "4780012340039", "Ichimliklar", 55, 80, 29, 10, "dona"),
    ("Suv 1L", "4780012340046", "Ichimliklar", 12, 20, 120, 20, "dona"),
    ("Non", "4780012340053", "Oziq-ovqat", 20, 30, 64, 15, "dona"),
    ("Shakar 1kg", "4780012340060", "Oziq-ovqat", 48, 65, 40, 10, "kg"),
    ("Guruch 1kg", "4780012340077", "Oziq-ovqat", 90, 120, 33, 10, "kg"),
    ("Tuxum 10ta", "4780012340084", "Oziq-ovqat", 145, 180, 15, 5, "upak"),
    ("Yog' 1L", "4780012340091", "Oziq-ovqat", 180, 220, 4, 5, "litr"),
    ("Sut 1L", "4780012340107", "Sut mahsulotlari", 68, 90, 38, 10, "litr"),
    ("Kefir", "4780012340114", "Sut mahsulotlari", 62, 85, 24, 8, "dona"),
    ("Tvorog", "4780012340121", "Sut mahsulotlari", 110, 140, 3, 5, "dona"),
    ("Shokolad", "4780012340138", "Shirinliklar", 70, 95, 52, 10, "dona"),
    ("Pechenye", "4780012340145", "Shirinliklar", 38, 55, 41, 10, "dona"),
    ("Konfet 1kg", "4780012340152", "Shirinliklar", 92, 120, 16, 5, "kg"),
    ("Sovun", "4780012340169", "Gigiyena", 28, 40, 44, 10, "dona"),
    ("Shampun", "4780012340176", "Gigiyena", 140, 180, 12, 5, "dona"),
    ("Tish pastasi", "4780012340183", "Gigiyena", 65, 90, 2, 5, "dona"),
    ("Salfetka", "4780012340190", "Gigiyena", 22, 35, 70, 15, "dona"),
]

CUSTOMERS = [
    ("Akbar Toshmatov", "+998 90 123 45 67", 480000),
    ("Malika Yusupova", "+998 91 234 56 78", 0),
    ("Jasur Karimov", "+998 93 345 67 89", 1240000),
    ("Nodira Rahimova", "+998 94 456 78 90", 0),
    ("Sanjar Umarov", "+998 97 567 89 01", 320000),
]

SUPPLIERS = [
    ("MevaSuv MChJ", "+998 71 200 40 50", 0),
    ("Nestle Distribution", "+998 71 244 11 22", 3150000),
    ("Oziq Baza", "+998 90 333 22 11", 0),
    ("Shirin Savdo", "+998 93 555 66 77", 2100000),
    ("Gigiena Plus", "+998 97 888 99 00", 0),
]

EMPLOYEES = [
    ("Sardor Aliyev", "+998 90 123 45 67", "administrator", "1234"),
    ("Dilnoza Rahimova", "+998 91 234 56 78", "kassir", "1111"),
    ("Jamshid Umarov", "+998 97 567 89 01", "omborchi", "2222"),
    ("Nodira Rahimova", "+998 94 456 78 90", "menejer", "3333"),
]


def run():
    db = SessionLocal()
    try:
        if db.query(Company).first():
            print("[--] Ma'lumot allaqachon mavjud — seed o'tkazib yuborildi")
            return

        company = Company(name="Oltin Do'kon", code="demo", currency="UZS")
        db.add(company)
        db.flush()

        branch = Branch(company_id=company.id, code="F01", name="Chilonzor filiali")
        db.add(branch)
        db.flush()
        db.add(Terminal(branch_id=branch.id, name="Kassa #1", device_uuid="demo-terminal-1"))

        # ruxsatlar
        perm = {}
        for code, module in PERMISSIONS:
            p = Permission(code=code, module=module)
            db.add(p)
            db.flush()
            perm[code] = p.id

        # rollar
        role_id = {}
        for code, (name, allowed) in ROLES.items():
            r = Role(code=code, name=name)
            db.add(r)
            db.flush()
            role_id[code] = r.id
            codes = list(perm) if allowed == "ALL" else allowed
            for c in codes:
                db.add(RolePermission(role_id=r.id, permission_id=perm[c]))

        # birliklar
        unit_id = {}
        for code, name, frac in UNITS:
            u = Unit(code=code, name=name, allow_fraction=frac)
            db.add(u)
            db.flush()
            unit_id[code] = u.id

        # to'lov usullari + soliq + sozlamalar
        for i, (code, name, en) in enumerate(
            [("cash", "Naqd", True), ("card", "Karta", True), ("qr", "QR", True), ("credit", "Qarz", True)]
        ):
            db.add(PaymentMethod(company_id=company.id, code=code, name=name, is_enabled=en, sort_order=i))
        db.add(TaxRate(company_id=company.id, name="QQS 12%", rate=12, is_default=True))
        db.add(Setting(company_id=company.id, key="payments", value={"karta": True, "qr": True, "qarz": True}))
        db.add(Setting(company_id=company.id, key="features", value={"returns": True}))
        db.add(Setting(company_id=company.id, key="store_info", value={"name": "Oltin Do'kon", "branch": "Chilonzor filiali"}))

        # kategoriyalar
        cat_id = {}
        for i, name in enumerate(CATEGORIES):
            c = Category(company_id=company.id, name=name, sort_order=i)
            db.add(c)
            db.flush()
            cat_id[name] = c.id

        # mahsulotlar + qoldiq. Bir nechta mahsulotga yaroqlilik muddati (demo: yaqin/o'tgan).
        from datetime import timedelta
        today = NOW.date()
        expiry_by_name = {
            "Sut 1L": today + timedelta(days=3),      # muddati yaqin
            "Kefir": today + timedelta(days=5),        # muddati yaqin
            "Tvorog": today - timedelta(days=2),       # muddati o'tgan
            "Non": today + timedelta(days=1),          # muddati yaqin
            "Tuxum 10ta": today + timedelta(days=20),
            "Yog' 1L": today + timedelta(days=120),
        }
        for i, (name, bc, cat, buy, sell, stock, mn, unit) in enumerate(CATALOG):
            p = Product(
                company_id=company.id,
                article_code=f"4-700000-160{200 + i:03d}",
                sku=str(10025 + i),
                name=name,
                category_id=cat_id[cat],
                unit_id=unit_id[unit],
                base_buy_price=buy,
                base_sell_price=sell,
                tax_rate=12,
                expiry_date=expiry_by_name.get(name),
            )
            db.add(p)
            db.flush()
            db.add(ProductBarcode(product_id=p.id, barcode=bc))
            db.add(Inventory(product_id=p.id, branch_id=branch.id, qty=stock, min_qty=mn, updated_at=NOW))

        # mijozlar
        for i, (name, phone, debt) in enumerate(CUSTOMERS):
            db.add(Customer(company_id=company.id, code=f"M-{1001 + i}", full_name=name, phone=phone, credit_balance=debt))

        # yetkazib beruvchilar
        for name, phone, bal in SUPPLIERS:
            db.add(Supplier(company_id=company.id, name=name, phone=phone, balance=bal))

        # xodimlar
        for name, phone, role, pin in EMPLOYEES:
            db.add(
                Employee(
                    company_id=company.id,
                    full_name=name,
                    phone=phone,
                    role_id=role_id[role],
                    pin_hash=hash_password(pin),
                )
            )

        db.commit()
        print("[OK] Seed tayyor. Login PIN: 1234 (Administrator - Sardor Aliyev)")
    finally:
        db.close()


if __name__ == "__main__":
    run()
