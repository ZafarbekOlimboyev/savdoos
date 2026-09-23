"""Flutter testlari HAQIQATAN bajarilganini isbotlaydi (`flutter test --reporter json`).

Exit kodiga ishonilmaydi (Phase 4A.1 saboqi: «no tests ran» oylar davomida sezilmadi).
Tekshiruvlar:
  * diskdagi HAR `test/**/*_test.dart` fayli yuklangan va unda kamida bitta test o'tgan;
  * hech bir test (yashirin yuklash/tearDownAll ham) yiqilmagan yoki `error` bermagan;
  * skip YO'Q;
  * bajarilgan testlar soni pastki chegaradan kam emas (include torayishi jim o'tmasin);
  * reporter `done` hodisasini `success: true` bilan yozgan.

Foydalanish: python verify_flutter_run.py flutter-test.jsonl <min_tests>
(`apps/mobile` papkasidan ishga tushiriladi — fayl yo'llari shunga nisbatan).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _rel(path: str) -> str:
    """Reporter suite yo'lini ABSOLYUT beradi (`C:/.../apps/mobile/test/x_test.dart`,
    `/home/runner/.../test/x_test.dart`) — diskdagi ro'yxat bilan solishtirish uchun
    joriy papkaga nisbatan yo'lga keltiramiz."""
    p = Path(path.replace("\\", "/"))
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            pass
    return p.as_posix()


def main(report: str, minimum: int) -> int:
    suites: dict[int, str] = {}
    tests: dict[int, dict] = {}
    passed_by_file: dict[str, int] = {}
    ok = failed = skipped = 0
    errors: list[str] = []
    done_success = None

    for raw in Path(report).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        e = json.loads(raw)
        kind = e.get("type")
        if kind == "suite":
            suites[e["suite"]["id"]] = _rel(e["suite"].get("path") or "")
        elif kind == "testStart":
            tests[e["test"]["id"]] = e["test"]
        elif kind == "error":
            t = tests.get(e.get("testID"), {})
            errors.append(f"{t.get('name', '?')}: {str(e.get('error'))[:300]}")
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
            ok += 1
            passed_by_file[path] = passed_by_file.get(path, 0) + 1
        elif kind == "done":
            done_success = e.get("success")

    on_disk = sorted(p.as_posix() for p in Path("test").rglob("*_test.dart"))
    not_run = [f for f in on_disk if passed_by_file.get(f, 0) == 0]

    for f in on_disk:
        print(f"  {passed_by_file.get(f, 0):4d}  {f}")
    print(f"flutter tests: passed={ok} failed={failed} skipped={skipped} files={len(on_disk)} "
          f"done.success={done_success}")

    bad = []
    if not on_disk:
        bad.append("diskda test fayli topilmadi — tekshiruv ma'nosiz")
    if not_run:
        bad.append(f"BAJARILMAGAN test fayllari: {not_run}")
    if failed or skipped or errors:
        bad.append("yiqilgan/skip/xato:\n    " + "\n    ".join(errors[:50]))
    if ok < minimum:
        bad.append(f"bajarilgan testlar {ok} < pastki chegara {minimum}")
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
