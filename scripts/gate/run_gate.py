# -*- coding: utf-8 -*-
"""PRODUCTION DEPLOY GATE 89f647a — orchestrator. The SAME code runs in CI (restored production
backup on postgres:18) and in the local dry run (throwaway pgserver). Refuses non-local databases.

  G1  fingerprint of the production-shaped clone BEFORE the target boot
  G2  DDL lock audit installed (event trigger, schema gate_audit)
  G3  target boot 1/2: initdb in production env — exact log expectations, NO unexpected CHECK rebuild
  G4  target boot 2/2: seed skips demo data in production
  G5  migration changed ZERO business rows; exact schema additions (check_shape.py)
  G6  second boot is a no-op (strict schema + rows)
  G7  lock audit of the real migration (lock_proof.py analyze)
  G8  production-mode server: /health build commit, /health/ready 200, lot_schema_integrity, no leak
  G9  migration / readiness / CHECK definition / break-recover / rollback proof
  G10 lock behaviour under concurrent sessions (lock_proof.py scenarios)
  G11 after all proofs the clone is back to the migrated state (rows + strict schema)
  G12 Phase 4A lifecycle on a TEMPLATE copy (synthetic tenant, staging env), Fayzan untouched
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

import psycopg

URL = os.environ["CLONE_DATABASE_URL"]
if "@localhost" not in URL and "@127.0.0.1" not in URL:
    raise SystemExit("REFUSED: clone database must be local")
ROOT = os.getcwd()
SERVER = os.path.join(ROOT, "apps", "server")
OUT = os.environ.get("GATE_OUT", "gate-out")
TARGET = os.environ["TARGET_SHA"]
PY = sys.executable
PORT = int(os.environ.get("GATE_PORT", "18765"))
LEGACY = ("public.ux_ret_alloc,public.return_item_lot_allocations_return_item_id_stock_batch_id_key,"
          "return_item_lot_allocations.return_item_lot_allocations_return_item_id_stock_batch_id_key")
STEPS = []
PROD = dict(os.environ, DATABASE_URL=URL, APP_ENV="production", RAILWAY_ENVIRONMENT_NAME="production")


def step(name, ok, note=""):
    STEPS.append({"step": name, "ok": bool(ok), "note": note if isinstance(note, (dict, list)) else str(note)[:3000]})
    print(f"\n##### [{'OK  ' if ok else 'FAIL'}] {name}" + (f"\n{json.dumps(note, ensure_ascii=False, default=str)[:2500]}" if note not in ("", None) else ""), flush=True)


def run(args, env=None, cwd=None, timeout=3600, stdout_file=None, log_file=None):
    t0 = time.monotonic()
    if stdout_file:
        with open(stdout_file, "w", encoding="utf-8") as fo:
            p = subprocess.run(args, cwd=cwd or ROOT, env=env or os.environ, stdout=fo, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = p.stderr or ""
    else:
        p = subprocess.run(args, cwd=cwd or ROOT, env=env or os.environ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
    if log_file:
        with open(log_file, "w", encoding="utf-8") as fl:
            fl.write(out)
    print(out[-6000:], flush=True)
    return p.returncode, out, time.monotonic() - t0


def fp(name, columns_from=None):
    args = [PY, os.path.join("scripts", "gate", "fp.py")] + (["--columns-from", columns_from] if columns_from else [])
    rc, err, _ = run(args, env=dict(os.environ, DATABASE_PUBLIC_URL=URL), stdout_file=os.path.join(OUT, name))
    return rc


def compare(a, b, out_name, extra=()):
    return run([PY, os.path.join("scripts", "gate", "compare_fp.py"), a, b, *extra],
               stdout_file=os.path.join(OUT, out_name))[0]


def http(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001
        return None, repr(e)


def make_copy(admin, src_db, copy_db):
    for _ in range(10):
        try:
            with psycopg.connect(admin, autocommit=True) as c:
                c.execute(f'DROP DATABASE IF EXISTS "{copy_db}" WITH (FORCE)')
                c.execute(f'CREATE DATABASE "{copy_db}" TEMPLATE "{src_db}"')
            return True
        except Exception as e:  # noqa: BLE001
            print("template copy retry:", type(e).__name__, str(e).splitlines()[0][:120])
            time.sleep(3)
    return False


def drop_db(admin, name):
    try:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:  # noqa: BLE001
        pass


BOOT1 = ["[migrate] sale_items.provisional_qty qo'shildi",
         "[perf] ix_sale_items_sale_id CONCURRENTLY qurildi (N ms)",
         "[migrate] ck_lot_shortfall_resolved_le_qty qo'shildi",
         "[migrate] ck_lot_shortfall_resolved_le_qty tasdiqlandi",
         "[fk] stock_batches(company_id) -> companies(id): NOT VALID qo'shildi",
         "[fk] stock_batches(company_id) -> companies(id): tasdiqlandi",
         "[fk] stock_batches(purchase_item_id) -> purchase_items(id): NOT VALID qo'shildi",
         "[fk] stock_batches(purchase_item_id) -> purchase_items(id): tasdiqlandi",
         "[fk] stock_batches(supplier_id) -> suppliers(id): NOT VALID qo'shildi",
         "[fk] stock_batches(supplier_id) -> suppliers(id): tasdiqlandi",
         "[migrate] return_item_lot_allocations: eskirgan (return_item_id, stock_batch_id) noyobligi olib tashlandi: "
         "return_item_lot_allocations_return_item_id_stock_batch_id_key, ux_ret_alloc",
         "[cash] sxema: exists",
         "[schema] majburiy V2 obyektlari joyida (109 ustun + 12 indeks; 48 FK — tayyor emas: 0)",
         "[OK] Jadvallar yaratildi"]
BOOT2 = ["[cash] sxema: exists",
         "[schema] majburiy V2 obyektlari joyida (109 ustun + 12 indeks; 48 FK — tayyor emas: 0)",
         "[OK] Jadvallar yaratildi"]


def main():
    os.makedirs(OUT, exist_ok=True)
    o = lambda n: os.path.join(OUT, n)  # noqa: E731

    # G1
    rc = fp("clone_pre_initdb.json")
    pre = json.load(open(o("clone_pre_initdb.json"), encoding="utf-8")) if rc == 0 else {}
    expect = json.loads(os.environ.get("GATE_EXPECT_FAYZAN") or "{}")
    scale_mismatch = {k: [(pre.get("fayzan") or {}).get(k), v] for k, v in expect.items()
                      if (pre.get("fayzan") or {}).get(k) != v}
    step("G1 fingerprint before the target boot: no query error, production scale as expected",
         rc == 0 and bool(pre.get("tables")) and not (pre.get("meta") or {}).get("query_errors") and not scale_mismatch,
         {"server_version": (pre.get("meta") or {}).get("server_version"), "fayzan": pre.get("fayzan"),
          "expected": expect, "scale_mismatch": scale_mismatch, "query_errors": (pre.get("meta") or {}).get("query_errors"),
          "phase4a_tables_before": [t for t in pre.get("tables", {}) if "resolution" in t or "shortfall_allocations" in t]})

    # G1b — report parity on a PRE-migration copy: da47aa8 numbers vs 89f647a numbers, same data
    parts = urlsplit(URL)
    admin = urlunsplit(parts._replace(path="/postgres"))
    rb = os.environ.get("ROLLBACK_SERVER")
    acct_db = "acct_copy"
    acct_url = urlunsplit(parts._replace(path="/" + acct_db))
    if rb and os.path.isdir(rb) and make_copy(admin, parts.path.lstrip("/"), acct_db):
        penv = dict(os.environ, DATABASE_URL=acct_url, APP_ENV="production", RAILWAY_ENVIRONMENT_NAME="production")
        par = os.path.join(ROOT, "scripts", "gate", "report_parity.py")
        r1 = run([PY, par, "seed", o("parity_state.json")], env=penv, cwd=rb, log_file=o("parity_seed.log"))[0]
        r2 = run([PY, par, "capture", o("parity_state.json"), o("parity_before.json")], env=penv, cwd=rb,
                 log_file=o("parity_capture_before.log"))[0] if r1 == 0 else 1
        r3 = run([PY, "-m", "app.initdb"], env=penv, cwd=SERVER, log_file=o("parity_initdb.log"))[0] if r2 == 0 else 1
        r4 = run([PY, par, "capture", o("parity_state.json"), o("parity_after.json")], env=penv, cwd=SERVER,
                 log_file=o("parity_capture_after.log"))[0] if r3 == 0 else 1
        r5, cmpout, _ = run([PY, par, "compare", o("parity_before.json"), o("parity_after.json")],
                            log_file=o("parity_compare.log")) if r4 == 0 else (1, "capture failed", 0)
        step("G1b report parity: on the SAME pre-migration data, da47aa8 and 89f647a return identical report "
             "numbers and labels (synthetic untracked tenant with a purchase, card/QR sales, price overrides and a "
             "restocked return, plus Fayzan) — every field present before is unchanged after the migration",
             r1 == 0 and r2 == 0 and r3 == 0 and r4 == 0 and r5 == 0,
             {"rcs": [r1, r2, r3, r4, r5], "compare": cmpout[-2500:]})
    else:
        step("G1b report parity", False, "ROLLBACK_SERVER missing or the pre-migration copy could not be created")
    drop_db(admin, acct_db)

    # G2
    rc, out, _ = run([PY, os.path.join("scripts", "gate", "lock_proof.py"), "install"], env=dict(os.environ, CLONE_DATABASE_URL=URL, GATE_OUT=OUT))
    step("G2 DDL lock audit installed and self-tested", rc == 0, out.strip()[-200:])

    # G3
    rc, log, secs = run([PY, "-m", "app.initdb"], env=PROD, cwd=SERVER, log_file=o("initdb_1.log"))
    with psycopg.connect(URL) as c:
        boot1_last = c.execute("SELECT coalesce(max(id), 0) FROM gate_audit.ddl").fetchone()[0]
        c.rollback()
    with open(o("audit_mark_boot1.txt"), "w") as f:
        f.write(str(boot1_last))
    lines1 = [re.sub(r"\(\d+ ms\)", "(N ms)", ln.strip()) for ln in log.splitlines() if ln.strip()]
    forbidden = [ln for ln in lines1 if ln not in BOOT1] + (["<duplicate lines>"] if len(lines1) != len(set(lines1)) else [])
    expected = ["ix_sale_items_sale_id CONCURRENTLY qurildi", "sale_items.provisional_qty qo'shildi",
                "ck_lot_shortfall_resolved_le_qty qo'shildi", "ck_lot_shortfall_resolved_le_qty tasdiqlandi",
                "stock_batches(company_id) -> companies(id): NOT VALID qo'shildi",
                "stock_batches(company_id) -> companies(id): tasdiqlandi",
                "stock_batches(purchase_item_id) -> purchase_items(id): tasdiqlandi",
                "stock_batches(supplier_id) -> suppliers(id): tasdiqlandi",
                "noyobligi olib tashlandi", "48 FK — tayyor emas: 0)"]
    missing = [e for e in BOOT1 if e not in lines1] + [e for e in expected if e not in log]
    step("G3 target boot 1/2 (initdb, production env): exit 0 and the log is EXACTLY the expected migration "
         "(column, CONCURRENTLY index, new CHECK, FK repair x3, legacy uniqueness removal, cash exists, "
         "required_schema 48 FK / 0 not ready) — no other line (no skip, no CHECK rebuild, no FATAL)",
         rc == 0 and not forbidden and not missing,
         {"rc": rc, "secs": round(secs, 1), "forbidden_lines": forbidden, "missing_expected": missing,
          "migration_lines": [ln for ln in log.splitlines() if ln.startswith(("[migrate]", "[fk]", "[perf]", "[schema]", "[cash]", "[OK]"))]})

    # G4
    rc, log, _ = run([PY, "-m", "app.seed"], env=PROD, cwd=SERVER, log_file=o("seed.log"))
    step("G4 target boot 2/2 (seed, production env) skips demo data", rc == 0 and "demo seed o'tkazib yuborildi" in log, log.strip()[-300:])

    # G5
    rc1 = fp("clone_post_initdb.json", o("clone_pre_initdb.json"))
    rc2 = compare(o("clone_pre_initdb.json"), o("clone_post_initdb.json"), "compare_migration.json",
                  ["--allow-removed", LEGACY, "--fail-on-writes"])
    rc3, shape, _ = run([PY, os.path.join("scripts", "gate", "check_shape.py"), o("compare_migration.json")])
    step("G5 migration changed ZERO business rows; exact schema additions", rc1 == 0 and rc2 == 0 and rc3 == 0, shape[-2500:])

    # G6
    rc0 = fp("clone_post_initdb_full.json")
    rc, log, _ = run([PY, "-m", "app.initdb"], env=PROD, cwd=SERVER, log_file=o("initdb_2.log"))
    lines2 = [ln.strip() for ln in log.splitlines() if ln.strip()]
    rc1 = fp("clone_post_initdb_2.json", o("clone_post_initdb_full.json"))
    rc2 = compare(o("clone_post_initdb_full.json"), o("clone_post_initdb_2.json"), "compare_second_boot.json",
                  ["--strict-schema", "--strict-identity", "--fail-on-writes"])
    step("G6 second boot is a no-op: the log is exactly the 3 steady-state lines; rows (all columns), full schema "
         "and the PHYSICAL identity (oid/relfilenode) of every table, index and constraint unchanged; no UPDATE/DELETE",
         rc == 0 and lines2 == BOOT2 and rc0 == 0 and rc1 == 0 and rc2 == 0, {"lines": lines2, "compare_rc": rc2})

    # G7
    rc, out, _ = run([PY, os.path.join("scripts", "gate", "lock_proof.py"), "analyze"], env=dict(os.environ, CLONE_DATABASE_URL=URL, GATE_OUT=OUT))
    step("G7 lock audit of the real migration", rc == 0, out[-2500:])

    # G8
    env = dict(PROD, RAILWAY_GIT_COMMIT_SHA=TARGET)
    logf = open(o("uvicorn_prod.log"), "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                           cwd=SERVER, env=env, stdout=logf, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            if http("/api/v1/health")[0] == 200:
                break
            time.sleep(1)
        hc, hb = http("/api/v1/health")
        rc_, rb = http("/api/v1/health/ready")
    finally:
        srv.terminate()
        try:
            srv.wait(15)
        except Exception:  # noqa: BLE001
            srv.kill()
        logf.close()
    slog = open(o("uvicorn_prod.log"), encoding="utf-8", errors="replace").read()
    try:
        h, r = json.loads(hb), json.loads(rb)
    except Exception:  # noqa: BLE001
        h, r = {}, {}
    leak = [s for s in ("postgresql://", "postgres://", "password", os.environ.get("SECRET_KEY") or "\x00",
                        "rehearsal-only-ephemeral") if s and (s in hb or s in rb)]
    step("G8 production-mode server: /health 200 with exact commit + production env; /health/ready 200 with "
         "lot_schema_integrity true; no secret in either body; no Traceback/500 in the server log",
         hc == 200 and rc_ == 200 and (h.get("build") or {}).get("commit") == TARGET
         and (h.get("build") or {}).get("environment") == "production"
         and (h.get("build") or {}).get("platform_environment") == "production"
         and (r.get("checks") or {}).get("lot_schema_integrity") is True and "missing_schema" not in r
         and not leak and not re.search(r"Traceback|\[FATAL\]| 500 ", slog),
         {"health": [hc, h], "ready": [rc_, r], "leak": leak})

    # G9
    genv = dict(os.environ, CLONE_DATABASE_URL=URL, GATE_OUT=OUT)
    rc, out, secs = run([PY, os.path.join("scripts", "gate", "clone_proof_89f647a.py")], env=genv, log_file=o("clone_proof.log"))
    step("G9 migration / readiness / CHECK definition / break-recover / rollback proof", rc == 0,
         "\n".join(ln for ln in out.splitlines() if "FAIL" in ln or "CLONE PROOF" in ln)[-2000:])

    # G10
    rc, out, secs = run([PY, os.path.join("scripts", "gate", "lock_proof.py"), "scenarios"], env=genv, log_file=o("lock_scenarios.log"))
    step("G10 lock behaviour under concurrent sessions", rc == 0,
         "\n".join(ln for ln in out.splitlines() if "FAIL" in ln or "LOCK SCENARIOS" in ln)[-2000:])

    # G11
    rc1 = fp("clone_after_proofs.json", o("clone_post_initdb_full.json"))
    rc2 = compare(o("clone_post_initdb_full.json"), o("clone_after_proofs.json"), "compare_after_proofs.json",
                  ["--strict-schema"])
    cmpj = json.load(open(o("compare_after_proofs.json"), encoding="utf-8")) if rc1 == 0 else {}
    step("G11 after every break/recover proof the clone equals the migrated state (business rows + strict schema)",
         rc1 == 0 and rc2 == 0, {k: v for k, v in cmpj.items() if v and k not in ("pg_stat_write_deltas", "meta")})

    # G12
    parts = urlsplit(URL)
    src_db = parts.path.lstrip("/")
    admin = urlunsplit(parts._replace(path="/postgres"))
    copy_db = "lifecycle_copy"
    copy_url = urlunsplit(parts._replace(path="/" + copy_db))
    made = False
    for _ in range(10):
        try:
            with psycopg.connect(admin, autocommit=True) as c:
                c.execute(f'DROP DATABASE IF EXISTS "{copy_db}" WITH (FORCE)')
                c.execute(f'CREATE DATABASE "{copy_db}" TEMPLATE "{src_db}"')
            made = True
            break
        except Exception as e:  # noqa: BLE001
            print("template copy retry:", type(e).__name__, str(e).splitlines()[0][:120])
            time.sleep(3)
    if made:
        lenv = dict(os.environ, DATABASE_URL=copy_url, APP_ENV="staging", RAILWAY_ENVIRONMENT_NAME="staging",
                    GATE_LIFECYCLE_DB=copy_db)
        rc, out, secs = run([PY, os.path.join(ROOT, "scripts", "gate", "clone_lifecycle.py")], env=lenv, cwd=SERVER,
                            log_file=o("lifecycle.log"), timeout=1800)
        lj = next((json.loads(ln[len("LIFECYCLE_JSON="):]) for ln in out.splitlines() if ln.startswith("LIFECYCLE_JSON=")), {})
        with open(o("lifecycle.json"), "w", encoding="utf-8") as f:
            json.dump(lj, f, indent=1, ensure_ascii=False)
        step("G12 Phase 4A lifecycle on a TEMPLATE copy of the migrated production clone (synthetic tenant): "
             "partial resolution, cogs_variance, P&L identities, return, replay, concurrency, invariant, purge; "
             "Fayzan byte-identical", rc == 0 and lj.get("verdict") == "PASS",
             [(s["step"], s["ok"]) for s in lj.get("steps", [])])
        try:
            with psycopg.connect(admin, autocommit=True) as c:
                c.execute(f'DROP DATABASE IF EXISTS "{copy_db}" WITH (FORCE)')
        except Exception:  # noqa: BLE001
            pass
    else:
        step("G12 lifecycle copy database created", False, "CREATE DATABASE ... TEMPLATE failed")

    bad = [s for s in STEPS if not s["ok"]]
    with open(o("run_gate_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"target": TARGET, "steps": STEPS, "failed": [s["step"] for s in bad]}, f, indent=1, ensure_ascii=False, default=str)
    print(f"\n=== GATE 89f647a: {len(STEPS) - len(bad)}/{len(STEPS)} steps OK ===")
    for s in STEPS:
        print(f"  [{'OK  ' if s['ok'] else 'FAIL'}] {s['step']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
