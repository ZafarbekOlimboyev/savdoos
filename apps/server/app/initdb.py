"""Dev/prod uchun jadvallarni yaratish (Alembic o'rniga tez yo'l) + yengil avto-migratsiya."""
from sqlalchemy import inspect, text

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import engine

# Mavjud jadvalga keyinroq qo'shilgan ustunlar (create_all ularni qo'shmaydi).
# (jadval, ustun, SQL-tur) — SQLite ham, Postgres ham tushunadigan turlar.
_ADDED_COLUMNS = [
    ("products", "sku", "VARCHAR"),
    ("products", "expiry_date", "DATE"),
    ("products", "is_weighted", "BOOLEAN"),
    ("products", "plu_code", "VARCHAR"),
    ("products", "scale_sync", "BOOLEAN"),
    ("companies", "code", "VARCHAR"),
    ("inventory", "low_alerted", "BOOLEAN"),
    ("employees", "sec_epoch", "INTEGER DEFAULT 0"),
    ("cash_movements", "client_uuid", "VARCHAR"),
]


def _ensure_columns():
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for table, col, sqltype in _ADDED_COLUMNS:
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if col in existing:
            continue
        try:
            with engine.begin() as con:
                con.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {sqltype}'))
            print(f"[migrate] {table}.{col} qo'shildi")
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] {table}.{col} — o'tkazib yuborildi ({e})")


def _backfill_company_codes():
    """Eski bazalarda companies.code NULL — PIN login scoping ishlashi uchun
    har mavjud kompaniyaga id'dan olingan noyob kod beramiz (dialekt-neytral)."""
    try:
        with engine.begin() as con:
            rows = con.execute(text(
                "SELECT id FROM companies WHERE code IS NULL AND deleted_at IS NULL"
            )).fetchall()
            for (cid,) in rows:
                code = str(cid).replace("-", "")[:8].lower()
                con.execute(text("UPDATE companies SET code = :c WHERE id = :i"), {"c": code, "i": cid})
                print(f"[migrate] companies.code backfill: {cid} -> {code}")
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] companies.code backfill — o'tkazib yuborildi ({e})")


def _ensure_indexes():
    # PLU noyobligi uchun kompaniya doirasidagi qisman unique indeks (SQLite + Postgres).
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_products_company_plu "
                             "ON products (company_id, plu_code) WHERE plu_code IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_products_company_plu \u2014 o'tkazib yuborildi ({e})")
    # Do'kon kodi noyobligi (bo'sh bo'lmagan, o'chirilmagan) \u2014 SQLite + Postgres.
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_companies_code "
                             "ON companies (code) WHERE code IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_companies_code \u2014 o'tkazib yuborildi ({e})")
    # Parolli akkaunt telefoni global noyob (race'ga qarshi DB-darajada, TOCTOU emas).
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_employees_phone_pw "
                             "ON employees (phone) WHERE phone IS NOT NULL "
                             "AND password_hash IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_employees_phone_pw \u2014 o'tkazib yuborildi ({e})")
    # Offline savdo dublikatiga qarshi DB-darajali dedup: bir client_uuid \u2014 bitta chek (race'ga chidamli).
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_company_client_uuid "
                             "ON sales (company_id, client_uuid) "
                             "WHERE client_uuid IS NOT NULL AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_sales_company_client_uuid \u2014 o'tkazib yuborildi ({e})")
    # Bitta kassir\u0434\u0430 bir vaqt\u0434\u0430 faqat BITTA ochiq smena (race/ikki oyna oldi olinadi).
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_shifts_cashier_open "
                             "ON shifts (cashier_id) WHERE status = 'open' AND deleted_at IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_shifts_cashier_open \u2014 o'tkazib yuborildi ({e})")
    # Offline idempotentlik DB-daraj\u0430\u0441\u0438\u0434\u0430 (bir client_uuid = bir yozuv) \u2014 bir qator\u043b\u0438 operatsiyalar
    # (to'lovlar/qabul). Bir vaqt\u0434\u0430\u0433\u0438 ikki bir xil so'rov ikki marta pul yoz\u043c\u0430\u0441\u0438\u043d (SELECT-dedup
    # race'\u0433\u0430 chidamli emas edi). Ko'p qator\u043b\u0438 transfer stock_movements'\u0433\u0430 bu qo'yil\u043c\u0430\u0439\u0434\u0438 (bir uuid
    # bir necha mahsul\u043e\u0442 satr\u0438\u0434\u0430 ishlatiladi).
    for name, ddl in [
        ("ux_custpay_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_custpay_client_uuid "
         "ON customer_payments (customer_id, client_uuid) WHERE client_uuid IS NOT NULL"),
        ("ux_suppay_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_suppay_client_uuid "
         "ON supplier_payments (supplier_id, client_uuid) WHERE client_uuid IS NOT NULL"),
        ("ux_receivings_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_receivings_client_uuid "
         "ON receivings (company_id, client_uuid) WHERE client_uuid IS NOT NULL"),
        ("ux_returns_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_returns_client_uuid "
         "ON returns (company_id, client_uuid) WHERE client_uuid IS NOT NULL AND deleted_at IS NULL"),
        ("ux_purchases_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_purchases_client_uuid "
         "ON purchases (company_id, client_uuid) WHERE client_uuid IS NOT NULL AND deleted_at IS NULL"),
        # Kassa harakати idempotentligи (mobil /cash/ops + /shifts/{id}/cash retry'да ikki marta emas).
        ("ux_cashmov_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_cashmov_client_uuid "
         "ON cash_movements (shift_id, client_uuid) WHERE client_uuid IS NOT NULL"),
        # writeoff + transfer_out offline retry idempotentligi. Bir client_uuid ko'p mahsulot
        # satrига tarqalgani uchun (client_uuid, product_id, type) KOMPOZIT — har satr baribir noyob
        # (transfer_in client_uuid=NULL bo'lgani uchun bu indeksга kirmaydi). SELECT-dedup race'га
        # chidamli emas edi (ikki konkurrent so'rov qoldiqni 2x kamaytirardi) — endi DB darajасида.
        # QA SB-007: filial kodi dublikati (F-xxx) — DB darajasida noyoblik (soft-delete'dan tashqari).
        ("ux_branches_company_code",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_branches_company_code "
         "ON branches (company_id, code) WHERE deleted_at IS NULL"),
        # QA SB-021: Setting NULL branch_id'da UniqueConstraint ishlamaydi (NULL != NULL) —
        # kompaniya-darajali kalit uchun alohida partial-unique.
        ("ux_settings_company_key",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_settings_company_key "
         "ON settings (company_id, key) WHERE branch_id IS NULL"),
        ("ux_stockmov_client_prod_type",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_stockmov_client_prod_type "
         "ON stock_movements (client_uuid, product_id, type) WHERE client_uuid IS NOT NULL"),
        # Xodim yaratish idempotentligi (double-click/retry dublikat xodim yaratmasin)
        ("ux_employees_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_employees_client_uuid "
         "ON employees (company_id, client_uuid) WHERE client_uuid IS NOT NULL"),
    ]:
        try:
            with engine.begin() as con:
                con.execute(text(ddl))
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] {name} \u2014 o'tkazib yuborildi ({e})")
    # Hisobot tezligi (katta bazada seq-scan o'rniga indeks-range): sotuv/qaytarish sana + harakatlar.
    for name, ddl in [
        ("ix_sales_company_sold", "CREATE INDEX IF NOT EXISTS ix_sales_company_sold ON sales (company_id, sold_at)"),
        ("ix_returns_company_created", "CREATE INDEX IF NOT EXISTS ix_returns_company_created ON returns (company_id, created_at)"),
        ("ix_stockmov_product_created", "CREATE INDEX IF NOT EXISTS ix_stockmov_product_created ON stock_movements (product_id, created_at)"),
        ("ix_stockmov_branch_created", "CREATE INDEX IF NOT EXISTS ix_stockmov_branch_created ON stock_movements (branch_id, created_at)"),
    ]:
        try:
            with engine.begin() as con:
                con.execute(text(ddl))
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] {name} \u2014 o'tkazib yuborildi ({e})")


def _ensure_catalog():
    """Bazaviy ruxsat/rol/rol-grant/birlik katalogini HAR boot idempotent ta'minlaydi. seed.run()
    prod'da (SEED_DEMO=1 bo'lmasa) chiqib ketadi, shu bois bu katalog seedsiz prod'da ham
    kafolatlanadi — va yangi ruxsat/rol qo'shilsa prod avtomatik oladi (aks holda seedga
    qo'shilган yangi kod prodда umuman paydo bo'lmasdi). Faqat QO'SHADI (eskini o'chirmaydi)."""
    from app.db.session import SessionLocal
    from app.models.auth import Permission, Role, RolePermission
    from app.models.catalog import Unit
    from app.seed import ADMIN_EXCLUDE, PERMISSIONS, ROLES, UNITS
    db = SessionLocal()
    try:
        perm: dict = {}
        for code, module in PERMISSIONS:
            p = db.query(Permission).filter_by(code=code).first()
            if not p:
                p = Permission(code=code, module=module); db.add(p); db.flush()
                print(f"[migrate] permission {code} qo'shildi")
            perm[code] = p.id
        for code, (name, allowed) in ROLES.items():
            r = db.query(Role).filter_by(code=code).first()
            if not r:
                r = Role(code=code, name=name); db.add(r); db.flush()
                print(f"[migrate] role {code} qo'shildi")
            codes = ([c for c in perm if code == "ega" or c not in ADMIN_EXCLUDE]
                     if allowed == "ALL" else allowed)
            have = {rp.permission_id for rp in db.query(RolePermission).filter_by(role_id=r.id).all()}
            for c in codes:
                if perm.get(c) and perm[c] not in have:
                    db.add(RolePermission(role_id=r.id, permission_id=perm[c]))
        for code, name, frac in UNITS:
            if not db.query(Unit).filter_by(code=code).first():
                db.add(Unit(code=code, name=name, allow_fraction=frac))
                print(f"[migrate] unit {code} qo'shildi")
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"[migrate] catalog — o'tkazib yuborildi ({e})")
    finally:
        db.close()


def _ensure_roles_and_owner():
    """'Ega' roli + 'xodimlar.make_admin' ruxsatini ta'minlaydi va har do'konning
    egasini (eng eski administratorini) 'ega' roliga ko'taradi. Idempotent — har boot.
    Rollar GLOBAL (company_id yo'q); prod seed'siz to'ldirilgani uchun bu yerda migratsiya."""
    from app.db.session import SessionLocal
    from app.models.auth import Employee, Permission, Role, RolePermission
    db = SessionLocal()
    try:
        # 1) make_admin ruxsati
        ma = db.query(Permission).filter_by(code="xodimlar.make_admin").first()
        if not ma:
            ma = Permission(code="xodimlar.make_admin", module="xodimlar")
            db.add(ma); db.flush()
            print("[migrate] permission xodimlar.make_admin qo'shildi")
        # 2) Ega roli — hamma ruxsat bilan
        ega = db.query(Role).filter_by(code="ega").first()
        if not ega:
            ega = Role(code="ega", name="Ega"); db.add(ega); db.flush()
            print("[migrate] role 'ega' qo'shildi")
        have = {rp.permission_id for rp in db.query(RolePermission).filter_by(role_id=ega.id).all()}
        for p in db.query(Permission).all():
            if p.id not in have:
                db.add(RolePermission(role_id=ega.id, permission_id=p.id))
        # 3) Administrator make_admin'га EGA bo'lmasin (imtiyoz shifti Ega qo'lida)
        admin = db.query(Role).filter_by(code="administrator").first()
        if admin and ma:
            db.query(RolePermission).filter_by(role_id=admin.id, permission_id=ma.id).delete()
        # 4) Har do'kon egasini (eng eski FAOL administratorni) 'ega' qilamiz — agar hali FAOL ega
        #    bo'lmasa. status=active SHART: to'xtatilgan (suspended) adminni egaga ko'tarib, keyin
        #    has_ega uni "ega bor" deb hisoblab HAQIQIY faol adminni bloklamasin (do'kon egasiz qolmasin).
        from app.models.enums import EmployeeStatus as _ESt
        if admin:
            for (cid,) in db.query(Employee.company_id).distinct().all():
                has_ega = db.query(Employee.id).filter(
                    Employee.company_id == cid, Employee.role_id == ega.id,
                    Employee.status == _ESt.active, Employee.deleted_at.is_(None)).first()
                if has_ega:
                    continue
                owner = (db.query(Employee)
                         .filter(Employee.company_id == cid, Employee.role_id == admin.id,
                                 Employee.status == _ESt.active, Employee.deleted_at.is_(None))
                         .order_by(Employee.created_at.asc()).first())
                if owner:
                    owner.role_id = ega.id
                    print(f"[migrate] ega tayinlandi: {owner.full_name} (company {cid})")
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"[migrate] ega/roles — o'tkazib yuborildi ({e})")
    finally:
        db.close()


def main():
    Base.metadata.create_all(engine)
    _ensure_columns()
    _backfill_company_codes()
    _ensure_indexes()
    _ensure_catalog()          # bazaviy ruxsat/rol/birlik (prod seedsiz ham) — ega'dan OLDIN
    _ensure_roles_and_owner()
    print("[OK] Jadvallar yaratildi")


if __name__ == "__main__":
    main()
