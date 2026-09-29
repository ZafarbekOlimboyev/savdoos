#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Staging deploy DARVOZASI — «bu SHA main'ga push qilingan va CI'si to'liq yashilmi?»

Nega alohida skript: darvoza mantiqi workflow YAML'i ichida yashaganda uni faqat matn
bilan tekshirish mumkin edi — ya'ni `grep` bilan. Matn testi chetlab o'tishni TUTMAYDI
(bu repoda allaqachon shunday bo'lgan: `test_encrypt_evidence.py` shifr tekshiruvi
butunlay olib tashlanganda ham yashil qolgan). Mantiq bu yerda — demak ijro etiladigan
POZITIV va NEGATIV testlar yozish mumkin, va mutatsiya bilan ularning tishi borligini
isbotlash mumkin.

Ishlatish (workflow ichida):
    gh api --paginate "repos/$REPO/actions/runs?head_sha=$SHA&per_page=100" > runs.json
    gh api --paginate "repos/$REPO/actions/runs/$RUN/jobs?per_page=100"      > jobs.json
    python scripts/ci/verify_main_ci_green.py \
        --sha "$SHA" --main-tip "$TIP" --runs runs.json --ci-workflow .github/workflows/ci.yml
  (`--jobs` berilmasa, skript kerakli run id'ni chiqaradi va chaqiruvchi uni oladi.)

Exit: 0 = darvoza OCHIQ · 1 = RAD ETILDI (sabab stderr'da) · 2 = foydalanish xatosi.

QAT'IY QOIDALAR (har biri test bilan qadab qo'yilgan):
  · Dalil FAQAT `main` branchiga PUSH bo'lgan `CI` run'idan olinadi.
    `ci-proof/**` run'i — DALIL EMAS, garchi u aynan shu SHA'da yashil bo'lsa ham.
  · Shu SHA'dagi HAR BIR main-push `CI` run'i `completed` + `success` bo'lishi shart
    (qayta yurgizish yiqilgan bo'lsa — rad).
  · `in_progress`, `queued`, `cancelled`, `skipped`, `neutral`, `timed_out`,
    `action_required`, `failure`, `null` — hammasi RAD.
  · Kerakli job ro'yxati `ci.yml` DAN o'qiladi, qo'lda yozilmaydi: job nomi o'zgarsa
    ro'yxat o'zi yangilanadi va darvoza jimgina bo'shashmaydi.
  · Har bir kerakli job `completed` + `success` bo'lishi shart; yo'q job — RAD.
  · Nishon SHA `main` tepasi bo'lishi shart (eskirgan yoki begona SHA — RAD).
  · Sahifalash: `runs.json`/`jobs.json` bir nechta sahifa massivi bo'lishi mumkin.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

OK_STATUS = "completed"
OK_CONCL = "success"


def _fail(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print("::error::" + msg, file=sys.stderr)
    raise SystemExit(1)


def _load(path: str, key: str) -> list:
    """`gh api --paginate` bir nechta JSON obyektini KETMA-KET yozadi.

    ⚠️  Bir sahifadan ko'p bo'lsa fayl `{...}{...}` ko'rinishida bo'ladi va oddiy
        `json.load` "Extra data" bilan yiqiladi. Shu bois ketma-ket dekodlanadi va
        barcha sahifalarning `key` massivlari BIRLASHTIRILADI. Ilgari bu yerda
        `per_page=100` bilan bitta sahifa o'qilardi — 100 dan ko'p run bo'lsa
        dalil jimgina yo'qolardi.
    """
    raw = pathlib.Path(path).read_text(encoding="utf-8").strip()
    if not raw:
        return []
    out, dec, i = [], json.JSONDecoder(), 0
    while i < len(raw):
        while i < len(raw) and raw[i] in " \t\r\n":
            i += 1
        if i >= len(raw):
            break
        obj, i = dec.raw_decode(raw, i)
        if isinstance(obj, list):
            out.extend(obj)
        elif isinstance(obj, dict):
            out.extend(obj.get(key) or [])
    return out


def required_jobs(ci_workflow: str) -> list[str]:
    """`ci.yml` dagi job `name:` larini o'qiydi — qo'lda ro'yxat SAQLANMAYDI.

    YAML kutubxonasi ishlatilmaydi: bu skript `ci.yml` ni CI'dan OLDIN, hech qanday
    qaramliksiz yurishi kerak. Naqsh ataylab tor: ikki bo'shliq chekinish (job kaliti)
    va undan keyingi `name:`.
    """
    text = pathlib.Path(ci_workflow).read_text(encoding="utf-8")
    names, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            cur = m.group(1)
            continue
        if cur is not None:
            n = re.match(r"^    name:\s*(.+?)\s*$", line)
            if n:
                val = n.group(1).strip().strip('"').strip("'")
                names.append(val)
                cur = None
    if not names:
        _fail("ci.yml dan birorta job nomi o'qilmadi — darvoza ishonchsiz, RAD ETILDI.")
    return names


def pick_main_run(runs: list, sha: str) -> dict:
    ci = [r for r in runs if r.get("name") == "CI" and r.get("head_sha") == sha]
    if not ci:
        _fail("Bu SHA uchun birorta `CI` run TOPILMADI.")
    pushes = [r for r in ci if r.get("event") == "push"]
    main = [r for r in pushes if r.get("head_branch") == "main"]
    if not main:
        branches = sorted({str(r.get("head_branch")) for r in ci})
        _fail("Bu SHA uchun `main` branchiga PUSH bo'lgan `CI` run YO'Q. "
              "Topilgan branchlar: %s. `ci-proof/**` run'i dalil sifatida QABUL "
              "QILINMAYDI." % ", ".join(branches))
    bad = [r for r in main
           if r.get("status") != OK_STATUS or r.get("conclusion") != OK_CONCL]
    if bad:
        detail = "; ".join("run %s: status=%s conclusion=%s"
                           % (r.get("id"), r.get("status"), r.get("conclusion"))
                           for r in bad)
        _fail("main-push `CI` run'lari YASHIL EMAS (%d ta): %s" % (len(bad), detail))
    main.sort(key=lambda r: str(r.get("run_started_at") or r.get("created_at") or ""))
    return main[-1]


def check_jobs(jobs: list, need: list[str], run_id) -> None:
    by_name = {}
    for j in jobs:
        by_name.setdefault(j.get("name"), []).append(j)
    missing = [n for n in need if n not in by_name]
    if missing:
        _fail("run %s da kerakli job(lar) YO'Q: %s" % (run_id, ", ".join(missing)))
    bad = []
    for n in need:
        for j in by_name[n]:
            if j.get("status") != OK_STATUS or j.get("conclusion") != OK_CONCL:
                bad.append("%s(status=%s, conclusion=%s)"
                           % (n, j.get("status"), j.get("conclusion")))
    if bad:
        _fail("kerakli job(lar) YASHIL EMAS: %s" % ", ".join(bad))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    ap.add_argument("--main-tip", required=True,
                    help="`main` ning HOZIRGI tepasi; SHA undan farq qilsa RAD.")
    ap.add_argument("--runs", required=True)
    ap.add_argument("--jobs", default=None,
                    help="Berilmasa faqat run tanlanadi va id chiqariladi.")
    ap.add_argument("--ci-workflow", default=".github/workflows/ci.yml")
    a = ap.parse_args(argv)

    sha, tip = a.sha.strip().lower(), a.main_tip.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        _fail("SHA 40 belgili o'n oltilik bo'lishi kerak.")
    if not re.fullmatch(r"[0-9a-f]{40}", tip):
        _fail("--main-tip 40 belgili o'n oltilik bo'lishi kerak.")
    if sha != tip:
        # ⚠️  `workflow_dispatch` ham BUNDAN o'tmaydi. Eski SHA'ni qo'lda deploy qilish
        #     yo'li ATAYLAB yopiq: qaytarish `deploymentRollback` bilan qilinadi, u
        #     Railway'dagi TAYYOR image'ni ishlatadi va CI'ni umuman chetlab o'tmaydi.
        _fail("Nishon SHA `main` tepasi EMAS (sha=%s tip=%s) — RAD ETILDI." % (sha, tip))

    need = required_jobs(a.ci_workflow)
    run = pick_main_run(_load(a.runs, "workflow_runs"), sha)
    print("main-push CI run: %s (branch=%s, status=%s/%s)"
          % (run.get("id"), run.get("head_branch"), run.get("status"), run.get("conclusion")))
    print("kerakli job: %d ta" % len(need))
    if a.jobs is None:
        print("run_id=%s" % run.get("id"))
        return 0
    check_jobs(_load(a.jobs, "jobs"), need, run.get("id"))
    print("DARVOZA OCHIQ: %d/%d kerakli job yashil" % (len(need), len(need)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
