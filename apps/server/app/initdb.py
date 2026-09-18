"""Dev/prod uchun jadvallarni yaratish (Alembic o'rniga tez yo'l) + yengil avto-migratsiya."""
import os
import re
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
    # ── PHASE 2 ─────────────────────────────────────────────────────────────
    ("products", "lots_activated_at", "TIMESTAMPTZ"),
    #  `sale_item_lot_allocations` — SOTUV ish vaqti ENDI shunga tayanadi.
    #  ⚠️  Jadvalning O'ZINI `create_all` yaratadi; bu ro'yxat esa MAVJUD, lekin
    #      TO'LIQSIZ jadvalni TUZATADI (`create_all` mavjud jadvalga ustun
    #      QO'SHMAYDI). Ikkalasi birgalikda haqiqiy migratsiya yo'lini beradi:
    #      jadval yo'q -> create_all; ustun yo'q -> shu ALTER; ikkalasi ham
    #      bo'lmasa -> `_verify_required_schema` ishga tushishni TO'XTATADI.
    ("sale_item_lot_allocations", "company_id", "UUID"),
    ("sale_item_lot_allocations", "sale_item_id", "UUID"),
    ("sale_item_lot_allocations", "stock_batch_id", "UUID"),
    ("sale_item_lot_allocations", "product_id", "UUID"),
    ("sale_item_lot_allocations", "qty", "NUMERIC(14,3) DEFAULT 0"),
    ("sale_item_lot_allocations", "unit_cost", "NUMERIC(14,2) DEFAULT 0"),
    ("sale_item_lot_allocations", "expiry_date", "DATE"),
    # ── PHASE 2.5 ───────────────────────────────────────────────────────────
    #  ANIQ qator COGS'i — sotuv ish vaqti yozadi, hisobotlar o'qiydi.
    ("sale_items", "cost_total", "NUMERIC(14,2)"),
    ("sale_items", "cost_unresolved", "NUMERIC(14,2)"),
    #  ANIQ QAYTARILGAN COGS — qaytarish bir nechта partiyaga bo'linsa
    #  `qty * unit_cost` (o'rtacha) tiyinni yo'qotardi; hisobotlar shu bois
    #  `coalesce(cost_total, qty*unit_cost)` o'qiydi.
    ("return_items", "cost_total", "NUMERIC(14,2)"),
    # ── PHASE 3 ─────────────────────────────────────────────────────────────
    #  Ombor harakatining partiya tafsiloti. Jadvalning O'ZINI `create_all`
    #  yaratadi; bu qatorlar MAVJUD, lekin to'liqsiz jadvalni tuzatadi.
    ("stock_movement_lot_allocations", "company_id", "UUID"),
    ("stock_movement_lot_allocations", "stock_movement_id", "UUID"),
    ("stock_movement_lot_allocations", "stock_batch_id", "UUID"),
    ("stock_movement_lot_allocations", "product_id", "UUID"),
    ("stock_movement_lot_allocations", "qty", "NUMERIC(14,3) DEFAULT 0"),
    ("stock_movement_lot_allocations", "unit_cost", "NUMERIC(14,2) DEFAULT 0"),
    ("stock_movement_lot_allocations", "expiry_date", "DATE"),
    #  Qaytarish qatorining partiya taqsimoti — kumulyativ himoya SHU jadvalni
    #  o'qiydi; usiz uchinchi qaytarish partiyaga sotilganidan ko'p qaytarardi.
    ("return_item_lot_allocations", "company_id", "UUID"),
    ("return_item_lot_allocations", "return_item_id", "UUID"),
    ("return_item_lot_allocations", "sale_item_id", "UUID"),
    ("return_item_lot_allocations", "stock_batch_id", "UUID"),
    ("return_item_lot_allocations", "product_id", "UUID"),
    ("return_item_lot_allocations", "qty", "NUMERIC(14,3) DEFAULT 0"),
    ("return_item_lot_allocations", "unit_cost", "NUMERIC(14,2) DEFAULT 0"),
    #  Qaytarishning TAXMINIY ulushi (sotuvdagi `cost_unresolved` ning aynasi).
    ("return_items", "cost_unresolved", "NUMERIC(14,2)"),
    #  Qarz yopilganda topilgan HAQIQIY tannarx yig'indisi (COGS og'ishi uchun).
    ("lot_shortfalls", "resolved_cost", "NUMERIC(14,2) DEFAULT 0"),
    ("lot_shortfalls", "returned_qty", "NUMERIC(14,3) DEFAULT 0"),
    # ── PHASE 3.5 ───────────────────────────────────────────────────────────
    #  Tannarx ASOSI: 'estimated' yoki NULL. Hisobot ANIQ va TAXMINIY COGS'ni
    #  ajratishi uchun shart (`/reports/history/seed` taxmini).
    ("sales", "cost_basis", "VARCHAR"),
    #  Hujjat raqami hisoblagichi. Jadvalning O'ZINI `create_all` yaratadi;
    #  bu qatorlar MAVJUD, lekin to'liqsiz jadvalni tuzatadi.
    ("doc_counters", "company_id", "UUID"),
    ("doc_counters", "kind", "VARCHAR"),
    ("doc_counters", "next_value", "INTEGER DEFAULT 1"),
    #  Taqsimlanmagan qarz (`lot_shortfalls`) — sotuv ish vaqti yozadi va
    #  invariant o'qiydi. Jadvalni `create_all` yaratadi; bu qatorlar MAVJUD,
    #  lekin to'liqsiz jadvalni tuzatadi.
    ("lot_shortfalls", "company_id", "UUID"),
    ("lot_shortfalls", "branch_id", "UUID"),
    ("lot_shortfalls", "product_id", "UUID"),
    ("lot_shortfalls", "sale_item_id", "UUID"),
    ("lot_shortfalls", "qty", "NUMERIC(14,3) DEFAULT 0"),
    ("lot_shortfalls", "resolved_qty", "NUMERIC(14,3) DEFAULT 0"),
    ("lot_shortfalls", "unit_cost", "NUMERIC(14,2) DEFAULT 0"),
    ("lot_shortfalls", "reason", "VARCHAR"),
    ("lot_shortfalls", "created_at", "TIMESTAMPTZ"),
    ("lot_shortfalls", "resolved_at", "TIMESTAMPTZ"),
    # ── PHASE 4A ────────────────────────────────────────────────────────────
    #  Basis tasnifi MIQDORGA qaraydi — nol so'mlik taxmin «aniq» bo'lib qolmasin.
    ("sale_items", "provisional_qty", "NUMERIC(14,3)"),
    #  Yopish / qaytarish HODISA jadvallari. Jadvallarning O'ZINI `create_all`
    #  yaratadi; bu qatorlar MAVJUD, lekin to'liqsiz jadvalni tuzatadi (Phase 3
    #  bilan bir xil ikki yo'l).
    ("lot_shortfall_resolution_requests", "company_id", "UUID"),
    ("lot_shortfall_resolution_requests", "client_uuid", "UUID"),
    ("lot_shortfall_resolution_requests", "shortfall_id", "UUID"),
    ("lot_shortfall_resolution_requests", "request_hash", "VARCHAR(64)"),
    ("lot_shortfall_resolution_requests", "response_json", "TEXT"),
    ("lot_shortfall_resolution_requests", "employee_id", "UUID"),
    ("lot_shortfall_resolution_requests", "created_at", "TIMESTAMPTZ"),
    ("lot_shortfall_resolutions", "request_id", "UUID"),
    ("lot_shortfall_resolutions", "line_no", "INTEGER"),
    ("lot_shortfall_resolutions", "kind", "VARCHAR"),
    ("lot_shortfall_resolutions", "company_id", "UUID"),
    ("lot_shortfall_resolutions", "branch_id", "UUID"),
    ("lot_shortfall_resolutions", "product_id", "UUID"),
    ("lot_shortfall_resolutions", "shortfall_id", "UUID"),
    ("lot_shortfall_resolutions", "sale_item_id", "UUID"),
    ("lot_shortfall_resolutions", "stock_batch_id", "UUID"),
    ("lot_shortfall_resolutions", "expiry_date", "DATE"),
    ("lot_shortfall_resolutions", "qty", "NUMERIC(14,3)"),
    ("lot_shortfall_resolutions", "provisional_unit_cost", "NUMERIC(14,2)"),
    ("lot_shortfall_resolutions", "actual_unit_cost", "NUMERIC(14,2)"),
    ("lot_shortfall_resolutions", "provisional_cost", "NUMERIC(14,2)"),
    ("lot_shortfall_resolutions", "actual_cost", "NUMERIC(14,2)"),
    ("lot_shortfall_resolutions", "variance", "NUMERIC(14,2)"),
    ("lot_shortfall_resolutions", "resolved_at", "TIMESTAMPTZ"),
    ("lot_shortfall_resolutions", "employee_id", "UUID"),
    ("lot_shortfall_resolutions", "created_at", "TIMESTAMPTZ"),
    ("return_item_shortfall_allocations", "company_id", "UUID"),
    ("return_item_shortfall_allocations", "return_id", "UUID"),
    ("return_item_shortfall_allocations", "return_item_id", "UUID"),
    ("return_item_shortfall_allocations", "shortfall_id", "UUID"),
    ("return_item_shortfall_allocations", "created_batch_id", "UUID"),
    ("return_item_shortfall_allocations", "product_id", "UUID"),
    ("return_item_shortfall_allocations", "branch_id", "UUID"),
    ("return_item_shortfall_allocations", "qty", "NUMERIC(14,3)"),
    ("return_item_shortfall_allocations", "provisional_unit_cost", "NUMERIC(14,2)"),
    ("return_item_shortfall_allocations", "provisional_cost_credit", "NUMERIC(14,2)"),
    ("return_item_shortfall_allocations", "created_at", "TIMESTAMPTZ"),
    ("return_item_resolution_allocations", "company_id", "UUID"),
    ("return_item_resolution_allocations", "return_id", "UUID"),
    ("return_item_resolution_allocations", "return_item_id", "UUID"),
    ("return_item_resolution_allocations", "resolution_id", "UUID"),
    ("return_item_resolution_allocations", "sale_item_id", "UUID"),
    ("return_item_resolution_allocations", "stock_batch_id", "UUID"),
    ("return_item_resolution_allocations", "product_id", "UUID"),
    ("return_item_resolution_allocations", "branch_id", "UUID"),
    ("return_item_resolution_allocations", "qty", "NUMERIC(14,3)"),
    ("return_item_resolution_allocations", "provisional_cost_credit", "NUMERIC(14,2)"),
    ("return_item_resolution_allocations", "variance_reversed", "NUMERIC(14,2)"),
    ("return_item_resolution_allocations", "created_at", "TIMESTAMPTZ"),
    ("purchase_items", "batch_no", "VARCHAR"),
    ("return_items", "sale_item_id", "UUID"),

    ("stock_movements", "ref_type", "VARCHAR"),
    ("import_jobs", "snapshot_id", "VARCHAR"),
    ("import_jobs", "content_sha256", "VARCHAR"),
    ("import_jobs", "mode", "VARCHAR"),
    ("import_jobs", "error", "TEXT"),
    ("import_jobs", "applied_rows", "INTEGER DEFAULT 0"),
    ("import_jobs", "hash_contract_version", "INTEGER"),
    ("companies", "code", "VARCHAR"),
    ("inventory", "low_alerted", "BOOLEAN"),
    ("employees", "sec_epoch", "INTEGER DEFAULT 0"),
    # ⚠️  Bu uchtasi ilgari "VARCHAR" edi, model esa UUID (Phase 5B.1): varchar ustunda ORM
    #     `= ...::UUID` taqqoslashi 42883 bilan yiqiladi. Tur endi model bilan AYNI — ya'ni
    #     ustun YO'Q bo'lsa u DARHOL to'g'ri tipda qo'shiladi (bu konversiya EMAS).
    #     ⚠️  Allaqachon `varchar` qo'shilgan bazani boot TUZATMAYDI: mavjud ustunning tipini
    #         o'zgartirish jadvalni qayta yozadi (ACCESS EXCLUSIVE, har indeks qayta quriladi)
    #         va qiymatlar bo'yicha operator qarorini talab qiladi. Tayyorlik uni QIZIL qiladi
    #         (`required_schema.column_type_problems`), tuzatish esa ANIQ migratsiya:
    #         `_UUID_MIGRATION_HINT` (pastda) — `python -m app.tools.schema_migrate`.
    ("cash_movements", "client_uuid", "UUID"),
    ("qr_payments", "sale_id", "UUID"),           # QA PAY-01: qr to'lov qaysi savdoga ishlatilgani (consume)
    ("qr_payments", "client_uuid", "UUID"),       # QA PAY-05: checkout-idempotent QR
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
    # QA PC-003: barkod KOMPANIYA doirasida. Ilgari `_migrate_barcodes_per_company` o'zi
    # qo'shardi — qulf chegarasiz, yiqilsa JIM (backfill va noyob indeks ham tushib qolardi),
    # holbuki `Product.barcodes` (selectin) orqali HAR mahsulot yuklanishi shu ustunni o'qiydi.
    # Endi umumiy yo'l: cheklangan urinish + MAJBURIY FATAL (Phase 5B.1).
    ("product_barcodes", "company_id", "UUID"),
]


# ⚠️  USTUN TIPI OG'ISHI (Phase 5C). Boot uni FAQAT ko'rsatadi: `column_type_problems` ->
#     `/health/ready` 503. Tuzatish — operator yurgizadigan ANIQ, versiyalangan migratsiya
#     (`app/db/migrations/`, CLI `app/tools/schema_migrate.py`). Satr O'ZGARMAS: baza nomi,
#     qiymat yoki xato matni chiqmaydi. Boot o'sha modulni IMPORT ham qilmaydi — bu yerda
#     faqat MATN; migratsiya identifikatori bilan izchilligi test bilan mixlangan.
_UUID_MIGRATION_HINT = ("[schema] ustun tipi og'ishi — tuzatish (boot EMAS, operator): "
                        "python -m app.tools.schema_migrate preflight "
                        "--migration 2026-09-17.uuid-client-columns-v1")


def _required_column(table: str, col: str) -> bool:
    """Bu ustun 1C Cutover V2 uchun MAJBURIYmi (va muhit uni talab qiladimi)."""
    from app.core import required_schema as rs
    return rs.enforced(engine) and (table, col) in rs.REQUIRED_COLUMNS


def _required_index(name: str) -> bool:
    from app.core import required_schema as rs
    return rs.enforced(engine) and name in {n for n, _ in rs.REQUIRED_INDEXES}


def _pg_relation_exists(name: str) -> bool:
    """`public.<name>` nomli relation (ISTALGAN turdagi) bormi — QULFSIZ.

    `to_regclass` faqat katalogda NOMNI qidiradi (NoLock) — jadvalga hech qanday qulf
    olinmaydi. Ayni usul `_ensure_lot_checks` da ham ishlatiladi."""
    with engine.connect() as con:
        return bool(con.execute(text("SELECT to_regclass(:q) IS NOT NULL"),
                                {"q": f"public.{name}"}).scalar())


# ── BOOT DDL QULFI BAND BO'LSA ──────────────────────────────────────────────
# Kutishning O'ZI sessiya `lock_timeout` i bilan chegaralangan (`_boot_pgoptions`).
# Bu yerda — NECHA MARTA urinish. Orada `_LOCK_RETRY_SLEEP` (tenancy bilan ayni
# pauza): har urinish jonli yozuvchilarni `lock_timeout` gacha navbatda ushlaydi,
# pauza esa ularga o'tib olish oynasini beradi. Faqat HAQIQIY migratsiyada ishlaydi —
# barqaror boot DDL yubormaydi, ya'ni kutadigan narsasi ham yo'q.
_DDL_LOCK_ATTEMPTS = 5
_LOCK_NOT_AVAILABLE = "55P03"


def _lock_retry(fn, what: str):
    """Qulf band (55P03) -> `_DDL_LOCK_ATTEMPTS` gacha urinadi; boshqa xato yoki oxirgi
    urinish -> yuqoriga (tasnif — chaqiruvchida: MAJBURIY FATAL, qolgani o'tkaziladi)."""
    for attempt in range(1, _DDL_LOCK_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if _sqlstate(e) != _LOCK_NOT_AVAILABLE or attempt == _DDL_LOCK_ATTEMPTS:
                raise
            print(f"[migrate] {what}: qulf band — {attempt}/{_DDL_LOCK_ATTEMPTS}, "
                  f"{_LOCK_RETRY_SLEEP:g}s dan keyin qayta uriniladi")
            time.sleep(_LOCK_RETRY_SLEEP)


def _lock_holders(tables) -> str:
    """Jadval(lar)dagi qulfni USHLAB turgan BOSHQA seanslar — FAQAT jurnal uchun.

    ⚠️  Faqat stdout'ga (Railway jurnali). `/health` javobiga HECH QACHON tushmaydi:
        pid, ilova nomi va tranzaksiya yoshi — ichki ma'lumot (`required_schema.missing`).
    ⚠️  Diagnostika yiqilsa asl xato YO'QOLMAYDI — faqat «o'qib bo'lmadi» yoziladi."""
    try:
        found = []
        with engine.connect() as con:
            lt = con.execute(text("SHOW lock_timeout")).scalar()
            for t in tables:
                for pid, mode, state, app, age in con.execute(text(
                        "SELECT a.pid, l.mode, a.state, a.application_name, "
                        "       EXTRACT(EPOCH FROM clock_timestamp() - a.xact_start)::int "
                        "FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                        "WHERE l.locktype = 'relation' AND l.granted "
                        "  AND l.database = (SELECT oid FROM pg_database "
                        "                    WHERE datname = current_database()) "
                        "  AND l.relation = to_regclass(:t) AND l.pid <> pg_backend_pid() "
                        "ORDER BY a.xact_start NULLS LAST, a.pid"), {"t": f"public.{t}"}):
                    found.append(f"{t}: pid={pid} {mode} ({state}, tranzaksiya "
                                 f"{'?' if age is None else age}s, ilova={app!r})")
    except Exception as e:  # noqa: BLE001
        return ("to'sayotgan seanslarni o'qib bo'lmadi: "
                f"{str(e).splitlines()[0] if str(e) else e!r}")
    who = "; ".join(found) if found else "hozir hech kim ushlamayapti (qulf bo'shagan)"
    return f"lock_timeout={lt}; to'sayotgan seanslar: {who}"


def _lock_reason(e, tables) -> str:
    """FATAL satrining sababi. Qulf band bo'lsa — urinishlar soni, chegara va KIM to'sgani;
    boshqa xatoda — xato matnining o'zi (avvalgidek)."""
    if _sqlstate(e) != _LOCK_NOT_AVAILABLE:
        return str(e)
    first = str(e).splitlines()[0] if str(e) else repr(e)
    return (f"{', '.join(tables) or '?'} qulfi {_DDL_LOCK_ATTEMPTS} urinishda ham olinmadi "
            f"({_lock_holders(tables)}) — {first}")


def _index(con_sql: str, name: str) -> None:
    """Indeks yaratadi. MAJBURIY bo'lsa — yiqilganda ishga tushish TO'XTAYDI.

    ⚠️  POSTGRES'DA AVVAL QULFSIZ PRECHEK. `CREATE INDEX IF NOT EXISTS` jadvalga SHARE
        qulfni nom tekshiruvidan OLDIN oladi: indeks BOR bo'lsa ham har boot jonli
        jadvaldagi har yozuv bilan to'qnashardi — ochiq bitta yozuvchi tranzaksiya
        boot'ni cheksiz ushlab, uning ortida esa YANGI sotuvlar navbatga tushardi.
    ⚠️  NOM bo'yicha, relation TURIGA qaramay. `IF NOT EXISTS` ham aynan shunday hukm
        qiladi (nom band — jadval bo'lsa ham o'tkazadi); bunday holatni yakuniy
        tekshiruv (`_verify_required_schema`) baribir ushlaydi. Qat'iyroq prechek
        (faqat indeks, faqat yaroqli) DDL'ni — ya'ni qulfni — qaytarib olib kelardi.
    ⚠️  Prechek HAR urinishda qayta: qulf kutilgan orada boshqa instansiya indeksni
        qurib bo'lgan bo'lsa, DDL umuman yuborilmaydi (tenancy naqshi).
    SQLite'da prechek yo'q — `IF NOT EXISTS` u yerda qulf muammosi emas."""
    pg = engine.dialect.name == "postgresql"

    def _attempt():
        if pg and _pg_relation_exists(name):
            return
        with engine.begin() as con:
            con.execute(text(con_sql))

    try:
        _lock_retry(_attempt, name)
    except Exception as e:  # noqa: BLE001
        if _required_index(name):
            on = re.search(r'\bON\s+(?:public\.)?"?(\w+)', con_sql, re.IGNORECASE)
            print(f"[FATAL] MAJBURIY indeks yaratilmadi: {name} — "
                  f"{_lock_reason(e, [on.group(1)] if on else [])}")
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
        # BOOLEAN standarti DIALEKTGA BOG'LIQ: SQLite `0/1` ni qabul qiladi,
        # Postgres esa `DEFAULT 0` ni BOOLEAN uchun rad etadi
        # («column is of type boolean but default expression is of type integer»).
        # Bu staging'da AYNAN shunday yiqilgan edi: ustunlar Postgres'da
        # yaratilmay qolgan, SQLite'da esa muammosiz o'tgan — ya'ni mahalliy
        # sinovlar buni KO'RA OLMAGAN.
        if sqltype.upper().startswith("BOOLEAN"):
            _type = ("BOOLEAN DEFAULT false" if dialect == "postgresql"
                     else "BOOLEAN DEFAULT 0")

        # ⚠️  `ADD COLUMN` ACCESS EXCLUSIVE oladi — jadvalni ochiq bitta `SELECT` ham
        #     ushlab turadi. Kutish sessiya `lock_timeout` i bilan chegaralangan;
        #     qulf band bo'lsa cheklangan qayta urinish, so'ng quyidagi tasnif.
        def _add(table=table, col=col, _type=_type):
            with engine.begin() as con:
                con.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {_type}'))
        try:
            _lock_retry(_add, f"{table}.{col}")
            print(f"[migrate] {table}.{col} qo'shildi")
        except Exception as e:  # noqa: BLE001
            # MAJBURIY ustun yiqilsa — JIM O'TMAYDI. Aks holda konteyner sog'lom
            # ko'tarilardi va V2 identifikatsiyasiz ishlardi (staging'da aynan shu
            # bo'lgan: «column source_system does not exist»).
            if _required_column(table, col):
                print(f"[FATAL] MAJBURIY ustun qo'shilmadi: {table}.{col} — "
                      f"{_lock_reason(e, [table])}")
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
        # Ustunni ENDI `_ensure_columns` qo'shadi (`_ADDED_COLUMNS`, MAJBURIY). Postgres'da u
        # qo'shilmasa boot shu yergacha yetib kelmaydi (FATAL); bu shox — faqat SQLite'da
        # o'tkazib yuborilgan holat: backfill va noyob indeksni ustunsiz qurib bo'lmaydi.
        print("[migrate] product_barcodes.company_id yo'q — backfill va ux_barcodes_company_bc "
              "o'tkazib yuborildi")
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
    #
    # ⚠️  AVVAL KATALOGDAN SO'RALADI. `DROP CONSTRAINT IF EXISTS` ACCESS EXCLUSIVE qulfni
    #     mavjudlik tekshiruvidan OLDIN oladi — cheklov allaqachon yo'q bo'lsa ham HAR
    #     boot `product_barcodes` dagi ochiq istalgan o'quvchi (`pg_dump`, uzun hisobot)
    #     ortida navbatga turar, o'zidan keyin esa hatto barkod qidiruvini ham to'xtatardi.
    if engine.dialect.name == "postgresql":
        try:
            with engine.connect() as con:
                legacy = con.execute(text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conrelid = to_regclass('public.product_barcodes') "
                    "AND conname = 'product_barcodes_barcode_key'")).first()
            if legacy is not None:
                with engine.begin() as con:
                    con.execute(text("ALTER TABLE product_barcodes "
                                     "DROP CONSTRAINT IF EXISTS product_barcodes_barcode_key"))
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] barcode global-unique drop — o'tkazib yuborildi ({e})")
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_barcodes_company_bc "
           "ON product_barcodes (company_id, barcode)", "ux_barcodes_company_bc")


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
    # ⚠️  HAR `CREATE [UNIQUE] INDEX` FAQAT `_index` ORQALI (qulfsiz prechek + cheklangan
    #     urinish). To'g'ridan-to'g'ri `engine.begin()` + `IF NOT EXISTS` indeks BOR
    #     bo'lsa ham jadvalga SHARE qulf olardi — `tests/test_boot_locks.py` qo'riqlaydi.
    # PLU noyobligi uchun kompaniya doirasidagi qisman unique indeks (SQLite + Postgres).
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_products_company_plu "
           "ON products (company_id, plu_code) WHERE plu_code IS NOT NULL AND deleted_at IS NULL",
           "ux_products_company_plu")
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
    #  ux_alloc_item_lot — bitta sotuv qatori bitta partiyadan ATIGI BIR MARTA
    #  yeyishi mumkin. Modelda `UniqueConstraint` bor, lekin uni FAQAT
    #  `create_all` chiqaradi: MAVJUD jadvalda cheklov paydo BO'LMAYDI va
    #  SQLite `ADD CONSTRAINT` ni umuman bilmaydi. NOYOB INDEKS esa ikkala
    #  dialektda ham `CREATE ... IF NOT EXISTS` bilan qo'shiladi — ya'ni
    #  qayta yuborishga qarshi DB to'sig'i migratsiya yo'liga ega bo'ladi.
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_alloc_item_lot "
           "ON sale_item_lot_allocations (sale_item_id, stock_batch_id)",
           "ux_alloc_item_lot")
    #  ── PHASE 3: ombor harakati -> partiya ──
    #  ux_smove_alloc — bitta harakat bitta partiyaga ATIGI BIR MARTA. Modeldagi
    #  `UniqueConstraint` ni faqat `create_all` chiqaradi; MAVJUD jadvalda
    #  (va SQLite'da umuman) indeks kerak — takroriy yuborishga DB to'sig'i.
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_smove_alloc "
           "ON stock_movement_lot_allocations (stock_movement_id, stock_batch_id)",
           "ux_smove_alloc")
    #  ⚠️  TEZLIK indeksi — MAJBURIY EMAS. «Bu partiyaga nima bo'ldi» so'rovi
    #      uchun; yo'qligida sekin, lekin TO'G'RI (Phase 1 qoidasi).
    _index("CREATE INDEX IF NOT EXISTS ix_smove_alloc_lot "
           "ON stock_movement_lot_allocations (stock_batch_id)", "ix_smove_alloc_lot")
    #  ux_ret_alloc_line — bitta qaytarish qatori bitta SOTUV QATORINING bitta
    #  partiyasiga ATIGI BIR MARTA (Phase 4A). Eski `ux_ret_alloc` (qaytarish
    #  qatori, partiya) ikki qatorli chekni qaytarishni bloklardi; u
    #  `_relax_ret_alloc_uniqueness` da YANGI indeks yaroqli bo'lgandan KEYIN olinadi.
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_ret_alloc_line "
           "ON return_item_lot_allocations (return_item_id, sale_item_id, stock_batch_id)",
           "ux_ret_alloc_line")
    #  ⚠️  TEZLIK indeksi — MAJBURIY EMAS. Kumulyativ chegara so'rovi
    #      (sale_item bo'yicha) uchun; yo'qligida sekin, lekin TO'G'RI.
    _index("CREATE INDEX IF NOT EXISTS ix_ret_alloc_item "
           "ON return_item_lot_allocations (sale_item_id, stock_batch_id)",
           "ix_ret_alloc_item")
    #  ux_doc_counter — hisoblagich kaliti. `INSERT ... ON CONFLICT (company_id,
    #  kind)` AYNAN shu noyoblikka tayanadi; usiz taqsimlagich ishlamaydi va
    #  ikki parallel sotuv ikkita hisoblagich qatori yaratib, bir xil raqam
    #  berib yuborardi. Modeldagi `UniqueConstraint` ni faqat `create_all`
    #  chiqaradi — MAVJUD bazada indeks kerak.
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_counter "
           "ON doc_counters (company_id, kind)", "ux_doc_counter")
    #  ⚠️  TEZLIK indeksi — MAJBURIY EMAS (`required_schema` ga kirmaydi).
    #      Yo'qligida invariant so'rovi sekinlashadi, javob esa TO'G'RI qoladi.
    #      Uni majburiy qilish ishlab chiqarishni tezlik sababli boot-loop'ga
    #      tushirardi (Phase 1 da o'rnatilgan qoida).
    _index("CREATE INDEX IF NOT EXISTS ix_lot_shortfall_open "
           "ON lot_shortfalls (company_id, branch_id, product_id) "
           "WHERE qty > resolved_qty", "ix_lot_shortfall_open")
    #  ── PHASE 4A: yopish / qaytarish hodisalari ──
    #  Noyob indekslar MAJBURIY (idempotentlik va «bir marta» qoidasi). Modelda
    #  ular `Index(..., unique=True)` — ya'ni yangi bazada `create_all` AYNI
    #  nomli indeksni beradi va bu qatorlar no-op; MAVJUD, to'liqsiz jadvalda esa
    #  shu yerda quriladi.
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_lsr_request_client "
           "ON lot_shortfall_resolution_requests (company_id, client_uuid)",
           "ux_lsr_request_client")
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_lsr_request_lot "
           "ON lot_shortfall_resolutions (request_id, stock_batch_id)",
           "ux_lsr_request_lot")
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_risa_item_shortfall "
           "ON return_item_shortfall_allocations (return_item_id, shortfall_id)",
           "ux_risa_item_shortfall")
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_rira_item_resolution "
           "ON return_item_resolution_allocations (return_item_id, resolution_id, sale_item_id)",
           "ux_rira_item_resolution")
    #  ── PHASE 5D: qabulni tuzatish (teskari yozuv + o'rniga qo'yish) ──
    #  ux_recv_corr_client — tuzatish idempotentligining YAGONA tranzaksion kafolati.
    #  Tuzatish qoldiqni, yetkazib beruvchi qarzini VA kassani siljitadi: SELECT-dedup
    #  klassik TOCTOU bo'lib, ikki bir vaqtdagi takror hammasini IKKI marta yozardi.
    #  Modelda `Index(..., unique=True)` — yangi bazada `create_all` shu nomli indeksni
    #  beradi (bu qator no-op); MAVJUD, to'liqsiz jadvalda esa shu yerda quriladi.
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_recv_corr_client "
           "ON receiving_corrections (company_id, client_uuid)",
           "ux_recv_corr_client")
    #  ⚠️  TEZLIK indekslari — MAJBURIY EMAS (`required_schema.PERFORMANCE_INDEXES`).
    #      `ix_lsr_company_resolved` — P&L og'ishni `resolved_at` davriga yig'adi.
    for _nm, _ddl in (
        ("ix_lsr_company_resolved",
         "ON lot_shortfall_resolutions (company_id, resolved_at)"),
        ("ix_lsr_shortfall", "ON lot_shortfall_resolutions (shortfall_id)"),
        ("ix_lsr_sale_item", "ON lot_shortfall_resolutions (sale_item_id)"),
        ("ix_rira_return", "ON return_item_resolution_allocations (return_id)"),
        ("ix_rira_resolution", "ON return_item_resolution_allocations (resolution_id)"),
        ("ix_risa_shortfall", "ON return_item_shortfall_allocations (shortfall_id)"),
        ("ix_risa_created_batch",
         "ON return_item_shortfall_allocations (created_batch_id)"),
    ):
        _index(f"CREATE INDEX IF NOT EXISTS {_nm} {_ddl}", _nm)
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
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_companies_code "
           "ON companies (code) WHERE code IS NOT NULL AND deleted_at IS NULL",
           "ux_companies_code")
    # Parolli akkaunt telefoni global noyob (race'ga qarshi DB-darajada, TOCTOU emas).
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_employees_phone_pw "
           "ON employees (phone) WHERE phone IS NOT NULL "
           "AND password_hash IS NOT NULL AND deleted_at IS NULL",
           "ux_employees_phone_pw")
    # Offline savdo dublikatiga qarshi DB-darajali dedup: bir client_uuid \u2014 bitta chek (race'ga chidamli).
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_company_client_uuid "
           "ON sales (company_id, client_uuid) "
           "WHERE client_uuid IS NOT NULL AND deleted_at IS NULL",
           "ux_sales_company_client_uuid")
    # Bitta kassir\u0434\u0430 bir vaqt\u0434\u0430 faqat BITTA ochiq smena (race/ikki oyna oldi olinadi).
    _index("CREATE UNIQUE INDEX IF NOT EXISTS ux_shifts_cashier_open "
           "ON shifts (cashier_id) WHERE status = 'open' AND deleted_at IS NULL",
           "ux_shifts_cashier_open")
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
        _index(ddl, name)
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
        _index(ddl, name)


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


def _log_boot_lock_timeout():
    """Boot seansining HAQIQIY `lock_timeout` i — jurnalga (faqat Postgres).

    `DATABASE_URL` dagi `options=` yoki baza/rol sozlamasi `_boot_pgoptions` ni bosib
    ketgan bo'lsa, buni faqat shu satr ko'rsatadi."""
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.connect() as con:
            lt = con.execute(text("SHOW lock_timeout")).scalar()
        print(f"[boot] lock_timeout={lt} — boot DDL'i qulfni shundan uzoq kutmaydi")
    except Exception as e:  # noqa: BLE001
        print(f"[boot] lock_timeout o'qilmadi ({str(e).splitlines()[0] if str(e) else e!r})")


def _log_lot_activation_scope():
    """Partiya kuzatuvini yoqish darvozasining rejimi — jurnalga, QIYMATSIZ.

    Ro'yxat (do'kon/filial UUID'lari) chop etilmaydi: faqat rejim va yozuvlar soni.
    Buzuq yozuv hamma do'konni yopadi — operator buni deploy jurnalidan ko'rsin.
    Jurnal satri hech qachon boot'ni yiqitmaydi."""
    try:
        from app.services import lot_policy as _LP
        s = _LP.scope_summary()
        print(f"[boot] partiya faollashtirish: rejim={s['mode']}, "
              f"ro'yxat yozuvlari={s['entries']}"
              + (" (BUZUQ — hammasi yopiq)" if s["malformed"] else ""))
    except Exception as e:  # noqa: BLE001
        print(f"[boot] partiya faollashtirish rejimi o'qilmadi ({type(e).__name__})")


def _create_all():
    """`create_all` — YO'Q jadvallarni yaratadi (SQLAlchemy: BITTA tranzaksiya).

    ⚠️  Yangi jadvalning FK'lari MAVJUD ota jadvallarga SHARE ROW EXCLUSIVE oladi —
        ya'ni ota jadvaldagi ochiq bitta yozuvchi (masalan `returns`) boot'ni ushlab
        turadi. Qulf band bo'lsa cheklangan qayta urinish (tranzaksiya to'liq qaytadi,
        yarim jadval qolmaydi), so'ng FATAL: jadvalsiz ish vaqti yozolmaydi, Railway'ning
        ON_FAILURE qayta ishga tushirishi esa idempotent boot'ni takrorlaydi.
    Barqaror holatda (hamma jadval bor) faqat katalog o'qiladi — qulf YO'Q."""
    try:
        _lock_retry(lambda: Base.metadata.create_all(engine), "create_all")
    except Exception as e:  # noqa: BLE001
        if _sqlstate(e) == _LOCK_NOT_AVAILABLE:
            stmt = str(getattr(e, "statement", "") or "")
            new = re.findall(r'CREATE\s+TABLE\s+"?(\w+)', stmt, re.IGNORECASE)[:1]
            parents = list(dict.fromkeys(re.findall(r'REFERENCES\s+"?(\w+)', stmt, re.IGNORECASE)))
            print(f"[FATAL] yangi jadval yaratilmadi (create_all): {', '.join(new) or '?'} — "
                  f"{_lock_reason(e, parents or new)}")
        raise


def main():
    _log_boot_lock_timeout()
    _log_lot_activation_scope()
    _create_all()
    _ensure_columns()
    _backfill_company_codes()
    _migrate_barcodes_per_company()   # QA PC-003: barcode endi kompaniya-doirali
    _normalize_plu_codes()            # QA PC-013: PLU yetakchi nollarsiz
    _ensure_indexes()
    _ensure_sale_items_sale_id_index()  # TEZLIK — CONCURRENTLY, hech qachon FATAL emas
    _ensure_tenant_scoped_catalogs()   # customer_groups/brands -> do'konga bog'lash
    _ensure_lot_checks()               # partiya CHECK'lari (Postgres, jadval doirasida)
    _migrate_shortfall_lots()          # Phase 2 manfiy partiyalari -> lot_shortfalls
    _ensure_foreign_keys()             # partiya jadvallari FK'lari — hech qachon FATAL emas
    _relax_ret_alloc_uniqueness()      # eskirgan (return_item_id, stock_batch_id) noyobligi
    _ensure_catalog()          # bazaviy ruxsat/rol/birlik (prod seedsiz ham) — ega'dan OLDIN
    _ensure_roles_and_owner()
    _deploy_cash()             # Cash quyi tizimi (faqat Postgres) — legacy jadvallar YONIGA
    _verify_required_schema()  # OXIRGI darvoza — yetishsa ISHGA TUSHISH YIQILADI
    print("[OK] Jadvallar yaratildi")


def _migrate_shortfall_lots():
    """Phase 2 ning MANFIY `stock_batches` qatorlarini qarzga KO'CHIRADI.

    Phase 2 da yetishmagan miqdor `source_type='shortfall'` bo'lgan MANFIY
    partiya bo'lib yozilardi. Phase 2.5 da jismoniy partiya HECH QACHON manfiy
    emas — qarz `lot_shortfalls` da yashaydi. Bu ko'chirish IDEMPOTENT va
    invariantni SAQLAGAN holda bajariladi:

        manfiy partiya (-N)  ->  qarz qatori (+N) + partiya remaining_qty = 0

    `sale_item_id` NULL qoladi: eski qator AGREGAT edi va qaysi chekdan
    kelganini tiklab bo'lmaydi. Uni o'ylab topish emas, NULL qoldirish halolroq.
    """
    import uuid as _uuid
    from datetime import datetime, timezone
    try:
        with engine.begin() as con:
            rows = con.execute(text(
                "SELECT id, company_id, branch_id, product_id, remaining_qty, unit_cost "
                "FROM stock_batches WHERE source_type = 'shortfall' AND remaining_qty < 0"
            )).fetchall()
            if not rows:
                return
            now = datetime.now(timezone.utc)
            for bid, cid, brid, pid, rem, cost in rows:
                con.execute(text(
                    "INSERT INTO lot_shortfalls (id, company_id, branch_id, product_id, "
                    "sale_item_id, qty, resolved_qty, unit_cost, reason, created_at) "
                    "VALUES (:i, :c, :b, :p, NULL, :q, 0, :u, :r, :t)"),
                    {"i": str(_uuid.uuid4()), "c": cid, "b": brid, "p": pid,
                     "q": abs(float(rem or 0)), "u": float(cost or 0),
                     "r": "Phase 2 manfiy partiyasidan ko'chirildi", "t": now})
                con.execute(text(
                    "UPDATE stock_batches SET remaining_qty = 0, status = 'void' "
                    "WHERE id = :i"), {"i": bid})
            print(f"[migrate] {len(rows)} ta manfiy partiya -> lot_shortfalls")
    except Exception as e:      # noqa: BLE001 — jadval hali yo'q (eski baza)
        print(f"[migrate] kamomad ko'chirish o'tkazib yuborildi: {e}")


def _ensure_lot_checks():
    """Partiya jadvallarining CHECK qoidalari — SXEMA darajasida, JADVAL doirasida.

    `track_expiry => track_lots`: ilova qatlamidagi tekshiruv yetarli emas —
    bayroqlarni to'g'ridan-to'g'ri SQL bilan o'zgartirgan operator muddat
    kuzatuvini partiyasiz yoqib qo'yishi mumkin.

    Phase 4A hodisa jadvallari (`variance = actual − provisional` va h.k.):
    hisobotlar og'ishni SHU ustunlardan yig'adi; qoida faqat kodda tursa, qo'lda
    tuzatilgan bitta qator P&L ayniyatini jimgina buzardi.

    ⚠️  NOT VALID + VALIDATE, IKKI tranzaksiyada. `ADD CONSTRAINT` NOT VALID —
        faqat metama'lumot (qisqa qulf); VALIDATE esa yozuvlarni BLOKLAMAYDI.
        Qoidaga zid eski qator bo'lsa cheklov NOT VALID qoladi: YANGI yozuvlar
        himoyalangan, tayyorlik QIZIL (`required_schema.soft_missing`), lekin
        boot YIQILMAYDI — zid qatorni tuzatish operator qarori.

    SQLite `ALTER TABLE ... ADD CONSTRAINT` ni QO'LLAB-QUVVATLAMAYDI; u yerda
    yangi jadvallar `create_all` bilan modeldagi CHECK'lar bilan tug'iladi.
    """
    if engine.dialect.name != "postgresql":
        print("[migrate] partiya CHECK cheklovlari — SQLite'da o'tkazib yuborildi")
        return
    from app.core import required_schema as rs
    # ⚠️  QULF BAND BO'LSA QAYTA URINILADI (review LOW). Rolling deploy'da eski
    #     instansiya hali `lot_shortfalls` ni o'qiydi; bitta 5 soniyalik urinish
    #     yiqilsa cheklov YO'Q qolardi. FK bilan ayni byudjet va ayni qoida.
    deadline = time.monotonic() + _FK_BUDGET_SECONDS
    state_sql = text(
        "SELECT c.convalidated, "
        "       COALESCE((to_jsonb(c) ->> 'conenforced')::boolean, true), "
        "       pg_get_expr(c.conbin, c.conrelid), "
        f"      {rs._TEXT_COLUMNS_SQL} "
        "FROM pg_constraint c "
        "JOIN pg_class ch ON ch.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = ch.relnamespace "
        "WHERE n.nspname = 'public' AND ch.relname = :t "
        "AND c.conname = :n AND c.contype = 'c'")
    probe_name = "ck_4a1_probe_tmp"
    for name, table in rs.REQUIRED_PG_CONSTRAINTS:
        expr = rs.CHECK_DEFINITIONS[name]
        # ⚠️  BYUDJET TUGAGACH yangi DDL BOSHLANMAYDI (review): har cheklov uchun yana 5 s
        #     ACCESS EXCLUSIVE kutish jonli jadvallarni (products) to'xtatib turardi.
        if time.monotonic() > deadline:
            print(f"[migrate] {name} — qulf byudjeti tugadi, o'tkazib yuborildi "
                  f"(tayyorlik QIZIL bo'lsa: python -m app.tools.repair_lot_schema)")
            continue

        def _add(name=name, table=table, expr=expr):
            """None = jadval yo'q; aks holda — cheklov tasdiqlanganmi.

            ⚠️  ISM BOR, TA'RIF NOTO'G'RI (Phase 4A.1). Ilgari nomi topilgan cheklovga
                umuman qaralmasdi: `CHECK (true)` yoki `NOT ENFORCED` cheklov abadiy
                qolardi. Endi u AYNI `ALTER TABLE` ichida DROP + ADD NOT VALID bilan
                almashtiriladi — jadval BIRORTA ham lahza cheklovsiz qolmaydi, eski
                qatorlar qayta yozilmaydi (VALIDATE keyin, yozuvlarni bloklamaydi).
            ⚠️  TAHLIL QILINMAGAN ta'rif QAYTA YARATILMAYDI: noma'lum ko'rinish
                «isbotlangan xato» emas, va har boot'da jadvalni qulflash sikli
                bo'lib qolmasin. Tayyorlik baribir QIZIL qoladi.
            """
            with engine.begin() as con:
                con.execute(text("SET LOCAL lock_timeout = '5s'"))
                if con.execute(text("SELECT to_regclass(:t)"),
                               {"t": f"public.{table}"}).scalar() is None:
                    return None
                row = con.execute(state_sql, {"t": table, "n": name}).first()
                if row is None:
                    con.execute(text(
                        f'ALTER TABLE "{table}" ADD CONSTRAINT {name} '
                        f"CHECK ({expr}) NOT VALID"))
                    print(f"[migrate] {name} qo'shildi")
                    return False
                validated, enforced = bool(row[0]), bool(row[1])
                cols = frozenset(row[3] or ())
                state = rs.check_definition_state(name, row[2], cols)

                def _recreate(why):
                    # Qisqa qulf kutish (review): jonli jadvalda (products) so'rovlar navbati
                    # ACCESS EXCLUSIVE ortida uzoq to'planmasin.
                    con.execute(text("SET LOCAL lock_timeout = '1s'"))
                    con.execute(text(
                        f'ALTER TABLE "{table}" DROP CONSTRAINT {name}, '
                        f"ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID"))
                    print(f"[migrate] {name}: {why} edi — ayni tranzaksiyada "
                          f"qayta yaratildi (NOT VALID)")

                if not enforced:
                    _recreate("NOT ENFORCED")
                    return False
                if state == rs.CHECK_DEF_WRONG:
                    # ⚠️  QAYTA YARATISH SIKLIGA QARSHI (review). Kutilgan ifodani Postgres SHU
                    #     sxemada qanday yozishi ko'riladi: ustun tiplari modeldan farq qilsa
                    #     (butun son + numeric) Postgres keltirish qo'shadi va kanonizator uni
                    #     ham «noto'g'ri» deydi — qayta yaratish natijani o'zgartirmas edi.
                    # ⚠️  JONLI JADVALGA QULFSIZ (re-review). Sinov cheklovi jadvalning O'ZIDA
                    #     EMAS, uning ustun tiplari nusxasida (TEMP ... LIKE) yaratiladi — manba
                    #     jadvalga faqat ACCESS SHARE. Aks holda og'gan sxemada HAR boot ACCESS
                    #     EXCLUSIVE olib, kassa so'rovlarini navbatda ushlab turardi.
                    con.execute(text(f'CREATE TEMP TABLE {probe_name} (LIKE public."{table}")'))
                    con.execute(text(f"ALTER TABLE {probe_name} ADD CONSTRAINT {probe_name} "
                                     f"CHECK ({expr})"))
                    probe = con.execute(text(
                        "SELECT pg_get_expr(c.conbin, c.conrelid) FROM pg_constraint c "
                        "WHERE c.conrelid = CAST(:r AS regclass) AND c.conname = :n"),
                        {"r": f"pg_temp.{probe_name}", "n": probe_name}).scalar()
                    con.execute(text(f"DROP TABLE {probe_name}"))
                    if rs.check_definition_state(name, probe, cols) != rs.CHECK_DEF_OK:
                        print(f"[migrate] {name}: kutilgan ifoda ham shu sxemada tanilmadi "
                              f"(ustun tiplari modeldan farqlimi?) — QAYTA YARATILMAYDI, "
                              f"tayyorlik QIZIL qoladi. `\\d+ {table}` bilan tekshiring")
                        return True     # ma'lum-noto'g'ri cheklov har boot'da VALIDATE qilinmasin
                    _recreate("ta'rifi noto'g'ri")
                    return False
                if state == rs.CHECK_DEF_UNPARSED:
                    print(f"[migrate] {name}: katalogdagi ta'rifni tahlil qilib bo'lmadi — "
                          f"AVTOMATIK qayta yaratilmaydi, tayyorlik QIZIL qoladi. "
                          f"`\\d+ {table}` bilan qo'lda tekshiring")
                return validated

        def _validate(name=name, table=table):
            with engine.begin() as con:
                con.execute(text("SET LOCAL lock_timeout = '5s'"))
                con.execute(text(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT {name}'))

        try:
            validated = _fk_retry(_add, deadline)
            if validated is None:
                print(f"[migrate] {name} — jadval yo'q ({table}), o'tkazib yuborildi")
                continue
            if not validated:
                _fk_retry(_validate, deadline)
                print(f"[migrate] {name} tasdiqlandi")
        except Exception as e:      # noqa: BLE001
            if _sqlstate(e) == "23514":         # check_violation — zid eski qatorlar
                print(f"[migrate] {name} TASDIQLANMADI: {table} da qoidaga zid qatorlar bor — "
                      f"cheklov NOT VALID qoldi (YANGI yozuvlar himoyalangan), tayyorlik QIZIL. "
                      f"Zid qatorlarni tuzatib `python -m app.tools.repair_lot_schema` ni "
                      f"ishga tushiring")
                continue
            print(f"[migrate] {name} — o'tkazib yuborildi "
                  f"({str(e).splitlines()[0] if str(e) else e!r})")


# ══ TEZLIK INDEKSI: sale_items(sale_id) — CONCURRENTLY (Phase 4A) ═══════════
def _ensure_sale_items_sale_id_index():
    """`ix_sale_items_sale_id` — MAVJUD Postgres'da yozuvlarni BLOKLAMASDAN quradi.

    ⚠️  NEGA ODDIY `_index` EMAS. Oddiy `CREATE INDEX` jadvalga SHARE qulf oladi
        va qurilish davomida HAR sotuvni to'xtatadi (1.2M qatorda ~2.6 s). Jonli
        kassa uchun bu qabul qilinmaydi — shu bois CONCURRENTLY.

    ⚠️  CONCURRENTLY TRANZAKSIYA BLOKIDA ISHLAMAYDI. Shu bois ALOHIDA, AUTOCOMMIT
        ulanishida bajariladi; `lock_timeout` sessiya darajasida qo'yiladi va
        `finally` da QAYTARILADI (ulanish pool'ga iflos qaytmasin).

    ⚠️  YIQILGAN CONCURRENTLY YAROQSIZ (`indisvalid=false`) indeks qoldiradi va
        `IF NOT EXISTS` uni «bor» deb o'tkazib yuborardi — indeks esa hech qachon
        ishlatilmasdi. Shu bois yaroqlilik AYNI ulanishda tekshiriladi va yaroqsiz
        indeks tushirilib, qayta quriladi.

    HECH QACHON FATAL EMAS: indeks faqat TEZLIK; yo'qligida javob o'zgarmaydi.
    """
    name = "ix_sale_items_sale_id"
    if engine.dialect.name != "postgresql":
        _index("CREATE INDEX IF NOT EXISTS ix_sale_items_sale_id ON sale_items (sale_id)", name)
        return
    valid_sql = text(
        "SELECT i.indisvalid AND i.indisready FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = :n "
        "AND i.indrelid = 'public.sale_items'::regclass")
    try:
        ac = engine.execution_options(isolation_level="AUTOCOMMIT")
        with ac.connect() as con:
            try:
                con.execute(text("SET lock_timeout = '10s'"))
                row = con.execute(valid_sql, {"n": name}).first()
                if row is not None and row[0]:
                    return
                if row is not None:
                    print(f"[perf] {name} YAROQSIZ (oldingi CONCURRENTLY yiqilgan) — "
                          "tushirilib qayta quriladi")
                    con.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS public.{name}"))
                t0 = time.monotonic()
                con.execute(text(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                    "ON public.sale_items (sale_id)"))
                row = con.execute(valid_sql, {"n": name}).first()
                if row is not None and row[0]:
                    print(f"[perf] {name} CONCURRENTLY qurildi "
                          f"({(time.monotonic() - t0) * 1000:.0f} ms)")
                else:
                    print(f"[perf] {name} qurilmadi yoki YAROQSIZ — javob o'zgarmaydi, "
                          "faqat sekinroq; keyingi boot qayta uriniadi")
            finally:
                try:
                    con.execute(text("RESET lock_timeout"))
                except Exception:      # noqa: BLE001
                    pass
    except Exception as e:      # noqa: BLE001
        print(f"[perf] {name} — o'tkazib yuborildi "
              f"({str(e).splitlines()[0] if str(e) else e!r}); javob o'zgarmaydi")


# ══ MAJBURIY FK TUZATISH (Phase 4A) ═════════════════════════════════════════
#
# ⚠️  HECH QACHON FATAL EMAS. Railway'da healthcheck yo'q va `restartPolicy`
#     ON_FAILURE: boot'dagi har FATAL cheksiz crash-loop. FK'ni tuzatib bo'lmasa
#     (yetim qatorlar, qulf band, shakli noto'g'ri FK) — sabab JURNALGA yoziladi,
#     tayyorlik QIZIL bo'ladi (`required_schema.soft_missing`), va `/lots/enable`
#     kuzatuvni yoqishni RAD etadi. Ya'ni xavfli holat ko'rinadi va yangi partiya
#     tarixi tug'ilmaydi, lekin mavjud savdo to'xtamaydi.
#
# ⚠️  TO'G'RI FK HECH QACHON TEGILMAYDI: faqat MISSING (qo'shiladi) va NOT_VALID
#     (tasdiqlanadi). WRONG / NOT_ENFORCED — faqat jurnal: noto'g'ri FK'ni
#     avtomatik DROP qilish ma'lumotni himoyasiz qoldiradi va operator qarori.
_FK_BUDGET_SECONDS = 30.0
_FK_RETRY_SQLSTATES = frozenset({"55P03", "40P01"})   # lock_not_available, deadlock


def _sqlstate(e) -> str | None:
    return getattr(getattr(e, "orig", None), "sqlstate", None)


def _fk_columns_exist(con, fk) -> bool:
    rows = con.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name IN (:c, :p)"),
        {"c": fk.child, "p": fk.parent}).fetchall()
    have = {(t, c) for t, c in rows}
    return (all((fk.child, c) in have for c in fk.cols)
            and all((fk.parent, c) in have for c in fk.refcols))


def _fk_orphans(con, fk) -> int:
    nn = " AND ".join(f'c."{a}" IS NOT NULL' for a in fk.cols)
    match = " AND ".join(f'p."{r}" = c."{a}"' for a, r in zip(fk.cols, fk.refcols))
    return int(con.execute(text(
        f'SELECT count(*) FROM "{fk.child}" c WHERE {nn} '
        f'AND NOT EXISTS (SELECT 1 FROM "{fk.parent}" p WHERE {match})')).scalar() or 0)


def _fk_retry(fn, deadline):
    """Qulf band / deadlock -> byudjet ichida qayta urinadi; boshqa xato -> yuqoriga."""
    while True:
        try:
            return fn()
        except Exception as e:      # noqa: BLE001
            if _sqlstate(e) in _FK_RETRY_SQLSTATES and time.monotonic() < deadline:
                time.sleep(0.5)
                continue
            raise


def _fk_add(fk, deadline) -> dict:
    """MISSING FK'ni NOT VALID qo'shadi. Qulflar QAT'IY tartibda, holat QULF ICHIDA."""
    from app.core import required_schema as rs
    ondel = " ON DELETE CASCADE" if fk.on_delete == "c" else ""
    cols = ", ".join(f'"{c}"' for c in fk.cols)
    refs = ", ".join(f'"{c}"' for c in fk.refcols)

    def _do():
        with engine.begin() as con:
            con.execute(text("SET LOCAL lock_timeout = '5s'"))
            if not _fk_columns_exist(con, fk):
                return {"skip": "jadval yoki ustun yo'q"}
            # `ADD FOREIGN KEY` IKKALA jadvalga ham SHARE ROW EXCLUSIVE oladi;
            # oshkora LOCK tartibni DETERMINISTIK qiladi (alifbo) — ikki instansiya
            # yoki jonli yozuvchi bilan AB/BA halqa tug'ilmasin.
            for t in sorted({fk.child, fk.parent}):
                con.execute(text(f'LOCK TABLE "{t}" IN SHARE ROW EXCLUSIVE MODE'))
            st, _names = rs.classify_fk(fk, rs.fk_rows(con))
            if st != rs.FK_MISSING:
                return {"skip": f"qulf ichida holat: {st}"}   # boshqa instansiya bajardi
            orphans = _fk_orphans(con, fk)
            con.execute(text(
                f'ALTER TABLE "{fk.child}" ADD FOREIGN KEY ({cols}) '
                f'REFERENCES "{fk.parent}" ({refs}){ondel} NOT VALID'))
            return {"orphans": orphans}
    return _fk_retry(_do, deadline)


def _fk_validate(fk, names, deadline) -> None:
    """VALIDATE — yozuvlarni BLOKLAMAYDI (SHARE UPDATE EXCLUSIVE)."""
    def _do():
        with engine.begin() as con:
            con.execute(text("SET LOCAL lock_timeout = '5s'"))
            for n in names:
                con.execute(text(f'ALTER TABLE "{fk.child}" VALIDATE CONSTRAINT "{n}"'))
    _fk_retry(_do, deadline)


def _ensure_foreign_keys():
    if engine.dialect.name != "postgresql":
        return
    from app.core import required_schema as rs
    deadline = time.monotonic() + _FK_BUDGET_SECONDS
    try:
        states = rs.fk_states(engine)
    except Exception as e:      # noqa: BLE001
        print(f"[fk] holatni o'qib bo'lmadi — tuzatish o'tkazib yuborildi ({e})")
        return
    for fk in rs.REQUIRED_FOREIGN_KEYS:
        st, names = states.get(fk, (rs.FK_MISSING, []))
        if st == rs.FK_OK:
            continue
        if st in (rs.FK_WRONG, rs.FK_NOT_ENFORCED):
            print(f"[fk] {fk.label}: holat «{st}» ({', '.join(names)}) — AVTOMATIK "
                  "tuzatilmaydi; tayyorlik QIZIL. Qo'lda ko'rib chiqing.")
            continue
        if time.monotonic() >= deadline:
            print(f"[fk] {fk.label}: vaqt byudjeti ({_FK_BUDGET_SECONDS:.0f}s) tugadi — "
                  "keyingi boot'da davom etadi")
            continue
        try:
            if st == rs.FK_MISSING:
                res = _fk_add(fk, deadline)
                if "skip" in res:
                    print(f"[fk] {fk.label}: qo'shilmadi — {res['skip']}")
                    continue
                if res["orphans"]:
                    print(f"[fk] {fk.label}: NOT VALID qo'shildi, lekin {res['orphans']} ta "
                          "YETIM qator bor — TASDIQLANMADI. Yangi yozuvlar himoyalangan; "
                          "tayyorlik QIZIL qoladi, yetim qatorlarni qo'lda ko'rib chiqing.")
                    continue
                print(f"[fk] {fk.label}: NOT VALID qo'shildi")
                with engine.connect() as con:
                    st, names = rs.classify_fk(fk, rs.fk_rows(con))
            if st == rs.FK_NOT_VALID:
                _fk_validate(fk, names, deadline)
                print(f"[fk] {fk.label}: tasdiqlandi")
        except Exception as e:      # noqa: BLE001
            print(f"[fk] {fk.label}: tuzatilmadi "
                  f"({_sqlstate(e) or ''} {str(e).splitlines()[0] if str(e) else e!r}) — "
                  "boot DAVOM etadi, tayyorlik QIZIL")


def _relax_ret_alloc_uniqueness():
    """Eskirgan `(return_item_id, stock_batch_id)` noyobligini olib tashlaydi (Phase 4A).

    ⚠️  NEGA. Bitta chekda ayni mahsulot IKKI qatorda AYNI partiyadan sotilgan bo'lsa,
        ikkalasini bitta qaytarishda qaytarish ikki taqsimot qatori yozadi va eski
        kalitga urilib DOIMIY 409 beradi. Yangi kalit `ux_ret_alloc_line`
        (qaytarish qatori, sotuv qatori, partiya) takror qatorga qarshi himoyani
        SAQLAYDI — faqat qonuniy holatni ochadi.

    ⚠️  TARTIB: faqat YANGI indeks yaroqli bo'lgach eskisi olinadi (orada himoyasiz
        oyna yo'q). Eski kalit ikki shaklda bo'lishi mumkin: `create_all` bergan
        nomsiz UNIQUE cheklov va `_index` bergan `ux_ret_alloc` — ikkalasi ham
        USTUNLAR to'plami bo'yicha topiladi.

    HECH QACHON FATAL EMAS: olinmay qolsa eski (qattiqroq) xulq davom etadi, tayyorlik
    QIZIL bo'ladi (`required_schema.soft_missing`), ta'mirlash vositasi qayta uriniadi.
    """
    if engine.dialect.name != "postgresql":
        try:
            with engine.begin() as con:
                con.execute(text("DROP INDEX IF EXISTS ux_ret_alloc"))
        except Exception as e:      # noqa: BLE001
            print(f"[migrate] ux_ret_alloc (SQLite) — o'tkazib yuborildi ({e})")
        return
    from app.core import required_schema as rs
    try:
        with engine.connect() as con:
            if not rs.index_valid(con, "ux_ret_alloc_line"):
                print("[migrate] ux_ret_alloc_line yaroqli emas — eski noyoblik SAQLANADI")
                return
            if not rs.legacy_ret_alloc_uniques(con):
                return
        deadline = time.monotonic() + _FK_BUDGET_SECONDS

        def _do():
            with engine.begin() as con:
                con.execute(text("SET LOCAL lock_timeout = '5s'"))
                done = []
                for index_name, constraint_name in rs.legacy_ret_alloc_uniques(con):
                    if constraint_name:
                        con.execute(text('ALTER TABLE return_item_lot_allocations '
                                         f'DROP CONSTRAINT "{constraint_name}"'))
                        done.append(constraint_name)
                    else:
                        con.execute(text(f'DROP INDEX IF EXISTS public."{index_name}"'))
                        done.append(index_name)
                return done
        done = _fk_retry(_do, deadline)
        if done:
            print("[migrate] return_item_lot_allocations: eskirgan (return_item_id, "
                  f"stock_batch_id) noyobligi olib tashlandi: {', '.join(done)}")
    except Exception as e:      # noqa: BLE001
        print(f"[migrate] eskirgan qaytarish noyobligi — o'tkazib yuborildi "
              f"({str(e).splitlines()[0] if str(e) else e!r}); tayyorlik QIZIL")


def _verify_required_schema():
    """MAJBURIY V2 obyektlari HAQIQATAN bormi — migratsiyadan KEYIN tekshiriladi.

    Har bir qadam alohida ham himoyalangan, lekin bu ikkinchi qatlam ATAYLAB bor:
    `CREATE INDEX IF NOT EXISTS` xato BERMASDAN hech narsa qilmasligi mumkin
    (masalan indeks boshqa ta'rif bilan allaqachon mavjud bo'lsa), ya'ni qadam
    "muvaffaqiyatli" ko'rinib, obyekt baribir kutilganday bo'lmasligi mumkin.
    Yagona ishonchli savol — «obyekt bazada bormi?».

    ⚠️  FATAL qarori FAQAT halokatli sinfga tayanadi (ustun / noyob indeks /
        CHECK umuman yo'q). FK holatlari va tasdiqlanmagan CHECK — tayyorlikni
        QIZIL qiladi, lekin boot'ni YIQITMAYDI (`required_schema` izohi).
    """
    from app.core import required_schema as rs
    missing = rs.fatal_missing(engine)
    soft = rs.soft_missing(engine)
    for s in soft:
        print(f"[schema] TAYYOR EMAS (boot davom etadi) — {s}")
    # ⚠️  Idempotentlik indeksi / ustun tipi — TAYYOR EMAS, lekin HECH QACHON FATAL: tuzatish
    #     dublikat qatorlar yoki UUID bo'lmagan qiymatlar ustida operator qarorini talab qiladi.
    bad_types = rs.column_type_problems(engine)
    for s in rs.idempotency_missing(engine) + bad_types:
        print(f"[schema] TAYYOR EMAS (boot davom etadi) — {s}")
    if bad_types:
        # ⚠️  BOOT TIPNI O'ZGARTIRMAYDI (`_ADDED_COLUMNS` izohi). Yagona yo'l — ANIQ migratsiya;
        #     satr O'ZGARMAS: qiymat ham, baza nomi ham, xato matni ham chiqmaydi.
        print(_UUID_MIGRATION_HINT)
    for u in rs.optional_unique_missing(engine):
        print(f"[integrity] {u} — DB darajasidagi dublikat to'sig'i yo'q (ilova tekshiruvi ishlaydi)")
    for p in rs.performance_missing(engine):
        print(f"[perf] {p} — javob o'zgarmaydi, faqat sekinroq")
    if not missing:
        print(f"[schema] majburiy V2 obyektlari joyida "
              f"({len(rs.REQUIRED_COLUMNS)} ustun + {len(rs.REQUIRED_INDEXES)} indeks; "
              f"{len(rs.REQUIRED_FOREIGN_KEYS)} FK — tayyor emas: {len(soft)})")
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


# ══ BOOT SEANSI QULF KUTISHI — faqat `python -m app.initdb` ═══════════════════
#
# ⚠️  NEGA PGOPTIONS. libpq uni HAR ulanishda o'qiydi: SQLAlchemy pool'i, cash
#     deploy'ning `raw_connection` i, CONCURRENTLY'ning AUTOCOMMIT ulanishi — boot'ning
#     HAMMA ulanishi bir xil chegarani oladi. Engine import paytida ulanmaydi (dangasa),
#     shu bois `main()` dan OLDIN qo'yish yetarli. uvicorn (`start.sh` dagi alohida
#     `exec`) va testlardagi jarayon ichidagi `initdb.main()` bunga TEGILMAYDI.
#     O'z chegarasini qo'yadigan yo'llar o'z qiymatini saqlaydi (tenancy/CHECK/FK —
#     `SET LOCAL`; CONCURRENTLY — sessiya `SET`, uning `RESET` i endi 0 ga emas, shu
#     chegaraga qaytaradi).
# ⚠️  MAVJUD opsiyalar SAQLANADI (masalan `-c default_transaction_read_only=on`); operator
#     `lock_timeout` ni o'zi bergan bo'lsa — uniki ustun (ochiq `0` ham — bu uning
#     qarori). `SAVDOOS_BOOT_LOCK_TIMEOUT` YO'Q, bo'sh yoki yaroqsiz bo'lsa — standart;
#     hech qachon jimgina «cheksiz» emas.
# ⚠️  `statement_timeout` ATAYLAB QO'YILMAYDI. U CONCURRENTLY qurilishini uzib yaroqsiz
#     indeks qoldirardi (har boot qayta qurish) va VALIDATE ni (yozuvlarni bloklamaydi)
#     bekorga bekor qilardi. Xavf — qulf KUTISH, bajarilish vaqti emas.
_BOOT_LOCK_TIMEOUT_DEFAULT = "2s"
# GUC nomi katta-kichik harfga sezgir EMAS (`-c LOCK_TIMEOUT=0` ham operator qiymati).
_LOCK_TIMEOUT_OPTION = re.compile(r"(?:^|\s)(?:-c\s*|--)lock[_-]timeout=", re.IGNORECASE)
# ⚠️  Bosh nol TAQIQLANGAN: Postgres sonni `strtol(.., 0)` bilan o'qiydi — `08s` sakkizlik
#     `0` + noma'lum birlik `8s` bo'lib RAD etiladi, `010` esa jimgina 8 ga aylanadi.
_LOCK_TIMEOUT_VALUE = re.compile(r"(0|[1-9]\d*)(ms|s|min|h|d)?")
_LOCK_TIMEOUT_UNIT_MS = {"": 1, "ms": 1, "s": 1000, "min": 60_000, "h": 3_600_000, "d": 86_400_000}
# `lock_timeout` — millisekundlik int: 2147483647 dan kattasi (≈24.8 kun) RAD etiladi.
_LOCK_TIMEOUT_MAX_MS = 2_147_483_647


def _boot_lock_timeout_ok(val: str) -> bool:
    """Qiymatni Postgres QABUL qiladimi. Startup opsiyasidagi yaroqsiz qiymat HAR ulanishni
    FATAL bilan rad ettiradi — boot umuman ko'tarilmay, Railway uni bir xil env bilan qayta-qayta
    ishga tushirardi. Shu bois bunday qiymat standartga almashtiriladi."""
    m = _LOCK_TIMEOUT_VALUE.fullmatch(val)
    return bool(m) and int(m.group(1)) * _LOCK_TIMEOUT_UNIT_MS[m.group(2) or ""] <= _LOCK_TIMEOUT_MAX_MS


def _boot_pgoptions(existing: str | None, value: str | None) -> str:
    """Boot jarayoni uchun PGOPTIONS: mavjud opsiyalar + `-c lock_timeout=<value>`.

    `existing` — hozirgi PGOPTIONS, `value` — `SAVDOOS_BOOT_LOCK_TIMEOUT`. Toza funksiya."""
    base = (existing or "").strip()
    if _LOCK_TIMEOUT_OPTION.search(base):
        return base
    val = "".join((value or "").split())
    if not _boot_lock_timeout_ok(val):
        val = _BOOT_LOCK_TIMEOUT_DEFAULT
    opt = f"-c lock_timeout={val}"
    return f"{base} {opt}" if base else opt


if __name__ == "__main__":
    _env_lt = "".join((os.environ.get("SAVDOOS_BOOT_LOCK_TIMEOUT") or "").split())
    if _env_lt and not _boot_lock_timeout_ok(_env_lt):
        print(f"[boot] SAVDOOS_BOOT_LOCK_TIMEOUT={_env_lt!r} yaroqsiz (Postgres rad etardi) — "
              f"standart {_BOOT_LOCK_TIMEOUT_DEFAULT} ishlatiladi")
    os.environ["PGOPTIONS"] = _boot_pgoptions(os.environ.get("PGOPTIONS"),
                                              os.environ.get("SAVDOOS_BOOT_LOCK_TIMEOUT"))
    main()
