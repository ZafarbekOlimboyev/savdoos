# -*- coding: utf-8 -*-
"""Mobil E2E backend (Phase 5G, M6): Postgres + initdb + stsenariy + uvicorn 127.0.0.1:8010.

Baza:
  * `DATABASE_URL` berilgan bo'lsa (CI: `postgres:18` servisi) — O'SHA baza (bo'sh bo'lishi kerak;
    stsenariy do'koni mavjud bo'lsa rad etadi);
  * aks holda — SHU jarayonning O'Z pgserver klasteri (`--pgdata`, standart: vaqtinchalik papka).
    Klaster jarayon tugaganda to'xtatiladi (vaqtinchalik papka o'chiriladi). Boshqa pgserver
    jarayonlariga HECH QACHON tegilmaydi.

Ketma-ketlik: xavfsizlik darvozasi (`scenario.refusal_reasons`) -> `app.initdb` -> stsenariy
(`scenario.seed`, manifest JSON) -> uvicorn. Tayyorlik belgisi: `GET /api/v1/health` 200 va
`--ready-file` (berilsa) yozilgan.

    apps/server/.venv/Scripts/python e2e/mobile/start_backend.py            # mahalliy
    DATABASE_URL=postgresql://... APP_ENV=test python e2e/mobile/start_backend.py   # CI

To'xtatish: Ctrl+C, `--watch-stdin` bilan stdin yopilishi (run_e2e.py shunday qiladi) yoki
`--stop-file` paydo bo'lishi.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import secrets
import shutil
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SERVER_DIR = REPO / "apps" / "server"
DEFAULT_MANIFEST = HERE / ".run" / "manifest.json"


def _log(msg: str) -> None:
    print(f"[e2e-backend] {msg}", flush=True)


def _prepare_env(url: str) -> None:
    """Jarayon ichidagi ilova konfiguratsiyasi — `app` import qilinishidan OLDIN."""
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    # Postgres bilan `settings.is_production` = True (fail-safe): boot qo'riqchisi kuchli JWT
    # kalitini talab qiladi. Kalit har ishga tushishda YANGI — tokenlar shu backenddan chiqmaydi.
    if len((os.environ.get("SECRET_KEY") or "").strip()) < 32:
        os.environ["SECRET_KEY"] = secrets.token_hex(32)
    # Vendor portali kerak emas (do'kon provizioning funksiyasi to'g'ridan-to'g'ri chaqiriladi);
    # demo seed Postgres'da production qoidasi bilan taqiqlangan.
    for k in ("VENDOR_ADMIN_KEY", "SEED_DEMO"):
        os.environ.pop(k, None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mobil E2E backend")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--tenant-code", default="e2emob")
    ap.add_argument("--pgdata", default=None,
                    help="pgserver papkasi (DATABASE_URL yo'q bo'lsa); standart: vaqtinchalik")
    ap.add_argument("--ready-file", default=None)
    ap.add_argument("--stop-file", default=None)
    ap.add_argument("--watch-stdin", action="store_true",
                    help="stdin yopilsa (ota jarayon o'ldi/tugadi) — to'xtash")
    a = ap.parse_args(argv)
    # Yo'llar ishga tushirilgan papkaga nisbatan — keyingi `chdir(apps/server)` dan OLDIN mutlaq.
    for attr in ("manifest", "pgdata", "ready_file", "stop_file"):
        v = getattr(a, attr)
        if v:
            setattr(a, attr, str(pathlib.Path(v).resolve()))

    t0 = time.monotonic()
    srv = None
    tmp_dir = None
    url = os.environ.get("DATABASE_URL", "").strip()
    sys.path.insert(0, str(HERE))
    import scenario  # noqa: E402  (shu papkadagi modul)

    try:
        if url:
            _log("baza: DATABASE_URL (tashqi Postgres)")
        else:
            import pgserver
            if a.pgdata:
                pg_dir = pathlib.Path(a.pgdata).resolve()
                pg_dir.parent.mkdir(parents=True, exist_ok=True)
                mode = "stop"
            else:
                tmp_dir = tempfile.mkdtemp(prefix="savdoos_mobile_e2e_")
                pg_dir = pathlib.Path(tmp_dir) / "pgdata"
                mode = "delete"
            srv = pgserver.get_server(str(pg_dir), cleanup_mode=mode)
            url = srv.get_uri()
            _log(f"baza: shaxsiy pgserver ({pg_dir}) {time.monotonic() - t0:.1f} s")
        url = scenario.normalize_url(url)
        _prepare_env(url)

        # ── Xavfsizlik darvozasi: initdb'dan ham OLDIN ──────────────────────────
        try:
            ident = scenario.assert_allowed(url, tenant_code=a.tenant_code)
        except scenario.Refused as e:
            _log(f"RAD: {e}")
            return 3
        _log(f"baza identiteti: sysid={ident['system_identifier']} db={ident['database']}")
        # Mavjud do'konga hech qachon yozilmaydi — DDL'dan (initdb) ham OLDIN to'xtaymiz.
        if scenario.tenant_exists(url, a.tenant_code):
            _log(f"RAD: do'kon '{a.tenant_code}' bu bazada ALLAQACHON bor — bo'sh baza yoki "
                 "boshqa --tenant-code bering")
            return 3

        os.chdir(SERVER_DIR)
        sys.path.insert(0, str(SERVER_DIR))
        t1 = time.monotonic()
        from app import initdb  # noqa: E402
        initdb.main()
        _log(f"initdb {time.monotonic() - t1:.1f} s")

        t2 = time.monotonic()
        try:
            manifest = scenario.seed(url, a.tenant_code, log=_log)
        except scenario.Refused as e:
            _log(f"RAD: {e}")
            return 3
        mpath = scenario.write_manifest(manifest, a.manifest)
        _log(f"stsenariy {time.monotonic() - t2:.1f} s -> {mpath}")

        import uvicorn  # noqa: E402

        from app.main import app  # noqa: E402
        config = uvicorn.Config(app, host=a.host, port=a.port, log_level="warning",
                                access_log=False)
        server = uvicorn.Server(config)

        def _stop(reason: str) -> None:
            _log(f"to'xtatilmoqda ({reason})")
            server.should_exit = True

        if a.watch_stdin:
            def _stdin():
                try:
                    while sys.stdin.read(1024):
                        pass
                except Exception:  # noqa: BLE001
                    pass
                _stop("stdin yopildi")
            threading.Thread(target=_stdin, daemon=True).start()
        if a.stop_file:
            sf = pathlib.Path(a.stop_file)

            def _watch():
                while not server.should_exit:
                    if sf.exists():
                        _stop("stop-file")
                        return
                    time.sleep(0.5)
            threading.Thread(target=_watch, daemon=True).start()

        def _ready():
            while not server.started and not server.should_exit:
                time.sleep(0.1)
            if server.started:
                _log(f"TAYYOR http://{a.host}:{a.port} (jami {time.monotonic() - t0:.1f} s)")
                if a.ready_file:
                    pathlib.Path(a.ready_file).write_text(str(mpath), encoding="utf-8")
        threading.Thread(target=_ready, daemon=True).start()
        server.run()
        return 0
    finally:
        try:
            from app.db.session import engine
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass
        if srv is not None:
            try:
                srv.cleanup()
                _log("pgserver to'xtatildi")
            except Exception as e:  # noqa: BLE001
                _log(f"pgserver cleanup: {e}")
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
