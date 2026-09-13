# -*- coding: utf-8 -*-
"""PHASE 4A — migration / readiness / fail-recover proof on the EPHEMERAL production clone.

Runs AFTER the target (Phase 4A) initdb has migrated the restored production backup.
Refuses to run against anything but a local database.

  P0  prod-mode readiness 200, lot_schema_integrity + catalog_v2_schema true
  P1  every REQUIRED FK satisfied; every performance index present and VALID
  P2  lot activation DENIED in production env (policy + POST /lots/enable -> 403)
  P3  legacy-shape probe = 0; read-only Fayzan report smoke (pnl identity with cogs_variance)
  B*  break a critical FK / unique index / CHECK / column / whole new table -> readiness 503,
      target initdb exit 0 (never FATAL for FK/CHECK states) -> restored -> readiness 200
  I*  performance index dropped / INVALID -> readiness stays 200, initdb rebuilds CONCURRENTLY
  O*  orphan row -> FK added NOT VALID, boot continues, readiness 503; fix + repair tool -> 200
  R*  rollback leg: da47aa8 code on the MIGRATED schema boots, is ready, reports work, DENY holds;
      roll-forward initdb afterwards is a no-op
  Z   final idempotent initdb: zero additions, identical object counts
"""
import json
import os
import subprocess
import sys

import psycopg

URL = os.environ["CLONE_DATABASE_URL"]
if "@localhost" not in URL and "@127.0.0.1" not in URL:
    raise SystemExit("REFUSED: clone database must be local")
ROOT = os.getcwd()
SERVER = os.path.join(ROOT, "apps", "server")
ROLLBACK_SERVER = os.environ.get("ROLLBACK_SERVER")          # extracted da47aa8 apps/server
OUT = os.environ.get("GATE_OUT", "gate-out")
ENV = dict(os.environ, DATABASE_URL=URL, APP_ENV="production", RAILWAY_ENVIRONMENT_NAME="production")
RESULTS = []


def rec(name, ok, note=""):
    RESULTS.append({"step": name, "ok": bool(ok), "note": str(note)[:600]})
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {note}" if note else ""), flush=True)


def exe(sql, params=None):
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(sql, params)


def scalar(sql, params=None):
    with psycopg.connect(URL) as c:
        r = c.execute(sql, params).fetchone()
        c.rollback()
    return r[0] if r else None


def initdb(server=SERVER):
    p = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=server, env=ENV,
                       capture_output=True, text=True, timeout=900)
    log = (p.stdout or "") + (p.stderr or "")
    fatal = [ln for ln in log.splitlines() if "[FATAL]" in ln or "Traceback" in ln]
    return p.returncode, log, fatal


PROBE = r'''
import json, os, sys
from fastapi.testclient import TestClient
from app.main import app
out = {}
with TestClient(app) as c:
    r = c.get('/api/v1/health/ready')
    out['ready_status'] = r.status_code
    out['checks'] = r.json().get('checks')
    out['missing_schema_count'] = r.json().get('missing_schema_count')
try:
    from app.core import required_schema as rs
    from app.db.session import engine
    out['fk_not_ok'] = [f"{k.label}: {v[0]}" for k, v in rs.fk_states(engine).items() if v[0] != rs.FK_OK]
    out['perf_missing'] = rs.performance_missing(engine)
    out['soft'] = rs.soft_missing(engine)
    out['fatal'] = rs.fatal_missing(engine)
except AttributeError as e:          # rollback leg: da47aa8 has no Phase 4A API
    out['legacy_api'] = str(e)
print('PROBE_JSON=' + json.dumps(out))
'''


def probe(server=SERVER):
    p = subprocess.run([sys.executable, "-c", PROBE], cwd=server, env=ENV, capture_output=True,
                       text=True, timeout=300)
    for line in (p.stdout or "").splitlines():
        if line.startswith("PROBE_JSON="):
            return json.loads(line[len("PROBE_JSON="):])
    return {"ready_status": None, "error": (p.stderr or "")[-800:]}


SMOKE = r'''
import os
os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=60000"
import json
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core import deps
from app.db.session import SessionLocal
from app.models.auth import Employee
s = SessionLocal()
out = {"ro": s.execute(text("SHOW default_transaction_read_only")).scalar()}
try:
    s.execute(text("UPDATE companies SET code = code WHERE false")); out["write_guard"] = "NOT ENFORCED"
except Exception:
    out["write_guard"] = "enforced"; s.rollback()
eid = s.execute(text("SELECT e.id FROM employees e JOIN companies c ON c.id = e.company_id "
                     "WHERE c.code IN ('fayzan1','fayzan') AND e.deleted_at IS NULL "
                     "ORDER BY c.code DESC, e.created_at LIMIT 1")).scalar()
out["fayzan_employee_found"] = eid is not None
if eid is not None:
    emp = s.get(Employee, eid)
    _ = emp.role.permissions
    app.dependency_overrides[deps.get_current_employee] = lambda: emp
    res = {}
    with TestClient(app) as c:
        for u in ["/api/v1/reports/pnl?period=month", "/api/v1/reports/pnl?period=all",
                  "/api/v1/reports/summary", "/api/v1/reports/dashboard",
                  "/api/v1/reports/overview?period=month", "/api/v1/reports/top-products?period=month",
                  "/api/v1/reports/detail?period=month", "/api/v1/reports/categories?period=month",
                  "/api/v1/lots/shortfalls"]:
            r = c.get(u)
            body = r.json() if r.status_code == 200 else {}
            res[u] = {"status": r.status_code}
            if "reports/pnl" in u and r.status_code == 200:
                cogs = (body["cogs_known"] + body["cogs_estimated"] + body["cogs_unknown"]
                        - body["cogs_returns_unlinked"] - body["cogs_returns_prior_period"]
                        + body.get("cogs_variance", 0))
                res[u]["identity_ok"] = round(cogs, 2) == round(body["cogs"], 2)
                res[u]["cogs_variance"] = body.get("cogs_variance")
                res[u]["has_4a_keys"] = all(k in body for k in (
                    "cogs_variance", "cogs_variance_resolutions", "cogs_variance_return_reversals",
                    "profit_includes_cost_adjustment"))
        r = c.post("/api/v1/lots/enable", json={"product_id": "00000000-0000-0000-0000-000000000000",
                                                "reason": "gate deny proof"})
        res["POST /lots/enable"] = {"status": r.status_code}
    out["endpoints"] = res
print("SMOKE_JSON=" + json.dumps(out))
'''


def smoke(server=SERVER):
    p = subprocess.run([sys.executable, "-c", SMOKE], cwd=server, env=ENV, capture_output=True,
                       text=True, timeout=600)
    for line in (p.stdout or "").splitlines():
        if line.startswith("SMOKE_JSON="):
            return json.loads(line[len("SMOKE_JSON="):])
    return {"error": (p.stderr or "")[-1200:]}


def fk_names(child, col):
    return [r[0] for r in psycopg.connect(URL).execute(
        "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE c.contype = 'f' AND n.nspname = 'public' AND t.relname = %s "
        "AND (SELECT a.attname FROM pg_attribute a WHERE a.attrelid = c.conrelid "
        "     AND a.attnum = c.conkey[1]) = %s AND array_length(c.conkey, 1) = 1",
        (child, col)).fetchall()]


def idx_valid(name):
    return scalar("SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c "
                  "ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                  "WHERE n.nspname = 'public' AND c.relname = %s", (name,))


def counts():
    with psycopg.connect(URL) as c:
        cols = c.execute("SELECT count(*) FROM information_schema.columns "
                         "WHERE table_schema IN ('public','cash')").fetchone()[0]
        idx = c.execute("SELECT count(*) FROM pg_indexes WHERE schemaname IN ('public','cash')").fetchone()[0]
        cons = c.execute("SELECT count(*) FROM pg_constraint WHERE connamespace IN "
                         "('public'::regnamespace,'cash'::regnamespace)").fetchone()[0]
        c.rollback()
    return cols, idx, cons


def break_repair(label, brk_sqls, restored, *, want_while_broken, check_key):
    for s in brk_sqls:
        exe(s)
    pb = probe()
    ok_broken = (pb.get("ready_status") == want_while_broken
                 and (want_while_broken == 200 or (pb.get("checks") or {}).get(check_key) is False))
    rec(f"B-break [{label}] readiness while broken = {want_while_broken}"
        + ("" if want_while_broken == 200 else f" ({check_key}=false)"), ok_broken,
        json.dumps({k: pb.get(k) for k in ("ready_status", "checks", "missing_schema_count")}))
    rc, log, fatal = initdb()
    rec(f"B-repair [{label}] target initdb exit 0, no FATAL/Traceback", rc == 0 and not fatal,
        f"rc={rc} {fatal[:2]}")
    rec(f"B-repair [{label}] object restored", restored(), "")
    pa = probe()
    rec(f"B-repair [{label}] readiness after repair = 200", pa.get("ready_status") == 200,
        json.dumps({k: pa.get(k) for k in ("ready_status", "checks", "fk_not_ok", "soft")}))


def main():
    os.makedirs(OUT, exist_ok=True)

    # ── P0/P1 ────────────────────────────────────────────────────────────────
    p0 = probe()
    rec("P0 prod-mode readiness 200 after migration", p0.get("ready_status") == 200, json.dumps(p0))
    rec("P0 checks.lot_schema_integrity true", (p0.get("checks") or {}).get("lot_schema_integrity") is True)
    rec("P0 checks.catalog_v2_schema true", (p0.get("checks") or {}).get("catalog_v2_schema") is True)
    rec("P1 every REQUIRED FK satisfied", p0.get("fk_not_ok") == [], json.dumps(p0.get("fk_not_ok")))
    rec("P1 every performance index present and VALID", p0.get("perf_missing") == [],
        json.dumps(p0.get("perf_missing")))
    rec("P1 ix_sale_items_sale_id valid on the production-shaped sale_items", idx_valid("ix_sale_items_sale_id") is True)
    legacy_uq = scalar(
        "SELECT count(*) FROM pg_index i WHERE i.indrelid = to_regclass('public.return_item_lot_allocations') "
        "AND i.indisunique AND i.indnkeyatts = 2 AND (SELECT array_agg(a.attname::text ORDER BY a.attname::text) "
        "FROM pg_attribute a WHERE a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)) "
        "= ARRAY['return_item_id','stock_batch_id']")
    rec("P1 legacy (return_item_id, stock_batch_id) uniqueness removed; ux_ret_alloc_line valid",
        legacy_uq == 0 and idx_valid("ux_ret_alloc_line") is True, f"legacy_unique_indexes={legacy_uq}")
    for t in ("lot_shortfall_resolution_requests", "lot_shortfall_resolutions",
              "return_item_shortfall_allocations", "return_item_resolution_allocations"):
        rec(f"P1 new table {t} exists (empty)", scalar("SELECT count(*) FROM " + t) == 0)

    # ── P2/P3 ────────────────────────────────────────────────────────────────
    sm = smoke()
    ep = sm.get("endpoints") or {}
    rec("P3 smoke ran read-only (write guard enforced)", sm.get("write_guard") == "enforced", json.dumps(sm)[:500])
    rec("P3 Fayzan employee found for report smoke", sm.get("fayzan_employee_found") is True)
    rec("P3 every report/lots GET = 200",
        bool(ep) and all(v.get("status") == 200 for k, v in ep.items() if not k.startswith("POST")),
        json.dumps({k: v.get("status") for k, v in ep.items()}))
    rec("P3 pnl identity with cogs_variance holds; variance = 0; Phase 4A keys present",
        all(v.get("identity_ok") and v.get("cogs_variance") == 0.0 and v.get("has_4a_keys")
            for k, v in ep.items() if "reports/pnl" in k), json.dumps({k: v for k, v in ep.items() if "pnl" in k}))
    rec("P2 POST /lots/enable in production env = 403 (activation DENIED)",
        (ep.get("POST /lots/enable") or {}).get("status") == 403, json.dumps(ep.get("POST /lots/enable")))
    legacy = scalar("""
        SELECT count(*) FROM lot_shortfalls sf WHERE
          sf.resolved_qty <> coalesce((SELECT sum(qty) FROM lot_shortfall_resolutions e WHERE e.shortfall_id = sf.id), 0)
          OR coalesce(sf.returned_qty, 0) <> coalesce((SELECT sum(qty) FROM return_item_shortfall_allocations r WHERE r.shortfall_id = sf.id), 0)""")
    rec("P3 legacy-shape probe = 0 (no pre-4A resolved/returned shortfalls)", legacy == 0, f"count={legacy}")

    # ── B: critical objects ──────────────────────────────────────────────────
    for child, col in (("return_item_lot_allocations", "stock_batch_id"),
                       ("stock_movement_lot_allocations", "stock_movement_id"),
                       ("sale_item_lot_allocations", "stock_batch_id"),
                       ("lot_shortfall_resolutions", "request_id"),
                       ("stock_batches", "company_id")):
        names = fk_names(child, col)
        break_repair(f"critical FK {child}({col})",
                     [f'ALTER TABLE {child} DROP CONSTRAINT "{n}"' for n in names],
                     lambda c=child, k=col: len(fk_names(c, k)) >= 1,
                     want_while_broken=503, check_key="lot_schema_integrity")
    break_repair("required CHECK ck_lsr_variance_identity",
                 ["ALTER TABLE lot_shortfall_resolutions DROP CONSTRAINT ck_lsr_variance_identity"],
                 lambda: scalar("SELECT count(*) FROM pg_constraint WHERE conname = 'ck_lsr_variance_identity' AND convalidated") == 1,
                 want_while_broken=503, check_key="lot_schema_integrity")
    break_repair("required unique index ux_lsr_request_client",
                 ["DROP INDEX ux_lsr_request_client"], lambda: idx_valid("ux_lsr_request_client") is True,
                 want_while_broken=503, check_key="catalog_v2_schema")
    break_repair("required column sale_items.provisional_qty",
                 ["ALTER TABLE sale_items DROP COLUMN provisional_qty"],
                 lambda: scalar("SELECT count(*) FROM information_schema.columns WHERE table_name='sale_items' AND column_name='provisional_qty'") == 1,
                 want_while_broken=503, check_key="catalog_v2_schema")
    break_repair("whole new table return_item_resolution_allocations",
                 ["DROP TABLE return_item_resolution_allocations"],
                 lambda: scalar("SELECT to_regclass('public.return_item_resolution_allocations') IS NOT NULL") is True
                 and len(fk_names("return_item_resolution_allocations", "resolution_id")) == 1,
                 want_while_broken=503, check_key="catalog_v2_schema")

    # ── I: performance-only index ────────────────────────────────────────────
    exe("DROP INDEX ix_sale_items_sale_id")
    pb = probe()
    rec("I-break ix_sale_items_sale_id dropped: readiness STAYS 200 (performance-only)",
        pb.get("ready_status") == 200 and "tezlik indeksi yo'q: ix_sale_items_sale_id" in (pb.get("perf_missing") or []),
        json.dumps({k: pb.get(k) for k in ("ready_status", "perf_missing")}))
    rc, log, fatal = initdb()
    rec("I-repair initdb rebuilds it CONCURRENTLY (exit 0)",
        rc == 0 and not fatal and "ix_sale_items_sale_id CONCURRENTLY qurildi" in log and idx_valid("ix_sale_items_sale_id") is True,
        f"rc={rc}")
    exe("UPDATE pg_index SET indisvalid = false WHERE indexrelid = 'public.ix_sale_items_sale_id'::regclass")
    rc, log, fatal = initdb()
    rec("I-invalid INVALID index (failed CONCURRENTLY) is dropped and rebuilt",
        rc == 0 and "YAROQSIZ" in log and idx_valid("ix_sale_items_sale_id") is True, f"rc={rc}")

    # ── O: orphan row keeps FK NOT VALID, boot continues ────────────────────
    # The lookup connection is CLOSED (and its snapshot rolled back): an idle-in-transaction
    # session would keep ACCESS SHARE on products/branches/companies and stall later DDL.
    with psycopg.connect(URL) as lc:
        row = lc.execute(
            "SELECT p.company_id, p.id, (SELECT b.id FROM branches b WHERE b.company_id = p.company_id "
            "ORDER BY b.created_at LIMIT 1) FROM products p JOIN companies c ON c.id = p.company_id "
            "ORDER BY (c.code IN ('fayzan1','fayzan')) DESC, p.created_at LIMIT 1").fetchone()
        lc.rollback()
    have_owner = row is not None and row[2] is not None
    rec("O-setup a product with a branch exists to own the orphan row", have_owner, row)
    names = fk_names("stock_batches", "supplier_id")
    fk_valid = scalar("SELECT count(*) FROM pg_constraint WHERE conname::text = ANY(%s) AND convalidated",
                      (list(names),))
    rec("O-setup supplier_id FK present and validated after the migration",
        len(names) == 1 and fk_valid == 1, names)
    if have_owner:
        cid, pid, bid = row
        # The migration has ALREADY added and validated stock_batches.supplier_id -> suppliers, so
        # the orphan can only exist the way it would on a pre-4A database: drop the FK FIRST.
        for n in names:
            exe(f'ALTER TABLE stock_batches DROP CONSTRAINT "{n}"')
        exe("INSERT INTO stock_batches (id, company_id, product_id, branch_id, qty, received_qty, remaining_qty,"
            " unit_cost, status, source_type, received_at, created_at, row_version, supplier_id)"
            " VALUES (gen_random_uuid(), %s, %s, %s, 0, 0, 0, 0, 'void', 'gate_orphan', now(), now(), 1, gen_random_uuid())",
            (cid, pid, bid))
        rc, log, fatal = initdb()
        validated = scalar("SELECT bool_and(c.convalidated) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                           "WHERE c.contype = 'f' AND t.relname = 'stock_batches' AND (SELECT a.attname FROM pg_attribute a "
                           "WHERE a.attrelid = c.conrelid AND a.attnum = c.conkey[1]) = 'supplier_id'")
        rec("O-orphan initdb exit 0 (NOT FATAL), FK added NOT VALID, orphan logged",
            rc == 0 and not fatal and "YETIM" in log and validated is False, f"rc={rc} validated={validated}")
        pb = probe()
        rec("O-orphan readiness 503 while the FK is NOT VALID", pb.get("ready_status") == 503
            and (pb.get("checks") or {}).get("lot_schema_integrity") is False, json.dumps(pb.get("soft")))
        exe("UPDATE stock_batches SET supplier_id = NULL WHERE source_type = 'gate_orphan'")
        rr = subprocess.run([sys.executable, "-m", "app.tools.repair_lot_schema"], cwd=SERVER, env=ENV,
                            capture_output=True, text=True, timeout=300)
        rec("O-repair tool validates the FK after the orphan is fixed (exit 0)", rr.returncode == 0,
            (rr.stdout or "")[-300:])
        rec("O-repair readiness back to 200", probe().get("ready_status") == 200)
        exe("DELETE FROM stock_batches WHERE source_type = 'gate_orphan'")

    # ── R: rollback leg (da47aa8 on the migrated schema) ─────────────────────
    if ROLLBACK_SERVER and os.path.isdir(ROLLBACK_SERVER):
        rc, log, fatal = initdb(ROLLBACK_SERVER)
        rec("R da47aa8 initdb on the MIGRATED schema: exit 0, no FATAL", rc == 0 and not fatal, f"rc={rc} {fatal[:2]}")
        pr = probe(ROLLBACK_SERVER)
        rec("R da47aa8 readiness 200 on the migrated schema", pr.get("ready_status") == 200, json.dumps(pr)[:400])
        sr = smoke(ROLLBACK_SERVER)
        epr = sr.get("endpoints") or {}
        rec("R da47aa8 report smoke 200 + activation DENY 403",
            bool(epr) and all(v.get("status") == 200 for k, v in epr.items() if not k.startswith("POST"))
            and (epr.get("POST /lots/enable") or {}).get("status") == 403,
            json.dumps({k: v.get("status") for k, v in epr.items()}))
        # da47aa8 re-creates its legacy strict `ux_ret_alloc` (it is REQUIRED there); the Phase 4A
        # roll-forward must remove it again — so object counts are compared on the NEXT boot.
        rc, log, fatal = initdb()
        rec("R roll-forward Phase 4A initdb after the rollback boot: exit 0, no FATAL, "
            "legacy return uniqueness removed again",
            rc == 0 and not fatal and "noyobligi olib tashlandi" in log, f"rc={rc} {fatal[:2]}")
        rec("R roll-forward readiness 200", probe().get("ready_status") == 200)
        before = counts()
        rc, log, fatal = initdb()
        after = counts()
        rec("R roll-forward is stable: a further Phase 4A initdb changes nothing",
            rc == 0 and not fatal and before == after, f"{before} -> {after}")
    else:
        rec("R rollback leg executed", False, "ROLLBACK_SERVER not provided")

    # ── Z: idempotent reboot ─────────────────────────────────────────────────
    before = counts()
    rc, log, fatal = initdb()
    after = counts()
    noisy = [ln for ln in log.splitlines()
             if "qo'shildi" in ln or "[fk]" in ln or "CONCURRENTLY qurildi" in ln or "tasdiqlandi" in ln]
    rec("Z final initdb: exit 0, zero additions, identical object counts",
        rc == 0 and not fatal and not noisy and before == after, f"{before} -> {after} {noisy[:3]}")

    with open(os.path.join(OUT, "phase4a_migration_proof.json"), "w", encoding="utf-8") as f:
        json.dump({"results": RESULTS, "probe_after_migration": p0, "smoke": sm}, f, indent=1,
                  ensure_ascii=False, default=str)
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"\nPHASE 4A MIGRATION PROOF: {len(RESULTS) - len(bad)}/{len(RESULTS)} OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
