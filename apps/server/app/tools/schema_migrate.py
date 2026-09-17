# -*- coding: utf-8 -*-
"""SavdoOS Operations CLI · ANIQ SXEMA MIGRATSIYASI (preflight / apply / verify / revert).

    python -m app.tools.schema_migrate list
    python -m app.tools.schema_migrate preflight --migration <id> [--expect-system-identifier <sysid>] \
        [--out report.json] [--json]
    python -m app.tools.schema_migrate apply --migration <id> --report report.json \
        --expect-system-identifier <sysid> (--rehearse | --commit) \
        [--lock-timeout-ms 2000] [--statement-timeout-ms 60000] \
        [--allow-production --confirm-production-system-identifier <sysid>]
    python -m app.tools.schema_migrate verify --migration <id> [--expect-system-identifier <sysid>]
    python -m app.tools.schema_migrate revert --migration <id> --report report.json \
        --expect-system-identifier <sysid> (--rehearse | --commit)   # FAQAT mashq/favqulodda

NEGA. Boot (`python -m app.initdb`) mavjud ustunning TIPINI HECH QACHON o'zgartirmaydi:
`ALTER .. TYPE` ACCESS EXCLUSIVE oladi, jadvalni qayta yozadi va har indeksni qayta quradi —
qulf band bo'lsa deploy crash-loop'ga tushardi, qiymatlar esa operator qarorini talab qiladi.
Boot faqat TAYYORLIKNI qizil qiladi (`column_types=false` -> `/health/ready` 503) va shu
vositani ko'rsatadi.

XAVFSIZLIK (fail-closed, `app/db/migrations/guard.py`):
  · `preflight` va `verify` HAR MUHITDA ruxsat, lekin sessiya DB darajasida read-only
    (`default_transaction_read_only=on` + REPEATABLE READ READ ONLY) va bu ISBOTLANADI:
    ijobiy dalil + negativ nazorat (yozuv AYNAN 25006 bilan rad etilishi);
  · `apply`/`revert` — muhit ruxsat ro'yxati, production sysid taqiq ro'yxati, ruxsat etilgan
    klaster ro'yxati (+ efemer klonlar uchun env), MAJBURIY `--expect-system-identifier`,
    ko'rib chiqilgan hisobotning baza identiteti va `plan_sha256` bog'lanishi;
  · production'ga yozish FAQAT `--allow-production` VA `--confirm-production-system-identifier`
    bilan, muhit o'zini production deb e'lon qilgan holda (runbook: bu bosqichda TAQIQLANGAN).

CHIQISH KODLARI: 0 = OK / ALREADY_APPLIED / NOT_APPLICABLE, 1 = usage yoki darvoza RAD etdi,
2 = REVIEW yoki qayta urinsa bo'ladigan holat (qulf band, statement_timeout), 3 = BLOCKED /
REJECTED / verify FAIL.

⚠️  CHIQISHDA QIYMAT YO'Q. Hisobotda faqat SANOQ, struktura va sha256; `DATABASE_URL`,
    host, foydalanuvchi paroli hech qachon chop etilmaydi.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from app.db.migrations import contract as C
from app.tools import _common as CM


class _Parser(argparse.ArgumentParser):
    """argparse standart bo'yicha 2 bilan chiqadi — bizda 2 «REVIEW» degani."""

    def error(self, message):       # noqa: D401
        CM.err(f"USAGE XATOSI: {message}")
        raise SystemExit(C.EXIT_USAGE)


# ── Ulanish ──────────────────────────────────────────────────────────────────

def _url() -> str:
    u = (os.getenv("DATABASE_URL") or "").strip()
    if not u:
        raise SystemExit("DATABASE_URL berilmagan")
    for p in ("postgres://", "postgresql://"):
        if u.startswith(p):
            return "postgresql+psycopg://" + u[len(p):]
    return u


def _backend(url: str) -> str:
    from sqlalchemy.engine import make_url
    return make_url(url).get_backend_name()


def _engine(url: str, *, read_only: bool, statement_timeout_ms: int):
    """⚠️  Read-only rejimda chegara SESSIYA opsiyasida — hovuzning HAR ulanishi uni oladi."""
    from sqlalchemy import create_engine
    opts = [f"-c application_name={_APP_NAME}", f"-c statement_timeout={int(statement_timeout_ms)}"]
    if read_only:
        opts.insert(0, "-c default_transaction_read_only=on")
    return create_engine(url, connect_args={"options": " ".join(opts), "connect_timeout": 30},
                         pool_pre_ping=False)


_APP_NAME = "savdoos_schema_migrate"


def _read_only_session(url: str, statement_timeout_ms: int):
    """(engine, connection, read-only isboti) — REPEATABLE READ READ ONLY."""
    from sqlalchemy import text

    from app.db.migrations import guard
    eng = _engine(url, read_only=True, statement_timeout_ms=statement_timeout_ms)
    con = eng.connect()
    try:
        con.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        proof = guard.prove_read_only(con)
    except BaseException:
        con.close()
        eng.dispose()
        raise
    return eng, con, proof


def _lock_holders(url: str, tables) -> str:
    """Qulfni ushlab turgan BOSHQA seanslar — FAQAT jurnal uchun (qiymat yo'q, DSN yo'q)."""
    from sqlalchemy import text
    try:
        eng = _engine(url, read_only=True, statement_timeout_ms=10_000)
        found = []
        try:
            with eng.connect() as con:
                for t in tables:
                    for pid, mode, state, app, age in con.execute(text(
                            "SELECT a.pid, l.mode, a.state, a.application_name, "
                            "       EXTRACT(EPOCH FROM clock_timestamp() - a.xact_start)::int "
                            "FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                            "WHERE l.locktype = 'relation' AND l.granted "
                            "  AND l.database = (SELECT oid FROM pg_database "
                            "                    WHERE datname = current_database()) "
                            "  AND l.relation = to_regclass(:t) AND l.pid <> pg_backend_pid() "
                            "ORDER BY a.xact_start NULLS LAST, a.pid"), {"t": f"public.{t}"}):
                        found.append(f"{t}: pid={pid} {mode} ({state}, tranzaksiya "
                                     f"{'?' if age is None else age}s, ilova={app!r})")
        finally:
            eng.dispose()
    except Exception:      # noqa: BLE001
        return "to'sayotgan seanslarni o'qib bo'lmadi"
    return "; ".join(found) if found else "hozir hech kim ushlamayapti (qulf bo'shagan)"


# ── Hisobot fayli ────────────────────────────────────────────────────────────

def _strict_load(path: str) -> dict:
    """Hisobotni QAT'IY o'qiydi: obyekt bo'lishi va TAKROR KALIT bo'lmasligi shart."""
    def pairs(items):
        seen = {}
        for k, v in items:
            if k in seen:
                raise SystemExit(f"hisobotda takror kalit: {k!r}")
            seen[k] = v
        return seen
    try:
        with open(path, encoding="utf-8-sig") as f:
            obj = json.loads(f.read(), object_pairs_hook=pairs)
    except OSError as e:
        raise SystemExit(f"hisobotni o'qib bo'lmadi: {type(e).__name__}") from e
    except ValueError as e:
        raise SystemExit(f"hisobot JSON emas: {e}") from e
    if not isinstance(obj, dict):
        raise SystemExit("hisobot: JSON obyekt kutilgan")
    return obj


def _write(path: str, obj: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, default=str) + "\n")


def _load_reviewed(path: str, migration_id: str) -> dict:
    """Ko'rib chiqilgan hisobot: sha256 buzilmagan, AYNI migratsiya uchun."""
    rep = _strict_load(path)
    if rep.get("migration_id") != migration_id:
        raise _Blocked(f"hisobot boshqa migratsiya uchun: {rep.get('migration_id')!r}")
    if rep.get("report_sha256") != C.report_sha256(rep):
        raise _Blocked("hisobot BUZILGAN: report_sha256 mos emas (qayta preflight qiling)")
    if rep.get("plan_sha256") != C.plan_sha256(rep):
        raise _Blocked("hisobot BUZILGAN: plan_sha256 hisobot mazmuniga mos emas")
    return rep


class _Blocked(Exception):
    """Hisobot/holat mos emas — chiqish kodi 3."""


# ── Buyruqlar ────────────────────────────────────────────────────────────────

def cmd_list(a) -> int:
    from app.db.migrations import MIGRATIONS
    rows = [{"migration_id": m.MIGRATION_ID, "title": m.TITLE,
             "targets": [f"{t}.{c}" for t, c in m.TARGETS]} for m in MIGRATIONS.values()]
    if a.json:
        CM.emit_json({"migrations": rows})
        return C.EXIT_OK
    for r in rows:
        CM.out(f"{r['migration_id']}  —  {r['title']}")
        CM.out(f"    ustunlar: {', '.join(r['targets'])}")
    return C.EXIT_OK


def _not_applicable(mig, backend: str, a) -> int:
    rep = {"migration_id": mig.MIGRATION_ID, "verdict": C.VERDICT_NOT_APPLICABLE,
           "dialect": backend, "findings": []}
    if getattr(a, "json", False):
        CM.emit_json(rep)
    else:
        CM.out(f"{mig.MIGRATION_ID}: NOT_APPLICABLE ({backend} — bu migratsiya faqat PostgreSQL "
               "uchun ma'noli; hech narsa o'qilmadi va yozilmadi)")
    return C.EXIT_OK


def cmd_preflight(a) -> int:
    mig = a.mig
    url = _url()
    backend = _backend(url)
    if backend != "postgresql":
        return _not_applicable(mig, backend, a)
    from app.db.migrations import guard
    eng, con, proof = _read_only_session(url, a.statement_timeout_ms)
    try:
        ident = guard.database_identity(con)
        if a.expect_system_identifier and \
                str(a.expect_system_identifier).strip() != ident["system_identifier"]:
            CM.err(f"RAD ETILDI: kutilgan baza {str(a.expect_system_identifier).strip()}, "
                   f"ulangan {ident['system_identifier']}")
            return C.EXIT_USAGE
        report = mig.preflight(con)
        report["read_only_proof"] = {"before": proof, "after": guard.prove_read_only(con)}
        C.seal(report)
    finally:
        con.rollback()
        con.close()
        eng.dispose()
    if a.out:
        _write(a.out, report)
    if a.json:
        CM.emit_json(report)
    _print_report(report, out_path=a.out)
    return C.exit_code_for(report)


def _print_report(report: dict, *, out_path: str | None = None) -> None:
    db = report.get("database") or {}
    block, review, info = C.split_severity(report.get("findings") or [])
    CM.out(f"migratsiya:  {report.get('migration_id')}")
    CM.out(f"baza:        {db.get('database')} · system_identifier {db.get('system_identifier')} "
           f"· server {db.get('server_version_num')}")
    CM.out(f"hukm:        {report.get('verdict')}")
    drifted = ", ".join("{}.{}".format(d["table"], d["column"])
                        for d in (report.get("drifted") or [])) or "—"
    CM.out(f"og'ishlar:   {drifted}")
    for v in (report.get("values") or {}).get("columns", []):
        CM.out(f"  {v['table']}.{v['column']}: qator={v['rows']} null={v['null']} "
               f"kanonik_kichik={v['canonical_lower']} kanonik_boshqa_registr="
               f"{v['canonical_other_case']} bo'sh={v['empty']} nokanonik={v['noncanonical']}")
    for f in block + review + info:
        CM.out(f"  [{f['severity']}] {f['code']}: {f['detail']}")
    CM.out(f"plan_sha256:   {report.get('plan_sha256')}")
    CM.out(f"report_sha256: {report.get('report_sha256')}")
    if out_path:
        CM.out(f"hisobot saqlandi: {out_path}")


def cmd_verify(a) -> int:
    mig = a.mig
    url = _url()
    backend = _backend(url)
    if backend != "postgresql":
        return _not_applicable(mig, backend, a)
    from app.db.migrations import guard
    eng, con, proof = _read_only_session(url, a.statement_timeout_ms)
    try:
        ident = guard.database_identity(con)
        if a.expect_system_identifier and \
                str(a.expect_system_identifier).strip() != ident["system_identifier"]:
            CM.err(f"RAD ETILDI: kutilgan baza {str(a.expect_system_identifier).strip()}, "
                   f"ulangan {ident['system_identifier']}")
            return C.EXIT_USAGE
        res = mig.verify(con, bind=eng)
        res["read_only_proof"] = {"before": proof, "after": guard.prove_read_only(con)}
        res["database"] = ident
    finally:
        con.rollback()
        con.close()
        eng.dispose()
    if a.json:
        CM.emit_json(res)
    CM.out(f"verify: {res['result']} · tiplar: "
           + ", ".join(f"{k}={v}" for k, v in sorted(res["column_types"].items())))
    for p in res["problems"]:
        CM.out(f"  [MUAMMO] {p}")
    return C.EXIT_OK if res["ok"] else C.EXIT_BLOCK


def _timeout_ok(ms) -> bool:
    return isinstance(ms, int) and 1 <= ms <= 2_147_483_647


def cmd_apply(a) -> int:
    return _apply_or_revert(a, revert=False)


def cmd_revert(a) -> int:
    return _apply_or_revert(a, revert=True)


def _apply_or_revert(a, *, revert: bool) -> int:
    from sqlalchemy.exc import DBAPIError

    from app.db.migrations import guard
    what = "revert" if revert else "apply"
    mig = a.mig
    if bool(a.rehearse) == bool(a.commit):
        CM.err("--rehearse YOKI --commit — AYNAN bittasi")
        return C.EXIT_USAGE
    for name, val in (("--lock-timeout-ms", a.lock_timeout_ms),
                      ("--statement-timeout-ms", a.statement_timeout_ms)):
        if not _timeout_ok(val):
            CM.err(f"{name} yaroqsiz: {val!r} (1..2147483647 ms)")
            return C.EXIT_USAGE
    url = _url()
    backend = _backend(url)
    if backend != "postgresql":
        return _not_applicable(mig, backend, a)
    try:
        reviewed = _load_reviewed(a.report, mig.MIGRATION_ID)
    except _Blocked as e:
        CM.err(f"RAD ETILDI: {e}")
        return C.EXIT_BLOCK
    if a.allow_production:
        CM.out("!" * 74)
        CM.out(f"  PRODUCTION YO'LI: {what} bazaga YOZADI (ACCESS EXCLUSIVE + ALTER TABLE).")
        CM.out("  Alohida YOZMA ruxsatsiz bajarilmaydi (runbook §2.1).")
        CM.out("!" * 74)

    eng = _engine(url, read_only=False, statement_timeout_ms=a.statement_timeout_ms)
    con = eng.connect()
    trans = con.begin()
    t0 = time.time()
    try:
        ident = guard.assert_write_allowed(
            con, expect_system_identifier=a.expect_system_identifier,
            reviewed_identity=reviewed.get("database"), allow_production=bool(a.allow_production),
            confirm_production_system_identifier=a.confirm_production_system_identifier)
        fn = mig.revert if revert else mig.apply
        out = fn(con, reviewed_report=reviewed, lock_timeout_ms=a.lock_timeout_ms,
                 statement_timeout_ms=a.statement_timeout_ms)
        if a.commit:
            trans.commit()
            out["committed"] = True
        else:
            trans.rollback()
            out["committed"] = False
            out["rehearsed"] = True
    except guard.MigrationForbidden as e:
        trans.rollback()
        con.close()
        eng.dispose()
        CM.err(f"RAD ETILDI: {e}")
        return C.EXIT_USAGE
    except (C.MigrationBlocked, C.MigrationRejected, C.MigrationVerifyFailed) as e:
        trans.rollback()
        con.close()
        eng.dispose()
        CM.err(f"TO'XTATILDI ({type(e).__name__}): {e} — hech narsa o'zgarmadi")
        return C.EXIT_BLOCK
    except DBAPIError as e:
        trans.rollback()
        con.close()
        eng.dispose()
        state = getattr(getattr(e, "orig", None), "sqlstate", None)
        if state == "55P03":
            CM.err(f"QULF OLINMADI (lock_timeout={a.lock_timeout_ms}ms): "
                   f"{_lock_holders(url, sorted({t for t, _ in mig.TARGETS}))} — hech narsa "
                   "o'zgarmadi, sokin oynada qayta urinib ko'ring")
            return C.EXIT_REVIEW
        if state == "57014":
            CM.err(f"VAQT CHEGARASI (statement_timeout={a.statement_timeout_ms}ms) — hech narsa "
                   "o'zgarmadi")
            return C.EXIT_REVIEW
        CM.err(f"BAZA XATOSI (SQLSTATE {state or '?'}) — hech narsa o'zgarmadi")
        return C.EXIT_BLOCK
    except BaseException:
        trans.rollback()
        con.close()
        eng.dispose()
        raise
    out["duration_ms"] = int((time.time() - t0) * 1000)
    out["database"] = {k: ident.get(k) for k in ("system_identifier", "database")}

    # Mashq: tranzaksiya qaytarildi — katalog HAQIQATAN o'zgarmaganini QAYTA o'qiymiz.
    try:
        with eng.connect() as con2:
            types = {f"{t}.{c}": v for (t, c), v in sorted(mig.column_types(con2).items())}
    finally:
        con.close()
        eng.dispose()
    out["column_types_after"] = types
    still_changed: list[str] = []
    if a.rehearse and out.get("changed"):
        # Mashq DOIM qaytariladi: o'zgartirmoqchi bo'lgan ustunlarning BIRORTASI ham
        # maqsad tipda qolmasligi kerak (aks holda ROLLBACK ishlamagan).
        want = mig.SOURCE_TYPES[0] if revert else mig.TARGET_TYPE
        still_changed = [k for k in out["changed"] if types.get(k) == want]
        out["catalog_unchanged"] = not still_changed
    if a.json:
        CM.emit_json(out)
    CM.out(f"{what}: {out['result']} · commit={out.get('committed')} · DDL={len(out.get('ddl') or [])} "
           f"· qulf kutishi={out.get('lock_wait_ms', 0)}ms · {out['duration_ms']} ms")
    for stmt in out.get("ddl") or []:
        CM.out(f"  {stmt}")
    CM.out("  tiplar: " + ", ".join(f"{k}={v}" for k, v in types.items()))
    if still_changed:
        CM.err(f"MASHQ QAYTARILMADI: {', '.join(still_changed)} hali ham o'zgargan")
        return C.EXIT_BLOCK

    if a.commit and out["result"] != C.RESULT_NOT_APPLICABLE:
        eng2, con2, _proof = _read_only_session(url, a.statement_timeout_ms)
        try:
            res = mig.verify(con2, bind=eng2) if not revert else {"ok": True, "problems": []}
        finally:
            con2.rollback()
            con2.close()
            eng2.dispose()
        if not res["ok"]:
            for p in res["problems"]:
                CM.err(f"  [VERIFY] {p}")
            return C.EXIT_BLOCK
    return C.EXIT_OK


# ── main ─────────────────────────────────────────────────────────────────────

def _add_common(p):
    p.add_argument("--json", action="store_true", help="stdout FAQAT JSON")
    p.add_argument("--statement-timeout-ms", type=int, default=60_000)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):        # Windows cp1252 konsolida kirill yiqilmasin
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    ap = _Parser(prog="schema_migrate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("preflight")
    p.add_argument("--migration", required=True)
    p.add_argument("--expect-system-identifier", default=None)
    p.add_argument("--out", default=None, help="hisobot JSON fayli (operator saqlaydi)")
    _add_common(p)
    p.set_defaults(fn=cmd_preflight)

    p = sub.add_parser("verify")
    p.add_argument("--migration", required=True)
    p.add_argument("--expect-system-identifier", default=None)
    _add_common(p)
    p.set_defaults(fn=cmd_verify)

    for name, fn in (("apply", cmd_apply), ("revert", cmd_revert)):
        p = sub.add_parser(name)
        p.add_argument("--migration", required=True)
        p.add_argument("--report", required=True, help="ko'rib chiqilgan preflight hisoboti")
        p.add_argument("--expect-system-identifier", default=None,
                       help="MAJBURIY (Postgres): maqsad bazaning system_identifier qiymati")
        p.add_argument("--rehearse", action="store_true", help="DOIM ROLLBACK")
        p.add_argument("--commit", action="store_true")
        p.add_argument("--lock-timeout-ms", type=int, default=2_000)
        p.add_argument("--allow-production", action="store_true")
        p.add_argument("--confirm-production-system-identifier", default=None)
        _add_common(p)
        p.set_defaults(fn=fn)

    try:
        a = ap.parse_args(argv)
    except SystemExit as e:            # `_Parser.error` yoki `--help`
        return e.code if isinstance(e.code, int) else C.EXIT_USAGE
    CM.set_stdout_json_only(bool(getattr(a, "json", False)))
    if getattr(a, "migration", None) is not None:
        from app.db.migrations import get
        try:
            a.mig = get(a.migration)
        except KeyError as e:
            CM.err(f"USAGE XATOSI: {e.args[0] if e.args else e}")
            return C.EXIT_USAGE
    try:
        return a.fn(a)
    except SystemExit as e:            # `DATABASE_URL yo'q`, buzuq hisobot fayli ...
        if isinstance(e.code, str):
            CM.err(f"USAGE XATOSI: {e.code}")
            return C.EXIT_USAGE
        return e.code if isinstance(e.code, int) else C.EXIT_USAGE
    except PermissionError as e:       # read-only isboti bo'lmadi
        CM.err(f"TO'XTATILDI: {e}")
        return C.EXIT_BLOCK


if __name__ == "__main__":
    raise SystemExit(main())
