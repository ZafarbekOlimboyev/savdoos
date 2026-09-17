# -*- coding: utf-8 -*-
"""ISH VAQTI USTUNLARI / INDEKSLARI TASNIFI va UUID TIP OG'ISHI (Phase 5B.1) — SQLite / birlik.

⚠️  NUQSON 1. `initdb._ADDED_COLUMNS` dagi 150 ustundan 41 tasi (+ yon yo'ldagi
    `product_barcodes.company_id`) hech qaysi sinfda emas edi: qo'shish yiqilsa bitta
    «o'tkazib yuborildi» satri, tayyorlik YASHIL. Holbuki ulardan 40 tasi ORM'da
    xaritalangan — ustun yo'q bo'lsa o'sha modelning HAR `select(Model)` va HAR INSERT'i
    yiqiladi (`employees.sec_epoch` -> har autentifikatsiyalangan so'rov 500).
⚠️  NUQSON 2. `cash_movements.client_uuid`, `qr_payments.sale_id/client_uuid` boot'da `VARCHAR`
    deb qo'shilardi, model esa UUID — Postgres'da ORM taqqoslashi 42883 bilan yiqiladi.
⚠️  NUQSON 3. Boot quradigan 56 indeksdan 30 tasi tasniflanmagan: 11 pul/qoldiq/auth
    idempotentlik noyob indeksi yo'qolsa ham tayyorlik YASHIL edi.

Bu fayl (Postgres'siz) mixlaydi:
  T1 · xaritalangan har qo'shilgan ustun MAJBURIY, qolgani ANIQ ruxsat ro'yxatida, ro'yxat eskirmagan;
  T2 · `ADD COLUMN` faqat `_ensure_columns` va tenancy migratsiyasida (yon yo'l yo'q);
  T3 · boot SQL tipi oilasi model tipi bilan AYNI (uuid / numeric aniqligi / varchar uzunligi ...);
  T4 · boot quradigan HAR indeks AYNAN BITTA sinfda, jadvali va noyobligi mos;
  T5 · asosiy fakt: xaritalangan ustun yo'q -> model so'rovi yiqiladi (eager load orqali ham);
  · tayyorlik: `idempotency_schema` / `column_types` kalitlari, fail-closed, production redaksiyasi,
    partiya aktivatsiyasi ularga BOG'LIQ EMAS;
  · `_repair_uuid_type_drift` tasnifi (soxta Postgres engine): barqarorda NOL so'rov, kanonik
    qiymat -> ALTER, UUID bo'lmagan qiymat -> DDL yo'q + TAYYOR EMAS, qulf -> FATAL.

Haqiqiy Postgres (tip tuzatish, 42883, yaroqsiz indeks, qulf ostida FATAL) —
`tests/test_runtime_columns_pg.py`.
"""
import ast
import contextlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import types
import uuid
from datetime import date, datetime, timezone

import psycopg.errors
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.initdb as I
from app.core import required_schema as rs
from tests.test_boot_locks import _func, _literals, _lock_err

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══ T1. XARITALANGAN QO'SHILGAN USTUN — MAJBURIY ════════════════════════════

def _mapped_columns() -> set[tuple[str, str]]:
    """ORM mapper'lari HAQIQATAN xaritalagan (jadval, ustun) juftliklari."""
    import app.models  # noqa: F401
    from app.db.base import Base
    out = set()
    for m in Base.registry.mappers:
        for prop in m.column_attrs:
            for col in prop.columns:
                if isinstance(col, sa.Column) and isinstance(col.table, sa.Table):
                    out.add((col.table.name, col.name))
    return out


def _t1_problems(added, mapped, required, unmapped) -> list[str]:
    required = set(required)
    added_set = set(added)
    bad = [f"xaritalangan, lekin MAJBURIY emas: {t}.{c}"
           for t, c in added if (t, c) in mapped and (t, c) not in required]
    bad += [f"xaritalanmagan, lekin UNMAPPED_ADDED_COLUMNS da yo'q: {t}.{c}"
            for t, c in added if (t, c) not in mapped and (t, c) not in unmapped]
    bad += [f"UNMAPPED_ADDED_COLUMNS eskirgan (xaritalangan yoki boot qo'shmaydi): {t}.{c}"
            for t, c in sorted(unmapped) if (t, c) in mapped or (t, c) not in added_set]
    bad += [f"ham MAJBURIY, ham XARITALANMAGAN: {t}.{c}" for t, c in sorted(required & set(unmapped))]
    bad += [f"MAJBURIY, lekin xaritalanmagan: {t}.{c}" for t, c in sorted(required - mapped)]
    return bad


def test_T1_ORM_xaritalangan_boot_ustuni_MAJBURIY_qolgani_ANIQ_royxatda():
    mapped = _mapped_columns()
    assert len(mapped) > 500, f"mapper'lar juda kam ustun berdi ({len(mapped)}) — tahlil buzilgan"
    added = [(t, c) for t, c, _ in I._ADDED_COLUMNS]
    assert len(added) == len(set(added)), "_ADDED_COLUMNS da takror juftlik"
    bad = _t1_problems(added, mapped, rs.REQUIRED_COLUMNS, rs.UNMAPPED_ADDED_COLUMNS)
    assert not bad, ("ustun yiqilsa boot uni JIMGINA o'tkazib yuborardi, model esa HAR so'rovda "
                     "yiqilardi:\n  " + "\n  ".join(bad))
    # yon yo'ldagi ustun ham umumiy yo'lga ko'chgan (T2 buni DDL tomonidan tutadi)
    assert ("product_barcodes", "company_id") in set(added)
    assert ("product_barcodes", "company_id") in set(rs.REQUIRED_COLUMNS)


def test_T1_salbiy_nazorat_qoriqchi_BUZILISHNI_KORADI():
    mapped = _mapped_columns()
    added = [(t, c) for t, c, _ in I._ADDED_COLUMNS]
    req = [p for p in rs.REQUIRED_COLUMNS if p != ("employees", "sec_epoch")]
    assert _t1_problems(added, mapped, req, rs.UNMAPPED_ADDED_COLUMNS) == [
        "xaritalangan, lekin MAJBURIY emas: employees.sec_epoch"]
    assert _t1_problems(added, mapped, rs.REQUIRED_COLUMNS, frozenset()) == [
        "xaritalanmagan, lekin UNMAPPED_ADDED_COLUMNS da yo'q: purchase_items.batch_no"]
    stale = rs.UNMAPPED_ADDED_COLUMNS | {("sales", "till_id"), ("purchase_items", "yoq_ustun")}
    got = _t1_problems(added, mapped, rs.REQUIRED_COLUMNS, stale)
    assert "UNMAPPED_ADDED_COLUMNS eskirgan (xaritalangan yoki boot qo'shmaydi): sales.till_id" in got
    assert ("UNMAPPED_ADDED_COLUMNS eskirgan (xaritalangan yoki boot qo'shmaydi): "
            "purchase_items.yoq_ustun") in got
    assert "ham MAJBURIY, ham XARITALANMAGAN: sales.till_id" in got


# ══ T2. ADD COLUMN — FAQAT UMUMIY YO'LDA ═════════════════════════════════════

#  `_ensure_columns` — cheklangan urinish + tasnif; `_migrate_one` — tenancy (qulfli, FATAL).
_ADD_COLUMN_ALLOWED = frozenset({"_ensure_columns", "_migrate_one"})
_ADD_COLUMN = re.compile(r"\bADD\s+COLUMN\b", re.IGNORECASE)


def _add_column_violations(src: str) -> tuple[list[str], int]:
    tree = ast.parse(src)
    bad, n = [], 0
    for lit, chain in _literals(tree):
        if not _ADD_COLUMN.search(lit.value):
            continue
        n += 1
        funcs = {p.name for p in chain if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if not funcs & _ADD_COLUMN_ALLOWED:
            fn = _func(chain)
            bad.append(f"{lit.lineno}: `{fn.name if fn else '<modul>'}` da ADD COLUMN: "
                       f"{lit.value[:60]!r}")
    return bad, n


def test_T2_ADD_COLUMN_faqat_ensure_columns_va_tenancy_migratsiyasida():
    bad, n = _add_column_violations(pathlib.Path(I.__file__).read_text(encoding="utf-8"))
    assert not bad, ("ustun yon yo'lda qo'shiladi — cheklangan urinish ham, MAJBURIY tasnif ham "
                     "yo'q:\n  " + "\n  ".join(bad))
    assert n >= 3, f"ADD COLUMN literallari juda kam ({n}) — tahlil buzilgan"


def test_T2_salbiy_nazorat_ESKI_barkod_yon_yolini_USHLAYDI():
    eski = (
        "def _ensure_columns():\n"
        "    def _add(table, col, _type):\n"
        "        con.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {_type}'))\n"
        "def _migrate_barcodes_per_company():\n"
        "    \"\"\"docstring: ADD COLUMN — hisobga olinmaydi.\"\"\"\n"
        "    con.execute(text(f\"ALTER TABLE product_barcodes ADD COLUMN company_id {coltype}\"))\n"
    )
    bad, n = _add_column_violations(eski)
    assert n == 2 and len(bad) == 1 and "_migrate_barcodes_per_company" in bad[0], (n, bad)


# ══ T3. BOOT TIPI == MODEL TIPI ══════════════════════════════════════════════

_BOOT_TYPE = re.compile(r"\s*([A-Z]+)(?:\((\d+)(?:\s*,\s*(\d+))?\))?")


def _type_mismatches(entries, tables) -> list[str]:
    bad = []
    for t, c, sqltype in entries:
        if t not in tables or c not in tables[t].c:
            continue                                   # xaritalanmagan — T1 ning ishi
        typ = tables[t].c[c].type
        m = _BOOT_TYPE.match(sqltype.upper())
        base, p1, p2 = m.group(1), m.group(2), m.group(3)
        if base == "UUID":
            ok = isinstance(typ, sa.Uuid)
        elif base == "TIMESTAMPTZ":
            ok = isinstance(typ, sa.DateTime) and bool(typ.timezone)
        elif base == "BOOLEAN":
            ok = isinstance(typ, sa.Boolean)
        elif base == "INTEGER":
            ok = isinstance(typ, sa.Integer) and not isinstance(typ, sa.BigInteger)
        elif base == "NUMERIC":
            ok = (isinstance(typ, sa.Numeric) and not isinstance(typ, sa.Float)
                  and (typ.precision, typ.scale) == (int(p1) if p1 else None,
                                                     int(p2) if p2 else None))
        elif base == "DATE":
            ok = isinstance(typ, sa.Date)
        elif base == "VARCHAR":
            ok = (isinstance(typ, sa.String) and not isinstance(typ, (sa.Text, sa.Enum))
                  and typ.length == (int(p1) if p1 else None))
        elif base == "TEXT":
            ok = isinstance(typ, sa.Text)
        else:
            bad.append(f"{t}.{c}: noma'lum boot tipi {sqltype!r} (qo'riqchiga qo'shing)")
            continue
        if not ok:
            bad.append(f"{t}.{c}: boot {sqltype!r}, model {typ!r}")
    return bad


def test_T3_boot_ustun_TIPI_model_tipi_bilan_MOS():
    import app.models  # noqa: F401
    from app.db.base import Base
    bad = _type_mismatches(I._ADDED_COLUMNS, Base.metadata.tables)
    assert not bad, ("boot model kutganidan BOSHQA tipli ustun qo'shardi (Postgres'da ORM "
                     "taqqoslashi/yozuvi yiqiladi):\n  " + "\n  ".join(bad))


def test_T3_salbiy_nazorat_ESKI_VARCHAR_va_aniqlik_farqini_USHLAYDI():
    import app.models  # noqa: F401
    from app.db.base import Base
    got = _type_mismatches([("cash_movements", "client_uuid", "VARCHAR"),
                            ("sale_items", "cost_total", "NUMERIC(14,3)"),
                            ("lot_shortfall_resolution_requests", "request_hash", "VARCHAR"),
                            ("products", "lots_activated_at", "DATE"),
                            ("sales", "cost_basis", "VARCHAR")], Base.metadata.tables)
    assert [g.split(":")[0] for g in got] == [
        "cash_movements.client_uuid", "sale_items.cost_total",
        "lot_shortfall_resolution_requests.request_hash", "products.lots_activated_at"], got


# ══ T4. HAR BOOT INDEKSI — AYNAN BITTA SINFDA ════════════════════════════════

_IX_LITERAL = re.compile(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS\s+"
                         r"(\w+)\s+ON\s+(?:public\.)?\"?(\w+)", re.IGNORECASE)
_IX_TEMPLATE = re.compile(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS\s+"
                          r"\{(\w+)\}\s*(?:ON\s+(?:public\.)?\"?(\w+)|\{(\w+)\})", re.IGNORECASE)
_ON_TABLE = re.compile(r"^\s*ON\s+(?:public\.)?\"?(\w+)", re.IGNORECASE)
_INDEX_CLASSES = ("REQUIRED_INDEXES", "IDEMPOTENCY_INDEXES", "OPTIONAL_UNIQUE_INDEXES",
                  "PERFORMANCE_INDEXES")


def _boot_indexes(src: str) -> tuple[dict[str, set[tuple[str, bool]]], list[str]]:
    """({indeks: {(jadval, noyobmi)}}, hal qilinmagan shablonlar) — literal VA f-satr DDL'lari."""
    tree = ast.parse(src)
    parents = {ch: node for node in ast.walk(tree) for ch in ast.iter_child_nodes(node)}
    found: dict[str, set[tuple[str, bool]]] = {}
    unresolved: list[str] = []

    def add(name, table, unique):
        found.setdefault(name, set()).add((table, unique))

    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and not isinstance(parents.get(node), (ast.Expr, ast.JoinedStr))):
            for m in _IX_LITERAL.finditer(node.value):
                add(m.group(2), m.group(3), bool(m.group(1)))
        elif isinstance(node, ast.JoinedStr):
            tmpl = "".join(v.value if isinstance(v, ast.Constant)
                           else "{" + ast.unparse(v.value) + "}" for v in node.values)
            m = _IX_TEMPLATE.search(tmpl)
            if not m:
                continue
            unique, name_var, table, ddl_var = bool(m.group(1)), m.group(2), m.group(3), m.group(4)
            done = False
            cur = node
            while cur in parents and not done:
                cur = parents[cur]
                if isinstance(cur, ast.For) and isinstance(cur.target, ast.Tuple):
                    names = [e.id if isinstance(e, ast.Name) else None for e in cur.target.elts]
                    if name_var in names and isinstance(cur.iter, (ast.Tuple, ast.List)):
                        for el in cur.iter.elts:
                            vals = [e.value if isinstance(e, ast.Constant) else None for e in el.elts]
                            tbl = table
                            if ddl_var is not None:
                                on = _ON_TABLE.match(vals[names.index(ddl_var)] or "")
                                tbl = on.group(1) if on else None
                            if vals[names.index(name_var)] and tbl:
                                add(vals[names.index(name_var)], tbl, unique)
                            else:
                                unresolved.append(tmpl)
                        done = True
                elif isinstance(cur, ast.FunctionDef):
                    for st in ast.walk(cur):
                        if (isinstance(st, ast.Assign) and len(st.targets) == 1
                                and isinstance(st.targets[0], ast.Name)
                                and st.targets[0].id == name_var
                                and isinstance(st.value, ast.Constant) and table):
                            add(st.value.value, table, unique)
                            done = True
                    break
            if not done:
                unresolved.append(tmpl)
    return found, unresolved


def _classification_problems(found, classes: dict[str, list[tuple[str, str]]]) -> list[str]:
    bad: list[str] = []
    where: dict[str, list[tuple[str, str]]] = {}
    for cls, pairs in classes.items():
        names = [n for n, _ in pairs]
        for n in sorted({n for n in names if names.count(n) > 1}):
            bad.append(f"{cls} da takror: {n}")
        for n, t in pairs:
            where.setdefault(n, []).append((cls, t))
    for name, shapes in sorted(found.items()):
        if len(shapes) != 1:
            bad.append(f"{name}: boot'da har xil ta'rif {sorted(shapes)}")
            continue
        (table, unique), = shapes
        hits = where.get(name, [])
        if not hits:
            bad.append(f"tasniflanmagan: {name} ({table})")
            continue
        if len({c for c, _ in hits}) > 1:
            bad.append(f"bir nechta sinfda: {name} -> {sorted({c for c, _ in hits})}")
        for cls, t in hits:
            if t != table:
                bad.append(f"{cls}: {name} jadvali {t}, boot'da {table}")
            if unique and cls == "PERFORMANCE_INDEXES":
                bad.append(f"NOYOB indeks TEZLIK sinfida: {name}")
            if not unique and cls != "PERFORMANCE_INDEXES":
                bad.append(f"noyob BO'LMAGAN indeks {cls} da: {name}")
    for name in sorted(set(where) - set(found)):
        bad.append(f"sinfda bor, boot qurmaydi (eskirgan): {name}")
    return bad


def test_T4_har_boot_indeksi_AYNAN_BITTA_sinfda_jadvali_va_noyobligi_MOS():
    found, unresolved = _boot_indexes(pathlib.Path(I.__file__).read_text(encoding="utf-8"))
    assert not unresolved, f"indeks shabloni hal qilinmadi (qo'riqchini yangilang): {unresolved}"
    assert len(found) >= 56, f"boot indekslari juda kam topildi ({len(found)}) — tahlil buzilgan"
    bad = _classification_problems(found, {c: getattr(rs, c) for c in _INDEX_CLASSES})
    assert not bad, ("indeks yiqilsa uning oqibati hech qayerda ko'rinmasdi:\n  "
                     + "\n  ".join(bad))
    assert {n for n, _ in rs.IDEMPOTENCY_INDEXES} == {
        "ux_sales_company_client_uuid", "ux_returns_client_uuid", "ux_custpay_client_uuid",
        "ux_suppay_client_uuid", "ux_purchases_client_uuid", "ux_receivings_client_uuid",
        "ux_cashmov_client_uuid", "ux_stockmov_client_prod_type", "ux_shifts_cashier_open",
        "ux_companies_code", "ux_employees_phone_pw"}


def test_T4_salbiy_nazorat_TASNIFLANMAGAN_va_NOTOGRI_sinfni_USHLAYDI():
    src = (
        "def _ensure_indexes():\n"
        "    _index(\"CREATE UNIQUE INDEX IF NOT EXISTS ux_a ON a (x)\", \"ux_a\")\n"
        "    _index(\"CREATE INDEX IF NOT EXISTS ix_b ON b (y)\", \"ix_b\")\n"
        "    for _nm, _ddl in ((\"ix_c\", \"ON c (z)\"), (\"ix_d\", \"ON d (w)\")):\n"
        "        _index(f\"CREATE INDEX IF NOT EXISTS {_nm} {_ddl}\", _nm)\n"
        "def _cic():\n"
        "    name = \"ix_e\"\n"
        "    con.execute(text(f\"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} \"\n"
        "                     \"ON public.e (v)\"))\n"
    )
    found, unresolved = _boot_indexes(src)
    assert not unresolved and found == {"ux_a": {("a", True)}, "ix_b": {("b", False)},
                                        "ix_c": {("c", False)}, "ix_d": {("d", False)},
                                        "ix_e": {("e", False)}}, (found, unresolved)
    got = _classification_problems(found, {
        "REQUIRED_INDEXES": [("ix_b", "b")],
        "IDEMPOTENCY_INDEXES": [],
        "OPTIONAL_UNIQUE_INDEXES": [],
        "PERFORMANCE_INDEXES": [("ux_a", "a"), ("ix_c", "boshqa"), ("ix_d", "d"), ("ix_d", "d"),
                                ("ix_eski", "z")],
    })
    assert sorted(got) == sorted([
        "PERFORMANCE_INDEXES da takror: ix_d",
        "noyob BO'LMAGAN indeks REQUIRED_INDEXES da: ix_b",
        "PERFORMANCE_INDEXES: ix_c jadvali boshqa, boot'da c",
        "NOYOB indeks TEZLIK sinfida: ux_a",
        "tasniflanmagan: ix_e (e)",
        "sinfda bor, boot qurmaydi (eskirgan): ix_eski",
    ]), got


# ══ T5. ASOSIY FAKT — XARITALANGAN USTUN YO'Q -> MODEL SO'ROVI YIQILADI ═══════

@pytest.fixture
def xotira_bazasi():
    import app.models  # noqa: F401
    from app.db.base import Base
    eng = create_engine("sqlite://", poolclass=StaticPool,
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _model(name):
    from app.models.auth import Employee
    from app.models.catalog import Product
    from app.models.inventory import Inventory
    from app.models.sales import Sale
    return {"Employee": Employee, "Product": Product, "Sale": Sale, "Inventory": Inventory}[name]


@pytest.mark.parametrize("table,col,model", [
    ("employees", "sec_epoch", "Employee"),
    ("products", "sku", "Product"),
    ("sales", "terminal_name_snapshot", "Sale"),
    ("inventory", "low_alerted", "Inventory"),
])
def test_T5_XARITALANGAN_ustun_yoq_bolsa_select_Model_YIQILADI(xotira_bazasi, table, col, model):
    Model = _model(model)
    with Session(xotira_bazasi) as s:
        assert s.execute(sa.select(Model)).scalars().all() == []     # nazorat: sxema to'liq
    with xotira_bazasi.begin() as con:
        con.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
    with Session(xotira_bazasi) as s:
        with pytest.raises(OperationalError) as ei:
            s.execute(sa.select(Model)).scalars().all()
        assert f"no such column: {table}.{col}" in str(ei.value), ei.value
        s.rollback()
        # Chegara: faqat ENTITY yuklanishi — aniq ustun tanlovi ishlaydi (qamrov shu).
        assert s.execute(sa.select(Model.id)).all() == []


def _majburiy_qator(table) -> dict:
    """Core INSERT uchun NOT NULL va standartsiz ustunlarga soxta qiymat."""
    vals = {}
    for col in table.columns:
        if col.nullable or col.default is not None or col.server_default is not None:
            continue
        t = col.type
        if isinstance(t, sa.Uuid):
            vals[col.name] = uuid.uuid4()
        elif isinstance(t, sa.Enum):
            vals[col.name] = next(iter(t.enum_class)) if t.enum_class else t.enums[0]
        elif isinstance(t, sa.String):
            vals[col.name] = "x"
        elif isinstance(t, sa.Boolean):
            vals[col.name] = False
        elif isinstance(t, (sa.Integer, sa.Numeric)):
            vals[col.name] = 0
        elif isinstance(t, sa.DateTime):
            vals[col.name] = datetime.now(timezone.utc)
        elif isinstance(t, sa.Date):
            vals[col.name] = date.today()
        else:
            vals[col.name] = {}
    return vals


def test_T5_barkod_company_id_yoq_bolsa_HAR_select_Product_YIQILADI_selectin_orqali(xotira_bazasi):
    """`Product.barcodes` (selectin) — QO'SHNI model ustuni ham mahsulot ro'yxatini yiqitadi."""
    from app.models.catalog import Product
    with xotira_bazasi.begin() as con:
        con.execute(Product.__table__.insert().values(**_majburiy_qator(Product.__table__)))
    with Session(xotira_bazasi) as s:
        assert len(s.execute(sa.select(Product)).scalars().all()) == 1   # nazorat
    with xotira_bazasi.begin() as con:
        #  UNIQUE/FK ichidagi ustunni SQLite DROP COLUMN qilmaydi — eski shakl qayta quriladi.
        con.execute(text("DROP TABLE product_barcodes"))
        con.execute(text("CREATE TABLE product_barcodes (id CHAR(32) NOT NULL PRIMARY KEY, "
                         "product_id CHAR(32), barcode VARCHAR)"))
    with Session(xotira_bazasi) as s:
        with pytest.raises(OperationalError) as ei:
            s.execute(sa.select(Product)).scalars().all()
        assert "no such column: product_barcodes.company_id" in str(ei.value), ei.value


# ══ TAYYORLIK — idempotency_schema / column_types ═══════════════════════════

_IDEM = "idempotentlik indeksi yo'q: ux_sales_company_client_uuid (sales)"
_TIP = "ustun tipi uuid emas: cash_movements.client_uuid"


class _R:
    status_code = 200


def test_tayyorlik_IDEMPOTENTLIK_indeksi_yoq_503_QOLGAN_kalitlar_YASHIL(client, monkeypatch):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["idempotency_schema"] is True, r.text
    assert r.json()["checks"]["column_types"] is True, r.text             # nazorat: to'liq sxema
    monkeypatch.setattr(rs, "idempotency_missing", lambda bind: [_IDEM])
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["checks"]["idempotency_schema"] is False, body
    assert {k: v for k, v in body["checks"].items() if k != "idempotency_schema"} == {
        "database": True, "cash_schema": True, "config": True, "tenancy_schema": True,
        "catalog_v2_schema": True, "lot_schema_integrity": True, "column_types": True}, body
    assert body["missing_schema"] == [_IDEM], body


def test_tayyorlik_USTUN_TIPI_muammosi_503_faqat_column_types_QIZIL(client, monkeypatch):
    monkeypatch.setattr(rs, "column_type_problems", lambda bind: [_TIP])
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503, r.text
    checks = r.json()["checks"]
    assert checks["column_types"] is False
    assert [k for k, v in checks.items() if not v] == ["column_types"], checks
    assert r.json()["missing_schema"] == [_TIP]


def test_tayyorlik_tekshiruv_YIQILSA_QIZIL_xato_matni_CHIQMAYDI(client, monkeypatch):
    sir = "host=maxfiy-host.internal user=maxfiy_user port=5432"

    def boom(bind):
        raise RuntimeError(sir)
    monkeypatch.setattr(rs, "idempotency_missing", boom)
    monkeypatch.setattr(rs, "column_type_problems", boom)
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["checks"]["idempotency_schema"] is False and body["checks"]["column_types"] is False
    assert sir not in r.text and "maxfiy" not in r.text, "XATO MATNI chiqib ketdi"
    assert body["missing_schema"] == ["idempotentlik indekslarini o'qib bo'lmadi",
                                      "ustun tiplarini o'qib bo'lmadi"], body


def test_idempotency_missing_ICHKI_xato_ozgarmas_satr_beradi(monkeypatch):
    sir = "host=maxfiy-host.internal"

    def boom(bind, pairs):
        raise RuntimeError(sir)
    monkeypatch.setattr(rs, "_unique_index_states", boom)
    assert rs.idempotency_missing(object()) == ["idempotentlik indekslarini o'qib bo'lmadi"]
    assert rs.optional_unique_missing(object()) == []          # faqat jurnal sinfi


def test_production_da_IDEMPOTENTLIK_va_TIP_NOMLARI_chiqmaydi(monkeypatch, client):
    from app.api.v1 import health as H
    monkeypatch.setattr(H, "_check_db", lambda: (True, True))
    monkeypatch.setattr(rs, "ok", lambda b: (True, []))
    monkeypatch.setattr(rs, "idempotency_missing", lambda b: [_IDEM])
    monkeypatch.setattr(rs, "column_type_problems", lambda b: [_TIP])
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    for app_env, platform in (("production", None), ("staging", "production")):
        monkeypatch.setenv("APP_ENV", app_env)
        if platform:
            monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", platform)
        resp = _R()
        body = H.ready(resp)
        assert resp.status_code == 503
        assert body["checks"]["idempotency_schema"] is False and body["checks"]["column_types"] is False
        assert "missing_schema" not in body and body["missing_schema_count"] == 2, body
        blob = json.dumps(body)
        for name in ("ux_sales_company_client_uuid", "cash_movements", "client_uuid"):
            assert name not in blob, (name, body)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    monkeypatch.setenv("APP_ENV", "staging")
    body = H.ready(_R())
    assert body["missing_schema"] == [_IDEM, _TIP], body


# ── HAQIQIY SQLite bazada: `idempotency_missing` va partiya darvozasi ─────────

@pytest.fixture(scope="module")
def _qurilgan_sqlite(tmp_path_factory):
    db = tmp_path_factory.mktemp("runtime_cols") / "asos.db"
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(db).replace("\\", "/"), APP_ENV="test",
               PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, timeout=600)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert "[schema] TAYYOR EMAS" not in r.stdout, r.stdout[-2000:]
    return db


@pytest.fixture
def sqlite_nusxa(_qurilgan_sqlite, tmp_path):
    dst = tmp_path / "nusxa.db"
    shutil.copy(_qurilgan_sqlite, dst)
    url = "sqlite:///" + str(dst).replace("\\", "/")
    eng = create_engine(url)
    try:
        yield eng, url
    finally:
        eng.dispose()


def _enable_status(eng) -> int:
    """`/lots/enable` sxema darvozasi: 409 = yopdi; 0 = o'tib soxta `db.get` ga yetdi."""
    from fastapi import HTTPException

    from app.api.v1.lots import enable_tracking
    fake_db = types.SimpleNamespace(get_bind=lambda: eng)
    try:
        enable_tracking(data=types.SimpleNamespace(product_id=None), emp=None, db=fake_db)
    except HTTPException as e:
        return e.status_code
    except AttributeError:
        return 0
    return 0


def test_SQLite_idempotency_missing_YOQ_NOYOB_EMAS_va_BOSHQA_JADVALDAGI_indeksni_KORADI(sqlite_nusxa):
    eng, _url = sqlite_nusxa
    assert rs.idempotency_missing(eng) == []                      # nazorat: boot hammasini qurgan
    assert rs.optional_unique_missing(eng) == []
    with eng.begin() as con:
        con.execute(text("DROP INDEX ux_sales_company_client_uuid"))
        con.execute(text("DROP INDEX ux_shifts_cashier_open"))
        con.execute(text("CREATE INDEX ux_shifts_cashier_open ON shifts (cashier_id)"))
        con.execute(text("DROP INDEX ux_companies_code"))
        con.execute(text("CREATE UNIQUE INDEX ux_companies_code ON employees (id)"))
        con.execute(text("DROP INDEX ux_barcodes_company_bc"))
    assert rs.idempotency_missing(eng) == [
        "idempotentlik indeksi yo'q: ux_sales_company_client_uuid (sales)",
        "idempotentlik indeksi noyob emas: ux_shifts_cashier_open (shifts)",
        "idempotentlik indeksi yo'q: ux_companies_code (companies)",
    ]
    assert rs.optional_unique_missing(eng) == [
        "noyoblik indeksi yo'q: ux_barcodes_company_bc (product_barcodes)"]


def test_SQLite_IDEMPOTENTLIK_yoq_PARTIYA_darvozasini_TOSMAYDI_majburiy_indeks_TOSADI(sqlite_nusxa):
    eng, _url = sqlite_nusxa
    assert _enable_status(eng) == 0, "nazorat: to'liq sxemada darvoza ochiq bo'lishi kerak"
    with eng.begin() as con:
        con.execute(text("DROP INDEX ux_sales_company_client_uuid"))
        con.execute(text("DROP INDEX ux_employees_phone_pw"))
    assert rs.idempotency_missing(eng), "sinov farazi: idempotentlik indeksi yo'q"
    assert rs.missing(eng) == [], "idempotentlik `missing()` ga SIZIB kirdi"
    assert _enable_status(eng) == 0, "aloqasiz indeks partiya aktivatsiyasini TO'SDI"
    # SALBIY NAZORAT: harness haqiqatan o'lchaydi — MAJBURIY indeks yo'q -> 409.
    with eng.begin() as con:
        con.execute(text("DROP INDEX ux_doc_counter"))
    assert _enable_status(eng) == 409


def test_SQLite_tayyorlik_HAQIQIY_bazada_idempotentlik_indeksi_yoq_503(sqlite_nusxa):
    eng, url = sqlite_nusxa
    with eng.begin() as con:
        con.execute(text("DROP INDEX ux_cashmov_client_uuid"))
    eng.dispose()
    code = ("import json" + chr(10) +
            "from app.api.v1 import health as H" + chr(10) +
            "class R: status_code = 200" + chr(10) +
            "r = R()" + chr(10) +
            "b = H.ready(r)" + chr(10) +
            "print('RESULT ' + json.dumps({'s': r.status_code, 'b': b}))" + chr(10))
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test", PYTHONIOENCODING="utf-8")
    env.pop("RAILWAY_ENVIRONMENT_NAME", None)
    r = subprocess.run([sys.executable, "-c", code], cwd=SRV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    res = json.loads(r.stdout.split("RESULT ", 1)[1].strip())
    assert res["s"] == 503, res
    assert res["b"]["checks"]["idempotency_schema"] is False, res
    assert [k for k, v in res["b"]["checks"].items() if not v] == ["idempotency_schema"], res
    assert res["b"]["missing_schema"] == [
        "idempotentlik indeksi yo'q: ux_cashmov_client_uuid (cash_movements)"], res


# ── Postgres tasnif mantig'i — soxta katalog qatorlari bilan ──────────────────

class _KatalogRes:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _KatalogBind:
    def __init__(self, rows=None, error=None):
        self.dialect = types.SimpleNamespace(name="postgresql")
        self.rows, self.error, self.sql = rows or [], error, []

    @contextlib.contextmanager
    def connect(self):
        bind = self

        class _Con:
            def execute(self, stmt, params=None):
                bind.sql.append((str(stmt), params))
                if bind.error:
                    raise bind.error
                return _KatalogRes(bind.rows)
        yield _Con()


def test_katalog_qatorlari_idempotency_missing_NOYOB_YAROQLI_va_JADVAL_DOIRASIDA():
    ok_rows = [(n, t, True, True) for n, t in rs.IDEMPOTENCY_INDEXES]
    assert rs.idempotency_missing(_KatalogBind(ok_rows)) == []            # nazorat
    rows = [r for r in ok_rows if r[0] not in (
        "ux_returns_client_uuid", "ux_custpay_client_uuid", "ux_suppay_client_uuid",
        "ux_employees_phone_pw")]
    rows += [("ux_returns_client_uuid", "returns", False, True),            # noyob emas
             ("ux_custpay_client_uuid", "customer_payments", True, False),  # yaroqsiz (CONCURRENTLY)
             ("ux_suppay_client_uuid", "sales", True, True),                # BOSHQA jadvalda
             ("ux_employees_phone_pw", "employees", False, False)]
    bind = _KatalogBind(rows)
    assert rs.idempotency_missing(bind) == [
        "idempotentlik indeksi noyob emas: ux_returns_client_uuid (returns)",
        "idempotentlik indeksi yaroqsiz: ux_custpay_client_uuid (customer_payments)",
        "idempotentlik indeksi yo'q: ux_suppay_client_uuid (supplier_payments)",
        "idempotentlik indeksi noyob emas: ux_employees_phone_pw (employees)",
    ]
    sql, params = bind.sql[0]
    assert "indisunique" in sql and "indisvalid" in sql and "indisready" in sql, sql
    assert sorted(params["n"]) == sorted(n for n, _ in rs.IDEMPOTENCY_INDEXES)


def test_katalog_qatorlari_column_type_problems_faqat_UUID_BOLMAGAN_ustunlar():
    bind = _KatalogBind([("cash_movements", "client_uuid", "varchar"),
                         ("qr_payments", "sale_id", "uuid"),
                         ("shifts", "client_uuid", "varchar")])          # ro'yxatda yo'q — e'tiborsiz
    assert rs.column_type_problems(bind) == ["ustun tipi uuid emas: cash_movements.client_uuid"]
    assert rs.column_type_problems(_KatalogBind([("cash_movements", "client_uuid", "uuid"),
                                                 ("qr_payments", "sale_id", "uuid"),
                                                 ("qr_payments", "client_uuid", "uuid")])) == []
    sir = "host=maxfiy-host.internal"
    assert rs.column_type_problems(_KatalogBind(error=RuntimeError(sir))) == [
        "ustun tiplarini o'qib bo'lmadi"]
    sqlite = types.SimpleNamespace(dialect=types.SimpleNamespace(name="sqlite"))
    assert rs.column_type_problems(sqlite) == []


# ══ `_repair_uuid_type_drift` — TASNIF (soxta Postgres engine) ════════════════

class _RepCon:
    def __init__(self, eng):
        self.eng = eng

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.eng.sql.append(sql)
        if "!~*" in sql:
            if self.eng.scan_errors:
                raise self.eng.scan_errors.pop(0)
            key = (re.search(r'FROM "(\w+)"', sql).group(1), re.search(r'WHERE "(\w+)"', sql).group(1))
            assert params == {"re": I._UUID_CANONICAL_RE}, params
            return types.SimpleNamespace(first=lambda: (1,) if key in self.eng.bad else None)
        if sql.startswith("ALTER TABLE"):
            if self.eng.alter_errors:
                raise self.eng.alter_errors.pop(0)
            m = re.search(r'ALTER TABLE "(\w+)" ALTER COLUMN "(\w+)"', sql)
            self.eng.types[(m.group(1), m.group(2))] = "uuid"
            return None
        raise AssertionError(f"kutilmagan SQL: {sql}")


class _RepEngine:
    def __init__(self, typ, bad=(), alter_errors=(), scan_errors=(), dialect="postgresql"):
        self.dialect = types.SimpleNamespace(name=dialect)
        self.types = {p: typ for p in rs.UUID_TYPED_COLUMNS} if isinstance(typ, str) else dict(typ)
        self.bad, self.sql = set(bad), []
        self.alter_errors, self.scan_errors = list(alter_errors), list(scan_errors)
        self.connects = 0

    @contextlib.contextmanager
    def connect(self):
        self.connects += 1
        yield _RepCon(self)

    begin = connect


@pytest.fixture
def repair(monkeypatch):
    def make(*a, **k):
        eng = _RepEngine(*a, **k)
        monkeypatch.setattr(I, "engine", eng)
        monkeypatch.setattr(I, "_LOCK_RETRY_SLEEP", 0)
        monkeypatch.setattr(I, "_lock_holders", lambda tables: (
            f"lock_timeout=1s; to'sayotgan seanslar: {tables[0]}: pid=4242 AccessShareLock"))
        monkeypatch.setattr(rs, "uuid_column_types", lambda con: dict(con.eng.types))
        return eng
    return make


def _alters(eng):
    return [s for s in eng.sql if s.startswith("ALTER TABLE")]


def test_REPAIR_BARQAROR_uuid_bolsa_skaner_ham_DDL_ham_YOQ(repair, capsys):
    eng = repair("uuid")
    I._repair_uuid_type_drift()
    assert eng.sql == [], f"barqaror boot jadvalga so'rov yubordi: {eng.sql}"
    assert capsys.readouterr().out == ""


def test_REPAIR_ustun_YOQ_bolsa_tegmaydi(repair):
    eng = repair({})
    I._repair_uuid_type_drift()
    assert eng.sql == []


def test_REPAIR_varchar_va_text_KANONIK_qiymatlar_ALTER_USING_uuid(repair, capsys):
    eng = repair({("cash_movements", "client_uuid"): "varchar", ("qr_payments", "sale_id"): "text",
                  ("qr_payments", "client_uuid"): "varchar"})
    I._repair_uuid_type_drift()
    out = capsys.readouterr().out
    assert _alters(eng) == [
        'ALTER TABLE "cash_movements" ALTER COLUMN "client_uuid" TYPE uuid USING "client_uuid"::uuid',
        'ALTER TABLE "qr_payments" ALTER COLUMN "sale_id" TYPE uuid USING "sale_id"::uuid',
        'ALTER TABLE "qr_payments" ALTER COLUMN "client_uuid" TYPE uuid USING "client_uuid"::uuid',
    ], eng.sql
    assert sum("!~*" in s for s in eng.sql) == 3, "qiymatlar ALTER'dan OLDIN tekshirilmadi"
    for line in ("[migrate] cash_movements.client_uuid: varchar -> uuid",
                 "[migrate] qr_payments.sale_id: text -> uuid"):
        assert line in out, out
    assert "[FATAL]" not in out and "TAYYOR EMAS" not in out, out
    #  kanonik shakl: registrga sezgir emas (`~*`), 32 belgili / qavsli shakl — EMAS
    pat = re.compile(I._UUID_CANONICAL_RE, re.IGNORECASE)
    assert pat.match(str(uuid.uuid4())) and pat.match(str(uuid.uuid4()).upper())
    assert not pat.match(uuid.uuid4().hex) and not pat.match("{" + str(uuid.uuid4()) + "}")
    assert not pat.match("") and not pat.match(" " + str(uuid.uuid4()))


def test_REPAIR_UUID_BOLMAGAN_qiymat_DDL_YOQ_TAYYOR_EMAS_boot_DAVOM(repair, capsys):
    eng = repair("varchar", bad={("qr_payments", "client_uuid")})
    I._repair_uuid_type_drift()                      # yiqilmaydi
    out = capsys.readouterr().out
    assert [a.split('"')[1] + "." + a.split('"')[3] for a in _alters(eng)] == [
        "cash_movements.client_uuid", "qr_payments.sale_id"], eng.sql
    ln = [x for x in out.splitlines() if "qr_payments.client_uuid" in x]
    assert len(ln) == 1 and ln[0].startswith("[schema] TAYYOR EMAS (boot davom etadi)"), out
    assert "DDL yuborilmadi" in ln[0] and "[FATAL]" not in out


def test_REPAIR_boshqa_TIP_avtomatik_tuzatilmaydi(repair, capsys):
    eng = repair({("cash_movements", "client_uuid"): "int4"})
    I._repair_uuid_type_drift()
    out = capsys.readouterr().out
    assert eng.sql == [], eng.sql
    assert "[schema] TAYYOR EMAS (boot davom etadi) — cash_movements.client_uuid" in out, out


def test_REPAIR_ALTER_QULF_BAND_cheklangan_urinish_keyin_FATAL(repair, capsys):
    eng = repair("varchar", alter_errors=[_lock_err("ALTER TABLE cash_movements")] * 20)
    with pytest.raises(OperationalError):
        I._repair_uuid_type_drift()
    out = capsys.readouterr().out
    assert len(_alters(eng)) == I._DDL_LOCK_ATTEMPTS == 5, eng.sql
    assert "cash_movements.client_uuid: qulf band — 4/5" in out, out
    fatal = [ln for ln in out.splitlines() if ln.startswith("[FATAL]")]
    assert len(fatal) == 1, out
    for part in ("MAJBURIY ustun tipi tuzatilmadi: cash_movements.client_uuid (varchar -> uuid)",
                 "cash_movements qulfi 5 urinishda", "lock_timeout=1s", "pid=4242"):
        assert part in fatal[0], fatal[0]


def test_REPAIR_skaner_QULF_BAND_ham_FATAL(repair, capsys):
    eng = repair("varchar", scan_errors=[_lock_err("SELECT 1 FROM cash_movements")] * 20)
    with pytest.raises(OperationalError):
        I._repair_uuid_type_drift()
    out = capsys.readouterr().out
    assert _alters(eng) == [] and sum("!~*" in s for s in eng.sql) == 5, eng.sql
    assert "[FATAL] MAJBURIY ustun tipi tuzatilmadi: cash_movements.client_uuid" in out, out


def test_REPAIR_qulf_BOSHLIQ_ikkinchi_urinishda_OTADI(repair, capsys):
    eng = repair("varchar", alter_errors=[_lock_err("ALTER TABLE cash_movements")])
    I._repair_uuid_type_drift()
    out = capsys.readouterr().out
    assert len(_alters(eng)) == 4 and "[FATAL]" not in out, (eng.sql, out)
    assert set(eng.types.values()) == {"uuid"}


def test_REPAIR_qulfdan_BOSHQA_xato_FATAL_EMAS_qiymat_JURNALGA_tushmaydi(repair, capsys):
    """Skaner va ALTER orasida UUID bo'lmagan qiymat yozildi (22P02) — operator ishi."""
    maxfiy = "MAXFIY-QIYMAT-42"
    err = DataError("ALTER TABLE", None, psycopg.errors.InvalidTextRepresentation(
        f'invalid input syntax for type uuid: "{maxfiy}"'))
    eng = repair("varchar", alter_errors=[err])
    I._repair_uuid_type_drift()
    out = capsys.readouterr().out
    assert len(_alters(eng)) == 3, "22P02 qayta urinildi yoki keyingi ustunlar to'xtadi"
    assert "[FATAL]" not in out and maxfiy not in out, out
    ln = [x for x in out.splitlines() if "cash_movements.client_uuid" in x]
    assert ln and "SQLSTATE 22P02" in ln[0] and ln[0].startswith("[schema] TAYYOR EMAS"), out


def test_REPAIR_qulf_kutilganda_BOSHQA_INSTANSIYA_tuzatgan_bolsa_ALTER_YOQ(repair, monkeypatch):
    eng = repair("varchar")
    calls = []

    def types_(con):
        calls.append(1)
        return dict(eng.types) if len(calls) == 1 else {p: "uuid" for p in rs.UUID_TYPED_COLUMNS}
    monkeypatch.setattr(rs, "uuid_column_types", types_)
    I._repair_uuid_type_drift()
    assert _alters(eng) == [], eng.sql
    assert len(calls) == 4, "ALTER tranzaksiyasida tip QAYTA o'qilmadi"


def test_REPAIR_SQLite_da_HECH_NARSA_qilmaydi(repair):
    eng = repair("varchar", dialect="sqlite")
    I._repair_uuid_type_drift()
    assert eng.connects == 0 and eng.sql == []


def test_REPAIR_main_da_ensure_columns_dan_KEYIN():
    src = pathlib.Path(I.__file__).read_text(encoding="utf-8")
    body = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    steps = [c.value.func.id for c in body.body
             if isinstance(c, ast.Expr) and isinstance(c.value, ast.Call)
             and isinstance(c.value.func, ast.Name)]
    assert steps.index("_repair_uuid_type_drift") == steps.index("_ensure_columns") + 1, steps
    assert steps.index("_repair_uuid_type_drift") < steps.index("_ensure_indexes"), steps
