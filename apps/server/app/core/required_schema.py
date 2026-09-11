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
]

# (indeks, jadval) — `initdb._ensure_indexes` bilan IZCHIL bo'lishi shart.
REQUIRED_INDEXES: list[tuple[str, str]] = [
    ("ux_products_external_identity", "products"),
    ("ux_import_jobs_snapshot", "import_jobs"),
    ("ux_movements_cutover_key", "stock_movements"),
]


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
    return out


def ok(bind) -> tuple[bool, list[str]]:
    """(hammasi_joyidami, yetishmayotganlar). Tekshiruv HAR DOIM bajariladi —
    dialektdan qat'i nazar; `enforced()` faqat YIQILISH qaroriga ta'sir qiladi."""
    m = missing(bind)
    return (not m), m
