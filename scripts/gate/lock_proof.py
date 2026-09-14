# -*- coding: utf-8 -*-
"""PRODUCTION DEPLOY GATE 89f647a — DDL LOCK PROOF on the ephemeral production clone.

  install    `ddl_command_end` event trigger (schema gate_audit — outside public/cash, so the
             fingerprints ignore it) that records for EVERY DDL: command tag, statement, the
             effective lock_timeout, and the relation locks the issuing backend holds at that
             moment (relation locks are held to transaction end). Self-tested on install.
  analyze    the audited FIRST target boot (the real migration): lock modes + lock_timeout of
             every DDL on tables that existed in production before the deploy.
  scenarios  behaviour under concurrent sessions (the parts an audit cannot show):
    L1  CHECK definition probe on drifted column types while another session READS the live
        table: boot completes without waiting, the live table only ever gets ACCESS SHARE from
        the probe, no ACCESS EXCLUSIVE is requested, the constraint is not recreated
    L2  wrong CHECK on products while an in-flight WRITE holds ROW EXCLUSIVE: each recreate
        attempt waits at most lock_timeout=1s, gives up inside the 30s budget, boot continues;
        concurrent readers/writers stall at most ~1s; after the writer ends it is recreated
    L3  ix_sale_items_sale_id CONCURRENTLY while a write transaction is open: the build holds
        SHARE UPDATE EXCLUSIVE only and a NEW writer still gets ROW EXCLUSIVE; negative control:
        a plain CREATE INDEX makes the same new writer time out
    L3b CONCURRENTLY blocked past its 10s lock_timeout: never fatal, next boot rebuilds it
    L4  FK ADD NOT VALID while a write transaction holds the parent: bounded retries inside the
        budget, boot continues, readers never wait; after release added + validated
Refuses to run against anything but a local database.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

import psycopg

URL = os.environ["CLONE_DATABASE_URL"]
if "@localhost" not in URL and "@127.0.0.1" not in URL:
    raise SystemExit("REFUSED: clone database must be local")
ROOT = os.getcwd()
SERVER = os.path.join(ROOT, "apps", "server")
OUT = os.environ.get("GATE_OUT", "gate-out")
ENV = dict(os.environ, DATABASE_URL=URL, APP_ENV="production", RAILWAY_ENVIRONMENT_NAME="production")
STRONG = {"ShareLock", "ShareRowExclusiveLock", "ExclusiveLock", "AccessExclusiveLock"}   # block writers
RESULTS = []

AUDIT_SQL = r"""
CREATE SCHEMA gate_audit;
CREATE TABLE gate_audit.ddl (id bigserial PRIMARY KEY, at timestamptz DEFAULT clock_timestamp(),
                             tag text, query text, lock_timeout text, locks jsonb);
CREATE FUNCTION gate_audit.record() RETURNS event_trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO gate_audit.ddl (tag, query, lock_timeout, locks)
  SELECT tg_tag, current_query(), current_setting('lock_timeout'),
         coalesce(jsonb_agg(jsonb_build_object('rel', n.nspname || '.' || c.relname, 'kind', c.relkind,
                                               'mode', l.mode, 'granted', l.granted)
                            ORDER BY n.nspname, c.relname, l.mode), '[]'::jsonb)
  FROM pg_locks l JOIN pg_class c ON c.oid = l.relation JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE l.pid = pg_backend_pid() AND l.locktype = 'relation'
    AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'gate_audit', 'pg_toast');
END $$;
CREATE EVENT TRIGGER gate_audit_ddl_end ON ddl_command_end EXECUTE FUNCTION gate_audit.record();
"""


def rec(name, ok, note=""):
    RESULTS.append({"step": name, "ok": bool(ok), "note": note if isinstance(note, (dict, list)) else str(note)[:1500]})
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {json.dumps(note, ensure_ascii=False, default=str)[:700]}" if note not in ("", None) else ""), flush=True)


def exe(sql, params=None):
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(sql, params)


def scalar(sql, params=None):
    with psycopg.connect(URL) as c:
        r = c.execute(sql, params).fetchone()
        c.rollback()
    return r[0] if r else None


def run_py(code, timeout=300):
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-c", code], cwd=SERVER, env=ENV, capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or ""), time.monotonic() - t0


def initdb(timeout=900):
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SERVER, env=ENV, capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or ""), time.monotonic() - t0


READY = r'''
import json
from fastapi.testclient import TestClient
from app.main import app
from app.core import required_schema as rs
from app.db.session import engine
with TestClient(app) as c:
    r = c.get('/api/v1/health/ready')
print('READY_JSON=' + json.dumps({"status": r.status_code, "checks": r.json().get("checks"), "soft": rs.soft_missing(engine)}))
'''


def ready():
    rc, out, _ = run_py(READY)
    for ln in out.splitlines():
        if ln.startswith("READY_JSON="):
            return json.loads(ln[len("READY_JSON="):])
    return {"status": None, "error": out[-600:]}


def audit_mark():
    return int(scalar("SELECT coalesce(max(id), 0) FROM gate_audit.ddl"))


def audit_rows(after_id=0):
    with psycopg.connect(URL) as c:
        rows = c.execute("SELECT id, tag, query, lock_timeout, locks FROM gate_audit.ddl WHERE id > %s ORDER BY id",
                         (after_id,)).fetchall()
        c.rollback()
    return [{"id": r[0], "tag": r[1], "query": " ".join((r[2] or "").split()), "lock_timeout": r[3],
             "locks": r[4] or []} for r in rows]


def con_state(table, name):
    with psycopg.connect(URL) as c:
        r = c.execute("SELECT c.oid::bigint, pg_get_expr(c.conbin, c.conrelid) FROM pg_constraint c "
                      "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = %s AND c.conname = %s",
                      (table, name)).fetchone()
        c.rollback()
    return (r[0], r[1]) if r else (None, None)


def fk_names(child, col):
    with psycopg.connect(URL) as c:
        rows = c.execute(
            "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE c.contype = 'f' AND t.relname = %s AND array_length(c.conkey, 1) = 1 "
            "AND (SELECT a.attname FROM pg_attribute a WHERE a.attrelid = c.conrelid AND a.attnum = c.conkey[1]) = %s",
            (child, col)).fetchall()
        c.rollback()
    return [r[0] for r in rows]


def index_state(name):
    v = scalar("SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
               "WHERE c.relname = %s", (name,))
    return "absent" if v is None else ("valid" if v else "invalid")


class Holder:
    """An open transaction holding a table lock (a simulated in-flight read or write)."""

    def __init__(self, sql):
        self.c = psycopg.connect(URL)
        self.c.execute(sql)
        self.pid = self.c.info.backend_pid

    def release(self):
        try:
            self.c.rollback()
        finally:
            self.c.close()


class Sampler(threading.Thread):
    """Repeatedly reads (SELECT) or writes (takes ROW EXCLUSIVE) a table and records latency."""

    def __init__(self, table, write):
        super().__init__(daemon=True)
        self.table, self.write = table, write
        self.stop = threading.Event()
        self.lat, self.errors = [], []

    def run(self):
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute("SET lock_timeout = '60s'")
            while not self.stop.is_set():
                t0 = time.monotonic()
                try:
                    if self.write:
                        with c.transaction():
                            c.execute(f"LOCK TABLE {self.table} IN ROW EXCLUSIVE MODE")
                    else:
                        c.execute(f"SELECT 1 FROM {self.table} LIMIT 1").fetchall()
                except Exception as e:  # noqa: BLE001
                    self.errors.append(type(e).__name__)
                self.lat.append(time.monotonic() - t0)
                time.sleep(0.05)

    def summary(self):
        return {"n": len(self.lat), "max_s": round(max(self.lat), 3) if self.lat else None,
                "over_1_5s": sum(1 for x in self.lat if x > 1.5), "errors": self.errors[:5]}


def try_writer(table, lock_timeout):
    with psycopg.connect(URL) as c:
        try:
            c.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
            c.execute(f"LOCK TABLE {table} IN ROW EXCLUSIVE MODE")
            c.rollback()
            return True
        except psycopg.errors.LockNotAvailable:
            c.rollback()
            return False


# ══ install ════════════════════════════════════════════════════════════════════
def install():
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("DROP EVENT TRIGGER IF EXISTS gate_audit_ddl_end")
        c.execute("DROP SCHEMA IF EXISTS gate_audit CASCADE")
        c.execute(AUDIT_SQL)
        c.execute("CREATE TEMP TABLE gate_selftest (x int)")
        n = c.execute("SELECT count(*) FROM gate_audit.ddl WHERE query LIKE 'CREATE TEMP TABLE gate_selftest%'").fetchone()[0]
        c.execute("DROP TABLE gate_selftest")
        c.execute("DELETE FROM gate_audit.ddl")
    print(f"[lock-audit] event trigger installed; self-test rows={n}")
    return 0 if n == 1 else 1


# ══ analyze (the audited migration) ════════════════════════════════════════════
def analyze():
    pre = json.load(open(os.path.join(OUT, "clone_pre_initdb.json"), encoding="utf-8"))
    live = set(pre["tables"])
    # Only the FIRST target boot is the migration; later boots are recorded separately.
    mark_file = os.path.join(OUT, "audit_mark_boot1.txt")
    boot1_last = int(open(mark_file).read().strip()) if os.path.exists(mark_file) else None
    all_rows = audit_rows()
    rows = [r for r in all_rows if boot1_last is None or r["id"] <= boot1_last]
    later = [r for r in all_rows if boot1_last is not None and r["id"] > boot1_last]
    report = []
    for r in rows:
        tl = sorted({(x["rel"], x["mode"]) for x in r["locks"] if x.get("kind") in ("r", "p") and x["rel"] in live})
        report.append({"id": r["id"], "tag": r["tag"], "stmt": r["query"][:240], "lock_timeout": r["lock_timeout"],
                       "live_table_locks": [f"{a}:{b}" for a, b in tl],
                       "blocks_writers_on_live": sorted({a for a, b in tl if b in STRONG}),
                       "access_exclusive_on_live": sorted({a for a, b in tl if b == "AccessExclusiveLock"})})

    def find(pat):
        return [x for x in report if re.search(pat, x["stmt"])]

    rec("A0 the audit captured the migration's DDL", len(report) > 0, f"{len(report)} DDL statements")
    fk_add = find(r'^ALTER TABLE "stock_batches" ADD FOREIGN KEY')
    ok = len(fk_add) == 3
    for x in fk_add:
        parent = re.search(r'REFERENCES "(\w+)"', x["stmt"]).group(1)
        ok = ok and x["lock_timeout"] == "5s" and "NOT VALID" in x["stmt"] and not x["access_exclusive_on_live"] \
            and "public.stock_batches:ShareRowExclusiveLock" in x["live_table_locks"] \
            and f"public.{parent}:ShareRowExclusiveLock" in x["live_table_locks"]
    rec("A1 FK ADD ... NOT VALID: exactly the 3 production-missing stock_batches FKs, lock_timeout 5s, "
        "SHARE ROW EXCLUSIVE on child and parent, never ACCESS EXCLUSIVE", ok, fk_add)
    fk_val = find(r'^ALTER TABLE "stock_batches" VALIDATE CONSTRAINT')
    rec("A2 FK VALIDATE: 3 statements, lock_timeout 5s, SHARE UPDATE EXCLUSIVE on the child, "
        "no write-blocking lock on any live table",
        len(fk_val) == 3 and all(x["lock_timeout"] == "5s" and "public.stock_batches:ShareUpdateExclusiveLock" in x["live_table_locks"]
                                 and not x["blocks_writers_on_live"] for x in fk_val), fk_val)
    ck_add = find(r'^ALTER TABLE "lot_shortfalls" ADD CONSTRAINT ck_lot_shortfall_resolved_le_qty CHECK')
    ck_val = find(r'^ALTER TABLE "lot_shortfalls" VALIDATE CONSTRAINT ck_lot_shortfall_resolved_le_qty')
    rec("A3 new CHECK on the existing lot_shortfalls: ADD ... NOT VALID (lock_timeout 5s), VALIDATE "
        "(lock_timeout 5s, SHARE UPDATE EXCLUSIVE only)",
        len(ck_add) == 1 and ck_add[0]["lock_timeout"] == "5s" and "NOT VALID" in ck_add[0]["stmt"]
        and len(ck_val) == 1 and ck_val[0]["lock_timeout"] == "5s" and not ck_val[0]["blocks_writers_on_live"],
        ck_add + ck_val)
    rebuild = find(r"DROP CONSTRAINT ck_\w+, ADD CONSTRAINT ck_") + find(r"ck_4a1_probe_tmp")
    rec("A4 production shape: NO CHECK definition probe and NO CHECK rebuild during the migration",
        not rebuild, rebuild)
    cic = find(r"^CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sale_items_sale_id ON public\.sale_items")
    rec("A5 ix_sale_items_sale_id statement is CREATE INDEX CONCURRENTLY (only legal outside a transaction "
        "block) with lock_timeout 10s — statement text and timeout only: the build's session lock is gone "
        "before the audit fires, L3 proves the locking",
        len(cic) == 1 and cic[0]["lock_timeout"] == "10s" and not cic[0]["blocks_writers_on_live"], cic)
    legacy = find(r'DROP CONSTRAINT "return_item_lot_allocations_return_item_id_stock_batch_id_key"|DROP INDEX IF EXISTS public\."ux_ret_alloc"')
    line_ix = find(r"CREATE UNIQUE INDEX IF NOT EXISTS ux_ret_alloc_line")
    rec("A6 legacy (return_item_id, stock_batch_id) uniqueness dropped only AFTER ux_ret_alloc_line was "
        "built, with lock_timeout 5s",
        len(legacy) == 2 and bool(line_ix) and min(x["id"] for x in legacy) > min(x["id"] for x in line_ix)
        and all(x["lock_timeout"] == "5s" for x in legacy), legacy + line_ix[:1])
    full = {r["id"]: r["query"] for r in rows}
    second_stmts = {r["query"] for r in later}
    new_expected = (
        r"^CREATE TABLE (lot_shortfall_resolution_requests|lot_shortfall_resolutions|"
        r"return_item_shortfall_allocations|return_item_resolution_allocations) \(",
        r"^CREATE (UNIQUE )?INDEX (ux_lsr_request_client|ux_lsr_request_lot|ux_risa_item_shortfall|"
        r"ux_rira_item_resolution|ix_lsr_company_resolved|ix_lsr_shortfall|ix_lsr_sale_item|ix_rira_return|"
        r"ix_rira_resolution|ix_risa_shortfall|ix_risa_created_batch) ON (lot_shortfall_resolution_requests|"
        r"lot_shortfall_resolutions|return_item_shortfall_allocations|return_item_resolution_allocations) ",
        r"^ALTER TABLE sale_items ADD COLUMN provisional_qty NUMERIC\(14,3\)$")
    unbounded, unexpected = [], []
    for x in report:
        if not (x["blocks_writers_on_live"] and x["lock_timeout"] in ("0", "0ms")):
            continue
        q = full[x["id"]]
        kind = ("every-boot (also issued by the second boot)" if q in second_stmts
                else "new in this deploy" if any(re.search(p, q) for p in new_expected) else "UNEXPECTED")
        item = {"kind": kind, "stmt": q[:170], "write_blocking_on": x["blocks_writers_on_live"]}
        unbounded.append(item)
        if kind == "UNEXPECTED":
            unexpected.append(item)
    rec("A7 write-blocking DDL on pre-existing tables WITHOUT lock_timeout is EXACTLY: the four new tables' "
        "create_all statements, ALTER TABLE sale_items ADD COLUMN provisional_qty, and the pre-existing "
        "every-boot IF NOT EXISTS set — nothing else (risk bounded by the pre-deploy no-long-transaction "
        "check; L5 shows the wait)",
        boot1_last is not None and not unexpected,
        {"unexpected": unexpected,
         "new_in_this_deploy": [u["stmt"][:110] for u in unbounded if u["kind"] == "new in this deploy"],
         "every_boot_count": sum(1 for u in unbounded if u["kind"].startswith("every-boot"))})
    second = [{"stmt": r["query"][:120], "lock_timeout": r["lock_timeout"],
               "write_blocking_on_live": sorted({x["rel"] for x in r["locks"] if x.get("kind") in ("r", "p")
                                                 and x["rel"] in live and x["mode"] in STRONG})} for r in later]
    changing = [x for x in second if not re.search(r"IF (NOT )?EXISTS", x["stmt"])]
    rec("A8 second boot: every DDL statement it issues is an IF [NOT] EXISTS no-op (nothing added, "
        "altered, validated or rebuilt)", boot1_last is not None and not changing,
        {"second_boot_statements": len(second), "non_idempotent": changing,
         "every_boot_write_blocking_without_timeout": sum(1 for x in second if x["write_blocking_on_live"]
                                                         and x["lock_timeout"] in ("0", "0ms"))})
    with open(os.path.join(OUT, "lock_audit_migration.json"), "w", encoding="utf-8") as f:
        json.dump({"results": RESULTS, "ddl": report, "unbounded": unbounded, "second_boot_ddl": second},
                  f, indent=1, ensure_ascii=False)
    with open(os.path.join(OUT, "lock_audit_mark.txt"), "w") as f:
        f.write(str(audit_mark()))
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"\nLOCK AUDIT (migration): {len(RESULTS) - len(bad)}/{len(RESULTS)} OK")
    return 1 if bad else 0


# ══ scenarios ══════════════════════════════════════════════════════════════════
def l1_probe_drifted_types():
    typ = scalar("SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                 "WHERE a.attrelid = 'public.lot_shortfalls'::regclass AND a.attname = 'resolved_qty'")
    dflt = scalar("SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d JOIN pg_attribute a "
                  "ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
                  "WHERE d.adrelid = 'public.lot_shortfalls'::regclass AND a.attname = 'resolved_qty'")
    exe("ALTER TABLE lot_shortfalls ALTER COLUMN resolved_qty DROP DEFAULT, "
        "ALTER COLUMN resolved_qty TYPE integer USING resolved_qty::integer")
    oid, expr = con_state("lot_shortfalls", "ck_lot_shortfall_resolved_le_qty")
    rec("L1-setup drifted column type: Postgres renders a cast, so the definition probe path runs",
        "::numeric" in (expr or ""), expr)
    mark = audit_mark()
    h = Holder("LOCK TABLE lot_shortfalls IN ACCESS SHARE MODE")
    try:
        rc, out, secs = initdb()
    finally:
        h.release()
    rows = audit_rows(mark)
    probe_rows = [x for x in rows if x["query"].startswith('CREATE TEMP TABLE ck_4a1_probe_tmp (LIKE public."lot_shortfalls")')]
    live_modes = sorted({x["mode"] for p in probe_rows for x in p["locks"] if x["rel"] == "public.lot_shortfalls"})
    ae = [x["query"][:120] for x in rows
          if any(l["rel"] == "public.lot_shortfalls" and l["mode"] == "AccessExclusiveLock" for l in x["locks"])]
    rec("L1 the probe ran on a TEMP copy: the live lot_shortfalls got ACCESS SHARE only from it",
        len(probe_rows) >= 1 and live_modes == ["AccessShareLock"], {"probe_rows": len(probe_rows), "modes": live_modes})
    rec("L1 full boot while another session READS the live table: exit 0, no lock wait, no ACCESS "
        "EXCLUSIVE ever taken on lot_shortfalls",
        rc == 0 and "qulf byudjeti tugadi" not in out and secs < 25 and not ae,
        {"rc": rc, "secs": round(secs, 1), "access_exclusive_rows": ae})
    oid2, _ = con_state("lot_shortfalls", "ck_lot_shortfall_resolved_le_qty")
    rd = ready()
    rec("L1 constraint NOT recreated (same oid), reason logged, probe table gone, readiness stays red",
        oid2 == oid and "kutilgan ifoda ham shu sxemada tanilmadi" in out
        and scalar("SELECT count(*) FROM pg_class WHERE relname = 'ck_4a1_probe_tmp'") == 0 and rd.get("status") == 503,
        {"oid": [oid, oid2], "ready": rd.get("status"), "soft": rd.get("soft")})
    exe(f"ALTER TABLE lot_shortfalls ALTER COLUMN resolved_qty TYPE {typ} USING resolved_qty::numeric"
        + (f", ALTER COLUMN resolved_qty SET DEFAULT {dflt}" if dflt else ""))
    # The integer detour rewrote the partial index predicate with a cast ((resolved_qty)::numeric)
    # and changing the type back keeps that text. Drop it so the boot recreates it from initdb's DDL.
    exe("DROP INDEX IF EXISTS ix_lot_shortfall_open")
    rc, out, _ = initdb()
    rd = ready()
    rec("L1-restore column type restored; the boot heals whatever the cast left; readiness 200",
        rc == 0 and rd.get("status") == 200, {"rc": rc, "ready": rd.get("status"), "soft": rd.get("soft"),
                                               "lines": [ln for ln in out.splitlines() if "ck_lot_shortfall" in ln]})


def l2_recreate_under_writer():
    exe('ALTER TABLE "products" DROP CONSTRAINT ck_track_expiry_implies_lots, '
        "ADD CONSTRAINT ck_track_expiry_implies_lots CHECK (NOT (track_expiry OR track_lots))")
    oid, _ = con_state("products", "ck_track_expiry_implies_lots")
    h = Holder("LOCK TABLE products IN ROW EXCLUSIVE MODE")
    rd_s, wr_s = Sampler("products", write=False), Sampler("products", write=True)
    rd_s.start()
    wr_s.start()
    time.sleep(0.5)
    try:
        rc, out, secs = run_py("from app import initdb as I; I._ensure_lot_checks()", timeout=300)
    finally:
        rd_s.stop.set()
        wr_s.stop.set()
        rd_s.join(30)
        wr_s.join(30)
        h.release()
    oid2, _ = con_state("products", "ck_track_expiry_implies_lots")
    rec("L2 recreate while a writer holds products: gives up inside the 30s budget, exit 0, constraint "
        "untouched",
        rc == 0 and "ck_track_expiry_implies_lots — o'tkazib yuborildi" in out and 20 <= secs <= 90 and oid2 == oid,
        {"rc": rc, "secs": round(secs, 1), "lines": [ln for ln in out.splitlines() if "ck_track" in ln][:3]})
    rec("L2 stall bounded by lock_timeout=1s: concurrent readers and writers of products never waited "
        "more than 1.5s, never failed, and DID wait >= 0.5s (real contention was measured)",
        rd_s.lat and wr_s.lat and 0.5 <= max(rd_s.lat) <= 1.5 and max(wr_s.lat) <= 1.5
        and not rd_s.errors and not wr_s.errors,
        {"reader": rd_s.summary(), "writer": wr_s.summary()})
    rd = ready()
    rec("L2 readiness red while the wrong definition remains", rd.get("status") == 503
        and "cheklov ta'rifi noto'g'ri: ck_track_expiry_implies_lots (products)" in (rd.get("soft") or []), rd)
    mark = audit_mark()
    rc, out, secs = run_py("from app import initdb as I; I._ensure_lot_checks()", timeout=300)
    rows = audit_rows(mark)
    probe = [x for x in rows if x["query"].startswith('CREATE TEMP TABLE ck_4a1_probe_tmp (LIKE public."products")')]
    recr = [x for x in rows if x["query"].startswith('ALTER TABLE "products" DROP CONSTRAINT ck_track_expiry_implies_lots, ADD CONSTRAINT')]
    val = [x for x in rows if x["query"].startswith('ALTER TABLE "products" VALIDATE CONSTRAINT ck_track_expiry_implies_lots')]
    rec("L2-recover writer gone: probe (ACCESS SHARE on products) -> recreate in ONE ALTER with lock_timeout "
        "1s -> VALIDATE with lock_timeout 5s under SHARE UPDATE EXCLUSIVE -> readiness 200",
        rc == 0 and len(probe) == 1 and sorted({l["mode"] for l in probe[0]["locks"] if l["rel"] == "public.products"}) == ["AccessShareLock"]
        and len(recr) == 1 and recr[0]["lock_timeout"] == "1s"
        and len(val) == 1 and val[0]["lock_timeout"] == "5s"
        and sorted({l["mode"] for l in val[0]["locks"] if l["rel"] == "public.products"}) == ["ShareUpdateExclusiveLock"]
        and ready().get("status") == 200,
        {"rc": rc, "secs": round(secs, 1), "probe": probe[:1], "recreate": [(x["lock_timeout"], x["query"][:90]) for x in recr],
         "validate": [(x["lock_timeout"], sorted({l["mode"] for l in x["locks"] if l["rel"] == "public.products"})) for x in val]})


def l3_concurrent_index():
    exe("DROP INDEX IF EXISTS ix_sale_items_sale_id")
    h = Holder("LOCK TABLE sale_items IN ROW EXCLUSIVE MODE")
    proc = subprocess.Popen([sys.executable, "-c", "from app import initdb as I; I._ensure_sale_items_sale_id_index()"],
                            cwd=SERVER, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    seen, got_sue, writer_ok = set(), False, None
    try:
        with psycopg.connect(URL, autocommit=True) as mon:
            t_end = time.monotonic() + 8
            while time.monotonic() < t_end:
                rows = mon.execute("SELECT mode, granted FROM pg_locks WHERE relation = 'public.sale_items'::regclass "
                                   "AND pid NOT IN (%s, pg_backend_pid())", (h.pid,)).fetchall()
                seen |= {(m, g) for m, g in rows}
                if any(m == "ShareUpdateExclusiveLock" and g for m, g in rows):
                    got_sue = True
                    break
                time.sleep(0.05)
            writer_ok = try_writer("sale_items", "500ms") if got_sue else None
            rows = mon.execute("SELECT mode, granted FROM pg_locks WHERE relation = 'public.sale_items'::regclass "
                               "AND pid NOT IN (%s, pg_backend_pid())", (h.pid,)).fetchall()
            seen |= {(m, g) for m, g in rows}
    finally:
        h.release()
    out = proc.communicate(timeout=180)[0]
    modes = sorted({m for m, _ in seen})
    rec("L3 CONCURRENTLY build waits for the open write transaction holding SHARE UPDATE EXCLUSIVE only",
        got_sue and not (set(modes) & STRONG), {"modes_seen": modes})
    rec("L3 a NEW writer takes ROW EXCLUSIVE on sale_items within 500ms DURING the build", writer_ok is True,
        {"writer_ok": writer_ok})
    rec("L3 build completes once the write transaction ends; index VALID",
        proc.returncode == 0 and "ix_sale_items_sale_id CONCURRENTLY qurildi" in out and index_state("ix_sale_items_sale_id") == "valid",
        out.strip()[-300:])

    # negative control — the same probe must detect a BLOCKING build
    h = Holder("LOCK TABLE sale_items IN ROW EXCLUSIVE MODE")
    res = {}

    def plain():
        with psycopg.connect(URL, autocommit=True) as c:
            try:
                c.execute("SET lock_timeout = '20s'")
                c.execute("CREATE INDEX gate_plain_ix ON sale_items (sale_id)")
                res["ok"] = True
            except Exception as e:  # noqa: BLE001
                res["err"] = type(e).__name__
    t = threading.Thread(target=plain, daemon=True)
    t.start()
    queued = False
    try:
        with psycopg.connect(URL, autocommit=True) as mon:
            t_end = time.monotonic() + 8
            while time.monotonic() < t_end and not queued:
                queued = bool(mon.execute("SELECT count(*) FROM pg_locks WHERE relation = 'public.sale_items'::regclass "
                                          "AND mode = 'ShareLock' AND NOT granted").fetchone()[0])
                time.sleep(0.05)
        blocked = (try_writer("sale_items", "500ms") is False) if queued else None
    finally:
        h.release()
    t.join(60)
    exe("DROP INDEX IF EXISTS gate_plain_ix")
    rec("L3-negative control: a plain CREATE INDEX queues SHARE and the same new writer is BLOCKED "
        "(the check can see a blocking build)", queued and blocked is True and res.get("ok") is True,
        {"queued": queued, "blocked": blocked, "plain": res})

    # L3b — blocked past lock_timeout=10s
    exe("DROP INDEX IF EXISTS ix_sale_items_sale_id")
    h = Holder("LOCK TABLE sale_items IN ROW EXCLUSIVE MODE")
    try:
        rc, out, secs = run_py("from app import initdb as I; I._ensure_sale_items_sale_id_index()", timeout=180)
    finally:
        h.release()
    st = index_state("ix_sale_items_sale_id")
    rec("L3b CONCURRENTLY blocked past lock_timeout=10s: gives up (exit 0, never fatal), leaves it invalid/absent",
        rc == 0 and 8 <= secs <= 60 and "[perf] ix_sale_items_sale_id" in out and st in ("invalid", "absent"),
        {"rc": rc, "secs": round(secs, 1), "state": st, "out": out.strip()[-240:]})
    rc, out, _ = run_py("from app import initdb as I; I._ensure_sale_items_sale_id_index()", timeout=180)
    rec("L3b the next boot drops the INVALID leftover and rebuilds it CONCURRENTLY -> VALID",
        rc == 0 and "CONCURRENTLY qurildi" in out and index_state("ix_sale_items_sale_id") == "valid"
        and (st == "absent" or "YAROQSIZ" in out), out.strip()[-300:])


def l4_fk_under_writer():
    names = fk_names("stock_batches", "supplier_id")
    for n in names:
        exe(f'ALTER TABLE stock_batches DROP CONSTRAINT "{n}"')
    h = Holder("LOCK TABLE suppliers IN ROW EXCLUSIVE MODE")
    rd_s, wr_s = Sampler("suppliers", write=False), Sampler("suppliers", write=True)
    sb_s = Sampler("stock_batches", write=True)   # the child is locked FIRST (alphabetical) and held
    rd_s.start()
    wr_s.start()
    sb_s.start()
    time.sleep(0.5)
    try:
        rc, out, secs = run_py("from app import initdb as I; I._ensure_foreign_keys()", timeout=300)
    finally:
        rd_s.stop.set()
        wr_s.stop.set()
        sb_s.stop.set()
        rd_s.join(30)
        wr_s.join(30)
        sb_s.join(30)
        h.release()
    rec("L4 FK add while a write transaction holds the parent: bounded retries inside the budget, exit 0, "
        "FK still missing, boot continues",
        rc == 0 and "stock_batches(supplier_id) -> suppliers(id): tuzatilmadi" in out and 20 <= secs <= 90
        and not fk_names("stock_batches", "supplier_id"),
        {"rc": rc, "secs": round(secs, 1), "lines": [ln for ln in out.splitlines() if "supplier_id" in ln][:3]})
    rec("L4 readers of the parent never waited (SHARE ROW EXCLUSIVE does not conflict with ACCESS SHARE, "
        "max <= 0.5s); writers of the parent AND of stock_batches waited at most lock_timeout=5s; no errors",
        rd_s.lat and wr_s.lat and sb_s.lat and max(rd_s.lat) <= 0.5 and max(wr_s.lat) <= 6.0
        and max(sb_s.lat) <= 6.0 and not rd_s.errors and not wr_s.errors and not sb_s.errors,
        {"reader_suppliers": rd_s.summary(), "writer_suppliers": wr_s.summary(),
         "writer_stock_batches": sb_s.summary()})
    rd = ready()
    rec("L4 readiness red while the FK is missing", rd.get("status") == 503, {"soft": rd.get("soft")})
    mark = audit_mark()
    rc, out, _ = run_py("from app import initdb as I; I._ensure_foreign_keys()", timeout=300)
    rows = audit_rows(mark)
    add = [x for x in rows if x["query"].startswith('ALTER TABLE "stock_batches" ADD FOREIGN KEY ("supplier_id")')]
    val = [x for x in rows if x["query"].startswith('ALTER TABLE "stock_batches" VALIDATE CONSTRAINT')]
    rec("L4-recover writer gone: ADD NOT VALID (5s, SHARE ROW EXCLUSIVE) -> VALIDATE (5s, SHARE UPDATE "
        "EXCLUSIVE) -> readiness 200",
        rc == 0 and "suppliers(id): NOT VALID qo'shildi" in out and "suppliers(id): tasdiqlandi" in out
        and len(add) == 1 and add[0]["lock_timeout"] == "5s"
        and "ShareRowExclusiveLock" in {l["mode"] for l in add[0]["locks"] if l["rel"] == "public.suppliers"}
        and len(val) == 1 and val[0]["lock_timeout"] == "5s"
        and {l["mode"] for l in val[0]["locks"] if l["rel"] == "public.stock_batches"} & {"ShareUpdateExclusiveLock"}
        and ready().get("status") == 200,
        {"add": [(x["lock_timeout"], x["query"][:100]) for x in add], "validate": [(x["lock_timeout"], x["query"][:100]) for x in val]})


def l5_add_column_waits():
    exe("ALTER TABLE sale_items DROP COLUMN provisional_qty")
    h = Holder("LOCK TABLE sale_items IN ACCESS SHARE MODE")
    env = dict(ENV, PGOPTIONS="-c lock_timeout=3000")
    t0 = time.monotonic()
    try:
        p = subprocess.run([sys.executable, "-c", "from app import initdb as I; I._ensure_columns()"], cwd=SERVER,
                           env=env, capture_output=True, text=True, timeout=180)
    finally:
        secs = time.monotonic() - t0
        h.release()
    out = (p.stdout or "") + (p.stderr or "")
    rec("L5 RISK DOCUMENTED: ALTER TABLE sale_items ADD COLUMN sets no lock_timeout of its own — while a "
        "reader holds ACCESS SHARE it WAITS (here cut only by an injected lock_timeout=3s; without it, as long "
        "as the reader lives). Production precondition: no long transaction on sale_items at deploy time",
        p.returncode != 0 and secs >= 2.5 and "lock timeout" in out.lower() and "provisional_qty" in out,
        {"rc": p.returncode, "secs": round(secs, 1), "tail": out.strip()[-260:]})
    rc, out, _ = initdb()
    rd = ready()
    rec("L5-restore a normal boot re-adds the column -> readiness 200",
        rc == 0 and "sale_items.provisional_qty qo'shildi" in out and rd.get("status") == 200,
        {"rc": rc, "ready": rd.get("status")})


def scenarios():
    for fn in (l1_probe_drifted_types, l2_recreate_under_writer, l3_concurrent_index, l4_fk_under_writer,
               l5_add_column_waits):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            rec(f"{fn.__name__} aborted", False, traceback.format_exc()[-1500:])
    rc, out, _ = initdb()
    rd = ready()
    rec("L-final boot after all lock scenarios: exit 0, readiness 200, lot_schema_integrity true",
        rc == 0 and rd.get("status") == 200 and (rd.get("checks") or {}).get("lot_schema_integrity") is True,
        {"rc": rc, "ready": rd})
    with open(os.path.join(OUT, "lock_proof_scenarios.json"), "w", encoding="utf-8") as f:
        json.dump({"results": RESULTS}, f, indent=1, ensure_ascii=False, default=str)
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"\nLOCK SCENARIOS: {len(RESULTS) - len(bad)}/{len(RESULTS)} OK")
    for b in bad:
        print("  FAILED:", b["step"])
    return 1 if bad else 0


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"install": install, "analyze": analyze, "scenarios": scenarios}.get(cmd, lambda: sys.exit(__doc__))())
