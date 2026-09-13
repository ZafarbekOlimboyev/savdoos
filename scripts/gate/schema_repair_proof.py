# -*- coding: utf-8 -*-
"""STEP 7 — schema repair / fail-closed proof on the EPHEMERAL production clone.

For representative objects the target code depends on:
  break the object -> readiness must be 503 if the object is REQUIRED (fail-closed),
  run target `python -m app.initdb` -> object restored -> readiness 200.
Plus: an initdb that cannot repair a required object must EXIT NON-ZERO with [FATAL]
(start.sh has `set -e`, so uvicorn never starts), and an inventory of objects that only
`create_all` creates (never repaired on an existing table).

Refuses to run against anything but a local database.
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
OUT = os.environ.get("GATE_OUT", "gate-out")
ENV = dict(os.environ, DATABASE_URL=URL, APP_ENV="production", RAILWAY_ENVIRONMENT_NAME="production")
RESULTS = []


def rec(name, ok, note=""):
    RESULTS.append({"step": name, "ok": bool(ok), "note": str(note)[:400]})
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {note}" if note else ""), flush=True)


def exe(sql):
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(sql)


def scalar(sql, p=()):
    with psycopg.connect(URL) as c:
        r = c.execute(sql, p).fetchone()
        c.rollback()
    return r[0] if r else None


def table_exists(t):
    return bool(scalar("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name=%s", (t,)))


def col_exists(t, c):
    return bool(scalar("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
                       "AND table_name=%s AND column_name=%s", (t, c)))


def idx_exists(n):
    return bool(scalar("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexname=%s", (n,)))


def con_exists(n):
    return bool(scalar("SELECT count(*) FROM pg_constraint WHERE conname=%s", (n,)))


def initdb(url=URL):
    p = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SERVER, env=dict(ENV, DATABASE_URL=url),
                       capture_output=True, text=True, timeout=900)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


READY = ("import json\nfrom fastapi.testclient import TestClient\nfrom app.main import app\n"
         "with TestClient(app) as c:\n"
         "    r = c.get('/api/v1/health/ready')\n"
         "    print('READY_JSON=' + json.dumps({'status': r.status_code, 'checks': r.json().get('checks')}))\n")


def ready():
    p = subprocess.run([sys.executable, "-c", READY], cwd=SERVER, env=ENV, capture_output=True, text=True, timeout=300)
    for line in (p.stdout or "").splitlines():
        if line.startswith("READY_JSON="):
            return json.loads(line[len("READY_JSON="):])
    return {"status": None, "error": ((p.stderr or "")[-400:])}


NEW_TABLE_COLS = {
    "stock_movement_lot_allocations": ["company_id", "stock_movement_id", "stock_batch_id", "product_id", "qty", "unit_cost"],
    "return_item_lot_allocations": ["company_id", "return_item_id", "sale_item_id", "stock_batch_id", "product_id", "qty", "unit_cost"],
}

CASES = [
    # (label, break SQL, restored check, required -> readiness must be 503 while broken)
    ("required index ux_ret_alloc", "DROP INDEX ux_ret_alloc", lambda: idx_exists("ux_ret_alloc"), True),
    ("required index ux_smove_alloc", "DROP INDEX ux_smove_alloc", lambda: idx_exists("ux_smove_alloc"), True),
    ("required column return_items.cost_total", "ALTER TABLE return_items DROP COLUMN cost_total",
     lambda: col_exists("return_items", "cost_total"), True),
    ("required column return_items.cost_unresolved", "ALTER TABLE return_items DROP COLUMN cost_unresolved",
     lambda: col_exists("return_items", "cost_unresolved"), True),
    ("required column sales.cost_basis", "ALTER TABLE sales DROP COLUMN cost_basis",
     lambda: col_exists("sales", "cost_basis"), True),
    ("required column lot_shortfalls.resolved_cost", "ALTER TABLE lot_shortfalls DROP COLUMN resolved_cost",
     lambda: col_exists("lot_shortfalls", "resolved_cost"), True),
    ("required column lot_shortfalls.returned_qty", "ALTER TABLE lot_shortfalls DROP COLUMN returned_qty",
     lambda: col_exists("lot_shortfalls", "returned_qty"), True),
    ("required column stock_movement_lot_allocations.unit_cost (new table, existing)",
     "ALTER TABLE stock_movement_lot_allocations DROP COLUMN unit_cost",
     lambda: col_exists("stock_movement_lot_allocations", "unit_cost"), True),
    ("whole new table stock_movement_lot_allocations", "DROP TABLE stock_movement_lot_allocations",
     lambda: table_exists("stock_movement_lot_allocations") and idx_exists("ux_smove_alloc")
     and all(col_exists("stock_movement_lot_allocations", c) for c in NEW_TABLE_COLS["stock_movement_lot_allocations"]), True),
    ("whole new table return_item_lot_allocations", "DROP TABLE return_item_lot_allocations",
     lambda: table_exists("return_item_lot_allocations") and idx_exists("ux_ret_alloc")
     and all(col_exists("return_item_lot_allocations", c) for c in NEW_TABLE_COLS["return_item_lot_allocations"]), True),
    ("speed-only index ix_ret_alloc_item (not required: readiness stays 200)", "DROP INDEX ix_ret_alloc_item",
     lambda: idx_exists("ix_ret_alloc_item"), False),
    ("required CHECK ck_track_expiry_implies_lots (readiness enforces it)",
     "ALTER TABLE products DROP CONSTRAINT ck_track_expiry_implies_lots",
     lambda: con_exists("ck_track_expiry_implies_lots"), True),
]


def main():
    r0 = ready()
    rec("S0 baseline readiness after migration = 200", r0.get("status") == 200, json.dumps(r0))

    for label, brk, restored, required in CASES:
        exe(brk)
        rb = ready()
        want = 503 if required else 200
        rec(f"S-break [{label}] readiness while broken = {want}", rb.get("status") == want, json.dumps(rb))
        rc, log = initdb()
        fatal = [ln for ln in log.splitlines() if "[FATAL]" in ln or "Traceback" in ln]
        rec(f"S-repair [{label}] target initdb exit 0, no FATAL", rc == 0 and not fatal, f"rc={rc} {fatal[:2]}")
        rec(f"S-repair [{label}] object restored by initdb", restored(), "")
        ra = ready()
        rec(f"S-repair [{label}] readiness after repair = 200", ra.get("status") == 200, json.dumps(ra))

    # ── FAIL-CLOSED BOOT: initdb that CANNOT repair a required object must stop the boot ──
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(URL)
    dbname = parts.path.lstrip("/") or "postgres"
    exe("DROP OWNED BY gate_limited" if scalar("SELECT count(*) FROM pg_roles WHERE rolname='gate_limited'") else "SELECT 1")
    exe("DROP ROLE IF EXISTS gate_limited")
    exe("CREATE ROLE gate_limited LOGIN PASSWORD 'gate-limited-ephemeral'")
    exe(f'GRANT CONNECT ON DATABASE "{dbname}" TO gate_limited')
    exe("GRANT USAGE ON SCHEMA public TO gate_limited")
    exe("GRANT USAGE ON SCHEMA cash TO gate_limited")
    exe("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gate_limited")
    exe("GRANT SELECT ON ALL TABLES IN SCHEMA cash TO gate_limited")
    exe("ALTER TABLE return_items DROP COLUMN cost_unresolved")
    host = parts.netloc.rsplit("@", 1)[-1]
    limited = urlunsplit((parts.scheme, f"gate_limited:gate-limited-ephemeral@{host}", parts.path, parts.query, ""))
    rc, log = initdb(limited)
    fatal = [ln for ln in log.splitlines() if "[FATAL]" in ln]
    rec("S-failclosed initdb WITHOUT table-owner rights exits NON-ZERO", rc != 0, f"rc={rc}")
    rec("S-failclosed initdb names the unrepairable REQUIRED column",
        any("return_items.cost_unresolved" in ln for ln in fatal), " | ".join(fatal[:3]))
    rb = ready()
    rec("S-failclosed readiness with the required column missing = 503", rb.get("status") == 503, json.dumps(rb))
    with open(os.path.join(ROOT, "apps", "server", "start.sh"), encoding="utf-8") as f:
        start = f.read()
    rec("S-failclosed start.sh has `set -e` before initdb (uvicorn never starts on initdb failure)",
        start.index("set -e") < start.index("python -m app.initdb") < start.index("exec uvicorn"), "")
    rc, log = initdb()
    rec("S-failclosed owner initdb repairs it (exit 0)", rc == 0 and col_exists("return_items", "cost_unresolved"), f"rc={rc}")
    rec("S-failclosed readiness back to 200", ready().get("status") == 200, "")

    # ── IDEMPOTENT REBOOT: a further initdb changes nothing ──
    def snapshot():
        with psycopg.connect(URL) as c:
            cols = c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema IN ('public','cash')").fetchone()[0]
            idx = c.execute("SELECT count(*) FROM pg_indexes WHERE schemaname IN ('public','cash')").fetchone()[0]
            cons = c.execute("SELECT count(*) FROM pg_constraint WHERE connamespace IN ('public'::regnamespace,'cash'::regnamespace)").fetchone()[0]
            c.rollback()
        return cols, idx, cons
    before = snapshot()
    rc, log = initdb()
    after = snapshot()
    added = [ln for ln in log.splitlines() if "qo'shildi" in ln]
    rec("S-idempotent extra initdb: exit 0, zero additions, identical object counts",
        rc == 0 and not added and before == after, f"{before} -> {after} {added[:2]}")

    # ── INVENTORY: objects ONLY create_all makes (never repaired on an existing table) ──
    with psycopg.connect(URL) as c:
        rows = c.execute(
            "SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid::regclass::text IN ('return_item_lot_allocations','stock_movement_lot_allocations') "
            "ORDER BY 1,2").fetchall()
        c.rollback()
    inv = [{"table": t, "name": n, "type": {"f": "FK", "u": "UNIQUE", "p": "PK", "c": "CHECK"}.get(ty, ty), "def": d}
           for t, n, ty, d in rows]
    print("create_all-created constraints on the new tables:")
    for x in inv:
        print(f"    {x['table']:32s} {x['type']:6s} {x['name']}  {x['def']}")
    fk = next((x["name"] for x in inv if x["type"] == "FK" and "return_item_id" in x["def"]), None)
    if fk:
        exe(f'ALTER TABLE return_item_lot_allocations DROP CONSTRAINT "{fk}"')
        r = ready()
        rc, _ = initdb()
        repaired = con_exists(fk)
        rec("S-inventory FK on a new table is create_all-only: NOT required by readiness, NOT re-created by initdb "
            "(documented, not a runtime dependency)", r.get("status") == 200 and rc == 0 and not repaired,
            f"readiness={r.get('status')} repaired={repaired}")
        exe(f'ALTER TABLE return_item_lot_allocations ADD CONSTRAINT "{fk}" '
            f"FOREIGN KEY (return_item_id) REFERENCES return_items(id) ON DELETE CASCADE")

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "schema_repair.json"), "w", encoding="utf-8") as f:
        json.dump({"results": RESULTS, "create_all_only_constraints": inv}, f, indent=1, ensure_ascii=False)
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"\nSCHEMA REPAIR PROOF: {len(RESULTS) - len(bad)}/{len(RESULTS)} OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
