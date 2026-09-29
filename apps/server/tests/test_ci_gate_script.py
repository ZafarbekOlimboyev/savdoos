# -*- coding: utf-8 -*-
"""`scripts/ci/verify_main_ci_green.py` — staging deploy darvozasining XULQ testlari.

Nega bu fayl bor: darvoza ilgari `staging-deploy.yml` ichida, YAML blok-skalyari sifatida
yashagan. Unday mantiqni faqat MATN bilan tekshirish mumkin, matn testi esa chetlab
o'tishni TUTMAYDI. Bu repoda aynan shunday bo'lgan ikki marta:
  · `test_encrypt_evidence.py` shifr TEKSHIRUVI butunlay olib tashlanganda ham 7/7 yashil
    qolgan (u `"tekshirildi" in stdout` ni, ya'ni `echo` matnini tekshirardi);
  · SHA naqshi `[0-9a-f]` ni sakkiz marta sanab `*` bilan tugardi va 40 belgili
    in'ektsiya o'tib ketardi — matn testi buni ko'rmagan.

Shu bois darvoza SKRIPTGA ko'chirildi va bu yerda HAQIQATAN bajariladi: har negativ
holat uchun skript nol bo'lmagan kod qaytarishi VA sababni aytishi talab qilinadi.
Testlarning tishi borligi mutatsiya bilan isbotlanadi (pastdagi `mutatsiya` testlari).
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
CI_WF = ROOT / ".github" / "workflows" / "ci.yml"

SHA = "e60c213a446caf0c8e845bd9caa50113aad0e194"
OTHER = "d916b9b1b4291ec500372a6c7d062f175d8f8815"


def _required():
    sys.path.insert(0, str(ROOT / "scripts" / "ci"))
    import verify_main_ci_green as m
    return m.required_jobs(str(CI_WF))


def _run(runs, tmp_path, jobs=None, sha=SHA, tip=SHA, ci_wf=None, paginate=False):
    rp = tmp_path / "runs.json"
    if paginate:
        # `gh api --paginate` sahifalarni KETMA-KET yozadi: {..}{..}
        half = len(runs) // 2
        rp.write_text(json.dumps({"workflow_runs": runs[:half]})
                      + json.dumps({"workflow_runs": runs[half:]}), encoding="utf-8")
    else:
        rp.write_text(json.dumps({"workflow_runs": runs}), encoding="utf-8")
    argv = [sys.executable, str(SCRIPT), "--sha", sha, "--main-tip", tip,
            "--runs", str(rp), "--ci-workflow", str(ci_wf or CI_WF)]
    if jobs is not None:
        jp = tmp_path / "jobs.json"
        jp.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        argv += ["--jobs", str(jp)]
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))


def _run_row(**kw):
    row = {"id": 1, "name": "CI", "event": "push", "head_branch": "main",
           "head_sha": SHA, "status": "completed", "conclusion": "success",
           "created_at": "2026-09-29T17:28:48Z"}
    row.update(kw)
    return row


def _jobs(names, **override):
    out = []
    for i, n in enumerate(names):
        j = {"name": n, "status": "completed", "conclusion": "success", "id": 100 + i}
        if n in override:
            j.update(override[n])
        out.append(j)
    return out


# ═══ POZITIV ════════════════════════════════════════════════════════════════

def test_POZITIV_main_push_yashil_va_hamma_job_yashil(tmp_path):
    r = _run([_run_row()], tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DARVOZA OCHIQ" in r.stdout


def test_POZITIV_sahifalangan_javob_ham_oqiladi(tmp_path):
    """Bitta SHA'da 100 dan ko'p run bo'lishi mumkin (qayta yurgizishlar). Dalil
    IKKINCHI sahifada bo'lsa ham topilishi kerak — aks holda darvoza jimgina
    "run topilmadi" deb rad etardi."""
    rows = [_run_row(id=i, name="Uptime", event="schedule") for i in range(5)]
    rows.append(_run_row(id=99))          # haqiqiy dalil — oxirida
    r = _run(rows, tmp_path, jobs=_jobs(_required()), paginate=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_POZITIV_ci_proof_run_YONIDA_bolsa_ham_otadi(tmp_path):
    """`ci-proof` run'i mavjudligi o'zi to'smaydi — u faqat DALIL sifatida qabul
    qilinmaydi. main-push run'i yashil bo'lsa darvoza ochiq."""
    rows = [_run_row(id=1, head_branch="ci-proof/p8-release-safety"), _run_row(id=2)]
    r = _run(rows, tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 0, r.stdout + r.stderr


# ═══ NEGATIV ════════════════════════════════════════════════════════════════

def test_NEGATIV_FAQAT_ci_proof_dalili_RAD_etiladi(tmp_path):
    """Eng muhim negativ holat: aynan shu SHA `ci-proof/**` da yashil, LEKIN
    `main` ga push bo'lgan CI run'i YO'Q. Bu kod main'da sinalmagan."""
    rows = [_run_row(head_branch="ci-proof/p8-release-safety")]
    r = _run(rows, tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 1, r.stdout
    assert "ci-proof" in (r.stdout + r.stderr)


@pytest.mark.parametrize("bad", [
    {"conclusion": "failure"},
    {"conclusion": "cancelled"},
    {"conclusion": "skipped"},
    {"conclusion": "neutral"},
    {"conclusion": "timed_out"},
    {"conclusion": "action_required"},
    {"conclusion": None, "status": "in_progress"},
    {"conclusion": None, "status": "queued"},
])
def test_NEGATIV_main_run_yashil_EMAS(bad, tmp_path):
    r = _run([_run_row(**bad)], tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 1, "%s qabul qilindi: %s" % (bad, r.stdout)
    assert "YASHIL EMAS" in (r.stdout + r.stderr)


def test_NEGATIV_bir_nechta_main_run_bittasi_yiqilgan(tmp_path):
    """Qayta yurgizish: ikki main-push run, biri yiqilgan -> RAD.
    (Eng yangisiga qarab qaror qilish yiqilgan qayta yurgizishni yashirardi.)"""
    rows = [_run_row(id=1, conclusion="failure", created_at="2026-09-29T17:28:48Z"),
            _run_row(id=2, conclusion="success", created_at="2026-09-29T18:00:00Z")]
    r = _run(rows, tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 1, r.stdout
    assert "YASHIL EMAS" in (r.stdout + r.stderr)


def test_NEGATIV_ESKIRGAN_SHA_rad_etiladi(tmp_path):
    """`workflow_dispatch` ham bundan o'tmaydi — nishon main tepasi bo'lishi shart."""
    r = _run([_run_row()], tmp_path, jobs=_jobs(_required()), sha=SHA, tip=OTHER)
    assert r.returncode == 1, r.stdout
    assert "tepasi" in (r.stdout + r.stderr)


@pytest.mark.parametrize("bad_sha", [
    "0123456789abcdef0123456789abcdef0123456z",
    "0123456789abcdef",
    "0123456789ABCDEF0123456789ABCDEF01234567",
    '0123456789abcdef", "x": "aaaaaaaaaaaaaa',
])
def test_NEGATIV_notogri_SHA_rad_etiladi(bad_sha, tmp_path):
    r = _run([_run_row()], tmp_path, jobs=_jobs(_required()), sha=bad_sha, tip=bad_sha)
    assert r.returncode == 1, "%r qabul qilindi" % bad_sha


def test_NEGATIV_kerakli_job_YOQ(tmp_path):
    need = _required()
    r = _run([_run_row()], tmp_path, jobs=_jobs(need[:-1]))
    assert r.returncode == 1, r.stdout
    assert "YO'Q" in (r.stdout + r.stderr)
    assert need[-1] in (r.stdout + r.stderr)


@pytest.mark.parametrize("concl,status", [
    ("failure", "completed"), ("cancelled", "completed"),
    ("skipped", "completed"), (None, "in_progress"),
])
def test_NEGATIV_kerakli_job_yashil_EMAS(concl, status, tmp_path):
    need = _required()
    jobs = _jobs(need, **{need[0]: {"conclusion": concl, "status": status}})
    r = _run([_run_row()], tmp_path, jobs=jobs)
    assert r.returncode == 1, "%s/%s qabul qilindi: %s" % (concl, status, r.stdout)
    assert "YASHIL EMAS" in (r.stdout + r.stderr)


def test_NEGATIV_birorta_CI_run_yoq(tmp_path):
    r = _run([_run_row(name="Uptime", event="schedule")], tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 1, r.stdout
    assert "TOPILMADI" in (r.stdout + r.stderr) or "YO'Q" in (r.stdout + r.stderr)


def test_NEGATIV_boshqa_SHA_dagi_run_dalil_EMAS(tmp_path):
    r = _run([_run_row(head_sha=OTHER)], tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 1, r.stdout


def test_NEGATIV_ci_yml_job_nomlari_oqilmasa_RAD(tmp_path):
    """Kerakli ro'yxat bo'sh chiqsa darvoza JIMGINA bo'shashmasligi kerak."""
    fake = tmp_path / "bosh-ci.yml"
    fake.write_text("name: CI\non:\n  push:\njobs:\n", encoding="utf-8")
    r = _run([_run_row()], tmp_path, jobs=_jobs(_required()), ci_wf=fake)
    assert r.returncode == 1, r.stdout
    assert "ishonchsiz" in (r.stdout + r.stderr) or "o'qilmadi" in (r.stdout + r.stderr)


# ═══ MUTATSIYA — testlarning TISHI borligini isbotlash ══════════════════════
#
# Har mutatsiya skriptdan bitta himoyani olib tashlaydi (NUSXADA — repo fayli
# TEGILMAYDI) va yuqoridagi negativ holat o'sha nusxada QABUL qilinishini ko'rsatadi.
# Ya'ni test haqiqatan shu himoyani qo'riqlaydi.

def _mutate(tmp_path, old, new):
    src = SCRIPT.read_text(encoding="utf-8")
    assert old in src, "mutatsiya nishoni topilmadi: %r" % old[:60]
    p = tmp_path / "mutant.py"
    p.write_text(src.replace(old, new, 1), encoding="utf-8", newline="\n")
    return p


def _run_mutant(mutant, runs, tmp_path, jobs=None, sha=SHA, tip=SHA):
    rp = tmp_path / "m_runs.json"
    rp.write_text(json.dumps({"workflow_runs": runs}), encoding="utf-8")
    argv = [sys.executable, str(mutant), "--sha", sha, "--main-tip", tip,
            "--runs", str(rp), "--ci-workflow", str(CI_WF)]
    if jobs is not None:
        jp = tmp_path / "m_jobs.json"
        jp.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        argv += ["--jobs", str(jp)]
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))


def test_MUTATSIYA_main_branch_sharti_olib_tashlansa_ci_proof_OTIB_ketadi(tmp_path):
    m = _mutate(tmp_path,
                'main = [r for r in pushes if r.get("head_branch") == "main"]',
                'main = list(pushes)')
    r = _run_mutant(m, [_run_row(head_branch="ci-proof/p8-release-safety")],
                    tmp_path, jobs=_jobs(_required()))
    assert r.returncode == 0, ("mutant HAM rad etdi — test `main` shartini "
                               "qo'riqlamayapti: %s" % (r.stdout + r.stderr))


def test_MUTATSIYA_eskirganlik_tekshiruvi_olib_tashlansa_ESKI_SHA_OTADI(tmp_path):
    m = _mutate(tmp_path, "    if sha != tip:", "    if False:")
    r = _run_mutant(m, [_run_row()], tmp_path, jobs=_jobs(_required()), tip=OTHER)
    assert r.returncode == 0, ("mutant HAM rad etdi — eskirganlik testi "
                               "qo'riqlamayapti: %s" % (r.stdout + r.stderr))


def test_MUTATSIYA_job_tekshiruvi_olib_tashlansa_YIQILGAN_job_OTADI(tmp_path):
    m = _mutate(tmp_path, "    if bad:\n        _fail(\"kerakli job(lar) YASHIL EMAS",
                "    if False:\n        _fail(\"kerakli job(lar) YASHIL EMAS")
    need = _required()
    jobs = _jobs(need, **{need[0]: {"conclusion": "failure"}})
    r = _run_mutant(m, [_run_row()], tmp_path, jobs=jobs)
    assert r.returncode == 0, ("mutant HAM rad etdi — job testi qo'riqlamayapti: %s"
                               % (r.stdout + r.stderr))


def test_MUTATSIYA_sahifalash_olib_tashlansa_IKKINCHI_sahifa_YOQOLADI(tmp_path):
    """`_load` faqat birinchi sahifani o'qisa, dalil ikkinchi sahifada bo'lgan
    holat "run topilmadi" bo'lib rad etiladi."""
    m = _mutate(tmp_path, "    out, dec, i = [], json.JSONDecoder(), 0",
                "    return (json.loads(raw.split('}{')[0] + '}') if '}{' in raw "
                "else json.loads(raw)).get(key) or []\n    out, dec, i = [], json.JSONDecoder(), 0")
    rp = tmp_path / "p_runs.json"
    rows_a = [_run_row(id=1, name="Uptime", event="schedule")]
    rows_b = [_run_row(id=99)]
    rp.write_text(json.dumps({"workflow_runs": rows_a}) + json.dumps({"workflow_runs": rows_b}),
                  encoding="utf-8")
    jp = tmp_path / "p_jobs.json"
    jp.write_text(json.dumps({"jobs": _jobs(_required())}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(m), "--sha", SHA, "--main-tip", SHA,
                        "--runs", str(rp), "--jobs", str(jp), "--ci-workflow", str(CI_WF)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(ROOT))
    assert r.returncode == 1, ("mutant o'tib ketdi — sahifalash testi hech narsani "
                               "qo'riqlamayapti: %s" % (r.stdout + r.stderr))
