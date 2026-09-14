# -*- coding: utf-8 -*-
"""PRODUCTION FINGERPRINT — STRICTLY READ-ONLY.

* One REPEATABLE READ, READ ONLY transaction: every number comes from ONE snapshot.
* SELECT only. Errors roll back to a savepoint; nothing is ever written.
* The connection string is never printed or written anywhere.

Usage (inside `railway run --service Postgres-d29B --environment production`):
    python prodfp.py                      > pre.json
    python prodfp.py --columns-from pre.json > post.json

`--columns-from` makes the post-deploy row digests use EXACTLY the pre-deploy column
lists, so additive schema changes (new columns) cannot change a digest by themselves —
only a changed business ROW can.
"""
import argparse
import json
import os
import sys
from urllib.parse import quote

import psycopg
from psycopg import sql


def external_url():
    pub = os.environ.get("DATABASE_PUBLIC_URL")
    if pub and "railway.internal" not in pub:
        return pub
    host = os.environ.get("RAILWAY_TCP_PROXY_DOMAIN")
    port = os.environ.get("RAILWAY_TCP_PROXY_PORT")
    user = os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER")
    pw = os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    db = os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DB")
    if not all((host, port, user, pw, db)):
        return None
    return f"postgresql://{quote(user)}:{quote(pw)}@{host}:{port}/{db}"


class Q:
    def __init__(self, conn):
        self.cur = conn.cursor()
        self.errors = []

    def one(self, query, params=None, label=None):
        self.cur.execute("SAVEPOINT fp")
        try:
            self.cur.execute(query, params)
            row = self.cur.fetchone()
            self.cur.execute("RELEASE SAVEPOINT fp")
            return row
        except Exception as e:  # noqa: BLE001
            self.cur.execute("ROLLBACK TO SAVEPOINT fp")
            self.errors.append({"label": label or str(query)[:80], "error": type(e).__name__})
            return None

    def all(self, query, params=None, label=None):
        self.cur.execute("SAVEPOINT fp")
        try:
            self.cur.execute(query, params)
            rows = self.cur.fetchall()
            self.cur.execute("RELEASE SAVEPOINT fp")
            return rows
        except Exception as e:  # noqa: BLE001
            self.cur.execute("ROLLBACK TO SAVEPOINT fp")
            self.errors.append({"label": label or str(query)[:80], "error": type(e).__name__})
            return None


def scalar(q, query, params=None, label=None):
    r = q.one(query, params, label)
    if r is None:
        return None
    v = r[0]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v if isinstance(v, (int, float, str, bool)) or v is None else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--columns-from")
    args = ap.parse_args()
    prev_cols = None
    if args.columns_from:
        with open(args.columns_from, encoding="utf-8") as f:
            prev_cols = json.load(f)["schema"]["digest_columns"]

    url = external_url()
    if not url:
        print("connection details not found", file=sys.stderr)
        return 2

    out = {"meta": {}, "schema": {}, "tables": {}, "global": {}, "fayzan": {}, "companies": []}
    with psycopg.connect(url, connect_timeout=30) as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        q = Q(conn)
        try:
            q.cur.execute("SAVEPOINT tz")
            q.cur.execute("SET TIME ZONE 'UTC'")
            q.cur.execute("RELEASE SAVEPOINT tz")
        except Exception:  # noqa: BLE001 — server without tz database (Windows pgserver)
            q.cur.execute("ROLLBACK TO SAVEPOINT tz")
            q.cur.execute("SET TIME ZONE INTERVAL '+00:00' HOUR TO MINUTE")
        q.cur.execute("SET extra_float_digits = 3")

        m = out["meta"]
        m["server_version"] = scalar(q, "SHOW server_version")
        m["system_identifier"] = scalar(q, "SELECT system_identifier::text FROM pg_control_system()",
                                        label="system_identifier")
        m["db_now_utc"] = scalar(q, "SELECT now()")
        m["transaction_read_only"] = scalar(q, "SHOW transaction_read_only")
        m["isolation"] = scalar(q, "SHOW transaction_isolation")

        # ── schema catalog ────────────────────────────────────────────────
        tables = q.all(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('public','cash') AND table_type='BASE TABLE' "
            "ORDER BY 1,2") or []
        # Full type WITH modifiers (information_schema.data_type drops them: numeric(14,3) == numeric).
        cols = q.all(
            "SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod), "
            "CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END, coalesce(pg_get_expr(d.adbin, d.adrelid), '') "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE n.nspname IN ('public','cash') AND c.relkind IN ('r','p') AND a.attnum > 0 "
            "AND NOT a.attisdropped ORDER BY 1, 2, a.attnum") or []
        colmap = {}
        for s, t, c, dt, nul, dflt in cols:
            colmap.setdefault(f"{s}.{t}", []).append([c, dt, nul, dflt])
        out["schema"]["columns"] = colmap
        out["schema"]["indexes"] = {
            f"{s}.{n}": d for s, n, d in (q.all(
                "SELECT schemaname, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname IN ('public','cash') ORDER BY 1,2") or [])}
        # indexdef does not show validity: an INVALID unique index would otherwise look identical.
        out["schema"]["index_validity"] = {
            f"{s}.{n}": v for s, n, v in (q.all(
                "SELECT n.nspname, c.relname, i.indisvalid AND i.indisready FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname IN ('public','cash') ORDER BY 1, 2") or [])}
        out["schema"]["constraints"] = {
            f"{r}.{n}": d for r, n, d in (q.all(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
                "FROM pg_constraint WHERE connamespace IN "
                "('public'::regnamespace, 'cash'::regnamespace) ORDER BY 1,2") or [])}
        out["schema"]["triggers"] = {
            f"{t}.{n}": d for t, n, d in (q.all(
                "SELECT tg.tgrelid::regclass::text, tg.tgname, pg_get_triggerdef(tg.oid) FROM pg_trigger tg "
                "JOIN pg_class c ON c.oid = tg.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE NOT tg.tgisinternal AND n.nspname IN ('public','cash') ORDER BY 1, 2") or [])}
        out["schema"]["functions"] = {
            f"{s}.{n}({args})": h for s, n, args, h in (q.all(
                "SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid), "
                "md5(pg_get_functiondef(p.oid)) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname IN ('public','cash') AND p.prokind IN ('f','p') ORDER BY 1, 2, 3") or [])}
        # The deploy gate's own DDL lock audit trigger (schema gate_audit) is excluded BY NAME.
        out["schema"]["event_triggers"] = {
            n: f"{e}:{en}" for n, e, en in (q.all(
                "SELECT evtname, evtevent, evtenabled::text FROM pg_event_trigger "
                "WHERE evtname <> 'gate_audit_ddl_end' ORDER BY 1") or [])}
        # Physical identity: a drop-and-recreate with the same definition changes these.
        out["schema"]["identity"] = {
            f"{k}:{s}.{n}": [o, fn] for k, s, n, o, fn in (q.all(
                "SELECT c.relkind::text, n.nspname, c.relname, c.oid::bigint, c.relfilenode::bigint "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname IN ('public','cash') AND c.relkind IN ('r','p','i') ORDER BY 2, 3") or [])}
        out["schema"]["constraint_identity"] = {
            f"{r}.{n}": o for r, n, o in (q.all(
                "SELECT conrelid::regclass::text, conname, oid::bigint FROM pg_constraint WHERE connamespace IN "
                "('public'::regnamespace, 'cash'::regnamespace) ORDER BY 1, 2") or [])}
        out["schema"]["table_count"] = len(tables)

        # ── per-table row count + content digest over PRE-DEPLOY columns ─
        digest_cols = {}
        for s, t in tables:
            key = f"{s}.{t}"
            names = (prev_cols or {}).get(key) or [c[0] for c in colmap.get(key, [])]
            digest_cols[key] = names
            if not names:
                continue
            row_expr = sql.SQL("concat_ws(E'\\x1f', {})").format(sql.SQL(", ").join(
                sql.SQL("quote_nullable({}::text)").format(sql.Identifier(n)) for n in names))
            query = sql.SQL(
                "SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                "FROM (SELECT md5({}) AS h FROM {}.{}) x").format(
                    row_expr, sql.Identifier(s), sql.Identifier(t))
            r = q.one(query, label=f"digest {key}")
            out["tables"][key] = ({"rows": r[0], "digest": r[1]} if r else {"rows": None, "digest": None})
        out["schema"]["digest_columns"] = digest_cols
        if prev_cols:
            out["schema"]["tables_new_since_columns_file"] = sorted(set(digest_cols) - set(prev_cols))
            out["schema"]["tables_missing_since_columns_file"] = sorted(set(prev_cols) - set(digest_cols))

        # ── write-activity counters (cumulative; compare pre/post) ────────
        out["schema"]["pg_stat"] = {
            f"{s}.{t}": {"ins": i, "upd": u, "del": d, "live": lv}
            for s, t, i, u, d, lv in (q.all(
                "SELECT schemaname, relname, n_tup_ins, n_tup_upd, n_tup_del, n_live_tup "
                "FROM pg_stat_user_tables WHERE schemaname IN ('public','cash') ORDER BY 1,2") or [])}

        # ── global lot / activation state ─────────────────────────────────
        g = out["global"]
        g["products_track_lots"] = scalar(q, "SELECT count(*) FROM products WHERE track_lots IS TRUE")
        g["products_track_expiry"] = scalar(q, "SELECT count(*) FROM products WHERE track_expiry IS TRUE")
        g["products_lots_activated_at"] = scalar(
            q, "SELECT count(*) FROM products WHERE lots_activated_at IS NOT NULL", label="lots_activated_at")
        for t in ("stock_batches", "sale_item_lot_allocations", "lot_shortfalls",
                  "return_item_lot_allocations", "stock_movement_lot_allocations", "doc_counters"):
            g[t] = scalar(q, sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t)), label=t)
        g["new_tables_present"] = {
            t: f"public.{t}" in digest_cols
            for t in ("return_item_lot_allocations", "stock_movement_lot_allocations")}

        # ── companies (code + flags only) ─────────────────────────────────
        comps = q.all(
            "SELECT c.id::text, c.code, c.deleted_at IS NOT NULL, "
            "(SELECT count(*) FROM products p WHERE p.company_id=c.id), "
            "(SELECT count(*) FROM sales s WHERE s.company_id=c.id), "
            "(SELECT count(*) FROM returns r WHERE r.company_id=c.id) "
            "FROM companies c ORDER BY c.code") or []
        out["companies"] = [dict(zip(("id", "code", "deleted", "products", "sales", "returns"), r))
                            for r in comps]

        # ── Fayzan ────────────────────────────────────────────────────────
        fz = q.one("SELECT id::text, code FROM companies WHERE code IN ('fayzan1','fayzan') "
                   "ORDER BY code DESC LIMIT 1")
        f = out["fayzan"]
        if fz:
            cid = fz[0]
            f["company_id"], f["code"] = fz
            P = {"c": cid}
            def cnt(label, query):
                f[label] = scalar(q, query, P, label=f"fayzan {label}")
            cnt("products", "SELECT count(*) FROM products WHERE company_id=%(c)s")
            cnt("products_active_not_deleted", "SELECT count(*) FROM products WHERE company_id=%(c)s AND deleted_at IS NULL")
            cnt("product_barcodes", "SELECT count(*) FROM product_barcodes WHERE company_id=%(c)s")
            cnt("inventory", "SELECT count(*) FROM inventory i JOIN products p ON p.id=i.product_id WHERE p.company_id=%(c)s")
            cnt("inventory_qty_sum", "SELECT coalesce(sum(i.qty),0)::text FROM inventory i JOIN products p ON p.id=i.product_id WHERE p.company_id=%(c)s")
            cnt("stock_movements", "SELECT count(*) FROM stock_movements m JOIN products p ON p.id=m.product_id WHERE p.company_id=%(c)s")
            cnt("stock_movements_1c_cutover", "SELECT count(*) FROM stock_movements m JOIN products p ON p.id=m.product_id WHERE p.company_id=%(c)s AND m.ref_type='1c_cutover'")
            cnt("sales", "SELECT count(*) FROM sales WHERE company_id=%(c)s")
            cnt("sale_items", "SELECT count(*) FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE s.company_id=%(c)s")
            cnt("sale_payments", "SELECT count(*) FROM sale_payments sp JOIN sales s ON s.id=sp.sale_id WHERE s.company_id=%(c)s")
            cnt("returns", "SELECT count(*) FROM returns WHERE company_id=%(c)s")
            cnt("return_items", "SELECT count(*) FROM return_items ri JOIN returns r ON r.id=ri.return_id WHERE r.company_id=%(c)s")
            cnt("purchases", "SELECT count(*) FROM purchases WHERE company_id=%(c)s")
            # `shifts` has no company_id: it is scoped through its branch.
            cnt("shifts", "SELECT count(*) FROM shifts s JOIN branches b ON b.id=s.branch_id WHERE b.company_id=%(c)s")
            cnt("cash_shifts", "SELECT count(*) FROM cash.shifts WHERE tenant_id=%(c)s")
            cnt("settings_keys", "SELECT coalesce(string_agg(key, ',' ORDER BY key), '') FROM settings WHERE company_id=%(c)s")
            cnt("settings_digest", "SELECT md5(coalesce(string_agg(key || '=' || value::text, '|' ORDER BY key, id::text), '')) FROM settings WHERE company_id=%(c)s")
            cnt("import_jobs_digest", "SELECT md5(coalesce(string_agg(id::text || ':' || status::text, '|' ORDER BY id::text), '')) FROM import_jobs WHERE company_id=%(c)s")
            if "source_system" in {c[0] for c in colmap.get("public.products", [])}:
                cnt("products_with_source_system", "SELECT count(*) FROM products WHERE company_id=%(c)s AND source_system IS NOT NULL")
            # Phase 4A tables: counted only when they exist (absent before the deploy).
            for t4 in ("lot_shortfall_resolution_requests", "lot_shortfall_resolutions",
                       "return_item_shortfall_allocations", "return_item_resolution_allocations"):
                if f"public.{t4}" in digest_cols:
                    cnt(t4, f"SELECT count(*) FROM {t4} WHERE company_id=%(c)s")
                else:
                    f[t4] = "table absent"
            cnt("employees", "SELECT count(*) FROM employees WHERE company_id=%(c)s")
            cnt("branches", "SELECT count(*) FROM branches WHERE company_id=%(c)s")
            cnt("settings_rows", "SELECT count(*) FROM settings WHERE company_id=%(c)s")
            cnt("settings_catalog_present", "SELECT count(*) FROM settings WHERE company_id=%(c)s AND key='catalog'")
            cnt("import_jobs", "SELECT count(*) FROM import_jobs WHERE company_id=%(c)s")
            cnt("track_lots_products", "SELECT count(*) FROM products WHERE company_id=%(c)s AND track_lots IS TRUE")
            cnt("track_expiry_products", "SELECT count(*) FROM products WHERE company_id=%(c)s AND track_expiry IS TRUE")
            cnt("stock_batches", "SELECT count(*) FROM stock_batches WHERE company_id=%(c)s")
            cnt("sale_item_lot_allocations", "SELECT count(*) FROM sale_item_lot_allocations a JOIN products p ON p.id=a.product_id WHERE p.company_id=%(c)s")
            cnt("lot_shortfalls", "SELECT count(*) FROM lot_shortfalls WHERE company_id=%(c)s")
            cnt("return_item_lot_allocations", "SELECT count(*) FROM return_item_lot_allocations WHERE company_id=%(c)s")
            cnt("stock_movement_lot_allocations", "SELECT count(*) FROM stock_movement_lot_allocations WHERE company_id=%(c)s")
            cnt("cash_ledger_entries", "SELECT count(*) FROM cash.cash_ledger_entries WHERE tenant_id=%(c)s")
            cnt("cash_reconciliation_records", "SELECT count(*) FROM cash.reconciliation_records WHERE tenant_id=%(c)s")
            cnt("products_max_updated_at", "SELECT max(updated_at) FROM products WHERE company_id=%(c)s")
            cnt("stock_movements_max_created_at", "SELECT max(m.created_at) FROM stock_movements m JOIN products p ON p.id=m.product_id WHERE p.company_id=%(c)s")
        out["meta"]["query_errors"] = q.errors
        conn.rollback()

    print(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
