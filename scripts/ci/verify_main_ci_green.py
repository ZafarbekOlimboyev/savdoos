#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Staging deploy DARVOZASI — «bu SHA `main` tepasi va CI'si TO'LIQ yashilmi?»

Nega alohida skript: darvoza mantiqi workflow YAML'i ichida yashaganda uni faqat MATN
bilan tekshirish mumkin edi. Matn testi chetlab o'tishni TUTMAYDI — bu repoda allaqachon
shunday bo'lgan. Mantiq bu yerda bo'lgani uchun ijro etiladigan POZITIV va NEGATIV testlar
yozish mumkin, va mutatsiya bilan ularning tishi borligini isbotlash mumkin.

Ishlatish (ikki fazada, chunki job'lar run id'siz olinmaydi):

    # 1) run darajasi — nomzod run id'larini chiqaradi
    gh api --paginate "repos/$REPO/actions/runs?head_sha=$SHA&per_page=100" > runs.json
    python scripts/ci/verify_main_ci_green.py \\
        --sha "$SHA" --main-tip "$TIP" --runs runs.json

    # 2) HAR BIR nomzod run uchun job'lar olinadi va to'liq tekshiriladi
    python scripts/ci/verify_main_ci_green.py \\
        --sha "$SHA" --main-tip "$TIP" --runs runs.json --jobs jobs-1.json --jobs jobs-2.json

Exit: 0 = darvoza OCHIQ · 1 = RAD ETILDI (sabab stderr'da) · 2 = foydalanish xatosi.

QAT'IY QOIDALAR (har biri ijro etiladigan test bilan qadab qo'yilgan):
  · Workflow AYNAN fayl yo'li bo'yicha tanilади (`path`), ko'rsatiladigan NOMI bo'yicha EMAS.
    Nom o'zgaruvchan va noyob emas — shu nomli ikkinchi workflow vakolat bera olardi.
  · Dalil FAQAT `main` branchiga PUSH bo'lgan run'dan olinadi. `ci-proof/**` run'i —
    DALIL EMAS, garchi u aynan shu SHA'da yashil bo'lsa ham.
  · Shu SHA'dagi HAR BIR main-push run `completed` + `success` bo'lishi shart
    (qayta yurgizishlardan biri yiqilgan bo'lsa — RAD).
  · `in_progress`, `queued`, `cancelled`, `skipped`, `neutral`, `timed_out`,
    `action_required`, `failure`, `null` — hammasi RAD.
  · Kerakli job ro'yxati `ci.yml` DAN o'qiladi, qo'lda yozilmaydi.
    FAIL-CLOSED: nomsiz job, dublikat nom, bo'sh ro'yxat yoki o'qib bo'lmaslik — RAD.
  · Job darajasi HAR BIR nomzod run uchun tekshiriladi, faqat oxirgisi uchun emas:
    aks holda shartli qilib o'chirilgan («skipped») majburiy job run xulosasini
    `success` qoldirgancha darvozadan o'tib ketardi.
  · Nishon SHA `main` tepasi bo'lishi SHART — `workflow_dispatch` ham bundan o'tmaydi.
    Eski holatga qaytish ATAYLAB bu yo'l orqali emas: `deploymentRollback` Railway'dagi
    TAYYOR image'ni ishlatadi va CI'ni umuman chetlab o'tmaydi.
  · Sahifalash: `gh api --paginate` bir nechta JSON obyektini KETMA-KET yozadi; hammasi
    birlashtiriladi, aks holda 100 dan keyingi dalil jimgina yo'qolardi.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

OK_STATUS = "completed"
OK_CONCL = "success"
DEFAULT_CI_PATH = ".github/workflows/ci.yml"


def _fail(msg):
    print("::error::" + msg, file=sys.stderr)
    raise SystemExit(1)


def _load(path: str, key: str) -> list:
    """`gh api --paginate` chiqishini o'qiydi — bir nechta sahifa bo'lsa ham.

    ⚠️  Bir sahifadan ko'p bo'lganda fayl `{...}{...}` ko'rinishida bo'ladi va oddiy
        `json.load` "Extra data" bilan yiqiladi. Shu bois ketma-ket dekodlanadi va
        barcha sahifalarning `key` massivlari BIRLASHTIRILADI.
    """
    p = pathlib.Path(path)
    if not p.exists():
        _fail("dalil fayli topilmadi: %s" % path)
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    out, dec, i = [], json.JSONDecoder(), 0
    while i < len(raw):
        while i < len(raw) and raw[i] in " \t\r\n":
            i += 1
        if i >= len(raw):
            break
        try:
            obj, i = dec.raw_decode(raw, i)
        except ValueError as e:
            _fail("dalil faylini o'qib bo'lmadi (%s): %s" % (path, e))
        if isinstance(obj, list):
            out.extend(obj)
        elif isinstance(obj, dict):
            out.extend(obj.get(key) or [])
    return out


JOB_KEY = re.compile(r"""^\ \ (?:"(?P<q>[A-Za-z0-9_-]+)"|'(?P<s>[A-Za-z0-9_-]+)'|(?P<p>[A-Za-z0-9_-]+))\s*:(?P<rest>.*)$""")
NAME_LINE = re.compile(r"^    name:\s*(?P<v>.*)$")


def required_jobs(ci_workflow: str, min_jobs=None) -> list:
    r"""`ci.yml` dagi job nomlarini o'qiydi — qo'lda ro'yxat SAQLANMAYDI.

    YAML kutubxonasi ATAYLAB ishlatilmaydi: bu skript hech qanday qaramliksiz, CI
    o'rnatmasidan OLDIN ham yurishi kerak.

    ⚠️  NUQSON BOR EDI (fail-OPEN). Ilgari kalit naqshi `^  ([A-Za-z0-9_-]+):\s*$` edi
        va unga TUSHMAGAN qator JIMGINA e'tiborsiz qolardi. Ya'ni `  backend:  # izoh`
        yoki `  "backend":` deb yozilgan job kerakli ro'yxatdan chiqib ketardi; keyin
        o'sha job `if: false` bilan o'chirilsa, run xulosasi `success` qolardi va
        darvoza OCHILARDI. Quyidagi uchta fail-closed tekshiruv ham yordam bermasdi,
        chunki ular faqat naqshga TUSHGAN joblarni ko'rardi.

    Endi qoida teskari: jobs bloki ichidagi 2 bo'shliqli HAR QANDAY qator tanilishi
    SHART. Tanilmasa — RAD. «Tushunmadim» hech qachon «ruxsat» degani emas.
    """
    p = pathlib.Path(ci_workflow)
    if not p.exists():
        _fail("ci.yml topilmadi: %s — darvoza ishonchsiz, RAD ETILDI." % ci_workflow)
    text = p.read_text(encoding="utf-8")

    lines = text.replace("\r\n", "\n").split("\n")
    in_jobs = False
    jobs = []          # [[kalit, nom|None]]
    cur = None
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        # Yuqori daraja: `jobs:` blokiga kirish/chiqish
        if re.match(r"^[A-Za-z0-9_'\"-]+\s*:", raw):
            in_jobs = raw.split(":", 1)[0].strip().strip("'\"") == "jobs"
            cur = None
            continue
        if not in_jobs:
            continue

        indent = len(raw) - len(raw.lstrip())
        if indent == 2:
            m = JOB_KEY.match(raw)
            if not m:
                _fail("`jobs:` ichidagi qator TANILMADI: %r — kerakli job ro'yxati "
                      "ishonchsiz bo'ladi, RAD ETILDI." % raw)
            rest = (m.group("rest") or "").strip()
            if rest and not rest.startswith("#"):
                _fail("job kalitidan keyin o'qib bo'lmaydigan qiymat: %r — flow-mapping "
                      "yoki anchor bo'lishi mumkin, RAD ETILDI." % raw)
            cur = m.group("q") or m.group("s") or m.group("p")
            jobs.append([cur, None])
            continue

        if cur is not None and indent == 4:
            n = NAME_LINE.match(raw)
            if n:
                val = n.group("v").strip()
                if val in ("|", ">", "|-", ">-", "") or val.startswith(("|", ">", "&", "*")):
                    _fail("job `%s` ning `name:` i ko'p qatorli yoki havola (%r) — "
                          "ishonchli o'qib bo'lmaydi, RAD ETILDI." % (cur, val))
                jobs[-1][1] = val.strip('"').strip("'")
            elif raw.strip().startswith("strategy:"):
                jobs[-1].append("matrix?")

    if not jobs:
        _fail("`%s` dan birorta job o'qilmadi — darvoza ishonchsiz, RAD ETILDI." % ci_workflow)

    unnamed = [k for k, n, *_ in jobs if not n]
    if unnamed:
        _fail("job(lar)da `name:` YO'Q: %s. Job nomi bo'lmasa kerakli job ro'yxati "
              "ishonchsiz bo'ladi — RAD ETILDI (jimgina tushirib qoldirilmaydi)."
              % ", ".join(unnamed))

    # Matritsali job: API job nomiga matritsa qiymatini qo'shadi (`Nom (x)`), ya'ni
    # bu yerdagi nom bilan MOS KELMAYDI. Jimgina «job yo'q» deyish o'rniga aniq rad.
    matrix = [k for k, _n, *rest in jobs if rest]
    if matrix:
        _fail("job(lar)da `strategy:` bor: %s. Matritsali job nomlari API'da "
              "kengaytiriladi va bu ro'yxat bilan mos kelmaydi — RAD ETILDI." % ", ".join(matrix))

    names = [n for _k, n, *_ in jobs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        _fail("job nomlari TAKRORLANGAN: %s — qaysi job majburiy ekani noaniq, RAD ETILDI."
              % ", ".join(dupes))

    # Pol: kerakli ro'yxatni QISQARTIRISH uchun endi ikkinchi fayl ham tahrirlanishi kerak.
    if min_jobs is not None and len(names) < int(min_jobs):
        _fail("kerakli job soni kutilganidan KAM: %d < %d — `ci.yml` qisqartirilgan "
              "bo'lishi mumkin, RAD ETILDI." % (len(names), int(min_jobs)))
    return names


def candidate_runs(runs: list, sha: str, ci_path: str) -> list:
    """Vakolat berishi MUMKIN bo'lgan run'lar: aynan shu SHA, aynan shu workflow FAYLI,
    `push` hodisasi, `main` branchi. Ularning HAMMASI yashil bo'lishi shart."""
    same = [r for r in runs if r.get("head_sha") == sha]
    mine = [r for r in same if r.get("path") == ci_path]
    if not mine:
        paths = sorted({str(r.get("path")) for r in same})
        _fail("Bu SHA uchun `%s` workflow run'i TOPILMADI. Topilgan yo'llar: %s. "
              "Workflow KO'RSATILADIGAN NOMI bo'yicha tanilmaydi — faqat fayl yo'li."
              % (ci_path, ", ".join(paths) if paths else "(yo'q)"))
    pushes = [r for r in mine if r.get("event") == "push"]
    main = [r for r in pushes if r.get("head_branch") == "main"]
    if not main:
        br = sorted({"%s/%s" % (r.get("event"), r.get("head_branch")) for r in mine})
        _fail("Bu SHA uchun `main` ga PUSH bo'lgan run YO'Q. Topilgani: %s. "
              "`ci-proof/**` run'i dalil sifatida QABUL QILINMAYDI." % ", ".join(br))
    bad = [r for r in main
           if r.get("status") != OK_STATUS or r.get("conclusion") != OK_CONCL]
    if bad:
        detail = "; ".join("run %s: status=%s conclusion=%s"
                           % (r.get("id"), r.get("status"), r.get("conclusion"))
                           for r in bad)
        _fail("main-push run'lari YASHIL EMAS (%d ta): %s" % (len(bad), detail))
    main.sort(key=lambda r: str(r.get("run_started_at") or r.get("created_at") or ""))
    return main


def check_jobs(jobs: list, need: list, run_ids: list) -> None:
    """Job darajasi — HAR BIR nomzod run uchun.

    Run xulosasi `success` bo'la turib majburiy job `skipped` bo'lishi MUMKIN (shartli
    qilib o'chirilgan job run'ni qizil qilmaydi). Shu bois job darajasi alohida
    tekshiriladi, va faqat oxirgi run uchun emas — aks holda yiqilgan qayta-yurgizish
    yashil qo'shnisi ortida yashirinib qolardi.
    """
    by_run = {}
    for j in jobs:
        by_run.setdefault(str(j.get("run_id")), []).append(j)

    missing_runs = [str(r) for r in run_ids if str(r) not in by_run]
    if missing_runs:
        _fail("quyidagi nomzod run(lar) uchun job dalili BERILMAGAN: %s — "
              "tekshirilmagan run darvozadan o'tkazilmaydi." % ", ".join(missing_runs))

    problems = []
    for rid in run_ids:
        group = by_run[str(rid)]
        by_name = {}
        for j in group:
            by_name.setdefault(j.get("name"), []).append(j)
        for n in need:
            if n not in by_name:
                problems.append("run %s: kerakli job YO'Q — %s" % (rid, n))
                continue
            for j in by_name[n]:
                if j.get("status") != OK_STATUS or j.get("conclusion") != OK_CONCL:
                    problems.append("run %s: %s (status=%s, conclusion=%s)"
                                    % (rid, n, j.get("status"), j.get("conclusion")))
    if problems:
        _fail("kerakli job tekshiruvi RAD ETDI: %s" % "; ".join(problems))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    ap.add_argument("--main-tip", required=True,
                    help="`main` ning HOZIRGI tepasi; SHA undan farq qilsa RAD.")
    ap.add_argument("--runs", required=True)
    ap.add_argument("--jobs", action="append", default=None,
                    help="Nomzod run'larning job dalili. Bir nechta marta berilishi mumkin. "
                         "Berilmasa faqat run darajasi tekshiriladi va id'lar chiqariladi.")
    ap.add_argument("--ci-workflow", default=DEFAULT_CI_PATH,
                    help="Kerakli job ro'yxati O'QILADIGAN fayl.")
    ap.add_argument("--expect-path", default=DEFAULT_CI_PATH,
                    help="Run'ning `path` maydoni AYNAN shunday bo'lishi kerak.")
    ap.add_argument("--min-jobs", type=int, default=None,
                    help="Kerakli job soni shundan KAM bo'lsa RAD. `ci.yml` ni "
                         "qisqartirish uchun ikkinchi fayl ham tahrirlanishi kerak bo'ladi.")
    a = ap.parse_args(argv)

    sha, tip = a.sha.strip().lower(), a.main_tip.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        _fail("SHA 40 belgili o'n oltilik bo'lishi kerak.")
    if not re.fullmatch(r"[0-9a-f]{40}", tip):
        _fail("--main-tip 40 belgili o'n oltilik bo'lishi kerak.")
    if sha != tip:
        _fail("Nishon SHA `main` tepasi EMAS (sha=%s tip=%s) — RAD ETILDI. "
              "Eskiroq holatga qaytish `deploymentRollback` bilan qilinadi." % (sha, tip))

    need = required_jobs(a.ci_workflow, a.min_jobs)
    runs = candidate_runs(_load(a.runs, "workflow_runs"), sha, a.expect_path)
    ids = [r.get("id") for r in runs]
    print("nomzod main-push run: %s" % ", ".join(str(i) for i in ids))
    print("kerakli job: %d ta" % len(need))

    if a.jobs is None:
        print("run_ids=%s" % ",".join(str(i) for i in ids))
        return 0

    jobs = []
    for f in a.jobs:
        jobs.extend(_load(f, "jobs"))
    check_jobs(jobs, need, ids)
    print("DARVOZA OCHIQ: %d run × %d kerakli job — hammasi yashil" % (len(ids), len(need)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
