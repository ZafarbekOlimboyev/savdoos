# -*- coding: utf-8 -*-
"""Mobil E2E — BITTA buyruq: backend (start_backend.py) -> `flutter test` -> tozalash.

    python e2e/mobile/run_e2e.py                      # mahalliy (pgserver, PG16)
    python e2e/mobile/run_e2e.py --report e2e/mobile/.run/flutter-e2e.jsonl   # CI (JSON hisobot)

Backend python: `--python`, aks holda `apps/server/.venv` (bor bo'lsa), aks holda joriy python.
Flutter: `--flutter`, aks holda PATH'dagi `flutter`.

Chiqish kodi = `flutter test` kodi (hisobot tekshiruvi berilsa — uning kodi ham). Backend har
holatda to'xtatiladi: stdin yopiladi -> uvicorn to'xtaydi -> O'Z pgserver klasteri to'xtaydi.
Boshqa jarayonlarning pgserver klasterlariga TEGILMAYDI.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
MOBILE = REPO / "apps" / "mobile"
RUN = HERE / ".run"
E2E_FILES = ["test/e2e/flows_e2e.dart"]


def _log(msg: str) -> None:
    print(f"[run-e2e] {msg}", flush=True)


def _python(explicit: str | None) -> str:
    if explicit:
        return explicit
    for cand in (REPO / "apps/server/.venv/Scripts/python.exe", REPO / "apps/server/.venv/bin/python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _flutter(explicit: str | None) -> str:
    f = explicit or shutil.which("flutter") or shutil.which("flutter.bat")
    if not f:
        raise SystemExit("flutter topilmadi (PATH yoki --flutter)")
    return f


def _healthy(base: str) -> bool:
    try:
        with urllib.request.urlopen(base + "/api/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--python", default=None)
    ap.add_argument("--flutter", default=None)
    ap.add_argument("--report", default=None, help="flutter JSON hisoboti (CI); berilmasa expanded")
    ap.add_argument("--min-tests", type=int, default=15,
                    help="hisobot tekshiruvi: kamida shuncha test O'TGAN bo'lsin")
    ap.add_argument("--boot-timeout", type=int, default=900)
    ap.add_argument("--name", default=None, help="flutter test --plain-name filtri (mahalliy)")
    ap.add_argument("--keep-backend", action="store_true",
                    help="testlardan keyin backend'ni to'xtatmaslik (Ctrl+C gacha)")
    a = ap.parse_args(argv)
    if a.report:
        a.report = str(pathlib.Path(a.report).resolve())   # flutter/verify boshqa papkada ishlaydi

    RUN.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{a.port}"
    manifest = RUN / "manifest.json"
    ready = RUN / "ready.txt"
    for p in (manifest, ready):
        if p.exists():
            p.unlink()
    if _healthy(base):
        _log(f"XATO: {base} allaqachon band — boshqa backend ishlayapti")
        return 2

    blog = open(RUN / "backend.log", "w", encoding="utf-8")
    cmd = [_python(a.python), str(HERE / "start_backend.py"), "--port", str(a.port),
           "--manifest", str(manifest), "--ready-file", str(ready), "--watch-stdin"]
    env = dict(os.environ)
    env.setdefault("APP_ENV", "test")
    env.setdefault("PYTHONUNBUFFERED", "1")
    t0 = time.monotonic()
    be = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=blog, stderr=subprocess.STDOUT,
                          env=env, cwd=str(REPO))
    rc = 1
    timings: dict[str, float] = {}
    try:
        while not (ready.exists() and _healthy(base)):
            if be.poll() is not None:
                _log(f"backend to'xtadi (kod {be.returncode}) — {RUN / 'backend.log'}:")
                print((RUN / "backend.log").read_text(encoding="utf-8", errors="replace")[-4000:])
                return 2
            if time.monotonic() - t0 > a.boot_timeout:
                _log("backend tayyor bo'lmadi (timeout)")
                return 2
            time.sleep(1)
        timings["backend_ready_s"] = round(time.monotonic() - t0, 1)
        _log(f"backend tayyor: {base} ({timings['backend_ready_s']} s)")

        fl = [_flutter(a.flutter), "--no-version-check", "test", *E2E_FILES,
              f"--dart-define=E2E_BASE={base}", f"--dart-define=E2E_MANIFEST={manifest}",
              "--concurrency=1", "--reporter", "json" if a.report else "expanded"]
        if a.name:
            fl += ["--plain-name", a.name]
        _log("flutter: " + " ".join(fl[1:]))
        t1 = time.monotonic()
        if a.report:
            with open(a.report, "w", encoding="utf-8") as out:
                rc = subprocess.run(fl, cwd=str(MOBILE), stdout=out).returncode
        else:
            rc = subprocess.run(fl, cwd=str(MOBILE)).returncode
        timings["flutter_s"] = round(time.monotonic() - t1, 1)
        if a.report:
            vr = subprocess.run([sys.executable, str(HERE / "verify_e2e_report.py"), a.report,
                                 str(a.min_tests)], cwd=str(MOBILE)).returncode
            rc = rc or vr
        if a.keep_backend:
            _log("backend ishlashda qoldi (Ctrl+C)")
            try:
                be.wait()
            except KeyboardInterrupt:
                pass
    finally:
        t2 = time.monotonic()
        try:
            if be.stdin:
                be.stdin.close()
            be.wait(timeout=90)
        except Exception:  # noqa: BLE001
            be.terminate()
            try:
                be.wait(timeout=30)
            except Exception:  # noqa: BLE001
                be.kill()
        blog.close()
        timings["shutdown_s"] = round(time.monotonic() - t2, 1)
        timings["total_s"] = round(time.monotonic() - t0, 1)
        _log(f"vaqtlar: {timings}; natija kodi {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
