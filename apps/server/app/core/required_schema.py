"""MAJBURIY sxema obyektlari — MIGRATSIYA va TAYYORLIK uchun YAGONA manba.

NEGA BU FAYL BOR: `initdb` har bir `ALTER TABLE` / `CREATE INDEX` ni `try/except`
ichida bajaradi va xatoni CHOP ETIB davom etadi. Bu eski, ixtiyoriy migratsiyalar
uchun ataylab shunday: bitta eskirgan ustun butun ishga tushishni to'xtatmasin.

LEKIN 1C Cutover V2 obyektlari ixtiyoriy EMAS. Ular bo'lmasa:
  · `ux_import_jobs_snapshot` yo'q  -> parallel commit DB darajasida to'sib qolinmaydi,
    ya'ni import idempotentligi faqat SELECT-tekshiruvga qoladi (TOCTOU poygasi);
  · `ux_movements_cutover_key` yo'q -> qoldiq rekonsiliatsiyasi IKKI MARTA qo'llanishi
    mumkin (aynan shu indeks buni imkonsiz qiladi);
  · `ux_products_external_identity` yo'q -> bitta 1C GUID ikkita mahsulotga tegishli
    bo'lib qolishi mumkin;
  · `products.source_system` / `external_id` yo'q -> identifikatsiya kaskadi eng
    kuchsiz bosqichlarga (nom/barkod) tushib qoladi.

Ya'ni yiqilgan migratsiya "biroz kamroq imkoniyat" emas, "jimgina buzilgan
idempotentlik" degani. Shu bois bu ro'yxat IKKI joyda ishlatiladi:
  1) `initdb` — Postgres'da (production/staging) yetishmasa ISHGA TUSHISH YIQILADI;
  2) `/health/ready` — yetishmasa `ready=false` (ikkinchi qatlam: kimdir uvicorn'ni
     to'g'ridan-to'g'ri ko'tarsa ham, yaroqsiz sxema "tayyor" deb ko'rinmaydi).
"""
from __future__ import annotations

from sqlalchemy import inspect

# (jadval, ustun) — `initdb._ADDED_COLUMNS` bilan IZCHIL bo'lishi shart.
REQUIRED_COLUMNS: list[tuple[str, str]] = [
    ("products", "source_system"),
    ("products", "external_id"),
    ("import_jobs", "snapshot_id"),
    ("import_jobs", "content_sha256"),
    ("import_jobs", "mode"),
    ("import_jobs", "error"),
    ("import_jobs", "applied_rows"),
    # ── PARTIYA POYDEVORI (Phase 0) — ish vaqti ALLAQACHON o'qiydi ───────────
    #  `stock_gate.assert_untracked()` har inventarizatsiya va har 1C qoldiq
    #  moslashtiruvida `products.track_lots` ni SO'RAYDI; `stock_invariant` ham.
    #  Ya'ni bular kelajak uchun emas — bugungi ish vaqti bog'liqligi.
    #
    #  ⚠️  AYNAN SHU narsa staging'da yiqilgan edi: Postgres ikkala ustunni ham
    #      YARATMADI (`BOOLEAN DEFAULT 0` tip xatosi), lekin tayyorlik YASHIL
    #      qoldi — chunki ular bu ro'yxatда yo'q edi. Qoida: ish vaqti tayangan
    #      obyekt AYNI relizда tayyorlikda ham majburiy bo'ladi.
    ("products", "track_lots"),
    ("products", "track_expiry"),
    #  `ReturnItem.sale_item_id` ni JONLI qaytarish kodi YOZADI (api/v1/sales.py).
    #  Ustun bo'lmasa har chek asosidagi qaytarish yiqilardi.
    ("return_items", "sale_item_id"),
    # ── PARTIYA QABULI (Phase 1) — `lot_receiving.create_lots()` HAR BIRIGA yozadi ──
    #  Bu ro'yxat "kelajak uchun" emas: `create_lots()` INSERT'i shu 12 ustunni
    #  nomma-nom beradi, ya'ni bittasi yo'q bo'lsa HAR qabul yiqiladi. Postgres'da
    #  ustun `ALTER TABLE` bilan qo'shiladi (`create_all` MAVJUD jadvalga ustun
    #  QO'SHMAYDI) — demak migratsiya jimgina yiqilsa, buni FAQAT shu ro'yxat tutadi.
    ("stock_batches", "company_id"),
    ("stock_batches", "received_qty"),
    ("stock_batches", "remaining_qty"),
    ("stock_batches", "status"),
    ("stock_batches", "source_type"),
    ("stock_batches", "purchase_item_id"),
    ("stock_batches", "receiving_id"),
    ("stock_batches", "external_lot_id"),
    ("stock_batches", "supplier_id"),
    ("stock_batches", "client_uuid"),
    ("stock_batches", "updated_at"),
    ("stock_batches", "row_version"),
    # ── PHASE 2 — SOTUV ish vaqti ENDI shularga tayanadi ────────────────────
    #  `lot_fefo.apply()` HAR kuzatuvli sotuvda `sale_item_lot_allocations` ga
    #  yozadi, `lots.py` esa `products.lots_activated_at` ni yozadi. Bittasi
    #  yo'q bo'lsa kuzatuvli mahsulotning HAR sotuvi yiqilardi.
    #
    #  ⚠️  Phase 1 da bu jadval ATAYLAB ro'yxatdan CHIQARILGAN edi: o'shanda uni
    #      faqat `create_all` yaratardi va yetishmovchilikni TUZATADIGAN qadam
    #      yo'q edi — majburiy qilish abadiy boot-loop berardi. ENDI tuzatish
    #      qadami BOR (`_ADDED_COLUMNS` da ustunlar, `_index` da noyob indeks),
    #      shuning uchun majburiy qilish XAVFSIZ. Qoida o'zgarmadi: majburiy
    #      obyekt migratsiya tuzata oladigan bo'lishi SHART.
    ("products", "lots_activated_at"),
    ("sale_item_lot_allocations", "company_id"),
    ("sale_item_lot_allocations", "sale_item_id"),
    ("sale_item_lot_allocations", "stock_batch_id"),
    ("sale_item_lot_allocations", "product_id"),
    ("sale_item_lot_allocations", "qty"),
    ("sale_item_lot_allocations", "unit_cost"),
    ("sale_item_lot_allocations", "expiry_date"),
    # ── PHASE 2.5 — sotuv ish vaqti ENDI shularga tayanadi ──────────────────
    #  `sale_items.cost_total` HAR sotuvda yoziladi (aniq COGS), `doc_counters`
    #  esa HAR chek raqamini beradi — usiz sotuv UMUMAN yakunlanmaydi.
    ("sale_items", "cost_total"),
    ("sale_items", "cost_unresolved"),
    ("doc_counters", "company_id"),
    ("doc_counters", "kind"),
    ("doc_counters", "next_value"),
    #  `lot_shortfalls` — invariant HAR tekshiruvda o'qiydi, sotuv esa offline
    #  qayta yuborishda YOZADI. Bittasi yo'q bo'lsa invariant noto'g'ri javob
    #  berardi (qarz ko'rinmay, qoldiq oshiq ko'rinardi).
    ("lot_shortfalls", "company_id"),
    ("lot_shortfalls", "branch_id"),
    ("lot_shortfalls", "product_id"),
    ("lot_shortfalls", "sale_item_id"),
    ("lot_shortfalls", "qty"),
    ("lot_shortfalls", "resolved_qty"),
]

# ⚠️  `sale_item_lot_allocations` ATAYLAB YO'Q. Vasvasa bor edi: `catalog_reset`
#     undan o'chiradi, demak "majburiy" ko'rinadi. Lekin bu ro'yxatning vazifasi
#     torroq — MIGRATSIYA ta'minlashi kerak bo'lgan obyektlar. Butun jadvalni
#     `Base.metadata.create_all()` yaratadi, `_ADDED_COLUMNS` emas; ya'ni u
#     yetishmasa migratsiyada TUZATADIGAN qadam YO'Q va tayyorlik abadiy qizil
#     qolardi (boot-loop). Boshqa birorta jadval ham bu ro'yxatda yo'q — istisno
#     qilish izchillikni buzardi. Buni `test_majburiy_sxema_royxati_initdb_bilan_
#     IZCHIL` tutdi: har majburiy ustun `_ADDED_COLUMNS` da bo'lishi SHART.

# Faqat POSTGRES'da tekshiriladigan cheklovlar. SQLite `ALTER TABLE ADD
# CONSTRAINT` ni qo'llab-quvvatlamaydi, shu bois u yerda bu ro'yxat BO'SH deb
# qaraladi — aks holda mahalliy tayyorlik DOIM qizil bo'lardi.
REQUIRED_PG_CONSTRAINTS: list[tuple[str, str]] = [
    # `track_expiry => track_lots` — ilova qatlamida majburlovchi kod YO'Q
    # (Phase 0 da bayroqlarni o'rnatadigan API ham yo'q), ya'ni bu CHECK
    # YAGONA himoya. Usiz muddat kuzatuvi partiyasiz yoqilishi mumkin bo'lardi
    # va muddat qaysi partiyaga tegishli ekani ANIQLANMAY qolardi.
    ("ck_track_expiry_implies_lots", "products"),
]

# (indeks, jadval) — `initdb._ensure_indexes` bilan IZCHIL bo'lishi shart.
REQUIRED_INDEXES: list[tuple[str, str]] = [
    ("ux_products_external_identity", "products"),
    ("ux_import_jobs_snapshot", "import_jobs"),
    ("ux_movements_cutover_key", "stock_movements"),
    # ── QABUL IDEMPOTENTLIGI (Phase 1) ──────────────────────────────────────
    #  `create_lots()` avval `client_uuid` bo'yicha SELECT qiladi, so'ng INSERT —
    #  bu klassik TOCTOU. Ikki bir vaqtdagi qayta-yuborish oynaga tushsa, DB
    #  darajasidagi YAGONA to'siq shu indeks: usiz AYNI qabul IKKI partiya
    #  tug'dirib qoldiqni ikki marta oshirardi.
    ("ux_lot_intake_key", "stock_batches"),
    # ── PHASE 2 ─────────────────────────────────────────────────────────────
    #  Bitta sotuv qatori bitta partiyadan ATIGI BIR MARTA yeyishi mumkin.
    #  Modeldagi `UniqueConstraint` ni faqat `create_all` chiqaradi — MAVJUD
    #  jadvalda u paydo bo'lmaydi. Noyob INDEKS esa migratsiya bilan qo'shiladi,
    #  ya'ni takroriy ulushga qarshi DB to'sig'i har ikki yo'lda ham mavjud.
    ("ux_alloc_item_lot", "sale_item_lot_allocations"),
    #  Taqsimlagich `ON CONFLICT (company_id, kind)` ga tayanadi — indekssiz
    #  ikki parallel sotuv bir xil chek raqamini berib yuborardi.
    ("ux_doc_counter", "doc_counters"),
]

# ⚠️  ATAYLAB KIRITILMAGAN: `ix_lot_fefo`, `ix_lot_expiry`, `ix_alloc_lot`.
#     Ular FAQAT tezlik uchun — yo'qligida so'rov sekinlashadi, lekin javob
#     TO'G'RI qoladi. Ularni majburiy qilish ishlab chiqarishni TEZLIK sababli
#     abadiy boot-loop'ga tushirardi. Majburiy ro'yxat faqat TO'G'RILIK
#     bog'liqliklaridan iborat bo'lishi shart.


def enforced(bind) -> bool:
    """Yetishmovchilik ISHGA TUSHISHNI to'xtatadigan muhitmi.

    Postgres = production/staging. SQLite dev/test/e2e uchun ataylab yumshoq:
    u yerda ham obyektlar yaratiladi, lekin yo'qligi ishni to'xtatmaydi.
    """
    try:
        return bind.dialect.name == "postgresql"
    except Exception:      # noqa: BLE001
        return False


def missing(bind) -> list[str]:
    """Yetishmayotgan MAJBURIY obyektlar ro'yxati (aniq nomlar bilan).

    HECH NARSA O'ZGARTIRMAYDI — faqat introspeksiya. `/health/ready` ham shuni
    chaqiradi, shuning uchun bu yerda yozuv bo'lishi MUMKIN EMAS.

    ⚠️  QAYTARILADIGAN SATRLAR OMMAVIY. Ular `/health/ready` javobiga tushadi, u
        esa AVTORIZATSIYASIZ endpoint. Shu bois bu yerdan CHIQADIGAN matn faqat
        SHU FAYLDAGI o'zgarmas nomlardan iborat bo'lishi shart. Istisno matni
        (`str(e)`) HECH QACHON qo'shilmaydi: SQLAlchemy/psycopg xatolari ichida
        host, IP, port, baza foydalanuvchisi va to'liq reflection SQL bo'ladi —
        ya'ni ulanish tafsilotlari ochiq internetga chiqib ketardi. Sabab
        JURNALGA (stdout -> Railway loglari) yoziladi, javobga EMAS.
    """
    insp = inspect(bind)
    out: list[str] = []
    try:
        tables = set(insp.get_table_names())
    except Exception as e:      # noqa: BLE001
        print(f"[schema] introspeksiya yiqildi: {e}")
        return ["introspeksiya yiqildi"]

    for table, col in REQUIRED_COLUMNS:
        if table not in tables:
            out.append(f"jadval yo'q: {table}")
            continue
        try:
            cols = {c["name"] for c in insp.get_columns(table)}
        except Exception as e:      # noqa: BLE001
            print(f"[schema] {table}: ustunlarni o'qib bo'lmadi: {e}")
            out.append(f"ustunlarni o'qib bo'lmadi: {table}")
            continue
        if col not in cols:
            out.append(f"ustun yo'q: {table}.{col}")

    for index, table in REQUIRED_INDEXES:
        if table not in tables:
            out.append(f"jadval yo'q: {table} ({index} uchun)")
            continue
        try:
            names = {i["name"] for i in insp.get_indexes(table)}
        except Exception as e:      # noqa: BLE001
            print(f"[schema] {table}: indekslarni o'qib bo'lmadi: {e}")
            out.append(f"indekslarni o'qib bo'lmadi: {table}")
            continue
        if index not in names:
            out.append(f"indeks yo'q: {index}")

    # ── Postgres cheklovlari ────────────────────────────────────────────────
    try:
        is_pg = bind.dialect.name == "postgresql"
    except Exception:      # noqa: BLE001
        is_pg = False
    if is_pg and REQUIRED_PG_CONSTRAINTS:
        try:
            from sqlalchemy import text as _t
            with bind.connect() as con:
                have = {r[0] for r in con.execute(_t(
                    "SELECT conname FROM pg_constraint WHERE conname = ANY(:n)"
                ), {"n": [c for c, _ in REQUIRED_PG_CONSTRAINTS]}).fetchall()}
        except Exception as e:      # noqa: BLE001
            print(f"[schema] cheklovlarni o'qib bo'lmadi: {e}")
            out.append("cheklovlarni o'qib bo'lmadi")
            return out
        for name, table in REQUIRED_PG_CONSTRAINTS:
            if name not in have:
                out.append(f"cheklov yo'q: {name} ({table})")
    return out


def ok(bind) -> tuple[bool, list[str]]:
    """(hammasi_joyidami, yetishmayotganlar). Tekshiruv HAR DOIM bajariladi —
    dialektdan qat'i nazar; `enforced()` faqat YIQILISH qaroriga ta'sir qiladi."""
    m = missing(bind)
    return (not m), m
