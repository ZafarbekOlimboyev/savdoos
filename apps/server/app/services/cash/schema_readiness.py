# -*- coding: utf-8 -*-
"""Phase 1 — `cash` SXEMASI TAYYORLIGI (SEYF ochilish obyektlari).

⚠️  NEGA ALOHIDA MODUL, `required_schema` EMAS. `app/core/required_schema.py` ning HAR
    so'rovi `nspname = 'public'` bo'yicha filtrlaydi — bu ATAYLAB (u public sxemaning
    registri). `cash` sxemasidagi obyekt u yerda abadiy «yo'q» bo'lardi, ya'ni
    yolg'on-qizil yoki (filtr olib tashlansa) butun registrning ma'nosi buzilardi.

⚠️  `CREATE TABLE IF NOT EXISTS` O'ZI ISBOT EMAS. Nomi to'g'ri, shakli noto'g'ri jadval
    uni JIM o'tkazib yuboradi va boot «bajarildi» deb o'tardi. Shu bois bu yerda
    ustun (nom+tip+nullability), CHECK (MA'NO bo'yicha — `check_canon`), FK, UNIQUE,
    qisman indeks va triggerlar ANIQ tekshiriladi.

QATTIQLIK: natija — TAYYORLIK QIZIL (`/health/ready` 503), boot TO'XTAMAYDI. Bu
R-DDL dagi ayni naqsh: pul kafolatining O'ZI (ledger yozuvi) hali yo'q, obyekt esa
hech narsa majburlamayapti — ishlab turgan do'konning bootini to'xtatish zarari
foydasidan katta bo'lardi. Buzuq obyekt JIMGINA ALMASHTIRILMAYDI (migratsiya qadamida
DROP/REINDEX yo'q), operator tayyorlikda ko'radi.

QAMROV: faqat PostgreSQL va faqat `cash` sxemasi MAVJUD bo'lganda. SQLite'da cash
quyi tizimi umuman yo'q (`cash_enabled`, `require_ledger_writable`, `is_ledger_authoritative`
bilan ayni qamrov) → muammo YO'Q (yolg'on ogohlantirish bermaymiz).
"""
from __future__ import annotations

from sqlalchemy import text

TABLE = "cash_account_openings"
SCHEMA = "cash"

# (tip, nullable) — `information_schema.columns` atamalarida
COLUMNS = {
    "id": ("uuid", False),
    "tenant_id": ("uuid", False),
    "cash_account_id": ("uuid", False),
    "account_type": ("USER-DEFINED", False),          # cash.cash_account_type
    "kind": ("text", False),
    "counted_amount": ("numeric", False),
    "currency": ("character", False),
    "counted_at": ("timestamp with time zone", False),
    "attested_by": ("uuid", False),
    "attestation_ref": ("text", False),
    "ledger_entry_id": ("uuid", True),                # KNOWN_ZERO uchun NULL
    "created_at": ("timestamp with time zone", False),
}

# CHECK — MATN emas, MA'NO bo'yicha (`check_canon.same_check`)
CHECK_DEFS = {
    "ck_cao_kind": "kind IN ('KNOWN_ZERO','COUNTED')",
    "ck_cao_amount_nonneg": "counted_amount >= 0",
    "ck_cao_kind_amount": "(kind = 'COUNTED') = (counted_amount > 0)",
    "ck_cao_kind_ledger": "(kind = 'COUNTED') = (ledger_entry_id IS NOT NULL)",
    "ck_cao_ref_nb": "attestation_ref <> ''",
    # ⚠️ ENUM ustuni: Postgres ifodani `'SAFE'::cash.cash_account_type` deb SAQLAYDI va
    # `check_canon` KVALIFIKATSIYALANGAN tip keltirishni ATAYLAB olib tashlamaydi (u domen
    # yoki boshqa foydalanuvchi tipi bo'lishi mumkin). Shu bois kutilgan ta'rif ham AYNAN
    # shu shaklda — aks holda tekshiruv har doim yolg'on-qizil bo'lardi.
    "ck_cao_type_safe": "account_type = 'SAFE'::cash.cash_account_type",
}

# FK nomi -> ota-tomon ustunlari (`pg_get_constraintdef` ichida bo'lishi shart)
FOREIGN_KEYS = {
    "cao_acct_type_fk": ("cash_accounts", ("tenant_id", "id", "type")),
    "cao_acct_cur_fk": ("cash_accounts", ("tenant_id", "id", "currency")),
    "cao_entry_fk": ("cash_ledger_entries", ("tenant_id", "id")),
}

UNIQUE_CONSTRAINTS = {
    "cao_uq_account": ("tenant_id", "cash_account_id"),
    "cao_uq_tenant_id": ("tenant_id", "id"),
}

# qisman NOYOB indeks: bitta leg -> bitta ochilish
PARTIAL_UNIQUE = {"cao_uq_entry": "ledger_entry_id IS NOT NULL"}

# trigger nomi -> (qo'riqchi funksiya, kutilgan hodisalar bitmaskasi tekshiruvi uchun nom)
# ⚠️  NOM YETMAYDI: to'g'ri nomli, lekin BOSHQA (masalan bo'sh) funksiyani chaqiradigan
#     trigger jadvalni himoya QILMASDAN "joyida" ko'rinardi — `check_canon` ning CHECK
#     uchun aytgan darsining AYNI o'zi. Shu bois funksiya ham tekshiriladi.
TRIGGERS = {
    "trg_cao_immutable": "fn_block_mutation",
    "trg_cao_no_truncate": "fn_block_truncate",
}

ENUM_TYPE = "cash_source_type"
ENUM_LABEL = "ACCOUNT_OPENING"

_TEXT_COLUMNS = tuple(n for n, (t, _) in COLUMNS.items() if t in ("text", "character"))


def _schema_exists(con) -> bool:
    return con.execute(text(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
        {"s": SCHEMA}).first() is not None


def opening_schema_problems(bind) -> list[str]:
    """Phase 1 obyektlaridagi muammolar ro'yxati (bo'sh = tayyor).

    `bind` — Engine yoki Connection. HECH NARSA YOZMAYDI."""
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return []                       # SQLite/dev — cash quyi tizimi umuman yo'q

    close = False
    con = bind
    if hasattr(bind, "connect"):        # Engine
        con = bind.connect()
        close = True
    try:
        if not _schema_exists(con):
            return []                   # cash o'rnatilmagan — Phase 1 KUTILMAYDI
        return _problems(con)
    except Exception as e:              # tekshirib bo'lmadi != tayyor (fail-closed)
        return [f"cash Phase 1 sxemasini tekshirib bo'lmadi: {e}"]
    finally:
        if close:
            con.close()


def opening_schema_ok(bind) -> bool:
    return not opening_schema_problems(bind)


def _problems(con) -> list[str]:
    from app.core import check_canon as cc

    out: list[str] = []

    # ── enum labeli ─────────────────────────────────────────────────────────
    labels = {r[0] for r in con.execute(text(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = :s AND t.typname = :t"), {"s": SCHEMA, "t": ENUM_TYPE})}
    if ENUM_LABEL not in labels:
        out.append(f"{SCHEMA}.{ENUM_TYPE} da {ENUM_LABEL} labeli YO'Q")

    # ── ustunlar ────────────────────────────────────────────────────────────
    cols = {r[0]: (r[1], r[2] == "YES") for r in con.execute(text(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = :s AND table_name = :t"), {"s": SCHEMA, "t": TABLE})}
    if not cols:
        out.append(f"{SCHEMA}.{TABLE} jadvali YO'Q")
        return out                      # qolgani ma'nosiz
    for name, (typ, nullable) in COLUMNS.items():
        if name not in cols:
            out.append(f"{TABLE}.{name} ustuni YO'Q")
            continue
        got_t, got_n = cols[name]
        if got_t != typ:
            out.append(f"{TABLE}.{name} tipi mos emas: {got_t} != {typ}")
        if got_n != nullable:
            out.append(f"{TABLE}.{name} nullability mos emas: {got_n} != {nullable}")

    # ── CHECK (MA'NO bo'yicha) ──────────────────────────────────────────────
    got_ck = {r[0]: r[1] for r in con.execute(text(
        "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = :s AND t.relname = :t AND c.contype = 'c'"),
        {"s": SCHEMA, "t": TABLE})}
    for name, src in CHECK_DEFS.items():
        if name not in got_ck:
            out.append(f"{name} CHECK YO'Q")
            continue
        defn = got_ck[name]
        try:
            body = defn[defn.index("(") + 1:defn.rindex(")")]
            if not cc.same_check(src, body, text_columns=_TEXT_COLUMNS):
                out.append(f"{name} CHECK ta'rifi BOSHQA: {body}")
        except cc.CanonError as e:       # «tekshirib bo'lmadi» -> baribir QIZIL
            out.append(f"{name} CHECK ta'rifini tahlil qilib bo'lmadi: {e}")
        except ValueError:
            out.append(f"{name} CHECK ta'rifi kutilmagan shaklda: {defn}")

    # ── FK ──────────────────────────────────────────────────────────────────
    got_fk = {r[0]: r[1] for r in con.execute(text(
        "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = :s AND t.relname = :t AND c.contype = 'f'"),
        {"s": SCHEMA, "t": TABLE})}
    for name, (parent, pcols) in FOREIGN_KEYS.items():
        if name not in got_fk:
            out.append(f"{name} FK YO'Q")
            continue
        defn = got_fk[name].replace('"', "")
        if parent not in defn:
            out.append(f"{name} FK boshqa jadvalga: {defn}")
        tail = defn.split("REFERENCES", 1)[-1]
        for c in pcols:
            if c not in tail:
                out.append(f"{name} FK ota ustuni YO'Q ({c}): {defn}")

    # ── UNIQUE cheklovlari ──────────────────────────────────────────────────
    got_u = {r[0]: r[1] for r in con.execute(text(
        "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = :s AND t.relname = :t AND c.contype = 'u'"),
        {"s": SCHEMA, "t": TABLE})}
    for name, ucols in UNIQUE_CONSTRAINTS.items():
        if name not in got_u:
            out.append(f"{name} UNIQUE YO'Q")
            continue
        defn = got_u[name].replace('"', "")
        for c in ucols:
            if c not in defn:
                out.append(f"{name} UNIQUE ustuni YO'Q ({c}): {defn}")

    # ── qisman noyob indeks ─────────────────────────────────────────────────
    got_ix = {r[0]: (bool(r[1]), bool(r[2]), r[3]) for r in con.execute(text(
        "SELECT c.relname, i.indisunique, i.indisvalid AND i.indisready, "
        "       pg_get_indexdef(i.indexrelid) "
        "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_class t ON t.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :s AND t.relname = :t"), {"s": SCHEMA, "t": TABLE})}
    for name, pred in PARTIAL_UNIQUE.items():
        if name not in got_ix:
            out.append(f"{name} indeksi YO'Q")
            continue
        uniq, valid, ddef = got_ix[name]
        if not uniq:
            out.append(f"{name} indeksi NOYOB EMAS")
        if not valid:
            out.append(f"{name} indeksi YAROQSIZ")
        if pred.replace(" ", "") not in ddef.replace(" ", ""):
            out.append(f"{name} predikati mos emas (QISMAN bo'lishi kerak): {ddef}")

    # ── triggerlar (o'zgarmaslik) ───────────────────────────────────────────
    got_tg = {r[0]: r[1] for r in con.execute(text(
        "SELECT tg.tgname, p.proname FROM pg_trigger tg "
        "JOIN pg_class t ON t.oid = tg.tgrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "JOIN pg_proc p ON p.oid = tg.tgfoid "
        "WHERE n.nspname = :s AND t.relname = :t AND NOT tg.tgisinternal"),
        {"s": SCHEMA, "t": TABLE})}
    for name, fn in TRIGGERS.items():
        if name not in got_tg:
            out.append(f"{name} trigger YO'Q (jadval o'zgarmas EMAS)")
        elif got_tg[name] != fn:
            out.append(f"{name} trigger BOSHQA funksiyani chaqiradi: {got_tg[name]} != {fn}")

    return out
