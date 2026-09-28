# -*- coding: utf-8 -*-
"""CI-darvozali staging deploy (`staging-deploy.yml`) — XULQ kafolatlari.

Bu yerda matn qidirilmaydi: workflow'dan HAQIQIY shell bo'laklari ajratib olinadi va
BAJARILADI. Sabab — nuqson aynan matn to'g'ri ko'ringan joyda yashiringan edi:

    case "$SHA" in
      [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;

izohda "40 belgili o'n oltilik" deb yozilgan, amalda esa FAQAT birinchi 8 belgi
tekshirilardi. Qolgan 32 tasi ixtiyoriy bo'lardi — jumladan qo'shtirnoq, ya'ni
quyidagi heredoc'dagi JSON tanasini buzish mumkin edi. Matn testi buni TUTMASDI.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

SERVER = pathlib.Path(__file__).resolve().parents[1]
ROOT = SERVER.parent.parent
WF = ROOT / ".github" / "workflows" / "staging-deploy.yml"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash kerak")


def _step_run(name_fragment: str) -> str:
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    steps = data["jobs"]["deploy"]["steps"]
    hit = [s for s in steps if name_fragment in str(s.get("name", ""))]
    assert hit, "qadam topilmadi: %s" % name_fragment
    return hit[0]["run"]


def _slice(run: str, start: str, end: str) -> str:
    i = run.index(start)
    j = run.index(end, i)
    return run[i:j]


def _run_sha_guard(sha: str, tmp_path) -> subprocess.CompletedProcess:
    """Workflow'dagi AYNAN tekshiruv bo'lagi, berilgan qiymat bilan bajariladi.

    ⚠️  Qiymat skriptga MATN sifatida QO'YILMAYDI, MUHIT o'zgaruvchisi orqali beriladi.
        Birinchi variantda `SHA="%s"` deb yozilgan edi va aynan tekshirilishi kerak
        bo'lgan in'ektsiya yuki (ichida qo'shtirnoq bor) shell satrini UZIB yuborardi:
        bash sintaksis xatosi bilan yiqilardi, test esa "rad etildi" deb YASHIL
        bo'lardi — ya'ni qo'riqchi umuman sinalmagan holda o'tib ketardi.
    """
    run = _step_run("SHA ni aniqlash")
    guard = _slice(run, 'case "$SHA" in', 'echo "sha=$SHA"')
    script = tmp_path / "guard.sh"
    script.write_text('SHA="$TEST_SHA"\n%s\necho ACCEPTED\n' % guard,
                      encoding="utf-8", newline="\n")
    import os
    env = dict(os.environ, TEST_SHA=sha)
    return subprocess.run(["bash", str(script)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


GOOD = "0123456789abcdef0123456789abcdef01234567"


def test_haqiqiy_sha_QABUL_qilinadi(tmp_path):
    r = _run_sha_guard(GOOD, tmp_path)
    assert r.returncode == 0 and "ACCEPTED" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("bad, nega", [
    # ⚠️  ASOSIY REGRESSIYA: 8 ta o'n oltilik + qo'shtirnoqli axlat, uzunligi AYNAN 40.
    ('0123456789abcdef", "x": "aaaaaaaaaaaaaa', "qo'shtirnoq bilan JSON in'ektsiyasi"),
    ("0123456789abcdef0123456789abcdef0123456z", "oxirida o'n oltilik bo'lmagan belgi"),
    ("ZZZZZZZZ0123456789abcdef0123456789abcdef", "boshida o'n oltilik bo'lmagan belgi"),
    ("0123456789abcdef0123456789abcdef0123456", "39 belgi"),
    ("0123456789abcdef0123456789abcdef012345678", "41 belgi"),
    ("0123456789ABCDEF0123456789ABCDEF01234567", "katta harf (git kichik harf beradi)"),
    ("", "bo'sh"),
    ("$(id)", "buyruq almashtirish shakli"),
])
def test_yaroqsiz_sha_RAD_etiladi(bad, nega, tmp_path):
    r = _run_sha_guard(bad, tmp_path)
    assert r.returncode != 0, "%s — QABUL QILINDI: %r\n%s" % (nega, bad, r.stdout)
    assert "ACCEPTED" not in r.stdout, nega


def test_uzunligi_40_bolgan_INEKTSIYA_aynan_shu_testda_tutiladi(tmp_path):
    """Regressiya qo'riqchisi: uzunlik tekshiruvi YOLG'IZ yetarli emasligini qadab qo'yadi."""
    payload = '0123456789abcdef", "x": "aaaaaaaaaaaaaa'
    assert len(payload) == 39
    r = _run_sha_guard(payload + "a", tmp_path)   # aniq 40 belgi
    assert r.returncode != 0, "40 belgili in'ektsiya o'tib ketdi"


def test_xato_xabari_SHA_qiymatini_jurnalga_chiqarmaydi():
    """Jurnal ochiq repoda LOGINSIZ o'qiladi — hujumchi bergan satr u yerga yozilmasin."""
    run = _step_run("SHA ni aniqlash")
    guard = _slice(run, 'case "$SHA" in', 'echo "sha=$SHA"')
    for ln in guard.splitlines():
        if "::error::" in ln:
            assert "$SHA" not in ln, "xato xabari SHA qiymatini chiqarmoqda: %s" % ln.strip()


def test_darvoza_sharti_UCH_qismdan_iborat():
    """Yoqilganlik + CI xulosasi + hodisa turi — uchalasi ham bo'lishi shart."""
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    cond = " ".join(str(data["jobs"]["deploy"]["if"]).split())
    assert "vars.STAGING_DEPLOY_ENABLED == 'true'" in cond
    assert "github.event.workflow_run.conclusion == 'success'" in cond
    assert "github.event_name == 'workflow_dispatch'" in cond


def test_token_buyruq_satriga_va_jurnalga_chiqmaydi():
    run = _step_run("Railway")
    assert "-d @payload.json" in run, "so'rov tanasi faylga yozilmayapti"
    assert "set -x" not in run, "`set -x` tokenni jurnalga chiqaradi"
    for ln in run.splitlines():
        if "echo" in ln:
            assert "RAILWAY_TOKEN" not in ln or "-n " in ln, (
                "token echo qilinmoqda: %s" % ln.strip())
