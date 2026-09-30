# -*- coding: utf-8 -*-
"""`scripts/ci/verify_main_ci_green.py` — DARVOZA mantiqi, IJRO ETILADIGAN testlar.

Nega bu fayl bor: darvoza mantiqi workflow YAML'i ichida turganda uni faqat MATN bilan
tekshirish mumkin edi, matn testi esa chetlab o'tishni TUTMAYDI. Mantiq skriptga
ko'chirilgach — uni haqiqatan ishga tushirib, rad etishlarini kuzatish mumkin.

Oxirida MUTATSIYA testlari: skript ataylab buziladi va mos salbiy holat endi O'TIB
KETISHI ko'rsatiladi — ya'ni yuqoridagi testlarning tishi bor.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[1]
ROOT = SERVER.parent.parent
SCRIPT = ROOT / "scripts" / "ci" / "verify_main_ci_green.py"
REAL_CI = ROOT / ".github" / "workflows" / "ci.yml"
CI_PATH = ".github/workflows/ci.yml"

GOOD = "0123456789abcdef0123456789abcdef01234567"
OTHER = "f" * 40

SYNTH_CI = """name: CI

on:
  push:
    branches: [main, "ci-proof/**"]

jobs:
  alpha:
    name: Alpha job
    runs-on: ubuntu-latest
  beta:
    name: Beta job
    runs-on: ubuntu-latest
"""
NEED = ["Alpha job", "Beta job"]


# ── Yordamchilar ───────────────────────────────────────────────────────────

def _wf_run(rid=1, *, sha=GOOD, path=CI_PATH, event="push", branch="main",
            status="completed", conclusion="success") -> dict:
    return {"id": rid, "path": path, "event": event, "head_branch": branch,
            "head_sha": sha, "status": status, "conclusion": conclusion,
            "run_started_at": "2026-09-30T00:00:0%d" % (rid % 10)}


def _job(run_id, name, *, status="completed", conclusion="success") -> dict:
    return {"run_id": run_id, "name": name, "status": status, "conclusion": conclusion}


def _all_jobs(run_id, need=None) -> list:
    return [_job(run_id, n) for n in (need or NEED)]


def _gate(tmp_path, *, runs, jobs=None, sha=GOOD, tip=None, ci_yml=SYNTH_CI,
          expect_path=CI_PATH, mutate=None, runs_raw=None, min_jobs=None):
    """Skriptni HAQIQATAN ishga tushiradi. `jobs=None` -> faqat run darajasi."""
    (tmp_path / "runs.json").write_text(
        runs_raw if runs_raw is not None
        else json.dumps({"workflow_runs": runs}),
        encoding="utf-8", newline="\n")

    ci = tmp_path / "ci.yml"
    if ci_yml is not None:
        ci.write_text(ci_yml, encoding="utf-8", newline="\n")

    script = SCRIPT
    if mutate is not None:
        body = SCRIPT.read_text(encoding="utf-8")
        new = mutate(body)
        assert new != body, "mutatsiya hech narsani o'zgartirmadi — test ma'nosiz"
        script = tmp_path / "mutant.py"
        script.write_text(new, encoding="utf-8", newline="\n")

    argv = [sys.executable, str(script), "--sha", sha,
            "--main-tip", tip if tip is not None else sha,
            "--runs", "runs.json", "--ci-workflow", str(ci),
            "--expect-path", expect_path]
    if min_jobs is not None:
        argv += ["--min-jobs", str(min_jobs)]
    if jobs is not None:
        for idx, group in enumerate(jobs):
            f = tmp_path / ("jobs-%d.json" % idx)
            f.write_text(json.dumps({"jobs": group}), encoding="utf-8", newline="\n")
            argv += ["--jobs", f.name]
    return subprocess.run(argv, cwd=str(tmp_path), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _out(r) -> str:
    return (r.stdout or "") + (r.stderr or "")


# ── POZITIV ────────────────────────────────────────────────────────────────

def test_POZITIV_main_tepasi_va_toliq_yashil_CI_QABUL(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)])
    assert r.returncode == 0, _out(r)
    assert "DARVOZA OCHIQ" in _out(r)


def test_POZITIV_HAQIQIY_ci_yml_dan_8_ta_job_oqiladi(tmp_path):
    """Sintetik emas, repodagi ASL `ci.yml`. Job nomlari o'zgarsa bu test seziladi."""
    real = REAL_CI.read_text(encoding="utf-8")
    names = ["Backend (pytest)", "Backend (PostgreSQL 18 schema gate)",
             "Backend (production install has no tooling packages)",
             "Frontend (tsc)", "Frontend (komponent sinovlari)", "E2E (Playwright)",
             "Mobile (Flutter analyze + test)",
             "Mobile E2E (Flutter x real backend, PostgreSQL 18)"]
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1, names)], ci_yml=real)
    assert r.returncode == 0, _out(r)
    assert "kerakli job: 8 ta" in _out(r)


# ── NEGATIV: SHA va yangilik ───────────────────────────────────────────────

def test_NEGATIV_notogri_SHA_shakli(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], sha="qwerty")
    assert r.returncode != 0
    assert "o'n oltilik" in _out(r)


def test_NEGATIV_SHA_main_tepasi_EMAS(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)], sha=GOOD, tip=OTHER)
    assert r.returncode != 0
    assert "tepasi EMAS" in _out(r)


def test_NEGATIV_ESKI_main_SHA_si_ham_RAD(tmp_path):
    """Yashil, main'ga push bo'lgan, lekin ESKIRGAN commit ham o'tmaydi."""
    old = "a" * 40
    r = _gate(tmp_path, runs=[_wf_run(1, sha=old)], jobs=[_all_jobs(1)],
              sha=old, tip=GOOD)
    assert r.returncode != 0
    assert "tepasi EMAS" in _out(r)


# ── NEGATIV: run identifikatsiyasi ─────────────────────────────────────────

def test_NEGATIV_ci_proof_branchidagi_yashil_run_VAKOLAT_BERMAYDI(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1, branch="ci-proof/nimadir")])
    assert r.returncode != 0
    assert "ci-proof" in _out(r)


def test_NEGATIV_notogri_HODISA(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1, event="pull_request")])
    assert r.returncode != 0


def test_NEGATIV_notogri_workflow_YOLI(tmp_path):
    """Workflow KO'RSATILADIGAN NOMI bo'yicha tanilmaydi — faqat fayl yo'li."""
    r = _gate(tmp_path, runs=[_wf_run(1, path=".github/workflows/uptime.yml")])
    assert r.returncode != 0
    assert "TOPILMADI" in _out(r)


def test_NEGATIV_BOSHQA_SHA_dagi_run_hisobga_olinmaydi(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1, sha=OTHER)])
    assert r.returncode != 0


def test_NEGATIV_run_UMUMAN_YOQ(tmp_path):
    r = _gate(tmp_path, runs=[])
    assert r.returncode != 0


# ── NEGATIV: run holati/xulosasi ───────────────────────────────────────────

@pytest.mark.parametrize("status,concl", [
    ("in_progress", None), ("queued", None), ("completed", "cancelled"),
    ("completed", "skipped"), ("completed", "neutral"), ("completed", "timed_out"),
    ("completed", "action_required"), ("completed", "failure"), ("completed", None),
])
def test_NEGATIV_run_yashil_EMAS(tmp_path, status, concl):
    r = _gate(tmp_path, runs=[_wf_run(1, status=status, conclusion=concl)],
              jobs=[_all_jobs(1)])
    assert r.returncode != 0, "status=%s concl=%s o'tib ketdi" % (status, concl)
    assert "YASHIL EMAS" in _out(r)


def test_NEGATIV_QAYTA_YURGIZISHDA_bittasi_yiqilgan(tmp_path):
    """Ikkita main-push run: biri yashil, biri qizil. Yashili qizilini YOPMASIN."""
    r = _gate(tmp_path,
              runs=[_wf_run(1), _wf_run(2, conclusion="failure")],
              jobs=[_all_jobs(1), _all_jobs(2)])
    assert r.returncode != 0
    assert "YASHIL EMAS" in _out(r)


# ── NEGATIV: job darajasi ──────────────────────────────────────────────────

def test_NEGATIV_kerakli_job_YOQ(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[[_job(1, "Alpha job")]])
    assert r.returncode != 0
    assert "Beta job" in _out(r)


@pytest.mark.parametrize("concl", ["failure", "skipped", "cancelled", "timed_out", None])
def test_NEGATIV_kerakli_job_yashil_EMAS(tmp_path, concl):
    """`skipped` majburiy job run xulosasini `success` QOLDIRADI — aynan shu bo'shliq
    uchun job darajasi alohida tekshiriladi."""
    jobs = [_job(1, "Alpha job"), _job(1, "Beta job", conclusion=concl)]
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[jobs])
    assert r.returncode != 0, "job conclusion=%s o'tib ketdi" % concl
    assert "RAD ETDI" in _out(r)


def test_NEGATIV_job_royxati_BOSH(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[[]])
    assert r.returncode != 0


def test_NEGATIV_nomzod_run_uchun_job_dalili_BERILMAGAN(tmp_path):
    """Ikki nomzod run, job dalili faqat bittasi uchun — tekshirilmagani o'tmasin."""
    r = _gate(tmp_path, runs=[_wf_run(1), _wf_run(2)], jobs=[_all_jobs(1)])
    assert r.returncode != 0
    assert "BERILMAGAN" in _out(r)


def test_NEGATIV_IKKINCHI_run_da_job_yiqilgan(tmp_path):
    """Ikkala run ham run darajasida yashil, lekin ikkinchisining job'i skipped."""
    bad = [_job(2, "Alpha job"), _job(2, "Beta job", conclusion="skipped")]
    r = _gate(tmp_path, runs=[_wf_run(1), _wf_run(2)], jobs=[_all_jobs(1), bad])
    assert r.returncode != 0
    assert "run 2" in _out(r)


# ── NEGATIV: kerakli job ro'yxatini o'qish (FAIL-CLOSED) ───────────────────

def test_NEGATIV_ci_yml_YOQ(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], ci_yml=None)
    assert r.returncode != 0
    assert "topilmadi" in _out(r)


def test_NEGATIV_NOMSIZ_job_jimgina_TUSHIRILMAYDI(tmp_path):
    ci = SYNTH_CI + "  gamma:\n    runs-on: ubuntu-latest\n"
    r = _gate(tmp_path, runs=[_wf_run(1)], ci_yml=ci)
    assert r.returncode != 0
    assert "gamma" in _out(r)


def test_NEGATIV_DUBLIKAT_job_nomi(tmp_path):
    ci = SYNTH_CI + "  gamma:\n    name: Alpha job\n    runs-on: ubuntu-latest\n"
    r = _gate(tmp_path, runs=[_wf_run(1)], ci_yml=ci)
    assert r.returncode != 0
    assert "TAKRORLANGAN" in _out(r)


def test_NEGATIV_jobs_bolimi_BOSH(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], ci_yml="name: CI\non:\n  push:\njobs:\n")
    assert r.returncode != 0
    assert "birorta job o'qilmadi" in _out(r)


def test_on_bolimidagi_kalitlar_job_deb_OQILMAYDI(tmp_path):
    """`on:` ostidagi `  push:` 2 bo'shliqli kalit — u job emas. Aks holda qat'iy
    tekshiruv «nomsiz job» deb YOLG'ON rad berardi."""
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)])
    assert r.returncode == 0, _out(r)


# ── NEGATIV: sahifalash ────────────────────────────────────────────────────

def test_NEGATIV_SAHIFALASH_yiqilgan_run_ni_YASHIRA_OLMAYDI(tmp_path):
    """`gh api --paginate` sahifalarni KETMA-KET yozadi. Ikkinchi sahifadagi qizil
    run ham topilishi shart — aks holda dalil jimgina yo'qolardi."""
    p1 = json.dumps({"workflow_runs": [_wf_run(1)]})
    p2 = json.dumps({"workflow_runs": [_wf_run(2, conclusion="failure")]})
    r = _gate(tmp_path, runs=None, runs_raw=p1 + "\n" + p2, jobs=[_all_jobs(1), _all_jobs(2)])
    assert r.returncode != 0
    assert "YASHIL EMAS" in _out(r)


def test_SAHIFALASH_ikki_sahifadagi_yashil_run_lar_QABUL(tmp_path):
    p1 = json.dumps({"workflow_runs": [_wf_run(1)]})
    p2 = json.dumps({"workflow_runs": [_wf_run(2)]})
    r = _gate(tmp_path, runs=None, runs_raw=p1 + p2,
              jobs=[_all_jobs(1), _all_jobs(2)])
    assert r.returncode == 0, _out(r)


def test_NEGATIV_buzuq_dalil_fayli_FAIL_CLOSED(tmp_path):
    r = _gate(tmp_path, runs=None, runs_raw='{"workflow_runs": [ }')
    assert r.returncode != 0
    assert "o'qib bo'lmadi" in _out(r)


# ── MUTATSIYA: testlarning tishi bormi ─────────────────────────────────────

def test_MUTATSIYA_main_tepasi_shartini_olib_tashlash_TUTILADI(tmp_path):
    assert _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)],
                 sha=GOOD, tip=OTHER).returncode != 0
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)], sha=GOOD, tip=OTHER,
              mutate=lambda s: s.replace("if sha != tip:", "if False:"))
    assert r.returncode == 0, "mutatsiya darvozani ochmadi — salbiy test sezgir emas"


def test_MUTATSIYA_kerakli_job_tekshiruvini_olib_tashlash_TUTILADI(tmp_path):
    jobs = [[_job(1, "Alpha job"), _job(1, "Beta job", conclusion="skipped")]]
    assert _gate(tmp_path, runs=[_wf_run(1)], jobs=jobs).returncode != 0
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=jobs,
              mutate=lambda s: s.replace("    if problems:", "    if False:"))
    assert r.returncode == 0, "job tekshiruvi olib tashlansa ham rad etildi"


def test_MUTATSIYA_workflow_YOLI_tekshiruvini_olib_tashlash_TUTILADI(tmp_path):
    runs = [_wf_run(1, path=".github/workflows/uptime.yml")]
    assert _gate(tmp_path, runs=runs).returncode != 0
    r = _gate(tmp_path, runs=runs, jobs=[_all_jobs(1)],
              mutate=lambda s: s.replace(
                  'mine = [r for r in same if r.get("path") == ci_path]',
                  'mine = list(same)'))
    assert r.returncode == 0, "yo'l tekshiruvi olib tashlansa ham rad etildi"


def test_MUTATSIYA_SAHIFALASHNI_olib_tashlash_TUTILADI(tmp_path):
    """`_load` faqat BIRINCHI sahifani o'qiydigan qilinsa, ikkinchi sahifadagi qizil
    run ko'rinmay qoladi va darvoza ochilib ketadi."""
    p1 = json.dumps({"workflow_runs": [_wf_run(1)]})
    p2 = json.dumps({"workflow_runs": [_wf_run(2, conclusion="failure")]})
    raw = p1 + "\n" + p2
    assert _gate(tmp_path, runs=None, runs_raw=raw,
                 jobs=[_all_jobs(1), _all_jobs(2)]).returncode != 0
    r = _gate(tmp_path, runs=None, runs_raw=raw, jobs=[_all_jobs(1)],
              mutate=lambda s: s.replace("    while i < len(raw):", "    while i < 1:"))
    assert r.returncode == 0, "sahifalash olib tashlansa ham qizil run topildi"


def test_MUTATSIYA_NOMSIZ_job_fail_closed_ini_olib_tashlash_TUTILADI(tmp_path):
    ci = SYNTH_CI + "  gamma:\n    runs-on: ubuntu-latest\n"
    assert _gate(tmp_path, runs=[_wf_run(1)], ci_yml=ci).returncode != 0
    # Mutatsiya B ning ASL xulqini tiklaydi: nomsiz job ro'yxatga umuman kirmaydi,
    # ya'ni JIMGINA tushib qoladi va darvoza ochilib ketadi.
    def _silent_drop(src: str) -> str:
        src = src.replace("    if unnamed:", "    if False:")
        return src.replace("    names = [n for _k, n, *_ in jobs]",
                           "    names = [n for _k, n, *_ in jobs if n]")

    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)], ci_yml=ci,
              mutate=_silent_drop)
    assert r.returncode == 0, "nomsiz job jimgina tushirilmadi — test sezgir emas"


# ═══════════════════════════════════════════════════════════════════════════
# Q4 / BLOCKER — kerakli job ro'yxati parseri FAIL-OPEN edi
#
# Adversarial ko'rik buni HAQIQIY `ci.yml` da uchidan-uchiga isbotladi:
#   `  backend:  # TODO re-enable`  +  o'sha job'da `if: false`
#   -> job kerakli ro'yxatdan JIMGINA tushardi, run xulosasi `success` qolardi,
#      darvoza «kerakli job: 7 ta · DARVOZA OCHIQ» deb OCHILARDI.
#
# Endi qoida teskari: `jobs:` ichidagi 2 bo'shliqli HAR QANDAY qator tanilishi
# SHART. «Tushunmadim» hech qachon «ruxsat» degani emas.
# ═══════════════════════════════════════════════════════════════════════════

REAL_CI_NAMES = [
    "Backend (pytest)", "Backend (PostgreSQL 18 schema gate)",
    "Backend (production install has no tooling packages)",
    "Frontend (tsc)", "Frontend (komponent sinovlari)", "E2E (Playwright)",
    "Mobile (Flutter analyze + test)",
    "Mobile E2E (Flutter x real backend, PostgreSQL 18)",
]


def test_EKSPLUATATSIYA_izohli_job_kaliti_endi_RAD_etiladi(tmp_path):
    """Ko'rik ko'rsatgan AYNAN o'sha hujum, haqiqiy `ci.yml` ustida."""
    real = REAL_CI.read_text(encoding="utf-8")
    holed = real.replace("\n  backend:\n", "\n  backend:  # TODO re-enable\n", 1)
    assert holed != real, "haqiqiy ci.yml da `  backend:` topilmadi"
    # `backend` job'i o'chirilgan (skipped), qolgan 7 tasi yashil
    jobs = [_job(1, n) for n in REAL_CI_NAMES if n != "Backend (pytest)"]
    jobs.append(_job(1, "Backend (pytest)", conclusion="skipped"))
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[jobs], ci_yml=holed, min_jobs=8)
    assert r.returncode != 0, "izohli job kaliti hamon jimgina tushib qolmoqda"
    # Job ro'yxatdan TUSHMAYDI — u taniladi va o'chirilgani job DARAJASIDA tutiladi.
    assert "kerakli job: 8 ta" in _out(r), "job ro'yxati qisqargan: %s" % _out(r)
    assert "Backend (pytest)" in _out(r), _out(r)


@pytest.mark.parametrize("line,nega", [
    ("  gamma: {name: Gamma, runs-on: ubuntu-latest}\n", "flow-mapping"),
    ("  gamma: &base\n    name: Gamma\n", "anchor"),
    ("  gamma!:\n    name: Gamma\n", "yaroqsiz kalit"),
])
def test_PARSER_tanimagan_qatorda_FAIL_CLOSED(tmp_path, line, nega):
    r = _gate(tmp_path, runs=[_wf_run(1)], ci_yml=SYNTH_CI + line)
    assert r.returncode != 0, "%s jimgina o'tib ketdi" % nega


def test_PARSER_IZOHLI_kalit_TANILADI_tushib_qolmaydi(tmp_path):
    """Kalitdan keyingi izoh — oddiy YAML. U RAD etilmasin, lekin job ro'yxatdan ham
    TUSHIB QOLMASIN: aynan shu jimgina tushish fail-open teshigi edi."""
    ci = SYNTH_CI + "  gamma:  # keyinroq yoqiladi\n    name: Gamma job\n"
    jobs = [_job(1, n) for n in NEED + ["Gamma job"]]
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[jobs], ci_yml=ci)
    assert r.returncode == 0, _out(r)
    assert "kerakli job: 3 ta" in _out(r), "izohli job ro'yxatga kirmadi"


def test_PARSER_QOSHTIRNOQLI_kalit_TANILADI(tmp_path):
    """Qo'shtirnoqli kalit — oddiy YAML va GitHub uni qabul qiladi. U TANILISHI
    kerak (rad emas), aks holda yolg'on rad berардi."""
    ci = SYNTH_CI + '  "gamma":\n    name: Gamma job\n'
    jobs = [_job(1, n) for n in NEED + ["Gamma job"]]
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[jobs], ci_yml=ci)
    assert r.returncode == 0, _out(r)
    assert "kerakli job: 3 ta" in _out(r)


def test_PARSER_MATRITSALI_job_aniq_RAD_etiladi(tmp_path):
    """API matritsali job nomiga qiymat qo'shadi (`Nom (x)`) — bu ro'yxat bilan mos
    kelmaydi. Jimgina «job yo'q» o'rniga ANIQ sabab bilan rad."""
    ci = SYNTH_CI + "  gamma:\n    name: Gamma\n    strategy:\n      matrix:\n        v: [1, 2]\n"
    r = _gate(tmp_path, runs=[_wf_run(1)], ci_yml=ci)
    assert r.returncode != 0
    assert "strategy" in _out(r)


def test_PARSER_KOP_QATORLI_name_RAD_etiladi(tmp_path):
    ci = SYNTH_CI + "  gamma:\n    name: >\n      Gamma job\n"
    r = _gate(tmp_path, runs=[_wf_run(1)], ci_yml=ci)
    assert r.returncode != 0


def test_PARSER_CRLF_bilan_ham_ishlaydi(tmp_path):
    ci = SYNTH_CI.replace("\n", "\r\n")
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)], ci_yml=ci)
    assert r.returncode == 0, _out(r)


def test_PARSER_on_bolimi_job_deb_OQILMAYDI(tmp_path):
    """`on:` ostidagi `  push:` ham 2 bo'shliqli — u jobs blokida EMAS."""
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)])
    assert r.returncode == 0, _out(r)


# ── Pol: ro'yxatni qisqartirish uchun IKKINCHI fayl ham kerak ─────────────

def test_MIN_JOBS_poli_QISQARTIRISHNI_tutadi(tmp_path):
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1)], min_jobs=8)
    assert r.returncode != 0, "2 ta job 8 lik poldan o'tib ketdi"
    assert "KAM" in _out(r)


def test_MIN_JOBS_HAQIQIY_ci_yml_da_qanoatlanadi(tmp_path):
    real = REAL_CI.read_text(encoding="utf-8")
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=[_all_jobs(1, REAL_CI_NAMES)],
              ci_yml=real, min_jobs=8)
    assert r.returncode == 0, _out(r)


# ── MUTATSIYA: eski, bo'sh naqshni tiklash ────────────────────────────────

def test_MUTATSIYA_ESKI_bosh_naqshni_tiklash_TUTILADI(tmp_path):
    """Eski naqsh (`^  ([A-Za-z0-9_-]+):\\s*$`) tanimagan qatorni e'tiborsiz
    qoldirardi. Uni tiklasak — izohli kalit yana jimgina tushadi va darvoza ochiladi."""
    ci = SYNTH_CI.replace("  alpha:\n", "  alpha:  # izoh\n", 1)
    # `alpha` O'CHIRILGAN (skipped), `beta` yashil.
    evidence = [[_job(1, "Alpha job", conclusion="skipped"), _job(1, "Beta job")]]
    # Qat'iy parser: `alpha` ro'yxatda QOLADI (2 ta) -> o'chirilgani tutiladi.
    strict = _gate(tmp_path, runs=[_wf_run(1)], jobs=evidence, ci_yml=ci)
    assert strict.returncode != 0
    assert "kerakli job: 2 ta" in _out(strict), _out(strict)

    def _loose(src: str) -> str:
        i = src.index("        if indent == 2:")
        j = src.index("        if cur is not None and indent == 4:")
        loose = ('        if indent == 2:\n'
                 '            m = re.match(r"^  ([A-Za-z0-9_-]+):\\s*$", raw)\n'
                 '            if not m:\n'
                 '                continue\n'
                 '            cur = m.group(1)\n'
                 '            jobs.append([cur, None])\n'
                 '            continue\n\n')
        return src[:i] + loose + src[j:]

    # Bo'sh naqsh tiklansa `beta` JIMGINA tushadi (1 ta) va o'sha dalil bilan OCHILADI.
    r = _gate(tmp_path, runs=[_wf_run(1)], jobs=evidence, ci_yml=ci, mutate=_loose)
    assert r.returncode == 0, "bo'sh naqsh tiklansa ham rad etildi — test sezgir emas"
    assert "kerakli job: 1 ta" in _out(r), "mutatsiya ro'yxatni qisqartirmadi"
