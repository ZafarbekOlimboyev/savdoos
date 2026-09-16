# -*- coding: utf-8 -*-
"""Fayzan 1C Migrator V1 — operator CLI.

    python -m app.tools.migrate_1c verify-bundle   --bundle export.json
    python -m app.tools.migrate_1c dry-run         --bundle export.json --company-code fayzan1 --out report.json
    python -m app.tools.migrate_1c mapping-template --report report.json --out mapping.json
    python -m app.tools.migrate_1c plan            --report report.json --mapping mapping.json --out plan.json
    python -m app.tools.migrate_1c apply           --bundle export.json --report report.json --mapping mapping.json \
                                                   --expect-system-identifier <sysid> (--rehearse | --commit)
    python -m app.tools.migrate_1c verify-applied  --company-code fayzan1 --job-id <uuid>

QURUQ YURISH: sessiya DB darajasida read-only (Postgres `default_transaction_read_only=on` + REPEATABLE READ
READ ONLY; SQLite fayl `mode=ro` URI + `query_only`). Ijobiy dalil va negativ nazorat (UPDATE ... WHERE 1=0
AYNAN read-only xatosi bilan rad etilishi) ISBOTLANMASA — to'xtaydi.
APPLY: `guard.assert_apply_allowed` — production muhiti/bazasi RAD; Postgres'da kutilgan system_identifier
MAJBURIY va ko'rib chiqilgan hisobot bazasiga teng. `--rehearse` DOIM ROLLBACK; `--commit` faqat ANIQ
berilganda va post-tekshiruv o'tganda COMMIT.
JSON fayllar (hisobot, mapping, birlik xaritasi) QAT'IY o'qiladi: takror kalit, float, NaN — RAD.
Ulanish satri faqat DATABASE_URL muhit o'zgaruvchisidan olinadi va HECH QACHON chop etilmaydi.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def _url() -> str:
    u = (os.getenv("DATABASE_URL") or "").strip()
    if not u:
        raise SystemExit("DATABASE_URL berilmagan")
    for p in ("postgres://", "postgresql://"):
        if u.startswith(p):
            return "postgresql+psycopg://" + u[len(p):]
    return u


def _sqlite_ro_creator(url: str):
    """SQLite faylini FAQAT O'QISH uchun ochadi — noto'g'ri yo'l yangi bo'sh fayl YARATMAYDI."""
    import pathlib
    import sqlite3
    from urllib.request import pathname2url
    path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else ""
    if not path or path == ":memory:":
        raise SystemExit("quruq yurish uchun SQLite FAYL yo'li kerak")
    p = pathlib.Path(path).resolve()
    if not p.is_file():
        raise SystemExit(f"SQLite fayli topilmadi: {p}")
    uri = "file:" + pathname2url(str(p)) + "?mode=ro"

    def creator():
        con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        con.execute("PRAGMA query_only = ON")
        return con
    return creator


def _engine(read_only: bool):
    from sqlalchemy import create_engine
    url = _url()
    if url.startswith("sqlite"):
        if read_only:
            return create_engine("sqlite://", creator=_sqlite_ro_creator(url))
        return create_engine(url)
    opts = "-c statement_timeout=900000"
    if read_only:
        opts = "-c default_transaction_read_only=on " + opts
    return create_engine(url, connect_args={"options": opts, "connect_timeout": 30}, pool_pre_ping=False)


def _session(read_only: bool):
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    eng = _engine(read_only)
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    if eng.dialect.name == "postgresql" and read_only:
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    return s


def _load_json(path: str, allow_int: bool = True):
    from app.services.migrator_1c.bundle import strict_json_loads
    with open(path, encoding="utf-8-sig") as f:
        return strict_json_loads(f.read(), allow_int=allow_int)


def _load_obj(path: str, what: str) -> dict:
    v = _load_json(path)
    if not isinstance(v, dict):
        raise SystemExit(f"{what}: JSON obyekt kutilgan")
    return v


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def cmd_verify_bundle(a) -> int:
    from app.services.migrator_1c.bundle import load_file
    b = load_file(a.bundle, a.sha256, require_sidecar=not a.no_sidecar)
    print(json.dumps({"ok": True, "file_sha256": b.file_sha256, "content_sha256": b.content_sha256,
                      "size_bytes": b.size_bytes, "products": len(b.products),
                      "export_id": b.data["export_id"], "snapshot_at": b.data["snapshot_at"],
                      "infobase": b.data["infobase"], "manifest": b.data["manifest"]}, ensure_ascii=False, indent=1))
    return 0


def cmd_dry_run(a) -> int:
    from app.services.migrator_1c import classify as C
    from app.services.migrator_1c.bundle import load_file
    from app.services.migrator_1c.catalog import load_snapshot
    from app.services.migrator_1c.guard import database_identity, prove_read_only
    from app.services.migrator_1c.normalize import build_unit_table

    t0 = time.time()
    bundle = load_file(a.bundle, a.sha256, require_sidecar=not a.no_sidecar)
    unit_names = _load_obj(a.unit_map, "birlik xaritasi") if a.unit_map else None
    try:
        build_unit_table(unit_names)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    db = _session(read_only=True)
    try:
        ro = prove_read_only(db)
        ident = database_identity(db)
        snap = load_snapshot(db, a.company_code)
        report = C.classify(bundle, snap, unit_names)
        ro_after = prove_read_only(db)
    finally:
        db.rollback()
        db.close()
    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report["duration_ms"] = int((time.time() - t0) * 1000)
    report["read_only_proof"] = {"before": ro, "after": ro_after}
    report["database"] = {k: ident[k] for k in ("dialect", "system_identifier", "database")}
    report["report_sha256"] = C.report_hash(report)
    _write(a.out, C.report_json(report))
    text = C.summary_text(report)
    if a.summary_out:
        _write(a.summary_out, text + "\n")
    print(text)
    print(f"read-only: {ro['probe']} / {ro_after['probe']} · baza {ident['dialect']} "
          f"{ident['system_identifier'] or ''} · {report['duration_ms']} ms · hisobot: {a.out}")
    return 0 if report["reconciliation"]["ok"] else 3


def cmd_mapping_template(a) -> int:
    from app.services.migrator_1c.mapping import build_template
    tpl = build_template(_load_obj(a.report, "hisobot"))
    _write(a.out, json.dumps(tpl, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"shablon: {a.out} · qaror kutilayotgan qatorlar {len(tpl['decisions'])} · siyosatlar {sorted(tpl['policies'])}")
    return 0


def cmd_plan(a) -> int:
    from app.services.migrator_1c.mapping import MappingError, build_plan
    try:
        plan = build_plan(_load_obj(a.report, "hisobot"), _load_obj(a.mapping, "mapping"))
    except MappingError as e:
        print(json.dumps({"ok": False, "problems": e.problems}, ensure_ascii=False, indent=1))
        return 2
    if a.out:
        _write(a.out, json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"ok": True, "plan_sha256": plan["plan_sha256"], "expected": plan["expected"],
                      "skipped": len(plan["skipped"]), "deactivate": len(plan["deactivate"]),
                      "kept_unlinked": len(plan["kept_unlinked"])}, ensure_ascii=False, indent=1))
    return 0


def cmd_apply(a) -> int:
    from app.services.migrator_1c.apply import apply_migration
    from app.services.migrator_1c.bundle import load_file
    if a.rehearse == a.commit:
        raise SystemExit("--rehearse YOKI --commit — aynan bittasi")
    bundle = load_file(a.bundle, a.sha256, require_sidecar=not a.no_sidecar)
    report, mapping = _load_obj(a.report, "hisobot"), _load_obj(a.mapping, "mapping")
    db = _session(read_only=False)
    t0 = time.time()
    try:
        out = apply_migration(db, bundle, report, mapping, expect_system_identifier=a.expect_system_identifier)
        if a.commit:
            db.commit()
            out["committed"] = True
        else:
            db.rollback()
            out["committed"] = False
            out["rolled_back"] = True
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    out["duration_ms"] = int((time.time() - t0) * 1000)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_verify_applied(a) -> int:
    import uuid

    from app.models.imports import ImportJob
    from app.services.migrator_1c.apply import verify_state
    from app.services.migrator_1c.guard import prove_read_only
    db = _session(read_only=True)
    try:
        ro = prove_read_only(db)
        job = db.get(ImportJob, uuid.UUID(a.job_id))
        if job is None or not (job.column_mapping or {}).get("plan"):
            raise SystemExit("job yoki uning rejasi topilmadi")
        plan = job.column_mapping["plan"]
        if plan["company_code"] != a.company_code:
            raise SystemExit("job boshqa do'konga tegishli")
        status = job.status.value                      # sessiya yopilishidan OLDIN o'qiladi
        res = verify_state(db, job.company_id, job.id, plan)
        ro_after = prove_read_only(db)
    finally:
        db.rollback()
        db.close()
    print(json.dumps({"read_only": {"before": ro, "after": ro_after}, "job_status": status, **res},
                     ensure_ascii=False, indent=1, default=str))
    return 0 if res["ok"] and status == "committed" else 4


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):                 # Windows cp1252 konsolida kirill chiqishi yiqilmasin
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="migrate_1c")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def bundle_args(p):
        p.add_argument("--bundle", required=True)
        p.add_argument("--sha256", default=None, help="yon fayl (standart: <bundle>.sha256)")
        p.add_argument("--no-sidecar", action="store_true", help="FAQAT test: yon fayl talab qilinmaydi")

    p = sub.add_parser("verify-bundle")
    bundle_args(p)
    p.set_defaults(fn=cmd_verify_bundle)
    p = sub.add_parser("dry-run")
    bundle_args(p)
    p.add_argument("--company-code", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--summary-out")
    p.add_argument("--unit-map")
    p.set_defaults(fn=cmd_dry_run)
    p = sub.add_parser("mapping-template")
    p.add_argument("--report", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_mapping_template)
    p = sub.add_parser("plan")
    p.add_argument("--report", required=True)
    p.add_argument("--mapping", required=True)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("apply")
    bundle_args(p)
    p.add_argument("--report", required=True)
    p.add_argument("--mapping", required=True)
    p.add_argument("--expect-system-identifier", default=None,
                   help="Postgres'da MAJBURIY: maqsad bazaning pg_control_system().system_identifier qiymati")
    p.add_argument("--rehearse", action="store_true")
    p.add_argument("--commit", action="store_true")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("verify-applied")
    p.add_argument("--company-code", required=True)
    p.add_argument("--job-id", required=True)
    p.set_defaults(fn=cmd_verify_applied)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
