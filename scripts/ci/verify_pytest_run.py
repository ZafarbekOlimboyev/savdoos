#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI: pytest HAQIQATAN ishladimi — yig'ish emas, BAJARILISH isboti (Phase 4A.1).

⚠️  NEGA EXIT KODI YETMAYDI. Backend CI 2026-09-11 dan 68f73ae gacha HAR commit'da
    «no tests ran» bilan qizil edi va buni hech kim sezmadi — ya'ni «qizil» signal
    ham ma'lumot bermadi. Teskari holat undan xavfliroq: pytest 0 bilan tugab, lekin
    to'plamning bir qismini ISHLATMASLIGI mumkin:
      · test tanasida `pytest.exit(..., returncode=0)` — sessiya yarmida TO'XTAYDI;
      · modul/conftest darajasidagi `pytest.skip(allow_module_level=True)` — butun
        katalog «1 skipped» bo'lib yashil o'tadi (tests/cash/conftest.py izohi);
      · `-k`/`--deselect`/`collect_ignore`/`pytest_collection_modifyitems` — modul
        yoki funksiya jimgina yo'qoladi;
      · `if dependency: def test_...` — shart bajarilmasa modul HECH NARSA yig'maydi.

Qoidalar — HAMMASI bajarilishi shart, aks holda exit 1:
  1. junit XML mavjud va o'qiladi (INTERNALERROR'da u umuman yozilmasligi mumkin);
  2. error va failure testcase'lar soni 0;
  3. HAR BIR statik test funksiyasi (AST: modul darajasi va undagi if/try/with/for
     bloklari, `Test*` sinf metodlari) junit'da O'Z modulida (classname = modul yoki
     modul.Sinf) kamida bitta testcase bilan uchraydi (nomi `fn` yoki `fn[...]`).
     ⚠️ SON EMAS, IDENTIFIKATSIYA (review): parametr/import qilingan nusxalar sonni
     to'ldirib, haqiqiy funksiya yo'qolganini yashirardi;
  4. modul/katalog darajasidagi (collection) skip — HECH QACHON kechirilmaydi;
  5. test darajasidagi har bir skip kutilgan-skip ro'yxatida (ANIQ id, yoki `glob:`
     bilan boshlanadigan shablon) va sabab bo'lagi mos;
  6. o'tgan (passed) testcase > 0;
  7. (`--pytest-log` berilsa) logda `_pytest.outcomes.Exit`, `Interrupted:`,
     `INTERNALERROR` yoki `N deselected` yo'q.

Ishlatish (apps/server ichida):
    python ../../scripts/ci/verify_pytest_run.py --junit pytest-junit.xml \
        --tests tests --allow tests/ci_expected_skips.txt --pytest-log pytest-output.log
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

_COMPOUND = tuple(t for t in (ast.If, ast.Try, getattr(ast, "TryStar", None), ast.With,
                              ast.AsyncWith, ast.For, ast.AsyncFor, ast.While) if t is not None)


def _is_fixture(fn: ast.AST) -> bool:
    for d in getattr(fn, "decorator_list", []):
        target = d.func if isinstance(d, ast.Call) else d
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "fixture":
            return True
    return False


def _is_test_fn(node: ast.AST) -> bool:
    return (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test") and not _is_fixture(node))


def _iter_test_defs(tree: ast.Module) -> list[tuple[str | None, str]]:
    """[(sinf yoki None, funksiya)] — modul darajasi va undagi if/try/with/for bloklari.

    Funksiya TANASIGA kirilmaydi (ichki yordamchi funksiya test emas).
    """
    out: list[tuple[str | None, str]] = []
    stack = list(tree.body)
    while stack:
        node = stack.pop(0)
        if _is_test_fn(node):
            out.append((None, node.name))
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("Test") and not any(
                    isinstance(b, ast.FunctionDef) and b.name == "__init__" for b in node.body):
                out.extend((node.name, b.name) for b in node.body if _is_test_fn(b))
        elif isinstance(node, _COMPOUND):
            for field in ("body", "orelse", "finalbody"):
                stack.extend(getattr(node, field, None) or [])
            for h in getattr(node, "handlers", None) or []:
                stack.extend(h.body)
    return out


def static_test_functions(tests_dir: pathlib.Path) -> dict[str, list[tuple[str | None, str]]]:
    """{"tests/x/test_y.py": [(sinf yoki None, funksiya), ...]}"""
    per: dict[str, list[tuple[str | None, str]]] = {}
    for p in sorted(tests_dir.rglob("*.py")):
        if "__pycache__" in p.parts or not (p.name.startswith("test_") or p.name.endswith("_test.py")):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        per[p.relative_to(tests_dir.parent).as_posix()] = _iter_test_defs(tree)
    return per


def static_test_count(tests_dir: pathlib.Path) -> tuple[int, dict[str, int]]:
    per = {k: len(v) for k, v in static_test_functions(tests_dir).items()}
    return sum(per.values()), per


def _reason_from_text(text: str) -> str:
    """Collection skip'da haqiqiy sabab faqat element MATNIDA: ('fayl', 2, 'Skipped: sabab')."""
    m = re.search(r"Skipped: (.*?)['\"]\)\s*$", text.strip(), re.S)
    return m.group(1) if m else text.strip()


def parse_junit(path: pathlib.Path) -> list[dict]:
    root = ET.parse(path).getroot()
    cases = []
    for tc in root.iter("testcase"):
        kind, msg = "passed", ""
        for child in tc:
            if child.tag in ("error", "failure"):
                kind, msg = child.tag, child.get("message") or (child.text or "")
                break
            if child.tag == "skipped":
                kind = "skipped"
                msg = child.get("message") or ""
                if msg in ("", "collection skipped"):
                    msg = _reason_from_text(child.text or "") or msg
        cid = tc.get("classname") or ""
        name = tc.get("name") or ""
        collection = cid == ""
        cases.append({"id": f"{cid}::{name}" if cid else name, "classname": cid,
                      "base": name.split("[", 1)[0], "kind": kind, "msg": msg.strip(),
                      "collection": collection})
    return cases


def load_allowlist(path: pathlib.Path | None) -> list[tuple[bool, str, str]]:
    """[(glob_mi, shablon_yoki_id, sabab_bo'lagi)]. Aniq id — standart (`[..]` literal)."""
    out: list[tuple[bool, str, str]] = []
    if path is None:
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#") or not raw.strip():
            continue
        pat, sep, reason = (x.strip() for x in raw.partition(" | "))
        if not sep or not pat or not reason:
            raise ValueError(f"kutilgan-skip qatori noto'g'ri (kerak: `id | sabab`): {raw!r}")
        is_glob = pat.startswith("glob:")
        out.append((is_glob, pat[len("glob:"):].strip() if is_glob else pat, reason))
    return out


def _matches(rule: tuple[bool, str, str], case: dict) -> bool:
    is_glob, pat, reason = rule
    hit = fnmatch.fnmatchcase(case["id"], pat) if is_glob else case["id"] == pat
    return hit and reason in case["msg"]


_LOG_MARKERS = (("_pytest.outcomes.Exit", "pytest.exit chaqirilgan — sessiya yarmida to'xtagan"),
                ("Interrupted:", "sessiya uzilgan"),
                ("INTERNALERROR", "pytest ichki xatosi"))


def verify(junit: pathlib.Path, tests_dir: pathlib.Path, allow: pathlib.Path | None,
           pytest_log: pathlib.Path | None = None) -> tuple[list[str], list[str]]:
    """(muammolar, hisobot_satrlari). Muammo bo'sh bo'lsa — bajarilish isbotlangan."""
    problems: list[str] = []
    report: list[str] = []
    defs = static_test_functions(tests_dir)
    static_total = sum(len(v) for v in defs.values())
    report.append(f"statik test funksiyalari: {static_total} ({len(defs)} fayl)")

    if pytest_log is not None:
        if not pytest_log.exists():
            problems.append(f"pytest logi yo'q: {pytest_log}")
        else:
            body = pytest_log.read_text(encoding="utf-8", errors="replace")
            for marker, why in _LOG_MARKERS:
                if marker in body:
                    problems.append(f"pytest logi: {why} (`{marker}`)")
            m = re.search(r"\b(\d+) deselected\b", body)
            if m:
                problems.append(f"pytest logi: {m.group(1)} ta test DESELECT qilingan")

    if not junit.exists():
        problems.append(f"junit XML yo'q: {junit} — pytest ichki xato bilan to'xtagan bo'lishi mumkin")
        return problems, report
    try:
        cases = parse_junit(junit)
    except ET.ParseError as e:
        problems.append(f"junit XML o'qilmadi: {e}")
        return problems, report

    counts = {k: sum(1 for c in cases if c["kind"] == k)
              for k in ("passed", "failure", "error", "skipped")}
    report.append(f"testcase: {len(cases)} | passed {counts['passed']} | failed {counts['failure']} "
                  f"| errors {counts['error']} | skipped {counts['skipped']}")
    if counts["error"] or counts["failure"]:
        bad = [c["id"] for c in cases if c["kind"] in ("error", "failure")][:15]
        problems.append(f"{counts['failure']} failure / {counts['error']} error: {bad}")
    if counts["passed"] == 0:
        problems.append("birorta ham test O'TMADI — to'plam bajarilmagan")

    seen = {(c["classname"], c["base"]) for c in cases if not c["collection"]}
    missing: list[str] = []
    for rel, fns in defs.items():
        dotted = rel[:-3].replace("/", ".")
        for cls, fn in fns:
            want_cls = dotted if cls is None else f"{dotted}.{cls}"
            if (want_cls, fn) not in seen:
                missing.append(f"{rel}::{cls + '::' if cls else ''}{fn}")
    report.append(f"junit'da topilmagan statik test funksiyalari: {len(missing)}")
    if missing:
        problems.append(f"{len(missing)} ta test funksiyasi junit'da YO'Q — bajarilmagan (sessiya "
                        f"to'xtagan, modul yo'qolgan yoki filtrlangan): {missing[:12]}")

    rules = load_allowlist(allow)
    used: set[int] = set()
    for c in cases:
        if c["kind"] != "skipped":
            continue
        if c["collection"]:
            problems.append(f"MODUL/KATALOG butunlay o'tkazib yuborildi: {c['id']} — {c['msg'][:160]} "
                            "(bunday skip ro'yxatga KIRITILMAYDI)")
            continue
        hit = next((i for i, r in enumerate(rules) if _matches(r, c)), None)
        if hit is None:
            problems.append(f"KUTILMAGAN skip: {c['id']} — {c['msg'][:160]}")
        else:
            used.add(hit)
            report.append(f"kutilgan skip: {c['id']} — {c['msg'][:120]}")
    for i, (_g, pat, reason) in enumerate(rules):
        if i not in used:
            report.append(f"(eslatma) kutilgan-skip ishlatilmadi: {pat} | {reason}")
    return problems, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="pytest bajarilishini junit bo'yicha isbotlaydi")
    ap.add_argument("--junit", required=True, type=pathlib.Path)
    ap.add_argument("--tests", required=True, type=pathlib.Path)
    ap.add_argument("--allow", type=pathlib.Path)
    ap.add_argument("--pytest-log", type=pathlib.Path)
    a = ap.parse_args(argv)
    problems, report = verify(a.junit, a.tests, a.allow, a.pytest_log)
    verdict = "BAJARILISH ISBOTLANDI" if not problems else "BAJARILISH ISBOTLANMADI"
    lines = [f"## pytest bajarilishi: {verdict}", ""] + [f"- {r}" for r in report]
    if problems:
        lines += ["", "### Muammolar"] + [f"- {p}" for p in problems]
    text = "\n".join(lines)
    print(text)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
