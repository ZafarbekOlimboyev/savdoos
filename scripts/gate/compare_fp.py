# -*- coding: utf-8 -*-
"""Compare two fingerprints produced by fp.py / prodfp.py. Connects to NOTHING.

    python compare_fp.py --hashes FP.json
    python compare_fp.py A.json B.json [--volatile t1,t2] [--strict-schema] [--allow-removed n1,n2]
                                       [--strict-identity] [--fail-on-writes]

Business rows: every table's (row count, content digest over A's column list) must be
identical, except tables named in --volatile (reported as INFO).
Schema: nothing may be removed or altered (columns with full type, indexes + validity, constraints,
triggers, functions, event triggers); additions are listed (forbidden with --strict-schema).
--strict-identity: tables, indexes and constraints present in both must keep their oid/relfilenode
                   (a drop-and-recreate with an identical definition fails).
--fail-on-writes:  any UPDATE/DELETE counted by pg_stat on a table present in A fails.
Exit 0 = OK, 1 = mismatch.
"""
import argparse
import hashlib
import json
import sys


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def canon(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def hashes(fp):
    s = fp["schema"]
    return {
        "schema_columns_sha256": canon(s["columns"]),
        "schema_indexes_sha256": canon(s["indexes"]),
        "schema_constraints_sha256": canon(s["constraints"]),
        "table_rows_and_digests_sha256": canon(fp["tables"]),
        "table_count": s["table_count"],
        "index_count": len(s["indexes"]),
        "constraint_count": len(s["constraints"]),
    }


def diff_map(xa, xb):
    return ([f"{k}: {xb[k]}" for k in sorted(set(xb) - set(xa))],
            sorted(set(xa) - set(xb)),
            [{"name": k, "before": xa[k], "after": xb[k]} for k in sorted(set(xa) & set(xb)) if xa[k] != xb[k]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--hashes")
    ap.add_argument("--volatile", default="")
    ap.add_argument("--strict-schema", action="store_true")
    ap.add_argument("--strict-identity", action="store_true")
    ap.add_argument("--fail-on-writes", action="store_true")
    # Phase 4A: EXPECTED removals only (legacy return uniqueness). Anything else still fails.
    ap.add_argument("--allow-removed", default="")
    a = ap.parse_args()

    if a.hashes:
        fp = load(a.hashes)
        print(json.dumps(hashes(fp), indent=1))
        for k, v in sorted(fp["tables"].items()):
            print(f"  {k:48s} rows={v['rows']!s:>7s} digest={str(v['digest'])[:16]}")
        return 0

    A, B = load(a.files[0]), load(a.files[1])
    vol = {x.strip() for x in a.volatile.split(",") if x.strip()}
    out = {"business_row_mismatch": [], "volatile_changed": [], "tables_added": [], "tables_removed": [],
           "columns_added": [], "columns_removed": [], "columns_altered": [],
           "indexes_added": [], "indexes_removed": [], "indexes_altered": [], "index_validity_changed": [],
           "constraints_added": [], "constraints_removed": [], "constraints_altered": [],
           "triggers_added": [], "triggers_removed": [], "triggers_altered": [],
           "functions_added": [], "functions_removed": [], "functions_altered": [],
           "event_triggers_added": [], "event_triggers_removed": [], "event_triggers_altered": [],
           "identity_changed": [], "not_compared": [], "query_errors": {},
           "pg_stat_write_deltas": {}, "pg_stat_update_delete_on_existing": {}}

    for label, fp in (("A", A), ("B", B)):
        errs = (fp.get("meta") or {}).get("query_errors")
        if errs:
            out["query_errors"][label] = errs

    for t, va in sorted(A["tables"].items()):
        vb = B["tables"].get(t)
        if vb is None:
            out["tables_removed"].append(t)
            continue
        if (va["rows"], va["digest"]) != (vb["rows"], vb["digest"]) or va["digest"] is None:
            item = {"table": t, "rows": [va["rows"], vb["rows"]],
                    "digest": [str(va["digest"])[:16], str(vb["digest"])[:16]]}
            short = t.split(".", 1)[1] if t.startswith("public.") else t
            (out["volatile_changed"] if (t in vol or short in vol) else out["business_row_mismatch"]).append(item)
    out["tables_added"] = sorted(set(B["tables"]) - set(A["tables"]))

    ca, cb = A["schema"]["columns"], B["schema"]["columns"]
    for t in sorted(set(ca) | set(cb)):
        ma = {c[0]: c for c in ca.get(t, [])}
        mb = {c[0]: c for c in cb.get(t, [])}
        if t not in ca:
            continue  # whole new table, already listed
        for n in sorted(set(mb) - set(ma)):
            out["columns_added"].append(f"{t}.{n} {mb[n][1]} nullable={mb[n][2]} default={mb[n][3]!r}")
        for n in sorted(set(ma) - set(mb)):
            out["columns_removed"].append(f"{t}.{n}")
        for n in sorted(set(ma) & set(mb)):
            if ma[n] != mb[n]:
                out["columns_altered"].append({"column": f"{t}.{n}", "before": ma[n], "after": mb[n]})

    for kind in ("indexes", "constraints", "triggers", "functions", "event_triggers"):
        xa, xb = A["schema"].get(kind), B["schema"].get(kind)
        if xa is None or xb is None:
            out["not_compared"].append(kind)
            continue
        out[f"{kind}_added"], out[f"{kind}_removed"], out[f"{kind}_altered"] = diff_map(xa, xb)

    va_, vb_ = A["schema"].get("index_validity"), B["schema"].get("index_validity")
    if va_ is None or vb_ is None:
        out["not_compared"].append("index_validity")
    else:
        out["index_validity_changed"] = [{"index": k, "before": va_[k], "after": vb_[k]}
                                         for k in sorted(set(va_) & set(vb_)) if va_[k] != vb_[k]]
        out["index_validity_changed"] += [{"index": k, "before": None, "after": vb_[k]}
                                          for k in sorted(set(vb_) - set(va_)) if vb_[k] is not True]

    if a.strict_identity:
        for kind in ("identity", "constraint_identity"):
            xa, xb = A["schema"].get(kind), B["schema"].get(kind)
            if xa is None or xb is None:
                out["not_compared"].append(kind)
                out["identity_changed"].append(f"{kind} missing from a fingerprint")
                continue
            out["identity_changed"] += [{"object": k, "before": xa[k], "after": xb[k]}
                                        for k in sorted(set(xa) & set(xb)) if xa[k] != xb[k]]

    sa, sb = A["schema"].get("pg_stat", {}), B["schema"].get("pg_stat", {})
    for t in sorted(set(sa) & set(sb)):
        d = {k: sb[t][k] - sa[t][k] for k in ("ins", "upd", "del")}
        if any(d.values()):
            out["pg_stat_write_deltas"][t] = d
        if d["upd"] or d["del"]:
            out["pg_stat_update_delete_on_existing"][t] = d

    allowed = {x.strip() for x in a.allow_removed.split(",") if x.strip()}
    out["allowed_removed"] = sorted(n for n in out["indexes_removed"] + out["constraints_removed"] if n in allowed)
    out["indexes_removed"] = [n for n in out["indexes_removed"] if n not in allowed]
    out["constraints_removed"] = [n for n in out["constraints_removed"] if n not in allowed]
    # validity rows of an allowed-removed index cannot change after removal; nothing else is excused
    bad = (out["business_row_mismatch"] or out["tables_removed"] or out["columns_removed"]
           or out["columns_altered"] or out["indexes_removed"] or out["indexes_altered"]
           or out["index_validity_changed"]
           or out["constraints_removed"] or out["constraints_altered"]
           or out["triggers_removed"] or out["triggers_altered"]
           or out["functions_removed"] or out["functions_altered"]
           or out["event_triggers_removed"] or out["event_triggers_altered"]
           or out["query_errors"])
    if a.strict_schema:
        bad = bad or out["tables_added"] or out["columns_added"] or out["indexes_added"] or out["constraints_added"] \
            or out["triggers_added"] or out["functions_added"] or out["event_triggers_added"]
    if a.strict_identity:
        bad = bad or out["identity_changed"]
    if a.fail_on_writes:
        bad = bad or out["pg_stat_update_delete_on_existing"]
    out["verdict"] = "MISMATCH" if bad else "OK"
    out["meta"] = {"A_system_identifier": A["meta"].get("system_identifier"),
                   "B_system_identifier": B["meta"].get("system_identifier"),
                   "A_db_now": A["meta"].get("db_now_utc"), "B_db_now": B["meta"].get("db_now_utc")}
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
