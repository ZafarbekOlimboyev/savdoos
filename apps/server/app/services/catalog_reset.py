# -*- coding: utf-8 -*-
"""1С Cutover V2 — TENANT DOIRASIDAGI KATALOG RESETI (dry-run + darvozalar).

⚠️  TO'LIQ BAZANI TIKLASH BU YERDA ISHLATILMAYDI. Backup/restore — FALOKATDAN
    TIKLASH vositasi; u butun bazani (barcha do'konlar, xodimlar, kassa) orqaga
    suradi. Demo katalogni tozalash BITTA do'kon doirasida bo'lishi shart.

⚠️  BAJARISH FUNKSIYA-DARVOZA ORTIDA. `execute()` faqat APP_ENV dev/test/staging
    bo'lganda ishlaydi. Production'da u XATO qaytaradi — Phase 1 da bajarish
    YOQILMAYDI.

FK GRAFI PRODUCTION'DAN OLINGAN (taxmin emas):

  products <- product_barcodes   ON DELETE CASCADE   (avtomatik)
           <- product_prices     ON DELETE CASCADE   (avtomatik)
           <- inventory          NO ACTION           -> qo'lda
           <- stock_movements    NO ACTION           -> qo'lda
           <- stock_batches      NO ACTION           -> qo'lda
           <- import_rows        NO ACTION           -> qo'lda
           <- sale_items         NO ACTION           -> 0 BO'LISHI SHART
           <- purchase_items     NO ACTION           -> 0 BO'LISHI SHART
           <- return_items       NO ACTION           -> 0 BO'LISHI SHART
  stock_batches <- stock_movements, purchase_items   -> batches ULARDAN KEYIN

  inventory / stock_movements / stock_batches / product_prices / import_rows da
  `company_id` ustuni YO'Q — ular FAQAT product_id orqali doiralanadi. Har DELETE
  shu bois `product_id IN (SELECT id FROM products WHERE company_id = :tenant)`
  bilan chegaralanadi.

HECH QACHON TEGILMAYDI:
  units (GLOBAL — 4 qator, barcha do'konlar uchun umumiy, sale_items ham havola
  qiladi) · companies · branches · employees · roles/permissions · tills/safes ·
  butun `cash` sxemasi · auth/xavfsizlik yozuvlari ·
  settings ning `cash` / `plan` / `store_info` / `security` kalitlari.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.db.types import UUID as AppUUID

# Reset MUMKIN EMAS, agar shulardan birortasi mavjud bo'lsa (fail-closed).
BLOCKERS = [
    ("sales", "SELECT count(*) FROM sales WHERE company_id = :c"),
    ("sale_items", "SELECT count(*) FROM sale_items si JOIN sales s ON s.id = si.sale_id "
                   "WHERE s.company_id = :c"),
    ("shifts", "SELECT count(*) FROM shifts s JOIN branches b ON b.id = s.branch_id "
               "WHERE b.company_id = :c"),
    ("purchases", "SELECT count(*) FROM purchases WHERE company_id = :c"),
    ("purchase_items", "SELECT count(*) FROM purchase_items pi JOIN purchases p "
                       "ON p.id = pi.purchase_id WHERE p.company_id = :c"),
    ("purchase_returns", "SELECT count(*) FROM purchase_returns WHERE company_id = :c"),
    ("receivings", "SELECT count(*) FROM receivings WHERE company_id = :c"),
    ("returns", "SELECT count(*) FROM returns WHERE company_id = :c"),
    ("return_items", "SELECT count(*) FROM return_items ri JOIN returns r "
                     "ON r.id = ri.return_id WHERE r.company_id = :c"),
    ("stock_batches", "SELECT count(*) FROM stock_batches b JOIN products p "
                      "ON p.id = b.product_id WHERE p.company_id = :c"),
    # Phase 2: sotuv ulushlari ENDI haqiqiy biznes ma'lumoti — chek qaysi
    # partiyadan yeganini AYNAN shu jadval saqlaydi (qaytarish izi shunga tayanadi).
    # ⚠️  `sales`/`sale_items` allaqachon bloklaydi, ya'ni bu qator BUGUN ortiqcha
    #     ko'rinadi. Ataylab qo'shildi: kimdir keyinchalik sotuv blokerini
    #     yumshatsa, izlanish zanjiri JIMGINA o'chib ketmasin.
    ("lot_shortfalls",
     "SELECT count(*) FROM lot_shortfalls s JOIN products p "
     "ON p.id = s.product_id WHERE p.company_id = :c"),
    ("sale_item_lot_allocations",
     "SELECT count(*) FROM sale_item_lot_allocations a JOIN products p "
     "ON p.id = a.product_id WHERE p.company_id = :c"),
    ("cash_ledger_entries", "SELECT count(*) FROM cash.cash_ledger_entries WHERE tenant_id = :c"),
    ("reconciliation_records", "SELECT count(*) FROM cash.reconciliation_records WHERE tenant_id = :c"),
]

# `products` ga havola qiluvchi va reset REJASIDA hisobga OLINGAN jadvallar.
# Bazada bulardan TASHQARI havola topilsa — reset FAIL-CLOSED rad etiladi
# (sxema o'sgan, reja eskirgan; jim ma'lumot qoldirib ketmaymiz).
KNOWN_PRODUCT_REFERRERS = {
    "product_barcodes", "product_prices", "inventory", "stock_movements",
    "stock_batches", "sale_item_lot_allocations", "lot_shortfalls",
    "import_rows", "sale_items", "purchase_items", "return_items",
}

# O'CHIRISH TARTIBI — bolalardan otaga. Har biri tenant doirasida.
DELETE_PLAN = [
    ("stock_movements",
     "DELETE FROM stock_movements WHERE product_id IN "
     "(SELECT id FROM products WHERE company_id = :c)"),
    # ⚠️  TARTIB: taqsimotlar partiyalarga FK bilan havola qiladi, shu bois ular
    #     partiyalardan OLDIN o'chiriladi.
    ("lot_shortfalls",
     "DELETE FROM lot_shortfalls WHERE product_id IN "
     "(SELECT id FROM products WHERE company_id = :c)"),
    ("sale_item_lot_allocations",
     "DELETE FROM sale_item_lot_allocations WHERE product_id IN "
     "(SELECT id FROM products WHERE company_id = :c)"),
    ("stock_batches",
     "DELETE FROM stock_batches WHERE product_id IN "
     "(SELECT id FROM products WHERE company_id = :c)"),
    ("inventory",
     "DELETE FROM inventory WHERE product_id IN "
     "(SELECT id FROM products WHERE company_id = :c)"),
    ("import_rows",
     "DELETE FROM import_rows WHERE job_id IN "
     "(SELECT id FROM import_jobs WHERE company_id = :c)"),
    ("import_jobs", "DELETE FROM import_jobs WHERE company_id = :c"),
    # ⚠️  BARKOD/NARX qatorlari ANIQ o'chiriladi, CASCADE'ga TAYANILMAYDI.
    #     FK'da `ON DELETE CASCADE` bor, lekin u Postgres'da ishlaydi va SQLite'da
    #     `PRAGMA foreign_keys` yoqilmagani uchun ISHLAMAYDI — natijada yetim
    #     barkod qolib ketardi (sinovda aynan shunday bo'ldi). Aniq DELETE
    #     dialektdan QAT'IY NAZAR ishlaydi va sanoqni auditga ko'rsatadi.
    ("product_barcodes",
     "DELETE FROM product_barcodes WHERE product_id IN "
     "(SELECT id FROM products WHERE company_id = :c)"),
    ("product_prices",
     "DELETE FROM product_prices WHERE product_id IN "
     "(SELECT id FROM products WHERE company_id = :c)"),
    ("products", "DELETE FROM products WHERE company_id = :c"),
]

# Sanoq hisoboti uchun (o'chiriladigan, lekin cascade bilan ketadiganlar ham).
COUNT_PLAN = [
    ("products", "SELECT count(*) FROM products WHERE company_id = :c"),
    ("product_barcodes", "SELECT count(*) FROM product_barcodes WHERE company_id = :c"),
    ("product_prices", "SELECT count(*) FROM product_prices pp JOIN products p "
                       "ON p.id = pp.product_id WHERE p.company_id = :c"),
    ("inventory", "SELECT count(*) FROM inventory i JOIN products p "
                  "ON p.id = i.product_id WHERE p.company_id = :c"),
    ("stock_movements", "SELECT count(*) FROM stock_movements sm JOIN products p "
                        "ON p.id = sm.product_id WHERE p.company_id = :c"),
    ("stock_batches", "SELECT count(*) FROM stock_batches b JOIN products p "
                      "ON p.id = b.product_id WHERE p.company_id = :c"),
    ("lot_shortfalls",
     "SELECT count(*) FROM lot_shortfalls s JOIN products p "
     "ON p.id = s.product_id WHERE p.company_id = :c"),
    ("sale_item_lot_allocations",
     "SELECT count(*) FROM sale_item_lot_allocations a JOIN products p "
     "ON p.id = a.product_id WHERE p.company_id = :c"),
    ("import_jobs", "SELECT count(*) FROM import_jobs WHERE company_id = :c"),
    ("import_rows", "SELECT count(*) FROM import_rows ir JOIN import_jobs j "
                    "ON j.id = ir.job_id WHERE j.company_id = :c"),
]

# TEGILMASLIGI shart — dry-run ularni ham sanaydi, tekshiruv uchun.
PRESERVE_PLAN = [
    ("companies", "SELECT count(*) FROM companies WHERE id = :c"),
    ("branches", "SELECT count(*) FROM branches WHERE company_id = :c"),
    ("employees", "SELECT count(*) FROM employees WHERE company_id = :c"),
    ("units_GLOBAL", "SELECT count(*) FROM units"),
    ("settings", "SELECT count(*) FROM settings WHERE company_id = :c"),
]

# MAZMUN izi — SANOQ yetarli emas. Qator soni o'zgarmasdan turib mazmun
# o'zgarishi mumkin: `inventory.qty` joyida yangilansa, barkod satri tahrirlansa
# yoki mahsulot narxi/nomi almashsa sanoqlar AYNI qoladi va operator TASDIQLAGAN
# holat endi boshqa bo'lgani holda token yaroqli ko'rinardi. Shu bois o'chirish
# nishoni bo'lgan jadvallarning mazmuni ham izga kiradi.
#
# ⚠️  SQL'da `md5(string_agg(...))` ISHLATILMAYDI — u Postgres'ga xos; SQLite'da
#     testlar jimgina boshqa yo'ldan ketardi. Iz Python'da hisoblanadi: qatorlar
#     SARALANGAN RO'YXAT (to'plam EMAS) va SONI bilan — takror qatorlar yo'qolmaydi.
DIGEST_PLAN = [
    ("products", "SELECT id, name, base_sell_price, base_buy_price, external_id, "
                 "source_system, is_active, deleted_at FROM products WHERE company_id = :c"),
    ("product_barcodes", "SELECT product_id, barcode, pack_qty, is_primary "
                         "FROM product_barcodes WHERE company_id = :c"),
    ("inventory", "SELECT i.product_id, i.branch_id, i.qty FROM inventory i "
                  "JOIN products p ON p.id = i.product_id WHERE p.company_id = :c"),
    # ── DIGEST_PLAN partiya MAZMUNI (Phase 1) ────────────────────────────────
    #  NEGA YETMAYDI `inventory.qty`. Token reja tuzilgan paytdagi katalogga
    #  bog'lanadi. Bugungi oqimlarda partiya o'zgarishi qoldiqni ham suradi, ya'ni
    #  `inventory` daydi. LEKIN qoldiqni QIMIRLATMAYDIGAN partiya o'zgarishlari
    #  bor va ko'payadi: partiya bo'linishi, muddat tuzatilishi, `status` ning
    #  `void` ga o'tishi (miqdor hisobdan chiqadi, `inventory` esa boshqa yozuvchi
    #  tomonidan tuzatiladi). Ular digestga kirmasa, operator KO'RGAN rejadan
    #  boshqa holatni o'chirib yuborishi mumkin edi — token esa hamon "yaroqli".
    ("stock_batches",
     "SELECT b.id, b.product_id, b.branch_id, b.received_qty, b.remaining_qty, "
     "b.status, b.expiry_date, b.batch_no FROM stock_batches b "
     "JOIN products p ON p.id = b.product_id WHERE p.company_id = :c"),
    ("lot_shortfalls",
     "SELECT s.id, s.product_id, s.branch_id, s.qty, s.resolved_qty "
     "FROM lot_shortfalls s JOIN products p ON p.id = s.product_id "
     "WHERE p.company_id = :c"),
    ("sale_item_lot_allocations",
     "SELECT a.sale_item_id, a.stock_batch_id, a.qty FROM sale_item_lot_allocations a "
     "JOIN products p ON p.id = a.product_id WHERE p.company_id = :c"),
]


@dataclass
class ResetPlan:
    eligible: bool
    blockers: dict[str, int]
    delete_counts: dict[str, int]
    preserve_counts: dict[str, int]
    categories: dict
    brands: dict
    notes: list[str]
    digest: dict | None = None
    token: str = ""
    fingerprint: dict | None = None


# Bog'liqlik grafining VERSIYASI — reja o'zgarsa eski tokenlar KUCHSIZ bo'lsin.
def graph_hash() -> str:
    payload = json.dumps({
        "blockers": [n for n, _ in BLOCKERS],
        "delete": [n for n, _ in DELETE_PLAN],
        "count": [n for n, _ in COUNT_PLAN],
        "digest": [n for n, _ in DIGEST_PLAN],
        "known_referrers": sorted(KNOWN_PRODUCT_REFERRERS),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


TOKEN_TTL_SECONDS = 15 * 60


def _token_key() -> bytes:
    from app.core.config import settings
    return hashlib.sha256(("catalog-reset:" + settings.secret_key).encode()).digest()


def fingerprint(db: Session, company_id, plan_obj: "ResetPlan") -> dict:
    """Reset paytidagi holatning TO'LIQ barmoq izi.

    `expect_products` YETARLI EMAS: mahsulot soni o'zgarmasdan turib barkod,
    qoldiq, harakat yoki import qatorlari o'zgargan bo'lishi mumkin — ya'ni
    operator TASDIQLAGAN holat endi boshqa. Shu bois BARCHA sanoqlar va
    BARCHA bloker sanoqlari izga kiradi.

    Sanoqlarning O'ZI ham yetarli emas: `inventory.qty` joyida yangilansa yoki
    barkod satri tahrirlansa sanoq o'zgarmaydi. Shuning uchun `digest` —
    o'chiriladigan jadvallar MAZMUNINING izi — ham qo'shiladi.
    """
    return {
        "company_id": str(company_id),
        "nonce": uuid.uuid4().hex,
        "generated_at": int(time.time()),
        "graph": graph_hash(),
        "delete": dict(plan_obj.delete_counts),
        "blockers": dict(plan_obj.blockers),
        "digest": dict(plan_obj.digest or {}),
    }


def make_token(fp: dict) -> str:
    body = json.dumps(fp, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(_token_key(), body, hashlib.sha256).digest()[:16]
    return (base64.urlsafe_b64encode(body).decode().rstrip("=") + "."
            + base64.urlsafe_b64encode(sig).decode().rstrip("="))


def read_token(token: str) -> dict:
    """Tokenni OCHADI va IMZOSINI tekshiradi. Soxta token QABUL QILINMAYDI."""
    try:
        b64, sig64 = token.split(".", 1)
        body = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        sig = base64.urlsafe_b64decode(sig64 + "=" * (-len(sig64) % 4))
    except Exception as e:      # noqa: BLE001
        raise ValueError("reset tokeni buzuq") from e
    want = hmac.new(_token_key(), body, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(sig, want):
        raise ValueError("reset tokeni IMZOSI noto'g'ri")
    fp = json.loads(body.decode())
    if int(time.time()) - int(fp.get("generated_at", 0)) > TOKEN_TTL_SECONDS:
        raise ValueError("reset tokeni ESKIRGAN — dry-run'ni qayta yurgizing")
    return fp


def _stmt(sql: str):
    """`:c` ni UUID sifatida bog'laydi.

    ⚠️  XOM `str(uuid)` ISHLATIB BO'LMAYDI: Postgres native `uuid` saqlaydi, SQLite esa
        CHAR(32) — DEFISSIZ hex. Defisli satr SQLite'da HECH NARSAGA mos kelmaydi va
        sanoqlar JIMGINA 0 chiqadi (ya'ni "o'chiriladigan narsa yo'q" degan yolg'on).
        Turni bog'lash SQLAlchemy'ga dialektga mos shaklni tanlatadi.
    """
    st = text(sql)
    # `units` kabi tenantsiz so'rovlarda `:c` umuman yo'q — bog'lash XATO berardi.
    return st.bindparams(bindparam("c", type_=AppUUID())) if ":c" in sql else st


ERR = -1          # so'rov YIQILDI — "0 qator" EMAS


def _scalar(db: Session, sql: str, company_id) -> int:
    """Sanoq. So'rov yiqilsa `ERR` (-1) qaytadi — buni 0 deb O'QIMANG.

    ⚠️  Ilgari `plan()` bloklarni faqat `v > 0` bo'lganda hisobga olardi, ya'ni
        -1 JIMGINA "to'siq yo'q" degani edi. `cash.*` bloklari alohida Postgres
        sxemasida yashaydi: sxema yo'q bo'lsa yoki rolda USAGE bo'lmasa, ikkala
        eng kuchli "bu do'konda haqiqiy pul tarixi bor" dalili g'oyib bo'lardi.
    """
    try:
        params = {"c": company_id} if ":c" in sql else {}
        return int(db.execute(_stmt(sql), params).scalar() or 0)
    except Exception:      # noqa: BLE001
        db.rollback()
        return ERR


def _cash_not_applicable(db: Session, sql: str) -> bool:
    """SQLite'da `cash` sxemasi ATAYLAB yo'q (initdb: «cash sxema: skipped-sqlite»).

    Faqat SHU holatda yiqilgan `cash.*` so'rovi «0 qator» deb o'qiladi. Postgres'da
    ayni xato BLOKLAYDI — u yerda sxema bo'lishi SHART.
    """
    try:
        return "cash." in sql and db.bind.dialect.name == "sqlite"
    except Exception:      # noqa: BLE001
        return False


def _digest(db: Session, sql: str, company_id) -> str:
    """Jadval MAZMUNINING izi — qator soni o'zgarmagan tahrirlarni ham ushlaydi.

    Kanoniklashtirish `catalog_commit_v2.canonical_hash` bilan bir xil qoidada:
    qatorlar SARALANGAN RO'YXATga tushadi (to'plam EMAS) va izga qatorlar SONI
    ham kiradi — ya'ni takror qatorlar YO'QOLMAYDI.
    """
    try:
        rows = db.execute(_stmt(sql), {"c": company_id} if ":c" in sql else {}).fetchall()
    except Exception:          # noqa: BLE001 — jadval yo'q (eski baza)
        db.rollback()
        return "-"
    lines = sorted("\x1f".join("" if v is None else str(v) for v in r) for r in rows)
    h = hashlib.sha256()
    h.update(str(len(lines)).encode())
    h.update(b"\x00")
    for ln in lines:
        h.update(ln.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def _catalog_owned(db: Session, company_id) -> tuple[dict, dict]:
    """KATEGORIYA/BREND — import EGALIGI isbotlanmasa TEGILMAYDI (Correction B).

    Ular keyinchalik do'konning O'ZI yaratgan asosiy ma'lumot bo'lishi mumkin.
    Import egaligining isboti: kategoriya/brend SHU do'kon importi tomonidan
    yaratilgan va unga hech qanday QOLGAN havola yo'q.

    Hozirgi sxemada `categories`/`brands` da PROVENANS ustuni YO'Q, shu bois
    isbot faqat bitta holatda mumkin: ularga havola qiluvchi mahsulot qolmagan
    VA ular bo'sh. Aks holda — SAQLANADI.
    """
    c_total = _scalar(db, "SELECT count(*) FROM categories WHERE company_id = :c", company_id)
    b_total = _scalar(db, "SELECT count(*) FROM brands WHERE company_id = :c", company_id)
    # Mahsulotlar o'chirilgandan KEYIN havola qoladimi? (mahsulotdan tashqari havola yo'q)
    c_refd = _scalar(db, "SELECT count(DISTINCT category_id) FROM products "
                         "WHERE company_id = :c AND category_id IS NOT NULL", company_id)
    b_refd = _scalar(db, "SELECT count(DISTINCT brand_id) FROM products "
                         "WHERE company_id = :c AND brand_id IS NOT NULL", company_id)
    cats = {"total": c_total, "referenced_by_products": c_refd,
            "action": "SAQLANADI",
            "reason": "provenans ustuni yo'q — import egaligi ISBOTLANMAYDI; "
                      "do'kon o'zi yaratgan bo'lishi mumkin"}
    brands = {"total": b_total, "referenced_by_products": b_refd,
              "action": "SAQLANADI",
              "reason": "provenans ustuni yo'q — import egaligi ISBOTLANMAYDI"}
    return cats, brands


def unknown_referrers(db: Session) -> list[str]:
    """`products` ga havola qiluvchi, REJADA hisobga olinmagan jadvallar.

    Sxema kengaysa (yangi jadval `products` ga FK qo'ysa) reset uni bilmay
    qolardi va o'chirish yoki FK xatosi bilan yiqilardi, yoki — battari —
    tegishli qatorlarni yetim qoldirardi. Shu bois NOMA'LUM havola topilsa
    reset UMUMAN bajarilmaydi.
    """
    sql = """
        SELECT src.relname FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_class tgt ON tgt.oid = c.confrelid
        WHERE c.contype = 'f' AND tgt.relname = 'products'
    """
    try:
        found = {r[0] for r in db.execute(text(sql)).fetchall()}
    except Exception:          # noqa: BLE001 — SQLite'da pg_constraint yo'q
        db.rollback()
        return []
    return sorted(found - KNOWN_PRODUCT_REFERRERS)


def plan(db: Session, company_id) -> ResetPlan:
    """DRY-RUN. HECH NARSA O'ZGARTIRMAYDI — faqat `SELECT`."""
    blockers = {}
    for name, sql in BLOCKERS:
        v = _scalar(db, sql, company_id)
        if v == ERR and _cash_not_applicable(db, sql):
            v = 0                      # bu dialektda sxema ATAYLAB yo'q
        blockers[name] = v
    # `!= 0` — ya'ni ERR (-1) ham BLOKLAYDI. O'qib bo'lmagan to'siq = to'siq bor.
    bad = {k: v for k, v in blockers.items() if v != 0}
    unknown = unknown_referrers(db)
    if unknown:
        # FAIL-CLOSED: bilmagan bog'liqlik bor ekan, o'chirmaymiz.
        blockers["NOMA'LUM_FK: " + ", ".join(unknown)] = len(unknown)
        bad["unknown_fk"] = len(unknown)
    delete_counts = {name: _scalar(db, sql, company_id) for name, sql in COUNT_PLAN}
    preserve = {name: _scalar(db, sql, company_id) for name, sql in PRESERVE_PLAN}
    # Nima o'chirilishini O'QIY OLMASAK — o'chirmaymiz ham.
    unreadable = sorted(k for k, v in {**delete_counts, **preserve}.items() if v == ERR)
    if unreadable:
        blockers["SANOQ_O'QILMADI: " + ", ".join(unreadable)] = len(unreadable)
        bad["count_error"] = len(unreadable)
    cats, brands = _catalog_owned(db, company_id)
    notes = [
        "units GLOBAL — hech qachon o'chirilmaydi",
        "product_barcodes va product_prices ANIQ o'chiriladi (CASCADE'ga tayanmaydi)",
        "kategoriya/brend SAQLANADI (Correction B) — import egaligi isbotlanmaydi",
        "settings dan FAQAT 'catalog' kaliti tozalanadi; 'cash'/'plan'/'store_info'/"
        "'security' TEGILMAYDI",
    ]
    rp = ResetPlan(eligible=not bad, blockers=blockers, delete_counts=delete_counts,
                   preserve_counts=preserve, categories=cats, brands=brands, notes=notes,
                   digest={name: _digest(db, sql, company_id) for name, sql in DIGEST_PLAN})
    if rp.eligible:
        rp.fingerprint = fingerprint(db, company_id, rp)
        rp.token = make_token(rp.fingerprint)
    return rp


# Reset BAJARISHGA ruxsat berilgan muhitlar — ANIQ RO'YXAT (allowlist).
# Ro'yxatda yo'q HAR QANDAY qiymat (production, noma'lum, bo'sh, buzuq) RAD ETILADI.
RESET_ALLOWED_ENVS = frozenset({"dev", "test", "staging"})


def environment_name() -> str:
    """Muhitning ANIQ nomi. Aniqlab bo'lmasa — `"unknown"`.

    ⚠️  «Production signali yo'q» ni «production emas» deb O'QIMAYMIZ. Ilgari
        aynan shu xato bo'lgan: `APP_ENV` yo'qligi «dev» deb talqin qilinardi va
        production'da katalog reseti OCHIQ qolardi.
    """
    raw = (os.getenv("APP_ENV") or "").strip().lower()
    return raw if raw else "unknown"


def platform_environment_name() -> str:
    """Platformaning O'Z muhit nomi (Railway). Aniqlanmasa — `"unknown"`."""
    raw = (os.getenv("RAILWAY_ENVIRONMENT_NAME") or "").strip().lower()
    return raw if raw else "unknown"


def execution_allowed() -> bool:
    """Bajarish FAQAT dev/test/staging'da. Production'da YOPIQ — FAIL-CLOSED.

    ⚠️  ILGARI BU OCHIQ EDI. Kod `(os.getenv("APP_ENV") or "dev")` deb yozilgan edi,
        ya'ni o'zgaruvchi YO'Q bo'lsa muhit "dev" deb hisoblanardi. Production'da
        `APP_ENV` UMUMAN o'rnatilmagan — natijada katalog resetini bajarish
        production'da OCHIQ edi. Buni sinovlar ham ushlamadi: ular `APP_ENV` ni
        ANIQ `production` qilib qo'yardi, ya'ni production'ning HAQIQIY
        konfiguratsiyasini emas, taxminni tekshirardi.

        Endi qoida ANIQ RO'YXAT (allowlist) bilan yozilgan: ruxsat FAQAT muhit
        o'zini `dev`/`test`/`staging` deb ATAYLAB e'lon qilganda beriladi.
        Ruxsat production signalining YO'QLIGIDAN KELTIRIB CHIQARILMAYDI.

    Qaror jadvali:
        APP_ENV=production           -> RAD (aniq production)
        APP_ENV yo'q / bo'sh         -> RAD (noma'lum)
        APP_ENV="  PROD  " / "qwe"   -> RAD (noma'lum yoki buzuq)
        platforma=production         -> RAD (APP_ENV=dev bo'lsa ham)
        APP_ENV=staging, platforma=staging -> RUXSAT
        APP_ENV=dev (mahalliy)       -> RUXSAT
    """
    env = environment_name()
    # 1) ANIQ RO'YXAT: ro'yxatda bo'lmagan hamma narsa — RAD (production, noma'lum,
    #    yo'q, buzuq). Bu yagona «ruxsat beruvchi» shart.
    if env not in RESET_ALLOWED_ENVS:
        return False
    # 2) PLATFORMANING O'Z belgisi APP_ENV dan USTUN. Sabab: `main.py` production'da
    #    SQLite aniqlansa operatorga «APP_ENV=dev bering» deb maslahat beradi — o'sha
    #    maslahatga amal qilish PRODUCTION'da reset darvozasini ochib yuborardi.
    if platform_environment_name() in {"prod", "production"}:
        return False
    return True


def verify_token(db: Session, company_id, token: str) -> dict:
    """Tokenni ochadi VA holatni TRANZAKSIYA ICHIDA qayta o'qib solishtiradi.

    Dry-run'dan keyin BIRON NARSA o'zgargan bo'lsa — reset RAD ETILADI.
    """
    fp = read_token(token)
    if fp.get("company_id") != str(company_id):
        raise ValueError("reset tokeni BOSHQA do'konga tegishli")
    if fp.get("graph") != graph_hash():
        raise ValueError("bog'liqlik grafi o'zgargan — dry-run'ni qayta yurgizing")
    now = plan(db, company_id)
    if not now.eligible:
        raise ValueError(f"holat o'zgardi — endi mumkin emas: "
                         f"{ {k: v for k, v in now.blockers.items() if v > 0} }")
    diffs = {k: (v, now.delete_counts.get(k))
             for k, v in (fp.get("delete") or {}).items() if now.delete_counts.get(k) != v}
    diffs.update({f"blocker:{k}": (v, now.blockers.get(k))
                  for k, v in (fp.get("blockers") or {}).items() if now.blockers.get(k) != v})
    diffs.update({f"mazmun:{k}": (v, (now.digest or {}).get(k))
                  for k, v in (fp.get("digest") or {}).items()
                  if (now.digest or {}).get(k) != v})
    if diffs:
        raise ValueError(f"dry-run'dan keyin holat O'ZGARDI: {diffs}")
    return fp


def execute(db: Session, company_id) -> dict:
    """Katalogni BITTA tranzaksiyada o'chiradi. Chaqiruvchi `plan()` ni oldin
    tekshirgan va operator tasdiqlagan bo'lishi SHART.

    ⚠️  Production'da funksiya-darvoza yopiq — `execution_allowed()` False.
    """
    if not execution_allowed():
        raise PermissionError("katalog-reset bajarish bu muhitda YOPIQ (Phase 1)")
    p = plan(db, company_id)
    if not p.eligible:
        raise ValueError(f"reset mumkin emas — biznes hujjatlari mavjud: "
                         f"{ {k: v for k, v in p.blockers.items() if v > 0} }")
    deleted: dict[str, int] = {}
    for name, sql in DELETE_PLAN:
        try:
            res = db.execute(_stmt(sql), {"c": company_id})
            deleted[name] = int(res.rowcount or 0)
        except Exception as e:      # noqa: BLE001
            db.rollback()
            raise RuntimeError(f"{name} o'chirishda xato — tranzaksiya qaytarildi: {e}") from e
    # settings.catalog ni tozalaymiz; boshqa kalitlarga TEGMAYMIZ.
    db.execute(_stmt("DELETE FROM settings WHERE company_id = :c AND key = 'catalog'"),
               {"c": company_id})
    return deleted
