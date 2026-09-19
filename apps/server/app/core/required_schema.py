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

UCH SINF — ARALASHTIRILMAYDI (Phase 4A):
  · HALOKATLI (fatal)   — ustun / noyob indeks / CHECK UMUMAN yo'q. Kod ularsiz
                          yozolmaydi yoki idempotentlik yo'qoladi -> boot TO'XTAYDI.
  · TAYYOR EMAS (soft)  — FK yo'q/tasdiqlanmagan/noto'g'ri, CHECK tasdiqlanmagan.
                          Tayyorlik QIZIL, lekin boot YIQILMAYDI. Sabab: Railway'da
                          healthcheck yo'q, `restartPolicy=ON_FAILURE` — FK uchun
                          boot-FATAL cheksiz crash-loop bo'lardi, holbuki FK'ni
                          tuzatish (yetim qatorlar) operator qarori talab qiladi.
  · TEZLIK (performance)— yo'qligida javob O'ZGARMAYDI, faqat sekinlashadi.
                          Tayyorlikka UMUMAN ta'sir qilmaydi.

PHASE 5B.1 — TAYYOR EMAS sinfining `missing()` ga KIRMAYDIGAN ikki qo'shnisi (alohida
tayyorlik kalitlari; `missing()`, `catalog_v2_schema`/`lot_schema_integrity` tasnifi va
`lot_policy.schema_problems` ularni KO'RMAYDI):
  · `idempotency_missing`   — pul/qoldiq/auth idempotentlik noyob indekslari
                              (qurish dublikat qatorlarda yiqilishi mumkin — operator);
  · `column_type_problems`  — uuid bo'lishi shart ustun varchar qolgan (UUID bo'lmagan
                              qiymat bor — operator).
Va faqat JURNAL: `optional_unique_missing` (ma'lumot sifati noyobliklari).
Har boot qo'shadigan indeks AYNAN BITTA sinfda (`tests/test_runtime_columns.py`).

⚠️  PHASE 5C — QAROR TESKARISIGA O'ZGARDI: yuqoridagi ikki sinf `missing()` dan
    TASHQARIDA qoladi (tasnif o'zgarmaydi), LEKIN partiya kuzatuvini yoqishni
    ENDI TO'SADI — alohida darvoza orqali (`lot_policy.activation_readiness` ->
    `/lots/enable` 409 `LOT_SCHEMA_NOT_READY`). Sabab: yoqish QAYTARIB
    BO'LMAYDI, undan keyin esa ayni mahsulot offline sotuv/qaytarish/kassa
    yozuvlarini tug'diradi — takrorni to'suvchi noyob indeks yoki uuid ustun tipi
    yo'q bo'lsa o'sha tarix ikkilangan yoki yiqilgan holda paydo bo'lardi.
"""
from __future__ import annotations

from dataclasses import dataclass

from contextlib import contextmanager

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

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
    #  `return_items.cost_total` — qaytarish yo'li HAR qatorda yozadi va
    #  hisobotlar o'qiydi; yo'q bo'lsa qaytarish UMUMAN yozilmasdi.
    ("return_items", "cost_total"),
    # ── PHASE 3 — hisobdan chiqarish / inventarizatsiya ish vaqti ──────────
    #  Kuzatuvli mahsulotda HAR hisobdan chiqarish partiya tafsilotini YOZADI;
    #  ustun yo'q bo'lsa amal umuman yakunlanmasdi.
    ("stock_movement_lot_allocations", "company_id"),
    ("stock_movement_lot_allocations", "stock_movement_id"),
    ("stock_movement_lot_allocations", "stock_batch_id"),
    ("stock_movement_lot_allocations", "product_id"),
    ("stock_movement_lot_allocations", "qty"),
    ("stock_movement_lot_allocations", "unit_cost"),
    #  Qaytarish ish vaqti: kumulyativ chegara va ANIQ COGS shularsiz ishlamaydi.
    ("return_item_lot_allocations", "company_id"),
    ("return_item_lot_allocations", "return_item_id"),
    ("return_item_lot_allocations", "sale_item_id"),
    ("return_item_lot_allocations", "stock_batch_id"),
    ("return_item_lot_allocations", "product_id"),
    ("return_item_lot_allocations", "qty"),
    ("return_item_lot_allocations", "unit_cost"),
    ("return_items", "cost_unresolved"),
    ("lot_shortfalls", "resolved_cost"),
    ("lot_shortfalls", "returned_qty"),
    #  `sales.cost_basis` — hisobot ish vaqtida O'QIYDI (P&L taxminiy ulushi);
    #  ustun yo'q bo'lsa P&L so'rovi UMUMAN yiqilardi.
    ("sales", "cost_basis"),
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
    # ── PHASE 4A — yopish/qaytarish HODISALARI va basis tasnifi ─────────────
    #  Yopish yo'li, qaytarish yo'li va hisobotlar BUGUN shularga yozadi/o'qiydi.
    ("sale_items", "provisional_qty"),
    ("lot_shortfall_resolution_requests", "company_id"),
    ("lot_shortfall_resolution_requests", "client_uuid"),
    ("lot_shortfall_resolution_requests", "shortfall_id"),
    ("lot_shortfall_resolution_requests", "request_hash"),
    ("lot_shortfall_resolution_requests", "response_json"),
    ("lot_shortfall_resolution_requests", "employee_id"),
    ("lot_shortfall_resolution_requests", "created_at"),
    ("lot_shortfall_resolutions", "request_id"),
    ("lot_shortfall_resolutions", "line_no"),
    ("lot_shortfall_resolutions", "kind"),
    ("lot_shortfall_resolutions", "company_id"),
    ("lot_shortfall_resolutions", "branch_id"),
    ("lot_shortfall_resolutions", "product_id"),
    ("lot_shortfall_resolutions", "shortfall_id"),
    ("lot_shortfall_resolutions", "sale_item_id"),
    ("lot_shortfall_resolutions", "stock_batch_id"),
    ("lot_shortfall_resolutions", "expiry_date"),
    ("lot_shortfall_resolutions", "qty"),
    ("lot_shortfall_resolutions", "provisional_unit_cost"),
    ("lot_shortfall_resolutions", "actual_unit_cost"),
    ("lot_shortfall_resolutions", "provisional_cost"),
    ("lot_shortfall_resolutions", "actual_cost"),
    ("lot_shortfall_resolutions", "variance"),
    ("lot_shortfall_resolutions", "resolved_at"),
    ("lot_shortfall_resolutions", "employee_id"),
    ("lot_shortfall_resolutions", "created_at"),
    ("return_item_shortfall_allocations", "company_id"),
    ("return_item_shortfall_allocations", "return_id"),
    ("return_item_shortfall_allocations", "return_item_id"),
    ("return_item_shortfall_allocations", "shortfall_id"),
    ("return_item_shortfall_allocations", "created_batch_id"),
    ("return_item_shortfall_allocations", "product_id"),
    ("return_item_shortfall_allocations", "branch_id"),
    ("return_item_shortfall_allocations", "qty"),
    ("return_item_shortfall_allocations", "provisional_unit_cost"),
    ("return_item_shortfall_allocations", "provisional_cost_credit"),
    ("return_item_shortfall_allocations", "created_at"),
    ("return_item_resolution_allocations", "company_id"),
    ("return_item_resolution_allocations", "return_id"),
    ("return_item_resolution_allocations", "return_item_id"),
    ("return_item_resolution_allocations", "resolution_id"),
    ("return_item_resolution_allocations", "sale_item_id"),
    ("return_item_resolution_allocations", "stock_batch_id"),
    ("return_item_resolution_allocations", "product_id"),
    ("return_item_resolution_allocations", "branch_id"),
    ("return_item_resolution_allocations", "qty"),
    ("return_item_resolution_allocations", "provisional_cost_credit"),
    ("return_item_resolution_allocations", "variance_reversed"),
    ("return_item_resolution_allocations", "created_at"),
    # ── PHASE 5B.1 — ORM XARITALAGAN HAR QO'SHILGAN USTUN MAJBURIY ──────────
    #  QOIDA (qurilishi bo'yicha): model ustunni `mapped_column` bilan e'lon qilsa,
    #  HAR `select(Model)` uni SELECT ro'yxatida nomma-nom beradi, HAR ORM INSERT esa
    #  (nullable va standartsiz bo'lsa ham — NULL sifatida) yozadi. Ya'ni ustun bazada
    #  yo'q bo'lsa o'sha modelning HAR yuklanishi va HAR yozuvi yiqiladi; eager load
    #  (`Product.barcodes` selectin) orqali esa QO'SHNI model ham. Bu «biroz kamroq
    #  imkoniyat» emas: `employees.sec_epoch` yo'q -> HAR autentifikatsiyalangan so'rov
    #  (`deps.get_current_employee`) 500, tayyorlik esa ilgari YASHIL qolardi.
    #  `_ensure_columns` ustunni HAR DOIM nullable yoki DEFAULT'li qo'shadi — yagona
    #  yiqilish sababi band qulf, uni qayta ishga tushirish tuzatadi. Shu bois FATAL
    #  to'g'ri tasnif (operator qarori kerak emas). Qo'riqchi:
    #  `tests/test_runtime_columns.py` — xaritalangan, lekin bu ro'yxatda yo'q qo'shilgan
    #  ustun QIZIL. Jonli issiq jadvalga yangi ustun uchun kengaytir/qisqartir yo'li:
    #  N-relizda ustun XARITALANMAGAN qo'shiladi (`UNMAPPED_ADDED_COLUMNS`), N+1 da
    #  modelga ulanadi — o'shanda boot ALTER'i allaqachon no-op.
    ("employees", "sec_epoch"),
    ("companies", "code"),
    ("products", "sku"),
    ("products", "expiry_date"),
    ("products", "is_weighted"),
    ("products", "plu_code"),
    ("products", "scale_sync"),
    ("product_barcodes", "company_id"),
    ("inventory", "low_alerted"),
    #  Ilgari faqat BILVOSITA halokatli edi (`ux_movements_cutover_key` ularsiz qurilmasdi).
    ("stock_movements", "client_uuid"),
    ("stock_movements", "ref_type"),
    ("sales", "till_id"),
    ("sales", "cashier_name_snapshot"),
    ("sales", "branch_name_snapshot"),
    ("sales", "till_code_snapshot"),
    ("sales", "till_label_snapshot"),
    ("sales", "terminal_name_snapshot"),
    ("returns", "shift_id"),
    ("returns", "till_id"),
    ("shifts", "till_id"),
    #  Bu uchtasining TIPI ham tekshiriladi (`UUID_TYPED_COLUMNS`) — mavjudlik yetmaydi.
    ("cash_movements", "client_uuid"),
    ("customer_payments", "cash_account_id"),
    ("purchases", "cash_account_id"),
    ("supplier_payments", "cash_account_id"),
    ("purchase_returns", "cash_account_id"),
    ("qr_payments", "sale_id"),
    ("qr_payments", "client_uuid"),
    #  Kam trafikli telemetriya jadvali: qulf sababli FATAL ehtimoli juda past, bitta
    #  bir xil qoida esa tanlov ro'yxatidan ishonchliroq.
    ("sync_devices", "company_id"),
    ("sync_devices", "branch_id"),
    ("sync_devices", "app_name"),
    ("sync_devices", "platform"),
    ("sync_devices", "last_seen_at"),
    ("sync_devices", "pending_ops"),
    ("sync_devices", "failed_ops"),
    ("sync_devices", "last_sync_ok_at"),
    ("import_jobs", "hash_contract_version"),
    ("lot_shortfalls", "unit_cost"),
    ("lot_shortfalls", "reason"),
    ("lot_shortfalls", "created_at"),
    ("lot_shortfalls", "resolved_at"),
    ("stock_movement_lot_allocations", "expiry_date"),
]

# ⚠️  XARITALANMAGAN qo'shilgan ustunlar — ish vaqti ularni UMUMAN o'qimaydi/yozmaydi,
#     shuning uchun yiqilsa boot faqat o'tkazib yuboradi (tayyorlikka ta'sir yo'q).
#     `purchase_items.batch_no` eskirgan: `PurchaseItem` da atribut yo'q (partiya raqami
#     endi `StockBatch.batch_no`). Ro'yxat eskirmasligini qo'riqchi ham tekshiradi: bu
#     yerdagi ustun modelga ulansa — QIZIL (demak endi `REQUIRED_COLUMNS` ga ko'chadi).
UNMAPPED_ADDED_COLUMNS: frozenset[tuple[str, str]] = frozenset({
    ("purchase_items", "batch_no"),
})

# ⚠️  TIPI UUID BO'LISHI SHART bo'lgan ustunlar (Phase 5B.1). `_ADDED_COLUMNS` ularni
#     ilgari `VARCHAR` deb qo'shgan, model esa `UUID`. psycopg dialekti ORM taqqoslashini
#     `ustun = %(p)s::UUID` deb yozadi — varchar ustunda bu 42883 («operator does not exist:
#     character varying = uuid»): kassa harakati va QR to'lov dedup so'rovi HAR SAFAR
#     yiqiladi. Mavjudlik tekshiruvi (`_fatal`) buni KO'RMAYDI.
#     ⚠️  BOOT TIPNI O'ZGARTIRMAYDI (Phase 5C): mavjud ustun tipini almashtirish jadvalni
#         qayta yozadi (ACCESS EXCLUSIVE) va qiymatlar bo'yicha operator qarorini talab
#         qiladi. Boot faqat `column_type_problems` orqali tayyorlikni QIZIL qiladi va
#         `initdb._UUID_MIGRATION_HINT` ni chop etadi; tuzatish — ANIQ migratsiya
#         `app/db/migrations/` (CLI: `python -m app.tools.schema_migrate`).
UUID_TYPED_COLUMNS: list[tuple[str, str]] = [
    ("cash_movements", "client_uuid"),
    ("qr_payments", "sale_id"),
    ("qr_payments", "client_uuid"),
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
#
# ⚠️  JADVAL DOIRASIDA tekshiriladi (Phase 4A). Ilgari faqat `conname` qidirilardi
#     — BUTUN bazada shu nomli istalgan cheklov (boshqa jadvalda, boshqa turda)
#     «joyida» deb hisoblanardi. Postgres'da cheklov nomi JADVAL ichida noyob,
#     baza bo'yicha EMAS.
REQUIRED_PG_CONSTRAINTS: list[tuple[str, str]] = [
    # `track_expiry => track_lots` — ilova qatlamida majburlovchi kod YO'Q
    # (Phase 0 da bayroqlarni o'rnatadigan API ham yo'q), ya'ni bu CHECK
    # YAGONA himoya. Usiz muddat kuzatuvi partiyasiz yoqilishi mumkin bo'lardi
    # va muddat qaysi partiyaga tegishli ekani ANIQLANMAY qolardi.
    ("ck_track_expiry_implies_lots", "products"),
    # ── PHASE 4A: hodisa jadvallarining arifmetik qoidalari ─────────────────
    #  `variance = actual − provisional` — hisobotlar og'ishni shu ustundan
    #  yig'adi; qoida faqat kodda tursa, qo'lda tuzatilgan bitta qator P&L
    #  ayniyatini JIMGINA buzardi.
    ("ck_lsr_qty_pos", "lot_shortfall_resolutions"),
    ("ck_lsr_variance_identity", "lot_shortfall_resolutions"),
    ("ck_lsr_kind", "lot_shortfall_resolutions"),
    ("ck_lsr_netting_zero", "lot_shortfall_resolutions"),
    ("ck_risa_qty_pos", "return_item_shortfall_allocations"),
    ("ck_rira_qty_pos", "return_item_resolution_allocations"),
    #  Ortiqcha yopish — invariant uni MUSBAT ochiq qarz sifatida ko'rmaydi.
    ("ck_lot_shortfall_resolved_le_qty", "lot_shortfalls"),
]

# CHECK ta'riflari — `initdb._ensure_lot_checks` SHU yerdan quradi (model bilan
# AYNAN bir xil ifoda; ikki joyda yozilsa bir kun ajralib ketardi).
CHECK_DEFINITIONS: dict[str, str] = {
    "ck_track_expiry_implies_lots": "NOT track_expiry OR track_lots",
    "ck_lsr_qty_pos": "qty > 0",
    "ck_lsr_variance_identity": "variance = actual_cost - provisional_cost",
    "ck_lsr_kind": "kind IN ('real', 'netting')",
    "ck_lsr_netting_zero": "kind <> 'netting' OR variance = 0",
    "ck_risa_qty_pos": "qty > 0",
    "ck_rira_qty_pos": "qty > 0",
    "ck_lot_shortfall_resolved_le_qty": "resolved_qty <= qty",
}

# ⚠️  Faqat shular YO'Q bo'lsa boot TO'XTAYDI (Phase 3 dan meros xulq). Phase 4A
#     cheklovlari yo'qligi — TAYYOR EMAS sinfi: ularni qo'shish jadval qulfini talab
#     qiladi va rolling deploy'dagi band qulf boot'ni crash-loop'ga tushirmasligi kerak.
#     Himoya baribir yopiq: tayyorlik QIZIL, `/lots/enable` 409.
FATAL_PG_CONSTRAINTS = frozenset({"ck_track_expiry_implies_lots"})

# Eskirgan `(return_item_id, stock_batch_id)` noyobligi — oddiy (qisman/ifodaviy
# EMAS) noyob indekslar, ustunlar to'plami AYNAN shu ikkisi. Cheklovga bog'langan
# bo'lsa uning nomi ham qaytadi (DROP CONSTRAINT kerak, DROP INDEX emas).
_LEGACY_RET_ALLOC_UNIQUE_SQL = """
SELECT ic.relname, con.conname
FROM pg_index i
JOIN pg_class ic ON ic.oid = i.indexrelid
LEFT JOIN pg_constraint con ON con.conindid = i.indexrelid AND con.contype IN ('u', 'p')
WHERE i.indrelid = to_regclass('public.return_item_lot_allocations')
  AND i.indisunique AND i.indpred IS NULL AND i.indexprs IS NULL AND i.indnkeyatts = 2
  AND (SELECT array_agg(a.attname::text ORDER BY a.attname::text) FROM pg_attribute a
       WHERE a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey))
      = ARRAY['return_item_id', 'stock_batch_id']
ORDER BY ic.relname
"""

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
    # ── PHASE 3 ─────────────────────────────────────────────────────────────
    #  Bitta ombor harakati bitta partiyaga ATIGI BIR MARTA. Takroriy yuborishga
    #  qarshi YAGONA DB to'sig'i — usiz qayta yuborish partiyani IKKI marta
    #  kamaytirardi (`ux_alloc_item_lot` bilan bir xil sabab).
    ("ux_smove_alloc", "stock_movement_lot_allocations"),
    #  Phase 4A: (qaytarish qatori, SOTUV QATORI, partiya). Eski `ux_ret_alloc`
    #  ikki qatorli chekni qaytarishni bloklardi (initdb `_relax_ret_alloc_uniqueness`).
    ("ux_ret_alloc_line", "return_item_lot_allocations"),
    # ── PHASE 4A ────────────────────────────────────────────────────────────
    #  Yopish idempotentligining YAGONA tranzaksion kafolati: ayni `client_uuid`
    #  ikkinchi marta yozilmaydi. Usiz ikki bir vaqtdagi takror qarzni IKKI
    #  marta yopib, partiyani ortiqcha kamaytirardi.
    ("ux_lsr_request_client", "lot_shortfall_resolution_requests"),
    ("ux_lsr_request_lot", "lot_shortfall_resolutions"),
    #  Bitta qaytarish qatori bitta qarz / bitta hodisani ATIGI BIR MARTA qaytaradi.
    ("ux_risa_item_shortfall", "return_item_shortfall_allocations"),
    ("ux_rira_item_resolution", "return_item_resolution_allocations"),
    # ── PHASE 5D ────────────────────────────────────────────────────────────
    #  Qabulni tuzatish idempotentligining YAGONA tranzaksion kafolati: ayni
    #  `client_uuid` ikkinchi marta yozilmaydi. Usiz ikki bir vaqtdagi takror
    #  partiyani IKKI marta teskari qilib, qarzni va kassani ham ikki marta
    #  siljitardi (`services/lot_correction.py`).
    #
    #  ⚠️  `IDEMPOTENCY_INDEXES` GA HAM QO'SHILMAYDI, garchi u ham idempotentlik
    #      kaliti bo'lsa-da: `tests/test_runtime_columns.py::test_T4...` har boot
    #      indeksi AYNAN BITTA sinfda bo'lishini talab qiladi. Bu yerdagi
    #      ro'yxat KUCHLIROQ va ikkala maqsadni ham qoplaydi: `missing()` orqali
    #      `/health/ready` QIZIL bo'ladi VA `/lots/enable` (u `_rs.missing` ni
    #      o'qiydi) aktivatsiyani to'sadi — ya'ni «tayyorlik qizil + aktivatsiya
    #      yopiq» talabi bajariladi, ustiga Postgres'da boot ham to'xtaydi.
    ("ux_recv_corr_client", "receiving_corrections"),
    # ── PHASE 5F ────────────────────────────────────────────────────────────
    #  Hujjatga BITTA asl chek — ikki bir vaqtdagi «asl» yozuvga qarshi YAGONA DB
    #  to'sig'i. Pulga tegmaydi, lekin usiz asl/nusxa belgisi (chekdagi «NUSXA»
    #  banneri) yolg'on bo'lardi. Jadval YANGI — mavjud qatorlarda dublikat bo'lishi
    #  mumkin emas, shu bois indeks qurilishi yiqilmaydi va MAJBURIY qilish xavfsiz.
    ("ux_print_jobs_original", "print_jobs"),
]

# ⚠️  TEZLIK INDEKSLARI — tayyorlikka UMUMAN kirmaydi. Ular yo'qligida so'rov
#     sekinlashadi, lekin javob TO'G'RI qoladi. Ularni majburiy qilish ishlab
#     chiqarishni TEZLIK sababli abadiy boot-loop'ga tushirardi. Majburiy
#     ro'yxat faqat TO'G'RILIK bog'liqliklaridan iborat bo'lishi shart.
#     Bu ro'yxat faqat JURNAL diagnostikasi uchun (`performance_missing`).
PERFORMANCE_INDEXES: list[tuple[str, str]] = [
    ("ix_sale_items_sale_id", "sale_items"),
    ("ix_lot_fefo", "stock_batches"),
    ("ix_lot_expiry", "stock_batches"),
    ("ix_alloc_lot", "sale_item_lot_allocations"),
    ("ix_smove_alloc_lot", "stock_movement_lot_allocations"),
    ("ix_ret_alloc_item", "return_item_lot_allocations"),
    ("ix_lot_shortfall_open", "lot_shortfalls"),
    ("ix_lsr_company_resolved", "lot_shortfall_resolutions"),
    ("ix_lsr_shortfall", "lot_shortfall_resolutions"),
    ("ix_lsr_sale_item", "lot_shortfall_resolutions"),
    ("ix_rira_return", "return_item_resolution_allocations"),
    ("ix_rira_resolution", "return_item_resolution_allocations"),
    ("ix_risa_shortfall", "return_item_shortfall_allocations"),
    ("ix_risa_created_batch", "return_item_shortfall_allocations"),
    #  Hisobot indekslari (Phase 5B.1) — ilgari hech qaysi ro'yxatda yo'q edi, ya'ni
    #  qurilmay qolsa jurnalda ham ko'rinmasdi.
    ("ix_sales_company_sold", "sales"),
    ("ix_returns_company_created", "returns"),
    ("ix_stockmov_product_created", "stock_movements"),
    ("ix_stockmov_branch_created", "stock_movements"),
    ("ix_sales_branch_sold", "sales"),
    ("ix_sales_cashier_sold", "sales"),
    ("ix_sales_till_sold", "sales"),
    ("ix_sales_terminal_sold", "sales"),
    ("ix_sales_shift", "sales"),
    ("ix_returns_till", "returns"),
    ("ix_print_jobs_doc", "print_jobs"),        # Phase 5F — hujjat bo'yicha chop etish ro'yxati
]

# ══ IDEMPOTENTLIK INDEKSLARI (Phase 5B.1) — TAYYOR EMAS sinfi, boot FATAL EMAS ═══
#
# ⚠️  NEGA KERAK. Pul/qoldiq/auth yo'llari takroriy yuborishni SELECT-dedup bilan
#     tekshiradi, so'ng INSERT — klassik TOCTOU. Ikki bir vaqtdagi takror oynaga tushsa,
#     DB darajasidagi YAGONA to'siq shu noyob indekslar (IntegrityError ushlovchilari
#     ularni NOMMA-NOM tilga oladi): usiz offline sotuv / qaytarish / to'lov / kassa
#     harakati IKKI MARTA yoziladi, hisobdan chiqarish qoldiqni 2x kamaytiradi, bir
#     kassirda ikki ochiq smena, parolli login esa birinchi mos telefonni tanlaydi.
# ⚠️  NEGA FATAL EMAS. Ular JONLI, eski jadvallarda. Jadvalda allaqachon dublikat qator
#     bo'lsa `CREATE UNIQUE INDEX` 23505 bilan yiqiladi — buni faqat operator hal qiladi
#     (moliyaviy ma'lumot jarrohligi). FATAL bo'lganda production crash-loop'ga tushardi.
# ⚠️  NEGA `missing()` DA EMAS. `missing()` — `catalog_v2_schema`/`lot_schema_integrity`
#     tasnifining va `lot_policy.schema_problems` keshining manbai; bu yerdagi indekslar
#     o'sha tasnifni siljitmasin. Tayyorlikda ALOHIDA kalit: `idempotency_schema`.
# ⚠️  PHASE 5C: «aktivatsiyani to'smaydi» endi TO'G'RI EMAS. `/lots/enable` shu ro'yxatni
#     (va `column_type_problems` ni) ALOHIDA, keshsiz darvozada o'qiydi
#     (`lot_policy.activation_readiness`): yoqish qaytarib bo'lmaydi, undan keyin esa
#     mahsulot aynan shu indekslar himoyalaydigan pul/qoldiq yozuvlarini tug'diradi.
#     `missing()` ning O'ZI esa o'zgarmaydi — tasnif va boot qarori avvalgidek.
# ⚠️  «NOM BOR» YETMAYDI: Postgres'da indeks NOYOB, YAROQLI va TAYYOR bo'lishi shart.
#     Yiqilgan `CREATE UNIQUE INDEX CONCURRENTLY` AYNI nomli YAROQSIZ indeks qoldiradi —
#     u hech narsani to'smaydi, `_index` ning nom prechegi esa uni «bor» deb o'tkazadi.
IDEMPOTENCY_INDEXES: list[tuple[str, str]] = [
    ("ux_sales_company_client_uuid", "sales"),
    ("ux_returns_client_uuid", "returns"),
    ("ux_custpay_client_uuid", "customer_payments"),
    ("ux_suppay_client_uuid", "supplier_payments"),
    ("ux_purchases_client_uuid", "purchases"),
    ("ux_receivings_client_uuid", "receivings"),
    ("ux_cashmov_client_uuid", "cash_movements"),
    ("ux_stockmov_client_prod_type", "stock_movements"),
    ("ux_shifts_cashier_open", "shifts"),
    ("ux_companies_code", "companies"),
    ("ux_employees_phone_pw", "employees"),
]

# ⚠️  MA'LUMOT SIFATI noyobliklari — FAQAT JURNAL. Yo'qligida pul/qoldiq ikkilanmaydi:
#     ilova tekshiruvi (TOCTOU bo'lsa ham) dublikatlarning ko'pini to'sadi, qolgani —
#     master-yozuv dublikati. Izohlar ham tan oladi: mavjud dublikatli bazada qurilmaydi.
OPTIONAL_UNIQUE_INDEXES: list[tuple[str, str]] = [
    ("ux_products_company_plu", "products"),
    ("ux_barcodes_company_bc", "product_barcodes"),
    ("ux_settings_company_key", "settings"),
    ("ux_customers_client_uuid", "customers"),
    ("ux_employees_client_uuid", "employees"),
    ("ux_products_client_uuid", "products"),
    ("ux_branches_company_code", "branches"),
    ("ux_categories_company_name", "categories"),
    ("ux_customers_company_phone", "customers"),
]


# ══ MAJBURIY FOREIGN KEY'LAR (Phase 4A) ══════════════════════════════════════
#
# ⚠️  NEGA KERAK. Partiya jadvallarining ustunlari MAVJUD bazada `_ADDED_COLUMNS`
#     orqali `ALTER TABLE ... ADD COLUMN` bilan qo'shilgan — FK'SIZ. `create_all`
#     yangi bazada FK beradi, eski bazada esa bermaydi. Ya'ni bir xil kod ikki
#     muhitda HAR XIL yaxlitlik kafolatiga ega bo'lardi: staging'da yetim
#     taqsimot qatori yozilib qolishi mumkin edi, test bazasida esa yo'q.
#
# ⚠️  «NOM BOR» YETMAYDI — SHAKL tekshiriladi: jadval, ustunlar TARTIBI, ota
#     jadval va ustunlari, ON DELETE, ON UPDATE (NO ACTION), MATCH SIMPLE,
#     DEFERRABLE emas, TASDIQLANGAN va (PG18+) MAJBURLANGAN.

# pg_constraint.confdeltype: a=NO ACTION, c=CASCADE
_NO_ACTION, _CASCADE = "a", "c"


@dataclass(frozen=True)
class RequiredFK:
    child: str
    cols: tuple[str, ...]
    parent: str
    refcols: tuple[str, ...] = ("id",)
    on_delete: str = _NO_ACTION

    @property
    def label(self) -> str:
        return (f"{self.child}({', '.join(self.cols)}) -> "
                f"{self.parent}({', '.join(self.refcols)})")


def _fk(child, col, parent, on_delete=_NO_ACTION):
    return RequiredFK(child, (col,), parent, ("id",), on_delete)


REQUIRED_FOREIGN_KEYS: list[RequiredFK] = [
    _fk("stock_batches", "company_id", "companies"),
    _fk("stock_batches", "product_id", "products"),
    _fk("stock_batches", "branch_id", "branches"),
    _fk("stock_batches", "purchase_item_id", "purchase_items"),
    _fk("stock_batches", "supplier_id", "suppliers"),
    _fk("sale_item_lot_allocations", "company_id", "companies"),
    _fk("sale_item_lot_allocations", "sale_item_id", "sale_items", _CASCADE),
    _fk("sale_item_lot_allocations", "stock_batch_id", "stock_batches"),
    _fk("sale_item_lot_allocations", "product_id", "products"),
    _fk("return_item_lot_allocations", "company_id", "companies"),
    _fk("return_item_lot_allocations", "return_item_id", "return_items", _CASCADE),
    _fk("return_item_lot_allocations", "sale_item_id", "sale_items"),
    _fk("return_item_lot_allocations", "stock_batch_id", "stock_batches"),
    _fk("return_item_lot_allocations", "product_id", "products"),
    _fk("stock_movement_lot_allocations", "company_id", "companies"),
    _fk("stock_movement_lot_allocations", "stock_movement_id", "stock_movements", _CASCADE),
    _fk("stock_movement_lot_allocations", "stock_batch_id", "stock_batches"),
    _fk("stock_movement_lot_allocations", "product_id", "products"),
    _fk("lot_shortfalls", "company_id", "companies"),
    _fk("lot_shortfalls", "branch_id", "branches"),
    _fk("lot_shortfalls", "product_id", "products"),
    _fk("lot_shortfalls", "sale_item_id", "sale_items", _CASCADE),
    _fk("lot_shortfall_resolution_requests", "company_id", "companies"),
    _fk("lot_shortfall_resolution_requests", "shortfall_id", "lot_shortfalls"),
    _fk("lot_shortfall_resolution_requests", "employee_id", "employees"),
    _fk("lot_shortfall_resolutions", "request_id", "lot_shortfall_resolution_requests"),
    _fk("lot_shortfall_resolutions", "company_id", "companies"),
    _fk("lot_shortfall_resolutions", "branch_id", "branches"),
    _fk("lot_shortfall_resolutions", "product_id", "products"),
    _fk("lot_shortfall_resolutions", "shortfall_id", "lot_shortfalls"),
    _fk("lot_shortfall_resolutions", "sale_item_id", "sale_items"),
    _fk("lot_shortfall_resolutions", "stock_batch_id", "stock_batches"),
    _fk("lot_shortfall_resolutions", "employee_id", "employees"),
    _fk("return_item_shortfall_allocations", "company_id", "companies"),
    _fk("return_item_shortfall_allocations", "return_id", "returns"),
    _fk("return_item_shortfall_allocations", "return_item_id", "return_items"),
    _fk("return_item_shortfall_allocations", "shortfall_id", "lot_shortfalls"),
    _fk("return_item_shortfall_allocations", "created_batch_id", "stock_batches"),
    _fk("return_item_shortfall_allocations", "product_id", "products"),
    _fk("return_item_shortfall_allocations", "branch_id", "branches"),
    _fk("return_item_resolution_allocations", "company_id", "companies"),
    _fk("return_item_resolution_allocations", "return_id", "returns"),
    _fk("return_item_resolution_allocations", "return_item_id", "return_items"),
    _fk("return_item_resolution_allocations", "resolution_id", "lot_shortfall_resolutions"),
    _fk("return_item_resolution_allocations", "sale_item_id", "sale_items"),
    _fk("return_item_resolution_allocations", "stock_batch_id", "stock_batches"),
    _fk("return_item_resolution_allocations", "product_id", "products"),
    _fk("return_item_resolution_allocations", "branch_id", "branches"),
]

# Model qaysi jadvallar uchun FK ro'yxatini TO'LIQ berishi shart (qo'riqchi test).
FK_GUARDED_TABLES = frozenset(fk.child for fk in REQUIRED_FOREIGN_KEYS)

FK_OK = "ok"
FK_MISSING = "yo'q"
FK_NOT_VALID = "tasdiqlanmagan"
FK_NOT_ENFORCED = "majburlanmagan"
FK_WRONG = "shakli noto'g'ri"

_FK_SQL = """
SELECT ch.relname, pa.relname, c.conname,
       ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
             ORDER BY k.ord),
       ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum
             ORDER BY k.ord),
       c.confdeltype, c.confupdtype, c.confmatchtype, c.condeferrable, c.convalidated,
       COALESCE((to_jsonb(c) ->> 'conenforced')::boolean, true),
       COALESCE((to_jsonb(c) ->> 'conperiod')::boolean, false)
FROM pg_constraint c
JOIN pg_class ch     ON ch.oid = c.conrelid
JOIN pg_namespace n  ON n.oid = ch.relnamespace
JOIN pg_class pa     ON pa.oid = c.confrelid
JOIN pg_namespace pn ON pn.oid = pa.relnamespace
WHERE c.contype = 'f' AND n.nspname = 'public' AND pn.nspname = 'public'
  AND ch.relname = ANY(:t)
"""


def _is_pg(bind) -> bool:
    try:
        return bind.dialect.name == "postgresql"
    except Exception:      # noqa: BLE001
        return False


@contextmanager
def _con_of(bind):
    """Engine YOKI Connection — introspeksiya ikkalasida ham ISHLASHI shart.

    ⚠️  ILGARI FAQAT ENGINE. Har tekshiruv `bind.connect()` chaqirardi; `Connection`
        da bu `AttributeError` beradi va u «o'qib bo'lmadi» soxta muammosiga
        aylanardi. Fail-CLOSED bo'lgani uchun xavfsiz, LEKIN aktivatsiya darvozasi
        (`/lots/enable` -> `missing()`/`activation_readiness()`) ochiq tranzaksiyaga
        bog'langan sessiyada HAR DOIM 409 berardi — sabab esa «4 ta FK/cheklov tayyor
        emas», ya'ni operatorga YOLG'ON. Sessiya Connection'ga bog'langan har yo'l
        (sinovlar, staging smoke, kelajakdagi so'rov-tranzaksiyasi) shu tuzoqqa
        tushardi. Endi mavjud ulanish QAYTA ISHLATILADI (yangi ulanish ochilmaydi,
        ochiq tranzaksiya buzilmaydi).
    """
    if isinstance(bind, Connection):
        yield bind
    else:
        with bind.connect() as con:
            yield con


def legacy_ret_alloc_uniques(con) -> list[tuple[str, str | None]]:
    """[(indeks nomi, cheklov nomi | None)] — eskirgan qaytarish noyobligi (Postgres)."""
    from sqlalchemy import text as _t
    return [(r[0], r[1]) for r in con.execute(_t(_LEGACY_RET_ALLOC_UNIQUE_SQL)).fetchall()]


def index_valid(con, name: str) -> bool:
    from sqlalchemy import text as _t
    return bool(con.execute(_t(
        "SELECT i.indisvalid AND i.indisready FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = :n"), {"n": name}).scalar())


def fk_rows(con) -> list[dict]:
    """Qo'riqlanadigan jadvallardagi BARCHA FK'lar — bitta so'rov bilan.

    ⚠️  `conenforced` (NOT ENFORCED FK) va `conperiod` (temporal FK) FAQAT
        PostgreSQL 18+ da bor. So'rov matnida ustunni NOMI bilan yozish PG16 da
        (pgserver sinovlari) so'rovni tahlil paytidayoq YIQITARDI — hatto
        `CASE WHEN version >= 18` ichida ham. `to_jsonb(c)` qatorni kalit-qiymat
        sifatida beradi: ustun yo'q bo'lsa NULL, ya'ni bitta matn ikkala
        versiyada ham ishlaydi.
    """
    from sqlalchemy import text as _t
    out = []
    for r in con.execute(_t(_FK_SQL), {"t": sorted(FK_GUARDED_TABLES)}).fetchall():
        out.append({"child": r[0], "parent": r[1], "name": r[2],
                    "cols": tuple(r[3] or ()), "refcols": tuple(r[4] or ()),
                    "deltype": r[5], "updtype": r[6], "matchtype": r[7],
                    "deferrable": bool(r[8]), "validated": bool(r[9]),
                    "enforced": bool(r[10]), "period": bool(r[11])})
    return out


def classify_fk(fk: RequiredFK, rows: list[dict]) -> tuple[str, list[str]]:
    """(holat, AYNAN shu shakldagi cheklov nomlari)."""
    same = [r for r in rows
            if r["child"] == fk.child and r["parent"] == fk.parent
            and r["cols"] == fk.cols and r["refcols"] == fk.refcols]
    if not same:
        return FK_MISSING, []
    exact = [r for r in same
             if r["deltype"] == fk.on_delete and r["updtype"] == _NO_ACTION
             and r["matchtype"] == "s" and not r["deferrable"] and not r["period"]]
    if any(r["validated"] and r["enforced"] for r in exact):
        return FK_OK, [r["name"] for r in exact if r["validated"] and r["enforced"]]
    if any(r["enforced"] and not r["validated"] for r in exact):
        return FK_NOT_VALID, [r["name"] for r in exact if r["enforced"] and not r["validated"]]
    if any(not r["enforced"] for r in exact):
        return FK_NOT_ENFORCED, [r["name"] for r in exact if not r["enforced"]]
    return FK_WRONG, [r["name"] for r in same]


def fk_states(bind) -> dict[RequiredFK, tuple[str, list[str]]]:
    """Har majburiy FK uchun (holat, nomlar). Faqat Postgres; SQLite'da bo'sh."""
    if not _is_pg(bind):
        return {}
    with _con_of(bind) as con:
        rows = fk_rows(con)
    return {fk: classify_fk(fk, rows) for fk in REQUIRED_FOREIGN_KEYS}


def enforced(bind) -> bool:
    """Yetishmovchilik ISHGA TUSHISHNI to'xtatadigan muhitmi.

    Postgres = production/staging. SQLite dev/test/e2e uchun ataylab yumshoq:
    u yerda ham obyektlar yaratiladi, lekin yo'qligi ishni to'xtatmaydi.
    """
    return _is_pg(bind)


def _fatal(bind) -> list[str]:
    """HALOKATLI yetishmovchilik: ustun / noyob indeks / CHECK UMUMAN yo'q."""
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

    if _is_pg(bind) and REQUIRED_PG_CONSTRAINTS:
        try:
            have = _check_exists(bind)       # FAQAT mavjudlik — tahlil boot'ni yiqitmasin
        except Exception as e:      # noqa: BLE001
            print(f"[schema] cheklovlarni o'qib bo'lmadi: {e}")
            out.append("cheklovlarni o'qib bo'lmadi")
            return out
        for name, table in REQUIRED_PG_CONSTRAINTS:
            if name in FATAL_PG_CONSTRAINTS and (name, table) not in have:
                out.append(f"cheklov yo'q: {name} ({table})")
    # dedup, tartib saqlanadi (bir jadval bir necha ustun uchun «yo'q» chiqmasin)
    return list(dict.fromkeys(out))


# ── CHECK TA'RIFI (Phase 4A.1) ────────────────────────────────────────────────
# ⚠️  NOM VA JADVAL YETMAYDI. Ayni nomli, lekin boshqa ifodali cheklov (`CHECK (true)`,
#     `qty >= 0` ...) yoki PG18 dagi `NOT ENFORCED` cheklov ilgari «joyida» deb
#     o'tardi — himoya yo'q, tayyorlik YASHIL. Endi uch narsa ALOHIDA tekshiriladi:
#       · ta'rif — `check_canon` bilan TUZILMA bo'yicha (Postgres qayta yozishiga
#         chidamli, qavs/NOT joyiga sezgir);
#       · majburlanganmi — `conenforced` (PG18+; eski versiyada ustun yo'q = true);
#       · tasdiqlanganmi — `convalidated`.
#     Katalog MATNI hech qachon javobga chiqmaydi (`missing()` izohiga qarang) —
#     faqat shu fayldagi nom va jadval.
CHECK_DEF_OK = "ok"
CHECK_DEF_WRONG = "noto'g'ri"
CHECK_DEF_UNPARSED = "tahlil qilinmadi"


@dataclass(frozen=True)
class CheckState:
    validated: bool
    enforced: bool
    definition: str        # CHECK_DEF_OK | CHECK_DEF_WRONG | CHECK_DEF_UNPARSED


def check_definition_state(name: str, catalog_expr: str | None, text_columns=()) -> str:
    """Katalogdagi ifoda (`pg_get_expr(conbin, conrelid)`) kutilganmi.

    `text_columns` — jadvalning HAQIQIY tipi text/varchar bo'lgan ustunlari: faqat ular
    uchun `::text` keltirish ma'nosiz (raqamli ustunda u satr taqqoslashiga aylanadi).

    Tahlil qilib bo'lmasa — `CHECK_DEF_UNPARSED`: bu «noto'g'ri» EMAS (avtomatik
    qayta yaratilmaydi), lekin tayyorlik baribir QIZIL.

    ⚠️  HAR QANDAY istisno UNPARSED (review): kanonizatordagi kutilmagan xato
        (RecursionError va h.k.) `_fatal` orqali boot'ni crash-loop'ga tushirmasin.
    """
    from app.core.check_canon import same_check
    if not catalog_expr:
        return CHECK_DEF_UNPARSED
    try:
        return CHECK_DEF_OK if same_check(CHECK_DEFINITIONS[name], catalog_expr,
                                          text_columns=text_columns) \
            else CHECK_DEF_WRONG
    except Exception:      # noqa: BLE001 — CanonError va boshqalar: «tekshirib bo'lmadi»
        return CHECK_DEF_UNPARSED


# Jadvalning matn tipidagi ustunlari — ayni so'rovda, katalogdan (model emas: baza haqiqati).
_TEXT_COLUMNS_SQL = (
    "ARRAY(SELECT a.attname::text FROM pg_attribute a "
    "      WHERE a.attrelid = c.conrelid AND a.attnum > 0 AND NOT a.attisdropped "
    "        AND a.atttypid IN ('text'::regtype, 'varchar'::regtype))"
)

CHECK_STATE_SQL = (
    "SELECT c.conname, ch.relname, c.convalidated, "
    "       COALESCE((to_jsonb(c) ->> 'conenforced')::boolean, true), "
    "       pg_get_expr(c.conbin, c.conrelid), "
    f"      {_TEXT_COLUMNS_SQL} "
    "FROM pg_constraint c "
    "JOIN pg_class ch ON ch.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = ch.relnamespace "
    "WHERE c.contype = 'c' AND n.nspname = 'public' AND c.conname = ANY(:n)"
)


def _check_rows(bind) -> dict[tuple[str, str], CheckState]:
    """{(nom, jadval): CheckState} — faqat `public` dagi, MAJBURIY (nom, jadval) juftlari.

    ⚠️  Boshqa jadvaldagi ayni nomli CHECK TAHLIL QILINMAYDI: tayyorlikka aloqasi yo'q
        katalog matni hech narsaga ta'sir qilmasin.
    """
    from sqlalchemy import text as _t
    wanted = set(REQUIRED_PG_CONSTRAINTS)
    with _con_of(bind) as con:
        rows = con.execute(_t(CHECK_STATE_SQL),
                           {"n": [c for c, _ in REQUIRED_PG_CONSTRAINTS]}).fetchall()
    return {(r[0], r[1]): CheckState(bool(r[2]), bool(r[3]),
                                     check_definition_state(r[0], r[4], frozenset(r[5] or ())))
            for r in rows if (r[0], r[1]) in wanted}


def _check_exists(bind) -> set[tuple[str, str]]:
    """Majburiy CHECK'lar MAVJUDLIGI — hech narsa tahlil qilinmaydi (`_fatal` uchun).

    Halokatli qaror FAQAT mavjudlikka tayanadi: ta'rif muammosi har doim soft.
    """
    from sqlalchemy import text as _t
    with _con_of(bind) as con:
        rows = con.execute(_t(
            "SELECT c.conname, ch.relname FROM pg_constraint c "
            "JOIN pg_class ch ON ch.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = ch.relnamespace "
            "WHERE c.contype = 'c' AND n.nspname = 'public' AND c.conname = ANY(:n)"
        ), {"n": [c for c, _ in REQUIRED_PG_CONSTRAINTS]}).fetchall()
    return {(r[0], r[1]) for r in rows}


def check_problems(name: str, table: str, st: CheckState) -> list[str]:
    """Mavjud cheklovning TAYYOR-EMAS sabablari (bo'sh = joyida va to'g'ri)."""
    out: list[str] = []
    if st.definition == CHECK_DEF_WRONG:
        out.append(f"cheklov ta'rifi noto'g'ri: {name} ({table})")
    elif st.definition == CHECK_DEF_UNPARSED:
        out.append(f"cheklov ta'rifini tekshirib bo'lmadi: {name} ({table})")
    if not st.enforced:
        out.append(f"cheklov majburlanmagan: {name} ({table})")
    if not st.validated:
        out.append(f"cheklov tasdiqlanmagan: {name} ({table})")
    return out


def soft_missing(bind) -> list[str]:
    """TAYYOR EMAS, lekin boot'ni YIQITMAYDI: FK holatlari, CHECK ta'rifi/majburi/tasdig'i."""
    if not _is_pg(bind):
        return []
    out: list[str] = []
    try:
        for fk, (state, _names) in fk_states(bind).items():
            if state != FK_OK:
                out.append(f"FK {state}: {fk.label}")
    except Exception as e:      # noqa: BLE001
        print(f"[schema] FK'larni o'qib bo'lmadi: {e}")
        out.append("FK'larni o'qib bo'lmadi")
    try:
        have = _check_rows(bind)
        for name, table in REQUIRED_PG_CONSTRAINTS:
            st = have.get((name, table))
            if st is None:
                # Halokatli CHECK yo'qligi `_fatal` da; bu yerda faqat Phase 4A lari.
                if name not in FATAL_PG_CONSTRAINTS:
                    out.append(f"lot cheklov yo'q: {name} ({table})")
                continue
            out.extend(check_problems(name, table, st))
    except Exception as e:      # noqa: BLE001
        print(f"[schema] cheklov tasdig'ini o'qib bo'lmadi: {e}")
        out.append("cheklov tasdig'ini o'qib bo'lmadi")
    try:
        with _con_of(bind) as con:
            if legacy_ret_alloc_uniques(con):
                out.append("eskirgan noyoblik: return_item_lot_allocations"
                           "(return_item_id, stock_batch_id)")
    except Exception as e:      # noqa: BLE001
        print(f"[schema] qaytarish noyobligini o'qib bo'lmadi: {e}")
        out.append("eskirgan noyoblikni o'qib bo'lmadi")
    return out


# ⚠️  YANGI soft xabar qo'shilsa — prefiksi SHU YERGA ham. Aks holda `/health/ready`
#     uni «V2 ob'ekt yo'q» deb sanaydi va `lot_schema_integrity` JIMGINA yashil qoladi
#     (`tests/test_check_canon.py::test_tayyorlik_XABARLARI_hammasi_SOFT_sinfida`).
_SOFT_PREFIXES = ("FK ", "FK'larni o'qib bo'lmadi", "cheklov tasdiqlanmagan:",
                  "cheklov ta'rifi noto'g'ri:", "cheklov ta'rifini tekshirib bo'lmadi:",
                  "cheklov majburlanmagan:",
                  "cheklov tasdig'ini o'qib bo'lmadi", "lot cheklov yo'q:",
                  "eskirgan noyoblik", "eskirgan noyoblikni o'qib bo'lmadi")


def is_soft(item: str) -> bool:
    """`missing()` satri TAYYOR-EMAS sinfidanmi (boot yiqilmaydi) — aks holda halokatli."""
    return item.startswith(_SOFT_PREFIXES)


def fatal_missing(bind) -> list[str]:
    """Boot FATAL qarori FAQAT shunga tayanadi (FK holatlari KIRMAYDI)."""
    return _fatal(bind)


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
    out = _fatal(bind)
    if out == ["introspeksiya yiqildi"]:
        return out
    return out + soft_missing(bind)


def performance_missing(bind) -> list[str]:
    """TEZLIK indekslaridan yo'qlari (yoki Postgres'da YAROQSIZ qolganlari).

    Tayyorlikka TA'SIR QILMAYDI — faqat jurnal uchun.
    """
    out: list[str] = []
    try:
        if _is_pg(bind):
            from sqlalchemy import text as _t
            with _con_of(bind) as con:
                rows = con.execute(_t(
                    "SELECT c.relname, t.relname, i.indisvalid AND i.indisready "
                    "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "JOIN pg_class t ON t.oid = i.indrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = ANY(:n)"),
                    {"n": [n for n, _ in PERFORMANCE_INDEXES]}).fetchall()
            have = {(r[0], r[1]): bool(r[2]) for r in rows}
            for name, table in PERFORMANCE_INDEXES:
                v = have.get((name, table))
                if v is None:
                    out.append(f"tezlik indeksi yo'q: {name}")
                elif v is False:
                    out.append(f"tezlik indeksi yaroqsiz: {name}")
        else:
            insp = inspect(bind)
            tables = set(insp.get_table_names())
            for name, table in PERFORMANCE_INDEXES:
                if table not in tables or name not in {
                        i["name"] for i in insp.get_indexes(table)}:
                    out.append(f"tezlik indeksi yo'q: {name}")
    except Exception as e:      # noqa: BLE001
        print(f"[perf] tezlik indekslarini o'qib bo'lmadi: {e}")
    return out


IX_OK = "ok"
IX_NOT_UNIQUE = "noyob emas"
IX_INVALID = "yaroqsiz"

_UNIQUE_INDEX_SQL = (
    "SELECT c.relname, t.relname, i.indisunique, i.indisvalid AND i.indisready "
    "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_class t ON t.oid = i.indrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relname = ANY(:n)"
)


def _unique_index_states(bind, pairs) -> dict[tuple[str, str], str]:
    """{(indeks, jadval): IX_*} — faqat TOPILGAN juftliklar (yo'q = kalit yo'q).

    JADVAL DOIRASIDA: boshqa jadvaldagi ayni nomli indeks hisobga olinmaydi.
    Postgres — `pg_index` (noyob + yaroqli + tayyor); SQLite — `PRAGMA index_list`
    (yaroqsiz indeks tushunchasi yo'q; ifodaviy indeks ham ko'rinadi, inspector esa
    uni tashlab yuborardi). Faqat katalog o'qiladi — jadvalga qulf YO'Q.
    """
    from sqlalchemy import text as _t
    wanted = set(pairs)
    out: dict[tuple[str, str], str] = {}
    with _con_of(bind) as con:
        if _is_pg(bind):
            for name, table, unique, valid in con.execute(
                    _t(_UNIQUE_INDEX_SQL), {"n": sorted({n for n, _ in pairs})}).fetchall():
                if (name, table) in wanted:
                    out[(name, table)] = (IX_NOT_UNIQUE if not unique
                                          else IX_OK if valid else IX_INVALID)
        else:
            for table in sorted({t for _, t in pairs}):
                # (seq, name, unique, origin, partial); jadval yo'q -> bo'sh
                for row in con.exec_driver_sql(f'PRAGMA index_list("{table}")').fetchall():
                    if (row[1], table) in wanted:
                        out[(row[1], table)] = IX_OK if row[2] else IX_NOT_UNIQUE
    return out


def idempotency_missing(bind) -> list[str]:
    """IDEMPOTENTLIK indekslaridan yo'q / noyob emas / yaroqsizlari — TAYYOR EMAS sinfi.

    Boot'ni YIQITMAYDI va `missing()` ga KIRMAYDI (`IDEMPOTENCY_INDEXES` izohi).
    ⚠️  Satrlar OMMAVIY (`/health/ready`): faqat shu fayldagi o'zgarmas nomlar; xato
        matni (`str(e)`) faqat JURNALGA (`missing()` izohi bilan ayni qoida).
    """
    try:
        have = _unique_index_states(bind, IDEMPOTENCY_INDEXES)
    except Exception as e:      # noqa: BLE001
        print(f"[schema] idempotentlik indekslarini o'qib bo'lmadi: {e}")
        return ["idempotentlik indekslarini o'qib bo'lmadi"]
    out: list[str] = []
    for name, table in IDEMPOTENCY_INDEXES:
        st = have.get((name, table))
        if st is None:
            out.append(f"idempotentlik indeksi yo'q: {name} ({table})")
        elif st != IX_OK:
            out.append(f"idempotentlik indeksi {st}: {name} ({table})")
    return out


def optional_unique_missing(bind) -> list[str]:
    """Ma'lumot sifati noyobliklaridan yo'qlari — FAQAT JURNAL (tayyorlikka ta'sir yo'q)."""
    try:
        have = _unique_index_states(bind, OPTIONAL_UNIQUE_INDEXES)
    except Exception as e:      # noqa: BLE001
        print(f"[integrity] noyoblik indekslarini o'qib bo'lmadi: {e}")
        return []
    out: list[str] = []
    for name, table in OPTIONAL_UNIQUE_INDEXES:
        st = have.get((name, table))
        if st != IX_OK:
            label = st or "yo'q"
            out.append(f"noyoblik indeksi {label}: {name} ({table})")
    return out


_UUID_COLUMN_TYPES_SQL = (
    "SELECT c.relname, a.attname, ty.typname "
    "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_type ty ON ty.oid = a.atttypid "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND a.attnum > 0 "
    "AND NOT a.attisdropped AND c.relname = ANY(:t) AND a.attname = ANY(:c)"
)


def uuid_column_types(con) -> dict[tuple[str, str], str]:
    """{(jadval, ustun): pg tip nomi} — `UUID_TYPED_COLUMNS` dan MAVJUDLARI (Postgres).

    QULFSIZ: faqat `pg_attribute`/`pg_class`/`pg_type` katalogi — jadvalga qulf olinmaydi,
    ya'ni barqaror boot jonli yozuvchi bilan to'qnashmaydi.
    """
    from sqlalchemy import text as _t
    wanted = set(UUID_TYPED_COLUMNS)
    rows = con.execute(_t(_UUID_COLUMN_TYPES_SQL),
                       {"t": sorted({t for t, _ in UUID_TYPED_COLUMNS}),
                        "c": sorted({c for _, c in UUID_TYPED_COLUMNS})}).fetchall()
    return {(r[0], r[1]): r[2] for r in rows if (r[0], r[1]) in wanted}


def column_type_problems(bind) -> list[str]:
    """`UUID_TYPED_COLUMNS` dan tipi uuid BO'LMAGANLARI — TAYYOR EMAS (boot FATAL emas).

    Ustun umuman yo'qligi bu yerda emas — u `_fatal` da (majburiy ustun). SQLite'da
    tip og'ishi yo'q (UUID har ikki yo'lda matn), shuning uchun bo'sh.
    ⚠️  Satrlar OMMAVIY — faqat o'zgarmas nomlar; bazadagi tip nomi ham chiqmaydi.
    """
    if not _is_pg(bind):
        return []
    try:
        with _con_of(bind) as con:
            have = uuid_column_types(con)
    except Exception as e:      # noqa: BLE001
        print(f"[schema] ustun tiplarini o'qib bo'lmadi: {e}")
        return ["ustun tiplarini o'qib bo'lmadi"]
    return [f"ustun tipi uuid emas: {t}.{c}" for t, c in UUID_TYPED_COLUMNS
            if have.get((t, c)) not in (None, "uuid")]


def ok(bind) -> tuple[bool, list[str]]:
    """(hammasi_joyidami, yetishmayotganlar). Tekshiruv HAR DOIM bajariladi —
    dialektdan qat'i nazar; `enforced()` faqat YIQILISH qaroriga ta'sir qiladi."""
    m = missing(bind)
    return (not m), m
