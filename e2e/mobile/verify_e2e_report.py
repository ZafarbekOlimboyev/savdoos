# -*- coding: utf-8 -*-
"""Mobil E2E testlari HAQIQATAN bajarilganini isbotlaydi (`flutter test --reporter json`).

Exit kodiga ishonilmaydi (Phase 4A.1 saboqi). Tekshiruvlar:
  * `test/e2e/*_e2e.dart` fayllarining HAR biri yuklangan va kamida bitta test o'tgan;
  * `REQUIRED_GROUPS` dagi har oqim (1..10 + connectivity + sign-in) kamida bitta O'TGAN test bilan;
  * hech bir test yiqilmagan, `error` bermagan, SKIP qilinmagan;
  * o'tgan testlar soni pastki chegaradan kam emas;
  * reporter `done` hodisasi `success: true`.

    python e2e/mobile/verify_e2e_report.py <flutter-e2e.jsonl> <min_tests>

(`apps/mobile` papkasidan ishga tushiriladi — fayl yo'llari shunga nisbatan.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Guruh nomi PREFIKSLARI (flows_e2e.dart dagi `group(...)`). Oqim olib tashlansa — QIZIL.
REQUIRED_GROUPS = (
    "0. sign-in", "1. barcode", "2-3-7. receiving", "4. count", "5. write-off",
    "6. correction", "8. customer debt", "9. branch isolation", "10. permission negative",
    "connectivity",
)


def main(report: str, minimum: int) -> int:
    suites: dict[int, str] = {}
    tests: dict[int, dict] = {}
    groups: dict[int, str] = {}
    passed: list[tuple[str, str]] = []
    errors: list[str] = []
    failed = skipped = 0
    done_success = None

    for raw in Path(report).read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = e.get("type")
        if kind == "suite":
            suites[e["suite"]["id"]] = (e["suite"].get("path") or "").replace("\\", "/")
        elif kind == "group":
            groups[e["group"]["id"]] = e["group"].get("name") or ""
        elif kind == "testStart":
            tests[e["test"]["id"]] = e["test"]
        elif kind == "error":
            t = tests.get(e.get("testID"), {})
            errors.append(f"{t.get('name', '?')}: {str(e.get('error'))[:400]}")
        elif kind == "testDone":
            t = tests.get(e["testID"], {})
            path = suites.get(t.get("suiteID"), "?")
            if e.get("result") != "success":
                failed += 1
                errors.append(f"{path} :: {t.get('name', '?')} -> {e.get('result')}")
                continue
            if e.get("hidden"):
                continue
            if e.get("skipped"):
                skipped += 1
                errors.append(f"{path} :: {t.get('name', '?')} -> SKIPPED")
                continue
            passed.append((path, t.get("name", "")))
        elif kind == "done":
            done_success = e.get("success")

    on_disk = sorted(p.as_posix() for p in Path("test/e2e").glob("*_e2e.dart"))
    by_file: dict[str, int] = {}
    for path, _ in passed:
        for f in on_disk:
            if path.endswith(f):
                by_file[f] = by_file.get(f, 0) + 1
    names = [n for _, n in passed]
    missing_groups = [g for g in REQUIRED_GROUPS if not any(n.startswith(g) for n in names)]

    for f in on_disk:
        print(f"  {by_file.get(f, 0):4d}  {f}")
    for n in names:
        print(f"    ok  {n}")
    print(f"mobile e2e: passed={len(passed)} failed={failed} skipped={skipped} "
          f"files={len(on_disk)} done.success={done_success}")

    bad = []
    if not on_disk:
        bad.append("test/e2e/*_e2e.dart topilmadi — tekshiruv ma'nosiz")
    not_run = [f for f in on_disk if by_file.get(f, 0) == 0]
    if not_run:
        bad.append(f"BAJARILMAGAN e2e fayllari: {not_run}")
    if missing_groups:
        bad.append(f"o'tgan testi YO'Q oqimlar: {missing_groups}")
    if failed or skipped or errors:
        bad.append("yiqilgan/skip/xato:\n    " + "\n    ".join(errors[:50]))
    if len(passed) < minimum:
        bad.append(f"o'tgan testlar {len(passed)} < pastki chegara {minimum}")
    if done_success is not True:
        bad.append(f"reporter done.success={done_success}")
    for b in bad:
        print("XATO:", b)
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], int(sys.argv[2])))
