# -*- coding: utf-8 -*-
"""RUNTIME PAKETI shartnomasi va OFFLINE validatori (`runtime_bundle.py` + `cli.py`).

⚠️⚠️ HAMMA FIKSTURA SINTETIK. Bu fayl VALIDATORNI isbotlaydi; u yig'uvchining haqiqiy 1C da
     ishlashini ISBOTLAMAYDI va bunday da'vo QILMAYDI. `.epf` hech qachon kompilyatsiya
     qilinmagan va ishlatilmagan — yig'uvchining runtime holati `RUNTIME-UNKNOWN`.

ISBOTLANADIGAN INVARIANTLAR:
  · yetti artefakt shartnomasi: majburiy fayl yo'qligi, buzuq JSON, noma'lum versiya,
    noma'lum kalit — HAMMASI RAD;
  · sanoq MATN (JSON soni RAD), uchulik mantiq ham MATN (`true`/`false` RAD);
  · obyekt manzili NOYOB (`full_name` takrorlanmaydi);
  · yig'uvchi o'zini TASDIQLAY OLMAYDI: `VERIFIED` ham, KUCHLI dalil turi ham RAD;
  · 1C tomoni ISHONCH DARAJASI bermaydi: `confidence` nomli kalit RAD;
  · sir FAIL-CLOSED to'siladi (to'rt tildagi parol, ulanish satri, fayl yo'li) va nuqson
    matnida qiymatning O'ZI KO'RSATILMAYDI;
  · manifest — YOZILGAN BAYTLARNING xeshi, PROVENANS DA'VOSI EMAS;
  · `overall=SUCCESS` bo'lib majburiy artefakt yo'qligi ZIDDIYAT deb belgilanadi;
  · rejim DEFAULT `METADATA_ONLY` va noma'lum rejim shu yerga fail-safe tushadi;
  · CLI chiqish kodi 0/1 SHARTNOMA, `--json` chiqishi DETERMINISTIK.

ATAYLAB SINALMAYDI:
  · fikstura ichidagi 1C nomlarining MA'NOSI — validator talqin qilmaydi;
  · zond natijasining (`result`) SHAKLI — u hali shartnoma emas va shunday deb yozilgan.
"""
from __future__ import annotations

import copy
import io
import json
import pathlib
import re

import pytest

from app.services.discovery_1c import REQUIRED_MEMBERS
from app.services.discovery_1c import cli
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c.bundle import dumps
from app.services.discovery_1c.probe import PROBE_CATALOG, PROBE_VERSION
from app.services.discovery_1c.schema import TARGETS
from app.services.migrator_1c.bundle import sha256_bytes
from tests.discovery_1c_export_synth import CATALOG, REGISTER, export_dict
from tests.discovery_1c_metadata_synth import CONFIG_A_STANDARD_RU

# ── Sintetik yurish yozuvi ────────────────────────────────────────────────────────────────
#: ⚠️ Versiyada `UNVERIFIED` ATAYLAB turadi: yig'uvchi birorta haqiqiy konfiguratsiyada
#: tasdiqlanmagan. U AYNI VAQTDA `VERIFIED` darvozasining eng nozik holati — so'z chegarasi
#: bo'lmaganda bu halol versiya HAR BIR paketni rad etardi.
#: ⚠️ Versiya `BinOSDiscovery.bsl` dagi `ОписаниеСборщика()` bilan AYNI qiymat.
COLLECTOR = {"name": "BinOSDiscovery", "version": "0.2.0-UNVERIFIED"}
STARTED = "2026-09-30T10:14:30+06:00"
FINISHED = "2026-09-30T10:15:00+06:00"

#: §11 ishga tushirish maydonlari (`run_status.platform`). ⚠️ Qiymatlar MATN yoki `null`:
#: uchulik mantiq JSON booleani bilan almashtirilmaydi. Kalit RO'YXATI shartnoma EMAS
#: (`PLATFORM_KEY_RE` izohiga qarang) — shakl va qiymat TURI shartnoma.
PLATFORM_OK = {
    "platform_version": "8.3.24.1548",
    "configuration_name": "SintetikKonfiguratsiya",
    "configuration_modified": "unknown",
    "infobase_id": None,
}

RUN_NOTES = ["Bu yurish SINTETIK fiksturadan qurilgan — 1C da bajarilmagan."]

SECTIONS_OK = [
    {"name": "platform", "status": "ok", "error": None},
    {"name": "metadata_sweep", "status": "ok", "error": None},
    {"name": "counts", "status": "ok", "error": None},
    {"name": "candidates", "status": "ok", "error": None},
    {"name": "write_metadata", "status": "ok", "error": None},
]

#: ⚠️ `absent` va `unreadable` FARQI shu fiksturada YASHAYDI: `absent` — JAVOB («bunday oila
#: bu konfiguratsiyada yo'q»), `unreadable` — javob YO'QLIGI. Sog'lom paketda `unreadable`
#: BO'LMAYDI, shu bois u alohida fiksturada (`paket_partial`) turadi.
FAMILIES_OK = [
    {"name": "catalogs", "state": "present", "detail": None},
    {"name": "documents", "state": "present", "detail": None},
    {"name": "information_registers", "state": "present", "detail": None},
    {"name": "accumulation_registers", "state": "absent",
     "detail": "bu konfiguratsiyada bunday oila yo'q — bu JAVOB, o'qilmaganlik EMAS"},
    {"name": "enums", "state": "present", "detail": None},
]

SUMMARY_MD = (
    "# 1C razvedka yurishi\n"
    "\n"
    "- Rejim: METADATA_ONLY (aktiv zond yo'q)\n"
    "- Ikki hujjat yozildi, bo'limlar hammasi tugadi\n"
    "\n"
    "Bu hisobot yig'uvchining 1C da ishlashini ISBOTLAMAYDI.\n"
)

BOSH_ERRORS = {"errors_version": rb.ERRORS_VERSION, "collected_at": FINISHED,
               "errors": [], "notes": ["xato chiqmadi — fayl BARIBIR yoziladi"]}


def run_status(*, mode=rb.MODE_METADATA_ONLY, mode_note=None, overall=None, sections=None,
               families=None, probes_log=None, artifacts=None, error_count=None,
               **over) -> dict:
    """`binos-1c-run-v1` hujjati — YAGONA HAQIQIY SHAKL.

    ⚠️ `overall` berilmasa YAGONA TA'RIF bo'yicha hisoblanadi: majburiy artefaktlar yozilgan
       + `failed` bo'lim yo'q + `unreadable` oila yo'q (`rb.derive_overall`).
    ⚠️ `artifacts` STANDART HOLDA majburiy oltovi: bo'sh ro'yxat «hech narsa yozilmadi»
       degani va u holat hisobini `FAILED` ga aylantirardi, ya'ni har bir fikstura jimgina
       boshqa narsani o'lchab qolardi."""
    secs = copy.deepcopy(SECTIONS_OK) if sections is None else copy.deepcopy(sections)
    fams = copy.deepcopy(FAMILIES_OK) if families is None else copy.deepcopy(families)
    arts = sorted(rb.REQUIRED_FILES) if artifacts is None else sorted(artifacts)
    qayd = [] if probes_log is None else copy.deepcopy(probes_log)
    doc = {
        "run_version": rb.RUN_VERSION,
        "collector": dict(COLLECTOR),
        "mode": mode,
        "mode_note": mode_note,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "overall": (rb.derive_overall(secs, families=fams, artifacts=arts)
                    if overall is None else overall),
        "platform": dict(PLATFORM_OK),
        "sections": secs,
        "families": fams,
        "probes": qayd,
        "artifacts": arts,
        "error_count": "0" if error_count is None else error_count,
        "notes": list(RUN_NOTES),
    }
    doc.update(over)
    return doc


def zond_qaydi(tur="row_count", *, no="01", target=CATALOG, status="ok", **over) -> dict:
    """`run_status.probes[]` ning bitta qatori: NIMA bajarildi va QAYERGA yozildi.

    ⚠️ `file` jurnaldagi `no`/`probe_type` dan QURILADI: `ls` qiladigan operator va JSON
       o'qiydigan kod bir xil narsani ko'rishi SHART, shu bois fikstura ikkisini qo'lda
       ajratib yozmaydi."""
    d = {
        "no": no,
        "probe_type": tur,
        "target_object": target,
        "reason": "operator tasdiqlagan allowlistdan tanlangan",
        "file": f"{rb.PROBE_DIR}/{no}_{tur}.json",
        "status": status,
    }
    d.update(over)
    return d


def probe_doc(tur="row_count", *, target=CATALOG, **over) -> dict:
    """`binos-1c-probe-v1` NATIJASI (so'rovi emas). `read_only` — AYNAN `"true"` MATNI.

    ⚠️ `mode` natijaning O'ZIDA ham turadi: zond fayli paketdan ajratib olinib uzatilsa,
       «bu qaysi rejimda bajarildi» degan savol javobsiz qolmasligi kerak."""
    d = {
        "probe_version": PROBE_VERSION,
        "probe_type": tur,
        "target_object": target,
        "read_only": "true",
        "result": {"row_count": "7137"},
        "errors": [],
        "mode": rb.MODE_APPROVED_PROBES,
    }
    d.update(over)
    return d


def paket(*, export=None, metadata=None, errors=None, summary=None, probes=None,
          probes_log=None, run=None, mode=rb.MODE_METADATA_ONLY, drop=(), mutate=None,
          manifest_files=None, manifest=None) -> dict[str, bytes]:
    """SINTETIK runtime paketi: `nom -> baytlar`.

    ⚠️ QURILISH NAVBATI shartnomadagi YOZISH NAVBATI bilan AYNI, chunki shartnoma faqat shu
       navbatda bajarilishi mumkin: (1) mazmun fayllari, (2) `run_status.json` — `artifacts`
       da O'ZI ham, `manifest.json` ham sanaladi, (3) `manifest.json` — O'ZIDAN tashqari hamma
       faylning xeshi. Nomni sanash mazmunga tegmaydi, shu bois aylanma YO'Q.
    ⚠️ `drop` manifest QURILGANDAN KEYIN ishlaydi: haqiqiy nuqson aynan shunday ko'rinadi —
       fayl yo'qoladi, uni da'vo qilgan yozuvlar esa joyida qoladi.
    """
    export = export_dict() if export is None else export
    metadata = copy.deepcopy(CONFIG_A_STANDARD_RU) if metadata is None else metadata
    errors = copy.deepcopy(BOSH_ERRORS) if errors is None else errors
    summary = SUMMARY_MD if summary is None else summary
    probes = {} if probes is None else probes

    m: dict[str, bytes] = {
        rb.EXPORT_FILE: dumps(export).encode("utf-8"),
        rb.METADATA_FILE: dumps(metadata).encode("utf-8"),
        rb.ERRORS_FILE: dumps(errors).encode("utf-8"),
        rb.RUN_SUMMARY_FILE: summary.encode("utf-8"),
    }
    for nom, doc in probes.items():
        m[f"{rb.PROBE_DIR}/{nom}.json"] = dumps(doc).encode("utf-8")

    if run is None:
        qayd = probes_log
        if qayd is None:
            # ⚠️ JURNAL ZOND FAYLLARIDAN QURILADI: standart holda ikkisi AYNAN mos bo'ladi,
            #    mos kelmaslik esa testda ATAYLAB yasaladi.
            qayd = [zond_qaydi(nom.split("_", 1)[1], no=nom.split("_", 1)[0])
                    for nom in sorted(probes)]
        run = run_status(mode=mode, probes_log=qayd,
                         artifacts=sorted(set(m) | {rb.RUN_STATUS_FILE, rb.MANIFEST_FILE}))
    m[rb.RUN_STATUS_FILE] = dumps(run).encode("utf-8")

    if manifest is None:
        files = manifest_files
        if files is None:
            files = [{"name": n, "bytes": str(len(m[n])), "sha256": sha256_bytes(m[n])}
                     for n in sorted(m)]
        manifest = {"manifest_version": rb.MANIFEST_VERSION, "files": files,
                    "notes": ["manifest faqat YOZILGAN baytlarni tavsiflaydi"]}
    m[rb.MANIFEST_FILE] = dumps(manifest).encode("utf-8")

    for n in drop:
        m.pop(n, None)
    if mutate is not None:
        m = mutate(m)
    return m


def hamma_nom(probes=None) -> list[str]:
    """Paketdagi HAMMA fayl nomi — `run_status.artifacts` da AYNAN shu ro'yxat turadi
    (o'zi ham, `manifest.json` ham sanaladi: nomni sanash mazmunga tegmaydi)."""
    probes = probes or {}
    return sorted(set(rb.REQUIRED_FILES) | {f"{rb.PROBE_DIR}/{n}.json" for n in probes})


def paket_partial(**kw) -> dict[str, bytes]:
    """Yiqilgan bo'limi BOR paket: `overall=PARTIAL`, xato ro'yxati to'ldirilgan, oila
    `unreadable`. ⚠️ Bu HALOL paket: yiqilish JIMGINA tushib qolmagan, sababi bilan qolgan."""
    secs = copy.deepcopy(SECTIONS_OK)
    secs[1] = {"name": "metadata_sweep", "status": "failed",
               "error": "oila o'qilmadi: huquq yetmadi"}
    fams = copy.deepcopy(FAMILIES_OK)
    fams[1] = {"name": "documents", "state": "unreadable",
               "detail": "o'qiy olmadim: huquq yetmadi (bu javob YO'QLIGI)"}
    errors = {**BOSH_ERRORS, "errors": [
        {"scope": "family", "family": "documents", "object": None,
         "code": "FAMILY_UNREADABLE", "detail": "oila o'qilmadi: huquq yetmadi"},
    ]}
    kw.setdefault("errors", errors)
    kw.setdefault("run", run_status(sections=secs, families=fams,
                                   artifacts=hamma_nom(kw.get("probes"))))
    return paket(**kw)


def yoz(tmp_path: pathlib.Path, members: dict[str, bytes]) -> str:
    """Paketni diskka yozadi va papka yo'lini qaytaradi."""
    for nom, raw in sorted(members.items()):
        p = tmp_path / nom
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    return str(tmp_path)


def rad(members: dict[str, bytes]) -> rb.Report:
    """Paketni tekshiradi (fayl tizimisiz)."""
    return rb.validate_runtime_members(members)


def yiqilgan(report: rb.Report) -> set[str]:
    return {c.name for c in report.checks if not c.ok}


def matn(report: rb.Report) -> str:
    return " || ".join(report.problems)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · SHARTNOMA DOIMIYLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_versiyalar_qulflangan():
    assert rb.RUN_VERSION == "binos-1c-run-v1"
    assert rb.ERRORS_VERSION == "binos-1c-errors-v1"
    assert rb.MANIFEST_VERSION == "binos-1c-manifest-v1"


def test_majburiy_va_ixtiyoriy_fayllar_qulflangan():
    assert rb.REQUIRED_FILES == ("errors.json", "export.json", "manifest.json",
                                 "metadata.json", "run_status.json", "run_summary.md")
    assert rb.OPTIONAL_FILES == ("probes/NN_<tur>.json",)
    for tur in PROBE_CATALOG:
        assert rb.PROBE_NAME_RE.fullmatch(f"probes/01_{tur}.json"), tur


def test_runtime_fayl_nomlari_TOPLAM_azolaridan_AJRALGAN():
    """⚠️ NEGA `run_status.json`, `status.json` EMAS: to'plamning (`binos-1c-discovery-v1`)
       a'zolari AYNAN `status.json` va `summary.md` deb ataladi va ularni ADAPTER quradi.
       Bir xil nom ikki xil sxemani anglatsa, operator ham, kod ham noto'g'ri hujjatni
       to'g'ri deb o'qiydi."""
    assert not (set(rb.REQUIRED_FILES) & set(REQUIRED_MEMBERS)), (
        "runtime paketi fayllari to'plam a'zolari bilan kesishmasligi SHART")
    assert "status.json" not in rb.REQUIRED_FILES
    assert "summary.md" not in rb.REQUIRED_FILES
    assert "status.json" in REQUIRED_MEMBERS and "summary.md" in REQUIRED_MEMBERS


def test_rejimlar_va_DEFAULT_metadata_only():
    assert rb.DEFAULT_MODE == rb.MODE_METADATA_ONLY == "METADATA_ONLY"
    assert set(rb.MODES) == {"METADATA_ONLY", "APPROVED_PROBES"}


@pytest.mark.parametrize("kelgan", [None, "", "metadata_only", " METADATA_ONLY",
                                    "APPROVED-PROBES", "RUN_EVERYTHING", 0, True, ["x"]])
def test_notanish_rejim_FAIL_SAFE_metadata_only_ga_tushadi(kelgan):
    """⚠️ Yo'nalish MUHIM: shubha bo'lganda ENG QAT'IY rejim. Teskarisi bitta imlo xatosini
       mijoz bazasida bajariladigan amalga aylantirardi."""
    mode, note = rb.resolve_mode(kelgan)
    assert mode == rb.MODE_METADATA_ONLY
    assert note and "METADATA_ONLY" in note, "tushish JIMGINA bo'lmasligi kerak"


@pytest.mark.parametrize("kelgan", list(rb.MODES))
def test_tanilgan_rejim_ozgarmaydi_va_izoh_yozilmaydi(kelgan):
    assert rb.resolve_mode(kelgan) == (kelgan, None)


def test_manifestda_taqiqlangan_provenans_maydonlari():
    """⚠️ Manifest — YOZILGAN BAYTLARNING xeshi, MANBA provenansi DA'VOSI EMAS."""
    assert rb.FORBIDDEN_MANIFEST_KEYS == ("plan_sha256", "snapshot_at", "source_copy")
    assert rb.MANIFEST_FILE_KEYS == {"name", "bytes", "sha256"}


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · TO'G'RI PAKET O'TADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_TOGRI_paket_hamma_tekshiruvdan_otadi():
    r = rad(paket())
    assert r.ok, matn(r)
    assert r.problems == ()
    assert len(r.checks) == len(rb.CHECK_NAMES)
    assert all(c.ok and c.detail.strip() for c in r.checks)


def test_TOGRI_paket_diskdan_ham_otadi(tmp_path):
    r = rb.validate_runtime_bundle(yoz(tmp_path, paket()))
    assert r.ok, matn(r)


def test_YIQILGAN_bolimi_bor_HALOL_paket_ham_otadi():
    """⚠️ `PARTIAL` — NUQSON EMAS: yiqilish sababi bilan qayd etilgan. Validator paketning
       SHAKLINI tekshiradi, yurishning muvaffaqiyatini emas."""
    r = rad(paket_partial())
    assert r.ok, matn(r)
    doc = json.loads(paket_partial()[rb.RUN_STATUS_FILE].decode("utf-8"))
    assert doc["overall"] == rb.OVERALL_PARTIAL


def test_tekshiruv_nomlari_va_TARTIBI_SHARTNOMA():
    """⚠️ Operator skripti nom bo'yicha filtr yozadi, shu bois nom ham, tartib ham qulflangan."""
    for members in (paket(), {}, paket(drop=[rb.EXPORT_FILE])):
        r = rad(members)
        assert tuple(c.name for c in r.checks) == rb.CHECK_NAMES


def test_BOSH_papka_hamma_tekshiruvni_NUQSON_qiladi():
    """⚠️ FAIL-CLOSED: bajarilmagan tekshiruv `ok=True` BO'LMAYDI — «tekshirib ko'rmadim»
       «muammo yo'q» EMAS."""
    r = rad({})
    assert not r.ok
    assert yiqilgan(r) == set(rb.CHECK_NAMES)
    assert all(c.detail.strip() for c in r.checks)
    assert sum(1 for c in r.checks if c.detail == rb.NOT_RUN) >= 10


def test_YOZILMAGAN_tekshiruv_FAIL_CLOSED():
    """⚠️ MUTATSIYA BILAN TOPILGAN BO'SHLIQ: bugun har bir tekshiruv HAR YO'LDA natija
       yozadi, ya'ni «yozilmagan» holat bo'sh papkada ham yuzaga kelmaydi va uni faqat
       bo'sh papka bilan sinash himoyani O'LCHAMAYDI (`(False, NOT_RUN)` ni `(True, ...)`
       ga o'zgartirish to'plamni qizil qilmasdi). Bu test himoyani TO'G'RIDAN-TO'G'RI
       o'lchaydi: kelasi tekshiruv biror shoxda natija yozishni unutsa, javob `ok=False`
       bo'lishi SHART."""
    ck = rb._Checks()
    ck.ok(rb.CHECK_NAMES[0], "yozildi")
    r = ck.build()
    assert not r.ok
    assert [c.ok for c in r.checks] == [True] + [False] * (len(rb.CHECK_NAMES) - 1)
    assert all(c.detail == rb.NOT_RUN for c in r.checks[1:])
    assert len(r.problems) == len(rb.CHECK_NAMES) - 1


def test_BIRINCHI_yozuv_qoladi_keyingi_OK_eskisini_YUVMAYDI():
    """⚠️ Bir tekshiruv ikki sababdan yiqilsa birinchisi ko'rsatiladi, va keyingi `ok`
       yiqilishni JIMGINA o'chirib tashlamaydi."""
    ck = rb._Checks()
    nom = rb.CHECK_NAMES[0]
    ck.bad(nom, "birinchi sabab")
    ck.ok(nom, "aslida hammasi joyida")
    r = ck.build()
    assert not r.checks[0].ok
    assert r.checks[0].detail == "birinchi sabab"


def test_papka_topilmasa_NUQSON(tmp_path):
    r = rb.validate_runtime_bundle(str(tmp_path / "yoq"))
    assert not r.ok
    assert "majburiy_fayllar" in yiqilgan(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · MAJBURIY FAYLLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("nom", list(rb.REQUIRED_FILES))
def test_HAR_majburiy_fayl_yoqligi_RAD(nom):
    r = rad(paket(drop=[nom]))
    assert not r.ok
    assert "majburiy_fayllar" in yiqilgan(r)
    assert nom in matn(r)


def test_shartnomada_YOQ_fayl_RAD():
    """⚠️ Notanish fayl nima ekani MA'LUM EMAS, lekin u paket bilan qo'ldan-qo'lga o'tadi."""
    m = paket()
    m["qoshimcha.txt"] = b"nima bu?\n"
    r = rad(m)
    assert not r.ok
    assert "majburiy_fayllar" in yiqilgan(r)
    assert "qoshimcha.txt" in matn(r)


def test_bosh_run_summary_RAD():
    r = rad(paket(summary="   \n"))
    assert not r.ok
    assert "majburiy_fayllar" in yiqilgan(r)


def test_UTF8_emas_fayl_RAD():
    r = rad(paket(mutate=lambda m: {**m, rb.RUN_SUMMARY_FILE: b"\xff\xfe salom"}))
    assert not r.ok
    assert "majburiy_fayllar" in yiqilgan(r)


def test_BOM_li_fayl_QABUL_qilinadi():
    """⚠️ 1C va PowerShell BOM qo'shadi — bu nuqson emas, shu bois BOM olib tashlanadi.
       Lekin BOM BAYTLARI manifestga KIRADI: xesh yozilgan baytlarning xeshi."""
    def bom(m):
        yangi = dict(m)
        yangi[rb.RUN_SUMMARY_FILE] = b"\xef\xbb\xbf" + m[rb.RUN_SUMMARY_FILE]
        return yangi
    m = paket()
    m2 = bom(m)
    # BOM qo'shilgani uchun manifest qayta hisoblanadi (aks holda xesh mos kelmaydi).
    files = [{"name": n, "bytes": str(len(m2[n])), "sha256": sha256_bytes(m2[n])}
             for n in sorted(m2) if n != rb.MANIFEST_FILE]
    m2[rb.MANIFEST_FILE] = dumps({"manifest_version": rb.MANIFEST_VERSION, "files": files,
                                  "notes": ["BOM baytlari xeshga KIRADI"]}).encode("utf-8")
    r = rad(m2)
    assert r.ok, matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · BUZUQ JSON · NOMA'LUM VERSIYA · NOMA'LUM KALIT
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("nom", [rb.RUN_STATUS_FILE, rb.ERRORS_FILE, rb.MANIFEST_FILE,
                                 rb.EXPORT_FILE, rb.METADATA_FILE])
def test_BUZUQ_json_RAD(nom):
    r = rad(paket(mutate=lambda m, n=nom: {**m, n: b'{"buzuq": '}))
    assert not r.ok
    assert "json_parse" in yiqilgan(r)
    assert nom in matn(r)


def test_TAKROR_kalit_RAD():
    """⚠️ Takror kalit — JSON'da «oxirgisi yutadi», ya'ni hujjat ikki xil o'qiladi."""
    xom = b'{"run_version":"binos-1c-run-v1","run_version":"boshqa"}\n'
    r = rad(paket(mutate=lambda m: {**m, rb.RUN_STATUS_FILE: xom}))
    assert not r.ok
    assert "json_parse" in yiqilgan(r)
    assert "takror" in matn(r).lower()


VERSIYA_HOLATLARI = [
    (rb.RUN_STATUS_FILE, "run_version"),
    (rb.ERRORS_FILE, "errors_version"),
    (rb.MANIFEST_FILE, "manifest_version"),
    (rb.EXPORT_FILE, "export_version"),
    (rb.METADATA_FILE, "metadata_version"),
]


@pytest.mark.parametrize("nom,kalit", VERSIYA_HOLATLARI, ids=[n for n, _ in VERSIYA_HOLATLARI])
def test_NOMALUM_versiya_RAD(nom, kalit):
    def buz(m, n=nom, k=kalit):
        doc = json.loads(m[n].decode("utf-8"))
        doc[k] = "binos-1c-kelasi-v9"
        return {**m, n: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r)
    assert kalit in matn(r)


KALIT_HOLATLARI = [
    (rb.RUN_STATUS_FILE, ()),
    (rb.ERRORS_FILE, ()),
    (rb.MANIFEST_FILE, ()),
    (rb.EXPORT_FILE, ()),
    (rb.METADATA_FILE, ()),
    (rb.RUN_STATUS_FILE, ("sections", 0)),
    (rb.RUN_STATUS_FILE, ("families", 0)),
    (rb.MANIFEST_FILE, ("files", 0)),
    (rb.METADATA_FILE, ("objects", 0)),
    (rb.EXPORT_FILE, ("candidates", 0)),
]


@pytest.mark.parametrize("nom,yo_l", KALIT_HOLATLARI,
                         ids=[f"{n}:{'.'.join(str(x) for x in y) or 'root'}"
                              for n, y in KALIT_HOLATLARI])
def test_NOMALUM_kalit_RAD(nom, yo_l):
    """⚠️ Oq ro'yxat: yangi maydon faqat SXEMA VERSIYASI oshganda qo'shiladi."""
    def buz(m, n=nom, y=yo_l):
        doc = json.loads(m[n].decode("utf-8"))
        nishon = doc
        for bo_lak in y:
            nishon = nishon[bo_lak]
        nishon["yangi_maydon"] = "x"
        return {**m, n: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r)
    assert "yangi_maydon" in matn(r)


@pytest.mark.parametrize("kalit", sorted(rb.RUN_KEYS))
def test_run_status_da_TUSHIB_QOLGAN_kalit_RAD(kalit):
    def buz(m):
        doc = json.loads(m[rb.RUN_STATUS_FILE].decode("utf-8"))
        doc.pop(kalit)
        return {**m, rb.RUN_STATUS_FILE: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r)


@pytest.mark.parametrize("maydon,qiymat", [
    ("mode", "RUN_EVERYTHING"),
    ("overall", "MAYBE"),
])
def test_run_status_da_NOMALUM_enum_RAD(maydon, qiymat):
    r = rad(paket(run=run_status(**{maydon: qiymat})))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r)
    assert maydon in matn(r)


def test_NOMALUM_bolim_holati_RAD():
    secs = copy.deepcopy(SECTIONS_OK)
    secs[0]["status"] = "maybe"
    r = rad(paket(run=run_status(sections=secs, overall=rb.OVERALL_SUCCESS)))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


@pytest.mark.parametrize("holat", list(rb.FAMILY_STATES))
def test_oila_holatining_UCHOVI_HAM_ruxsat_etilgan(holat):
    """⚠️ Uchovi SHAKLAN qonuniy; farq MA'NODA va u `overall` ziddiyatida o'lchanadi
       (`unreadable` bilan `SUCCESS` yozib bo'lmaydi)."""
    fams = copy.deepcopy(FAMILIES_OK)
    fams[0] = {"name": "catalogs", "state": holat,
               "detail": None if holat == "present" else "sabab yozilgan"}
    if holat == "unreadable":
        secs = copy.deepcopy(SECTIONS_OK)
        secs[1] = {"name": "metadata_sweep", "status": "failed", "error": "o'qilmadi"}
        errors = {**BOSH_ERRORS, "errors": [
            {"scope": "family", "family": "catalogs", "object": None,
             "code": "FAMILY_UNREADABLE", "detail": "o'qilmadi"}]}
        r = rad(paket(errors=errors,
                      run=run_status(sections=secs, families=fams, artifacts=hamma_nom())))
    else:
        r = rad(paket(run=run_status(families=fams, artifacts=hamma_nom())))
    assert "sxema_va_versiya" not in yiqilgan(r), matn(r)


def test_NOMALUM_oila_holati_RAD():
    fams = copy.deepcopy(FAMILIES_OK)
    fams[0]["state"] = "probably_there"
    r = rad(paket(run=run_status(families=fams, artifacts=sorted(rb.REQUIRED_FILES))))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


def test_UNREADABLE_oila_sababsiz_RAD():
    """⚠️ Sababsiz «o'qiy olmadim» — tekshirib bo'lmaydigan da'vo."""
    secs = copy.deepcopy(SECTIONS_OK)
    secs[1] = {"name": "metadata_sweep", "status": "failed", "error": "o'qilmadi"}
    fams = copy.deepcopy(FAMILIES_OK)
    fams[1] = {"name": "documents", "state": "unreadable", "detail": None}
    r = rad(paket(run=run_status(sections=secs, families=fams,
                                 artifacts=sorted(rb.REQUIRED_FILES))))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


def test_ABSENT_oila_sababsiz_QONUNIY():
    """⚠️ `absent` — TO'LIQ javob, u sabab talab qilmaydi (`unreadable` esa talab qiladi)."""
    fams = copy.deepcopy(FAMILIES_OK)
    fams[3] = {"name": "accumulation_registers", "state": "absent", "detail": None}
    r = rad(paket(run=run_status(families=fams, artifacts=sorted(rb.REQUIRED_FILES))))
    assert r.ok, matn(r)


def test_yiqilgan_bolim_SABABSIZ_RAD():
    secs = copy.deepcopy(SECTIONS_OK)
    secs[0] = {"name": "platform", "status": "failed", "error": None}
    r = rad(paket(run=run_status(sections=secs, artifacts=sorted(rb.REQUIRED_FILES))))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


def test_ELON_QILINGAN_overall_HISOBLANGANIGA_MOS_kelishi_SHART():
    """⚠️ Holat YAGONA TA'RIFDAN hisoblanadi — e'lon qilinganiga ishonilmaydi.
    ⚠️ HUKM `overall_ziddiyatsiz` DA, `sxema_va_versiya` DA EMAS: yagona ta'rif bo'limlardan
       tashqari OILALARGA va yozilgan artefaktlarga ham tayanadi, ya'ni bu bir nechta maydonni
       solishtiradigan CROSS-DOCUMENT hukm. U bitta joyda aytiladi, shunda operator bir xil
       nuqsonni ikki xil so'z bilan ikki marta o'qimaydi."""
    r = rad(paket(run=run_status(overall=rb.OVERALL_FAILED)))
    assert not r.ok
    assert "overall_ziddiyatsiz" in yiqilgan(r), matn(r)
    assert "sxema_va_versiya" not in yiqilgan(r), "bu SHAKL xatosi emas, HOLAT ziddiyati"
    assert "hisoblangani" in matn(r)


@pytest.mark.parametrize("scope,family,obyekt", [
    ("run", "catalogs", None),
    ("run", None, "X"),
    ("family", None, None),
    ("family", "catalogs", "X"),
    ("object", "catalogs", None),
    ("object", None, "X"),
    ("probe", "catalogs", None),
])
def test_errors_qamrov_shartnomasi_buzilsa_RAD(scope, family, obyekt):
    errors = {**BOSH_ERRORS, "errors": [
        {"scope": scope, "family": family, "object": obyekt,
         "code": "X_FAILED", "detail": "sabab"}]}
    r = rad(paket(errors=errors))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


def test_errors_kodi_ERKIN_MATN_bolsa_RAD():
    errors = {**BOSH_ERRORS, "errors": [
        {"scope": "run", "family": None, "object": None,
         "code": "nimadir yiqildi", "detail": "sabab"}]}
    r = rad(paket(errors=errors))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


def test_BOSH_errors_royxati_QONUNIY():
    """⚠️ Fayl SHART, mazmuni esa bo'sh bo'lishi MUMKIN: «xato bo'lmadi» ham javob."""
    r = rad(paket(errors={**BOSH_ERRORS, "errors": []}))
    assert r.ok, matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · SANOQ MATN · UCHULIK MANTIQ MATN
# ══════════════════════════════════════════════════════════════════════════════════════════
SANOQ_HOLATLARI = [
    (rb.MANIFEST_FILE, ("files", 0, "bytes"), 123),
    (rb.METADATA_FILE, ("objects", 0, "row_count"), 4021),
    (rb.EXPORT_FILE, ("candidates", 0, "row_count"), 7137),
    (rb.EXPORT_FILE, ("objects", 0, "row_count"), 7137),
]


@pytest.mark.parametrize("nom,yo_l,qiymat", SANOQ_HOLATLARI,
                         ids=[f"{n}:{'.'.join(str(x) for x in y)}" for n, y, _ in SANOQ_HOLATLARI])
def test_sanoq_JSON_SONI_bolsa_RAD(nom, yo_l, qiymat):
    """⚠️ `0000123` soni `123` bo'lib qoladi — PLU va Kod aynan shunday yo'qoladi."""
    def buz(m, n=nom, y=yo_l, q=qiymat):
        doc = json.loads(m[n].decode("utf-8"))
        nishon = doc
        for bo_lak in y[:-1]:
            nishon = nishon[bo_lak]
        nishon[y[-1]] = q
        return {**m, n: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "sanoqlar_matn" in yiqilgan(r), matn(r)
    assert "json_parse" in yiqilgan(r), "qat'iy parse ham sonni RAD etishi kerak"
    # ⚠️ Nuqson matni YO'LNI ko'rsatadi: `strict_json_loads` faqat qiymatni aytadi.
    assert yo_l[-1] in matn(r)


@pytest.mark.parametrize("nom,yo_l", [
    (rb.METADATA_FILE, ("objects", 0, "hierarchical")),
    (rb.EXPORT_FILE, ("platform", "configuration_modified")),
])
def test_uchulik_mantiq_JSON_BOOLEANI_bolsa_RAD(nom, yo_l):
    """⚠️ NEGA BOOLEAN HAM TAQIQLANGAN: `"unknown"` = «qaralmadi», `"false"` = «qaradi va
       yo'q». JSON booleani uchinchi holatni JIMGINA yo'q qiladi.
    ⚠️ `strict_json_loads` booleanni O'TKAZIB YUBORADI — ya'ni bu darvoza QO'SHIMCHA va
       shu test uni aynan shunday isbotlaydi (`json_parse` YASHIL qoladi)."""
    def buz(m, n=nom, y=yo_l):
        doc = json.loads(m[n].decode("utf-8"))
        nishon = doc
        for bo_lak in y[:-1]:
            nishon = nishon[bo_lak]
        nishon[y[-1]] = True
        return {**m, n: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "sanoqlar_matn" in yiqilgan(r), matn(r)
    assert "json_parse" not in yiqilgan(r), "boolean qat'iy parse'dan o'tadi — darvoza ALOHIDA"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · OBYEKT NOYOBLIGI VA HAVOLA BUTUNLIGI
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("nom", [rb.EXPORT_FILE, rb.METADATA_FILE])
def test_TAKROR_full_name_RAD(nom):
    """⚠️ Takror `full_name` — ikki BOSHQA javobning BITTA manzilda turishi."""
    def buz(m, n=nom):
        doc = json.loads(m[n].decode("utf-8"))
        doc["objects"].append(copy.deepcopy(doc["objects"][0]))
        return {**m, n: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "obyekt_noyobligi" in yiqilgan(r), matn(r)


def test_KORILMAGAN_obyektga_ishora_RAD():
    """⚠️ Yig'uvchi KO'RMAGAN narsaga xarita qura olmaydi — bu dalil emas, TAXMIN."""
    e = export_dict()
    e["candidates"][0]["source_object"] = "Справочник.Bunday_Obyekt_Yoq"
    r = rad(paket(export=e))
    assert not r.ok
    assert "havola_butunligi" in yiqilgan(r), matn(r)


def test_ANIQLANMAGAN_havola_NUQSON_EMAS():
    """⚠️ Konfiguratsiya bo'lak-bo'lak olinishi mumkin: hujjatda yo'q obyektga havola
       SAQLANADI, rad ETILMAYDI — jimgina o'chirish ma'lumot yo'qotish bo'lardi."""
    md = copy.deepcopy(CONFIG_A_STANDARD_RU)
    md["objects"][0]["attributes"][5]["reference_targets"] = ["Справочник.Tashqi_Royxat"]
    r = rad(paket(metadata=md))
    assert r.ok, matn(r)
    detal = next(c.detail for c in r.checks if c.name == "havola_butunligi")
    assert "aniqlanmagan havola" in detal and "NUQSON EMAS" in detal


def test_QARALMAGAN_oilaning_xatosi_RAD():
    errors = {**BOSH_ERRORS, "errors": [
        {"scope": "family", "family": "bunday_oila_yoq", "object": None,
         "code": "FAMILY_UNREADABLE", "detail": "o'qilmadi"}]}
    secs = copy.deepcopy(SECTIONS_OK)
    secs[1] = {"name": "metadata_sweep", "status": "failed", "error": "o'qilmadi"}
    r = rad(paket(errors=errors,
                  run=run_status(sections=secs, artifacts=sorted(rb.REQUIRED_FILES))))
    assert not r.ok
    assert "havola_butunligi" in yiqilgan(r), matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · YIG'UVCHIDAN `VERIFIED` YO'Q · BSL DAN `confidence` YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_VERIFIED_bolsa_RAD():
    """⚠️ Yig'uvchi o'zini o'zi tasdiqlay olmaydi: u hali BIRORTA haqiqiy konfiguratsiyada
       ishlamagan. `VERIFIED` faqat odam ko'rigidan keladi."""
    e = export_dict()
    e["notes"].append("bu xarita VERIFIED deb belgilandi")
    r = rad(paket(export=e))
    assert not r.ok
    assert "yiguvchidan_verified_yoq" in yiqilgan(r), matn(r)


def test_UNVERIFIED_QONUNIY_va_RAD_ETILMAYDI():
    """⚠️ SO'Z CHEGARASI SHART: yig'uvchining halol versiyasi `0.1.0-UNVERIFIED`. Bo'lak
       qidiruvi HAR BIR halol paketni rad etib, darvozani o'chirishga olib kelardi."""
    assert "UNVERIFIED" in COLLECTOR["version"]
    r = rad(paket())
    assert r.ok, matn(r)
    assert not rb.VERIFIED_WORD_RE.search("0.1.0-UNVERIFIED")
    assert rb.VERIFIED_WORD_RE.search('"confidence":"VERIFIED"')


@pytest.mark.parametrize("nom", [rb.RUN_SUMMARY_FILE, rb.METADATA_FILE])
def test_VERIFIED_har_qaysi_faylda_tutiladi(nom):
    def buz(m, n=nom):
        if n == rb.RUN_SUMMARY_FILE:
            return {**m, n: (SUMMARY_MD + "\nHolat: VERIFIED\n").encode("utf-8")}
        doc = json.loads(m[n].decode("utf-8"))
        doc["notes"].append("VERIFIED")
        return {**m, n: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok and "yiguvchidan_verified_yoq" in yiqilgan(r)


@pytest.mark.parametrize("kind", ["human_confirmed", "arithmetic_proof", "absence_proven"])
def test_KUCHLI_dalil_turi_yiguvchidan_kelmaydi(kind):
    """⚠️ Kuchli dalil zonddan ham, metadata razvedkasidan ham CHIQMAYDI. `validate_export`
       uni O'TKAZADI (u umumiy dalil lug'atini biladi), shu bois darvoza SHU YERDA."""
    e = export_dict()
    e["candidates"][0]["evidence"] = [{"kind": kind, "detail": "shunday deydi"}]
    r = rad(paket(export=e))
    assert not r.ok
    assert "yiguvchidan_verified_yoq" in yiqilgan(r), matn(r)
    assert "sxema_va_versiya" not in yiqilgan(r), "bu shakl xatosi emas, DA'VO xatosi"


@pytest.mark.parametrize("nom,yo_l", [
    (rb.EXPORT_FILE, ("objects", 0)),
    (rb.EXPORT_FILE, ("counts", 0)),
])
def test_export_da_confidence_kaliti_bolsa_RAD(nom, yo_l):
    """⚠️ 1C tomoni ISHONCH DARAJASI BERMAYDI — u faqat KO'RGANINI yozadi, darajani BinOS
       tomoni hisoblaydi. `validate_export` `objects`/`counts` ni FAQAT ro'yxat deb ko'radi,
       ya'ni ichma-ich yashiringan `confidence` shu darvozadan boshqa joyda tutilmaydi."""
    def buz(m, n=nom, y=yo_l):
        doc = json.loads(m[n].decode("utf-8"))
        nishon = doc
        for bo_lak in y:
            nishon = nishon[bo_lak]
        nishon["confidence"] = "CANDIDATE"
        return {**m, n: dumps(doc).encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "bsl_dan_confidence_yoq" in yiqilgan(r), matn(r)


def test_zond_faylida_confidence_bolsa_RAD():
    p = probe_doc()
    p["result"] = {"confidence_score": "0.9"}
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES, probes={"01_row_count": p}))
    assert not r.ok
    assert "bsl_dan_confidence_yoq" in yiqilgan(r), matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8 · SIRLAR — FAIL-CLOSED, QIYMAT EKRANGA CHIQMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ To'rt tildagi parol + ulanish satri + fayl yo'li. Har biri REAL oqim: yig'uvchi 1C ning
#: xato tavsifini hisobotga qo'yadi, SUBD xatolari esa baza faylining to'liq yo'lini oladi;
#: operator esa izohni O'Z TILIDA yozadi.
SIR_HOLATLARI = [
    ("lotin_parol", "Diqqat: parol: 4471 bilan kirdim\n", "4471"),
    ("kirill_parol", "Diqqat: пароль — 4471 bilan kirdim\n", "4471"),
    ("qirgiz_sirsoz", "Diqqat: сырсөз: 4471 bilan kirdim\n", "4471"),
    ("uzbek_kirill", "Diqqat: махфий сўз – 4471 bilan kirdim\n", "4471"),
    ("ulanish_satri", "Ulanish: Srvr=SRV1;Ref=baza;Usr=admin;Pwd=hunter2\n", "hunter2"),
    ("windows_yoli", "Baza: C:\\bazalar\\1Cv8.1CD ochilmadi\n", "bazalar"),
    ("email", "Aloqa: admin@dokon.example.com\n", "admin@dokon.example.com"),
    ("masofaviy_kirish", "AnyDesk: 123 456 789 orqali ulandim\n", "123 456 789"),
]


@pytest.mark.parametrize("nomi,satr,qiymat", SIR_HOLATLARI, ids=[h[0] for h in SIR_HOLATLARI])
def test_run_summary_dagi_SIR_RAD(nomi, satr, qiymat):
    """⚠️ FAIL-CLOSED: yolg'on ijobiy — bir marta qo'lda ko'rish; yolg'on salbiy — mijozning
       paroli paket bilan birga tarqaladi."""
    r = rad(paket(summary=SUMMARY_MD + satr))
    assert not r.ok
    assert {"maxfiylik_skani", "taqiqlangan_sir_naqshlari"} <= yiqilgan(r), matn(r)


@pytest.mark.parametrize("nomi,satr,qiymat", SIR_HOLATLARI, ids=[h[0] for h in SIR_HOLATLARI])
def test_nuqson_matnida_SIRNING_OZI_KORSATILMAYDI(nomi, satr, qiymat):
    """⚠️ Nuqson matni operator ekranidan jurnalga, jurnaldan xabar almashinuviga ko'chadi."""
    r = rad(paket(summary=SUMMARY_MD + satr))
    hammasi = matn(r) + " || " + " ".join(c.detail for c in r.checks)
    assert qiymat not in hammasi, f"sir qiymati nuqson matniga chiqib ketdi: {nomi}"


def test_errors_ICHIDAGI_sir_RAD():
    """⚠️ REAL OQIM: SUBD xatosi baza faylining TO'LIQ YO'LINI o'z ichiga oladi va yig'uvchi
       o'sha matnni `errors` ga qo'yadi."""
    errors = {**BOSH_ERRORS, "errors": [
        {"scope": "run", "family": None, "object": None, "code": "DB_OPEN_FAILED",
         "detail": "ochilmadi: C:\\bazalar\\1Cv8.1CD"}]}
    secs = copy.deepcopy(SECTIONS_OK)
    secs[1] = {"name": "metadata_sweep", "status": "failed", "error": "baza ochilmadi"}
    r = rad(paket(errors=errors,
                  run=run_status(sections=secs, artifacts=sorted(rb.REQUIRED_FILES))))
    assert not r.ok
    assert {"maxfiylik_skani", "taqiqlangan_sir_naqshlari"} <= yiqilgan(r), matn(r)
    assert "bazalar" not in matn(r)


def test_SIR_NOMLI_kalit_RAD():
    """⚠️ Sir nomli kalit ostidagi HAMMA narsa shubhali — QIYMATIGA qaralmaydi. Bu strukturali
       skanning ishi: XOM MATN skani kalit nomlarini ATAYLAB qaramaydi (qonuniy metadata
       nomlari rad etilmasligi uchun), shu bois ikki skan bir-birini QOPLAMAYDI."""
    p = probe_doc()
    p["result"] = {"api_key": "x"}
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES, probes={"01_row_count": p}))
    assert not r.ok
    assert "maxfiylik_skani" in yiqilgan(r), matn(r)
    assert "taqiqlangan_sir_naqshlari" not in yiqilgan(r), (
        "xom matn skani kalit NOMINI qaramasligi kerak — qamrov chegarasi OCHIQ yozilgan")


def test_BUZUQ_json_da_ham_XOM_MATN_skani_ishlaydi():
    """⚠️ NEGA IKKI SKAN KERAK: `redact.scan` PARSE QILINGAN hujjatni kezadi, ya'ni JSON
       buzuq bo'lsa u UMUMAN ishlamaydi va sir hech kim ko'rmasdan paket bilan ketardi."""
    xom = b'{"buzuq": "Pwd=hunter2"'
    r = rad(paket(mutate=lambda m: {**m, rb.ERRORS_FILE: xom}))
    assert not r.ok
    assert "json_parse" in yiqilgan(r)
    assert "taqiqlangan_sir_naqshlari" in yiqilgan(r), matn(r)
    assert "hunter2" not in matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9 · MANIFEST VA XESH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_manifest_xeshi_MOS_KELMASA_RAD():
    """⚠️ Xesh mos kelmasa fayl manifest yozilgandan KEYIN o'zgargan (yoki ko'chirishda
       buzilgan) — ikkisi ham paketni ishonchsiz qiladi."""
    def buz(m):
        return {**m, rb.RUN_SUMMARY_FILE: (SUMMARY_MD + "\nqo'shimcha satr\n").encode("utf-8")}
    r = rad(paket(mutate=buz))
    assert not r.ok
    assert "xesh_manifest_mosligi" in yiqilgan(r), matn(r)
    assert "sha256" in matn(r) or "bayt hajmi" in matn(r)


def test_manifest_xeshi_BAYT_HAJMI_MOS_bolganda_HAM_solishtiriladi():
    """⚠️ MUTATSIYA BILAN TOPILGAN BO'SHLIQ: ilgari xesh nuqsoni faqat MAZMUNNI o'zgartirib
       sinalardi, ya'ni BAYT HAJMI ham o'zgarardi va hajm tekshiruvining o'zi «tutib» turardi.
       Xesh solishtiruvini butunlay o'chirib qo'ysa ham to'plam yashil qolardi. Bu yerda hajm
       TO'G'RI, xesh esa BOSHQA — ya'ni faqat xesh darvozasi ishlaydi."""
    m0 = paket()
    files = copy.deepcopy(json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))["files"])
    for f in files:
        if f["name"] == rb.RUN_SUMMARY_FILE:
            f["sha256"] = "0" * 64
    r = rad(paket(manifest_files=files))
    assert not r.ok
    assert "xesh_manifest_mosligi" in yiqilgan(r), matn(r)
    assert "MOS KELMADI" in matn(r)


def test_manifest_BAYT_HAJMI_mos_kelmasa_RAD():
    """⚠️ Hajm darvozasi ALOHIDA sinaladi: xesh to'g'ri, hajm esa yolg'on."""
    m0 = paket()
    files = copy.deepcopy(json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))["files"])
    for f in files:
        if f["name"] == rb.RUN_SUMMARY_FILE:
            f["bytes"] = "1"
    r = rad(paket(manifest_files=files))
    assert not r.ok
    assert "xesh_manifest_mosligi" in yiqilgan(r), matn(r)
    assert "bayt hajmi" in matn(r)


def test_manifestda_FAYL_YOQ_bolsa_RAD():
    m0 = paket()
    files = json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))["files"]
    qisqa = [f for f in files if f["name"] != rb.ERRORS_FILE]
    r = rad(paket(manifest_files=qisqa))
    assert not r.ok
    assert "xesh_manifest_mosligi" in yiqilgan(r), matn(r)
    assert rb.ERRORS_FILE in matn(r)


def test_manifestda_PAPKADA_YOQ_fayl_RAD():
    m0 = paket()
    files = json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))["files"]
    files = files + [{"name": "probes/07_row_count.json", "bytes": "10",
                      "sha256": "0" * 64}]
    r = rad(paket(manifest_files=files))
    assert not r.ok
    assert "xesh_manifest_mosligi" in yiqilgan(r), matn(r)


def test_manifest_OZINI_xeshlay_olmaydi():
    """⚠️ AYLANMA: o'z xeshini o'z ichiga yozish xeshni o'zgartiradi."""
    m0 = paket()
    files = json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))["files"]
    files = files + [{"name": rb.MANIFEST_FILE, "bytes": "10", "sha256": "0" * 64}]
    r = rad(paket(manifest_files=files))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_manifestda_NULL_xesh_RAD():
    """⚠️ `null` — «xeshlay olmadim», ya'ni fayl buzilganini ISBOTLAB BO'LMAYDI. Fail-closed."""
    m0 = paket()
    files = copy.deepcopy(json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))["files"])
    files[0]["sha256"] = None
    r = rad(paket(manifest_files=files))
    assert not r.ok
    assert "xesh_manifest_mosligi" in yiqilgan(r), matn(r)


@pytest.mark.parametrize("kalit", list(rb.FORBIDDEN_MANIFEST_KEYS))
def test_manifestda_PROVENANS_dalvosi_RAD(kalit):
    """⚠️ `source_copy`/`snapshot_at`/`plan_sha256` metadata razvedkasidan KELIB CHIQMAYDI:
       yig'uvchi qaysi nusxada ishlayotganini bila olmaydi."""
    m0 = paket()
    doc = json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))
    doc[kalit] = "x"
    r = rad(paket(manifest=doc))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)
    assert kalit in matn(r)
    assert "provenansi" in matn(r)


def test_manifest_xesh_SHAKLI_qatiy():
    m0 = paket()
    files = copy.deepcopy(json.loads(m0[rb.MANIFEST_FILE].decode("utf-8"))["files"])
    files[0]["sha256"] = files[0]["sha256"].upper()
    r = rad(paket(manifest_files=files))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10 · ARTEFAKT DA'VOSI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_artifacts_da_SANALMAGAN_fayl_RAD():
    nomlar = [n for n in sorted(rb.REQUIRED_FILES) if n != rb.ERRORS_FILE]
    r = rad(paket(run=run_status(artifacts=nomlar)))
    assert not r.ok
    assert "artefakt_dalvosi" in yiqilgan(r), matn(r)
    assert rb.ERRORS_FILE in matn(r)


def test_artifacts_PAPKADA_YOQ_faylni_dalvo_qilsa_RAD():
    nomlar = sorted(set(rb.REQUIRED_FILES) | {"probes/01_row_count.json"})
    r = rad(paket(run=run_status(artifacts=nomlar)))
    assert not r.ok
    assert "artefakt_dalvosi" in yiqilgan(r), matn(r)


def test_artifacts_shartnomada_YOQ_nomni_qabul_qilmaydi():
    nomlar = sorted(set(rb.REQUIRED_FILES) | {"boshqa.json"})
    r = rad(paket(run=run_status(artifacts=nomlar)))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 11 · `UNKNOWN` TO'LIQLIGI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_HAR_nishon_qayd_etiladi_qidirilmagani_UNKNOWN():
    """⚠️ Jim tushib qolgan nishon eng xavfli nosozlik: hisobot TO'LIQ ko'rinadi, aslida esa
       savol berilmagan."""
    r = rad(paket())
    detal = next(c.detail for c in r.checks if c.name == "unknown_toliqligi")
    assert str(len(TARGETS)) in detal
    assert "UNKNOWN=" in detal and "CANDIDATE=" in detal


def test_nishon_shartnomadan_TASHQARI_bolsa_RAD():
    e = export_dict()
    e["candidates"][0]["target"] = "products.bunday_maydon_yoq"
    r = rad(paket(export=e))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_TAKROR_nishon_RAD():
    e = export_dict()
    e["candidates"].append(copy.deepcopy(e["candidates"][0]))
    r = rad(paket(export=e))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_MANBA_korsatilgan_lekin_DALIL_yoq_bolsa_sabab_YOZILADI():
    """⚠️ Dalilsiz manba — UNKNOWN, va u SABABSIZ qolmaydi (`export_adapter` sababni yozadi)."""
    e = export_dict()
    e["candidates"][0]["evidence"] = []
    r = rad(paket(export=e))
    assert r.ok, matn(r)
    detal = next(c.detail for c in r.checks if c.name == "unknown_toliqligi")
    assert "UNKNOWN=" in detal


# ══════════════════════════════════════════════════════════════════════════════════════════
# 12 · GRAF VA AI KIRISHI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_graf_va_AI_yuki_qurilishi_tekshiriladi():
    r = rad(paket())
    graf = next(c for c in r.checks if c.name == "graf_qurilishi")
    ai_c = next(c for c in r.checks if c.name == "ai_kirishiga_tayyor")
    assert graf.ok and ai_c.ok
    assert "TASDIQ EMAS" in graf.detail, "graf qurilishi TASDIQ deb o'qilmasin"
    assert "YUBORILMADI" in ai_c.detail and "tarmoq YO'Q" in ai_c.detail


def test_buzuq_metadata_grafni_va_AI_yukini_TOXTATADI():
    md = copy.deepcopy(CONFIG_A_STANDARD_RU)
    md["objects"][0]["attributes"][0]["name"] = 'Kod"; DROP'
    r = rad(paket(metadata=md))
    assert not r.ok
    assert {"graf_qurilishi", "ai_kirishiga_tayyor"} <= yiqilgan(r), matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 13 · REJIM DARVOZASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_METADATA_ONLY_da_zond_fayli_RAD():
    """⚠️ DEFAULT rejimda AKTIV ZOND YO'Q — na faylda, na qaydda."""
    r = rad(paket(mode=rb.MODE_METADATA_ONLY, probes={"01_row_count": probe_doc()},
                  probes_log=[]))
    assert not r.ok
    assert "rejim_darvozasi" in yiqilgan(r), matn(r)


def test_METADATA_ONLY_da_qayd_etilgan_zond_RAD():
    r = rad(paket(mode=rb.MODE_METADATA_ONLY,
                  probes_log=[zond_qaydi("row_count")]))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_APPROVED_PROBES_TOGRI_paket_otadi():
    m = paket(mode=rb.MODE_APPROVED_PROBES,
              probes={"01_row_count": probe_doc("row_count"),
                      "02_enum_values": probe_doc("enum_values", target=REGISTER)})
    r = rad(m)
    assert r.ok, matn(r)
    detal = next(c.detail for c in r.checks if c.name == "rejim_darvozasi")
    assert "APPROVED_PROBES" in detal and "row_count" in detal


def test_APPROVED_PROBES_da_zond_BOLMASA_RAD():
    """⚠️ Bo'sh allowlist bilan aktiv rejim yozish — rejim haqida YOLG'ON."""
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_qayd_etilmagan_zond_fayli_RAD():
    """⚠️ Operator tasdiqlagan ALLOWLIST bilan bajarilgan ish AYNAN mos bo'lishi SHART."""
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes={"01_row_count": probe_doc("row_count"),
                          "02_enum_values": probe_doc("enum_values", target=REGISTER)},
                  probes_log=[zond_qaydi("row_count")]))
    assert not r.ok
    assert "rejim_darvozasi" in yiqilgan(r), matn(r)
    assert "enum_values" in matn(r)


def test_KATALOGDA_YOQ_zond_nomi_RAD():
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes_log=[zond_qaydi("run_sql")]))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_zond_fayli_nomi_va_ICHI_MOS_kelishi_SHART():
    """⚠️ `ls` qiladigan operator va JSON o'qiydigan kod BIR XIL narsani ko'rishi kerak."""
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes={"01_row_count": probe_doc("enum_values")},
                  probes_log=[zond_qaydi("row_count")]))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


@pytest.mark.parametrize("qiymat", [True, "false", "TRUE", None])
def test_zond_read_only_AYNAN_true_MATNI(qiymat):
    """⚠️ Yozuvchi zond MAVJUD EMAS va bo'lishi ham mumkin emas."""
    p = probe_doc()
    p["read_only"] = qiymat
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES, probes={"01_row_count": p}))
    assert not r.ok
    assert {"sxema_va_versiya"} <= yiqilgan(r) or "sanoqlar_matn" in yiqilgan(r), matn(r)


def test_zond_faylining_TARTIB_raqami_NOYOB():
    """⚠️ `NN` — bajarilish O'RNI, ikki zond bir o'rinda tura olmaydi."""
    m = paket(mode=rb.MODE_APPROVED_PROBES,
              probes={"01_row_count": probe_doc("row_count"),
                      "01_enum_values": probe_doc("enum_values", target=REGISTER)})
    r = rad(m)
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_mode_note_HAR_IKKI_REJIMDA_ruxsat_etiladi():
    """⚠️ SHAKL QARORI: `mode_note` «rejim QANDAY hal bo'ldi» degan savolga javob beradi va
       u HAR REJIMDA to'ldirilishi mumkin. Ilgari bu yerda `APPROVED_PROBES` uchun `null`
       TALAB qilinardi — yig'uvchi esa izohni har yurishda yozadi, ya'ni talab operator
       tasdiqlagan HAR BIR aktiv zond yurishini rad etardi."""
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes={"01_row_count": probe_doc()},
                  run=run_status(mode=rb.MODE_APPROVED_PROBES,
                                 mode_note="operator ANIQ allowlist tasdiqladi",
                                 probes_log=[zond_qaydi("row_count")],
                                 artifacts=sorted(set(rb.REQUIRED_FILES)
                                                  | {"probes/01_row_count.json"}))))
    assert r.ok, matn(r)
    detal = next(c.detail for c in r.checks if c.name == "rejim_darvozasi")
    assert "izoh" in detal, "rejim izohi hisobotda KO'RSATILADI"


def test_mode_note_fail_safe_tushishini_QAYD_etadi():
    mode, note = rb.resolve_mode("hammasini_ishlat")
    r = rad(paket(run=run_status(mode=mode, mode_note=note,
                                 artifacts=sorted(rb.REQUIRED_FILES))))
    assert r.ok, matn(r)
    detal = next(c.detail for c in r.checks if c.name == "rejim_darvozasi")
    assert "fail-safe" in detal


# ══════════════════════════════════════════════════════════════════════════════════════════
# 14 · `overall` ZIDDIYATI (§6 ning oxirgi bandi)
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("nom", list(rb.REQUIRED_FILES))
def test_SUCCESS_lekin_ARTEFAKT_YOQ_ZIDDIYAT(nom):
    """⚠️ Ziddiyat oddiy nuqsondan QO'RQINCHLIROQ: u paketning O'Z hisobotiga ishonib
       bo'lmasligini ko'rsatadi."""
    r = rad(paket(drop=[nom]))
    assert not r.ok
    if nom == rb.RUN_STATUS_FILE:
        # ⚠️ Yurish yozuvi o'zi yo'q bo'lsa ziddiyatni O'LCHAB ham bo'lmaydi — fail-closed.
        assert next(c for c in r.checks if c.name == "overall_ziddiyatsiz").detail == rb.NOT_RUN
        return
    assert "overall_ziddiyatsiz" in yiqilgan(r), matn(r)
    assert "ZIDDIYAT" in matn(r) and nom in matn(r)


def test_SUCCESS_lekin_XATO_ROYXATI_TOLA_ZIDDIYAT():
    """⚠️ Birorta bo'limni yiqitmagan xato — JIMGINA tushib qolgan nosozlik."""
    errors = {**BOSH_ERRORS, "errors": [
        {"scope": "run", "family": None, "object": None, "code": "SOMETHING_FAILED",
         "detail": "nimadir yiqildi, lekin bo'lim ok deb qoldi"}]}
    r = rad(paket(errors=errors))
    assert not r.ok
    assert "overall_ziddiyatsiz" in yiqilgan(r), matn(r)
    assert "ZIDDIYAT" in matn(r)


def test_SUCCESS_lekin_OQILMAGAN_OILA_ZIDDIYAT():
    """⚠️ `unreadable` — javob YO'QLIGI; u bilan yurish muvaffaqiyatli deb e'lon qilinmaydi."""
    fams = copy.deepcopy(FAMILIES_OK)
    fams[1] = {"name": "documents", "state": "unreadable", "detail": "huquq yetmadi"}
    r = rad(paket(run=run_status(families=fams, artifacts=sorted(rb.REQUIRED_FILES))))
    assert not r.ok
    assert "overall_ziddiyatsiz" in yiqilgan(r), matn(r)
    assert "ZIDDIYAT" in matn(r)


def test_PARTIAL_da_xato_royxati_TOLA_bolishi_QONUNIY():
    r = rad(paket_partial())
    assert r.ok, matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 15 · CLI — CHIQISH KODI SHARTNOMASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def ishlat(argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    kod = cli.main(argv, out=out, err=err)
    return kod, out.getvalue(), err.getvalue()


def test_CLI_chiqish_kodi_0_hammasi_otganda(tmp_path):
    kod, out, _ = ishlat([cli.VALIDATE_CMD, yoz(tmp_path, paket())])
    assert kod == cli.EXIT_OK == 0
    assert out.count(cli.MARK_OK) == len(rb.CHECK_NAMES)
    assert cli.MARK_BAD not in out
    assert "HAMMASI O'TDI" in out


def test_CLI_chiqish_kodi_1_nuqson_borda(tmp_path):
    kod, out, _ = ishlat([cli.VALIDATE_CMD, yoz(tmp_path, paket(drop=[rb.ERRORS_FILE]))])
    assert kod == cli.EXIT_PROBLEM == 1
    assert cli.MARK_BAD in out
    assert "NUQSON BOR" in out


def test_CLI_papka_yoq_bolsa_ham_HUKM_beradi(tmp_path):
    """⚠️ Papka yo'qligi — paket haqidagi HUKM (majburiy fayllar yo'q), buyruq xatosi EMAS."""
    kod, out, _ = ishlat([cli.VALIDATE_CMD, str(tmp_path / "yoq")])
    assert kod == cli.EXIT_PROBLEM
    assert "papka topilmadi" in out


@pytest.mark.parametrize("argv", [[], ["validate"], [cli.VALIDATE_CMD],
                                  [cli.VALIDATE_CMD, "x", "--nomalum"]])
def test_CLI_buyruq_xatosi_2(argv):
    """⚠️ `2` — buyruqni tuzat, `1` — paket yaroqsiz. Operator skripti ikkisini
       ARALASHTIRMASLIGI kerak."""
    kod, _, _ = ishlat(argv)
    assert kod == cli.EXIT_USAGE == 2


def test_CLI_help_NUQSON_emas():
    kod, _, _ = ishlat(["--help"])
    assert kod == cli.EXIT_OK


def test_CLI_hamma_tekshiruvni_KORSATADI(tmp_path):
    kod, out, _ = ishlat([cli.VALIDATE_CMD, yoz(tmp_path, paket(drop=[rb.ERRORS_FILE]))])
    for nom in rb.CHECK_NAMES:
        assert nom in out, nom
    assert str(tmp_path) in out, "odam o'qiydigan hisobotda papka YO'LI ko'rsatiladi"


def test_CLI_SIRNI_ekranga_CHIQARMAYDI(tmp_path):
    """⚠️ CLI chiqishi jurnalga tushadi, jurnal esa qo'ldan-qo'lga o'tadi."""
    m = paket(summary=SUMMARY_MD + "Ulanish: Srvr=SRV1;Usr=admin;Pwd=hunter2\n")
    kod, out, _ = ishlat([cli.VALIDATE_CMD, yoz(tmp_path, m)])
    assert kod == cli.EXIT_PROBLEM
    assert "hunter2" not in out
    assert "1c_connection_string" in out


# ══════════════════════════════════════════════════════════════════════════════════════════
# 16 · CLI `--json` — DETERMINIZM
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_CLI_json_shakli(tmp_path):
    kod, out, _ = ishlat([cli.VALIDATE_CMD, yoz(tmp_path, paket()), "--json"])
    assert kod == cli.EXIT_OK
    doc = json.loads(out)
    assert doc["report_version"] == rb.REPORT_VERSION
    assert doc["ok"] is True
    assert [c["name"] for c in doc["checks"]] == list(rb.CHECK_NAMES)
    assert doc["problems"] == []


def test_CLI_json_DETERMINISTIK_va_PAPKA_YOLINI_tashimaydi(tmp_path):
    """⚠️ Papka yo'li chiqishda bo'lsa AYNI paketning ikki nusxasi ikki xil bayt berardi."""
    m = paket()
    bir = tmp_path / "bir"
    ikki = tmp_path / "ikki"
    bir.mkdir()
    ikki.mkdir()
    _, out1, _ = ishlat([cli.VALIDATE_CMD, yoz(bir, m), "--json"])
    _, out2, _ = ishlat([cli.VALIDATE_CMD, yoz(ikki, m), "--json"])
    assert out1 == out2, "bir xil paket — AYNAN bir xil baytlar"
    assert out1.encode("utf-8") == out2.encode("utf-8")
    assert str(bir) not in out1 and str(ikki) not in out2
    assert "folder" not in json.loads(out1)


def test_CLI_json_NUQSONLI_paketda_ham_DETERMINISTIK(tmp_path):
    m = paket(drop=[rb.ERRORS_FILE])
    bir = tmp_path / "a"
    ikki = tmp_path / "b"
    bir.mkdir()
    ikki.mkdir()
    kod1, out1, _ = ishlat([cli.VALIDATE_CMD, yoz(bir, m), "--json"])
    kod2, out2, _ = ishlat([cli.VALIDATE_CMD, yoz(ikki, m), "--json"])
    assert kod1 == kod2 == cli.EXIT_PROBLEM
    assert out1 == out2
    doc = json.loads(out1)
    assert doc["ok"] is False and doc["problems"]


def test_hisobot_json_matni_DETERMINISTIK():
    m = paket()
    birinchi = rb.report_to_json_text(rad(m))
    ikkinchi = rb.report_to_json_text(rad(dict(m)))
    assert birinchi == ikkinchi
    assert birinchi.endswith("\n")


def test_problems_yiqilgan_tekshiruvlar_bilan_AYNI_TARTIBDA():
    """⚠️ Alfavit bo'yicha tartiblash nuqsonni uni TOPGAN tekshiruvdan ajratardi."""
    r = rad({})
    assert list(r.problems) == [f"{c.name}: {c.detail}" for c in r.checks if not c.ok]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 17 · STATIK: TARMOQ YO'Q, 1C GA ULANISH YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
YANGI_FAYLLAR = ("runtime_bundle.py", "cli.py")


def manba(nom: str) -> str:
    import app.services.discovery_1c as pkg
    return (pathlib.Path(pkg.__file__).parent / nom).read_text(encoding="utf-8")


@pytest.mark.parametrize("nom", YANGI_FAYLLAR)
def test_tarmoq_va_COM_importi_YOQ(nom):
    """⚠️ Validator OFFLINE: u faqat papkani o'qiydi. AI provayderi ham KERAK EMAS."""
    text = manba(nom)
    for tok in ("socket", "requests", "urllib", "httpx", "aiohttp", "subprocess",
                "win32com", "pythoncom", "ctypes", "comtypes", "anthropic", "openai"):
        assert f"import {tok}" not in text and f"from {tok}" not in text, f"{nom}: {tok}"


@pytest.mark.parametrize("nom", YANGI_FAYLLAR)
def test_migrator_paketiga_TEGILMAYDI(nom):
    """⚠️ Bu bosqichda `migrator_1c` ga TEGISH TAQIQLANGAN — faqat `bundle` yordamchilari
       (xesh, qat'iy JSON, vaqt tahlili) O'QILADI, boshqa modul IMPORT QILINMAYDI."""
    for line in manba(nom).splitlines():
        if re.match(r"\s*(?:from|import)\s", line) and "migrator_1c" in line:
            assert "migrator_1c.bundle import" in line, line


def test_paket_yozish_amali_YOQ():
    """⚠️ Validator HECH NARSA YOZMAYDI: «tuzatib qo'yish» nuqsonni yashirish va asl
       baytlarni yo'qotish bo'lardi."""
    text = manba("runtime_bundle.py")
    for tok in ("os.makedirs", "shutil", '"wb"', "'wb'", '"w"', "os.remove", "os.rename"):
        assert tok not in text, f"runtime_bundle.py da yozish amali: {tok}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 18 · VALIDATOR FAIL-CLOSED: `overall != SUCCESS` PAKET KEYINGI BOSQICHGA O'TMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_SABABSIZ_yiqilish_ZIDDIYAT():
    """⚠️ `overall` `SUCCESS` EMAS, lekin `errors.json` BO'SH — sababi ko'rsatilmagan
       yiqilish. Bu ziddiyat: bo'lim «yiqildim» deydi, xato ro'yxati «hech narsa bo'lmadi»
       deydi. Ilgari `overall_ziddiyatsiz` FAQAT `SUCCESS` shoxini tekshirardi, ya'ni bunday
       paket 17/17 tekshiruvdan o'tib, chiqish kodi `0` olardi."""
    secs = copy.deepcopy(SECTIONS_OK)
    secs[1] = {"name": "metadata_sweep", "status": "failed", "error": "oila o'qilmadi"}
    r = rad(paket(errors=copy.deepcopy(BOSH_ERRORS),
                  run=run_status(sections=secs, artifacts=sorted(rb.REQUIRED_FILES))))
    assert not r.ok, matn(r)
    assert "overall_ziddiyatsiz" in yiqilgan(r), matn(r)
    assert "ZIDDIYAT" in matn(r)


def test_hisobot_OVERALL_ni_HAM_chiqaradi():
    """⚠️ Chaqiruvchi `ok` dan tashqari YURISH holatini ham bilishi kerak: «fayllar butun»
       va «yurish to'liq» ikki XIL savol."""
    r = rad(paket())
    assert r.ok, matn(r)
    assert r.overall == rb.OVERALL_SUCCESS
    assert r.to_json()["overall"] == rb.OVERALL_SUCCESS
    assert rad(paket_partial()).overall == rb.OVERALL_PARTIAL
    assert rad({}).overall is None, "yurish yozuvi o'qilmasa holat NOMA'LUM bo'ladi"


def test_CLI_chiqish_kodi_2_paket_TOGRI_lekin_YURISH_TOLIQ_EMAS(tmp_path):
    """⚠️ UCHINCHI HOLAT: fayllar butun, sxema mos, sir yo'q — lekin yurishning O'ZI to'liq
       emas. Runbook `0` ni «AI analitikka topshir» deb ta'riflaydi, ya'ni bu paketga `0`
       berish YIQILGAN yurishni keyingi bosqichga o'tkazib yuborardi."""
    kod, out, _ = ishlat([cli.VALIDATE_CMD, yoz(tmp_path, paket_partial())])
    assert kod == cli.EXIT_INCOMPLETE == 2
    assert cli.MARK_BAD not in out, "paket TO'G'RI: birorta tekshiruv yiqilmagan"
    assert "TO'XTASH" in out and rb.OVERALL_PARTIAL in out


def test_CLI_chiqish_kodlarining_UCHOVI_HAM_AJRALGAN(tmp_path):
    """⚠️ `1` — «fayllarga ishonib bo'lmaydi», `2` — «fayllar butun, yurish to'liq emas».
       Operator harakati ikki holatda BOSHQA, shu bois kodlar ham boshqa."""
    a = tmp_path / "toliq"
    b = tmp_path / "toliq_emas"
    c = tmp_path / "buzuq"
    for p in (a, b, c):
        p.mkdir()
    assert ishlat([cli.VALIDATE_CMD, yoz(a, paket())])[0] == cli.EXIT_OK == 0
    assert ishlat([cli.VALIDATE_CMD, yoz(b, paket_partial())])[0] == cli.EXIT_INCOMPLETE == 2
    assert ishlat([cli.VALIDATE_CMD,
                   yoz(c, paket(drop=[rb.ERRORS_FILE]))])[0] == cli.EXIT_PROBLEM == 1


def test_CLI_json_chiqishida_ham_OVERALL_bor(tmp_path):
    kod, out, _ = ishlat([cli.VALIDATE_CMD, yoz(tmp_path, paket_partial()), "--json"])
    doc = json.loads(out)
    assert kod == cli.EXIT_INCOMPLETE
    assert doc["ok"] is True and doc["overall"] == rb.OVERALL_PARTIAL


# ══════════════════════════════════════════════════════════════════════════════════════════
# 19 · SIR NUQSON MATNIGA INTERPOLYATSIYA QILINMAYDI (HAR TEKSHIRUV TURI)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ SINTETIK VA TO'QIMA ulanish satri. Haqiqiy oqim: 1C ning xato tavsifi ulanish satrini,
#: server nomini va parolni O'Z ICHIGA OLADI, yig'uvchi esa shu matnni paketga qo'yadi. Ya'ni
#: sir paketning HAR QANDAY tashqi maydonida bo'lishi mumkin — oila nomida, fayl nomida,
#: obyekt manzilida, rejim izohida.
SIR_SATR = "Srvr=1c-srv-01;Ref=trade;Usr=admin;Pwd=Qwerty12345"
SIR_BOLAKLAR: tuple[str, ...] = ("Qwerty12345", "1c-srv-01", "Pwd=", "Usr=admin")


def _sir_errors_family() -> dict[str, bytes]:
    """Sir `errors.json` ning `family` maydonida — ISBOT: `havola_butunligi` uni XOM holda
    nuqson matniga qo'shardi."""
    errors = {**BOSH_ERRORS, "errors": [
        {"scope": "family", "family": SIR_SATR, "object": None,
         "code": "FAMILY_UNREADABLE", "detail": "oila o'qilmadi"}]}
    secs = copy.deepcopy(SECTIONS_OK)
    secs[1] = {"name": "metadata_sweep", "status": "failed", "error": "oila o'qilmadi"}
    return paket(errors=errors,
                 run=run_status(sections=secs, artifacts=sorted(rb.REQUIRED_FILES)))


def _sir_export_manbasi() -> dict[str, bytes]:
    """Sir nomzodning MANBA obyektida — `havola_butunligi` «ko'rilmagan obyekt» deb aytadi."""
    e = export_dict()
    e["candidates"][0]["source_object"] = SIR_SATR
    return paket(export=e)


def _sir_mode_note() -> dict[str, bytes]:
    """Sir rejim izohida — `rejim_darvozasi` izohni hisobotga KO'CHIRADI."""
    return paket(run=run_status(mode_note=SIR_SATR, artifacts=sorted(rb.REQUIRED_FILES)))


def _sir_fayl_nomi() -> dict[str, bytes]:
    """Sir FAYL NOMIDA — `majburiy_fayllar`, `xesh_manifest_mosligi`, `artefakt_dalvosi` va
    xom matn skani nomni ekranga chiqaradi."""
    m = paket()
    m[f"{SIR_SATR}.txt"] = b"shartnomada yo'q fayl\n"
    return m


def _sir_oila_nomi() -> dict[str, bytes]:
    """Sir O'QILMAGAN oila nomida — `overall_ziddiyatsiz` oila nomini sanaydi."""
    fams = copy.deepcopy(FAMILIES_OK)
    fams[1] = {"name": SIR_SATR, "state": "unreadable", "detail": "huquq yetmadi"}
    return paket(run=run_status(families=fams, overall=rb.OVERALL_SUCCESS,
                                artifacts=sorted(rb.REQUIRED_FILES)))


def _sir_manifest_nomi() -> dict[str, bytes]:
    """Sir MANIFEST qatorining nomida — `sxema_va_versiya` nomni repr bilan chiqaradi."""
    files = [{"name": SIR_SATR, "bytes": "12", "sha256": "0" * 64}]
    return paket(manifest_files=files)


def _sir_artifacts() -> dict[str, bytes]:
    """Sir `artifacts` da'vosida."""
    return paket(run=run_status(artifacts=sorted(set(rb.REQUIRED_FILES) | {SIR_SATR})))


def _sir_metadata_obyekti() -> dict[str, bytes]:
    """Sir metadata obyektining NOMIDA — inventarizatsiya validatori nomni repr qiladi."""
    md = copy.deepcopy(CONFIG_A_STANDARD_RU)
    md["objects"][0]["name"] = SIR_SATR
    return paket(metadata=md)


SIR_INTERPOLYATSIYA = [
    ("errors_family", _sir_errors_family),
    ("export_manbasi", _sir_export_manbasi),
    ("mode_note", _sir_mode_note),
    ("fayl_nomi", _sir_fayl_nomi),
    ("oila_nomi", _sir_oila_nomi),
    ("manifest_nomi", _sir_manifest_nomi),
    ("artifacts", _sir_artifacts),
    ("metadata_obyekti", _sir_metadata_obyekti),
]


@pytest.mark.parametrize("nomi,yasa", SIR_INTERPOLYATSIYA,
                         ids=[n for n, _ in SIR_INTERPOLYATSIYA])
def test_HAR_tekshiruv_turida_SIR_hisobotga_CHIQMAYDI(nomi, yasa):
    """⚠️ Nuqson matni operator ekranidan jurnalga, jurnaldan xabar almashinuviga ko'chadi.
       Shu bois nuqson matniga QO'SHILADIGAN HAR QANDAY tashqi qiymat `redact` dan o'tadi."""
    r = rad(yasa())
    assert not r.ok, f"{nomi}: fikstura buzuq paket bo'lishi kerak"
    hammasi = (matn(r) + " || " + " ".join(c.detail for c in r.checks)
               + " || " + rb.report_to_json_text(r))
    for bolak in SIR_BOLAKLAR:
        assert bolak not in hammasi, f"{nomi}: sir hisobotga chiqib ketdi ({bolak!r})"


@pytest.mark.parametrize("nomi,yasa", SIR_INTERPOLYATSIYA,
                         ids=[n for n, _ in SIR_INTERPOLYATSIYA])
def test_HAR_tekshiruv_turida_SIR_CLI_ekraniga_CHIQMAYDI(nomi, yasa, tmp_path):
    """⚠️ `cli.py` boshidagi «SIR EKRANGA CHIQMAYDI» da'vosi ikki chiqishda ham tekshiriladi:
       odam o'qiydigan hisobotda ham, `--json` da ham."""
    papka = yoz(tmp_path, yasa())
    for bayroq in ([], ["--json"]):
        kod, out, err = ishlat([cli.VALIDATE_CMD, papka] + bayroq)
        assert kod == cli.EXIT_PROBLEM
        ekran = out + err
        for bolak in SIR_BOLAKLAR:
            assert bolak not in ekran, f"{nomi}/{bayroq}: sir ekranga chiqdi ({bolak!r})"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 20 · YAGONA HAQIQIY SHAKL — KALITLAR IKKI TOMONDA BIR XIL
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_RUN_KEYS_YAGONA_SHAKL_bilan_QULFLANGAN():
    """⚠️ ILGARI FAQAT ARTEFAKT JADVALI KELISHILGAN EDI, KALIT NOMLARI EMAS: yig'uvchi yurish
       jurnalini `probes`, validator esa `probes_run` deb atardi va HAR BIR real paket
       `noma'lum kalit` bilan rad etilardi. Kalit nomlari endi shartnoma."""
    assert rb.RUN_KEYS == {
        "run_version", "collector", "mode", "mode_note", "started_at", "finished_at",
        "overall", "platform", "sections", "families", "probes", "artifacts",
        "error_count", "notes"}
    assert "probes_run" not in rb.RUN_KEYS, "eski nom qaytib kelgan"


def test_ERRORS_va_MANIFEST_hujjat_kalitlari_QULFLANGAN():
    assert rb.ERRORS_DOC_KEYS == {"errors_version", "collected_at", "errors", "notes"}
    assert rb.ERROR_KEYS == {"scope", "family", "object", "code", "detail"}
    assert rb.MANIFEST_DOC_KEYS == {"manifest_version", "files", "notes"}
    # ⚠️ MANBA provenansi maydonlari MANIFESTGA QO'SHILMAYDI (Phase 2 qoidasi) — `notes`
    #    qo'shilgani bu qoidani BO'SHATMAYDI.
    assert rb.MANIFEST_FILE_KEYS == {"name", "bytes", "sha256"}
    assert rb.FORBIDDEN_MANIFEST_KEYS == ("plan_sha256", "snapshot_at", "source_copy")


def test_ZOND_jurnali_va_NATIJASI_kalitlari_QULFLANGAN():
    """⚠️ IKKI BOSHQA HUJJAT: jurnal «nima bajarildi va qayerga yozildi» ni aytadi, natija
       «nima chiqdi» ni. Ularni aralashtirish ikki tomonni zid qilib qo'yardi."""
    assert rb.PROBE_LOG_KEYS == {"no", "probe_type", "target_object", "reason", "file",
                                 "status"}
    assert rb.PROBE_RESULT_KEYS == {"probe_version", "probe_type", "target_object",
                                    "read_only", "result", "errors", "mode"}
    assert "mode" in rb.PROBE_RESULT_KEYS, (
        "zond natijasi paketdan ajratib olinsa, rejim savoli javobsiz qolmasligi kerak")


def test_ERROR_SCOPES_qulflangan_va_run_QAMROVI_YOQ():
    """⚠️ `run` qamrovi juda keng edi: u xato QAYERDAN kelganini aytmasdi. O'rniga uchta aniq
       qamrov — platforma so'rovi, fayl yozish, rejim hal qilish."""
    assert rb.ERROR_SCOPES == ("family", "mode", "object", "platform", "probe", "write")
    assert "run" not in rb.ERROR_SCOPES
    assert rb.RUN_LEVEL_SCOPES == ("mode", "platform", "write")


@pytest.mark.parametrize("scope", list(rb.RUN_LEVEL_SCOPES))
def test_oiladan_TASHQARI_qamrovda_family_NULL(scope):
    """⚠️ `platform`/`write`/`mode` xatosi metadata OILASIGA tegishli emas: oila nomi
       `run_status.families` bilan solishtiriladi va «platforma» degan oila yo'q. `object`
       esa IXTIYORIY — platforma maydonining yoki yozilmagan faylning nomi shu yerda qoladi."""
    yaxshi = {**BOSH_ERRORS, "errors": [
        {"scope": scope, "family": None, "object": "locale", "code": "UNREADABLE",
         "detail": "o'qilmadi"}]}
    secs = copy.deepcopy(SECTIONS_OK)
    secs[0] = {"name": "platform", "status": "failed", "error": "o'qilmadi"}
    r = rad(paket(errors=yaxshi, run=run_status(sections=secs)))
    assert r.ok, matn(r)

    yomon = {**BOSH_ERRORS, "errors": [
        {"scope": scope, "family": "catalogs", "object": None, "code": "UNREADABLE",
         "detail": "o'qilmadi"}]}
    r = rad(paket(errors=yomon, run=run_status(sections=secs)))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 21 · `overall` YAGONA TA'RIFI — `skipped` VA `absent` SUCCESS NI BUZMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: `METADATA_ONLY` rejimidagi HALOL default yurish: yig'uvchi `probes` bo'limini `skipped`
#: deb yozadi (aktiv zond ATAYLAB bajarilmadi).
SECTIONS_SKIPPED_PROBES = SECTIONS_OK + [
    {"name": "probes", "status": "skipped",
     "error": "rejim METADATA_ONLY — aktiv zond bajarilmadi"},
]


def test_SKIPPED_bolim_va_ABSENT_oila_SUCCESS_ni_BUZMAYDI():
    """⚠️⚠️ AYNAN SHU HOLAT HAR BIR HALOL YURISHNI RAD ETARDI: `derive_overall` `SUCCESS`
       uchun HAMMA bo'lim `ok` bo'lishini talab qilardi, yig'uvchi esa `METADATA_ONLY` da
       HAR DOIM `probes` bo'limini `skipped` deb yozadi — ya'ni yig'uvchi `SUCCESS`, validator
       `PARTIAL` deb hisoblardi va ikki tomon HAR YURISHDA bir-biriga zid javob berardi.
    ⚠️ `skipped` — «bu ish ATAYLAB qilinmadi» degan JAVOB, yiqilish EMAS; `absent` ham JAVOB
       («bu konfiguratsiyada bunday oila yo'q»)."""
    assert any(f["state"] == "absent" for f in FAMILIES_OK), "fikstura `absent` oilani beradi"
    r = rad(paket(run=run_status(sections=SECTIONS_SKIPPED_PROBES)))
    assert r.ok, matn(r)
    assert r.overall == rb.OVERALL_SUCCESS
    assert rb.derive_overall(SECTIONS_SKIPPED_PROBES, families=FAMILIES_OK,
                             artifacts=rb.REQUIRED_FILES) == rb.OVERALL_SUCCESS


def test_derive_overall_YAGONA_TARIF():
    """Ta'rifning uch shoxi ham TO'G'RIDAN-TO'G'RI o'lchanadi."""
    hammasi = sorted(rb.REQUIRED_FILES)
    yiqilgan_bolim = copy.deepcopy(SECTIONS_OK)
    yiqilgan_bolim[0] = {"name": "platform", "status": "failed", "error": "o'qilmadi"}
    oqilmagan_oila = copy.deepcopy(FAMILIES_OK)
    oqilmagan_oila[0] = {"name": "catalogs", "state": "unreadable", "detail": "huquq yetmadi"}

    assert rb.derive_overall(SECTIONS_OK, families=FAMILIES_OK,
                             artifacts=hammasi) == rb.OVERALL_SUCCESS
    assert rb.derive_overall(yiqilgan_bolim, families=FAMILIES_OK,
                             artifacts=hammasi) == rb.OVERALL_PARTIAL
    assert rb.derive_overall(SECTIONS_OK, families=oqilmagan_oila,
                             artifacts=hammasi) == rb.OVERALL_PARTIAL
    # ⚠️ YOZISH YIQILSA — `FAILED`: paketning O'ZI to'liq bo'lmasa, ichidagi hukmlarni
    #    o'qishdan foyda yo'q.
    assert rb.derive_overall(SECTIONS_OK, families=FAMILIES_OK,
                             artifacts=[]) == rb.OVERALL_FAILED


@pytest.mark.parametrize("yoq", list(rb.REQUIRED_FILES))
def test_HAR_majburiy_artefakt_HISOBGA_olinadi(yoq):
    """⚠️ `errors.json` HAM MAJBURIY: uning yozilishini hisobga olmaslik YOLG'ON `SUCCESS`
       berardi — xatolar ro'yxati yozilmagan yurish «hech qanday xato bo'lmadi» bilan bir xil
       ko'rinardi."""
    qolgan = [n for n in rb.REQUIRED_FILES if n != yoq]
    assert rb.derive_overall(SECTIONS_OK, families=FAMILIES_OK,
                             artifacts=qolgan) == rb.OVERALL_FAILED


def test_YOZILMAGAN_artefakt_dalvosi_bilan_SUCCESS_ZIDDIYAT():
    """Yig'uvchi `errors.json` ni sanamasdan `SUCCESS` yozsa — ziddiyat (hisoblangani
    `FAILED`)."""
    r = rad(paket(run=run_status(artifacts=[n for n in rb.REQUIRED_FILES
                                           if n != rb.ERRORS_FILE],
                                 overall=rb.OVERALL_SUCCESS)))
    assert not r.ok
    assert "overall_ziddiyatsiz" in yiqilgan(r), matn(r)
    assert "ZIDDIYAT" in matn(r) and "hisoblangani" in matn(r)


@pytest.mark.parametrize("holat", ["absent", "unreadable"])
def test_OILA_HOLATI_bolim_lugatida_YOQ(holat):
    """⚠️ `absent`/`unreadable` FAQAT `families[].state` da yashaydi. Bir so'z ikki lug'atda
       tursa, «o'qilmadim» bo'lim jurnalidan oila jurnaliga ko'chib, ajrim yo'qolardi."""
    assert holat not in rb.SECTION_STATUSES, "bo'lim lug'ati bundle bilan AYNI qoladi"
    secs = copy.deepcopy(SECTIONS_OK)
    secs[0] = {"name": "platform", "status": holat, "error": "sabab"}
    r = rad(paket(run=run_status(sections=secs, overall=rb.OVERALL_SUCCESS)))
    assert not r.ok
    assert "sxema_va_versiya" in yiqilgan(r), matn(r)
    assert "families" in matn(r), "xato matni ajrimni AYTISHI kerak"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 22 · `platform`, `error_count`, `notes` — YANGI MAYDONLAR SHARTNOMASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_platform_BOSH_bolsa_RAD():
    """⚠️ §11 maydoni topilmasa ham kalit `null` qiymat bilan TURADI: bo'sh obyekt «hech
       narsaga qaralmadi» degani va u jimgina «platforma noma'lum» ga aylanmasligi kerak."""
    r = rad(paket(run=run_status(platform={})))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_platform_ICHMA_ICH_obyekt_bolsa_RAD():
    """⚠️ TEKIS shakl: §11 maydonlari XOM qiymatlar, tuzilma emas."""
    r = rad(paket(run=run_status(platform={**PLATFORM_OK,
                                          "locale": {"code": "ru"}})))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_platform_ichidagi_JSON_SONI_ham_RAD():
    """⚠️ Sanoq darvozasi (`sanoqlar_matn`) platformaga ham TO'LIQ qo'llanadi — kalit oq
       ro'yxati bu bo'limda ataylab qulflanmagani himoyani BO'SHATMAYDI."""
    r = rad(paket(run=run_status(platform={**PLATFORM_OK, "row_limit": 100})))
    assert not r.ok
    assert "sanoqlar_matn" in yiqilgan(r), matn(r)


def test_platform_kaliti_SHAKLAN_tekshiriladi():
    r = rad(paket(run=run_status(platform={**PLATFORM_OK, "Locale-1C": "ru"})))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_error_count_JSON_SONI_bolsa_RAD():
    """⚠️ Sanoq MATN: `0000` soni `0` bo'lib qolardi."""
    r = rad(paket(run=run_status(error_count=3)))
    assert not r.ok
    assert {"sanoqlar_matn", "sxema_va_versiya"} & yiqilgan(r), matn(r)


def test_errors_collected_at_NULL_QONUNIY_buzuq_vaqt_RAD():
    """⚠️ `null` — «vaqt olinmadi» (YOLG'ON vaqt yozilmaydi). Vaqt BOR bo'lsa — shakli
       QAT'IY."""
    r = rad(paket(errors={**BOSH_ERRORS, "collected_at": None}))
    assert r.ok, matn(r)
    r = rad(paket(errors={**BOSH_ERRORS, "collected_at": "kecha"}))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 23 · ZOND JURNALI — FAYL BILAN BIR-BIRINI TASDIQLAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_zond_jurnali_FAYL_NOMIGA_mos_kelishi_SHART():
    """⚠️ `ls` qiladigan operator va JSON o'qiydigan kod BIR XIL narsani ko'rishi SHART."""
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes={"01_row_count": probe_doc("row_count")},
                  probes_log=[zond_qaydi("row_count", no="01",
                                         file="probes/02_row_count.json")]))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_BIR_TURDAGI_IKKI_zond_IKKI_NISHONGA_QONUNIY():
    """⚠️ Ilgari jurnal TUR bo'yicha noyob bo'lishi talab qilinardi, ya'ni bitta turdagi
       zondni ikki BOSHQA nishonga bajarish mumkin emasdi — ikkinchi zond jimgina «takror»
       bo'lib yo'qolardi. Noyoblik endi bajarilish O'RNI va FAYL bo'yicha."""
    m = paket(mode=rb.MODE_APPROVED_PROBES,
              probes={"01_row_count": probe_doc("row_count", target=CATALOG),
                      "02_row_count": probe_doc("row_count", target=REGISTER)},
              probes_log=[zond_qaydi("row_count", no="01", target=CATALOG),
                          zond_qaydi("row_count", no="02", target=REGISTER)])
    r = rad(m)
    assert r.ok, matn(r)


def test_zond_jurnalidagi_TAKROR_orin_RAD():
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes={"01_row_count": probe_doc("row_count")},
                  probes_log=[zond_qaydi("row_count", no="01"),
                              zond_qaydi("enum_values", no="01")]))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_zond_jurnalidagi_NOMALUM_status_RAD():
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes={"01_row_count": probe_doc("row_count")},
                  probes_log=[zond_qaydi("row_count", status="maybe")]))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


def test_YIQILGAN_zond_jurnalda_failed_bolib_QOLADI():
    """⚠️ Yiqilgan zond JIMGINA `ok` bo'lib qolmaydi: uning fayli yozilgan, natijasi esa
       bo'sh — jurnal shu farqni aytadi."""
    p = probe_doc("row_count")
    p["result"] = None
    p["errors"] = ["nishon topilmadi"]
    m = paket(mode=rb.MODE_APPROVED_PROBES, probes={"01_row_count": p},
              probes_log=[zond_qaydi("row_count", status="failed")])
    r = rad(m)
    assert r.ok, matn(r)


def test_zond_natijasidagi_REJIM_metadata_only_bolsa_RAD():
    r = rad(paket(mode=rb.MODE_APPROVED_PROBES,
                  probes={"01_row_count": probe_doc("row_count",
                                                    mode=rb.MODE_METADATA_ONLY)},
                  probes_log=[zond_qaydi("row_count")]))
    assert not r.ok and "sxema_va_versiya" in yiqilgan(r), matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# NOM ICHIGA YELIMLANGAN SIR — `\b` ANKER'I KO'RMAYDIGAN HOLAT
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️ NEGA ALOHIDA BO'LIM: `redact` naqshlari so'z chegarasiga (`\b`) tayanadi va `_` so'z
#    belgisi bo'lgani uchun sir NOM ICHIGA yelimlanganda ko'rinmaydi:
#    `redact("10.8.0.5:1541")` niqoblaydi, `redact("99_10.8.0.5:1541")` esa YO'Q.
#    Zond fayllari aynan shunday nomlanadi (`probes/NN_<tur>.json`), ya'ni 1C xatosidan
#    kelgan nishon nomi fayl nomiga tushsa sir to'rt kanalda ham (problems, --json,
#    CLI odam-hisoboti, report matni) oshkor bo'lardi.
# ⚠️ `redact.py` — Phase 2 fayli va TEGILMAYDI; darvoza `runtime_bundle._xavfsiz` da.
@pytest.mark.parametrize("nom,sir", [
    ("probes/99_pwd=hunter2.json", "hunter2"),
    ("probes/99_10.8.0.5:1541.json", "10.8.0.5"),
    ("99_parol=Qwerty12345.json", "Qwerty12345"),
    ("probes/07_rdp=10.0.0.5:3389.json", "10.0.0.5"),
    ("Srvr=1c-srv-01;Pwd=hunter2", "hunter2"),
    ("99_maxfiy=Parol123.json", "Parol123"),
])
def test_NOM_ICHIGA_yelimlangan_sir_NIQOBLANADI(nom, sir):
    """Ajratuvchi normalizatsiyasi bo'lmasa bu qiymatlar XOM holda hisobotga tushardi."""
    natija = rb._xavfsiz(nom)
    assert sir not in natija, (
        f"nom ichiga yelimlangan sir niqoblanmadi: {natija!r} ichida {sir!r} qoldi")


@pytest.mark.parametrize("qonuniy", [
    "export.json", "metadata.json", "run_status.json", "errors.json", "manifest.json",
    "run_summary.md", "probes/01_row_count.json", "probes/02_enum_values.json",
    "probes/03_common_attributes.json", "probes/04_field_type_details.json",
    "metadata_sweep", "counts", "export:platform",
    "8.3.24.1548", "1.0.0.1", "0.2.0-UNVERIFIED",
    "Справочник.Номенклатура", "ТоварыНаСкладах",
])
def test_QONUNIY_nom_va_VERSIYA_niqoblanmaydi(qonuniy):
    """⚠️ YOLG'ON IJOBIY darvozasi: ajratuvchi normalizatsiyasi haqiqiy artefakt
       nomlarini, zond fayl nomlarini va VERSIYA satrlarini yeb qo'ymasligi kerak —
       aks holda hisobot o'qilmas bo'lib qoladi va operator nimani tekshirishni bilmaydi."""
    assert rb._xavfsiz(qonuniy) == qonuniy, "qonuniy qiymat bexosdan niqoblandi"


def test_ikki_AJRATUVCHI_varianti_HAM_kerak():
    """⚠️ Bitta variant YETMAYDI va buni qulflash kerak: nuqtani ham almashtirsak IP
       BO'LINIB ketadi (`10.8.0.5:1541` -> `10 8 0 5:1541`) va `ip_with_port` ishlamaydi;
       nuqtani saqlasak kengaytmaga yelimlangan sir yashirinadi. Shu bois IKKISI ham."""
    assert len(rb._AJRATUVCHILAR) >= 2, "ikki ajratuvchi varianti bo'lishi SHART"
    assert rb._xavfsiz("probes/99_10.8.0.5:1541.json") == rb.redaction.MASK
    assert rb._xavfsiz("probes/99_pwd=hunter2.json") == rb.redaction.MASK
