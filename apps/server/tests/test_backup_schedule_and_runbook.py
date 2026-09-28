# -*- coding: utf-8 -*-
"""Backup mashqi JADVALI va deploy runbook'i — TUZILISH kafolatlari (F5–F9).

NEGA BU FAYL: `tests/cash/test_artifact_restore.py` artefaktdan tiklashning XATTI-HARAKATINI
sinaydi (bash + gpg + pgserver kerak, CI'dan tashqarida tez-tez o'tkazib yuboriladi). Bu yerdagi
savollar boshqa va ular HECH QACHON o'tkazib yuborilmasligi kerak:

  F5 — SAQLANGAN artefakt JADVAL bo'yicha tiklanadimi? Ilgari faqat operator qo'lda
       `backup_run_id` bergandagina tiklanardi, haftalik jadval esa YANGI dump olardi.
       Ya'ni almashtirilgan `BACKUP_PASSPHRASE` yoki buzilgan artefakt FALOKAT KUNIGACHA
       bilinmasdi — mashq esa har hafta YASHIL bo'lardi.
  F6 — Haftalik mashqning "BEFORE" barmoq izi dumpdan OLDIN olinadimi? Dumpdan KEYIN olinsa,
       dump davomida tushgan yozuv yolg'on nomuvofiqlik berardi (yoki HAQIQIYsini yopardi).
  F7–F9 — Runbook operatorga NIMA bo'lishini aytadi? Bo'lmaydigan narsani ("jurnal satrlari
       YO'QOLDI") va'da qilsa yoki vositaning chiqishini NOTO'G'RI ko'rsatsa, operator
       to'g'ri deployni ham STOP deb o'qiydi.

Kutilgan chiqish satrlari TAXMINDAN emas, HAQIQIY vositadan olinadi: `_print_report` shu yerda
CHAQIRILADI va runbook'dagi blok bilan solishtiriladi.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

SERVER = pathlib.Path(__file__).resolve().parents[1]
ROOT = SERVER.parent.parent
WF = ROOT / ".github" / "workflows" / "restore-rehearsal.yml"
BACKUP_WF = ROOT / ".github" / "workflows" / "db-backup.yml"
STAGING_BACKUP_WF = ROOT / ".github" / "workflows" / "staging-backup.yml"
STAGING_DEPLOY_WF = ROOT / ".github" / "workflows" / "staging-deploy.yml"
RUNBOOK = ROOT / "BINOS_PRODUCTION_DEPLOY_RUNBOOK.md"


def _backup_core_path(caller_path=BACKUP_WF):
    """Chaqiruvchidan (`uses:`) reusable core workflow yo'lini topadi.

    ⚠️  `db-backup.yml` endi BUTUN mantiqni `_db-backup-core.yml` ga topshiradi. Testlar
        chaqiruvchining xom matnini o'qishda davom etsa, ular refaktordan keyin JIMGINA
        bo'sh tekshiruvga aylanardi — aynan bu repoda bir marta sodir bo'lgan nuqson
        (`pg_client.sh` tuzatilgan, `action.yml` dagi NUSXASI esa yo'q). Shu bois test
        indirektsiyani KUZATADI.
    """
    data = yaml.safe_load(caller_path.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    assert len(jobs) == 1, "chaqiruvchida bitta job kutilgan edi: %s" % list(jobs)
    uses = str(next(iter(jobs.values()))["uses"])
    assert uses.startswith("./.github/workflows/"), (
        "MAHALLIY reusable workflow kutilgan edi: %s" % uses)
    return ROOT / uses.removeprefix("./")


# ═══ Yordamchilar ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def wf():
    raw = WF.read_text(encoding="utf-8")
    return yaml.safe_load(raw), raw


def _job_text(raw: str, job: str) -> str:
    """Bitta job'ning xom YAML matni (keyingi job boshlanguncha)."""
    start = raw.index("\n  %s:" % job)
    rest = raw[start + 1:]
    nxt = [i for i in (rest.find("\n  artifact:"), rest.find("\n  fresh:")) if i > 0]
    return rest[:min(nxt)] if nxt else rest


def _code(text: str) -> str:
    """Izohlarsiz matn — izohda atama ESLATILISHI mumkin, muhimi BAJARILADIGAN qismi."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _eval_if(expr: str, *, event: str, run_id: str) -> bool:
    """GitHub `if:` ifodasini SHU stsenariy uchun hisoblaydi.

    Faqat ikki kontekst tokeni tanilgan (`github.event_name`, `inputs.backup_run_id`).
    Boshqa token kirsa `NameError` chiqadi va test YIQILADI — bu ataylab: rejim tanlashga
    yangi, tekshirilmagan shart jimgina kirib qolmasin."""
    py = (expr.replace("&&", " and ").replace("||", " or ")
              .replace("github.event_name", repr(event))
              .replace("inputs.backup_run_id", repr(run_id)))
    return bool(eval(py, {"__builtins__": {}}, {}))  # noqa: S307 — ifoda repo'ning O'ZIDAN


def _steps(data, job) -> list:
    return data["jobs"][job]["steps"]


def _step_index(data, job, needle: str) -> int:
    for i, s in enumerate(_steps(data, job)):
        if needle in (s.get("run") or "") or needle in (s.get("name") or ""):
            return i
    raise AssertionError("%s: '%s' bor qadam topilmadi" % (job, needle))


def _section(md: str, heading: str) -> str:
    """`### <heading>` dan keyingi bo'lim matni (keyingi sarlavhagacha)."""
    start = md.index(heading)
    tail = md[start:]
    nxt = [i for i in (tail.find("\n### ", 1), tail.find("\n## ", 1)) if i > 0]
    return tail[:min(nxt)] if nxt else tail


# ═══ F5 — SAQLANGAN artefakt JADVAL bo'yicha tiklanadi ══════════════════════

def test_F5_artefakt_rejimi_JADVALDA_ham_ishlaydi(wf):
    """Jadval SAQLANGAN artefaktni tiklashi SHART.

    Aks holda parol rotatsiyasi yoki buzuq artefakt faqat falokat kunida bilinardi."""
    data, _raw = wf
    art_if = data["jobs"]["artifact"]["if"]
    assert _eval_if(art_if, event="schedule", run_id="") is True, (
        "artefakt job'i JADVALDA ishlamaydi — saqlangan artefakt hech qachon avtomatik "
        "tiklanmaydi (F5)")
    assert _eval_if(art_if, event="workflow_dispatch", run_id="34338652056") is True
    assert _eval_if(art_if, event="workflow_dispatch", run_id="") is False


def test_F5_jadvalda_ham_ikki_rejim_ALOHIDA_qoladi(wf):
    """Operator qo'lda run bersa — AYNAN bitta rejim; jadval ikkalasini ham yurgizadi,
    lekin ular ALOHIDA job, ya'ni biri ikkinchisiga O'TA OLMAYDI."""
    data, _raw = wf
    jobs = data["jobs"]
    assert set(jobs) == {"artifact", "fresh"}
    for run_id, want in (("34338652056", ("artifact",)), ("", ("fresh",))):
        active = tuple(j for j in ("artifact", "fresh")
                       if _eval_if(jobs[j]["if"], event="workflow_dispatch", run_id=run_id))
        assert active == want, "workflow_dispatch(backup_run_id=%r): %s" % (run_id, active)
    assert _eval_if(jobs["fresh"]["if"], event="schedule", run_id="") is True


def test_F5_jadval_uchun_eng_yangi_backup_run_aniqlanadi(wf):
    """Jadvalda `backup_run_id` yo'q — run `gh api` bilan TOPILADI (db-backup.yml)."""
    data, raw = wf
    code = _code(_job_text(raw, "artifact"))
    assert "actions/workflows/db-backup.yml/runs" in code, (
        "jadval uchun eng yangi backup run'i aniqlanmaydi (F5)")
    assert "savdoos-db-" in code
    dl = [s for s in _steps(data, "artifact") if "download-artifact" in str(s.get("uses", ""))]
    assert dl, "artefakt yuklab olish qadami YO'Q"
    run_id = str(dl[0]["with"]["run-id"])
    assert "steps." in run_id and "run_id" in run_id, (
        "yuklab olish hali ham to'g'ridan-to'g'ri `inputs.backup_run_id` ga bog'langan: %s" % run_id)


def test_F5_run_topilmasa_JIMGINA_yangi_dump_OLINMAYDI(wf):
    """Artefakt yo'li YIQILADI, yangi dump olishga QAYTMAYDI — mashqning butun ma'nosi shu."""
    _data, raw = wf
    code = _code(_job_text(raw, "artifact"))
    assert "backup_postgres.sh" not in code, "artefakt job'i YANGI DUMP olmoqda"
    assert "PROD_DATABASE_URL" not in code, "artefakt job'i production satrini ko'rmoqda"
    pick = [blk for blk in code.split("      - name: ") if "db-backup.yml/runs" in blk]
    assert pick and "::error::" in pick[0], (
        "run topilmaganda ANIQ xato YO'Q — jim o'tib ketishi mumkin")


def test_F5_operatsiya_runbooki_jadvalni_TOGRI_tasvirlaydi():
    """Operator jadval nima qilishini AYNAN shu bo'limdan o'qiydi — u haqiqatga mos bo'lsin."""
    ops = (ROOT / "PRODUCTION_OPERATIONS_RUNBOOK.md").read_text(encoding="utf-8")
    sec = _section(ops, "### 4.1a SAQLANGAN ARTEFAKTNI tiklash")
    assert "jadval" in sec.lower(), (
        "§4.1a hali ham artefakt rejimi FAQAT qo'lda ishlaydi deb tushuntirmoqda (F5)")
    assert "db-backup.yml" in sec, "§4.1a run qayerdan topilishini aytmaydi (F5)"


# ═══ F6 — capture barmoq izi dumpdan OLDIN va KEYIN ═════════════════════════

def test_F6_before_barmoq_izi_dumpdan_OLDIN_olinadi(wf):
    """`pg_dump` tarkibi dump BOSHLANGAN paytdagi snapshot — solishtirish asosi ham shu payt."""
    data, _raw = wf
    i_before = _step_index(data, "fresh", "before.json")
    i_dump = _step_index(data, "fresh", "backup_postgres.sh")
    assert i_before < i_dump, (
        "BEFORE barmoq izi dumpdan KEYIN olinmoqda (qadam %d > %d) — dump davomidagi "
        "yozuv yolg'on nomuvofiqlik beradi (F6)" % (i_before, i_dump))


def test_F6_capture_IKKI_MARTA_olinadi_va_solishtiriladi(wf):
    """`db-backup.yml` dagi naqsh: oldin + keyin, farqi `quiescent` bahosini beradi."""
    _data, raw = wf
    fresh = _code(_job_text(raw, "fresh"))
    assert "db_fingerprint --compare" in fresh, (
        "dumpdan keyingi capture BILAN solishtirish yo'q (F6)")
    assert "QUIESCENT" in fresh, "capture tinch turganmi — belgilanmaydi (F6)"
    assert "::warning::" in fresh, (
        "tinch bo'lmagan capture JIMGINA o'tmoqda — ogohlantirish yo'q (F6)")
    backup = _backup_core_path().read_text(encoding="utf-8")
    assert "fingerprint-before.json" in backup and "capture_quiescent" in backup, (
        "backup core'idagi naqsh o'zgargan — mashq endi unga MOS EMAS")


def test_F6_solishtirish_asosi_BEFORE_fayli(wf):
    """Tiklangan baza dumpdan OLDINGI barmoq izi bilan solishtiriladi."""
    _data, raw = wf
    fresh = _code(_job_text(raw, "fresh"))
    assert "BEFORE_FINGERPRINT" in fresh and "before.json" in fresh
    # Ikkinchi capture ALOHIDA faylga yozilsin — aks holda BEFORE ustiga yozilib ketardi.
    assert "capture-after.json" in fresh, "dumpdan keyingi capture alohida faylga yozilmayapti"


# ═══ F7 — D7 bo'lmaydigan narsani va'da qilmaydi ════════════════════════════

def test_F7_D7_jurnal_satrlari_YOQOLDI_deb_vada_QILMAYDI():
    """Migratsiya konteynerni qayta ishga tushirmaydi — deploy boot satrlari JURNALDA QOLADI.

    Ularning "yo'qolishini" kutgan operator to'g'ri deployni STOP deb o'qiydi."""
    d7 = _section(RUNBOOK.read_text(encoding="utf-8"), "### D7 — Smoke")
    assert "YO'QOLDI" not in d7, (
        "D7 hali ham boot jurnali satrlari yo'qolishini va'da qilmoqda (F7)")
    assert "QOLADI" in d7, "D7 boot satrlari jurnalda QOLISHINI aytmaydi (F7)"
    assert "column_types=true" in d7 and "verify: VERIFIED" in d7, (
        "D7 holatni ISBOTLAYDIGAN signalni (verify + column_types) ko'rsatmaydi (F7)")


# ═══ F8/F9 — keltirilgan chiqishlar HAQIQIY vositaniki ══════════════════════

def _real_preflight_lines(capsys) -> list[str]:
    """`schema_migrate preflight` HAQIQATDA chop etadigan satrlar (sintetik hisobot ustida)."""
    from app.tools.schema_migrate import _print_report
    _print_report({
        "migration_id": "2026-09-17.uuid-client-columns-v1",
        "database": {"database": "railway", "system_identifier": "7674898282858840119",
                     "server_version_num": 180000},
        "verdict": "READY",
        "drifted": [{"table": "cash_movements", "column": "client_uuid"},
                    {"table": "qr_payments", "column": "sale_id"},
                    {"table": "qr_payments", "column": "client_uuid"}],
        "values": {"columns": [{"table": "cash_movements", "column": "client_uuid",
                                "rows": 1234, "null": 12, "canonical_lower": 1222,
                                "canonical_other_case": 0, "empty": 0, "noncanonical": 0}]},
        "findings": [],
        "plan_sha256": "a" * 64,
        "report_sha256": "b" * 64,
    }, out_path="uuid-preflight-prod.json")
    return capsys.readouterr().out.splitlines()


def test_F8_D2_preflight_chiqishi_HAQIQIY_shaklda(capsys):
    """D2 «chiqish AYNAN shu shaklda» deydi — demak maydonlar ham AYNAN bo'lsin."""
    real = _real_preflight_lines(capsys)
    values_line = [ln for ln in real if ln.startswith("  cash_movements.client_uuid:")][0]
    labels = [tok.split("=")[0] for tok in values_line.split() if "=" in tok]
    assert "kanonik_boshqa_registr" in labels and "bo'sh" in labels  # vosita shunday chop etadi
    d2 = _section(RUNBOOK.read_text(encoding="utf-8"), "### D2 — `preflight`")
    for label in labels:
        assert label + "=" in d2, (
            "D2 dagi kutilgan chiqishda `%s=` maydoni YO'Q — vosita uni chop etadi (F8)" % label)
    for head in ("migratsiya:", "baza:", "hukm:", "og'ishlar:",
                 "plan_sha256:", "report_sha256:", "hisobot saqlandi:"):
        assert head in d2, "D2 da `%s` satri yo'q (F8)" % head


def test_F9_D5_apply_chiqishida_DDL_IKKI_MARTA_korinadi():
    """Vosita DDL satrlarini `apply:` satridan OLDIN ham, KEYIN ham chop etadi.

    Manbadan tasdiqlanadi (taxmin emas): `COMMIT BAJARILDI` bloki, keyin `apply:` satri,
    keyin DDL sikli, keyin `tiplar:`."""
    src = (SERVER / "app" / "tools" / "schema_migrate.py").read_text(encoding="utf-8")
    i_commit = src.index('CM.out(f"COMMIT BAJARILDI')
    i_apply = src.index('CM.out(f"{what}: {out[')
    i_loop = src.index('for stmt in out.get("ddl") or []:', i_apply)
    i_types = src.index('CM.out("  tiplar: "', i_loop)
    assert i_commit < i_apply < i_loop < i_types

    d5 = _section(RUNBOOK.read_text(encoding="utf-8"), "### D5 — `uuid` migratsiyasi")
    block = d5[d5.index("COMMIT BAJARILDI · DDL=2"):]
    after_apply = block[block.index("apply: APPLIED · commit=True"):]
    assert "ALTER TABLE" in after_apply[:after_apply.index("tiplar:")], (
        "D5 dagi kutilgan chiqishda `apply:` satridan KEYINGI DDL satrlari YO'Q — "
        "vosita ularni ikki marta chop etadi (F9)")


def test_F9_D8_kutilgan_apply_satri_TOLIQ():
    """D8 dagi `ALREADY_APPLIED` kutilishi vositaning HAQIQIY satri bilan berilsin."""
    d8 = _section(RUNBOOK.read_text(encoding="utf-8"), "### D8 — Deploydan KEYINGI backup")
    assert "apply: ALREADY_APPLIED · commit=True · DDL=0" in d8, (
        "D8 dagi kutilgan chiqish vositaning satriga MOS EMAS (F9)")
    assert "COMMIT BAJARILDI · DDL=0" in d8, (
        "`--commit` yo'lida bu satr DDL=0 bo'lganda ham chiqadi — D8 uni ko'rsatmaydi (F9)")


def test_F9_runbookdagi_har_apply_satri_HAQIQIY_maydonlarga_ega():
    """`apply:` satri vositada DOIM `commit=`, `DDL=`, `qulf kutishi=` va davomiylikni beradi."""
    md = RUNBOOK.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in md.splitlines() if ln.strip().startswith("apply: ")]
    assert lines, "runbook'da birorta `apply:` chiqish satri yo'q"
    for ln in lines:
        for token in ("commit=", "DDL=", "qulf kutishi="):
            assert token in ln, "`%s` satrida `%s` yo'q (F9)" % (ln, token)
        assert ln.endswith(" ms"), "`%s` satri davomiylik bilan tugamaydi (F9)" % ln


# ═══ P8 — RELIZ XAVFSIZLIGI: staging nusxasi + CI darvozasi ═════════════════
#
# Bu guruh IKKI narsani qadab qo'yadi:
#   1. Ikki muhit BITTA mantiqni ulashadi (nusxa drifti mumkin bo'lmasin).
#   2. Staging nusxasi va staging deploy darvozasi production'ga TEGMASIN.
#
# NEGA: bu repo nusxa driftidan bir marta allaqachon jabr ko'rgan — `pg_client.sh`
# tuzatilgan, `action.yml` dagi NUSXASI esa yo'q edi, va birinchi HAQIQIY production
# backup'i shundan yiqilgan (`major=2, expected=18`).

CORE_WF = ROOT / ".github" / "workflows" / "_db-backup-core.yml"


def _raw(p):
    return p.read_text(encoding="utf-8")


def test_P8_ikkala_muhit_ham_BITTA_core_ni_chaqiradi():
    """Production va staging AYNAN bir xil backup mantiqini ishlatishi SHART."""
    prod_core = _backup_core_path(BACKUP_WF)
    stg_core = _backup_core_path(STAGING_BACKUP_WF)
    assert prod_core == stg_core == CORE_WF, (
        "muhitlar TURLI core'ni chaqirmoqda — drift boshlandi: %s vs %s" % (prod_core, stg_core))


def test_P8_chaqiruvchilarda_dump_MANTIQI_YOQ():
    """Chaqiruvchi faqat parametr berishi kerak. Ularda dump/shifrlash qadami paydo
    bo'lsa — bu aynan biz qochayotgan ikkinchi nusxaning boshlanishi."""
    for wf in (BACKUP_WF, STAGING_BACKUP_WF):
        raw = _raw(wf)
        for forbidden in ("backup_postgres.sh", "gpg --batch", "db_fingerprint", "pg-client"):
            assert forbidden not in raw, (
                "%s ichida `%s` bor — mantiq core'da BO'LISHI kerak" % (wf.name, forbidden))


def test_P8_artefakt_prefikslari_TOQNASHMAYDI():
    """`restore-rehearsal.yml` bitta run'da `savdoos-db-*` bilan boshlanadigan BIR NECHTA
    artefakt topsa ATAYLAB yiqiladi. Staging prefiksi shu naqshga TUSHMASLIGI shart."""
    prod = yaml.safe_load(_raw(BACKUP_WF))["jobs"]["backup"]["with"]["artifact_prefix"]
    stg = yaml.safe_load(_raw(STAGING_BACKUP_WF))["jobs"]["backup"]["with"]["artifact_prefix"]
    assert prod == "savdoos-db", (
        "production prefiksi o'zgardi (%s) — mashq artefaktni endi TOPOLMAYDI" % prod)
    assert not stg.startswith("savdoos-db-") and stg != "savdoos-db", (
        "staging prefiksi (%s) production naqshiga tushmoqda — mashq ikki artefakt "
        "ko'rib yiqiladi" % stg)


def test_P8_staging_PRODUCTION_satrini_KORMAYDI():
    """Staging nusxasi production bazasiga ULANMASLIGI tuzilmaviy kafolat bo'lsin."""
    stg = _raw(STAGING_BACKUP_WF)
    assert "PROD_DATABASE_URL" not in stg, "staging workflow'i production satrini ko'rmoqda"
    assert "STAGING_DATABASE_URL" in stg, "staging workflow'i o'z sirini ishlatmayapti"
    prod = _raw(BACKUP_WF)
    assert "STAGING_DATABASE_URL" not in prod, "production workflow'i staging satrini ko'rmoqda"
    assert "PROD_DATABASE_URL" in prod


def test_P8_staging_saqlash_muddati_OCHIQ_repo_chegarasida():
    """OCHIQ repoda GitHub artefaktni 90 kundan uzoq saqlamaydi — undan katta qiymat
    JIMGINA qisqartirilardi va runbook'dagi va'da yolg'on bo'lib qolardi."""
    w = yaml.safe_load(_raw(STAGING_BACKUP_WF))["jobs"]["backup"]["with"]
    for key in ("retention_daily", "retention_weekly", "retention_monthly"):
        assert int(w[key]) <= 90, "%s = %s > 90 kun (ochiq repo chegarasi)" % (key, w[key])
    assert int(w["retention_daily"]) < int(w["retention_weekly"]) <= int(w["retention_monthly"])


def test_P8_core_sir_yoq_bolsa_YIQILADI():
    """Jim `exit 0` — aynan production'da 11 tunlik yolg'on "success" bergan nuqson edi."""
    raw = _raw(CORE_WF)
    assert "::error::" in raw and "exit 1" in raw, "sir yo'qligida ANIQ xato yo'q"
    assert "exit 0" not in raw, "core'da jim `exit 0` yo'li paydo bo'lgan"


def test_P8_shifrlash_MAJBURIY_va_ochiq_dump_YUKLANMAYDI():
    """Repo OCHIQ — shifr YAGONA to'siq. Ochiq dump artefaktga chiqmasligi shart."""
    core = yaml.safe_load(_raw(CORE_WF))
    steps = core["jobs"]["dump"]["steps"]
    up = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))][0]
    paths = str(up["with"]["path"])
    assert "*.dump.gpg" in paths
    assert "backups/*.dump\n" not in paths, "OCHIQ dump artefaktga chiqmoqda"
    assert str(up["with"]["if-no-files-found"]) == "error", "bo'sh backup jimgina o'tib ketadi"
    # ⚠️  Ochiq nusxani o'chirish endi CORE'DA EMAS — u `scripts/encrypt_evidence.sh`
    #     ichida, va aynan SHIFR OCHIB TEKSHIRILGANDAN keyin bajariladi. Bu test
    #     ilgari core'ning matnidan `rm -f "$f"` ni qidirardi; skript ajratilgach u
    #     jimgina bo'sh tekshiruvga aylanardi. Endi indirektsiya KUZATILADI.
    helper = ROOT / "scripts" / "encrypt_evidence.sh"
    src = helper.read_text(encoding="utf-8")
    assert "encrypt_evidence.sh" in _raw(CORE_WF), "core umumiy skriptni chaqirmayapti"
    assert 'rm -f "$f"' in src, "skript ochiq nusxani o'chirmayapti"
    assert "-d \"$f.gpg\"" in src, "shifr OCHIB TEKSHIRILMAYAPTI"


# ── CI darvozasi ────────────────────────────────────────────────────────────

def test_P8_deploy_darvozasi_OCHIQ_HOLDA_KELMAYDI():
    """Yangi deploy yo'li EGA aniq yoqmaguncha ishlamasligi SHART — aks holda merge
    bo'lgan zahoti ikkita deploy yo'li (Railway trigger + bu workflow) poyga qilardi."""
    data = yaml.safe_load(_raw(STAGING_DEPLOY_WF))
    cond = str(data["jobs"]["deploy"]["if"])
    assert "STAGING_DEPLOY_ENABLED" in cond, "darvoza o'zgaruvchisi yo'q — workflow o'z-o'zidan ishlaydi"
    assert "workflow_run.conclusion == 'success'" in cond, "CI xulosasi tekshirilmayapti"


def test_P8_deploy_FAQAT_CI_dan_keyin_ishga_tushadi():
    """Trigger `workflow_run` bo'lishi va AYNAN `CI` ni kuzatishi kerak."""
    data = yaml.safe_load(_raw(STAGING_DEPLOY_WF))
    on = data.get(True) or data.get("on")
    wr = on["workflow_run"]
    assert wr["workflows"] == ["CI"], "boshqa workflow kuzatilmoqda: %s" % wr["workflows"]
    assert wr["branches"] == ["main"], "main'dan boshqa branch ham deploy qilmoqda"
    assert "push" not in on, "deploy push'ga to'g'ridan-to'g'ri bog'langan — darvoza chetlab o'tiladi"


def test_P8_qolda_chaqiruv_darvozani_CHETLAB_OTMAYDI():
    """`workflow_dispatch` yo'li ham CI yashilligini ANIQ tekshirishi shart, aks holda u
    darvozadagi teshik bo'lardi."""
    raw = _raw(STAGING_DEPLOY_WF)
    assert "actions/runs?head_sha=" in raw, "qo'lda yo'lda CI holati tekshirilmayapti"
    assert "YASHIL EMAS" in raw or "conclusion" in raw
    # SHA ko'rinishi tasdiqlanadi — ixtiyoriy satr Railway'ga uzatilmaydi.
    assert "40" in raw and "o'n oltilik" in raw.lower() or "hex" in raw.lower()


def test_P8_deploy_token_buyruq_satriga_CHIQMAYDI():
    """Token `-d` bilan buyruq satriga yozilsa jarayonlar ro'yxatida ko'rinardi."""
    raw = _raw(STAGING_DEPLOY_WF)
    assert "-d @payload.json" in raw, "so'rov tanasi faylga yozilmayapti"
    assert "$RAILWAY_TOKEN" in raw and "echo \"$RAILWAY_TOKEN\"" not in raw


def test_P8_barmoq_izi_artefaktga_OCHIQ_CHIQMAYDI():
    """`fingerprint*.json` ichida 25 biznes jadvalining aniq sanog'i, `cash_counts`,
    `max_timestamps` va `ledger_sums` (naqd ledgerning PUL SUMMALARI) hamda `target_db` bor.

    Repo OCHIQ — GitHub hujjatiga ko'ra ochiq repoda artefaktni tizimga kirgan HAR QANDAY
    hisob yuklab oladi. Ya'ni dump shifrlangan bo'lsa ham, biznes raqamlari PAROLDAN
    QAT'I NAZAR ochiq turardi. Endi ular ham AES256 ostida."""
    core = yaml.safe_load(_raw(CORE_WF))
    up = [s for s in core["jobs"]["dump"]["steps"]
          if "upload-artifact" in str(s.get("uses", ""))][0]
    paths = [ln.strip() for ln in str(up["with"]["path"]).splitlines() if ln.strip()]
    for p in paths:
        assert not p.endswith("fingerprint.json"), (
            "OCHIQ barmoq izi artefaktga chiqmoqda: %s" % p)
        assert not p.endswith("fingerprint-before.json"), (
            "OCHIQ barmoq izi artefaktga chiqmoqda: %s" % p)
    assert any(p.endswith("fingerprint.json.gpg") for p in paths), (
        "shifrlangan capture barmoq izi YUKLANMAYAPTI — mashqning solishtirish asosi yo'qoladi")


def test_P8_tiklash_ESKI_artefaktlarni_ham_ochadi():
    """Saqlash muddati 180 kungacha — OCHIQ barmoq izli eski artefaktlar HAMON tiklanishi
    shart. Shifrlangan yo'l qo'shildi, ochiq yo'l ZAXIRA sifatida qoldi."""
    raw = (ROOT / "scripts" / "restore_from_artifact.sh").read_text(encoding="utf-8")
    assert "fingerprint.json.gpg" in raw, "shifrlangan barmoq izi ochilmayapti"
    assert 'if [ -f "$CAPTURE_FP" ]; then' in raw, "ochiq fayl yo'li (eski artefaktlar) yo'qolgan"


def test_P8_tiklashda_YAGONA_trap_qoladi():
    """Ikkinchi `trap ... EXIT` birinchisini ALMASHTIRIB yuboradi — ya'ni ochiq dump
    tozalanmay qolardi. Tozalash BITTA funksiyada bo'lishi shart."""
    raw = (ROOT / "scripts" / "restore_from_artifact.sh").read_text(encoding="utf-8")
    traps = [ln for ln in raw.splitlines()
             if ln.strip().startswith("trap ") and "EXIT" in ln]
    assert len(traps) == 1, "bir nechta EXIT trap'i bor, ular bir-birini almashtiradi: %s" % traps


# ═══ P8/2 — mashq DALILLARI ham ochiq chiqmasin ═════════════════════════════

def test_P8_mashq_dalillari_OCHIQ_CHIQMAYDI():
    """`restore-rehearsal.yml` ikkala job'i ham barmoq izi JSON'larini yuklaydi. Ular
    production bazasining qator sanoqlari va `ledger_sums` (PUL SUMMALARI) ni tashiydi.

    Repo OCHIQ — ya'ni dump shifrlangan bo'lsa ham bu raqamlar paroldan qat'i nazar
    o'qilardi. 2026-09-28 holati: 36 ta `artifact-restore-*` + 3 ta `restore-rehearsal-*`
    jonli artefakt aynan shunday ochiq JSON tashirdi."""
    data = yaml.safe_load(_raw(WF))
    ochiq = ("after.json", "before.json", "capture-after.json", "fingerprint.json",
             "uuid-preflight.json")
    for job in ("artifact", "fresh"):
        up = [s for s in data["jobs"][job]["steps"]
              if "upload-artifact" in str(s.get("uses", ""))][0]
        paths = [ln.strip() for ln in str(up["with"]["path"]).splitlines() if ln.strip()]
        for p in paths:
            base = p.rsplit("/", 1)[-1]
            assert base not in ochiq, (
                "%s job'i OCHIQ barmoq izi yuklamoqda: %s" % (job, p))
        assert any(p.endswith(".gpg") for p in paths), (
            "%s job'ida shifrlangan dalil umuman yo'q — tekshiruv ma'nosini yo'qotdi" % job)


def test_P8_dalil_shifrlash_SOLISHTIRISHDAN_KEYIN_turadi():
    """Shifrlash qadami barmoq izi solishtiruvidan OLDIN tursa, solishtirish o'qiydigan
    fayl allaqachon o'chirilgan bo'lardi va mashq jimgina o'z kuchini yo'qotardi."""
    data = yaml.safe_load(_raw(WF))
    for job, oldingi in (("artifact", "Ilova smoke testi"), ("fresh", "Barmoq izi solishtiruvi")):
        names = [str(s.get("name") or s.get("uses")) for s in data["jobs"][job]["steps"]]
        enc = [i for i, n in enumerate(names) if n.startswith("Dalillarni shifrlash")]
        assert enc, "%s job'ida shifrlash qadami yo'q" % job
        ref = [i for i, n in enumerate(names) if n.startswith(oldingi)]
        assert ref and enc[0] > ref[0], (
            "%s: shifrlash `%s` dan OLDIN turibdi" % (job, oldingi))
        # ⚠️  `names` yaramaydi: yuklash qadamining `name` i bor ("Natijani saqlash"),
        #     shu bois `uses` bo'yicha qidiriladi.
        up = [i for i, st in enumerate(data["jobs"][job]["steps"])
              if "upload-artifact" in str(st.get("uses", ""))]
        assert up and enc[0] < up[-1], "%s: shifrlash yuklashdan KEYIN turibdi" % job


# ═══ P8/3 — OCHIQ repoda oshkor bo'lmasligi kerak bo'lgan narsalar ═════════

def test_P8_ignore_qoidasini_buzadigan_KUZATILAYOTGAN_fayl_yoq():
    """`.gitignore` ga qoida qo'shish allaqachon kuzatilayotgan faylni UNTRACK QILMAYDI.

    Aynan shunday bo'lgan: `apps/server/qa_auth_results.json` `.gitignore:47`
    (`apps/server/qa_*_results.json`) qoidasidan OLDIN commit qilingan, qoida keyin
    qo'shilgan — va fayl HEAD'da qolib ketgan. Repo OCHIQ, fayl ichida esa bitta
    O'zbek mobil raqami bor edi. Sherigi `qa_products_results.json` to'g'ri o'chirilgan,
    bu esa e'tibordan qolgan."""
    import subprocess
    root = str(ROOT)
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
    assert tracked.returncode == 0, tracked.stderr
    chk = subprocess.run(["git", "check-ignore", "--no-index", "-v", "--stdin"],
                         cwd=root, input=tracked.stdout, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    hits = [ln for ln in chk.stdout.splitlines() if ln.strip()]
    assert not hits, (
        "kuzatilayotgan fayl(lar) o'z ignore qoidasini buzmoqda — ular HEAD'da qolgan:\n  "
        + "\n  ".join(hits))


def test_P8_HAQIQIY_production_endpointi_kodda_YOQ():
    """Repo OCHIQ. Jonli bazaning aniq manzili (host + port + baza nomi) kodda tursa,
    hujumchiga faqat parol topish qoladi.

    Ilgari `tests/cash/test_artifact_restore.py` da HAQIQIY Railway proxy endpoint'i
    qattiq yozilgan edi — holbuki qo'riqchi localhost BO'LMAGAN har qanday manzilni
    rad etadi, ya'ni test haqiqiy host'ga muhtoj emas. Sintetik host bilan
    almashtirildi; bu test uni qaytarib qo'yishdan saqlaydi."""
    import subprocess
    # Aniq host nomi ATAYLAB bo'laklab yoziladi: bu faylning o'zi ham ochiq repoda turadi.
    needle = "sakura" + ".proxy.rlwy.net"
    r = subprocess.run(["git", "grep", "-l", needle, "--", "."], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    # `git grep` topilmasa 1 qaytaradi — bu KUTILGAN holat.
    assert r.returncode != 0 or not r.stdout.strip(), (
        "HAQIQIY production endpoint'i qaytib kelgan:\n" + r.stdout)


def test_P8_barmoq_izi_farqlari_JURNALGA_chiqmaydi():
    """Actions jurnali OCHIQ repoda LOGINSIZ o'qiladi — artefaktdan ham ZAIF chegara.

    Barmoq izi solishtiruvining chiqishi qator sanoqlari va `ledger_sums` (pul
    summalari) ni oshkor qiladi. Shu bois HAR BIR `--compare` chaqiruvi chiqishini
    `/dev/null` ga yoki dalil fayliga yo'naltirishi SHART. Artefaktlarni shifrlab,
    o'sha raqamlarni jurnalga chiqarish — qulfni qo'yib, kalitni eshik oldiga tashlash."""
    raw = _raw(WF)
    # Davomiy satrlarni birlashtiramiz — chaqiruv ikki qatorga bo'lingan.
    # ⚠️  `raw.replace(chr(92) + chr(10), " ")` bilan emas, SATRMA-SATR: shell davomiyligi
    #     ortidan bo'shliq qolishi mumkin va bitta almashtirish uni o'tkazib yuborardi.
    merged, buf = [], ""
    for ln in raw.splitlines():
        stripped = ln.rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        merged.append(buf + ln)
        buf = ""
    if buf:
        merged.append(buf)
    calls = [ln.strip() for ln in merged if "db_fingerprint --compare" in ln]
    assert calls, "mashqda barmoq izi solishtiruvi umuman yo'q"
    for c in calls:
        assert (">/dev/null" in c) or ("> ../../" in c and ".txt" in c), (
            "solishtiruv chiqishi JURNALGA ketmoqda: %s" % c)


def test_P8_core_qator_sanogini_jurnalga_chop_ETMAYDI():
    """`db-backup.yml` ilgari `companies=.. branches=.. sales=..` ni jurnalga yozardi."""
    raw = _raw(CORE_WF)
    assert "companies=%s" not in raw and "branches=%s" not in raw, (
        "production qator sanog'i hamon jurnalga chop etilmoqda")
    assert "sha256=" in raw, (
        "sanoq o'rniga korrelyatsiya uchun barmoq izi sha256 prefiksi chiqarilmayapti")


def test_P8_shifrlash_YAGONA_skriptda():
    """Shifrlash uch joyda kerak (nusxa core'i + mashqning ikkala job'i). Uch nusxa =
    uch xil drift. Bu repo aynan shundan jabr ko'rgan: `pg_client.sh` tuzatilgan,
    `action.yml` dagi NUSXASI esa yo'q edi, va birinchi haqiqiy production backup'i
    "major=2, expected=18" bilan yiqilgan.

    Yagona istisno — mashqning `fresh` job'idagi "shifrlash + ochish" qadami: u
    ochiq nusxani YO'Q QILISH uchun emas, HAQIQIY tiklash yo'lini sinash uchun."""
    helper = ROOT / "scripts" / "encrypt_evidence.sh"
    assert helper.exists(), "umumiy shifrlash skripti yo'q"
    for wf in (CORE_WF, WF):
        raw = _raw(wf)
        # Izohlar emas, HAQIQIY chaqiruvlar: satr `gpg ` bilan boshlanadi yoki
        # `| gpg ` ko'rinishida quvurga ulanadi. (Blok bo'yicha qidirish sarlavhadagi
        # izohlarni ham ushlab, yolg'on qizil berardi.)
        calls = []
        for ln in raw.splitlines():
            t = ln.strip()
            if t.startswith("#"):
                continue
            if t.startswith("gpg ") or "| gpg " in t:
                calls.append(t)
        for c in calls:
            assert "haqiqiy tiklash" in raw, "istisno izohi yo'qolgan"
        # `fresh` job'idagi ataylab istisnodan tashqari boshqa chaqiruv bo'lmasin.
        assert len(calls) <= 2, (
            "%s da umumiy skriptdan tashqari %d ta gpg chaqiruvi bor:\n%s"
            % (wf.name, len(calls), "\n".join(calls)))


def test_P8_ochiq_nusxa_artefaktga_CHIQMAYDI_hech_qachon():
    """Shifrlash yiqilsa ochiq fayl diskda qoladi (ataylab — ma'lumot yo'qolmasin).
    Shu bois yuklash yo'llari OCHIQ nomni UMUMAN qabul qilmasligi kerak: aks holda
    yiqilgan shifrlashdan keyin ochiq nusxa jimgina yuklanardi."""
    ochiq = ("after.json", "before.json", "capture-after.json", "capture-diff.txt",
             "restore-diff.txt", "fingerprint.json", "fingerprint-before.json",
             "uuid-preflight.json")
    for wf in (CORE_WF, WF):
        data = yaml.safe_load(_raw(wf))
        for job in data["jobs"].values():
            for st in job.get("steps", []):
                if "upload-artifact" not in str(st.get("uses", "")):
                    continue
                for ln in str(st["with"]["path"]).splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    assert ln.rsplit("/", 1)[-1] not in ochiq, (
                        "%s: ochiq nom yuklash ro'yxatida: %s" % (wf.name, ln))
                    assert not ln.endswith(".dump"), (
                        "%s: OCHIQ dump yuklash ro'yxatida: %s" % (wf.name, ln))
