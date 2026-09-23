# -*- coding: utf-8 -*-
"""2026-09-17.uuid-client-columns-v1 — `varchar` qolgan UUID ustunlarini `uuid` ga o'tkazish.

NUQSON. `initdb._ADDED_COLUMNS` `cash_movements.client_uuid`, `qr_payments.sale_id` va
`qr_payments.client_uuid` ni ilgari `VARCHAR` deb qo'shardi, model esa `UUID`. psycopg
dialekti ORM taqqoslashini `ustun = %(p)s::UUID` deb yozadi — varchar ustunda bu 42883
(«operator does not exist: character varying = uuid»): kassa harakati va QR to'lov dedup
so'rovlari HAR SAFAR yiqiladi. Tayyorlik buni `column_types=false` bilan ko'rsatadi
(`required_schema.column_type_problems`), boot esa endi HECH NARSA O'ZGARTIRMAYDI.

NEGA ANIQ MIGRATSIYA (boot ta'miri emas):
  · production sxemasi deploy paytida JIMGINA o'zgarmasin — bu operator qarori;
  · `ALTER TABLE .. TYPE uuid` ACCESS EXCLUSIVE oladi, jadvalni QAYTA YOZADI va jadvalning
    HAR indeksini qayta quradi: qulf band bo'lsa boot FATAL bo'lib crash-loop'ga tushardi;
  · skaner va ALTER orasidagi oynada yozilgan NOKANONIK qiymatni («{uuid}», defisssiz 32 hex)
    Postgres cast'i JIMGINA qabul qilardi — siyosat esa kanonik shaklni talab qiladi;
  · `(shift_id, lower(client_uuid))` bo'yicha REGISTR DUBLIKATI indeks qayta qurilishida
    23505 beradi — buni OLDINDAN, jadvalni qayta yozmasdan bilish kerak.

BOSQICHLAR (hammasi shu modulda, SQL faqat shu yerda):
  `preflight(con)`  — FAQAT O'QISH: identitet, ustun/jadval strukturasi, bog'liqliklar,
                      indekslar, qiymat sinflari (FAQAT SANOQ) -> hukm + `plan_sha256`;
  `apply(con, ..)`  — chaqiruvchining BITTA tranzaksiyasida: qulf -> preflight QAYTA -> reja
                      bir xilmi -> digest -> har jadvalga BITTA `ALTER` -> tranzaksiya ichida
                      yakuniy tekshiruv (tip, indeks, digest). Nomuvofiqlik -> istisno -> ROLLBACK;
  `verify(con)`     — FAQAT O'QISH: katalog + `column_type_problems` + ORM zondlari (42883 yo'q);
  `revert(con, ..)` — simmetrik (`TYPE varchar USING "c"::text`). FAQAT mashq/favqulodda holat:
                      42883 nuqsonini QAYTARADI va asli KATTA HARFLI bo'lgan qiymatlar kichik
                      harfda qoladi (preflight'dagi `canonical_other_case` — o'sha dalil).

⚠️  `TARGETS` MUZLATILGAN. `required_schema.UUID_TYPED_COLUMNS` dan import QILINMAYDI: o'sha
    ro'yxat kelajakda o'zgarsa, BU migratsiya qamrovi o'zgarmasligi kerak (ko'rib chiqilgan
    hisobot boshqa ma'no anglatib qolardi). Qamrov TEST bilan tekshiriladi.
⚠️  Hisobotga QIYMAT tushmaydi — faqat sanoq (`tests/test_uuid_migration_pg.py`).
"""
from __future__ import annotations

import time

from sqlalchemy import text

from .contract import (RESULT_ALREADY_APPLIED, RESULT_APPLIED, RESULT_NOT_APPLICABLE,
                       REPORT_SCHEMA_VERSION, SEVERITY_BLOCK, SEVERITY_INFO, SEVERITY_REVIEW,
                       VERDICT_ALREADY_APPLIED, VERDICT_BLOCKED, VERDICT_NOT_APPLICABLE,
                       VERDICT_READY, MigrationBlocked, MigrationRejected, MigrationVerifyFailed,
                       finding, plan_sha256, seal, split_severity)

MIGRATION_ID = "2026-09-17.uuid-client-columns-v1"
TITLE = "cash_movements.client_uuid / qr_payments.sale_id / qr_payments.client_uuid -> uuid"

# ⚠️  MUZLATILGAN — bu migratsiyaning qamrovi. Boshqa joydan olinmaydi.
TARGETS: tuple[tuple[str, str], ...] = (
    ("cash_movements", "client_uuid"),
    ("qr_payments", "sale_id"),
    ("qr_payments", "client_uuid"),
)
TARGET_TYPE = "uuid"
SOURCE_TYPES = ("varchar", "text")

# Maqsad ustunlarga TEGADIGAN, KUTILADIGAN indekslar. Ro'yxatda yo'q indeks (yoki boshqa
# ta'rif) — BLOKER: `ALTER .. TYPE` jadvalning HAR indeksini qayta quradi.
EXPECTED_INDEXES: dict[str, dict] = {
    "ux_cashmov_client_uuid": {
        "table": "cash_movements",
        "unique": True,
        "columns": ("shift_id", "client_uuid"),
        "predicate": "(client_uuid IS NOT NULL)",
    },
    # Phase 5G FX-A: kassa amali idempotentligining SMENADAN QAT'I NAZAR noyobligi
    # (`initdb._ensure_indexes`). Bu ro'yxat migratsiyaning QAMROVI emas — u `ALTER
    # .. TYPE` QAYTA QURADIGAN indekslar ro'yxati: maqsad ustunga tegadigan HAR
    # indeks bu yerda ATAYLAB sanab o'tilishi shart, aks holda preflight BLOKER
    # beradi (va aksincha — sanalgani yo'q bo'lsa ham BLOKER).
    "ux_cashmov_client_uuid_all": {
        "table": "cash_movements",
        "unique": True,
        "columns": ("client_uuid",),
        "predicate": "(client_uuid IS NOT NULL)",
    },
}

# Noyob kalit ichidagi REGISTR dublikati (uuid'ga o'tgach ular TENG bo'lib qoladi).
UNIQUE_KEY_CHECKS: tuple[dict, ...] = (
    {"index": "ux_cashmov_client_uuid", "table": "cash_movements",
     "key": ("shift_id",), "column": "client_uuid"},
    # Phase 5G FX-A: smenadan QAT'I NAZAR noyoblik — guruh kaliti BO'SH (butun jadval).
    {"index": "ux_cashmov_client_uuid_all", "table": "cash_movements",
     "key": (), "column": "client_uuid"},
)

# Qator soni shu chegaradan oshsa — REVIEW: ACCESS EXCLUSIVE ostidagi qayta yozish uzoq
# davom etadi (escape hatch: expand/contract).
REVIEW_ROW_THRESHOLD = 100_000

# Qulf va bajarilish chegaralari (CLI ularni bekor qila oladi).
LOCK_TIMEOUT_MS_DEFAULT = 2_000
STATEMENT_TIMEOUT_MS_DEFAULT = 60_000
IDLE_IN_TRANSACTION_TIMEOUT_MS_DEFAULT = 60_000

# Kanonik shakl SQL'da BIR MARTA ta'riflanadi (Python nusxasi yo'q — ular farq qilardi):
# aniq belgilar sinfi (diapazon/kolatsiya emas) + 36 BAYT.
_RE_LOWER = ("^[0123456789abcdef]{8}-[0123456789abcdef]{4}-[0123456789abcdef]{4}-"
             "[0123456789abcdef]{4}-[0123456789abcdef]{12}$")
_RE_ANY_CASE = ("^[0123456789abcdefABCDEF]{8}-[0123456789abcdefABCDEF]{4}-"
                "[0123456789abcdefABCDEF]{4}-[0123456789abcdefABCDEF]{4}-"
                "[0123456789abcdefABCDEF]{12}$")

# Bloker/topilma kodlari — O'ZGARMAS (runbook va testlar shularga tayanadi).
CODE_TABLE_MISSING = "UUID_TABLE_MISSING"
CODE_COLUMN_MISSING = "UUID_COLUMN_MISSING"
CODE_UNEXPECTED_TYPE = "UUID_UNEXPECTED_TYPE"
CODE_NOT_PLAIN_TABLE = "UUID_NOT_PLAIN_TABLE"
CODE_COLUMN_HAS_DEFAULT = "UUID_COLUMN_HAS_DEFAULT"
CODE_GENERATED_COLUMN = "UUID_GENERATED_COLUMN"
CODE_UNEXPECTED_DEPENDENCY = "UUID_UNEXPECTED_DEPENDENCY"
CODE_UNEXPECTED_INDEX = "UUID_UNEXPECTED_INDEX"
CODE_INDEX_MISSING = "UUID_EXPECTED_INDEX_MISSING"
CODE_INDEX_NOT_USABLE = "UUID_EXPECTED_INDEX_NOT_USABLE"
CODE_EMPTY_STRING = "UUID_EMPTY_STRING"
CODE_NONCANONICAL = "UUID_NONCANONICAL"
CODE_CASE_DUPLICATE = "UUID_CASE_DUPLICATE_IN_UNIQUE_KEY"
CODE_NOT_OWNER = "UUID_NOT_TABLE_OWNER"
CODE_LARGE_TABLE = "UUID_LARGE_TABLE"
CODE_LOWERCASE_DUPLICATE = "UUID_LOWERCASE_DUPLICATE_INFO"

_TABLES = tuple(dict.fromkeys(t for t, _ in TARGETS))
_COLUMNS = tuple(dict.fromkeys(c for _, c in TARGETS))


# ══ QULFSIZ KATALOG O'QISHLARI ══════════════════════════════════════════════

_SQL_TABLES = text(
    "SELECT c.relname, c.relkind, c.relispartition, c.oid, "
    "       pg_has_role(c.relowner, 'USAGE') AS is_owner, "
    "       (SELECT count(*) FROM pg_inherits i WHERE i.inhparent = c.oid) AS children, "
    "       (SELECT count(*) FROM pg_inherits i WHERE i.inhrelid = c.oid) AS parents "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relname = ANY(:t)")

_SQL_COLUMNS = text(
    "SELECT c.relname, a.attname, a.attnum, ty.typname, a.atttypmod, a.attnotnull, "
    "       pg_get_expr(ad.adbin, ad.adrelid) AS default_expr, co.collname, "
    "       a.attgenerated, a.attidentity "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_attribute a ON a.attrelid = c.oid "
    "JOIN pg_type ty ON ty.oid = a.atttypid "
    "LEFT JOIN pg_attrdef ad ON ad.adrelid = c.oid AND ad.adnum = a.attnum "
    "LEFT JOIN pg_collation co ON co.oid = a.attcollation "
    "WHERE n.nspname = 'public' AND c.relname = ANY(:t) AND a.attname = ANY(:c) "
    "AND a.attnum > 0 AND NOT a.attisdropped")

_SQL_INDEXES = text(
    "SELECT ic.relname AS index_name, tc.relname AS table_name, i.indexrelid, "
    "       i.indisunique, i.indisvalid, i.indisready, i.indisprimary, "
    "       pg_get_indexdef(i.indexrelid) AS definition, "
    "       pg_get_expr(i.indpred, i.indrelid) AS predicate, "
    # Kalit ustunlar ifodasi — `int2vector` ni massivga aylantirmasdan (ifodali indeks ham
    # ko'rinadi, INCLUDE ustunlari kalit emas va bu yerga kirmaydi).
    "       (SELECT array_agg(pg_get_indexdef(i.indexrelid, k.ord::int, true) ORDER BY k.ord) "
    "        FROM generate_series(1, i.indnkeyatts::int) AS k(ord)) AS cols "
    "FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid "
    "JOIN pg_class tc ON tc.oid = i.indrelid "
    "JOIN pg_namespace n ON n.oid = tc.relnamespace "
    "WHERE n.nspname = 'public' AND tc.relname = ANY(:t)")

_SQL_DEPENDS = text(
    "SELECT d.classid::regclass::text AS dep_class, d.objid, d.deptype, "
    "       c.relname AS table_name, a.attname AS column_name, "
    # ⚠️  INDEKS `pg_class` da yashaydi: uning bog'liqligi `classid='pg_index'` EMAS,
    #     `classid='pg_class'` bilan yoziladi. Shuning uchun sinf nomiga emas, BOG'LIQ
    #     obyektning `relkind` iga qaraladi (aks holda har qism indeks ikki marta —
    #     kalit ustun va `WHERE` sharti uchun — «kutilmagan bog'liqlik» bo'lardi).
    "       dc.relkind AS dep_relkind, dc.relname AS dep_relname "
    "FROM pg_depend d JOIN pg_class c ON c.oid = d.refobjid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid "
    "LEFT JOIN pg_class dc ON d.classid = 'pg_class'::regclass AND dc.oid = d.objid "
    "WHERE d.refclassid = 'pg_class'::regclass AND n.nspname = 'public' "
    "AND c.relname = ANY(:t) AND a.attname = ANY(:c) AND d.refobjsubid > 0")

_SQL_DEP_NAME = {
    "pg_constraint": "SELECT conname FROM pg_constraint WHERE oid = :oid",
    "pg_rewrite": ("SELECT (SELECT relname FROM pg_class WHERE oid = r.ev_class) || '.' || "
                   "r.rulename FROM pg_rewrite r WHERE r.oid = :oid"),
    "pg_trigger": "SELECT tgname FROM pg_trigger WHERE oid = :oid",
    "pg_policy": "SELECT polname FROM pg_policy WHERE oid = :oid",
    "pg_statistic_ext": "SELECT stxname FROM pg_statistic_ext WHERE oid = :oid",
    "pg_class": "SELECT relname FROM pg_class WHERE oid = :oid",
}

# Standart qiymat ustun strukturasida (`has_default`) tekshiriladi, shuning uchun
# «kutilmagan bog'liqlik» sifatida IKKI MARTA sanalmaydi.
_DEP_HANDLED_ELSEWHERE = {"pg_attrdef"}
# Indeks relkind'lari: oddiy (`i`) va bo'lingan jadval indeksi (`I`). Ular `EXPECTED_INDEXES`
# bo'yicha ALOHIDA baholanadi — pastdagi indeks siklida.
_INDEX_RELKINDS = {"i", "I"}


def _dep_is_index(row) -> bool:
    return row.dep_class == "pg_class" and (row.dep_relkind or "") in _INDEX_RELKINDS


def is_applicable(con) -> bool:
    return _dialect(con) == "postgresql"


def _dialect(con) -> str:
    return con.engine.dialect.name if hasattr(con, "engine") else con.get_bind().dialect.name


def _q(name: str) -> str:
    """Katalogdan emas, MUZLATILGAN konstantadan kelgan nom — qo'shtirnoq bilan."""
    if not name.replace("_", "").isalnum():
        raise ValueError(f"nom yaroqsiz: {name!r}")
    return f'"{name}"'


def column_types(con) -> dict[tuple[str, str], str]:
    """{(jadval, ustun): pg tip nomi} — QULFSIZ (faqat katalog)."""
    rows = con.execute(_SQL_COLUMNS, {"t": list(_TABLES), "c": list(_COLUMNS)}).fetchall()
    have = {(r.relname, r.attname): r.typname for r in rows}
    return {k: v for k, v in have.items() if k in set(TARGETS)}


def not_applicable_report(con=None) -> dict:
    return seal({
        "schema_version": REPORT_SCHEMA_VERSION,
        "migration_id": MIGRATION_ID,
        "title": TITLE,
        "database": {"dialect": _dialect(con) if con is not None else None,
                     "system_identifier": None, "database": None,
                     "server_version_num": None, "current_user": None},
        "structure": None,
        "values": None,
        "findings": [],
        "verdict": VERDICT_NOT_APPLICABLE,
    })


# ══ PREFLIGHT — FAQAT O'QISH ════════════════════════════════════════════════

def preflight(con, *, row_review_threshold: int = REVIEW_ROW_THRESHOLD) -> dict:
    """Maqsad holatni BAHOLAYDI. Hech narsa yozmaydi, hech narsani cast QILMAYDI.

    Chaqiruvchi read-only (REPEATABLE READ) tranzaksiyani kafolatlaydi; `apply` uni
    ACCESS EXCLUSIVE qulf OSTIDA qayta chaqiradi.
    """
    if not is_applicable(con):
        return not_applicable_report(con)
    from .guard import database_identity

    t0 = time.monotonic()
    findings: list[dict] = []
    ident = database_identity(con)

    tables = {r.relname: r for r in con.execute(_SQL_TABLES, {"t": list(_TABLES)})}
    cols = {(r.relname, r.attname): r
            for r in con.execute(_SQL_COLUMNS, {"t": list(_TABLES), "c": list(_COLUMNS)})}
    dep_rows = list(con.execute(_SQL_DEPENDS, {"t": list(_TABLES), "c": list(_COLUMNS)}))
    ix_rows = list(con.execute(_SQL_INDEXES, {"t": list(_TABLES)}))

    # ── jadvallar ────────────────────────────────────────────────────────────
    # ⚠️  EGALIK `structure` ga KIRMAYDI (ya'ni `plan_sha256` ga ham): u ROLGA bog'liq fakt.
    #     Preflight ko'pincha FAQAT O'QISH login'i bilan, apply esa jadval EGASI bilan
    #     bajariladi — egalikni rejaga qo'shish har bunday juftlikni «holat o'zgardi» deb
    #     RAD etardi.
    table_info, privileges = [], []
    for t in _TABLES:
        r = tables.get(t)
        if r is None:
            findings.append(finding(SEVERITY_BLOCK, CODE_TABLE_MISSING, f"jadval yo'q: {t}"))
            table_info.append({"table": t, "present": False})
            continue
        info = {"table": t, "present": True, "relkind": r.relkind,
                "is_partition": bool(r.relispartition), "partition_children": int(r.children),
                "inherits_parents": int(r.parents)}
        table_info.append(info)
        privileges.append({"table": t, "is_owner": bool(r.is_owner)})
        if r.relkind != "r" or r.relispartition or r.children or r.parents:
            findings.append(finding(SEVERITY_BLOCK, CODE_NOT_PLAIN_TABLE,
                                    f"{t}: oddiy jadval emas (relkind={r.relkind}, "
                                    f"partition={bool(r.relispartition)}, "
                                    f"children={int(r.children)}, parents={int(r.parents)})"))
        if not r.is_owner:
            findings.append(finding(SEVERITY_REVIEW, CODE_NOT_OWNER,
                                    f"{t}: joriy rol jadval egasi emas — APPLY egasi bilan "
                                    "bajarilishi kerak (preflight o'qish uchun yetarli)"))

    # ── ustunlar ─────────────────────────────────────────────────────────────
    column_info, drifted = [], []
    for t, c in TARGETS:
        r = cols.get((t, c))
        if r is None:
            findings.append(finding(SEVERITY_BLOCK, CODE_COLUMN_MISSING, f"ustun yo'q: {t}.{c}"))
            column_info.append({"table": t, "column": c, "present": False})
            continue
        info = {"table": t, "column": c, "present": True, "type": r.typname,
                "typmod": int(r.atttypmod), "not_null": bool(r.attnotnull),
                "has_default": r.default_expr is not None, "collation": r.collname,
                "generated": (r.attgenerated or ""), "identity": (r.attidentity or "")}
        column_info.append(info)
        if r.typname == TARGET_TYPE:
            pass
        elif r.typname in SOURCE_TYPES:
            drifted.append((t, c))
        else:
            findings.append(finding(SEVERITY_BLOCK, CODE_UNEXPECTED_TYPE,
                                    f"{t}.{c}: tipi {r.typname} — kutilgan "
                                    f"{TARGET_TYPE} yoki {'/'.join(SOURCE_TYPES)}"))
        if r.default_expr is not None:
            findings.append(finding(SEVERITY_BLOCK, CODE_COLUMN_HAS_DEFAULT,
                                    f"{t}.{c}: ustunda standart qiymat bor"))
        if (r.attgenerated or "") or (r.attidentity or ""):
            findings.append(finding(SEVERITY_BLOCK, CODE_GENERATED_COLUMN,
                                    f"{t}.{c}: generated/identity ustun"))

    # ── bog'liqliklar (ko'rinish, qoida, trigger, siyosat, cheklov, statistika) ─
    dep_index_oids = {int(r.objid) for r in dep_rows if _dep_is_index(r)}
    dependencies = []
    for r in dep_rows:
        if _dep_is_index(r) or r.dep_class in _DEP_HANDLED_ELSEWHERE:
            continue
        sql = _SQL_DEP_NAME.get(r.dep_class)
        name = None
        if sql:
            name = con.execute(text(sql), {"oid": int(r.objid)}).scalar()
        dep = {"table": r.table_name, "column": r.column_name, "class": r.dep_class,
               "name": name, "deptype": r.deptype}
        dependencies.append(dep)
        findings.append(finding(SEVERITY_BLOCK, CODE_UNEXPECTED_DEPENDENCY,
                                f"{r.table_name}.{r.column_name}: kutilmagan bog'liqlik "
                                f"({r.dep_class}: {name or r.objid})"))

    # ── indekslar ────────────────────────────────────────────────────────────
    index_info, seen_expected = [], set()
    for r in ix_rows:
        cols_list = list(r.cols or [])
        touches = (int(r.indexrelid) in dep_index_oids
                   or any(c in cols_list for t, c in TARGETS if t == r.table_name))
        if not touches:
            continue
        exp = EXPECTED_INDEXES.get(r.index_name)
        info = {"name": r.index_name, "table": r.table_name, "definition": r.definition,
                "unique": bool(r.indisunique), "valid": bool(r.indisvalid),
                "ready": bool(r.indisready), "primary": bool(r.indisprimary),
                "columns": cols_list, "predicate": _norm(r.predicate),
                "expected": exp is not None}
        index_info.append(info)
        if exp is None:
            findings.append(finding(SEVERITY_BLOCK, CODE_UNEXPECTED_INDEX,
                                    f"{r.table_name}: kutilmagan indeks {r.index_name} "
                                    "maqsad ustunga tegadi"))
            continue
        seen_expected.add(r.index_name)
        mismatch = []
        if r.table_name != exp["table"]:
            mismatch.append("jadval")
        if bool(r.indisunique) != exp["unique"]:
            mismatch.append("noyoblik")
        if tuple(cols_list) != tuple(exp["columns"]):
            mismatch.append("ustunlar")
        if _norm(r.predicate) != _norm(exp["predicate"]):
            mismatch.append("shart")
        if mismatch:
            findings.append(finding(SEVERITY_BLOCK, CODE_UNEXPECTED_INDEX,
                                    f"{r.index_name}: ta'rifi kutilganidan farq qiladi "
                                    f"({', '.join(mismatch)})"))
        elif not (r.indisvalid and r.indisready):
            findings.append(finding(SEVERITY_BLOCK, CODE_INDEX_NOT_USABLE,
                                    f"{r.index_name}: yaroqsiz yoki tayyor emas — "
                                    "`ALTER .. TYPE` uni qayta quradi"))
    for name in EXPECTED_INDEXES:
        if name not in seen_expected:
            findings.append(finding(SEVERITY_BLOCK, CODE_INDEX_MISSING,
                                    f"kutilgan indeks yo'q: {name}"))

    structure = {"tables": table_info, "columns": column_info,
                 "indexes": sorted(index_info, key=lambda x: x["name"]),
                 "dependencies": sorted(dependencies,
                                        key=lambda x: (x["table"], x["column"], x["class"],
                                                       str(x["name"])))}

    # ── qiymat sinflari — FAQAT SANOQ, hech qachon cast QILINMAYDI ───────────
    values = {"columns": [], "case_duplicates": [], "lowercase_duplicates": []}
    structural_block = bool(split_severity(findings)[0])
    if not structural_block:
        for t, c in drifted:
            row = con.execute(text(
                f'SELECT count(*) AS total_count, '
                f'count(*) FILTER (WHERE {_q(c)} IS NULL) AS null_count, '
                f"count(*) FILTER (WHERE {_q(c)} = '') AS empty_count, "
                f"count(*) FILTER (WHERE {_q(c)} <> '' AND octet_length({_q(c)}) = 36 "
                f'  AND {_q(c)} ~ :lo) AS canonical_lower, '
                f"count(*) FILTER (WHERE {_q(c)} <> '' AND octet_length({_q(c)}) = 36 "
                f'  AND {_q(c)} !~ :lo AND {_q(c)} ~ :any) AS canonical_other_case, '
                f"count(*) FILTER (WHERE {_q(c)} IS NOT NULL AND {_q(c)} <> '' "
                f'  AND NOT (octet_length({_q(c)}) = 36 AND {_q(c)} ~ :any)) AS noncanonical '
                f'FROM public.{_q(t)}'), {"lo": _RE_LOWER, "any": _RE_ANY_CASE}).one()
            v = {"table": t, "column": c, "rows": int(row.total_count),
                 "null": int(row.null_count), "empty": int(row.empty_count),
                 "canonical_lower": int(row.canonical_lower),
                 "canonical_other_case": int(row.canonical_other_case),
                 "noncanonical": int(row.noncanonical)}
            values["columns"].append(v)
            if v["empty"]:
                findings.append(finding(SEVERITY_BLOCK, CODE_EMPTY_STRING,
                                        f"{t}.{c}: bo'sh satr {v['empty']} ta"))
            if v["noncanonical"]:
                findings.append(finding(SEVERITY_BLOCK, CODE_NONCANONICAL,
                                        f"{t}.{c}: kanonik BO'LMAGAN qiymat "
                                        f"{v['noncanonical']} ta"))
            if v["rows"] > row_review_threshold:
                findings.append(finding(SEVERITY_REVIEW, CODE_LARGE_TABLE,
                                        f"{t}: {v['rows']} qator — ACCESS EXCLUSIVE ostidagi "
                                        "qayta yozish uzoq davom etadi"))

        drifted_set = set(drifted)
        for chk in UNIQUE_KEY_CHECKS:
            if (chk["table"], chk["column"]) not in drifted_set:
                continue
            # ⚠️  `key` BO'SH bo'lishi mumkin (butun jadval bo'yicha noyob indeks —
            #     `ux_cashmov_client_uuid_all`): u holda guruh faqat qiymatning o'zi.
            sel = [_q(k) for k in chk["key"]] + [f'lower({_q(chk["column"])}::text)']
            n = int(con.execute(text(
                f'SELECT count(*) FROM (SELECT {", ".join(sel)} '
                f'FROM public.{_q(chk["table"])} WHERE {_q(chk["column"])} IS NOT NULL '
                f'GROUP BY {", ".join(str(i + 1) for i in range(len(sel)))} '
                f'HAVING count(*) > 1) d')).scalar() or 0)
            values["case_duplicates"].append({"index": chk["index"], "table": chk["table"],
                                              "column": chk["column"], "groups": n})
            if n:
                findings.append(finding(SEVERITY_BLOCK, CODE_CASE_DUPLICATE,
                                        f"{chk['index']}: registr dublikati {n} guruh — "
                                        "uuid'ga o'tgach noyoblik buziladi (23505)"))

        covered = {(c["table"], c["column"]) for c in UNIQUE_KEY_CHECKS}
        for t, c in drifted:
            if (t, c) in covered:
                continue
            n = int(con.execute(text(
                f'SELECT count(*) FROM (SELECT lower({_q(c)}::text) FROM public.{_q(t)} '
                f'WHERE {_q(c)} IS NOT NULL GROUP BY 1 HAVING count(*) > 1) d')).scalar() or 0)
            values["lowercase_duplicates"].append({"table": t, "column": c, "groups": n})
            if n:
                findings.append(finding(SEVERITY_INFO, CODE_LOWERCASE_DUPLICATE,
                                        f"{t}.{c}: registrsiz dublikat {n} guruh — noyob "
                                        "indeks yo'q, migratsiyaga to'siq emas"))

    block, review, _info = split_severity(findings)
    if block:
        verdict = VERDICT_BLOCKED
    elif drifted:
        verdict = VERDICT_READY
    else:
        verdict = VERDICT_ALREADY_APPLIED
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "migration_id": MIGRATION_ID,
        "title": TITLE,
        "database": ident,
        "structure": structure,
        "privileges": {"tables": privileges},      # rejaga KIRMAYDI (rolga bog'liq)
        "values": values,
        "drifted": [{"table": t, "column": c} for t, c in drifted],
        "findings": findings,
        "verdict": verdict,
        "review_count": len(review),
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }
    return seal(report)


def _norm(expr) -> str | None:
    return None if expr is None else " ".join(str(expr).split())


# ══ APPLY / REVERT — CHAQIRUVCHINING BITTA TRANZAKSIYASIDA ══════════════════

def apply(con, *, reviewed_report: dict, lock_timeout_ms: int = LOCK_TIMEOUT_MS_DEFAULT,
          statement_timeout_ms: int = STATEMENT_TIMEOUT_MS_DEFAULT,
          idle_timeout_ms: int = IDLE_IN_TRANSACTION_TIMEOUT_MS_DEFAULT) -> dict:
    """`varchar/text` -> `uuid`. Qiymatlar `lower(..)::uuid` bilan KANONIK ko'chiriladi."""
    return _change_type(con, to_target=True, reviewed_report=reviewed_report,
                        lock_timeout_ms=lock_timeout_ms,
                        statement_timeout_ms=statement_timeout_ms, idle_timeout_ms=idle_timeout_ms)


def revert(con, *, reviewed_report: dict, lock_timeout_ms: int = LOCK_TIMEOUT_MS_DEFAULT,
           statement_timeout_ms: int = STATEMENT_TIMEOUT_MS_DEFAULT,
           idle_timeout_ms: int = IDLE_IN_TRANSACTION_TIMEOUT_MS_DEFAULT) -> dict:
    """`uuid` -> `varchar` (`::text`). FAQAT mashq/favqulodda: 42883 nuqsoni QAYTADI."""
    return _change_type(con, to_target=False, reviewed_report=reviewed_report,
                        lock_timeout_ms=lock_timeout_ms,
                        statement_timeout_ms=statement_timeout_ms, idle_timeout_ms=idle_timeout_ms)


def _change_type(con, *, to_target: bool, reviewed_report: dict, lock_timeout_ms: int,
                 statement_timeout_ms: int, idle_timeout_ms: int) -> dict:
    direction = "apply" if to_target else "revert"
    if not is_applicable(con):
        return {"migration_id": MIGRATION_ID, "direction": direction,
                "result": RESULT_NOT_APPLICABLE, "ddl": [], "locked_tables": []}
    t0 = time.monotonic()
    for guc, val in (("lock_timeout", lock_timeout_ms), ("statement_timeout", statement_timeout_ms),
                     ("idle_in_transaction_session_timeout", idle_timeout_ms)):
        con.execute(text(f"SET LOCAL {guc} = '{int(val)}ms'"))
    con.execute(text("SET LOCAL application_name = 'savdoos_schema_migrate'"))

    # 1) QULFSIZ katalog o'qishi. Maqsad holat joyida bo'lsa — LOCK ham, DDL ham YO'Q.
    have = column_types(con)
    yoq = [f"{t}.{c}" for t, c in TARGETS if (t, c) not in have]
    if yoq:
        # Ustunning O'ZI yo'q — bu boot ishi (`_ensure_columns`, MAJBURIY ustun), migratsiya
        # uni YARATMAYDI: yo'q ustunni «allaqachon qo'llangan» deb hisoblash yolg'on bo'lardi.
        raise MigrationBlocked(f"maqsad ustun yo'q: {', '.join(sorted(yoq))}")
    want = TARGET_TYPE if to_target else SOURCE_TYPES[0]
    todo = [(t, c) for t, c in TARGETS if have.get((t, c)) != want]
    if not todo:
        return {"migration_id": MIGRATION_ID, "direction": direction,
                "result": RESULT_ALREADY_APPLIED, "ddl": [], "locked_tables": [],
                "column_types": {f"{t}.{c}": v for (t, c), v in sorted(have.items())},
                "duration_ms": int((time.monotonic() - t0) * 1000)}
    allowed_from = SOURCE_TYPES if to_target else (TARGET_TYPE,)
    bad = [f"{t}.{c}={have.get((t, c))}" for t, c in todo if have.get((t, c)) not in allowed_from]
    if bad:
        raise MigrationBlocked(f"kutilmagan ustun tipi: {', '.join(sorted(bad))}")

    # 2) QULF — jadvallar TARTIBLANGAN nomda (deadlock tartibi barqaror bo'lsin).
    tables = sorted({t for t, _ in todo})
    lock_t0 = time.monotonic()
    con.execute(text("LOCK TABLE " + ", ".join(f"public.{_q(t)}" for t in tables)
                     + " IN ACCESS EXCLUSIVE MODE"))
    lock_ms = int((time.monotonic() - lock_t0) * 1000)

    # 3) Qulf OSTIDA preflight QAYTA — reja va baza AYNI bo'lishi SHART.
    now = preflight(con)
    _assert_same_plan(now, reviewed_report)
    if split_severity(now["findings"])[0]:
        raise MigrationBlocked("qulf ostida bloker topildi: "
                               + "; ".join(f["code"] for f in split_severity(now["findings"])[0]))
    # Egalik preflight'da REVIEW (o'qish login'i ham hisobot tayyorlay olsin), APPLY'da esa
    # SHART: `ALTER TABLE` faqat jadval egasida ishlaydi.
    not_owner = [p["table"] for p in now["privileges"]["tables"] if not p["is_owner"]]
    if not_owner:
        raise MigrationBlocked(f"jadval egasi emas: {', '.join(sorted(not_owner))} — "
                               "APPLY egasi (yoki uning roli) bilan bajarilishi kerak")

    # 4) Qulf ostidagi indeks ta'riflari — ALTER ulardan birortasini o'zgartirmasligi kerak.
    ix_before = {i["name"]: i["definition"] for i in now["structure"]["indexes"]}
    before = {f"{t}.{c}": _digest(con, t, c) for t, c in todo}

    # 5) DDL — har jadvalga BITTA `ALTER` (jadval BIR MARTA qayta yoziladi).
    ddl = []
    for t in tables:
        parts = []
        for tt, c in todo:
            if tt != t:
                continue
            parts.append(f'ALTER COLUMN {_q(c)} TYPE uuid USING lower({_q(c)})::uuid' if to_target
                         else f'ALTER COLUMN {_q(c)} TYPE varchar USING {_q(c)}::text')
        stmt = f'ALTER TABLE public.{_q(t)} ' + ", ".join(parts)
        con.execute(text(stmt))
        ddl.append(stmt)

    # 6) TRANZAKSIYA ICHIDAGI yakuniy tekshiruv — nomuvofiqlikda hammasi QAYTADI.
    after_types = column_types(con)
    wrong = {f"{t}.{c}": after_types.get((t, c)) for t, c in TARGETS
             if after_types.get((t, c)) != want}
    if wrong:
        raise MigrationVerifyFailed(f"tip o'zgarmadi: {sorted(wrong)}")
    post = preflight(con)
    _assert_structure_unchanged(now, post, ix_before)
    after = {f"{t}.{c}": _digest(con, t, c) for t, c in todo}
    if after != before:
        raise MigrationVerifyFailed("qiymat digest'i mos emas — qiymatlar saqlanmadi")
    return {"migration_id": MIGRATION_ID, "direction": direction, "result": RESULT_APPLIED,
            "ddl": ddl, "locked_tables": tables, "lock_wait_ms": lock_ms,
            "changed": [f"{t}.{c}" for t, c in todo],
            "digest": {k: v["digest"] for k, v in sorted(after.items())},
            "rows": {k: v["rows"] for k, v in sorted(after.items())},
            "plan_sha256": now["plan_sha256"],
            "duration_ms": int((time.monotonic() - t0) * 1000)}


def _digest(con, table: str, col: str) -> dict:
    """(qator soni, NULL bo'lmaganlar, md5) — `id` bo'yicha tartiblangan KICHIK HARFLI matn.

    `::text` ikkala tipda ham ishlaydi, shuning uchun ALTER'dan oldin va keyin AYNI qiymat.
    """
    r = con.execute(text(
        f'SELECT count(*) AS row_count, count({_q(col)}) AS non_null, '
        f'md5(coalesce(string_agg("id"::text || \'=\' || coalesce(lower({_q(col)}::text), \'-\'), '
        f'\',\' ORDER BY "id"::text), \'\')) AS digest FROM public.{_q(table)}')).one()
    return {"rows": int(r.row_count), "non_null": int(r.non_null), "digest": r.digest}


def _assert_same_plan(now: dict, reviewed: dict) -> None:
    if not isinstance(reviewed, dict):
        raise MigrationRejected("ko'rib chiqilgan hisobot berilmagan")
    if reviewed.get("migration_id") != MIGRATION_ID:
        raise MigrationRejected(f"hisobot boshqa migratsiya uchun: {reviewed.get('migration_id')}")
    a, b = now["database"], reviewed.get("database") or {}
    if (a.get("system_identifier"), a.get("database")) != (b.get("system_identifier"),
                                                           b.get("database")):
        raise MigrationRejected("REJECTED_STATE_CHANGED: hisobot BOSHQA bazada tayyorlangan")
    if reviewed.get("plan_sha256") != plan_sha256(reviewed):
        raise MigrationRejected("REJECTED_STATE_CHANGED: hisobotdagi plan_sha256 hisobotga mos emas")
    if now["plan_sha256"] != reviewed.get("plan_sha256"):
        raise MigrationRejected("REJECTED_STATE_CHANGED: sxema ko'rib chiqilgandan keyin "
                                "o'zgargan — preflight QAYTA bajarilsin")


def _assert_structure_unchanged(before: dict, after: dict, ix_before: dict) -> None:
    for name, definition in ix_before.items():
        got = [i for i in after["structure"]["indexes"] if i["name"] == name]
        if not got:
            raise MigrationVerifyFailed(f"indeks yo'qoldi: {name}")
        ix = got[0]
        if ix["definition"] != definition:
            raise MigrationVerifyFailed(f"indeks ta'rifi o'zgardi: {name}")
        if not (ix["valid"] and ix["ready"]):
            raise MigrationVerifyFailed(f"indeks yaroqsiz yoki tayyor emas: {name}")
        exp = EXPECTED_INDEXES.get(name)
        if exp and ix["unique"] != exp["unique"]:
            raise MigrationVerifyFailed(f"indeks noyobligi o'zgardi: {name}")
    a = {(c["table"], c["column"]): (c.get("not_null"), c.get("has_default"), c.get("generated"),
                                     c.get("identity")) for c in before["structure"]["columns"]}
    b = {(c["table"], c["column"]): (c.get("not_null"), c.get("has_default"), c.get("generated"),
                                     c.get("identity")) for c in after["structure"]["columns"]}
    if a != b:
        raise MigrationVerifyFailed("ustun NULL/standart/generated xossalari o'zgardi")


# ══ VERIFY — FAQAT O'QISH ═══════════════════════════════════════════════════

def verify(con, *, bind=None) -> dict:
    """Katalog + `column_type_problems` + ORM zondlari (42883 bo'lmasligi)."""
    if not is_applicable(con):
        return {"migration_id": MIGRATION_ID, "result": RESULT_NOT_APPLICABLE, "ok": True,
                "problems": []}
    import uuid as _uuid

    from sqlalchemy import select

    from app.core import required_schema as rs
    from app.models.payments import QrPayment
    from app.models.shifts import CashMovement

    problems: list[str] = []
    have = column_types(con)
    for t, c in TARGETS:
        got = have.get((t, c))
        if got != TARGET_TYPE:
            problems.append(f"{t}.{c}: tip {got or 'yo`q'}")
    report = preflight(con)
    for f in split_severity(report["findings"])[0]:
        problems.append(f"{f['code']}: {f['detail']}")
    try:
        problems += rs.column_type_problems(bind if bind is not None else con.engine)
    except Exception as e:      # noqa: BLE001
        problems.append(f"tayyorlik tekshiruvi yiqildi (SQLSTATE "
                        f"{getattr(getattr(e, 'orig', None), 'sqlstate', None) or '?'})")
    probes = (select(CashMovement.id).where(CashMovement.client_uuid == _uuid.uuid4()),
              select(QrPayment.id).where(QrPayment.sale_id == _uuid.uuid4()),
              select(QrPayment.id).where(QrPayment.client_uuid == _uuid.uuid4()))
    probe_ok = []
    for q in probes:
        # ⚠️  Har zond SAVEPOINT ichida: varchar ustunda 42883 TRANZAKSIYANI buzadi va keyingi
        #     o'qishlar 25P02 bilan yiqilardi (read-only isboti ham).
        sp = con.begin_nested()
        try:
            con.execute(q).all()
            sp.rollback()
            probe_ok.append(True)
        except Exception as e:      # noqa: BLE001
            sp.rollback()
            probe_ok.append(False)
            problems.append("ORM zondi yiqildi (SQLSTATE "
                            f"{getattr(getattr(e, 'orig', None), 'sqlstate', None) or '?'})")
    return {"migration_id": MIGRATION_ID, "result": "VERIFIED" if not problems else "FAILED",
            "ok": not problems, "problems": problems, "verdict": report["verdict"],
            "orm_probes_ok": all(probe_ok),
            "column_types": {f"{t}.{c}": have.get((t, c)) for t, c in TARGETS}}
