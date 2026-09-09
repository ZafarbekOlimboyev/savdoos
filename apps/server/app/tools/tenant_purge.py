# -*- coding: utf-8 -*-
"""SavdoOS Operations CLI · TENANT PURGE (do'kon ma'lumotini butunlay o'chirish).

⚠️  BU YAGONA QAYTARIB BO'LMAYDIGAN VOSITA. Standart rejim — QURUQ SINOV (dry run):
    hech narsa o'chirilmaydi, faqat NIMA o'chirilishi hisoblab chiqiladi.

    python -m app.tools.tenant_purge --company-code baraka            # DRY RUN
    python -m app.tools.tenant_purge --company-code baraka --json     # DRY RUN (JSON)

O'chirish uchun IKKI aniq tasdiq SHART (ikkalasi ham):

    --execute --confirm-company-code baraka

`--confirm-company-code` topilgan do'kon kodiga AYNAN mos kelishi kerak. Nusxa-ko'chirish
xatosi (boshqa do'konni o'chirib yuborish) shu bilan to'sib qo'yilgan.

═══ BOG'LIQLIKLAR QANDAY TOPILADI ══════════════════════════════════════════
Jadval ro'yxati QO'LDA YOZILMAGAN. U har ishga tushganda PostgreSQL katalogidan
(`information_schema` + `pg_catalog`) O'QILADI:

  1. `companies` ga to'g'ridan-to'g'ri FK bo'lgan jadvallar
  2. ular orqali BILVOSITA egalik qiladigan jadvallar (sale_items -> sales -> company)
  3. `company_id`/`tenant_id` ustuni bor, LEKIN FK'si YO'Q jadvallar

3-band ATAYLAB alohida: bu bazada `qr_payments`, `scales`, `sync_devices` aynan shunday —
faqat FK bo'yicha yursak ular JIMGINA yetim qolardi. Sxema o'zgarsa ro'yxat o'zi yangilanadi,
chunki u koddan emas, BAZADAN o'qiladi.

═══ APPEND-ONLY LEDGER ═════════════════════════════════════════════════════
`cash` sxemasidagi 7 jadval `fn_block_mutation` triggeri bilan himoyalangan: ular
DELETE'ni RAD ETADI (ledger — o'zgarmas audit izi). Bu ATAYLAB shunday va normal ish
paytida buzilmasligi kerak. Tenant butunlay o'chirilishi esa boshqa toifadagi amal:
ma'muriy destruktiv operatsiya. Shu bois triggerlar TRANZAKSIYA ICHIDA vaqtincha
o'chiriladi va commit'dan OLDIN QAYTA YOQILADI. Rollback bo'lsa DDL ham qaytariladi.

XAVFSIZLIK: hech qanday sir chop etilmaydi. Exit: 0 = OK, 2 = BLOKLANGAN, 1 = usage/xato.
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.tools import _common as C

# `fn_block_mutation` bilan himoyalangan jadvallar shu ro'yxatdan EMAS, katalogdan topiladi
# (quyida `_blocking_triggers`). Bu doimiy faqat hujjat uchun.
APPEND_ONLY_NOTE = "cash.* append-only triggerlari tranzaksiya ichida vaqtincha o'chiriladi"


# ═══════════════════════════════════════════════════════════════════════════
# 1) SXEMA KASHFIYOTI
# ═══════════════════════════════════════════════════════════════════════════
def _foreign_keys(db) -> list[dict]:
    """public+cash sxemalaridagi FK'lar — KO'P USTUNLI (composite) bo'lsa ham TO'G'RI.

    ⚠️  NEGA `pg_catalog`, `information_schema` EMAS:
    `information_schema.constraint_column_usage` ko'p ustunli FK'da bola va ota
    ustunlarini TARTIB bo'yicha JUFTLAMAYDI — u shunchaki dekart ko'paytmasini beradi.
    `cash` sxemasida composite FK'lar bor (masalan `(tenant_id, id)` -> shifts), va
    natijada `account_type -> cash_accounts.id` kabi SOXTA juftliklar hosil bo'lardi.
    Bu jimgina noto'g'ri egalik sharti demakdir. `conkey`/`confkey` massivlari esa
    ordinal tartibni saqlaydi."""
    rows = db.execute(text("""
        SELECT cn.nspname  AS child_schema,
               cc.relname  AS child_table,
               (SELECT array_agg(a.attname ORDER BY x.ord)
                  FROM unnest(c.conkey) WITH ORDINALITY AS x(attnum, ord)
                  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = x.attnum)
                          AS child_columns,
               pn.nspname  AS parent_schema,
               pc.relname  AS parent_table,
               (SELECT array_agg(a.attname ORDER BY x.ord)
                  FROM unnest(c.confkey) WITH ORDINALITY AS x(attnum, ord)
                  JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = x.attnum)
                          AS parent_columns
        FROM pg_constraint c
        JOIN pg_class cc      ON cc.oid = c.conrelid
        JOIN pg_namespace cn  ON cn.oid = cc.relnamespace
        JOIN pg_class pc      ON pc.oid = c.confrelid
        JOIN pg_namespace pn  ON pn.oid = pc.relnamespace
        WHERE c.contype = 'f'
          AND cn.nspname IN ('public','cash')
        ORDER BY 1,2,3
    """)).fetchall()
    return [dict(child_schema=r[0], child_table=r[1], child_columns=list(r[2]),
                 parent_schema=r[3], parent_table=r[4], parent_columns=list(r[5]))
            for r in rows]


def _tenant_columns(db) -> dict[tuple[str, str], str]:
    """FK'siz bo'lsa ham tenantga tegishli ustun: company_id yoki tenant_id."""
    rows = db.execute(text("""
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE column_name IN ('company_id','tenant_id')
          AND table_schema IN ('public','cash')
    """)).fetchall()
    out: dict[tuple[str, str], str] = {}
    for sch, tbl, col in rows:
        # company_id ustunligi (tenant_id faqat cash'da)
        if (sch, tbl) not in out or col == "company_id":
            out[(sch, tbl)] = col
    return out


def _all_tables(db) -> list[tuple[str, str]]:
    rows = db.execute(text("""
        SELECT table_schema, table_name FROM information_schema.tables
        WHERE table_schema IN ('public','cash') AND table_type='BASE TABLE'
        ORDER BY 1,2
    """)).fetchall()
    return [(r[0], r[1]) for r in rows]


def _blocking_triggers(db) -> list[tuple[str, str]]:
    """DELETE'ni bloklaydigan foydalanuvchi triggerlari bor jadvallar."""
    rows = db.execute(text("""
        SELECT DISTINCT n.nspname, c.relname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE NOT t.tgisinternal
          AND n.nspname IN ('public','cash')
          AND (t.tgtype & 8) > 0          -- DELETE hodisasi
        ORDER BY 1,2
    """)).fetchall()
    return [(r[0], r[1]) for r in rows]


def residual_tables(db, ownership: dict) -> list[dict]:
    """Egalik ANIQLANMAGAN, LEKIN tenantga bog'liq bo'lishi MUMKIN bo'lgan jadvallar.

    NEGA KERAK: ba'zi jadvallarda `branch_id` / `employee_id` / `terminal_id` PLAIN UUID
    sifatida turadi — FK YO'Q. Masalan `activity_events`, shuningdek `sync_log` /
    `sync_cursors` faqat `device_uuid` bo'yicha kalitlangan. Ularni FK grafi ham,
    `company_id` qidiruvi ham TOPMAYDI.

    Bu qatorlar do'kon o'chgach ham QOLADI. Ular hech narsani buzmaydi (FK yo'q, ular
    yetim ham hisoblanmaydi), LEKIN operator BILISHI kerak — "hammasi o'chdi" degan
    yolg'on taassurot bo'lmasligi uchun. Shu bois ular hisobotda ALOHIDA ko'rsatiladi,
    JIMGINA o'tkazib yuborilmaydi."""
    suspicious = ("branch_id", "employee_id", "terminal_id", "cashier_id",
                  "device_uuid", "actor_id")
    rows = db.execute(text("""
        SELECT t.table_schema, t.table_name,
               array_agg(c.column_name ORDER BY c.column_name)
        FROM information_schema.tables t
        JOIN information_schema.columns c
          ON c.table_schema = t.table_schema AND c.table_name = t.table_name
        WHERE t.table_schema IN ('public','cash') AND t.table_type='BASE TABLE'
          AND c.column_name = ANY(:cols)
        GROUP BY 1,2 ORDER BY 1,2
    """), {"cols": list(suspicious)}).fetchall()

    out = []
    for sch, tbl, cols in rows:
        if (sch, tbl) in ownership:
            continue                       # allaqachon qamrab olingan
        try:
            n = db.execute(text(f'SELECT count(*) FROM "{sch}"."{tbl}"')).scalar()
        except Exception:
            db.rollback()
            n = None
        # psycopg Postgres massivini ba'zan SATR sifatida qaytaradi ("{a,b}") — u holda
        # `list(...)` uni BELGILARGA bo'lib yuborardi. Ikkala shaklni ham normallashtiramiz.
        if isinstance(cols, str):
            names = [c for c in cols.strip("{}").split(",") if c]
        else:
            names = list(cols)
        out.append({"table": f"{sch}.{tbl}", "hint_columns": names,
                    "total_rows_all_tenants": n})
    return out


def build_ownership(db) -> tuple[dict, list, dict]:
    """Har jadval uchun "shu tenantga tegishli qatorlar" SHARTINI quradi.

    Qaytaradi: (ownership, order, meta)
      ownership[(sch,tbl)] = SQL WHERE ifodasi (`:cid` parametri bilan)
      order                = o'chirish TARTIBI (bolalar OLDIN)
      meta                 = qanday aniqlangani (audit uchun)
    """
    fks = _foreign_keys(db)
    tcols = _tenant_columns(db)
    tables = _all_tables(db)

    # child -> [FK] indeksi
    by_child: dict[tuple[str, str], list[dict]] = {}
    for fk in fks:
        by_child.setdefault((fk["child_schema"], fk["child_table"]), []).append(fk)

    ownership: dict[tuple[str, str], str] = {}
    how: dict[tuple[str, str], str] = {}
    resolving: set = set()

    def q(sch, tbl):
        return f'"{sch}"."{tbl}"'

    def _cols(cols):
        return ", ".join(f'"{c}"' for c in cols)

    def resolve(node) -> str | None:
        """Shu jadvaldagi qaysi qatorlar SHU tenantga tegishli — SQL sharti.

        ⚠️  BARCHA yo'llar OR bilan BIRLASHTIRILADI. Ilgari BIRINCHI topilgan yo'l
        ishlatilardi va bu IKKI xil jimgina xatoga olib kelgan (testlar ushladi):

          1. `sync_devices` da ham `company_id`, ham `terminal_id -> terminals` bor.
             Faqat FK yo'li tanlansa, `terminal_id` NULL bo'lgan qatorlar TOPILMASDI —
             qurilma yozuvlari YETIM qolardi.
          2. `credit_transactions` da `customer_id`, `payment_id`, `sale_id` bor.
             Faqat bittasi tanlansa, o'sha ustuni NULL qatorlar qolib ketardi va ular
             `customers` ni O'CHIRISHGA YO'L BERMASDI (FK to'qnashuvi) — purge to'xtardi.

        Qator YO'LLARDAN BIRORTASI orqali tenant ma'lumotiga ulansa — u SHU tenantniki.
        Boshqacha bo'lishi mumkin emas: aks holda o'sha FK butunlay buzilgan bo'lardi."""
        if node in ownership:
            return ownership[node]
        if node in resolving:          # sikl — bu yo'ldan bormaymiz
            return None
        if node == ("public", "companies"):
            ownership[node] = "id = :cid"
            how[node] = "company_row"
            return ownership[node]

        resolving.add(node)
        try:
            preds: list[str] = []
            reasons: list[str] = []

            # (a) `companies` ga TO'G'RIDAN-TO'G'RI FK — eng ishonchli belgi
            for fk in sorted(by_child.get(node, []), key=lambda f: f["child_columns"]):
                if ((fk["parent_schema"], fk["parent_table"]) == ("public", "companies")
                        and len(fk["child_columns"]) == 1):
                    preds.append(f'"{fk["child_columns"][0]}" = :cid')
                    reasons.append(f'direct_fk:{fk["child_columns"][0]}')

            # (b) FK bo'lmasa ham tenant ustuni — `qr_payments`/`scales`/`sync_devices`
            col = tcols.get(node)
            if col and f'"{col}" = :cid' not in preds:
                preds.append(f'"{col}" = :cid')
                reasons.append(f'tenant_column:{col}')

            # (c) BILVOSITA: egalik qiluvchi HAR BIR ota-jadval orqali.
            #     Composite FK uchun qatorli (row-wise) IN ishlatiladi.
            for fk in sorted(by_child.get(node, []),
                             key=lambda f: (f["parent_table"], f["child_columns"])):
                parent = (fk["parent_schema"], fk["parent_table"])
                if parent == node or parent == ("public", "companies"):
                    continue
                ppred = resolve(parent)
                if not ppred:
                    continue
                ch, pa = fk["child_columns"], fk["parent_columns"]
                if len(ch) == 1:
                    preds.append(f'"{ch[0]}" IN '
                                 f'(SELECT "{pa[0]}" FROM {q(*parent)} WHERE {ppred})')
                else:
                    preds.append(f'({_cols(ch)}) IN '
                                 f'(SELECT {_cols(pa)} FROM {q(*parent)} WHERE {ppred})')
                reasons.append(f'via:{fk["parent_table"]}.{"+".join(ch)}')

            if not preds:
                return None                     # global/umumiy jadval — TEGILMAYDI
            ownership[node] = "(" + " OR ".join(preds) + ")"
            how[node] = " | ".join(reasons)
            return ownership[node]
        finally:
            resolving.discard(node)

    for t in tables:
        resolve(t)

    # ── O'CHIRISH TARTIBI: bolalar OLDIN, ota KEYIN ────────────────────────
    owned = set(ownership) - {("public", "companies")}
    deps: dict[tuple, set] = {t: set() for t in owned}
    for fk in fks:
        ch = (fk["child_schema"], fk["child_table"])
        pa = (fk["parent_schema"], fk["parent_table"])
        if ch in owned and pa in owned and ch != pa:
            deps[pa].add(ch)                        # ota bola O'CHGACH o'chadi

    order: list = []
    seen: set = set()

    def visit(node, stack):
        if node in seen or node in stack:
            return
        stack.add(node)
        for child in sorted(deps.get(node, ()), key=lambda x: (x[0], x[1])):
            visit(child, stack)
        stack.discard(node)
        seen.add(node)
        order.append(node)

    for t in sorted(owned, key=lambda x: (x[0], x[1])):
        visit(t, set())
    order.append(("public", "companies"))           # do'kon qatori ENG OXIRIDA

    meta = {"how": how, "fk_count": len(fks), "tables_scanned": len(tables),
            "blocking_triggers": _blocking_triggers(db)}
    return ownership, order, meta


# ═══════════════════════════════════════════════════════════════════════════
# 2) DO'KONNI ANIQLASH
# ═══════════════════════════════════════════════════════════════════════════
def resolve_company(db, *, code: str | None, cid: str | None) -> dict:
    """AYNAN bitta do'konni topadi. Noaniqlik yoki topilmaslik — XATO."""
    # `is not None` — ATAYLAB: `--company-code ""` ANIQ berilgan hisoblanadi va quyidagi
    # joker tekshiruviga tushadi ("ikkalasi ham berilmagan" degan chalg'ituvchi xabar emas).
    if (code is not None) == (cid is not None):
        raise SystemExit("--company-code YOKI --company-id — AYNAN bittasi berilishi kerak.")

    if cid:
        try:
            key = uuid.UUID(str(cid).strip())
        except ValueError:
            raise SystemExit(f"--company-id yaroqli UUID emas: {cid}")
        rows = db.execute(text(
            "SELECT id, code, name, created_at, deleted_at FROM companies WHERE id = :v"),
            {"v": key}).fetchall()
        label = f"id={cid}"
    else:
        val = (code or "").strip()
        # Bo'sh/joker QABUL QILINMAYDI — "hammasini o'chirish" MUMKIN EMAS.
        if not val or val in {"*", "%", "all", "ALL"}:
            raise SystemExit("--company-code bo'sh yoki joker bo'lishi MUMKIN EMAS.")
        if "%" in val or "_" in val.replace("-", ""):
            pass    # LIKE ishlatilmaydi — quyida TENGLIK bo'yicha qidiriladi
        rows = db.execute(text(
            "SELECT id, code, name, created_at, deleted_at FROM companies WHERE code = :v"),
            {"v": val}).fetchall()
        label = f"code={val}"

    if not rows:
        raise SystemExit(f"Do'kon TOPILMADI ({label}). Hech narsa qilinmadi.")
    if len(rows) > 1:
        raise SystemExit(f"NOANIQ: {label} bo'yicha {len(rows)} ta do'kon topildi. To'xtatildi.")
    r = rows[0]
    return {"id": r[0], "code": r[1], "name": r[2],
            "created_at": r[3], "deleted_at": r[4]}


# ═══════════════════════════════════════════════════════════════════════════
# 3) HAQIQIY MIJOZ HIMOYASI
# ═══════════════════════════════════════════════════════════════════════════
def risk_signals(db, company_id, ownership: dict) -> tuple[list[dict], list[dict]]:
    """Bu do'kon HAQIQIY mijozga o'xshaydimi — DALILLAR bo'yicha.

    Qaytaradi: (bloklovchi_signallar, ma'lumot_uchun_signallar)

    DIQQAT — IKKI TOIFA ATAYLAB AJRATILGAN. Har qanday "faollik" ni bloklovchi qilib
    qo'yish gardni FOYDASIZ qiladi: masalan naqd ledger yozuvlari BARCHA tenantlarda
    bor (dual-write butun bazada yoqilgan), shu bois u bloklasa ETTALA eski demo ham
    bloklanardi va operator gardni har safar bekor qilishga o'rganib qolardi — ya'ni
    garddan foyda qolmasdi. Shu bois faqat HAQIQIY MIJOZGA XOS, demo tenantda
    KUTILMAYDIGAN dalillar bloklaydi; qolgani kontekst sifatida KO'RSATILADI.

    "Kod demo'ga o'xshaydi" HIMOYA SIFATIDA UMUMAN ISHLATILMAYDI: kod ixtiyoriy matn va
    onboarding paytida haqiqiy do'kon ham `test-...` deb nomlanishi mumkin."""
    blocking: list[dict] = []
    info: list[dict] = []
    p = {"cid": company_id}

    def count(sql, params=None):
        try:
            return int(db.execute(text(sql), {**p, **(params or {})}).scalar() or 0)
        except Exception:
            db.rollback()
            return 0

    # ── BLOKLOVCHI: eski demo tenantda BO'LMASLIGI kerak bo'lgan dalillar ──

    # (1) Ledger-native onboarding — YANGI arxitekturada ochilgan do'kon belgisi.
    #     Eski demo tenantlar bu belgidan OLDIN yaratilgan.
    try:
        ln = db.execute(text(
            "SELECT value FROM settings WHERE company_id = :cid AND branch_id IS NULL "
            "AND key = 'cash'"), p).scalar()
    except Exception:
        db.rollback()
        ln = None
    if isinstance(ln, dict) and ln.get("ledger_native") is True:
        blocking.append({"signal": "ledger_native_onboarding",
                         "detail": "settings.cash.ledger_native=true",
                         "why": "do'kon YANGI (ledger-native) arxitekturada ochilgan — "
                                "eski demo tenantlar bunday emas"})

    # (2) Tashqi to'lov faolligi (QR) — soxta/demo ma'lumotda hosil bo'lmaydi
    n = count("SELECT count(*) FROM qr_payments WHERE company_id = :cid")
    if n:
        blocking.append({"signal": "external_payments", "detail": f"{n} ta QR to'lov",
                         "why": "tashqi to'lov tizimi bilan HAQIQIY aloqa bo'lgan"})

    # (3) YAQINDAGI savdo — demo tenantlar harakatsiz turadi
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    n = count("SELECT count(*) FROM sales WHERE company_id = :cid AND sold_at >= :c",
              {"c": cutoff})
    if n:
        blocking.append({"signal": "recent_sales_30d", "detail": f"{n} ta savdo (oxirgi 30 kun)",
                         "why": "do'kon YAQINDA ishlagan — harakatsiz demo emas"})

    # (4) Versiya xabar qilgan qurilma — haqiqiy kassa ulangan
    n = count("SELECT count(*) FROM sync_devices "
              "WHERE company_id = :cid AND app_version IS NOT NULL")
    if n:
        blocking.append({"signal": "reporting_devices", "detail": f"{n} ta qurilma",
                         "why": "haqiqiy kassa qurilmasi serverga versiya xabar bergan"})

    # ── MA'LUMOT UCHUN: bloklamaydi, lekin operator KO'RISHI kerak ────────
    n = count("SELECT count(*) FROM cash.cash_ledger_entries WHERE tenant_id = :cid")
    if n:
        info.append({"signal": "cash_ledger_entries", "detail": f"{n} ta yozuv",
                     "why": "dual-write butun bazada yoqilgan — bu YOLG'IZ holda "
                            "haqiqiy mijoz belgisi EMAS"})
    n = count("SELECT count(*) FROM sales WHERE company_id = :cid")
    if n:
        info.append({"signal": "total_sales", "detail": f"{n} ta savdo (butun tarix)",
                     "why": "hajm konteksti — o'chirish miqyosini ko'rsatadi"})
    last = None
    try:
        last = db.execute(text("SELECT max(sold_at) FROM sales WHERE company_id = :cid"), p).scalar()
    except Exception:
        db.rollback()
    if last is not None:
        info.append({"signal": "last_sale_at", "detail": last.isoformat(),
                     "why": "oxirgi faollik sanasi"})

    return blocking, info


# ═══════════════════════════════════════════════════════════════════════════
# 4) HISOBOT
# ═══════════════════════════════════════════════════════════════════════════
def collect_counts(db, company_id, ownership: dict, order: list) -> dict:
    counts: dict[str, int] = {}
    for node in order:
        if node == ("public", "companies"):
            continue
        sch, tbl = node
        pred = ownership[node]
        n = db.execute(text(f'SELECT count(*) FROM "{sch}"."{tbl}" WHERE {pred}'),
                       {"cid": company_id}).scalar()
        if n:
            counts[f"{sch}.{tbl}"] = int(n)
    return counts


def build_report(db, company: dict, ownership, order, meta, *, allow_real: bool) -> dict:
    counts = collect_counts(db, company["id"], ownership, order)
    signals, info = risk_signals(db, company["id"], ownership)
    residual = residual_tables(db, ownership)

    blockers: list[str] = []
    if signals and not allow_real:
        blockers.append(
            "HAQIQIY MIJOZ SHUBHASI: " + ", ".join(s["signal"] for s in signals) +
            ". O'chirish BLOKLANDI. Agar bu haqiqatan eski demo bo'lsa — "
            "--i-know-this-is-not-a-real-merchant bilan aniq bekor qiling.")
    if company.get("deleted_at") is not None:
        blockers.append("Do'kon allaqachon `deleted_at` bilan belgilangan (yumshoq o'chirilgan).")

    return {
        "company": {"id": str(company["id"]), "code": company["code"],
                    "name": company["name"],
                    "created_at": (company["created_at"].isoformat()
                                   if company["created_at"] else None)},
        "discovery": {"foreign_keys_scanned": meta["fk_count"],
                      "tables_scanned": meta["tables_scanned"],
                      "owned_tables": len(ownership) - 1,
                      "append_only_tables": [f"{s}.{t}" for s, t in meta["blocking_triggers"]]},
        "dependencies": counts,
        "total_rows": sum(counts.values()),
        "risk_signals": signals,
        "context_signals": info,
        "residual_tables": residual,
        "real_merchant_override": bool(allow_real),
        "blockers": blockers,
        "verdict": "PURGE_BLOCKED" if blockers else "PURGE_READY",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5) BAJARISH
# ═══════════════════════════════════════════════════════════════════════════
def execute_purge(db, company: dict, ownership, order, meta) -> dict:
    """BITTA tranzaksiya. Xato bo'lsa — TO'LIQ rollback."""
    cid = company["id"]
    blocking = meta["blocking_triggers"]
    deleted: dict[str, int] = {}

    # (a) append-only triggerlarni VAQTINCHA o'chirish. DDL tranzaksion — rollback
    #     bo'lsa triggerlar o'z-o'zidan qaytadi.
    for sch, tbl in blocking:
        try:
            db.execute(text(f'ALTER TABLE "{sch}"."{tbl}" DISABLE TRIGGER USER'))
        except Exception as e:
            raise SystemExit(
                f"Trigger o'chirilmadi ({sch}.{tbl}): {e}\n"
                "Bu amal jadval EGASI huquqini talab qiladi. Ledger append-only "
                "triggerlarisiz o'chirilmaydi — to'xtatildi.")

    # (b) o'chirish — bolalar oldin. FK to'qnashuvida keyingi bosqichga qoldiramiz.
    pending = [n for n in order if n != ("public", "companies")]
    for _ in range(len(pending) + 2):
        if not pending:
            break
        stuck = []
        progress = False
        for node in pending:
            sch, tbl = node
            sp = db.begin_nested()
            try:
                res = db.execute(
                    text(f'DELETE FROM "{sch}"."{tbl}" WHERE {ownership[node]}'), {"cid": cid})
                sp.commit()
                if res.rowcount:
                    deleted[f"{sch}.{tbl}"] = deleted.get(f"{sch}.{tbl}", 0) + res.rowcount
                progress = True
            except Exception:
                sp.rollback()
                stuck.append(node)
        pending = stuck
        if not progress:
            break
    if pending:
        raise SystemExit("O'chirib bo'lmadi (FK bog'liqligi hal bo'lmadi): "
                         + ", ".join(f"{s}.{t}" for s, t in pending))

    # (c) do'kon qatori
    res = db.execute(text("DELETE FROM companies WHERE id = :cid"), {"cid": cid})
    deleted["public.companies"] = res.rowcount

    # (d) triggerlarni QAYTA YOQISH — commit'dan OLDIN
    for sch, tbl in blocking:
        db.execute(text(f'ALTER TABLE "{sch}"."{tbl}" ENABLE TRIGGER USER'))

    # (e) TEKSHIRUV — qoldiq BO'LMASLIGI shart
    residue: dict[str, int] = {}
    for node in order:
        sch, tbl = node
        n = db.execute(text(f'SELECT count(*) FROM "{sch}"."{tbl}" WHERE {ownership[node]}'),
                       {"cid": cid}).scalar()
        if n:
            residue[f"{sch}.{tbl}"] = int(n)
    if residue:
        raise SystemExit(f"QOLDIQ TOPILDI — rollback qilinadi: {residue}")

    still = db.execute(text("SELECT count(*) FROM companies WHERE id = :cid"), {"cid": cid}).scalar()
    if still:
        raise SystemExit("Do'kon qatori o'chmadi — rollback qilinadi.")

    # (f) triggerlar HAQIQATAN qaytganini tasdiqlash
    for sch, tbl in blocking:
        bad = db.execute(text("""
            SELECT count(*) FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE NOT t.tgisinternal AND n.nspname=:s AND c.relname=:t AND t.tgenabled='D'
        """), {"s": sch, "t": tbl}).scalar()
        if bad:
            raise SystemExit(f"{sch}.{tbl}: trigger QAYTA YOQILMADI — rollback qilinadi.")

    return deleted


# ═══════════════════════════════════════════════════════════════════════════
def main(argv=None, session_factory=None) -> int:
    p = argparse.ArgumentParser(
        description="Do'kon (tenant) ma'lumotini butunlay o'chirish. Standart: QURUQ SINOV.")
    p.add_argument("--company-code", default=None)
    p.add_argument("--company-id", default=None)
    p.add_argument("--json", action="store_true", help="stdout FAQAT JSON")
    p.add_argument("--execute", action="store_true",
                   help="HAQIQATAN o'chirish (--confirm-company-code ham SHART)")
    p.add_argument("--confirm-company-code", default=None,
                   help="o'chiriladigan do'kon kodini QAYTA yozing (aynan mos kelishi shart)")
    p.add_argument("--i-know-this-is-not-a-real-merchant", action="store_true",
                   dest="allow_real", help="haqiqiy-mijoz gardini ANIQ bekor qilish")
    args = p.parse_args(argv)

    C.set_stdout_json_only(bool(args.json))
    try:
        _engine, db = C.get_engine_and_session(session_factory)
        try:
            if not C.is_postgres(db):
                C.err("REFUSED: bu vosita faqat PostgreSQL'da ishlaydi.")
                return 1

            company = resolve_company(db, code=args.company_code, cid=args.company_id)
            ownership, order, meta = build_ownership(db)
            report = build_report(db, company, ownership, order, meta, allow_real=args.allow_real)

            if not args.json:
                C.out("=" * 74)
                C.out(" SavdoOS · TENANT PURGE   " +
                      ("[BAJARISH]" if args.execute else "[QURUQ SINOV — hech narsa o'chirilmaydi]"))
                C.out("=" * 74)
                C.out("COMPANY")
                C.out(f"  id   = {report['company']['id']}")
                C.out(f"  code = {report['company']['code']}")
                C.out(f"  name = {report['company']['name']}")
                C.out(f"\nDISCOVERY  (katalogdan, qo'lda yozilmagan)")
                d = report["discovery"]
                C.out(f"  FK ko'rildi={d['foreign_keys_scanned']}  jadval={d['tables_scanned']}  "
                      f"tenantga tegishli={d['owned_tables']}")
                C.out(f"  append-only: {', '.join(d['append_only_tables']) or 'yo‘q'}")
                C.out("\nDEPENDENCIES")
                for k, v in sorted(report["dependencies"].items()):
                    C.out(f"  {k:<40} {v}")
                C.out(f"  {'JAMI':<40} {report['total_rows']}")
                if report["residual_tables"]:
                    C.out("\nRESIDUAL (egaligi aniqlanmadi — o'chirilmaydi, QOLADI)")
                    for r in report["residual_tables"]:
                        C.out(f"   ? {r['table']:<30} ustunlar={','.join(r['hint_columns'])} "
                              f"(jami {r['total_rows_all_tenants']} qator, BARCHA tenantlar)")
                    C.out("     Bular tenantga FK bilan bog'lanmagan — qo'lda ko'rib chiqing.")
                if report["context_signals"]:
                    C.out("\nCONTEXT (bloklamaydi — faqat ma'lumot)")
                    for s in report["context_signals"]:
                        C.out(f"   - {s['signal']}: {s['detail']}")
                if report["risk_signals"]:
                    C.out("\nRISK SIGNALS (HAQIQIY MIJOZ dalillari — BLOKLAYDI)")
                    for s in report["risk_signals"]:
                        C.out(f"  !! {s['signal']}: {s['detail']}")
                        C.out(f"     {s['why']}")
                C.out("\nBLOCKERS")
                for b in report["blockers"]:
                    C.out(f"  !! {b}")
                if not report["blockers"]:
                    C.out("  (yo'q)")
                C.out("\nVERDICT: " + report["verdict"])

            if report["verdict"] == "PURGE_BLOCKED":
                if args.json:
                    C.emit_json(report)
                return 2

            if not args.execute:
                if args.json:
                    C.emit_json({**report, "mode": "dry_run", "rows_deleted": 0})
                else:
                    C.out("\nQURUQ SINOV — hech narsa o'chirilmadi.")
                    C.out("Bajarish uchun: --execute --confirm-company-code "
                          f"{report['company']['code']}")
                return 0

            # ── BAJARISH ──────────────────────────────────────────────────
            if args.confirm_company_code != company["code"]:
                C.err(f"TASDIQ MOS EMAS: --confirm-company-code '{args.confirm_company_code}' "
                      f"!= '{company['code']}'. Hech narsa o'chirilmadi.")
                return 1

            try:
                deleted = execute_purge(db, company, ownership, order, meta)
                db.commit()
            except BaseException:
                db.rollback()
                raise

            payload = {**report, "mode": "execute", "deleted_counts": deleted,
                       "rows_deleted": sum(deleted.values()), "result": "TENANT_PURGE_OK"}
            if args.json:
                C.emit_json(payload)
            else:
                C.out("\nTENANT_PURGE_OK")
                C.out(f"company_id={report['company']['id']}")
                C.out(f"company_code={report['company']['code']}")
                C.out(f"deleted_counts={deleted}")
            return 0
        finally:
            db.rollback()
            db.close()
    finally:
        C.set_stdout_json_only(False)


if __name__ == "__main__":
    raise SystemExit(main())
