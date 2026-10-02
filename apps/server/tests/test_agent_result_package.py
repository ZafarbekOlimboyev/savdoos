# -*- coding: utf-8 -*-
"""NATIJA PAKETI, MINIMAL UI va KIRISH NUQTASI shartnomasi.

⚠️ NIMANI ISBOTLAYDI: `binos-discovery-<timestamp>/` papkasining shakli, Phase 4 paketining
   `bundle/` ichida O'ZGARMAGAN holda yashashi va YADRO VALIDATORIDAN o'tishi,
   `agent_manifest.json` ning butun papkani (shu jumladan `bundle/...` ni) xeshlashi, xesh va
   fayl mos kelmasa RAD etilishi, sir topilsa HECH NARSA yozilmasligi, agent paketida tarmoq
   importi va avtoyuklanish/xizmat/reestrga yozish belgilarining YO'Qligi, `ui.py` ning
   `tkinter` SIZ ham import qilinishi va determinizm (bir xil kirish -> bir xil bayt).

⚠️ NIMANI ISBOTLAMAYDI: 1C bilan ishlashni. Bu mashinada 1C:Enterprise UMUMAN O'RNATILMAGAN
   (`1cv8.exe` yo'q, COM klasslari ro'yxatda yo'q, `pywin32` yo'q), shu bois integratsiya
   yo'llari (`batch_execute`, `watch_folder`) `RUNTIME-UNKNOWN`. Bu faylda sinaladigan
   narsalarning hech biri 1C ni TALAB QILMAYDI — natija paketi fayllar bilan ishlaydi, UI
   esa boshqa modullarni chaqiradi.

⚠️ `pyinstaller` ham O'RNATILMAGAN: portable build HUJJATLASHTIRILGAN, lekin QURILMAGAN, va
   `AGENT_PORTABLE_BUILD.md` buni ochiq aytishi shu faylda qulflangan.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import io
import json
import os
import pathlib
import re
import sys

import pytest

from app.services.discovery_1c import review as rv
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c.bundle import dumps
from app.services.discovery_agent import (AGENT_ARTIFACTS, AGENT_MANIFEST_FILE,
                                          AGENT_STATUS_FILE, AI_CANDIDATES_FILE,
                                          BUNDLE_SUBDIR, ENVIRONMENT_FILE, ERRORS_FILE,
                                          ERRORS_VERSION, REPORT_FILE,
                                          RESULT_DIR_PREFIX, ROUTE_WATCH_FOLDER)
from app.services.discovery_agent import __main__ as agent_main
from app.services.discovery_agent import detector as det
from app.services.discovery_agent import report as agent_report
from app.services.discovery_agent import result_package as rp
from app.services.discovery_agent import states as st
from app.services.discovery_agent import status as stat
from app.services.discovery_agent import ui as agent_ui
from app.services.migrator_1c.bundle import sha256_bytes
# ⚠️ Phase 4 paketining SINTETIK fiksturasi QAYTA ISHLATILADI: ikkinchi «to'g'ri paket»
#    quruvchisi yozilsa, u bir kun yadroning shartnomasidan ajralib ketardi va bu fayl
#    yadro o'zgarganini SEZMASDAN yashil qolardi.
from tests.test_discovery_1c_runtime_bundle import paket as phase4_bundle

#: Vaqt KIRISHDAN — hamma joyda AYNI qiymat (determinizm).
T0 = "2026-09-30T10:14:30+00:00"
TS = "20260930T101430Z"

PAKET_DIR = pathlib.Path(rp.__file__).parent
PAKET_FAYLLARI = sorted(p for p in PAKET_DIR.glob("*.py"))

PORTABLE_DOC = (pathlib.Path(rb.__file__).resolve().parents[5] / "integrations" / "1c"
                / "AGENT_PORTABLE_BUILD.md")

#: Odam o'qiydigan hisobot. ⚠️ Ichida mahalliy yo'l ham, sir ham, `VERIFIED` so'zi ham YO'Q.
REPORT_MD = (
    "# BinOS 1C razvedka hisoboti\n"
    "\n"
    "- Rejim: METADATA_ONLY (aktiv zond yo'q)\n"
    "- Agent faqat O'QIDI: hech narsa yozilmadi, hech narsa bajarilmadi\n"
    "- Integratsiya yo'li: watch_folder — RUNTIME-UNKNOWN, haqiqiy 1C ga qarshi SINALMAGAN\n"
    "\n"
    "Bu hisobot agentning 1C da ishlashini ISBOTLAMAYDI.\n"
)

#: Analitik artefakti — YADRONING yozuvchisi bilan quriladi (`review.dumps_review`).
REVIEW_DOC = {
    "review_version": rv.REVIEW_VERSION,
    "analyzer": {"name": "deterministik-lokal", "version": "0.1.0-UNVERIFIED"},
    "analyzer_notes": ["izoh berilmagan — hech narsa qisilmadi degani EMAS"],
    "graph": {"objects": "0"},
    "coverage": None,
    "candidates": [],
    "unknown_concepts": [],
    "counts": {"candidates": "0"},
    "warnings": list(rv.WARNINGS),
}
AI_MATNI = rv.dumps_review(REVIEW_DOC).decode("utf-8")


# ══════════════════════════════════════════════════════════════════════════════════════════
# FIKSTURALAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def env_scan(*, installs=None, infobases=None, com=det.TRI_UNKNOWN,
             unreadables=()) -> det.EnvironmentScan:
    """SINTETIK muhit skaneri natijasi — haqiqiy reestr O'QILMAYDI."""
    if installs is None:
        installs = (det.Install(path=r"C:\Program Files\1cv8\8.3.24\bin\1cv8.exe",
                                version="8.3.24.1548", bitness="x64",
                                source=det.SOURCE_REGISTRY),)
    if infobases is None:
        infobases = (det.Infobase(kind=det.KIND_FILE, locator=r"C:\bazalar\dokon",
                                  name="Dokon savdo", source=det.SOURCE_IBASES_USER,
                                  requires_auth=det.TRI_UNKNOWN),)
    return det.EnvironmentScan(scanned_at=T0, os_version="Windows-11-10.0.26200",
                               installs=tuple(installs), com_registered=com,
                               infobases=tuple(infobases),
                               notes=(det.RUNTIME_UNKNOWN_NOTE,),
                               unreadables=tuple(unreadables))


def env_matni(**kw) -> str:
    return det.dump_document(env_scan(**kw))


def env_hukm(verdikt: str) -> str:
    """AYNAN berilgan `presence_verdict` ni chiqaradigan muhit hujjati.

    ⚠️ Hukm O'YLAB CHIQARILMAYDI — u `detector.EnvironmentScan.presence_verdict` dan
       KELADI (ikkinchi lug'at yo'q): fikstura KIRISHNI o'zgartiradi va chiqqan hukmni
       TEKSHIRADI, skanerning qoidasini TAKRORLAMAYDI.
    """
    if verdikt == det.PRESENCE_FOUND:
        scan = env_scan()                                       # o'rnatma BOR
    elif verdikt == det.PRESENCE_ABSENT:
        scan = env_scan(installs=(), infobases=())              # qaradim va YO'Q
    else:
        scan = env_scan(installs=(), infobases=(),              # QARAY OLMADIM
                        unreadables=(det.Unreadable(
                            scope="registry", code=det.CODE_REGISTRY_UNREADABLE,
                            detail="huquq yetmadi"),))
    assert scan.presence_verdict == verdikt, "fikstura kutilgan hukmni bermadi"
    return det.dump_document(scan)


def status_matni(artifacts, *, state=st.COMPLETE, verdict=None) -> str:
    """`COMPLETE` gacha yetgan HALOL yurish yozuvi (`binos-agent-run-v1`)."""
    s = stat.new_run("run-0001", now=T0)
    yo_l = [st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK, st.METADATA_DISCOVERY,
            st.VALIDATION, st.GRAPH_BUILD, st.ANALYSIS, st.REPORT, st.COMPLETE]
    for holat in yo_l:
        if holat == state:
            s = s.advance(holat, now=T0, note="sintetik fikstura")
            break
        s = s.advance(holat, now=T0, note="")
    s = (s.with_route(ROUTE_WATCH_FOLDER).with_bundle_dir(BUNDLE_SUBDIR)
         .with_environment_file(ENVIRONMENT_FILE).with_artifacts(artifacts)
         .with_note("1C integratsiya yo'li RUNTIME-UNKNOWN: haqiqiy 1C ga qarshi sinalmagan"))
    # ⚠️⚠️ HUKM IKKI HUJJATDA TENG: `environment.json` ni `env_matni()` yozadi, yurish yozuvi
    #    esa AYNI skanerning hukmini olib yuradi. Avval bu fikstura `with_presence_verdict`
    #    ni UMUMAN chaqirmasdi (standart — `unknown`), muhit hujjati esa `found` yozardi:
    #    ya'ni TO'PLAMNING O'Z FIKSTURASI paketdagi zidlikni JONLI saqlab turardi.
    s = s.with_presence_verdict(env_scan().presence_verdict if verdict is None else verdict)
    return s.to_json()


def paket(*, bundle=None, status=None, env=None, ai=None, report=None,
          timestamp=TS) -> rp.ResultPackage:
    """To'g'ri natija paketi (shakl o'zgartirilishi testda ATAYLAB qilinadi)."""
    bundle = phase4_bundle() if bundle is None else bundle
    nomlar = sorted(set(AGENT_ARTIFACTS) | {f"{BUNDLE_SUBDIR}/{n}" for n in bundle})
    return rp.ResultPackage.from_parts(
        timestamp=timestamp,
        status_json=status_matni(nomlar) if status is None else status,
        environment_json=env_matni() if env is None else env,
        ai_candidates_json=AI_MATNI if ai is None else ai,
        report_md=REPORT_MD if report is None else report,
        bundle=bundle,
    )


def yoz(tmp_path: pathlib.Path, **kw) -> pathlib.Path:
    return pathlib.Path(paket(**kw).write(str(tmp_path)))


def muammolar(folder) -> str:
    return " || ".join(rp.check_result_package(str(folder)))


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · PAPKA NOMI va VAQT TAMG'ASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_papka_nomi_timestampdan_quriladi():
    assert rp.result_dir_name(TS) == f"{RESULT_DIR_PREFIX}{TS}"
    assert rp.timestamp_from_dir_name(rp.result_dir_name(TS)) == TS


def test_ISO_timestamp_papka_nomida_RAD_etiladi():
    """⚠️ Windows fayl nomida `:` TAQIQLANGAN — ISO vaqt papka nomi bo'la olmaydi."""
    with pytest.raises(rp.ResultPackageError, match="Windows fayl nomi"):
        rp.result_dir_name(T0)


@pytest.mark.parametrize("yaroqsiz", ["", "../qochib", "C:/mutlaq", "nom/boshqa", "nom\\x"])
def test_yaroqsiz_timestamp_RAD(yaroqsiz):
    with pytest.raises(rp.ResultPackageError):
        rp.result_dir_name(yaroqsiz)


def test_compact_va_iso_bir_birining_teskarisi():
    assert rp.compact_timestamp(T0) == TS
    assert rp.iso_from_compact(TS) == T0
    assert rp.compact_timestamp(rp.iso_from_compact(TS)) == TS


def test_compact_timestamp_UTC_ga_keltiradi():
    """⚠️ Mahalliy zonali vaqt UTC ga aylanadi: nom LEKSIK tartibda vaqt tartibiga teng."""
    assert rp.compact_timestamp("2026-09-30T10:14:30+06:00") == "20260930T041430Z"


def test_shaklga_mos_lekin_MAVJUD_BOLMAGAN_sana_RAD():
    with pytest.raises(rp.ResultPackageError):
        rp.iso_from_compact("20261345T101430Z")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · PAKET QURILADI va VALIDATORDAN O'TADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_natija_paketi_quriladi_va_validatordan_otadi(tmp_path):
    root = yoz(tmp_path)
    assert root.name == f"{RESULT_DIR_PREFIX}{TS}"
    rp.validate_result_package(str(root))  # ⚠️ istisno bo'lmasligi SHART
    assert rp.check_result_package(str(root)) == []


def test_ildizda_ALTI_artefakt_va_bundle_ostki_papkasi(tmp_path):
    """⚠️ Sanoq BESHDAN ALTIGA o'sdi: brief talab qilgan ildizdagi `errors.json` qo'shildi."""
    root = yoz(tmp_path)
    ildiz = sorted(p.name for p in root.iterdir() if p.is_file())
    assert ildiz == sorted(AGENT_ARTIFACTS)
    assert (root / BUNDLE_SUBDIR).is_dir()


def test_bundle_PHASE4_validatoridan_otadi(tmp_path):
    """⚠️ Shartnoma BUZILMAGAN: Phase 4 paketi O'ZGARMAGAN holda yashaydi va YADRO
    validatoridan o'tadi (mantiq qayta yozilmaydi — `validate_runtime_bundle` chaqiriladi)."""
    root = yoz(tmp_path)
    hisobot = rb.validate_runtime_bundle(str(root / BUNDLE_SUBDIR))
    assert hisobot.ok, hisobot.problems
    assert hisobot.overall == rb.OVERALL_SUCCESS


def test_bundle_BAYTLARI_OZGARMAYDI(tmp_path):
    """Phase 4 paketining har bir fayli AYNAN kirgan baytlar bilan yoziladi."""
    kirish = phase4_bundle()
    root = yoz(tmp_path, bundle=kirish)
    for nom, raw in kirish.items():
        assert (root / BUNDLE_SUBDIR / nom).read_bytes() == raw


def test_ildizda_manifest_json_YOZILMAYDI(tmp_path):
    """⚠️⚠️ BIR XIL NOM, IKKI XIL SXEMA TAQIQ: Phase 4 ning `manifest.json` i faqat
    `bundle/` da, agentning manifesti esa `agent_manifest.json` deb ATALADI."""
    root = yoz(tmp_path)
    assert not (root / rb.MANIFEST_FILE).exists()
    assert (root / AGENT_MANIFEST_FILE).exists()
    assert (root / BUNDLE_SUBDIR / rb.MANIFEST_FILE).exists()
    agent_doc = json.loads((root / AGENT_MANIFEST_FILE).read_text("utf-8"))
    phase4_doc = json.loads((root / BUNDLE_SUBDIR / rb.MANIFEST_FILE).read_text("utf-8"))
    # ⚠️ IKKI XIL HUJJAT: kalit to'plamlari ham AJRALGAN.
    assert set(agent_doc) == {"files", "notes"}
    assert "manifest_version" in phase4_doc


def test_phase4_fayli_ILDIZDA_tursa_RAD(tmp_path):
    root = yoz(tmp_path)
    (root / rb.EXPORT_FILE).write_bytes((root / BUNDLE_SUBDIR / rb.EXPORT_FILE).read_bytes())
    matn = muammolar(root)
    assert "ildizda Phase 4 paketining fayl(lar)i" in matn
    assert "manifestda YO'Q" in matn


def test_bundle_ostki_papkasi_yoq_bolsa_RAD(tmp_path):
    root = yoz(tmp_path)
    for p in sorted((root / BUNDLE_SUBDIR).rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (root / BUNDLE_SUBDIR).rmdir()
    assert f"{BUNDLE_SUBDIR}/ ostki papkasi yo'q" in muammolar(root)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · MANIFEST
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_agent_manifestida_bundle_fayllari_HAM_bor(tmp_path):
    bundle = phase4_bundle()
    root = yoz(tmp_path, bundle=bundle)
    doc = json.loads((root / AGENT_MANIFEST_FILE).read_text("utf-8"))
    nomlar = {f["name"] for f in doc["files"]}
    assert {f"{BUNDLE_SUBDIR}/{n}" for n in bundle} <= nomlar
    # ildiz artefaktlari ham (manifestning O'ZIDAN tashqari)
    assert set(AGENT_ARTIFACTS) - {AGENT_MANIFEST_FILE} <= nomlar


def test_manifest_OZINI_xeshlamaydi(tmp_path):
    root = yoz(tmp_path)
    doc = json.loads((root / AGENT_MANIFEST_FILE).read_text("utf-8"))
    assert AGENT_MANIFEST_FILE not in {f["name"] for f in doc["files"]}
    doc["files"].append({"name": AGENT_MANIFEST_FILE, "bytes": "1", "sha256": "0" * 64})
    with pytest.raises(rp.ResultPackageError, match="O'ZINI xeshlay olmaydi"):
        rp.validate_agent_manifest(doc)


@pytest.mark.parametrize("taqiq", rp.FORBIDDEN_MANIFEST_KEYS)
def test_manifest_MANBA_provenansini_yozmaydi_hujjat_darajasida(taqiq):
    """⚠️ `source_copy`/`snapshot_at`/`plan_sha256` — Phase 2 taqig'i: manifest faqat
    YOZILGAN BAYTLARNI tasdiqlaydi, «qaysi bazadan» DEMAYDI."""
    doc = rp.build_agent_manifest({"a.txt": b"x"})
    doc[taqiq] = "qiymat"
    with pytest.raises(rp.ResultPackageError, match="MANBA provenansi"):
        rp.validate_agent_manifest(doc)


@pytest.mark.parametrize("taqiq", rp.FORBIDDEN_MANIFEST_KEYS)
def test_manifest_MANBA_provenansini_yozmaydi_fayl_darajasida(taqiq):
    doc = rp.build_agent_manifest({"a.txt": b"x"})
    doc["files"][0][taqiq] = "qiymat"
    with pytest.raises(rp.ResultPackageError, match="MANBA provenansi"):
        rp.validate_agent_manifest(doc)


def test_quruvchi_manifest_HECH_QACHON_provenans_yozmaydi(tmp_path):
    """Qurilgan manifestda taqiqlangan maydon BO'LMASLIGI — quruvchining O'Z invarianti."""
    root = yoz(tmp_path)
    xom = (root / AGENT_MANIFEST_FILE).read_text("utf-8")
    for taqiq in rp.FORBIDDEN_MANIFEST_KEYS:
        assert taqiq not in xom


@pytest.mark.parametrize("nom,qiymat", [
    ("bytes", 7),            # JSON soni
    ("bytes", "yetti"),      # raqamli MATN emas
    ("sha256", None),        # agent manifestida `null` TAQIQ
    ("sha256", "ABC" * 21 + "d"),  # katta harf
])
def test_manifest_shakli_buzilsa_RAD(nom, qiymat):
    doc = rp.build_agent_manifest({"a.txt": b"x"})
    doc["files"][0][nom] = qiymat
    with pytest.raises(rp.ResultPackageError):
        rp.validate_agent_manifest(doc)


def test_manifest_TARTIBLANGAN_bolishi_SHART():
    doc = rp.build_agent_manifest({"a.txt": b"x", "b.txt": b"y"})
    doc["files"].reverse()
    with pytest.raises(rp.ResultPackageError, match="tartiblangan"):
        rp.validate_agent_manifest(doc)


def test_manifestda_NOMALUM_kalit_RAD():
    doc = rp.build_agent_manifest({"a.txt": b"x"})
    doc["manifest_version"] = "binos-agent-manifest-v1"
    with pytest.raises(rp.ResultPackageError, match="noma'lum kalit"):
        rp.validate_agent_manifest(doc)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · XESH va FAYL MOSLIGI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_xesh_mos_kelmasa_RAD(tmp_path):
    root = yoz(tmp_path)
    yo_l = root / REPORT_FILE
    xom = yo_l.read_bytes()
    # ⚠️ AYNI HAJM, boshqa mazmun: faqat xesh darvozasi ushlaydi.
    yo_l.write_bytes(b"X" + xom[1:])
    matn = muammolar(root)
    assert "sha256 MOS KELMADI" in matn
    assert sha256_bytes(xom) not in matn  # ⚠️ xeshning O'ZI xato matnida ko'rsatilmaydi


def test_bayt_hajmi_mos_kelmasa_RAD(tmp_path):
    root = yoz(tmp_path)
    (root / REPORT_FILE).write_bytes(REPORT_MD.encode("utf-8") + b"qo'shimcha\n")
    assert "bayt hajmi mos emas" in muammolar(root)


@pytest.mark.parametrize("nom", sorted(AGENT_ARTIFACTS))
def test_ildiz_fayli_yoq_bolsa_RAD(tmp_path, nom):
    root = yoz(tmp_path)
    (root / nom).unlink()
    matn = muammolar(root)
    assert "majburiy artefakt(lar) yo'q" in matn and nom in matn


def test_ORTIQCHA_fayl_RAD(tmp_path):
    """⚠️ Manifest papkadagi HAMMA faylni qamraydi: «zararsiz qo'shimcha» jimgina qolmaydi."""
    root = yoz(tmp_path)
    (root / "qoshimcha.txt").write_bytes(b"men bu yerda nima qilyapman?\n")
    assert "papkadagi fayl(lar) manifestda YO'Q" in muammolar(root)


def test_manifest_DALVO_qilgan_fayl_yoq_bolsa_RAD(tmp_path):
    root = yoz(tmp_path)
    (root / BUNDLE_SUBDIR / rb.RUN_SUMMARY_FILE).unlink()
    matn = muammolar(root)
    assert "manifest da'vo qilgan fayl(lar) papkada YO'Q" in matn


def test_xato_matnida_PAPKA_YOLI_YOQ(tmp_path):
    """⚠️ Absolyut yo'l do'kon mashinasining tuzilmasini oshkor qiladi va bu matnlar
    ekrandan jurnalga ko'chadi."""
    root = yoz(tmp_path)
    (root / REPORT_FILE).write_bytes(b"boshqa mazmun\n")
    (root / "qoshimcha.txt").write_bytes(b"x")
    matn = muammolar(root)
    assert matn  # nuqson BOR
    assert str(tmp_path) not in matn
    assert str(root) not in matn


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · SIR DARVOZASI (fail-closed)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_hisobotda_SIR_bolsa_RAD():
    yomon = REPORT_MD + "\nBaza paroli: hunter2\n"
    with pytest.raises(rp.ResultPackageError, match="shubhali qiymat"):
        paket(report=yomon).members()


def test_hisobotda_mahalliy_YOL_bolsa_RAD():
    yomon = REPORT_MD + "\nBaza joyi: C:\\bazalar\\dokon\\1Cv8.1CD\n"
    with pytest.raises(rp.ResultPackageError):
        paket(report=yomon).members()


def test_environmentda_SIR_bolsa_RAD():
    """⚠️ `detector` chiqishni O'ZI niqoblaydi, lekin darvoza IKKI QATLAMLI: fayl qo'lda
    tahrirlangan yoki boshqa yozuvchi tomonidan qurilgan bo'lishi mumkin."""
    doc = json.loads(env_matni())
    doc["notes"] = doc["notes"] + ["ulanish: Usr=admin;Pwd=hunter2"]
    yomon = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    with pytest.raises(rp.ResultPackageError, match="shubhali qiymat"):
        paket(env=yomon).members()


def test_hisobotda_VERIFIED_sozi_RAD():
    """⚠️ Agent hech narsani tasdiqlamaydi; `HUMAN_CONFIRMED` faqat operatordan."""
    with pytest.raises(rp.ResultPackageError, match="VERIFIED"):
        paket(report=REPORT_MD + "\nXulosa: VERIFIED\n").members()


def test_HALOL_UNVERIFIED_versiyasi_RAD_ETILMAYDI():
    """⚠️ So'z CHEGARASI: `0.1.0-UNVERIFIED` halol versiya va u o'tishi SHART."""
    paket(report=REPORT_MD + "\nAgent: 0.1.0-UNVERIFIED\n").members()


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · AGENT ARTEFAKTLARINING SHAKLI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_buzuq_yurish_yozuvi_YOZILMAYDI():
    doc = json.loads(status_matni(sorted(AGENT_ARTIFACTS)))
    doc["read_only"] = "false"  # ⚠️ yozadigan agent MAVJUD EMAS
    with pytest.raises(rp.ResultPackageError, match="read_only"):
        paket(status=dumps(doc)).members()


def test_yurish_yozuvining_baytlari_DETERMINISTIK_bolishi_SHART():
    doc = json.loads(status_matni(sorted(AGENT_ARTIFACTS)))
    with pytest.raises(rp.ResultPackageError, match="deterministik shaklda emas"):
        paket(status=json.dumps(doc, indent=4, ensure_ascii=False)).members()


def test_yurish_yozuvi_YOQ_faylni_dalvo_qilsa_RAD():
    nomlar = sorted(set(AGENT_ARTIFACTS) | {"bundle/yoq-fayl.json"})
    with pytest.raises(rp.ResultPackageError, match="papkada YO'Q"):
        paket(status=status_matni(nomlar)).members()


def test_bundle_dir_boshqa_nom_bolsa_RAD():
    s = stat.new_run("run-0002", now=T0).advance(st.ENVIRONMENT_SCAN, now=T0)
    s = s.with_bundle_dir("paket")  # ⚠️ Phase 4 paketi AYNAN `bundle/` da yashaydi
    with pytest.raises(rp.ResultPackageError, match="bundle_dir"):
        paket(status=s.to_json()).members()


def test_env_versiyasi_boshqa_bolsa_RAD():
    doc = json.loads(env_matni())
    doc["env_version"] = "binos-agent-env-v2"
    with pytest.raises(rp.ResultPackageError, match="env_version"):
        paket(env=json.dumps(doc, ensure_ascii=False, indent=2) + "\n").members()


def test_env_uchulik_mantiqni_BOOLEANGA_siqsa_RAD():
    """⚠️ `"unknown"` ni booleanga siqish «1C yo'q» va «ko'rolmadim» ni ADASHTIRADI."""
    doc = json.loads(env_matni())
    doc["com_registered"] = False
    with pytest.raises(rp.ResultPackageError, match="JSON soni/booleani"):
        paket(env=json.dumps(doc, ensure_ascii=False, indent=2) + "\n").members()


def test_env_unknown_qiymati_QONUNIY():
    """`com_registered` va `requires_auth` uchun `"unknown"` — TO'LIQ HAQLI javob."""
    doc = json.loads(env_matni(com=det.TRI_UNKNOWN))
    assert doc["com_registered"] == "unknown"
    assert doc["infobases"][0]["requires_auth"] == "unknown"
    paket().members()


def test_env_fayl_bazasining_YOLI_NIQOBLANGAN():
    """⚠️ `redact` ning yo'l naqshi probelda to'xtaydi, shu bois `detector` yo'lni TO'LIQ
    niqoblaydi — natija paketida mahalliy yo'l qolmaydi."""
    matn = env_matni()
    assert "bazalar" not in matn and "Program" not in matn
    assert matn.count("[REDACTED]") >= 2


def test_ai_artefakti_yadro_validatoridan_otadi():
    doc = json.loads(AI_MATNI)
    assert doc["review_version"] == rv.REVIEW_VERSION
    with pytest.raises(rp.ResultPackageError, match="yadro validatori rad etdi"):
        yomon = dict(doc, review_version="boshqa")
        paket(ai=dumps(yomon)).members()


def test_ai_artefaktining_fayl_nomi_YADRODAN():
    """⚠️ Operator AYNAN shu nomni izlaydi — ikki joyda ikki nom bo'lishi mumkin emas."""
    assert AI_CANDIDATES_FILE == rv.REVIEW_FILENAME


def test_bosh_hisobot_RAD():
    with pytest.raises(rp.ResultPackageError, match="bo'sh"):
        paket(report="   \n").members()


def test_buzuq_bundle_YOZILMAYDI(tmp_path):
    """⚠️ FAIL-CLOSED: rad etilgan Phase 4 paketi natija papkasiga TUSHMAYDI va bo'sh papka
    ham qolmaydi."""
    buzuq = phase4_bundle(drop=(rb.EXPORT_FILE,))
    with pytest.raises(rp.ResultPackageError) as e:
        paket(bundle=buzuq).write(str(tmp_path))
    assert f"{BUNDLE_SUBDIR}/" in str(e.value)
    assert list(tmp_path.iterdir()) == []


def test_HAMMA_nuqson_bir_yurishda_korinadi():
    """⚠️ Operator o'nta nuqsonni o'n marta urinmasdan ko'rishi kerak (Phase 4 qarori)."""
    problems = paket(report="", ai="{}").problems()
    assert len(problems) >= 2
    assert any(REPORT_FILE in p for p in problems)
    assert any(AI_CANDIDATES_FILE in p for p in problems)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6b · PAPKANING SHAKLI HOLATDAN KELIB CHIQADI (paketsiz yiqilish ham papka qoldiradi)
# ══════════════════════════════════════════════════════════════════════════════════════════
def yiqilgan_status(*, artifacts, bundle_dir=None, via=(), verdict=None,
                    state=st.FAILED_COLLECTOR_UNAVAILABLE) -> str:
    """Yiqilgan yurishning yozuvi.

    ⚠️ `via` — yiqilishdan OLDINGI qo'shimcha holatlar: `states.TRANSITIONS` har bir
    yiqilishni FAQAT o'z joyidan ruxsat etadi (`FAILED_VALIDATION` — `VALIDATION` dan).
    """
    s = stat.new_run("run-0002", now=T0)
    for holat in (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK,
                  st.METADATA_DISCOVERY) + tuple(via):
        s = s.advance(holat, now=T0)
    s = (s.with_route(ROUTE_WATCH_FOLDER).with_environment_file(ENVIRONMENT_FILE)
         .with_artifacts(artifacts)
         .with_error("collector:watch_folder", "BUNDLE_DIR_MISSING",
                     "yig'uvchi natija bermadi — javob YO'Q"))
    # ⚠️ Hukm muhit hujjati bilan MOS (`env_matni()` — `found`), aks holda paket O'Z-O'ZIGA
    #    zid bo'lardi va `_check_status_cross_refs` uni RAD etardi.
    s = s.with_presence_verdict(env_scan().presence_verdict if verdict is None else verdict)
    if bundle_dir is not None:
        s = s.with_bundle_dir(bundle_dir)
    return s.advance(state, now=T0, note="sintetik fikstura").to_json()


def paketsiz(**over) -> rp.ResultPackage:
    """Paketsiz va analitiksiz natija paketi (yiqilgan yurish)."""
    kw = dict(timestamp=TS, status_json=yiqilgan_status(artifacts=rp.ALWAYS_FILES),
              environment_json=env_matni(), report_md=REPORT_MD)
    kw.update(over)
    return rp.ResultPackage.from_parts(**kw)


def test_SHARTNOMA_royxatlari_bir_biridan_ajralmaydi():
    assert set(rp.ALWAYS_FILES) | set(rp.OPTIONAL_AGENT_FILES) == set(AGENT_ARTIFACTS)
    assert not (set(rp.ALWAYS_FILES) & set(rp.OPTIONAL_AGENT_FILES))
    assert all(n in rb.CHECK_NAMES for n in rp.BUNDLE_SECRET_CHECKS)


def test_PAKETSIZ_yiqilish_papkasi_QONUNIY(tmp_path):
    """⚠️⚠️ `states.FAILURE_MEANING` operatorga «natija papkasini hisoboti bilan uzating»
    deydi — demak yiqilgan yurish HAM papka qoldiradi."""
    root = pathlib.Path(paketsiz().write(str(tmp_path)))
    rp.validate_result_package(str(root))
    assert sorted(p.name for p in root.iterdir()) == sorted(rp.ALWAYS_FILES)
    assert not (root / BUNDLE_SUBDIR).exists()


def test_YETIM_paket_RAD():
    """Paket BOR, lekin yozuv uni DA'VO QILMAYDI (`bundle_dir` — `null`)."""
    with pytest.raises(rp.ResultPackageError, match="yetim paket"):
        paketsiz(bundle=phase4_bundle()).members()


def test_BOSH_DALVO_RAD():
    """Yozuv `bundle_dir` ni da'vo qiladi, paket esa YO'Q."""
    yozuv = yiqilgan_status(artifacts=rp.ALWAYS_FILES, bundle_dir=BUNDLE_SUBDIR)
    with pytest.raises(rp.ResultPackageError, match="da'vo bo'sh"):
        paketsiz(status_json=yozuv).members()


def test_COMPLETE_paketsiz_BOLMAYDI():
    nomlar = sorted(set(AGENT_ARTIFACTS))
    with pytest.raises(rp.ResultPackageError, match="razvedka paketsiz TUGAMAYDI"):
        rp.ResultPackage.from_parts(
            timestamp=TS, status_json=status_matni(nomlar), environment_json=env_matni(),
            report_md=REPORT_MD, ai_candidates_json=AI_MATNI).members()


def test_COMPLETE_analitiksiz_BOLMAYDI():
    bundle = phase4_bundle()
    nomlar = sorted(set(rp.ALWAYS_FILES) | {f"{BUNDLE_SUBDIR}/{n}" for n in bundle})
    with pytest.raises(rp.ResultPackageError, match=re.escape(AI_CANDIDATES_FILE)):
        rp.ResultPackage.from_parts(
            timestamp=TS, status_json=status_matni(nomlar), environment_json=env_matni(),
            report_md=REPORT_MD, bundle=bundle).members()


def test_yiqilgan_yurishda_BUZUQ_paket_DALIL_bolib_saqlanadi(tmp_path):
    """⚠️⚠️ ASIMMETRIYA: `COMPLETE` da `bundle/` validatordan TO'LIQ o'tadi, yiqilgan
    yurishda esa paket NUQSONI bilan saqlanadi — aks holda yagona dalil yo'q qilinardi."""
    buzuq = phase4_bundle(drop=(rb.EXPORT_FILE,))
    yozuv = yiqilgan_status(artifacts=rp.ALWAYS_FILES, bundle_dir=BUNDLE_SUBDIR,
                            via=(st.VALIDATION,), state=st.FAILED_VALIDATION)
    root = pathlib.Path(paketsiz(status_json=yozuv, bundle=buzuq).write(str(tmp_path)))
    rp.validate_result_package(str(root))
    assert (root / BUNDLE_SUBDIR / rb.METADATA_FILE).exists()


def test_yiqilgan_yurishda_ham_SIR_RAD():
    """⚠️ Dalilni saqlash sirni chiqarishni OQLAMAYDI."""
    sirli = phase4_bundle(drop=(rb.EXPORT_FILE,))
    sirli[rb.RUN_SUMMARY_FILE] = "# h\n\nBaza paroli: hunter2\n".encode("utf-8")
    yozuv = yiqilgan_status(artifacts=rp.ALWAYS_FILES, bundle_dir=BUNDLE_SUBDIR,
                            via=(st.VALIDATION,), state=st.FAILED_VALIDATION)
    with pytest.raises(rp.ResultPackageError, match="maxfiylik_skani"):
        paketsiz(status_json=yozuv, bundle=sirli).members()


def test_yurish_yozuvi_OQILMASA_HAMMA_artefakt_talab_qilinadi(tmp_path):
    """⚠️ FAIL-CLOSED: shakl chiqarib bo'lmasa, eng QAT'IY talab qo'llanadi."""
    root = pathlib.Path(paketsiz().write(str(tmp_path)))
    (root / AGENT_STATUS_FILE).write_bytes(b"{buzuq\n")
    matn = muammolar(root)
    assert AI_CANDIDATES_FILE in matn
    assert "majburiy artefakt(lar) yo'q" in matn


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6c · `presence_verdict` IKKI HUJJATDA TENG (aks holda paket O'Z-O'ZIGA ZID bo'ladi)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️⚠️ NEGA SHU DARVOZA KERAK: `agent_status.json` ham, `environment.json` ham AYNI savolga
#:    javob beradi — «1C bormi». Ikkisi boshqacha javob bersa, paketning ichida bir hujjat
#:    «qaray olmadim», ikkinchisi «topildi» deyishi mumkin bo'lardi, ya'ni loyihaning O'ZAK
#:    invarianti (`UNKNOWN` hech qachon `NOT_FOUND` ga aylanmaydi) PAKET darajasida teshik
#:    qolardi. `environment_file` uchun ikki tomonlama darvoza ALLAQACHON bor edi, hukm uchun
#:    esa YO'Q — ASIMMETRIYA shu yerda tugaydi.
#: ⚠️ ZID JUFTLIKLAR ro'yxati IKKI TOMONLAMA: har bir juftlik teskarisi bilan birga turadi,
#:    chunki darvoza «qaysi hujjat haqiqat» deb HUKM CHIQARMAYDI — u faqat ZIDLIKNI rad etadi.
ZID_JUFTLIKLAR: tuple[tuple[str, str], ...] = (
    (det.PRESENCE_FOUND, det.PRESENCE_UNKNOWN),
    (det.PRESENCE_UNKNOWN, det.PRESENCE_FOUND),
    (det.PRESENCE_ABSENT, det.PRESENCE_UNKNOWN),
    (det.PRESENCE_UNKNOWN, det.PRESENCE_ABSENT),
    (det.PRESENCE_FOUND, det.PRESENCE_ABSENT),
    (det.PRESENCE_ABSENT, det.PRESENCE_FOUND),
)


@pytest.mark.parametrize("verdikt", [det.PRESENCE_FOUND, det.PRESENCE_ABSENT,
                                     det.PRESENCE_UNKNOWN])
def test_presence_verdict_IKKI_hujjatda_TENG_bolsa_OTADI(verdikt):
    """⚠️ UCHALA hukm QONUNIY — darvoza qiymatni emas, ZIDLIKNI rad etadi."""
    paketsiz(status_json=yiqilgan_status(artifacts=rp.ALWAYS_FILES, verdict=verdikt),
             environment_json=env_hukm(verdikt)).members()


@pytest.mark.parametrize("muhit,yozuv", list(ZID_JUFTLIKLAR))
def test_presence_verdict_ZID_bolsa_RAD(muhit, yozuv):
    """⚠️⚠️ NUQSON: bu zidlikni HECH QAYSI darvoza tutmasdi (`problems()` BO'SH qaytardi).

    ⚠️ Eng qimmat juftlik — `unknown` + `absent`: bitta paket ichida «qaray olmadim»
       «qaradim va yo'q» ga aylanib qoladi, operator esa 1C ni O'RNATISHGA yuboriladi.
    """
    nuqsonlar = paketsiz(
        status_json=yiqilgan_status(artifacts=rp.ALWAYS_FILES, verdict=yozuv),
        environment_json=env_hukm(muhit)).problems()
    assert any("presence_verdict" in n and muhit in n and yozuv in n
               for n in nuqsonlar), \
        f"hukm ZIDLIGI TUTILMADI ({muhit!r} ≠ {yozuv!r}): {nuqsonlar}"


def test_presence_verdict_ZIDLIGI_PAKETNI_butunlay_RAD_etadi():
    """⚠️ Fail-closed: nuqson ro'yxatda qolib ketmaydi, `members()` HECH NARSA qaytarmaydi."""
    with pytest.raises(rp.ResultPackageError, match="presence_verdict"):
        paketsiz(status_json=yiqilgan_status(artifacts=rp.ALWAYS_FILES,
                                            verdict=det.PRESENCE_ABSENT),
                 environment_json=env_hukm(det.PRESENCE_UNKNOWN)).members()


def test_presence_verdict_ZIDLIGI_DISKDA_ham_RAD(tmp_path):
    """⚠️ Darvoza diskdagi papkada ham ishlaydi: fayl QO'LDA tahrirlangan bo'lishi mumkin."""
    root = pathlib.Path(paketsiz().write(str(tmp_path)))
    doc = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    assert doc["presence_verdict"] == det.PRESENCE_FOUND, "fikstura: ikki hujjat MOS edi"
    doc["presence_verdict"] = det.PRESENCE_UNKNOWN
    # BAYTLAR BILAN YOZILADI: `write_text` Windowsda qator oxirini o'zgartiradi va determinizm
    # darvozasi qo'shimcha nuqson qo'shib, o'lchanadigan xabarni ko'mib yuborardi.
    (root / AGENT_STATUS_FILE).write_bytes(dumps(doc).encode("utf-8"))
    matn = muammolar(root)
    assert "presence_verdict" in matn and det.PRESENCE_UNKNOWN in matn, matn


def test_presence_verdict_ZIDLIGI_COMPLETE_yurishda_ham_RAD():
    """⚠️ Darvoza HOLATDAN MUSTAQIL: tugagan yurish ham o'z-o'ziga zid bo'lolmaydi."""
    nomlar = sorted(set(AGENT_ARTIFACTS) | {f"{BUNDLE_SUBDIR}/{n}"
                                            for n in phase4_bundle()})
    with pytest.raises(rp.ResultPackageError, match="presence_verdict"):
        paket(status=status_matni(nomlar, verdict=det.PRESENCE_UNKNOWN)).members()


def test_presence_verdict_MUHIT_hujjati_BUZUQ_bolsa_OZ_darvozasi_gapiradi():
    """⚠️ Hukm lug'atdan tashqarida bo'lsa, zidlik xabari QO'SHILMAYDI — chunki
       `environment.json` ning O'Z darvozasi uni allaqachon RAD etadi va paket baribir
       yozilmaydi. Ikki xabar bir nuqsonni ikki marta sanab, operatorni chalg'itardi.
    """
    doc = json.loads(env_matni())
    doc["presence_verdict"] = "not_found"          # ⚠️ lug'atda YO'Q
    yomon = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    nuqsonlar = paketsiz(environment_json=yomon).problems()
    assert any("presence_verdict" in n and "not_found" in n for n in nuqsonlar)
    assert not any("ZID" in n for n in nuqsonlar), nuqsonlar


def test_FIKSTURALAR_ikki_hujjatda_AYNI_hukmni_yozadi():
    """⚠️⚠️ TO'PLAMNING O'Z FIKSTURASI nuqsonni JONLI saqlab turgan edi — bu test shuni
       qulflaydi: har bir paket quruvchisi ikki hujjatga AYNI hukmni yozadi.
    """
    for qurgich in (paket, paketsiz, xatoli_paket):
        obj = qurgich()
        assert (json.loads(obj.status_json)["presence_verdict"]
                == json.loads(obj.environment_json)["presence_verdict"]), qurgich.__name__


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · DETERMINIZM va YOZISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_determinizm_bir_xil_kirish_bir_xil_bayt():
    birinchi = paket().members()
    ikkinchi = paket().members()
    assert birinchi == ikkinchi
    assert list(birinchi) == sorted(birinchi)  # tartib ham barqaror


def test_determinizm_DISKDA_ham(tmp_path):
    a = yoz(tmp_path / "a")
    b = yoz(tmp_path / "b")
    for yo_l in sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file()):
        assert (a / yo_l).read_bytes() == (b / yo_l).read_bytes()


def test_mavjud_papkaga_YOZMAYDI(tmp_path):
    """⚠️ Har yurish O'Z papkasini oladi: oldingisi o'chmaydi va ustiga yozilmaydi."""
    yoz(tmp_path)
    with pytest.raises(FileExistsError):
        paket().write(str(tmp_path))


def test_BIR_XIL_mazmun_boshqa_TIMESTAMP_boshqa_papka(tmp_path):
    bitta = yoz(tmp_path, timestamp=TS)
    ikki = yoz(tmp_path, timestamp="20260930T101431Z")
    assert bitta != ikki
    assert (bitta / REPORT_FILE).read_bytes() == (ikki / REPORT_FILE).read_bytes()


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8 · STATIK DARVOZALAR (agent paketining O'ZI)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Taqiqlangan tarmoq modullari. ⚠️ Offline-first: deterministik LOKAL analitik MAJBURIY,
#: cloud AI YO'Q. Importning O'ZI ham bo'lmaydi — «ishlatilmaydi» degan da'vo tekshirilmaydi.
TARMOQ_MODULLARI = ("socket", "ssl", "requests", "urllib", "urllib3", "http", "httpx",
                    "http.client", "xmlrpc", "ftplib", "smtplib", "telnetlib", "asyncio")


def _import_nomlari(src: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


@pytest.mark.parametrize("fayl", PAKET_FAYLLARI, ids=lambda p: p.name)
def test_agent_paketida_TARMOQ_importi_YOQ(fayl: pathlib.Path):
    nomlar = _import_nomlari(fayl.read_text("utf-8"))
    ildizlar = {n.split(".")[0] for n in nomlar} | nomlar
    topilgan = sorted(ildizlar & set(TARMOQ_MODULLARI))
    assert not topilgan, f"{fayl.name}: tarmoq importi {topilgan} — TAQIQLANGAN"


#: Yashirin davomiylik belgilari. ⚠️ Agent FAQAT operator ishga tushirganda ishlaydi:
#: avtoyuklanish YO'Q, Windows xizmati YO'Q, reestrga YOZISH YO'Q, rejalashtirilgan
#: topshiriq YO'Q.
#: ⚠️ `startfile` bu ro'yxatda EMAS va bu ATAYLAB: `os.startfile` operator TUGMANI bosganda,
#:    faqat agentning O'ZI yozgan natija papkasi ICHIDAGI yo'lni ochadi (`ui._open` darvozasi).
YASHIRIN_BELGILAR = ("SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey",
                     "CreateService", "StartService", "schtasks", "sc.exe", "Task Scheduler",
                     "CurrentVersion\\Run", "RunOnce", "startup", "autostart", "autorun",
                     "pythonw", "win32serviceutil", "ShellExecute")


@pytest.mark.parametrize("fayl", PAKET_FAYLLARI, ids=lambda p: p.name)
def test_agent_paketida_YASHIRIN_davomiylik_belgilari_YOQ(fayl: pathlib.Path):
    src = fayl.read_text("utf-8")
    topilgan = sorted(b for b in YASHIRIN_BELGILAR if b.lower() in src.lower())
    assert not topilgan, (f"{fayl.name}: yashirin davomiylik belgisi {topilgan} — "
                          f"avtoyuklanish/xizmat/reestrga yozish TAQIQLANGAN")


@pytest.mark.parametrize("fayl", PAKET_FAYLLARI, ids=lambda p: p.name)
def test_agent_paketida_TASHQI_kutubxona_YOQ(fayl: pathlib.Path):
    """⚠️ Faqat stdlib + `tkinter`: do'kon kompyuterida Python o'rnatish talab
    QILINMASLIGI kerak va `pywin32` O'RNATILMAGAN."""
    taqiq = {"pywin32", "win32com", "win32api", "pythoncom", "requests", "pydantic",
             "sqlalchemy", "fastapi", "numpy", "pandas", "pyinstaller"}
    nomlar = {n.split(".")[0] for n in _import_nomlari(fayl.read_text("utf-8"))}
    assert not (nomlar & taqiq), f"{fayl.name}: tashqi kutubxona {sorted(nomlar & taqiq)}"


def test_agent_paketi_FASTAPI_qatlamiga_bogliq_EMAS():
    """⚠️ Agent alohida `.exe` bo'lib yig'iladi: server qatlamiga bog'lanish portable
    build ni imkonsiz qilardi."""
    for fayl in PAKET_FAYLLARI:
        nomlar = _import_nomlari(fayl.read_text("utf-8"))
        assert not any(n.startswith("app.") and "discovery" not in n and "migrator" not in n
                       for n in nomlar), fayl.name


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9 · UI — MANTIQSIZ QOBIQ, tkinter'SIZ ham sinaladi
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_ui_tkintersiz_IMPORT_qilinadi(monkeypatch):
    """⚠️ CI Linux'da `tkinter` bo'lmasligi mumkin: modul BARIBIR import qilinadi, `TK_MAVJUD`
    esa `False` bo'ladi. «Jimgina ishlamaslik» YO'Q — oyna ochishga urinish ANIQ xato."""
    monkeypatch.setitem(sys.modules, "tkinter", None)
    try:
        qayta = importlib.reload(agent_ui)
        assert qayta.TK_MAVJUD is False
        with pytest.raises(qayta.UiError, match="tkinter"):
            qayta.launch(parent_dir=".")
    finally:
        monkeypatch.undo()
        importlib.reload(agent_ui)


def test_ui_tkinter_importi_HIMOYALANGAN():
    """Statik dalil: `tkinter` importi `try` ichida turadi (reload bilan ham tekshirildi)."""
    daraxt = ast.parse(pathlib.Path(agent_ui.__file__).read_text("utf-8"))
    himoyalangan = {n.name for try_ in ast.walk(daraxt) if isinstance(try_, ast.Try)
                    for node in ast.walk(try_) if isinstance(node, ast.Import)
                    for n in node.names}
    assert "tkinter" in himoyalangan


def test_UiModel_tkinterga_TEGMAYDI():
    """⚠️ UI MANTIQNI O'Z ICHIGA OLMAYDI: `UiModel` vidjetlarga murojaat qilmaydi, shu bois
    butun xulq UI siz sinaladi."""
    src = inspect.getsource(agent_ui.UiModel)
    for belgi in ("tk.", "messagebox", "filedialog", "Listbox", "mainloop"):
        assert belgi not in src


class SuruvchiSoat:
    """Soxta monoton soat: `sleep` vaqtni SURADI.

    ⚠️⚠️ NEGA KERAK BO'LIB QOLDI: `watch_folder` yo'lining normal oqimi endi ko'prikning
         KUTISH mantig'idan o'tadi (brief §6C — bo'sh papka KUTILADI, so'ng `FAILED_TIMEOUT`).
         Haqiqiy soat va haqiqiy `time.sleep` bilan bu testlar daqiqalar kutardi.
    ⚠️ QOTIB QOLGAN soat (`lambda: 0.0`) ATAYLAB ISHLATILMAYDI: u vaqt chegarasini hech
       qachon urmaydi. Ko'prikda o'lchov soni chegarasi ham bor, lekin test xulqni O'LCHASHI
       kerak — zaxira darvozaga tayanish nimani o'lchayotganini yashirardi.
    """

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.sleeps.append(dt)
        self.t += dt


def model(tmp_path, **kw) -> agent_ui.UiModel:
    """⚠️ Soat ham, skaner ham SINTETIK: test haqiqiy reestrni o'qimaydi va soatga qaramaydi.

    ⚠️ KUTISH ham SINTETIK: `clock`/`sleeper` soxta soatdan keladi va kutish chegarasi
       QISQA — haqiqiy soniyalar kutilmaydi (`SuruvchiSoat` izohiga qarang).
    """
    kw.setdefault("scan", lambda: env_scan())
    kw.setdefault("now", lambda: T0)
    soat = SuruvchiSoat()
    kw.setdefault("clock", soat)
    kw.setdefault("sleeper", soat.sleep)
    kw.setdefault("watch_timeout_seconds", 10.0)
    kw.setdefault("watch_poll_seconds", 2.0)
    return agent_ui.UiModel(parent_dir=str(tmp_path), **kw)


def test_ui_READ_ONLY_holatini_korsatadi(tmp_path):
    m = model(tmp_path)
    assert "READ ONLY" in m.read_only_line()
    assert "O'QIYDI" in m.read_only_line()


def test_ui_aniqlangan_1C_va_nishonni_korsatadi(tmp_path):
    m = model(tmp_path)
    m.refresh_environment()
    assert "topildi" in m.install_line() and "8.3.24.1548" in m.install_line()
    assert "Dokon savdo" in m.target_line()
    # ⚠️ KO'RSATISH uchun skanerlash YURISH EMAS: progress `START` da qoladi.
    assert m.progress == st.START


def test_ui_nishon_yorligida_MAHALLIY_YOL_YOQ(tmp_path):
    """⚠️ Fayl bazasining `locator` i — mahalliy yo'l, u EKRANGA chiqmaydi."""
    m = model(tmp_path)
    m.refresh_environment()
    for yorliq in m.target_labels():
        assert "bazalar" not in yorliq and "C:\\" not in yorliq


def test_ui_1C_YOQ_va_OQILMADI_ni_ADASHTIRMAYDI(tmp_path):
    """⚠️⚠️ `UNKNOWN` HECH QACHON `NOT_FOUND` ga aylanmaydi — UI matnida ham."""
    yoq = model(tmp_path, scan=lambda: env_scan(installs=(), infobases=()))
    yoq.refresh_environment()
    assert "O'RNATILMAGAN" in yoq.install_line()

    oqilmadi = model(tmp_path, scan=lambda: env_scan(
        installs=(), infobases=(),
        unreadables=(det.Unreadable(scope="registry", code=det.CODE_REGISTRY_UNREADABLE,
                                    detail="huquq yetmadi"),)))
    oqilmadi.refresh_environment()
    assert "NOMA'LUM" in oqilmadi.install_line()
    assert "O'RNATILMAGAN" not in oqilmadi.install_line()


def test_ui_baza_yoq_bolsa_nishon_TANLANMAYDI(tmp_path):
    m = model(tmp_path, scan=lambda: env_scan(infobases=()))
    m.refresh_environment()
    assert m.selected_index is None
    assert "baza topilmadi" in m.target_line()


def test_ui_muhit_skaneri_YIQILSA_JIM_yutilmaydi(tmp_path):
    """⚠️ Kutilmagan istisno `FAILED_INTERNAL` ga tushadi (NUQSON), matni NIQOBLANADI."""
    def yiqiladigan():
        raise RuntimeError(r"reestr o'qilmadi: C:\bazalar\dokon")

    natija = model(tmp_path, scan=yiqiladigan).start()
    assert natija.state == st.FAILED_INTERNAL
    assert natija.code == agent_ui.CODE_ICHKI_XATO
    # ⚠️ Istisno matnidagi mahalliy yo'l NIQOBLANADI: u ekrandan jurnalga ko'chadi.
    assert "bazalar" not in natija.detail
    assert "[REDACTED]" in natija.detail


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9b · UI → QUVUR → NATIJA PAKETI (HAQIQIY modullar, 1C SIZ)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Bu bo'limda `pipeline`, `collector_bridge`, `report` va `result_package` HAQIQATDA
#:    chaqiriladi — soxta quvur YO'Q. 1C esa KERAK EMAS: paket allaqachon yozilgan papkadan
#:    o'qiladi (`watch_folder` yo'lining natijasi), ya'ni aynan shu yo'l bu mashinada
#:    bajarilishi MUMKIN bo'lgan yagona yo'l (`AGENT_INTEGRATION_MATRIX.md`, 5-qator).
def kuzatilgan_papka(tmp_path: pathlib.Path, bundle=None, nom="kuzatilgan") -> pathlib.Path:
    """Yig'uvchi YOZGAN papkani taqlid qiladi (Phase 4 paketining sintetik fiksturasi)."""
    root = tmp_path / nom
    root.mkdir(parents=True, exist_ok=True)
    for nomi, raw in (phase4_bundle() if bundle is None else bundle).items():
        p = root / nomi
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    return root


def test_ui_START_butun_quvurni_yuritadi_va_paketni_TEKSHIRADI(tmp_path):
    """⚠️ Holat QUVURDAN keladi — UI o'zidan «COMPLETE» DEMAYDI."""
    m = model(tmp_path / "natija", bundle_dir=str(kuzatilgan_papka(tmp_path)))
    (tmp_path / "natija").mkdir()
    natija = m.start()
    assert natija.state == st.COMPLETE, natija.problems
    assert not natija.is_failure
    assert pathlib.Path(natija.result_dir).name == f"{RESULT_DIR_PREFIX}{TS}"
    assert m.progress == st.COMPLETE
    # ⚠️ Paket diskda TO'LIQ va validatordan o'tadi.
    rp.validate_result_package(natija.result_dir)


def test_ui_MANBA_papkasiga_TEGILMAYDI(tmp_path):
    """⚠️ FAQAT O'QISH: yig'uvchi papkasi bayt-ba-bayt O'QILADI, o'zgartirilmaydi."""
    manba = kuzatilgan_papka(tmp_path)
    oldin = {p.name: p.read_bytes() for p in manba.iterdir()}
    (tmp_path / "natija").mkdir()
    model(tmp_path / "natija", bundle_dir=str(manba)).start()
    assert {p.name: p.read_bytes() for p in manba.iterdir()} == oldin


def test_ui_BOSH_papka_KUTILADI_va_vaqt_tugasa_papka_BARIBIR_yoziladi(tmp_path):
    """⚠️⚠️ XULQ O'ZGARDI (brief §6C) va bu ATAYLAB: BO'SH papka endi darhol «paket yo'q» deb
         hukm qilinmaydi — u yig'uvchi hali YOZMAGAN NORMAL holat, shu bois agent KUTADI va
         vaqt tugaganda `FAILED_TIMEOUT` beradi. Oldin bu `FAILED_COLLECTOR_UNAVAILABLE` edi,
         ya'ni «yig'uvchi javob bermadi» degan HUKM — holbuki operator yig'uvchini hali ishga
         tushirmagan bo'lishi mumkin.
    ⚠️ `FAILED_COLLECTOR_UNAVAILABLE` esa papka UMUMAN YO'Q/O'QILMAGAN holatda qoladi
       (`test_ui_papka_YOQ_bolsa_...`): kutish papkani YARATMAYDI.
    ⚠️ O'ZGARMAGAN QISMI: yiqilgan yurish ham natija papkasini QOLDIRADI —
       `states.failure_meaning` operatorga aynan shu papkani uzatishni aytadi."""
    bosh = tmp_path / "bosh"
    bosh.mkdir()
    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(bosh))
    natija = m.start()
    assert natija.state == st.FAILED_TIMEOUT, natija.problems
    assert natija.state != st.FAILED_NO_1C, "1C bor-yo'qligi haqida bu HECH NARSA demaydi"
    assert m.waiting_ticks > 0, "kutish ROSTDAN bo'ldi va operator uni ko'rdi"
    root = pathlib.Path(natija.result_dir)
    rp.validate_result_package(str(root))
    # ⚠️ Paketsiz papka: `bundle/` YO'Q, analitik artefakti ham YO'Q, qolganlari BOR.
    assert not (root / BUNDLE_SUBDIR).exists()
    assert not (root / AI_CANDIDATES_FILE).exists()
    assert sorted(p.name for p in root.iterdir()) == sorted(rp.ALWAYS_FILES)
    doc = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    assert doc["bundle_dir"] is None
    assert doc["route"] == ROUTE_WATCH_FOLDER


def test_ui_papka_YOQ_bolsa_KUTMAYDI_balki_COLLECTOR_UNAVAILABLE(tmp_path):
    """⚠️ FAIL-CLOSED va TEZ: kutish papkani YARATMAYDI, demak kutish bu holatni hech qachon
    tuzatmaydi. «Bo'sh papka» (kutiladi) va «papka yo'q» (darhol yiqiladi) IKKI XIL vaziyat."""
    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(tmp_path / "umuman-yoq"))
    natija = m.start()
    assert natija.state == st.FAILED_COLLECTOR_UNAVAILABLE, natija.problems
    assert m.waiting_ticks == 0, "papka yo'q bo'lsa kutish UMUMAN boshlanmaydi"
    doc = json.loads((pathlib.Path(natija.result_dir) / AGENT_STATUS_FILE).read_text("utf-8"))
    assert "BUNDLE_DIR_MISSING" in [e["code"] for e in doc["errors"]]
    assert doc["bundle_dir"] is None


def test_ui_YARIM_yozilgan_manifest_PAKET_deb_qabul_QILINMAYDI(tmp_path):
    """⚠️⚠️ SHIPPED OQIM KO'PRIKNING TAYYORLIK ISBOTIDAN O'TADI. Oldin UI faqat «papkada
         yozuv bormi» deb qarardi, ya'ni yarim yozilgan `manifest.json` «paket bor» bo'lib
         o'tib ketardi va Phase 4 da yolg'on SUCCESS bergan nuqson qaytib kelardi."""
    manba = kuzatilgan_papka(tmp_path)
    (manba / rb.MANIFEST_FILE).write_text('{"manifest_version": "binos-1c-mani',
                                          encoding="utf-8")
    (tmp_path / "natija").mkdir()
    natija = model(tmp_path / "natija", bundle_dir=str(manba)).start()
    assert natija.state == st.FAILED_TIMEOUT, natija.problems
    root = pathlib.Path(natija.result_dir)
    rp.validate_result_package(str(root))
    assert not (root / BUNDLE_SUBDIR).exists(), "yarim paket UZATILMAYDI"


def test_ui_BUZUQ_paket_DALIL_bolib_saqlanadi(tmp_path):
    """⚠️⚠️ Yiqilgan yurishda `bundle/` Phase 4 validatoridan O'TMASLIGI MUMKIN: rad etilgan
    paket aynan NUQSONI bilan saqlanadi, aks holda yagona dalil yo'q qilinardi."""
    buzuq = phase4_bundle(drop=(rb.EXPORT_FILE,))
    manba = kuzatilgan_papka(tmp_path, bundle=buzuq)
    (tmp_path / "natija").mkdir()
    natija = model(tmp_path / "natija", bundle_dir=str(manba)).start()
    assert natija.state == st.FAILED_VALIDATION, natija.problems
    root = pathlib.Path(natija.result_dir)
    rp.validate_result_package(str(root))
    assert (root / BUNDLE_SUBDIR / rb.METADATA_FILE).exists()
    assert not (root / BUNDLE_SUBDIR / rb.EXPORT_FILE).exists()


def test_ui_SIRLI_paket_yiqilishda_HAM_RAD_lekin_MINIMAL_PAKET_qoladi(tmp_path):
    """⚠️ Dalilni saqlash sirni chiqarishni OQLAMAYDI: sirli `bundle/` paketga TUSHMAYDI.

    ⚠️⚠️ LEKIN OPERATOR BO'SH QO'L BILAN QOLMAYDI (brief §2): minimal, SIRSIZ paket yoziladi
         va u `validate_result_package` dan O'TADI. Avval bu yerda `result_dir is None` edi —
         ya'ni sir ANIQLANGANI faktining ham hujjatli izi qolmasdi.
    """
    sirli = phase4_bundle(drop=(rb.EXPORT_FILE,))
    sirli[rb.RUN_SUMMARY_FILE] = "# hisobot\n\nBaza paroli: hunter2\n".encode("utf-8")
    manba = kuzatilgan_papka(tmp_path, bundle=sirli)
    (tmp_path / "natija").mkdir()
    natija = model(tmp_path / "natija", bundle_dir=str(manba)).start()
    assert natija.state == st.FAILED_REPORT
    assert natija.code == agent_ui.CODE_SIR_USHLANDI
    assert natija.result_dir is not None, "sir topilsa ham UZATILADIGAN paket qoladi"

    root = pathlib.Path(natija.result_dir)
    rp.validate_result_package(str(root))
    # ⚠️ SIRNING O'ZI YOZILMAYDI: `bundle/` ham, nomzodlar ham paketda YO'Q.
    assert sorted(p.name for p in root.iterdir()) == sorted(rp.ALWAYS_FILES)
    assert not (root / BUNDLE_SUBDIR).exists()
    assert "hunter2" not in "".join((root / n).read_text("utf-8") for n in rp.ALWAYS_FILES)
    # ⚠️ Sir QAYSI artefaktda topilgani yozuvda turadi — QIYMATI esa YO'Q.
    yozuv = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    sabab = [e["detail"] for e in yozuv["errors"] if e["code"] == agent_ui.CODE_SIR_USHLANDI]
    assert len(sabab) == 1 and f"{BUNDLE_SUBDIR}/{rb.RUN_SUMMARY_FILE}" in sabab[0]
    assert errors_doc(root)["errors"] == yozuv["errors"]


def test_ui_OPEN_tugmalari_yurishdan_OLDIN_ANIQ_xato(tmp_path):
    m = model(tmp_path)
    with pytest.raises(agent_ui.UiError, match="Start Discovery"):
        m.open_report()
    with pytest.raises(agent_ui.UiError, match="Start Discovery"):
        m.open_result_folder()


def test_ui_OPEN_faqat_natija_papkasi_ICHINI_ochadi(tmp_path):
    ochilgan: list[str] = []
    natija_dir = tmp_path / "natija"
    natija_dir.mkdir()
    m = model(natija_dir, bundle_dir=str(kuzatilgan_papka(tmp_path)),
              opener=ochilgan.append)
    natija = m.start()
    assert natija.state == st.COMPLETE, natija.problems

    assert m.open_report().endswith(REPORT_FILE)
    assert m.open_result_folder() == os.path.abspath(natija.result_dir)
    assert len(ochilgan) == 2

    # ⚠️ Papkadan TASHQARIDAGI yo'l ochilmaydi: «ochish» ixtiyoriy dastur ishga tushirish
    #    yo'liga aylanmasligi kerak.
    with pytest.raises(agent_ui.UiError, match="TASHQARIDAGI"):
        m._open(str(natija_dir))
    with pytest.raises(agent_ui.UiError, match="TASHQARIDAGI"):
        m._open(str(pathlib.Path(natija.result_dir) / ".." / "boshqa"))
    assert len(ochilgan) == 2  # hech narsa qo'shilmadi


def test_ui_progress_HOLAT_NOMI_bolib_boradi(tmp_path):
    kuzatuv: list[str] = []
    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(kuzatilgan_papka(tmp_path)))
    m.on_progress = kuzatuv.append
    m.start()
    assert kuzatuv[0] == st.ENVIRONMENT_SCAN
    assert kuzatuv[-1] == st.COMPLETE
    assert all(st.is_known(h) for h in kuzatuv)
    # ⚠️ Quvurning holatlari ham ko'rinadi (yurishdan KEYIN takrorlanadi).
    assert st.METADATA_DISCOVERY in kuzatuv and st.VALIDATION in kuzatuv


def test_ui_detektor_XATO_KODI_yurish_yozuviga_moslashtiriladi(tmp_path):
    """⚠️⚠️ TOPILGAN MOSLIKSIZLIK: `detector` xato kodlarini KICHIK harfda yozadi
    (`registry_unreadable`), `status.ERROR_CODE_RE` esa `[A-Z][A-Z0-9_]+` talab qiladi —
    ya'ni xom kod yurish yozuvini RAD etardi va BUTUN paket yozilmasdi. Ulagich kodni
    KATTA harfga keltiradi; KATTA harfli kod esa O'ZGARMAYDI."""
    assert agent_ui._error_code(det.CODE_REGISTRY_UNREADABLE) == "REGISTRY_UNREADABLE"
    assert agent_ui._error_code("EPF_MISSING") == "EPF_MISSING"

    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(kuzatilgan_papka(tmp_path)),
              scan=lambda: env_scan(unreadables=(det.Unreadable(
                  scope="registry", code=det.CODE_REGISTRY_UNREADABLE,
                  detail="huquq yetmadi"),)))
    natija = m.start()
    assert natija.state == st.COMPLETE, natija.problems
    doc = json.loads((pathlib.Path(natija.result_dir) / AGENT_STATUS_FILE).read_text("utf-8"))
    # ⚠️ RO'YXAT AYNAN: `BATCH_EXECUTE_NOT_ATTEMPTED` har bir `watch_folder` yurishida
    #    ATAYLAB yoziladi — paketli yo'l NEGA urinilmagani JIM qolmasligi kerak (brief §4).
    #    Shu bois bu yerda «faqat bitta xato» deb turib olinmaydi, lekin ro'yxat baribir
    #    TO'LIQ solishtiriladi: kutilmagan xato jimgina qo'shilib ketmaydi.
    assert [e["code"] for e in doc["errors"]] == ["REGISTRY_UNREADABLE",
                                                  "BATCH_EXECUTE_NOT_ATTEMPTED"]


def test_ui_epf_YOQ_bolsa_KOPRIK_darvozasi_toxtatadi(tmp_path):
    """⚠️ `.epf` konteyneri repoda YO'Q (`AGENT_INTEGRATION_MATRIX.md`) — ko'prik buni
    `FAILED_COLLECTOR_UNAVAILABLE` deb aytadi, `FAILED_NO_1C` DEMAYDI."""
    chiqish = tmp_path / "chiqish"
    chiqish.mkdir()
    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", epf_path=str(tmp_path / "yoq.epf"),
              output_dir=str(chiqish))
    natija = m.start()
    assert natija.state == st.FAILED_COLLECTOR_UNAVAILABLE, natija.problems
    doc = json.loads((pathlib.Path(natija.result_dir) / AGENT_STATUS_FILE).read_text("utf-8"))
    assert [e["code"] for e in doc["errors"]] == ["EPF_MISSING"]
    assert doc["bundle_dir"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10 · KIRISH NUQTASI (`__main__`) — CHIQISH KODLARI SHARTNOMA
# ══════════════════════════════════════════════════════════════════════════════════════════
def ishga_tushir(argv, **kw):
    """⚠️ Muhit skaneri STANDART HOLDA sintetik: test haqiqiy reestrni O'QIMAYDI.

    ⚠️ KUTISH ham sintetik (`clock`/`sleeper`): `watch_folder` yo'li bo'sh papkani KUTADI va
       haqiqiy soat bilan bu test daqiqalar kutardi.
    """
    out, err = io.StringIO(), io.StringIO()
    kw.setdefault("scan", lambda: env_scan())
    soat = SuruvchiSoat()
    kw.setdefault("clock", soat)
    kw.setdefault("sleeper", soat.sleep)
    kod = agent_main.main(argv, out=out, err=err, **kw)
    return kod, out.getvalue(), err.getvalue()


def test_version_0_qaytaradi_va_RUNTIME_UNKNOWN_deydi():
    kod, out, _ = ishga_tushir(["--version"])
    assert kod == agent_main.EXIT_OK
    assert "RUNTIME-UNKNOWN" in out
    assert "FAQAT O'QISH" in out


def test_NOMALUM_bayroq_2_qaytaradi():
    kod, _, _ = ishga_tushir(["--yoq-bayroq"])
    assert kod == agent_main.EXIT_CANNOT_RUN


def test_yordam_0_qaytaradi():
    kod, _, _ = ishga_tushir(["--help"])
    assert kod == agent_main.EXIT_OK


def test_headless_papkasi_YOQ_bolsa_2(tmp_path):
    kod, _, err = ishga_tushir(["--headless", str(tmp_path / "yoq")])
    assert kod == agent_main.EXIT_CANNOT_RUN
    assert "topilmadi" in err


def test_headless_natija_papkasi_YOQ_bolsa_2(tmp_path):
    kod, _, err = ishga_tushir(["--headless", str(tmp_path),
                                "--result-dir", str(tmp_path / "yoq")])
    assert kod == agent_main.EXIT_CANNOT_RUN
    assert "topilmadi" in err


def test_headless_YAROQSIZ_timestamp_2(tmp_path):
    kod, _, err = ishga_tushir(["--headless", str(tmp_path), "--timestamp", "bugun"])
    assert kod == agent_main.EXIT_CANNOT_RUN
    assert "YYYYMMDDTHHMMSSZ" in err


def test_headless_TOGRI_yurish_0(tmp_path):
    """UCHIDAN-UCHIGA: HAQIQIY `pipeline` + `report` + `result_package`, 1C SIZ."""
    kirish = kuzatilgan_papka(tmp_path)
    natija = tmp_path / "natija"
    natija.mkdir()
    kod, out, err = ishga_tushir(["--headless", str(kirish), "--result-dir", str(natija),
                                  "--timestamp", TS])
    assert kod == agent_main.EXIT_OK, err
    assert f"holat: {st.COMPLETE}" in out
    assert f"{RESULT_DIR_PREFIX}{TS}" in out
    rp.validate_result_package(str(natija / f"{RESULT_DIR_PREFIX}{TS}"))


def test_headless_YIQILGAN_yurish_1_va_MANOSI_chiqadi(tmp_path):
    """⚠️ `1` — «yurish yiqildi» (bu ham JAVOB), `2` — «yurish BOSHLANMADI».

    ⚠️⚠️ YAKUN `FAILED_TIMEOUT` ga O'ZGARDI (brief §6C): bo'sh papka yig'uvchi hali YOZMAGAN
         normal holat, shu bois agent kutadi va vaqt tugaganda to'xtaydi. Oldin bu darhol
         `FAILED_COLLECTOR_UNAVAILABLE` («yig'uvchi javob bermadi») degan HUKM edi."""
    bosh = tmp_path / "bosh"
    bosh.mkdir()
    natija = tmp_path / "natija"
    natija.mkdir()
    kod, out, err = ishga_tushir(["--headless", str(bosh), "--timestamp", TS,
                                  "--result-dir", str(natija), "--wait-seconds", "10"])
    assert kod == agent_main.EXIT_FAILED_RUN
    assert st.FAILED_TIMEOUT in out
    # ⚠️ KUTISH OPERATOR EKRANIDA KO'RINADI: jim turgan agent «osilgan» deb o'qilardi.
    assert "kutilmoqda" in out
    # ⚠️ YO'L HAQQONIYLIGI: ekranda yig'uvchini OPERATOR ishga tushirishi AYTILADI.
    assert ROUTE_WATCH_FOLDER in out and "OPERATOR" in out
    # ⚠️ Yiqilish MA'NOSI: NIMA bo'ldi va NIMA QILISH kerak.
    assert "Keyingi qadam" in err
    rp.validate_result_package(str(natija / f"{RESULT_DIR_PREFIX}{TS}"))


def test_headless_wait_seconds_MUSBAT_bolmasa_yurish_BOSHLANMAYDI(tmp_path):
    """⚠️ FAIL-CLOSED: nol/manfiy/yaroqsiz chegara «cheksiz kut» DEGANI EMAS — `2` (yurish
    BOSHLANMADI). Cheksiz kutish bu agentda umuman mavjud emas."""
    for qiymat in ("0", "-5", "tezda"):
        kod, _, err = ishga_tushir(["--headless", str(tmp_path), "--wait-seconds", qiymat])
        assert kod == agent_main.EXIT_CANNOT_RUN, qiymat
        assert "Cheksiz kutish YO'Q" in err or "cheksiz kutish YO'Q" in err


def test_headless_1C_YOQ_bolsa_ham_MAVJUD_paket_oqiladi(tmp_path):
    """⚠️⚠️ 1C O'RNATILMAGAN bo'lsa ham mavjud paketni O'QISH uchun u KERAK EMAS — aks holda
    agent o'z ishini o'zi bloklardi. «1C yo'q» xulosasi FAQAT 1C ni ishga tushirishi kerak
    bo'lgan yo'lda yiqilishga aylanadi (`collector_bridge._batch_preflight`)."""
    kirish = kuzatilgan_papka(tmp_path)
    natija = tmp_path / "natija"
    natija.mkdir()
    kod, out, err = ishga_tushir(["--headless", str(kirish), "--timestamp", TS,
                                  "--result-dir", str(natija)],
                                 scan=lambda: env_scan(installs=(), infobases=()))
    assert kod == agent_main.EXIT_OK, err
    assert "O'RNATILMAGAN" in out
    assert f"holat: {st.COMPLETE}" in out


def test_UI_rejimi_tkinter_yoq_bolsa_2(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_ui, "TK_MAVJUD", False)
    kod, _, err = ishga_tushir(["--result-dir", str(tmp_path)])
    assert kod == agent_main.EXIT_CANNOT_RUN
    assert "--headless" in err


def test_UI_rejimi_oynani_ochadi(tmp_path):
    """⚠️ HAQIQIY oyna OCHILMAYDI: ochuvchi almashtiriladi (CI da displey yo'q)."""
    chaqiruvlar: list[dict] = []
    kod, _, _ = ishga_tushir(["--result-dir", str(tmp_path)],
                             launcher=lambda **kw: chaqiruvlar.append(kw))
    assert kod == agent_main.EXIT_OK
    assert chaqiruvlar == [{"parent_dir": str(tmp_path), "bundle_dir": None}]


def test_kirish_nuqtasida_PAROL_bayrogi_YOQ():
    """⚠️ Parol buyruq satrida jarayon ro'yxatida KO'RINADI — shu bois bayroq ATAYLAB yo'q."""
    yordam = agent_main.build_parser().format_help().lower()
    for taqiq in ("--password", "--parol", "--pwd", "/p<", "--user", "--usr"):
        assert taqiq not in yordam


# ══════════════════════════════════════════════════════════════════════════════════════════
# 11 · PORTABLE BUILD HUJJATI — «QURILDI» DEMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_portable_hujjati_MAVJUD():
    assert PORTABLE_DOC.is_file(), str(PORTABLE_DOC.name)


def test_portable_hujjati_IKKI_variantni_yozadi():
    matn = PORTABLE_DOC.read_text("utf-8")
    assert "PyInstaller" in matn
    assert "BinOSDiscoveryAgent.exe" in matn
    assert "embeddable" in matn.lower()


def test_portable_hujjati_QURILMAGANINI_ochiq_aytadi():
    """⚠️ `pyinstaller` O'RNATILMAGAN: «qurildi» deb aytish YOLG'ON bo'lardi."""
    matn = PORTABLE_DOC.read_text("utf-8")
    assert "QURILMAGAN" in matn
    assert "pyinstaller" in matn.lower()
    assert "3.12.10" in matn


def test_portable_hujjati_VENV_ga_ornatmaslikni_aytadi():
    """⚠️ `.venv` boshqa sessiyalar bilan BO'LISHILADI."""
    matn = PORTABLE_DOC.read_text("utf-8")
    assert ".venv" in matn
    assert "stdlib" in matn.lower()


# ══════════════════════════════════════════════════════════════════════════════════════════
# 11 · ILDIZDAGI `errors.json` (`binos-agent-errors-v1`) — IKKI SXEMA ARALASHMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Ikki xato — TARTIB ham tekshiriladi: ro'yxat `agent_status.errors` ning AYNAN nusxasi
#: bo'lishi kerak, «tartiblab qo'yish» ham o'zgartirish hisoblanadi.
IKKI_XATO: tuple[tuple[str, str, str], ...] = (
    ("collector:batch_execute", "EXE_MISSING", "1C ijro fayli topilmadi"),
    ("agent:environment", "REGISTRY_UNREADABLE", "reestr shoxiga huquq yetmadi"),
)


def xatoli_status(*, artifacts, xatolar=IKKI_XATO, state=st.FAILED_NO_1C) -> str:
    """Xatolari BOR yiqilgan yurish yozuvi (`FAILED_NO_1C` — `ENVIRONMENT_SCAN` dan)."""
    s = stat.new_run("run-0003", now=T0).advance(st.ENVIRONMENT_SCAN, now=T0)
    s = (s.with_environment_file(ENVIRONMENT_FILE).with_artifacts(artifacts)
         .with_presence_verdict(det.PRESENCE_ABSENT))
    for scope, code, detail in xatolar:
        s = s.with_error(scope, code, detail)
    return s.advance(state, now=T0, note="sintetik fikstura").to_json()


def xatoli_paket(**over) -> rp.ResultPackage:
    # ⚠️ `xatoli_status` `FAILED_NO_1C` + `absent` yozadi, demak MUHIT hujjati ham AYNI
    #    hukmni yozishi SHART (`env_matni()` ning standart holati — `found`).
    kw = dict(timestamp=TS, status_json=xatoli_status(artifacts=rp.ALWAYS_FILES),
              environment_json=env_hukm(det.PRESENCE_ABSENT), report_md=REPORT_MD)
    kw.update(over)
    return rp.ResultPackage.from_parts(**kw)


def errors_doc(root) -> dict:
    return json.loads((pathlib.Path(root) / ERRORS_FILE).read_text("utf-8"))


def test_ildizda_errors_json_AGENT_sxemasida_yoziladi(tmp_path):
    """`binos-agent-errors-v1`: `{errors_version, run_id, generated_at, errors, notes}`."""
    root = pathlib.Path(xatoli_paket().write(str(tmp_path)))
    rp.validate_result_package(str(root))
    doc = errors_doc(root)
    assert set(doc) == set(rp.AGENT_ERRORS_KEYS)
    assert doc["errors_version"] == ERRORS_VERSION
    assert doc["run_id"] == "run-0003"
    assert doc["notes"], "hujjat o'z chegarasini O'ZI bilan olib yuradi"
    assert [(e["scope"], e["code"], e["detail"]) for e in doc["errors"]] == list(IKKI_XATO)


def test_errors_json_agent_status_bilan_AYNAN_MOS(tmp_path):
    """⚠️⚠️ IKKI JOYDA ZID RO'YXAT — YANGI NUQSON: tenglik SHU YERDA qulflanadi."""
    root = pathlib.Path(xatoli_paket().write(str(tmp_path)))
    yozuv = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    doc = errors_doc(root)
    assert doc["errors"] == yozuv["errors"]
    assert doc["run_id"] == yozuv["run_id"]
    # ⚠️ Vaqt O'YLAB CHIQARILMAYDI: u yurish yozuvidan keladi.
    assert doc["generated_at"] == (yozuv["finished_at"] or yozuv["started_at"])


def test_errors_json_ZID_bolsa_RAD(tmp_path):
    """Diskda xato ro'yxati o'zgartirilsa — paket RAD (tartib o'zgarishi ham)."""
    root = pathlib.Path(xatoli_paket().write(str(tmp_path)))
    doc = errors_doc(root)
    doc["errors"] = list(reversed(doc["errors"]))
    (root / ERRORS_FILE).write_text(dumps(doc), encoding="utf-8")
    assert "TENG EMAS" in muammolar(root)


def test_errors_json_BOSHQA_yurishning_xatolarini_olmaydi(tmp_path):
    root = pathlib.Path(xatoli_paket().write(str(tmp_path)))
    doc = errors_doc(root)
    doc["run_id"] = "run-9999"
    (root / ERRORS_FILE).write_text(dumps(doc), encoding="utf-8")
    assert "yurish bilan mos emas" in muammolar(root)


def test_PHASE4_errors_hujjati_ILDIZDA_tursa_RAD(tmp_path):
    """⚠️⚠️ BIR XIL NOM, IKKI XIL SXEMA: Phase 4 hujjati ildizda TURMAYDI."""
    root = yoz(tmp_path)
    phase4 = (root / BUNDLE_SUBDIR / rb.ERRORS_FILE).read_bytes()
    (root / ERRORS_FILE).write_bytes(phase4)
    matn = muammolar(root)
    assert rb.ERRORS_VERSION in matn and ERRORS_VERSION in matn
    assert "ARALASHTIRILMAYDI" in matn


def test_AGENT_errors_hujjati_BUNDLE_ichida_tursa_RAD(tmp_path):
    """⚠️ Teskari tomon ham: agent hujjati `bundle/` da YADRO validatoridan O'TMAYDI."""
    root = yoz(tmp_path)
    agent_doc = (root / ERRORS_FILE).read_bytes()
    (root / BUNDLE_SUBDIR / rb.ERRORS_FILE).write_bytes(agent_doc)
    matn = muammolar(root)
    assert f"{BUNDLE_SUBDIR}/" in matn
    # ⚠️ YADRO uni O'Z sxemasi bilan rad etadi: agentning kalitlari Phase 4 da YO'Q.
    assert "run_id" in matn and "generated_at" in matn


def test_ildizdagi_errors_json_PHASE4_fayli_deb_hisoblanmaydi(tmp_path):
    """⚠️ Nomi Phase 4 fayli bilan bir xil bo'lsa ham, ildizdagi `errors.json` QONUNIY."""
    assert ERRORS_FILE in rb.REQUIRED_FILES, "nom Phase 4 da ham bor — shu bois istisno kerak"
    root = yoz(tmp_path)
    matn = muammolar(root)
    assert matn == "", matn


def test_errors_json_HOSILA_ikkinchi_manba_YOQ(tmp_path):
    """⚠️ Hujjat `agent_status.json` DAN quriladi: kirishdan kelmaydi, demak zid bo'lolmaydi."""
    paket_obj = xatoli_paket()
    birinchi = pathlib.Path(paket_obj.write(str(tmp_path / "a")))
    ikkinchi = pathlib.Path(xatoli_paket().write(str(tmp_path / "b")))
    assert (birinchi / ERRORS_FILE).read_bytes() == (ikkinchi / ERRORS_FILE).read_bytes()
    assert paket_obj.errors_json() == (birinchi / ERRORS_FILE).read_text("utf-8")


def test_errors_json_BOSH_royxat_QONUNIY(tmp_path):
    """⚠️ «Xato qayd etilmadi» QONUNIY javob — bo'sh fayl emas, BO'SH RO'YXAT."""
    root = yoz(tmp_path)          # ⚠️ `COMPLETE` yurish: xatosi yo'q
    doc = errors_doc(root)
    assert doc["errors"] == []
    rp.validate_result_package(str(root))


@pytest.mark.parametrize("kalit,qiymat", [
    ("errors_version", "binos-agent-errors-v2"),
    ("run_id", ""),
    ("generated_at", "2026-09-30"),
])
def test_errors_json_SHAKLI_buzilsa_RAD(tmp_path, kalit, qiymat):
    root = pathlib.Path(xatoli_paket().write(str(tmp_path)))
    doc = errors_doc(root)
    doc[kalit] = qiymat
    (root / ERRORS_FILE).write_text(dumps(doc), encoding="utf-8")
    assert any(ERRORS_FILE in m for m in rp.check_result_package(str(root)))


def test_errors_json_da_JSON_SONI_TAQIQ(tmp_path):
    root = pathlib.Path(xatoli_paket().write(str(tmp_path)))
    doc = errors_doc(root)
    doc["errors"][0]["detail"] = 7          # ⚠️ JSON SONI
    (root / ERRORS_FILE).write_text(dumps(doc), encoding="utf-8")
    # ⚠️ Darvoza `strict_json_loads` da ham, `_scalar_paths` da ham bor — ikkisi ham SONNI
    #    rad etadi, va matn qaysi faylda ekanini aytadi.
    matn = muammolar(root)
    assert "taqiqlangan" in matn.lower() and ERRORS_FILE in matn


def test_errors_json_kodi_BARQAROR_belgi_bolishi_SHART(tmp_path):
    root = pathlib.Path(xatoli_paket().write(str(tmp_path)))
    doc = errors_doc(root)
    doc["errors"][0]["code"] = "exe missing"     # kichik harf va probel
    (root / ERRORS_FILE).write_text(dumps(doc), encoding="utf-8")
    assert "BARQAROR belgi" in muammolar(root)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 12 · ON BIRTA YIQILISH HOLATI — HAR BIRI YAROQLI PAKET QOLDIRADI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Har bir yiqilish holatiga olib boradigan YO'L (`states.TRANSITIONS` har bir yiqilishni
#: FAQAT o'z joyidan ruxsat etadi). ⚠️ `FAILED_TIMEOUT`, `FAILED_INTERNAL` va
#: `ABORTED_BY_OPERATOR` — har qanday holatdan (`_ANY_EXIT`), shu bois ular qisqa yo'ldan
#: sinaladi.
_ENV, _TARGET, _SAFETY, _META = (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK,
                                 st.METADATA_DISCOVERY)
YIQILISH_YOLLARI: dict[str, tuple[str, ...]] = {
    st.FAILED_NO_1C: (_ENV,),
    st.FAILED_NO_TARGET: (_ENV, _TARGET),
    st.FAILED_AUTH_REQUIRED: (_ENV, _TARGET),
    st.FAILED_SAFETY: (_ENV, _TARGET, _SAFETY),
    st.FAILED_COLLECTOR_UNAVAILABLE: (_ENV, _TARGET, _SAFETY, _META),
    st.FAILED_VALIDATION: (_ENV, _TARGET, _SAFETY, _META, st.VALIDATION),
    st.FAILED_ANALYSIS: (_ENV, _TARGET, _SAFETY, _META, st.VALIDATION, st.GRAPH_BUILD),
    st.FAILED_REPORT: (_ENV, _TARGET, _SAFETY, _META, st.VALIDATION, st.GRAPH_BUILD,
                       st.ANALYSIS, st.REPORT),
    st.FAILED_TIMEOUT: (_ENV,),
    st.FAILED_INTERNAL: (_ENV,),
    st.ABORTED_BY_OPERATOR: (_ENV,),
}


def test_yiqilish_yollari_HAMMA_yiqilish_holatini_qamraydi():
    """⚠️ Ro'yxat holat mashinasidan ajralib ketmasin: ON BIRTA holat, hammasi tekshiriladi."""
    assert set(YIQILISH_YOLLARI) == set(st.FAILURE_STATES)
    assert len(YIQILISH_YOLLARI) == 11


@pytest.mark.parametrize("holat", sorted(st.FAILURE_STATES))
def test_HAR_yiqilish_holati_YAROQLI_paket_qoldiradi(tmp_path, holat):
    """⚠️⚠️ «Yiqilish paketi ham VALID paket bo'lsin»: operator UZATADIGAN narsa qolishi SHART.

    Har paketda BESH fayl: `agent_status.json`, `environment.json`, `errors.json`,
    `agent_manifest.json`, `discovery_report.md` — va `validate_result_package` dan O'TADI.
    ⚠️ `FAILED_INTERNAL` ham shu ro'yxatda: kutilmagan istisno operatorni «hech narsa
       qolmadi» holatida QOLDIRMAYDI, aks holda `failure_meaning` ning «natija papkasini
       ishlab chiquvchiga uzating» ko'rsatmasi bajarilmas bo'lib qolardi.
    ⚠️⚠️ ENDI ISTISNO UMUMAN YO'Q: chiqishda SIR topilgan yurish ham (`FAILED_REPORT`) paket
         qoldiradi — MINIMAL va SIRSIZ. Uning o'lchovi
         `test_ui_SIRLI_paket_yiqilishda_HAM_RAD_lekin_MINIMAL_PAKET_qoladi` da (va to'liq
         operator oqimi darajasida — `test_agent_e2e_watch_folder.py` ning G ssenariysida),
         chunki u YOZUVNI emas, UI QATLAMINING yo'lini o'lchaydi.
    """
    s = stat.new_run("run-0004", now=T0)
    for oraliq in YIQILISH_YOLLARI[holat]:
        s = s.advance(oraliq, now=T0)
    # ⚠️⚠️ TUZATILGAN FIKSTURA: avval `with_presence_verdict` UMUMAN chaqirilmasdi (standart
    #    — `unknown`), `env_matni()` esa `found` yozardi — ya'ni ON BIRTA yiqilish paketining
    #    HAR BIRI ichida ikki hujjat ZID edi va validator JIM qolardi (aynan shu nuqson).
    s = (s.with_environment_file(ENVIRONMENT_FILE).with_artifacts(rp.ALWAYS_FILES)
         .with_presence_verdict(env_scan().presence_verdict)
         .with_error("agent:ui", "AGENT_INTERNAL_ERROR", "sintetik sabab")
         .advance(holat, now=T0, note="sintetik fikstura"))

    root = pathlib.Path(rp.ResultPackage.from_parts(
        timestamp=TS, status_json=s.to_json(), environment_json=env_matni(),
        report_md=REPORT_MD).write(str(tmp_path)))

    rp.validate_result_package(str(root))
    assert rp.check_result_package(str(root)) == []
    assert sorted(p.name for p in root.iterdir()) == sorted(rp.ALWAYS_FILES)
    for nom in (AGENT_STATUS_FILE, ENVIRONMENT_FILE, ERRORS_FILE, AGENT_MANIFEST_FILE,
                REPORT_FILE):
        assert (root / nom).is_file(), nom
    yozuv = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    assert yozuv["state"] == holat
    # ⚠️ Paket O'Z-O'ZIGA ZID BO'LMAYDI: ikki hujjat AYNI hukmni aytadi.
    muhit_doc = json.loads((root / ENVIRONMENT_FILE).read_text("utf-8"))
    assert yozuv["presence_verdict"] == muhit_doc["presence_verdict"]
    assert not (root / BUNDLE_SUBDIR).exists(), "paket OLINMAGAN yurishda `bundle/` YO'Q"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 13 · UI: KUTILMAGAN ISTISNO HAM PAPKA QOLDIRADI
# ══════════════════════════════════════════════════════════════════════════════════════════
class BirMartaYiqiladi:
    """Berilgan holatda BIR MARTA istisno tashlaydigan progress kuzatuvchisi.

    ⚠️ NEGA SHU USUL: kutilmagan ichki xatoni TABIIY joyda (quvur o'rtasida) yuzaga
       keltiradi va ikkinchi marta yiqilmaydi — ya'ni test `_ichki_xato` ning natija
       papkasini yozishini o'lchaydi, cheksiz yiqilishni emas.
    """

    def __init__(self, holat: str, matn: str) -> None:
        self.holat = holat
        self.matn = matn
        self.yiqildi = False
        self.korilgan: list[str] = []

    def __call__(self, holat: str) -> None:
        self.korilgan.append(holat)
        if holat == self.holat and not self.yiqildi:
            self.yiqildi = True
            raise RuntimeError(self.matn)


def test_ui_KUTILMAGAN_istisno_ham_YAROQLI_paket_qoldiradi(tmp_path):
    """⚠️⚠️ `FAILED_INTERNAL` da operator «hech narsa qolmadi» holatida QOLMAYDI."""
    kuzatuvchi = BirMartaYiqiladi(st.METADATA_DISCOVERY,
                                  r"sintetik kutilmagan xato: C:\maxfiy\yol")
    manba = kuzatilgan_papka(tmp_path)
    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(manba))
    m.on_progress = kuzatuvchi
    natija = m.start()

    assert kuzatuvchi.yiqildi, "sintetik xato UMUMAN yuzaga kelmadi — test o'lchamay qoldi"
    assert natija.state == st.FAILED_INTERNAL
    assert natija.code == agent_ui.CODE_ICHKI_XATO
    assert natija.result_dir is not None, "yiqilgan yurish ham UZATILADIGAN papka qoldiradi"

    root = pathlib.Path(natija.result_dir)
    rp.validate_result_package(str(root))
    assert sorted(p.name for p in root.iterdir()) == sorted(rp.ALWAYS_FILES)
    yozuv = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    assert yozuv["state"] == st.FAILED_INTERNAL
    assert yozuv["transitions"][-1]["to"] == st.FAILED_INTERNAL
    assert agent_ui.CODE_ICHKI_XATO in [e["code"] for e in yozuv["errors"]]
    # ⚠️ Xato ro'yxati IKKI faylda MOS: `errors.json` hosila, demak zid bo'lolmaydi.
    assert errors_doc(root)["errors"] == yozuv["errors"]
    # ⚠️ Mahalliy yo'l BIRORTA faylda qolmaydi (istisno matni `redact` dan o'tadi).
    for nom in rp.ALWAYS_FILES:
        assert "maxfiy" not in (root / nom).read_text("utf-8")


def test_ui_SIRSIZ_paket_ZOND_yozuvlarini_ham_OLIB_TASHLAYDI_va_AYTADI(tmp_path):
    """⚠️ Zond yozuvi O'Z natija faylini DA'VO qiladi, fayl esa ushlab qolingan `bundle/` da.

    ⚠️⚠️ NEGA INVARIANT KERAK: paketda YO'Q faylni da'vo qiladigan yozuv paket BO'LOLMAYDI
         (`result_package._check_status_cross_refs`), ya'ni zond yozuvi qolib ketsa MINIMAL
         paket ham RAD etilardi — operator yana bo'sh qo'l bilan qolardi. Shu bois zond
         yozuvlari olib tashlanadi, LEKIN bu JIM qilinmaydi: ularning SONI tafsilotda
         qoladi («yo'q edi» va «olib tashlandi» ARALASHTIRILMAYDI).
    ⚠️ TO'G'RIDAN `_sirsiz_paket` CHAQIRILADI: zond + sir birikmasiga quvur orqali erishib
       bo'lmaydi (paketdagi sirni `VALIDATION` bosqichi zond yozuvlaridan OLDIN tutadi), lekin
       darvoza shunga ham tayyor bo'lishi kerak — fail-closed qoidasi.
    """
    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija")
    m.refresh_environment()
    run = (stat.new_run("run-0009", now=T0).with_mode(stat.MODE_APPROVED_PROBES)
           .with_environment_file(ENVIRONMENT_FILE)
           .with_presence_verdict(env_scan().presence_verdict)
           .with_bundle_dir(BUNDLE_SUBDIR)
           .with_probe(stat.ProbeRecord(no="01", probe_type="row_count",
                                        target_object="Spravochnik.Tovary",
                                        reason="sintetik fikstura", status="EXECUTED",
                                        file=f"{rb.PROBE_DIR}/01_row_count.json")))
    for holat in (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK,
                  st.METADATA_DISCOVERY, st.VALIDATION, st.FAILED_VALIDATION):
        run = run.advance(holat, now=T0)

    natija = m._sirsiz_paket(run, TS, (f"{BUNDLE_SUBDIR}/{rb.ERRORS_FILE}",),
                             rp.ResultPackageError("sintetik: [REDACTED] shubhasi"))

    assert natija.result_dir is not None, "zond yozuvi paketni YO'Q QILMAYDI"
    assert natija.code == agent_ui.CODE_SIR_USHLANDI
    rp.validate_result_package(natija.result_dir)
    yozuv = json.loads((pathlib.Path(natija.result_dir) / AGENT_STATUS_FILE)
                       .read_text("utf-8"))
    assert yozuv["probes"] == [], "yo'q faylga ishora qiladigan da'vo paketda QOLMAYDI"
    assert yozuv["bundle_dir"] is None
    assert "Zond yozuvlari ham olib tashlandi" in natija.detail, \
        "olib tashlash JIM bo'lmaydi — tafsilotda aytiladi"
    assert "soni: 1" in natija.detail, "zond BO'LGANI fakti SANOQ bilan qoladi"


def test_ui_ICHKI_XATO_MINIMAL_yozuvi_MUHIT_hujjati_bilan_ZID_EMAS(tmp_path):
    """⚠️⚠️ TUZATILGAN NUQSON: paket O'Z-O'ZIGA ZID edi.

    Oxirgi haqiqiy yozuv YAKUNLANGAN bo'lsa (yakunlangan yurish qayta tirilmaydi), ichki xato
    yo'li MINIMAL yozuv quradi. Avval bu yozuv muhit haqida HECH NARSA da'vo qilmasdi
    (`environment_file=null`, `presence_verdict` — standart `unknown`), AYNI papkadagi
    `environment.json` esa TO'LIQ skaner natijasini yozardi: bitta paketda ikki hujjat ZID
    bo'lardi va «qaysi biri haqiqat» savoli javobsiz qolardi.

    ⚠️ ENDI SHART: muhit hujjati YOZILADIGAN bo'lsa, yozuvda `environment_file` ham,
       `presence_verdict` ham MOS bo'ladi — ya'ni paketdagi ikki hujjat bir-birini TASDIQLAYDI.
    ⚠️ FIKSTURA ATAYLAB `unknown` DAN FARQLI hukm beradi: standart qiymat bilan mos kelib
       qolgan test nuqsonni UMUMAN o'lchamasdi.
    """
    kuzatuvchi = BirMartaYiqiladi(st.COMPLETE, "sintetik kutilmagan xato: yakunda")
    manba = kuzatilgan_papka(tmp_path)
    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(manba))
    m.on_progress = kuzatuvchi
    natija = m.start()

    assert kuzatuvchi.yiqildi, "sintetik xato UMUMAN yuzaga kelmadi — test o'lchamay qoldi"
    assert natija.state == st.FAILED_INTERNAL
    assert natija.result_dir is not None, "yiqilgan yurish ham UZATILADIGAN papka qoldiradi"
    root = pathlib.Path(natija.result_dir)
    rp.validate_result_package(str(root))

    yozuv = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    assert yozuv["state"] == st.FAILED_INTERNAL
    # ⚠️ Yozuv HAQIQATAN minimal: to'liq quvur zanjiri unda YO'Q (va buni izoh aytadi).
    assert [t["to"] for t in yozuv["transitions"]] == [st.ENVIRONMENT_SCAN, st.FAILED_INTERNAL]
    assert any("MINIMAL" in n for n in yozuv["notes"]), "yozuvning minimalligi OCHIQ aytiladi"

    # ── IKKI HUJJAT BIR-BIRIGA MOS ───────────────────────────────────────────────────────
    assert (root / ENVIRONMENT_FILE).is_file(), "muhit hujjati YOZILGAN"
    assert yozuv["environment_file"] == ENVIRONMENT_FILE, \
        "muhit hujjati yozilgan bo'lsa, yozuv ham uni DA'VO qiladi"
    kutilgan = env_scan().presence_verdict
    assert kutilgan != det.PRESENCE_UNKNOWN, "fikstura standart qiymat bilan mos kelmasin"
    assert yozuv["presence_verdict"] == kutilgan, \
        "hukm skanerdan keladi — yozuv muhit hujjati bilan ZID bo'lolmaydi"


def test_ui_SKANER_IKKINCHI_marta_yiqilsa_ham_IKKI_hujjat_MOS_qoladi(tmp_path):
    """⚠️⚠️ IKKINCHI SHOX (oxirgi yozuv YAKUNLANMAGAN): istisno `refresh_environment` ning
         ICHIDA bo'lsa ham `environment.json` YOZILADI — chunki oyna ochilganda skanerlangan
         natija qo'lda qolgan. Yozuv shu hujjatni DA'VO qilmasa, «papkada hujjat bor, yozuv
         uni da'vo qilmaydi» degan nuqson BUTUN paketni rad etardi va operator ENG MUHIM
         yiqilishda yana «hech narsa qolmadi» holatida qolardi.

    ⚠️ FIKSTURA: skaner BIRINCHI marta ishlaydi (oyna ochilishi), IKKINCHI marta yiqiladi
       («Start Discovery»). Shunda `self.environment` to'ldirilgan, yurish yozuvi esa
       `environment_file` ni hali yozmagan — AYNAN shu oraliq.
    """
    urinishlar = {"soni": 0}

    def ikki_marta_chaqiriladigan_skaner():
        urinishlar["soni"] += 1
        if urinishlar["soni"] == 1:
            return env_scan()
        raise RuntimeError(r"sintetik ikkinchi skaner xatosi: C:\maxfiy\reestr")

    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(kuzatilgan_papka(tmp_path)),
              scan=ikki_marta_chaqiriladigan_skaner)
    m.refresh_environment()
    natija = m.start()

    assert urinishlar["soni"] == 2, "fikstura ikkinchi skanerni UMUMAN chaqirmadi"
    assert natija.state == st.FAILED_INTERNAL
    assert natija.result_dir is not None, "muhit hujjati bor — paket ham BO'LISHI kerak"
    root = pathlib.Path(natija.result_dir)
    rp.validate_result_package(str(root))
    yozuv = json.loads((root / AGENT_STATUS_FILE).read_text("utf-8"))
    assert yozuv["environment_file"] == ENVIRONMENT_FILE
    assert yozuv["presence_verdict"] == env_scan().presence_verdict, \
        "yozuvdagi hukm AYNI yozilgan muhit hujjatidan keladi"
    assert "maxfiy" not in papka_matni(root), "istisno matni `redact` dan o'tadi"


def papka_matni(root) -> str:
    """Papkadagi HAMMA ildiz artefaktining matni bitta blokda (qidirish uchun)."""
    return "".join((pathlib.Path(root) / n).read_text("utf-8") for n in rp.ALWAYS_FILES)


def test_ui_MUHIT_SKANERI_yiqilsa_PAPKA_umuman_yozilmaydi(tmp_path):
    """⚠️⚠️ ANIQ CHEGARA: skaner yiqilsa `environment.json` uchun HALOL mazmun YO'Q.

    To'qima «bo'sh muhit» hujjati «qaradim va 1C yo'q» degan YOLG'ON hukm bo'lib o'qilardi,
    shu bois papka UMUMAN yozilmaydi. ⚠️ Bu bo'shliq emas, TANLOV — va u ENDI ANIQ
    tekshiriladi (`det.dump_document(None)` ning tasodifiy istisnosiga tayanmaydi).
    """
    def yiqiladigan_skaner():
        raise RuntimeError(r"sintetik skaner xatosi: C:\maxfiy\reestr")

    (tmp_path / "natija").mkdir()
    m = model(tmp_path / "natija", bundle_dir=str(kuzatilgan_papka(tmp_path)),
              scan=yiqiladigan_skaner)
    natija = m.start()
    assert natija.state == st.FAILED_INTERNAL
    assert natija.code == agent_ui.CODE_ICHKI_XATO
    assert natija.result_dir is None, "muhit hujjati uchun halol mazmun yo'q — papka ham yo'q"
    assert list((tmp_path / "natija").iterdir()) == []
    assert "maxfiy" not in natija.detail, "istisno matni `redact` dan o'tadi"
