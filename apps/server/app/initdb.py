"""Dev/prod uchun jadvallarni yaratish (Alembic o'rniga tez yo'l) + yengil avto-migratsiya."""
import time

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
    # 1C Cutover V2: tashqi tizim identifikatsiyasi. Ikkalasi ham NULLABLE — mavjud
    # mahsulotlar NULL bo'lib qoladi va hech qanday kod ularni o'qimaydi.
    #
    # !!  BU IKKI QATOR HAYOTIY: `create_all()` faqat YO'Q jadvalni yaratadi, MAVJUD
    #     jadvalga ustun QO'SHMAYDI. Ular bo'lmasa bo'sh bazada (testlar) hammasi
    #     ishlaydi, lekin JONLI bazada `ux_products_external_identity` "column does
    #     not exist" bilan yiqiladi va V2 jimgina identifikatsiyasiz qoladi.
    ("products", "source_system", "VARCHAR"),
    ("products", "external_id", "VARCHAR"),
    # 1C Cutover V2 Phase 2 — snapshot identifikatsiyasi va import hayot sikli.
    # `ux_movements_cutover_key` AYNAN shu ikki ustunga tayanadi va u endi MAJBURIY
    # (yaratilmasa ishga tushish to'xtaydi). Ular modelda bor, lekin `create_all`
    # MAVJUD jadvalga ustun QO'SHMAYDI — ya'ni eski bazada indeks hech qachon
    # yaratilmasdi va endi bu abadiy boot-loop bo'lardi. Shu bois migratsiyaga
    # kiritildi: darvoza tayanadigan narsa darvoza bilan birga ta'minlanadi.
    ("stock_movements", "client_uuid", "UUID"),
    # ── PARTIYA POYDEVORI (Phase 0) — FAQAT SXEMA, ish vaqti kodi hali YO'Q ──
    #    Hammasi NULLABLE yoki DEFAULT'li: mavjud qatorlarga TEGMAYDI, mavjud
    #    kod ularni o'qimaydi. `required_schema` ga HOZIR qo'shilmaydi — qoida:
    #    obyekt tayyorlikda majburiy bo'ladi FAQAT ish vaqti unga tayangan relizda.
    ("products", "track_lots", "BOOLEAN DEFAULT 0"),
    ("products", "track_expiry", "BOOLEAN DEFAULT 0"),
    ("stock_batches", "company_id", "UUID"),
    ("stock_batches", "received_qty", "NUMERIC(14,3) DEFAULT 0"),
    ("stock_batches", "remaining_qty", "NUMERIC(14,3) DEFAULT 0"),
    ("stock_batches", "status", "VARCHAR DEFAULT 'open'"),
    ("stock_batches", "source_type", "VARCHAR"),
    ("stock_batches", "purchase_item_id", "UUID"),
    ("stock_batches", "receiving_id", "UUID"),
    ("stock_batches", "external_lot_id", "VARCHAR"),
    ("stock_batches", "supplier_id", "UUID"),
    ("stock_batches", "client_uuid", "UUID"),
    ("stock_batches", "updated_at", "TIMESTAMPTZ"),
    ("stock_batches", "row_version", "INTEGER DEFAULT 1"),
    ("purchase_items", "batch_no", "VARCHAR"),
    ("return_items", "sale_item_id", "UUID"),

    ("stock_movements", "ref_type", "VARCHAR"),
    ("import_jobs", "snapshot_id", "VARCHAR"),
    ("import_jobs", "content_sha256", "VARCHAR"),
    ("import_jobs", "mode", "VARCHAR"),
    ("import_jobs", "error", "TEXT"),
    ("import_jobs", "applied_rows", "INTEGER DEFAULT 0"),
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


def _required_column(table: str, col: str) -> bool:
    """Bu ustun 1C Cutover V2 uchun MAJBURIYmi (va muhit uni talab qiladimi)."""
    from app.core import required_schema as rs
    return rs.enforced(engine) and (table, col) in rs.REQUIRED_COLUMNS


def _required_index(name: str) -> bool:
    from app.core import required_schema as rs
    return rs.enforced(engine) and name in {n for n, _ in rs.REQUIRED_INDEXES}


def _index(con_sql: str, name: str) -> None:
    """Indeks yaratadi. MAJBURIY bo'lsa — yiqilganda ishga tushish TO'XTAYDI."""
    try:
        with engine.begin() as con:
            con.execute(text(con_sql))
    except Exception as e:  # noqa: BLE001
        if _required_index(name):
            print(f"[FATAL] MAJBURIY indeks yaratilmadi: {name} — {e}")
            raise
        print(f"[migrate] {name} — o'tkazib yuborildi ({e})")


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
            # MAJBURIY ustun yiqilsa — JIM O'TMAYDI. Aks holda konteyner sog'lom
            # ko'tarilardi va V2 identifikatsiyasiz ishlardi (staging'da aynan shu
            # bo'lgan: «column source_system does not exist»).
            if _required_column(table, col):
                print(f"[FATAL] MAJBURIY ustun qo'shilmadi: {table}.{col} — {e}")
                raise
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
    # 1C cutover qoldiq-rekonsiliatsiyasi TAKRORLANMASIN (DB darajasida).
    #
    # !!  Shart `ref_type='1c_cutover'` bilan TOR: `stock_movements.client_uuid`
    #     boshqa yo'llarda (inventarizatsiya, transfer) BIR uuid bir nechta
    #     mahsulot qatorida ishlatiladi — global noyoblik ularni buzardi.
    #     Cutover kaliti esa uuid5(job_id, product_id), ya'ni har juftlik uchun
    #     bitta. Bu bo'lmasa SELECT-tekshiruv TOCTOU poygasiga ochiq qolardi.
    # ── PARTIYA POYDEVORI indekslari (Phase 0) ────────────────────────────
    #  ux_lot_intake_key — QABUL IDEMPOTENTLIGI. Takroriy yetkazib berish
    #  ikkinchi partiya YARATMAYDI. Identifikatsiya — qabul AMALI (client_uuid),
    #  atributlar (muddat/partiya raqami/narx) EMAS: bir xil atributli ikkinchi
    #  yetkazib berish ALOHIDA kogorta bo'lishi SHART.
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_lot_intake_key "
           "ON stock_batches (company_id, client_uuid) WHERE client_uuid IS NOT NULL",
           "ux_lot_intake_key")
    #  ix_lot_fefo — ustunlar tartibi AYNAN FEFO saralash tartibi, shu bois
    #  taqsimlash so'rovi indeksdan o'qiydi va qo'shimcha saralash qilmaydi.
    _index("CREATE INDEX IF NOT EXISTS ix_lot_fefo "
           "ON stock_batches (company_id, branch_id, product_id, expiry_date, received_at, id) "
           "WHERE remaining_qty > 0 AND status = 'open'",
           "ix_lot_fefo")
    #  ix_lot_expiry — muddat hisoboti to'liq jadval skanerlamasin.
    _index("CREATE INDEX IF NOT EXISTS ix_lot_expiry "
           "ON stock_batches (company_id, expiry_date) "
           "WHERE remaining_qty > 0 AND status = 'open' AND expiry_date IS NOT NULL",
           "ix_lot_expiry")
    _index("CREATE INDEX IF NOT EXISTS ix_alloc_lot "
           "ON sale_item_lot_allocations (stock_batch_id)", "ix_alloc_lot")
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_movements_cutover_key "
           "ON stock_movements (client_uuid) "
           "WHERE client_uuid IS NOT NULL AND ref_type = '1c_cutover'",
           "ux_movements_cutover_key")
    # BITTA snapshot uchun BITTA commit-yo'li. Qisman shart `committing`/`committed`
    # bilan: preview (validated) qatorlari cheklanmaydi, lekin ikkita PARALLEL commit
    # DB darajasida mumkin emas — poygada biri UniqueViolation oladi va ikkinchisining
    # natijasini KUZATADI (jim ikkinchi import boshlanmaydi).
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_import_jobs_snapshot "
           "ON import_jobs (company_id, source, snapshot_id) "
           "WHERE snapshot_id IS NOT NULL "
           "AND status IN ('committing', 'committed')",
           "ux_import_jobs_snapshot")
    # Do'kon kodi noyobligi (bo'sh bo'lmagan, o'chirilmagan) \u2014 SQLite + Postgres.
    # 1C Cutover V2 — TASHQI IDENTIFIKATSIYA NOYOBLIGI (do'kon doirasida, ABADIY).
    #
    # !!  `deleted_at IS NULL` sharti ATAYLAB YO'Q. Boshqa qisman indekslarda u bor
    #     (PLU, telefon, do'kon kodi) — u yerda o'chirilgan yozuv resursni BO'SHATISHI
    #     kerak. Bu yerda TESKARI: 1C GUID'i mahsulotning butun tarixi davomida BITTA
    #     identifikatsiyani bildirishi shart. Filtr qo'yilsa, o'chirilgan mahsulotning
    #     GUID'i bilan IKKINCHI Product yaratilardi va tarixiy identifikatsiya JIMGINA
    #     ikkiga bo'linardi. Import o'chirilgan moslikni `DELETED_MATCH` deb tasniflaydi
    #     va operatordan qaror so'raydi (REACTIVATE_EXISTING / KEEP_DELETED).
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_products_external_identity "
           "ON products (company_id, source_system, external_id) "
           "WHERE source_system IS NOT NULL AND external_id IS NOT NULL",
           "ux_products_external_identity")
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
#   LEGACY       — `company_id` YO'Q va tuzatishning boshqa izlari ham yo'q
#   MIGRATED     — ustun + NOT NULL + companies FK + IKKALA unique + bola KOMPOZIT FK,
#                  hamda `row_version` da server default YO'Q (model bilan AYNAN mos)
#   NEEDS_REPAIR — TENANCY to'liq joyida, faqat `row_version` da ORTIQCHA server
#                  default qolgan (eski migratsiya qoldirgan)
#   PARTIAL      — TENANCY cheklovlarining o'zi CHALA
#
# LEGACY  + 0 qator  -> migratsiya
# LEGACY  + qator    -> FATAL (egasi noma'lum, TAXMIN QILINMAYDI)
# MIGRATED           -> no-op (qator bo'lishi MUTLAQO normal)
# NEEDS_REPAIR       -> `DROP DEFAULT` (metama'lumot, 0 qator tegiladi) -> MIGRATED
# PARTIAL            -> FATAL (jimgina davom etish "nol qoldiq"ni yolg'onga aylantiradi)
#
# ⚠️  NEEDS_REPAIR ni PARTIAL dan AJRATISH SHART. Ilgari ajratilmagan edi va bu
#     production'ni ISHDAN CHIQARDI: 1386599 migratsiyasi `row_version` da
#     `DEFAULT 1` qoldirgan; 865f562 esa uni MIGRATED emas deb baholay boshladi,
#     natijada TO'LIQ va TO'G'RI ko'chirilgan baza "yarim migratsiya" deb
#     hisoblanib, boot ABADIY crash-loop ga tushdi (production + staging, 502).
#     Farq muhim: `DEFAULT 1` — MODEL BILAN MOSLIK nuqsoni, XAVFSIZLIK nuqsoni
#     EMAS. company_id NOT NULL, companies FK, ikkala UNIQUE va bola KOMPOZIT FK
#     joyida bo'lsa, cross-tenant himoyasi TO'LIQ ishlaydi. Bunday holatni
#     bloklash emas, TUZATISH kerak — `DROP DEFAULT` metama'lumot amali,
#     birorta qatorni o'qimaydi ham, yozmaydi ham.
_ST_LEGACY, _ST_MIGRATED, _ST_PARTIAL = "LEGACY", "MIGRATED", "PARTIAL"
_ST_NEEDS_REPAIR = "NEEDS_REPAIR"


# Cheklovni NOMI bo'yicha emas, SHAKLI bo'yicha o'qiydi.
#
# ⚠️  Ilgari tekshiruv `SELECT 1 FROM pg_constraint WHERE conname = :n` edi — na
#     jadval, na sxema, na turi, na ustunlari solishtirilmasdi. Ya'ni BUTUN bazada
#     shu NOMDAGI istalgan cheklov "tenancy himoyasi joyida" degan xulosaga
#     yetarli bo'lardi: boshqa jadvaldagi begona cheklov, hatto boshqa TURDAGI
#     (CHECK) cheklov ham. Bu yerda xulosa `MIGRATED` ga, `MIGRATED` esa
#     backend'ning trafik qabul qilishiga olib boradi — shuning uchun taxminiy
#     "nom bor" yetarli emas.
_CON_SHAPE_SQL = text("""
    SELECT c.contype,
           c.convalidated,
           ARRAY(SELECT a.attname
                 FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                 ORDER BY k.ord)                                   AS cols,
           pf.relname                                              AS reftable,
           ARRAY(SELECT a.attname
                 FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum
                 ORDER BY k.ord)                                   AS refcols
    FROM pg_constraint c
    JOIN pg_class ch     ON ch.oid = c.conrelid
    JOIN pg_namespace n  ON n.oid = ch.relnamespace
    LEFT JOIN pg_class pf ON pf.oid = c.confrelid
    WHERE c.conname = :n AND ch.relname = :r AND n.nspname = 'public'
""")


def _con_shape(con, name, relname):
    """`public.<relname>` dagi `<name>` cheklovining shakli (yo'q bo'lsa None)."""
    r = con.execute(_CON_SHAPE_SQL, {"n": name, "r": relname}).first()
    if r is None:
        return None
    return {"contype": r[0], "validated": r[1], "cols": list(r[2] or []),
            "reftable": r[3], "refcols": list(r[4] or [])}


def _uq_ok(shape, cols):
    """UNIQUE aynan shu ustunlar to'plamida. Tartib AHAMIYATSIZ — `UNIQUE (a, b)`
    va `UNIQUE (b, a)` bir xil kafolat beradi, shuning uchun to'plam solishtiriladi
    (ortiqcha qat'iylik bekordan-bekorga PARTIAL berib, boot'ni bloklardi)."""
    return bool(shape) and shape["contype"] == "u" and set(shape["cols"]) == set(cols)


def _fk_ok(shape, mapping, reftable):
    """FK aynan shu jadvalga va aynan shu ustun JUFTLIKLARI bilan, hamda TASDIQLANGAN.

    ⚠️  `convalidated` SHART. `NOT VALID` FK yangi yozuvlarni tekshiradi, lekin
        MAVJUD qatorlarni TEKSHIRMAYDI — ya'ni allaqachon boshqa do'konga ishora
        qilayotgan qatorlar joyida qolaveradi. Bunday cheklov "cross-tenant
        bog'lanish BAZA DARAJASIDA imkonsiz" degan da'voni bajarmaydi, shuning
        uchun u tenancy artefakti sifatida HISOBGA OLINMAYDI.

    Juftliklar to'plam sifatida solishtiriladi: `(a,b)->(x,y)` va `(b,a)->(y,x)`
    bir xil cheklov."""
    if not shape or shape["contype"] != "f" or not shape["validated"]:
        return False
    if shape["reftable"] != reftable:
        return False
    return set(zip(shape["cols"], shape["refcols"])) == set(mapping)


def _tenancy_state(con, spec) -> tuple[str, dict]:
    """Jadvalning migratsiya holatini DALILLAR bilan aniqlaydi."""
    tbl, child, child_col = spec["table"], spec["child"], spec["child_col"]

    col = con.execute(text("""
        SELECT is_nullable FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t AND column_name='company_id'
    """), {"t": tbl}).scalar()

    # `company_id -> companies(id)` — nomi o'zgaruvchan (`create_all` va migratsiya
    # har xil nom beradi), shuning uchun bu bittasi SHAKL bo'yicha izlanadi. Lekin
    # jadval, sxema va TASDIQLANGANLIK baribir talab qilinadi.
    fk_companies = bool(con.execute(text("""
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class ch     ON ch.oid = c.conrelid
        JOIN pg_namespace n  ON n.oid = ch.relnamespace
        JOIN pg_class pa     ON pa.oid = c.confrelid
        JOIN pg_namespace pn ON pn.oid = pa.relnamespace
        WHERE c.contype = 'f' AND c.convalidated
          AND n.nspname = 'public' AND ch.relname = :t
          AND pn.nspname = 'public' AND pa.relname = 'companies'
          AND (SELECT a.attname FROM pg_attribute a
               WHERE a.attrelid = c.conrelid AND a.attnum = c.conkey[1]) = 'company_id'
    """), {"t": tbl}).first())

    uq_name_sh = _con_shape(con, spec["uq_name"], tbl)
    uq_id_sh = _con_shape(con, spec["uq_id"], tbl)
    new_fk_sh = _con_shape(con, spec["new_fk"], child)
    old_fk_sh = _con_shape(con, spec["old_fk"], child)

    ev = {
        "company_id": ("yo'q" if col is None else f"bor (nullable={col})"),
        "fk_companies": fk_companies,
        spec["uq_name"]: _uq_ok(uq_name_sh, ("company_id", "name")),
        spec["uq_id"]: _uq_ok(uq_id_sh, ("company_id", "id")),
        spec["new_fk"]: _fk_ok(new_fk_sh,
                               [("company_id", "company_id"), (child_col, "id")], tbl),
        "old_fk_" + spec["old_fk"]: old_fk_sh is not None,
    }
    # Nomi bor-u shakli MOS EMAS bo'lsa — sababi dalillarda KO'RINSIN, aks holda
    # operator "cheklov bor-ku" deb o'ylab, nima uchun PARTIAL ekanini topolmaydi.
    for key, sh in ((spec["uq_name"], uq_name_sh), (spec["uq_id"], uq_id_sh),
                    (spec["new_fk"], new_fk_sh)):
        if sh is not None and not ev[key]:
            ev[key + "__shakli"] = sh

    # `row_version` da SERVER DEFAULT bo'lmasligi SHART — model (`SyncMixin`) uni
    # Python tomonda beradi. Server default qolsa, ko'chirilgan baza `create_all`
    # bilan yaratilganidan farq qilardi.
    rv_default = con.execute(text("""
        SELECT column_default FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t AND column_name='row_version'
    """), {"t": tbl}).scalar()
    ev["row_version_server_default"] = rv_default
    rv_ok = rv_default is None

    artifacts = [fk_companies, ev[spec["uq_name"]], ev[spec["uq_id"]], ev[spec["new_fk"]]]
    # TENANCY himoyasi to'liqmi? Bu — XAVFSIZLIK savoli.
    tenancy_ok = col == "NO" and all(artifacts)

    if col is None and not any(artifacts):
        return _ST_LEGACY, ev
    if tenancy_ok:
        # Himoya joyida. Qolgani — MODEL BILAN MOSLIK, uni o'zimiz tuzata olamiz.
        return (_ST_MIGRATED if rv_ok else _ST_NEEDS_REPAIR), ev
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

    # `FullMixin` ustunlari. Uchinchi maydon — SERVER DEFAULT SAQLANADIMI.
    #
    # ⚠️  `row_version` uchun FALSE, va bu MUHIM. `SyncMixin` da u shunday e'lon qilingan:
    #         row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    #     `default=` — PYTHON tomonidagi qiymat; SQLAlchemy uni INSERT paytida o'zi
    #     qo'yadi va DDL'ga `DEFAULT` YOZMAYDI. `created_at`/`updated_at` esa
    #     `server_default=func.now()` bilan e'lon qilingan, ya'ni ularda DDL default BOR.
    #
    #     Agar migratsiya `row_version` ni doimiy `DEFAULT 1` bilan qoldirsa, KO'CHIRILGAN
    #     baza `create_all` bilan yaratilganidan FARQ QILARDI — ya'ni "model va migratsiya
    #     bir xil sxema beradi" degani YOLG'ON bo'lardi. Bo'sh jadvalda `DEFAULT` shart
    #     emas, lekin uni VAQTINCHA qo'yish generik DDL uchun xavfsizroq; shu bois
    #     qo'yamiz va AYNI TRANZAKSIYADA olib tashlaymiz.
    for extra, ddl, keep_default in (
        ("created_at", "timestamptz NOT NULL DEFAULT now()", True),
        ("updated_at", "timestamptz NOT NULL DEFAULT now()", True),
        ("deleted_at", "timestamptz", True),
        ("row_version", "bigint NOT NULL DEFAULT 1", False),
        ("client_uuid", "uuid", True),
    ):
        if extra in cols:
            continue
        con.execute(text(f'ALTER TABLE "{tbl}" ADD COLUMN {extra} {ddl}'))
        if not keep_default:
            # AYNI tranzaksiyada — yakuniy sxemada server default QOLMAYDI.
            con.execute(text(f'ALTER TABLE "{tbl}" ALTER COLUMN {extra} DROP DEFAULT'))

    con.execute(text(
        f'ALTER TABLE "{tbl}" ADD CONSTRAINT {spec["uq_name"]} UNIQUE (company_id, name)'))
    con.execute(text(
        f'ALTER TABLE "{tbl}" ADD CONSTRAINT {spec["uq_id"]} UNIQUE (company_id, id)'))

    # Bolaning ODDIY FK'sini KOMPOZIT bilan almashtiramiz.
    con.execute(text(f'ALTER TABLE "{child}" DROP CONSTRAINT IF EXISTS "{spec["old_fk"]}"'))
    con.execute(text(
        f'ALTER TABLE "{child}" ADD CONSTRAINT "{spec["new_fk"]}" '
        f'FOREIGN KEY (company_id, {child_col}) REFERENCES "{tbl}" (company_id, id)'))


def _repair_one(con, spec):
    """`row_version` dagi ORTIQCHA server default'ni olib tashlaydi.

    Bu — SOF METAMA'LUMOT amali: `ALTER COLUMN ... DROP DEFAULT` birorta qatorni
    o'qimaydi ham, yozmaydi ham, jadvalni qayta yozmaydi. Shuning uchun jadvalda
    qator bo'lishi AHAMIYATSIZ va egalik savoli UMUMAN tug'ilmaydi — LEGACY
    migratsiyasidan farqli o'laroq, bu yerda hech narsa taxmin qilinmaydi.

    Chaqiruvchi tranzaksiyani va ACCESS EXCLUSIVE qulfni boshqaradi."""
    con.execute(text(
        f'ALTER TABLE "{spec["table"]}" ALTER COLUMN row_version DROP DEFAULT'))


# ── QULF TARTIBI va DARAJALARI ──────────────────────────────────────────────
# Migratsiya/tuzatish DDL'i AMALDA qanday qulf olishi O'LCHANGAN (`pg_locks`):
#
#   ALTER COLUMN row_version DROP DEFAULT       -> ACCESS EXCLUSIVE (ota)
#   ADD COLUMN company_id NOT NULL REFERENCES   -> ACCESS EXCLUSIVE (ota)
#                                                  SHARE ROW EXCLUSIVE (companies)
#   ADD CONSTRAINT ... UNIQUE                   -> ACCESS EXCLUSIVE (ota)
#   DROP CONSTRAINT <bola FK>                   -> ACCESS EXCLUSIVE (bola VA ota)
#   ADD CONSTRAINT ... FOREIGN KEY              -> SHARE ROW EXCLUSIVE (ikkalasi)
#
# Shuning uchun har jadvalga AMALDA KERAK BO'LGAN eng kuchli daraja qo'yiladi —
# ko'proq emas. `companies` faqat SHARE ROW EXCLUSIVE oladi, ya'ni u bo'yicha
# o'qish (va `pg_dump`) BLOKLANMAYDI.
#
# TARTIB QAT'IY va GLOBAL (alifbo). Deadlock qulf DARAJASIDAN emas, TARTIB
# nomuvofiqligidan kelib chiqadi: ilgari 1-bosqich faqat OTA jadvallarni
# qulflardi, 2-bosqich esa `customers`/`products` da ACCESS EXCLUSIVE va
# `companies` da SHARE ROW EXCLUSIVE olardi — ya'ni qulflar oldindan e'lon
# qilinmagan tartibda o'sardi.
_LOCK_ORDER = ("brands", "companies", "customer_groups", "customers", "products")
_LOCK_LEVEL = {
    "brands": "ACCESS EXCLUSIVE",
    "customer_groups": "ACCESS EXCLUSIVE",
    "customers": "ACCESS EXCLUSIVE",
    "products": "ACCESS EXCLUSIVE",
    "companies": "SHARE ROW EXCLUSIVE",
}

# Qulf band bo'lsa NECHA MARTA qayta urinamiz. Cheksiz kutish YO'Q.
# Sabab: rolling deploy'da IKKI instansiya bir vaqtda ko'tarilishi mumkin. Biri
# qulfni olib migratsiyani bajaradi, ikkinchisi `lock_timeout` ga uchraydi.
# Ikkinchisini darhol yiqitish KERAKSIZ crash bo'lardi — u aslida hech narsa
# qilishi shart emas, chunki ish allaqachon bajarilgan. Shuning uchun qulf band
# bo'lsa QULFSIZ prechek qayta yurgiziladi.
_LOCK_RETRIES = 3
_LOCK_RETRY_SLEEP = 2.0


def _precheck_states():
    """QULFSIZ holat o'qish — HAR jadval uchun (holat, dalillar).

    ⚠️  Bu yerda jadvalga QULF OLINMAYDI. O'lchandi (`pg_locks`): `_tenancy_state`
        faqat `information_schema` va `pg_catalog` ni o'qiydi, ya'ni
        `customer_groups`/`brands` ustida BIRORTA qulf paydo bo'lmaydi.

    Nega muhim: ilgari holat ACCESS EXCLUSIVE qulf OLINGANDAN KEYIN o'qilardi,
    ya'ni ish bor-yo'qligini bilishdan oldin. Sxema allaqachon to'g'ri bo'lganda
    ham (deyarli har boot) butun jadval bo'yicha SELECT, yozuv va `pg_dump`
    bloklanardi; teskari tomondan esa 5 soniyadan uzun ISTALGAN o'quvchi boot'ni
    yiqitardi — o'lchangan: ochiq bitta `SELECT` yetarli edi."""
    out = {}
    with engine.connect() as con:
        for spec in _tenancy_specs():
            out[spec["table"]] = _tenancy_state(con, spec)
    return out


def _tenancy_specs():
    """Bazada MAVJUD bo'lgan (ota + bola) juftliklar."""
    tables = set(inspect(engine).get_table_names())
    return [sp for sp in _TENANCY_TABLES
            if sp["table"] in tables and sp["child"] in tables]


def _partial_error(tbl, ev):
    return UnsafeSchemaError(
        f"`{tbl}`: sxema YARIM MIGRATSIYA holatida — ishga tushish TO'XTATILDI.\n"
        f"  dalillar: {ev}\n"
        "  Yarim holat jimgina o'tkazilmaydi: ba'zi cheklovlar bor, ba'zilari "
        "yo'q, ya'ni cross-tenant himoyasi QISMAN. Sxemani qo'lda to'g'rilang.")


def _ensure_tenant_scoped_catalogs():
    """`customer_groups` va `brands` ni do'konga bog'laydi — IDEMPOTENT va FAIL-CLOSED.

    IKKI YO'L:

    A) TEZ YO'L (deyarli har boot). Qulfsiz prechek hammasi MIGRATED deb topsa —
       DARHOL qaytiladi. BIRORTA oshkora qulf olinmaydi, ya'ni normal deploy
       jonli `SELECT`/`INSERT`/`pg_dump` ni BLOKLAMAYDI va aksincha, jonli
       o'quvchi boot'ni yiqitmaydi.

    B) QULFLI YO'L (faqat LEGACY yoki NEEDS_REPAIR topilganda). Bitta
       tranzaksiyada qat'iy tartibda qulflar olinadi, holat QULF ICHIDA QAYTA
       o'qiladi (TOCTOU), so'ng ko'chirish/tuzatish bajariladi va natija
       tasdiqlanadi.

    ⚠️  QATOR BO'LSA (LEGACY) MIGRATSIYA QILINMAYDI VA ISHGA TUSHISH TO'XTAYDI.
    `company_id NOT NULL` to'ldirish uchun mavjud qatorlarning EGASINI bilish
    kerak; uni taxmin qilib bo'lmaydi.

    MUHIM FARQ: MIGRATSIYA QILINGAN jadvalda qator bo'lishi — MUTLAQO NORMAL.

    ATOMIKLIK: IKKALA jadval BITTA tranzaksiyada ko'chiriladi."""
    if engine.dialect.name != "postgresql":
        return                      # SQLite (dev/e2e): create_all yangi sxemani beradi
    if not _tenancy_specs():
        return

    for attempt in range(1, _LOCK_RETRIES + 1):
        # ── A) QULFSIZ PRECHEK ────────────────────────────────────────────
        states = _precheck_states()

        for tbl, (st, ev) in sorted(states.items()):
            if st == _ST_PARTIAL:
                # PARTIAL ni qulfsiz FATAL qilish TO'G'RI: PostgreSQL'da DDL
                # tranzaksion, boshqa instansiyaning TUGALLANMAGAN migratsiyasi
                # bizga KO'RINMAYDI. Ya'ni PARTIAL o'qishi hech qachon vaqtinchalik
                # artefakt emas — u haqiqiy chala sxema.
                raise _partial_error(tbl, ev)

        todo = [sp for sp in _tenancy_specs()
                if states[sp["table"]][0] != _ST_MIGRATED]
        if not todo:
            return                  # ── TEZ YO'L: hech qanday qulf olinmadi ──

        # ── B) QULFLI YO'L ────────────────────────────────────────────────
        try:
            _locked_migrate(todo)
            return
        except _LockBusy as e:
            if attempt == _LOCK_RETRIES:
                raise UnsafeSchemaError(
                    f"`{e.table}`: jadval {_LOCK_RETRIES} urinishda ham qulflanmadi "
                    f"({e.reason}). Boshqa seans uni ushlab turibdi va sxema hamon "
                    "migratsiya kutmoqda — ishga tushish TO'XTATILDI.\n"
                    "  Uzoq tranzaksiya yoki backup tugashini kuting, so'ng qayta "
                    "urining.") from e
            print(f"[migrate] qulf band ({e.table}) — {attempt}/{_LOCK_RETRIES}, "
                  "holat qayta tekshiriladi")
            time.sleep(_LOCK_RETRY_SLEEP)
            # keyingi aylanish qulfsiz prechekni QAYTA yurgizadi: boshqa instansiya
            # ishni bajargan bo'lsa, holat MIGRATED bo'ladi va biz muvaffaqiyat bilan
            # qaytamiz.


class _LockBusy(RuntimeError):
    """Qulf band — bu ICHKI signal, yakuniy xato EMAS (qayta urinish mumkin)."""

    def __init__(self, table, reason):
        super().__init__(f"{table}: {reason}")
        self.table, self.reason = table, reason


def _locked_migrate(todo):
    """Qulflarni oladi, holatni QULF ICHIDA qayta o'qiydi va ish bajaradi."""
    with engine.begin() as con:
        # Qulf MUDDATLI: boot migratsiyasi HECH QACHON cheksiz kutmasligi kerak.
        con.execute(text("SET LOCAL lock_timeout = '5s'"))

        # Qat'iy GLOBAL tartibda, har jadvalga AMALDA kerak bo'lgan darajada.
        want = {sp["table"] for sp in todo} | {sp["child"] for sp in todo} | {"companies"}
        for tbl in _LOCK_ORDER:
            if tbl not in want:
                continue
            try:
                con.execute(text(f'LOCK TABLE "{tbl}" IN {_LOCK_LEVEL[tbl]} MODE'))
            except Exception as e:      # noqa: BLE001
                raise _LockBusy(tbl, str(e).splitlines()[0]) from e

        # ── TOCTOU: holat QULF ICHIDA QAYTA o'qiladi ──────────────────────
        # Prechek qulfsiz edi, ya'ni u o'qigan holat eskirgan bo'lishi mumkin.
        # Qulf olingandan keyingi o'qish esa BARQAROR: endi hech kim jadvalni
        # o'zgartira olmaydi.
        plan, repairs = [], []
        for spec in todo:
            tbl = spec["table"]
            state, ev = _tenancy_state(con, spec)
            if state == _ST_MIGRATED:
                # Boshqa instansiya biz kutayotganda bajargan — bu NORMAL.
                continue
            if state == _ST_NEEDS_REPAIR:
                # Tenancy himoyasi TO'LIQ; faqat model bilan moslik tuzatiladi.
                # Qator sanog'i TEKSHIRILMAYDI — `DROP DEFAULT` qatorlarga tegmaydi.
                repairs.append(spec)
                continue
            if state == _ST_PARTIAL:
                raise _partial_error(tbl, ev)

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

        if not plan and not repairs:
            return                  # qulf ichida MIGRATED chiqdi — ish yo'q

        # ── ISH: tuzatish + ko'chirish (hammasi shu tranzaksiyada) ────────
        for spec in repairs:
            _repair_one(con, spec)
        for spec in plan:
            _migrate_one(con, spec)

        # ── TASDIQ: yarim holat COMMIT bo'lmasin ──────────────────────────
        for spec in repairs:
            after, ev2 = _tenancy_state(con, spec)
            if after != _ST_MIGRATED:
                raise UnsafeSchemaError(
                    f"`{spec['table']}`: tuzatishdan keyin holat MIGRATED emas "
                    f"({after}) — rollback qilinadi. dalillar: {ev2}")
            print(f"[migrate] {spec['table']}: row_version dagi ortiqcha server "
                  "default olib tashlandi (qatorlarga tegilmadi)")
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
    _ensure_lot_checks()               # track_expiry => track_lots (Postgres)
    _ensure_catalog()          # bazaviy ruxsat/rol/birlik (prod seedsiz ham) — ega'dan OLDIN
    _ensure_roles_and_owner()
    _deploy_cash()             # Cash quyi tizimi (faqat Postgres) — legacy jadvallar YONIGA
    _verify_required_schema()  # OXIRGI darvoza — yetishsa ISHGA TUSHISH YIQILADI
    print("[OK] Jadvallar yaratildi")


def _ensure_lot_checks():
    """`track_expiry => track_lots` — SXEMA darajasidagi qoida.

    Ilova qatlamidagi tekshiruv yetarli emas: bayroqlarni to'g'ridan-to'g'ri SQL
    bilan o'zgartirgan operator muddat kuzatuvini partiyasiz yoqib qo'yishi
    mumkin — u holda muddat qaysi partiyaga tegishli ekani ANIQLANMAYDI.

    SQLite `ALTER TABLE ... ADD CONSTRAINT` ni QO'LLAB-QUVVATLAMAYDI, shu bois
    bu faqat Postgres'da qo'llanadi; SQLite'da ayni qoidani ilova qatlami va
    sinovlar ushlaydi.
    """
    if engine.dialect.name != "postgresql":
        print("[migrate] ck_track_expiry_implies_lots — SQLite'da o'tkazib yuborildi")
        return
    try:
        with engine.begin() as con:
            con.execute(text(
                "ALTER TABLE products ADD CONSTRAINT ck_track_expiry_implies_lots "
                "CHECK (NOT track_expiry OR track_lots)"))
        print("[migrate] ck_track_expiry_implies_lots qo'shildi")
    except Exception as e:      # noqa: BLE001 — allaqachon bor bo'lsa normal
        msg = str(e).lower()
        if "already exists" not in msg and "duplicate" not in msg:
            print(f"[migrate] ck_track_expiry_implies_lots — o'tkazib yuborildi ({e})")


def _verify_required_schema():
    """MAJBURIY V2 obyektlari HAQIQATAN bormi — migratsiyadan KEYIN tekshiriladi.

    Har bir qadam alohida ham himoyalangan, lekin bu ikkinchi qatlam ATAYLAB bor:
    `CREATE INDEX IF NOT EXISTS` xato BERMASDAN hech narsa qilmasligi mumkin
    (masalan indeks boshqa ta'rif bilan allaqachon mavjud bo'lsa), ya'ni qadam
    "muvaffaqiyatli" ko'rinib, obyekt baribir kutilganday bo'lmasligi mumkin.
    Yagona ishonchli savol — «obyekt bazada bormi?».
    """
    from app.core import required_schema as rs
    ok, missing = rs.ok(engine)
    if ok:
        print(f"[schema] majburiy V2 obyektlari joyida "
              f"({len(rs.REQUIRED_COLUMNS)} ustun + {len(rs.REQUIRED_INDEXES)} indeks)")
        return
    for m in missing:
        print(f"[FATAL] majburiy sxema yetishmayapti — {m}")
    if rs.enforced(engine):
        raise RuntimeError(
            "Majburiy 1C Cutover V2 sxemasi to'liq emas: " + "; ".join(missing) +
            ". Ishga tushish TO'XTATILDI — bu sxemasiz import idempotentligi "
            "(parallel commit, qoldiq rekonsiliatsiyasi, tashqi identifikatsiya) "
            "DB darajasida kafolatlanmaydi.")
    print("[schema] (SQLite/mahalliy — yetishmovchilik ishni to'xtatmaydi)")


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
