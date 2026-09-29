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


# ═══ Faza 2 talablari ═══════════════════════════════════════════════════════

def test_konkurent_deploylar_NAVBATGA_qoyiladi():
    """Ketma-ket ikki push -> ikki CI -> ikki deploy. Parallel ketsa Railway'ga ikki
    mutatsiya bir vaqtda boradi va OXIRGI TUGAGANI yutadi — bu eng yangi commit
    bo'lishi SHART EMAS, chunki CI davomiyligi 9-30 daqiqa orasida o'zgaradi."""
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    c = data.get("concurrency")
    assert c, "`concurrency` bloki YO'Q — deploy'lar parallel ketadi"
    assert c.get("group"), "concurrency guruhi nomlanmagan"
    assert c.get("cancel-in-progress") is False, (
        "yarim yo'ldagi deploy UZILADI: Railway mutatsiyasi yuborilgan bo'lsa deploy "
        "baribir davom etadi, lekin natija ko'rinmaydi")


def test_ESKIRGAN_nishon_deploy_QILINMAYDI():
    """Navbatning o'zi tartibni kafolatlamaydi — eski commit'ning CI'si kechroq tugab,
    yangisining ustiga tushishi mumkin. Shu bois tartibga emas, FAKTGA bog'lanadi."""
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    steps = data["jobs"]["deploy"]["steps"]
    fresh = [s for s in steps if s.get("id") == "fresh"]
    assert fresh, "eskirganlik tekshiruvi YO'Q"
    assert "commits/main" in str(fresh[0]["run"]), "main tepasi so'ralmayapti"
    dep = [s for s in steps if "Railway" in str(s.get("name", ""))][0]
    assert "steps.fresh.outputs.stale != 'true'" in str(dep.get("if", "")), (
        "deploy qadami eskirganlik natijasiga BOG'LANMAGAN")
    # B4: freshness ENDI IKKALA yo'lda ham ishlaydi.
    #
    # ⚠️  Ilgari bu yerda `workflow_dispatch` MUSTASNO ekanini tasdiqlaydigan
    #     satr turardi va u aynan TESHIKNI MUSTAHKAMLAB qo'ygan edi: qadam
    #     o'tkazib yuborilganda uning chiqishi BO'SH bo'ladi, deploy sharti esa
    #     `stale != 'true'` — bo'sh qiymat bunga MOS KELADI, ya'ni main'da hech
    #     qachon bo'lmagan SHA (masalan `ci-proof/**` dagi yashil commit) qo'lda
    #     staging'ga chiqarilardi. Eskiroq holatga qaytish — Railway'ning O'Z
    #     rollback mexanizmi (RELEASE_SAFETY_RUNBOOK.md §2.5).
    assert not fresh[0].get("if"), (
        "freshness qadami shartga bog'langan — o'tkazib yuborilgan qadamning "
        "bo'sh chiqishi `stale != 'true'` ni ROST qiladi va vakolatsiz SHA "
        "o'tib ketadi")
    assert "workflow_dispatch" in str(fresh[0]["run"]), (
        "qo'lda chaqiruvda eskirgan SHA uchun QATTIQ RAD yo'li yo'q")


def test_PRODUCTION_muhiti_HECH_QACHON_nishon_emas():
    """Bu workflow faqat staging'ni deploy qiladi. Production environment id yoki
    production servis id bu yerda UMUMAN bo'lmasligi kerak."""
    raw = WF.read_text(encoding="utf-8")
    PROD_ENV = "1d0edbf9-652e-44ae-b4ca-ca58d6c8106f"
    STAGING_ENV = "7eb2e84f-3c17-4dbb-b343-2b7a6df783fe"
    assert PROD_ENV not in raw, "PRODUCTION environment id workflow'da mavjud"
    assert STAGING_ENV in raw, "staging environment id yo'q — nishon noaniq"
    assert "savdoos-production" not in raw, "production URL'i workflow'da"
    # Muhit id'si o'zgaruvchidan emas, QATTIQ yozilgan bo'lsin: hodisa maydonidan
    # kelgan qiymat muhitni almashtira olmasin.
    data = yaml.safe_load(raw)
    dep = [s for s in data["jobs"]["deploy"]["steps"] if "Railway" in str(s.get("name", ""))][0]
    env = dep.get("env") or {}
    assert env.get("ENVIRONMENT_ID") == STAGING_ENV
    assert "github.event" not in str(env.get("ENVIRONMENT_ID", "")), (
        "muhit id'si hodisa maydonidan olinmoqda")


def test_GraphQL_tanasiga_faqat_TASDIQLANGAN_qiymatlar_tushadi():
    """So'rov tanasidagi uchala qiymat ham: ikkitasi konstanta, uchinchisi esa oldingi
    qadamda 40 belgili o'n oltilik deb TASDIQLANGAN SHA. Hodisa maydoni to'g'ridan-to'g'ri
    tushmasligi kerak — aks holda GraphQL in'ektsiyasi mumkin bo'lardi."""
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    dep = [s for s in data["jobs"]["deploy"]["steps"] if "Railway" in str(s.get("name", ""))][0]
    run = str(dep["run"])
    i = run.index("cat > payload.json")
    j = run.index("\nJSON\n", i)
    body = run[i:j]
    for bad in ("github.event", "inputs.", "${{"):
        assert bad not in body, "so'rov tanasiga tekshirilmagan qiymat tushmoqda: %s" % bad
    assert '"$SHA"' in body and '"$ENVIRONMENT_ID"' in body and '"$SERVICE_ID"' in body


# ═══════════════════════════════════════════════════════════════════════════
# B5 — HAQIQATAN BAJARILADIGAN salbiy testlar
#
# Auditda aniqlangan nuqson: darvozaning markaziy da'vosi — «qizil CI deploy
# qila olmaydi» — faqat MATN bilan tasdiqlanardi. `test_darvoza_sharti_UCH_
# qismdan_iborat` uchta substring borligini tekshiradi, ya'ni `&&` ni `||` ga
# almashtirsangiz ham YASHIL qolardi. Quyidagilar workflow'ning O'Z matnidan
# bo'lak ajratib olib, uni HAQIQATAN ishga tushiradi.
#
# Oxirida MUTATSIYA testlari bor: tekshiruv ataylab buziladi va salbiy holat
# endi O'TIB KETISHI ko'rsatiladi — ya'ni testlar haqiqatan sezgir.
# ═══════════════════════════════════════════════════════════════════════════
import json
import os
import sys


def _ci_script_text() -> str:
    """`CI HAQIQATAN yashilmi` qadamidagi python heredoc'ining AYNAN tanasi."""
    run = _step_run("CI HAQIQATAN yashilmi")
    i = run.index("python - <<'PY'") + len("python - <<'PY'")
    j = run.index("\nPY\n", i)
    return run[i:j].strip("\n") + "\n"


def _ci_check(tmp_path, runs, sha=GOOD, mutate=None) -> subprocess.CompletedProcess:
    body = _ci_script_text()
    if mutate:
        before = body
        body = mutate(body)
        assert body != before, "mutatsiya hech narsani o'zgartirmadi — test ma'nosiz"
    script = tmp_path / "ci_check.py"
    script.write_text(body, encoding="utf-8", newline="\n")
    (tmp_path / "runs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in runs), encoding="utf-8", newline="\n")
    env = dict(os.environ, SHA=sha)
    return subprocess.run([sys.executable, str(script)], cwd=str(tmp_path),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def _wf_run(conclusion="success", status="completed", branch="main",
            event="push", sha=GOOD, name="CI", rid=1) -> dict:
    return {"id": rid, "name": name, "event": event, "head_branch": branch,
            "head_sha": sha, "status": status, "conclusion": conclusion}


def _all(r: subprocess.CompletedProcess) -> str:
    return (r.stdout or "") + (r.stderr or "")


# ── Salbiy holatlar: deploy BLOKLANISHI shart ──────────────────────────────

def test_CI_YIQILGAN_bolsa_deploy_BLOKLANADI(tmp_path):
    r = _ci_check(tmp_path, [_wf_run(conclusion="failure")])
    assert r.returncode != 0, "qizil CI deploy'ga yo'l berdi"
    assert "YASHIL EMAS" in _all(r)


def test_CI_BEKOR_QILINGAN_bolsa_deploy_BLOKLANADI(tmp_path):
    r = _ci_check(tmp_path, [_wf_run(conclusion="cancelled")])
    assert r.returncode != 0, "bekor qilingan CI deploy'ga yo'l berdi"


def test_CI_HALI_TUGAMAGAN_bolsa_deploy_BLOKLANADI(tmp_path):
    r = _ci_check(tmp_path, [_wf_run(status="in_progress", conclusion=None)])
    assert r.returncode != 0, "tugamagan CI deploy'ga yo'l berdi"
    assert "TUGAMAGAN" in _all(r)


def test_CI_UMUMAN_YOQ_bolsa_deploy_BLOKLANADI(tmp_path):
    r = _ci_check(tmp_path, [])
    assert r.returncode != 0, "CI yo'q bo'lsa ham deploy'ga yo'l berildi"
    assert "TOPILMADI" in _all(r)


def test_CI_SKIPPED_bolsa_deploy_BLOKLANADI(tmp_path):
    """`skipped` — `success` EMAS. Majburiy tekshiruv o'tkazib yuborilgan bo'lsa
    (masalan concurrency navbatdagi run'ni bekor qilgan) vakolat berilmaydi."""
    r = _ci_check(tmp_path, [_wf_run(conclusion="skipped")])
    assert r.returncode != 0, "skipped CI deploy'ga yo'l berdi"


def test_FAQAT_ci_proof_dagi_yashil_CI_VAKOLAT_BERMAYDI(tmp_path):
    """B4 ning o'zagi: `ci.yml` `ci-proof/**` da ham ishlaydi, ya'ni u yerda yashil
    CI olish OSON. Bunday SHA main'ga hech qachon kirmagan bo'lishi mumkin."""
    r = _ci_check(tmp_path, [_wf_run(branch="ci-proof/nimadir")])
    assert r.returncode != 0, "ci-proof dagi yashil CI staging'ga vakolat berdi"
    assert "TOPILMADI" in _all(r)


def test_pull_request_hodisasidagi_CI_VAKOLAT_BERMAYDI(tmp_path):
    r = _ci_check(tmp_path, [_wf_run(event="pull_request")])
    assert r.returncode != 0


def test_BOSHQA_SHA_dagi_yashil_run_HISOBGA_OLINMAYDI(tmp_path):
    other = "f" * 40
    r = _ci_check(tmp_path, [_wf_run(sha=other)], sha=GOOD)
    assert r.returncode != 0
    assert "TOPILMADI" in _all(r)


def test_ARALASH_yashil_va_qizil_RAD_etiladi(tmp_path):
    r = _ci_check(tmp_path, [_wf_run(rid=1), _wf_run(rid=2, conclusion="failure")])
    assert r.returncode != 0, "bitta yashil run qizilini yopib ketdi"


def test_BOSHQA_workflow_ning_yashilligi_CI_orniga_otmaydi(tmp_path):
    r = _ci_check(tmp_path, [_wf_run(name="Uptime")])
    assert r.returncode != 0
    assert "TOPILMADI" in _all(r)


# ── Ijobiy holat ───────────────────────────────────────────────────────────

def test_YASHIL_main_push_CI_QABUL_qilinadi(tmp_path):
    r = _ci_check(tmp_path, [_wf_run()])
    assert r.returncode == 0, _all(r)
    assert "CI yashil" in _all(r)


def test_SAHIFALASH_uzun_royxatda_ham_CI_topiladi(tmp_path):
    """Ilgari bitta sahifa (`per_page=100`) o'qilardi va `Uptime` kuniga ~96 run
    qo'shgani uchun CI run ro'yxatdan tushib qolardi. Endi JSONL — chegara yo'q."""
    noise = [_wf_run(name="Uptime", rid=100 + i) for i in range(250)]
    r = _ci_check(tmp_path, noise + [_wf_run(rid=9999)])
    assert r.returncode == 0, _all(r)


# ── Freshness: qadamning O'Z shell matni bajariladi ────────────────────────

def _fresh(tmp_path, *, tip, sha=GOOD, event="workflow_run"):
    """`gh` chaqiruvi funksiya bilan almashtiriladi; qolgan hammasi workflow'ning
    AYNAN matni. Chiqish `GITHUB_OUTPUT` fayliga yoziladi va qaytariladi."""
    out = tmp_path / "gh_out"
    out.write_text("", encoding="utf-8", newline="\n")
    script = tmp_path / "fresh.sh"
    script.write_text(
        'gh() { echo "%s"; }\n%s\n' % (tip, _step_run("Nishon hali ham main tepasimi")),
        encoding="utf-8", newline="\n")
    env = dict(os.environ, SHA=sha, EVENT=event, REPO="o/r", GH_TOKEN="x",
               GITHUB_OUTPUT=str(out))
    r = subprocess.run(["bash", str(script)], cwd=str(tmp_path), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return r, out.read_text(encoding="utf-8")


def test_QOLDA_chaqiruvda_ESKIRGAN_SHA_QATTIQ_RAD_etiladi(tmp_path):
    """B4: ilgari bu qadam `workflow_dispatch` da O'TKAZIB YUBORILARDI va bo'sh
    chiqish `stale != 'true'` shartini ROST qilardi — main'da bo'lmagan SHA
    staging'ga chiqib ketardi."""
    r, out = _fresh(tmp_path, tip="a" * 40, sha=GOOD, event="workflow_dispatch")
    assert r.returncode != 0, "qo'lda chaqiruvda eskirgan/vakolatsiz SHA qabul qilindi"
    assert "main tepasi EMAS" in _all(r)
    assert "stale=" not in out, "rad etilgan holatda ham chiqish yozilgan"


def test_AVTOMATIK_yolda_ESKIRGAN_SHA_jimgina_SKIP(tmp_path):
    """Avtomatik yo'lda eskirish NORMAL: yangiroq commit uchun alohida run bor."""
    r, out = _fresh(tmp_path, tip="a" * 40, sha=GOOD, event="workflow_run")
    assert r.returncode == 0, _all(r)
    assert "stale=true" in out


def test_MAIN_TEPASI_bolsa_QABUL(tmp_path):
    r, out = _fresh(tmp_path, tip=GOOD, sha=GOOD, event="workflow_dispatch")
    assert r.returncode == 0, _all(r)
    assert "stale=false" in out


# ── Darvoza sharti: IFODA hisoblanadi, substring emas ──────────────────────

def _eval_gate(expr: str, *, enabled, event, ci_conclusion) -> bool:
    """`if:` ifodasini SHU stsenariy uchun hisoblaydi. Tanilmagan token kirsa
    `NameError` chiqadi va test yiqiladi — yangi, sinalmagan shart jimgina
    kirib qolmasin."""
    py = (" ".join(expr.split())
          .replace("&&", " and ").replace("||", " or ")
          .replace("vars.STAGING_DEPLOY_ENABLED", repr(enabled))
          .replace("github.event.workflow_run.conclusion", repr(ci_conclusion))
          .replace("github.event_name", repr(event)))
    return bool(eval(py, {"__builtins__": {}}, {}))  # noqa: S307 — ifoda repo'ning O'ZIDAN


def _gate_expr() -> str:
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    return str(data["jobs"]["deploy"]["if"])


def test_darvoza_IFODASI_togri_hisoblanadi():
    e = _gate_expr()
    assert _eval_gate(e, enabled="true", event="workflow_run", ci_conclusion="success")
    assert not _eval_gate(e, enabled="", event="workflow_run", ci_conclusion="success"), \
        "darvoza O'CHIQ bo'lsa ham job ishladi"
    assert not _eval_gate(e, enabled="false", event="workflow_run", ci_conclusion="success")
    assert not _eval_gate(e, enabled="true", event="workflow_run", ci_conclusion="failure"), \
        "qizil CI da job ishladi"
    assert not _eval_gate(e, enabled="true", event="workflow_run", ci_conclusion="cancelled")
    # Qo'lda chaqiruvda job ISHLAYDI, lekin vakolat qadamlarda tekshiriladi.
    assert _eval_gate(e, enabled="true", event="workflow_dispatch", ci_conclusion=None)


# ── MUTATSIYA: testlar haqiqatan sezgirmi ──────────────────────────────────

def test_MUTATSIYA_darvoza_va_ni_yoki_ga_almashtirish_TUTILADI():
    """`&&` -> `||` almashtirilsa darvoza O'CHIQ bo'lsa ham job ishlab ketadi.
    Substring testi buni TUTMAYDI, ifoda hisoblash esa tutadi."""
    e = _gate_expr()
    mutant = e.replace("&&", "||", 1)
    assert mutant != e
    assert not _eval_gate(e, enabled="", event="workflow_run", ci_conclusion="success")
    assert _eval_gate(mutant, enabled="", event="workflow_run", ci_conclusion="success"), \
        "mutatsiya xulqni o'zgartirmadi — bu test hech narsani isbotlamaydi"


def test_MUTATSIYA_qizil_CI_tekshiruvini_olib_tashlash_TUTILADI(tmp_path):
    bad = [_wf_run(conclusion="failure")]
    assert _ci_check(tmp_path, bad).returncode != 0
    r = _ci_check(tmp_path, bad, mutate=lambda s: s.replace("if bad:", "if False:"))
    assert r.returncode == 0, "mutatsiya deploy'ni ochmadi — salbiy test sezgir emas"


def test_MUTATSIYA_branch_filtrini_olib_tashlash_TUTILADI(tmp_path):
    proof = [_wf_run(branch="ci-proof/nimadir")]
    assert _ci_check(tmp_path, proof).returncode != 0
    r = _ci_check(tmp_path, proof,
                  mutate=lambda s: s.replace("and r.get('head_branch') == 'main'", ""))
    assert r.returncode == 0, "branch filtri olib tashlansa ham rad etildi — test noto'g'ri"


def test_MUTATSIYA_tugallanganlik_tekshiruvini_olib_tashlash_TUTILADI(tmp_path):
    """Tugallanmagan run'ning `conclusion` i `None` — u `bad` ga ham tushadi, ya'ni
    mutatsiyadan keyin ham RAD etiladi. Muhimi: ANIQ sabab yo'qoladi, ya'ni
    «hali tugamagan» yo'li haqiqatan alohida mavjud."""
    pend = [_wf_run(status="in_progress", conclusion=None)]
    assert "TUGAMAGAN" in _all(_ci_check(tmp_path, pend))
    r = _ci_check(tmp_path, pend, mutate=lambda s: s.replace("if pending:", "if False:"))
    assert "TUGAMAGAN" not in _all(r), "mutatsiya tugallanganlik yo'lini o'zgartirmadi"
