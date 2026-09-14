# -*- coding: utf-8 -*-
"""PRODUCTION DEPLOY GATE 89f647a — migration / readiness / CHECK definition / fail-recover proof
on the EPHEMERAL production clone (the restored PRE-DEPLOY production backup).

Runs AFTER the target initdb has migrated the clone. Refuses to run against anything but a
local database.

  P0  prod-mode readiness 200, lot_schema_integrity + catalog_v2_schema true
  P1  every REQUIRED FK satisfied; performance indexes VALID; legacy return uniqueness removed
  P2  lot activation DENIED in production env (policy + POST /lots/enable -> 403)
  P3  read-only Fayzan report smoke: 200s, pnl identity with cogs_variance, 4A fields serialize
  B*  critical FK / CHECK / unique index / column / whole table break -> 503 -> initdb -> 200
  C*  Phase 4A.1 CHECK DEFINITION validation on the production shape:
        wrong definition on a 4A table AND on the production products CHECK, NOT ENFORCED (PG18),
        unparsed definition (never auto-recreated), missing fatal-class CHECK (repair tool).
        Each: readiness 503, schema gate 409 in staging env / policy 403 in production env,
        boot never FATAL, safe repair path, the next boot is a no-op (same constraint oid)
  I*  performance-only index dropped / INVALID -> readiness stays 200, CONCURRENTLY rebuild
  O*  orphan row -> FK added NOT VALID, boot continues, readiness 503; fix + repair tool -> 200
  R*  rollback leg: da47aa8 code on the MIGRATED schema boots, is ready, reports work, DENY holds;
      roll-forward initdb afterwards is a no-op
  Z   final idempotent initdb: zero additions, identical object counts
"""
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit

import psycopg

URL = os.environ["CLONE_DATABASE_URL"]
if "@localhost" not in URL and "@127.0.0.1" not in URL:
    raise SystemExit("REFUSED: clone database must be local")
ROOT = os.getcwd()
SERVER = os.path.join(ROOT, "apps", "server")
ROLLBACK_SERVER = os.environ.get("ROLLBACK_SERVER")          # extracted da47aa8 apps/server
OUT = os.environ.get("GATE_OUT", "gate-out")
REQUIRE_PG18 = os.environ.get("GATE_REQUIRE_PG18") == "1"
ENV = dict(os.environ, DATABASE_URL=URL, APP_ENV="production", RAILWAY_ENVIRONMENT_NAME="production")
RESULTS = []


def rec(name, ok, note=""):
    RESULTS.append({"step": name, "ok": bool(ok), "note": str(note)[:900]})
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {str(note)[:600]}" if note else ""), flush=True)


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


# The REAL endpoint function, called with a stand-in session: 403 = activation policy refused,
# 409 = schema-integrity gate refused, 404 = BOTH gates passed and it went on to look the
# product up (the stand-in returns None, so nothing is ever written).
GATE = r'''
import types
from fastapi import HTTPException
from app.api.v1.lots import enable_tracking
from app.db.session import engine
fake = types.SimpleNamespace(get_bind=lambda: engine, get=lambda *a, **k: None)
code = "no-exception"
try:
    enable_tracking(data=types.SimpleNamespace(product_id=None, branch_id=None), emp=None, db=fake)
except HTTPException as e:
    code = e.status_code
print("GATE_STATUS=" + str(code))
'''


def gate_status(env_name, env=None):
    env = env or dict(ENV, APP_ENV=env_name, RAILWAY_ENVIRONMENT_NAME=env_name)
    p = subprocess.run([sys.executable, "-c", GATE], cwd=SERVER, env=env, capture_output=True,
                       text=True, timeout=300)
    for line in (p.stdout or "").splitlines():
        if line.startswith("GATE_STATUS="):
            v = line.split("=", 1)[1]
            return int(v) if v.isdigit() else v
    return "error: " + (p.stderr or "")[-400:]


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
                    "profit_includes_cost_adjustment", "gross_profit_basis", "cogs_known",
                    "cogs_estimated", "cogs_unknown", "revenue_known_cost", "revenue_estimated_cost",
                    "revenue_cost_unknown"))
            if u in ("/api/v1/reports/summary", "/api/v1/reports/dashboard") and r.status_code == 200:
                res[u]["has_4a_keys"] = all(k in body for k in ("cogs_variance", "profit_basis"))
            if u.startswith("/api/v1/reports/overview") and r.status_code == 200:
                res[u]["has_4a_keys"] = all(k in (body.get("kpi") or {}) for k in ("cogs_variance", "profit_basis"))
        r = c.post("/api/v1/lots/enable", json={"product_id": "00000000-0000-0000-0000-000000000000",
                                                "reason": "gate deny proof"})
        res["POST /lots/enable"] = {"status": r.status_code,
                                    "policy_detail": "partiya kuzatuvi bu muhitda" in r.text}
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
    with psycopg.connect(URL) as c:
        rows = c.execute(
            "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE c.contype = 'f' AND n.nspname = 'public' AND t.relname = %s "
            "AND (SELECT a.attname FROM pg_attribute a WHERE a.attrelid = c.conrelid "
            "     AND a.attnum = c.conkey[1]) = %s AND array_length(c.conkey, 1) = 1",
            (child, col)).fetchall()
        c.rollback()
    return [r[0] for r in rows]


def idx_valid(name):
    return scalar("SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c "
                  "ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                  "WHERE n.nspname = 'public' AND c.relname = %s", (name,))


RAW_READY = r'''
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    r = c.get('/api/v1/health/ready')
print("RAW_STATUS=" + str(r.status_code))
print("RAW_BODY=" + r.text)
'''


def raw_ready():
    p = subprocess.run([sys.executable, "-c", RAW_READY], cwd=SERVER, env=ENV, capture_output=True, text=True,
                       timeout=300)
    st, body = None, ""
    for ln in (p.stdout or "").splitlines():
        if ln.startswith("RAW_STATUS="):
            st = int(ln.split("=", 1)[1])
        elif ln.startswith("RAW_BODY="):
            body = ln[len("RAW_BODY="):]
    return st, body


def identity():
    with psycopg.connect(URL) as c:
        rel = c.execute("SELECT n.nspname || '.' || c.relname, c.oid::bigint, c.relfilenode::bigint FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('public','cash') "
                        "AND c.relkind IN ('r','p','i') ORDER BY 1").fetchall()
        con = c.execute("SELECT conrelid::regclass::text || '.' || conname, oid::bigint FROM pg_constraint "
                        "WHERE connamespace IN ('public'::regnamespace,'cash'::regnamespace) ORDER BY 1").fetchall()
        c.rollback()
    return [list(r) for r in rel], [list(r) for r in con]


def catalog(table, name):
    with psycopg.connect(URL) as c:
        r = c.execute(
            "SELECT c.oid::bigint, pg_get_expr(c.conbin, c.conrelid), c.convalidated "
            "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'public' AND t.relname = %s AND c.conname = %s AND c.contype = 'c'",
            (table, name)).fetchone()
        c.rollback()
    return r if r else (None, None, None)


def replace_check(table, name, clause):
    exe(f'ALTER TABLE "{table}" DROP CONSTRAINT {name}, ADD CONSTRAINT {name} {clause}')


def counts():
    with psycopg.connect(URL) as c:
        cols = c.execute("SELECT count(*) FROM information_schema.columns "
                         "WHERE table_schema IN ('public','cash')").fetchone()[0]
        idx = c.execute("SELECT count(*) FROM pg_indexes WHERE schemaname IN ('public','cash')").fetchone()[0]
        cons = c.execute("SELECT count(*) FROM pg_constraint WHERE connamespace IN "
                         "('public'::regnamespace,'cash'::regnamespace)").fetchone()[0]
        c.rollback()
    return cols, idx, cons


def brief(pb):
    return json.dumps({k: pb.get(k) for k in ("ready_status", "checks", "soft", "fatal", "fk_not_ok")},
                      ensure_ascii=False)


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
    rec(f"B-repair [{label}] readiness after repair = 200", pa.get("ready_status") == 200, brief(pa))


def check_definition_section():
    ver = int(scalar("SHOW server_version_num"))
    gs, gp = gate_status("staging"), gate_status("production")
    rec("C0 control on the healthy migrated clone: /lots/enable passes the schema gate in staging env "
        "(404 = got past it, nothing written) and is refused by policy in production env (403)",
        gs == 404 and gp == 403, f"staging={gs} production={gp} server_version_num={ver}")

    cases = [
        ("C1 wrong definition, right name, Phase 4A table", "lot_shortfall_resolutions",
         "ck_lsr_variance_identity", "CHECK (variance = actual_cost + provisional_cost)",
         "cheklov ta'rifi noto'g'ri: ck_lsr_variance_identity (lot_shortfall_resolutions)",
         "ta'rifi noto'g'ri edi — ayni tranzaksiyada qayta yaratildi"),
        ("C2 wrong definition, right name, the PRODUCTION products CHECK (7137 rows)", "products",
         "ck_track_expiry_implies_lots", "CHECK (NOT (track_expiry OR track_lots))",
         "cheklov ta'rifi noto'g'ri: ck_track_expiry_implies_lots (products)",
         "ta'rifi noto'g'ri edi — ayni tranzaksiyada qayta yaratildi"),
    ]
    if ver >= 180000:
        cases.append(("C3 NOT ENFORCED CHECK (PostgreSQL 18)", "lot_shortfalls",
                      "ck_lot_shortfall_resolved_le_qty", "CHECK (resolved_qty <= qty) NOT ENFORCED",
                      "cheklov majburlanmagan: ck_lot_shortfall_resolved_le_qty (lot_shortfalls)",
                      "NOT ENFORCED edi — ayni tranzaksiyada qayta yaratildi"))
    else:
        rec("C3 NOT ENFORCED CHECK (PostgreSQL 18)", not REQUIRE_PG18,
            f"server_version_num={ver} < 180000: NOT ENFORCED does not exist on this server"
            + (" — REQUIRED here" if REQUIRE_PG18 else " (local dry run only; CI requires PG18)"))

    for label, table, name, clause, soft_msg, log_msg in cases:
        replace_check(table, name, clause)
        pb = probe()
        if name == "ck_lsr_variance_identity":
            st_, body_ = raw_ready()
            secret_vals = [v for v in (os.environ.get("SECRET_KEY"), os.environ.get("VENDOR_ADMIN_KEY"),
                                       os.environ.get("VENDOR_TOTP_SECRET"), urlsplit(URL).password) if v]
            leaks = [s for s in ('missing_schema"', "ck_", "FK ", "stock_batches", "cheklov", "postgresql://",
                                 "postgres://", "password", "localhost") if s in body_]
            leaks += ["<secret value>" for v in secret_vals if v in body_]
            rec("C-leak production-mode /health/ready 503 body: no schema object name, no connection detail, "
                "no secret (only missing_schema_count)", st_ == 503 and not leaks and "missing_schema_count" in body_,
                {"status": st_, "leaks": leaks, "body": body_[:300]})
        rec(f"{label}: readiness 503, lot_schema_integrity=false, exact soft reason, NOT fatal",
            pb.get("ready_status") == 503 and (pb.get("checks") or {}).get("lot_schema_integrity") is False
            and soft_msg in (pb.get("soft") or []) and pb.get("fatal") == [], brief(pb))
        gs, gp = gate_status("staging"), gate_status("production")
        rec(f"{label}: /lots/enable blocked — schema gate 409 (staging env), policy 403 (production env)",
            gs == 409 and gp == 403, f"staging={gs} production={gp}")
        rc, log, fatal = initdb()
        mine = [ln for ln in log.splitlines() if name in ln]
        rec(f"{label}: target boot exit 0, no FATAL, replaced in ONE ALTER (NOT VALID) and validated",
            rc == 0 and not fatal and any(f"{name}: {log_msg}" in ln for ln in mine)
            and any(f"{name} tasdiqlandi" in ln for ln in mine), f"rc={rc} {mine}")
        rec(f"{label}: (informational) no TEMP probe relation remains",
            scalar("SELECT count(*) FROM pg_class WHERE relname = 'ck_4a1_probe_tmp'") == 0)
        pa = probe()
        gs2 = gate_status("staging")
        rec(f"{label}: readiness 200 after the boot repair and the schema gate opens again (staging 404)",
            pa.get("ready_status") == 200 and gs2 == 404, brief(pa) + f" staging={gs2}")
        before = catalog(table, name)
        rc, log, fatal = initdb()
        after = catalog(table, name)
        rec(f"{label}: the next boot is a no-op (same constraint oid, no rebuild line)",
            rc == 0 and not fatal and "qayta yaratildi" not in log and before[0] == after[0] and after[2] is True,
            f"oid {before[0]} -> {after[0]} validated={after[2]}")

    # C4 — unparsed definition: red, blocked, but NEVER auto-recreated
    replace_check("lot_shortfall_resolutions", "ck_lsr_qty_pos", "CHECK (abs(qty) > 0)")
    pb = probe()
    msg = "cheklov ta'rifini tekshirib bo'lmadi: ck_lsr_qty_pos (lot_shortfall_resolutions)"
    rec("C4 unparsed definition: readiness 503 with the 'could not be checked' reason, NOT fatal",
        pb.get("ready_status") == 503 and msg in (pb.get("soft") or []) and pb.get("fatal") == [], brief(pb))
    gs, gp = gate_status("staging"), gate_status("production")
    rec("C4 unparsed definition: /lots/enable 409 (staging env) / 403 (production env)",
        gs == 409 and gp == 403, f"staging={gs} production={gp}")
    before = catalog("lot_shortfall_resolutions", "ck_lsr_qty_pos")
    rc, log, fatal = initdb()
    after = catalog("lot_shortfall_resolutions", "ck_lsr_qty_pos")
    rec("C4 unparsed definition is NEVER auto-recreated: boot exit 0, same oid, reason logged, still 503",
        rc == 0 and not fatal and "ck_lsr_qty_pos: katalogdagi ta'rifni tahlil qilib bo'lmadi" in log
        and "ck_lsr_qty_pos: ta'rifi noto'g'ri edi" not in log and before[0] == after[0]
        and probe().get("ready_status") == 503, f"rc={rc} oid {before[0]} -> {after[0]}")
    replace_check("lot_shortfall_resolutions", "ck_lsr_qty_pos", "CHECK (qty > 0)")
    rec("C4 operator restores the definition -> readiness 200", probe().get("ready_status") == 200)

    # C5 — fatal-class CHECK missing: the safe path is the repair tool
    exe("ALTER TABLE products DROP CONSTRAINT ck_track_expiry_implies_lots")
    pb = probe()
    gs = gate_status("staging")
    rec("C5 products CHECK missing: readiness 503 via the fatal set, schema gate 409",
        pb.get("ready_status") == 503 and "cheklov yo'q: ck_track_expiry_implies_lots (products)" in (pb.get("fatal") or [])
        and gs == 409, brief(pb) + f" staging={gs}")
    rr = subprocess.run([sys.executable, "-m", "app.tools.repair_lot_schema"], cwd=SERVER, env=ENV,
                        capture_output=True, text=True, timeout=300)
    rec("C5 repair tool re-adds and validates it (exit 0) -> readiness 200",
        rr.returncode == 0 and "ck_track_expiry_implies_lots qo'shildi" in (rr.stdout or "")
        and probe().get("ready_status") == 200, (rr.stdout or "")[-400:])


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
    for child, col in (("stock_batches", "company_id"), ("stock_batches", "purchase_item_id"),
                       ("stock_batches", "supplier_id")):
        names = fk_names(child, col)
        ok = len(names) == 1 and scalar("SELECT convalidated FROM pg_constraint WHERE conname = %s", (names[0],)) is True
        rec(f"P1 production-missing FK {child}({col}) added and VALIDATED by the boot", ok, names)

    # ── P2/P3 ────────────────────────────────────────────────────────────────
    sm = smoke()
    ep = sm.get("endpoints") or {}
    rec("P3 smoke ran read-only (write guard enforced)", sm.get("write_guard") == "enforced", json.dumps(sm)[:500])
    rec("P3 Fayzan employee found for report smoke", sm.get("fayzan_employee_found") is True)
    rec("P3 every report/lots GET = 200",
        bool(ep) and all(v.get("status") == 200 for k, v in ep.items() if not k.startswith("POST")),
        json.dumps({k: v.get("status") for k, v in ep.items()}))
    rec("P3 pnl identity with cogs_variance holds; variance = 0 (no shortfalls in production); 4A keys present",
        all(v.get("identity_ok") and v.get("cogs_variance") == 0.0 and v.get("has_4a_keys")
            for k, v in ep.items() if "reports/pnl" in k), json.dumps({k: v for k, v in ep.items() if "pnl" in k}))
    rec("P3 summary / dashboard / overview.kpi serialize cogs_variance and profit_basis",
        all((ep.get(u) or {}).get("has_4a_keys") is True for u in (
            "/api/v1/reports/summary", "/api/v1/reports/dashboard", "/api/v1/reports/overview?period=month")),
        json.dumps({k: v.get("has_4a_keys") for k, v in ep.items()}))
    rec("P2 POST /lots/enable in production env = 403 from the ACTIVATION POLICY (detail text), not a permission",
        (ep.get("POST /lots/enable") or {}).get("status") == 403
        and (ep.get("POST /lots/enable") or {}).get("policy_detail") is True, json.dumps(ep.get("POST /lots/enable")))
    no_app = {k: v for k, v in ENV.items() if k != "APP_ENV"}
    g_platform = gate_status(None, dict(no_app, RAILWAY_ENVIRONMENT_NAME="production"))
    g_nothing = gate_status(None, {k: v for k, v in no_app.items() if k != "RAILWAY_ENVIRONMENT_NAME"})
    rec("P2b fail-closed without APP_ENV: platform=production -> 403; APP_ENV and platform BOTH missing -> 403",
        g_platform == 403 and g_nothing == 403, f"platform_only={g_platform} nothing_set={g_nothing}")
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

    # ── C: CHECK definition validation (Phase 4A.1) ──────────────────────────
    check_definition_section()

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
        gs = gate_status("staging")
        rec("O-orphan /lots/enable schema gate 409 while the FK is NOT VALID", gs == 409, f"staging={gs}")
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
        rec("R da47aa8 readiness 200 on the migrated schema (and it really is da47aa8: no Phase 4A API)",
            pr.get("ready_status") == 200 and "legacy_api" in pr, json.dumps(pr)[:400])
        sr = smoke(ROLLBACK_SERVER)
        epr = sr.get("endpoints") or {}
        rec("R da47aa8 report smoke 200 + activation DENY 403",
            bool(epr) and all(v.get("status") == 200 for k, v in epr.items() if not k.startswith("POST"))
            and (epr.get("POST /lots/enable") or {}).get("status") == 403
            and (epr.get("POST /lots/enable") or {}).get("policy_detail") is True,
            json.dumps({k: v.get("status") for k, v in epr.items()}))
        rc, log, fatal = initdb()
        rec("R roll-forward target initdb after the rollback boot: exit 0, no FATAL, "
            "legacy return uniqueness removed again",
            rc == 0 and not fatal and "noyobligi olib tashlandi" in log, f"rc={rc} {fatal[:2]}")
        rec("R roll-forward readiness 200", probe().get("ready_status") == 200)
        before = counts()
        rc, log, fatal = initdb()
        after = counts()
        rec("R roll-forward is stable: a further target initdb changes nothing",
            rc == 0 and not fatal and before == after, f"{before} -> {after}")
    else:
        rec("R rollback leg executed", False, "ROLLBACK_SERVER not provided")

    # ── Z: idempotent reboot ─────────────────────────────────────────────────
    before = counts()
    id_before = identity()
    rc, log, fatal = initdb()
    after = counts()
    id_after = identity()
    noisy = [ln for ln in log.splitlines()
             if "qo'shildi" in ln or "[fk]" in ln or "CONCURRENTLY qurildi" in ln or "tasdiqlandi" in ln
             or "qayta yaratildi" in ln]
    rec("Z final initdb: exit 0, zero additions, identical object counts AND identical physical identity "
        "(oid/relfilenode of every table, index, constraint)",
        rc == 0 and not fatal and not noisy and before == after and id_before == id_after,
        f"{before} -> {after} identity_equal={id_before == id_after} {noisy[:3]}")
    pz = probe()
    rec("Z final readiness 200, lot_schema_integrity true", pz.get("ready_status") == 200
        and (pz.get("checks") or {}).get("lot_schema_integrity") is True, brief(pz))

    with open(os.path.join(OUT, "clone_proof_89f647a.json"), "w", encoding="utf-8") as f:
        json.dump({"results": RESULTS, "probe_after_migration": p0, "smoke": sm}, f, indent=1,
                  ensure_ascii=False, default=str)
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"\nCLONE PROOF 89f647a: {len(RESULTS) - len(bad)}/{len(RESULTS)} OK")
    for b in bad:
        print("  FAILED:", b["step"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
