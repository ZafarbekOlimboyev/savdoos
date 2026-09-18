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
RUNBOOK = ROOT / "BINOS_PRODUCTION_DEPLOY_RUNBOOK.md"


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
    backup = BACKUP_WF.read_text(encoding="utf-8")
    assert "fingerprint-before.json" in backup and "capture_quiescent" in backup, (
        "db-backup.yml dagi naqsh o'zgargan — mashq endi unga MOS EMAS")


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
