# -*- coding: utf-8 -*-
"""RELEASE SAFETY — bajariladigan sintetik darvoza sinovlari (YAML substring EMAS).

staging-deploy.yml ichidagi HAQIQIY python darvoza bloki git'dan sug'urib olinadi va
sintetik `workflow_runs` fixture'lariga qarshi BAJARILADI. Qo'shimcha: GitHub Actions
`if:`/skipped-step semantikasi simulyatsiyasi (o'tkazib yuborilgan qadam chiqishi = bo'sh
satr) — deploy shartiga ta'siri.

KUTILGAN NATIJA (nuqson isboti):
  · MAIN_SHA (e60c213a, joriy origin/main): ci-proof yashil run VAKOLAT BERADI (B4 teshigi
    OCHIQ) va dispatch yo'lida freshness qadami O'TKAZIB YUBORILib deploy sharti ROST
    bo'ladi -> invariant sinovlari QIZIL.
  · P81_SHA (38f1d750): ikkala invariant ham YASHIL (tuzatilgan).

Ishga tushirish: repo ichida  pytest qa/audit-2026-09-30/synthetic/test_release_gate_sim.py
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

REPO = os.environ.get("QA_REPO", r"C:\Users\Developer\Desktop\savdoOS")
MAIN_SHA = "e60c213a446caf0c8e845bd9caa50113aad0e194"   # joriy origin/main
P81_SHA = "38f1d750d1ea9d65a397d13b5c1648054a1d5312"    # p8.1-release-gate-fixes

GOOD_SHA = "a" * 40


def _yaml(sha: str) -> str:
    return subprocess.run(
        ["git", "-C", REPO, "show", f"{sha}:.github/workflows/staging-deploy.yml"],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _gate_python(sha: str) -> str:
    """`Bu SHA uchun CI HAQIQATAN yashilmi` qadamidagi python heredoc'ini oladi."""
    y = _yaml(sha)
    body = y.split("CI HAQIQATAN yashilmi", 1)[1]
    blk = body.split("python - <<'PY'", 1)[1]
    blk = blk.split("\n          PY", 1)[0]
    return textwrap.dedent(blk)


def _run_gate(sha: str, runs: list[dict], tmpdir) -> subprocess.CompletedProcess:
    """Darvoza kodini sintetik runs bilan bajaradi. Eski nusxa runs.json (bitta JSON),
    yangi nusxa runs.jsonl (qator-json) o'qiydi — ikkalasini ham yozamiz."""
    code = _gate_python(sha)
    (tmpdir / "runs.json").write_text(json.dumps({"workflow_runs": runs}), encoding="utf-8")
    (tmpdir / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in runs), encoding="utf-8")
    return subprocess.run([sys.executable, "-c", code], cwd=tmpdir,
                          env={**os.environ, "SHA": GOOD_SHA, "PYTHONIOENCODING": "utf-8"},
                          capture_output=True, text=True, encoding="utf-8")


def _mk_run(branch="main", event="push", conclusion="success", status="completed"):
    return {"id": 1, "name": "CI", "event": event, "head_branch": branch,
            "head_sha": GOOD_SHA, "status": status, "conclusion": conclusion,
            "created_at": "2026-09-30T00:00:00Z", "run_started_at": "2026-09-30T00:00:00Z"}


# ══ INVARIANT 1 (B4): ci-proof yashil run deploy VAKOLATINI BERMASLIGI SHART ═══════════

@pytest.mark.parametrize("sha", [MAIN_SHA, P81_SHA], ids=["main-e60c213a", "p8.1-38f1d750"])
def test_ciproof_green_run_must_not_authorize(sha, tmp_path):
    p = _run_gate(sha, [_mk_run(branch="ci-proof/pos-store-4")], tmp_path)
    assert p.returncode != 0, (
        f"B4 BYPASS: {sha[:8]} nusxasi ci-proof/** dagi yashil CI run bilan deploy'ga "
        f"VAKOLAT BERDI (rc=0, stdout={p.stdout[-200:]!r})")


# ══ INVARIANT 2: main'dagi push yashil run — vakolat BERADI (musbat nazorat) ═══════════

@pytest.mark.parametrize("sha", [MAIN_SHA, P81_SHA], ids=["main-e60c213a", "p8.1-38f1d750"])
def test_green_main_push_authorizes(sha, tmp_path):
    p = _run_gate(sha, [_mk_run()], tmp_path)
    assert p.returncode == 0, f"{sha[:8]}: sog'lom yashil main run rad etildi: {p.stderr[-300:]}"


# ══ INVARIANT 3: tugamagan/qizil run deploy'ni TO'XTATADI ══════════════════════════════

@pytest.mark.parametrize("sha", [MAIN_SHA, P81_SHA], ids=["main-e60c213a", "p8.1-38f1d750"])
@pytest.mark.parametrize("bad", [
    dict(status="in_progress", conclusion=None),
    dict(conclusion="failure"),
    dict(conclusion="cancelled"),
    dict(conclusion="skipped"),
], ids=["pending", "failure", "cancelled", "skipped"])
def test_incomplete_or_red_run_blocks(sha, bad, tmp_path):
    p = _run_gate(sha, [_mk_run(**bad)], tmp_path)
    assert p.returncode != 0, (
        f"{sha[:8]}: {bad} holatidagi CI run deploy'ni TO'XTATMADI")


# ══ INVARIANT 4: dispatch yo'lida freshness darvozasi ISHLASHI SHART ═══════════════════
# GitHub semantikasi: `if:` yolg'on bo'lgan qadam O'TKAZIB YUBORILADI va uning har qanday
# chiqishi KEYINGI ifodalarda BO'SH SATR bo'ladi. Deploy qadami sharti:
#   steps.fresh.outputs.stale != 'true'
# Bo'sh satr != 'true'  ->  ROST  ->  deploy DAVOM ETADI.

def _fresh_step_if(sha: str) -> str | None:
    y = _yaml(sha)
    seg = y.split("id: fresh", 1)
    head = seg[0].rsplit("- name:", 1)[1] + "id: fresh" + seg[1].split("env:", 1)[0]
    for line in head.splitlines():
        s = line.strip()
        if s.startswith("if:"):
            return s[3:].strip()
    return None


@pytest.mark.parametrize("sha", [MAIN_SHA, P81_SHA], ids=["main-e60c213a", "p8.1-38f1d750"])
def test_dispatch_path_runs_freshness_gate(sha):
    cond = _fresh_step_if(sha)
    # `github.event_name != 'workflow_dispatch'` sharti bo'lsa — dispatch'da qadam SKIP,
    # stale chiqishi bo'sh, deploy sharti ('' != 'true') ROST bo'lib DAVOM ETADI.
    skipped_on_dispatch = cond is not None and "!= 'workflow_dispatch'" in cond.replace('"', "'")
    stale_output = "" if skipped_on_dispatch else "false"
    deploy_runs = stale_output != "true"          # aynan YAMLdagi shart semantikasi
    freshness_enforced = not skipped_on_dispatch
    assert freshness_enforced and deploy_runs, (
        f"{sha[:8]}: dispatch yo'lida freshness qadami SKIP (if: {cond!r}) — "
        f"stale='' bo'lib deploy sharti ROST, main'da bo'lmagan SHA ham deploy bo'ladi")
