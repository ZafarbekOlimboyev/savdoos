"""Dev/prod uchun jadvallarni yaratish (Alembic o'rniga tez yo'l) + yengil avto-migratsiya."""
from sqlalchemy import inspect, text

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import engine

# Mavjud jadvalga keyinroq qo'shilgan ustunlar (create_all ularni qo'shmaydi).
# (jadval, ustun, SQL-tur) — SQLite ham, Postgres ham tushunadigan turlar.
_ADDED_COLUMNS = [
    ("customer_payments", "cash_account_id", "UUID"),
    # Qurilma telemetriyasi (operator ko'rinishi) — hammasi nullable, mavjud qatorlarga tegmaydi.
    ("sync_devices", "company_id", "UUID"),
    ("sync_devices", "branch_id", "UUID"),
    ("sync_devices", "app_name", "VARCHAR"),
    ("sync_devices", "platform", "VARCHAR"),
    ("sync_devices", "last_seen_at", "TIMESTAMPTZ"),
    ("sync_devices", "pending_ops", "INTEGER"),
    ("sync_devices", "failed_ops", "INTEGER"),
    ("sync_devices", "last_sync_ok_at", "TIMESTAMPTZ"),
    ("products", "sku", "VARCHAR"),
    ("products", "expiry_date", "DATE"),
    ("products", "is_weighted", "BOOLEAN"),
    ("products", "plu_code", "VARCHAR"),
    ("products", "scale_sync", "BOOLEAN"),
    ("companies", "code", "VARCHAR"),
    ("inventory", "low_alerted", "BOOLEAN"),
    ("employees", "sec_epoch", "INTEGER DEFAULT 0"),
    ("cash_movements", "client_uuid", "VARCHAR"),
    ("qr_payments", "sale_id", "VARCHAR"),        # QA PAY-01: qr to'lov qaysi savdoga ishlatilgani (consume)
    ("qr_payments", "client_uuid", "VARCHAR"),    # QA PAY-05: checkout-idempotent QR
    # §5 Purchase custody AUDIT identity (T0 explicit custody): additive + nullable, legacy NULL qoladi
    ("purchases", "cash_account_id", "UUID"),
    ("supplier_payments", "cash_account_id", "UUID"),
    ("purchase_returns", "cash_account_id", "UUID"),
    # Sale/Receipt AUDIT identity (physical drawer revision): "UUID" -> dialekt-mos (PG uuid / SQLite CHAR(32))
    ("shifts", "till_id", "UUID"),                # smena bog'langan fizik TILL (open paytida resolve)
    ("sales", "till_id", "UUID"),                 # savdo bajarilgan fizik TILL (smenadan meros / server-auth)
    ("sales", "cashier_name_snapshot", "VARCHAR"),
    ("sales", "branch_name_snapshot", "VARCHAR"),
    ("sales", "till_code_snapshot", "VARCHAR"),
    ("sales", "till_label_snapshot", "VARCHAR"),
    ("sales", "terminal_name_snapshot", "VARCHAR"),
    ("returns", "shift_id", "UUID"),              # qaytarishни bajarган smena
    ("returns", "till_id", "UUID"),               # qaytariш bajarилган fizik TILL (asl sale TILL'дан farq mumkin)
]


def _ensure_columns():
    insp = inspect(engine)
    dialect = engine.dialect.name
    tables = set(insp.get_table_names())
    for table, col, sqltype in _ADDED_COLUMNS:
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if col in existing:
            continue
        # UUID cross-dialect (app.db.types.UUID bilan izchil): Postgres -> native uuid, SQLite -> CHAR(32).
        _type = (("UUID" if dialect == "postgresql" else "CHAR(32)") if sqltype == "UUID" else sqltype)
        # TIMESTAMPTZ ham dialekt-mos: Postgres -> native, SQLite -> DATETIME (SQLAlchemy'ning
        # DateTime(timezone=True) uchun ishlatadigan turi bilan IZCHIL).
        if sqltype == "TIMESTAMPTZ":
            _type = "TIMESTAMPTZ" if dialect == "postgresql" else "DATETIME"
        try:
            with engine.begin() as con:
                con.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {_type}'))
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


def _migrate_barcodes_per_company():
    """QA PC-003: barcode noyobligi GLOBAL edi (butun SaaS bo'ylab bitta EAN) — endi
    KOMPANIYA doirasida. Idempotent: ustun qo'shish + backfill + eski global unique'ni
    olib tashlash + (company_id, barcode) unique indeks."""
    insp = inspect(engine)
    if "product_barcodes" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("product_barcodes")}
    if "company_id" not in cols:
        coltype = "UUID" if engine.dialect.name == "postgresql" else "CHAR(32)"
        try:
            with engine.begin() as con:
                con.execute(text(f"ALTER TABLE product_barcodes ADD COLUMN company_id {coltype}"))
            print("[migrate] product_barcodes.company_id qo'shildi")
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] product_barcodes.company_id — o'tkazib yuborildi ({e})")
            return
    try:
        with engine.begin() as con:
            con.execute(text(
                "UPDATE product_barcodes SET company_id = "
                "(SELECT company_id FROM products WHERE products.id = product_barcodes.product_id) "
                "WHERE company_id IS NULL"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] product_barcodes backfill — o'tkazib yuborildi ({e})")
    # Eski GLOBAL unique (Postgres avto-nom) — endi kerak emas; SQLite'da jadval ichida
    # qolsa ham yangi dev-bazalar to'g'ri sxema bilan yaratiladi (drop qilinmaydi).
    if engine.dialect.name == "postgresql":
        try:
            with engine.begin() as con:
                con.execute(text("ALTER TABLE product_barcodes DROP CONSTRAINT IF EXISTS product_barcodes_barcode_key"))
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] barcode global-unique drop — o'tkazib yuborildi ({e})")
    try:
        with engine.begin() as con:
            con.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_barcodes_company_bc "
                             "ON product_barcodes (company_id, barcode)"))
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] ux_barcodes_company_bc — o'tkazib yuborildi ({e})")


def _normalize_plu_codes():
    """QA PC-013: PLU satr sifatida saqlanib '123' va '0123' birga yashardi — tarozi esa
    RAQAM bo'yicha o'qiydi. Yetakchi nollarni olib tashlaymiz (to'qnashuv bo'lsa tegmaymiz)."""
    try:
        with engine.begin() as con:
            rows = con.execute(text(
                "SELECT id, company_id, plu_code FROM products "
                "WHERE plu_code IS NOT NULL AND plu_code LIKE '0%' AND deleted_at IS NULL")).fetchall()
            for pid, cid, plu in rows:
                norm = plu.lstrip("0") or "0"
                clash = con.execute(text(
                    "SELECT 1 FROM products WHERE company_id = :c AND plu_code = :p "
                    "AND deleted_at IS NULL AND id != :i"), {"c": cid, "p": norm, "i": pid}).first()
                if clash is None:
                    con.execute(text("UPDATE products SET plu_code = :p WHERE id = :i"), {"p": norm, "i": pid})
                    print(f"[migrate] PLU normalizatsiya: {plu} -> {norm}")
                else:
                    print(f"[migrate] PLU {plu} normalizatsiya QILINMADI — {norm} band (qo'lda hal qiling)")
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] PLU normalizatsiya — o'tkazib yuborildi ({e})")


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
        ("ux_customers_client_uuid",   # QA OFF-5: yangi kredit-mijoz idempotent (response-lost dublikat yo'q)
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_customers_client_uuid "
         "ON customers (company_id, client_uuid) WHERE client_uuid IS NOT NULL AND deleted_at IS NULL"),
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
        # QA PC-007: mahsulot yaratish idempotentligi (retry/2-tab dublikat mahsulot yaratmasin)
        ("ux_products_client_uuid",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_products_client_uuid "
         "ON products (company_id, client_uuid) WHERE client_uuid IS NOT NULL"),
        # QA PC-025: kategoriya nom-noyobligi DB darajasida (app-tekshiruv TOCTOU edi).
        # Mavjud dublikatli bazada yaratilmaydi (try/except) — app-tekshiruv baribir ishlaydi.
        ("ux_categories_company_name",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_company_name "
         "ON categories (company_id, lower(name)) WHERE deleted_at IS NULL"),
        # QA CC-004: mijoz telefoni do'kon ichida noyob (app-tekshiruv TOCTOU edi) — partial,
        # faqat telefonli va o'chirilmagan qatorlar. Mavjud dublikatli bazada yaratilmaydi (try/except).
        ("ux_customers_company_phone",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_customers_company_phone "
         "ON customers (company_id, phone) WHERE phone IS NOT NULL AND deleted_at IS NULL"),
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
        # Sale AUDIT filtrlari (kassa/kassir/smena/terminal/filial bo'yicha savdolar) — sold_at bilan
        # kompozit (company index bilan dublikat emas; queries sold_at bo'yicha filtrlaydi).
        ("ix_sales_branch_sold", "CREATE INDEX IF NOT EXISTS ix_sales_branch_sold ON sales (branch_id, sold_at)"),
        ("ix_sales_cashier_sold", "CREATE INDEX IF NOT EXISTS ix_sales_cashier_sold ON sales (cashier_id, sold_at)"),
        ("ix_sales_till_sold", "CREATE INDEX IF NOT EXISTS ix_sales_till_sold ON sales (till_id, sold_at)"),
        ("ix_sales_terminal_sold", "CREATE INDEX IF NOT EXISTS ix_sales_terminal_sold ON sales (terminal_id, sold_at)"),
        ("ix_sales_shift", "CREATE INDEX IF NOT EXISTS ix_sales_shift ON sales (shift_id)"),
        ("ix_returns_till", "CREATE INDEX IF NOT EXISTS ix_returns_till ON returns (till_id)"),
    ]:
        try:
            with engine.begin() as con:
                con.execute(text(ddl))
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] {name} \u2014 o'tkazib yuborildi ({e})")


# ── customer_groups / brands: do'konga bog'lash (tenancy tuzatishi) ──────────
# Bu ikki jadval dastlabki sxemada `company_id` SIZ e'lon qilingan edi. Ular hech
# qachon yakunlanmagan (CRUD/UI/seed/yozuvchi — hech biri yo'q), shu bois nuqson
# ko'rinmas bo'lib qolgan. `categories` esa YONIDAGI jadval bo'lib, u DOIM do'konga
# bog'langan — ya'ni bu ataylab qilingan "global katalog" emas, tugallanmagan ish.
#
# Kompozit FK NEGA: oddiy FK `customers.group_id` ni BOSHQA do'kon guruhiga
# ko'rsatishga ruxsat berardi. `(company_id, group_id) -> (company_id, id)` esa buni
# BAZA DARAJASIDA imkonsiz qiladi (`cash` sxemasidagi `(tenant_id, id)` naqshi).
# DIQQAT — CHEKLOV NOMLARI MODEL BILAN AYNAN BIR XIL BO'LISHI SHART.
# Ilgari ular jadval nomining kesimidan hosil qilinardi (`uq_custom_...`), model esa
# `uq_cgroup_...` deb e'lon qilardi. Natijada MIGRATSIYA qilingan baza va `create_all`
# bilan YARATILGAN baza HAR XIL cheklov nomlariga ega bo'lardi — keyingi migratsiyalar
# va `DROP CONSTRAINT` lar bir muhitda ishlab, boshqasida yiqilardi.
_TENANCY_TABLES = [
    {
        "table": "customer_groups", "child": "customers", "child_col": "group_id",
        "old_fk": "customers_group_id_fkey", "new_fk": "fk_customers_group_same_company",
        "uq_name": "uq_cgroup_company_name", "uq_id": "uq_cgroup_company_id",
    },
    {
        "table": "brands", "child": "products", "child_col": "brand_id",
        "old_fk": "products_brand_id_fkey", "new_fk": "fk_products_brand_same_company",
        "uq_name": "uq_brand_company_name", "uq_id": "uq_brand_company_id",
    },
]


class UnsafeSchemaError(RuntimeError):
    """Sxema xavfsiz emas va AVTOMATIK tuzatib bo'lmaydi — ishga tushish TO'XTAYDI.

    `start.sh` `set -e` bilan ishlaydi, ya'ni `python -m app.initdb` nol bo'lmagan kod
    bilan tugasa uvicorn UMUMAN ishga tushmaydi. Bu ATAYLAB: egasi noma'lum qatorlar
    ustida ishlayotgan backend "sog'lom" ko'rinishi mumkin emas."""


# ── Migratsiya HOLAT MASHINASI ──────────────────────────────────────────────
#   LEGACY   — `company_id` YO'Q va tuzatishning boshqa izlari ham yo'q
#   MIGRATED — ustun + NOT NULL + companies FK + IKKALA unique + bola KOMPOZIT FK
#   PARTIAL  — oradagi HAR QANDAY holat (yarim qolgan/qo'lda o'zgartirilgan)
#
# LEGACY  + 0 qator  -> migratsiya
# LEGACY  + qator    -> FATAL (egasi noma'lum, TAXMIN QILINMAYDI)
# MIGRATED           -> no-op (qator bo'lishi MUTLAQO normal)
# PARTIAL            -> FATAL (jimgina davom etish "nol qoldiq"ni yolg'onga aylantiradi)
_ST_LEGACY, _ST_MIGRATED, _ST_PARTIAL = "LEGACY", "MIGRATED", "PARTIAL"


def _tenancy_state(con, spec) -> tuple[str, dict]:
    """Jadvalning migratsiya holatini DALILLAR bilan aniqlaydi."""
    tbl, child = spec["table"], spec["child"]

    col = con.execute(text("""
        SELECT is_nullable FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t AND column_name='company_id'
    """), {"t": tbl}).scalar()

    def _con_exists(name):
        return bool(con.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}).first())

    fk_companies = bool(con.execute(text("""
        SELECT 1 FROM pg_constraint c
        JOIN pg_class ch ON ch.oid = c.conrelid
        JOIN pg_class pa ON pa.oid = c.confrelid
        WHERE c.contype='f' AND ch.relname=:t AND pa.relname='companies'
    """), {"t": tbl}).first())

    ev = {
        "company_id": ("yo'q" if col is None else f"bor (nullable={col})"),
        "fk_companies": fk_companies,
        spec["uq_name"]: _con_exists(spec["uq_name"]),
        spec["uq_id"]: _con_exists(spec["uq_id"]),
        spec["new_fk"]: _con_exists(spec["new_fk"]),
        "old_fk_" + spec["old_fk"]: _con_exists(spec["old_fk"]),
    }

    artifacts = [fk_companies, ev[spec["uq_name"]], ev[spec["uq_id"]], ev[spec["new_fk"]]]
    if col is None and not any(artifacts):
        return _ST_LEGACY, ev
    if col == "NO" and all(artifacts):
        return _ST_MIGRATED, ev
    return _ST_PARTIAL, ev


def _migrate_one(con, spec):
    """Bitta jadvalni ko'chiradi. Chaqiruvchi tranzaksiyani boshqaradi."""
    tbl, child, child_col = spec["table"], spec["child"], spec["child_col"]

    # ⚠️  USTUNLARNI AYNAN SHU ULANISHDA (`con`) o'qiymiz. Ilgari bu yerda
    # `insp.get_columns(tbl)` chaqirilardi — Inspector esa pooldan IKKINCHI ulanish
    # oladi. Biz jadvalni ACCESS EXCLUSIVE bilan ushlab turganimiz uchun o'sha
    # ikkinchi ulanish ACCESS SHARE kutib ABADIY osilardi (`lock_timeout` faqat
    # BIZNING ulanishimizga qo'yilgan). Ya'ni boot migratsiyasi jadvalni qulflab,
    # o'zini o'zi bloklab qo'yardi.
    cols = {r[0] for r in con.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name = :t
    """), {"t": tbl})}

    con.execute(text(
        f'ALTER TABLE "{tbl}" ADD COLUMN company_id uuid NOT NULL REFERENCES companies(id)'))
    for extra, ddl in (
        ("created_at", "timestamptz NOT NULL DEFAULT now()"),
        ("updated_at", "timestamptz NOT NULL DEFAULT now()"),
        ("deleted_at", "timestamptz"),
        ("row_version", "bigint NOT NULL DEFAULT 1"),
        ("client_uuid", "uuid"),
    ):
        if extra not in cols:
            con.execute(text(f'ALTER TABLE "{tbl}" ADD COLUMN {extra} {ddl}'))

    con.execute(text(
        f'ALTER TABLE "{tbl}" ADD CONSTRAINT {spec["uq_name"]} UNIQUE (company_id, name)'))
    con.execute(text(
        f'ALTER TABLE "{tbl}" ADD CONSTRAINT {spec["uq_id"]} UNIQUE (company_id, id)'))

    # Bolaning ODDIY FK'sini KOMPOZIT bilan almashtiramiz.
    con.execute(text(f'ALTER TABLE "{child}" DROP CONSTRAINT IF EXISTS "{spec["old_fk"]}"'))
    con.execute(text(
        f'ALTER TABLE "{child}" ADD CONSTRAINT "{spec["new_fk"]}" '
        f'FOREIGN KEY (company_id, {child_col}) REFERENCES "{tbl}" (company_id, id)'))


def _ensure_tenant_scoped_catalogs():
    """`customer_groups` va `brands` ni do'konga bog'laydi — IDEMPOTENT va FAIL-CLOSED.

    ⚠️  QATOR BO'LSA MIGRATSIYA QILINMAYDI VA ISHGA TUSHISH TO'XTAYDI.
    `company_id NOT NULL` to'ldirish uchun mavjud qatorlarning EGASINI bilish kerak;
    uni taxmin qilib bo'lmaydi. Ilgari bu holatda ogohlantirish chiqarib, ilova
    baribir ko'tarilardi — ya'ni backend EGASI NOMA'LUM ma'lumot ustida "sog'lom"
    ishlayverardi. Bu fail-OPEN edi va tuzatildi: endi FATAL.

    MUHIM FARQ: MIGRATSIYA QILINGAN jadvalda qator bo'lishi — MUTLAQO NORMAL
    (haqiqiy do'kon guruhlari/brendlari). Faqat MIGRATSIYA QILINMAGAN jadvaldagi
    egasi noma'lum qatorlar bloklaydi.

    ATOMIKLIK: IKKALA jadval BITTA tranzaksiyada ko'chiriladi. Ilgari har jadval
    o'z tranzaksiyasida edi va `customer_groups` muvaffaqiyatli, `brands` esa xato
    bo'lsa — baza YARIM ko'chirilgan holatda qolardi. Endi istalgan xato IKKALASINI
    ham qaytaradi.

    UCH BOSQICH: (1) qulf + baho, (2) ko'chirish, (3) natijani tasdiqlash."""
    if engine.dialect.name != "postgresql":
        return                      # SQLite (dev/e2e): create_all yangi sxemani beradi
    tables = set(inspect(engine).get_table_names())
    todo = [sp for sp in _TENANCY_TABLES
            if sp["table"] in tables and sp["child"] in tables]
    if not todo:
        return

    with engine.begin() as con:
        # Qulf MUDDATLI: boot migratsiyasi HECH QACHON cheksiz kutmasligi kerak.
        # Muddatsiz `LOCK TABLE` boshqa seans jadvalni ushlab tursa ilovani ABADIY
        # osib qo'yardi — bu ham fail-open shakli (servis ko'tarilmaydi, sababi ham
        # ko'rinmaydi). Endi 5 soniyada BALAND xato.
        con.execute(text("SET LOCAL lock_timeout = '5s'"))

        # ── 1-BOSQICH: qulflash va BARCHA jadvallarni baholash ─────────────
        # TOCTOU himoyasi: holat va sanoqni o'qishdan OLDIN qulflaymiz, aks holda
        # tekshiruv bilan ALTER orasida boshqa seans qator qo'shib ulgurishi va u
        # JIMGINA company_id'siz qolishi mumkin edi.
        plan = []
        for spec in todo:
            tbl = spec["table"]
            try:
                con.execute(text(f'LOCK TABLE "{tbl}" IN ACCESS EXCLUSIVE MODE'))
            except Exception as e:      # noqa: BLE001
                raise UnsafeSchemaError(
                    f"`{tbl}`: jadval qulflanmadi ({str(e).splitlines()[0]}). "
                    "Boshqa seans jadvalni ushlab turibdi — migratsiya XAVFSIZ emas, "
                    "ishga tushish TO'XTATILDI. Trafik to'xtaganda qayta urining.") from e

            state, ev = _tenancy_state(con, spec)
            if state == _ST_MIGRATED:
                continue                # allaqachon to'g'ri — qatorlari bo'lsa ham OK
            if state == _ST_PARTIAL:
                raise UnsafeSchemaError(
                    f"`{tbl}`: sxema YARIM MIGRATSIYA holatida — ishga tushish TO'XTATILDI.\n"
                    f"  dalillar: {ev}\n"
                    "  Yarim holat jimgina o'tkazilmaydi: ba'zi cheklovlar bor, ba'zilari "
                    "yo'q, ya'ni cross-tenant himoyasi QISMAN. Sxemani qo'lda to'g'rilang.")

            n = con.execute(text(f'SELECT count(*) FROM "{tbl}"')).scalar()
            if n:
                raise UnsafeSchemaError(
                    f"`{tbl}`: {n} ta qator bor, LEKIN jadval hali do'konga BOG'LANMAGAN "
                    "— ishga tushish TO'XTATILDI.\n"
                    "  `company_id NOT NULL` to'ldirish uchun bu qatorlarning EGASI kerak; "
                    "uni taxmin qilib bo'lmaydi va noto'g'ri taxmin ma'lumotni BOSHQA "
                    "do'konga biriktirib qo'yardi.\n"
                    "  Bu jadvalga kodda hech kim yozmaydi, ya'ni qatorlar kutilmagan. "
                    "Ularni ko'rib chiqing va (egasi aniqlangach) qo'lda biriktiring yoki "
                    "o'chiring, so'ng qayta ishga tushiring.")
            plan.append(spec)

        if not plan:
            return                      # hammasi allaqachon MIGRATED

        # ── 2-BOSQICH: ko'chirish (hammasi shu tranzaksiyada) ─────────────
        for spec in plan:
            _migrate_one(con, spec)

        # ── 3-BOSQICH: natijani tasdiqlash — yarim holat COMMIT bo'lmasin ──
        for spec in plan:
            after, ev2 = _tenancy_state(con, spec)
            if after != _ST_MIGRATED:
                raise UnsafeSchemaError(
                    f"`{spec['table']}`: migratsiyadan keyin holat MIGRATED emas "
                    f"({after}) — rollback qilinadi. dalillar: {ev2}")
            print(f"[migrate] {spec['table']}: company_id + kompozit FK "
                  f"({spec['child']}.{spec['child_col']}) qo'shildi")


def tenancy_schema_ok() -> tuple[bool, dict]:
    """Readiness uchun: ikkala jadval ham MIGRATED holatidami.

    Ikkinchi himoya qatlami — kimdir `initdb`siz to'g'ridan-to'g'ri uvicorn ishga
    tushirsa ham, backend XAVFSIZ BO'LMAGAN sxemada "tayyor" deb ko'rinmasligi kerak."""
    if engine.dialect.name != "postgresql":
        return True, {"dialect": engine.dialect.name}
    try:
        detail = {}
        with engine.connect() as con:
            existing = set(inspect(engine).get_table_names())
            for spec in _TENANCY_TABLES:
                if spec["table"] not in existing:
                    continue
                state, _ev = _tenancy_state(con, spec)
                detail[spec["table"]] = state
        return all(v == _ST_MIGRATED for v in detail.values()), detail
    except Exception as e:      # noqa: BLE001
        return False, {"error": str(e)[:120]}


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
    _migrate_barcodes_per_company()   # QA PC-003: barcode endi kompaniya-doirali
    _normalize_plu_codes()            # QA PC-013: PLU yetakchi nollarsiz
    _ensure_indexes()
    _ensure_tenant_scoped_catalogs()   # customer_groups/brands -> do'konga bog'lash
    _ensure_catalog()          # bazaviy ruxsat/rol/birlik (prod seedsiz ham) — ega'dan OLDIN
    _ensure_roles_and_owner()
    _deploy_cash()             # Cash quyi tizimi (faqat Postgres) — legacy jadvallar YONIGA
    print("[OK] Jadvallar yaratildi")


def _deploy_cash():
    """Cash `cash` sxemasini o'rnatadi (Postgres). SQLite'da no-op. Non-destructive,
    idempotent — legacy public.* jadvallar tegilmaydi (faqat REFERENCE)."""
    try:
        from app.db.cash.deploy import deploy_cash_schema
        result = deploy_cash_schema(engine)
        print(f"[cash] sxema: {result}")
    except Exception as e:  # noqa: BLE001
        # Cash sxemasi (masalan CREATEROLE huquqi yo'q managed Postgres'да) o'rnatilmasa —
        # legacy tizim ishlashda davom etadi; migration owner alohida qo'llaydi (§21).
        print(f"[cash] sxema o'rnatilmadi — o'tkazib yuborildi ({e})")


if __name__ == "__main__":
    main()
